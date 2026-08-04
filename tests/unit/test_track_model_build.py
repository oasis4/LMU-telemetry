import numpy as np
import pytest

from lmu_telemetry.core.quality import clean_laps
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import (
    MODEL_FORMAT_VERSION,
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


def test_a_model_saved_under_another_version_does_not_load(monza_q_file, tmp_path):
    """A cache built under different rules must be rebuilt, not trusted.

    Nothing in the stored fields says which detection constants or which
    projection produced them, so the stamp is the only thing standing between
    a changed pipeline and a silently stale model.
    """
    import json

    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    path = save_model(model, tmp_path)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["format_version"] == MODEL_FORMAT_VERSION
    stored["format_version"] = MODEL_FORMAT_VERSION + 1
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert load_model(model.key, tmp_path) is None


def test_a_model_with_no_version_stamp_does_not_load(monza_q_file, tmp_path):
    """Every cache written before the stamp existed was built under the
    per-lap projection frames, so none of them may be served."""
    import json

    with Session.open(monza_q_file) as s:
        model = build_track_model([s])
    path = save_model(model, tmp_path)

    stored = json.loads(path.read_text(encoding="utf-8"))
    del stored["format_version"]
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert load_model(model.key, tmp_path) is None


def test_loading_an_absent_model_returns_none(monza_q_file, tmp_path):
    with Session.open(monza_q_file) as s:
        key = build_track_model([s]).key
    assert load_model(key, tmp_path) is None


def test_model_can_be_built_from_several_sessions_of_one_track(
    monza_q_file, fixture_dir
):
    """The whole point of the model: many sessions, one shared corner list.

    The two sessions must be genuinely different recordings. Opening one file
    twice makes the median across sessions the identity, so such a test
    cannot tell a correctly merged model from one whose laps never shared a
    coordinate frame - which is exactly the failure worth catching here.
    """
    monza_r = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    with Session.open(monza_q_file) as a, Session.open(monza_r) as b:
        assert a.file.path != b.file.path
        both = build_track_model([a, b])
        first = build_track_model([a])
        second = build_track_model([b])

    assert both is not None
    assert both.key == first.key == second.key
    assert both.lap_count == first.lap_count + second.lap_count
    assert first.lap_count > 0 and second.lap_count > 0

    # A merged model is one corner list, not the concatenation of two.
    assert len(both.corners) == len(first.corners) == len(second.corners)
    # Every corner of the merged model sits between what the two sessions
    # measured on their own, which it cannot do if the laps of one session
    # were shifted into a frame of their own before the median.
    for merged, a_c, b_c in zip(both.corners, first.corners, second.corners):
        assert min(a_c.apex_m, b_c.apex_m) - 60.0 <= merged.apex_m
        assert merged.apex_m <= max(a_c.apex_m, b_c.apex_m) + 60.0


def test_a_built_model_is_named_without_the_caller_applying_names(
    monza_q_file, fixture_dir
):
    """Task 8's deliverable has to be reachable from production code.

    build_track_model, not its callers, applies the curated names - otherwise
    save_model persists T1..Tn and every consumer of a cached model sees the
    generic names.
    """
    monza_r = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    with Session.open(monza_q_file) as a, Session.open(monza_r) as b:
        model = build_track_model([a, b])

    names = [c.name for c in model.corners]
    assert "Curva Parabolica" in names
    assert names[0] == "Variante del Rettifilo 1"
    assert not any(n.startswith("T") and n[1:].isdigit() for n in names)


def test_a_cached_model_comes_back_named(monza_q_file, fixture_dir, tmp_path):
    """A named model must survive the cache, or the cache un-names it."""
    monza_r = fixture_dir / "monza_r_extra_dist_reset.duckdb"
    with Session.open(monza_q_file) as a, Session.open(monza_r) as b:
        model = build_track_model([a, b])
    save_model(model, tmp_path)
    again = load_model(model.key, tmp_path)

    assert again is not None
    assert [c.name for c in again.corners] == [c.name for c in model.corners]
    assert "Curva Parabolica" in [c.name for c in again.corners]


def test_sessions_from_different_tracks_are_rejected(monza_q_file, imola_unclosed_file):
    """Two identities in one call is a caller error, not something to average."""
    with Session.open(monza_q_file) as a, Session.open(imola_unclosed_file) as b:
        with pytest.raises(ValueError):
            build_track_model([a, b])
