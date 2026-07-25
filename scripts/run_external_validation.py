"""Execute Jalon 8 exclusively from the durable historical cache."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from robin.historical.external_validation import run_external_validation

ROOT = Path(__file__).resolve().parents[1]


def git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        type=Path,
        default=ROOT / "data" / "historical",
    )
    parser.add_argument("--run-id", default="local-jalon8")
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--frozen-at", default=None)
    args = parser.parse_args()
    result = run_external_validation(
        args.state,
        source_commit=args.source_commit or git_revision(),
        run_id=args.run_id,
        frozen_at=args.frozen_at,
    )
    summary = {
        "status": result["status"],
        "run_id": result["run_id"],
        "predictions": result["predictions"],
        "provider_calls": result["provider_calls"],
        "quota_consumed": result["quota_consumed"],
        "production_status": result["production_status"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
