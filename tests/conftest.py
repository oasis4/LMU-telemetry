"""Shared fixtures.

Small real fixtures live in ``tests/fixtures`` and are committed, so the suite
runs anywhere.  The recorded sessions are gitignored; tests marked ``corpus``
skip cleanly when they are absent.

``data/sessions`` is the working set that ``tools/curate_corpus.py`` selects -
sessions that still contribute a clean lap, per layout. ``data/archive`` holds
everything else and is deliberately not read here: an invariant that has to
hold for every session should be measured against the set the project actually
works from, and reading the archive would make the suite slower every time
another race is recorded.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "data" / "sessions"
ARCHIVE_DIR = REPO_ROOT / "data" / "archive"
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
def find_session():
    """Locate one named session in the working set or the archive.

    A test that names a session usually names it *because* of some defect it
    carries, and that is often the same reason curation archived it. Looking
    only in the working set would turn those tests into skips - which read as
    passes and cover nothing.
    """

    def _find(name: str) -> Path:
        for directory in (CORPUS_DIR, ARCHIVE_DIR):
            candidate = directory / name
            if candidate.is_file():
                return candidate
        pytest.skip(f"{name} is not present in data/sessions or data/archive")

    return _find


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


@pytest.fixture(scope="session")
def imola_fused_lap_file() -> Path:
    path = FIXTURE_DIR / "imola_r_fused_formation_lap.duckdb"
    if not path.is_file():
        pytest.skip("imola fixture not built")
    return path


@pytest.fixture(scope="session")
def position_jump_file() -> Path:
    path = FIXTURE_DIR / "monza_r_position_jump.duckdb"
    if not path.is_file():
        pytest.skip("position-jump fixture not built")
    return path


@pytest.fixture(scope="session")
def backward_lap_dist_file() -> Path:
    path = FIXTURE_DIR / "bahrain_q_backward_lap_dist.duckdb"
    if not path.is_file():
        pytest.skip("backward-Lap-Dist fixture not built")
    return path


@pytest.fixture(scope="session")
def zero_winding_file() -> Path:
    path = FIXTURE_DIR / "paul_ricard_p_zero_winding.duckdb"
    if not path.is_file():
        pytest.skip("zero-winding fixture not built")
    return path
