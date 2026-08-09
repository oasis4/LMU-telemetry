"""Where the tools look for recordings when nobody tells them.

``data/sessions`` is the curated working set and the right answer when it is
there. It is not always there: a driver who has only ever run the launcher has
their recordings where the game writes them, and the launcher already knows
that folder because it asked once and wrote it down. Falling back to it is the
difference between the overlay starting and the overlay refusing.
"""

import json

import pytest

from lmu_telemetry.recordings import default_recordings_dir

CONFIGURED = "telemetry_dir"


def _config(root, target) -> None:
    (root / ".telemetry_config.json").write_text(
        json.dumps({CONFIGURED: str(target)}), encoding="utf-8"
    )


def test_the_curated_working_set_is_used_when_it_is_there(tmp_path):
    """It is the set the rest of the project measures against, so it wins."""
    curated = tmp_path / "data" / "sessions"
    curated.mkdir(parents=True)
    other = tmp_path / "from-the-game"
    other.mkdir()
    _config(tmp_path, other)

    assert default_recordings_dir(tmp_path) == curated


def test_the_configured_folder_is_used_when_there_is_no_working_set(tmp_path):
    """The whole point: the launcher already asked where the recordings are."""
    game = tmp_path / "Le Mans Ultimate" / "UserData" / "Telemetry"
    game.mkdir(parents=True)
    _config(tmp_path, game)

    assert default_recordings_dir(tmp_path) == game


def test_a_configured_folder_that_is_gone_is_not_offered(tmp_path):
    """A drive that is not mounted, or a folder since moved. Naming it as the
    answer would report a missing directory the driver did not choose."""
    _config(tmp_path, tmp_path / "F_drive_not_mounted")

    assert default_recordings_dir(tmp_path) == tmp_path / "data" / "sessions"


def test_a_damaged_config_falls_back_rather_than_raising(tmp_path):
    """Half-written by a launcher that was closed at the wrong moment."""
    (tmp_path / ".telemetry_config.json").write_text("{not json", encoding="utf-8")

    assert default_recordings_dir(tmp_path) == tmp_path / "data" / "sessions"


def test_a_config_without_the_key_falls_back(tmp_path):
    (tmp_path / ".telemetry_config.json").write_text('{"port": 8001}', encoding="utf-8")

    assert default_recordings_dir(tmp_path) == tmp_path / "data" / "sessions"


def test_with_nothing_at_all_it_names_the_conventional_place(tmp_path):
    """So the message the driver reads names somewhere they recognise, rather
    than an empty path or the repository root."""
    found = default_recordings_dir(tmp_path)

    assert found == tmp_path / "data" / "sessions"
    assert not found.is_dir(), "the point is that it does not exist yet"


def test_this_repository_resolves_to_a_directory_that_holds_recordings():
    """The real check: on this machine, started with no arguments, does the
    overlay have somewhere to look? Skips where neither place is populated."""
    found = default_recordings_dir()
    if not found.is_dir():
        pytest.skip(f"no recordings on this machine at {found}")
    assert any(found.glob("*.duckdb")), f"{found} holds no recordings"
