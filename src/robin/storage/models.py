"""Schéma transactionnel minimal du jalon 1."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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
