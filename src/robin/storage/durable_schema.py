"""Schéma durable du registre prospectif et de l'entrepôt shadow."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from robin.storage.models import Base

metadata: MetaData = Base.metadata


def registry_columns() -> list[Any]:
    return [
        Column("id", String(36), primary_key=True),
        Column("business_key", String(500), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("provider", String(120), nullable=False),
        Column("observed_at", DateTime(timezone=True), nullable=False),
        Column("ingested_at", DateTime(timezone=True), nullable=False),
        Column("schema_version", String(80), nullable=False),
        Column(
            "source_run_id",
            String(36),
            ForeignKey("ingestion_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        Column("provenance_status", String(40), nullable=False),
        Column("quality_status", String(40), nullable=False),
        Column("payload", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("last_observed_at", DateTime(timezone=True), nullable=False),
    ]


def registry_table(name: str, *extra: Any) -> Table:
    return Table(
        name,
        metadata,
        *registry_columns(),
        *extra,
        UniqueConstraint(
            "business_key",
            "content_hash",
            name=f"uq_{name}_business_content",
        ),
        Index(f"ix_{name}_provider_time", "provider", "observed_at"),
        Index(f"ix_{name}_run", "source_run_id"),
    )


ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("idempotency_key", String(250), nullable=False, unique=True),
    Column("pipeline_name", String(120), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(40), nullable=False),
    Column("source_version", String(120), nullable=False),
    Column("durable_backend", String(80), nullable=False),
    Column("durable_commit", String(64)),
    Column("error_message", Text),
    Index("ix_ingestion_runs_pipeline_time", "pipeline_name", "started_at"),
)

raw_payloads = Table(
    "raw_payloads",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("provider", String(120), nullable=False),
    Column("object_location", String(1000), nullable=False),
    Column("byte_size", Integer, nullable=False),
    Column("compression", String(20), nullable=False),
    Column("schema_version", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_observed_at", DateTime(timezone=True), nullable=False),
    Index("ix_raw_payloads_provider_time", "provider", "last_observed_at"),
)

provider_requests = Table(
    "provider_requests",
    metadata,
    *registry_columns(),
    Column("raw_payload_id", String(36), ForeignKey("raw_payloads.id")),
    Column("endpoint", String(500), nullable=False),
    Column("http_status", Integer),
    Column("quota_cost", Integer, nullable=False, default=0),
    UniqueConstraint(
        "business_key",
        "content_hash",
        name="uq_provider_requests_business_content",
    ),
    Index("ix_provider_requests_provider_time", "provider", "observed_at"),
    Index("ix_provider_requests_run", "source_run_id"),
)

fixtures = registry_table(
    "durable_fixtures",
    Column("fixture_id", String(36), nullable=False),
    Column("kickoff_at", DateTime(timezone=True)),
    Column("competition", String(120)),
    Column("status", String(40)),
    Index("ix_durable_fixtures_fixture", "fixture_id", "kickoff_at"),
)
provider_entity_mappings = registry_table(
    "provider_entity_mappings",
    Column("internal_entity_id", String(36), nullable=False),
    Column("provider_entity_id", String(250), nullable=False),
    Column("entity_type", String(40), nullable=False),
)
bookmakers = registry_table(
    "bookmakers",
    Column("bookmaker_id", String(36), nullable=False),
)
markets = registry_table(
    "markets",
    Column("market_key", String(250), nullable=False),
    Column("market_type", String(50), nullable=False),
)
odds_snapshots = registry_table(
    "odds_snapshots",
    Column("fixture_id", String(36), nullable=False),
    Column("snapshot_id", String(36), nullable=False),
    Column("market_type", String(50)),
    Index("ix_odds_snapshots_fixture_time", "fixture_id", "observed_at"),
)
prediction_runs = registry_table(
    "prediction_runs",
    Column("model_version", String(120), nullable=False),
)
predictions = registry_table(
    "predictions",
    Column("fixture_id", String(36), nullable=False),
    Column("prediction_id", String(36), nullable=False),
    Column("model_version", String(120), nullable=False),
    Index("ix_predictions_fixture_time", "fixture_id", "observed_at"),
)
candidate_bets = registry_table(
    "candidate_bets",
    Column("fixture_id", String(36), nullable=False),
    Column("strategy_version", String(120), nullable=False),
)
rejected_bets = registry_table(
    "rejected_bets",
    Column("fixture_id", String(36), nullable=False),
    Column("reason_code", String(120), nullable=False),
)
shadow_bets = registry_table(
    "shadow_bets",
    Column("fixture_id", String(36), nullable=False),
    Column("strategy_version", String(120), nullable=False),
    Column("stake", Float, nullable=False, default=0),
    Column("simulation", Boolean, nullable=False, default=True),
)
settlements = registry_table(
    "settlements",
    Column("fixture_id", String(36), nullable=False),
    Column("settlement_status", String(40), nullable=False),
)
quality_runs = registry_table(
    "quality_runs",
    Column("overall_status", String(40), nullable=False),
)
quality_results = registry_table(
    "quality_results",
    Column("check_code", String(160), nullable=False),
    Column("check_status", String(40), nullable=False),
)
pipeline_incidents = registry_table(
    "pipeline_incidents",
    Column("incident_code", String(160), nullable=False),
    Column("severity", String(30), nullable=False),
    Column("incident_status", String(40), nullable=False),
)
quota_usage = registry_table(
    "quota_usage",
    Column("credits_used", Integer, nullable=False, default=0),
    Column("credits_remaining", Integer),
    Column("budget_level", String(40), nullable=False),
)
scheduler_windows = registry_table(
    "scheduler_windows",
    Column("fixture_id", String(36), nullable=False),
    Column("window_name", String(20), nullable=False),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    Column("acceptable_from", DateTime(timezone=True), nullable=False),
    Column("acceptable_until", DateTime(timezone=True), nullable=False),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("window_status", String(40), nullable=False),
    Column("observation_received", Boolean, nullable=False, default=False),
    Column("market_available", Boolean),
    Column("provider_status", String(40)),
    Index("ix_scheduler_windows_fixture", "fixture_id", "window_name"),
    Index("ix_scheduler_windows_status_due", "window_status", "scheduled_for"),
)
burn_in_daily_metrics = registry_table(
    "burn_in_daily_metrics",
    Column("metric_date", Date, nullable=False),
    Column("health_status", String(40), nullable=False),
    Column("coverage_rate", Float, nullable=False),
    Column("workflow_success_rate", Float, nullable=False),
    UniqueConstraint(
        "metric_date",
        "content_hash",
        name="uq_burn_in_daily_metric_version",
    ),
)

JALON4_TABLES = {
    table.name
    for table in (
        ingestion_runs,
        raw_payloads,
        provider_requests,
        fixtures,
        provider_entity_mappings,
        bookmakers,
        markets,
        odds_snapshots,
        prediction_runs,
        predictions,
        candidate_bets,
        rejected_bets,
        shadow_bets,
        settlements,
        quality_runs,
        quality_results,
        pipeline_incidents,
        quota_usage,
        scheduler_windows,
        burn_in_daily_metrics,
    )
}

REGISTRY_TABLES = {
    table.name: table
    for table in (
        provider_requests,
        fixtures,
        provider_entity_mappings,
        bookmakers,
        markets,
        odds_snapshots,
        prediction_runs,
        predictions,
        candidate_bets,
        rejected_bets,
        shadow_bets,
        settlements,
        quality_runs,
        quality_results,
        pipeline_incidents,
        quota_usage,
        scheduler_windows,
        burn_in_daily_metrics,
    )
}
