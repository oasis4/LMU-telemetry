# Stufe 4: Delta, Kurvenmetriken, Coaching — Implementierungsplan

> **Für Agenten:** ERFORDERLICHE TEILFÄHIGKEIT: superpowers:subagent-driven-development.
> Schritte tragen Checkboxen (`- [ ]`).

**Ziel:** Aus zwei sauberen Runden derselben Streckenidentität ableiten, *wo* die
eine schneller war und *warum* — in Sekunden, nicht als Etikett.

**Architektur:** Alles legt sich auf das gemeinsame 2-m-Distanzraster des
Referenzmodells aus Stufe 3. Weil beide Runden dieselbe Kurvenliste benutzen,
ist jeder Vergleich per Konstruktion konsistent — das war Fehler D des alten
Standes, wo `CompareView.vue` für jede Seite eine eigene Kurvenliste holte.

**Technik:** numpy; scipy nur dort, wo Stufe 3 es schon nutzt.

## Globale Randbedingungen

- **Ground Truth vor Heuristik.** Jede Größe, die in der Datei steht, wird
  gelesen, nie geraten. Fehlt sie, ist das Ergebnis `None` oder ein Fehler mit
  genannter Ursache — nie ein Platzhalter.
- **Einheiten kommen aus `channelsList`, nie aus dem beobachteten Wertebereich.**
  Gemessen über die 78 Sessions des Arbeitssets:
  `Ground Speed` = `km/h` @ 100 Hz (alle 78) · `Throttle Pos` und `Brake Pos` =
  `%` @ 50 Hz (alle 78, von `normalise` auf 0–1 gebracht) ·
  `Steering Pos` = `%` in 69, `''` in 9 · `Lap Dist` = `m` @ 10 Hz.
- **Schwellen in normalisierten Einheiten:** Bremspunkt bei `brake > 0.05`,
  Gaspunkt bei `throttle > 0.50`. Der alte Stand prüfte `brake > 0.1` gegen
  0–100-Werte und löste damit bei 0,1 % Bremsdruck aus.
- **Die Distanzachse ist 10 Hz.** `Lap Dist` wird auf die Zeitachse des
  jeweiligen Kanals interpoliert, bevor auf das 2-m-Raster resampled wird. Bei
  83 m/s liegen die Stützstellen 8,3 m auseinander; die tatsächliche Auflösung
  eines Bremspunkts ist dadurch begrenzt und muss so benannt werden.
- **Nur saubere Runden** (`quality.clean_laps`) gehen in einen Vergleich.
- Jeder Test braucht einen **Diskriminierungsbeweis**: Verhalten entfernen,
  Test muss rot werden, wiederherstellen.
- pytest-Marker: Tests, die Aufnahmen unter `data/` brauchen, tragen
  `@pytest.mark.corpus`. CI fährt `-m "not corpus"`.

---

## Dateiübersicht

| Datei | Verantwortung |
|---|---|
| `lmu_telemetry/core/trace.py` | eine Runde, jeder Kanal auf dem 2-m-Raster |
| `lmu_telemetry/core/delta.py` | kumulative Zeitdifferenz über die Distanz |
| `lmu_telemetry/core/metrics.py` | Kennzahlen je Kurve und Runde |
| `lmu_telemetry/core/coaching.py` | Zeitverlust je Kurve, nach Ursache zerlegt |

---

### Task 1: Rundenspur auf dem Raster (`trace.py`)

**Dateien:** Erstellen `lmu_telemetry/core/trace.py`,
Test `tests/unit/test_trace.py`

**Schnittstellen:**
- Nutzt: `Session.lap_channel`, `geometry.grid_for`, `geometry.resample_to_grid`,
  `quality.lap_line_on_grid`
- Liefert:
  ```python
  @dataclass(frozen=True)
  class LapTrace:
      lap: Lap
      grid: np.ndarray            # Distanzraster, 2 m
      time_s: np.ndarray          # Zeit seit Rundenbeginn, je Rasterpunkt
      speed_kmh: np.ndarray
      throttle: np.ndarray        # 0..1
      brake: np.ndarray           # 0..1
      def at(self, distance_m: float) -> dict[str, float]
  def build_trace(session, lap, track_length_m) -> LapTrace
  class TraceError(ValueError)
  ```

- [ ] **Schritt 1: Test, der die Zeitachse festnagelt**

```python
def test_time_axis_starts_at_zero_and_ends_at_the_lap_duration(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        trace = build_trace(s, lap, s.track_length_m)
    assert trace.time_s[0] == pytest.approx(0.0, abs=0.05)
    assert trace.time_s[-1] == pytest.approx(lap.duration_s, abs=0.5)
    assert np.all(np.diff(trace.time_s) > 0), "time must advance with distance"
```

- [ ] **Schritt 2: Lauf, muss scheitern** — `pytest tests/unit/test_trace.py -x`,
  erwartet `ModuleNotFoundError`.

- [ ] **Schritt 3: `build_trace` schreiben.** Kern: pro Kanal die eigene
  Zeitachse bilden (`TimeBase.axis_for`), `Lap Dist` darauf interpolieren,
  dann `resample_to_grid`. Die Zeitachse `time_s` entsteht als Umkehrung:
  Zeit als Funktion der Distanz, auf dem Raster.

- [ ] **Schritt 4: Lauf, muss bestehen.**

- [ ] **Schritt 5: Test, dass Einheiten aus dem Register kommen**

```python
def test_speed_stays_in_kmh_and_pedals_are_normalised(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        trace = build_trace(s, lap, s.track_length_m)
    assert 150.0 < trace.speed_kmh.max() < 400.0
    assert 0.0 <= trace.brake.min() and trace.brake.max() <= 1.0
    assert trace.throttle.max() > 0.9, "a qualifying lap reaches full throttle"
```

- [ ] **Schritt 6: Diskriminierungsbeweis.** `normalise` im Pfad umgehen,
  Schritt 5 muss rot werden, zurücknehmen. Ergebnis im Bericht festhalten.

- [ ] **Schritt 7: Commit** — `feat(core): resample one lap onto the distance grid`

---

### Task 2: Delta über die Distanz (`delta.py`)

**Dateien:** Erstellen `lmu_telemetry/core/delta.py`,
Test `tests/unit/test_delta.py`

**Schnittstellen:**
- Nutzt: `LapTrace`
- Liefert:
  ```python
  def delta_s(reference: LapTrace, other: LapTrace) -> np.ndarray
  def gain_loss_per_span(delta: np.ndarray, grid, start_m, end_m) -> float
  ```
  `delta_s[i]` = `other.time_s[i] − reference.time_s[i]`; positiv heißt, die
  Vergleichsrunde liegt an dieser Stelle zurück.

- [ ] **Schritt 1: Test des Vorzeichens und des Endwerts**

```python
def test_delta_ends_at_the_difference_of_the_two_lap_times():
    ref = _synthetic_trace(duration_s=100.0)
    slower = _synthetic_trace(duration_s=101.5)
    d = delta_s(ref, slower)
    assert d[0] == pytest.approx(0.0, abs=1e-9)
    assert d[-1] == pytest.approx(1.5, rel=1e-6)
    assert np.all(d >= -1e-9), "a uniformly slower lap never leads"
```

- [ ] **Schritt 2: Lauf, muss scheitern.**
- [ ] **Schritt 3: `delta_s` schreiben** — Differenz zweier Zeitachsen; beide
  müssen dasselbe Raster tragen, sonst `ValueError` mit beiden Längen.
- [ ] **Schritt 4: Lauf, muss bestehen.**

- [ ] **Schritt 5: Test gegen zwei echte Runden**

```python
@pytest.mark.corpus
def test_delta_over_two_real_laps_matches_their_lap_times(monza_q_file):
    with Session.open(monza_q_file) as s:
        fast, slow = s.laps[2], s.laps[1]
        L = s.track_length_m
        d = delta_s(build_trace(s, fast, L), build_trace(s, slow, L))
    assert d[-1] == pytest.approx(slow.duration_s - fast.duration_s, abs=0.3)
```

- [ ] **Schritt 6: `gain_loss_per_span` mit Wrap.** Eine Kurve, die die
  Start-/Ziellinie enthält, hat `start_m > end_m` (Stufe 3). Der Test dafür:

```python
def test_a_span_that_wraps_the_start_finish_line_is_measured_once():
    grid = grid_for(1000.0)
    d = np.linspace(0.0, 10.0, len(grid))
    whole = gain_loss_per_span(d, grid, 900.0, 100.0)
    assert whole == pytest.approx((d[-1] - d[449]) + (d[49] - d[0]), abs=1e-6)
```

- [ ] **Schritt 7: Commit** — `feat(core): cumulative delta over distance`

---

### Task 3: Kurvenmetriken (`metrics.py`)

**Dateien:** Erstellen `lmu_telemetry/core/metrics.py`,
Test `tests/unit/test_metrics.py`

**Schnittstellen:**
- Nutzt: `LapTrace`, `corners.Corner`
- Liefert:
  ```python
  BRAKE_ON = 0.05        # normalisiert: 5 % Bremsdruck
  THROTTLE_ON = 0.50     # normalisiert: 50 % Gas
  APPROACH_M = 250.0     # wie weit vor Kurvenbeginn nach dem Bremspunkt gesucht wird

  @dataclass(frozen=True)
  class CornerMetrics:
      corner: Corner
      brake_point_m: float | None
      entry_speed_kmh: float
      min_speed_kmh: float
      min_speed_at_m: float
      throttle_point_m: float | None
      exit_speed_kmh: float
      time_s: float
  def corner_metrics(trace: LapTrace, corner: Corner) -> CornerMetrics
  ```
  `brake_point_m` ist `None`, wenn im Anlauf nie gebremst wurde — das ist bei
  einer Vollgaskurve die Wahrheit, kein Fehler.

- [ ] **Schritt 1: Test des Bremspunkts an einer gebauten Spur**

```python
def test_brake_point_is_the_first_distance_above_the_threshold():
    trace = _trace_with(brake=_step(at_m=800.0))     # 0 davor, 0.8 danach
    corner = _corner(start_m=900.0, apex_m=950.0, end_m=1000.0)
    m = corner_metrics(trace, corner)
    assert m.brake_point_m == pytest.approx(800.0, abs=GRID_STEP_M)
```

- [ ] **Schritt 2: Lauf, muss scheitern.**
- [ ] **Schritt 3: `corner_metrics` schreiben.**
- [ ] **Schritt 4: Lauf, muss bestehen.**

- [ ] **Schritt 5: Der Test, der den alten Fehler C festnagelt**

```python
def test_sensor_noise_below_the_threshold_is_not_a_brake_point():
    """Der alte Stand prüfte brake > 0.1 gegen 0-100-Werte und loeste
    damit bei 0,1 % Bremsdruck aus - auf Rauschen."""
    trace = _trace_with(brake=_noise(amplitude=0.02))   # 2 %, dauerhaft
    m = corner_metrics(trace, _corner(900.0, 950.0, 1000.0))
    assert m.brake_point_m is None
```

- [ ] **Schritt 6: Test, dass eine Vollgaskurve keinen Bremspunkt erfindet**
  (Le Mans, Mulsanne-Knick) — `@pytest.mark.corpus`.

- [ ] **Schritt 7: Diskriminierungsbeweis** für `BRAKE_ON`: Schwelle auf 0.001
  setzen, Schritt 5 muss rot werden, zurücknehmen.

- [ ] **Schritt 8: Commit** — `feat(core): per-corner metrics in declared units`

---

### Task 4: Zeitverlust je Kurve, nach Ursache (`coaching.py`)

**Dateien:** Erstellen `lmu_telemetry/core/coaching.py`,
Test `tests/unit/test_coaching.py`

**Schnittstellen:**
- Nutzt: `delta_s`, `gain_loss_per_span`, `CornerMetrics`
- Liefert:
  ```python
  @dataclass(frozen=True)
  class CornerComparison:
      corner: Corner
      lost_s: float                      # positiv: die Vergleichsrunde verliert
      brake_point_delta_m: float | None  # positiv: spaeter gebremst
      min_speed_delta_kmh: float
      throttle_point_delta_m: float | None
      note: str                          # was davon den Verlust traegt
  def compare_corners(reference, other, corners) -> list[CornerComparison]
  ```
  `note` benennt den größten beitragenden Unterschied und nennt seinen Betrag.
  Es wird **kein** Etikett ohne Zahl ausgegeben.

- [ ] **Schritt 1: Test, dass die Kurvenverluste die Rundendifferenz ergeben**

```python
@pytest.mark.corpus
def test_the_corner_losses_and_the_straights_add_up_to_the_lap_delta(monza_q_file):
    ...
    total = sum(c.lost_s for c in comparisons)
    assert total <= lap_delta + 1e-6
    assert total == pytest.approx(lap_delta, abs=0.5 * abs(lap_delta) + 0.2)
```

- [ ] **Schritt 2: Lauf, muss scheitern.**
- [ ] **Schritt 3: `compare_corners` schreiben.**
- [ ] **Schritt 4: Lauf, muss bestehen.**

- [ ] **Schritt 5: Test, dass `note` nie ohne Zahl auskommt**

```python
def test_every_note_names_a_measured_amount():
    for c in _comparisons_from_synthetic():
        assert any(ch.isdigit() for ch in c.note), c.note
```

- [ ] **Schritt 6: Test des Vorzeichens** — später gebremst und trotzdem
  langsamer heraus ergibt Verlust, nicht Gewinn.

- [ ] **Schritt 7: Commit** — `feat(core): attribute time loss to a cause per corner`

---

### Task 5: Vergleich zweier Sessions über das Referenzmodell

**Dateien:** Ändern `lmu_telemetry/core/__init__.py` (öffentliche Fläche),
Test `tests/invariants/test_compare_invariants.py`

- [ ] **Schritt 1: Invariante — beide Seiten teilen eine Kurvenliste**

```python
@pytest.mark.corpus
def test_both_sides_of_a_comparison_use_the_same_corner_list(corpus_files):
    """Fehler D des alten Standes: CompareView.vue holte pro Seite eine
    eigene Kurvenliste, also wurden zwei Fahrer gegen verschiedene
    Kurvendefinitionen verglichen."""
```

- [ ] **Schritt 2–4:** TDD wie oben.
- [ ] **Schritt 5:** Öffentliche Fläche in `core/__init__.py` benennen —
  bisher leer, Stufe 4 importiert sonst Interna.
- [ ] **Schritt 6: Commit** — `feat(core): compare two laps through one track model`

---

## Offene Punkte aus Stufe 3, die hier zu klären sind

1. **Der Apex ist ein fragiler Anker.** `argmax|kappa|` kann bei breiten,
   zweilappigen Kurven zwischen den Lappen springen (Le Mans, Porsche-Kurven 2:
   182 m Sprung bei unveränderten Start-, End- und Winkelwerten). Alle
   Kurvenmetriken hier verankern auf `start_m`/`end_m`, **nicht** auf `apex_m`;
   `apex_m` wird nur berichtet.
2. `TrackModel.corners` ist eine `list`, das eingefrorene Dataclass ist damit
   nicht wirklich unveränderlich.
3. Es gibt keine Basisausnahme der Domäne.
