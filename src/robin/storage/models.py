"""Schéma transactionnel minimal du jalon 1."""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InternalEntity(Base):
    __tablename__ = "internal_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    display_name: Mapped[str | None] = mapped_column(String(250))
    attributes: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProviderMapping(Base):
    __tablename__ = "provider_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "entity_type",
            "provider_entity_id",
            "valid_from",
            name="uq_provider_mapping_version",
        ),
        Index(
            "ix_provider_mapping_lookup",
            "provider_name",
            "entity_type",
            "provider_entity_id",
            "valid_to",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    internal_entity_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40))
    provider_name: Mapped[str] = mapped_column(String(120))
    provider_entity_id: Mapped[str] = mapped_column(String(250))
    observed_name: Mapped[str | None] = mapped_column(String(250))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mapping_status: Mapped[str] = mapped_column(String(30))
    mapping_confidence: Mapped[float] = mapped_column(Float)
    mapping_method: Mapped[str] = mapped_column(String(80))
    review_status: Mapped[str] = mapped_column(String(30))


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    pipeline_name: Mapped[str] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    source_version: Mapped[str] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)


class RawObservationModel(Base):
    __tablename__ = "raw_observations"
    __table_args__ = (
        Index("ix_raw_provider_received", "provider", "received_at"),
        Index("ix_raw_payload_hash", "payload_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(500))
    request_parameters: Mapped[dict[str, object]] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(80))
    ingestion_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), index=True
    )
    raw_payload_location: Mapped[str] = mapped_column(String(1000))


class Fixture(Base):
    __tablename__ = "fixtures"
    __table_args__ = (
        UniqueConstraint(
            "fixture_entity_id",
            "version",
            name="uq_fixture_version",
        ),
        Index("ix_fixture_kickoff", "kickoff_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_entity_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT"), index=True
    )
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    season_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    home_team_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    away_team_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    referee_id: Mapped[str | None] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    fixture_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_local: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer)
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("raw_observations.id", ondelete="RESTRICT")
    )


class FeatureValue(Base):
    __tablename__ = "feature_values"
    __table_args__ = (
        UniqueConstraint(
            "feature_name",
            "entity_id",
            "fixture_id",
            "as_of_time",
            "feature_version",
            "source_version",
            name="uq_feature_value_version",
        ),
        Index("ix_feature_as_of", "fixture_id", "as_of_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature_name: Mapped[str] = mapped_column(String(160))
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id", ondelete="RESTRICT"))
    value: Mapped[dict[str, object] | None] = mapped_column(JSON)
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_version: Mapped[str] = mapped_column(String(120))
    feature_version: Mapped[str] = mapped_column(String(120))
    quality_status: Mapped[str] = mapped_column(String(30))


class QualityCheck(Base):
    __tablename__ = "quality_checks"
    __table_args__ = (Index("ix_quality_run_severity", "run_id", "severity"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    check_name: Mapped[str] = mapped_column(String(160))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(30))
    scope: Mapped[str] = mapped_column(String(250))
    observed_value: Mapped[str] = mapped_column(Text)
    expected_rule: Mapped[str] = mapped_column(Text)
    affected_rows: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_location: Mapped[str | None] = mapped_column(String(1000))


class BookmakerQuote(Base):
    __tablename__ = "bookmaker_quotes"
    __table_args__ = (
        UniqueConstraint(
            "fixture_id",
            "bookmaker_id",
            "market_type",
            "market_scope",
            "selection",
            "line_value",
            "period",
            "observed_at",
            name="uq_bookmaker_quote",
        ),
        Index("ix_quote_fixture_observed", "fixture_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id", ondelete="RESTRICT"))
    bookmaker_id: Mapped[str] = mapped_column(
        ForeignKey("internal_entities.id", ondelete="RESTRICT")
    )
    market_type: Mapped[str] = mapped_column(String(50))
    market_scope: Mapped[str] = mapped_column(String(30))
    selection: Mapped[str] = mapped_column(String(50))
    line_value: Mapped[float | None] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String(30))
    settlement_rule_version: Mapped[str] = mapped_column(String(80))
    odds_decimal: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quote_phase: Mapped[str] = mapped_column(String(30))
    source_observation_id: Mapped[str] = mapped_column(
        ForeignKey("raw_observations.id", ondelete="RESTRICT")
    )


class MarketOpportunity(Base):
    __tablename__ = "market_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "fixture_id",
            "market_type",
            "market_scope",
            "selection",
            "line_value",
            "period",
            "strategy_version",
            name="uq_market_opportunity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id", ondelete="RESTRICT"))
    market_type: Mapped[str] = mapped_column(String(50))
    market_scope: Mapped[str] = mapped_column(String(30))
    selection: Mapped[str] = mapped_column(String(50))
    line_value: Mapped[float | None] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String(30))
    strategy_version: Mapped[str] = mapped_column(String(120))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SelectedBet(Base):
    __tablename__ = "selected_bets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("market_opportunities.id", ondelete="RESTRICT"), unique=True
    )
    quote_id: Mapped[str] = mapped_column(
        ForeignKey("bookmaker_quotes.id", ondelete="RESTRICT")
    )
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stake: Mapped[float] = mapped_column(Float)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class SettledBet(Base):
    __tablename__ = "settled_bets"
    __table_args__ = (
        UniqueConstraint("selected_bet_id", "result_version", name="uq_settlement_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    selected_bet_id: Mapped[str] = mapped_column(
        ForeignKey("selected_bets.id", ondelete="RESTRICT")
    )
    result_version: Mapped[int] = mapped_column(Integer)
    settlement_rule_version: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(30))
    profit: Mapped[float] = mapped_column(Float)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_settlement_id: Mapped[str | None] = mapped_column(
        ForeignKey("settled_bets.id", ondelete="RESTRICT")
    )


class ProviderCallLog(Base):
    __tablename__ = "provider_call_logs"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "endpoint",
            "requested_at",
            "ingestion_run_id",
            name="uq_provider_call",
        ),
        Index("ix_provider_call_observed", "provider", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(500))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    quota_used: Mapped[int | None] = mapped_column(Integer)
    quota_remaining: Mapped[int | None] = mapped_column(Integer)
    raw_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_observations.id", ondelete="RESTRICT")
    )
    ingestion_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE")
    )
    error_code: Mapped[str | None] = mapped_column(String(120))


class ShadowPredictionModel(Base):
    __tablename__ = "shadow_predictions"
    __table_args__ = (
        UniqueConstraint(
            "fixture_id",
            "model_name",
            "model_version",
            "as_of_time",
            name="uq_shadow_prediction",
        ),
        Index("ix_shadow_prediction_time", "generated_at", "as_of_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_id: Mapped[str] = mapped_column(String(36), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    as_of_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    dataset_version: Mapped[str] = mapped_column(String(120))
    feature_version: Mapped[str] = mapped_column(String(120))
    probability_home: Mapped[float] = mapped_column(Float)
    probability_draw: Mapped[float] = mapped_column(Float)
    probability_away: Mapped[float] = mapped_column(Float)
    expected_home_goals: Mapped[float] = mapped_column(Float)
    expected_away_goals: Mapped[float] = mapped_column(Float)
    data_quality_status: Mapped[str] = mapped_column(String(30))
    uncertainty_status: Mapped[str] = mapped_column(String(30))
    market_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class ShadowDecisionModel(Base):
    __tablename__ = "shadow_decisions"
    __table_args__ = (
        UniqueConstraint(
            "fixture_id",
            "market_key",
            "selection",
            "strategy_version",
            name="uq_shadow_decision",
        ),
        Index("ix_shadow_decision_accepted", "decided_at", "accepted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fixture_id: Mapped[str] = mapped_column(String(36), index=True)
    market_key: Mapped[str] = mapped_column(String(160))
    selection: Mapped[str] = mapped_column(String(50))
    odds_decimal: Mapped[float | None] = mapped_column(Float)
    model_probability: Mapped[float] = mapped_column(Float)
    implied_probability: Mapped[float | None] = mapped_column(Float)
    edge: Mapped[float | None] = mapped_column(Float)
    strategy_version: Mapped[str] = mapped_column(String(120))
    quality_status: Mapped[str] = mapped_column(String(30))
    uncertainty_status: Mapped[str] = mapped_column(String(30))
    suggested_stake: Mapped[float] = mapped_column(Float)
    accepted: Mapped[bool] = mapped_column(Boolean)
    primary_reason: Mapped[str | None] = mapped_column(String(80))
    secondary_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class LegacyMigrationRun(Base):
    __tablename__ = "legacy_migration_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_examined: Mapped[int] = mapped_column(Integer)
    mappings_total: Mapped[int] = mapped_column(Integer)
    certain_coverage: Mapped[float] = mapped_column(Float)
    ambiguous: Mapped[int] = mapped_column(Integer)
    unresolved: Mapped[int] = mapped_column(Integer)
    collisions: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    report_location: Mapped[str] = mapped_column(String(1000))


class OperationalMetric(Base):
    __tablename__ = "operational_metrics"
    __table_args__ = (
        Index("ix_operational_metric_time", "metric_name", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(160))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    dimensions: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL")
    )


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (
        Index("ix_operational_alert_time", "severity", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    alert_code: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    action_required: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL")
    )


class PatternDefinitionModel(Base):
    """Définition immuable et versionnée d'une règle de recherche."""

    __tablename__ = "pattern_definitions"
    __table_args__ = (
        UniqueConstraint(
            "pattern_id",
            "pattern_version",
            name="uq_pattern_definition_version",
        ),
        UniqueConstraint(
            "rule_hash",
            "pattern_version",
            name="uq_pattern_definition_rule_version",
        ),
        Index("ix_pattern_definition_status", "status", "evidence_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pattern_id: Mapped[str] = mapped_column(String(80))
    pattern_version: Mapped[str] = mapped_column(String(40))
    rule_hash: Mapped[str] = mapped_column(String(64))
    sport: Mapped[str] = mapped_column(String(30))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(50))
    evidence_scope: Mapped[str] = mapped_column(String(50))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    code_revision: Mapped[str] = mapped_column(String(80))
    dataset_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_definitions.id", ondelete="RESTRICT")
    )


class PatternRunModel(Base):
    """Exécution reproductible de découverte, validation ou replay."""

    __tablename__ = "pattern_runs"
    __table_args__ = (
        CheckConstraint("simulation = true", name="ck_pattern_run_simulation"),
        CheckConstraint(
            "rules_generated >= 0 AND rules_executed >= 0 "
            "AND rules_rejected >= 0",
            name="ck_pattern_run_counts",
        ),
        Index("ix_pattern_run_status", "run_type", "status", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    run_type: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    code_revision: Mapped[str] = mapped_column(String(80))
    configuration: Mapped[dict[str, object]] = mapped_column(JSON)
    dataset_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    environment: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))
    rules_generated: Mapped[int] = mapped_column(Integer, default=0)
    rules_executed: Mapped[int] = mapped_column(Integer, default=0)
    rules_rejected: Mapped[int] = mapped_column(Integer, default=0)
    cost_units: Mapped[float] = mapped_column(Float, default=0.0)
    checkpoint: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class PatternEvaluationModel(Base):
    """Mesures d'une règle pour une portée et un fold déterminés."""

    __tablename__ = "pattern_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "pattern_definition_id",
            "pattern_run_id",
            "evaluation_scope",
            "fold_key",
            name="uq_pattern_evaluation_fold",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_pattern_evaluation_simulation",
        ),
        CheckConstraint("support >= 0", name="ck_pattern_evaluation_support"),
        CheckConstraint(
            "(p_value IS NULL OR (p_value >= 0 AND p_value <= 1)) "
            "AND (q_value IS NULL OR (q_value >= 0 AND q_value <= 1))",
            name="ck_pattern_evaluation_probabilities",
        ),
        Index(
            "ix_pattern_evaluation_status",
            "evaluation_scope",
            "status",
            "evaluated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pattern_definition_id: Mapped[str] = mapped_column(
        ForeignKey("pattern_definitions.id", ondelete="RESTRICT")
    )
    pattern_run_id: Mapped[str] = mapped_column(
        ForeignKey("pattern_runs.id", ondelete="RESTRICT")
    )
    evaluation_scope: Mapped[str] = mapped_column(String(50))
    fold_key: Mapped[str] = mapped_column(String(120))
    support: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    p_value: Mapped[float | None] = mapped_column(Float)
    q_value: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class PatternDecisionRecordModel(Base):
    """Décision shadow gelée avant match; jamais un ordre de pari réel."""

    __tablename__ = "pattern_decisions"
    __table_args__ = (
        CheckConstraint("simulation = true", name="ck_pattern_decision_simulation"),
        CheckConstraint("append_only = true", name="ck_pattern_decision_append_only"),
        CheckConstraint(
            "published_at <= cutoff_at AND cutoff_at < kickoff_at",
            name="ck_pattern_decision_temporal",
        ),
        CheckConstraint(
            "decision IN ('BET', 'NO_BET', 'NO_BET_DATA_UNAVAILABLE')",
            name="ck_pattern_decision_value",
        ),
        CheckConstraint(
            "(decision = 'BET' AND stake_units = 1) "
            "OR (decision <> 'BET' AND stake_units = 0)",
            name="ck_pattern_decision_stake",
        ),
        UniqueConstraint(
            "fixture_id",
            "market",
            "selection",
            "cutoff_at",
            name="uq_pattern_decision_business",
        ),
        Index("ix_pattern_decision_fixture", "fixture_id", "kickoff_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    pattern_definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_definitions.id", ondelete="RESTRICT")
    )
    pattern_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_runs.id", ondelete="RESTRICT")
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fixture_id: Mapped[str] = mapped_column(String(100))
    competition: Mapped[str] = mapped_column(String(120))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(80))
    odds: Mapped[float | None] = mapped_column(Float)
    odds_source: Mapped[str] = mapped_column(String(160))
    decision: Mapped[str] = mapped_column(String(40))
    stake_units: Mapped[float] = mapped_column(Float, default=0.0)
    shadow_bankroll_before: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50))
    code_revision: Mapped[str] = mapped_column(String(80))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class PatternSettlementModel(Base):
    """Événement de règlement séparé de la décision immuable."""

    __tablename__ = "pattern_settlements"
    __table_args__ = (
        CheckConstraint(
            "simulation = true",
            name="ck_pattern_settlement_simulation",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_pattern_settlement_append_only",
        ),
        CheckConstraint(
            "result IN ('WIN', 'LOSS', 'VOID')",
            name="ck_pattern_settlement_result",
        ),
        UniqueConstraint(
            "pattern_decision_id",
            name="uq_pattern_settlement_decision",
        ),
        Index("ix_pattern_settlement_time", "settled_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    settlement_id: Mapped[str] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    pattern_decision_id: Mapped[str] = mapped_column(
        ForeignKey("pattern_decisions.id", ondelete="RESTRICT")
    )
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(20))
    profit_units: Mapped[float] = mapped_column(Float)
    shadow_bankroll_after: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class BankrollEventModel(Base):
    """Mouvement append-only du bankroll shadow."""

    __tablename__ = "bankroll_events"
    __table_args__ = (
        CheckConstraint("simulation = true", name="ck_bankroll_event_simulation"),
        CheckConstraint("append_only = true", name="ck_bankroll_event_append_only"),
        CheckConstraint(
            "balance_before >= 0 AND balance_after >= 0",
            name="ck_bankroll_event_balances",
        ),
        UniqueConstraint(
            "pattern_settlement_id",
            name="uq_bankroll_event_settlement",
        ),
        Index("ix_bankroll_event_time", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    event_type: Mapped[str] = mapped_column(String(40))
    pattern_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_decisions.id", ondelete="RESTRICT")
    )
    pattern_settlement_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_settlements.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_units: Mapped[float] = mapped_column(Float)
    balance_before: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class EvidenceLedgerModel(Base):
    """Projection transactionnelle de la chaîne publique append-only."""

    __tablename__ = "evidence_ledger"
    __table_args__ = (
        CheckConstraint("append_only = true", name="ck_evidence_ledger_append_only"),
        CheckConstraint("simulation = true", name="ck_evidence_ledger_simulation"),
        CheckConstraint("sequence_no >= 0", name="ck_evidence_ledger_sequence"),
        Index("ix_evidence_ledger_recorded", "recorded_at", "record_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(120), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    sequence_no: Mapped[int] = mapped_column(Integer, unique=True)
    record_type: Mapped[str] = mapped_column(String(30))
    pattern_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_decisions.id", ondelete="RESTRICT")
    )
    pattern_settlement_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_settlements.id", ondelete="RESTRICT")
    )
    previous_record_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class ExperimentRegistryModel(Base):
    """Préenregistrement versionné des hypothèses et seuils scientifiques."""

    __tablename__ = "experiment_registry"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "experiment_version",
            name="uq_experiment_registry_version",
        ),
        UniqueConstraint(
            "preregistration_hash",
            "experiment_version",
            name="uq_experiment_preregistration_hash",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_experiment_registry_simulation",
        ),
        CheckConstraint(
            "frozen_at >= registered_at",
            name="ck_experiment_registry_frozen",
        ),
        Index("ix_experiment_registry_status", "status", "registered_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(120))
    experiment_version: Mapped[str] = mapped_column(String(40))
    preregistration_hash: Mapped[str] = mapped_column(String(64))
    hypothesis: Mapped[str] = mapped_column(Text)
    protocol: Mapped[dict[str, object]] = mapped_column(JSON)
    dataset_scope: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    pattern_definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("pattern_definitions.id", ondelete="RESTRICT")
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiment_registry.id", ondelete="RESTRICT")
    )
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class DeepFeatureDefinitionModel(Base):
    """Contrat immuable et versionné d'une feature de football profond."""

    __tablename__ = "deep_feature_definitions"
    __table_args__ = (
        UniqueConstraint(
            "feature_id",
            "feature_version",
            name="uq_deep_feature_definition_version",
        ),
        UniqueConstraint(
            "definition_hash",
            "feature_version",
            name="uq_deep_feature_definition_hash_version",
        ),
        CheckConstraint(
            "length(definition_hash) = 64 AND length(dataset_hash) = 64",
            name="ck_deep_feature_definition_hashes",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_deep_feature_definition_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_deep_feature_definition_simulation",
        ),
        Index(
            "ix_deep_feature_definition_family",
            "feature_family",
            "entity_level",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature_id: Mapped[str] = mapped_column(String(120))
    feature_version: Mapped[str] = mapped_column(String(40))
    feature_family: Mapped[str] = mapped_column(String(80))
    entity_level: Mapped[str] = mapped_column(String(40))
    cutoff_policy: Mapped[str] = mapped_column(String(80))
    contract: Mapped[dict[str, object]] = mapped_column(JSON)
    definition_hash: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("deep_feature_definitions.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class DeepFeatureObservationModel(Base):
    """Valeur point-in-time immuable ou absence explicitement qualifiée."""

    __tablename__ = "deep_feature_observations"
    __table_args__ = (
        UniqueConstraint(
            "feature_definition_id",
            "fixture_id",
            "entity_id",
            "as_of_at",
            "dataset_version",
            name="uq_deep_feature_observation_business",
        ),
        CheckConstraint(
            "length(source_hash) = 64 "
            "AND length(observation_hash) = 64 "
            "AND length(dataset_hash) = 64",
            name="ck_deep_feature_observation_hashes",
        ),
        CheckConstraint(
            "value IS NOT NULL OR missing_reason IS NOT NULL",
            name="ck_deep_feature_observation_missing",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_deep_feature_observation_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_deep_feature_observation_simulation",
        ),
        Index(
            "ix_deep_feature_observation_fixture",
            "fixture_id",
            "as_of_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    feature_definition_id: Mapped[str] = mapped_column(
        ForeignKey("deep_feature_definitions.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    entity_id: Mapped[str] = mapped_column(String(120))
    side: Mapped[str] = mapped_column(String(20))
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[dict[str, object] | None] = mapped_column(JSON)
    missing_reason: Mapped[str | None] = mapped_column(String(120))
    source_hash: Mapped[str] = mapped_column(String(64))
    observation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class CoverageGateModel(Base):
    """Preuve versionnée de disponibilité, qualité et temporalité."""

    __tablename__ = "coverage_gates"
    __table_args__ = (
        UniqueConstraint(
            "gate_key",
            "gate_version",
            "competition",
            "season",
            "cutoff_class",
            name="uq_coverage_gate_scope",
        ),
        CheckConstraint(
            "status IN ('READY', 'PARTIAL', 'BLOCKED_BY_COVERAGE', "
            "'BLOCKED_BY_TEMPORALITY', 'BLOCKED_BY_IDENTITY', "
            "'MARKET_UNAVAILABLE')",
            name="ck_coverage_gate_status",
        ),
        CheckConstraint(
            "coverage >= 0 AND coverage <= 1 "
            "AND quality_score >= 0 AND quality_score <= 1",
            name="ck_coverage_gate_scores",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64 AND length(dataset_hash) = 64",
            name="ck_coverage_gate_hashes",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_coverage_gate_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_coverage_gate_simulation",
        ),
        Index(
            "ix_coverage_gate_status",
            "gate_key",
            "status",
            "evaluated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    gate_key: Mapped[str] = mapped_column(String(120))
    gate_version: Mapped[str] = mapped_column(String(40))
    competition: Mapped[str] = mapped_column(String(120))
    season: Mapped[str] = mapped_column(String(40))
    feature_family: Mapped[str] = mapped_column(String(80))
    cutoff_class: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(50))
    coverage: Mapped[float] = mapped_column(Float)
    quality_score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class MatchupHypothesisModel(Base):
    """Hypothèse propriétaire préenregistrée avant toute évaluation."""

    __tablename__ = "matchup_hypotheses"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_id",
            "hypothesis_version",
            name="uq_matchup_hypothesis_version",
        ),
        UniqueConstraint(
            "preregistration_hash",
            "hypothesis_version",
            name="uq_matchup_hypothesis_preregistration_version",
        ),
        CheckConstraint(
            "length(preregistration_hash) = 64 "
            "AND length(dataset_hash) = 64",
            name="ck_matchup_hypothesis_hashes",
        ),
        CheckConstraint(
            "frozen_at >= registered_at",
            name="ck_matchup_hypothesis_frozen",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_matchup_hypothesis_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_matchup_hypothesis_simulation",
        ),
        Index(
            "ix_matchup_hypothesis_status",
            "family",
            "status",
            "registered_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(120))
    hypothesis_version: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(250))
    family: Mapped[str] = mapped_column(String(80))
    hypothesis: Mapped[str] = mapped_column(Text)
    protocol: Mapped[dict[str, object]] = mapped_column(JSON)
    required_gates: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50))
    preregistration_hash: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class MatchupEvaluationModel(Base):
    """Résultat apparié, versionné et reproductible d'une hypothèse."""

    __tablename__ = "matchup_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_id",
            "evaluation_scope",
            "fold_key",
            "model_key",
            "dataset_hash",
            name="uq_matchup_evaluation_fold",
        ),
        CheckConstraint(
            "support >= 0",
            name="ck_matchup_evaluation_support",
        ),
        CheckConstraint(
            "(p_value IS NULL OR (p_value >= 0 AND p_value <= 1)) "
            "AND (q_value_family IS NULL OR "
            "(q_value_family >= 0 AND q_value_family <= 1)) "
            "AND (q_value_global IS NULL OR "
            "(q_value_global >= 0 AND q_value_global <= 1))",
            name="ck_matchup_evaluation_probabilities",
        ),
        CheckConstraint(
            "length(paired_sample_hash) = 64 "
            "AND length(dataset_hash) = 64 "
            "AND length(evaluation_hash) = 64",
            name="ck_matchup_evaluation_hashes",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_matchup_evaluation_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_matchup_evaluation_simulation",
        ),
        Index(
            "ix_matchup_evaluation_status",
            "evaluation_scope",
            "status",
            "evaluated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT")
    )
    coverage_gate_id: Mapped[str | None] = mapped_column(
        ForeignKey("coverage_gates.id", ondelete="RESTRICT")
    )
    evaluation_scope: Mapped[str] = mapped_column(String(50))
    fold_key: Mapped[str] = mapped_column(String(120))
    model_key: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(80))
    support: Mapped[int] = mapped_column(Integer)
    effect: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    p_value: Mapped[float | None] = mapped_column(Float)
    q_value_family: Mapped[float | None] = mapped_column(Float)
    q_value_global: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50))
    paired_sample_hash: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    evaluation_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_revision: Mapped[str] = mapped_column(String(80))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectiveWatchlistModel(Base):
    """Entrée immuable de surveillance prospective, sans ordre réel."""

    __tablename__ = "prospective_watchlist"
    __table_args__ = (
        UniqueConstraint(
            "candidate_key",
            "watchlist_version",
            name="uq_prospective_watchlist_version",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at >= entered_at",
            name="ck_prospective_watchlist_window",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64 AND length(dataset_hash) = 64",
            name="ck_prospective_watchlist_hashes",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_prospective_watchlist_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_prospective_watchlist_simulation",
        ),
        Index(
            "ix_prospective_watchlist_status",
            "status",
            "entered_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    candidate_key: Mapped[str] = mapped_column(String(160))
    watchlist_version: Mapped[str] = mapped_column(String(40))
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT")
    )
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("matchup_evaluations.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64), unique=True)
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)


class ShadowCandidateVersionModel(Base):
    """Version append-only d'un candidat strictement limité au shadow."""

    __tablename__ = "shadow_candidate_versions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_key",
            "candidate_version",
            name="uq_shadow_candidate_version",
        ),
        CheckConstraint(
            "length(selection_rule_hash) = 64 "
            "AND length(evidence_hash) = 64 "
            "AND length(dataset_hash) = 64",
            name="ck_shadow_candidate_hashes",
        ),
        CheckConstraint(
            "production_status = 'PRODUCTION_LOCKED' "
            "AND real_bets = false AND no_bet_default = true",
            name="ck_shadow_candidate_production_locked",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_shadow_candidate_append_only",
        ),
        CheckConstraint(
            "simulation = true",
            name="ck_shadow_candidate_simulation",
        ),
        Index(
            "ix_shadow_candidate_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    candidate_key: Mapped[str] = mapped_column(String(160))
    candidate_version: Mapped[str] = mapped_column(String(40))
    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("prospective_watchlist.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(50))
    selection_rule: Mapped[dict[str, object]] = mapped_column(JSON)
    selection_rule_hash: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64), unique=True)
    dataset_version: Mapped[str] = mapped_column(String(120))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    production_status: Mapped[str] = mapped_column(
        String(40),
        default="PRODUCTION_LOCKED",
    )
    real_bets: Mapped[bool] = mapped_column(Boolean, default=False)
    no_bet_default: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("shadow_candidate_versions.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
    simulation: Mapped[bool] = mapped_column(Boolean, default=True)
