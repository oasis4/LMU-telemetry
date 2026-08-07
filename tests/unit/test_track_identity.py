import numpy as np
import pytest

from lmu_telemetry.core.session import Session, SessionInfo
from lmu_telemetry.core.track_model import TrackKey, build_track_model, reference_line


class _StubSession:
    """Minimal stand-in exposing only what TrackKey.of reads."""

    def __init__(self, track: str, layout: str, length: float | None) -> None:
        self.info = SessionInfo(
            track=track, layout=layout, car="", car_class="",
            driver="", session_type="", recorded_at="",
        )
        self.track_length_m = length


def test_identity_combines_name_and_layout(monza_q_file):
    with Session.open(monza_q_file) as s:
        key = TrackKey.of(s)
    assert key.track == "Autodromo Nazionale Monza"
    assert key.layout == "Autodromo Nazionale Monza"


def test_identity_does_not_depend_on_the_measured_length():
    """Le Mans measures 13619.4-13621.8 m across sessions. One track, one key.

    Length used to be bucketed into the key specifically to absorb this
    scatter. It no longer is - name and layout alone decide identity, so
    scatter of any size (as long as it doesn't cross the layout-agreement
    check in build_track_model) simply never reaches the key at all.
    """
    a = TrackKey.of(_StubSession("Circuit de la Sarthe", "Circuit de la Sarthe", 13619.4))
    b = TrackKey.of(_StubSession("Circuit de la Sarthe", "Circuit de la Sarthe", 13621.8))
    assert a == b
    assert hash(a) == hash(b)


def test_build_track_model_rejects_a_genuine_layout_collision():
    """A short and a full layout sharing a name must not silently average.

    TrackKey no longer separates them - see the test above, they now key
    equal. Catching this moved to build_track_model, the only place that
    sees every session of a track at once. Its length-agreement check runs
    before any lap/channel access, so a minimal stub exposing only what
    TrackKey.of and the length comparison read is enough to drive it here
    without needing real lap data.
    """
    short = _StubSession("Some Circuit", "Some Circuit", 3000.0)
    full = _StubSession("Some Circuit", "Some Circuit", 5000.0)
    with pytest.raises(ValueError):
        build_track_model([short, full])


def test_slug_is_filesystem_safe(monza_q_file):
    with Session.open(monza_q_file) as s:
        slug = TrackKey.of(s).slug()
    assert " " not in slug
    assert all(c.isalnum() or c in "-_" for c in slug)


def test_slug_cannot_collide_across_different_identities():
    a = TrackKey("A", "B-C").slug()
    b = TrackKey("A-B", "C").slug()
    assert a != b


def test_slug_handles_punctuation_and_stays_filesystem_safe():
    slug = TrackKey("Circuit de Spa-Francorchamps", "Grand Prix / 2024").slug()
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
