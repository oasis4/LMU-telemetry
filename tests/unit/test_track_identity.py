import numpy as np
import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, reference_line


def test_identity_combines_name_layout_and_length(monza_q_file):
    with Session.open(monza_q_file) as s:
        key = TrackKey.of(s)
    assert key.track == "Autodromo Nazionale Monza"
    assert key.layout == "Autodromo Nazionale Monza"
    assert key.length_bucket_m == 5780


def test_length_is_bucketed_so_lap_to_lap_scatter_does_not_split_a_track():
    """Le Mans measures 13619.4-13621.8 m across sessions - one track."""
    a = TrackKey("Circuit de la Sarthe", "Circuit de la Sarthe", 13620)
    b = TrackKey("Circuit de la Sarthe", "Circuit de la Sarthe", 13620)
    assert a == b
    assert hash(a) == hash(b)


def test_length_separates_layouts_that_share_a_name():
    short = TrackKey("Some Circuit", "Some Circuit", 3000)
    full = TrackKey("Some Circuit", "Some Circuit", 5000)
    assert short != full


def test_slug_is_filesystem_safe(monza_q_file):
    with Session.open(monza_q_file) as s:
        slug = TrackKey.of(s).slug()
    assert " " not in slug
    assert all(c.isalnum() or c in "-_" for c in slug)


def test_identity_is_none_without_a_track_length(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert TrackKey.of(s) is None


def test_reference_line_is_the_median_of_its_inputs():
    a = (np.array([0.0, 1.0, 2.0]), np.array([0.0, 0.0, 0.0]))
    b = (np.array([0.0, 2.0, 4.0]), np.array([1.0, 1.0, 1.0]))
    c = (np.array([0.0, 3.0, 6.0]), np.array([2.0, 2.0, 2.0]))
    x, y = reference_line([a, b, c])
    assert np.allclose(x, [0.0, 2.0, 4.0])
    assert np.allclose(y, [1.0, 1.0, 1.0])


def test_reference_line_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        reference_line([(np.zeros(3), np.zeros(3)), (np.zeros(4), np.zeros(4))])


def test_reference_line_rejects_an_empty_input():
    with pytest.raises(ValueError):
        reference_line([])
