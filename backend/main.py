"""LMU Telemetry Analyzer — FastAPI backend.

Provides REST endpoints for session listing, lap data, telemetry traces,
corner detection, time-delta computation, and multi-driver corner comparison.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from .corner_detector import detect_corners
from .delta_calc import compute_delta
from .duckdb_reader import DuckDBSession, quick_file_scan
from .lap_processor import LapProcessor, LapData
from .models import (
    ChannelsResponse,
    CoachingAnalysis,
    CompareResponse,
    Corner as CornerModel,
    CornerComparison,
    CornersResponse,
    DeltaResponse,
    DriverCornerMetrics,
    FocusZone,
    LapListResponse,
    LapSummary,
    LoadedSessionInfo,
    SectorTimes,
    SegmentAnalysis,
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

# ---------------------------------------------------------------------------
# Session list cache (background-scanned)
# ---------------------------------------------------------------------------

_session_cache: dict[str, dict] = {}  # filename → quick_file_scan result
_cache_lock = threading.Lock()
_cache_ready = threading.Event()


def _scan_all_sessions() -> None:
    """Background scan of all .duckdb files for metadata/lap info."""
    tdir = Path(TELEMETRY_DIR)
    if not tdir.is_dir():
        _cache_ready.set()
        return
    files = [f for f in sorted(tdir.iterdir())
             if f.suffix.lower() == ".duckdb" and f.is_file()]
    # Parallel scan
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda f: quick_file_scan(str(f)), files)
    with _cache_lock:
        _session_cache.clear()
        for info in results:
            _session_cache[info["filename"]] = info
    _cache_ready.set()


def _start_cache_scan() -> None:
    threading.Thread(target=_scan_all_sessions, daemon=True).start()


@app.on_event("startup")
def _on_startup():
    _start_cache_scan()


def _get_session(session_id: str) -> tuple[DuckDBSession, LapProcessor, str]:
    if session_id not in _sessions:
        raise HTTPException(404, f"Session '{session_id}' not loaded.")
    return _sessions[session_id]


def _build_composite(laps: list[LapData]) -> TelemetryData:
    """Build a theoretical best-lap composite by splicing the fastest sector
    from each real lap.  Sectors are identified by cumulative time boundaries
    derived from each lap's ``.sectors`` list and ``.time`` array.

    Only valid laps are used (filters out pit-out, in-laps, formation laps).
    """
    # Filter to valid laps only
    valid_laps = [l for l in laps if l.valid and l.lap_time_ms > 0]
    if not valid_laps:
        valid_laps = laps  # fallback if none marked valid
    if not valid_laps:
        raise HTTPException(404, "No laps to build composite from.")

    n_sectors = max((len(l.sectors) for l in valid_laps), default=0)
    if n_sectors == 0:
        raise HTTPException(400, "No sector data available for composite.")

    # Compute median per sector for outlier rejection
    _sv: list[list[float]] = [[] for _ in range(n_sectors)]
    for l in valid_laps:
        for si in range(min(n_sectors, len(l.sectors))):
            if l.sectors[si] > 0:
                _sv[si].append(l.sectors[si])
    _medians = []
    for sv in _sv:
        if sv:
            sv.sort()
            _medians.append(sv[len(sv) // 2])
        else:
            _medians.append(0)

    # For each sector index, find the lap with the fastest time (skip outliers)
    best_lap_per_sector: list[LapData] = []
    best_sector_ms: list[float] = []
    for si in range(n_sectors):
        best_l = None
        best_t = float("inf")
        median = _medians[si]
        for l in valid_laps:
            if si < len(l.sectors) and 0 < l.sectors[si] < best_t:
                # Skip anomalously fast sectors (< 70% of median)
                if median > 0 and l.sectors[si] < median * 0.7:
                    continue
                best_t = l.sectors[si]
                best_l = l
        if best_l is None:
            best_l = valid_laps[0]
            best_t = valid_laps[0].sectors[si] if si < len(valid_laps[0].sectors) else 0.0
        best_lap_per_sector.append(best_l)
        best_sector_ms.append(best_t)

    # Build composite arrays by splicing distance-sampled data.
    # Sector boundaries in distance: cumulative sector time mapped via
    # the source lap's time(distance) array.
    composite_arrays: dict[str, list[float]] = {
        k: [] for k in ("distance", "speed", "throttle", "brake",
                        "steering", "rpm", "lat", "lon", "time")
    }
    composite_gear: list[int] = []
    time_offset = 0.0

    for si in range(n_sectors):
        lap = best_lap_per_sector[si]
        # Determine distance boundaries for this sector in the source lap
        cum_before = sum(lap.sectors[:si]) / 1000.0  # seconds
        cum_after = sum(lap.sectors[:si + 1]) / 1000.0  # seconds
        t = lap.time  # time in seconds from lap start

        d_start = float(np.interp(cum_before, t, lap.distance))
        d_end = float(np.interp(cum_after, t, lap.distance))
        i_start = max(0, int(np.searchsorted(lap.distance, d_start)))
        i_end = min(len(lap.distance), int(np.searchsorted(lap.distance, d_end)))
        if i_end <= i_start:
            continue

        sl = slice(i_start, i_end)
        composite_arrays["distance"].extend(lap.distance[sl].tolist())
        composite_arrays["speed"].extend(lap.speed[sl].tolist())
        composite_arrays["throttle"].extend(lap.throttle[sl].tolist())
        composite_arrays["brake"].extend(lap.brake[sl].tolist())
        composite_arrays["steering"].extend(lap.steering[sl].tolist())
        composite_arrays["rpm"].extend(lap.rpm[sl].tolist())
        composite_arrays["lat"].extend(lap.lat[sl].tolist())
        composite_arrays["lon"].extend(lap.lon[sl].tolist())

        # Shift time so sectors chain seamlessly
        sector_time = (lap.time[sl] - lap.time[i_start]) + time_offset
        composite_arrays["time"].extend(sector_time.tolist())
        time_offset = composite_arrays["time"][-1] if composite_arrays["time"] else 0.0

        composite_gear.extend(lap.gear[sl].astype(int).tolist())

    total_ms = sum(best_sector_ms)
    return TelemetryData(
        distance=composite_arrays["distance"],
        speed=composite_arrays["speed"],
        throttle=composite_arrays["throttle"],
        brake=composite_arrays["brake"],
        steering=composite_arrays["steering"],
        gear=composite_gear,
        rpm=composite_arrays["rpm"],
        lat=composite_arrays["lat"],
        lon=composite_arrays["lon"],
        time=composite_arrays["time"],
        lap_time_ms=total_ms,
        sectors=best_sector_ms,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/sessions", response_model=list[SessionInfo])
def list_sessions():
    """List all .duckdb files with metadata from background cache."""
    _cache_ready.wait(timeout=15)  # wait for initial scan
    with _cache_lock:
        items = list(_session_cache.values())
    return [
        SessionInfo(
            session_id="",
            filename=i["filename"],
            track=i.get("track", ""),
            layout=i.get("layout", ""),
            car=i.get("car", ""),
            car_class=i.get("car_class", ""),
            session_type=i.get("session_type", ""),
            driver=i.get("driver", ""),
            date=i.get("date", ""),
            lap_count=i.get("lap_count", 0),
            best_time=i.get("best_time", 0.0),
        )
        for i in items
    ]


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
    best = min((l.lap_time_ms for l in laps if l.lap_time_ms > 0), default=0.0)

    # Refresh cache so new file appears in session list
    _start_cache_scan()

    return SessionInfo(
        session_id=sid,
        filename=safe_name,
        track=meta.get("track", ""),
        layout=meta.get("layout", ""),
        car=meta.get("car", ""),
        car_class=meta.get("car_class", ""),
        session_type=meta.get("session_type", ""),
        driver=driver_name,
        date=meta.get("date", ""),
        lap_count=len(laps),
        best_time=round(best / 1000.0, 3) if best > 0 else 0.0,
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
    best = min((l.lap_time_ms for l in laps if l.lap_time_ms > 0), default=0.0)

    return SessionInfo(
        session_id=sid,
        filename=filename,
        track=meta.get("track", ""),
        layout=meta.get("layout", ""),
        car=meta.get("car", ""),
        car_class=meta.get("car_class", ""),
        session_type=meta.get("session_type", ""),
        driver=driver_name,
        date=meta.get("date", ""),
        lap_count=len(laps),
        best_time=round(best / 1000.0, 3) if best > 0 else 0.0,
    )


@app.get("/api/laps/{session_id}", response_model=LapListResponse)
def get_laps(session_id: str):
    """List all laps with times, sectors, gap-to-best, and theoretical best."""
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    if not laps:
        return LapListResponse(session_id=session_id, laps=[])

    valid_laps = [l for l in laps if l.valid and l.lap_time_ms > 0]
    best_time = min((l.lap_time_ms for l in valid_laps), default=0) if valid_laps else min(l.lap_time_ms for l in laps)

    # Theoretical best: fastest each sector (valid laps only)
    # With sector-level validation: reject sectors < 70% of median for that position
    source_laps = valid_laps if valid_laps else laps
    n_sectors = max((len(l.sectors) for l in source_laps), default=0)

    # Compute median per sector for outlier rejection
    sector_values: list[list[float]] = [[] for _ in range(n_sectors)]
    for l in source_laps:
        for i, s in enumerate(l.sectors):
            if s > 0:
                sector_values[i].append(s)
    sector_medians = []
    for sv in sector_values:
        if sv:
            sv_sorted = sorted(sv)
            sector_medians.append(sv_sorted[len(sv_sorted) // 2])
        else:
            sector_medians.append(0)

    best_sectors = [float("inf")] * n_sectors
    for l in source_laps:
        for i, s in enumerate(l.sectors):
            median = sector_medians[i]
            # Skip anomalously fast sectors (< 70% of median)
            if median > 0 and s < median * 0.7:
                continue
            if 0 < s < best_sectors[i]:
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
        composite_available=theoretical_best is not None and len(laps) > 1,
    )


@app.get("/api/telemetry/{session_id}/{lap_number}", response_model=TelemetryData)
def get_telemetry(session_id: str, lap_number: int):
    """Return full telemetry for a lap, sampled at 1 m resolution.

    Use ``lap_number=0`` to get the theoretical best-lap composite
    (spliced from the best sector of each real lap).
    """
    _, proc, _ = _get_session(session_id)
    laps = proc.process()

    if lap_number == 0:
        return _build_composite(laps)

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
        time=lap.time.tolist() if len(lap.time) > 0 else [],
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

    raw_corners = detect_corners(lap.speed, lap.distance, steering=lap.steering)
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
# Coaching analysis endpoint
# ---------------------------------------------------------------------------

def _classify_corner_error(
    active_lap: LapData, ref_lap: LapData, corner, delta_arr, delta_dist,
) -> tuple[str | None, str, str, str]:
    """Classify the error type for one corner. Returns (error_type, label, explanation, recommendation)."""
    d = active_lap.distance
    spd_a = active_lap.speed
    brk_a = active_lap.brake
    thr_a = active_lap.throttle

    spd_r = ref_lap.speed
    brk_r = ref_lap.brake
    thr_r = ref_lap.throttle

    si_a = int(np.searchsorted(d, corner.distance_start))
    ai_a = int(np.searchsorted(d, corner.distance_apex))
    ei_a = int(np.searchsorted(d, corner.distance_end))
    si_a = max(si_a, 0)
    ai_a = min(ai_a, len(d) - 1)
    ei_a = min(ei_a, len(d) - 1)

    d_r = ref_lap.distance
    si_r = int(np.searchsorted(d_r, corner.distance_start))
    ai_r = int(np.searchsorted(d_r, corner.distance_apex))
    ei_r = int(np.searchsorted(d_r, corner.distance_end))
    si_r = max(si_r, 0)
    ai_r = min(ai_r, len(d_r) - 1)
    ei_r = min(ei_r, len(d_r) - 1)

    # Find brake points
    def _find_brake(brk, dist, start_i, apex_i):
        search_start = max(0, start_i - 50)
        for i in range(search_start, apex_i):
            if i < len(brk) and brk[i] > 0.1:
                return float(dist[i])
        return None

    # Find throttle points (first > 50% after apex)
    def _find_throttle(thr, dist, apex_i, end_i):
        for i in range(apex_i, min(end_i + 50, len(thr))):
            if thr[i] > 0.5:
                return float(dist[i])
        return None

    a_brake = _find_brake(brk_a, d, si_a, ai_a)
    r_brake = _find_brake(brk_r, d_r, si_r, ai_r)
    a_throttle = _find_throttle(thr_a, d, ai_a, ei_a)
    r_throttle = _find_throttle(thr_r, d_r, ai_r, ei_r)

    a_min_speed = float(np.min(spd_a[si_a:ei_a + 1])) if ei_a > si_a else 0
    r_min_speed = float(np.min(spd_r[si_r:ei_r + 1])) if ei_r > si_r else 0

    a_exit_speed = float(spd_a[ei_a]) if ei_a < len(spd_a) else 0
    r_exit_speed = float(spd_r[ei_r]) if ei_r < len(spd_r) else 0

    # Classify error by severity
    errors = []

    # Late/early braking
    if a_brake is not None and r_brake is not None:
        brake_diff = a_brake - r_brake
        if brake_diff < -8:
            errors.append((
                abs(brake_diff),
                "early_brake",
                "Zu frühes Bremsen",
                f"Du bremst {abs(brake_diff):.0f}m früher als die Referenz.",
                "Versuche den Bremspunkt nach hinten zu verschieben und mehr Speed in die Kurve mitzunehmen.",
            ))
        elif brake_diff > 8:
            errors.append((
                brake_diff,
                "late_brake",
                "Zu spätes Bremsen",
                f"Du bremst {brake_diff:.0f}m später als die Referenz.",
                "Bremse etwas früher, um den Apex sauber zu treffen und besseren Exit-Speed zu haben.",
            ))

    # Low minimum speed
    min_speed_diff = a_min_speed - r_min_speed
    if min_speed_diff < -5:
        errors.append((
            abs(min_speed_diff),
            "low_min_speed",
            "Zu niedriges Kurvenminimum",
            f"Dein Minimum-Speed ist {abs(min_speed_diff):.0f} km/h langsamer als die Referenz.",
            "Trage mehr Geschwindigkeit in die Kurve. Weniger aggressiv bremsen, sanfterer Lenkeinschlag.",
        ))

    # Bad traction / throttle pickup
    if a_throttle is not None and r_throttle is not None:
        thr_diff = a_throttle - r_throttle
        if thr_diff > 8:
            errors.append((
                thr_diff,
                "bad_traction",
                "Schlechte Gasannahme / Traktion",
                f"Du gehst {thr_diff:.0f}m später aufs Gas als die Referenz.",
                "Gehe früher und progressiver ans Gas. Achte auf eine gute Linie zum Kurvenausgang.",
            ))

    exit_diff = a_exit_speed - r_exit_speed
    if exit_diff < -5 and not any(e[1] == "bad_traction" for e in errors):
        errors.append((
            abs(exit_diff),
            "bad_traction",
            "Schlechte Gasannahme / Traktion",
            f"Dein Exit-Speed ist {abs(exit_diff):.0f} km/h langsamer.",
            "Arbeite an einer sauberen Linie zum Kurvenausgang für bessere Traktion.",
        ))

    if not errors:
        return None, "", "", ""

    # Return the most severe error
    errors.sort(key=lambda e: e[0], reverse=True)
    _, error_type, label, explanation, recommendation = errors[0]
    return error_type, label, explanation, recommendation


@app.get("/api/coaching/{session_id}/{lap_a}/{lap_b}", response_model=CoachingAnalysis)
def get_coaching(session_id: str, lap_a: int, lap_b: int):
    """Coaching analysis: segment deltas, error classification, focus zone.

    lap_a = your lap (active), lap_b = reference lap.
    Positive delta = lap_a is slower.
    """
    _, proc, _ = _get_session(session_id)
    laps = proc.process()
    la = next((l for l in laps if l.lap_number == lap_a), None)
    lb = next((l for l in laps if l.lap_number == lap_b), None)
    if la is None or lb is None:
        raise HTTPException(404, "One or both laps not found.")

    # Get corners from the reference lap
    raw_corners = detect_corners(lb.speed, lb.distance, steering=lb.steering)

    # Get cumulative delta
    d_common, delta_arr = compute_delta(la, lb)

    segments: list[SegmentAnalysis] = []
    worst_segment: SegmentAnalysis | None = None

    for c in raw_corners:
        # Delta at corner: difference between entry and exit delta
        si = int(np.searchsorted(d_common, c.distance_start))
        ei = int(np.searchsorted(d_common, c.distance_end))
        si = max(si, 0)
        ei = min(ei, len(delta_arr) - 1)

        if ei > si and len(delta_arr) > 0:
            delta_at_corner = float(delta_arr[ei] - delta_arr[si])
        else:
            delta_at_corner = 0.0

        error_type, error_label, explanation, recommendation = _classify_corner_error(
            la, lb, c, delta_arr, d_common,
        )

        seg = SegmentAnalysis(
            corner_id=c.id,
            corner_name=c.name,
            distance_start=c.distance_start,
            distance_apex=c.distance_apex,
            distance_end=c.distance_end,
            delta_s=delta_at_corner,
            error_type=error_type,
            error_label=error_label,
            explanation=explanation,
            recommendation=recommendation,
        )
        segments.append(seg)

        if worst_segment is None or delta_at_corner > worst_segment.delta_s:
            worst_segment = seg

    # Focus zone = segment with largest time loss
    focus = None
    main_message = ""
    if worst_segment and worst_segment.delta_s > 0.01:
        focus = FocusZone(
            distance_start=worst_segment.distance_start,
            distance_end=worst_segment.distance_end,
            delta_s=worst_segment.delta_s,
            corner_name=worst_segment.corner_name,
        )
        if worst_segment.error_label:
            main_message = (
                f"Dein größter Verlust ist in {worst_segment.corner_name} "
                f"({worst_segment.delta_s * 1000:.0f}ms) — {worst_segment.error_label}"
            )
        else:
            main_message = (
                f"Dein größter Verlust ist in {worst_segment.corner_name} "
                f"({worst_segment.delta_s * 1000:.0f}ms)"
            )

    return CoachingAnalysis(
        segments=segments,
        focus_zone=focus,
        main_message=main_message,
    )


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
            layout=meta.get("layout", ""),
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
def compare_corners(track: Optional[str] = Query(None), layout: Optional[str] = Query(None)):
    """Cross-driver corner comparison for all loaded sessions on the same track.

    Uses each driver's fastest lap. Detects corners on the overall fastest
    lap, then extracts per-corner metrics from every driver and generates
    coaching tips.
    """
    # Gather all sessions (optionally filtered by track and layout)
    candidates: list[tuple[str, DuckDBSession, LapProcessor, str]] = []
    for sid, (sess, proc, driver) in _sessions.items():
        meta = sess.session_metadata()
        sess_track = meta.get("track", sess.filename)
        if track and sess_track.lower() != track.lower():
            continue
        if layout and meta.get("layout", "").lower() != layout.lower():
            continue
        candidates.append((sid, sess, proc, driver))

    if not candidates:
        raise HTTPException(404, "No loaded sessions found" + (f" for track '{track}'" if track else ""))

    # Resolve effective track name from first match
    effective_track = candidates[0][1].session_metadata().get("track", "")
    effective_layout = candidates[0][1].session_metadata().get("layout", "")

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
    raw_corners = detect_corners(ref_lap.speed, ref_lap.distance, steering=ref_lap.steering)

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
        layout=effective_layout,
        corners=comparisons,
        drivers=list(driver_best.keys()),
    )


# ---------------------------------------------------------------------------
# Driver bests endpoint (best lap per driver for a track)
# ---------------------------------------------------------------------------

@app.get("/api/driver-bests")
def get_driver_bests(track: str = Query(...), layout: str = Query("")):
    """Return the best session per driver for a given track.

    Uses the session cache (background-scanned metadata) to find,
    for each unique driver, the session with the fastest best_time
    on the requested track.  Optionally filtered by layout.
    """
    _cache_ready.wait(timeout=15)
    with _cache_lock:
        items = list(_session_cache.values())

    driver_best: dict[str, dict] = {}
    for item in items:
        item_track = item.get("track", "")
        if item_track.lower() != track.lower():
            continue
        if layout and item.get("layout", "").lower() != layout.lower():
            continue
        driver = item.get("driver", "") or "Unknown"
        best = item.get("best_time", 0)
        if best <= 0:
            continue
        if driver not in driver_best or best < driver_best[driver]["best_time"]:
            driver_best[driver] = item

    return [
        {
            "driver": d,
            "filename": info["filename"],
            "best_time": info["best_time"],
            "car": info.get("car", ""),
            "session_type": info.get("session_type", ""),
        }
        for d, info in sorted(driver_best.items(), key=lambda x: x[1]["best_time"])
    ]


# ---------------------------------------------------------------------------
# Delete session endpoint
# ---------------------------------------------------------------------------

@app.delete("/api/session/delete")
def delete_session_file(filename: str = Query(...)):
    """Delete a .duckdb session file permanently."""
    safe_name = os.path.basename(filename)
    if safe_name != filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")
    if not safe_name.lower().endswith(".duckdb"):
        raise HTTPException(400, "Only .duckdb files can be deleted.")

    fpath = Path(TELEMETRY_DIR) / safe_name
    resolved = fpath.resolve()
    telemetry_root = Path(TELEMETRY_DIR).resolve()
    if not str(resolved).startswith(str(telemetry_root) + os.sep) and resolved != telemetry_root:
        raise HTTPException(400, "Invalid filename.")
    if not resolved.is_file():
        raise HTTPException(404, f"File not found: {safe_name}")

    # Close and remove any loaded sessions for this file first (releases file lock)
    to_remove = [
        sid for sid, (sess, _, _) in _sessions.items()
        if os.path.basename(sess.filename) == safe_name
    ]
    for sid in to_remove:
        try:
            _sessions[sid][0].conn.close()
        except Exception:
            pass
        del _sessions[sid]

    # Remove the file
    resolved.unlink()

    # Remove from cache
    with _cache_lock:
        _session_cache.pop(safe_name, None)

    return {"deleted": safe_name}
