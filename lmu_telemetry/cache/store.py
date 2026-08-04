"""A disk cache for arrays derived from one recording.

The expensive part of answering a request is never the arithmetic - it is
reading a 40 MB DuckDB file and resampling it. Doing that once per recording
and reading the result back as a single ``.npz`` is what turns the second view
of a session into a file read.

The key is ``(resolved path, mtime_ns, size)``. All three, because none alone
is enough: a path is reused when a recording is replaced, mtime alone moves
when a file is merely touched, and size alone collides between two recordings
of the same length. If the recording changes in any of those ways the key
changes and the stale entry is simply never asked for again.

A stored entry also carries the code version that produced it. Cached geometry
outlived a change to the geometry pipeline once already in this project, and a
cache that serves results from code that no longer exists is worse than no
cache: it is a bug that only appears on machines that ran the old version.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

#: Bumped whenever a change makes previously cached arrays wrong. An entry
#: written under a different version is ignored, not migrated.
CACHE_FORMAT_VERSION = 1

_VERSION_KEY = "__cache_format_version__"


class CacheError(OSError):
    """Raised when the cache directory cannot be used, with the reason."""


def source_key(path: "str | Path") -> str:
    """A stable key for one recording, from its identity on disk.

    Raises ``FileNotFoundError`` rather than keying on a path that is not
    there: a key for a missing file would be perfectly valid and would then
    collide with whatever appears at that path next.
    """
    resolved = Path(path).resolve(strict=True)
    stat = resolved.stat()
    material = f"{resolved}|{stat.st_mtime_ns}|{stat.st_size}|v{CACHE_FORMAT_VERSION}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class ArrayCache:
    """Named arrays on disk, one ``.npz`` per (recording, kind).

    Nothing here decides *what* is worth caching; callers name a kind - the
    lap traces of a session, say - and hand over the arrays.
    """

    def __init__(self, directory: "str | Path") -> None:
        self.directory = Path(directory)

    def _path(self, key: str, kind: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in kind)
        return self.directory / f"{key}.{safe}.npz"

    def load(self, key: str, kind: str) -> "dict[str, np.ndarray] | None":
        """The stored arrays, or None if nothing usable is stored.

        A cache miss and a corrupt entry are the same answer on purpose: the
        caller can always recompute, and a half-written file left behind by an
        interrupted run must not be able to fail a request.
        """
        path = self._path(key, kind)
        if not path.is_file():
            return None
        try:
            with np.load(path, allow_pickle=False) as archive:
                stored = {name: archive[name] for name in archive.files}
        except (OSError, ValueError, EOFError):
            return None
        version = stored.pop(_VERSION_KEY, None)
        if version is None or int(version) != CACHE_FORMAT_VERSION:
            return None
        return stored

    def store(self, key: str, kind: str, arrays: "dict[str, np.ndarray]") -> Path:
        """Write *arrays* under (key, kind), replacing anything there.

        Written to a temporary file and renamed, so a reader either sees the
        previous entry or the new one - never half of either.
        """
        if _VERSION_KEY in arrays:
            raise ValueError(f"{_VERSION_KEY} is reserved for the cache itself")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CacheError(f"cannot use cache directory {self.directory}: {exc}") from exc

        path = self._path(key, kind)
        temporary = path.with_suffix(f".npz.{os.getpid()}.tmp")
        payload = dict(arrays)
        payload[_VERSION_KEY] = np.asarray(CACHE_FORMAT_VERSION)
        try:
            with open(temporary, "wb") as handle:
                np.savez_compressed(handle, **payload)
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise CacheError(f"cannot write {path}: {exc}") from exc
        return path

    def clear(self) -> int:
        """Delete every entry. Returns how many files were removed."""
        if not self.directory.is_dir():
            return 0
        removed = 0
        for path in self.directory.glob("*.npz"):
            path.unlink(missing_ok=True)
            removed += 1
        return removed
