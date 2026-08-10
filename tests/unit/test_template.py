"""The window a braking template is drawn over.

Everything here works in offsets into that window rather than in lap
distances. A window crossing the start/finish line is two ranges in lap
distance, and every consumer would have to know it; as an offset it is one
range that starts at zero.
"""

import numpy as np
import pytest

from lmu_telemetry.core.metrics import APPROACH_M
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.template import Template, offset_into, templates_for


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
