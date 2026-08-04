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
#:
#: This is an upper bound only - see :func:`_tolerances`. It says nothing
#: about how far apart a table's own entries are, and several shipped
#: clusters are far tighter than 150 m: Monza's Variante del Rettifilo is two
#: entries 40 m apart, Le Mans' Ford Chicane the same.
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


def _tolerances(entries: "tuple[CornerName, ...]") -> list[float]:
    """How far each entry's apex may drift before the match stops meaning much.

    ``NAME_SANITY_M`` alone ignores how far apart the table's own entries are,
    and a chicane's entries sit far closer together than that: Monza's
    Variante del Rettifilo is 40 m from entry 1 to entry 2. A 150 m allowance
    inside a 40 m cluster is not a sanity check at all - a detected apex could
    sit nearer to the neighbouring entry than to its own and still be
    accepted, which is precisely the mix-up the check exists to catch.

    So each entry is additionally held to half the distance to its nearest
    neighbour in the table. Half, because that is the point at which a
    detected apex stops being closer to its own entry than to the next one:
    beyond it, the order-based pairing no longer has anything supporting it.
    """
    out = []
    for i, entry in enumerate(entries):
        neighbours = entries[max(i - 1, 0) : i] + entries[i + 1 : i + 2]
        gaps = [abs(entry.apex_m - other.apex_m) for other in neighbours]
        limit = min(gaps) / 2.0 if gaps else NAME_SANITY_M
        out.append(min(NAME_SANITY_M, limit))
    return out


def apply_names(corners: list[Corner], track: str) -> list[Corner]:
    """Return *corners* with curated names, matched to the table by order.

    A name table lists a track's corners in track order, and
    ``detect_corners`` returns corners in track order too, so the Nth
    detected corner is the Nth named corner - provided the table still
    describes this geometry. If the corner counts disagree, or a paired
    apex has drifted further than legitimate drift explains, every corner
    keeps its generic name rather than risking a half-correct naming.

    How much drift counts as legitimate is per entry, not one figure for the
    whole table: see :func:`_tolerances`.
    """
    entries = load_names(track)
    if not entries:
        return list(corners)
    if len(entries) != len(corners):
        return list(corners)
    for entry, corner, tolerance in zip(entries, corners, _tolerances(entries)):
        if abs(entry.apex_m - corner.apex_m) > tolerance:
            return list(corners)
    return [replace(corner, name=entry.name) for entry, corner in zip(entries, corners)]
