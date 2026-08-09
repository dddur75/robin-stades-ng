"""Compact append-only PostgreSQL projections for Robin Chronos V1.

Raw provider bodies never enter these models.  They remain authoritative in R2.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from robin.storage.models import Base

PRICE_CONTRACT_HASH = (
    "18835b64961986d154a1bc26211c0c2ee09075af42aa59a954d6ba5461e3de4c"
)
CANONICAL_TAG_REGISTRY_HASH = (
    "c95bedfe0a02e2858722e93af13023b5cf4edb53692f7e46216599a3a3979d7d"
)


class ChronosCanaryRunModel(Base):
    __tablename__ = "chronos_canary_runs"
    __table_args__ = (
        CheckConstraint(
            "max_fixtures <= 5 AND max_api_football_calls <= 50 "
            "AND max_odds_credits <= 100 AND max_r2_object_writes <= 2000 "
            "AND max_postgresql_rows <= 10000 AND max_technical_attempts <= 2 "
            "AND new_purchase_allowed = false AND r2_deletes_allowed = 0 "
            "AND destructive_sql_allowed = 0 AND planned_at < expires_at "
            "AND append_only = true",
            name="ck_chronos_canary_bounds",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canary_id: Mapped[str] = mapped_column(String(160), unique=True)
    plan_hash: Mapped[str] = mapped_column(String(64))
    policy_hash: Mapped[str] = mapped_column(String(64))
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activation_mode: Mapped[str] = mapped_column(String(40))
    max_fixtures: Mapped[int] = mapped_column(Integer)
    max_api_football_calls: Mapped[int] = mapped_column(Integer)
    max_odds_credits: Mapped[int] = mapped_column(Integer)
    max_r2_object_writes: Mapped[int] = mapped_column(Integer)
    max_postgresql_rows: Mapped[int] = mapped_column(Integer)
    max_technical_attempts: Mapped[int] = mapped_column(Integer)
    new_purchase_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    r2_deletes_allowed: Mapped[int] = mapped_column(Integer, default=0)
    destructive_sql_allowed: Mapped[int] = mapped_column(Integer, default=0)
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosCanaryCohortFixtureModel(Base):
    __tablename__ = "chronos_canary_cohort_fixtures"
    __table_args__ = (
        UniqueConstraint(
            "canary_run_id",
            "fixture_id",
            name="uq_chronos_canary_cohort_fixture",
        ),
        UniqueConstraint(
            "canary_run_id",
            "competition",
            name="uq_chronos_canary_cohort_competition",
        ),
        CheckConstraint(
            "length(cohort_hash) = 64 AND append_only = true",
            name="ck_chronos_canary_cohort_fixture",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canary_run_id: Mapped[str] = mapped_column(
        ForeignKey("chronos_canary_runs.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    competition: Mapped[str] = mapped_column(String(120))
    cohort_hash: Mapped[str] = mapped_column(String(64))
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosCanaryUsageEventModel(Base):
    __tablename__ = "chronos_canary_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "canary_run_id",
            "resource_kind",
            "phase",
            "operation_key",
            name="uq_chronos_canary_usage_event",
        ),
        CheckConstraint(
            "phase IN ('RESERVED','ACTUAL') AND units > 0 "
            "AND length(event_hash) = 64 AND append_only = true",
            name="ck_chronos_canary_usage_event",
        ),
        Index(
            "ix_chronos_canary_usage_resource",
            "canary_run_id",
            "resource_kind",
            "phase",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canary_run_id: Mapped[str] = mapped_column(
        ForeignKey("chronos_canary_runs.id", ondelete="RESTRICT")
    )
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    resource_kind: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str] = mapped_column(String(20))
    operation_key: Mapped[str] = mapped_column(String(500))
    units: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class CaptureIntentModel(Base):
    __tablename__ = "capture_intents"
    __table_args__ = (
        CheckConstraint(
            "opens_at <= due_at AND due_at <= cutoff_at "
            "AND cutoff_at < kickoff_at AND max_technical_attempts <= 2 "
            "AND reserved_provider_units >= 0 AND reserved_r2_objects >= 0 "
            "AND reserved_postgresql_rows >= 0 "
            f"AND ((family = 'ODDS' AND price_contract_hash = "
            f"'{PRICE_CONTRACT_HASH}') OR (family <> 'ODDS' "
            "AND price_contract_hash IS NULL)) AND append_only = true",
            name="ck_chronos_capture_intent_bounds",
        ),
        Index("ix_chronos_capture_intent_due", "due_at", "family"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    intent_hash: Mapped[str] = mapped_column(String(64), unique=True)
    canary_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("chronos_canary_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    window_record_id: Mapped[str] = mapped_column(
        ForeignKey("capture_windows.id", ondelete="RESTRICT"),
        unique=True,
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    cutoff_id: Mapped[str] = mapped_column(String(250))
    source: Mapped[str] = mapped_column(String(120))
    provider_kind: Mapped[str] = mapped_column(String(40))
    family: Mapped[str] = mapped_column(String(40))
    request_contract_hash: Mapped[str] = mapped_column(String(64))
    price_contract_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_technical_attempts: Mapped[int] = mapped_column(Integer, default=2)
    reserved_provider_units: Mapped[int] = mapped_column(Integer, default=0)
    reserved_r2_objects: Mapped[int] = mapped_column(Integer, default=0)
    reserved_postgresql_rows: Mapped[int] = mapped_column(Integer, default=0)
    policy_version: Mapped[str] = mapped_column(String(80))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosCanaryRunWindowModel(Base):
    __tablename__ = "chronos_canary_run_windows"
    __table_args__ = (
        UniqueConstraint(
            "canary_run_id",
            "intent_id",
            name="uq_chronos_canary_run_intent",
        ),
        CheckConstraint(
            "length(plan_hash) = 64 AND append_only = true",
            name="ck_chronos_canary_run_window",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canary_run_id: Mapped[str] = mapped_column(
        ForeignKey("chronos_canary_runs.id", ondelete="RESTRICT")
    )
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("capture_intents.id", ondelete="RESTRICT")
    )
    window_record_id: Mapped[str] = mapped_column(
        ForeignKey("capture_windows.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    plan_hash: Mapped[str] = mapped_column(String(64))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class KnownAtFactMetadataModel(Base):
    __tablename__ = "known_at_fact_metadata"
    __table_args__ = (
        CheckConstraint(
            "length(fact_id) > 64 AND length(source_object_hash) = 64 "
            "AND length(normalized_fact_hash) = 64 "
            "AND (requested_at IS NULL OR response_received_at IS NULL "
            "OR requested_at <= response_received_at) "
            "AND (response_received_at IS NULL OR known_at IS NULL "
            "OR response_received_at <= known_at) AND cutoff_at < kickoff_at "
            "AND ((temporal_class = 'KNOWN_AT_UNKNOWN' "
            "AND requested_at IS NULL AND response_received_at IS NULL "
            "AND known_at IS NULL) "
            "OR (temporal_class = 'ON_TIME' AND known_at <= cutoff_at) "
            "OR (temporal_class = 'LATE_FOR_CUTOFF' "
            "AND known_at > cutoff_at AND known_at < kickoff_at) "
            "OR (temporal_class = 'POST_KICKOFF_ONLY' AND known_at >= kickoff_at)) "
            "AND (supersedes_fact_id IS NULL OR supersedes_fact_id <> fact_id) "
            "AND append_only = true",
            name="ck_chronos_known_at_fact_temporal",
        ),
        Index("ix_chronos_fact_fixture_cutoff", "fixture_id", "cutoff_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(96), unique=True)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("capture_intents.id", ondelete="RESTRICT")
    )
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    entity_id: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(40))
    source_object_hash: Mapped[str] = mapped_column(String(64))
    normalized_fact_hash: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_at_basis: Mapped[str] = mapped_column(String(80))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temporal_class: Mapped[str] = mapped_column(String(40))
    scientific_role: Mapped[str] = mapped_column(String(40))
    quality_status: Mapped[str] = mapped_column(String(60))
    supersedes_fact_id: Mapped[str | None] = mapped_column(
        String(96),
        ForeignKey(
            "known_at_fact_metadata.fact_id",
            name="fk_chronos_fact_supersedes",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    schema_version: Mapped[str] = mapped_column(String(80))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceSnapshotMetadataModel(Base):
    __tablename__ = "price_snapshot_metadata"
    __table_args__ = (
        CheckConstraint(
            "length(price_snapshot_id) > 64 AND length(raw_object_hash) = 64 "
            "AND length(receipt_hash) = 64 "
            "AND length(request_contract_hash) = 64 "
            f"AND price_contract_hash = '{PRICE_CONTRACT_HASH}' "
            "AND odds_decimal > 1 "
            "AND requested_at <= response_received_at "
            "AND response_received_at = known_at AND cutoff_at < kickoff_at "
            "AND ((temporal_class = 'ON_TIME' AND known_at <= cutoff_at) "
            "OR (temporal_class = 'LATE_FOR_CUTOFF' "
            "AND known_at > cutoff_at AND known_at < kickoff_at) "
            "OR (temporal_class = 'POST_KICKOFF_ONLY' AND known_at >= kickoff_at)) "
            "AND ((provider_updated_at IS NULL AND price_age_seconds IS NULL "
            "AND quality_status = 'NO_PRICE') OR provider_updated_at IS NOT NULL) "
            "AND ((market = 'MATCH_RESULT_90M' AND line IS NULL "
            "AND selection IN ('HOME','DRAW','AWAY')) "
            "OR (market = 'TOTAL_GOALS_2_5_90M' AND line = 2.5 "
            "AND selection IN ('OVER_2_5','UNDER_2_5'))) "
            "AND append_only = true",
            name="ck_chronos_price_snapshot",
        ),
        UniqueConstraint(
            "receipt_id", "bookmaker", "market", "selection", "line",
            name="uq_chronos_price_receipt_selection",
        ),
        Index("ix_chronos_price_fixture_cutoff", "fixture_id", "cutoff_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    price_snapshot_id: Mapped[str] = mapped_column(String(96), unique=True)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("capture_intents.id", ondelete="RESTRICT")
    )
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(120))
    bookmaker: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(60))
    selection: Mapped[str] = mapped_column(String(40))
    line: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    odds_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    price_age_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_object_hash: Mapped[str] = mapped_column(String(64))
    receipt_hash: Mapped[str] = mapped_column(String(64))
    request_contract_hash: Mapped[str] = mapped_column(String(64))
    price_contract_hash: Mapped[str] = mapped_column(String(64))
    bookmaker_policy_hash: Mapped[str] = mapped_column(String(64))
    temporal_class: Mapped[str] = mapped_column(String(40))
    quality_status: Mapped[str] = mapped_column(String(60))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceDerivationMetadataModel(Base):
    __tablename__ = "price_derivation_metadata"
    __table_args__ = (
        CheckConstraint(
            "length(source_price_set_hash) = 64 "
            f"AND price_contract_hash = '{PRICE_CONTRACT_HASH}' "
            "AND length(definition_hash) = 64 "
            "AND length(inputs_hash) = 64 AND implied_probability > 0 "
            "AND devigged_probability > 0 AND devigged_probability <= 1 "
            "AND price_age_seconds >= 0 AND append_only = true",
            name="ck_chronos_price_derivation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    derivation_id: Mapped[str] = mapped_column(String(96), unique=True)
    price_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("price_snapshot_metadata.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    market: Mapped[str] = mapped_column(String(60))
    selection: Mapped[str] = mapped_column(String(40))
    source_price_set_hash: Mapped[str] = mapped_column(String(64))
    price_contract_hash: Mapped[str] = mapped_column(String(64))
    method_id: Mapped[str] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(40))
    definition_hash: Mapped[str] = mapped_column(String(64))
    inputs_hash: Mapped[str] = mapped_column(String(64))
    implied_probability: Mapped[Decimal] = mapped_column(Numeric(24, 18))
    market_overround: Mapped[Decimal] = mapped_column(Numeric(24, 18))
    devigged_probability: Mapped[Decimal] = mapped_column(Numeric(24, 18))
    best_available_price: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 12), nullable=True
    )
    median_market_price: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 12), nullable=True
    )
    price_age_seconds: Mapped[int] = mapped_column(Integer)
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketSnapshotMetadataModel(Base):
    __tablename__ = "market_snapshot_metadata"
    __table_args__ = (
        CheckConstraint(
            "length(market_snapshot_id) > 64 AND length(bookmakers_hash) = 64 "
            "AND length(input_set_hash) = 64 AND length(contract_hash) = 64 "
            f"AND price_contract_hash = '{PRICE_CONTRACT_HASH}' "
            "AND bookmaker_count >= 1 AND bookmaker_count <= 5 "
            "AND ((market = 'MATCH_RESULT_90M' AND line IS NULL "
            "AND home_probability IS NOT NULL AND draw_probability IS NOT NULL "
            "AND away_probability IS NOT NULL AND over_probability IS NULL "
            "AND under_probability IS NULL) OR "
            "(market = 'TOTAL_GOALS_2_5_90M' AND line = 2.5 "
            "AND home_probability IS NULL AND draw_probability IS NULL "
            "AND away_probability IS NULL AND over_probability IS NOT NULL "
            "AND under_probability IS NOT NULL)) AND append_only = true",
            name="ck_chronos_market_snapshot",
        ),
        Index("ix_chronos_market_fixture_cutoff", "fixture_id", "cutoff_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    market_snapshot_id: Mapped[str] = mapped_column(String(96), unique=True)
    fixture_id: Mapped[str] = mapped_column(String(120))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    market: Mapped[str] = mapped_column(String(60))
    line: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    bookmakers_hash: Mapped[str] = mapped_column(String(64))
    bookmaker_count: Mapped[int] = mapped_column(Integer)
    input_set_hash: Mapped[str] = mapped_column(String(64))
    contract_hash: Mapped[str] = mapped_column(String(64))
    price_contract_hash: Mapped[str] = mapped_column(String(64))
    home_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 18), nullable=True
    )
    draw_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 18), nullable=True
    )
    away_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 18), nullable=True
    )
    over_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 18), nullable=True
    )
    under_probability: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 18), nullable=True
    )
    confirmatory_admissible: Mapped[bool] = mapped_column(Boolean)
    quality_status: Mapped[str] = mapped_column(String(60))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class TagSnapshotMetadataModel(Base):
    __tablename__ = "tag_snapshot_metadata"
    __table_args__ = (
        CheckConstraint(
            "length(tag_snapshot_hash) = 64 "
            f"AND tag_registry_hash = '{CANONICAL_TAG_REGISTRY_HASH}' "
            "AND length(facts_manifest_hash) = 64 AND cutoff_at < kickoff_at "
            "AND true_count + false_count = known_count "
            "AND known_count + unknown_count = tag_count "
            "AND (supersedes_tag_snapshot_hash IS NULL "
            "OR supersedes_tag_snapshot_hash <> tag_snapshot_hash) "
            "AND append_only = true",
            name="ck_chronos_tag_snapshot",
        ),
        Index("ix_chronos_tag_fixture_cutoff", "fixture_id", "cutoff_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tag_snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    fixture_id: Mapped[str] = mapped_column(String(120))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tag_registry_hash: Mapped[str] = mapped_column(String(64))
    facts_manifest_hash: Mapped[str] = mapped_column(String(64))
    tag_count: Mapped[int] = mapped_column(Integer)
    known_count: Mapped[int] = mapped_column(Integer)
    true_count: Mapped[int] = mapped_column(Integer)
    false_count: Mapped[int] = mapped_column(Integer)
    unknown_count: Mapped[int] = mapped_column(Integer)
    tag_snapshot_r2_key: Mapped[str] = mapped_column(String(1500))
    supersedes_tag_snapshot_hash: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "tag_snapshot_metadata.tag_snapshot_hash",
            name="fk_chronos_tag_supersedes",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    schema_version: Mapped[str] = mapped_column(String(80))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosDataQualityEventModel(Base):
    __tablename__ = "data_quality_events"
    __table_args__ = (
        CheckConstraint(
            "length(event_id) = 64 AND length(evidence_hash) = 64 "
            "AND length(summary) <= 500 AND append_only = true",
            name="ck_chronos_data_quality_event",
        ),
        Index("ix_chronos_dq_fixture_cutoff", "fixture_id", "cutoff_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    fixture_id: Mapped[str] = mapped_column(String(120))
    cutoff_id: Mapped[str] = mapped_column(String(250))
    source: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(40))
    event_code: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(160))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    receipt_id: Mapped[str | None] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT"), nullable=True
    )
    intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("capture_intents.id", ondelete="RESTRICT"), nullable=True
    )
    summary: Mapped[str] = mapped_column(String(500))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosLineageNodeModel(Base):
    __tablename__ = "chronos_lineage_nodes"
    __table_args__ = (
        CheckConstraint(
            "length(content_hash) = 64 AND append_only = true",
            name="ck_chronos_lineage_node",
        ),
        Index("ix_chronos_lineage_node_kind", "node_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(160), unique=True)
    node_kind: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ChronosLineageEdgeModel(Base):
    __tablename__ = "chronos_lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "upstream_type",
            "upstream_id",
            "downstream_type",
            "downstream_id",
            "relationship",
            name="uq_chronos_lineage_edge",
        ),
        CheckConstraint(
            "length(edge_hash) = 64 AND upstream_id <> downstream_id "
            "AND length(upstream_hash) = 64 AND length(downstream_hash) = 64 "
            "AND length(contract_hash) = 64 "
            "AND append_only = true",
            name="ck_chronos_lineage_edge",
        ),
        Index("ix_chronos_lineage_upstream", "upstream_type", "upstream_id"),
        Index("ix_chronos_lineage_downstream", "downstream_type", "downstream_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    edge_hash: Mapped[str] = mapped_column(String(64), unique=True)
    upstream_type: Mapped[str] = mapped_column(String(40))
    upstream_id: Mapped[str] = mapped_column(String(160))
    downstream_type: Mapped[str] = mapped_column(String(40))
    downstream_id: Mapped[str] = mapped_column(String(160))
    relationship: Mapped[str] = mapped_column(String(60))
    upstream_hash: Mapped[str] = mapped_column(String(64))
    downstream_hash: Mapped[str] = mapped_column(String(64))
    contract_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


CHRONOS_TABLE_NAMES = (
    "chronos_canary_runs",
    "chronos_canary_cohort_fixtures",
    "chronos_canary_usage_events",
    "capture_intents",
    "chronos_canary_run_windows",
    "known_at_fact_metadata",
    "price_snapshot_metadata",
    "price_derivation_metadata",
    "market_snapshot_metadata",
    "tag_snapshot_metadata",
    "data_quality_events",
    "chronos_lineage_nodes",
    "chronos_lineage_edges",
)


__all__ = [
    "CHRONOS_TABLE_NAMES",
    "CaptureIntentModel",
    "ChronosCanaryCohortFixtureModel",
    "ChronosCanaryRunModel",
    "ChronosCanaryRunWindowModel",
    "ChronosCanaryUsageEventModel",
    "ChronosDataQualityEventModel",
    "ChronosLineageEdgeModel",
    "ChronosLineageNodeModel",
    "KnownAtFactMetadataModel",
    "MarketSnapshotMetadataModel",
    "PriceDerivationMetadataModel",
    "PriceSnapshotMetadataModel",
    "TagSnapshotMetadataModel",
]
