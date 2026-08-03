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


def test_a_lap_that_does_not_close_is_rejected(imola_unclosed_file):
    """Imola's only complete racing lap closes at 406 degrees, not 360.

    Its distance ratio is 0.998, so it passes every other check - this lap is
    rejected by the closure band alone. Without that band it would define the
    track's geometry from a lap the car did not actually drive round.
    """
    with Session.open(imola_unclosed_file) as s:
        lap = next(l for l in s.laps if l.number == 1)
        q = assess_lap(s, lap)
    assert q.is_clean is False
    assert q.closure_deg == pytest.approx(406.0, abs=2.0)
    assert "closure" in q.reason.lower()


def test_a_lap_covering_two_track_lengths_is_rejected_on_distance(imola_unclosed_file):
    """Race lap 0 fuses the formation lap with the first racing lap.

    Renumbered past the lap-0 short-circuit so the distance criterion itself is
    what gets exercised, rather than the blanket lap-0 rule in front of it.
    """
    from dataclasses import replace

    with Session.open(imola_unclosed_file) as s:
        lap_zero = next(l for l in s.laps if l.number == 0)
        assert lap_zero.distance_m / s.track_length_m == pytest.approx(1.93, abs=0.05)
        q = assess_lap(s, replace(lap_zero, number=1))
    assert q.is_clean is False
    assert "track lengths" in q.reason
