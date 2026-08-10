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

from .screens import choose_screen, monitors

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

#: Height of one pedal strip at the design scale, and the gap between the two.
_STRIP_H = 34.0
_STRIP_GAP = 6.0
#: The reference, and the driver's own lines over it.
GHOST = "#4a4a58"
OWN_BRAKE = "#ff6b52"
OWN_THROTTLE = "#43d08a"
MARK = "#8a8aa0"

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
        monitor: int | None = None,
    ) -> None:
        if position not in POSITIONS:
            raise ValueError(
                f"position must be one of {', '.join(POSITIONS)}, got {position!r}"
            )
        _make_dpi_aware()
        # Before Tk is asked anything. Tk only ever reports the primary
        # monitor, so on a two-screen desk it would size the panel for one
        # screen and place it on another.
        self._monitor = choose_screen(monitor)

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

        screen_w = self._monitor.width
        screen_h = self._monitor.height
        k = (screen_h / _BASE_HEIGHT) * scale
        width = int(
            min(max(screen_w * _WIDTH_SHARE, _MIN_WIDTH_PX * k), _MAX_WIDTH_PX * k)
        )
        pad = max(8, int(14 * k))
        self._expires_at = 0.0

        # A coloured rail down the left edge. In peripheral vision this reads
        # before any of the text does - gaining or losing is the one thing
        # worth knowing without looking directly at the panel.
        # fill/expand, not a bare pack(). The window's width is set explicitly
        # below, and pack() centres its child inside whatever it is given - so
        # the card sat in the middle of the window with the punched-out
        # background, and therefore the desktop, showing down both sides.
        shell = tk.Frame(self.root, bg=CARD)
        shell.pack(fill="both", expand=True)
        self.rail = tk.Frame(shell, bg=NEUTRAL, width=max(4, int(6 * k)))
        self.rail.pack(side="left", fill="y")
        self.rail.pack_propagate(False)

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

        self._strip_h = max(18, int(_STRIP_H * k))
        self._strip_gap = max(3, int(_STRIP_GAP * k))
        self.strips = tk.Canvas(
            card, bg=CARD, highlightthickness=0, bd=0,
            width=text_width, height=2 * self._strip_h + self._strip_gap,
        )
        self.entry = tk.Label(
            card, text="", font=("Segoe UI", max(8, int(11 * k))),
            fg=MUTED, bg=CARD, anchor="w",
        )
        self._strip_width = text_width
        self._template_up = False

        self._position = position
        self._width = width
        self._margin = int(28 * k) if margin_px is None else margin_px
        self._relayout()

    @property
    def monitor(self):
        """The screen the panel was put on, so a caller can say which."""
        return self._monitor

    def _relayout(self) -> None:
        """Re-fix the window to whatever the content now needs.

        Only the height changes - the width was decided once - so the panel
        grows and shrinks downward from a fixed top edge, or upward to a fixed
        bottom one, and never moves sideways.
        """
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        x, y = self._place(
            self._position, self._monitor, self._width, height, self._margin
        )
        self.root.geometry(f"{self._width}x{height}+{x}+{y}")

    @staticmethod
    def _strip_points(offsets_m, values, length_m, width, top, height):
        """One polyline, flattened to x1, y1, x2, y2, ... for tkinter.

        The x axis is the window in metres and nothing else. That is what puts
        the grey line and the driver's line on the same metres, which is the
        only reason the strip is worth looking at.

        The y axis is fixed 0..1 and clamped. Scaled to the data instead, a
        60 % brake application and a 90 % one would be drawn at the same
        height, and the template would be pretty and wrong.
        """
        if length_m <= 0 or len(offsets_m) == 0:
            return [0.0, float(top + height), float(width), float(top + height)]
        flat: "list[float]" = []
        for offset, value in zip(offsets_m, values):
            x = float(offset) / float(length_m) * float(width)
            clamped = min(1.0, max(0.0, float(value)))
            flat.extend([x, float(top) + (1.0 - clamped) * float(height)])
        if len(flat) == 2:
            # tkinter will not draw a line with one point, and the driver has
            # exactly one sample on the first frame of every window.
            flat = flat + [flat[0] + 0.5, flat[1]]
        return flat

    @staticmethod
    def _place(position, monitor, width, height, margin):
        """Where the window goes, in the virtual desktop's coordinates.

        Every result is offset by the monitor's own origin. That offset is
        zero for the primary and only for the primary - computing from a width
        alone, as this used to, is the same as asserting every screen starts
        at x=0, which is how the panel kept appearing on the wrong one.
        """
        vertical, _, horizontal = position.partition("-")
        if horizontal == "center":
            x = monitor.x + (monitor.width - width) // 2
        elif horizontal == "left":
            x = monitor.x + margin
        else:
            x = monitor.x + monitor.width - width - margin
        y = (monitor.y + margin if vertical == "top"
             else monitor.y + monitor.height - height - margin)
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

    def show_template(self, showing, own_brake, own_throttle,
                      entry_delta_kmh=None) -> None:
        """The reference's pedals for this corner, with the driver's over them.

        Drawn from scratch each frame rather than moved: the driver's line
        grows by a point or two per frame and the reference does not change,
        and a canvas of a few hundred segments redraws far inside the 15 Hz
        this is called at.
        """
        template = showing.template
        width, height = self._strip_width, self._strip_h
        gap = self._strip_gap
        self.strips.delete("all")

        for top, values, own, colour in (
            (0, template.brake, own_brake, OWN_BRAKE),
            (height + gap, template.throttle, own_throttle, OWN_THROTTLE),
        ):
            self.strips.create_line(
                *self._strip_points(template.offsets_m, values,
                                    template.length_m, width, top, height),
                fill=GHOST, width=max(2, int(height / 12)),
            )
            if len(own):
                self.strips.create_line(
                    *self._strip_points(template.offsets_m[:len(own)], own,
                                        template.length_m, width, top, height),
                    fill=colour, width=max(2, int(height / 10)),
                )

        mark = template.brake_at_m / template.length_m * width
        self.strips.create_line(
            mark, 0, mark, 2 * height + gap, fill=MARK, dash=(3, 3),
        )
        here = showing.at_m / template.length_m * width
        self.strips.create_line(
            here, 0, here, 2 * height + gap, fill=INK,
        )

        if entry_delta_kmh is None:
            self.entry.configure(text=template.corner.name.upper())
        else:
            # Shown, never corrected for. A car arriving slower may brake
            # later, but turning that into a moved mark would be a braking
            # model, and the number would look measured when it was invented.
            self.entry.configure(
                text=f"{template.corner.name.upper()}   "
                     f"{entry_delta_kmh:+.0f} km/h in"
            )

        if not self._template_up:
            self.entry.pack(anchor="w", pady=self._tip_pad)
            self.strips.pack(anchor="w", fill="x")
            self._template_up = True
            self._relayout()

    def hide_template(self) -> None:
        if not self._template_up:
            return
        self.strips.pack_forget()
        self.entry.pack_forget()
        self._template_up = False
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
