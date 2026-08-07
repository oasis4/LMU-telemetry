"""Finding the lap to be measured against, from the track the driver is on.

The game says which circuit it has loaded. The recordings say which circuit
they were driven on. Matching the two means the overlay can be started once,
before the session, and pick up whatever track is loaded - rather than being
told a filename and a lap number every time.

Names are matched loosely on purpose. The game reports a track name and so
does the recording, and they agree in every case seen so far, but they come
from different places in the same product and a shared prefix is as much as
can be relied on: "Monza" against "Autodromo Nazionale Monza" is the same
circuit and a strict comparison would say otherwise.

What is *not* loose is the choice among the laps that match. It is the
quickest clean lap, by the same definition of clean the rest of the package
uses - a lap that cut the track or came out of the pits is not a reference,
however fast it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core.quality import clean_laps
from ..core.session import Session


@dataclass(frozen=True)
class Reference:
    """The lap picked, and enough about it to say so out loud."""

    path: Path
    lap_number: int
    duration_s: float
    track: str

    @property
    def label(self) -> str:
        return (
            f"{self.path.name} lap {self.lap_number} "
            f"({self.duration_s:.3f} s) at {self.track}"
        )


def normalise(name: str) -> str:
    """A track name reduced to what two sources can be expected to agree on."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def same_track(a: str, b: str) -> bool:
    """Whether two names denote one circuit.

    Containment rather than equality: the game and the recordings both name
    the circuit, but one may carry the full title where the other carries the
    common one. Empty names never match anything - an unnamed track is not a
    match for every track.
    """
    left, right = normalise(a), normalise(b)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def find_reference(recordings: Path, track: str) -> "Reference | None":
    """The quickest clean lap recorded on *track*, or None if there is none.

    Every recording in the directory is opened. That is a second or two for a
    corpus of a few hundred, and it happens once when a session loads - the
    alternative, trusting the filename, breaks the moment a file is renamed
    and fails silently rather than loudly.

    A recording that cannot be opened or read is skipped rather than raising.
    One damaged file in a directory is not a reason to leave the driver with
    no reference at all.
    """
    best: Reference | None = None
    for path in sorted(Path(recordings).glob("*.duckdb")):
        try:
            with Session.open(path) as session:
                if not same_track(session.info.track, track):
                    continue
                for lap in clean_laps(session):
                    if lap.duration_s is None:
                        continue
                    if best is None or lap.duration_s < best.duration_s:
                        best = Reference(
                            path=path,
                            lap_number=lap.number,
                            duration_s=lap.duration_s,
                            track=session.info.track,
                        )
        except Exception:
            # Damaged, half-written, or not a recording at all. Skipping one
            # file is better than denying the driver every other lap they have.
            continue
    return best
