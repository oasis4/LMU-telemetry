import numpy as np
import pytest

from lmu_telemetry.core.session import Session, SessionInfo
from lmu_telemetry.core.track_model import TrackKey, reference_line


class _StubSession:
    """Minimal stand-in exposing only what TrackKey.of reads."""

    def __init__(self, track: str, layout: str, length: float | None) -> None:
        self.info = SessionInfo(
            track=track, layout=layout, car="", car_class="",
            driver="", session_type="", recorded_at="",
        )
        self.track_length_m = length


def test_identity_combines_name_layout_and_length(monza_q_file):
    with Session.open(monza_q_file) as s:
        key = TrackKey.of(s)
    assert key.track == "Autodromo Nazionale Monza"
    assert key.layout == "Autodromo Nazionale Monza"
    assert key.length_bucket_m == 5780


def test_lap_to_lap_length_scatter_does_not_split_a_track():
    """Le Mans measures 13619.4-13621.8 m across sessions. One track, one key."""
    a = TrackKey.of(_StubSession("Circuit de la Sarthe", "Circuit de la Sarthe", 13619.4))
    b = TrackKey.of(_StubSession("Circuit de la Sarthe", "Circuit de la Sarthe", 13621.8))
    assert a == b
    assert hash(a) == hash(b)
    assert a.length_bucket_m == 13620


def test_genuinely_different_layouts_get_different_keys():
    """A short and a full layout sharing one name must not collapse."""
    short = TrackKey.of(_StubSession("Some Circuit", "Some Circuit", 3000.0))
    full = TrackKey.of(_StubSession("Some Circuit", "Some Circuit", 5000.0))
    assert short != full


def test_slug_is_filesystem_safe(monza_q_file):
    with Session.open(monza_q_file) as s:
        slug = TrackKey.of(s).slug()
    assert " " not in slug
    assert all(c.isalnum() or c in "-_" for c in slug)


def test_slug_cannot_collide_across_different_identities():
    a = TrackKey("A", "B-C", 5).slug()
    b = TrackKey("A-B", "C", 5).slug()
    assert a != b


def test_slug_handles_punctuation_and_stays_filesystem_safe():
    slug = TrackKey("Circuit de Spa-Francorchamps", "Grand Prix / 2024", 7004).slug()
    assert " " not in slug
    assert "/" not in slug
    assert all(c.isalnum() or c in "-_" for c in slug)


def test_identity_is_none_without_a_track_length(no_complete_lap_file):
    with Session.open(no_complete_lap_file) as s:
        assert TrackKey.of(s) is None


def test_reference_line_takes_the_median_not_the_mean():
    """One wild lap must not drag the reference geometry.

    Per sample the values are 0, 0 and 30: the median is 0, the mean 10.
    A mean implementation would place the reference line a third of the way
    towards a lap nobody else drove.
    """
    normal_a = (np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    normal_b = (np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    wild = (np.array([30.0, 30.0]), np.array([30.0, 30.0]))
    x, y = reference_line([normal_a, normal_b, wild])
    assert np.allclose(x, [0.0, 0.0])
    assert np.allclose(y, [0.0, 0.0])


def test_reference_line_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        reference_line([(np.zeros(3), np.zeros(3)), (np.zeros(4), np.zeros(4))])


def test_reference_line_rejects_an_empty_input():
    with pytest.raises(ValueError):
        reference_line([])
