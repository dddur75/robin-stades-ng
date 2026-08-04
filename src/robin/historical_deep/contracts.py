"""Fail-closed contracts for Historical Deep Data Harvest V1."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

CAMPAIGN_SCHEMA_VERSION = "historical-deep-data-harvest-v1"
R2_NAMESPACE = "historical-deep-data/schema-v1"
DEFAULT_CAMPAIGN_CONTRACT_PATH = Path(
    "configs/historical-deep-data-harvest-v1.json"
)

JsonScalar = str | int | float | bool | None

_SENSITIVE_PARAMETER_NAMES = frozenset(
    {
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "x-apisports-key",
    }
)


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STALE_RETRYABLE = "STALE_RETRYABLE"
    COMPLETE = "COMPLETE"
    EMPTY_VALID = "EMPTY_VALID"
    RETRYABLE = "RETRYABLE"
    BLOCKED_COVERAGE = "BLOCKED_COVERAGE"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    FAILED = "FAILED"


class TemporalClass(StrEnum):
    STATIC_PROFILE = "STATIC_PROFILE"
    EVENT_TIME_USABLE = "EVENT_TIME_USABLE"
    PRIOR_MATCH_USABLE = "PRIOR_MATCH_USABLE"
    POST_LINEUP_RECONSTRUCTED = "POST_LINEUP_RECONSTRUCTED"
    POST_MATCH_ONLY = "POST_MATCH_ONLY"
    ANNOUNCEMENT_TIME_UNKNOWN = "ANNOUNCEMENT_TIME_UNKNOWN"
    SEASON_FINAL_AGGREGATE = "SEASON_FINAL_AGGREGATE"
    PROSPECTIVE_POINT_IN_TIME = "PROSPECTIVE_POINT_IN_TIME"
    HISTORICAL_INTERVAL_RECONSTRUCTED = "HISTORICAL_INTERVAL_RECONSTRUCTED"
    FIXTURE_SPECIFIC_POST_HOC = "FIXTURE_SPECIFIC_POST_HOC"


class GateStatus(StrEnum):
    READY_STRICT = "READY_STRICT"
    READY_RECONSTRUCTED = "READY_RECONSTRUCTED"
    PARTIAL = "PARTIAL"
    BLOCKED_BY_COVERAGE = "BLOCKED_BY_COVERAGE"
    BLOCKED_BY_TEMPORALITY = "BLOCKED_BY_TEMPORALITY"
    BLOCKED_BY_SOURCE = "BLOCKED_BY_SOURCE"


class HarvestVerdict(StrEnum):
    READY = "HISTORICAL_DEEP_DATA_HARVEST_READY"
    PARTIAL = "HISTORICAL_DEEP_DATA_HARVEST_PARTIAL"
    BLOCKED_BY_PROVIDER = "HISTORICAL_DEEP_DATA_HARVEST_BLOCKED_BY_PROVIDER"
    FAILED = "HISTORICAL_DEEP_DATA_HARVEST_FAILED"


class DatasetName(StrEnum):
    TEAM_PREMATCH_STRICT = "TEAM_PREMATCH_STRICT"
    PLAYER_PREMATCH_STRICT = "PLAYER_PREMATCH_STRICT"
    LINEUP_HISTORY_PREMATCH_STRICT = "LINEUP_HISTORY_PREMATCH_STRICT"
    TARGET_POST_LINEUP_RECONSTRUCTED = "TARGET_POST_LINEUP_RECONSTRUCTED"
    INJURY_INTERVAL_RECONSTRUCTED = "INJURY_INTERVAL_RECONSTRUCTED"
    POST_MATCH_DESCRIPTIVE = "POST_MATCH_DESCRIPTIVE"


class DataFamily(StrEnum):
    FIXTURES = "fixtures"
    EVENTS = "events"
    LINEUPS = "lineups"
    LINEUP_PLAYERS = "lineup_players"
    FORMATIONS = "formations"
    TEAM_MATCH_STATISTICS = "team_match_statistics"
    PLAYER_MATCH_STATISTICS = "player_match_statistics"
    REFEREES = "referees"
    VENUES = "venues"
    TEAMS = "teams"
    STANDINGS = "standings"
    ROUNDS = "rounds"
    PLAYERS = "players"
    PLAYER_SEASON_STATISTICS = "player_season_statistics"
    INJURIES = "injuries"
    SUSPENSIONS = "suspensions"
    CAREERS = "careers"
    TRANSFERS = "transfers"
    SIDELINED_PERIODS = "sidelined_periods"
    COACHES = "coaches"
    TROPHIES = "trophies"
    OTHER_PROFILES = "other_profiles"


def ensure_utc(value: datetime, *, field: str) -> datetime:
    """Return an aware UTC value or reject the contract."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return value.astimezone(UTC)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON deterministically and reject NaN/infinity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class CompetitionSpec(FrozenContract):
    canonical_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    provider_league_id: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_canonical_key(self) -> Self:
        if self.canonical_key != f"api-football:{self.provider_league_id}":
            raise ValueError("COMPETITION_CANONICAL_KEY_LEAGUE_ID_MISMATCH")
        return self


class SubscriptionRequirements(FrozenContract):
    plan: Literal["Mega"]
    active: Literal[True]


class SeasonPriorities(FrozenContract):
    P0: tuple[int, ...]
    P1: tuple[int, ...]
    P2: Literal["all_older_seasons_with_verified_coverage"]
    P3: Literal["expensive_secondary_families_after_P0_and_P1"]

    @model_validator(mode="after")
    def validate_seasons(self) -> Self:
        if not self.P0 or not self.P1:
            raise ValueError("HARVEST_PRIORITY_SEASONS_REQUIRED")
        if any(season < 1888 or season > 2100 for season in (*self.P0, *self.P1)):
            raise ValueError("HARVEST_SEASON_OUT_OF_RANGE")
        if len(set(self.P0)) != len(self.P0) or len(set(self.P1)) != len(self.P1):
            raise ValueError("HARVEST_PRIORITY_SEASONS_DUPLICATED")
        if set(self.P0) & set(self.P1):
            raise ValueError("HARVEST_PRIORITY_SEASONS_OVERLAP")
        return self


class FamilyPriorities(FrozenContract):
    P0: tuple[DataFamily, ...]
    P3: tuple[DataFamily, ...]

    @model_validator(mode="after")
    def validate_families(self) -> Self:
        if not self.P0 or not self.P3:
            raise ValueError("HARVEST_PRIORITY_FAMILIES_REQUIRED")
        if len(set(self.P0)) != len(self.P0) or len(set(self.P3)) != len(self.P3):
            raise ValueError("HARVEST_PRIORITY_FAMILIES_DUPLICATED")
        if set(self.P0) & set(self.P3):
            raise ValueError("HARVEST_PRIORITY_FAMILIES_OVERLAP")
        if set((*self.P0, *self.P3)) != set(DataFamily):
            raise ValueError("HARVEST_PRIORITY_FAMILIES_NOT_EXHAUSTIVE")
        return self


class QuotaSpec(FrozenContract):
    daily_limit_source: Literal["provider_status_and_headers"]
    daily_remaining_source: Literal["provider_status_and_headers"]
    mandatory_reserve_minimum: Literal[20000]
    mandatory_reserve_fraction: float = Field(ge=0.2, le=0.2)
    mission_call_cap: Literal[90000]
    initial_requests_per_second: Literal[8]
    initial_requests_per_minute: Literal[480]
    max_retries: Literal[3]
    checkpoint_max_calls: int = Field(gt=0, le=500)
    checkpoint_max_minutes: int = Field(gt=0, le=20)


class BundlePilotSpec(FrozenContract):
    preferred_competition: str = Field(min_length=1, max_length=120)
    preferred_season: int = Field(ge=1888, le=2100)
    candidate_sizes: tuple[int, ...]

    @model_validator(mode="after")
    def validate_candidate_sizes(self) -> Self:
        if (
            not self.candidate_sizes
            or any(size <= 0 for size in self.candidate_sizes)
            or tuple(sorted(self.candidate_sizes, reverse=True)) != self.candidate_sizes
            or self.candidate_sizes[-1] != 1
            or len(set(self.candidate_sizes)) != len(self.candidate_sizes)
        ):
            raise ValueError("BUNDLE_PILOT_CANDIDATE_SIZES_INVALID")
        return self


class StorageSpec(FrozenContract):
    mode: Literal["R2_FIRST_APPEND_ONLY"]
    namespace: Literal["historical-deep-data/schema-v1"]
    payload_key_template: Literal[
        "competition={competition}/season={season}/family={family}/"
        "endpoint={endpoint}/task={task_id}/payload-{sha256}.json.gz"
    ]
    receipt_name: Literal["receipt.json"]
    raw_payloads_in_git: Literal[False]
    deletions_allowed: Literal[False]


class SafetySpec(FrozenContract):
    storage_paused: Literal[True] = Field(alias="STORAGE_PAUSED")
    p3_p4_paused: Literal[True] = Field(alias="P3_P4_PAUSED")
    production_locked: Literal[True] = Field(alias="PRODUCTION_LOCKED")
    real_bets: Literal[False] = Field(alias="REAL_BETS")
    no_bet_default: Literal[True] = Field(alias="NO_BET_DEFAULT")
    promotion_locked: Literal[True] = Field(alias="PROMOTION_LOCKED")
    social_publishing_enabled: Literal[False] = Field(
        alias="SOCIAL_PUBLISHING_ENABLED"
    )
    demo_mode_enabled: Literal[False] = Field(alias="DEMO_MODE_ENABLED")
    postgresql_production_destructive_writes: Literal[False] = Field(
        alias="POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES"
    )
    the_odds_api_historical_credits: Literal[False] = Field(
        alias="THE_ODDS_API_HISTORICAL_CREDITS"
    )


class CampaignContract(FrozenContract):
    schema_version: Literal["historical-deep-data-harvest-v1"]
    campaign_id: Literal["historical-deep-data-harvest-v1"]
    provider: Literal["api-football"]
    provider_secret_name: Literal["API_FOOTBALL_KEY"]
    subscription_requirements: SubscriptionRequirements
    competitions: tuple[CompetitionSpec, ...]
    season_priorities: SeasonPriorities
    families: FamilyPriorities
    quota: QuotaSpec
    bundle_pilot: BundlePilotSpec
    storage: StorageSpec
    task_statuses: tuple[TaskStatus, ...]
    temporal_classes: tuple[TemporalClass, ...]
    datasets: tuple[DatasetName, ...]
    gate_statuses: tuple[GateStatus, ...]
    workflows: tuple[int, ...]
    safety: SafetySpec
    verdicts: tuple[HarvestVerdict, ...]

    @model_validator(mode="after")
    def validate_campaign(self) -> Self:
        if not self.competitions:
            raise ValueError("HARVEST_COMPETITIONS_REQUIRED")
        if len({item.canonical_key for item in self.competitions}) != len(
            self.competitions
        ):
            raise ValueError("HARVEST_COMPETITION_KEYS_DUPLICATED")
        if len({item.provider_league_id for item in self.competitions}) != len(
            self.competitions
        ):
            raise ValueError("HARVEST_PROVIDER_LEAGUE_IDS_DUPLICATED")
        if self.bundle_pilot.preferred_competition not in {
            item.canonical_key for item in self.competitions
        }:
            raise ValueError("BUNDLE_PILOT_COMPETITION_NOT_IN_CAMPAIGN")
        if self.bundle_pilot.preferred_season not in self.season_priorities.P0:
            raise ValueError("BUNDLE_PILOT_SEASON_NOT_P0")
        exact_enums: tuple[tuple[object, ...], ...] = (
            self.task_statuses,
            self.temporal_classes,
            self.datasets,
            self.gate_statuses,
            self.verdicts,
        )
        enum_types = (
            TaskStatus,
            TemporalClass,
            DatasetName,
            GateStatus,
            HarvestVerdict,
        )
        if any(values != tuple(enum_type) for values, enum_type in zip(exact_enums, enum_types)):
            raise ValueError("HARVEST_ENUM_CONTRACT_MUST_BE_EXACT_AND_ORDERED")
        if self.workflows != tuple(range(70, 79)):
            raise ValueError("HARVEST_WORKFLOW_CONTRACT_MUST_BE_70_TO_78")
        return self

    @property
    def contract_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))

    def competition(self, canonical_key: str) -> CompetitionSpec:
        for competition in self.competitions:
            if competition.canonical_key == canonical_key:
                return competition
        raise KeyError(f"COMPETITION_NOT_IN_CAMPAIGN:{canonical_key}")


class ProviderStatus(FrozenContract):
    """Sanitized status proof; provider account details are never retained."""

    provider: Literal["api-football"] = "api-football"
    plan: Literal["Mega"]
    active: Literal[True]
    daily_limit: int = Field(gt=0)
    daily_used: int = Field(ge=0)
    daily_remaining: int = Field(ge=0)
    requests_per_second: int = Field(default=8, gt=0, le=8)
    requests_per_minute: int = Field(default=480, gt=0, le=480)
    requests_per_minute_remaining: int | None = Field(default=None, ge=0)
    checked_at: datetime
    expires_at: datetime | None = None
    subscription_end: datetime | None = None
    days_remaining: int | None = Field(default=None, ge=0)
    next_quota_reset: datetime | None = None
    rate_limit_reset_at: datetime | None = None
    header_daily_limit: int | None = Field(default=None, gt=0)
    header_daily_remaining: int | None = Field(default=None, ge=0)
    header_minute_limit: int | None = Field(default=None, gt=0)
    header_minute_remaining: int | None = Field(default=None, ge=0)
    sanitized_headers: dict[str, str] = Field(default_factory=dict)
    source_endpoint: Literal["/status"] = "/status"

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        checked_at = ensure_utc(self.checked_at, field="checked_at")
        expires_at = (
            ensure_utc(self.expires_at, field="expires_at")
            if self.expires_at is not None
            else checked_at + timedelta(minutes=5)
        )
        object.__setattr__(self, "expires_at", expires_at)
        if expires_at <= checked_at:
            raise ValueError("PROVIDER_STATUS_EXPIRY_MUST_FOLLOW_CHECK")
        if self.subscription_end is not None:
            subscription_end = ensure_utc(
                self.subscription_end,
                field="subscription_end",
            )
            if subscription_end <= checked_at:
                raise ValueError("PROVIDER_MEGA_SUBSCRIPTION_EXPIRED")
            expected_days = max(
                0,
                (subscription_end.date() - checked_at.date()).days,
            )
            if self.days_remaining is not None and self.days_remaining != expected_days:
                raise ValueError("PROVIDER_SUBSCRIPTION_DAYS_REMAINING_MISMATCH")
            object.__setattr__(self, "days_remaining", expected_days)
        elif self.days_remaining is not None:
            raise ValueError("PROVIDER_SUBSCRIPTION_END_REQUIRED_FOR_DAYS")
        next_quota_reset = self.next_quota_reset or (
            checked_at.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        next_quota_reset = ensure_utc(
            next_quota_reset,
            field="next_quota_reset",
        )
        if next_quota_reset <= checked_at:
            raise ValueError("PROVIDER_NEXT_QUOTA_RESET_MUST_BE_FUTURE")
        object.__setattr__(self, "next_quota_reset", next_quota_reset)
        if self.rate_limit_reset_at is not None:
            ensure_utc(self.rate_limit_reset_at, field="rate_limit_reset_at")
        if self.daily_used > self.daily_limit:
            raise ValueError("PROVIDER_DAILY_USED_EXCEEDS_LIMIT")
        if self.daily_remaining > self.daily_limit:
            raise ValueError("PROVIDER_DAILY_REMAINING_EXCEEDS_LIMIT")
        minute_remaining = (
            self.requests_per_minute
            if self.requests_per_minute_remaining is None
            else self.requests_per_minute_remaining
        )
        if minute_remaining > self.requests_per_minute:
            raise ValueError("PROVIDER_MINUTE_REMAINING_EXCEEDS_LIMIT")
        object.__setattr__(
            self,
            "requests_per_minute_remaining",
            minute_remaining,
        )
        allowed_headers = {
            "retry-after",
            "x-ratelimit-limit",
            "x-ratelimit-remaining",
            "x-ratelimit-requests-limit",
            "x-ratelimit-requests-remaining",
            "x-ratelimit-requests-reset",
            "x-ratelimit-rps-limit",
            "x-ratelimit-reset",
            "x-rate-limit-limit",
            "x-rate-limit-remaining",
            "x-rate-limit-requests-limit",
            "x-rate-limit-requests-remaining",
            "x-rate-limit-requests-reset",
            "x-rate-limit-rps-limit",
            "x-rate-limit-reset",
            "x-requests-per-minute",
            "x-requests-per-second",
        }
        if any(key.casefold() not in allowed_headers for key in self.sanitized_headers):
            raise ValueError("PROVIDER_STATUS_HEADERS_NOT_SANITIZED")
        return self

    @property
    def status_expires_at(self) -> datetime:
        if self.expires_at is None:
            raise RuntimeError("PROVIDER_STATUS_EXPIRY_NOT_MATERIALIZED")
        return self.expires_at

    @property
    def header_reset_at(self) -> datetime | None:
        return self.rate_limit_reset_at

    @property
    def quota_reset_at(self) -> datetime | None:
        return self.next_quota_reset

    @property
    def per_minute_remaining(self) -> int:
        if self.requests_per_minute_remaining is None:
            raise RuntimeError("PROVIDER_MINUTE_REMAINING_NOT_MATERIALIZED")
        return self.requests_per_minute_remaining

    def is_fresh(self, at: datetime) -> bool:
        return ensure_utc(at, field="status_check_at") < self.status_expires_at


class QuotaBudget(FrozenContract):
    daily_limit: int = Field(gt=0)
    daily_remaining: int = Field(ge=0)
    reserve: int = Field(ge=20000)
    available: int = Field(ge=0)
    mission_cap: int = Field(ge=0, le=100000)
    mission_used: int = Field(default=0, ge=0)
    requests_per_second: int = Field(default=8, gt=0, le=8)
    requests_per_minute: int = Field(default=480, gt=0, le=480)

    @model_validator(mode="after")
    def validate_budget_formula(self) -> Self:
        expected_reserve = max(20000, math.ceil(self.daily_limit * 0.2))
        expected_available = max(0, self.daily_remaining - expected_reserve)
        if self.reserve != expected_reserve:
            raise ValueError("QUOTA_RESERVE_FORMULA_MISMATCH")
        if self.available != expected_available:
            raise ValueError("QUOTA_AVAILABLE_FORMULA_MISMATCH")
        if self.mission_used == 0 and self.mission_cap != min(
            100000,
            expected_available,
        ):
            raise ValueError("QUOTA_INITIAL_MISSION_CAP_FORMULA_MISMATCH")
        return self

    @classmethod
    def from_status(
        cls,
        status: ProviderStatus,
        *,
        mission_used: int = 0,
        mission_cap: int | None = None,
    ) -> QuotaBudget:
        reserve = max(20000, math.ceil(status.daily_limit * 0.2))
        available = max(0, status.daily_remaining - reserve)
        fixed_cap = (
            min(100000, available)
            if mission_cap is None
            else mission_cap
        )
        return cls(
            daily_limit=status.daily_limit,
            daily_remaining=status.daily_remaining,
            reserve=reserve,
            available=available,
            mission_cap=fixed_cap,
            mission_used=mission_used,
            requests_per_second=status.requests_per_second,
            requests_per_minute=status.requests_per_minute,
        )

    @property
    def mission_remaining(self) -> int:
        return min(
            max(0, self.mission_cap - self.mission_used),
            self.available,
        )

    @property
    def exhausted(self) -> bool:
        return self.mission_remaining == 0


def _validate_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    if not value:
        raise ValueError("HARVEST_ENDPOINT_REQUIRED")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("HARVEST_ENDPOINT_MUST_BE_RELATIVE_WITHOUT_QUERY")
    normalized = "/" + value.strip("/")
    if normalized == "/" or ".." in normalized.split("/"):
        raise ValueError("HARVEST_ENDPOINT_INVALID")
    lowered = normalized.casefold()
    if any(name in lowered for name in _SENSITIVE_PARAMETER_NAMES):
        raise ValueError("HARVEST_ENDPOINT_CONTAINS_SENSITIVE_NAME")
    return normalized


def _normalize_params(
    params: dict[str, JsonScalar] | None,
) -> dict[str, JsonScalar]:
    normalized: dict[str, JsonScalar] = {}
    for key, value in (params or {}).items():
        name = str(key).strip()
        if not name or name.casefold() in _SENSITIVE_PARAMETER_NAMES:
            raise ValueError("HARVEST_PARAMETERS_CONTAIN_SENSITIVE_NAME")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("HARVEST_PARAMETERS_REQUIRE_FINITE_FLOATS")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise TypeError("HARVEST_PARAMETERS_REQUIRE_JSON_SCALARS")
        normalized[name] = value
    return dict(sorted(normalized.items()))


def build_task_id(
    *,
    campaign_id: str,
    competition: str | CompetitionSpec,
    season: int,
    family: str | DataFamily,
    endpoint: str,
    params: dict[str, JsonScalar] | None = None,
    page: int = 1,
) -> str:
    """Build the stable full SHA-256 identity of one provider request."""

    competition_key = (
        competition.canonical_key
        if isinstance(competition, CompetitionSpec)
        else str(competition)
    )
    if not campaign_id or not competition_key or season < 1888 or page < 1:
        raise ValueError("HARVEST_TASK_IDENTITY_INVALID")
    family_value = DataFamily(family).value
    identity = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "competition": competition_key,
        "season": season,
        "family": family_value,
        "endpoint": _validate_endpoint(endpoint),
        "params": _normalize_params(params),
        "page": page,
    }
    return canonical_sha256(identity)


class HarvestTask(FrozenContract):
    task_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_id: Literal["historical-deep-data-harvest-v1"]
    competition: str = Field(min_length=1, max_length=120)
    league_id: int = Field(gt=0)
    season: int = Field(ge=1888, le=2100)
    family: DataFamily
    endpoint: str = Field(min_length=1, max_length=250)
    params: dict[str, JsonScalar] = Field(default_factory=dict)
    page: int = Field(default=1, ge=1)
    status: TaskStatus = TaskStatus.PENDING
    temporal_class: TemporalClass

    @model_validator(mode="after")
    def validate_task(self) -> Self:
        if self.competition != f"api-football:{self.league_id}":
            raise ValueError("HARVEST_TASK_COMPETITION_LEAGUE_ID_MISMATCH")
        normalized_endpoint = _validate_endpoint(self.endpoint)
        normalized_params = _normalize_params(self.params)
        if normalized_endpoint != self.endpoint:
            raise ValueError("HARVEST_TASK_ENDPOINT_NOT_CANONICAL")
        if normalized_params != self.params:
            raise ValueError("HARVEST_TASK_PARAMETERS_NOT_CANONICAL")
        expected_id = build_task_id(
            campaign_id=self.campaign_id,
            competition=self.competition,
            season=self.season,
            family=self.family,
            endpoint=self.endpoint,
            params=self.params,
            page=self.page,
        )
        if self.task_id != expected_id:
            raise ValueError("HARVEST_TASK_ID_MISMATCH")
        return self

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        competition: CompetitionSpec,
        season: int,
        family: str | DataFamily,
        endpoint: str,
        temporal_class: TemporalClass,
        params: dict[str, JsonScalar] | None = None,
        page: int = 1,
        status: TaskStatus = TaskStatus.PENDING,
    ) -> HarvestTask:
        normalized_endpoint = _validate_endpoint(endpoint)
        normalized_params = _normalize_params(params)
        normalized_family = DataFamily(family)
        if campaign_id != CAMPAIGN_SCHEMA_VERSION:
            raise ValueError("HARVEST_CAMPAIGN_ID_INVALID")
        typed_campaign_id = cast(
            Literal["historical-deep-data-harvest-v1"],
            campaign_id,
        )
        task_id = build_task_id(
            campaign_id=typed_campaign_id,
            competition=competition,
            season=season,
            family=normalized_family,
            endpoint=normalized_endpoint,
            params=normalized_params,
            page=page,
        )
        return cls(
            task_id=task_id,
            campaign_id=typed_campaign_id,
            competition=competition.canonical_key,
            league_id=competition.provider_league_id,
            season=season,
            family=normalized_family,
            endpoint=normalized_endpoint,
            params=normalized_params,
            page=page,
            status=status,
            temporal_class=temporal_class,
        )

    @property
    def task_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"CAMPAIGN_CONTRACT_DUPLICATE_KEY:{key}")
        result[key] = value
    return result


def load_campaign_contract(
    path: str | Path = DEFAULT_CAMPAIGN_CONTRACT_PATH,
) -> CampaignContract:
    """Load the public campaign contract without reading any secret value."""

    contract_path = Path(path)
    try:
        raw = contract_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("CAMPAIGN_CONTRACT_UNREADABLE") from exc
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("CAMPAIGN_CONTRACT_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("CAMPAIGN_CONTRACT_ROOT_MUST_BE_OBJECT")
    return CampaignContract.model_validate(payload)
