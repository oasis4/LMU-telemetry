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

from ..core.session import Session
from ..core.track_model import build_track_model
from ..core.trace import build_trace
from .buffer import LapBuffer
from .replay import replay
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
    args = parser.parse_args(argv)

    if args.probe:
        return _probe()
    if args.reference is None:
        parser.error("--reference is required unless --probe is given")

    reference, model, reference_lap = _trace_of(args.reference, args.reference_lap)
    print(
        f"reference: {args.reference.name} lap {reference_lap.number} "
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
        from .sharedmem import LiveTelemetry, SharedMemoryUnavailable

        try:
            source = _from_game(LiveTelemetry())
        except SharedMemoryUnavailable as exc:
            print(f"{exc}", file=sys.stderr)
            return 1
        print("driving:   the running game")

    overlay = None
    if not args.no_window:
        from .overlay import Overlay

        overlay = Overlay()

    buffer = LapBuffer(reference.grid)
    watch = CornerWatch(reference, model.corners)
    drawn_at = 0.0
    on_lap = None

    try:
        _drive(source, buffer, watch, reference, overlay, drawn_at, on_lap)
    except KeyboardInterrupt:
        # Reading the game runs until stopped, and the way it is stopped is
        # Ctrl-C. A traceback there reads as a fault when it is the exit.
        print("\nstopped")
    finally:
        if overlay is not None:
            overlay.close()
    return 0


def _drive(source, buffer, watch, reference, overlay, drawn_at, on_lap) -> None:
    for sample, lap in source:
        if lap != on_lap:
            # A new lap. The buffer and the watch both start again; the watch
            # keeps its reference metrics, which have not changed.
            if on_lap is not None:
                print(f"  -- lap {lap} --")
            on_lap = lap
            buffer.reset()
            watch.reset()
        buffer.add(sample)

        for finding in watch.advance(buffer):
            corner = finding.comparison.corner
            tip = finding.to_say
            note = ""
            if tip is None and finding.advice is not None:
                note = f"  (same braking as an earlier corner)"
            print(
                f"  {corner.name:28s} {finding.comparison.lost_s:+.3f} s  "
                f"{tip.headline if tip else '-'}{note}"
            )
            if overlay is not None:
                overlay.show_finding(corner.name, tip.headline if tip else None)

        # Paced on the wall clock, not on lap time: lap time restarts at every
        # line, and a replay running at 40x would redraw 40 times as often as
        # a driver can read.
        now = time.perf_counter()
        if overlay is not None and now - drawn_at >= 1.0 / REDRAW_HZ:
            drawn_at = now
            # Where the reference was in time when it reached here. Positive
            # means this lap took longer to get to the same piece of track.
            was = float(np.interp(sample.distance_m, reference.grid, reference.time_s))
            overlay.show_delta(sample.time_s - was)
            overlay.pump()


if __name__ == "__main__":
    sys.exit(main())
