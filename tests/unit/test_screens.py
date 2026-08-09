"""Which screen the panel belongs on.

A driver with two monitors has the game on one of them, and a panel that
appears on the other is a panel that does not exist as far as driving is
concerned. Tk only ever reports the primary monitor's size, so the answer has
to come from Windows.
"""

import pytest

from lmu_telemetry.live.overlay import Overlay
from lmu_telemetry.live.screens import Monitor, monitors, monitor_holding

#: Two 2752x1152 screens side by side, the left one primary. The layout on the
#: machine this was written for, and the case Tk gets wrong.
LEFT = Monitor(index=0, x=0, y=0, width=2752, height=1152, primary=True)
RIGHT = Monitor(index=1, x=2752, y=0, width=2752, height=1152, primary=False)
PAIR = [LEFT, RIGHT]


def test_a_point_on_the_second_screen_is_not_read_as_the_first():
    """The whole bug: an x of 3000 is off the right edge of the primary and
    well inside the secondary."""
    assert monitor_holding(3000, 500, PAIR) is RIGHT
    assert monitor_holding(100, 500, PAIR) is LEFT


def test_a_point_on_no_screen_is_nobody_s():
    assert monitor_holding(-4000, 500, PAIR) is None
    assert monitor_holding(100, 9000, PAIR) is None


def test_the_edges_belong_to_exactly_one_screen():
    """2752 is the last column of the left screen plus one, and the first of
    the right. Counted by both, a window on the seam would flicker between."""
    assert monitor_holding(2751, 0, PAIR) is LEFT
    assert monitor_holding(2752, 0, PAIR) is RIGHT


# -- placing the panel on a chosen screen ----------------------------------


def test_the_panel_is_placed_inside_the_screen_it_was_given():
    """Placement used to be computed from a width alone, which is the same as
    assuming every screen starts at x=0 - true only of the primary."""
    x, y = Overlay._place("top-center", RIGHT, width=600, height=200, margin=28)
    assert RIGHT.x <= x <= RIGHT.x + RIGHT.width - 600
    assert x == 2752 + (2752 - 600) // 2


def test_the_primary_screen_places_where_it_always_did():
    """A one-monitor driver must see no change at all."""
    x, y = Overlay._place("top-center", LEFT, width=600, height=200, margin=28)
    assert (x, y) == ((2752 - 600) // 2, 28)


@pytest.mark.parametrize("position,expected_x", [
    ("top-left", 2752 + 28),
    ("top-right", 2752 + 2752 - 600 - 28),
    ("top-center", 2752 + (2752 - 600) // 2),
])
def test_every_horizontal_position_stays_on_the_chosen_screen(position, expected_x):
    x, _ = Overlay._place(position, RIGHT, width=600, height=200, margin=28)
    assert x == expected_x


def test_the_bottom_positions_measure_from_that_screen_s_bottom():
    _, y = Overlay._place("bottom-center", RIGHT, width=600, height=200, margin=28)
    assert y == 1152 - 200 - 28


# -- against the real machine ----------------------------------------------


def test_windows_reports_at_least_one_screen():
    found = monitors()
    assert found, "no monitors reported at all"
    assert sum(1 for m in found if m.primary) == 1, "exactly one is primary"
    for at, screen in enumerate(found):
        assert screen.index == at
        assert screen.width > 0 and screen.height > 0


def test_every_reported_screen_holds_its_own_middle():
    """A rectangle that does not contain its own centre is not a rectangle."""
    found = monitors()
    for screen in found:
        middle_x = screen.x + screen.width // 2
        middle_y = screen.y + screen.height // 2
        assert monitor_holding(middle_x, middle_y, found) is screen


# -- telling the game from everything else ---------------------------------


def test_the_editor_this_is_written_in_is_not_the_game():
    """It was, for a minute. This project lives in a folder called
    LMU-telemetry, so a window-title search for "lmu" picks the editor - which
    sits on the primary screen and sent the panel straight back there."""
    from lmu_telemetry.live.screens import is_game_image

    assert not is_game_image(r"C:\Program Files\Microsoft VS Code\Code.exe")
    assert not is_game_image(r"C:\...\msedge.exe")
    assert not is_game_image(r"C:\lmu-telemetry\python.exe")


def test_the_game_is_recognised_wherever_it_is_installed():
    from lmu_telemetry.live.screens import is_game_image

    assert is_game_image(
        r"F:\SteamLibrary\steamapps\common\Le Mans Ultimate\Le Mans Ultimate.exe"
    )
    assert is_game_image("/somewhere/else/Le Mans Ultimate.exe")
    assert is_game_image(r"D:\games\LE MANS ULTIMATE.EXE"), "case must not matter"


def test_a_name_that_merely_contains_the_game_s_is_not_the_game():
    """Matched on the whole stem. A launcher or a mod manager named after the
    game is not the window the driver is looking at."""
    from lmu_telemetry.live.screens import is_game_image

    assert not is_game_image(r"C:\x\Le Mans Ultimate Launcher.exe")
    assert not is_game_image(r"C:\x\My Le Mans Ultimate Tool.exe")
    assert not is_game_image("")
