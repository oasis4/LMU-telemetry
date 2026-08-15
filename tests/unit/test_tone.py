"""The tone at the reference brake point.

The only thing worth asserting without a sound card is that it does not do
the two things that would matter: block the reader, or raise.
"""

import time

from lmu_telemetry.live.tone import TONE_MS, play_brake_tone


def test_the_tone_does_not_block_the_reader():
    """winsound.Beep blocks. Eighty milliseconds of it inside a 50 Hz read
    loop is four lost samples in the middle of a braking zone - the one place
    the reader must not stall."""
    started = time.perf_counter()
    for _ in range(3):
        play_brake_tone()
    took = time.perf_counter() - started
    assert took < (TONE_MS / 1000.0), f"blocked for {took:.3f} s"


def test_the_tone_never_raises():
    """A machine with no sound device is a machine that should still coach."""
    play_brake_tone()
    play_brake_tone()
