"""Which laps may define the track's geometry.

The spec keeps two properties apart that the old implementation mixed:

* **complete** - bounded by two `Lap` events. That is `segment_laps`' contract.
* **clean** - additionally suitable for measuring the track itself.

Only clean laps build the reference model. Every lap is still shown; an
unclean one carries the reason it was excluded, because a lap dropped without
a stated reason is indistinguishable from a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry
from .laps import Lap
from .session import Session

#: A lap that goes round the circuit once has winding number 1. Because the
#: samples form a closed polygon this quantity is an exact multiple of 1, so
#: the tolerance only absorbs floating-point error - it is not a band that
#: real laps scatter across.
WINDING_TOLERANCE = 0.02

#: Largest planar move allowed between two adjacent grid samples, in metres.
#: The grid advances 2 m of track distance per step, so the position should
#: advance about 2 m too; a recording gap or a teleport shows up here.
#:
#: This is a policy, not a measured constant. Over the corpus the largest
#: interior step per lap runs continuously from 2 m to 74 m with no gap to cut
#: at: median 2.45 m, p90 3.61 m, p99 30.2 m. Five grid steps sits well above
#: the ordinary range and rejects 3.5 % of otherwise-admissible laps.
MAX_POSITION_STEP_M = 10.0

#: Covered distance must be within this fraction of the track length.
DISTANCE_TOLERANCE = 0.02

#: How far our derived duration may differ from the lap time the game itself
#: recorded, in seconds.
#:
#: The two are measured independently - ours from the ``Lap`` event timestamps,
#: the game's from its own timing - so agreement is evidence that the lap
#: boundaries are right. Across the corpus 913 of 995 laps agree to within
#: 17 ms, and the laps that disagree miss by more than a second, up to 8.5 s.
#: Exactly two laps fall in between, so this threshold sits in a real gap
#: rather than cutting through a population.
LAP_TIME_TOLERANCE_S = 0.1


@dataclass(frozen=True)
class LapQuality:
    is_clean: bool
    reason: str | None
    closure_deg: float | None
    max_step_m: float | None = None


def _rejected(
    reason: str, closure: float | None = None, max_step: float | None = None
) -> LapQuality:
    return LapQuality(
        is_clean=False, reason=reason, closure_deg=closure, max_step_m=max_step
    )


def coverage_reason(d_sorted: np.ndarray, track_length_m: float) -> str | None:
    """Why these distance samples cannot represent a full lap, or None.

    Resampling onto the track grid uses np.interp, which flat-extrapolates
    silently outside the sample range rather than failing. So the samples must
    actually reach both ends of the grid they will be resampled onto - and that
    grid is not always built from the same track length the lap was admitted
    against, because a multi-session model resamples onto the median length.
    """
    if len(d_sorted) < 50:
        return f"only {len(d_sorted)} distinct distance samples"
    span_tolerance = track_length_m * DISTANCE_TOLERANCE
    if d_sorted[0] > span_tolerance or d_sorted[-1] < track_length_m - span_tolerance:
        return (
            f"position samples span {d_sorted[0]:.0f}-{d_sorted[-1]:.0f} m, "
            f"which does not cover the {track_length_m:.0f} m track"
        )
    return None


def lap_line_on_grid(
    session: Session,
    lap: Lap,
    track_length_m: float,
    origin: "tuple[float, float] | None" = None,
) -> "tuple[tuple[np.ndarray, np.ndarray] | None, str | None]":
    """One lap's position resampled onto the track's common distance grid.

    Returns ``(line, None)`` or ``(None, reason)``. This is the single
    project/sort/dedupe/resample pipeline: :func:`assess_lap` runs it to judge
    a lap, and ``track_model`` runs it again to collect the lap's line, and
    the two must agree sample for sample or a lap could be admitted on one
    geometry and measured on another.

    *origin* is handed straight to :func:`geometry.project_enu`. A caller that
    combines several laps must supply one, or every lap lands in its own frame.
    """
    lat = session.lap_channel(lap, "GPS Latitude")
    lon = session.lap_channel(lap, "GPS Longitude")
    dist = session.lap_channel(lap, "Lap Dist")
    n = min(len(lat), len(lon), len(dist))
    if n < 100:
        return None, f"only {n} position samples"

    x, y = geometry.project_enu(lat[:n], lon[:n], origin)
    order = np.argsort(dist[:n])
    d_sorted = dist[:n][order]
    keep = np.concatenate(([True], np.diff(d_sorted) > 1e-6))
    d_sorted = d_sorted[keep]

    reason = coverage_reason(d_sorted, track_length_m)
    if reason is not None:
        return None, reason

    # coverage_reason has just established that these samples reach both ends
    # of the grid to within DISTANCE_TOLERANCE. That same allowance is handed
    # to resample_to_grid rather than left for it to infer, so the guard there
    # rejects exactly what was not admitted here and nothing more.
    tolerance_m = track_length_m * DISTANCE_TOLERANCE
    return (
        geometry.resample_to_grid(
            d_sorted, x[order][keep], track_length_m, tolerance_m=tolerance_m
        ),
        geometry.resample_to_grid(
            d_sorted, y[order][keep], track_length_m, tolerance_m=tolerance_m
        ),
    ), None


def assess_lap(session: Session, lap: Lap) -> LapQuality:
    """Judge whether *lap* may contribute to the track's reference geometry.

    Two distance checks run for different reasons. The ``distance_m`` ratio
    checks total forward travel across the lap - but that is a sum over all
    positive ``Lap Dist`` steps, so it is invariant to *where* in
    distance-space those steps sit. A lap that resets mid-way (for example a
    formation lap fused with the first racing lap by a missed ``Lap`` event)
    can sum to the right total while its raw samples still only span part of
    the track's distance range. The span check below catches that case
    directly, on the actual samples that get resampled onto the grid -
    because ``resample_to_grid`` uses ``np.interp``, which silently
    flat-extrapolates outside the input range rather than failing, so an
    under-spanning array would otherwise distort the curvature and closure
    figures without any error.
    """
    if lap.touched_pits:
        return _rejected("the lap touched the pit lane")
    if lap.number == 0:
        return _rejected(
            "lap 0 runs from the start of recording to the first timed crossing"
        )

    # The game's own verdict comes first: it is exact, it costs nothing to
    # read, and no amount of geometry can overrule a lap the game itself
    # refused to time.
    if lap.recorded_time_s == 0.0:
        return _rejected("the game recorded no lap time for this lap")
    if lap.recorded_time_s is not None:
        drift = abs(lap.duration_s - lap.recorded_time_s)
        if drift > LAP_TIME_TOLERANCE_S:
            return _rejected(
                f"our duration {lap.duration_s:.3f} s disagrees with the "
                f"{lap.recorded_time_s:.3f} s the game recorded, by "
                f"{drift:.3f} s - the lap boundaries in this file are unreliable"
            )

    track_length = session.track_length_m
    if track_length is None:
        return _rejected("the session has no established track length")
    if track_length <= 0:
        return _rejected(f"track length is degenerate ({track_length:.0f} m)")

    ratio = lap.distance_m / track_length
    if abs(ratio - 1.0) > DISTANCE_TOLERANCE:
        return _rejected(
            f"covered {ratio:.2f} track lengths, expected 1.00 "
            f"+-{DISTANCE_TOLERANCE:.2f}"
        )

    # No origin: one lap is judged entirely on its own, and every quantity
    # measured below is translation-invariant, so this lap's own mean is as
    # good a frame as any. Callers that combine laps must pass an origin.
    line, reason = lap_line_on_grid(session, lap, track_length)
    if line is None:
        return _rejected(reason)
    xs, ys = line

    # The wrap segment is excluded: the last grid point and the first belong to
    # two different passes over the start/finish line, so the gap between them
    # is the driver taking a different line, not a break in the recording.
    max_step = float(np.hypot(np.diff(xs), np.diff(ys)).max())

    turn = geometry.turn_rad(xs, ys)
    closure = geometry.heading_change_deg(turn)
    winding = geometry.winding_number(turn)

    if abs(abs(winding) - 1.0) > WINDING_TOLERANCE:
        return _rejected(
            f"the lap winds {winding:.2f} times round the circuit, not once",
            closure,
            max_step,
        )
    if max_step > MAX_POSITION_STEP_M:
        return _rejected(
            f"position jumps {max_step:.0f} m between samples 2 m apart, "
            f"more than the {MAX_POSITION_STEP_M:.0f} m allowed",
            closure,
            max_step,
        )
    return LapQuality(
        is_clean=True, reason=None, closure_deg=closure, max_step_m=max_step
    )


def clean_laps(session: Session) -> list[Lap]:
    """Every lap of *session* that may define the track's geometry."""
    return [l for l in session.laps if assess_lap(session, l).is_clean]
