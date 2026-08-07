"""Where the track may be cut, and where it may not.

A fast left-right is one connected act: how you enter the right is decided by
how you left the left. Take the left from one lap and the right from another
and the result is a lap nobody could drive, and a target nobody could reach.
These tests are that rule.
"""

import numpy as np
import pytest

from lmu_telemetry.core.blocks import BLOCK_THROTTLE_M, split_into_blocks
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for

LAP_M = 3000.0


def _index(distance_m: float) -> int:
    return int(distance_m / GRID_STEP_M)


def _corner(index, start_m, end_m) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=start_m,
        apex_m=(start_m + end_m) / 2, end_m=end_m,
        radius_m=80.0, heading_deg=90.0, direction="L",
    )


def _trace(throttle_from_to, pace_kmh=180.0):
    """A lap at a constant pace with full throttle over the given ranges."""
    from lmu_telemetry.core.trace import LapTrace

    grid = grid_for(LAP_M)
    n = len(grid)
    throttle = np.zeros(n)
    for first_m, last_m in throttle_from_to:
        throttle[_index(first_m) : _index(last_m)] = 1.0
    speed = np.full(n, pace_kmh)
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))
    return LapTrace(
        lap=None, grid=grid, time_s=time_s, speed_kmh=speed,
        throttle=throttle, brake=np.zeros(n), steering=np.zeros(n),
    )


def test_a_chicane_is_one_block():
    """Never onto full power between the two halves.

    This is the case the whole design exists for. Split here and the ideal lap
    claims a time built from an entry that never happened.
    """
    corners = [_corner(1, 500.0, 560.0), _corner(2, 570.0, 630.0)]
    trace = _trace([(0.0, 480.0), (700.0, 3000.0)])   # flat before and after, not between
    blocks = split_into_blocks([trace], corners)
    assert len(blocks) == 1
    assert [c.index for c in blocks[0].corners] == [1, 2]


def test_two_corners_with_a_straight_between_them_separate():
    corners = [_corner(1, 500.0, 560.0), _corner(2, 1500.0, 1560.0)]
    trace = _trace([(0.0, 480.0), (600.0, 1480.0), (1600.0, 3000.0)])
    blocks = split_into_blocks([trace], corners)
    assert len(blocks) == 2
    assert [c.index for c in blocks[0].corners] == [1]
    assert [c.index for c in blocks[1].corners] == [2]


def test_a_stab_of_throttle_between_two_corners_does_not_separate_them():
    """A short crack of throttle between the halves of a chicane is not a
    straight, and BLOCK_THROTTLE_M is what tells them apart."""
    assert BLOCK_THROTTLE_M > 20.0, "or a stab of throttle reads as a straight"
    corners = [_corner(1, 500.0, 560.0), _corner(2, 600.0, 660.0)]
    trace = _trace([(0.0, 480.0), (570.0, 590.0), (700.0, 3000.0)])   # 20 m stab
    blocks = split_into_blocks([trace], corners)
    assert len(blocks) == 1


def test_a_gap_only_one_lap_took_flat_stays_joined():
    """The cut has to be safe for every lap being spliced.

    One lap lifting there means that lap was still connected through the gap,
    and its block time was driven in a context a cut would take it out of.
    """
    corners = [_corner(1, 500.0, 560.0), _corner(2, 1500.0, 1560.0)]
    flat = _trace([(0.0, 480.0), (600.0, 1480.0), (1600.0, 3000.0)])
    lifted = _trace([(0.0, 480.0), (600.0, 640.0), (1600.0, 3000.0)])
    assert len(split_into_blocks([flat], corners)) == 2, "the flat lap alone splits"
    assert len(split_into_blocks([flat, lifted], corners)) == 1


def test_the_cut_sits_in_the_full_throttle_stretch_all_laps_share():
    """Not at a corner's end, and not where only one lap was flat."""
    corners = [_corner(1, 500.0, 560.0), _corner(2, 1500.0, 1560.0)]
    early = _trace([(0.0, 480.0), (600.0, 1200.0), (1600.0, 3000.0)])
    late = _trace([(0.0, 480.0), (1000.0, 1480.0), (1600.0, 3000.0)])
    blocks = split_into_blocks([early, late], corners)
    assert len(blocks) == 2
    # Shared stretch is 1000-1200 m, so the cut belongs at its middle.
    cut = blocks[0].end_m
    assert 1000.0 <= cut <= 1200.0
    assert cut == pytest.approx(1100.0, abs=2 * GRID_STEP_M)


def test_every_corner_lands_in_exactly_one_block():
    """A corner falling through the segmentation is time belonging to no
    block, silently absent from the ideal lap."""
    corners = [
        _corner(1, 400.0, 460.0), _corner(2, 470.0, 530.0),
        _corner(3, 1500.0, 1560.0), _corner(4, 2200.0, 2260.0),
    ]
    trace = _trace([(0.0, 380.0), (600.0, 1480.0), (1600.0, 2180.0), (2300.0, 3000.0)])
    blocks = split_into_blocks([trace], corners)
    placed = [c.index for block in blocks for c in block.corners]
    assert sorted(placed) == [1, 2, 3, 4]
    assert len(placed) == len(set(placed))


def test_a_lap_with_no_full_throttle_anywhere_is_one_block():
    """Nothing may be spliced, and the honest answer is one block covering the
    lap rather than a segmentation that pretends otherwise."""
    corners = [_corner(1, 500.0, 560.0), _corner(2, 1500.0, 1560.0)]
    blocks = split_into_blocks([_trace([])], corners)
    assert len(blocks) == 1
    assert [c.index for c in blocks[0].corners] == [1, 2]
