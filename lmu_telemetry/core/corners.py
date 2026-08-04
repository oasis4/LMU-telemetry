"""Corner detection from the curvature of the reference racing line.

A corner is a stretch where the track bends more tightly than
``CORNER_MAX_RADIUS_M``. Adjacent stretches bending the same way and separated
by only a short gap belong to one corner.

Splitting fused sequences is gated on **total heading change**, not on the
prominence of curvature peaks. Prominence alone halves Monza's Curva Grande -
a long shallow bend whose two halves each read as a peak - while leaving
genuinely fused blocks intact. A single corner rarely turns more than about
180 degrees, so only blocks beyond that gate are split, and a part that still
exceeds it goes back through the splitter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.signal import find_peaks

from .geometry import GRID_STEP_M, heading_change_deg

#: A bend tighter than this radius counts as a corner.
CORNER_MAX_RADIUS_M = 400.0
#: Below this much turning it is a kink, not a corner.
CORNER_MIN_HEADING_DEG = 20.0
#: Below this length it is noise.
CORNER_MIN_LENGTH_M = 25.0
#: Same-signed bends closer than this belong to one corner.
MERGE_GAP_M = 40.0

#: Only blocks turning more than this are treated as fused sequences.
SPLIT_HEADING_GATE_DEG = 180.0
#: A curvature peak must stand this fraction above its surroundings to count.
SPLIT_PROMINENCE_FRAC = 0.05
#: No part of a split may be shorter than this.
SPLIT_MIN_PART_M = 40.0
#: Guard against pathological recursion.
SPLIT_MAX_DEPTH = 4


@dataclass(frozen=True)
class Corner:
    """One corner, positioned by distance along the lap.

    Normally ``start_m <= apex_m <= end_m``. The one exception is a corner
    that contains the start/finish line: the line is an arbitrary point on the
    track, so a corner may straddle it, and such a corner runs off the end of
    the lap and back to the beginning. It reports ``start_m > end_m``, and its
    ``apex_m`` lies in whichever of the two stretches holds the tightest
    point - so it is on one side or the other of ``0``, not between the two
    figures. ``heading_deg`` and ``radius_m`` are always measured over the
    whole corner, both stretches together.

    Such a corner is listed first, since it is the corner the lap starts in.
    """

    index: int
    name: str
    start_m: float
    apex_m: float
    end_m: float
    radius_m: float
    heading_deg: float
    direction: str

    @property
    def wraps(self) -> bool:
        """Whether this corner contains the start/finish line."""
        return self.start_m > self.end_m


def _contiguous(mask: np.ndarray) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def _merge(regions, kappa, grid):
    merged: list[tuple[int, int]] = []
    for si, ei in regions:
        if merged:
            pi, pe = merged[-1]
            same_way = np.sign(kappa[(pi + pe) // 2]) == np.sign(kappa[(si + ei) // 2])
            if same_way and (grid[si] - grid[pe]) < MERGE_GAP_M:
                merged[-1] = (pi, ei)
                continue
        merged.append((si, ei))
    return merged


def _join_wrap(regions, kappa, n_samples):
    """Join a region ending at the last sample to one starting at the first.

    The start/finish line is an arbitrary point on the track and not a feature
    of it - the same reason ``geometry.smooth_closed`` wraps. A corner may
    therefore contain it, and a linear scan cuts such a corner in half; if
    both halves then fall under ``CORNER_MIN_LENGTH_M`` it disappears
    altogether, without saying so.

    The joined region is returned as ``(start, end)`` with ``start > end``,
    meaning it runs off the end of the lap and back to the beginning, and is
    placed first because it is the region the lap starts in.

    Only genuinely adjacent halves are joined - curvature present at both the
    first and the last sample. Two same-signed bends separated by a gap below
    ``MERGE_GAP_M`` *across* the line are left alone, because ``_merge``
    measures its gap linearly and cannot see across the wrap either.
    """
    if len(regions) < 2:
        return regions
    (first_start, first_end), (last_start, last_end) = regions[0], regions[-1]
    if first_start != 0 or last_end != n_samples - 1:
        return regions
    first_sign = np.sign(kappa[(first_start + first_end) // 2])
    last_sign = np.sign(kappa[(last_start + last_end) // 2])
    if first_sign != last_sign:
        return regions
    return [(last_start, first_end)] + regions[1:-1]


def _region(kappa, grid, si, ei):
    """Sample indices, curvature and distance for one region.

    A region that wraps gets a distance axis that continues past the end of
    the lap rather than jumping back to zero, so heading, length and the peak
    search all see one continuous stretch of track instead of two.
    """
    if si <= ei:
        idx = np.arange(si, ei + 1)
        return idx, kappa[idx], grid[idx]
    lap_length = float(grid[-1]) - float(grid[0]) + float(grid[1] - grid[0])
    idx = np.concatenate([np.arange(si, len(grid)), np.arange(0, ei + 1)])
    dist = np.concatenate([grid[si:], grid[: ei + 1] + lap_length])
    return idx, kappa[idx], dist


def _split_once(kappa, grid) -> list[tuple[int, int]]:
    """Cut a block at curvature valleys that genuinely separate two corners.

    *kappa* and *grid* are the block's own samples, and the returned index
    pairs are positions within them. Working on the block rather than on
    slices of the whole lap is what lets a block that wraps the start/finish
    line be split like any other.
    """
    segment = np.abs(kappa)
    last = len(segment) - 1
    if len(segment) < 5:
        return [(0, last)]
    min_part = max(int(SPLIT_MIN_PART_M / GRID_STEP_M), 2)
    peaks, _ = find_peaks(
        segment,
        prominence=segment.max() * SPLIT_PROMINENCE_FRAC,
        distance=min_part,
    )
    if len(peaks) < 2:
        return [(0, last)]

    cuts = []
    for a, b in zip(peaks, peaks[1:]):
        valley = a + int(np.argmin(segment[a : b + 1]))
        if segment[valley] < min(segment[a], segment[b]) * (1.0 - SPLIT_PROMINENCE_FRAC):
            cuts.append(valley)
    if not cuts:
        return [(0, last)]

    parts, previous = [], 0
    for cut in cuts:
        if cut - previous >= min_part and last - cut >= min_part:
            parts.append((previous, cut - 1))
            previous = cut
    parts.append((previous, last))
    return parts


def _split(kappa, grid, depth: int = 0) -> list[tuple[int, int]]:
    last = len(kappa) - 1
    if depth >= SPLIT_MAX_DEPTH:
        return [(0, last)]
    if heading_change_deg(kappa, grid) <= SPLIT_HEADING_GATE_DEG:
        return [(0, last)]
    parts = _split_once(kappa, grid)
    if len(parts) == 1:
        return parts
    out: list[tuple[int, int]] = []
    for ps, pe in parts:
        out.extend(
            (ps + a, ps + b)
            for a, b in _split(kappa[ps : pe + 1], grid[ps : pe + 1], depth + 1)
        )
    return out


def detect_corners(kappa: np.ndarray, grid: np.ndarray) -> list[Corner]:
    """Every corner on the line described by *kappa*, in track order.

    A corner containing the start/finish line is reported once, spanning the
    wrap, and comes first - see :class:`Corner`.
    """
    kappa = np.asarray(kappa, dtype=np.float64)
    grid = np.asarray(grid, dtype=np.float64)
    if len(kappa) != len(grid):
        raise ValueError(f"kappa and grid differ: {len(kappa)} vs {len(grid)}")

    regions = _join_wrap(
        _merge(_contiguous(np.abs(kappa) > 1.0 / CORNER_MAX_RADIUS_M), kappa, grid),
        kappa,
        len(grid),
    )
    lap_length = float(grid[-1]) - float(grid[0]) + float(grid[1] - grid[0])

    found: list[tuple[float, Corner]] = []
    for si, ei in regions:
        idx, region_kappa, region_grid = _region(kappa, grid, si, ei)
        for ps, pe in _split(region_kappa, region_grid):
            heading = heading_change_deg(
                region_kappa[ps : pe + 1], region_grid[ps : pe + 1]
            )
            if heading < CORNER_MIN_HEADING_DEG:
                continue
            if region_grid[pe] - region_grid[ps] < CORNER_MIN_LENGTH_M:
                continue
            apex = ps + int(np.argmax(np.abs(region_kappa[ps : pe + 1])))
            peak = abs(float(region_kappa[apex]))
            start_m = float(grid[idx[ps]])
            # Track order runs from the start/finish line, and a corner that
            # contains the line starts before it - so it sorts ahead of
            # everything, including any corner that ends just short of it.
            order = start_m - lap_length if idx[ps] > idx[pe] else start_m
            found.append(
                (
                    order,
                    Corner(
                        index=0,
                        name="",
                        start_m=start_m,
                        apex_m=float(grid[idx[apex]]),
                        end_m=float(grid[idx[pe]]),
                        radius_m=1.0 / peak if peak > 0 else float("inf"),
                        heading_deg=heading,
                        direction="L" if region_kappa[apex] > 0 else "R",
                    ),
                )
            )

    found.sort(key=lambda entry: entry[0])
    return [
        replace(corner, index=i + 1, name=f"T{i + 1}")
        for i, (_order, corner) in enumerate(found)
    ]
