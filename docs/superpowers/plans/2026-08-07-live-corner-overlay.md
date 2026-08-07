# Live Corner Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A transparent always-on-top panel that shows the live delta to a reference lap and, as each corner is left behind, the same action sentence the post-lap view produces.

**Architecture:** A new `lmu_telemetry/live/` package. `mLapDist` from shared memory removes the offline pipeline's hardest step — reconstructing progress from a wobbling 10 Hz channel — so what remains is filling the *same* 2 m grid as the lap runs and calling the *same* `corner_metrics` and `_advise`. Everything above the shared-memory reader is tested by replaying recorded laps through the identical buffer, so only the reader itself needs the game.

**Tech Stack:** Python 3.11+, numpy, ctypes + mmap (stdlib), tkinter (stdlib, already used by `start.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-07-live-corner-overlay-design.md`

---

## Prerequisite the user must do

`rF2SharedMemoryMapPlugin64.dll` (TheIronWolf) into `<LMU install>\Bin64\Plugins\`,
then enable it in LMU under Settings → Plugins. This project does not fetch or
place that DLL. Tasks 1–3 and 5 do not need it; Task 4 cannot be verified
without it.

## File Structure

| File | Responsibility |
|---|---|
| `lmu_telemetry/live/__init__.py` | The package's front door: `LiveSample`, `LapBuffer`, `CornerWatch` |
| `lmu_telemetry/live/buffer.py` | `LiveSample`, `LapBuffer` — raw samples in, a `LapTrace` on the model's grid out |
| `lmu_telemetry/live/watch.py` | `CornerWatch` — fires once per corner as its end is passed |
| `lmu_telemetry/live/sharedmem.py` | ctypes structs + mmap reader for the rF2 plugin |
| `lmu_telemetry/live/overlay.py` | The tkinter window |
| `lmu_telemetry/live/__main__.py` | Wiring, plus a `--replay` mode that drives it from a recording |
| `tests/unit/test_live_buffer.py` | Replay equivalence |
| `tests/unit/test_live_watch.py` | Firing, ordering, and the silence rule |
| `tests/unit/test_live_sharedmem.py` | Struct size self-check and absence handling |

---

### Task 1: A lap buffer that fills as the lap runs

**Files:**
- Create: `lmu_telemetry/live/__init__.py`, `lmu_telemetry/live/buffer.py`
- Test: `tests/unit/test_live_buffer.py`

The test that matters: replay a *recorded* lap through the buffer one sample
at a time and require the metrics that come out to match the ones the offline
pipeline produces from the same lap. If they differ, the live path has invented
a second definition of a brake point, which is the one thing this design exists
to prevent.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_live_buffer.py`:

```python
"""The live buffer must produce the numbers the offline pipeline produces.

Two definitions of a brake point would be two answers to one question. This
file replays a recorded lap through the live buffer sample by sample and
requires the corner metrics to come out the same.
"""

import numpy as np
import pytest

from lmu_telemetry.core.metrics import corner_metrics
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace
from lmu_telemetry.live.buffer import LapBuffer, LiveSample


def _replayed(trace, grid):
    """Feed every grid point of *trace* through a buffer, in track order."""
    buffer = LapBuffer(grid)
    for i in range(len(grid)):
        buffer.add(
            LiveSample(
                distance_m=float(grid[i]),
                time_s=float(trace.time_s[i]),
                speed_kmh=float(trace.speed_kmh[i]),
                throttle=float(trace.throttle[i]),
                brake=float(trace.brake[i]),
                steering=float(trace.steering[i]),
            )
        )
    return buffer


def test_a_replayed_lap_measures_the_same_as_the_recorded_one(monza_q_file):
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        trace = build_trace(session, lap, model.track_length_m)

    live = _replayed(trace, trace.grid).trace()
    for corner in model.corners:
        if corner.start_m > corner.end_m:
            continue                      # see the wrap limitation below
        offline = corner_metrics(trace, corner)
        online = corner_metrics(live, corner)
        assert online.brake_point_m == offline.brake_point_m, corner.name
        assert online.brake_peak_m == offline.brake_peak_m, corner.name
        assert online.trail_length_m == offline.trail_length_m, corner.name
        assert online.min_speed_kmh == pytest.approx(offline.min_speed_kmh)
        assert online.time_s == pytest.approx(offline.time_s)


def test_samples_that_go_backwards_are_ignored():
    """Shared memory repeats and jitters. A sample behind the furthest point
    reached is not new information, and letting it overwrite what is already
    there would put a dent in the trace at whatever the car was doing then."""
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    buffer.add(LiveSample(50.0, 1.0, 200.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(20.0, 1.1, 50.0, 0.0, 1.0, 0.0))
    assert buffer.reached_m == pytest.approx(50.0)
    trace = buffer.trace()
    assert trace.speed_kmh[int(50.0 // 2.0)] == pytest.approx(200.0)


def test_a_buffer_reports_how_far_the_lap_has_come():
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    assert buffer.reached_m is None
    buffer.add(LiveSample(0.0, 0.0, 100.0, 1.0, 0.0, 0.0))
    buffer.add(LiveSample(30.0, 1.0, 100.0, 1.0, 0.0, 0.0))
    assert buffer.reached_m == pytest.approx(30.0)


def test_resetting_forgets_the_previous_lap():
    grid = np.arange(0.0, 100.0, 2.0)
    buffer = LapBuffer(grid)
    buffer.add(LiveSample(50.0, 9.9, 200.0, 1.0, 0.0, 0.0))
    buffer.reset()
    assert buffer.reached_m is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_live_buffer.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.live'`.

- [ ] **Step 3: Write the buffer**

Create `lmu_telemetry/live/__init__.py`:

```python
"""Driving the corner comparison from live telemetry instead of a recording.

Nothing here measures anything. The whole point of this package is that a
lap being driven ends up on the same 2 m grid, with the same corner list,
as a lap read from disk - so `core.metrics` and `core.coaching` answer for
both, and there is one definition of a brake point rather than two.
"""

from .buffer import LapBuffer, LiveSample
from .watch import CornerWatch

__all__ = ["CornerWatch", "LapBuffer", "LiveSample"]
```

Create `lmu_telemetry/live/buffer.py`:

```python
"""One lap being driven, filled onto the track's grid as it goes.

The offline pipeline's hardest step - reconstructing progress from a 10 Hz
`Lap Dist` that wobbles backwards - has no counterpart here. Shared memory
reports distance along the lap directly, at 50 Hz, which at any speed the car
reaches is finer than the 2 m grid. So the grid is filled by interpolating the
samples onto it, exactly as `trace._on_grid` does, and not by any new scheme.

Grid points ahead of the car hold the last value seen. That is safe only
because nothing is ever measured there: `CornerWatch` asks for a corner's
numbers when the corner is behind the car, never before.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.trace import LapTrace


@dataclass(frozen=True)
class LiveSample:
    """One instant of the car, as shared memory reports it."""

    distance_m: float
    time_s: float
    speed_kmh: float
    throttle: float
    brake: float
    steering: float


class LapBuffer:
    """The lap so far, on the track model's grid."""

    def __init__(self, grid: np.ndarray) -> None:
        self.grid = np.asarray(grid, dtype=np.float64)
        self._samples: list[LiveSample] = []
        self._reached: float | None = None

    @property
    def reached_m(self) -> float | None:
        """How far round the lap the car has come, or None before it starts."""
        return self._reached

    def reset(self) -> None:
        """Start a new lap. Called when the game reports the line was crossed."""
        self._samples.clear()
        self._reached = None

    def add(self, sample: LiveSample) -> None:
        """Record one instant, unless it is behind where the lap already is.

        Shared memory repeats a frame when the game is ahead of the reader, and
        jitters by centimetres besides. A sample behind the furthest point
        reached carries no new information, and interpolating it in would put a
        dent in the trace at whatever the car happened to be doing.
        """
        if self._reached is not None and sample.distance_m <= self._reached:
            return
        self._samples.append(sample)
        self._reached = sample.distance_m

    def trace(self) -> LapTrace:
        """The lap so far as a LapTrace, for `core.metrics` to measure.

        Beyond the car, every channel holds its last value - `np.interp` does
        that by construction. Those points are not measurable and must not be
        measured; see the module docstring.
        """
        if len(self._samples) < 2:
            raise ValueError(
                f"a lap needs at least 2 samples to be measured, have "
                f"{len(self._samples)}"
            )
        distance = np.array([s.distance_m for s in self._samples])

        def on_grid(pick) -> np.ndarray:
            return np.interp(
                self.grid, distance, np.array([pick(s) for s in self._samples])
            )

        return LapTrace(
            lap=None,
            grid=self.grid,
            time_s=on_grid(lambda s: s.time_s),
            speed_kmh=on_grid(lambda s: s.speed_kmh),
            throttle=on_grid(lambda s: s.throttle),
            brake=on_grid(lambda s: s.brake),
            steering=on_grid(lambda s: s.steering),
        )
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/unit/test_live_buffer.py -q
```

Expected: PASS. If the metrics differ by a metre or two, that is the
interpolation, and the test is right to fail — do not loosen it to `approx`
without understanding which sample moved.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live tests/unit/test_live_buffer.py
git commit -m "Fill the track's grid from a lap as it is driven"
```

---

### Task 2: Fire once per corner, as it is left behind

**Files:**
- Create: `lmu_telemetry/live/watch.py`
- Test: `tests/unit/test_live_watch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_live_watch.py`:

```python
"""A corner speaks when it is behind the car, once, and only with a story."""

import pytest

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
        laps = {l.number: l for l in session.laps}
        fast = build_trace(session, laps[2], model.track_length_m)
        slow = build_trace(session, laps[1], model.track_length_m)
    return model, fast, slow


def test_a_corner_is_never_reported_before_the_car_has_left_it(two_laps):
    model, fast, slow = two_laps
    for at_m, finding in _drive(slow, model.corners, fast):
        assert at_m >= finding.comparison.corner.end_m, finding.comparison.corner.name


def test_each_corner_speaks_at_most_once(two_laps):
    model, fast, slow = two_laps
    seen = [f.comparison.corner.index for _at, f in _drive(slow, model.corners, fast)]
    assert len(seen) == len(set(seen)), seen


def test_corners_are_reported_in_the_order_they_are_driven(two_laps):
    model, fast, slow = two_laps
    at = [a for a, _f in _drive(slow, model.corners, fast)]
    assert at == sorted(at)


def test_a_lap_against_itself_finds_nothing_to_say(two_laps):
    """Every measurement identical, so no corner has a story."""
    model, fast, _slow = two_laps
    said = [f for _at, f in _drive(fast, model.corners, fast) if f.advice is not None]
    assert said == []


def test_the_findings_carry_the_same_advice_the_post_lap_view_would(two_laps):
    """The live path must not be a second opinion."""
    from lmu_telemetry.core.coaching import compare_corners

    model, fast, slow = two_laps
    live = {
        f.comparison.corner.index: f.advice
        for _at, f in _drive(slow, model.corners, fast)
        if f.advice is not None
    }
    offline = {}
    for comparison in compare_corners(fast, slow, model.corners):
        from lmu_telemetry.core.coaching import _advise

        tip = _advise(comparison)
        if tip is not None:
            offline[comparison.corner.index] = tip

    assert set(live) == set(offline), (sorted(live), sorted(offline))
    for index, tip in live.items():
        assert tip.headline == offline[index].headline
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_live_watch.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.live.watch'`.

- [ ] **Step 3: Write the watch**

Create `lmu_telemetry/live/watch.py`:

```python
"""Reporting each corner once, as soon as the car has finished it.

The corner's numbers are taken the moment its end is behind the car, and
compared against the reference's numbers for the same corner. Nothing is
measured ahead of the car and nothing is measured twice.

`lost_s` is the difference of the two corner times rather than the integral of
a delta trace, because there is no delta trace until the lap ends.
`time_lost_over` measures exactly that difference across a corner's span, so
the two agree; `test_live_watch` pins them together.

A corner containing the start/finish line is skipped. Its start lies in the
previous lap, which this buffer has already forgotten, and reporting it from a
half-filled span would be a number about nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.coaching import CornerComparison, _advise, _differences
from ..core.corners import Corner
from ..core.metrics import corner_metrics
from ..core.trace import LapTrace
from .buffer import LapBuffer


@dataclass(frozen=True)
class Finding:
    """One completed corner: what was measured, and what to say about it."""

    comparison: CornerComparison
    #: None where the measurements do not agree on a story - the normal case.
    advice: "object | None"


class CornerWatch:
    """Watches a lap go by and reports each corner as it is completed."""

    def __init__(self, reference: LapTrace, corners) -> None:
        self.reference = reference
        # In track order, and without the one across the line; see the module
        # docstring. Sorting by end_m is what makes "the next corner to
        # complete" a single moving index rather than a search.
        self.corners = sorted(
            (c for c in corners if c.start_m <= c.end_m), key=lambda c: c.end_m
        )
        self._next = 0
        self._reference_metrics: dict[int, object] = {}

    def advance(self, buffer: LapBuffer) -> "list[Finding]":
        """Every corner completed since the last call, in track order."""
        reached = buffer.reached_m
        if reached is None:
            return []

        out = []
        while self._next < len(self.corners):
            corner = self.corners[self._next]
            if reached < corner.end_m:
                break
            out.append(self._finish(corner, buffer))
            self._next += 1
        return out

    def _finish(self, corner: Corner, buffer: LapBuffer) -> Finding:
        reference = self._reference_metrics.get(corner.index)
        if reference is None:
            reference = corner_metrics(self.reference, corner)
            self._reference_metrics[corner.index] = reference

        driven = corner_metrics(buffer.trace(), corner)
        comparison = CornerComparison(
            corner=corner,
            lost_s=driven.time_s - reference.time_s,
            reference=reference,
            other=driven,
            differences=_differences(reference, driven),
        )
        return Finding(comparison=comparison, advice=_advise(comparison))

    def reset(self) -> None:
        """A new lap has begun. Reference metrics are kept - they do not change."""
        self._next = 0
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/unit/test_live_watch.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/live/watch.py tests/unit/test_live_watch.py
git commit -m "Report each corner the moment the car has finished it"
```

---

### Task 3: Pin the live and offline time-lost figures together

`_finish` computes `lost_s` as a difference of corner times; `compare_corners`
integrates a delta trace. They must agree, or the same corner reads differently
in the panel and in the browser.

**Files:**
- Test: `tests/unit/test_live_watch.py`

- [ ] **Step 1: Write the test**

```python
def test_live_time_lost_agrees_with_the_post_lap_figure(two_laps):
    """One computed from two corner times, the other by integrating a delta.

    They are the same quantity, and if they drift the panel and the browser
    disagree about the same corner.
    """
    from lmu_telemetry.core.coaching import compare_corners

    model, fast, slow = two_laps
    offline = {
        c.corner.index: c.lost_s for c in compare_corners(fast, slow, model.corners)
    }
    for _at, finding in _drive(slow, model.corners, fast):
        index = finding.comparison.corner.index
        assert finding.comparison.lost_s == pytest.approx(offline[index], abs=0.02), (
            model.corners[index - 1].name
        )
```

- [ ] **Step 2: Run it**

```bash
python -m pytest tests/unit/test_live_watch.py -k time_lost_agrees -q
```

Expected: PASS. If it fails, the disagreement is real and belongs in the
docstring of whichever definition is wrong — do not widen `abs=` to hide it.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_live_watch.py
git commit -m "Pin the live and post-lap time-lost figures to each other"
```

---

### Task 4: Read the shared memory

**Files:**
- Create: `lmu_telemetry/live/sharedmem.py`
- Test: `tests/unit/test_live_sharedmem.py`

**This is the one part that cannot be verified without LMU running.** The
guard against that is a size self-check: a transcribed struct whose
`ctypes.sizeof` does not match the mapping must fail loudly, because a struct
off by one field returns plausible-looking garbage.

- [ ] **Step 1: Transcribe the structs**

Take the layout from TheIronWolf's `rF2Data.h` at the plugin version installed
(`rF2SharedMemoryMapPlugin64.dll`, Settings → Plugins in LMU). Transcribe
`rF2Vec3`, `rF2VehicleTelemetry`, and `rF2Telemetry` in field order — the whole
struct, not a subset, because ctypes computes offsets from what precedes a
field and a skipped field silently shifts every one after it.

Do not write this from memory. Read the header.

- [ ] **Step 2: Write the reader**

Create `lmu_telemetry/live/sharedmem.py`:

```python
"""Live telemetry from the rF2 Shared Memory Map Plugin.

LMU runs on the rFactor 2 engine and exposes its state through TheIronWolf's
plugin, the same interface SimHub and the rest read. Two mappings matter:

    $rFactor2SMMP_Telemetry$   ~50 Hz, physics and driver inputs
    $rFactor2SMMP_Scoring$     ~5 Hz, session and lap state

The DLL is the user's to install - it is a third-party binary going into a
game directory, and this project neither fetches nor places it. Its absence is
reported, never papered over: a reader that returned zeros would drive an
overlay that confidently showed a stationary car.
"""

from __future__ import annotations

import ctypes
import mmap

TELEMETRY_MAP = "$rFactor2SMMP_Telemetry$"
SCORING_MAP = "$rFactor2SMMP_Scoring$"


class SharedMemoryUnavailable(RuntimeError):
    """Raised when the plugin's mapping cannot be opened, with what to do."""


def _explain(name: str) -> str:
    return (
        f"cannot open {name}. Le Mans Ultimate must be running with the rF2 "
        f"Shared Memory Map Plugin enabled: put rF2SharedMemoryMapPlugin64.dll "
        f"in <LMU install>\\Bin64\\Plugins\\ and tick it under Settings -> "
        f"Plugins."
    )


class SharedMemoryReader:
    """One mapping, opened read-only."""

    def __init__(self, name: str, layout: type[ctypes.Structure]) -> None:
        self.name = name
        self.layout = layout
        try:
            self._mm = mmap.mmap(-1, ctypes.sizeof(layout), name,
                                 access=mmap.ACCESS_READ)
        except OSError as exc:
            raise SharedMemoryUnavailable(_explain(name)) from exc

        # A struct transcribed one field short still maps, and every value
        # after the gap comes back shifted and plausible. Size is the only
        # cheap check that catches it, so it is not optional.
        if len(self._mm) < ctypes.sizeof(layout):
            raise SharedMemoryUnavailable(
                f"{name} is {len(self._mm)} bytes but {layout.__name__} is "
                f"{ctypes.sizeof(layout)}; the struct does not match the "
                f"plugin version installed"
            )

    def read(self) -> ctypes.Structure:
        return self.layout.from_buffer_copy(self._mm[: ctypes.sizeof(self.layout)])

    def close(self) -> None:
        self._mm.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
```

Then a `sample()` that turns one telemetry frame into a `LiveSample`: speed is
the magnitude of `mLocalVel`, converted to km/h; `mLapDist` is metres along
the lap; `mElapsedTime` is seconds.

- [ ] **Step 3: Write the tests that do not need the game**

Create `tests/unit/test_live_sharedmem.py`:

```python
"""What can be checked without the game running: that absence is loud."""

import ctypes

import pytest

from lmu_telemetry.live.sharedmem import (
    SharedMemoryReader,
    SharedMemoryUnavailable,
)


class _Tiny(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double)]


def test_a_missing_mapping_says_what_to_install():
    """A reader that returned zeros would drive an overlay that confidently
    showed a stationary car."""
    with pytest.raises(SharedMemoryUnavailable) as caught:
        SharedMemoryReader("$definitely_not_running$", _Tiny)
    message = str(caught.value)
    assert "rF2SharedMemoryMapPlugin64.dll" in message
    assert "Plugins" in message


def test_the_telemetry_struct_has_the_fields_the_buffer_needs():
    from lmu_telemetry.live import sharedmem

    names = {name for name, *_ in sharedmem.rF2VehicleTelemetry._fields_}
    for needed in ("mLapDist", "mElapsedTime", "mUnfilteredThrottle",
                   "mUnfilteredBrake", "mUnfilteredSteering", "mLocalVel"):
        assert needed in names, needed
```

- [ ] **Step 4: Run them**

```bash
python -m pytest tests/unit/test_live_sharedmem.py -q
```

Expected: PASS.

- [ ] **Step 5: Verify against the running game**

With LMU running and in a session:

```bash
python -m lmu_telemetry.live --probe
```

Expected: distance, speed, throttle and brake printed once a second and
changing as the car moves. Speed must agree with the game's own readout within
a km/h or so — if it is out by a factor, `mLocalVel` is being read in the wrong
units or the struct is misaligned.

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/live/sharedmem.py tests/unit/test_live_sharedmem.py
git commit -m "Read the sim's live telemetry, and say so plainly when it is not there"
```

---

### Task 5: The panel

**Files:**
- Create: `lmu_telemetry/live/overlay.py`

- [ ] **Step 1: Write the window**

Create `lmu_telemetry/live/overlay.py`. tkinter, because `start.py` already
depends on it and a second GUI stack for one panel is not worth it.

```python
"""A small always-on-top panel: the delta, and the last corner's sentence.

Not injected into the game's renderer. Hooking a running D3D device is a far
larger and more fragile undertaking, and it buys nothing for text in a corner
of the screen. The cost of that choice is real and belongs here: **an
exclusive-fullscreen game covers this window.** LMU must run borderless or
windowed for the panel to be visible at all.
"""

from __future__ import annotations

import tkinter as tk

#: The colour the window paints where it wants to be see-through. A near-black
#: that is not pure black, so an actual black pixel in the text is not punched
#: out along with the background.
TRANSPARENT = "#000001"


class Overlay:
    def __init__(self, x: int = 40, y: int = 40) -> None:
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # no title bar
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.geometry(f"+{x}+{y}")
        self.root.configure(bg=TRANSPARENT)

        self.delta = tk.Label(
            self.root, text="--.---", font=("Consolas", 34, "bold"),
            fg="#e8e8ea", bg=TRANSPARENT,
        )
        self.delta.pack(anchor="w")

        self.corner = tk.Label(
            self.root, text="", font=("Segoe UI", 12), fg="#9a9aa2",
            bg=TRANSPARENT,
        )
        self.corner.pack(anchor="w")

        self.sentence = tk.Label(
            self.root, text="", font=("Segoe UI", 15, "bold"), fg="#e8e8ea",
            bg=TRANSPARENT, wraplength=420, justify="left",
        )
        self.sentence.pack(anchor="w")

    def show_delta(self, seconds: float) -> None:
        self.delta.configure(
            text=f"{seconds:+.3f}",
            fg="#e06c5a" if seconds > 0 else "#5ab88a",
        )

    def show_finding(self, name: str, sentence: str | None) -> None:
        """A corner just completed. `None` means it had no story - say nothing."""
        self.corner.configure(text=name if sentence else "")
        self.sentence.configure(text=sentence or "")

    def pump(self) -> None:
        self.root.update_idletasks()
        self.root.update()
```

- [ ] **Step 2: Verify it draws**

```bash
python -c "import time; from lmu_telemetry.live.overlay import Overlay; o=Overlay(); o.show_delta(-0.421); o.show_finding('Ascari 1','Come off the brake earlier here'); [ (o.pump(), time.sleep(0.02)) for _ in range(250) ]"
```

Expected: a borderless panel appears top-left for five seconds showing a green
`-0.421` and the sentence, with no grey box behind the text.

- [ ] **Step 3: Commit**

```bash
git add lmu_telemetry/live/overlay.py
git commit -m "Draw the panel that sits over the game"
```

---

### Task 6: Wire it up, and make it demonstrable without the game

**Files:**
- Create: `lmu_telemetry/live/__main__.py`

`--replay` is not a convenience. It is what makes the whole path above the
shared-memory reader verifiable on a machine with no sim running, and it is how
the overlay gets demonstrated at all before the DLL is installed.

- [ ] **Step 1: Write the entry point**

```
python -m lmu_telemetry.live --reference data/sessions/<file>.duckdb --reference-lap 2
python -m lmu_telemetry.live --reference <file>.duckdb --reference-lap 2 --replay <file>.duckdb --replay-lap 1
python -m lmu_telemetry.live --probe
```

- `--reference` / `--reference-lap` build the reference trace and the track
  model through the existing pipeline, so the corner list and grid are shared
  by construction.
- With `--replay`, samples come from a recorded lap played back at wall-clock
  speed instead of from shared memory.
- `--probe` prints raw shared-memory frames and exits; it is Task 4's
  verification step.

The loop: read a sample, `buffer.add`, `watch.advance`, push any finding to the
overlay, and set the delta from the reference's time at the current distance
minus the lap's own elapsed time. Redraw at about 15 Hz rather than 50 — the
panel is read by a driver, not sampled by an instrument.

On lap change, `buffer.reset()` and `watch.reset()`.

- [ ] **Step 2: Verify by replay**

```bash
python -m lmu_telemetry.live --reference tests/fixtures/monza_q_3laps.duckdb --reference-lap 2 --replay tests/fixtures/monza_q_3laps.duckdb --replay-lap 1
```

Expected: the panel shows a delta that grows through the lap (lap 1 is 5.5 s
slower than lap 2) and prints a sentence at the corners the post-lap view
already reports — with T10, T8, T4 and T6 among them, since those are what
`advice()` produces for this pair today.

- [ ] **Step 3: Commit**

```bash
git add lmu_telemetry/live/__main__.py
git commit -m "Run the overlay from the sim, or from a recording"
```

---

## Self-Review

**Spec coverage**

| Spec item | Task |
|---|---|
| Same grid, same corner list, same `corner_metrics` | 1 (replay equivalence test) |
| Sentence appears as the corner is left behind | 2 |
| Live and post-lap must not disagree | 2 (advice equality), 3 (lost_s) |
| Shared memory read via mmap + ctypes | 4 |
| Missing plugin reported, never papered over | 4 |
| Transparent always-on-top panel | 5 |
| Silence where there is no story | 2, 5 (`show_finding(None)`) |
| Exclusive fullscreen limitation stated | 5 (module docstring) |

**Known limitations, written into the code rather than left to be discovered**

- A corner containing the start/finish line is not reported live (`watch.py`
  docstring). Its start is in the previous lap, which the buffer has forgotten.
- The panel is invisible under exclusive fullscreen (`overlay.py` docstring).
- The struct in `sharedmem.py` is pinned to a plugin version; the size check is
  what turns a version mismatch into an error instead of plausible garbage.

**Type consistency:** `LiveSample` fields are used by name in `buffer.py`,
both test files and `__main__.py`. `LapBuffer` exposes `add`, `reset`,
`reached_m`, `trace`. `CornerWatch` exposes `advance(buffer) -> list[Finding]`
and `reset`. `Finding` carries `comparison` and `advice`.

**One import to check during Task 2:** `watch.py` uses `_advise` and
`_differences`, both currently private to `coaching.py`. If a second caller
outside that module is unwelcome, promote them in `coaching.py` and re-export
through `core/__init__.py` rather than duplicating either.
