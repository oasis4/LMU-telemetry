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
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .corners import Corner

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tracks"

#: An entry only claims a corner whose apex is within this distance of it.
#: Beyond that the corner keeps its generic name rather than borrowing a
#: neighbour's, which would silently mislabel a shifted apex.
MATCH_TOLERANCE_M = 60.0


def _slug(track: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", track).strip("-").lower()


@lru_cache(maxsize=None)
def load_names(track: str) -> "tuple[dict, ...] | None":
    path = _DATA_DIR / f"{_slug(track)}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(data.get("corners", ()))


def apply_names(corners: list[Corner], track: str) -> list[Corner]:
    """Return *corners* with curated names where one matches."""
    entries = load_names(track)
    if not entries:
        return list(corners)
    named = []
    for corner in corners:
        best = min(entries, key=lambda e: abs(float(e["apex_m"]) - corner.apex_m))
        if abs(float(best["apex_m"]) - corner.apex_m) <= MATCH_TOLERANCE_M:
            named.append(replace(corner, name=str(best["name"])))
        else:
            named.append(corner)
    return named
