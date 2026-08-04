"""Frozen reference models. Any change that moves a corner fails here."""

import json
from collections import defaultdict
from pathlib import Path

import pytest

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
    """One model per track identity, built from every clean lap in the corpus.

    Keyed by ``TrackKey.slug()``, because a track is not an identity: LMU
    ships two Monza layouts and two each at Sebring and Le Mans, and they are
    different circuits that happen to share a name. Keying by track name would
    make one of each pair overwrite the other.
    """
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
            assert key.slug() not in out, f"{key} produced two models"
            out[key.slug()] = model
        return out
    finally:
        for s in open_sessions:
            s.close()


@pytest.mark.parametrize("slug", sorted(GOLDEN))
def test_track_model_matches_the_frozen_reference(models, slug):
    expected = GOLDEN[slug]
    assert slug in models, f"no model built for {expected['track']} / {expected['layout']}"
    model = models[slug]

    assert model.track_length_m == pytest.approx(expected["track_length_m"], abs=2.0)
    # A lap that goes round once turns exactly 360 degrees, and the reference
    # line is a median of such laps. This is a tight bound on purpose: the
    # loose one it replaces hid a bias that grew with how much a track turned.
    assert model.closure_deg == pytest.approx(360.0, abs=0.5)
    assert len(model.corners) == expected["corner_count"], (
        f"{slug}: expected {expected['corner_count']} corners, "
        f"got {len(model.corners)} at {[round(c.apex_m) for c in model.corners]}"
    )

    # The model's own names, not names this test applied: build_track_model
    # is what has to produce a named model, since that is what save_model
    # persists and load_model serves.
    for corner, apex, name in zip(
        model.corners, expected["apex_m"], expected["names"]
    ):
        assert corner.apex_m == pytest.approx(apex, abs=APEX_TOLERANCE_M), (
            f"{slug} {name}: apex moved from {apex} to {corner.apex_m:.0f} m"
        )
        assert corner.name == name


def test_monza_curva_grande_is_one_corner(models):
    """The regression this design was corrected for: prominence-based
    splitting halved this bend into two corners."""
    corners = models["autodromo-nazionale-monza--autodromo-nazionale-monza"].corners
    grande = [c for c in corners if 1250 < c.apex_m < 1750]
    assert len(grande) == 1
    assert grande[0].radius_m > 150.0


def test_two_layouts_of_one_track_are_two_models(models):
    """Monza's full circuit and its Curva Grande layout are different tracks.

    They share a name and 5.7 km of length, so a model keyed on the track name
    alone would serve one where the other was asked for - and every corner
    position would be wrong by however much the layouts diverge.
    """
    full = models["autodromo-nazionale-monza--autodromo-nazionale-monza"]
    junior = models["autodromo-nazionale-monza--monza-curva-grande-circuit"]
    assert full.key.layout != junior.key.layout
    assert len(full.corners) != len(junior.corners)
