"""DuckDB reader – connects to LMU .duckdb telemetry files and exposes
normalised channel data.

Leverages the channel-mapping logic from the parent project's
``duckdb_to_motec_unified.py`` while providing a clean, session-based API
suitable for the FastAPI backend.
"""

from __future__ import annotations

import os
import re
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Channel-name normalisation (ported from duckdb_to_motec_unified.py)
# ---------------------------------------------------------------------------

WHEEL_MAP: dict[str, str] = {
    "value1": "FL",
    "value2": "FR",
    "value3": "RL",
    "value4": "RR",
}

_SKIP_TABLES = {"channelslist", "eventslist", "metadata"}

# Mapping of lowercase *base* patterns to internal normalised names.
CHANNEL_MAP: dict[str, str] = {
    "throttle": "throttle",
    "brake": "brake",
    "steer": "steering",
    "speed": "speed",
    "gear": "gear",
    "rpm": "rpm",
    "engine": "rpm",
    "lap": "lap",
    "lap_number": "lap",
    "lap_beacon": "lap_beacon",
    "lapdist": "lap_distance",
    "lap_dist": "lap_distance",
    "lap distance": "lap_distance",
    "normalizedlap": "normalized_lap",
    "pos_x": "pos_x",
    "pos_y": "pos_y",
    "pos_z": "pos_z",
    "gps_lat": "lat",
    "gps_lon": "lon",
    "gps lat": "lat",
    "gps lon": "lon",
    "latitude": "lat",
    "longitude": "lon",
    "sector": "sector",
    "abs": "abs_active",
    "tc": "tc_active",
}


def _clean(name: str) -> str:
    """Lowercase, strip, collapse whitespace/underscores."""
    return re.sub(r"[\s_]+", "_", str(name).strip().lower())


def _match_channel(raw: str) -> str | None:
    """Try to map a raw DuckDB column/table name to an internal name."""
    c = _clean(raw)
    # exact match
    if c in CHANNEL_MAP:
        return CHANNEL_MAP[c]
    # partial containment
    for pattern, internal in CHANNEL_MAP.items():
        if pattern in c:
            return internal
    return None


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
                r[0]
                for r in self.conn.execute(
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

    # -- high-level channel extraction ---------------------------------------

    def _find_table_and_col(self, internal_name: str) -> list[tuple[str, str]]:
        """Find all (table, column) pairs that map to *internal_name*."""
        matches: list[tuple[str, str]] = []
        for tbl, cols in self.tables().items():
            tbl_match = _match_channel(tbl)
            if tbl_match == internal_name:
                # If the table name itself maps, use the first numeric column
                matches.append((tbl, cols[0] if cols else "value1"))
                continue
            for col in cols:
                col_match = _match_channel(col)
                if col_match == internal_name:
                    matches.append((tbl, col))
        return matches

    def get_channel(self, internal_name: str) -> np.ndarray | None:
        """Return a 1-D numpy array for the requested channel, or *None*."""
        pairs = self._find_table_and_col(internal_name)
        if not pairs:
            return None
        tbl, col = pairs[0]
        df = self.read_table(tbl)
        if col not in df.columns:
            # fall back to first column
            col = df.columns[0]
        arr = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)
        return arr

    def session_duration_s(self) -> float:
        """Estimate session duration in seconds using GPS Time table or row count."""
        tbls = self.tables()
        # prefer GPS Time table
        for tbl_name in tbls:
            if "gps" in tbl_name.lower() and "time" in tbl_name.lower():
                df = self.read_table(tbl_name)
                col = df.columns[0]
                series = pd.to_numeric(df[col], errors="coerce").dropna()
                if len(series) > 1:
                    return float(series.iloc[-1] - series.iloc[0])

        # fallback: largest table row count / 100 Hz
        max_rows = 0
        for tbl_name in tbls:
            df = self.read_table(tbl_name)
            if len(df) > max_rows:
                max_rows = len(df)
        if max_rows > 0:
            return max_rows / 100.0
        return 0.0

    def session_metadata(self) -> dict[str, Any]:
        """Return whatever metadata can be gleaned (track, car, etc.)."""
        meta: dict[str, Any] = {"filename": self.filename}

        # Try metadata table
        for tbl_name, cols in self.tables().items():
            if tbl_name.lower().replace("_", "").replace(" ", "") == "metadata":
                df = self.read_table(tbl_name)
                for _, row in df.iterrows():
                    for c in cols:
                        v = str(row[c]).strip()
                        cl = c.lower()
                        if "track" in cl or "venue" in cl:
                            meta["track"] = v
                        elif "car" in cl or "vehicle" in cl:
                            meta["car"] = v
                        elif "driver" in cl:
                            meta["driver"] = v
                        elif "date" in cl:
                            meta["date"] = v
                break

        # Fallback: derive from filename
        stem = os.path.splitext(self.filename)[0]
        meta.setdefault("track", stem)
        meta.setdefault("car", "")
        meta.setdefault("driver", "")
        meta.setdefault("date", "")
        return meta

    def close(self) -> None:
        self.conn.close()
