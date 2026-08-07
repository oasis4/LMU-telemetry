"""Reporting each corner once, the moment the car has finished it.

A corner's numbers are taken as soon as its end is behind the car, and
compared against the reference's numbers for the same corner. Nothing is
measured ahead of the car, because ahead of the car the buffer holds its last
sample flat and every figure read there would be that instant repeated.

``lost_s`` is the difference of the two corner times rather than the integral
of a delta trace: there is no delta trace until the lap ends, and waiting for
one would mean saying nothing until the driver is past the corner they wanted
to hear about. :func:`delta.time_lost_over` measures exactly that difference
across a corner's span, so the two agree - and ``test_live_watch`` pins them
together, because two figures for one corner is how a panel and a browser come
to disagree.

A corner containing the start/finish line is not reported. Its start lies in
the previous lap, which this buffer has already forgotten, so its span is half
empty and any number from it would be about nothing. It is the one corner the
post-lap view can measure and this cannot.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.coaching import Advice, CornerComparison, advise_on, corner_comparison
from ..core.corners import Corner
from ..core.metrics import CornerMetrics, corner_metrics
from ..core.trace import LapTrace
from .buffer import LapBuffer


@dataclass(frozen=True)
class Finding:
    """One completed corner: what was measured, and what to say about it."""

    comparison: CornerComparison
    #: ``None`` where the measurements do not agree on a story, which is the
    #: normal outcome and not a failure. The comparison is still here: the
    #: numbers are the honest answer when no sentence is.
    advice: Advice | None


class CornerWatch:
    """Watches a lap go by and reports each corner as it is completed."""

    def __init__(self, reference: LapTrace, corners) -> None:
        self.reference = reference
        # In the order they are finished, and without the one across the line;
        # see the module docstring. Sorting by end_m is what makes "the next
        # corner to complete" a single moving index rather than a search.
        self.corners = sorted(
            (c for c in corners if c.start_m <= c.end_m), key=lambda c: c.end_m
        )
        self._next = 0
        self._reference_metrics: dict[int, CornerMetrics] = {}

    def advance(self, buffer: LapBuffer) -> "list[Finding]":
        """Every corner completed since the last call, in the order driven.

        Returns a list rather than one finding: a caller that polls slowly, or
        a replay stepping in metres rather than frames, can pass two corner
        ends in one step, and the second would otherwise be lost.
        """
        reached = buffer.reached_m
        if reached is None:
            return []

        out = []
        while self._next < len(self.corners):
            corner = self.corners[self._next]
            if reached < corner.end_m:
                break
            out.append(self._finish(corner, buffer))
            self._next += 1
        return out

    def _finish(self, corner: Corner, buffer: LapBuffer) -> Finding:
        reference = self._reference_metrics.get(corner.index)
        if reference is None:
            # Measured once and kept: the reference lap does not change, and
            # re-measuring it every corner of every lap is the same answer at
            # 50 Hz.
            reference = corner_metrics(self.reference, corner)
            self._reference_metrics[corner.index] = reference

        driven = corner_metrics(buffer.trace(), corner)
        comparison = corner_comparison(
            corner, reference, driven, lost_s=driven.time_s - reference.time_s
        )
        return Finding(comparison=comparison, advice=advise_on(comparison))

    def reset(self) -> None:
        """A new lap has begun.

        The reference metrics are kept. They are measurements of the reference
        lap, which is the same lap it was.
        """
        self._next = 0
