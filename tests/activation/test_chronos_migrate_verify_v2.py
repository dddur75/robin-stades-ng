from __future__ import annotations

import base64
import inspect
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import pytest

import robin.chronos_role_lifecycle as lifecycle
import scripts.chronos_production_recovery_v2 as recovery
import scripts.dispatch_data_torrent_recovery_v2_stage as controller
from robin.chronos_production import (
    ChronosProductionError,
    data_torrent_recovery_v2_sql_contract_marker,
    generation_hash,
    sign_document,
)
from scripts import chronos_production_bootstrap_v3 as base

MAIN_SHA = "a" * 40
GENERATION_NONCE = "ab" * 32


def _binding() -> dict[str, object]:
    receipt = {
        "schema_version": "chronos-runtime-bindings-v2",
        "verdict": "FOUR_RUNTIME_BINDINGS_INSTALLED_V2",
        "repository": "dddur75/robin-stades-ng",
        "environment": "chronos-control-plane-production",
        "main_sha": MAIN_SHA,
        "preflight_run_id": "300",
        "preflight_hash": "b" * 64,
        "preflight_controller_receipt_sha256": "9" * 64,
        "secret_writes_attempted": 4,
        "secret_writes_confirmed": 4,
        "secret_names_in_order": [
            "CHRONOS_AUTHORITY_DATABASE_URL",
            "CHRONOS_RUNTIME_DATABASE_URL",
            "CHRONOS_READER_DATABASE_URL",
            "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        ],
        "secret_value_readbacks": 0,
        "automatic_retries": 0,
        "global_hold_full_validations": 2,
        "concurrent_run_inventory_validations": 4,
        "github_api_gets_upper_bound": 55,
        "github_api_gets_exact": False,
        "github_cli_version": "2.96.0",
        "github_cli_sha256": "cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b",
        "effect_admission_deadline_seconds": 480,
        "stage_outer_timeout_seconds": 600,
        "generation_hash": generation_hash(GENERATION_NONCE),
        "installed_at": "2026-08-30T13:00:00Z",
        "secret_values_observed": False,
    }
    return sign_document(receipt, GENERATION_NONCE)


def _identity_seal() -> dict[str, object]:
    payload_sha = "c" * 64
    archive_sha = "d" * 64
    store_sha = "e" * 64
    artifact_id = 210
    identity_run_id = "100"
    return {
        "schema_version": "durable-identity-seal-v2",
        "verdict": "DURABLE_IDENTITY_SEAL_V2",
        "sealed_at": "2026-08-30T12:30:00Z",
        "source": {
            "repository": "dddur75/robin-stades-ng",
            "ref": "refs/heads/main",
            "main_sha": MAIN_SHA,
            "run_id": "200",
            "run_attempt": "1",
        },
        "identity_go": {
            "schema_version": "github-artifact-attestation-v2",
            "repository": "dddur75/robin-stades-ng",
            "workflow_path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
            "run_id": identity_run_id,
            "run_attempt": "1",
            "head_sha": MAIN_SHA,
            "artifact_id": artifact_id,
            "artifact_name": f"neon-branch-identity-go-v2-{identity_run_id}",
            "payload_sha256": payload_sha,
            "archive_sha256": archive_sha,
            "durable_store": "R2_IMMUTABLE",
            "conditional_put_outcome": "CREATED",
            "durable_object_key": (
                "data-torrent-recovery-v2/control-plane/identity-go/"
                f"main_sha={MAIN_SHA}/run_id={identity_run_id}/report-{payload_sha}.json"
            ),
            "durable_metadata": {
                "schema": "neon-branch-identity-go-v2",
                "sha256": payload_sha,
                "main_sha": MAIN_SHA,
                "identity_run_id": identity_run_id,
                "artifact_id": str(artifact_id),
                "archive_sha256": archive_sha,
                "store_identity_sha256": store_sha,
            },
            "durable_readback_sha256": payload_sha,
            "store_identity_sha256": store_sha,
        },
        "github_actions": {
            "queued": 0,
            "in_progress": 0,
            "exact_main_dispatch_count": 1,
            "authority_window_dispatch_count": 1,
        },
        "effects": {
            "r2_puts": 1,
            "r2_gets": 1,
            "r2_objects_created": 1,
            "r2_lists": 0,
            "r2_deletes": 0,
            "r2_overwrites": 0,
            "automatic_retries": 0,
            "neon_gets": 0,
            "neon_mutations": 0,
            "postgresql_connections": 0,
            "sql_statements": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
        },
    }


def _bootstrap_effects(*, verify: bool) -> dict[str, object]:
    if verify:
        return {
            "effect_counter_certainty": "CONSERVATIVE_UPPER_BOUNDS",
            "r2_gets": 0,
            "r2_gets_exact": True,
            "r2_puts": 0,
            "neon_gets": 0,
            "neon_gets_exact": True,
            "neon_posts": 0,
            "neon_posts_exact": True,
            "postgresql_connection_attempts": 4,
            "postgresql_connection_attempts_exact": True,
            "recovery_branch_creations_upper_bound": 0,
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
        }
    return {
        "effect_counter_certainty": "CONSERVATIVE_UPPER_BOUNDS",
        "r2_gets": 0,
        "r2_gets_exact": True,
        "r2_puts": 0,
        "neon_gets": 1,
        "neon_gets_exact": True,
        "neon_posts": 0,
        "neon_posts_exact": True,
        "postgresql_connection_attempts": 5,
        "postgresql_connection_attempts_exact": True,
        "recovery_branch_creations_upper_bound": 0,
        "recovery_branch_creations_exact": True,
        "migration_dispatches": 0,
        "migration_dispatches_exact": True,
        "sql_statements_upper_bound": 2048,
        "sql_statements_exact": False,
        "sql_write_statements_upper_bound": 1024,
        "sql_write_statements_exact": False,
        "automatic_retries": 0,
        "provider_calls": 0,
        "purchases": 0,
        "secret_values_observed": False,
    }


def _terminal_executor() -> dict[str, object]:
    return {
        "schema_version": "chronos-bootstrap-executor-terminal-v2",
        "executor_role": "chronos_bootstrap_executor_recoveryv2",
        "state": "NEUTRALIZED",
        "marker": lifecycle.EXECUTOR_TOMBSTONE_MARKER,
        "can_login": False,
        "inherit": False,
        "password_null": True,
        "valid_until_epoch": True,
        "connection_limit": 0,
        "membership_count": 0,
        "session_count": 0,
        "effective_chronos_privilege_count": 0,
    }


def _migration_artifact() -> dict[str, object]:
    document = {
        "schema_version": "chronos-production-migrate-v2",
        "database_host": "ep-test.eu-central-1.aws.neon.tech",
        "database_port": 5432,
        "database_name": "neondb",
        "sslmode": "require",
        "channel_binding": "require",
        "authority_username": "chronos_authority_runtime_login",
        "runtime_username": "chronos_effect_runtime_login",
        "reader_username": "chronos_reader_login",
        "non_secret_generation_id": generation_hash(GENERATION_NONCE)[:16],
        "generation_hash": generation_hash(GENERATION_NONCE),
        "server_epoch": "2026-08-30T13:00:00Z",
        "revision": "0015_data_torrent_opportunity",
        "migration_dispatches": 0,
        "migration_outcome": "MIGRATION_RESUMED",
        "project_id": "project-1",
        "production_branch_id": "branch-production",
        "recovery_branch_id": "branch-recovery",
        "main_sha": MAIN_SHA,
        "workflow_sha": MAIN_SHA,
        "post_merge_ci_sha": MAIN_SHA,
        "preflight_run_id": "300",
        "preflight_hash": "b" * 64,
        "migration_run_id": "400",
        "migration_run_attempt": "1",
        "effects": _bootstrap_effects(verify=False),
        "identity_seal": _identity_seal(),
        "runtime_bindings": _binding(),
        "bootstrap_executor_terminal": _terminal_executor(),
    }
    return sign_document(document, GENERATION_NONCE)


def _verify_identities() -> dict[str, object]:
    accounts = {
        "authority": ("chronos_authority_runtime_login", "chronos_authority_executor"),
        "runtime": ("chronos_effect_runtime_login", "chronos_runtime_writer"),
        "reader": ("chronos_reader_login", "chronos_reader"),
    }
    return {
        role: {
            "database_host": "ep-test.eu-central-1.aws.neon.tech",
            "database_port": 5432,
            "database_name": "neondb",
            "sslmode": "require",
            "channel_binding": "require",
            "current_user": login,
            "revision": "0015_data_torrent_opportunity",
            "server_epoch": "2026-08-30T13:00:00Z",
            "memberships": [{"granted_role": group}],
        }
        for role, (login, group) in accounts.items()
    }


def _verify_artifact() -> dict[str, object]:
    document = {
        "schema_version": "chronos-production-verify-v2",
        "verdict": "VERIFY_0015_COMPLETE_V2",
        "revision": "0015_data_torrent_opportunity",
        "identities": _verify_identities(),
        "business_data_modified": False,
        "forbidden_membership": 0,
        "migrator_runtime_membership": 0,
        "runtime_effective_bootstrap_edge": 0,
        "provider_calls": 0,
        "r2_operations": 0,
        "main_sha": MAIN_SHA,
        "workflow_sha": MAIN_SHA,
        "post_merge_ci_sha": MAIN_SHA,
        "generation_hash": generation_hash(GENERATION_NONCE),
        "preflight_run_id": "300",
        "preflight_hash": "b" * 64,
        "migration_run_id": "400",
        "migration_run_attempt": "1",
        "verify_run_id": "500",
        "verify_run_attempt": "1",
        "migration_output_signature_algorithm": "HMAC-SHA256",
        "effects": _bootstrap_effects(verify=True),
        "identity_seal": _identity_seal(),
        "runtime_bindings": _binding(),
        "production_database_revision_verified": True,
        "chronos_opportunity_claim_active": True,
        "torrent_recovery_v2_contract_active": True,
        "runtime_bindings_present": 4,
    }
    return sign_document(document, GENERATION_NONCE)


def _resign(document: dict[str, object]) -> dict[str, object]:
    return sign_document(
        {key: value for key, value in document.items() if key != "signature"},
        GENERATION_NONCE,
    )


def test_controller_accepts_exact_signed_migration_and_verify_artifacts() -> None:
    migration = _migration_artifact()
    validated_migration = controller._validate_migration_artifact(
        migration,
        main_sha=MAIN_SHA,
        migration_run_id="400",
        generation_nonce=GENERATION_NONCE,
    )
    assert validated_migration == {
        key: value for key, value in migration.items() if key != "signature"
    }
    verify = _verify_artifact()
    validated_verify = controller._validate_verify_artifact(
        verify,
        main_sha=MAIN_SHA,
        verify_run_id="500",
        identity_run_id="100",
        expected_generation_hash=generation_hash(GENERATION_NONCE),
        generation_nonce=GENERATION_NONCE,
    )
    assert validated_verify == {key: value for key, value in verify.items() if key != "signature"}


def test_controller_binds_identity_seal_to_exact_cached_identity_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seal = _identity_seal()
    binding = seal["identity_go"]
    assert isinstance(binding, dict)
    attestation_fields = {
        "schema_version",
        "repository",
        "workflow_path",
        "run_id",
        "run_attempt",
        "head_sha",
        "artifact_id",
        "artifact_name",
        "payload_sha256",
        "archive_sha256",
    }
    attestation = {field: binding[field] for field in attestation_fields}
    monkeypatch.setattr(
        controller,
        "_load_cached_stage_success",
        lambda **_kwargs: {"attestation": attestation, "document": {}},
    )

    assert controller._validate_stage_success_document(
        stage="DURABLE_IDENTITY_SEAL_V2",
        document=seal,
        main_sha=MAIN_SHA,
        run_id="200",
        inputs={"identity_run_id": "100"},
    ) == seal

    mutant = deepcopy(seal)
    mutant_binding = mutant["identity_go"]
    assert isinstance(mutant_binding, dict)
    mutant_binding["artifact_id"] = 211
    metadata = mutant_binding["durable_metadata"]
    assert isinstance(metadata, dict)
    metadata["artifact_id"] = "211"
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_SEAL_INVALID",
    ):
        controller._validate_stage_success_document(
            stage="DURABLE_IDENTITY_SEAL_V2",
            document=mutant,
            main_sha=MAIN_SHA,
            run_id="200",
            inputs={"identity_run_id": "100"},
        )


def test_preflight_expiry_is_enforced_only_at_preflight_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_now: list[datetime | None] = []
    monkeypatch.setattr(
        controller,
        "_load_cached_stage_success",
        lambda **_kwargs: {"attestation": {}, "document": {"sealed": True}},
    )

    def validate(_document: object, **kwargs: object) -> dict[str, object]:
        observed_now.append(kwargs.get("now"))  # type: ignore[arg-type]
        return {"preflight_run_id": "300"}

    monkeypatch.setattr(controller, "validate_preflight_artifact_v2", validate)
    arguments = {
        "stage": "PRODUCTION_PREFLIGHT_V2",
        "document": {},
        "main_sha": MAIN_SHA,
        "run_id": "300",
        "inputs": {"identity_run_id": "100", "seal_run_id": "200"},
    }
    controller._validate_stage_success_document(
        **arguments,
        enforce_preflight_expiry=False,
    )
    controller._validate_stage_success_document(
        **arguments,
        enforce_preflight_expiry=True,
    )

    assert observed_now[0] is None
    assert isinstance(observed_now[1], datetime)


def test_live_release_chain_projection_is_exact_not_field_selective() -> None:
    verify = {
        key: value for key, value in _verify_artifact().items() if key != "signature"
    }
    expected = controller._expected_live_release_chain(
        verify=verify,
        verify_attestation={"payload_sha256": "f" * 64},
    )

    assert set(expected) == {
        "receipt_sha256",
        "schema_version",
        "verdict",
        "revision",
        "main_sha",
        "post_merge_ci_sha",
        "generation_hash",
        "preflight_run_id",
        "preflight_hash",
        "migration_run_id",
        "verify_run_id",
        "verify_run_attempt",
        "signature_algorithm",
        "database_target",
        "identity_seal",
        "runtime_bindings",
        "torrent_recovery_v2_contract_active",
    }
    assert expected["receipt_sha256"] == "f" * 64
    assert expected["verify_run_attempt"] == 1
    assert expected["database_target"] == {
        "host": "ep-test.eu-central-1.aws.neon.tech",
        "port": 5432,
        "database": "neondb",
        "sslmode": "require",
        "channel_binding": "require",
        "server_epoch": "2026-08-30T13:00:00Z",
    }


def test_controller_rejects_re_signed_migration_subcontract_mutants() -> None:
    base_document = _migration_artifact()

    def extra_field(value: dict[str, object]) -> None:
        value["extra"] = True

    def target_drift(value: dict[str, object]) -> None:
        value["database_host"] = "ep-test-pooler.eu-central-1.aws.neon.tech"

    def effect_drift(value: dict[str, object]) -> None:
        effects = value["effects"]
        assert isinstance(effects, dict)
        effects["sql_write_statements_upper_bound"] = 1025

    def executor_drift(value: dict[str, object]) -> None:
        terminal = value["bootstrap_executor_terminal"]
        assert isinstance(terminal, dict)
        terminal["effective_chronos_privilege_count"] = 1

    def binding_drift(value: dict[str, object]) -> None:
        binding = value["runtime_bindings"]
        assert isinstance(binding, dict)
        unsigned = {key: item for key, item in binding.items() if key != "signature"}
        unsigned["secret_writes_confirmed"] = 3
        value["runtime_bindings"] = sign_document(unsigned, GENERATION_NONCE)

    def seal_drift(value: dict[str, object]) -> None:
        seal = value["identity_seal"]
        assert isinstance(seal, dict)
        effects = seal["effects"]
        assert isinstance(effects, dict)
        effects["r2_gets"] = 2

    for mutate in (
        extra_field,
        target_drift,
        effect_drift,
        executor_drift,
        binding_drift,
        seal_drift,
    ):
        document = deepcopy(base_document)
        mutate(document)
        with pytest.raises(
            controller.RecoveryV2ControllerError,
            match="RECOVERY_V2_CONTROLLER_MIGRATION_INVALID",
        ):
            controller._validate_migration_artifact(
                _resign(document),
                main_sha=MAIN_SHA,
                migration_run_id="400",
                generation_nonce=GENERATION_NONCE,
            )


def test_controller_rejects_re_signed_verify_subcontract_mutants() -> None:
    base_document = _verify_artifact()

    def extra_field(value: dict[str, object]) -> None:
        value["extra"] = True

    def identity_target_drift(value: dict[str, object]) -> None:
        identities = value["identities"]
        assert isinstance(identities, dict)
        authority = identities["authority"]
        assert isinstance(authority, dict)
        authority["database_port"] = 6432

    def effect_drift(value: dict[str, object]) -> None:
        effects = value["effects"]
        assert isinstance(effects, dict)
        effects["sql_write_statements_upper_bound"] = 1

    def terminal_boolean_drift(value: dict[str, object]) -> None:
        value["production_database_revision_verified"] = False

    def run_drift(value: dict[str, object]) -> None:
        value["migration_run_attempt"] = "2"

    def binding_drift(value: dict[str, object]) -> None:
        binding = value["runtime_bindings"]
        assert isinstance(binding, dict)
        unsigned = {key: item for key, item in binding.items() if key != "signature"}
        unsigned["automatic_retries"] = 1
        value["runtime_bindings"] = sign_document(unsigned, GENERATION_NONCE)

    for mutate in (
        extra_field,
        identity_target_drift,
        effect_drift,
        terminal_boolean_drift,
        run_drift,
        binding_drift,
    ):
        document = deepcopy(base_document)
        mutate(document)
        with pytest.raises(
            controller.RecoveryV2ControllerError,
            match="RECOVERY_V2_CONTROLLER_VERIFY_INVALID",
        ):
            controller._validate_verify_artifact(
                _resign(document),
                main_sha=MAIN_SHA,
                verify_run_id="500",
                identity_run_id="100",
                expected_generation_hash=generation_hash(GENERATION_NONCE),
                generation_nonce=GENERATION_NONCE,
            )


def test_binding_receipt_requires_exactly_four_confirmed_writes() -> None:
    receipt = _binding()
    assert (
        recovery.validate_runtime_bindings_v2(
            receipt,
            main_sha=MAIN_SHA,
            preflight_run_id="300",
            preflight_artifact_hash="b" * 64,
            generation_nonce=GENERATION_NONCE,
        )
        == receipt
    )
    for field, value in (
        ("secret_writes_confirmed", 3),
        ("automatic_retries", 1),
        ("secret_value_readbacks", 1),
    ):
        invalid = {**receipt, field: value}
        with pytest.raises(ChronosProductionError, match="RUNTIME_BINDINGS_V2_INVALID"):
            recovery.validate_runtime_bindings_v2(
                invalid,
                main_sha=MAIN_SHA,
                preflight_run_id="300",
                preflight_artifact_hash="b" * 64,
                generation_nonce=GENERATION_NONCE,
            )


def test_migrate_admission_binds_runtime_receipt_to_exact_r3_controller_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / ".torrent" / "release"
    release.mkdir(parents=True)
    receipt_path = release / "chronos-runtime-bindings-v2.json"
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(controller, "_BINDINGS_RECEIPT", receipt_path)

    def encoded(document: dict[str, object]) -> str:
        payload = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        receipt_path.write_bytes(payload)
        return base64.b64encode(payload).decode("ascii")

    exact = _binding()
    assert (
        controller._validate_local_runtime_bindings(
            encoded_receipt=encoded(exact),
            main_sha=MAIN_SHA,
            preflight_run_id="300",
            preflight_hash="b" * 64,
            preflight_controller_receipt_sha256="9" * 64,
            generation_nonce=GENERATION_NONCE,
        )
        == exact
    )

    unsigned_mutant = {key: value for key, value in exact.items() if key != "signature"}
    unsigned_mutant["preflight_controller_receipt_sha256"] = "8" * 64
    resigned_mutant = sign_document(unsigned_mutant, GENERATION_NONCE)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_BINDINGS_INVALID",
    ):
        controller._validate_local_runtime_bindings(
            encoded_receipt=encoded(resigned_mutant),
            main_sha=MAIN_SHA,
            preflight_run_id="300",
            preflight_hash="b" * 64,
            preflight_controller_receipt_sha256="9" * 64,
            generation_nonce=GENERATION_NONCE,
        )

    run_cycle_source = inspect.getsource(controller.run_cycle)
    assert run_cycle_source.index("predecessor = _validate_predecessor") < (
        run_cycle_source.index("_write_receipt(receipt_path, reservation")
    )


def test_migrate_wrapper_requires_v2_preflight_and_binding_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(recovery, "validate_preflight_artifact_v2", lambda value, **_: value)
    monkeypatch.setattr(recovery, "_binding_document", lambda *_a, **_k: _binding())
    monkeypatch.setenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", GENERATION_NONCE)

    def fake_run(
        _report_dir: Path,
        _preflight_path: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        observed.update(kwargs)
        validator = kwargs["preflight_chain_validator"]
        seal, binding = validator(  # type: ignore[operator]
            {
                "preflight_run_id": "300",
                "preflight_hash": "b" * 64,
                "identity_seal": {"verdict": "DURABLE_IDENTITY_SEAL_V2"},
            },
            MAIN_SHA,
        )
        assert seal["verdict"] == "DURABLE_IDENTITY_SEAL_V2"
        assert binding["secret_writes_confirmed"] == 4
        return {"verdict": "MIGRATE_0015_COMPLETE_V2"}

    monkeypatch.setattr(base, "run_migrate", fake_run)
    assert recovery.run_migrate(tmp_path, tmp_path / "preflight", tmp_path / "binding") == {
        "verdict": "MIGRATE_0015_COMPLETE_V2"
    }
    assert observed["recovery_v2"] is True
    assert isinstance(observed["effects"], base.BootstrapEffects)
    assert observed["effects"].postgresql_connection_attempts_maximum == 10


def test_verify_wrapper_requires_seal_and_four_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery, "validate_identity_seal_v2", lambda value, **_: value)
    monkeypatch.setattr(recovery, "validate_runtime_bindings_v2", lambda value, **_: value)
    monkeypatch.setenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", GENERATION_NONCE)

    def fake_verify(
        _report_dir: Path,
        _migration_path: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        assert kwargs["recovery_v2"] is True
        validator = kwargs["migration_chain_validator"]
        seal, binding = validator(  # type: ignore[operator]
            {
                "identity_seal": {"identity_go": {"run_id": "100"}},
                "runtime_bindings": _binding(),
                "preflight_run_id": "300",
                "preflight_hash": "b" * 64,
            },
            MAIN_SHA,
        )
        assert seal["identity_go"]["run_id"] == "100"
        assert binding["secret_writes_confirmed"] == 4
        return {
            "schema_version": "chronos-production-verify-v2",
            "verdict": "VERIFY_0015_COMPLETE_V2",
            "revision": "0015_data_torrent_opportunity",
            "chronos_opportunity_claim_active": True,
            "runtime_bindings_present": 4,
        }

    monkeypatch.setattr(base, "run_verify", fake_verify)
    result = recovery.run_verify(tmp_path, tmp_path / "migration")
    assert result["revision"] == "0015_data_torrent_opportunity"
    assert result["chronos_opportunity_claim_active"] is True
    assert result["runtime_bindings_present"] == 4


def test_recovery_postgresql_budget_refuses_attempt_eleven_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = base.BootstrapEffects(postgresql_connection_attempts_maximum=10)
    effects.reserve_postgresql_connections(6, exact=True)
    effects.reserve_postgresql_connections(4, exact=False)
    assert effects.postgresql_connection_attempts == 10
    assert effects.postgresql_connection_attempts_exact is False
    monkeypatch.setattr(base, "_validate_bootstrap_authority", lambda: None)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_POSTGRESQL_CONNECTION_BUDGET_EXHAUSTED",
    ):
        base._connect_direct("never-dispatched", effects=effects)
    assert effects.postgresql_connection_attempts == 10


@pytest.mark.parametrize("maximum", [None, 9, 11])
def test_migrate_wrapper_rejects_non_exact_or_unbounded_connection_budget(
    tmp_path: Path,
    maximum: int | None,
) -> None:
    effects = base.BootstrapEffects(postgresql_connection_attempts_maximum=maximum)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_V2_EFFECT_COUNTER_INVALID",
    ):
        recovery.run_migrate(
            tmp_path,
            tmp_path / "preflight",
            tmp_path / "binding",
            effects=effects,
        )


def test_migrate_wrapper_rejects_preconsumed_effect_counter(tmp_path: Path) -> None:
    effects = base.BootstrapEffects(postgresql_connection_attempts_maximum=10)
    effects.reserve_postgresql_connections(1, exact=True)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_V2_EFFECT_COUNTER_INVALID",
    ):
        recovery.run_migrate(
            tmp_path,
            tmp_path / "preflight",
            tmp_path / "binding",
            effects=effects,
        )


def test_migrate_graph_has_six_orchestration_connections_plus_four_alembic() -> None:
    source = inspect.getsource(base.run_migrate)
    assert source.count("inspect_database(database_url, effects=effect_counts)") == 4
    assert source.count("_connect_direct(") == 2
    assert source.count("reserve_postgresql_connections(4, exact=False)") == 1


@pytest.mark.parametrize(
    ("field", "drift"),
    [
        ("database_host", "ep-other.eu-central-1.aws.neon.tech"),
        ("database_port", 6432),
        ("database_name", "otherdb"),
        ("sslmode", "verify-full"),
        ("channel_binding", "prefer"),
    ],
)
def test_migrate_rejects_signed_preflight_target_drift_before_neon_or_postgres(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    drift: object,
) -> None:
    api_key = "synthetic-neon-api-key"
    for name, value in {
        "GITHUB_SHA": MAIN_SHA,
        "GITHUB_WORKFLOW_SHA": MAIN_SHA,
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "400",
        "CHRONOS_EXPECTED_PREFLIGHT_RUN_ID": "300",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE": GENERATION_NONCE,
        "NEON_API_KEY": api_key,
        "NEON_BOOTSTRAP_DATABASE_URL": (
            "postgresql://bootstrap:synthetic-password@"
            "ep-test.eu-central-1.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require"
        ),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(base, "_validate_bootstrap_authority", lambda: None)
    monkeypatch.setattr(base, "assert_production_safety_locks", lambda _env: None)
    monkeypatch.setattr(base, "_assert_bootstrap_dispatch_ordinal", lambda **_: None)
    monkeypatch.setattr(base, "_assert_hold", lambda: {})
    monkeypatch.setattr(
        base,
        "_assert_post_merge_ci_binding",
        lambda *_args, **_kwargs: {"head_sha": MAIN_SHA},
    )
    monkeypatch.setattr(base, "_runtime_accounts", lambda **_: [])
    external_calls: list[str] = []
    monkeypatch.setattr(
        base,
        "resolve_neon_identity",
        lambda *_args, **_kwargs: external_calls.append("NEON"),
    )
    monkeypatch.setattr(
        base,
        "_connect_direct",
        lambda *_args, **_kwargs: external_calls.append("POSTGRES"),
    )
    artifact: dict[str, object] = {
        "preflight_run_id": "300",
        "preflight_run_attempt": "1",
        "post_merge_ci_sha": MAIN_SHA,
        "database_host": "ep-test.eu-central-1.aws.neon.tech",
        "database_port": 5432,
        "database_name": "neondb",
        "sslmode": "require",
        "channel_binding": "require",
    }
    artifact[field] = drift
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(sign_document(artifact, api_key)),
        encoding="utf-8",
    )
    validated: list[dict[str, Any]] = []

    def chain_validator(
        document: dict[str, Any], _main_sha: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        validated.append(document)
        return {}, {}

    with pytest.raises(
        ChronosProductionError,
        match="^CHRONOS_PREFLIGHT_DATABASE_TARGET_MISMATCH$",
    ):
        base.run_migrate(
            tmp_path / "reports",
            preflight_path,
            effects=base.BootstrapEffects(postgresql_connection_attempts_maximum=10),
            recovery_v2=True,
            preflight_chain_validator=chain_validator,
        )
    assert len(validated) == 1
    assert external_calls == []
    source = inspect.getsource(base.run_migrate)
    assert source.index("assert_exact_preflight_target") < source.index(
        "resolve_neon_identity"
    )


def test_recovery_migrate_retains_one_neutralized_executor_without_drop() -> None:
    lifecycle_source = inspect.getsource(base.neutralize_bootstrap_executor)
    migrate_source = inspect.getsource(base.run_migrate)
    assert "DROP ROLE" not in lifecycle_source
    assert "RECOVERY_V2_EXECUTOR_ROLE" in migrate_source
    assert "allow_stale_cleanup=not recovery_v2" in migrate_source
    assert migrate_source.count("neutralize_bootstrap_executor(") == 2
    assert "retained_executor_role=lease.executor_role if recovery_v2 else None" in migrate_source


def test_executor_create_role_probe_rolls_back_without_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object, _params: object = None) -> None:
            statements.append(str(statement))

        def fetchone(self) -> tuple[bool]:
            return (False,)

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(lifecycle, "assert_executor_before_set_role", lambda _connection: None)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_EXECUTOR_PRE_SET_CREATE_ROLE_SUCCEEDED",
    ):
        lifecycle.assert_executor_cannot_create_role(  # type: ignore[arg-type]
            Connection(),
            probe_role="chronos_executor_pre_set_probe",
        )
    joined = "\n".join(statements)
    assert "ROLLBACK TO SAVEPOINT" in joined
    assert "DROP ROLE" not in joined


def test_recovery_stale_executor_refuses_without_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle,
        "provision_permanent_bootstrap_authority",
        lambda *_args, **_kwargs: (lifecycle.BOOTSTRAP_AUTHORITY, 1, "admin", True),
    )
    monkeypatch.setattr(
        lifecycle,
        "_executor_names",
        lambda _connection: [lifecycle.BOOTSTRAP_EXECUTOR_PREFIX + "stalev2x"],
    )
    monkeypatch.setattr(
        lifecycle,
        "cleanup_bootstrap_executor",
        lambda *_args, **_kwargs: pytest.fail("Recovery V2 reached destructive cleanup"),
    )
    with pytest.raises(ChronosProductionError, match="CHRONOS_BOOTSTRAP_EXECUTOR_NAME_REUSE"):
        lifecycle.provision_bootstrap_executor(  # type: ignore[arg-type]
            object(),
            executor_role=base.RECOVERY_V2_EXECUTOR_ROLE,
            password="synthetic-secret",
            valid_until=datetime.now(UTC) + timedelta(minutes=1),
            lifecycle_lock_held=True,
            allow_stale_cleanup=False,
        )


@pytest.mark.parametrize("failed_checkpoint", ["executor_created", "executor_granted"])
def test_recovery_executor_failure_after_create_is_neutralized_once(
    monkeypatch: pytest.MonkeyPatch,
    failed_checkpoint: str,
) -> None:
    executor = base.RECOVERY_V2_EXECUTOR_ROLE
    neutralized: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _statement: object, _params: object = None) -> None:
            return None

    class Connection:
        commits = 0
        rollbacks = 0

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    connection = Connection()

    @contextmanager
    def client_cursor(_connection: object) -> Iterator[Cursor]:
        yield Cursor()

    monkeypatch.setattr(
        lifecycle,
        "provision_permanent_bootstrap_authority",
        lambda *_a, **_k: (lifecycle.BOOTSTRAP_AUTHORITY, 1, "admin", True),
    )
    monkeypatch.setattr(lifecycle, "_client_cursor", client_cursor)
    monkeypatch.setattr(lifecycle, "_assert_executor_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "_configure_transaction", lambda *_a, **_k: None)
    monkeypatch.setattr(
        lifecycle,
        "_executor_names",
        lambda _connection: [executor] if connection.commits else [],
    )
    monkeypatch.setattr(
        lifecycle,
        "neutralize_bootstrap_executor",
        lambda _connection, **kwargs: neutralized.append(str(kwargs["executor_role"])),
    )

    def checkpoint(name: str) -> None:
        if name == failed_checkpoint:
            raise RuntimeError(f"synthetic-{name}")

    with pytest.raises(RuntimeError, match=f"synthetic-{failed_checkpoint}"):
        lifecycle.provision_bootstrap_executor(  # type: ignore[arg-type]
            connection,
            executor_role=executor,
            password="synthetic-secret",
            valid_until=datetime.now(UTC) + timedelta(minutes=1),
            checkpoint=checkpoint,
            lifecycle_lock_held=True,
            allow_stale_cleanup=False,
            neutralize_on_failure=True,
        )
    assert connection.rollbacks >= 1
    assert neutralized == [executor]


def test_recovery_executor_grant_failure_is_neutralized_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = base.RECOVERY_V2_EXECUTOR_ROLE
    neutralized: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object, _params: object = None) -> None:
            if "GRANT" in str(statement):
                raise RuntimeError("synthetic-grant")

    class Connection:
        commits = 0

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            return None

    connection = Connection()

    @contextmanager
    def client_cursor(_connection: object) -> Iterator[Cursor]:
        yield Cursor()

    monkeypatch.setattr(
        lifecycle,
        "provision_permanent_bootstrap_authority",
        lambda *_a, **_k: (lifecycle.BOOTSTRAP_AUTHORITY, 1, "admin", True),
    )
    monkeypatch.setattr(lifecycle, "_client_cursor", client_cursor)
    monkeypatch.setattr(lifecycle, "_assert_executor_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "_configure_transaction", lambda *_a, **_k: None)
    monkeypatch.setattr(
        lifecycle,
        "_executor_names",
        lambda _connection: [executor] if connection.commits else [],
    )
    monkeypatch.setattr(
        lifecycle,
        "neutralize_bootstrap_executor",
        lambda _connection, **kwargs: neutralized.append(str(kwargs["executor_role"])),
    )
    with pytest.raises(RuntimeError, match="synthetic-grant"):
        lifecycle.provision_bootstrap_executor(  # type: ignore[arg-type]
            connection,
            executor_role=executor,
            password="synthetic-secret",
            valid_until=datetime.now(UTC) + timedelta(minutes=1),
            lifecycle_lock_held=True,
            allow_stale_cleanup=False,
            neutralize_on_failure=True,
        )
    assert neutralized == [executor]


def test_recovery_executor_cleanup_failure_is_terminal_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = base.RECOVERY_V2_EXECUTOR_ROLE

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _statement: object, _params: object = None) -> None:
            return None

    class Connection:
        commits = 0

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            return None

    connection = Connection()

    @contextmanager
    def client_cursor(_connection: object) -> Iterator[Cursor]:
        yield Cursor()

    monkeypatch.setattr(
        lifecycle,
        "provision_permanent_bootstrap_authority",
        lambda *_a, **_k: (lifecycle.BOOTSTRAP_AUTHORITY, 1, "admin", True),
    )
    monkeypatch.setattr(lifecycle, "_client_cursor", client_cursor)
    monkeypatch.setattr(lifecycle, "_assert_executor_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "_configure_transaction", lambda *_a, **_k: None)
    monkeypatch.setattr(
        lifecycle,
        "_executor_names",
        lambda _connection: [executor] if connection.commits else [],
    )
    monkeypatch.setattr(
        lifecycle,
        "neutralize_bootstrap_executor",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("SECRET-SENTINEL")),
    )
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_BOOTSTRAP_EXECUTOR_NEUTRALIZATION_FAILED",
    ):
        lifecycle.provision_bootstrap_executor(  # type: ignore[arg-type]
            connection,
            executor_role=executor,
            password="synthetic-secret",
            valid_until=datetime.now(UTC) + timedelta(minutes=1),
            checkpoint=lambda _name: (_ for _ in ()).throw(RuntimeError("original")),
            lifecycle_lock_held=True,
            allow_stale_cleanup=False,
            neutralize_on_failure=True,
        )


def test_recovery_migrate_enables_exception_safe_executor_neutralization() -> None:
    source = inspect.getsource(base.run_migrate)
    assert "neutralize_on_failure=recovery_v2" in source


def test_recovery_executor_neutralization_revokes_both_edges_and_never_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []
    terminal_assertions: list[str] = []
    executor = base.RECOVERY_V2_EXECUTOR_ROLE
    authority = lifecycle.BOOTSTRAP_AUTHORITY
    admin = "synthetic_admin"
    memberships = [
        (authority, executor, admin, False, False, False, True),
        (executor, admin, "provider", True, True, False, False),
    ]

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object, _params: object = None) -> None:
            statements.append(str(statement))

        def fetchone(self) -> tuple[int]:
            return (0,)

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            statements.append("COMMIT")

    @contextmanager
    def client_cursor(_connection: object) -> Iterator[Cursor]:
        yield Cursor()

    monkeypatch.setattr(lifecycle, "_assert_executor_catalog", lambda *_a, **_k: None)
    monkeypatch.setattr(lifecycle, "_executor_memberships", lambda *_a, **_k: memberships)
    monkeypatch.setattr(lifecycle, "_client_cursor", client_cursor)
    monkeypatch.setattr(
        lifecycle,
        "assert_neutralized_bootstrap_executor",
        lambda _connection, *, executor_role: terminal_assertions.append(executor_role),
    )
    lifecycle.neutralize_bootstrap_executor(  # type: ignore[arg-type]
        Connection(),
        executor_role=executor,
        authority=authority,
        lifecycle_admin=admin,
        lifecycle_admin_superuser=False,
    )
    joined = "\n".join(statements)
    assert joined.count("REVOKE") == 2
    assert "NOLOGIN" in joined
    assert "PASSWORD NULL" in joined
    assert "CONNECTION LIMIT 0" in joined
    assert "VALID UNTIL 'epoch'" in joined
    assert "DROP ROLE" not in joined
    assert terminal_assertions == [executor]


def test_verify_requires_exact_signed_neutralized_executor_observation() -> None:
    row: tuple[Any, ...] = (
        base.RECOVERY_V2_EXECUTOR_ROLE,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        0,
        None,
        True,
        lifecycle.EXECUTOR_TOMBSTONE_MARKER,
    )
    proof = base._recovery_v2_executor_terminal_proof()
    base._assert_recovery_v2_executor_terminal_observation(
        executor_rows=[row],
        membership_count=0,
        session_count=0,
        effective_chronos_privilege_count=0,
        migration_proof=proof,
    )
    mutants = (
        ([], 0, 0, 0, proof),
        ([row, row], 0, 0, 0, proof),
        ([(row[0], True, *row[2:])], 0, 0, 0, proof),
        ([row], 1, 0, 0, proof),
        ([row], 0, 1, 0, proof),
        ([row], 0, 0, 1, proof),
        ([row], 0, 0, 0, {**proof, "password_null": False}),
    )
    for rows, memberships, sessions, privileges, mutated_proof in mutants:
        with pytest.raises(ChronosProductionError, match="CHRONOS_VERIFY_ROLE_LIFECYCLE_UNSAFE"):
            base._assert_recovery_v2_executor_terminal_observation(
                executor_rows=rows,
                membership_count=memberships,
                session_count=sessions,
                effective_chronos_privilege_count=privileges,
                migration_proof=mutated_proof,
            )


def test_verify_inventory_counts_direct_column_privileges() -> None:
    verify_source = inspect.getsource(base.run_verify)
    column_query = verify_source.split("pg_catalog.has_column_privilege", maxsplit=1)[0].rsplit(
        "cursor.execute(", maxsplit=1
    )[1]
    assert "pg_catalog.pg_attribute" in column_query
    assert "a.attnum>0 AND NOT a.attisdropped" in column_query
    assert "c.relname LIKE 'chronos\\\\_%%'" in column_query
    assert "c.relname='alembic_version'" in column_query
    for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
        assert privilege in column_query


def test_migration_target_is_exactly_0015_and_neon_get_27_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = (
        Path(__file__).resolve().parents[2] / "migrations/versions/0015_data_torrent_opportunity.py"
    )
    assert migration.is_file()
    assert base.MIGRATION_TARGET == "0015_data_torrent_opportunity"
    effects = base.BootstrapEffects(neon_gets=26)
    client = base.NeonClient("synthetic", effects=effects, maximum_gets=26, maximum_posts=0)
    monkeypatch.setattr(base, "_validate_bootstrap_authority", lambda: None)
    with pytest.raises(ChronosProductionError, match="NEON_GET_BUDGET_EXHAUSTED"):
        client.branch("project", "branch")
    assert effects.neon_gets == 26


def test_sql_contract_marker_is_bound_to_exact_function_definition() -> None:
    definition = "CREATE OR REPLACE FUNCTION public.synthetic() RETURNS void ..."
    marker = data_torrent_recovery_v2_sql_contract_marker(definition)
    assert marker.startswith("DATA_TORRENT_RECOVERY_V2_SQL_CONTRACT_V1:")
    assert len(marker.rsplit(":", 1)[1]) == 64
    assert data_torrent_recovery_v2_sql_contract_marker(definition + " drift") != marker
