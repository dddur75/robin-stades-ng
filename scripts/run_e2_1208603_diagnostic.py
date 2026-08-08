"""Run the allow-listed E2 fixture diagnostic and write sanitized reports only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from robin.historical.object_storage_migration import create_r2_client
from robin.historical_deep.e2_targeted_diagnostic import diagnose_payload, fetch_exact_pair

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/execution/e2-1208603-targeted-diagnostic-v1.json"


def _safety() -> None:
    forbidden_secrets = ("API_FOOTBALL_KEY", "DATABASE_URL", "ODDS_API_KEY")
    if any(os.environ.get(name) for name in forbidden_secrets):
        raise RuntimeError("E2_DIAGNOSTIC_FORBIDDEN_SECRET_MOUNTED")
    expected = {
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "ODDS_CREDITS_ALLOWED": "0",
        "REMOTE_SQL_ALLOWED": "0",
        "R2_LIST_ALLOWED": "0",
        "R2_HEAD_ALLOWED": "0",
        "R2_WRITES_ALLOWED": "0",
        "R2_DELETES_ALLOWED": "0",
        "DEPLOYMENT_ALLOWED": "0",
        "PUBLICATION_ALLOWED": "0",
        "REAL_BETS": "false",
        "PROMOTION_LOCKED": "true",
    }
    for name, value in expected.items():
        if os.environ.get(name) not in (None, "", value):
            raise RuntimeError(f"E2_DIAGNOSTIC_LOCK_INVALID:{name}")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _safety()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    client, bucket = create_r2_client(os.environ)
    receipt, payload, telemetry = fetch_exact_pair(
        client, bucket=bucket, contract=contract
    )
    source_hashes = {
        "object_id": contract["object_id"],
        "receipt_hash": contract["receipt_hash"],
        "payload_hash": contract["payload_hash"],
        "stored_hash": contract["stored_hash"],
        "receipt_task_id": receipt["task_id"],
        "r2_gets": telemetry["r2_gets"],
        "network_bytes": telemetry["network_bytes"],
        "logical_bytes": telemetry["logical_bytes"],
    }
    diagnostic, census = diagnose_payload(
        payload, fixture_id=int(contract["fixture_id"]), source_hashes=source_hashes
    )
    output = args.output.resolve()
    _write(output / "e2-player-statistics-1208603-diagnostic-v1.json", diagnostic)
    _write(output / "e2-1208603-field-path-census-v1.json", census)
    print("E2_1208603_DIAGNOSTIC_COMPLETE")


if __name__ == "__main__":
    main()
