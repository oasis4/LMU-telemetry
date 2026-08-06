"""Read-only access to a single LMU ``.duckdb`` telemetry file.

Tables come in two shapes:

* **Channels** - a bare ``value`` column sampled at a fixed frequency, with no
  timestamps.  The frequency is declared in ``channelsList``.
* **Events** - ``ts`` plus ``value``, written only when the value changes.

Nothing here interprets the data; that is the job of :mod:`lmu_telemetry.core`.

One file, one connection, one reader at a time. The server hands the same open
recording to every request that wants it and answers requests on a thread pool,
so two of them read the same file whenever a page asks for more than one thing
at once - which the corner overlay does on every lap change. A DuckDB
connection cannot be used that way: interleaved queries hand each other's
result sets back. The observed failures were ``could not convert string to
float: 'ts'`` - a column name arriving where a row should be - and a lap table
that read as empty, reported as "no 'Lap' event table" for a recording that
has one. Every query below therefore holds the file's lock, and so does every
memoised property, so the first reader finishes before the second starts.
"""

from __future__ import annotations

import threading
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
        # Reentrant: the query helpers call each other (a channel read asks
        # for the registry, which is itself a query).
        self._lock = threading.RLock()
        self._metadata: dict[str, str] | None = None
        self._channels: ChannelRegistry | None = None
        self._tables: set[str] | None = None
        self._channel_cache: dict[str, np.ndarray] = {}

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # -- queries -----------------------------------------------------------

    def _rows(self, sql: str, parameters: "list | None" = None) -> list:
        """Run *sql* and read its result while holding the file's lock.

        Executing and fetching must be one atomic step: a DuckDB connection
        keeps the pending result on itself, so a second thread's ``execute``
        between another's ``execute`` and ``fetch`` replaces what that thread
        is about to read.
        """
        with self._lock:
            cursor = self._con.execute(sql, parameters) if parameters else self._con.execute(sql)
            return cursor.fetchall()

    def __enter__(self) -> "TelemetryFile":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- schema ------------------------------------------------------------

    @property
    def tables(self) -> set[str]:
        with self._lock:
            if self._tables is None:
                rows = self._rows(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE'"
                )
                self._tables = {str(r[0]) for r in rows}
            return self._tables

    @property
    def metadata(self) -> dict[str, str]:
        with self._lock:
            if self._metadata is None:
                rows = self._rows('SELECT key, value FROM "metadata"')
                self._metadata = {str(k): str(v) for k, v in rows}
            return self._metadata

    @property
    def channels(self) -> ChannelRegistry:
        with self._lock:
            if self._channels is None:
                self._channels = ChannelRegistry.from_connection(self._con)
            return self._channels

    # -- data --------------------------------------------------------------

    def raw_channel(self, name: str) -> np.ndarray:
        """Channel values exactly as stored."""
        self.channels.require(name)
        if name not in self.tables:
            raise MissingChannelError(name)
        with self._lock:
            col = self._con.execute(f'SELECT value FROM "{name}"').fetchnumpy()["value"]
        return np.asarray(col, dtype=np.float64)

    def channel(self, name: str) -> np.ndarray:
        """Channel values converted into canonical units.

        Cached and read-only: the same array is handed to every caller, so it
        must not be writable - one caller mutating it would corrupt the next.
        """
        with self._lock:
            cached = self._channel_cache.get(name)
            if cached is not None:
                return cached
            spec = self.channels.require(name)
            values = normalise(self.raw_channel(name), spec)
            values.flags.writeable = False
            self._channel_cache[name] = values
            return values

    def first_channel_value(self, name: str) -> float | None:
        """First sample of a channel, without materialising the whole array."""
        spec = self.channels.require(name)
        if name not in self.tables:
            raise MissingChannelError(name)
        rows = self._rows(f'SELECT value FROM "{name}" LIMIT 1')
        if not rows:
            return None
        return float(normalise(np.array([rows[0][0]], dtype=np.float64), spec)[0])

    def has_event(self, name: str) -> bool:
        if name not in self.tables:
            return False
        cols = {str(r[1]) for r in self._rows(f'PRAGMA table_info("{name}")')}
        return "ts" in cols and "value" in cols

    def events(self, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return ``(timestamps, values)`` sorted by timestamp, or ``None``."""
        if not self.has_event(name):
            return None
        rows = self._rows(f'SELECT ts, value FROM "{name}" ORDER BY ts')
        if not rows:
            return np.empty(0), np.empty(0)
        ts = np.array([float(r[0]) for r in rows], dtype=np.float64)
        val = np.array([float(r[1]) for r in rows], dtype=np.float64)
        return ts, val
