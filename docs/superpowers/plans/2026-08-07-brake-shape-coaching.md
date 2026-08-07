# Brake-Shape Coaching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read four markers out of each corner's brake trace instead of one, and turn their differences — always coupled to a min-speed or exit-speed signal — into finer post-lap advice sentences.

**Architecture:** `core/metrics.py` grows the three new markers on `CornerMetrics`, read from the same braking event `brake_point_m` is already read from. `core/coaching.py` compares them in `_differences` and gains three new patterns in `_advise`, each slotted next to the coarser existing rule it refines. The API and frontend pick the new fields up through the payload they already render. No new endpoint, no realtime path.

**Tech Stack:** Python 3.11+, numpy, pytest, FastAPI, Vue 3.

**Spec:** `docs/superpowers/specs/2026-08-07-brake-shape-coaching-design.md`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `lmu_telemetry/core/metrics.py` | Reads one lap's numbers through one corner | Add `TRAIL_OFF`, `_brake_shape()`, three fields on `CornerMetrics` |
| `lmu_telemetry/core/coaching.py` | Compares two laps, produces advice | Add `ADVICE_TRAIL_M`, `TRAIL_NOISE_M`, two new `_differences` entries, three new `_advise` patterns |
| `lmu_telemetry/api/app.py` | Serves the comparison | Add three keys to `_corner_metrics()` |
| `frontend/src/components/CornerFocus.vue` | Per-corner numbers | Add a trail-length row |
| `tests/unit/test_metrics.py` | Marker extraction | New tests |
| `tests/unit/test_advice.py` | The "never alone" rule | New tests |
| `tests/unit/test_api.py` | Payload shape | Extend existing assertion |

---

### Task 1: Read all four brake markers from the trace

**Files:**
- Modify: `lmu_telemetry/core/metrics.py:26-33` (constants), `:92-115` (`_brake_point`), `:35-46` (`CornerMetrics`), `:150-159` (construction)
- Test: `tests/unit/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_metrics.py`. Reuse the module's existing trace helper if one is present; otherwise add this local one:

```python
from lmu_telemetry.core.metrics import TRAIL_OFF, corner_metrics
from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for
from lmu_telemetry.core.trace import LapTrace
import numpy as np

SHAPE_LAP_M = 2000.0
SHAPE_CORNER = Corner(
    index=1, name="T1", start_m=900.0, apex_m=950.0, end_m=1000.0,
    radius_m=80.0, heading_deg=90.0, direction="L",
)


def _at(distance_m):
    return int(distance_m / GRID_STEP_M)


def _shaped_trace(brake):
    """A lap at a constant pace with the given brake channel."""
    grid = grid_for(SHAPE_LAP_M)
    n = len(grid)
    speed = np.full(n, 200.0)
    speed[_at(900.0):_at(1000.0)] = 100.0
    time_s = np.concatenate(([0.0], np.cumsum(GRID_STEP_M / (speed[:-1] / 3.6))))
    return LapTrace(
        lap=None, grid=grid, time_s=time_s, speed_kmh=speed,
        throttle=np.zeros(n), brake=np.asarray(brake, float),
        steering=np.zeros(n),
    )


def _trail_brake(start_m, peak_m, release_m):
    """Pressure up at `start_m`, highest at `peak_m`, bled off by `release_m`."""
    brake = np.zeros(len(grid_for(SHAPE_LAP_M)))
    brake[_at(start_m):_at(peak_m)] = 0.6
    brake[_at(peak_m)] = 1.0
    # A linear taper from the peak down through TRAIL_OFF.
    taper = np.linspace(1.0, 0.0, _at(release_m) - _at(peak_m) + 2)[1:-1]
    brake[_at(peak_m) + 1:_at(release_m) + 1] = taper
    return brake


def test_the_four_markers_come_off_one_braking_event():
    metrics = corner_metrics(
        _shaped_trace(_trail_brake(800.0, 840.0, 940.0)), SHAPE_CORNER
    )
    assert metrics.brake_point_m == pytest.approx(800.0, abs=GRID_STEP_M)
    assert metrics.brake_peak_m == pytest.approx(840.0, abs=GRID_STEP_M)
    assert metrics.brake_release_m == pytest.approx(940.0, abs=2 * GRID_STEP_M)
    assert metrics.trail_length_m == pytest.approx(100.0, abs=2 * GRID_STEP_M)


def test_the_release_is_read_past_the_slowest_point():
    """A trail carries past the minimum speed.

    The brake point is found in a window that ends at the slowest sample. Read
    for the release too, that window would report every trail as ending
    exactly at the apex - a number that is an artefact of the window, not of
    the driving.
    """
    trace = _shaped_trace(_trail_brake(800.0, 830.0, 980.0))
    slowest = 900.0  # the speed plateau begins here
    metrics = corner_metrics(trace, SHAPE_CORNER)
    assert metrics.brake_release_m > slowest


def test_a_lap_that_never_braked_has_no_markers():
    metrics = corner_metrics(_shaped_trace(np.zeros(len(grid_for(SHAPE_LAP_M)))), SHAPE_CORNER)
    assert metrics.brake_point_m is None
    assert metrics.brake_peak_m is None
    assert metrics.brake_release_m is None
    assert metrics.trail_length_m is None


def test_the_release_threshold_is_below_the_one_that_starts_braking():
    """Or the tapering end of every trail is clipped by it."""
    from lmu_telemetry.core.metrics import BRAKE_ON
    assert 0.0 < TRAIL_OFF < BRAKE_ON


def test_a_stab_of_the_brakes_with_no_trail_has_a_trail_of_about_nothing():
    brake = np.zeros(len(grid_for(SHAPE_LAP_M)))
    brake[_at(800.0):_at(840.0)] = 0.9
    metrics = corner_metrics(_shaped_trace(brake), SHAPE_CORNER)
    assert metrics.trail_length_m == pytest.approx(38.0, abs=4 * GRID_STEP_M)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m pytest tests/unit/test_metrics.py -k "marker or release or trail or stab" -v
```

Expected: FAIL — `ImportError: cannot import name 'TRAIL_OFF'`.

- [ ] **Step 3: Add the threshold and the shape reader**

In `lmu_telemetry/core/metrics.py`, after the `BRAKE_ON` block (around line 27), add:

```python
#: Brake pressure below which the pedal is off, normalised (2 %). Lower than
#: BRAKE_ON on purpose: a trail tapers to nothing, and a release read at the
#: threshold that *starts* a braking event cuts the last stretch of it off -
#: exactly the stretch a trail-braking difference lives in.
TRAIL_OFF = 0.02
```

Replace `_brake_point` (lines 92-115) with:

```python
def _brake_shape(
    trace: LapTrace, corner: Corner, slowest: int
) -> "tuple[float, float, float, float] | None":
    """Start, peak, release and trail length of this corner's braking, in metres.

    The event is the one :func:`_brake_point` always picked: the last stretch
    of brake pressure before the slowest point. Taking the *first* stretch
    instead would report a brush of the pedal several hundred metres earlier -
    correcting a slide on the straight, say - as the brake point for the
    corner.

    The release is searched forward to the corner's end rather than to the
    slowest point, because a trail carries past the minimum speed. Bounded at
    the slowest sample instead, every trail would come back ending exactly at
    the apex: a number produced by the window, not by the driving.

    Trail length is counted in grid steps rather than subtracted from the
    distances, so it stays right for a corner that wraps the start/finish
    line, where the two distances are a lap apart.
    """
    lap_length = float(trace.grid[-1]) + GRID_STEP_M
    # An approach as long as the lap would wrap onto itself and come back as
    # no approach at all, silently. Every circuit is far longer than this, but
    # the failure would be a wrong brake point rather than an error.
    approach_m = min(APPROACH_M, lap_length - GRID_STEP_M)
    approach_start = (corner.start_m - approach_m) % lap_length
    window = span_indices(trace.grid, approach_start, float(trace.grid[slowest]))
    if len(window) == 0:
        return None

    runs = _runs(trace.brake[window] > BRAKE_ON)
    if not runs:
        return None
    start_index = int(window[runs[-1][0]])

    ahead = span_indices(trace.grid, float(trace.grid[start_index]), corner.end_m)
    if len(ahead) == 0:
        return None
    # The pedal is above BRAKE_ON at `ahead[0]`, and BRAKE_ON > TRAIL_OFF, so
    # this run always has at least its first sample and `last` is never -1.
    released = np.flatnonzero(trace.brake[ahead] <= TRAIL_OFF)
    last = len(ahead) - 1 if len(released) == 0 else int(released[0]) - 1

    peak = int(np.argmax(trace.brake[ahead[: last + 1]]))
    return (
        float(trace.grid[start_index]),
        float(trace.grid[ahead[peak]]),
        float(trace.grid[ahead[last]]),
        float(last - peak) * GRID_STEP_M,
    )
```

- [ ] **Step 4: Carry the markers on CornerMetrics**

Replace the `CornerMetrics` dataclass body (lines 36-46) with:

```python
@dataclass(frozen=True)
class CornerMetrics:
    """One lap's numbers through one corner. ``None`` means "did not happen"."""

    corner: Corner
    brake_point_m: float | None
    #: Where pressure was highest in that braking event, and where the pedal
    #: came off it. Between them is the trail phase, whose *length* is the
    #: measurement worth comparing: two drivers can release in different
    #: places and both be right, but how long they bled the brake off over is
    #: what shows up in the corner's outcome.
    brake_peak_m: float | None
    brake_release_m: float | None
    trail_length_m: float | None
    entry_speed_kmh: float
    min_speed_kmh: float
    min_speed_at_m: float
    throttle_point_m: float | None
    exit_speed_kmh: float
    time_s: float
```

Then in `corner_metrics` (line 150), replace the `brake_point_m=...` line with:

```python
    shape = _brake_shape(trace, corner, slowest)
    return CornerMetrics(
        corner=corner,
        brake_point_m=None if shape is None else shape[0],
        brake_peak_m=None if shape is None else shape[1],
        brake_release_m=None if shape is None else shape[2],
        trail_length_m=None if shape is None else shape[3],
```

Leave the remaining keyword arguments exactly as they are.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_metrics.py -v
```

Expected: PASS, including every pre-existing test in the file — `brake_point_m` must be unchanged.

- [ ] **Step 6: Run the whole unit suite to prove nothing shifted**

```bash
python -m pytest tests/unit -q
```

Expected: PASS. `test_public_surface.py::test_metrics_are_reachable_and_agree_with_the_comparison` asserts `brake_point_m` equality and is the guard that this refactor kept it identical.

- [ ] **Step 7: Commit**

```bash
git add lmu_telemetry/core/metrics.py tests/unit/test_metrics.py
git commit -m "Read the whole brake application, not just where it started"
```

---

### Task 2: Compare the new markers between the two laps

**Files:**
- Modify: `lmu_telemetry/core/coaching.py:23-29` (noise floors), `:64-96` (`_differences`)
- Test: `tests/unit/test_coaching.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_coaching.py`:

```python
def test_a_longer_trail_is_reported_as_a_difference():
    """The four markers are compared the way the single brake point always was."""
    from lmu_telemetry.core.coaching import compare_corners
    reference = _trace(brake=_trail_brake(800.0, 840.0, 900.0))
    other = _trace(brake=_trail_brake(800.0, 840.0, 960.0))
    comparison = compare_corners(reference, other, [CORNER])[0]
    what = [d.what for d in comparison.differences]
    assert "trail length" in what
    assert "brake release" in what


def test_a_trail_difference_inside_the_noise_floor_is_not_reported():
    from lmu_telemetry.core.coaching import compare_corners
    reference = _trace(brake=_trail_brake(800.0, 840.0, 900.0))
    other = _trace(brake=_trail_brake(800.0, 840.0, 904.0))
    comparison = compare_corners(reference, other, [CORNER])[0]
    assert "trail length" not in [d.what for d in comparison.differences]
```

Add the same `_trail_brake` helper used in Task 1 to this file if it does not already have one, and make sure `_trace` and `CORNER` exist here (they do in `test_advice.py`; mirror them if `test_coaching.py` lacks them).

- [ ] **Step 2: Run the test to verify it fails**

```bash
python -m pytest tests/unit/test_coaching.py -k trail -v
```

Expected: FAIL — `assert 'trail length' in [...]`.

- [ ] **Step 3: Add the noise floor**

In `lmu_telemetry/core/coaching.py`, after `BRAKE_POINT_NOISE_M` (line 27), add:

```python
#: A trail length is the gap between two positions on one trace, so its error
#: is about twice a single position's - which is why this is not
#: BRAKE_POINT_NOISE_M.
TRAIL_NOISE_M = 2 * BRAKE_POINT_NOISE_M
```

- [ ] **Step 4: Report the two new differences**

In `_differences`, after the throttle-point block (line 93), add:

```python
    if reference.brake_release_m is not None and other.brake_release_m is not None:
        metres = other.brake_release_m - reference.brake_release_m
        if abs(metres) >= BRAKE_POINT_NOISE_M:
            found.append((abs(metres), Difference("brake release", metres, "m")))

    if reference.trail_length_m is not None and other.trail_length_m is not None:
        metres = other.trail_length_m - reference.trail_length_m
        if abs(metres) >= TRAIL_NOISE_M:
            found.append((abs(metres), Difference("trail length", metres, "m")))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_coaching.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/core/coaching.py tests/unit/test_coaching.py
git commit -m "Compare how long the brake was bled off, not only where it went on"
```

---

### Task 3: The rule that keeps brake shape honest

Written before the patterns that could break it, so it is a real guard rather than a description of whatever got built.

**Files:**
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Add the `_trail_brake` helper to the test file**

Append to `tests/unit/test_advice.py`, next to `_brake_from`:

```python
def _trail_brake(start_m, peak_m, release_m):
    """Pressure up at `start_m`, highest at `peak_m`, bled off by `release_m`."""
    brake = np.zeros(len(grid_for(LAP_M)))
    brake[_index(start_m):_index(peak_m)] = 0.6
    brake[_index(peak_m)] = 1.0
    taper = np.linspace(1.0, 0.0, _index(release_m) - _index(peak_m) + 2)[1:-1]
    brake[_index(peak_m) + 1:_index(release_m) + 1] = taper
    return brake
```

- [ ] **Step 2: Write the failing guard test**

```python
def test_a_different_brake_shape_alone_says_nothing():
    """Two valid styles, not a fault.

    One driver stops the car and turns; the other carries the brake to the
    apex. The corner cost nothing and the outcome matched, so there is no
    result to attach the shape to - and a sentence about it here would be
    technically true and useless to drive on.
    """
    speed = _slow_through(100.0)
    reference = _trace(brake=_trail_brake(800.0, 820.0, 860.0), speed_kmh=speed)
    other = _trace(brake=_trail_brake(800.0, 820.0, 960.0), speed_kmh=speed)
    assert _advice_for(reference, other) == []


def test_a_brake_shape_difference_with_a_matched_outcome_stays_quiet():
    """The corner cost time, but neither the minimum nor the exit is worse.

    Something was lost here, and the shape difference is real - but nothing
    ties the two together, so naming the shape would be a guess wearing a
    number.
    """
    speed = _slow_through(100.0, exit_kmh=200.0)
    slower = speed.copy()
    slower[_index(900.0):_index(1000.0)] = 99.5   # inside SPEED noise, still costs time
    reference = _trace(brake=_trail_brake(800.0, 820.0, 860.0), speed_kmh=speed)
    other = _trace(brake=_trail_brake(800.0, 820.0, 960.0), speed_kmh=slower)

    comparison = compare_corners(reference, other, [CORNER])[0]
    assert comparison.lost_s > ADVICE_MIN_LOSS_S, "the corner must actually cost time"

    found = advice([comparison])
    assert all("trail" not in a.because for a in found), [a.headline for a in found]
```

- [ ] **Step 3: Run them to verify they pass on today's code**

```bash
python -m pytest tests/unit/test_advice.py -k "shape" -v
```

Expected: PASS — nothing says anything about trails yet. These tests exist to fail later if Task 4-6 get the coupling wrong, which is the point of writing them now.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_advice.py
git commit -m "Pin down that a brake shape never speaks on its own"
```

---

### Task 4: Pattern A — stopped it straight, then coasted

**Files:**
- Modify: `lmu_telemetry/core/coaching.py:136-140` (thresholds), `:171-183` (locals), `:207-224` (insert before the existing rule 2)
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Write the failing test**

```python
def test_braking_early_with_a_short_trail_is_told_to_stay_on_the_brake():
    """Braked earlier, came off it sooner, and was slower through the middle.

    The car was slowed in a straight line and then rolled through with no
    brake left to rotate it. The coarse rule would say only "brake later";
    the trail is what makes the second half of the sentence true.
    """
    reference = _trace(brake=_trail_brake(840.0, 860.0, 940.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(790.0, 810.0, 850.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "longer" in found[0].headline.lower()
    assert "trail length" in found[0].because
    assert "brake point" in found[0].because


def test_braking_early_without_a_trail_difference_still_gets_the_coarse_rule():
    """Pattern A refines rule 2; it must not swallow it."""
    reference = _trace(brake=_brake_from(840.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_brake_from(790.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "brake later" in found[0].headline.lower()
    assert "trail length" not in found[0].because
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_advice.py -k "short_trail or without_a_trail" -v
```

Expected: FAIL — `assert 'longer' in 'you can brake later here'`.

- [ ] **Step 3: Add the threshold**

In `lmu_telemetry/core/coaching.py`, after `ADVICE_SPEED_KMH` (line 140), add:

```python
#: How much longer or shorter a trail phase has to be to count. A trail length
#: is the gap between two positions on one trace, so its error is about twice
#: ADVICE_POINT_M's - and a typical trail runs 20-60 m, so this stays
#: deliberately demanding. Silence is the right answer more often than not.
ADVICE_TRAIL_M = 15.0
```

- [ ] **Step 4: Read the trail difference in `_advise`**

After the `throttle = ...` block (line 183), add:

```python
    trail = (
        None
        if reference.trail_length_m is None or other.trail_length_m is None
        else other.trail_length_m - reference.trail_length_m
    )
```

- [ ] **Step 5: Add the pattern, before the existing "braked earlier" rule**

Insert directly above the `# Braked earlier and slower everywhere` comment (line 207):

```python
    # Braked earlier, off the brake sooner, and slower through the middle: the
    # car was stopped in a straight line and then rolled through it with
    # nothing left on the brake to rotate it. This is rule 2 with the reason
    # attached, so it is tried first and rule 2 catches what it leaves.
    if (
        brake is not None
        and brake < -ADVICE_POINT_M
        and trail is not None
        and trail < -ADVICE_TRAIL_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Brake a touch later and stay on it longer",
            "You went to the brake earlier and came off it sooner, so the car "
            "was slowed in a straight line and had nothing left on the brake "
            "to turn with.",
            amounts(
                f"brake point {brake:+.0f} m",
                f"trail length {trail:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_advice.py -v
```

Expected: PASS, including the Task 3 guard tests.

- [ ] **Step 7: Commit**

```bash
git add lmu_telemetry/core/coaching.py tests/unit/test_advice.py
git commit -m "Say to stay on the brake when the car was stopped straight"
```

---

### Task 5: Pattern B — still braking where the reference was driving

**Files:**
- Modify: `lmu_telemetry/core/coaching.py` — insert before the existing throttle rule (`# Late on the power`, line 226 before Task 4's insert, later after it)
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_long_trail_with_a_slower_exit_is_told_to_release_earlier():
    """The entry matched; the brake was still on where the throttle belonged.

    The exit has to be slower *inside* the corner, or nothing was lost there -
    the same trap the throttle-rule test fell into first.
    """
    fast = np.full(len(grid_for(LAP_M)), 200.0)
    fast[_index(900.0):_index(960.0)] = 100.0      # both matched through the middle
    slow = fast.copy()
    fast[_index(960.0):_index(1000.0)] = 190.0     # reference picks up
    slow[_index(960.0):_index(1000.0)] = 120.0     # this lap is still slowing

    reference = _trace(brake=_trail_brake(800.0, 820.0, 900.0), speed_kmh=fast)
    other = _trace(brake=_trail_brake(800.0, 820.0, 980.0), speed_kmh=slow)

    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "off the brake earlier" in found[0].headline.lower()
    assert "trail length" in found[0].because
    assert "exit speed" in found[0].because


def test_a_long_trail_with_a_worse_entry_is_not_read_as_the_release():
    """Both a longer trail and a lower minimum speed.

    The trail rule must not claim this one: with the entry unmatched the long
    trail is as likely a consequence - still slowing because the corner was
    entered too fast - as a cause.
    """
    reference = _trace(brake=_trail_brake(800.0, 820.0, 880.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(800.0, 820.0, 970.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert found, "a corner this much slower should say something"
    assert all("off the brake earlier" not in a.headline.lower() for a in found), [
        a.headline for a in found
    ]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_advice.py -k "long_trail" -v
```

Expected: FAIL — the first test finds no advice at all.

- [ ] **Step 3: Add the pattern, before the throttle rule**

Insert directly above the `# Late on the power, with the entry matched` comment:

```python
    # Off the brake much later, with the entry matched and the exit slower:
    # the brake was still on where the reference was already driving. The
    # entry condition is what rules out the alternative - a long trail with a
    # worse minimum speed is a driver still slowing down, not one over-
    # trailing, and telling them to release earlier would point them away
    # from the corner they actually entered too fast.
    if (
        trail is not None
        and trail > ADVICE_TRAIL_M
        and minimum > -ADVICE_SPEED_KMH
        and exit_speed < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Come off the brake earlier here",
            "You matched the reference into the corner but carried the brake "
            "further through it, and the time went on the way out.",
            amounts(
                f"trail length {trail:+.0f} m",
                f"exit speed {exit_speed:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_advice.py -v
```

Expected: PASS. `test_a_late_throttle_pick_up_with_a_slower_exit` must still pass — its traces have no brake channel, so `trail` is `None` there and this rule cannot fire.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/coaching.py tests/unit/test_advice.py
git commit -m "Say to release the brake when it was still on through the exit"
```

---

### Task 6: Pattern C — slow to build the pressure

**Files:**
- Modify: `lmu_telemetry/core/coaching.py:171-183` (locals), and insert before the existing "more corner speed" rule
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_late_peak_from_the_same_brake_point_is_told_to_build_pressure():
    """Pedal down in the right place, full pressure late, slower through the middle."""
    reference = _trace(brake=_trail_brake(800.0, 812.0, 900.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(800.0, 860.0, 900.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "pressure" in found[0].headline.lower()
    assert "brake peak" in found[0].because


def test_a_matched_peak_still_gets_the_corner_speed_rule():
    """Pattern C refines rule 4; it must not swallow it."""
    reference = _trace(brake=_trail_brake(800.0, 820.0, 900.0), speed_kmh=_slow_through(100.0))
    other = _trace(brake=_trail_brake(800.0, 822.0, 900.0), speed_kmh=_slow_through(80.0))
    found = _advice_for(reference, other)
    assert len(found) == 1
    assert "corner speed" in found[0].headline.lower()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_advice.py -k "late_peak or matched_peak" -v
```

Expected: FAIL — the first test gets "There is more corner speed here".

- [ ] **Step 3: Read the peak difference in `_advise`**

Next to the `trail = ...` block added in Task 4, add:

```python
    peak = (
        None
        if reference.brake_peak_m is None or other.brake_peak_m is None
        else other.brake_peak_m - reference.brake_peak_m
    )
```

- [ ] **Step 4: Add the pattern, before the "more corner speed" rule**

Insert directly above the `# Slower through the middle with nothing else to explain it.` comment:

```python
    # The pedal went down in the right place but the pressure arrived late, so
    # the stop happened deeper than it should have and the middle of the
    # corner paid for it. This is rule 4 with a cause, so it is tried first
    # and rule 4 catches what it leaves.
    if (
        brake is not None
        and abs(brake) <= ADVICE_POINT_M
        and peak is not None
        and peak > ADVICE_POINT_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Get to full brake pressure sooner",
            "You went to the brake in the same place but took longer to reach "
            "peak pressure, so the car was still slowing where it should have "
            "been turning.",
            amounts(
                f"brake peak {peak:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )
```

- [ ] **Step 5: Run the whole advice suite**

```bash
python -m pytest tests/unit/test_advice.py -v
```

Expected: PASS, all of it — the four original patterns, the three new ones, and the Task 3 guards.

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/core/coaching.py tests/unit/test_advice.py
git commit -m "Say to build the pressure sooner when the peak arrived late"
```

---

### Task 7: The de-duplication guard covers the new patterns

`advice()` drops a second brake-point finding that came from the same braking event (Monza's Ascari is three corners and one stop). Patterns A and C cite a brake point too, and pattern B cites a trail from the same event, so the guard has to see them.

**Files:**
- Modify: `lmu_telemetry/core/coaching.py:289-299` (the `about_braking` test)
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Write the failing test**

```python
def test_one_braking_event_produces_one_finding_whatever_its_shape():
    """The Ascari guard has to see the trail rules too, not just 'brake point'."""
    corners = [
        Corner(index=1, name="Ascari 1", start_m=900.0, apex_m=930.0, end_m=960.0,
               radius_m=80.0, heading_deg=90.0, direction="L"),
        Corner(index=2, name="Ascari 2", start_m=960.0, apex_m=990.0, end_m=1020.0,
               radius_m=80.0, heading_deg=90.0, direction="R"),
    ]
    speed = np.full(len(grid_for(LAP_M)), 200.0)
    speed[_index(900.0):_index(1020.0)] = 110.0
    slow = speed.copy()
    slow[_index(900.0):_index(1020.0)] = 85.0

    found = advice(
        compare_corners(
            _trace(brake=_trail_brake(840.0, 860.0, 940.0), speed_kmh=speed),
            _trace(brake=_trail_brake(790.0, 810.0, 850.0), speed_kmh=slow),
            corners,
        )
    )
    braking = [a for a in found if "brake" in a.because or "trail" in a.because]
    assert len(braking) == 1, [a.corner.name for a in braking]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_advice.py -k whatever_its_shape -v
```

Expected: FAIL — two findings, because `"brake point" in item.because` is the only thing the guard looks for and pattern A's evidence also contains `"trail length"`, which alone would not have matched.

- [ ] **Step 3: Widen the guard**

In `advice()`, replace:

```python
        about_braking = "brake point" in item.because
```

with:

```python
        # Every brake-shape pattern reads the same braking event, so any of
        # them naming it is a finding about that one application - not just
        # the rules that happen to print "brake point".
        about_braking = any(
            phrase in item.because
            for phrase in ("brake point", "brake peak", "trail length")
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m pytest tests/unit/test_advice.py -v
```

Expected: PASS, including `test_two_separate_braking_events_both_get_advice` — two genuinely different corners must still both speak.

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/coaching.py tests/unit/test_advice.py
git commit -m "Keep one braking event to one finding, whichever rule names it"
```

---

### Task 8: Serve and show the new markers

**Files:**
- Modify: `lmu_telemetry/api/app.py:546-557` (`_corner_metrics`)
- Modify: `frontend/src/components/CornerFocus.vue:216-229` (the numbers table)
- Test: `tests/unit/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api.py`, following the file's existing client fixture and compare-endpoint pattern:

```python
def test_the_compare_payload_carries_the_whole_brake_shape(client, a_comparison_url):
    body = client.get(a_comparison_url).json()
    metrics = body["corners"][0]["reference"]
    for key in ("brake_point_m", "brake_peak_m", "brake_release_m", "trail_length_m"):
        assert key in metrics
```

Use whatever fixture the file already uses to reach `/compare`; do not invent a new one.

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/unit/test_api.py -k brake_shape -v
```

Expected: FAIL — `assert 'brake_peak_m' in {...}`.

- [ ] **Step 3: Add the keys to the payload**

In `_corner_metrics`, after the `brake_point_m` entry:

```python
        "brake_peak_m": None if metrics.brake_peak_m is None
        else round(metrics.brake_peak_m, 1),
        "brake_release_m": None if metrics.brake_release_m is None
        else round(metrics.brake_release_m, 1),
        "trail_length_m": None if metrics.trail_length_m is None
        else round(metrics.trail_length_m, 1),
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m pytest tests/unit/test_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Show the trail in the corner focus table**

In `CornerFocus.vue`, in the array returned around line 218, insert after the `'brake point'` row:

```js
    ['trail length', metres(r.trail_length_m), metres(o.trail_length_m),
      difference(r.trail_length_m, o.trail_length_m, 'm', 0)],
```

The brake peak and release stay out of the table: the trail length is the
comparable number, and two more marker rows would push the outcome speeds off
the visible part of the panel.

- [ ] **Step 6: Verify it renders**

Start the app and open a comparison with a corner that has braking; confirm the
"trail length" row shows metres for both laps and a signed difference.

```bash
python start.py
```

- [ ] **Step 7: Commit**

```bash
git add lmu_telemetry/api/app.py frontend/src/components/CornerFocus.vue tests/unit/test_api.py
git commit -m "Send and show how long the brake was trailed"
```

---

### Task 9: Check it against real laps

The unit tests are built from synthetic traces with clean trapezoid brake
traces. Real pedal data is noisy, and the corpus test is what says whether the
thresholds hold up on it.

**Files:**
- Test: `tests/unit/test_advice.py`

- [ ] **Step 1: Write the corpus test**

```python
@pytest.mark.corpus
def test_brake_shape_advice_on_real_laps_always_carries_an_outcome(corpus_dir):
    """A trail sentence without a speed behind it is the failure mode this
    whole feature is built to avoid, so it is checked on real pedal data."""
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        laps = [l for l in s.laps if l.number in (2, 3)]
        a, b = (build_trace(s, lap, model.track_length_m) for lap in laps)
        found = advice(compare_corners(a, b, model.corners))

    for item in found:
        if "trail length" in item.because or "brake peak" in item.because:
            assert "minimum speed" in item.because or "exit speed" in item.because, (
                item.headline, item.because
            )


@pytest.mark.corpus
def test_every_real_corner_with_braking_has_a_trail_length(corpus_dir):
    """A marker that comes back None on real data is a marker that does nothing."""
    path = corpus_dir / "Autodromo Nazionale Monza_R_2026-04-04T19_41_31Z.duckdb"
    if not path.is_file():
        pytest.skip("session not present")
    with Session.open(path) as s:
        model = build_track_model([s])
        lap = [l for l in s.laps if l.number == 2][0]
        trace = build_trace(s, lap, model.track_length_m)
        metrics = [corner_metrics(trace, c) for c in model.corners]

    braked = [m for m in metrics if m.brake_point_m is not None]
    assert braked, "Monza has braking zones"
    assert all(m.trail_length_m is not None for m in braked)
    assert all(m.trail_length_m >= 0.0 for m in braked)
```

Add `corner_metrics` to the file's imports from `lmu_telemetry.core.metrics`.

- [ ] **Step 2: Run the corpus tests**

```bash
python -m pytest tests/unit/test_advice.py -m corpus -v
```

Expected: PASS, or SKIP if the recording is not present. A failure here is a
real finding about the thresholds, not a broken test — report the actual
values before changing any constant.

- [ ] **Step 3: Run the whole suite**

```bash
python -m pytest tests/ -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_advice.py
git commit -m "Check the brake-shape rules against real pedal traces"
```

---

## Self-Review

**Spec coverage**

| Spec item | Task |
|---|---|
| Four markers from the brake trace | 1 |
| `brake_point_m` unchanged | 1 (steps 5-6) |
| Markers compared like the single brake point | 2 |
| Brake shape never stands alone | 3 (guards), 4-6 (each rule couples to a speed) |
| Pattern A "brake later, trail longer" | 4 |
| Pattern B "release earlier, roll longer" | 5 |
| Pattern C "build pressure sooner" | 6 |
| New rules refine, do not shadow, the old ones | 4 step 1, 6 step 1 |
| No new endpoint / no realtime path | Task 8 extends the existing payload only |
| Thresholds justified by resolution | 1 (`TRAIL_OFF`), 2 (`TRAIL_NOISE_M`), 4 (`ADVICE_TRAIL_M`) |

**Type consistency:** `brake_peak_m`, `brake_release_m`, `trail_length_m` are the
names used in `CornerMetrics` (Task 1), `_differences` (Task 2), `_advise`
(Tasks 4-6), the API payload (Task 8) and the Vue table (Task 8). `_brake_shape`
returns `(start, peak, release, trail_length)` in that order and is unpacked by
index only in `corner_metrics`.

**Placeholders:** none — every code step carries the code.
