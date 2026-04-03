"""LMU Telemetry Analyzer — FastAPI backend.

Provides REST endpoints for session listing, lap data, telemetry traces,
corner detection, time-delta computation, and multi-driver corner comparison.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .corner_detector import detect_corners
from .delta_calc import compute_delta
from .duckdb_reader import DuckDBSession
from .lap_processor import LapProcessor, LapData
from .models import (
    ChannelsResponse,
    CompareResponse,
    Corner as CornerModel,
    CornerComparison,
    CornersResponse,
    DeltaResponse,
    DriverCornerMetrics,
    LapListResponse,
    LapSummary,
    LoadedSessionInfo,
    SectorTimes,
    SessionInfo,
    TelemetryData,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="LMU Telemetry Analyzer", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEMETRY_DIR = os.environ.get("TELEMETRY_DIR", str(Path(__file__).resolve().parent.parent / "data"))

# Ensure the telemetry directory exists
Path(TELEMETRY_DIR).mkdir(parents=True, exist_ok=True)

# In-memory session store:  session_id → (DuckDBSession, LapProcessor, driver_name)
_sessions: dict[str, tuple[DuckDBSession, LapProcessor, str]] = {}


def _get_session(session_id: str) -> tuple[DuckDBSession, LapProcessor, str]:
    if session_id not in _sessions:
        raise HTTPException(404, f"Session '{session_id}' not loaded.")
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/sessions", response_model=list[SessionInfo])
def list_sessions():
    """List all .duckdb files found in ``TELEMETRY_DIR``."""
    tdir = Path(TELEMETRY_DIR)
    if not tdir.is_dir():
        return []
    result: list[SessionInfo] = []
    for f in sorted(tdir.iterdir()):
        if f.suffix.lower() == ".duckdb" and f.is_file():
            result.append(SessionInfo(
                session_id="",
                filename=f.name,
                track=f.stem,
            ))
    return result


@app.post("/api/upload", response_model=SessionInfo)
async def upload_session(file: UploadFile = File(...), driver: str = ""):
    """Upload a .duckdb file, save it, and load it as a session."""
    if not file.filename or not file.filename.lower().endswith(".duckdb"):
        raise HTTPException(400, "Only .duckdb files are supported.")
    safe_name = os.path.basename(file.filename)
    if safe_name != file.filename or ".." in file.filename:
        raise HTTPException(400, "Invalid filename.")

    dest = Path(TELEMETRY_DIR) / safe_name
    # Read file contents (limit 500 MB)
    MAX_SIZE = 500 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "File too large (max 500 MB).")
    dest.write_bytes(content)

    # Now load via normal path
    try:
        sess = DuckDBSession(str(dest.resolve()))
    except Exception as exc:
        # Clean up bad file
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Cannot open DuckDB: {exc}") from exc

    proc = LapProcessor(sess)
    laps = proc.process()
    sid = uuid.uuid4().hex[:12]
    meta = sess.session_metadata()
    driver_name = driver.strip() or meta.get("driver", "") or "Unknown"
    _sessions[sid] = (sess, proc, driver_name)

    return SessionInfo(
        session_id=sid,
        filename=safe_name,
        track=meta.get("track", ""),
        car=meta.get("car", ""),
        driver=driver_name,
        date=meta.get("date", ""),
        lap_count=len(laps),
    )


@app.post("/api/load", response_model=SessionInfo)
def load_session(filename: str, driver: str = ""):
    """Load a .duckdb file and return session metadata."""
    # Sanitize: only allow bare filenames with .duckdb extension (no path separators)
    safe_name = os.path.basename(filename)
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")
    if not safe_name.lower().endswith(".duckdb"):
        raise HTTPException(400, "Only .duckdb files are supported.")
    fpath = Path(TELEMETRY_DIR) / safe_name
    # Ensure resolved path stays within TELEMETRY_DIR
    resolved = fpath.resolve()
    telemetry_root = Path(TELEMETRY_DIR).resolve()
    if not str(resolved).startswith(str(telemetry_root) + os.sep) and resolved != telemetry_root:
        raise HTTPException(400, "Invalid filename.")
    if not resolved.is_file():
        raise HTTPException(404, f"File not found: {safe_name}")
    try:
        sess = DuckDBSession(str(resolved))
    except Exception as exc:
        raise HTTPException(400, f"Cannot open DuckDB: {exc}") from exc

    proc = LapProcessor(sess)
    laps = proc.process()

    sid = uuid.uuid4().hex[:12]
    meta = sess.session_metadata()
    driver_name = driver.strip() or meta.get("driver", "") or "Unknown"
    _sessions[sid] = (sess, proc, driver_name)

    return SessionInfo(
        session_id=sid,
        filename=filename,
        track=meta.get("track", ""),
        car=meta.get("car", ""),
        driver=driver_name,
        date=meta.get("date", ""),
        lap_count=len(laps),
    )


@app.get("/api/laps/{session_id}", response_model=LapListResponse)
def get_laps(session_id: str):
    """List all laps with times, sectors, gap-to-best, and theoretical best."""
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    if not laps:
        return LapListResponse(session_id=session_id, laps=[])

    best_time = min(l.lap_time_ms for l in laps)

    # Theoretical best: fastest each sector
    n_sectors = max((len(l.sectors) for l in laps), default=0)
    best_sectors = [float("inf")] * n_sectors
    for l in laps:
        for i, s in enumerate(l.sectors):
            if s < best_sectors[i]:
                best_sectors[i] = s
    theoretical_best = sum(best_sectors) if all(s < float("inf") for s in best_sectors) else None

    summaries: list[LapSummary] = []
    for l in laps:
        sec = SectorTimes()
        if len(l.sectors) >= 1:
            sec.s1 = l.sectors[0]
        if len(l.sectors) >= 2:
            sec.s2 = l.sectors[1]
        if len(l.sectors) >= 3:
            sec.s3 = l.sectors[2]
        summaries.append(LapSummary(
            lap_number=l.lap_number,
            lap_time_ms=l.lap_time_ms,
            sectors=sec,
            gap_to_best_ms=l.lap_time_ms - best_time,
            valid=l.valid,
        ))

    theo_sec = SectorTimes()
    if n_sectors >= 1 and best_sectors[0] < float("inf"):
        theo_sec.s1 = best_sectors[0]
    if n_sectors >= 2 and best_sectors[1] < float("inf"):
        theo_sec.s2 = best_sectors[1]
    if n_sectors >= 3 and best_sectors[2] < float("inf"):
        theo_sec.s3 = best_sectors[2]

    return LapListResponse(
        session_id=session_id,
        laps=summaries,
        theoretical_best_ms=theoretical_best,
        theoretical_sectors=theo_sec,
    )


@app.get("/api/telemetry/{session_id}/{lap_number}", response_model=TelemetryData)
def get_telemetry(session_id: str, lap_number: int):
    """Return full telemetry for a lap, sampled at 1 m resolution."""
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    lap = next((l for l in laps if l.lap_number == lap_number), None)
    if lap is None:
        raise HTTPException(404, f"Lap {lap_number} not found.")
    return TelemetryData(
        distance=lap.distance.tolist(),
        speed=lap.speed.tolist(),
        throttle=lap.throttle.tolist(),
        brake=lap.brake.tolist(),
        steering=lap.steering.tolist(),
        gear=lap.gear.astype(int).tolist(),
        rpm=lap.rpm.tolist(),
        lat=lap.lat.tolist(),
        lon=lap.lon.tolist(),
        lap_time_ms=lap.lap_time_ms,
        sectors=lap.sectors,
    )


@app.get("/api/corners/{session_id}", response_model=CornersResponse)
def get_corners(session_id: str, lap_number: int = 1):
    """Auto-detect corners from the speed trace of the given lap."""
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    lap = next((l for l in laps if l.lap_number == lap_number), None)
    if lap is None:
        raise HTTPException(404, f"Lap {lap_number} not found.")

    raw_corners = detect_corners(lap.speed, lap.distance)
    corners = [
        CornerModel(
            id=c.id,
            name=c.name,
            distance_start=c.distance_start,
            distance_apex=c.distance_apex,
            distance_end=c.distance_end,
            min_speed=c.min_speed,
        )
        for c in raw_corners
    ]
    return CornersResponse(session_id=session_id, corners=corners)


@app.get("/api/delta/{session_id}/{lap_a}/{lap_b}", response_model=DeltaResponse)
def get_delta(session_id: str, lap_a: int, lap_b: int):
    """Cumulative time-delta between two laps over distance."""
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    la = next((l for l in laps if l.lap_number == lap_a), None)
    lb = next((l for l in laps if l.lap_number == lap_b), None)
    if la is None or lb is None:
        raise HTTPException(404, "One or both laps not found.")

    d, delta = compute_delta(la, lb)
    return DeltaResponse(distance=d.tolist(), delta=delta.tolist())


@app.get("/api/channels/{session_id}", response_model=ChannelsResponse)
def get_channels(session_id: str):
    """Debug: return raw DuckDB table/column names."""
    sess, _, _ = _get_session(session_id)
    return ChannelsResponse(session_id=session_id, tables=sess.tables())


# ---------------------------------------------------------------------------
# Multi-driver endpoints
# ---------------------------------------------------------------------------

@app.get("/api/loaded", response_model=list[LoadedSessionInfo])
def list_loaded_sessions():
    """Return all currently loaded sessions with driver info."""
    result: list[LoadedSessionInfo] = []
    for sid, (sess, proc, driver) in _sessions.items():
        laps = proc.process()
        meta = sess.session_metadata()
        result.append(LoadedSessionInfo(
            session_id=sid,
            filename=sess.filename,
            driver=driver,
            track=meta.get("track", ""),
            car=meta.get("car", ""),
            lap_count=len(laps),
        ))
    return result


@app.patch("/api/session/{session_id}/driver")
def set_driver(session_id: str, driver: str):
    """Update the driver name for a loaded session."""
    if session_id not in _sessions:
        raise HTTPException(404, f"Session '{session_id}' not loaded.")
    sess, proc, _ = _sessions[session_id]
    driver_name = driver.strip()
    if not driver_name:
        raise HTTPException(400, "Driver name cannot be empty.")
    _sessions[session_id] = (sess, proc, driver_name)
    return {"session_id": session_id, "driver": driver_name}


def _extract_corner_metrics(
    lap: LapData, corner, session_id: str, driver: str,
) -> DriverCornerMetrics:
    """Extract per-driver metrics for one corner from one lap."""
    d = lap.distance
    t = lap.time
    spd = lap.speed
    brk = lap.brake
    thr = lap.throttle

    si = int(np.searchsorted(d, corner.distance_start))
    ai = int(np.searchsorted(d, corner.distance_apex))
    ei = int(np.searchsorted(d, corner.distance_end))
    si = max(si, 0)
    ai = min(ai, len(d) - 1)
    ei = min(ei, len(d) - 1)

    corner_time = float((t[ei] - t[si]) * 1000) if ei > si else 0.0
    entry_speed = float(spd[si]) if si < len(spd) else 0.0
    apex_speed = float(spd[ai]) if ai < len(spd) else 0.0
    exit_speed = float(spd[ei]) if ei < len(spd) else 0.0
    min_speed_val = float(np.min(spd[si:ei + 1])) if ei > si else apex_speed

    # Brake point: first index where brake > 0.1 in the entry zone
    brake_point = float(d[si])
    for i in range(max(si - 50, 0), ai):
        if i < len(brk) and brk[i] > 0.1:
            brake_point = float(d[i])
            break

    # Throttle point: first index after apex where throttle > 0.5
    throttle_point = float(d[ei])
    for i in range(ai, min(ei + 50, len(thr))):
        if thr[i] > 0.5:
            throttle_point = float(d[i])
            break

    return DriverCornerMetrics(
        driver=driver,
        session_id=session_id,
        lap_number=lap.lap_number,
        corner_time_ms=corner_time,
        min_speed=min_speed_val,
        entry_speed=entry_speed,
        exit_speed=exit_speed,
        brake_point=brake_point,
        throttle_point=throttle_point,
        apex_speed=apex_speed,
    )


def _generate_tips(
    metrics: DriverCornerMetrics, best: DriverCornerMetrics, corner_name: str,
) -> list[str]:
    """Generate coaching tips comparing a driver's metrics to the best."""
    if metrics.driver == best.driver:
        return []
    tips: list[str] = []
    time_diff = metrics.corner_time_ms - best.corner_time_ms

    if time_diff < 50:  # within 50 ms — no tips needed
        return []

    # Braking
    brake_diff = metrics.brake_point - best.brake_point
    if brake_diff < -5:
        tips.append(
            f"Braking {abs(brake_diff):.0f}m earlier than {best.driver} at {corner_name}. "
            f"Try braking later to carry more speed."
        )
    elif brake_diff > 10:
        tips.append(
            f"Braking {brake_diff:.0f}m later than {best.driver} at {corner_name}. "
            f"You may be overshooting the apex."
        )

    # Apex speed
    apex_diff = metrics.apex_speed - best.apex_speed
    if apex_diff < -3:
        tips.append(
            f"Apex speed {abs(apex_diff):.0f} km/h slower than {best.driver}. "
            f"Work on carrying more speed through the corner."
        )

    # Throttle pickup
    thr_diff = metrics.throttle_point - best.throttle_point
    if thr_diff > 5:
        tips.append(
            f"Getting on throttle {thr_diff:.0f}m later than {best.driver}. "
            f"Commit to throttle earlier on exit."
        )

    # Exit speed
    exit_diff = metrics.exit_speed - best.exit_speed
    if exit_diff < -3:
        tips.append(
            f"Exit speed {abs(exit_diff):.0f} km/h slower than {best.driver}. "
            f"Better exit = faster all the way to the next braking zone."
        )

    if not tips:
        tips.append(
            f"Losing {time_diff:.0f}ms to {best.driver} through {corner_name}. "
            f"Review your line and inputs."
        )

    return tips


@app.get("/api/compare/corners", response_model=CompareResponse)
def compare_corners(track: Optional[str] = Query(None)):
    """Cross-driver corner comparison for all loaded sessions on the same track.

    Uses each driver's fastest lap. Detects corners on the overall fastest
    lap, then extracts per-corner metrics from every driver and generates
    coaching tips.
    """
    # Gather all sessions (optionally filtered by track)
    candidates: list[tuple[str, DuckDBSession, LapProcessor, str]] = []
    for sid, (sess, proc, driver) in _sessions.items():
        meta = sess.session_metadata()
        sess_track = meta.get("track", sess.filename)
        if track and sess_track.lower() != track.lower():
            continue
        candidates.append((sid, sess, proc, driver))

    if not candidates:
        raise HTTPException(404, "No loaded sessions found" + (f" for track '{track}'" if track else ""))

    # Resolve effective track name from first match
    effective_track = candidates[0][1].session_metadata().get("track", "")

    # For each driver, find their fastest lap
    driver_best: dict[str, tuple[str, LapData]] = {}  # driver → (session_id, LapData)
    for sid, _sess, proc, driver in candidates:
        laps = proc.process()
        if not laps:
            continue
        fastest = min(laps, key=lambda l: l.lap_time_ms)
        if driver not in driver_best or fastest.lap_time_ms < driver_best[driver][1].lap_time_ms:
            driver_best[driver] = (sid, fastest)

    if not driver_best:
        raise HTTPException(404, "No valid laps in loaded sessions.")

    # Detect corners on the overall fastest lap
    overall_best_driver = min(driver_best, key=lambda d: driver_best[d][1].lap_time_ms)
    ref_sid, ref_lap = driver_best[overall_best_driver]
    raw_corners = detect_corners(ref_lap.speed, ref_lap.distance)

    if not raw_corners:
        return CompareResponse(track=effective_track, corners=[], drivers=list(driver_best.keys()))

    # Build comparison for each corner
    comparisons: list[CornerComparison] = []
    for c in raw_corners:
        all_metrics: list[DriverCornerMetrics] = []
        for driver, (sid, lap) in driver_best.items():
            m = _extract_corner_metrics(lap, c, sid, driver)
            all_metrics.append(m)

        # Find best for this corner
        best_m = min(all_metrics, key=lambda m: m.corner_time_ms)

        # Generate tips for each driver
        tips: dict[str, list[str]] = {}
        for m in all_metrics:
            tips[m.driver] = _generate_tips(m, best_m, c.name)

        comparisons.append(CornerComparison(
            corner_id=c.id,
            corner_name=c.name,
            distance_start=c.distance_start,
            distance_apex=c.distance_apex,
            distance_end=c.distance_end,
            best_driver=best_m.driver,
            best_time_ms=best_m.corner_time_ms,
            drivers=all_metrics,
            tips=tips,
        ))

    return CompareResponse(
        track=effective_track,
        corners=comparisons,
        drivers=list(driver_best.keys()),
    )
