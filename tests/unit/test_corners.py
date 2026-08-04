import numpy as np
import pytest

from lmu_telemetry.core.corners import (
    CORNER_MIN_HEADING_DEG,
    MERGE_GAP_M,
    detect_corners,
)
from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    curvature,
    grid_for,
    heading_change_deg,
    turn_rad,
)


def _detect(kappa, grid):
    """``detect_corners`` for a curvature array written out by hand.

    Curvature is heading change per metre of arc, so a curvature array laid on
    a uniform grid turns ``kappa * GRID_STEP_M`` at each sample. Deriving the
    turning array from kappa here ties the two together in exactly the way
    ``geometry.curvature`` and ``geometry.turn_rad`` are tied together for a
    real line, so a test that writes down a shape does not also have to write
    down its turning.
    """
    kappa = np.asarray(kappa, dtype=float)
    return detect_corners(kappa, grid, kappa * GRID_STEP_M)


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
    corners = detect_corners(curvature(x, y), grid, turn_rad(x, y))
    assert len(corners) == 2


def test_oval_corners_report_the_geometric_radius():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid, turn_rad(x, y)):
        assert c.radius_m == pytest.approx(120.0, rel=0.15)


def test_each_oval_corner_turns_about_180_degrees():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid, turn_rad(x, y)):
        assert c.heading_deg == pytest.approx(180.0, abs=25.0)


def test_a_straight_track_has_no_corners():
    grid = grid_for(2000.0)
    corners = _detect(np.zeros_like(grid), grid)
    assert corners == []


def test_a_gentle_bend_wider_than_the_radius_limit_is_not_a_corner():
    """A 900 m radius sweep is a straight with a kink, not a corner."""
    grid = grid_for(1200.0)
    corners = _detect(np.full_like(grid, 1.0 / 900.0), grid)
    assert corners == []


def test_corners_are_numbered_in_track_order():
    x, y, grid = _oval(600.0, 120.0)
    corners = detect_corners(curvature(x, y), grid, turn_rad(x, y))
    assert [c.index for c in corners] == [1, 2]
    assert [c.name for c in corners] == ["T1", "T2"]
    # The oval's second bend ends exactly at the lap length, so smoothing
    # carries it a sample past the start/finish line: it is a corner that
    # contains d=0, and therefore the corner the lap starts in.
    assert corners[0].wraps
    assert not corners[1].wraps
    assert corners[0].end_m <= corners[1].start_m
    assert corners[1].start_m < corners[1].end_m


def test_direction_follows_the_sign_of_curvature():
    grid = grid_for(400.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 60.0    # left
    left = _detect(k, grid)
    right = _detect(-k, grid)
    assert left[0].direction == "L"
    assert right[0].direction == "R"


def test_apex_sits_at_the_tightest_point():
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 100.0
    k[99] = 1.0 / 40.0     # a single unambiguous tightest sample
    c = _detect(k, grid)[0]
    assert c.apex_m == pytest.approx(grid[99], abs=GRID_STEP_M)


# --- SPLIT_HEADING_GATE_DEG -------------------------------------------------
#
# The tests above never exercise the gate: every block they hand the splitter
# is a flat plateau, so find_peaks sees fewer than two peaks and _split_once
# bails out through its `len(peaks) < 2` fallback before the gate is even
# consulted. The pair below builds a block with two genuine, well-separated
# curvature peaks and a valley deep enough that _split_once *would* cut there
# - so whichever way the block comes out, it was the heading gate that
# decided it, not the peak search.


def _two_peak_curvature(scale: float):
    """Two curvature peaks separated by a valley, on grid_for(1000.0).

    Baseline of 1/250 over samples 100-300, raised to 1/150 around samples
    140 and 260 - the Curva Grande shape: two peaks that read as separate
    bends to a peak-prominence search, but whose combined turn may or may not
    clear the heading gate depending on *scale*. Scaling multiplies every
    curvature value equally, which scales total heading change linearly
    without changing the shape find_peaks sees (same relative peaks and
    valley) - so the two tests built from this differ *only* in whether the
    gate fires, not in topology.
    """
    grid = grid_for(1000.0)
    k = np.zeros_like(grid)
    k[100:300] = (1.0 / 250.0) * scale
    k[135:145] = (1.0 / 150.0) * scale
    k[255:265] = (1.0 / 150.0) * scale
    return k, grid


def test_gate_holds_a_shallow_two_peak_block_together():
    """Curva Grande: two curvature peaks, but well under 180 degrees total.

    Every value here sits inside the corner radius limit, find_peaks finds
    two well-separated peaks with ample prominence, and the valley between
    them is deep enough that _split_once would happily cut there. Only the
    heading gate stops it - so the fact that this comes back as one corner
    pins the gate, not the peak search.
    """
    k, grid = _two_peak_curvature(scale=1.0)
    heading = heading_change_deg(k[100:300] * GRID_STEP_M)
    assert heading < 180.0

    corners = _detect(k, grid)
    assert len(corners) == 1


def test_gate_splits_the_same_shape_scaled_past_it():
    """The identical two-peak topology, scaled until it clears 180 degrees.

    Same peaks, same valley, same relative shape as the "held together" test
    above - only the magnitude changed. That total heading change alone
    flips the outcome from one corner to two is the discrimination: nothing
    about the peak search changed between the two tests.
    """
    k, grid = _two_peak_curvature(scale=2.0)
    heading = heading_change_deg(k[100:300] * GRID_STEP_M)
    assert heading > 180.0

    corners = _detect(k, grid)
    assert len(corners) == 2


# --- MERGE_GAP_M -------------------------------------------------------------


def test_merge_gap_below_threshold_merges_same_signed_bends():
    """Two same-signed bends 22 m apart (< MERGE_GAP_M = 40 m) are one corner."""
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[100:150] = 1.0 / 100.0   # bend 1: samples 100-149
    k[160:210] = 1.0 / 100.0   # bend 2: samples 160-209, gap = 22 m

    gap_m = (grid[160] - grid[149])
    assert gap_m < MERGE_GAP_M

    corners = _detect(k, grid)
    assert len(corners) == 1
    # combined heading must stay under the split gate, or the merge would
    # just be undone again by _split.
    assert corners[0].heading_deg < 180.0


def test_merge_gap_above_threshold_keeps_bends_separate():
    """The same two bends 52 m apart (> MERGE_GAP_M = 40 m) stay two corners."""
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[100:150] = 1.0 / 100.0   # bend 1: samples 100-149
    k[175:225] = 1.0 / 100.0   # bend 2: samples 175-224, gap = 52 m

    gap_m = (grid[175] - grid[149])
    assert gap_m > MERGE_GAP_M

    corners = _detect(k, grid)
    assert len(corners) == 2


def test_opposite_signed_bends_never_merge():
    """_merge requires the same sign, no matter how close two bends are."""
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[100:150] = 1.0 / 100.0    # left bend
    k[160:210] = -1.0 / 100.0   # right bend, only 22 m away

    corners = _detect(k, grid)
    assert len(corners) == 2
    assert {c.direction for c in corners} == {"L", "R"}


# --- the start/finish line ----------------------------------------------------
#
# d=0 is an arbitrary point on the track, not a feature of it - the same
# reasoning that makes geometry.smooth_closed wrap. A corner may therefore
# contain it, and must come out as the same corner it would be anywhere else
# on the lap. Every track in the corpus happens to start on a straight, so
# only synthetic curvature can exercise this.


def _wrapped_and_middle(width_before: int, width_after: int, kappa_value: float):
    """The same bend twice: once straddling d=0, once in the middle of the lap.

    Both get exactly ``width_before + width_after`` samples of identical
    curvature, so every measurement over them must agree.
    """
    grid = grid_for(1000.0)
    n = len(grid)
    wrapped = np.zeros_like(grid)
    wrapped[n - width_before :] = kappa_value
    wrapped[:width_after] = kappa_value

    middle = np.zeros_like(grid)
    middle[200 : 200 + width_before + width_after] = kappa_value
    return wrapped, middle, grid


def test_a_corner_straddling_the_start_finish_line_is_one_corner():
    """Scanned linearly this bend is cut in half by an arbitrary line."""
    wrapped, middle, grid = _wrapped_and_middle(20, 30, 1.0 / 60.0)

    mid_corners = _detect(middle, grid)
    wrap_corners = _detect(wrapped, grid)

    assert len(mid_corners) == 1
    assert len(wrap_corners) == 1
    a, b = wrap_corners[0], mid_corners[0]
    assert a.heading_deg == pytest.approx(b.heading_deg, abs=0.5)
    assert a.radius_m == pytest.approx(b.radius_m, rel=0.01)
    assert a.direction == b.direction
    # A corner that contains d=0 runs off the end of the lap and back to the
    # start, so it is the one case where start_m sits after end_m.
    assert a.start_m > a.end_m


def test_a_short_corner_straddling_the_start_finish_line_does_not_vanish():
    """Both halves fall under CORNER_MIN_LENGTH_M, so a linear scan drops
    the corner entirely - and silently, which is the worse failure."""
    wrapped, middle, grid = _wrapped_and_middle(10, 10, 1.0 / 50.0)

    assert len(_detect(middle, grid)) == 1
    corners = _detect(wrapped, grid)
    assert len(corners) == 1
    assert corners[0].heading_deg > CORNER_MIN_HEADING_DEG


def test_a_wrapping_corner_is_measured_over_the_whole_joined_region():
    """Not over whichever half happens to be longer."""
    wrapped, middle, grid = _wrapped_and_middle(20, 30, 1.0 / 60.0)
    wrapped[-10:] = 1.0 / 25.0  # the tightest point sits before d=0

    corner = _detect(wrapped, grid)[0]
    assert corner.radius_m == pytest.approx(25.0, rel=0.05)
    assert corner.apex_m > 900.0  # apex found in the pre-d=0 half
    assert corner.start_m > corner.end_m


def test_opposite_signed_bends_across_the_start_finish_line_stay_separate():
    """Joining is for one corner cut in half, not for two adjacent corners."""
    grid = grid_for(1000.0)
    k = np.zeros_like(grid)
    k[-25:] = 1.0 / 60.0
    k[:25] = -1.0 / 60.0

    corners = _detect(k, grid)
    assert len(corners) == 2
    assert {c.direction for c in corners} == {"L", "R"}


def test_a_wrapping_corner_is_first_and_corners_stay_in_track_order():
    """A corner containing d=0 is the lap's first corner; the ordering
    guarantee detect_corners makes must survive it."""
    grid = grid_for(1000.0)
    k = np.zeros_like(grid)
    k[-20:] = 1.0 / 60.0
    k[:30] = 1.0 / 60.0     # wraps d=0
    k[200:250] = 1.0 / 60.0
    k[350:400] = 1.0 / 60.0

    corners = _detect(k, grid)
    assert [c.index for c in corners] == [1, 2, 3]
    assert [c.name for c in corners] == ["T1", "T2", "T3"]
    assert corners[0].start_m > corners[0].end_m       # the wrapping one
    assert corners[0].end_m <= corners[1].start_m
    assert corners[1].end_m <= corners[2].start_m


# --- _split recursion ---------------------------------------------------------
#
# _split calls itself on each part _split_once produces, bounded by
# SPLIT_MAX_DEPTH. Every case above only ever needs one pass: _split_once
# cuts at *every* validated valley it finds in a single call (its `for a, b
# in zip(peaks, peaks[1:])` loop is not one-cut-per-call), so three genuine,
# independently-detectable peaks would simply be sliced into three parts on
# the first pass - no recursion needed.
#
# A genuine second-level cut requires a peak that find_peaks does not detect
# on the first pass but does detect on a later one. That happens here via
# find_peaks' *prominence* filter: prominence is measured relative to the
# tallest point in whatever segment is currently being searched. A very tall
# third peak (D) inflates that segment maximum enough that a real second
# peak (B) - genuinely present, just modest - falls below the 5% prominence
# threshold and is not detected. The valley between the two peaks that *are*
# detected (A and D) is deep enough to cut, producing a part that still
# contains both A and B fused together with a heading over the gate. On the
# recursive call into that part, D is gone, the local maximum is much
# smaller, and B's prominence now clears the (now lower) threshold - so a
# genuine second cut happens, splitting A from B.


def test_split_recursion_performs_a_genuine_second_level_cut():
    grid = grid_for(1800.0)
    k = np.zeros_like(grid)
    k[100:290] = 1.0 / 95.0     # baseline shared by peaks A and B
    k[290:799] = 1.0 / 125.0    # lower baseline on D's side
    k[145:156] = 1.0 / 60.0     # peak A - tall enough to survive pass 1
    k[245:256] = 0.0125         # peak B - real, but not prominent next to D
    k[595:606] = 1.0 / 15.0     # peak D - dominates pass 1's prominence scale

    # Pass 1 detects only A and D (B's prominence is swamped by D) and cuts
    # once between them, leaving A and B fused in a part that is still over
    # the gate. Only the recursive call - with D out of the segment - finds
    # B's prominence large enough to detect and cut a second time.
    region_heading = heading_change_deg(k[100:799] * GRID_STEP_M)
    assert region_heading > 180.0

    corners = _detect(k, grid)
    assert len(corners) == 3
