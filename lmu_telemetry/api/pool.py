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
from collections.abc import Iterable
from pathlib import Path

from ..core.session import Session
from ..core.track_model import (
    TrackKey,
    TrackModel,
    build_track_model,
    load_model,
    save_model,
)

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

    def __init__(
        self,
        max_open: int = DEFAULT_MAX_OPEN,
        model_cache_dir: "str | Path | None" = None,
    ) -> None:
        if max_open < 1:
            raise ValueError(f"the pool must hold at least one session, got {max_open}")
        self.max_open = max_open
        #: Where built models are kept between runs. Building one reads every
        #: recording of the circuit - measured at 16.7 s for Monza's 24 - so
        #: without this the first view after a restart pays that again.
        #: ``load_model`` discards anything stamped with another pipeline
        #: version, so a stale cache is a miss rather than a wrong answer.
        self.model_cache_dir = Path(model_cache_dir) if model_cache_dir else None
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

    def model_for(
        self, session: Session, siblings: "Iterable[Path] | None" = None
    ) -> "TrackModel | None":
        """The reference model for *session*'s track, built once per identity.

        Corners were re-detected on every request before; a track's geometry
        does not change between them.

        *siblings* are other recordings that may be of the same circuit. Every
        one that is contributes its clean laps, and that is not a refinement:
        the curated corner names are applied all-or-nothing, and they are
        dropped when the detected apexes drift further than the name table can
        absorb. One practice session of three laps drifts that far, so a model
        built from it alone comes back as T1..Tn - which is what the app showed
        before this. Recordings of other circuits are skipped by their key, so
        passing the whole directory is safe and costs one metadata read each.
        """
        key = TrackKey.of(session)
        if key is None:
            return None
        with self._lock:
            cached = self._models.get(key)
            if cached is not None:
                return cached

            if self.model_cache_dir is not None:
                stored = load_model(key, self.model_cache_dir)
                if stored is not None:
                    self._models[key] = stored
                    return stored

            # Siblings are opened outside the pool and closed again. Going
            # through the pool would evict up to its whole contents - including
            # the session this model is being built for - on any circuit with
            # more recordings than the pool holds.
            contributors, opened = [session], []
            own = session.file.path.resolve()
            try:
                for path in siblings or ():
                    if Path(path).resolve() == own:
                        continue
                    try:
                        other = Session.open(path)
                    except Exception:  # noqa: BLE001 - an unreadable one is skipped
                        continue
                    if TrackKey.of(other) == key:
                        opened.append(other)
                        contributors.append(other)
                    else:
                        other.close()
                model = build_track_model(contributors)
            finally:
                for other in opened:
                    other.close()

            if model is not None:
                self._models[key] = model
                if self.model_cache_dir is not None:
                    try:
                        save_model(model, self.model_cache_dir)
                    except OSError:
                        pass  # a cache that cannot be written is not an error
            return model

    def close(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()
            self._models.clear()

    def __len__(self) -> int:
        return len(self._sessions)
