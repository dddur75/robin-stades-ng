from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.chronos_production_recovery_v2 as recovery
from robin.chronos_production import ChronosProductionError
from scripts.chronos_production_bootstrap_v3 import BootstrapEffects

MAIN_SHA = "a" * 40


@pytest.mark.parametrize("mode", ("PREFLIGHT", "MIGRATE", "VERIFY"))
def test_bootstrap_supervisor_timeout_preserves_exact_conservative_stage_maxima(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setattr(
        recovery,
        "run_child_once",
        lambda *_args, **_kwargs: recovery.SUPERVISOR_TIMEOUT_EXIT,
    )
    args = SimpleNamespace(
        mode=mode,
        report_dir=tmp_path,
        identity_artifact=None,
        seal_artifact=None,
        preflight_artifact=None,
        bindings_receipt=None,
        migration_artifact=None,
    )
    assert recovery._supervise(args) == recovery.SUPERVISOR_TIMEOUT_EXIT
    path = tmp_path / recovery._SUPERVISED_FILENAMES[mode]
    document = json.loads(path.read_bytes())
    assert recovery._validate_failure_export(document, mode=mode) == document
    assert document["effects"] == recovery._supervisor_effects(mode).snapshot()
    assert document["failure_class"] == "TRANSPORT_AMBIGUOUS"


@pytest.mark.parametrize(
    "mutation", ("exactness_type", "r2_top_mismatch", "supervisor_error_code")
)
def test_bootstrap_supervisor_rejects_malformed_failure_candidates(
    mutation: str,
) -> None:
    document = deepcopy(recovery._supervisor_fallback("PREFLIGHT"))
    if mutation == "exactness_type":
        document["effects"]["neon_gets_exact"] = "false"
    elif mutation == "r2_top_mismatch":
        document["r2_operations"] = 0
    else:
        document["error_code"] = "CHRONOS_OTHER_SAFE_FAILURE"
    with pytest.raises(ChronosProductionError, match="SUPERVISOR_EXPORT_INVALID"):
        recovery._validate_failure_export(document, mode="PREFLIGHT")


def test_bootstrap_export_key_guard_allows_only_exact_safe_structural_markers() -> None:
    assert not recovery._contains_forbidden_export_key(
        {
            "secret_values_observed": False,
            "secret_value_readbacks": 0,
            "password_null": True,
        }
    )
    for mutant in (
        {"secret_values_observed": True},
        {"secret_value_readbacks": 1},
        {"secret_value_readbacks": "0"},
        {"password_null": "true"},
        {"database_url": "postgresql://secret"},
    ):
        assert recovery._contains_forbidden_export_key(mutant)


@pytest.mark.parametrize(
    ("revision", "expected_connections"),
    [
        ("0014_chronos_control_plane_v2", 3),
        ("0015_data_torrent_opportunity", 4),
    ],
)
def test_preflight_orders_seal_get_then_postgres_then_neon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision: str,
    expected_connections: int,
) -> None:
    events: list[str] = []
    effects = BootstrapEffects(postgresql_connection_attempts_maximum=4)
    for name, value in {
        "GITHUB_SHA": MAIN_SHA,
        "GITHUB_WORKFLOW_SHA": MAIN_SHA,
        "GITHUB_RUN_ID": "300",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "CHRONOS_EXPECTED_MAIN_SHA": MAIN_SHA,
        "CHRONOS_EXPECTED_IDENTITY_RUN_ID": "100",
        "CHRONOS_EXPECTED_IDENTITY_SEAL_RUN_ID": "200",
        "NEON_BOOTSTRAP_DATABASE_URL": "postgresql://user:pw@host.example/db?sslmode=require&channel_binding=require",
        "NEON_API_KEY": "synthetic",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(recovery, "validate_data_torrent_recovery_v2_authority", lambda **_: None)
    monkeypatch.setattr(recovery, "assert_production_safety_locks", lambda _env: None)
    monkeypatch.setattr(recovery.base, "_assert_bootstrap_dispatch_ordinal", lambda **_: None)
    monkeypatch.setattr(recovery.base, "_assert_hold", lambda: {})
    monkeypatch.setattr(
        recovery.base, "_assert_post_merge_ci_binding", lambda *_a, **_k: {"head_sha": MAIN_SHA}
    )

    def seal_readback(**_kwargs: object) -> dict[str, object]:
        events.append("R2_GET")
        effects.r2_operations = 1
        return {"verdict": "DURABLE_IDENTITY_SEAL_V2"}

    monkeypatch.setattr(recovery, "_identity_seal_readback", seal_readback)

    def connect(_url: str, *, effects: BootstrapEffects) -> nullcontext[object]:
        events.append("POSTGRES")
        effects.postgresql_connection_attempts += 1
        return nullcontext(object())

    monkeypatch.setattr(recovery.base, "_connect_direct", connect)
    monkeypatch.setattr(recovery, "assert_privileged_catalog_visibility", lambda _connection: None)

    def inspect(_url: str, *, effects: BootstrapEffects) -> dict[str, object]:
        events.append("POSTGRES")
        effects.postgresql_connection_attempts += 1
        return {"current_revision": revision}

    monkeypatch.setattr(recovery.base, "inspect_database", inspect)
    monkeypatch.setattr(recovery, "role_inventory_hash", lambda _connection: "b" * 64)
    monkeypatch.setattr(recovery, "role_inventory_snapshot", lambda _connection: {})
    monkeypatch.setattr(recovery.base, "_assert_post_migration", lambda _database: None)
    monkeypatch.setattr(recovery.base, "_scalar", lambda *_a, **_k: revision)
    target = SimpleNamespace(
        host="host.example",
        port=5432,
        database="db",
        sslmode="require",
        channel_binding="require",
    )
    monkeypatch.setattr(recovery, "validate_direct_postgres_url", lambda _url: target)
    identity = SimpleNamespace(project_id="project", production_branch_id="branch")
    neon = SimpleNamespace(target_project_branch_count=1)

    def resolve(_key: str, _target: object, *, effects: BootstrapEffects) -> tuple[object, object]:
        events.append("NEON_GET")
        effects.neon_gets = 10
        return identity, neon

    monkeypatch.setattr(recovery.base, "resolve_neon_identity", resolve)
    monkeypatch.setattr(recovery, "require_neon_recovery_feasibility", lambda _neon: None)
    monkeypatch.setattr(recovery.base, "NeonClient", lambda *_a, **_k: object())

    def create(*_args: object, **_kwargs: object) -> dict[str, str]:
        events.append("NEON_POST")
        effects.neon_posts = 1
        return {
            "recovery_branch_id": "recovery",
            "recovery_branch_name": "chronos-pre-0015-recovery-20260830T130000Z",
        }

    monkeypatch.setattr(recovery.base, "create_recovery_point", create)
    monkeypatch.setattr(recovery, "validate_preflight_artifact_v2", lambda value, **_: value)
    report = recovery.run_preflight(
        tmp_path / "reports",
        tmp_path / "identity.json",
        tmp_path / "seal.json",
        effects=effects,
    )
    assert events == [
        "R2_GET",
        *("POSTGRES" for _ in range(expected_connections)),
        "NEON_GET",
        "NEON_POST",
    ]
    assert report["effects"]["r2_gets"] == 1
    assert report["effects"]["postgresql_connection_attempts"] == expected_connections
    assert report["effects"]["neon_posts"] == 1


def test_preflight_validator_rejects_effect_order_counter_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery, "validate_identity_seal_v2", lambda value, **_: value)
    artifact = {
        "schema_version": recovery.PREFLIGHT_SCHEMA,
        "main_sha": MAIN_SHA,
        "workflow_sha": MAIN_SHA,
        "project_id": "project",
        "production_branch_id": "branch",
        "current_revision": "0014_chronos_control_plane_v2",
        "role_inventory_hash": hashlib.sha256(b"[]").hexdigest(),
        "role_inventory": {},
        "recovery_branch_id": "recovery",
        "recovery_branch_name": "chronos-pre-0015-recovery-20260830T130000Z",
        "golden_gate": "CHRONOS_MIGRATION_READY",
        "database_host": "ep-test.eu-central-1.aws.neon.tech",
        "database_port": 5432,
        "database_name": "db",
        "sslmode": "require",
        "channel_binding": "require",
        "created_at": "2026-08-30T13:00:00Z",
        "expires_at": "2026-08-30T14:00:00Z",
        "preflight_run_id": "300",
        "preflight_run_attempt": "1",
        "post_merge_ci_sha": MAIN_SHA,
        "identity_run_id": "100",
        "seal_run_id": "200",
        "identity_seal": {"source": {"run_id": "200"}},
        "effects": {
            "effect_counter_certainty": "CONSERVATIVE_UPPER_BOUNDS",
            "r2_gets": 1,
            "r2_gets_exact": True,
            "r2_puts": 0,
            "neon_gets": 10,
            "neon_gets_exact": True,
            "neon_posts": 1,
            "neon_posts_exact": True,
            "postgresql_connection_attempts": 3,
            "postgresql_connection_attempts_exact": True,
            "recovery_branch_creations_upper_bound": 1,
            "recovery_branch_creations_exact": True,
            "migration_dispatches": 0,
            "migration_dispatches_exact": True,
            "sql_statements_upper_bound": 128,
            "sql_statements_exact": False,
            "sql_write_statements_upper_bound": 0,
            "sql_write_statements_exact": True,
            "automatic_retries": 0,
            "provider_calls": 0,
            "purchases": 0,
            "secret_values_observed": False,
        },
    }
    artifact["preflight_hash"] = recovery.preflight_hash(artifact)
    assert recovery.validate_preflight_artifact_v2(artifact, main_sha=MAIN_SHA)
    artifact["effects"]["postgresql_connection_attempts"] = 2
    with pytest.raises(Exception, match="PREFLIGHT_V2_INVALID"):
        recovery.validate_preflight_artifact_v2(artifact, main_sha=MAIN_SHA)
