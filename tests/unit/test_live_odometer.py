"""Carrying the lap distance between scoring updates.

Scoring moves about five times a second; the pedals move fifty. This is the
piece that bridges the two, and it is the piece with real behaviour in it -
so it is tested on its own rather than only through a running game.
"""

import pytest

from lmu_telemetry.live.sharedmem import MAX_PLAUSIBLE_MS, Odometer


def test_the_first_frame_of_a_lap_is_the_scoring_figure():
    odo = Odometer()
    assert odo.advance(lap_dist=120.0, lap=3, speed_ms=50.0, elapsed=900.0) == 120.0


def test_distance_is_carried_by_speed_between_scoring_updates():
    """Scoring repeats the same lap_dist for ~200 ms. The car does not stop."""
    odo = Odometer()
    odo.advance(100.0, 3, 50.0, 900.00)
    at = odo.advance(100.0, 3, 50.0, 900.10)     # same scoring, 100 ms later
    assert at == pytest.approx(105.0)
    at = odo.advance(100.0, 3, 50.0, 900.20)
    assert at == pytest.approx(110.0)


def test_a_scoring_update_replaces_the_carried_figure_rather_than_nudging_it():
    """Anchoring is what stops integration error building over a lap."""
    odo = Odometer()
    odo.advance(100.0, 3, 50.0, 900.00)
    odo.advance(100.0, 3, 50.0, 900.20)          # carried to ~110
    at = odo.advance(108.0, 3, 50.0, 900.21)     # scoring says 108
    assert at == pytest.approx(108.0), "the anchor wins outright"


def test_a_new_lap_starts_from_its_own_scoring_figure():
    odo = Odometer()
    odo.advance(5700.0, 3, 50.0, 900.0)
    assert odo.advance(4.0, 4, 50.0, 901.0) == 4.0


def test_a_lap_distance_that_jumps_further_than_a_car_can_go_is_refused():
    """A torn read, or a struct that does not match the game. Either way it is
    not something to place a brake point by."""
    odo = Odometer()
    odo.advance(100.0, 3, 50.0, 900.0)
    assert odo.advance(9000.0, 3, 50.0, 900.02) is None


def test_a_plausible_jump_after_a_long_gap_is_kept():
    """The allowance has to scale with the gap, or a stall in the reader looks
    like a teleport."""
    odo = Odometer()
    odo.advance(100.0, 3, 50.0, 900.0)
    moved = MAX_PLAUSIBLE_MS * 1.0
    assert odo.advance(100.0 + moved * 0.5, 3, 50.0, 901.0) is not None


def test_returning_to_the_same_lap_after_the_car_went_away_does_not_crash():
    """The player drops to the menus mid-lap and comes back.

    `forget()` clears the anchor while the lap number stays what it was, so
    the next frame is the same lap with no anchor behind it. Comparing a
    distance against that missing anchor raised TypeError and took the whole
    overlay down.
    """
    odo = Odometer()
    odo.advance(1200.0, 7, 50.0, 900.0)
    odo.forget()
    assert odo.advance(1260.0, 7, 50.0, 903.0) == 1260.0


def test_a_session_whose_clock_starts_at_zero_still_carries():
    """`mElapsedTime` is session time and a test day starts it at 0.0.

    Written as `self._last_et or elapsed`, a stored 0.0 read as "nothing
    stored" and every step came out zero, so the distance never moved between
    scoring updates.
    """
    odo = Odometer()
    assert odo.advance(0.0, 1, 50.0, 0.0) == 0.0
    at = odo.advance(0.0, 1, 50.0, 0.10)
    assert at == pytest.approx(5.0), "distance must move even from a zero clock"


def test_time_running_backwards_is_refused():
    odo = Odometer()
    odo.advance(100.0, 3, 50.0, 900.0)
    assert odo.advance(100.0, 3, 50.0, 899.5) is None


def test_a_stationary_car_stays_where_it_is():
    odo = Odometer()
    odo.advance(100.0, 3, 0.0, 900.0)
    assert odo.advance(100.0, 3, 0.0, 901.0) == pytest.approx(100.0)
