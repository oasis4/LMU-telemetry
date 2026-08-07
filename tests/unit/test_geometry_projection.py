import numpy as np
import pytest

from lmu_telemetry.core.geometry import (
    GRID_STEP_M,
    grid_for,
    project_enu,
    resample_to_grid,
)


def test_projection_turns_degrees_into_metres():
    """One degree of latitude is about 111.3 km anywhere."""
    lat = np.array([60.0, 60.001])
    lon = np.array([0.0, 0.0])
    x, y = project_enu(lat, lon)
    assert (y[1] - y[0]) == pytest.approx(111.32, abs=0.5)
    assert x[1] == pytest.approx(x[0], abs=1e-6)


def test_longitude_is_scaled_by_the_cosine_of_latitude():
    """At 60 deg north a degree of longitude is half a degree of latitude."""
    lat = np.array([60.0, 60.0])
    lon = np.array([0.0, 0.001])
    x, y = project_enu(lat, lon)
    assert (x[1] - x[0]) == pytest.approx(111.32 * 0.5, abs=0.5)


def test_projection_is_centred_on_the_data():
    lat = np.array([59.99, 60.0, 60.01])
    lon = np.array([-0.01, 0.0, 0.01])
    x, y = project_enu(lat, lon)
    assert np.mean(x) == pytest.approx(0.0, abs=1e-6)
    assert np.mean(y) == pytest.approx(0.0, abs=1e-6)


def test_an_explicit_origin_is_used_instead_of_the_data_mean():
    lat = np.array([60.0, 60.001])
    lon = np.array([0.0, 0.0])
    x, y = project_enu(lat, lon, origin=(60.0, 0.0))
    assert y[0] == pytest.approx(0.0, abs=1e-6)
    assert y[1] == pytest.approx(111.32, abs=0.5)
    assert np.mean(y) != pytest.approx(0.0, abs=1.0)  # not re-centred


def test_one_origin_keeps_two_arrays_in_one_frame():
    """Two laps centred on their own means lose their relative offset entirely.

    This is why a median across per-lap frames is not a racing line: the
    offset between two laps - the thing the median is supposed to average
    out - is forced to exactly zero before the median ever sees it.
    """
    lon = np.array([0.0, 0.0])
    a_lat = np.array([60.0000, 60.0010])
    b_lat = np.array([60.0020, 60.0030])  # 222 m north of a

    _, ya = project_enu(a_lat, lon, origin=(60.0, 0.0))
    _, yb = project_enu(b_lat, lon, origin=(60.0, 0.0))
    assert (np.mean(yb) - np.mean(ya)) == pytest.approx(222.6, abs=1.0)

    _, ya_own = project_enu(a_lat, lon)
    _, yb_own = project_enu(b_lat, lon)
    assert (np.mean(yb_own) - np.mean(ya_own)) == pytest.approx(0.0, abs=1e-6)


def test_grid_spans_the_track_at_the_declared_step():
    g = grid_for(1000.0)
    assert g[0] == 0.0
    assert len(g) == 500
    assert g[1] - g[0] == GRID_STEP_M


def test_resampling_is_linear_between_samples():
    d = np.array([0.0, 100.0, 200.0])
    v = np.array([0.0, 10.0, 20.0])
    out = resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)
    assert np.allclose(out, [0.0, 5.0, 10.0, 15.0])


def test_resampling_rejects_unsorted_distance():
    """Out-of-order distance would silently produce nonsense."""
    d = np.array([0.0, 200.0, 100.0])
    v = np.array([0.0, 20.0, 10.0])
    with pytest.raises(ValueError):
        resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)


def test_resampling_rejects_input_that_stops_short_of_the_grid():
    """np.interp would extend the last value flat and invent the end."""
    d = np.array([0.0, 50.0, 100.0])
    v = np.array([0.0, 5.0, 10.0])
    with pytest.raises(ValueError, match="does not cover the grid"):
        resample_to_grid(d, v, track_length_m=400.0, step_m=50.0)


def test_resampling_rejects_input_that_starts_after_the_grid():
    d = np.array([100.0, 150.0, 200.0])
    v = np.array([10.0, 15.0, 20.0])
    with pytest.raises(ValueError, match="does not cover the grid"):
        resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)


def test_resampling_accepts_a_shortfall_inside_the_stated_tolerance():
    """Real samples do not land exactly on the grid's ends, so the caller
    states how far short they may fall - it is not this function's guess."""
    d = np.array([2.0, 100.0, 148.0])
    v = np.array([0.0, 10.0, 20.0])
    with pytest.raises(ValueError):
        resample_to_grid(d, v, track_length_m=200.0, step_m=50.0)
    out = resample_to_grid(d, v, track_length_m=200.0, step_m=50.0, tolerance_m=5.0)
    assert len(out) == 4
