"""Corner auto-detection from speed traces.

Detects corners by finding local speed minima below a rolling-average
threshold, then expands each apex into entry/exit windows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Corner:
    id: int
    name: str
    distance_start: float
    distance_apex: float
    distance_end: float
    min_speed: float


def detect_corners(
    speed: np.ndarray,
    distance: np.ndarray,
    window_m: float = 50.0,
    threshold_pct: float = 0.85,
    max_apex_speed: float = 200.0,
    min_duration_m: float = 20.0,
) -> list[Corner]:
    """Detect corners from a speed-over-distance trace.

    Algorithm
    ---------
    1. Smooth *speed* with a rolling average (window = *window_m*).
    2. Find local minima where ``speed < threshold_pct * rolling_avg``.
    3. Each minimum becomes an *apex*; expand ± *window_m* for entry/exit.
    4. Merge overlapping windows.
    5. Filter out apices with ``min_speed >= max_apex_speed`` or windows
       shorter than *min_duration_m*.

    Returns a list of :class:`Corner` objects ordered by distance.
    """
    if len(speed) < 3 or len(distance) < 3:
        return []

    resolution = float(np.median(np.diff(distance))) if len(distance) > 1 else 1.0
    if resolution <= 0:
        resolution = 1.0
    win_samples = max(int(window_m / resolution), 3)

    # 1. Rolling average
    kernel = np.ones(win_samples) / win_samples
    smoothed = np.convolve(speed, kernel, mode="same")

    # 2. Find candidate apices: local minima below threshold
    below = speed < threshold_pct * smoothed
    # local-minimum flag (both neighbours higher)
    local_min = np.zeros(len(speed), dtype=bool)
    for i in range(1, len(speed) - 1):
        if speed[i] <= speed[i - 1] and speed[i] <= speed[i + 1]:
            local_min[i] = True
    candidates = np.where(below & local_min)[0]

    if len(candidates) == 0:
        return []

    # 3. Expand each apex ± window_m
    raw_windows: list[tuple[int, int, int]] = []  # (start_idx, apex_idx, end_idx)
    for apex_i in candidates:
        apex_d = distance[apex_i]
        start_d = apex_d - window_m
        end_d = apex_d + window_m
        si = int(np.searchsorted(distance, start_d))
        ei = int(np.searchsorted(distance, end_d))
        si = max(si, 0)
        ei = min(ei, len(distance) - 1)
        raw_windows.append((si, apex_i, ei))

    # 4. Merge overlapping windows (keep apex with lowest speed)
    merged: list[tuple[int, int, int]] = [raw_windows[0]]
    for si, ai, ei in raw_windows[1:]:
        prev_si, prev_ai, prev_ei = merged[-1]
        if si <= prev_ei:
            # Overlap – merge, keep apex with min speed
            new_si = min(prev_si, si)
            new_ei = max(prev_ei, ei)
            best_ai = prev_ai if speed[prev_ai] <= speed[ai] else ai
            merged[-1] = (new_si, best_ai, new_ei)
        else:
            merged.append((si, ai, ei))

    # 5. Filter and build result
    corners: list[Corner] = []
    idx = 1
    for si, ai, ei in merged:
        ms = float(speed[ai])
        dur = float(distance[ei] - distance[si])
        if ms >= max_apex_speed:
            continue
        if dur < min_duration_m:
            continue
        corners.append(Corner(
            id=idx,
            name=f"C{idx}",
            distance_start=float(distance[si]),
            distance_apex=float(distance[ai]),
            distance_end=float(distance[ei]),
            min_speed=ms,
        ))
        idx += 1

    return corners
