"""How much time one lap has gained or lost on another, at every point.

Both laps are read off the same distance grid, so the comparison is between
two cars at the same place on the track rather than at the same moment - which
is the only way "where was I slower" has an answer.

The old implementation fetched a separate corner list for each side of a
comparison, so two drivers were measured against different corner definitions
and any per-corner figure was between two different questions. Everything here
takes one corner list and applies it to both sides.
"""

from __future__ import annotations

import numpy as np

from .corners import Corner
from .geometry import span_indices
from .trace import LapTrace

__all__ = ["delta_s", "span_indices", "time_lost_over"]


def delta_s(reference: LapTrace, other: LapTrace) -> np.ndarray:
    """Seconds *other* is behind *reference*, at each grid point.

    Positive means *other* is losing. The value at the last grid point is the
    difference between the two lap times.
    """
    if len(reference.grid) != len(other.grid):
        raise ValueError(
            f"the two laps are on different grids: {len(reference.grid)} "
            f"and {len(other.grid)} samples - they are not the same track"
        )
    return np.asarray(other.time_s, dtype=np.float64) - np.asarray(
        reference.time_s, dtype=np.float64
    )


def time_lost_over(delta: np.ndarray, grid: np.ndarray, corner: Corner) -> float:
    """Seconds lost across *corner* alone: the delta's rise over its span.

    Taking the rise between the ends rather than integrating the delta is what
    makes the corners add up to the lap: each is charged for the time it
    added, and the straights keep the rest.

    A corner containing the start/finish line is two pieces of one lap that are
    not next to each other in time - the run to the line and the run away from
    it, half a lap apart in the array. Its rise is the sum of the two, because
    subtracting one end from the other would compare the end of the lap with
    the beginning of it and report whatever the rest of the lap did.
    """
    if corner.start_m <= corner.end_m:
        indices = span_indices(grid, corner.start_m, corner.end_m)
        return float(delta[indices[-1]] - delta[indices[0]])

    tail = span_indices(grid, corner.start_m, float(grid[-1]))
    head = span_indices(grid, float(grid[0]), corner.end_m)
    return float(
        (delta[tail[-1]] - delta[tail[0]]) + (delta[head[-1]] - delta[head[0]])
    )
