"""Reduce a trace to what a screen can show, without losing what matters.

A Le Mans comparison at full resolution is 5.31 MB of JSON for two laps. A
chart is about 1500 pixels wide, so all but a few thousand of those points
land on a pixel that another point already occupies. Sending them costs the
network, the JSON parser and the browser's memory, and shows nothing.

The reduction keeps, for each bucket of samples, the **first, the minimum, the
maximum and the last**. That is deliberately not the obvious "take every nth
sample", and not a visually-optimised thinning either:

* Every nth sample can miss a brake spike entirely. On a telemetry trace the
  spike is frequently the whole point - it is where the driver locked a wheel.
* A thinning that optimises for how the line looks, such as LTTB, keeps the
  shape convincing but can still drop a one-sample extreme.

Keeping both extremes of every bucket means the drawn envelope contains every
sample that was measured: a reader can trust that no peak was removed. Keeping
the first and last as well means the line still passes through the bucket's
ends in the right order, so it does not zigzag.

Full resolution stays available and is what the corner detail and a zoomed
view ask for; this is only the default for an overview.
"""

from __future__ import annotations

import numpy as np

#: Points to aim for across a whole trace. A chart is about 1500 px wide.
TARGET_POINTS = 1500


def bucket_count(n_samples: int, target_points: int = TARGET_POINTS) -> int:
    """How many buckets *n_samples* should be reduced to for *target_points*.

    Each bucket contributes at most four points, so the bucket count is a
    quarter of the target. Below that many samples nothing is gained by
    reducing at all.
    """
    if target_points < 4:
        raise ValueError(f"target must leave room for one bucket, got {target_points}")
    return max(target_points // 4, 1)


def decimate(
    series: "dict[str, np.ndarray]",
    by: str,
    target_points: int = TARGET_POINTS,
) -> "dict[str, np.ndarray]":
    """Reduce every array in *series* on one shared set of indices.

    *by* names the series whose extremes decide which samples survive - the
    one a reader is looking for peaks in. Every other series is sampled at the
    same indices, so all of them stay aligned.

    Which samples to keep is decided **once** and applied to every series.
    Deciding per series would put the speed trace's points at different
    distances from the delta's, and the two could then no longer be read
    against each other - which is the entire purpose of a comparison.
    """
    if by not in series:
        raise KeyError(f"{by!r} is not among the series: {sorted(series)}")
    lengths = {name: len(values) for name, values in series.items()}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"series differ in length: {lengths}")

    n_samples = lengths[by]
    if n_samples <= target_points:
        return {name: np.asarray(values) for name, values in series.items()}

    keep = _indices(np.asarray(series[by], dtype=np.float64), n_samples, target_points)
    return {name: np.asarray(values)[keep] for name, values in series.items()}


def _indices(values: np.ndarray, n_samples: int, target_points: int) -> np.ndarray:
    buckets = bucket_count(n_samples, target_points)
    edges = np.linspace(0, n_samples, buckets + 1).astype(np.intp)

    # The first bucket contributes sample 0 and the last contributes n-1, so
    # the ends of the lap need no separate handling.
    keep: list[np.intp] = []
    for start, end in zip(edges[:-1], edges[1:]):
        if end <= start:
            continue
        window = values[start:end]
        keep.append(np.intp(start))
        keep.append(np.intp(start + int(np.argmin(window))))
        keep.append(np.intp(start + int(np.argmax(window))))
        keep.append(np.intp(end - 1))
    return np.unique(np.asarray(keep, dtype=np.intp))
