import pytest

from lmu_telemetry.api.pool import SessionPool


def test_the_same_recording_is_opened_once(monza_q_file):
    pool = SessionPool()
    try:
        assert pool.get(monza_q_file) is pool.get(monza_q_file)
        assert len(pool) == 1
    finally:
        pool.close()


def test_the_pool_does_not_grow_past_its_limit(monza_q_file, position_jump_file,
                                               zero_winding_file):
    """The old server kept every session it had ever loaded, for ever."""
    pool = SessionPool(max_open=2)
    try:
        pool.get(monza_q_file)
        pool.get(position_jump_file)
        pool.get(zero_winding_file)
        assert len(pool) == 2
    finally:
        pool.close()


def test_eviction_closes_the_recording_it_drops(monza_q_file, position_jump_file):
    """A DuckDB connection is an operating-system handle. Dropping the
    reference and leaving it to the garbage collector leaks it.

    The exception type is named rather than caught broadly: `raises(Exception)`
    would also pass if the evicted session failed for some unrelated reason,
    and would then prove nothing about eviction.
    """
    import duckdb

    pool = SessionPool(max_open=1)
    try:
        first = pool.get(monza_q_file)
        assert first.file.channel("Lap Dist") is not None    # open before eviction
        pool.get(position_jump_file)
        with pytest.raises(duckdb.ConnectionException):
            first.file.raw_channel("Ground Speed")
    finally:
        pool.close()


def test_the_least_recently_used_recording_is_the_one_evicted(
    monza_q_file, position_jump_file, zero_winding_file
):
    pool = SessionPool(max_open=2)
    try:
        first = pool.get(monza_q_file)
        pool.get(position_jump_file)
        pool.get(monza_q_file)          # first is used again, so it is not oldest
        pool.get(zero_winding_file)     # this evicts position_jump_file
        assert pool.get(monza_q_file) is first
        assert len(pool) == 2
    finally:
        pool.close()


def test_a_track_model_is_built_once_per_identity(monza_q_file):
    """Corners were re-detected on every request; a track does not move."""
    pool = SessionPool()
    try:
        session = pool.get(monza_q_file)
        assert pool.model_for(session) is pool.model_for(session)
    finally:
        pool.close()


def test_a_pool_that_cannot_hold_anything_is_refused():
    with pytest.raises(ValueError):
        SessionPool(max_open=0)


def test_closing_releases_everything(monza_q_file):
    pool = SessionPool()
    pool.get(monza_q_file)
    pool.close()
    assert len(pool) == 0
