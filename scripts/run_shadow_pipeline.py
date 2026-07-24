"""Point d'entrée idempotent des workflows shadow live."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from robin.domain.enums import DataOrigin, QualityStatus, QuotePhase
from robin.domain.odds import stable_internal_id
from robin.ingestion.raw_store import LocalRawStore
from robin.ingestion.scheduler import (
    BudgetLevel,
    CollectionTask,
    CollectionWindow,
    FixtureCandidate,
    SchedulerWindowState,
    WindowStatus,
    adaptive_plan,
    quota_budget,
    record_window_result,
    window_states,
)
from robin.ingestion.snapshot_store import JsonlSnapshotStore
from robin.modeling.reference import (
    EloModel,
    consensus,
    estimate_expected_goals,
    poisson_probabilities,
)
from robin.operations.activation import (
    WORKFLOW_SUCCESS_LIVE_DATA,
    WORKFLOW_SUCCESS_NO_DATA,
    normalized_market_probabilities,
    workflow_outcome,
)
from robin.operations.burn_in import (
    AlertSeverity,
    IncidentJournal,
    compute_daily_metrics,
    render_daily_report,
    render_weekly_report,
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


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text("utf-8"))


def append_jsonl_once(path: Path, record: dict[str, object], *, key: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    known = {
        str(item.get(key))
        for item in read_jsonl(path)
        if item.get(key) is not None
    }
    if str(record[key]) in known:
        return False
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
        stream.write("\n")
    return True


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        value
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def runtime_run_id(pipeline: str) -> str:
    github_run_id = (os.getenv("GITHUB_RUN_ID") or "").strip()
    suffix = github_run_id or datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"{pipeline}-{suffix}"


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
    run_id = runtime_run_id("fixtures")
    result = provider(output, run_id, mock).get_fixtures()
    fixtures = []
    for record in result.records:
        item = dict(record)
        item["origin"] = result.origin.value
        item["collected_at"] = result.observed_at.isoformat()
        fixtures.append(item)
    write_json(output / "fixtures" / "latest.json", fixtures)
    authenticated = mock or result.message != "credential_absent"
    summary: dict[str, object] = {
        "run_id": run_id,
        "pipeline": "collect-fixtures",
        "status": (
            result.availability.value
            if mock
            else workflow_outcome(
                authenticated=authenticated,
                records_received=len(fixtures),
                records_persisted=len(fixtures),
            )
        ),
        "origin": (
            result.origin.value
            if mock or (authenticated and fixtures)
            else "NO_OUTPUT"
        ),
        "provider": result.provider,
        "endpoint": result.endpoint,
        "authenticated": authenticated and not mock,
        "records": len(fixtures),
        "calls_consumed": result.quota.last_cost or 0,
        "quota_used": result.quota.used,
        "quota_remaining": result.quota.remaining,
        "raw_observation_id": result.raw_observation_id,
        "raw_payload_hash": result.raw_payload_hash,
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


def read_scheduler_states(path: Path) -> dict[tuple[str, CollectionWindow], SchedulerWindowState]:
    latest: dict[tuple[str, CollectionWindow], SchedulerWindowState] = {}
    for value in read_jsonl(path):
        state = SchedulerWindowState.model_validate(value)
        latest[(state.fixture_id, state.window)] = state
    return latest


def persist_scheduler_states(
    output: Path,
    states: dict[tuple[str, CollectionWindow], SchedulerWindowState],
) -> None:
    write_json(
        output / "scheduler" / "latest.json",
        [
            state.model_dump(mode="json")
            for _, state in sorted(
                states.items(),
                key=lambda item: (item[0][0], item[0][1].value),
            )
        ],
    )


def append_scheduler_event(
    output: Path,
    state: SchedulerWindowState,
    run_id: str,
) -> None:
    value = state.model_dump(mode="json")
    value["run_id"] = run_id
    value["event_id"] = stable_internal_id(
        "scheduler-event",
        "internal",
        f"{run_id}:{state.fixture_id}:{state.window.value}:{state.attempt_count}:{state.status.value}",
    )
    append_jsonl_once(
        output / "scheduler" / "windows.jsonl",
        value,
        key="event_id",
    )


def collect_odds(
    output: Path,
    *,
    mock: bool,
    diagnostic: bool = False,
) -> dict[str, object]:
    run_id = runtime_run_id("odds")
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
    remaining = fixture_result.quota.remaining or 0
    scheduler_path = output / "scheduler" / "windows.jsonl"
    known_states = read_scheduler_states(scheduler_path)
    all_states = {
        (state.fixture_id, state.window): state
        for state in window_states(
            candidates,
            now=now,
            known=known_states,
        )
    }
    budget = quota_budget(
        credits_used_today=0,
        credits_used_month=fixture_result.quota.used or 0,
        provider_remaining=remaining,
        operational_ceiling=1_000,
        reserve_credits=4_000,
        forecast_month_end=max(fixture_result.quota.used or 0, 720),
    )
    tasks = list(
        adaptive_plan(
            tuple(all_states.values()),
            fixtures={item.provider_fixture_id: item for item in candidates},
            budget=budget,
        )
    )
    diagnostic_outside_window = False
    if diagnostic and not tasks and candidates and remaining >= 2:
        nearest = min(
            candidates,
            key=lambda item: abs((item.kickoff_at - now).total_seconds()),
        )
        tasks = [
            CollectionTask(
                provider_fixture_id=nearest.provider_fixture_id,
                window=CollectionWindow.D7,
                kickoff_at=nearest.kickoff_at,
                priority=0,
                estimated_credits=2,
            )
        ]
        diagnostic_outside_window = True
    store = JsonlSnapshotStore(output / "odds")
    appended = quotes = exact_payloads_deduplicated = 0
    calls_consumed = fixture_result.quota.last_cost or 0
    last_quota = fixture_result.quota
    for task in tasks:
        fixture_id = task.provider_fixture_id
        window = task.window
        result = odds_provider.get_event_odds(fixture_id)
        last_quota = result.quota
        calls_consumed += result.quota.last_cost or 0
        state_key = (fixture_id, window)
        state = all_states[state_key]
        if not result.records or result.raw_observation_id is None:
            updated = record_window_result(
                state,
                attempted_at=datetime.now(UTC),
                provider_status="EMPTY",
                observation_received=False,
                market_available=False if not result.records else None,
            )
            all_states[state_key] = updated
            append_scheduler_event(output, updated, run_id)
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
        was_appended = store.append(
            snapshot,
            source_payload_hash=result.raw_payload_hash,
        )
        appended += int(was_appended)
        exact_payloads_deduplicated += int(not was_appended)
        updated = record_window_result(
            state,
            attempted_at=result.observed_at,
            provider_status="SUCCESS",
            observation_received=True,
            market_available=bool(snapshot.quotes),
        )
        all_states[state_key] = updated
        append_scheduler_event(output, updated, run_id)
        if not diagnostic_outside_window:
            collected.add((fixture_id, window))
    planned_keys = {(task.provider_fixture_id, task.window) for task in tasks}
    if budget.level != BudgetLevel.NORMAL:
        for key, state in tuple(all_states.items()):
            if (
                state.status in {WindowStatus.DUE, WindowStatus.MISSED_RECOVERABLE}
                and key not in planned_keys
            ):
                protected = state.model_copy(
                    update={
                        "status": WindowStatus.SKIPPED_QUOTA,
                        "provider_status": "QUOTA_PROTECTED",
                    }
                )
                all_states[key] = protected
                append_scheduler_event(output, protected, run_id)
    persist_scheduler_states(output, all_states)
    write_ledger(ledger_path, collected)
    authenticated = bool(os.getenv("ODDS_API_KEY"))
    summary = {
        "run_id": run_id,
        "pipeline": "collect-odds",
        "status": workflow_outcome(
            authenticated=authenticated,
            records_received=quotes,
            records_persisted=appended,
        ),
        "origin": (
            DataOrigin.LIVE_SOURCE.value
            if authenticated and quotes
            else "NO_OUTPUT"
        ),
        "provider": fixture_result.provider,
        "authenticated": authenticated,
        "fixtures_visible": len(candidates),
        "tasks_due": len(tasks),
        "diagnostic_outside_window": diagnostic_outside_window,
        "snapshots_appended": appended,
        "quotes_received": quotes,
        "exact_payloads_deduplicated": exact_payloads_deduplicated,
        "calls_consumed": calls_consumed,
        "quota_used": last_quota.used,
        "quota_remaining": last_quota.remaining,
        "budget_level": budget.level.value,
        "budget_explanation": budget.explanation,
        "windows_recoverable": sum(
            state.status == WindowStatus.MISSED_RECOVERABLE
            for state in all_states.values()
        ),
        "windows_missed_final": sum(
            state.status == WindowStatus.MISSED_FINAL
            for state in all_states.values()
        ),
        "next_window": min(
            (
                state.scheduled_for.isoformat()
                for state in all_states.values()
                if state.status == WindowStatus.PENDING
            ),
            default=None,
        ),
        "persistence": "DURABLE_WRITE_STAGED",
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{run_id}.json", summary)
    return summary


def pre_match_shadow(output: Path, *, mock: bool) -> dict[str, object]:
    fixtures_path = output / "fixtures" / "latest.json"
    if not fixtures_path.exists():
        collect_fixtures(output, mock=mock)
    fixtures = json.loads(fixtures_path.read_text("utf-8"))
    predictions: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    journal = DecisionJournal(output / "decisions" / "shadow-decisions.jsonl")
    odds_records = JsonlSnapshotStore(output / "odds").read_all()
    history = pd.read_parquet("data/matches.parquet") if mock else None
    predictions_history = output / "predictions" / "history.jsonl"
    new_predictions = 0
    new_decisions = 0
    durable_required = os.getenv("DURABLE_STORAGE_REQUIRED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    durable_ready = (output / "durable" / "last-ack.json").exists()
    for fixture in fixtures:
        kickoff = datetime.fromisoformat(
            str(fixture["commence_time"]).replace("Z", "+00:00")
        )
        if kickoff <= datetime.now(UTC):
            continue
        home = str(fixture["home_team"])
        away = str(fixture["away_team"])
        fixture_id = stable_internal_id("fixture", "the-odds-api", str(fixture["id"]))
        if not mock and durable_required and not durable_ready:
            blocked.append(
                {
                    "fixture_id": fixture_id,
                    "reason": "DURABLE_STORAGE_UNAVAILABLE",
                    "origin": str(fixture.get("origin", DataOrigin.LIVE_SOURCE.value)),
                }
            )
            continue
        fixture_quotes = [
            record for record in odds_records if record.get("fixture_id") == fixture_id
        ]
        if mock:
            if history is None:
                raise RuntimeError("historique mock indisponible")
            expected_home, expected_away = estimate_expected_goals(
                history,
                home_team=home,
                away_team=away,
                as_of_time=kickoff,
            )
            poisson = poisson_probabilities(expected_home, expected_away)
            elo = EloModel().predict(home, away)
            probabilities = consensus(elo, poisson)
            prediction = {
                "prediction_id": stable_internal_id(
                    "prediction",
                    "demo",
                    f"{fixture_id}:consensus-1.0",
                ),
                "fixture_id": fixture_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "as_of_time": datetime.now(UTC).isoformat(),
                "model_name": "consensus-elo-poisson",
                "model_version": "1.0",
                "dataset_version": "matches-parquet-j2",
                "feature_version": "shadow-v1",
                "probability_home": probabilities.home,
                "probability_draw": probabilities.draw,
                "probability_away": probabilities.away,
                "expected_home_goals": probabilities.expected_home_goals,
                "expected_away_goals": probabilities.expected_away_goals,
                "data_quality_status": QualityStatus.DERIVED.value,
                "uncertainty_status": "HIGH",
                "market_snapshot_id": None,
                "origin": DataOrigin.DEMO_DATA.value,
                "provenance": {"fixture": "DEMO DATA", "history": "LEGACY SOURCE"},
            }
            home_odds = None
            model_disagreement = abs(elo.home - poisson.home) > 0.15
        elif fixture_quotes:
            latest = fixture_quotes[-1]
            quote_rows = latest.get("quotes", [])
            prices: dict[str, list[float]] = {"HOME": [], "DRAW": [], "AWAY": []}
            for quote in quote_rows if isinstance(quote_rows, list) else []:
                market = quote.get("market", {})
                if (
                    isinstance(market, dict)
                    and market.get("market_type") == "1X2"
                ):
                    selection = str(market.get("selection"))
                    if selection in prices:
                        prices[selection].append(float(quote["odds_decimal"]))
            baseline = normalized_market_probabilities(
                prices["HOME"],
                prices["DRAW"],
                prices["AWAY"],
            )
            if baseline is None:
                blocked.append(
                    {
                        "fixture_id": fixture_id,
                        "reason": "INCOMPLETE_1X2_MARKET",
                        "origin": DataOrigin.LIVE_SOURCE.value,
                    }
                )
                continue
            snapshot_id = str(latest.get("snapshot_id"))
            prediction = {
                "prediction_id": stable_internal_id(
                    "prediction",
                    "market-baseline",
                    f"{fixture_id}:{snapshot_id}:1.0",
                ),
                "fixture_id": fixture_id,
                "generated_at": datetime.now(UTC).isoformat(),
                "as_of_time": latest.get("observed_at"),
                "model_name": "MARKET_BASELINE_ONLY",
                "model_version": "1.0",
                "dataset_version": "live-odds-snapshot",
                "feature_version": "market-1x2-v1",
                "probability_home": baseline[0],
                "probability_draw": baseline[1],
                "probability_away": baseline[2],
                "expected_home_goals": None,
                "expected_away_goals": None,
                "data_quality_status": QualityStatus.OBSERVED.value,
                "uncertainty_status": "MARKET_CONSENSUS",
                "market_snapshot_id": snapshot_id,
                "origin": DataOrigin.LIVE_SOURCE.value,
                "provenance": {
                    "fixture": DataOrigin.LIVE_SOURCE.value,
                    "odds": DataOrigin.LIVE_SOURCE.value,
                    "sports_history": "NOT_USED",
                    "source_payload_hash": latest.get("source_payload_hash"),
                },
            }
            home_odds = sum(prices["HOME"]) / len(prices["HOME"])
            model_disagreement = False
        else:
            blocked.append(
                {
                    "fixture_id": fixture_id,
                    "reason": "MISSING_ODDS",
                    "origin": str(
                        fixture.get("origin", DataOrigin.DEMO_DATA.value)
                    ),
                }
            )
            continue
        predictions.append(prediction)
        new_predictions += int(
            append_jsonl_once(
                predictions_history,
                prediction,
                key="prediction_id",
            )
        )
        new_decisions += int(
            journal.append(
                decide_shadow_bet(
                    fixture_id=fixture_id,
                    market_key="1X2",
                    selection="HOME",
                    odds_decimal=home_odds,
                    model_probability=float(prediction["probability_home"]),
                    strategy_version="value-simple-1.0",
                    quality_ok=False,
                    model_disagreement=model_disagreement,
                    origin=str(prediction["origin"]),
                    prediction_id=str(prediction["prediction_id"]),
                )
            )
        )
    write_json(output / "predictions" / "latest.json", predictions)
    write_json(output / "predictions" / "blocked.json", blocked)
    summary = {
        "run_id": runtime_run_id("pre-match"),
        "pipeline": "pre-match-shadow",
        "status": (
            "PRESENT"
            if mock
            else (
                WORKFLOW_SUCCESS_LIVE_DATA
                if predictions
                else WORKFLOW_SUCCESS_NO_DATA
            )
        ),
        "predictions": len(predictions),
        "predictions_created": new_predictions,
        "predictions_blocked": len(blocked),
        "decisions_created": new_decisions,
        "decisions_total": len(journal.read_all()),
        "origin": (
            DataOrigin.DEMO_DATA.value
            if mock
            else (
                DataOrigin.LIVE_SOURCE.value
                if predictions
                else "NO_OUTPUT"
            )
        ),
        "model_policy": (
            "DEMO_CONSENSUS"
            if mock
            else "MARKET_BASELINE_ONLY_WITH_LIVE_ODDS"
        ),
        "durable_storage_required": durable_required,
        "durable_storage_available": durable_ready,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    write_json(output / "runs" / f"{summary['run_id']}.json", summary)
    return summary


def post_match_settlement(output: Path, *, mock: bool) -> dict[str, object]:
    run_id = runtime_run_id("settlement")
    decisions = DecisionJournal(
        output / "decisions" / "shadow-decisions.jsonl"
    ).read_all()
    eligible = [item for item in decisions if item.get("accepted") is True]
    if not eligible:
        summary = {
            "run_id": run_id,
            "pipeline": "post-match-settlement",
            "status": WORKFLOW_SUCCESS_NO_DATA,
            "results_received": 0,
            "settled": 0,
            "eligible_decisions": 0,
            "calls_consumed": 0,
            "message": "aucune décision shadow éligible et terminée",
            "finished_at": datetime.now(UTC).isoformat(),
        }
        write_json(output / "runs" / f"{run_id}.json", summary)
        return summary
    results = provider(output, run_id, mock).get_results()
    summary = {
        "run_id": run_id,
        "pipeline": "post-match-settlement",
        "status": results.availability.value,
        "results_received": len(results.records),
        "settled": 0,
        "eligible_decisions": len(eligible),
        "calls_consumed": results.quota.last_cost or 0,
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
    decisions = DecisionJournal(
        output / "decisions" / "shadow-decisions.jsonl"
    ).read_all()
    predictions = read_jsonl(output / "predictions" / "history.jsonl")
    scheduler_rows = read_json(output / "scheduler" / "latest.json", [])
    rejected: dict[str, int] = {}
    for decision in decisions:
        reason = str(decision.get("primary_reason") or "ACCEPTED")
        rejected[reason] = rejected.get(reason, 0) + 1
    health = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "WARNING" if not snapshots else "PASSED",
        "pipeline_runs": len(runs),
        "successful_runs": sum(
            run.get("status")
            in {
                "PASSED",
                "PRESENT",
                "ABSENT",
                WORKFLOW_SUCCESS_LIVE_DATA,
                WORKFLOW_SUCCESS_NO_DATA,
            }
            for run in runs
        ),
        "snapshots_received": len(snapshots),
        "decisions": len(decisions),
        "rejections_by_reason": rejected,
        "critical_alerts": 0,
        "estimated_cost_eur": 0,
        "persistence": (
            "DURABLE_WRITE_CONFIRMED"
            if (output / "durable" / "last-ack.json").exists()
            else "DURABLE_WRITE_STAGED"
        ),
        "live_snapshots": sum(
            record.get("provider") == "the-odds-api"
            and bool(record.get("source_payload_hash"))
            for record in snapshots
        ),
        "live_predictions": sum(
            item.get("origin") == DataOrigin.LIVE_SOURCE.value
            for item in predictions
        ),
        "production_locked": True,
    }
    raw_paths = sorted((output / "raw" / "observations").rglob("*.json"))
    raw_rows = [
        value
        for path in raw_paths
        for value in [read_json(path)]
        if isinstance(value, dict)
    ]
    last_run = runs[-1] if runs else {}
    metrics = compute_daily_metrics(
        metric_date=datetime.now(UTC).date(),
        runs=runs,
        fixtures=len(read_json(output / "fixtures" / "latest.json", [])),
        snapshots=len(snapshots),
        windows=scheduler_rows if isinstance(scheduler_rows, list) else [],
        predictions=len(predictions),
        decisions=len(decisions),
        settlements=len(read_jsonl(output / "settlements" / "history.jsonl")),
        raw_observations=len(raw_rows),
        provenance_complete=sum(
            bool(item.get("payload_hash"))
            and bool(item.get("provider"))
            and bool(item.get("received_at"))
            for item in raw_rows
        ),
        duplicates=sum(
            int(run.get("exact_payloads_deduplicated", 0))
            for run in runs
        ),
        silent_losses=0,
        quota_used=int(last_run.get("quota_used") or 0),
        quota_remaining=int(last_run.get("quota_remaining") or 20_000),
        quota_limit=20_000,
    )
    metrics["metric_id"] = stable_internal_id(
        "burn-in-daily",
        "internal",
        f"{metrics['date']}:{len(runs)}:{len(snapshots)}",
    )
    append_jsonl_once(
        output / "burn-in" / "daily.jsonl",
        metrics,
        key="metric_id",
    )
    write_json(output / "burn-in" / "latest.json", metrics)
    report_dir = output / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "daily.md").write_text(
        render_daily_report(metrics),
        encoding="utf-8",
    )
    burn_history = read_jsonl(output / "burn-in" / "daily.jsonl")
    (report_dir / "weekly.md").write_text(
        render_weekly_report(burn_history[-7:]),
        encoding="utf-8",
    )
    incidents = IncidentJournal(output / "incidents" / "history.jsonl")
    if health["persistence"] != "DURABLE_WRITE_CONFIRMED":
        incidents.open(
            code="DURABLE_STORAGE_UNCONFIRMED",
            severity=AlertSeverity.CRITICAL,
            cause="aucun accusé de réception durable restauré",
            impact="décisions shadow bloquées lorsque le mode requis est actif",
        )
    else:
        incidents.resolve(
            code="DURABLE_STORAGE_UNCONFIRMED",
            correction="accusé durable restauré",
        )
    health["burn_in"] = metrics
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
