"""The HTTP surface.

Two rules run through every route here, and both come from what went wrong
before.

**One corner list per comparison.** A comparison names two laps and gets back
one list of corners with both drivers measured against it. The old server
offered ``/api/corners/{session}``, so the client fetched a list per side and
compared two drivers against two different definitions of the same corner.
There is deliberately no per-session corner route to make that possible again.

**Decimated unless asked otherwise.** A response carries about 1500 points per
series by default and says so in ``resolution``. Full resolution is available
with ``?full=true`` for a zoomed view or a corner detail, but it is not what
an overview costs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from ..cache.store import ArrayCache, CacheError, SummaryCache, source_key
from ..core import Session, build_trace, clean_laps, compare_corners, delta_s
from ..core.coaching import advice
from ..core.metrics import BRAKE_ON, braking_zones
from ..core.trace import LapTrace, TraceError
from .decimate import TARGET_POINTS, decimate
from .pool import SessionPool

#: The arrays a cached lap trace consists of, in the order LapTrace takes them.
_TRACE_ARRAYS = (
    "grid", "time_s", "speed_kmh", "throttle", "brake", "steering", "x", "y"
)


def corner_spans(
    start_m: float, end_m: float, kept_m: np.ndarray, track_length_m: float
) -> "list[list[int]]":
    """A corner's extent as index ranges into the points that were sent.

    A corner containing the start/finish line has ``start_m > end_m`` and comes
    back as two ranges - the run to the line and the run away from it. Read as
    one range it is empty, and the corner disappears from the map without
    anything saying so. No circuit in the working set has one (all four of the
    original tracks start on a straight), which is why this is a function that
    can be tested rather than a branch inside the route.
    """
    edges = (
        [(start_m, end_m)]
        if start_m <= end_m
        else [(start_m, track_length_m), (0.0, end_m)]
    )
    out = []
    for first_m, last_m in edges:
        first = int(np.searchsorted(kept_m, first_m, side="left"))
        last = int(np.searchsorted(kept_m, last_m, side="right"))
        first = min(first, len(kept_m) - 1)
        out.append([first, min(max(last, first + 1), len(kept_m))])
    return out


def path_stride(n_samples: int, target_points: int = TARGET_POINTS) -> int:
    """How many samples to skip when thinning a path to *target_points*.

    A path is thinned by taking every nth point, not by ``decimate``. That one
    keeps the minimum and maximum of each bucket, which is right for a signal
    where a spike must survive - but a path has two coordinates and only one
    can drive the choice. Keeping the x-extremes of a bucket and dropping its
    y-extremes does not preserve a shape, it distorts it.

    The line is already sampled evenly, every 2 m of track, so every nth point
    is evenly spaced too and the thinned path is the same shape at lower
    resolution.
    """
    if n_samples <= target_points:
        return 1
    return max(1, -(-n_samples // target_points))


def _series(values: np.ndarray, digits: int = 3) -> list[float]:
    """A numpy array as JSON numbers, rounded to what the reading supports.

    Speed is recorded to about 0.01 km/h and distance to centimetres, so the
    17 significant digits a float64 serialises to are noise that costs bytes.
    """
    return [round(float(v), digits) for v in values]


def create_app(
    recordings_dir: "str | Path | None" = None,
    pool: "SessionPool | None" = None,
    cache_dir: "str | Path | None" = None,
) -> FastAPI:
    """Build the application. *recordings_dir* is where sessions are read from."""
    root = Path(recordings_dir) if recordings_dir else Path("data") / "sessions"
    cache_root = Path(cache_dir) if cache_dir else Path(".cache") / "traces"
    sessions = pool if pool is not None else SessionPool(
        model_cache_dir=cache_root / "models"
    )
    cache = ArrayCache(cache_root)
    summaries = SummaryCache(cache_root)
    # Keyed on (path, mtime, size) like the disk cache, so a replaced recording
    # gets a new key and this never serves the old one. Reading 78 small JSON
    # files still took 2.5 s on Windows; this is what makes the listing free
    # after the first request in a process.
    summary_memo: "dict[str, dict]" = {}

    app = FastAPI(title="LMU Telemetry", version="2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.recordings_dir = root
    app.state.pool = sessions

    def _resolve(name: str) -> Path:
        """The recording called *name*, refusing anything outside the root.

        The name arrives from the client, so it is untrusted: without this a
        request for ``../../etc/passwd`` would be answered.
        """
        candidate = (root / name).resolve()
        if root.resolve() not in candidate.parents:
            raise HTTPException(400, f"{name!r} is not inside the recordings directory")
        if not candidate.is_file():
            raise HTTPException(404, f"no recording called {name!r}")
        return candidate

    def _open(name: str) -> Session:
        try:
            return sessions.get(_resolve(name))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - the client gets the reason
            raise HTTPException(422, f"{name!r} cannot be read: {exc}") from exc

    def _siblings_of(path: Path) -> "list[Path]":
        """Recordings of the same circuit as the one at *path*.

        A track's geometry is measured from every clean lap of that circuit,
        not from the one session being viewed: the curated corner names are
        applied all-or-nothing and are dropped when too few laps let the
        detected apexes drift, so a model built from one short session comes
        back as T1..Tn.

        The pool would sift the whole directory itself, but that means opening
        all 78 recordings - 16.7 s measured on the first request. The cached
        summaries already know each one's track and layout, so they do the
        filtering and only the same circuit's recordings are opened.

        This takes a path rather than an open session on purpose. Reading the
        summaries opens whatever is not cached yet, which churns the pool and
        evicts up to its whole contents - an open session handed in here would
        be closed underneath the caller before it got used.
        """
        if not root.is_dir():
            return []
        try:
            own = _summary(path)
        except Exception:  # noqa: BLE001 - nothing to match against
            return [path]
        found = []
        for candidate in sorted(root.glob("*.duckdb")):
            try:
                summary = _summary(candidate)
            except Exception:  # noqa: BLE001 - an unreadable one cannot contribute
                continue
            if (summary.get("track"), summary.get("layout")) == (
                own.get("track"),
                own.get("layout"),
            ):
                found.append(candidate)
        return found

    def _model_for(name: str):
        """The circuit behind *name*, and the open session it was asked about.

        The sibling list is built first and the session opened after, because
        building it churns the pool.
        """
        siblings = _siblings_of(_resolve(name))
        session = _open(name)
        return session, sessions.model_for(session, siblings)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "recordings_dir": str(root), "open_sessions": len(sessions)}

    def _summary(path: Path) -> dict:
        """One recording's headline facts, from cache when it has them.

        Counting the usable laps costs the whole geometry pipeline for every
        lap of the recording. Over 78 recordings that measured 9.3 s - on the
        page a user lands on. It depends only on the recording, so it is
        cached under the same (path, mtime, size) key as everything else.

        An entry written before ``best_lap`` existed is treated as absent
        rather than migrated. Bumping ``CACHE_FORMAT_VERSION`` would say the
        same thing, but that key is shared with the resampled traces, and
        those are unaffected by this - it would throw away several minutes of
        correct work to add one field.
        """
        try:
            key = source_key(path)
        except OSError:
            key = None
        if key is not None:
            remembered = summary_memo.get(key)
            if remembered is not None:
                return remembered
            cached = summaries.load(key, "session")
            if cached is not None and "best_lap" in cached:
                summary_memo[key] = cached
                return cached

        session = sessions.get(path)
        info = session.info
        # The quickest *usable* lap, not the quickest lap. The headline time
        # is what a lap gets chosen by, so a recording that advertises one the
        # comparison then refuses is advertising a lap that cannot be opened.
        # Four of the 78 working-set recordings differ on this: Monza practice
        # offers 1:42.10 for a lap the game itself recorded no time for.
        usable = clean_laps(session)
        best = min(usable, key=lambda l: l.duration_s) if usable else None
        summary = {
            "name": path.name,
            "track": info.track,
            "layout": info.layout,
            "car": info.car,
            "car_class": info.car_class,
            "driver": info.driver,
            "session_type": info.session_type,
            "recorded_at": info.recorded_at,
            "track_length_m": session.track_length_m,
            "laps": len(session.laps),
            "clean_laps": len(usable),
            "best_lap": None if best is None else best.number,
            "best_lap_s": None if best is None else round(best.duration_s, 3),
        }
        if key is not None:
            summary_memo[key] = summary
            try:
                summaries.store(key, "session", summary)
            except CacheError:
                pass
        return summary

    @app.get("/api/sessions")
    def list_sessions() -> dict:
        """Every recording, with what it is and how much of it is usable."""
        found = []
        for path in sorted(root.glob("*.duckdb")) if root.is_dir() else []:
            try:
                found.append(_summary(path))
            except Exception as exc:  # noqa: BLE001 - listed with its reason
                found.append({"name": path.name, "error": str(exc)})
        return {"sessions": found}

    @app.get("/api/sessions/{name}/laps")
    def list_laps(name: str) -> dict:
        """Every lap, with why an unusable one was excluded.

        A lap dropped without a stated reason is indistinguishable from a bug,
        so the reason travels with it rather than being filtered out here.
        """
        from ..core.quality import assess_lap

        session = _open(name)
        laps = []
        for lap in session.laps:
            quality = assess_lap(session, lap)
            laps.append({
                "number": lap.number,
                "duration_s": round(lap.duration_s, 3),
                "recorded_time_s": lap.recorded_time_s,
                "sectors_s": None if lap.sectors_s is None
                else [round(s, 3) for s in lap.sectors_s],
                "touched_pits": lap.touched_pits,
                "distance_m": round(lap.distance_m, 1),
                "clean": quality.is_clean,
                "reason": quality.reason,
            })
        return {"name": name, "laps": laps}

    @app.get("/api/sessions/{name}/track")
    def track_model(name: str) -> dict:
        """The circuit: its corners, built once per track identity."""
        session, model = _model_for(name)
        if model is None:
            raise HTTPException(422, f"no clean lap in {name!r} to measure the track from")
        return {
            "track": model.key.track,
            "layout": model.key.layout,
            "track_length_m": round(model.track_length_m, 1),
            "closure_deg": round(model.closure_deg, 2),
            "lap_count": model.lap_count,
            "confident": model.confident,
            "warning": model.warning,
            "corners": [{
                "index": c.index,
                "name": c.name,
                "start_m": round(c.start_m, 1),
                "apex_m": round(c.apex_m, 1),
                "end_m": round(c.end_m, 1),
                "radius_m": round(c.radius_m, 1),
                "heading_deg": round(c.heading_deg, 1),
                "direction": c.direction,
                "wraps": c.start_m > c.end_m,
            } for c in model.corners],
        }

    @app.get("/api/sessions/{name}/map")
    def track_map(
        name: str,
        full: bool = Query(False, description="send every point instead of ~1500"),
    ) -> dict:
        """The circuit's shape, as measured, with each corner's span on it.

        The line is the median racing line the corners were detected on - not
        a shape reconstructed from their radii and headings, which would draw
        what the detector believed rather than where the car went, and would
        then agree with the corner list however wrong both were.

        Corners are given as index ranges into the line, so the client marks
        them by slicing rather than by matching distances back to points. A
        corner that contains the start/finish line comes as two ranges.
        """
        session, model = _model_for(name)
        if model is None:
            raise HTTPException(422, f"no clean lap in {name!r} to measure the track from")
        if model.line_x is None or model.line_y is None:
            raise HTTPException(
                422, f"the cached model for {name!r} predates the reference line"
            )

        step_m = model.track_length_m / len(model.line_x)
        stride = 1 if full else path_stride(len(model.line_x))
        kept = np.arange(0, len(model.line_x), stride)
        sent_x, sent_y = model.line_x[kept], model.line_y[kept]
        # A corner's span is given as indices into what was actually sent, so
        # the client marks it by slicing rather than by matching distances
        # back to points.
        kept_m = kept * step_m

        return {
            "track": model.key.track,
            "layout": model.key.layout,
            "track_length_m": round(model.track_length_m, 1),
            "resolution": "full" if full else f"every {stride} of {len(model.line_x)} points",
            "samples": len(sent_x),
            "x": _series(sent_x, 2),
            "y": _series(sent_y, 2),
            "corners": [
                {
                    "index": c.index,
                    "name": c.name,
                    "direction": c.direction,
                    "apex_m": round(c.apex_m, 1),
                    "spans": corner_spans(
                        c.start_m, c.end_m, kept_m, model.track_length_m
                    ),
                }
                for c in model.corners
            ],
        }

    def _trace_for(name: str, lap_number: int):
        """The lap on the grid, from disk if it has been built before.

        Resampling a lap is the expensive half of answering a request, and the
        result depends only on the recording. So it is written once, keyed on
        the recording's identity, and read back afterwards - which is what
        makes looking at the same session again a file read rather than a
        recomputation. A cache that cannot be written is not an error: the
        answer is the same either way, only slower.
        """
        path = _resolve(name)
        session, model = _model_for(name)
        if model is None:
            raise HTTPException(422, f"no clean lap in {name!r} to measure the track from")
        lap = next((l for l in session.laps if l.number == lap_number), None)
        if lap is None:
            raise HTTPException(404, f"{name!r} has no lap {lap_number}")

        kind = f"trace-lap{lap_number}"
        try:
            key = source_key(path)
        except OSError:
            key = None

        if key is not None:
            stored = cache.load(key, kind)
            if stored is not None and all(n in stored for n in _TRACE_ARRAYS):
                return session, model, LapTrace(
                    lap=lap, **{n: stored[n] for n in _TRACE_ARRAYS}
                )

        try:
            trace = build_trace(
                session, lap, model.track_length_m, origin=model.origin
            )
        except TraceError as exc:
            raise HTTPException(422, str(exc)) from exc

        if key is not None:
            try:
                cache.store(key, kind, {n: getattr(trace, n) for n in _TRACE_ARRAYS})
            except CacheError:
                pass
        return session, model, trace

    @app.get("/api/sessions/{name}/laps/{lap_number}/trace")
    def lap_trace(
        name: str,
        lap_number: int,
        full: bool = Query(False, description="send every sample instead of ~1500"),
    ) -> dict:
        _session, _model, trace = _trace_for(name, lap_number)
        series = {
            "distance_m": trace.grid,
            "time_s": trace.time_s,
            "speed_kmh": trace.speed_kmh,
            "throttle": trace.throttle,
            "brake": trace.brake,
            "steering": trace.steering,
        }
        # Where the car was, in the circuit's own frame, so a lap can be drawn
        # on the same map as the reference line rather than beside it.
        if trace.x is not None and trace.y is not None:
            series["x"] = trace.x
            series["y"] = trace.y
        sent = series if full else decimate(series, by="speed_kmh")
        return {
            "name": name,
            "lap": lap_number,
            "resolution": "full" if full else f"~{TARGET_POINTS} points",
            "samples": len(sent["distance_m"]),
            "series": {k: _series(v) for k, v in sent.items()},
        }

    @app.get("/api/compare")
    def compare(
        reference: str = Query(..., description="recording holding the reference lap"),
        reference_lap: int = Query(...),
        other: str = Query(..., description="recording holding the compared lap"),
        other_lap: int = Query(...),
        full: bool = Query(False),
    ) -> dict:
        """Two laps against one corner list and one distance grid."""
        _s1, model, a = _trace_for(reference, reference_lap)
        _s2, other_model, b = _trace_for(other, other_lap)

        if (model.key.track, model.key.layout) != (
            other_model.key.track, other_model.key.layout
        ):
            raise HTTPException(
                422,
                f"{model.key.track} / {model.key.layout} and {other_model.key.track} "
                f"/ {other_model.key.layout} are different circuits",
            )

        delta = delta_s(a, b)
        comparisons = compare_corners(a, b, model.corners)
        series = {
            "distance_m": a.grid,
            "delta_s": delta,
            "speed_reference_kmh": a.speed_kmh,
            "speed_other_kmh": b.speed_kmh,
            "brake_reference": a.brake,
            "brake_other": b.brake,
            "throttle_reference": a.throttle,
            "throttle_other": b.throttle,
            "steering_reference": a.steering,
            "steering_other": b.steering,
        }
        sent = series if full else decimate(series, by="delta_s")
        return {
            "reference": {"name": reference, "lap": reference_lap,
                          "duration_s": round(a.lap.duration_s, 3)},
            "other": {"name": other, "lap": other_lap,
                      "duration_s": round(b.lap.duration_s, 3)},
            "lap_delta_s": round(float(delta[-1]), 3),
            # The pedal pressure above which the car is braking. Sent rather
            # than repeated in the client: the brake points in `corners` are
            # found with this number, so a client drawing braking with a
            # different one would shade a stretch that disagrees with the
            # figure printed beside it.
            "brake_on": BRAKE_ON,
            # Where each lap was on the brakes, as (from, to) in metres.
            # Measured on the full trace even when the series below are
            # decimated: decimation keeps the samples where the delta turns,
            # so a short brush of the brakes can fall between two kept samples
            # and disappear from a map drawn client-side.
            "braking": {
                "reference": [
                    [round(a, 1), round(b, 1)] for a, b in braking_zones(a)
                ],
                "other": [
                    [round(a, 1), round(b, 1)] for a, b in braking_zones(b)
                ],
            },
            "resolution": "full" if full else f"~{TARGET_POINTS} points",
            "samples": len(sent["distance_m"]),
            "series": {k: _series(v) for k, v in sent.items()},
            "advice": [
                {
                    "corner": tip.corner.index,
                    "name": tip.corner.name,
                    "headline": tip.headline,
                    "detail": tip.detail,
                    "because": tip.because,
                    "lost_s": round(tip.lost_s, 3),
                }
                for tip in advice(comparisons)
            ],
            "corners": [{
                "index": c.corner.index,
                "name": c.corner.name,
                "start_m": round(c.corner.start_m, 1),
                # The apex travels with the corner's other two distances. The
                # corner map marks it, and looking it up from a second route
                # would be matching two lists by index again - the thing this
                # server has no per-session corner route in order to prevent.
                "apex_m": round(c.corner.apex_m, 1),
                "end_m": round(c.corner.end_m, 1),
                "lost_s": round(c.lost_s, 3),
                "summary": c.summary,
                "differences": [
                    {"what": d.what, "amount": round(d.amount, 1), "unit": d.unit}
                    for d in c.differences
                ],
                "reference": _corner_metrics(c.reference),
                "other": _corner_metrics(c.other),
            } for c in comparisons],
        }

    return app


def _corner_metrics(metrics) -> dict:
    return {
        "brake_point_m": None if metrics.brake_point_m is None
        else round(metrics.brake_point_m, 1),
        "brake_peak_m": None if metrics.brake_peak_m is None
        else round(metrics.brake_peak_m, 1),
        "brake_release_m": None if metrics.brake_release_m is None
        else round(metrics.brake_release_m, 1),
        "trail_length_m": None if metrics.trail_length_m is None
        else round(metrics.trail_length_m, 1),
        "entry_speed_kmh": round(metrics.entry_speed_kmh, 1),
        "min_speed_kmh": round(metrics.min_speed_kmh, 1),
        "min_speed_at_m": round(metrics.min_speed_at_m, 1),
        "throttle_point_m": None if metrics.throttle_point_m is None
        else round(metrics.throttle_point_m, 1),
        "exit_speed_kmh": round(metrics.exit_speed_kmh, 1),
        "time_s": round(metrics.time_s, 3),
    }
