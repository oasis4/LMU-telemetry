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
    #: Who drove it, from the recording's own metadata. Defaulted so every
    #: existing construction keeps working, but in practice always filled:
    #: a folder can hold more than one driver's laps - this one holds two -
    #: and "the quickest clean lap here" will pick the quicker driver every
    #: time, silently. That is usually what is wanted and was never what was
    #: said, and a driver who cannot see whose line they are chasing has no
    #: way to tell a good reference from a wrong one.
    driver: str = ""
    #: The recording's own timestamp, verbatim, e.g.
    #: ``2026-03-28T17_02_56Z``. Carried rather than re-read because the scan
    #: has the metadata open anyway and the panel would otherwise have to
    #: reopen the file to print a date.
    recorded_at: str = ""
    #: Fuel in the tank at the lap's start, in litres, or None where the
    #: recording did not store the channel. Read for the chosen reference
    #: only - see :func:`fuel_at_lap_start` - never during the scan.
    fuel_l: "float | None" = None

    @property
    def label(self) -> str:
        return (
            f"{self.path.name} lap {self.lap_number} "
            f"({self.duration_s:.3f} s) at {self.track}"
        )


def lap_time(seconds: float) -> str:
    """A lap time as a driver reads one: ``1:50.700``, not ``110.700 s``."""
    return f"{int(seconds // 60)}:{seconds % 60:06.3f}"


def _short_date(recorded_at: str) -> str:
    """``2026-03-28T17_02_56Z`` as ``28.03.26``, or "" if it is not a date.

    Day first, because the driver reading it is German and the panel is the
    one place in this package a date is read at a glance rather than sorted.
    """
    date = (recorded_at or "").split("T")[0]
    parts = date.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return ""
    year, month, day = parts
    return f"{day}.{month}.{year[-2:]}"


def headline(reference: "Reference", contributing_laps: int = 1) -> str:
    """One line naming the lap being measured against.

    Who drove it, when, how much fuel it carried and what it took. The driver
    asked for exactly these four after a session spent unable to tell whether
    the reference was a team-mate's qualifying run or their own race lap -
    the fuel load is what separates those two, and nothing on screen had ever
    said. Anything the recording did not store is left out rather than shown
    empty: a field reading "-" invites the driver to wonder what went wrong
    with it mid-corner.

    *contributing_laps* is how many distinct laps the strips were drawn from.
    Said only when it is more than one, because "1 lap" is the ordinary case
    and would just be noise on every line.
    """
    fields = [
        reference.driver,
        _short_date(reference.recorded_at),
        "" if reference.fuel_l is None else f"{reference.fuel_l:.0f} L",
        lap_time(reference.duration_s),
    ]
    if contributing_laps > 1:
        fields.append(f"+{contributing_laps - 1} laps")
    return "  ".join(field for field in fields if field)


def describe(path: Path, lap_number: int, contributing_laps: int = 1) -> str:
    """:func:`headline` for one recorded lap, read from the file itself.

    Used for both ways a reference is arrived at - the automatic scan and an
    explicit ``--reference`` - rather than formatting the scan's own
    ``Reference`` in one case and something else in the other. The scan
    already knows most of this and re-reading it costs one file open at
    startup, against hundreds the scan has just done; one code path is worth
    more than that, because two would let the panel describe the same lap
    differently depending on how it was chosen.

    Returns "" when the file or the lap cannot be read. The panel then shows
    no reference line rather than a line saying nothing.
    """
    try:
        with Session.open(path) as session:
            lap = next((l for l in session.laps if l.number == lap_number), None)
            if lap is None or lap.duration_s is None:
                return ""
            found = Reference(
                path=path,
                lap_number=lap.number,
                duration_s=lap.duration_s,
                track=session.info.track,
                driver=session.info.driver,
                recorded_at=session.info.recorded_at,
                fuel_l=_fuel_at(session, lap),
            )
    except Exception:
        return ""
    return headline(found, contributing_laps)


def _fuel_at(session: Session, lap) -> "float | None":
    """Litres in the tank as *lap* began, or None if it was not recorded.

    Read only for the lap actually chosen, never during
    :func:`find_quickest_laps` - that opens every recording in the folder,
    and materialising a channel per candidate lap to answer a question about
    one of them would add seconds to a scan that already takes eight.

    None covers the fixtures, which declare the channel without storing it,
    as well as any recording that omits it. A missing fuel figure drops one
    field off the line; it is not a reason to withhold the rest.
    """
    try:
        litres = session.lap_channel(lap, "Fuel Level")
    except Exception:
        return None
    return float(litres[0]) if len(litres) else None


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


#: How many of the matching laps a best-of-set template may draw candidates
#: from. Measured on this corpus - Monza, GT3, 187 clean laps within 3 s of
#: the best:
#:
#: | laps considered | build time | recovers |
#: |---|---|---|
#: | 10 | 0.7 s | 0.648 s |
#: | 20 | 1.4 s | 0.693 s |
#: | **40** | **2.7 s** | **0.832 s** |
#: | 80 | 5.7 s | 0.845 s |
#:
#: Forty is the knee: 93 % of what is available, and eighty doubles the cost
#: for another 13 ms. This happens once, while the driver is in the garage,
#: on top of the ~8 s recording scan :func:`find_quickest_laps` already pays.
CANDIDATE_LAPS = 40


def find_quickest_laps(
    recordings: Path,
    track: str,
    length_m: "float | None" = None,
    car_class: "str | None" = None,
    keep: int = CANDIDATE_LAPS,
) -> "list[Reference]":
    """The *keep* quickest clean laps matching *track*, quickest first.

    Every recording in the directory is opened - the same cost
    :func:`find_reference` always paid for a single lap, now paid once for a
    whole pool of candidates rather than once per corner. Measured against
    the 239 recordings on the machine this was written on, that is 7 to 8
    seconds, and it happens once while the driver is still in the garage.

    A recording that cannot be opened or read is skipped rather than raising.
    One damaged file in a directory is not a reason to leave the driver with
    fewer laps to draw templates from.
    """
    found: "list[Reference]" = []
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
                    found.append(Reference(
                        path=path,
                        lap_number=lap.number,
                        duration_s=lap.duration_s,
                        track=session.info.track,
                        driver=session.info.driver,
                        recorded_at=session.info.recorded_at,
                    ))
        except Exception:
            # Damaged, half-written, or not a recording at all. Skipping one
            # file is better than denying the driver every other lap they have.
            continue
    found.sort(key=lambda reference: reference.duration_s)
    return found[:keep]


def find_reference(
    recordings: Path,
    track: str,
    length_m: "float | None" = None,
    car_class: "str | None" = None,
) -> "Reference | None":
    """The quickest clean lap recorded on *track*, or None if there is none.

    Built on :func:`find_quickest_laps` asking for just the one - not a
    second copy of the same scan and the same filters, which is exactly how
    the two could end up disagreeing about what matches. The alternative to
    scanning every recording, trusting the filename, breaks the moment a file
    is renamed and fails silently rather than loudly - which is the worse
    trade at any price.
    """
    found = find_quickest_laps(recordings, track, length_m, car_class, keep=1)
    return found[0] if found else None
