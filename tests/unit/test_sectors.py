import numpy as np
import pytest

from lmu_telemetry.core.laps import segment_laps
from lmu_telemetry.core.sectors import sector_times
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_three_marks_split_the_lap_into_three_sectors():
    ts = np.array([260.22, 297.02, 334.62])
    val = np.array([1.0, 2.0, 0.0])
    out = sector_times((ts, val), t_start=260.22, t_end=371.22)
    assert out == pytest.approx((36.80, 37.60, 36.60))
    assert sum(out) == pytest.approx(111.00)


def test_missing_events_give_none():
    assert sector_times(None, 0.0, 100.0) is None


def test_wrong_number_of_marks_gives_none():
    """Honest failure beats a fabricated split."""
    ts = np.array([260.22, 297.02])
    val = np.array([1.0, 2.0])
    assert sector_times((ts, val), t_start=260.22, t_end=371.22) is None


@pytest.mark.corpus
def test_monza_reference_lap_sectors(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        laps = segment_laps(tf, TimeBase.from_file(tf))
    assert laps[2].sectors_s == pytest.approx((36.80, 37.60, 36.60))
    assert laps[1].sectors_s == pytest.approx((37.02, 38.10, 41.44))
    assert laps[0].sectors_s == pytest.approx((56.305, 37.88, 36.90))


@pytest.mark.corpus
def test_sector_sum_equals_lap_time_for_every_corpus_lap(corpus_files):
    """The invariant that proves the extraction is correct: 190/190 laps."""
    checked = 0
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            laps = segment_laps(tf, TimeBase.from_file(tf))
        for lap in laps:
            if lap.sectors_s is None:
                continue
            assert sum(lap.sectors_s) == pytest.approx(lap.duration_s, abs=0.02), (
                f"{path.name} lap {lap.number}"
            )
            checked += 1
    assert checked == 190, f"expected 190 laps with sector data, checked {checked}"
