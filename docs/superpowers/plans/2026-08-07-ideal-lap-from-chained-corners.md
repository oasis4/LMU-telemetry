# Ideal Lap From Chained Corners Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A theoretical best lap assembled from the driver's own laps, spliced only where splicing is defensible.

**Architecture:** One new module, `core/blocks.py`. It splits the track into *blocks* — runs of corners that must be taken from one lap or not at all — picks the quickest lap per block, and reports the entry-speed mismatch at every seam so the result cannot quietly claim a time it does not support.

**Tech Stack:** Python 3.11+, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-07-ideal-lap-from-chained-corners-design.md`

---

## The two decisions this rests on

**Which lap's throttle defines a block boundary?** Every candidate lap's. A
gap between two corners is a valid cut only if *all* the laps being spliced
reached sustained full throttle there. If any of them did not, that lap was
still connected through the gap, and a cut there would take its block time out
of a context it never had.

**What makes a seam sound?** The two laps that actually contribute the blocks
on either side of it must arrive at the cut at nearly the same speed. That is
computed after the choice, not before, because it is a property of the choice.

## File Structure

| File | Responsibility |
|---|---|
| `lmu_telemetry/core/blocks.py` | `Block`, `Seam`, `BlockChoice`, `IdealLap`, `split_into_blocks`, `ideal_lap` |
| `lmu_telemetry/core/__init__.py` | Export the five names |
| `tests/unit/test_blocks.py` | Segmentation: what merges, what separates |
| `tests/unit/test_ideal_lap.py` | Selection, timing, seam soundness |

---

### Task 1: Split the track into blocks

**Files:**
- Create: `lmu_telemetry/core/blocks.py`
- Test: `tests/unit/test_blocks.py`

- [ ] **Step 1: Write the failing tests**

The cases that matter, in the order they matter:

```python
def test_a_chicane_is_one_block():
    """Never off the brakes and onto full power between the two halves.

    This is the case the whole design exists for: take the left from one lap
    and the right from another and you get a lap nobody could drive.
    """

def test_two_corners_with_a_straight_between_them_separate():
    """Full throttle in the middle, so the exit of the first does not decide
    the entry of the second."""

def test_a_stab_of_throttle_between_two_corners_does_not_separate_them():
    """A short crack of throttle between the halves of a chicane is not a
    straight. BLOCK_THROTTLE_M is what tells them apart."""

def test_a_gap_only_one_lap_took_flat_stays_joined():
    """The cut has to be safe for every lap being spliced. One lap lifting
    there means that lap was still connected through it."""

def test_the_cut_sits_in_the_full_throttle_stretch_all_laps_share():
    """Not at the corner's end, and not where only one lap was flat."""

def test_every_corner_lands_in_exactly_one_block():
    """A corner falling through the segmentation would be time that belongs to
    no block and is silently absent from the ideal lap."""
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/unit/test_blocks.py -q
```

Expected: FAIL — no module `lmu_telemetry.core.blocks`.

- [ ] **Step 3: Write the segmentation**

Constants, with their reasoning:

```python
#: Full throttle held this far means the corners either side of it are
#: separate acts. Shorter than this is the crack of throttle between the two
#: halves of a chicane, which is not a straight and does not make them two.
BLOCK_THROTTLE_M = 50.0
```

`split_into_blocks(traces, corners)`:
1. Corners in track order; the one across the start/finish line is handled by
   the wrap arithmetic, not excluded.
2. For each consecutive pair, take the gap `[corners[i].end_m, corners[i+1].start_m]`.
3. In each trace, find runs of `throttle > THROTTLE_ON` inside that gap and
   keep those at least `BLOCK_THROTTLE_M` long.
4. Intersect those ranges across all traces. Empty intersection → the two
   corners are one block. Non-empty → separable, and the cut is the midpoint
   of the intersection.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "Split the track where the laps agree it can be split"
```

---

### Task 2: Time each block, and pick the quickest lap for it

**Files:**
- Modify: `lmu_telemetry/core/blocks.py`
- Test: `tests/unit/test_ideal_lap.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_block_times_of_one_lap_sum_to_that_lap():
    """The segmentation must not lose or double-count a metre of the lap.
    If these do not sum, every figure built on them is wrong by the remainder.
    """

def test_the_ideal_is_never_slower_than_the_best_real_lap():
    """It is a minimum over laps, block by block. A best lap is one of the
    candidates, so the ideal is at worst equal to it."""

def test_the_ideal_equals_the_only_lap_when_there_is_only_one():
    """No choice to make, and no gain to claim."""

def test_each_block_names_the_lap_it_came_from():
    """A target time with no provenance cannot be checked, and cannot be
    driven towards."""
```

- [ ] **Step 2: Write it**

Block time on a lap: `t(end) - t(start)` by interpolating `trace.time_s` at
the two cut distances. The block containing the start/finish line is summed
over its two halves — `(lap_duration - t(start)) + t(end)` — for the same
reason `corner_metrics` does it: the two halves sit at opposite ends of the
array and subtracting one from the other returns the rest of the lap with a
minus sign.

- [ ] **Step 3: Run, then commit**

---

### Task 3: Report what each seam costs in credibility

**Files:**
- Modify: `lmu_telemetry/core/blocks.py`
- Test: `tests/unit/test_ideal_lap.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_seam_between_two_laps_at_the_same_speed_is_sound():

def test_a_seam_where_the_laps_arrive_differently_is_reported_unsound():
    """The block after the seam was driven from an entry the ideal lap does
    not deliver, so its time is not transferable. Saying so is the whole
    point: the alternative is a target that looks achievable and is not."""

def test_an_ideal_lap_with_any_unsound_seam_is_not_sound():

def test_a_seam_between_two_blocks_from_the_same_lap_is_always_sound():
    """Nothing was spliced there at all."""
```

Constant:

```python
#: How far apart two laps may arrive at a seam before the block after it is
#: taken from an entry the ideal lap does not deliver. Wider than
#: ADVICE_SPEED_KMH: this is a straight at full throttle, where laps differ by
#: more than they do at a minimum speed, and the cut was chosen to be where
#: they differ least.
SEAM_SPEED_KMH = 5.0
```

- [ ] **Step 2: Write it, run, commit**

---

### Task 4: Check it against real laps

**Files:**
- Test: `tests/unit/test_ideal_lap.py`

- [ ] **Step 1: Write the tests**

Against the committed `monza_q_3laps` fixture, which has two usable laps:

```python
def test_monza_splits_into_blocks_that_make_sense(monza_q_file):
    """Monza has 11 corners. Ascari's three are one block - one braking event,
    no full throttle between them - so the count must be below 11 and above 1.
    """

def test_the_ideal_lap_of_real_laps_is_between_the_best_lap_and_the_sum(monza_q_file):
    """Bounded below by the best real lap and above by nothing that matters,
    but every block time must be one a lap actually recorded."""

def test_every_seam_of_a_real_ideal_lap_is_reported_one_way_or_the_other(monza_q_file):
    """Sound or not, never absent - an unreported seam is an unexamined join."""
```

- [ ] **Step 2: Run, inspect the actual numbers, commit**

Print the segmentation once and read it. If Ascari is not one block, the
throttle test is wrong and the number it produced is worth more than the test
passing.

---

## Self-Review

**Spec coverage:** blocks from the no-full-throttle rule (Task 1); cut at the
shared full-throttle midpoint (Task 1); quickest lap per block with provenance
(Task 2); `ideal_s`, `gain_s` (Task 2); seams with entry-speed spread and
soundness (Task 3); one session at a time (the API takes traces the caller
chose, so this is the caller's constraint and is documented, not enforced).

**Deliberately not built:** the spliced *trace*. The spec makes it a second
step and nothing needs it yet — the times, the provenance and the seams are
what a driver can act on. Building an array with invented joins before anyone
has asked to draw it would be inventing data for its own sake.
