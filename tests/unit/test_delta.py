import numpy as np
import pytest

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.delta import delta_s, span_indices, time_lost_over
from lmu_telemetry.core.geometry import grid_for
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.trace import LapTrace, build_trace


def _trace(grid, time_s) -> LapTrace:
    zeros = np.zeros_like(grid)
    return LapTrace(
        lap=None, grid=grid, time_s=np.asarray(time_s, dtype=float),
        speed_kmh=zeros, throttle=zeros, brake=zeros,
    )


def _corner(start_m, apex_m, end_m) -> Corner:
    return Corner(
        index=1, name="T1", start_m=start_m, apex_m=apex_m, end_m=end_m,
        radius_m=100.0, heading_deg=90.0, direction="L",
    )


def test_delta_ends_at_the_difference_of_the_two_lap_times():
    grid = grid_for(1000.0)
    reference = _trace(grid, np.linspace(0.0, 100.0, len(grid)))
    slower = _trace(grid, np.linspace(0.0, 101.5, len(grid)))
    d = delta_s(reference, slower)
    assert d[0] == pytest.approx(0.0, abs=1e-12)
    assert d[-1] == pytest.approx(1.5, rel=1e-9)
    assert np.all(d >= -1e-12), "a uniformly slower lap never leads"


def test_the_sign_says_who_is_behind():
    grid = grid_for(1000.0)
    reference = _trace(grid, np.linspace(0.0, 100.0, len(grid)))
    faster = _trace(grid, np.linspace(0.0, 98.0, len(grid)))
    assert delta_s(reference, faster)[-1] == pytest.approx(-2.0, rel=1e-9)


def test_two_laps_on_different_grids_are_refused():
    """Different grids mean different tracks, and subtracting them would
    return a plausible-looking array of nonsense."""
    a = _trace(grid_for(1000.0), np.linspace(0.0, 100.0, len(grid_for(1000.0))))
    b = _trace(grid_for(2000.0), np.linspace(0.0, 100.0, len(grid_for(2000.0))))
    with pytest.raises(ValueError):
        delta_s(a, b)


def test_a_span_that_wraps_the_start_finish_line_is_covered_once():
    """A corner containing d=0 has start_m > end_m.

    Read as an ordinary range it is empty, and that corner then vanishes from
    every comparison on a circuit whose start/finish sits inside a bend -
    without anything saying so.
    """
    grid = grid_for(1000.0)
    indices = span_indices(grid, 900.0, 100.0)
    assert indices[0] == 450                      # 900 m / 2 m
    assert indices[-1] == 50                      # wrapped round to 100 m
    assert len(indices) == 101
    assert len(set(indices.tolist())) == len(indices), "no index covered twice"


def test_time_lost_over_a_corner_is_the_deltas_rise_across_it():
    grid = grid_for(1000.0)
    delta = np.zeros_like(grid)
    delta[200:] = 0.4                              # all of it lost at 400 m
    lost = time_lost_over(delta, grid, _corner(300.0, 400.0, 500.0))
    assert lost == pytest.approx(0.4, abs=1e-9)


def test_a_corner_where_nothing_changed_is_charged_nothing():
    grid = grid_for(1000.0)
    delta = np.zeros_like(grid)
    delta[600:] = 2.0                              # lost somewhere else entirely
    assert time_lost_over(delta, grid, _corner(100.0, 150.0, 200.0)) == pytest.approx(0.0)


def test_time_lost_over_a_wrapping_corner_adds_both_sides_of_the_line():
    """Its two pieces are half a lap apart in the array, not adjacent.

    0.3 s is lost at 950 m and 0.2 s more at 50 m, both inside a corner that
    runs 900 m -> 100 m. Subtracting the far end from the near one instead
    would read delta[50] - delta[450] and report the whole rest of the lap.
    """
    grid = grid_for(1000.0)
    delta = np.zeros_like(grid)
    delta[475:] = 0.3                              # 0.3 s lost at 950 m
    delta[25:] += 0.2                              # 0.2 s lost at 50 m
    lost = time_lost_over(delta, grid, _corner(900.0, 960.0, 100.0))
    assert lost == pytest.approx(0.5, abs=1e-9)


def test_a_wrapping_corner_is_not_charged_for_the_rest_of_the_lap():
    """Nothing happens inside the corner; 4 s are lost in the middle of the lap."""
    grid = grid_for(1000.0)
    delta = np.zeros_like(grid)
    delta[200:] = 4.0                              # at 400 m, far from the corner
    assert time_lost_over(delta, grid, _corner(900.0, 960.0, 100.0)) == pytest.approx(
        0.0, abs=1e-9
    )


@pytest.mark.corpus
def test_delta_over_two_real_laps_matches_their_lap_times(monza_q_file):
    with Session.open(monza_q_file) as s:
        length = s.track_length_m
        fast = next(l for l in s.laps if l.number == 2)
        slow = next(l for l in s.laps if l.number == 1)
        d = delta_s(build_trace(s, fast, length), build_trace(s, slow, length))
    assert d[-1] == pytest.approx(slow.duration_s - fast.duration_s, abs=0.3)
