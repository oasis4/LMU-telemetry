import pytest

from lmu_telemetry.core.quality import assess_lap, clean_laps
from lmu_telemetry.core.session import Session


def test_a_qualifying_flyer_is_clean(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        q = assess_lap(s, lap)
    assert q.is_clean is True
    assert q.reason is None
    assert q.closure_deg == pytest.approx(360.0, abs=30.0)


def test_the_out_lap_is_rejected_for_touching_the_pits(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 0)
        q = assess_lap(s, lap)
    assert q.is_clean is False
    assert "pit" in q.reason.lower()


def test_the_rejection_reason_is_stated_not_just_a_boolean(monza_q_file):
    """A lap dropped without a reason is indistinguishable from a bug."""
    with Session.open(monza_q_file) as s:
        for lap in s.laps:
            q = assess_lap(s, lap)
            assert q.is_clean or q.reason


def test_clean_laps_excludes_lap_zero(monza_q_file):
    """Lap 0 runs from the start of recording to the first timed crossing."""
    with Session.open(monza_q_file) as s:
        assert all(l.number > 0 for l in clean_laps(s))


def test_a_lap_spanning_two_track_lengths_is_rejected(fixture_dir):
    """Race lap 0 fuses the formation lap with the first racing lap."""
    path = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    if not path.is_file():
        pytest.skip("fixture not built")
    with Session.open(path) as s:
        lap = next((l for l in s.laps if l.number == 0), None)
        if lap is None:
            pytest.skip("fixture has no lap 0")
        q = assess_lap(s, lap)
    assert q.is_clean is False
