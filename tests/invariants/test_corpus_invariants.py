"""Properties that must hold for every lap in every file.

These are the guarantees that replace the old heuristic validation stages.
"""

import pytest

from lmu_telemetry.core.quality import LAP_TIME_TOLERANCE_S, assess_lap
from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus

#: No car in any LMU class averages more than this over a full lap.
MAX_PLAUSIBLE_AVG_KMH = 300.0


def _boundaries_are_trustworthy(lap) -> bool:
    """Whether this lap's own file agrees about where the lap begins and ends.

    Some sessions carry ``Lap`` events whose timestamps do not match the lap
    times the game recorded - by seconds, not milliseconds. Nothing derived
    from those boundaries means anything, so an invariant about our sector or
    speed arithmetic cannot be tested on them. They get their own test below,
    which asserts they are rejected rather than quietly skipped.
    """
    if lap.recorded_time_s is None or lap.recorded_time_s == 0.0:
        return False
    return abs(lap.duration_s - lap.recorded_time_s) <= LAP_TIME_TOLERANCE_S


def test_sector_sum_equals_duration(corpus_files):
    checked = seen = 0
    for path in corpus_files:
        with Session.open(path) as s:
            for lap in s.laps:
                seen += 1
                if lap.sectors_s is None or not _boundaries_are_trustworthy(lap):
                    continue
                assert sum(lap.sectors_s) == pytest.approx(lap.duration_s, abs=0.02), (
                    f"{path.name} lap {lap.number}"
                )
                checked += 1
    # A fraction, not a count: an absolute floor pins how much data happens to
    # be on this machine, so it fails the day a session is added or archived
    # and teaches whoever sees it to edit the number rather than read it.
    assert checked >= 0.4 * seen, f"only {checked} of {seen} laps carried sector data"


def test_no_lap_implies_impossible_average_speed(corpus_files):
    """No lap the pipeline is willing to time may imply an impossible speed.

    Lap 0 is excluded because it is not a lap time: it runs from wherever
    recording started to the first crossing. The guarantee that it never
    reaches a user is ``fastest_lap``'s, and is tested there.
    """
    checked = seen = 0
    for path in corpus_files:
        with Session.open(path) as s:
            length = s.track_length_m
            if length is None:
                continue
            for lap in s.laps:
                if lap.number == 0:
                    continue
                seen += 1
                if lap.distance_m < length * 0.5:
                    continue  # partial lap, not a timing claim
                avg_kmh = (lap.distance_m / lap.duration_s) * 3.6
                assert avg_kmh < MAX_PLAUSIBLE_AVG_KMH, (
                    f"{path.name} lap {lap.number}: {avg_kmh:.1f} km/h average"
                )
                checked += 1
    assert checked >= 0.8 * seen, f"only {checked} of {seen} laps were full laps"


def test_every_lap_whose_boundaries_are_suspect_is_rejected(corpus_files):
    """The laps skipped above must be rejected, not merely skipped.

    Without this, widening the skip in ``_boundaries_are_trustworthy`` would
    silently shrink what the invariants above cover. Here that same set has to
    come back from ``assess_lap`` as unclean, with the disagreement named.
    """
    suspect = 0
    for path in corpus_files:
        with Session.open(path) as s:
            for lap in s.laps:
                if lap.number == 0 or lap.touched_pits:
                    continue
                if lap.recorded_time_s is None or _boundaries_are_trustworthy(lap):
                    continue
                quality = assess_lap(s, lap)
                assert quality.is_clean is False, (
                    f"{path.name} lap {lap.number}: derived {lap.duration_s:.3f}s "
                    f"against the game's {lap.recorded_time_s:.3f}s, yet accepted"
                )
                suspect += 1
    # Curation archives whole sessions whose laps are all suspect, so how many
    # survive here depends on the working set. One is enough to prove the
    # branch is reachable from real data; the fixture test pins the behaviour.
    assert suspect >= 1, "no suspect lap in the working set to test the rejection on"


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

    Across the corpus 913 of 995 timed laps agree to within 17 ms. The rest
    miss by more than a second and belong to files whose `Lap` events are
    unreliable; ``assess_lap`` rejects those, and the test above holds it to
    that. This one asserts the positive half: where a lap survives, the two
    independent measurements of its duration agree to milliseconds.
    """
    checked = 0
    for path in corpus_files:
        with Session.open(path) as s:
            events = s.file.events("Lap Time")
            if events is None:
                continue
            ev_ts, ev_val = events
            for lap in s.laps:
                if not _boundaries_are_trustworthy(lap):
                    continue
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
    assert checked >= 0.5 * _timed_laps(corpus_files), (
        f"only {checked} laps could be cross-checked against a Lap Time event"
    )


def _timed_laps(corpus_files) -> int:
    """Laps past lap 0 across the working set - the denominator above."""
    total = 0
    for path in corpus_files:
        with Session.open(path) as s:
            total += sum(1 for lap in s.laps if lap.number > 0)
    return total
