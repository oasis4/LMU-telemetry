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
from ..core.trace import LapTrace, TraceError
from .decimate import TARGET_POINTS, decimate
from .pool import SessionPool

#: The arrays a cached lap trace consists of, in the order LapTrace takes them.
_TRACE_ARRAYS = ("grid", "time_s", "speed_kmh", "throttle", "brake")


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
    sessions = pool if pool is not None else SessionPool()
    cache_root = Path(cache_dir) if cache_dir else Path(".cache") / "traces"
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

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "recordings_dir": str(root), "open_sessions": len(sessions)}

    def _summary(path: Path) -> dict:
        """One recording's headline facts, from cache when it has them.

        Counting the usable laps costs the whole geometry pipeline for every
        lap of the recording. Over 78 recordings that measured 9.3 s - on the
        page a user lands on. It depends only on the recording, so it is
        cached under the same (path, mtime, size) key as everything else.
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
            if cached is not None:
                summary_memo[key] = cached
                return cached

        session = sessions.get(path)
        info = session.info
        fastest = session.fastest_lap
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
            "clean_laps": len(clean_laps(session)),
            "fastest_lap_s": None if fastest is None else round(fastest.duration_s, 3),
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
        session = _open(name)
        model = sessions.model_for(session)
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
        session = _open(name)
        model = sessions.model_for(session)
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
            trace = build_trace(session, lap, model.track_length_m)
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
        }
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
        }
        sent = series if full else decimate(series, by="delta_s")
        return {
            "reference": {"name": reference, "lap": reference_lap,
                          "duration_s": round(a.lap.duration_s, 3)},
            "other": {"name": other, "lap": other_lap,
                      "duration_s": round(b.lap.duration_s, 3)},
            "lap_delta_s": round(float(delta[-1]), 3),
            "resolution": "full" if full else f"~{TARGET_POINTS} points",
            "samples": len(sent["distance_m"]),
            "series": {k: _series(v) for k, v in sent.items()},
            "corners": [{
                "index": c.corner.index,
                "name": c.corner.name,
                "start_m": round(c.corner.start_m, 1),
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
        "entry_speed_kmh": round(metrics.entry_speed_kmh, 1),
        "min_speed_kmh": round(metrics.min_speed_kmh, 1),
        "min_speed_at_m": round(metrics.min_speed_at_m, 1),
        "throttle_point_m": None if metrics.throttle_point_m is None
        else round(metrics.throttle_point_m, 1),
        "exit_speed_kmh": round(metrics.exit_speed_kmh, 1),
        "time_s": round(metrics.time_s, 3),
    }
