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


#: How long before the reference's own brake mark the window opens, in
#: seconds of the reference's own travel - not metres, because a fixed metre
#: span does not mean a fixed warning: the same 100 m is 1.4 s at Parabolica's
#: approach speed and 4 s into a slow chicane, so a driver reading the strip
#: gets a wildly different amount of notice corner to corner even though the
#: strip itself looks the same. Time is what the driver actually experiences,
#: so it is what every corner is given equally of.
#:
#: Read straight off the lap's own clock - see :func:`_window_start` - not by
#: multiplying LEAD_S by the speed *at* the mark. That shortcut looks
#: equivalent and is not: it assumes the car held the mark's speed through the
#: whole approach, and where the approach is a hard acceleration out of a slow
#: corner it is wrong in the same direction as the fault being fixed. Both
#: were measured on a 181-session, 1705-event corpus - the shortcut ranged
#: 1.45 s to 5.82 s with 85 % of events inside +-0.3 s; the clock puts 94 % of
#: them inside +-0.1 s, and every event that is not is one of the two guards
#: below deliberately overriding it.
#:
#: What it replaces: ``corner.start_m - APPROACH_M``, the brake-point *search*
#: span used as the display window by mistake. Across the same corpus that
#: gave the driver between 0 m and 600 m of warning depending only on where
#: each brake point happened to fall inside the fixed span - and **170 of the
#: 1705 events, one in ten, opened with the mark already under 2 m away**: the
#: strip's first frame said brake now. A driver reported it as being told to
#: brake while nowhere near the braking zone.
#:
#: Two seconds on the Monza reference in ``tests/fixtures/monza_q_3laps.duckdb``
#: is 42-146 m across its 8 braking events - 42 m into the slow half of the
#: T1/T2 chicane, 146 m into T1 itself at 266 km/h. Same warning either way,
#: which is the point: a fixed distance is a different amount of notice at
#: every corner, and notice is what the driver is actually reading.
LEAD_S = 2.0

#: Floor under the lead distance, so a brake point taken at a crawl still
#: opens a window with a shape worth glancing at rather than the mark and a
#: handful of samples. LEAD_S stops being enough on its own below 72 km/h
#: (2.0 s * 20 m/s = 40 m).
#:
#: Not hypothetical: 12 of the same corpus scan's 1705 events reach it, all
#: of them the slow second half of a chicane taken at 60-70 km/h - Monza's
#: Variante del Rettifilo 2 among them. Rare, but the case it rescues is a
#: strip with almost nothing on it, which is worse than no strip.
MIN_LEAD_M = 40.0

#: Ceiling on the same distance. Nothing in this speed range asks for it -
#: 2.0 s would need upward of 450 km/h to reach 250 m - but the display must
#: never claim to show track further back than ``_brake_shape`` was allowed to
#: search over, because beyond that boundary "the brake point" is not a
#: measured fact about the lap, only an artefact of how far the window reached.
#: Tied to APPROACH_M rather than restated, so the two cannot drift apart.
MAX_LEAD_M = APPROACH_M


def _window_start(trace: LapTrace, brake_point_m: float) -> float:
    """Where the strip opens: :data:`LEAD_S` seconds before *brake_point_m*.

    Read off ``trace.time_s`` - the clock the lap was actually driven to -
    rather than converting LEAD_S into metres at some single speed and
    stepping back that far. A single speed has to be *some* speed, and every
    choice of one is wrong wherever the approach is not steady: taken at the
    mark, it treats a hard acceleration out of the previous corner as though
    the car had been at the mark's speed all along, which opens the strip
    nearly six seconds early at Sarthe's Ford chicanes. That is the same
    complaint this change exists to answer, in a smaller size, and no amount
    of picking a better single speed removes it.

    The window may open before the start/finish line, for a corner early
    enough in the lap - Spa's T1 does. A single-lap trace does not hold those
    metres, so they are read off this same lap's own tail: the car's line and
    speed at 5700 m on this lap is the closest thing there is to its line and
    speed at 5700 m on the lap before.

    Returns a grid value, so the window starts exactly on a sample and
    ``offsets_m[0]`` is exactly 0.0.
    """
    grid, time_s = trace.grid, trace.time_s
    count = len(grid)
    mark_i = min(int(np.searchsorted(grid, brake_point_m)), count - 1)

    opens_at_s = float(time_s[mark_i]) - LEAD_S
    if opens_at_s < time_s[0]:
        opens_at_s += float(time_s[-1] - time_s[0])    # round the loop
    steps = (mark_i - int(np.searchsorted(time_s, opens_at_s))) % count

    steps = min(max(steps, int(MIN_LEAD_M // GRID_STEP_M)),
                int(MAX_LEAD_M // GRID_STEP_M), count - 1)
    return float(grid[(mark_i - steps) % count])


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

    # The display window is LEAD_S seconds of the reference's own travel
    # before its brake mark - not APPROACH_M, which is how far back the
    # search for that mark was allowed to look, not how far back it makes
    # sense to *show*. Using the search span as the display window is the
    # fault this replaces: a fixed 250 m before corner.start_m puts the mark
    # wherever inside that span the braking happened to fall, from right at
    # the corner (0 m of warning) to nearly the full 250 m, and the driver
    # reading the strip has no way to know which lap they are getting.
    start_m = _window_start(trace, figures.brake_point_m)

    # Guard: the window must never open after the corner's own start. Every
    # distance in this module downstream of *start_m* is read through
    # offset_into, which measures forward from *start_m* and wraps - so if
    # the brake point sits close enough past event.start_m that lead_m does
    # not reach back far enough to clear it (trail braking deeper into the
    # corner than the lead distance), start_m lands *after* event.start_m,
    # and entry_at_m below would wrap almost a full lap instead of reading as
    # a small offset near the window's own start.
    #
    # Checked with offset_into itself, the same tool it would otherwise fool:
    # a good start_m always has event.start_m reachable within the window's
    # own span (offset_into(start_m, event.start_m, ...) no further out than
    # offset_into(start_m, event.end_m, ...)); a start_m that landed past
    # event.start_m instead puts it almost a lap out - past the window's own
    # far edge, not inside it - which is exactly what distinguishes the bad
    # case from the good one. When that happens the window opens at the
    # corner's own start instead.
    #
    # This fires, and not rarely: 106 of the corpus scan's 1705 events, 6 %,
    # are corners the reference trail-braked deep enough that _brake_shape's
    # mark sits past corner.start_m - Paul Ricard's T13 and T11-T12 among
    # them. Those events get a window longer than LEAD_S asks for, up to
    # 5.8 s at Sarthe's Ford chicanes, and that is the intended trade: a
    # window that opened LEAD_S before a mark inside the corner would begin
    # after the corner already had, leaving entry_at_m and the entry-speed
    # readout pointing outside the strip they are drawn on. Containing the
    # corner is the harder requirement; the lead time yields to it.
    entry_candidate = offset_into(start_m, event.start_m, lap_length_m)
    span_candidate = offset_into(start_m, event.end_m, lap_length_m)
    if entry_candidate > span_candidate:
        start_m = event.start_m

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
        tone name different corners. It was found at Monza's T1/T2, back when
        every window opened a fixed 250 m before its corner: T2's opened 68 m
        before T1's own brake point, so the strip swapped to T2 while T1's
        mark was still 68 m away, and the tone - which scanned for a passed
        brake point on its own - fired for T1 into a panel already showing
        T2. Picking the soonest still-ahead brake point instead keeps T1 on
        screen right through the frame its own mark is crossed, so a tone
        built on *this* method's answer can no longer disagree with what is
        drawn.

        :data:`LEAD_S` has since shortened every window, and Monza's T1/T2 no
        longer overlap that way - T2 now opens well past T1's mark. The
        arrangement did not go away, it moved: on the same lap T10's window
        opens 94 m before T8-T9's mark. Naming both pairs because a reader
        checking only the first would find nothing wrong there and conclude
        this arbitration was dead weight.
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
        tied their answers together. Where two windows overlap, that let the
        tone fire for the earlier corner while the panel had already switched
        to the later one - found at Monza's T1/T2, and since :data:`LEAD_S`
        shortened the windows it is that lap's T8-T9 and T10 that sit that
        way. Routing through :meth:`showing` makes the two
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
