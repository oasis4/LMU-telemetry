"""Cumulative time-delta computation between two laps.

Positive delta = lap_a is *slower* (losing time) relative to lap_b.
"""

from __future__ import annotations

import numpy as np

from .lap_processor import LapData


def compute_delta(
    lap_a: LapData,
    lap_b: LapData,
    resolution_m: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(distance, delta)`` arrays.

    Both laps are re-interpolated onto a shared distance grid so the
    arrays have equal length.  ``delta[i]`` is the cumulative time
    difference in **seconds** at ``distance[i]``.
    """
    max_dist = min(lap_a.distance[-1], lap_b.distance[-1]) if (
        len(lap_a.distance) > 0 and len(lap_b.distance) > 0
    ) else 0.0

    if max_dist <= 0:
        return np.array([]), np.array([])

    d_common = np.arange(0, max_dist, resolution_m)

    # Interpolate time(distance) for each lap
    t_a = np.interp(d_common, lap_a.distance, lap_a.time)
    t_b = np.interp(d_common, lap_b.distance, lap_b.time)

    delta = t_a - t_b  # positive → A is slower

    return d_common, delta
