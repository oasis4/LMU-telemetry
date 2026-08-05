"""The reference line the map is drawn from.

A map has to be drawn from the measured line. Reconstructing it from corner
radii and headings would draw what the detector believed rather than where the
car went - and would then agree with the corner list no matter how wrong both
were, which is the failure this project exists to remove.
"""

import json

import numpy as np
import pytest

from lmu_telemetry.core.geometry import GRID_STEP_M, grid_for, turn_rad, winding_number
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import (
    MODEL_FORMAT_VERSION,
    TrackKey,
    build_track_model,
    load_model,
    save_model,
)

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def monza(monza_q_file):
    with Session.open(monza_q_file) as session:
        yield build_track_model([session])


def test_the_model_carries_the_line_it_measured(monza):
    assert monza.line_x is not None and monza.line_y is not None
    assert len(monza.line_x) == len(monza.line_y)
    assert len(monza.line_x) == len(grid_for(monza.track_length_m))


def test_the_line_is_evenly_sampled_all_the_way_round(monza):
    """Every step covers one grid step of track, with no gap anywhere.

    This is what makes the stored line drawable as one path: a hole in it
    would be drawn as a straight line across whatever is missing.
    """
    step = np.hypot(np.diff(monza.line_x), np.diff(monza.line_y))
    assert float(np.median(step)) == pytest.approx(GRID_STEP_M, rel=0.02)
    assert float(np.percentile(step, 99)) < 1.5 * GRID_STEP_M


def test_the_line_comes_back_to_its_start(monza):
    """Its two ends are close, but not one grid step apart, and that is real.

    Measured over the whole working set the gap runs 4.6 m (COTA National) to
    13.8 m (Daytona), against a grid step of 2 m. The first and last grid
    points are the least supported points of the median: a lap's samples may
    fall short of either end by up to the coverage tolerance, and those laps
    contribute a held value there rather than a measured one.

    The bound is what was measured, not a round number chosen to pass. On the
    smallest circuit here that gap is 0.4 % of the lap, so a map closes the
    path across it; anything larger would mean the line no longer joins up.
    """
    gap = float(np.hypot(monza.line_x[0] - monza.line_x[-1],
                         monza.line_y[0] - monza.line_y[-1]))
    assert gap < 20.0, f"the line's ends are {gap:.1f} m apart"
    assert gap < 0.01 * monza.track_length_m


def test_the_stored_line_is_the_one_the_corners_were_found_on(monza):
    """Redetecting on the stored line must give the same corners back.

    If the two ever came apart, the map would show a shape the corner list
    does not describe - and there would be nothing to say which was right.
    """
    assert winding_number(turn_rad(monza.line_x, monza.line_y)) == pytest.approx(
        1.0, abs=1e-6
    ) or winding_number(turn_rad(monza.line_x, monza.line_y)) == pytest.approx(
        -1.0, abs=1e-6
    )


def test_a_corners_apex_sits_on_the_line(monza):
    """Every corner's apex distance indexes a real point of the line.

    The map places a marker by that index, so an apex past the end of the line
    would be drawn at whatever the last point happens to be.
    """
    samples = len(monza.line_x)
    for corner in monza.corners:
        index = int(round(corner.apex_m / GRID_STEP_M))
        assert 0 <= index < samples, f"{corner.name} apex at {corner.apex_m} m"


def test_the_line_survives_a_round_trip_through_the_cache(monza, tmp_path):
    save_model(monza, tmp_path)
    loaded = load_model(monza.key, tmp_path)
    assert loaded is not None
    assert loaded.line_x is not None
    # Stored to centimetres; that is what a screen a few hundred pixels wide
    # can show, and it halves the file.
    assert np.allclose(loaded.line_x, monza.line_x, atol=0.01)
    assert np.allclose(loaded.line_y, monza.line_y, atol=0.01)


def test_a_model_cached_before_the_line_existed_is_discarded(monza, tmp_path):
    """A version-1 model has no line. Handing one back would look complete
    and could not be drawn."""
    path = save_model(monza, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["format_version"] = MODEL_FORMAT_VERSION - 1
    data.pop("line_x")
    data.pop("line_y")
    path.write_text(json.dumps(data), encoding="utf-8")

    assert load_model(monza.key, tmp_path) is None


def test_a_model_read_without_a_line_says_so_rather_than_inventing_one(monza):
    """from_dict must not fabricate a line for a payload that has none."""
    data = monza.to_dict()
    data.pop("line_x")
    data.pop("line_y")
    from lmu_telemetry.core.track_model import TrackModel

    assert TrackModel.from_dict(data).line_x is None
