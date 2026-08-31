"""Recovery V2 PREFLIGHT, MIGRATE, and VERIFY orchestration."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, cast

from robin.chronos_production import (
    _RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS,
    _RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS,
    EXPECTED_AFTER_REVISION,
    EXPECTED_BEFORE_REVISIONS,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    DirectPostgresTarget,
    assert_production_safety_locks,
    generation_hash,
    preflight_hash,
    require_sha,
    sign_document,
    validate_data_torrent_recovery_v2_authority,
    validate_direct_postgres_url,
    validate_identity_seal_v2,
    validate_neon_branch_identity_go_v2,
    validate_runtime_bindings_v2,
    verify_signed_document,
)
from robin.chronos_role_lifecycle import (
    assert_privileged_catalog_visibility,
    role_inventory_hash,
    role_inventory_snapshot,
)
from robin.prospective_observatory.chronos_r2 import ChronosR2ConditionalStore
from scripts import chronos_production_bootstrap_v3 as base
from scripts.chronos_neon_pure_readonly_preflight_v4 import require_neon_recovery_feasibility
from scripts.recovery_v2_supervision import (
    SUPERVISOR_CHILD_STUCK_EXIT,
    SUPERVISOR_EXPORT_EXIT,
    SUPERVISOR_TIMEOUT_EXIT,
    RecoveryV2SupervisionError,
    adopt_or_create_json_fallback,
    promote_validated_file,
    remaining_effect_timeout,
    run_child_once,
)

PREFLIGHT_SCHEMA = "production-preflight-v2"
PREFLIGHT_FILENAME = "production-preflight-v2.json"
WORKFLOW_FILE = "chronos-production-bootstrap-v4.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"
_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*(?::[A-Z0-9_.-]+)*$")
_PREFLIGHT_FIELDS = {
    "schema_version",
    "main_sha",
    "workflow_sha",
    "project_id",
    "production_branch_id",
    "current_revision",
    "role_inventory_hash",
    "role_inventory",
    "recovery_branch_id",
    "recovery_branch_name",
    "golden_gate",
    "database_host",
    "database_port",
    "database_name",
    "sslmode",
    "channel_binding",
    "created_at",
    "expires_at",
    "preflight_run_id",
    "preflight_run_attempt",
    "post_merge_ci_sha",
    "identity_run_id",
    "seal_run_id",
    "identity_seal",
    "effects",
    "preflight_hash",
}
_SUPERVISOR_TIMEOUT_SECONDS = 780
_SUPERVISED_FILENAMES = {
    "PREFLIGHT": PREFLIGHT_FILENAME,
    "MIGRATE": "chronos-production-migrate-v2.json",
    "VERIFY": "chronos-production-verify-v2.json",
}
_SUPERVISED_SUCCESS_SCHEMAS = {
    "PREFLIGHT": PREFLIGHT_SCHEMA,
    "MIGRATE": "chronos-production-migrate-v2",
    "VERIFY": "chronos-production-verify-v2",
}
_FORBIDDEN_EXPORT_KEY_PARTS = (
    "api_key",
    "database_url",
    "password",
    "secret_value",
    "access_key",
    "private_key",
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _read_json(path: Path, *, code: str) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = path.read_bytes()
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError(code) from None
    if (
        not payload
        or len(payload) > 10 * 1024 * 1024
        or path.is_symlink()
        or not isinstance(document, dict)
    ):
        raise ChronosProductionError(code)
    return payload, cast(dict[str, Any], document)


def _timestamp(value: object, *, code: str) -> datetime:
    if not isinstance(value, str):
        raise ChronosProductionError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ChronosProductionError(code) from None
    if parsed.tzinfo is None:
        raise ChronosProductionError(code)
    return parsed.astimezone(UTC)


def validate_preflight_artifact_v2(
    value: object,
    *,
    main_sha: str,
    expected_identity_run_id: str | None = None,
    expected_seal_run_id: str | None = None,
    expected_identity_seal: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate PREFLIGHT V2 and, when supplied, its exact causal admission."""

    expected_sha = require_sha(main_sha, field="main_sha")
    if not isinstance(value, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    artifact = dict(value)
    signature = artifact.pop("signature", None)
    if signature is not None and (
        not isinstance(signature, dict)
        or set(signature) != {"algorithm", "value"}
        or signature.get("algorithm") != "HMAC-SHA256"
        or not isinstance(signature.get("value"), str)
        or _HEX_64.fullmatch(cast(str, signature.get("value"))) is None
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    if set(artifact) != _PREFLIGHT_FIELDS:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    identity_run_id = artifact.get("identity_run_id")
    seal_run_id = artifact.get("seal_run_id")
    preflight_run_id = artifact.get("preflight_run_id")
    if any(
        not isinstance(item, str) or _RUN_ID.fullmatch(item) is None
        for item in (identity_run_id, seal_run_id, preflight_run_id)
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    seal = validate_identity_seal_v2(
        artifact.get("identity_seal"),
        main_sha=expected_sha,
        expected_identity_run_id=cast(str, identity_run_id),
    )
    source = cast(dict[str, Any], seal["source"])
    effects = artifact.get("effects")
    revision = artifact.get("current_revision")
    expected_connections = 4 if revision == EXPECTED_AFTER_REVISION else 3
    if (
        not isinstance(artifact.get("database_host"), str)
        or type(artifact.get("database_port")) is not int
        or not isinstance(artifact.get("database_name"), str)
        or not isinstance(artifact.get("sslmode"), str)
        or not isinstance(artifact.get("channel_binding"), str)
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    try:
        DirectPostgresTarget(
            host=cast(str, artifact.get("database_host")),
            port=cast(int, artifact.get("database_port")),
            database=cast(str, artifact.get("database_name")),
            username="bootstrap-placeholder",
            sslmode=cast(str, artifact.get("sslmode")),
            channel_binding=cast(str, artifact.get("channel_binding")),
        )
    except ChronosProductionError:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID") from None
    if (
        artifact.get("schema_version") != PREFLIGHT_SCHEMA
        or artifact.get("main_sha") != expected_sha
        or artifact.get("workflow_sha") != expected_sha
        or artifact.get("post_merge_ci_sha") != expected_sha
        or artifact.get("preflight_run_attempt") != "1"
        or source.get("run_id") != seal_run_id
        or artifact.get("golden_gate") != "CHRONOS_MIGRATION_READY"
        or revision not in {*EXPECTED_BEFORE_REVISIONS, EXPECTED_AFTER_REVISION}
        or not isinstance(artifact.get("project_id"), str)
        or base._NEON_SAFE_IDENTIFIER.fullmatch(cast(str, artifact.get("project_id"))) is None
        or not isinstance(artifact.get("production_branch_id"), str)
        or base._NEON_SAFE_IDENTIFIER.fullmatch(
            cast(str, artifact.get("production_branch_id"))
        )
        is None
        or not isinstance(artifact.get("recovery_branch_id"), str)
        or base._NEON_SAFE_IDENTIFIER.fullmatch(
            cast(str, artifact.get("recovery_branch_id"))
        )
        is None
        or not isinstance(artifact.get("recovery_branch_name"), str)
        or base._RECOVERY_BRANCH_NAME.fullmatch(
            cast(str, artifact.get("recovery_branch_name"))
        )
        is None
        or not isinstance(artifact.get("role_inventory"), dict)
        or not isinstance(artifact.get("role_inventory_hash"), str)
        or _HEX_64.fullmatch(cast(str, artifact.get("role_inventory_hash"))) is None
        or type(artifact.get("database_port")) is not int
        or artifact.get("preflight_hash") != preflight_hash(artifact)
        or not isinstance(effects, dict)
        or set(effects) != _RECOVERY_V2_BOOTSTRAP_EFFECT_FIELDS
        or any(
            type(effects.get(field)) is not int
            for field in _RECOVERY_V2_BOOTSTRAP_INTEGER_FIELDS
        )
        or effects.get("effect_counter_certainty") != "CONSERVATIVE_UPPER_BOUNDS"
        or effects.get("r2_gets") != 1
        or effects.get("r2_gets_exact") is not True
        or effects.get("r2_puts") != 0
        or effects.get("neon_gets_exact") is not True
        or type(effects.get("neon_gets")) is not int
        or not 1 <= effects.get("neon_gets", 0) <= 39
        or effects.get("neon_posts") != 1
        or effects.get("neon_posts_exact") is not True
        or effects.get("postgresql_connection_attempts") != expected_connections
        or effects.get("postgresql_connection_attempts_exact") is not True
        or effects.get("recovery_branch_creations_upper_bound") != 1
        or effects.get("recovery_branch_creations_exact") is not True
        or effects.get("migration_dispatches") != 0
        or effects.get("migration_dispatches_exact") is not True
        or effects.get("sql_statements_upper_bound") != 128
        or effects.get("sql_statements_exact") is not False
        or effects.get("sql_write_statements_upper_bound") != 0
        or effects.get("sql_write_statements_exact") is not True
        or effects.get("automatic_retries") != 0
        or effects.get("provider_calls") != 0
        or effects.get("purchases") != 0
        or effects.get("secret_values_observed") is not False
        or (
            expected_identity_run_id is not None
            and identity_run_id != expected_identity_run_id
        )
        or expected_seal_run_id is not None
        and seal_run_id != expected_seal_run_id
        or expected_identity_seal is not None
        and artifact.get("identity_seal") != dict(expected_identity_seal)
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    inventory = cast(dict[str, object], artifact["role_inventory"])
    if any(not isinstance(name, str) or not name or not isinstance(row, list) for name, row in inventory.items()):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    inventory_payload = [[name, *cast(list[object], row)] for name, row in sorted(inventory.items())]
    inventory_hash = hashlib.sha256(
        json.dumps(
            inventory_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    if not hmac.compare_digest(
        cast(str, artifact["role_inventory_hash"]),
        inventory_hash,
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    created = _timestamp(artifact.get("created_at"), code="CHRONOS_PREFLIGHT_V2_INVALID")
    expires = _timestamp(artifact.get("expires_at"), code="CHRONOS_PREFLIGHT_V2_INVALID")
    if expires - created != timedelta(hours=1):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    if now is not None:
        if now.tzinfo is None:
            raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
        observed_now = now.astimezone(UTC)
        if not created <= observed_now < expires:
            raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_INVALID")
    artifact["identity_seal"] = seal
    if signature is not None:
        artifact["signature"] = signature
    return artifact


def _identity_seal_readback(
    *,
    seal_path: Path,
    identity_path: Path,
    main_sha: str,
    identity_run_id: str,
    seal_run_id: str,
    store: ChronosR2ConditionalStore | None,
    effects: base.BootstrapEffects,
) -> dict[str, Any]:
    identity_bytes, identity = _read_json(identity_path, code="CHRONOS_IDENTITY_V2_INVALID")
    validated_identity = validate_neon_branch_identity_go_v2(identity, main_sha=main_sha)
    if cast(dict[str, Any], validated_identity["source"]).get("run_id") != identity_run_id:
        raise ChronosProductionError("CHRONOS_IDENTITY_V2_RUN_MISMATCH")
    _, seal = _read_json(seal_path, code="CHRONOS_IDENTITY_SEAL_V2_INVALID")
    validated_seal = validate_identity_seal_v2(
        seal,
        main_sha=main_sha,
        expected_identity_run_id=identity_run_id,
    )
    source = cast(dict[str, Any], validated_seal["source"])
    binding = cast(dict[str, Any], validated_seal["identity_go"])
    if source.get("run_id") != seal_run_id or hashlib.sha256(
        identity_bytes
    ).hexdigest() != binding.get("payload_sha256"):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_CAUSAL_MISMATCH")
    if effects.r2_operations != 0:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_SECOND_R2_GET_FORBIDDEN")
    effects.r2_operations = 1
    effects.r2_operations_exact = False
    validate_data_torrent_recovery_v2_authority(scale_stage="E3A")
    durable_store = store or ChronosR2ConditionalStore.from_environment(os.environ)
    try:
        observed = durable_store.get_object(cast(str, binding["durable_object_key"]))
    except Exception:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_R2_GET_AMBIGUOUS") from None
    effects.r2_operations_exact = True
    if (
        observed is None
        or observed.data != identity_bytes
        or observed.metadata != binding.get("durable_metadata")
        or hashlib.sha256(observed.data).hexdigest() != binding.get("payload_sha256")
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_R2_MISMATCH")
    return validated_seal


def run_preflight(
    report_dir: Path,
    identity_path: Path,
    seal_path: Path,
    *,
    store: ChronosR2ConditionalStore | None = None,
    effects: base.BootstrapEffects | None = None,
) -> dict[str, Any]:
    """Run exact seal GET, then PostgreSQL proof, then Neon recovery creation."""

    token = base._RECOVERY_V2_AUTHORITY_STAGE.set("E3A")
    try:
        validate_data_torrent_recovery_v2_authority(scale_stage="E3A")
        assert_production_safety_locks(os.environ)
        counters = _fresh_stage_effects(
            effects,
            postgresql_connection_attempts_maximum=4,
        )
        main_sha = require_sha(base._required_public("GITHUB_SHA"), field="main_sha")
        workflow_sha = require_sha(
            base._required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha"
        )
        run_id = base._required_public("GITHUB_RUN_ID")
        identity_run_id = base._required_public("CHRONOS_EXPECTED_IDENTITY_RUN_ID")
        seal_run_id = base._required_public("CHRONOS_EXPECTED_IDENTITY_SEAL_RUN_ID")
        if (
            base._required_public("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY
            or base._required_public("GITHUB_REF") != EXPECTED_REF
            or base._required_public("GITHUB_RUN_ATTEMPT") != "1"
            or any(
                _RUN_ID.fullmatch(value) is None for value in (run_id, identity_run_id, seal_run_id)
            )
            or main_sha
            != require_sha(
                base._required_public("CHRONOS_EXPECTED_MAIN_SHA"), field="expected_main_sha"
            )
        ):
            raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_SOURCE_INVALID")
        base._assert_bootstrap_dispatch_ordinal(
            mode="PREFLIGHT", main_sha=main_sha, workflow_file=WORKFLOW_FILE
        )
        hold = base._assert_hold()
        post_merge_ci = base._assert_post_merge_ci_binding(hold, main_sha=main_sha)
        identity_seal = _identity_seal_readback(
            seal_path=seal_path,
            identity_path=identity_path,
            main_sha=main_sha,
            identity_run_id=identity_run_id,
            seal_run_id=seal_run_id,
            store=store,
            effects=counters,
        )
        database_url = base._required("NEON_BOOTSTRAP_DATABASE_URL")
        target = validate_direct_postgres_url(database_url)
        counters.mark_sql_upper_bound(statements=128, writes=0)
        with base._connect_direct(database_url, effects=counters) as capability_connection:
            assert_privileged_catalog_visibility(capability_connection)
        database = base.inspect_database(database_url, effects=counters)
        with base._connect_direct(database_url, effects=counters) as connection:
            inventory_hash = role_inventory_hash(connection)
            inventory = role_inventory_snapshot(connection)
        revision = database.get("current_revision")
        if revision not in {*EXPECTED_BEFORE_REVISIONS, EXPECTED_AFTER_REVISION}:
            raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
        if revision == EXPECTED_AFTER_REVISION:
            base._assert_post_migration(database)
            with base._connect_direct(database_url, effects=counters) as connection:
                if (
                    base._scalar(connection, "SELECT version_num FROM public.alembic_version")
                    != EXPECTED_AFTER_REVISION
                ):
                    raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_REVISION_DRIFT")
        expected_connections = 4 if revision == EXPECTED_AFTER_REVISION else 3
        if counters.postgresql_connection_attempts != expected_connections:
            raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_POSTGRES_COUNT_INVALID")
        api_key = base._required("NEON_API_KEY")
        identity, neon = base.resolve_neon_identity(api_key, target, effects=counters)
        require_neon_recovery_feasibility(neon)
        client = base.NeonClient(api_key, effects=counters, maximum_gets=39, maximum_posts=1)
        recovery = base.create_recovery_point(
            client,
            identity,
            expected_branch_count=neon.target_project_branch_count,
            receipt_path=report_dir / "chronos-neon-recovery-point-v2.json",
        )
        if counters.neon_gets > 39 or counters.neon_posts != 1:
            raise ChronosProductionError("CHRONOS_PREFLIGHT_V2_NEON_BUDGET_INVALID")
        created_at = datetime.now(UTC)
        artifact: dict[str, Any] = {
            "schema_version": PREFLIGHT_SCHEMA,
            "main_sha": main_sha,
            "workflow_sha": workflow_sha,
            "project_id": identity.project_id,
            "production_branch_id": identity.production_branch_id,
            "current_revision": revision,
            "role_inventory_hash": inventory_hash,
            "role_inventory": {name: list(values) for name, values in inventory.items()},
            "recovery_branch_id": recovery["recovery_branch_id"],
            "recovery_branch_name": recovery["recovery_branch_name"],
            "golden_gate": "CHRONOS_MIGRATION_READY",
            "database_host": target.host,
            "database_port": target.port,
            "database_name": target.database,
            "sslmode": target.sslmode,
            "channel_binding": target.channel_binding,
            "created_at": base._timestamp(created_at),
            "expires_at": base._timestamp(created_at + timedelta(hours=1)),
            "preflight_run_id": run_id,
            "preflight_run_attempt": "1",
            "post_merge_ci_sha": post_merge_ci["head_sha"],
            "identity_run_id": identity_run_id,
            "seal_run_id": seal_run_id,
            "identity_seal": identity_seal,
            "effects": counters.snapshot(),
        }
        artifact["preflight_hash"] = preflight_hash(artifact)
        signed = sign_document(artifact, api_key)
        validate_preflight_artifact_v2(signed, main_sha=main_sha)
        base._write_json(report_dir / PREFLIGHT_FILENAME, signed)
        return signed
    finally:
        base._RECOVERY_V2_AUTHORITY_STAGE.reset(token)


def _binding_document(path: Path, *, artifact: Mapping[str, Any], main_sha: str) -> dict[str, Any]:
    _, binding = _read_json(path, code="CHRONOS_RUNTIME_BINDINGS_V2_INVALID")
    return validate_runtime_bindings_v2(
        binding,
        main_sha=main_sha,
        preflight_run_id=cast(str, artifact["preflight_run_id"]),
        preflight_artifact_hash=cast(str, artifact["preflight_hash"]),
        generation_nonce=base._required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
    )


def _fresh_stage_effects(
    effects: base.BootstrapEffects | None,
    *,
    postgresql_connection_attempts_maximum: int,
) -> base.BootstrapEffects:
    counters = (
        effects
        if effects is not None
        else base.BootstrapEffects(
            postgresql_connection_attempts_maximum=postgresql_connection_attempts_maximum
        )
    )
    if (
        counters.postgresql_connection_attempts_maximum
        != postgresql_connection_attempts_maximum
        or counters.r2_operations != 0
        or counters.neon_gets != 0
        or counters.neon_posts != 0
        or counters.postgresql_connection_attempts != 0
        or counters.recovery_branch_creations_upper_bound != 0
        or counters.migration_dispatches != 0
        or counters.sql_statements_upper_bound != 0
        or counters.sql_write_statements_upper_bound != 0
        or not counters.r2_operations_exact
        or not counters.neon_gets_exact
        or not counters.neon_posts_exact
        or not counters.postgresql_connection_attempts_exact
        or not counters.recovery_branch_creations_exact
        or not counters.migration_dispatches_exact
        or not counters.sql_statements_exact
        or not counters.sql_write_statements_exact
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_EFFECT_COUNTER_INVALID")
    return counters


def run_migrate(
    report_dir: Path,
    preflight_path: Path,
    binding_path: Path,
    *,
    effects: base.BootstrapEffects | None = None,
) -> dict[str, Any]:
    token = base._RECOVERY_V2_AUTHORITY_STAGE.set("E3B")
    try:

        def validate_chain(
            artifact: dict[str, Any], main_sha: str
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            validated = validate_preflight_artifact_v2(artifact, main_sha=main_sha)
            binding = _binding_document(binding_path, artifact=validated, main_sha=main_sha)
            seal = cast(dict[str, Any], validated["identity_seal"])
            return seal, binding

        counters = _fresh_stage_effects(
            effects,
            postgresql_connection_attempts_maximum=10,
        )
        return base.run_migrate(
            report_dir,
            preflight_path,
            effects=counters,
            recovery_v2=True,
            preflight_chain_validator=validate_chain,
        )
    finally:
        base._RECOVERY_V2_AUTHORITY_STAGE.reset(token)


def run_verify(
    report_dir: Path,
    migration_path: Path,
    *,
    effects: base.BootstrapEffects | None = None,
) -> dict[str, Any]:
    token = base._RECOVERY_V2_AUTHORITY_STAGE.set("E3B")
    try:

        def validate_chain(
            migration: dict[str, Any], main_sha: str
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            seal = migration.get("identity_seal")
            if not isinstance(seal, dict):
                raise ChronosProductionError("CHRONOS_MIGRATION_V2_CHAIN_INVALID")
            identity = seal.get("identity_go")
            if not isinstance(identity, dict) or not isinstance(identity.get("run_id"), str):
                raise ChronosProductionError("CHRONOS_MIGRATION_V2_CHAIN_INVALID")
            validated_seal = validate_identity_seal_v2(
                seal,
                main_sha=main_sha,
                expected_identity_run_id=cast(str, identity["run_id"]),
            )
            binding = validate_runtime_bindings_v2(
                migration.get("runtime_bindings"),
                main_sha=main_sha,
                preflight_run_id=cast(str, migration.get("preflight_run_id")),
                preflight_artifact_hash=cast(str, migration.get("preflight_hash")),
                generation_nonce=base._required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
            )
            return validated_seal, binding

        counters = _fresh_stage_effects(
            effects,
            postgresql_connection_attempts_maximum=4,
        )
        return base.run_verify(
            report_dir,
            migration_path,
            effects=counters,
            recovery_v2=True,
            migration_chain_validator=validate_chain,
        )
    finally:
        base._RECOVERY_V2_AUTHORITY_STAGE.reset(token)


def _contains_forbidden_export_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (
                not (
                    (str(key) == "secret_values_observed" and item is False)
                    or (str(key) == "password_null" and type(item) is bool)
                    or (str(key) == "secret_value_readbacks" and item == 0)
                )
                and any(part in str(key).lower() for part in _FORBIDDEN_EXPORT_KEY_PARTS)
            )
            or _contains_forbidden_export_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_export_key(item) for item in value)
    return False


def _supervisor_effects(mode: str) -> base.BootstrapEffects:
    maximum_connections = {"PREFLIGHT": 4, "MIGRATE": 10, "VERIFY": 4}[mode]
    effects = base.BootstrapEffects(
        postgresql_connection_attempts=maximum_connections,
        postgresql_connection_attempts_exact=False,
        postgresql_connection_attempts_maximum=maximum_connections,
    )
    effects.sql_statements_upper_bound = {"PREFLIGHT": 128, "MIGRATE": 2_048, "VERIFY": 128}[
        mode
    ]
    effects.sql_statements_exact = False
    if mode == "PREFLIGHT":
        effects.r2_operations = 1
        effects.r2_operations_exact = False
        effects.neon_gets = 39
        effects.neon_gets_exact = False
        effects.neon_posts = 1
        effects.neon_posts_exact = False
        effects.recovery_branch_creations_upper_bound = 1
        effects.recovery_branch_creations_exact = False
    elif mode == "MIGRATE":
        effects.neon_gets = 26
        effects.neon_gets_exact = False
        effects.migration_dispatches = 1
        effects.migration_dispatches_exact = False
        effects.sql_write_statements_upper_bound = 1_024
        effects.sql_write_statements_exact = False
    return effects


def _supervisor_fallback(mode: str) -> dict[str, Any]:
    effects = _supervisor_effects(mode)
    failure = base._safe_failure(
        mode,
        ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_AMBIGUOUS"),
        effects,
    )
    failure.update(
        {
            "schema_version": "chronos-production-recovery-supervisor-failure-v2",
            "failure_class": "TRANSPORT_AMBIGUOUS",
            "effect_counter_certainty": "UNKNOWN_OR_UPPER_BOUND",
        }
    )
    return failure


def _validate_failure_export(document: dict[str, Any], *, mode: str) -> dict[str, Any]:
    ordinary = set(document) == {
        "schema_version",
        "mode",
        "status",
        "error_code",
        "secret_values_observed",
        "provider_calls",
        "odds_credits",
        "r2_operations",
        "effects",
        "purchases",
    } and document.get("schema_version") == "chronos-production-recovery-failure-v2"
    supervised = set(document) == {
        "schema_version",
        "mode",
        "status",
        "error_code",
        "secret_values_observed",
        "provider_calls",
        "odds_credits",
        "r2_operations",
        "effects",
        "purchases",
        "failure_class",
        "effect_counter_certainty",
    } and (
        document.get("schema_version")
        == "chronos-production-recovery-supervisor-failure-v2"
        and document.get("failure_class") == "TRANSPORT_AMBIGUOUS"
        and document.get("effect_counter_certainty") == "UNKNOWN_OR_UPPER_BOUND"
    )
    effects = document.get("effects")
    expected_maxima = _supervisor_effects(mode).snapshot()
    if (
        not (ordinary or supervised)
        or document.get("mode") != mode
        or document.get("status") != "FAILED"
        or not isinstance(document.get("error_code"), str)
        or _SAFE_FAILURE_CODE.fullmatch(cast(str, document["error_code"])) is None
        or (
            supervised
            and document.get("error_code")
            != "CHRONOS_RECOVERY_V2_SUPERVISOR_AMBIGUOUS"
        )
        or document.get("secret_values_observed") is not False
        or any(
            type(document.get(field)) is not int
            for field in {"provider_calls", "odds_credits", "r2_operations", "purchases"}
        )
        or document.get("provider_calls") != 0
        or document.get("odds_credits") != 0
        or document.get("purchases") != 0
        or not isinstance(effects, dict)
        or set(effects) != set(expected_maxima)
        or effects.get("automatic_retries") != 0
        or effects.get("provider_calls") != 0
        or effects.get("purchases") != 0
        or effects.get("secret_values_observed") is not False
        or document.get("r2_operations") != effects.get("r2_gets")
        or effects.get("r2_puts") != 0
        or effects.get("effect_counter_certainty")
        not in {"EXACT_DISPATCH_ACCOUNTING", "CONSERVATIVE_UPPER_BOUNDS"}
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    integer_fields = {
        "r2_gets",
        "r2_puts",
        "neon_gets",
        "neon_posts",
        "postgresql_connection_attempts",
        "recovery_branch_creations_upper_bound",
        "migration_dispatches",
        "sql_statements_upper_bound",
        "sql_write_statements_upper_bound",
        "automatic_retries",
        "provider_calls",
        "purchases",
    }
    if any(
        type(effects.get(field)) is not int
        or not 0 <= cast(int, effects[field]) <= cast(int, expected_maxima[field])
        for field in integer_fields
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    exactness_fields = {
        "r2_gets_exact",
        "neon_gets_exact",
        "neon_posts_exact",
        "postgresql_connection_attempts_exact",
        "recovery_branch_creations_exact",
        "migration_dispatches_exact",
        "sql_statements_exact",
        "sql_write_statements_exact",
    }
    if any(type(effects.get(field)) is not bool for field in exactness_fields):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    if supervised and effects != expected_maxima:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    return document


def _load_supervised_export(path: Path, *, mode: str) -> dict[str, Any]:
    payload, document = _read_json(path, code="CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    if len(payload) > 1_048_576 or _contains_forbidden_export_key(document):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    if document.get("status") == "FAILED":
        return _validate_failure_export(document, mode=mode)
    expected_main_sha = require_sha(base._required_public("GITHUB_SHA"), field="main_sha")
    signing_key = (
        base._required("NEON_API_KEY")
        if mode == "PREFLIGHT"
        else base._required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE")
    )
    unsigned = verify_signed_document(document, signing_key)
    if mode == "PREFLIGHT":
        validate_preflight_artifact_v2(unsigned, main_sha=expected_main_sha)
    elif mode == "MIGRATE":
        from scripts.dispatch_data_torrent_recovery_v2_stage import (
            _validate_migration_artifact,
        )

        _validate_migration_artifact(
            document,
            main_sha=expected_main_sha,
            migration_run_id=base._required_public("GITHUB_RUN_ID"),
            generation_nonce=signing_key,
        )
    else:
        from scripts.dispatch_data_torrent_recovery_v2_stage import _validate_verify_artifact

        seal = unsigned.get("identity_seal")
        identity_go = seal.get("identity_go") if isinstance(seal, dict) else None
        identity_run_id = identity_go.get("run_id") if isinstance(identity_go, dict) else None
        if not isinstance(identity_run_id, str):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
        _validate_verify_artifact(
            document,
            main_sha=expected_main_sha,
            verify_run_id=base._required_public("GITHUB_RUN_ID"),
            identity_run_id=identity_run_id,
            expected_generation_hash=generation_hash(signing_key),
            generation_nonce=signing_key,
        )
    if (
        unsigned.get("schema_version") != _SUPERVISED_SUCCESS_SCHEMAS[mode]
        or unsigned.get("main_sha") != expected_main_sha
        or unsigned.get("workflow_sha") != expected_main_sha
        or unsigned.get("post_merge_ci_sha") != expected_main_sha
        or not isinstance(unsigned.get("effects"), dict)
        or cast(dict[str, object], unsigned["effects"]).get("automatic_retries") != 0
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    return document


def _supervise(args: argparse.Namespace) -> int:
    output_path = args.report_dir / _SUPERVISED_FILENAMES[args.mode]
    fallback_sha256 = adopt_or_create_json_fallback(
        output_path,
        _supervisor_fallback(args.mode),
    )
    with tempfile.TemporaryDirectory(
        prefix=f".{args.mode.casefold()}-v2-candidate-",
        dir=args.report_dir,
    ) as raw:
        candidate_dir = Path(raw)
        command = [
            sys.executable,
            "-m",
            "scripts.chronos_production_recovery_v2",
            "--mode",
            args.mode,
            "--report-dir",
            str(candidate_dir),
        ]
        for option, value in (
            ("--identity-artifact", args.identity_artifact),
            ("--seal-artifact", args.seal_artifact),
            ("--preflight-artifact", args.preflight_artifact),
            ("--bindings-receipt", args.bindings_receipt),
            ("--migration-artifact", args.migration_artifact),
        ):
            if value is not None:
                command.extend((option, str(value)))
        timeout_seconds = remaining_effect_timeout(_SUPERVISOR_TIMEOUT_SECONDS)
        if timeout_seconds == 0:
            return SUPERVISOR_TIMEOUT_EXIT
        return_code = run_child_once(command, timeout_seconds=timeout_seconds)
        if return_code in {
            SUPERVISOR_TIMEOUT_EXIT,
            SUPERVISOR_EXPORT_EXIT,
            SUPERVISOR_CHILD_STUCK_EXIT,
        }:
            return return_code
        if return_code < 0:
            return return_code
        try:
            def validate_candidate(path: Path) -> dict[str, Any]:
                candidate_report = _load_supervised_export(path, mode=args.mode)
                success = (
                    candidate_report.get("schema_version")
                    == _SUPERVISED_SUCCESS_SCHEMAS[args.mode]
                )
                if success is not (return_code == 0):
                    raise ChronosProductionError(
                        "CHRONOS_RECOVERY_V2_SUPERVISOR_EXPORT_INVALID"
                    )
                return candidate_report

            validated = promote_validated_file(
                candidate_dir / _SUPERVISED_FILENAMES[args.mode],
                output_path,
                expected_fallback_sha256=fallback_sha256,
                validator=validate_candidate,
            )
        except (ChronosProductionError, RecoveryV2SupervisionError):
            return SUPERVISOR_EXPORT_EXIT
        if (
            validated.get("schema_version") == _SUPERVISED_SUCCESS_SCHEMAS[args.mode]
        ) is not (return_code == 0):
            return SUPERVISOR_EXPORT_EXIT
        return return_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("PREFLIGHT", "MIGRATE", "VERIFY"), required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--identity-artifact", type=Path)
    parser.add_argument("--seal-artifact", type=Path)
    parser.add_argument("--preflight-artifact", type=Path)
    parser.add_argument("--bindings-receipt", type=Path)
    parser.add_argument("--migration-artifact", type=Path)
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    if getattr(args, "supervise", False):
        return _supervise(args)
    maximum_connections = {"PREFLIGHT": 4, "MIGRATE": 10, "VERIFY": 4}[args.mode]
    effects = base.BootstrapEffects(
        postgresql_connection_attempts_maximum=maximum_connections
    )
    output_path = args.report_dir / {
        "PREFLIGHT": PREFLIGHT_FILENAME,
        "MIGRATE": "chronos-production-migrate-v2.json",
        "VERIFY": "chronos-production-verify-v2.json",
    }[args.mode]
    try:
        if args.mode == "PREFLIGHT" and args.identity_artifact and args.seal_artifact:
            result = run_preflight(
                args.report_dir,
                args.identity_artifact,
                args.seal_artifact,
                effects=effects,
            )
        elif args.mode == "MIGRATE" and args.preflight_artifact and args.bindings_receipt:
            result = run_migrate(
                args.report_dir,
                args.preflight_artifact,
                args.bindings_receipt,
                effects=effects,
            )
        elif args.mode == "VERIFY" and args.migration_artifact:
            result = run_verify(
                args.report_dir,
                args.migration_artifact,
                effects=effects,
            )
        else:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_INPUT_MISSING")
    except Exception as error:
        failure = base._safe_failure(args.mode, error, effects)
        failure["schema_version"] = "chronos-production-recovery-failure-v2"
        base._write_json(output_path, failure)
        return 1
    print(result.get("verdict", result.get("schema_version")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
