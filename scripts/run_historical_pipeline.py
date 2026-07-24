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
from sqlalchemy import insert, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from robin.historical.features import (
    assert_temporal_integrity,
    build_team_feature_rows,
    dataset_manifest,
)
from robin.historical.modeling import backtest_fixed_stake, train_elo_baseline
from robin.historical.normalization import entity_type_for_endpoint, normalize_records
from robin.historical.orchestrator import (
    COMPETITION_TARGETS,
    CORE_ENDPOINTS,
    build_backfill_plan,
    quota_decision,
    select_validated_competition,
    stable_task_id,
)
from robin.historical.pagination import iterate_pages
from robin.historical.storage import (
    GzipPayloadBackend,
    PartitionedParquetStore,
    directory_size,
    write_json_atomic,
)
from robin.ingestion.raw_store import LocalRawStore
from robin.providers.api_football import ApiFootballProvider
from robin.storage.database import build_engine
from robin.storage.historical_schema import (
    api_football_coverage,
    backtest_runs,
    dataset_versions,
    historical_backfill_tasks,
    historical_ingestion_runs,
    model_versions,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data" / "historical"
CONTRACT = ROOT / "data" / "contracts" / "api-football-coverage.json"
PROOF = ROOT / "data" / "live-proof" / "jalon5-api-football.json"


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
    return [
        rows[offset : offset + batch_size]
        for offset in range(0, len(rows), batch_size)
    ]


class HistoricalRunner:
    def __init__(
        self,
        *,
        state: Path,
        max_calls: int,
        quota_reserve: int,
        api_key: str,
        run_id: str,
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
        if (
            self.quota_remaining is not None
            and self.quota_remaining <= self.quota_reserve
        ):
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
        else:
            result = self._fetch(clean_endpoint, params)
            records = result.records
            status = (
                "COMPLETED"
                if result.http_status is None or result.http_status < 400
                else "FAILED"
            )
            pages = 1
        normalized = normalize_records(
            clean_endpoint,
            records,
            competition_id=competition_id,
            season=season,
            ingestion_run_id=self.run_id,
            raw_payload_hash=None,
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


def command_pilot(args: argparse.Namespace) -> None:
    summary_path = args.state / "runs" / "pilot-ligue-1-2025.json"
    previous = read_json(summary_path, {})
    if previous.get("status") == "HISTORICAL_PILOT_VERIFIED" and not args.force:
        print(
            json.dumps(
                {**previous, "replay": True, "provider_calls": 0},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
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
        ("injuries", {"league": league_id, "season": 2025}, False),
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
    )
    tasks: list[dict[str, Any]] = list(plan.get("tasks", []))
    completed = 0
    expanded = 0
    stopped_reason: str | None = None
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
        if time.monotonic() - started_monotonic >= args.max_duration_minutes * 60:
            stopped_reason = "MAX_DURATION_REACHED"
            break
        competition_id = int(task["competition_id"])
        competition = names_by_id.get(competition_id)
        if competition is None:
            task["status"] = "QUARANTINED"
            task["error_code"] = "COMPETITION_ID_NOT_VALIDATED"
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
        paginated = endpoint == "players"
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
            task["status"] = (
                "SKIPPED_QUOTA"
                if code == "QUOTA_RESERVE_REACHED"
                else "RETRYABLE"
            )
            task["error_code"] = code
            stopped_reason = code
            if code in {"MAX_CALLS_REACHED", "QUOTA_RESERVE_REACHED"}:
                break
            continue
        task["rows_received"] = report["rows_received"]
        task["status"] = (
            "COMPLETED" if report["status"] == "COMPLETED" else "PARTIAL"
        )
        task["coverage_status"] = (
            "AVAILABLE" if int(report["rows_received"]) > 0 else "UNAVAILABLE"
        )
        task["completed_at"] = now_iso()
        task["error_code"] = None
        completed += 1
    unique_tasks = {str(task["task_id"]): task for task in tasks}
    tasks = sorted(
        unique_tasks.values(),
        key=lambda task: (
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
    payload = {
        **plan,
        "last_run_at": now_iso(),
        "last_run_id": args.run_id,
        "status": "HISTORICAL_BACKFILL_ACTIVE" if remaining else "COMPLETED",
        "tasks": tasks,
        "remaining_tasks": remaining,
        "provider_calls": runner.calls,
        "completed_this_run": completed,
        "expanded_this_run": expanded,
        "stopped_reason": stopped_reason,
        "quota_remaining": runner.quota_remaining,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(plan_path, payload)
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "tasks"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def command_quality(args: argparse.Namespace) -> None:
    store = PartitionedParquetStore(args.state / "parquet")
    failures = store.validate()
    summary = {
        "generated_at": now_iso(),
        "status": "FAILED" if failures else "PASSED",
        "parquet_partitions": len(list((args.state / "parquet").rglob("*.parquet"))),
        "raw_observations": len(list((args.state / "raw").rglob("*.json"))),
        "failures": failures,
        "production_status": "PRODUCTION_LOCKED",
    }
    write_json_atomic(args.state / "quality" / "latest.json", summary)
    if failures:
        raise RuntimeError("HISTORICAL_DATA_QUALITY_FAILED")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def command_features(args: argparse.Namespace) -> None:
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
            connection.execute(
                update(table).where(key_column == key_value).values(**values)
            )
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
                connection.execute(
                    select(key_column).where(key_column.in_(keys))
                ).scalars()
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
            scope = (
                f"{row['competition']}:{row['season']}:{row['endpoint']}"
            )
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

        for path, table in (
            (args.state / "datasets" / "team_baseline_v1.json", dataset_versions),
            (args.state / "models" / "elo_v1.json", model_versions),
            (args.state / "backtests" / "elo_edge_5pct_oos.json", backtest_runs),
        ):
            manifest = read_json(path, {})
            if not manifest:
                continue
            version = str(
                manifest.get("dataset_version")
                or manifest.get("model_version")
                or manifest.get("backtest_version")
            )
            artifact_hash = str(
                manifest.get("sha256")
                or manifest.get("artifact_hash")
                or hashlib.sha256(
                    json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
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
                connection.execute(select(table.c.id)).all().__len__()
            )
            for table in (
                api_football_coverage,
                historical_ingestion_runs,
                historical_backfill_tasks,
                dataset_versions,
                model_versions,
                backtest_runs,
            )
        }
    result = {
        "status": "POSTGRESQL_CONNECTED",
        "migration_revision": "0004_jalon5_deep_data_factory",
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
    parser.add_argument("--quota-reserve", type=int, default=100)
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
    subparsers.add_parser("quality")
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
        "quality": command_quality,
        "features": command_features,
        "train": command_train,
        "backtest": command_backtest,
        "persist": command_persist,
    }
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
