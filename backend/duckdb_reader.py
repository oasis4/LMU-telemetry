"""DuckDB reader – connects to LMU .duckdb telemetry files and exposes
normalised channel data.

Tables in LMU DuckDB files fall into two categories:

- **Continuous**: single ``value`` column, thousands of rows at a fixed
  sample rate (10 Hz spatial, 50 Hz pedals, 100 Hz engine/steering).
- **Event**: ``ts`` + ``value`` columns, sparse rows recording only state
  changes (lap numbers, gear shifts, sector times).

This module uses explicit table-name preferences so that e.g. ``"brake"``
always resolves to ``Brake Pos`` (28 k rows) rather than ``Brake Bias Rear``
(3 event rows).
"""

from __future__ import annotations

import os
import re
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Table / channel configuration
# ---------------------------------------------------------------------------

_SKIP_TABLES = {"channelslist", "eventslist", "metadata"}

# Preferred DuckDB table for each logical channel, in priority order.
# The ``value`` column is always used for data; ``ts`` is only used via
# ``get_events()``.
PREFERRED_TABLES: dict[str, list[str]] = {
    "speed":          ["GPS Speed", "Ground Speed"],
    "ground_speed":   ["Ground Speed"],
    "throttle":       ["Throttle Pos"],
    "brake":          ["Brake Pos"],
    "steering":       ["Steering Pos"],
    "gear":           ["Gear"],
    "rpm":            ["Engine RPM"],
    "lap":            ["Lap"],
    "lap_distance":   ["Lap Dist"],
    "lat":            ["GPS Latitude", "GPS Lat"],
    "lon":            ["GPS Longitude", "GPS Lon"],
    "gps_time":       ["GPS Time"],
    "sector":         ["Current Sector"],
    "sector1_time":   ["Current Sector1"],
    "sector2_time":   ["Current Sector2"],
    "lap_time":       ["Current LapTime", "Lap Time"],
    "sector1_flag":   ["Sector1 Flag"],
    "sector2_flag":   ["Sector2 Flag"],
    "sector3_flag":   ["Sector3 Flag"],
    "g_lat":          ["G Force Lat"],
    "g_long":         ["G Force Long"],
}


# ---------------------------------------------------------------------------
# DuckDB session reader
# ---------------------------------------------------------------------------

class DuckDBSession:
    """Represents a single DuckDB telemetry file loaded in read-only mode."""

    def __init__(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        self.path = path
        self.filename = os.path.basename(path)
        self.conn = duckdb.connect(path, read_only=True)
        self._tables: dict[str, list[str]] | None = None
        self._raw_cache: dict[str, pd.DataFrame] = {}

    # -- schema introspection ------------------------------------------------

    def tables(self) -> dict[str, list[str]]:
        """Return ``{table_name: [col_name, …]}`` for every real data table."""
        if self._tables is not None:
            return self._tables
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE'"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for (tbl,) in rows:
            if tbl.lower().replace(" ", "").replace("_", "") in _SKIP_TABLES:
                continue
            cols = [
                r[1]                              # r[1] = column name
                for r in self.conn.execute(       # (r[0] = column id)
                    f'PRAGMA table_info("{tbl}")'
                ).fetchall()
            ]
            result[tbl] = cols
        self._tables = result
        return result

    def read_table(self, table: str) -> pd.DataFrame:
        """Read a full table into a DataFrame (cached)."""
        if table not in self._raw_cache:
            self._raw_cache[table] = self.conn.execute(
                f'SELECT * FROM "{table}"'
            ).fetchdf()
        return self._raw_cache[table]

    # -- table helpers -------------------------------------------------------

    def is_event_table(self, table: str) -> bool:
        """True if *table* is an event table (``ts`` + ``value`` columns)."""
        cols = self.tables().get(table, [])
        return "ts" in cols and "value" in cols and len(cols) == 2

    def _find_preferred_table(self, internal_name: str) -> str | None:
        """Return the first existing table from *PREFERRED_TABLES*."""
        prefs = PREFERRED_TABLES.get(internal_name, [])
        all_tables = self.tables()
        for pref in prefs:
            if pref in all_tables:
                return pref
        return None

    # -- high-level channel extraction ---------------------------------------

    def get_channel(self, internal_name: str) -> np.ndarray | None:
        """Return a 1-D numpy array for the ``value`` column, or *None*.

        Works for both continuous tables (returns all rows) and event
        tables (returns the sparse ``value`` column – use
        :meth:`get_events` if you need timestamps too).
        """
        tbl_name = self._find_preferred_table(internal_name)
        if tbl_name is None:
            return None
        df = self.read_table(tbl_name)
        if "value" in df.columns:
            return pd.to_numeric(df["value"], errors="coerce").to_numpy(dtype=np.float64)
        # Multi-value tables (e.g. Susp Pos with value1..value4)
        for col in df.columns:
            if col.startswith("value"):
                return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
        return None

    def get_events(self, internal_name: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return ``(timestamps, values)`` for an event table, or *None*."""
        tbl_name = self._find_preferred_table(internal_name)
        if tbl_name is None:
            return None
        df = self.read_table(tbl_name)
        if "ts" not in df.columns or "value" not in df.columns:
            return None
        ts = pd.to_numeric(df["ts"], errors="coerce").to_numpy(dtype=np.float64)
        vals = pd.to_numeric(df["value"], errors="coerce").to_numpy(dtype=np.float64)
        return ts, vals

    @staticmethod
    def expand_events(
        ts: np.ndarray,
        values: np.ndarray,
        time_axis: np.ndarray,
        fill: float = 0.0,
    ) -> np.ndarray:
        """Forward-fill event values onto a continuous *time_axis*."""
        result = np.full(len(time_axis), fill, dtype=np.float64)
        if len(ts) == 0:
            return result
        # Use searchsorted for efficiency: for each event, find its
        # insertion point on the time axis and fill from there.
        indices = np.searchsorted(time_axis, ts, side="right")
        for i in range(len(ts)):
            si = max(int(indices[i]) - 1, 0) if i == 0 else int(indices[i]) - 1
            si = max(si, 0)
            result[si:] = values[i]
        return result

    # -- sample-rate helpers -------------------------------------------------

    def get_base_rate_info(self) -> tuple[int, float]:
        """Return ``(n_samples, dt)`` for the 10 Hz spatial base rate.

        The base rate is determined from GPS Speed / Lap Dist (both 10 Hz).
        """
        for name in ["GPS Speed", "Lap Dist", "GPS Latitude"]:
            if name in self.tables():
                df = self.read_table(name)
                n = len(df)
                if n > 1:
                    dur = self.session_duration_s()
                    return n, dur / n if n > 0 else 0.1
        dur = self.session_duration_s()
        return max(int(dur * 10), 1), 0.1

    def session_duration_s(self) -> float:
        """Session duration in seconds from GPS Time table."""
        tbls = self.tables()
        for tbl_name in tbls:
            if "gps" in tbl_name.lower() and "time" in tbl_name.lower():
                df = self.read_table(tbl_name)
                if "value" in df.columns:
                    series = pd.to_numeric(df["value"], errors="coerce").dropna()
                else:
                    series = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
                if len(series) > 1:
                    return float(series.iloc[-1] - series.iloc[0])
        # fallback: largest table row count / 100 Hz
        max_rows = 0
        for tbl_name in tbls:
            df = self.read_table(tbl_name)
            if len(df) > max_rows:
                max_rows = len(df)
        return max_rows / 100.0 if max_rows > 0 else 0.0

    def session_metadata(self) -> dict[str, Any]:
        """Return whatever metadata can be gleaned (track, car, etc.)."""
        meta: dict[str, Any] = {"filename": self.filename}
        stem = os.path.splitext(self.filename)[0]
        clean_track = re.sub(r'_[PQR]_\d{4}-\d{2}-\d{2}T.*$', '', stem)
        meta["track"] = clean_track
        meta["car"] = ""
        meta["driver"] = ""
        meta["date"] = ""

        # Try to extract date from filename pattern
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2})_(\d{2})_(\d{2})Z', self.filename)
        if m:
            meta["date"] = f"{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}:{m.group(5)}"

        # Try to read the DuckDB metadata table for driver/car info
        try:
            rows = self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' AND LOWER(table_name) = 'metadata'"
            ).fetchall()
            if rows:
                tbl = rows[0][0]
                df = self.conn.execute(f'SELECT * FROM "{tbl}"').fetchdf()
                # Metadata table may have key/value pairs or named columns
                cols_lower = {c.lower(): c for c in df.columns}
                if "key" in cols_lower and "value" in cols_lower:
                    kv = dict(zip(
                        df[cols_lower["key"]].astype(str).str.lower(),
                        df[cols_lower["value"]].astype(str),
                    ))
                    meta["driver"] = kv.get("drivername", kv.get("driver", kv.get("playername", "")))
                    meta["car"] = kv.get("carname", kv.get("vehiclename", kv.get("car", "")))
                    meta["car_class"] = kv.get("carclass", "")
                    meta["session_type"] = kv.get("sessiontype", "")
                    meta["layout"] = kv.get("tracklayout", "")
                    if kv.get("trackname"):
                        meta["track"] = kv.get("trackname", "")
                else:
                    # Try named columns
                    for col in df.columns:
                        cl = col.lower()
                        if cl in ("driver", "playername", "player_name"):
                            val = str(df[col].iloc[0]) if len(df) > 0 else ""
                            if val and val.lower() != "nan":
                                meta["driver"] = val
                        elif cl in ("car", "vehicle", "vehiclename", "vehicle_name"):
                            val = str(df[col].iloc[0]) if len(df) > 0 else ""
                            if val and val.lower() != "nan":
                                meta["car"] = val
        except Exception:
            pass  # metadata table may not exist or have unexpected format

        return meta

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# Fast standalone scan (no full session load)
# ---------------------------------------------------------------------------

def quick_file_scan(path: str) -> dict[str, Any]:
    """Open a DuckDB file, read metadata + lap count + best time, close it.

    Returns a dict compatible with SessionInfo fields.
    Much faster than a full DuckDBSession + LapProcessor cycle.
    """
    filename = os.path.basename(path)
    info: dict[str, Any] = {"filename": filename}

    # Parse filename for fallbacks
    stem = os.path.splitext(filename)[0]
    info["track"] = re.sub(r'_[PQR]_\d{4}-\d{2}-\d{2}T.*$', '', stem)
    type_map = {"P": "Practice", "Q": "Qualifying", "R": "Race"}
    tm = re.search(r'_([PQR])_\d{4}', filename)
    info["session_type"] = type_map.get(tm.group(1), "") if tm else ""
    dm = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2})_(\d{2})', filename)
    info["date"] = f"{dm.group(3)}.{dm.group(2)}.{dm.group(1)} {dm.group(4)}:{dm.group(5)}" if dm else ""
    info["car"] = ""
    info["car_class"] = ""
    info["driver"] = ""
    info["layout"] = ""
    info["lap_count"] = 0
    info["best_time"] = 0.0

    try:
        conn = duckdb.connect(path, read_only=True)
    except Exception:
        return info

    try:
        # Metadata table
        try:
            mdf = conn.execute('SELECT key, value FROM "metadata"').fetchdf()
            kv = dict(zip(
                mdf["key"].astype(str).str.lower(),
                mdf["value"].astype(str),
            ))
            info["driver"] = kv.get("drivername", kv.get("driver", ""))
            info["car"] = kv.get("carname", kv.get("vehiclename", ""))
            info["car_class"] = kv.get("carclass", "")
            info["layout"] = kv.get("tracklayout", "")
            if kv.get("sessiontype"):
                info["session_type"] = kv["sessiontype"]
            if kv.get("trackname"):
                info["track"] = kv["trackname"]
        except Exception:
            pass

        # Lap count from Lap event table
        try:
            r = conn.execute('SELECT MAX(value) FROM "Lap"').fetchone()
            if r and r[0] is not None:
                info["lap_count"] = int(r[0])
        except Exception:
            pass

        # Best lap time from Lap Time event table (seconds)
        try:
            r = conn.execute(
                'SELECT MIN(value) FROM "Lap Time" WHERE value > 0'
            ).fetchone()
            if r and r[0] is not None:
                info["best_time"] = round(float(r[0]), 3)
        except Exception:
            pass
    finally:
        conn.close()

    return info
