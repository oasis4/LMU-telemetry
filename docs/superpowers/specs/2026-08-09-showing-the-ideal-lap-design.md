# Showing the ideal lap — design

Date: 2026-08-09
Branch: `feature/brake-shape-coaching`

## Goal

`core.ideal_lap()` builds the best lap that could be assembled from a session's
laps, block by block, and reports what each join costs in credibility. None of
it can be seen. There is no API endpoint and nothing in the browser. This spec
covers the endpoint and the page.

The design of the ideal lap itself is settled and not reopened here; see
[2026-08-07-ideal-lap-from-chained-corners-design.md](2026-08-07-ideal-lap-from-chained-corners-design.md).

## What the corpus says

Measured over a sample of 60 of the 239 recordings, which is what the shape of
this feature is argued from rather than guessed at:

- **34 can build an ideal lap. 26 cannot, all for the same reason: fewer than
  two clean laps.** The refusal is not an edge case, it is 43 % of what a
  driver will meet. It gets designed, not bolted on.
- **Five of the 34 have a seam that does not hold.** Unsoundness is real, not
  theoretical.
- The largest gain in the sample, +1.436 s at Monza from 8 laps over 7 blocks,
  is **one of those five** — 20.0 km/h of spread at one join. The most
  exciting number in the sample is the worst supported one. That single fact
  decides how the headline is written.
- Gains otherwise: median +0.422 s, max +1.436 s.
- Cost: 0.10 s per session, model and traces included. No cache.

## The endpoint

`GET /api/sessions/{name}/ideal`

Over the clean laps of **one** recording. Not a choice: `ideal_lap()` states
its own constraint — two sessions mean two fuel loads and two tyre states, and
a block time from one is not comparable to a block time from the other.

```
{
  "name", "track",
  "laps_used": [2, 3, 4, 5],
  "ideal_s", "best_lap_s", "best_lap_number", "gain_s", "sound",
  "blocks": [
    { "index", "name", "corners": [1, 2],
      "start_m", "end_m", "wraps",
      "lap_number", "time_s", "gain_s" }
  ],
  "seams": [ { "at_m", "speed_spread_kmh", "sound" } ],
  "seam_limit_kmh": 5.0
}
```

`wraps` is `start_m > end_m`, sent for the block holding the start/finish line
exactly as `/api/sessions/{name}/track` sends it per corner. A client that
works it out itself will one day work it out differently.

`seam_limit_kmh` is sent for the reason `/api/compare` already sends
`brake_on`: the flags are computed with it, and a client drawing a threshold
from its own copy would shade something that disagrees with the marks printed
beside it.

### The two refusals

Both are 422, both name their reason, because a refusal without one is
indistinguishable from a bug.

1. **Fewer than two clean laps.** The message says how many clean laps were
   found and how many laps the recording holds. This is the common path and
   the text carries the weight: it is what 43 % of recordings answer.
2. **No track model.** Same condition and same wording as the existing
   `/api/sessions/{name}/track`, which already refuses this way.

## The page

Route `/ideal`, view `IdealView.vue`. A third route beside `/` and
`/recordings`. It is not a card on the comparison page: that page answers
"these two laps" where this answers "which of my laps belong spliced", and its
own header comment records that it was once a wall and was deliberately
cleared.

**Recording picker.** Offers only recordings with at least two clean laps. The
sessions listing already reports `clean_laps` per recording, so this costs
nothing. Offering a recording that cannot answer is an invitation into an
error message.

**Headline.** The ideal time, the best real lap, and the gain — subject to the
soundness rule below.

**`BlockMap.vue`.** The circuit with each block coloured by the lap it was
taken from, and the seams marked on it.

Not a mode added to `TrackMap`. That component commits in its own header to
colour carrying polarity — time lost against time gained — and to answering
one question at a time. Block provenance is categorical colour, a second
meaning on the same stroke, which is the thing it says it will not do.

The projection both need — bounds, one scale for both axes, centring — is
lifted out of `TrackMap` into `track-projection.js`, beside the existing
`corner-window.js` and `overlay-data.js`. `TrackMap` keeps its behaviour;
this is extraction, not redesign.

**Block table.** Block, corners, source lap, time, gain. In driven order,
starting with the block holding the line, which is the order `split_into_blocks`
already returns.

## How soundness is shown

`IdealLap.sound` is an `all()` and not a count, and the code says why: one join
that does not hold makes the whole time a claim the laps do not support.

So where `sound` is false the headline **does not print the gain as a plain
number**. The ideal time is shown as unsupported, with the offending seam named
— where it is and by how much the two laps disagreed there. The number is not
hidden; a driver who wants it can read it in the table. What it must not do is
sit in large type looking like a lap that was nearly driven.

Sound seams are not decorated. A mark on every join would make the marks mean
"join" rather than "look at this one".

## Testing

- The endpoint against `monza_q_3laps.duckdb`: blocks come back in driven
  order, times sum to `ideal_s`, `gain_s` equals `best_lap_s - ideal_s`.
- Both refusals, each asserting the reason is present and names the count.
- **A recording whose ideal lap has an unsound seam qualifies the headline.**
  Written explicitly, because a conditional that suppresses a number is exactly
  the kind of line that later reads as dead weight and gets tidied away.
- `seam_limit_kmh` in the response equals `blocks.SEAM_SPEED_KMH`, so the two
  cannot drift apart unnoticed.
- `track-projection.js` extraction: `TrackMap` renders as before.

## Out of scope

- **Choosing laps by hand.** The session is the unit `ideal_lap()` requires.
- **Caching.** Measured at 0.10 s per session.
- **Ideal laps across recordings.** Different fuel and tyres; the core refuses
  to pretend otherwise and so does this.
- **The overlay.** This is the browser view. The live panel is unchanged.
