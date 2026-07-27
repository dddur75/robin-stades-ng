"""SQLAlchemy projections for the R2-first Jalon 12 lane.

Raw provider bodies are intentionally absent: only immutable indexes, compact
normalised projections and evidence hashes are stored in PostgreSQL.
"""

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
from sqlalchemy.orm import Mapped, mapped_column

from robin.storage.models import Base


class ProspectiveFixtureModel(Base):
    __tablename__ = "prospective_fixtures"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_fixture_id", "registry_hash",
            name="uq_prospective_fixture_version",
        ),
        CheckConstraint(
            "length(registry_hash) = 64 AND append_only = true",
            name="ck_prospective_fixture_integrity",
        ),
        Index("ix_prospective_fixture_kickoff", "competition", "kickoff_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    competition: Mapped[str] = mapped_column(String(120))
    season: Mapped[str] = mapped_column(String(40))
    phase: Mapped[str] = mapped_column(String(120))
    home_team_id: Mapped[str] = mapped_column(String(120))
    away_team_id: Mapped[str] = mapped_column(String(120))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(120))
    provider_fixture_id: Mapped[str] = mapped_column(String(120))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registry_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    kickoff_reliable: Mapped[bool] = mapped_column(Boolean, default=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class CaptureWindowModel(Base):
    __tablename__ = "capture_windows"
    __table_args__ = (
        CheckConstraint(
            "opens_at <= due_at AND due_at <= cutoff_at "
            "AND cutoff_at < kickoff_at",
            name="ck_capture_window_temporal_order",
        ),
        CheckConstraint(
            "append_only = true",
            name="ck_capture_window_append_only",
        ),
        Index("ix_capture_window_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    window_id: Mapped[str] = mapped_column(String(250), unique=True)
    fixture_record_id: Mapped[str] = mapped_column(
        ForeignKey("prospective_fixtures.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    family: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(40))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    operational_tolerance_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(80))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class CaptureAttemptModel(Base):
    __tablename__ = "capture_attempts"
    __table_args__ = (
        UniqueConstraint(
            "window_record_id", "attempt_number",
            name="uq_capture_attempt_window_number",
        ),
        CheckConstraint(
            "attempt_number >= 1 AND attempt_number <= 5 "
            "AND provider_calls >= 0 AND provider_calls <= 1 "
            "AND provider_credits >= 0 AND append_only = true",
            name="ck_capture_attempt_bounds",
        ),
        Index("ix_capture_attempt_status", "status", "attempted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(250), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(250), unique=True)
    window_id: Mapped[str] = mapped_column(String(250), index=True)
    window_record_id: Mapped[str] = mapped_column(
        ForeignKey("capture_windows.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(40))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))
    retry_disposition: Mapped[str] = mapped_column(String(40))
    attempt_number: Mapped[int] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    provider_calls: Mapped[int] = mapped_column(Integer)
    provider_credits: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(120))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class CaptureReceiptModel(Base):
    __tablename__ = "capture_receipts"
    __table_args__ = (
        CheckConstraint(
            "length(receipt_hash) = 64 AND length(payload_sha256) = 64 "
            "AND payload_bytes >= 0 AND stored_bytes >= 0 "
            "AND provider_calls >= 0 AND provider_calls <= 1 "
            "AND cutoff_at < kickoff_at AND append_only = true",
            name="ck_capture_receipt_integrity",
        ),
        Index("ix_capture_receipt_fixture_family", "fixture_id", "family", "observed_at"),
        Index("ix_capture_receipts_r2_key", "r2_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_hash: Mapped[str] = mapped_column(String(64), unique=True)
    window_id: Mapped[str | None] = mapped_column(String(250), nullable=True)
    window_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("capture_windows.id", ondelete="RESTRICT"), nullable=True
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    competition: Mapped[str] = mapped_column(String(120))
    season: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(40))
    window_label: Mapped[str] = mapped_column(String(40))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    materialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seconds_before_kickoff: Mapped[int] = mapped_column(Integer)
    http_status: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_bytes: Mapped[int] = mapped_column(Integer)
    stored_bytes: Mapped[int] = mapped_column(Integer)
    r2_key: Mapped[str] = mapped_column(String(1500))
    receipt_r2_key: Mapped[str] = mapped_column(String(1500), unique=True)
    source_endpoint: Mapped[str] = mapped_column(String(500))
    complete: Mapped[bool] = mapped_column(Boolean)
    quality_status: Mapped[str] = mapped_column(String(40))
    provider_calls: Mapped[int] = mapped_column(Integer)
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectivePayloadIndexModel(Base):
    __tablename__ = "prospective_payload_index"
    __table_args__ = (
        CheckConstraint(
            "length(payload_sha256) = 64 AND payload_bytes >= 0 "
            "AND stored_bytes >= 0 AND append_only = true",
            name="ck_prospective_payload_index_integrity",
        ),
        Index("ix_prospective_payload_fixture", "fixture_id", "family", "observed_at"),
        Index("ix_prospective_payload_r2_key", "r2_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT"), unique=True
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    family: Mapped[str] = mapped_column(String(40))
    r2_key: Mapped[str] = mapped_column(String(1500))
    receipt_r2_key: Mapped[str] = mapped_column(String(1500), unique=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_bytes: Mapped[int] = mapped_column(Integer)
    stored_bytes: Mapped[int] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectivePlayerStatusModel(Base):
    __tablename__ = "prospective_player_status"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id", "player_id", name="uq_prospective_player_status_receipt_player"
        ),
        CheckConstraint(
            "length(projection_hash) = 64 AND append_only = true",
            name="ck_prospective_player_status_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    team_id: Mapped[str] = mapped_column(String(120))
    player_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(String(250))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    projection_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectiveInjuryModel(Base):
    __tablename__ = "prospective_injuries"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id", "player_id", "status",
            name="uq_prospective_injury_receipt_player_status",
        ),
        CheckConstraint(
            "length(projection_hash) = 64 AND append_only = true",
            name="ck_prospective_injury_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    team_id: Mapped[str] = mapped_column(String(120))
    player_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    projection_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectiveLineupModel(Base):
    __tablename__ = "prospective_lineups"
    __table_args__ = (
        UniqueConstraint("receipt_id", "team_id", name="uq_prospective_lineup_receipt_team"),
        CheckConstraint(
            "starter_count = 11 AND identities_complete = true "
            "AND length(lineup_hash) = 64 AND append_only = true",
            name="ck_prospective_lineup_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    team_id: Mapped[str] = mapped_column(String(120))
    starter_ids: Mapped[list[str]] = mapped_column(JSON)
    starter_count: Mapped[int] = mapped_column(Integer)
    identities_complete: Mapped[bool] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lineup_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectiveFormationModel(Base):
    __tablename__ = "prospective_formations"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id", "team_id", name="uq_prospective_formation_receipt_team"
        ),
        CheckConstraint(
            "length(projection_hash) = 64 AND append_only = true",
            name="ck_prospective_formation_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120), index=True)
    team_id: Mapped[str] = mapped_column(String(120))
    formation: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    projection_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProspectiveOddsSnapshotModel(Base):
    __tablename__ = "prospective_odds_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "receipt_id", "bookmaker", "market", "selection",
            name="uq_prospective_odds_receipt_selection",
        ),
        CheckConstraint(
            "odds > 1 AND margin >= 0 AND length(snapshot_hash) = 64 "
            "AND append_only = true",
            name="ck_prospective_odds_integrity",
        ),
        Index("ix_prospective_odds_fixture", "fixture_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("capture_receipts.id", ondelete="RESTRICT")
    )
    fixture_id: Mapped[str] = mapped_column(String(120))
    bookmaker: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(120))
    odds: Mapped[float] = mapped_column(Float)
    margin: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fixture_match_status: Mapped[str] = mapped_column(String(40))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class TemporalDataGateModel(Base):
    __tablename__ = "temporal_data_gates"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_temporal_data_gate_idempotency"
        ),
        CheckConstraint(
            "coverage >= 0 AND coverage <= 1 "
            "AND length(evidence_hash) = 64 AND append_only = true",
            name="ck_temporal_data_gate_integrity",
        ),
        Index("ix_temporal_data_gate_fixture", "fixture_id", "gate_name", "evaluated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250))
    fixture_id: Mapped[str] = mapped_column(String(120))
    gate_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(60))
    coverage: Mapped[float] = mapped_column(Float)
    observations: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(250))
    evidence: Mapped[dict[str, object]] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class ProviderBudgetLedgerModel(Base):
    __tablename__ = "provider_budget_ledger"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_provider_budget_ledger_idempotency"
        ),
        CheckConstraint(
            "units >= 0 AND cumulative_units >= units AND hard_limit > 0 "
            "AND provider_remaining >= 0 AND provider_reserve >= 0 "
            "AND append_only = true",
            name="ck_provider_budget_ledger_bounds",
        ),
        Index("ix_provider_budget_recorded", "provider", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(250))
    provider: Mapped[str] = mapped_column(String(80))
    units: Mapped[int] = mapped_column(Integer)
    cumulative_units: Mapped[int] = mapped_column(Integer)
    hard_limit: Mapped[int] = mapped_column(Integer)
    provider_remaining: Mapped[int] = mapped_column(Integer)
    provider_reserve: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(250))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_revision: Mapped[str] = mapped_column(String(80))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)
