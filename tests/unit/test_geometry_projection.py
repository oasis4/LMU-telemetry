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
