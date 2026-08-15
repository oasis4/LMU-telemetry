"""Where the recordings are, when the caller does not say.

There are two answers and they are both right, in order.

``data/sessions`` is the curated working set - the sessions that still
contribute a clean lap, per layout, as ``tools/curate_corpus.py`` selects them.
It is what the invariants are measured against and what the API serves, so
where it exists it is the answer.

It does not always exist. A driver who has only ever run ``start.py`` has their
recordings where the game wrote them, and nowhere else. The launcher already
asked for that folder and wrote it into ``.telemetry_config.json``, so asking
again - or refusing to start - would be asking a question already answered.

Falling back is deliberately quiet in one direction only: a configured folder
that is *not there* is not offered, because an unmounted drive is not a place
the driver chose to keep recordings, and naming it would report a missing
directory they never asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The repository, from this file. The launcher writes its config beside it.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: The curated working set, relative to the repository.
WORKING_SET = Path("data") / "sessions"

#: Written by ``start.py`` when the driver picks their telemetry folder.
CONFIG_NAME = ".telemetry_config.json"
CONFIG_KEY = "telemetry_dir"


def configured_recordings_dir(root: "Path | None" = None) -> "Path | None":
    """The folder the launcher was pointed at, if it is still there.

    Unreadable, half-written, or missing the key: all the same answer, None.
    A launcher config is a convenience, and a damaged one is not worth raising
    over when there is a conventional place to fall back to.
    """
    config = (root or REPO_ROOT) / CONFIG_NAME
    try:
        named = json.loads(config.read_text(encoding="utf-8")).get(CONFIG_KEY)
    except (OSError, ValueError, AttributeError):
        return None
    if not named:
        return None
    folder = Path(named)
    return folder if folder.is_dir() else None


def default_recordings_dir(root: "Path | None" = None) -> Path:
    """Where to look for recordings, in order of what the project prefers.

    Always returns a path, never None. Where nothing can be found it names the
    working set - so the message the driver reads points at somewhere they
    recognise and can create, rather than at a blank.
    """
    conventional = (root or REPO_ROOT) / WORKING_SET
    if conventional.is_dir():
        return conventional
    return configured_recordings_dir(root) or conventional
