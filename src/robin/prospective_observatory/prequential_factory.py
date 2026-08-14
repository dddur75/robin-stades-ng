"""Five-league prediction, settlement and learning factory."""

from __future__ import annotations

import json
import math
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
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    FeatureSnapshotRegistry,
    verify_feature_snapshot_artifact,
)
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
    complete_injuries_feature,
    complete_lineup_feature,
    durable_required_feature_gates,
    feature_fixture_kickoff,
    feature_team_ids,
    prediction_record_id,
)
from robin.prospective_observatory.prequential_settlement import (
    SettlementRegistry,
    verify_result_observation_artifact,
)
from robin.prospective_observatory.prequential_storage import (
    PrequentialArtifactRepository,
)
from robin.prospective_observatory.prequential_training import (
    challenger_probabilities_from_artifact,
    eligible_training_examples,
    train_challenger_if_eligible,
)
from robin.temporal.lineage import parse_utc


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


def _verified_snapshot_odds(
    *,
    snapshot: object,
    market: PredictionMarket,
    decimal_odds: Mapping[str, float],
    odds_snapshot_id: str | None,
) -> tuple[dict[str, float], str]:
    """Bind the odds used by a forecast to its verified feature snapshot."""
    if not hasattr(snapshot, "values") or not hasattr(snapshot, "provenance"):
        raise ValueError("PREQUENTIAL_ODDS_SNAPSHOT_LINEAGE_MISMATCH")
    values = snapshot.values
    provenance = snapshot.provenance
    market_values = values.get("market")
    market_provenance = provenance.get("market")
    if not isinstance(market_values, Mapping) or not isinstance(
        market_provenance, Mapping
    ):
        raise ValueError("PREQUENTIAL_ODDS_SNAPSHOT_LINEAGE_MISMATCH")
    stored_odds = market_values.get("decimal_odds")
    stored_snapshot_id = market_provenance.get("odds_snapshot_id")
    if (
        not isinstance(stored_odds, Mapping)
        or not isinstance(stored_snapshot_id, str)
        or not stored_snapshot_id
        or odds_snapshot_id != stored_snapshot_id
    ):
        raise ValueError("PREQUENTIAL_ODDS_SNAPSHOT_LINEAGE_MISMATCH")
    expected = (
        ("HOME", "DRAW", "AWAY")
        if market is PredictionMarket.ONE_X_TWO
        else ("OVER", "UNDER")
    )
    if set(stored_odds) != set(expected) or set(decimal_odds) != set(expected):
        raise ValueError("PREQUENTIAL_ODDS_VALUES_LINEAGE_MISMATCH")
    verified: dict[str, float] = {}
    for selection in expected:
        stored_value = stored_odds[selection]
        supplied_value = decimal_odds[selection]
        if (
            isinstance(stored_value, bool)
            or not isinstance(stored_value, (int, float))
            or isinstance(supplied_value, bool)
            or not isinstance(supplied_value, (int, float))
        ):
            raise ValueError("PREQUENTIAL_ODDS_VALUES_LINEAGE_MISMATCH")
        stored_float = float(stored_value)
        supplied_float = float(supplied_value)
        if (
            not math.isfinite(stored_float)
            or not math.isfinite(supplied_float)
            or stored_float != supplied_float
        ):
            raise ValueError("PREQUENTIAL_ODDS_VALUES_LINEAGE_MISMATCH")
        verified[selection] = stored_float
    return verified, stored_snapshot_id


def _required_gate_feature_available(snapshot: object, family: str) -> bool:
    if not hasattr(snapshot, "missingness") or not hasattr(snapshot, "values"):
        return False
    if snapshot.missingness.get(family, True):
        return False
    value = snapshot.values.get(family)
    if family == "team":
        return feature_team_ids(value) is not None
    if family == "lineup":
        expected_team_ids = feature_team_ids(snapshot.values.get("team"))
        return bool(
            expected_team_ids is not None
            and complete_lineup_feature(
                value,
                expected_team_ids=expected_team_ids,
            )
        )
    if family == "injuries":
        return complete_injuries_feature(value)
    if family == "market":
        return value is not None
    # The remaining families do not yet have a canonical, family-specific gate
    # projection.  Refuse to promote even a non-empty payload until that
    # semantic validator exists; generic truthiness is not temporal evidence.
    return False


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
        recorded_at = ensure_utc(recorded_at, field="recorded_at")
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
        references = tuple(
            model for model in model_rows if model.role is ModelRole.REFERENCE
        )
        reference_scopes = {model.scope for model in references}
        if (
            len(references) != len(ModelScope)
            or reference_scopes != set(ModelScope)
        ):
            raise ValueError("PREQUENTIAL_REFERENCE_SCOPE_INCOMPLETE")
        for model in references:
            expected = next(
                candidate
                for candidate in initial_model_versions(
                    created_at=model.created_at,
                    feature_contract_hash=model.feature_contract_hash,
                    code_revision=model.code_revision,
                )
                if candidate.role is ModelRole.REFERENCE
                and candidate.scope is model.scope
            )
            if model != expected:
                # The reference algorithm is an embedded immutable artifact.
                # Re-derive its exact identity instead of trusting a
                # caller-supplied 64-hex token or self-hashed registry row.
                raise ValueError("PREQUENTIAL_REFERENCE_MODEL_ROOT_INVALID")
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
        verify_feature_snapshot_artifact(self.artifact_repository, snapshot)
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
        kickoff = ensure_utc(kickoff_at, field="kickoff_at")
        # Fixture identity/team evidence is a non-optional causal input.  A
        # caller can add stricter gates but cannot remove this base contract.
        required_gate_names = {"fixture", *required_gates}
        if decimal_odds is not None:
            required_gate_names.add("market")
        if model.created_at > predicted:
            raise ValueError("MODEL_NOT_AVAILABLE_AT_CUTOFF")
        if model.training_cutoff is not None and model.training_cutoff > predicted:
            raise ValueError("MODEL_NOT_AVAILABLE_AT_CUTOFF")
        snapshot = (
            self.features.get(feature_snapshot_id)
            if feature_snapshot_id is not None
            else None
        )
        if feature_snapshot_id is not None and snapshot is None:
            raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_NOT_FOUND")
        if snapshot is not None:
            # Re-read the immutable snapshot and every source receipt from the
            # artifact store at the decision boundary.  A dataclass carrying
            # plausible hashes is not sufficient evidence for a forecast.
            verify_feature_snapshot_artifact(self.artifact_repository, snapshot)
            if snapshot.created_at > predicted:
                raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_AFTER_PREDICTION")
            if (
                snapshot.fixture_record_id != fixture_record_id
                or snapshot.fixture_id != fixture_id
                or snapshot.competition != competition
                or snapshot.market is not market
                or snapshot.cutoff_name is not cutoff_name
                or snapshot.cutoff_at != cutoff
            ):
                raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_LINEAGE_MISMATCH")
            if model.feature_contract_hash != snapshot.feature_contract_hash:
                raise ValueError("PREQUENTIAL_FEATURE_CONTRACT_MISMATCH")
        declared_optional_gates = (
            set(durable_required_feature_gates(snapshot.quality))
            if snapshot is not None
            else set()
        )
        required_gate_names.update(declared_optional_gates)
        prediction_id = prediction_record_id(
            fixture_record_id=fixture_record_id,
            cutoff_name=cutoff_name,
            market=market,
            model_id=model_id,
            model_version=model_version,
        )
        status = PredictionStatus.FROZEN
        rejection_reason: str | None = None
        probabilities: dict[str, float] = {}
        market_probabilities: dict[str, float] | None = None
        verified_odds: dict[str, float] | None = None
        verified_odds_snapshot_id: str | None = None
        if predicted > cutoff:
            status = PredictionStatus.REJECTED_LATE
            rejection_reason = "PREDICTION_CUTOFF_EXCEEDED"
        else:
            effective_gate_statuses = dict(gate_statuses)
            for gate in required_gate_names:
                feature_family = (
                    "team"
                    if gate == "fixture"
                    else gate
                    if gate in FEATURE_FAMILIES
                    else None
                )
                # A caller-supplied boolean is never sufficient evidence for a
                # required data gate.  Every recognised gate must project to a
                # repository-verified, non-missing feature family.  Market is
                # implicitly requested whenever odds are supplied, so its
                # caller flag defaults to true only after that evidence check.
                gate_is_durable = gate in {"fixture", "market"} or (
                    gate in declared_optional_gates
                )
                feature_available = bool(
                    gate_is_durable
                    and feature_family is not None
                    and snapshot is not None
                    and _required_gate_feature_available(snapshot, feature_family)
                )
                if gate == "fixture":
                    # A team receipt proves identities only when it also
                    # attests the exact scheduled kickoff used to derive this
                    # prediction cutoff. SQL fixture scalars alone are not a
                    # positive point-in-time fixture receipt.
                    team_projection = (
                        snapshot.values.get("team")
                        if snapshot is not None
                        else None
                    )
                    feature_available = bool(
                        feature_available
                        and isinstance(team_projection, Mapping)
                        and feature_fixture_kickoff(team_projection) == kickoff
                        and team_projection.get("competition") == competition
                    )
                effective_gate_statuses[gate] = bool(
                    feature_available
                    and effective_gate_statuses.get(gate, gate == "market")
                )
            if decimal_odds is None:
                status = PredictionStatus.NO_ODDS_REFERENCE
                rejection_reason = "NO_ADMISSIBLE_ODDS_BEFORE_CUTOFF"
            else:
                missing_gates = sorted(
                    gate
                    for gate in required_gate_names
                    if not effective_gate_statuses.get(gate, False)
                )
                if missing_gates:
                    status = PredictionStatus.REJECTED_MISSING_GATE
                    rejection_reason = "MISSING_GATES:" + ",".join(missing_gates)
                else:
                    if snapshot is None:
                        raise ValueError(
                            "PREQUENTIAL_ODDS_SNAPSHOT_LINEAGE_MISMATCH"
                        )
                    verified_odds, verified_odds_snapshot_id = (
                        _verified_snapshot_odds(
                            snapshot=snapshot,
                            market=market,
                            decimal_odds=decimal_odds,
                            odds_snapshot_id=odds_snapshot_id,
                        )
                    )
                    market_probabilities, _margin = devig_probabilities(
                        market,
                        verified_odds,
                        devig_method=self.devig_method,
                    )
                    if model.role is ModelRole.REFERENCE:
                        probabilities = dict(market_probabilities)
                    elif model.status is ModelStatus.INSUFFICIENT_TRAINING_SUPPORT:
                        status = PredictionStatus.REJECTED_MISSING_GATE
                        rejection_reason = "INSUFFICIENT_TRAINING_SUPPORT"
                    else:
                        if model.artifact_r2_key is None:
                            raise ValueError(
                                "PREQUENTIAL_CHALLENGER_ARTIFACT_REQUIRED"
                            )
                        artifact = json.loads(
                            self.artifact_repository.read_verified(
                                model.artifact_r2_key,
                                model.artifact_sha256,
                            )
                        )
                        if not isinstance(artifact, Mapping) or artifact.get(
                            "schema_version"
                        ) != "prequential-challenger-artifact-v1":
                            raise ValueError(
                                "PREQUENTIAL_CHALLENGER_ARTIFACT_INVALID"
                            )
                        artifact_cutoff = parse_utc(
                            str(artifact.get("training_cutoff", "")),
                            field="challenger_artifact_training_cutoff",
                        )
                        training_manifest_hash = str(
                            artifact.get("training_manifest_hash", "")
                        )
                        if (
                            model.training_cutoff is None
                            or artifact_cutoff != model.training_cutoff
                            or artifact_cutoff > predicted
                            or len(training_manifest_hash) != 64
                            or any(
                                character not in "0123456789abcdef"
                                for character in training_manifest_hash
                            )
                            or artifact.get("promotion_status")
                            != PROMOTION_LOCKED
                        ):
                            raise ValueError(
                                "PREQUENTIAL_CHALLENGER_ARTIFACT_TIME_MISMATCH"
                            )
                        expected_challenger = (
                            challenger_probabilities_from_artifact(
                                artifact,
                                market,
                            )
                        )
                        if challenger_probabilities is not None and (
                            set(challenger_probabilities)
                            != set(expected_challenger)
                            or any(
                                not math.isclose(
                                    float(challenger_probabilities[label]),
                                    probability,
                                    rel_tol=0.0,
                                    abs_tol=1e-15,
                                )
                                for label, probability in expected_challenger.items()
                            )
                        ):
                            raise ValueError(
                                "PREQUENTIAL_CHALLENGER_PROBABILITY_MISMATCH"
                            )
                        probabilities = expected_challenger
        prediction = FrozenPredictionRecord(
            prediction_id=prediction_id,
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition=competition,
            market=market,
            cutoff_name=cutoff_name,
            cutoff_at=cutoff,
            kickoff_at=kickoff,
            predicted_at=predicted,
            model_id=model_id,
            model_version=model_version,
            feature_snapshot_id=feature_snapshot_id,
            probabilities=probabilities,
            market_probabilities=market_probabilities,
            odds_snapshot_id=verified_odds_snapshot_id,
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
        result_provider_identity = verify_result_observation_artifact(
            self.artifact_repository,
            result,
        )
        expected_provider_identities: set[tuple[str, str]] = set()
        for prediction in self.predictions.predictions:
            if (
                prediction.status is not PredictionStatus.FROZEN
                or prediction.fixture_record_id != result.fixture_record_id
                or prediction.fixture_id != result.fixture_id
                or prediction.feature_snapshot_id is None
            ):
                continue
            snapshot = self.features.get(prediction.feature_snapshot_id)
            team_projection = (
                snapshot.values.get("team") if snapshot is not None else None
            )
            if not isinstance(team_projection, Mapping):
                continue
            provider = str(team_projection.get("provider", "")).strip()
            provider_fixture_id = str(
                team_projection.get("provider_fixture_id", "")
            ).strip()
            if provider and provider_fixture_id:
                expected_provider_identities.add(
                    (provider, provider_fixture_id)
                )
        if expected_provider_identities != {result_provider_identity}:
            raise ValueError("PREQUENTIAL_RESULT_FIXTURE_IDENTITY_MISMATCH")
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
                        and prediction.fixture_record_id
                        == result.fixture_record_id
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
        cutoff = ensure_utc(training_cutoff, field="training_cutoff")
        expected_competition = FIVE_LEAGUE_NAMES.get(previous.scope)
        candidate_snapshots = tuple(
            snapshot
            for snapshot in self.features.snapshots
            if snapshot.created_at <= snapshot.cutoff_at < cutoff
            and (
                expected_competition is None
                or snapshot.competition == expected_competition
            )
        )
        candidate_settlements = tuple(
            settlement
            for settlement in self.settlements.settlements
            if settlement.settled_at < cutoff
            and (
                expected_competition is None
                or settlement.result.competition == expected_competition
            )
        )
        selected_examples = eligible_training_examples(
            settlements=candidate_settlements,
            snapshots=candidate_snapshots,
            training_cutoff=cutoff,
            required_feature_contract_hash=previous.feature_contract_hash,
        )
        selected_snapshot_ids = {
            example.snapshot_id for example in selected_examples
        }
        selected_settlement_ids = {
            example.settlement_id for example in selected_examples
        }
        for snapshot in candidate_snapshots:
            if snapshot.snapshot_id not in selected_snapshot_ids:
                continue
            verify_feature_snapshot_artifact(self.artifact_repository, snapshot)
        for settlement in candidate_settlements:
            if settlement.settlement_id not in selected_settlement_ids:
                continue
            verify_result_observation_artifact(
                self.artifact_repository,
                settlement.result,
            )
        decision = train_challenger_if_eligible(
            repository=self.artifact_repository,
            previous_model=previous,
            settlements=candidate_settlements,
            snapshots=candidate_snapshots,
            training_cutoff=cutoff,
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
                    "model_id": model_id,
                    "previous_version": previous_version,
                    "training_cutoff": cutoff.isoformat(),
                    "code_revision": code_revision,
                }
            )
            self.ledger.append(
                kind=PrequentialEventKind.TRAINING_DEFERRED,
                recorded_at=cutoff,
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
