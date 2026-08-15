"""A recorded lap, handed out one sample at a time as if it were being driven.

This is not a convenience. It is what makes everything above
:mod:`live.sharedmem` verifiable on a machine with no sim running - and the
only way to see the panel work at all before the plugin DLL is installed.

The lap is emitted at its own pace: the recorded time axis is followed against
the wall clock, so a corner arrives when it would have arrived. *speed* scales
that, because watching a 111 s Monza lap in real time to check a two-line
change is not a test anybody runs twice.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from ..core.trace import LapTrace
from .buffer import LiveSample


def replay(trace: LapTrace, speed: float = 1.0) -> Iterator[LiveSample]:
    """Yield *trace* as live samples, paced against the wall clock.

    Every grid point is emitted, so the buffer receives the lap at 2 m
    resolution - finer than shared memory will manage, which is the point:
    if the path above disagrees with the offline pipeline here, the
    disagreement is in the code and not in the sampling.
    """
    if speed <= 0.0:
        raise ValueError(f"replay speed must be positive, got {speed}")

    started = time.perf_counter()
    for i in range(len(trace.grid)):
        lap_time = float(trace.time_s[i])
        # Sleep only if the replay is ahead of where it should be. Behind, it
        # simply carries on: dropping the pacing is better than dropping the
        # samples, which would leave holes the buffer would interpolate over.
        ahead = (lap_time / speed) - (time.perf_counter() - started)
        if ahead > 0:
            time.sleep(ahead)
        yield LiveSample(
            distance_m=float(trace.grid[i]),
            time_s=lap_time,
            speed_kmh=float(trace.speed_kmh[i]),
            throttle=float(trace.throttle[i]),
            brake=float(trace.brake[i]),
            steering=float(trace.steering[i]),
        )
