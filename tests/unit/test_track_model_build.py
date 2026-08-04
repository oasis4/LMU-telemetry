import numpy as np
import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import (
    TrackModel,
    build_track_model,
    load_model,
    save_model,
)


def test_model_from_the_reference_fixture(monza_q_file):
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    assert model is not None
    assert model.key.track == "Autodromo Nazionale Monza"
    assert model.track_length_m == pytest.approx(5776.08, abs=1.0)
    assert 340.0 <= model.closure_deg <= 380.0
    assert len(model.corners) >= 10


def test_a_model_from_too_few_laps_is_flagged_unconfident(monza_q_file):
    """The fixture holds two clean laps; a warning must say so."""
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    assert model.confident is False
    assert model.warning is not None
    assert str(model.lap_count) in model.warning


def test_no_model_without_a_clean_lap(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert build_track_model([s]) is None


def test_no_model_is_built_silently_from_bad_data(no_complete_lap_file):
    """Returning None beats inventing geometry - that is the old bug."""
    with Session.open(no_complete_lap_file) as s:
        assert build_track_model([s]) is None


def test_model_survives_a_round_trip_through_json(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    path = save_model(model, tmp_path)
    assert path.is_file()
    again = load_model(model.key, tmp_path)
    assert again is not None
    assert again.key == model.key
    assert again.track_length_m == pytest.approx(model.track_length_m)
    assert [c.name for c in again.corners] == [c.name for c in model.corners]
    for a, b in zip(again.corners, model.corners):
        assert a.start_m == pytest.approx(b.start_m)
        assert a.apex_m == pytest.approx(b.apex_m)
        assert a.radius_m == pytest.approx(b.radius_m)


def test_loading_an_absent_model_returns_none(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        key = build_track_model([s]).key
    assert load_model(key, tmp_path) is None
