"""Immutable contracts for the five-league prequential learning lane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from math import isclose, isfinite
from typing import Any, cast

from robin.market_math import kernel_versions
from robin.prospective_observatory.contracts import canonical_sha256, ensure_utc
from robin.temporal.lineage import (
    TEMPORAL_CONTRACT_VERSION,
    SourceReceipt,
    TemporalProofLevel,
    freeze_json,
    parse_utc,
    thaw_json,
)

SHA256_LENGTH = 64
PRODUCTION_LOCKED = "PRODUCTION_LOCKED"
PROMOTION_LOCKED = "PROMOTION_LOCKED"


class CutoffName(StrEnum):
    H_2 = "H-2"
    NEAR_KICKOFF = "NEAR_KICKOFF"


CUTOFF_MINUTES_BEFORE_KICKOFF = {
    CutoffName.H_2: 120,
    CutoffName.NEAR_KICKOFF: 1,
}

_DURABLE_OPTIONAL_FEATURE_GATES = {"injuries", "lineup"}


def durable_required_feature_gates(quality: object) -> tuple[str, ...]:
    """Read optional gates whose contract is persisted in snapshot quality."""

    if not isinstance(quality, Mapping):
        raise ValueError("FEATURE_REQUIRED_GATES_CONTRACT_INVALID")
    raw = quality.get("required_gates", ())
    if not isinstance(raw, (list, tuple)) or any(
        not isinstance(value, str) or not value.strip() for value in raw
    ):
        raise ValueError("FEATURE_REQUIRED_GATES_CONTRACT_INVALID")
    values = tuple(value.strip() for value in raw)
    if (
        values != tuple(sorted(set(values)))
        or any(value not in _DURABLE_OPTIONAL_FEATURE_GATES for value in values)
    ):
        raise ValueError("FEATURE_REQUIRED_GATES_CONTRACT_INVALID")
    return values


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


def feature_team_ids(value: object) -> tuple[str, str] | None:
    """Return one coherent home/away identity pair, or fail closed."""

    if not isinstance(value, Mapping):
        return None
    pairs: list[tuple[str, str]] = []
    for home_key, away_key in (
        ("home", "away"),
        ("home_team_id", "away_team_id"),
    ):
        home_raw = value.get(home_key)
        away_raw = value.get(away_key)
        if home_raw is None and away_raw is None:
            continue
        if not isinstance(home_raw, str) or not isinstance(away_raw, str):
            return None
        home = home_raw.strip()
        away = away_raw.strip()
        if not home or not away or home == away:
            return None
        pairs.append((home, away))
    if not pairs or any(pair != pairs[0] for pair in pairs[1:]):
        return None
    return pairs[0]


def feature_fixture_kickoff(value: object) -> datetime | None:
    """Return the receipt-bound fixture kickoff embedded in a team projection."""

    if not isinstance(value, Mapping):
        return None
    kickoff_raw = value.get("kickoff_at")
    if not isinstance(kickoff_raw, str) or not kickoff_raw.strip():
        return None
    try:
        return parse_utc(kickoff_raw, field="feature_fixture_kickoff")
    except ValueError:
        return None


def complete_lineup_feature(
    value: object,
    *,
    expected_team_ids: tuple[str, str],
) -> bool:
    """Validate two expected teams and twenty-two globally unique starters."""

    candidate: object = value
    if isinstance(candidate, Mapping):
        candidate = candidate.get("teams", candidate.get("lineups", candidate))
    entries: list[tuple[str, object]] = []
    if isinstance(candidate, Mapping):
        entries = [(str(team_id).strip(), roster) for team_id, roster in candidate.items()]
    elif isinstance(candidate, (list, tuple)):
        for item in candidate:
            if not isinstance(item, Mapping):
                return False
            team_id = str(item.get("team_id", "")).strip()
            roster = item.get("starters", item.get("starter_ids"))
            entries.append((team_id, roster))
    else:
        return False
    if (
        len(entries) != 2
        or {team_id for team_id, _ in entries} != set(expected_team_ids)
    ):
        return False
    all_player_ids: list[str] = []
    for team_id, roster in entries:
        if not team_id or not isinstance(roster, (list, tuple)) or len(roster) != 11:
            return False
        identities = [str(player_id).strip() for player_id in roster]
        if any(not player_id for player_id in identities) or len(set(identities)) != 11:
            return False
        all_player_ids.extend(identities)
    return len(set(all_player_ids)) == 22


def complete_injuries_feature(value: object) -> bool:
    """Validate a canonical injury collection; an attested empty list is valid."""

    if not isinstance(value, (list, tuple)):
        return False
    player_ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            return False
        player_id = str(item.get("player_id", "")).strip()
        status = str(item.get("status", "")).strip()
        if not player_id or not status:
            return False
        player_ids.append(player_id)
    return len(player_ids) == len(set(player_ids))


def prediction_record_id(
    *,
    fixture_record_id: str,
    cutoff_name: CutoffName,
    market: PredictionMarket,
    model_id: str,
    model_version: str,
) -> str:
    return "prediction-" + canonical_sha256(
        {
            "fixture_record_id": fixture_record_id,
            "cutoff": cutoff_name.value,
            "market": market.value,
            "model_id": model_id,
            "model_version": model_version,
        }
    )


def settlement_record_id(
    result: VerifiedFixtureResult,
    *,
    supersedes_id: str | None,
) -> str:
    return "settlement-" + canonical_sha256(
        {
            "fixture_record_id": result.fixture_record_id,
            "fixture_id": result.fixture_id,
            "result_hash": result.result_hash,
            "supersedes_id": supersedes_id,
        }
    )


def score_record_id(*, prediction_id: str, settlement_id: str) -> str:
    return "score-" + canonical_sha256(
        {
            "prediction_id": prediction_id,
            "settlement_id": settlement_id,
        }
    )


def source_receipt_from_provenance(
    evidence: Mapping[str, object],
) -> SourceReceipt:
    """Rebuild and validate the complete content-addressed source receipt."""

    required = (
        "receipt_id",
        "source_name",
        "request_identity",
        "payload_sha256",
        "robin_first_observed_at",
        "robin_ingested_at",
        "capture_code_revision",
        "storage_identity",
        "source_identity",
        "availability_status",
        "available_at",
    )
    if any(key not in evidence for key in required):
        raise ValueError("FEATURE_PROVENANCE_SOURCE_RECEIPT_REQUIRED")
    try:
        availability_status = TemporalProofLevel(
            str(evidence["availability_status"])
        )
    except ValueError as error:
        raise ValueError("FEATURE_PROVENANCE_AVAILABILITY_NOT_ATTESTED") from error
    source_published_raw = evidence.get("source_published_at")
    source_published_at = (
        parse_utc(str(source_published_raw), field="source_published_at")
        if source_published_raw is not None
        else None
    )
    event_raw = evidence.get("event_at")
    event_at = (
        parse_utc(str(event_raw), field="event_at")
        if event_raw is not None
        else None
    )
    supersedes_raw = evidence.get("supersedes_receipt_id")
    receipt = SourceReceipt(
        receipt_id=str(evidence["receipt_id"]),
        source_name=str(evidence["source_name"]),
        request_identity=str(evidence["request_identity"]),
        payload_sha256=str(evidence["payload_sha256"]),
        source_published_at=source_published_at,
        robin_first_observed_at=parse_utc(
            str(evidence["robin_first_observed_at"]),
            field="robin_first_observed_at",
        ),
        robin_ingested_at=parse_utc(
            str(evidence["robin_ingested_at"]),
            field="robin_ingested_at",
        ),
        capture_code_revision=str(evidence["capture_code_revision"]),
        storage_identity=str(evidence["storage_identity"]),
        availability_status=availability_status,
        supersedes_receipt_id=(
            str(supersedes_raw) if supersedes_raw is not None else None
        ),
        event_at=event_at,
    )
    if str(evidence["source_identity"]) != receipt.storage_identity:
        raise ValueError("FEATURE_PROVENANCE_STORAGE_IDENTITY_MISMATCH")
    if parse_utc(str(evidence["available_at"]), field="available_at") != (
        receipt.available_at
    ):
        raise ValueError("FEATURE_PROVENANCE_AVAILABLE_AT_INVALID")
    observed_raw = evidence.get("observed_at")
    if observed_raw is not None and parse_utc(
        str(observed_raw),
        field="observed_at",
    ) != receipt.robin_first_observed_at:
        raise ValueError("FEATURE_PROVENANCE_OBSERVED_AT_MISMATCH")
    return receipt


def validate_probabilities(
    market: PredictionMarket,
    probabilities: Mapping[str, float],
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
        object.__setattr__(self, "created_at", created)
        if self.training_cutoff is not None:
            object.__setattr__(self, "training_cutoff", cutoff)

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
        expected_provenance_families = {
            family
            for family, missing in self.missingness.items()
            if not missing
        }
        if set(self.provenance) != expected_provenance_families:
            raise ValueError("FEATURE_PROVENANCE_FAMILY_SET_INVALID")
        declared_optional_gates = durable_required_feature_gates(self.quality)
        if any(self.missingness.get(gate, True) for gate in declared_optional_gates):
            raise ValueError("FEATURE_REQUIRED_GATE_VALUE_MISSING")
        for family, missing in self.missingness.items():
            if missing and family in self.provenance:
                raise ValueError(
                    "FEATURE_PROVENANCE_FOR_MISSING_FAMILY_FORBIDDEN"
                )
            if missing and self.values.get(family) not in (None, {}, [], ()):
                raise ValueError("MISSING_FEATURE_MUST_NOT_BE_ZERO_FILLED")
            if not missing and self.values.get(family) is None:
                raise ValueError("AVAILABLE_FEATURE_VALUE_REQUIRED")
            if not missing and family == "team":
                team_value = self.values.get(family)
                if feature_team_ids(team_value) is None:
                    raise ValueError("AVAILABLE_TEAM_FEATURE_INVALID")
                if (
                    not isinstance(team_value, Mapping)
                    or team_value.get("competition") != self.competition
                    or feature_fixture_kickoff(team_value)
                    != cutoff
                    + timedelta(
                        minutes=CUTOFF_MINUTES_BEFORE_KICKOFF[self.cutoff_name]
                    )
                    or not str(team_value.get("provider", "")).strip()
                    or not str(
                        team_value.get("provider_fixture_id", "")
                    ).strip()
                ):
                    raise ValueError(
                        "AVAILABLE_TEAM_FIXTURE_PROJECTION_INVALID"
                    )
            if not missing and family == "lineup":
                expected_team_ids = feature_team_ids(self.values.get("team"))
                if expected_team_ids is None or not complete_lineup_feature(
                    self.values.get(family),
                    expected_team_ids=expected_team_ids,
                ):
                    raise ValueError("AVAILABLE_LINEUP_FEATURE_INVALID")
            if not missing and family == "injuries":
                if not complete_injuries_feature(self.values.get(family)):
                    raise ValueError("AVAILABLE_INJURIES_FEATURE_INVALID")
            if not missing and family == "market":
                market_value = self.values.get(family)
                decimal_odds = (
                    market_value.get("decimal_odds")
                    if isinstance(market_value, Mapping)
                    else None
                )
                expected_selections = set(_market_selections(self.market))
                if (
                    not isinstance(decimal_odds, Mapping)
                    or set(decimal_odds) != expected_selections
                    or any(
                        not isinstance(odd, (int, float))
                        or isinstance(odd, bool)
                        or not isfinite(float(odd))
                        or float(odd) <= 1.0
                        for odd in decimal_odds.values()
                    )
                ):
                    raise ValueError("AVAILABLE_MARKET_FEATURE_INVALID")
        for family, missing in self.missingness.items():
            if missing:
                continue
            evidence = self.provenance.get(family)
            if not isinstance(evidence, Mapping):
                raise ValueError(f"FEATURE_PROVENANCE_REQUIRED:{family}")
            receipt = source_receipt_from_provenance(evidence)
            if receipt.available_at > cutoff:
                raise ValueError("FEATURE_PROVENANCE_AFTER_CUTOFF")
            if receipt.robin_ingested_at > cutoff:
                raise ValueError("FEATURE_PROVENANCE_INGESTED_AFTER_CUTOFF")
            if (
                receipt.available_at > created
                or receipt.robin_ingested_at > created
            ):
                raise ValueError("FEATURE_PROVENANCE_AFTER_SNAPSHOT_CREATION")
        frozen_values = freeze_json(self.values)
        frozen_missingness = freeze_json(self.missingness)
        frozen_provenance = freeze_json(self.provenance)
        frozen_quality = freeze_json(self.quality)
        if not all(
            isinstance(value, dict) or hasattr(value, "items")
            for value in (
                frozen_values,
                frozen_missingness,
                frozen_provenance,
                frozen_quality,
            )
        ):
            raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_JSON_INVALID")
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "values", frozen_values)
        object.__setattr__(self, "missingness", frozen_missingness)
        object.__setattr__(self, "provenance", frozen_provenance)
        object.__setattr__(self, "quality", frozen_quality)

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
            "values": thaw_json(self.values),
            "missingness": thaw_json(self.missingness),
            "provenance": thaw_json(self.provenance),
            "quality": thaw_json(self.quality),
            "code_revision": self.code_revision,
            "supersedes_id": self.supersedes_id,
            "status": self.status,
        }
        if include_storage:
            value["r2_manifest_key"] = self.r2_manifest_key
        return value

    def storage_manifest(self) -> dict[str, object]:
        """Exact content-addressed manifest persisted in the artifact store."""

        return {
            "schema_version": "prequential-feature-snapshot-v1",
            **self.as_manifest(include_storage=False),
        }

    @property
    def temporal_lineage_hash(self) -> str:
        return canonical_sha256(
            {
                "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
                "fixture_record_id": self.fixture_record_id,
                "cutoff_at": self.cutoff_at.isoformat(),
                "feature_contract_hash": self.feature_contract_hash,
                "provenance": thaw_json(self.provenance),
            }
        )


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
    probabilities: Mapping[str, float]
    market_probabilities: Mapping[str, float] | None
    odds_snapshot_id: str | None
    code_revision: str
    status: PredictionStatus
    scientific_kernel_version: str
    devig_method: str
    devig_version: str
    devig_definition_hash: str
    roi_definition_version: str
    turnover_definition_version: str
    yield_definition_version: str
    decision_threshold_version: str
    staking_version: str
    settlement_version: str
    rejection_reason: str | None = None
    persisted_payload_hash: str | None = None

    def __post_init__(self) -> None:
        cutoff = ensure_utc(self.cutoff_at, field="cutoff_at")
        kickoff = ensure_utc(self.kickoff_at, field="kickoff_at")
        predicted = ensure_utc(self.predicted_at, field="predicted_at")
        expected_kernel = kernel_versions(self.devig_method)
        actual_kernel = {
            key: getattr(self, key)
            for key in expected_kernel
        }
        if actual_kernel != expected_kernel:
            raise ValueError("PREQUENTIAL_SCIENTIFIC_KERNEL_METADATA_INVALID")
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
            if kickoff - cutoff != timedelta(
                minutes=CUTOFF_MINUTES_BEFORE_KICKOFF[self.cutoff_name]
            ):
                raise ValueError("PREQUENTIAL_CUTOFF_POLICY_MISMATCH")
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
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "kickoff_at", kickoff)
        object.__setattr__(self, "predicted_at", predicted)
        frozen_probabilities = freeze_json(self.probabilities)
        frozen_market_probabilities = (
            freeze_json(self.market_probabilities)
            if self.market_probabilities is not None
            else None
        )
        if not isinstance(frozen_probabilities, Mapping) or (
            frozen_market_probabilities is not None
            and not isinstance(frozen_market_probabilities, Mapping)
        ):
            raise ValueError("PREQUENTIAL_PREDICTION_JSON_INVALID")
        object.__setattr__(
            self,
            "probabilities",
            cast(Mapping[str, float], frozen_probabilities),
        )
        object.__setattr__(
            self,
            "market_probabilities",
            cast(Mapping[str, float] | None, frozen_market_probabilities),
        )
        if self.persisted_payload_hash is not None and (
            len(self.persisted_payload_hash) != SHA256_LENGTH
            or self.persisted_payload_hash
            not in {self.computed_payload_hash, self.legacy_payload_hash}
        ):
            raise ValueError("PREQUENTIAL_PERSISTED_PAYLOAD_HASH_INVALID")

    def _payload_content(self) -> dict[str, object]:
        return {
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
            "probabilities": thaw_json(self.probabilities),
            "market_probabilities": thaw_json(self.market_probabilities),
            "odds_snapshot_id": self.odds_snapshot_id,
            "code_revision": self.code_revision,
            "status": self.status.value,
            "scientific_kernel_version": self.scientific_kernel_version,
            "devig_method": self.devig_method,
            "devig_version": self.devig_version,
            "devig_definition_hash": self.devig_definition_hash,
            "roi_definition_version": self.roi_definition_version,
            "turnover_definition_version": self.turnover_definition_version,
            "yield_definition_version": self.yield_definition_version,
            "decision_threshold_version": self.decision_threshold_version,
            "staking_version": self.staking_version,
            "settlement_version": self.settlement_version,
            "rejection_reason": self.rejection_reason,
        }

    @property
    def computed_payload_hash(self) -> str:
        """Hash of the current in-memory scientific payload definition."""

        return canonical_sha256(self._payload_content())

    @property
    def payload_hash(self) -> str:
        """Durable identity when loaded, otherwise the current candidate hash."""

        return self.persisted_payload_hash or self.computed_payload_hash

    @property
    def legacy_payload_hash(self) -> str:
        """Hash emitted before scientific lineage was added to predictions."""

        payload = self._payload_content()
        for field_name in kernel_versions(self.devig_method):
            payload.pop(field_name, None)
        return canonical_sha256(payload)

    @property
    def scientific_lineage_status(self) -> str:
        if self.persisted_payload_hash is None:
            return "SCIENTIFIC_LINEAGE_DECLARED_IN_MEMORY"
        if self.persisted_payload_hash == self.computed_payload_hash:
            return "SCIENTIFIC_LINEAGE_PERSISTED_EXACT"
        return "SCIENTIFIC_LINEAGE_NOT_PERSISTED"

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        value = self._payload_content()
        if include_hash:
            value["payload_hash"] = self.payload_hash
            value["scientific_lineage_status"] = self.scientific_lineage_status
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
        object.__setattr__(self, "kickoff_at", kickoff)
        object.__setattr__(self, "verified_at", verified)

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
        expected_effective_status = (
            PredictionStatus.SETTLED
            if self.result.status
            in {FixtureResultStatus.FINISHED, FixtureResultStatus.CORRECTED}
            else PredictionStatus.VOID
            if self.result.status
            in {FixtureResultStatus.CANCELLED, FixtureResultStatus.ABANDONED}
            else None
        )
        if (
            not self.settlement_id
            or settled < self.result.verified_at
            or self.effective_status
            not in {PredictionStatus.SETTLED, PredictionStatus.VOID}
            or self.effective_status is not expected_effective_status
        ):
            raise ValueError("PREQUENTIAL_SETTLEMENT_INVALID")
        object.__setattr__(self, "settled_at", settled)

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
        scored = ensure_utc(self.scored_at, field="scored_at")
        expected_outcomes = set(_market_selections(self.market))
        if (
            not self.score_id
            or not self.prediction_id
            or not self.settlement_id
            or self.outcome not in expected_outcomes
            or not isinstance(self.accurate, bool)
            or isinstance(self.log_loss, bool)
            or isinstance(self.brier_score, bool)
            or not isfinite(self.log_loss)
            or not isfinite(self.brier_score)
            or self.log_loss < 0
            or self.brier_score < 0
            or (
                self.reference_log_loss_delta is not None
                and (
                    isinstance(self.reference_log_loss_delta, bool)
                    or not isfinite(self.reference_log_loss_delta)
                )
            )
        ):
            raise ValueError("PREQUENTIAL_SCORE_INVALID")
        object.__setattr__(self, "scored_at", scored)

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
        frozen_hyperparameters = freeze_json(self.hyperparameters)
        frozen_metrics = freeze_json(self.training_metrics)
        if not isinstance(frozen_hyperparameters, Mapping) or not isinstance(
            frozen_metrics,
            Mapping,
        ):
            raise ValueError("TRAINING_DATASET_JSON_INVALID")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "training_cutoff", cutoff)
        object.__setattr__(self, "hyperparameters", frozen_hyperparameters)
        object.__setattr__(self, "training_metrics", frozen_metrics)

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
            "hyperparameters": thaw_json(self.hyperparameters),
            "training_metrics": thaw_json(self.training_metrics),
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
    details: Mapping[str, Any] = field(default_factory=dict)
    previous_hash: str = "0" * SHA256_LENGTH
    production_status: str = PRODUCTION_LOCKED
    real_bets: bool = False
    promoted: bool = False

    def __post_init__(self) -> None:
        recorded_at = ensure_utc(self.recorded_at, field="recorded_at")
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
        frozen_details = freeze_json(self.details)
        if not isinstance(frozen_details, Mapping):
            raise ValueError("PREQUENTIAL_LEDGER_EVENT_DETAILS_INVALID")
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "details", frozen_details)

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
                "details": thaw_json(self.details),
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
    "complete_injuries_feature",
    "complete_lineup_feature",
    "CUTOFF_MINUTES_BEFORE_KICKOFF",
    "durable_required_feature_gates",
    "feature_fixture_kickoff",
    "feature_team_ids",
    "source_receipt_from_provenance",
    "prediction_record_id",
    "score_record_id",
    "settlement_record_id",
    "validate_probabilities",
]
