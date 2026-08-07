from pathlib import Path

import pytest

from lmu_telemetry.core.laps import Lap, _distance_covered, segment_laps
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.channels import ChannelRegistry, MissingChannelError
from lmu_telemetry.io.duckdb_source import TelemetryFile


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


@pytest.mark.corpus
def test_sessions_without_two_lap_events_yield_no_laps(find_session):
    """Seven recorded sessions were abandoned before completing a lap."""
    path = find_session("Autodromo Nazionale Monza_Q_2026-03-27T09_02_56Z.duckdb")
    assert _laps(path) == []


@pytest.mark.corpus
def test_no_lap_in_the_corpus_is_physically_impossible(corpus_files):
    """A lap cannot be faster than the track length at 400 km/h.

    This is the structural guarantee that replaces the old median heuristics:
    the duration comes from the game clock, so it cannot be fabricated.
    """
    max_speed_ms = 400.0 / 3.6
    checked = 0
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            laps = segment_laps(tf, TimeBase.from_file(tf))
            track_len = float(tf.channel("Lap Dist").max()) if laps else 0.0
        for lap in laps:
            # Lap 0 spans from the start of recording to the first crossing,
            # so it is a fragment of a lap rather than a slow one, and no
            # floor derived from the track length applies to it.
            if lap.number == 0:
                continue
            floor = track_len / max_speed_ms
            assert lap.duration_s >= floor, (
                f"{path.name} lap {lap.number}: {lap.duration_s:.2f}s "
                f"is below the {floor:.2f}s physical floor"
            )
            checked += 1
    # Scaled to the working set rather than fixed: every session kept there
    # has at least one clean lap, so at least one lap per session must reach
    # this check. A fixed count would only record how much data is on hand.
    assert checked >= len(corpus_files), (
        f"only {checked} laps reached the floor check across "
        f"{len(corpus_files)} sessions"
    )


def test_missing_lap_dist_channel_raises_rather_than_returning_zero():
    """A substitute value would be indistinguishable from 'the car did not move'."""

    class _NoDistFile:
        path = Path("stub.duckdb")
        channels = ChannelRegistry({})

    with pytest.raises(MissingChannelError):
        _distance_covered(_NoDistFile(), TimeBase(t0=0.0), 0.0, 10.0)


@pytest.mark.corpus
def test_pit_state_carried_into_lap_is_detected_without_an_in_lap_event(find_session):
    """Lap 1 of this Monza race enters the pits before the lap starts (t=254.9)
    and leaves during it (t=284.0). No 'In Pits' event inside the lap window
    carries a non-zero value - only the carried-in state from before the lap
    reveals that it touched the pits. This would fail if the carried-in
    branch of ``_touched_pits`` were deleted.
    """
    path = find_session("Autodromo Nazionale Monza_R_2026-03-29T16_13_52Z.duckdb")

    with TelemetryFile(path) as tf:
        laps = segment_laps(tf, TimeBase.from_file(tf))
        lap1 = next(l for l in laps if l.number == 1)
        ts, val = tf.events("In Pits")

    inside = (ts >= lap1.t_start) & (ts < lap1.t_end)
    assert not (val[inside] != 0).any(), (
        "expected no in-window 'In Pits' event to carry a non-zero value; "
        "if one does, this test no longer exercises the carried-in branch"
    )
    assert lap1.touched_pits is True
