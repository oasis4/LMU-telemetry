"""The window a braking template is drawn over, and what fills it.

Everything here is an offset into that window, not a lap distance. A window
that crosses the start/finish line is two ranges in lap distance, and every
consumer - the drawing, the tone, the driver's own line - would have to know
it. As an offset it is one range that starts at zero and only increases.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ..core.coaching import SAME_BRAKING_M
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
    """One template per braking event the reference used.

    A corner taken flat is skipped rather than drawn with no mark on it: it
    has nothing to teach here, and at Monza it would mean eleven strips a lap
    where seven are useful.

    Consecutive corners whose reference brake points fall within
    ``SAME_BRAKING_M`` of each other are one braking event, not several -
    the same rule ``live.watch.CornerWatch`` and ``core.coaching.advice``
    already apply so a chicane is not coached on the same brake application
    two or three times over. Left ungrouped here, Monza's Roggia and Ascari
    would each draw more than one strip and sound more than one tone for a
    stop the driver felt once. The merged template spans from the earliest
    window's start to the last corner's end, and keeps the earliest brake
    point and the first corner's entry - it is that first corner's approach
    that the driver is actually braking for.
    """
    lap_length_m = float(reference.grid[-1]) + GRID_STEP_M

    braked: "list[tuple[Corner, CornerMetrics]]" = []
    for corner in corners:
        figures = corner_metrics(reference, corner)
        if figures.brake_point_m is None:
            continue
        braked.append((corner, figures))

    # Group consecutive braked corners - consecutive in the order driven,
    # not merely close on the map - that share one brake point. A later
    # corner is folded into the group open at the time it is reached, so a
    # run of three (Ascari) merges as readily as a run of two (Roggia).
    groups: "list[list[tuple[Corner, CornerMetrics]]]" = []
    for item in braked:
        if groups and abs(
            item[1].brake_point_m - groups[-1][-1][1].brake_point_m
        ) < SAME_BRAKING_M:
            groups[-1].append(item)
        else:
            groups.append([item])

    made: "list[Template]" = []
    for group in groups:
        first_corner, first_figures = group[0]
        last_corner, _last_figures = group[-1]
        corner = (
            first_corner if len(group) == 1
            else replace(
                first_corner,
                name=f"{first_corner.name} - {last_corner.name}",
                end_m=last_corner.end_m,
            )
        )
        start_m = (first_corner.start_m - APPROACH_M) % lap_length_m
        window = span_indices(reference.grid, start_m, last_corner.end_m)
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
            brake_at_m=offset_into(
                start_m, first_figures.brake_point_m, lap_length_m
            ),
            entry_at_m=offset_into(start_m, first_corner.start_m, lap_length_m),
            entry_speed_kmh=first_figures.entry_speed_kmh,
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
        # needs their attention. Where two held windows overlap, the most
        # recently left one wins, for the same reason as above: it is the
        # corner the driver was in last, not whichever happens to come first
        # in the list.
        held: "Showing | None" = None
        held_last = None
        for template in self.templates:
            last = self._last_inside.get(template.corner.index)
            if last is None or now - last > TEMPLATE_HOLD_S:
                continue
            if held_last is None or last > held_last:
                held_last, held = last, Showing(template, template.length_m, past_corner=True)
        return held

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
