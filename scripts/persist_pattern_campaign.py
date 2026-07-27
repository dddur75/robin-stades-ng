"""Persister les registres compacts Jalon 10 dans PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from robin.patterns.persistence import persist_campaign
from robin.storage.database import build_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL") or os.environ.get(
        "ROBIN_DATABASE_URL"
    )
    if not database_url:
        raise SystemExit("DATABASE_URL_ABSENT_NO_SECRET_VALUE_LOGGED")
    payload = json.loads(args.campaign.read_text("utf-8"))
    report = persist_campaign(build_engine(database_url), payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
