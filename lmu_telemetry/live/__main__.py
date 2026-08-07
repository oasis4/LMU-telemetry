"""Run the corner overlay.

    python -m lmu_telemetry.live --reference LAP.duckdb --reference-lap 2 \
                                 --replay  LAP.duckdb --replay-lap 1

The reference lap is built through the ordinary pipeline, so the corner list
and the distance grid the overlay works on are the same objects the browser
view works on - not a second copy that could drift from it.

Only ``--replay`` is wired up as a source today. The live one arrives with
``live.sharedmem``, which needs the rF2 Shared Memory Map Plugin installed
into Le Mans Ultimate; see the plan under docs/superpowers/plans/.
"""

from __future__ import annotations

import argparse
import sys
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


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(prog="lmu_telemetry.live", description=__doc__)
    parser.add_argument("--reference", type=Path, required=True,
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

    if args.replay is None:
        parser.error(
            "--replay is required: the live shared-memory source is not built "
            "yet. It needs rF2SharedMemoryMapPlugin64.dll in <LMU>\\Bin64\\Plugins\\."
        )

    reference, model, reference_lap = _trace_of(args.reference, args.reference_lap)
    driven, _model, driven_lap = _trace_of(args.replay, args.replay_lap)
    print(
        f"reference: {args.reference.name} lap {reference_lap.number} "
        f"({reference_lap.duration_s:.3f} s)\n"
        f"driving:   {args.replay.name} lap {driven_lap.number} "
        f"({driven_lap.duration_s:.3f} s)\n"
        f"{model.track_length_m / 1000:.3f} km, {len(model.corners)} corners"
    )

    overlay = None
    if not args.no_window:
        from .overlay import Overlay

        overlay = Overlay()

    buffer = LapBuffer(reference.grid)
    watch = CornerWatch(reference, model.corners)
    drawn_at = -1.0

    for sample in replay(driven, speed=args.speed):
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

        if overlay is not None and sample.time_s - drawn_at >= 1.0 / REDRAW_HZ:
            drawn_at = sample.time_s
            # Where the reference was in time when it reached here. Positive
            # means this lap took longer to get to the same piece of track.
            was = float(np.interp(sample.distance_m, reference.grid, reference.time_s))
            overlay.show_delta(sample.time_s - was)
            overlay.pump()

    print(f"lap done: {driven_lap.duration_s - reference_lap.duration_s:+.3f} s")
    if overlay is not None:
        overlay.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
