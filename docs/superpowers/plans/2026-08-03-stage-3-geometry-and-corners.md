# LMU Telemetry Rework — Stufe 3: Geometrie, Referenzmodell, Kurven

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pro Strecke **einmal** ein Kurvenmodell aus der gemittelten Ideallinie aller sauberen Runden bestimmen und cachen, sodass jede Runde jedes Fahrers exakt dieselben Kurvengrenzen benutzt — damit sind Vergleiche per Konstruktion konsistent.

**Architecture:** Vier neue Module in `lmu_telemetry/core/`. `geometry.py` rechnet GPS in lokale Meter, resampelt auf ein Distanzraster und liefert Krümmung und Rundenschluss. `corners.py` erkennt Kurven auf einer Krümmungskurve. `track_model.py` baut daraus je Streckenidentität ein Modell und cacht es als JSON. `naming.py` legt kuratierte Kurvennamen darüber. Alles baut auf der fertigen Stufe-1+2-API auf; `Session` bekommt dafür einen Kanalzugriff pro Runde.

**Tech Stack:** Python 3.11, numpy, scipy 1.11 (`scipy.signal.find_peaks`), duckdb 1.5, pytest 7.4.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-lmu-telemetry-rework-design.md`
- Python-Mindestversion **3.11**. DuckDB-Zugriffe ausschließlich read-only.
- **Keine Heuristik für Größen, die in der Datei stehen.** Fehlt eine Größe, wird das explizit ausgewiesen — nie ein Ersatzwert.
- Einheiten kommen aus `channelsList`, nie aus beobachteten Wertebereichen.
- **Kurven werden aus der Geometrie bestimmt, nie aus dem Lenkwinkel.** Der Lenkwinkel ist fahrerabhängig und einheiteninkonsistent; Krümmung ist eine Eigenschaft der Strecke.
- **Ein Kurvenmodell gilt pro Streckenidentität, nicht pro Runde.** Alle Runden aller Fahrer einer Strecke teilen dieselbe Kurvenliste.
- Tests, die den 637-MB-Bestand brauchen, tragen `@pytest.mark.corpus`. Alles andere muss unter `pytest -m "not corpus"` ausgewählt bleiben.
- `backend/` bleibt in dieser Stufe unangetastet.

### Feste Parameter (empirisch bestimmt, siehe Spec §3.3)

Diese Werte sind gemessen, nicht geschätzt. Sie gehören als benannte Konstanten in den Code, nicht als Zahlenliterale in Funktionsrümpfe.

| Konstante | Wert | Bedeutung |
|---|---|---|
| `GRID_STEP_M` | `2.0` | Distanzraster des Referenzmodells |
| `LINE_SMOOTH_WINDOW` | `15` | Glättung der Linie (15 × 2 m = 30 m) |
| `CURVATURE_SMOOTH_WINDOW` | `8` | Glättung der Krümmung |
| `CORNER_MAX_RADIUS_M` | `400.0` | enger als das ⇒ Kurve |
| `CORNER_MIN_HEADING_DEG` | `20.0` | Mindest-Richtungsänderung |
| `CORNER_MIN_LENGTH_M` | `25.0` | Mindestlänge |
| `MERGE_GAP_M` | `40.0` | Lücke, unter der gleichsinnige Bereiche verschmelzen |
| `SPLIT_HEADING_GATE_DEG` | `180.0` | nur Blöcke darüber gelten als verschmolzen |
| `SPLIT_PROMINENCE_FRAC` | `0.05` | Mindestprominenz eines Krümmungspeaks |
| `SPLIT_MIN_PART_M` | `40.0` | Mindestlänge eines Teilstücks |
| `SPLIT_MAX_DEPTH` | `4` | Rekursionsgrenze des Splits |
| `CLOSURE_MIN_DEG` / `CLOSURE_MAX_DEG` | `330.0` / `390.0` | Rundenschluss einer sauberen Runde |

**Warum der Heading-Gate und nicht Krümmungsprominenz:** ein rein prominenzbasierter Split zerlegt Monzas Curva Grande (zwei flache Hälften, R ≈ 260 m, zusammen 66°) fälschlich in zwei Kurven. Über die gesamte Richtungsänderung zu gaten lässt sie intakt und trennt trotzdem Algarves verschmolzene Blöcke (278°, 243°). Mit dem Gate liefert Monza über **jede** getestete Parameterkombination 11 Kurven.

---

### Task 1: Kanalzugriff pro Runde

Stufe 3 braucht überall „Kanal X über Runde N". Diese Logik existiert bisher nur inline in `_distance_covered`. Ohne sie würde sie in jedem folgenden Task kopiert.

**Files:**
- Modify: `lmu_telemetry/io/duckdb_source.py` — Kanal-Cache
- Modify: `lmu_telemetry/core/session.py` — `lap_channel`
- Test: `tests/unit/test_lap_channel.py`

**Interfaces:**
- Consumes: `TelemetryFile`, `TimeBase`, `Lap` (Stufe 1+2)
- Produces:
  - `Session.lap_channel(lap: Lap, name: str) -> np.ndarray` — der Kanalausschnitt dieser Runde, einheitennormalisiert
  - `TelemetryFile.channel()` cacht das normalisierte Array pro Kanalname

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lap_channel.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.session import Session


def test_lap_channel_length_matches_the_lap_duration(monza_q_file):
    """Lap Dist runs at 10 Hz, so a 111 s lap yields about 1110 samples."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        dist = s.lap_channel(lap, "Lap Dist")
    assert len(dist) == pytest.approx(1110, abs=3)


def test_lap_channel_covers_one_track_length(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        dist = s.lap_channel(lap, "Lap Dist")
    assert dist.min() < 50.0
    assert dist.max() > 5700.0


def test_lap_channel_is_unit_normalised(monza_q_file):
    """Throttle Pos is declared in percent; the slice must be 0..1 like the whole channel."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        thr = s.lap_channel(lap, "Throttle Pos")
    assert 0.0 <= thr.min()
    assert thr.max() <= 1.0
    assert thr.max() > 0.9  # the driver did use full throttle on a qualifying lap


def test_channel_array_is_cached(monza_q_file):
    """The same array object comes back, so repeated reads cost nothing."""
    with Session.open(monza_q_file) as s:
        a = s.file.channel("Lap Dist")
        b = s.file.channel("Lap Dist")
    assert a is b


def test_cached_channel_cannot_be_mutated_by_a_caller(monza_q_file):
    """A shared cached array must not be writable, or one caller corrupts another."""
    with Session.open(monza_q_file) as s:
        a = s.file.channel("Lap Dist")
        with pytest.raises(ValueError):
            a[0] = 12345.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_lap_channel.py -v`
Expected: FAIL — `AttributeError: 'Session' object has no attribute 'lap_channel'`

- [ ] **Step 3: Add the channel cache**

In `lmu_telemetry/io/duckdb_source.py`, add `self._channel_cache: dict[str, np.ndarray] = {}` to `__init__`, and replace the body of `channel` with:

```python
    def channel(self, name: str) -> np.ndarray:
        """Channel values converted into canonical units.

        Cached and read-only: the same array is handed to every caller, so it
        must not be writable - one caller mutating it would corrupt the next.
        """
        cached = self._channel_cache.get(name)
        if cached is not None:
            return cached
        spec = self.channels.require(name)
        values = normalise(self.raw_channel(name), spec)
        values.flags.writeable = False
        self._channel_cache[name] = values
        return values
```

- [ ] **Step 4: Add `lap_channel`**

In `lmu_telemetry/core/session.py`, add:

```python
    def lap_channel(self, lap: Lap, name: str) -> np.ndarray:
        """The slice of *name* covering *lap*, in canonical units.

        The channel carries no timestamps, so the lap's time window is mapped
        onto sample indices via the channel's declared frequency.
        """
        spec = self._file.channels.require(name)
        values = self._file.channel(name)
        i0 = min(self._timebase.index_at(lap.t_start, spec.frequency_hz), len(values))
        i1 = min(self._timebase.index_at(lap.t_end, spec.frequency_hz), len(values))
        return values[i0:i1]
```

Add `from .laps import Lap, segment_laps` to the existing import if `Lap` is not already imported.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_lap_channel.py -v`
Expected: PASS — 5 passed

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS — no regressions

- [ ] **Step 7: Commit**

```bash
git add lmu_telemetry/io/duckdb_source.py lmu_telemetry/core/session.py tests/unit/test_lap_channel.py
git commit -m "feat: add per-lap channel access and cache channel arrays

Every Stage 3 module needs 'channel X over lap N'; that logic existed only
inline in _distance_covered. Cached arrays are marked read-only so one
caller cannot corrupt another."
```

---

### Task 2: Projektion und Distanzraster

**Files:**
- Create: `lmu_telemetry/core/geometry.py`
- Test: `tests/unit/test_geometry_projection.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `GRID_STEP_M: float = 2.0`
  - `project_enu(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]` — Grad → lokale Meter `(x, y)`, zentriert auf den Mittelwert
  - `resample_to_grid(distance: np.ndarray, values: np.ndarray, track_length_m: float, step_m: float = GRID_STEP_M) -> np.ndarray`
  - `grid_for(track_length_m: float, step_m: float = GRID_STEP_M) -> np.ndarray`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_geometry_projection.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    grid_for,
    project_enu,
    resample_to_grid,
)


def test_projection_turns_degrees_into_metres():
    """One degree of latitude is about 111.3 km anywhere."""
    lat = np.array([60.0, 60.001])
    lon = np.array([0.0, 0.0])
    x, y = project_enu(lat, lon)
    assert (y[1] - y[0]) == pytest.approx(111.32, abs=0.5)
    assert x[1] == pytest.approx(x[0], abs=1e-6)


def test_longitude_is_scaled_by_the_cosine_of_latitude():
    """At 60 deg north a degree of longitude is half a degree of latitude."""
    lat = np.array([60.0, 60.0])
    lon = np.array([0.0, 0.001])
    x, y = project_enu(lat, lon)
    assert (x[1] - x[0]) == pytest.approx(111.32 * 0.5, abs=0.5)


def test_projection_is_centred_on_the_data():
    lat = np.array([59.99, 60.0, 60.01])
    lon = np.array([-0.01, 0.0, 0.01])
    x, y = project_enu(lat, lon)
    assert np.mean(x) == pytest.approx(0.0, abs=1e-6)
    assert np.mean(y) == pytest.approx(0.0, abs=1e-6)


def test_grid_spans_the_track_at_the_declared_step():
    g = grid_for(1000.0)
    assert g[0] == 0.0
    assert len(g) == 500
    assert g[1] - g[0] == GRID_STEP_M


def test_resampling_is_linear_between_samples():
    d = np.array([0.0, 100.0, 200.0])
    v = np.array([0.0, 10.0, 20.0])
    out = resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)
    assert np.allclose(out, [0.0, 5.0, 10.0, 15.0])


def test_resampling_rejects_unsorted_distance():
    """Out-of-order distance would silently produce nonsense."""
    d = np.array([0.0, 200.0, 100.0])
    v = np.array([0.0, 20.0, 10.0])
    with pytest.raises(ValueError):
        resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_geometry_projection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.geometry'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/geometry.py`:

```python
"""Track geometry: projection, distance resampling, curvature, closure.

Corners are a property of the track, so they are derived from where the track
goes - not from the steering trace, which depends on the driver and whose unit
differs between files.

LMU reports position as latitude/longitude around a synthetic origin rather
than the circuit's real coordinates, so these values are only meaningful as a
local shape. That is all this module needs them for.
"""

from __future__ import annotations

import numpy as np

#: Distance resolution of the reference model, in metres.
GRID_STEP_M = 2.0

_EARTH_RADIUS_M = 6378137.0


def project_enu(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project degrees onto local metres, centred on the mean position."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    lat0 = float(np.mean(lat))
    x = np.radians(lon - float(np.mean(lon))) * _EARTH_RADIUS_M * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * _EARTH_RADIUS_M
    return x, y


def grid_for(track_length_m: float, step_m: float = GRID_STEP_M) -> np.ndarray:
    """The common distance grid every lap of a track is resampled onto."""
    if track_length_m <= 0:
        raise ValueError(f"track length must be positive, got {track_length_m}")
    if step_m <= 0:
        raise ValueError(f"step must be positive, got {step_m}")
    return np.arange(0.0, track_length_m, step_m)


def resample_to_grid(
    distance: np.ndarray,
    values: np.ndarray,
    track_length_m: float,
    step_m: float = GRID_STEP_M,
) -> np.ndarray:
    """Resample *values* from *distance* onto the track's common grid."""
    distance = np.asarray(distance, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if len(distance) != len(values):
        raise ValueError(
            f"distance and values differ in length: {len(distance)} vs {len(values)}"
        )
    if len(distance) < 2:
        raise ValueError("need at least two samples to resample")
    if np.any(np.diff(distance) < 0):
        raise ValueError("distance must be non-decreasing")
    return np.interp(grid_for(track_length_m, step_m), distance, values)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_geometry_projection.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/geometry.py tests/unit/test_geometry_projection.py
git commit -m "feat: add local projection and distance-grid resampling"
```

---

### Task 3: Krümmung und Rundenschluss

Diese Mathematik wird gegen analytisch bekannte Formen geprüft, nicht gegen Telemetrie — ein Kreis mit Radius R hat überall κ = 1/R und schließt mit exakt 360°.

**Files:**
- Modify: `lmu_telemetry/core/geometry.py`
- Test: `tests/unit/test_geometry_curvature.py`

**Interfaces:**
- Consumes: `GRID_STEP_M`, `grid_for` (Task 2)
- Produces:
  - `LINE_SMOOTH_WINDOW: int = 15`, `CURVATURE_SMOOTH_WINDOW: int = 8`
  - `smooth_closed(values: np.ndarray, window: int) -> np.ndarray` — Glättung mit Wrap-around, weil eine Runde geschlossen ist
  - `curvature(x: np.ndarray, y: np.ndarray, step_m: float = GRID_STEP_M) -> np.ndarray` — signiertes κ in 1/m, positiv = Linkskurve
  - `heading_change_deg(kappa: np.ndarray, grid: np.ndarray) -> float` — `|∮κ ds|` in Grad

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_geometry_curvature.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    curvature,
    grid_for,
    heading_change_deg,
    smooth_closed,
)


def _circle(radius_m: float, step_m: float = GRID_STEP_M):
    """A closed circle sampled at *step_m* along its circumference."""
    circumference = 2.0 * np.pi * radius_m
    grid = grid_for(circumference, step_m)
    theta = grid / radius_m
    return np.cos(theta) * radius_m, np.sin(theta) * radius_m, grid


def test_circle_has_constant_curvature_equal_to_one_over_radius():
    x, y, _ = _circle(200.0)
    k = curvature(x, y)
    interior = k[20:-20]  # ends are affected by the smoothing wrap
    assert np.allclose(interior, 1.0 / 200.0, rtol=0.02)


def test_curvature_scales_inversely_with_radius():
    for radius in (50.0, 100.0, 400.0):
        x, y, _ = _circle(radius)
        k = curvature(x, y)[20:-20]
        assert np.median(np.abs(k)) == pytest.approx(1.0 / radius, rel=0.02)


def test_a_closed_circle_turns_exactly_360_degrees():
    x, y, grid = _circle(200.0)
    assert heading_change_deg(curvature(x, y), grid) == pytest.approx(360.0, abs=5.0)


def test_curvature_sign_distinguishes_left_from_right():
    x, y, _ = _circle(200.0)
    left = curvature(x, y)[20:-20]
    right = curvature(x, -y)[20:-20]   # mirrored track turns the other way
    assert np.median(left) > 0
    assert np.median(right) < 0


def test_a_straight_line_has_no_curvature():
    grid = grid_for(1000.0)
    x = grid.copy()
    y = np.zeros_like(grid)
    assert np.allclose(curvature(x, y)[20:-20], 0.0, atol=1e-6)


def test_smoothing_wraps_around_because_a_lap_is_closed():
    """Without wrap-around the start/finish line would show a false corner."""
    values = np.ones(100)
    assert np.allclose(smooth_closed(values, 9), 1.0)


def test_smoothing_preserves_length():
    values = np.random.default_rng(0).random(250)
    assert len(smooth_closed(values, 15)) == 250
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_geometry_curvature.py -v`
Expected: FAIL — `ImportError: cannot import name 'curvature'`

- [ ] **Step 3: Write the minimal implementation**

Append to `lmu_telemetry/core/geometry.py`:

```python
#: Smoothing window for the racing line, in grid samples (15 x 2 m = 30 m).
LINE_SMOOTH_WINDOW = 15
#: Smoothing window applied to the curvature itself.
CURVATURE_SMOOTH_WINDOW = 8


def smooth_closed(values: np.ndarray, window: int) -> np.ndarray:
    """Moving average that wraps around, because a lap is a closed loop.

    Smoothing without wrap-around would leave an artefact at the start/finish
    line, which is an arbitrary point on the track and not a feature of it.
    """
    values = np.asarray(values, dtype=np.float64)
    if window <= 1:
        return values.copy()
    if window >= len(values):
        raise ValueError(f"window {window} exceeds series length {len(values)}")
    kernel = np.ones(window) / window
    padded = np.concatenate([values[-window:], values, values[:window]])
    return np.convolve(padded, kernel, mode="same")[window:-window]


def curvature(
    x: np.ndarray, y: np.ndarray, step_m: float = GRID_STEP_M
) -> np.ndarray:
    """Signed curvature in 1/m. Positive turns left, negative turns right.

    kappa = (x' y'' - y' x'') / (x'^2 + y'^2)^(3/2)

    The line is smoothed first: GPS jitter differentiates into large spurious
    curvature, and curvature needs two derivatives.
    """
    xs = smooth_closed(np.asarray(x, dtype=np.float64), LINE_SMOOTH_WINDOW)
    ys = smooth_closed(np.asarray(y, dtype=np.float64), LINE_SMOOTH_WINDOW)
    dx, dy = np.gradient(xs, step_m), np.gradient(ys, step_m)
    ddx, ddy = np.gradient(dx, step_m), np.gradient(dy, step_m)
    denominator = (dx**2 + dy**2) ** 1.5
    kappa = np.where(
        denominator > 1e-9,
        (dx * ddy - dy * ddx) / np.maximum(denominator, 1e-9),
        0.0,
    )
    return smooth_closed(kappa, CURVATURE_SMOOTH_WINDOW)


def heading_change_deg(kappa: np.ndarray, grid: np.ndarray) -> float:
    """Total change of heading over *grid*, in degrees.

    Integrated over a whole lap this is the closure check: a lap that goes
    round the circuit once and returns to its own start must come out near
    360 degrees. A lap that does not is geometrically broken.
    """
    return float(np.degrees(abs(np.trapz(kappa, grid))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_geometry_curvature.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/geometry.py tests/unit/test_geometry_curvature.py
git commit -m "feat: add curvature and lap-closure geometry

Validated against analytic shapes: a circle of radius R has curvature 1/R
everywhere and closes at exactly 360 degrees."
```

---

### Task 4: Sauberkeitsprüfung mit Rundenschluss

Spec §3.2 trennt **vollständig** von **sauber**. Stufe 1+2 lieferte die nicht-geometrischen Teile; hier kommt der Rundenschluss dazu.

**Files:**
- Create: `lmu_telemetry/core/quality.py`
- Test: `tests/unit/test_quality.py`

**Interfaces:**
- Consumes: `Session`, `Lap`, `geometry` (Tasks 1–3)
- Produces:
  - `CLOSURE_MIN_DEG = 330.0`, `CLOSURE_MAX_DEG = 390.0`, `DISTANCE_TOLERANCE = 0.02`
  - `LapQuality` — frozen dataclass: `is_clean: bool`, `reason: str | None`, `closure_deg: float | None`
  - `assess_lap(session: Session, lap: Lap) -> LapQuality`
  - `clean_laps(session: Session) -> list[Lap]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_quality.py`:

```python
import pytest

from lmu_telemetry.core.quality import assess_lap, clean_laps
from lmu_telemetry.core.session import Session


def test_a_qualifying_flyer_is_clean(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        q = assess_lap(s, lap)
    assert q.is_clean is True
    assert q.reason is None
    assert q.closure_deg == pytest.approx(360.0, abs=30.0)


def test_the_out_lap_is_rejected_for_touching_the_pits(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 0)
        q = assess_lap(s, lap)
    assert q.is_clean is False
    assert "pit" in q.reason.lower()


def test_the_rejection_reason_is_stated_not_just_a_boolean(monza_q_file):
    """A lap dropped without a reason is indistinguishable from a bug."""
    with Session.open(monza_q_file) as s:
        for lap in s.laps:
            q = assess_lap(s, lap)
            assert q.is_clean or q.reason


def test_clean_laps_excludes_lap_zero(monza_q_file):
    """Lap 0 runs from the start of recording to the first timed crossing."""
    with Session.open(monza_q_file) as s:
        assert all(l.number > 0 for l in clean_laps(s))


def test_a_lap_spanning_two_track_lengths_is_rejected(fixture_dir):
    """Race lap 0 fuses the formation lap with the first racing lap."""
    path = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    if not path.is_file():
        pytest.skip("fixture not built")
    with Session.open(path) as s:
        lap = next((l for l in s.laps if l.number == 0), None)
        if lap is None:
            pytest.skip("fixture has no lap 0")
        q = assess_lap(s, lap)
    assert q.is_clean is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_quality.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.quality'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/quality.py`:

```python
"""Which laps may define the track's geometry.

The spec keeps two properties apart that the old implementation mixed:

* **complete** - bounded by two `Lap` events. That is `segment_laps`' contract.
* **clean** - additionally suitable for measuring the track itself.

Only clean laps build the reference model. Every lap is still shown; an
unclean one carries the reason it was excluded, because a lap dropped without
a stated reason is indistinguishable from a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry
from .laps import Lap

#: A closed lap integrates to 360 degrees of heading change. Real laps scatter
#: around that; outside this band the lap is geometrically broken.
CLOSURE_MIN_DEG = 330.0
CLOSURE_MAX_DEG = 390.0

#: Covered distance must be within this fraction of the track length.
DISTANCE_TOLERANCE = 0.02


@dataclass(frozen=True)
class LapQuality:
    is_clean: bool
    reason: str | None
    closure_deg: float | None


def _rejected(reason: str, closure: float | None = None) -> LapQuality:
    return LapQuality(is_clean=False, reason=reason, closure_deg=closure)


def assess_lap(session, lap: Lap) -> LapQuality:
    """Judge whether *lap* may contribute to the track's reference geometry."""
    if lap.number == 0:
        return _rejected(
            "lap 0 runs from the start of recording to the first timed crossing"
        )
    if lap.touched_pits:
        return _rejected("the lap touched the pit lane")

    track_length = session.track_length_m
    if track_length is None:
        return _rejected("the session has no established track length")

    ratio = lap.distance_m / track_length
    if abs(ratio - 1.0) > DISTANCE_TOLERANCE:
        return _rejected(
            f"covered {ratio:.2f} track lengths, expected 1.00 "
            f"+-{DISTANCE_TOLERANCE:.2f}"
        )

    lat = session.lap_channel(lap, "GPS Latitude")
    lon = session.lap_channel(lap, "GPS Longitude")
    dist = session.lap_channel(lap, "Lap Dist")
    n = min(len(lat), len(lon), len(dist))
    if n < 100:
        return _rejected(f"only {n} position samples")

    x, y = geometry.project_enu(lat[:n], lon[:n])
    order = np.argsort(dist[:n])
    d_sorted = dist[:n][order]
    keep = np.concatenate(([True], np.diff(d_sorted) > 1e-6))
    d_sorted = d_sorted[keep]
    if len(d_sorted) < 50:
        return _rejected("too few distinct distance samples")

    xs = geometry.resample_to_grid(d_sorted, x[order][keep], track_length)
    ys = geometry.resample_to_grid(d_sorted, y[order][keep], track_length)
    grid = geometry.grid_for(track_length)
    closure = geometry.heading_change_deg(geometry.curvature(xs, ys), grid)

    if not (CLOSURE_MIN_DEG <= closure <= CLOSURE_MAX_DEG):
        return _rejected(
            f"lap closure {closure:.0f} deg is outside "
            f"{CLOSURE_MIN_DEG:.0f}-{CLOSURE_MAX_DEG:.0f}",
            closure,
        )
    return LapQuality(is_clean=True, reason=None, closure_deg=closure)


def clean_laps(session) -> list[Lap]:
    """Every lap of *session* that may define the track's geometry."""
    return [l for l in session.laps if assess_lap(session, l).is_clean]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_quality.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/quality.py tests/unit/test_quality.py
git commit -m "feat: classify which laps may define the track geometry

Adds the geometric half of the spec's clean-lap rule: a lap that does not
close to roughly 360 degrees is broken. Every rejection states its reason."
```

---

### Task 5: Kurvenerkennung

**Files:**
- Create: `lmu_telemetry/core/corners.py`
- Test: `tests/unit/test_corners.py`

**Interfaces:**
- Consumes: `geometry` (Tasks 2–3)
- Produces:
  - Konstanten `CORNER_MAX_RADIUS_M`, `CORNER_MIN_HEADING_DEG`, `CORNER_MIN_LENGTH_M`, `MERGE_GAP_M`, `SPLIT_HEADING_GATE_DEG`, `SPLIT_PROMINENCE_FRAC`, `SPLIT_MIN_PART_M`, `SPLIT_MAX_DEPTH`
  - `Corner` — frozen dataclass: `index: int`, `name: str`, `start_m: float`, `apex_m: float`, `end_m: float`, `radius_m: float`, `heading_deg: float`, `direction: str` (`"L"`/`"R"`)
  - `detect_corners(kappa: np.ndarray, grid: np.ndarray) -> list[Corner]` — Namen zunächst `T1…Tn`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_corners.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.corners import detect_corners
from lmu_telemetry.core.geometry import GRID_STEP_M, curvature, grid_for


def _oval(straight_m: float, radius_m: float):
    """A rounded rectangle: two straights joined by two 180 degree bends."""
    bend = np.pi * radius_m
    total = 2 * straight_m + 2 * bend
    grid = grid_for(total)
    x, y = [], []
    for d in grid:
        if d < straight_m:
            x.append(d); y.append(0.0)
        elif d < straight_m + bend:
            t = (d - straight_m) / radius_m
            x.append(straight_m + np.sin(t) * radius_m)
            y.append(radius_m - np.cos(t) * radius_m)
        elif d < 2 * straight_m + bend:
            x.append(straight_m - (d - straight_m - bend)); y.append(2 * radius_m)
        else:
            t = (d - 2 * straight_m - bend) / radius_m
            x.append(-np.sin(t) * radius_m)
            y.append(2 * radius_m - (radius_m - np.cos(t) * radius_m))
    return np.array(x), np.array(y), grid


def test_an_oval_has_exactly_two_corners():
    x, y, grid = _oval(600.0, 120.0)
    corners = detect_corners(curvature(x, y), grid)
    assert len(corners) == 2


def test_oval_corners_report_the_geometric_radius():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid):
        assert c.radius_m == pytest.approx(120.0, rel=0.15)


def test_each_oval_corner_turns_about_180_degrees():
    x, y, grid = _oval(600.0, 120.0)
    for c in detect_corners(curvature(x, y), grid):
        assert c.heading_deg == pytest.approx(180.0, abs=25.0)


def test_a_straight_track_has_no_corners():
    grid = grid_for(2000.0)
    corners = detect_corners(np.zeros_like(grid), grid)
    assert corners == []


def test_a_gentle_bend_wider_than_the_radius_limit_is_not_a_corner():
    """A 900 m radius sweep is a straight with a kink, not a corner."""
    grid = grid_for(1200.0)
    corners = detect_corners(np.full_like(grid, 1.0 / 900.0), grid)
    assert corners == []


def test_corners_are_numbered_in_track_order():
    x, y, grid = _oval(600.0, 120.0)
    corners = detect_corners(curvature(x, y), grid)
    assert [c.index for c in corners] == [1, 2]
    assert [c.name for c in corners] == ["T1", "T2"]
    assert corners[0].start_m < corners[1].start_m


def test_direction_follows_the_sign_of_curvature():
    grid = grid_for(400.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 60.0    # left
    left = detect_corners(k, grid)
    right = detect_corners(-k, grid)
    assert left[0].direction == "L"
    assert right[0].direction == "R"


def test_apex_sits_at_the_tightest_point():
    grid = grid_for(600.0)
    k = np.zeros_like(grid)
    k[50:150] = 1.0 / 100.0
    k[99] = 1.0 / 40.0     # a single unambiguous tightest sample
    c = detect_corners(k, grid)[0]
    assert c.apex_m == pytest.approx(grid[99], abs=GRID_STEP_M)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_corners.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.corners'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/corners.py`:

```python
"""Corner detection from the curvature of the reference racing line.

A corner is a stretch where the track bends more tightly than
``CORNER_MAX_RADIUS_M``. Adjacent stretches bending the same way and separated
by only a short gap belong to one corner.

Splitting fused sequences is gated on **total heading change**, not on the
prominence of curvature peaks. Prominence alone halves Monza's Curva Grande -
a long shallow bend whose two halves each read as a peak - while leaving
genuinely fused blocks intact. A single corner rarely turns more than about
180 degrees, so only blocks beyond that gate are split, and a part that still
exceeds it goes back through the splitter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from .geometry import GRID_STEP_M, heading_change_deg

#: A bend tighter than this radius counts as a corner.
CORNER_MAX_RADIUS_M = 400.0
#: Below this much turning it is a kink, not a corner.
CORNER_MIN_HEADING_DEG = 20.0
#: Below this length it is noise.
CORNER_MIN_LENGTH_M = 25.0
#: Same-signed bends closer than this belong to one corner.
MERGE_GAP_M = 40.0

#: Only blocks turning more than this are treated as fused sequences.
SPLIT_HEADING_GATE_DEG = 180.0
#: A curvature peak must stand this fraction above its surroundings to count.
SPLIT_PROMINENCE_FRAC = 0.05
#: No part of a split may be shorter than this.
SPLIT_MIN_PART_M = 40.0
#: Guard against pathological recursion.
SPLIT_MAX_DEPTH = 4


@dataclass(frozen=True)
class Corner:
    index: int
    name: str
    start_m: float
    apex_m: float
    end_m: float
    radius_m: float
    heading_deg: float
    direction: str


def _contiguous(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _merge(regions, kappa, grid):
    merged: list[tuple[int, int]] = []
    for si, ei in regions:
        if merged:
            pi, pe = merged[-1]
            same_way = np.sign(kappa[(pi + pe) // 2]) == np.sign(kappa[(si + ei) // 2])
            if same_way and (grid[si] - grid[pe]) < MERGE_GAP_M:
                merged[-1] = (pi, ei)
                continue
        merged.append((si, ei))
    return merged


def _split_once(kappa, grid, si, ei) -> list[tuple[int, int]]:
    """Cut a block at curvature valleys that genuinely separate two corners."""
    segment = np.abs(kappa[si : ei + 1])
    if len(segment) < 5:
        return [(si, ei)]
    min_part = max(int(SPLIT_MIN_PART_M / GRID_STEP_M), 2)
    peaks, _ = find_peaks(
        segment,
        prominence=segment.max() * SPLIT_PROMINENCE_FRAC,
        distance=min_part,
    )
    if len(peaks) < 2:
        return [(si, ei)]

    cuts = []
    for a, b in zip(peaks, peaks[1:]):
        valley = a + int(np.argmin(segment[a : b + 1]))
        if segment[valley] < min(segment[a], segment[b]) * (1.0 - SPLIT_PROMINENCE_FRAC):
            cuts.append(si + valley)
    if not cuts:
        return [(si, ei)]

    parts, previous = [], si
    for cut in cuts:
        if cut - previous >= min_part and ei - cut >= min_part:
            parts.append((previous, cut - 1))
            previous = cut
    parts.append((previous, ei))
    return parts


def _split(kappa, grid, si, ei, depth: int = 0) -> list[tuple[int, int]]:
    if depth >= SPLIT_MAX_DEPTH:
        return [(si, ei)]
    if heading_change_deg(kappa[si : ei + 1], grid[si : ei + 1]) <= SPLIT_HEADING_GATE_DEG:
        return [(si, ei)]
    parts = _split_once(kappa, grid, si, ei)
    if len(parts) == 1:
        return parts
    out: list[tuple[int, int]] = []
    for ps, pe in parts:
        out.extend(_split(kappa, grid, ps, pe, depth + 1))
    return out


def detect_corners(kappa: np.ndarray, grid: np.ndarray) -> list[Corner]:
    """Every corner on the line described by *kappa*, in track order."""
    kappa = np.asarray(kappa, dtype=np.float64)
    grid = np.asarray(grid, dtype=np.float64)
    if len(kappa) != len(grid):
        raise ValueError(f"kappa and grid differ: {len(kappa)} vs {len(grid)}")

    regions = _merge(
        _contiguous(np.abs(kappa) > 1.0 / CORNER_MAX_RADIUS_M), kappa, grid
    )

    corners: list[Corner] = []
    for si, ei in regions:
        for ps, pe in _split(kappa, grid, si, ei):
            heading = heading_change_deg(kappa[ps : pe + 1], grid[ps : pe + 1])
            if heading < CORNER_MIN_HEADING_DEG:
                continue
            if grid[pe] - grid[ps] < CORNER_MIN_LENGTH_M:
                continue
            apex = ps + int(np.argmax(np.abs(kappa[ps : pe + 1])))
            peak = abs(float(kappa[apex]))
            index = len(corners) + 1
            corners.append(
                Corner(
                    index=index,
                    name=f"T{index}",
                    start_m=float(grid[ps]),
                    apex_m=float(grid[apex]),
                    end_m=float(grid[pe]),
                    radius_m=1.0 / peak if peak > 0 else float("inf"),
                    heading_deg=heading,
                    direction="L" if kappa[apex] > 0 else "R",
                )
            )
    return corners
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_corners.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/corners.py tests/unit/test_corners.py
git commit -m "feat: detect corners from curvature, splitting on heading change

Gating the split on total heading change rather than curvature-peak
prominence keeps Monza's Curva Grande intact while still separating fused
sequences. Validated against an analytic oval."
```

---

### Task 6: Streckenidentität und Referenzlinie

> **Nachtrag nach der Umsetzung:** Der hier beschriebene Entwurf mit
> `length_bucket_m` (Streckenlänge auf ein 10-m-Raster gerundet) ist **überholt**.
> Der Golden-Test aus Task 9 hat aufgedeckt, dass ein festes Raster immer Grenzen hat:
> eine Monza-Session misst 5773,812 m und fällt in Bucket 5770, die übrigen 22 messen
> 5775–5780 und fallen in 5780 — Monza zerfiel dadurch in zwei Identitäten. Eine
> größere Bucketgröße verschiebt die Grenze nur. Die Identität ist jetzt
> `(track, layout)`, und die Längenübereinstimmung wird in `build_track_model`
> geprüft (`LENGTH_AGREEMENT_TOLERANCE = 0.02`) — der einzigen Stelle, die alle
> Sessions einer Strecke gleichzeitig sieht.


**Files:**
- Create: `lmu_telemetry/core/track_model.py`
- Test: `tests/unit/test_track_identity.py`

**Interfaces:**
- Consumes: `Session`, `quality`, `geometry` (Tasks 1–4)
- Produces:
  - `TrackKey` — frozen dataclass: `track: str`, `layout: str`, `length_bucket_m: int`; `TrackKey.of(session) -> TrackKey | None`; `TrackKey.slug() -> str`
  - `reference_line(sessions_laps) -> tuple[np.ndarray, np.ndarray]` — mediane Linie
  - `LENGTH_BUCKET_M: int = 10`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_track_identity.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, reference_line


def test_identity_combines_name_layout_and_length(monza_q_file):
    with Session.open(monza_q_file) as s:
        key = TrackKey.of(s)
    assert key.track == "Autodromo Nazionale Monza"
    assert key.layout == "Autodromo Nazionale Monza"
    assert key.length_bucket_m == 5780


def test_length_is_bucketed_so_lap_to_lap_scatter_does_not_split_a_track():
    """Le Mans measures 13619.4-13621.8 m across sessions - one track."""
    a = TrackKey("Circuit de la Sarthe", "Circuit de la Sarthe", 13620)
    b = TrackKey("Circuit de la Sarthe", "Circuit de la Sarthe", 13620)
    assert a == b
    assert hash(a) == hash(b)


def test_length_separates_layouts_that_share_a_name():
    short = TrackKey("Some Circuit", "Some Circuit", 3000)
    full = TrackKey("Some Circuit", "Some Circuit", 5000)
    assert short != full


def test_slug_is_filesystem_safe(monza_q_file):
    with Session.open(monza_q_file) as s:
        slug = TrackKey.of(s).slug()
    assert " " not in slug
    assert all(c.isalnum() or c in "-_" for c in slug)


def test_identity_is_none_without_a_track_length(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert TrackKey.of(s) is None


def test_reference_line_is_the_median_of_its_inputs():
    a = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 0.0, 0.0]))
    b = (np.array([0.0, 2.0, 4.0]), np.array([1.0, 1.0, 1.0]))
    c = (np.array([0.0, 3.0, 6.0]), np.array([2.0, 2.0, 2.0]))
    x, y = reference_line([a, b, c])
    assert np.allclose(x, [0.0, 2.0, 4.0])
    assert np.allclose(y, [1.0, 1.0, 1.0])


def test_reference_line_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        reference_line([(np.zeros(3), np.zeros(3)), (np.zeros(4), np.zeros(4))])


def test_reference_line_rejects_an_empty_input():
    with pytest.raises(ValueError):
        reference_line([])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_track_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.track_model'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/track_model.py`:

```python
"""The reference model: one corner list per track, shared by every lap.

Detecting corners per lap cannot work - measured on the corpus, the same track
yields 9 to 13 corners depending on the line driven. So corners are determined
once per track identity from the median racing line of every clean lap, and
every lap of every driver then refers to that one list. Comparisons are
consistent by construction rather than by convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

#: Track length is bucketed to this resolution before it enters the identity,
#: so lap-to-lap scatter (Le Mans: 13619.4-13621.8 m) does not split a track
#: while genuinely different layouts still separate.
LENGTH_BUCKET_M = 10


@dataclass(frozen=True)
class TrackKey:
    """What makes two sessions the same track.

    The name alone is not enough: a circuit can ship several layouts under one
    name. The measured length separates them.
    """

    track: str
    layout: str
    length_bucket_m: int

    @classmethod
    def of(cls, session) -> "TrackKey | None":
        length = session.track_length_m
        if length is None:
            return None
        info = session.info
        return cls(
            track=info.track,
            layout=info.layout or info.track,
            length_bucket_m=int(round(length / LENGTH_BUCKET_M) * LENGTH_BUCKET_M),
        )

    def slug(self) -> str:
        """A filesystem-safe identifier, used as the cache filename."""
        raw = f"{self.track}-{self.layout}-{self.length_bucket_m}"
        return re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").lower()


def reference_line(lines) -> tuple[np.ndarray, np.ndarray]:
    """The median racing line over many laps, sample by sample.

    The median rather than the mean: one wild lap should not drag the
    reference geometry with it.
    """
    lines = list(lines)
    if not lines:
        raise ValueError("need at least one lap to build a reference line")
    lengths = {len(x) for x, _ in lines} | {len(y) for _, y in lines}
    if len(lengths) != 1:
        raise ValueError(f"lines differ in length: {sorted(lengths)}")
    xs = np.median(np.array([x for x, _ in lines], dtype=np.float64), axis=0)
    ys = np.median(np.array([y for _, y in lines], dtype=np.float64), axis=0)
    return xs, ys
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_track_identity.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/track_model.py tests/unit/test_track_identity.py
git commit -m "feat: add track identity and median reference line"
```

---

### Task 7: Modell bauen und cachen

**Files:**
- Modify: `lmu_telemetry/core/track_model.py`
- Test: `tests/unit/test_track_model_build.py`

**Interfaces:**
- Consumes: alles aus Tasks 1–6
- Produces:
  - `TrackModel` — frozen dataclass: `key: TrackKey`, `track_length_m: float`, `corners: list[Corner]`, `closure_deg: float`, `lap_count: int`, `confident: bool`, `warning: str | None`
  - `build_track_model(sessions: list[Session]) -> TrackModel | None`
  - `TrackModel.to_dict()` / `TrackModel.from_dict(data)`
  - `save_model(model, cache_dir) -> Path` / `load_model(key, cache_dir) -> TrackModel | None`
  - `MIN_CONFIDENT_LAPS: int = 3`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_track_model_build.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import (
    TrackModel,
    build_track_model,
    load_model,
    save_model,
)


def test_model_from_the_reference_fixture(monza_q_file):
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    assert model is not None
    assert model.key.track == "Autodromo Nazionale Monza"
    assert model.track_length_m == pytest.approx(5776.08, abs=1.0)
    assert 340.0 <= model.closure_deg <= 380.0
    assert len(model.corners) >= 10


def test_a_model_from_too_few_laps_is_flagged_unconfident(monza_q_file):
    """The fixture holds two clean laps; a warning must say so."""
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    assert model.confident is False
    assert model.warning is not None
    assert str(model.lap_count) in model.warning


def test_no_model_without_a_clean_lap(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert build_track_model([s]) is None


def test_no_model_is_built_silently_from_bad_data(no_complete_lap_file):
    """Returning None beats inventing geometry - that is the old bug."""
    with Session.open(no_complete_lap_file) as s:
        assert build_track_model([s]) is None


def test_model_survives_a_round_trip_through_json(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    path = save_model(model, tmp_path)
    assert path.is_file()
    again = load_model(model.key, tmp_path)
    assert again is not None
    assert again.key == model.key
    assert again.track_length_m == pytest.approx(model.track_length_m)
    assert [c.name for c in again.corners] == [c.name for c in model.corners]
    for a, b in zip(again.corners, model.corners):
        assert a.start_m == pytest.approx(b.start_m)
        assert a.apex_m == pytest.approx(b.apex_m)
        assert a.radius_m == pytest.approx(b.radius_m)


def test_loading_an_absent_model_returns_none(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        key = build_track_model([s]).key
    assert load_model(key, tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_track_model_build.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_track_model'`

- [ ] **Step 3: Write the minimal implementation**

Append to `lmu_telemetry/core/track_model.py` (and extend the imports at the top with `import json`, `from pathlib import Path`, `from . import geometry`, `from .corners import Corner, detect_corners`, `from .quality import clean_laps`):

```python
#: Below this many clean laps the model is served with a warning attached.
MIN_CONFIDENT_LAPS = 3


@dataclass(frozen=True)
class TrackModel:
    key: TrackKey
    track_length_m: float
    corners: list[Corner]
    closure_deg: float
    lap_count: int
    confident: bool
    warning: str | None

    def to_dict(self) -> dict:
        return {
            "track": self.key.track,
            "layout": self.key.layout,
            "length_bucket_m": self.key.length_bucket_m,
            "track_length_m": self.track_length_m,
            "closure_deg": self.closure_deg,
            "lap_count": self.lap_count,
            "confident": self.confident,
            "warning": self.warning,
            "corners": [
                {
                    "index": c.index, "name": c.name,
                    "start_m": c.start_m, "apex_m": c.apex_m, "end_m": c.end_m,
                    "radius_m": c.radius_m, "heading_deg": c.heading_deg,
                    "direction": c.direction,
                }
                for c in self.corners
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrackModel":
        return cls(
            key=TrackKey(data["track"], data["layout"], int(data["length_bucket_m"])),
            track_length_m=float(data["track_length_m"]),
            corners=[Corner(**c) for c in data["corners"]],
            closure_deg=float(data["closure_deg"]),
            lap_count=int(data["lap_count"]),
            confident=bool(data["confident"]),
            warning=data.get("warning"),
        )


def _lap_line(session, lap, track_length_m):
    """One lap's racing line on the track's common grid, or None."""
    lat = session.lap_channel(lap, "GPS Latitude")
    lon = session.lap_channel(lap, "GPS Longitude")
    dist = session.lap_channel(lap, "Lap Dist")
    n = min(len(lat), len(lon), len(dist))
    if n < 100:
        return None
    x, y = geometry.project_enu(lat[:n], lon[:n])
    order = np.argsort(dist[:n])
    d = dist[:n][order]
    keep = np.concatenate(([True], np.diff(d) > 1e-6))
    d = d[keep]
    if len(d) < 50 or d[-1] - d[0] < track_length_m * 0.9:
        return None
    return (
        geometry.resample_to_grid(d, x[order][keep], track_length_m),
        geometry.resample_to_grid(d, y[order][keep], track_length_m),
    )


def build_track_model(sessions) -> "TrackModel | None":
    """Build one corner model from every clean lap of *sessions*.

    Returns ``None`` rather than a model built from unusable data: inventing
    geometry from a single crash lap is precisely the failure this design
    exists to prevent.
    """
    sessions = list(sessions)
    keys = {TrackKey.of(s) for s in sessions} - {None}
    if len(keys) != 1:
        raise ValueError(f"sessions span {len(keys)} track identities, expected 1")
    key = keys.pop()

    lengths = [s.track_length_m for s in sessions if s.track_length_m is not None]
    track_length = float(np.median(lengths))

    lines = []
    for session in sessions:
        for lap in clean_laps(session):
            line = _lap_line(session, lap, track_length)
            if line is not None:
                lines.append(line)
    if not lines:
        return None

    x, y = reference_line(lines)
    grid = geometry.grid_for(track_length)
    kappa = geometry.curvature(x, y)
    closure = geometry.heading_change_deg(kappa, grid)
    corners = detect_corners(kappa, grid)

    confident = len(lines) >= MIN_CONFIDENT_LAPS
    warning = None
    if not confident:
        warning = (
            f"built from only {len(lines)} clean lap(s); "
            f"corner positions may shift as more laps are recorded"
        )
    return TrackModel(
        key=key,
        track_length_m=track_length,
        corners=corners,
        closure_deg=closure,
        lap_count=len(lines),
        confident=confident,
        warning=warning,
    )


def save_model(model: TrackModel, cache_dir) -> Path:
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{model.key.slug()}.json"
    path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return path


def load_model(key: TrackKey, cache_dir) -> "TrackModel | None":
    path = Path(cache_dir) / f"{key.slug()}.json"
    if not path.is_file():
        return None
    return TrackModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_track_model_build.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/track_model.py tests/unit/test_track_model_build.py
git commit -m "feat: build and cache one corner model per track identity

A model is never built silently from unusable data: too few clean laps
attaches a warning, none at all returns nothing."
```

---

### Task 8: Kuratierte Kurvennamen

Portimãos offizielle 15 Turns bilden sich nicht 1:1 auf geometrische Bögen ab — ein 190°-Hufeisen zählt die Streckenkarte als zwei. Die Namenstabelle ist der Ort, an dem offizielle Nummerierung und Geometrie versöhnt werden, nicht der Detektor.

**Files:**
- Create: `lmu_telemetry/core/naming.py`
- Create: `lmu_telemetry/data/tracks/autodromo-nazionale-monza.json`
- Create: `lmu_telemetry/data/tracks/circuit-de-la-sarthe.json`
- Create: `lmu_telemetry/data/tracks/algarve-international-circuit.json`
- Modify: `pyproject.toml` — JSON-Dateien ins Paket aufnehmen
- Test: `tests/unit/test_naming.py`

**Interfaces:**
- Consumes: `Corner` (Task 5), `TrackKey` (Task 6)
- Produces:
  - `load_names(track: str) -> list[dict] | None`
  - `apply_names(corners: list[Corner], track: str) -> list[Corner]` — ohne Tabelle unverändert `T1…Tn`

- [ ] **Step 1: Write the name tables**

Create `lmu_telemetry/data/tracks/autodromo-nazionale-monza.json`. Distances are the apex positions of the reference model; each entry claims the corner whose apex is nearest.

```json
{
  "track": "Autodromo Nazionale Monza",
  "corners": [
    {"apex_m": 932,  "name": "Variante del Rettifilo 1", "turns": "1"},
    {"apex_m": 972,  "name": "Variante del Rettifilo 2", "turns": "2"},
    {"apex_m": 1354, "name": "Curva Grande",             "turns": "3"},
    {"apex_m": 2146, "name": "Variante della Roggia 1",  "turns": "4"},
    {"apex_m": 2190, "name": "Variante della Roggia 2",  "turns": "5"},
    {"apex_m": 2550, "name": "Curva di Lesmo 1",         "turns": "6"},
    {"apex_m": 2878, "name": "Curva di Lesmo 2",         "turns": "7"},
    {"apex_m": 3948, "name": "Variante Ascari 1",        "turns": "8"},
    {"apex_m": 4050, "name": "Variante Ascari 2",        "turns": "9"},
    {"apex_m": 4132, "name": "Variante Ascari 3",        "turns": "10"},
    {"apex_m": 5178, "name": "Curva Parabolica",         "turns": "11"}
  ]
}
```

Create `lmu_telemetry/data/tracks/circuit-de-la-sarthe.json`:

```json
{
  "track": "Circuit de la Sarthe",
  "corners": [
    {"apex_m": 670,   "name": "Dunlop Curve",        "turns": "1"},
    {"apex_m": 844,   "name": "Dunlop Chicane 1",    "turns": "2"},
    {"apex_m": 908,   "name": "Dunlop Chicane 2",    "turns": "3"},
    {"apex_m": 1270,  "name": "Esses 1",             "turns": "4"},
    {"apex_m": 1490,  "name": "Esses 2",             "turns": "5"},
    {"apex_m": 1590,  "name": "Esses 3",             "turns": "6"},
    {"apex_m": 1914,  "name": "Tertre Rouge",        "turns": "7"},
    {"apex_m": 4056,  "name": "Mulsanne Chicane 1a", "turns": "8"},
    {"apex_m": 4134,  "name": "Mulsanne Chicane 1b", "turns": "9"},
    {"apex_m": 4224,  "name": "Mulsanne Chicane 1c", "turns": "10"},
    {"apex_m": 6016,  "name": "Mulsanne Chicane 2a", "turns": "11"},
    {"apex_m": 6086,  "name": "Mulsanne Chicane 2b", "turns": "12"},
    {"apex_m": 6200,  "name": "Mulsanne Chicane 2c", "turns": "13"},
    {"apex_m": 7738,  "name": "Mulsanne Corner",     "turns": "14"},
    {"apex_m": 9650,  "name": "Indianapolis 1",      "turns": "15"},
    {"apex_m": 9832,  "name": "Indianapolis 2",      "turns": "16"},
    {"apex_m": 10160, "name": "Arnage",              "turns": "17"},
    {"apex_m": 11532, "name": "Porsche Curves 1",    "turns": "18"},
    {"apex_m": 11792, "name": "Porsche Curves 2",    "turns": "19"},
    {"apex_m": 12212, "name": "Porsche Curves 3",    "turns": "20"},
    {"apex_m": 12434, "name": "Porsche Curves 4",    "turns": "21"},
    {"apex_m": 13254, "name": "Ford Chicane 1",      "turns": "22"},
    {"apex_m": 13318, "name": "Ford Chicane 2",      "turns": "23"},
    {"apex_m": 13406, "name": "Ford Chicane 3",      "turns": "24"},
    {"apex_m": 13446, "name": "Ford Chicane 4",      "turns": "25"}
  ]
}
```

Create `lmu_telemetry/data/tracks/algarve-international-circuit.json`. Note the last entry: one geometric arc carries two official turn numbers, which is exactly what this table exists to express.

```json
{
  "track": "Algarve International Circuit",
  "corners": [
    {"apex_m": 406,  "name": "Turn 1",       "turns": "1"},
    {"apex_m": 566,  "name": "Turn 2",       "turns": "2"},
    {"apex_m": 726,  "name": "Turn 3",       "turns": "3"},
    {"apex_m": 820,  "name": "Turn 4",       "turns": "4"},
    {"apex_m": 1458, "name": "Turn 5",       "turns": "5"},
    {"apex_m": 1674, "name": "Turn 6",       "turns": "6"},
    {"apex_m": 1908, "name": "Turn 7",       "turns": "7"},
    {"apex_m": 2070, "name": "Turn 8",       "turns": "8"},
    {"apex_m": 2464, "name": "Turn 9",       "turns": "9"},
    {"apex_m": 2744, "name": "Turn 10",      "turns": "10"},
    {"apex_m": 2952, "name": "Turn 11",      "turns": "11"},
    {"apex_m": 3200, "name": "Turn 12",      "turns": "12"},
    {"apex_m": 3428, "name": "Turns 13-14",  "turns": "13-14"},
    {"apex_m": 3848, "name": "Turn 15",      "turns": "15"}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_naming.py`:

```python
import pytest

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.naming import apply_names, load_names


def _corner(index: int, apex_m: float) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=apex_m - 50.0,
        apex_m=apex_m, end_m=apex_m + 50.0, radius_m=80.0,
        heading_deg=60.0, direction="R",
    )


def test_known_track_gets_real_names():
    named = apply_names([_corner(1, 932), _corner(2, 5178)], "Autodromo Nazionale Monza")
    assert named[0].name == "Variante del Rettifilo 1"
    assert named[1].name == "Curva Parabolica"


def test_unknown_track_keeps_generic_names():
    corners = [_corner(1, 100), _corner(2, 500)]
    named = apply_names(corners, "Some Unlisted Circuit")
    assert [c.name for c in named] == ["T1", "T2"]


def test_one_arc_may_carry_two_official_turn_numbers():
    """Portimao's 190-degree horseshoe is numbered as two turns on the map."""
    named = apply_names([_corner(1, 3428)], "Algarve International Circuit")
    assert named[0].name == "Turns 13-14"


def test_a_corner_far_from_every_entry_keeps_its_generic_name():
    """A drifting apex must not silently borrow a neighbour's name."""
    named = apply_names([_corner(1, 4500)], "Autodromo Nazionale Monza")
    assert named[0].name == "T1"


def test_naming_does_not_alter_geometry():
    original = _corner(1, 932)
    named = apply_names([original], "Autodromo Nazionale Monza")[0]
    assert named.start_m == original.start_m
    assert named.apex_m == original.apex_m
    assert named.radius_m == original.radius_m


def test_load_names_returns_none_for_an_unknown_track():
    assert load_names("Some Unlisted Circuit") is None


@pytest.mark.parametrize(
    "track",
    ["Autodromo Nazionale Monza", "Circuit de la Sarthe", "Algarve International Circuit"],
)
def test_every_shipped_table_loads(track):
    entries = load_names(track)
    assert entries
    assert all("apex_m" in e and "name" in e for e in entries)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.naming'`

- [ ] **Step 4: Write the minimal implementation**

Create `lmu_telemetry/core/naming.py`:

```python
"""Curated corner names layered over the detected geometry.

Corner count is a naming convention, not a physical fact. Portimao's official
15 turns do not map one-to-one onto geometrically distinct arcs: the 190-degree
horseshoe at 3428 m is one continuous arc that the circuit map numbers as two
turns. Reconciling the two belongs here, not in the detector - the detector
must never invent a boundary the geometry does not contain.

A track with no table keeps the generic T1..Tn names.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .corners import Corner

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tracks"

#: An entry only claims a corner whose apex is within this distance of it.
#: Beyond that the corner keeps its generic name rather than borrowing a
#: neighbour's, which would silently mislabel a shifted apex.
MATCH_TOLERANCE_M = 60.0


def _slug(track: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", track).strip("-").lower()


@lru_cache(maxsize=None)
def load_names(track: str) -> "tuple[dict, ...] | None":
    path = _DATA_DIR / f"{_slug(track)}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(data.get("corners", ()))


def apply_names(corners: list[Corner], track: str) -> list[Corner]:
    """Return *corners* with curated names where one matches."""
    entries = load_names(track)
    if not entries:
        return list(corners)
    named = []
    for corner in corners:
        best = min(entries, key=lambda e: abs(float(e["apex_m"]) - corner.apex_m))
        if abs(float(best["apex_m"]) - corner.apex_m) <= MATCH_TOLERANCE_M:
            named.append(replace(corner, name=str(best["name"])))
        else:
            named.append(corner)
    return named
```

In `pyproject.toml`, below the existing `[tool.setuptools.packages.find]` block, add:

```toml
[tool.setuptools.package-data]
lmu_telemetry = ["data/tracks/*.json"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_naming.py -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/core/naming.py lmu_telemetry/data tests/unit/test_naming.py pyproject.toml
git commit -m "feat: layer curated corner names over the detected geometry

Official turn numbering and geometric arcs do not always agree - Portimao's
190-degree horseshoe is one arc numbered as two turns. The name table
reconciles them so the detector never has to invent a boundary."
```

---

### Task 9: Golden-Tests der Referenzmodelle

Friert die vier gemessenen Modelle ein. Jede Änderung, die eine Kurve verschiebt, wird ab hier sichtbar.

**Files:**
- Create: `tests/golden/expected_track_models.json`
- Create: `tests/golden/test_golden_track_models.py`
- Test: `tests/invariants/test_corner_invariants.py`

**Interfaces:**
- Consumes: alles aus Tasks 1–8
- Produces: nichts (nur Tests)

- [ ] **Step 1: Write the golden data**

Create `tests/golden/expected_track_models.json`. These were measured on the full corpus with the parameters in this plan's Global Constraints.

```json
{
  "Autodromo Nazionale Monza": {
    "track_length_m": 5778.1,
    "closure_deg": 359,
    "corner_count": 11,
    "apex_m": [932, 972, 1354, 2146, 2190, 2550, 2878, 3948, 4050, 4132, 5178],
    "names": [
      "Variante del Rettifilo 1", "Variante del Rettifilo 2", "Curva Grande",
      "Variante della Roggia 1", "Variante della Roggia 2",
      "Curva di Lesmo 1", "Curva di Lesmo 2",
      "Variante Ascari 1", "Variante Ascari 2", "Variante Ascari 3",
      "Curva Parabolica"
    ]
  },
  "Algarve International Circuit": {
    "track_length_m": 4634.9,
    "closure_deg": 350,
    "corner_count": 14,
    "apex_m": [406, 566, 726, 820, 1458, 1674, 1908, 2070, 2464, 2744, 2952, 3200, 3428, 3848],
    "names": [
      "Turn 1", "Turn 2", "Turn 3", "Turn 4", "Turn 5", "Turn 6", "Turn 7",
      "Turn 8", "Turn 9", "Turn 10", "Turn 11", "Turn 12", "Turns 13-14", "Turn 15"
    ]
  },
  "Circuit de la Sarthe": {
    "track_length_m": 13620.0,
    "closure_deg": 372,
    "corner_count": 25,
    "apex_m": [670, 844, 908, 1270, 1490, 1590, 1914, 4056, 4134, 4224,
               6016, 6086, 6200, 7738, 9650, 9832, 10160, 11532, 11792,
               12212, 12434, 13254, 13318, 13406, 13446],
    "names": [
      "Dunlop Curve", "Dunlop Chicane 1", "Dunlop Chicane 2",
      "Esses 1", "Esses 2", "Esses 3", "Tertre Rouge",
      "Mulsanne Chicane 1a", "Mulsanne Chicane 1b", "Mulsanne Chicane 1c",
      "Mulsanne Chicane 2a", "Mulsanne Chicane 2b", "Mulsanne Chicane 2c",
      "Mulsanne Corner", "Indianapolis 1", "Indianapolis 2", "Arnage",
      "Porsche Curves 1", "Porsche Curves 2", "Porsche Curves 3", "Porsche Curves 4",
      "Ford Chicane 1", "Ford Chicane 2", "Ford Chicane 3", "Ford Chicane 4"
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/golden/test_golden_track_models.py`:

```python
"""Frozen reference models. Any change that moves a corner fails here."""

import json
from collections import defaultdict
from pathlib import Path

import pytest

from lmu_telemetry.core.naming import apply_names
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, build_track_model

pytestmark = pytest.mark.corpus

GOLDEN = json.loads((Path(__file__).parent / "expected_track_models.json").read_text())

#: How far an apex may move before the model counts as changed. Generous
#: enough to absorb median-line jitter (measured at up to 46 m on Algarve when
#: the clean-lap set changes) but far tighter than the >100 m jump a corner
#: makes when it is wrongly split or merged - which is what this test guards.
APEX_TOLERANCE_M = 60.0


@pytest.fixture(scope="module")
def models(corpus_files):
    """One model per track, built from every clean lap in the corpus."""
    grouped = defaultdict(list)
    open_sessions = []
    try:
        for path in corpus_files:
            s = Session.open(path)
            open_sessions.append(s)
            key = TrackKey.of(s)
            if key is not None:
                grouped[key].append(s)
        out = {}
        for key, sessions in grouped.items():
            model = build_track_model(sessions)
            if model is not None:
                out[key.track] = model
        return out
    finally:
        for s in open_sessions:
            s.close()


@pytest.mark.parametrize("track", sorted(GOLDEN))
def test_track_model_matches_the_frozen_reference(models, track):
    expected = GOLDEN[track]
    assert track in models, f"no model built for {track}"
    model = models[track]

    assert model.track_length_m == pytest.approx(expected["track_length_m"], abs=2.0)
    assert model.closure_deg == pytest.approx(expected["closure_deg"], abs=10.0)
    assert len(model.corners) == expected["corner_count"], (
        f"{track}: expected {expected['corner_count']} corners, "
        f"got {len(model.corners)} at {[round(c.apex_m) for c in model.corners]}"
    )

    named = apply_names(model.corners, track)
    for corner, apex, name in zip(named, expected["apex_m"], expected["names"]):
        assert corner.apex_m == pytest.approx(apex, abs=APEX_TOLERANCE_M), (
            f"{track} {name}: apex moved from {apex} to {corner.apex_m:.0f} m"
        )
        assert corner.name == name


def test_monza_curva_grande_is_one_corner(models):
    """The regression this design was corrected for: prominence-based
    splitting halved this bend into two corners."""
    corners = models["Autodromo Nazionale Monza"].corners
    grande = [c for c in corners if 1250 < c.apex_m < 1750]
    assert len(grande) == 1
    assert grande[0].radius_m > 150.0
```

Create `tests/invariants/test_corner_invariants.py`:

```python
"""Properties every track model must satisfy, whatever the track."""

from collections import defaultdict

import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, build_track_model

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def models(corpus_files):
    grouped = defaultdict(list)
    open_sessions = []
    try:
        for path in corpus_files:
            s = Session.open(path)
            open_sessions.append(s)
            key = TrackKey.of(s)
            if key is not None:
                grouped[key].append(s)
        return [m for m in (build_track_model(v) for v in grouped.values()) if m]
    finally:
        for s in open_sessions:
            s.close()


def test_at_least_three_tracks_produced_a_model(models):
    assert len(models) >= 3


def test_corners_are_ordered_and_do_not_overlap(models):
    for model in models:
        for a, b in zip(model.corners, model.corners[1:]):
            assert a.end_m <= b.start_m, f"{model.key.track}: {a.name} overlaps {b.name}"


def test_every_apex_lies_inside_its_own_corner(models):
    for model in models:
        for c in model.corners:
            assert c.start_m <= c.apex_m <= c.end_m, f"{model.key.track} {c.name}"


def test_every_corner_stays_within_the_track(models):
    for model in models:
        for c in model.corners:
            assert 0.0 <= c.start_m
            assert c.end_m <= model.track_length_m


def test_corners_are_tighter_than_the_radius_limit(models):
    from lmu_telemetry.core.corners import CORNER_MAX_RADIUS_M

    for model in models:
        for c in model.corners:
            assert c.radius_m < CORNER_MAX_RADIUS_M, f"{model.key.track} {c.name}"


def test_a_model_built_from_few_laps_says_so(models):
    from lmu_telemetry.core.track_model import MIN_CONFIDENT_LAPS

    for model in models:
        if model.lap_count < MIN_CONFIDENT_LAPS:
            assert model.confident is False
            assert model.warning
```

- [ ] **Step 3: Run the new tests**

Run: `python -m pytest tests/golden/test_golden_track_models.py tests/invariants/test_corner_invariants.py -v`
Expected: PASS

**If a golden value fails, the bug is in Tasks 5–8, not in the JSON.** These figures were measured against the corpus. Report the actual-versus-expected values rather than editing the golden file — editing it to match the code defeats its purpose.

Imola is deliberately absent from the golden file: the corpus holds a single clean lap there, so its model is served with a warning and its geometry is not stable enough to freeze.

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS — no regressions

- [ ] **Step 5: Verify the CI-facing run still holds**

Run: `python -m pytest -q -m "not corpus"`
Expected: PASS — the count must have risen by the unit tests added in Tasks 1–8

- [ ] **Step 6: Commit**

```bash
git add tests/golden/expected_track_models.json tests/golden/test_golden_track_models.py tests/invariants/test_corner_invariants.py
git commit -m "test: freeze the reference track models

Monza 11 corners, Algarve 14, Le Mans 25, each with named apexes measured
from the full corpus. Includes a direct guard on Curva Grande staying one
corner, which is the regression the split criterion was corrected for."
```

---

## Abnahmekriterien für Stufe 3

- [ ] `python -m pytest -q` vollständig grün
- [ ] `python -m pytest -q -m "not corpus"` grün und gewachsen — die gesamte Geometrie- und Kurvenmathematik ist ohne den Bestand geprüft
- [ ] Monza liefert **11** Kurven, Curva Grande ist **eine** davon
- [ ] Algarve liefert **14** geometrische Bögen, T13–14 als ein benannter Eintrag
- [ ] Le Mans liefert **25** Kurven mit Mulsanne, Arnage, Porsche- und Ford-Abschnitten
- [ ] Kein Modell wird stillschweigend aus zu wenigen Runden gebaut — entweder Warnung oder `None`
- [ ] Kurvenerkennung liest **nirgends** den Lenkwinkel
- [ ] Ein Kurvenmodell hängt an der Streckenidentität, nicht an einer Runde oder Session
- [ ] `backend/` unverändert

## Nicht Teil dieser Stufe

- Delta über Distanz, Kurvenmetriken, Coaching (Stufe 4)
- API, Cache-Anbindung, Dezimierung (Stufe 5)
- Frontend, Streckenkarte (Stufe 6)
- Gemeinsame Basis-Exception und ein `Protocol` für die Datei-Schnittstelle — vom Abschluss-Review empfohlen, aber erst nötig, wenn Stufe 5 die API-Schicht baut
