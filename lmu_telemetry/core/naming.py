"""Curated corner names layered over the detected geometry.

Corner count is a naming convention, not a physical fact. Portimao's official
15 turns do not map one-to-one onto geometrically distinct arcs: the 190-degree
horseshoe at 3428 m is one continuous arc that the circuit map numbers as two
turns. Reconciling the two belongs here, not in the detector - the detector
must never invent a boundary the geometry does not contain.

A track with no table keeps the generic T1..Tn names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from .corners import Corner

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tracks"

#: How far a detected apex may sit from its table entry's apex_m before the
#: match is treated as a structural mismatch (a corner split or merged since
#: the table was curated) rather than legitimate drift. Measured apex drift
#: across clean-lap set changes is up to 46 m (Algarve); a wrongly split or
#: merged corner shifts an apex by several hundred metres. 150 m sits
#: comfortably between the two, so it separates legitimate drift from a
#: genuine structural mismatch.
NAME_SANITY_M = 150.0


@dataclass(frozen=True)
class CornerName:
    """One entry of a curated name table."""

    apex_m: float
    name: str
    turns: str


def _slug(track: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", track).strip("-").lower()


@lru_cache(maxsize=None)
def load_names(track: str) -> "tuple[CornerName, ...] | None":
    path = _DATA_DIR / f"{_slug(track)}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        CornerName(apex_m=float(e["apex_m"]), name=str(e["name"]), turns=str(e["turns"]))
        for e in data.get("corners", ())
    )


def apply_names(corners: list[Corner], track: str) -> list[Corner]:
    """Return *corners* with curated names, matched to the table by order.

    A name table lists a track's corners in track order, and
    ``detect_corners`` returns corners in track order too, so the Nth
    detected corner is the Nth named corner - provided the table still
    describes this geometry. If the corner counts disagree, or a paired
    apex has drifted further than legitimate drift explains, every corner
    keeps its generic name rather than risking a half-correct naming.
    """
    entries = load_names(track)
    if not entries:
        return list(corners)
    if len(entries) != len(corners):
        return list(corners)
    for entry, corner in zip(entries, corners):
        if abs(entry.apex_m - corner.apex_m) > NAME_SANITY_M:
            return list(corners)
    return [replace(corner, name=entry.name) for entry, corner in zip(entries, corners)]
