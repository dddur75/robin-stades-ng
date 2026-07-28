"""Leakage-safe prequential prediction and challenger update protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from robin.prospective_observatory.contracts import canonical_sha256, ensure_utc


class PrequentialEventKind(StrEnum):
    PREDICTION_FROZEN = "PREDICTION_FROZEN"
    MATCH_SETTLED = "MATCH_SETTLED"
    CHALLENGER_TRAINING_ELIGIBLE = "CHALLENGER_TRAINING_ELIGIBLE"
    CHALLENGER_UPDATED = "CHALLENGER_UPDATED"
    REFERENCE_UNCHANGED = "REFERENCE_UNCHANGED"


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


class ShadowAction(StrEnum):
    NO_BET = "NO_BET"
    SHADOW_DECISION = "SHADOW_DECISION"


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_id: str
    scope: ModelScope
    role: ModelRole
    version: str
    artifact_sha256: str
    created_at: datetime
    frozen: bool = True

    def __post_init__(self) -> None:
        ensure_utc(self.created_at, field="created_at")
        if (
            not self.model_id
            or not self.version
            or len(self.artifact_sha256) != 64
            or not self.frozen
        ):
            raise ValueError("PREQUENTIAL_MODEL_VERSION_INVALID")


@dataclass(frozen=True, slots=True)
class FrozenPrediction:
    fixture_id: str
    competition: str
    model_id: str
    model_version: str
    features_sha256: str
    cutoff_at: datetime
    frozen_at: datetime
    kickoff_at: datetime
    odds_sha256: str | None
    shadow_action: ShadowAction
    prediction_payload_sha256: str

    def __post_init__(self) -> None:
        cutoff = ensure_utc(self.cutoff_at, field="cutoff_at")
        frozen = ensure_utc(self.frozen_at, field="frozen_at")
        kickoff = ensure_utc(self.kickoff_at, field="kickoff_at")
        hashes = (
            self.features_sha256,
            self.prediction_payload_sha256,
            *(() if self.odds_sha256 is None else (self.odds_sha256,)),
        )
        if (
            not self.fixture_id
            or not self.competition
            or not self.model_id
            or not self.model_version
            or any(len(value) != 64 for value in hashes)
            or not cutoff <= frozen < kickoff
        ):
            raise ValueError("PREQUENTIAL_PREDICTION_INVALID")

    @property
    def prediction_hash(self) -> str:
        return canonical_sha256(
            {
                "fixture_id": self.fixture_id,
                "competition": self.competition,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "features_sha256": self.features_sha256,
                "cutoff_at": self.cutoff_at.isoformat(),
                "frozen_at": self.frozen_at.isoformat(),
                "kickoff_at": self.kickoff_at.isoformat(),
                "odds_sha256": self.odds_sha256,
                "shadow_action": self.shadow_action.value,
                "prediction_payload_sha256": self.prediction_payload_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class MatchSettlement:
    fixture_id: str
    result_sha256: str
    settled_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.settled_at, field="settled_at")
        if not self.fixture_id or len(self.result_sha256) != 64:
            raise ValueError("PREQUENTIAL_SETTLEMENT_INVALID")


@dataclass(frozen=True, slots=True)
class PrequentialEvent:
    sequence_no: int
    kind: PrequentialEventKind
    fixture_id: str | None
    model_id: str
    model_version: str
    recorded_at: datetime
    evidence_hashes: tuple[str, ...]
    previous_hash: str
    event_hash: str
    production_status: str = "PRODUCTION_LOCKED"
    real_bets: bool = False
    promoted: bool = False


class PrequentialLedger:
    """Append-only state machine; challenger training is post-settlement only."""

    def __init__(self, models: tuple[ModelVersion, ...]) -> None:
        keys = {(model.model_id, model.version) for model in models}
        if len(keys) != len(models):
            raise ValueError("PREQUENTIAL_MODEL_VERSION_DUPLICATED")
        reference_scopes = {
            model.scope for model in models if model.role is ModelRole.REFERENCE
        }
        if reference_scopes != set(ModelScope):
            raise ValueError("PREQUENTIAL_REFERENCE_SCOPE_INCOMPLETE")
        self._models = {
            (model.model_id, model.version): model for model in models
        }
        self._events: list[PrequentialEvent] = []
        self._predictions: dict[tuple[str, str, str], FrozenPrediction] = {}
        self._settlements: dict[str, MatchSettlement] = {}
        self._eligible: set[tuple[str, str, str]] = set()

    @property
    def events(self) -> tuple[PrequentialEvent, ...]:
        return tuple(self._events)

    def _append(
        self,
        *,
        kind: PrequentialEventKind,
        fixture_id: str | None,
        model_id: str,
        model_version: str,
        recorded_at: datetime,
        evidence_hashes: tuple[str, ...],
    ) -> PrequentialEvent:
        recorded = ensure_utc(recorded_at, field="recorded_at")
        if any(len(value) != 64 for value in evidence_hashes):
            raise ValueError("PREQUENTIAL_EVIDENCE_HASH_INVALID")
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        body = {
            "sequence_no": len(self._events),
            "kind": kind.value,
            "fixture_id": fixture_id,
            "model_id": model_id,
            "model_version": model_version,
            "recorded_at": recorded.isoformat(),
            "evidence_hashes": list(evidence_hashes),
            "previous_hash": previous_hash,
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "promoted": False,
        }
        event = PrequentialEvent(
            sequence_no=len(self._events),
            kind=kind,
            fixture_id=fixture_id,
            model_id=model_id,
            model_version=model_version,
            recorded_at=recorded,
            evidence_hashes=evidence_hashes,
            previous_hash=previous_hash,
            event_hash=canonical_sha256(body),
        )
        self._events.append(event)
        return event

    def freeze_prediction(self, prediction: FrozenPrediction) -> PrequentialEvent:
        model_key = (prediction.model_id, prediction.model_version)
        model = self._models.get(model_key)
        if model is None or not model.frozen:
            raise ValueError("PREQUENTIAL_MODEL_VERSION_NOT_FROZEN")
        expected_competition = {
            ModelScope.LIGUE_1: "Ligue 1",
            ModelScope.PREMIER_LEAGUE: "Premier League",
            ModelScope.LIGA: "Liga",
            ModelScope.BUNDESLIGA: "Bundesliga",
            ModelScope.SERIE_A: "Serie A",
        }.get(model.scope)
        if (
            expected_competition is not None
            and prediction.competition != expected_competition
        ):
            raise ValueError("PREQUENTIAL_MODEL_SCOPE_MISMATCH")
        key = (prediction.fixture_id, *model_key)
        existing = self._predictions.get(key)
        if existing is not None:
            if existing != prediction:
                raise ValueError("PREQUENTIAL_PREDICTION_IMMUTABILITY_CONFLICT")
            return next(
                event
                for event in self._events
                if event.kind is PrequentialEventKind.PREDICTION_FROZEN
                and event.fixture_id == prediction.fixture_id
                and event.model_id == prediction.model_id
                and event.model_version == prediction.model_version
            )
        if prediction.fixture_id in self._settlements:
            raise ValueError("PREQUENTIAL_PREDICTION_AFTER_SETTLEMENT_REJECTED")
        self._predictions[key] = prediction
        return self._append(
            kind=PrequentialEventKind.PREDICTION_FROZEN,
            fixture_id=prediction.fixture_id,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            recorded_at=prediction.frozen_at,
            evidence_hashes=(
                prediction.features_sha256,
                prediction.prediction_payload_sha256,
                prediction.prediction_hash,
            ),
        )

    def settle(self, settlement: MatchSettlement) -> tuple[PrequentialEvent, ...]:
        predictions = tuple(
            (key, prediction)
            for key, prediction in self._predictions.items()
            if prediction.fixture_id == settlement.fixture_id
        )
        if not predictions:
            raise ValueError("PREQUENTIAL_SETTLEMENT_WITHOUT_PREDICTION")
        if any(settlement.settled_at <= prediction.kickoff_at for _, prediction in predictions):
            raise ValueError("PREQUENTIAL_SETTLEMENT_BEFORE_KICKOFF_REJECTED")
        existing = self._settlements.get(settlement.fixture_id)
        if existing is not None:
            if existing != settlement:
                raise ValueError("PREQUENTIAL_SETTLEMENT_IMMUTABILITY_CONFLICT")
            return ()
        self._settlements[settlement.fixture_id] = settlement
        output: list[PrequentialEvent] = []
        for key, prediction in predictions:
            output.append(
                self._append(
                    kind=PrequentialEventKind.MATCH_SETTLED,
                    fixture_id=settlement.fixture_id,
                    model_id=prediction.model_id,
                    model_version=prediction.model_version,
                    recorded_at=settlement.settled_at,
                    evidence_hashes=(
                        prediction.prediction_hash,
                        settlement.result_sha256,
                    ),
                )
            )
            model = self._models[(prediction.model_id, prediction.model_version)]
            if model.role is ModelRole.CHALLENGER:
                self._eligible.add(key)
                output.append(
                    self._append(
                        kind=PrequentialEventKind.CHALLENGER_TRAINING_ELIGIBLE,
                        fixture_id=settlement.fixture_id,
                        model_id=prediction.model_id,
                        model_version=prediction.model_version,
                        recorded_at=settlement.settled_at,
                        evidence_hashes=(
                            prediction.prediction_hash,
                            settlement.result_sha256,
                        ),
                    )
                )
            else:
                output.append(
                    self._append(
                        kind=PrequentialEventKind.REFERENCE_UNCHANGED,
                        fixture_id=settlement.fixture_id,
                        model_id=prediction.model_id,
                        model_version=prediction.model_version,
                        recorded_at=settlement.settled_at,
                        evidence_hashes=(model.artifact_sha256,),
                    )
                )
        return tuple(output)

    def update_challenger(
        self,
        *,
        fixture_id: str,
        model_id: str,
        previous_version: str,
        next_model: ModelVersion,
        training_dataset_sha256: str,
        updated_at: datetime,
    ) -> PrequentialEvent:
        key = (fixture_id, model_id, previous_version)
        if key not in self._eligible:
            raise ValueError("PREQUENTIAL_TRAINING_BEFORE_SETTLEMENT_REJECTED")
        previous = self._models.get((model_id, previous_version))
        settlement = self._settlements.get(fixture_id)
        update_time = ensure_utc(updated_at, field="updated_at")
        if (
            previous is None
            or settlement is None
            or previous.role is not ModelRole.CHALLENGER
            or next_model.role is not ModelRole.CHALLENGER
            or next_model.model_id != model_id
            or next_model.scope is not previous.scope
            or next_model.version == previous_version
            or len(training_dataset_sha256) != 64
            or update_time < settlement.settled_at
            or next_model.created_at < settlement.settled_at
        ):
            raise ValueError("PREQUENTIAL_CHALLENGER_UPDATE_INVALID")
        next_key = (next_model.model_id, next_model.version)
        if next_key in self._models:
            raise ValueError("PREQUENTIAL_MODEL_VERSION_DUPLICATED")
        self._models[next_key] = next_model
        self._eligible.remove(key)
        return self._append(
            kind=PrequentialEventKind.CHALLENGER_UPDATED,
            fixture_id=fixture_id,
            model_id=model_id,
            model_version=next_model.version,
            recorded_at=update_time,
            evidence_hashes=(
                previous.artifact_sha256,
                training_dataset_sha256,
                next_model.artifact_sha256,
            ),
        )

    def audit(self) -> dict[str, object]:
        previous_hash = "0" * 64
        for sequence, event in enumerate(self._events):
            body = {
                "sequence_no": event.sequence_no,
                "kind": event.kind.value,
                "fixture_id": event.fixture_id,
                "model_id": event.model_id,
                "model_version": event.model_version,
                "recorded_at": event.recorded_at.isoformat(),
                "evidence_hashes": list(event.evidence_hashes),
                "previous_hash": event.previous_hash,
                "production_status": event.production_status,
                "real_bets": event.real_bets,
                "promoted": event.promoted,
            }
            if (
                event.sequence_no != sequence
                or event.previous_hash != previous_hash
                or event.event_hash != canonical_sha256(body)
                or event.production_status != "PRODUCTION_LOCKED"
                or event.real_bets
                or event.promoted
            ):
                return {"status": "PREQUENTIAL_LEDGER_INVALID", "sequence": sequence}
            previous_hash = event.event_hash
        return {
            "status": "PREQUENTIAL_LEDGER_VERIFIED",
            "events": len(self._events),
            "head_hash": previous_hash,
            "reference_updates": 0,
            "promotions": 0,
        }
