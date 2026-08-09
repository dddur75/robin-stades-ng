from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureFamily,
    CaptureReceipt,
    receipt_scope_sha256,
)
from robin.prospective_observatory.r2 import StoredCapture
from robin.storage.chronos_models import CHRONOS_TABLE_NAMES
from robin.storage.database import build_engine
from scripts.run_prospective_observatory import SQLAlchemyOperationalState

ROOT = Path(__file__).resolve().parents[2]
HEAD = "0015_chronos_fail_closed"
NOW = datetime(2026, 8, 9, 8, tzinfo=UTC)


def _config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _stable_id(scope: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:j12:{scope}:{value}"))


def _receipt() -> CaptureReceipt:
    payload_hash = "a" * 64
    scope = receipt_scope_sha256(window_id=None, window_label="REGISTRY")
    kickoff = NOW + timedelta(hours=2)
    return CaptureReceipt(
        window_id=None,
        window_label="REGISTRY",
        fixture_id="fixture-chronos-migration",
        competition="Ligue 1",
        season="2026",
        provider="api-football",
        family=CaptureFamily.FIXTURE,
        requested_at=NOW,
        response_received_at=NOW,
        observed_at=NOW,
        kickoff_at=kickoff,
        cutoff_at=kickoff - timedelta(microseconds=1),
        seconds_before_kickoff=7200,
        http_status=200,
        payload_sha256=payload_hash,
        payload_bytes=100,
        stored_bytes=80,
        r2_key=f"prospective-deep-data/schema-v1/payload-{payload_hash}.json.gz",
        receipt_r2_key=(
            "prospective-deep-data/schema-v1/"
            f"receipt-{scope}-{payload_hash}.json"
        ),
        source_endpoint="/fixtures",
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=1,
        code_revision="chronos-migration-test",
        materialized_at=NOW,
    )


def _receipt_row(receipt: CaptureReceipt, table: sa.Table) -> dict[str, object]:
    values = receipt.model_dump()
    values.update(
        {
            "id": _stable_id("receipt", receipt.receipt_hash),
            "receipt_hash": receipt.receipt_hash,
            "window_record_id": None,
            "append_only": True,
        }
    )
    return {key: value for key, value in values.items() if key in table.c}


def test_chronos_is_single_migration_head() -> None:
    scripts = ScriptDirectory.from_config(_config("sqlite+pysqlite:///:memory:"))
    assert scripts.get_current_head() == HEAD
    assert len(HEAD) <= 32


def test_migration_creates_append_only_tables_and_round_trips(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'chronos.db').as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert set(CHRONOS_TABLE_NAMES) <= set(sa.inspect(engine).get_table_names())
    canaries = sa.Table("chronos_canary_runs", sa.MetaData(), autoload_with=engine)
    row = {
        "id": str(uuid.uuid4()),
        "canary_id": "canary-test",
        "plan_hash": "a" * 64,
        "policy_hash": "b" * 64,
        "planned_at": NOW,
        "expires_at": NOW + timedelta(days=7),
        "activation_mode": "CANARY_ONLY",
        "max_fixtures": 5,
        "max_api_football_calls": 50,
        "max_odds_credits": 20,
        "max_r2_object_writes": 2000,
        "max_postgresql_rows": 10000,
        "max_technical_attempts": 2,
        "new_purchase_allowed": False,
        "r2_deletes_allowed": 0,
        "destructive_sql_allowed": 0,
        "code_revision": "test-revision",
        "append_only": True,
    }
    with engine.begin() as connection:
        connection.execute(canaries.insert().values(**row))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            canaries.update()
            .where(canaries.c.id == row["id"])
            .values(max_fixtures=4)
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(canaries.delete().where(canaries.c.id == row["id"]))
    known_at_checks = {
        str(check["name"]): str(check["sqltext"])
        for check in sa.inspect(engine).get_check_constraints(
            "known_at_fact_metadata"
        )
    }
    temporal_check = known_at_checks["ck_chronos_known_at_fact_temporal"]
    assert "requested_at IS NULL" in temporal_check
    assert "response_received_at IS NULL" in temporal_check
    edges = sa.Table(
        "chronos_lineage_edges", sa.MetaData(), autoload_with=engine
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            edges.insert().values(
                id=str(uuid.uuid4()),
                edge_hash="c" * 64,
                upstream_type="RAW_OBJECT",
                upstream_id="raw-missing",
                upstream_hash="a" * 64,
                downstream_type="KNOWN_AT_FACT",
                downstream_id="fact-missing",
                downstream_hash="b" * 64,
                relationship="DERIVED_FROM",
                contract_hash="d" * 64,
                created_at=NOW,
                code_revision="test-revision",
                append_only=True,
            )
        )
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_0015_REPLAY_REQUIRED:chronos_canary_runs",
    ):
        command.downgrade(config, "0014_robin_chronos_v1")

    roundtrip_url = (
        f"sqlite+pysqlite:///{(tmp_path / 'chronos-roundtrip.db').as_posix()}"
    )
    roundtrip_config = _config(roundtrip_url)
    command.upgrade(roundtrip_config, "head")
    roundtrip_engine = build_engine(roundtrip_url)
    command.downgrade(roundtrip_config, "0014_robin_chronos_v1")
    inspector = sa.inspect(roundtrip_engine)
    names_at_0014 = set(inspector.get_table_names())
    assert not {
        "chronos_canary_cohort_fixtures",
        "chronos_canary_usage_events",
        "chronos_canary_run_windows",
        "market_snapshot_metadata",
        "chronos_lineage_nodes",
    } & names_at_0014
    assert "price_contract_hash" not in {
        column["name"] for column in inspector.get_columns("capture_intents")
    }
    assert "supersedes_fact_id" not in {
        column["name"]
        for column in inspector.get_columns("known_at_fact_metadata")
    }
    command.upgrade(roundtrip_config, "head")
    assert set(CHRONOS_TABLE_NAMES) <= set(
        sa.inspect(roundtrip_engine).get_table_names()
    )
    command.downgrade(roundtrip_config, "0013_historical_evidence_index")
    assert not set(CHRONOS_TABLE_NAMES) & set(
        sa.inspect(roundtrip_engine).get_table_names()
    )
    command.upgrade(roundtrip_config, "head")


def test_migration_backfills_missing_payload_index_without_mutation(
    tmp_path: Path,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'backfill.db').as_posix()}"
    config = _config(url)
    command.upgrade(config, "0013_historical_evidence_index")
    engine = build_engine(url)
    receipts = sa.Table("capture_receipts", sa.MetaData(), autoload_with=engine)
    receipt = _receipt()
    with engine.begin() as connection:
        connection.execute(receipts.insert().values(**_receipt_row(receipt, receipts)))
    command.upgrade(config, "head")
    indexes = sa.Table(
        "prospective_payload_index",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.connect() as connection:
        row = connection.execute(sa.select(indexes)).mappings().one()
    assert row["receipt_id"] == _stable_id("receipt", receipt.receipt_hash)
    assert row["id"] == _stable_id("payload-index", receipt.receipt_hash)
    assert row["payload_sha256"] == receipt.payload_sha256


def test_runtime_repairs_receipt_without_index_before_any_provider(
    tmp_path: Path,
) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'runtime-repair.db').as_posix()}"
    command.upgrade(_config(url), "head")
    engine = build_engine(url)
    receipts = sa.Table("capture_receipts", sa.MetaData(), autoload_with=engine)
    receipt = _receipt()
    with engine.begin() as connection:
        connection.execute(receipts.insert().values(**_receipt_row(receipt, receipts)))
    state = SQLAlchemyOperationalState(engine)
    inserted = state.persist_capture(
        StoredCapture(
            receipt=receipt,
            payload={},
            payload_created=False,
            receipt_created=False,
        )
    )
    assert inserted is False
    indexes = state.tables["prospective_payload_index"]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(indexes)) == 1
    restarted = SQLAlchemyOperationalState(engine)
    assert receipt.receipt_hash in restarted.payload_index_rows
