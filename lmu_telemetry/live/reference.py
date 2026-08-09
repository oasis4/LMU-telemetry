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

#: How far a recording's measured length may sit from the game's own before it
#: is taken to be a different layout of the same circuit.
#:
#: The name is not enough. Monza's full course and its Curva Grande variant
#: both report the track name "Autodromo Nazionale Monza", and the game says
#: only that name - there is no layout anywhere in its shared memory. So the
#: length is the only thing that tells them apart, and getting it wrong is not
#: a near miss: a reference from the wrong variant is 40 m and two corners
#: away, and every delta measured against it is nonsense.
#:
#: Worse, the failure favours itself. The shorter layout is quicker *because*
#: it is shorter, so "the quickest clean lap at Monza" picks it every time.
#:
#: The number is measured, not chosen. Across the corpus this was written
#: against, one layout's recorded length varies by at most 6.3 m between
#: sessions, and the closest two layouts of one circuit are 29.3 m apart -
#: Monza's pair. Fifteen is twice the first and half the second.
LAYOUT_TOLERANCE_M = 15.0


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


def same_class(recorded: str, driven: str) -> bool:
    """Whether two class names denote the same machinery.

    Loose in the same way and for the same reason as :func:`same_track`: the
    game and the recordings both name the class but come from different places
    in one product, so "GT3" and "LMGT3" are one class.

    Either being unknown is a yes - a recording that never stated its class is
    not evidence of a different one. A stated class that matches nothing is
    not: that is the Hypercar case, and it is worth nine seconds a lap.
    """
    if not recorded or not driven:
        return True
    left, right = normalise(recorded), normalise(driven)
    return left == right or left in right or right in left


def same_layout(recorded_m: "float | None", loaded_m: "float | None") -> bool:
    """Whether two measured lengths are the same layout of a circuit.

    Either being unknown is a yes. A recording that never measured its length
    is not evidence of a different layout, and refusing it would leave a
    driver with no reference over a fact nobody asserted.
    """
    if not recorded_m or not loaded_m:
        return True
    return abs(recorded_m - loaded_m) <= LAYOUT_TOLERANCE_M


def find_reference(
    recordings: Path,
    track: str,
    length_m: "float | None" = None,
    car_class: "str | None" = None,
) -> "Reference | None":
    """The quickest clean lap recorded on *track*, or None if there is none.

    Every recording in the directory is opened. Measured against the 239
    recordings on the machine this was written on, that is 7 to 8 seconds, and
    it happens once while the driver is still in the garage. The alternative,
    trusting the filename, breaks the moment a file is renamed and fails
    silently rather than loudly - which is the worse trade at any price.

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
                if not same_layout(session.track_length_m, length_m):
                    continue
                if not same_class(session.info.car_class, car_class):
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
