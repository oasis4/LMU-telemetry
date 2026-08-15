import numpy as np
import pytest

from lmu_telemetry.core.coaching import (
    BRAKE_POINT_NOISE_M,
    biggest_losses,
    compare_corners,
)
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.delta import delta_s
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for, span_indices
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import LapTrace, build_trace

LAP_M = 2000.0


def _corner(index, start_m, apex_m, end_m) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=start_m, apex_m=apex_m, end_m=end_m,
        radius_m=80.0, heading_deg=90.0, direction="L",
    )


def _trace(speed_kmh=None, throttle=None, brake=None, pace_kmh=150.0) -> LapTrace:
    grid = grid_for(LAP_M)
    n = len(grid)
    speed = np.full(n, pace_kmh) if speed_kmh is None else np.asarray(speed_kmh, float)
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))
    return LapTrace(
        lap=None, grid=grid, time_s=time_s, speed_kmh=speed,
        throttle=np.zeros(n) if throttle is None else np.asarray(throttle, float),
        brake=np.zeros(n) if brake is None else np.asarray(brake, float),
        steering=np.zeros(n),
    )


def _index(distance_m: float) -> int:
    return int(distance_m / GRID_STEP_M)


def _trail_brake(start_m, peak_m, release_m):
    """Pressure up at *start_m*, highest at *peak_m*, bled off by *release_m*."""
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(start_m) : _index(peak_m)] = 0.6
    brake[_index(peak_m)] = 1.0
    taper = np.linspace(1.0, 0.0, _index(release_m) - _index(peak_m) + 2)[1:-1]
    brake[_index(peak_m) + 1 : _index(release_m) + 1] = taper
    return brake


def test_the_release_and_the_trail_are_compared_like_the_brake_point():
    """All four markers are measured against the reference, not just the first."""
    reference = _trace(brake=_trail_brake(800.0, 840.0, 900.0))
    other = _trace(brake=_trail_brake(800.0, 840.0, 960.0))
    comparison = compare_corners(reference, other, [_corner(1, 900.0, 950.0, 1000.0)])[0]
    what = [d.what for d in comparison.differences]
    assert "brake release" in what
    assert "trail length" in what


def test_a_trail_difference_inside_the_noise_floor_is_not_reported():
    """Two positions on one trace, so the error is about twice a single one's."""
    reference = _trace(brake=_trail_brake(800.0, 840.0, 900.0))
    other = _trace(brake=_trail_brake(800.0, 840.0, 904.0))
    comparison = compare_corners(reference, other, [_corner(1, 900.0, 950.0, 1000.0)])[0]
    what = [d.what for d in comparison.differences]
    assert "trail length" not in what
    assert "brake release" not in what


def test_a_slower_corner_is_charged_the_time_it_cost():
    slow = np.full(len(grid_for(LAP_M)), 150.0)
    slow[_index(900.0) : _index(1000.0)] = 100.0
    reference, other = _trace(), _trace(speed_kmh=slow)
    corner = _corner(1, 900.0, 950.0, 1000.0)

    lost = compare_corners(reference, other, [corner])[0].lost_s
    expected = 100.0 / (100.0 / 3.6) - 100.0 / (150.0 / 3.6)
    assert lost == pytest.approx(expected, rel=0.05)


def test_a_faster_corner_shows_a_gain_not_a_loss():
    fast = np.full(len(grid_for(LAP_M)), 150.0)
    fast[_index(900.0) : _index(1000.0)] = 200.0
    result = compare_corners(_trace(), _trace(speed_kmh=fast), [_corner(1, 900.0, 950.0, 1000.0)])
    assert result[0].lost_s < 0.0
    assert "gained" in result[0].summary


def test_every_difference_carries_its_own_measured_amount():
    """A label without a number is not something a driver can act on."""
    brake_ref = np.zeros(len(grid_for(LAP_M)))
    brake_ref[_index(800.0) : _index(920.0)] = 0.8
    brake_other = np.zeros(len(grid_for(LAP_M)))
    brake_other[_index(830.0) : _index(920.0)] = 0.8

    slow = np.full(len(grid_for(LAP_M)), 150.0)
    slow[_index(900.0) : _index(1000.0)] = 120.0

    result = compare_corners(
        _trace(brake=brake_ref),
        _trace(speed_kmh=slow, brake=brake_other),
        [_corner(1, 900.0, 950.0, 1000.0)],
    )[0]
    assert result.differences, "a 30 m later brake point must be reported"
    for difference in result.differences:
        assert any(ch.isdigit() for ch in str(difference)), str(difference)
    assert any(ch.isdigit() for ch in result.summary)


def test_the_brake_point_difference_has_the_sign_of_braking_later():
    brake_ref = np.zeros(len(grid_for(LAP_M)))
    brake_ref[_index(800.0) : _index(920.0)] = 0.8
    brake_other = np.zeros(len(grid_for(LAP_M)))
    brake_other[_index(840.0) : _index(920.0)] = 0.8

    result = compare_corners(
        _trace(brake=brake_ref), _trace(brake=brake_other),
        [_corner(1, 900.0, 950.0, 1000.0)],
    )[0]
    brake = next(d for d in result.differences if d.what == "brake point")
    assert brake.amount == pytest.approx(40.0, abs=2 * GRID_STEP_M)
    assert brake.unit == "m"


def test_a_difference_inside_the_recordings_resolution_is_not_reported():
    """Lap Dist is 10 Hz, so 5-8 m separate its samples at racing speed.

    A brake-point difference of 2 m is below what was recorded, and reporting
    it would invite a driver to chase noise.
    """
    brake_ref = np.zeros(len(grid_for(LAP_M)))
    brake_ref[_index(800.0) : _index(920.0)] = 0.8
    brake_other = np.zeros(len(grid_for(LAP_M)))
    brake_other[_index(802.0) : _index(920.0)] = 0.8
    assert 2.0 < BRAKE_POINT_NOISE_M

    result = compare_corners(
        _trace(brake=brake_ref), _trace(brake=brake_other),
        [_corner(1, 900.0, 950.0, 1000.0)],
    )[0]
    assert not any(d.what == "brake point" for d in result.differences)


def test_one_driver_braking_and_the_other_not_is_not_a_difference_of_zero():
    brake_ref = np.zeros(len(grid_for(LAP_M)))
    brake_ref[_index(800.0) : _index(920.0)] = 0.8

    result = compare_corners(
        _trace(brake=brake_ref), _trace(), [_corner(1, 900.0, 950.0, 1000.0)]
    )[0]
    assert any("did not brake" in d.what for d in result.differences)


def test_braking_where_the_reference_did_not_is_reported_too():
    """The mirror of the case above, and a separate branch.

    Both directions matter: one says the reference carried more speed in, the
    other says this lap did, and collapsing either to a brake-point difference
    of zero would hide it.
    """
    brake_other = np.zeros(len(grid_for(LAP_M)))
    brake_other[_index(800.0) : _index(920.0)] = 0.8

    result = compare_corners(
        _trace(), _trace(brake=brake_other), [_corner(1, 900.0, 950.0, 1000.0)]
    )[0]
    assert any("braked where the reference did not" in d.what for d in result.differences)


def test_differences_come_out_largest_first():
    """The summary reads left to right, so the first one has to be the one
    worth looking at. A 40 km/h drop in minimum speed outranks a 6 m brake
    point, not the other way round."""
    brake_ref = np.zeros(len(grid_for(LAP_M)))
    brake_ref[_index(800.0) : _index(920.0)] = 0.8
    brake_other = np.zeros(len(grid_for(LAP_M)))
    brake_other[_index(806.0) : _index(920.0)] = 0.8      # 6 m later: small

    slow = np.full(len(grid_for(LAP_M)), 150.0)
    slow[_index(900.0) : _index(1000.0)] = 110.0          # 40 km/h down: large

    result = compare_corners(
        _trace(brake=brake_ref),
        _trace(speed_kmh=slow, brake=brake_other),
        [_corner(1, 900.0, 950.0, 1000.0)],
    )[0]
    assert [d.what for d in result.differences][:1] == ["minimum speed"]
    assert "brake point" in [d.what for d in result.differences]


def test_biggest_losses_puts_the_worst_corner_first():
    speed = np.full(len(grid_for(LAP_M)), 150.0)
    speed[_index(300.0) : _index(400.0)] = 130.0     # a small loss
    speed[_index(900.0) : _index(1000.0)] = 80.0     # a big one
    corners = [_corner(1, 300.0, 350.0, 400.0), _corner(2, 900.0, 950.0, 1000.0)]

    worst = biggest_losses(compare_corners(_trace(), _trace(speed_kmh=speed), corners), 1)
    assert [c.corner.index for c in worst] == [2]


def test_when_all_the_time_goes_in_corners_the_corners_account_for_the_lap():
    """Both losses sit wholly inside a corner and the straights are identical,
    so here - and only here - the corner charges must sum to the lap delta.
    Each corner is charged its own rise, so nothing is counted twice."""
    speed = np.full(len(grid_for(LAP_M)), 150.0)
    speed[_index(300.0) : _index(400.0)] = 130.0
    speed[_index(900.0) : _index(1000.0)] = 80.0
    reference, other = _trace(), _trace(speed_kmh=speed)
    corners = [_corner(1, 300.0, 350.0, 400.0), _corner(2, 900.0, 950.0, 1000.0)]

    comparisons = compare_corners(reference, other, corners)
    lap_delta = delta_s(reference, other)[-1]
    assert sum(c.lost_s for c in comparisons) == pytest.approx(lap_delta, rel=0.02)


@pytest.mark.corpus
def test_both_sides_of_a_real_comparison_use_the_same_corner_list(corpus_dir):
    """The old compare view fetched a corner list per side, so two drivers
    were measured against different corner definitions."""
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        laps = [l for l in s.laps if l.number in (2, 3)]
        a, b = (build_trace(s, lap, model.track_length_m) for lap in laps)
        comparisons = compare_corners(a, b, model.corners)

    assert len(comparisons) == len(model.corners)
    for comparison in comparisons:
        assert comparison.reference.corner is comparison.corner
        assert comparison.other.corner is comparison.corner


@pytest.mark.corpus
def test_a_corner_is_charged_exactly_the_delta_measured_inside_it(corpus_dir):
    """The charge equals the sum of the delta's steps within the corner.

    This is the property that lets a corner's loss be read on its own: it is
    the time that corner added, no more. It is not that the corners sum to the
    lap - they do not, and should not. On the two Monza laps below the corners
    together gain 2.52 s while the lap as a whole gains 0.80 s, because the
    straights gave 1.72 s of it back. An assertion that the corners bound the
    lap delta would be wrong, and passing it would mean the corners were
    swallowing the straights.
    """
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        laps = [l for l in s.laps if l.number in (2, 3)]
        a, b = (build_trace(s, lap, model.track_length_m) for lap in laps)
        comparisons = compare_corners(a, b, model.corners)
        delta = delta_s(a, b)

    steps = np.diff(delta)
    covered = np.zeros(len(delta), dtype=int)
    for comparison in comparisons:
        indices = span_indices(a.grid, comparison.corner.start_m, comparison.corner.end_m)
        covered[indices] += 1
        inside = steps[indices[:-1]] if len(indices) > 1 else np.zeros(0)
        if comparison.corner.start_m > comparison.corner.end_m:
            # the wrap seam is not a step the car took
            inside = np.concatenate(
                [steps[i[:-1]] for i in _wrap_pieces(a.grid, comparison.corner)]
            )
        assert comparison.lost_s == pytest.approx(float(inside.sum()), abs=1e-9), (
            f"{comparison.corner.name} charged {comparison.lost_s:.4f} s but "
            f"{inside.sum():.4f} s were measured inside it"
        )

    assert covered.max() <= 1, "corners overlap, so some time is charged twice"


def _wrap_pieces(grid, corner):
    return [
        span_indices(grid, corner.start_m, float(grid[-1])),
        span_indices(grid, float(grid[0]), corner.end_m),
    ]
