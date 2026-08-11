from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import pytest
import yaml
from psycopg.conninfo import conninfo_to_dict

import scripts.chronos_production_bootstrap_v3 as bootstrap_module
from robin.chronos_production import (
    ChronosProductionError,
    DirectPostgresTarget,
    assert_exact_preflight_binding,
    build_scoped_database_url,
    preflight_hash,
    sign_document,
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
    _attempt_cleanup_steps,
    inspect_database,
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


def test_mutating_production_bootstrap_workflow_is_intentionally_absent() -> None:
    assert not (WORKFLOWS / "chronos-production-bootstrap-v3.yml").exists()


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
    migration = (ROOT / "migrations" / "versions" / "0014_chronos_control_plane_v2.py").read_text(
        encoding="utf-8"
    )
    postgresql_test = (ROOT / "tests" / "chronos" / "test_chronos_postgresql_v2.py").read_text(
        encoding="utf-8"
    )
    assert "CHRONOS_GROUP_ROLE_MISSING" in migration
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
        ("sslmode=require", "require", None),
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
    assert hashlib.sha256(libpq["password"].encode()).digest() == hashlib.sha256(
        scoped_password.encode()
    ).digest()
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
