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


def curvature(
    x: np.ndarray, y: np.ndarray, step_m: float = GRID_STEP_M
) -> np.ndarray:
    """Signed curvature in 1/m. Positive turns left, negative turns right.

    kappa = (x' y'' - y' x'') / (x'^2 + y'^2)^(3/2)

    The line is smoothed first: GPS jitter differentiates into large spurious
    curvature, and curvature needs two derivatives.
    """
    xs = smooth_closed(np.asarray(x, dtype=np.float64), LINE_SMOOTH_WINDOW)
    ys = smooth_closed(np.asarray(y, dtype=np.float64), LINE_SMOOTH_WINDOW)
    dx, dy = np.gradient(xs, step_m), np.gradient(ys, step_m)
    ddx, ddy = np.gradient(dx, step_m), np.gradient(dy, step_m)
    denominator = (dx**2 + dy**2) ** 1.5
    kappa = np.where(
        denominator > 1e-9,
        (dx * ddy - dy * ddx) / np.maximum(denominator, 1e-9),
        0.0,
    )
    return smooth_closed(kappa, CURVATURE_SMOOTH_WINDOW)


def heading_change_deg(kappa: np.ndarray, grid: np.ndarray) -> float:
    """Total change of heading over *grid*, in degrees.

    Integrated over a whole lap this is the closure check: a lap that goes
    round the circuit once and returns to its own start must come out near
    360 degrees. A lap that does not is geometrically broken.
    """
    if len(kappa) != len(grid):
        raise ValueError(f"kappa and grid differ in length: {len(kappa)} vs {len(grid)}")
    return float(np.degrees(abs(np.trapz(kappa, grid))))
