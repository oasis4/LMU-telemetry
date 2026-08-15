"""Turning a template into pixels.

The whole value of the strip is that the grey line and the driver's line sit
over the same metres. That is arithmetic, and it is tested here without a
window - `_strip_points` is static for exactly that reason.
"""

import numpy as np
import pytest

from lmu_telemetry.live.overlay import Overlay


def _points(offsets, values, length_m=400.0, width=600, top=0, height=40):
    flat = Overlay._strip_points(
        np.asarray(offsets, dtype=float), np.asarray(values, dtype=float),
        length_m, width, top, height,
    )
    return list(zip(flat[0::2], flat[1::2]))


def test_the_window_is_stretched_across_the_full_width():
    got = _points([0.0, 200.0, 400.0], [0.0, 0.0, 0.0], length_m=400.0, width=600)
    assert got[0][0] == pytest.approx(0.0)
    assert got[-1][0] == pytest.approx(600.0)
    assert got[1][0] == pytest.approx(300.0)


def test_the_two_lines_land_on_the_same_metres():
    """The property the strip exists for. A reference sampled every 2 m and a
    driver's line stopping partway must agree wherever both have a point."""
    reference = _points(np.arange(0.0, 401.0, 2.0), np.zeros(201))
    own = _points(np.arange(0.0, 201.0, 2.0), np.zeros(101))
    for at in range(101):
        assert own[at][0] == pytest.approx(reference[at][0])


def test_full_brake_reaches_the_top_of_its_strip():
    got = _points([0.0, 400.0], [1.0, 1.0], top=10, height=40)
    assert all(y == pytest.approx(10.0) for _x, y in got)


def test_no_brake_sits_on_the_bottom_of_its_strip():
    got = _points([0.0, 400.0], [0.0, 0.0], top=10, height=40)
    assert all(y == pytest.approx(50.0) for _x, y in got)


def test_the_scale_is_fixed_and_not_stretched_to_the_data():
    """A 60 % application and a 90 % one must not be drawn the same height.
    Auto-scaling is what would make the template pretty and wrong."""
    soft = _points([0.0, 400.0], [0.6, 0.6], top=0, height=100)
    hard = _points([0.0, 400.0], [0.9, 0.9], top=0, height=100)
    assert soft[0][1] == pytest.approx(40.0)
    assert hard[0][1] == pytest.approx(10.0)


def test_a_value_outside_the_scale_is_clamped_not_drawn_off_the_strip():
    got = _points([0.0, 400.0], [1.4, -0.3], top=0, height=40)
    assert got[0][1] == pytest.approx(0.0)
    assert got[1][1] == pytest.approx(40.0)


def test_a_single_point_still_produces_a_drawable_line():
    """tkinter refuses a line with one point; the driver has exactly one
    sample for the first frame of every window."""
    got = _points([0.0], [0.5])
    assert len(got) >= 2
