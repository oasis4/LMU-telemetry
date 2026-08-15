import numpy as np
import pytest

from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    curvature,
    grid_for,
    heading_change_deg,
    smooth_closed,
    turn_rad,
    winding_number,
)


def _circle(radius_m: float, step_m: float = GRID_STEP_M):
    """A closed circle sampled at *step_m* along its circumference."""
    circumference = 2.0 * np.pi * radius_m
    grid = grid_for(circumference, step_m)
    theta = grid / radius_m
    return np.cos(theta) * radius_m, np.sin(theta) * radius_m, grid


def test_circle_has_constant_curvature_equal_to_one_over_radius():
    x, y, _ = _circle(200.0)
    k = curvature(x, y)
    interior = k[20:-20]  # ends are affected by the smoothing wrap
    assert np.allclose(interior, 1.0 / 200.0, rtol=0.02)


def test_curvature_scales_inversely_with_radius():
    for radius in (50.0, 100.0, 400.0):
        x, y, _ = _circle(radius)
        k = curvature(x, y)[20:-20]
        assert np.median(np.abs(k)) == pytest.approx(1.0 / radius, rel=0.02)


def test_a_closed_circle_turns_exactly_360_degrees():
    x, y, _ = _circle(200.0)
    assert heading_change_deg(turn_rad(x, y)) == pytest.approx(360.0, abs=1e-9)


def test_heading_comes_from_the_tangent_not_from_integrating_curvature():
    """The same circle, sampled so that smoothing visibly cuts its corners.

    Integrating curvature over the distance grid measures the curvature of the
    *smoothed* line but weights it by *unsmoothed* distance, so it reads high
    by however much the smoothing shortened the line - and how much that is
    depends on how tightly the line turns, which is why no single circuit
    exposes it. A 15 m radius circle reads 424 degrees that way; on the corpus
    the same effect put COTA National at 437 and Monza at 361. The tangent
    estimator returns exactly 360 at every radius below.
    """
    for radius, integrated_at_least in ((15.0, 400.0), (20.0, 385.0), (25.0, 375.0)):
        x, y, grid = _circle(radius)
        integrated = float(np.degrees(abs(np.trapezoid(curvature(x, y), grid))))
        assert integrated > integrated_at_least, f"radius {radius} m"
        assert heading_change_deg(turn_rad(x, y)) == pytest.approx(360.0, abs=1e-9)


def test_curvature_and_turning_agree_about_how_far_the_line_turned():
    """kappa * ds and the turning array must integrate to the same angle.

    They are derived from one primitive precisely so this holds. If curvature
    were computed independently - from second derivatives, say - the two could
    drift apart, and a corner's radius and its heading would then describe
    slightly different corners.
    """
    x, y, _ = _circle(120.0)
    kappa = curvature(x, y)
    arc = 2.0 * np.pi * 120.0
    assert float(np.degrees(abs(kappa.mean() * arc))) == pytest.approx(360.0, rel=0.02)


def test_curvature_sign_distinguishes_left_from_right():
    x, y, _ = _circle(200.0)
    left = curvature(x, y)[20:-20]
    right = curvature(x, -y)[20:-20]   # mirrored track turns the other way
    assert np.median(left) > 0
    assert np.median(right) < 0


def test_a_straight_line_has_no_curvature():
    grid = grid_for(1000.0)
    x = grid.copy()
    y = np.zeros_like(grid)
    assert np.allclose(curvature(x, y)[20:-20], 0.0, atol=1e-6)


def test_smoothing_leaves_a_constant_signal_untouched():
    values = np.ones(100)
    assert np.allclose(smooth_closed(values, 9), 1.0)


def test_smoothing_wraps_around_because_a_lap_is_closed():
    """A spike at the very end must bleed into the start of the array.

    This is what distinguishes wrap-around from edge padding. A constant
    signal cannot: averaging a constant gives the same answer under any
    padding scheme, so it would pass even if the wrap were removed.
    Without the wrap the start/finish line - an arbitrary point on the
    track - would show up as a phantom corner.
    """
    values = np.zeros(100)
    values[-1] = 1.0
    smoothed = smooth_closed(values, 9)
    assert smoothed[0] > 0.0, "the end of the lap did not reach its start"
    assert smoothed[0] == pytest.approx(1.0 / 9.0, rel=1e-6)
    # the far side of the lap stays untouched
    assert smoothed[50] == pytest.approx(0.0, abs=1e-12)


def test_smoothing_with_a_trivial_window_returns_the_input():
    values = np.array([1.0, 5.0, 2.0])
    out = smooth_closed(values, 1)
    assert np.allclose(out, values)
    assert out is not values     # a copy, so the caller cannot alias it


def test_smoothing_preserves_length():
    values = np.random.default_rng(0).random(250)
    assert len(smooth_closed(values, 15)) == 250


def test_a_lap_that_goes_round_once_has_winding_number_one():
    x, y, _ = _circle(200.0)
    assert winding_number(turn_rad(x, y)) == pytest.approx(1.0, abs=1e-9)


def test_winding_number_counts_a_second_loop():
    """Two laps' worth of line reads 2, not 1.

    This is what the winding check is for: a lap that failed to reset at the
    start/finish line and ran on into the next one covers the circuit twice,
    and no distance or duration check on its own can tell that apart from a
    long lap.
    """
    x, y, _ = _circle(200.0)
    doubled_x = np.concatenate([x, x])
    doubled_y = np.concatenate([y, y])
    assert winding_number(turn_rad(doubled_x, doubled_y)) == pytest.approx(2.0, abs=1e-9)


def test_winding_number_is_negative_running_the_other_way():
    x, y, _ = _circle(200.0)
    assert winding_number(turn_rad(x, -y)) == pytest.approx(-1.0, abs=1e-9)
