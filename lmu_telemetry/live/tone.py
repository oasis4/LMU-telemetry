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


def _sound() -> None:
    try:
        import winsound

        winsound.Beep(TONE_HZ, TONE_MS)
    except Exception:
        pass


def play_brake_tone() -> None:
    """Sound the brake mark. Returns immediately."""
    threading.Thread(target=_sound, daemon=True).start()
