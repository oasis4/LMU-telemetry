"""A circuit is measured from every recording of it, not from one session.

The curated corner names are applied all-or-nothing and dropped when the
detected apexes drift further than the name table can absorb. A model built
from a single short session drifts that far, so the app showed T1..Tn where it
should have shown the circuit's own names.
"""

import shutil

import pytest

from lmu_telemetry.api.pool import SessionPool
from lmu_telemetry.core.track_model import TrackKey


@pytest.fixture
def two_monza_recordings(tmp_path, fixture_dir):
    """Two recordings of the same circuit, and one of another."""
    for source, name in (
        ("monza_q_3laps.duckdb", "monza-a.duckdb"),
        ("monza_r_position_jump.duckdb", "monza-b.duckdb"),
        ("paul_ricard_p_zero_winding.duckdb", "elsewhere.duckdb"),
    ):
        path = fixture_dir / source
        if not path.is_file():
            pytest.skip(f"{source} not built")
        shutil.copy(path, tmp_path / name)
    return tmp_path


def test_siblings_of_the_same_circuit_contribute_their_laps(two_monza_recordings):
    pool = SessionPool()
    try:
        session = pool.get(two_monza_recordings / "monza-a.duckdb")
        alone = pool.model_for(session)
        pool._models.clear()          # noqa: SLF001 - forcing a rebuild
        together = pool.model_for(session, sorted(two_monza_recordings.glob("*.duckdb")))
    finally:
        pool.close()

    assert together.lap_count > alone.lap_count


def test_a_recording_of_another_circuit_is_not_folded_in(two_monza_recordings):
    """Handing over the whole directory has to be safe.

    Without the identity check Paul Ricard's laps would be resampled onto
    Monza's grid and averaged into its racing line.
    """
    pool = SessionPool()
    try:
        session = pool.get(two_monza_recordings / "monza-a.duckdb")
        model = pool.model_for(session, sorted(two_monza_recordings.glob("*.duckdb")))
    finally:
        pool.close()

    assert model.key == TrackKey("Autodromo Nazionale Monza", "Autodromo Nazionale Monza")
    assert model.track_length_m == pytest.approx(5776, abs=20)
    assert model.closure_deg == pytest.approx(360.0, abs=0.5)


def test_the_session_being_asked_about_is_never_evicted(two_monza_recordings):
    """Siblings are opened outside the pool.

    Going through it would evict up to its whole contents - including the very
    session the model is being built for - on any circuit with more recordings
    than the pool holds.
    """
    pool = SessionPool(max_open=1)
    try:
        session = pool.get(two_monza_recordings / "monza-a.duckdb")
        pool.model_for(session, sorted(two_monza_recordings.glob("*.duckdb")))
        # Still usable: not closed underneath us.
        assert session.file.channel("Lap Dist") is not None
        assert len(pool) == 1
    finally:
        pool.close()


def test_a_model_is_still_built_once_per_identity(two_monza_recordings):
    pool = SessionPool()
    try:
        session = pool.get(two_monza_recordings / "monza-a.duckdb")
        siblings = sorted(two_monza_recordings.glob("*.duckdb"))
        assert pool.model_for(session, siblings) is pool.model_for(session, siblings)
    finally:
        pool.close()
