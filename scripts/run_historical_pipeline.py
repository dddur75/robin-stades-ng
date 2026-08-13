"""Piloter la Deep Data Factory sans intervention ni secret dans les sorties."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import func, insert, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from robin.backtesting.v3 import (
    StrategyParameters,
    run_backtest,
    strategy_sensitivity,
)
from robin.historical.canonical import (
    CompetitionFormat,
    canonical_dataset_hash,
    canonicalize_fixtures,
    validate_canonical_cardinality,
)
from robin.historical.critical_closure import storage_readiness
from robin.historical.dataset_factory import (
    build_api_team_pre_match,
    build_player_feature_datasets,
    player_match_facts,
    write_dataset,
)
from robin.historical.features import (
    assert_temporal_integrity,
    build_team_feature_rows,
    dataset_manifest,
)
from robin.historical.forecast import build_complete_forecast
from robin.historical.model_lab import (
    LINEUP_FEATURES,
    PLAYER_FEATURES,
    TEAM_FEATURES,
    run_model_lab,
)
from robin.historical.model_lab import (
    target as model_target,
)
from robin.historical.modeling import backtest_fixed_stake, train_elo_baseline
from robin.historical.normalization import entity_type_for_endpoint, normalize_records
from robin.historical.orchestrator import (
    BUSINESS_PRIORITY_ORDER,
    COMPETITION_TARGETS,
    CORE_ENDPOINTS,
    build_backfill_plan,
    business_value_priority,
    quota_decision,
    select_validated_competition,
    stable_task_id,
    storage_allows_business_priority,
)
from robin.historical.pagination import iterate_pages
from robin.historical.quality import (
    historical_quality_report,
    repair_raw_hash_provenance,
)
from robin.historical.readiness import (
    build_multiseason_readiness,
    readiness_markdown,
)
from robin.historical.scheduling import (
    BackfillTelemetry,
    accelerated_safe_plan,
    observed_throughput,
)
from robin.historical.scientific_arena import (
    OOS_GOVERNANCE,
    ablation_registry,
    apply_selected_calibration,
    arena_cache_key,
    deterministic_permutation_control,
    external_validation_protocol,
    feature_stability_audit,
    freeze_jalon6,
    paired_model_comparison,
    prediction_leaderboard_row,
    random_lineup_control,
    score_model_predictions,
    stable_hash,
    storage_guard,
    strategy_lab_v2_protocol,
    temporal_discriminative_predictions,
    validated_ensemble,
)
from robin.historical.storage import (
    GzipPayloadBackend,
    HistoricalBundleStore,
    PartitionedParquetStore,
    directory_size,
    storage_inventory,
    write_json_atomic,
)
from robin.ingestion.raw_store import LocalRawStore
from robin.market_math import (
    DevigInputError,
    DevigMethod,
    devig_execution_metadata,
    devig_probabilities,
    kernel_versions,
)
from robin.providers.api_football import ApiFootballProvider
from robin.storage.database import build_engine
from robin.storage.historical_schema import (
    api_football_coverage,
    backtest_runs,
    dataset_versions,
    historical_backfill_tasks,
    historical_ingestion_runs,
    model_versions,
    strategy_versions,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data" / "historical"
CONTRACT = ROOT / "data" / "contracts" / "api-football-coverage.json"
PROOF = ROOT / "data" / "live-proof" / "jalon5-api-football.json"
DEPENDENCY_REGISTRY = ROOT / "configs" / "historical_dependency_registry_v1.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def required_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} absent; aucune valeur de secret n'est affichée")
    return value


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def completed_rows_this_run(plan: Mapping[str, object]) -> int:
    explicit = int(str(plan.get("normalized_rows_this_run", 0)))
    if explicit:
        return explicit
    completed = int(str(plan.get("completed_this_run", 0)))
    raw_tasks = plan.get("tasks", [])
    task_items = raw_tasks if isinstance(raw_tasks, list) else []
    tasks = [task for task in task_items if isinstance(task, Mapping) and task.get("completed_at")]
    latest = sorted(
        tasks,
        key=lambda task: str(task.get("completed_at", "")),
        reverse=True,
    )[:completed]
    return sum(int(str(task.get("rows_received", 0))) for task in latest)


def parameters_hash(endpoint: str, params: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"endpoint": endpoint, "params": dict(params)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def batched_rows(
    rows: list[dict[str, object]],
    batch_size: int = 1_000,
) -> list[list[dict[str, object]]]:
    if batch_size <= 0:
        raise ValueError("batch_size doit être strictement positif")
    return [rows[offset : offset + batch_size] for offset in range(0, len(rows), batch_size)]


class HistoricalRunner:
    def __init__(
        self,
        *,
        state: Path,
        max_calls: int,
        quota_reserve: int,
        api_key: str,
        run_id: str,
        request_rate: float | None = None,
    ) -> None:
        self.state = state
        self.max_calls = max_calls
        self.quota_reserve = quota_reserve
        self.run_id = run_id
        raw_root = state / "raw"
        self.raw_store = LocalRawStore(
            raw_root,
            backend=GzipPayloadBackend(raw_root / "payloads"),
        )
        self.provider = ApiFootballProvider(
            api_key=api_key,
            raw_store=self.raw_store,
            ingestion_run_id=run_id,
            request_rate_per_second=request_rate,
        )
        self.parquet = PartitionedParquetStore(state / "parquet")
        self.calls = 0
        self.quota_remaining: int | None = None
        self.endpoint_reports: list[dict[str, object]] = []

    def _fetch(self, endpoint: str, params: dict[str, object]) -> Any:
        if self.calls >= self.max_calls:
            raise RuntimeError("MAX_CALLS_REACHED")
        result = self.provider.request(endpoint, params=params)
        self.calls += 1
        if result.quota.remaining is not None:
            self.quota_remaining = result.quota.remaining
        if self.quota_remaining is not None and self.quota_remaining <= self.quota_reserve:
            raise RuntimeError("QUOTA_RESERVE_REACHED")
        return result

    def ingest(
        self,
        endpoint: str,
        params: dict[str, object],
        *,
        competition: str,
        competition_id: int,
        season: int,
        paginated: bool = False,
    ) -> dict[str, object]:
        clean_endpoint = endpoint.strip("/")
        started_calls = self.calls
        raw_payload_hash: str | None = None
        if paginated:
            outcome = iterate_pages(
                endpoint=clean_endpoint,
                parameters_hash=parameters_hash(clean_endpoint, params),
                fetch_page=lambda page: self._fetch(
                    clean_endpoint,
                    {**params, "page": page},
                ),
                checkpoint_path=(
                    self.state
                    / "checkpoints"
                    / competition.replace(" ", "-").lower()
                    / str(season)
                    / f"{clean_endpoint.replace('/', '-')}.json"
                ),
                quota_reserve=self.quota_reserve,
            )
            records = outcome.records
            status = outcome.manifest.status
            pages = len(outcome.manifest.pages)
            page_hashes = sorted(
                evidence.payload_hash
                for evidence in outcome.manifest.pages
                if evidence.payload_hash is not None
            )
            if page_hashes:
                raw_payload_hash = hashlib.sha256(
                    "\n".join(page_hashes).encode("ascii")
                ).hexdigest()
        else:
            result = self._fetch(clean_endpoint, params)
            records = result.records
            status = (
                "COMPLETED" if result.http_status is None or result.http_status < 400 else "FAILED"
            )
            pages = 1
            raw_payload_hash = result.raw_payload_hash
        normalized = normalize_records(
            clean_endpoint,
            records,
            competition_id=competition_id,
            season=season,
            ingestion_run_id=self.run_id,
            raw_payload_hash=raw_payload_hash,
            request_params=params,
        )
        storage = self.parquet.write_records(
            normalized,
            competition=competition,
            season=season,
            entity_type=entity_type_for_endpoint(clean_endpoint),
            dataset_version="api-football-v3",
        )
        report = {
            "endpoint": clean_endpoint,
            "status": status,
            "calls": self.calls - started_calls,
            "pages": pages,
            "rows_received": len(records),
            "normalized_rows": len(normalized),
            "parquet": storage,
            "quota_remaining": self.quota_remaining,
        }
        self.endpoint_reports.append(report)
        return report

    def authenticate(self) -> dict[str, object]:
        requested_at = now_iso()
        result = self._fetch("status", {})
        if result.http_status not in (None, 200) or not result.records:
            raise RuntimeError("API_FOOTBALL_AUTHENTICATION_FAILED")
        proof = {
            "provider": "api-football",
            "endpoint": "status",
            "requested_at": requested_at,
            "received_at": (result.received_at or result.observed_at).isoformat(),
            "http_status": result.http_status or 200,
            "quota_limit": result.quota.limit,
            "quota_remaining": result.quota.remaining,
            "payload_hash": result.raw_payload_hash,
            "ingestion_run_id": self.run_id,
            "raw_payload_location": result.raw_observation_id,
            "normalized_rows": len(result.records),
            "coverage_status": "AVAILABLE",
            "status": "API_FOOTBALL_AUTHENTICATED",
            "secret_exposed": False,
        }
        write_json_atomic(self.state / "proofs" / "authentication.json", proof)
        return proof

    def validate_competitions(self) -> dict[str, int]:
        validated: dict[str, int] = {}
        evidence: list[dict[str, object]] = []
        for target in COMPETITION_TARGETS:
            result = self._fetch(
                "leagues",
                {"search": target.search},
            )
            selected = select_validated_competition(
                result.records,
                expected_name=target.name,
                expected_country=target.country,
            )
            if selected is None:
                evidence.append(
                    {
                        "competition": target.name,
                        "provider_id": None,
                        "status": "FAILED",
                    }
                )
                continue
            provider_id, record = selected
            validated[target.name] = provider_id
            evidence.append(
                {
                    "competition": target.name,
                    "provider_id": provider_id,
                    "status": "VALIDATED_BY_LIVE_RESPONSE",
                    "coverage": record.get("seasons", []),
                }
            )
        write_json_atomic(self.state / "coverage" / "validated-ids.json", evidence)
        return validated


def coverage_contract(validated: dict[str, int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for target in COMPETITION_TARGETS:
        provider_id = validated.get(target.name)
        for season in range(2018, 2026):
            for endpoint in CORE_ENDPOINTS:
                rows.append(
                    {
                        "competition": target.name,
                        "country": target.country,
                        "season": season,
                        "endpoint": endpoint,
                        "provider_competition_id": provider_id,
                        "advertised_coverage": {},
                        "first_test": "NOT_RUN",
                        "rows_received": 0,
                        "pages": 0,
                        "quota_consumed": 0,
                        "raw_bytes": 0,
                        "compressed_bytes": 0,
                        "normalized_bytes": 0,
                        "quality": "NOT_CHECKED",
                        "status": "UNKNOWN",
                        "last_checked_at": now_iso(),
                    }
                )
    return rows


def command_coverage(args: argparse.Namespace) -> None:
    runner = HistoricalRunner(
        state=args.state,
        max_calls=args.max_calls,
        quota_reserve=args.quota_reserve,
        api_key=required_secret("API_FOOTBALL_KEY"),
        run_id=args.run_id,
    )
    authentication = runner.authenticate()
    validated = runner.validate_competitions()
    matrix = coverage_contract(validated)
    write_json_atomic(args.state / "coverage" / "matrix.json", matrix)
    write_json_atomic(CONTRACT, matrix)
    proof = {
        **authentication,
        "status": (
            "API_FOOTBALL_LIVE_PIPELINE_VERIFIED"
            if len(validated) == len(COMPETITION_TARGETS)
            else "API_FOOTBALL_AUTHENTICATED"
        ),
        "validated_competitions": validated,
        "calls": runner.calls,
        "quota_remaining": runner.quota_remaining,
        "source_revision": git_revision(),
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "proofs" / "api-football-live.json", proof)
    write_json_atomic(PROOF, proof)
    print(json.dumps(proof, ensure_ascii=False, sort_keys=True))
    if len(validated) != len(COMPETITION_TARGETS):
        raise RuntimeError("COMPETITION_VALIDATION_FAILED")


def command_contract(_: argparse.Namespace) -> None:
    matrix = coverage_contract({})
    write_json_atomic(CONTRACT, matrix)
    print(
        json.dumps(
            {
                "status": "CONTRACT_CREATED",
                "rows": len(matrix),
                "live_validation": "PENDING",
            },
            sort_keys=True,
        )
    )


def _identifier(record: Mapping[str, Any], wrapper: str) -> int | None:
    value = record.get(wrapper)
    if not isinstance(value, Mapping):
        return None
    provider_id = value.get("id")
    return provider_id if isinstance(provider_id, int) else None


def canonicalize_ligue1_2025(state: Path) -> dict[str, object]:
    formats = read_json(ROOT / "config" / "competition-formats.json", {})
    format_config = formats.get("Ligue 1:2025")
    if not isinstance(format_config, dict):
        raise RuntimeError("COMPETITION_FORMAT_ABSENT")
    competition_format = CompetitionFormat(
        team_count=int(format_config["team_count"]),
        legs=int(format_config.get("legs", 2)),
        phase_prefix=str(format_config.get("phase_prefix", "Regular Season")),
    )
    store = PartitionedParquetStore(state / "parquet")
    fixtures_path = store.partition_path(
        competition="Ligue 1",
        season=2025,
        entity_type="fixtures",
        dataset_version="api-football-v3",
    )
    if not fixtures_path.exists():
        raise RuntimeError("LIGUE1_2025_FIXTURES_ABSENT")
    source_rows = pd.read_parquet(fixtures_path).to_dict(orient="records")
    records: list[dict[str, Any]] = []
    for row in source_rows:
        records.append(
            {
                **{str(key): value for key, value in row.items()},
                "payload": json.loads(str(row["payload"])),
            }
        )
    classified = canonicalize_fixtures(
        records,
        competition_id=61,
        season=2025,
        competition_format=competition_format,
    )
    cardinality = validate_canonical_cardinality(classified, competition_format)
    canonical = [row for row in classified if row["canonical_scope"] == "REGULAR_SEASON_CANONICAL"]
    excluded = [row for row in classified if row["canonical_scope"] != "REGULAR_SEASON_CANONICAL"]
    canonical_storage = PartitionedParquetStore(state / "canonical").write_records(
        canonical,
        competition="Ligue 1",
        season=2025,
        entity_type="fixtures",
        dataset_version="ligue1_2025_regular_season",
    )
    result = {
        "dataset_name": "ligue1_2025_regular_season",
        "status": cardinality["status"],
        "format": {
            **format_config,
            "expected_fixtures": competition_format.expected_fixtures,
        },
        **cardinality,
        "dataset_hash": canonical_dataset_hash(canonical),
        "canonical_storage": canonical_storage,
        "fixtures": classified,
        "excluded_fixtures": excluded,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(state / "audits" / "ligue1-2025-canonicalization.json", result)
    if cardinality["status"] != "PASSED":
        raise RuntimeError("CANONICAL_CARDINALITY_INCOHERENT")
    return result


def command_canonicalize(args: argparse.Namespace) -> None:
    result = canonicalize_ligue1_2025(args.state)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "fixtures"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def build_observed_forecast(state: Path) -> dict[str, object]:
    pilot = read_json(state / "runs" / "pilot-ligue-1-2025.json", {})
    plan = read_json(state / "tasks" / "backfill-plan.json", {})
    started = datetime.fromisoformat(str(pilot["started_at"]).replace("Z", "+00:00"))
    finished = datetime.fromisoformat(str(pilot["finished_at"]).replace("Z", "+00:00"))
    payload_count = len(list((state / "raw" / "payloads").rglob("*.gz")))
    throughput = observed_throughput(
        calls=int(pilot.get("provider_calls", 0)),
        tasks=54,
        fixtures=int(pilot.get("fixtures", 0)),
        rows=int(pilot.get("normalized_rows", 0)),
        elapsed_seconds=(finished - started).total_seconds(),
        compressed_bytes=int(pilot.get("raw_compressed_bytes", 0)),
        payloads=payload_count,
    )
    scheduler_rate = float(plan.get("scheduler", {}).get("request_rate", 0.0))
    effective_seconds_per_call = (
        float(plan.get("seconds_per_call", 0.0))
        or (1.0 / scheduler_rate if scheduler_rate > 0 else 0.0)
        or float(throughput["seconds_per_call"])
    )
    throughput["effective_seconds_per_call"] = effective_seconds_per_call
    throughput["calls_per_minute"] = 60.0 / effective_seconds_per_call
    throughput["calls_per_hour"] = 3600.0 / effective_seconds_per_call
    throughput["recent_calls_per_task"] = (
        float(plan.get("provider_calls", 0)) / max(1, int(plan.get("completed_this_run", 0)))
        if int(plan.get("provider_calls", 0)) > 0
        else float(throughput["calls_per_task"])
    )
    recent_rows = completed_rows_this_run(plan)
    throughput["recent_rows_per_call"] = (
        float(recent_rows) / max(1, int(plan.get("provider_calls", 0)))
        if int(plan.get("provider_calls", 0)) > 0
        else float(throughput["rows_per_call"])
    )
    remaining_by_priority: dict[str, int] = {}
    for task in plan.get("tasks", []):
        if task.get("status") not in {"PENDING", "READY", "RETRYABLE", "SKIPPED_QUOTA"}:
            continue
        priority = str(task.get("priority", "UNKNOWN"))
        remaining_by_priority[priority] = remaining_by_priority.get(priority, 0) + 1
    inventory = storage_inventory(state)
    complete = build_complete_forecast(state, DEPENDENCY_REGISTRY)
    scenarios = complete["scenarios"]
    if not isinstance(scenarios, dict):
        raise RuntimeError("COMPLETE_FORECAST_SCENARIOS_ABSENT")
    base = scenarios["base"]
    if not isinstance(base, dict):
        raise RuntimeError("COMPLETE_FORECAST_BASE_ABSENT")
    daily_calls = int(complete["calls_per_day"])
    total_call_projection = int(complete["calls_remaining_base"])
    uncompressed_file_projection = int(
        total_call_projection * max(float(throughput["payloads_per_task"]) / 25.08, 1) * 2
    )
    compacted_file_projection = max(1, len(plan.get("tasks", [])) // 100) * 3 + 300
    return {
        **complete,
        "observed": throughput,
        "cache_rate": 0.0,
        "unavailable_endpoint_rate": (
            sum(task.get("coverage_status") == "UNAVAILABLE" for task in plan.get("tasks", []))
            / max(1, len(plan.get("tasks", [])))
        ),
        "error_rate": 0.0,
        "calls_per_day": daily_calls,
        "github_actions_hours_per_day": round(
            daily_calls * effective_seconds_per_call / 3600,
            2,
        ),
        "remaining_by_priority": remaining_by_priority,
        "remaining_calls_by_priority": base["calls_by_priority"],
        "eta_priority_a_days": complete["eta_priority_a_base"],
        "eta_priority_b_days": complete["eta_priority_b_base"],
        "eta_full_scope_days": complete["eta_full_base"],
        "estimated_calls_full_scope": total_call_projection,
        "storage_current": inventory,
        "storage_projected_bytes": complete["storage_projected_base"],
        "files_without_compaction": uncompressed_file_projection,
        "files_after_compaction": compacted_file_projection,
        "storage_warning_bytes": 750_000_000,
        "storage_pause_bytes": 900_000_000,
    }


def command_forecast(args: argparse.Namespace) -> None:
    forecast = build_observed_forecast(args.state)
    write_json_atomic(args.state / "forecasts" / "accelerated-safe.json", forecast)
    print(json.dumps(forecast, ensure_ascii=False, sort_keys=True))


def command_pilot(args: argparse.Namespace) -> None:
    summary_path = args.state / "runs" / "pilot-ligue-1-2025.json"
    previous = read_json(summary_path, {})
    if previous.get("status") == "HISTORICAL_PILOT_VERIFIED" and not args.force:
        if any((args.state / "parquet").rglob("*.parquet")):
            canonicalize_ligue1_2025(args.state)
        replay_proof = {
            "status": "PILOT_REPLAY_VERIFIED",
            "run_id": args.run_id,
            "source_run_id": previous.get("run_id"),
            "source_finished_at": previous.get("finished_at"),
            "provider_calls": 0,
            "quota_consumed": 0,
            "business_rows_inserted": 0,
            "duplicates_created": 0,
            "production_status": "PRODUCTION_LOCKED",
        }
        write_json_atomic(args.state / "proofs" / "pilot-replay.json", replay_proof)
        print(json.dumps(replay_proof, ensure_ascii=False, sort_keys=True))
        return
    runner = HistoricalRunner(
        state=args.state,
        max_calls=args.max_calls,
        quota_reserve=args.quota_reserve,
        api_key=required_secret("API_FOOTBALL_KEY"),
        run_id=args.run_id,
    )
    started_at = now_iso()
    auth = runner.authenticate()
    validated = runner.validate_competitions()
    league_id = validated.get("Ligue 1")
    if league_id is None:
        raise RuntimeError("LIGUE_1_ID_NOT_VALIDATED")
    runner.ingest(
        "leagues",
        {"id": league_id, "season": 2025},
        competition="Ligue 1",
        competition_id=league_id,
        season=2025,
    )
    teams_report = runner.ingest(
        "teams",
        {"league": league_id, "season": 2025},
        competition="Ligue 1",
        competition_id=league_id,
        season=2025,
    )
    fixtures_report = runner.ingest(
        "fixtures",
        {"league": league_id, "season": 2025},
        competition="Ligue 1",
        competition_id=league_id,
        season=2025,
    )
    for endpoint, params, paginated in (
        ("standings", {"league": league_id, "season": 2025}, False),
        ("players", {"league": league_id, "season": 2025}, True),
        ("injuries", {"league": league_id, "season": 2025}, True),
    ):
        runner.ingest(
            endpoint,
            params,
            competition="Ligue 1",
            competition_id=league_id,
            season=2025,
            paginated=paginated,
        )

    teams_path = runner.parquet.partition_path(
        competition="Ligue 1",
        season=2025,
        entity_type="teams",
        dataset_version="api-football-v3",
    )
    team_ids: list[int] = []
    if teams_path.exists():
        for payload in pd.read_parquet(teams_path)["payload"].tolist():
            record = json.loads(str(payload))
            provider_id = _identifier(record, "team")
            if provider_id is not None:
                team_ids.append(provider_id)
    fixtures_path = runner.parquet.partition_path(
        competition="Ligue 1",
        season=2025,
        entity_type="fixtures",
        dataset_version="api-football-v3",
    )
    fixture_ids: list[int] = []
    if fixtures_path.exists():
        for payload in pd.read_parquet(fixtures_path)["payload"].tolist():
            record = json.loads(str(payload))
            provider_id = _identifier(record, "fixture")
            if provider_id is not None:
                fixture_ids.append(provider_id)

    stopped_reason: str | None = None
    try:
        for team_id in sorted(set(team_ids)):
            for endpoint, params in (
                ("players/squads", {"team": team_id}),
                (
                    "teams/statistics",
                    {"league": league_id, "season": 2025, "team": team_id},
                ),
                ("coachs", {"team": team_id}),
            ):
                runner.ingest(
                    endpoint,
                    params,
                    competition="Ligue 1",
                    competition_id=league_id,
                    season=2025,
                )
        for fixture_id in sorted(set(fixture_ids)):
            for endpoint in (
                "fixtures/events",
                "fixtures/statistics",
                "fixtures/players",
                "fixtures/lineups",
            ):
                runner.ingest(
                    endpoint,
                    {"fixture": fixture_id},
                    competition="Ligue 1",
                    competition_id=league_id,
                    season=2025,
                )
    except RuntimeError as exc:
        if str(exc) not in {"MAX_CALLS_REACHED", "QUOTA_RESERVE_REACHED"}:
            raise
        stopped_reason = str(exc)

    parquet_failures = runner.parquet.validate()
    raw_bytes = directory_size(args.state / "raw")
    parquet_bytes = directory_size(args.state / "parquet")
    status = (
        "HISTORICAL_PILOT_VERIFIED"
        if stopped_reason is None and not parquet_failures
        else "HISTORICAL_PILOT_ACTIVE"
    )
    summary = {
        "run_id": args.run_id,
        "status": status,
        "provider_status": auth["status"],
        "competition": "Ligue 1",
        "provider_competition_id": league_id,
        "season": 2025,
        "started_at": started_at,
        "finished_at": now_iso(),
        "provider_calls": runner.calls,
        "quota_remaining": runner.quota_remaining,
        "teams": teams_report["rows_received"],
        "fixtures": fixtures_report["rows_received"],
        "endpoints": runner.endpoint_reports,
        "normalized_rows": sum(
            int(report["normalized_rows"]) for report in runner.endpoint_reports
        ),
        "raw_compressed_bytes": raw_bytes,
        "parquet_bytes": parquet_bytes,
        "quality_failures": parquet_failures,
        "stopped_reason": stopped_reason,
        "replay": False,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(summary_path, summary)
    canonicalize_ligue1_2025(args.state)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def command_plan(args: argparse.Namespace) -> None:
    evidence = read_json(args.state / "coverage" / "validated-ids.json", [])
    validated = {
        str(item["competition"]): int(item["provider_id"])
        for item in evidence
        if item.get("provider_id") is not None
    }
    tasks = build_backfill_plan(validated, include_secondary=args.include_secondary)
    pilot = read_json(args.state / "runs" / "pilot-ligue-1-2025.json", {})
    pilot_endpoints = {
        str(report.get("endpoint"))
        for report in pilot.get("endpoints", [])
        if report.get("status") == "COMPLETED"
    }
    if pilot.get("status") == "HISTORICAL_PILOT_VERIFIED":
        for index, task in enumerate(tasks):
            if (
                task.competition_id == validated.get("Ligue 1")
                and task.season == 2025
                and task.endpoint in pilot_endpoints
            ):
                tasks[index] = task.model_copy(
                    update={
                        "status": "COMPLETED",
                        "completed_at": datetime.fromisoformat(
                            str(pilot["finished_at"]).replace("Z", "+00:00")
                        ),
                        "coverage_status": "AVAILABLE",
                    }
                )
    payload = {
        "generated_at": now_iso(),
        "status": "HISTORICAL_BACKFILL_ACTIVE",
        "production_status": "PRODUCTION_LOCKED",
        "tasks": [task.model_dump(mode="json") for task in tasks],
        "remaining_tasks": len(tasks),
        "estimated_calls_lower_bound": sum(task.estimated_calls for task in tasks),
    }
    write_json_atomic(args.state / "tasks" / "backfill-plan.json", payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "tasks"}))


def _partition_ids(
    runner: HistoricalRunner,
    *,
    competition: str,
    season: int,
    entity_type: str,
    wrapper: str,
) -> list[int]:
    path = runner.parquet.partition_path(
        competition=competition,
        season=season,
        entity_type=entity_type,
        dataset_version="api-football-v3",
    )
    if not path.exists():
        return []
    identifiers: list[int] = []
    for payload in pd.read_parquet(path)["payload"].tolist():
        record = json.loads(str(payload))
        provider_id = _identifier(record, wrapper)
        if provider_id is not None:
            identifiers.append(provider_id)
    return sorted(set(identifiers))


def command_backfill(args: argparse.Namespace) -> None:
    plan_path = args.state / "tasks" / "backfill-plan.json"
    plan = read_json(plan_path, {})
    if not plan:
        raise RuntimeError("BACKFILL_PLAN_ABSENT")
    pilot = read_json(args.state / "runs" / "pilot-ligue-1-2025.json", {})
    quota_remaining = plan.get("quota_remaining", pilot.get("quota_remaining"))
    adaptive = accelerated_safe_plan(
        BackfillTelemetry(
            quota_remaining=(int(quota_remaining) if quota_remaining is not None else None),
            quota_reset_at=None,
            reserve=args.quota_reserve,
            mean_calls_per_task=(
                max(
                    1.0,
                    float(plan.get("provider_calls", 0))
                    / max(1, int(plan.get("completed_this_run", 0))),
                )
                if int(plan.get("provider_calls", 0)) > 0
                else 25.08
            ),
            mean_seconds_per_call=(
                max(
                    0.05,
                    float(plan.get("duration_seconds", 0.0))
                    / max(1, int(plan.get("provider_calls", 0))),
                )
                if float(plan.get("duration_seconds", 0.0)) > 0
                else 0.146
            ),
            storage_bytes=directory_size(args.state),
            recent_error_rate=float(plan.get("recent_error_rate", 0.0)),
            recent_429_count=int(plan.get("recent_429_count", 0)),
            temporal_checks_passed=bool(plan.get("temporal_checks_passed", True)),
        )
    )
    if adaptive.stop_reason:
        plan["scheduler"] = {
            **adaptive.__dict__,
            "next_run_at": adaptive.next_run_at.isoformat(),
        }
        plan["stopped_reason"] = adaptive.stop_reason
        write_json_atomic(plan_path, plan)
        raise RuntimeError(adaptive.stop_reason)
    if args.max_calls <= 0:
        args.max_calls = adaptive.max_calls
    if args.max_tasks <= 0:
        args.max_tasks = adaptive.max_tasks
    request_rate = args.request_rate or adaptive.request_rate
    evidence = read_json(args.state / "coverage" / "validated-ids.json", [])
    names_by_id = {
        int(item["provider_id"]): str(item["competition"])
        for item in evidence
        if item.get("provider_id") is not None
    }
    runner = HistoricalRunner(
        state=args.state,
        max_calls=args.max_calls,
        quota_reserve=args.quota_reserve,
        api_key=required_secret("API_FOOTBALL_KEY"),
        run_id=args.run_id,
        request_rate=request_rate,
    )
    tasks: list[dict[str, Any]] = list(plan.get("tasks", []))
    for task in tasks:
        task["business_value_priority"] = business_value_priority(
            competition=names_by_id.get(
                int(task.get("competition_id", 0)),
                "UNKNOWN",
            ),
            season=int(task.get("season", 0)),
            endpoint=str(task.get("endpoint", "")),
        )
    tasks.sort(
        key=lambda task: (
            BUSINESS_PRIORITY_ORDER.get(
                str(task.get("business_value_priority", "P4_DEFERRED")),
                99,
            ),
            str(task.get("priority", "Z")),
            -int(task.get("season", 0)),
            str(task.get("endpoint", "")),
        )
    )
    storage_guard = storage_readiness(args.state)
    deferred_by_storage = 0
    completed = 0
    expanded = 0
    unavailable_this_run = 0
    quarantined_this_run = 0
    normalized_rows_this_run = 0
    stopped_reason: str | None = None
    started_at = now_iso()
    started_monotonic = time.monotonic()
    index = 0
    while index < len(tasks) and completed < args.max_tasks:
        task = tasks[index]
        index += 1
        if task.get("status") not in {
            "PENDING",
            "READY",
            "RETRYABLE",
            "SKIPPED_QUOTA",
        }:
            continue
        if not storage_allows_business_priority(
            str(storage_guard["status"]),
            str(task.get("business_value_priority", "P4_DEFERRED")),
        ):
            deferred_by_storage += 1
            continue
        if time.monotonic() - started_monotonic >= args.max_duration_minutes * 60:
            stopped_reason = "MAX_DURATION_REACHED"
            break
        competition_id = int(task["competition_id"])
        competition = names_by_id.get(competition_id)
        if competition is None:
            task["status"] = "QUARANTINED"
            task["error_code"] = "COMPETITION_ID_NOT_VALIDATED"
            quarantined_this_run += 1
            continue
        season = int(task["season"])
        endpoint = str(task["endpoint"])
        if args.competition and competition.casefold() != args.competition.casefold():
            continue
        if args.season and season != args.season:
            continue
        if args.endpoint and endpoint != args.endpoint.strip("/"):
            continue
        if args.priority and str(task.get("priority")) != args.priority:
            continue
        if (
            args.business_priority
            and str(task.get("business_value_priority")) != args.business_priority
        ):
            continue
        fixture_id = task.get("fixture_id")
        team_id = task.get("team_id")
        if endpoint.startswith("fixtures/") and fixture_id is None:
            fixture_ids = _partition_ids(
                runner,
                competition=competition,
                season=season,
                entity_type="fixtures",
                wrapper="fixture",
            )
            if not fixture_ids:
                task["status"] = "RETRYABLE"
                task["error_code"] = "FIXTURES_REQUIRED"
                continue
            for identifier in fixture_ids:
                tasks.append(
                    {
                        **task,
                        "task_id": stable_task_id(
                            competition_id,
                            season,
                            endpoint,
                            fixture_id=identifier,
                        ),
                        "fixture_id": identifier,
                        "status": "READY",
                        "error_code": None,
                    }
                )
                expanded += 1
            task["status"] = "COMPLETED"
            task["completed_at"] = now_iso()
            continue
        if endpoint in {"players/squads", "teams/statistics", "coachs"} and team_id is None:
            team_ids = _partition_ids(
                runner,
                competition=competition,
                season=season,
                entity_type="teams",
                wrapper="team",
            )
            if not team_ids:
                task["status"] = "RETRYABLE"
                task["error_code"] = "TEAMS_REQUIRED"
                continue
            for identifier in team_ids:
                tasks.append(
                    {
                        **task,
                        "task_id": stable_task_id(
                            competition_id,
                            season,
                            endpoint,
                            team_id=identifier,
                        ),
                        "team_id": identifier,
                        "status": "READY",
                        "error_code": None,
                    }
                )
                expanded += 1
            task["status"] = "COMPLETED"
            task["completed_at"] = now_iso()
            continue
        params: dict[str, object]
        paginated = endpoint in {"players", "injuries"}
        if endpoint == "leagues":
            params = {"id": competition_id, "season": season}
        elif fixture_id is not None:
            params = {"fixture": int(fixture_id)}
        elif team_id is not None:
            params = {"team": int(team_id)}
            if endpoint == "teams/statistics":
                params.update({"league": competition_id, "season": season})
        else:
            params = {"league": competition_id, "season": season}
        task["status"] = "RUNNING"
        task["attempt_count"] = int(task.get("attempt_count", 0)) + 1
        task["last_attempt_at"] = now_iso()
        try:
            report = runner.ingest(
                endpoint,
                params,
                competition=competition,
                competition_id=competition_id,
                season=season,
                paginated=paginated,
            )
        except RuntimeError as exc:
            code = str(exc)
            task["status"] = "SKIPPED_QUOTA" if code == "QUOTA_RESERVE_REACHED" else "RETRYABLE"
            task["error_code"] = code
            stopped_reason = code
            if code in {"MAX_CALLS_REACHED", "QUOTA_RESERVE_REACHED"}:
                break
            continue
        task["rows_received"] = report["rows_received"]
        task["status"] = "COMPLETED" if report["status"] == "COMPLETED" else "PARTIAL"
        task["coverage_status"] = (
            "AVAILABLE" if int(str(report["rows_received"])) > 0 else "UNAVAILABLE"
        )
        if task["coverage_status"] == "UNAVAILABLE":
            unavailable_this_run += 1
        task["completed_at"] = now_iso()
        task["error_code"] = None
        normalized_rows_this_run += int(str(report["normalized_rows"]))
        completed += 1
    unique_tasks = {str(task["task_id"]): task for task in tasks}
    for task in unique_tasks.values():
        task["business_value_priority"] = business_value_priority(
            competition=names_by_id.get(
                int(task.get("competition_id", 0)),
                "UNKNOWN",
            ),
            season=int(task.get("season", 0)),
            endpoint=str(task.get("endpoint", "")),
        )
    tasks = sorted(
        unique_tasks.values(),
        key=lambda task: (
            BUSINESS_PRIORITY_ORDER.get(
                str(task.get("business_value_priority", "P4_DEFERRED")),
                99,
            ),
            str(task.get("priority", "Z")),
            -int(task.get("season", 0)),
            str(task.get("endpoint", "")),
            str(task.get("task_id", "")),
        ),
    )
    remaining = sum(
        1
        for task in tasks
        if task.get("status") in {"PENDING", "READY", "RETRYABLE", "SKIPPED_QUOTA"}
    )
    finished_at = now_iso()
    duration_seconds = time.monotonic() - started_monotonic
    payload = {
        **plan,
        "last_run_started_at": started_at,
        "last_run_at": finished_at,
        "last_run_id": args.run_id,
        "status": "HISTORICAL_BACKFILL_ACTIVE" if remaining else "COMPLETED",
        "tasks": tasks,
        "remaining_tasks": remaining,
        "provider_calls": runner.calls,
        "normalized_rows_this_run": normalized_rows_this_run,
        "duration_seconds": round(duration_seconds, 6),
        "calls_per_task": round(runner.calls / max(completed, 1), 6),
        "seconds_per_call": round(duration_seconds / max(runner.calls, 1), 6),
        "lines_per_call": round(
            normalized_rows_this_run / max(runner.calls, 1),
            6,
        ),
        "completed_this_run": completed,
        "expanded_this_run": expanded,
        "new_latent_tasks_materialized": expanded,
        "remaining_materialized_tasks": remaining,
        "unavailable_this_run": unavailable_this_run,
        "quarantined_this_run": quarantined_this_run,
        "stopped_reason": stopped_reason,
        "storage_guard": storage_guard,
        "deferred_by_storage": deferred_by_storage,
        "quota_remaining": runner.quota_remaining,
        "production_status": "PRODUCTION_LOCKED",
        "scheduler": {
            **adaptive.__dict__,
            "max_calls": args.max_calls,
            "max_tasks": args.max_tasks,
            "request_rate": request_rate,
            "next_run_at": adaptive.next_run_at.isoformat(),
        },
    }
    write_json_atomic(plan_path, payload)
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "tasks"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_compact(args: argparse.Namespace) -> None:
    raw_files = [path for path in (args.state / "raw").rglob("*") if path.is_file()]
    if not raw_files:
        result: dict[str, object] = {
            "status": "NO_RAW_FILES",
            "files": 0,
        }
    else:
        result = HistoricalBundleStore(args.state).create_bundle(
            raw_files,
            run_id=args.run_id,
            competition="multi",
            season=0,
            endpoint="multi",
            remove_sources=args.remove_sources,
        )
        result["status"] = "COMPACTED_AND_VERIFIED"
    write_json_atomic(args.state / "storage" / "latest-compaction.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def command_quality(args: argparse.Namespace) -> None:
    summary = historical_quality_report(args.state)
    write_json_atomic(args.state / "quality" / "latest.json", summary)
    if summary["status"] == "FAILED":
        write_json_atomic(
            args.state / "quality" / "quarantine-latest.json",
            {
                "generated_at": summary["generated_at"],
                "failures": summary["failures"],
                "status": "QUARANTINED",
                "production_status": "PRODUCTION_LOCKED",
            },
        )
        raise RuntimeError("HISTORICAL_DATA_QUALITY_FAILED")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def command_repair_provenance(args: argparse.Namespace) -> None:
    result = repair_raw_hash_provenance(args.state)
    write_json_atomic(args.state / "quality" / "provenance-repair.json", result)
    if result["rows_unresolved"]:
        raise RuntimeError("HISTORICAL_PROVENANCE_REPAIR_INCOMPLETE")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def command_readiness(args: argparse.Namespace) -> None:
    report = build_multiseason_readiness(args.state)
    write_json_atomic(
        args.state / "readiness" / "ligue1-multiseason-v1.json",
        report,
    )
    markdown = readiness_markdown(report)
    report_path = args.state / "reports" / "ligue1-multiseason-readiness.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")
    printable = {
        "status": report["status"],
        "gates": report["gates"],
        "normalized_rows": report["normalized_rows"],
        "provenance_rows": report["provenance_rows"],
        "production_status": "PRODUCTION_LOCKED",
    }
    print(json.dumps(printable, ensure_ascii=False, sort_keys=True))


def command_datasets(args: argparse.Namespace) -> None:
    readiness_path = args.state / "readiness" / "ligue1-multiseason-v1.json"
    readiness = read_json(readiness_path, {})
    if not readiness:
        readiness = build_multiseason_readiness(args.state)
        write_json_atomic(readiness_path, readiness)
    gates = readiness.get("gates", {})
    gate_a = gates.get("A", {}) if isinstance(gates, Mapping) else {}
    gate_b = gates.get("B", {}) if isinstance(gates, Mapping) else {}
    gate_c = gates.get("C", {}) if isinstance(gates, Mapping) else {}
    result: dict[str, object] = {
        "status": "WAITING_FOR_BACKFILL_GATES",
        "datasets": [],
        "production_status": "PRODUCTION_LOCKED",
    }
    if not isinstance(gate_a, Mapping) or not gate_a.get("passed"):
        write_json_atomic(args.state / "datasets" / "jalon6-run.json", result)
        print(json.dumps(result, sort_keys=True))
        return
    seasons = tuple(int(value) for value in gate_a.get("eligible_seasons", []))
    team_rows, market_rows = build_api_team_pre_match(
        args.state,
        seasons=seasons,
        legacy_matches=ROOT / "data" / "matches.parquet",
        devig_method="PROPORTIONAL",
    )
    manifests: list[dict[str, object]] = []
    for name, rows, policy in (
        (
            "api_team_pre_match_v1",
            team_rows,
            "HISTORICAL POINT-IN-TIME",
        ),
        (
            "api_market_baseline_v1",
            market_rows,
            "HISTORICAL_CLOSING_MARKET",
        ),
    ):
        manifest = write_dataset(
            args.state,
            name=name,
            rows=rows,
            code_revision=git_revision(),
            temporal_policy=policy,
        )
        write_json_atomic(args.state / "datasets" / f"{name}.json", manifest)
        manifests.append(manifest)
    if isinstance(gate_b, Mapping) and gate_b.get("passed"):
        player_seasons = tuple(int(value) for value in gate_b.get("eligible_seasons", []))
        facts = player_match_facts(args.state, seasons=player_seasons)
        facts_manifest = write_dataset(
            args.state,
            name="api_player_match_facts_v1",
            rows=facts,
            code_revision=git_revision(),
            temporal_policy="POST_MATCH_ONLY",
        )
        write_json_atomic(
            args.state / "datasets" / "api_player_match_facts_v1.json",
            facts_manifest,
        )
        manifests.append(facts_manifest)
        feature_rows, pre_rows, post_rows = build_player_feature_datasets(
            args.state,
            team_rows=team_rows,
            seasons=player_seasons,
        )
        for name, rows, policy in (
            ("player_feature_store_v1", feature_rows, "PRE_LINEUP"),
            ("api_player_pre_lineup_v1", pre_rows, "PRE_LINEUP"),
        ):
            manifest = write_dataset(
                args.state,
                name=name,
                rows=rows,
                code_revision=git_revision(),
                temporal_policy=policy,
            )
            write_json_atomic(args.state / "datasets" / f"{name}.json", manifest)
            manifests.append(manifest)
        if isinstance(gate_c, Mapping) and gate_c.get("passed"):
            post_manifest = write_dataset(
                args.state,
                name="api_post_lineup_simulated_v1",
                rows=post_rows,
                code_revision=git_revision(),
                temporal_policy="POST_LINEUP_SIMULATED",
            )
            write_json_atomic(
                args.state / "datasets" / "api_post_lineup_simulated_v1.json",
                post_manifest,
            )
            manifests.append(post_manifest)
    result = {
        "status": "DATA_FACTORY_READY",
        "datasets": [
            {
                "name": manifest["dataset_name"],
                "rows": manifest["rows"],
                "fixtures": manifest["fixtures"],
                "sha256": manifest["sha256"],
                "status": manifest["status"],
            }
            for manifest in manifests
        ],
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "datasets" / "jalon6-run.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _dataset_rows(state: Path, dataset_name: str) -> list[dict[str, object]]:
    root = state / "derived"
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.parquet")):
        if f"entity_type={dataset_name}" not in path.as_posix():
            continue
        rows.extend(
            {str(key): value for key, value in record.items() if key != "_record_hash"}
            for record in pd.read_parquet(path).to_dict(orient="records")
        )
    return rows


def command_model_lab(args: argparse.Namespace) -> None:
    dataset_names = (
        "api_team_pre_match_v1",
        "api_player_pre_lineup_v1",
        "api_post_lineup_simulated_v1",
    )
    datasets = {name: _dataset_rows(args.state, name) for name in dataset_names}
    if not datasets["api_team_pre_match_v1"]:
        raise RuntimeError("MODEL_LAB_BLOCKED_GATE_A")
    models, predictions = run_model_lab(
        datasets,
        devig_method="PROPORTIONAL",
    )
    for model in models:
        write_json_atomic(
            args.state / "models" / f"{model['model_version']}.json",
            model,
        )
    store = PartitionedParquetStore(args.state / "derived")
    prediction_partitions: list[dict[str, object]] = []
    for model_version in sorted({str(row["model_version"]) for row in predictions}):
        model_rows = [row for row in predictions if row["model_version"] == model_version]
        for season in sorted({int(row["season"]) for row in model_rows}):
            prediction_partitions.append(
                store.write_records(
                    [row for row in model_rows if int(row["season"]) == season],
                    competition="Ligue-1",
                    season=season,
                    entity_type="api_model_predictions_v1",
                    dataset_version=model_version,
                )
            )
    result = {
        "status": "PLAYER_MODEL_TESTING",
        "models": [
            {
                "model_version": model["model_version"],
                "dataset": model["dataset"],
                "status": model["status"],
                "selected_calibration": model.get("selected_calibration"),
                "oos_metrics": model.get("oos_metrics"),
            }
            for model in models
        ],
        "predictions": len(predictions),
        "partitions": prediction_partitions,
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "models" / "jalon6-run.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def command_strategy_lab(args: argparse.Namespace) -> None:
    predictions = _dataset_rows(args.state, "api_model_predictions_v1")
    if not predictions:
        raise RuntimeError("STRATEGY_LAB_BLOCKED_MODEL_OUTPUT")
    model_versions = sorted({str(row["model_version"]) for row in predictions})
    results: list[dict[str, object]] = []
    for model_version in model_versions:
        results.extend(
            strategy_sensitivity(
                predictions,
                model_version=model_version,
                devig_method="PROPORTIONAL",
            )
        )
    for result in results:
        safe_name = str(result["strategy"]).replace(".", "_")
        write_json_atomic(
            args.state / "backtests" / f"{safe_name}.json",
            result,
        )
        strategy_manifest = {key: value for key, value in result.items() if key != "details"}
        strategy_manifest["strategy_version"] = result["strategy"]
        write_json_atomic(
            args.state / "strategies" / f"{safe_name}.json",
            strategy_manifest,
        )
    summary = {
        "status": "INCONCLUSIVE",
        "strategies_tested": len(results),
        "rejected": sum(result["status"] == "REJECTED" for result in results),
        "inconclusive": sum(result["status"] == "INCONCLUSIVE" for result in results),
        "live_shadow_candidates": 0,
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "strategies" / "jalon6-run.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _market_prediction_rows(
    rows: list[dict[str, object]],
    *,
    devig_method: DevigMethod | str,
) -> list[dict[str, object]]:
    predictions: list[dict[str, object]] = []
    for row in rows:
        label = model_target(row)
        season = int(str(row.get("season", 0)))
        prices = [
            row.get("odds_home"),
            row.get("odds_draw"),
            row.get("odds_away"),
        ]
        if label is None or season not in {2024, 2025}:
            continue
        try:
            devig = devig_probabilities(
                prices,
                method=devig_method,
                outcome_labels=("HOME", "DRAW", "AWAY"),
            )
        except DevigInputError:
            continue
        predictions.append(
            {
                "fixture_id": row["fixture_id"],
                "season": season,
                "kickoff_at": row["kickoff_at"],
                "target": label,
                "model_version": "market_devigged_baseline_v1",
                "dataset_version": "api_market_baseline_v1",
                "probability_home": devig.fair_probabilities[0],
                "probability_draw": devig.fair_probabilities[1],
                "probability_away": devig.fair_probabilities[2],
                "market_snapshot": row.get("market_source", ""),
                "temporal_policy": "PRE_MATCH_CUTOFF",
                "odds_home": row.get("odds_home"),
                "odds_draw": row.get("odds_draw"),
                "odds_away": row.get("odds_away"),
                "origin": "EXPOSED_HISTORICAL_OOS",
                **kernel_versions(devig),
                **devig_execution_metadata(devig),
            }
        )
    return predictions


def _paired_cutoff(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            **row,
            "market_snapshot": str(row.get("market_snapshot", "")),
            "temporal_policy": "PRE_MATCH_CUTOFF",
        }
        for row in rows
    ]


def command_scientific_arena(args: argparse.Namespace) -> None:
    """Run Jalon 7 without provider calls, using only durable restored datasets."""

    state = args.state
    manifests = [read_json(path, {}) for path in sorted((state / "datasets").glob("*.json"))]
    manifests = [item for item in manifests if isinstance(item, Mapping)]
    cache_key = arena_cache_key(manifests, code_revision=git_revision())
    run_path = state / "models" / "jalon7-arena-run.json"
    cached = read_json(run_path, {})
    if cached.get("cache_key") == cache_key:
        printable = dict(cached)
        printable["execution_status"] = "CACHED"
        printable["provider_calls"] = 0
        printable["quota_consumed"] = 0
        print(json.dumps(printable, ensure_ascii=False, sort_keys=True))
        return

    baseline_spec = read_json(ROOT / "configs" / "jalon6-baseline.json", {})
    freeze = freeze_jalon6(
        state,
        source_commit=str(baseline_spec.get("source_commit", git_revision())),
    )
    arena_root = state / "arena"
    write_json_atomic(arena_root / "oos-governance-v1.json", OOS_GOVERNANCE)
    external = external_validation_protocol()
    write_json_atomic(arena_root / "external-validation-protocol-v1.json", external)
    strategy_protocol = strategy_lab_v2_protocol()
    write_json_atomic(arena_root / "strategy-lab-v2-protocol.json", strategy_protocol)
    write_json_atomic(arena_root / "ablation-registry-v1.json", ablation_registry())

    team_rows = _dataset_rows(state, "api_team_pre_match_v1")
    player_rows = _dataset_rows(state, "api_player_pre_lineup_v1")
    post_rows = _dataset_rows(state, "api_post_lineup_simulated_v1")
    if not team_rows:
        raise RuntimeError("SCIENTIFIC_ARENA_BLOCKED_DATASET_GATE_A")

    model_inputs = {
        "team_multinomial_crossfit": temporal_discriminative_predictions(
            team_rows,
            model_family="MULTINOMIAL",
            model_version="team_multinomial_crossfit_v1",
        ),
        "team_hist_gradient_boosting_crossfit": (
            temporal_discriminative_predictions(
                team_rows,
                model_family="HIST_GRADIENT_BOOSTING",
                model_version="team_hist_gradient_boosting_crossfit_v1",
            )
        ),
        "team_without_recent_form_crossfit": (
            temporal_discriminative_predictions(
                team_rows,
                model_family="MULTINOMIAL",
                model_version="team_without_recent_form_crossfit_v1",
                features=tuple(
                    feature
                    for feature in TEAM_FEATURES
                    if "form" not in feature and "goals_" not in feature
                ),
            )
        ),
        "poisson_score": score_model_predictions(team_rows, method="POISSON"),
        "dixon_coles_score": score_model_predictions(team_rows, method="DIXON_COLES"),
        "market_devigged": _market_prediction_rows(
            team_rows,
            devig_method="PROPORTIONAL",
        ),
    }
    if player_rows:
        model_inputs["player_pre_lineup_crossfit"] = temporal_discriminative_predictions(
            player_rows,
            model_family="MULTINOMIAL",
            model_version="player_pre_lineup_crossfit_v1",
            features=(*TEAM_FEATURES, *PLAYER_FEATURES),
        )
    if post_rows:
        model_inputs["post_lineup_audit_crossfit"] = temporal_discriminative_predictions(
            post_rows,
            model_family="MULTINOMIAL",
            model_version="post_lineup_audit_crossfit_v1",
            features=(*TEAM_FEATURES, *PLAYER_FEATURES, *LINEUP_FEATURES),
        )

    calibrated: dict[str, list[dict[str, object]]] = {}
    calibration_audits: dict[str, object] = {}
    for name, rows in model_inputs.items():
        development = [row for row in rows if int(str(row.get("season", 0))) <= 2023]
        evaluation = [row for row in rows if int(str(row.get("season", 0))) >= 2024]
        if name.endswith("_crossfit") and development and evaluation:
            calibrated[name], calibration_audits[name] = apply_selected_calibration(
                development, evaluation
            )
        else:
            calibrated[name] = evaluation or rows
            calibration_audits[name] = {
                "method": "NONE",
                "reason": "FIXED_SCORE_OR_MARKET_BASELINE",
            }

    comparisons: list[dict[str, object]] = []

    def compare(challenger: str, reference: str) -> None:
        left = _paired_cutoff(calibrated.get(challenger, []))
        right = _paired_cutoff(calibrated.get(reference, []))
        try:
            result = paired_model_comparison(
                left,
                right,
                comparison_id=f"{challenger}_VS_{reference}",
            )
        except ValueError as error:
            result = {
                "comparison_id": f"{challenger}_VS_{reference}",
                "status": "REJECTED",
                "reason": str(error),
                "production_status": "PRODUCTION_LOCKED",
            }
        comparisons.append(result)

    compare("team_hist_gradient_boosting_crossfit", "team_multinomial_crossfit")
    compare("team_without_recent_form_crossfit", "team_multinomial_crossfit")
    compare("poisson_score", "market_devigged")
    compare("dixon_coles_score", "poisson_score")
    if "player_pre_lineup_crossfit" in calibrated:
        compare("player_pre_lineup_crossfit", "team_multinomial_crossfit")
    if "post_lineup_audit_crossfit" in calibrated:
        compare("post_lineup_audit_crossfit", "player_pre_lineup_crossfit")

    controls = [deterministic_permutation_control(team_rows)]
    if player_rows:
        controls.append(random_lineup_control(player_rows))
    all_predictions = [row for rows in calibrated.values() for row in rows]
    leaderboard = [
        prediction_leaderboard_row(name, rows)
        for name, rows in sorted(calibrated.items())
    ]
    for row in leaderboard:
        model_name = str(row["model"])
        row["paired_sample"] = max(
            (
                int(str(comparison.get("paired_fixtures", 0)))
                for comparison in comparisons
                if model_name in str(comparison.get("comparison_id", ""))
            ),
            default=0,
        )
    score_models = [
        {
            "model": name,
            "fixtures": len(rows),
            "mean_home_goals": (
                float(
                    sum(float(str(row["home_rate"])) for row in rows)
                    / len(rows)
                )
                if rows
                else None
            ),
            "mean_away_goals": (
                float(
                    sum(float(str(row["away_rate"])) for row in rows)
                    / len(rows)
                )
                if rows
                else None
            ),
            "markets": ["1X2", "OVER_UNDER_2_5", "BTTS", "EXACT_SCORE"],
            "status": "SCORE_MODEL_READY",
        }
        for name, rows in calibrated.items()
        if name in {"poisson_score", "dixon_coles_score"}
    ]
    store = PartitionedParquetStore(state / "derived")
    partitions: list[dict[str, object]] = []
    for model_version in sorted({str(row["model_version"]) for row in all_predictions}):
        model_rows = [row for row in all_predictions if str(row["model_version"]) == model_version]
        for season in sorted({int(str(row["season"])) for row in model_rows}):
            partitions.append(
                store.write_records(
                    [row for row in model_rows if int(str(row["season"])) == season],
                    competition="Ligue-1",
                    season=season,
                    entity_type="scientific_arena_predictions_v1",
                    dataset_version=model_version,
                )
            )
    guard = storage_guard(directory_size(state))
    result: dict[str, object] = {
        "status": "MODEL_ARENA_ACTIVE",
        "model_version": "scientific_model_arena_v1",
        "backtest_version": "scientific_paired_arena_v1",
        "cache_key": cache_key,
        "baseline_status": freeze["status"],
        "baseline_hash": freeze["baseline_hash"],
        "external_protocol": external["protocol_id"],
        "model_families": sorted(calibrated),
        "models_tested": len(calibrated),
        "predictions": len(all_predictions),
        "comparisons": comparisons,
        "leaderboard": leaderboard,
        "score_models": score_models,
        "calibration_audits": calibration_audits,
        "negative_controls": controls,
        "feature_stability": feature_stability_audit(
            team_rows,
            features=TEAM_FEATURES,
        ),
        "ablation_count": len(ablation_registry()),
        "ensemble": validated_ensemble(leaderboard),
        "external_validation": {
            "status": "INCONCLUSIVE",
            "reason": "LOCKED_EXTERNAL_VALIDATION",
            "protocol": external["protocol_id"],
            "results_observed": False,
        },
        "scientific_statuses": {
            "paired_evaluation": "PAIRED_EVALUATION_READY",
            "calibration": "CROSS_FITTED_CALIBRATION_READY",
            "score_models": "SCORE_MODEL_READY",
            "player": "PLAYER_INCREMENTAL_VALUE_INCONCLUSIVE",
            "post_lineup": "POST_LINEUP_NO_INCREMENTAL_VALUE",
        },
        "partitions": partitions,
        "storage": guard,
        "live_candidates": 0,
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
        "run_hash": stable_hash(
            {
                "cache_key": cache_key,
                "comparisons": comparisons,
                "controls": controls,
            }
        ),
    }
    write_json_atomic(run_path, result)
    write_json_atomic(state / "backtests" / "jalon7-paired-comparisons.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def command_strategy_lab_v2(args: argparse.Namespace) -> None:
    predictions = _dataset_rows(args.state, "scientific_arena_predictions_v1")
    if not predictions:
        raise RuntimeError("STRATEGY_LAB_V2_BLOCKED_ARENA_OUTPUT")
    protocol = strategy_lab_v2_protocol()
    results: list[dict[str, object]] = []
    for model_version in sorted({str(row.get("model_version", "")) for row in predictions}):
        model_rows = [
            {**row, "origin": "OOS HISTORICAL"}
            for row in predictions
            if str(row.get("model_version", "")) == model_version
        ]
        if any(row.get("odds_home") for row in model_rows):
            results.extend(
                strategy_sensitivity(
                    model_rows,
                    model_version=model_version,
                    devig_method="PROPORTIONAL",
                    edges=(0.03, 0.05, 0.07),
                )
            )
        over_under_rows = [
            row
            for row in model_rows
            if str(row.get("target_over_25")) in {"0", "1", "0.0", "1.0"}
            and row.get("probability_over_25") is not None
            and row.get("odds_over_25") is not None
            and row.get("odds_under_25") is not None
        ]
        if over_under_rows:
            for edge in (0.03, 0.05, 0.07):
                results.append(
                    run_backtest(
                        over_under_rows,
                        StrategyParameters(
                            name=(
                                f"{model_version}_over_under_2_5_edge_{edge:.2f}"
                            ),
                            market="OVER_UNDER_2_5",
                            minimum_edge=edge,
                        ),
                        devig_method="PROPORTIONAL",
                        hypotheses_tested=3,
                    )
                )
    summary = {
        "status": "INCONCLUSIVE",
        "strategy_version": "strategy_lab_v2_protocol",
        "backtest_version": "strategy_lab_v2_exposed_oos_v1",
        "protocol": protocol["protocol_id"],
        "protocol_hash": protocol["protocol_hash"],
        "strategies_tested": len(results),
        "evaluation_segment": "EXPOSED_HISTORICAL_OOS",
        "promoted": 0,
        "markets_without_usable_prices": ["BTTS"],
        "live_shadow_candidates": 0,
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "strategies" / "jalon7-run.json", summary)
    write_json_atomic(args.state / "backtests" / "jalon7-strategy-lab-v2.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def command_features(args: argparse.Namespace) -> None:
    canonical_audit = read_json(
        args.state / "audits" / "ligue1-2025-canonicalization.json",
        {},
    )
    if canonical_audit and canonical_audit.get("status") != "PASSED":
        raise RuntimeError("FEATURE_FACTORY_BLOCKED_CANONICAL_CARDINALITY")
    frame = pd.read_parquet(ROOT / "data" / "matches.parquet")
    records = frame.to_dict(orient="records")
    rows = build_team_feature_rows(records)
    assert_temporal_integrity(rows)
    manifest = dataset_manifest(
        rows,
        name="team_baseline_v1",
        code_version=git_revision(),
    )
    store = PartitionedParquetStore(args.state / "derived")
    partitions: list[dict[str, object]] = []
    for season in sorted({int(row["season"]) for row in rows}):
        season_rows = [row for row in rows if int(row["season"]) == season]
        partitions.append(
            store.write_records(
                season_rows,
                competition="legacy-multi-league",
                season=season,
                entity_type="team_features",
                dataset_version="team_baseline_v1",
            )
        )
    manifest["partitions"] = partitions
    manifest["status"] = "FEATURE_FACTORY_ACTIVE"
    write_json_atomic(args.state / "datasets" / "team_baseline_v1.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


def _derived_rows(state: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in (state / "derived").rglob("*.parquet"):
        for record in pd.read_parquet(path).to_dict(orient="records"):
            rows.append({str(key): value for key, value in record.items()})
    return rows


def command_train(args: argparse.Namespace) -> None:
    dataset = read_json(args.state / "datasets" / "team_baseline_v1.json", {})
    if not dataset:
        raise RuntimeError("DATASET_TEAM_BASELINE_ABSENT")
    model = train_elo_baseline(
        _derived_rows(args.state),
        dataset_hash=str(dataset["sha256"]),
    )
    write_json_atomic(args.state / "models" / "elo_v1.json", model)
    print(json.dumps(model, ensure_ascii=False, sort_keys=True))


def command_backtest(args: argparse.Namespace) -> None:
    model = read_json(args.state / "models" / "elo_v1.json", {})
    if not model:
        raise RuntimeError("MODEL_ELO_V1_ABSENT")
    result = backtest_fixed_stake(_derived_rows(args.state))
    write_json_atomic(
        args.state / "backtests" / "elo_edge_5pct_oos.json",
        result,
    )
    printable = {key: value for key, value in result.items() if key != "details"}
    print(json.dumps(printable, ensure_ascii=False, sort_keys=True))


def command_persist(args: argparse.Namespace) -> None:
    database_url = required_secret("DATABASE_URL")
    engine = build_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "api_football_coverage",
        "historical_ingestion_runs",
        "historical_backfill_tasks",
        "dataset_versions",
        "model_versions",
        "backtest_runs",
        "strategy_versions",
    }
    missing = sorted(expected - tables)
    if missing:
        raise RuntimeError(f"tables historiques absentes: {','.join(missing)}")
    inserted = 0
    updated = 0

    def upsert(
        connection: Any,
        table: Any,
        key_column: Any,
        key_value: object,
        values: dict[str, object],
    ) -> None:
        nonlocal inserted, updated
        existing = connection.execute(
            select(key_column).where(key_column == key_value)
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(insert(table).values(**values))
            inserted += 1
        else:
            connection.execute(update(table).where(key_column == key_value).values(**values))
            updated += 1

    def bulk_upsert(
        connection: Any,
        table: Any,
        key_column: Any,
        rows: list[dict[str, object]],
    ) -> None:
        nonlocal inserted, updated
        if not rows:
            return
        # Psycopg refuse une requête dépassant 65 535 paramètres. Un lot de
        # 1 000 lignes reste borné même pour les tables historiques larges.
        for batch in batched_rows(rows):
            keys = [row[key_column.name] for row in batch]
            existing = set(
                connection.execute(select(key_column).where(key_column.in_(keys))).scalars()
            )
            updated += len(existing)
            inserted += len(batch) - len(existing)
            if connection.dialect.name == "postgresql":
                statement: Any = postgresql_insert(table).values(batch)
            elif connection.dialect.name == "sqlite":
                statement = sqlite_insert(table).values(batch)
            else:
                for row in batch:
                    upsert(
                        connection,
                        table,
                        key_column,
                        row[key_column.name],
                        row,
                    )
                continue
            replacement = {
                column.name: getattr(statement.excluded, column.name)
                for column in table.c
                if column.name != key_column.name
            }
            connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[key_column.name],
                    set_=replacement,
                )
            )

    with engine.begin() as connection:
        matrix = read_json(args.state / "coverage" / "matrix.json", [])
        coverage_rows: list[dict[str, object]] = []
        for row in matrix:
            scope = f"{row['competition']}:{row['season']}:{row['endpoint']}"
            row_id = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:36]
            values = {
                "id": row_id,
                "competition_name": row["competition"],
                "provider_competition_id": row.get("provider_competition_id"),
                "season": int(row["season"]),
                "endpoint": row["endpoint"],
                "coverage_status": row["status"],
                "advertised_coverage": row.get("advertised_coverage", {}),
                "rows_received": int(row.get("rows_received", 0)),
                "pages": int(row.get("pages", 0)),
                "quota_consumed": int(row.get("quota_consumed", 0)),
                "raw_bytes": int(row.get("raw_bytes", 0)),
                "compressed_bytes": int(row.get("compressed_bytes", 0)),
                "normalized_bytes": int(row.get("normalized_bytes", 0)),
                "last_checked_at": datetime.fromisoformat(
                    str(row["last_checked_at"]).replace("Z", "+00:00")
                ),
            }
            coverage_rows.append(values)
        bulk_upsert(
            connection,
            api_football_coverage,
            api_football_coverage.c.id,
            coverage_rows,
        )

        pilot = read_json(args.state / "runs" / "pilot-ligue-1-2025.json", {})
        if pilot:
            run_id = str(pilot["run_id"])[:120]
            run_values = {
                "id": run_id,
                "idempotency_key": "pilot:ligue-1:2025",
                "mode": "PILOT",
                "status": pilot["status"],
                "started_at": datetime.fromisoformat(
                    str(pilot["started_at"]).replace("Z", "+00:00")
                ),
                "finished_at": datetime.fromisoformat(
                    str(pilot["finished_at"]).replace("Z", "+00:00")
                ),
                "calls": int(pilot["provider_calls"]),
                "rows_received": int(pilot["normalized_rows"]),
                "quota_remaining": pilot.get("quota_remaining"),
                "manifest_location": "historical/runs/pilot-ligue-1-2025.json",
                "error_code": pilot.get("stopped_reason"),
            }
            upsert(
                connection,
                historical_ingestion_runs,
                historical_ingestion_runs.c.idempotency_key,
                "pilot:ligue-1:2025",
                run_values,
            )

        plan = read_json(args.state / "tasks" / "backfill-plan.json", {})
        last_run_id = str(plan.get("last_run_id", ""))
        if last_run_id:
            finished_at = datetime.fromisoformat(str(plan["last_run_at"]).replace("Z", "+00:00"))
            started_at = datetime.fromisoformat(
                str(plan.get("last_run_started_at", plan["last_run_at"])).replace(
                    "Z",
                    "+00:00",
                )
            )
            backfill_key = f"backfill:{last_run_id}"
            backfill_values = {
                "id": last_run_id[:120],
                "idempotency_key": backfill_key,
                "mode": str(plan.get("scheduler", {}).get("mode", "ACCELERATED_SAFE")),
                "status": str(plan.get("status", "HISTORICAL_BACKFILL_ACTIVE")),
                "started_at": started_at,
                "finished_at": finished_at,
                "calls": int(plan.get("provider_calls", 0)),
                "rows_received": completed_rows_this_run(plan),
                "quota_remaining": plan.get("quota_remaining"),
                "manifest_location": "historical/tasks/backfill-plan.json",
                "error_code": plan.get("stopped_reason"),
            }
            upsert(
                connection,
                historical_ingestion_runs,
                historical_ingestion_runs.c.idempotency_key,
                backfill_key,
                backfill_values,
            )
        task_rows: list[dict[str, object]] = []
        for task in plan.get("tasks", []):
            task_values = {
                **task,
                "last_attempt_at": (
                    datetime.fromisoformat(task["last_attempt_at"])
                    if task.get("last_attempt_at")
                    else None
                ),
                "next_retry_at": (
                    datetime.fromisoformat(task["next_retry_at"])
                    if task.get("next_retry_at")
                    else None
                ),
                "completed_at": (
                    datetime.fromisoformat(task["completed_at"])
                    if task.get("completed_at")
                    else None
                ),
            }
            task_rows.append(task_values)
        bulk_upsert(
            connection,
            historical_backfill_tasks,
            historical_backfill_tasks.c.task_id,
            task_rows,
        )

        registry_sources = (
            (
                sorted((args.state / "datasets").glob("*.json")),
                dataset_versions,
                "dataset_version",
            ),
            (
                sorted((args.state / "models").glob("*.json")),
                model_versions,
                "model_version",
            ),
            (
                sorted((args.state / "backtests").glob("*.json")),
                backtest_runs,
                "backtest_version",
            ),
            (
                sorted((args.state / "strategies").glob("*.json")),
                strategy_versions,
                "strategy_version",
            ),
        )
        for paths, table, version_key in registry_sources:
            for path in paths:
                manifest = read_json(path, {})
                version_value = manifest.get(version_key)
                if not manifest or not version_value:
                    continue
                version = str(version_value)
                artifact_hash = str(
                    manifest.get("sha256")
                    or manifest.get("artifact_hash")
                    or hashlib.sha256(
                        json.dumps(
                            manifest,
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()
                )
                row_id = hashlib.sha256(f"{table.name}:{version}".encode()).hexdigest()[:36]
                values = {
                    "id": row_id,
                    "version": version,
                    "status": str(manifest.get("status", "RECORDED")),
                    "manifest": manifest,
                    "artifact_hash": artifact_hash,
                    "created_at": datetime.now(UTC),
                }
                upsert(connection, table, table.c.version, version, values)

        table_counts = {
            table.name: int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
            for table in (
                api_football_coverage,
                historical_ingestion_runs,
                historical_backfill_tasks,
                dataset_versions,
                model_versions,
                backtest_runs,
                strategy_versions,
            )
        }
    result = {
        "status": "POSTGRESQL_CONNECTED",
        "migration_revision": "0005_jalon9_critical_closure",
        "tables_verified": len(expected),
        "rows_inserted": inserted,
        "rows_updated": updated,
        "table_counts": table_counts,
        "secret_exposed": False,
    }
    write_json_atomic(args.state / "proofs" / "postgresql.json", result)
    print(json.dumps(result, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--run-id", default=f"local-{uuid4()}")
    parser.add_argument("--max-calls", type=int, default=1500)
    parser.add_argument("--quota-reserve", type=int, default=5_000)
    parser.add_argument("--request-rate", type=float, default=0.0)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("coverage")
    subparsers.add_parser("contract")
    pilot = subparsers.add_parser("pilot")
    pilot.add_argument("--force", action="store_true")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--include-secondary", action="store_true")
    backfill = subparsers.add_parser("backfill")
    backfill.add_argument("--max-tasks", type=int, default=25)
    backfill.add_argument("--max-duration-minutes", type=int, default=110)
    backfill.add_argument("--competition", default="")
    backfill.add_argument("--season", type=int)
    backfill.add_argument("--endpoint", default="")
    backfill.add_argument("--priority", default="")
    backfill.add_argument("--business-priority", default="")
    compact = subparsers.add_parser("compact")
    compact.add_argument("--remove-sources", action="store_true")
    subparsers.add_parser("canonicalize")
    subparsers.add_parser("forecast")
    subparsers.add_parser("quality")
    subparsers.add_parser("repair-provenance")
    subparsers.add_parser("readiness")
    subparsers.add_parser("datasets")
    subparsers.add_parser("model-lab")
    subparsers.add_parser("strategy-lab")
    subparsers.add_parser("scientific-arena")
    subparsers.add_parser("strategy-lab-v2")
    subparsers.add_parser("features")
    subparsers.add_parser("train")
    subparsers.add_parser("backtest")
    subparsers.add_parser("persist")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.state = args.state.resolve()
    args.state.mkdir(parents=True, exist_ok=True)
    commands = {
        "coverage": command_coverage,
        "contract": command_contract,
        "pilot": command_pilot,
        "plan": command_plan,
        "backfill": command_backfill,
        "canonicalize": command_canonicalize,
        "compact": command_compact,
        "forecast": command_forecast,
        "quality": command_quality,
        "repair-provenance": command_repair_provenance,
        "readiness": command_readiness,
        "datasets": command_datasets,
        "model-lab": command_model_lab,
        "strategy-lab": command_strategy_lab,
        "scientific-arena": command_scientific_arena,
        "strategy-lab-v2": command_strategy_lab_v2,
        "features": command_features,
        "train": command_train,
        "backtest": command_backtest,
        "persist": command_persist,
    }
    if args.max_calls > 0:
        decision = quota_decision(
            None,
            requested_calls=args.max_calls,
            reserve=args.quota_reserve,
            accelerated=True,
        )
        if decision.callable_budget == 0:
            raise RuntimeError("QUOTA_PAUSED")
    commands[args.command](args)


if __name__ == "__main__":
    main()
