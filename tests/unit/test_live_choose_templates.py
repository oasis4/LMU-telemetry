"""Which template builder a run actually uses, and what it is handed.

``_choose_templates`` is the one piece of task 6 that is authored rather than
transcribed from the brief: the auto-versus-explicit dispatch, the candidate
pool it assembles for the automatic path, and the label/exception handling in
``_candidate_source``. None of that is exercised by ``test_template.py`` or
``test_live_reference.py``, which only ever call ``live.template`` and
``live.reference`` directly - the same reason ``test_live_template_wiring.py``
exists for ``_show_template`` and ``_sound_if_due``.

The fixture recordings stand in for the game and the driver's own corpus:
``fixture_dir`` holds several real Monza GT3 sessions, so
``find_quickest_laps`` has a real pool to draw from without touching
``F:/...Telemetry``.
"""

from __future__ import annotations

from pathlib import Path

from lmu_telemetry.live.__main__ import _choose_templates, _trace_of
from lmu_telemetry.live.reference import Reference, find_reference
from lmu_telemetry.live.template import templates_for

MONZA = "Autodromo Nazionale Monza"


class _FakeLive:
    """Stands in for LiveTelemetry: only track_length_m() and car_class() are
    read by _choose_templates."""

    def __init__(self, length_m: float, car_class: str) -> None:
        self._length_m = length_m
        self._car_class = car_class

    def track_length_m(self) -> float:
        return self._length_m

    def car_class(self) -> str:
        return self._car_class


# -- the dispatch itself ------------------------------------------------------


def test_an_explicit_reference_is_built_with_templates_for_unmixed(monza_q_file):
    """auto_found=None is what --reference produces: the driver named a lap,
    and gets that lap, not a best-of-set assembled behind their back."""
    reference, model, _lap = _trace_of(monza_q_file, 2)

    built, line = _choose_templates(None, monza_q_file.parent, None, reference, model)

    expected = templates_for(reference, model.corners)
    assert len(built) == len(expected)
    assert line == f"{len(expected)} braked corners"
    assert all(template.source == "" for template in built)


def test_an_automatic_reference_is_built_with_the_best_of_set(
    fixture_dir, monza_q_file
):
    """auto_found set - the ordinary case, a circuit found from the running
    game - reaches for find_quickest_laps and best_templates instead."""
    found = find_reference(fixture_dir, MONZA, length_m=5776.0, car_class="GT3")
    reference, model, _lap = _trace_of(found.path, found.lap_number)
    live = _FakeLive(model.track_length_m, "GT3")

    built, line = _choose_templates(found, fixture_dir, live, reference, model)

    expected = templates_for(reference, model.corners)
    assert len(built) == len(expected), (
        "the best-of-set must cover exactly the events templates_for would"
    )
    assert "braking events from" in line
    assert "different laps contributed" in line


# -- the guarantee, exercised through the real dispatch, not just the unit ---
#
# live.template.test_best_templates_covers_every_event_even_with_no_candidates_at_all
# already pins this at the best_templates level. This is the integration
# check: a real find_quickest_laps call that finds nothing to scan, reached
# through _choose_templates exactly as main() reaches it, must still hand
# TemplateWatch the full set of strips rather than a thinned one.


def test_a_candidate_scan_that_finds_nothing_still_yields_every_event(
    monza_q_file, tmp_path
):
    reference, model, _lap = _trace_of(monza_q_file, 2)
    # A Reference naming a real lap, but pointed at a recordings directory
    # that holds none of the fixtures - tmp_path is empty - so
    # find_quickest_laps inside _choose_templates has nothing to return.
    stub_found = Reference(
        path=monza_q_file, lap_number=2, duration_s=111.0, track=MONZA
    )
    live = _FakeLive(model.track_length_m, "GT3")

    built, line = _choose_templates(stub_found, tmp_path, live, reference, model)

    expected = templates_for(reference, model.corners)
    assert len(built) == len(expected)
    assert {t.corner.index for t in built} == {t.corner.index for t in expected}
    assert "0 laps" in line
    assert "0 different laps contributed" in line


def test_a_candidate_scan_that_finds_nothing_still_needs_a_real_track(tmp_path):
    """Test-setup sanity: an empty recordings directory really does make
    find_quickest_laps return nothing, so the test above is exercising the
    fallback and not silently finding fixtures some other way."""
    from lmu_telemetry.live.reference import find_quickest_laps

    assert find_quickest_laps(tmp_path, MONZA) == []
