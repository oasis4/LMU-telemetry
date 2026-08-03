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

from dataclasses import dataclass

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
    index: int
    name: str
    start_m: float
    apex_m: float
    end_m: float
    radius_m: float
    heading_deg: float
    direction: str


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


def _split_once(kappa, grid, si, ei) -> list[tuple[int, int]]:
    """Cut a block at curvature valleys that genuinely separate two corners."""
    segment = np.abs(kappa[si : ei + 1])
    if len(segment) < 5:
        return [(si, ei)]
    min_part = max(int(SPLIT_MIN_PART_M / GRID_STEP_M), 2)
    peaks, _ = find_peaks(
        segment,
        prominence=segment.max() * SPLIT_PROMINENCE_FRAC,
        distance=min_part,
    )
    if len(peaks) < 2:
        return [(si, ei)]

    cuts = []
    for a, b in zip(peaks, peaks[1:]):
        valley = a + int(np.argmin(segment[a : b + 1]))
        if segment[valley] < min(segment[a], segment[b]) * (1.0 - SPLIT_PROMINENCE_FRAC):
            cuts.append(si + valley)
    if not cuts:
        return [(si, ei)]

    parts, previous = [], si
    for cut in cuts:
        if cut - previous >= min_part and ei - cut >= min_part:
            parts.append((previous, cut - 1))
            previous = cut
    parts.append((previous, ei))
    return parts


def _split(kappa, grid, si, ei, depth: int = 0) -> list[tuple[int, int]]:
    if depth >= SPLIT_MAX_DEPTH:
        return [(si, ei)]
    if heading_change_deg(kappa[si : ei + 1], grid[si : ei + 1]) <= SPLIT_HEADING_GATE_DEG:
        return [(si, ei)]
    parts = _split_once(kappa, grid, si, ei)
    if len(parts) == 1:
        return parts
    out: list[tuple[int, int]] = []
    for ps, pe in parts:
        out.extend(_split(kappa, grid, ps, pe, depth + 1))
    return out


def detect_corners(kappa: np.ndarray, grid: np.ndarray) -> list[Corner]:
    """Every corner on the line described by *kappa*, in track order."""
    kappa = np.asarray(kappa, dtype=np.float64)
    grid = np.asarray(grid, dtype=np.float64)
    if len(kappa) != len(grid):
        raise ValueError(f"kappa and grid differ: {len(kappa)} vs {len(grid)}")

    regions = _merge(
        _contiguous(np.abs(kappa) > 1.0 / CORNER_MAX_RADIUS_M), kappa, grid
    )

    corners: list[Corner] = []
    for si, ei in regions:
        for ps, pe in _split(kappa, grid, si, ei):
            heading = heading_change_deg(kappa[ps : pe + 1], grid[ps : pe + 1])
            if heading < CORNER_MIN_HEADING_DEG:
                continue
            if grid[pe] - grid[ps] < CORNER_MIN_LENGTH_M:
                continue
            apex = ps + int(np.argmax(np.abs(kappa[ps : pe + 1])))
            peak = abs(float(kappa[apex]))
            index = len(corners) + 1
            corners.append(
                Corner(
                    index=index,
                    name=f"T{index}",
                    start_m=float(grid[ps]),
                    apex_m=float(grid[apex]),
                    end_m=float(grid[pe]),
                    radius_m=1.0 / peak if peak > 0 else float("inf"),
                    heading_deg=heading,
                    direction="L" if kappa[apex] > 0 else "R",
                )
            )
    return corners
