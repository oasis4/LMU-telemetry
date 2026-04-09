"""Pydantic schemas for LMU Telemetry Analyzer API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Session / Lap
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    session_id: str
    filename: str
    track: str = ""
    layout: str = ""
    car: str = ""
    car_class: str = ""
    session_type: str = ""
    driver: str = ""
    date: str = ""
    lap_count: int = 0
    best_time: float = 0.0  # best lap time in seconds (0 = unknown)


class SectorTimes(BaseModel):
    s1: float | None = None  # ms
    s2: float | None = None
    s3: float | None = None


class LapSummary(BaseModel):
    lap_number: int
    lap_time_ms: float
    sectors: SectorTimes = Field(default_factory=SectorTimes)
    gap_to_best_ms: float = 0.0
    valid: bool = True


class LapListResponse(BaseModel):
    session_id: str
    laps: list[LapSummary]
    theoretical_best_ms: float | None = None
    theoretical_sectors: SectorTimes = Field(default_factory=SectorTimes)
    composite_available: bool = False


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

class TelemetryData(BaseModel):
    distance: list[float]
    speed: list[float]
    throttle: list[float]
    brake: list[float]
    steering: list[float]
    gear: list[int]
    rpm: list[float]
    lat: list[float]
    lon: list[float]
    time: list[float] = Field(default_factory=list)
    lap_time_ms: float = 0.0
    sectors: list[float] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Corners
# ---------------------------------------------------------------------------

class Corner(BaseModel):
    id: int
    name: str
    distance_start: float
    distance_apex: float
    distance_end: float
    min_speed: float


class CornersResponse(BaseModel):
    session_id: str
    corners: list[Corner]


# ---------------------------------------------------------------------------
# Delta
# ---------------------------------------------------------------------------

class DeltaResponse(BaseModel):
    distance: list[float]
    delta: list[float]  # cumulative time delta in seconds


# ---------------------------------------------------------------------------
# Driver / Multi-driver comparison
# ---------------------------------------------------------------------------

class DriverInfo(BaseModel):
    name: str
    sessions: list[str]  # session_ids


class DriverCornerMetrics(BaseModel):
    """Per-driver metrics for a single corner."""
    driver: str
    session_id: str
    lap_number: int
    corner_time_ms: float
    min_speed: float
    entry_speed: float
    exit_speed: float
    brake_point: float        # distance where braking begins
    throttle_point: float     # distance where throttle > 50 % after apex
    apex_speed: float


class CornerComparison(BaseModel):
    """One corner with metrics from every driver."""
    corner_id: int
    corner_name: str
    distance_start: float
    distance_apex: float
    distance_end: float
    best_driver: str
    best_time_ms: float
    drivers: list[DriverCornerMetrics]
    tips: dict[str, list[str]]  # driver → list of coaching tips


class CompareResponse(BaseModel):
    track: str
    layout: str = ""
    corners: list[CornerComparison]
    drivers: list[str]


class LoadedSessionInfo(BaseModel):
    """Summary of an already-loaded session."""
    session_id: str
    filename: str
    driver: str
    track: str
    layout: str = ""
    car: str
    lap_count: int


# ---------------------------------------------------------------------------
# Coaching / Dashboard analysis
# ---------------------------------------------------------------------------

class SegmentAnalysis(BaseModel):
    """Delta and error info for one segment (corner)."""
    corner_id: int
    corner_name: str
    distance_start: float
    distance_apex: float
    distance_end: float
    delta_s: float  # time delta in seconds (positive = losing)
    error_type: str | None = None  # 'late_brake', 'early_brake', 'low_min_speed', 'bad_traction', None
    error_label: str = ""
    explanation: str = ""
    recommendation: str = ""


class FocusZone(BaseModel):
    """Zone with the largest time loss."""
    distance_start: float
    distance_end: float
    delta_s: float
    corner_name: str


class CoachingAnalysis(BaseModel):
    """Full coaching analysis for an active vs ref lap pair."""
    segments: list[SegmentAnalysis]
    focus_zone: FocusZone | None = None
    main_message: str = ""


# ---------------------------------------------------------------------------
# Channels (debug)
# ---------------------------------------------------------------------------

class ChannelsResponse(BaseModel):
    session_id: str
    tables: dict[str, list[str]]  # table_name -> list of column names
