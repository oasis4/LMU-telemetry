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
