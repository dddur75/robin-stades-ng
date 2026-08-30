from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlparse

import pytest
import yaml
from psycopg.conninfo import conninfo_to_dict

import scripts.chronos_neon_pure_readonly_preflight_v4 as readonly_preflight
import scripts.chronos_production_bootstrap_v3 as bootstrap_module
from robin.chronos_production import (
    PRODUCTION_SAFETY_LOCKS,
    SCOPED_LOGINS,
    ChronosProductionError,
    DirectPostgresTarget,
    assert_exact_preflight_binding,
    assert_production_safety_locks,
    build_generation_bound_password,
    build_scoped_database_url,
    preflight_hash,
    sign_document,
    validate_data_torrent_authority,
    validate_direct_postgres_url,
    verify_signed_document,
)
from robin.prospective_observatory.chronos_control_plane import (
    AttributableR2EffectExecutor,
    ChronosControlPlaneError,
    ConditionalPutOutcome,
    ConditionalPutResult,
    EffectEventType,
    EffectOperation,
    GitHubRunIdentity,
    MemoryChronosControlPlane,
    ObservedObject,
)
from scripts.chronos_production_bootstrap_v3 import (
    NeonClient,
    NeonIdentity,
    _attempt_cleanup_steps,
    create_recovery_point,
    inspect_database,
)
from tests.activation.test_chronos_neon_controlled_idle_wake_readonly_v1 import (
    _run_synthetic as _run_controlled_synthetic,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA = "1" * 40
WORKFLOW_SHA = "2" * 40
GENERATION = "ab" * 32
PAYLOAD = b'{"synthetic":true}'
PAYLOAD_HASH = hashlib.sha256(PAYLOAD).hexdigest()
NOW = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
EPOCH = datetime(2026, 8, 9, 20, 0, tzinfo=UTC)


def _on(document: dict[object, object]) -> object:
    return document.get("on", document.get(True))


def test_production_workflows_are_manual_only_and_environment_protected() -> None:
    for name in ("chronos-provider-free-canary-v3.yml",):
        document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        assert set(_on(document)) == {"workflow_dispatch"}
        assert document["permissions"]["contents"] == "read"
        for job in document["jobs"].values():
            assert job["environment"] == "chronos-control-plane-production"
        content = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "secrets.API_FOOTBALL_KEY" not in content
        assert "secrets.ODDS_API_KEY" not in content
        assert "schedule:" not in content
        assert "workflow_run:" not in content
        assert "repository_dispatch:" not in content


def test_mutating_production_bootstrap_workflow_is_manual_exact_and_protected() -> None:
    path = WORKFLOWS / "chronos-production-bootstrap-v3.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(_on(document)) == {"workflow_dispatch"}
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert set(document["jobs"]) == {"validate", "preflight", "migrate", "verify"}
    assert set(_on(document)["workflow_dispatch"]["inputs"]) == {
        "mode",
        "expected_main_sha",
        "post_merge_ci_sha",
        "controlled_run_id",
        "controlled_seal_run_id",
        "preflight_run_id",
        "migration_run_id",
    }
    assert document["env"] == {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
        "THE_ODDS_API_HISTORICAL_CREDITS": "false",
        "API_FOOTBALL_CALLS_ALLOWED": "0",
    }
    validation_source = document["jobs"]["validate"]["steps"][0]["run"]
    assert "GITHUB_RUN_ATTEMPT" in validation_source
    assert "git/ref/heads/main" in validation_source
    for name, job in document["jobs"].items():
        if name == "validate":
            continue
        assert job["environment"] == "chronos-control-plane-production"
        assert job["env"]["PYTHONPATH"] == "${{ github.workspace }}/src"
        setup = next(
            step for step in job["steps"] if "actions/setup-python@" in step.get("uses", "")
        )
        assert setup["with"]["python-version"] == "3.12.10"
        assert job["needs"] == "validate"
        assert job["if"] == f"inputs.mode == '{name.upper()}'"
    content = path.read_text(encoding="utf-8")
    assert "PREFLIGHT_RUN_ID: ${{ inputs.preflight_run_id }}" in content
    assert "CONTROLLED_RUN_ID: ${{ inputs.controlled_run_id }}" in content
    assert '[[ "$CONTROLLED_RUN_ID" =~ ^[1-9][0-9]*$ ]]' in content
    assert '[[ "$CONTROLLED_SEAL_RUN_ID" =~ ^[1-9][0-9]*$ ]]' in content
    assert '[[ "$PREFLIGHT_RUN_ID" =~ ^[1-9][0-9]*$ ]]' in content
    assert 'test -n "${{ inputs.preflight_run_id }}"' not in content
    assert content.count("--required-successful-ci-sha") == 3
    assert content.count("github_release_attestation_v1.py") == 4
    assert content.count("python -m scripts.chronos_production_bootstrap_v3") == 3
    assert "python scripts/chronos_production_bootstrap_v3.py" not in content
    assert content.count("NEON_ORG_ID: ${{ vars.NEON_ORG_ID }}") == 2
    assert "--migration-artifact .chronos/migration/chronos-bootstrap-output-v3.json" in content
    assert (
        "--workflow-path .github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"
    ) in content
    assert (
        "--controlled-readonly-artifact\n"
        "          .chronos/controlled/"
        "chronos-neon-controlled-idle-wake-readonly-v1.json"
    ) in content
    assert (
        "--controlled-seal-artifact\n"
        "          .chronos/controlled/"
        "chronos-controlled-go-durable-seal-v1.json"
    ) in content
    for name in ("preflight", "migrate", "verify"):
        upload = next(
            step
            for step in document["jobs"][name]["steps"]
            if "actions/upload-artifact@" in step.get("uses", "")
        )
        assert upload["if"] == "always()"


def test_recovery_receipt_is_written_immediately_after_branch_creation() -> None:
    source = (ROOT / "scripts" / "chronos_production_bootstrap_v3.py").read_text(encoding="utf-8")
    preflight = source[source.index("def run_preflight") : source.index("def _preflight_expiry")]
    controlled = preflight.index("controlled_readonly = _controlled_readonly_go")
    durable = preflight.index("controlled_go = _controlled_go_durable_binding")
    identity = preflight.index("identity, neon_observation = resolve_neon_identity")
    feasibility = preflight.index("require_neon_recovery_feasibility")
    mutating_client = preflight.index("client = NeonClient(api_key, effects=effect_counts)")
    created = preflight.index("recovery_report = create_recovery_point")
    receipt = preflight.index('"chronos-neon-recovery-point-v3.json"')
    database_inspection = preflight.index("database = inspect_database")
    assert controlled < durable < identity < feasibility < mutating_client < created
    assert created < receipt < database_inspection


def test_controlled_readonly_go_is_exact_and_causally_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_controlled_synthetic(monkeypatch)
    path = tmp_path / "controlled.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    receipt = bootstrap_module._controlled_readonly_go(
        path,
        expected_main_sha="a" * 40,
        expected_run_id="1234",
    )

    assert receipt["run_id"] == "1234"
    assert receipt["main_sha"] == "a" * 40
    assert receipt["compute_wake_events"] == 1
    assert receipt["postgresql_connection_attempts"] == 1
    assert receipt["production_sql_writes"] == 0
    assert len(receipt["artifact_sha256"]) == 64


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("verdict",), "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"),
        (("source", "run_id"), "4321"),
        (("source", "main_sha"), "b" * 40),
        (("checks", "project_identity_verified"), False),
        (("neon", "project_inventory_exhaustive"), False),
        (("neon", "cursor_cycle_encountered"), True),
        (("lifecycle", "effective_suspend_timeout_seconds"), 299),
        (("postgresql", "current_revision"), "0015_data_torrent_opportunity"),
        (("postgresql", "transaction_read_only"), False),
        (("effects", "neon_mutations"), 1),
        (("effects", "sql_write_count"), 1),
    ],
)
def test_controlled_readonly_gate_rejects_non_go_or_unbound_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: object,
) -> None:
    report = _run_controlled_synthetic(monkeypatch)
    target: dict[str, Any] = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    artifact = tmp_path / "controlled.json"
    artifact.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_CONTROLLED_READONLY_GO_NOT_PROVEN",
    ):
        bootstrap_module._controlled_readonly_go(
            artifact,
            expected_main_sha="a" * 40,
            expected_run_id="1234",
        )


def test_preflight_refuses_rerun_before_any_external_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in PRODUCTION_SAFETY_LOCKS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    external_calls = 0

    def forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal external_calls
        external_calls += 1
        raise AssertionError("external boundary must remain unreachable")

    monkeypatch.setattr(bootstrap_module, "NeonClient", forbidden)
    monkeypatch.setattr(bootstrap_module, "_connect_direct", forbidden)
    monkeypatch.setattr(bootstrap_module, "create_recovery_point", forbidden)
    report_dir = tmp_path / "reports"

    with pytest.raises(ChronosProductionError, match="CHRONOS_RERUN_FORBIDDEN"):
        bootstrap_module.run_preflight(report_dir)

    assert external_calls == 0
    assert not report_dir.exists()


def test_production_safety_locks_are_exact_and_fail_closed() -> None:
    assert_production_safety_locks(PRODUCTION_SAFETY_LOCKS)
    for name in PRODUCTION_SAFETY_LOCKS:
        invalid = dict(PRODUCTION_SAFETY_LOCKS)
        invalid[name] = "unsafe"
        with pytest.raises(
            ChronosProductionError,
            match=f"CHRONOS_PRODUCTION_SAFETY_LOCK_MISMATCH:{name}",
        ):
            assert_production_safety_locks(invalid)


def test_data_torrent_authority_is_exact_bound_and_time_limited() -> None:
    expiry = validate_data_torrent_authority(
        now=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
    )
    assert expiry == datetime(2026, 9, 1, 23, 59, 59, tzinfo=UTC)
    validate_data_torrent_authority(
        now=datetime(2026, 9, 1, 21, 59, 59, tzinfo=UTC),
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED",
    ):
        validate_data_torrent_authority(
            now=datetime(2026, 9, 1, 22, 0, 0, tzinfo=UTC),
        )
    with pytest.raises(ChronosProductionError, match="CHRONOS_MISSION_AUTHORITY_EXPIRED"):
        validate_data_torrent_authority(
            now=datetime(2026, 9, 1, 23, 59, 59, tzinfo=UTC),
        )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_MISSION_AUTHORITY_NOT_YET_ACTIVE",
    ):
        validate_data_torrent_authority(
            now=datetime(2026, 8, 30, 6, 35, 59, tzinfo=UTC),
        )


def test_all_authorized_effect_jobs_fit_inside_the_bound_runtime() -> None:
    effect_workflows = (
        "chronos-neon-controlled-idle-wake-readonly-v1.yml",
        "chronos-controlled-go-durable-seal-v1.yml",
        "chronos-production-bootstrap-v3.yml",
        "data-torrent-live-v1.yml",
    )
    for name in effect_workflows:
        workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            assert 1 <= int(job["timeout-minutes"]) <= 60


def test_data_torrent_authority_rejects_any_local_byte_drift(tmp_path: Path) -> None:
    execution = tmp_path / "configs" / "execution"
    execution.mkdir(parents=True)
    for name in (
        "data-torrent-ready-v1.json",
        "data-torrent-ready-v1-controlled-go-effect-contract.json",
    ):
        source = ROOT / "configs" / "execution" / name
        (execution / name).write_bytes(source.read_bytes())
    (execution / "data-torrent-ready-v1.json").write_bytes(
        (execution / "data-torrent-ready-v1.json").read_bytes() + b" "
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_MISSION_AUTHORITY_HASH_MISMATCH",
    ):
        validate_data_torrent_authority(
            now=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
            repository_root=tmp_path,
        )


def test_bootstrap_failure_receipt_preserves_all_external_effect_bounds() -> None:
    effects = bootstrap_module.BootstrapEffects(
        r2_operations=1,
        r2_operations_exact=False,
        neon_gets=7,
        neon_gets_exact=False,
        neon_posts=1,
        neon_posts_exact=True,
        postgresql_connection_attempts=3,
        postgresql_connection_attempts_exact=False,
        recovery_branch_creations_upper_bound=1,
        recovery_branch_creations_exact=False,
        migration_dispatches=1,
        migration_dispatches_exact=True,
    )
    effects.mark_sql_upper_bound(statements=2_048, writes=1_024)
    failure = bootstrap_module._safe_failure(
        "MIGRATE",
        ChronosProductionError("INJECTED_FAILURE"),
        effects,
    )
    observed = failure["effects"]
    assert observed["effect_counter_certainty"] == "CONSERVATIVE_UPPER_BOUNDS"
    assert observed["r2_gets"] == 1
    assert observed["r2_gets_exact"] is False
    assert observed["neon_gets"] == 7
    assert observed["neon_posts"] == 1
    assert observed["postgresql_connection_attempts"] == 3
    assert observed["recovery_branch_creations_upper_bound"] == 1
    assert observed["migration_dispatches"] == 1
    assert observed["sql_statements_upper_bound"] == 2_048
    assert observed["sql_write_statements_upper_bound"] == 1_024


def test_identity_failure_carries_neon_get_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = bootstrap_module.BootstrapEffects()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise readonly_preflight.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "synthetic",
            effect_counts={"neon_get_count": 7},
        )

    monkeypatch.setattr(bootstrap_module, "resolve_neon_identity_readonly", fail)
    with pytest.raises(ChronosProductionError, match="NEON_PROJECT_IDENTITY_AMBIGUOUS"):
        bootstrap_module.resolve_neon_identity(
            "synthetic-api-key",
            DirectPostgresTarget(
                host="ep-synthetic.neon.tech",
                port=5432,
                database="neondb",
                username="owner",
                sslmode="require",
                channel_binding="require",
            ),
            effects=effects,
        )
    assert effects.neon_gets == 7
    assert effects.neon_gets_exact is False


@pytest.mark.parametrize(
    ("mode", "dispatches"),
    [("PREFLIGHT", 1), ("MIGRATE", 2), ("VERIFY", 3)],
)
def test_bootstrap_dispatch_history_has_exact_stage_ordinal(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    dispatches: int,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "9876")
    calls: list[tuple[str, int, str, str]] = []

    def history(
        repository: str,
        run_id: int,
        main_sha: str,
        *,
        workflow_file: str,
    ) -> tuple[int, int, int]:
        calls.append((repository, run_id, main_sha, workflow_file))
        return 0, 0, dispatches

    monkeypatch.setattr(bootstrap_module.readonly_gate, "_github_actions_state", history)
    bootstrap_module._assert_bootstrap_dispatch_ordinal(mode=mode, main_sha=SHA)
    assert calls == [
        (
            "dddur75/robin-stades-ng",
            9876,
            SHA,
            "chronos-production-bootstrap-v3.yml",
        )
    ]
    monkeypatch.setattr(
        bootstrap_module.readonly_gate,
        "_github_actions_state",
        lambda *_args, **_kwargs: (0, 0, dispatches + 1),
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_BOOTSTRAP_DISPATCH_ORDINAL_MISMATCH",
    ):
        bootstrap_module._assert_bootstrap_dispatch_ordinal(mode=mode, main_sha=SHA)


def test_runtime_bindings_are_validated_against_bootstrap_target_before_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = DirectPostgresTarget(
        host="ep-production.eu-central-1.aws.neon.tech",
        port=5432,
        database="neondb",
        username="bootstrap",
        sslmode="require",
        channel_binding="require",
    )
    for login, _group, secret_name in SCOPED_LOGINS:
        password = build_generation_bound_password(
            nonce_hex=GENERATION,
            entropy="p" * 64,
        )
        monkeypatch.setenv(
            secret_name,
            build_scoped_database_url(target, username=login, password=password),
        )
    accounts = bootstrap_module._runtime_accounts(
        expected_target=target,
        generation_nonce=GENERATION,
    )
    assert [(login, group) for login, group, _password in accounts] == [
        (login, group) for login, group, _secret_name in SCOPED_LOGINS
    ]
    login, _group, secret_name = SCOPED_LOGINS[1]
    mismatched = replace(target, host="ep-other.eu-central-1.aws.neon.tech")
    monkeypatch.setenv(
        secret_name,
        build_scoped_database_url(
            mismatched,
            username=login,
            password=build_generation_bound_password(
                nonce_hex=GENERATION,
                entropy="q" * 64,
            ),
        ),
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_SCOPED_DATABASE_TARGET_MISMATCH",
    ):
        bootstrap_module._runtime_accounts(
            expected_target=target,
            generation_nonce=GENERATION,
        )
    monkeypatch.setenv(
        secret_name,
        build_scoped_database_url(
            target,
            username=login,
            password=build_generation_bound_password(
                nonce_hex="cd" * 32,
                entropy="q" * 64,
            ),
        ),
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_SCOPED_PASSWORD_GENERATION_MISMATCH",
    ):
        bootstrap_module._runtime_accounts(
            expected_target=target,
            generation_nonce=GENERATION,
        )
    source = (ROOT / "scripts" / "chronos_production_bootstrap_v3.py").read_text(encoding="utf-8")
    migrate_source = source[source.index("def run_migrate") : source.index("def run_verify")]
    assert migrate_source.index("runtime_accounts = _runtime_accounts") < migrate_source.index(
        "client = NeonClient(api_key, effects=effect_counts)"
    )
    assert migrate_source.index("assert_exact_preflight_binding") < migrate_source.index(
        "client = NeonClient(api_key, effects=effect_counts)"
    )
    assert (
        migrate_source.index("recovery = client.branch")
        < migrate_source.index("_assert_recovery_branch_observation")
        < migrate_source.index("prelock_observation = inspect_database")
    )


def test_controlled_go_is_validated_and_copied_through_signed_migrate_and_verify() -> None:
    source = (ROOT / "scripts" / "chronos_production_bootstrap_v3.py").read_text(encoding="utf-8")
    migrate = source[source.index("def run_migrate") : source.index("def run_verify")]
    verify = source[source.index("def run_verify") : source.index("def _safe_failure")]
    assert migrate.index("controlled_go = validate_controlled_go_binding") < migrate.index(
        "identity, _neon_observation = resolve_neon_identity"
    )
    assert migrate.count('"controlled_go": controlled_go') == 2
    assert '"preflight_hash": artifact["preflight_hash"]' in migrate
    assert verify.index("controlled_go = validate_controlled_go_binding") < verify.index("urls = {")
    assert verify.count('"controlled_go": controlled_go') == 1
    assert '"preflight_hash": preflight_chain_hash' in verify


def test_dual_principal_provisions_roles_and_migrator_is_nocreaterole() -> None:
    bootstrap = (ROOT / "scripts" / "chronos_production_bootstrap_v3.py").read_text(
        encoding="utf-8"
    )
    ci = (WORKFLOWS / "chronos-bootstrap-ci-v3.yml").read_text(encoding="utf-8")
    for content in (bootstrap, ci):
        assert "FROM CURRENT_USER" not in content
        assert "CREATEROLE PASSWORD" not in content
    assert "provision_chronos_group_roles" in bootstrap
    assert "provision_migrator" in bootstrap
    assert "provision_runtime_logins" in bootstrap
    assert "run_chronos_dual_principal_ci_v2.py" in ci
    migrations = tuple(
        (ROOT / "migrations" / "versions" / name).read_text(encoding="utf-8")
        for name in (
            "0014_chronos_control_plane_v2.py",
            "0015_data_torrent_opportunity.py",
        )
    )
    postgresql_test = (ROOT / "tests" / "chronos" / "test_chronos_postgresql_v2.py").read_text(
        encoding="utf-8"
    )
    assert "CHRONOS_GROUP_ROLE_MISSING" in migrations[0]
    for migration in migrations:
        assert "CREATE ROLE" not in migration
        assert "DROP ROLE" not in migration
        assert "ALTER ROLE" not in migration
    assert "grantor.rolsuper" in postgresql_test
    assert "grantor='10'" not in postgresql_test


def test_role_valid_until_avoids_typed_bind_in_utility_grammar() -> None:
    lifecycle = (ROOT / "src" / "robin" / "chronos_role_lifecycle.py").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_chronos_dual_principal_ci_v2.py").read_text(encoding="utf-8")
    assert "PASSWORD %s" in lifecycle
    assert "sql.Literal(valid_until.isoformat())" in lifecycle
    for content in (lifecycle, runner):
        assert "VALID UNTIL %s" not in content


def test_neon_identity_routes_are_rejected_before_network() -> None:
    client = NeonClient("test-only-neon-key")
    for method, path in (
        ("GET", "/projects/project/roles"),
        ("POST", "/projects/project/roles"),
        ("POST", "/projects/project/users"),
        ("POST", "/projects/project/identities"),
    ):
        with pytest.raises(ChronosProductionError, match="CHRONOS_NEON_ROUTE_FORBIDDEN"):
            client.request(method, path)


class _MutatingNeonResponse:
    def __init__(
        self,
        *,
        status_code: int,
        content: bytes,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.chunks = chunks if chunks is not None else [content]
        self.chunks_read = 0
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> object:
        assert chunk_size == 64 * 1024
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class _MutatingNeonSession:
    def __init__(self, response: _MutatingNeonResponse) -> None:
        self.response = response
        self.trust_env = True
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _MutatingNeonResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def test_mutating_neon_client_isolates_proxy_redirect_and_authorization_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _MutatingNeonSession(
        _MutatingNeonResponse(status_code=200, content=b'{"projects":[]}')
    )
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    monkeypatch.setattr(bootstrap_module.requests, "Session", lambda: session)

    client = NeonClient("synthetic-neon-key")
    assert client.projects() == []

    assert session.trust_env is False
    assert "Authorization" not in session.headers
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["allow_redirects"] is False
    assert call["stream"] is True
    assert call["headers"] == {
        "Authorization": "Bearer synthetic-neon-key",
        "Accept": "application/json",
    }


def test_mutating_neon_client_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _MutatingNeonResponse(status_code=307, content=b"")
    session = _MutatingNeonSession(response)
    monkeypatch.setattr(bootstrap_module.requests, "Session", lambda: session)

    client = NeonClient("synthetic-neon-key")
    with pytest.raises(ChronosProductionError, match="CHRONOS_NEON_API_HTTP_307"):
        client.projects()

    assert len(session.calls) == 1
    assert session.calls[0]["allow_redirects"] is False
    assert response.closed is True


@pytest.mark.parametrize(
    "content",
    [
        b'{"projects":[],"projects":[]}',
        b'{"value":NaN}',
        b"{}" + (b" " * bootstrap_module.MAX_NEON_RESPONSE_BYTES),
    ],
    ids=("duplicate-keys", "non-finite", "oversized"),
)
def test_mutating_neon_client_rejects_ambiguous_or_unbounded_json(
    content: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _MutatingNeonSession(_MutatingNeonResponse(status_code=200, content=content))
    monkeypatch.setattr(bootstrap_module.requests, "Session", lambda: session)

    client = NeonClient("synthetic-neon-key")
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_NEON_API_RESPONSE_INVALID",
    ):
        client.projects()


def test_mutating_neon_client_stops_stream_at_the_response_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _MutatingNeonResponse(
        status_code=200,
        content=b"",
        chunks=[
            b"x" * bootstrap_module.MAX_NEON_RESPONSE_BYTES,
            b"x",
            b"must-not-be-read",
        ],
    )
    session = _MutatingNeonSession(response)
    monkeypatch.setattr(bootstrap_module.requests, "Session", lambda: session)

    client = NeonClient("synthetic-neon-key")
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_NEON_API_RESPONSE_INVALID",
    ):
        client.projects()

    assert response.chunks_read == 2
    assert response.closed is True


def test_recovery_branch_request_explicitly_forbids_compute_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "branch": {"id": "branch-recovery-new"},
        "endpoints": [],
    }
    session = _MutatingNeonSession(
        _MutatingNeonResponse(
            status_code=201,
            content=json.dumps(response).encode("utf-8"),
        )
    )
    monkeypatch.setattr(bootstrap_module.requests, "Session", lambda: session)

    client = NeonClient("synthetic-neon-key")
    assert (
        client.create_recovery_branch(
            project_id="project-robin",
            parent_branch_id="branch-production",
            branch_name="chronos-pre-0015-recovery-20260830T000000Z",
        )
        == response
    )

    assert session.calls[0]["json"] == {
        "endpoints": [],
        "branch": {
            "name": "chronos-pre-0015-recovery-20260830T000000Z",
            "parent_id": "branch-production",
        },
    }


def test_bootstrap_identity_reuses_bounded_get_only_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = DirectPostgresTarget(
        host="ep-production.eu-central-1.aws.neon.tech",
        port=5432,
        database="neondb",
        username="bootstrap",
        sslmode="require",
        channel_binding="require",
    )
    readonly_client = object()
    calls: list[tuple[object, DirectPostgresTarget, bool]] = []

    def client_factory(api_key: str) -> object:
        assert api_key == "synthetic-neon-key"
        return readonly_client

    def resolver(
        client: object,
        observed_target: DirectPostgresTarget,
        *,
        allow_idle: bool,
    ) -> SimpleNamespace:
        calls.append((client, observed_target, allow_idle))
        return SimpleNamespace(
            project_id="project-production",
            project_name="Robin production",
            branch_id="branch-production",
            branch_name="production",
            endpoint_id="endpoint-production",
            endpoint_host=target.host,
            region="aws-eu-central-1",
        )

    monkeypatch.setattr(readonly_preflight, "NeonReadOnlyClient", client_factory)
    monkeypatch.setattr(readonly_preflight, "_resolve_neon_identity", resolver)

    identity, observation = bootstrap_module.resolve_neon_identity(
        "synthetic-neon-key",
        target,
    )

    assert calls == [(readonly_client, target, True)]
    assert observation.project_id == "project-production"
    assert identity == NeonIdentity(
        project_id="project-production",
        project_name="Robin production",
        production_branch_id="branch-production",
        production_branch_name="production",
        endpoint_id="endpoint-production",
        endpoint_host=target.host,
        region="aws-eu-central-1",
        database_name="neondb",
    )


def test_bootstrap_identity_preserves_only_sanitized_failure_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = DirectPostgresTarget(
        host="ep-production.eu-central-1.aws.neon.tech",
        port=5432,
        database="neondb",
        username="bootstrap",
        sslmode="require",
        channel_binding="require",
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise readonly_preflight.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "project_cursor_cycle",
            sanitized_evidence={"project_id_sha256": "raw-value-must-not-escape"},
        )

    monkeypatch.setattr(bootstrap_module, "resolve_neon_identity_readonly", fail)

    with pytest.raises(ChronosProductionError) as caught:
        bootstrap_module.resolve_neon_identity("synthetic-neon-key", target)

    assert str(caught.value) == "NEON_PROJECT_IDENTITY_AMBIGUOUS:project_cursor_cycle"
    assert "raw-value-must-not-escape" not in str(caught.value)


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"branch_capacity_proven": False}, "branch_capacity_ambiguous"),
        ({"owner_branch_count": 5, "branch_limit": 5}, "branch_capacity_exhausted"),
        ({"bill_free_branch_capacity_proven": False}, "purchase_required"),
        ({"history_retention_seconds": 0}, "recovery_branch_not_feasible"),
    ],
)
def test_recovery_feasibility_refuses_before_mutating_client(
    updates: dict[str, object],
    expected: str,
) -> None:
    values: dict[str, object] = {
        "branch_capacity_proven": True,
        "owner_branch_count": 1,
        "branch_limit": 10,
        "bill_free_branch_capacity_proven": True,
        "history_retention_seconds": 86_400,
        "branch_id": "branch-production",
        "branch_state": "ready",
    }
    values.update(updates)
    observation = SimpleNamespace(**values)

    with pytest.raises(readonly_preflight.PreflightNoGo) as caught:
        readonly_preflight.require_neon_recovery_feasibility(observation)  # type: ignore[arg-type]

    assert caught.value.gate == expected


class FakeRecoveryClient(NeonClient):
    def __init__(
        self,
        inventory: list[dict[str, object]],
        *,
        created_branch_id: str = "branch-recovery-new",
    ) -> None:
        self.inventory = inventory
        self.created_branch_id = created_branch_id
        self.created_branch_name = ""
        self.created_parent_branch_id = ""
        self.create_calls = 0
        self.branch_read_calls = 0
        self.branch_endpoint_calls = 0

    def branches(self, project_id: str) -> list[dict[str, object]]:  # type: ignore[override]
        assert project_id == "project-robin"
        return self.inventory

    def create_recovery_branch(
        self,
        *,
        project_id: str,
        parent_branch_id: str,
        branch_name: str,
    ) -> dict[str, object]:  # type: ignore[override]
        assert project_id == "project-robin"
        assert parent_branch_id == "branch-production"
        assert branch_name.startswith("chronos-pre-0015-recovery-")
        self.create_calls += 1
        self.created_branch_name = branch_name
        self.created_parent_branch_id = parent_branch_id
        return {
            "branch": {
                "id": self.created_branch_id,
                "project_id": project_id,
                "name": branch_name,
                "parent_id": parent_branch_id,
                "default": False,
                "current_state": "ready",
                "pending_state": None,
                "created_at": "2026-08-29T12:00:00Z",
            },
            "endpoints": [],
        }

    def branch(
        self,
        project_id: str,
        branch_id: str,
    ) -> dict[str, object]:  # type: ignore[override]
        assert project_id == "project-robin"
        assert branch_id == self.created_branch_id
        self.branch_read_calls += 1
        return {
            "id": self.created_branch_id,
            "project_id": project_id,
            "name": self.created_branch_name,
            "parent_id": self.created_parent_branch_id,
            "default": False,
            "current_state": "ready",
            "pending_state": None,
            "created_at": "2026-08-29T12:00:00Z",
        }

    def branch_endpoints(
        self,
        project_id: str,
        branch_id: str,
    ) -> list[dict[str, object]]:  # type: ignore[override]
        assert project_id == "project-robin"
        assert branch_id == self.created_branch_id
        self.branch_endpoint_calls += 1
        return []


def _neon_identity() -> NeonIdentity:
    return NeonIdentity(
        project_id="project-robin",
        project_name="Robin production",
        production_branch_id="branch-production",
        production_branch_name="production",
        endpoint_id="endpoint-production",
        endpoint_host="ep-production.eu-central-1.aws.neon.tech",
        region="aws-eu-central-1",
        database_name="neondb",
    )


def _branch_fixture(
    branch_id: str,
    name: str,
    *,
    default: bool = False,
    state: str = "ready",
    parent_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": branch_id,
        "project_id": "project-robin",
        "name": name,
        "parent_id": parent_id,
        "default": default,
        "current_state": state,
        "pending_state": None,
    }


def test_recovery_point_allows_only_the_second_cross_run_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap_module, "_utc_now", lambda: NOW)
    client = FakeRecoveryClient(
        [
            _branch_fixture("branch-production", "production", default=True),
            _branch_fixture(
                "branch-recovery-old",
                "chronos-pre-0015-recovery-20260828T120000Z",
                parent_id="branch-production",
            ),
        ]
    )

    receipt = create_recovery_point(
        client,
        _neon_identity(),
        expected_branch_count=2,
    )

    assert client.create_calls == 1
    assert receipt["recovery_branch_id"] == "branch-recovery-new"
    assert receipt["recovery_branch_limit"] == 2
    assert receipt["recovery_branch_count_before"] == 1
    assert receipt["recovery_branch_count_after"] == 2
    assert receipt["endpoint_count_in_create_response"] == 0
    assert receipt["endpoint_count_after_readiness"] == 0
    assert receipt["endpoint_created"] is False
    assert receipt["endpoint_absence_verified"] is True
    assert client.branch_read_calls == 1
    assert client.branch_endpoint_calls == 1


def test_recovery_point_accepts_readiness_on_the_twelfth_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])
    observations = 0

    def delayed_branch(project_id: str, branch_id: str) -> dict[str, object]:
        nonlocal observations
        observations += 1
        client.branch_read_calls += 1
        return {
            "id": branch_id,
            "project_id": project_id,
            "name": client.created_branch_name,
            "parent_id": client.created_parent_branch_id,
            "default": False,
            "current_state": "ready" if observations == 12 else "creating",
            "pending_state": None if observations == 12 else "ready",
            "created_at": "2026-08-29T12:00:00Z",
        }

    monkeypatch.setattr(client, "branch", delayed_branch)
    monkeypatch.setattr(bootstrap_module.time, "sleep", lambda _seconds: None)

    receipt = create_recovery_point(
        client,
        _neon_identity(),
        expected_branch_count=1,
    )

    assert receipt["readiness_verified"] is True
    assert observations == 12
    assert client.branch_endpoint_calls == 1


def test_recovery_point_requires_get_branch_to_match_ready_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])

    def divergent_branch(project_id: str, branch_id: str) -> dict[str, object]:
        client.branch_read_calls += 1
        return {
            "id": branch_id,
            "project_id": project_id,
            "name": client.created_branch_name,
            "parent_id": "branch-foreign",
            "default": False,
            "current_state": "ready",
            "pending_state": None,
        }

    monkeypatch.setattr(client, "branch", divergent_branch)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_OBSERVATION_INVALID",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert client.branch_read_calls == 1
    assert receipt["response_contract_verified"] is True
    assert receipt["readiness_verified"] is False


def test_recovery_point_receipt_survives_readiness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])

    def create_pending(**values: str) -> dict[str, object]:
        client.create_calls += 1
        return {
            "branch": {
                "id": "branch-recovery-pending",
                "project_id": "project-robin",
                "name": values["branch_name"],
                "parent_id": values["parent_branch_id"],
                "default": False,
                "current_state": "creating",
                "pending_state": "ready",
                "created_at": "2026-08-29T12:00:00Z",
            },
            "endpoints": [],
        }

    def readiness_failed(_project_id: str, _branch_id: str) -> dict[str, object]:
        raise ChronosProductionError("NEON_RECOVERY_READBACK_FAILED")

    monkeypatch.setattr(client, "create_recovery_branch", create_pending)
    monkeypatch.setattr(client, "branch", readiness_failed)
    monkeypatch.setattr(bootstrap_module.time, "sleep", lambda _seconds: None)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"
    with pytest.raises(ChronosProductionError, match="NEON_RECOVERY_READBACK_FAILED"):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["recovery_branch_id"] == "branch-recovery-pending"
    assert receipt["verdict"] == "NEON_RECOVERY_POINT_CREATED_PENDING_VERIFICATION"
    assert receipt["readiness_verified"] is False


def test_recovery_intent_receipt_survives_indeterminate_create_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])

    def indeterminate_create(**_values: str) -> dict[str, object]:
        client.create_calls += 1
        raise ChronosProductionError("CHRONOS_NEON_API_UNAVAILABLE")

    monkeypatch.setattr(client, "create_recovery_branch", indeterminate_create)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(ChronosProductionError, match="CHRONOS_NEON_API_UNAVAILABLE"):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["verdict"] == "NEON_RECOVERY_POINT_CREATE_OUTCOME_INDETERMINATE"
    assert receipt["create_request_dispatched"] is True
    assert receipt["create_response_observed"] is False
    assert receipt["create_outcome"] == "INDETERMINATE"
    assert receipt["endpoint_count_in_create_response"] is None
    assert receipt["endpoint_created"] is None
    assert receipt["readiness_verified"] is False


def test_recovery_intent_receipt_survives_missing_id_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])

    def missing_id(**values: str) -> dict[str, object]:
        client.create_calls += 1
        return {
            "branch": {
                "project_id": "project-robin",
                "name": values["branch_name"],
                "parent_id": values["parent_branch_id"],
                "default": False,
                "current_state": "creating",
                "pending_state": "ready",
            },
            "endpoints": [],
        }

    monkeypatch.setattr(client, "create_recovery_branch", missing_id)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(ChronosProductionError, match="CHRONOS_RECOVERY_BRANCH_ID_MISSING"):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["create_request_dispatched"] is True
    assert receipt["create_response_observed"] is True
    assert receipt["recovery_branch_id"] is None
    assert receipt["endpoint_count_in_create_response"] == 0
    assert receipt["endpoint_created"] is False
    assert receipt["readiness_verified"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "project-foreign"),
        ("parent_id", "branch-foreign"),
        ("name", "wrong-name"),
        ("default", True),
        ("current_state", "active"),
        ("pending_state", "deleting"),
    ],
)
def test_recovery_point_rejects_invalid_creation_response_after_post(
    field: str,
    value: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])
    original_create = client.create_recovery_branch

    def invalid_create(**values: str) -> dict[str, object]:
        document = original_create(**values)
        branch = document["branch"]
        assert isinstance(branch, dict)
        branch[field] = value
        return document

    monkeypatch.setattr(client, "create_recovery_branch", invalid_create)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_OBSERVATION_INVALID",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    assert client.create_calls == 1
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["verdict"] == "NEON_RECOVERY_POINT_CREATE_OUTCOME_INDETERMINATE"
    assert receipt["create_response_observed"] is True
    assert receipt["response_contract_verified"] is False
    assert receipt["readiness_verified"] is False


def test_recovery_point_records_and_rejects_endpoint_in_create_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])
    original_create = client.create_recovery_branch

    def create_with_endpoint(**values: str) -> dict[str, object]:
        document = original_create(**values)
        document["endpoints"] = [
            {
                "id": "endpoint-unexpected",
                "project_id": "project-robin",
                "branch_id": "branch-recovery-new",
                "type": "read_write",
            }
        ]
        return document

    monkeypatch.setattr(client, "create_recovery_branch", create_with_endpoint)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_ENDPOINT_CREATED_UNEXPECTEDLY",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["verdict"] == "NEON_RECOVERY_POINT_UNEXPECTED_ENDPOINT_CREATED"
    assert receipt["create_outcome"] == "CREATED_WITH_UNEXPECTED_ENDPOINT"
    assert receipt["endpoint_count_in_create_response"] == 1
    assert receipt["endpoint_created"] is True
    assert receipt["endpoint_absence_verified"] is False
    assert receipt["response_contract_verified"] is False
    assert receipt["readiness_verified"] is False
    assert client.branch_endpoint_calls == 0


def test_recovery_point_preserves_unknown_endpoint_state_for_invalid_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])
    original_create = client.create_recovery_branch

    def create_without_endpoint_contract(**values: str) -> dict[str, object]:
        document = original_create(**values)
        del document["endpoints"]
        return document

    monkeypatch.setattr(
        client,
        "create_recovery_branch",
        create_without_endpoint_contract,
    )
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_ENDPOINT_RESPONSE_INVALID",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["endpoint_count_in_create_response"] is None
    assert receipt["endpoint_created"] is None
    assert receipt["endpoint_absence_verified"] is False
    assert receipt["response_contract_verified"] is False
    assert receipt["readiness_verified"] is False


def test_recovery_point_rechecks_branch_endpoints_after_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeRecoveryClient([_branch_fixture("branch-production", "production", default=True)])

    def unexpected_branch_endpoints(
        _project_id: str,
        _branch_id: str,
    ) -> list[dict[str, object]]:
        client.branch_endpoint_calls += 1
        return [
            {
                "id": "endpoint-unexpected",
                "project_id": "project-robin",
                "branch_id": "branch-recovery-new",
                "type": "read_write",
            }
        ]

    monkeypatch.setattr(client, "branch_endpoints", unexpected_branch_endpoints)
    receipt_path = tmp_path / "chronos-neon-recovery-point-v3.json"

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_ENDPOINT_CREATED_UNEXPECTEDLY",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
            receipt_path=receipt_path,
        )

    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["verdict"] == "NEON_RECOVERY_POINT_UNEXPECTED_ENDPOINT_OBSERVED"
    assert receipt["endpoint_count_in_create_response"] == 0
    assert receipt["endpoint_count_after_readiness"] == 1
    assert receipt["endpoint_created"] is True
    assert receipt["endpoint_absence_verified"] is False
    assert receipt["response_contract_verified"] is True
    assert receipt["readiness_verified"] is False
    assert client.branch_endpoint_calls == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "branch-other"),
        ("project_id", "project-other"),
        ("parent_id", "branch-other"),
        ("name", "unrelated-branch"),
        ("default", True),
        ("current_state", "deleting"),
        ("pending_state", "deleting"),
    ],
)
def test_ready_recovery_observation_is_exactly_bound(
    field: str,
    value: object,
) -> None:
    branch = _branch_fixture(
        "branch-recovery-new",
        "chronos-pre-0015-recovery-20260829T120000Z",
        parent_id="branch-production",
    )
    branch[field] = value

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_OBSERVATION_INVALID",
    ):
        bootstrap_module._assert_recovery_branch_observation(
            branch,
            _neon_identity(),
            recovery_branch_id="branch-recovery-new",
            expected_name=None,
        )


def test_recovery_point_refuses_a_third_cross_run_branch_before_post() -> None:
    client = FakeRecoveryClient(
        [
            _branch_fixture("branch-production", "production", default=True),
            *[
                _branch_fixture(
                    f"branch-recovery-{index}",
                    f"chronos-pre-0015-recovery-2026082{index}T120000Z",
                    parent_id="branch-production",
                )
                for index in (7, 8)
            ],
        ]
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_LIMIT_REACHED",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=3,
        )
    assert client.create_calls == 0


def test_recovery_point_refuses_an_unbounded_branch_inventory_before_post() -> None:
    client = FakeRecoveryClient(
        [
            _branch_fixture("branch-production", "production", default=True),
            *[_branch_fixture(f"branch-{index}", f"unrelated-{index}") for index in range(1, 100)],
        ]
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=100,
        )
    assert client.create_calls == 0


def test_recovery_point_reconciles_the_proven_branch_count_before_post() -> None:
    client = FakeRecoveryClient(
        [
            {
                "id": "branch-production",
                "project_id": "project-robin",
                "name": "production",
                "default": True,
                "current_state": "ready",
                "pending_state": None,
            }
        ]
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=2,
        )

    assert client.create_calls == 0


@pytest.mark.parametrize(
    "invalid_branch",
    [
        {
            "project_id": "project-robin",
            "name": "missing-id",
            "default": False,
            "current_state": "ready",
            "pending_state": None,
        },
        {
            "id": "branch-foreign",
            "project_id": "project-foreign",
            "name": "foreign",
            "default": False,
            "current_state": "ready",
            "pending_state": None,
        },
    ],
)
def test_recovery_point_refuses_malformed_inventory_before_post(
    invalid_branch: dict[str, object],
) -> None:
    client = FakeRecoveryClient(
        [
            {
                "id": "branch-production",
                "project_id": "project-robin",
                "name": "production",
                "default": True,
                "current_state": "ready",
                "pending_state": None,
            },
            invalid_branch,
        ]
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=2,
        )

    assert client.create_calls == 0


def test_recovery_point_revalidates_ready_production_branch_before_post() -> None:
    client = FakeRecoveryClient(
        [
            {
                "id": "branch-production",
                "project_id": "project-robin",
                "name": "production",
                "default": True,
                "current_state": "deleting",
                "pending_state": None,
            }
        ]
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=1,
        )

    assert client.create_calls == 0


def test_recovery_point_refuses_a_reused_branch_id() -> None:
    client = FakeRecoveryClient(
        [
            _branch_fixture("branch-production", "production", default=True),
            _branch_fixture(
                "branch-recovery-old",
                "chronos-pre-0015-recovery-20260828T120000Z",
                parent_id="branch-production",
            ),
        ],
        created_branch_id="branch-recovery-old",
    )

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_BRANCH_ID_INVALID",
    ):
        create_recovery_point(
            client,
            _neon_identity(),
            expected_branch_count=2,
        )
    assert client.create_calls == 1


def test_alembic_runs_in_the_fenced_process_with_an_injected_connection() -> None:
    bootstrap = (ROOT / "scripts" / "chronos_production_bootstrap_v3.py").read_text(
        encoding="utf-8"
    )
    migration_environment = (ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    fenced_runner = (ROOT / "src" / "robin" / "chronos_alembic.py").read_text(encoding="utf-8")
    assert "subprocess.run" not in bootstrap
    assert "run_fenced_alembic" in bootstrap
    assert 'configuration.attributes["connection"]' in fenced_runner
    assert 'config.attributes.get("connection")' in migration_environment
    assert '"-c search_path=pg_catalog"' in fenced_runner
    assert 'common["version_table_schema"] = "public"' in migration_environment
    assert "CHRONOS_ALEMBIC_EXECUTION_FAILED" in fenced_runner


def test_cleanup_attempts_external_cleanup_after_migrator_failure() -> None:
    attempted: list[str] = []

    def fail_migrator() -> None:
        attempted.append("migrator")
        raise RuntimeError("injected-disable-failure")

    def cleanup_executor() -> None:
        attempted.append("executor")

    with pytest.raises(ChronosProductionError, match="CHRONOS_LIFECYCLE_CLEANUP_FAILED"):
        _attempt_cleanup_steps((fail_migrator, cleanup_executor))
    assert attempted == ["migrator", "executor"]


def test_role_edge_matrix_contract_classifies_both_admin_profiles() -> None:
    document = json.loads(
        (
            ROOT
            / "reports"
            / "architecture"
            / "chronos-dual-principal-authority-e1-v2-portable-contract.json"
        ).read_text(encoding="utf-8")
    )
    assert document["admin_profiles"]["superuser"]["active_final_edges"] == 12
    assert document["admin_profiles"]["superuser"]["terminal_edges"] == 11
    non_super = document["admin_profiles"]["non_superuser_createrole"]
    assert non_super["active_final_edges"] == 14
    assert non_super["terminal_edges"] == 12
    assert document["terminal_invariants"]["executor_roles"] == 0
    assert document["terminal_invariants"]["forbidden_edges"] == 0


def test_canary_has_only_the_reviewed_r2_surface_and_budgets() -> None:
    workflow = (WORKFLOWS / "chronos-provider-free-canary-v3.yml").read_text(encoding="utf-8")
    runner = (ROOT / "scripts" / "run_chronos_provider_free_canary_v3.py").read_text(
        encoding="utf-8"
    )
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert "self.put > 1" in runner
    assert "self.get > 1" in runner
    assert "def list_" not in runner
    assert "def head_" not in runner
    assert "def delete_" not in runner
    assert 'provider_calls": 0' in runner
    assert 'odds_credits": 0' in runner


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///tmp.db",
        "postgresql://user:pass@ep-name-pooler.eu.neon.tech/db?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://user:pass@ep-name.eu.neon.tech/db",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://user:pass@localhost/db?sslmode=require",
        "postgresql://user@ep-name.eu.neon.tech/db?sslmode=require",
        "postgresql://user:pass@ep-name.eu.neon.tech/db?sslmode=disable",  # SECRET_SCANNER_TEST_FIXTURE
    ],
)
def test_direct_database_contract_fails_closed(value: str) -> None:
    with pytest.raises(ChronosProductionError):
        validate_direct_postgres_url(value)


@pytest.mark.parametrize(
    ("query", "sslmode", "channel_binding"),
    [
        ("sslmode=require&channel_binding=require", "require", "require"),
        ("channel_binding=require&sslmode=require", "require", "require"),
        ("sslmode=verify-ca&channel_binding=require", "verify-ca", "require"),
        ("sslmode=verify-full&channel_binding=require", "verify-full", "require"),
    ],
)
def test_canonical_dsn_allowlist_accepts_only_reviewed_secure_sets(
    query: str,
    sslmode: str,
    channel_binding: str | None,
) -> None:
    target = validate_direct_postgres_url(
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?"  # SECRET_SCANNER_TEST_FIXTURE
        + query
    )
    assert target.sslmode == sslmode
    assert target.channel_binding == channel_binding


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=require&channel_binding=prefer",
        "sslmode=require&channel_binding=disable",
        "sslmode=require&channel_binding=",
        "sslmode=require&channel_binding=require&channel_binding=require",
        "sslmode=require&sslmode=require",
        "sslmode=require&SSLMode=require",
        "sslmode=require&host=attacker.example",
        "sslmode=require&hostaddr=192.0.2.10",
        "sslmode=require&port=6543",
        "sslmode=require&dbname=other",
        "sslmode=require&user=other",
        "sslmode=require&password=other",
        "sslmode=require&options=-csearch_path%3Dpublic",
        "sslmode=require&service=other",
        "sslmode=require&connect_timeout=10",
        "sslmode=require&application_name=other",
        "sslmode=require&unexpected_future_parameter=value",
        "sslmode=disable",
        "sslmode=allow",
        "sslmode=prefer",
    ],
)
def test_canonical_dsn_allowlist_rejects_overrides_and_downgrades(
    query: str,
) -> None:
    with pytest.raises(ChronosProductionError):
        validate_direct_postgres_url(
            "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?"  # SECRET_SCANNER_TEST_FIXTURE
            + query
        )


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin;host=attacker?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require#fragment",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/a/b?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name-pooler.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name-%70ooler.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-safe.eu.neon.tech%2Cep-other.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@%2Ftmp%2Fep-safe.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "POSTGRESQL://owner:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql+psycopg://owner:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-first.eu.neon.tech,ep-second.eu.neon.tech@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:raw:colon@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech:0/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bad%@ep-name.eu.neon.tech/robin?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/rob%in?sslmode=require",  # SECRET_SCANNER_TEST_FIXTURE
    ],
)
def test_canonical_dsn_rejects_ambiguous_url_structure(value: str) -> None:
    with pytest.raises(ChronosProductionError):
        validate_direct_postgres_url(value)


def test_direct_target_rejects_arbitrary_channel_binding() -> None:
    with pytest.raises(ChronosProductionError, match="CHANNEL_BINDING_REQUIRED"):
        DirectPostgresTarget(
            host="ep-name.eu.neon.tech",
            port=5432,
            database="robin",
            username="owner",
            sslmode="require",
            channel_binding="prefer",
        )


@pytest.mark.parametrize(
    "query",
    [
        "sslmode",
        "sslmode=require&",
        "sslmode=require&&channel_binding=require",
        "channel_binding=require",
        "sslmode=",
        "ssl%6dode=require",
        "sslmode=require&ssl%6dode=require",
    ],
)
def test_canonical_dsn_rejects_malformed_or_encoded_query_keys(query: str) -> None:
    with pytest.raises(ChronosProductionError):
        validate_direct_postgres_url(
            "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?"  # SECRET_SCANNER_TEST_FIXTURE
            + query
        )


@pytest.mark.parametrize(
    "host",
    [
        "ep-name-%70ooler.eu.neon.tech",
        "ep-safe.eu.neon.tech%2Cep-other.eu.neon.tech",
        "%2Ftmp%2Fep-safe.eu.neon.tech",
    ],
)
def test_encoded_host_redirection_fails_before_bootstrap_connect(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    connect_calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("psycopg.connect must remain unreachable")

    monkeypatch.setattr(bootstrap_module.psycopg, "connect", forbidden_connect)
    with pytest.raises(ChronosProductionError):
        inspect_database(
            "postgresql://owner:bootstrap@"  # SECRET_SCANNER_TEST_FIXTURE
            f"{host}/robin?sslmode=require&channel_binding=require"
        )
    assert connect_calls == 0


@pytest.mark.parametrize(
    "netloc",
    [
        "owner:bootstrap@ep-first.eu.neon.tech,ep-second.eu.neon.tech@ep-name.eu.neon.tech",
        "owner:bootstrap@@ep-name.eu.neon.tech",
    ],
)
def test_ambiguous_userinfo_fails_before_bootstrap_connect(
    monkeypatch: pytest.MonkeyPatch,
    netloc: str,
) -> None:
    connect_calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("psycopg.connect must remain unreachable")

    monkeypatch.setattr(bootstrap_module.psycopg, "connect", forbidden_connect)
    with pytest.raises(ChronosProductionError):
        inspect_database(
            f"postgresql://{netloc}/robin?sslmode=require&channel_binding=require"  # SECRET_SCANNER_TEST_FIXTURE
        )
    assert connect_calls == 0


def test_scoped_urls_encode_credentials_and_keep_tls() -> None:
    target = validate_direct_postgres_url(
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require&channel_binding=require"  # SECRET_SCANNER_TEST_FIXTURE
    )
    scoped_password = "p@ss:/?#% with spaces"
    value = build_scoped_database_url(
        target,
        username="chronos_reader_login",
        password=scoped_password,
    )
    assert scoped_password not in value
    rebuilt = validate_direct_postgres_url(value)
    parsed = urlparse(value)
    assert rebuilt.host == target.host
    assert rebuilt.port == target.port
    assert rebuilt.database == target.database
    assert rebuilt.username == "chronos_reader_login"
    assert parsed.password is not None
    assert rebuilt.sslmode == target.sslmode
    assert rebuilt.channel_binding == "require"
    assert {key for key, _ in parse_qsl(parsed.query)} == {
        "sslmode",
        "channel_binding",
    }
    libpq = conninfo_to_dict(value)
    assert libpq["host"] == target.host
    assert int(libpq.get("port", "5432")) == target.port
    assert libpq["dbname"] == target.database
    assert libpq["user"] == "chronos_reader_login"
    assert (
        hashlib.sha256(libpq["password"].encode()).digest()
        == hashlib.sha256(scoped_password.encode()).digest()
    )
    assert libpq["sslmode"] == target.sslmode
    assert libpq["channel_binding"] == "require"


def test_signed_preflight_is_bound_and_tampering_is_rejected() -> None:
    artifact: dict[str, object] = {
        "schema_version": "chronos-preflight-artifact-v3",
        "main_sha": SHA,
        "workflow_sha": WORKFLOW_SHA,
        "project_id": "project-robin",
        "production_branch_id": "branch-production",
        "current_revision": "0013_historical_evidence_index",
        "recovery_branch_id": "branch-recovery",
        "golden_gate": "CHRONOS_MIGRATION_READY",
    }
    artifact["preflight_hash"] = preflight_hash(artifact)  # type: ignore[arg-type]
    signed = sign_document(artifact, "sentinel-signing-key")  # type: ignore[arg-type]
    unsigned = verify_signed_document(signed, "sentinel-signing-key")
    assert_exact_preflight_binding(
        unsigned,
        main_sha=SHA,
        workflow_sha=WORKFLOW_SHA,
        project_id="project-robin",
        production_branch_id="branch-production",
        recovery_branch_id="branch-recovery",
    )
    tampered = {**signed, "production_branch_id": "branch-wrong"}
    with pytest.raises(ChronosProductionError, match="CHRONOS_PREFLIGHT_SIGNATURE_MISMATCH"):
        verify_signed_document(tampered, "sentinel-signing-key")


def test_signed_preflight_can_bind_an_exact_0014_resume() -> None:
    artifact: dict[str, object] = {
        "main_sha": SHA,
        "workflow_sha": WORKFLOW_SHA,
        "project_id": "project-robin",
        "production_branch_id": "branch-production",
        "current_revision": "0014_chronos_control_plane_v2",
        "recovery_branch_id": "branch-recovery",
        "golden_gate": "CHRONOS_MIGRATION_READY",
    }
    artifact["preflight_hash"] = preflight_hash(artifact)  # type: ignore[arg-type]
    assert_exact_preflight_binding(
        artifact,  # type: ignore[arg-type]
        main_sha=SHA,
        workflow_sha=WORKFLOW_SHA,
        project_id="project-robin",
        production_branch_id="branch-production",
        recovery_branch_id="branch-recovery",
        current_revision="0014_chronos_control_plane_v2",
    )


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class FakeStore:
    def __init__(self) -> None:
        self.put_calls = 0
        self.get_calls = 0

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str],
        on_dispatch: Callable[[], None],
    ) -> ConditionalPutResult:
        del key, data, metadata
        on_dispatch()
        self.put_calls += 1
        return ConditionalPutResult(ConditionalPutOutcome.CREATED)

    def get_object(self, key: str) -> ObservedObject | None:
        del key
        self.get_calls += 1
        return None


def _identity() -> GitHubRunIdentity:
    return GitHubRunIdentity(
        github_run_id=12345,
        github_run_attempt=1,
        github_sha=SHA,
        github_workflow_ref=(
            "dddur75/robin-stades-ng/.github/workflows/"
            "chronos-provider-free-canary-v3.yml@refs/heads/main"
        ),
        github_workflow_sha=WORKFLOW_SHA,
        github_repository="dddur75/robin-stades-ng",
        github_ref="refs/heads/main",
    )


def _operation(identity: GitHubRunIdentity | None = None) -> EffectOperation:
    selected = identity or _identity()
    return EffectOperation(
        mission_id="chronos-provider-free-canary-v3",
        identity=selected,
        resource_kind="R2_OBJECT",
        canonical_key="chronos/provider-free-canary/v3/synthetic.json",
        canonical_payload_hash=PAYLOAD_HASH,
        code_revision=selected.github_sha,
    )


def _issued(
    *, ttl: int = 60
) -> tuple[MutableClock, MemoryChronosControlPlane, str, EffectOperation]:
    clock = MutableClock()
    ledger = MemoryChronosControlPlane(clock=clock, postgres_server_epoch=EPOCH)
    operation = _operation()
    authority = ledger.issue_authority(
        mission_id=operation.mission_id,
        identity=operation.identity,
        generation_token=GENERATION,
        ttl_seconds=ttl,
        code_revision=operation.code_revision,
    )
    return clock, ledger, authority, operation


def test_old_authorities_and_run_identity_are_refused_without_network() -> None:
    clock, ledger, authority, operation = _issued(ttl=1)
    clock.value += timedelta(seconds=2)
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_AUTHORITY_NOT_ACTIVE"):
        ledger.claim_effect_authority(
            authority_id=authority,
            operation=operation,
            generation_token=GENERATION,
        )
    _, ledger, authority, operation = _issued()
    wrong_identity = replace(operation.identity, github_run_id=99999)
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH"):
        ledger.claim_effect_authority(
            authority_id=authority,
            operation=_operation(wrong_identity),
            generation_token=GENERATION,
        )


def test_restore_epoch_and_generation_are_refused_before_network() -> None:
    _, ledger, authority, operation = _issued()
    receipt = ledger.claim_effect_authority(
        authority_id=authority,
        operation=operation,
        generation_token=GENERATION,
    )
    ledger.restart_server_for_test(EPOCH + timedelta(hours=1))
    store = FakeStore()
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_SERVER_EPOCH_MISMATCH"):
        executor.dispatch_reserved(
            authority_id=authority,
            authority_receipt_hash=receipt.authority_receipt_hash,
            operation=operation,
            generation_token=GENERATION,
            payload=PAYLOAD,
        )
    assert store.put_calls == 0
    assert store.get_calls == 0

    _, ledger, authority, operation = _issued()
    ledger.claim_effect_authority(
        authority_id=authority,
        operation=operation,
        generation_token=GENERATION,
    )
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH",
    ):
        ledger.append_event(
            authority_id=authority,
            operation=operation,
            generation_token="cd" * 32,
            event_type=EffectEventType.PUT_DISPATCHED,
        )


def test_replay_after_terminal_state_emits_no_second_network() -> None:
    _, ledger, authority, operation = _issued()
    receipt = ledger.claim_effect_authority(
        authority_id=authority,
        operation=operation,
        generation_token=GENERATION,
    )
    store = FakeStore()
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    first = executor.dispatch_reserved(
        authority_id=authority,
        authority_receipt_hash=receipt.authority_receipt_hash,
        operation=operation,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    second = executor.dispatch_reserved(
        authority_id=authority,
        authority_receipt_hash=receipt.authority_receipt_hash,
        operation=operation,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert first.event.event_hash == second.event.event_hash
    assert store.put_calls == 1
    assert store.get_calls == 0
