# Showing the ideal lap — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `core.ideal_lap()` reachable — a `/api/sessions/{name}/ideal` endpoint and an `/ideal` page that shows which lap each block came from and whether the joins hold.

**Architecture:** One endpoint over one recording's clean laps, because `ideal_lap()` requires that. A new page rather than a card on the comparison view. The circuit is drawn by a new `BlockMap` component, not by a mode added to `TrackMap`, whose header commits to colour meaning time lost and to answering one question at a time. The shared projection is lifted into `track-projection.js`. The rule that a bad seam disqualifies the headline lives in a tested pure function, not in a template.

**Tech Stack:** Python 3.13, FastAPI, numpy, pytest; Vue 3, pinia, vue-router, vitest + jsdom.

## Global Constraints

- Endpoint path: `GET /api/sessions/{name}/ideal`. Over the clean laps of one recording only.
- `seam_limit_kmh` in the response must equal `lmu_telemetry.core.blocks.SEAM_SPEED_KMH` (currently `5.0`). Never hard-code `5.0` in the route or the client.
- Both refusals are HTTP 422 and must state their reason in `detail`.
- Where `IdealLap.sound` is false the page must not present `gain_s` as a plain headline number.
- Block order is driven order, beginning with the block holding the start/finish line — the order `split_into_blocks()` already returns. Do not re-sort.
- Run Python tests with `.venv/Scripts/python.exe -m pytest`; frontend tests with `npm test` from `frontend/`.
- Commit after every task. Branch is `feature/brake-shape-coaching`.

## Fixture facts (measured, do not re-derive)

| fixture | laps | clean | track model | use |
|---|---|---|---|---|
| `monza_q_3laps.duckdb` | 3 | **2** | yes | happy path, the minimum viable case |
| `monza_r_extra_dist_reset.duckdb` | 5 | **4** | yes | a richer ideal lap |
| `monza_r_position_jump.duckdb` | 3 | **1** | yes | refusal: fewer than two clean laps |
| `lemans_r_percent_steering.duckdb` | 1 | **0** | **no** | refusal: no track model |

`_model_for()` builds the model from *siblings* — every recording of the same circuit in the directory. So the no-model refusal needs a recording whose circuit has no clean lap anywhere in its directory. The Le Mans fixture alone in its own directory is that case; a Monza fixture is not, because its Monza siblings supply a model.

## File structure

- Create `tests/unit/test_api_ideal.py` — its own recordings directories, so `test_api.py`'s module-scoped fixture is untouched.
- Modify `lmu_telemetry/api/app.py` — one new route and one helper.
- Modify `frontend/src/api/client.js` — one method.
- Modify `frontend/src/stores/telemetry.js` — one action, one state field.
- Create `frontend/src/components/track-projection.js` — projection + wrap-aware span maths.
- Create `frontend/src/components/ideal-headline.js` — the soundness rule.
- Create `frontend/tests/track-projection.test.js`, `frontend/tests/ideal-headline.test.js`.
- Modify `frontend/src/components/TrackMap.vue` — consume the extracted projection.
- Create `frontend/src/components/BlockMap.vue`, `frontend/src/views/IdealView.vue`.
- Modify `frontend/src/router.js`, `frontend/src/App.vue` — the route and its link.

---

### Task 1: The endpoint, happy path

**Files:**
- Modify: `lmu_telemetry/api/app.py` (add route after `track_map`, around line 419)
- Test: `tests/unit/test_api_ideal.py` (create)

**Interfaces:**
- Consumes: `_model_for(name) -> (Session, TrackModel | None)`, `_trace_for(name, lap) -> (Session, TrackModel, LapTrace)`, `clean_laps(session)`, `build_trace(session, lap, track_length_m)`, `core.ideal_lap(traces, corners) -> IdealLap`, `core.blocks.SEAM_SPEED_KMH`.
- Produces: `GET /api/sessions/{name}/ideal` returning the JSON in the spec.

- [ ] **Step 1: Write the failing tests**

```python
"""The ideal lap, over the wire.

The endpoint exists so the ideal lap can be seen at all. What it must never
do is present a time the laps do not support - see the seam tests below and
`core/blocks.py` on why `sound` is an `all()` and not a count.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import create_app
from lmu_telemetry.core.blocks import SEAM_SPEED_KMH


@pytest.fixture(scope="module")
def client(tmp_path_factory, fixture_dir):
    recordings = tmp_path_factory.mktemp("ideal-recordings")
    for name in ("monza_q_3laps.duckdb", "monza_r_extra_dist_reset.duckdb",
                 "monza_r_position_jump.duckdb"):
        shutil.copy(fixture_dir / name, recordings / name)
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("ideal-cache"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_the_ideal_lap_is_built_from_the_recording_s_clean_laps(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["track"] == "Autodromo Nazionale Monza"
    assert body["laps_used"], "no laps named"
    assert len(body["laps_used"]) == 2, "the fixture has two clean laps"
    assert body["best_lap_number"] in body["laps_used"]


def test_the_blocks_account_for_the_whole_ideal_time(client):
    """A headline figure whose parts do not sum to it is two numbers, not one."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["blocks"]
    total = sum(block["time_s"] for block in body["blocks"])
    assert total == pytest.approx(body["ideal_s"], abs=0.01)


def test_the_gain_is_the_difference_it_claims_to_be(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["gain_s"] == pytest.approx(
        body["best_lap_s"] - body["ideal_s"], abs=0.001
    )
    assert body["ideal_s"] <= body["best_lap_s"] + 1e-9, (
        "an ideal lap slower than a lap that was actually driven"
    )


def test_every_block_names_the_lap_it_came_from(client):
    """A block whose source is unnamed cannot be checked against the lap."""
    body = client.get("/api/sessions/monza_r_extra_dist_reset.duckdb/ideal").json()
    for block in body["blocks"]:
        assert block["lap_number"] in body["laps_used"]
        assert block["name"]
        assert block["corners"], f"block {block['index']} holds no corners"


def test_the_first_block_is_the_one_holding_the_line(client):
    """Driven order, as split_into_blocks returns it. A block list sorted by
    distance would start somewhere arbitrary on the track."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    first = body["blocks"][0]
    assert first["index"] == 1
    if len(body["blocks"]) > 1:
        assert first["wraps"] == (first["start_m"] > first["end_m"])


def test_there_is_a_seam_for_every_block(client):
    """The lap is a loop; every block is entered from another one."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert len(body["seams"]) == len(body["blocks"])


def test_the_seam_limit_is_sent_rather_than_left_to_the_client(client):
    """Sent for the reason /api/compare sends brake_on: the flags are computed
    with it, and a client drawing its own threshold would contradict them."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["seam_limit_kmh"] == SEAM_SPEED_KMH
    for seam in body["seams"]:
        assert seam["sound"] == (seam["speed_spread_kmh"] <= body["seam_limit_kmh"])


def test_sound_is_true_only_when_every_seam_holds(client):
    body = client.get("/api/sessions/monza_r_extra_dist_reset.duckdb/ideal").json()
    assert body["sound"] == all(seam["sound"] for seam in body["seams"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api_ideal.py -q`
Expected: every test FAILS on a 404 — the route does not exist. If any fails on a fixture copy error instead, fix that first and re-run; a test that errors has not proved anything.

- [ ] **Step 3: Write the route**

Add after the `track_map` route in `lmu_telemetry/api/app.py`. Import at the top of the file, beside the other core imports:

```python
from ..core.blocks import SEAM_SPEED_KMH
from ..core.trace import build_trace
```

(`ideal_lap` comes from `..core`, which already exports it.)

```python
    @app.get("/api/sessions/{name}/ideal")
    def ideal(name: str) -> dict:
        """The best lap that could be assembled from this recording's laps.

        One recording, because `ideal_lap` requires it: two recordings mean
        two fuel loads and two tyre states, and a block time from one is not
        comparable to a block time from the other.
        """
        from ..core import ideal_lap

        session, model = _model_for(name)
        if model is None:
            raise HTTPException(
                422, f"no clean lap in {name!r} to measure the track from"
            )
        usable = clean_laps(session)
        if len(usable) < 2:
            raise HTTPException(
                422,
                f"{name!r} has {len(usable)} usable lap of {len(session.laps)}. "
                f"An ideal lap is assembled from several, so it needs at least "
                f"two to choose between.",
            )
        traces = [build_trace(session, lap, model.track_length_m) for lap in usable]
        built = ideal_lap(traces, model.corners)
        return {
            "name": name,
            "track": model.key.track,
            "laps_used": [lap.number for lap in usable],
            "ideal_s": round(built.ideal_s, 3),
            "best_lap_s": round(built.best_lap_s, 3),
            "best_lap_number": built.best_lap_number,
            "gain_s": round(built.gain_s, 3),
            "sound": built.sound,
            "blocks": [{
                "index": choice.block.index,
                "name": choice.block.name,
                "corners": [c.index for c in choice.block.corners],
                "start_m": round(choice.block.start_m, 1),
                "end_m": round(choice.block.end_m, 1),
                "wraps": choice.block.start_m > choice.block.end_m,
                "lap_number": choice.lap_number,
                "time_s": round(choice.time_s, 3),
                "gain_s": round(choice.gain_s, 3),
            } for choice in built.blocks],
            "seams": [{
                "at_m": round(seam.at_m, 1),
                "speed_spread_kmh": round(seam.speed_spread_kmh, 1),
                "sound": seam.sound,
            } for seam in built.seams],
            # Sent rather than repeated client-side: the flags above are
            # computed with it, so a client with its own copy would one day
            # mark a threshold that disagrees with them.
            "seam_limit_kmh": SEAM_SPEED_KMH,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api_ideal.py -q`
Expected: PASS. If `test_the_blocks_account_for_the_whole_ideal_time` fails by more than 0.01 s, do not widen the tolerance — the rounding is to 3 decimals and the sum of a handful of them cannot drift that far. Read `_block_time` and `_duration` in `core/blocks.py` instead.

- [ ] **Step 5: Run the whole Python suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: everything that passed before still passes. One pre-existing failure is known and unrelated: `test_geometry_curvature.py::test_heading_comes_from_the_tangent_not_from_integrating_curvature` (numpy 2 removed `np.trapz`). Nothing else may be red.

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/api/app.py tests/unit/test_api_ideal.py && git commit -m "Serve the ideal lap that until now could not be seen"
```

---

### Task 2: The two refusals

**Files:**
- Test: `tests/unit/test_api_ideal.py` (extend)
- Modify: `lmu_telemetry/api/app.py` only if a test fails

**Interfaces:**
- Consumes: the route from Task 1.
- Produces: nothing new; this fixes the wording and proves the paths.

The refusal for too few clean laps is the common case — of 60 recordings sampled from the corpus, 26 hit it and only 34 could build an ideal lap at all. It is the text most drivers will read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_api_ideal.py`:

```python
@pytest.fixture(scope="module")
def lonely_lemans(tmp_path_factory, fixture_dir):
    """Le Mans alone in a directory, so no sibling can supply a track model.

    _model_for builds the model from every recording of the same circuit in
    the directory. A Monza fixture with no clean lap would still get a model
    from its Monza siblings, so it cannot test this refusal.
    """
    recordings = tmp_path_factory.mktemp("lemans-only")
    shutil.copy(
        fixture_dir / "lemans_r_percent_steering.duckdb", recordings / "lemans.duckdb"
    )
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("lemans-cache"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_one_clean_lap_is_refused_with_the_count_that_caused_it(client):
    """The common path: 26 of 60 sampled recordings end here. A refusal that
    does not say what it counted is indistinguishable from a bug."""
    response = client.get("/api/sessions/monza_r_position_jump.duckdb/ideal")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "1 usable lap" in detail, detail
    assert "3" in detail, "the total the recording holds is not stated"
    assert "two" in detail, "the requirement is not stated"


def test_a_recording_with_no_track_model_is_refused(lonely_lemans):
    response = lonely_lemans.get("/api/sessions/lemans.duckdb/ideal")
    assert response.status_code == 422
    assert "measure the track from" in response.json()["detail"]


def test_a_recording_that_is_not_there_is_a_404_not_a_422(client):
    """A missing file and an unusable one are different problems."""
    assert client.get("/api/sessions/nope.duckdb/ideal").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api_ideal.py -q -k "refused or 404"`
Expected: the two refusal tests fail on the exact wording; the 404 test may already pass because `_resolve` handles it. A test that already passes here is fine and expected — `_resolve` is existing, tested behaviour and this pins it against the new route.

- [ ] **Step 3: Adjust the wording only if needed**

If `test_one_clean_lap_is_refused_with_the_count_that_caused_it` fails, the message in Task 1 Step 3 is the thing to fix, not the test. It must contain the usable count, the total, and the word "two".

- [ ] **Step 4: Run and verify**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_api_ideal.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_api_ideal.py lmu_telemetry/api/app.py && git commit -m "Say what was counted when there is not enough to build an ideal from"
```

---

### Task 3: Client method and store action

**Files:**
- Modify: `frontend/src/api/client.js:61-93` (the returned object)
- Modify: `frontend/src/stores/telemetry.js`

**Interfaces:**
- Consumes: the endpoint from Task 1.
- Produces: `client.ideal(name) -> Promise<object>`; store field `ideal` (a `shallowRef`) and action `loadIdeal(name)`.

- [ ] **Step 1: Add the client method**

In `frontend/src/api/client.js`, inside the returned object, after `track:`:

```js
    ideal: (name) => get(`/api/sessions/${encodeURIComponent(name)}/ideal`),
```

No `toTypedSeries`: this response carries no measurement arrays, only a few dozen numbers. Wrapping them in `Float64Array` would say otherwise.

- [ ] **Step 2: Add the store field and action**

In `frontend/src/stores/telemetry.js`, beside `comparison` and `trace`:

```js
  const ideal = shallowRef(null)
```

After `loadTrace`:

```js
  const loadIdeal = (name) =>
    run(async () => {
      // markRaw for the same reason as the others: nothing here is mutated,
      // and a deep proxy over the block list buys nothing.
      ideal.value = markRaw(await client.ideal(name))
      return ideal.value
    })
```

Add `ideal` and `loadIdeal` to the returned object, and set `ideal.value = null` inside `reset()`.

- [ ] **Step 3: Extend the existing tests**

`frontend/tests/client.test.js` and `frontend/tests/telemetry-store.test.js` already exist and cover every other client method and store action. Add to them: that `ideal` is asked for by recording alone with no lap number and no query string; that the body comes back as plain numbers rather than typed arrays; that a 422's `detail` reaches the caller; that `loadIdeal` fills `store.ideal` and that a refusal lands in `store.error`; and that `reset()` clears it.

- [ ] **Step 4: Verify**

Run from `frontend/`: `npm install`, then `npx vitest run` and `npm run build`
Expected: green. `npm install` is required — `node_modules` is not in the checkout.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.js frontend/src/stores/telemetry.js && git commit -m "Let the client ask for an ideal lap"
```

---

### Task 4: Extract the projection, and the first frontend test

**Files:**
- Create: `frontend/src/components/track-projection.js`
- Create: `frontend/tests/track-projection.test.js`
- Modify: `frontend/src/components/TrackMap.vue:38-74`

**Interfaces:**
- Produces:
  - `project(map, size) -> { minX, minY, scale, offsetX, offsetY }`
  - `pointAt(map, frame, size, index) -> "x,y"` (one decimal each)
  - `spanIndices(fromM, toM, trackLengthM, pointCount) -> [[first, last], ...]`

`spanIndices` is new, not extracted. `TrackMap.zonePath` clamps rather than wraps, because the server pre-splits braking zones into two ranges. A block that holds the start/finish line arrives as one range with `start_m > end_m` and must be split here.

The frontend already has 8 test files and 86 tests in `frontend/tests/` — including `track-map.test.js`, which guards this extraction, and `client.test.js` and `telemetry-store.test.js`, which Task 3 should have extended. Run `npm install` first; `node_modules` is not in the checkout.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/track-projection.test.js`:

```js
import { describe, expect, it } from 'vitest'

import { project, pointAt, spanIndices } from '../src/components/track-projection.js'

const SQUARE = { x: [0, 100, 100, 0], y: [0, 0, 100, 100] }

describe('project', () => {
  it('uses one scale for both axes, so a circuit keeps its shape', () => {
    const wide = { x: [0, 200, 0], y: [0, 0, 50] }
    const frame = project(wide, 560)
    // A separate scale per axis would stretch this to fill the box.
    expect(frame.scale).toBeCloseTo((560 - 44) / 200, 6)
  })

  it('centres what it draws inside the box', () => {
    const frame = project(SQUARE, 560)
    expect(frame.offsetX).toBeCloseTo(frame.offsetY, 6)
  })

  it('survives a degenerate extent rather than dividing by zero', () => {
    const frame = project({ x: [5, 5], y: [7, 7] }, 560)
    expect(Number.isFinite(frame.scale)).toBe(true)
  })
})

describe('pointAt', () => {
  it('flips y, because SVG grows downward and a circuit would be mirrored', () => {
    const frame = project(SQUARE, 560)
    const bottom = pointAt(SQUARE, frame, 560, 0)   // y = 0, the lowest point
    const top = pointAt(SQUARE, frame, 560, 2)      // y = 100, the highest
    expect(Number(bottom.split(',')[1])).toBeGreaterThan(Number(top.split(',')[1]))
  })
})

describe('spanIndices', () => {
  it('maps a plain range onto the drawn points', () => {
    // 1000 m of track over 100 points: 10 m each.
    expect(spanIndices(200, 400, 1000, 100)).toEqual([[20, 40]])
  })

  it('splits a span that holds the start/finish line into two', () => {
    // A block from 900 m round to 100 m is the end of the lap and its start.
    expect(spanIndices(900, 100, 1000, 100)).toEqual([[90, 100], [0, 10]])
  })

  it('never returns an empty range, which would draw nothing at all', () => {
    // Shorter than the spacing between two drawn points.
    const [[first, last]] = spanIndices(200, 201, 1000, 100)
    expect(last).toBeGreaterThan(first)
  })

  it('stays inside the array it will be used to index', () => {
    for (const [first, last] of spanIndices(995, 5, 1000, 100)) {
      expect(first).toBeGreaterThanOrEqual(0)
      expect(last).toBeLessThanOrEqual(100)
    }
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/`: `npm install` then `npm test`
Expected: FAIL — cannot resolve `../src/components/track-projection.js`.

- [ ] **Step 3: Write the module**

Create `frontend/src/components/track-projection.js`:

```js
/**
 * Putting a measured circuit into a square box.
 *
 * Lifted out of TrackMap so BlockMap can draw the same circuit the same way.
 * Two components each with their own copy of this would drift, and the drift
 * would look like the two maps disagreeing about the track.
 */

const PADDING = 22

/** Bounds and scale for `map`, drawn into a `size` by `size` box. */
export function project(map, size) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (let i = 0; i < map.x.length; i += 1) {
    if (map.x[i] < minX) minX = map.x[i]
    if (map.x[i] > maxX) maxX = map.x[i]
    if (map.y[i] < minY) minY = map.y[i]
    if (map.y[i] > maxY) maxY = map.y[i]
  }
  const width = maxX - minX || 1
  const height = maxY - minY || 1
  // One scale for both axes: a circuit stretched to fill a box is no longer
  // the shape of that circuit. Taking the larger extent also keeps it inside
  // the box when the circuit is taller than it is wide.
  const scale = (size - 2 * PADDING) / Math.max(width, height)
  return {
    minX, minY, scale,
    offsetX: PADDING + (size - 2 * PADDING - width * scale) / 2,
    offsetY: PADDING + (size - 2 * PADDING - height * scale) / 2,
  }
}

/** One point as `"x,y"`, ready for an SVG path. */
export function pointAt(map, frame, size, index) {
  const px = frame.offsetX + (map.x[index] - frame.minX) * frame.scale
  // SVG's y grows downward; drawn without flipping, every circuit is mirrored.
  const py = size - (frame.offsetY + (map.y[index] - frame.minY) * frame.scale)
  return `${px.toFixed(1)},${py.toFixed(1)}`
}

/**
 * A distance range as index ranges into the drawn points.
 *
 * Comes back as two ranges when the span holds the start/finish line, which
 * is `from_m > to_m` - the run to the line and the run away from it. Read as
 * one range it is empty and the block vanishes from the map with nothing
 * saying so. This is the same split `api.corner_spans` makes server-side, for
 * the same reason.
 */
export function spanIndices(fromM, toM, trackLengthM, pointCount) {
  const perPoint = trackLengthM / pointCount
  const edges = fromM <= toM
    ? [[fromM, toM]]
    : [[fromM, trackLengthM], [0, toM]]
  return edges.map(([first_m, last_m]) => {
    const first = Math.min(Math.max(0, Math.round(first_m / perPoint)), pointCount - 1)
    const last = Math.min(Math.max(Math.round(last_m / perPoint), first + 1), pointCount)
    return [first, last]
  })
}
```

- [ ] **Step 4: Run to verify it passes**

Run from `frontend/`: `npm test`
Expected: PASS, all of it.

- [ ] **Step 5: Make TrackMap use it**

In `frontend/src/components/TrackMap.vue`, add to the imports:

```js
import { pointAt, project } from './track-projection.js'
```

Replace the `PADDING` constant and the `frame` computed (lines 34–60) with:

```js
const frame = computed(() => project(props.map, props.size))
```

and replace `toPoint` (lines 62–68) with:

```js
function toPoint(index) {
  return pointAt(props.map, frame.value, props.size, index)
}
```

Leave everything else — `pathFrom`, `outline`, `cornerPaths`, `zonePath`, `brakingPaths` — untouched. This is extraction, not redesign.

- [ ] **Step 6: Verify TrackMap still renders**

Run from `frontend/`: `npm run build`
Expected: build succeeds with no unused-import or undefined-variable errors. `PADDING` and `NOISE_S`: `PADDING` moves out, `NOISE_S` stays — deleting it would break `cornerPaths`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/track-projection.js frontend/tests/track-projection.test.js frontend/src/components/TrackMap.vue && git commit -m "Draw one circuit one way, from one place"
```

---

### Task 5: The soundness rule, as a tested function

**Files:**
- Create: `frontend/src/components/ideal-headline.js`
- Create: `frontend/tests/ideal-headline.test.js`

**Interfaces:**
- Produces: `headlineFor(ideal) -> { idealS, bestS, gainS, qualified, worstSeam }`
  - `qualified` is `true` when the ideal time is not supported by the laps.
  - `worstSeam` is the seam with the largest spread among the unsound ones, or `null`.

This is a pure function and not a template branch on purpose. It is the one rule this whole feature turns on, and a conditional that suppresses a number is exactly the kind of line that later reads as dead weight and gets tidied away. In a tested function, tidying it away turns something red.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/ideal-headline.test.js`:

```js
import { describe, expect, it } from 'vitest'

import { headlineFor } from '../src/components/ideal-headline.js'

const SOUND = {
  ideal_s: 101.212, best_lap_s: 101.271, gain_s: 0.059, sound: true,
  seams: [
    { at_m: 0, speed_spread_kmh: 3.1, sound: true },
    { at_m: 900, speed_spread_kmh: 1.6, sound: true },
  ],
}

/** Monza, the largest gain in the sampled corpus - and 20 km/h at one join. */
const UNSOUND = {
  ideal_s: 99.5, best_lap_s: 100.936, gain_s: 1.436, sound: false,
  seams: [
    { at_m: 0, speed_spread_kmh: 2.0, sound: true },
    { at_m: 1500, speed_spread_kmh: 20.0, sound: false },
    { at_m: 3000, speed_spread_kmh: 6.2, sound: false },
  ],
}

describe('headlineFor', () => {
  it('passes the numbers through when every join holds', () => {
    const headline = headlineFor(SOUND)
    expect(headline.qualified).toBe(false)
    expect(headline.gainS).toBeCloseTo(0.059, 6)
    expect(headline.worstSeam).toBeNull()
  })

  it('marks the headline unsupported when one join does not hold', () => {
    // core/blocks.py: `sound` is an all() and not a count, because one join
    // that does not hold makes the whole time a claim the laps do not support.
    expect(headlineFor(UNSOUND).qualified).toBe(true)
  })

  it('names the worst join, not merely the first bad one', () => {
    const headline = headlineFor(UNSOUND)
    expect(headline.worstSeam.speed_spread_kmh).toBe(20.0)
    expect(headline.worstSeam.at_m).toBe(1500)
  })

  it('still carries the numbers, so the table can show them', () => {
    // Qualified, not hidden. A driver who wants the figure can have it.
    const headline = headlineFor(UNSOUND)
    expect(headline.gainS).toBeCloseTo(1.436, 6)
    expect(headline.idealS).toBeCloseTo(99.5, 6)
  })

  it('is safe before anything has loaded', () => {
    expect(headlineFor(null).qualified).toBe(false)
    expect(headlineFor(null).idealS).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/`: `npm test`
Expected: FAIL — cannot resolve `ideal-headline.js`.

- [ ] **Step 3: Write the module**

```js
/**
 * What the headline may claim about an ideal lap.
 *
 * `IdealLap.sound` is an `all()` and not a count, and core/blocks.py says why:
 * one join that does not hold makes the whole time a claim the laps do not
 * support. So an unsound ideal lap does not get to put its gain in large type
 * looking like a lap that was nearly driven.
 *
 * Qualified, not hidden. The numbers travel on and the block table shows them.
 * A driver who wants the figure can have it; what they must not get is the
 * figure without the doubt attached.
 *
 * A function rather than a branch in the template because this is the rule the
 * feature turns on, and it is tested so that removing it goes red.
 */

export function headlineFor(ideal) {
  if (!ideal) {
    return { idealS: null, bestS: null, gainS: null, qualified: false, worstSeam: null }
  }
  const bad = (ideal.seams ?? []).filter((seam) => !seam.sound)
  // The worst one, not the first: the first is wherever the lap happens to
  // start, and the driver needs the join that costs the claim the most.
  const worstSeam = bad.length
    ? bad.reduce((a, b) => (b.speed_spread_kmh > a.speed_spread_kmh ? b : a))
    : null
  return {
    idealS: ideal.ideal_s,
    bestS: ideal.best_lap_s,
    gainS: ideal.gain_s,
    qualified: !ideal.sound,
    worstSeam,
  }
}
```

- [ ] **Step 4: Run to verify it passes**

Run from `frontend/`: `npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ideal-headline.js frontend/tests/ideal-headline.test.js && git commit -m "Let a bad join take the headline away from the time it cannot support"
```

---

### Task 6: BlockMap

**Files:**
- Create: `frontend/src/components/BlockMap.vue`

**Interfaces:**
- Consumes: `project`, `pointAt`, `spanIndices` from Task 4.
- Props: `map` (the `/map` payload: `x`, `y`, `track_length_m`, `track`), `blocks` (from the ideal payload), `seams`, `selected` (block index or null), `size` (default 560).
- Emits: `select` with the block object.
- Produces: the component Task 7 mounts.

Colour here is categorical — which lap a block came from — which is why this is not a mode on `TrackMap`. That component's header commits to colour carrying polarity and to answering one question at a time.

Provenance colour is not enough on its own for a CVD reader, so each block also carries its lap number as a label on the map, the same way `TrackMap` gives corners a second channel in stroke width.

- [ ] **Step 1: Write the component**

```vue
<script setup>
/**
 * The circuit, split into the blocks an ideal lap was assembled from.
 *
 * Colour is categorical here - which lap this block was taken from - and that
 * is exactly why this is not a mode on TrackMap, whose header commits to
 * colour meaning time lost against time gained. Two meanings on one stroke is
 * the thing it says it will not do.
 *
 * Colour alone would fail a CVD reader, so each block is labelled with the lap
 * it came from. That label is the answer; the colour only groups.
 *
 * Seams are drawn only where they do not hold. A mark on every join would make
 * the mark mean "join" rather than "look at this one".
 */
import { computed } from 'vue'

import { pointAt, project, spanIndices } from './track-projection.js'

const props = defineProps({
  map: { type: Object, required: true },
  blocks: { type: Array, default: () => [] },
  seams: { type: Array, default: () => [] },
  selected: { type: Number, default: null },
  size: { type: Number, default: 560 },
})
const emit = defineEmits(['select'])

const frame = computed(() => project(props.map, props.size))

function toPoint(index) {
  return pointAt(props.map, frame.value, props.size, index)
}

function pathFrom(first, last) {
  const points = []
  for (let i = first; i < last; i += 1) points.push(toPoint(i))
  return points.length ? `M${points.join('L')}` : ''
}

const outline = computed(() => `${pathFrom(0, props.map.x.length)}Z`)

/** Lap number -> a slot 0..n, so the palette is stable across re-renders. */
const lapSlots = computed(() => {
  const seen = [...new Set(props.blocks.map((b) => b.lap_number))].sort((a, b) => a - b)
  return Object.fromEntries(seen.map((lap, at) => [lap, at % 6]))
})

const blockPaths = computed(() =>
  props.blocks.map((block) => {
    const ranges = spanIndices(
      block.start_m, block.end_m, props.map.track_length_m, props.map.x.length,
    )
    const [first, last] = ranges[0]
    return {
      ...block,
      slot: lapSlots.value[block.lap_number] ?? 0,
      d: ranges.map(([a, b]) => pathFrom(a, b)).join(' '),
      label: toPoint(Math.floor((first + last) / 2)).split(','),
    }
  }),
)

const badSeams = computed(() =>
  props.seams
    .filter((seam) => !seam.sound)
    .map((seam) => {
      const [[first]] = spanIndices(
        seam.at_m, seam.at_m, props.map.track_length_m, props.map.x.length,
      )
      return { ...seam, at: toPoint(first).split(',') }
    }),
)
</script>

<template>
  <svg
    :viewBox="`0 0 ${props.size} ${props.size}`"
    class="map"
    role="img"
    :aria-label="`${props.map.track} — ${props.blocks.length} blocks`"
  >
    <path :d="outline" class="outline" />

    <path
      v-for="block in blockPaths"
      :key="block.index"
      :d="block.d"
      class="block"
      :class="[`slot-${block.slot}`, { selected: block.index === props.selected }]"
      @mouseenter="emit('select', block)"
      @click="emit('select', block)"
    >
      <title>{{ block.name }} — lap {{ block.lap_number }}, {{ block.time_s.toFixed(3) }} s</title>
    </path>

    <text
      v-for="block in blockPaths"
      :key="`label-${block.index}`"
      :x="block.label[0]"
      :y="block.label[1]"
      class="label"
    >{{ block.lap_number }}</text>

    <g v-for="(seam, at) in badSeams" :key="`seam-${at}`">
      <circle :cx="seam.at[0]" :cy="seam.at[1]" r="6" class="seam-bad">
        <title>
          the two laps were {{ seam.speed_spread_kmh.toFixed(1) }} km/h apart here
        </title>
      </circle>
    </g>
  </svg>
</template>

<style scoped>
.map { width: 100%; height: auto; }
.outline { fill: none; stroke: var(--line); stroke-width: 1.5; }

.block {
  fill: none;
  stroke-width: 5;
  stroke-linecap: round;
  cursor: pointer;
  transition: stroke-width 0.12s ease;
}
.block.selected { stroke-width: 9; }

/* Grouping only - the lap number on the map is what actually says which. */
.slot-0 { stroke: #4c9be8; }
.slot-1 { stroke: #e8a33d; }
.slot-2 { stroke: #57c78a; }
.slot-3 { stroke: #b07fe0; }
.slot-4 { stroke: #e06c9f; }
.slot-5 { stroke: #46c4c4; }

.label {
  font-size: 0.7rem;
  fill: var(--ink);
  paint-order: stroke;
  stroke: var(--bg);
  stroke-width: 3;
  text-anchor: middle;
  dominant-baseline: middle;
  pointer-events: none;
}

.seam-bad { fill: none; stroke: var(--loss); stroke-width: 2.5; }
</style>
```

- [ ] **Step 2: Verify it compiles**

Run from `frontend/`: `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BlockMap.vue && git commit -m "Draw which lap each part of the ideal came from"
```

---

### Task 7: The page

**Files:**
- Create: `frontend/src/views/IdealView.vue`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/App.vue` (the navigation)

**Interfaces:**
- Consumes: `store.loadSessions`, `store.loadIdeal`, `store.client.map`, `headlineFor`, `BlockMap`.

- [ ] **Step 1: Write the view**

```vue
<script setup>
/**
 * What the best lap in one recording could have been.
 *
 * One recording, because that is what ideal_lap requires: two recordings mean
 * two fuel loads and two tyre states, and a block time from one is not
 * comparable to a block time from the other.
 *
 * Only recordings with two or more usable laps are offered. Of 60 recordings
 * sampled from the corpus, 26 have fewer - so offering all of them would be
 * an invitation into an error message more often than into an answer.
 */
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'

import BlockMap from '../components/BlockMap.vue'
import { headlineFor } from '../components/ideal-headline.js'
import { useTelemetryStore } from '../stores/telemetry.js'

const store = useTelemetryStore()
const { sessions, ideal, loading, error } = storeToRefs(store)

const chosen = ref(null)
const selected = ref(null)
const trackMap = shallowRef(null)

/** Only what can answer. A recording with one usable lap has nothing to
 *  choose between, and the server would refuse it. */
const usable = computed(() =>
  sessions.value.filter((s) => !s.error && (s.clean_laps ?? 0) >= 2),
)

const headline = computed(() => headlineFor(ideal.value))

function lapTime(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${(seconds - minutes * 60).toFixed(3).padStart(6, '0')}`
}

onMounted(() => store.loadSessions())

watch(chosen, async (name) => {
  selected.value = null
  trackMap.value = null
  if (!name) return
  trackMap.value = await store.client.map(name).catch(() => null)
  await store.loadIdeal(name)
})
</script>

<template>
  <section class="ideal">
    <header class="picker">
      <h1>The lap you had in you</h1>
      <select v-model="chosen" aria-label="recording">
        <option :value="null">choose a recording…</option>
        <option v-for="s in usable" :key="s.name" :value="s.name">
          {{ s.track }} — {{ s.session_type }} — {{ s.recorded_at }}
          ({{ s.clean_laps }} usable)
        </option>
      </select>
    </header>

    <p v-if="error" class="card failure">{{ error }}</p>
    <p v-else-if="loading" class="card quiet">reading…</p>

    <section v-else-if="!chosen" class="card empty">
      <p class="quiet">
        Built from the usable laps of one recording, block by block. A block is
        a run of corners that has to be taken from one lap or not at all — a
        chicane is one act, and taking half of it from another lap would be a
        target nobody can drive. Only recordings with two or more usable laps
        are listed; the rest have nothing to choose between.
      </p>
    </section>

    <template v-else-if="ideal">
      <section class="card headline" :class="{ qualified: headline.qualified }">
        <div class="figure">
          <span class="label">ideal</span>
          <strong>{{ lapTime(headline.idealS) }}</strong>
        </div>
        <div class="figure">
          <span class="label">best driven — lap {{ ideal.best_lap_number }}</span>
          <strong>{{ lapTime(headline.bestS) }}</strong>
        </div>
        <div v-if="!headline.qualified" class="figure gain">
          <span class="label">left on the table</span>
          <strong>{{ headline.gainS.toFixed(3) }} s</strong>
        </div>
        <p v-else class="doubt">
          This time is not supported by these laps. At
          {{ headline.worstSeam.at_m.toFixed(0) }} m the two laps being joined
          were {{ headline.worstSeam.speed_spread_kmh.toFixed(1) }} km/h apart
          — more than the {{ ideal.seam_limit_kmh }} km/h a join may differ by —
          so the block after it was driven from an entry this lap never
          delivers. The figure is {{ headline.gainS.toFixed(3) }} s; it is not
          a lap that was nearly driven.
        </p>
      </section>

      <div class="body">
        <section class="card">
          <header><h2>Where each part came from</h2></header>
          <BlockMap
            v-if="trackMap"
            :map="trackMap"
            :blocks="ideal.blocks"
            :seams="ideal.seams"
            :selected="selected"
            @select="(b) => (selected = b.index)"
          />
          <p v-else class="quiet">no reference line for this recording</p>
        </section>

        <section class="card">
          <header>
            <h2>Block by block</h2>
            <span class="note">driven order</span>
          </header>
          <table class="blocks">
            <thead>
              <tr>
                <th>block</th><th class="num">from lap</th>
                <th class="num">time</th><th class="num">gain</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="block in ideal.blocks"
                :key="block.index"
                :class="{ current: block.index === selected }"
                @mouseenter="selected = block.index"
              >
                <td>{{ block.name }}</td>
                <td class="num">{{ block.lap_number }}</td>
                <td class="num">{{ block.time_s.toFixed(3) }}</td>
                <td class="num" :class="{ gained: block.gain_s > 0 }">
                  {{ block.gain_s > 0 ? `−${block.gain_s.toFixed(3)}` : '—' }}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ideal { display: flex; flex-direction: column; gap: 1rem; }
.picker { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.picker select { max-width: 34rem; }

.headline { display: flex; gap: 2.5rem; flex-wrap: wrap; align-items: baseline; }
.headline.qualified { border-left: 3px solid var(--loss); }
.figure { display: flex; flex-direction: column; gap: 0.15rem; }
.figure .label { color: var(--muted); font-size: 0.8rem; }
.figure strong { font-size: 1.6rem; font-variant-numeric: tabular-nums; }
.gain strong { color: var(--gain); }
.doubt { flex: 1 1 22rem; max-width: 60ch; color: var(--loss); margin: 0; }

.body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1rem; }
.body > * { min-width: 0; }

.blocks { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.blocks th, .blocks td { padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.gained { color: var(--gain); }
tr.current { background: var(--line); }
.quiet { color: var(--muted); }
.failure { color: var(--loss); font-weight: 600; }
.empty p { max-width: 60ch; }

@media (max-width: 1200px) { .body { grid-template-columns: minmax(0, 1fr); } }
</style>
```

- [ ] **Step 2: Add the route**

In `frontend/src/router.js`:

```js
import IdealView from './views/IdealView.vue'
```

and in `routes`, after the compare entry:

```js
  { path: '/ideal', name: 'ideal', component: IdealView },
```

- [ ] **Step 3: Add the navigation link**

In `frontend/src/App.vue`, in the `<nav>` at line 14, between the two existing links:

```html
      <nav>
        <router-link :to="{ name: 'compare' }">Compare</router-link>
        <router-link :to="{ name: 'ideal' }">Ideal lap</router-link>
        <router-link :to="{ name: 'sessions' }">Recordings</router-link>
      </nav>
```

Between them, not after: it belongs with Compare as a reading of laps, where Recordings is the inventory. No style change — `nav a` already covers it, including the active state.

- [ ] **Step 4: Verify in the browser**

Start the API and the dev server, then check the page actually renders rather than assuming it does:

```bash
.venv/Scripts/python.exe -m lmu_telemetry.api --port 8000
```

Use `preview_start` with `.claude/launch.json` for the frontend, navigate to `/ideal`, and:
- pick a recording, confirm the map draws and every block carries a lap number;
- check `read_console_messages` for errors — an empty console is part of the deliverable;
- find a recording with an unsound seam and confirm the headline shows the doubt instead of the gain. From the corpus sample, `Autodromo Nazionale Monza_R_2026-03-22T18_50_09Z.duckdb` is one (20.0 km/h at one join); `monza_r_extra_dist_reset.duckdb` may or may not be.
- take a screenshot of both headline states.

- [ ] **Step 5: Run everything**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q` and, from `frontend/`, `npm test && npm run build`
Expected: Python as in Task 1 Step 5 (only the known `np.trapz` failure). Frontend green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/IdealView.vue frontend/src/router.js frontend/src/App.vue && git commit -m "Give the ideal lap a page, and its doubts equal billing"
```

---

## Self-review

**Spec coverage.** Endpoint and payload: Task 1. `seam_limit_kmh` sent, not repeated: Task 1, asserted in `test_the_seam_limit_is_sent_rather_than_left_to_the_client`. Both refusals with reasons: Task 2. Route `/ideal` and view: Task 7. Picker offering only recordings with ≥2 clean laps: Task 7, `usable`. `BlockMap` not a `TrackMap` mode: Task 6. `track-projection.js` extraction: Task 4. Headline soundness rule: Task 5, rendered in Task 7. Block table in driven order: Task 7. Tests named in the spec: Tasks 1, 2, 4, 5. Out-of-scope items are absent — no lap picker, no cache, no cross-recording ideal, no overlay change.

**Type consistency.** `headlineFor` returns `idealS`/`bestS`/`gainS`/`qualified`/`worstSeam` in Task 5 and is read under those names in Task 7. `spanIndices(fromM, toM, trackLengthM, pointCount)` is defined in Task 4 and called with that arity in Task 6. `client.ideal(name)` in Task 3 is called by `store.loadIdeal` in Task 3 and reached as `ideal` in Task 7. Block fields (`index`, `name`, `corners`, `start_m`, `end_m`, `wraps`, `lap_number`, `time_s`, `gain_s`) are emitted in Task 1 and read in Tasks 6 and 7.

**No placeholders.** Every code step carries the code. `App.vue`'s nav was read and quoted rather than described, which was the one step that had been left as prose.
