"""The live buffer must produce the numbers the offline pipeline produces.

Two definitions of a brake point would be two answers to one question. This
file replays a recorded lap through the live buffer sample by sample and
requires the corner metrics to come out the same.
"""

import numpy as np
import pytest

from lmu_telemetry.core.metrics import corner_metrics
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.buffer import LapBuffer, LiveSample


def _replayed(trace, grid):
    """Feed every grid point of *trace* through a buffer, in track order."""
    buffer = LapBuffer(grid)
    for i in range(len(grid)):
        buffer.add(
            LiveSample(
                distance_m=float(grid[i]),
                time_s=float(trace.time_s[i]),
                speed_kmh=float(trace.speed_kmh[i]),
                throttle=float(trace.throttle[i]),
                brake=float(trace.brake[i]),
                steering=float(trace.steering[i]),
            )
        )
    return buffer


def test_a_replayed_lap_measures_the_same_as_the_recorded_one(monza_q_file):
    """Every marker, on every corner of a real lap.

    Exact equality, not approx: the samples are fed at the grid points
    themselves, so nothing is interpolated and any difference at all means the
    live path measures something the offline path does not.
    """
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        trace = build_trace(session, lap, model.track_length_m)

    live = _replayed(trace, trace.grid).trace()
    for corner in model.corners:
        if corner.start_m > corner.end_m:
            continue                      # not reported live; see watch.py
        offline = corner_metrics(trace, corner)
        online = corner_metrics(live, corner)
        assert online.brake_point_m == offline.brake_point_m, corner.name
        assert online.brake_peak_m == offline.brake_peak_m, corner.name
        assert online.brake_release_m == offline.brake_release_m, corner.name
        assert online.trail_length_m == offline.trail_length_m, corner.name
        assert online.throttle_point_m == offline.throttle_point_m, corner.name
        assert online.min_speed_kmh == pytest.approx(offline.min_speed_kmh)
        assert online.exit_speed_kmh == pytest.approx(offline.exit_speed_kmh)
        assert online.time_s == pytest.approx(offline.time_s)


def test_samples_that_go_backwards_are_ignored():
    """Shared memory repeats a frame when the reader is ahead of the game, and
    jitters by centimetres besides. A sample behind the furthest point reached
    is not new information, and interpolating it in would put a dent in the
    trace at whatever the car happened to be doing then."""
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    buffer.add(LiveSample(0.0, 0.0, 200.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(50.0, 1.0, 200.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(20.0, 1.1, 50.0, 0.0, 1.0, 0.0))

    assert buffer.reached_m == pytest.approx(50.0)
    trace = buffer.trace()
    assert trace.speed_kmh[int(50.0 // 2.0)] == pytest.approx(200.0)
    assert trace.brake[int(20.0 // 2.0)] == pytest.approx(0.0)


def test_a_buffer_reports_how_far_the_lap_has_come():
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    assert buffer.reached_m is None
    buffer.add(LiveSample(0.0, 0.0, 100.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(30.0, 1.0, 100.0, 1.0, 0.0, 0.0))
    assert buffer.reached_m == pytest.approx(30.0)


def test_resetting_forgets_the_previous_lap():
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    buffer.add(LiveSample(0.0, 0.0, 200.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(50.0, 9.9, 200.0, 1.0, 0.0, 0.0))
    buffer.reset()
    assert buffer.reached_m is None
    with pytest.raises(ValueError):
        buffer.trace()


def test_a_lap_with_one_sample_cannot_be_measured():
    """Rather than a trace whose every value is the one sample held flat,
    which measures as confidently as a real one."""
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    buffer.add(LiveSample(10.0, 0.0, 100.0, 1.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="at least 2 samples"):
        buffer.trace()
