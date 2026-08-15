"""A short tone, played without making the caller wait for it.

``winsound.Beep`` blocks for its whole duration. Called from the 50 Hz read
loop that is at that moment inside a braking zone, seventy milliseconds of
blocking is three or four samples lost from exactly the stretch the tone is
drawing attention to.

So it goes on a daemon thread. A machine with no sound device, or one that is
not Windows, gets silence rather than an exception: a driver whose speakers
are off should still be coached.
"""

from __future__ import annotations

import threading

#: A pitch that carries over engine noise without being shrill, and short
#: enough not to still be sounding at the point it is telling the driver about.
TONE_HZ = 880
TONE_MS = 70

#: How far ahead of the brake mark the tone sounds, in seconds of the
#: driver's own travel.
#:
#: It used to sound *at* the mark, which a driver reported as arriving too
#: late - correctly, and it was never going to be otherwise. A cue delivered
#: at the moment the action is due leaves no time to act on it: simple
#: auditory reaction time is around 150 ms before anything moves, and getting
#: off the throttle and onto the brake costs another 50-100 ms on top. At
#: 250 km/h that is 15-20 m past the mark before the pedal is touched, which
#: is most of what the strip is trying to fix.
#:
#: 0.3 s covers that with a little to spare, so the foot lands on the pedal
#: about where the reference's did rather than after it. Measured against the
#: driver's own speed rather than the reference's - it is their reaction the
#: lead is being held for - and against time rather than a fixed distance,
#: for the same reason the window itself is timed: a fixed 20 m is a very
#: different amount of notice into Parabolica than into a chicane.
#:
#: Well inside the window, which opens LEAD_S (2.0 s) before the same mark
#: even at its shortest, so the tone can never sound before its own strip is
#: on screen.
TONE_LEAD_S = 0.3


def _sound() -> None:
    try:
        import winsound

        winsound.Beep(TONE_HZ, TONE_MS)
    except Exception:
        pass


def play_brake_tone() -> None:
    """Sound the brake mark. Returns immediately."""
    threading.Thread(target=_sound, daemon=True).start()
