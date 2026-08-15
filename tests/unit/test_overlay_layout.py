"""Which optional widgets are on screen, and in what order.

The panel cannot be constructed here - there is no display in the
environment these run in - so ``_widget_order`` is static and pure, the same
reason ``_strip_points`` and ``_place`` are: it is the decision, without the
window. ``_set_content`` (the real, stateful method that packs and forgets
actual widgets) is built directly on top of it, so what is tested here and
what actually gets drawn cannot drift apart.

The bug this exists for: a driver reported the panel growing, shrinking and
shifting around, steady only in the moment right before a corner. The cause
was that ``show_finding`` and ``show_template`` each packed their own pair of
widgets independently, and tkinter stacks in pack order - so whichever had
been called more recently sat higher, and the vertical order flipped corner
to corner.
"""

from lmu_telemetry.live.overlay import Overlay


def test_delta_always_leads():
    for content in (None, "template", "finding"):
        order = Overlay._widget_order(content)
        assert order[0] == "delta", content


def test_the_content_order_is_fixed_by_state_alone():
    assert Overlay._widget_order(None) == ("delta",)
    assert Overlay._widget_order("template") == ("delta", "entry", "strips")
    assert Overlay._widget_order("finding") == ("delta", "corner", "sentence")


def test_the_template_and_the_finding_are_never_both_shown():
    """At most one of the two optional groups appears, for every state -
    there is no state that asks for both."""
    for content in (None, "template", "finding"):
        order = set(Overlay._widget_order(content))
        template_group = {"entry", "strips"}
        finding_group = {"corner", "sentence"}
        assert not (template_group & order and finding_group & order), content


def test_the_reference_line_is_not_the_arbitration_s_to_take_down():
    """It names the lap the delta is measured against, and it is true for as
    long as the overlay runs. Leaving it out of _widget_order is what keeps
    it out of the content slot's reach: no state can evict it, and packing
    it once at construction costs no relayout when a strip or a sentence
    comes and goes."""
    for content in (None, "template", "finding"):
        assert "reference" not in Overlay._widget_order(content), content


def test_the_order_does_not_depend_on_which_was_shown_first():
    """The actual bug, restated as a property: the order for "template" is
    the same whether the panel arrived there fresh, from a finding, or from
    another template - because the order is a function of the current state
    alone, not of the sequence of calls that got here."""

    def order_after(sequence):
        # Only the last state matters to _widget_order - that is the point
        # being pinned: it takes no history, so there is nothing for the
        # call order to leave a mark on.
        return Overlay._widget_order(sequence[-1])

    assert (
        order_after([None, "template"])
        == order_after(["finding", "template"])
        == order_after(["template", "finding", "template"])
    )
    assert (
        order_after([None, "finding"])
        == order_after(["template", "finding"])
        == order_after(["finding", "template", "finding"])
    )
