"""Persister les preuves compactes Jalon 11 dans PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from robin.deep_football.persistence import (
    PROTOCOL_AMENDMENT_PUBLISHED_AT,
    PROTOCOL_AMENDMENT_SOURCE_COMMIT,
    persist_deep_football_evidence,
)
from robin.storage.database import build_engine

DEFAULT_PROTOCOL_AMENDMENT = Path("configs/deep-football-v1-amendment-1.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--protocol-amendment",
        type=Path,
        default=DEFAULT_PROTOCOL_AMENDMENT,
    )
    parser.add_argument(
        "--protocol-amendment-source-commit",
        default=PROTOCOL_AMENDMENT_SOURCE_COMMIT,
    )
    parser.add_argument(
        "--protocol-amendment-published-at",
        default=PROTOCOL_AMENDMENT_PUBLISHED_AT.isoformat(),
    )
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL") or os.environ.get("ROBIN_DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL_ABSENT_NO_SECRET_VALUE_LOGGED")
    protocol_amendment = json.loads(args.protocol_amendment.read_text(encoding="utf-8"))
    if not isinstance(protocol_amendment, dict):
        raise SystemExit("JALON11_PROTOCOL_AMENDMENT_OBJECT_REQUIRED")
    try:
        protocol_amendment_published_at = datetime.fromisoformat(
            args.protocol_amendment_published_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise SystemExit("JALON11_PROTOCOL_AMENDMENT_PUBLISHED_AT_INVALID") from exc
    report = persist_deep_football_evidence(
        build_engine(database_url),
        args.artifacts,
        code_revision=args.code_revision,
        protocol_amendment=protocol_amendment,
        protocol_amendment_source_commit=(args.protocol_amendment_source_commit),
        protocol_amendment_published_at=protocol_amendment_published_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
