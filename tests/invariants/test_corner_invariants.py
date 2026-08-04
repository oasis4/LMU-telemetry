"""Properties every track model must satisfy, whatever the track."""

from collections import defaultdict

import pytest

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, build_track_model

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def models(corpus_files):
    grouped = defaultdict(list)
    open_sessions = []
    try:
        for path in corpus_files:
            s = Session.open(path)
            open_sessions.append(s)
            key = TrackKey.of(s)
            if key is not None:
                grouped[key].append(s)
        return [m for m in (build_track_model(v) for v in grouped.values()) if m]
    finally:
        for s in open_sessions:
            s.close()


def test_at_least_three_tracks_produced_a_model(models):
    assert len(models) >= 3


def test_corners_are_ordered_and_do_not_overlap(models):
    for model in models:
        for a, b in zip(model.corners, model.corners[1:]):
            assert a.end_m <= b.start_m, f"{model.key.track}: {a.name} overlaps {b.name}"


def test_every_apex_lies_inside_its_own_corner(models):
    for model in models:
        for c in model.corners:
            assert c.start_m <= c.apex_m <= c.end_m, f"{model.key.track} {c.name}"


def test_every_corner_stays_within_the_track(models):
    for model in models:
        for c in model.corners:
            assert 0.0 <= c.start_m
            assert c.end_m <= model.track_length_m


def test_corners_are_tighter_than_the_radius_limit(models):
    from lmu_telemetry.core.corners import CORNER_MAX_RADIUS_M

    for model in models:
        for c in model.corners:
            assert c.radius_m < CORNER_MAX_RADIUS_M, f"{model.key.track} {c.name}"


def test_a_model_built_from_few_laps_says_so(models):
    from lmu_telemetry.core.track_model import MIN_CONFIDENT_LAPS

    for model in models:
        if model.lap_count < MIN_CONFIDENT_LAPS:
            assert model.confident is False
            assert model.warning
