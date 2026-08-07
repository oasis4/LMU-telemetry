import json

import pytest

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.core.naming import (
    NAME_SANITY_M,
    _DATA_DIR,
    _slug,
    _tolerances,
    apply_names,
    load_names,
)


def _corner(index: int, apex_m: float) -> Corner:
    return Corner(
        index=index, name=f"T{index}", start_m=apex_m - 50.0,
        apex_m=apex_m, end_m=apex_m + 50.0, radius_m=80.0,
        heading_deg=60.0, direction="R",
    )


def _table_apex_values(track: str) -> list[float]:
    """Read a shipped table's apex_m values directly from its JSON file.

    Kept independent of load_names/CornerName so the test data cannot
    silently drift from what's actually shipped.
    """
    path = _DATA_DIR / f"{_slug(track)}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [float(e["apex_m"]) for e in data["corners"]]


def test_unknown_track_keeps_generic_names():
    corners = [_corner(1, 100), _corner(2, 500)]
    named = apply_names(corners, "Some Unlisted Circuit")
    assert [c.name for c in named] == ["T1", "T2"]


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
    assert all(hasattr(e, "apex_m") and hasattr(e, "name") for e in entries)


def test_full_table_names_every_corner_in_order():
    track = "Autodromo Nazionale Monza"
    apexes = _table_apex_values(track)
    entries = load_names(track)
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes)]

    named = apply_names(corners, track)

    assert [c.name for c in named] == [e.name for e in entries]


def test_count_mismatch_falls_back_to_generic_names():
    track = "Autodromo Nazionale Monza"
    apexes = _table_apex_values(track)
    # One fewer corner than the table has entries.
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes[:-1])]

    named = apply_names(corners, track)

    assert [c.name for c in named] == [f"T{i + 1}" for i in range(len(corners))]


def test_structural_mismatch_falls_back_for_all_corners():
    """A single wildly shifted apex must not just lose its own name -
    it must invalidate the whole match, since the ordering assumption
    has broken down for every corner, not just the shifted one."""
    track = "Autodromo Nazionale Monza"
    apexes = _table_apex_values(track)
    # Shift one apex far beyond NAME_SANITY_M (150 m).
    apexes[3] = apexes[3] + 300.0
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes)]

    named = apply_names(corners, track)

    assert [c.name for c in named] == [f"T{i + 1}" for i in range(len(corners))]


def test_legitimate_drift_still_names_correctly():
    """46 m is the measured worst-case apex drift across clean-lap set
    changes (Algarve); it must still resolve to the curated name.

    Applied to Curva Grande, whose neighbouring entries are several hundred
    metres away, so the drift stays well inside what the pairing supports.
    """
    track = "Autodromo Nazionale Monza"
    apexes = _table_apex_values(track)
    entries = load_names(track)
    grande = [e.name for e in entries].index("Curva Grande")
    apexes[grande] = apexes[grande] + 46.0
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes)]

    named = apply_names(corners, track)

    assert [c.name for c in named] == [e.name for e in entries]


def test_a_shift_inside_a_tight_cluster_invalidates_the_match():
    """The same 46 m drift is not legitimate inside a chicane.

    Monza's two Variante del Rettifilo entries are 40 m apart, so a corner
    displaced by 46 m sits closer to its neighbour's entry than to its own -
    the order-based pairing no longer has anything supporting it, and a
    single table-wide 150 m tolerance would have accepted it regardless.
    """
    track = "Autodromo Nazionale Monza"
    apexes = _table_apex_values(track)
    assert abs(apexes[1] - apexes[0]) < 46.0, "this test needs a tight cluster"
    apexes[0] = apexes[0] + 46.0
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes)]

    named = apply_names(corners, track)

    assert [c.name for c in named] == [f"T{i + 1}" for i in range(len(corners))]


def test_the_tolerance_of_a_clustered_entry_is_half_its_nearest_gap():
    """Stated directly, so the clamp is pinned and not merely implied."""
    entries = load_names("Autodromo Nazionale Monza")
    tolerances = _tolerances(entries)

    assert len(tolerances) == len(entries)
    gap = abs(entries[1].apex_m - entries[0].apex_m)
    assert tolerances[0] == pytest.approx(gap / 2.0)
    assert tolerances[1] == pytest.approx(gap / 2.0)
    # An entry with no near neighbour keeps the table-wide bound.
    isolated = max(range(len(entries)), key=lambda i: tolerances[i])
    assert tolerances[isolated] == NAME_SANITY_M
    assert all(t <= NAME_SANITY_M for t in tolerances)


@pytest.mark.parametrize(
    "track",
    ["Autodromo Nazionale Monza", "Circuit de la Sarthe", "Algarve International Circuit"],
)
def test_no_shipped_entry_is_closer_to_a_neighbour_than_its_own_tolerance(track):
    """Every shipped table stays within what its own spacing can support."""
    entries = load_names(track)
    for i, tolerance in enumerate(_tolerances(entries)):
        for j in (i - 1, i + 1):
            if 0 <= j < len(entries):
                gap = abs(entries[i].apex_m - entries[j].apex_m)
                assert tolerance <= gap / 2.0, (
                    f"{track} entry {i} ({entries[i].name}) tolerates {tolerance} m "
                    f"but sits {gap} m from {entries[j].name}"
                )


def test_portimao_horseshoe_carries_two_official_turn_numbers():
    """Portimao's 190-degree horseshoe is numbered as two turns on the map."""
    track = "Algarve International Circuit"
    apexes = _table_apex_values(track)
    corners = [_corner(i + 1, apex) for i, apex in enumerate(apexes)]

    named = apply_names(corners, track)

    assert named[12].name == "Turns 13-14"
