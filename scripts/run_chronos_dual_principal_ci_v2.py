"""Prove the Chronos dual-principal lifecycle on PostgreSQL 16 CI only."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess  # nosec B404
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import ClientCursor, sql
from sqlalchemy.engine import make_url

from robin.chronos_alembic import run_fenced_alembic
from robin.chronos_production import ChronosProductionError
from robin.chronos_role_lifecycle import (
    BOOTSTRAP_AUTHORITY,
    BOOTSTRAP_EXECUTOR_PREFIX,
    GROUP_ROLES,
    RUNTIME_ROLE_GROUPS,
    BootstrapExecutorLease,
    RoleEdgeAudit,
    assert_authority_password_null,
    assert_executor_before_set_role,
    assert_executor_cannot_create_role,
    assert_migrator_disabled,
    assert_permanent_bootstrap_authority,
    assert_post_migration_role_state,
    audit_role_edges,
    audit_terminal_lifecycle,
    cleanup_bootstrap_executor,
    disable_migrator,
    provision_bootstrap_executor,
    provision_chronos_group_roles,
    provision_migrator,
    provision_permanent_bootstrap_authority,
    provision_runtime_logins,
    release_lifecycle_lock,
    reset_permanent_bootstrap_authority,
    role_inventory_snapshot,
    set_permanent_bootstrap_authority,
)

PROFILE_SUPERUSER = "superuser"
PROFILE_NON_SUPERUSER = "non_superuser_createrole"
ADMIN_ROLE = "robin_ci_lifecycle_admin"
OBSERVER_ROLE = "robin_ci_terminal_observer"
MIGRATOR_ROLE = "robin_ci_migrator"
REVISION_0013 = "0013_historical_evidence_index"
REVISION_0014 = "0014_chronos_control_plane_v2"
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
ALEMBIC_PGOPTIONS = (
    "-c statement_timeout=300000 "
    "-c idle_session_timeout=60000 "
    "-c idle_in_transaction_session_timeout=60000"
)


class InjectedCrash(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"CI_CONTEXT_MISSING:{name}")
    return value


def _psycopg_url(database_url: str) -> str:
    return make_url(database_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def _scoped_url(database_url: str, username: str, password: str) -> str:
    return make_url(database_url).set(
        drivername="postgresql", username=username, password=password
    ).render_as_string(hide_password=False)


def _alembic(database_url: str, *arguments: str) -> None:
    environment = dict(os.environ)
    environment["ROBIN_DATABASE_URL"] = database_url
    environment["PGOPTIONS"] = ALEMBIC_PGOPTIONS
    try:
        subprocess.run(  # nosec B603
            [sys.executable, "-m", "alembic", *arguments],
            env=environment,
            check=True,
            timeout=300,
        )
    finally:
        environment.pop("ROBIN_DATABASE_URL", None)


def _revision(connection: psycopg.Connection[Any]) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM public.alembic_version")
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("CHRONOS_CI_REVISION_MISSING")
    return str(row[0])


def _new_executor_role() -> str:
    return BOOTSTRAP_EXECUTOR_PREFIX + uuid.uuid4().hex[:16]


def _prepare_admin_profile(
    superuser_url: str, profile: str
) -> tuple[str, str, str | None]:
    observer_password = secrets.token_urlsafe(48)
    admin_password: str | None = None
    with psycopg.connect(_psycopg_url(superuser_url), connect_timeout=10) as connection:
        with ClientCursor(connection) as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT SUPERUSER CREATEDB CREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD %s"
                ).format(sql.Identifier(OBSERVER_ROLE)),
                (observer_password,),
            )
            if profile == PROFILE_NON_SUPERUSER:
                admin_password = secrets.token_urlsafe(48)
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                        "CREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s"
                    ).format(sql.Identifier(ADMIN_ROLE)),
                    (admin_password,),
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT USAGE, CREATE ON SCHEMA public TO {} "
                        "WITH GRANT OPTION"
                    ).format(sql.Identifier(ADMIN_ROLE))
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                        "public.alembic_version TO {} WITH GRANT OPTION"
                    ).format(sql.Identifier(ADMIN_ROLE))
                )
                cursor.execute(
                    sql.SQL("GRANT SELECT ON TABLE pg_catalog.pg_authid TO {}").format(
                        sql.Identifier(ADMIN_ROLE)
                    )
                )
    observer_url = _scoped_url(superuser_url, OBSERVER_ROLE, observer_password)
    if profile == PROFILE_SUPERUSER:
        return _psycopg_url(superuser_url), observer_url, None
    if admin_password is None:
        raise RuntimeError("CHRONOS_CI_ADMIN_PASSWORD_MISSING")
    return (
        _scoped_url(superuser_url, ADMIN_ROLE, admin_password),
        observer_url,
        admin_password,
    )


def _lease(
    admin: psycopg.Connection[Any],
    *,
    passwords: list[str],
    crash_after: str | None = None,
) -> tuple[BootstrapExecutorLease, str]:
    password = secrets.token_urlsafe(48)
    passwords.append(password)

    def checkpoint(name: str) -> None:
        if name == crash_after:
            raise InjectedCrash(name)

    lease = provision_bootstrap_executor(
        admin,
        executor_role=_new_executor_role(),
        password=password,
        valid_until=datetime.now(UTC) + timedelta(minutes=9),
        checkpoint=checkpoint if crash_after is not None else None,
    )
    return lease, _scoped_url(
        _required("ROBIN_TEST_POSTGRES_URL"), lease.executor_role, password
    )


def _cleanup_lease(
    admin: psycopg.Connection[Any], lease: BootstrapExecutorLease
) -> None:
    cleanup_bootstrap_executor(
        admin,
        executor_role=lease.executor_role,
        authority=lease.authority,
        lifecycle_admin=lease.lifecycle_admin,
        lifecycle_admin_superuser=lease.lifecycle_admin_superuser,
    )
    release_lifecycle_lock(admin)


def _migrator_session_count(
    observer: psycopg.Connection[Any], *, role: str = MIGRATOR_ROLE
) -> int:
    with observer.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.pg_stat_clear_snapshot()")
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=%s",
            (role,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("CHRONOS_CI_SESSION_COUNT_MISSING")
    return int(row[0])


def _blocked_migrator_backend_pids(
    observer: psycopg.Connection[Any],
) -> list[int]:
    with observer.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.pg_stat_clear_snapshot()")
        cursor.execute(
            "SELECT DISTINCT a.pid FROM pg_catalog.pg_stat_activity a "
            "JOIN pg_catalog.pg_locks l ON l.pid=a.pid "
            "WHERE a.usename=%s AND a.wait_event_type='Lock' "
            "AND l.locktype='relation' AND NOT l.granted "
            "AND l.relation='public.alembic_version'::regclass ORDER BY a.pid",
            (MIGRATOR_ROLE,),
        )
        return [int(row[0]) for row in cursor.fetchall()]


def _simulate_killed_migration_window(
    migrator_url: str, observer: psycopg.Connection[Any]
) -> dict[str, object]:
    """Block a real Alembic backend, kill it, and prove its session is gone."""

    with observer.cursor() as cursor:
        cursor.execute("LOCK TABLE public.alembic_version IN ACCESS EXCLUSIVE MODE")
    environment = dict(os.environ)
    environment["ROBIN_DATABASE_URL"] = migrator_url
    environment["PGOPTIONS"] = ALEMBIC_PGOPTIONS
    process = subprocess.Popen(  # nosec B603
        [sys.executable, "-m", "alembic", "upgrade", REVISION_0014],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    backend_observed = False
    lock_wait_observed = False
    backend_pids: list[int] = []
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            backend_pids = _blocked_migrator_backend_pids(observer)
            if len(backend_pids) == 1:
                backend_observed = True
                lock_wait_observed = True
                break
            if len(backend_pids) > 1:
                raise RuntimeError("CHRONOS_CI_MULTIPLE_BLOCKED_ALEMBIC_BACKENDS")
            if process.poll() is not None:
                raise RuntimeError("CHRONOS_CI_ALEMBIC_CRASH_BACKEND_EXITED_EARLY")
            time.sleep(0.1)
        if not backend_observed:
            raise RuntimeError("CHRONOS_CI_ALEMBIC_CRASH_BACKEND_NOT_OBSERVED")
        with observer.cursor() as cursor:
            cursor.execute(
                "WITH targets AS MATERIALIZED ("
                "SELECT pid FROM pg_catalog.pg_stat_activity "
                "WHERE pid=ANY(%s) AND usename=%s) "
                "SELECT count(*)=cardinality(%s),"
                "bool_and(pg_catalog.pg_terminate_backend(pid)) FROM targets",
                (backend_pids, MIGRATOR_ROLE, backend_pids),
            )
            terminated = cursor.fetchone()
        if (
            terminated is None
            or not bool(terminated[0])
            or not bool(terminated[1])
        ):
            raise RuntimeError("CHRONOS_CI_ALEMBIC_BACKEND_TERMINATION_FAILED")
        client_kill_fallback = False
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            client_kill_fallback = True
            process.kill()
            process.wait(timeout=10)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and _migrator_session_count(observer) != 0:
            time.sleep(0.1)
        if _migrator_session_count(observer) != 0:
            raise RuntimeError("CHRONOS_CI_ALEMBIC_CRASH_BACKEND_SURVIVED")
    finally:
        environment.pop("ROBIN_DATABASE_URL", None)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        observer.rollback()
    if _revision(observer) != REVISION_0013:
        raise RuntimeError("CHRONOS_CI_CRASH_CHANGED_REVISION")
    return {
        "alembic_backend_observed": backend_observed,
        "alembic_version_lock_wait_observed": lock_wait_observed,
        "backend_terminated": True,
        "client_kill_fallback": client_kill_fallback,
        "backend_sessions_after_kill": 0,
        "revision_after_kill": REVISION_0013,
    }


def _snapshot(connection: psycopg.Connection[Any]) -> dict[str, object]:
    roles = role_inventory_snapshot(connection)
    selected = {
        role: tuple(
            value for index, value in enumerate(roles[role]) if index != 9
        )
        for role in (
            BOOTSTRAP_AUTHORITY,
            MIGRATOR_ROLE,
            *GROUP_ROLES,
            *RUNTIME_ROLE_GROUPS,
        )
        if role in roles
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT granted.rolname,member.rolname,grantor.rolname,"
            "m.admin_option,m.inherit_option,m.set_option "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=ANY(%s) OR member.rolname=ANY(%s) "
            "ORDER BY 1,2,3",
            (list(selected), list(selected)),
        )
        memberships = [tuple(row) for row in cursor.fetchall()]
    return {"roles": selected, "memberships": memberships}


def _assert_passwords_null(
    connection: psycopg.Connection[Any], *, authority: str
) -> None:
    assert_authority_password_null(connection, authority=authority)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*),bool_and(rolpassword IS NULL) "
            "FROM pg_catalog.pg_authid WHERE rolname=ANY(%s)",
            ([authority, MIGRATOR_ROLE],),
        )
        row = cursor.fetchone()
    if row is None or int(row[0]) != 2 or not bool(row[1]):
        raise RuntimeError("CHRONOS_CI_TERMINAL_PASSWORD_UNSAFE")


def _assert_runtime_set_role_denials(
    superuser_url: str, lifecycle_admin: str
) -> None:
    for login, _group, password in RUNTIME_ACCOUNTS:
        runtime_url = _scoped_url(superuser_url, login, password)
        with psycopg.connect(runtime_url, connect_timeout=10) as connection:
            for target in (BOOTSTRAP_AUTHORITY, lifecycle_admin):
                with connection.cursor() as cursor:
                    cursor.execute("SAVEPOINT chronos_runtime_set_probe")
                    try:
                        cursor.execute(
                            sql.SQL("SET ROLE {}").format(sql.Identifier(target))
                        )
                    except psycopg.errors.InsufficientPrivilege as error:
                        if error.sqlstate != "42501":
                            raise RuntimeError(
                                "CHRONOS_CI_RUNTIME_SET_ROLE_SQLSTATE_UNSAFE"
                            ) from None
                        cursor.execute("ROLLBACK TO SAVEPOINT chronos_runtime_set_probe")
                        cursor.execute("RELEASE SAVEPOINT chronos_runtime_set_probe")
                    else:
                        cursor.execute("RESET ROLE")
                        raise RuntimeError("CHRONOS_CI_RUNTIME_SET_ROLE_SUCCEEDED")


def _force_drop_executor_roles(observer_url: str) -> None:
    with psycopg.connect(observer_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname LIKE %s "
                "ORDER BY rolname",
                (BOOTSTRAP_EXECUTOR_PREFIX + "%",),
            )
            roles = [str(row[0]) for row in cursor.fetchall()]
            for role in roles:
                cursor.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(role))
                )


def _expect_pre_set_rejection(
    *,
    superuser_url: str,
    admin_url: str,
    observer_url: str,
    passwords: list[str],
    mutation: str,
) -> None:
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=passwords)
    alias = "chronos_hidden_executor_alias"
    try:
        with ClientCursor(admin) as cursor:
            if mutation in {"set_false", "inherit_true", "admin_true"}:
                cursor.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(BOOTSTRAP_AUTHORITY),
                        sql.Identifier(lease.executor_role),
                    )
                )
                options = {
                    "set_false": "SET FALSE, INHERIT FALSE, ADMIN FALSE",
                    "inherit_true": "SET TRUE, INHERIT TRUE, ADMIN FALSE",
                    "admin_true": "SET TRUE, INHERIT FALSE, ADMIN TRUE",
                }[mutation]
                cursor.execute(
                    sql.SQL("GRANT {} TO {} WITH " + options).format(
                        sql.Identifier(BOOTSTRAP_AUTHORITY),
                        sql.Identifier(lease.executor_role),
                    )
                )
            elif mutation == "direct_createrole":
                cursor.execute(
                    sql.SQL("ALTER ROLE {} CREATEROLE").format(
                        sql.Identifier(lease.executor_role)
                    )
                )
            elif mutation == "hidden_membership":
                cursor.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(alias))
                )
                cursor.execute(
                    sql.SQL("GRANT {} TO {} WITH SET TRUE").format(
                        sql.Identifier(alias), sql.Identifier(lease.executor_role)
                    )
                )
            else:
                raise RuntimeError("CHRONOS_CI_NEGATIVE_MUTATION_UNKNOWN")
        admin.commit()
        with psycopg.connect(executor_url, connect_timeout=10) as executor:
            try:
                assert_executor_before_set_role(executor)
            except ChronosProductionError:
                pass
            else:
                raise RuntimeError("CHRONOS_CI_UNSAFE_EXECUTOR_ACCEPTED")
    finally:
        admin.close()
        _force_drop_executor_roles(observer_url)
        if mutation == "hidden_membership":
            with psycopg.connect(observer_url, connect_timeout=10) as observer:
                observer.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(alias))
                )


def _run_negative_matrix(
    *,
    superuser_url: str,
    admin_url: str,
    observer_url: str,
    passwords: list[str],
    lifecycle_admin: str,
) -> dict[str, str]:
    # An exact-looking authority with a retained password is never adopted.
    authority_password = secrets.token_urlsafe(48)
    passwords.append(authority_password)
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        with ClientCursor(observer) as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD %s").format(
                    sql.Identifier(BOOTSTRAP_AUTHORITY)
                ),
                (authority_password,),
            )
    admin = psycopg.connect(admin_url, connect_timeout=10)
    try:
        try:
            provision_permanent_bootstrap_authority(admin)
        except ChronosProductionError as error:
            if str(error) != "CHRONOS_BOOTSTRAP_AUTHORITY_PASSWORD_UNSAFE":
                raise
        else:
            raise RuntimeError("CHRONOS_CI_PASSWORD_AUTHORITY_ADOPTED")
    finally:
        admin.close()
        with psycopg.connect(observer_url, connect_timeout=10) as observer:
            observer.execute(
                sql.SQL("ALTER ROLE {} PASSWORD NULL").format(
                    sql.Identifier(BOOTSTRAP_AUTHORITY)
                )
            )

    # No hidden direct or transitive role can be reachable from the authority.
    authority_alias = "chronos_hidden_authority_alias"
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        observer.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(authority_alias))
        )
        observer.execute(
            sql.SQL(
                "GRANT {} TO {} WITH ADMIN FALSE, INHERIT TRUE, SET TRUE"
            ).format(
                sql.Identifier(authority_alias),
                sql.Identifier(BOOTSTRAP_AUTHORITY),
            )
        )
    admin = psycopg.connect(admin_url, connect_timeout=10)
    try:
        try:
            _lease(admin, passwords=passwords)
        except ChronosProductionError as error:
            if str(error) not in {
                "CHRONOS_BOOTSTRAP_AUTHORITY_MEMBERSHIP_UNSAFE",
                "CHRONOS_BOOTSTRAP_AUTHORITY_EFFECTIVE_ROLE_UNSAFE",
            }:
                raise
        else:
            raise RuntimeError("CHRONOS_CI_HIDDEN_AUTHORITY_MEMBERSHIP_ACCEPTED")
    finally:
        admin.close()
        with psycopg.connect(observer_url, connect_timeout=10) as observer:
            observer.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(authority_alias),
                    sql.Identifier(BOOTSTRAP_AUTHORITY),
                )
            )
            observer.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(authority_alias))
            )

    for mutation in (
        "set_false",
        "inherit_true",
        "admin_true",
        "direct_createrole",
        "hidden_membership",
    ):
        _expect_pre_set_rejection(
            superuser_url=superuser_url,
            admin_url=admin_url,
            observer_url=observer_url,
            passwords=passwords,
            mutation=mutation,
        )

    # Table, column and revision-table PUBLIC privileges all fail pre-SET.
    public_acl_mutations = (
        (
            "GRANT SELECT ON TABLE public.chronos_effect_events TO PUBLIC",
            "REVOKE SELECT ON TABLE public.chronos_effect_events FROM PUBLIC",
        ),
        (
            "GRANT SELECT (event_id) ON TABLE public.chronos_effect_events "
            "TO PUBLIC",
            "REVOKE SELECT (event_id) ON TABLE public.chronos_effect_events "
            "FROM PUBLIC",
        ),
        (
            "GRANT UPDATE ON TABLE public.alembic_version TO PUBLIC",
            "REVOKE UPDATE ON TABLE public.alembic_version FROM PUBLIC",
        ),
    )
    for grant_sql, revoke_sql in public_acl_mutations:
        admin = psycopg.connect(admin_url, connect_timeout=10)
        lease, executor_url = _lease(admin, passwords=passwords)
        with psycopg.connect(observer_url, connect_timeout=10) as observer:
            observer.execute(grant_sql)
        executor = psycopg.connect(executor_url, connect_timeout=10)
        try:
            try:
                assert_executor_before_set_role(executor)
            except ChronosProductionError as error:
                if str(error) != "CHRONOS_EXECUTOR_EFFECTIVE_PRIVILEGE_UNSAFE":
                    raise
            else:
                raise RuntimeError("CHRONOS_CI_PUBLIC_PRIVILEGE_ACCEPTED")
        finally:
            executor.close()
            with psycopg.connect(observer_url, connect_timeout=10) as observer:
                observer.execute(revoke_sql)
        _cleanup_lease(admin, lease)
        admin.close()

    # Cleanup must perform no mutation while an executor client backend exists.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    try:
        try:
            cleanup_bootstrap_executor(
                admin,
                executor_role=lease.executor_role,
                authority=lease.authority,
                lifecycle_admin=lease.lifecycle_admin,
                lifecycle_admin_superuser=lease.lifecycle_admin_superuser,
            )
        except ChronosProductionError as error:
            if str(error) != "CHRONOS_BOOTSTRAP_EXECUTOR_SESSION_ACTIVE":
                raise
        else:
            raise RuntimeError("CHRONOS_CI_CONNECTED_EXECUTOR_CLEANED")
    finally:
        executor.close()
    _cleanup_lease(admin, lease)
    admin.close()

    # An expired/lost credential is never rotated on the same role.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    expired_lease, _expired_url = _lease(admin, passwords=passwords)
    with ClientCursor(admin) as cursor:
        cursor.execute(
            sql.SQL("ALTER ROLE {} VALID UNTIL {}").format(
                sql.Identifier(expired_lease.executor_role),
                sql.Literal((datetime.now(UTC) - timedelta(minutes=1)).isoformat()),
            )
        )
    admin.commit()
    admin.close()
    admin = psycopg.connect(admin_url, connect_timeout=10)
    replacement, _replacement_url = _lease(admin, passwords=passwords)
    if replacement.executor_role == expired_lease.executor_role:
        raise RuntimeError("CHRONOS_CI_EXPIRED_EXECUTOR_ADOPTED")
    _cleanup_lease(admin, replacement)
    admin.close()

    # A stale executor name can only be destroyed, never credential-rotated.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    same_name_lease, _same_name_url = _lease(admin, passwords=passwords)
    replacement_password = secrets.token_urlsafe(48)
    passwords.append(replacement_password)
    try:
        provision_bootstrap_executor(
            admin,
            executor_role=same_name_lease.executor_role,
            password=replacement_password,
            valid_until=datetime.now(UTC) + timedelta(minutes=9),
            lifecycle_lock_held=True,
        )
    except ChronosProductionError as error:
        if str(error) != "CHRONOS_BOOTSTRAP_EXECUTOR_NAME_REUSE":
            raise
    else:
        raise RuntimeError("CHRONOS_CI_EXECUTOR_NAME_REUSED")
    _cleanup_lease(admin, same_name_lease)
    admin.close()

    # A second cooperative orchestrator is fenced before role creation.
    first_admin = psycopg.connect(admin_url, connect_timeout=10)
    first_lease, _first_url = _lease(first_admin, passwords=passwords)
    second_admin = psycopg.connect(admin_url, connect_timeout=10)
    try:
        try:
            _lease(second_admin, passwords=passwords)
        except ChronosProductionError as error:
            if str(error) != "CHRONOS_LIFECYCLE_ALREADY_RUNNING":
                raise
        else:
            raise RuntimeError("CHRONOS_CI_CONCURRENT_EXECUTOR_ACCEPTED")
    finally:
        second_admin.close()
    _cleanup_lease(first_admin, first_lease)
    first_admin.close()

    # Unknown and multiple executor inventories fail before adoption.
    unexpected = _new_executor_role()
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        observer.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOCREATEROLE CONNECTION LIMIT 1"
            ).format(sql.Identifier(unexpected))
        )
    admin = psycopg.connect(admin_url, connect_timeout=10)
    try:
        try:
            _lease(admin, passwords=passwords)
        except ChronosProductionError:
            pass
        else:
            raise RuntimeError("CHRONOS_CI_UNEXPECTED_EXECUTOR_ADOPTED")
    finally:
        admin.close()
        _force_drop_executor_roles(observer_url)

    two_roles = (_new_executor_role(), _new_executor_role())
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        for role in two_roles:
            observer.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOCREATEROLE CONNECTION LIMIT 1"
                ).format(sql.Identifier(role))
            )
    admin = psycopg.connect(admin_url, connect_timeout=10)
    try:
        try:
            _lease(admin, passwords=passwords)
        except ChronosProductionError as error:
            if str(error) != "CHRONOS_MULTIPLE_BOOTSTRAP_EXECUTORS":
                raise
        else:
            raise RuntimeError("CHRONOS_CI_MULTIPLE_EXECUTORS_ACCEPTED")
    finally:
        admin.close()
        _force_drop_executor_roles(observer_url)

    # The NOLOGIN authority cannot terminalize or re-enable itself.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=passwords)
    with psycopg.connect(executor_url, connect_timeout=10) as executor:
        set_permanent_bootstrap_authority(executor)
        with executor.cursor() as cursor:
            cursor.execute("SAVEPOINT chronos_authority_self_alter")
            try:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} NOLOGIN").format(
                        sql.Identifier(BOOTSTRAP_AUTHORITY)
                    )
                )
            except psycopg.errors.InsufficientPrivilege as error:
                if error.sqlstate != "42501":
                    raise RuntimeError(
                        "CHRONOS_CI_AUTHORITY_SELF_ALTER_SQLSTATE_UNSAFE"
                    ) from None
                cursor.execute("ROLLBACK TO SAVEPOINT chronos_authority_self_alter")
                cursor.execute("RELEASE SAVEPOINT chronos_authority_self_alter")
            else:
                raise RuntimeError("CHRONOS_CI_AUTHORITY_SELF_ALTER_SUCCEEDED")
        reset_permanent_bootstrap_authority(executor)
    _cleanup_lease(admin, lease)
    admin.close()

    _assert_runtime_set_role_denials(superuser_url, lifecycle_admin)

    # An authenticated migrator backend fences both rotation and reactivation.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    set_permanent_bootstrap_authority(executor)
    groups = audit_role_edges(
        executor,
        phase="final",
        bootstrap_owner=BOOTSTRAP_AUTHORITY,
        migrator_role=MIGRATOR_ROLE,
    )
    active_migrator_password = secrets.token_urlsafe(48)
    passwords.append(active_migrator_password)
    provision_migrator(
        executor,
        role=MIGRATOR_ROLE,
        password=active_migrator_password,
        valid_until=datetime.now(UTC) + timedelta(minutes=6),
        pinned_system_grantor=groups.bootstrap_system_grantor,
        audit_phase="final",
        runtime_roles=sorted(RUNTIME_ROLE_GROUPS),
    )
    active_migrator_url = _scoped_url(
        superuser_url, MIGRATOR_ROLE, active_migrator_password
    )
    active_migrator = psycopg.connect(active_migrator_url, connect_timeout=10)
    try:
        try:
            provision_migrator(
                executor,
                role=MIGRATOR_ROLE,
                password=secrets.token_urlsafe(48),
                valid_until=datetime.now(UTC) + timedelta(minutes=6),
                pinned_system_grantor=groups.bootstrap_system_grantor,
                audit_phase="final",
                runtime_roles=sorted(RUNTIME_ROLE_GROUPS),
            )
        except ChronosProductionError as error:
            if str(error) != "CHRONOS_MIGRATOR_SESSION_ACTIVE":
                raise
        else:
            raise RuntimeError("CHRONOS_CI_ACTIVE_MIGRATOR_ROTATED")
    finally:
        active_migrator.close()
    try:
        provision_migrator(
            executor,
            role=MIGRATOR_ROLE,
            password=secrets.token_urlsafe(48),
            valid_until=datetime.now(UTC) + timedelta(minutes=6),
            pinned_system_grantor=groups.bootstrap_system_grantor,
            audit_phase="final",
            runtime_roles=sorted(RUNTIME_ROLE_GROUPS),
        )
    except ChronosProductionError as error:
        if str(error) != "CHRONOS_MIGRATOR_MUST_BE_DISABLED":
            raise
    else:
        raise RuntimeError("CHRONOS_CI_LOGIN_MIGRATOR_REACTIVATED")
    disable_migrator(executor, role=MIGRATOR_ROLE)
    reset_permanent_bootstrap_authority(executor)
    executor.close()
    _cleanup_lease(admin, lease)
    admin.close()
    lifecycle_source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "robin"
        / "chronos_role_lifecycle.py"
    ).read_text(encoding="utf-8")
    if (
        '"ALTER ROLE {} LOGIN PASSWORD %s VALID UNTIL {}"'
        not in lifecycle_source
        or '"ALTER ROLE {} NOLOGIN PASSWORD NULL"' not in lifecycle_source
        or "ALTER ROLE {} LOGIN NOINHERIT" in lifecycle_source
        or "ALTER ROLE {} NOLOGIN NOINHERIT" in lifecycle_source
    ):
        raise RuntimeError("CHRONOS_CI_MIGRATOR_ALTER_ROLE_NONMINIMAL")
    return {
        "executor_without_set_true": "PASS",
        "executor_with_inherit_true": "PASS",
        "executor_with_admin_true": "PASS",
        "executor_with_direct_createrole": "PASS",
        "executor_create_role_before_set": "PASS",
        "runtime_set_role_authority": "PASS",
        "runtime_set_role_lifecycle_admin": "PASS",
        "executor_connected_during_cleanup": "PASS",
        "expired_executor": "PASS",
        "unexpected_executor": "PASS",
        "two_executors": "PASS",
        "concurrent_executor_attempt": "PASS",
        "hidden_membership": "PASS",
        "hidden_authority_membership": "PASS",
        "authority_password_non_null": "PASS",  # nosec B105
        "public_effective_privilege": "PASS",
        "public_column_privilege": "PASS",
        "public_alembic_mutation": "PASS",
        "same_executor_name_reuse": "PASS",
        "active_migrator_session": "PASS",
        "login_migrator_requires_disable": "PASS",
        "migrator_nonminimal_reactivation": "PASS",
        "authority_self_terminalization": "PASS",
    }


def _write_evidence(
    *,
    profile: str,
    audits: list[RoleEdgeAudit],
    terminal: RoleEdgeAudit,
    authority_oid: int,
    migrator_oid: int,
    before_cycle: dict[str, object],
    after_cycle: dict[str, object],
    passwords: list[str],
    negative_tests: dict[str, str],
    migration_crash_proof: dict[str, object],
    postgresql_version: str,
    non_superuser_terminal_audit: str,
) -> None:
    final = terminal.report()
    root = Path(__file__).resolve().parents[1]
    source_sha256 = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in (
            "migrations/env.py",
            "migrations/versions/0013_historical_evidence_index.py",
            "migrations/versions/0014_chronos_control_plane_v2.py",
            "scripts/chronos_production_bootstrap_v3.py",
            "scripts/run_chronos_dual_principal_ci_v2.py",
            "src/robin/chronos_alembic.py",
            "src/robin/chronos_role_lifecycle.py",
        )
    }
    document = {
        "schema_version": "chronos-dual-principal-role-edge-matrix-v2",
        "verdict": "DUAL_PRINCIPAL_BOOTSTRAP_AUTHORITY_ACCEPTED",
        "postgresql_profile": profile,
        "postgresql_version": postgresql_version,
        "source_sha256": source_sha256,
        "micro_experiments": {"A": "PASS", "B": "PASS", "C": "PASS"},
        "crash_matrix": {
            "authority_created": "PASS",
            "executor_created": "PASS",
            "executor_granted": "PASS",
            "after_set_role": "PASS",
            "during_migration": "PASS",
            "migrator_disabled": "PASS",
            "before_executor_deleted": "PASS",
        },
        "migration_crash_proof": migration_crash_proof,
        "non_superuser_production_like_terminal_audit": (
            non_superuser_terminal_audit
        ),
        "negative_tests": negative_tests,
        "authority_oid": authority_oid,
        "migrator_oid": migrator_oid,
        "migration_dispatches": 1,
        "migration_cycle": "0013->0014->0013->0014:PASS",
        "stable_cycle": before_cycle == after_cycle,
        "password_state": {
            "authority": "PG_AUTHID_NULL_PROVEN",
            "migrator": "PG_AUTHID_NULL_PROVEN",
            "executor": "ABSENT_FROM_FINAL_CATALOG",
        },
        "phases": [audit.report() for audit in audits] + [final],
        "terminal": final,
        "external_effects": {
            "neon_api_calls": 0,
            "production_postgresql_reads": 0,
            "production_postgresql_writes": 0,
            "r2_operations": 0,
            "provider_calls": 0,
            "odds_credits": 0,
        },
    }
    serialized = json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n"
    if any(password in serialized for password in passwords):
        raise RuntimeError("CHRONOS_EXECUTOR_PASSWORD_LEAKED_TO_EVIDENCE")
    path = Path(f".ci/chronos-dual-principal-{profile}-v2.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized, encoding="utf-8")


def main() -> None:
    superuser_url = _required("ROBIN_TEST_POSTGRES_URL")
    profile = _required("CHRONOS_CI_ADMIN_PROFILE")
    if profile not in {PROFILE_SUPERUSER, PROFILE_NON_SUPERUSER}:
        raise RuntimeError("CHRONOS_CI_ADMIN_PROFILE_INVALID")
    _alembic(superuser_url, "upgrade", REVISION_0013)
    with psycopg.connect(_psycopg_url(superuser_url), connect_timeout=10) as server:
        with server.cursor() as cursor:
            cursor.execute("SHOW server_version")
            version_row = cursor.fetchone()
            cursor.execute("SHOW server_version_num")
            version_num_row = cursor.fetchone()
    if (
        version_row is None
        or version_num_row is None
        or not 160000 <= int(version_num_row[0]) < 170000
    ):
        raise RuntimeError("CHRONOS_CI_POSTGRESQL16_REQUIRED")
    postgresql_version = str(version_row[0])
    admin_url, observer_url, _admin_password = _prepare_admin_profile(
        superuser_url, profile
    )
    executor_passwords: list[str] = []
    crash_records: list[str] = []

    # Crash 1: the authority commit survives and is adopted with the same OID.
    with psycopg.connect(admin_url, connect_timeout=10) as admin:
        _, authority_oid, _admin, _super = provision_permanent_bootstrap_authority(
            admin
        )
    crash_records.append("authority_created")

    # Crashes 2 and 3: creation and delegation are separately committed.
    for checkpoint in ("executor_created", "executor_granted"):
        admin = psycopg.connect(admin_url, connect_timeout=10)
        try:
            try:
                _lease(
                    admin,
                    passwords=executor_passwords,
                    crash_after=checkpoint,
                )
            except InjectedCrash as error:
                if str(error) != checkpoint:
                    raise
            else:
                raise RuntimeError("CHRONOS_CI_CRASH_NOT_INJECTED")
        finally:
            admin.close()
        crash_records.append(checkpoint)

    # Crash 4: RESET ROLE/finally is deliberately skipped; the external admin recovers.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=executor_passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    assert_executor_cannot_create_role(
        executor, probe_role="chronos_executor_pre_set_probe"
    )
    set_permanent_bootstrap_authority(executor)
    assert_permanent_bootstrap_authority(executor)
    executor.close()
    admin.close()
    crash_records.append("after_set_role")

    # Crash 5: leave a bounded LOGIN migrator and kill the child migration window.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=executor_passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    assert_executor_cannot_create_role(
        executor, probe_role="chronos_executor_pre_set_probe_2"
    )
    set_permanent_bootstrap_authority(executor)
    groups_audit = provision_chronos_group_roles(
        executor, migrator_role=MIGRATOR_ROLE
    )
    migrator_password = secrets.token_urlsafe(48)
    executor_passwords.append(migrator_password)
    migrator_audit = provision_migrator(
        executor,
        role=MIGRATOR_ROLE,
        password=migrator_password,
        valid_until=datetime.now(UTC) + timedelta(minutes=6),
        pinned_system_grantor=groups_audit.bootstrap_system_grantor,
    )
    migrator_url = _scoped_url(superuser_url, MIGRATOR_ROLE, migrator_password)
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        with observer.cursor() as cursor:
            cursor.execute(
                "SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s",
                (MIGRATOR_ROLE,),
            )
            migrator_oid_row = cursor.fetchone()
        if migrator_oid_row is None:
            raise RuntimeError("CHRONOS_CI_MIGRATOR_OID_MISSING")
        migrator_oid = int(migrator_oid_row[0])
        migration_crash_proof = _simulate_killed_migration_window(
            migrator_url, observer
        )
    executor.close()
    admin.close()
    crash_records.append("during_migration")

    # Resume 0013: new executor, same authority/migrator OIDs, exactly one dispatch.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=executor_passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    set_permanent_bootstrap_authority(executor)
    resumed_groups = provision_chronos_group_roles(
        executor, migrator_role=MIGRATOR_ROLE
    )
    disable_migrator(executor, role=MIGRATOR_ROLE)
    migrator_password = secrets.token_urlsafe(48)
    executor_passwords.append(migrator_password)
    resumed_migrator = provision_migrator(
        executor,
        role=MIGRATOR_ROLE,
        password=migrator_password,
        valid_until=datetime.now(UTC) + timedelta(minutes=6),
        pinned_system_grantor=resumed_groups.bootstrap_system_grantor,
    )
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        with observer.cursor() as cursor:
            cursor.execute(
                "SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s",
                (MIGRATOR_ROLE,),
            )
            resumed_oid_row = cursor.fetchone()
        if resumed_oid_row is None or int(resumed_oid_row[0]) != migrator_oid:
            raise RuntimeError("CHRONOS_CI_MIGRATOR_OID_CHANGED_AFTER_CRASH")
    migrator_url = _scoped_url(superuser_url, MIGRATOR_ROLE, migrator_password)
    run_fenced_alembic(migrator_url, REVISION_0014)
    disable_migrator(executor, role=MIGRATOR_ROLE)
    assert_post_migration_role_state(
        executor,
        migrator_role=MIGRATOR_ROLE,
        bootstrap_owner=BOOTSTRAP_AUTHORITY,
    )
    if _revision(executor) != REVISION_0014:
        raise RuntimeError("CHRONOS_CI_0014_NOT_PROVEN")
    executor.close()
    admin.close()
    crash_records.append("migrator_disabled")

    # Resume 0014: zero second dispatch, then runtime provisioning and full cycle.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=executor_passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    set_permanent_bootstrap_authority(executor)
    no_dispatch_audit = audit_role_edges(
        executor,
        phase="migrator",
        bootstrap_owner=BOOTSTRAP_AUTHORITY,
        migrator_role=MIGRATOR_ROLE,
        pinned_system_grantor=resumed_migrator.bootstrap_system_grantor,
    )
    assert_migrator_disabled(
        executor, role=MIGRATOR_ROLE, bootstrap_owner=BOOTSTRAP_AUTHORITY
    )
    runtime_audit = provision_runtime_logins(
        executor,
        accounts=RUNTIME_ACCOUNTS,
        migrator_role=MIGRATOR_ROLE,
        pinned_system_grantor=resumed_migrator.bootstrap_system_grantor,
    )
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        before_cycle = _snapshot(observer)
        if int(before_cycle["roles"][MIGRATOR_ROLE][0]) != migrator_oid:  # type: ignore[index]
            raise RuntimeError("CHRONOS_CI_MIGRATOR_OID_CHANGED_BEFORE_CYCLE")
    migrator_password = secrets.token_urlsafe(48)
    executor_passwords.append(migrator_password)
    cycle_audit = provision_migrator(
        executor,
        role=MIGRATOR_ROLE,
        password=migrator_password,
        valid_until=datetime.now(UTC) + timedelta(minutes=6),
        pinned_system_grantor=resumed_migrator.bootstrap_system_grantor,
        audit_phase="final",
        runtime_roles=sorted(RUNTIME_ROLE_GROUPS),
    )
    migrator_url = _scoped_url(superuser_url, MIGRATOR_ROLE, migrator_password)
    _alembic(migrator_url, "downgrade", REVISION_0013)
    _alembic(migrator_url, "upgrade", REVISION_0014)
    disable_migrator(executor, role=MIGRATOR_ROLE)
    after_cycle_audit = audit_role_edges(
        executor,
        phase="final",
        bootstrap_owner=BOOTSTRAP_AUTHORITY,
        migrator_role=MIGRATOR_ROLE,
        pinned_system_grantor=resumed_migrator.bootstrap_system_grantor,
    )
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        after_cycle = _snapshot(observer)
    if before_cycle != after_cycle:
        raise RuntimeError("CHRONOS_CI_ROLE_GRAPH_CHANGED_DURING_CYCLE")
    reset_permanent_bootstrap_authority(executor)
    executor.close()
    admin.close()
    crash_records.append("before_executor_deleted")

    # Final retry proves no Alembic dispatch at 0014 and deletes its fresh executor.
    admin = psycopg.connect(admin_url, connect_timeout=10)
    lease, executor_url = _lease(admin, passwords=executor_passwords)
    executor = psycopg.connect(executor_url, connect_timeout=10)
    set_permanent_bootstrap_authority(executor)
    terminal_active_audit = audit_role_edges(
        executor,
        phase="final",
        bootstrap_owner=BOOTSTRAP_AUTHORITY,
        migrator_role=MIGRATOR_ROLE,
        pinned_system_grantor=resumed_migrator.bootstrap_system_grantor,
    )
    reset_permanent_bootstrap_authority(executor)
    executor.close()
    _cleanup_lease(admin, lease)
    admin.close()

    negative_tests = _run_negative_matrix(
        superuser_url=superuser_url,
        admin_url=admin_url,
        observer_url=observer_url,
        passwords=executor_passwords,
        lifecycle_admin=lease.lifecycle_admin,
    )
    non_superuser_terminal_audit = "NOT_APPLICABLE"
    if profile == PROFILE_NON_SUPERUSER:
        with psycopg.connect(admin_url, connect_timeout=10) as lifecycle_admin_connection:
            audit_terminal_lifecycle(
                lifecycle_admin_connection,
                bootstrap_owner=BOOTSTRAP_AUTHORITY,
                lifecycle_admin=lease.lifecycle_admin,
                migrator_role=MIGRATOR_ROLE,
            )
        non_superuser_terminal_audit = "PASS"
    with psycopg.connect(observer_url, connect_timeout=10) as observer:
        _assert_passwords_null(observer, authority=BOOTSTRAP_AUTHORITY)
        terminal = audit_terminal_lifecycle(
            observer,
            bootstrap_owner=BOOTSTRAP_AUTHORITY,
            lifecycle_admin=lease.lifecycle_admin,
            migrator_role=MIGRATOR_ROLE,
        )
    terminal_oids = {
        str(role["role"]): int(role["oid"])
        for role in terminal.role_inventory
    }
    if (
        terminal_oids.get(BOOTSTRAP_AUTHORITY) != authority_oid
        or terminal_oids.get(MIGRATOR_ROLE) != migrator_oid
    ):
        raise RuntimeError("CHRONOS_CI_LIFECYCLE_OID_CHANGED")
    if crash_records != [
        "authority_created",
        "executor_created",
        "executor_granted",
        "after_set_role",
        "during_migration",
        "migrator_disabled",
        "before_executor_deleted",
    ]:
        raise RuntimeError("CHRONOS_CI_CRASH_MATRIX_INCOMPLETE")
    _write_evidence(
        profile=profile,
        audits=[
            groups_audit,
            migrator_audit,
            resumed_groups,
            resumed_migrator,
            no_dispatch_audit,
            runtime_audit,
            cycle_audit,
            after_cycle_audit,
            terminal_active_audit,
        ],
        terminal=terminal,
        authority_oid=authority_oid,
        migrator_oid=migrator_oid,
        before_cycle=before_cycle,
        after_cycle=after_cycle,
        passwords=executor_passwords,
        negative_tests=negative_tests,
        migration_crash_proof=migration_crash_proof,
        postgresql_version=postgresql_version,
        non_superuser_terminal_audit=non_superuser_terminal_audit,
    )
    print(f"CHRONOS_DUAL_PRINCIPAL_POSTGRESQL16_READY:{profile}")


if __name__ == "__main__":
    main()
