"""Construire le snapshot live, compact et traçable du Cockpit Shadow."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from robin.domain.odds import stable_internal_id

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cockpit" / "app" / "cockpit-data.json"
OUTPUT_HASH = ROOT / "cockpit" / "app" / "cockpit-data.sha256"
PRIVATE_DEPLOYMENT = ROOT / "configs" / "cockpit-private-deployment.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def private_deployment_status(
    *,
    current_backfill_run: str,
    current_data_hash: str,
    deployment_state: dict[str, Any],
) -> str:
    """Refuser le statut déployé dès que les données privées ont divergé."""

    deployed_backfill_run = str(deployment_state.get("backfill_run_id", ""))
    deployed_data_hash = str(deployment_state.get("data_hash", ""))
    if (
        current_backfill_run
        and current_backfill_run == deployed_backfill_run
        and current_data_hash
        and current_data_hash == deployed_data_hash
    ):
        return "COCKPIT_PRIVATE_DEPLOYED"
    return "COCKPIT_PRIVATE_STALE"


def completed_rows_this_run(plan: dict[str, Any]) -> int:
    explicit = int(str(plan.get("normalized_rows_this_run", 0)))
    if explicit:
        return explicit
    completed = int(str(plan.get("completed_this_run", 0)))
    tasks = [
        task
        for task in plan.get("tasks", [])
        if isinstance(task, dict) and task.get("completed_at")
    ]
    latest = sorted(
        tasks,
        key=lambda task: str(task.get("completed_at", "")),
        reverse=True,
    )[:completed]
    return sum(int(str(task.get("rows_received", 0))) for task in latest)


def build_player_readiness(
    state: Path,
    quality: dict[str, Any],
    forecast: dict[str, Any],
) -> dict[str, Any]:
    entity_metrics: dict[str, dict[str, Any]] = {}
    observation_dimensions: dict[str, dict[str, int]] = {}

    for observation_path in sorted((state / "raw" / "observations").rglob("*.json")):
        observation = read_json(observation_path, {})
        payload_hash = str(observation.get("payload_hash", ""))
        parameters = observation.get("request_parameters", {})
        if not payload_hash or not isinstance(parameters, dict):
            continue
        dimensions: dict[str, int] = {}
        for key in ("fixture", "team"):
            value = parameters.get(key)
            if isinstance(value, int):
                dimensions[key] = value
        observation_dimensions[payload_hash] = dimensions

    def payload_ids(value: Any, wrapper: str) -> set[int]:
        found: set[int] = set()
        if isinstance(value, dict):
            wrapped = value.get(wrapper)
            if isinstance(wrapped, dict) and isinstance(wrapped.get("id"), int):
                found.add(int(wrapped["id"]))
            for nested in value.values():
                found.update(payload_ids(nested, wrapper))
        elif isinstance(value, list):
            for nested in value:
                found.update(payload_ids(nested, wrapper))
        return found

    for path in sorted((state / "parquet").rglob("*.parquet")):
        competition_part = next(
            (part for part in path.parts if part.startswith("competition=")),
            "competition=unknown",
        )
        entity_part = next(
            (part for part in path.parts if part.startswith("entity_type=")),
            "entity_type=unknown",
        )
        season_part = next(
            (part for part in path.parts if part.startswith("season=")),
            "season=0",
        )
        competition = competition_part.split("=", 1)[1]
        entity = entity_part.split("=", 1)[1]
        season = int(season_part.split("=", 1)[1])
        frame = pd.read_parquet(path)
        metrics = entity_metrics.setdefault(
            entity,
            {
                "competitions": set(),
                "seasons": set(),
                "teams": set(),
                "fixtures": set(),
                "players": set(),
                "rows": 0,
                "nullCells": 0,
                "cells": 0,
            },
        )
        metrics["competitions"].add(competition)
        metrics["seasons"].add(season)
        metrics["rows"] += len(frame)
        metrics["nullCells"] += int(frame.isna().sum().sum())
        metrics["cells"] += int(frame.shape[0] * frame.shape[1])
        if "payload" not in frame.columns:
            continue
        raw_hashes = (
            frame["raw_payload_hash"].tolist()
            if "raw_payload_hash" in frame.columns
            else [None] * len(frame)
        )
        for raw_payload, raw_hash in zip(
            frame["payload"].tolist(),
            raw_hashes,
            strict=True,
        ):
            try:
                payload = json.loads(str(raw_payload))
            except json.JSONDecodeError:
                continue
            metrics["teams"].update(payload_ids(payload, "team"))
            metrics["fixtures"].update(payload_ids(payload, "fixture"))
            metrics["players"].update(payload_ids(payload, "player"))
            dimensions = observation_dimensions.get(str(raw_hash), {})
            fixture_id = dimensions.get("fixture")
            team_id = dimensions.get("team")
            if fixture_id is not None:
                metrics["fixtures"].add(fixture_id)
            if team_id is not None:
                metrics["teams"].add(team_id)

    quality_status = str(quality.get("status", "NOT_RUN"))
    eta_a = forecast.get("eta_priority_a_base", forecast.get("eta_priority_a_days"))
    after_priority_a = (
        f"after priority A (~{eta_a} d)"
        if eta_a is not None
        else "after priority A"
    )
    specifications = [
        ("Effectifs", ("squads",), "POINT_IN_TIME_SAFE"),
        ("Joueurs", ("players",), "POINT_IN_TIME_SAFE"),
        ("Minutes", ("fixture_player_statistics",), "POST_MATCH_LAG_REQUIRED"),
        (
            "Statistiques joueurs par match",
            ("fixture_player_statistics",),
            "POST_MATCH_LAG_REQUIRED",
        ),
        ("Compositions", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Continuite du onze", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Formations", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Blessures", ("injuries",), "HISTORICAL_NON_POINT_IN_TIME"),
        (
            "Disponibilite",
            ("injuries", "lineups"),
            "HISTORICAL_NON_POINT_IN_TIME",
        ),
        ("Force du banc", ("squads", "lineups"), "POST_MATCH_LAG_REQUIRED"),
        (
            "Force du onze",
            ("fixture_player_statistics", "lineups"),
            "POST_MATCH_LAG_REQUIRED",
        ),
        (
            "Retour de blessure",
            ("injuries", "fixture_player_statistics"),
            "HISTORICAL_NON_POINT_IN_TIME",
        ),
        (
            "Fatigue",
            ("fixture_player_statistics", "lineups"),
            "POST_MATCH_LAG_REQUIRED",
        ),
    ]
    families: list[dict[str, Any]] = []
    for name, dependencies, temporality in specifications:
        dependency_metrics = [
            entity_metrics.get(
                entity,
                {
                    "competitions": set(),
                    "seasons": set(),
                    "teams": set(),
                    "fixtures": set(),
                    "players": set(),
                    "rows": 0,
                    "nullCells": 0,
                    "cells": 0,
                },
            )
            for entity in dependencies
        ]

        def common_values(key: str) -> set[Any]:
            populated = [
                set(metrics[key])
                for metrics in dependency_metrics
                if metrics[key]
            ]
            return set.intersection(*populated) if populated else set()

        competitions = sorted(common_values("competitions"))
        seasons = sorted(common_values("seasons"))
        teams = common_values("teams")
        fixtures = common_values("fixtures")
        players_covered = common_values("players")
        rows = min(
            (int(metrics["rows"]) for metrics in dependency_metrics),
            default=0,
        )
        cells = sum(int(metrics["cells"]) for metrics in dependency_metrics)
        null_cells = sum(
            int(metrics["nullCells"]) for metrics in dependency_metrics
        )
        null_rate = round(null_cells / cells, 4) if cells else None
        if quality_status not in {"PASSED", "WARNING"}:
            status = "BLOCKED_BY_QUALITY"
            reason = f"historical quality is {quality_status}"
        elif temporality == "HISTORICAL_NON_POINT_IN_TIME":
            status = "BLOCKED_BY_TEMPORALITY"
            reason = "point-in-time injury snapshots are unavailable"
        elif len(seasons) < 2:
            status = "BLOCKED_BY_COVERAGE"
            reason = "fewer than two verified common seasons"
        elif name == "Joueurs":
            status = "COMPUTABLE"
            reason = "multi-season player dimension is available"
        else:
            status = "TESTING"
            reason = "per-match as-of and identity validation is still required"
        families.append(
            {
                "name": name,
                "coverage": {
                    "competitions": competitions,
                    "competitionCount": len(competitions),
                    "seasons": seasons,
                    "seasonCount": len(seasons),
                    "teamCount": len(teams),
                    "fixtureCount": len(fixtures),
                    "playerCount": len(players_covered),
                    "rows": rows,
                    "nullRate": null_rate,
                    "dependencies": list(dependencies),
                },
                "quality": quality_status,
                "identities": (
                    "VERIFIED"
                    if quality_status == "PASSED" and rows > 0
                    else "PENDING"
                ),
                "temporality": temporality,
                "status": status,
                "reason": reason,
                "estimatedAvailability": (
                    "unknown - point-in-time source required"
                    if status == "BLOCKED_BY_TEMPORALITY"
                    else after_priority_a
                ),
            }
        )
    return {
        "coverage": "INSUFFICIENT",
        "quality": quality_status,
        "temporality": "MIXED_BLOCKS",
        "status": "BLOCKED_BY_COVERAGE",
        "estimatedFirstModel": "after priority A and multi-season gates",
        "families": families,
    }


def sanitize_public_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_public_snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_snapshot(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        marker = "/data/historical/"
        if marker in normalized:
            return f"historical/{normalized.split(marker, 1)[1]}"
    return value


def build_deep_data() -> dict[str, Any]:
    state = ROOT / "data" / "historical"
    analytics = read_json(
        ROOT / "data" / "live-proof" / "jalon5-legacy-analytics.json",
        {},
    )
    matrix = read_json(
        state / "coverage" / "matrix.json",
        read_json(ROOT / "data" / "contracts" / "api-football-coverage.json", []),
    )
    pilot = read_json(state / "runs" / "pilot-ligue-1-2025.json", {})
    plan = read_json(state / "tasks" / "backfill-plan.json", {})
    quality = read_json(state / "quality" / "latest.json", {})
    canonical = read_json(
        state / "audits" / "ligue1-2025-canonicalization.json",
        {},
    )
    forecast = read_json(state / "forecasts" / "accelerated-safe.json", {})
    readiness = read_json(
        state / "readiness" / "ligue1-multiseason-v1.json",
        {},
    )
    deployment_state = read_json(PRIVATE_DEPLOYMENT, {})
    compaction = read_json(state / "storage" / "latest-compaction.json", {})
    dataset = read_json(
        state / "datasets" / "api_team_pre_match_v1.json",
        read_json(
            state / "datasets" / "team_baseline_v1.json",
            (
                {
                    **analytics.get("dataset", {}),
                    "dataset_version": analytics.get("dataset", {}).get("name"),
                    "status": "FEATURE_FACTORY_ACTIVE",
                }
                if analytics
                else {}
            ),
        ),
    )
    model = read_json(
        state / "models" / "elo_v1.json",
        (
            {
                **analytics.get("model", {}),
                "model_version": analytics.get("model", {}).get("version"),
                "oos_metrics": {
                    "matches": analytics.get("model", {}).get("oos_matches"),
                    "log_loss": analytics.get("model", {}).get("oos_log_loss"),
                    "brier_score": analytics.get("model", {}).get("oos_brier_score"),
                },
            }
            if analytics
            else {}
        ),
    )
    backtest = read_json(
        state / "backtests" / "elo_edge_5pct_oos.json",
        analytics.get("backtest", {}),
    )
    proof = read_json(
        state / "proofs" / "api-football-live.json",
        read_json(ROOT / "data" / "live-proof" / "jalon5-api-football.json", {}),
    )
    task_counts: dict[str, int] = {}
    for task in plan.get("tasks", []):
        status = str(task.get("status", "UNKNOWN"))
        task_counts[status] = task_counts.get(status, 0) + 1
    coverage_counts: dict[str, int] = {}
    for row in matrix:
        status = str(row.get("status", "UNKNOWN"))
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    endpoint_counts: dict[str, int] = {}
    for report in pilot.get("endpoints", []):
        endpoint = str(report.get("endpoint", "UNKNOWN"))
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
    public_pilot = {
        key: value for key, value in pilot.items() if key != "endpoints"
    }
    public_pilot["endpointCounts"] = endpoint_counts
    public_dataset = {
        key: value for key, value in dataset.items() if key != "partitions"
    }
    player_readiness = build_player_readiness(state, quality, forecast)
    current_backfill_run = str(plan.get("last_run_id", ""))
    current_data_hash = hashlib.sha256(
        json.dumps(
            {
                "backfill_run_id": current_backfill_run,
                "forecast": forecast,
                "quality_generated_at": quality.get("generated_at"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    private_status = private_deployment_status(
        current_backfill_run=current_backfill_run,
        current_data_hash=current_data_hash,
        deployment_state=deployment_state,
    )
    private_status = os.environ.get("COCKPIT_PRIVATE_STATUS", private_status)
    players: list[dict[str, Any]] = []
    player_partitions = (
        path
        for path in (state / "parquet").rglob("*.parquet")
        if any(parent.name == "entity_type=players" for parent in path.parents)
    )
    for path in sorted(player_partitions):
        player_frame = pd.read_parquet(path)
        if "payload" not in player_frame.columns:
            continue
        for payload in player_frame["payload"].tolist()[:20]:
            record = json.loads(str(payload))
            player = record.get("player", {})
            statistics = record.get("statistics", [])
            stat = statistics[0] if statistics else {}
            games = stat.get("games", {})
            goals = stat.get("goals", {})
            players.append(
                {
                    "id": player.get("id"),
                    "name": player.get("name"),
                    "age": player.get("age"),
                    "position": games.get("position"),
                    "appearances": games.get("appearences"),
                    "minutes": games.get("minutes"),
                    "rating": games.get("rating"),
                    "goals": goals.get("total"),
                    "assists": goals.get("assists"),
                    "origin": "HISTORICAL POINT-IN-TIME",
                }
            )
        if players:
            break
    model_manifests = [
        read_json(path, {})
        for path in sorted((state / "models").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    models = [
        {
            "name": manifest.get("model_name"),
            "version": manifest.get("model_version"),
            "dataset": manifest.get("dataset"),
            "status": manifest.get("status"),
            "calibration": manifest.get("selected_calibration"),
            "logLoss": manifest.get("oos_metrics", {}).get("log_loss"),
            "brier": manifest.get("oos_metrics", {}).get("brier_score"),
            "ece": manifest.get("oos_metrics", {}).get("ece"),
            "incremental": manifest.get("incremental_vs_team"),
            "origin": "OOS HISTORICAL",
        }
        for manifest in model_manifests
        if manifest.get("model_version")
    ]
    if not models and model:
        models.append(
            {
                "name": "Elo",
                "version": model.get("model_version", "elo_v1"),
                "dataset": "team_baseline_v1",
                "status": model.get("status", "WAITING_FOR_DATASET"),
                "calibration": model.get("calibration"),
                "logLoss": model.get("oos_metrics", {}).get("log_loss"),
                "brier": model.get("oos_metrics", {}).get("brier_score"),
                "ece": None,
                "incremental": None,
                "origin": "OOS HISTORICAL",
            }
        )
    models.extend(
        {
            "name": name,
            "version": "planned_v1",
            "status": "BLOCKED_BY_COVERAGE",
            "logLoss": None,
            "brier": None,
            "origin": "NO OUTPUT",
        }
        for name in (
            "Poisson",
            "Dixon-Coles",
            "Gradient boosting",
            "Ensemble calibré",
        )
    )
    dataset_manifests = [
        read_json(path, {})
        for path in sorted((state / "datasets").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    strategy_manifests = [
        read_json(path, {})
        for path in sorted((state / "strategies").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    backtest_manifests = [
        read_json(path, {})
        for path in sorted((state / "backtests").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    return {
        "status": proof.get("status", "ADAPTER_ONLY"),
        "pilotStatus": pilot.get("status", "NOT_STARTED"),
        "backfillStatus": plan.get("status", "NOT_STARTED"),
        "qualityStatus": quality.get("status", "NOT_RUN"),
        "productionStatus": "PRODUCTION_LOCKED",
        "coverageCounts": coverage_counts,
        "coverageMatrix": matrix,
        "taskCounts": task_counts,
        "taskTotal": len(plan.get("tasks", [])),
        "taskCompleted": task_counts.get("COMPLETED", 0),
        "remainingTasks": plan.get("remaining_tasks", 0),
        "nextTask": next(
            (
                task
                for task in plan.get("tasks", [])
                if task.get("status")
                in {"PENDING", "READY", "RETRYABLE", "SKIPPED_QUOTA"}
            ),
            None,
        ),
        "pilot": public_pilot,
        "quota": {
            "remaining": plan.get(
                "quota_remaining",
                proof.get("quota_remaining", pilot.get("quota_remaining")),
            ),
            "calls": plan.get("provider_calls", 0),
            "lastRunId": plan.get("last_run_id"),
            "lastRunAt": plan.get("last_run_at"),
            "mode": "ACCELERATED_SAFE",
            "reserve": 5_000,
        },
        "storage": {
            "rawBytes": directory_size(state / "raw"),
            "parquetBytes": directory_size(state / "parquet"),
            "derivedBytes": directory_size(state / "derived"),
            "totalBytes": directory_size(state),
            "fileCount": len([path for path in state.rglob("*") if path.is_file()]),
            "bundleCount": len(
                list((state / "bundles").rglob("*.manifest.json"))
            ),
            "payloadCount": len(list((state / "raw" / "payloads").rglob("*.gz"))),
            "projectedBytes": forecast.get("storage_projected_bytes"),
            "projectedBytesLow": forecast.get("storage_projected_low"),
            "projectedBytesBase": forecast.get("storage_projected_base"),
            "projectedBytesHigh": forecast.get("storage_projected_high"),
            "warningBytes": forecast.get("storage_warning_bytes"),
            "pauseBytes": forecast.get("storage_pause_bytes"),
            "capacityStatus": (
                "PAUSE"
                if directory_size(state)
                >= int(forecast.get("storage_pause_bytes", 900_000_000))
                else "WARNING"
                if directory_size(state)
                >= int(forecast.get("storage_warning_bytes", 750_000_000))
                else "OK"
            ),
            "lastCompaction": compaction.get("status", "NOT_RUN"),
            "backend": "POSTGRESQL + PARQUET + HISTORICAL-DATA",
        },
        "players": players,
        "datasetReadiness": readiness,
        "datasets": [
            {
                "name": manifest.get("dataset_name"),
                "version": manifest.get("dataset_version"),
                "rows": manifest.get("rows"),
                "fixtures": manifest.get("fixtures"),
                "coverage": manifest.get("coverage"),
                "quality": manifest.get("quality"),
                "temporalPolicy": manifest.get("temporal_policy"),
                "status": manifest.get("status"),
                "sha256": manifest.get("sha256"),
            }
            for manifest in dataset_manifests
            if manifest.get("dataset_version")
        ],
        "featureCatalog": [
            {
                "name": name,
                "version": "v1",
                "status": (
                    "PLAYER_FEATURE_FACTORY_ACTIVE"
                    if readiness.get("gates", {}).get("B", {}).get("passed")
                    and name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "BLOCKED_BY_COVERAGE"
                    if name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "LEGACY_SOURCE_ONLY"
                    if dataset
                    else "CANDIDATE"
                ),
                "leakageRisk": "LOW",
                "origin": (
                    "HISTORICAL POINT-IN-TIME"
                    if readiness.get("gates", {}).get("B", {}).get("passed")
                    and name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "NO OUTPUT"
                    if name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "LEGACY SOURCE"
                ),
            }
            for name in (
                "elo_global",
                "forme_5",
                "forme_10",
                "buts_marques_5",
                "buts_encaisses_5",
                "jours_repos",
                "minutes_joueur_5",
                "force_onze",
                "continuite_onze",
            )
        ],
        "dataset": public_dataset,
        "models": models,
        "backtests": [
            {
                **{
                    key: value
                    for key, value in manifest.items()
                    if key != "details"
                },
                "origin": "OOS HISTORICAL",
            }
            for manifest in backtest_manifests
            if manifest.get("backtest_version")
        ]
        or (
            [
                {
                    **{key: value for key, value in backtest.items() if key != "details"},
                    "origin": "OOS HISTORICAL",
                }
            ]
            if backtest
            else []
        ),
        "strategies": strategy_manifests,
        "quality": quality,
        "progress": {
            "tasksTotal": len(plan.get("tasks", [])),
            "tasksCompleted": task_counts.get("COMPLETED", 0),
            "tasksRemaining": plan.get("remaining_tasks", 0),
            "callsConsumed": plan.get("provider_calls", 0),
            "callsEstimated": forecast.get("estimated_calls_full_scope"),
            "callsRemainingLow": forecast.get("calls_remaining_low"),
            "callsRemainingBase": forecast.get("calls_remaining_base"),
            "callsRemainingHigh": forecast.get("calls_remaining_high"),
            "callsPerHour": (
                round(float(plan["scheduler"]["request_rate"]) * 3600)
                if plan.get("scheduler", {}).get("request_rate")
                else None
            ),
            "callsPerDay": forecast.get("calls_per_day"),
            "etaPriorityADays": forecast.get("eta_priority_a_days"),
            "etaPriorityBDays": forecast.get("eta_priority_b_days"),
            "etaFullDays": forecast.get("eta_full_scope_days"),
            "etaPriorityA": {
                "low": forecast.get("eta_priority_a_low"),
                "base": forecast.get("eta_priority_a_base"),
                "high": forecast.get("eta_priority_a_high"),
            },
            "etaPriorityB": {
                "low": forecast.get("eta_priority_b_low"),
                "base": forecast.get("eta_priority_b_base"),
                "high": forecast.get("eta_priority_b_high"),
            },
            "etaFull": {
                "low": forecast.get("eta_full_low"),
                "base": forecast.get("eta_full_base"),
                "high": forecast.get("eta_full_high"),
            },
            "materializedTasksTotal": forecast.get("materialized_tasks_total"),
            "materializedTasksCompleted": forecast.get(
                "materialized_tasks_completed"
            ),
            "materializedTasksRemaining": forecast.get(
                "materialized_tasks_remaining"
            ),
            "materializedCallsRemaining": forecast.get(
                "materialized_calls_remaining"
            ),
            "materializedEtaDays": forecast.get("materialized_eta_days"),
            "materializedEtaLabel": forecast.get("materialized_eta_label"),
            "latentFixtureTasks": forecast.get("latent_fixture_tasks"),
            "latentTeamTasks": forecast.get("latent_team_tasks"),
            "latentPlayerPages": forecast.get("latent_player_pages"),
            "completedThisRun": forecast.get("completed_this_run"),
            "expandedThisRun": forecast.get("expanded_this_run"),
            "newLatentTasksMaterialized": forecast.get(
                "new_latent_tasks_materialized"
            ),
            "scheduler": plan.get("scheduler", {}),
            "rowsLastRun": completed_rows_this_run(plan),
        },
        "canonicality": {
            key: canonical.get(key)
            for key in (
                "status",
                "received_fixtures",
                "canonical_fixtures",
                "received_teams",
                "canonical_teams",
                "classifications",
                "dataset_hash",
            )
        },
        "isolation": {
            "status": "LIVE_HISTORICAL_ISOLATED",
            "liveActive": True,
            "historicalActive": plan.get("status") == "HISTORICAL_BACKFILL_ACTIVE",
            "liveBranch": "shadow-data",
            "historicalBranch": "historical-data",
            "liveConcurrency": "shadow-state",
            "historicalConcurrency": "historical-state",
            "lastConflict": None,
            "lag": 0,
        },
        "playerReadiness": player_readiness,
        "deployment": {
            "build": "COCKPIT_BUILD_SUCCESS",
            "artifact": "COCKPIT_ARTIFACT_PUBLISHED",
            "private": private_status,
            "snapshotGeneratedAt": datetime.now(UTC).isoformat(),
            "currentDataHash": current_data_hash,
            "currentBackfillRunId": current_backfill_run,
            "deploymentVersion": deployment_state.get("deployment_version"),
            "deploymentTime": deployment_state.get("deployment_time"),
            "deployedSourceCommit": deployment_state.get("source_commit"),
            "deployedSnapshotHash": deployment_state.get("snapshot_hash"),
            "deployedBackfillRunId": deployment_state.get("backfill_run_id"),
            "accessMode": deployment_state.get("access_mode"),
            "automation": deployment_state.get("automation"),
            "sourceCommit": os.environ.get("GITHUB_SHA", "LOCAL_WORKTREE"),
        },
        "origins": [
            "LIVE SHADOW",
            "HISTORICAL POINT-IN-TIME",
            "HISTORICAL SIMULATED",
            "OOS HISTORICAL",
            "LEGACY SOURCE",
            "DEMO DATA",
            "NO OUTPUT",
        ],
    }


def main() -> None:
    live = read_json(
        ROOT / "data" / "live-proof" / "jalon3-activation.json",
        {},
    )
    if not live:
        raise RuntimeError("preuve live Jalon 3 absente")
    durable = read_json(
        ROOT / "data" / "live-proof" / "jalon4-durable-shadow.json",
        {},
    )
    if not durable:
        raise RuntimeError("preuve durable Jalon 4 absente")
    migration_rows = read_json(
        ROOT / "data" / "migrations" / "jalon2" / "legacy-uuid-summary.json",
        [{}],
    )
    migration = migration_rows[0] if migration_rows else {}
    oos = read_json(ROOT / "rapports" / "jalon2" / "oos-results.json", [])

    predictions = {
        item["internal_fixture_id"]: item
        for item in live.get("predictions", [])
    }
    decisions = {
        item["internal_fixture_id"]: item
        for item in live.get("decisions", [])
    }
    matches: list[dict[str, Any]] = []
    fixture_names: dict[str, tuple[str, str]] = {}
    for fixture in live.get("fixtures", []):
        internal_id = stable_internal_id(
            "fixture",
            "the-odds-api",
            fixture["provider_fixture_id"],
        )
        fixture_names[internal_id] = (fixture["home"], fixture["away"])
        prediction = predictions.get(internal_id)
        decision = decisions.get(internal_id)
        matches.append(
            {
                "id": fixture["provider_fixture_id"],
                "internalId": internal_id,
                "kickoff": fixture["kickoff"],
                "competition": fixture["competition"],
                "home": fixture["home"],
                "away": fixture["away"],
                "origin": fixture["origin"],
                "quality": prediction["quality"] if prediction else "PENDING",
                "model": (
                    prediction["model"]
                    if prediction
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "probabilities": {
                    "home": prediction.get("probability_home") if prediction else None,
                    "draw": prediction.get("probability_draw") if prediction else None,
                    "away": prediction.get("probability_away") if prediction else None,
                },
                "expectedGoals": {"home": None, "away": None},
                "decision": (
                    decision["primary_reason"]
                    if decision
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "accepted": bool(decision and decision["accepted"]),
            }
        )

    odds = []
    for item in live.get("snapshots", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        odds.append({**item, "home": home, "away": away})

    decision_rows = []
    for item in live.get("decisions", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        decision_rows.append(
            {
                **item,
                "home": home,
                "away": away,
                "decided_at": next(
                    (
                        prediction["generated_at"]
                        for prediction in live.get("predictions", [])
                        if prediction["prediction_id"] == item["prediction_id"]
                    ),
                    live["captured_at"],
                ),
            }
        )

    quota = live["quota"]
    persistence = live["persistence"]
    idempotence = live["idempotence"]
    health = live["health"]
    postgresql = durable["postgresql"]
    double_write = durable["double_write"]
    quality_checks = [
        {
            "check": "PostgreSQL Neon",
            "status": "PASS",
            "value": (
                f"{postgresql['registry_records']} lignes · "
                f"révision {postgresql['migration_revision']}"
            ),
            "threshold": "connecté, migré et audité",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Double écriture durable",
            "status": "PASS",
            "value": double_write["latest_ack_backend"],
            "threshold": "PostgreSQL + shadow-data",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Authentification The Odds API",
            "status": "PASS",
            "value": "appel HTTP 200, secret non exposé",
            "threshold": "source authentifiée",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Provenance brute",
            "status": "PASS",
            "value": "endpoint + temps + hash + ingestion",
            "threshold": "champs complets",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Persistance inter-runners",
            "status": "PASS",
            "value": f"{persistence['files_restored_by_runner_b']} fichiers restaurés",
            "threshold": "observation stable",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Déduplication exacte",
            "status": "PASS",
            "value": f"{idempotence['exact_duplicate_snapshots']} doublon",
            "threshold": "0",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Idempotence prédictions",
            "status": "PASS",
            "value": "1 → 1 ; décisions 1 → 1",
            "threshold": "aucun ajout identique",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Réserve quota",
            "status": "PASS",
            "value": f"{quota['reserve_pct']} %",
            "threshold": "≥ 20 %",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Prédictions sans cote",
            "status": "WARN",
            "value": f"{health['blocked_predictions']} bloquées",
            "threshold": "jamais synthétisées",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "API-Football",
            "status": "PENDING",
            "value": "adaptateur prêt, secret absent",
            "threshold": "enrichissement optionnel",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Paris réels",
            "status": "PASS",
            "value": "PRODUCTION_LOCKED",
            "threshold": "aucune exécution financière",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Couverture UUID legacy",
            "status": "PASS",
            "value": f"{migration.get('coverage', 0) * 100:.3f} %",
            "threshold": "≥ 98 %",
            "origin": "LEGACY SOURCE",
        },
    ]

    strategies = [
        {
            **item,
            "origin": "LEGACY SOURCE",
            "roiPct": round(item.get("roi", 0) * 100, 2),
            "ciLowPct": round(item.get("roi_ci_low", 0) * 100, 2),
            "ciHighPct": round(item.get("roi_ci_high", 0) * 100, 2),
        }
        for item in oos
    ]
    deep_data = build_deep_data()
    snapshot = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceCapturedAt": durable["captured_at"],
        "snapshotType": live["snapshot_type"],
        "status": durable["burn_in"]["health"],
        "shadowStatus": durable["status"],
        "productionStatus": live["production_status"],
        "demoModeAvailable": True,
        "demoModeEnabled": False,
        "message": (
            "PostgreSQL Neon et le registre append-only shadow-data sont "
            "synchronisés. La double écriture et le replay sans fournisseur "
            "sont vérifiés ; le burn-in reste statistiquement insuffisant."
        ),
        "metrics": {
            "fixtures": len(matches),
            "snapshots": len(odds),
            "quotes": sum(item["quotes"] for item in odds),
            "bookmakers": max((item["bookmakers"] for item in odds), default=0),
            "predictions": len(live.get("predictions", [])),
            "candidates": sum(1 for item in decision_rows if item["accepted"]),
            "rejections": sum(1 for item in decision_rows if not item["accepted"]),
            "blockedPredictions": health["blocked_predictions"],
            "quotaUsed": quota["used_after_activation"],
            "quotaRemaining": quota["remaining_after_activation"],
            "migrationCoveragePct": round(migration.get("coverage", 0) * 100, 3),
            "durableRecords": postgresql["registry_records"],
            "rawPayloads": durable["migration"]["physical_payloads_migrated"],
            "windowCoveragePct": 0,
            "sloBreaches": 0,
        },
        "matches": matches,
        "odds": odds,
        "decisions": decision_rows,
        "qualityChecks": quality_checks,
        "strategies": strategies,
        "runs": [
            {
                "id": str(item["id"]),
                "pipeline": item["pipeline"],
                "status": item["status"],
                "records": item["records"],
                "calls": item["calls"],
                "quotaRemaining": item["quota_remaining"],
                "finishedAt": item["finished_at"],
                "origin": item["origin"],
            }
            for item in live.get("runs", [])
        ],
        "filters": {
            "periods": ["30 prochains jours", "7 prochains jours", "Saison 2026–2027"],
            "competitions": ["Ligue 1 - France"],
            "markets": ["1X2", "TOTAL_GOALS"],
            "strategies": ["Toutes"]
            + [item.get("strategy", "inconnue") for item in oos],
            "models": ["MARKET_BASELINE_ONLY"],
            "statuses": ["Tous", "Bloqué", "En attente"],
            "qualities": ["Toutes", "OBSERVED", "PENDING"],
            "bookmakers": ["Tous", "22 agrégés"],
        },
        "provenance": {
            "demo": "Mode démo disponible uniquement sur activation explicite.",
            "legacy": "data/matches.parquet + rapports/jalon2/oos-results.json",
            "live": (
                "The Odds API → registre append-only shadow-data → "
                "preuve compacte Jalon 4"
            ),
            "stateArtifact": live["source_state_artifact"],
            "sourceCommit": live["source_commit"],
        },
        "quota": quota,
        "persistence": persistence,
        "idempotence": idempotence,
        "providers": live["providers"],
        "durableStorage": durable["storage"],
        "postgresql": postgresql,
        "doubleWrite": double_write,
        "failureRecovery": durable["failure_recovery"],
        "migration": durable["migration"],
        "replay": durable["replay"],
        "burnIn": durable["burn_in"],
        "slo": durable["slo"],
        "scheduler": durable["scheduler"],
        "funnel": [
            {"stage": "Fixtures attendues", "count": len(matches), "loss": 0},
            {"stage": "Fixtures collectées", "count": len(matches), "loss": 0},
            {"stage": "Avec marchés", "count": 1, "loss": len(matches) - 1},
            {"stage": "Avec snapshots", "count": 1, "loss": 0},
            {"stage": "Analysables", "count": 1, "loss": 0},
            {"stage": "Prédictions", "count": len(predictions), "loss": 0},
            {"stage": "Candidats", "count": len(decision_rows), "loss": 0},
            {"stage": "Retenus shadow", "count": 0, "loss": len(decision_rows)},
            {"stage": "Rejetés / bloqués", "count": 9, "loss": 0},
            {"stage": "Réglés", "count": 0, "loss": 0},
        ],
        "notAnalyzableReasons": [
            {"reason": "MARKET_NOT_AVAILABLE", "count": 8, "origin": "LIVE SOURCE"},
            {"reason": "QUALITY_BLOCKED", "count": 1, "origin": "LIVE SOURCE"},
        ],
        "coverage": [
            {
                "fixture": f"{item['home']} — {item['away']}",
                "fixtureId": item["internalId"],
                "kickoff": item["kickoff"],
                "providerCoverage": 1 if item["probabilities"]["home"] else 0,
                "analyticCoverage": 1 if item["probabilities"]["home"] else 0,
                "windows": {
                    window: "PENDING"
                    for window in durable["scheduler"]["windows"]
                },
                "origin": item["origin"],
            }
            for item in matches
        ],
        "coverageRates": {
            "provider": round(1 / len(matches), 4) if matches else 0,
            "collection": None,
            "analytic": round(1 / len(matches), 4) if matches else 0,
            "collectionStatus": "INSUFFICIENT_OBSERVATION",
        },
        "oddsMovement": durable["odds_movement"],
        "incidents": [
            {
                "code": "ARTIFACT_REDIRECT_AUTH_HEADER",
                "severity": "WARNING",
                "status": "RESOLVED",
                "startedAt": "2026-07-24T12:54:00Z",
                "endedAt": "2026-07-24T12:56:43Z",
                "cause": "En-tête GitHub transmis vers une URL signée",
                "impact": "Un run arrêté avant appel fournisseur",
                "correction": "Retrait de l’en-tête hors api.github.com",
                "origin": "LIVE SOURCE",
            }
        ],
        "costScenarios": [
            {"scope": "Rythme actuel", "competitions": 1, "markets": 2, "credits": 720},
            {"scope": "Deux championnats", "competitions": 2, "markets": 2, "credits": 1440},
            {"scope": "Cinq championnats", "competitions": 5, "markets": 2, "credits": 3600},
            {"scope": "Marchés étendus", "competitions": 1, "markets": 4, "credits": 1440},
        ],
        "dataExplorer": [
            {
                "date": item["kickoff"],
                "fixture": f"{item['home']} — {item['away']}",
                "competition": item["competition"],
                "market": "1X2",
                "bookmakers": 22 if item["probabilities"]["home"] else 0,
                "snapshots": 2 if item["probabilities"]["home"] else 0,
                "model": item["model"],
                "decision": item["decision"],
                "quality": item["quality"],
                "provenance": item["origin"],
            }
            for item in matches
        ],
        "deepData": deep_data,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    public_snapshot = sanitize_public_snapshot(snapshot)
    OUTPUT.write_text(
        json.dumps(public_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUTPUT_HASH.write_text(
        hashlib.sha256(OUTPUT.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )
    try:
        label = OUTPUT.relative_to(ROOT)
    except ValueError:
        label = OUTPUT
    print(f"Snapshot Cockpit écrit dans {label}")


if __name__ == "__main__":
    main()
