"""Five-league prediction, settlement and learning factory."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from robin.market_math import (
    DevigMethod,
    kernel_versions,
    normalize_method,
)
from robin.market_math import (
    devig_probabilities as kernel_devig_probabilities,
)
from robin.prospective_observatory.contracts import canonical_sha256, ensure_utc
from robin.prospective_observatory.feature_snapshots import FeatureSnapshotRegistry
from robin.prospective_observatory.prequential_contracts import (
    FIVE_LEAGUE_NAMES,
    PROMOTION_LOCKED,
    CutoffName,
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionScore,
    PredictionStatus,
    PrequentialEventKind,
    PrequentialLedgerEvent,
    TrainingDecision,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_settlement import SettlementRegistry
from robin.prospective_observatory.prequential_storage import (
    PrequentialArtifactRepository,
)
from robin.prospective_observatory.prequential_training import (
    train_challenger_if_eligible,
)


def devig_probabilities(
    market: PredictionMarket,
    decimal_odds: Mapping[str, float],
    *,
    devig_method: DevigMethod | str,
) -> tuple[dict[str, float], float]:
    expected = (
        ("HOME", "DRAW", "AWAY")
        if market is PredictionMarket.ONE_X_TWO
        else ("OVER", "UNDER")
    )
    if set(decimal_odds) != set(expected):
        raise ValueError("PREQUENTIAL_ODDS_SELECTIONS_INVALID")
    result = kernel_devig_probabilities(
        [decimal_odds[selection] for selection in expected],
        method=devig_method,
        outcome_labels=expected,
    )
    return (
        {
            selection: probability
            for selection, probability in zip(
                expected,
                result.fair_probabilities,
                strict=True,
            )
        },
        result.overround,
    )


def initial_model_versions(
    *,
    created_at: datetime,
    feature_contract_hash: str,
    code_revision: str,
) -> tuple[ModelVersion, ...]:
    reference_artifact_hash = canonical_sha256(
        {
            "family": "DEVIGGED_MARKET_REFERENCE",
            "markets": ["1X2", "OVER_UNDER_2_5"],
            "immutable": True,
        }
    )
    references = tuple(
        ModelVersion(
            model_id=f"reference-{scope.value.casefold()}",
            scope=scope,
            role=ModelRole.REFERENCE,
            version="market-devigged-v1",
            artifact_sha256=reference_artifact_hash,
            created_at=created_at,
            training_cutoff=None,
            feature_contract_hash=feature_contract_hash,
            code_revision=code_revision,
            status=ModelStatus.FROZEN_REFERENCE,
        )
        for scope in ModelScope
    )
    challengers = tuple(
        ModelVersion(
            model_id=f"challenger-{scope.value.casefold()}",
            scope=scope,
            role=ModelRole.CHALLENGER,
            version="untrained-v1",
            artifact_sha256=canonical_sha256(
                {
                    "family": "UNTRAINED_CHALLENGER",
                    "scope": scope.value,
                    "predictions": 0,
                }
            ),
            created_at=created_at,
            training_cutoff=None,
            feature_contract_hash=feature_contract_hash,
            code_revision=code_revision,
            status=ModelStatus.INSUFFICIENT_TRAINING_SUPPORT,
        )
        for scope in ModelScope
    )
    return (*references, *challengers)


class HashChainedPrequentialLedger:
    """Deterministic global chain; persistence serialises appends transactionally."""

    def __init__(self) -> None:
        self._events: list[PrequentialLedgerEvent] = []

    @property
    def events(self) -> tuple[PrequentialLedgerEvent, ...]:
        return tuple(self._events)

    def restore(self, event: PrequentialLedgerEvent) -> None:
        expected_sequence = len(self._events)
        expected_previous = (
            self._events[-1].event_hash if self._events else "0" * 64
        )
        if (
            event.sequence_no != expected_sequence
            or event.previous_hash != expected_previous
        ):
            raise ValueError("PREQUENTIAL_LEDGER_RESTORE_CHAIN_INVALID")
        self._events.append(event)

    def append(
        self,
        *,
        kind: PrequentialEventKind,
        recorded_at: datetime,
        stream_key: str,
        evidence_hashes: tuple[str, ...],
        fixture_id: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> PrequentialLedgerEvent:
        previous_hash = (
            self._events[-1].event_hash if self._events else "0" * 64
        )
        sequence_no = len(self._events)
        event_id = "event-" + canonical_sha256(
            {
                "sequence_no": sequence_no,
                "kind": kind.value,
                "recorded_at": recorded_at.isoformat(),
                "stream_key": stream_key,
                "evidence_hashes": list(evidence_hashes),
                "previous_hash": previous_hash,
            }
        )
        event = PrequentialLedgerEvent(
            event_id=event_id,
            sequence_no=sequence_no,
            kind=kind,
            recorded_at=recorded_at,
            stream_key=stream_key,
            fixture_id=fixture_id,
            model_id=model_id,
            model_version=model_version,
            evidence_hashes=evidence_hashes,
            details=dict(details or {}),
            previous_hash=previous_hash,
        )
        self._events.append(event)
        return event

    def audit(self) -> dict[str, object]:
        previous_hash = "0" * 64
        for expected_sequence, event in enumerate(self._events):
            if (
                event.sequence_no != expected_sequence
                or event.previous_hash != previous_hash
                or event.real_bets
                or event.promoted
            ):
                return {
                    "status": "PREQUENTIAL_LEDGER_INVALID",
                    "sequence": expected_sequence,
                }
            previous_hash = event.event_hash
        return {
            "status": "PREQUENTIAL_LEDGER_VERIFIED",
            "events": len(self._events),
            "head_hash": previous_hash,
            "promotion_status": PROMOTION_LOCKED,
        }


class PredictionRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, FrozenPredictionRecord] = {}
        self._by_business_key: dict[
            tuple[str, CutoffName, PredictionMarket, str, str],
            FrozenPredictionRecord,
        ] = {}

    @property
    def predictions(self) -> tuple[FrozenPredictionRecord, ...]:
        return tuple(self._by_id.values())

    def append(self, prediction: FrozenPredictionRecord) -> tuple[FrozenPredictionRecord, bool]:
        key = (
            prediction.fixture_record_id,
            prediction.cutoff_name,
            prediction.market,
            prediction.model_id,
            prediction.model_version,
        )
        existing = self._by_business_key.get(key)
        if existing is not None:
            if (
                existing.status is not prediction.status
                or existing.payload_hash != prediction.payload_hash
            ):
                # Retrying a frozen row at a later wall-clock time must return
                # the original row; changing its meaning is forbidden.
                stable_existing = existing.as_dict(include_hash=False)
                stable_candidate = prediction.as_dict(include_hash=False)
                stable_existing.pop("predicted_at")
                stable_candidate.pop("predicted_at")
                if stable_existing != stable_candidate:
                    raise ValueError("PREQUENTIAL_PREDICTION_IMMUTABILITY_CONFLICT")
            return existing, False
        by_id = self._by_id.get(prediction.prediction_id)
        if by_id is not None and by_id != prediction:
            raise ValueError("PREQUENTIAL_PREDICTION_ID_CONFLICT")
        self._by_id[prediction.prediction_id] = prediction
        self._by_business_key[key] = prediction
        return prediction, True


class PrequentialLearningFactory:
    def __init__(
        self,
        *,
        artifact_repository: PrequentialArtifactRepository,
        models: Iterable[ModelVersion],
        devig_method: DevigMethod | str,
    ) -> None:
        model_rows = tuple(models)
        keys = {(model.model_id, model.version) for model in model_rows}
        if len(keys) != len(model_rows):
            raise ValueError("PREQUENTIAL_MODEL_VERSION_DUPLICATED")
        reference_scopes = {
            model.scope
            for model in model_rows
            if model.role is ModelRole.REFERENCE
        }
        if reference_scopes != set(ModelScope):
            raise ValueError("PREQUENTIAL_REFERENCE_SCOPE_INCOMPLETE")
        challenger_scopes = {
            model.scope
            for model in model_rows
            if model.role is ModelRole.CHALLENGER
        }
        if challenger_scopes != set(ModelScope):
            raise ValueError("PREQUENTIAL_CHALLENGER_SCOPE_INCOMPLETE")
        self.artifact_repository = artifact_repository
        self.devig_method = normalize_method(devig_method)
        if self.devig_method is not DevigMethod.PROPORTIONAL:
            # The current durable prediction schema predates scientific-kernel
            # metadata.  Loading those rows is reproducible only for the
            # protocol historically executed by this factory.  Fail closed
            # instead of accepting a method that the store cannot round-trip.
            raise ValueError("PREQUENTIAL_DEVIG_PROTOCOL_UNSUPPORTED")
        self.models: dict[tuple[str, str], ModelVersion] = {
            (model.model_id, model.version): model for model in model_rows
        }
        self.features = FeatureSnapshotRegistry()
        self.predictions = PredictionRegistry()
        self.settlements = SettlementRegistry()
        self.ledger = HashChainedPrequentialLedger()
        self.training_decisions: list[TrainingDecision] = []

    def register_snapshot(self, snapshot: object) -> bool:
        from robin.prospective_observatory.prequential_contracts import (
            FeatureSnapshot,
        )

        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("FEATURE_SNAPSHOT_REQUIRED")
        inserted = self.features.append(snapshot)
        event_exists = any(
            event.kind is PrequentialEventKind.FEATURE_SNAPSHOT_FROZEN
            and snapshot.snapshot_hash in event.evidence_hashes
            for event in self.ledger.events
        )
        if not event_exists:
            self.ledger.append(
                kind=PrequentialEventKind.FEATURE_SNAPSHOT_FROZEN,
                recorded_at=snapshot.created_at,
                stream_key=f"fixture:{snapshot.fixture_id}",
                fixture_id=snapshot.fixture_id,
                evidence_hashes=(snapshot.snapshot_hash,),
                details={
                    "cutoff": snapshot.cutoff_name.value,
                    "market": snapshot.market.value,
                },
            )
        return bool(inserted)

    @staticmethod
    def _scope_allows(model: ModelVersion, competition: str) -> bool:
        expected = FIVE_LEAGUE_NAMES.get(model.scope)
        return expected is None or expected == competition

    def forecast(
        self,
        *,
        fixture_record_id: str,
        fixture_id: str,
        competition: str,
        market: PredictionMarket,
        cutoff_name: CutoffName,
        cutoff_at: datetime,
        kickoff_at: datetime,
        predicted_at: datetime,
        model_id: str,
        model_version: str,
        feature_snapshot_id: str | None,
        gate_statuses: Mapping[str, bool],
        required_gates: Iterable[str],
        decimal_odds: Mapping[str, float] | None,
        odds_snapshot_id: str | None,
        challenger_probabilities: Mapping[str, float] | None,
        code_revision: str,
    ) -> FrozenPredictionRecord:
        model = self.models.get((model_id, model_version))
        if model is None or not model.frozen:
            raise ValueError("PREQUENTIAL_MODEL_VERSION_NOT_FROZEN")
        if not self._scope_allows(model, competition):
            raise ValueError("PREQUENTIAL_MODEL_SCOPE_MISMATCH")
        predicted = ensure_utc(predicted_at, field="predicted_at")
        cutoff = ensure_utc(cutoff_at, field="cutoff_at")
        identity = canonical_sha256(
            {
                "fixture_record_id": fixture_record_id,
                "cutoff": cutoff_name.value,
                "market": market.value,
                "model_id": model_id,
                "model_version": model_version,
            }
        )
        prediction_id = f"prediction-{identity}"
        status = PredictionStatus.FROZEN
        rejection_reason: str | None = None
        probabilities: dict[str, float] = {}
        market_probabilities: dict[str, float] | None = None
        if predicted > cutoff:
            status = PredictionStatus.REJECTED_LATE
            rejection_reason = "PREDICTION_CUTOFF_EXCEEDED"
        else:
            missing_gates = sorted(
                gate for gate in required_gates if not gate_statuses.get(gate, False)
            )
            if missing_gates:
                status = PredictionStatus.REJECTED_MISSING_GATE
                rejection_reason = "MISSING_GATES:" + ",".join(missing_gates)
            elif decimal_odds is None:
                status = PredictionStatus.NO_ODDS_REFERENCE
                rejection_reason = "NO_ADMISSIBLE_ODDS_BEFORE_CUTOFF"
            else:
                market_probabilities, _margin = devig_probabilities(
                    market,
                    decimal_odds,
                    devig_method=self.devig_method,
                )
                if model.role is ModelRole.REFERENCE:
                    probabilities = dict(market_probabilities)
                elif model.status is ModelStatus.INSUFFICIENT_TRAINING_SUPPORT:
                    status = PredictionStatus.REJECTED_MISSING_GATE
                    rejection_reason = "INSUFFICIENT_TRAINING_SUPPORT"
                elif challenger_probabilities is None:
                    status = PredictionStatus.REJECTED_MISSING_GATE
                    rejection_reason = "CHALLENGER_PROBABILITIES_UNAVAILABLE"
                else:
                    probabilities = dict(challenger_probabilities)
        prediction = FrozenPredictionRecord(
            prediction_id=prediction_id,
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition=competition,
            market=market,
            cutoff_name=cutoff_name,
            cutoff_at=cutoff_at,
            kickoff_at=kickoff_at,
            predicted_at=predicted_at,
            model_id=model_id,
            model_version=model_version,
            feature_snapshot_id=feature_snapshot_id,
            probabilities=probabilities,
            market_probabilities=market_probabilities,
            odds_snapshot_id=odds_snapshot_id,
            code_revision=code_revision,
            status=status,
            rejection_reason=rejection_reason,
            **kernel_versions(self.devig_method),
        )
        stored, inserted = self.predictions.append(prediction)
        if inserted:
            self.ledger.append(
                kind=(
                    PrequentialEventKind.PREDICTION_FROZEN
                    if stored.status is PredictionStatus.FROZEN
                    else PrequentialEventKind.PREDICTION_REJECTED
                ),
                recorded_at=stored.predicted_at,
                stream_key=f"fixture:{stored.fixture_id}",
                fixture_id=stored.fixture_id,
                model_id=stored.model_id,
                model_version=stored.model_version,
                evidence_hashes=(stored.payload_hash,),
                details={
                    "status": stored.status.value,
                    "market": stored.market.value,
                    "cutoff": stored.cutoff_name.value,
                },
            )
        return stored

    def settle(
        self,
        result: VerifiedFixtureResult,
        *,
        settled_at: datetime,
    ) -> tuple[FixtureSettlementRecord, tuple[PredictionScore, ...], bool]:
        settlement, scores, inserted = self.settlements.settle(
            result,
            predictions=self.predictions.predictions,
            settled_at=settled_at,
        )
        if inserted:
            self.ledger.append(
                kind=PrequentialEventKind.FIXTURE_SETTLED,
                recorded_at=settled_at,
                stream_key=f"fixture:{result.fixture_id}",
                fixture_id=result.fixture_id,
                evidence_hashes=(settlement.settlement_hash,),
                details={
                    "status": settlement.effective_status.value,
                    "result_version": result.result_version,
                },
            )
            for score in scores:
                self.ledger.append(
                    kind=PrequentialEventKind.PREDICTION_SCORED,
                    recorded_at=score.scored_at,
                    stream_key=f"fixture:{score.fixture_id}",
                    fixture_id=score.fixture_id,
                    model_id=score.model_id,
                    model_version=score.model_version,
                    evidence_hashes=(score.score_hash,),
                    details={"market": score.market.value},
                )
            if settlement.effective_status is PredictionStatus.SETTLED:
                self.ledger.append(
                    kind=PrequentialEventKind.TRAINING_ELIGIBLE,
                    recorded_at=settled_at,
                    stream_key=f"fixture:{result.fixture_id}",
                    fixture_id=result.fixture_id,
                    evidence_hashes=(settlement.settlement_hash,),
                )
                for prediction in self.predictions.predictions:
                    if (
                        prediction.fixture_id == result.fixture_id
                        and prediction.model_id.startswith("reference-")
                    ):
                        model = self.models[
                            (prediction.model_id, prediction.model_version)
                        ]
                        self.ledger.append(
                            kind=PrequentialEventKind.REFERENCE_UNCHANGED,
                            recorded_at=settled_at,
                            stream_key=f"model:{model.model_id}",
                            fixture_id=result.fixture_id,
                            model_id=model.model_id,
                            model_version=model.version,
                            evidence_hashes=(model.registry_hash,),
                        )
        return settlement, scores, inserted

    def train(
        self,
        *,
        model_id: str,
        previous_version: str,
        training_cutoff: datetime,
        code_revision: str,
        last_training_at: datetime | None = None,
    ) -> TrainingDecision:
        previous = self.models.get((model_id, previous_version))
        if previous is None:
            raise ValueError("PREQUENTIAL_CHALLENGER_MODEL_MISSING")
        decision = train_challenger_if_eligible(
            repository=self.artifact_repository,
            previous_model=previous,
            settlements=self.settlements.settlements,
            snapshots=self.features.snapshots,
            training_cutoff=training_cutoff,
            code_revision=code_revision,
            last_training_at=last_training_at,
        )
        self.training_decisions.append(decision)
        if decision.next_model is None or decision.manifest is None:
            evidence_hash = canonical_sha256(
                {
                    "status": decision.status,
                    "eligible": decision.eligible_fixtures,
                    "leagues": decision.represented_leagues,
                    "reason": decision.reason,
                }
            )
            self.ledger.append(
                kind=PrequentialEventKind.TRAINING_DEFERRED,
                recorded_at=training_cutoff,
                stream_key=f"model:{model_id}",
                model_id=model_id,
                model_version=previous_version,
                evidence_hashes=(evidence_hash,),
                details={"status": decision.status},
            )
            return decision
        self.ledger.append(
            kind=PrequentialEventKind.CHALLENGER_TRAINING_STARTED,
            recorded_at=training_cutoff,
            stream_key=f"model:{model_id}",
            model_id=model_id,
            model_version=previous_version,
            evidence_hashes=(decision.manifest.manifest_hash,),
        )
        next_model = decision.next_model
        key = (next_model.model_id, next_model.version)
        if key in self.models:
            raise ValueError("PREQUENTIAL_MODEL_VERSION_DUPLICATED")
        self.models[key] = next_model
        self.ledger.append(
            kind=PrequentialEventKind.CHALLENGER_VERSION_CREATED,
            recorded_at=training_cutoff,
            stream_key=f"model:{model_id}",
            model_id=model_id,
            model_version=next_model.version,
            evidence_hashes=(
                decision.manifest.manifest_hash,
                next_model.registry_hash,
            ),
        )
        self.ledger.append(
            kind=PrequentialEventKind.PROMOTION_BLOCKED,
            recorded_at=training_cutoff,
            stream_key=f"model:{model_id}",
            model_id=model_id,
            model_version=next_model.version,
            evidence_hashes=(next_model.registry_hash,),
            details={"promotion_status": PROMOTION_LOCKED},
        )
        return decision


__all__ = [
    "HashChainedPrequentialLedger",
    "PredictionRegistry",
    "PrequentialLearningFactory",
    "devig_probabilities",
    "initial_model_versions",
]
