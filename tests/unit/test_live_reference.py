"""Picking the reference lap from the track the game has loaded.

The point of this is that the overlay can be started before the session and
work out for itself what to measure against. What it must never do is pick a
lap from a different circuit, which would compare a driver against a corner
list that has nothing to do with where they are.
"""

import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.live.reference import (
    find_reference,
    normalise,
    same_track,
)

MONZA = "Autodromo Nazionale Monza"


def test_the_same_circuit_under_two_names_matches():
    assert same_track(MONZA, MONZA)
    assert same_track("Monza", MONZA), "the game may use the short name"
    assert same_track(MONZA, "monza")
    assert same_track("Autodromo Nazionale Monza ", MONZA)


def test_two_different_circuits_do_not_match():
    assert not same_track(MONZA, "Bahrain International Circuit")
    assert not same_track("Circuit de la Sarthe", "Circuit de Spa-Francorchamps")


def test_an_unnamed_track_matches_nothing():
    """Containment would otherwise make the empty string match everything, and
    the overlay would coach a driver at Le Mans against a lap from Monza."""
    assert not same_track("", MONZA)
    assert not same_track(MONZA, "")
    assert not same_track("", "")


def test_normalising_ignores_punctuation_and_case():
    assert normalise("Circuit de Spa-Francorchamps") == "circuitdespafrancorchamps"
    assert normalise("  MONZA  ") == "monza"


def test_the_quickest_clean_lap_of_the_matching_track_is_picked(fixture_dir):
    found = find_reference(fixture_dir, MONZA)
    assert found is not None
    assert "monza" in found.path.name.lower()

    with Session.open(found.path) as session:
        from lmu_telemetry.core.quality import clean_laps

        quickest = min(clean_laps(session), key=lambda lap: lap.duration_s)
    assert found.lap_number == quickest.number
    assert found.duration_s == pytest.approx(quickest.duration_s)


def test_a_track_with_no_recording_finds_nothing(fixture_dir):
    """None, rather than the nearest lap from somewhere else."""
    assert find_reference(fixture_dir, "Circuit de Spa-Francorchamps") is None


def test_a_directory_with_no_recordings_finds_nothing(tmp_path):
    assert find_reference(tmp_path, MONZA) is None


def test_a_damaged_file_does_not_deny_the_others(fixture_dir, tmp_path):
    """One unreadable file in a directory is not a reason to leave the driver
    with no reference at all."""
    import shutil

    for source in fixture_dir.glob("*monza_q_3laps*.duckdb"):
        shutil.copy(source, tmp_path / source.name)
    (tmp_path / "broken.duckdb").write_bytes(b"not a database")

    found = find_reference(tmp_path, MONZA)
    assert found is not None
    assert found.lap_number > 0


def test_the_reference_says_what_it_picked(fixture_dir):
    """A reference the driver cannot identify is one they cannot check."""
    found = find_reference(fixture_dir, MONZA)
    assert found.path.name in found.label
    assert str(found.lap_number) in found.label
    assert "Monza" in found.label


# -- picking it from the running game --------------------------------------

class _Game:
    """Stands in for LiveTelemetry: reports a circuit after so many polls."""

    def __init__(self, track, after=0):
        self._track = track
        self._left = after
        self.polls = 0

    def track_name(self):
        self.polls += 1
        if self._left > 0:
            self._left -= 1
            return ""
        return self._track


def test_the_reference_is_picked_from_the_circuit_the_game_loaded(fixture_dir):
    """The whole point: started before the session, it works out for itself
    what to measure against."""
    from lmu_telemetry.live.__main__ import _await_reference

    found = _await_reference(_Game(MONZA), fixture_dir, patience_s=5.0)
    assert found is not None
    assert "monza" in found.path.name.lower()


def test_it_waits_for_the_garage_rather_than_giving_up_at_once(fixture_dir):
    """Scoring reports no circuit until one is loaded, and the overlay is
    meant to be started first."""
    from lmu_telemetry.live.__main__ import _await_reference

    game = _Game(MONZA, after=2)
    found = _await_reference(game, fixture_dir, patience_s=10.0)
    assert found is not None
    assert game.polls >= 3


def test_a_circuit_that_never_loads_gives_up_and_says_so(fixture_dir):
    from lmu_telemetry.live.__main__ import _await_reference

    assert _await_reference(_Game("", after=99), fixture_dir, patience_s=1.5) is None


def test_a_circuit_with_nothing_recorded_on_it_is_not_matched_to_another(fixture_dir):
    """Better no reference than a lap from a circuit the driver is not on."""
    from lmu_telemetry.live.__main__ import _await_reference

    found = _await_reference(
        _Game("Circuit de Spa-Francorchamps"), fixture_dir, patience_s=5.0
    )
    assert found is None


def test_a_missing_recordings_directory_is_reported_not_ignored(tmp_path):
    from lmu_telemetry.live.__main__ import _await_reference

    missing = tmp_path / "not-here"
    assert _await_reference(_Game(MONZA), missing, patience_s=5.0) is None


# -- telling two layouts of one circuit apart ------------------------------
#
# Measured across the corpus this was written against: within one layout the
# recorded length varies by at most 6.3 m, and the closest two layouts of the
# same circuit are 29.3 m apart - Monza's full course against its Curva Grande
# variant. LAYOUT_TOLERANCE_M sits between those two numbers.


def test_the_tolerance_lies_between_measurement_spread_and_a_real_variant():
    """Pinned so neither number can be widened without meeting the other."""
    from lmu_telemetry.live.reference import LAYOUT_TOLERANCE_M

    assert LAYOUT_TOLERANCE_M > 6.3, "would reject the right layout"
    assert LAYOUT_TOLERANCE_M < 29.3, "would accept Monza's Curva Grande"


def test_the_two_layouts_of_monza_are_told_apart(fixture_dir):
    """The bug this exists for, and the fixtures happen to hold both variants.

    Both report the track name 'Autodromo Nazionale Monza' and the game says
    only that name, so matching on it alone picks whichever lap is quickest -
    systematically the *shorter* layout, because it is shorter. Every delta
    measured against it is then nonsense: 40 m and two corners out.
    """
    from lmu_telemetry.live.reference import find_reference

    short = find_reference(fixture_dir, MONZA, length_m=5741.0)
    full = find_reference(fixture_dir, MONZA, length_m=5780.6)
    assert short is not None and full is not None

    with Session.open(short.path) as session:
        assert session.info.layout == "Monza Curva Grande Circuit"
    with Session.open(full.path) as session:
        assert session.info.layout == "Autodromo Nazionale Monza"
    assert short.path != full.path


def test_asking_for_the_full_course_never_returns_the_short_one(fixture_dir):
    """Which is what happened live: the reference came back 5740.9 m and nine
    corners while the game was running the 5780.6 m course with eleven."""
    from lmu_telemetry.live.reference import find_reference

    found = find_reference(fixture_dir, MONZA, length_m=5780.6)
    with Session.open(found.path) as session:
        assert abs(session.track_length_m - 5780.6) <= 15.0


def test_the_length_is_optional_and_omitting_it_changes_nothing(fixture_dir):
    """A caller with no length - a replay, or a game that will not say - gets
    the old behaviour rather than nothing at all."""
    from lmu_telemetry.live.reference import find_reference

    assert find_reference(fixture_dir, MONZA) is not None
    assert find_reference(fixture_dir, MONZA, length_m=None) is not None


def test_a_length_inside_the_tolerance_is_accepted(fixture_dir):
    """Measured length varies by a few metres between laps of one layout, so
    an exact match would reject the right recording."""
    from lmu_telemetry.live.reference import LAYOUT_TOLERANCE_M, find_reference

    exact = find_reference(fixture_dir, MONZA)
    with Session.open(exact.path) as session:
        recorded = session.track_length_m

    for offset in (0.0, LAYOUT_TOLERANCE_M - 0.5, -(LAYOUT_TOLERANCE_M - 0.5)):
        assert find_reference(fixture_dir, MONZA, length_m=recorded + offset)
    assert find_reference(
        fixture_dir, MONZA, length_m=recorded + LAYOUT_TOLERANCE_M + 1
    ) is None


# -- telling one class from another ----------------------------------------
#
# Found the same way the layout bug was: the reference chosen live was a
# Hypercar while the driver was in a GT3. Nine seconds a lap apart, and every
# corner would have reported the driver miles off their own reference.
#
# It is the same self-reinforcing shape as the layout fault. "The quickest
# clean lap here" picks the quickest *car*, every time, whatever is driving.


def test_a_faster_class_is_not_offered_to_a_slower_one(fixture_dir):
    """monza_r_position_jump is a Hypercar on the full Monza course; the other
    full-course Monza fixtures are GT3. Same circuit, same layout."""
    from lmu_telemetry.live.reference import find_reference

    found = find_reference(fixture_dir, MONZA, length_m=5776.0, car_class="GT3")
    assert found is not None
    with Session.open(found.path) as session:
        assert session.info.car_class == "GT3"


def test_the_class_that_was_asked_for_is_the_class_that_comes_back(fixture_dir):
    from lmu_telemetry.live.reference import find_reference

    found = find_reference(fixture_dir, MONZA, length_m=5776.0, car_class="Hyper")
    assert found is not None
    with Session.open(found.path) as session:
        assert session.info.car_class == "Hyper"


def test_a_class_with_nothing_recorded_finds_nothing(fixture_dir):
    """Better none than one that is nine seconds a lap away."""
    from lmu_telemetry.live.reference import find_reference

    assert find_reference(
        fixture_dir, MONZA, length_m=5776.0, car_class="LMP2"
    ) is None


def test_the_class_is_matched_loosely_like_the_track_name(fixture_dir):
    """The game and the recordings both name the class but come from
    different places in one product, so LMGT3 and GT3 are one class."""
    from lmu_telemetry.live.reference import find_reference

    for asked in ("GT3", "gt3", "LMGT3"):
        found = find_reference(fixture_dir, MONZA, length_m=5776.0, car_class=asked)
        assert found is not None, asked


def test_omitting_the_class_changes_nothing(fixture_dir):
    """A replay, or a game that will not say, gets the old behaviour."""
    from lmu_telemetry.live.reference import find_reference

    assert find_reference(fixture_dir, MONZA, length_m=5776.0) is not None


# -- the best-of-set candidate pool ------------------------------------------
#
# find_quickest_laps is what a template's best-of-set draws its candidates
# from. It must never disagree with find_reference about what matches - the
# two are tested here as the one function they actually are.


def test_find_quickest_laps_returns_at_most_keep_quickest_first(fixture_dir):
    from lmu_telemetry.live.reference import find_quickest_laps

    found = find_quickest_laps(
        fixture_dir, MONZA, length_m=5776.0, car_class="GT3", keep=3
    )
    assert found
    assert len(found) <= 3
    assert [r.duration_s for r in found] == sorted(r.duration_s for r in found)


def test_find_quickest_laps_first_element_is_find_reference(fixture_dir):
    """The two can never disagree about what matches: find_reference is
    find_quickest_laps(keep=1)'s own first element, not a second copy of the
    same filters."""
    from lmu_telemetry.live.reference import find_quickest_laps

    found = find_quickest_laps(fixture_dir, MONZA, length_m=5776.0, car_class="GT3")
    reference = find_reference(fixture_dir, MONZA, length_m=5776.0, car_class="GT3")
    assert found
    assert found[0] == reference


def test_find_quickest_laps_obeys_the_layout_and_class_filters(fixture_dir):
    """Asking on the full Monza course in GT3 must never return a Curva
    Grande lap or a Hypercar one, the same guarantee find_reference already
    gives for a single lap."""
    from lmu_telemetry.live.reference import find_quickest_laps

    found = find_quickest_laps(
        fixture_dir, MONZA, length_m=5776.0, car_class="GT3", keep=40
    )
    assert found
    for reference in found:
        with Session.open(reference.path) as session:
            assert session.info.layout != "Monza Curva Grande Circuit"
            assert session.info.car_class != "Hyper"
