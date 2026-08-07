"""Where a lap lost time, and what the driver did differently there.

Two laps of the same track identity are measured against **one** corner list.
The old compare view fetched a separate list per side, so the two halves of
every per-corner figure answered different questions.

What this does not do is decide why a driver was slower. It reports the time
lost in a corner and the differences that were measured in it, largest first,
each with its amount. Choosing a cause from those is the driver's job: braking
five metres later can be the reason for a loss or the reason for a gain, and
nothing in the telemetry settles which.
"""

from __future__ import annotations

from dataclasses import dataclass

from .corners import Corner
from .delta import delta_s, time_lost_over
from .metrics import CornerMetrics, corner_metrics
from .trace import LapTrace

#: Differences smaller than these are not worth mentioning: they sit inside
#: what the recording can resolve. Distances are limited by Lap Dist at 10 Hz,
#: which is 5-8 m between samples at racing speed, so a brake-point difference
#: under 5 m says nothing.
BRAKE_POINT_NOISE_M = 5.0
SPEED_NOISE_KMH = 1.0
TIME_NOISE_S = 0.02
#: A trail length is the gap between two positions on one trace, so its error
#: is about twice a single position's - which is why this is not
#: BRAKE_POINT_NOISE_M.
TRAIL_NOISE_M = 2 * BRAKE_POINT_NOISE_M


@dataclass(frozen=True)
class Difference:
    """One measured difference, with its amount and the unit it is in."""

    what: str
    amount: float
    unit: str

    def __str__(self) -> str:
        return f"{self.what} {self.amount:+.1f} {self.unit}"


@dataclass(frozen=True)
class CornerComparison:
    """How the two laps differed through one corner."""

    corner: Corner
    lost_s: float
    reference: CornerMetrics
    other: CornerMetrics
    differences: tuple[Difference, ...]

    @property
    def summary(self) -> str:
        """One line: the time lost and the differences behind it, largest first."""
        verb = "lost" if self.lost_s >= 0 else "gained"
        head = f"{self.corner.name}: {verb} {abs(self.lost_s):.2f} s"
        if not self.differences:
            return f"{head} with nothing measurably different"
        return f"{head} ({', '.join(str(d) for d in self.differences)})"


def _differences(reference: CornerMetrics, other: CornerMetrics) -> tuple[Difference, ...]:
    """Every measured difference worth mentioning, largest first.

    A difference whose value is missing on either side is left out rather than
    treated as zero: one driver braking and the other not is not a
    brake-point difference of nothing.
    """
    found: list[tuple[float, Difference]] = []

    if reference.brake_point_m is not None and other.brake_point_m is not None:
        metres = other.brake_point_m - reference.brake_point_m
        if abs(metres) >= BRAKE_POINT_NOISE_M:
            found.append((abs(metres), Difference("brake point", metres, "m")))
    elif reference.brake_point_m is None and other.brake_point_m is not None:
        found.append((1e9, Difference("braked where the reference did not", 0.0, "")))
    elif reference.brake_point_m is not None and other.brake_point_m is None:
        found.append((1e9, Difference("did not brake where the reference did", 0.0, "")))

    kmh = other.min_speed_kmh - reference.min_speed_kmh
    if abs(kmh) >= SPEED_NOISE_KMH:
        found.append((abs(kmh) * 10.0, Difference("minimum speed", kmh, "km/h")))

    kmh = other.exit_speed_kmh - reference.exit_speed_kmh
    if abs(kmh) >= SPEED_NOISE_KMH:
        found.append((abs(kmh) * 10.0, Difference("exit speed", kmh, "km/h")))

    if reference.throttle_point_m is not None and other.throttle_point_m is not None:
        metres = other.throttle_point_m - reference.throttle_point_m
        if abs(metres) >= BRAKE_POINT_NOISE_M:
            found.append((abs(metres), Difference("throttle point", metres, "m")))

    if reference.brake_release_m is not None and other.brake_release_m is not None:
        metres = other.brake_release_m - reference.brake_release_m
        if abs(metres) >= BRAKE_POINT_NOISE_M:
            found.append((abs(metres), Difference("brake release", metres, "m")))

    if reference.trail_length_m is not None and other.trail_length_m is not None:
        metres = other.trail_length_m - reference.trail_length_m
        if abs(metres) >= TRAIL_NOISE_M:
            found.append((abs(metres), Difference("trail length", metres, "m")))

    found.sort(key=lambda entry: -entry[0])
    return tuple(difference for _weight, difference in found)


def corner_comparison(
    corner: Corner,
    reference: CornerMetrics,
    other: CornerMetrics,
    lost_s: float,
) -> CornerComparison:
    """One corner's comparison, from metrics that have already been taken.

    Public because the live overlay builds comparisons one corner at a time,
    as each is completed, and cannot wait for the whole-lap delta that
    :func:`compare_corners` integrates. Both paths come through here so the
    list of differences is assembled once: two constructions of a
    ``CornerComparison`` would be two chances for the panel and the browser to
    describe one corner differently.

    *lost_s* is the caller's to supply, because the two paths measure it
    differently and both are right - see :mod:`live.watch`.
    """
    return CornerComparison(
        corner=corner,
        lost_s=lost_s,
        reference=reference,
        other=other,
        differences=_differences(reference, other),
    )


def advise_on(comparison: CornerComparison) -> "Advice | None":
    """What to try in this corner, or ``None`` if the data does not say.

    The single-corner entry point. :func:`advice` is the whole-lap one, which
    also drops a second finding about a braking event it has already named;
    that guard needs the other corners to exist, so it has nothing to do here.
    """
    return _advise(comparison)


def compare_corners(
    reference: LapTrace, other: LapTrace, corners
) -> list[CornerComparison]:
    """Compare two laps corner by corner, against one corner list.

    Both traces must be on the same grid; :func:`delta.delta_s` refuses them
    otherwise, because two grids mean two different tracks.
    """
    delta = delta_s(reference, other)
    return [
        corner_comparison(
            corner,
            corner_metrics(reference, corner),
            corner_metrics(other, corner),
            time_lost_over(delta, reference.grid, corner),
        )
        for corner in corners
    ]


def biggest_losses(comparisons, count: int = 3) -> list[CornerComparison]:
    """The corners that cost the most time, worst first."""
    return sorted(comparisons, key=lambda c: -c.lost_s)[:count]


#: A corner has to have cost at least this much before anything is said about
#: why. Below it the differences are within what one lap varies from the next,
#: and a confident sentence about them would be noise given a voice.
ADVICE_MIN_LOSS_S = 0.05

#: How much later or earlier counts as a real difference in a pedal point.
#: Lap Dist runs at 10 Hz - 5 to 8 m between samples at racing speed - so this
#: is two samples' worth, not a resolution the recording can support.
ADVICE_POINT_M = 15.0

#: And how much slower counts, in km/h.
ADVICE_SPEED_KMH = 3.0

#: How much longer or shorter a trail phase has to be to count. A trail length
#: is the gap between two positions on one trace, so its error is about twice
#: ADVICE_POINT_M's - and a typical trail runs 20-60 m, which makes this
#: deliberately demanding. Silence is the right answer here more often than
#: not: a release point is as often a style as a mistake.
ADVICE_TRAIL_M = 15.0


@dataclass(frozen=True)
class Advice:
    """Something to try, with the measurement it rests on.

    ``because`` is the evidence, in the driver's own numbers. Nothing here is
    inferred beyond what the pattern shows: the telemetry records what was
    done, never why, so an explanation that the data does not force is left
    unsaid rather than guessed.
    """

    corner: Corner
    headline: str
    detail: str
    because: str
    lost_s: float


def _advise(comparison: "CornerComparison") -> "Advice | None":
    """What to try in this corner, or None if the data does not say.

    Each pattern below needs *several* measurements to agree before it will
    speak. Later braking on its own means nothing - it is what a faster driver
    does. Later braking together with a lower minimum speed and lost time is a
    corner entered too fast to rotate, and that is a claim the numbers carry.

    The rules that read the *shape* of the braking - where pressure peaked and
    how far it was bled off over - carry that further: each is tied to a
    minimum or exit speed, and none of them may speak from the shape alone.
    One driver stops the car and turns it, another carries the brake to the
    apex, and both are right. Without a result attached, a sentence about the
    release is technically true and useless to drive on.

    Order matters here. The three shape rules each sit directly above the
    coarser rule they refine, so the coarse one still catches every corner
    whose shape says nothing.
    """
    if comparison.lost_s < ADVICE_MIN_LOSS_S:
        return None

    reference, other = comparison.reference, comparison.other
    minimum = other.min_speed_kmh - reference.min_speed_kmh
    exit_speed = other.exit_speed_kmh - reference.exit_speed_kmh
    brake = (
        None
        if reference.brake_point_m is None or other.brake_point_m is None
        else other.brake_point_m - reference.brake_point_m
    )
    throttle = (
        None
        if reference.throttle_point_m is None or other.throttle_point_m is None
        else other.throttle_point_m - reference.throttle_point_m
    )
    trail = (
        None
        if reference.trail_length_m is None or other.trail_length_m is None
        else other.trail_length_m - reference.trail_length_m
    )
    peak = (
        None
        if reference.brake_peak_m is None or other.brake_peak_m is None
        else other.brake_peak_m - reference.brake_peak_m
    )

    def amounts(*parts: str) -> str:
        return ", ".join(parts)

    # Braked later and could not carry it: entered faster than the corner took.
    if (
        brake is not None
        and brake > ADVICE_POINT_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Try braking earlier here",
            "You braked later but were slower through the middle, so the extra "
            "entry speed did not survive the corner.",
            amounts(
                f"brake point {brake:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    # Braked earlier, off the pedal sooner, and slower through the middle: the
    # car was stopped in a straight line and then rolled through the corner
    # with nothing left on the brake to turn it. This is the rule below with
    # its reason attached, so it is tried first and that rule catches whatever
    # it leaves - a brake-point difference with no trail difference behind it
    # is still worth saying, just not with the second half of this sentence.
    if (
        brake is not None
        and brake < -ADVICE_POINT_M
        and trail is not None
        and trail < -ADVICE_TRAIL_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Brake a touch later and stay on it longer",
            "You went to the brake earlier and came off it sooner, so the car "
            "was slowed in a straight line and had nothing left on the brake "
            "to turn with.",
            amounts(
                f"brake point {brake:+.0f} m",
                f"trail length {trail:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    # Braked earlier and slower everywhere: there was time left on the brakes.
    if (
        brake is not None
        and brake < -ADVICE_POINT_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "You can brake later here",
            "You braked earlier and were still slower through the corner, so "
            "the earlier braking was not buying entry speed.",
            amounts(
                f"brake point {brake:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    # Off the brake much later, with the entry matched and the exit slower:
    # the brake was still on where the reference was already driving.
    #
    # The entry condition is what rules out the alternative. A long trail with
    # a *worse* minimum speed is a driver still slowing down because they
    # arrived too fast, not one over-trailing, and telling them to release
    # earlier would point them away from the corner they actually entered too
    # quickly.
    if (
        trail is not None
        and trail > ADVICE_TRAIL_M
        and minimum > -ADVICE_SPEED_KMH
        and exit_speed < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Come off the brake earlier here",
            "You matched the reference into the corner but carried the brake "
            "further through it, and the time went on the way out.",
            amounts(
                f"trail length {trail:+.0f} m",
                f"exit speed {exit_speed:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    # Late on the power, with the entry matched: the loss is on the way out.
    #
    # The test is "minimum speed was not worse", not "the exit speed was
    # slower". Exit speed is read at one sample - the corner's last - so a lap
    # that was slower for the whole exit and had caught up by that one point
    # would go unmentioned. Matching the entry is what rules out the
    # alternative explanation, and the corner's own cost is the evidence that
    # something was lost.
    if (
        throttle is not None
        and throttle > ADVICE_POINT_M
        and minimum > -ADVICE_SPEED_KMH
    ):
        parts = [f"throttle point {throttle:+.0f} m"]
        if exit_speed < -ADVICE_SPEED_KMH:
            parts.append(f"exit speed {exit_speed:+.1f} km/h")
        parts.append(f"cost {comparison.lost_s:.3f} s")
        return Advice(
            comparison.corner,
            "Get on the power earlier",
            "You matched the reference through the corner but picked the "
            "throttle up later, and the time went on the way out.",
            amounts(*parts),
            comparison.lost_s,
        )

    # The pedal went down in the right place, but the pressure arrived late -
    # so the stop happened deeper than it should have and the middle of the
    # corner paid for it. A single brake point cannot see this at all: both
    # laps braked in the same metre. This is the rule below with a cause, so
    # it is tried first and that rule catches what it leaves.
    if (
        brake is not None
        and abs(brake) <= ADVICE_POINT_M
        and peak is not None
        and peak > ADVICE_POINT_M
        and minimum < -ADVICE_SPEED_KMH
    ):
        return Advice(
            comparison.corner,
            "Get to full brake pressure sooner",
            "You went to the brake in the same place but took longer to reach "
            "peak pressure, so the car was still slowing where it should have "
            "been turning.",
            amounts(
                f"brake peak {peak:+.0f} m",
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    # Slower through the middle with nothing else to explain it.
    if minimum < -ADVICE_SPEED_KMH and (brake is None or abs(brake) <= ADVICE_POINT_M):
        return Advice(
            comparison.corner,
            "There is more corner speed here",
            "You braked in the same place but carried less speed through the "
            "middle.",
            amounts(
                f"minimum speed {minimum:+.1f} km/h",
                f"cost {comparison.lost_s:.3f} s",
            ),
            comparison.lost_s,
        )

    return None


#: Two corners whose reference brake points sit this close were braked for
#: once. Half a grid step apart is the same sample.
SAME_BRAKING_M = 2.0


def advice(comparisons, count: int = 4) -> "list[Advice]":
    """What to try, worst corner first.

    Fewer than *count* is the normal outcome and not a failure: a corner where
    the measurements do not agree on a story gets no advice, because the
    honest answer there is the numbers themselves.

    Consecutive corners of a complex share one braking event - Monza's Ascari
    is three corners and one stop - so the brake point found for each of them
    is the same event. Saying "brake later" twice about one brake application
    reads as two findings when there is one, so the second is dropped.
    """
    found: list[Advice] = []
    braking_cited: list[float] = []

    for comparison in sorted(comparisons, key=lambda c: -c.lost_s):
        item = _advise(comparison)
        if item is None:
            continue
        point = comparison.reference.brake_point_m
        # Every brake-shape rule reads that one application, so any of them
        # naming it is a finding about it - not only the two that happen to
        # print "brake point". Left as that one phrase, the pressure and trail
        # rules walked straight past this guard.
        about_braking = any(
            phrase in item.because
            for phrase in ("brake point", "brake peak", "trail length")
        )
        if about_braking and point is not None:
            if any(abs(point - cited) < SAME_BRAKING_M for cited in braking_cited):
                continue
            braking_cited.append(point)
        found.append(item)
        if len(found) == count:
            break
    return found
