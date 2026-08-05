import shutil

import numpy as np

import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import corner_spans, create_app, path_stride
from lmu_telemetry.api.decimate import TARGET_POINTS


@pytest.fixture(scope="module")
def client(tmp_path_factory, fixture_dir):
    recordings = tmp_path_factory.mktemp("map-recordings")
    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", recordings / "monza.duckdb")
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("map-cache"))
    with TestClient(app) as test_client:
        yield test_client
    app.state.pool.close()


def test_the_map_is_the_measured_line(client):
    body = client.get("/api/sessions/monza.duckdb/map").json()
    assert body["track"] == "Autodromo Nazionale Monza"
    assert len(body["x"]) == len(body["y"]) == body["samples"]
    assert body["samples"] > 100


def test_the_line_spans_the_circuit_it_claims_to_be(client):
    """Monza is about 5.8 km round, so its bounding box is roughly a kilometre.

    A line that came back an order of magnitude too small would mean the
    projection or the units went wrong somewhere, and a map drawn from it
    would still look like a circuit.
    """
    body = client.get("/api/sessions/monza.duckdb/map").json()
    width = max(body["x"]) - min(body["x"])
    height = max(body["y"]) - min(body["y"])
    assert 500 < width < 3000, width
    assert 500 < height < 3000, height


def test_a_map_is_thinned_by_taking_every_nth_point(client):
    small = client.get("/api/sessions/monza.duckdb/map").json()
    whole = client.get("/api/sessions/monza.duckdb/map?full=true").json()

    assert whole["samples"] > small["samples"]
    assert small["samples"] <= TARGET_POINTS
    stride = path_stride(whole["samples"])
    assert small["x"][1] == whole["x"][stride]


def test_thinning_a_path_keeps_its_shape_in_both_coordinates(client):
    """Every nth point, not min/max per bucket.

    Bucketed extremes are right for a signal where a spike must survive, but a
    path has two coordinates and only one can drive the choice - keeping the
    x-extremes of a bucket while dropping the y-extremes distorts the shape.
    The thinned bounding box must match the full one.
    """
    small = client.get("/api/sessions/monza.duckdb/map").json()
    whole = client.get("/api/sessions/monza.duckdb/map?full=true").json()

    for axis in ("x", "y"):
        full_extent = max(whole[axis]) - min(whole[axis])
        thin_extent = max(small[axis]) - min(small[axis])
        assert thin_extent == pytest.approx(full_extent, rel=0.02), axis


def test_every_corner_carries_a_span_into_the_points_that_were_sent(client):
    body = client.get("/api/sessions/monza.duckdb/map").json()
    assert body["corners"]
    for corner in body["corners"]:
        assert corner["spans"], corner["name"]
        for first, last in corner["spans"]:
            assert 0 <= first < last <= body["samples"], corner
        assert corner["direction"] in ("L", "R")


def test_a_corner_across_the_start_finish_line_comes_as_two_spans():
    """start_m > end_m means the corner contains d=0.

    Read as one range it is empty and the corner vanishes from the map. No
    circuit in the working set has such a corner - all of them start on a
    straight - so this is written against the function rather than the route,
    where it can actually fail.
    """
    kept_m = np.arange(0, 1000.0, 2.0)

    ordinary = corner_spans(300.0, 400.0, kept_m, 1000.0)
    assert len(ordinary) == 1
    assert ordinary == [[150, 201]]

    wrapping = corner_spans(940.0, 60.0, kept_m, 1000.0)
    assert len(wrapping) == 2
    assert wrapping[0][0] == 470            # 940 m
    assert wrapping[0][1] == len(kept_m)    # to the end of the lap
    assert wrapping[1] == [0, 31]           # and on to 60 m
    covered = sum(last - first for first, last in wrapping)
    assert covered * 2.0 == pytest.approx(120.0, abs=4.0)


def test_every_corner_of_a_real_circuit_gets_exactly_one_span(client):
    """Monza has no corner over the line, so every span list has one entry.

    Paired with the synthetic test above this pins both branches: that one
    proves the wrap is split, this one proves an ordinary corner is not.
    """
    track = client.get("/api/sessions/monza.duckdb/track").json()
    body = client.get("/api/sessions/monza.duckdb/map").json()
    assert not any(c["wraps"] for c in track["corners"]), (
        "this circuit now has a wrapping corner, so this test no longer says "
        "what it claims"
    )
    assert all(len(c["spans"]) == 1 for c in body["corners"])


def test_the_spans_land_where_the_corner_actually_is(client):
    """A span is checked against the distance it covers, not just its bounds.

    Indices that were merely in range would satisfy the test above while
    pointing at the wrong part of the circuit.
    """
    track = client.get("/api/sessions/monza.duckdb/track").json()
    body = client.get("/api/sessions/monza.duckdb/map").json()
    per_point = body["track_length_m"] / body["samples"]

    for corner, mapped in zip(track["corners"], body["corners"]):
        assert corner["index"] == mapped["index"]
        if len(mapped["spans"]) != 1:
            continue
        first, last = mapped["spans"][0]
        assert first * per_point == pytest.approx(corner["start_m"], abs=3 * per_point)
        assert last * per_point == pytest.approx(corner["end_m"], abs=3 * per_point)


def test_a_model_without_a_line_is_refused_rather_than_drawn(
    tmp_path_factory, fixture_dir
):
    """A model cached before the line existed reads back with line_x=None.

    It looks complete and cannot be drawn. Every model built now carries a
    line, so the branch is reached by handing the route one that does not -
    otherwise nothing exercises it and it could be deleted unnoticed.
    """
    from dataclasses import replace

    recordings = tmp_path_factory.mktemp("lineless")
    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", recordings / "monza.duckdb")
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("lineless-cache"))

    with TestClient(app) as client:
        assert client.get("/api/sessions/monza.duckdb/map").status_code == 200
        pool = app.state.pool
        real = pool.model_for
        pool.model_for = lambda session: replace(real(session), line_x=None, line_y=None)
        response = client.get("/api/sessions/monza.duckdb/map")
        pool.model_for = real
    app.state.pool.close()

    assert response.status_code == 422
    assert "reference line" in response.json()["detail"]


def test_a_recording_with_no_usable_lap_says_so(tmp_path_factory, fixture_dir):
    recordings = tmp_path_factory.mktemp("empty-map")
    source = fixture_dir / "monza_q_no_complete_lap.duckdb"
    if not source.is_file():
        pytest.skip("fixture not built")
    shutil.copy(source, recordings / "empty.duckdb")
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("empty-cache"))
    with TestClient(app) as client:
        response = client.get("/api/sessions/empty.duckdb/map")
    app.state.pool.close()
    assert response.status_code == 422
    assert response.json()["detail"]
