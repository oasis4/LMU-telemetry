"""Shared fixtures. The telemetry corpus is gitignored, so every fixture that
needs it skips cleanly when it is absent (e.g. on CI)."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"

# The reference session for all golden tests: Monza qualifying, 3 complete laps,
# known lap times 131.085 / 116.560 / 111.000 s.
MONZA_Q_NAME = "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb"


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    if not CORPUS_DIR.is_dir():
        pytest.skip(f"telemetry corpus not present at {CORPUS_DIR}")
    return CORPUS_DIR


@pytest.fixture(scope="session")
def corpus_files(corpus_dir: Path) -> list[Path]:
    return sorted(corpus_dir.glob("*.duckdb"))


@pytest.fixture(scope="session")
def monza_q_file(corpus_dir: Path) -> Path:
    path = corpus_dir / MONZA_Q_NAME
    if not path.is_file():
        pytest.skip(f"reference session missing: {path}")
    return path
