# Brake-shape coaching — design

**Status:** agreed, ready to plan
**Date:** 2026-08-07
**Branch:** `feature/brake-shape-coaching`

## Goal

After a lap, each corner that cost time should be able to produce a short,
concrete action sentence — "brake a touch later and stay on it longer", "come
off the brake earlier and let it roll" — instead of only the four coarse
patterns the app has today.

This is **not** a live coach. It runs where the advice already runs: in the
post-lap corner comparison (`compare_corners` → `advice`), on the finished
trace. No new realtime path, no new endpoint, no new fetch.

## What already exists

- `LapTrace.brake` — the Brake Pos channel, normalised to 0..1, resampled onto
  the 2 m distance grid (`core/trace.py`).
- `CornerMetrics.brake_point_m` — **one** marker per corner: where the braking
  that produced the corner's minimum speed began (`core/metrics.py`).
- `CornerMetrics.min_speed_kmh`, `.exit_speed_kmh` — the outcome signals the
  four current rules in `core/coaching.py::_advise` already lean on.
- The corner list and the reference lap, both shared by both sides of a
  comparison.

## Core idea

Extract **four** markers from the brake trace per corner instead of one, and
compare all four between the driver's lap and the reference, exactly the way
the single brake point is compared today.

| Marker | Definition |
|---|---|
| `brake_point_m` | first sample above `BRAKE_ON` (5 %) — unchanged, still the start |
| `brake_peak_m` | where pressure is highest inside the braking event |
| `brake_release_m` | last sample above `TRAIL_OFF` (2 %) — where the brake is truly off |
| `trail_length_m` | `brake_release_m − brake_peak_m` — metres spent bleeding pressure off after the peak |

**The event these are read from** is the same one `_brake_point` already
picks: the last run of brake pressure before the corner's slowest point. The
run is taken at the *low* threshold (`TRAIL_OFF`) so the release is not cut off
where the pedal crosses 5 % on the way out, and the start is still read at
`BRAKE_ON` inside it — so `brake_point_m` keeps exactly the value it has today
and nothing downstream shifts.

From the differences in those four markers, **combined with** the existing
min-speed and exit-speed differences, derive finer sentence templates.

## The rule that must not be broken

A different release point can simply be a different, valid style. Some drivers
stop the car and turn; some carry the brake to the apex. Neither is a fault on
its own, and telemetry cannot tell them apart.

So: **a brake-shape statement never stands alone.** Every new pattern must be
coupled to an outcome signal — a worse minimum speed or a worse exit speed —
before it will speak, on top of the existing "the corner must have cost at
least `ADVICE_MIN_LOSS_S`" gate. This is the same "several measurements must
agree" principle the current four rules are built on, applied to a signal that
is *more* prone to false positives, not less.

## New patterns

Three, each inserted next to the existing rule it refines.

**A — Stopped it straight, then coasted.** Braked earlier, trail shorter,
minimum speed worse. The car was slowed in a straight line and then rolled
through with no rotation left.
→ *"Brake later and stay on the brake longer"*
Refines the existing rule 2 ("You can brake later here"), so it is checked
first and rule 2 remains the fallback when the trail evidence is absent.

**B — Still braking where the reference was driving.** Trail longer, exit speed
worse, minimum speed not worse. The entry was fine; the brake was still on
where the throttle should have been.
→ *"Come off the brake earlier here"*
Checked before the existing throttle rule, which is the coarser statement of
the same loss.

**C — Slow to build the pressure.** Brake point matched, peak later, minimum
speed worse. The pedal went down in the right place but the pressure arrived
late, so the stop happened deeper than it should have.
→ *"Get to full brake pressure sooner"*
Refines the existing rule 4 ("There is more corner speed here"), so it is
checked first and rule 4 remains the fallback.

Resulting order in `_advise`:

1. braked later + lower min → brake earlier *(existing)*
2. **A** braked earlier + shorter trail + lower min → brake later, stay on longer
3. braked earlier + lower min → brake later *(existing, fallback for A)*
4. **B** longer trail + slower exit + min not worse → come off the brake earlier
5. later throttle + min not worse → power earlier *(existing)*
6. **C** brake point matched + later peak + lower min → build pressure sooner
7. lower min + brake point matched → more corner speed *(existing, fallback for C)*

## Thresholds

- `TRAIL_OFF = 0.02` — below 2 % of pedal travel the brake is off. Lower than
  `BRAKE_ON` so the tapering end of a trail is inside the event rather than
  clipped by it.
- `ADVICE_TRAIL_M = 15.0` — how much longer or shorter a trail has to be to
  count. Trail length is a difference of two positions on one trace, so its
  error is roughly twice a single position's; Lap Dist at 10 Hz puts that at
  10-16 m. A typical trail phase is 20-60 m, so this stays deliberately
  demanding and the honest outcome is often silence.
- Display noise floor for the new markers in `_differences`: reuse
  `BRAKE_POINT_NOISE_M` (5 m) for release, and `2 × BRAKE_POINT_NOISE_M` for
  trail length, for the same doubling reason.

## Language

Product surface is English throughout (headlines, detail text, frontend copy).
The new sentences stay English and match the existing register.

## Out of scope

- Any realtime or in-corner output.
- New API endpoints — the new markers ride along in the existing
  `/compare` payload's `reference`/`other` metric blocks.
- Changing `brake_point_m`'s meaning or value.
- Frontend redesign. The corner table and focus panel pick the new fields up
  through the payload they already render.
