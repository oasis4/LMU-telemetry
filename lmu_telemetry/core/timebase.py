"""Mapping between channel sample indices and event timestamps.

Channels carry no timestamps - only a fixed sampling frequency declared in
``channelsList``.  Events carry timestamps in the same clock as the ``GPS Time``
channel.  Sample *i* of a channel running at *f* Hz therefore occurs at::

    t_i = gps_time[0] + i / f

Verified across the whole corpus (40 files, 224 Lap Dist resets) against the
external fact that a distance reset must coincide with a Lap event: median
error 0.0525 s, p90 0.0925 s - both inside one 10 Hz sample.  Stretching the
GPS Time array onto the channel length instead gives 0.0774 s / 0.1464 s.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TimeBase:
    """Session clock origin, taken from the first ``GPS Time`` sample."""

    t0: float

    @classmethod
    def from_file(cls, tf) -> "TimeBase":
        t0 = tf.first_channel_value("GPS Time")
        if t0 is None:
            raise ValueError(f"{tf.path.name}: GPS Time channel is empty")
        return cls(t0=float(t0))

    def axis(self, n_samples: int, frequency_hz: int) -> np.ndarray:
        """Timestamps for *n_samples* consecutive samples at *frequency_hz*."""
        if frequency_hz <= 0:
            raise ValueError(f"frequency must be positive, got {frequency_hz}")
        return self.t0 + np.arange(n_samples, dtype=np.float64) / frequency_hz

    def axis_for(self, tf, channel_name: str) -> np.ndarray:
        """Timestamps for every sample of *channel_name* in *tf*."""
        spec = tf.channels.require(channel_name)
        n = len(tf.raw_channel(channel_name))
        return self.axis(n, spec.frequency_hz)

    def index_at(self, time_s: float, frequency_hz: int) -> int:
        """Nearest sample index at *frequency_hz* for absolute *time_s*."""
        if frequency_hz <= 0:
            raise ValueError(f"frequency must be positive, got {frequency_hz}")
        idx = int(round((time_s - self.t0) * frequency_hz))
        return max(idx, 0)

    def channel_window(self, tf, channel_name: str, t_start: float, t_end: float) -> np.ndarray:
        """The slice of *channel_name* covering the interval [t_start, t_end).

        Channels carry no timestamps, so the interval is mapped onto sample
        indices via the channel's declared frequency. Both ends are clamped to
        the array, so a window running past the end of a recording yields a
        short slice rather than raising or wrapping.
        """
        spec = tf.channels.require(channel_name)
        values = tf.channel(channel_name)
        i0 = min(self.index_at(t_start, spec.frequency_hz), len(values))
        i1 = min(self.index_at(t_end, spec.frequency_hz), len(values))
        return values[i0:i1]
