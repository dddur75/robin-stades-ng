from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "src" / "robin" / "chronos_role_lifecycle.py"
RUNNER = ROOT / "scripts" / "run_chronos_dual_principal_ci_v2.py"
PRODUCTION = ROOT / "scripts" / "chronos_production_bootstrap_v3.py"
MIGRATION = ROOT / "migrations" / "versions" / "0014_chronos_control_plane_v2.py"
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


def test_migration_0014_contains_objects_and_acls_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
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
    assert '"-m", "alembic", "upgrade", REVISION_0014' in source
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
        'if before["current_revision"] == EXPECTED_BEFORE_REVISION',
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
