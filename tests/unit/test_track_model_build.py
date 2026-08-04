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
    """Returning None beats inventing geometry - that is the old bug."""
    with Session.open(no_complete_lap_file) as s:
        assert build_track_model([s]) is None


def test_model_survives_a_round_trip_through_json(monza_q_file, tmp_path):
    from dataclasses import asdict

    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    path = save_model(model, tmp_path)
    assert path.is_file()
    again = load_model(model.key, tmp_path)
    assert again is not None
    # Compare every field of the model and of every corner, so a value that is
    # dropped or swapped in to_dict/from_dict cannot slip through unnoticed.
    # pytest.approx() does not support nested dicts (raises TypeError on the
    # "corners" list of dicts), so this compares exactly - which is fine here
    # because the values round-trip through JSON as floats and come back
    # bit-identical.
    assert asdict(again) == asdict(model)


def test_loading_an_absent_model_returns_none(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        key = build_track_model([s]).key
    assert load_model(key, tmp_path) is None


def test_model_can_be_built_from_several_sessions_of_one_track(monza_q_file):
    """The whole point of the model: many sessions, one shared corner list."""
    with Session.open(monza_q_file) as a, Session.open(monza_q_file) as b:
        both = build_track_model([a, b])
        single = build_track_model([a])
    assert both is not None
    assert both.lap_count == single.lap_count * 2
    assert both.key == single.key
    assert [c.name for c in both.corners] == [c.name for c in single.corners]


def test_sessions_from_different_tracks_are_rejected(monza_q_file, imola_unclosed_file):
    """Two identities in one call is a caller error, not something to average."""
    with Session.open(monza_q_file) as a, Session.open(imola_unclosed_file) as b:
        with pytest.raises(ValueError):
            build_track_model([a, b])
