"""Frozen reference models. Any change that moves a corner fails here."""

import json
from collections import defaultdict
from pathlib import Path

import pytest

from lmu_telemetry.core.naming import apply_names
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, build_track_model

pytestmark = pytest.mark.corpus

GOLDEN = json.loads((Path(__file__).parent / "expected_track_models.json").read_text())

#: How far an apex may move before the model counts as changed. Generous
#: enough to absorb median-line jitter (measured at up to 46 m on Algarve when
#: the clean-lap set changes) but far tighter than the >100 m jump a corner
#: makes when it is wrongly split or merged - which is what this test guards.
APEX_TOLERANCE_M = 60.0


@pytest.fixture(scope="module")
def models(corpus_files):
    """One model per track, built from every clean lap in the corpus."""
    grouped = defaultdict(list)
    open_sessions = []
    try:
        for path in corpus_files:
            s = Session.open(path)
            open_sessions.append(s)
            key = TrackKey.of(s)
            if key is not None:
                grouped[key].append(s)
        out = {}
        for key, sessions in grouped.items():
            model = build_track_model(sessions)
            if model is None:
                continue
            assert key.track not in out, (
                f"{key.track} produced two track identities: {key} and "
                f"{out[key.track].key} - a single track must not split"
            )
            out[key.track] = model
        return out
    finally:
        for s in open_sessions:
            s.close()


@pytest.mark.parametrize("track", sorted(GOLDEN))
def test_track_model_matches_the_frozen_reference(models, track):
    expected = GOLDEN[track]
    assert track in models, f"no model built for {track}"
    model = models[track]

    assert model.track_length_m == pytest.approx(expected["track_length_m"], abs=2.0)
    assert model.closure_deg == pytest.approx(expected["closure_deg"], abs=10.0)
    assert len(model.corners) == expected["corner_count"], (
        f"{track}: expected {expected['corner_count']} corners, "
        f"got {len(model.corners)} at {[round(c.apex_m) for c in model.corners]}"
    )

    named = apply_names(model.corners, track)
    for corner, apex, name in zip(named, expected["apex_m"], expected["names"]):
        assert corner.apex_m == pytest.approx(apex, abs=APEX_TOLERANCE_M), (
            f"{track} {name}: apex moved from {apex} to {corner.apex_m:.0f} m"
        )
        assert corner.name == name


def test_monza_curva_grande_is_one_corner(models):
    """The regression this design was corrected for: prominence-based
    splitting halved this bend into two corners."""
    corners = models["Autodromo Nazionale Monza"].corners
    grande = [c for c in corners if 1250 < c.apex_m < 1750]
    assert len(grande) == 1
    assert grande[0].radius_m > 150.0
