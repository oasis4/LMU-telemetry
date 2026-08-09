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

from ..core.coaching import (
    SAME_BRAKING_M,
    TIME_NOISE_S,
    Advice,
    CornerComparison,
    advise_on,
    corner_comparison,
    names_braking,
)
from ..core.corners import Corner
from ..core.metrics import APPROACH_M, CornerMetrics, corner_metrics
from ..core.trace import LapTrace
from .buffer import LapBuffer


@dataclass(frozen=True)
class Finding:
    """One completed corner: what was measured, and what to say about it."""

    comparison: CornerComparison
    #: What the rules make of this corner on its own. ``None`` where the
    #: measurements do not agree on a story, which is the normal outcome and
    #: not a failure - the comparison is still here, because the numbers are
    #: the honest answer when no sentence is.
    advice: Advice | None
    #: Set when *advice* is about a braking event this lap has already named.
    #: Monza's Ascari is three corners and one stop.
    repeats_braking: bool = False

    @property
    def to_say(self) -> Advice | None:
        """What the panel should show, which is not always what the rules said.

        A caller that reached for :attr:`advice` directly would coach one brake
        application three times on the way through Ascari, so the suppression
        lives here rather than in each caller's memory.
        """
        return None if self.repeats_braking else self.advice

    @property
    def praise(self) -> "str | None":
        """Said when the corner went well and there is nothing to change.

        Silence and "that was good" are different answers, and a panel that
        only ever speaks up to criticise leaves the driver unable to tell "you
        matched the reference" from "nothing was measured here". So a corner
        that gained time, or matched within the noise, says so.

        Never alongside advice. Something to change beats something to feel
        good about, and a corner that gained a tenth on entry while giving it
        back on exit has a sentence worth more than praise.

        Never in place of a suppressed repeat either. The second and third
        corners of Ascari are quiet because they would say the same thing as
        the first, not because they went well - and praising them there would
        be inventing a verdict out of a formatting decision.
        """
        if self.advice is not None:
            return None
        lost = self.comparison.lost_s
        if lost < -TIME_NOISE_S:
            return f"Good - {abs(lost):.3f} s up on the reference here"
        if abs(lost) <= TIME_NOISE_S:
            # No figure: inside the noise there is nothing to quote that would
            # not be quoting the measurement error.
            return "Level with the reference here"
        return None


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
        self._braking_named: list[float] = []

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
            self._next += 1
            if self._was_watched(corner, buffer):
                out.append(self._finish(corner, buffer))
        return out

    @staticmethod
    def _was_watched(corner: Corner, buffer: LapBuffer) -> bool:
        """Whether this lap actually saw enough of the corner to measure it.

        A corner needs its approach as much as itself: the brake point is
        looked for up to ``APPROACH_M`` before the corner starts. Two ways
        that stretch can be missing - the overlay started while the driver was
        already on track, or the corner sits so close to the start/finish line
        that its braking zone belongs to the previous lap.

        Either way ``np.interp`` holds the first sample flat across the gap,
        and a brake point read there is that one sample repeated. It would
        compare against the reference as confidently as a real one, so the
        corner is passed over instead.
        """
        started = buffer.started_m
        if started is None or len(buffer) < 2:
            return False
        return corner.start_m - APPROACH_M >= max(started, 0.0)

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
        item = advise_on(comparison)

        # The same guard `advice()` applies over a finished lap, kept instead
        # of sorted: this watch meets corners one at a time and cannot look
        # ahead, so it remembers which brake applications it has already
        # spoken about. Keyed on the *reference* brake point, because that is
        # the one that does not move between laps.
        repeat = False
        point = reference.brake_point_m
        if item is not None and names_braking(item) and point is not None:
            repeat = any(
                abs(point - named) < SAME_BRAKING_M for named in self._braking_named
            )
            if not repeat:
                self._braking_named.append(point)

        return Finding(comparison=comparison, advice=item, repeats_braking=repeat)

    def reset(self) -> None:
        """A new lap has begun.

        The reference metrics are kept: they are measurements of the reference
        lap, which is the same lap it was. Which braking events have been named
        is not - that is about the lap being driven, and carrying it over would
        leave the second lap silent about every corner the first one covered.
        """
        self._next = 0
        self._braking_named.clear()
