"""What one driver did through one corner.

Every threshold here is in the units the channel register declares, after
``normalise`` has brought a ``'%'`` channel to 0..1. The old implementation
checked ``brake > 0.1`` against values that run 0-100, so it reported a brake
point wherever the pedal touched 0.1 % - on sensor noise - and every brake
point, corner metric and coaching tip built on it was worthless.

Nothing here anchors on the apex. ``argmax|kappa|`` moves between the lobes of
a broad two-lobed corner when they differ by only a few percent: Le Mans'
Porsche Curves 2 shifted 182 m that way while its start, end and heading
stayed put. A metric keyed on it would have moved with it. The corner's start
and end are stable, so they are what everything is measured between.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .corners import Corner
from .geometry import GRID_STEP_M, span_indices
from .trace import LapTrace

#: Brake pressure above which the driver is braking, normalised (5 %).
BRAKE_ON = 0.05
#: Brake pressure below which the pedal is off again, normalised (2 %). Lower
#: than BRAKE_ON on purpose: a trail tapers to nothing, and a release read at
#: the threshold that *starts* a braking event cuts the last stretch of it
#: off - which is exactly the stretch a trail-braking difference lives in.
TRAIL_OFF = 0.02
#: Throttle above which the driver is back on the power, normalised (50 %).
THROTTLE_ON = 0.50
#: How far before a corner to look for its braking, in metres. Long enough for
#: a hard stop from top speed - Le Mans brakes for about 200 m into Mulsanne.
APPROACH_M = 250.0


@dataclass(frozen=True)
class CornerMetrics:
    """One lap's numbers through one corner. ``None`` means "did not happen"."""

    corner: Corner
    brake_point_m: float | None
    #: Where pressure was highest in that same braking event, and where the
    #: pedal came off it. Between them is the trail phase, whose *length* is
    #: the number worth comparing: two drivers can release in different places
    #: and both be right, but how far they bled the brake off over is what
    #: turns up in the corner's outcome.
    brake_peak_m: float | None
    brake_release_m: float | None
    trail_length_m: float | None
    entry_speed_kmh: float
    min_speed_kmh: float
    min_speed_at_m: float
    throttle_point_m: float | None
    exit_speed_kmh: float
    time_s: float


def braking_zones(
    trace: LapTrace, threshold: float = BRAKE_ON
) -> "list[tuple[float, float]]":
    """Every stretch of the lap the car spent on the brakes, in metres.

    Measured here rather than in the client, and from the full trace rather
    than the decimated one a page is sent. Decimation keeps the samples where
    the *delta* turns, so a short brush of the brakes can fall between two
    kept samples and vanish - a map drawn from it would show no braking where
    there was some, and say nothing about it.

    Two applications inside one corner stay two zones. Merged, a map draws a
    band straight across the stretch the driver was off the pedal, which is
    the part worth seeing.

    A lone sample over the threshold is not a zone. At a 2 m grid that is a
    twitch, and drawn it becomes a dot claiming a brake point that was never
    applied.
    """
    grid = trace.grid
    zones = []
    for first, last in _runs(np.asarray(trace.brake, dtype=np.float64) > threshold):
        if last == first:
            continue
        zones.append((float(grid[first]), float(grid[last])))
    return zones


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous stretches where *mask* is true, as (first, last) pairs."""
    runs, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def _brake_shape(
    trace: LapTrace, corner: Corner, slowest: int
) -> "tuple[float, float, float, float] | None":
    """Start, peak, release and trail length of this corner's braking, in metres.

    The event is found as it always was: the approach is searched for
    stretches of brake pressure, and the last one before the slowest point is
    the one that belongs to this corner. Taking the *first* stretch instead
    would report a brush of the pedal several hundred metres earlier -
    correcting a slide on the straight, say - as the brake point for the
    corner.

    The release is then searched forward to the corner's end rather than to
    the slowest point, because a trail carries past the minimum speed. Bounded
    at the slowest sample, every trail would come back ending exactly there: a
    number produced by the window, not by the driving.

    Trail length is counted in grid steps rather than subtracted from the two
    distances, so it stays right for a corner that wraps the start/finish
    line, where peak and release sit at opposite ends of the array.
    """
    lap_length = float(trace.grid[-1]) + GRID_STEP_M
    # An approach as long as the lap would wrap onto itself and come back as
    # no approach at all, silently. Every circuit is far longer than this, but
    # the failure would be a wrong brake point rather than an error.
    approach_m = min(APPROACH_M, lap_length - GRID_STEP_M)
    approach_start = (corner.start_m - approach_m) % lap_length
    window = span_indices(trace.grid, approach_start, float(trace.grid[slowest]))
    if len(window) == 0:
        return None

    runs = _runs(trace.brake[window] > BRAKE_ON)
    if not runs:
        return None
    start_index = int(window[runs[-1][0]])

    ahead = span_indices(trace.grid, float(trace.grid[start_index]), corner.end_m)
    if len(ahead) == 0:
        return None
    # The pedal is above BRAKE_ON at ahead[0] and BRAKE_ON > TRAIL_OFF, so this
    # run always holds at least its first sample and `last` is never -1.
    released = np.flatnonzero(trace.brake[ahead] <= TRAIL_OFF)
    last = len(ahead) - 1 if len(released) == 0 else int(released[0]) - 1
    peak = int(np.argmax(trace.brake[ahead[: last + 1]]))

    return (
        float(trace.grid[start_index]),
        float(trace.grid[ahead[peak]]),
        float(trace.grid[ahead[last]]),
        float(last - peak) * GRID_STEP_M,
    )


def _throttle_point(trace: LapTrace, corner: Corner, slowest: int) -> float | None:
    """Where the driver got back on the power, at or after the slowest point."""
    window = span_indices(trace.grid, float(trace.grid[slowest]), corner.end_m)
    if len(window) == 0:
        return None
    on = np.flatnonzero(trace.throttle[window] > THROTTLE_ON)
    if len(on) == 0:
        return None
    return float(trace.grid[window[int(on[0])]])


def corner_metrics(trace: LapTrace, corner: Corner) -> CornerMetrics:
    """Measure *trace* through *corner*."""
    inside = span_indices(trace.grid, corner.start_m, corner.end_m)
    if len(inside) < 2:
        raise ValueError(
            f"corner {corner.index} spans {len(inside)} grid samples, "
            f"which is not enough to measure anything"
        )

    slowest = int(inside[int(np.argmin(trace.speed_kmh[inside]))])
    time_s = float(trace.time_s[inside[-1]] - trace.time_s[inside[0]])
    if corner.start_m > corner.end_m:
        # The two halves are half a lap apart in the array; their times do not
        # subtract. Sum each half's own elapsed time instead.
        tail = span_indices(trace.grid, corner.start_m, float(trace.grid[-1]))
        head = span_indices(trace.grid, float(trace.grid[0]), corner.end_m)
        time_s = float(
            (trace.time_s[tail[-1]] - trace.time_s[tail[0]])
            + (trace.time_s[head[-1]] - trace.time_s[head[0]])
        )

    shape = _brake_shape(trace, corner, slowest)
    return CornerMetrics(
        corner=corner,
        brake_point_m=None if shape is None else shape[0],
        brake_peak_m=None if shape is None else shape[1],
        brake_release_m=None if shape is None else shape[2],
        trail_length_m=None if shape is None else shape[3],
        entry_speed_kmh=float(trace.speed_kmh[inside[0]]),
        min_speed_kmh=float(trace.speed_kmh[slowest]),
        min_speed_at_m=float(trace.grid[slowest]),
        throttle_point_m=_throttle_point(trace, corner, slowest),
        exit_speed_kmh=float(trace.speed_kmh[inside[-1]]),
        time_s=time_s,
    )


def lap_metrics(trace: LapTrace, corners) -> list[CornerMetrics]:
    """Measure *trace* through every corner, in track order."""
    return [corner_metrics(trace, corner) for corner in corners]
