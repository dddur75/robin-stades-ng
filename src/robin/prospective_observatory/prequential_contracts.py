"""Immutable contracts for the five-league prequential learning lane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isclose
from typing import Any

from robin.prospective_observatory.contracts import canonical_sha256, ensure_utc

SHA256_LENGTH = 64
PRODUCTION_LOCKED = "PRODUCTION_LOCKED"
PROMOTION_LOCKED = "PROMOTION_LOCKED"


class CutoffName(StrEnum):
    H_2 = "H-2"
    NEAR_KICKOFF = "NEAR_KICKOFF"


class PredictionMarket(StrEnum):
    ONE_X_TWO = "1X2"
    OVER_UNDER_2_5 = "OVER_UNDER_2_5"


class PredictionStatus(StrEnum):
    FROZEN = "FROZEN"
    REJECTED_LATE = "REJECTED_LATE"
    REJECTED_MISSING_GATE = "REJECTED_MISSING_GATE"
    NO_ODDS_REFERENCE = "NO_ODDS_REFERENCE"
    SETTLED = "SETTLED"
    VOID = "VOID"


class FixtureResultStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PLAY = "IN_PLAY"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    CORRECTED = "CORRECTED"


class ModelScope(StrEnum):
    GLOBAL_FIVE_LEAGUES = "GLOBAL_FIVE_LEAGUES"
    LIGUE_1 = "LIGUE_1"
    PREMIER_LEAGUE = "PREMIER_LEAGUE"
    LIGA = "LIGA"
    BUNDESLIGA = "BUNDESLIGA"
    SERIE_A = "SERIE_A"


class ModelRole(StrEnum):
    REFERENCE = "REFERENCE"
    CHALLENGER = "CHALLENGER"


class ModelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN_REFERENCE = "FROZEN_REFERENCE"
    INSUFFICIENT_TRAINING_SUPPORT = "INSUFFICIENT_TRAINING_SUPPORT"


class PrequentialEventKind(StrEnum):
    FEATURE_SNAPSHOT_FROZEN = "FEATURE_SNAPSHOT_FROZEN"
    PREDICTION_FROZEN = "PREDICTION_FROZEN"
    PREDICTION_REJECTED = "PREDICTION_REJECTED"
    FIXTURE_SETTLED = "FIXTURE_SETTLED"
    PREDICTION_SCORED = "PREDICTION_SCORED"
    TRAINING_ELIGIBLE = "TRAINING_ELIGIBLE"
    TRAINING_DEFERRED = "TRAINING_DEFERRED"
    CHALLENGER_TRAINING_STARTED = "CHALLENGER_TRAINING_STARTED"
    CHALLENGER_VERSION_CREATED = "CHALLENGER_VERSION_CREATED"
    REFERENCE_UNCHANGED = "REFERENCE_UNCHANGED"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"
    # Compatibility vocabulary from the five-league expansion.
    MATCH_SETTLED = "MATCH_SETTLED"
    CHALLENGER_TRAINING_ELIGIBLE = "CHALLENGER_TRAINING_ELIGIBLE"
    CHALLENGER_UPDATED = "CHALLENGER_UPDATED"


def _is_sha256(value: str) -> bool:
    return len(value) == SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _require_sha256(value: str, *, field_name: str) -> None:
    if not _is_sha256(value):
        raise ValueError(f"{field_name.upper()}_SHA256_INVALID")


def _market_selections(market: PredictionMarket) -> tuple[str, ...]:
    if market is PredictionMarket.ONE_X_TWO:
        return ("HOME", "DRAW", "AWAY")
    return ("OVER", "UNDER")


def validate_probabilities(
    market: PredictionMarket,
    probabilities: dict[str, float],
) -> None:
    expected = set(_market_selections(market))
    if set(probabilities) != expected:
        raise ValueError("PREQUENTIAL_PROBABILITY_SELECTIONS_INVALID")
    if any(value <= 0.0 or value >= 1.0 for value in probabilities.values()):
        raise ValueError("PREQUENTIAL_PROBABILITY_BOUNDS_INVALID")
    if not isclose(sum(probabilities.values()), 1.0, abs_tol=1e-9):
        raise ValueError("PREQUENTIAL_PROBABILITY_SUM_INVALID")


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_id: str
    scope: ModelScope
    role: ModelRole
    version: str
    artifact_sha256: str
    created_at: datetime
    training_cutoff: datetime | None = None
    feature_contract_hash: str = "0" * SHA256_LENGTH
    code_revision: str = "unknown"
    status: ModelStatus = ModelStatus.ACTIVE
    artifact_r2_key: str | None = None
    parent_version: str | None = None
    frozen: bool = True

    def __post_init__(self) -> None:
        created = ensure_utc(self.created_at, field="created_at")
        _require_sha256(self.artifact_sha256, field_name="artifact")
        _require_sha256(self.feature_contract_hash, field_name="feature_contract")
        if self.training_cutoff is not None:
            cutoff = ensure_utc(self.training_cutoff, field="training_cutoff")
            if cutoff > created:
                raise ValueError("MODEL_TRAINING_CUTOFF_AFTER_CREATION")
        if (
            not self.model_id
            or not self.version
            or not self.code_revision
            or not self.frozen
        ):
            raise ValueError("PREQUENTIAL_MODEL_VERSION_INVALID")
        if (
            self.role is ModelRole.REFERENCE
            and self.status is not ModelStatus.FROZEN_REFERENCE
            and self.status is not ModelStatus.ACTIVE
        ):
            raise ValueError("PREQUENTIAL_REFERENCE_STATUS_INVALID")

    @property
    def registry_hash(self) -> str:
        return canonical_sha256(
            {
                "model_id": self.model_id,
                "scope": self.scope.value,
                "role": self.role.value,
                "version": self.version,
                "artifact_sha256": self.artifact_sha256,
                "created_at": self.created_at.isoformat(),
                "training_cutoff": (
                    self.training_cutoff.isoformat()
                    if self.training_cutoff is not None
                    else None
                ),
                "feature_contract_hash": self.feature_contract_hash,
                "code_revision": self.code_revision,
                "status": self.status.value,
                "artifact_r2_key": self.artifact_r2_key,
                "parent_version": self.parent_version,
                "frozen": self.frozen,
            }
        )


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    snapshot_id: str
    fixture_record_id: str
    fixture_id: str
    competition: str
    market: PredictionMarket
    cutoff_name: CutoffName
    cutoff_at: datetime
    created_at: datetime
    feature_contract_version: str
    feature_contract_hash: str
    values: dict[str, object]
    missingness: dict[str, bool]
    provenance: dict[str, dict[str, object]]
    quality: dict[str, object]
    code_revision: str
    r2_manifest_key: str
    supersedes_id: str | None = None
    status: str = "FROZEN"

    def __post_init__(self) -> None:
        cutoff = ensure_utc(self.cutoff_at, field="cutoff_at")
        created = ensure_utc(self.created_at, field="created_at")
        _require_sha256(
            self.feature_contract_hash,
            field_name="feature_contract",
        )
        if (
            not self.snapshot_id
            or not self.fixture_record_id
            or not self.fixture_id
            or not self.competition
            or not self.feature_contract_version
            or not self.code_revision
            or not self.r2_manifest_key
            or self.status != "FROZEN"
            or created > cutoff
        ):
            raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_INVALID")
        for family, missing in self.missingness.items():
            if missing and self.values.get(family) not in (None, {}, [], ()):
                raise ValueError("MISSING_FEATURE_MUST_NOT_BE_ZERO_FILLED")
        for evidence in self.provenance.values():
            observed = evidence.get("observed_at")
            if not isinstance(observed, str):
                raise ValueError("FEATURE_PROVENANCE_OBSERVED_AT_REQUIRED")
            observed_at = ensure_utc(
                datetime.fromisoformat(observed.replace("Z", "+00:00")),
                field="observed_at",
            )
            if observed_at > cutoff:
                raise ValueError("FEATURE_PROVENANCE_AFTER_CUTOFF")

    @property
    def snapshot_hash(self) -> str:
        return canonical_sha256(self.as_manifest(include_storage=False))

    @property
    def payload_hash(self) -> str:
        """Canonical payload hash; kept as an explicit contract alias."""

        return self.snapshot_hash

    def as_manifest(self, *, include_storage: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "snapshot_id": self.snapshot_id,
            "fixture_record_id": self.fixture_record_id,
            "fixture_id": self.fixture_id,
            "competition": self.competition,
            "market": self.market.value,
            "cutoff_name": self.cutoff_name.value,
            "cutoff_at": self.cutoff_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "feature_contract_version": self.feature_contract_version,
            "feature_contract_hash": self.feature_contract_hash,
            "values": self.values,
            "missingness": self.missingness,
            "provenance": self.provenance,
            "quality": self.quality,
            "code_revision": self.code_revision,
            "supersedes_id": self.supersedes_id,
            "status": self.status,
        }
        if include_storage:
            value["r2_manifest_key"] = self.r2_manifest_key
        return value


@dataclass(frozen=True, slots=True)
class FrozenPredictionRecord:
    prediction_id: str
    fixture_record_id: str
    fixture_id: str
    competition: str
    market: PredictionMarket
    cutoff_name: CutoffName
    cutoff_at: datetime
    kickoff_at: datetime
    predicted_at: datetime
    model_id: str
    model_version: str
    feature_snapshot_id: str | None
    probabilities: dict[str, float]
    market_probabilities: dict[str, float] | None
    odds_snapshot_id: str | None
    code_revision: str
    status: PredictionStatus
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        cutoff = ensure_utc(self.cutoff_at, field="cutoff_at")
        kickoff = ensure_utc(self.kickoff_at, field="kickoff_at")
        predicted = ensure_utc(self.predicted_at, field="predicted_at")
        if (
            not self.prediction_id
            or not self.fixture_record_id
            or not self.fixture_id
            or not self.competition
            or not self.model_id
            or not self.model_version
            or not self.code_revision
            or cutoff >= kickoff
        ):
            raise ValueError("PREQUENTIAL_PREDICTION_INVALID")
        if self.status is PredictionStatus.FROZEN:
            if predicted > cutoff:
                raise ValueError("PREQUENTIAL_PREDICTION_AFTER_CUTOFF")
            if self.feature_snapshot_id is None:
                raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_REQUIRED")
            validate_probabilities(self.market, self.probabilities)
            if self.market_probabilities is not None:
                validate_probabilities(self.market, self.market_probabilities)
        else:
            if self.probabilities:
                raise ValueError("REJECTED_PREDICTION_PROBABILITIES_FORBIDDEN")
            if not self.rejection_reason:
                raise ValueError("PREDICTION_REJECTION_REASON_REQUIRED")

    @property
    def payload_hash(self) -> str:
        return canonical_sha256(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "prediction_id": self.prediction_id,
            "fixture_record_id": self.fixture_record_id,
            "fixture_id": self.fixture_id,
            "competition": self.competition,
            "market": self.market.value,
            "cutoff_name": self.cutoff_name.value,
            "cutoff_at": self.cutoff_at.isoformat(),
            "kickoff_at": self.kickoff_at.isoformat(),
            "predicted_at": self.predicted_at.isoformat(),
            "model_id": self.model_id,
            "model_version": self.model_version,
            "feature_snapshot_id": self.feature_snapshot_id,
            "probabilities": self.probabilities,
            "market_probabilities": self.market_probabilities,
            "odds_snapshot_id": self.odds_snapshot_id,
            "code_revision": self.code_revision,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
        }
        if include_hash:
            value["payload_hash"] = self.payload_hash
        return value


@dataclass(frozen=True, slots=True)
class VerifiedFixtureResult:
    fixture_record_id: str
    fixture_id: str
    competition: str
    kickoff_at: datetime
    status: FixtureResultStatus
    verified_at: datetime
    home_goals: int | None = None
    away_goals: int | None = None
    result_version: int = 1
    source_hash: str = "0" * SHA256_LENGTH

    def __post_init__(self) -> None:
        kickoff = ensure_utc(self.kickoff_at, field="kickoff_at")
        verified = ensure_utc(self.verified_at, field="verified_at")
        _require_sha256(self.source_hash, field_name="source")
        if (
            not self.fixture_record_id
            or not self.fixture_id
            or not self.competition
            or self.result_version < 1
        ):
            raise ValueError("PREQUENTIAL_RESULT_INVALID")
        score_required = self.status in {
            FixtureResultStatus.FINISHED,
            FixtureResultStatus.CORRECTED,
        }
        if score_required and verified <= kickoff:
            raise ValueError("FINAL_RESULT_VERIFIED_BEFORE_KICKOFF")
        if score_required and (
            self.home_goals is None
            or self.away_goals is None
            or self.home_goals < 0
            or self.away_goals < 0
        ):
            raise ValueError("FINAL_RESULT_SCORE_REQUIRED")
        if not score_required and (
            self.home_goals is not None or self.away_goals is not None
        ):
            raise ValueError("NON_SCORE_RESULT_MUST_NOT_HAVE_SCORE")

    @property
    def result_hash(self) -> str:
        return canonical_sha256(
            {
                "fixture_record_id": self.fixture_record_id,
                "fixture_id": self.fixture_id,
                "competition": self.competition,
                "kickoff_at": self.kickoff_at.isoformat(),
                "status": self.status.value,
                "verified_at": self.verified_at.isoformat(),
                "home_goals": self.home_goals,
                "away_goals": self.away_goals,
                "result_version": self.result_version,
                "source_hash": self.source_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class FixtureSettlementRecord:
    settlement_id: str
    result: VerifiedFixtureResult
    settled_at: datetime
    effective_status: PredictionStatus
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        settled = ensure_utc(self.settled_at, field="settled_at")
        if (
            not self.settlement_id
            or settled < self.result.verified_at
            or self.effective_status
            not in {PredictionStatus.SETTLED, PredictionStatus.VOID}
        ):
            raise ValueError("PREQUENTIAL_SETTLEMENT_INVALID")

    @property
    def settlement_hash(self) -> str:
        return canonical_sha256(
            {
                "settlement_id": self.settlement_id,
                "result_hash": self.result.result_hash,
                "settled_at": self.settled_at.isoformat(),
                "effective_status": self.effective_status.value,
                "supersedes_id": self.supersedes_id,
            }
        )


@dataclass(frozen=True, slots=True)
class PredictionScore:
    score_id: str
    prediction_id: str
    settlement_id: str
    fixture_id: str
    competition: str
    market: PredictionMarket
    cutoff_name: CutoffName
    model_id: str
    model_version: str
    scored_at: datetime
    outcome: str
    log_loss: float
    brier_score: float
    accurate: bool
    reference_log_loss_delta: float | None = None

    def __post_init__(self) -> None:
        ensure_utc(self.scored_at, field="scored_at")
        if (
            not self.score_id
            or not self.prediction_id
            or not self.settlement_id
            or self.log_loss < 0
            or self.brier_score < 0
        ):
            raise ValueError("PREQUENTIAL_SCORE_INVALID")

    @property
    def score_hash(self) -> str:
        return canonical_sha256(
            {
                "score_id": self.score_id,
                "prediction_id": self.prediction_id,
                "settlement_id": self.settlement_id,
                "fixture_id": self.fixture_id,
                "competition": self.competition,
                "market": self.market.value,
                "cutoff_name": self.cutoff_name.value,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "scored_at": self.scored_at.isoformat(),
                "outcome": self.outcome,
                "log_loss": self.log_loss,
                "brier_score": self.brier_score,
                "accurate": self.accurate,
                "reference_log_loss_delta": self.reference_log_loss_delta,
            }
        )


@dataclass(frozen=True, slots=True)
class TrainingDatasetManifest:
    manifest_id: str
    created_at: datetime
    training_cutoff: datetime
    fixture_ids: tuple[str, ...]
    settlement_ids: tuple[str, ...]
    competitions: tuple[str, ...]
    feature_snapshot_ids: tuple[str, ...]
    feature_contract_hash: str
    hyperparameters: dict[str, object]
    code_revision: str
    r2_key: str
    training_metrics: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        created = ensure_utc(self.created_at, field="created_at")
        cutoff = ensure_utc(self.training_cutoff, field="training_cutoff")
        _require_sha256(
            self.feature_contract_hash,
            field_name="feature_contract",
        )
        if (
            not self.manifest_id
            or not self.code_revision
            or not self.r2_key
            or cutoff > created
            or len(self.fixture_ids) != len(set(self.fixture_ids))
            or len(self.fixture_ids) != len(self.settlement_ids)
        ):
            raise ValueError("TRAINING_DATASET_MANIFEST_INVALID")

    @property
    def manifest_hash(self) -> str:
        return canonical_sha256(self.as_dict(include_storage=False))

    def as_dict(self, *, include_storage: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "manifest_id": self.manifest_id,
            "created_at": self.created_at.isoformat(),
            "training_cutoff": self.training_cutoff.isoformat(),
            "fixture_ids": list(self.fixture_ids),
            "settlement_ids": list(self.settlement_ids),
            "competitions": list(self.competitions),
            "feature_snapshot_ids": list(self.feature_snapshot_ids),
            "feature_contract_hash": self.feature_contract_hash,
            "hyperparameters": self.hyperparameters,
            "training_metrics": self.training_metrics,
            "code_revision": self.code_revision,
        }
        if include_storage:
            value["r2_key"] = self.r2_key
        return value


@dataclass(frozen=True, slots=True)
class TrainingDecision:
    status: str
    eligible_fixtures: int
    represented_leagues: int
    manifest: TrainingDatasetManifest | None = None
    next_model: ModelVersion | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PrequentialLedgerEvent:
    event_id: str
    sequence_no: int
    kind: PrequentialEventKind
    recorded_at: datetime
    stream_key: str
    fixture_id: str | None
    model_id: str | None
    model_version: str | None
    evidence_hashes: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = "0" * SHA256_LENGTH
    production_status: str = PRODUCTION_LOCKED
    real_bets: bool = False
    promoted: bool = False

    def __post_init__(self) -> None:
        ensure_utc(self.recorded_at, field="recorded_at")
        _require_sha256(self.previous_hash, field_name="previous")
        for evidence_hash in self.evidence_hashes:
            _require_sha256(evidence_hash, field_name="evidence")
        if (
            not self.event_id
            or self.sequence_no < 0
            or not self.stream_key
            or self.production_status != PRODUCTION_LOCKED
            or self.real_bets
            or self.promoted
        ):
            raise ValueError("PREQUENTIAL_LEDGER_EVENT_INVALID")

    @property
    def event_hash(self) -> str:
        return canonical_sha256(
            {
                "event_id": self.event_id,
                "sequence_no": self.sequence_no,
                "kind": self.kind.value,
                "recorded_at": self.recorded_at.isoformat(),
                "stream_key": self.stream_key,
                "fixture_id": self.fixture_id,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "evidence_hashes": list(self.evidence_hashes),
                "details": self.details,
                "previous_hash": self.previous_hash,
                "production_status": self.production_status,
                "real_bets": self.real_bets,
                "promoted": self.promoted,
            }
        )


FIVE_LEAGUE_NAMES: dict[ModelScope, str] = {
    ModelScope.LIGUE_1: "Ligue 1",
    ModelScope.PREMIER_LEAGUE: "Premier League",
    ModelScope.LIGA: "Liga",
    ModelScope.BUNDESLIGA: "Bundesliga",
    ModelScope.SERIE_A: "Serie A",
}


__all__ = [
    "CutoffName",
    "FIVE_LEAGUE_NAMES",
    "FeatureSnapshot",
    "FixtureResultStatus",
    "FixtureSettlementRecord",
    "FrozenPredictionRecord",
    "ModelRole",
    "ModelScope",
    "ModelStatus",
    "ModelVersion",
    "PROMOTION_LOCKED",
    "PRODUCTION_LOCKED",
    "PredictionMarket",
    "PredictionScore",
    "PredictionStatus",
    "PrequentialEventKind",
    "PrequentialLedgerEvent",
    "TrainingDatasetManifest",
    "TrainingDecision",
    "VerifiedFixtureResult",
    "validate_probabilities",
]
