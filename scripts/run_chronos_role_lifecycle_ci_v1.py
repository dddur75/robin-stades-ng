"""Run the PostgreSQL 16 Chronos role lifecycle contract in CI only."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import sqlalchemy as sa
from psycopg import ClientCursor, sql
from sqlalchemy.engine import make_url

from robin.chronos_production import ChronosProductionError
from robin.chronos_role_lifecycle import (
    GROUP_ROLES,
    MIGRATOR_MARKER,
    ROLE_MARKER,
    RoleEdgeAudit,
    assert_bootstrap_owner,
    assert_post_migration_role_state,
    assert_role_inventory_delta,
    audit_role_edges,
    audit_terminal_lifecycle,
    disable_migrator,
    provision_chronos_group_roles,
    provision_migrator,
    provision_runtime_logins,
    role_inventory_snapshot,
    terminalize_bootstrap_owner,
)
from robin.storage.database import build_engine

BOOTSTRAP_OWNER = "robin_ci_bootstrap_owner"
# Ephemeral, local-only PostgreSQL CI fixtures.
BOOTSTRAP_PASSWORD = "chronos_bootstrap_ci"  # nosec B105
MIGRATOR_ROLE = "robin_ci_migrator"
MIGRATOR_PASSWORD = "chronos_migrator_ci"  # nosec B105
RUNTIME_ACCOUNTS = (
    (
        "chronos_authority_runtime_login",
        "chronos_authority_executor",
        "chronos_authority_ci",
    ),
    (
        "chronos_effect_runtime_login",
        "chronos_runtime_writer",
        "chronos_runtime_ci",
    ),
    ("chronos_reader_login", "chronos_reader", "chronos_reader_ci"),
)
REVISION_0013 = "0013_historical_evidence_index"
REVISION_0014 = "0014_chronos_control_plane_v2"
ALEMBIC_PGOPTIONS = (
    "-c statement_timeout=300000 "
    "-c idle_session_timeout=60000 "
    "-c idle_in_transaction_session_timeout=60000"
)


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"CI_CONTEXT_MISSING:{name}")
    return value


def _scoped_url(database_url: str, username: str, password: str) -> str:
    return make_url(database_url).set(username=username, password=password).render_as_string(
        hide_password=False
    )


def _psycopg_url(database_url: str) -> str:
    value = make_url(database_url).set(drivername="postgresql")
    return value.render_as_string(hide_password=False)


def _alembic(database_url: str, *arguments: str) -> None:
    environment = dict(os.environ)
    environment["ROBIN_DATABASE_URL"] = database_url
    environment["PGOPTIONS"] = ALEMBIC_PGOPTIONS
    subprocess.run(  # nosec B603
        [sys.executable, "-m", "alembic", *arguments],
        env=environment,
        check=True,
        timeout=300,
    )


def _bootstrap_owner(superuser_url: str) -> None:
    valid_until = datetime.now(UTC) + timedelta(minutes=10)
    with psycopg.connect(
        _psycopg_url(superuser_url), connect_timeout=10
    ) as connection:
        with ClientCursor(connection) as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "CREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s "
                    "VALID UNTIL {}"
                ).format(
                    sql.Identifier(BOOTSTRAP_OWNER),
                    sql.Literal(valid_until.isoformat()),
                ),
                (BOOTSTRAP_PASSWORD,),
            )
            cursor.execute(
                sql.SQL(
                    "GRANT USAGE, CREATE ON SCHEMA public TO {} WITH GRANT OPTION"
                ).format(sql.Identifier(BOOTSTRAP_OWNER))
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                    "public.alembic_version TO {} WITH GRANT OPTION"
                ).format(sql.Identifier(BOOTSTRAP_OWNER))
            )


def _snapshot(superuser_url: str) -> dict[str, list[list[Any]]]:
    engine = build_engine(superuser_url)
    try:
        with engine.connect() as connection:
            roles = connection.execute(
                sa.text(
                    "SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
                    "rolcreaterole,rolreplication,rolbypassrls,rolconfig "
                    "FROM pg_catalog.pg_roles WHERE rolname=ANY(:roles) "
                    "ORDER BY rolname"
                ),
                {
                    "roles": [
                        *[item[0] for item in RUNTIME_ACCOUNTS],
                        *[item[1] for item in RUNTIME_ACCOUNTS],
                        "chronos_test_writer",
                        MIGRATOR_ROLE,
                    ]
                },
            ).all()
            marker_inventory = connection.execute(
                sa.text(
                    "SELECT oid,rolname,rolcanlogin,rolcreaterole,"
                    "pg_catalog.shobj_description(oid,'pg_authid') "
                    "FROM pg_catalog.pg_roles WHERE rolname=:owner OR "
                    "pg_catalog.shobj_description(oid,'pg_authid')=ANY(:markers) "
                    "ORDER BY rolname"
                ),
                {
                    "owner": BOOTSTRAP_OWNER,
                    "markers": [ROLE_MARKER, MIGRATOR_MARKER],
                },
            ).all()
            memberships = connection.execute(
                sa.text(
                    "SELECT granted.rolname,member.rolname,grantor.rolname,"
                    "m.admin_option,m.inherit_option,m.set_option "
                    "FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
                    "WHERE granted.rolname=ANY(:roles) OR member.rolname=ANY(:roles) "
                    "ORDER BY granted.rolname,member.rolname,grantor.rolname"
                ),
                {
                    "roles": [
                        *[item[0] for item in RUNTIME_ACCOUNTS],
                        *[item[1] for item in RUNTIME_ACCOUNTS],
                        "chronos_test_writer",
                        MIGRATOR_ROLE,
                        BOOTSTRAP_OWNER,
                    ]
                },
            ).all()
    finally:
        engine.dispose()
    return {
        "roles": [list(row) for row in roles],
        "marker_inventory": [list(row) for row in marker_inventory],
        "memberships": [list(row) for row in memberships],
    }


def _assert_migrator_denials(migrator_url: str) -> None:
    environment = dict(os.environ)
    environment.update(
        {
            "ROBIN_TEST_CHRONOS_MIGRATOR_URL": migrator_url,
            "ROBIN_TEST_CHRONOS_MIGRATOR_ROLE": MIGRATOR_ROLE,
        }
    )
    environment["PGOPTIONS"] = (
        "-c statement_timeout=1000 "
        "-c idle_session_timeout=60000 "
        "-c idle_in_transaction_session_timeout=60000"
    )
    subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/chronos/test_chronos_postgresql_v2.py::"
            "test_nocreaterole_migrator_cannot_mutate_role_lifecycle",
        ],
        env=environment,
        check=True,
        timeout=120,
    )


def _write_matrix(
    path: Path,
    audits: list[RoleEdgeAudit],
    *,
    before_cycle: dict[str, list[list[Any]]],
    after_cycle: dict[str, list[list[Any]]],
) -> None:
    final = audits[-1].report()
    document = {
        "schema_version": "chronos-role-edge-matrix-v1",
        "verdict": "BIDIRECTIONAL_ROLE_EDGE_AUDIT_READY",
        "migration_cycle": "PASS",
        "same_role_oids": before_cycle["roles"] == after_cycle["roles"],
        "same_membership_graph": (
            before_cycle["memberships"] == after_cycle["memberships"]
        ),
        "password_state": {
            "bootstrap_owner": "PG_AUTHID_NULL_PROVEN",
            "migrator": "PG_AUTHID_NULL_PROVEN",
        },
        "phases": [audit.report() for audit in audits],
        "edges": final["edges"],
        "forbidden_edge_count": final["forbidden_edge_count"],
        "runtime_effective_bootstrap_edge_count": final[
            "runtime_effective_bootstrap_edge_count"
        ],
        "migrator_runtime_edge_count": final["migrator_runtime_edge_count"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _assert_alias_rejected(
    owner_psycopg: str,
    *,
    baseline: dict[str, tuple[Any, ...]],
) -> None:
    alias = "rds_ci_lifecycle_alias"
    with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN INHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(alias))
            )
        try:
            assert_role_inventory_delta(
                connection,
                baseline=baseline,
                expected_new_roles=[
                    *GROUP_ROLES,
                    MIGRATOR_ROLE,
                    *[item[0] for item in RUNTIME_ACCOUNTS],
                ],
            )
        except ChronosProductionError:
            connection.rollback()
        else:
            raise RuntimeError("CHRONOS_LIFECYCLE_ALIAS_NOT_REJECTED")


def _assert_smuggled_acl_rejected(
    owner_psycopg: str, *, pinned_system_grantor: str
) -> None:
    with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "GRANT SELECT ON TABLE public.alembic_version "
                "TO chronos_authority_runtime_login"
            )
            cursor.execute(
                "GRANT SELECT(authority_id) ON TABLE "
                "public.chronos_effect_authorities "
                "TO chronos_authority_runtime_login"
            )
            cursor.execute(
                "CREATE TYPE public.evil_runtime_acl_type AS ENUM ('injected')"
            )
            cursor.execute(
                "GRANT USAGE ON TYPE public.evil_runtime_acl_type "
                "TO chronos_authority_runtime_login"
            )
        try:
            provision_runtime_logins(
                connection,
                accounts=RUNTIME_ACCOUNTS,
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=pinned_system_grantor,
            )
        except ChronosProductionError:
            connection.rollback()
        else:
            raise RuntimeError("CHRONOS_RUNTIME_SMUGGLED_ACL_NOT_REJECTED")

    with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "GRANT UPDATE ON TABLE public.alembic_version TO {} "
                    "WITH GRANT OPTION"
                ).format(sql.Identifier(MIGRATOR_ROLE))
            )
        try:
            provision_migrator(
                connection,
                role=MIGRATOR_ROLE,
                password=MIGRATOR_PASSWORD,
                valid_until=datetime.now(UTC) + timedelta(minutes=6),
                pinned_system_grantor=pinned_system_grantor,
                audit_phase="final",
            )
        except ChronosProductionError:
            connection.rollback()
        else:
            raise RuntimeError("CHRONOS_MIGRATOR_SMUGGLED_ACL_NOT_REJECTED")


def _assert_owned_object_smuggling_rejected(
    owner_psycopg: str,
    migrator_url: str,
    superuser_url: str,
    *,
    pinned_system_grantor: str,
) -> None:
    with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
        provision_migrator(
            connection,
            role=MIGRATOR_ROLE,
            password=MIGRATOR_PASSWORD,
            valid_until=datetime.now(UTC) + timedelta(minutes=6),
            pinned_system_grantor=pinned_system_grantor,
            audit_phase="final",
        )
    hidden_homonym_rejected = False
    with psycopg.connect(_psycopg_url(superuser_url), connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA evil_chronos_shadow")
            cursor.execute(
                "CREATE FUNCTION evil_chronos_shadow.chronos_get_effect_state(text) "
                "RETURNS text LANGUAGE sql SECURITY DEFINER AS 'SELECT $1'"
            )
            cursor.execute(
                sql.SQL(
                    "ALTER FUNCTION evil_chronos_shadow."
                    "chronos_get_effect_state(text) OWNER TO {}"
                ).format(sql.Identifier(MIGRATOR_ROLE))
            )
    try:
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            try:
                assert_post_migration_role_state(
                    connection,
                    migrator_role=MIGRATOR_ROLE,
                    bootstrap_owner=BOOTSTRAP_OWNER,
                )
            except ChronosProductionError:
                hidden_homonym_rejected = True
    finally:
        with psycopg.connect(
            _psycopg_url(superuser_url), connect_timeout=10
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA evil_chronos_shadow CASCADE")
    if not hidden_homonym_rejected:
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            disable_migrator(connection, role=MIGRATOR_ROLE)
        raise RuntimeError("CHRONOS_HIDDEN_FUNCTION_HOMONYM_NOT_REJECTED")
    rejected = False
    try:
        with psycopg.connect(_psycopg_url(migrator_url), connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE FUNCTION public.chronos_get_effect_state(integer) "
                    "RETURNS integer LANGUAGE sql SECURITY DEFINER AS "
                    "'SELECT $1'"
                )
                cursor.execute("CREATE TABLE public.evil_chronos_helper(id integer)")
                cursor.execute(
                    "CREATE TYPE public.evil_chronos_type AS ENUM ('injected')"
                )
                cursor.execute(
                    "GRANT SELECT(authority_id) ON TABLE "
                    "public.chronos_effect_authorities TO PUBLIC"
                )
                cursor.execute(
                    "GRANT USAGE ON TYPE public.evil_chronos_type TO PUBLIC"
                )
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            try:
                assert_post_migration_role_state(
                    connection,
                    migrator_role=MIGRATOR_ROLE,
                    bootstrap_owner=BOOTSTRAP_OWNER,
                )
            except ChronosProductionError:
                rejected = True
    finally:
        with psycopg.connect(_psycopg_url(migrator_url), connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "REVOKE SELECT(authority_id) ON TABLE "
                    "public.chronos_effect_authorities FROM PUBLIC"
                )
                cursor.execute("DROP TABLE public.evil_chronos_helper")
                cursor.execute("DROP TYPE public.evil_chronos_type")
                cursor.execute(
                    "DROP FUNCTION public.chronos_get_effect_state(integer)"
                )
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            disable_migrator(connection, role=MIGRATOR_ROLE)
    if not rejected:
        raise RuntimeError("CHRONOS_OWNED_OBJECT_SMUGGLING_NOT_REJECTED")


def _assert_unbounded_owner_window_rejected(owner_psycopg: str) -> None:
    with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} VALID UNTIL 'infinity'").format(
                    sql.Identifier(BOOTSTRAP_OWNER)
                )
            )
        try:
            assert_bootstrap_owner(connection)
        except ChronosProductionError:
            connection.rollback()
        else:
            raise RuntimeError("CHRONOS_UNBOUNDED_OWNER_WINDOW_NOT_REJECTED")


def _assert_expected_owner_transfer_rejected(
    superuser_url: str, owner_psycopg: str
) -> None:
    alias = "rds_ci_unexpected_object_owner"
    with psycopg.connect(_psycopg_url(superuser_url), connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(alias)))
            cursor.execute(
                sql.SQL("ALTER VIEW public.chronos_effect_accounting OWNER TO {}").format(
                    sql.Identifier(alias)
                )
            )
    rejected = False
    try:
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            try:
                assert_post_migration_role_state(
                    connection,
                    migrator_role=MIGRATOR_ROLE,
                    bootstrap_owner=BOOTSTRAP_OWNER,
                )
            except ChronosProductionError:
                rejected = True
    finally:
        with psycopg.connect(
            _psycopg_url(superuser_url), connect_timeout=10
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "ALTER VIEW public.chronos_effect_accounting OWNER TO {}"
                    ).format(sql.Identifier(MIGRATOR_ROLE))
                )
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(alias)))
    if not rejected:
        raise RuntimeError("CHRONOS_EXPECTED_OWNER_TRANSFER_NOT_REJECTED")


def _assert_ci_passwords_null(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*),bool_and(rolpassword IS NULL) "
            "FROM pg_catalog.pg_authid WHERE rolname=ANY(%s)",
            ([BOOTSTRAP_OWNER, MIGRATOR_ROLE],),
        )
        row = cursor.fetchone()
    if row is None or int(row[0]) != 2 or not bool(row[1]):
        raise RuntimeError("CHRONOS_CI_LIFECYCLE_PASSWORD_NOT_NULL")


def main() -> None:
    superuser_url = _required("ROBIN_TEST_POSTGRES_URL")
    owner_created = False
    migrator_created = False
    terminalized = False
    owner_url = _scoped_url(superuser_url, BOOTSTRAP_OWNER, BOOTSTRAP_PASSWORD)
    migrator_url = _scoped_url(superuser_url, MIGRATOR_ROLE, MIGRATOR_PASSWORD)
    owner_psycopg = _psycopg_url(owner_url)
    try:
        _alembic(superuser_url, "upgrade", REVISION_0013)
        _bootstrap_owner(superuser_url)
        owner_created = True
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            role_baseline = role_inventory_snapshot(connection)
            group_audit = provision_chronos_group_roles(
                connection, migrator_role=MIGRATOR_ROLE
            )
            assert_role_inventory_delta(
                connection,
                baseline=role_baseline,
                expected_new_roles=GROUP_ROLES,
            )
            migrator_audit = provision_migrator(
                connection,
                role=MIGRATOR_ROLE,
                password=MIGRATOR_PASSWORD,
                valid_until=datetime.now(UTC) + timedelta(minutes=6),
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
            )
            migrator_created = True
            assert_role_inventory_delta(
                connection,
                baseline=role_baseline,
                expected_new_roles=[*GROUP_ROLES, MIGRATOR_ROLE],
            )
        _assert_migrator_denials(migrator_url)
        _alembic(migrator_url, "upgrade", REVISION_0014)
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            disable_migrator(connection, role=MIGRATOR_ROLE)
            assert_post_migration_role_state(
                connection,
                migrator_role=MIGRATOR_ROLE,
                bootstrap_owner=BOOTSTRAP_OWNER,
            )
            zero_runtime_audit = audit_role_edges(
                connection,
                phase="migrator",
                bootstrap_owner=BOOTSTRAP_OWNER,
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
            )
            one_runtime_audit = provision_runtime_logins(
                connection,
                accounts=RUNTIME_ACCOUNTS[:1],
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
                complete=False,
            )
            two_runtime_audit = provision_runtime_logins(
                connection,
                accounts=RUNTIME_ACCOUNTS[1:2],
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
                complete=False,
            )
            final_audit = provision_runtime_logins(
                connection,
                accounts=RUNTIME_ACCOUNTS,
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
            )
            assert_role_inventory_delta(
                connection,
                baseline=role_baseline,
                expected_new_roles=[
                    *GROUP_ROLES,
                    MIGRATOR_ROLE,
                    *[item[0] for item in RUNTIME_ACCOUNTS],
                ],
            )
        first_snapshot = _snapshot(superuser_url)

        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            provision_migrator(
                connection,
                role=MIGRATOR_ROLE,
                password=MIGRATOR_PASSWORD,
                valid_until=datetime.now(UTC) + timedelta(minutes=6),
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
                audit_phase="final",
            )
        _alembic(migrator_url, "downgrade", REVISION_0013)
        _alembic(migrator_url, "upgrade", REVISION_0014)
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            disable_migrator(connection, role=MIGRATOR_ROLE)
            assert_post_migration_role_state(
                connection,
                migrator_role=MIGRATOR_ROLE,
                bootstrap_owner=BOOTSTRAP_OWNER,
            )
            after_cycle_audit = audit_role_edges(
                connection,
                phase="final",
                bootstrap_owner=BOOTSTRAP_OWNER,
                migrator_role=MIGRATOR_ROLE,
                pinned_system_grantor=group_audit.bootstrap_system_grantor,
            )
        second_snapshot = _snapshot(superuser_url)
        if second_snapshot != first_snapshot:
            raise RuntimeError("CHRONOS_ROLE_GRAPH_CHANGED_DURING_MIGRATION_CYCLE")
        _assert_alias_rejected(
            owner_psycopg,
            baseline=role_baseline,
        )
        _assert_smuggled_acl_rejected(
            owner_psycopg,
            pinned_system_grantor=group_audit.bootstrap_system_grantor,
        )
        _assert_owned_object_smuggling_rejected(
            owner_psycopg,
            migrator_url,
            superuser_url,
            pinned_system_grantor=group_audit.bootstrap_system_grantor,
        )
        _assert_unbounded_owner_window_rejected(owner_psycopg)
        _assert_expected_owner_transfer_rejected(superuser_url, owner_psycopg)
        with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
            terminalize_bootstrap_owner(connection)
        terminalized = True
        with psycopg.connect(_psycopg_url(superuser_url), connect_timeout=10) as connection:
            _assert_ci_passwords_null(connection)
            terminal_audit = audit_terminal_lifecycle(
                connection,
                bootstrap_owner=BOOTSTRAP_OWNER,
                migrator_role=MIGRATOR_ROLE,
            )
        _write_matrix(
            Path(".ci/chronos-role-edge-matrix-v1.json"),
            [
                group_audit,
                migrator_audit,
                zero_runtime_audit,
                one_runtime_audit,
                two_runtime_audit,
                final_audit,
                after_cycle_audit,
                terminal_audit,
            ],
            before_cycle=first_snapshot,
            after_cycle=second_snapshot,
        )
    finally:
        cleanup_errors: list[Exception] = []
        if owner_created and migrator_created and not terminalized:
            try:
                with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
                    disable_migrator(connection, role=MIGRATOR_ROLE)
            except Exception as error:
                cleanup_errors.append(error)
        if owner_created and not terminalized:
            try:
                with psycopg.connect(owner_psycopg, connect_timeout=10) as connection:
                    terminalize_bootstrap_owner(connection)
            except Exception as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise RuntimeError("CHRONOS_CI_LIFECYCLE_CLEANUP_FAILED") from cleanup_errors[0]
    print("CHRONOS_ROLE_LIFECYCLE_POSTGRESQL16_READY")


if __name__ == "__main__":
    main()
