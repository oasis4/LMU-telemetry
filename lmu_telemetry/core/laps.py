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
    #: The lap time the game itself recorded at the closing crossing, if it
    #: recorded one. ``None`` means no ``Lap Time`` event landed there;
    #: ``0.0`` is the game's own way of saying the lap earned no time at all.
    #: This is not the same number as ``duration_s``: that one is derived from
    #: the ``Lap`` event timestamps, and comparing the two is how a file with
    #: unreliable lap boundaries gives itself away.
    recorded_time_s: float | None = None


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
    indistinguishable from "the car did not move". ``channel_window`` raises
    that error itself via ``tf.channels.require``, so no explicit check is
    needed here.
    """
    segment = timebase.channel_window(tf, "Lap Dist", t_start, t_end)
    if len(segment) < 2:
        return 0.0
    steps = np.diff(segment)
    return float(np.sum(steps[steps > 0.0]))


#: How far from a lap's closing crossing a ``Lap Time`` event may sit and
#: still be that lap's. The event is written at the crossing, so this only
#: absorbs the gap between the two event streams' timestamps.
LAP_TIME_MATCH_WINDOW_S = 2.0


def _recorded_lap_time(lap_time_events, t_end: float) -> float | None:
    """The lap time the game wrote at *t_end*, or None if it wrote none."""
    if lap_time_events is None:
        return None
    ts, values = lap_time_events
    near = np.abs(ts - t_end) < LAP_TIME_MATCH_WINDOW_S
    if not np.any(near):
        return None
    candidates = np.flatnonzero(near)
    closest = candidates[np.argmin(np.abs(ts[candidates] - t_end))]
    return float(values[closest])


#: How far either side of a lap's boundary its own distance reset may sit, in
#: seconds.
#:
#: A lap boundary is an event timestamp while ``Lap Dist`` is sampled at 10 Hz,
#: so the window rounds outwards - but in some sessions the ``Lap`` event fires
#: a good deal later than the car crossed the line. Measured over the working
#: set, the position samples of about 30 % of clean laps begin 100-115 m into
#: the lap, which is the ~1.3 s by which the event lagged. Those metres are
#: not missing: they sit at the end of the previous lap's window. So the
#: position of a lap is read from a window opened this much early, and trimmed
#: back to the reset - real samples rather than an interpolated straight line.
RESET_GRACE_S = 2.0


def one_lap_slice(
    distance: np.ndarray,
    frequency_hz: int,
    track_length_m: float,
    lookback_s: float = 0.0,
) -> slice:
    """The samples of *distance* that belong to this lap and no other.

    A lap is bounded by two crossings of the start/finish line and ``Lap Dist``
    resets at a crossing, so both resets can fall inside the window: the
    opening one just after it starts, the closing one just before it ends.
    The samples outside them belong to the neighbouring laps.

    Every caller that reads a lap's position has to do this, and one of them
    not doing it is not a small error. ``assess_lap`` sorted the raw samples by
    distance instead, which put the *next* lap's samples - values near zero -
    at the front. The lap then appeared to span the whole track when its own
    samples began 144 m in, and the racing line it contributed to the
    reference model was stitched from two laps across the start/finish line.
    """
    if len(distance) < 2:
        return slice(0, len(distance))
    resets = np.flatnonzero(np.diff(distance) < -0.5 * track_length_m)
    if len(resets) == 0:
        return slice(0, len(distance))

    # *lookback_s* is how much of the window sits before the lap's own start,
    # so the opening reset may be that much earlier still. Leaving it out puts
    # the reset exactly on the boundary of the allowance and the slice then
    # keeps the *previous* lap instead of this one.
    grace_samples = (RESET_GRACE_S + lookback_s) * frequency_hz
    opening = resets[resets + 1 <= grace_samples]
    start = int(opening[-1]) + 1 if len(opening) else 0

    after_start = resets[resets >= start]
    stop = int(after_start[0]) + 1 if len(after_start) else len(distance)
    return slice(start, max(stop, start))


def segment_laps(tf, timebase: TimeBase) -> list[Lap]:
    """Return every lap that is bounded by two consecutive ``Lap`` events."""
    events = tf.events("Lap")
    if events is None:
        raise NoLapDataError(f"{tf.path.name}: no 'Lap' event table")
    ts, numbers = events
    if len(ts) < 2:
        return []
    sector_events = tf.events("Current Sector")
    lap_time_events = tf.events("Lap Time")

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
                recorded_time_s=_recorded_lap_time(lap_time_events, t_end),
            )
        )
    return laps
