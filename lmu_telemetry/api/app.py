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

import hashlib
import re
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..cache.store import ArrayCache, CacheError, SummaryCache, source_key
from ..core import (
    Session, build_trace, clean_laps, compare_corners, delta_s, ideal_lap
)
from ..core.blocks import SEAM_SPEED_KMH
from ..core.coaching import advice
from ..core.metrics import BRAKE_ON, braking_zones
from ..core.trace import LapTrace, TraceError
from ..recordings import default_recordings_dir
from ..sharing.library import SharingLibrary, state_dir
from ..sharing.package import SharedLap, align_trace
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


class SharingSettings(BaseModel):
    publish_dir: str
    public_url: str = ""


class FriendSettings(BaseModel):
    name: str
    url: str


def create_app(
    recordings_dir: "str | Path | None" = None,
    pool: "SessionPool | None" = None,
    cache_dir: "str | Path | None" = None,
    frontend_dir: "str | Path | None" = None,
    sharing_dir: "str | Path | None" = None,
    sharing_provider=None,
) -> FastAPI:
    """Build the application. *recordings_dir* is where sessions are read from."""
    root = Path(recordings_dir) if recordings_dir else default_recordings_dir()
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

    sharing = SharingLibrary(Path(sharing_dir) if sharing_dir else state_dir() / "sharing", sharing_provider)

    @asynccontextmanager
    async def lifespan(app):
        sharing.start()
        try:
            yield
        finally:
            sharing.close()

    app = FastAPI(title="LMU Telemetry", version="2.0", lifespan=lifespan)
    app.state.sharing = sharing
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    @app.middleware("http")
    async def sharing_origin_guard(request: Request, call_next):
        # A browser may send a simple cross-origin POST even when CORS prevents
        # reading its response. Reject those before publishing or starting sync.
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            own_origin = f"{request.url.scheme}://{request.url.netloc}"
            if origin and origin not in {own_origin, "http://localhost:5173", "http://127.0.0.1:5173"}:
                return JSONResponse({"detail": "Sharing changes must come from the analyzer interface"}, status_code=403)
        return await call_next(request)

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
        if _is_shared(name):
            shared = _shared(name)
            return shared, shared.model
        siblings = _siblings_of(_resolve(name))
        session = _open(name)
        return session, sessions.model_for(session, siblings)

    def _is_shared(name):
        return re.fullmatch(r"shared-[a-f0-9]{64}", name) is not None

    def _shared(name):
        try:
            return sharing.get(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def _sharing_action(action, *args):
        try:
            return action(*args)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/sharing")
    def sharing_status():
        return sharing.snapshot()

    @app.get("/api/sharing/library")
    def shared_library():
        return {"sessions": sharing.summaries()}

    @app.put("/api/sharing/settings")
    def sharing_settings(body: SharingSettings):
        _sharing_action(sharing.settings, body.publish_dir, body.public_url)
        return sharing.snapshot()["settings"]

    @app.post("/api/sharing/friends")
    def add_friend(body: FriendSettings):
        friend = _sharing_action(sharing.add_friend, body.name, body.url)
        sharing.request_sync(friend["id"])
        return friend

    @app.delete("/api/sharing/friends/{identity}")
    def remove_friend(identity: str):
        _sharing_action(sharing.remove_friend, identity)
        return {"ok": True}

    @app.post("/api/sharing/sync")
    def sync_all():
        return {"started": sharing.request_sync()}

    @app.post("/api/sharing/friends/{identity}/sync")
    def sync_friend(identity: str):
        return {"started": _sharing_action(sharing.request_sync, identity)}

    @app.post("/api/sessions/{name}/laps/{lap_number}/share")
    def share_lap(name: str, lap_number: int):
        if _is_shared(name):
            raise HTTPException(422, "Only your recorded laps can be published")
        session = _open(name)
        lap = next((lap for lap in clean_laps(session) if lap.number == lap_number), None)
        if lap is None:
            raise HTTPException(422, "Only usable recorded laps can be shared")
        session, model, trace = _trace_for(name, lap_number)
        # Hash source content, not a machine-specific path or modification time.
        digest = hashlib.sha256()
        with _resolve(name).open("rb") as recording:
            for block in iter(lambda: recording.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(f":lap:{lap_number}".encode())
        shared = SharedLap(digest.hexdigest(), session.info, model, trace)
        return _sharing_action(sharing.publish, shared, name)

    @app.delete("/api/sharing/published/{identity}")
    def stop_sharing(identity: str):
        _sharing_action(sharing.unpublish, identity)
        return {"ok": True}

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
        return {"sessions": found + sharing.summaries()}

    @app.get("/api/sessions/{name}/laps")
    def list_laps(name: str) -> dict:
        """Every lap, with why an unusable one was excluded.

        A lap dropped without a stated reason is indistinguishable from a bug,
        so the reason travels with it rather than being filtered out here.
        """
        from ..core.quality import assess_lap

        if _is_shared(name):
            lap = _shared(name).trace.lap
            return {"name": name, "laps": [dict(asdict(lap), clean=True, reason=None)]}
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
        if _is_shared(name):
            shared = _shared(name)
            if shared.trace.lap.number != lap_number:
                raise HTTPException(404, "Shared lap number not found")
            return shared, shared.model, shared.trace
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

    @app.get("/api/sessions/{name}/ideal")
    def ideal(name: str) -> dict:
        """The best lap that could be assembled from this recording's laps.

        One recording, because `ideal_lap` requires it: two recordings mean two
        fuel loads and two tyre states, and a block time from one is not
        comparable to a block time from the other.
        """
        session, model = _model_for(name)
        if model is None:
            raise HTTPException(
                422, f"no clean lap in {name!r} to measure the track from"
            )
        if _is_shared(name):
            raise HTTPException(422, "Ideal laps require a local recording")
        usable = clean_laps(session)
        if len(usable) < 2:
            raise HTTPException(
                422,
                f"{name!r} has {len(usable)} usable lap of {len(session.laps)}. "
                f"An ideal lap is assembled from several, so it needs at least "
                f"two to choose between.",
            )
        try:
            traces = [
                build_trace(session, lap, model.track_length_m, origin=model.origin)
                for lap in usable
            ]
        except TraceError as exc:
            raise HTTPException(422, str(exc)) from exc
        built = ideal_lap(traces, model.corners)
        return {
            "name": name,
            "track": model.key.track,
            "laps_used": [lap.number for lap in usable],
            "ideal_s": round(built.ideal_s, 3),
            "best_lap_s": round(built.best_lap_s, 3),
            "best_lap_number": built.best_lap_number,
            "gain_s": round(built.gain_s, 3),
            "sound": built.sound,
            "blocks": [{
                "index": choice.block.index,
                "name": choice.block.name,
                "corners": [c.index for c in choice.block.corners],
                "start_m": round(choice.block.start_m, 1),
                "end_m": round(choice.block.end_m, 1),
                "wraps": choice.block.start_m > choice.block.end_m,
                "lap_number": choice.lap_number,
                "time_s": round(choice.time_s, 3),
                "gain_s": round(choice.gain_s, 3),
            } for choice in built.blocks],
            "seams": [{
                "at_m": round(seam.at_m, 1),
                "speed_spread_kmh": round(seam.speed_spread_kmh, 1),
                "sound": seam.sound,
            } for seam in built.seams],
            # Sent rather than repeated client-side: the flags above are
            # computed with it, so a client with its own copy would one day
            # mark a threshold that disagrees with them.
            "seam_limit_kmh": SEAM_SPEED_KMH,
        }

    @app.get("/api/sessions/{name}/laps/{lap_number}/trace")
    def lap_trace(
        name: str,
        lap_number: int,
        full: bool = Query(False, description="send every sample instead of ~1500"),
        reference: str | None = Query(None, description="align onto this recording or shared lap's track model"),
    ) -> dict:
        _session, _model, trace = _trace_for(name, lap_number)
        if reference is not None:
            _, target_model = _model_for(reference)
            if target_model is None:
                raise HTTPException(422, "Reference track model is unavailable")
            try:
                trace = align_trace(trace, _model, target_model)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
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

        if _is_shared(reference) or _is_shared(other):
            try:
                b = align_trace(b, other_model, model)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
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
            "reference": {"name": reference, "display_name": sharing.label(reference) if _is_shared(reference) else reference, "lap": reference_lap,
                          "duration_s": round(a.lap.duration_s, 3)},
            "other": {"name": other, "display_name": sharing.label(other) if _is_shared(other) else other, "lap": other_lap,
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

    if frontend_dir is not None:
        web_root = Path(frontend_dir).resolve()
        if not (web_root / "index.html").is_file():
            raise ValueError(f"Built frontend missing at {web_root}")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Not Found")
            candidate = (web_root / path).resolve()
            if not candidate.is_relative_to(web_root):
                raise HTTPException(404, "Not Found")
            if candidate.is_file():
                return FileResponse(candidate)
            if path in ("", "ideal", "recordings", "sharing"):
                return FileResponse(web_root / "index.html")
            raise HTTPException(404, "Not Found")

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
