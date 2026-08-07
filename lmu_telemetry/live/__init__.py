"""Driving the corner comparison from live telemetry instead of a recording.

Nothing in this package measures anything. That is the whole point of it: a
lap being driven ends up on the same 2 m grid, against the same corner list,
as a lap read from disk - so :mod:`core.metrics` and :mod:`core.coaching`
answer for both, and there is one definition of a brake point rather than two.

    LapBuffer      the lap so far, as samples arrive
    CornerWatch    reports each corner the moment the car has finished it
"""

from .buffer import LapBuffer, LiveSample

__all__ = ["LapBuffer", "LiveSample"]
