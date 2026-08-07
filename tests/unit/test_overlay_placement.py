"""Where the panel lands, which is the whole difference between usable and not.

None of this needs a window: the placement is arithmetic on the screen size,
and it is the part that decides whether a driver on a 32:9 screen can read the
panel at all.
"""

import pytest

from lmu_telemetry.live.overlay import POSITIONS, Overlay

#: A 32:9 ultrawide, and an ordinary 16:9 one.
ULTRAWIDE = (5120, 1440)
NORMAL = (1920, 1080)


def _place(position, screen, width=500, height=200, margin=28):
    return Overlay._place(position, screen[0], screen[1], width, height, margin)


def test_the_default_sits_near_the_middle_of_a_wide_screen():
    """A top-left panel on a 32:9 screen is two and a half thousand pixels
    from where the driver is looking. That is not peripheral vision."""
    x, _y = _place("top-center", ULTRAWIDE, width=500)
    centre = ULTRAWIDE[0] / 2
    assert abs((x + 250) - centre) <= 1

    far_left, _ = _place("top-left", ULTRAWIDE, width=500)
    assert centre - (far_left + 250) > 2000, "this is what the default avoids"


def test_every_position_keeps_the_whole_panel_on_the_screen():
    for position in POSITIONS:
        for screen in (ULTRAWIDE, NORMAL):
            x, y = _place(position, screen, width=500, height=200)
            assert 0 <= x, (position, screen, x)
            assert x + 500 <= screen[0], (position, screen, x)
            assert 0 <= y, (position, screen, y)
            assert y + 200 <= screen[1], (position, screen, y)


def test_top_and_bottom_go_to_opposite_ends():
    top = _place("top-center", NORMAL, height=200)[1]
    bottom = _place("bottom-center", NORMAL, height=200)[1]
    assert top < bottom
    assert bottom + 200 <= NORMAL[1]


def test_left_and_right_go_to_opposite_ends():
    left = _place("top-left", NORMAL, width=500)[0]
    right = _place("top-right", NORMAL, width=500)[0]
    assert left < right
    assert right + 500 <= NORMAL[0]


def test_an_unknown_position_is_refused_by_name():
    """Rather than silently landing somewhere. A panel in the wrong place is
    a panel the driver never looks at."""
    with pytest.raises(ValueError, match="position must be one of"):
        Overlay(position="middle-of-nowhere")
