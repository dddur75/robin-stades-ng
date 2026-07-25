"""Schéma relationnel de contrôle de la Deep Data Factory.

Les faits volumineux restent en Parquet ; PostgreSQL conserve les identités,
manifests, états, qualités et résultats synthétiques.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
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


def provenance_columns() -> list[Any]:
    return [
        Column("source_provider", String(80), nullable=False, default="api-football"),
        Column("source_run_id", String(120), nullable=False),
        Column("raw_payload_hash", String(64)),
        Column("availability_status", String(50), nullable=False),
        Column("quality_status", String(40), nullable=False),
        Column("observed_at", DateTime(timezone=True), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    ]


api_football_coverage = Table(
    "api_football_coverage",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("competition_name", String(160), nullable=False),
    Column("provider_competition_id", Integer),
    Column("season", Integer, nullable=False),
    Column("endpoint", String(160), nullable=False),
    Column("coverage_status", String(30), nullable=False),
    Column("advertised_coverage", JSON, nullable=False),
    Column("rows_received", Integer, nullable=False, default=0),
    Column("pages", Integer, nullable=False, default=0),
    Column("quota_consumed", Integer, nullable=False, default=0),
    Column("raw_bytes", Integer, nullable=False, default=0),
    Column("compressed_bytes", Integer, nullable=False, default=0),
    Column("normalized_bytes", Integer, nullable=False, default=0),
    Column("last_checked_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "competition_name",
        "season",
        "endpoint",
        name="uq_api_football_coverage_scope",
    ),
)

historical_ingestion_runs = Table(
    "historical_ingestion_runs",
    metadata,
    Column("id", String(120), primary_key=True),
    Column("idempotency_key", String(250), nullable=False, unique=True),
    Column("mode", String(30), nullable=False),
    Column("status", String(40), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("calls", Integer, nullable=False, default=0),
    Column("rows_received", Integer, nullable=False, default=0),
    Column("quota_remaining", Integer),
    Column("manifest_location", String(1000)),
    Column("error_code", String(160)),
)

historical_backfill_tasks = Table(
    "historical_backfill_tasks",
    metadata,
    Column("task_id", String(120), primary_key=True),
    Column("provider", String(80), nullable=False),
    Column("competition_id", Integer, nullable=False),
    Column("season", Integer, nullable=False),
    Column("endpoint", String(160), nullable=False),
    Column("page", Integer, nullable=False, default=1),
    Column("fixture_id", Integer),
    Column("team_id", Integer),
    Column("player_id", Integer),
    Column("priority", String(10), nullable=False),
    Column("estimated_calls", Integer, nullable=False),
    Column("status", String(40), nullable=False),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("last_attempt_at", DateTime(timezone=True)),
    Column("next_retry_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("rows_received", Integer, nullable=False, default=0),
    Column("payload_hash", String(64)),
    Column("error_code", String(160)),
    Column("coverage_status", String(30), nullable=False),
    Index("ix_historical_tasks_ready", "status", "priority", "season"),
)


def identity_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column("provider_id", String(120), nullable=False),
        Column("display_name", String(300)),
        Column("attributes", JSON, nullable=False),
        *provenance_columns(),
        UniqueConstraint(
            "source_provider",
            "provider_id",
            name=f"uq_{name}_provider_id",
        ),
    )


competitions = identity_table("competitions")
seasons = identity_table("seasons")
players = identity_table("players")
coaches = identity_table("coaches")
venues = identity_table("venues")
referees = identity_table("referees")


def fact_table(name: str, *extra: Any) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column("business_key", String(500), nullable=False),
        Column("payload", JSON, nullable=False),
        *extra,
        *provenance_columns(),
        UniqueConstraint(
            "business_key",
            "raw_payload_hash",
            name=f"uq_{name}_business_payload",
        ),
    )


team_seasons = fact_table("team_seasons", Column("season", Integer, nullable=False))
player_seasons = fact_table(
    "player_seasons",
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
    Column("season", Integer, nullable=False),
)
squads = fact_table("squads", Column("season", Integer, nullable=False))
fixture_status_history = fact_table(
    "fixture_status_history",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
)
fixture_events = fact_table(
    "fixture_events",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
)
fixture_team_statistics = fact_table(
    "fixture_team_statistics",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
)
fixture_player_statistics = fact_table(
    "fixture_player_statistics",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
)
lineups = fact_table(
    "lineups",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
)
lineup_players = fact_table(
    "lineup_players",
    Column("lineup_id", String(36), ForeignKey("lineups.id", ondelete="CASCADE")),
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
)
formations = fact_table(
    "formations",
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
)
injuries = fact_table(
    "injuries",
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
)
suspensions = fact_table(
    "suspensions",
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
)
transfers = fact_table(
    "transfers",
    Column("player_id", String(36), ForeignKey("players.id", ondelete="RESTRICT")),
)
standings_snapshots = fact_table(
    "standings_snapshots",
    Column("season", Integer, nullable=False),
)

feature_definitions = Table(
    "feature_definitions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("feature_name", String(160), nullable=False),
    Column("feature_version", String(80), nullable=False),
    Column("entity_type", String(40), nullable=False),
    Column("formula", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("leakage_risk", String(40), nullable=False),
    Column("status", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("feature_name", "feature_version", name="uq_feature_definition"),
)

feature_snapshots = Table(
    "feature_snapshots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("feature_definition_id", String(36), ForeignKey("feature_definitions.id")),
    Column("entity_id", String(36), nullable=False),
    Column("fixture_id", String(36), ForeignKey("fixtures.id", ondelete="RESTRICT")),
    Column("as_of_time", DateTime(timezone=True), nullable=False),
    Column("value", JSON),
    Column("source_version", String(120), nullable=False),
    Column("quality_status", String(40), nullable=False),
    Column("availability_status", String(50), nullable=False),
    Column("calculated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "feature_definition_id",
        "entity_id",
        "fixture_id",
        "as_of_time",
        "source_version",
        name="uq_feature_snapshot_version",
    ),
    Index("ix_feature_snapshots_asof", "fixture_id", "as_of_time"),
)


def registry_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column("version", String(120), nullable=False),
        Column("status", String(50), nullable=False),
        Column("manifest", JSON, nullable=False),
        Column("artifact_hash", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("version", "artifact_hash", name=f"uq_{name}_version_hash"),
    )


dataset_versions = registry_table("dataset_versions")
training_runs = registry_table("training_runs")
model_versions = registry_table("model_versions")
backtest_runs = registry_table("backtest_runs")
strategy_versions = registry_table("strategy_versions")
strategy_results = Table(
    "strategy_results",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("strategy_version_id", String(36), ForeignKey("strategy_versions.id")),
    Column("backtest_run_id", String(36), ForeignKey("backtest_runs.id")),
    Column("sample_size", Integer, nullable=False),
    Column("roi", Float),
    Column("yield_value", Float),
    Column("clv", Float),
    Column("drawdown", Float),
    Column("confidence_interval", JSON, nullable=False),
    Column("status", String(50), nullable=False),
    Column("production_locked", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

HISTORICAL_TABLES = {
    table.name
    for table in (
        api_football_coverage,
        historical_ingestion_runs,
        historical_backfill_tasks,
        competitions,
        seasons,
        team_seasons,
        players,
        player_seasons,
        squads,
        coaches,
        venues,
        referees,
        fixture_status_history,
        fixture_events,
        fixture_team_statistics,
        fixture_player_statistics,
        lineups,
        lineup_players,
        formations,
        injuries,
        suspensions,
        transfers,
        standings_snapshots,
        feature_definitions,
        feature_snapshots,
        dataset_versions,
        training_runs,
        model_versions,
        backtest_runs,
        strategy_versions,
        strategy_results,
    )
}
