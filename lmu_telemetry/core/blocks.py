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
    lap_length = float(grid[-1]) + GRID_STEP_M
    ordered = sorted(corners, key=lambda c: c.apex_m if c.start_m <= c.end_m else 0.0)

    cuts = []
    for i, corner in enumerate(ordered):
        following = ordered[(i + 1) % len(ordered)]
        cut = _cut_between(traces, grid, corner.end_m, following.start_m)
        if cut is not None:
            cuts.append(cut)

    if not cuts:
        return [Block(index=1, corners=tuple(ordered), start_m=0.0, end_m=lap_length)]

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
