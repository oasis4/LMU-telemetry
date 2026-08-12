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
    """One corner's approach and braking zone, taken from one lap.

    That lap is always the reference's when the template comes from
    :func:`templates_for`, but :func:`best_templates` may fill it from
    whichever candidate drove the event quickest - see ``source`` below.
    """

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
    #: A short label for which lap this strip was drawn from, e.g.
    #: ``"Q 2026-03-27 lap 2"``, so the driver can see whose corner they are
    #: chasing. Empty for a template built by :func:`templates_for`, where
    #: there is only ever the one lap and nothing to say that distinguishes
    #: it. Defaulted rather than required so every existing construction -
    #: in tests, and in :func:`template_from` itself - keeps working without
    #: naming a lap it has no opinion about.
    source: str = ""


def braking_events(reference: LapTrace, corners) -> "list[Corner]":
    """The merged corners - one per braking event - taken from *reference*.

    A corner taken flat contributes no event: it has nothing to teach here,
    and at Monza it would mean eleven strips a lap where seven are useful.

    Consecutive corners whose reference brake points fall within
    ``SAME_BRAKING_M`` of each other are one braking event, not several -
    the same rule ``live.watch.CornerWatch`` and ``core.coaching.advice``
    already apply so a chicane is not coached on the same brake application
    two or three times over. Left ungrouped here, Monza's Roggia and Ascari
    would each draw more than one strip and sound more than one tone for a
    stop the driver felt once. The merged corner spans from the first
    corner's own start to the last corner's end, and keeps the first
    corner's name-leading identity - see :mod:`core.blocks`'s ``Block.name``,
    which names a run of corners the same way.

    Grouped from *reference* alone, and only from it: the set of braking
    events a best-of-set template draws its strips for must not change with
    which laps happen to be in the candidate pool, or which strips exist
    would depend on which lap won - see :func:`best_templates`.
    """
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

    events: "list[Corner]" = []
    for group in groups:
        first_corner, _first_figures = group[0]
        last_corner, _last_figures = group[-1]
        events.append(
            first_corner if len(group) == 1
            else replace(
                first_corner,
                name=f"{first_corner.name} - {last_corner.name}",
                end_m=last_corner.end_m,
            )
        )
    return events


def template_from(trace: LapTrace, event: Corner) -> "Template | None":
    """Fill one braking event's window from one lap, or None if it did not
    brake there.

    *event* is one of :func:`braking_events`'s own corners, already merged
    where a chicane shares one brake point, so the window read here is
    exactly the one the reference's own version of it covers. ``None``
    rather than a template with nothing in it: a lap that took this event
    flat is not a worse version of the reference's line through it, it is
    not a version at all, and :func:`best_templates` must not be able to
    pick it.
    """
    lap_length_m = float(trace.grid[-1]) + GRID_STEP_M
    # Read against *event* itself, not the first physical corner it was
    # merged from. entry_speed_kmh is unaffected either way - it only reads
    # trace.speed_kmh at corner.start_m, which the merge never moves - but
    # brake_point_m is not provably the same: a merged event's wider
    # corner.end_m widens the window _brake_shape hunts the last brake
    # application in, so a second, closer application between two merged
    # corners could in principle be picked up instead of the true first one.
    # Checked, not proven: identical to the old per-corner figure across
    # every group in the Monza fixture, including both of its actual merges,
    # and across a real 249-recording corpus run. If a future track's
    # geometry ever produces a divergence, it will show up here first.
    figures = corner_metrics(trace, event)
    if figures.brake_point_m is None:
        return None

    start_m = (event.start_m - APPROACH_M) % lap_length_m
    window = span_indices(trace.grid, start_m, event.end_m)
    if len(window) < 2:
        return None
    abs_m = trace.grid[window]
    offsets = np.array(
        [offset_into(start_m, float(d), lap_length_m) for d in abs_m]
    )
    return Template(
        corner=event,
        start_m=start_m,
        length_m=float(offsets[-1]),
        brake_at_m=offset_into(start_m, figures.brake_point_m, lap_length_m),
        entry_at_m=offset_into(start_m, event.start_m, lap_length_m),
        entry_speed_kmh=figures.entry_speed_kmh,
        offsets_m=offsets,
        abs_m=abs_m,
        brake=trace.brake[window],
        throttle=trace.throttle[window],
    )


def templates_for(reference: LapTrace, corners) -> "list[Template]":
    """One template per braking event the reference used, all from that one
    lap.

    Built directly on :func:`braking_events` and :func:`template_from`, so
    there is one grouping rule and one window-filling rule rather than two
    copies that could drift apart - :func:`best_templates` runs its many-lap
    search through the same two functions.
    """
    made: "list[Template]" = []
    for event in braking_events(reference, corners):
        template = template_from(reference, event)
        if template is not None:
            made.append(template)
    return made


def best_templates(reference: LapTrace, others, corners) -> "list[Template]":
    """Each braking event from whichever lap drove it quickest.

    *others* is every extra candidate to consider, as ``(source, trace)``
    pairs - *source* a short label for where the lap came from (``"Q
    2026-03-27 lap 2"``), *trace* built with the reference's own track
    model, so its window lands on the reference's own metres rather than its
    own.

    *reference* itself does not need to be in *others* - it is always in the
    pool anyway, appended after them with an empty source. This is a
    property the function enforces, not a precondition it trusts its caller
    to have met: a caller that also lists the reference, properly labelled
    (as ``live.__main__`` does whenever :func:`reference.find_quickest_laps`
    found it), keeps that label for any event it wins, because ties favour
    whichever candidate was offered first and the caller's own copy is
    offered before this function's own fallback copy. But an event nobody in
    *others* has a template for still gets the reference's own version -
    with ``source=""``, the same template :func:`templates_for` would have
    given it - rather than losing the strip because a candidate scan came
    back empty, was stale, or happened to exclude the reference's own lap.
    That is what makes the result never worse than :func:`templates_for` a
    guarantee, not a hope resting on how *others* was built.

    The set of events is :func:`braking_events` (*reference*, *corners*) and
    nothing else - grouped once, before any candidate is looked at, so which
    strips exist is a property of the circuit and only their contents vary
    with who drove them. A candidate that brakes somewhere the reference did
    not never gets to add a strip for it; one that took a reference braking
    event flat (:func:`template_from` returning None for it) simply does not
    compete for that one.

    Ranking is by ``corner_metrics(trace, event).time_s`` - the time actually
    spent driving that stretch, on whichever lap did it.
    """
    pool = (*others, ("", reference))
    made: "list[Template]" = []
    for event in braking_events(reference, corners):
        best: "Template | None" = None
        best_time: "float | None" = None
        for source, trace in pool:
            template = template_from(trace, event)
            if template is None:
                continue
            time_s = corner_metrics(trace, event).time_s
            if best_time is None or time_s < best_time:
                best_time, best = time_s, replace(template, source=source)
        if best is not None:
            made.append(best)
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
        they do - the one whose own brake point has not yet been reached and
        is soonest wins: that is the corner the driver is still braking
        towards, and it is what keeps this method and :meth:`due_template` in
        agreement, since the latter is now built directly on this one. Only
        once every open window has already had its brake point pass - both
        corners of a pair mid-corner, the first already braked into and being
        held through the second's approach - does the window that opened most
        recently win, the same tie-break this used unconditionally before.

        That "most recently opened" rule alone is what let the panel and the
        tone name different corners at Monza's T1/T2: T2's window opens 68 m
        before T1's own brake point, so "most recently opened" swapped the
        strip to T2 while T1's brake point was still 68 m away, and the tone
        - which scanned for a passed brake point on its own - fired for T1
        into a panel already showing T2. Picking the soonest still-ahead
        brake point instead keeps T1 on screen right through the frame its
        own mark is crossed, so a tone built on *this* method's answer can no
        longer disagree with what is drawn.
        """
        ahead: "tuple[Template, float] | None" = None
        ahead_remaining = None
        any_open: "tuple[Template, float] | None" = None
        any_open_at = None
        for template in self.templates:
            at = self._inside(template, distance_m)
            if at is None:
                continue
            self._last_inside[template.corner.index] = now
            if any_open_at is None or at < any_open_at:
                any_open_at, any_open = at, (template, at)
            if at <= template.brake_at_m:
                remaining = template.brake_at_m - at
                if ahead_remaining is None or remaining < ahead_remaining:
                    ahead_remaining, ahead = remaining, (template, at)

        chosen = ahead if ahead is not None else any_open
        if chosen is not None:
            template, at = chosen
            return Showing(template, at, past_corner=False)

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

    def due_template(self, distance_m: float, now: float) -> "Template | None":
        """The template whose brake mark has just been passed, if any - and
        only if it is the one currently on screen.

        Built on :meth:`showing` rather than its own scan of
        ``self.templates``, so the tone can never name a corner other than
        the one the strip is showing: before this, the two ran independent
        searches - :meth:`showing` picked nearest-window for *display*,
        this scanned for a passed brake point for the *tone* - and nothing
        tied their answers together. At Monza's T1/T2, where the windows
        overlap, that let the tone fire for T1 while the panel had already
        switched to T2. Routing through :meth:`showing` makes the two
        structurally unable to disagree, rather than agreeing only because
        both searches happened to land on the same corner.

        A corner whose own brake point is passed while a *different*
        template is on screen - the scenario the fix above has to answer
        for - simply is not due here: ``showing()`` no longer lets that
        happen for a *fresh* approach (see its docstring), and a *held*
        display (``past_corner``) is excluded outright, since a held
        ``Showing``'s ``at_m`` is pinned to the window's far edge and would
        otherwise always read as "past the mark". The corner it belongs to
        already had its own chance to tone while it was the fresh, on-screen
        template; this is not a second chance for it, and it does not sound
        late. Nothing here can leave a corner un-toned *silently*, though:
        :meth:`due_template` returning ``None`` for a corner whose brake
        point has genuinely passed just means it toned already (see
        :meth:`mark_toned`) or its approach was never the one shown - and a
        corner braked for by the reference always gets a turn as the fresh
        display at some point along its own approach, because a window only
        loses that contest to another window whose own brake point is
        nearer still.

        Split out from :meth:`tone_due` so a caller can decide *not* to sound
        it - the overlay withholds the tone for a window it never watched
        the approach of, the same as it withholds the strip, and it can only
        make that decision once it knows which template is in question.
        Finding a template here does not arm it; :meth:`mark_toned` does
        that separately, once the caller has decided the tone is actually
        going to sound.
        """
        showing = self.showing(distance_m, now)
        if showing is None or showing.past_corner:
            return None
        template = showing.template
        if showing.at_m < template.brake_at_m:
            return None
        if template.corner.index in self._toned:
            return None
        return template

    def mark_toned(self, template: "Template") -> None:
        """Record that *template*'s tone has sounded, so it does not again."""
        self._toned.add(template.corner.index)

    def tone_due(self, distance_m: float, now: float) -> bool:
        """True exactly once per corner, as the reference brake point passes
        while that corner is the one on screen.

        Built on :meth:`due_template` and :meth:`mark_toned` rather than its
        own loop, so there is one place that decides which template a
        distance is due for. Takes ``now`` for the same reason
        :meth:`showing` does now that this is built on it - the display
        arbitration needs to know how long ago a window was last entered.
        """
        template = self.due_template(distance_m, now)
        if template is None:
            return False
        self.mark_toned(template)
        return True
