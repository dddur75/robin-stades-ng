"""Exécuter et rejouer la campagne Jalon 10 sans fournisseur."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from robin.patterns.campaign import run_campaign
from robin.patterns.ledger import EvidenceLedger
from robin.patterns.social import build_disabled_exports


def _native(value: Any) -> object:
    if pd.isna(value):
        return None
    item = getattr(value, "item", None)
    return item() if callable(item) else value


def load_market_rows(root: Path) -> list[dict[str, object]]:
    paths = sorted(
        (root / "parquet").glob(
            "competition=*/season=*/entity_type=historical_market/"
            "dataset_version=historical_market_v1/*.parquet"
        )
    )
    if not paths:
        raise SystemExit("HISTORICAL_MARKET_CACHE_UNAVAILABLE")
    rows: list[dict[str, object]] = []
    for path in paths:
        for row in pd.read_parquet(path).to_dict(orient="records"):
            rows.append({str(key): _native(value) for key, value in row.items()})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    rows = load_market_rows(args.state)
    result = run_campaign(rows, code_revision=args.code_revision)
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "campaign-summary.json"
    previous = (
        json.loads(summary_path.read_text("utf-8"))
        if args.replay and summary_path.exists()
        else None
    )
    summary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hypotheses = result["hypotheses"]
    registry = output / "hypothesis-registry.jsonl"
    registry.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in hypotheses
        ),
        encoding="utf-8",
    )
    ledger = EvidenceLedger(output / "public-ledger.jsonl")
    ledger_summary = ledger.audit()
    (output / "ledger-summary.json").write_text(
        json.dumps(ledger_summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    build_disabled_exports(output / "social_exports", ledger_url="/robin-live")
    replay_status = {
        "mode": "REPLAY" if args.replay else "PRIMARY",
        "provider_calls": 0,
        "odds_api_credits": 0,
        "business_duplicates": 0,
        "previous_result_hash": previous.get("result_hash") if previous else None,
        "result_hash": result["result_hash"],
        "identical": previous is None
        or previous.get("result_hash") == result["result_hash"],
    }
    (output / "replay.json").write_text(
        json.dumps(replay_status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.replay and not replay_status["identical"]:
        raise SystemExit("NON_DETERMINISTIC_REPLAY")
    print(json.dumps({"counts": result["counts"], "replay": replay_status}))


if __name__ == "__main__":
    main()
