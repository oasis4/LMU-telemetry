"""Track geometry: projection, distance resampling, curvature, closure.

Corners are a property of the track, so they are derived from where the track
goes - not from the steering trace, which depends on the driver and whose unit
differs between files.

LMU reports position as latitude/longitude around a synthetic origin rather
than the circuit's real coordinates, so these values are only meaningful as a
local shape. That is all this module needs them for.
"""

from __future__ import annotations

import numpy as np

#: Distance resolution of the reference model, in metres.
GRID_STEP_M = 2.0

_EARTH_RADIUS_M = 6378137.0


def project_enu(
    lat: np.ndarray,
    lon: np.ndarray,
    origin: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Project degrees onto local metres around *origin*, a ``(lat0, lon0)`` pair.

    With ``origin=None`` the projection is centred on the mean of the arrays
    handed in. That is safe only for a caller that looks at one array at a
    time, because everything derived from a single line here - curvature, the
    closure integral - is translation-invariant and therefore indifferent to
    where the frame sits.

    It is **not** safe for a caller that compares or combines several arrays:
    centring each one on its own mean puts every one of them in a different
    frame. Measured on the corpus, the per-lap means of Monza's 135 clean laps
    span 112.6 m in x and 165.0 m in y - on a track about 12 m wide. Such
    callers must choose one origin up front and pass it for every array.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    if origin is None:
        lat0, lon0 = float(np.mean(lat)), float(np.mean(lon))
    else:
        lat0, lon0 = float(origin[0]), float(origin[1])
    x = np.radians(lon - lon0) * _EARTH_RADIUS_M * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * _EARTH_RADIUS_M
    return x, y


def grid_for(track_length_m: float, step_m: float = GRID_STEP_M) -> np.ndarray:
    """The common distance grid every lap of a track is resampled onto."""
    if track_length_m <= 0:
        raise ValueError(f"track length must be positive, got {track_length_m}")
    if step_m <= 0:
        raise ValueError(f"step must be positive, got {step_m}")
    return np.arange(0.0, track_length_m, step_m)


def resample_to_grid(
    distance: np.ndarray,
    values: np.ndarray,
    track_length_m: float,
    step_m: float = GRID_STEP_M,
    tolerance_m: float = 0.0,
) -> np.ndarray:
    """Resample *values* from *distance* onto the track's common grid.

    Raises ``ValueError`` when *distance* does not reach both ends of that
    grid. This function interpolates with ``np.interp``, which extends the
    first and last value flat outside the input range rather than failing, so
    an under-spanning input silently comes back as a real-looking line with
    invented ends - and a lap's curvature and closure are then measured off
    that invention. The hazard belongs to this function, so the check does
    too; a caller that forgets it should not be the only thing standing
    between a short array and a fabricated result.

    *tolerance_m* is how far the input may fall short at either end, which is
    a policy the caller owns and this function should not guess. It defaults
    to zero - the strict reading - so a caller has to say so deliberately.
    ``quality.lap_line_on_grid`` passes the same allowance it admitted the lap
    under, because samples do not land exactly on the grid's ends: measured
    over the corpus, 90 of Monza's 135 clean laps begin after d=0 (by up to
    5.4 m) and 122 end before the last grid point (by up to 8.8 m).
    """
    distance = np.asarray(distance, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if len(distance) != len(values):
        raise ValueError(
            f"distance and values differ in length: {len(distance)} vs {len(values)}"
        )
    if len(distance) < 2:
        raise ValueError("need at least two samples to resample")
    if np.any(np.diff(distance) < 0):
        raise ValueError("distance must be non-decreasing")
    grid = grid_for(track_length_m, step_m)
    if distance[0] > grid[0] + tolerance_m or distance[-1] < grid[-1] - tolerance_m:
        raise ValueError(
            f"samples span {distance[0]:.1f}-{distance[-1]:.1f} m, which does "
            f"not cover the grid {grid[0]:.1f}-{grid[-1]:.1f} m within "
            f"{tolerance_m:.1f} m; interpolating would invent the ends"
        )
    return np.interp(grid, distance, values)


#: Smoothing window for the racing line, in grid samples (15 x 2 m = 30 m).
LINE_SMOOTH_WINDOW = 15
#: Smoothing window applied to the curvature itself.
CURVATURE_SMOOTH_WINDOW = 8


def smooth_closed(values: np.ndarray, window: int) -> np.ndarray:
    """Moving average that wraps around, because a lap is a closed loop.

    Smoothing without wrap-around would leave an artefact at the start/finish
    line, which is an arbitrary point on the track and not a feature of it.
    """
    values = np.asarray(values, dtype=np.float64)
    if window <= 1:
        return values.copy()
    if window >= len(values):
        raise ValueError(f"window {window} exceeds series length {len(values)}")
    kernel = np.ones(window) / window
    padded = np.concatenate([values[-window:], values, values[:window]])
    return np.convolve(padded, kernel, mode="same")[window:-window]


def _turn_and_arc(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Heading change at each sample, and the arc length belonging to it.

    Segment *i* leaves sample *i* and the last one wraps back to sample 0, so
    the segments form a closed polygon: their heading increments sum to a whole
    number of turns, and their lengths sum to the line's perimeter.
    """
    xs = smooth_closed(np.asarray(x, dtype=np.float64), LINE_SMOOTH_WINDOW)
    ys = smooth_closed(np.asarray(y, dtype=np.float64), LINE_SMOOTH_WINDOW)
    dx = np.diff(xs, append=xs[0])
    dy = np.diff(ys, append=ys[0])
    theta = np.arctan2(dy, dx)
    turn = (theta - np.roll(theta, 1) + np.pi) % (2 * np.pi) - np.pi
    segment = np.hypot(dx, dy)
    # Half the segment arriving at a sample plus half the one leaving it.
    return turn, 0.5 * (np.roll(segment, 1) + segment)


def turn_rad(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Signed heading change at each sample, in radians. Left turns positive.

    This is the module's primitive: everything angular is derived from it, so
    curvature and heading can never disagree about how far the line turned.

    Taking the heading from the tangent rather than from a second derivative
    matters. The obvious alternative - evaluate the curvature formula and
    integrate it over the distance grid - measures the curvature *of the
    smoothed line* but weights it by *unsmoothed* track distance. Smoothing
    cuts corners, so the smoothed line is shorter than the grid exactly where
    the track turns, and the integral is inflated exactly there. Measured over
    the corpus, a whole lap came out at 360.6 deg on Monza but 436.8 deg on
    COTA National, whose corners are far tighter - an error that scales with
    how much the track turns and so is invisible on any one circuit.

    The sum of this array over a whole lap is 2*pi times the winding number,
    exactly, on every circuit and at every smoothing window.
    """
    return _turn_and_arc(x, y)[0]


def curvature(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Signed curvature in 1/m. Positive turns left, negative turns right.

    Curvature is heading change per unit of arc length, so it is derived from
    :func:`turn_rad` and the arc length of the same smoothed line. Deriving
    both from one primitive is what makes ``sum(turn) == sum(kappa * ds)``
    hold rather than merely hold approximately.

    The line is smoothed first: GPS jitter differentiates into large spurious
    curvature.
    """
    turn, ds = _turn_and_arc(x, y)
    kappa = np.where(ds > 1e-9, turn / np.maximum(ds, 1e-9), 0.0)
    return smooth_closed(kappa, CURVATURE_SMOOTH_WINDOW)


def heading_change_deg(turn: np.ndarray) -> float:
    """How far the heading turned over these samples, in degrees, unsigned.

    Over a whole lap this is the closure check: a lap that goes round the
    circuit once must come out at 360 degrees. Because the samples form a
    closed polygon the result is then an exact multiple of 360, so the check
    reads the lap's *shape* - see :func:`winding_number`.
    """
    return float(np.degrees(abs(np.sum(np.asarray(turn, dtype=np.float64)))))


def winding_number(turn: np.ndarray) -> float:
    """How many times the line goes round, from the same primitive.

    Exactly 1.0 (or -1.0, running clockwise) for a lap that goes round the
    circuit once. Measured over the corpus this held for 1097 of 1098 laps;
    the one exception was a lap with a 74 m jump in its recorded position.
    """
    return float(np.degrees(np.sum(np.asarray(turn, dtype=np.float64))) / 360.0)
