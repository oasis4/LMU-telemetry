import numpy as np
import pytest

from lmu_telemetry.core.quality import clean_laps
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import (
    TrackModel,
    _lap_line,
    build_track_model,
    load_model,
    save_model,
    track_origin,
)


def test_model_from_the_reference_fixture(monza_q_file):
    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    assert model is not None
    assert model.key.track == "Autodromo Nazionale Monza"
    assert model.track_length_m == pytest.approx(5776.08, abs=1.0)
    assert 340.0 <= model.closure_deg <= 380.0
    assert len(model.corners) >= 10


def test_a_lap_line_is_placed_by_the_origin_it_is_given(monza_q_file):
    """The lap's line must sit where the shared origin puts it.

    Re-centring each lap on its own mean would make both calls below return
    the identical line, so the measured 111 m shift is what pins that every
    lap of a track really does land in one frame rather than its own.
    """
    with Session.open(monza_q_file) as s:
        length = s.track_length_m
        lap = clean_laps(s)[0]
        origin = track_origin([s])
        here = _lap_line(s, lap, length, origin)
        north = _lap_line(s, lap, length, (origin[0] + 0.001, origin[1]))

    assert here is not None and north is not None
    # x moves only through cos(lat0), which barely changes over 0.001 deg.
    assert np.allclose(here[0], north[0], atol=0.1)
    assert np.mean(here[1] - north[1]) == pytest.approx(111.3, abs=1.0)


def test_the_track_origin_does_not_move_with_where_the_car_spent_its_time(
    monza_q_file,
):
    """The bounding box midpoint is a property of the circuit, not of a lap.

    Building from one lap and from every lap of the session must agree,
    because both see the same extremes of the same track.
    """
    with Session.open(monza_q_file) as s:
        origin = track_origin([s])
        lat = s.file.channel("GPS Latitude")
        lon = s.file.channel("GPS Longitude")

    assert origin[0] == pytest.approx((lat.min() + lat.max()) / 2.0)
    assert origin[1] == pytest.approx((lon.min() + lon.max()) / 2.0)
    # It is not the (time-weighted) mean position, which is what would drift.
    assert origin[0] != pytest.approx(float(lat.mean()), abs=1e-9)


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
