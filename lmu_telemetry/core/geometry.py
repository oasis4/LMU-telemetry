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


def project_enu(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Project degrees onto local metres, centred on the mean position."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    lat0 = float(np.mean(lat))
    x = np.radians(lon - float(np.mean(lon))) * _EARTH_RADIUS_M * np.cos(np.radians(lat0))
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
) -> np.ndarray:
    """Resample *values* from *distance* onto the track's common grid."""
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
    return np.interp(grid_for(track_length_m, step_m), distance, values)


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
