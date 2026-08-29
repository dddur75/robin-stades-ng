from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from robin.chronos_role_lifecycle import (
    _grant_bootstrap_authority_schema,
    _is_expected_neon_platform_edge,
)

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "src" / "robin" / "chronos_role_lifecycle.py"
RUNNER = ROOT / "scripts" / "run_chronos_dual_principal_ci_v2.py"
PRODUCTION = ROOT / "scripts" / "chronos_production_bootstrap_v3.py"
MIGRATIONS = (
    ROOT / "migrations" / "versions" / "0014_chronos_control_plane_v2.py",
    ROOT / "migrations" / "versions" / "0015_data_torrent_opportunity.py",
)
WORKFLOW = ROOT / ".github" / "workflows" / "chronos-bootstrap-ci-v3.yml"


def test_authority_is_permanent_nologin_and_executor_is_bounded() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    assert "CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB" in source
    assert "CREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL" in source
    assert "CONNECTION LIMIT 1" in source
    assert "NOCREATEROLE NOREPLICATION NOBYPASSRLS" in source
    assert "SET TRUE, INHERIT FALSE, ADMIN FALSE" in source
    assert "timedelta(minutes=10)" in source


def test_no_self_terminalization_path_exists() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (LIFECYCLE, RUNNER, PRODUCTION)
    )
    assert "terminalize_bootstrap_owner" not in combined
    assert "assert_bootstrap_owner" not in combined
    assert "alter role current_user" not in combined.lower()
    assert "ALTER ROLE CURRENT_USER" not in combined


def test_migrator_alter_role_statements_are_minimal() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    assert '"ALTER ROLE {} LOGIN PASSWORD %s VALID UNTIL {}"' in source
    assert '"ALTER ROLE {} NOLOGIN PASSWORD NULL"' in source
    assert "ALTER ROLE {} LOGIN NOINHERIT" not in source
    assert "ALTER ROLE {} NOLOGIN NOINHERIT" not in source


def test_acl_default_object_type_is_explicitly_text_in_both_audits() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    assert source.count("defaclobjtype::text") == 2


def test_authority_grants_pin_the_postcondition_grantors() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    assert "pg_catalog.pg_has_role(" in source
    assert "n.nspowner,'SET'" in source
    assert 'sql.SQL("SET LOCAL ROLE {}")' in source
    assert 'cursor.execute("RESET ROLE")' in source
    assert "GRANTED BY" not in source


def test_failed_schema_grant_is_not_masked_by_reset_role() -> None:
    class FailingGrantCursor:
        def __init__(self) -> None:
            self.statements: list[object] = []

        def execute(self, statement: object) -> None:
            self.statements.append(statement)
            if len(self.statements) == 2:
                raise RuntimeError("primary schema grant failure")

    cursor = FailingGrantCursor()
    with pytest.raises(RuntimeError, match="primary schema grant failure"):
        _grant_bootstrap_authority_schema(
            cursor,
            authority="chronos_bootstrap_authority",
            lifecycle_admin="lifecycle_admin",
            schema_owner_name="database_owner",
            can_set_schema_owner=True,
        )
    assert len(cursor.statements) == 2


def test_migrations_0014_and_0015_contain_objects_and_acls_only() -> None:
    for migration in MIGRATIONS:
        source = migration.read_text(encoding="utf-8")
        for forbidden in ("CREATE ROLE", "ALTER ROLE", "DROP ROLE"):
            assert forbidden not in source
        assert "pg_auth_members" not in source
        assert "GRANT role membership" not in source
        assert "REVOKE role membership" not in source


def test_executor_password_is_memory_only_and_evidence_is_scanned() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "secrets.token_urlsafe(48)" in source
    assert "CHRONOS_EXECUTOR_PASSWORD_LEAKED_TO_EVIDENCE" in source
    assert "if any(password in serialized for password in passwords)" in source
    assert "passwords" not in source[
        source.index("document = {") : source.index("serialized =")
    ]


def test_ci_covers_both_lifecycle_admin_profiles() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "admin-profile:" in source
    assert "- superuser" in source
    assert "- non_superuser_createrole" in source
    assert "run_chronos_dual_principal_ci_v2.py" in source


def test_neon_platform_edge_is_exact_optional_and_recursively_closed() -> None:
    base: dict[str, object] = {
        "granted_role": "neon_superuser",
        "member_role": "lifecycle_admin",
        "grantor_superuser": True,
        "granted_authenticatable": False,
        "member_authenticatable": True,
        "admin_option": False,
        "inherit_option": True,
        "set_option": True,
        "runtime_set": True,
        "runtime_usage": True,
        "member_inherit": True,
    }
    for superuser in (False, True):
        for inherit in (False, True):
            profile = {
                **base,
                "inherit_option": inherit,
                "runtime_usage": superuser or inherit,
                "member_inherit": inherit,
            }
            assert _is_expected_neon_platform_edge(
                profile,
                lifecycle_admin="lifecycle_admin",
                lifecycle_admin_superuser=superuser,
                lifecycle_admin_inherit=inherit,
            )
    for mutation in (
        {"granted_role": "hostile_platform_role"},
        {"grantor_superuser": False},
        {"granted_authenticatable": True},
        {"member_authenticatable": False},
        {"admin_option": True},
        {"set_option": False},
        {"inherit_option": False},
        {"runtime_set": False},
        {"runtime_usage": False},
        {"member_inherit": False},
        {"member_role": "hostile_peer"},
    ):
        assert not _is_expected_neon_platform_edge(
            {**base, **mutation},
            lifecycle_admin="lifecycle_admin",
            lifecycle_admin_superuser=True,
            lifecycle_admin_inherit=True,
        )
    source = LIFECYCLE.read_text(encoding="utf-8")
    assert "actual_neon_platform not in {0, 1}" in source
    assert "WITH RECURSIVE platform AS" in source
    assert "neon_platform_descendant_count != actual_neon_platform" in source
    assert "neon_actor_descendant_count != actual_neon_platform" in source
    runner = RUNNER.read_text(encoding="utf-8")
    assert "_assert_neon_platform_lifecycle_audit_rejects_descendants" in runner
    assert "CHRONOS_CI_NEON_PLATFORM_HOSTILE_DESCENDANT_ACCEPTED" in runner
    assert "CHRONOS_CI_NEON_PLATFORM_AUDIT_DID_NOT_RECOVER" in runner
    assert "_assert_neon_platform_lifecycle_audit_rejects_orphans" in runner
    assert "CHRONOS_CI_NEON_PLATFORM_ORPHAN_DESCENDANT_ACCEPTED" in runner


def test_ci_executes_the_complete_readonly_preflight_ledger_before_role_mutation() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    main_source = source[source.index("def main() -> None:") :]
    superuser_proof = "superuser_readonly_preflight_catalog_contract = ("
    lifecycle_proof = "lifecycle_admin_readonly_preflight_catalog_contract = ("
    first_role_mutation = "provision_permanent_bootstrap_authority(admin)"
    assert "for ordinal, statement in enumerate(statements)" in source
    assert 'if len(statements) != 18' in source
    assert '"sql_statement_count": len(statements)' in source
    assert '"sql_read_count": len(rows_by_ordinal)' in source
    assert superuser_proof in source
    assert lifecycle_proof in source
    assert main_source.index(superuser_proof) < main_source.index(
        "_prepare_admin_profile(superuser_url, profile)"
    )
    assert main_source.index(lifecycle_proof) < main_source.index(first_role_mutation)
    assert 'expected_user="robin"' in source
    assert "ADMIN_ROLE if profile == PROFILE_NON_SUPERUSER" in source


def test_visual_ci_materializes_untracked_node_pages_before_build_and_tests() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    visual = source[source.index("  visual-regression:") :]

    setup_python = visual.index("uses: actions/setup-python@")
    install_generator = visual.index("Installer le générateur de présentation")
    install_requirements = visual.index(
        "python -m pip install -r requirements.txt"
    )
    install_repository = visual.index("python -m pip install --no-deps -e .")
    build_data = visual.index("pnpm run build:data")
    page_guard = visual.index(
        "test -s public/data/hypotheses/nodes/page-001.json"
    )
    vinext_build = visual.index("pnpm exec vinext build")
    node_tests = visual.index("node --test tests/*.test.mjs")

    assert setup_python < install_generator < install_requirements
    assert install_requirements < install_repository < build_data
    assert build_data < page_guard < vinext_build < node_tests
    assert visual.count("pnpm run build:data") == 1
    assert "continue-on-error" not in visual
    assert "|| true" not in visual
    assert "--test-skip-pattern" not in visual

    tracked_pages = subprocess.run(
        ["git", "ls-files", "cockpit/public/data/hypotheses/nodes/*.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tracked_pages == []


def test_pre_set_fail_closed_checks_cover_authority_public_and_password_state() -> None:
    source = LIFECYCLE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for invariant in (
        "CHRONOS_BOOTSTRAP_AUTHORITY_PASSWORD_UNSAFE",
        "CHRONOS_BOOTSTRAP_AUTHORITY_MEMBERSHIP_UNSAFE",
        "CHRONOS_BOOTSTRAP_AUTHORITY_EFFECTIVE_ROLE_UNSAFE",
        "CHRONOS_EXECUTOR_EFFECTIVE_PRIVILEGE_UNSAFE",
        "has_table_privilege",
        "has_any_column_privilege",
        "has_function_privilege",
        "has_schema_privilege",
    ):
        assert invariant in source
    for negative in (
        "authority_password_non_null",
        "hidden_authority_membership",
        "public_effective_privilege",
        "public_column_privilege",
        "public_alembic_mutation",
    ):
        assert negative in runner


def test_recovery_fences_executor_and_migrator_identity_reuse() -> None:
    lifecycle = LIFECYCLE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "CHRONOS_BOOTSTRAP_EXECUTOR_NAME_REUSE" in lifecycle
    assert "CHRONOS_MIGRATOR_SESSION_ACTIVE" in lifecycle
    assert "CHRONOS_MIGRATOR_MUST_BE_DISABLED" in lifecycle
    assert "same_executor_name_reuse" in runner
    assert "active_migrator_session" in runner
    assert "MIGRATOR_OID_CHANGED_AFTER_CRASH" in runner


def test_crash_checkpoint_uses_a_real_blocked_alembic_backend() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert '"-m", "alembic", "upgrade", REVISION_0015' in source
    assert "LOCK TABLE public.alembic_version IN ACCESS EXCLUSIVE MODE" in source
    assert "pg_stat_activity WHERE usename=%s" in source
    assert "l.relation='public.alembic_version'::regclass" in source
    assert 'a.wait_event_type=\'Lock\'' in source
    assert "alembic_version_lock_wait_observed" in source
    assert "backend_sessions_after_kill" in source
    assert "time.sleep(60)" not in source


def test_production_revalidates_under_lock_and_runs_alembic_in_process() -> None:
    source = PRODUCTION.read_text(encoding="utf-8")
    lock_index = source.index("acquire_lifecycle_lock(admin)")
    locked_revision_index = source.index("before = inspect_database", lock_index)
    branch_index = source.index(
        'if before["current_revision"] in EXPECTED_BEFORE_REVISIONS',
        locked_revision_index,
    )
    dispatch_revision_index = source.index(
        'cursor.execute("SELECT version_num FROM public.alembic_version")',
        branch_index,
    )
    dispatch_index = source.index("run_fenced_alembic", dispatch_revision_index)
    assert lock_index < locked_revision_index < branch_index
    assert branch_index < dispatch_revision_index < dispatch_index
    assert "subprocess.run" not in source
