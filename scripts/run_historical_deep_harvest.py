"""Production glue for Historical Deep Data Harvest workflows 70--78.

Raw provider responses are committed through :class:`R2FirstRepository` before
the runner acknowledges work.  Replay, quality, features, backtest, and report
commands never construct a provider client.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import inspect
import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from robin.historical_deep.adapters import (
    DirectoryObjectStore,
    R2ObjectStore,
    assert_safety_locks,
    build_object_store,
    validate_r2_round_trip,
)
from robin.historical_deep.backtest import run_cache_only_backtest
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import (
    CampaignContract,
    CompetitionSpec,
    HarvestTask,
    ProviderStatus,
    QuotaBudget,
    TemporalClass,
    canonical_json_bytes,
    load_campaign_contract,
)
from robin.historical_deep.features import build_historical_feature_bundle
from robin.historical_deep.gates import evaluate_gate_registry, gate_summary
from robin.historical_deep.genome import build_genome_availability_projection
from robin.historical_deep.provider import (
    ApiFootballDeepClient,
    ProviderAuthenticationError,
    ProviderError,
    ProviderStatusError,
)
from robin.historical_deep.quality import (
    DATASET_NAMES,
    build_dataset_manifests,
    compare_quality_v2,
    coverage_snapshot_v2,
    separate_temporal_datasets,
)
from robin.historical_deep.quota import (
    QuotaController,
    QuotaExhaustedError,
)
from robin.historical_deep.replay import (
    canonical_sha256,
    replay_stream_cache_only,
)
from robin.historical_deep.reporting import (
    build_historical_deep_report,
    render_report_json,
    render_report_markdown,
)
from robin.historical_deep.runtime import (
    DERIVED_NAMESPACE,
    DurableRuntimeLedger,
    compact_artifact,
    read_objects_bounded,
    write_artifact,
)
from robin.historical_deep.segmented_replay import load_staging_projection_rows
from robin.historical_deep.storage import (
    PayloadIntegrityError,
    R2FirstRepository,
)

COLLECTION_COMMANDS = frozenset({"census", "fixtures", "players", "injuries"})
ANALYSIS_COMMANDS = frozenset({"replay", "quality", "features", "backtest", "report"})
ALL_COMMANDS = tuple(sorted(COLLECTION_COMMANDS | ANALYSIS_COMMANDS))
GLOBAL_MISSION_MAX_MINUTES = 720
JOB_MAX_DURATION_MINUTES = 100
CHECKPOINT_MAX_CALLS = 250
CHECKPOINT_MAX_MINUTES = 5
QUALITY_DATASET_PART_MAX_ROWS = 2_500
QUALITY_DATASET_COMPRESSION_LEVEL = 1
COLLECTOR_VERSION = "historical-deep-collector-v1"
SENTINEL_KEY = (
    "historical-deep-data/schema-v1/_control/"
    "historical-deep-runner-sentinel-v1.json"
)

ObjectStoreType = R2ObjectStore | DirectoryObjectStore


class ProviderClient(Protocol):
    @property
    def quota(self) -> object | None: ...

    def get_status(self) -> ProviderStatus: ...

    def get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> object: ...


class RunnerBlocked(RuntimeError):
    """A bounded run stopped safely and can be resumed."""


class ProviderFactory(Protocol):
    def __call__(self, api_key: str) -> ProviderClient: ...


class StoreFactory(Protocol):
    def __call__(
        self,
        environment: Mapping[str, str],
        cache_root: Path | None,
    ) -> ObjectStoreType: ...


@dataclass(frozen=True, slots=True)
class RunnerServices:
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    provider_factory: ProviderFactory
    store_factory: StoreFactory


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _provider_factory(api_key: str) -> ProviderClient:
    return cast(
        ProviderClient,
        ApiFootballDeepClient(
            api_key=api_key,
            status_ttl_seconds=(JOB_MAX_DURATION_MINUTES + 10) * 60,
        ),
    )


def _store_factory(
    environment: Mapping[str, str],
    cache_root: Path | None,
) -> ObjectStoreType:
    return build_object_store(environment, cache_root=cache_root)


DEFAULT_SERVICES = RunnerServices(
    now=_utc_now,
    monotonic=time.monotonic,
    provider_factory=_provider_factory,
    store_factory=_store_factory,
)


def _plain(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RUNNER_DATETIME_MUST_BE_TIMEZONE_AWARE")
        return value.astimezone(UTC).isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(mode="json"))
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        return _plain(as_dict())
    return repr(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}_INVALID")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}_INVALID") from exc
    return result


def _aware_now(services: RunnerServices) -> datetime:
    value = services.now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RUNNER_NOW_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _run_token(
    environment: Mapping[str, str],
    *,
    code_revision: str,
) -> str:
    explicit = environment.get("HISTORICAL_DEEP_RUN_TOKEN", "").strip()
    if explicit:
        return explicit
    run_id = environment.get("GITHUB_RUN_ID", "").strip()
    run_attempt = environment.get("GITHUB_RUN_ATTEMPT", "").strip()
    if bool(run_id) != bool(run_attempt):
        raise ValueError("RUNNER_GITHUB_RUN_TOKEN_INCOMPLETE")
    if run_id and run_attempt:
        return f"{run_id}:{run_attempt}"
    return f"LOCAL:{code_revision}"


def _construct_with_supported_kwargs(
    constructor: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> object:
    parameters = inspect.signature(constructor).parameters
    accepted = {key: value for key, value in kwargs.items() if key in parameters}
    return constructor(*args, **accepted)


def _invoke_with_supported_kwargs(
    function: Callable[..., object],
    **kwargs: object,
) -> object:
    parameters = inspect.signature(function).parameters
    accepted = {key: value for key, value in kwargs.items() if key in parameters}
    return function(**accepted)


@dataclass(slots=True)
class ExecutionLimits:
    phase: str
    ledger: DurableRuntimeLedger
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    job_started_at: datetime
    mission_started_at: datetime
    maximum_calls: int
    maximum_minutes: int
    mission_maximum_minutes: int
    checkpoint_calls: int
    checkpoint_minutes: int
    provider_calls: int = 1
    tasks_completed: int = 0
    mission_calls_used: int = 1
    mission_call_cap: int = 100_000
    reservation_chunk_calls: int = CHECKPOINT_MAX_CALLS
    code_revision: str = "UNSPECIFIED"
    run_token: str = "LOCAL:UNSPECIFIED"
    usage_category: str = "mission/usage"
    _job_started_monotonic: float = field(init=False)
    _last_checkpoint_monotonic: float = field(init=False)
    _last_checkpoint_calls: int = field(init=False)
    _mission_reservation_remaining: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        if not 1 <= self.reservation_chunk_calls <= CHECKPOINT_MAX_CALLS:
            raise ValueError("RUNNER_MISSION_RESERVATION_CHUNK_INVALID")
        self._job_started_monotonic = self.monotonic()
        self._last_checkpoint_monotonic = self._job_started_monotonic
        self._last_checkpoint_calls = self.provider_calls

    def _current_time(self) -> datetime:
        value = self.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RUNNER_LIMIT_CLOCK_MUST_BE_TIMEZONE_AWARE")
        return value.astimezone(UTC)

    def current_time(self) -> datetime:
        return self._current_time()

    def assert_time(self) -> None:
        if self.monotonic() - self._job_started_monotonic >= self.maximum_minutes * 60:
            raise RunnerBlocked("JOB_DURATION_LIMIT_REACHED")
        if not self.ledger.mission_has_time(
            now=self._current_time(),
            started_at=self.mission_started_at,
            maximum_minutes=self.mission_maximum_minutes,
        ):
            raise RunnerBlocked("GLOBAL_MISSION_720_MINUTES_REACHED")

    def before_provider_attempt(self) -> None:
        self.assert_time()
        if self.provider_calls >= self.maximum_calls:
            raise RunnerBlocked("JOB_PROVIDER_CALL_LIMIT_REACHED")
        if self._mission_reservation_remaining == 0:
            job_remaining = self.maximum_calls - self.provider_calls
            mission_remaining = self.mission_call_cap - self.mission_calls_used
            reservation = min(
                self.reservation_chunk_calls,
                self.checkpoint_calls,
                job_remaining,
                mission_remaining,
            )
            if reservation < 1:
                raise RunnerBlocked("GLOBAL_MISSION_CALL_CAP_REACHED")
            # Persist a conservative high-water mark before transport. A crash can
            # therefore over-count at most one bounded chunk, never under-count
            # provider attempts or permit the global 90k ceiling to be crossed.
            self.mission_calls_used += reservation
            self._mission_reservation_remaining = reservation
            self.persist_mission_usage(recorded_at=self._current_time())
        self.provider_calls += 1
        self._mission_reservation_remaining -= 1
        self.checkpoint_if_due()

    def task_completed(self) -> None:
        self.tasks_completed += 1
        self.checkpoint_if_due()

    def checkpoint_if_due(
        self,
        *,
        force: bool = False,
        status: str = "RUNNING",
        reason: str | None = None,
    ) -> None:
        elapsed = self.monotonic() - self._last_checkpoint_monotonic
        calls = self.provider_calls - self._last_checkpoint_calls
        if (
            not force
            and calls < self.checkpoint_calls
            and elapsed < self.checkpoint_minutes * 60
        ):
            return
        recorded_at = self._current_time()
        self.ledger.checkpoint(
            phase=self.phase,
            status=status,
            provider_calls=self.provider_calls,
            tasks_completed=self.tasks_completed,
            started_at=self.job_started_at,
            recorded_at=recorded_at,
            reason=reason,
        )
        self.persist_mission_usage(recorded_at=recorded_at)
        self._last_checkpoint_monotonic = self.monotonic()
        self._last_checkpoint_calls = self.provider_calls

    def persist_mission_usage(self, *, recorded_at: datetime) -> None:
        self.ledger.put_json(
            self.usage_category,
            {
                "schema_version": "historical-deep-mission-usage-v1",
                "mission_started_at": self.mission_started_at,
                "mission_call_cap": self.mission_call_cap,
                "mission_calls_used": self.mission_calls_used,
                "accounting": "CONSERVATIVE_RESERVED_HIGH_WATER",
                "reservation_chunk_calls": self.reservation_chunk_calls,
                "last_phase": self.phase,
                "code_revision": self.code_revision,
                "run_token": self.run_token,
            },
            recorded_at=recorded_at,
        )


class CappedQuota:
    """Apply job and mission ceilings to every transport attempt, including retries."""

    def __init__(self, base: QuotaController, limits: ExecutionLimits) -> None:
        self.base = base
        self.limits = limits

    @property
    def status(self) -> ProviderStatus:
        return self.base.status

    @property
    def budget(self) -> object:
        return self.base.budget

    @property
    def mission_used(self) -> int:
        return self.base.mission_used

    @property
    def mission_cap(self) -> int:
        return self.base.mission_cap

    def before_request(self) -> object:
        self.limits.before_provider_attempt()
        return self.base.before_request()

    acquire = before_request

    def observe_headers(self, headers: Mapping[str, str]) -> object:
        return self.base.observe_headers(headers)

    def replace_status(self, status: ProviderStatus) -> object:
        return self.base.replace_status(status)


def _persisted_mission_calls(
    ledger: DurableRuntimeLedger,
    *,
    mission_started_at: datetime,
    mission_call_cap: int,
    usage_category: str = "mission/usage",
) -> int:
    """Recover the conservative high-water mark for the active mission."""

    expected_start = mission_started_at.astimezone(UTC).isoformat()
    high_water_mark = 0
    for envelope in ledger.values(usage_category):
        value = _mapping(envelope.get("value"))
        if str(value.get("mission_started_at", "")) != expected_start:
            continue
        recorded_cap = _integer(
            value.get("mission_call_cap"),
            label="RUNNER_MISSION_CALL_CAP",
        )
        if recorded_cap != mission_call_cap:
            raise ValueError("RUNNER_MISSION_CALL_CAP_MISMATCH")
        calls = _integer(
            value.get("mission_calls_used"),
            label="RUNNER_MISSION_CALLS_USED",
        )
        if calls < 0 or calls > mission_call_cap:
            raise ValueError("RUNNER_MISSION_CALLS_USED_OUT_OF_RANGE")
        high_water_mark = max(high_water_mark, calls)
    return high_water_mark


def _provider_status_proof(
    status: ProviderStatus,
    *,
    limits: ExecutionLimits,
) -> dict[str, object]:
    budget = QuotaBudget.from_status(status)
    mission_cap = min(limits.mission_call_cap, budget.available)
    proof = status.model_dump(mode="json")
    proof.update(
        {
            "status": "AVAILABLE",
            "quota_remaining": status.daily_remaining,
            "mandatory_reserve": budget.reserve,
            "mission_available": budget.available,
            "mission_call_cap": mission_cap,
            "mission_calls_reserved_high_water": limits.mission_calls_used,
            "mission_remaining": min(
                max(0, mission_cap - limits.mission_calls_used),
                budget.available,
            ),
            "accounting": "CONSERVATIVE_RESERVED_HIGH_WATER",
            "code_revision": limits.code_revision,
            "run_token": limits.run_token,
        }
    )
    return proof


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/historical-deep-data-harvest-v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/historical-deep"),
    )
    parser.add_argument("--code-revision", default="UNSPECIFIED")
    parser.add_argument(
        "--continuation-id",
        default="p0-closure-30622258001-1",
    )
    parser.add_argument("--continuation-of", default="30622258001:1")
    parser.add_argument(
        "--run-purpose",
        default="P0_CLOSURE_AND_SHARDED_REPLAY",
    )
    parser.add_argument(
        "--matches-path",
        type=Path,
        default=Path("data/matches.parquet"),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        help="Explicit local append-only cache; omission requires R2 credentials.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    census = subparsers.add_parser("census")
    _add_collection_arguments(census, default_calls=500, include_priority=False)

    fixtures = subparsers.add_parser("fixtures")
    _add_collection_arguments(fixtures, default_calls=30_000, include_priority=True)

    players = subparsers.add_parser("players")
    _add_collection_arguments(players, default_calls=20_000, include_priority=True)

    injuries = subparsers.add_parser("injuries")
    _add_collection_arguments(injuries, default_calls=10_000, include_priority=True)

    for command in ("replay", "quality", "features", "backtest", "report"):
        subparsers.add_parser(command)
    return parser


def _add_collection_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_calls: int,
    include_priority: bool,
) -> None:
    parser.add_argument("--execute", action="store_true")
    if include_priority:
        parser.add_argument(
            "--priority",
            choices=("P0", "P1", "P2", "auto"),
            default="P0",
        )
    parser.add_argument("--max-calls", type=int, default=default_calls)
    parser.add_argument(
        "--max-duration-minutes",
        type=int,
        default=JOB_MAX_DURATION_MINUTES,
    )
    parser.add_argument(
        "--mission-max-minutes",
        type=int,
        default=GLOBAL_MISSION_MAX_MINUTES,
    )


def _validate_arguments(args: argparse.Namespace, contract: CampaignContract) -> None:
    if args.command not in ALL_COMMANDS:
        raise ValueError("RUNNER_COMMAND_UNKNOWN")
    if args.command not in COLLECTION_COMMANDS:
        return
    if not 1 <= args.max_calls <= contract.quota.mission_call_cap:
        raise ValueError("RUNNER_MAX_CALLS_OUTSIDE_CAMPAIGN_CAP")
    if not 1 <= args.max_duration_minutes <= JOB_MAX_DURATION_MINUTES:
        raise ValueError("RUNNER_JOB_DURATION_OUTSIDE_100_MINUTE_CAP")
    if not 1 <= args.mission_max_minutes <= GLOBAL_MISSION_MAX_MINUTES:
        raise ValueError("RUNNER_MISSION_DURATION_OUTSIDE_720_MINUTE_CAP")
    if contract.quota.checkpoint_max_calls > CHECKPOINT_MAX_CALLS:
        raise ValueError("RUNNER_CHECKPOINT_CALL_CAP_INVALID")
    if contract.quota.checkpoint_max_minutes > CHECKPOINT_MAX_MINUTES:
        raise ValueError("RUNNER_CHECKPOINT_DURATION_CAP_INVALID")


def _new_repository(
    store: ObjectStoreType,
    *,
    code_revision: str,
) -> R2FirstRepository:
    value = _construct_with_supported_kwargs(
        R2FirstRepository,
        store,
        source_commit=code_revision,
    )
    if not isinstance(value, R2FirstRepository):
        raise TypeError("RUNNER_REPOSITORY_FACTORY_INVALID")
    return value


def _new_collector(
    provider: ProviderClient,
    repository: R2FirstRepository,
    *,
    contract: CampaignContract,
    code_revision: str,
    services: RunnerServices,
) -> HistoricalDeepCollector:
    value = _construct_with_supported_kwargs(
        HistoricalDeepCollector,
        provider,
        repository,
        campaign_id=contract.campaign_id,
        clock=services.now,
        monotonic=services.monotonic,
        source_commit=code_revision,
    )
    if not isinstance(value, HistoricalDeepCollector):
        raise TypeError("RUNNER_COLLECTOR_FACTORY_INVALID")
    return value


def _provider_payload(response: object) -> object:
    return getattr(response, "payload", response)


def _provider_datetime(
    response: object,
    field: str,
    default: datetime,
) -> datetime:
    value = getattr(response, field, default)
    if not isinstance(value, datetime):
        return default
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"RUNNER_PROVIDER_{field.upper()}_UTC_REQUIRED")
    return value.astimezone(UTC)


def _direct_task_payload(
    *,
    provider: ProviderClient,
    repository: R2FirstRepository,
    contract: CampaignContract,
    competition: CompetitionSpec,
    season: int,
    endpoint: str,
    params: dict[str, str | int | float | bool | None],
    now: Callable[[], datetime],
    code_revision: str,
) -> object:
    task = HarvestTask.create(
        campaign_id=contract.campaign_id,
        competition=competition,
        season=season,
        family="fixtures",
        endpoint=endpoint,
        temporal_class=TemporalClass.FIXTURE_SPECIFIC_POST_HOC,
        params=params,
    )
    existing = repository.receipt_for(task)
    if existing is not None:
        payload = repository.payload_for(task)
        if payload is None:
            raise PayloadIntegrityError("RUNNER_RECEIPT_WITHOUT_PAYLOAD")
        return payload

    requested_at = now()
    response = provider.get(endpoint, params=params)
    received_at = now()
    requested_at = _provider_datetime(response, "requested_at", requested_at)
    received_at = _provider_datetime(response, "received_at", received_at)
    headers = getattr(response, "headers", {})
    attempts = _integer(getattr(response, "attempts", 1), label="RUNNER_ATTEMPTS")
    stored = _invoke_with_supported_kwargs(
        repository.capture,
        task=task,
        payload=_provider_payload(response),
        requested_at=requested_at,
        received_at=received_at,
        http_status=getattr(response, "http_status", 200),
        sanitized_quota_headers=headers if isinstance(headers, Mapping) else {},
        attempts=attempts,
        provider_calls=attempts,
        collector_version=COLLECTOR_VERSION,
        source_commit=code_revision,
    )
    return getattr(stored, "payload", _provider_payload(response))


def _season_discovery(payload: object) -> tuple[list[int], list[int], dict[str, object]]:
    seasons: dict[int, object] = {}
    response = _mapping(payload).get("response")
    for league_value in _sequence(response):
        league = _mapping(league_value)
        for season_value in _sequence(league.get("seasons")):
            season = _mapping(season_value)
            year = season.get("year")
            if isinstance(year, int) and not isinstance(year, bool):
                seasons[year] = _plain(season.get("coverage"))
    advertised = sorted(seasons)
    verified = [
        year
        for year in advertised
        if isinstance(_mapping(seasons[year]).get("fixtures"), Mapping)
        or _mapping(seasons[year]).get("fixtures") is True
    ]
    return advertised, verified, {str(year): seasons[year] for year in advertised}


def _run_census(
    *,
    collector: HistoricalDeepCollector,
    provider: ProviderClient,
    repository: R2FirstRepository,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    limits: ExecutionLimits,
    code_revision: str,
    services: RunnerServices,
) -> dict[str, object]:
    observations: list[object] = []
    discoveries: dict[str, object] = {}
    previous_census = _mapping(ledger.latest_value("collection/census"))
    previous_by_scope = {
        (
            str(previous.get("competition", "")),
            str(previous.get("season", "")),
        ): previous
        for value in _sequence(previous_census.get("observations"))
        for previous in (_mapping(value),)
    }
    anchor = max((*contract.season_priorities.P0, *contract.season_priorities.P1))
    for competition in contract.competitions:
        limits.assert_time()
        payload = _direct_task_payload(
            provider=provider,
            repository=repository,
            contract=contract,
            competition=competition,
            season=anchor,
            endpoint="/leagues",
            params={"id": competition.provider_league_id},
            now=services.now,
            code_revision=code_revision,
        )
        advertised, _advertised_fixture_coverage, coverage = _season_discovery(payload)
        scoped_observations: list[Mapping[str, object]] = []
        if advertised:
            census = collector.coverage_census(
                [competition.model_dump(mode="python")],
                advertised,
                sample_limit=20,
            )
            scoped_observations = []
            for value in _sequence(census.get("observations")):
                current = dict(_mapping(value))
                scope = (
                    str(current.get("competition", "")),
                    str(current.get("season", "")),
                )
                previous = previous_by_scope.get(scope, {})
                after = _mapping(current.get("actual_coverage"))
                before = _mapping(previous.get("actual_coverage"))
                current["coverage_before_mission"] = {
                    family: before.get(family) if family in before else None
                    for family in sorted(after)
                }
                current["coverage_after_mission"] = dict(after)
                current["coverage_changed_families"] = [
                    family
                    for family in sorted(after)
                    if before.get(family) != after.get(family)
                ]
                scoped_observations.append(current)
            observations.extend(scoped_observations)
        verified = sorted(
            {
                _integer(
                    observation.get("season"),
                    label="RUNNER_VERIFIED_CENSUS_SEASON",
                )
                for observation in scoped_observations
                if _integer(
                    observation.get("sample_received", 0),
                    label="RUNNER_CENSUS_SAMPLE_RECEIVED",
                )
                > 0
            }
        )
        verified_by_family = {
            family: sorted(
                {
                    _integer(
                        observation.get("season"),
                        label="RUNNER_VERIFIED_FAMILY_SEASON",
                    )
                    for observation in scoped_observations
                    if _mapping(observation.get("actual_coverage")).get(family)
                    is True
                }
            )
            for family in ("fixtures", "players", "injuries", "standings")
        }
        older = [
            season
            for season in verified
            if season not in contract.season_priorities.P0
            and season not in contract.season_priorities.P1
        ]
        discoveries[competition.canonical_key] = {
            "provider_league_id": competition.provider_league_id,
            "advertised_seasons": advertised,
            "verified_seasons": verified,
            "verified_older_seasons": older,
            "verified_by_family": verified_by_family,
            "coverage": coverage,
        }
        limits.task_completed()
    discovery = {
        "schema_version": "historical-deep-season-discovery-v1",
        "campaign_id": contract.campaign_id,
        "code_revision": limits.code_revision,
        "run_token": limits.run_token,
        "competitions": discoveries,
        "hash": canonical_sha256(discoveries),
    }
    discovery_key = ledger.put_json(
        "coverage/discovery",
        discovery,
        recorded_at=_aware_now(services),
    )
    result = {
        "schema_version": "historical-deep-census-run-v1",
        "status": "COMPLETE",
        "competition_count": len(contract.competitions),
        "observation_count": len(observations),
        "observations": observations,
        "coverage_comparison": "PREVIOUS_DURABLE_CENSUS_TO_CURRENT_RUN",
        "baseline_census_present": bool(previous_by_scope),
        "discovery": discovery,
        "discovery_key": discovery_key,
        "provider_calls": limits.provider_calls,
        "code_revision": limits.code_revision,
        "run_token": limits.run_token,
    }
    result["hash"] = canonical_sha256(result)
    return result


def _verified_older_seasons(
    ledger: DurableRuntimeLedger,
    competition: CompetitionSpec,
    *,
    family: str,
    contract: CampaignContract,
) -> tuple[int, ...]:
    discovery = _mapping(ledger.latest_value("coverage/discovery"))
    competitions = _mapping(discovery.get("competitions"))
    scoped = _mapping(competitions.get(competition.canonical_key))
    by_family = _mapping(scoped.get("verified_by_family"))
    selected = by_family.get(family, scoped.get("verified_older_seasons"))
    excluded = set(contract.season_priorities.P0) | set(
        contract.season_priorities.P1
    )
    values = {
        _integer(value, label="RUNNER_DISCOVERED_SEASON")
        for value in _sequence(selected)
        if _integer(value, label="RUNNER_DISCOVERED_SEASON") not in excluded
    }
    return tuple(sorted(values))


def _priority_seasons(
    *,
    contract: CampaignContract,
    ledger: DurableRuntimeLedger,
    competition: CompetitionSpec,
    priority: str,
    family: str,
) -> tuple[int, ...]:
    if priority == "P0":
        return tuple(contract.season_priorities.P0)
    if priority == "P1":
        return tuple(contract.season_priorities.P1)
    older = _verified_older_seasons(
        ledger,
        competition,
        family=family,
        contract=contract,
    )
    if priority == "P2":
        return older
    if priority == "auto":
        return tuple(
            sorted(
                set(contract.season_priorities.P0)
                | set(contract.season_priorities.P1)
                | set(older)
            )
        )
    raise ValueError(f"RUNNER_PRIORITY_INVALID:{priority}")


def _compact_collection_result(value: Mapping[str, object]) -> dict[str, object]:
    compact = compact_artifact(value)
    if not isinstance(compact, Mapping):
        raise TypeError("RUNNER_COLLECTION_RESULT_INVALID")
    return dict(compact)


def _completed_collection_scopes(
    ledger: DurableRuntimeLedger,
    category: str,
) -> set[tuple[str, int]]:
    completed: set[tuple[str, int]] = set()
    for envelope in ledger.values(category):
        value = _mapping(envelope.get("value"))
        if value.get("status") != "COMPLETE":
            continue
        competition = value.get("competition")
        season = value.get("season")
        if isinstance(competition, str) and isinstance(season, int):
            completed.add((competition, season))
    return completed


def _record_collection_scope(
    *,
    ledger: DurableRuntimeLedger,
    limits: ExecutionLimits,
    category: str,
    competition: CompetitionSpec,
    season: int,
    status: str,
    details: Mapping[str, object],
) -> str:
    return ledger.put_json(
        category,
        {
            "schema_version": "historical-deep-collection-scope-v1",
            "competition": competition.canonical_key,
            "provider_league_id": competition.provider_league_id,
            "season": season,
            "status": status,
            "details": compact_artifact(details),
            "code_revision": limits.code_revision,
            "run_token": limits.run_token,
        },
        recorded_at=limits.current_time(),
    )


def _run_fixture_collection(
    *,
    collector: HistoricalDeepCollector,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    limits: ExecutionLimits,
    priority: str,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    missing_inventory: list[dict[str, object]] = []
    completed_scopes = _completed_collection_scopes(
        ledger,
        "progress/fixtures",
    )
    pilot = ledger.latest_value("bundle/pilot")
    preferred = contract.competition(contract.bundle_pilot.preferred_competition)
    preferred_seasons = _priority_seasons(
        contract=contract,
        ledger=ledger,
        competition=preferred,
        priority=priority,
        family="fixtures",
    )
    if (
        pilot is None
        and contract.bundle_pilot.preferred_season in preferred_seasons
    ):
        preferred_fixture_ids = ledger.fixture_inventory(
            league=preferred.provider_league_id,
            season=contract.bundle_pilot.preferred_season,
        )
        if preferred_fixture_ids:
            pilot = collector.pilot_fixture_bundles(
                preferred_fixture_ids,
                competition=preferred.model_dump(mode="python"),
                season=contract.bundle_pilot.preferred_season,
                candidate_sizes=contract.bundle_pilot.candidate_sizes,
            )
            ledger.put_json(
                "bundle/pilot",
                pilot,
                recorded_at=limits.current_time(),
            )
    recommended = _mapping(pilot).get("recommended_size")
    batch_size = (
        _integer(recommended, label="RUNNER_PILOT_RECOMMENDED_SIZE")
        if recommended is not None
        else 1
    )
    for competition in contract.competitions:
        for season in _priority_seasons(
            contract=contract,
            ledger=ledger,
            competition=competition,
            priority=priority,
            family="fixtures",
        ):
            limits.assert_time()
            if (competition.canonical_key, season) in completed_scopes:
                continue
            fixture_ids = ledger.fixture_inventory(
                league=competition.provider_league_id,
                season=season,
            )
            if not fixture_ids:
                missing_inventory.append(
                    {
                        "competition": competition.canonical_key,
                        "season": season,
                        "reason": "CENSUS_FIXTURE_INVENTORY_MISSING",
                    }
                )
                continue
            season_context = collector.harvest_season_context(
                competition.provider_league_id,
                season,
            )
            flags = ledger.coverage_flags(
                league=competition.provider_league_id,
                season=season,
            )
            harvested = collector.harvest_fixture_bundles(
                fixture_ids,
                competition=competition.model_dump(mode="python"),
                season=season,
                batch_size=batch_size,
                coverage_flags=flags,
            )
            compact_result = {
                "season_context": _compact_collection_result(season_context),
                "fixture_harvest": _compact_collection_result(harvested),
                "batch_size": batch_size,
            }
            results.append(compact_result)
            _record_collection_scope(
                ledger=ledger,
                limits=limits,
                category="progress/fixtures",
                competition=competition,
                season=season,
                status="COMPLETE",
                details=compact_result,
            )
            completed_scopes.add((competition.canonical_key, season))
            limits.task_completed()
    return {
        "schema_version": "historical-deep-fixture-run-v1",
        "status": "PARTIAL" if missing_inventory else "COMPLETE",
        "priority": priority,
        "results": results,
        "pilot": compact_artifact(pilot),
        "batch_size": batch_size,
        "missing_inventory": missing_inventory,
        "provider_calls": limits.provider_calls,
    }


def _run_player_collection(
    *,
    collector: HistoricalDeepCollector,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    limits: ExecutionLimits,
    priority: str,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    completed_scopes = _completed_collection_scopes(ledger, "progress/players")
    for competition in contract.competitions:
        for season in _priority_seasons(
            contract=contract,
            ledger=ledger,
            competition=competition,
            priority=priority,
            family="players",
        ):
            limits.assert_time()
            if (competition.canonical_key, season) in completed_scopes:
                continue
            result = collector.harvest_player_pages(
                competition.provider_league_id,
                season,
            )
            compact_result = _compact_collection_result(result)
            results.append(compact_result)
            _record_collection_scope(
                ledger=ledger,
                limits=limits,
                category="progress/players",
                competition=competition,
                season=season,
                status="COMPLETE",
                details=compact_result,
            )
            completed_scopes.add((competition.canonical_key, season))
            limits.task_completed()
    return {
        "schema_version": "historical-deep-player-run-v1",
        "status": "COMPLETE",
        "priority": priority,
        "results": results,
        "provider_calls": limits.provider_calls,
    }


def _run_injury_collection(
    *,
    collector: HistoricalDeepCollector,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    limits: ExecutionLimits,
    priority: str,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    completed_scopes = _completed_collection_scopes(
        ledger,
        "progress/injuries",
    )
    for competition in contract.competitions:
        for season in _priority_seasons(
            contract=contract,
            ledger=ledger,
            competition=competition,
            priority=priority,
            family="injuries",
        ):
            limits.assert_time()
            if (competition.canonical_key, season) in completed_scopes:
                continue
            result = collector.harvest_injuries_sidelined(
                competition.provider_league_id,
                season,
                max_sidelined_players=0,
            )
            compact_result = _compact_collection_result(result)
            results.append(compact_result)
            _record_collection_scope(
                ledger=ledger,
                limits=limits,
                category="progress/injuries",
                competition=competition,
                season=season,
                status="COMPLETE",
                details=compact_result,
            )
            completed_scopes.add((competition.canonical_key, season))
            limits.task_completed()
    return {
        "schema_version": "historical-deep-injury-run-v1",
        "status": "COMPLETE",
        "priority": priority,
        "results": results,
        "provider_calls": limits.provider_calls,
    }


def _replay_proof(result: object) -> dict[str, object]:
    mapped = dict(_mapping(_plain(result)))
    entries: list[dict[str, object]] = []
    for value in _sequence(mapped.get("entries")):
        entry = _mapping(value)
        entries.append(
            {
                key: entry.get(key)
                for key in (
                    "receipt_id",
                    "payload_key",
                    "payload_sha256",
                    "projection_sha256",
                )
            }
        )
    mapped["entries"] = entries
    return mapped


def _run_replay(
    *,
    ledger: DurableRuntimeLedger,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
) -> dict[str, object]:
    replay = replay_stream_cache_only(
        ledger.iter_raw_evidence(),
        known_payload_keys=ledger.raw_payload_keys(),
        retain_projections=False,
    )
    result = _replay_proof(replay.as_dict())
    normalized_rows, normalization_errors = ledger.normalized_records()
    projection = {
        "schema_version": "historical-deep-normalized-replay-v1",
        "code_revision": code_revision,
        "run_token": run_token,
        "rows": normalized_rows,
        "row_count": len(normalized_rows),
        "normalization_errors": list(normalization_errors),
        "projection_hash": canonical_sha256(normalized_rows),
        "provider_calls": 0,
    }
    projection_key = ledger.put_json(
        "replay/projection",
        projection,
        recorded_at=_aware_now(services),
    )
    result["normalized_rows"] = len(normalized_rows)
    result["normalization_errors"] = list(normalization_errors)
    result["normalized_projection_hash"] = projection["projection_hash"]
    result["normalized_projection_key"] = projection_key
    result["code_revision"] = code_revision
    result["run_token"] = run_token
    result["durable_key"] = ledger.put_json(
        "replay",
        result,
        recorded_at=_aware_now(services),
    )
    return result


def _deduplicated_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    preserve_input_order: bool = False,
) -> list[dict[str, object]]:
    indexed: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row.get("task_id", "")), str(row.get("record_hash", "")))
        if not all(key):
            continue
        # Staging hydration already owns mutable dictionaries.  Reuse them so a
        # multi-million-row projection is not copied merely to deduplicate it.
        value = row if isinstance(row, dict) else dict(row)
        indexed.setdefault(key, value)
    if preserve_input_order:
        return list(indexed.values())
    return [indexed[key] for key in sorted(indexed)]


def _verified_segmented_quality_comparison(
    rows: Sequence[Mapping[str, object]],
    *,
    projection_hash: str,
) -> dict[str, object]:
    """Build an exact comparison from the verified second-pass proof.

    The segmented reducer has already compared both passes, verified every
    staging part, and pinned the projection hash.  Re-indexing and copying the
    full corpus twice in quality adds no evidence and can exhaust a hosted
    runner.  We still validate the stable quality identity and coverage here.
    """

    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        identity = {
            "task_id": row.get("task_id"),
            "normalized_family": row.get(
                "normalized_family", row.get("family")
            ),
            "canonical_id": row.get("canonical_id"),
            "provider_fixture_id": row.get("provider_fixture_id"),
            "source_record_hash": row.get("source_record_hash"),
        }
        if not identity["task_id"] or not identity["canonical_id"]:
            raise ValueError("QUALITY_STABLE_IDENTITY_REQUIRED")
        quality_row_key = (
            str(identity["task_id"] or ""),
            str(identity["normalized_family"] or ""),
            str(identity["canonical_id"] or ""),
            str(identity["provider_fixture_id"] or ""),
            str(identity["source_record_hash"] or ""),
        )
        if quality_row_key in seen:
            raise ValueError(
                f"QUALITY_BEFORE_DUPLICATE_KEY:{canonical_sha256(identity)}"
            )
        seen.add(quality_row_key)
    del seen
    snapshot = coverage_snapshot_v2(
        rows,
        required_fields=(
            "record_hash",
            "source_payload_hash",
            "temporal_class",
        ),
    ).as_dict()
    return {
        "schema_version": "historical-deep-quality-v2",
        "before": snapshot,
        "after": dict(snapshot),
        "mismatches": [],
        "null_to_zero_conversions": 0,
        "before_hash": projection_hash,
        "after_hash": projection_hash,
        "exact_replay": True,
        "comparison_basis": "SEGMENTED_SECOND_PASS_IDEMPOTENCE",
        "stable_identity_verified": True,
    }


def _quality_keyed_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach a replay-stable identity that does not include normalized values."""

    keyed: list[dict[str, object]] = []
    for row in rows:
        identity = {
            "task_id": row.get("task_id"),
            "normalized_family": row.get("normalized_family", row.get("family")),
            "canonical_id": row.get("canonical_id"),
            "provider_fixture_id": row.get("provider_fixture_id"),
            "source_record_hash": row.get("source_record_hash"),
        }
        if not identity["task_id"] or not identity["canonical_id"]:
            raise ValueError("QUALITY_STABLE_IDENTITY_REQUIRED")
        keyed.append(
            {
                **dict(row),
                "quality_row_key": canonical_sha256(identity),
            }
        )
    return keyed


def _latest_target_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    targets: dict[tuple[str, str], tuple[str, str, Mapping[str, object]]] = {}
    for row in rows:
        if str(row.get("family")) != "fixtures":
            continue
        fixture_id = row.get("provider_fixture_id")
        kickoff = row.get("target_kickoff_at")
        competition = row.get("provider_competition_id")
        season = row.get("season")
        if None in (fixture_id, kickoff, competition, season):
            continue
        key = (str(competition), str(season))
        candidate = (str(fixture_id), str(kickoff), row)
        if key not in targets or candidate[1] > targets[key][1]:
            targets[key] = candidate
    return [
        row if isinstance(row, dict) else dict(row)
        for _fixture_id, _kickoff, row in targets.values()
    ]


def _enrich_targets(
    rows: Sequence[Mapping[str, object]],
    *,
    copy_rows: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    targets = {
        (
            str(row.get("provider_competition_id", "")),
            str(row.get("season", "")),
        ): (
            str(row.get("provider_fixture_id", "")),
            str(row.get("target_kickoff_at", "")),
            row,
        )
        for row in _latest_target_rows(rows)
    }
    enriched: list[dict[str, object]] = []
    target_rows = [
        row if isinstance(row, dict) else dict(row)
        for _fixture_id, _kickoff, row in targets.values()
    ]
    for row in rows:
        key = (
            str(row.get("provider_competition_id", "")),
            str(row.get("season", "")),
        )
        target = targets.get(key)
        if target is None:
            continue
        fixture_id, kickoff, _ = target
        if copy_rows:
            value = dict(row)
        elif isinstance(row, dict):
            value = row
        else:
            raise TypeError("QUALITY_IN_PLACE_RECORD_MUST_BE_MUTABLE")
        value.update(
            {
                "source_fixture_id": row.get("provider_fixture_id"),
                "source_fixture_kickoff": row.get("target_kickoff_at"),
                "target_fixture_id": fixture_id,
                "target_fixture_kickoff": kickoff,
            }
        )
        enriched.append(value)
    return enriched, target_rows


def _quality_products(
    *,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
) -> tuple[
    dict[str, object],
    dict[str, list[dict[str, object]]],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
]:
    replay_projection = _latest_mapping_for_lineage(
        ledger,
        "replay/projection",
        code_revision,
        run_token,
    )
    normalized_before = load_staging_projection_rows(
        ledger.store,
        replay_projection,
    )
    errors_before = tuple(
        str(value)
        for value in _sequence(replay_projection.get("normalization_errors"))
    )
    expected_projection_hash = replay_projection.get("projection_hash")
    projection_hash_valid = (
        isinstance(expected_projection_hash, str)
        and expected_projection_hash == canonical_sha256(normalized_before)
    )
    replay_value = _latest_mapping_for_lineage(
        ledger,
        "replay",
        code_revision,
        run_token,
    )
    segmented_projection = replay_value.get("inventory_sha256") is not None
    if segmented_projection:
        idempotence = _latest_mapping_for_lineage(
            ledger,
            "replay/idempotence",
            code_revision,
            run_token,
        )
        idempotence_gates = {
            str(value) for value in _sequence(idempotence.get("gates"))
        }
        if (
            idempotence.get("status") != "SECOND_PASS_IDEMPOTENT"
            or "CURRENT_SECOND_PASS_IDEMPOTENT" not in idempotence_gates
            or idempotence.get("inventory_sha256")
            != replay_value.get("inventory_sha256")
        ):
            raise ValueError("QUALITY_SEGMENTED_IDEMPOTENCE_PROOF_REQUIRED")
        normalized_after = normalized_before
        errors_after: tuple[str, ...] = ()
    else:
        normalized_after, errors_after = ledger.normalized_records()
    rows = _deduplicated_rows(
        normalized_before,
        preserve_input_order=segmented_projection,
    )
    if segmented_projection:
        if not isinstance(expected_projection_hash, str):
            raise ValueError("QUALITY_SEGMENTED_PROJECTION_HASH_REQUIRED")
        comparison = _verified_segmented_quality_comparison(
            rows,
            projection_hash=expected_projection_hash,
        )
    else:
        replayed_rows = _deduplicated_rows(normalized_after)
        comparison = compare_quality_v2(
            _quality_keyed_rows(rows),
            _quality_keyed_rows(replayed_rows),
            key_fields=("quality_row_key",),
            required_fields=(
                "record_hash",
                "source_payload_hash",
                "temporal_class",
            ),
            identity_fields=("canonical_id",),
            fail_on_null_to_zero=False,
        ).as_dict()
    normalization_errors = tuple(
        sorted(
            {
                *errors_before,
                *errors_after,
                *(
                    ()
                    if projection_hash_valid
                    else ("REPLAY_NORMALIZED_PROJECTION_MISSING_OR_MISMATCHED",)
                ),
            }
        )
    )
    comparison["exact_replay"] = bool(comparison.get("exact_replay")) and not (
        normalization_errors
    )
    enriched, _targets = _enrich_targets(
        rows,
        copy_rows=not segmented_projection,
    )
    separated = separate_temporal_datasets(
        enriched,
        copy_records=not segmented_projection,
    )
    datasets = (
        separated
        if segmented_projection
        else {
            name: sorted(values, key=canonical_sha256)
            for name, values in separated.items()
        }
    )
    manifests = build_dataset_manifests(
        datasets,
        provenance={
            "provider": "api-football",
            "r2_namespace": contract.storage.namespace,
            "campaign_contract_hash": contract.contract_hash,
            "code_revision": code_revision,
            "run_token": run_token,
            "replay_hash": replay_value.get("replay_hash"),
        },
        preserve_input_order=segmented_projection,
    )
    manifest_values: dict[str, object] = {
        name: manifest.as_dict() for name, manifest in manifests.items()
    }
    evidence = _gate_evidence(
        datasets,
        coverage_census=_latest_mapping_for_lineage(
            ledger,
            "collection/census",
            code_revision,
            run_token,
        ),
    )
    assessments = evaluate_gate_registry(evidence)
    gates: dict[str, object] = {
        name: {
            **assessment.as_dict(),
            "code_revision": code_revision,
            "run_token": run_token,
        }
        for name, assessment in assessments.items()
    }
    quality = {
        **comparison,
        "code_revision": code_revision,
        "run_token": run_token,
        "source_replay_hash": replay_value.get("replay_hash"),
        "source_projection_hash": expected_projection_hash,
        "normalization_errors": list(normalization_errors),
        "normalized_rows": len(rows),
        "targeted_rows": len(enriched),
        "dataset_rows": {name: len(values) for name, values in datasets.items()},
        "provider_calls": 0,
    }
    return quality, datasets, manifest_values, gates, normalized_before


def _evidence_for_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    reconstructed: bool,
    coverage_by_scope: Mapping[tuple[str, int], float | None] | None = None,
) -> list[dict[str, object]]:
    selected_coverage = coverage_by_scope or {}
    by_scope: dict[tuple[str, int], list[Mapping[str, object]]] = {}
    for row in rows:
        season = row.get("season")
        if isinstance(season, int) and not isinstance(season, bool):
            league = str(row.get("provider_competition_id", "UNKNOWN"))
            by_scope.setdefault((league, season), []).append(row)
    evidence: list[dict[str, object]] = []
    for (league, season) in sorted(set(by_scope) | set(selected_coverage)):
        scoped = by_scope.get((league, season), [])
        identities = sum(
            bool(row.get("canonical_id")) and bool(row.get("identity_status"))
            for row in scoped
        )
        evidence.append(
            {
                "provider_league_id": league,
                "season": season,
                "coverage_rate": selected_coverage.get((league, season)),
                "identity_rate": identities / len(scoped) if scoped else 0.0,
                "cutoff_proven": not reconstructed,
                "source_available": True,
                "reconstructed": reconstructed,
            }
        )
    return evidence


def _census_family_coverage(
    census: Mapping[str, object],
    family: str,
) -> dict[tuple[str, int], float | None]:
    rates: dict[tuple[str, int], float | None] = {}
    for value in _sequence(census.get("observations")):
        observation = _mapping(value)
        league = observation.get("provider_league_id")
        season = observation.get("season")
        if (
            isinstance(league, bool)
            or not isinstance(league, (int, str))
            or isinstance(season, bool)
            or not isinstance(season, int)
        ):
            continue
        raw_rate = _mapping(
            _mapping(observation.get("field_matrix")).get(family)
        ).get("sample_coverage_rate")
        rate = (
            float(raw_rate)
            if isinstance(raw_rate, (int, float))
            and not isinstance(raw_rate, bool)
            and 0.0 <= float(raw_rate) <= 1.0
            else None
        )
        rates[(str(league), season)] = rate
    return rates


def _gate_evidence(
    datasets: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    coverage_census: Mapping[str, object],
) -> dict[str, Sequence[Mapping[str, object]]]:
    team_rows = datasets["TEAM_PREMATCH_STRICT"]
    player_rows = datasets["PLAYER_PREMATCH_STRICT"]
    team = _evidence_for_rows(
        team_rows,
        reconstructed=False,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "team_match_statistics",
        ),
    )
    player = _evidence_for_rows(
        player_rows,
        reconstructed=False,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "player_match_statistics",
        ),
    )
    lineup = _evidence_for_rows(
        datasets["LINEUP_HISTORY_PREMATCH_STRICT"],
        reconstructed=False,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "lineups",
        ),
    )
    target_lineup = _evidence_for_rows(
        datasets["TARGET_POST_LINEUP_RECONSTRUCTED"],
        reconstructed=True,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "lineups",
        ),
    )
    absence = _evidence_for_rows(
        datasets["INJURY_INTERVAL_RECONSTRUCTED"],
        reconstructed=True,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "injuries",
        ),
    )
    formation = _evidence_for_rows(
        [
            row
            for row in (
                *datasets["LINEUP_HISTORY_PREMATCH_STRICT"],
                *datasets["TARGET_POST_LINEUP_RECONSTRUCTED"],
            )
            if str(row.get("family", "")).casefold()
            in {"formation", "formations", "lineup", "lineups"}
        ],
        reconstructed=True,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "formations",
        ),
    )
    discipline = _evidence_for_rows(
        [
            row
            for row in team_rows
            if str(row.get("family", "")).casefold()
            in {"event", "events", "fixture_events"}
        ],
        reconstructed=False,
        coverage_by_scope=_census_family_coverage(
            coverage_census,
            "events",
        ),
    )
    seasons = sorted(
        {
            _integer(row["season"], label="RUNNER_GATE_SEASON")
            for values in datasets.values()
            for row in values
            if isinstance(row.get("season"), int)
        }
    )
    unavailable_weather = [
        {"season": season, "source_available": False} for season in seasons
    ]
    return {
        "TEAM": team,
        "PLAYER": player,
        "PLAYER_FORM": player,
        "STARTER_BASELINE": lineup,
        "LINEUP": [*lineup, *target_lineup],
        "FORMATION": formation,
        "ABSENCE": absence,
        "DISCIPLINE": discipline,
        "FOOTEDNESS": (),
        "WEATHER": unavailable_weather,
    }


def _canonical_sequence_sha256(values: Sequence[object]) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, value in enumerate(values):
        if index:
            digest.update(b",")
        digest.update(canonical_json_bytes(value))
    digest.update(b"]")
    return digest.hexdigest()


def _put_immutable_bytes(
    ledger: DurableRuntimeLedger,
    key: str,
    data: bytes,
) -> None:
    if ledger.store.put_if_absent(key, data):
        return
    if ledger.store.get_object(key) != data:
        raise ValueError(f"QUALITY_APPEND_ONLY_MISMATCH:{key}")


def _persist_quality_dataset(
    *,
    ledger: DurableRuntimeLedger,
    dataset_name: str,
    rows: Sequence[Mapping[str, object]],
    manifest: Mapping[str, object],
    code_revision: str,
    run_token: str,
    recorded_at: datetime,
) -> str:
    """Persist a temporal dataset without one runner-sized JSON allocation."""

    if len(rows) <= QUALITY_DATASET_PART_MAX_ROWS:
        return ledger.put_json(
            f"datasets/{dataset_name}",
            {
                "schema_version": "historical-deep-temporal-dataset-v1",
                "dataset": dataset_name,
                "manifest": manifest,
                "rows": rows,
                "row_count": len(rows),
                "provider_calls": 0,
                "code_revision": code_revision,
                "run_token": run_token,
            },
            recorded_at=recorded_at,
        )

    dataset_hash = str(manifest.get("dataset_hash", ""))
    if len(dataset_hash) != 64:
        raise ValueError("QUALITY_DATASET_HASH_REQUIRED")
    parts: list[dict[str, object]] = []
    for ordinal, offset in enumerate(
        range(0, len(rows), QUALITY_DATASET_PART_MAX_ROWS),
        start=1,
    ):
        part_rows = rows[offset : offset + QUALITY_DATASET_PART_MAX_ROWS]
        part_hash = _canonical_sequence_sha256(part_rows)
        part_value = {
            "schema_version": "historical-deep-temporal-dataset-part-v2",
            "dataset": dataset_name,
            "code_revision": code_revision,
            "part_ordinal": ordinal,
            "row_count": len(part_rows),
            "part_sha256": part_hash,
            "rows": part_rows,
        }
        key = (
            f"{DERIVED_NAMESPACE}/quality-datasets-v2/"
            f"revision={code_revision}/dataset={dataset_name}/"
            f"dataset-hash={dataset_hash}/"
            f"part-{ordinal:06d}-{part_hash}.json.gz"
        )
        data = gzip.compress(
            canonical_json_bytes(part_value),
            compresslevel=QUALITY_DATASET_COMPRESSION_LEVEL,
            mtime=0,
        )
        _put_immutable_bytes(ledger, key, data)
        parts.append(
            {
                "part_ordinal": ordinal,
                "row_count": len(part_rows),
                "part_sha256": part_hash,
                "key": key,
            }
        )
    return ledger.put_json(
        f"datasets/{dataset_name}",
        {
            "schema_version": "historical-deep-temporal-dataset-manifest-v2",
            "dataset": dataset_name,
            "manifest": manifest,
            "storage_layout": "SHARDED_R2",
            "parts": parts,
            "part_count": len(parts),
            "row_count": len(rows),
            "dataset_hash": manifest.get("dataset_hash"),
            "provider_calls": 0,
            "code_revision": code_revision,
            "run_token": run_token,
        },
        recorded_at=recorded_at,
        compression_level=QUALITY_DATASET_COMPRESSION_LEVEL,
    )


def _load_persisted_quality_dataset(
    *,
    ledger: DurableRuntimeLedger,
    dataset_name: str,
    code_revision: str,
    run_token: str,
) -> list[dict[str, object]]:
    value = _latest_mapping_for_lineage(
        ledger,
        f"datasets/{dataset_name}",
        code_revision,
        run_token,
    )
    inline = value.get("rows")
    if isinstance(inline, Sequence) and not isinstance(
        inline, (str, bytes, bytearray)
    ):
        return [dict(_mapping(row)) for row in inline]
    if (
        value.get("schema_version")
        != "historical-deep-temporal-dataset-manifest-v2"
        or value.get("storage_layout") != "SHARDED_R2"
        or value.get("dataset") != dataset_name
    ):
        return []
    parts = list(_sequence(value.get("parts")))
    if value.get("part_count") != len(parts):
        raise ValueError("QUALITY_DATASET_PART_COUNT_MISMATCH")
    rows: list[dict[str, object]] = []
    for offset in range(0, len(parts), 8):
        batch = parts[offset : offset + 8]
        keys = [str(_mapping(part).get("key", "")) for part in batch]
        for (key, body), part_value in zip(
            read_objects_bounded(ledger.store, keys),
            batch,
            strict=True,
        ):
            part_manifest = _mapping(part_value)
            if body is None:
                raise ValueError(f"QUALITY_DATASET_PART_MISSING:{key}")
            try:
                decoded = json.loads(gzip.decompress(body))
            except (gzip.BadGzipFile, EOFError, json.JSONDecodeError) as error:
                raise ValueError("QUALITY_DATASET_PART_INVALID") from error
            part = _mapping(decoded)
            part_rows = [
                dict(_mapping(row)) for row in _sequence(part.get("rows"))
            ]
            expected_hash = str(part_manifest.get("part_sha256", ""))
            if (
                part.get("schema_version")
                != "historical-deep-temporal-dataset-part-v2"
                or part.get("dataset") != dataset_name
                or part.get("code_revision") != code_revision
                or part.get("part_ordinal")
                != part_manifest.get("part_ordinal")
                or part.get("row_count") != len(part_rows)
                or part.get("row_count") != part_manifest.get("row_count")
                or part.get("part_sha256") != expected_hash
                or _canonical_sequence_sha256(part_rows) != expected_hash
            ):
                raise ValueError("QUALITY_DATASET_PART_CONTRACT_MISMATCH")
            rows.extend(part_rows)
    expected_rows = value.get("row_count")
    dataset_hash = value.get("dataset_hash")
    if (
        expected_rows != len(rows)
        or not isinstance(dataset_hash, str)
        or _canonical_sequence_sha256(rows) != dataset_hash
    ):
        raise ValueError("QUALITY_DATASET_MANIFEST_MISMATCH")
    return rows


def _run_quality(
    *,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
) -> dict[str, object]:
    quality, datasets, manifests, gates, _normalized = _quality_products(
        ledger=ledger,
        contract=contract,
        code_revision=code_revision,
        run_token=run_token,
    )
    genome = build_genome_availability_projection(gates)
    genome.pop("projection_hash", None)
    genome["code_revision"] = code_revision
    genome["run_token"] = run_token
    genome["projection_hash"] = canonical_sha256(genome)
    gate_assessments = evaluate_gate_registry(
        _gate_evidence(
            datasets,
            coverage_census=_latest_mapping_for_lineage(
                ledger,
                "collection/census",
                code_revision,
                run_token,
            ),
        )
    )
    recorded_at = _aware_now(services)
    gate_report = {
        "schema_version": "historical-deep-gate-report-v1",
        "status": "COMPLETE",
        "code_revision": code_revision,
        "run_token": run_token,
        "gate_hash": canonical_sha256(gates),
        "gates": gates,
        "provider_calls": 0,
    }
    keys = {
        "quality": ledger.put_json("quality", quality, recorded_at=recorded_at),
        "datasets": ledger.put_json(
            "dataset-manifests",
            manifests,
            recorded_at=recorded_at,
        ),
        "gates": ledger.put_json("gates", gates, recorded_at=recorded_at),
        "gate_report": ledger.put_json(
            "gate-report", gate_report, recorded_at=recorded_at
        ),
        "genome": ledger.put_json("genome", genome, recorded_at=recorded_at),
    }
    for name, rows in sorted(datasets.items()):
        keys[f"dataset:{name}"] = _persist_quality_dataset(
            ledger=ledger,
            dataset_name=name,
            rows=rows,
            manifest=_mapping(manifests[name]),
            code_revision=code_revision,
            run_token=run_token,
            recorded_at=recorded_at,
        )
    return {
        "schema_version": "historical-deep-quality-run-v1",
        "status": (
            "FAILED"
            if quality.get("null_to_zero_conversions", 0) not in (0, None)
            else "COMPLETE"
            if quality.get("exact_replay")
            else "PARTIAL"
        ),
        "code_revision": code_revision,
        "run_token": run_token,
        "quality": quality,
        "datasets": manifests,
        "gates": gates,
        "gate_summary": gate_summary(gate_assessments),
        "genome": genome,
        "durable_keys": keys,
        "provider_calls": 0,
    }


def _target_team_ids(row: Mapping[str, object]) -> tuple[str, ...]:
    data = _mapping(row.get("data"))
    teams = _mapping(data.get("teams"))
    output: list[str] = []
    for side in ("home", "away"):
        team_id = _mapping(teams.get(side)).get("id")
        if team_id is not None:
            output.append(str(team_id))
    return tuple(output)


def _run_features(
    *,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
) -> dict[str, object]:
    quality = _latest_mapping_for_lineage(
        ledger,
        "quality",
        code_revision,
        run_token,
    )
    manifests = _latest_mapping_for_lineage(
        ledger,
        "dataset-manifests",
        code_revision,
        run_token,
    )
    gates = _latest_mapping_for_lineage(
        ledger,
        "gates",
        code_revision,
        run_token,
    )
    dataset_records = {
        name: _latest_mapping_for_lineage(
            ledger,
            f"datasets/{name}",
            code_revision,
            run_token,
        )
        for name in DATASET_NAMES
    }
    if quality and manifests and gates and all(dataset_records.values()):
        datasets = {
            name: _load_persisted_quality_dataset(
                ledger=ledger,
                dataset_name=name,
                code_revision=code_revision,
                run_token=run_token,
            )
            for name in DATASET_NAMES
        }
    else:
        quality, datasets, manifests, gates, _normalized = _quality_products(
            ledger=ledger,
            contract=contract,
            code_revision=code_revision,
            run_token=run_token,
        )
    targets = _latest_target_rows(datasets["POST_MATCH_DESCRIPTIVE"])
    if not targets:
        targets = _latest_target_rows(
            [row for values in datasets.values() for row in values]
        )

    def by_team(
        rows: Sequence[Mapping[str, object]],
    ) -> dict[str, list[Mapping[str, object]]]:
        indexed: dict[str, list[Mapping[str, object]]] = {}
        for row in rows:
            team_id = row.get("provider_team_id")
            if team_id is not None:
                indexed.setdefault(str(team_id), []).append(row)
        return indexed

    team_by_team = by_team(datasets["TEAM_PREMATCH_STRICT"])
    player_by_team = by_team(datasets["PLAYER_PREMATCH_STRICT"])
    lineup_by_team = by_team(datasets["LINEUP_HISTORY_PREMATCH_STRICT"])
    injury_by_team = by_team(datasets["INJURY_INTERVAL_RECONSTRUCTED"])
    bundles: list[dict[str, object]] = []
    errors: list[str] = []
    for target in targets:
        fixture_id = target.get("provider_fixture_id")
        kickoff = target.get("target_kickoff_at")
        if fixture_id is None or kickoff is None:
            continue
        for team_id in _target_team_ids(target):
            player_ids = sorted(
                {
                    str(row["provider_player_id"])
                    for row in player_by_team.get(team_id, ())
                    if row.get("provider_player_id") is not None
                }
            )[:25]
            try:
                bundle = build_historical_feature_bundle(
                    target_fixture_id=str(fixture_id),
                    target_fixture_kickoff=str(kickoff),
                    team_id=team_id,
                    team_rows=team_by_team.get(team_id, ()),
                    player_rows=player_by_team.get(team_id, ()),
                    lineup_rows=lineup_by_team.get(team_id, ()),
                    discipline_rows=[
                        *team_by_team.get(team_id, ()),
                        *injury_by_team.get(team_id, ()),
                    ],
                    player_ids=player_ids,
                )
            except ValueError as error:
                errors.append(f"{fixture_id}:{team_id}:{error}")
                continue
            bundles.append(bundle)
    detailed: dict[str, object] = {
        "schema_version": "historical-deep-feature-run-v1",
        "status": (
            "COMPLETE"
            if not errors and bundles and quality.get("exact_replay") is True
            else "PARTIAL"
        ),
        "code_revision": code_revision,
        "run_token": run_token,
        "bundles": bundles,
        "errors": errors,
        "dataset_manifests": manifests,
        "gates": gates,
        "provider_calls": 0,
        "production_status": "PRODUCTION_LOCKED",
        "promotion": "NO_PROMOTION",
    }
    detailed["feature_hash"] = canonical_sha256(detailed)
    feature_manifest = {
        "schema_version": "historical-deep-feature-manifests-v1",
        "status": detailed["status"],
        "code_revision": code_revision,
        "run_token": run_token,
        "feature_hash": detailed["feature_hash"],
        "bundle_count": len(bundles),
        "dataset_manifests": manifests,
        "provider_calls": 0,
    }
    detailed["feature_manifest_key"] = ledger.put_json(
        "feature-manifests",
        feature_manifest,
        recorded_at=_aware_now(services),
    )
    detailed["durable_key"] = ledger.put_json(
        "features",
        detailed,
        recorded_at=_aware_now(services),
    )
    return detailed


def _backtest_rows(
    ledger: DurableRuntimeLedger,
    *,
    code_revision: str,
    run_token: str,
) -> list[dict[str, object]]:
    value = _latest_mapping_for_lineage(
        ledger,
        "backtest-input",
        code_revision,
        run_token,
    )
    rows = value.get("rows")
    return [
        dict(item)
        for item in _sequence(rows)
        if isinstance(item, Mapping)
    ]


def _run_backtest(
    *,
    ledger: DurableRuntimeLedger,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
    matches_path: Path,
) -> dict[str, object]:
    rows = _backtest_rows(
        ledger,
        code_revision=code_revision,
        run_token=run_token,
    )
    input_key: str | None = None
    if not rows:
        rows = build_cache_only_backtest_input(matches_path)
        input_key = ledger.put_json(
            "backtest-input",
            {
                "schema_version": "historical-deep-backtest-input-v1",
                "code_revision": code_revision,
                "run_token": run_token,
                "source": "TRACKED_DATA_MATCHES_PARQUET",
                "source_path": matches_path.as_posix(),
                "provider_calls": 0,
                "deep_player_features": "BLOCKED_BY_SOURCE",
                "deep_lineup_features": "BLOCKED_BY_SOURCE",
                "rows": rows,
                "input_hash": canonical_sha256(rows),
            },
            recorded_at=_aware_now(services),
        )
    result = run_cache_only_backtest(rows)
    modes = _mapping(result.get("modes"))
    evaluated_folds = sum(
        len(_sequence(_mapping(mode).get("folds")))
        for mode in modes.values()
    )
    deep_feature_rows = sum(
        row.get("deep_player_features") not in {None, "BLOCKED_BY_SOURCE"}
        and row.get("deep_lineup_features") not in {None, "BLOCKED_BY_SOURCE"}
        for row in rows
    )
    result["input_rows"] = len(rows)
    result["evaluated_folds"] = evaluated_folds
    result["deep_feature_rows"] = deep_feature_rows
    result["input_status"] = "AVAILABLE" if rows else "NO_CACHE_ONLY_INPUT"
    result["status"] = (
        "COMPLETE"
        if rows and evaluated_folds and deep_feature_rows
        else "PARTIAL"
    )
    result["scope_reason"] = (
        "DEEP_R2_FEATURE_SUPPORT"
        if deep_feature_rows
        else "TRACKED_TEAM_HISTORY_ONLY_DEEP_FEATURES_BLOCKED_BY_SOURCE"
    )
    result["input_key"] = input_key
    result["code_revision"] = code_revision
    result["run_token"] = run_token
    result["durable_key"] = ledger.put_json(
        "backtest",
        result,
        recorded_at=_aware_now(services),
    )
    return result


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _match_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        if not isinstance(converted, datetime):
            raise ValueError("BACKTEST_MATCH_DATE_INVALID")
        parsed = converted
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError("BACKTEST_MATCH_DATE_INVALID") from error
    else:
        raise ValueError("BACKTEST_MATCH_DATE_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _history_mean(
    values: Sequence[tuple[datetime, float, float]],
    *,
    position: int,
    window: int = 5,
) -> float | None:
    selected = values[-window:]
    if not selected:
        return None
    if position == 1:
        return sum(item[1] for item in selected) / len(selected)
    if position == 2:
        return sum(item[2] for item in selected) / len(selected)
    raise ValueError("BACKTEST_HISTORY_POSITION_INVALID")


def build_cache_only_backtest_input(
    matches_path: Path,
    *,
    maximum_rows: int = 5_000,
) -> list[dict[str, object]]:
    """Build a bounded pilot from tracked matches using strictly prior state."""

    if maximum_rows < 1:
        raise ValueError("BACKTEST_INPUT_MAXIMUM_ROWS_MUST_BE_POSITIVE")
    if not matches_path.is_file():
        return []
    import pandas as pd

    selected_columns = [
        "league",
        "season",
        "date",
        "home",
        "away",
        "fthg",
        "ftag",
        "psh",
        "psch",
        "match_id",
    ]
    frame = pd.read_parquet(matches_path, columns=selected_columns)
    frame = frame[frame["league"].isin(("E0", "F1", "SP1", "D1", "I1"))]
    frame = frame.sort_values(["date", "match_id"], kind="stable")
    records = cast(list[dict[str, object]], frame.to_dict(orient="records"))

    TeamKey = tuple[str, str]
    overall: dict[TeamKey, list[tuple[datetime, float, float]]] = {}
    home_history: dict[TeamKey, list[tuple[datetime, float, float]]] = {}
    away_history: dict[TeamKey, list[tuple[datetime, float, float]]] = {}
    output: list[dict[str, object]] = []
    competition_map = {
        "E0": "api-football:39",
        "F1": "api-football:61",
        "SP1": "api-football:140",
        "D1": "api-football:78",
        "I1": "api-football:135",
    }

    for record in records:
        league = str(record.get("league", ""))
        home = str(record.get("home", ""))
        away = str(record.get("away", ""))
        fixture_id = str(record.get("match_id", ""))
        if not all((league, home, away, fixture_id)):
            continue
        kickoff = _match_datetime(record.get("date"))
        home_goals = _optional_number(record.get("fthg"))
        away_goals = _optional_number(record.get("ftag"))
        odds = _optional_number(record.get("psch")) or _optional_number(
            record.get("psh")
        )
        if home_goals is None or away_goals is None or odds is None or odds <= 1:
            continue

        home_key = (league, home)
        away_key = (league, away)
        # A duplicated fixture or simultaneous record must never make an
        # outcome at the target kickoff available to another target row.
        home_overall = [
            item for item in overall.get(home_key, []) if item[0] < kickoff
        ]
        away_overall = [
            item for item in overall.get(away_key, []) if item[0] < kickoff
        ]
        home_at_home = [
            item for item in home_history.get(home_key, []) if item[0] < kickoff
        ]
        away_as_away = [
            item for item in away_history.get(away_key, []) if item[0] < kickoff
        ]
        home_ppg = _history_mean(home_overall, position=1)
        away_ppg = _history_mean(away_overall, position=1)
        home_goal_difference = _history_mean(home_overall, position=2)
        away_goal_difference = _history_mean(away_overall, position=2)
        home_home_ppg = _history_mean(home_at_home, position=1)
        away_away_ppg = _history_mean(away_as_away, position=1)
        home_last = home_overall[-1][0] if home_overall else None
        away_last = away_overall[-1][0] if away_overall else None

        if (
            home_ppg is not None
            and away_ppg is not None
            and home_goal_difference is not None
            and away_goal_difference is not None
        ):
            venue_edge = (home_home_ppg or home_ppg) - (away_away_ppg or away_ppg)
            raw_probability = (
                0.46
                + 0.055 * (home_ppg - away_ppg)
                + 0.025 * (home_goal_difference - away_goal_difference)
                + 0.025 * venue_edge
            )
            probability = min(0.95, max(0.05, raw_probability))
            prior_dates = [
                item[0]
                for item in (*home_overall[-5:], *away_overall[-5:])
                if item[0] < kickoff
            ]
            output.append(
                {
                    "research_mode": "STRICT_PREMATCH",
                    "period": str(record.get("season", "")),
                    "season": str(record.get("season", "")),
                    "fixture_id": fixture_id,
                    "target_fixture_id": fixture_id,
                    "kickoff_at": kickoff.isoformat(),
                    "target_fixture_kickoff": kickoff.isoformat(),
                    "model_probability": probability,
                    "market_probability": 1.0 / odds,
                    "odds": odds,
                    "target": int(home_goals > away_goals),
                    "competition": competition_map[league],
                    "source_mode": "TRACKED_CACHE",
                    "provider_calls": 0,
                    "home_form_points_5": home_ppg,
                    "away_form_points_5": away_ppg,
                    "home_goal_difference_5": home_goal_difference,
                    "away_goal_difference_5": away_goal_difference,
                    "home_home_points_5": home_home_ppg,
                    "away_away_points_5": away_away_ppg,
                    "home_rest_days": (
                        (kickoff - home_last).total_seconds() / 86_400
                        if home_last is not None
                        else None
                    ),
                    "away_rest_days": (
                        (kickoff - away_last).total_seconds() / 86_400
                        if away_last is not None
                        else None
                    ),
                    "max_feature_source_kickoff": (
                        max(prior_dates).isoformat() if prior_dates else None
                    ),
                    "feature_policy": "STRICTLY_PRIOR_ROLLING_NO_TARGET_ROW",
                    "deep_player_features": "BLOCKED_BY_SOURCE",
                    "deep_lineup_features": "BLOCKED_BY_SOURCE",
                }
            )

        home_points = 3.0 if home_goals > away_goals else 1.0 if home_goals == away_goals else 0.0
        away_points = 3.0 if away_goals > home_goals else 1.0 if home_goals == away_goals else 0.0
        home_observation = (kickoff, home_points, home_goals - away_goals)
        away_observation = (kickoff, away_points, away_goals - home_goals)
        overall.setdefault(home_key, []).append(home_observation)
        overall.setdefault(away_key, []).append(away_observation)
        home_history.setdefault(home_key, []).append(home_observation)
        away_history.setdefault(away_key, []).append(away_observation)

    return output[-maximum_rows:]


def _latest_mapping(ledger: DurableRuntimeLedger, category: str) -> dict[str, object]:
    return dict(_mapping(ledger.latest_value(category)))


def _value_code_revision(value: object) -> str | None:
    mapped = _mapping(value)
    direct = mapped.get("code_revision")
    if isinstance(direct, str) and direct:
        return direct
    revisions: set[str] = set()
    for item in mapped.values():
        child = _mapping(item)
        child_revision = child.get("code_revision")
        provenance_revision = _mapping(child.get("provenance")).get(
            "code_revision"
        )
        for candidate in (child_revision, provenance_revision):
            if isinstance(candidate, str) and candidate:
                revisions.add(candidate)
    return next(iter(revisions)) if len(revisions) == 1 else None


def _value_run_token(value: object) -> str | None:
    mapped = _mapping(value)
    direct = mapped.get("run_token")
    if isinstance(direct, str) and direct:
        return direct
    tokens: set[str] = set()
    for item in mapped.values():
        child = _mapping(item)
        child_token = child.get("run_token")
        provenance_token = _mapping(child.get("provenance")).get("run_token")
        for candidate in (child_token, provenance_token):
            if isinstance(candidate, str) and candidate:
                tokens.add(candidate)
    return next(iter(tokens)) if len(tokens) == 1 else None


def _latest_mapping_for_revision(
    ledger: DurableRuntimeLedger,
    category: str,
    code_revision: str,
) -> dict[str, object]:
    candidates = [
        envelope
        for envelope in ledger.values(category)
        if _value_code_revision(envelope.get("value")) == code_revision
    ]
    if not candidates:
        return {}
    latest = max(candidates, key=lambda item: str(item.get("recorded_at", "")))
    return dict(_mapping(latest.get("value")))


def _workflow_attempt_lineage(run_token: str) -> tuple[str, int] | None:
    run_id, separator, raw_attempt = run_token.rpartition(":")
    if (
        separator != ":"
        or not run_id.isdigit()
        or not raw_attempt.isdigit()
        or int(raw_attempt) < 1
    ):
        return None
    return run_id, int(raw_attempt)


def _latest_mapping_for_lineage(
    ledger: DurableRuntimeLedger,
    category: str,
    code_revision: str,
    run_token: str,
) -> dict[str, object]:
    revision_candidates = [
        envelope
        for envelope in ledger.values(category)
        if _value_code_revision(envelope.get("value")) == code_revision
    ]
    candidates = [
        envelope
        for envelope in revision_candidates
        if _value_run_token(envelope.get("value")) == run_token
    ]
    if not candidates:
        current_lineage = _workflow_attempt_lineage(run_token)
        if current_lineage is not None:
            current_run_id, current_attempt = current_lineage
            fallback_candidates: list[tuple[int, Mapping[str, object]]] = []
            for envelope in revision_candidates:
                candidate_token = _value_run_token(envelope.get("value"))
                if candidate_token is None:
                    continue
                candidate_lineage = _workflow_attempt_lineage(candidate_token)
                if candidate_lineage is None:
                    continue
                candidate_run_id, candidate_attempt = candidate_lineage
                if (
                    candidate_run_id == current_run_id
                    and candidate_attempt < current_attempt
                ):
                    fallback_candidates.append((candidate_attempt, envelope))
            if fallback_candidates:
                highest_attempt = max(attempt for attempt, _ in fallback_candidates)
                candidates = [
                    envelope
                    for attempt, envelope in fallback_candidates
                    if attempt == highest_attempt
                ]
    if not candidates:
        return {}
    latest = max(candidates, key=lambda item: str(item.get("recorded_at", "")))
    return dict(_mapping(latest.get("value")))


def _run_report(
    *,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
) -> dict[str, object]:
    expected_analysis = ("replay", "quality", "features", "backtest")
    analysis_statuses = {
        phase: _latest_mapping_for_lineage(
            ledger,
            f"analysis/status/{phase}",
            code_revision,
            run_token,
        )
        for phase in expected_analysis
    }
    fatal_errors: list[str] = []
    partial_reasons: list[str] = []
    for phase, status in analysis_statuses.items():
        if not status:
            partial_reasons.append(
                f"ANALYSIS_{phase.upper()}_MISSING_FOR_LINEAGE"
            )
            continue
        outcome = str(status.get("status", "UNKNOWN")).upper()
        reason = str(status.get("reason_class") or "UNSPECIFIED")
        if outcome == "FAILED":
            fatal_errors.append(f"ANALYSIS_{phase.upper()}_FAILED:{reason}")
        elif outcome != "COMPLETE":
            partial_reasons.append(
                f"ANALYSIS_{phase.upper()}_{outcome}:{reason}"
            )

    replay = _latest_mapping_for_lineage(
        ledger,
        "replay",
        code_revision,
        run_token,
    )
    quality = _latest_mapping_for_lineage(
        ledger,
        "quality",
        code_revision,
        run_token,
    )
    datasets = _latest_mapping_for_lineage(
        ledger,
        "dataset-manifests",
        code_revision,
        run_token,
    )
    gates = _latest_mapping_for_lineage(
        ledger,
        "gates",
        code_revision,
        run_token,
    )
    backtest = _latest_mapping_for_lineage(
        ledger,
        "backtest",
        code_revision,
        run_token,
    )
    provider = _latest_mapping_for_lineage(
        ledger,
        "provider/status",
        code_revision,
        run_token,
    )
    for phase, evidence in (
        ("REPLAY", replay),
        ("QUALITY", quality),
        ("DATASETS", datasets),
        ("GATES", gates),
        ("BACKTEST", backtest),
    ):
        if not evidence:
            partial_reasons.append(f"{phase}_EVIDENCE_MISSING_FOR_LINEAGE")
    replay_hash = replay.get("replay_hash")
    quality_replay_hash = quality.get("source_replay_hash")
    if replay_hash and quality_replay_hash and replay_hash != quality_replay_hash:
        fatal_errors.append("LINEAGE_QUALITY_REPLAY_HASH_MISMATCH")
    elif replay_hash and not quality_replay_hash:
        partial_reasons.append("LINEAGE_QUALITY_REPLAY_HASH_MISSING")
    for name, value in datasets.items():
        manifest_replay_hash = _mapping(
            _mapping(value).get("provenance")
        ).get("replay_hash")
        if replay_hash and manifest_replay_hash != replay_hash:
            fatal_errors.append(
                f"LINEAGE_DATASET_REPLAY_HASH_MISMATCH:{name}"
            )
        if _mapping(value).get("row_count", 0) in (0, None):
            partial_reasons.append(f"DATASET_EMPTY:{name}")
    for name, value in gates.items():
        gate_status = str(_mapping(value).get("status", "UNKNOWN"))
        if gate_status not in {"READY_STRICT", "READY_RECONSTRUCTED"}:
            partial_reasons.append(f"GATE_{name}_{gate_status}")
    if not provider:
        partial_reasons.append("PROVIDER_STATUS_MISSING_FOR_LINEAGE")
    if replay.get("payloads_replayed", 0) in (0, None):
        partial_reasons.append("REPLAY_HAS_NO_PAYLOADS")

    report = build_historical_deep_report(
        replay=replay,
        quality=quality,
        datasets=datasets,
        gates=gates,
        backtest=backtest,
        provider=provider,
        fatal_errors=tuple(sorted(set(fatal_errors))),
        partial_reasons=tuple(sorted(set(partial_reasons))),
        campaign_id=contract.campaign_id,
    )
    report["code_revision"] = code_revision
    report["run_token"] = run_token
    report["analysis_statuses"] = analysis_statuses
    continuation = _latest_mapping_for_lineage(
        ledger,
        "continuation/lineage",
        code_revision,
        run_token,
    )
    continuation_id = continuation.get("continuation_id")
    report["continuation"] = continuation
    usage_category = (
        f"mission/continuations/{continuation_id}/usage"
        if isinstance(continuation_id, str) and continuation_id
        else "mission/usage"
    )
    mission_usage = _latest_mapping_for_lineage(
        ledger,
        usage_category,
        code_revision,
        run_token,
    )
    collection_progress = {
        lane: [
            dict(_mapping(envelope.get("value")))
            for envelope in ledger.values(f"progress/{lane}")
            if _value_code_revision(envelope.get("value")) == code_revision
            and _value_run_token(envelope.get("value")) == run_token
        ]
        for lane in ("fixtures", "players", "injuries")
    }
    storage_metrics = ledger.evidence_metrics()
    mission_started_raw = mission_usage.get("mission_started_at")
    mission_started = (
        datetime.fromisoformat(str(mission_started_raw))
        if mission_started_raw is not None
        else None
    )
    duration_seconds = (
        max(
            0.0,
            (
                _aware_now(services)
                - (
                    mission_started.replace(tzinfo=UTC)
                    if mission_started is not None
                    and (
                        mission_started.tzinfo is None
                        or mission_started.utcoffset() is None
                    )
                    else mission_started
                )
            ).total_seconds(),
        )
        if mission_started is not None
        else None
    )
    mission_calls_raw = mission_usage.get("mission_calls_used", 0)
    mission_calls = (
        int(mission_calls_raw)
        if isinstance(mission_calls_raw, int)
        and not isinstance(mission_calls_raw, bool)
        else 0
    )
    batches_completed = sum(
        str(item.get("status", "")).upper() == "COMPLETE"
        for values in collection_progress.values()
        for item in values
    )
    report["operations"] = {
        "provider": provider,
        "mission_usage": mission_usage,
        "coverage_census": _latest_mapping_for_lineage(
            ledger,
            "collection/census",
            code_revision,
            run_token,
        ),
        "collection_summaries": {
            command: _latest_mapping_for_lineage(
                ledger,
                f"collection/{command}",
                code_revision,
                run_token,
            )
            for command in sorted(COLLECTION_COMMANDS)
        },
        "collection_progress": collection_progress,
        "time_and_calls": {
            "duration_seconds": duration_seconds,
            "provider_calls": mission_calls,
            "requests_per_second_average": (
                mission_calls / duration_seconds
                if duration_seconds is not None and duration_seconds > 0
                else None
            ),
            "errors": storage_metrics.get("task_errors"),
            "retries": storage_metrics.get("retries_in_receipts"),
            "batches_completed": batches_completed,
            "tasks_remaining": storage_metrics.get("tasks_remaining"),
            "eta_seconds": None,
        },
        "storage": storage_metrics,
        "features": compact_artifact(
            _latest_mapping_for_lineage(
                ledger,
                "features",
                code_revision,
                run_token,
            )
        ),
        "genome": _latest_mapping_for_lineage(
            ledger,
            "genome",
            code_revision,
            run_token,
        ),
        "code_revision": code_revision,
        "run_token": run_token,
    }
    safety = dict(_mapping(report.get("safety")))
    safety.update(
        {
            "new_purchases": False,
            "secrets_exposed": False,
            "r2_deletions": 0,
            "raw_payloads_in_git": 0,
            "the_odds_api_historical_credits": 0,
            "social_publications": 0,
            "model_promotions": 0,
        }
    )
    report["safety"] = safety
    report.pop("report_hash", None)
    report["report_hash"] = canonical_sha256(report)
    rendered_json = render_report_json(report)
    rendered_markdown = render_report_markdown(report)
    recorded_at = _aware_now(services)
    report["durable_keys"] = {
        "report": ledger.put_json("report", report, recorded_at=recorded_at),
        "rendered": ledger.put_json(
            "report/rendered",
            {
                "code_revision": code_revision,
                "run_token": run_token,
                "json": rendered_json,
                "markdown": rendered_markdown,
            },
            recorded_at=recorded_at,
        ),
    }
    return report


def _plan(
    args: argparse.Namespace,
    contract: CampaignContract,
) -> dict[str, object]:
    priority = getattr(args, "priority", None)
    seasons: object = None
    if priority == "P0":
        seasons = list(contract.season_priorities.P0)
    elif priority == "P1":
        seasons = list(contract.season_priorities.P1)
    elif priority in {"P2", "auto"}:
        seasons = "R2_VERIFIED_COVERAGE_REQUIRED"
    return {
        "schema_version": "historical-deep-run-plan-v1",
        "status": "PLANNED_NOT_EXECUTED",
        "command": args.command,
        "execute": False,
        "campaign_id": contract.campaign_id,
        "contract_hash": contract.contract_hash,
        "competitions": len(contract.competitions),
        "priority": priority,
        "seasons": seasons,
        "max_calls": getattr(args, "max_calls", None),
        "max_duration_minutes": getattr(args, "max_duration_minutes", None),
        "mission_max_minutes": getattr(args, "mission_max_minutes", None),
        "provider_calls": 0,
        "durable_writes": 0,
    }


def _early_collection_stop(
    *,
    args: argparse.Namespace,
    ledger: DurableRuntimeLedger,
    services: RunnerServices,
    run_token: str,
    reason: str,
) -> dict[str, object]:
    recorded_at = _aware_now(services)
    result: dict[str, object] = {
        "schema_version": "historical-deep-bounded-run-v1",
        "status": "PARTIAL",
        "reason": reason,
        "provider_calls": 0,
        "tasks_completed": 0,
        "resume": "R2_RECEIPTS_AND_CHECKPOINT",
        "code_revision": args.code_revision,
        "run_token": run_token,
    }
    ledger.checkpoint(
        phase=args.command,
        status="PARTIAL",
        provider_calls=0,
        tasks_completed=0,
        started_at=recorded_at,
        recorded_at=recorded_at,
        reason=reason,
    )
    result["durable_key"] = ledger.put_json(
        f"collection/{args.command}",
        result,
        recorded_at=recorded_at,
    )
    return result


def _collection_run(
    *,
    args: argparse.Namespace,
    environment: Mapping[str, str],
    services: RunnerServices,
    store: ObjectStoreType,
    repository: R2FirstRepository,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    run_token: str,
) -> dict[str, object]:
    api_key = environment.get("API_FOOTBALL_KEY", "").strip()
    if not api_key:
        recorded_at = _aware_now(services)
        reason_class = "API_FOOTBALL_KEY_REQUIRED"
        ledger.put_json(
            "provider/status",
            {
                "schema_version": "historical-deep-provider-block-v1",
                "status": "BLOCKED_PROVIDER",
                "reason_class": reason_class,
                "checked_at": recorded_at,
                "provider_calls": 0,
                "code_revision": args.code_revision,
                "run_token": run_token,
            },
            recorded_at=recorded_at,
        )
        result: dict[str, object] = {
            "status": "BLOCKED_PROVIDER",
            "reason": reason_class,
            "provider_calls": 0,
            "code_revision": args.code_revision,
            "run_token": run_token,
        }
        result["durable_key"] = ledger.put_json(
            f"collection/{args.command}",
            result,
            recorded_at=recorded_at,
        )
        return result
    checked_at = _aware_now(services)
    mission_started_at = ledger.continuation_start(
        continuation_id=args.continuation_id,
        continuation_of=args.continuation_of,
        run_purpose=args.run_purpose,
        now=checked_at,
        code_revision=args.code_revision,
        maximum_minutes=args.mission_max_minutes,
    )
    usage_category = f"mission/continuations/{args.continuation_id}/usage"
    if not ledger.mission_has_time(
        now=checked_at,
        started_at=mission_started_at,
        maximum_minutes=args.mission_max_minutes,
    ):
        return _early_collection_stop(
            args=args,
            ledger=ledger,
            services=services,
            run_token=run_token,
            reason="GLOBAL_MISSION_720_MINUTES_REACHED",
        )
    persisted_calls = _persisted_mission_calls(
        ledger,
        mission_started_at=mission_started_at,
        mission_call_cap=contract.quota.mission_call_cap,
        usage_category=usage_category,
    )
    status_call_reservation = contract.quota.max_retries + 1
    if status_call_reservation > args.max_calls:
        return _early_collection_stop(
            args=args,
            ledger=ledger,
            services=services,
            run_token=run_token,
            reason="JOB_PROVIDER_CALL_LIMIT_BELOW_STATUS_PROOF_RESERVATION",
        )
    if (
        persisted_calls + status_call_reservation
        > contract.quota.mission_call_cap
    ):
        return _early_collection_stop(
            args=args,
            ledger=ledger,
            services=services,
            run_token=run_token,
            reason="GLOBAL_MISSION_CALL_CAP_REACHED",
        )
    limits = ExecutionLimits(
        phase=args.command,
        ledger=ledger,
        now=services.now,
        monotonic=services.monotonic,
        job_started_at=checked_at,
        mission_started_at=mission_started_at,
        maximum_calls=args.max_calls,
        maximum_minutes=args.max_duration_minutes,
        mission_maximum_minutes=args.mission_max_minutes,
        checkpoint_calls=min(
            CHECKPOINT_MAX_CALLS,
            contract.quota.checkpoint_max_calls,
        ),
        checkpoint_minutes=min(
            CHECKPOINT_MAX_MINUTES,
            contract.quota.checkpoint_max_minutes,
        ),
        provider_calls=status_call_reservation,
        mission_calls_used=persisted_calls + status_call_reservation,
        mission_call_cap=contract.quota.mission_call_cap,
        code_revision=args.code_revision,
        run_token=run_token,
        usage_category=usage_category,
    )
    # Crash-safe conservative accounting: reserve every possible /status retry
    # durably before making the first network attempt.
    limits.persist_mission_usage(recorded_at=checked_at)

    result = {}
    base_quota: QuotaController | None = None
    try:
        client = services.provider_factory(api_key)
        status = client.get_status()
        status_checked_at = _aware_now(services)
        if not status.is_fresh(status_checked_at):
            raise RunnerBlocked("PROVIDER_STATUS_PROOF_EXPIRED")
        ledger.put_json(
            "provider/status",
            _provider_status_proof(status, limits=limits),
            recorded_at=status_checked_at,
        )
        if status.daily_remaining <= max(20_000, int(status.daily_limit * 0.2)):
            raise RunnerBlocked("PROVIDER_PROTECTED_RESERVE_REACHED")

        candidate_quota = client.quota
        if isinstance(candidate_quota, QuotaController):
            base_quota = candidate_quota
        else:
            base_quota = QuotaController(
                status,
                sleeper=lambda _seconds: None,
                clock=services.monotonic,
                now=services.now,
            )
        cast(Any, client).quota = CappedQuota(base_quota, limits)
        collector = _new_collector(
            client,
            repository,
            contract=contract,
            code_revision=args.code_revision,
            services=services,
        )
        if args.command == "census":
            result = _run_census(
                collector=collector,
                provider=client,
                repository=repository,
                ledger=ledger,
                contract=contract,
                limits=limits,
                code_revision=args.code_revision,
                services=services,
            )
        elif args.command == "fixtures":
            result = _run_fixture_collection(
                collector=collector,
                ledger=ledger,
                contract=contract,
                limits=limits,
                priority=args.priority,
            )
        elif args.command == "players":
            result = _run_player_collection(
                collector=collector,
                ledger=ledger,
                contract=contract,
                limits=limits,
                priority=args.priority,
            )
        elif args.command == "injuries":
            result = _run_injury_collection(
                collector=collector,
                ledger=ledger,
                contract=contract,
                limits=limits,
                priority=args.priority,
            )
        else:
            raise ValueError(f"RUNNER_COLLECTION_COMMAND_UNKNOWN:{args.command}")
    except (ProviderAuthenticationError, ProviderStatusError) as error:
        reason_class = type(error).__name__
        ledger.put_json(
            "provider/status",
            {
                "schema_version": "historical-deep-provider-block-v1",
                "status": "BLOCKED_PROVIDER",
                "reason_class": reason_class,
                "checked_at": _aware_now(services),
                "provider_calls": limits.provider_calls,
                "code_revision": args.code_revision,
                "run_token": run_token,
            },
            recorded_at=_aware_now(services),
        )
        result = {
            "schema_version": "historical-deep-bounded-run-v1",
            "status": "BLOCKED_PROVIDER",
            "reason": reason_class,
            "provider_calls": limits.provider_calls,
            "tasks_completed": limits.tasks_completed,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
        }
    except ProviderError as error:
        result = {
            "schema_version": "historical-deep-bounded-run-v1",
            "status": "PARTIAL",
            "reason": type(error).__name__,
            "provider_calls": limits.provider_calls,
            "tasks_completed": limits.tasks_completed,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
        }
    except (RunnerBlocked, QuotaExhaustedError) as error:
        result = {
            "schema_version": "historical-deep-bounded-run-v1",
            "status": "PARTIAL",
            "reason": str(error),
            "provider_calls": limits.provider_calls,
            "tasks_completed": limits.tasks_completed,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
        }
    if base_quota is not None and result.get("status") != "BLOCKED_PROVIDER":
        ledger.put_json(
            "provider/status",
            _provider_status_proof(base_quota.status, limits=limits),
            recorded_at=_aware_now(services),
        )
    result["code_revision"] = args.code_revision
    result["run_token"] = run_token
    limits.checkpoint_if_due(
        force=True,
        status=str(result.get("status", "PARTIAL")),
        reason=(
            str(result.get("reason"))
            if result.get("reason") is not None
            else None
        ),
    )
    result["durable_key"] = ledger.put_json(
        f"collection/{args.command}",
        result,
        recorded_at=_aware_now(services),
    )
    return result


def _compact_result_projection(result: Mapping[str, object]) -> dict[str, object]:
    """Keep workflow artifacts diagnostic but never row- or payload-heavy."""

    scalar_fields = (
        "schema_version",
        "status",
        "verdict",
        "code_revision",
        "run_token",
        "reason",
        "provider_calls",
        "provider_credits",
        "tasks_completed",
        "resume",
        "durable_key",
        "discovery_key",
        "input_key",
        "input_status",
        "input_rows",
        "evaluated_folds",
        "cache_only",
        "promotion",
        "production_status",
        "real_bets",
        "no_bet_default",
        "mode_separation_verified",
        "hash",
        "report_hash",
        "feature_hash",
    )
    projection = {
        field_name: compact_artifact(result[field_name])
        for field_name in scalar_fields
        if field_name in result
    }
    for field_name in (
        "observations",
        "results",
        "missing_inventory",
        "bundles",
        "errors",
        "fatal_errors",
        "partial_reasons",
    ):
        value = result.get(field_name)
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            projection[f"{field_name}_count"] = len(value)
            if field_name in {"fatal_errors", "partial_reasons"}:
                projection[field_name] = [str(item) for item in value]

    discovery = _mapping(result.get("discovery"))
    competitions = _mapping(discovery.get("competitions"))
    if competitions:
        projection["discovered_competitions"] = len(competitions)

    datasets = _mapping(
        result.get("datasets", result.get("dataset_manifests"))
    )
    if datasets:
        dataset_summaries: dict[str, object] = {}
        for name, value in sorted(datasets.items()):
            manifest = _mapping(value)
            if manifest:
                dataset_summaries[str(name)] = {
                    field_name: compact_artifact(manifest[field_name])
                    for field_name in (
                        "row_count",
                        "fixture_count",
                        "dataset_hash",
                        "provenance_hash",
                        "cutoff_policy",
                        "allowed_usages",
                        "features",
                        "null_counts",
                        "null_count",
                        "null_rate",
                        "temporal_classes",
                        "temporal_class_counts",
                        "normalized_family_counts",
                    )
                    if field_name in manifest
                }
            else:
                dataset_summaries[str(name)] = {
                    "row_count": len(_sequence(value))
                }
        projection["datasets"] = dataset_summaries
        projection["dataset_row_counts"] = {
            name: _mapping(summary).get("row_count", 0)
            for name, summary in dataset_summaries.items()
        }
    manifests = _mapping(result.get("dataset_manifests"))
    if manifests:
        projection["dataset_manifest_count"] = len(manifests)

    gate_value = result.get("gate_summary")
    if isinstance(gate_value, Mapping):
        projection["gate_summary"] = compact_artifact(gate_value)
    gates = _mapping(result.get("gates"))
    if gates:
        statuses: dict[str, int] = {}
        gate_summaries: dict[str, object] = {}
        for gate in gates.values():
            status = str(_mapping(gate).get("status", "UNKNOWN"))
            statuses[status] = statuses.get(status, 0) + 1
        for name, value in sorted(gates.items()):
            gate = _mapping(value)
            gate_summaries[str(name)] = {
                "status": gate.get("status", "UNKNOWN"),
                "eligible_seasons": compact_artifact(
                    gate.get("eligible_seasons", ())
                ),
                "reasons": compact_artifact(gate.get("reasons", ())),
            }
        projection["gate_status_counts"] = statuses
        projection["gates"] = gate_summaries

    backtest = _mapping(result.get("backtest"))
    modes = _mapping(result.get("modes", backtest.get("modes")))
    if modes:
        mode_summaries: dict[str, object] = {}
        for name, value in sorted(modes.items()):
            mode = _mapping(value)
            summary = {
                field_name: mode[field_name]
                for field_name in (
                    "rows",
                    "predictive_evaluation",
                    "walk_forward",
                    "bets",
                    "roi",
                    "promotion",
                    "reason",
                )
                if field_name in mode
            }
            summary["fold_count"] = len(_sequence(mode.get("folds")))
            mode_summaries[str(name)] = summary
        projection["modes"] = mode_summaries

    provider = _mapping(result.get("provider"))
    if provider:
        projection["provider"] = {
            field_name: compact_artifact(provider[field_name])
            for field_name in (
                "status",
                "plan",
                "active",
                "subscription_end",
                "daily_limit",
                "daily_used",
                "daily_remaining",
                "quota_remaining",
                "mandatory_reserve",
                "mission_available",
                "mission_calls_reserved_high_water",
                "mission_remaining",
                "code_revision",
                "run_token",
                "reason_class",
            )
            if field_name in provider
        }

    replay = _mapping(
        result.get(
            "replay",
            result if "payloads_replayed" in result else None,
        )
    )
    if replay:
        projection["replay"] = {
            field_name: compact_artifact(replay[field_name])
            for field_name in (
                "status",
                "payloads_replayed",
                "receipts_verified",
                "hash_mismatches",
                "missing_payloads",
                "extra_payloads",
                "source_hash",
                "replay_hash",
                "hash_identical",
                "normalized_rows",
                "normalized_projection_hash",
                "provider_calls",
                "provider_credits",
                "code_revision",
                "run_token",
            )
            if field_name in replay
        }

    quality = _mapping(result.get("quality_v2", result.get("quality")))
    if quality:
        mismatches = _sequence(quality.get("mismatches"))
        normalization_errors = _sequence(quality.get("normalization_errors"))
        projection["quality"] = {
            "exact_replay": quality.get("exact_replay", False),
            "before_hash": quality.get("before_hash"),
            "after_hash": quality.get("after_hash"),
            "mismatch_count": len(mismatches),
            "null_to_zero_conversions": quality.get(
                "null_to_zero_conversions",
                0,
            ),
            "normalization_error_count": len(normalization_errors),
            "normalized_rows": quality.get("normalized_rows", 0),
            "targeted_rows": quality.get("targeted_rows", 0),
            "code_revision": quality.get("code_revision"),
            "run_token": quality.get("run_token"),
        }

    if backtest:
        projection["backtest"] = {
            field_name: compact_artifact(backtest[field_name])
            for field_name in (
                "status",
                "input_status",
                "input_rows",
                "evaluated_folds",
                "deep_feature_rows",
                "scope_reason",
                "cache_only",
                "mode_separation_verified",
                "multiple_testing_method",
                "promotion",
                "production_status",
                "provider_calls",
                "provider_credits",
                "dataset_hash",
                "code_revision",
                "run_token",
            )
            if field_name in backtest
        }

    operations = _mapping(result.get("operations"))
    if operations:
        mission_usage = _mapping(operations.get("mission_usage"))
        storage = _mapping(operations.get("storage"))
        time_and_calls = _mapping(operations.get("time_and_calls"))
        projection["operations"] = {
            "mission_usage": {
                field_name: compact_artifact(mission_usage[field_name])
                for field_name in (
                    "mission_started_at",
                    "mission_call_cap",
                    "mission_calls_used",
                    "accounting",
                    "last_phase",
                    "code_revision",
                    "run_token",
                )
                if field_name in mission_usage
            },
            "storage": {
                field_name: compact_artifact(storage[field_name])
                for field_name in (
                    "receipts",
                    "payload_objects",
                    "payload_bytes",
                    "stored_bytes",
                    "provider_calls_in_receipts",
                    "attempts_in_receipts",
                    "retries_in_receipts",
                    "rows_normalized_in_receipts",
                    "families",
                    "statuses",
                    "competition_seasons",
                    "hash_mismatches",
                    "hash_verification",
                    "task_events",
                    "tasks",
                    "task_statuses",
                    "tasks_completed",
                    "tasks_remaining",
                    "tasks_blocked",
                    "tasks_failed",
                    "task_errors",
                    "rows_received_in_task_journal",
                    "last_task_heartbeat",
                    "deletions",
                    "raw_payloads_in_git",
                )
                if field_name in storage
            },
            "time_and_calls": {
                field_name: compact_artifact(time_and_calls[field_name])
                for field_name in (
                    "duration_seconds",
                    "provider_calls",
                    "requests_per_second_average",
                    "errors",
                    "retries",
                    "batches_completed",
                    "tasks_remaining",
                    "eta_seconds",
                )
                if field_name in time_and_calls
            },
        }

    analysis_statuses = _mapping(result.get("analysis_statuses"))
    if analysis_statuses:
        projection["analysis_statuses"] = {
            str(name): {
                field_name: compact_artifact(status[field_name])
                for field_name in (
                    "status",
                    "reason_class",
                    "code_revision",
                    "run_token",
                    "result_hash",
                )
                if field_name in status
            }
            for name, value in sorted(analysis_statuses.items())
            for status in (_mapping(value),)
        }

    durable_keys = result.get("durable_keys")
    if isinstance(durable_keys, Mapping):
        projection["durable_keys"] = compact_artifact(durable_keys)
    return projection


def _analysis_outcome(result: Mapping[str, object]) -> str:
    raw = str(result.get("status", result.get("verdict", "UNKNOWN"))).upper()
    if raw == "FAILED" or raw.endswith("_FAILED"):
        return "FAILED"
    if raw == "PARTIAL" or raw.endswith("_PARTIAL"):
        return "PARTIAL"
    if "BLOCKED" in raw:
        return "BLOCKED"
    return "COMPLETE"


def _record_analysis_status(
    *,
    ledger: DurableRuntimeLedger,
    command: str,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
    status: str,
    reason_class: str | None = None,
    result: Mapping[str, object] | None = None,
) -> str:
    value: dict[str, object] = {
        "schema_version": "historical-deep-analysis-status-v1",
        "command": command,
        "status": status,
        "reason_class": reason_class,
        "code_revision": code_revision,
        "run_token": run_token,
    }
    if result is not None:
        value["result_hash"] = canonical_sha256(result)
    return ledger.put_json(
        f"analysis/status/{command}",
        value,
        recorded_at=_aware_now(services),
    )


def _analysis_run(
    *,
    command: str,
    ledger: DurableRuntimeLedger,
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
    services: RunnerServices,
    matches_path: Path,
) -> dict[str, object]:
    if command == "replay":
        return _run_replay(
            ledger=ledger,
            code_revision=code_revision,
            run_token=run_token,
            services=services,
        )
    if command == "quality":
        return _run_quality(
            ledger=ledger,
            contract=contract,
            code_revision=code_revision,
            run_token=run_token,
            services=services,
        )
    if command == "features":
        return _run_features(
            ledger=ledger,
            contract=contract,
            code_revision=code_revision,
            run_token=run_token,
            services=services,
        )
    if command == "backtest":
        return _run_backtest(
            ledger=ledger,
            code_revision=code_revision,
            run_token=run_token,
            services=services,
            matches_path=matches_path,
        )
    if command == "report":
        return _run_report(
            ledger=ledger,
            contract=contract,
            code_revision=code_revision,
            run_token=run_token,
            services=services,
        )
    raise ValueError(f"RUNNER_ANALYSIS_COMMAND_UNKNOWN:{command}")


def _compact_summary(
    *,
    command: str,
    result: Mapping[str, object],
    contract: CampaignContract,
    code_revision: str,
    run_token: str,
) -> dict[str, object]:
    return {
        "schema_version": "historical-deep-runner-artifact-v1",
        "campaign_id": contract.campaign_id,
        "contract_hash": contract.contract_hash,
        "command": command,
        "code_revision": code_revision,
        "run_token": run_token,
        "status": result.get("status", result.get("verdict", "UNKNOWN")),
        "provider_calls": result.get("provider_calls", 0),
        "result": _compact_result_projection(result),
        "result_hash": canonical_sha256(result),
    }


def run(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    services: RunnerServices = DEFAULT_SERVICES,
) -> int:
    args = build_parser().parse_args(argv)
    selected_environment = dict(os.environ if environment is None else environment)
    contract = load_campaign_contract(args.config)
    _validate_arguments(args, contract)
    args.output.mkdir(parents=True, exist_ok=True)
    artifact_path = args.output / f"{args.command}.json"
    ledger: DurableRuntimeLedger | None = None
    selected_run_token = f"LOCAL:{args.code_revision}"

    try:
        selected_run_token = _run_token(
            selected_environment,
            code_revision=args.code_revision,
        )
        assert_safety_locks(selected_environment)
    except (RuntimeError, ValueError) as error:
        failure = {
            "schema_version": "historical-deep-runner-artifact-v1",
            "command": args.command,
            "status": "FAILED",
            "reason": str(error),
            "provider_calls": 0,
            "code_revision": args.code_revision,
            "run_token": selected_run_token,
        }
        write_artifact(artifact_path, failure)
        return 2

    if args.command in COLLECTION_COMMANDS and not args.execute:
        write_artifact(artifact_path, _plan(args, contract))
        return 0
    if (
        args.command in COLLECTION_COMMANDS
        and args.execute
        and args.cache_root is not None
        and services is DEFAULT_SERVICES
    ):
        write_artifact(
            artifact_path,
            {
                "schema_version": "historical-deep-runner-artifact-v1",
                "command": args.command,
                "status": "FAILED",
                "reason": "EXECUTED_COLLECTION_REQUIRES_DURABLE_R2",
                "provider_calls": 0,
            },
        )
        return 2

    try:
        store = services.store_factory(selected_environment, args.cache_root)
        validate_r2_round_trip(store, key=SENTINEL_KEY)
        repository = _new_repository(store, code_revision=args.code_revision)
        # Recovery is task-local on collection lookup.  Analysis must remain
        # read-only over raw evidence and fail closed when a payload has no
        # durable receipt, rather than rewriting every complete capture first.
        ledger = DurableRuntimeLedger(store, campaign_id=contract.campaign_id)
        if args.command in COLLECTION_COMMANDS:
            result = _collection_run(
                args=args,
                environment=selected_environment,
                services=services,
                store=store,
                repository=repository,
                ledger=ledger,
                contract=contract,
                run_token=selected_run_token,
            )
        else:
            result = _analysis_run(
                command=args.command,
                ledger=ledger,
                contract=contract,
                code_revision=args.code_revision,
                run_token=selected_run_token,
                services=services,
                matches_path=args.matches_path,
            )
            _record_analysis_status(
                ledger=ledger,
                command=args.command,
                code_revision=args.code_revision,
                run_token=selected_run_token,
                services=services,
                status=_analysis_outcome(result),
                reason_class=(
                    str(result.get("reason"))
                    if result.get("reason") is not None
                    else None
                ),
                result=result,
            )
        summary = _compact_summary(
            command=args.command,
            result=result,
            contract=contract,
            code_revision=args.code_revision,
            run_token=selected_run_token,
        )
        write_artifact(artifact_path, summary)
        print(json.dumps({"command": args.command, "status": summary["status"]}))
        return 0
    except (ProviderAuthenticationError, ProviderStatusError) as error:
        if ledger is not None and args.command in ANALYSIS_COMMANDS:
            _record_analysis_status(
                ledger=ledger,
                command=args.command,
                code_revision=args.code_revision,
                run_token=selected_run_token,
                services=services,
                status="FAILED",
                reason_class=type(error).__name__,
            )
        blocked = {
            "schema_version": "historical-deep-runner-artifact-v1",
            "command": args.command,
            "status": "BLOCKED_PROVIDER",
            "reason": type(error).__name__,
            "provider_calls": 0,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
            "code_revision": args.code_revision,
            "run_token": selected_run_token,
        }
        write_artifact(artifact_path, blocked)
        return 0
    except (ProviderError, QuotaExhaustedError, RunnerBlocked) as error:
        if ledger is not None and args.command in ANALYSIS_COMMANDS:
            _record_analysis_status(
                ledger=ledger,
                command=args.command,
                code_revision=args.code_revision,
                run_token=selected_run_token,
                services=services,
                status="FAILED",
                reason_class=type(error).__name__,
            )
        partial = {
            "schema_version": "historical-deep-runner-artifact-v1",
            "command": args.command,
            "status": "PARTIAL",
            "reason": type(error).__name__,
            "provider_calls": 0,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
            "code_revision": args.code_revision,
            "run_token": selected_run_token,
        }
        write_artifact(artifact_path, partial)
        return 0
    except (PayloadIntegrityError, ValueError, TypeError) as error:
        if ledger is not None and args.command in ANALYSIS_COMMANDS:
            _record_analysis_status(
                ledger=ledger,
                command=args.command,
                code_revision=args.code_revision,
                run_token=selected_run_token,
                services=services,
                status="FAILED",
                reason_class=type(error).__name__,
            )
        failed = {
            "schema_version": "historical-deep-runner-artifact-v1",
            "command": args.command,
            "status": "FAILED",
            "reason": type(error).__name__,
            "provider_calls": 0,
            "code_revision": args.code_revision,
            "run_token": selected_run_token,
        }
        write_artifact(artifact_path, failed)
        return 2


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
