"""Extract small, real test fixtures from the local telemetry corpus.

The corpus itself is gitignored (637 MB).  These fixtures are committed so the
test suite has real data to run against in CI.  They keep only the tables the
tests read, blank the 38 kB CarSetup JSON, and use a 16 kB DuckDB block size -
which takes the Monza reference session from 8.6 MB down to 860 kB.

Run from the repository root:

    python tools/build_fixtures.py
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"
OUT_DIR = REPO_ROOT / "tests" / "fixtures"

BLOCK_SIZE = 16384

#: Tables every fixture keeps.  Event tables first, then channels.
EVENT_TABLES = ["Lap", "Current Sector", "In Pits", "Lap Time"]
CHANNEL_TABLES = [
    "GPS Time", "Lap Dist", "GPS Latitude", "GPS Longitude",
    "Ground Speed", "Throttle Pos", "Brake Pos", "Steering Pos",
]
META_TABLES = ["metadata", "channelsList", "eventsList"]

#: (source filename, fixture name, seconds to keep or None for all, why it exists)
FIXTURES: list[tuple[str, str, float | None, str]] = [
    (
        "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb",
        "monza_q_3laps.duckdb",
        None,
        "reference session: 3 complete laps, 131.085 / 116.560 / 111.000 s",
    ),
    (
        "Autodromo Nazionale Monza_Q_2026-03-27T09_02_56Z.duckdb",
        "monza_q_no_complete_lap.duckdb",
        None,
        "abandoned after 160 m: one Lap event, no complete lap",
    ),
    (
        "Circuit de la Sarthe_R_2026-04-01T06_41_16Z.duckdb",
        "lemans_r_percent_steering.duckdb",
        400.0,
        "Steering Pos carries unit '%' (range +-100) instead of the usual +-1",
    ),
    (
        "Autodromo Nazionale Monza_R_2026-03-22T18_20_02Z.duckdb",
        "monza_r_extra_dist_reset.duckdb",
        700.0,
        "12 Lap events but 13 Lap Dist resets - the case that broke the old code",
    ),
    (
        "Autodromo Enzo e Dino Ferrari_R_2026-04-04T18_46_34Z.duckdb",
        "imola_r_unclosed_lap.duckdb",
        500.0,
        "its only complete racing lap closes at 406 deg, so the track "
        "legitimately yields no reference model",
    ),
]


def _channel_frequency(con, name: str) -> int | None:
    row = con.execute(
        'SELECT frequency FROM src."channelsList" WHERE channelName = ?', [name]
    ).fetchone()
    return int(row[0]) if row else None


def _table_exists(con, name: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables"
        " WHERE table_catalog = 'src' AND table_name = ?",
        [name],
    ).fetchone()
    return bool(row and row[0])


def build(source: Path, dest: Path, keep_seconds: float | None) -> None:
    dest.unlink(missing_ok=True)
    con = duckdb.connect(str(dest), config={"default_block_size": BLOCK_SIZE})
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")

        for table in META_TABLES:
            if _table_exists(con, table):
                con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"')

        # Blank the setup blob: 38 kB of JSON that nothing reads.
        if _table_exists(con, "metadata"):
            con.execute("UPDATE metadata SET value = '{}' WHERE key = 'CarSetup'")

        t0_row = con.execute('SELECT value FROM src."GPS Time" LIMIT 1').fetchone()
        t0 = float(t0_row[0]) if t0_row else 0.0
        t_cut = None if keep_seconds is None else t0 + keep_seconds

        for table in EVENT_TABLES:
            if not _table_exists(con, table):
                continue
            where = "" if t_cut is None else f" WHERE ts <= {t_cut}"
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"{where}')

        for table in CHANNEL_TABLES:
            if not _table_exists(con, table):
                continue
            freq = _channel_frequency(con, table)
            if t_cut is None or freq is None:
                limit = ""
            else:
                # Truncate the tail only, so sample i still maps to t0 + i / freq.
                limit = f" LIMIT {math.ceil(keep_seconds * freq)}"
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"{limit}')

        con.execute("DETACH src")
    finally:
        con.close()


def main() -> None:
    if not CORPUS.is_dir():
        raise SystemExit(f"corpus not found at {CORPUS}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, dest_name, keep, why in FIXTURES:
        source = CORPUS / src_name
        if not source.is_file():
            print(f"SKIP {dest_name}: source missing ({src_name})")
            continue
        dest = OUT_DIR / dest_name
        build(source, dest, keep)
        size_kb = dest.stat().st_size / 1024
        print(f"{dest_name:38s} {size_kb:8.1f} KB   {why}")


if __name__ == "__main__":
    main()
