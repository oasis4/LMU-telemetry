import pytest

from lmu_telemetry.core.quality import DISTANCE_TOLERANCE, assess_lap, clean_laps
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


def test_a_lap_that_does_not_wind_round_the_circuit_is_rejected(zero_winding_file):
    """Paul Ricard lap 2 covers 1.011 track lengths but winds 0.00 times.

    A 74 m jump in the recorded position sends the line out and straight back,
    and the turning it adds cancels the turning it removes. Distance and
    duration both look ordinary, so the winding number is the only check that
    sees it - and a lap admitted here would define the track's geometry from a
    line the car never drove.
    """
    with Session.open(zero_winding_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        assert abs(lap.distance_m / s.track_length_m - 1.0) <= DISTANCE_TOLERANCE
        q = assess_lap(s, lap)
    assert q.is_clean is False
    assert "winds" in q.reason
    assert q.closure_deg == pytest.approx(0.0, abs=1.0)


def test_a_lap_whose_position_jumps_is_rejected(position_jump_file):
    """Monza lap 1 winds exactly once and covers 1.002 track lengths.

    It is admissible on every other criterion; only its 41 m position jump
    rejects it. The lap after it, from the same session, passes - so the
    fixture is not simply a broken recording throughout.
    """
    with Session.open(position_jump_file) as s:
        lap = next(l for l in s.laps if l.number == 1)
        q = assess_lap(s, lap)
        good = assess_lap(s, next(l for l in s.laps if l.number == 2))
    assert q.is_clean is False
    assert q.closure_deg == pytest.approx(360.0, abs=0.5)
    assert q.max_step_m == pytest.approx(40.7, abs=1.0)
    assert "jumps" in q.reason
    assert good.is_clean is True


def test_a_lap_covering_two_track_lengths_is_rejected_on_distance(imola_fused_lap_file):
    """Race lap 0 fuses the formation lap with the first racing lap.

    Renumbered past the lap-0 short-circuit, and with the game's recorded time
    cleared, so the distance criterion itself is what gets exercised rather
    than one of the two rules that sit in front of it.
    """
    from dataclasses import replace

    with Session.open(imola_fused_lap_file) as s:
        lap_zero = next(l for l in s.laps if l.number == 0)
        assert lap_zero.distance_m / s.track_length_m == pytest.approx(1.93, abs=0.05)
        q = assess_lap(s, replace(lap_zero, number=1, recorded_time_s=None))
    assert q.is_clean is False
    assert "track lengths" in q.reason


def test_a_duration_disagreeing_with_the_games_own_lap_time_is_rejected(
    imola_fused_lap_file,
):
    """The formation lap fused with the first racing lap gives itself away.

    We derive 315.8 s from the ``Lap`` event timestamps; the game recorded
    134.3 s for the same crossing. The two are measured independently, so a
    disagreement of that size means the lap boundaries in this file cannot be
    trusted - and no geometric check is needed to establish it.
    """
    from dataclasses import replace

    with Session.open(imola_fused_lap_file) as s:
        lap_zero = next(l for l in s.laps if l.number == 0)
        assert lap_zero.recorded_time_s == pytest.approx(134.255, abs=0.01)
        assert lap_zero.duration_s == pytest.approx(315.820, abs=0.01)
        q = assess_lap(s, replace(lap_zero, number=1))
    assert q.is_clean is False
    assert "disagrees" in q.reason


def test_a_lap_the_game_refused_to_time_is_rejected(monza_q_file):
    """``Lap Time == 0`` is the game saying the lap earned no time.

    Constructed here rather than taken from a fixture, because the check must
    hold for any lap that carries it - and the lap used is otherwise clean, so
    nothing but the recorded zero can be what rejects it.
    """
    from dataclasses import replace

    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 1)
        assert assess_lap(s, lap).is_clean is True
        q = assess_lap(s, replace(lap, recorded_time_s=0.0))
    assert q.is_clean is False
    assert "no lap time" in q.reason
