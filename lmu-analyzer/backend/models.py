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
    car: str = ""
    driver: str = ""
    date: str = ""
    lap_count: int = 0


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
# Channels (debug)
# ---------------------------------------------------------------------------

class ChannelsResponse(BaseModel):
    session_id: str
    tables: dict[str, list[str]]  # table_name -> list of column names
