import numpy as np
import pytest

from lmu_telemetry.cache.store import (
    CACHE_FORMAT_VERSION,
    ArrayCache,
    CacheError,
    source_key,
)


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "session.duckdb"
    path.write_bytes(b"x" * 1024)
    return path


def test_a_stored_entry_comes_back_unchanged(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    arrays = {"speed": np.arange(10, dtype=float), "time": np.linspace(0, 1, 10)}
    key = source_key(recording)
    cache.store(key, "trace", arrays)

    loaded = cache.load(key, "trace")
    assert set(loaded) == {"speed", "time"}
    assert np.array_equal(loaded["speed"], arrays["speed"])


def test_nothing_stored_is_a_miss_not_an_error(tmp_path, recording):
    assert ArrayCache(tmp_path / "cache").load(source_key(recording), "trace") is None


def test_kinds_do_not_collide(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    key = source_key(recording)
    cache.store(key, "trace", {"a": np.zeros(3)})
    cache.store(key, "model", {"a": np.ones(3)})
    assert np.array_equal(cache.load(key, "trace")["a"], np.zeros(3))
    assert np.array_equal(cache.load(key, "model")["a"], np.ones(3))


def test_a_changed_recording_gets_a_different_key(tmp_path, recording):
    """The key is (path, mtime, size). Rewriting the file must invalidate it.

    Without this a replaced recording is served from the previous one's cache
    - and every number shown is then from a file the user no longer has.
    """
    before = source_key(recording)
    recording.write_bytes(b"y" * 2048)
    assert source_key(recording) != before


def test_two_recordings_of_the_same_size_have_different_keys(tmp_path):
    a, b = tmp_path / "a.duckdb", tmp_path / "b.duckdb"
    a.write_bytes(b"x" * 512)
    b.write_bytes(b"x" * 512)
    assert source_key(a) != source_key(b)


def test_a_key_for_a_missing_file_is_refused(tmp_path):
    """A key computed for a path that is not there would be valid, and would
    then be handed to whatever appears at that path next."""
    with pytest.raises(FileNotFoundError):
        source_key(tmp_path / "not-here.duckdb")


def test_an_entry_from_another_format_version_is_ignored(tmp_path, recording):
    """Cached geometry outlived a change to the geometry pipeline once in this
    project. A cache that serves results from code that no longer exists is a
    bug that only appears on machines which ran the old version.
    """
    cache = ArrayCache(tmp_path / "cache")
    key = source_key(recording)
    cache.store(key, "trace", {"a": np.zeros(3)})

    path = next((tmp_path / "cache").glob("*.npz"))
    with np.load(path, allow_pickle=False) as archive:
        stored = {name: archive[name] for name in archive.files}
    stored["__cache_format_version__"] = np.asarray(CACHE_FORMAT_VERSION + 1)
    np.savez_compressed(path, **stored)

    assert cache.load(key, "trace") is None


def test_an_entry_without_a_version_stamp_is_ignored(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    key = source_key(recording)
    cache.store(key, "trace", {"a": np.zeros(3)})
    path = next((tmp_path / "cache").glob("*.npz"))
    np.savez_compressed(path, a=np.zeros(3))
    assert cache.load(key, "trace") is None


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path, recording):
    """A half-written file from an interrupted run must not fail a request."""
    cache = ArrayCache(tmp_path / "cache")
    key = source_key(recording)
    cache.store(key, "trace", {"a": np.zeros(3)})
    next((tmp_path / "cache").glob("*.npz")).write_bytes(b"not an npz")
    assert cache.load(key, "trace") is None


def test_storing_leaves_no_temporary_file_behind(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    cache.store(source_key(recording), "trace", {"a": np.zeros(3)})
    assert list((tmp_path / "cache").glob("*.tmp")) == []


def test_the_reserved_version_name_cannot_be_stored(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache.store(
            source_key(recording), "trace", {"__cache_format_version__": np.zeros(1)}
        )


def test_a_directory_that_cannot_be_created_reports_why(tmp_path, recording):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    cache = ArrayCache(blocker / "cache")
    with pytest.raises(CacheError):
        cache.store(source_key(recording), "trace", {"a": np.zeros(3)})


def test_clear_removes_every_entry(tmp_path, recording):
    cache = ArrayCache(tmp_path / "cache")
    key = source_key(recording)
    cache.store(key, "trace", {"a": np.zeros(3)})
    cache.store(key, "model", {"a": np.zeros(3)})
    assert cache.clear() == 2
    assert cache.load(key, "trace") is None
