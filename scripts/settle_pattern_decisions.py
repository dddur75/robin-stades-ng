"""Régler séparément les décisions shadow à partir de résultats déjà en cache."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from robin.patterns.ledger import EvidenceLedger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ledger = EvidenceLedger(args.ledger)
    raw_records: list[dict[str, Any]] = [
        json.loads(line)
        for line in args.ledger.read_text("utf-8").splitlines()
        if line.strip()
    ]
    decisions = {
        str(record["decision_id"]): record
        for record in raw_records
        if record.get("record_type") == "DECISION"
    }
    results: list[dict[str, Any]] = json.loads(args.results.read_text("utf-8"))
    settled = 0
    skipped = 0
    for result in results:
        decision_id = str(result["decision_id"])
        decision = decisions.get(decision_id)
        if decision is None or decision.get("decision") != "BET":
            skipped += 1
            continue
        outcome = str(result["result"])
        stake = float(decision["stake_units"])
        profit = {
            "WIN": float(decision["odds"]) - stake,
            "LOSS": -stake,
            "VOID": 0.0,
        }[outcome]
        ledger.append_settlement(
            settlement_id=f"PTRN-SET-{decision_id}",
            decision_id=decision_id,
            settled_at=datetime.fromisoformat(
                str(result["settled_at"]).replace("Z", "+00:00")
            ),
            result=outcome,
            profit_units=profit,
        )
        settled += 1
    report = {
        "status": "SETTLEMENT_REPLAY_VERIFIED",
        "results_examined": len(results),
        "settled_or_replayed": settled,
        "skipped": skipped,
        "provider_calls": 0,
        "real_bets": False,
        "ledger": ledger.audit(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
