"""SQLAlchemy projections for the append-only prequential learning factory."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from robin.storage.models import Base


class PrequentialFeatureSnapshotModel(Base):
    __tablename__ = "prequential_feature_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_prequential_feature_snapshot_id"),
        UniqueConstraint(
            "fixture_record_id",
            "cutoff_name",
            "market",
            "feature_contract_version",
            "snapshot_hash",
            name="uq_prequential_feature_snapshot_version",
        ),
        CheckConstraint(
            "length(snapshot_hash) = 64 "
            "AND length(feature_contract_hash) = 64 "
            "AND created_at <= cutoff_at "
            "AND status = 'FROZEN' AND append_only = true",
            name="ck_prequential_feature_snapshot_integrity",
        ),
        Index(
            "ix_prequential_feature_fixture_cutoff",
            "fixture_id",
            "cutoff_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(120))
    fixture_record_id: Mapped[str] = mapped_column(
        ForeignKey("prospective_fixtures.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(40))
    cutoff_name: Mapped[str] = mapped_column(String(40))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    feature_contract_version: Mapped[str] = mapped_column(String(80))
    feature_contract_hash: Mapped[str] = mapped_column(String(64))
    values: Mapped[dict[str, object]] = mapped_column(JSON)
    missingness: Mapped[dict[str, bool]] = mapped_column(JSON)
    provenance: Mapped[dict[str, object]] = mapped_column(JSON)
    quality: Mapped[dict[str, object]] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_revision: Mapped[str] = mapped_column(String(80))
    r2_manifest_key: Mapped[str] = mapped_column(String(1500))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "prequential_feature_snapshots.id",
            ondelete="RESTRICT",
        )
    )
    status: Mapped[str] = mapped_column(String(40), default="FROZEN")
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialModelVersionModel(Base):
    __tablename__ = "prequential_model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "model_version",
            name="uq_prequential_model_version",
        ),
        CheckConstraint(
            "length(artifact_sha256) = 64 "
            "AND length(feature_contract_hash) = 64 "
            "AND length(registry_hash) = 64 "
            "AND (training_cutoff IS NULL OR training_cutoff <= created_at) "
            "AND append_only = true",
            name="ck_prequential_model_version_integrity",
        ),
        CheckConstraint(
            "role != 'REFERENCE' OR status IN ('ACTIVE', 'FROZEN_REFERENCE')",
            name="ck_prequential_reference_frozen",
        ),
        Index("ix_prequential_model_scope_role", "scope", "role", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(40))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_r2_key: Mapped[str | None] = mapped_column(String(1500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    training_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feature_contract_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(60))
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("prequential_model_versions.id", ondelete="RESTRICT")
    )
    registry_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialPredictionModel(Base):
    __tablename__ = "prequential_predictions"
    __table_args__ = (
        UniqueConstraint(
            "fixture_record_id",
            "cutoff_name",
            "market",
            "model_id",
            "model_version",
            name="uq_prequential_prediction_business",
        ),
        CheckConstraint(
            "length(payload_hash) = 64 "
            "AND cutoff_at < kickoff_at "
            "AND (status != 'FROZEN' OR predicted_at <= cutoff_at) "
            "AND append_only = true",
            name="ck_prequential_prediction_integrity",
        ),
        CheckConstraint(
            "(status = 'FROZEN' AND feature_snapshot_id IS NOT NULL "
            "AND rejection_reason IS NULL) "
            "OR (status != 'FROZEN' AND rejection_reason IS NOT NULL)",
            name="ck_prequential_prediction_status_shape",
        ),
        Index(
            "ix_prequential_prediction_fixture_cutoff",
            "fixture_id",
            "cutoff_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    prediction_id: Mapped[str] = mapped_column(String(120), unique=True)
    fixture_record_id: Mapped[str] = mapped_column(
        ForeignKey("prospective_fixtures.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(40))
    cutoff_name: Mapped[str] = mapped_column(String(40))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("prequential_model_versions.id", ondelete="RESTRICT")
    )
    model_id: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120))
    feature_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("prequential_feature_snapshots.id", ondelete="RESTRICT")
    )
    probabilities: Mapped[dict[str, float]] = mapped_column(JSON)
    market_probabilities: Mapped[dict[str, float] | None] = mapped_column(JSON)
    odds_snapshot_id: Mapped[str | None] = mapped_column(String(120))
    code_revision: Mapped[str] = mapped_column(String(80))
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(50))
    rejection_reason: Mapped[str | None] = mapped_column(String(250))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialFixtureSettlementModel(Base):
    __tablename__ = "prequential_fixture_settlements"
    __table_args__ = (
        UniqueConstraint(
            "fixture_record_id",
            "result_version",
            name="uq_prequential_fixture_result_version",
        ),
        CheckConstraint(
            "length(source_hash) = 64 AND length(result_hash) = 64 "
            "AND length(settlement_hash) = 64 "
            "AND settled_at >= verified_at "
            "AND result_version >= 1 AND append_only = true",
            name="ck_prequential_settlement_integrity",
        ),
        CheckConstraint(
            "(result_status IN ('FINISHED', 'CORRECTED') "
            "AND verified_at > kickoff_at "
            "AND home_goals IS NOT NULL AND away_goals IS NOT NULL "
            "AND home_goals >= 0 AND away_goals >= 0 "
            "AND effective_status = 'SETTLED') "
            "OR (result_status IN ('CANCELLED', 'ABANDONED') "
            "AND home_goals IS NULL AND away_goals IS NULL "
            "AND effective_status = 'VOID')",
            name="ck_prequential_settlement_result_shape",
        ),
        Index(
            "ix_prequential_settlement_fixture",
            "fixture_id",
            "result_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    settlement_id: Mapped[str] = mapped_column(String(120), unique=True)
    fixture_record_id: Mapped[str] = mapped_column(
        ForeignKey("prospective_fixtures.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_status: Mapped[str] = mapped_column(String(40))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    result_version: Mapped[int] = mapped_column(Integer)
    source_hash: Mapped[str] = mapped_column(String(64))
    result_hash: Mapped[str] = mapped_column(String(64), unique=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_status: Mapped[str] = mapped_column(String(40))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "prequential_fixture_settlements.id",
            ondelete="RESTRICT",
        )
    )
    settlement_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialPredictionScoreModel(Base):
    __tablename__ = "prequential_prediction_scores"
    __table_args__ = (
        UniqueConstraint(
            "prediction_id",
            "settlement_id",
            name="uq_prequential_prediction_score_version",
        ),
        CheckConstraint(
            "length(score_hash) = 64 "
            "AND log_loss >= 0 AND brier_score >= 0 "
            "AND append_only = true",
            name="ck_prequential_prediction_score_integrity",
        ),
        Index(
            "ix_prequential_score_segment",
            "competition",
            "market",
            "cutoff_name",
            "model_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    score_id: Mapped[str] = mapped_column(String(120), unique=True)
    prediction_id: Mapped[str] = mapped_column(
        ForeignKey("prequential_predictions.id", ondelete="RESTRICT")
    )
    settlement_id: Mapped[str] = mapped_column(
        ForeignKey("prequential_fixture_settlements.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(40))
    cutoff_name: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120))
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20))
    log_loss: Mapped[float] = mapped_column(Float)
    brier_score: Mapped[float] = mapped_column(Float)
    accurate: Mapped[bool] = mapped_column(Boolean)
    reference_log_loss_delta: Mapped[float | None] = mapped_column(Float)
    score_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialMetricSnapshotModel(Base):
    __tablename__ = "prequential_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "competition",
            "market",
            "cutoff_name",
            "model_id",
            "model_version",
            "month",
            "metric_hash",
            name="uq_prequential_metric_segment_version",
        ),
        CheckConstraint(
            "length(metric_hash) = 64 AND support >= 0 "
            "AND coverage >= 0 AND coverage <= 1 "
            "AND (missingness IS NULL OR "
            "(missingness >= 0 AND missingness <= 1)) "
            "AND append_only = true",
            name="ck_prequential_metric_snapshot_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    metric_snapshot_id: Mapped[str] = mapped_column(String(120), unique=True)
    competition: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(40))
    cutoff_name: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120))
    month: Mapped[str] = mapped_column(String(7))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    support: Mapped[int] = mapped_column(Integer)
    log_loss: Mapped[float | None] = mapped_column(Float)
    brier_score: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    accuracy_descriptive: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    missingness: Mapped[float | None] = mapped_column(Float)
    reference_log_loss_delta: Mapped[float | None] = mapped_column(Float)
    metric_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialTrainingRunModel(Base):
    __tablename__ = "prequential_training_runs"
    __table_args__ = (
        CheckConstraint(
            "eligible_fixtures >= 0 AND represented_leagues >= 0 "
            "AND finished_at >= started_at "
            "AND (dataset_manifest_hash IS NULL "
            "OR length(dataset_manifest_hash) = 64) "
            "AND (artifact_sha256 IS NULL OR length(artifact_sha256) = 64) "
            "AND promotion_status = 'PROMOTION_LOCKED' "
            "AND append_only = true",
            name="ck_prequential_training_run_integrity",
        ),
        Index("ix_prequential_training_model_time", "model_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    training_run_id: Mapped[str] = mapped_column(String(120), unique=True)
    model_id: Mapped[str] = mapped_column(String(120))
    previous_model_version: Mapped[str] = mapped_column(String(120))
    next_model_version: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    training_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eligible_fixtures: Mapped[int] = mapped_column(Integer)
    represented_leagues: Mapped[int] = mapped_column(Integer)
    dataset_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    dataset_manifest_r2_key: Mapped[str | None] = mapped_column(String(1500))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_r2_key: Mapped[str | None] = mapped_column(String(1500))
    fixture_ids: Mapped[list[str]] = mapped_column(JSON)
    settlement_ids: Mapped[list[str]] = mapped_column(JSON)
    competitions: Mapped[list[str]] = mapped_column(JSON)
    feature_snapshot_ids: Mapped[list[str]] = mapped_column(JSON)
    hyperparameters: Mapped[dict[str, object]] = mapped_column(JSON)
    training_metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    code_revision: Mapped[str] = mapped_column(String(80))
    promotion_status: Mapped[str] = mapped_column(
        String(40),
        default="PROMOTION_LOCKED",
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PrequentialLedgerEventModel(Base):
    __tablename__ = "prequential_ledger_events"
    __table_args__ = (
        UniqueConstraint("sequence_no", name="uq_prequential_ledger_sequence"),
        CheckConstraint(
            "length(previous_hash) = 64 AND length(record_hash) = 64 "
            "AND sequence_no >= 0 "
            "AND production_status = 'PRODUCTION_LOCKED' "
            "AND real_bets = false AND promoted = false "
            "AND append_only = true",
            name="ck_prequential_ledger_event_integrity",
        ),
        Index("ix_prequential_ledger_stream", "stream_key", "sequence_no"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stream_key: Mapped[str] = mapped_column(String(250))
    fixture_id: Mapped[str | None] = mapped_column(String(120))
    model_id: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(120))
    evidence_hashes: Mapped[list[str]] = mapped_column(JSON)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)
    production_status: Mapped[str] = mapped_column(
        String(40),
        default="PRODUCTION_LOCKED",
    )
    real_bets: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


PREQUENTIAL_TABLES = {
    "prequential_feature_snapshots",
    "prequential_model_versions",
    "prequential_predictions",
    "prequential_fixture_settlements",
    "prequential_prediction_scores",
    "prequential_metric_snapshots",
    "prequential_training_runs",
    "prequential_ledger_events",
}


__all__ = [
    "PREQUENTIAL_TABLES",
    "PrequentialFeatureSnapshotModel",
    "PrequentialFixtureSettlementModel",
    "PrequentialLedgerEventModel",
    "PrequentialMetricSnapshotModel",
    "PrequentialModelVersionModel",
    "PrequentialPredictionModel",
    "PrequentialPredictionScoreModel",
    "PrequentialTrainingRunModel",
]
