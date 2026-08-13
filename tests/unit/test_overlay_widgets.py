"""The real ``Overlay``, not a fake: what ``_set_content`` actually packs
and forgets.

``test_overlay_layout.py`` pins ``_widget_order``, the pure decision of
which widgets *should* be visible for a content state, without a window.
``test_live_template_wiring.py`` drives that decision through
``_show_template``, but against a ``_FakeOverlay`` that reimplements the
bookkeeping (a ``content`` attribute set by hand) rather than exercising the
widgets ``Overlay`` itself packs and forgets. Neither ever constructs a real
``Overlay`` and calls ``_set_content``, ``show_template``, ``show_finding``,
or ``hide_template`` on it.

That gap is not theoretical: a fix round in this feature's own history
shipped a Critical regression in exactly this layer - the mutual-exclusion
change silently dropped the coaching sentence for 8 of 11 corners at Monza
(see ``_widget_order``'s docstring and the design doc's "When it appears"
section) - and nothing in the committed suite would have caught it, because
nothing called the real packing code with real widgets.

Needs an actual window - tkinter, and a display to open one on - so every
test here goes through the ``overlay`` fixture below, which skips cleanly
(``pytest.importorskip``, then a guarded ``Tk()`` construction) rather than
failing on a machine that cannot make one, the same way the suite already
skips corpus-dependent tests via the fixtures in ``conftest.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")

from lmu_telemetry.core.corners import Corner
from lmu_telemetry.live.overlay import Overlay
from lmu_telemetry.live.template import Showing, Template

#: The widgets _set_content ever packs below the delta, keyed the same way
#: Overlay._widget_order names them - see its docstring for why these two
#: groups may never both be on screen.
_TEMPLATE_GROUP = ("entry", "strips")
_FINDING_GROUP = ("corner", "sentence")


def _corner(index: int = 1, name: str = "T1",
            start_m: float = 950.0, end_m: float = 1100.0) -> Corner:
    return Corner(index=index, name=name, start_m=start_m,
                  apex_m=(start_m + end_m) / 2, end_m=end_m,
                  radius_m=60.0, heading_deg=90.0, direction="L")


def _showing(index: int = 1, name: str = "T1", past_corner: bool = False) -> Showing:
    """A minimal, self-consistent Showing - enough for show_template to draw
    something, not a claim about any real corner."""
    offsets = np.arange(0.0, 401.0, 2.0)
    template = Template(
        corner=_corner(index=index, name=name), start_m=700.0, length_m=400.0,
        brake_at_m=100.0, entry_at_m=250.0, entry_speed_kmh=180.0,
        offsets_m=offsets, abs_m=offsets + 700.0,
        brake=np.linspace(0.0, 1.0, len(offsets)),
        throttle=np.linspace(1.0, 0.0, len(offsets)),
    )
    return Showing(template, at_m=100.0, past_corner=past_corner)


def _open_overlay() -> Overlay:
    """A real Overlay, or a clean skip on a machine that cannot make one.

    Caught narrowly on ``tk.TclError`` - the error Tk itself raises when it
    cannot open a window (no display, no desktop session) - rather than a
    bare ``except Exception``, so a genuine bug in ``Overlay.__init__``
    still fails these tests instead of being swallowed as "no display".
    """
    try:
        return Overlay(position="top-center", scale=1.0)
    except tk.TclError as exc:
        pytest.skip(f"cannot open a window on this machine: {exc}")


@pytest.fixture
def overlay():
    """A real Overlay, torn down after the test.

    Destroyed even on failure - a leaked ``Tk()`` window is a leaked window
    handle every later test in the same run would also carry.
    """
    made = _open_overlay()
    try:
        yield made
    finally:
        made.close()


def _packed(one: Overlay) -> "list[str]":
    """The optional-group widget names currently packed under the card, in
    pack order.

    Read from ``pack_slaves()`` on the widgets' own parent frame - reached
    via ``one.delta.master``, since ``card`` itself is a local variable in
    ``Overlay.__init__`` and not kept as an attribute - rather than
    ``winfo_ismapped()``. Mapping only becomes true after a window-manager
    cycle (``root.update()``), which these tests do not run and should not
    need to: ``pack()``/``pack_forget()`` update the geometry manager's own
    bookkeeping synchronously, and that bookkeeping is exactly what
    ``_set_content`` is responsible for getting right.
    """
    slaves = set(one.delta.master.pack_slaves())
    return [
        name for name in ("delta", "entry", "strips", "corner", "sentence")
        if one._widgets[name] in slaves
    ]


def test_the_strip_and_the_sentence_are_never_packed_together(overlay):
    overlay.show_template(_showing(), own_brake=[], own_throttle=[])
    packed = set(_packed(overlay))
    assert packed & set(_TEMPLATE_GROUP), "the strip should be up"
    assert not (packed & set(_FINDING_GROUP)), (
        "the finding's widgets must not still be packed once the strip is up"
    )

    overlay.show_finding("T1", "You can brake later here")
    packed = set(_packed(overlay))
    assert packed & set(_FINDING_GROUP), "the sentence should be up"
    assert not (packed & set(_TEMPLATE_GROUP)), (
        "the strip's widgets must not still be packed once the sentence is up"
    )


def test_a_sentence_shown_after_a_template_replaces_it_and_clears_its_widgets(overlay):
    """The exact shape of the regression this file exists for: a sentence
    arriving while a template is up must actually unpack the template's
    widgets, not just claim the content slot while entry/strips stay
    mapped underneath it."""
    overlay.show_template(_showing(), own_brake=[], own_throttle=[])
    assert overlay.content == "template"
    for name in _TEMPLATE_GROUP:
        assert overlay._widgets[name].winfo_manager() == "pack", name

    overlay.show_finding("T1", "You can brake later here")

    assert overlay.content == "finding"
    for name in _TEMPLATE_GROUP:
        assert overlay._widgets[name].winfo_manager() == "", (
            f"{name} should have been pack_forget()'d when the sentence took the slot"
        )
    for name in _FINDING_GROUP:
        assert overlay._widgets[name].winfo_manager() == "pack", name


def test_a_template_shown_after_a_sentence_replaces_it_and_clears_its_widgets(overlay):
    """The other direction: a freshly armed window must evict a sentence
    that is currently up, and actually clear its widgets - not just the
    finding-then-template direction the previous test covers."""
    overlay.show_finding("T1", "You can brake later here")
    assert overlay.content == "finding"
    for name in _FINDING_GROUP:
        assert overlay._widgets[name].winfo_manager() == "pack", name

    overlay.show_template(_showing(), own_brake=[], own_throttle=[])

    assert overlay.content == "template"
    for name in _FINDING_GROUP:
        assert overlay._widgets[name].winfo_manager() == "", (
            f"{name} should have been pack_forget()'d when the strip took the slot"
        )
    for name in _TEMPLATE_GROUP:
        assert overlay._widgets[name].winfo_manager() == "pack", name


def test_the_widget_order_is_the_same_whichever_was_shown_first(overlay):
    """test_overlay_layout.py pins this for the pure _widget_order function;
    this pins the same property for the real, stateful _set_content that
    drives it - reaching "finding" by two different routes on one Overlay
    must leave tkinter's own pack order identical, not merely
    _widget_order's answer identical.

    Driven on a single Overlay rather than two separately-constructed ones:
    _set_content(None) puts it back in the empty-slot state directly - the
    same state a fresh Overlay starts in - so the second route is exercised
    for real without a second Tk() window, which this machine can construct
    reliably but which is needless churn for what this test is actually
    checking (order, not construction).
    """
    overlay.show_template(_showing(), own_brake=[], own_throttle=[])
    overlay.show_finding("T1", "You can brake later here")
    via_template_first = _packed(overlay)

    overlay._set_content(None)
    overlay.show_finding("T1", "You can brake later here")
    via_finding_only = _packed(overlay)

    assert via_template_first == via_finding_only == ["delta", "corner", "sentence"]


def test_the_reference_line_sits_above_the_delta_and_stays_there(overlay):
    """It names the lap the delta is measured against - who drove it, when,
    on how much fuel, and what it took. Above the delta because it is what
    the delta means, and permanent because that does not change while the
    driver is out.

    Pinned against the content arbitration, which is where a permanent
    widget would be lost: this feature's own history has a regression in
    exactly that layer, where packing order depended on which of two methods
    had been called last.
    """
    overlay.show_reference("A Mueller  27.03.26  12 L  1:50.700")
    assert overlay.reference.cget("text").startswith("A Mueller")

    order = list(overlay.delta.master.pack_slaves())
    assert order.index(overlay.reference) < order.index(overlay.delta)

    for show in (
        lambda: overlay.show_template(_showing(), own_brake=[], own_throttle=[]),
        lambda: overlay.show_finding("T1", "You can brake later here"),
        overlay.hide_template,
        lambda: overlay.show_template(_showing(), own_brake=[], own_throttle=[]),
    ):
        show()
        slaves = list(overlay.delta.master.pack_slaves())
        assert overlay.reference in slaves, "the reference line was evicted"
        assert slaves.index(overlay.reference) < slaves.index(overlay.delta)
        assert overlay.reference.cget("text").startswith("A Mueller")
