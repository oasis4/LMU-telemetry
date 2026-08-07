"""Where a lap may be cut, and what the best of several laps would have been.

A theoretical best lap is only worth having if it is a lap somebody could
drive. Spliced at the wrong place it is not: a fast left-right is one
connected act, and how you enter the right is decided by how you left the
left. Take the left from one lap and the right from another and the result is
a target nobody can reach, which is worse than no target at all.

So the unit here is not the corner. It is the **block**: a run of corners that
must be taken from one lap or not at all. Two corners are separate blocks only
when there is sustained full throttle between them - the point on the track
where nothing is being decided and the laps are most alike. That one test
catches every case worth catching: a chicane, Monza's Ascari, and a pair of
corners with a straight between them, which it correctly separates.

The test is applied to **every** lap being spliced, not to the fastest. A gap
one lap took flat and another lifted through is a gap that lap was still
connected across, and cutting there would take its block time out of the only
context it ever had.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .corners import Corner
from .geometry import GRID_STEP_M, span_indices
from .metrics import THROTTLE_ON
from .trace import LapTrace

#: Full throttle held over this distance means the corners either side of it
#: are separate acts. Anything shorter is the crack of throttle between the
#: halves of a chicane, which is not a straight and does not make them two.
BLOCK_THROTTLE_M = 50.0

#: How far apart two laps may arrive at a seam before the block after it was
#: driven from an entry the ideal lap does not deliver. Wider than
#: ADVICE_SPEED_KMH: a seam sits on a straight at full throttle, where laps
#: differ by more than they do at a minimum speed, and the cut was already
#: chosen to be where they differ least.
SEAM_SPEED_KMH = 5.0


@dataclass(frozen=True)
class Block:
    """A run of corners that must be taken from one lap or not at all.

    ``start_m > end_m`` for the block containing the start/finish line, the
    same convention :class:`corners.Corner` uses and for the same reason: the
    line is an arbitrary point on the track and something has to straddle it.
    """

    index: int
    corners: tuple[Corner, ...]
    start_m: float
    end_m: float

    @property
    def name(self) -> str:
        if not self.corners:
            return f"block {self.index}"
        if len(self.corners) == 1:
            return self.corners[0].name
        return f"{self.corners[0].name} - {self.corners[-1].name}"


def _contains(start_m: float, end_m: float, distance_m: float) -> bool:
    """Whether *distance_m* lies in a span that may wrap the start/finish line.

    A span that starts and ends at the same point is the whole lap, not an
    empty one: with a single cut there is one block, and it runs from that cut
    the long way round to itself.
    """
    if start_m == end_m:
        return True
    if start_m < end_m:
        return start_m <= distance_m < end_m
    return distance_m >= start_m or distance_m < end_m


def _sustained(trace: LapTrace, window: np.ndarray, least: int) -> np.ndarray:
    """Mask over *window*: is this sample inside a long enough flat stretch?

    "Long enough" is judged per stretch, not per sample, so a point one metre
    into a 400 m straight counts and the whole of a 20 m stab does not.
    """
    flat = trace.throttle[window] > THROTTLE_ON
    inside = np.zeros(len(window), dtype=bool)
    i = 0
    while i < len(flat):
        if not flat[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(flat) and flat[j + 1]:
            j += 1
        if j - i + 1 >= least:
            inside[i : j + 1] = True
        i = j + 1
    return inside


def _cut_between(traces, grid: np.ndarray, after_m: float, before_m: float):
    """Where the gap between two corners may be cut, or None if it may not.

    The cut is the middle of the stretch every lap took flat. Working in
    offsets along the window rather than in distances is what keeps this right
    for the gap that wraps the start/finish line, where the two ends of the
    stretch are a lap apart in the array.
    """
    window = span_indices(grid, after_m, before_m)
    if len(window) == 0:
        return None
    least = max(1, int(round(BLOCK_THROTTLE_M / GRID_STEP_M)))

    shared = np.ones(len(window), dtype=bool)
    for trace in traces:
        shared &= _sustained(trace, window, least)
        if not shared.any():
            return None

    offsets = np.flatnonzero(shared)
    return float(grid[window[int(offsets[len(offsets) // 2])]])


def split_into_blocks(traces, corners) -> "list[Block]":
    """Split the track into runs of corners that may not be taken apart.

    *traces* are every lap that might contribute to an ideal lap; a cut has to
    be sound for all of them. *corners* is the shared corner list.

    Blocks come back in the order they are driven, beginning with the one that
    holds the start/finish line. Where no gap can be cut - a lap with no
    sustained full throttle anywhere - the answer is a single block covering
    the whole lap, which is the honest one: nothing here may be spliced.
    """
    traces = list(traces)
    corners = list(corners)
    if not traces:
        raise ValueError("no laps to split")
    if not corners:
        raise ValueError("no corners to split between")

    grid = traces[0].grid
    for trace in traces[1:]:
        if len(trace.grid) != len(grid):
            # The same refusal delta_s makes, for the same reason: two grids
            # mean two tracks. Unchecked, this indexes one lap's throttle with
            # another lap's window and surfaces as an IndexError from inside
            # numpy, several frames from the mistake.
            raise ValueError(
                f"laps are not on the same grid: {len(grid)} points and "
                f"{len(trace.grid)}. Two grids mean two tracks."
            )
    ordered = sorted(corners, key=lambda c: c.apex_m if c.start_m <= c.end_m else 0.0)

    cuts = []
    for i, corner in enumerate(ordered):
        following = ordered[(i + 1) % len(ordered)]
        cut = _cut_between(traces, grid, corner.end_m, following.start_m)
        if cut is not None:
            cuts.append(cut)

    if not cuts:
        # start == end is "from here the long way round to here". Written as
        # 0 to lap_length it looks the same and is not: the grid stops one
        # step short of the length, so _block_time would lose that step and
        # the ideal lap would come back shorter than the lap it was built
        # from.
        return [Block(index=1, corners=tuple(ordered), start_m=0.0, end_m=0.0)]

    cuts.sort()
    spans = [(cuts[i], cuts[(i + 1) % len(cuts)]) for i in range(len(cuts))]
    # Driven order: the block holding the line comes first, because that is the
    # block the lap starts in.
    first = next(i for i, (a, b) in enumerate(spans) if _contains(a, b, 0.0))
    spans = spans[first:] + spans[:first]

    blocks = []
    for index, (start_m, end_m) in enumerate(spans, start=1):
        held = tuple(c for c in ordered if _contains(start_m, end_m, c.start_m))
        blocks.append(
            Block(index=index, corners=held, start_m=start_m, end_m=end_m)
        )
    return blocks


@dataclass(frozen=True)
class Seam:
    """A join between two blocks, and what it costs in credibility.

    The ideal lap arrives here having driven the block before, and then claims
    the time the block after took on a *different* lap. That claim holds only
    if the two laps were doing the same thing at this point.
    """

    at_m: float
    #: How far apart the two contributing laps were here, in km/h.
    speed_spread_kmh: float
    sound: bool


@dataclass(frozen=True)
class BlockChoice:
    """Which lap the ideal takes this block from, and what it saved."""

    block: Block
    lap_number: "int | None"
    time_s: float
    #: Seconds this block was quicker than the best complete lap's own time
    #: through it. Zero where the best lap already owned the block.
    gain_s: float


@dataclass(frozen=True)
class IdealLap:
    """The best of several laps, block by block, with its joins examined."""

    blocks: tuple[BlockChoice, ...]
    seams: tuple[Seam, ...]
    ideal_s: float
    best_lap_s: float
    best_lap_number: "int | None"

    @property
    def gain_s(self) -> float:
        """What the ideal lap claims over the best real one."""
        return self.best_lap_s - self.ideal_s

    @property
    def sound(self) -> bool:
        """Whether every join holds. One that does not makes the whole time a
        claim the laps do not support, so this is an ``all`` and not a count."""
        return all(seam.sound for seam in self.seams)


def _at(trace: LapTrace, distance_m: float, values: np.ndarray) -> float:
    return float(np.interp(distance_m, trace.grid, values))


def _duration(trace: LapTrace) -> float:
    """How long the whole lap took, including the step the grid does not reach.

    ``grid`` runs to ``lap_length - GRID_STEP_M``, so ``time_s[-1]`` is the
    time at the last *sample*, not at the line. Used as the lap's duration it
    is short by one grid step - 0.03 s at Monza speeds - and every block time
    would sum to that much less than the lap they came from. Small, and
    exactly the kind of quiet shortfall a headline figure should not carry.
    """
    return float(trace.time_s[-1] + (trace.time_s[-1] - trace.time_s[-2]))


def _block_time(trace: LapTrace, block: Block) -> float:
    """How long *trace* took through *block*.

    The block holding the start/finish line is summed over its two halves. Its
    ends sit at opposite ends of the time axis, and subtracting one from the
    other returns the whole rest of the lap with a minus sign - the same trap
    :func:`metrics.corner_metrics` avoids for a corner that straddles the line.
    """
    entered = _at(trace, block.start_m, trace.time_s)
    left = _at(trace, block.end_m, trace.time_s)
    if block.start_m < block.end_m:
        return left - entered
    # start == end is the single block covering the whole lap; start > end is
    # the block holding the line. Both are the lap from `entered` round to
    # `left`, which is what this says.
    return (_duration(trace) - entered) + left


def ideal_lap(traces, corners) -> IdealLap:
    """The quickest lap that could be assembled from *traces*, block by block.

    One session's laps at a time. Two sessions mean two fuel loads and two
    tyre states, and a block time from one is not comparable to a block time
    from the other - which this cannot detect and does not try to: the caller
    chooses the laps.
    """
    traces = list(traces)
    if not traces:
        raise ValueError("no laps to build an ideal from")

    blocks = split_into_blocks(traces, corners)
    numbers = [
        getattr(trace.lap, "number", None) for trace in traces
    ]
    totals = [_duration(trace) for trace in traces]
    best = int(np.argmin(totals))

    chosen: list[BlockChoice] = []
    picked: list[LapTrace] = []
    for block in blocks:
        times = [_block_time(trace, block) for trace in traces]
        quickest = int(np.argmin(times))
        chosen.append(
            BlockChoice(
                block=block,
                lap_number=numbers[quickest],
                time_s=times[quickest],
                gain_s=times[best] - times[quickest],
            )
        )
        picked.append(traces[quickest])

    # A seam is the entry to each block, so there are as many as there are
    # blocks - the lap is a loop and every block is entered from another.
    seams = []
    for i, block in enumerate(blocks):
        leaving = picked[i - 1]           # -1 wraps to the last block, correctly
        entering = picked[i]
        spread = abs(
            _at(leaving, block.start_m, leaving.speed_kmh)
            - _at(entering, block.start_m, entering.speed_kmh)
        )
        seams.append(
            Seam(
                at_m=block.start_m,
                speed_spread_kmh=spread,
                sound=spread <= SEAM_SPEED_KMH,
            )
        )

    return IdealLap(
        blocks=tuple(chosen),
        seams=tuple(seams),
        ideal_s=float(sum(choice.time_s for choice in chosen)),
        best_lap_s=totals[best],
        best_lap_number=numbers[best],
    )
