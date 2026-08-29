from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

REVISION = "0015_data_torrent_opportunity"
DOWN_REVISION = "0014_chronos_control_plane_v2"
TABLES = {
    "chronos_opportunity_claims",
    "chronos_torrent_external_effect_permits",
    "chronos_torrent_external_effect_events",
    "chronos_torrent_batches",
}


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    value = Config(str(root / "alembic.ini"))
    value.set_main_option("script_location", str(root / "migrations"))
    value.set_main_option("sqlalchemy.url", url)
    return value


def _upgrade(tmp_path: Path, name: str) -> tuple[sa.Engine, Config]:
    url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    value = _config(url)
    command.upgrade(value, REVISION)
    return sa.create_engine(url), value


def _authority() -> dict[str, object]:
    now = datetime(2026, 8, 29, 12, tzinfo=UTC)
    return {
        "authority_id": "chronos-authority:" + "a" * 64,
        "mission_id": "data-torrent-ready-v1",
        "github_run_id": 123,
        "github_run_attempt": 1,
        "github_sha": "1" * 40,
        "github_workflow_ref": "dddur75/robin-stades-ng/.github/workflows/x.yml@refs/heads/main",
        "github_workflow_sha": "1" * 40,
        "github_repository": "dddur75/robin-stades-ng",
        "github_ref": "refs/heads/main",
        "code_revision": "1" * 40,
        "planned_at": now,
        "expires_at": now + timedelta(minutes=20),
        "db_issued_at": now,
        "postgres_server_epoch": now - timedelta(hours=1),
        "control_plane_generation_hash": "b" * 64,
        "authority_hash": "c" * 64,
        "max_r2_put_requests": 1,
    }


def _claim(authority: dict[str, object]) -> dict[str, object]:
    return {
        "opportunity_id": "d" * 64,
        "opportunity_kind": "FOOTBALL_OFFICIAL_AND_ODDS_BREADTH",
        "canonical_key": "stable-key",
        "mission_id": authority["mission_id"],
        "authority_id": authority["authority_id"],
        "github_run_id": authority["github_run_id"],
        "github_run_attempt": authority["github_run_attempt"],
        "github_sha": authority["github_sha"],
        "github_workflow_ref": authority["github_workflow_ref"],
        "github_workflow_sha": authority["github_workflow_sha"],
        "github_repository": authority["github_repository"],
        "github_ref": authority["github_ref"],
        "code_revision": authority["code_revision"],
        "db_claimed_at": authority["planned_at"],
        "postgres_server_epoch": authority["postgres_server_epoch"],
        "claim_hash": "e" * 64,
    }


def test_revision_is_single_head_and_additive() -> None:
    scripts = ScriptDirectory.from_config(_config("sqlite+pysqlite:///:memory:"))
    assert scripts.get_heads() == [REVISION]
    script = scripts.get_revision(REVISION)
    assert script is not None
    assert script.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_sqlite_upgrade_append_only_and_nonempty_downgrade_refusal(tmp_path: Path) -> None:
    engine, value = _upgrade(tmp_path, "nonempty.db")
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    authority_table = sa.Table("chronos_effect_authorities", sa.MetaData(), autoload_with=engine)
    claim_table = sa.Table("chronos_opportunity_claims", sa.MetaData(), autoload_with=engine)
    authority = _authority()
    claim = _claim(authority)
    with engine.begin() as connection:
        connection.execute(authority_table.insert().values(**authority))
        connection.execute(claim_table.insert().values(**claim))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            claim_table.update()
            .where(claim_table.c.opportunity_id == claim["opportunity_id"])
            .values(canonical_key="changed")
        )
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_TORRENT_DOWNGRADE_REFUSED_NONEMPTY",
    ):
        command.downgrade(value, DOWN_REVISION)
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_empty_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    engine, value = _upgrade(tmp_path, "empty.db")
    command.downgrade(value, DOWN_REVISION)
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(value, REVISION)
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_upgrade_refuses_any_precreated_owned_table(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'collision.db').as_posix()}"
    value = _config(url)
    command.upgrade(value, DOWN_REVISION)
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE chronos_torrent_batches(id integer)"))
    with pytest.raises(RuntimeError, match="CHRONOS_TORRENT_UPGRADE_SCHEMA_DRIFT"):
        command.upgrade(value, REVISION)
    engine.dispose()


def test_postgresql_source_contains_cross_run_lock_rbac_and_fail_closed_bounds() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "migrations" / "versions" / f"{REVISION}.py").read_text(encoding="utf-8")
    for marker in (
        "FOR UPDATE",
        "ON CONFLICT ON CONSTRAINT chronos_opportunity_claims_pkey",
        "CHRONOS_OPPORTUNITY_WINNER_REQUIRED",
        "CHRONOS_EXTERNAL_EFFECT_BUDGET_EXCEEDED",
        "CHRONOS_EXTERNAL_EFFECTS_UNACCOUNTED",
        "CHRONOS_TORRENT_DURABILITY_NOT_PROVEN",
        "p_odds_provider_requests <> 5",
        "pg_catalog.jsonb_array_length(p_coverage_matrix) <> 10",
        "REVOKE ALL ON public.chronos_opportunity_claims",
        "TO chronos_reader",
        "TO chronos_runtime_writer",
        "SET search_path = pg_catalog",
    ):
        assert marker in source
