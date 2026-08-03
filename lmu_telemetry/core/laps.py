"""Lap segmentation.

A lap exists only between two consecutive ``Lap`` events, and its duration is
the difference of their timestamps.  There is deliberately no fallback path:
if the game did not record the boundary, no lap is reported.

``Lap Dist`` is used to measure distance *within* a lap, never to delimit one.
Its resets are unreliable - across the corpus one Monza session has 12 ``Lap``
events but 13 distance resets, another 5 against 6.  Treating those resets as
lap boundaries produced partial laps that were then reported as full ones,
which is where the impossible lap times came from.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .sectors import sector_times
from .timebase import TimeBase


class NoLapDataError(ValueError):
    """Raised when a file carries no ``Lap`` event table at all."""


@dataclass(frozen=True)
class Lap:
    """One complete lap, bounded by two ``Lap`` events."""

    number: int
    t_start: float
    t_end: float
    duration_s: float
    sectors_s: tuple[float, float, float] | None
    touched_pits: bool
    distance_m: float


def _touched_pits(tf, t_start: float, t_end: float) -> bool:
    events = tf.events("In Pits")
    if events is None:
        return False
    ts, val = events
    inside = (ts >= t_start) & (ts < t_end)
    if np.any(val[inside] != 0):
        return True
    # Also honour the state carried into the lap from an earlier event.
    before = ts < t_start
    return bool(np.any(before)) and float(val[before][-1]) != 0.0


def _distance_covered(tf, timebase: TimeBase, t_start: float, t_end: float) -> float:
    """Metres covered in the interval, summing across any Lap Dist reset.

    ``Lap Dist`` is mandatory - it is present in every file of the corpus.
    Its absence means a broken file, so this raises ``MissingChannelError``
    rather than returning a substitute ``0.0``, which would be
    indistinguishable from "the car did not move".
    """
    spec = tf.channels.require("Lap Dist")
    dist = tf.channel("Lap Dist")
    i0 = min(timebase.index_at(t_start, spec.frequency_hz), len(dist))
    i1 = min(timebase.index_at(t_end, spec.frequency_hz), len(dist))
    segment = dist[i0:i1]
    if len(segment) < 2:
        return 0.0
    steps = np.diff(segment)
    return float(np.sum(steps[steps > 0.0]))


def segment_laps(tf, timebase: TimeBase) -> list[Lap]:
    """Return every lap that is bounded by two consecutive ``Lap`` events."""
    events = tf.events("Lap")
    if events is None:
        raise NoLapDataError(f"{tf.path.name}: no 'Lap' event table")
    ts, numbers = events
    if len(ts) < 2:
        return []
    sector_events = tf.events("Current Sector")

    laps: list[Lap] = []
    for i in range(len(ts) - 1):
        t_start = float(ts[i])
        t_end = float(ts[i + 1])
        laps.append(
            Lap(
                number=int(numbers[i]),
                t_start=t_start,
                t_end=t_end,
                duration_s=t_end - t_start,
                sectors_s=sector_times(sector_events, t_start, t_end),
                touched_pits=_touched_pits(tf, t_start, t_end),
                distance_m=_distance_covered(tf, timebase, t_start, t_end),
            )
        )
    return laps
