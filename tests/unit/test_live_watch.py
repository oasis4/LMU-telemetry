"""A corner speaks when it is behind the car, once, and only with a story.

The live path must not be a second opinion. Where these tests compare it to
the post-lap view, they compare it to the *same* functions - the point is that
one set of rules answers for both, and these are what would notice if that
stopped being true.
"""

import pytest

from lmu_telemetry.core.coaching import (
    SAME_BRAKING_M,
    advise_on,
    compare_corners,
    names_braking,
)
from lmu_telemetry.core.metrics import APPROACH_M
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.buffer import LapBuffer, LiveSample
from lmu_telemetry.live.watch import CornerWatch


def _drive(trace, corners, reference):
    """Replay *trace* through a watch, collecting what it says and where."""
    watch = CornerWatch(reference, corners)
    buffer = LapBuffer(trace.grid)
    said = []
    for i in range(len(trace.grid)):
        buffer.add(
            LiveSample(
                distance_m=float(trace.grid[i]),
                time_s=float(trace.time_s[i]),
                speed_kmh=float(trace.speed_kmh[i]),
                throttle=float(trace.throttle[i]),
                brake=float(trace.brake[i]),
                steering=float(trace.steering[i]),
            )
        )
        for finding in watch.advance(buffer):
            said.append((float(trace.grid[i]), finding))
    return said


@pytest.fixture(scope="module")
def two_laps(monza_q_file):
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        laps = {lap.number: lap for lap in session.laps}
        fast = build_trace(session, laps[2], model.track_length_m)
        slow = build_trace(session, laps[1], model.track_length_m)
    return model, fast, slow


def test_a_corner_is_never_reported_before_the_car_has_left_it(two_laps):
    """The whole design rests on this. A corner measured from a span the car
    is still inside is measured from values np.interp invented ahead of it."""
    model, fast, slow = two_laps
    reported = _drive(slow, model.corners, fast)
    assert reported, "a lap 5 s off the reference should report something"
    for at_m, finding in reported:
        assert at_m >= finding.comparison.corner.end_m, finding.comparison.corner.name


def test_each_corner_speaks_at_most_once(two_laps):
    model, fast, slow = two_laps
    seen = [f.comparison.corner.index for _at, f in _drive(slow, model.corners, fast)]
    assert len(seen) == len(set(seen)), seen


def test_corners_are_reported_in_the_order_they_are_driven(two_laps):
    model, fast, slow = two_laps
    at = [a for a, _f in _drive(slow, model.corners, fast)]
    assert at == sorted(at)


def test_every_corner_of_the_lap_is_accounted_for(two_laps):
    """Silence must be a decision about a corner, not a corner going missing."""
    model, fast, slow = two_laps
    reported = {f.comparison.corner.index for _at, f in _drive(slow, model.corners, fast)}
    expected = {c.index for c in model.corners if c.start_m <= c.end_m}
    assert reported == expected


def test_a_lap_against_itself_finds_nothing_to_say(two_laps):
    """Every measurement identical, so no corner has a story."""
    model, fast, _slow = two_laps
    said = [f for _at, f in _drive(fast, model.corners, fast) if f.advice is not None]
    assert said == [], [f.comparison.corner.name for f in said]


def test_the_findings_carry_the_same_advice_the_post_lap_view_would(two_laps):
    """Same corners named, same sentence for each."""
    model, fast, slow = two_laps
    live = {
        f.comparison.corner.index: f.advice
        for _at, f in _drive(slow, model.corners, fast)
        if f.advice is not None
    }
    offline = {}
    for comparison in compare_corners(fast, slow, model.corners):
        tip = advise_on(comparison)
        if tip is not None:
            offline[comparison.corner.index] = tip

    assert set(live) == set(offline), (sorted(live), sorted(offline))
    for index, tip in live.items():
        assert tip.headline == offline[index].headline


def test_live_time_lost_agrees_with_the_post_lap_figure(two_laps):
    """One is a difference of two corner times, the other the integral of a
    delta trace. They are the same quantity, and if they drift the panel and
    the browser disagree about the same corner."""
    model, fast, slow = two_laps
    offline = {
        c.corner.index: c.lost_s for c in compare_corners(fast, slow, model.corners)
    }
    for _at, finding in _drive(slow, model.corners, fast):
        index = finding.comparison.corner.index
        assert finding.comparison.lost_s == pytest.approx(offline[index], abs=0.02), (
            finding.comparison.corner.name,
            finding.comparison.lost_s,
            offline[index],
        )


def test_joining_a_session_part_way_round_does_not_crash(two_laps):
    """The overlay is started while the driver is already on track.

    The first sample lands at 3000 m, and every corner behind it is instantly
    "complete". Measuring one from a buffer holding a single sample raised
    ValueError out of LapBuffer.trace and took the overlay down before it drew
    anything.
    """
    model, fast, slow = two_laps
    watch = CornerWatch(fast, model.corners)
    buffer = LapBuffer(slow.grid)
    at = int(3000 / 2)
    buffer.add(
        LiveSample(
            float(slow.grid[at]), float(slow.time_s[at]), float(slow.speed_kmh[at]),
            float(slow.throttle[at]), float(slow.brake[at]), float(slow.steering[at]),
        )
    )
    assert watch.advance(buffer) == []


def test_a_corner_whose_approach_was_never_seen_is_not_reported(two_laps):
    """Not silence for its own sake: the brake point is looked for up to
    APPROACH_M before the corner starts, and np.interp holds the first sample
    flat across everything before it. A brake point read there is that one
    sample repeated, and it would compare as confidently as a real one.
    """
    model, fast, slow = two_laps
    watch = CornerWatch(fast, model.corners)
    buffer = LapBuffer(slow.grid)

    joined = int(3000 / 2)
    for i in range(joined, len(slow.grid)):
        buffer.add(
            LiveSample(
                float(slow.grid[i]), float(slow.time_s[i]), float(slow.speed_kmh[i]),
                float(slow.throttle[i]), float(slow.brake[i]), float(slow.steering[i]),
            )
        )
    reported = [f.comparison.corner for f in watch.advance(buffer)]

    assert reported, "the corners after 3000 m should still be measured"
    for corner in reported:
        assert corner.start_m - APPROACH_M >= 3000.0, corner.name
    behind = [c for c in model.corners if c.end_m < 3000.0]
    assert behind, "this track must have corners before the join, or nothing is tested"
    assert not any(c.index in {r.index for r in reported} for c in behind)


def test_one_braking_event_is_not_coached_twice(two_laps):
    """Monza's Ascari is three corners and one stop.

    Offline, `advice()` drops the repeat because it can see the whole lap at
    once. The watch sees one corner at a time, so it has to remember instead -
    and it matters more here: a list read afterwards shows plainly that two
    entries are one braking event, but a panel just says the same sentence
    twice in two seconds while the driver is trying to drive.
    """
    model, fast, slow = two_laps
    spoken = [f for _at, f in _drive(slow, model.corners, fast) if f.to_say is not None]
    cited = [
        f.comparison.reference.brake_point_m
        for f in spoken
        if names_braking(f.to_say)
    ]
    assert cited, "this pair does produce braking advice, or the test proves nothing"
    for i, point in enumerate(cited):
        for earlier in cited[:i]:
            assert abs(point - earlier) >= SAME_BRAKING_M, [
                (f.comparison.corner.name, f.to_say.headline) for f in spoken
            ]


def test_a_suppressed_repeat_still_reports_its_corner(two_laps):
    """Silence about the braking is not the corner going missing. The numbers
    are still measured and still carried; only the sentence is withheld."""
    model, fast, slow = two_laps
    findings = [f for _at, f in _drive(slow, model.corners, fast)]
    repeats = [f for f in findings if f.advice is not None and f.to_say is None]
    assert repeats, "Ascari should produce at least one suppressed repeat"
    for finding in repeats:
        assert finding.comparison.differences or finding.comparison.lost_s


def test_a_new_lap_forgets_which_braking_was_already_named(two_laps):
    """Or the second lap goes quiet about every corner the first one covered."""
    model, fast, slow = two_laps
    watch = CornerWatch(fast, model.corners)
    buffer = LapBuffer(slow.grid)

    def run_one_lap():
        buffer.reset()
        watch.reset()
        said = []
        for i in range(len(slow.grid)):
            buffer.add(
                LiveSample(
                    float(slow.grid[i]), float(slow.time_s[i]),
                    float(slow.speed_kmh[i]), float(slow.throttle[i]),
                    float(slow.brake[i]), float(slow.steering[i]),
                )
            )
            said.extend(f for f in watch.advance(buffer) if f.to_say is not None)
        return [f.comparison.corner.index for f in said]

    assert run_one_lap() == run_one_lap()


def test_a_new_lap_starts_the_corners_again(two_laps):
    model, fast, slow = two_laps
    watch = CornerWatch(fast, model.corners)
    buffer = LapBuffer(slow.grid)
    for i in range(len(slow.grid)):
        buffer.add(
            LiveSample(
                float(slow.grid[i]), float(slow.time_s[i]), float(slow.speed_kmh[i]),
                float(slow.throttle[i]), float(slow.brake[i]), float(slow.steering[i]),
            )
        )
        watch.advance(buffer)

    assert watch.advance(buffer) == [], "the lap is over; nothing is left to report"
    watch.reset()
    buffer.reset()
    buffer.add(LiveSample(0.0, 0.0, 100.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(float(slow.grid[-1]), 90.0, 100.0, 1.0, 0.0, 0.0))
    assert watch.advance(buffer), "a second lap must report its corners too"
