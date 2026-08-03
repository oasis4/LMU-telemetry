import numpy as np
import pytest

from lmu_telemetry.io.channels import MissingChannelError
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_opening_a_missing_file_raises_file_not_found_error():
    with pytest.raises(FileNotFoundError):
        TelemetryFile("does_not_exist.duckdb")


def test_metadata_has_the_twelve_known_keys(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        meta = tf.metadata
    assert set(meta) == {
        "CarClass", "CarName", "CarSetup", "DriverName", "RecordingTime",
        "SessionTime", "SessionType", "SteamID", "TrackLayout", "TrackName",
        "Version", "WeatherConditions",
    }
    assert meta["TrackName"] == "Autodromo Nazionale Monza"
    assert meta["SessionType"] == "Qualify"
    assert meta["CarClass"] == "GT3"
    assert meta["DriverName"] == "A Mueller"


def test_raw_channel_returns_declared_percent_range(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        raw = tf.raw_channel("Throttle Pos")
    assert len(raw) == 18282
    assert raw.max() == pytest.approx(100.0)


def test_channel_is_normalised_to_fraction(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        thr = tf.channel("Throttle Pos")
    assert thr.max() == pytest.approx(1.0)
    assert thr.min() == pytest.approx(0.0)


def test_lap_dist_is_not_rescaled(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        dist = tf.channel("Lap Dist")
    assert len(dist) == 3657
    assert dist.max() == pytest.approx(5776.076, abs=0.01)


def test_events_are_sorted_pairs(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        ts, val = tf.events("Lap")
    assert np.allclose(ts, [12.575, 143.66, 260.22, 371.22])
    assert np.allclose(val, [0, 1, 2, 3])
    assert np.all(np.diff(ts) > 0)


def test_events_returns_none_for_unknown_table(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        assert tf.events("No Such Event") is None
        assert tf.has_event("Lap") is True
        assert tf.has_event("No Such Event") is False


def test_unknown_channel_raises(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        with pytest.raises(MissingChannelError):
            tf.channel("No Such Channel")


@pytest.mark.corpus
def test_every_corpus_file_opens_and_reports_metadata(corpus_files):
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            meta = tf.metadata
            assert meta["TrackName"], f"{path.name} has no TrackName"
            assert meta["TrackLayout"], f"{path.name} has no TrackLayout"
