import numpy as np
import pytest

from lmu_telemetry.core.geometry import GRID_STEP_M
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.trace import TraceError, build_trace


def _trace(path, lap_number: int):
    with Session.open(path) as s:
        lap = next(l for l in s.laps if l.number == lap_number)
        return build_trace(s, lap, s.track_length_m), lap


def test_time_axis_starts_at_zero_and_ends_at_the_lap_duration(monza_q_file):
    trace, lap = _trace(monza_q_file, 2)
    assert trace.time_s[0] == pytest.approx(0.0, abs=0.05)
    assert trace.time_s[-1] == pytest.approx(lap.duration_s, abs=0.5)


def test_time_advances_with_distance(monza_q_file):
    """Every grid step costs time, so the axis is strictly increasing.

    A repeated or decreasing value would mean the car covered 2 m of track in
    no time at all, and any delta built on it would be meaningless there.
    """
    trace, _ = _trace(monza_q_file, 2)
    assert np.all(np.diff(trace.time_s) > 0.0)


def test_speed_stays_in_the_declared_unit_and_pedals_are_normalised(monza_q_file):
    """km/h from channelsList, pedals from '%' to 0..1.

    The old code read the pedals as though they were already 0..1 and checked
    brake > 0.1 - which fires at 0.1 % brake pressure, on sensor noise.
    """
    trace, _ = _trace(monza_q_file, 2)
    assert 150.0 < trace.speed_kmh.max() < 400.0
    assert trace.brake.min() >= 0.0
    assert trace.brake.max() <= 1.0
    assert trace.throttle.max() > 0.9, "a qualifying lap reaches full throttle"


def test_speed_and_time_agree_about_the_lap(monza_q_file):
    """Distance over the mean speed must come back to the lap time.

    Speed is read from its own 100 Hz channel and time is derived from Lap
    Dist at 10 Hz, so this holds only if both landed on the grid consistently.
    """
    trace, lap = _trace(monza_q_file, 2)
    step_time = np.diff(trace.time_s)
    implied_m = np.sum(trace.speed_kmh[:-1] / 3.6 * step_time)
    assert implied_m == pytest.approx(trace.grid[-1], rel=0.05)


def test_a_lap_where_lap_dist_steps_backwards_still_advances_in_time(
    backward_lap_dist_file,
):
    """Lap 2 of this session steps backwards in Lap Dist 33 times, once by 5.2 m.

    Progress round the lap is the running maximum of Lap Dist. Sorting the raw
    samples by distance instead - the other way to get a usable axis - carries
    time along with them, and time then runs backwards wherever distance did:
    on 24 of the working set's 424 clean laps, here by 2.2 s. A delta built on
    such an axis is nonsense exactly where the driver had a moment, which is
    the part worth looking at.

    The 5.2 m step is what makes this lap the one that discriminates: the grid
    advances 2 m, so a backward step smaller than that disappears between two
    grid points and both approaches agree.
    """
    with Session.open(backward_lap_dist_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        length = s.track_length_m
        raw = np.asarray(s.lap_channel(lap, "Lap Dist"), dtype=float)
        trace = build_trace(s, lap, length)

    after_reset = int(np.flatnonzero(np.diff(raw) < -0.5 * length)[-1]) + 1
    assert np.min(np.diff(raw[after_reset:])) < -2.0 * GRID_STEP_M, (
        "this fixture no longer steps back further than a grid step, "
        "so it no longer discriminates"
    )
    assert np.all(np.diff(trace.time_s) > 0.0)


def test_a_channel_the_file_does_not_carry_is_an_error_not_a_zero(monza_q_file):
    """A substitute array is indistinguishable from a lap spent stationary."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        with pytest.raises(TraceError):
            build_trace(s, lap, s.track_length_m, channels={"No Such Channel": "x"})


def test_a_lap_that_does_not_span_the_track_is_refused(monza_q_file):
    """Resampling flat-extrapolates, so a short lap would come back as a real
    -looking trace with invented ends rather than as a failure."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 0)  # the out lap
        with pytest.raises(TraceError):
            build_trace(s, lap, s.track_length_m)
