"""Properties that must hold for every lap in every file.

These are the guarantees that replace the old heuristic validation stages.
"""

import pytest

from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus

#: No car in any LMU class averages more than this over a full lap.
MAX_PLAUSIBLE_AVG_KMH = 300.0


def test_sector_sum_equals_duration(corpus_files):
    checked = 0
    for path in corpus_files:
        with Session.open(path) as s:
            for lap in s.laps:
                if lap.sectors_s is None:
                    continue
                assert sum(lap.sectors_s) == pytest.approx(lap.duration_s, abs=0.02), (
                    f"{path.name} lap {lap.number}"
                )
                checked += 1
    assert checked == 190, f"expected 190 laps with sector data, checked {checked}"


def test_no_lap_implies_impossible_average_speed(corpus_files):
    checked = 0
    for path in corpus_files:
        with Session.open(path) as s:
            length = s.track_length_m
            if length is None:
                continue
            for lap in s.laps:
                if lap.distance_m < length * 0.5:
                    continue  # partial lap, not a timing claim
                avg_kmh = (lap.distance_m / lap.duration_s) * 3.6
                assert avg_kmh < MAX_PLAUSIBLE_AVG_KMH, (
                    f"{path.name} lap {lap.number}: {avg_kmh:.1f} km/h average"
                )
                checked += 1
    assert checked > 150, f"only {checked} full laps reached the speed check"


def test_lap_intervals_are_contiguous_and_ordered(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            laps = s.laps
        for lap in laps:
            assert lap.t_end > lap.t_start
            assert lap.duration_s == pytest.approx(lap.t_end - lap.t_start)
        for a, b in zip(laps, laps[1:]):
            assert a.t_end == pytest.approx(b.t_start), f"{path.name}: gap between laps"


def test_every_session_reports_a_track_and_layout(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            assert s.info.track, f"{path.name}"
            assert s.info.layout, f"{path.name}"


def test_derived_duration_matches_the_games_own_lap_time_event(corpus_files):
    """The strongest available check: the file records its own lap time.

    `Lap Time` fires at lap completion carrying the just-completed lap's
    duration. We never read it to derive anything - which is exactly why it
    makes an independent oracle for the durations we do derive.

    Every lap from 1 onward agrees with the game's own recorded lap time to
    within 18.3 ms across all 40 sessions, independently corroborating that
    deriving duration from `Lap` event timestamps is correct.
    """
    checked = 0
    for path in corpus_files:
        with Session.open(path) as s:
            events = s.file.events("Lap Time")
            if events is None:
                continue
            ev_ts, ev_val = events
            for lap in s.laps:
                # Skip lap 0: it runs from the start of recording to the first
                # timed crossing, covering a formation lap plus the first racing
                # lap (measured at 1.93-2.00 track lengths) or including stationary
                # grid time. Not comparable to a single recorded lap time.
                if lap.number == 0:
                    continue
                # the event fires at this lap's end
                hits = [
                    float(v)
                    for t, v in zip(ev_ts, ev_val)
                    if abs(float(t) - lap.t_end) < 0.5 and float(v) > 0
                ]
                if len(hits) != 1:
                    continue
                assert hits[0] == pytest.approx(lap.duration_s, abs=0.03), (
                    f"{path.name} lap {lap.number}: derived {lap.duration_s:.3f}s "
                    f"but the file records {hits[0]:.3f}s"
                )
                checked += 1
    assert checked >= 140, (
        f"only {checked} laps could be cross-checked against a Lap Time event"
    )
