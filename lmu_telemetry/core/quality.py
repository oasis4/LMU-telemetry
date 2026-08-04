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

#: A closed lap integrates to 360 degrees of heading change. Real laps scatter
#: around that; outside this band the lap is geometrically broken.
CLOSURE_MIN_DEG = 330.0
CLOSURE_MAX_DEG = 390.0

#: Covered distance must be within this fraction of the track length.
DISTANCE_TOLERANCE = 0.02


@dataclass(frozen=True)
class LapQuality:
    is_clean: bool
    reason: str | None
    closure_deg: float | None


def _rejected(reason: str, closure: float | None = None) -> LapQuality:
    return LapQuality(is_clean=False, reason=reason, closure_deg=closure)


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

    lat = session.lap_channel(lap, "GPS Latitude")
    lon = session.lap_channel(lap, "GPS Longitude")
    dist = session.lap_channel(lap, "Lap Dist")
    n = min(len(lat), len(lon), len(dist))
    if n < 100:
        return _rejected(f"only {n} position samples")

    x, y = geometry.project_enu(lat[:n], lon[:n])
    order = np.argsort(dist[:n])
    d_sorted = dist[:n][order]
    keep = np.concatenate(([True], np.diff(d_sorted) > 1e-6))
    d_sorted = d_sorted[keep]
    reason = coverage_reason(d_sorted, track_length)
    if reason is not None:
        return _rejected(reason)

    xs = geometry.resample_to_grid(d_sorted, x[order][keep], track_length)
    ys = geometry.resample_to_grid(d_sorted, y[order][keep], track_length)
    grid = geometry.grid_for(track_length)
    closure = geometry.heading_change_deg(geometry.curvature(xs, ys), grid)

    if not (CLOSURE_MIN_DEG <= closure <= CLOSURE_MAX_DEG):
        return _rejected(
            f"lap closure {closure:.0f} deg is outside "
            f"{CLOSURE_MIN_DEG:.0f}-{CLOSURE_MAX_DEG:.0f}",
            closure,
        )
    return LapQuality(is_clean=True, reason=None, closure_deg=closure)


def clean_laps(session: Session) -> list[Lap]:
    """Every lap of *session* that may define the track's geometry."""
    return [l for l in session.laps if assess_lap(session, l).is_clean]
