"""The best of several laps, block by block, and what the joins cost.

A target time is only worth having if it is one somebody could reach. Every
seam here is a claim that the lap after it could have been driven from the
entry the lap before it delivered - so every seam is measured and reported,
sound or not.
"""

import numpy as np
import pytest

from lmu_telemetry.core.blocks import SEAM_SPEED_KMH, ideal_lap, split_into_blocks
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import LapTrace, build_trace

LAP_M = 3000.0


def _index(distance_m: float) -> int:
    return int(distance_m / GRID_STEP_M)


def _corner(index, start_m, end_m) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=start_m,
        apex_m=(start_m + end_m) / 2, end_m=end_m,
        radius_m=80.0, heading_deg=90.0, direction="L",
    )


def _lap(number, throttle_from_to, slow_stretches=(), pace_kmh=180.0):
    """A lap at *pace_kmh* except where a stretch says otherwise."""

    class _Lap:
        pass

    grid = grid_for(LAP_M)
    n = len(grid)
    throttle = np.zeros(n)
    for first_m, last_m in throttle_from_to:
        throttle[_index(first_m) : _index(last_m)] = 1.0
    speed = np.full(n, pace_kmh)
    for first_m, last_m, kmh in slow_stretches:
        speed[_index(first_m) : _index(last_m)] = kmh
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))

    lap = _Lap()
    lap.number = number
    lap.duration_s = float(time_s[-1] + GRID_STEP_M / (speed[-1] / 3.6))
    return LapTrace(
        lap=lap, grid=grid, time_s=time_s, speed_kmh=speed,
        throttle=throttle, brake=np.zeros(n), steering=np.zeros(n),
    )


FLAT = [(0.0, 480.0), (600.0, 1480.0), (1600.0, 3000.0)]
CORNERS = [_corner(1, 500.0, 560.0), _corner(2, 1500.0, 1560.0)]


# -- block times -----------------------------------------------------------

def test_the_block_times_of_one_lap_sum_to_that_lap():
    """The segmentation must not lose or double-count a metre.

    If these do not sum, every figure built on them is wrong by the remainder,
    and wrong in a direction nothing else would reveal.
    """
    lap = _lap(1, FLAT)
    result = ideal_lap([lap], CORNERS)
    total = sum(choice.time_s for choice in result.blocks)
    assert total == pytest.approx(lap.lap.duration_s, abs=1e-6)
    assert result.ideal_s == pytest.approx(lap.lap.duration_s, abs=1e-6)


def test_the_ideal_equals_the_only_lap_when_there_is_only_one():
    lap = _lap(1, FLAT)
    result = ideal_lap([lap], CORNERS)
    assert result.gain_s == pytest.approx(0.0, abs=1e-9)
    assert {choice.lap_number for choice in result.blocks} == {1}


def test_the_ideal_is_never_slower_than_the_best_real_lap():
    """It is a minimum over laps, block by block, and a real lap is one of the
    candidates - so at worst the ideal equals it."""
    a = _lap(1, FLAT, slow_stretches=[(500.0, 560.0, 90.0)])
    b = _lap(2, FLAT, slow_stretches=[(1500.0, 1560.0, 90.0)])
    result = ideal_lap([a, b], CORNERS)
    assert result.ideal_s <= result.best_lap_s + 1e-9
    assert result.gain_s >= -1e-9


def test_each_block_is_taken_from_whichever_lap_was_quickest_through_it():
    """And says which, because a target with no provenance cannot be checked."""
    a = _lap(1, FLAT, slow_stretches=[(500.0, 560.0, 90.0)])     # slow in T1
    b = _lap(2, FLAT, slow_stretches=[(1500.0, 1560.0, 90.0)])   # slow in T2
    result = ideal_lap([a, b], CORNERS)

    by_corner = {
        choice.block.corners[0].index: choice.lap_number
        for choice in result.blocks
        if choice.block.corners
    }
    assert by_corner[1] == 2, "lap 2 was quicker through T1"
    assert by_corner[2] == 1, "lap 1 was quicker through T2"
    assert result.gain_s > 0.0


# -- seams -----------------------------------------------------------------

def test_a_seam_between_two_blocks_from_the_same_lap_is_sound():
    """Nothing was spliced there at all."""
    lap = _lap(1, FLAT)
    result = ideal_lap([lap, _lap(2, FLAT, pace_kmh=120.0)], CORNERS)
    assert all(seam.sound for seam in result.seams)
    assert result.sound


def test_a_seam_where_the_laps_arrive_at_different_speeds_is_reported_unsound():
    """The block after the seam was driven from an entry the ideal lap does
    not deliver, so its time is not transferable. Saying so is the point: the
    alternative is a target that looks reachable and is not.

    The seams here sit at 1040 m and 2540 m. Lap 1 throws away the first block
    and lap 2 the second, so the ideal really does splice - an earlier version
    of this test had both blocks fall to one lap, which left nothing joined and
    a spread of zero that looked like the rule failing.
    """
    a = _lap(1, FLAT, slow_stretches=[(300.0, 800.0, 100.0)])
    # Quicker through the first block, but crawling right at the 1040 m seam.
    b = _lap(2, FLAT, slow_stretches=[(1030.0, 1050.0, 60.0),
                                      (1200.0, 1560.0, 100.0)])
    result = ideal_lap([a, b], CORNERS)

    taken = {choice.block.start_m: choice.lap_number for choice in result.blocks}
    assert len(set(taken.values())) == 2, f"nothing was spliced: {taken}"

    at_seam = {seam.at_m: seam for seam in result.seams}
    assert not at_seam[1040.0].sound, at_seam[1040.0]
    assert at_seam[1040.0].speed_spread_kmh > SEAM_SPEED_KMH
    assert not result.sound


def test_every_seam_carries_the_spread_it_was_judged_on():
    a = _lap(1, FLAT, slow_stretches=[(500.0, 560.0, 90.0)])
    b = _lap(2, FLAT, slow_stretches=[(1500.0, 1560.0, 90.0)])
    for seam in ideal_lap([a, b], CORNERS).seams:
        assert seam.speed_spread_kmh >= 0.0
        assert seam.sound == (seam.speed_spread_kmh <= SEAM_SPEED_KMH)


def test_there_is_one_seam_for_every_block():
    """Each block is entered somewhere, including the one holding the line."""
    a = _lap(1, FLAT, slow_stretches=[(500.0, 560.0, 90.0)])
    b = _lap(2, FLAT, slow_stretches=[(1500.0, 1560.0, 90.0)])
    result = ideal_lap([a, b], CORNERS)
    assert len(result.seams) == len(result.blocks)


# -- real laps -------------------------------------------------------------

def _monza(path):
    with Session.open(path) as session:
        model = build_track_model([session])
        laps = {lap.number: lap for lap in session.laps}
        traces = [build_trace(session, laps[n], model.track_length_m) for n in (1, 2)]
    return model, traces


def test_monza_splits_into_blocks_that_hold_its_chicanes_together(monza_q_file):
    """Both Variantes and Ascari are one block each. Splitting a chicane is
    the failure this whole module exists to prevent."""
    model, traces = _monza(monza_q_file)
    blocks = split_into_blocks(traces, model.corners)
    held = {c.index: b.index for b in blocks for c in b.corners}

    assert 1 < len(blocks) < len(model.corners)
    assert held[1] == held[2], "Variante del Rettifilo is one block"
    assert held[4] == held[5], "Variante della Roggia is one block"
    assert held[8] == held[9] == held[10], "Ascari is one block"
    assert len({held[3], held[6], held[7], held[11]}) == 4, "these stand alone"


def test_the_ideal_lap_of_real_laps_beats_neither_physics_nor_the_best_lap(monza_q_file):
    model, traces = _monza(monza_q_file)
    result = ideal_lap(traces, model.corners)

    assert result.ideal_s <= result.best_lap_s + 1e-9
    assert result.gain_s >= 0.0
    assert result.best_lap_number in {t.lap.number for t in traces}
    # Every block time has to be one a lap actually recorded, not an average.
    assert all(choice.lap_number in {t.lap.number for t in traces}
               for choice in result.blocks)


def test_every_seam_of_a_real_ideal_lap_is_reported_one_way_or_the_other(monza_q_file):
    """Sound or not, never absent - an unreported seam is an unexamined join."""
    model, traces = _monza(monza_q_file)
    result = ideal_lap(traces, model.corners)
    assert len(result.seams) == len(result.blocks)
    for seam in result.seams:
        assert isinstance(seam.sound, bool)
        assert seam.speed_spread_kmh >= 0.0
