"""Lap detection, distance-based resampling, and sector extraction.

Works on top of :class:`duckdb_reader.DuckDBSession` to produce per-lap
telemetry arrays at a uniform distance resolution (default 1 m).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import interpolate

from .duckdb_reader import DuckDBSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STEP_CHANNELS = {"gear", "lap", "lap_beacon", "abs_active", "tc_active", "sector"}


def _interp(x_old: np.ndarray, y_old: np.ndarray, x_new: np.ndarray,
            step: bool = False) -> np.ndarray:
    """Resample *y_old* from *x_old* onto *x_new*.

    Uses linear interpolation for continuous channels and nearest-previous
    (zero-order hold) for step channels.
    """
    if step:
        idx = np.searchsorted(x_old, x_new, side="right") - 1
        idx = np.clip(idx, 0, len(y_old) - 1)
        return y_old[idx]
    return np.interp(x_new, x_old, y_old)


# ---------------------------------------------------------------------------
# Lap data container
# ---------------------------------------------------------------------------

@dataclass
class LapData:
    lap_number: int = 0
    lap_time_ms: float = 0.0
    valid: bool = True
    sectors: list[float] = field(default_factory=list)  # ms per sector

    # distance-sampled arrays
    distance: np.ndarray = field(default_factory=lambda: np.array([]))
    speed: np.ndarray = field(default_factory=lambda: np.array([]))
    throttle: np.ndarray = field(default_factory=lambda: np.array([]))
    brake: np.ndarray = field(default_factory=lambda: np.array([]))
    steering: np.ndarray = field(default_factory=lambda: np.array([]))
    gear: np.ndarray = field(default_factory=lambda: np.array([]))
    rpm: np.ndarray = field(default_factory=lambda: np.array([]))
    lat: np.ndarray = field(default_factory=lambda: np.array([]))
    lon: np.ndarray = field(default_factory=lambda: np.array([]))
    time: np.ndarray = field(default_factory=lambda: np.array([]))


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------

class LapProcessor:
    """Detects laps and produces uniformly-distance-sampled telemetry."""

    def __init__(self, session: DuckDBSession, resolution_m: float = 1.0) -> None:
        self.session = session
        self.resolution = resolution_m
        self._laps: list[LapData] | None = None

    # -- lap boundary detection ---------------------------------------------

    @staticmethod
    def _detect_boundaries(lap_arr: np.ndarray | None,
                           norm_arr: np.ndarray | None,
                           dist_arr: np.ndarray | None,
                           n_samples: int) -> list[tuple[int, int]]:
        """Return ``[(start_idx, end_idx), …]`` for each lap.

        Priority:
        1. Explicit ``lap`` channel (value changes → new lap).
        2. ``normalized_lap`` wraps from ~1 back to ~0.
        3. ``lap_distance`` resets to near-zero.
        4. Single-lap fallback – entire trace.
        """
        if lap_arr is not None and len(lap_arr) == n_samples:
            laps_i: list[tuple[int, int]] = []
            current_start = 0
            current_val = lap_arr[0]
            for i in range(1, n_samples):
                if lap_arr[i] != current_val:
                    laps_i.append((current_start, i - 1))
                    current_start = i
                    current_val = lap_arr[i]
            laps_i.append((current_start, n_samples - 1))
            return laps_i

        if norm_arr is not None and len(norm_arr) == n_samples:
            laps_i = []
            current_start = 0
            for i in range(1, n_samples):
                if norm_arr[i] < norm_arr[i - 1] - 0.5:
                    laps_i.append((current_start, i - 1))
                    current_start = i
            laps_i.append((current_start, n_samples - 1))
            return laps_i

        if dist_arr is not None and len(dist_arr) == n_samples:
            laps_i = []
            current_start = 0
            for i in range(1, n_samples):
                if dist_arr[i] < dist_arr[i - 1] - 50:
                    laps_i.append((current_start, i - 1))
                    current_start = i
            laps_i.append((current_start, n_samples - 1))
            return laps_i

        return [(0, n_samples - 1)]

    # -- distance axis computation ------------------------------------------

    @staticmethod
    def _compute_distance(speed_kmh: np.ndarray, dt: float) -> np.ndarray:
        """Integrate speed (km/h) to cumulative distance (m)."""
        speed_ms = speed_kmh / 3.6
        dist = np.cumsum(speed_ms * dt)
        dist = np.insert(dist[:-1], 0, 0.0)
        return dist

    # -- main processing ----------------------------------------------------

    def process(self) -> list[LapData]:
        """Parse all laps and resample to uniform distance grid."""
        if self._laps is not None:
            return self._laps

        sess = self.session

        # Fetch raw channels ---------------------------------------------------
        speed_raw = sess.get_channel("speed")
        throttle_raw = sess.get_channel("throttle")
        brake_raw = sess.get_channel("brake")
        steering_raw = sess.get_channel("steering")
        gear_raw = sess.get_channel("gear")
        rpm_raw = sess.get_channel("rpm")
        lap_raw = sess.get_channel("lap")
        norm_raw = sess.get_channel("normalized_lap")
        dist_raw = sess.get_channel("lap_distance")
        lat_raw = sess.get_channel("lat") or sess.get_channel("pos_x")
        lon_raw = sess.get_channel("lon") or sess.get_channel("pos_y")
        sector_raw = sess.get_channel("sector")

        # Determine dominant sample count (largest available array)
        counts = [
            len(a) for a in [speed_raw, throttle_raw, brake_raw, steering_raw,
                              gear_raw, rpm_raw]
            if a is not None
        ]
        if not counts:
            self._laps = []
            return self._laps
        n_samples = max(counts)

        # Pad / trim helper
        def _fix(arr: np.ndarray | None, fill: float = 0.0) -> np.ndarray:
            if arr is None:
                return np.full(n_samples, fill)
            if len(arr) >= n_samples:
                return arr[:n_samples]
            return np.pad(arr, (0, n_samples - len(arr)),
                          constant_values=fill)

        speed = _fix(speed_raw)
        throttle = _fix(throttle_raw)
        brake = _fix(brake_raw)
        steering = _fix(steering_raw)
        gear = _fix(gear_raw)
        rpm = _fix(rpm_raw)
        lat = _fix(lat_raw)
        lon = _fix(lon_raw)

        # Estimate dt from session duration
        dur = sess.session_duration_s()
        dt = dur / n_samples if n_samples > 0 else 0.01

        # Time axis
        time_axis = np.arange(n_samples) * dt

        # Distance axis (from speed integration or raw lap_distance)
        if dist_raw is not None and len(dist_raw) == n_samples:
            full_dist = dist_raw.copy()
        else:
            full_dist = self._compute_distance(speed, dt)

        # Lap boundaries
        boundaries = self._detect_boundaries(
            _fix(lap_raw) if lap_raw is not None else None,
            _fix(norm_raw) if norm_raw is not None else None,
            _fix(dist_raw) if dist_raw is not None else None,
            n_samples,
        )

        laps: list[LapData] = []
        for lap_idx, (si, ei) in enumerate(boundaries, start=1):
            if ei - si < 10:
                continue  # skip trivially short laps

            sl = slice(si, ei + 1)
            lap_speed = speed[sl]
            lap_time_arr = time_axis[sl]
            lap_dist = full_dist[sl]

            # Make distance monotonically increasing within the lap
            if dist_raw is not None:
                lap_dist = lap_dist - lap_dist[0]
            else:
                lap_dist = self._compute_distance(lap_speed, dt)

            total_dist = lap_dist[-1] if len(lap_dist) > 0 else 0.0
            if total_dist < 10:
                continue

            # Uniform distance grid
            d_new = np.arange(0, total_dist, self.resolution)
            if len(d_new) == 0:
                continue

            # Ensure monotonicity for interpolation
            mono_mask = np.concatenate(([True], np.diff(lap_dist) > 0))
            lap_dist_mono = lap_dist[mono_mask]

            def _resample(arr: np.ndarray, step: bool = False) -> np.ndarray:
                arr_mono = arr[sl][mono_mask] if len(arr[sl]) == len(mono_mask) else arr[sl]
                if len(arr_mono) != len(lap_dist_mono):
                    arr_mono = arr_mono[: len(lap_dist_mono)]
                return _interp(lap_dist_mono, arr_mono, d_new, step=step)

            lap_data = LapData(
                lap_number=lap_idx,
                lap_time_ms=float((lap_time_arr[-1] - lap_time_arr[0]) * 1000),
                valid=True,
                distance=d_new,
                speed=_resample(speed),
                throttle=_resample(throttle),
                brake=_resample(brake),
                steering=_resample(steering),
                gear=_resample(gear, step=True),
                rpm=_resample(rpm),
                lat=_resample(lat),
                lon=_resample(lon),
                time=_interp(lap_dist_mono,
                             lap_time_arr[mono_mask] - lap_time_arr[mono_mask][0]
                             if len(lap_time_arr[mono_mask]) == len(lap_dist_mono)
                             else lap_time_arr[:len(lap_dist_mono)] - lap_time_arr[0],
                             d_new),
            )

            # Sector estimation (divide lap into 3 equal-distance parts)
            if sector_raw is not None:
                # TODO: use actual sector markers if present
                pass
            third = total_dist / 3.0
            s1_end = np.searchsorted(d_new, third)
            s2_end = np.searchsorted(d_new, 2 * third)
            t = lap_data.time
            if len(t) > 0:
                s1_ms = float(t[min(s1_end, len(t) - 1)] * 1000)
                s2_ms = float(t[min(s2_end, len(t) - 1)] * 1000) - s1_ms
                s3_ms = lap_data.lap_time_ms - s1_ms - s2_ms
                lap_data.sectors = [s1_ms, s2_ms, s3_ms]

            laps.append(lap_data)

        self._laps = laps
        return laps
