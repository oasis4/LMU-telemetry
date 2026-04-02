"""LMU Telemetry Analyzer — FastAPI backend.

Provides REST endpoints for session listing, lap data, telemetry traces,
corner detection, and time-delta computation.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .corner_detector import detect_corners
from .delta_calc import compute_delta
from .duckdb_reader import DuckDBSession
from .lap_processor import LapProcessor
from .models import (
    ChannelsResponse,
    Corner as CornerModel,
    CornersResponse,
    DeltaResponse,
    LapListResponse,
    LapSummary,
    SectorTimes,
    SessionInfo,
    TelemetryData,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="LMU Telemetry Analyzer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TELEMETRY_DIR = os.environ.get("TELEMETRY_DIR", str(Path.home() / "Telemetry"))

# In-memory session store:  session_id → (DuckDBSession, LapProcessor)
_sessions: dict[str, tuple[DuckDBSession, LapProcessor]] = {}


def _get_session(session_id: str) -> tuple[DuckDBSession, LapProcessor]:
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


@app.post("/api/load", response_model=SessionInfo)
def load_session(filename: str):
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
    _sessions[sid] = (sess, proc)

    meta = sess.session_metadata()
    return SessionInfo(
        session_id=sid,
        filename=filename,
        track=meta.get("track", ""),
        car=meta.get("car", ""),
        driver=meta.get("driver", ""),
        date=meta.get("date", ""),
        lap_count=len(laps),
    )


@app.get("/api/laps/{session_id}", response_model=LapListResponse)
def get_laps(session_id: str):
    """List all laps with times, sectors, gap-to-best, and theoretical best."""
    _, proc = _get_session(session_id)
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
    _, proc = _get_session(session_id)
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
    _, proc = _get_session(session_id)
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
    _, proc = _get_session(session_id)
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
    sess, _ = _get_session(session_id)
    return ChannelsResponse(session_id=session_id, tables=sess.tables())
