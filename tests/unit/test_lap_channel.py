import numpy as np
import pytest

from lmu_telemetry.core.session import Session


def test_lap_channel_length_matches_the_lap_duration(monza_q_file):
    """Lap Dist runs at 10 Hz, so a 111 s lap yields about 1110 samples."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        dist = s.lap_channel(lap, "Lap Dist")
    assert len(dist) == pytest.approx(1110, abs=3)


def test_lap_channel_covers_one_track_length(monza_q_file):
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        dist = s.lap_channel(lap, "Lap Dist")
    assert dist.min() < 50.0
    assert dist.max() > 5700.0


def test_lap_channel_is_unit_normalised(monza_q_file):
    """Throttle Pos is declared in percent; the slice must be 0..1 like the whole channel."""
    with Session.open(monza_q_file) as s:
        lap = next(l for l in s.laps if l.number == 2)
        thr = s.lap_channel(lap, "Throttle Pos")
    assert 0.0 <= thr.min()
    assert thr.max() <= 1.0
    assert thr.max() > 0.9  # the driver did use full throttle on a qualifying lap


def test_channel_array_is_cached(monza_q_file):
    """The same array object comes back, so repeated reads cost nothing."""
    with Session.open(monza_q_file) as s:
        a = s.file.channel("Lap Dist")
        b = s.file.channel("Lap Dist")
    assert a is b


def test_cached_channel_cannot_be_mutated_by_a_caller(monza_q_file):
    """A shared cached array must not be writable, or one caller corrupts another."""
    with Session.open(monza_q_file) as s:
        a = s.file.channel("Lap Dist")
        with pytest.raises(ValueError):
            a[0] = 12345.0


def test_a_lap_window_running_past_the_recording_is_clamped(monza_q_file):
    """A lap window may end after the last sample; that must truncate, not raise.

    The assertion is against the *unclamped* index span, not against the
    channel length: len(slice) <= len(channel) is true of any numpy slice
    whether or not anything clamps it, so it cannot fail and pins nothing.

    The reference session's own final lap ends inside the recording, so the
    overrun is constructed rather than assumed - otherwise the test would
    only be asserting that a window which fits, fits.
    """
    from dataclasses import replace

    with Session.open(monza_q_file) as s:
        spec = s.file.channels.require("Lap Dist")
        values = s.file.channel("Lap Dist")
        overrun = replace(s.laps[-1], t_end=s.laps[-1].t_end + 60.0)
        i0 = s.timebase.index_at(overrun.t_start, spec.frequency_hz)
        i1 = s.timebase.index_at(overrun.t_end, spec.frequency_hz)
        dist = s.lap_channel(overrun, "Lap Dist")

    assert i1 > len(values)             # the window genuinely runs off the end
    assert len(dist) > 0                # and is not thrown away wholesale
    assert len(dist) < i1 - i0          # the clamp shortened it
    assert len(dist) == len(values) - i0  # to exactly what was recorded
