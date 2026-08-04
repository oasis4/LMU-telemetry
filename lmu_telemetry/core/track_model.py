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
from .quality import clean_laps

#: Track length is bucketed to this resolution before it enters the identity,
#: so lap-to-lap scatter (Le Mans: 13619.4-13621.8 m) does not split a track
#: while genuinely different layouts still separate.
LENGTH_BUCKET_M = 10


@dataclass(frozen=True)
class TrackKey:
    """What makes two sessions the same track.

    The name alone is not enough: a circuit can ship several layouts under one
    name. The measured length separates them.
    """

    track: str
    layout: str
    length_bucket_m: int

    @classmethod
    def of(cls, session) -> "TrackKey | None":
        length = session.track_length_m
        if length is None:
            return None
        info = session.info
        return cls(
            track=info.track,
            layout=info.layout or info.track,
            length_bucket_m=int(round(length / LENGTH_BUCKET_M) * LENGTH_BUCKET_M),
        )

    def slug(self) -> str:
        """A filesystem-safe identifier, used as the cache filename.

        Each field is slugified separately and joined with a double hyphen.
        Slugifying the concatenation instead would let ("A", "B-C") and
        ("A-B", "C") collide onto one filename, silently merging two tracks'
        cached models. A slugified field never contains a double hyphen, so
        this joiner is unambiguous.
        """
        parts = (self.track, self.layout, str(self.length_bucket_m))
        return "--".join(
            re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-").lower() for part in parts
        )


def reference_line(lines) -> tuple[np.ndarray, np.ndarray]:
    """The median racing line over many laps, sample by sample.

    The median rather than the mean: one wild lap should not drag the
    reference geometry with it.
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


@dataclass(frozen=True)
class TrackModel:
    key: TrackKey
    track_length_m: float
    corners: list[Corner]
    closure_deg: float
    lap_count: int
    confident: bool
    warning: str | None

    def to_dict(self) -> dict:
        return {
            "track": self.key.track,
            "layout": self.key.layout,
            "length_bucket_m": self.key.length_bucket_m,
            "track_length_m": self.track_length_m,
            "closure_deg": self.closure_deg,
            "lap_count": self.lap_count,
            "confident": self.confident,
            "warning": self.warning,
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
        return cls(
            key=TrackKey(data["track"], data["layout"], int(data["length_bucket_m"])),
            track_length_m=float(data["track_length_m"]),
            corners=[Corner(**c) for c in data["corners"]],
            closure_deg=float(data["closure_deg"]),
            lap_count=int(data["lap_count"]),
            confident=bool(data["confident"]),
            warning=data.get("warning"),
        )


def _lap_line(session, lap, track_length_m):
    """One lap's racing line on the track's common grid, or None."""
    lat = session.lap_channel(lap, "GPS Latitude")
    lon = session.lap_channel(lap, "GPS Longitude")
    dist = session.lap_channel(lap, "Lap Dist")
    n = min(len(lat), len(lon), len(dist))
    if n < 100:
        return None
    x, y = geometry.project_enu(lat[:n], lon[:n])
    order = np.argsort(dist[:n])
    d = dist[:n][order]
    keep = np.concatenate(([True], np.diff(d) > 1e-6))
    d = d[keep]
    if len(d) < 50 or d[-1] - d[0] < track_length_m * 0.9:
        return None
    return (
        geometry.resample_to_grid(d, x[order][keep], track_length_m),
        geometry.resample_to_grid(d, y[order][keep], track_length_m),
    )


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

    lines = []
    for session in sessions:
        for lap in clean_laps(session):
            line = _lap_line(session, lap, track_length)
            if line is not None:
                lines.append(line)
    if not lines:
        return None

    x, y = reference_line(lines)
    grid = geometry.grid_for(track_length)
    kappa = geometry.curvature(x, y)
    closure = geometry.heading_change_deg(kappa, grid)
    corners = detect_corners(kappa, grid)

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
    )


def save_model(model: TrackModel, cache_dir) -> Path:
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{model.key.slug()}.json"
    path.write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    return path


def load_model(key: TrackKey, cache_dir) -> "TrackModel | None":
    path = Path(cache_dir) / f"{key.slug()}.json"
    if not path.is_file():
        return None
    return TrackModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
