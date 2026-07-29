"""Versioned contracts for machine discoveries and prospective observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

SHA256_LENGTH = 64
PRODUCTION_LOCKED = "PRODUCTION_LOCKED"


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name.upper()}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


class HypothesisOrigin(StrEnum):
    MACHINE_DISCOVERED = "MACHINE_DISCOVERED"
    OWNER_PROPOSED = "OWNER_PROPOSED"
    MODEL_DISCOVERED = "MODEL_DISCOVERED"
    LITERATURE_PROPOSED = "LITERATURE_PROPOSED"


class HypothesisStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING = "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
    PROSPECTIVE_OBSERVATION_CANDIDATE = "PROSPECTIVE_OBSERVATION_CANDIDATE"
    PROSPECTIVE_FROZEN = "PROSPECTIVE_FROZEN"
    OBSERVATION_ACTIVE = "OBSERVATION_ACTIVE"
    VALIDATION_DEFERRED_INSUFFICIENT_SUPPORT = "VALIDATION_DEFERRED_INSUFFICIENT_SUPPORT"
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"
    VALIDATED = "VALIDATED"
    REJECTED_PROSPECTIVE = "REJECTED_PROSPECTIVE"
    DATA_GATE_BLOCKED = "DATA_GATE_BLOCKED"
    ARCHIVED = "ARCHIVED"


class ObservationStatus(StrEnum):
    ELIGIBLE_FROZEN = "ELIGIBLE_FROZEN"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    REJECTED_MISSING_PRICE = "REJECTED_MISSING_PRICE"
    REJECTED_LATE = "REJECTED_LATE"
    VOID = "VOID"
    SETTLED = "SETTLED"


class HypothesisEventKind(StrEnum):
    HYPOTHESIS_DISCOVERED = "HYPOTHESIS_DISCOVERED"
    HYPOTHESIS_IMPORTED = "HYPOTHESIS_IMPORTED"
    HYPOTHESIS_EXPLAINED = "HYPOTHESIS_EXPLAINED"
    HYPOTHESIS_PROSPECTIVE_SELECTED = "HYPOTHESIS_PROSPECTIVE_SELECTED"
    HYPOTHESIS_PROSPECTIVE_FROZEN = "HYPOTHESIS_PROSPECTIVE_FROZEN"
    HYPOTHESIS_MATCH_EVALUATED = "HYPOTHESIS_MATCH_EVALUATED"
    HYPOTHESIS_OBSERVATION_FROZEN = "HYPOTHESIS_OBSERVATION_FROZEN"
    HYPOTHESIS_OBSERVATION_REJECTED = "HYPOTHESIS_OBSERVATION_REJECTED"
    HYPOTHESIS_OBSERVATION_SETTLED = "HYPOTHESIS_OBSERVATION_SETTLED"
    HYPOTHESIS_SUPPORT_UPDATED = "HYPOTHESIS_SUPPORT_UPDATED"
    HYPOTHESIS_VALIDATION_DEFERRED = "HYPOTHESIS_VALIDATION_DEFERRED"
    HYPOTHESIS_REJECTED_PROSPECTIVE = "HYPOTHESIS_REJECTED_PROSPECTIVE"
    HYPOTHESIS_VALIDATED = "HYPOTHESIS_VALIDATED"


ALLOWED_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.DISCOVERED: frozenset(
        {
            HypothesisStatus.EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING,
            HypothesisStatus.PROSPECTIVE_OBSERVATION_CANDIDATE,
            HypothesisStatus.DATA_GATE_BLOCKED,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING: frozenset(
        {
            HypothesisStatus.PROSPECTIVE_OBSERVATION_CANDIDATE,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.PROSPECTIVE_OBSERVATION_CANDIDATE: frozenset(
        {HypothesisStatus.PROSPECTIVE_FROZEN, HypothesisStatus.ARCHIVED}
    ),
    HypothesisStatus.PROSPECTIVE_FROZEN: frozenset(
        {HypothesisStatus.OBSERVATION_ACTIVE, HypothesisStatus.ARCHIVED}
    ),
    HypothesisStatus.OBSERVATION_ACTIVE: frozenset(
        {
            HypothesisStatus.VALIDATION_DEFERRED_INSUFFICIENT_SUPPORT,
            HypothesisStatus.SHADOW_ELIGIBLE,
            HypothesisStatus.REJECTED_PROSPECTIVE,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.VALIDATION_DEFERRED_INSUFFICIENT_SUPPORT: frozenset(
        {
            HypothesisStatus.OBSERVATION_ACTIVE,
            HypothesisStatus.SHADOW_ELIGIBLE,
            HypothesisStatus.REJECTED_PROSPECTIVE,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.SHADOW_ELIGIBLE: frozenset(
        {
            HypothesisStatus.REJECTED_PROSPECTIVE,
            HypothesisStatus.VALIDATED,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.VALIDATED: frozenset({HypothesisStatus.ARCHIVED}),
    HypothesisStatus.REJECTED_PROSPECTIVE: frozenset({HypothesisStatus.ARCHIVED}),
    HypothesisStatus.DATA_GATE_BLOCKED: frozenset(
        {
            HypothesisStatus.DISCOVERED,
            HypothesisStatus.PROSPECTIVE_OBSERVATION_CANDIDATE,
            HypothesisStatus.ARCHIVED,
        }
    ),
    HypothesisStatus.ARCHIVED: frozenset(),
}


def validate_transition(
    previous: HypothesisStatus,
    target: HypothesisStatus,
    *,
    automatic: bool = True,
) -> None:
    if target not in ALLOWED_TRANSITIONS[previous]:
        raise ValueError(f"HYPOTHESIS_STATUS_TRANSITION_FORBIDDEN:{previous.value}:{target.value}")
    if automatic and target is HypothesisStatus.VALIDATED:
        raise ValueError("AUTOMATIC_HYPOTHESIS_VALIDATION_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ExplanationMetadata:
    explanation_generated_by: str
    explanation_model: str
    explanation_prompt_hash: str
    explanation_source_hash: str
    explanation_generated_at: datetime

    def __post_init__(self) -> None:
        utc(self.explanation_generated_at, field_name="explanation_generated_at")
        for name, value in (
            ("explanation_prompt", self.explanation_prompt_hash),
            ("explanation_source", self.explanation_source_hash),
        ):
            if len(value) != SHA256_LENGTH:
                raise ValueError(f"{name.upper()}_HASH_INVALID")


@dataclass(frozen=True, slots=True)
class PriceContract:
    provider: str
    sport_key: str
    bookmaker_scope: tuple[str, ...]
    aggregation_method: str
    de_vig_method: str
    market: str
    selection: str
    minimum_odds: float
    maximum_odds: float
    maximum_margin: float
    cutoff_name: str
    cutoff_tolerance: str
    observed_at_rule: str
    kickoff_change_policy: str
    missing_price_policy: str
    multiple_bookmaker_policy: str
    price_contract_version: str

    def __post_init__(self) -> None:
        if (
            self.minimum_odds <= 1
            or self.maximum_odds < self.minimum_odds
            or not 0 <= self.maximum_margin <= 1
            or self.cutoff_name not in {"NEAR_KICKOFF", "H-2"}
        ):
            raise ValueError("HYPOTHESIS_PRICE_CONTRACT_INVALID")

    @property
    def contract_hash(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class HypothesisRecord:
    hypothesis_id: str
    hypothesis_version: str
    origin: HypothesisOrigin
    title: str
    description: str
    mechanism: str
    family: str
    competition_scope: tuple[str, ...]
    market: str
    selection: str
    conditions: tuple[dict[str, object], ...]
    price_contract: dict[str, object]
    discovery_dataset: str
    discovery_run_id: str
    discovery_code_revision: str
    discovery_timestamp: datetime
    historical_support: int
    historical_profit: float | None
    historical_roi: float | None
    historical_confidence_interval: tuple[float, float] | None
    historical_p_value: float | None
    historical_q_value: float | None
    historical_walk_forward: dict[str, object]
    historical_drawdown: float | None
    historical_cross_league_stability: dict[str, object]
    team_concentration: dict[str, object]
    time_concentration: dict[str, object]
    negative_controls: tuple[str, ...]
    required_data_gates: tuple[str, ...]
    current_data_gates: dict[str, str]
    status: HypothesisStatus
    status_reason: str
    preregistered_at: datetime | None
    preregistration_hash: str | None
    prospective_start_at: datetime | None
    minimum_prospective_support: int
    promotion_locked: bool
    created_at: datetime
    supersedes: str | None
    rule_hash: str
    canonical_fingerprint: str
    parent_rule_id: str | None = None
    variant_ids: tuple[str, ...] = ()
    explanation: ExplanationMetadata | None = None

    def __post_init__(self) -> None:
        utc(self.discovery_timestamp, field_name="discovery_timestamp")
        utc(self.created_at, field_name="created_at")
        if self.preregistered_at is not None:
            utc(self.preregistered_at, field_name="preregistered_at")
        if self.prospective_start_at is not None:
            utc(self.prospective_start_at, field_name="prospective_start_at")
        if (
            not self.hypothesis_id
            or not self.competition_scope
            or len(self.rule_hash) != SHA256_LENGTH
            or len(self.canonical_fingerprint) != SHA256_LENGTH
            or self.historical_support < 0
            or self.minimum_prospective_support < 0
            or not self.promotion_locked
        ):
            raise ValueError("HYPOTHESIS_RECORD_INVALID")
        if self.status is HypothesisStatus.VALIDATED:
            raise ValueError("IMPORTED_HYPOTHESIS_CANNOT_BE_VALIDATED")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = asdict(self)
        payload["origin"] = self.origin.value
        payload["status"] = self.status.value
        for name in (
            "discovery_timestamp",
            "preregistered_at",
            "prospective_start_at",
            "created_at",
        ):
            value = getattr(self, name)
            payload[name] = value.isoformat() if value is not None else None
        if self.explanation is not None:
            explanation = asdict(self.explanation)
            explanation["explanation_generated_at"] = (
                self.explanation.explanation_generated_at.isoformat()
            )
            payload["explanation"] = explanation
        if include_hash:
            payload["payload_hash"] = canonical_sha256(payload)
        return payload

    @property
    def payload_hash(self) -> str:
        return str(self.as_dict()["payload_hash"])


@dataclass(frozen=True, slots=True)
class ProspectiveHypothesisContract:
    contract_id: str
    hypothesis_id: str
    hypothesis_version: str
    frozen_at: datetime
    code_revision: str
    source_rule_hash: str
    source_registry_hash: str
    primary_price: PriceContract
    secondary_price: PriceContract
    minimum_descriptive_support: int = 30
    minimum_exploratory_support: int = 80
    minimum_seasons: int = 1
    evaluation_horizon: str = "SEASON_2026_2027"
    validation_criteria: tuple[str, ...] = (
        "FULL_PREREGISTERED_HORIZON_COMPLETE",
        "MULTIPLICITY_REVIEW_REQUIRED",
        "MANUAL_SCIENTIFIC_REVIEW_REQUIRED",
    )
    rejection_criteria: tuple[str, ...] = (
        "PROSPECTIVE_EFFECT_IN_WRONG_DIRECTION",
        "PROSPECTIVE_INSTABILITY",
        "DATA_CONTRACT_FAILURE",
    )
    multiplicity_policy: str = "JOINT_FAMILY_OF_THREE;NO_AUTOMATIC_VALIDATION"
    promotion_locked: bool = True
    supersedes: str | None = None

    def __post_init__(self) -> None:
        utc(self.frozen_at, field_name="frozen_at")
        if (
            self.primary_price.cutoff_name != "NEAR_KICKOFF"
            or self.secondary_price.cutoff_name != "H-2"
            or self.minimum_descriptive_support != 30
            or self.minimum_exploratory_support != 80
            or not self.promotion_locked
        ):
            raise ValueError("PROSPECTIVE_HYPOTHESIS_CONTRACT_INVALID")

    @property
    def contract_hash(self) -> str:
        payload = asdict(self)
        payload["frozen_at"] = self.frozen_at.isoformat()
        return canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class HypothesisObservation:
    hypothesis_observation_id: str
    hypothesis_id: str
    hypothesis_version: str
    fixture_id: str
    competition: str
    market: str
    selection: str
    cutoff_name: str
    cutoff_at: datetime
    kickoff_at: datetime
    observed_at: datetime
    odds: float | None
    margin: float | None
    bookmaker_scope: tuple[str, ...]
    conditions_snapshot: dict[str, object]
    status: ObservationStatus
    status_reason: str
    code_revision: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        cutoff = utc(self.cutoff_at, field_name="cutoff_at")
        kickoff = utc(self.kickoff_at, field_name="kickoff_at")
        observed = utc(self.observed_at, field_name="observed_at")
        if cutoff >= kickoff:
            raise ValueError("HYPOTHESIS_CUTOFF_MUST_PRECEDE_KICKOFF")
        if self.status is ObservationStatus.ELIGIBLE_FROZEN and (
            self.odds is None or self.margin is None or observed > cutoff
        ):
            raise ValueError("ELIGIBLE_HYPOTHESIS_OBSERVATION_INVALID")

    @property
    def conditions_hash(self) -> str:
        return canonical_sha256(self.conditions_snapshot)

    @property
    def payload_hash(self) -> str:
        payload = asdict(self)
        payload["status"] = self.status.value
        for name in ("cutoff_at", "kickoff_at", "observed_at"):
            payload[name] = getattr(self, name).isoformat()
        payload["conditions_hash"] = self.conditions_hash
        return canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class HypothesisSettlement:
    settlement_id: str
    observation_id: str
    fixture_id: str
    result_version: int
    result_status: str
    home_goals: int | None
    away_goals: int | None
    profit_units: float
    settled_at: datetime
    result_hash: str
    supersedes: str | None = None
    metrics: dict[str, float | int | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        utc(self.settled_at, field_name="settled_at")
        if self.result_version < 1 or len(self.result_hash) != SHA256_LENGTH:
            raise ValueError("HYPOTHESIS_SETTLEMENT_INVALID")

    @property
    def settlement_hash(self) -> str:
        payload = asdict(self)
        payload["settled_at"] = self.settled_at.isoformat()
        return canonical_sha256(payload)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ExplanationMetadata",
    "HypothesisEventKind",
    "HypothesisObservation",
    "HypothesisOrigin",
    "HypothesisRecord",
    "HypothesisSettlement",
    "HypothesisStatus",
    "ObservationStatus",
    "PriceContract",
    "ProspectiveHypothesisContract",
    "canonical_sha256",
    "validate_transition",
]
