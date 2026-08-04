"""One lap, every channel resampled onto the track's distance grid.

Channels are sampled at different rates - ``Ground Speed`` at 100 Hz, the
pedals at 50 Hz, ``Lap Dist`` at 10 Hz - and none of them carry timestamps.
Putting them on a common *distance* axis is what makes two laps comparable at
all, and it has to happen once, here, rather than per caller: the whole point
of the reference model is that both sides of a comparison are measured on the
same grid.

Distance resolution is set by ``Lap Dist``, the slowest of them. At 83 m/s its
samples are 8.3 m apart, so a brake point read off this trace is located to
about that, not to the 2 m of the grid it lands on. The grid is fine enough not
to lose anything; it does not add precision that was never recorded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry
from .laps import Lap
from .quality import DISTANCE_TOLERANCE

#: Channel name -> attribute on :class:`LapTrace`. Anything here must exist in
#: the file; see :func:`build_trace` on why a missing one is an error.
DEFAULT_CHANNELS = {
    "Ground Speed": "speed_kmh",
    "Throttle Pos": "throttle",
    "Brake Pos": "brake",
}


class TraceError(ValueError):
    """Raised when a lap cannot be put on the grid, with the reason."""


@dataclass(frozen=True)
class LapTrace:
    """One lap's channels on the track's common distance grid.

    ``time_s`` runs from 0 at the start/finish line to the lap's duration, and
    is the axis every delta is built from.
    """

    lap: Lap
    grid: np.ndarray
    time_s: np.ndarray
    speed_kmh: np.ndarray
    throttle: np.ndarray
    brake: np.ndarray

    def at(self, distance_m: float) -> dict[str, float]:
        """Every channel's value at *distance_m*, interpolated onto the grid."""
        index = int(np.searchsorted(self.grid, float(distance_m), side="left"))
        index = min(max(index, 0), len(self.grid) - 1)
        return {
            "distance_m": float(self.grid[index]),
            "time_s": float(self.time_s[index]),
            "speed_kmh": float(self.speed_kmh[index]),
            "throttle": float(self.throttle[index]),
            "brake": float(self.brake[index]),
        }


#: How long after a lap's start the distance reset may still arrive, in
#: seconds. The window is mapped onto sample indices by rounding, so its first
#: samples can still belong to the previous lap.
RESET_GRACE_S = 2.0


def _progress(session, lap: Lap, track_length_m: float):
    """How far round the lap the car is, against seconds since it began.

    Two things have to be dealt with, and both were measured rather than
    guessed on the Monza reference session.

    The window's first sample can still carry the *previous* lap's distance -
    5776 m of a 5776 m circuit, one sample before the reset - because the lap
    boundary is an event timestamp and the channel is sampled at 10 Hz. Left
    in, it sits above every later value and flattens the whole lap.

    After that, ``Lap Dist`` still is not monotonic sample to sample: it
    wobbles backwards by centimetres. Progress round a lap is its running
    maximum, which is non-decreasing by construction. Sorting the raw values
    by distance instead - the obvious alternative - reorders time along with
    them, and the time axis then runs backwards wherever distance did.
    """
    distance = np.asarray(session.lap_channel(lap, "Lap Dist"), dtype=np.float64)
    if len(distance) < 2:
        raise TraceError(f"lap {lap.number}: only {len(distance)} distance samples")
    hz = session.file.channels.require("Lap Dist").frequency_hz
    elapsed = np.arange(len(distance), dtype=np.float64) / hz

    # A lap is bounded by two crossings of the start/finish line, and Lap Dist
    # resets at a crossing. Both of them can fall inside the window, because
    # the boundary is an event timestamp while the channel is sampled at
    # 10 Hz: the opening reset lands just after the window starts and the
    # closing one just before it ends. Both belong to the neighbours.
    #
    # Rejecting a lap for the closing reset cost 140 of the working set's 426
    # clean laps - a third of them - so the window is trimmed to the samples
    # between the two instead. Whether what remains is still a whole lap is
    # not decided here: resample_to_grid refuses samples that do not span the
    # track, and that guard is the one that has to hold anyway.
    resets = np.flatnonzero(np.diff(distance) < -0.5 * track_length_m)
    opening = resets[elapsed[resets + 1] <= RESET_GRACE_S]
    if len(opening):
        start = int(opening[-1]) + 1
        distance, elapsed = distance[start:], elapsed[start:] - elapsed[start]
        resets = np.flatnonzero(np.diff(distance) < -0.5 * track_length_m)
    if len(resets):
        end = int(resets[0]) + 1
        distance, elapsed = distance[:end], elapsed[:end]

    distance = np.maximum.accumulate(distance)
    # Keep the first time each distance is reached: a stall contributes no new
    # distance, and averaging over it would smear the time axis across it.
    keep = np.concatenate(([True], np.diff(distance) > 1e-6))
    distance, elapsed = distance[keep], elapsed[keep]
    if len(distance) < 2:
        raise TraceError(f"lap {lap.number}: distance never advances")
    return distance, elapsed


def _on_grid(
    session, lap: Lap, name: str, progress, track_length_m: float, tolerance_m: float
) -> np.ndarray:
    """One channel resampled from its own clock onto the distance grid.

    Distance is interpolated onto the channel's clock rather than the other
    way round: distance is what both sides of a comparison are indexed by, so
    it is the axis that must be exact where it was recorded and interpolated
    only in between.
    """
    file, timebase = session.file, session.timebase
    if name not in file.channels:
        raise TraceError(f"{file.path.name}: no channel {name!r}")

    values = np.asarray(session.lap_channel(lap, name), dtype=np.float64)
    if len(values) < 2:
        raise TraceError(f"lap {lap.number}: only {len(values)} samples of {name!r}")

    distance, elapsed = progress
    # Both clocks start at the lap's own t_start, so they are already aligned;
    # they differ only in how densely they sample the same interval.
    value_t = np.arange(len(values), dtype=np.float64) / (
        file.channels.require(name).frequency_hz
    )
    at_value_clock = np.interp(value_t, elapsed, distance)

    keep = np.concatenate(([True], np.diff(at_value_clock) > 1e-6))
    try:
        return geometry.resample_to_grid(
            at_value_clock[keep],
            values[keep],
            track_length_m,
            tolerance_m=tolerance_m,
        )
    except ValueError as exc:
        raise TraceError(f"lap {lap.number}, {name!r}: {exc}") from exc


def build_trace(
    session,
    lap: Lap,
    track_length_m: float | None,
    channels: dict[str, str] | None = None,
) -> LapTrace:
    """Put one lap on the track's distance grid.

    Raises :class:`TraceError` rather than returning a partial trace. Every
    caller of this compares one lap against another, and a trace with invented
    ends compares as confidently as a real one - so the failure has to be loud.
    """
    if track_length_m is None or track_length_m <= 0:
        raise TraceError(f"lap {lap.number}: no usable track length")
    channels = DEFAULT_CHANNELS if channels is None else channels

    grid = geometry.grid_for(track_length_m)
    tolerance_m = track_length_m * DISTANCE_TOLERANCE
    progress = _progress(session, lap, track_length_m)

    resampled = {
        attribute: _on_grid(session, lap, name, progress, track_length_m, tolerance_m)
        for name, attribute in channels.items()
    }
    return LapTrace(
        lap=lap, grid=grid, time_s=_time_axis(lap, progress, grid), **resampled
    )


def _time_axis(lap: Lap, progress, grid: np.ndarray) -> np.ndarray:
    """Seconds since the start of the lap, at each grid point.

    Built by inverting the progress trace: ``Lap Dist`` gives distance as a
    function of time, and this reads it back the other way.
    """
    distance, elapsed = progress
    time_s = np.interp(grid, distance, elapsed)

    # np.interp holds its end values flat outside the input range, so the few
    # grid points before the first sample and after the last one come back as
    # runs of equal time. Those two runs are extended at the lap's own mean
    # pace - the grid was admitted within DISTANCE_TOLERANCE of the samples,
    # so both are short. Only they are touched: a blanket repair of every
    # non-increasing step would overwrite the rest of the lap with a straight
    # line, which silently replaces the very moment worth looking at.
    pace = (elapsed[-1] - elapsed[0]) / (distance[-1] - distance[0])
    before = grid < distance[0]
    after = grid > distance[-1]
    time_s[before] = elapsed[0] - pace * (distance[0] - grid[before])
    time_s[after] = elapsed[-1] + pace * (grid[after] - distance[-1])

    if np.any(np.diff(time_s) <= 0.0):
        at = int(np.flatnonzero(np.diff(time_s) <= 0.0)[0])
        raise TraceError(
            f"lap {lap.number}: time does not advance at {grid[at]:.0f} m - "
            f"the distance samples it was inverted from are not ordered in time"
        )
    return time_s
