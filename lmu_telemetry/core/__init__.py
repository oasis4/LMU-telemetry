"""Reading a Le Mans Ultimate recording, and comparing two laps from it.

The route through this package, in the order the data moves:

    Session.open(path)              one recording
      .laps                         complete laps, from the game's Lap events
      .fastest_lap                  the quickest that is a lap time at all
    build_track_model(sessions)     one circuit's geometry and corner list,
                                    from the clean laps of any number of
                                    sessions of the same track and layout
    build_trace(session, lap, L)    one lap, every channel on the 2 m grid
    delta_s(reference, other)       seconds one lap is behind the other,
                                    at every point round the circuit
    compare_corners(a, b, corners)  what differed in each corner, and what
                                    it cost

Both sides of a comparison are measured against one corner list and one
distance grid. That is the whole point of the reference model, and it is why
``compare_corners`` takes the corners as an argument rather than deriving them
per lap: derived per lap, two drivers are compared against two different
definitions of the same corner.
"""

from .coaching import (
    Advice,
    CornerComparison,
    Difference,
    advice,
    advise_on,
    biggest_losses,
    compare_corners,
    corner_comparison,
)
from .blocks import (
    Block,
    BlockChoice,
    IdealLap,
    Seam,
    ideal_lap,
    split_into_blocks,
)
from .corners import Corner, detect_corners
from .delta import delta_s, time_lost_over
from .laps import Lap, NoLapDataError, segment_laps
from .metrics import CornerMetrics, corner_metrics, lap_metrics
from .naming import CornerName, apply_names, load_names
from .quality import LapQuality, assess_lap, clean_laps
from .session import Session, SessionInfo
from .track_model import (
    TrackKey,
    TrackModel,
    build_track_model,
    load_model,
    save_model,
)
from .trace import LapTrace, TraceError, build_trace

__all__ = [
    "Advice",
    "Block",
    "BlockChoice",
    "Corner",
    "CornerComparison",
    "CornerMetrics",
    "CornerName",
    "Difference",
    "IdealLap",
    "Lap",
    "LapQuality",
    "LapTrace",
    "NoLapDataError",
    "Seam",
    "Session",
    "SessionInfo",
    "TraceError",
    "TrackKey",
    "TrackModel",
    "advice",
    "advise_on",
    "apply_names",
    "assess_lap",
    "biggest_losses",
    "build_trace",
    "build_track_model",
    "clean_laps",
    "compare_corners",
    "corner_comparison",
    "corner_metrics",
    "delta_s",
    "detect_corners",
    "ideal_lap",
    "lap_metrics",
    "load_model",
    "load_names",
    "save_model",
    "segment_laps",
    "split_into_blocks",
    "time_lost_over",
]
