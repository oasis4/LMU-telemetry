"""The reference model: one corner list per track, shared by every lap.

Detecting corners per lap cannot work - measured on the corpus, the same track
yields 9 to 13 corners depending on the line driven. So corners are determined
once per track identity from the median racing line of every clean lap, and
every lap of every driver then refers to that one list. Comparisons are
consistent by construction rather than by convention.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import geometry
from .corners import Corner, detect_corners
from .naming import apply_names
from .quality import clean_laps, lap_line_on_grid


@dataclass(frozen=True)
class TrackKey:
    """What makes two sessions the same track.

    Identity used to include the measured length rounded to a fixed grid, on
    the theory that lap-to-lap measurement scatter should not split a track
    while two layouts sharing a name should still separate. That does not
    work: any fixed grid has boundaries, and a cluster of near-identical
    measurements that straddles one gets split into two identities anyway -
    on the corpus, one Monza session measuring 5773.812 m bucketed one grid
    cell away from the other 22 sessions' 5775-5780 m, splitting a single
    134-lap track into two, with the 1-lap outlier's model shadowing the
    correct one. Widening the bucket only moves the boundary; it does not
    remove it.

    So identity is name plus layout only. LMU already reports ``TrackLayout``
    in the file metadata, which is what actually distinguishes two layouts
    sharing a name - the length was only ever a proxy for that. Length
    agreement across sessions is now verified in ``build_track_model``, the
    only place that sees every session of a track at once and can therefore
    tell scatter apart from a genuine layout collision.
    """

    track: str
    layout: str

    @classmethod
    def of(cls, session) -> "TrackKey | None":
        length = session.track_length_m
        if length is None:
            return None
        info = session.info
        return cls(
            track=info.track,
            layout=info.layout or info.track,
        )

    def slug(self) -> str:
        """A filesystem-safe identifier, used as the cache filename.

        Each field is slugified separately and joined with a double hyphen.
        Slugifying the concatenation instead would let ("A", "B-C") and
        ("A-B", "C") collide onto one filename, silently merging two tracks'
        cached models. A slugified field never contains a double hyphen, so
        this joiner is unambiguous.
        """
        parts = (self.track, self.layout)
        return "--".join(
            re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-").lower() for part in parts
        )


def reference_line(lines) -> tuple[np.ndarray, np.ndarray]:
    """The median racing line over many laps, sample by sample.

    The median rather than the mean: one wild lap should not drag the
    reference geometry with it.

    **Every line must already be in one common frame.** A per-sample median
    across lines that sit in different coordinate frames is not a racing line
    at all - it picks, for each sample, whichever lap happens to be shifted
    into the middle, so a lap with an outlying frame is structurally excluded
    from contributing rather than outvoted. That is the exact opposite of what
    the median is here for. ``build_track_model`` guarantees the common frame
    by choosing one projection origin for the whole track up front.
    """
    lines = list(lines)
    if not lines:
        raise ValueError("need at least one lap to build a reference line")
    lengths = {len(x) for x, _ in lines} | {len(y) for _, y in lines}
    if len(lengths) != 1:
        raise ValueError(f"lines differ in length: {sorted(lengths)}")
    xs = np.median(np.array([x for x, _ in lines], dtype=np.float64), axis=0)
    ys = np.median(np.array([y for _, y in lines], dtype=np.float64), axis=0)
    return xs, ys


#: Below this many clean laps the model is served with a warning attached.
MIN_CONFIDENT_LAPS = 3

#: Version of the pipeline a cached model was built by.
#:
#: A cached model is a *measurement*, not a document: it is only meaningful
#: together with the code that produced it. Nothing in the stored fields
#: records which detection constants, which smoothing window or which
#: projection were in force, so without a stamp load_model would happily go on
#: serving a model built under rules that no longer exist - and the staler it
#: got, the less anything would notice.
#:
#: Raise this whenever a change moves where corners land: a detection
#: constant, a smoothing window, the projection, the wrap handling. A cache
#: written by any other version is discarded and rebuilt, which costs one
#: rebuild and buys the guarantee that a served model matches this code.
#:
#: 3: the projection origin is stored, so a lap drawn beside the line can be
#: put in the same frame without reloading the sessions it was measured from.
#:
#: 2: the reference line is stored. A version-1 model has no line, and
#: ``from_dict`` would hand one back with ``line_x=None`` - a model that looks
#: complete and cannot be drawn. Discarding those is the point of the stamp.
MODEL_FORMAT_VERSION = 3

#: Maximum fractional deviation a session's measured length may have from the
#: median before it is treated as a different layout rather than measurement
#: scatter. 2%: comfortably wider than the lap-to-lap scatter seen on the
#: corpus (well under 0.1%), comfortably narrower than what two genuinely
#: different layouts sharing a name would produce.
LENGTH_AGREEMENT_TOLERANCE = 0.02


#: Centimetres. The reference line is stored to this precision because that is
#: about what the recording supports, and because it is drawn at a few hundred
#: pixels across - two decimal places is already far finer than any screen.
LINE_PRECISION_M = 2


@dataclass(frozen=True)
class TrackModel:
    key: TrackKey
    track_length_m: float
    corners: list[Corner]
    closure_deg: float
    lap_count: int
    confident: bool
    warning: str | None
    #: The median racing line, in metres, one point per grid sample. This is
    #: the shape a map is drawn from - measured, not reconstructed from corner
    #: radii and headings, which is a drawing of what the detector believed
    #: rather than of where the car went.
    line_x: np.ndarray | None = None
    line_y: np.ndarray | None = None
    #: The projection origin the line was measured in, as ``(lat, lon)``.
    #:
    #: Stored because anything drawn beside the line - an individual lap's own
    #: path, say - has to be projected in the same frame or the two will not
    #: overlay. ``track_origin`` is deterministic for a given set of sessions,
    #: but a cached model is served without those sessions being loaded.
    origin: tuple[float, float] | None = None

    def to_dict(self) -> dict:
        return {
            "format_version": MODEL_FORMAT_VERSION,
            "track": self.key.track,
            "layout": self.key.layout,
            "track_length_m": self.track_length_m,
            "closure_deg": self.closure_deg,
            "lap_count": self.lap_count,
            "confident": self.confident,
            "warning": self.warning,
            "line_x": None if self.line_x is None
            else [round(float(v), LINE_PRECISION_M) for v in self.line_x],
            "line_y": None if self.line_y is None
            else [round(float(v), LINE_PRECISION_M) for v in self.line_y],
            "origin": None if self.origin is None else list(self.origin),
            "corners": [
                {
                    "index": c.index, "name": c.name,
                    "start_m": c.start_m, "apex_m": c.apex_m, "end_m": c.end_m,
                    "radius_m": c.radius_m, "heading_deg": c.heading_deg,
                    "direction": c.direction,
                }
                for c in self.corners
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TrackModel":
        line_x, line_y = data.get("line_x"), data.get("line_y")
        return cls(
            key=TrackKey(data["track"], data["layout"]),
            track_length_m=float(data["track_length_m"]),
            corners=[Corner(**c) for c in data["corners"]],
            closure_deg=float(data["closure_deg"]),
            lap_count=int(data["lap_count"]),
            confident=bool(data["confident"]),
            warning=data.get("warning"),
            line_x=None if line_x is None else np.asarray(line_x, dtype=np.float64),
            line_y=None if line_y is None else np.asarray(line_y, dtype=np.float64),
            origin=None if data.get("origin") is None else tuple(data["origin"]),
        )


def _lap_line(session, lap, track_length_m, origin):
    """One lap's racing line on the track's common grid, or None."""
    line, _reason = lap_line_on_grid(session, lap, track_length_m, origin)
    return line


def track_origin(sessions) -> "tuple[float, float]":
    """One projection origin for the whole track: the bounding box midpoint.

    Chosen before any lap is projected, because every lap of the track has to
    land in the same frame for :func:`reference_line` to mean anything.

    The midpoint of the combined bounding box rather than a mean position: a
    mean is time-weighted, so it drifts with where the car spent its time -
    which is exactly what differs between laps and between sessions. The
    bounding box depends only on how far the *track* reaches in each
    direction, which is a property of the circuit and identical for every lap
    of it. Nothing downstream cares where the origin sits (curvature, corner
    detection and the closure integral are all translation-invariant); what
    they care about is that it is the same one for every lap, and that
    rebuilding the same track tomorrow picks the same one again.
    """
    lo_lat = lo_lon = float("inf")
    hi_lat = hi_lon = float("-inf")
    for session in sessions:
        lat = session.file.channel("GPS Latitude")
        lon = session.file.channel("GPS Longitude")
        if len(lat) == 0 or len(lon) == 0:
            continue
        lo_lat, hi_lat = min(lo_lat, float(lat.min())), max(hi_lat, float(lat.max()))
        lo_lon, hi_lon = min(lo_lon, float(lon.min())), max(hi_lon, float(lon.max()))
    if lo_lat == float("inf"):
        # No positions anywhere. There is nothing to project, but returning a
        # usable origin keeps the caller's lap loop on one code path; every
        # lap will be rejected for want of samples regardless.
        return (0.0, 0.0)
    return ((lo_lat + hi_lat) / 2.0, (lo_lon + hi_lon) / 2.0)


def build_track_model(sessions) -> "TrackModel | None":
    """Build one corner model from every clean lap of *sessions*.

    Returns ``None`` rather than a model built from unusable data: inventing
    geometry from a single crash lap is precisely the failure this design
    exists to prevent.
    """
    sessions = list(sessions)
    keys = {TrackKey.of(s) for s in sessions} - {None}
    if not keys:
        # No session established a track length (no complete lap anywhere) -
        # there is no identity to build against, which is the "none at all"
        # case: return None rather than raising.
        return None
    if len(keys) != 1:
        raise ValueError(f"sessions span {len(keys)} track identities, expected 1")
    key = keys.pop()

    lengths = [s.track_length_m for s in sessions if s.track_length_m is not None]
    track_length = float(np.median(lengths))

    # TrackKey no longer carries the length, so this is the only place that
    # ever sees every session of a track at once - the one place a genuine
    # layout collision (two different circuits sharing a name) can actually
    # be told apart from ordinary lap-to-lap measurement scatter. Scatter on
    # the corpus is well under 0.1%; two distinct layouts differ by far more
    # than LENGTH_AGREEMENT_TOLERANCE, so this raises loudly instead of
    # silently splitting - or silently averaging together - a track.
    for s in sessions:
        if s.track_length_m is None:
            continue
        deviation = abs(s.track_length_m - track_length) / track_length
        if deviation > LENGTH_AGREEMENT_TOLERANCE:
            raise ValueError(
                f"session length {s.track_length_m} m disagrees with the "
                f"median {track_length} m by more than "
                f"{LENGTH_AGREEMENT_TOLERANCE:.0%}; sessions may span two "
                f"different layouts sharing one name"
            )

    # One frame for the whole track, fixed before the first lap is projected.
    origin = track_origin(sessions)

    lines = []
    for session in sessions:
        for lap in clean_laps(session):
            line = _lap_line(session, lap, track_length, origin)
            if line is not None:
                lines.append(line)
    if not lines:
        return None

    x, y = reference_line(lines)
    grid = geometry.grid_for(track_length)
    kappa = geometry.curvature(x, y)
    turn = geometry.turn_rad(x, y)
    closure = geometry.heading_change_deg(turn)
    # Named here rather than by the caller. A model that leaves
    # build_track_model as T1..Tn is persisted that way by save_model and
    # comes back that way from load_model, so a curated name applied
    # afterwards would exist only in whichever caller remembered to apply it.
    # Naming is part of what a TrackModel *is*, so it happens once, here.
    corners = apply_names(detect_corners(kappa, grid, turn), key.track)

    confident = len(lines) >= MIN_CONFIDENT_LAPS
    warning = None
    if not confident:
        warning = (
            f"built from only {len(lines)} clean lap(s); "
            f"corner positions may shift as more laps are recorded"
        )
    return TrackModel(
        key=key,
        track_length_m=track_length,
        corners=corners,
        closure_deg=closure,
        lap_count=len(lines),
        confident=confident,
        warning=warning,
        line_x=x,
        line_y=y,
        origin=origin,
    )


def save_model(model: TrackModel, cache_dir) -> Path:
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{model.key.slug()}.json"
    path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return path


def load_model(key: TrackKey, cache_dir) -> "TrackModel | None":
    """The cached model for *key*, or None if there is no usable one.

    A model stamped with any version other than this pipeline's is treated as
    absent, so the caller rebuilds it. Returning None rather than raising is
    deliberate: a stale cache is a cache miss, not an error - the caller
    already has to handle "not built yet", and this is that same case.
    """
    path = Path(cache_dir) / f"{key.slug()}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != MODEL_FORMAT_VERSION:
        return None
    return TrackModel.from_dict(data)
