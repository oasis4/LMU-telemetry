import pytest

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.naming import apply_names, load_names


def _corner(index: int, apex_m: float) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=apex_m - 50.0,
        apex_m=apex_m, end_m=apex_m + 50.0, radius_m=80.0,
        heading_deg=60.0, direction="R",
    )


def test_known_track_gets_real_names():
    named = apply_names([_corner(1, 932), _corner(2, 5178)], "Autodromo Nazionale Monza")
    assert named[0].name == "Variante del Rettifilo 1"
    assert named[1].name == "Curva Parabolica"


def test_unknown_track_keeps_generic_names():
    corners = [_corner(1, 100), _corner(2, 500)]
    named = apply_names(corners, "Some Unlisted Circuit")
    assert [c.name for c in named] == ["T1", "T2"]


def test_one_arc_may_carry_two_official_turn_numbers():
    """Portimao's 190-degree horseshoe is numbered as two turns on the map."""
    named = apply_names([_corner(1, 3428)], "Algarve International Circuit")
    assert named[0].name == "Turns 13-14"


def test_a_corner_far_from_every_entry_keeps_its_generic_name():
    """A drifting apex must not silently borrow a neighbour's name."""
    named = apply_names([_corner(1, 4500)], "Autodromo Nazionale Monza")
    assert named[0].name == "T1"


def test_naming_does_not_alter_geometry():
    original = _corner(1, 932)
    named = apply_names([original], "Autodromo Nazionale Monza")[0]
    assert named.start_m == original.start_m
    assert named.apex_m == original.apex_m
    assert named.radius_m == original.radius_m


def test_load_names_returns_none_for_an_unknown_track():
    assert load_names("Some Unlisted Circuit") is None


@pytest.mark.parametrize(
    "track",
    ["Autodromo Nazionale Monza", "Circuit de la Sarthe", "Algarve International Circuit"],
)
def test_every_shipped_table_loads(track):
    entries = load_names(track)
    assert entries
    assert all("apex_m" in e and "name" in e for e in entries)
