# Live brake template — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the reference lap's brake and throttle traces as a template under the delta as each braked corner arrives, with a tone at the reference brake point.

**Architecture:** A new `live/template.py` holds the arming logic as plain values — which corner is showing, where in its window the car is, whether the tone is due — and is testable without a window or a game. `live/overlay.py` gains a `tk.Canvas` that draws whatever it is handed. `live/tone.py` plays the tone without blocking. `live/__main__.py` wires them. This is the split `watch.py` and the panel already keep: behaviour stays testable, drawing stays dumb.

**Tech Stack:** Python 3.13, numpy, tkinter, winsound, pytest.

## Global Constraints

- **The x axis is distance, never time.** Measured on two Monza laps 2.700 s apart, the driver brakes within 2 m of the reference at Ascari having lost 1.86 s by then. Against time the template would sit ~130 m out there.
- **The vertical scale is fixed 0.0 to 1.0 and never auto-scaled.** Auto-scaling draws a 60 % brake application at the same height as a 90 % one.
- **The brake point is never corrected for entry speed.** The difference is displayed instead. Correcting means a braking model this corpus cannot check.
- **The driver's line comes from `buffer.trace()`**, the same interpolation the corner figures use — never from raw samples.
- Window span is `corner.start_m - APPROACH_M` to `corner.end_m`. `APPROACH_M` is `250.0`, already in `core.metrics`. Do not introduce a second constant.
- Only corners whose **reference** `brake_point_m` is not None are armed.
- Nothing is shown on a lap where `CornerWatch.why_silent` is set.
- Run tests with `.venv/Scripts/python.exe -m pytest`. Commit after every task. Branch `feature/brake-shape-coaching`.

## Existing interfaces this builds on

```python
# core.metrics
APPROACH_M = 250.0
def corner_metrics(trace: LapTrace, corner: Corner) -> CornerMetrics
# CornerMetrics fields used here: brake_point_m: float | None, entry_speed_kmh: float

# core.trace.LapTrace fields: lap, grid, time_s, speed_kmh, throttle, brake, steering
# core.geometry: GRID_STEP_M = 2.0

# live.buffer.LapBuffer: .trace() -> LapTrace (raises below 2 samples),
#                        .reached_m, .started_m, .reset(), .add(sample)
# live.watch.CornerWatch: .why_silent -> str | None, .mark_unusable(str), .reset()

# live.overlay.Overlay: .show_delta(float|None), .show_finding(str, str|None),
#                       ._relayout(), .pump(), .close(), .monitor
#   widgets: self.root, self.rail, self.delta, self.corner, self.sentence
#   self._expires_at, self._tip_pad, self._width, and a scale factor `k`
#   computed in __init__ as (screen_h / 1080.0) * scale
```

## File structure

- Create `lmu_telemetry/live/template.py` — window geometry and arming. No tkinter, no game.
- Create `lmu_telemetry/live/tone.py` — the sound, asynchronous, never raising.
- Modify `lmu_telemetry/live/overlay.py` — a canvas, `show_template`, `hide_template`.
- Modify `lmu_telemetry/live/__main__.py` — build templates, feed the canvas, play the tone.
- Create `tests/unit/test_template.py`, `tests/unit/test_tone.py`.
- Modify `tests/unit/test_overlay_placement.py` — nothing; the canvas has its own file.
- Create `tests/unit/test_overlay_template.py`.

---

### Task 1: The window geometry

**Files:**
- Create: `lmu_telemetry/live/template.py`
- Test: `tests/unit/test_template.py`

**Interfaces:**
- Consumes: `core.metrics.APPROACH_M`, `core.metrics.corner_metrics`, `core.geometry.GRID_STEP_M`, `core.trace.LapTrace`, `core.corners.Corner`.
- Produces:
  - `offset_into(start_m: float, distance_m: float, lap_length_m: float) -> float`
  - `Template` frozen dataclass with fields `corner`, `start_m`, `length_m`, `brake_at_m`, `entry_at_m`, `entry_speed_kmh`, `offsets_m` (np.ndarray), `abs_m` (np.ndarray), `brake` (np.ndarray), `throttle` (np.ndarray)
  - `templates_for(reference: LapTrace, corners) -> list[Template]`

Everything downstream works in **offsets into the window** rather than in lap distances. A window that crosses the start/finish line is otherwise a pair of ranges that every consumer has to special-case, and the tone comparison `distance >= brake_point` is simply wrong there.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_template.py -q`
Expected: collection error — `No module named 'lmu_telemetry.live.template'`.

- [ ] **Step 3: Write the module**

```python
"""The window a braking template is drawn over, and what fills it.

Everything here is an offset into that window, not a lap distance. A window
that crosses the start/finish line is two ranges in lap distance, and every
consumer - the drawing, the tone, the driver's own line - would have to know
it. As an offset it is one range that starts at zero and only increases.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.corners import Corner
from ..core.geometry import GRID_STEP_M, span_indices
from ..core.metrics import APPROACH_M, corner_metrics
from ..core.trace import LapTrace


def offset_into(start_m: float, distance_m: float, lap_length_m: float) -> float:
    """How far past *start_m* the car is, measured forward round the lap."""
    return float((distance_m - start_m) % lap_length_m)


@dataclass(frozen=True)
class Template:
    """One corner's approach and braking zone, taken from the reference lap."""

    corner: Corner
    #: Where the window begins, as a lap distance.
    start_m: float
    length_m: float
    #: Offsets into the window, not lap distances. See the module docstring.
    brake_at_m: float
    entry_at_m: float
    entry_speed_kmh: float
    offsets_m: np.ndarray
    #: The same points as lap distances, so the driver's own trace can be
    #: sampled at exactly the places the grey line was.
    abs_m: np.ndarray
    brake: np.ndarray
    throttle: np.ndarray


def templates_for(reference: LapTrace, corners) -> "list[Template]":
    """One template per corner the reference braked for.

    A corner taken flat is skipped rather than drawn with no mark on it: it
    has nothing to teach here, and at Monza it would mean eleven strips a lap
    where seven are useful.
    """
    lap_length_m = float(reference.grid[-1]) + GRID_STEP_M
    made: "list[Template]" = []
    for corner in corners:
        figures = corner_metrics(reference, corner)
        if figures.brake_point_m is None:
            continue
        start_m = (corner.start_m - APPROACH_M) % lap_length_m
        window = span_indices(reference.grid, start_m, corner.end_m)
        if len(window) < 2:
            continue
        abs_m = reference.grid[window]
        offsets = np.array(
            [offset_into(start_m, float(d), lap_length_m) for d in abs_m]
        )
        made.append(Template(
            corner=corner,
            start_m=start_m,
            length_m=float(offsets[-1]),
            brake_at_m=offset_into(start_m, figures.brake_point_m, lap_length_m),
            entry_at_m=offset_into(start_m, corner.start_m, lap_length_m),
            entry_speed_kmh=figures.entry_speed_kmh,
            offsets_m=offsets,
            abs_m=abs_m,
            brake=reference.brake[window],
            throttle=reference.throttle[window],
        ))
    return made
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_template.py -q`
Expected: PASS. If `test_the_offsets_only_ever_increase` fails, the window wrapped and `offset_into` was given the wrong `lap_length_m` — check `reference.grid[-1] + GRID_STEP_M`, not `grid[-1]`.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live/template.py tests/unit/test_template.py && git commit -m "Measure the template window in offsets, so a wrapping one is still one range"
```

---

### Task 2: Arming, holding, and the tone falling due

**Files:**
- Modify: `lmu_telemetry/live/template.py`
- Test: `tests/unit/test_template.py`

**Interfaces:**
- Consumes: `Template`, `offset_into` from Task 1.
- Produces:
  - `TEMPLATE_HOLD_S = 1.5`
  - `Showing` frozen dataclass: `template: Template`, `at_m: float`, `past_corner: bool`
  - `TemplateWatch(templates: list[Template], lap_length_m: float)` with
    `showing(distance_m: float, now: float) -> Showing | None`,
    `tone_due(distance_m: float) -> bool`,
    `reset() -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_template.py`:

```python
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


def _corner_at(start_m, end_m):
    from lmu_telemetry.core.corners import Corner

    return Corner(index=1, name="T1", start_m=start_m,
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_template.py -q -k "arming or tone or window or hold or shows or lap"`
Expected: `ImportError: cannot import name 'TemplateWatch'`.

- [ ] **Step 3: Write it**

Append to `lmu_telemetry/live/template.py`:

```python
#: How long a template stays up after its corner is behind the car. During the
#: corner the driver has no attention to spare; afterwards is when they can
#: look at whether it fitted.
TEMPLATE_HOLD_S = 1.5


@dataclass(frozen=True)
class Showing:
    """The template on screen now, and where in it the car is."""

    template: Template
    at_m: float
    #: True once the corner is behind the car and this is the hold.
    past_corner: bool


class TemplateWatch:
    """Which template is up, and whether the tone has fallen due.

    Kept apart from the drawing for the same reason CornerWatch is: this is
    the part with behaviour in it, and it should answer without a window or a
    running game.
    """

    def __init__(self, templates, lap_length_m: float) -> None:
        self.templates = list(templates)
        self.lap_length_m = float(lap_length_m)
        self._toned: set[int] = set()
        self._left_at: "dict[int, float]" = {}

    def reset(self) -> None:
        """A new lap. Every template arms again."""
        self._toned.clear()
        self._left_at.clear()

    def _inside(self, template: Template, distance_m: float) -> "float | None":
        at = offset_into(template.start_m, distance_m, self.lap_length_m)
        return at if at <= template.length_m else None

    def showing(self, distance_m: float, now: float) -> "Showing | None":
        """The template to draw, or None.

        Where two windows overlap - Ascari's corners are close enough that
        they do - the one whose window started most recently wins, because
        that is the corner being driven into rather than the one just left.
        """
        best: "Showing | None" = None
        best_at = None
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None:
                continue
            if best_at is None or at < best_at:
                best_at, best = at, Showing(template, at, past_corner=False)

        if best is not None:
            self._left_at.pop(best.template.corner.index, None)
            return best

        # Outside every window. Hold the one just left, briefly.
        for template in self.templates:
            index = template.corner.index
            left = self._left_at.get(index)
            if left is not None and now - left <= TEMPLATE_HOLD_S:
                return Showing(template, template.length_m, past_corner=True)
        return None

    def tone_due(self, distance_m: float) -> bool:
        """True exactly once per corner, as the reference brake point passes."""
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None or at < template.brake_at_m:
                continue
            index = template.corner.index
            if index in self._toned:
                continue
            self._toned.add(index)
            return True
        return False
```

The hold needs `_left_at` filled when a window is left. Add to `showing`, immediately before `return best` is skipped — that is, record the departure when a template that was inside is no longer inside. Replace the loop above with this exact body:

```python
    def showing(self, distance_m: float, now: float) -> "Showing | None":
        best: "Showing | None" = None
        best_at = None
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None:
                if template.corner.index in self._seen:
                    self._left_at.setdefault(template.corner.index, now)
                continue
            self._seen.add(template.corner.index)
            if best_at is None or at < best_at:
                best_at, best = at, Showing(template, at, past_corner=False)

        if best is not None:
            return best

        for template in self.templates:
            left = self._left_at.get(template.corner.index)
            if left is not None and now - left <= TEMPLATE_HOLD_S:
                return Showing(template, template.length_m, past_corner=True)
        return None
```

and add `self._seen: set[int] = set()` to `__init__` and `self._seen.clear()` to `reset()`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_template.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live/template.py tests/unit/test_template.py && git commit -m "Arm one template at a time, and hold it long enough to be read"
```

---

### Task 3: The tone

**Files:**
- Create: `lmu_telemetry/live/tone.py`
- Test: `tests/unit/test_tone.py`

**Interfaces:**
- Produces: `play_brake_tone() -> None`, `TONE_HZ = 880`, `TONE_MS = 70`

- [ ] **Step 1: Write the failing tests**

```python
"""The tone at the reference brake point.

The only thing worth asserting without a sound card is that it does not do
the two things that would matter: block the reader, or raise.
"""

import time

from lmu_telemetry.live.tone import TONE_MS, play_brake_tone


def test_the_tone_does_not_block_the_reader():
    """winsound.Beep blocks. Eighty milliseconds of it inside a 50 Hz read
    loop is four lost samples in the middle of a braking zone - the one place
    the reader must not stall."""
    started = time.perf_counter()
    for _ in range(3):
        play_brake_tone()
    took = time.perf_counter() - started
    assert took < (TONE_MS / 1000.0), f"blocked for {took:.3f} s"


def test_the_tone_never_raises():
    """A machine with no sound device is a machine that should still coach."""
    play_brake_tone()
    play_brake_tone()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_tone.py -q`
Expected: collection error, `No module named 'lmu_telemetry.live.tone'`.

- [ ] **Step 3: Write it**

```python
"""A short tone, played without making the caller wait for it.

``winsound.Beep`` blocks for its whole duration. Called from the 50 Hz read
loop that is at that moment inside a braking zone, seventy milliseconds of
blocking is three or four samples lost from exactly the stretch the tone is
drawing attention to.

So it goes on a daemon thread. A machine with no sound device, or one that is
not Windows, gets silence rather than an exception: a driver whose speakers
are off should still be coached.
"""

from __future__ import annotations

import threading

#: A pitch that carries over engine noise without being shrill, and short
#: enough not to still be sounding at the point it is telling the driver about.
TONE_HZ = 880
TONE_MS = 70


def _sound() -> None:
    try:
        import winsound

        winsound.Beep(TONE_HZ, TONE_MS)
    except Exception:
        pass


def play_brake_tone() -> None:
    """Sound the brake mark. Returns immediately."""
    threading.Thread(target=_sound, daemon=True).start()
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_tone.py -q`
Expected: PASS. You may hear three beeps.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live/tone.py tests/unit/test_tone.py && git commit -m "Sound the brake mark without stalling the reader that found it"
```

---

### Task 4: The strips

**Files:**
- Modify: `lmu_telemetry/live/overlay.py`
- Test: `tests/unit/test_overlay_template.py`

**Interfaces:**
- Consumes: `Showing` from Task 2.
- Produces on `Overlay`:
  - `show_template(showing, own_brake: np.ndarray, own_throttle: np.ndarray, entry_delta_kmh: float | None) -> None`
  - `hide_template() -> None`
  - static `_strip_points(offsets_m, values, length_m, width, top, height) -> list[float]`

`_strip_points` is static and pure so the arithmetic that decides whether the two lines land on the same metres can be tested without a window.

- [ ] **Step 1: Write the failing tests**

```python
"""Turning a template into pixels.

The whole value of the strip is that the grey line and the driver's line sit
over the same metres. That is arithmetic, and it is tested here without a
window - `_strip_points` is static for exactly that reason.
"""

import numpy as np
import pytest

from lmu_telemetry.live.overlay import Overlay


def _points(offsets, values, length_m=400.0, width=600, top=0, height=40):
    flat = Overlay._strip_points(
        np.asarray(offsets, dtype=float), np.asarray(values, dtype=float),
        length_m, width, top, height,
    )
    return list(zip(flat[0::2], flat[1::2]))


def test_the_window_is_stretched_across_the_full_width():
    got = _points([0.0, 200.0, 400.0], [0.0, 0.0, 0.0], length_m=400.0, width=600)
    assert got[0][0] == pytest.approx(0.0)
    assert got[-1][0] == pytest.approx(600.0)
    assert got[1][0] == pytest.approx(300.0)


def test_the_two_lines_land_on_the_same_metres():
    """The property the strip exists for. A reference sampled every 2 m and a
    driver's line stopping partway must agree wherever both have a point."""
    reference = _points(np.arange(0.0, 401.0, 2.0), np.zeros(201))
    own = _points(np.arange(0.0, 201.0, 2.0), np.zeros(101))
    for at in range(101):
        assert own[at][0] == pytest.approx(reference[at][0])


def test_full_brake_reaches_the_top_of_its_strip():
    got = _points([0.0, 400.0], [1.0, 1.0], top=10, height=40)
    assert all(y == pytest.approx(10.0) for _x, y in got)


def test_no_brake_sits_on_the_bottom_of_its_strip():
    got = _points([0.0, 400.0], [0.0, 0.0], top=10, height=40)
    assert all(y == pytest.approx(50.0) for _x, y in got)


def test_the_scale_is_fixed_and_not_stretched_to_the_data():
    """A 60 % application and a 90 % one must not be drawn the same height.
    Auto-scaling is what would make the template pretty and wrong."""
    soft = _points([0.0, 400.0], [0.6, 0.6], top=0, height=100)
    hard = _points([0.0, 400.0], [0.9, 0.9], top=0, height=100)
    assert soft[0][1] == pytest.approx(40.0)
    assert hard[0][1] == pytest.approx(10.0)


def test_a_value_outside_the_scale_is_clamped_not_drawn_off_the_strip():
    got = _points([0.0, 400.0], [1.4, -0.3], top=0, height=40)
    assert got[0][1] == pytest.approx(0.0)
    assert got[1][1] == pytest.approx(40.0)


def test_a_single_point_still_produces_a_drawable_line():
    """tkinter refuses a line with one point; the driver has exactly one
    sample for the first frame of every window."""
    got = _points([0.0], [0.5])
    assert len(got) >= 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_overlay_template.py -q`
Expected: `AttributeError: type object 'Overlay' has no attribute '_strip_points'`.

- [ ] **Step 3: Add the geometry and the canvas**

In `lmu_telemetry/live/overlay.py`, add near the other module constants:

```python
#: Height of one pedal strip at the design scale, and the gap between the two.
_STRIP_H = 34.0
_STRIP_GAP = 6.0
#: The reference, and the driver's own lines over it.
GHOST = "#4a4a58"
OWN_BRAKE = "#ff6b52"
OWN_THROTTLE = "#43d08a"
MARK = "#8a8aa0"
```

Add this static method to `Overlay`:

```python
    @staticmethod
    def _strip_points(offsets_m, values, length_m, width, top, height):
        """One polyline, flattened to x1, y1, x2, y2, ... for tkinter.

        The x axis is the window in metres and nothing else. That is what puts
        the grey line and the driver's line on the same metres, which is the
        only reason the strip is worth looking at.

        The y axis is fixed 0..1 and clamped. Scaled to the data instead, a
        60 % brake application and a 90 % one would be drawn at the same
        height, and the template would be pretty and wrong.
        """
        if length_m <= 0 or len(offsets_m) == 0:
            return [0.0, float(top + height), float(width), float(top + height)]
        flat: "list[float]" = []
        for offset, value in zip(offsets_m, values):
            x = float(offset) / float(length_m) * float(width)
            clamped = min(1.0, max(0.0, float(value)))
            flat.extend([x, float(top) + (1.0 - clamped) * float(height)])
        if len(flat) == 2:
            # tkinter will not draw a line with one point, and the driver has
            # exactly one sample on the first frame of every window.
            flat = flat + [flat[0] + 0.5, flat[1]]
        return flat
```

In `Overlay.__init__`, after `self.sentence` is created and before `self._position = position`, add:

```python
        self._strip_h = max(18, int(_STRIP_H * k))
        self._strip_gap = max(3, int(_STRIP_GAP * k))
        self.strips = tk.Canvas(
            card, bg=CARD, highlightthickness=0, bd=0,
            width=text_width, height=2 * self._strip_h + self._strip_gap,
        )
        self.entry = tk.Label(
            card, text="", font=("Segoe UI", max(8, int(11 * k))),
            fg=MUTED, bg=CARD, anchor="w",
        )
        self._strip_width = text_width
        self._template_up = False
```

Add the two methods, next to `show_finding`:

```python
    def show_template(self, showing, own_brake, own_throttle,
                      entry_delta_kmh=None) -> None:
        """The reference's pedals for this corner, with the driver's over them.

        Drawn from scratch each frame rather than moved: the driver's line
        grows by a point or two per frame and the reference does not change,
        and a canvas of a few hundred segments redraws far inside the 15 Hz
        this is called at.
        """
        template = showing.template
        width, height = self._strip_width, self._strip_h
        gap = self._strip_gap
        self.strips.delete("all")

        for top, values, own, colour in (
            (0, template.brake, own_brake, OWN_BRAKE),
            (height + gap, template.throttle, own_throttle, OWN_THROTTLE),
        ):
            self.strips.create_line(
                *self._strip_points(template.offsets_m, values,
                                    template.length_m, width, top, height),
                fill=GHOST, width=max(2, int(height / 12)),
            )
            if len(own):
                self.strips.create_line(
                    *self._strip_points(template.offsets_m[:len(own)], own,
                                        template.length_m, width, top, height),
                    fill=colour, width=max(2, int(height / 10)),
                )

        mark = template.brake_at_m / template.length_m * width
        self.strips.create_line(
            mark, 0, mark, 2 * height + gap, fill=MARK, dash=(3, 3),
        )
        here = showing.at_m / template.length_m * width
        self.strips.create_line(
            here, 0, here, 2 * height + gap, fill=INK,
        )

        if entry_delta_kmh is None:
            self.entry.configure(text=template.corner.name.upper())
        else:
            # Shown, never corrected for. A car arriving slower may brake
            # later, but turning that into a moved mark would be a braking
            # model, and the number would look measured when it was invented.
            self.entry.configure(
                text=f"{template.corner.name.upper()}   "
                     f"{entry_delta_kmh:+.0f} km/h in"
            )

        if not self._template_up:
            self.entry.pack(anchor="w", pady=self._tip_pad)
            self.strips.pack(anchor="w", fill="x")
            self._template_up = True
            self._relayout()

    def hide_template(self) -> None:
        if not self._template_up:
            return
        self.strips.pack_forget()
        self.entry.pack_forget()
        self._template_up = False
        self._relayout()
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_overlay_template.py tests/unit/test_overlay_placement.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live/overlay.py tests/unit/test_overlay_template.py && git commit -m "Draw both pedals over the same metres, on a scale that cannot flatter"
```

---

### Task 5: Wiring it to the car

**Files:**
- Modify: `lmu_telemetry/live/__main__.py`
- Test: `tests/unit/test_template.py`

**Interfaces:**
- Consumes: `templates_for`, `TemplateWatch` (Tasks 1–2), `play_brake_tone` (Task 3), `Overlay.show_template` / `.hide_template` (Task 4), `LapBuffer.trace()`, `CornerWatch.why_silent`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_template.py`:

```python
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
```

- [ ] **Step 2: Run to verify**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_template.py -q -k "recorded or sampled"`
Expected: PASS if Tasks 1–2 are correct. These pin the end-to-end property rather than drive new code; if `test_a_recorded_lap_arms_every_braked_corner_once` reports fewer tones than corners, a window is being missed — check `span_indices` for a corner whose approach wraps.

- [ ] **Step 3: Wire it into `_drive`**

At the top of `lmu_telemetry/live/__main__.py`, add to the imports:

```python
from .template import TemplateWatch, templates_for
from .tone import play_brake_tone
```

In `main()`, after `watch = CornerWatch(reference, model.corners)`, add:

```python
    templates = TemplateWatch(
        templates_for(reference, model.corners),
        float(reference.grid[-1]) + GRID_STEP_M,
    )
    print(f"templates: {len(templates.templates)} braked corners")
```

and add `from ..core.geometry import GRID_STEP_M` to the imports.

Change the `_drive` signature to accept it and pass it from `main()`:

```python
    _drive(source, buffer, watch, templates, reference, overlay, drawn_at, on_lap)
```

```python
def _drive(source, buffer, watch, templates, reference, overlay, drawn_at, on_lap):
```

In `_drive`, inside the lap-change branch, add `templates.reset()` beside `watch.reset()`.

Replace the redraw block at the end of the loop with:

```python
        now = time.perf_counter()
        if overlay is not None and now - drawn_at >= 1.0 / REDRAW_HZ:
            drawn_at = now
            was = float(np.interp(sample.distance_m, reference.grid, reference.time_s))
            overlay.show_delta(sample.time_s - was)
            _show_template(overlay, templates, buffer, watch, sample, now)
            overlay.pump()
```

and add the helper beside `_drive`:

```python
def _show_template(overlay, templates, buffer, watch, sample, now) -> None:
    """Put the braking template up, or take it down.

    Nothing is shown on a lap that used the pit lane, by the same rule that
    silences the sentences there: an out lap is not a lap, and a template
    inviting the driver to match a qualifying brake point on cold tyres out of
    the pits is worse than no template.
    """
    showing = templates.showing(sample.distance_m, now)
    if showing is None or watch.why_silent is not None:
        return overlay.hide_template()

    template = showing.template
    try:
        driven = buffer.trace()
    except ValueError:
        return overlay.hide_template()      # fewer than two samples so far

    # Only as far as the car has come. Past that the buffer holds its last
    # sample flat, and a line drawn there is that instant repeated - which
    # would look like a driver holding a steady pedal into a corner they have
    # not reached.
    reached = int(np.searchsorted(template.offsets_m, showing.at_m, side="right"))
    upto = template.abs_m[:reached]
    own_brake = np.interp(upto, driven.grid, driven.brake)
    own_throttle = np.interp(upto, driven.grid, driven.throttle)

    entry_delta = None
    if showing.at_m >= template.entry_at_m:
        mine = float(np.interp(
            template.abs_m[
                int(np.searchsorted(template.offsets_m, template.entry_at_m))
            ],
            driven.grid, driven.speed_kmh,
        ))
        entry_delta = mine - template.entry_speed_kmh

    overlay.show_template(showing, own_brake, own_throttle, entry_delta)


def _sound_if_due(templates, sample) -> None:
    if templates.tone_due(sample.distance_m):
        play_brake_tone()
```

Call `_sound_if_due(templates, sample)` in the sample loop, immediately after `buffer.add(sample)` — **not** in the redraw block. The tone is a position, and gating it on the 15 Hz redraw would put it up to 67 ms late, which at 250 km/h is 4.6 m.

- [ ] **Step 4: Verify against a recording**

Run:

```bash
.venv/Scripts/python.exe -u -m lmu_telemetry.live --replay "F:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Telemetry\Autodromo Nazionale Monza_R_2026-03-28T17_09_54Z.duckdb" --replay-lap 6 --reference "F:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Telemetry\Autodromo Nazionale Monza_R_2026-03-28T17_09_54Z.duckdb" --reference-lap 4 --speed 3
```

Expected: `templates: 7 braked corners` in the header, a strip that appears before each braking zone with a grey line and a coloured one over it, a dashed mark, and a tone at each. Watch that the coloured line stops at the moving position line rather than running the full width.

- [ ] **Step 5: Run everything**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass. 442 was the count before this plan.

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/live/__main__.py tests/unit/test_template.py && git commit -m "Show the template while the corner is still ahead"
```

---

## Self-review

**Spec coverage.** Distance axis: Task 1 (`offsets_m`) and Task 4 (`_strip_points`), asserted in `test_the_two_lines_land_on_the_same_metres`. Fixed 0..1 scale: Task 4, `test_the_scale_is_fixed_and_not_stretched_to_the_data`. No brake-point correction, entry difference shown: Task 4's `entry_delta_kmh` and Task 5's `_show_template`. `buffer.trace()` as the source: Task 5. `APPROACH_M` reused: Task 1. Only braked corners: Task 1, `test_a_corner_taken_flat_gets_no_template`. Nothing on an out lap: Task 5, `_show_template`. Grey/coloured/mark/entry text: Task 4. Hold after the corner: Task 2, `TEMPLATE_HOLD_S`. Tone once per corner, asynchronous, at the brake point: Tasks 2, 3, 5. Wrapping window: Tasks 1 and 2.

**Type consistency.** `Showing(template, at_m, past_corner)` is built in Task 2 and read in Tasks 4 and 5 under those names. `Template.offsets_m`, `.abs_m`, `.brake`, `.throttle`, `.length_m`, `.brake_at_m`, `.entry_at_m`, `.entry_speed_kmh` are defined in Task 1 and used in Tasks 4 and 5 unchanged. `_strip_points(offsets_m, values, length_m, width, top, height)` has the same arity in its test and both call sites.

**One thing deliberately left thin.** `_show_template` calls `buffer.trace()` at 15 Hz, which re-interpolates the whole lap each time. At Monza that is a 2900-point numpy interpolation per channel, well inside the budget; if a longer circuit makes it show, the fix is a windowed trace and not a cache, because a cache would go stale mid-corner.
