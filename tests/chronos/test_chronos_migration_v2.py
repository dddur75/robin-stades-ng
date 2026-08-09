from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

REVISION = "0014_chronos_control_plane_v2"
DOWN_REVISION = "0013_historical_evidence_index"
TABLES = {"chronos_effect_authorities", "chronos_effect_events"}


def config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    value = Config(str(root / "alembic.ini"))
    value.set_main_option("script_location", str(root / "migrations"))
    value.set_main_option("sqlalchemy.url", url)
    return value


def upgrade(tmp_path: Path, name: str = "chronos.db") -> tuple[sa.Engine, Config]:
    url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    value = config(url)
    command.upgrade(value, "head")
    return sa.create_engine(url), value


def authority_row() -> dict[str, object]:
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    return {
        "authority_id": "chronos-authority:" + "a" * 64,
        "mission_id": "chronos-e1",
        "github_run_id": 123,
        "github_run_attempt": 1,
        "github_sha": "1" * 40,
        "github_workflow_ref": "org/repo/.github/workflows/x.yml@refs/heads/main",
        "github_workflow_sha": "2" * 40,
        "github_repository": "org/repo",
        "github_ref": "refs/heads/main",
        "code_revision": "1" * 40,
        "planned_at": now,
        "expires_at": now + timedelta(minutes=1),
        "db_issued_at": now,
        "postgres_server_epoch": now - timedelta(hours=1),
        "control_plane_generation_hash": "b" * 64,
        "authority_hash": "c" * 64,
        "max_r2_put_requests": 1,
    }


def event_row(
    authority: dict[str, object],
    *,
    sequence: int,
    event_type: str,
    event_hash: str,
    previous_hash: str | None,
) -> dict[str, object]:
    return {
        "event_id": "chronos-event:" + event_hash,
        "event_seq": sequence,
        "operation_id": "d" * 64,
        "authority_id": authority["authority_id"],
        "event_type": event_type,
        "resource_kind": "R2_OBJECT",
        "resource_key": "chronos/e1/payload.json",
        "payload_hash": "e" * 64,
        "db_recorded_at": authority["planned_at"],
        "recorded_server_epoch": authority["postgres_server_epoch"],
        "github_run_id": authority["github_run_id"],
        "github_run_attempt": authority["github_run_attempt"],
        "code_revision": authority["code_revision"],
        "previous_event_hash": previous_hash,
        "event_hash": event_hash,
    }


def test_revision_is_the_single_head_and_is_neon_compatible() -> None:
    scripts = ScriptDirectory.from_config(config("sqlite+pysqlite:///:memory:"))
    assert scripts.get_heads() == [REVISION]
    script = scripts.get_revision(REVISION)
    assert script is not None
    assert script.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32


def test_sqlite_upgrade_guards_fsm_and_downgrade_is_fail_closed(
    tmp_path: Path,
) -> None:
    engine, value = upgrade(tmp_path)
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    authorities = sa.Table(
        "chronos_effect_authorities", sa.MetaData(), autoload_with=engine
    )
    events = sa.Table("chronos_effect_events", sa.MetaData(), autoload_with=engine)
    authority = authority_row()
    granted = event_row(
        authority,
        sequence=0,
        event_type="AUTHORITY_GRANTED",
        event_hash="f" * 64,
        previous_hash=None,
    )
    reserved = event_row(
        authority,
        sequence=1,
        event_type="EFFECT_RESERVED",
        event_hash="0" * 64,
        previous_hash="f" * 64,
    )
    with engine.begin() as connection:
        connection.execute(authorities.insert().values(**authority))
        connection.execute(events.insert().values(**granted))
        connection.execute(events.insert().values(**reserved))

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            events.insert().values(
                **event_row(
                    authority,
                    sequence=2,
                    event_type="CREATED_CONFIRMED",
                    event_hash="9" * 64,
                    previous_hash="0" * 64,
                )
            )
        )
    dispatched = event_row(
        authority,
        sequence=2,
        event_type="PUT_DISPATCHED",
        event_hash="1" * 64,
        previous_hash="0" * 64,
    )
    with engine.begin() as connection:
        connection.execute(events.insert().values(**dispatched))
    for forbidden, event_hash in (
        ("PREEXISTING_CONFIRMED", "2" * 64),
        ("INTEGRITY_CONFLICT", "3" * 64),
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                events.insert().values(
                    **event_row(
                        authority,
                        sequence=3,
                        event_type=forbidden,
                        event_hash=event_hash,
                        previous_hash="1" * 64,
                    )
                )
            )
    get_permit = event_row(
        authority,
        sequence=3,
        event_type="R2_GET_DISPATCHED",
        event_hash="4" * 64,
        previous_hash="1" * 64,
    )
    preexisting = event_row(
        authority,
        sequence=4,
        event_type="PREEXISTING_CONFIRMED",
        event_hash="5" * 64,
        previous_hash="4" * 64,
    )
    with engine.begin() as connection:
        connection.execute(events.insert().values(**get_permit))
        connection.execute(events.insert().values(**preexisting))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            events.update().where(events.c.event_id == granted["event_id"]).values(
                event_type="FAILED_AFTER_DISPATCH"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(authorities.delete())
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_CONTROL_PLANE_DOWNGRADE_REFUSED_NONEMPTY",
    ):
        command.downgrade(value, DOWN_REVISION)
    assert TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == REVISION


def test_empty_downgrade_then_upgrade_round_trip(tmp_path: Path) -> None:
    engine, value = upgrade(tmp_path, "empty.db")
    command.downgrade(value, DOWN_REVISION)
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(value, "head")
    assert TABLES <= set(sa.inspect(engine).get_table_names())


def test_upgrade_refuses_preexisting_control_plane_table(tmp_path: Path) -> None:
    url = f"sqlite+pysqlite:///{(tmp_path / 'collision.db').as_posix()}"
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE chronos_effect_authorities(id int)"))
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_CONTROL_PLANE_UPGRADE_SCHEMA_DRIFT",
    ):
        command.upgrade(config(url), "head")
    assert "chronos_effect_authorities" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_postgresql_contract_is_server_clocked_role_separated_and_scoped() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "migrations" / "versions" / f"{REVISION}.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        "clock_timestamp()",
        "pg_postmaster_start_time()",
        "SECURITY DEFINER",
        "SET search_path = pg_catalog",
        "chronos_reader",
        "chronos_test_writer",
        "chronos_runtime_writer",
        "chronos_authority_executor",
        "managed-by:0014_chronos_control_plane_v2",
        "CHRONOS_ROLE_PROVENANCE_UNSAFE",
        "CHRONOS_ROLE_ACL_UNSAFE",
        "m.admin_option",
        "NOT m.inherit_option",
        "NOT m.set_option",
        "'USAGE'",
        "pg_catalog.shobj_description",
        "REVOKE ALL PRIVILEGES ON TABLE",
        "CHRONOS_OBJECT_ACL_UNSAFE",
        "p_generation_nonce bytea",
        "p_generation_nonce IS NULL",
        "octet_length(p_generation_nonce) <> 32",
        "IS DISTINCT FROM",
        "R2_GET_DISPATCHED",
        "CHRONOS_R2_GET_PERMIT_ALREADY_EXISTS",
        "LOCK TABLE public.chronos_effect_authorities",
        "CHRONOS_CONTROL_PLANE_UPGRADE_SCHEMA_DRIFT",
        "REVOKE EXECUTE ON FUNCTION",
        "FROM PUBLIC",
        "CHRONOS_CONTROL_PLANE_DOWNGRADE_REFUSED_NONEMPTY",
    ):
        assert marker in source
    assert source.count("RETURN QUERY SELECT a.authority_id::text") == 2
    assert "DROP ROLE" not in source
    assert "DROP EXTENSION" not in source
    assert "pg_catalog.sh_description" not in source
    assert "REVOKE EXECUTE ON ALL FUNCTIONS" not in source
    assert "p_generation_hash" not in source
    assert "p_now" not in source
    assert "test_now" not in source
    assert "fake_now" not in source


def test_ci_finishes_downgrade_cycle_before_stateful_scoped_login_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    migrator_downgrade = (
        "ROBIN_DATABASE_URL='postgresql+psycopg://robin_ci_migrator:chronos_ci@"
        "localhost:5432/robin_ci' python -m alembic downgrade "
        "0013_historical_evidence_index"
    )
    cleanup_cycle = (
        migrator_downgrade
        + "\n          python -m alembic downgrade 0002_jalon2_shadow"
        + "\n          python -m alembic downgrade base"
    )
    scoped_contract = (
        "tests/chronos/test_chronos_postgresql_v2.py::"
        "test_scoped_login_connections_enforce_allows_and_denials"
    )

    assert workflow.count(migrator_downgrade) == 1
    assert cleanup_cycle in workflow
    assert workflow.count("python -m alembic upgrade head") == 2
    assert scoped_contract in workflow
    assert "python -m alembic downgrade" not in workflow.split(scoped_contract, 1)[1]
