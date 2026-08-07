"""A small always-on-top panel: the delta, and the last corner's sentence.

Not injected into the game's renderer. Hooking a running D3D device is a far
larger and more fragile undertaking, and it buys nothing for text in a corner
of the screen. The cost of that choice is real and belongs here rather than in
a README nobody opens: **an exclusive-fullscreen game covers this window.**
LMU must run borderless or windowed for the panel to be visible at all.

The window's own background is punched out with ``-transparentcolor``, so
there is no grey rectangle around the panel, but the panel itself is a solid
dark card. Transparent *text* was the first design and is unreadable in
practice: white letters over a white kerb are white letters over a white kerb,
and the one moment the driver most needs to read it is the moment they are
next to one.
"""

from __future__ import annotations

import tkinter as tk

#: The colour the window paints where it wants to be see-through. A near-black
#: rather than pure black, so a genuinely black pixel inside the panel is not
#: punched out along with the background.
TRANSPARENT = "#000001"

PANEL = "#101018"
INK = "#e8e8ea"
MUTED = "#8f8f99"
LOST = "#e0705c"
GAINED = "#57b98b"


class Overlay:
    """The panel. Call :meth:`pump` from the loop that feeds it."""

    def __init__(self, x: int = 40, y: int = 40, alpha: float = 0.92) -> None:
        self.root = tk.Tk()
        self.root.title("LMU corner coach")
        self.root.overrideredirect(True)              # no title bar
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", alpha)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            # Not Windows. The panel still draws; it just sits on a rectangle.
            pass
        self.root.geometry(f"+{x}+{y}")

        card = tk.Frame(self.root, bg=PANEL, padx=14, pady=10)
        card.pack()

        self.delta = tk.Label(
            card, text="--.---", font=("Consolas", 32, "bold"), fg=MUTED, bg=PANEL,
        )
        self.delta.pack(anchor="w")

        self.corner = tk.Label(
            card, text="", font=("Segoe UI", 10), fg=MUTED, bg=PANEL,
        )
        self.sentence = tk.Label(
            card, text="", font=("Segoe UI", 14, "bold"), fg=INK, bg=PANEL,
            wraplength=380, justify="left",
        )

    def show_delta(self, seconds: float | None) -> None:
        """The live gap to the reference. ``None`` before there is one."""
        if seconds is None:
            self.delta.configure(text="--.---", fg=MUTED)
            return
        self.delta.configure(
            text=f"{seconds:+.3f}", fg=LOST if seconds > 0 else GAINED
        )

    def show_finding(self, name: str, sentence: str | None) -> None:
        """A corner just completed.

        ``None`` means its measurements did not agree on a story, and the panel
        then shows nothing at all rather than the corner's name over an empty
        line. Silence is the post-lap view's answer too, and a driver glancing
        at a name with no advice under it would read it as a tip that failed to
        load.
        """
        if not sentence:
            self.corner.pack_forget()
            self.sentence.pack_forget()
            return
        self.corner.configure(text=name)
        self.sentence.configure(text=sentence)
        self.corner.pack(anchor="w", pady=(6, 0))
        self.sentence.pack(anchor="w")

    def pump(self) -> None:
        """Let tkinter draw. Raises ``tk.TclError`` once the window is closed."""
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        self.root.destroy()
