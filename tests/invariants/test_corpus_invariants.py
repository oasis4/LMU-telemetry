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
