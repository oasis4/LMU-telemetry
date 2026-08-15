# Ideal lap from chained corner groups — design

**Status:** agreed, ready to plan
**Date:** 2026-08-07

## Goal

A theoretical best lap assembled from the driver's own laps: for each stretch
of track, take the lap that did it quickest, and report what the lap time
would have been.

## Why the legacy version is not it

`backend/main.py::_build_composite` already does this, and it is wrong twice
over. It lives in the superseded `backend/` package, which the current
frontend never calls. And it splices at **sector** boundaries — the game's
three sectors, placed by convention, not by geometry. A sector line can fall
straight through a chicane.

## The constraint that drives the whole design

A fast left-right is not two corners. It is one connected act: how you enter
the right is decided by how you left the left. Take the left from lap A and
the right from lap B and you get a lap nobody could drive, and a target time
nobody could reach.

So the unit of splicing is not the corner. It is the **block**: a run of
corners that must be taken from one lap or not at all.

## What makes two corners one block

Corners N and N+1 belong to the same block when there is no **sustained full
throttle** between them. That single test captures every case worth catching:

- A left-right chicane — never off the brakes and onto full power in between.
- Monza's Ascari — three corners, one braking event, no full throttle between.
- Two corners with a straight between them — full throttle in the middle, so
  they separate.

It is also the test the driving itself defines, rather than one imposed by a
threshold on distance. `coaching.py` already carries a weaker cousin of this
idea in `SAME_BRAKING_M`, which refuses to give three tips for Ascari's one
brake application.

Sustained means at least `BLOCK_THROTTLE_M` metres continuously above
`THROTTLE_ON`, so a stab of throttle between the two halves of a chicane does
not split it.

## Where a block is cut

At the midpoint of the full-throttle stretch that separates it from the next.
That is the point on the track where the laps are most alike: same pedal, same
attitude, nothing being decided.

## The honesty problem, and what is done about it

Even cut on a straight, two laps arrive at a seam at different speeds. A block
time taken from a lap that entered 6 km/h faster is not transferable to a lap
that did not.

So every seam records the **entry-speed spread** between the contributing
laps. Where the spread exceeds `SEAM_SPEED_KMH`, the seam is reported as
unsound and the ideal lap says so rather than quietly claiming a time it
cannot support. This is the same rule the advice engine already lives by: say
nothing rather than say something the numbers do not carry.

## What it produces

- `blocks` — the segmentation, as distance ranges, with the corners in each.
- Per block: which lap was quickest through it, and by how much.
- `ideal_s` — the sum of the best block times.
- `gain_s` — `ideal_s` minus the driver's actual best lap.
- `seams` — each cut point with its entry-speed spread, and whether it is sound.

A spliced *trace* is a second step and is only built on request. Where it is
built, the seams travel with it, so nothing downstream draws it as a
continuous lap without knowing where the joins are.

## Out of scope

- Porting anything from `backend/`. That package is superseded; this is new
  work in `lmu_telemetry/core/`.
- Cross-session ideal laps. One session at a time to begin with: two sessions
  mean two fuel loads and two tyre states, and a block time from one is not
  comparable to a block time from the other.
- Any change to the corner list or corner detection.
