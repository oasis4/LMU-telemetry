"""Advice only where the measurements agree on a story.

The rule this file exists to enforce: a sentence about *why* a corner cost
time may only appear when several independent measurements point the same
way, and it must carry those measurements with it. Braking later on its own
means nothing - it is what a faster driver does.
"""

import numpy as np
import pytest

from lmu_telemetry.core.coaching import (
    ADVICE_MIN_LOSS_S,
    ADVICE_POINT_M,
    ADVICE_SPEED_KMH,
    advice,
    compare_corners,
)
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import LapTrace, build_trace

LAP_M = 2000.0
CORNER = Corner(
    index=1, name="T1", start_m=900.0, apex_m=950.0, end_m=1000.0,
    radius_m=80.0, heading_deg=90.0, direction="L",
)


def _index(distance_m):
    return int(distance_m / GRID_STEP_M)


def _trace(speed_kmh=None, throttle=None, brake=None, pace_kmh=150.0):
    grid = grid_for(LAP_M)
    n = len(grid)
    speed = np.full(n, pace_kmh) if speed_kmh is None else np.asarray(speed_kmh, float)
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))
    return LapTrace(
        lap=None, grid=grid, time_s=time_s, speed_kmh=speed,
        throttle=np.zeros(n) if throttle is None else np.asarray(throttle, float),
        brake=np.zeros(n) if brake is None else np.asarray(brake, float),
        steering=np.zeros(n),
    )


def _brake_from(distance_m):
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(distance_m) : _index(920.0)] = 0.8
    return brake


def _trail_brake(start_m, peak_m, release_m):
    """Pressure up at *start_m*, highest at *peak_m*, bled off by *release_m*."""
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(start_m) : _index(peak_m)] = 0.6
    brake[_index(peak_m)] = 1.0
    taper = np.linspace(1.0, 0.0, _index(release_m) - _index(peak_m) + 2)[1:-1]
    brake[_index(peak_m) + 1 : _index(release_m) + 1] = taper
    return brake


def _throttle_from(distance_m):
    throttle = np.zeros(len(grid_for(LAP_M)))
    throttle[_index(distance_m) :] = 1.0
    return throttle


def _slow_through(minimum_kmh, exit_kmh=200.0, pace=200.0):
    speed = np.full(len(grid_for(LAP_M)), pace)
    speed[_index(900.0) : _index(1000.0)] = minimum_kmh
    speed[_index(1000.0) :] = exit_kmh
    return speed


def _advice_for(reference, other):
    return advice(compare_corners(reference, other, [CORNER]))


def test_a_different_brake_shape_alone_says_nothing():
    """Two valid styles, not a fault.

    One driver stops the car and turns it; the other carries the brake to the
    apex. The corner cost nothing and the outcome matched, so there is no
    result to attach the shape to - and telemetry cannot tell a style from a
    mistake without one.
    """
    speed = _slow_through(100.0)
    reference = _trace(brake=_trail_brake(800.0, 820.0, 860.0), speed_kmh=speed)
    other = _trace(brake=_trail_brake(800.0, 820.0, 960.0), speed_kmh=speed)
    assert _advice_for(reference, other) == []


def test_a_brake_shape_difference_with_a_matched_outcome_stays_quiet():
    """The corner cost time and the shape really did differ - and still nothing.

    Neither the minimum nor the exit is measurably worse, so nothing ties the
    loss to the shape. Naming it here would be a guess wearing a number, which
    is the failure this whole feature is built to avoid.
    """
    reference = _trace(brake=_trail_brake(800.0, 820.0, 860.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(800.0, 820.0, 960.0), speed_kmh=_slow_through(98.0))

    comparison = compare_corners(reference, other, [CORNER])[0]
    assert comparison.lost_s > ADVICE_MIN_LOSS_S, "the corner must actually cost time"
    assert "trail length" in [d.what for d in comparison.differences], (
        "the shape difference must be visible, or this tests nothing"
    )
    assert abs(comparison.other.min_speed_kmh - comparison.reference.min_speed_kmh) < (
        ADVICE_SPEED_KMH
    ), "the outcome must be matched, or this tests the wrong rule"

    found = advice([comparison])
    assert all(
        "trail" not in a.because and "brake peak" not in a.because for a in found
    ), [a.headline for a in found]


def test_braking_later_alone_says_nothing():
    """It is what a faster driver does. On its own it is not a fault."""
    reference = _trace(brake=_brake_from(800.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(830.0), speed_kmh=_slow_through(100.0))
    assert _advice_for(reference, other) == []


def test_braking_later_while_losing_time_is_still_not_a_braking_story():
    """Time lost *in* the corner, brake point later - and the entry matched.

    The minimum speed is identical, so the loss is on the exit and the brake
    point does not explain it. Telling this driver to brake earlier would
    point them away from where the time actually went.

    Getting this scenario right took two attempts. Both earlier versions lost
    no time in the corner itself, so the loss threshold refused them and the
    "several measurements must agree" rule was never reached - the test passed
    with that rule deleted.
    """
    reference_speed = np.full(len(grid_for(LAP_M)), 200.0)
    reference_speed[_index(900.0) : _index(950.0)] = 100.0
    reference_speed[_index(950.0) : _index(1000.0)] = 160.0   # picks up well

    other_speed = reference_speed.copy()
    other_speed[_index(950.0) : _index(1000.0)] = 105.0       # does not

    reference = _trace(brake=_brake_from(800.0), speed_kmh=reference_speed)
    other = _trace(brake=_brake_from(840.0), speed_kmh=other_speed)

    comparison = compare_corners(reference, other, [CORNER])[0]
    assert comparison.lost_s > ADVICE_MIN_LOSS_S, "the corner must actually cost time"
    assert comparison.other.min_speed_kmh == pytest.approx(
        comparison.reference.min_speed_kmh
    ), "the entry must be matched, or this tests the wrong rule"

    found = advice([comparison])
    assert all("braking earlier" not in a.headline.lower() for a in found), [
        a.headline for a in found
    ]


def test_a_late_throttle_with_a_worse_entry_is_read_as_the_entry():
    """Both a later throttle point and a lower minimum speed.

    The throttle rule must not claim this one: the entry was not matched, so
    the throttle point is as likely a consequence as a cause.
    """
    reference = _trace(
        brake=_brake_from(800.0),
        throttle=_throttle_from(960.0),
        speed_kmh=_slow_through(100.0),
    )
    other = _trace(
        brake=_brake_from(800.0),
        throttle=_throttle_from(995.0),
        speed_kmh=_slow_through(80.0),
    )

    found = _advice_for(reference, other)
    assert found, "a corner this much slower should say something"
    assert all("power earlier" not in a.headline.lower() for a in found), [
        a.headline for a in found
    ]


def test_braking_later_and_slower_through_the_middle_is_a_story():
    reference = _trace(brake=_brake_from(800.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(840.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "braking earlier" in found[0].headline.lower()


def test_braking_early_with_a_short_trail_is_told_to_stay_on_the_brake():
    """Braked earlier, off the pedal sooner, and slower through the middle.

    The car was slowed in a straight line and then rolled through with no
    brake left to turn it. The coarse rule can only say "brake later"; the
    trail is what makes the second half of the sentence true.
    """
    reference = _trace(brake=_trail_brake(840.0, 860.0, 940.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(790.0, 810.0, 850.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "longer" in found[0].headline.lower()
    assert "trail length" in found[0].because
    assert "brake point" in found[0].because


def test_braking_early_without_a_trail_difference_still_gets_the_coarse_rule():
    """The finer rule refines rule 2; it must not swallow it."""
    reference = _trace(brake=_brake_from(840.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(790.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "brake later" in found[0].headline.lower()
    assert "trail length" not in found[0].because


def test_braking_earlier_and_still_slower_is_the_other_story():
    reference = _trace(brake=_brake_from(840.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(790.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "brake later" in found[0].headline.lower()


def test_a_late_throttle_pick_up_with_a_slower_exit():
    """The exit has to be slower *inside* the corner, or nothing was lost there.

    A first version of this test put the slower stretch after the corner's end
    and got no advice - correctly, because that corner cost no time. The
    threshold did its job; the scenario was wrong.
    """
    fast = np.full(len(grid_for(LAP_M)), 200.0)
    fast[_index(900.0) : _index(970.0)] = 100.0     # same through the middle
    slow = fast.copy()
    fast[_index(970.0) : _index(1000.0)] = 190.0    # reference picks up early
    slow[_index(970.0) : _index(1000.0)] = 120.0    # this lap does not

    reference = _trace(throttle=_throttle_from(965.0), speed_kmh=fast)
    other = _trace(throttle=_throttle_from(995.0), speed_kmh=slow)

    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "power earlier" in found[0].headline.lower()
    assert "throttle point" in found[0].because


def test_a_long_trail_with_a_slower_exit_is_told_to_release_earlier():
    """The entry matched; the brake was still on where the throttle belonged.

    The slower stretch has to reach the corner's last sample, which is where
    exit speed is read. Ended at 1000 m it stops one sample short, both laps
    read 200 km/h there, and the rule this test exists for never fires.
    """
    fast = np.full(len(grid_for(LAP_M)), 200.0)
    fast[_index(900.0) : _index(960.0)] = 100.0    # matched through the middle
    slow = fast.copy()
    fast[_index(960.0) : _index(1010.0)] = 190.0   # the reference picks up
    slow[_index(960.0) : _index(1010.0)] = 120.0   # this lap is still slowing

    reference = _trace(brake=_trail_brake(800.0, 820.0, 900.0), speed_kmh=fast)
    other = _trace(brake=_trail_brake(800.0, 820.0, 980.0), speed_kmh=slow)

    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "off the brake earlier" in found[0].headline.lower()
    assert "trail length" in found[0].because
    assert "exit speed" in found[0].because


def test_a_long_trail_with_a_worse_entry_is_not_read_as_the_release():
    """Both a longer trail and a lower minimum speed.

    The trail rule must not claim this one: with the entry unmatched, the long
    trail is as likely a consequence - a driver still slowing because they
    arrived too fast - as a cause. Telling them to release earlier would point
    them away from the corner they actually entered too quickly.
    """
    reference = _trace(brake=_trail_brake(800.0, 820.0, 880.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(800.0, 820.0, 970.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert found, "a corner this much slower should say something"
    assert all("off the brake earlier" not in a.headline.lower() for a in found), [
        a.headline for a in found
    ]


def test_every_piece_of_advice_carries_the_numbers_it_rests_on():
    reference = _trace(brake=_brake_from(800.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(840.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)[0]
    assert any(ch.isdigit() for ch in found.because)
    assert "km/h" in found.because
    assert "s" in found.because


def test_a_corner_that_cost_nothing_gets_no_advice():
    """Below the threshold the differences are lap-to-lap variation, and a
    confident sentence about them is noise given a voice."""
    speed = _slow_through(100.0)
    reference = _trace(brake=_brake_from(800.0), speed_kmh=speed)
    other = _trace(brake=_brake_from(840.0), speed_kmh=speed - 0.05)
    found = _advice_for(reference, other)
    assert found == []


def test_a_difference_inside_the_recordings_resolution_is_not_a_story():
    """Lap Dist is 10 Hz, so 5-8 m separate its samples at racing speed."""
    assert ADVICE_POINT_M > 8.0
    reference = _trace(brake=_brake_from(800.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(806.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    # The brake point is unchanged within the resolution, so the story that
    # remains is the corner speed itself, not the braking.
    assert len(found) == 1
    assert "corner speed" in found[0].headline.lower()


def test_advice_is_ordered_worst_corner_first():
    corners = [
        Corner(index=1, name="T1", start_m=300.0, apex_m=350.0, end_m=400.0,
               radius_m=80.0, heading_deg=90.0, direction="L"),
        Corner(index=2, name="T2", start_m=900.0, apex_m=950.0, end_m=1000.0,
               radius_m=80.0, heading_deg=90.0, direction="L"),
    ]
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(300.0) : _index(400.0)] = 100.0
    speed[_index(900.0) : _index(1000.0)] = 100.0
    slow = speed.copy()
    slow[_index(300.0) : _index(400.0)] = 90.0    # small loss
    slow[_index(900.0) : _index(1000.0)] = 60.0   # big loss

    found = advice(compare_corners(_trace(speed_kmh=speed), _trace(speed_kmh=slow), corners))
    assert [a.corner.index for a in found] == [2, 1]


@pytest.mark.corpus
def test_advice_on_real_laps_never_speaks_without_evidence(corpus_dir):
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        laps = [l for l in s.laps if l.number in (2, 3)]
        a, b = (build_trace(s, lap, model.track_length_m) for lap in laps)
        comparisons = compare_corners(a, b, model.corners)
        found = advice(comparisons)

    assert len(found) <= len(comparisons)
    for item in found:
        assert item.lost_s >= ADVICE_MIN_LOSS_S
        assert any(ch.isdigit() for ch in item.because)
    # Fewer than one per corner is the expected outcome, not a failure.
    assert len(found) < len(comparisons)


def test_one_braking_event_produces_one_piece_of_advice():
    """Monza's Ascari is three corners and one stop.

    Each corner resolves the same braking run as its own brake point, so
    without this the app says "brake later" three times about one brake
    application - three findings where there is one. Observed on real laps:
    Ascari 1 and 2 both reported a 96 m difference from the same event.
    """
    corners = [
        Corner(index=1, name="Ascari 1", start_m=900.0, apex_m=930.0, end_m=960.0,
               radius_m=80.0, heading_deg=90.0, direction="L"),
        Corner(index=2, name="Ascari 2", start_m=960.0, apex_m=990.0, end_m=1020.0,
               radius_m=80.0, heading_deg=90.0, direction="R"),
    ]
    # One braking run before the complex, and both corners slower right through.
    reference_brake = np.zeros(len(grid_for(LAP_M)))
    reference_brake[_index(840.0) : _index(900.0)] = 0.8
    other_brake = np.zeros(len(grid_for(LAP_M)))
    other_brake[_index(800.0) : _index(900.0)] = 0.8

    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(900.0) : _index(1020.0)] = 110.0
    slow = speed.copy()
    slow[_index(900.0) : _index(1020.0)] = 85.0

    found = advice(
        compare_corners(
            _trace(brake=reference_brake, speed_kmh=speed),
            _trace(brake=other_brake, speed_kmh=slow),
            corners,
        )
    )
    braking = [a for a in found if "brake point" in a.because]
    assert len(braking) == 1, [a.corner.name for a in braking]


def test_two_separate_braking_events_both_get_advice():
    """The guard must not silence a genuinely different corner."""
    corners = [
        Corner(index=1, name="T1", start_m=300.0, apex_m=340.0, end_m=380.0,
               radius_m=80.0, heading_deg=90.0, direction="L"),
        Corner(index=2, name="T2", start_m=900.0, apex_m=940.0, end_m=980.0,
               radius_m=80.0, heading_deg=90.0, direction="R"),
    ]
    reference_brake = np.zeros(len(grid_for(LAP_M)))
    reference_brake[_index(240.0) : _index(300.0)] = 0.8
    reference_brake[_index(840.0) : _index(900.0)] = 0.8
    other_brake = np.zeros(len(grid_for(LAP_M)))
    other_brake[_index(200.0) : _index(300.0)] = 0.8
    other_brake[_index(800.0) : _index(900.0)] = 0.8

    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(300.0) : _index(380.0)] = 110.0
    speed[_index(900.0) : _index(980.0)] = 110.0
    slow = speed.copy()
    slow[_index(300.0) : _index(380.0)] = 85.0
    slow[_index(900.0) : _index(980.0)] = 85.0

    found = advice(
        compare_corners(
            _trace(brake=reference_brake, speed_kmh=speed),
            _trace(brake=other_brake, speed_kmh=slow),
            corners,
        )
    )
    assert len([a for a in found if "brake point" in a.because]) == 2


def test_the_thresholds_are_above_what_the_recording_resolves():
    assert ADVICE_SPEED_KMH >= 1.0
    assert ADVICE_POINT_M >= 2 * 5.0
    assert ADVICE_MIN_LOSS_S > 0.0
