"""One recorded session: file, clock and laps in a single object."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..io.duckdb_source import TelemetryFile
from .laps import Lap, segment_laps
from .timebase import TimeBase


@dataclass(frozen=True)
class SessionInfo:
    """Descriptive metadata, read verbatim from the file."""

    track: str
    layout: str
    car: str
    car_class: str
    driver: str
    session_type: str
    recorded_at: str


class Session:
    """A telemetry file together with its derived laps."""

    def __init__(self, file: TelemetryFile) -> None:
        self._file = file
        self._timebase = TimeBase.from_file(file)
        self._laps: list[Lap] | None = None
        self._track_length: float | None = None

    @classmethod
    def open(cls, path: str | Path) -> Session:
        return cls(TelemetryFile(path))

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def file(self) -> TelemetryFile:
        return self._file

    @property
    def timebase(self) -> TimeBase:
        return self._timebase

    @property
    def info(self) -> SessionInfo:
        meta = self._file.metadata
        return SessionInfo(
            track=meta.get("TrackName", ""),
            layout=meta.get("TrackLayout", ""),
            car=meta.get("CarName", ""),
            car_class=meta.get("CarClass", ""),
            driver=meta.get("DriverName", ""),
            session_type=meta.get("SessionType", ""),
            recorded_at=meta.get("RecordingTime", ""),
        )

    @property
    def laps(self) -> list[Lap]:
        if self._laps is None:
            self._laps = segment_laps(self._file, self._timebase)
        return self._laps

    @property
    def track_length_m(self) -> float:
        if self._track_length is None:
            if "Lap Dist" not in self._file.channels:
                self._track_length = 0.0
            else:
                dist = self._file.channel("Lap Dist")
                self._track_length = float(dist.max()) if len(dist) else 0.0
        return self._track_length

    @property
    def fastest_lap(self) -> Lap | None:
        candidates = [l for l in self.laps if not l.touched_pits]
        if not candidates:
            return None
        return min(candidates, key=lambda l: l.duration_s)
