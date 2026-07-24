"""Point d'entrée idempotent des workflows shadow du Jalon 2."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from robin.domain.enums import DataOrigin, QualityStatus, QuotePhase
from robin.domain.odds import stable_internal_id
from robin.ingestion.raw_store import LocalRawStore
from robin.ingestion.scheduler import CollectionWindow, FixtureCandidate, plan_collection
from robin.ingestion.snapshot_store import JsonlSnapshotStore
from robin.modeling.reference import (
    EloModel,
    consensus,
    estimate_expected_goals,
    poisson_probabilities,
)
from robin.providers.mock import MockFootballProvider
from robin.providers.the_odds_api import TheOddsApiProvider, parse_odds_snapshot
from robin.shadow.decision import DecisionJournal, decide_shadow_bet


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def mock_provider() -> MockFootballProvider:
    return MockFootballProvider(
        {
            "competitions": ({"id": "ligue-1", "name": "Ligue 1"},),
            "fixtures": (
                {
                    "id": "demo-fixture-1",
                    "sport_key": "soccer_france_ligue_one",
                    "sport_title": "Ligue 1",
                    "commence_time": "2026-08-16T18:45:00Z",
                    "home_team": "Paris SG",
                    "away_team": "Marseille",
                    "origin": DataOrigin.DEMO_DATA.value,
                },
            ),
            "results": (),
        }
    )


def provider(output: Path, run_id: str, mock: bool) -> Any:
    if mock:
        return mock_provider()
    return TheOddsApiProvider(
        api_key=os.getenv("ODDS_API_KEY"),
        raw_store=LocalRawStore(output / "raw"),
        ingestion_run_id=run_id,
    )


def collect_fixtures(output: Path, *, mock: bool) -> dict[str, object]:
    run_id = f"fixtures-{datetime.now(UTC).strftime('%Y%m%d%H')}"
    result = provider(output, run_id, mock).get_fixtures()
    fixtures = []
    for record in result.records:
        item = dict(record)
        item["origin"] = result.origin.value
        item["collected_at"] = result.observed_at.isoformat()
        fixtures.append(item)
    write_json(output / "fixtures" / "latest.json", fixtures)
    summary = {
        "run_id": run_id,
        "pipeline": "collect-fixtures",
        "status": (
            "READY_NO_KEY"
            if not mock and result.message == "credential_absent"
            else result.availability.value
        ),
        "origin": result.origin.value,
        "records": len(fixtures),
        "quota_remaining": result.quota.remaining,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{run_id}.json", summary)
    return summary


def read_ledger(path: Path) -> set[tuple[str, CollectionWindow]]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text("utf-8"))
    return {
        (str(item["fixture_id"]), CollectionWindow(str(item["window"])))
        for item in payload
    }


def write_ledger(path: Path, values: set[tuple[str, CollectionWindow]]) -> None:
    write_json(
        path,
        [
            {"fixture_id": fixture_id, "window": window.value}
            for fixture_id, window in sorted(
                values,
                key=lambda item: (item[0], item[1].value),
            )
        ],
    )


def collect_odds(
    output: Path,
    *,
    mock: bool,
    diagnostic: bool = False,
) -> dict[str, object]:
    run_id = f"odds-{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    if mock:
        fixtures_summary = collect_fixtures(output, mock=True)
        return {
            **fixtures_summary,
            "pipeline": "collect-odds",
            "status": "ABSENT",
            "message": "mode mock : aucune cote présentée comme réelle",
            "snapshots": 0,
        }
    odds_provider = provider(output, run_id, False)
    fixture_result = odds_provider.get_fixtures()
    now = datetime.now(UTC)
    candidates = tuple(
        FixtureCandidate(
            provider_fixture_id=str(record["id"]),
            kickoff_at=datetime.fromisoformat(
                str(record["commence_time"]).replace("Z", "+00:00")
            ),
        )
        for record in fixture_result.records
    )
    ledger_path = output / "odds" / "collection-ledger.json"
    collected = read_ledger(ledger_path)
    remaining = fixture_result.quota.remaining or 500
    tasks = list(
        plan_collection(
            candidates,
            now=now,
            collected=collected,
            quota_remaining=remaining,
        )
    )
    if diagnostic and not tasks and candidates and remaining >= 2:
        nearest = min(
            candidates,
            key=lambda item: abs((item.kickoff_at - now).total_seconds()),
        )
        tasks = [
            {
                "provider_fixture_id": nearest.provider_fixture_id,
                "window": CollectionWindow.D7,
            }
        ]
    store = JsonlSnapshotStore(output / "odds")
    appended = quotes = 0
    last_quota = fixture_result.quota
    for task in tasks:
        fixture_id = (
            task.provider_fixture_id
            if not isinstance(task, dict)
            else str(task["provider_fixture_id"])
        )
        window = (
            task.window
            if not isinstance(task, dict)
            else CollectionWindow(str(task["window"]))
        )
        result = odds_provider.get_event_odds(fixture_id)
        last_quota = result.quota
        if not result.records or result.raw_observation_id is None:
            continue
        snapshot = parse_odds_snapshot(
            result.records[0],
            observed_at=result.observed_at,
            ingested_at=datetime.now(UTC),
            raw_observation_id=result.raw_observation_id,
            phase=(
                QuotePhase.CLOSING
                if window in {CollectionWindow.M30, CollectionWindow.M10}
                else QuotePhase.INTERMEDIATE
            ),
        )
        quotes += len(snapshot.quotes)
        appended += int(store.append(snapshot))
        collected.add((fixture_id, window))
    write_ledger(ledger_path, collected)
    summary = {
        "run_id": run_id,
        "pipeline": "collect-odds",
        "status": "PASSED" if os.getenv("ODDS_API_KEY") else "READY_NO_KEY",
        "origin": DataOrigin.LIVE_SOURCE.value,
        "fixtures_visible": len(candidates),
        "tasks_due": len(tasks),
        "snapshots_appended": appended,
        "quotes_received": quotes,
        "quota_used": last_quota.used,
        "quota_remaining": last_quota.remaining,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{run_id}.json", summary)
    return summary


def pre_match_shadow(output: Path, *, mock: bool) -> dict[str, object]:
    fixtures_path = output / "fixtures" / "latest.json"
    if not fixtures_path.exists():
        collect_fixtures(output, mock=mock)
    fixtures = json.loads(fixtures_path.read_text("utf-8"))
    history = pd.read_parquet("data/matches.parquet")
    predictions: list[dict[str, object]] = []
    journal = DecisionJournal(output / "decisions" / "shadow-decisions.jsonl")
    odds_records = JsonlSnapshotStore(output / "odds").read_all()
    for fixture in fixtures:
        kickoff = datetime.fromisoformat(
            str(fixture["commence_time"]).replace("Z", "+00:00")
        )
        if kickoff <= datetime.now(UTC):
            continue
        home = str(fixture["home_team"])
        away = str(fixture["away_team"])
        expected_home, expected_away = estimate_expected_goals(
            history,
            home_team=home,
            away_team=away,
            as_of_time=kickoff,
        )
        poisson = poisson_probabilities(expected_home, expected_away)
        elo = EloModel().predict(home, away)
        combined = consensus(elo, poisson)
        fixture_id = stable_internal_id("fixture", "the-odds-api", str(fixture["id"]))
        prediction = {
            "prediction_id": str(uuid4()),
            "fixture_id": fixture_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of_time": datetime.now(UTC).isoformat(),
            "model_name": "consensus-elo-poisson",
            "model_version": "1.0",
            "dataset_version": "matches-parquet-j2",
            "feature_version": "shadow-v1",
            "probability_home": combined.home,
            "probability_draw": combined.draw,
            "probability_away": combined.away,
            "expected_home_goals": combined.expected_home_goals,
            "expected_away_goals": combined.expected_away_goals,
            "data_quality_status": QualityStatus.DERIVED.value,
            "uncertainty_status": "HIGH" if mock else "NORMAL",
            "market_snapshot_id": None,
            "origin": fixture.get("origin", DataOrigin.DEMO_DATA.value),
        }
        predictions.append(prediction)
        fixture_quotes = [
            record for record in odds_records if record.get("fixture_id") == fixture_id
        ]
        home_odds: float | None = None
        if fixture_quotes:
            quote_rows = fixture_quotes[-1].get("quotes", [])
            for quote in quote_rows if isinstance(quote_rows, list) else []:
                market = quote.get("market", {})
                if (
                    isinstance(market, dict)
                    and market.get("market_type") == "1X2"
                    and market.get("selection") == "HOME"
                ):
                    home_odds = float(quote["odds_decimal"])
                    break
        journal.append(
            decide_shadow_bet(
                fixture_id=fixture_id,
                market_key="1X2",
                selection="HOME",
                odds_decimal=home_odds,
                model_probability=combined.home,
                strategy_version="value-simple-1.0",
                quality_ok=not mock,
                model_disagreement=abs(elo.home - poisson.home) > 0.15,
            )
        )
    write_json(output / "predictions" / "latest.json", predictions)
    summary = {
        "run_id": f"pre-match-{datetime.now(UTC).strftime('%Y%m%d%H')}",
        "pipeline": "pre-match-shadow",
        "status": "PASSED",
        "predictions": len(predictions),
        "decisions_total": len(journal.read_all()),
        "origin": DataOrigin.DEMO_DATA.value if mock else DataOrigin.LIVE_SOURCE.value,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{summary['run_id']}.json", summary)
    return summary


def post_match_settlement(output: Path, *, mock: bool) -> dict[str, object]:
    run_id = f"settlement-{datetime.now(UTC).strftime('%Y%m%d%H')}"
    results = provider(output, run_id, mock).get_results()
    summary = {
        "run_id": run_id,
        "pipeline": "post-match-settlement",
        "status": results.availability.value,
        "results_received": len(results.records),
        "settled": 0,
        "message": "aucun pari réel ; règlements shadow uniquement",
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{run_id}.json", summary)
    return summary


def daily_health(output: Path) -> dict[str, object]:
    run_dir = output / "runs"
    runs = [
        json.loads(path.read_text("utf-8"))
        for path in sorted(run_dir.glob("*.json"))
    ] if run_dir.exists() else []
    snapshots = JsonlSnapshotStore(output / "odds").read_all()
    decisions = DecisionJournal(output / "decisions" / "shadow-decisions.jsonl").read_all()
    rejected: dict[str, int] = {}
    for decision in decisions:
        reason = str(decision.get("primary_reason") or "ACCEPTED")
        rejected[reason] = rejected.get(reason, 0) + 1
    health = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "WARNING" if not snapshots else "PASSED",
        "pipeline_runs": len(runs),
        "successful_runs": sum(
            run.get("status") in {"PASSED", "PRESENT", "ABSENT"} for run in runs
        ),
        "snapshots_received": len(snapshots),
        "decisions": len(decisions),
        "rejections_by_reason": rejected,
        "critical_alerts": 0,
        "estimated_cost_eur": 0,
        "production_locked": True,
    }
    write_json(output / "health" / "latest.json", health)
    return health


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "collect-fixtures",
            "collect-odds",
            "pre-match-shadow",
            "post-match-settlement",
            "daily-health",
        ],
    )
    parser.add_argument("--output", type=Path, default=Path("data/shadow"))
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    if args.command == "collect-fixtures":
        result = collect_fixtures(args.output, mock=args.mock)
    elif args.command == "collect-odds":
        result = collect_odds(args.output, mock=args.mock, diagnostic=args.diagnostic)
    elif args.command == "pre-match-shadow":
        result = pre_match_shadow(args.output, mock=args.mock)
    elif args.command == "post-match-settlement":
        result = post_match_settlement(args.output, mock=args.mock)
    else:
        result = daily_health(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
