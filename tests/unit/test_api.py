import json
import shutil

import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import create_app
from lmu_telemetry.api.decimate import TARGET_POINTS


@pytest.fixture(scope="module")
def recordings(tmp_path_factory, fixture_dir):
    """A recordings directory holding the committed fixtures."""
    directory = tmp_path_factory.mktemp("recordings")
    for name in (
        "monza_q_3laps.duckdb",
        "monza_r_position_jump.duckdb",
        "monza_p_fastest_lap_untimed.duckdb",
    ):
        source = fixture_dir / name
        if source.is_file():
            shutil.copy(source, directory / name)
    return directory


@pytest.fixture(scope="module")
def cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("trace-cache")


@pytest.fixture(scope="module")
def client(recordings, cache_dir):
    app = create_app(recordings, cache_dir=cache_dir)
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_health_reports_where_it_reads_from(client, recordings):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["recordings_dir"] == str(recordings)


def test_sessions_are_listed_with_what_they_contain(client):
    sessions = client.get("/api/sessions").json()["sessions"]
    assert sessions
    monza = next(s for s in sessions if s["name"] == "monza_q_3laps.duckdb")
    assert monza["track"] == "Autodromo Nazionale Monza"
    assert monza["laps"] == 3
    assert monza["clean_laps"] == 2
    assert monza["best_lap_s"] == pytest.approx(111.0, abs=0.01)
    assert monza["best_lap"] == 2


def test_the_best_time_advertised_is_one_the_pipeline_will_accept(client):
    """The listing's headline time is what a lap is chosen by, so offering
    one the comparison then refuses is offering a lap that cannot be opened.

    Four of the 78 working-set recordings disagree that way. The fixture here
    is one of them: Monza practice, where lap 3 is the quickest at 102.10 s
    and the game recorded no lap time for it at all.
    """
    for session in client.get("/api/sessions").json()["sessions"]:
        if session.get("best_lap") is None:
            continue
        laps = client.get(f"/api/sessions/{session['name']}/laps").json()["laps"]
        best = next(l for l in laps if l["number"] == session["best_lap"])
        assert best["clean"], f"{session['name']} offers a lap it refuses: {best['reason']}"
        assert best["duration_s"] == pytest.approx(session["best_lap_s"], abs=0.001)


def test_the_quickest_lap_is_not_offered_when_it_is_not_usable(client):
    """The discriminating case, named rather than left to the sweep above."""
    listed = client.get("/api/sessions").json()["sessions"]
    monza = next(s for s in listed if s["name"] == "monza_p_fastest_lap_untimed.duckdb")
    assert monza["best_lap"] == 1
    assert monza["best_lap_s"] == pytest.approx(103.36, abs=0.01)


def test_the_best_lap_offered_is_never_lap_zero(client):
    """Lap 0 runs from the start of recording to the first crossing. One
    Sebring session offers 43.3 s of a 5820 m circuit that way."""
    for session in client.get("/api/sessions").json()["sessions"]:
        assert session.get("best_lap") != 0


def test_every_lap_is_listed_and_an_excluded_one_says_why(client):
    laps = client.get("/api/sessions/monza_q_3laps.duckdb/laps").json()["laps"]
    assert [l["number"] for l in laps] == [0, 1, 2]
    excluded = [l for l in laps if not l["clean"]]
    assert excluded and all(l["reason"] for l in excluded)


def test_the_track_comes_back_with_its_corners(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/track").json()
    assert body["track"] == "Autodromo Nazionale Monza"
    assert body["closure_deg"] == pytest.approx(360.0, abs=0.5)
    assert len(body["corners"]) == body["corners"][-1]["index"]
    assert all(c["direction"] in ("L", "R") for c in body["corners"])


def test_a_lap_trace_is_decimated_by_default(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/laps/2/trace").json()
    assert body["samples"] <= TARGET_POINTS
    assert set(body["series"]) == {
        "distance_m", "time_s", "speed_kmh", "throttle", "brake", "steering",
        "x", "y",
    }
    assert all(len(v) == body["samples"] for v in body["series"].values())


def test_full_resolution_is_available_when_asked_for(client):
    small = client.get("/api/sessions/monza_q_3laps.duckdb/laps/2/trace").json()
    whole = client.get(
        "/api/sessions/monza_q_3laps.duckdb/laps/2/trace?full=true"
    ).json()
    assert whole["samples"] > small["samples"]
    assert whole["resolution"] == "full"


def test_a_comparison_returns_one_corner_list_for_both_laps(client):
    """The old server had /api/corners/{session}, so the client fetched a list
    per side and compared two drivers against different corner definitions."""
    body = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": "monza_q_3laps.duckdb", "other_lap": 1},
    ).json()
    track = client.get("/api/sessions/monza_q_3laps.duckdb/track").json()
    assert [c["name"] for c in body["corners"]] == [c["name"] for c in track["corners"]]
    assert body["lap_delta_s"] == pytest.approx(116.560 - 111.000, abs=0.3)


def test_every_corner_of_a_comparison_carries_both_drivers_numbers(client):
    body = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": "monza_q_3laps.duckdb", "other_lap": 1},
    ).json()
    for corner in body["corners"]:
        assert corner["reference"]["min_speed_kmh"] > 0
        assert corner["other"]["min_speed_kmh"] > 0
        assert corner["name"] in corner["summary"]
        for difference in corner["differences"]:
            assert difference["what"]


def test_every_corner_of_a_comparison_carries_the_three_distances(client):
    """The corner map marks the apex, and read it off the comparison's own
    corner - which did not carry one. `undefined` divided by a metres-per-point
    ran all the way into the DOM as `<circle cx="NaN">`."""
    body = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": "monza_q_3laps.duckdb", "other_lap": 1},
    ).json()
    track = client.get("/api/sessions/monza_q_3laps.duckdb/track").json()
    assert [c["apex_m"] for c in body["corners"]] == [c["apex_m"] for c in track["corners"]]
    for corner in body["corners"]:
        assert corner["start_m"] <= corner["apex_m"] <= corner["end_m"] or (
            corner["start_m"] > corner["end_m"]  # a corner spanning the line
        )


def test_a_comparison_says_what_counts_as_braking(client):
    """The corner map shades where the car is braking, and the brake points in
    the same response were found with this threshold. A client with its own
    number would shade a stretch that disagrees with the figure beside it."""
    from lmu_telemetry.core.metrics import BRAKE_ON

    body = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": "monza_q_3laps.duckdb", "other_lap": 1},
    ).json()
    assert body["brake_on"] == BRAKE_ON


def test_a_comparison_says_where_each_lap_was_on_the_brakes(client):
    """As distance ranges, measured on the full trace. The map draws these, so
    they must survive the decimation the series beside them go through: that
    keeps the samples where the delta turns, and a short brush of the brakes
    can fall between two of them and disappear."""
    params = {"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
              "other": "monza_q_3laps.duckdb", "other_lap": 1}
    small = client.get("/api/compare", params=params).json()
    whole = client.get("/api/compare", params={**params, "full": "true"}).json()

    for side in ("reference", "other"):
        zones = small["braking"][side]
        assert zones, f"a Monza lap brakes somewhere ({side})"
        assert zones == whole["braking"][side], "the zones changed with the resolution"
        for first, last in zones:
            assert 0.0 <= first < last
        for (_, ends), (starts, _) in zip(zones, zones[1:]):
            assert ends < starts, "zones must not touch or overlap"


def test_a_comparison_carries_every_input_for_both_laps(client):
    """The corner overlay draws the pedals and the wheel together; a response
    carrying only the brake makes each of the others a round trip per corner."""
    body = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": "monza_q_3laps.duckdb", "other_lap": 1},
    ).json()
    expected = {
        "distance_m", "delta_s", "speed_reference_kmh", "speed_other_kmh",
        "brake_reference", "brake_other", "throttle_reference", "throttle_other",
        "steering_reference", "steering_other",
    }
    assert set(body["series"]) == expected
    # One shared index set, so the series can be read at the same position.
    assert {len(v) for v in body["series"].values()} == {body["samples"]}


def test_a_comparison_sends_the_samples_a_screen_can_show(client):
    """The measured problem was 5.31 MB of JSON per Le Mans comparison.

    The saving scales with how long the circuit is, so it is asserted against
    the grid rather than against a byte count that only holds for Monza.
    Monza's 5776 m is 2889 grid points, reduced to the target; Le Mans' 13.6 km
    is 6811, so the same code saves more there, not less.
    """
    params = {"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
              "other": "monza_q_3laps.duckdb", "other_lap": 1}
    small = client.get("/api/compare", params=params).json()
    whole = client.get("/api/compare", params={**params, "full": "true"}).json()

    assert whole["samples"] > 2500, "Monza on a 2 m grid should be about 2889 points"
    assert small["samples"] <= TARGET_POINTS
    # Well under the target, because a bucket over a smooth stretch has its
    # minimum, maximum and both ends at the same sample and contributes one
    # point rather than four. Monza comes out at about 829 of 2889.
    assert small["samples"] * 2 < whole["samples"]


def test_decimation_shrinks_what_actually_crosses_the_network(client):
    params = {"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
              "other": "monza_q_3laps.duckdb", "other_lap": 1}
    small = len(client.get("/api/compare", params=params).content)
    whole = len(client.get("/api/compare", params={**params, "full": "true"}).content)
    assert whole > small * 2.5, f"only {whole / small:.1f}x ({whole} -> {small} bytes)"


def test_comparing_two_different_circuits_is_refused(client, recordings, fixture_dir):
    source = fixture_dir / "paul_ricard_p_zero_winding.duckdb"
    if not source.is_file():
        pytest.skip("Paul Ricard fixture not built")
    shutil.copy(source, recordings / source.name)
    response = client.get(
        "/api/compare",
        params={"reference": "monza_q_3laps.duckdb", "reference_lap": 2,
                "other": source.name, "other_lap": 1},
    )
    assert response.status_code == 422, response.json()
    assert "different circuits" in response.json()["detail"]


def test_a_recording_that_is_not_there_is_a_404(client):
    assert client.get("/api/sessions/nope.duckdb/laps").status_code == 404


def test_a_lap_that_is_not_there_is_a_404(client):
    response = client.get("/api/sessions/monza_q_3laps.duckdb/laps/99/trace")
    assert response.status_code == 404


def test_a_recording_outside_the_directory_cannot_be_reached(tmp_path, fixture_dir):
    """The name arrives from the client, so it is untrusted.

    Two things are needed for this to prove anything. The file must exist
    outside the root, or the file check refuses it whether or not the
    directory is enforced. And the separator must be one the router lets
    through: Starlette will not match a path parameter containing '/', so
    every slash-based attempt is a 404 from the router and never reaches this
    code. A backslash is not a URL separator, so it arrives intact - and on
    Windows it is a path separator, which is exactly the case the guard is for.
    """
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", recordings / "inside.duckdb")

    outside = tmp_path / "outside.duckdb"
    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", outside)
    assert outside.is_file()

    app = create_app(recordings, cache_dir=tmp_path / "cache")
    with TestClient(app) as client:
        allowed = client.get("/api/sessions/inside.duckdb/laps")
        by_backslash = client.get("/api/sessions/..%5Coutside.duckdb/laps")
        by_slash = client.get("/api/sessions/..%2Foutside.duckdb/laps")
    app.state.pool.close()

    assert allowed.status_code == 200
    assert by_backslash.status_code == 400, by_backslash.json()
    assert "not inside the recordings directory" in by_backslash.json()["detail"]
    assert by_slash.status_code == 404, by_slash.json()


def test_a_lap_that_cannot_be_put_on_the_grid_says_so(client):
    """Lap 0 starts in the pit lane and never spans the track."""
    response = client.get("/api/sessions/monza_q_3laps.duckdb/laps/0/trace")
    assert response.status_code == 422
    assert response.json()["detail"]


def test_a_lap_is_resampled_once_and_read_back_afterwards(client, cache_dir):
    """The old server resampled the whole session on every selection change.

    The result depends only on the recording, so it is written once and read
    back - which is what makes looking at the same session again a file read.
    """
    first = client.get("/api/sessions/monza_q_3laps.duckdb/laps/1/trace?full=true").json()
    assert list(cache_dir.glob("*trace-lap1*.npz")), "nothing was cached"

    # Asserting that the second call returns the same numbers proves nothing:
    # recomputing returns them too. So resampling is made to fail, and the
    # request has to be answered anyway - which it can only do from the cache.
    import lmu_telemetry.api.app as app_module

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("the lap was resampled again instead of being read back")

    original = app_module.build_trace
    app_module.build_trace = _must_not_be_called
    try:
        again = client.get(
            "/api/sessions/monza_q_3laps.duckdb/laps/1/trace?full=true"
        ).json()
    finally:
        app_module.build_trace = original

    assert again["series"] == first["series"]


def test_a_cache_entry_from_a_replaced_recording_is_not_served(
    tmp_path, fixture_dir
):
    """The key is (path, mtime, size). Replacing the file must invalidate it,
    or every number shown comes from a recording the user no longer has.

    Two applications share one cache directory, because on Windows a recording
    cannot be overwritten while a DuckDB connection holds it open - which is
    also true of the running server, and is why the first pool is closed here
    rather than kept.
    """
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    cache = tmp_path / "cache"
    target = recordings / "swappable.duckdb"

    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", target)
    app = create_app(recordings, cache_dir=cache)
    with TestClient(app) as first_client:
        before = first_client.get("/api/sessions/swappable.duckdb/laps/2/trace").json()
    app.state.pool.close()
    assert list(cache.glob("*.npz")), "nothing was cached to go stale"

    shutil.copy(fixture_dir / "monza_r_position_jump.duckdb", target)
    app = create_app(recordings, cache_dir=cache)
    with TestClient(app) as second_client:
        after = second_client.get("/api/sessions/swappable.duckdb/laps/2/trace")
    app.state.pool.close()

    assert after.status_code == 200
    assert after.json()["series"] != before["series"]


def test_a_cache_that_cannot_be_written_still_answers(recordings, tmp_path):
    """A cache is an optimisation. If the directory is unusable the answer is
    the same, only slower - it must not become an error."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    app = create_app(recordings, cache_dir=blocked / "cache")
    with TestClient(app) as client:
        response = client.get("/api/sessions/monza_q_3laps.duckdb/laps/2/trace")
    app.state.pool.close()
    assert response.status_code == 200
    assert response.json()["samples"] > 0


def test_the_response_is_json_a_browser_can_parse(client):
    body = client.get("/api/sessions/monza_q_3laps.duckdb/laps/2/trace")
    assert body.headers["content-type"].startswith("application/json")
    json.loads(body.content)
