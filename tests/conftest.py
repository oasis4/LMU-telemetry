"""Shared fixtures.

Small real fixtures live in ``tests/fixtures`` and are committed, so the suite
runs anywhere.  The full 637 MB corpus is gitignored; tests marked ``corpus``
skip cleanly when it is absent.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

MONZA_Q_NAME = "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb"
MONZA_Q_FIXTURE = "monza_q_3laps.duckdb"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    if not CORPUS_DIR.is_dir():
        pytest.skip(f"telemetry corpus not present at {CORPUS_DIR}")
    return CORPUS_DIR


@pytest.fixture(scope="session")
def corpus_files(corpus_dir: Path) -> list[Path]:
    return sorted(corpus_dir.glob("*.duckdb"))


@pytest.fixture(scope="session")
def monza_q_file() -> Path:
    """The reference session: the committed fixture, or the corpus original."""
    fixture = FIXTURE_DIR / MONZA_Q_FIXTURE
    if fixture.is_file():
        return fixture
    original = CORPUS_DIR / MONZA_Q_NAME
    if original.is_file():
        return original
    pytest.skip("neither the fixture nor the corpus reference session is present")


@pytest.fixture(scope="session")
def percent_steering_file() -> Path:
    path = FIXTURE_DIR / "lemans_r_percent_steering.duckdb"
    if not path.is_file():
        pytest.skip("percent-steering fixture not built")
    return path


@pytest.fixture(scope="session")
def no_complete_lap_file() -> Path:
    path = FIXTURE_DIR / "monza_q_no_complete_lap.duckdb"
    if not path.is_file():
        pytest.skip("no-complete-lap fixture not built")
    return path
