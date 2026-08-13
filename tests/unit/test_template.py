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
from lmu_telemetry.core.geometry import GRID_STEP_M, span_indices
from lmu_telemetry.core.metrics import APPROACH_M, corner_metrics
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.template import (
    LEAD_S,
    MIN_LEAD_M,
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


def test_the_window_opens_the_same_lead_time_before_the_mark(monza):
    """The fix itself. Before this, the window opened corner.start_m -
    APPROACH_M and the warning it gave depended only on where the brake
    point happened to fall inside that fixed 250 m span - measured on this
    same fixture (see test_a_corner_whose_old_window_gave_zero_warning_now_
    gets_some below), that ranged from 0 s to over 6 s of warning, corner to
    corner, on one lap.

    Measured as *elapsed time along the real trace* between the window's own
    opening frame and the brake mark - by interpolating trace.time_s at both
    ends, which is not how _window_start finds them (it indexes time_s and
    counts grid steps). So this asks what a driver watching the clock would
    actually see, rather than restating the implementation's own arithmetic
    back at itself.

    A tenth of a second of tolerance, not a third: the window can only open
    on a grid point, so the achievable precision is one GRID_STEP_M of travel
    - about 30 ms at 250 km/h, about 100 ms at 70 km/h through a chicane -
    and this fixture's 8 events land between 1.948 s and 1.998 s. Anything
    looser would have passed the bug this replaces at three of them.

    None of this fixture's events trip the two guards below, which is what
    makes a tight bound legitimate here; test_a_mark_inside_the_corner_keeps_
    the_entry_in_the_window covers the case that deliberately overrides
    LEAD_S.
    """
    model, trace = monza
    for one in templates_for(trace, model.corners):
        mark_index = int(np.searchsorted(one.offsets_m, one.brake_at_m))
        mark_abs_m = one.abs_m[mark_index]
        opens_at_s = float(np.interp(one.start_m, trace.grid, trace.time_s))
        marks_at_s = float(np.interp(mark_abs_m, trace.grid, trace.time_s))
        lead_s = marks_at_s - opens_at_s
        assert lead_s == pytest.approx(LEAD_S, abs=0.1), (
            f"{one.corner.name}: window opened {lead_s:.2f} s before its "
            f"own mark, not the ~{LEAD_S} s every corner should agree on"
        )


def test_no_event_opens_with_zero_warning(monza):
    """The complaint itself: Ascari 3 used to tell the driver to brake with
    the mark already crossed. brake_at_m is exactly the window's own lead
    distance (the offset from where it opens to the mark), so this is
    checking there is always *some* strip ahead of the mark, whatever
    guard ended up deciding how much."""
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert one.brake_at_m > 0.0, one.corner.name


def test_a_corner_whose_old_window_gave_zero_warning_now_gets_some(monza):
    """Not a hypothetical - Monza's own reference has one. Its last brake
    application before the corner starts right where the old search span
    (corner.start_m - APPROACH_M) stopped looking, which is also where the
    old *display* window opened - so the old window put the brake mark on
    its own first frame, the "0 m ahead" case in the driver's report.
    Identified generically (whichever corner exhibits it in *this* fixture),
    not by name, since it is a property of the reference's own braking, not
    of one corner's label."""
    model, trace = monza
    lap_length_m = float(trace.grid[-1]) + GRID_STEP_M
    events = braking_events(trace, model.corners)
    culprits = []
    for event in events:
        figures = corner_metrics(trace, event)
        if figures.brake_point_m is None:
            continue
        old_open = (event.start_m - APPROACH_M) % lap_length_m
        old_warning = offset_into(old_open, figures.brake_point_m, lap_length_m)
        if old_warning < GRID_STEP_M:
            culprits.append(event)
    assert culprits, (
        "the fixture no longer has a corner whose old window gave (near) "
        "zero warning - this test needs one to mean anything"
    )

    made = {one.corner.index: one for one in templates_for(trace, model.corners)}
    for event in culprits:
        assert made[event.index].brake_at_m > 50.0, (
            f"{event.name} still opens with almost no warning"
        )


def test_the_window_still_ends_at_the_corners_own_end(monza):
    """The one part of the old window this fix does not touch."""
    model, trace = monza
    for one in templates_for(trace, model.corners):
        assert one.abs_m[-1] == pytest.approx(one.corner.end_m, abs=GRID_STEP_M)


# -- the floor and the ceiling ------------------------------------------------
#
# Neither shows up in the Monza fixture as recorded, so both are built rather
# than found, the same way test_template_from_is_none_for_a_lap_that_never_
# brakes builds its own case below.
#
# What is rewritten is time_s - the clock _window_start actually reads - and
# only over the approach strictly before the corner's own start. Not
# speed_kmh: nothing downstream of the window derives from it, so a test that
# moved it would pass whatever the window did. time_s must stay increasing
# across the whole lap or every later distance reads as time travel, so these
# rebuild it from its own steps rather than overwriting a slice in place.


def _with_approach_pace(trace, event, step_s):
    """*trace* with each grid step of *event*'s approach taking *step_s*.

    Only the steps before the corner's own start are touched; the rest of the
    lap keeps its own pace and is carried forward by the running total, so the
    clock stays monotonic and the brake channel - and therefore the brake
    point _brake_shape finds - is untouched.
    """
    lap_length_m = float(trace.grid[-1]) + GRID_STEP_M
    approach = span_indices(
        trace.grid, (event.start_m - APPROACH_M) % lap_length_m, event.start_m
    )
    approach = approach[trace.grid[approach] < event.start_m]
    assert len(approach), "test setup needs an approach zone to re-pace"
    steps = np.diff(trace.time_s, prepend=trace.time_s[0])
    steps[approach] = step_s
    return _replace(trace, time_s=np.cumsum(steps) + float(trace.time_s[0]))


def test_a_very_low_speed_at_the_mark_still_gets_a_useful_window(monza):
    """The floor: a brake point crawled up to. At 1 s per 2 m step - about
    7 km/h - LEAD_S alone would open the window 4 m before the mark, which is
    the mark and one sample either side, not a shape worth glancing at."""
    model, trace = monza
    event = braking_events(trace, model.corners)[0]

    template = template_from(_with_approach_pace(trace, event, 1.0), event)
    assert template is not None
    assert template.brake_at_m == pytest.approx(MIN_LEAD_M, abs=GRID_STEP_M)


def test_an_extreme_speed_at_the_mark_never_reaches_further_than_approach_m(monza):
    """The ceiling: at 1 ms per 2 m step - about 7200 km/h - LEAD_S would ask
    for two kilometres of lead. Built at a speed no real lap has, to show the
    cap holds rather than assume it because nothing has tripped it: the strip
    must never show track from further back than _brake_shape was allowed to
    look for a brake point over."""
    model, trace = monza
    event = braking_events(trace, model.corners)[0]

    template = template_from(_with_approach_pace(trace, event, 0.001), event)
    assert template is not None
    assert template.brake_at_m == pytest.approx(APPROACH_M, abs=GRID_STEP_M)


def test_a_mark_inside_the_corner_keeps_the_entry_in_the_window(monza):
    """The third guard, and the one that actually fires on real laps: 106 of
    1705 events across the corpus are corners the reference trail-braked deep
    enough that the brake mark sits *past* corner.start_m.

    LEAD_S alone would then open the window after the corner had already
    begun, and every offset in this module is measured forward from the
    window's own start and wraps - so entry_at_m would come back as nearly a
    whole lap instead of a small number, and the entry-speed readout would be
    drawn off the end of the strip it belongs to. The window has to give way
    and open at the corner's own start.

    Built by re-pacing the stretch *inside* the corner, unlike the two above:
    the guard needs the car to take longer than LEAD_S to get from the
    corner's start to the mark, which is exactly what a slow corner entry is.
    """
    model, trace = monza
    lap_length_m = float(trace.grid[-1]) + GRID_STEP_M

    # Whichever event has the most room between its start and its apex - the
    # mark has to land more than MIN_LEAD_M inside the corner, or the floor
    # reaches back past the start on its own and the guard is never asked.
    def apex_of(event):
        inside = span_indices(trace.grid, event.start_m, event.end_m)
        return int(np.argmin(trace.speed_kmh[inside]))

    event = max(braking_events(trace, model.corners), key=apex_of)
    inside = span_indices(trace.grid, event.start_m, event.end_m)
    apex = apex_of(event)
    mark = apex - 5
    assert mark * GRID_STEP_M > MIN_LEAD_M + GRID_STEP_M, (
        "test setup needs a corner whose apex is further in than the floor"
    )

    # One brake application there and nothing before it, so _brake_shape's
    # mark lands inside the corner rather than on the real approach. It must
    # sit before the apex, which is where that search stops.
    brake = trace.brake.copy()
    brake[span_indices(
        trace.grid, (event.start_m - APPROACH_M) % lap_length_m, event.end_m
    )] = 0.0
    brake[inside[mark:apex]] = 0.8

    # 0.2 s per 2 m step is about 36 km/h, so the stretch from the corner's
    # start to that mark takes far longer than LEAD_S and a 2 s walk back
    # from it cannot reach the start.
    steps = np.diff(trace.time_s, prepend=trace.time_s[0])
    steps[inside[:apex]] = 0.2
    crawling = _replace(
        trace, brake=brake,
        time_s=np.cumsum(steps) + float(trace.time_s[0]),
    )

    template = template_from(crawling, event)
    assert template is not None
    assert template.brake_at_m > 0.0, "the mark must still be ahead on the strip"
    assert template.entry_at_m == pytest.approx(0.0, abs=GRID_STEP_M), (
        "the window should have opened at the corner's own start"
    )
    assert 0.0 <= template.entry_at_m <= template.length_m, (
        "the entry wrapped out of its own window - the fault this guards"
    )


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


# -- the reference-in-the-pool guarantee -------------------------------------
#
# best_templates must never return fewer events than braking_events found,
# and that has to be true regardless of what *others* turns out to hold - not
# only in the ordinary case where a caller remembered to put the reference in
# it. These drive the fallback directly: an empty pool, and a pool that holds
# a real, different lap but not the reference.


def test_best_templates_covers_every_event_even_with_no_candidates_at_all(monza):
    """A candidate scan that came back empty - no recordings matched, or
    every one of them failed to rebuild - must still produce the full set of
    strips, from the reference itself, not fewer."""
    model, trace = monza
    events = braking_events(trace, model.corners)
    plain = templates_for(trace, model.corners)

    made = best_templates(trace, [], model.corners)

    assert len(made) == len(events)
    assert {t.corner.index for t in made} == {e.index for e in events}
    by_index = {t.corner.index: t for t in made}
    for template in plain:
        assert template.brake_at_m == pytest.approx(
            by_index[template.corner.index].brake_at_m
        )
        assert np.allclose(template.brake, by_index[template.corner.index].brake)
        assert by_index[template.corner.index].source == ""


def test_best_templates_falls_back_to_the_reference_for_an_event_the_only_candidate_misses(
    monza,
):
    """The reference lap belongs in *others* in the ordinary case - it is
    ``find_quickest_laps``'s own first element - but best_templates must not
    depend on a caller having put it there. This is a test of the fallback
    actually *firing*, not just of the final count - a test built on a real
    other lap that happens to brake everywhere the reference does would pass
    whether or not the fallback existed, and prove nothing.

    So the candidate here is built, not found: identical to the reference
    everywhere except across one event's own window, where its brake channel
    is held at zero - genuinely never touching the pedal there, not merely
    slower to. That event can then only be filled from the reference; a
    second, untouched event is left as a control the candidate can still
    win, so the assertion below is specifically "the gap came from the
    fallback and a real win still came from the candidate", not just "the
    count came out right".
    """
    model, trace = monza
    events = braking_events(trace, model.corners)
    non_wrapping = [e for e in events if e.start_m < e.end_m]
    assert len(non_wrapping) >= 2, "test needs two straightforward events"

    # First and last, not two neighbours: adjacent events' APPROACH_M windows
    # overlap at Monza (T1's reaches back into T2's own corner), and zeroing
    # one's window would blind the candidate in the other's too.
    missing, present = non_wrapping[0], non_wrapping[-1]
    lap_length_m = float(trace.grid[-1]) + GRID_STEP_M
    assert missing.end_m < (present.start_m - APPROACH_M), (
        "test setup needs two events whose approach windows do not overlap"
    )

    gap = span_indices(
        trace.grid, (missing.start_m - APPROACH_M) % lap_length_m, missing.end_m
    )
    other_brake = trace.brake.copy()
    other_brake[gap] = 0.0
    other_lap = _replace(trace, brake=other_brake)
    assert corner_metrics(other_lap, missing).brake_point_m is None, (
        "test setup is wrong: the candidate must not brake for the missing event"
    )
    assert corner_metrics(other_lap, present).brake_point_m is not None, (
        "test setup is wrong: the candidate must still brake for the control event"
    )

    made = best_templates(trace, [("other lap", other_lap)], model.corners)

    assert len(made) == len(events)
    assert {t.corner.index for t in made} == {e.index for e in events}

    by_index = {t.corner.index: t for t in made}
    assert by_index[missing.index].source == "", (
        "the event the candidate could not supply must come from the "
        "reference fallback"
    )
    assert by_index[present.index].source == "other lap", (
        "an event the candidate can supply must actually come from it - "
        "otherwise this test would pass even if the fallback swallowed "
        "everything"
    )


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
    assert watch.tone_due(750.0, 0.0) is False, "before the mark"
    assert watch.tone_due(805.0, 0.1) is True, "at the mark"
    assert watch.tone_due(850.0, 0.2) is False, "already sounded"
    assert watch.tone_due(900.0, 0.3) is False


def test_the_tone_is_not_due_outside_a_window():
    watch = TemplateWatch([_one_template()], LAP)
    assert watch.tone_due(400.0, 0.0) is False


def test_a_new_lap_arms_everything_again():
    watch = TemplateWatch([_one_template()], LAP)
    watch.showing(750.0, 0.0)
    watch.tone_due(805.0, 0.1)

    watch.reset()
    watch.showing(750.0, 100.0)
    assert watch.tone_due(805.0, 100.1) is True


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
    assert watch.tone_due(5000.0, 0.2) is False, "the far side of the lap"


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
    templates sounds each corner exactly once, in track order - and, the
    assertion this test used to be missing, each tone fires for the corner
    the panel is actually showing at that instant.

    showing() and the tone used to be decided independently: showing()
    picked a display by nearest-window, due_template() scanned for a passed
    brake point on its own, and nothing tied the two answers together. At
    Monza's own T1/T2 - not a constructed case, the first corner of this
    fixture, every lap - the windows overlap enough that they disagreed:
    T2's window opens 68 m before T1's own brake point, so by the time T1's
    brake point passed the panel had already switched to T2, and the tone
    fired into a strip for the wrong corner. Counting and ordering the
    tones, which is all this test used to do, cannot see that: the count
    and the order were both still right, only the *pairing* was wrong. Six
    task reviews and eight fix rounds missed it for exactly that reason.

    Uses ``due_template``/``mark_toned`` rather than ``tone_due`` - the same
    pair ``live.__main__._sound_if_due`` calls - because ``tone_due`` only
    ever answers True/False and this needs to know *which* template was
    found due, to compare it against what ``showing()`` says is on screen
    at the same distance and clock reading.
    """
    model, trace = monza
    made = templates_for(trace, model.corners)
    watch = TemplateWatch(made, float(trace.grid[-1]) + 2.0)

    sounded = []
    for i in range(len(trace.grid)):
        here = float(trace.grid[i])
        now = i * 0.02
        showing = watch.showing(here, now)
        due = watch.due_template(here, now)
        if due is not None:
            watch.mark_toned(due)
            sounded.append(here)
            assert showing is not None and not showing.past_corner, (
                f"the tone for {due.corner.name!r} fired with no fresh "
                f"approach on screen for it"
            )
            assert showing.template.corner.index == due.corner.index, (
                f"the tone fired for {due.corner.name!r} while the panel "
                f"showed {showing.template.corner.name!r}"
            )

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
