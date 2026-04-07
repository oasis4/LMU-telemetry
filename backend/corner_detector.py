"""Corner auto-detection from speed and steering traces.

Primary method: steering-based detection (finds turns via steering angle).
Fallback: speed-based detection with tuned parameters.

Speed is expected in **km/h** (converted by LapProcessor).
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


def _detect_corners_steering(
    speed: np.ndarray,
    distance: np.ndarray,
    steering: np.ndarray,
    steer_threshold: float = 0.03,
    gap_m: float = 50.0,
    min_duration_m: float = 12.0,
    max_apex_speed: float = 280.0,
) -> list[Corner]:
    """Detect corners from steering activity.

    1. Find regions where ``|steering| > steer_threshold``.
    2. Merge regions separated by less than *gap_m*.
    3. For each region, find the speed minimum as apex.
    4. Filter by minimum duration and apex speed.
    """
    if len(steering) < 3:
        return []

    resolution = float(np.median(np.diff(distance))) if len(distance) > 1 else 1.0
    if resolution <= 0:
        resolution = 1.0
    gap_samples = max(int(gap_m / resolution), 1)

    turning = np.abs(steering) > steer_threshold
    if not np.any(turning):
        return []

    # Find contiguous turning regions
    regions: list[tuple[int, int]] = []
    in_turn = False
    start = 0
    for i in range(len(turning)):
        if turning[i] and not in_turn:
            start = i
            in_turn = True
        elif not turning[i] and in_turn:
            regions.append((start, i - 1))
            in_turn = False
    if in_turn:
        regions.append((start, len(turning) - 1))

    if not regions:
        return []

    # Merge regions separated by less than gap_samples
    merged: list[tuple[int, int]] = [regions[0]]
    for si, ei in regions[1:]:
        _, prev_ei = merged[-1]
        if si - prev_ei <= gap_samples:
            merged[-1] = (merged[-1][0], ei)
        else:
            merged.append((si, ei))

    # Build corners
    corners: list[Corner] = []
    idx = 1
    for si, ei in merged:
        dur = float(distance[ei] - distance[si]) if ei > si else 0.0
        if dur < min_duration_m:
            continue

        apex_i = si + int(np.argmin(speed[si : ei + 1]))
        ms = float(speed[apex_i])
        if ms >= max_apex_speed:
            continue

        corners.append(Corner(
            id=idx,
            name=f"C{idx}",
            distance_start=float(distance[si]),
            distance_apex=float(distance[apex_i]),
            distance_end=float(distance[ei]),
            min_speed=ms,
        ))
        idx += 1

    return corners


def _detect_corners_speed(
    speed: np.ndarray,
    distance: np.ndarray,
    window_m: float = 200.0,
    threshold_pct: float = 0.92,
    max_apex_speed: float = 280.0,
    min_duration_m: float = 12.0,
) -> list[Corner]:
    """Detect corners from speed dips (fallback when steering unavailable).

    Uses a wider rolling-average window and tighter threshold than the
    original defaults to reliably detect corners on real data.
    """
    if len(speed) < 3 or len(distance) < 3:
        return []

    resolution = float(np.median(np.diff(distance))) if len(distance) > 1 else 1.0
    if resolution <= 0:
        resolution = 1.0
    win_samples = max(int(window_m / resolution), 3)

    # Rolling average
    kernel = np.ones(win_samples) / win_samples
    smoothed = np.convolve(speed, kernel, mode="same")

    # Candidate apices: local minima below threshold
    below = speed < threshold_pct * smoothed
    local_min = np.zeros(len(speed), dtype=bool)
    for i in range(1, len(speed) - 1):
        if speed[i] <= speed[i - 1] and speed[i] <= speed[i + 1]:
            local_min[i] = True
    candidates = np.where(below & local_min)[0]

    if len(candidates) == 0:
        return []

    # Expand each apex ± window_m
    raw_windows: list[tuple[int, int, int]] = []
    for apex_i in candidates:
        apex_d = distance[apex_i]
        si = int(np.searchsorted(distance, apex_d - window_m))
        ei = int(np.searchsorted(distance, apex_d + window_m))
        si = max(si, 0)
        ei = min(ei, len(distance) - 1)
        raw_windows.append((si, apex_i, ei))

    # Merge overlapping windows
    merged: list[tuple[int, int, int]] = [raw_windows[0]]
    for si, ai, ei in raw_windows[1:]:
        prev_si, prev_ai, prev_ei = merged[-1]
        if si <= prev_ei:
            new_si = min(prev_si, si)
            new_ei = max(prev_ei, ei)
            best_ai = prev_ai if speed[prev_ai] <= speed[ai] else ai
            merged[-1] = (new_si, best_ai, new_ei)
        else:
            merged.append((si, ai, ei))

    # Filter and build result
    corners: list[Corner] = []
    idx = 1
    for si, ai, ei in merged:
        ms = float(speed[ai])
        dur = float(distance[ei] - distance[si])
        if ms >= max_apex_speed or dur < min_duration_m:
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


def detect_corners(
    speed: np.ndarray,
    distance: np.ndarray,
    steering: np.ndarray | None = None,
    **kwargs,
) -> list[Corner]:
    """Detect corners — uses steering when available, speed as fallback.

    Parameters
    ----------
    speed : array
        Speed in km/h, sampled at uniform distance.
    distance : array
        Cumulative distance in metres.
    steering : array, optional
        Steering position (normalised, ~-1 to +1).
    **kwargs
        Forwarded to the underlying detection function.
    """
    if steering is not None and len(steering) == len(speed) and np.any(np.abs(steering) > 0.01):
        corners = _detect_corners_steering(speed, distance, steering, **kwargs)
        if corners:
            return corners
    return _detect_corners_speed(speed, distance, **kwargs)
