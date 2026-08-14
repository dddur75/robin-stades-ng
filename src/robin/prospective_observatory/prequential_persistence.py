"""Transactional PostgreSQL/SQLite index for prequential immutable records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.orm import Session

from robin.market_math import kernel_versions
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    feature_snapshot_record_id,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FeatureSnapshot,
    FixtureResultStatus,
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
    prediction_record_id,
    score_record_id,
    settlement_record_id,
)
from robin.storage.prequential_models import (
    PREQUENTIAL_TABLES,
    PrequentialFeatureSnapshotModel,
    PrequentialFixtureSettlementModel,
    PrequentialLedgerEventModel,
    PrequentialMetricSnapshotModel,
    PrequentialModelVersionModel,
    PrequentialPredictionModel,
    PrequentialPredictionScoreModel,
    PrequentialTrainingRunModel,
)
from robin.temporal.lineage import thaw_json


def _exact_values(instance: object) -> dict[str, object]:
    table = instance.__table__  # type: ignore[attr-defined]
    return {
        column.name: _comparison_value(getattr(instance, column.name))
        for column in table.columns
    }


def _comparison_value(value: object) -> object:
    if isinstance(value, datetime):
        return _utc_db(value).isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _comparison_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_comparison_value(item) for item in value]
    return value


def _add_exact(session: Session, instance: Any) -> bool:
    existing = session.get(type(instance), instance.id)
    if existing is not None:
        if _exact_values(existing) != _exact_values(instance):
            raise ValueError(
                f"PREQUENTIAL_SQL_IDEMPOTENCY_CONFLICT:"
                f"{instance.__tablename__}"
            )
        return False
    session.add(instance)
    session.flush()
    return True


def _model_row_id(model: ModelVersion) -> str:
    return f"model-{model.registry_hash}"


class PrequentialSQLRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        names = set(inspect(engine).get_table_names())
        missing = PREQUENTIAL_TABLES - names
        if missing:
            raise RuntimeError(
                "PREQUENTIAL_DATABASE_TABLES_MISSING:"
                + ",".join(sorted(missing))
            )

    def append_model(self, model: ModelVersion) -> bool:
        parent_id: str | None = None
        if model.parent_version is not None:
            with Session(self.engine) as lookup:
                parent = lookup.scalar(
                    select(PrequentialModelVersionModel).where(
                        PrequentialModelVersionModel.model_id == model.model_id,
                        PrequentialModelVersionModel.model_version
                        == model.parent_version,
                    )
                )
                if parent is None:
                    raise ValueError("PREQUENTIAL_PARENT_MODEL_VERSION_MISSING")
                parent_id = parent.id
        row = PrequentialModelVersionModel(
            id=_model_row_id(model),
            model_id=model.model_id,
            model_version=model.version,
            scope=model.scope.value,
            role=model.role.value,
            artifact_sha256=model.artifact_sha256,
            artifact_r2_key=model.artifact_r2_key,
            created_at=model.created_at,
            training_cutoff=model.training_cutoff,
            feature_contract_hash=model.feature_contract_hash,
            code_revision=model.code_revision,
            status=model.status.value,
            parent_version_id=parent_id,
            registry_hash=model.registry_hash,
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            return _add_exact(session, row)

    def append_snapshot(self, snapshot: FeatureSnapshot) -> bool:
        row = PrequentialFeatureSnapshotModel(
            id=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            fixture_record_id=snapshot.fixture_record_id,
            fixture_id=snapshot.fixture_id,
            competition=snapshot.competition,
            market=snapshot.market.value,
            cutoff_name=snapshot.cutoff_name.value,
            cutoff_at=snapshot.cutoff_at,
            created_at=snapshot.created_at,
            feature_contract_version=snapshot.feature_contract_version,
            feature_contract_hash=snapshot.feature_contract_hash,
            values=thaw_json(snapshot.values),
            missingness=thaw_json(snapshot.missingness),
            provenance=thaw_json(snapshot.provenance),
            quality=thaw_json(snapshot.quality),
            snapshot_hash=snapshot.snapshot_hash,
            code_revision=snapshot.code_revision,
            r2_manifest_key=snapshot.r2_manifest_key,
            supersedes_id=snapshot.supersedes_id,
            status=snapshot.status,
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            return _add_exact(session, row)

    def append_prediction(self, prediction: FrozenPredictionRecord) -> bool:
        model = None
        with Session(self.engine) as lookup:
            model = lookup.scalar(
                select(PrequentialModelVersionModel).where(
                    PrequentialModelVersionModel.model_id
                    == prediction.model_id,
                    PrequentialModelVersionModel.model_version
                    == prediction.model_version,
                )
            )
        if model is None:
            raise ValueError("PREQUENTIAL_PREDICTION_MODEL_VERSION_MISSING")
        row = PrequentialPredictionModel(
            id=prediction.prediction_id,
            prediction_id=prediction.prediction_id,
            fixture_record_id=prediction.fixture_record_id,
            fixture_id=prediction.fixture_id,
            competition=prediction.competition,
            market=prediction.market.value,
            cutoff_name=prediction.cutoff_name.value,
            cutoff_at=prediction.cutoff_at,
            kickoff_at=prediction.kickoff_at,
            predicted_at=prediction.predicted_at,
            model_version_id=model.id,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            feature_snapshot_id=prediction.feature_snapshot_id,
            probabilities=thaw_json(prediction.probabilities),
            market_probabilities=thaw_json(prediction.market_probabilities),
            odds_snapshot_id=prediction.odds_snapshot_id,
            code_revision=prediction.code_revision,
            payload_hash=prediction.payload_hash,
            status=prediction.status.value,
            rejection_reason=prediction.rejection_reason,
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            existing = session.get(PrequentialPredictionModel, row.id)
            if existing is None:
                session.add(row)
                session.flush()
                return True
            candidate = _exact_values(row)
            persisted = _exact_values(existing)
            candidate_hash = candidate.pop("payload_hash")
            persisted_hash = persisted.pop("payload_hash")
            if persisted != candidate or persisted_hash not in {
                candidate_hash,
                prediction.legacy_payload_hash,
            }:
                raise ValueError(
                    "PREQUENTIAL_SQL_IDEMPOTENCY_CONFLICT:"
                    "prequential_predictions"
                )
            return False

    def append_settlement(
        self,
        settlement: FixtureSettlementRecord,
    ) -> bool:
        result = settlement.result
        row = PrequentialFixtureSettlementModel(
            id=settlement.settlement_id,
            settlement_id=settlement.settlement_id,
            fixture_record_id=result.fixture_record_id,
            fixture_id=result.fixture_id,
            competition=result.competition,
            kickoff_at=result.kickoff_at,
            result_status=result.status.value,
            home_goals=result.home_goals,
            away_goals=result.away_goals,
            result_version=result.result_version,
            source_hash=result.source_hash,
            result_hash=result.result_hash,
            verified_at=result.verified_at,
            settled_at=settlement.settled_at,
            effective_status=settlement.effective_status.value,
            supersedes_id=settlement.supersedes_id,
            settlement_hash=settlement.settlement_hash,
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            return _add_exact(session, row)

    def append_scores(self, scores: Iterable[PredictionScore]) -> int:
        inserted = 0
        with Session(self.engine) as session, session.begin():
            for score in scores:
                row = PrequentialPredictionScoreModel(
                    id=score.score_id,
                    score_id=score.score_id,
                    prediction_id=score.prediction_id,
                    settlement_id=score.settlement_id,
                    fixture_id=score.fixture_id,
                    competition=score.competition,
                    market=score.market.value,
                    cutoff_name=score.cutoff_name.value,
                    model_id=score.model_id,
                    model_version=score.model_version,
                    scored_at=score.scored_at,
                    outcome=score.outcome,
                    log_loss=score.log_loss,
                    brier_score=score.brier_score,
                    accurate=score.accurate,
                    reference_log_loss_delta=score.reference_log_loss_delta,
                    score_hash=score.score_hash,
                    append_only=True,
                )
                if _add_exact(session, row):
                    inserted += 1
        return inserted

    def append_metric_snapshot(
        self,
        value: Mapping[str, object],
        *,
        measured_at: datetime,
    ) -> bool:
        metrics = value.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ValueError("PREQUENTIAL_METRICS_MAPPING_REQUIRED")
        payload = {
            "competition": value["competition"],
            "market": value["market"],
            "cutoff": value["cutoff"],
            "model_id": value["model_id"],
            "model_version": value["model_version"],
            "month": value["month"],
            "measured_at": measured_at.isoformat(),
            "metrics": dict(metrics),
        }
        metric_hash = canonical_sha256(payload)
        row = PrequentialMetricSnapshotModel(
            id=f"metric-{metric_hash}",
            metric_snapshot_id=f"metric-{metric_hash}",
            competition=str(value["competition"]),
            market=str(value["market"]),
            cutoff_name=str(value["cutoff"]),
            model_id=str(value["model_id"]),
            model_version=str(value["model_version"]),
            month=str(value["month"]),
            measured_at=measured_at,
            support=int(metrics["support"]),
            log_loss=_optional_float(metrics.get("log_loss")),
            brier_score=_optional_float(metrics.get("brier_score")),
            calibration_error=_optional_float(
                metrics.get("calibration_error")
            ),
            accuracy_descriptive=_optional_float(
                metrics.get("accuracy_descriptive")
            ),
            coverage=float(metrics["coverage"]),
            missingness=_optional_float(metrics.get("missingness")),
            reference_log_loss_delta=_optional_float(
                metrics.get("reference_log_loss_delta")
            ),
            metric_hash=metric_hash,
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            return _add_exact(session, row)

    def append_training_decision(
        self,
        *,
        training_run_id: str,
        model_id: str,
        previous_version: str,
        decision: TrainingDecision,
        started_at: datetime,
        finished_at: datetime,
        code_revision: str,
    ) -> bool:
        manifest = decision.manifest
        next_model = decision.next_model
        row = PrequentialTrainingRunModel(
            id=training_run_id,
            training_run_id=training_run_id,
            model_id=model_id,
            previous_model_version=previous_version,
            next_model_version=next_model.version if next_model else None,
            status=decision.status,
            started_at=started_at,
            finished_at=finished_at,
            training_cutoff=finished_at,
            eligible_fixtures=decision.eligible_fixtures,
            represented_leagues=decision.represented_leagues,
            dataset_manifest_hash=manifest.manifest_hash if manifest else None,
            dataset_manifest_r2_key=manifest.r2_key if manifest else None,
            artifact_sha256=next_model.artifact_sha256 if next_model else None,
            artifact_r2_key=next_model.artifact_r2_key if next_model else None,
            fixture_ids=list(manifest.fixture_ids) if manifest else [],
            settlement_ids=list(manifest.settlement_ids) if manifest else [],
            competitions=list(manifest.competitions) if manifest else [],
            feature_snapshot_ids=(
                list(manifest.feature_snapshot_ids) if manifest else []
            ),
            hyperparameters=(
                thaw_json(manifest.hyperparameters) if manifest else {}
            ),
            training_metrics=(
                thaw_json(manifest.training_metrics) if manifest else {}
            ),
            code_revision=code_revision,
            promotion_status="PROMOTION_LOCKED",
            append_only=True,
        )
        with Session(self.engine) as session, session.begin():
            return _add_exact(session, row)

    def append_events(
        self,
        events: Iterable[PrequentialLedgerEvent],
    ) -> int:
        inserted = 0
        with Session(self.engine) as session, session.begin():
            latest = session.scalar(
                select(PrequentialLedgerEventModel)
                .order_by(PrequentialLedgerEventModel.sequence_no.desc())
                .limit(1)
                .with_for_update()
            )
            expected_sequence = latest.sequence_no + 1 if latest else 0
            expected_previous = latest.record_hash if latest else "0" * 64
            for event in events:
                existing = session.get(
                    PrequentialLedgerEventModel,
                    event.event_id,
                )
                if existing is not None:
                    if existing.record_hash != event.event_hash:
                        raise ValueError("PREQUENTIAL_LEDGER_EVENT_CONFLICT")
                    continue
                if (
                    event.sequence_no != expected_sequence
                    or event.previous_hash != expected_previous
                ):
                    raise ValueError("PREQUENTIAL_LEDGER_HEAD_CONFLICT")
                row = PrequentialLedgerEventModel(
                    id=event.event_id,
                    event_id=event.event_id,
                    sequence_no=event.sequence_no,
                    kind=event.kind.value,
                    recorded_at=event.recorded_at,
                    stream_key=event.stream_key,
                    fixture_id=event.fixture_id,
                    model_id=event.model_id,
                    model_version=event.model_version,
                    evidence_hashes=list(event.evidence_hashes),
                    details=thaw_json(event.details),
                    previous_hash=event.previous_hash,
                    record_hash=event.event_hash,
                    production_status=event.production_status,
                    real_bets=event.real_bets,
                    promoted=event.promoted,
                    append_only=True,
                )
                session.add(row)
                session.flush()
                inserted += 1
                expected_sequence += 1
                expected_previous = event.event_hash
        return inserted

    def counts(self) -> dict[str, int]:
        model_types = {
            "feature_snapshots": PrequentialFeatureSnapshotModel,
            "models": PrequentialModelVersionModel,
            "predictions": PrequentialPredictionModel,
            "settlements": PrequentialFixtureSettlementModel,
            "scores": PrequentialPredictionScoreModel,
            "metric_snapshots": PrequentialMetricSnapshotModel,
            "training_runs": PrequentialTrainingRunModel,
            "ledger_events": PrequentialLedgerEventModel,
        }
        with Session(self.engine) as session:
            return {
                key: int(
                    session.scalar(
                        select(func.count()).select_from(model_type)
                    )
                    or 0
                )
                for key, model_type in model_types.items()
            }

    def load_models(self) -> tuple[ModelVersion, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialModelVersionModel).order_by(
                        PrequentialModelVersionModel.created_at,
                        PrequentialModelVersionModel.model_id,
                    )
                )
            )
        by_id = {row.id: row for row in rows}
        models: list[ModelVersion] = []
        for row in rows:
            if row.parent_version_id is not None and row.parent_version_id not in by_id:
                raise ValueError("PREQUENTIAL_PARENT_MODEL_VERSION_MISSING")
            model = ModelVersion(
                model_id=row.model_id,
                scope=ModelScope(row.scope),
                role=ModelRole(row.role),
                version=row.model_version,
                artifact_sha256=row.artifact_sha256,
                created_at=_utc_db(row.created_at),
                training_cutoff=(
                    _utc_db(row.training_cutoff)
                    if row.training_cutoff is not None
                    else None
                ),
                feature_contract_hash=row.feature_contract_hash,
                code_revision=row.code_revision,
                status=ModelStatus(row.status),
                artifact_r2_key=row.artifact_r2_key,
                parent_version=(
                    by_id[row.parent_version_id].model_version
                    if row.parent_version_id is not None
                    else None
                ),
            )
            if (
                model.registry_hash != row.registry_hash
                or _model_row_id(model) != row.id
            ):
                raise ValueError("PREQUENTIAL_MODEL_REGISTRY_HASH_MISMATCH")
            models.append(model)
        return tuple(models)

    def load_snapshots(self) -> tuple[FeatureSnapshot, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialFeatureSnapshotModel).order_by(
                        PrequentialFeatureSnapshotModel.created_at,
                        PrequentialFeatureSnapshotModel.snapshot_id,
                    )
                )
            )
        snapshots: list[FeatureSnapshot] = []
        for row in rows:
            snapshot = FeatureSnapshot(
                snapshot_id=row.snapshot_id,
                fixture_record_id=row.fixture_record_id,
                fixture_id=row.fixture_id,
                competition=row.competition,
                market=PredictionMarket(row.market),
                cutoff_name=CutoffName(row.cutoff_name),
                cutoff_at=_utc_db(row.cutoff_at),
                created_at=_utc_db(row.created_at),
                feature_contract_version=row.feature_contract_version,
                feature_contract_hash=row.feature_contract_hash,
                values=dict(row.values),
                missingness=dict(row.missingness),
                provenance={
                    str(key): dict(value)
                    for key, value in row.provenance.items()
                    if isinstance(value, Mapping)
                },
                quality=dict(row.quality),
                code_revision=row.code_revision,
                r2_manifest_key=row.r2_manifest_key,
                supersedes_id=row.supersedes_id,
                status=row.status,
            )
            if (
                snapshot.snapshot_hash != row.snapshot_hash
                or snapshot.snapshot_id != row.id
                or snapshot.snapshot_id
                != feature_snapshot_record_id(
                    fixture_record_id=snapshot.fixture_record_id,
                    fixture_id=snapshot.fixture_id,
                    market=snapshot.market,
                    cutoff_name=snapshot.cutoff_name,
                    cutoff_at=snapshot.cutoff_at,
                    feature_contract_version=snapshot.feature_contract_version,
                    feature_contract_hash=snapshot.feature_contract_hash,
                    values=snapshot.values,
                    missingness=snapshot.missingness,
                    provenance=snapshot.provenance,
                    quality=snapshot.quality,
                    supersedes_id=snapshot.supersedes_id,
                )
            ):
                raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_HASH_MISMATCH")
            snapshots.append(snapshot)
        return tuple(snapshots)

    def load_predictions(self) -> tuple[FrozenPredictionRecord, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialPredictionModel).order_by(
                        PrequentialPredictionModel.predicted_at,
                        PrequentialPredictionModel.prediction_id,
                    )
                )
            )
        predictions: list[FrozenPredictionRecord] = []
        for row in rows:
            prediction = FrozenPredictionRecord(
                prediction_id=row.prediction_id,
                fixture_record_id=row.fixture_record_id,
                fixture_id=row.fixture_id,
                competition=row.competition,
                market=PredictionMarket(row.market),
                cutoff_name=CutoffName(row.cutoff_name),
                cutoff_at=_utc_db(row.cutoff_at),
                kickoff_at=_utc_db(row.kickoff_at),
                predicted_at=_utc_db(row.predicted_at),
                model_id=row.model_id,
                model_version=row.model_version,
                feature_snapshot_id=row.feature_snapshot_id,
                probabilities={
                    str(key): float(value)
                    for key, value in row.probabilities.items()
                },
                market_probabilities=(
                    {
                        str(key): float(value)
                        for key, value in row.market_probabilities.items()
                    }
                    if row.market_probabilities is not None
                    else None
                ),
                odds_snapshot_id=row.odds_snapshot_id,
                code_revision=row.code_revision,
                status=PredictionStatus(row.status),
                rejection_reason=row.rejection_reason,
                persisted_payload_hash=row.payload_hash,
                **kernel_versions("PROPORTIONAL"),
            )
            if (
                prediction.prediction_id != row.id
                or prediction.prediction_id
                != prediction_record_id(
                    fixture_record_id=prediction.fixture_record_id,
                    cutoff_name=prediction.cutoff_name,
                    market=prediction.market,
                    model_id=prediction.model_id,
                    model_version=prediction.model_version,
                )
            ):
                raise ValueError("PREQUENTIAL_PREDICTION_ID_MISMATCH")
            predictions.append(prediction)
        return tuple(predictions)

    def load_settlements(
        self,
    ) -> tuple[FixtureSettlementRecord, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialFixtureSettlementModel).order_by(
                        PrequentialFixtureSettlementModel.fixture_id,
                        PrequentialFixtureSettlementModel.result_version,
                    )
                )
            )
        settlements: list[FixtureSettlementRecord] = []
        for row in rows:
            settlement = FixtureSettlementRecord(
                settlement_id=row.settlement_id,
                result=VerifiedFixtureResult(
                    fixture_record_id=row.fixture_record_id,
                    fixture_id=row.fixture_id,
                    competition=row.competition,
                    kickoff_at=_utc_db(row.kickoff_at),
                    status=FixtureResultStatus(row.result_status),
                    verified_at=_utc_db(row.verified_at),
                    home_goals=row.home_goals,
                    away_goals=row.away_goals,
                    result_version=row.result_version,
                    source_hash=row.source_hash,
                ),
                settled_at=_utc_db(row.settled_at),
                effective_status=PredictionStatus(row.effective_status),
                supersedes_id=row.supersedes_id,
            )
            if (
                settlement.result.result_hash != row.result_hash
                or settlement.settlement_hash != row.settlement_hash
                or settlement.settlement_id != row.id
                or settlement.settlement_id
                != settlement_record_id(
                    settlement.result,
                    supersedes_id=settlement.supersedes_id,
                )
            ):
                raise ValueError("PREQUENTIAL_SETTLEMENT_HASH_MISMATCH")
            settlements.append(settlement)
        return tuple(settlements)

    def load_scores(self) -> tuple[PredictionScore, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialPredictionScoreModel).order_by(
                        PrequentialPredictionScoreModel.scored_at,
                        PrequentialPredictionScoreModel.score_id,
                    )
                )
            )
        scores: list[PredictionScore] = []
        for row in rows:
            score = PredictionScore(
                score_id=row.score_id,
                prediction_id=row.prediction_id,
                settlement_id=row.settlement_id,
                fixture_id=row.fixture_id,
                competition=row.competition,
                market=PredictionMarket(row.market),
                cutoff_name=CutoffName(row.cutoff_name),
                model_id=row.model_id,
                model_version=row.model_version,
                scored_at=_utc_db(row.scored_at),
                outcome=row.outcome,
                log_loss=row.log_loss,
                brier_score=row.brier_score,
                accurate=row.accurate,
                reference_log_loss_delta=row.reference_log_loss_delta,
            )
            if (
                score.score_hash != row.score_hash
                or score.score_id != row.id
                or score.score_id
                != score_record_id(
                    prediction_id=score.prediction_id,
                    settlement_id=score.settlement_id,
                )
            ):
                raise ValueError("PREQUENTIAL_SCORE_HASH_MISMATCH")
            scores.append(score)
        return tuple(scores)

    def load_events(self) -> tuple[PrequentialLedgerEvent, ...]:
        with Session(self.engine) as session:
            rows = tuple(
                session.scalars(
                    select(PrequentialLedgerEventModel).order_by(
                        PrequentialLedgerEventModel.sequence_no
                    )
                )
            )
        events: list[PrequentialLedgerEvent] = []
        for row in rows:
            event = PrequentialLedgerEvent(
                event_id=row.event_id,
                sequence_no=row.sequence_no,
                kind=PrequentialEventKind(row.kind),
                recorded_at=_utc_db(row.recorded_at),
                stream_key=row.stream_key,
                fixture_id=row.fixture_id,
                model_id=row.model_id,
                model_version=row.model_version,
                evidence_hashes=tuple(str(value) for value in row.evidence_hashes),
                details=row.details,
                previous_hash=row.previous_hash,
                production_status=row.production_status,
                real_bets=row.real_bets,
                promoted=row.promoted,
            )
            if event.event_hash != row.record_hash or event.event_id != row.id:
                raise ValueError("PREQUENTIAL_LEDGER_EVENT_HASH_MISMATCH")
            events.append(event)
        return tuple(events)

    def replay_rows(self) -> dict[str, list[dict[str, object]]]:
        model_types = (
            PrequentialFeatureSnapshotModel,
            PrequentialModelVersionModel,
            PrequentialPredictionModel,
            PrequentialFixtureSettlementModel,
            PrequentialPredictionScoreModel,
            PrequentialMetricSnapshotModel,
            PrequentialTrainingRunModel,
            PrequentialLedgerEventModel,
        )
        output: dict[str, list[dict[str, object]]] = {}
        with Session(self.engine) as session:
            for model_type in model_types:
                statement = select(model_type)
                if model_type is PrequentialLedgerEventModel:
                    statement = statement.order_by(
                        PrequentialLedgerEventModel.sequence_no
                    )
                rows = session.scalars(statement)
                output[model_type.__tablename__] = [
                    _json_compatible(_exact_values(row)) for row in rows
                ]
        return output


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        raise ValueError("PREQUENTIAL_METRIC_NUMBER_INVALID")
    return float(value)


def _json_compatible(value: object) -> Any:
    if isinstance(value, datetime):
        candidate = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return candidate.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def _utc_db(value: datetime) -> datetime:
    candidate = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return candidate.astimezone(UTC)


__all__ = ["PrequentialSQLRepository"]
