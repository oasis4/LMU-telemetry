"""Lap detection, distance-based resampling, and sector extraction.

Uses ``Lap Dist`` resets for reliable lap-boundary detection, reads real
sector / lap times from DuckDB event tables, converts GPS Speed from m/s
to km/h, and handles the multi-rate channel layout (10 / 50 / 100 Hz).
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
    sectors_matched: bool = False  # True if sectors came from real events

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

    # -- lap boundary detection from distance resets ------------------------

    @staticmethod
    def _detect_boundaries_from_dist(
        dist_arr: np.ndarray, threshold_m: float = 50.0,
    ) -> list[tuple[int, int]]:
        """Return ``[(start_idx, end_idx), …]`` for each segment between
        Lap Dist resets (distance drops by more than *threshold_m*)."""
        boundaries: list[tuple[int, int]] = []
        current_start = 0
        for i in range(1, len(dist_arr)):
            if dist_arr[i] < dist_arr[i - 1] - threshold_m:
                boundaries.append((current_start, i - 1))
                current_start = i
        boundaries.append((current_start, len(dist_arr) - 1))
        return boundaries

    # -- resampling helpers -------------------------------------------------

    @staticmethod
    def _resample_to_base(
        arr: np.ndarray, n_base: int, dt_base: float, source_rate_hz: float,
    ) -> np.ndarray:
        """Resample a higher-rate channel to the base (10 Hz) rate."""
        if len(arr) == n_base:
            return arr
        dt_src = 1.0 / source_rate_hz if source_rate_hz > 0 else dt_base
        t_src = np.arange(len(arr)) * dt_src
        t_base = np.arange(n_base) * dt_base
        return np.interp(t_base, t_src, arr)

    # -- main processing ----------------------------------------------------

    def process(self) -> list[LapData]:
        """Parse all laps and resample to uniform distance grid."""
        if self._laps is not None:
            return self._laps

        sess = self.session

        # --- 10 Hz spatial channels (base rate) ----------------------------
        n_base, dt_base = sess.get_base_rate_info()

        dist_raw = sess.get_channel("lap_distance")
        speed_ms = sess.get_channel("speed")          # m/s (GPS Speed)
        lat_raw = sess.get_channel("lat")
        lon_raw = sess.get_channel("lon")

        if dist_raw is None or speed_ms is None:
            self._laps = []
            return self._laps

        # Convert speed from m/s → km/h
        speed_kmh = speed_ms * 3.6

        # Clamp to the shorter array
        n = min(len(dist_raw), len(speed_kmh), n_base)
        dist_raw = dist_raw[:n]
        speed_kmh = speed_kmh[:n]

        # --- Absolute time axis from GPS Time (100 Hz → 10 Hz) ------------
        # Event timestamps (ts) are in GPS Time, so the time axis must
        # also be in GPS Time for correct matching.
        gps_time_raw = sess.get_channel("gps_time")
        if gps_time_raw is not None and len(gps_time_raw) > 1:
            # Interpolate 100 Hz → n points (10 Hz) spanning the full session
            idx_src = np.arange(len(gps_time_raw))
            idx_dst = np.linspace(0, len(gps_time_raw) - 1, n)
            time_axis = np.interp(idx_dst, idx_src, gps_time_raw)
        else:
            # Fallback: synthetic time axis (event matching may be imprecise)
            time_axis = np.arange(n) * dt_base

        # --- higher-rate channels → resample to 10 Hz ---------------------
        def _read_resample(channel: str, fallback_hz: float = 0) -> np.ndarray:
            arr = sess.get_channel(channel)
            if arr is None:
                return np.zeros(n)
            if len(arr) == n:
                return arr[:n]
            hz = fallback_hz
            if hz <= 0 and n > 0:
                hz = len(arr) / (n * dt_base)
            return self._resample_to_base(arr, n, dt_base, hz)[:n]

        throttle = _read_resample("throttle", 50)
        brake = _read_resample("brake", 50)
        steering = _read_resample("steering", 100)
        rpm = _read_resample("rpm", 100)

        lat = lat_raw[:n] if lat_raw is not None and len(lat_raw) >= n else np.zeros(n)
        lon = lon_raw[:n] if lon_raw is not None and len(lon_raw) >= n else np.zeros(n)

        # --- event channels → forward-fill to 10 Hz time axis -------------
        gear_evt = sess.get_events("gear")
        gear = (
            DuckDBSession.expand_events(gear_evt[0], gear_evt[1], time_axis)
            if gear_evt is not None
            else np.zeros(n)
        )

        # --- sector / lap time events (real data) --------------------------
        sector1_evt = sess.get_events("sector1_time")
        sector2_evt = sess.get_events("sector2_time")
        laptime_evt = sess.get_events("lap_time")
        lap_evt = sess.get_events("lap")

        # --- detect lap boundaries from Lap Dist resets --------------------
        boundaries = self._detect_boundaries_from_dist(dist_raw)

        # Build continuous lap-number array from Lap events (forward-fill)
        if lap_evt is not None:
            lap_num_arr = DuckDBSession.expand_events(
                lap_evt[0], lap_evt[1], time_axis, fill=0.0,
            )
        else:
            lap_num_arr = np.zeros(n)

        # Merge consecutive segments that belong to the same lap.
        # Spurious mid-lap distance resets can split one lap into multiple
        # short segments.  Merging recovers the full lap data.
        merged_boundaries: list[tuple[int, int, int]] = []  # (si, ei, lap_num)
        for si, ei in boundaries:
            if ei - si < 2:
                continue
            mid_idx = (si + ei) // 2
            lap_n = int(lap_num_arr[mid_idx])
            if lap_n <= 0:
                lap_n = len(merged_boundaries) + 1
            if merged_boundaries and merged_boundaries[-1][2] == lap_n:
                # Same lap number as previous segment → merge
                prev_si, _, _ = merged_boundaries[-1]
                merged_boundaries[-1] = (prev_si, ei, lap_n)
            else:
                merged_boundaries.append((si, ei, lap_n))

        # Determine the typical full-lap distance (longest merged segment)
        seg_dists = []
        for si, ei, _ in merged_boundaries:
            d_seg = dist_raw[si:ei + 1]
            # For merged segments, total distance = sum of sub-segment distances
            total = 0.0
            sub_start = si
            for i in range(si + 1, ei + 1):
                if dist_raw[i] < dist_raw[i - 1] - 50:
                    total += float(dist_raw[i - 1] - dist_raw[sub_start])
                    sub_start = i
            total += float(dist_raw[ei] - dist_raw[sub_start])
            seg_dists.append(total)
        max_seg_dist = max(seg_dists) if seg_dists else 0.0
        min_full_lap = max_seg_dist * 0.75 if max_seg_dist > 500 else 500.0

        # Build lap interval mapping: lap_number → (start_gps_time, end_gps_time)
        # Used for matching sector/lap-time events to the correct lap.
        lap_intervals: dict[int, tuple[float, float]] = {}
        if lap_evt is not None:
            ts_arr, val_arr = lap_evt
            for i in range(len(ts_arr)):
                lap_n = int(val_arr[i])
                t_start = float(ts_arr[i])
                t_end = float(ts_arr[i + 1]) if i + 1 < len(ts_arr) else float("inf")
                lap_intervals[lap_n] = (t_start, t_end)

        laps: list[LapData] = []

        for si, ei, lap_num in merged_boundaries:
            if ei - si < 10:
                continue

            sl = slice(si, ei + 1)

            # Build concatenated distance for merged segments
            # (handle mid-segment resets by accumulating sub-segment distances)
            raw_dist_sl = dist_raw[sl]
            lap_dist = np.empty(len(raw_dist_sl))
            cum = 0.0
            sub_start = 0
            for i in range(1, len(raw_dist_sl)):
                if raw_dist_sl[i] < raw_dist_sl[i - 1] - 50:
                    for j in range(sub_start, i):
                        lap_dist[j] = cum + float(raw_dist_sl[j] - raw_dist_sl[sub_start])
                    cum += float(raw_dist_sl[i - 1] - raw_dist_sl[sub_start])
                    sub_start = i
            for j in range(sub_start, len(raw_dist_sl)):
                lap_dist[j] = cum + float(raw_dist_sl[j] - raw_dist_sl[sub_start])

            lap_speed = speed_kmh[sl]
            lap_time_arr = time_axis[sl]
            total_dist = float(lap_dist[-1]) if len(lap_dist) > 0 else 0.0

            # Skip segments shorter than a full lap
            if total_dist < min_full_lap:
                continue

            # --- real sector times matched by lap interval -----------------
            # LapTime fires at lap COMPLETION (≈ t_hi, the start of the next
            # lap), so match near the END of the interval.
            lap_time_ms: float = 0.0
            sectors_ms: list[float] = []

            matched_time = False
            matched_sectors = False
            if lap_num in lap_intervals:
                t_lo, t_hi = lap_intervals[lap_num]

                # LapTime fires at ≈ t_hi (completion of this lap)
                if laptime_evt is not None:
                    for lt_i in range(len(laptime_evt[0])):
                        evt_ts = laptime_evt[0][lt_i]
                        if abs(evt_ts - t_hi) < 10.0:
                            total_s = float(laptime_evt[1][lt_i])
                            if total_s > 0:
                                lap_time_ms = total_s * 1000
                                matched_time = True
                            break

                # Sector events fire DURING the lap (between t_lo and t_hi)
                if matched_time and sector1_evt is not None and sector2_evt is not None:
                    s1 = 0.0
                    s2_cumul = 0.0
                    for s1_i in range(len(sector1_evt[0])):
                        if t_lo + 1 < sector1_evt[0][s1_i] < t_hi + 5:
                            s1 = float(sector1_evt[1][s1_i])
                            break
                    for s2_i in range(len(sector2_evt[0])):
                        if t_lo + 1 < sector2_evt[0][s2_i] < t_hi + 5:
                            s2_cumul = float(sector2_evt[1][s2_i])
                            break
                    if s1 > 0 and s2_cumul > s1:
                        s2_delta = s2_cumul - s1
                        s3 = lap_time_ms / 1000 - s2_cumul
                        sectors_ms = [
                            s1 * 1000,
                            s2_delta * 1000,
                            s3 * 1000,
                        ]
                        matched_sectors = True

            # If still no match, compute from time axis
            if not matched_time:
                time_in_lap = lap_time_arr - lap_time_arr[0]
                lap_time_ms = float(time_in_lap[-1]) * 1000

            # --- uniform distance grid & resampling ------------------------
            d_new = np.arange(0, total_dist, self.resolution)
            if len(d_new) == 0:
                continue

            mono_mask = np.concatenate(([True], np.diff(lap_dist) > 0))
            lap_dist_mono = lap_dist[mono_mask]

            if len(lap_dist_mono) < 2:
                continue

            def _resample(arr: np.ndarray, step: bool = False) -> np.ndarray:
                a = arr[mono_mask] if len(arr) == len(mono_mask) else arr
                if len(a) != len(lap_dist_mono):
                    a = a[: len(lap_dist_mono)]
                return _interp(lap_dist_mono, a, d_new, step=step)

            time_in_lap = lap_time_arr - lap_time_arr[0]
            t_mono = (
                time_in_lap[mono_mask]
                if len(time_in_lap) == len(mono_mask)
                else time_in_lap[: len(lap_dist_mono)]
            )

            lap_data = LapData(
                lap_number=lap_num,
                lap_time_ms=lap_time_ms,
                valid=True,
                sectors=sectors_ms,
                sectors_matched=matched_sectors,
                distance=d_new,
                speed=_resample(lap_speed),
                throttle=_resample(throttle[sl]),
                brake=_resample(brake[sl]),
                steering=_resample(steering[sl]),
                gear=_resample(gear[sl], step=True),
                rpm=_resample(rpm[sl]),
                lat=_resample(lat[sl]),
                lon=_resample(lon[sl]),
                time=_interp(lap_dist_mono, t_mono, d_new),
            )

            # Fallback sectors from distance thirds if still missing
            if not lap_data.sectors and len(lap_data.time) > 0:
                third = total_dist / 3.0
                s1_end = min(int(np.searchsorted(d_new, third)), len(lap_data.time) - 1)
                s2_end = min(int(np.searchsorted(d_new, 2 * third)), len(lap_data.time) - 1)
                t = lap_data.time
                lap_data.sectors = [
                    float(t[s1_end]) * 1000,
                    float(t[s2_end] - t[s1_end]) * 1000,
                    lap_data.lap_time_ms - float(t[s2_end]) * 1000,
                ]

            laps.append(lap_data)

        # --- Mark invalid laps -----------------------------------------------
        # Step 1: basic time-based filtering
        valid_times = [l.lap_time_ms for l in laps if l.lap_time_ms > 0]
        if not valid_times:
            self._laps = laps
            return laps

        # Use median as reference instead of fastest (avoids race-start laps
        # skewing the threshold — a fast formation lap shouldn't be the anchor)
        sorted_times = sorted(valid_times)
        median_time = sorted_times[len(sorted_times) // 2]
        threshold = median_time * 1.2  # 20% slower than median = invalid
        too_fast = median_time * 0.85  # 15% faster than median = suspicious

        for l in laps:
            if l.lap_time_ms <= 0 or l.lap_time_ms > threshold:
                l.valid = False

        # Step 2: first lap is usually out-lap/formation/race-start
        if len(laps) > 1:
            laps[0].valid = False

        # Step 3: detect laps with broken sector patterns.
        # If a lap has sectors where any sector proportion is wildly different
        # from the majority, mark it invalid.
        laps_with_sectors = [l for l in laps if l.valid and len(l.sectors) >= 2
                             and all(s > 0 for s in l.sectors)]
        if len(laps_with_sectors) >= 3:
            # Compute sector proportions (sector_i / lap_time) per lap
            proportions = []
            for l in laps_with_sectors:
                total = sum(l.sectors)
                if total > 0:
                    proportions.append([s / total for s in l.sectors])
                else:
                    proportions.append([1.0 / len(l.sectors)] * len(l.sectors))
            # Median proportions
            n_sec = len(proportions[0])
            med_props = []
            for si in range(n_sec):
                vals = sorted(p[si] for p in proportions)
                med_props.append(vals[len(vals) // 2])
            # Flag laps where any sector proportion deviates >50% from median
            for l, props in zip(laps_with_sectors, proportions):
                for si in range(n_sec):
                    if med_props[si] > 0.05:  # ignore tiny sectors
                        ratio = props[si] / med_props[si]
                        if ratio < 0.5 or ratio > 2.0:
                            l.valid = False
                            break

        # Step 4: laps too fast compared to median are suspect
        for l in laps:
            if l.valid and l.lap_time_ms < too_fast:
                l.valid = False

        self._laps = laps
        return laps
