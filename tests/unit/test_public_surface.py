"""The package's front door.

Stage 5 and the frontend import from here rather than reaching into modules,
so what this exposes is a commitment. These tests keep the list honest: that
every name in ``__all__`` actually exists, and that the whole pipeline can be
driven through it without importing anything private.
"""

import pytest

import lmu_telemetry.core as core


def test_every_exported_name_exists():
    missing = [name for name in core.__all__ if not hasattr(core, name)]
    assert missing == []


def test_the_export_list_is_sorted_and_unique():
    """A list kept in order is one people can find things in, and a duplicate
    is a merge that went wrong."""
    assert core.__all__ == sorted(core.__all__)
    assert len(core.__all__) == len(set(core.__all__))


def test_a_whole_comparison_runs_through_the_public_names_alone(monza_q_file):
    """Open a recording, build the circuit, compare two laps - no private
    imports. If this needs one, the front door is missing something."""
    with core.Session.open(monza_q_file) as session:
        model = core.build_track_model([session])
        assert model is not None and model.corners

        laps = [lap for lap in core.clean_laps(session)][:2]
        assert len(laps) == 2

        traces = [
            core.build_trace(session, lap, model.track_length_m) for lap in laps
        ]
        delta = core.delta_s(*traces)
        assert len(delta) == len(traces[0].grid)

        comparisons = core.compare_corners(*traces, model.corners)
        assert len(comparisons) == len(model.corners)
        assert all(isinstance(c.summary, str) and c.summary for c in comparisons)

        worst = core.biggest_losses(comparisons, 1)
        assert len(worst) == 1


def test_the_summary_of_every_corner_names_the_corner(monza_q_file):
    with core.Session.open(monza_q_file) as session:
        model = core.build_track_model([session])
        laps = core.clean_laps(session)[:2]
        traces = [core.build_trace(session, l, model.track_length_m) for l in laps]
        for comparison in core.compare_corners(*traces, model.corners):
            assert comparison.corner.name in comparison.summary


def test_metrics_are_reachable_and_agree_with_the_comparison(monza_q_file):
    with core.Session.open(monza_q_file) as session:
        model = core.build_track_model([session])
        laps = core.clean_laps(session)[:2]
        traces = [core.build_trace(session, l, model.track_length_m) for l in laps]
        direct = core.lap_metrics(traces[1], model.corners)
        through = [c.other for c in core.compare_corners(*traces, model.corners)]

    for a, b in zip(direct, through):
        assert a.corner is b.corner
        assert a.min_speed_kmh == pytest.approx(b.min_speed_kmh)
        assert a.brake_point_m == b.brake_point_m
