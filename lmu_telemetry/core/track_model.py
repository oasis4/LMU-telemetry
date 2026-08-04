"""The reference model: one corner list per track, shared by every lap.

Detecting corners per lap cannot work - measured on the corpus, the same track
yields 9 to 13 corners depending on the line driven. So corners are determined
once per track identity from the median racing line of every clean lap, and
every lap of every driver then refers to that one list. Comparisons are
consistent by construction rather than by convention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

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
