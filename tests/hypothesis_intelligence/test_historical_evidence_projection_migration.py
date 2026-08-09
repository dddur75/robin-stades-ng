from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from robin.storage.database import build_engine

HEAD = "0014_chronos_control_plane_v2"
MIGRATION_REVISION = "0013_historical_evidence_index"
TABLES = {
    "hypothesis_historical_evidence_summaries",
    "hypothesis_evidence_artifact_indexes",
    "historical_fixture_evidence_indexes",
    "hypothesis_fixture_membership_indexes",
}


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _summary_row() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "hypothesis_id": "J10-M001",
        "rule_hash": "a" * 64,
        "dataset_hash": "b" * 64,
        "campaign_result_hash": "c" * 64,
        "evidence_hash": "d" * 64,
        "source_revision": "e" * 40,
        "occurrences": 261,
        "settled": 261,
        "wins": 135,
        "losses": 126,
        "voids": 0,
        "hit_rate": Decimal("0.517241379310344828"),
        "average_odds": Decimal("2.250421455938697200"),
        "median_odds": Decimal("2.240000000000000000"),
        "total_stake_units": Decimal("261.00000000"),
        "total_return_units": Decimal("304.43000000"),
        "profit_units": Decimal("43.43000000"),
        "roi": Decimal("0.166398467432950200"),
        "max_drawdown_units": Decimal("8.20000000"),
        "max_losing_streak": 7,
        "confidence_interval": {"lower": 0.08, "upper": 0.25},
        "eligible_folds": 6,
        "positive_folds": 5,
        "distinct_seasons": 6,
        "distinct_teams": 20,
        "distinct_groups": 30,
        "p_value": 0.01,
        "q_value": 0.12,
        "status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
        "payload_object_key": "hypothesis-evidence/v1/J10-M001/summary.json",
        "payload_sha256": "f" * 64,
        "schema_version": "hypothesis-historical-evidence-v1",
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }


def _artifact_row() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "dataset_hash": "b" * 64,
        "campaign_result_hash": "c" * 64,
        "artifact_kind": "HYPOTHESIS_FIXTURE_MEMBERSHIP",
        "object_key": "hypothesis-evidence/v1/membership/part-00000.parquet",
        "payload_sha256": "9" * 64,
        "row_count": 681_466,
        "byte_size": 12_345_678,
        "content_type": "application/vnd.apache.parquet",
        "schema_version": "hypothesis-fixture-membership-v1",
        "partition_key": "dataset=b" + "b" * 63,
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }


def _membership_row() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "dataset_hash": "b" * 64,
        "campaign_result_hash": "c" * 64,
        "hypothesis_id": "J10-M001",
        "rule_hash": "a" * 64,
        "canonical_match_id": "J10-FIXTURE-000001",
        "membership_hash": "8" * 64,
        "competition_key": "LA_LIGA",
        "season": 2024,
        "kickoff_at": datetime(2025, 2, 1, 20, 0, tzinfo=UTC),
        "outcome": "WON",
        "observed_odds": Decimal("2.250000000000000000"),
        "market_margin": Decimal("0.054000000000000000"),
        "profit_units": Decimal("1.25000000"),
        "chronological_fold": "FOLD_4",
        "artifact_object_key": ("hypothesis-evidence/v1/membership/part-00000.parquet"),
        "artifact_row_group": 0,
        "artifact_row_offset": 42,
        "schema_version": "hypothesis-fixture-membership-index-v1",
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }


def _fixture_row() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "dataset_hash": "b" * 64,
        "canonical_match_id": "J10-FIXTURE-000001",
        "provider_fixture_id": "football-data:000001",
        "competition_key": "LA_LIGA",
        "competition_name": "Liga",
        "season": 2024,
        "kickoff_at": datetime(2025, 2, 1, 20, 0, tzinfo=UTC),
        "home_team_id": "team-home-001",
        "home_team_name": "Équipe domicile",
        "away_team_id": "team-away-001",
        "away_team_name": "Équipe extérieure",
        "home_goals": 1,
        "away_goals": 2,
        "final_status": "FINISHED",
        "source_row_hash": "5" * 64,
        "artifact_object_key": ("hypothesis-evidence/v1/fixtures/part-00000.parquet"),
        "artifact_row_group": 0,
        "artifact_row_offset": 17,
        "schema_version": "historical-fixture-evidence-index-v1",
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }


def test_historical_evidence_projection_is_compact_and_postgresql_safe() -> None:
    config = _config("sqlite+pysqlite:///:memory:")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == HEAD
    assert len(HEAD) <= 32

    revision = scripts.get_revision(MIGRATION_REVISION)
    assert revision is not None
    migration_metadata = revision.module.metadata
    assert TABLES == set(migration_metadata.tables)

    forbidden_detail_columns = {
        "fixture_id",
        "match_id",
        "membership",
        "memberships",
        "payload",
        "payload_body",
        "raw_payload",
        "raw_body",
        "provider_response",
    }
    summary = migration_metadata.tables["hypothesis_historical_evidence_summaries"]
    artifacts = migration_metadata.tables["hypothesis_evidence_artifact_indexes"]
    fixtures = migration_metadata.tables["historical_fixture_evidence_indexes"]
    memberships = migration_metadata.tables["hypothesis_fixture_membership_indexes"]
    for table in (summary, artifacts, fixtures, memberships):
        assert forbidden_detail_columns.isdisjoint(table.c.keys())
        assert {"append_only", "simulation"} <= set(table.c.keys())
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in ddl
    assert isinstance(summary.c.confidence_interval.type, sa.JSON)
    assert not any(
        isinstance(column.type, sa.JSON)
        for table in (artifacts, fixtures, memberships)
        for column in table.c
    )
    for column_name in (
        "hit_rate",
        "average_odds",
        "median_odds",
        "total_stake_units",
        "total_return_units",
        "profit_units",
        "roi",
        "max_drawdown_units",
    ):
        assert isinstance(summary.c[column_name].type, sa.Numeric)
    for column_name in ("observed_odds", "market_margin", "profit_units"):
        assert isinstance(memberships.c[column_name].type, sa.Numeric)
    assert {
        "observed_odds",
        "market_margin",
        "payload_sha256",
        "raw_payload",
    }.isdisjoint(fixtures.c.keys())


def test_historical_evidence_projection_round_trip_and_guards(
    tmp_path: Path,
) -> None:
    database = tmp_path / "historical-evidence-index.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = build_engine(url)
    inspector = sa.inspect(engine)
    assert TABLES <= set(inspector.get_table_names())

    summary = sa.Table(
        "hypothesis_historical_evidence_summaries",
        sa.MetaData(),
        autoload_with=engine,
    )
    artifacts = sa.Table(
        "hypothesis_evidence_artifact_indexes",
        sa.MetaData(),
        autoload_with=engine,
    )
    memberships = sa.Table(
        "hypothesis_fixture_membership_indexes",
        sa.MetaData(),
        autoload_with=engine,
    )
    fixtures = sa.Table(
        "historical_fixture_evidence_indexes",
        sa.MetaData(),
        autoload_with=engine,
    )
    summary_row = _summary_row()
    artifact_row = _artifact_row()
    fixture_row = _fixture_row()
    membership_row = _membership_row()
    with engine.begin() as connection:
        connection.execute(summary.insert().values(**summary_row))
        connection.execute(artifacts.insert().values(**artifact_row))
        connection.execute(fixtures.insert().values(**fixture_row))
        connection.execute(memberships.insert().values(**membership_row))

    summary_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(summary.name)
    }
    assert (
        "dataset_hash",
        "rule_hash",
    ) in summary_unique_sets
    artifact_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(artifacts.name)
    }
    assert (
        "dataset_hash",
        "artifact_kind",
        "object_key",
    ) in artifact_unique_sets
    membership_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(memberships.name)
    }
    assert (
        "dataset_hash",
        "rule_hash",
        "canonical_match_id",
    ) in membership_unique_sets
    assert (
        "dataset_hash",
        "artifact_object_key",
        "artifact_row_group",
        "artifact_row_offset",
    ) in membership_unique_sets
    fixture_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(fixtures.name)
    }
    assert (
        "dataset_hash",
        "canonical_match_id",
    ) in fixture_unique_sets
    assert (
        "dataset_hash",
        "artifact_object_key",
        "artifact_row_group",
        "artifact_row_offset",
    ) in fixture_unique_sets

    summary_index_sets = {
        tuple(index["column_names"]) for index in inspector.get_indexes(summary.name)
    }
    assert {("hypothesis_id",), ("rule_hash",), ("status",)} <= summary_index_sets
    membership_index_sets = {
        tuple(index["column_names"]) for index in inspector.get_indexes(memberships.name)
    }
    assert {
        ("hypothesis_id", "kickoff_at", "canonical_match_id"),
        ("canonical_match_id", "hypothesis_id"),
    } <= membership_index_sets
    fixture_index_sets = {
        tuple(index["column_names"]) for index in inspector.get_indexes(fixtures.name)
    }
    assert {
        ("competition_key", "season", "kickoff_at"),
        ("home_team_id", "kickoff_at"),
        ("away_team_id", "kickoff_at"),
    } <= fixture_index_sets
    membership_fixture_links = {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys(memberships.name)
    }
    assert (
        ("dataset_hash", "canonical_match_id"),
        "historical_fixture_evidence_indexes",
        ("dataset_hash", "canonical_match_id"),
    ) in membership_fixture_links

    with engine.connect() as connection:
        stored_summary = (
            connection.execute(
                sa.select(
                    summary.c.hit_rate,
                    summary.c.profit_units,
                    summary.c.roi,
                )
            )
            .mappings()
            .one()
        )
        joined_evidence = (
            connection.execute(
                sa.select(
                    memberships.c.hypothesis_id,
                    fixtures.c.home_team_name,
                    fixtures.c.away_team_name,
                    fixtures.c.final_status,
                ).join(
                    fixtures,
                    sa.and_(
                        memberships.c.dataset_hash == fixtures.c.dataset_hash,
                        memberships.c.canonical_match_id == fixtures.c.canonical_match_id,
                    ),
                )
            )
            .mappings()
            .one()
        )
        stored_membership = (
            connection.execute(
                sa.select(
                    memberships.c.observed_odds,
                    memberships.c.market_margin,
                    memberships.c.profit_units,
                )
            )
            .mappings()
            .one()
        )
    sqlite_numeric_tolerance = Decimal("0.000000000000001")
    assert abs(stored_summary["hit_rate"] - summary_row["hit_rate"]) <= sqlite_numeric_tolerance
    assert stored_summary["profit_units"] == summary_row["profit_units"]
    assert abs(stored_summary["roi"] - summary_row["roi"]) <= sqlite_numeric_tolerance
    assert stored_membership["observed_odds"] == membership_row["observed_odds"]
    assert (
        abs(stored_membership["market_margin"] - membership_row["market_margin"])
        <= sqlite_numeric_tolerance
    )
    assert stored_membership["profit_units"] == membership_row["profit_units"]
    assert joined_evidence == {
        "hypothesis_id": "J10-M001",
        "home_team_name": "Équipe domicile",
        "away_team_name": "Équipe extérieure",
        "final_status": "FINISHED",
    }

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            summary.update().where(summary.c.id == summary_row["id"]).values(status="MUTATED")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(artifacts.delete().where(artifacts.c.id == artifact_row["id"]))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            memberships.update()
            .where(memberships.c.id == membership_row["id"])
            .values(outcome="LOST")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(fixtures.delete().where(fixtures.c.id == fixture_row["id"]))

    duplicate = {
        **summary_row,
        "id": str(uuid4()),
        "evidence_hash": "0" * 64,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(summary.insert().values(**duplicate))
    changed_artifact = {
        **artifact_row,
        "id": str(uuid4()),
        "payload_sha256": "7" * 64,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(artifacts.insert().values(**changed_artifact))
    duplicate_membership = {
        **membership_row,
        "id": str(uuid4()),
        "membership_hash": "6" * 64,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(memberships.insert().values(**duplicate_membership))
    duplicate_membership_pointer = {
        **membership_row,
        "id": str(uuid4()),
        "hypothesis_id": "J10-POINTER-COLLISION",
        "rule_hash": "1" * 64,
        "membership_hash": "2" * 64,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(memberships.insert().values(**duplicate_membership_pointer))
    duplicate_fixture = {
        **fixture_row,
        "id": str(uuid4()),
        "canonical_match_id": "J10-FIXTURE-000002",
        "provider_fixture_id": "football-data:000002",
        "source_row_hash": "3" * 64,
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(fixtures.insert().values(**duplicate_fixture))
    invalid_artifact = {
        **artifact_row,
        "id": str(uuid4()),
        "artifact_kind": "DETAILED_PROVIDER_PAYLOAD",
        "object_key": "hypothesis-evidence/v1/forbidden/part-00000.bin",
    }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(artifacts.insert().values(**invalid_artifact))

    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD

    command.downgrade(config, "0012_universal_genome_v2")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert TABLES <= set(sa.inspect(engine).get_table_names())
