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

**Corrected once the install was actually examined.** This section first said
to use the third-party rF2 Shared Memory Map Plugin. That is unnecessary: LMU
ships its own plugin SDK at `<LMU install>\Support\SharedMemoryInterface\`
and publishes its whole state into one mapping, `LMU_Data`. No third-party
DLL is needed at all, and the driver has to install nothing.

Two further details the first draft had wrong, both of which would have cost
an afternoon:

- Plugins live in `<LMU install>\Plugins\`, not `Bin64\Plugins\`. That is the
  rFactor 2 layout, not LMU's.
- `InternalsPlugin.hpp` wraps its structs in `#pragma pack(push, 4)`. At
  natural alignment every `double` after a 4-byte field lands four bytes late,
  and the values that come back are finite, plausible, and wrong.

Using the game's own headers also settles a version question the third-party
route could not. LMU's `TelemInfoV01` carries `mDeltaBest`,
`mBatteryChargeFraction` and the boost-motor fields where published rF2
transcriptions show one long padding array — so a plugin-shaped struct read
against this game would be misaligned from that point on.

The old route, for the record:

- `rF2SharedMemoryMapPlugin64.dll` in `<LMU install>\Plugins\`
- Enabled in LMU under Settings → Plugins
- Section `$rFactor2SMMP_Telemetry$`, ~50 Hz — `mElapsedTime`, `mDeltaTime`,
  `mLapNumber`, `mUnfilteredThrottle`, `mUnfilteredBrake`,
  `mUnfilteredSteering`, speed from `mLocalVel`
- Section `$rFactor2SMMP_Scoring$`, ~5 Hz — `mLapDist`, session and lap state

**Correction to an earlier draft of this spec.** It claimed `mLapDist` was in
the telemetry buffer at 50 Hz, and that this made the live path *simpler* than
the offline one. It is not: `mLapDist` is a field of `rF2VehicleScoring`, in
the 5 Hz mapping. At 90 m/s that is 18 m between distance readings — coarser
than the 2 m grid, and coarser than the 10 Hz `Lap Dist` the offline pipeline
reconstructs progress from. Read straight, it would put brake points out by up
to a car length and a half, confidently.

So distance is carried rather than read: anchor on `mLapDist` each time the
scoring buffer's version counter advances, and dead-reckon from speed between
anchors. That is sound because speed is sampled at 50 Hz and each integration
spans only 200 ms. The anchor also corrects any drift on every scoring tick,
so error cannot accumulate over a lap.

Read with `mmap` + `ctypes`. No new third-party dependency.

**Nothing has to be installed.** The mapping is the game's own. What the
overlay must still do is detect its absence — the game not running, or not in
a session — and say so plainly rather than showing a dead panel.

**And it must detect a layout it does not match.** The game creates the
mapping at `sizeof(SharedMemoryLayout)`; if the transcribed structs disagree,
opening fails outright. A wrong layout is the one failure mode here that does
not announce itself, because it returns numbers that look like numbers.

## The architectural point

The live path must not re-implement a single measurement. Once a sample
carries a settled distance, what remains is filling the *same* 2 m grid as the
lap goes on, and then calling the *same* `corner_metrics` and `_advise` that
the post-lap view calls.

Getting distance onto each sample is the live path's own problem, and it is
solved once, in the reader, behind `LiveSample`. Nothing above that layer
knows or cares that two mappings at two rates were involved.

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
