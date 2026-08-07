"""Regenerate tests/golden/expected_track_models.json from the local corpus.

Run after a deliberate change to the geometry pipeline, never to make a
failing golden test pass. The file it writes is the record of what the
pipeline produced at a known-good moment; overwriting it discards that record,
so the diff belongs in the same commit as the change that caused it.

    python tools/freeze_golden_models.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from lmu_telemetry.core.session import Session
from lmu_telemetry.core.track_model import TrackKey, build_track_model

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "data" / "sessions"
OUT = REPO_ROOT / "tests" / "golden" / "expected_track_models.json"

#: Layouts with fewer clean laps than this are left out: their median line
#: still moves noticeably as laps are added, so freezing them would record
#: sampling noise as if it were the track.
MIN_LAPS_TO_FREEZE = 10


def main() -> None:
    if not CORPUS.is_dir():
        raise SystemExit(f"corpus not found at {CORPUS}")

    grouped: dict[TrackKey, list[Session]] = defaultdict(list)
    sessions = []
    try:
        for path in sorted(CORPUS.glob("*.duckdb")):
            session = Session.open(path)
            sessions.append(session)
            key = TrackKey.of(session)
            if key is not None:
                grouped[key].append(session)

        out: dict[str, dict] = {}
        for key in sorted(grouped, key=lambda k: (k.track, k.layout)):
            model = build_track_model(grouped[key])
            if model is None or model.lap_count < MIN_LAPS_TO_FREEZE:
                continue
            out[key.slug()] = {
                "track": key.track,
                "layout": key.layout,
                "track_length_m": round(model.track_length_m, 1),
                "closure_deg": round(model.closure_deg, 1),
                "lap_count": model.lap_count,
                "corner_count": len(model.corners),
                "apex_m": [round(c.apex_m) for c in model.corners],
                "names": [c.name for c in model.corners],
            }
    finally:
        for session in sessions:
            session.close()

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"froze {len(out)} models to {OUT.relative_to(REPO_ROOT)}")
    for slug, entry in out.items():
        print(f"  {slug:<52} {entry['corner_count']:>3} corners  "
              f"{entry['lap_count']:>4} laps")


if __name__ == "__main__":
    main()
