"""The three fixtures that exist because they broke the old implementation."""

import numpy as np
import pytest

from lmu_telemetry.core.laps import segment_laps
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_percent_steering_is_scaled_by_100_not_by_observed_max(percent_steering_file):
    with TelemetryFile(percent_steering_file) as tf:
        assert tf.channels.require("Steering Pos").unit == "%"
        raw = tf.raw_channel("Steering Pos")
        steer = tf.channel("Steering Pos")
    assert np.abs(raw).max() > 50.0
    assert np.abs(steer).max() == pytest.approx(np.abs(raw).max() / 100.0)
    assert np.abs(steer).max() <= 1.0


def test_session_without_a_complete_lap_yields_no_laps(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert s.laps == []
        assert s.fastest_lap is None
        assert s.info.track == "Autodromo Nazionale Monza"


def test_extra_distance_reset_does_not_create_a_phantom_lap(fixture_dir):
    """The old code split this session on Lap Dist resets and invented a lap."""
    path = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    if not path.is_file():
        pytest.skip("fixture not built")

    with TelemetryFile(path) as tf:
        n_lap_events = len(tf.events("Lap")[0])
        dist = tf.channel("Lap Dist")
        laps = segment_laps(tf, TimeBase.from_file(tf))

    n_resets = int(np.sum(np.diff(dist) < -50.0))
    assert n_resets > n_lap_events - 1, "fixture no longer contains the extra reset"
    assert len(laps) == n_lap_events - 1, "lap count must follow Lap events, not resets"
    for lap in laps:
        assert lap.duration_s > 60.0, "no partial lap may be reported as a full one"
