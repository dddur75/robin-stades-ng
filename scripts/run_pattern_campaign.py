"""Exécuter et rejouer la campagne Jalon 10 sans fournisseur."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pandas as pd

from robin.patterns.campaign import CampaignConfig, run_campaign
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


def load_campaign_config(path: Path) -> CampaignConfig:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PATTERN_CONFIG_MUST_BE_OBJECT")
    expected = {field.name for field in fields(CampaignConfig)}
    actual = set(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        unexpected = ",".join(sorted(actual - expected))
        raise ValueError(
            f"PATTERN_CONFIG_KEYS_INVALID:missing={missing}:unexpected={unexpected}"
        )
    normalized = dict(payload)
    competitions = normalized.get("exposed_stability_competitions")
    if not isinstance(competitions, list) or not all(
        isinstance(item, str) for item in competitions
    ):
        raise ValueError("PATTERN_CONFIG_COMPETITIONS_INVALID")
    normalized["exposed_stability_competitions"] = tuple(competitions)
    return CampaignConfig(**normalized)


def compact_candidate_registry(result: dict[str, Any]) -> dict[str, object]:
    candidates = [
        item
        for item in result["hypotheses"]
        if item.get("status") == "LIVE_SHADOW_CANDIDATE"
    ]
    return {
        "schema_version": "pattern-shadow-candidates-v1",
        "source_result_hash": result["result_hash"],
        "dataset_hashes": result["dataset_hashes"],
        "code_revision": result["code_revision"],
        "data_classification": result["data_classification"],
        "verdict": result["verdict"],
        "config": result["config"],
        "provider_calls": result["provider_calls"],
        "odds_api_credits": result["odds_api_credits"],
        "production_status": result["production_status"],
        "real_bets": result["real_bets"],
        "no_bet_default": result["no_bet_default"],
        "social_publishing_enabled": result["social_publishing_enabled"],
        "demo_mode_enabled": result["demo_mode_enabled"],
        "candidate_count": len(candidates),
        "hypotheses": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/pattern-research-v1.json"),
    )
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    rows = load_market_rows(args.state)
    config = load_campaign_config(args.config)
    result = run_campaign(
        rows,
        code_revision=args.code_revision,
        config=config,
    )
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "campaign-summary.json"
    previous = (
        json.loads(summary_path.read_text("utf-8"))
        if args.replay and summary_path.exists()
        else None
    )
    replay_status = {
        "mode": "REPLAY" if args.replay else "PRIMARY",
        "provider_calls": 0,
        "odds_api_credits": 0,
        "business_duplicates": 0,
        "previous_result_hash": previous.get("result_hash") if previous else None,
        "result_hash": result["result_hash"],
        "identical": (
            previous is not None
            and previous.get("result_hash") == result["result_hash"]
            if args.replay
            else True
        ),
    }
    if args.replay and previous is None:
        raise SystemExit("REPLAY_PRIMARY_EVIDENCE_MISSING")
    if args.replay and not replay_status["identical"]:
        (output / "replay-mismatch.json").write_text(
            json.dumps(replay_status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise SystemExit("NON_DETERMINISTIC_REPLAY_PRIMARY_PRESERVED")
    if not args.replay:
        summary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        hypotheses = result["hypotheses"]
        if not isinstance(hypotheses, list):
            raise ValueError("PATTERN_HYPOTHESES_MUST_BE_LIST")
        registry = output / "hypothesis-registry.jsonl"
        registry.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in hypotheses
            ),
            encoding="utf-8",
        )
        candidate_registry = compact_candidate_registry(result)
        (output / "shadow-candidate-registry.json").write_text(
            json.dumps(
                candidate_registry,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        ledger = EvidenceLedger(output / "public-ledger.jsonl")
        ledger_summary = ledger.audit()
        (output / "ledger-summary.json").write_text(
            json.dumps(
                ledger_summary,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        build_disabled_exports(
            output / "social_exports",
            ledger_url="/robin-live",
        )
    (output / "replay.json").write_text(
        json.dumps(replay_status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"counts": result["counts"], "replay": replay_status}))


if __name__ == "__main__":
    main()
