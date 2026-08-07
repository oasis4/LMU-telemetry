"""Sort the recorded sessions into a working set and an archive.

Every file stays on disk. Sessions move into ``data/sessions`` or
``data/archive``; nothing is deleted, so a decision made here can be undone by
moving a file back.

What a session is judged on comes only from the file:

* how many of its laps survive ``assess_lap`` - laps the game itself timed,
  whose boundaries its own lap times confirm, and whose recorded position
  goes round the circuit once without jumping
* when it was recorded, from its metadata

Per track layout the working set keeps, in this order: the session holding
that layout's fastest clean lap, then the most recent sessions until
``TARGET_CLEAN_LAPS`` clean laps are in hand. A session with no clean lap is
archived whatever its date - it can contribute nothing to a reference model,
a comparison or a personal best.

    python tools/curate_corpus.py            # show the plan, move nothing
    python tools/curate_corpus.py --apply    # carry it out
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from lmu_telemetry.core.quality import assess_lap
from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
WORKING = DATA / "sessions"
ARCHIVE = DATA / "archive"
MANIFEST = DATA / "MANIFEST.json"

#: Clean laps to gather per layout before older sessions stop being kept.
#: A reference model is called confident at 3 laps, but its median line still
#: shifts perceptibly up to a few dozen; past that, added laps mostly confirm
#: what is already there.
TARGET_CLEAN_LAPS = 40


@dataclass
class Scanned:
    path: Path
    key: TrackKey | None
    recorded_at: str | None
    clean_laps: int
    total_laps: int
    best_clean_s: float | None
    reasons: dict[str, int]
    error: str | None = None


def scan(path: Path) -> Scanned:
    try:
        with Session.open(path) as session:
            reasons: dict[str, int] = defaultdict(int)
            clean, best = 0, None
            for lap in session.laps:
                quality = assess_lap(session, lap)
                if quality.is_clean:
                    clean += 1
                    if best is None or lap.duration_s < best:
                        best = lap.duration_s
                else:
                    reasons[_reason_kind(quality.reason)] += 1
            return Scanned(
                path=path,
                key=TrackKey.of(session),
                recorded_at=session.info.recorded_at,
                clean_laps=clean,
                total_laps=len(session.laps),
                best_clean_s=best,
                reasons=dict(reasons),
            )
    except Exception as exc:  # noqa: BLE001 - the manifest records why
        return Scanned(path, None, None, 0, 0, None, {}, f"{type(exc).__name__}: {exc}")


def _reason_kind(reason: str | None) -> str:
    """Collapse a reason to its kind, so counts stay readable."""
    if reason is None:
        return "unknown"
    for kind in (
        "touched the pit lane",
        "lap 0 runs from",
        "no lap time",
        "disagrees",
        "track lengths",
        "winds",
        "jumps",
        "does not cover",
        "position samples",
    ):
        if kind in reason:
            return kind
    return reason[:48]


def choose(scanned: list[Scanned]) -> tuple[list[Scanned], list[Scanned]]:
    """Split the scan into (working set, archive)."""
    by_layout: dict[TrackKey, list[Scanned]] = defaultdict(list)
    archive: list[Scanned] = []
    for item in scanned:
        if item.error is not None or item.key is None or item.clean_laps == 0:
            archive.append(item)
        else:
            by_layout[item.key].append(item)

    keep: list[Scanned] = []
    for key, items in by_layout.items():
        fastest = min(items, key=lambda i: i.best_clean_s)
        # Recorded_at sorts correctly as text: it is ISO 8601 with a Z suffix.
        by_date = sorted(items, key=lambda i: i.recorded_at or "", reverse=True)
        chosen = [fastest]
        laps = fastest.clean_laps
        for item in by_date:
            if item is fastest:
                continue
            if laps >= TARGET_CLEAN_LAPS:
                archive.append(item)
                continue
            chosen.append(item)
            laps += item.clean_laps
        keep.extend(chosen)
    return keep, archive


def _move(item: Scanned, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / item.path.name
    if target.resolve() == item.path.resolve():
        return
    shutil.move(str(item.path), str(target))
    wal = item.path.with_suffix(item.path.suffix + ".wal")
    if wal.is_file():
        shutil.move(str(wal), str(destination / wal.name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=None,
                        help="directory of .duckdb sessions to sort")
    parser.add_argument("--apply", action="store_true",
                        help="move the files; without it nothing is touched")
    args = parser.parse_args()

    source = args.source or (REPO_ROOT / "LMU Data-20260803T093100Z-1-001" / "LMU Data")
    files = sorted(Path(source).glob("*.duckdb"))
    if not files:
        raise SystemExit(f"no .duckdb sessions under {source}")

    print(f"scanning {len(files)} sessions from {source} ...")
    scanned = [scan(path) for path in files]
    keep, archive = choose(scanned)

    print(f"\n{'layout':<62}{'keep':>5}{'laps':>6}{'best':>10}")
    by_layout: dict[TrackKey, list[Scanned]] = defaultdict(list)
    for item in keep:
        by_layout[item.key].append(item)
    for key in sorted(by_layout, key=lambda k: (k.track, k.layout)):
        items = by_layout[key]
        laps = sum(i.clean_laps for i in items)
        best = min(i.best_clean_s for i in items)
        label = f"{key.track} / {key.layout}"
        best_text = f"{int(best // 60)}:{best % 60:06.3f}"
        print(f"{label[:61]:<62}{len(items):>5}{laps:>6}{best_text:>10}")
    print(f"\nworking set: {len(keep)} sessions   archive: {len(archive)} sessions")

    dropped = defaultdict(int)
    for item in archive:
        for kind, count in item.reasons.items():
            dropped[kind] += count
    print("\nlaps left behind, by reason:")
    for kind, count in sorted(dropped.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  {kind}")

    if not args.apply:
        print("\nnothing moved. Re-run with --apply to carry this out.")
        return

    for item in keep:
        _move(item, WORKING)
    for item in archive:
        _move(item, ARCHIVE)

    DATA.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "target_clean_laps": TARGET_CLEAN_LAPS,
                "working_set": [_entry(i, "sessions") for i in keep],
                "archive": [_entry(i, "archive") for i in archive],
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nmoved {len(keep)} to {WORKING}, {len(archive)} to {ARCHIVE}")
    print(f"manifest: {MANIFEST}")


def _entry(item: Scanned, folder: str) -> dict:
    return {
        "file": f"{folder}/{item.path.name}",
        "track": None if item.key is None else item.key.track,
        "layout": None if item.key is None else item.key.layout,
        "recorded_at": item.recorded_at,
        "clean_laps": item.clean_laps,
        "total_laps": item.total_laps,
        "best_clean_s": None if item.best_clean_s is None else round(item.best_clean_s, 3),
        "rejected": item.reasons,
        "error": item.error,
    }


if __name__ == "__main__":
    main()
