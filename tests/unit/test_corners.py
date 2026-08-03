import numpy as np
import pytest

from lmu_telemetry.core.corners import detect_corners
from lmu_telemetry.core.geometry import GRID_STEP_M, curvature, grid_for


def _oval(straight_m: float, radius_m: float):
    """A rounded rectangle: two straights joined by two 180 degree bends."""
    bend = np.pi * radius_m
    total = 2 * straight_m + 2 * bend
    grid = grid_for(total)
    x, y = [], []
    for d in grid:
        if d < straight_m:
            x.append(d); y.append(0.0)
        elif d < straight_m + bend:
            t = (d - straight_m) / radius_m
            x.append(straight_m + np.sin(t) * radius_m)
            y.append(radius_m - np.cos(t) * radius_m)
        elif d < 2 * straight_m + bend:
            x.append(straight_m - (d - straight_m - bend)); y.append(2 * radius_m)
        else:
            t = (d - 2 * straight_m - bend) / radius_m
            x.append(-np.sin(t) * radius_m)
            y.append(2 * radius_m - (radius_m - np.cos(t) * radius_m))
    return np.array(x), np.array(y), grid


def test_an_oval_has_exactly_two_corners():
    x, y, grid = _oval(600.0, 120.0)
    corners = detect_corners(curvature(x, y), grid)
    assert len(corners) == 2


def test_oval_corners_report_the_geometric_radius():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid):
        assert c.radius_m == pytest.approx(120.0, rel=0.15)


def test_each_oval_corner_turns_about_180_degrees():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid):
        assert c.heading_deg == pytest.approx(180.0, abs=25.0)


def test_a_straight_track_has_no_corners():
    grid = grid_for(2000.0)
    corners = detect_corners(np.zeros_like(grid), grid)
    assert corners == []


def test_a_gentle_bend_wider_than_the_radius_limit_is_not_a_corner():
    """A 900 m radius sweep is a straight with a kink, not a corner."""
    grid = grid_for(1200.0)
    corners = detect_corners(np.full_like(grid, 1.0 / 900.0), grid)
    assert corners == []


def test_corners_are_numbered_in_track_order():
    x, y, grid = _oval(600.0, 120.0)
    corners = detect_corners(curvature(x, y), grid)
    assert [c.index for c in corners] == [1, 2]
    assert [c.name for c in corners] == ["T1", "T2"]
    assert corners[0].start_m < corners[1].start_m


def test_direction_follows_the_sign_of_curvature():
    grid = grid_for(400.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 60.0    # left
    left = detect_corners(k, grid)
    right = detect_corners(-k, grid)
    assert left[0].direction == "L"
    assert right[0].direction == "R"


def test_apex_sits_at_the_tightest_point():
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 100.0
    k[99] = 1.0 / 40.0     # a single unambiguous tightest sample
    c = detect_corners(k, grid)[0]
    assert c.apex_m == pytest.approx(grid[99], abs=GRID_STEP_M)
