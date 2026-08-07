"""One lap being driven, filled onto the track's grid as it goes.

Distance is the awkward axis here too, for its own reason. The rF2 plugin
splits its state across two mappings, and they do not run at the same rate:
pedals, speed and elapsed time arrive in the telemetry buffer at about 50 Hz,
but ``mLapDist`` - how far round the lap the car is - lives in the *scoring*
buffer at about 5 Hz. At 90 m/s that is 18 m between distance readings, which
is coarser than this grid and coarser than the 10 Hz ``Lap Dist`` the offline
pipeline works from.

So distance is not read; it is carried. :mod:`live.sharedmem` anchors on
``mLapDist`` each time scoring advances and dead-reckons from speed in
between, which is accurate because speed *is* sampled at 50 Hz and the gap
being integrated over is 200 ms.

None of that is this module's problem: a :class:`LiveSample` arrives with its
distance already settled. What happens here is only the interpolation onto the
grid, exactly as :func:`trace._on_grid` does offline, and by no new scheme.

Grid points ahead of the car hold the last value seen, because that is what
``np.interp`` does outside its input range. That is safe only because nothing
is ever measured there: :class:`watch.CornerWatch` asks a corner for its
numbers once the corner is behind the car, never before.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.trace import LapTrace


@dataclass(frozen=True)
class LiveSample:
    """One instant of the car, as shared memory reports it.

    The units are the ones the rest of the package works in - km/h and
    normalised 0..1 pedals - so the conversion belongs in the reader that
    builds these, not in anything downstream.
    """

    distance_m: float
    time_s: float
    speed_kmh: float
    throttle: float
    brake: float
    steering: float


class LapBuffer:
    """The lap so far, ready to be put on the track model's grid."""

    def __init__(self, grid: np.ndarray) -> None:
        self.grid = np.asarray(grid, dtype=np.float64)
        self._samples: list[LiveSample] = []
        self._reached: float | None = None

    @property
    def reached_m(self) -> float | None:
        """How far round the lap the car has come, or None before it starts."""
        return self._reached

    def reset(self) -> None:
        """Start a new lap, called when the game reports the line was crossed."""
        self._samples.clear()
        self._reached = None

    def add(self, sample: LiveSample) -> None:
        """Record one instant, unless it is behind where the lap already is.

        Shared memory repeats a frame whenever the reader gets ahead of the
        game, and jitters by centimetres besides. A sample behind the furthest
        point reached carries no new information, and interpolating it in would
        put a dent in the trace at whatever the car happened to be doing then -
        a phantom lift, or a brush of the brakes that never happened.
        """
        if self._reached is not None and sample.distance_m <= self._reached:
            return
        self._samples.append(sample)
        self._reached = sample.distance_m

    def trace(self) -> LapTrace:
        """The lap so far as a :class:`LapTrace`, for ``core.metrics`` to read.

        Raises rather than returning a trace built from one sample. Held flat
        across the whole grid, a single sample measures as confidently as a
        real lap, and every number taken from it would be that one instant
        wearing a lap's clothes.
        """
        if len(self._samples) < 2:
            raise ValueError(
                f"a lap needs at least 2 samples to be measured, have "
                f"{len(self._samples)}"
            )
        distance = np.array([s.distance_m for s in self._samples])

        def on_grid(pick) -> np.ndarray:
            return np.interp(
                self.grid, distance, np.array([pick(s) for s in self._samples])
            )

        return LapTrace(
            lap=None,
            grid=self.grid,
            time_s=on_grid(lambda s: s.time_s),
            speed_kmh=on_grid(lambda s: s.speed_kmh),
            throttle=on_grid(lambda s: s.throttle),
            brake=on_grid(lambda s: s.brake),
            steering=on_grid(lambda s: s.steering),
        )
