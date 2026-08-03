# LMU Telemetry — Komplett-Rework

**Datum:** 2026-08-03
**Status:** Design, freigegeben
**Ersetzt:** den kompletten Stand von Commit `6367eb3`

---

## 1. Ausgangslage

Die bestehende App (~7.200 Zeilen) analysiert LMU-Telemetrie aus `.duckdb`-Dateien.
Sie funktioniert nicht zuverlässig. Die vier gemeldeten Symptome sind alle auf
denselben Grundfehler zurückzuführen: **der Code rät Größen, die als Ground Truth
in der Datei stehen.**

Untersucht wurde ein Bestand von 40 echten Sessions (637 MB) über vier Strecken
(Monza, Circuit de la Sarthe, Algarve, Imola), 190 gefahrene Runden, Klassen GT3,
LMP3 und Hypercar.

### 1.1 Belegte Ursachen

**A — Unmögliche Rundenzeiten.**
Rundengrenzen wurden aus Resets des `Lap Dist`-Kanals abgeleitet
([lap_processor.py:79](../../../backend/lap_processor.py)). Diese Resets sind
nachweislich unzuverlässig: eine Monza-Session enthält 12 `Lap`-Events, aber 13
Dist-Resets; eine andere 5 gegen 6. Jeder überzählige Reset erzeugt eine
Teilrunde. Findet sich dazu kein passendes `Lap Time`-Event, berechnet der Code
die Zeit aus einer synthetischen Zeitachse
([lap_processor.py:347](../../../backend/lap_processor.py)) — das Ergebnis ist eine
Teilrundenzeit, ausgewiesen als volle Runde. Daher die „Weltrekorde".

Anschließend versuchen acht Heuristikstufen (Median × 1.5, Median × 0.8,
Sektorproportionen, Sector-Flags …), den Schaden nachträglich zu maskieren.

**B — Kurvenerkennung instabil.**
Kurven werden pro Runde aus dem Lenkwinkel erkannt
([corner_detector.py:26](../../../backend/corner_detector.py)). Der Lenkwinkel ist
fahrerabhängig, und seine Einheit schwankt zwischen den Dateien: über den
Bestand gemessen liegt `Steering Pos` je nach Datei in −1…+1 **oder** −100…+100.
Die Normalisierung teilt durch das *beobachtete* Maximum dieser Runde
([corner_detector.py:52](../../../backend/corner_detector.py)) — eine Runde ohne
vollen Lenkeinschlag wird also anders skaliert als eine mit. Die Schwelle
`|steer| > 0.03` bedeutet damit in jeder Runde einen anderen physikalischen Winkel.

Messung: dieselbe Strecke, per-Runde-Erkennung liefert 9 bis 13 Kurven.

**C — Bremspunkte und Gaspunkte falsch.**
`Throttle Pos` und `Brake Pos` liegen über **alle 40 Dateien** im Bereich 0–100 %.
Der Code prüft `brake > 0.1` und `throttle > 0.5`
([main.py:530](../../../backend/main.py)) und behandelt die Werte damit als 0–1.
`brake > 0.1` löst bei 0,1 % Bremsdruck aus, also auf Sensorrauschen. Sämtliche
Bremspunkte, Gaspunkte, Kurvenmetriken und Coaching-Tipps des alten Stands sind
dadurch wertlos.

Die Einheiten stehen in der Datei: jede Session enthält eine Tabelle
`channelsList (channelName, frequency, unit)`, die der alte Code nie liest.

**D — Kurvenvergleich strukturell bedeutungslos.**
In der Compare-View holt jede Seite ihre Kurven getrennt über
`/api/corners/{eigene session}` ([CompareView.vue:295](../../../frontend/src/views/CompareView.vue)).
Zwei Fahrer werden also gegen **verschiedene Kurvendefinitionen** verglichen.

**E — Trägheit, vor allem im Vergleich.**
Gemessene JSON-Payloads bei 1 m Auflösung:

| Ansicht | Monza | Le Mans |
|---|---|---|
| Eine Runde | 1,13 MB | 2,66 MB |
| Vergleich (2 Runden) | 2,25 MB | **5,31 MB** |

Dazu drei Verstärker:
- `activeTelemetry = ref(null)` ([stores/telemetry.js:38](../../../frontend/src/stores/telemetry.js))
  macht die Messdaten tief reaktiv — rund 300.000 Floats einzeln in Proxies gewickelt.
- Jede Auswahländerung ruft `POST /api/load` mit neuer UUID und resampled die
  komplette Session neu; die alte Session bleibt unbegrenzt im Speicher.
- Kurven werden bei jedem Request neu erkannt, nichts wird gecacht.

Der Renderer (uPlot) ist nicht die Ursache und bleibt.

**F — Keine Tests.** Kein `tests/`, keine Fixtures, keine CI. Jede Regression
blieb unbemerkt.

### 1.2 Ground Truth, die vorhanden ist

Über alle 40 Dateien verifiziert:

| Größe | Quelle | Verifikation |
|---|---|---|
| Rundengrenze | `Lap`-Event, Zeitstempel je Übergang | alle 190 Runden plausibel |
| Rundenzeit | Δ zweier `Lap`-Zeitstempel | Monza GT3 1:50.7–1:55, Monza Hyper 1:41.6, Le Mans GT3 4:00.9, Le Mans Hyper 3:39.6, Algarve GT3 1:47.2, Imola LMP3 1:58.4 — **null Ausreißer** |
| Sektorzeiten | Übergänge des `Current Sector`-Events | **190 von 190 Runden exakt**, Σ = Rundenzeit auf < 20 ms |
| Einheit + Frequenz | Tabelle `channelsList` | 56 Kanäle deklariert |
| Geschwindigkeit | `Ground Speed`, 100 Hz, km/h | vs. `GPS Speed` 10 Hz m/s (10× gröber) |
| Strecke/Layout/Auto/Fahrer | Tabelle `metadata` | 12 Schlüssel inkl. `TrackLayout`, `CarClass`, `CarSetup` |
| Streckenlänge | `max(Lap Dist)` | Le Mans über 7 Sessions: 13619,4–13621,8 m (Streuung 2,5 m) |

**Konsequenz:** Der Rework braucht weniger Code, nicht mehr. Alle acht
Heuristikstufen der Rundenvalidierung entfallen ersatzlos.

---

## 2. Zielbild

Eine lokale Analyse-App für nach der Session. Kein Server, keine Accounts,
kein In-Game-Overlay.

**Kernfunktionen** (alle vier gleichrangig):
1. Kurvenanalyse pro Kurve — Bremspunkt, Einlenk-, Minimal-, Ausgangsgeschwindigkeit,
   Gaspunkt, Zeitverlust gegen Referenz
2. Rundenvergleich mit kumulativer Delta-Kurve über die Distanz
3. Freunde-Vergleich pro Kurve — mehrere Fahrer, dieselbe Strecke
4. Streckenkarte aus GPS-Daten, Kurven markiert, nach Zeitverlust eingefärbt

**Freundedaten** kommen als Datei in den Telemetrieordner. Die App gruppiert
selbständig nach Strecke, Layout und Fahrer.

---

## 3. Architektur

Stack bleibt Python + FastAPI + Vue 3 + uPlot. Der Stack war nicht die Ursache.
Inhaltlich wird `backend/` gelöscht und neu gebaut, nicht refactored.

```
lmu_telemetry/
  io/
    duckdb_source.py    Dateizugriff, Schema-Introspektion, read-only
    channels.py         Kanalregister: Name, Einheit, Frequenz aus channelsList
  core/
    laps.py             Rundensegmentierung aus Lap-Events
    sectors.py          Sektorzeiten aus Current-Sector-Übergängen
    resample.py         Zeit- → Distanzraster
    geometry.py         ENU-Projektion, Krümmung, Rundenschluss
    track_model.py      Referenzmodell bauen / laden / cachen
    corners.py          Kurvenerkennung inkl. Split langer Sequenzen
    naming.py           kuratierte Kurvennamen
    delta.py            Delta über Distanz
    metrics.py          Kurvenmetriken je Runde
    coaching.py         Fehlerklassifikation und Hinweise
  cache/
    store.py            Plattencache, Schlüssel (Pfad, mtime, Größe)
  api/
    app.py, routes/
  data/
    tracks/*.json       kuratierte Kurvennamen je Strecke

frontend/src/
  api/         typisierter Client
  stores/      Pinia, Messdaten via shallowRef
  components/  TrackMap, TraceChart, DeltaBar, CornerTable, CornerCard
  views/       Sessions, Lap, Compare, Corner
tests/
  unit/ invariants/ golden/ fixtures/
```

### 3.1 Grundregel

**Jede Größe, die in der Datei steht, wird gelesen — nie geschätzt.**
Wo eine Größe nicht vorhanden ist, wird das explizit als solches ausgewiesen,
nicht durch einen Ersatzwert kaschiert.

### 3.2 Rundenmodell

Eine Runde entsteht ausschließlich zwischen zwei aufeinanderfolgenden
`Lap`-Events. `Lap Dist` wird zur Positionsbestimmung innerhalb der Runde
benutzt, **nie** zur Rundenabgrenzung.

Zwei getrennte Eigenschaften, im alten Stand vermischt:

- **vollständig** — von zwei `Lap`-Events begrenzt. Nur vollständige Runden
  haben eine Rundenzeit.
- **sauber** — zusätzlich: keine Boxenberührung (`In Pits`), zurückgelegte
  Distanz ≈ Streckenlänge ± 2 %, Rundenschluss 330–390°.

Nur saubere Runden fließen ins Referenzmodell. Angezeigt werden alle,
unsaubere sichtbar markiert mit Grund.

Es gibt **keine** median- oder proportionsbasierte Verwerfung mehr.

### 3.3 Referenzmodell der Strecke

Identität einer Strecke: `(TrackName, TrackLayout, round(Streckenlänge, -1))`.
Die Länge im Schlüssel trennt Layouts, die im Namen gleich heißen.

Aufbau, einmalig je Strecke:
1. Alle sauberen Runden aller Sessions dieser Strecke sammeln
2. GPS auf lokale Meter projizieren (ENU), auf gemeinsames Distanzraster (2 m)
3. **Medianlinie** über alle Runden bilden — killt Einzelrundenrauschen
4. Krümmung κ = (x'y'' − y'x'') / (x'² + y'²)^{3/2} berechnen
5. Kurven: zusammenhängende Bereiche mit |κ| > 1/400 m⁻¹, Richtungsänderung ≥ 20°,
   Länge ≥ 25 m
6. Sequenzen über ~120° Richtungsänderung werden an Krümmungsminima gesplittet
7. Namen aus `data/tracks/*.json` zuordnen, sonst T1…Tn
8. Als JSON cachen

**Krümmung statt Lenkwinkel** ist der entscheidende Wechsel: Krümmung ist eine
Eigenschaft der Strecke, unabhängig von Fahrer und Kanaleinheit.

Der Rundenschluss (∮κ ds ≈ 360°) ist ein eingebauter Selbsttest, den es vorher
nicht gab.

Validierung des Ansatzes gegen die echten Daten:

| Strecke | Referenzmodell | Rundenschluss | Pro-Runde-Erkennung |
|---|---|---|---|
| Monza | **11 Kurven** (real: 11) | 360° | 9–13, instabil |
| Le Mans | **25 Kurven** | 372° | 25–27 |
| Algarve | 10 Kurven (real: 15) ⚠ | 351° | 10–11 |
| Imola | kein Modell ⚠ | 406–646° | — |

Monza wird korrekt aufgelöst: T3 mit R = 266 m die Curva Grande, T6/T7 die
beiden Lesmo, T8–T10 die Ascari-Schikane, T11 mit 167° die Parabolica.
Le Mans ebenso: T14 mit R = 30 m die Mulsanne-Haarnadel, T18–T21 die
Porsche-Kurven, T22–T25 die Ford-Schikanen.

**Zwei bekannte Lücken, die die Umsetzung schließen muss:**

- *Algarve findet 10 statt 15 Kurven.* Sequenzen mit 278° bzw. 241°
  Richtungsänderung sind zusammengeklebte Mehrfachkurven. Schritt 6 (Split)
  behebt das und wird gegen Algarve = 15 verifiziert.
- *Imola liefert kein Modell*, weil beide vorhandenen Runden Unfallrunden sind.
  Fallback: beste vorhandene Runde verwenden und im UI als unsicher kennzeichnen.
  Ein Modell wird nie stillschweigend aus schlechten Daten gebaut.

### 3.4 Auswertung

Alle Runden werden auf ein gemeinsames Distanzraster (1 m) gelegt. Da alle
dieselbe Kurvenliste teilen, ist jeder Vergleich per Konstruktion konsistent.

- **Delta:** t_A(d) − t_B(d), kumulativ über Distanz
- **Kurvenmetriken:** Bremspunkt (erste Distanz mit Bremsdruck > 5 %),
  Einlenkgeschwindigkeit, Minimalgeschwindigkeit, Gaspunkt (> 50 %),
  Ausgangsgeschwindigkeit, Kurvenzeit — **alle Schwellen einheitenbewusst
  gegen das Kanalregister**
- **Coaching:** Vergleich gegen Referenz, klassifiziert nach früh/spät gebremst,
  zu wenig Kurvengeschwindigkeit, späte Gasannahme; ausgegeben wird der
  Beitrag in Sekunden, nicht nur ein Label

---

## 4. Performance

Zielpfad ist ausdrücklich der **Vergleich**, nicht das erste Laden.

| Ursache | Fix | Erwartung |
|---|---|---|
| 5,31 MB JSON pro Vergleich | Auslieferung auf Displayauflösung dezimiert (~1500 Punkte); volle Auflösung nur bei Zoom und im Kurvendetail | 0,11 MB, Faktor 24 |
| Tief reaktive Messdaten | `shallowRef` + `markRaw` | Proxy-Overhead entfällt |
| Session-Neuberechnung je Auswahl | Ergebnis einmal berechnen, als `.npz` cachen, Schlüssel `(Pfad, mtime, Größe)` | zweites Laden = Dateiread |
| Kurven pro Request neu erkannt | Referenzmodell einmal je Strecke, gecacht | entfällt vollständig |
| `_sessions` wächst unbegrenzt | LRU-Eviction | konstanter Speicher |
| Blockierendes `_cache_ready.wait(15)` | Streckenliste liest nur die 12 Metadatenzeilen | keine Wartezeit |

`chart.js` wird als Abhängigkeit entfernt; uPlot bleibt.

---

## 5. Tests

Vier Ebenen. Der alte Stand hatte keine.

1. **Unit — synthetische Geometrie.** Kreis, Oval, S-Kurven-Layout mit
   analytisch bekannter Krümmung. Prüft die Mathematik ohne Daten.

2. **Invarianten**, geprüft über den gesamten Bestand:
   - `Σ Sektoren == Rundenzeit` ± 20 ms
   - `Rundenzeit ≥ Streckenlänge / 400 km/h` — macht unmögliche Zeiten
     strukturell unmöglich
   - Kurvenliste **identisch** für alle Runden derselben Strecke
   - Rundenschluss des fertigen Referenzmodells liegt bei 360° ± 15°
     (nicht zu verwechseln mit dem Sauberkeitsfilter aus §3.2 — hier wird
     geprüft, dass die *gemittelte* Linie geometrisch geschlossen ist)
   - der Sauberkeitsfilter verwirft die bekannten Problemrunden tatsächlich:
     beide Imola-Runden müssen abgelehnt werden, ≥ 90 % der Monza-Runden
     müssen durchkommen
   - jeder Kanal wird gegen die in `channelsList` deklarierte Einheit geprüft

3. **Golden Tests.** Rundenzeiten, Sektoren und Kurvenlisten je Strecke werden
   eingefroren. Jede Änderung, die eine Kurve verschiebt, schlägt fehl.

4. **Fixtures für CI.** Die 637 MB kommen nicht ins Repository. Stattdessen
   einzelne Runden von vier Strecken als kompakte Fixtures, ausdrücklich
   inklusive der Problemfälle:
   - Imola-Unfallrunden (Rundenschluss 406°/646°)
   - Monza-Session mit 13 Dist-Resets bei 12 `Lap`-Events
   - abgebrochene Session mit `.wal`-Datei
   - Session ohne einzige vollständige Runde (`max(Lap Dist)` = 160 m)
   - Le Mans als Langstreckenfall (13,6 km)

---

## 6. Umsetzungsreihenfolge

Jede Stufe ist für sich lauffähig und getestet, bevor die nächste beginnt.

1. **IO + Kanalregister** — Einheiten und Frequenzen aus `channelsList`
2. **Runden + Sektoren** — Ground Truth; hier verschwinden die unmöglichen Zeiten
3. **Geometrie + Referenzmodell + Kurven** — hier verschwinden Layout- und
   Kurvenfehler; Abnahme: Monza 11, Algarve 15, Le Mans plausibel
4. **Delta + Kurvenmetriken + Coaching** — korrekte Einheiten
5. **API mit Cache und Dezimierung**
6. **Frontend** — Vergleichsansicht zuerst

---

## 7. Was gelöscht wird

- `backend/` vollständig (2.400 Zeilen)
- `cleanup_sessions.py`, `StartAll.bat`
- alle vier Vue-Views und der Pinia-Store — Neuschrieb
- Abhängigkeit `chart.js`

**Erhalten:** Stack-Wahl, `docker-compose.yml`, `LICENSE`, `start.py` als
Launcher (überarbeitet).

---

## 8. Nicht Teil dieses Reworks

- In-Game-Live-Overlay (eigenes Projekt; bräuchte Shared-Memory-API statt Dateien)
- Server, Accounts, Bestenlisten
- Export einzelner Runden als Austauschformat
- Unterstützung anderer Simulatoren

---

## 9. Offene Punkte für die Umsetzung

- Kurvennamen liegen zunächst für die vier belegten Strecken vor; weitere
  Strecken fallen automatisch auf T1…Tn zurück.
- Der Split-Schwellwert für lange Kurvensequenzen wird gegen Algarve kalibriert
  und muss anschließend Monza (11) und Le Mans unverändert lassen.
