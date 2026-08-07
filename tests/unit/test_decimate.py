import numpy as np
import pytest

from lmu_telemetry.api.decimate import TARGET_POINTS, bucket_count, decimate


def _series(n: int, **extra):
    base = {"distance": np.arange(n, dtype=float), "speed": np.zeros(n)}
    base.update({k: np.asarray(v, dtype=float) for k, v in extra.items()})
    return base


def test_a_trace_already_small_enough_is_returned_whole():
    series = _series(500)
    out = decimate(series, by="speed")
    assert len(out["speed"]) == 500
    assert np.array_equal(out["distance"], series["distance"])


def test_a_long_trace_comes_back_near_the_target():
    out = decimate(_series(60_000), by="speed")
    assert len(out["speed"]) <= TARGET_POINTS
    assert len(out["speed"]) >= TARGET_POINTS // 4


def test_a_single_sample_spike_survives():
    """Every nth sample would miss this, and it is the whole point of the trace.

    On telemetry a one-sample extreme is where the driver locked a wheel. A
    reduction that can drop it makes the chart a liar rather than a summary.
    """
    speed = np.full(60_000, 200.0)
    speed[31_337] = 12.0
    out = decimate(_series(60_000, speed=speed), by="speed")
    assert out["speed"].min() == pytest.approx(12.0)


def test_a_single_sample_peak_survives_too():
    speed = np.full(60_000, 200.0)
    speed[7_001] = 340.0
    out = decimate(_series(60_000, speed=speed), by="speed")
    assert out["speed"].max() == pytest.approx(340.0)


def test_every_series_is_reduced_on_the_same_samples():
    """Two series thinned independently no longer line up, and a comparison
    of them is then between different places on the track."""
    n = 40_000
    speed = np.sin(np.linspace(0, 40, n)) * 100 + 200
    brake = np.cos(np.linspace(0, 40, n))
    out = decimate(_series(n, speed=speed, brake=brake), by="speed")

    kept = out["distance"].astype(int)
    assert np.array_equal(out["speed"], speed[kept])
    assert np.array_equal(out["brake"], brake[kept])


def test_the_kept_samples_stay_in_order_and_are_not_repeated():
    out = decimate(_series(50_000, speed=np.random.default_rng(0).random(50_000)),
                   by="speed")
    distance = out["distance"]
    assert np.all(np.diff(distance) > 0)


def test_the_first_and_last_sample_are_always_kept():
    """A chart that starts at the second bucket has lost the start/finish line.

    The bucket loop provides this rather than a special case: the first bucket
    contributes sample 0 and the last contributes n-1.
    """
    n = 30_000
    speed = np.random.default_rng(1).random(n)
    out = decimate(_series(n, speed=speed), by="speed")
    assert out["distance"][0] == 0.0
    assert out["distance"][-1] == float(n - 1)


def test_series_of_different_lengths_are_refused():
    series = {"distance": np.zeros(10), "speed": np.zeros(9)}
    with pytest.raises(ValueError):
        decimate(series, by="speed")


def test_an_unknown_reference_series_is_refused():
    with pytest.raises(KeyError):
        decimate(_series(100), by="nope")


def test_bucket_count_leaves_room_for_four_points_each():
    assert bucket_count(10_000, 1500) == 375
    with pytest.raises(ValueError):
        bucket_count(10_000, 3)


def test_the_reduction_is_worth_making():
    """The measured problem was 5.31 MB per Le Mans comparison.

    Le Mans is 13.6 km, so a 2 m grid is 6811 points per series. Two laps with
    distance, speed, throttle, brake and delta is what a comparison sends.
    """
    n = 6811
    rng = np.random.default_rng(2)
    series = {name: rng.random(n) for name in
              ("distance", "speed_a", "speed_b", "throttle_a", "throttle_b",
               "brake_a", "brake_b", "delta")}
    out = decimate(series, by="delta")
    factor = n / len(out["delta"])
    assert factor > 4.0, f"only reduced by {factor:.1f}x"
