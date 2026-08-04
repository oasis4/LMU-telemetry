"""A bounded set of open recordings, and the models built from them.

The old server kept every session it had ever loaded in a dict that only grew,
and rebuilt a track's corners on every request. Both are fixed here for the
same reason: what a request needs is almost always what the last request
needed, and what it does not need must be let go of.

The pool is deliberately small and explicit rather than an ``lru_cache``
decorator. A DuckDB connection is an operating-system resource, so eviction
has to close it - a decorator would drop the reference and leave the handle to
the garbage collector.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from ..core.session import Session
from ..core.track_model import TrackKey, TrackModel, build_track_model

#: Recordings kept open at once. Each holds one DuckDB connection and its
#: cached channel arrays; eight covers a comparison and the sessions either
#: side of it without holding a whole afternoon's driving in memory.
DEFAULT_MAX_OPEN = 8


class SessionPool:
    """Open recordings, most recently used last, bounded in number.

    Safe to share between requests: every operation holds one lock, and a
    session is never closed while a caller still has it, because callers ask
    for it again rather than keeping it.
    """

    def __init__(self, max_open: int = DEFAULT_MAX_OPEN) -> None:
        if max_open < 1:
            raise ValueError(f"the pool must hold at least one session, got {max_open}")
        self.max_open = max_open
        self._sessions: "OrderedDict[Path, Session]" = OrderedDict()
        self._models: "dict[TrackKey, TrackModel]" = {}
        self._lock = threading.RLock()

    def get(self, path: "str | Path") -> Session:
        """The open recording at *path*, opening it if it is not already."""
        resolved = Path(path).resolve()
        with self._lock:
            existing = self._sessions.get(resolved)
            if existing is not None:
                self._sessions.move_to_end(resolved)
                return existing

            session = Session.open(resolved)
            self._sessions[resolved] = session
            while len(self._sessions) > self.max_open:
                _evicted, victim = self._sessions.popitem(last=False)
                victim.close()
            return session

    def model_for(self, session: Session) -> "TrackModel | None":
        """The reference model for *session*'s track, built once per identity.

        Corners were re-detected on every request before; a track's geometry
        does not change between them.
        """
        key = TrackKey.of(session)
        if key is None:
            return None
        with self._lock:
            cached = self._models.get(key)
            if cached is not None:
                return cached
            model = build_track_model([session])
            if model is not None:
                self._models[key] = model
            return model

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()
            self._models.clear()

    def __len__(self) -> int:
        return len(self._sessions)
