"""Run the API.

    python -m lmu_telemetry.api --recordings data/sessions
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recordings",
        type=Path,
        default=Path("data") / "sessions",
        help="directory of .duckdb recordings to serve",
    )
    parser.add_argument("--cache", type=Path, default=Path(".cache") / "traces")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not args.recordings.is_dir():
        raise SystemExit(
            f"no recordings directory at {args.recordings}. Point --recordings at "
            f"one, or run tools/curate_corpus.py to sort your sessions into it."
        )
    uvicorn.run(
        create_app(args.recordings, cache_dir=args.cache),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
