"""Append-only SQLAlchemy projections for hypothesis intelligence evidence."""

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


class HypothesisRegistryModel(Base):
    __tablename__ = "hypothesis_registry"
    __table_args__ = (
        UniqueConstraint("hypothesis_id", name="uq_hypothesis_registry_id"),
        CheckConstraint(
            "origin IN ('MACHINE_DISCOVERED','OWNER_PROPOSED',"
            "'MODEL_DISCOVERED','LITERATURE_PROPOSED') "
            "AND promotion_locked = true AND append_only = true",
            name="ck_hypothesis_registry_security",
        ),
        Index("ix_hypothesis_registry_origin_status", "origin", "status"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(120))
    origin: Mapped[str] = mapped_column(String(60))
    family: Mapped[str] = mapped_column(String(160))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(100))
    canonical_fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promotion_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisVersionModel(Base):
    __tablename__ = "hypothesis_versions"
    __table_args__ = (
        UniqueConstraint(
            "registry_id",
            "hypothesis_version",
            name="uq_hypothesis_version",
        ),
        CheckConstraint(
            "length(payload_hash) = 64 AND append_only = true",
            name="ck_hypothesis_version_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    registry_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_registry.id", ondelete="RESTRICT")
    )
    hypothesis_version: Mapped[str] = mapped_column(String(40))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypothesis_versions.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisDiscoveryMetricModel(Base):
    __tablename__ = "hypothesis_discovery_metrics"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_version_id",
            "discovery_run_id",
            name="uq_hypothesis_discovery_metric",
        ),
        CheckConstraint(
            "historical_support >= 0 AND length(metrics_hash) = 64 "
            "AND append_only = true",
            name="ck_hypothesis_discovery_metric_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    hypothesis_version_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_versions.id", ondelete="RESTRICT")
    )
    discovery_run_id: Mapped[str] = mapped_column(String(160))
    discovery_dataset_hash: Mapped[str] = mapped_column(String(64))
    discovery_code_revision: Mapped[str] = mapped_column(String(80))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    historical_support: Mapped[int] = mapped_column(Integer)
    historical_profit: Mapped[float | None] = mapped_column(Float)
    historical_roi: Mapped[float | None] = mapped_column(Float)
    p_value: Mapped[float | None] = mapped_column(Float)
    q_value: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    metrics_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisProspectiveContractModel(Base):
    __tablename__ = "hypothesis_prospective_contracts"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_version_id",
            "contract_version",
            name="uq_hypothesis_prospective_contract",
        ),
        CheckConstraint(
            "length(contract_hash) = 64 AND length(price_contract_hash) = 64 "
            "AND minimum_descriptive_support = 30 "
            "AND minimum_exploratory_support = 80 "
            "AND promotion_locked = true AND append_only = true",
            name="ck_hypothesis_prospective_contract_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    hypothesis_version_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_versions.id", ondelete="RESTRICT")
    )
    contract_version: Mapped[str] = mapped_column(String(40))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    price_contract: Mapped[dict[str, object]] = mapped_column(JSON)
    price_contract_hash: Mapped[str] = mapped_column(String(64))
    protocol: Mapped[dict[str, object]] = mapped_column(JSON)
    minimum_descriptive_support: Mapped[int] = mapped_column(Integer)
    minimum_exploratory_support: Mapped[int] = mapped_column(Integer)
    contract_hash: Mapped[str] = mapped_column(String(64), unique=True)
    promotion_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypothesis_prospective_contracts.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisObservationModel(Base):
    __tablename__ = "hypothesis_observations"
    __table_args__ = (
        UniqueConstraint(
            "prospective_contract_id",
            "fixture_id",
            "cutoff_name",
            "cutoff_at",
            name="uq_hypothesis_observation_business",
        ),
        CheckConstraint(
            "length(conditions_hash) = 64 AND length(payload_hash) = 64 "
            "AND cutoff_at < kickoff_at "
            "AND (status != 'ELIGIBLE_FROZEN' OR observed_at <= cutoff_at) "
            "AND append_only = true",
            name="ck_hypothesis_observation_integrity",
        ),
        Index(
            "ix_hypothesis_observation_fixture_cutoff",
            "fixture_id",
            "cutoff_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    prospective_contract_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_prospective_contracts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(80))
    cutoff_name: Mapped[str] = mapped_column(String(40))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    odds: Mapped[float | None] = mapped_column(Float)
    margin: Mapped[float | None] = mapped_column(Float)
    bookmaker_scope: Mapped[list[str]] = mapped_column(JSON)
    conditions_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    conditions_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(60))
    status_reason: Mapped[str] = mapped_column(String(250))
    code_revision: Mapped[str] = mapped_column(String(80))
    payload_hash: Mapped[str] = mapped_column(String(64), unique=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisSettlementModel(Base):
    __tablename__ = "hypothesis_settlements"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "result_version",
            name="uq_hypothesis_settlement_version",
        ),
        CheckConstraint(
            "result_version >= 1 AND length(result_hash) = 64 "
            "AND length(settlement_hash) = 64 AND append_only = true",
            name="ck_hypothesis_settlement_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_observations.id", ondelete="RESTRICT")
    )
    result_version: Mapped[int] = mapped_column(Integer)
    result_status: Mapped[str] = mapped_column(String(40))
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    profit_units: Mapped[float] = mapped_column(Float)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result_hash: Mapped[str] = mapped_column(String(64))
    settlement_hash: Mapped[str] = mapped_column(String(64), unique=True)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypothesis_settlements.id", ondelete="RESTRICT")
    )
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisStatusEventModel(Base):
    __tablename__ = "hypothesis_status_events"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_hypothesis_status_event_hash"),
        CheckConstraint(
            "sequence_no >= 0 AND length(previous_hash) = 64 "
            "AND length(event_hash) = 64 AND production_locked = true "
            "AND real_bets = false AND promoted = false AND append_only = true "
            "AND NOT (kind = 'HYPOTHESIS_VALIDATED' AND automatic = true)",
            name="ck_hypothesis_status_event_integrity",
        ),
        Index(
            "ix_hypothesis_status_event_stream",
            "hypothesis_id",
            "sequence_no",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(120))
    sequence_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(100))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    evidence_hashes: Mapped[list[str]] = mapped_column(JSON)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    previous_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    automatic: Mapped[bool] = mapped_column(Boolean, default=True)
    production_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    real_bets: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


HYPOTHESIS_TABLES = frozenset(
    {
        "hypothesis_registry",
        "hypothesis_versions",
        "hypothesis_discovery_metrics",
        "hypothesis_prospective_contracts",
        "hypothesis_observations",
        "hypothesis_settlements",
        "hypothesis_status_events",
    }
)

__all__ = [
    "HYPOTHESIS_TABLES",
    "HypothesisDiscoveryMetricModel",
    "HypothesisObservationModel",
    "HypothesisProspectiveContractModel",
    "HypothesisRegistryModel",
    "HypothesisSettlementModel",
    "HypothesisStatusEventModel",
    "HypothesisVersionModel",
]
