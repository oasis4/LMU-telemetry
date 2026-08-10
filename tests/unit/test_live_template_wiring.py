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

import numpy as np
import pytest

import lmu_telemetry.live.__main__ as live_main
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.metrics import APPROACH_M
from lmu_telemetry.live.__main__ import _show_template, _sound_if_due
from lmu_telemetry.live.buffer import LapBuffer, LiveSample
from lmu_telemetry.live.template import Template, TemplateWatch

LAP = 6000.0


class _FakeOverlay:
    """Records what it was told, and nothing more."""

    def __init__(self) -> None:
        self.shown = None          # (showing, own_brake, own_throttle, entry_delta) | None
        self.hidden_count = 0

    def show_template(self, showing, own_brake, own_throttle, entry_delta_kmh=None) -> None:
        self.shown = (showing, np.asarray(own_brake), np.asarray(own_throttle), entry_delta_kmh)

    def hide_template(self) -> None:
        self.hidden_count += 1
        self.shown = None


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


def _feed(buffer: LapBuffer, distances) -> LiveSample:
    """Add one real sample per distance and return the last one added."""
    last = None
    for i, d in enumerate(distances):
        last = LiveSample(
            distance_m=float(d), time_s=i * 0.02, speed_kmh=200.0,
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
    _sound_if_due(templates, buffer, watch, sample)
    assert sounded == [], "a silenced lap must not sound the tone either"

    # Prove the guard, not a coincidence, suppressed it: since why_silent
    # short-circuits before the tone is committed, the corner is still armed
    # underneath. Clearing the silence and asking again should sound it - if
    # it does not, the first call already consumed it and the assertion
    # above was not testing what it claimed to.
    watch.why_silent = None
    _sound_if_due(templates, buffer, watch, sample)
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
    _sound_if_due(templates, buffer, watch, sample)
    assert sounded == [], "a window whose strip is hidden must not sound its tone"

    # Prove it is still armed, not consumed: a fresh lap that does watch the
    # window from its own start should still sound the same brake point.
    templates.reset()
    fresh_buffer = LapBuffer(np.arange(0.0, LAP, 2.0))
    fresh_sample = _feed(
        fresh_buffer,
        np.arange(template.start_m, template.start_m + template.brake_at_m + 10.0, 2.0),
    )
    _sound_if_due(templates, fresh_buffer, watch, fresh_sample)
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
