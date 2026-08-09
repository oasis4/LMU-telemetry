"""The ideal lap, over the wire.

The endpoint exists so the ideal lap can be seen at all. What it must never
do is present a time the laps do not support - see the seam tests below and
``core/blocks.py`` on why ``sound`` is an ``all()`` and not a count.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import create_app
from lmu_telemetry.core.blocks import SEAM_SPEED_KMH


@pytest.fixture(scope="module")
def client(tmp_path_factory, fixture_dir):
    recordings = tmp_path_factory.mktemp("ideal-recordings")
    for name in ("monza_q_3laps.duckdb", "monza_r_extra_dist_reset.duckdb",
                 "monza_r_position_jump.duckdb"):
        shutil.copy(fixture_dir / name, recordings / name)
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("ideal-cache"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_the_ideal_lap_is_built_from_the_recording_s_clean_laps(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["track"] == "Autodromo Nazionale Monza"
    assert body["laps_used"], "no laps named"
    assert len(body["laps_used"]) == 2, "the fixture has two clean laps"
    assert body["best_lap_number"] in body["laps_used"]


def test_the_blocks_account_for_the_whole_ideal_time(client):
    """A headline figure whose parts do not sum to it is two numbers, not one."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["blocks"]
    total = sum(block["time_s"] for block in body["blocks"])
    assert total == pytest.approx(body["ideal_s"], abs=0.01)


def test_the_gain_is_the_difference_it_claims_to_be(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["gain_s"] == pytest.approx(
        body["best_lap_s"] - body["ideal_s"], abs=0.001
    )
    assert body["ideal_s"] <= body["best_lap_s"] + 1e-9, (
        "an ideal lap slower than a lap that was actually driven"
    )


def test_every_block_names_the_lap_it_came_from(client):
    """A block whose source is unnamed cannot be checked against the lap."""
    body = client.get("/api/sessions/monza_r_extra_dist_reset.duckdb/ideal").json()
    for block in body["blocks"]:
        assert block["lap_number"] in body["laps_used"]
        assert block["name"]
        assert block["corners"], f"block {block['index']} holds no corners"


def test_the_first_block_is_the_one_holding_the_line(client):
    """Driven order, as split_into_blocks returns it. A block list sorted by
    distance would start somewhere arbitrary on the track."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    first = body["blocks"][0]
    assert first["index"] == 1
    if len(body["blocks"]) > 1:
        assert first["wraps"] == (first["start_m"] > first["end_m"])


def test_there_is_a_seam_for_every_block(client):
    """The lap is a loop; every block is entered from another one."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert len(body["seams"]) == len(body["blocks"])


def test_the_seam_limit_is_sent_rather_than_left_to_the_client(client):
    """Sent for the reason /api/compare sends brake_on: the flags are computed
    with it, and a client drawing its own threshold would contradict them."""
    body = client.get("/api/sessions/monza_q_3laps.duckdb/ideal").json()
    assert body["seam_limit_kmh"] == SEAM_SPEED_KMH
    for seam in body["seams"]:
        assert seam["sound"] == (seam["speed_spread_kmh"] <= body["seam_limit_kmh"])


def test_sound_is_true_only_when_every_seam_holds(client):
    body = client.get("/api/sessions/monza_r_extra_dist_reset.duckdb/ideal").json()
    assert body["sound"] == all(seam["sound"] for seam in body["seams"])


# -- the refusals ----------------------------------------------------------
#
# The first of these is the common path, not an edge. Of 60 recordings sampled
# from the corpus only 34 could build an ideal lap; all 26 of the others ended
# here, every one for want of a second usable lap.


@pytest.fixture(scope="module")
def lonely_lemans(tmp_path_factory, fixture_dir):
    """Le Mans alone in a directory, so no sibling can supply a track model.

    ``_model_for`` builds the model from every recording of the same circuit in
    the directory. A Monza fixture with no clean lap would still get a model
    from its Monza siblings, so it cannot test this refusal.
    """
    recordings = tmp_path_factory.mktemp("lemans-only")
    shutil.copy(
        fixture_dir / "lemans_r_percent_steering.duckdb", recordings / "lemans.duckdb"
    )
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("lemans-cache"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_one_clean_lap_is_refused_with_the_count_that_caused_it(client):
    """A refusal that does not say what it counted is indistinguishable from a
    bug - and this is the message most recordings will answer with."""
    response = client.get("/api/sessions/monza_r_position_jump.duckdb/ideal")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "1 usable lap" in detail, detail
    assert "of 3" in detail, "the total the recording holds is not stated"
    assert "two" in detail, "the requirement is not stated"


def test_the_two_refusals_do_not_read_the_same(client, lonely_lemans):
    """They are different problems and lead to different next moves: drive
    another lap, against this recording having no measurable circuit at all."""
    few = client.get("/api/sessions/monza_r_position_jump.duckdb/ideal").json()
    none = lonely_lemans.get("/api/sessions/lemans.duckdb/ideal").json()
    assert few["detail"] != none["detail"]


def test_a_recording_with_no_track_model_is_refused(lonely_lemans):
    response = lonely_lemans.get("/api/sessions/lemans.duckdb/ideal")
    assert response.status_code == 422
    assert "measure the track from" in response.json()["detail"]


def test_a_recording_that_is_not_there_is_a_404_not_a_422(client):
    """A missing file and an unusable one are different problems."""
    assert client.get("/api/sessions/nope.duckdb/ideal").status_code == 404
