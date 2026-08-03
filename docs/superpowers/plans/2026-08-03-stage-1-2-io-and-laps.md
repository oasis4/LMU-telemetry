# LMU Telemetry Rework — Stufe 1+2: IO, Kanalregister, Runden, Sektoren

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein neues Python-Paket `lmu_telemetry`, das LMU-`.duckdb`-Dateien einheitenkorrekt liest und Runden- sowie Sektorzeiten ausschließlich aus der Ground Truth der Datei ableitet — damit sind physikalisch unmögliche Rundenzeiten strukturell ausgeschlossen.

**Architecture:** Zwei Schichten. `io/` kapselt den Dateizugriff und das Kanalregister (Einheit + Frequenz kommen aus der `channelsList`-Tabelle, werden nie geraten). `core/` leitet daraus Zeitachse, Runden und Sektoren ab — Rundengrenzen ausschließlich aus dem `Lap`-Event, Sektorzeiten ausschließlich aus den `Current Sector`-Übergängen. `Lap Dist` wird zur Positionsbestimmung *innerhalb* einer Runde benutzt, nie zur Abgrenzung.

**Tech Stack:** Python 3.11, duckdb 1.5, numpy, pytest 7.4. Kein pandas, kein scipy in dieser Stufe.

## Global Constraints

- Zielspec: `docs/superpowers/specs/2026-08-03-lmu-telemetry-rework-design.md`
- Python-Mindestversion: **3.11** (installiert: 3.11.4)
- Alle DuckDB-Verbindungen **read-only**. Telemetriedateien werden nie geschrieben.
- **Keine Heuristik für Größen, die in der Datei stehen.** Fehlt eine Größe, wird `None` zurückgegeben — nie ein Ersatzwert.
- Einheitenumrechnung **ausschließlich** anhand der `unit`-Spalte aus `channelsList`. Niemals anhand beobachteter Wertebereiche.
- Zeitachse eines Kanals: `t_i = gps_time[0] + i / frequency_hz`. Die Frequenz kommt aus `channelsList`.
- Das Korpus-Verzeichnis heißt `LMU Data-20260803T093100Z-1-001/LMU Data/` und ist in `.gitignore`. Tests, die es brauchen, tragen die Markierung `@pytest.mark.corpus` und überspringen sich, wenn es fehlt. Ab Task 9 laufen die Kerntests gegen eingecheckte Fixtures und brauchen den Bestand nicht mehr.
- Alle 40 Korpusdateien haben exakt dieselben 12 Metadatenschlüssel: `CarClass, CarName, CarSetup, DriverName, RecordingTime, SessionTime, SessionType, SteamID, TrackLayout, TrackName, Version, WeatherConditions`.
- Das bestehende `backend/` wird in dieser Stufe **nicht angefasst** und **nicht gelöscht** — das passiert erst, wenn die neue API es ersetzt (Stufe 5).

---

### Task 1: Projektgerüst und Testfundament

**Files:**
- Create: `pyproject.toml`
- Create: `lmu_telemetry/__init__.py`
- Create: `lmu_telemetry/io/__init__.py`
- Create: `lmu_telemetry/core/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_corpus_discovery.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - pytest-Fixture `corpus_dir` → `pathlib.Path` auf das Telemetrieverzeichnis, `pytest.skip` falls nicht vorhanden
  - pytest-Fixture `corpus_files` → `list[pathlib.Path]`, alphabetisch sortiert, nur `*.duckdb`
  - pytest-Fixture `monza_q_file` → `pathlib.Path` auf `Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb` (die Referenzdatei aller Golden-Tests)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_corpus_discovery.py`:

```python
"""The corpus fixtures must find the real telemetry files, or skip cleanly."""


def test_corpus_files_are_duckdb(corpus_files):
    assert len(corpus_files) >= 1
    assert all(f.suffix == ".duckdb" for f in corpus_files)


def test_monza_reference_file_exists(monza_q_file):
    assert monza_q_file.is_file()
    assert monza_q_file.name.startswith("Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_corpus_discovery.py -v`
Expected: FAIL — `fixture 'corpus_files' not found`

- [ ] **Step 3: Write the minimal implementation**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "lmu-telemetry"
version = "1.0.0.dev0"
description = "Telemetry analysis for Le Mans Ultimate"
requires-python = ">=3.11"
dependencies = [
    "duckdb>=1.5",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = ["pytest>=7.4"]

[tool.setuptools.packages.find]
include = ["lmu_telemetry*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = [
    "corpus: test requires the full local telemetry corpus",
]
```

Create `lmu_telemetry/__init__.py`:

```python
"""Telemetry analysis for Le Mans Ultimate."""

__version__ = "1.0.0.dev0"
```

Create `lmu_telemetry/io/__init__.py` and `lmu_telemetry/core/__init__.py`, both containing only:

```python
```

(empty files)

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
"""Shared fixtures. The telemetry corpus is gitignored, so every fixture that
needs it skips cleanly when it is absent (e.g. on CI)."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"

# The reference session for all golden tests: Monza qualifying, 3 complete laps,
# known lap times 131.085 / 116.560 / 111.000 s.
MONZA_Q_NAME = "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb"


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    if not CORPUS_DIR.is_dir():
        pytest.skip(f"telemetry corpus not present at {CORPUS_DIR}")
    return CORPUS_DIR


@pytest.fixture(scope="session")
def corpus_files(corpus_dir: Path) -> list[Path]:
    return sorted(corpus_dir.glob("*.duckdb"))


@pytest.fixture(scope="session")
def monza_q_file(corpus_dir: Path) -> Path:
    path = corpus_dir / MONZA_Q_NAME
    if not path.is_file():
        pytest.skip(f"reference session missing: {path}")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_corpus_discovery.py -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Install the package in editable mode**

Run: `python -m pip install -e ".[dev]"`
Expected: `Successfully installed lmu-telemetry-1.0.0.dev0`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml lmu_telemetry tests
git commit -m "feat: add lmu_telemetry package skeleton and corpus test fixtures"
```

---

### Task 2: Kanalregister — Einheiten und Frequenzen aus der Datei

Dies ist der Fix für Ursache C und B aus der Spec: Pedalkanäle liegen in 0–100 %, Lenkwinkel je nach Datei in `±1` (unit `''`) oder `±100` (unit `'%'`).

**Files:**
- Create: `lmu_telemetry/io/channels.py`
- Test: `tests/unit/test_channels.py`

**Interfaces:**
- Consumes: nichts
- Produces:
  - `ChannelSpec(name: str, frequency_hz: int, unit: str)` — frozen dataclass
  - `ChannelRegistry.from_connection(con) -> ChannelRegistry`
  - `ChannelRegistry.get(name: str) -> ChannelSpec | None`
  - `ChannelRegistry.require(name: str) -> ChannelSpec` — wirft `MissingChannelError`
  - `ChannelRegistry.__contains__(name: str) -> bool`
  - `ChannelRegistry.names() -> list[str]`
  - `normalise(values: np.ndarray, spec: ChannelSpec) -> np.ndarray`
  - `MissingChannelError(KeyError)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_channels.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.io.channels import (
    ChannelRegistry,
    ChannelSpec,
    MissingChannelError,
    normalise,
)


def test_percent_channel_is_scaled_to_fraction():
    spec = ChannelSpec(name="Throttle Pos", frequency_hz=50, unit="%")
    out = normalise(np.array([0.0, 50.0, 100.0]), spec)
    assert np.allclose(out, [0.0, 0.5, 1.0])


def test_percent_scaling_uses_100_not_observed_maximum():
    """A lap where the driver never reached full lock must NOT be stretched.

    One Le Mans session has |Steering Pos| max 93.023 with unit '%'.
    Dividing by the observed maximum would report 93% lock as 100%.
    """
    spec = ChannelSpec(name="Steering Pos", frequency_hz=100, unit="%")
    out = normalise(np.array([-93.023, 0.0, 46.5]), spec)
    assert np.isclose(out[0], -0.93023)
    assert np.isclose(out[2], 0.465)


def test_unitless_channel_is_passed_through():
    spec = ChannelSpec(name="Steering Pos", frequency_hz=100, unit="")
    values = np.array([-0.8085, 0.0, 0.5079])
    out = normalise(values, spec)
    assert np.allclose(out, values)


def test_metre_channel_is_passed_through():
    spec = ChannelSpec(name="Lap Dist", frequency_hz=10, unit="m")
    values = np.array([0.0, 2887.5, 5775.0])
    assert np.allclose(normalise(values, spec), values)


def test_normalise_does_not_mutate_input():
    spec = ChannelSpec(name="Brake Pos", frequency_hz=50, unit="%")
    values = np.array([100.0])
    normalise(values, spec)
    assert values[0] == 100.0


@pytest.mark.corpus
def test_registry_reads_real_channel_list(monza_q_file):
    import duckdb

    con = duckdb.connect(str(monza_q_file), read_only=True)
    try:
        reg = ChannelRegistry.from_connection(con)
    finally:
        con.close()

    assert reg.require("Ground Speed") == ChannelSpec("Ground Speed", 100, "km/h")
    assert reg.require("Lap Dist") == ChannelSpec("Lap Dist", 10, "m")
    assert reg.require("Throttle Pos") == ChannelSpec("Throttle Pos", 50, "%")
    assert reg.require("Brake Pos") == ChannelSpec("Brake Pos", 50, "%")
    assert reg.require("GPS Speed") == ChannelSpec("GPS Speed", 10, "m/s")
    assert reg.require("GPS Time") == ChannelSpec("GPS Time", 100, "s")
    assert "Lap" not in reg  # events are not channels
    assert len(reg.names()) == 56


@pytest.mark.corpus
def test_require_raises_for_unknown_channel(monza_q_file):
    import duckdb

    con = duckdb.connect(str(monza_q_file), read_only=True)
    try:
        reg = ChannelRegistry.from_connection(con)
    finally:
        con.close()
    with pytest.raises(MissingChannelError):
        reg.require("No Such Channel")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_channels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.io.channels'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/io/channels.py`:

```python
"""Channel metadata read from the file's own ``channelsList`` table.

Every LMU telemetry file declares, for each continuous channel, its sampling
frequency and its unit.  Reading that table is the difference between knowing
that ``Brake Pos`` is a percentage and guessing that it is a 0..1 fraction.

The unit genuinely varies between files: ``Steering Pos`` is reported unitless
(range +-1) in most sessions and as a percentage (range +-100) in others.  The
unit column is the only reliable discriminator - the observed value range is
not, because a driver who never reaches full lock produces a smaller maximum.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class MissingChannelError(KeyError):
    """Raised when a required channel is absent from the file."""


@dataclass(frozen=True)
class ChannelSpec:
    """Declared properties of one continuous channel."""

    name: str
    frequency_hz: int
    unit: str


#: Unit -> factor applied to convert into the canonical representation.
#: Percentages become 0..1 fractions.  Everything else is already canonical.
_UNIT_FACTORS: dict[str, float] = {"%": 0.01}


def normalise(values: np.ndarray, spec: ChannelSpec) -> np.ndarray:
    """Convert *values* into canonical units for *spec*.

    Returns a new array; the input is never modified.
    """
    factor = _UNIT_FACTORS.get(spec.unit)
    if factor is None:
        return np.asarray(values, dtype=np.float64).copy()
    return np.asarray(values, dtype=np.float64) * factor


class ChannelRegistry:
    """Lookup of :class:`ChannelSpec` by channel name."""

    def __init__(self, specs: dict[str, ChannelSpec]) -> None:
        self._specs = specs

    @classmethod
    def from_connection(cls, con) -> "ChannelRegistry":
        rows = con.execute(
            'SELECT channelName, frequency, unit FROM "channelsList"'
        ).fetchall()
        specs = {
            str(name): ChannelSpec(
                name=str(name),
                frequency_hz=int(freq),
                unit="" if unit is None else str(unit),
            )
            for name, freq, unit in rows
        }
        return cls(specs)

    def get(self, name: str) -> ChannelSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ChannelSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise MissingChannelError(name)
        return spec

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def names(self) -> list[str]:
        return sorted(self._specs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_channels.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/io/channels.py tests/unit/test_channels.py
git commit -m "feat: read channel units and frequencies from channelsList

Pedal channels are 0-100% and steering is unitless in some files and
percent in others. The unit column is the only reliable discriminator;
scaling by the observed maximum misreports partial lock as full lock."
```

---

### Task 3: Dateizugriff

**Files:**
- Create: `lmu_telemetry/io/duckdb_source.py`
- Test: `tests/unit/test_duckdb_source.py`

**Interfaces:**
- Consumes: `ChannelRegistry`, `ChannelSpec`, `normalise`, `MissingChannelError` aus Task 2
- Produces:
  - `TelemetryFile(path: str | Path)` — Kontextmanager
  - `TelemetryFile.metadata -> dict[str, str]` (property, gecacht)
  - `TelemetryFile.channels -> ChannelRegistry` (property, gecacht)
  - `TelemetryFile.raw_channel(name: str) -> np.ndarray` — unveränderte Werte
  - `TelemetryFile.channel(name: str) -> np.ndarray` — einheitennormalisiert
  - `TelemetryFile.events(name: str) -> tuple[np.ndarray, np.ndarray] | None` — `(ts, value)`, nach `ts` sortiert
  - `TelemetryFile.has_event(name: str) -> bool`
  - `TelemetryFile.close() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_duckdb_source.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.io.channels import MissingChannelError
from lmu_telemetry.io.duckdb_source import TelemetryFile

pytestmark = pytest.mark.corpus


def test_metadata_has_the_twelve_known_keys(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        meta = tf.metadata
    assert set(meta) == {
        "CarClass", "CarName", "CarSetup", "DriverName", "RecordingTime",
        "SessionTime", "SessionType", "SteamID", "TrackLayout", "TrackName",
        "Version", "WeatherConditions",
    }
    assert meta["TrackName"] == "Autodromo Nazionale Monza"
    assert meta["SessionType"] == "Qualify"
    assert meta["CarClass"] == "GT3"
    assert meta["DriverName"] == "A Mueller"


def test_raw_channel_returns_declared_percent_range(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        raw = tf.raw_channel("Throttle Pos")
    assert len(raw) == 18282
    assert raw.max() == pytest.approx(100.0)


def test_channel_is_normalised_to_fraction(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        thr = tf.channel("Throttle Pos")
    assert thr.max() == pytest.approx(1.0)
    assert thr.min() == pytest.approx(0.0)


def test_lap_dist_is_not_rescaled(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        dist = tf.channel("Lap Dist")
    assert len(dist) == 3657
    assert dist.max() == pytest.approx(5776.076, abs=0.01)


def test_events_are_sorted_pairs(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        ts, val = tf.events("Lap")
    assert np.allclose(ts, [12.575, 143.66, 260.22, 371.22])
    assert np.allclose(val, [0, 1, 2, 3])
    assert np.all(np.diff(ts) > 0)


def test_events_returns_none_for_unknown_table(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        assert tf.events("No Such Event") is None
        assert tf.has_event("Lap") is True
        assert tf.has_event("No Such Event") is False


def test_unknown_channel_raises(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        with pytest.raises(MissingChannelError):
            tf.channel("No Such Channel")


def test_every_corpus_file_opens_and_reports_metadata(corpus_files):
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            meta = tf.metadata
            assert meta["TrackName"], f"{path.name} has no TrackName"
            assert meta["TrackLayout"], f"{path.name} has no TrackLayout"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_duckdb_source.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.io.duckdb_source'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/io/duckdb_source.py`:

```python
"""Read-only access to a single LMU ``.duckdb`` telemetry file.

Tables come in two shapes:

* **Channels** - a bare ``value`` column sampled at a fixed frequency, with no
  timestamps.  The frequency is declared in ``channelsList``.
* **Events** - ``ts`` plus ``value``, written only when the value changes.

Nothing here interprets the data; that is the job of :mod:`lmu_telemetry.core`.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from .channels import ChannelRegistry, MissingChannelError, normalise


class TelemetryFile:
    """One telemetry file, opened read-only."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._con = duckdb.connect(str(self.path), read_only=True)
        self._metadata: dict[str, str] | None = None
        self._channels: ChannelRegistry | None = None
        self._tables: set[str] | None = None

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "TelemetryFile":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- schema ------------------------------------------------------------

    @property
    def tables(self) -> set[str]:
        if self._tables is None:
            rows = self._con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE'"
            ).fetchall()
            self._tables = {str(r[0]) for r in rows}
        return self._tables

    @property
    def metadata(self) -> dict[str, str]:
        if self._metadata is None:
            rows = self._con.execute('SELECT key, value FROM "metadata"').fetchall()
            self._metadata = {str(k): str(v) for k, v in rows}
        return self._metadata

    @property
    def channels(self) -> ChannelRegistry:
        if self._channels is None:
            self._channels = ChannelRegistry.from_connection(self._con)
        return self._channels

    # -- data --------------------------------------------------------------

    def raw_channel(self, name: str) -> np.ndarray:
        """Channel values exactly as stored."""
        self.channels.require(name)
        if name not in self.tables:
            raise MissingChannelError(name)
        col = self._con.execute(f'SELECT value FROM "{name}"').fetchnumpy()["value"]
        return np.asarray(col, dtype=np.float64)

    def channel(self, name: str) -> np.ndarray:
        """Channel values converted into canonical units."""
        spec = self.channels.require(name)
        return normalise(self.raw_channel(name), spec)

    def has_event(self, name: str) -> bool:
        if name not in self.tables:
            return False
        cols = {
            str(r[1])
            for r in self._con.execute(f'PRAGMA table_info("{name}")').fetchall()
        }
        return "ts" in cols and "value" in cols

    def events(self, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return ``(timestamps, values)`` sorted by timestamp, or ``None``."""
        if not self.has_event(name):
            return None
        rows = self._con.execute(
            f'SELECT ts, value FROM "{name}" ORDER BY ts'
        ).fetchall()
        if not rows:
            return np.empty(0), np.empty(0)
        ts = np.array([float(r[0]) for r in rows], dtype=np.float64)
        val = np.array([float(r[1]) for r in rows], dtype=np.float64)
        return ts, val
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_duckdb_source.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/io/duckdb_source.py tests/unit/test_duckdb_source.py
git commit -m "feat: add read-only TelemetryFile with unit-aware channel access"
```

---

### Task 4: Zeitachse

Kanäle haben keine Zeitstempel, Events schon. Ohne korrekte Zuordnung schneidet Task 5 die Runden falsch.

Empirisch über alle 40 Dateien und 224 Distanz-Resets geprüft (Referenz: Reset muss auf ein `Lap`-Event fallen): `gps_time[0] + i / f` erreicht Median 0,0525 s und p90 0,0925 s — beides unter einer 10-Hz-Sample-Breite. Die von der Altlösung benutzte `linspace`-Streckung erreicht nur Median 0,0774 s / p90 0,1464 s.

**Files:**
- Create: `lmu_telemetry/core/timebase.py`
- Test: `tests/unit/test_timebase.py`

**Interfaces:**
- Consumes: `TelemetryFile` aus Task 3
- Produces:
  - `TimeBase(t0: float)` — frozen dataclass
  - `TimeBase.from_file(tf: TelemetryFile) -> TimeBase`
  - `TimeBase.axis(n_samples: int, frequency_hz: int) -> np.ndarray`
  - `TimeBase.axis_for(tf: TelemetryFile, channel_name: str) -> np.ndarray`
  - `TimeBase.index_at(time_s: float, frequency_hz: int) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_timebase.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_axis_starts_at_t0_and_steps_by_one_over_frequency():
    tb = TimeBase(t0=12.575)
    axis = tb.axis(n_samples=4, frequency_hz=10)
    assert np.allclose(axis, [12.575, 12.675, 12.775, 12.875])


def test_axis_rejects_non_positive_frequency():
    tb = TimeBase(t0=0.0)
    with pytest.raises(ValueError):
        tb.axis(n_samples=10, frequency_hz=0)


def test_index_at_rounds_to_nearest_sample():
    tb = TimeBase(t0=12.575)
    assert tb.index_at(12.575, 10) == 0
    assert tb.index_at(12.675, 10) == 1
    assert tb.index_at(143.575, 10) == 1310
    assert tb.index_at(0.0, 10) == 0  # clamped, never negative


@pytest.mark.corpus
def test_axis_from_real_file_matches_gps_time_start(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        tb = TimeBase.from_file(tf)
        axis = tb.axis_for(tf, "Lap Dist")
        gps = tf.channel("GPS Time")
    assert tb.t0 == pytest.approx(12.575)
    assert len(axis) == 3657
    assert axis[0] == pytest.approx(gps[0])


@pytest.mark.corpus
def test_lap_dist_resets_land_on_lap_events(monza_q_file):
    """The hard external check: a Lap Dist reset marks a lap start, so it must
    coincide with a Lap event to within one 10 Hz sample."""
    with TelemetryFile(monza_q_file) as tf:
        tb = TimeBase.from_file(tf)
        dist = tf.channel("Lap Dist")
        axis = tb.axis_for(tf, "Lap Dist")
        lap_ts, _ = tf.events("Lap")

    reset_idx = np.where(np.diff(dist) < -50.0)[0] + 1
    assert len(reset_idx) == 3
    for i in reset_idx:
        gap = np.min(np.abs(lap_ts - axis[i]))
        assert gap < 0.10, f"reset at sample {i} is {gap:.3f}s from any Lap event"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_timebase.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.timebase'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/timebase.py`:

```python
"""Mapping between channel sample indices and event timestamps.

Channels carry no timestamps - only a fixed sampling frequency declared in
``channelsList``.  Events carry timestamps in the same clock as the ``GPS Time``
channel.  Sample *i* of a channel running at *f* Hz therefore occurs at::

    t_i = gps_time[0] + i / f

Verified across the whole corpus (40 files, 224 Lap Dist resets) against the
external fact that a distance reset must coincide with a Lap event: median
error 0.0525 s, p90 0.0925 s - both inside one 10 Hz sample.  Stretching the
GPS Time array onto the channel length instead gives 0.0774 s / 0.1464 s.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TimeBase:
    """Session clock origin, taken from the first ``GPS Time`` sample."""

    t0: float

    @classmethod
    def from_file(cls, tf) -> "TimeBase":
        gps = tf.channel("GPS Time")
        if len(gps) == 0:
            raise ValueError(f"{tf.path.name}: GPS Time channel is empty")
        return cls(t0=float(gps[0]))

    def axis(self, n_samples: int, frequency_hz: int) -> np.ndarray:
        """Timestamps for *n_samples* consecutive samples at *frequency_hz*."""
        if frequency_hz <= 0:
            raise ValueError(f"frequency must be positive, got {frequency_hz}")
        return self.t0 + np.arange(n_samples, dtype=np.float64) / frequency_hz

    def axis_for(self, tf, channel_name: str) -> np.ndarray:
        """Timestamps for every sample of *channel_name* in *tf*."""
        spec = tf.channels.require(channel_name)
        n = len(tf.raw_channel(channel_name))
        return self.axis(n, spec.frequency_hz)

    def index_at(self, time_s: float, frequency_hz: int) -> int:
        """Nearest sample index at *frequency_hz* for absolute *time_s*."""
        if frequency_hz <= 0:
            raise ValueError(f"frequency must be positive, got {frequency_hz}")
        idx = int(round((time_s - self.t0) * frequency_hz))
        return max(idx, 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_timebase.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/timebase.py tests/unit/test_timebase.py
git commit -m "feat: add TimeBase mapping channel samples to event timestamps

Verified against 224 Lap Dist resets across the corpus: median error
0.0525s, below one 10 Hz sample."
```

---

### Task 5: Rundensegmentierung aus `Lap`-Events

Dies ist der Fix für Ursache A. Rundenzeit = Differenz zweier `Lap`-Zeitstempel. Es gibt keinen anderen Pfad.

**Files:**
- Create: `lmu_telemetry/core/laps.py`
- Test: `tests/unit/test_laps.py`

**Interfaces:**
- Consumes: `TelemetryFile` (Task 3), `TimeBase` (Task 4)
- Produces:
  - `Lap` — frozen dataclass mit `number: int`, `t_start: float`, `t_end: float`, `duration_s: float`, `sectors_s: tuple[float, float, float] | None`, `touched_pits: bool`, `distance_m: float`
  - `segment_laps(tf: TelemetryFile, timebase: TimeBase) -> list[Lap]` — nur vollständige Runden
  - `NoLapDataError(ValueError)`

Sektoren füllt Task 6; hier ist `sectors_s` zunächst immer `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_laps.py`:

```python
import pytest

from lmu_telemetry.core.laps import Lap, segment_laps
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile

pytestmark = pytest.mark.corpus


def _laps(path):
    with TelemetryFile(path) as tf:
        return segment_laps(tf, TimeBase.from_file(tf))


def test_monza_qualifying_has_exactly_three_complete_laps(monza_q_file):
    laps = _laps(monza_q_file)
    assert [l.number for l in laps] == [0, 1, 2]


def test_lap_durations_come_from_lap_event_timestamps(monza_q_file):
    """Ground truth: Lap events at 12.575 / 143.66 / 260.22 / 371.22."""
    laps = _laps(monza_q_file)
    assert [round(l.duration_s, 3) for l in laps] == [131.085, 116.560, 111.000]


def test_trailing_incomplete_lap_is_dropped(monza_q_file):
    """The file has 4 Lap events, so only 3 laps are bounded on both sides."""
    with TelemetryFile(monza_q_file) as tf:
        n_events = len(tf.events("Lap")[0])
        laps = segment_laps(tf, TimeBase.from_file(tf))
    assert n_events == 4
    assert len(laps) == 3


def test_out_lap_is_flagged_as_having_touched_the_pits(monza_q_file):
    """In Pits goes 1 -> 0 at t=31.96, inside lap 0."""
    laps = _laps(monza_q_file)
    assert laps[0].touched_pits is True
    assert laps[1].touched_pits is False
    assert laps[2].touched_pits is False


def test_distance_covered_is_about_one_track_length(monza_q_file):
    laps = _laps(monza_q_file)
    for lap in laps[1:]:  # the out lap starts in the pit lane
        assert 5600.0 < lap.distance_m < 5900.0


def test_sessions_without_two_lap_events_yield_no_laps(corpus_dir):
    """Seven corpus sessions were abandoned before completing a lap."""
    path = corpus_dir / "Autodromo Nazionale Monza_Q_2026-03-27T09_02_56Z.duckdb"
    if not path.is_file():
        pytest.skip("edge-case session not present")
    assert _laps(path) == []


def test_no_lap_in_the_corpus_is_physically_impossible(corpus_files):
    """A lap cannot be faster than the track length at 400 km/h.

    This is the structural guarantee that replaces the old median heuristics:
    the duration comes from the game clock, so it cannot be fabricated.
    """
    max_speed_ms = 400.0 / 3.6
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            laps = segment_laps(tf, TimeBase.from_file(tf))
            track_len = float(tf.channel("Lap Dist").max()) if laps else 0.0
        for lap in laps:
            floor = track_len / max_speed_ms
            assert lap.duration_s >= floor, (
                f"{path.name} lap {lap.number}: {lap.duration_s:.2f}s "
                f"is below the {floor:.2f}s physical floor"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_laps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.laps'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/laps.py`:

```python
"""Lap segmentation.

A lap exists only between two consecutive ``Lap`` events, and its duration is
the difference of their timestamps.  There is deliberately no fallback path:
if the game did not record the boundary, no lap is reported.

``Lap Dist`` is used to measure distance *within* a lap, never to delimit one.
Its resets are unreliable - across the corpus one Monza session has 12 ``Lap``
events but 13 distance resets, another 5 against 6.  Treating those resets as
lap boundaries produced partial laps that were then reported as full ones,
which is where the impossible lap times came from.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .timebase import TimeBase


class NoLapDataError(ValueError):
    """Raised when a file carries no ``Lap`` event table at all."""


@dataclass(frozen=True)
class Lap:
    """One complete lap, bounded by two ``Lap`` events."""

    number: int
    t_start: float
    t_end: float
    duration_s: float
    sectors_s: tuple[float, float, float] | None
    touched_pits: bool
    distance_m: float


def _touched_pits(tf, t_start: float, t_end: float) -> bool:
    events = tf.events("In Pits")
    if events is None:
        return False
    ts, val = events
    inside = (ts >= t_start) & (ts < t_end)
    if np.any(val[inside] != 0):
        return True
    # Also honour the state carried into the lap from an earlier event.
    before = ts < t_start
    return bool(np.any(before)) and float(val[before][-1]) != 0.0


def _distance_covered(tf, timebase: TimeBase, t_start: float, t_end: float) -> float:
    """Metres covered in the interval, summing across any Lap Dist reset."""
    spec = tf.channels.get("Lap Dist")
    if spec is None:
        return 0.0
    dist = tf.channel("Lap Dist")
    i0 = min(timebase.index_at(t_start, spec.frequency_hz), len(dist))
    i1 = min(timebase.index_at(t_end, spec.frequency_hz), len(dist))
    segment = dist[i0:i1]
    if len(segment) < 2:
        return 0.0
    steps = np.diff(segment)
    return float(np.sum(steps[steps > 0.0]))


def segment_laps(tf, timebase: TimeBase) -> list[Lap]:
    """Return every lap that is bounded by two consecutive ``Lap`` events."""
    events = tf.events("Lap")
    if events is None:
        raise NoLapDataError(f"{tf.path.name}: no 'Lap' event table")
    ts, numbers = events
    if len(ts) < 2:
        return []

    laps: list[Lap] = []
    for i in range(len(ts) - 1):
        t_start = float(ts[i])
        t_end = float(ts[i + 1])
        laps.append(
            Lap(
                number=int(numbers[i]),
                t_start=t_start,
                t_end=t_end,
                duration_s=t_end - t_start,
                sectors_s=None,
                touched_pits=_touched_pits(tf, t_start, t_end),
                distance_m=_distance_covered(tf, timebase, t_start, t_end),
            )
        )
    return laps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_laps.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/laps.py tests/unit/test_laps.py
git commit -m "feat: derive laps from Lap events instead of Lap Dist resets

Lap duration is now the difference of two game-recorded timestamps, so
impossible lap times cannot be produced. Replaces eight heuristic
validation stages that existed only to mask fabricated times."
```

---

### Task 6: Sektorzeiten aus `Current Sector`-Übergängen

Über den gesamten Bestand geprüft: 190 von 190 Runden liefern eine Sektorsumme, die exakt der Rundenzeit entspricht.

**Files:**
- Create: `lmu_telemetry/core/sectors.py`
- Modify: `lmu_telemetry/core/laps.py` — `segment_laps` füllt `sectors_s`
- Test: `tests/unit/test_sectors.py`

**Interfaces:**
- Consumes: `TelemetryFile` (Task 3), `Lap` (Task 5)
- Produces:
  - `sector_times(sector_events: tuple[np.ndarray, np.ndarray] | None, t_start: float, t_end: float) -> tuple[float, float, float] | None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sectors.py`:

```python
import numpy as np
import pytest

from lmu_telemetry.core.laps import segment_laps
from lmu_telemetry.core.sectors import sector_times
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_three_marks_split_the_lap_into_three_sectors():
    ts = np.array([260.22, 297.02, 334.62])
    val = np.array([1.0, 2.0, 0.0])
    out = sector_times((ts, val), t_start=260.22, t_end=371.22)
    assert out == pytest.approx((36.80, 37.60, 36.60))
    assert sum(out) == pytest.approx(111.00)


def test_missing_events_give_none():
    assert sector_times(None, 0.0, 100.0) is None


def test_wrong_number_of_marks_gives_none():
    """Honest failure beats a fabricated split."""
    ts = np.array([260.22, 297.02])
    val = np.array([1.0, 2.0])
    assert sector_times((ts, val), t_start=260.22, t_end=371.22) is None


@pytest.mark.corpus
def test_monza_reference_lap_sectors(monza_q_file):
    with TelemetryFile(monza_q_file) as tf:
        laps = segment_laps(tf, TimeBase.from_file(tf))
    assert laps[2].sectors_s == pytest.approx((36.80, 37.60, 36.60))
    assert laps[1].sectors_s == pytest.approx((37.02, 38.10, 41.44))
    assert laps[0].sectors_s == pytest.approx((56.305, 37.88, 36.90))


@pytest.mark.corpus
def test_sector_sum_equals_lap_time_for_every_corpus_lap(corpus_files):
    """The invariant that proves the extraction is correct: 190/190 laps."""
    checked = 0
    for path in corpus_files:
        with TelemetryFile(path) as tf:
            laps = segment_laps(tf, TimeBase.from_file(tf))
        for lap in laps:
            if lap.sectors_s is None:
                continue
            assert sum(lap.sectors_s) == pytest.approx(lap.duration_s, abs=0.02), (
                f"{path.name} lap {lap.number}"
            )
            checked += 1
    assert checked >= 180, f"only {checked} laps had sector data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_sectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.sectors'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/sectors.py`:

```python
"""Sector times from ``Current Sector`` transitions.

The ``Current Sector`` event fires whenever the car crosses a sector line, so
the three transitions inside a lap delimit the three sectors exactly.  The lap
start is itself the first transition (into sector 1).

Verified over the whole corpus: 190 of 190 laps reconstruct a sector split
whose sum matches the lap duration to better than 20 ms.  The previous
implementation matched separate ``Current Sector1`` / ``Current Sector2``
events with a fuzzy time window and fell back to splitting the lap into
distance thirds when that failed.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-9


def sector_times(
    sector_events: tuple[np.ndarray, np.ndarray] | None,
    t_start: float,
    t_end: float,
) -> tuple[float, float, float] | None:
    """Return ``(s1, s2, s3)`` in seconds, or ``None`` if not derivable."""
    if sector_events is None:
        return None
    ts, _values = sector_events
    marks = ts[(ts >= t_start - _EPS) & (ts < t_end - _EPS)]
    if len(marks) != 3:
        return None
    return (
        float(marks[1] - marks[0]),
        float(marks[2] - marks[1]),
        float(t_end - marks[2]),
    )
```

- [ ] **Step 4: Wire it into `segment_laps`**

In `lmu_telemetry/core/laps.py`, add the import below the existing `from .timebase import TimeBase`:

```python
from .sectors import sector_times
```

Then in `segment_laps`, insert this line directly after `if len(ts) < 2: return []`:

```python
    sector_events = tf.events("Current Sector")
```

and replace `sectors_s=None,` in the `Lap(...)` construction with:

```python
                sectors_s=sector_times(sector_events, t_start, t_end),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_sectors.py tests/unit/test_laps.py -v`
Expected: PASS — 12 passed

- [ ] **Step 6: Commit**

```bash
git add lmu_telemetry/core/sectors.py lmu_telemetry/core/laps.py tests/unit/test_sectors.py
git commit -m "feat: derive sector times from Current Sector transitions

Verified across the corpus: 190/190 laps reconstruct a split whose sum
matches the lap duration within 20 ms."
```

---

### Task 7: Session-Fassade

Eine Klasse, die Datei, Zeitachse und Runden zusammenfasst, damit spätere Stufen nicht jedes Mal drei Objekte verdrahten.

**Files:**
- Create: `lmu_telemetry/core/session.py`
- Test: `tests/unit/test_session.py`

**Interfaces:**
- Consumes: `TelemetryFile` (Task 3), `TimeBase` (Task 4), `segment_laps`, `Lap` (Task 5)
- Produces:
  - `SessionInfo` — frozen dataclass: `track: str`, `layout: str`, `car: str`, `car_class: str`, `driver: str`, `session_type: str`, `recorded_at: str`
  - `Session.open(path) -> Session` — Kontextmanager
  - `Session.info -> SessionInfo`
  - `Session.laps -> list[Lap]` (gecacht; enthält per Definition nur vollständige Runden)
  - `Session.track_length_m -> float`
  - `Session.fastest_lap -> Lap | None` — schnellste Runde ohne Boxenberührung
  - `Session.close() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_session.py`:

```python
import pytest

from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus


def test_info_is_read_from_metadata(monza_q_file):
    with Session.open(monza_q_file) as s:
        info = s.info
    assert info.track == "Autodromo Nazionale Monza"
    assert info.layout == "Autodromo Nazionale Monza"
    assert info.car_class == "GT3"
    assert info.driver == "A Mueller"
    assert info.session_type == "Qualify"


def test_track_length_is_the_maximum_lap_distance(monza_q_file):
    with Session.open(monza_q_file) as s:
        assert s.track_length_m == pytest.approx(5776.08, abs=0.1)


def test_fastest_lap_excludes_the_out_lap(monza_q_file):
    with Session.open(monza_q_file) as s:
        fastest = s.fastest_lap
    assert fastest is not None
    assert fastest.number == 2
    assert fastest.duration_s == pytest.approx(111.000)


def test_every_corpus_session_reports_plausible_fastest_lap(corpus_files):
    """Nothing in the corpus may look like a world record.

    Ranges are the known real-world envelope per track length, deliberately
    generous: the point is to catch fabricated times, not to grade driving.
    """
    for path in corpus_files:
        with Session.open(path) as s:
            fastest = s.fastest_lap
            length = s.track_length_m
        if fastest is None:
            continue
        # No car in any class averages more than 300 km/h over a full lap.
        floor = length / (300.0 / 3.6)
        assert fastest.duration_s > floor, (
            f"{path.name}: {fastest.duration_s:.2f}s over {length:.0f}m "
            f"implies more than 300 km/h average"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lmu_telemetry.core.session'`

- [ ] **Step 3: Write the minimal implementation**

Create `lmu_telemetry/core/session.py`:

```python
"""One recorded session: file, clock and laps in a single object."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..io.duckdb_source import TelemetryFile
from .laps import Lap, segment_laps
from .timebase import TimeBase


@dataclass(frozen=True)
class SessionInfo:
    """Descriptive metadata, read verbatim from the file."""

    track: str
    layout: str
    car: str
    car_class: str
    driver: str
    session_type: str
    recorded_at: str


class Session:
    """A telemetry file together with its derived laps."""

    def __init__(self, file: TelemetryFile) -> None:
        self._file = file
        self._timebase = TimeBase.from_file(file)
        self._laps: list[Lap] | None = None
        self._track_length: float | None = None

    @classmethod
    def open(cls, path: str | Path) -> "Session":
        return cls(TelemetryFile(path))

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @property
    def file(self) -> TelemetryFile:
        return self._file

    @property
    def timebase(self) -> TimeBase:
        return self._timebase

    @property
    def info(self) -> SessionInfo:
        meta = self._file.metadata
        return SessionInfo(
            track=meta.get("TrackName", ""),
            layout=meta.get("TrackLayout", ""),
            car=meta.get("CarName", ""),
            car_class=meta.get("CarClass", ""),
            driver=meta.get("DriverName", ""),
            session_type=meta.get("SessionType", ""),
            recorded_at=meta.get("RecordingTime", ""),
        )

    @property
    def laps(self) -> list[Lap]:
        if self._laps is None:
            self._laps = segment_laps(self._file, self._timebase)
        return self._laps

    @property
    def track_length_m(self) -> float:
        if self._track_length is None:
            if "Lap Dist" not in self._file.channels:
                self._track_length = 0.0
            else:
                dist = self._file.channel("Lap Dist")
                self._track_length = float(dist.max()) if len(dist) else 0.0
        return self._track_length

    @property
    def fastest_lap(self) -> Lap | None:
        candidates = [l for l in self.laps if not l.touched_pits]
        if not candidates:
            return None
        return min(candidates, key=lambda l: l.duration_s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_session.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Commit**

```bash
git add lmu_telemetry/core/session.py tests/unit/test_session.py
git commit -m "feat: add Session facade over file, timebase and laps"
```

---

### Task 8: Golden- und Invariantentests über den gesamten Bestand

Der Regressionsschutz, den es vorher nicht gab. Frieren die heute verifizierten Werte ein.

**Files:**
- Create: `tests/golden/__init__.py`
- Create: `tests/golden/expected_laps.json`
- Create: `tests/golden/test_golden_laps.py`
- Create: `tests/invariants/__init__.py`
- Create: `tests/invariants/test_corpus_invariants.py`

**Interfaces:**
- Consumes: `Session` (Task 7), `Lap` (Task 5)
- Produces: nichts (nur Tests)

- [ ] **Step 1: Write the golden data file**

Create `tests/golden/expected_laps.json`. These values were read from the files and verified by hand:

```json
{
  "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb": {
    "track": "Autodromo Nazionale Monza",
    "car_class": "GT3",
    "track_length_m": 5776.08,
    "laps": [
      {"number": 0, "duration_s": 131.085, "sectors_s": [56.305, 37.880, 36.900], "touched_pits": true},
      {"number": 1, "duration_s": 116.560, "sectors_s": [37.020, 38.100, 41.440], "touched_pits": false},
      {"number": 2, "duration_s": 111.000, "sectors_s": [36.800, 37.600, 36.600], "touched_pits": false}
    ]
  }
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/golden/__init__.py` and `tests/invariants/__init__.py` (both empty files).

Create `tests/golden/test_golden_laps.py`:

```python
"""Frozen expectations. Any change that moves a lap time or a sector fails."""

import json
from pathlib import Path

import pytest

from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus

GOLDEN = json.loads((Path(__file__).parent / "expected_laps.json").read_text())


@pytest.mark.parametrize("filename", sorted(GOLDEN))
def test_golden_session(corpus_dir, filename):
    expected = GOLDEN[filename]
    path = corpus_dir / filename
    if not path.is_file():
        pytest.skip(f"{filename} not present")

    with Session.open(path) as s:
        info = s.info
        laps = s.laps
        length = s.track_length_m

    assert info.track == expected["track"]
    assert info.car_class == expected["car_class"]
    assert length == pytest.approx(expected["track_length_m"], abs=0.1)
    assert len(laps) == len(expected["laps"])

    for lap, exp in zip(laps, expected["laps"]):
        assert lap.number == exp["number"]
        assert lap.duration_s == pytest.approx(exp["duration_s"], abs=0.001)
        assert lap.touched_pits == exp["touched_pits"]
        assert lap.sectors_s == pytest.approx(tuple(exp["sectors_s"]), abs=0.001)
```

Create `tests/invariants/test_corpus_invariants.py`:

```python
"""Properties that must hold for every lap in every file.

These are the guarantees that replace the old heuristic validation stages.
"""

import pytest

from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus

#: No car in any LMU class averages more than this over a full lap.
MAX_PLAUSIBLE_AVG_KMH = 300.0


def test_sector_sum_equals_duration(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            for lap in s.laps:
                if lap.sectors_s is None:
                    continue
                assert sum(lap.sectors_s) == pytest.approx(lap.duration_s, abs=0.02), (
                    f"{path.name} lap {lap.number}"
                )


def test_no_lap_implies_impossible_average_speed(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            length = s.track_length_m
            for lap in s.laps:
                if lap.distance_m < length * 0.5:
                    continue  # partial lap, not a timing claim
                avg_kmh = (lap.distance_m / lap.duration_s) * 3.6
                assert avg_kmh < MAX_PLAUSIBLE_AVG_KMH, (
                    f"{path.name} lap {lap.number}: {avg_kmh:.1f} km/h average"
                )


def test_lap_intervals_are_contiguous_and_ordered(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            laps = s.laps
        for lap in laps:
            assert lap.t_end > lap.t_start
            assert lap.duration_s == pytest.approx(lap.t_end - lap.t_start)
        for a, b in zip(laps, laps[1:]):
            assert a.t_end == pytest.approx(b.t_start), f"{path.name}: gap between laps"


def test_every_session_reports_a_track_and_layout(corpus_files):
    for path in corpus_files:
        with Session.open(path) as s:
            assert s.info.track, f"{path.name}"
            assert s.info.layout, f"{path.name}"
```

- [ ] **Step 3: Run the new tests**

Run: `python -m pytest tests/golden tests/invariants -v`
Expected: PASS — 5 passed

Diese Tests prüfen bereits fertigen Code aus Task 5–7, sie müssen also sofort grün sein.
**Falls einer fehlschlägt, ist das ein echter Fehler in Task 5–7.** Er wird dort behoben —
die Golden-Werte werden nicht an das Verhalten des Codes angepasst. Sie stammen direkt
aus den `Lap`- und `Current Sector`-Events der Referenzdatei und sind die Vorgabe.

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS — alle Tests grün, keine Fehler

- [ ] **Step 5: Verify the suite skips cleanly without the corpus**

Run: `python -m pytest -v -p no:cacheprovider --ignore=tests/golden --ignore=tests/invariants -k "not corpus"`
Expected: PASS — die reinen Unit-Tests (Kanalregister, Zeitachse, Sektor-Mathematik) laufen ohne Telemetriedateien durch

- [ ] **Step 6: Commit**

```bash
git add tests/golden tests/invariants
git commit -m "test: freeze lap and sector expectations, add corpus invariants

Golden values verified by hand against the Monza reference session.
Invariants assert sector sums, physically possible average speeds and
contiguous lap intervals across all 40 sessions."
```

---

### Task 9: Kleine eingecheckte Fixtures für CI

Spec §5.4. Bisher laufen alle datenbezogenen Tests nur lokal und überspringen sich ohne den 637-MB-Bestand — in CI wäre also faktisch nichts abgesichert. Diese Aufgabe extrahiert kompakte, echte Testdateien.

Verifiziert: mit `default_block_size=16384` schrumpft die Monza-Referenzsession von 8,6 MB auf **860 KB**, bleibt mit einer normalen `duckdb.connect(..., read_only=True)` lesbar, und alle von den Tests gelesenen Werte sind unverändert (`Lap`-Events, `Current Sector`, `channelsList`, `Lap Dist` max 5776.076, `Throttle Pos` max 100.0, alle 12 Metadatenschlüssel).

**Files:**
- Create: `tools/build_fixtures.py`
- Create: `tests/fixtures/README.md`
- Create: `tests/fixtures/*.duckdb` (vom Skript erzeugt, eingecheckt)
- Modify: `tests/conftest.py` — `monza_q_file` bevorzugt die Fixture
- Modify: `.gitignore` — Fixtures vom `*.duckdb`-Ausschluss ausnehmen

**Interfaces:**
- Consumes: nichts
- Produces: pytest-Fixture `fixture_dir -> Path`; `monza_q_file` löst jetzt auf die eingecheckte Fixture auf

- [ ] **Step 1: Write the fixture builder**

Create `tools/build_fixtures.py`:

```python
"""Extract small, real test fixtures from the local telemetry corpus.

The corpus itself is gitignored (637 MB).  These fixtures are committed so the
test suite has real data to run against in CI.  They keep only the tables the
tests read, blank the 38 kB CarSetup JSON, and use a 16 kB DuckDB block size -
which takes the Monza reference session from 8.6 MB down to 860 kB.

Run from the repository root:

    python tools/build_fixtures.py
"""

from __future__ import annotations

import math
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"
OUT_DIR = REPO_ROOT / "tests" / "fixtures"

BLOCK_SIZE = 16384

#: Tables every fixture keeps.  Event tables first, then channels.
EVENT_TABLES = ["Lap", "Current Sector", "In Pits", "Lap Time"]
CHANNEL_TABLES = [
    "GPS Time", "Lap Dist", "GPS Latitude", "GPS Longitude",
    "Ground Speed", "Throttle Pos", "Brake Pos", "Steering Pos",
]
META_TABLES = ["metadata", "channelsList", "eventsList"]

#: (source filename, fixture name, seconds to keep or None for all, why it exists)
FIXTURES: list[tuple[str, str, float | None, str]] = [
    (
        "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb",
        "monza_q_3laps.duckdb",
        None,
        "reference session: 3 complete laps, 131.085 / 116.560 / 111.000 s",
    ),
    (
        "Autodromo Nazionale Monza_Q_2026-03-27T09_02_56Z.duckdb",
        "monza_q_no_complete_lap.duckdb",
        None,
        "abandoned after 160 m: one Lap event, no complete lap",
    ),
    (
        "Circuit de la Sarthe_R_2026-04-01T06_41_16Z.duckdb",
        "lemans_r_percent_steering.duckdb",
        400.0,
        "Steering Pos carries unit '%' (range +-100) instead of the usual +-1",
    ),
    (
        "Autodromo Nazionale Monza_R_2026-03-22T18_20_02Z.duckdb",
        "monza_r_extra_dist_reset.duckdb",
        700.0,
        "12 Lap events but 13 Lap Dist resets - the case that broke the old code",
    ),
]


def _channel_frequency(con, name: str) -> int | None:
    row = con.execute(
        'SELECT frequency FROM src."channelsList" WHERE channelName = ?', [name]
    ).fetchone()
    return int(row[0]) if row else None


def _table_exists(con, name: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM src.information_schema.tables WHERE table_name = ?",
        [name],
    ).fetchone()
    return bool(row and row[0])


def build(source: Path, dest: Path, keep_seconds: float | None) -> None:
    dest.unlink(missing_ok=True)
    con = duckdb.connect(str(dest), config={"default_block_size": BLOCK_SIZE})
    try:
        con.execute(f"ATTACH '{source}' AS src (READ_ONLY)")

        for table in META_TABLES:
            if _table_exists(con, table):
                con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"')

        # Blank the setup blob: 38 kB of JSON that nothing reads.
        con.execute("UPDATE metadata SET value = '{}' WHERE key = 'CarSetup'")

        t0_row = con.execute('SELECT value FROM src."GPS Time" LIMIT 1').fetchone()
        t0 = float(t0_row[0]) if t0_row else 0.0
        t_cut = None if keep_seconds is None else t0 + keep_seconds

        for table in EVENT_TABLES:
            if not _table_exists(con, table):
                continue
            where = "" if t_cut is None else f" WHERE ts <= {t_cut}"
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"{where}')

        for table in CHANNEL_TABLES:
            if not _table_exists(con, table):
                continue
            freq = _channel_frequency(con, table)
            if t_cut is None or freq is None:
                limit = ""
            else:
                # Truncate the tail only, so sample i still maps to t0 + i / freq.
                limit = f" LIMIT {math.ceil(keep_seconds * freq)}"
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM src."{table}"{limit}')

        con.execute("DETACH src")
    finally:
        con.close()


def main() -> None:
    if not CORPUS.is_dir():
        raise SystemExit(f"corpus not found at {CORPUS}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, dest_name, keep, why in FIXTURES:
        source = CORPUS / src_name
        if not source.is_file():
            print(f"SKIP {dest_name}: source missing ({src_name})")
            continue
        dest = OUT_DIR / dest_name
        build(source, dest, keep)
        size_kb = dest.stat().st_size / 1024
        print(f"{dest_name:38s} {size_kb:8.1f} KB   {why}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Build the fixtures**

Run: `python tools/build_fixtures.py`
Expected: four lines, each well under 4000 KB, e.g.
```
monza_q_3laps.duckdb                      860.0 KB   reference session: ...
monza_q_no_complete_lap.duckdb            ...
lemans_r_percent_steering.duckdb          ...
monza_r_extra_dist_reset.duckdb           ...
```

If any fixture exceeds 4000 KB, lower its `keep_seconds` value in `FIXTURES` and rerun.
The total of all four must stay under 8 MB.

- [ ] **Step 3: Allow the fixtures past .gitignore**

In `.gitignore`, directly below the `*.duckdb` line, add:

```gitignore
!tests/fixtures/*.duckdb
```

Verify: `git check-ignore -v tests/fixtures/monza_q_3laps.duckdb`
Expected: no output (exit code 1) — the file is no longer ignored

- [ ] **Step 4: Point the test fixtures at the committed data**

Create `tests/fixtures/README.md`:

```markdown
# Test fixtures

Real telemetry, cut down for version control by `tools/build_fixtures.py`.

Each file keeps only the tables the tests read, blanks the `CarSetup` JSON blob
and uses a 16 kB DuckDB block size. Channel values, event timestamps and
`channelsList` entries are untouched, so assertions made against the full
corpus hold here too.

| Fixture | Why it exists |
|---|---|
| `monza_q_3laps.duckdb` | Reference session. 3 complete laps: 131.085 / 116.560 / 111.000 s. |
| `monza_q_no_complete_lap.duckdb` | Abandoned after 160 m. One `Lap` event, so no lap is bounded on both sides. |
| `lemans_r_percent_steering.duckdb` | `Steering Pos` carries unit `%` (range ±100) rather than the usual ±1. |
| `monza_r_extra_dist_reset.duckdb` | 12 `Lap` events but 13 `Lap Dist` resets — the case that produced impossible lap times in the old implementation. |

Rebuild with `python tools/build_fixtures.py` (needs the local corpus).
```

In `tests/conftest.py`, replace the whole file with:

```python
"""Shared fixtures.

Small real fixtures live in ``tests/fixtures`` and are committed, so the suite
runs anywhere.  The full 637 MB corpus is gitignored; tests marked ``corpus``
skip cleanly when it is absent.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

MONZA_Q_NAME = "Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z.duckdb"
MONZA_Q_FIXTURE = "monza_q_3laps.duckdb"


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    if not CORPUS_DIR.is_dir():
        pytest.skip(f"telemetry corpus not present at {CORPUS_DIR}")
    return CORPUS_DIR


@pytest.fixture(scope="session")
def corpus_files(corpus_dir: Path) -> list[Path]:
    return sorted(corpus_dir.glob("*.duckdb"))


@pytest.fixture(scope="session")
def monza_q_file() -> Path:
    """The reference session: the committed fixture, or the corpus original."""
    fixture = FIXTURE_DIR / MONZA_Q_FIXTURE
    if fixture.is_file():
        return fixture
    original = CORPUS_DIR / MONZA_Q_NAME
    if original.is_file():
        return original
    pytest.skip("neither the fixture nor the corpus reference session is present")


@pytest.fixture(scope="session")
def percent_steering_file() -> Path:
    path = FIXTURE_DIR / "lemans_r_percent_steering.duckdb"
    if not path.is_file():
        pytest.skip("percent-steering fixture not built")
    return path


@pytest.fixture(scope="session")
def no_complete_lap_file() -> Path:
    path = FIXTURE_DIR / "monza_q_no_complete_lap.duckdb"
    if not path.is_file():
        pytest.skip("no-complete-lap fixture not built")
    return path
```

- [ ] **Step 5: Retire the now-obsolete corpus assertion from Task 1**

Task 1 created `tests/unit/test_corpus_discovery.py`, whose
`test_monza_reference_file_exists` asserts that `monza_q_file` is named after the
**corpus** session. From this task onward `monza_q_file` resolves to the committed
fixture `monza_q_3laps.duckdb`, so that assertion no longer describes the contract.

Replace the whole of `tests/unit/test_corpus_discovery.py` with:

```python
"""The corpus fixtures must find the real telemetry files, or skip cleanly."""

import pytest


@pytest.mark.corpus
def test_corpus_files_are_duckdb(corpus_files):
    assert len(corpus_files) >= 1
    assert all(f.suffix == ".duckdb" for f in corpus_files)


def test_reference_session_resolves_to_a_readable_file(monza_q_file):
    """Resolves to the committed fixture, or the corpus original as a fallback."""
    assert monza_q_file.is_file()
    assert monza_q_file.suffix == ".duckdb"
```

Note the marker moved from module level to `test_corpus_files_are_duckdb` alone:
the reference-session test no longer needs the corpus, and must stay selected
under `pytest -m "not corpus"`.

- [ ] **Step 6: Write tests that exercise the edge-case fixtures**

Create `tests/unit/test_fixture_edge_cases.py`:

```python
"""The three fixtures that exist because they broke the old implementation."""

import numpy as np
import pytest

from lmu_telemetry.core.laps import segment_laps
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.timebase import TimeBase
from lmu_telemetry.io.duckdb_source import TelemetryFile


def test_percent_steering_is_scaled_by_100_not_by_observed_max(percent_steering_file):
    with TelemetryFile(percent_steering_file) as tf:
        assert tf.channels.require("Steering Pos").unit == "%"
        raw = tf.raw_channel("Steering Pos")
        steer = tf.channel("Steering Pos")
    assert np.abs(raw).max() > 50.0
    assert np.abs(steer).max() == pytest.approx(np.abs(raw).max() / 100.0)
    assert np.abs(steer).max() <= 1.0


def test_session_without_a_complete_lap_yields_no_laps(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert s.laps == []
        assert s.fastest_lap is None
        assert s.info.track == "Autodromo Nazionale Monza"


def test_extra_distance_reset_does_not_create_a_phantom_lap(fixture_dir):
    """The old code split this session on Lap Dist resets and invented a lap."""
    path = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    if not path.is_file():
        pytest.skip("fixture not built")

    with TelemetryFile(path) as tf:
        n_lap_events = len(tf.events("Lap")[0])
        dist = tf.channel("Lap Dist")
        laps = segment_laps(tf, TimeBase.from_file(tf))

    n_resets = int(np.sum(np.diff(dist) < -50.0))
    assert n_resets > n_lap_events - 1, "fixture no longer contains the extra reset"
    assert len(laps) == n_lap_events - 1, "lap count must follow Lap events, not resets"
    for lap in laps:
        assert lap.duration_s > 60.0, "no partial lap may be reported as a full one"
```

- [ ] **Step 7: Run the suite without the corpus**

Run: `python -m pytest -v -m "not corpus"`
Expected: PASS — die Unit-, Fixture- und Edge-Case-Tests laufen alle durch, ohne dass der 637-MB-Bestand vorhanden sein muss

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS — alle Tests grün

- [ ] **Step 9: Commit**

```bash
git add tools/build_fixtures.py tests/fixtures tests/conftest.py tests/unit/test_fixture_edge_cases.py .gitignore
git commit -m "test: add committed telemetry fixtures so CI has real data

Extracted from the gitignored corpus with a 16 kB block size, keeping only
the tables the tests read: the Monza reference session drops from 8.6 MB to
860 kB. Includes the three sessions that defeated the old implementation."
```

---

## Abnahmekriterien für Stufe 1+2

- [ ] `python -m pytest -v` ist vollständig grün
- [ ] `python -m pytest -m "not corpus"` ist grün **ohne** den 637-MB-Bestand (CI-fähig)
- [ ] Rundenzeiten werden ausschließlich aus `Lap`-Event-Zeitstempeln gebildet; es existiert kein Codepfad, der eine Rundenzeit aus einer Zeitachse berechnet
- [ ] Sektorsumme == Rundenzeit für mindestens 180 Runden im Bestand
- [ ] Keine Runde im Bestand impliziert eine Durchschnittsgeschwindigkeit über 300 km/h
- [ ] `Throttle Pos` und `Brake Pos` liefern über `channel()` Werte in 0..1
- [ ] `Steering Pos` liefert über `channel()` Werte in −1..1, auch in den vier Dateien mit Einheit `%`
- [ ] `backend/` ist unverändert

## Nicht Teil dieser Stufe

- Geometrie, Krümmung, Rundenschluss, Kurvenerkennung (Stufe 3)
- Sauberkeitsbewertung `clean`, die den Rundenschluss braucht (Stufe 3)
- Distanzraster-Resampling der Kanäle (Stufe 3)
- Delta, Kurvenmetriken, Coaching (Stufe 4)
- API, Cache, Dezimierung (Stufe 5)
- Frontend (Stufe 6)
