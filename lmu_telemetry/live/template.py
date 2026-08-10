"""The window a braking template is drawn over, and what fills it.

Everything here is an offset into that window, not a lap distance. A window
that crosses the start/finish line is two ranges in lap distance, and every
consumer - the drawing, the tone, the driver's own line - would have to know
it. As an offset it is one range that starts at zero and only increases.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.corners import Corner
from ..core.geometry import GRID_STEP_M, span_indices
from ..core.metrics import APPROACH_M, corner_metrics
from ..core.trace import LapTrace


def offset_into(start_m: float, distance_m: float, lap_length_m: float) -> float:
    """How far past *start_m* the car is, measured forward round the lap."""
    return float((distance_m - start_m) % lap_length_m)


@dataclass(frozen=True)
class Template:
    """One corner's approach and braking zone, taken from the reference lap."""

    corner: Corner
    #: Where the window begins, as a lap distance.
    start_m: float
    length_m: float
    #: Offsets into the window, not lap distances. See the module docstring.
    brake_at_m: float
    entry_at_m: float
    entry_speed_kmh: float
    offsets_m: np.ndarray
    #: The same points as lap distances, so the driver's own trace can be
    #: sampled at exactly the places the grey line was.
    abs_m: np.ndarray
    brake: np.ndarray
    throttle: np.ndarray


def templates_for(reference: LapTrace, corners) -> "list[Template]":
    """One template per corner the reference braked for.

    A corner taken flat is skipped rather than drawn with no mark on it: it
    has nothing to teach here, and at Monza it would mean eleven strips a lap
    where seven are useful.
    """
    lap_length_m = float(reference.grid[-1]) + GRID_STEP_M
    made: "list[Template]" = []
    for corner in corners:
        figures = corner_metrics(reference, corner)
        if figures.brake_point_m is None:
            continue
        start_m = (corner.start_m - APPROACH_M) % lap_length_m
        window = span_indices(reference.grid, start_m, corner.end_m)
        if len(window) < 2:
            continue
        abs_m = reference.grid[window]
        offsets = np.array(
            [offset_into(start_m, float(d), lap_length_m) for d in abs_m]
        )
        made.append(Template(
            corner=corner,
            start_m=start_m,
            length_m=float(offsets[-1]),
            brake_at_m=offset_into(start_m, figures.brake_point_m, lap_length_m),
            entry_at_m=offset_into(start_m, corner.start_m, lap_length_m),
            entry_speed_kmh=figures.entry_speed_kmh,
            offsets_m=offsets,
            abs_m=abs_m,
            brake=reference.brake[window],
            throttle=reference.throttle[window],
        ))
    return made
