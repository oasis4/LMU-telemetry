"""Frozen expectations. Any change that moves a lap time or a sector fails."""

import json
from pathlib import Path

import pytest

from lmu_telemetry.core.session import Session

GOLDEN = json.loads((Path(__file__).parent / "expected_laps.json").read_text())


@pytest.mark.parametrize("filename", sorted(GOLDEN))
def test_golden_session(fixture_dir, filename):
    expected = GOLDEN[filename]
    path = fixture_dir / filename
    assert path.is_file(), f"golden fixture missing: {path}"

    with Session.open(path) as s:
        info = s.info
        laps = s.laps
        length = s.track_length_m

    assert info.track == expected["track"]
    assert info.car_class == expected["car_class"]
    assert length == pytest.approx(expected["track_length_m"], abs=0.1)
    assert len(laps) == len(expected["laps"])

    for lap, exp in zip(laps, expected["laps"]):
        assert lap.number == exp["number"]
        assert lap.duration_s == pytest.approx(exp["duration_s"], abs=0.001)
        assert lap.touched_pits == exp["touched_pits"]
        assert lap.sectors_s == pytest.approx(tuple(exp["sectors_s"]), abs=0.001)
