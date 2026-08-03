import numpy as np
import pytest

from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    curvature,
    grid_for,
    heading_change_deg,
    smooth_closed,
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
    x, y, grid = _circle(200.0)
    assert heading_change_deg(curvature(x, y), grid) == pytest.approx(360.0, abs=5.0)


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


def test_smoothing_wraps_around_because_a_lap_is_closed():
    """Without wrap-around the start/finish line would show a false corner."""
    values = np.ones(100)
    assert np.allclose(smooth_closed(values, 9), 1.0)


def test_smoothing_preserves_length():
    values = np.random.default_rng(0).random(250)
    assert len(smooth_closed(values, 15)) == 250
