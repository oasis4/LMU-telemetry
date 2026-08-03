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


def test_mark_exactly_on_t_end_is_excluded_from_the_next_lap():
    """Laps are exactly contiguous (``a.t_end == b.t_start``), so a mark that
    lands exactly on ``t_end`` belongs to the lap that is starting, not the
    one that is ending. A 4-mark array with one mark on the boundary must be
    trimmed back down to 3 marks and a valid split - an off-by-one here would
    double-count the boundary mark into two laps."""
    ts = np.array([260.22, 297.02, 334.62, 371.22])
    val = np.array([1.0, 2.0, 0.0, 1.0])
    out = sector_times((ts, val), t_start=260.22, t_end=371.22)
    assert out == pytest.approx((36.80, 37.60, 36.60))
    assert sum(out) == pytest.approx(111.00)


def test_monza_reference_lap_sectors(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        laps = segment_laps(tf, TimeBase.from_file(tf))
    assert laps[2].sectors_s == pytest.approx((36.80, 37.60, 36.60))
    assert laps[1].sectors_s == pytest.approx((37.02, 38.10, 41.44))
    assert laps[0].sectors_s == pytest.approx((56.305, 37.88, 36.90))
