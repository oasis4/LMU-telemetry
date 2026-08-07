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
