from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from robin.chronos_production import (
    ChronosProductionError,
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
    _alembic_environment,
    _attempt_cleanup_steps,
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
    for name in (
        "chronos-production-bootstrap-v3.yml",
        "chronos-provider-free-canary-v3.yml",
    ):
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


def test_bootstrap_workflow_has_three_exclusive_modes_and_no_auto_head() -> None:
    content = (WORKFLOWS / "chronos-production-bootstrap-v3.yml").read_text(
        encoding="utf-8"
    )
    document = yaml.safe_load(content)
    options = _on(document)["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert options == ["PREFLIGHT", "MIGRATE", "VERIFY"]
    assert document["concurrency"] == {
        "group": "chronos-production-bootstrap-v3",
        "cancel-in-progress": False,
    }
    assert "alembic upgrade head" not in content
    assert "NEON_BOOTSTRAP_DATABASE_URL" not in str(document["jobs"]["verify"])
    assert "NEON_API_KEY" not in str(document["jobs"]["verify"])


def test_bootstrap_owner_provisions_roles_and_migrator_is_nocreaterole() -> None:
    bootstrap = (
        ROOT / "scripts" / "chronos_production_bootstrap_v3.py"
    ).read_text(encoding="utf-8")
    ci = (WORKFLOWS / "chronos-bootstrap-ci-v3.yml").read_text(encoding="utf-8")
    for content in (bootstrap, ci):
        assert "FROM CURRENT_USER" not in content
        assert "CREATEROLE PASSWORD" not in content
    assert "provision_chronos_group_roles" in bootstrap
    assert "provision_migrator" in bootstrap
    assert "provision_runtime_logins" in bootstrap
    assert "run_chronos_role_lifecycle_ci_v1.py" in ci
    migration = (
        ROOT / "migrations" / "versions" / "0014_chronos_control_plane_v2.py"
    ).read_text(encoding="utf-8")
    postgresql_test = (
        ROOT / "tests" / "chronos" / "test_chronos_postgresql_v2.py"
    ).read_text(encoding="utf-8")
    assert "CHRONOS_GROUP_ROLE_MISSING" in migration
    assert "CREATE ROLE" not in migration
    assert "DROP ROLE" not in migration
    assert "ALTER ROLE" not in migration
    assert "grantor.rolsuper" in postgresql_test
    assert "grantor='10'" not in postgresql_test


def test_role_valid_until_avoids_typed_bind_in_utility_grammar() -> None:
    lifecycle = (ROOT / "src" / "robin" / "chronos_role_lifecycle.py").read_text(
        encoding="utf-8"
    )
    runner = (
        ROOT / "scripts" / "run_chronos_role_lifecycle_ci_v1.py"
    ).read_text(encoding="utf-8")
    for content in (lifecycle, runner):
        assert "PASSWORD %s" in content
        assert "VALID UNTIL %s" not in content
        assert "sql.Literal(valid_until.isoformat())" in content


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


def test_alembic_subprocess_receives_no_bootstrap_or_runtime_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive = (
        "NEON_API_KEY",
        "NEON_BOOTSTRAP_DATABASE_URL",
        "CHRONOS_BOOTSTRAP_AUTHORITY_PASSWORD",
        "CHRONOS_BOOTSTRAP_RUNTIME_PASSWORD",
        "CHRONOS_BOOTSTRAP_READER_PASSWORD",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    )
    for name in sensitive:
        monkeypatch.setenv(name, f"sentinel-{name.lower()}")
    environment = _alembic_environment("postgresql://migrator:scoped@db/robin")
    assert environment["ROBIN_DATABASE_URL"].startswith("postgresql://migrator:")
    assert not set(sensitive).intersection(environment)


def test_cleanup_attempts_terminalization_after_migrator_cleanup_failure() -> None:
    attempted: list[str] = []

    def fail_migrator() -> None:
        attempted.append("migrator")
        raise RuntimeError("injected-disable-failure")

    def terminalize_owner() -> None:
        attempted.append("owner")

    with pytest.raises(ChronosProductionError, match="CHRONOS_LIFECYCLE_CLEANUP_FAILED"):
        _attempt_cleanup_steps((fail_migrator, terminalize_owner))
    assert attempted == ["migrator", "owner"]


def test_role_edge_matrix_contract_has_exact_eleven_edges() -> None:
    document = json.loads(
        (
            ROOT
            / "reports"
            / "activation"
            / "chronos-role-edge-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert document["phase_edge_counts"] == {
        "groups": 4,
        "migrator": 5,
        "final": 11,
    }
    assert len(document["edges"]) == 11
    assert document["forbidden_edge_count"] == 0
    assert document["runtime_effective_bootstrap_edge_count"] == 0
    assert document["migrator_runtime_edge_count"] == 0


def test_canary_has_only_the_reviewed_r2_surface_and_budgets() -> None:
    workflow = (
        WORKFLOWS / "chronos-provider-free-canary-v3.yml"
    ).read_text(encoding="utf-8")
    runner = (
        ROOT / "scripts" / "run_chronos_provider_free_canary_v3.py"
    ).read_text(encoding="utf-8")
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert "self.put > 1" in runner
    assert "self.get > 1" in runner
    assert "def list_" not in runner
    assert "def head_" not in runner
    assert "def delete_" not in runner
    assert "provider_calls\": 0" in runner
    assert "odds_credits\": 0" in runner


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///tmp.db",
        "postgresql://user:pass@ep-name-pooler.eu.neon.tech/db?sslmode=require",
        "postgresql://user:pass@ep-name.eu.neon.tech/db",
        "postgresql://user:pass@localhost/db?sslmode=require",
        "postgresql://user@ep-name.eu.neon.tech/db?sslmode=require",
        "postgresql://user:pass@ep-name.eu.neon.tech/db?sslmode=disable",
    ],
)
def test_direct_database_contract_fails_closed(value: str) -> None:
    with pytest.raises(ChronosProductionError):
        validate_direct_postgres_url(value)


def test_scoped_urls_encode_credentials_and_keep_tls() -> None:
    target = validate_direct_postgres_url(
        "postgresql://owner:bootstrap@ep-name.eu.neon.tech/robin?sslmode=require"
    )
    value = build_scoped_database_url(
        target,
        username="chronos_reader_login",
        password="p@ss:/?#% with spaces",
    )
    assert "p@ss" not in value
    assert "p%40ss%3A%2F%3F%23%25%20with%20spaces" in value
    assert value.endswith("sslmode=require")


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
    with pytest.raises(
        ChronosProductionError, match="CHRONOS_PREFLIGHT_SIGNATURE_MISMATCH"
    ):
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
    with pytest.raises(
        ChronosControlPlaneError, match="CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH"
    ):
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
