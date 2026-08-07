"""A small always-on-top panel: the delta, and the last corner's sentence.

Not injected into the game's renderer. Hooking a running D3D device is a far
larger and more fragile undertaking, and it buys nothing for text in a corner
of the screen. The cost of that choice is real and belongs here rather than in
a README nobody opens: **an exclusive-fullscreen game covers this window.**
LMU must run borderless or windowed for the panel to be visible at all.

Three things decide whether a panel like this is actually usable at speed.

**Where it sits.** The default is top centre, not a corner. On a 32:9 screen a
top-left panel is two and a half thousand pixels from where the driver is
looking, which is not peripheral vision, it is another postcode. Top centre
sits just above the horizon, where the eyes already are.

**How big it is.** Sizes are derived from the screen's own height rather than
fixed in points, so a 1440p or 4K screen gets a proportionally larger panel
instead of the same one rendered small. The process is made DPI-aware first,
or Windows reports a 4K screen at 150% scaling as 2560 wide and everything is
sized for a monitor that is not there.

**That it never twitches sideways.** The width is fixed at construction, so a
tip arriving does not shuffle the panel left and right in the corner of the
eye. It grows downward instead, and shrinks back to the delta alone when the
tip expires - reserving the two lines permanently was the first design and
left a large empty card on screen for most of the lap.

The window background is punched out with ``-transparentcolor`` so there is no
grey rectangle around it, but the panel itself is a solid dark card.
Transparent *text* was the first design and is unreadable in practice: white
letters over a white kerb are white letters over a white kerb, and the one
moment the driver most needs to read it is the moment they are beside one.
"""

from __future__ import annotations

import time
import tkinter as tk

#: The colour the window paints where it wants to be see-through. A near-black
#: rather than pure black, so a genuinely black pixel inside the panel is not
#: punched out along with the background.
TRANSPARENT = "#000001"

CARD = "#0b0b11"
INK = "#f2f2f5"
MUTED = "#8b8b96"
LOST = "#ff6b52"
GAINED = "#43d08a"
NEUTRAL = "#6f6f7a"

#: How long a corner's sentence stays up. Long enough to read on the straight
#: that follows, short enough that it is gone before the next braking zone -
#: advice about a corner two corners ago, still sitting there, reads as advice
#: about the one being driven.
SENTENCE_SECONDS = 11.0

#: Where the panel may be put. Top centre is the default for the reason in the
#: module docstring.
POSITIONS = (
    "top-center", "top-left", "top-right",
    "bottom-center", "bottom-left", "bottom-right",
)

#: The design was drawn against a 1080-high screen; everything scales from it.
_BASE_HEIGHT = 1080.0
#: Panel width as a share of screen width, and the range it may take. The cap
#: is what stops a 32:9 screen producing a panel a metre wide.
_WIDTH_SHARE = 0.20
_MIN_WIDTH_PX = 360
_MAX_WIDTH_PX = 620


def _make_dpi_aware() -> None:
    """Ask Windows for real pixels before Tk asks for the screen size.

    Without this a 4K screen at 150% scaling reports 2560x1440, the panel is
    sized for a monitor that is not there, and Windows then scales the result
    up into something soft. Harmless and ignored anywhere that is not Windows.
    """
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()    # older Windows
        except Exception:
            pass


class Overlay:
    """The panel. Call :meth:`pump` from the loop that feeds it."""

    def __init__(
        self,
        position: str = "top-center",
        scale: float = 1.0,
        margin_px: int | None = None,
    ) -> None:
        if position not in POSITIONS:
            raise ValueError(
                f"position must be one of {', '.join(POSITIONS)}, got {position!r}"
            )
        _make_dpi_aware()

        self.root = tk.Tk()
        self.root.title("LMU corner coach")
        self.root.overrideredirect(True)              # no title bar
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg=TRANSPARENT)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            # Not Windows. The panel still draws; it just sits on a rectangle.
            pass

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        k = (screen_h / _BASE_HEIGHT) * scale
        width = int(
            min(max(screen_w * _WIDTH_SHARE, _MIN_WIDTH_PX * k), _MAX_WIDTH_PX * k)
        )
        pad = max(8, int(14 * k))
        self._expires_at = 0.0

        # A coloured rail down the left edge. In peripheral vision this reads
        # before any of the text does - gaining or losing is the one thing
        # worth knowing without looking directly at the panel.
        shell = tk.Frame(self.root, bg=CARD)
        shell.pack()
        self.rail = tk.Frame(shell, bg=NEUTRAL, width=max(4, int(6 * k)))
        self.rail.pack(side="left", fill="y")

        card = tk.Frame(shell, bg=CARD, padx=pad, pady=max(6, int(10 * k)))
        card.pack(side="left", fill="both", expand=True)

        text_width = width - self.rail.cget("width") - 2 * pad

        self.delta = tk.Label(
            card, text="--.---", font=("Consolas", max(18, int(38 * k)), "bold"),
            fg=NEUTRAL, bg=CARD, anchor="w", width=0,
        )
        self.delta.pack(anchor="w")

        self.corner = tk.Label(
            card, text="", font=("Segoe UI Semibold", max(8, int(11 * k))),
            fg=MUTED, bg=CARD, anchor="w",
        )
        self.sentence = tk.Label(
            card, text="", font=("Segoe UI", max(10, int(15 * k)), "bold"),
            fg=INK, bg=CARD, wraplength=max(120, text_width),
            justify="left", anchor="nw",
        )
        self._tip_pad = (max(2, int(4 * k)), 0)

        self._position = position
        self._screen = (screen_w, screen_h)
        self._width = width
        self._margin = int(28 * k) if margin_px is None else margin_px
        self._relayout()

    def _relayout(self) -> None:
        """Re-fix the window to whatever the content now needs.

        Only the height changes - the width was decided once - so the panel
        grows and shrinks downward from a fixed top edge, or upward to a fixed
        bottom one, and never moves sideways.
        """
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x, y = self._place(
            self._position, *self._screen, self._width, height, self._margin
        )
        self.root.geometry(f"{self._width}x{height}+{x}+{y}")

    @staticmethod
    def _place(position, screen_w, screen_h, width, height, margin):
        vertical, _, horizontal = position.partition("-")
        if horizontal == "center":
            x = (screen_w - width) // 2
        elif horizontal == "left":
            x = margin
        else:
            x = screen_w - width - margin
        y = margin if vertical == "top" else screen_h - height - margin
        return x, y

    def show_delta(self, seconds: float | None) -> None:
        """The live gap to the reference. ``None`` before there is one."""
        if seconds is None:
            self.delta.configure(text="--.---", fg=NEUTRAL)
            self.rail.configure(bg=NEUTRAL)
            return
        colour = LOST if seconds > 0 else GAINED
        self.delta.configure(text=f"{seconds:+.3f}", fg=colour)
        self.rail.configure(bg=colour)

    def show_finding(self, name: str, sentence: str | None) -> None:
        """A corner just completed.

        ``None`` means its measurements did not agree on a story, and the panel
        then shows nothing at all rather than the corner's name over an empty
        line. Silence is the post-lap view's answer too, and a driver glancing
        at a name with no advice under it would read it as a tip that failed to
        arrive.
        """
        if not sentence:
            return self._clear()
        self.corner.configure(text=name.upper())
        self.sentence.configure(text=sentence)
        self.corner.pack(anchor="w", pady=self._tip_pad)
        self.sentence.pack(anchor="w", fill="x")
        self._expires_at = time.monotonic() + SENTENCE_SECONDS
        self._relayout()

    def _clear(self) -> None:
        if not self._expires_at:
            return                      # already just the delta; nothing to do
        self.corner.pack_forget()
        self.sentence.pack_forget()
        self._expires_at = 0.0
        self._relayout()

    def pump(self) -> None:
        """Let tkinter draw, and retire a sentence that has had its time.

        Raises ``tk.TclError`` once the window has been closed.
        """
        if self._expires_at and time.monotonic() >= self._expires_at:
            self._clear()
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        self.root.destroy()
