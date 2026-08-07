"""A lap's own path, in the circuit's frame.

Drawn on a map beside the reference line, a lap has to be projected in the
same frame as that line. Projecting each on its own mean puts them in
different frames, and the offset between them is then the frames' rather than
the driving's - measured at 112 m in x across Monza's laps, on a track about
12 m wide.
"""

import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lmu_telemetry.api.app import create_app
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import build_track_model
from lmu_telemetry.core.trace import build_trace


@pytest.fixture(scope="module")
def monza(monza_q_file):
    with Session.open(monza_q_file) as session:
        model = build_track_model([session])
        lap = next(l for l in session.laps if l.number == 2)
        yield session, model, lap


def test_without_an_origin_no_path_is_produced(monza):
    """None, not a path in this lap's own frame.

    A path centred on its own mean looks perfectly reasonable and cannot be
    drawn against anything else, so it is worse than nothing.
    """
    session, model, lap = monza
    trace = build_trace(session, lap, model.track_length_m)
    assert trace.x is None and trace.y is None


def test_with_the_model_s_origin_the_lap_lands_on_the_reference_line(monza):
    session, model, lap = monza
    trace = build_trace(session, lap, model.track_length_m, origin=model.origin)

    assert trace.x is not None
    assert len(trace.x) == len(model.line_x)
    # The lap is one of the laps the reference was built from, so it sits on
    # it to within the width of a racing line - not hundreds of metres away.
    offset = np.hypot(trace.x - model.line_x, trace.y - model.line_y)
    assert float(np.median(offset)) < 5.0, float(np.median(offset))
    assert float(np.percentile(offset, 99)) < 20.0


def test_the_model_carries_the_origin_it_measured_in(monza):
    _session, model, _lap = monza
    assert model.origin is not None
    latitude, longitude = model.origin
    assert -90 <= latitude <= 90
    assert -180 <= longitude <= 180


def test_the_origin_survives_the_cache(monza, tmp_path):
    from lmu_telemetry.core.track_model import load_model, save_model

    _session, model, _lap = monza
    save_model(model, tmp_path)
    loaded = load_model(model.key, tmp_path)
    assert loaded is not None
    assert loaded.origin == pytest.approx(model.origin)


def test_the_route_sends_the_path_with_the_trace(tmp_path_factory, fixture_dir):
    recordings = tmp_path_factory.mktemp("path-recordings")
    shutil.copy(fixture_dir / "monza_q_3laps.duckdb", recordings / "monza.duckdb")
    app = create_app(recordings, cache_dir=tmp_path_factory.mktemp("path-cache"))
    with TestClient(app) as client:
        body = client.get("/api/sessions/monza.duckdb/laps/2/trace").json()
        track = client.get("/api/sessions/monza.duckdb/map").json()
    app.state.pool.close()

    assert "x" in body["series"] and "y" in body["series"]
    assert len(body["series"]["x"]) == body["samples"]

    # Same frame as the map: the two bounding boxes must overlap, not sit
    # hundreds of metres apart.
    assert min(body["series"]["x"]) == pytest.approx(min(track["x"]), abs=60)
    assert min(body["series"]["y"]) == pytest.approx(min(track["y"]), abs=60)
