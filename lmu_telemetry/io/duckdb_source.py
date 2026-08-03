"""Read-only access to a single LMU ``.duckdb`` telemetry file.

Tables come in two shapes:

* **Channels** - a bare ``value`` column sampled at a fixed frequency, with no
  timestamps.  The frequency is declared in ``channelsList``.
* **Events** - ``ts`` plus ``value``, written only when the value changes.

Nothing here interprets the data; that is the job of :mod:`lmu_telemetry.core`.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from .channels import ChannelRegistry, MissingChannelError, normalise


class TelemetryFile:
    """One telemetry file, opened read-only."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._metadata: dict[str, str] | None = None
        self._channels: ChannelRegistry | None = None
        self._tables: set[str] | None = None

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "TelemetryFile":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- schema ------------------------------------------------------------

    @property
    def tables(self) -> set[str]:
        if self._tables is None:
            rows = self._con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE'"
            ).fetchall()
            self._tables = {str(r[0]) for r in rows}
        return self._tables

    @property
    def metadata(self) -> dict[str, str]:
        if self._metadata is None:
            rows = self._con.execute('SELECT key, value FROM "metadata"').fetchall()
            self._metadata = {str(k): str(v) for k, v in rows}
        return self._metadata

    @property
    def channels(self) -> ChannelRegistry:
        if self._channels is None:
            self._channels = ChannelRegistry.from_connection(self._con)
        return self._channels

    # -- data --------------------------------------------------------------

    def raw_channel(self, name: str) -> np.ndarray:
        """Channel values exactly as stored."""
        self.channels.require(name)
        if name not in self.tables:
            raise MissingChannelError(name)
        col = self._con.execute(f'SELECT value FROM "{name}"').fetchnumpy()["value"]
        return np.asarray(col, dtype=np.float64)

    def channel(self, name: str) -> np.ndarray:
        """Channel values converted into canonical units."""
        spec = self.channels.require(name)
        return normalise(self.raw_channel(name), spec)

    def has_event(self, name: str) -> bool:
        if name not in self.tables:
            return False
        cols = {
            str(r[1])
            for r in self._con.execute(f'PRAGMA table_info("{name}")').fetchall()
        }
        return "ts" in cols and "value" in cols

    def events(self, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return ``(timestamps, values)`` sorted by timestamp, or ``None``."""
        if not self.has_event(name):
            return None
        rows = self._con.execute(
            f'SELECT ts, value FROM "{name}" ORDER BY ts'
        ).fetchall()
        if not rows:
            return np.empty(0), np.empty(0)
        ts = np.array([float(r[0]) for r in rows], dtype=np.float64)
        val = np.array([float(r[1]) for r in rows], dtype=np.float64)
        return ts, val
