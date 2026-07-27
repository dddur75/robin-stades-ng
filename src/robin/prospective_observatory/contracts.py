"""Immutable contracts for the Jalon 12 prospective data memory."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECEIPT_SCHEMA_VERSION = "prospective-capture-receipt-v1"
R2_SCHEMA_VERSION = "schema-v1"
PRODUCTION_STATUS = "PRODUCTION_LOCKED"
REAL_BETS = False
NO_BET_DEFAULT = True
SOCIAL_PUBLISHING_ENABLED = False
DEMO_MODE_ENABLED = False

_SENSITIVE_NAMES = {
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
    "x-apisports-key",
}


class CaptureFamily(StrEnum):
    FIXTURE = "FIXTURE"
    TEAM = "TEAM"
    SQUAD = "SQUAD"
    PLAYER_STATUS = "PLAYER_STATUS"
    INJURY = "INJURY"
    LINEUP = "LINEUP"
    FORMATION = "FORMATION"
    ODDS = "ODDS"
    EVENT_STATUS = "EVENT_STATUS"


class AvailabilityStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    CAPTURED = "CAPTURED"
    CAPTURED_EMPTY = "CAPTURED_EMPTY"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MISSED_WINDOW = "MISSED_WINDOW"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    TEMPORALITY_FAILED = "TEMPORALITY_FAILED"
    IDENTITY_FAILED = "IDENTITY_FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    COMPLETE = "COMPLETE"


class RetryDisposition(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    RETRY_PENDING = "RETRY_PENDING"
    LATE_RETRY = "LATE_RETRY"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


class HistoricalSemanticStatus(StrEnum):
    HISTORICAL_EVENT_TIME_USABLE = "HISTORICAL_EVENT_TIME_USABLE"
    HISTORICAL_SEMANTIC_POST_LINEUP_EXPOSED = (
        "HISTORICAL_SEMANTIC_POST_LINEUP_EXPOSED"
    )
    BLOCKED_BY_TEMPORALITY = "BLOCKED_BY_TEMPORALITY"


class ProspectiveHypothesisStatus(StrEnum):
    WAITING_FOR_OBSERVATIONS = "WAITING_FOR_OBSERVATIONS"
    DATA_CAPTURE_ACTIVE = "DATA_CAPTURE_ACTIVE"
    MINIMUM_SAMPLE_NOT_REACHED = "MINIMUM_SAMPLE_NOT_REACHED"
    ELIGIBLE_FOR_EXPLORATORY_ANALYSIS = "ELIGIBLE_FOR_EXPLORATORY_ANALYSIS"


def ensure_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return value.astimezone(UTC)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def receipt_scope_sha256(
    *,
    window_id: str | None,
    window_label: str,
) -> str:
    """Identify the capture window independently from the raw payload."""

    return canonical_sha256(
        {
            "window_id": window_id,
            "window_label": window_label,
        }
    )


def _validate_source_endpoint(value: str) -> str:
    lowered = value.casefold()
    if any(f"{name}=" in lowered for name in _SENSITIVE_NAMES):
        raise ValueError("SOURCE_ENDPOINT_CONTAINS_SENSITIVE_PARAMETER")
    parsed = urlsplit(value)
    if parsed.password is not None or parsed.username is not None:
        raise ValueError("SOURCE_ENDPOINT_CONTAINS_CREDENTIALS")
    for name, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if name.casefold() in _SENSITIVE_NAMES:
            raise ValueError("SOURCE_ENDPOINT_CONTAINS_SENSITIVE_PARAMETER")
    return value


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProspectiveFixture(FrozenContract):
    fixture_id: str = Field(min_length=1, max_length=120)
    competition: str = Field(min_length=1, max_length=120)
    season: str = Field(min_length=1, max_length=40)
    phase: str = Field(min_length=1, max_length=120)
    home_team_id: str = Field(min_length=1, max_length=120)
    away_team_id: str = Field(min_length=1, max_length=120)
    kickoff_at: datetime
    provider: str = Field(min_length=1, max_length=120)
    provider_fixture_id: str = Field(min_length=1, max_length=120)
    registered_at: datetime
    code_revision: str = Field(min_length=1, max_length=80)
    cancelled: bool = False
    kickoff_reliable: bool = True
    horizon_days: int = Field(default=30, ge=1, le=30)
    lifecycle_version_hash: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_fixture(self) -> Self:
        ensure_utc(self.kickoff_at, field="kickoff_at")
        ensure_utc(self.registered_at, field="registered_at")
        if self.home_team_id == self.away_team_id:
            raise ValueError("FIXTURE_TEAMS_MUST_DIFFER")
        # A cancelled/postponed fixture is retained as an immutable tombstone
        # so older capture windows cannot remain operational. It is never
        # exposed by the active fixture registry.
        if not self.kickoff_reliable:
            raise ValueError("FIXTURE_NOT_ELIGIBLE_FOR_PROSPECTIVE_REGISTRY")
        if not self.registered_at < self.kickoff_at <= (
            self.registered_at + timedelta(days=self.horizon_days)
        ):
            raise ValueError("FIXTURE_OUTSIDE_PROSPECTIVE_HORIZON")
        return self

    @property
    def business_hash(self) -> str:
        # Registration time and the running code revision are observation
        # metadata, not part of the provider fixture's business identity.
        # Excluding them keeps a daily registry replay idempotent while a real
        # kickoff/team/phase change still creates a new immutable version.
        return canonical_sha256(
            self.model_dump(
                mode="json",
                exclude={
                    "registered_at",
                    "code_revision",
                    "lifecycle_version_hash",
                },
            )
        )

    @property
    def registry_hash(self) -> str:
        # An exact business state may legitimately recur after a cancellation
        # or TBD tombstone. In that case the immutable lifecycle hash prevents
        # the new activation from aliasing the older SQL/R2 version.
        return self.lifecycle_version_hash or self.business_hash


class CaptureWindow(FrozenContract):
    window_id: str = Field(min_length=1, max_length=250)
    fixture_id: str = Field(min_length=1, max_length=120)
    family: CaptureFamily
    label: str = Field(min_length=1, max_length=40)
    due_at: datetime
    opens_at: datetime
    cutoff_at: datetime
    kickoff_at: datetime
    scheduled_at: datetime
    operational_tolerance_seconds: int = Field(ge=0, le=3600)
    status: AvailabilityStatus = AvailabilityStatus.NOT_DUE
    policy_version: str = "prospective-capture-window-v1"
    code_revision: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        due_at = ensure_utc(self.due_at, field="due_at")
        opens_at = ensure_utc(self.opens_at, field="opens_at")
        cutoff_at = ensure_utc(self.cutoff_at, field="cutoff_at")
        kickoff_at = ensure_utc(self.kickoff_at, field="kickoff_at")
        ensure_utc(self.scheduled_at, field="scheduled_at")
        if not opens_at <= due_at <= cutoff_at < kickoff_at:
            raise ValueError("CAPTURE_WINDOW_TEMPORAL_ORDER_INVALID")
        return self


class CaptureAttempt(FrozenContract):
    attempt_id: str = Field(min_length=1, max_length=250)
    idempotency_key: str = Field(min_length=1, max_length=250)
    window_id: str = Field(min_length=1, max_length=250)
    fixture_id: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    family: CaptureFamily
    attempted_at: datetime
    status: AvailabilityStatus
    retry_disposition: RetryDisposition = RetryDisposition.NOT_REQUIRED
    attempt_number: int = Field(ge=1, le=5)
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_calls: int = Field(default=0, ge=0, le=1)
    provider_credits: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=120)
    code_revision: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        ensure_utc(self.attempted_at, field="attempted_at")
        if self.status in {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        } and self.http_status is None:
            raise ValueError("CAPTURED_ATTEMPT_REQUIRES_HTTP_STATUS")
        return self


class CaptureContext(FrozenContract):
    window_id: str | None = Field(default=None, min_length=1, max_length=250)
    window_label: str = Field(default="REGISTRY", min_length=1, max_length=40)
    fixture_id: str = Field(min_length=1, max_length=120)
    competition: str = Field(min_length=1, max_length=120)
    season: str = Field(min_length=1, max_length=40)
    provider: str = Field(min_length=1, max_length=120)
    family: CaptureFamily
    requested_at: datetime
    response_received_at: datetime
    observed_at: datetime
    kickoff_at: datetime
    cutoff_at: datetime
    http_status: int = Field(ge=100, le=599)
    source_endpoint: str = Field(min_length=1, max_length=500)
    complete: bool
    quality_status: AvailabilityStatus
    provider_calls: int = Field(ge=0, le=1)
    code_revision: str = Field(min_length=1, max_length=80)
    event_time: datetime | None = None
    provider_updated_at: datetime | None = None
    materialized_at: datetime | None = None

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        requested_at = ensure_utc(self.requested_at, field="requested_at")
        response_at = ensure_utc(
            self.response_received_at,
            field="response_received_at",
        )
        observed_at = ensure_utc(self.observed_at, field="observed_at")
        cutoff_at = ensure_utc(self.cutoff_at, field="cutoff_at")
        kickoff_at = ensure_utc(self.kickoff_at, field="kickoff_at")
        for field_name in ("event_time", "provider_updated_at", "materialized_at"):
            value = getattr(self, field_name)
            if value is not None:
                ensure_utc(value, field=field_name)
        if requested_at > response_at or response_at > observed_at:
            raise ValueError("CAPTURE_REQUEST_RESPONSE_OBSERVATION_ORDER_INVALID")
        if cutoff_at >= kickoff_at:
            raise ValueError("CAPTURE_CUTOFF_MUST_PRECEDE_KICKOFF")
        if (self.window_id is None) != (self.window_label == "REGISTRY"):
            raise ValueError("CAPTURE_REGISTRY_WINDOW_REFERENCE_INCONSISTENT")
        _validate_source_endpoint(self.source_endpoint)
        return self


class CaptureReceipt(FrozenContract):
    schema_version: str = RECEIPT_SCHEMA_VERSION
    window_id: str | None = None
    window_label: str = "REGISTRY"
    fixture_id: str
    competition: str
    season: str
    provider: str
    family: CaptureFamily
    requested_at: datetime
    response_received_at: datetime
    observed_at: datetime
    kickoff_at: datetime
    cutoff_at: datetime
    seconds_before_kickoff: int
    http_status: int = Field(ge=100, le=599)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_bytes: int = Field(ge=0)
    stored_bytes: int = Field(ge=0)
    r2_key: str = Field(min_length=1, max_length=1500)
    receipt_r2_key: str = Field(min_length=1, max_length=1500)
    source_endpoint: str
    complete: bool
    quality_status: AvailabilityStatus
    provider_calls: int = Field(ge=0, le=1)
    code_revision: str
    event_time: datetime | None = None
    provider_updated_at: datetime | None = None
    materialized_at: datetime

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        context = CaptureContext(
            window_id=self.window_id,
            window_label=self.window_label,
            fixture_id=self.fixture_id,
            competition=self.competition,
            season=self.season,
            provider=self.provider,
            family=self.family,
            requested_at=self.requested_at,
            response_received_at=self.response_received_at,
            observed_at=self.observed_at,
            kickoff_at=self.kickoff_at,
            cutoff_at=self.cutoff_at,
            http_status=self.http_status,
            source_endpoint=self.source_endpoint,
            complete=self.complete,
            quality_status=self.quality_status,
            provider_calls=self.provider_calls,
            code_revision=self.code_revision,
            event_time=self.event_time,
            provider_updated_at=self.provider_updated_at,
            materialized_at=self.materialized_at,
        )
        expected_seconds = int(
            (
                ensure_utc(context.kickoff_at, field="kickoff_at")
                - ensure_utc(
                    context.response_received_at,
                    field="response_received_at",
                )
            ).total_seconds()
        )
        if self.seconds_before_kickoff != expected_seconds:
            raise ValueError("RECEIPT_SECONDS_BEFORE_KICKOFF_MISMATCH")
        if not self.r2_key.endswith(f"payload-{self.payload_sha256}.json.gz"):
            raise ValueError("RECEIPT_R2_KEY_HASH_MISMATCH")
        receipt_scope = receipt_scope_sha256(
            window_id=self.window_id,
            window_label=self.window_label,
        )
        if not self.receipt_r2_key.endswith(
            f"receipt-{receipt_scope}-{self.payload_sha256}.json"
        ):
            raise ValueError("RECEIPT_OBJECT_KEY_HASH_MISMATCH")
        return self

    @property
    def temporally_admissible(self) -> bool:
        return (
            ensure_utc(
                self.response_received_at,
                field="response_received_at",
            )
            < ensure_utc(self.cutoff_at, field="cutoff_at")
            < ensure_utc(self.kickoff_at, field="kickoff_at")
        )

    @property
    def receipt_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))
