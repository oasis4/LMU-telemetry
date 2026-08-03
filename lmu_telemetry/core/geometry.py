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
