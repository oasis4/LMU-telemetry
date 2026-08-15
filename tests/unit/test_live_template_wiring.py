"""The two functions that sit between the sample loop and the panel.

``_show_template`` and ``_sound_if_due`` are where the searchsorted
truncation, the ``buffer.trace()`` ``ValueError`` catch, the entry-delta
index and the two silence gates all live - none of it exercised by
``test_template.py``, which only ever calls ``TemplateWatch`` and
``templates_for`` directly. The overlay is faked, because all it needs to do
here is remember what it was told; the buffer is real and fed real samples,
because the truncation and the interpolation are the behaviour under test.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

import lmu_telemetry.live.__main__ as live_main
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.metrics import APPROACH_M
from lmu_telemetry.live.__main__ import _show_template, _sound_if_due
from lmu_telemetry.live.buffer import LapBuffer, LiveSample
from lmu_telemetry.live.template import Template, TemplateWatch
from lmu_telemetry.live.tone import TONE_LEAD_S

LAP = 6000.0


class _FakeOverlay:
    """Records what it was told, and mirrors just enough of the real
    Overlay's content-slot bookkeeping - see ``Overlay._set_content`` and
    ``Overlay.content`` - for the precedence tests to mean something: which
    of "template" / "finding" / None is current, so a test can tell whether
    a call actually changed anything. The precedence *decision* itself is
    not reimplemented here; it lives in ``_show_template``, which is what
    these tests call.
    """

    def __init__(self) -> None:
        self.shown = None          # (showing, own_brake, own_throttle, entry_delta) | None
        self.hidden_count = 0
        self.finding = None        # (name, sentence) | None
        self.content: "str | None" = None
        self.deltas: "list[float | None]" = []

    def show_delta(self, seconds: "float | None") -> None:
        self.deltas.append(seconds)

    def pump(self) -> None:
        pass

    def show_template(self, showing, own_brake, own_throttle, entry_delta_kmh=None) -> None:
        self.shown = (showing, np.asarray(own_brake), np.asarray(own_throttle), entry_delta_kmh)
        self.content = "template"

    def hide_template(self) -> None:
        self.hidden_count += 1
        self.shown = None
        if self.content == "template":
            self.content = None

    def show_finding(self, name: str, sentence: "str | None") -> None:
        if not sentence:
            if self.content == "finding":
                self.content = None
            self.finding = None
            return
        self.finding = (name, sentence)
        self.content = "finding"


@dataclass
class _FakeWatch:
    """Stands in for CornerWatch: only ``why_silent`` is read by these two
    functions, so only it needs to be real to control."""

    why_silent: "str | None" = None


def _corner_at(start_m: float, end_m: float, index: int = 1) -> Corner:
    return Corner(index=index, name="T1", start_m=start_m,
                  apex_m=(start_m + end_m) / 2, end_m=end_m,
                  radius_m=60.0, heading_deg=90.0, direction="L")


def _template_at(corner_start_m: float = 950.0, corner_end_m: float = 1100.0) -> Template:
    """A window built the way templates_for builds one: APPROACH_M back from
    the corner's own start, at a 2 m step, brake ramping so interpolation is
    checkable rather than trivially constant."""
    corner = _corner_at(corner_start_m, corner_end_m)
    start_m = corner_start_m - APPROACH_M
    length_m = APPROACH_M + (corner_end_m - corner_start_m)
    offsets = np.arange(0.0, length_m + 1.0, 2.0)
    return Template(
        corner=corner, start_m=start_m, length_m=float(offsets[-1]),
        brake_at_m=100.0, entry_at_m=APPROACH_M, entry_speed_kmh=180.0,
        offsets_m=offsets, abs_m=offsets + start_m,
        brake=np.linspace(0.0, 1.0, len(offsets)),
        throttle=np.linspace(1.0, 0.0, len(offsets)),
    )


def _feed(buffer: LapBuffer, distances, speed_kmh: float = 200.0) -> LiveSample:
    """Add one real sample per distance and return the last one added.

    *speed_kmh* matters to the tone: its lead is held in seconds of the
    driver's own travel, so how far before the mark it fires is a function of
    this. Defaulted, because every test written before that existed neither
    knew nor cared.
    """
    last = None
    for i, d in enumerate(distances):
        last = LiveSample(
            distance_m=float(d), time_s=i * 0.02, speed_kmh=speed_kmh,
            throttle=0.4, brake=0.6, steering=0.0,
        )
        buffer.add(last)
    assert last is not None, "fed no distances at all"
    return last


def _rig():
    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeWatch()
    overlay = _FakeOverlay()
    return template, templates, buffer, watch, overlay


# -- the own line stops at the car -------------------------------------------


def test_the_own_line_stops_at_the_car_and_never_runs_past_it():
    template, templates, buffer, watch, overlay = _rig()

    # Drive from the window's own start to partway through it - not to the
    # far edge, so the truncation actually has something to prove.
    partway_m = template.start_m + 150.0
    sample = _feed(buffer, np.arange(template.start_m, partway_m, 2.0))

    _show_template(overlay, templates, buffer, watch, sample, now=0.0)

    assert overlay.shown is not None, "the car is inside the window; something should show"
    showing, own_brake, own_throttle, _entry = overlay.shown
    reached = int(np.searchsorted(template.offsets_m, showing.at_m, side="right"))

    assert len(own_brake) == reached
    assert len(own_throttle) == reached
    # The car has not reached the far edge of the window, so the own line
    # must not either - a full-width line there would be the last sample
    # held flat and drawn as if it were driven.
    assert reached < len(template.offsets_m)
    assert np.allclose(
        own_brake, np.interp(template.abs_m[:reached], buffer.trace().grid, buffer.trace().brake)
    )


# -- too little data ----------------------------------------------------------


def test_a_buffer_with_one_sample_hides_rather_than_raises():
    template, templates, buffer, watch, overlay = _rig()

    # Exactly one sample, and planted at the window's own start so the
    # "was this window watched" guard passes and the test actually reaches
    # buffer.trace() - which needs at least two samples to answer at all.
    sample = _feed(buffer, [template.start_m])

    _show_template(overlay, templates, buffer, watch, sample, now=0.0)

    assert overlay.hidden_count == 1
    assert overlay.shown is None


# -- silenced laps --------------------------------------------------------


def test_a_why_silent_lap_neither_draws_nor_sounds(monkeypatch):
    template, templates, buffer, watch, overlay = _rig()
    watch.why_silent = "this lap used the pit lane"

    # Past the brake mark, so absent the guard both halves would fire.
    sample = _feed(
        buffer, np.arange(template.start_m, template.start_m + template.brake_at_m + 10.0, 2.0)
    )

    _show_template(overlay, templates, buffer, watch, sample, now=0.0)
    assert overlay.hidden_count == 1
    assert overlay.shown is None, "a silenced lap must not draw the strip"

    sounded = []
    monkeypatch.setattr(live_main, "play_brake_tone", lambda: sounded.append(True))
    _sound_if_due(templates, buffer, watch, sample, now=0.0)
    assert sounded == [], "a silenced lap must not sound the tone either"

    # Prove the guard, not a coincidence, suppressed it: since why_silent
    # short-circuits before the tone is committed, the corner is still armed
    # underneath. Clearing the silence and asking again should sound it - if
    # it does not, the first call already consumed it and the assertion
    # above was not testing what it claimed to.
    watch.why_silent = None
    _sound_if_due(templates, buffer, watch, sample, now=0.0)
    assert sounded == [True], "the same brake point should still be armed once the lap is usable"


def test_a_window_that_was_never_watched_does_not_sound_either(monkeypatch):
    """_show_template already hides the strip for a window whose approach
    began before buffer.started_m - the tone must agree, not sound for a
    window whose strip is correctly withheld."""
    template, templates, buffer, watch, _overlay = _rig()

    # Same setup as test_a_window_opened_before_started_m_is_not_drawn: the
    # overlay attached mid-approach, past the brake mark.
    sample = _feed(
        buffer, np.arange(template.corner.start_m, template.corner.start_m + 100.0, 2.0)
    )
    assert not live_main._window_was_watched(template, buffer), "test setup is wrong"

    sounded = []
    monkeypatch.setattr(live_main, "play_brake_tone", lambda: sounded.append(True))
    _sound_if_due(templates, buffer, watch, sample, now=0.0)
    assert sounded == [], "a window whose strip is hidden must not sound its tone"

    # Prove it is still armed, not consumed: a fresh lap that does watch the
    # window from its own start should still sound the same brake point.
    templates.reset()
    fresh_buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    fresh_sample = _feed(
        fresh_buffer,
        np.arange(template.start_m, template.start_m + template.brake_at_m + 10.0, 2.0),
    )
    _sound_if_due(templates, fresh_buffer, watch, fresh_sample, now=0.0)
    assert sounded == [True], "the same brake point should still be armed next lap"


# -- the pit-lane race --------------------------------------------------------


class _FakeCornerWatch:
    """Stands in for CornerWatch inside _drive: only reset(), why_silent,
    mark_unusable() and advance() are called on it there, and none of them
    need real corner measurement for this test."""

    def __init__(self) -> None:
        self.why_silent: "str | None" = None

    def reset(self) -> None:
        self.why_silent = None

    def mark_unusable(self, because: str) -> None:
        if self.why_silent is None:
            self.why_silent = because

    def advance(self, buffer) -> list:
        return []


def test_the_pit_lane_gate_is_set_before_the_tone_can_fire(monkeypatch):
    """The race this closes: on the single sample that first reports
    in_pits, watch.why_silent must already be set by the time
    _sound_if_due looks at it - not on the frame after."""
    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeCornerWatch()

    sounded = []
    monkeypatch.setattr(live_main, "play_brake_tone", lambda: sounded.append(True))

    # First sample: on track, at the window's own start, so the window is
    # watched from its own start and only the pit-lane gate is left to
    # prove. Second: past the brake mark, and the first sample this lap to
    # report in_pits - the exact frame the race was about.
    on_track = LiveSample(
        distance_m=template.start_m, time_s=0.0, speed_kmh=200.0,
        throttle=0.0, brake=0.0, steering=0.0, in_pits=False,
    )
    into_the_pits = LiveSample(
        distance_m=template.start_m + template.brake_at_m + 10.0, time_s=1.0,
        speed_kmh=80.0, throttle=0.0, brake=0.3, steering=0.0, in_pits=True,
    )
    source = [(on_track, 1), (into_the_pits, 1)]

    live_main._drive(source, buffer, watch, templates, None, None, 0.0, None)

    assert watch.why_silent is not None, "test setup is wrong"
    assert sounded == [], "the first in-pits sample must not sound the tone"


def test_the_delta_stops_counting_on_a_lap_that_used_the_pit_lane(monkeypatch):
    """The strip and the sentences already go quiet on an out lap. The delta
    did not, so the one number left on screen was the only one that meant
    nothing - counting a pit-lane crawl against a flying reference. The
    driver reported reading it and being told, correctly, that it was an out
    lap; the tool knew, and went on showing the number anyway.

    The clock is driven by hand because _drive redraws at REDRAW_HZ: left to
    the real one, two samples fed back to back land inside a single redraw
    window and the second never draws, so the test would pass on the first
    sample's delta while proving nothing about the second.
    """
    ticks = iter([100.0, 101.0, 102.0])
    monkeypatch.setattr(live_main.time, "perf_counter", lambda: next(ticks))

    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeCornerWatch()
    overlay = _FakeOverlay()

    grid = np.arange(0.0, LAP, 2.0)
    reference = SimpleNamespace(grid=grid, time_s=grid / 50.0)

    on_track = LiveSample(
        distance_m=template.start_m, time_s=10.0, speed_kmh=200.0,
        throttle=1.0, brake=0.0, steering=0.0, in_pits=False,
    )
    into_the_pits = LiveSample(
        distance_m=template.start_m + 40.0, time_s=11.0, speed_kmh=60.0,
        throttle=0.0, brake=0.3, steering=0.0, in_pits=True,
    )

    live_main._drive(
        [(on_track, 1), (into_the_pits, 1)],
        buffer, watch, templates, reference, overlay, 0.0, None,
    )

    assert watch.why_silent is not None, "test setup is wrong"
    assert overlay.deltas, "the panel should have been drawn at all"
    assert overlay.deltas[0] is not None, "an on-track lap still gets its delta"
    assert overlay.deltas[-1] is None, (
        "the delta must go blank once the lap is known to be unusable"
    )


# -- precedence between a template's hold and a sentence --------------------
#
# A corner's template window ends at corner.end_m - the same threshold
# CornerWatch.advance uses to complete the corner - so the held Showing for
# a corner (past_corner=True, up to TEMPLATE_HOLD_S) is what the very next
# redraw sees after show_finding puts that same corner's sentence up. That
# is the sequence these two tests drive directly, rather than through
# _widget_order alone: _widget_order takes no history, so a test built only
# on it cannot see an interleaving bug like this one.


def test_a_held_showing_does_not_evict_a_sentence_just_shown_for_it():
    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeWatch()
    overlay = _FakeOverlay()

    # Drive through the window so it is recorded as having been inside it -
    # TemplateWatch._last_inside - at t=10.0.
    inside_m = template.start_m + template.length_m - 2.0
    sample = _feed(buffer, np.arange(template.start_m, inside_m + 2.0, 2.0))
    templates.showing(sample.distance_m, now=10.0)

    # The corner has just completed: watch.advance() would yield a finding
    # here, and _drive calls overlay.show_finding with it.
    overlay.show_finding("T1", "You can brake later here")
    assert overlay.content == "finding", "test setup is wrong"

    # The very next redraw, well inside TEMPLATE_HOLD_S (1.5 s): the car has
    # moved past the window's end, so templates.showing() now returns the
    # held Showing for the SAME corner.
    past_m = template.start_m + template.length_m + 20.0
    past_sample = _feed(buffer, np.arange(inside_m + 2.0, past_m, 2.0))
    _show_template(overlay, templates, buffer, watch, past_sample, now=10.05)

    assert overlay.content == "finding", (
        "the held showing must not evict a sentence just shown for the same corner"
    )
    assert overlay.finding == ("T1", "You can brake later here")


def test_a_freshly_armed_window_does_replace_a_sentence():
    """The other direction: a fresh approach (past_corner=False) always
    takes the slot, sentence or no sentence - otherwise an eleven-second
    sentence would swallow the next corner's strip."""
    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeWatch()
    overlay = _FakeOverlay()

    overlay.show_finding("T0", "Level with the reference here")
    assert overlay.content == "finding", "test setup is wrong"

    # A fresh approach: the car is inside the window, not past its end, so
    # showing.past_corner is False.
    sample = _feed(buffer, np.arange(template.start_m, template.start_m + 50.0, 2.0))
    _show_template(overlay, templates, buffer, watch, sample, now=0.0)

    assert overlay.content == "template", "a freshly armed window must win the slot"
    assert overlay.shown is not None


# -- windows opened before the buffer was watching ---------------------------


def test_a_window_opened_before_started_m_is_not_drawn():
    template, templates, buffer, watch, overlay = _rig()

    # The overlay started after the window's approach began: the first
    # sample lands at the corner's own start, not the window's.
    assert template.corner.start_m > template.start_m
    sample = _feed(buffer, np.arange(template.corner.start_m, template.corner.start_m + 100.0, 2.0))

    _show_template(overlay, templates, buffer, watch, sample, now=0.0)

    assert overlay.hidden_count == 1
    assert overlay.shown is None, (
        "the window's opening metres were never recorded; drawing anyway "
        "would be np.interp inventing them"
    )


def test_a_window_watched_from_its_own_start_is_drawn():
    """The companion case: starting the buffer exactly where the window
    starts is watched, and must not be swept up by the same guard."""
    template, templates, buffer, watch, overlay = _rig()

    sample = _feed(buffer, np.arange(template.start_m, template.start_m + 100.0, 2.0))

    _show_template(overlay, templates, buffer, watch, sample, now=0.0)

    assert overlay.shown is not None
    assert overlay.hidden_count == 0


# -- the entry delta --------------------------------------------------------


def test_the_entry_delta_appears_only_after_the_corners_start_is_passed():
    template, templates, buffer, watch, overlay = _rig()

    # Short of the corner's own start (window offset == entry_at_m): the
    # entry speed cannot be known yet.
    before = _feed(
        buffer, np.arange(template.start_m, template.corner.start_m - 10.0, 2.0)
    )
    _show_template(overlay, templates, buffer, watch, before, now=0.0)
    assert overlay.shown is not None
    _showing, _brake, _throttle, entry_delta = overlay.shown
    assert entry_delta is None

    # Past it: the entry speed is now knowable.
    after = _feed(
        buffer, np.arange(template.corner.start_m - 8.0, template.corner.start_m + 20.0, 2.0)
    )
    _show_template(overlay, templates, buffer, watch, after, now=0.0)
    assert overlay.shown is not None
    _showing2, _brake2, _throttle2, entry_delta2 = overlay.shown
    assert entry_delta2 is not None
    assert isinstance(entry_delta2, float)


def test_the_tone_sounds_before_the_mark_not_on_it(monkeypatch):
    """The driver reported the beep arriving too late, and it was: it fired
    at the mark, and simple auditory reaction time plus a throttle-to-brake
    move is 200-250 ms, so the pedal went down 15-20 m past it at speed.

    Asserted as a distance before the mark, from the driver's own speed -
    that is what TONE_LEAD_S buys and what a fixed metre count would not.
    """
    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeWatch()

    sounded = []
    monkeypatch.setattr(live_main, "play_brake_tone", lambda: sounded.append(True))

    speed_kmh = 250.0
    lead_m = TONE_LEAD_S * speed_kmh / 3.6
    assert lead_m > 4.0, "test setup: the lead must be worth measuring"

    # Just before the lead point: still nothing.
    early = template.start_m + template.brake_at_m - lead_m - 6.0
    sample = _feed(buffer, np.arange(template.start_m, early + 2.0, 2.0),
                   speed_kmh=speed_kmh)
    _sound_if_due(templates, buffer, watch, sample, now=0.0)
    assert sounded == [], "the tone must not sound a whole lead early"

    # Past it, but still short of the mark itself.
    at_lead = template.start_m + template.brake_at_m - lead_m + 2.0
    sample = _feed(buffer, np.arange(early + 2.0, at_lead + 2.0, 2.0),
                   speed_kmh=speed_kmh)
    assert sample.distance_m < template.start_m + template.brake_at_m, (
        "test setup: this sample must still be short of the mark"
    )
    _sound_if_due(templates, buffer, watch, sample, now=0.0)
    assert sounded == [True], "the tone should already have sounded by here"


def test_the_lead_is_measured_in_time_so_a_slower_car_gets_a_shorter_one(monkeypatch):
    """A fixed distance would be the wrong amount of warning at every speed
    but one - the same reason the window itself is timed."""
    def fires_at(speed_kmh: float) -> float:
        """How far before the mark the tone sounds, at a steady *speed_kmh*."""
        template = _template_at()
        templates = TemplateWatch([template], LAP)
        buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
        watch = _FakeWatch()
        sounded: "list[bool]" = []
        monkeypatch.setattr(
            live_main, "play_brake_tone", lambda: sounded.append(True)
        )
        mark_m = template.start_m + template.brake_at_m
        for upto in np.arange(template.start_m, mark_m + 2.0, 2.0):
            sample = _feed(buffer, [upto], speed_kmh=speed_kmh)
            _sound_if_due(templates, buffer, watch, sample, now=0.0)
            if sounded:
                return mark_m - float(upto)
        raise AssertionError(f"the tone never sounded at {speed_kmh} km/h")

    fast, slow = fires_at(280.0), fires_at(90.0)
    assert fast > slow, (
        f"the faster car should be warned from further out, got {fast:.0f} m "
        f"at 280 km/h against {slow:.0f} m at 90 km/h"
    )
    # Both should be about TONE_LEAD_S of their own travel, within the 2 m
    # the grid can resolve.
    for speed_kmh, got in ((280.0, fast), (90.0, slow)):
        assert got == pytest.approx(TONE_LEAD_S * speed_kmh / 3.6, abs=2.5)


# -- the circuit changing underneath the reference ----------------------------
#
# The reference is chosen once, before the session, from a single read of the
# game. That read can be of the *previous* session: the mapping holds the last
# circuit's scoring until a new one loads. A driver reported being coached
# against Daytona for a whole run on another track, having driven Daytona
# before it - and the run's own output carried the contradiction that proves
# it, "5 braking events from 0 laps", printed without comment.


class _FakeGame:
    """Reports one circuit, then another from the nth call onward."""

    def __init__(self, first, then=None, after=0, length_m=5734.0,
                 then_length_m=5776.0):
        self._first, self._then, self._left = first, then, after
        self._length, self._then_length = length_m, then_length_m
        self.calls = 0

    def _switched(self) -> bool:
        return self._then is not None and self.calls > self._left

    def track_name(self) -> str:
        self.calls += 1
        return self._then if self._switched() else self._first

    def track_length_m(self) -> float:
        return self._then_length if self._switched() else self._length


DAYTONA = "Daytona International Speedway Road Course"


def test_a_circuit_that_never_changes_is_never_complained_about():
    game = _FakeGame(DAYTONA)
    assert live_main._circuit_changed(game, DAYTONA, 5734.0) is None


def test_the_game_going_quiet_is_not_a_different_circuit():
    """Between sessions the mapping can report nothing at all. Treating that
    as a change would stop the tool every time the driver opened a menu."""
    assert live_main._circuit_changed(_FakeGame(""), DAYTONA, 5734.0) is None


def test_another_circuit_is_reported():
    game = _FakeGame(DAYTONA, then="Autodromo Nazionale Monza", after=0)
    assert live_main._circuit_changed(game, DAYTONA, 5734.0) == (
        "Autodromo Nazionale Monza"
    )


def test_another_layout_of_the_same_circuit_is_reported_too():
    """One name, two courses - the fault LAYOUT_TOLERANCE_M exists for. The
    name alone would say nothing had changed."""
    game = _FakeGame("Autodromo Nazionale Monza", then="Autodromo Nazionale Monza",
                     after=0, length_m=5776.0, then_length_m=5741.0)
    assert live_main._circuit_changed(
        game, "Autodromo Nazionale Monza", 5776.0
    ) is not None


def test_driving_stops_when_the_circuit_turns_out_to_be_another_one(monkeypatch):
    """The whole point: coaching against the wrong circuit is worse than not
    coaching, so the loop gives up rather than going on."""
    ticks = iter([100.0 + i for i in range(20)])
    monkeypatch.setattr(live_main.time, "perf_counter", lambda: next(ticks))

    template = _template_at()
    templates = TemplateWatch([template], LAP)
    buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    watch = _FakeCornerWatch()
    overlay = _FakeOverlay()
    grid = np.arange(0.0, LAP, 2.0)
    reference = SimpleNamespace(grid=grid, time_s=grid / 50.0)
    game = _FakeGame(DAYTONA, then="Autodromo Nazionale Monza", after=1)

    # Counted as they are pulled, rather than inferred from how much the
    # overlay was told: the redraw is throttled, so a delta count would say
    # as much about the clock as about whether the loop gave up.
    taken = []

    def feed():
        for d in (700.0, 720.0, 740.0, 760.0):
            taken.append(d)
            yield LiveSample(
                distance_m=d, time_s=d / 50.0, speed_kmh=180.0,
                throttle=1.0, brake=0.0, steering=0.0, in_pits=False,
            ), 1

    live_main._drive(
        feed(), buffer, watch, templates, reference, overlay, 0.0, None,
        live=game, expect_track=DAYTONA, expect_length_m=5734.0,
    )

    assert game.calls >= 2, "the circuit should be re-read while driving"
    assert len(taken) < 4, (
        f"the loop worked through all {len(taken)} samples instead of giving "
        f"up when the circuit changed"
    )


def test_an_explicit_reference_is_never_second_guessed():
    """--reference means the driver named a lap and meant it. Nothing here
    re-decides whether it belongs to the circuit they are on."""
    assert live_main._circuit_changed(None, DAYTONA, 5734.0) is None
