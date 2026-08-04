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

    found.sort(key=lambda entry: -entry[0])
    return tuple(difference for _weight, difference in found)


def compare_corners(
    reference: LapTrace, other: LapTrace, corners
) -> list[CornerComparison]:
    """Compare two laps corner by corner, against one corner list.

    Both traces must be on the same grid; :func:`delta.delta_s` refuses them
    otherwise, because two grids mean two different tracks.
    """
    delta = delta_s(reference, other)
    out = []
    for corner in corners:
        reference_metrics = corner_metrics(reference, corner)
        other_metrics = corner_metrics(other, corner)
        out.append(
            CornerComparison(
                corner=corner,
                lost_s=time_lost_over(delta, reference.grid, corner),
                reference=reference_metrics,
                other=other_metrics,
                differences=_differences(reference_metrics, other_metrics),
            )
        )
    return out


def biggest_losses(comparisons, count: int = 3) -> list[CornerComparison]:
    """The corners that cost the most time, worst first."""
    return sorted(comparisons, key=lambda c: -c.lost_s)[:count]
