import numpy as np
import pytest

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for
from lmu_telemetry.core.metrics import (
    APPROACH_M,
    BRAKE_ON,
    corner_metrics,
)
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import LapTrace, build_trace

LAP_M = 2000.0


def _corner(start_m, apex_m, end_m) -> Corner:
    return Corner(
        index=1, name="T1", start_m=start_m, apex_m=apex_m, end_m=end_m,
        radius_m=80.0, heading_deg=90.0, direction="L",
    )


def _trace(speed_kmh=None, throttle=None, brake=None, pace_kmh=150.0) -> LapTrace:
    """A lap at a constant pace unless a channel says otherwise."""
    grid = grid_for(LAP_M)
    n = len(grid)
    speed = np.full(n, pace_kmh) if speed_kmh is None else np.asarray(speed_kmh, float)
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))
    return LapTrace(
        lap=None,
        grid=grid,
        time_s=time_s,
        speed_kmh=speed,
        throttle=np.zeros(n) if throttle is None else np.asarray(throttle, float),
        brake=np.zeros(n) if brake is None else np.asarray(brake, float),
        steering=np.zeros(n),
    )



def _real_trace(path, lap_number: int):
    """A real lap of a committed fixture, on its own track's grid."""
    with Session.open(path) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == lap_number)
        return build_trace(session, lap, model.track_length_m), lap

def _index(distance_m: float) -> int:
    return int(distance_m / GRID_STEP_M)


def test_brake_point_is_where_the_pedal_first_passes_the_threshold():
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(800.0) : _index(920.0)] = 0.8
    m = corner_metrics(_trace(brake=brake), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m == pytest.approx(800.0, abs=GRID_STEP_M)


def test_sensor_noise_below_the_threshold_is_not_a_brake_point():
    """The old code checked brake > 0.1 against 0-100 values.

    That fires at 0.1 % brake pressure. Here the pedal sits at 2 % for the
    whole lap - well inside noise - and no brake point may be reported.
    """
    brake = np.full(len(grid_for(LAP_M)), 0.02)
    assert brake.max() < BRAKE_ON
    m = corner_metrics(_trace(brake=brake), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m is None


def test_a_corner_taken_flat_reports_no_brake_point():
    """None is the truth for a flat-out kink, not a defect to paper over."""
    m = corner_metrics(_trace(), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m is None
    assert m.throttle_point_m is None


def test_an_earlier_brush_of_the_brake_is_not_this_corners_brake_point():
    """Braking for the corner is the stretch that ends at the slowest point.

    A dab 300 m earlier - catching a slide on the straight - is a separate
    event. Reporting the first stretch in the window would name it instead,
    and every brake-point comparison would then be against the wrong thing.
    """
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(680.0) : _index(700.0)] = 0.3     # the dab
    brake[_index(820.0) : _index(920.0)] = 0.9     # braking for the corner
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(900.0) : _index(1000.0)] = 90.0
    m = corner_metrics(_trace(speed_kmh=speed, brake=brake), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m == pytest.approx(820.0, abs=GRID_STEP_M)


def test_braking_before_the_approach_window_is_out_of_scope():
    """Braking at 500 m has nothing to do with a corner that starts at 900 m.

    The distance is written out rather than derived from APPROACH_M. Deriving
    it makes the test move with the constant it is supposed to pin: raising
    the window from 250 m to 400 m moved the braking too, and the test went on
    passing while the behaviour it names had changed.
    """
    assert APPROACH_M < 400.0, (
        "the approach window now reaches 500 m, so this test no longer places "
        "the braking outside it"
    )
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(500.0) : _index(540.0)] = 0.9
    m = corner_metrics(_trace(brake=brake), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m is None


def test_speeds_are_read_at_the_corners_own_bounds():
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(900.0) : _index(1000.0)] = 100.0
    speed[_index(940.0)] = 80.0                    # the slowest point
    m = corner_metrics(_trace(speed_kmh=speed), _corner(900.0, 950.0, 1000.0))
    assert m.entry_speed_kmh == pytest.approx(100.0)
    assert m.min_speed_kmh == pytest.approx(80.0)
    assert m.min_speed_at_m == pytest.approx(940.0, abs=GRID_STEP_M)
    assert m.exit_speed_kmh == pytest.approx(200.0)


def test_throttle_point_is_found_after_the_slowest_point_not_before():
    """Throttle is often still open on the way in; only the pick-up counts."""
    throttle = np.zeros(len(grid_for(LAP_M)))
    throttle[: _index(905.0)] = 1.0                # still on the power arriving
    throttle[_index(960.0) :] = 1.0                # picked up again
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(940.0)] = 80.0
    m = corner_metrics(
        _trace(speed_kmh=speed, throttle=throttle), _corner(900.0, 950.0, 1000.0)
    )
    assert m.throttle_point_m == pytest.approx(960.0, abs=GRID_STEP_M)


def test_corner_time_is_the_time_between_its_bounds():
    m = corner_metrics(_trace(pace_kmh=180.0), _corner(900.0, 950.0, 1000.0))
    assert m.time_s == pytest.approx(100.0 / (180.0 / 3.6), rel=0.02)


def test_a_corner_across_the_start_finish_line_is_measured_over_both_halves():
    """start_m > end_m means the corner contains d=0.

    Its two halves sit at opposite ends of the array, so subtracting the time
    at one from the time at the other would return the whole rest of the lap
    with a minus sign.
    """
    trace = _trace(pace_kmh=180.0)
    m = corner_metrics(trace, _corner(1900.0, 1980.0, 100.0))
    expected = 200.0 / (180.0 / 3.6)               # 100 m before + 100 m after
    assert m.time_s == pytest.approx(expected, rel=0.05)
    assert m.time_s > 0.0


@pytest.mark.corpus
def test_metrics_over_a_real_lap_are_physically_ordered(corpus_dir):
    """On every corner of a real lap: brake before the apex, throttle after.

    Nothing in the implementation enforces this ordering - it falls out of
    reading the right windows - so it is evidence the windows are right.
    """
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        lap = next(l for l in s.laps if l.number == 3)
        trace = build_trace(s, lap, model.track_length_m)
        braked = 0
        for corner in model.corners:
            m = corner_metrics(trace, corner)
            assert 0.0 < m.min_speed_kmh <= m.entry_speed_kmh + 1.0
            assert m.time_s > 0.0
            if m.brake_point_m is not None:
                braked += 1
    assert braked >= 5, f"only {braked} corners of Monza showed any braking"


# -- the shape of one braking event ----------------------------------------

def _trail_brake(start_m, peak_m, release_m):
    """Pressure up at *start_m*, highest at *peak_m*, bled off by *release_m*.

    The taper is linear from the peak down through TRAIL_OFF, which is what a
    trail-braking release looks like and what a lone threshold crossing cannot
    describe.
    """
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(start_m) : _index(peak_m)] = 0.6
    brake[_index(peak_m)] = 1.0
    taper = np.linspace(1.0, 0.0, _index(release_m) - _index(peak_m) + 2)[1:-1]
    brake[_index(peak_m) + 1 : _index(release_m) + 1] = taper
    return brake


def test_the_four_markers_come_off_one_braking_event():
    m = corner_metrics(
        _trace(brake=_trail_brake(800.0, 840.0, 940.0)), _corner(900.0, 950.0, 1000.0)
    )
    assert m.brake_point_m == pytest.approx(800.0, abs=GRID_STEP_M)
    assert m.brake_peak_m == pytest.approx(840.0, abs=GRID_STEP_M)
    assert m.brake_release_m == pytest.approx(940.0, abs=2 * GRID_STEP_M)
    assert m.trail_length_m == pytest.approx(100.0, abs=2 * GRID_STEP_M)


def test_the_release_is_read_past_the_slowest_point():
    """A trail carries past the minimum speed.

    The brake point is found in a window that ends at the slowest sample. Used
    for the release too, that window would report every trail as ending
    exactly at the slowest point - a number produced by the window rather than
    by the driving, and one that would compare as confidently as a real one.
    """
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(900.0) : _index(1000.0)] = 100.0
    m = corner_metrics(
        _trace(speed_kmh=speed, brake=_trail_brake(800.0, 830.0, 980.0)),
        _corner(900.0, 950.0, 1000.0),
    )
    assert m.min_speed_at_m == pytest.approx(900.0, abs=GRID_STEP_M)
    assert m.brake_release_m > m.min_speed_at_m


def test_a_lap_that_never_braked_has_none_of_the_markers():
    m = corner_metrics(_trace(), _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m is None
    assert m.brake_peak_m is None
    assert m.brake_release_m is None
    assert m.trail_length_m is None


def test_the_release_threshold_is_below_the_one_that_starts_braking():
    """Or the tapering end of every trail is clipped by it."""
    from lmu_telemetry.core.metrics import TRAIL_OFF

    assert 0.0 < TRAIL_OFF < BRAKE_ON


def test_a_stab_of_the_brakes_has_almost_no_trail():
    """Straight-line braking released in one go. The marker has to be able to
    say "there was no trail here", or a short trail and a long one compare the
    same."""
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(800.0) : _index(840.0)] = 0.9
    m = corner_metrics(_trace(brake=brake), _corner(900.0, 950.0, 1000.0))
    assert m.trail_length_m == pytest.approx(38.0, abs=4 * GRID_STEP_M)


def test_the_trail_of_a_corner_across_the_start_finish_line_is_not_a_lap_long():
    """The peak and the release sit at opposite ends of the array there.

    Subtracting the two distances returns the whole rest of the lap with a
    minus sign, so the length is counted in grid steps instead.
    """
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(1840.0) :] = 0.6
    brake[_index(1900.0)] = 1.0
    taper = np.linspace(1.0, 0.0, _index(60.0) + (len(brake) - _index(1900.0)) + 1)[1:]
    brake[_index(1900.0) + 1 :] = taper[: len(brake) - _index(1900.0) - 1]
    brake[: _index(60.0)] = taper[len(brake) - _index(1900.0) - 1 :][: _index(60.0)]

    m = corner_metrics(_trace(brake=brake), _corner(1900.0, 1980.0, 100.0))
    assert m.trail_length_m is not None
    assert 0.0 <= m.trail_length_m < 200.0, m.trail_length_m


def test_the_brake_markers_of_a_real_lap_are_physically_ordered(monza_q_file):
    """Pressure up, then peak, then release.

    Nothing in the implementation enforces that order - the peak is an argmax
    and the release a threshold crossing - so it falls out only if the windows
    they are read over are right.
    """
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        trace = build_trace(session, lap, model.track_length_m)
        measured = [corner_metrics(trace, corner) for corner in model.corners]

    braked = [m for m in measured if m.brake_point_m is not None]
    assert len(braked) >= 5, f"only {len(braked)} corners of Monza showed braking"
    for m in braked:
        assert m.brake_peak_m is not None
        assert m.brake_release_m is not None
        assert m.trail_length_m is not None and m.trail_length_m >= 0.0
        if m.corner.start_m < m.corner.end_m:      # not one across the line
            assert m.brake_point_m <= m.brake_peak_m <= m.brake_release_m, m


def test_real_trail_lengths_are_not_all_the_same(monza_q_file):
    """A marker that comes back constant discriminates nothing, and every
    comparison built on it would be a comparison of zero."""
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        trace = build_trace(session, lap, model.track_length_m)
        measured = [corner_metrics(trace, corner) for corner in model.corners]

    lengths = [m.trail_length_m for m in measured if m.trail_length_m is not None]
    assert len(set(lengths)) > 1, lengths


# -- braking zones ---------------------------------------------------------

def test_braking_zones_are_the_stretches_the_pedal_was_down(monza_q_file):
    from lmu_telemetry.core.metrics import braking_zones

    trace, _ = _real_trace(monza_q_file, 2)
    zones = braking_zones(trace)
    assert zones, "a Monza lap brakes somewhere"
    for start_m, end_m in zones:
        assert 0.0 <= start_m < end_m <= trace.grid[-1] + GRID_STEP_M


def test_a_braking_zone_covers_only_metres_that_were_braked(monza_q_file):
    """Every metre inside a zone must be over the threshold, and every metre
    over the threshold must be inside one. A zone that merely brackets the
    braking would look right on a map and be wrong by a hundred metres."""
    from lmu_telemetry.core.metrics import BRAKE_ON, braking_zones

    trace, _ = _real_trace(monza_q_file, 2)
    inside = np.zeros(len(trace.grid), dtype=bool)
    for start_m, end_m in braking_zones(trace):
        inside |= (trace.grid >= start_m) & (trace.grid <= end_m)
    on = trace.brake > BRAKE_ON
    # A single sample on its own is dropped - see the test below - so the
    # zones may miss those, but must never claim a metre that was not braked.
    assert not np.any(inside & ~on), "a zone covers metres the car was not braking"
    assert np.sum(on & ~inside) <= np.sum(on) * 0.02


def test_two_applications_stay_two_zones(monza_q_file):
    """A lift and a re-application inside one braking event are two zones.
    Merged, a map draws a band across the part the driver was off the pedal."""
    from lmu_telemetry.core.metrics import braking_zones

    trace, _ = _real_trace(monza_q_file, 2)
    zones = braking_zones(trace)
    gaps = [b[0] - a[1] for a, b in zip(zones, zones[1:])]
    assert all(gap > 0 for gap in gaps), "zones overlap or touch"


def test_a_single_sample_over_the_threshold_is_not_a_zone():
    """Two metres of grid is a twitch of the pedal, not a braking zone, and it
    draws as a dot claiming a brake point that was never applied."""
    from lmu_telemetry.core.metrics import braking_zones

    brake = np.zeros(len(grid_for(LAP_M)))
    brake[100] = 0.9                      # one sample
    brake[200:210] = 0.9                  # a real application
    zones = braking_zones(_trace(brake=brake))
    assert len(zones) == 1
    assert zones[0][0] == pytest.approx(200 * GRID_STEP_M)
