"""The window a braking template is drawn over, and what fills it.

Everything here is an offset into that window, not a lap distance. A window
that crosses the start/finish line is two ranges in lap distance, and every
consumer - the drawing, the tone, the driver's own line - would have to know
it. As an offset it is one range that starts at zero and only increases.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.corners import Corner
from ..core.geometry import GRID_STEP_M, span_indices
from ..core.metrics import APPROACH_M, corner_metrics
from ..core.trace import LapTrace


def offset_into(start_m: float, distance_m: float, lap_length_m: float) -> float:
    """How far past *start_m* the car is, measured forward round the lap."""
    return float((distance_m - start_m) % lap_length_m)


@dataclass(frozen=True)
class Template:
    """One corner's approach and braking zone, taken from the reference lap."""

    corner: Corner
    #: Where the window begins, as a lap distance.
    start_m: float
    length_m: float
    #: Offsets into the window, not lap distances. See the module docstring.
    brake_at_m: float
    entry_at_m: float
    entry_speed_kmh: float
    offsets_m: np.ndarray
    #: The same points as lap distances, so the driver's own trace can be
    #: sampled at exactly the places the grey line was.
    abs_m: np.ndarray
    brake: np.ndarray
    throttle: np.ndarray


def templates_for(reference: LapTrace, corners) -> "list[Template]":
    """One template per corner the reference braked for.

    A corner taken flat is skipped rather than drawn with no mark on it: it
    has nothing to teach here, and at Monza it would mean eleven strips a lap
    where seven are useful.
    """
    lap_length_m = float(reference.grid[-1]) + GRID_STEP_M
    made: "list[Template]" = []
    for corner in corners:
        figures = corner_metrics(reference, corner)
        if figures.brake_point_m is None:
            continue
        start_m = (corner.start_m - APPROACH_M) % lap_length_m
        window = span_indices(reference.grid, start_m, corner.end_m)
        if len(window) < 2:
            continue
        abs_m = reference.grid[window]
        offsets = np.array(
            [offset_into(start_m, float(d), lap_length_m) for d in abs_m]
        )
        made.append(Template(
            corner=corner,
            start_m=start_m,
            length_m=float(offsets[-1]),
            brake_at_m=offset_into(start_m, figures.brake_point_m, lap_length_m),
            entry_at_m=offset_into(start_m, corner.start_m, lap_length_m),
            entry_speed_kmh=figures.entry_speed_kmh,
            offsets_m=offsets,
            abs_m=abs_m,
            brake=reference.brake[window],
            throttle=reference.throttle[window],
        ))
    return made


#: How long a template stays up after its corner is behind the car. During the
#: corner the driver has no attention to spare; afterwards is when they can
#: look at whether it fitted.
TEMPLATE_HOLD_S = 1.5


@dataclass(frozen=True)
class Showing:
    """The template on screen now, and where in it the car is."""

    template: Template
    at_m: float
    #: True once the corner is behind the car and this is the hold.
    past_corner: bool


class TemplateWatch:
    """Which template is up, and whether the tone has fallen due.

    Kept apart from the drawing for the same reason CornerWatch is: this is
    the part with behaviour in it, and it should answer without a window or a
    running game.
    """

    def __init__(self, templates, lap_length_m: float) -> None:
        self.templates = list(templates)
        self.lap_length_m = float(lap_length_m)
        self._toned: set[int] = set()
        #: Per corner, the last moment the car was seen inside its window.
        #: The hold is measured from here rather than from the first frame
        #: after leaving, so it means one thing - "this long since the car was
        #: in the window" - instead of depending on which frame first noticed.
        self._last_inside: "dict[int, float]" = {}

    def reset(self) -> None:
        """A new lap. Every template arms again."""
        self._toned.clear()
        self._last_inside.clear()

    def _inside(self, template: Template, distance_m: float) -> "float | None":
        at = offset_into(template.start_m, distance_m, self.lap_length_m)
        return at if at <= template.length_m else None

    def showing(self, distance_m: float, now: float) -> "Showing | None":
        """The template to draw, or None.

        Where two windows overlap - Ascari's corners are close enough that
        they do - the one whose window started most recently wins, because
        that is the corner being driven into rather than the one just left.
        """
        best: "Showing | None" = None
        best_at = None
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None:
                continue
            self._last_inside[template.corner.index] = now
            if best_at is None or at < best_at:
                best_at, best = at, Showing(template, at, past_corner=False)

        if best is not None:
            return best

        # Outside every window. Hold the one just left, briefly, so the
        # driver can look at whether it fitted once the corner no longer
        # needs their attention.
        for template in self.templates:
            last = self._last_inside.get(template.corner.index)
            if last is not None and now - last <= TEMPLATE_HOLD_S:
                return Showing(template, template.length_m, past_corner=True)
        return None

    def tone_due(self, distance_m: float) -> bool:
        """True exactly once per corner, as the reference brake point passes."""
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None or at < template.brake_at_m:
                continue
            index = template.corner.index
            if index in self._toned:
                continue
            self._toned.add(index)
            return True
        return False
