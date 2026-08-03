import pytest

from lmu_telemetry.core.laps import Lap, segment_laps
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile

pytestmark = pytest.mark.corpus


def _laps(path):
    with TelemetryFile(path) as tf:
        return segment_laps(tf, TimeBase.from_file(tf))


def test_monza_qualifying_has_exactly_three_complete_laps(monza_q_file):
    laps = _laps(monza_q_file)
    assert [l.number for l in laps] == [0, 1, 2]


def test_lap_durations_come_from_lap_event_timestamps(monza_q_file):
    """Ground truth: Lap events at 12.575 / 143.66 / 260.22 / 371.22."""
    laps = _laps(monza_q_file)
    assert [round(l.duration_s, 3) for l in laps] == [131.085, 116.560, 111.000]


def test_trailing_incomplete_lap_is_dropped(monza_q_file):
    """The file has 4 Lap events, so only 3 laps are bounded on both sides."""
    with TelemetryFile(monza_q_file) as tf:
        n_events = len(tf.events("Lap")[0])
        laps = segment_laps(tf, TimeBase.from_file(tf))
    assert n_events == 4
    assert len(laps) == 3


def test_out_lap_is_flagged_as_having_touched_the_pits(monza_q_file):
    """In Pits goes 1 -> 0 at t=31.96, inside lap 0."""
    laps = _laps(monza_q_file)
    assert laps[0].touched_pits is True
    assert laps[1].touched_pits is False
    assert laps[2].touched_pits is False


def test_distance_covered_is_about_one_track_length(monza_q_file):
    laps = _laps(monza_q_file)
    for lap in laps[1:]:  # the out lap starts in the pit lane
        assert 5600.0 < lap.distance_m < 5900.0


def test_sessions_without_two_lap_events_yield_no_laps(corpus_dir):
    """Seven corpus sessions were abandoned before completing a lap."""
    path = corpus_dir / "Autodromo Nazionale Monza_Q_2026-03-27T09_02_56Z.duckdb"
    if not path.is_file():
        pytest.skip("edge-case session not present")
    assert _laps(path) == []


def test_no_lap_in_the_corpus_is_physically_impossible(corpus_files):
    """A lap cannot be faster than the track length at 400 km/h.

    This is the structural guarantee that replaces the old median heuristics:
    the duration comes from the game clock, so it cannot be fabricated.
    """
    max_speed_ms = 400.0 / 3.6
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            laps = segment_laps(tf, TimeBase.from_file(tf))
            track_len = float(tf.channel("Lap Dist").max()) if laps else 0.0
        for lap in laps:
            floor = track_len / max_speed_ms
            assert lap.duration_s >= floor, (
                f"{path.name} lap {lap.number}: {lap.duration_s:.2f}s "
                f"is below the {floor:.2f}s physical floor"
            )
