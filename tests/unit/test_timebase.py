import numpy as np
import pytest

from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_axis_starts_at_t0_and_steps_by_one_over_frequency():
    tb = TimeBase(t0=12.575)
    axis = tb.axis(n_samples=4, frequency_hz=10)
    assert np.allclose(axis, [12.575, 12.675, 12.775, 12.875])


def test_axis_rejects_non_positive_frequency():
    tb = TimeBase(t0=0.0)
    with pytest.raises(ValueError):
        tb.axis(n_samples=10, frequency_hz=0)


def test_index_at_rounds_to_nearest_sample():
    tb = TimeBase(t0=12.575)
    assert tb.index_at(12.575, 10) == 0
    assert tb.index_at(12.675, 10) == 1
    assert tb.index_at(143.575, 10) == 1310
    assert tb.index_at(0.0, 10) == 0  # clamped, never negative


@pytest.mark.corpus
def test_axis_from_real_file_matches_gps_time_start(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        tb = TimeBase.from_file(tf)
        axis = tb.axis_for(tf, "Lap Dist")
        gps = tf.channel("GPS Time")
    assert tb.t0 == pytest.approx(12.575)
    assert len(axis) == 3657
    assert axis[0] == pytest.approx(gps[0])


@pytest.mark.corpus
def test_lap_dist_resets_land_on_lap_events(monza_q_file):
    """The hard external check: a Lap Dist reset marks a lap start, so it must
    coincide with a Lap event to within one 10 Hz sample."""
    with TelemetryFile(monza_q_file) as tf:
        tb = TimeBase.from_file(tf)
        dist = tf.channel("Lap Dist")
        axis = tb.axis_for(tf, "Lap Dist")
        lap_ts, _ = tf.events("Lap")

    reset_idx = np.where(np.diff(dist) < -50.0)[0] + 1
    assert len(reset_idx) == 3
    for i in reset_idx:
        gap = np.min(np.abs(lap_ts - axis[i]))
        assert gap < 0.10, f"reset at sample {i} is {gap:.3f}s from any Lap event"
