"""The window a braking template is drawn over.

Everything here works in offsets into that window rather than in lap
distances. A window crossing the start/finish line is two ranges in lap
distance, and every consumer would have to know it; as an offset it is one
range that starts at zero.
"""

from dataclasses import replace as _replace

import numpy as np
import pytest

from lmu_telemetry.core.coaching import SAME_BRAKING_M
from lmu_telemetry.core.geometry import span_indices
from lmu_telemetry.core.metrics import APPROACH_M, corner_metrics
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.template import (
    Template,
    best_templates,
    braking_events,
    offset_into,
    template_from,
    templates_for,
)


def test_an_offset_is_measured_forward_from_the_window_start():
    assert offset_into(700.0, 900.0, 5800.0) == pytest.approx(200.0)
    assert offset_into(700.0, 700.0, 5800.0) == pytest.approx(0.0)


def test_an_offset_wraps_the_start_finish_line():
    """A window from 5700 m to 100 m is 200 m long, not minus 5600."""
    assert offset_into(5700.0, 5750.0, 5800.0) == pytest.approx(50.0)
    assert offset_into(5700.0, 50.0, 5800.0) == pytest.approx(150.0)


@pytest.fixture(scope="module")
def monza(monza_q_file):
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        laps = {lap.number: lap for lap in session.laps}
        trace = build_trace(session, laps[2], model.track_length_m)
    return model, trace


def test_a_template_is_made_for_every_corner_the_reference_braked_for(monza):
    model, trace = monza
    made = templates_for(trace, model.corners)
    assert made, "no templates at all"
    assert len(made) <= len(model.corners)
    for one in made:
        assert one.brake_at_m is not None


def test_a_corner_taken_flat_gets_no_template(monza):
    """It has nothing to teach here, and it would put a strip on the screen
    with no mark on it."""
    from lmu_telemetry.core.metrics import corner_metrics

    model, trace = monza
    made = {one.corner.index for one in templates_for(trace, model.corners)}
    for corner in model.corners:
        if corner_metrics(trace, corner).brake_point_m is None:
            assert corner.index not in made


def test_the_window_reaches_back_the_approach_distance(monza):
    model, trace = monza
    for one in templates_for(trace, model.corners):
        span = one.corner.end_m - one.corner.start_m
        if span < 0:
            span += trace.grid[-1]
        assert one.length_m == pytest.approx(APPROACH_M + span, abs=4.0)


def test_the_brake_mark_sits_inside_the_window(monza):
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert 0.0 <= one.brake_at_m <= one.length_m, one.corner.name
        assert 0.0 <= one.entry_at_m <= one.length_m


def test_the_traces_are_as_long_as_the_offsets(monza):
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert len(one.offsets_m) == len(one.brake) == len(one.throttle)
        assert len(one.abs_m) == len(one.offsets_m)
        assert one.offsets_m[0] == pytest.approx(0.0)


def test_the_offsets_only_ever_increase(monza):
    """Which is the property that makes a wrapping window one range."""
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert np.all(np.diff(one.offsets_m) > 0), one.corner.name


def test_the_pedal_traces_stay_inside_their_scale(monza):
    """The strip is drawn on a fixed 0..1 axis and must not run off it."""
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert one.brake.min() >= -0.01 and one.brake.max() <= 1.01
        assert one.throttle.min() >= -0.01 and one.throttle.max() <= 1.01


def test_the_reference_entry_speed_is_carried(monza):
    """So the strip can say how much slower the driver arrived, which is the
    one thing about the grey line that is not simply true today."""
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert one.entry_speed_kmh > 0.0


# -- shared braking events ---------------------------------------------------


def _expected_groups(model, trace):
    """Braked corners grouped the way templates_for groups them: consecutive
    in track order, and within SAME_BRAKING_M of the group's own last point.

    An independent restatement of the merge rule against real data, not a
    call into templates_for itself - so it is the corner list and the
    reference's own braking, not the implementation, that decides what the
    right groups are.
    """
    ordered = sorted(model.corners, key=lambda c: c.index)
    braked = [
        (c, corner_metrics(trace, c).brake_point_m) for c in ordered
        if corner_metrics(trace, c).brake_point_m is not None
    ]
    groups: "list[list[tuple]]" = []
    for corner, point in braked:
        if groups and abs(point - groups[-1][-1][1]) < SAME_BRAKING_M:
            groups[-1].append((corner, point))
        else:
            groups.append([(corner, point)])
    return [[corner for corner, _point in group] for group in groups]


def test_corners_sharing_a_brake_point_are_merged_into_one_template(monza):
    """Monza's Variante della Roggia and Variante Ascari each brake once in
    this recording, not once per corner - the live strip must not switch
    partway through what the driver felt as a single stop."""
    model, trace = monza
    groups = _expected_groups(model, trace)
    runs = [group for group in groups if len(group) > 1]
    assert runs, (
        "the fixture no longer has neighbouring corners that share a brake "
        "point - this test needs a run to mean anything"
    )

    made = {one.corner.index: one for one in templates_for(trace, model.corners)}
    for run in runs:
        head, tail = run[0], run[-1]
        assert head.index in made, head.name
        for corner in run[1:]:
            assert corner.index not in made, (
                f"{corner.name} should have been folded into {head.name}'s "
                f"template, not kept as one of its own"
            )
        merged = made[head.index]
        assert merged.corner.end_m == tail.end_m
        assert merged.corner.name == f"{head.name} - {tail.name}"


def test_the_template_count_drops_by_the_corners_folded_into_a_run(monza):
    """Counting one template per braked corner overcounts by exactly the
    corners a shared brake point folds into their neighbour."""
    model, trace = monza
    groups = _expected_groups(model, trace)
    made = templates_for(trace, model.corners)
    assert len(made) == len(groups)
    braked_corners = sum(len(group) for group in groups)
    assert len(made) < braked_corners, (
        "no merging happened at all - this test needs the fixture to have "
        "at least one shared brake point to say anything about the drop"
    )


def test_a_genuinely_separate_brake_point_keeps_its_own_template(monza):
    """A corner is not merged into its neighbour just for being next to it -
    only a brake point within SAME_BRAKING_M does that."""
    model, trace = monza
    groups = _expected_groups(model, trace)
    singles = [group[0] for group in groups if len(group) == 1]
    assert singles, "need at least one corner with a brake point of its own"

    made = {one.corner.index: one for one in templates_for(trace, model.corners)}
    for corner in singles:
        assert corner.index in made, corner.name
        one = made[corner.index]
        assert one.corner.name == corner.name
        assert one.corner.end_m == corner.end_m


# -- best-of-set templates ---------------------------------------------------
#
# templates_for draws every strip from the one reference lap. best_templates
# draws each from whichever of a pool of candidates drove that braking event
# quickest. The event set itself still comes from the reference alone, via
# braking_events, which templates_for is now built on top of too.


def test_braking_events_matches_what_templates_for_groups(monza):
    """braking_events is templates_for's own grouping, pulled out so a
    best-of-set caller can group once and fill many times."""
    model, trace = monza
    events = braking_events(trace, model.corners)
    made = templates_for(trace, model.corners)
    assert len(events) == len(made)
    assert [e.name for e in events] == [t.corner.name for t in made]
    assert [e.end_m for e in events] == [t.corner.end_m for t in made]


def test_template_from_is_none_for_a_lap_that_never_brakes(monza):
    """A lap that took an event flat is not a worse version of it - it is not
    a version at all, and must not be offered to best_templates."""
    model, trace = monza
    events = braking_events(trace, model.corners)
    never_brakes = _replace(trace, brake=np.zeros_like(trace.brake))
    assert template_from(never_brakes, events[0]) is None


def test_best_templates_with_only_the_reference_matches_templates_for(monza):
    model, trace = monza
    label = "Q 2026-03-28 lap 2"
    made = best_templates(trace, [(label, trace)], model.corners)
    plain = templates_for(trace, model.corners)
    assert len(made) == len(plain)
    for best, reference_only in zip(made, plain):
        assert best.corner == reference_only.corner
        assert best.start_m == pytest.approx(reference_only.start_m)
        assert best.length_m == pytest.approx(reference_only.length_m)
        assert best.brake_at_m == pytest.approx(reference_only.brake_at_m)
        assert best.entry_at_m == pytest.approx(reference_only.entry_at_m)
        assert best.entry_speed_kmh == pytest.approx(reference_only.entry_speed_kmh)
        assert np.allclose(best.offsets_m, reference_only.offsets_m)
        assert np.allclose(best.abs_m, reference_only.abs_m)
        assert np.allclose(best.brake, reference_only.brake)
        assert np.allclose(best.throttle, reference_only.throttle)
        assert best.source == label


def test_best_templates_picks_the_quicker_laps_version(monza):
    """A lap built to be measurably quicker through exactly one event, and
    identical everywhere else, must move only that event's template."""
    model, trace = monza
    events = braking_events(trace, model.corners)
    target = next(e for e in events if e.start_m < e.end_m)
    inside = span_indices(trace.grid, target.start_m, target.end_m)
    assert len(inside) >= 2, "test needs a real span to shrink"

    # Halve the elapsed time across this one event's own samples and nowhere
    # else, so every other event's corner_metrics(...).time_s is untouched
    # and the reference - listed first, so it wins ties - keeps them.
    quicker_time = trace.time_s.copy()
    quicker_time[inside] = trace.time_s[inside[0]] + (
        trace.time_s[inside] - trace.time_s[inside[0]]
    ) * 0.5
    quicker = _replace(trace, time_s=quicker_time)

    made = best_templates(
        trace, [("reference", trace), ("quicker lap", quicker)], model.corners
    )
    by_index = {t.corner.index: t for t in made}
    plain = {t.corner.index: t for t in templates_for(trace, model.corners)}

    assert by_index[target.index].source == "quicker lap"
    for index, template in by_index.items():
        if index == target.index:
            continue
        assert template.source == "reference"
        assert template.brake_at_m == pytest.approx(plain[index].brake_at_m)
        assert np.allclose(template.brake, plain[index].brake)


def test_every_template_from_best_templates_has_a_source(monza):
    model, trace = monza
    made = best_templates(trace, [("Q 2026-03-28 lap 2", trace)], model.corners)
    assert made
    assert all(t.source for t in made)


def test_adding_a_lap_that_brakes_elsewhere_does_not_change_the_event_set(monza):
    """The strip set is grouped from the reference alone. A candidate that
    brakes hard everywhere - including corners the reference took flat - must
    not add a strip, because best_templates only ever asks about the events
    braking_events already found."""
    model, trace = monza
    events = braking_events(trace, model.corners)

    brakes_everywhere = _replace(trace, brake=np.ones_like(trace.brake))
    made = best_templates(
        trace,
        [("reference", trace), ("brakes everywhere", brakes_everywhere)],
        model.corners,
    )
    assert len(made) == len(events)
    assert {t.corner.index for t in made} == {e.index for e in events}


# -- arming ----------------------------------------------------------------

from lmu_telemetry.live.template import TEMPLATE_HOLD_S, TemplateWatch

LAP = 6000.0


def _one_template():
    """A window from 700 m to 1100 m, braking at 800 m, corner starting 950 m."""
    offsets = np.arange(0.0, 401.0, 2.0)
    corner = _corner_at(950.0, 1100.0)
    return Template(
        corner=corner, start_m=700.0, length_m=400.0,
        brake_at_m=100.0, entry_at_m=250.0, entry_speed_kmh=180.0,
        offsets_m=offsets, abs_m=offsets + 700.0,
        brake=np.zeros_like(offsets), throttle=np.ones_like(offsets),
    )


def _corner_at(start_m, end_m, index=1):
    from lmu_telemetry.core.corners import Corner

    return Corner(index=index, name="T1", start_m=start_m,
                  apex_m=(start_m + end_m) / 2, end_m=end_m,
                  radius_m=60.0, heading_deg=90.0, direction="L")


def test_nothing_shows_before_the_window():
    watch = TemplateWatch([_one_template()], LAP)
    assert watch.showing(400.0, 0.0) is None


def test_the_template_shows_inside_its_window():
    watch = TemplateWatch([_one_template()], LAP)
    found = watch.showing(800.0, 0.0)
    assert found is not None
    assert found.at_m == pytest.approx(100.0)
    assert found.past_corner is False


def test_it_is_held_briefly_after_the_corner():
    """During the corner the driver has no attention to spare. Afterwards is
    when they can look at whether it fitted."""
    watch = TemplateWatch([_one_template()], LAP)
    watch.showing(1000.0, 10.0)
    held = watch.showing(1200.0, 10.5)
    assert held is not None
    assert held.past_corner is True


def test_the_hold_lets_go():
    watch = TemplateWatch([_one_template()], LAP)
    watch.showing(1000.0, 10.0)
    watch.showing(1200.0, 10.5)
    assert watch.showing(1400.0, 10.0 + TEMPLATE_HOLD_S + 0.1) is None


def test_the_tone_falls_due_once_at_the_brake_point():
    watch = TemplateWatch([_one_template()], LAP)
    watch.showing(750.0, 0.0)
    assert watch.tone_due(750.0) is False, "before the mark"
    assert watch.tone_due(805.0) is True, "at the mark"
    assert watch.tone_due(850.0) is False, "already sounded"
    assert watch.tone_due(900.0) is False


def test_the_tone_is_not_due_outside_a_window():
    watch = TemplateWatch([_one_template()], LAP)
    assert watch.tone_due(400.0) is False


def test_a_new_lap_arms_everything_again():
    watch = TemplateWatch([_one_template()], LAP)
    watch.showing(750.0, 0.0)
    watch.tone_due(805.0)

    watch.reset()
    watch.showing(750.0, 100.0)
    assert watch.tone_due(805.0) is True


def test_a_window_across_the_line_still_arms():
    """The one case offsets exist for."""
    offsets = np.arange(0.0, 401.0, 2.0)
    across = Template(
        corner=_corner_at(150.0, 300.0), start_m=5900.0, length_m=400.0,
        brake_at_m=100.0, entry_at_m=250.0, entry_speed_kmh=180.0,
        offsets_m=offsets, abs_m=(offsets + 5900.0) % LAP,
        brake=np.zeros_like(offsets), throttle=np.ones_like(offsets),
    )
    watch = TemplateWatch([across], LAP)
    assert watch.showing(5950.0, 0.0) is not None, "before the line"
    found = watch.showing(100.0, 0.1)
    assert found is not None and found.at_m == pytest.approx(200.0)
    assert watch.tone_due(5000.0) is False, "the far side of the lap"


def test_the_nearest_window_wins_when_two_overlap():
    """Ascari's corners are close enough that their approaches overlap. The
    one being driven into is the one whose window started most recently."""
    first = _one_template()
    second = Template(
        corner=_corner_at(1150.0, 1300.0), start_m=900.0, length_m=400.0,
        brake_at_m=100.0, entry_at_m=250.0, entry_speed_kmh=170.0,
        offsets_m=np.arange(0.0, 401.0, 2.0),
        abs_m=np.arange(0.0, 401.0, 2.0) + 900.0,
        brake=np.zeros(201), throttle=np.ones(201),
    )
    watch = TemplateWatch([first, second], LAP)
    found = watch.showing(1000.0, 0.0)
    assert found.template.corner.start_m == 1150.0


def test_the_most_recently_left_window_wins_the_hold():
    """The same tie-break the inside loop makes, made in the hold loop too.
    Two overlapping windows can both still be within TEMPLATE_HOLD_S once the
    car is outside both - the one the driver left last should win, not
    whichever template happens to come first in the list."""
    first = _one_template()
    second = Template(
        corner=_corner_at(1150.0, 1300.0, index=2), start_m=900.0, length_m=400.0,
        brake_at_m=100.0, entry_at_m=250.0, entry_speed_kmh=170.0,
        offsets_m=np.arange(0.0, 401.0, 2.0),
        abs_m=np.arange(0.0, 401.0, 2.0) + 900.0,
        brake=np.zeros(201), throttle=np.ones(201),
    )
    watch = TemplateWatch([first, second], LAP)
    watch.showing(800.0, 0.0)      # inside first only
    watch.showing(1200.0, 0.5)     # inside second only, left after first
    held = watch.showing(1350.0, TEMPLATE_HOLD_S)   # outside both, both held
    assert held is not None
    assert held.template.corner.start_m == 1150.0


# -- driving a recorded lap through it -------------------------------------


def test_a_recorded_lap_arms_every_braked_corner_once(monza):
    """The end-to-end property: driving the reference through its own
    templates sounds each corner exactly once, in track order."""
    model, trace = monza
    made = templates_for(trace, model.corners)
    watch = TemplateWatch(made, float(trace.grid[-1]) + 2.0)

    sounded = []
    for i in range(len(trace.grid)):
        here = float(trace.grid[i])
        watch.showing(here, i * 0.02)
        if watch.tone_due(here):
            sounded.append(here)

    assert len(sounded) == len(made), f"{len(sounded)} tones, {len(made)} corners"
    assert sounded == sorted(sounded), "tones out of track order"


def test_the_drivers_line_is_sampled_where_the_reference_was(monza):
    """The claim the strip rests on. Interpolating the driver's own trace at
    the template's own distances is what makes the two comparable."""
    model, trace = monza
    one = templates_for(trace, model.corners)[0]
    own = np.interp(one.abs_m, trace.grid, trace.brake)
    assert np.allclose(own, one.brake, atol=1e-9), (
        "the reference sampled at its own distances is not itself"
    )
