"""Décisions shadow fail-closed depuis des données point-in-time déjà en cache."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from robin.patterns.contracts import PatternCondition
from robin.patterns.engine import condition_matches
from robin.patterns.ledger import EvidenceLedger
from robin.patterns.temporal import validate_observation_cutoff


def _time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC_TIMESTAMP_REQUIRED")
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--published-at")
    args = parser.parse_args()

    campaign: dict[str, Any] = json.loads(args.campaign.read_text("utf-8"))
    fixtures: list[dict[str, Any]] = json.loads(args.fixtures.read_text("utf-8"))
    candidates = [
        item
        for item in campaign.get("hypotheses", [])
        if item.get("status") == "LIVE_SHADOW_CANDIDATE"
    ]
    published_at = (
        _time(args.published_at)
        if args.published_at
        else datetime.now(UTC)
    )
    ledger = EvidenceLedger(args.ledger)
    written = 0
    unavailable = 0
    no_bet = 0
    bets = 0
    for fixture in fixtures:
        kickoff_at = _time(fixture["kickoff_at"])
        cutoff_at = kickoff_at - timedelta(minutes=60)
        if published_at > cutoff_at:
            unavailable += 1
            continue
        try:
            validate_observation_cutoff(fixture, cutoff_at=cutoff_at)
        except ValueError:
            unavailable += 1
            continue
        matching = []
        for candidate in candidates:
            conditions = [
                PatternCondition.model_validate(condition)
                for condition in candidate.get("conditions", [])
            ]
            if all(condition_matches(fixture, condition) for condition in conditions):
                matching.append(candidate)
        selected = matching[0] if len(matching) == 1 else None
        if selected is None:
            decision = "NO_BET"
            no_bet += 1
            odds = None
            pattern_id = None
            pattern_version = None
            selection = "NONE"
        else:
            market = str(selected["market"])
            odds_key = {
                "1X2_HOME": "odds_home",
                "1X2_DRAW": "odds_draw",
                "1X2_AWAY": "odds_away",
                "TOTAL_OVER_2_5": "odds_over_25",
                "TOTAL_UNDER_2_5": "odds_under_25",
            }[market]
            odds = float(fixture[odds_key])
            decision = "BET"
            bets += 1
            pattern_id = f"PTRN-{str(selected['rule_hash'])[:16].upper()}"
            pattern_version = "1.0.0"
            selection = str(selected["selection"])
        ledger.append_decision(
            decision_id=f"PTRN-DEC-{fixture['fixture_id']}-{cutoff_at:%Y%m%d%H%M}",
            published_at=published_at,
            cutoff_at=cutoff_at,
            fixture_id=int(fixture["fixture_id"]),
            competition=str(fixture["competition"]),
            kickoff_at=kickoff_at,
            market=(
                str(selected["market"]) if selected is not None else "NO_MARKET"
            ),
            selection=selection,
            odds=odds,
            odds_source=(
                str(fixture.get("odds_source", "POINT_IN_TIME_CACHE"))
                if selected is not None
                else "NO_CANDIDATE"
            ),
            pattern_id=pattern_id,
            pattern_version=pattern_version,
            decision=decision,
            code_revision=args.code_revision,
            dataset_hash=str(fixture["dataset_hash"]),
        )
        written += 1
    status = (
        "NO_BET_DATA_UNAVAILABLE"
        if fixtures and written == 0 and unavailable == len(fixtures)
        else "SHADOW_DECISIONS_RECORDED"
    )
    report = {
        "status": status,
        "fixtures_examined": len(fixtures),
        "records_appended_or_replayed": written,
        "bets": bets,
        "no_bet": no_bet,
        "data_unavailable": unavailable,
        "provider_calls": 0,
        "real_bets": False,
        "production_status": "PRODUCTION_LOCKED",
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
