# Live corner overlay — design

**Status:** agreed, ready to plan
**Date:** 2026-08-07

## Goal

While driving, show a small always-on-top panel that carries the live time
delta to a reference lap, and — as each corner is *left behind* — the same
short action sentence the post-lap view already produces.

## This does not contradict the post-lap rule

The original brake-shape spec ruled out a live shout during the braking zone,
and this keeps that. A sentence appears when the car passes the corner's
`end_m`, about the corner just completed. The driver is on the following
straight when they read it. What changes is only *where* the sentence is
shown, not when it is decided.

## Data source

LMU runs on the rFactor 2 engine and exposes live state through the **rF2
Shared Memory Map Plugin** (TheIronWolf), the same interface SimHub and
friends use.

- `rF2SharedMemoryMapPlugin64.dll` in `<LMU install>\Bin64\Plugins\`
- Enabled in LMU under Settings → Plugins
- Section `$rFactor2SMMP_Telemetry$`, ~50 Hz — `mLapDist`, `mElapsedTime`,
  `mUnfilteredThrottle`, `mUnfilteredBrake`, `mUnfilteredSteering`, speed from
  `mLocalVel`
- Section `$rFactor2SMMP_Scoring$`, ~5 Hz — lap number, session state

Read with `mmap` + `ctypes`. No new third-party dependency.

**The plugin is the user's to install.** It is a third-party DLL going into a
game install, and this project will not fetch or place it. The overlay must
detect its absence and say so plainly rather than showing a dead panel.

## The architectural point

The live path must not re-implement a single measurement. `mLapDist` gives
distance directly, so the awkward part of the offline pipeline — reconstructing
progress from a wobbling 10 Hz `Lap Dist` — disappears. What remains is
filling the *same* 2 m grid as the lap goes on, and then calling the *same*
`corner_metrics` and `_advise` that the post-lap view calls.

Two definitions of a brake point would be two answers to one question. There
is one.

Per-corner time lost is `live.time_s - reference.time_s` from the two
`CornerMetrics`, which is what `time_lost_over` measures across a corner span.
That equivalence gets a test, because the two paths must not drift.

## Components

    lmu_telemetry/live/
      sharedmem.py     ctypes structs + mmap reader; absence is an error, not a zero
      lap_buffer.py    fills a LapTrace-shaped buffer on the model's grid as the lap runs
      watch.py         fires when a corner's end_m is passed; returns the Advice
      overlay.py       transparent always-on-top tkinter window
      __main__.py      picks the reference lap, then runs

The reference lap comes from the existing pipeline: a chosen `.duckdb` lap
built through `build_trace` against the session's `TrackModel`, so the corner
list and the grid are shared by construction.

## What the panel shows

- The live delta to the reference, large.
- The last completed corner's name and its action sentence, if it produced one.
- Nothing where the numbers do not agree on a story — the same silence the
  post-lap view keeps, for the same reason.

## Constraints to state up front

- **Exclusive fullscreen hides it.** LMU must run borderless or windowed.
  The overlay is a normal top-most window, not an injected D3D hook, and this
  is deliberate: hooking a running game's renderer is a far larger and more
  fragile undertaking, and it is not needed for text in a corner.
- **This cannot be verified without LMU running** with the plugin installed.
  Everything below the shared-memory reader is testable from recorded laps
  replayed through the same buffer, and that is how it will be tested; the
  reader itself needs the game.

## Out of scope

- Any advice during a corner.
- Rendering inside the game.
- Setup, fuel, strategy, or standings. This panel is about one thing.
