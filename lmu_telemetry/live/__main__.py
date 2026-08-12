"""Run the corner overlay.

    python -m lmu_telemetry.live --reference LAP.duckdb --reference-lap 2 \
                                 --replay  LAP.duckdb --replay-lap 1

The reference lap is built through the ordinary pipeline, so the corner list
and the distance grid the overlay works on are the same objects the browser
view works on - not a second copy that could drift from it.

Without ``--replay`` it reads the running game instead. ``--probe`` prints raw
frames and exits, which is how the shared-memory transcription gets checked
against a real session.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from ..core.geometry import GRID_STEP_M
from ..core.metrics import APPROACH_M
from ..core.session import Session
from ..core.track_model import build_track_model, TrackModel
from ..core.trace import build_trace
from ..recordings import default_recordings_dir
from .buffer import LapBuffer
from .overlay import POSITIONS
from .replay import replay
from .template import TemplateWatch, best_templates, templates_for
from .tone import play_brake_tone
from .watch import CornerWatch

#: The panel is read by a driver, not sampled by an instrument. Redrawing at
#: every sample spends the whole budget on a number nobody can read changing
#: 50 times a second.
REDRAW_HZ = 15.0


def _trace_of(path: Path, lap_number: int | None):
    """One lap of one recording, with the track model it was measured against."""
    with Session.open(path) as session:
        model = build_track_model([session])
        if model is None:
            raise SystemExit(f"{path.name}: no track model could be built")
        if lap_number is None:
            lap = session.fastest_lap
            if lap is None:
                raise SystemExit(f"{path.name}: no usable lap to take as reference")
        else:
            lap = next((l for l in session.laps if l.number == lap_number), None)
            if lap is None:
                have = ", ".join(str(l.number) for l in session.laps)
                raise SystemExit(f"{path.name}: no lap {lap_number}; it has {have}")
        return build_trace(session, lap, model.track_length_m), model, lap


def _candidate_source(path: Path, lap_number: int, model: TrackModel):
    """One best-of-set candidate, as the ``(source, trace)`` pair
    :func:`live.template.best_templates` wants - or None if it could not be
    built.

    Built with *model*'s own ``track_length_m`` and ``origin`` rather than
    this recording's, so its absolute distances land on the reference's own
    metres: a candidate on a different track model would put its strip
    against the wrong point on the strip's own axis, which is metres and
    nothing else - see ``overlay.Overlay._strip_points``.

    Skipped, not raised, on anything that goes wrong - a damaged recording,
    a lap number that no longer exists in it, a lap too short to measure -
    the same treatment :func:`reference.find_quickest_laps` already gives a
    file it cannot read. One bad candidate is not a reason to fall back to
    the single reference lap for every corner.
    """
    try:
        with Session.open(path) as session:
            lap = next((l for l in session.laps if l.number == lap_number), None)
            if lap is None:
                return None
            trace = build_trace(
                session, lap, model.track_length_m, origin=model.origin
            )
            letter = (session.info.session_type or "?")[:1].upper()
            date = (session.info.recorded_at or "?").split("T")[0]
            return f"{letter} {date} lap {lap.number}", trace
    except Exception:
        return None


def _choose_templates(auto_found, recordings: Path, live, reference, model):
    """The templates for this run, and the line describing where they came
    from.

    Only reaches for the best-of-set when *auto_found* is not None - that is,
    when the reference itself was found automatically rather than named with
    --reference. A driver who named a lap gets that lap, unmixed with any
    other: :func:`templates_for`, unchanged.

    *auto_found* doubles as the track name to search on: it is the
    ``Reference`` :func:`_await_reference` already picked, and asking
    :func:`reference.find_quickest_laps` with its own ``track`` is what keeps
    the candidate pool and the reference itself agreeing about which circuit
    is meant.

    The candidate scan below is not required to find the reference's own lap
    again for the result to be complete - ``best_templates`` puts the
    reference into its own pool regardless, so a scan that comes back empty,
    or a rebuild that fails for that one recording, still yields every
    braking event rather than silently losing some. Re-reading
    ``live.track_length_m()``/``live.car_class()`` here rather than
    threading them through from ``_await_reference`` is therefore a
    readability choice, not a correctness one: the two reads disagreeing
    would at worst narrow the candidate pool, not drop a strip.
    """
    if auto_found is None:
        made = templates_for(reference, model.corners)
        return made, f"{len(made)} braked corners"

    from .reference import find_quickest_laps

    length_m = live.track_length_m() if hasattr(live, "track_length_m") else None
    car_class = live.car_class() if hasattr(live, "car_class") else None
    candidates = find_quickest_laps(
        recordings, auto_found.track, length_m=length_m, car_class=car_class
    )

    sources = []
    for candidate in candidates:
        got = _candidate_source(candidate.path, candidate.lap_number, model)
        if got is not None:
            sources.append(got)

    made = best_templates(reference, sources, model.corners)
    # Empty-string sources are best_templates' own reference fallback, not a
    # lap from the pool - counting them would claim a "different lap
    # contributed" for an event nobody in *sources* actually won.
    contributed = {template.source for template in made if template.source}
    return made, (
        f"{len(made)} braking events from {len(sources)} laps "
        f"({len(contributed)} different laps contributed)"
    )


def _from_game(live):
    """Samples from the running game, each with the lap it belongs to.

    Frames the reader refuses - in the menus, or a distance that jumped - are
    skipped rather than passed on. A refused frame is not a gap in the lap;
    the next good one lands on the grid where it belongs.
    """
    with live:
        while True:
            got = live.sample()
            if got is None:
                time.sleep(0.02)
                continue
            yield got
            # The game writes at about 50 Hz. Polling much faster only returns
            # the same frame again, which `LapBuffer.add` would discard anyway.
            time.sleep(0.01)


def _from_replay(trace, speed: float, lap_number: int):
    """The same shape, from a recording: one lap, so one lap number."""
    for sample in replay(trace, speed=speed):
        yield sample, lap_number


def _await_reference(live, recordings: Path, patience_s: float = 120.0):
    """Wait for the game to load a circuit, then find a lap driven on it.

    This is what lets the overlay be started once, before the session, rather
    than being handed a filename every time. The track name comes from
    scoring, which answers while the driver is still in the garage - which is
    the moment there is time to go and read a few hundred recordings.
    """
    from .reference import find_reference

    print(f"waiting for a circuit to load (looking in {recordings})")
    deadline = time.perf_counter() + patience_s
    track = ""
    while not track:
        if time.perf_counter() > deadline:
            print("no circuit loaded - is the game in a session?", file=sys.stderr)
            return None
        track = live.track_name()
        if not track:
            time.sleep(1.0)

    # The length, not just the name. Two layouts of one circuit share a name
    # and the game names no layout, so without this the quickest lap "at
    # Monza" is systematically the short variant - it is quicker for being
    # shorter - and every delta is measured against a different track.
    length_m = live.track_length_m() if hasattr(live, "track_length_m") else None
    # The class as well. A Hypercar reference under a GT3 driver is nine
    # seconds a lap and every corner reads as a disaster - the same shape of
    # fault as the layout: "the quickest lap here" is the quickest *car*.
    # Read after the circuit, because it only answers once a car exists.
    car_class = live.car_class() if hasattr(live, "car_class") else None
    print(f"circuit:   {track}"
          + (f", {length_m / 1000:.3f} km" if length_m else "")
          + (f"   class: {car_class}" if car_class else ""))
    if not recordings.is_dir():
        print(
            f"no recordings directory at {recordings}. Point --recordings at "
            f"one, or name a lap with --reference.",
            file=sys.stderr,
        )
        return None

    found = find_reference(
        recordings, track, length_m=length_m, car_class=car_class
    )
    if found is None:
        # Said apart, because they lead to different next moves: drive a lap
        # here, against you have laps here but in the other car or on the
        # other layout.
        other_class = (
            find_reference(recordings, track, length_m=length_m)
            if car_class else None
        )
        elsewhere = find_reference(recordings, track) if length_m else None
        if other_class is not None:
            with Session.open(other_class.path) as session:
                theirs = session.info.car_class
            print(
                f"nothing recorded here in {car_class}. There are laps on this "
                f"course in {theirs} - {other_class.path.name} is one - but a "
                f"reference from another class is worse than none: a Hypercar "
                f"lap at Monza is nine seconds under a GT3 one, and every "
                f"corner would report you hopelessly off a target this car "
                f"cannot reach. Drive a lap in this class, or name one with "
                f"--reference.",
                file=sys.stderr,
            )
        elif elsewhere is not None:
            print(
                f"nothing recorded on this layout of {track} "
                f"({length_m / 1000:.3f} km). There are laps under that name - "
                f"{elsewhere.path.name} is one - but on a course of a "
                f"different length, so measuring against it would compare two "
                f"different tracks. Drive a lap on this one, or name a lap "
                f"with --reference.",
                file=sys.stderr,
            )
        else:
            print(
                f"nothing recorded at {track} yet, so there is nothing to "
                f"measure against. Drive a lap with the game's own telemetry "
                f"logging on, or name a lap from elsewhere with --reference.",
                file=sys.stderr,
            )
    return found


def _probe(seconds: float = 20.0) -> int:
    """Print what the game is reporting, so the transcription can be checked.

    Speed must agree with the game's own readout and distance must climb
    smoothly to the track length and reset. Anything else means the structs in
    :mod:`live.sharedmem` do not match the installed version - which does not
    announce itself any other way, because a wrong layout returns numbers that
    look like numbers.
    """
    from .sharedmem import LiveTelemetry, SharedMemoryUnavailable

    try:
        live = LiveTelemetry()
    except SharedMemoryUnavailable as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    print("reading LMU_Data - drive, and watch that these move sensibly")
    print(f"{'lap':>4} {'dist m':>9} {'km/h':>7} {'thr':>5} {'brk':>5} {'steer':>6}")
    started = time.perf_counter()
    with live:
        while time.perf_counter() - started < seconds:
            got = live.sample()
            if got is None:
                print("  (no car - in the menus, or the frame was refused)")
            else:
                s, lap = got
                print(
                    f"{lap:>4} {s.distance_m:>9.1f} {s.speed_kmh:>7.1f} "
                    f"{s.throttle:>5.2f} {s.brake:>5.2f} {s.steering:>6.2f}"
                )
            time.sleep(0.25)
    return 0


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="lmu_telemetry.live", description=__doc__)
    parser.add_argument("--probe", action="store_true",
                        help="print raw frames from the running game and exit")
    parser.add_argument("--reference", type=Path,
                        help="recording holding the lap to be measured against")
    parser.add_argument("--reference-lap", type=int, default=None,
                        help="lap number in that recording (default: its fastest)")
    parser.add_argument("--replay", type=Path, default=None,
                        help="recording to play back in place of live telemetry")
    parser.add_argument("--replay-lap", type=int, default=None)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="replay pace; 1.0 is real time")
    parser.add_argument("--no-window", action="store_true",
                        help="print findings only, do not open the panel")
    parser.add_argument("--position", default="top-center", choices=POSITIONS,
                        help="where the panel sits (default: top-center, which "
                             "is the only corner-free choice on a wide screen)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="size multiplier on top of the screen-derived one")
    parser.add_argument("--monitor", type=int, default=None,
                        help="which screen to put the panel on, by index "
                             "(default: whichever one the game's window is on, "
                             "falling back to the primary)")
    parser.add_argument("--screens", action="store_true",
                        help="list the screens with their indices and exit")
    parser.add_argument("--recordings", type=Path, default=default_recordings_dir(),
                        help="where to look for a reference lap when --reference "
                             "is not given (default: the curated working set, or "
                             "the telemetry folder the launcher was pointed at)")
    args = parser.parse_args(argv)

    if args.screens:
        from .screens import choose_screen, game_screen, monitors

        found = game_screen()
        for screen in monitors():
            here = "  <- the game is on this one" if screen == found else ""
            print(f"  --monitor {screen.index}   {screen.label}{here}")
        if found is None:
            print("\nthe game's window was not found, so the default is the "
                  "primary. Start the game first, or name one with --monitor.")
        else:
            print(f"\ndefault without --monitor: {choose_screen().label}")
        return 0

    if args.probe:
        return _probe()

    live = None
    if args.replay is None:
        from .sharedmem import LiveTelemetry, SharedMemoryUnavailable

        try:
            live = LiveTelemetry()
        except SharedMemoryUnavailable as exc:
            print(f"{exc}", file=sys.stderr)
            return 1

    if args.reference is not None:
        chosen, chosen_lap = args.reference, args.reference_lap
        # An explicit --reference names one lap; the driver gets that lap,
        # not a best-of-set built behind their back. None here is what tells
        # _choose_templates so, below.
        auto_found = None
    else:
        if live is None:
            parser.error("--reference is required when replaying a recording")
        found = _await_reference(live, args.recordings)
        if found is None:
            return 1
        chosen, chosen_lap = found.path, found.lap_number
        auto_found = found

    reference, model, reference_lap = _trace_of(chosen, chosen_lap)
    print(
        f"reference: {chosen.name} lap {reference_lap.number} "
        f"({reference_lap.duration_s:.3f} s)\n"
        f"{model.track_length_m / 1000:.3f} km, {len(model.corners)} corners"
    )

    if args.replay is not None:
        driven, _model, driven_lap = _trace_of(args.replay, args.replay_lap)
        print(
            f"driving:   {args.replay.name} lap {driven_lap.number} "
            f"({driven_lap.duration_s:.3f} s)"
        )
        source = _from_replay(driven, args.speed, driven_lap.number)
    else:
        source = _from_game(live)
        print("driving:   the running game")

    overlay = None
    if not args.no_window:
        from .overlay import Overlay

        overlay = Overlay(
            position=args.position, scale=args.scale, monitor=args.monitor
        )
        print(f"panel on:  {overlay.monitor.label}")

    buffer = LapBuffer(reference.grid)
    watch = CornerWatch(reference, model.corners)
    built, templates_line = _choose_templates(
        auto_found, args.recordings, live, reference, model
    )
    templates = TemplateWatch(built, float(reference.grid[-1]) + GRID_STEP_M)
    print(f"templates: {templates_line}")
    drawn_at = 0.0
    on_lap = None

    try:
        _drive(source, buffer, watch, templates, reference, overlay, drawn_at, on_lap)
    except KeyboardInterrupt:
        # Reading the game runs until stopped, and the way it is stopped is
        # Ctrl-C. A traceback there reads as a fault when it is the exit.
        print("\nstopped")
    finally:
        if overlay is not None:
            overlay.close()
    return 0


def _drive(source, buffer, watch, templates, reference, overlay, drawn_at, on_lap) -> None:
    for sample, lap in source:
        if lap != on_lap:
            # A new lap. The buffer and the watch both start again; the watch
            # keeps its reference metrics, which have not changed.
            if on_lap is not None:
                print(f"  -- lap {lap} --")
            on_lap = lap
            buffer.reset()
            watch.reset()
            templates.reset()
        buffer.add(sample)

        # An out lap or an in lap is not a lap. Said once, when it is first
        # known, so the quiet that follows has a reason attached rather than
        # looking like the tool having stopped. Done before _sound_if_due,
        # not after: on the single sample that first reports in_pits,
        # why_silent would otherwise still read None when the tone check
        # runs, and a lap that just left the racing line for the pit
        # entry would still get one last beep.
        if sample.in_pits and watch.why_silent is None:
            watch.mark_unusable("this lap used the pit lane")
            print("  -- pit lane: this lap is not being measured --")
            if overlay is not None:
                overlay.show_finding("", "out lap - not measured")

        # Read once and threaded through both the tone and the redraw below,
        # rather than read twice: templates.showing() now backs both
        # _sound_if_due and _show_template (see live.template.TemplateWatch),
        # and it must see the same "now" from both call sites in one sample
        # or the display it arbitrates could answer differently a few
        # microseconds apart for no reason but the clock having moved.
        now = time.perf_counter()
        _sound_if_due(templates, buffer, watch, sample, now)

        for finding in watch.advance(buffer):
            corner = finding.comparison.corner
            tip = finding.to_say
            # Advice first, then praise, then nothing. A corner with something
            # to change has a sentence worth more than a compliment; a corner
            # that went well should hear so rather than be met with silence,
            # which reads as "nothing was measured here".
            if tip is not None:
                said = tip.headline
            elif finding.praise is not None:
                said = finding.praise
            elif finding.advice is not None:
                said = "- (same braking as an earlier corner)"
            else:
                said = "-"
            print(
                f"  {corner.name:28s} {finding.comparison.lost_s:+.3f} s  {said}"
            )
            if overlay is not None:
                overlay.show_finding(
                    corner.name, tip.headline if tip else finding.praise
                )

        # Paced on the wall clock, not on lap time: lap time restarts at every
        # line, and a replay running at 40x would redraw 40 times as often as
        # a driver can read. Reuses the "now" read above the tone check
        # rather than reading the clock again - see the comment there.
        if overlay is not None and now - drawn_at >= 1.0 / REDRAW_HZ:
            drawn_at = now
            # Where the reference was in time when it reached here. Positive
            # means this lap took longer to get to the same piece of track.
            was = float(np.interp(sample.distance_m, reference.grid, reference.time_s))
            overlay.show_delta(sample.time_s - was)
            _show_template(overlay, templates, buffer, watch, sample, now)
            overlay.pump()


def _window_was_watched(template, buffer) -> bool:
    """Whether the buffer already held data when this window's approach began.

    Mirrors ``watch.CornerWatch._was_watched``: the overlay can be started
    while the driver is already on track, and a window whose approach began
    before ``buffer.started_m`` has nothing recorded for its opening metres.
    ``np.interp`` would hold the first sample flat *backwards* across that
    gap, and the grey-versus-coloured comparison - and the entry-speed delta
    - would be drawn from that one instant rather than from driving.

    Read off the corner's own start and ``APPROACH_M`` rather than
    ``template.start_m``: the template's start has already been wrapped into
    ``0..lap_length_m``, and a window that wraps the start/finish line has a
    true beginning that sits in the *previous* lap - which this buffer,
    reset every lap, can never have watched, however large
    ``template.start_m`` looks next to ``buffer.started_m``. Working from the
    unwrapped ``corner.start_m - APPROACH_M`` instead makes a wrapping window
    read as never watched, which is the same answer ``_was_watched`` gives a
    corner in the same position.
    """
    started = buffer.started_m
    if started is None:
        return False
    return template.corner.start_m - APPROACH_M >= max(started, 0.0)


def _show_template(overlay, templates, buffer, watch, sample, now) -> None:
    """Put the braking template up, or take it down.

    Nothing is shown on a lap that used the pit lane, by the same rule that
    silences the sentences there: an out lap is not a lap, and a template
    inviting the driver to match a qualifying brake point on cold tyres out of
    the pits is worse than no template.

    A held showing (``showing.past_corner``) is the ``TEMPLATE_HOLD_S`` grace
    period after a corner, not a fresh approach - and that corner's own
    window ends at the same ``corner.end_m`` ``CornerWatch`` completes it at,
    so the held ``Showing`` for it is what the very next redraw sees after
    ``watch.advance`` yields a finding and ``overlay.show_finding`` puts the
    sentence up. Calling ``overlay.show_template`` there would evict that
    sentence within about 67 ms of it arriving - which is what a driver
    reported as the panel "growing, shrinking and shifting". So a held
    showing is left alone while a finding is current: the corner is over,
    and the sentence is the more useful of the two to be looking at. A
    freshly armed window (``not showing.past_corner``) is never held back
    this way - see ``Overlay.show_template``'s docstring, which states the
    same rule from the other side: a window for the *next* corner still
    takes the slot back, sentence or no sentence, or an eleven-second
    sentence would swallow it. The consequence, not a defect:
    ``TEMPLATE_HOLD_S`` is visibly reachable only for a corner that produced
    no sentence.
    """
    showing = templates.showing(sample.distance_m, now)
    if showing is None or watch.why_silent is not None:
        return overlay.hide_template()

    if showing.past_corner and overlay.content == "finding":
        return

    template = showing.template
    if not _window_was_watched(template, buffer):
        return overlay.hide_template()

    try:
        driven = buffer.trace()
    except ValueError:
        return overlay.hide_template()      # fewer than two samples so far

    # Only as far as the car has come. Past that the buffer holds its last
    # sample flat, and a line drawn there is that instant repeated - which
    # would look like a driver holding a steady pedal into a corner they have
    # not reached.
    reached = int(np.searchsorted(template.offsets_m, showing.at_m, side="right"))
    upto = template.abs_m[:reached]
    own_brake = np.interp(upto, driven.grid, driven.brake)
    own_throttle = np.interp(upto, driven.grid, driven.throttle)

    entry_delta = None
    if showing.at_m >= template.entry_at_m:
        mine = float(np.interp(
            template.abs_m[
                int(np.searchsorted(template.offsets_m, template.entry_at_m))
            ],
            driven.grid, driven.speed_kmh,
        ))
        entry_delta = mine - template.entry_speed_kmh

    overlay.show_template(showing, own_brake, own_throttle, entry_delta)


def _sound_if_due(templates, buffer, watch, sample, now: float) -> None:
    """Sound the brake mark, unless this lap or this window is not watched.

    Two silences, both mirrored from the guards ``_show_template`` already
    applies to the strip - so the two can never tell different stories about
    the same window: the whole lap, by ``watch.why_silent`` (a pit-lane lap
    beeping for a strip it is not showing would be stranger still than the
    strip alone being withheld), and this one window's approach, by
    ``_window_was_watched`` (a window whose opening metres were never
    recorded is exactly the case the strip already hides for, and the tone
    is a claim about the same metres).

    Uses ``templates.due_template``/``.mark_toned`` rather than
    ``.tone_due`` directly, so a window that is due but fails either guard
    is left un-toned rather than marked and silently dropped - it stays
    armed for the rest of this lap, which never matters (both guards, once
    true, stay true for the whole lap), but it means "armed" keeps meaning
    one thing.

    ``now`` is the same read of the clock ``_drive`` passes to
    ``_show_template`` later in this same sample - not a second call to
    ``time.perf_counter()`` - because ``due_template`` is now built on
    ``TemplateWatch.showing``, the very arbitration the strip is drawn from
    (see ``live.template.TemplateWatch.due_template``). A tone and a redraw
    a few microseconds apart, asking that arbitration with two different
    clock readings, could in principle answer differently; sharing one
    reading closes that off rather than leaving it as a coincidence that
    happens not to matter yet. This is also *why* the tone can no longer be
    later than a sample: it runs off ``showing()`` every sample, not off the
    15 Hz redraw ``_show_template`` is throttled to.
    """
    template = templates.due_template(sample.distance_m, now)
    if template is None:
        return
    if watch.why_silent is not None:
        return
    if not _window_was_watched(template, buffer):
        return
    templates.mark_toned(template)
    play_brake_tone()


if __name__ == "__main__":
    sys.exit(main())
