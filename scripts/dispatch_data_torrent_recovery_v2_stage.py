"""Fail-closed Recovery V2 controller gate for one workflow cycle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import multiprocessing
import os
import re
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    DATA_TORRENT_RECOVERY_V2_START_SHA,
    EXPECTED_REPOSITORY,
    SCOPED_LOGINS,
    ChronosProductionError,
    DirectPostgresTarget,
    _recovery_v2_evidence_bytes,
    _recovery_v2_path_is_reparse,
    _recovery_v2_prepare_repository_directory,
    _recovery_v2_publish_exclusive_bytes,
    _recovery_v2_read_bytes,
    _recovery_v2_replace_bytes,
    _recovery_v2_require_repository_file,
    _recovery_v2_require_unused_repository_output,
    assert_production_safety_locks,
    generation_hash,
    require_hash,
    require_sha,
    validate_data_torrent_recovery_v2_authority,
    validate_data_torrent_recovery_v2_council_release,
    validate_identity_seal_v2,
    validate_neon_branch_identity_go_v2,
    validate_runtime_bindings_v2,
    verify_signed_document,
)
from robin.chronos_role_lifecycle import EXECUTOR_TOMBSTONE_MARKER
from scripts.check_chronos_github_hold_v3 import (
    GITHUB_GET_TOTAL_TIMEOUT_SECONDS,
    RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS,
    RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS,
    _github_get,
    verify_hold,
)
from scripts.chronos_production_recovery_v2 import validate_preflight_artifact_v2
from scripts.github_release_attestation_v2 import (
    attest_and_download_bundle_v2,
    attest_and_download_failure_v2,
    attest_and_download_v2,
)
from scripts.recovery_v2_supervision import (
    CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS,
    RecoveryV2SupervisionError,
    run_captured_child_once,
)

_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_EFFECT_DEADLINE_EPOCH = re.compile(r"^[1-9][0-9]{9,11}$")
_DISPATCH_NONCE = re.compile(r"^[0-9a-f]{64}$")
_DISPATCH_EFFECT_DEADLINE_INPUT = "recovery_v2_effect_deadline_epoch"
_DISPATCH_NONCE_INPUT = "recovery_v2_dispatch_nonce"
_DISPATCH_BINDING_FIELDS = {
    _DISPATCH_EFFECT_DEADLINE_INPUT,
    _DISPATCH_NONCE_INPUT,
}
_SAFE_NEON_ID = re.compile(r"^[a-z0-9-]{1,60}$")
_MAX_INPUT_BYTES = 128 * 1024
_MUTATION_TOTAL_TIMEOUT_SECONDS = 15.0
_MUTATION_WORK_TIMEOUT_SECONDS = 11.0
_MUTATION_TERMINATE_TIMEOUT_SECONDS = 2.0
_MAX_MUTATION_RESPONSE_BYTES = 64 * 1024
_GIT_COMMAND_TIMEOUT_SECONDS = 60
_GIT_OUTPUT_LIMIT_BYTES = 65_536
_LOCAL_E1_STAGE_TIMEOUT_SECONDS = 5 * 60
_API_ROOT = "https://api.github.com"
_ENVIRONMENT = "chronos-control-plane-production"
_REPOSITORY_ROOT = Path(os.path.abspath(Path(__file__))).parents[1]
_BINDINGS_RECEIPT = _REPOSITORY_ROOT / ".torrent" / "release" / "chronos-runtime-bindings-v2.json"
_PREDECESSOR_CACHE_ROOT = (
    _REPOSITORY_ROOT / ".torrent" / "release" / "recovery-v2-predecessor-cache"
)
_LIVE_BUNDLE_CACHE_PATH = (
    _REPOSITORY_ROOT / ".torrent" / "release" / "recovery-v2-live-bundle-cache.json"
)
_PREDECESSOR_CACHE_SLUGS = {
    "IDENTITY": "recovery-identity-v2",
    "IDENTITY_SEAL": "durable-identity-seal-v2",
    "PREFLIGHT": "production-preflight-v2",
    "MIGRATION": "migrate-0015",
    "VERIFY": "verify-0015",
}
_LEGACY_PROVIDER_BRANCH = "codex/jalon-12-prospective-deep-data-observatory"
_LEGACY_PROVIDER_REF = f"refs/heads/{_LEGACY_PROVIDER_BRANCH}"
_EXPECTED_PUSH_URL = "https://github.com/dddur75/robin-stades-ng.git"
_QUARANTINE_WORKFLOWS = tuple(sorted(RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS))
_BOOTSTRAP_EFFECT_FIELDS = {
    "effect_counter_certainty",
    "r2_gets",
    "r2_gets_exact",
    "r2_puts",
    "neon_gets",
    "neon_gets_exact",
    "neon_posts",
    "neon_posts_exact",
    "postgresql_connection_attempts",
    "postgresql_connection_attempts_exact",
    "recovery_branch_creations_upper_bound",
    "recovery_branch_creations_exact",
    "migration_dispatches",
    "migration_dispatches_exact",
    "sql_statements_upper_bound",
    "sql_statements_exact",
    "sql_write_statements_upper_bound",
    "sql_write_statements_exact",
    "automatic_retries",
    "provider_calls",
    "purchases",
    "secret_values_observed",
}
_BOOTSTRAP_INTEGER_FIELDS = {
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
_RECOVERY_HOLD_FIELDS = {
    "schema_version",
    "verdict",
    "active_after",
    "disabled_after",
    "queued_after",
    "in_progress_after",
    "nonterminal_run_counts",
    "current_run_excluded",
    "unauthorized_active_workflows",
    "post_merge_ci",
    "recovery_v2_scope_guard",
    "legacy_secret_branch_sha",
    "legacy_ci_workflow_quarantine",
    "recovery_v2_production_workflow_quarantine",
    "production_environment_policy",
    "provider_calls",
    "r2_operations",
}

STAGES: dict[str, dict[str, object]] = {
    "RECOVERY_IDENTITY_V2": {
        "scale_stage": "E2",
        "workflow": "chronos-neon-branch-identity-v2.yml",
        "inputs": {"expected_main_sha"},
        "expected_prior_dispatches": 0,
    },
    "DURABLE_IDENTITY_SEAL_V2": {
        "scale_stage": "E2",
        "workflow": "chronos-identity-seal-v2.yml",
        "inputs": {"expected_main_sha", "identity_run_id"},
        "expected_prior_dispatches": 0,
    },
    "PRODUCTION_PREFLIGHT_V2": {
        "scale_stage": "E3A",
        "workflow": "chronos-production-bootstrap-v4.yml",
        "mode": "PREFLIGHT",
        "inputs": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "identity_run_id",
            "seal_run_id",
        },
        "expected_prior_dispatches": 0,
    },
    "MIGRATE_0015": {
        "scale_stage": "E3B",
        "workflow": "chronos-production-bootstrap-v4.yml",
        "mode": "MIGRATE",
        "inputs": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "preflight_run_id",
            "runtime_bindings_receipt_b64",
        },
        "expected_prior_dispatches": 1,
    },
    "VERIFY_0015": {
        "scale_stage": "E3B",
        "workflow": "chronos-production-bootstrap-v4.yml",
        "mode": "VERIFY",
        "inputs": {
            "mode",
            "expected_main_sha",
            "post_merge_ci_sha",
            "migration_run_id",
        },
        "expected_prior_dispatches": 2,
    },
    "LIVE_ONCE": {
        "scale_stage": "E4",
        "workflow": "data-torrent-live-v2.yml",
        "inputs": {
            "expected_main_sha",
            "expected_workflow_sha256",
            "expected_mission_manifest_sha256",
            "expected_generation_hash",
            "post_merge_ci_sha",
            "identity_run_id",
            "verify_run_id",
        },
        "expected_prior_dispatches": 0,
    },
}

_PREDECESSORS: dict[str, dict[str, str]] = {
    "DURABLE_IDENTITY_SEAL_V2": {
        "run_id_field": "identity_run_id",
        "workflow_path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
        "artifact_prefix": "neon-branch-identity-go-v2-",
        "artifact_filename": "neon-branch-identity-go-v2.json",
        "kind": "IDENTITY",
    },
    "PRODUCTION_PREFLIGHT_V2": {
        "run_id_field": "seal_run_id",
        "workflow_path": ".github/workflows/chronos-identity-seal-v2.yml",
        "artifact_prefix": "durable-identity-seal-v2-",
        "artifact_filename": "durable-identity-seal-v2.json",
        "kind": "IDENTITY_SEAL",
    },
    "MIGRATE_0015": {
        "run_id_field": "preflight_run_id",
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "production-preflight-v2-",
        "artifact_filename": "production-preflight-v2.json",
        "kind": "PREFLIGHT",
    },
    "VERIFY_0015": {
        "run_id_field": "migration_run_id",
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "chronos-production-migrate-v2-",
        "artifact_filename": "chronos-production-migrate-v2.json",
        "kind": "MIGRATION",
    },
    "LIVE_ONCE": {
        "run_id_field": "verify_run_id",
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "chronos-production-verify-v2-",
        "artifact_filename": "chronos-production-verify-v2.json",
        "kind": "VERIFY",
    },
}
_PREDECESSOR_SEMANTIC_VERDICTS = {
    "DURABLE_IDENTITY_SEAL_V2": "NEON_BRANCH_IDENTITY_GO_V2",
    "PRODUCTION_PREFLIGHT_V2": "DURABLE_IDENTITY_SEAL_V2",
    "MIGRATE_0015": "CHRONOS_MIGRATION_READY",
    "VERIFY_0015": "MIGRATE_0015_COMPLETE_V2",
    "LIVE_ONCE": "VERIFY_0015_COMPLETE_V2",
}
_SUCCESS_ARTIFACTS: dict[str, dict[str, str]] = {
    "RECOVERY_IDENTITY_V2": {
        "workflow_path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
        "artifact_prefix": "neon-branch-identity-go-v2-",
        "artifact_filename": "neon-branch-identity-go-v2.json",
        "kind": "IDENTITY",
        "semantic_verdict": "NEON_BRANCH_IDENTITY_GO_V2",
    },
    "DURABLE_IDENTITY_SEAL_V2": {
        "workflow_path": ".github/workflows/chronos-identity-seal-v2.yml",
        "artifact_prefix": "durable-identity-seal-v2-",
        "artifact_filename": "durable-identity-seal-v2.json",
        "kind": "IDENTITY_SEAL",
        "semantic_verdict": "DURABLE_IDENTITY_SEAL_V2",
    },
    "PRODUCTION_PREFLIGHT_V2": {
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "production-preflight-v2-",
        "artifact_filename": "production-preflight-v2.json",
        "kind": "PREFLIGHT",
        "semantic_verdict": "CHRONOS_MIGRATION_READY",
    },
    "MIGRATE_0015": {
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "chronos-production-migrate-v2-",
        "artifact_filename": "chronos-production-migrate-v2.json",
        "kind": "MIGRATION",
        "semantic_verdict": "MIGRATE_0015_COMPLETE_V2",
    },
    "VERIFY_0015": {
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "artifact_prefix": "chronos-production-verify-v2-",
        "artifact_filename": "chronos-production-verify-v2.json",
        "kind": "VERIFY",
        "semantic_verdict": "VERIFY_0015_COMPLETE_V2",
    },
}
_STAGE_TIMEOUT_SECONDS = {
    "RECOVERY_IDENTITY_V2": 10 * 60,
    "DURABLE_IDENTITY_SEAL_V2": 10 * 60,
    "PRODUCTION_PREFLIGHT_V2": 15 * 60,
    "MIGRATE_0015": 15 * 60,
    "VERIFY_0015": 15 * 60,
    "LIVE_ONCE": 20 * 60,
}
_POST_EFFECT_WORKFLOW_TERMINAL_GRACE_SECONDS = {
    "RECOVERY_IDENTITY_V2": 10 * 60 + 30,
    "DURABLE_IDENTITY_SEAL_V2": 10 * 60 + 30,
    "PRODUCTION_PREFLIGHT_V2": 15 * 60 + 30,
    "MIGRATE_0015": 15 * 60 + 30,
    "VERIFY_0015": 15 * 60 + 30,
    "LIVE_ONCE": 20 * 60 + 30,
}
_TERMINAL_RUN_OBSERVATIONS_MAXIMUM = 3
_TERMINAL_ATTESTATION_RESERVE_SECONDS = 210.0
_NONTERMINAL_RUN_STATUSES = {"requested", "waiting", "pending", "queued", "in_progress"}
_AUTHORIZED_MUTATIONS = frozenset(
    (method, f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/{workflow}/{suffix}")
    for workflow in {cast(str, contract["workflow"]) for contract in STAGES.values()}
    for method, suffix in (("PUT", "enable"), ("POST", "dispatches"), ("PUT", "disable"))
)


class RecoveryV2ControllerError(RuntimeError):
    """Sanitized terminal controller failure; a cycle is never retried."""


def _operation_deadline_epoch(
    authority_deadline: datetime,
    *,
    maximum_runtime_seconds: float,
    observed_epoch: float | None = None,
) -> float:
    if (
        not isinstance(authority_deadline, datetime)
        or authority_deadline.tzinfo is None
        or isinstance(maximum_runtime_seconds, bool)
        or not isinstance(maximum_runtime_seconds, (int, float))
        or not math.isfinite(float(maximum_runtime_seconds))
        or maximum_runtime_seconds <= 0
        or (
            observed_epoch is not None
            and (
                isinstance(observed_epoch, bool)
                or not isinstance(observed_epoch, (int, float))
                or not math.isfinite(float(observed_epoch))
            )
        )
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID")
    observed = time.time() if observed_epoch is None else float(observed_epoch)
    deadline = min(
        authority_deadline.astimezone(UTC).timestamp(),
        observed + float(maximum_runtime_seconds),
    )
    if deadline <= observed:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED")
    return deadline


def _stage_operation_deadlines_epoch(
    authority_deadline: datetime,
    *,
    stage: str,
    now_epoch: float | None = None,
) -> tuple[int, int]:
    """Return an effect cutoff and a later read-only terminalization cutoff."""

    if stage not in _STAGE_TIMEOUT_SECONDS or not isinstance(authority_deadline, datetime):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID")
    if authority_deadline.tzinfo is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID")
    observed = time.time() if now_epoch is None else now_epoch
    if (
        isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not math.isfinite(float(observed))
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID")
    effect_runtime = min(1_200, _STAGE_TIMEOUT_SECONDS[stage])
    workflow_terminal_grace = _POST_EFFECT_WORKFLOW_TERMINAL_GRACE_SECONDS[stage]
    authority_epoch = authority_deadline.astimezone(UTC).timestamp()
    effect_deadline = math.floor(
        min(
            float(observed) + effect_runtime,
            authority_epoch
            - workflow_terminal_grace
            - _TERMINAL_ATTESTATION_RESERVE_SECONDS,
        )
    )
    terminalization_deadline = math.floor(
        effect_deadline
        + workflow_terminal_grace
        + _TERMINAL_ATTESTATION_RESERVE_SECONDS
    )
    if (
        effect_deadline <= float(observed)
        or terminalization_deadline > authority_epoch
        or terminalization_deadline <= effect_deadline
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED")
    return effect_deadline, terminalization_deadline


def _require_effect_window(
    effect_deadline_epoch: float,
    *,
    margin_seconds: float = 0.0,
    observed_epoch: float | None = None,
) -> float:
    if (
        isinstance(effect_deadline_epoch, bool)
        or not isinstance(effect_deadline_epoch, (int, float))
        or not math.isfinite(float(effect_deadline_epoch))
        or isinstance(margin_seconds, bool)
        or not isinstance(margin_seconds, (int, float))
        or not math.isfinite(float(margin_seconds))
        or margin_seconds < 0
        or (
            observed_epoch is not None
            and (
                isinstance(observed_epoch, bool)
                or not isinstance(observed_epoch, (int, float))
                or not math.isfinite(float(observed_epoch))
            )
        )
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_INVALID")
    observed = time.time() if observed_epoch is None else float(observed_epoch)
    remaining = float(effect_deadline_epoch) - observed
    if remaining <= float(margin_seconds):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED")
    return remaining


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _validate_inputs(
    *,
    stage: str,
    main_sha: str,
    inputs: object,
    require_dispatch_binding: bool | None = None,
) -> dict[str, str]:
    contract = STAGES[stage]
    business_fields = cast(set[str], contract["inputs"])
    bound_fields = business_fields | _DISPATCH_BINDING_FIELDS
    observed_fields = set(inputs) if isinstance(inputs, dict) else set()
    expected_fields = (
        bound_fields
        if require_dispatch_binding is True
        else business_fields
        if require_dispatch_binding is False
        else observed_fields
    )
    if (
        not isinstance(inputs, dict)
        or observed_fields != expected_fields
        or (
            require_dispatch_binding is None
            and observed_fields not in (business_fields, bound_fields)
        )
        or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in inputs.items()
        )
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    values = cast(dict[str, str], dict(inputs))
    if values.get("expected_main_sha") != main_sha:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    if "post_merge_ci_sha" in values and values["post_merge_ci_sha"] != main_sha:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    expected_mode = contract.get("mode")
    if expected_mode is not None and values.get("mode") != expected_mode:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    for name, value in values.items():
        if name.endswith("_run_id") and _RUN_ID.fullmatch(value) is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
        if name.endswith("_sha256"):
            try:
                require_hash(value, field=name)
            except ChronosProductionError:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID") from None
    if "expected_generation_hash" in values:
        try:
            require_hash(values["expected_generation_hash"], field="expected_generation_hash")
        except ChronosProductionError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID") from None
    if observed_fields == bound_fields:
        deadline_text = values.get(_DISPATCH_EFFECT_DEADLINE_INPUT, "")
        nonce = values.get(_DISPATCH_NONCE_INPUT, "")
        if (
            _EFFECT_DEADLINE_EPOCH.fullmatch(deadline_text) is None
            or int(deadline_text) > 253_402_300_799
            or _DISPATCH_NONCE.fullmatch(nonce) is None
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    receipt = values.get("runtime_bindings_receipt_b64")
    if receipt is not None:
        try:
            decoded = base64.b64decode(receipt, validate=True)
        except ValueError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID") from None
        if not decoded or len(decoded) > 64 * 1024:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    if stage == "LIVE_ONCE":
        workflow_path = _REPOSITORY_ROOT / ".github" / "workflows" / "data-torrent-live-v2.yml"
        try:
            workflow_bytes = _recovery_v2_evidence_bytes(
                workflow_path,
                repository_root=_REPOSITORY_ROOT,
                maximum_bytes=1024 * 1024,
            )
        except ChronosProductionError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID") from None
        if (
            not workflow_bytes
            or len(workflow_bytes) > 1024 * 1024
            or values.get("expected_workflow_sha256") != hashlib.sha256(workflow_bytes).hexdigest()
            or values.get("expected_mission_manifest_sha256")
            != DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_INPUT_INVALID")
    return values


def _inputs_sha256(inputs: Mapping[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(dict(inputs), separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _object_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _require_utc_instant(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("not a UTC instant")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("not a UTC instant")
    return value


def _validate_migration_target(document: Mapping[str, object]) -> None:
    text_fields = (
        "database_host",
        "database_name",
        "sslmode",
        "channel_binding",
        "authority_username",
        "runtime_username",
        "reader_username",
        "project_id",
        "production_branch_id",
        "recovery_branch_id",
    )
    if any(not isinstance(document.get(field), str) for field in text_fields):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
    expected_logins = [login for login, _group, _secret in SCOPED_LOGINS]
    identifiers = [
        cast(str, document["project_id"]),
        cast(str, document["production_branch_id"]),
        cast(str, document["recovery_branch_id"]),
    ]
    if (
        type(document.get("database_port")) is not int
        or [
            document.get("authority_username"),
            document.get("runtime_username"),
            document.get("reader_username"),
        ]
        != expected_logins
        or any(_SAFE_NEON_ID.fullmatch(identifier) is None for identifier in identifiers)
        or identifiers[1] == identifiers[2]
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
    try:
        DirectPostgresTarget(
            host=cast(str, document["database_host"]),
            port=cast(int, document["database_port"]),
            database=cast(str, document["database_name"]),
            username="bootstrap-placeholder",
            sslmode=cast(str, document["sslmode"]),
            channel_binding=cast(str, document["channel_binding"]),
        )
        _require_utc_instant(document.get("server_epoch"))
    except (ChronosProductionError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID") from None


def _strict_json_document(path: Path, *, maximum_bytes: int) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = _recovery_v2_evidence_bytes(
            path,
            repository_root=_REPOSITORY_ROOT,
            maximum_bytes=maximum_bytes,
        )
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (ChronosProductionError, UnicodeDecodeError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    if not payload or len(payload) > maximum_bytes or not isinstance(document, dict):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    return payload, cast(dict[str, Any], document)


def _generation_nonce() -> str:
    value = os.getenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", "")
    try:
        return require_hash(value, field="generation_nonce")
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_GENERATION_NONCE_INVALID") from None


def _validate_local_runtime_bindings(
    *,
    encoded_receipt: str,
    main_sha: str,
    preflight_run_id: str,
    preflight_hash: str,
    preflight_controller_receipt_sha256: str,
    generation_nonce: str,
) -> dict[str, Any]:
    try:
        encoded_bytes = encoded_receipt.encode("ascii")
        decoded = base64.b64decode(encoded_bytes, validate=True)
    except (UnicodeEncodeError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_BINDINGS_INVALID") from None
    local_bytes, document = _strict_json_document(_BINDINGS_RECEIPT, maximum_bytes=64 * 1024)
    if not hmac.compare_digest(local_bytes, decoded):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_BINDINGS_INVALID")
    try:
        validated = validate_runtime_bindings_v2(
            document,
            main_sha=main_sha,
            preflight_run_id=preflight_run_id,
            preflight_artifact_hash=preflight_hash,
            generation_nonce=generation_nonce,
        )
        if not hmac.compare_digest(
            cast(str, validated["preflight_controller_receipt_sha256"]),
            preflight_controller_receipt_sha256,
        ):
            raise ChronosProductionError("CHRONOS_RUNTIME_BINDINGS_V2_INVALID")
        return validated
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_BINDINGS_INVALID") from None


def _validate_exact_runtime_bindings(
    *,
    encoded_receipt: str | None,
    main_sha: str,
    preflight_run_id: str,
    preflight_artifact_hash: str,
    preflight_controller_receipt_sha256: str | None = None,
    generation_nonce: str,
) -> dict[str, Any]:
    if encoded_receipt is not None:
        if preflight_controller_receipt_sha256 is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_BINDINGS_INVALID")
        return _validate_local_runtime_bindings(
            encoded_receipt=encoded_receipt,
            main_sha=main_sha,
            preflight_run_id=preflight_run_id,
            preflight_hash=preflight_artifact_hash,
            preflight_controller_receipt_sha256=(
                preflight_controller_receipt_sha256
            ),
            generation_nonce=generation_nonce,
        )
    _payload, document = _strict_json_document(_BINDINGS_RECEIPT, maximum_bytes=64 * 1024)
    try:
        return validate_runtime_bindings_v2(
            document,
            main_sha=main_sha,
            preflight_run_id=preflight_run_id,
            preflight_artifact_hash=preflight_artifact_hash,
            generation_nonce=generation_nonce,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_BINDINGS_INVALID") from None


def _validate_migration_artifact(
    document: dict[str, Any],
    *,
    main_sha: str,
    migration_run_id: str,
    generation_nonce: str,
    expected_preflight: Mapping[str, object] | None = None,
    expected_runtime_bindings: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    try:
        migration = verify_signed_document(document, generation_nonce)
        preflight_hash = require_hash(
            str(migration.get("preflight_hash", "")), field="preflight_hash"
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID") from None
    expected_fields = {
        "schema_version",
        "database_host",
        "database_port",
        "database_name",
        "sslmode",
        "channel_binding",
        "authority_username",
        "runtime_username",
        "reader_username",
        "non_secret_generation_id",
        "generation_hash",
        "server_epoch",
        "revision",
        "migration_dispatches",
        "migration_outcome",
        "project_id",
        "production_branch_id",
        "recovery_branch_id",
        "main_sha",
        "workflow_sha",
        "post_merge_ci_sha",
        "preflight_run_id",
        "preflight_hash",
        "migration_run_id",
        "migration_run_attempt",
        "effects",
        "identity_seal",
        "runtime_bindings",
        "bootstrap_executor_terminal",
    }
    effects = migration.get("effects")
    preflight_run_id = migration.get("preflight_run_id")
    identity_seal = migration.get("identity_seal")
    identity_go = identity_seal.get("identity_go") if isinstance(identity_seal, dict) else None
    identity_run_id = identity_go.get("run_id") if isinstance(identity_go, dict) else None
    dispatch_count = migration.get("migration_dispatches")
    expected_generation_hash = generation_hash(generation_nonce)
    expected_terminal = {
        "schema_version": "chronos-bootstrap-executor-terminal-v2",
        "executor_role": "chronos_bootstrap_executor_recoveryv2",
        "state": "NEUTRALIZED",
        "marker": EXECUTOR_TOMBSTONE_MARKER,
        "can_login": False,
        "inherit": False,
        "password_null": True,  # nosec B105
        "valid_until_epoch": True,
        "connection_limit": 0,
        "membership_count": 0,
        "session_count": 0,
        "effective_chronos_privilege_count": 0,
    }
    if (
        set(migration) != expected_fields
        or migration.get("schema_version") != "chronos-production-migrate-v2"
        or migration.get("main_sha") != main_sha
        or migration.get("workflow_sha") != main_sha
        or migration.get("post_merge_ci_sha") != main_sha
        or migration.get("migration_run_id") != migration_run_id
        or migration.get("migration_run_attempt") != "1"
        or migration.get("revision") != "0015_data_torrent_opportunity"
        or migration.get("generation_hash") != expected_generation_hash
        or migration.get("non_secret_generation_id") != expected_generation_hash[:16]
        or type(dispatch_count) is not int
        or dispatch_count not in {0, 1}
        or migration.get("migration_outcome")
        != {0: "MIGRATION_RESUMED", 1: "MIGRATION_CONFIRMED"}.get(dispatch_count)
        or not isinstance(preflight_run_id, str)
        or _RUN_ID.fullmatch(preflight_run_id) is None
        or not isinstance(migration.get("bootstrap_executor_terminal"), dict)
        or any(
            type(cast(dict[str, object], migration["bootstrap_executor_terminal"]).get(field))
            is not int
            for field in {
                "connection_limit",
                "membership_count",
                "session_count",
                "effective_chronos_privilege_count",
            }
        )
        or any(
            type(cast(dict[str, object], migration["bootstrap_executor_terminal"]).get(field))
            is not bool
            for field in {"can_login", "inherit", "password_null", "valid_until_epoch"}
        )
        or migration.get("bootstrap_executor_terminal") != expected_terminal
        or not isinstance(identity_run_id, str)
        or not isinstance(effects, dict)
        or set(effects) != _BOOTSTRAP_EFFECT_FIELDS
        or any(type(effects.get(field)) is not int for field in _BOOTSTRAP_INTEGER_FIELDS)
        or effects.get("effect_counter_certainty") != "CONSERVATIVE_UPPER_BOUNDS"
        or effects.get("r2_gets") != 0
        or effects.get("r2_gets_exact") is not True
        or effects.get("r2_puts") != 0
        or type(effects.get("neon_gets")) is not int
        or not 1 <= cast(int, effects["neon_gets"]) <= 26
        or effects.get("neon_gets_exact") is not True
        or effects.get("neon_posts") != 0
        or effects.get("neon_posts_exact") is not True
        or type(effects.get("postgresql_connection_attempts")) is not int
        or effects.get("postgresql_connection_attempts") != {0: 5, 1: 10}.get(dispatch_count)
        or effects.get("postgresql_connection_attempts_exact") is not (dispatch_count == 0)
        or effects.get("recovery_branch_creations_upper_bound") != 0
        or effects.get("recovery_branch_creations_exact") is not True
        or effects.get("migration_dispatches") != dispatch_count
        or effects.get("migration_dispatches_exact") is not True
        or effects.get("sql_statements_upper_bound") != 2048
        or effects.get("sql_statements_exact") is not False
        or effects.get("sql_write_statements_upper_bound") != 1024
        or effects.get("sql_write_statements_exact") is not False
        or effects.get("automatic_retries") != 0
        or effects.get("provider_calls") != 0
        or effects.get("purchases") != 0
        or effects.get("secret_values_observed") is not False
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
    if expected_preflight is not None:
        exact_preflight = dict(expected_preflight)
        if (
            migration.get("preflight_run_id") != exact_preflight.get("preflight_run_id")
            or migration.get("preflight_hash") != exact_preflight.get("preflight_hash")
            or migration.get("identity_seal") != exact_preflight.get("identity_seal")
            or any(
                migration.get(field) != exact_preflight.get(field)
                for field in (
                    "database_host",
                    "database_port",
                    "database_name",
                    "sslmode",
                    "channel_binding",
                    "project_id",
                    "production_branch_id",
                    "recovery_branch_id",
                )
            )
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
    if expected_runtime_bindings is not None and migration.get("runtime_bindings") != dict(
        expected_runtime_bindings
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
    _validate_migration_target(migration)
    try:
        validate_identity_seal_v2(
            identity_seal,
            main_sha=main_sha,
            expected_identity_run_id=identity_run_id,
        )
        validate_runtime_bindings_v2(
            migration.get("runtime_bindings"),
            main_sha=main_sha,
            preflight_run_id=preflight_run_id,
            preflight_artifact_hash=preflight_hash,
            generation_nonce=generation_nonce,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID") from None
    return migration


def _validate_verify_identities(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"authority", "runtime", "reader"}:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
    expected_accounts = {
        role: (login, group)
        for role, (login, group, _secret_name) in zip(
            ("authority", "runtime", "reader"), SCOPED_LOGINS, strict=True
        )
    }
    targets: set[tuple[str, int, str, str, str]] = set()
    server_epochs: set[str] = set()
    expected_fields = {
        "database_host",
        "database_port",
        "database_name",
        "sslmode",
        "channel_binding",
        "current_user",
        "revision",
        "server_epoch",
        "memberships",
    }
    for role, (login, group) in expected_accounts.items():
        entry = value.get(role)
        if (
            not isinstance(entry, dict)
            or set(entry) != expected_fields
            or not isinstance(entry.get("database_host"), str)
            or type(entry.get("database_port")) is not int
            or not isinstance(entry.get("database_name"), str)
            or not isinstance(entry.get("sslmode"), str)
            or not isinstance(entry.get("channel_binding"), str)
            or entry.get("current_user") != login
            or entry.get("revision") != "0015_data_torrent_opportunity"
            or entry.get("memberships") != [{"granted_role": group}]
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        try:
            DirectPostgresTarget(
                host=cast(str, entry["database_host"]),
                port=cast(int, entry["database_port"]),
                database=cast(str, entry["database_name"]),
                username=login,
                sslmode=cast(str, entry["sslmode"]),
                channel_binding=cast(str, entry["channel_binding"]),
            )
            _require_utc_instant(entry.get("server_epoch"))
        except (ChronosProductionError, ValueError):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID") from None
        targets.add(
            (
                cast(str, entry["database_host"]),
                cast(int, entry["database_port"]),
                cast(str, entry["database_name"]),
                cast(str, entry["sslmode"]),
                cast(str, entry["channel_binding"]),
            )
        )
        server_epochs.add(cast(str, entry["server_epoch"]))
    if len(targets) != 1 or len(server_epochs) != 1:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")


def _validate_verify_artifact(
    document: dict[str, Any],
    *,
    main_sha: str,
    verify_run_id: str,
    identity_run_id: str,
    expected_generation_hash: str,
    generation_nonce: str,
    expected_migration: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if generation_hash(generation_nonce) != expected_generation_hash:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
    try:
        verify = verify_signed_document(document, generation_nonce)
        preflight_hash = require_hash(str(verify.get("preflight_hash", "")), field="preflight_hash")
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID") from None
    expected_fields = {
        "schema_version",
        "verdict",
        "revision",
        "identities",
        "business_data_modified",
        "forbidden_membership",
        "migrator_runtime_membership",
        "runtime_effective_bootstrap_edge",
        "provider_calls",
        "r2_operations",
        "main_sha",
        "workflow_sha",
        "post_merge_ci_sha",
        "generation_hash",
        "preflight_run_id",
        "preflight_hash",
        "migration_run_id",
        "migration_run_attempt",
        "verify_run_id",
        "verify_run_attempt",
        "migration_output_signature_algorithm",
        "effects",
        "identity_seal",
        "runtime_bindings",
        "production_database_revision_verified",
        "chronos_opportunity_claim_active",
        "torrent_recovery_v2_contract_active",
        "runtime_bindings_present",
    }
    effects = verify.get("effects")
    identities = verify.get("identities")
    preflight_run_id = verify.get("preflight_run_id")
    migration_run_id = verify.get("migration_run_id")
    if (
        set(verify) != expected_fields
        or verify.get("schema_version") != "chronos-production-verify-v2"
        or verify.get("verdict") != "VERIFY_0015_COMPLETE_V2"
        or verify.get("revision") != "0015_data_torrent_opportunity"
        or verify.get("main_sha") != main_sha
        or verify.get("workflow_sha") != main_sha
        or verify.get("post_merge_ci_sha") != main_sha
        or verify.get("generation_hash") != expected_generation_hash
        or verify.get("verify_run_id") != verify_run_id
        or verify.get("verify_run_attempt") != "1"
        or verify.get("migration_run_attempt") != "1"
        or not isinstance(migration_run_id, str)
        or _RUN_ID.fullmatch(migration_run_id) is None
        or not isinstance(preflight_run_id, str)
        or _RUN_ID.fullmatch(preflight_run_id) is None
        or verify.get("business_data_modified") is not False
        or any(
            type(verify.get(field)) is not int
            for field in {
                "forbidden_membership",
                "migrator_runtime_membership",
                "runtime_effective_bootstrap_edge",
                "provider_calls",
                "r2_operations",
                "runtime_bindings_present",
            }
        )
        or verify.get("forbidden_membership") != 0
        or verify.get("migrator_runtime_membership") != 0
        or verify.get("runtime_effective_bootstrap_edge") != 0
        or verify.get("provider_calls") != 0
        or verify.get("r2_operations") != 0
        or verify.get("production_database_revision_verified") is not True
        or verify.get("chronos_opportunity_claim_active") is not True
        or verify.get("torrent_recovery_v2_contract_active") is not True
        or verify.get("runtime_bindings_present") != 4
        or verify.get("migration_output_signature_algorithm") != "HMAC-SHA256"
        or not isinstance(effects, dict)
        or set(effects) != _BOOTSTRAP_EFFECT_FIELDS
        or any(type(effects.get(field)) is not int for field in _BOOTSTRAP_INTEGER_FIELDS)
        or effects.get("effect_counter_certainty") != "CONSERVATIVE_UPPER_BOUNDS"
        or effects.get("r2_gets") != 0
        or effects.get("r2_gets_exact") is not True
        or effects.get("r2_puts") != 0
        or effects.get("neon_gets") != 0
        or effects.get("neon_gets_exact") is not True
        or effects.get("neon_posts") != 0
        or effects.get("neon_posts_exact") is not True
        or effects.get("postgresql_connection_attempts") != 4
        or effects.get("postgresql_connection_attempts_exact") is not True
        or effects.get("recovery_branch_creations_upper_bound") != 0
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
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
    _validate_verify_identities(identities)
    if expected_migration is not None:
        exact_migration = dict(expected_migration)
        if (
            verify.get("migration_run_id") != exact_migration.get("migration_run_id")
            or verify.get("preflight_run_id") != exact_migration.get("preflight_run_id")
            or verify.get("preflight_hash") != exact_migration.get("preflight_hash")
            or verify.get("generation_hash") != exact_migration.get("generation_hash")
            or verify.get("identity_seal") != exact_migration.get("identity_seal")
            or verify.get("runtime_bindings") != exact_migration.get("runtime_bindings")
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        expected_target = tuple(
            exact_migration.get(field)
            for field in (
                "database_host",
                "database_port",
                "database_name",
                "sslmode",
                "channel_binding",
            )
        )
        if not isinstance(identities, dict) or any(
            tuple(
                cast(dict[str, object], entry).get(field)
                for field in (
                    "database_host",
                    "database_port",
                    "database_name",
                    "sslmode",
                    "channel_binding",
                )
            )
            != expected_target
            for entry in identities.values()
            if isinstance(entry, dict)
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
    try:
        validate_identity_seal_v2(
            verify.get("identity_seal"),
            main_sha=main_sha,
            expected_identity_run_id=identity_run_id,
        )
        validate_runtime_bindings_v2(
            verify.get("runtime_bindings"),
            main_sha=main_sha,
            preflight_run_id=preflight_run_id,
            preflight_artifact_hash=preflight_hash,
            generation_nonce=generation_nonce,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID") from None
    return verify


def _strict_temporary_json_document(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    """Read one private temporary artifact without treating it as repository evidence."""

    try:
        payload = _recovery_v2_read_bytes(
            path,
            repository_root=path.parent,
            maximum_bytes=maximum_bytes,
        )
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (ChronosProductionError, OSError, UnicodeDecodeError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    if (
        not payload
        or len(payload) > maximum_bytes
        or b"\x00" in payload
        or b"\r" in payload
        or not payload.endswith(b"\n")
        or not isinstance(document, dict)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    return payload, cast(dict[str, Any], document)


def _validate_stage_success_document(
    *,
    stage: str,
    document: dict[str, Any],
    main_sha: str,
    run_id: str,
    inputs: Mapping[str, str],
    enforce_preflight_expiry: bool = True,
) -> dict[str, Any]:
    """Prove the semantic GO for one exact successful stage artifact."""

    if stage == "RECOVERY_IDENTITY_V2":
        validated = validate_neon_branch_identity_go_v2(document, main_sha=main_sha)
        source = cast(dict[str, Any], validated["source"])
        if source.get("run_id") != run_id:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_IDENTITY_INVALID")
        return validated
    if stage == "DURABLE_IDENTITY_SEAL_V2":
        identity_run_id = inputs.get("identity_run_id")
        if identity_run_id is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_SEAL_INVALID")
        cached_identity = _load_cached_stage_success(
            stage="RECOVERY_IDENTITY_V2",
            main_sha=main_sha,
            run_id=identity_run_id,
            inputs={},
        )
        if cached_identity is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_SEAL_INVALID")
        validated = validate_identity_seal_v2(
            document,
            main_sha=main_sha,
            expected_identity_run_id=identity_run_id,
        )
        source = cast(dict[str, Any], validated["source"])
        identity_binding = validated.get("identity_go")
        identity_attestation = cached_identity.get("attestation")
        if (
            source.get("run_id") != run_id
            or not isinstance(identity_binding, dict)
            or not isinstance(identity_attestation, dict)
            or {
                field: identity_binding.get(field) for field in identity_attestation
            }
            != identity_attestation
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_SEAL_INVALID")
        return validated
    if stage == "PRODUCTION_PREFLIGHT_V2":
        identity_run_id = inputs.get("identity_run_id") or document.get("identity_run_id")
        seal_run_id = inputs.get("seal_run_id") or document.get("seal_run_id")
        if (
            not isinstance(identity_run_id, str)
            or _RUN_ID.fullmatch(identity_run_id) is None
            or not isinstance(seal_run_id, str)
            or _RUN_ID.fullmatch(seal_run_id) is None
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREFLIGHT_INVALID")
        cached_seal = _load_cached_stage_success(
            stage="DURABLE_IDENTITY_SEAL_V2",
            main_sha=main_sha,
            run_id=seal_run_id,
            inputs={"identity_run_id": identity_run_id},
        )
        if cached_seal is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREFLIGHT_INVALID")
        try:
            validated = validate_preflight_artifact_v2(
                document,
                main_sha=main_sha,
                expected_identity_run_id=identity_run_id,
                expected_seal_run_id=seal_run_id,
                expected_identity_seal=cast(dict[str, object], cached_seal["document"]),
                now=datetime.now(UTC) if enforce_preflight_expiry else None,
            )
        except ChronosProductionError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREFLIGHT_INVALID") from None
        if validated.get("preflight_run_id") != run_id:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREFLIGHT_INVALID")
        return validated
    if stage == "MIGRATE_0015":
        expected_preflight_run_id = inputs.get("preflight_run_id") or document.get(
            "preflight_run_id"
        )
        if (
            not isinstance(expected_preflight_run_id, str)
            or _RUN_ID.fullmatch(expected_preflight_run_id) is None
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
        cached_preflight = _load_cached_stage_success(
            stage="PRODUCTION_PREFLIGHT_V2",
            main_sha=main_sha,
            run_id=expected_preflight_run_id,
            inputs={},
        )
        if cached_preflight is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
        exact_preflight = cast(dict[str, Any], cached_preflight["document"])
        exact_preflight_hash = exact_preflight.get("preflight_hash")
        if not isinstance(exact_preflight_hash, str):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
        exact_preflight_controller_receipt_sha256 = (
            _validate_predecessor_controller_receipt(
                stage="PRODUCTION_PREFLIGHT_V2",
                main_sha=main_sha,
                run_id=expected_preflight_run_id,
                attestation=cast(dict[str, object], cached_preflight["attestation"]),
            )
        )
        generation_nonce = _generation_nonce()
        exact_bindings = _validate_exact_runtime_bindings(
            encoded_receipt=inputs.get("runtime_bindings_receipt_b64"),
            main_sha=main_sha,
            preflight_run_id=expected_preflight_run_id,
            preflight_artifact_hash=exact_preflight_hash,
            preflight_controller_receipt_sha256=(
                exact_preflight_controller_receipt_sha256
            ),
            generation_nonce=generation_nonce,
        )
        validated = _validate_migration_artifact(
            document,
            main_sha=main_sha,
            migration_run_id=run_id,
            generation_nonce=generation_nonce,
            expected_preflight=exact_preflight,
            expected_runtime_bindings=exact_bindings,
        )
        if validated.get("preflight_run_id") != expected_preflight_run_id:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MIGRATION_INVALID")
        return validated
    if stage == "VERIFY_0015":
        expected_migration_run_id = inputs.get("migration_run_id") or document.get(
            "migration_run_id"
        )
        if (
            not isinstance(expected_migration_run_id, str)
            or _RUN_ID.fullmatch(expected_migration_run_id) is None
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        cached_migration = _load_cached_stage_success(
            stage="MIGRATE_0015",
            main_sha=main_sha,
            run_id=expected_migration_run_id,
            inputs={},
        )
        if cached_migration is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        migration = cast(dict[str, Any], cached_migration["document"])
        identity_seal = migration.get("identity_seal")
        identity_go = identity_seal.get("identity_go") if isinstance(identity_seal, dict) else None
        identity_run_id = identity_go.get("run_id") if isinstance(identity_go, dict) else None
        expected_generation_hash = migration.get("generation_hash")
        if not isinstance(identity_run_id, str) or not isinstance(expected_generation_hash, str):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        validated = _validate_verify_artifact(
            document,
            main_sha=main_sha,
            verify_run_id=run_id,
            identity_run_id=identity_run_id,
            expected_generation_hash=expected_generation_hash,
            generation_nonce=_generation_nonce(),
            expected_migration=migration,
        )
        if validated.get("migration_run_id") != expected_migration_run_id:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_VERIFY_INVALID")
        return validated
    raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_STAGE_INVALID")


def _validate_success_attestation(
    *,
    stage: str,
    main_sha: str,
    run_id: str,
    payload: bytes,
    attestation: Mapping[str, object],
) -> None:
    artifact = _SUCCESS_ARTIFACTS.get(stage)
    if (
        artifact is None
        or set(attestation)
        != {
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
        or attestation.get("schema_version") != "github-artifact-attestation-v2"
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path") != artifact["workflow_path"]
        or attestation.get("run_id") != run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != main_sha
        or type(attestation.get("artifact_id")) is not int
        or cast(int, attestation["artifact_id"]) <= 0
        or attestation.get("artifact_name") != artifact["artifact_prefix"] + run_id
        or attestation.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
        or not isinstance(attestation.get("archive_sha256"), str)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    try:
        require_hash(cast(str, attestation["archive_sha256"]), field="archive_sha256")
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None


def _load_cached_stage_success(
    *,
    stage: str,
    main_sha: str,
    run_id: str,
    inputs: Mapping[str, str],
    enforce_preflight_expiry: bool = False,
) -> dict[str, object] | None:
    artifact = _SUCCESS_ARTIFACTS.get(stage)
    if artifact is None:
        return None
    cache_path = (
        _PREDECESSOR_CACHE_ROOT
        / f"{_PREDECESSOR_CACHE_SLUGS[artifact['kind']]}.json"
    )
    if not os.path.lexists(cache_path):
        return None
    try:
        _cache_payload, cache = _strict_json_document(
            cache_path,
            maximum_bytes=16 * 1024 * 1024,
        )
        encoded_payload = cache.get("payload_base64")
        attestation = cache.get("attestation")
        if (
            set(cache)
            != {
                "schema_version",
                "kind",
                "artifact_filename",
                "payload_base64",
                "attestation",
            }
            or cache.get("schema_version")
            != "data-torrent-recovery-v2-singleton-cache-v1"
            or cache.get("kind") != artifact["kind"]
            or cache.get("artifact_filename") != artifact["artifact_filename"]
            or not isinstance(encoded_payload, str)
            or not isinstance(attestation, dict)
        ):
            raise ValueError
        payload = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
        if not payload or len(payload) > 10 * 1024 * 1024:
            raise ValueError
        _validate_success_attestation(
            stage=stage,
            main_sha=main_sha,
            run_id=run_id,
            payload=payload,
            attestation=cast(dict[str, object], attestation),
        )
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(document, dict):
            raise ValueError
        validated = _validate_stage_success_document(
            stage=stage,
            document=cast(dict[str, Any], document),
            main_sha=main_sha,
            run_id=run_id,
            inputs=inputs,
            enforce_preflight_expiry=enforce_preflight_expiry,
        )
    except RecoveryV2ControllerError:
        raise
    except (
        ChronosProductionError,
        OSError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        ValueError,
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    return {
        "attestation": cast(dict[str, object], attestation),
        "payload": payload,
        "document": validated,
        "semantic_verdict": artifact["semantic_verdict"],
    }


def _validate_predecessor(
    *, stage: str, main_sha: str, inputs: Mapping[str, str]
) -> dict[str, object]:
    if stage == "RECOVERY_IDENTITY_V2":
        return _validate_postmerge_quarantine_receipt(main_sha=main_sha)
    predecessor = _PREDECESSORS[stage]
    run_id = inputs[predecessor["run_id_field"]]
    expected_prior_run_ids: list[int] = []
    predecessor_stage = {
        "IDENTITY": "RECOVERY_IDENTITY_V2",
        "IDENTITY_SEAL": "DURABLE_IDENTITY_SEAL_V2",
        "PREFLIGHT": "PRODUCTION_PREFLIGHT_V2",
        "MIGRATION": "MIGRATE_0015",
        "VERIFY": "VERIFY_0015",
    }[predecessor["kind"]]
    try:
        cached = _load_cached_stage_success(
            stage=predecessor_stage,
            main_sha=main_sha,
            run_id=run_id,
            inputs=inputs,
            enforce_preflight_expiry=predecessor_stage == "PRODUCTION_PREFLIGHT_V2",
        )
        if cached is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
        attestation = cast(dict[str, object], cached["attestation"])
        validated_document = cast(dict[str, Any], cached["document"])
        kind = predecessor["kind"]
        semantic_verdict = _PREDECESSOR_SEMANTIC_VERDICTS[stage]
        predecessor_controller_receipt_sha256 = _validate_predecessor_controller_receipt(
            stage=predecessor_stage,
            main_sha=main_sha,
            run_id=run_id,
            attestation=attestation,
        )
        if kind == "PREFLIGHT":
            _validate_local_runtime_bindings(
                encoded_receipt=inputs["runtime_bindings_receipt_b64"],
                main_sha=main_sha,
                preflight_run_id=run_id,
                preflight_hash=cast(str, validated_document["preflight_hash"]),
                preflight_controller_receipt_sha256=(
                    predecessor_controller_receipt_sha256
                ),
                generation_nonce=_generation_nonce(),
            )
            expected_prior_run_ids = [int(run_id)]
        elif kind == "MIGRATION":
            preflight_run_id = validated_document.get("preflight_run_id")
            if not isinstance(preflight_run_id, str) or _RUN_ID.fullmatch(preflight_run_id) is None:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
            expected_prior_run_ids = [int(preflight_run_id), int(run_id)]
        elif kind == "VERIFY":
            identity_seal = validated_document.get("identity_seal")
            identity_go = (
                identity_seal.get("identity_go")
                if isinstance(identity_seal, dict)
                else None
            )
            verified_identity_run_id = (
                identity_go.get("run_id") if isinstance(identity_go, dict) else None
            )
            if (
                inputs.get("expected_generation_hash")
                != validated_document.get("generation_hash")
                or inputs.get("identity_run_id") != verified_identity_run_id
            ):
                raise RecoveryV2ControllerError(
                    "RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID"
                )
        elif kind not in {"IDENTITY", "IDENTITY_SEAL"}:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    except (ChronosProductionError, RecoveryV2ControllerError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    except Exception:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    return {
        "predecessor_kind": predecessor["kind"],
        "predecessor_attestation": attestation,
        "predecessor_semantic_verdict": semantic_verdict,
        "predecessor_controller_receipt_sha256": (
            predecessor_controller_receipt_sha256
        ),
        "expected_prior_run_ids": expected_prior_run_ids,
    }


def _cache_validated_predecessor(
    *,
    kind: str,
    artifact_filename: str,
    payload: bytes,
    attestation: Mapping[str, object],
) -> None:
    """Persist one already-validated predecessor for terminal evidence without a replay GET."""

    slug = _PREDECESSOR_CACHE_SLUGS.get(kind)
    expected_filenames = {
        "IDENTITY": "neon-branch-identity-go-v2.json",
        "IDENTITY_SEAL": "durable-identity-seal-v2.json",
        "PREFLIGHT": "production-preflight-v2.json",
        "MIGRATION": "chronos-production-migrate-v2.json",
        "VERIFY": "chronos-production-verify-v2.json",
    }
    if (
        slug is None
        or artifact_filename != expected_filenames.get(kind)
        or not payload
        or len(payload) > 10 * 1024 * 1024
        or set(attestation)
        != {
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
        or attestation.get("schema_version") != "github-artifact-attestation-v2"
        or hashlib.sha256(payload).hexdigest() != attestation.get("payload_sha256")
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    cache_path = _PREDECESSOR_CACHE_ROOT / f"{slug}.json"
    cache_document = {
        "schema_version": "data-torrent-recovery-v2-singleton-cache-v1",
        "kind": kind,
        "artifact_filename": artifact_filename,
        "payload_base64": base64.b64encode(payload).decode("ascii"),
        "attestation": dict(attestation),
    }
    try:
        _recovery_v2_prepare_repository_directory(
            _PREDECESSOR_CACHE_ROOT,
            repository_root=_REPOSITORY_ROOT,
        )
        _write_receipt(
            cache_path,
            cache_document,
            exclusive=True,
        )
    except FileExistsError:
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        ) from None
    except RecoveryV2ControllerError:
        raise
    except OSError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RECEIPT_INVALID") from None


def _validated_terminal_run(
    *,
    stage: str,
    main_sha: str,
    run_id: int,
    document: Mapping[str, object],
) -> dict[str, object]:
    workflow_path = f".github/workflows/{STAGES[stage]['workflow']}"
    repository = document.get("repository")
    status = document.get("status")
    conclusion = document.get("conclusion")
    updated_at = document.get("updated_at")
    if (
        type(document.get("id")) is not int
        or document.get("id") != run_id
        or type(document.get("run_attempt")) is not int
        or document.get("run_attempt") != 1
        or document.get("head_sha") != main_sha
        or document.get("head_branch") != "main"
        or document.get("event") != "workflow_dispatch"
        or document.get("path") != workflow_path
        or not isinstance(repository, dict)
        or repository.get("full_name") != EXPECTED_REPOSITORY
        or status not in _NONTERMINAL_RUN_STATUSES | {"completed"}
        or (status != "completed" and conclusion is not None)
        or (status == "completed" and not isinstance(conclusion, str))
        or not isinstance(updated_at, str)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RUN_OBSERVATION_INVALID")
    try:
        _require_utc_instant(updated_at)
    except ValueError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RUN_OBSERVATION_INVALID") from None
    return {
        "run_id": run_id,
        "run_attempt": 1,
        "workflow_path": workflow_path,
        "head_sha": main_sha,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": status,
        "conclusion": conclusion,
        "updated_at": updated_at,
    }


def _validate_terminal_success_evidence(
    *,
    stage: str,
    main_sha: str,
    run_id: str,
    terminal: Mapping[str, object],
    expected_attestation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Require a terminal-success proof, not merely a completed dispatch cycle."""

    if stage not in STAGES or _RUN_ID.fullmatch(run_id) is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID")
    live = stage == "LIVE_ONCE"
    expected_fields = {
        "outcome",
        "terminal_run",
        "run_observations",
        "attestation",
        "semantic_verdict",
    } | ({"semantic_projection_sha256"} if live else set())
    terminal_run = terminal.get("terminal_run")
    attestation = terminal.get("attestation")
    expected_attestation_fields = (
        {
            "schema_version",
            "repository",
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
            "run_completed_observed_at",
            "artifact_id",
            "artifact_name",
            "archive_sha256",
            "members",
        }
        if live
        else {
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
    )
    artifact = _SUCCESS_ARTIFACTS.get(stage)
    expected_semantic_verdict = (
        "DATA_TORRENT_READY"
        if live
        else artifact["semantic_verdict"]
        if artifact is not None
        else None
    )
    if (
        set(terminal) != expected_fields
        or terminal.get("outcome") != "SUCCESS"
        or type(terminal.get("run_observations")) is not int
        or not 1 <= cast(int, terminal["run_observations"]) <= 3
        or terminal.get("semantic_verdict") != expected_semantic_verdict
        or not isinstance(terminal_run, dict)
        or set(terminal_run)
        != {
            "run_id",
            "run_attempt",
            "workflow_path",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
            "updated_at",
        }
        or type(terminal_run.get("run_id")) is not int
        or terminal_run.get("run_id") != int(run_id)
        or type(terminal_run.get("run_attempt")) is not int
        or terminal_run.get("run_attempt") != 1
        or terminal_run.get("workflow_path")
        != f".github/workflows/{STAGES[stage]['workflow']}"
        or terminal_run.get("head_sha") != main_sha
        or terminal_run.get("head_branch") != "main"
        or terminal_run.get("event") != "workflow_dispatch"
        or terminal_run.get("status") != "completed"
        or terminal_run.get("conclusion") != "success"
        or not isinstance(terminal_run.get("updated_at"), str)
        or not isinstance(attestation, dict)
        or set(attestation) != expected_attestation_fields
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path")
        != f".github/workflows/{STAGES[stage]['workflow']}"
        or attestation.get("run_id") != run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != main_sha
        or type(attestation.get("artifact_id")) is not int
        or cast(int, attestation["artifact_id"]) <= 0
        or not isinstance(attestation.get("archive_sha256"), str)
        or (expected_attestation is not None and attestation != expected_attestation)
        or (
            live
            and (
                attestation.get("schema_version")
                != "github-artifact-bundle-attestation-v2"
                or attestation.get("head_branch") != "main"
                or attestation.get("event") != "workflow_dispatch"
                or attestation.get("status") != "completed"
                or attestation.get("conclusion") != "success"
                or attestation.get("artifact_name") != f"data-torrent-live-v2-{run_id}"
                or not isinstance(attestation.get("members"), list)
                or not isinstance(terminal.get("semantic_projection_sha256"), str)
            )
        )
        or (
            not live
            and (
                artifact is None
                or attestation.get("schema_version") != "github-artifact-attestation-v2"
                or attestation.get("artifact_name") != artifact["artifact_prefix"] + run_id
                or not isinstance(attestation.get("payload_sha256"), str)
            )
        )
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID")
    try:
        _require_utc_instant(terminal_run["updated_at"])
        require_hash(cast(str, attestation["archive_sha256"]), field="archive_sha256")
        if live:
            _require_utc_instant(attestation.get("run_completed_observed_at"))
            require_hash(
                cast(str, terminal["semantic_projection_sha256"]),
                field="semantic_projection_sha256",
            )
        else:
            require_hash(cast(str, attestation["payload_sha256"]), field="payload_sha256")
    except (ChronosProductionError, ValueError):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
        ) from None
    return dict(terminal)


def _validate_predecessor_controller_receipt(
    *,
    stage: str,
    main_sha: str,
    run_id: str,
    attestation: Mapping[str, object],
) -> str:
    """Bind a cached artifact to its exact one-shot controller success journal."""

    payload, receipt = _strict_json_document(
        _canonical_controller_receipt(stage), maximum_bytes=2 * 1024 * 1024
    )
    proof = receipt.get("pre_effect_proof")
    stage_inputs = proof.get("stage_inputs") if isinstance(proof, dict) else None
    reservation = receipt.get("terminalization_effect_reservation")
    bound_effect_deadline: int | None = None
    if isinstance(stage_inputs, dict):
        raw_deadline = stage_inputs.get(_DISPATCH_EFFECT_DEADLINE_INPUT)
        if (
            isinstance(raw_deadline, str)
            and raw_deadline.isascii()
            and raw_deadline.isdigit()
            and str(int(raw_deadline)) == raw_deadline
        ):
            bound_effect_deadline = int(raw_deadline)
    workflow_terminal_grace = _POST_EFFECT_WORKFLOW_TERMINAL_GRACE_SECONDS[stage]
    expected_fields = {
        "schema_version",
        "verdict",
        "stage",
        "main_sha",
        "inputs_sha256",
        "automatic_retries",
        "mutations_attempted",
        "mutations_confirmed",
        "pre_effect_proof",
        "pre_effect_proof_sha256",
        "workflow_path",
        "workflow_run_id",
        "terminalization_effect_reservation",
        "terminalization_completed_at",
        "terminal_evidence",
    }
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version")
        != "data-torrent-recovery-v2-controller-cycle-v1"
        or receipt.get("verdict") != "TERMINAL_SUCCESS_CONFIRMED"
        or receipt.get("stage") != stage
        or receipt.get("main_sha") != main_sha
        or type(receipt.get("automatic_retries")) is not int
        or receipt.get("automatic_retries") != 0
        or receipt.get("mutations_attempted") != ["ENABLE", "DISPATCH", "DISABLE"]
        or receipt.get("mutations_confirmed") != ["ENABLE", "DISPATCH", "DISABLE"]
        or receipt.get("workflow_path") != f".github/workflows/{STAGES[stage]['workflow']}"
        or type(receipt.get("workflow_run_id")) is not int
        or receipt.get("workflow_run_id") != int(run_id)
        or not isinstance(reservation, dict)
        or any(
            type(reservation.get(field)) is not int
            for field in {
                "workflow_run_id",
                "workflow_effect_deadline_epoch",
                "post_effect_workflow_terminal_grace_seconds",
                "controller_terminalization_deadline_epoch",
                "terminal_artifact_attestation_reserve_seconds",
                "workflow_run_observations_conservatively_consumed",
                "artifact_attestation_gets_conservatively_consumed",
                "artifact_downloads_conservatively_consumed",
                "automatic_retries",
            }
        )
        or reservation.get("second_terminalization_invocation_allowed") is not False
        or reservation
        != {
            "reservation_status": (
                "CONSERVATIVE_UPPER_BOUNDS_RESERVED_BEFORE_FIRST_TERMINAL_GET"
            ),
            "workflow_run_id": int(run_id),
            "workflow_effect_deadline_epoch": bound_effect_deadline,
            "post_effect_workflow_terminal_grace_seconds": workflow_terminal_grace,
            "controller_terminalization_deadline_epoch": (
                None
                if bound_effect_deadline is None
                else bound_effect_deadline
                + workflow_terminal_grace
                + int(_TERMINAL_ATTESTATION_RESERVE_SECONDS)
            ),
            "terminal_artifact_attestation_reserve_seconds": int(
                _TERMINAL_ATTESTATION_RESERVE_SECONDS
            ),
            "workflow_run_observations_conservatively_consumed": 3,
            "artifact_attestation_gets_conservatively_consumed": 3,
            "artifact_downloads_conservatively_consumed": 1,
            "automatic_retries": 0,
            "second_terminalization_invocation_allowed": False,
        }
        or not isinstance(proof, dict)
        or not isinstance(stage_inputs, dict)
        or receipt.get("pre_effect_proof_sha256") != _object_sha256(proof)
        or receipt.get("inputs_sha256") != _inputs_sha256(cast(dict[str, str], stage_inputs))
        or not isinstance(receipt.get("terminal_evidence"), dict)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    try:
        completed_text = _require_utc_instant(receipt.get("terminalization_completed_at"))
        completed_at = datetime.fromisoformat(completed_text.replace("Z", "+00:00"))
        if (
            bound_effect_deadline is None
            or completed_at
            > datetime.fromtimestamp(
                bound_effect_deadline
                + workflow_terminal_grace
                + int(_TERMINAL_ATTESTATION_RESERVE_SECONDS),
                tz=UTC,
            )
        ):
            raise ValueError
        _validate_pre_effect_proof(
            stage=stage,
            main_sha=main_sha,
            inputs_sha256=cast(str, receipt["inputs_sha256"]),
            proof=proof,
        )
        terminal = _validate_terminal_success_evidence(
            stage=stage,
            main_sha=main_sha,
            run_id=run_id,
            terminal=cast(dict[str, object], receipt["terminal_evidence"]),
            expected_attestation=attestation,
        )
        terminal_run = cast(dict[str, object], terminal["terminal_run"])
        terminal_updated_text = _require_utc_instant(terminal_run.get("updated_at"))
        terminal_updated_at = datetime.fromisoformat(
            terminal_updated_text.replace("Z", "+00:00")
        )
        if completed_at < terminal_updated_at:
            raise ValueError
    except (RecoveryV2ControllerError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    return hashlib.sha256(payload).hexdigest()


def validate_preflight_controller_handoff_v2(
    *,
    main_sha: str,
    run_id: str,
    attestation: Mapping[str, object],
) -> str:
    """Require the final successful R3 controller journal before local R4 effects."""

    try:
        expected_sha = require_sha(main_sha, field="main_sha")
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID") from None
    if _RUN_ID.fullmatch(run_id) is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID")
    return _validate_predecessor_controller_receipt(
        stage="PRODUCTION_PREFLIGHT_V2",
        main_sha=expected_sha,
        run_id=run_id,
        attestation=attestation,
    )


def _terminalization_completed_at(
    *,
    deadline_epoch: float,
    clock: Callable[[], float],
) -> str:
    observed = clock()
    if (
        isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not math.isfinite(float(observed))
        or float(observed) > deadline_epoch
    ):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_TERMINALIZATION_DEADLINE_EXCEEDED"
        )
    return (
        datetime.fromtimestamp(float(observed), tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _wait_for_terminal_run(
    *,
    stage: str,
    main_sha: str,
    run_id: int,
    token: str,
    run_loader: Callable[[str, str], Mapping[str, object]],
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
    terminalization_deadline_epoch: float,
) -> tuple[dict[str, object], int]:
    """Observe one exact run at most three times, leaving time for full attestation."""

    deadline = min(
        clock()
        + _STAGE_TIMEOUT_SECONDS[stage]
        + _POST_EFFECT_WORKFLOW_TERMINAL_GRACE_SECONDS[stage]
        + _TERMINAL_ATTESTATION_RESERVE_SECONDS,
        clock() + _require_effect_window(terminalization_deadline_epoch),
    )
    path = f"/repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}"
    for observation in range(1, _TERMINAL_RUN_OBSERVATIONS_MAXIMUM + 1):
        try:
            _require_effect_window(
                terminalization_deadline_epoch,
                margin_seconds=GITHUB_GET_TOTAL_TIMEOUT_SECONDS,
            )
            document = run_loader(path, token)
        except Exception:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_RUN_OBSERVATION_AMBIGUOUS"
            ) from None
        terminal = _validated_terminal_run(
            stage=stage,
            main_sha=main_sha,
            run_id=run_id,
            document=document,
        )
        if terminal["status"] == "completed":
            return terminal, observation
        if observation == _TERMINAL_RUN_OBSERVATIONS_MAXIMUM:
            break
        remaining = deadline - clock() - _TERMINAL_ATTESTATION_RESERVE_SECONDS
        observations_left = _TERMINAL_RUN_OBSERVATIONS_MAXIMUM - observation
        if remaining <= 0 or observations_left <= 0:
            break
        sleeper(remaining / observations_left)
    raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RUN_NOT_TERMINAL_WITHIN_BUDGET")


def _validate_live_success_bundle(
    *,
    bundle_dir: Path,
    main_sha: str,
    run_id: str,
    inputs: Mapping[str, str],
    pre_effect_proof: Mapping[str, object],
) -> dict[str, object]:
    from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import _ARTIFACT_NAMES

    artifacts: dict[str, bytes] = {}
    try:
        entries = list(os.scandir(bundle_dir))
        if tuple(sorted(entry.name for entry in entries)) != _ARTIFACT_NAMES:
            raise ValueError
        for entry in entries:
            metadata = entry.stat(follow_symlinks=False)
            path = Path(entry.path)
            if (
                entry.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or _recovery_v2_path_is_reparse(path)
                or metadata.st_size <= 0
                or metadata.st_size > 10 * 1024 * 1024
            ):
                raise ValueError
            artifacts[entry.name] = _recovery_v2_read_bytes(
                path,
                repository_root=bundle_dir,
                maximum_bytes=10 * 1024 * 1024,
            )
    except Exception:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID") from None
    return _validate_live_success_payloads(
        artifacts=artifacts,
        main_sha=main_sha,
        run_id=run_id,
        inputs=inputs,
        pre_effect_proof=pre_effect_proof,
    )


def _expected_live_release_chain(
    *,
    verify: Mapping[str, Any],
    verify_attestation: Mapping[str, object],
) -> dict[str, object]:
    identities = verify.get("identities")
    if not isinstance(identities, dict):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    authority = identities.get("authority")
    if not isinstance(authority, dict):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    return {
        "receipt_sha256": verify_attestation.get("payload_sha256"),
        "schema_version": verify.get("schema_version"),
        "verdict": verify.get("verdict"),
        "revision": verify.get("revision"),
        "main_sha": verify.get("main_sha"),
        "post_merge_ci_sha": verify.get("post_merge_ci_sha"),
        "generation_hash": verify.get("generation_hash"),
        "preflight_run_id": verify.get("preflight_run_id"),
        "preflight_hash": verify.get("preflight_hash"),
        "migration_run_id": verify.get("migration_run_id"),
        "verify_run_id": verify.get("verify_run_id"),
        "verify_run_attempt": 1,
        "signature_algorithm": "HMAC-SHA256",
        "database_target": {
            "host": authority.get("database_host"),
            "port": authority.get("database_port"),
            "database": authority.get("database_name"),
            "sslmode": authority.get("sslmode"),
            "channel_binding": authority.get("channel_binding"),
            "server_epoch": authority.get("server_epoch"),
        },
        "identity_seal": verify.get("identity_seal"),
        "runtime_bindings": verify.get("runtime_bindings"),
        "torrent_recovery_v2_contract_active": True,
    }


def _expected_live_post_merge_ci_proof(
    *,
    main_sha: str,
    run_id: str,
    inputs: Mapping[str, str],
    pre_effect_proof: Mapping[str, object],
) -> dict[str, object]:
    from robin.data_torrent.runtime import CI_WORKFLOW_PATH, CROSS_RUN_CONTRACT

    try:
        _validate_pre_effect_proof(
            stage="LIVE_ONCE",
            main_sha=main_sha,
            inputs_sha256=_inputs_sha256(inputs),
            proof=pre_effect_proof,
        )
        live_holds = pre_effect_proof.get("live_postmerge_holds")
        if not isinstance(live_holds, list) or len(live_holds) != 2:
            raise ValueError
        live_hold = deepcopy(cast(dict[str, object], live_holds[0]))
        live_hold["current_run_excluded"] = int(run_id)
        hold_payload = (
            json.dumps(live_hold, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        ci_payload = _recovery_v2_read_bytes(
            _REPOSITORY_ROOT / CI_WORKFLOW_PATH,
            repository_root=_REPOSITORY_ROOT,
            maximum_bytes=2 * 1024 * 1024,
        )
        post_merge = live_hold.get("post_merge_ci")
        if not isinstance(post_merge, dict):
            raise ValueError
        return {
            "receipt_sha256": hashlib.sha256(hold_payload).hexdigest(),
            "workflow_path": CI_WORKFLOW_PATH,
            "workflow_file_sha256": hashlib.sha256(ci_payload).hexdigest(),
            "run_id": post_merge.get("run_id"),
            "run_attempt": post_merge.get("run_attempt"),
            "head_sha": post_merge.get("head_sha"),
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "cross_run_test_contract": CROSS_RUN_CONTRACT,
        }
    except (ChronosProductionError, RecoveryV2ControllerError, OSError, TypeError, ValueError):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID"
        ) from None


def _validate_live_success_payloads(
    *,
    artifacts: Mapping[str, bytes],
    main_sha: str,
    run_id: str,
    inputs: Mapping[str, str],
    pre_effect_proof: Mapping[str, object],
) -> dict[str, object]:
    from robin.chronos_production import _recovery_v2_terminal_live_semantics
    from robin.data_torrent.runtime import _assert_final_artifact_closure
    from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import _ARTIFACT_NAMES

    if tuple(sorted(artifacts)) != _ARTIFACT_NAMES or any(
        not isinstance(payload, bytes) or not payload or len(payload) > 10 * 1024 * 1024
        for payload in artifacts.values()
    ) or sum(len(payload) for payload in artifacts.values()) > 10 * 1024 * 1024:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    try:
        manifest = json.loads(
            artifacts["torrent-real-batch-manifest-v1.json"],
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(manifest, dict):
            raise ValueError
        normalized_binding = cast(dict[str, Any], manifest["evidence_validity"])["binding"]
        _assert_final_artifact_closure(
            artifacts=dict(artifacts),
            normalized_binding=normalized_binding,
        )
        semantics = _recovery_v2_terminal_live_semantics(
            artifacts,
            repository_root=_REPOSITORY_ROOT,
        )
    except Exception:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID") from None
    verify_run_id = inputs.get("verify_run_id")
    if verify_run_id is None or _RUN_ID.fullmatch(verify_run_id) is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    cached_verify = _load_cached_stage_success(
        stage="VERIFY_0015",
        main_sha=main_sha,
        run_id=verify_run_id,
        inputs={},
    )
    if cached_verify is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    verify = cast(dict[str, Any], cached_verify["document"])
    verify_attestation = cast(dict[str, object], cached_verify["attestation"])
    release_chain = semantics.get("release_chain")
    run_identity = semantics.get("run_identity")
    post_merge_ci_proof = semantics.get("post_merge_ci_proof")
    embedded_bindings = semantics.get("embedded_runtime_bindings")
    claim = semantics.get("claim")
    identity_seal = verify.get("identity_seal")
    identity_go = identity_seal.get("identity_go") if isinstance(identity_seal, dict) else None
    expected_identity_run_id = (
        identity_go.get("run_id") if isinstance(identity_go, dict) else None
    )
    expected_release_chain = _expected_live_release_chain(
        verify=verify,
        verify_attestation=verify_attestation,
    )
    expected_post_merge_ci_proof = _expected_live_post_merge_ci_proof(
        main_sha=main_sha,
        run_id=run_id,
        inputs=inputs,
        pre_effect_proof=pre_effect_proof,
    )
    expected_run_identity = {
        "github_repository": EXPECTED_REPOSITORY,
        "github_run_id": int(run_id),
        "github_run_attempt": 1,
        "github_sha": main_sha,
        "github_ref": "refs/heads/main",
        "github_workflow_ref": (
            f"{EXPECTED_REPOSITORY}/.github/workflows/data-torrent-live-v2.yml@refs/heads/main"
        ),
        "github_workflow_sha": main_sha,
        "workflow_path": ".github/workflows/data-torrent-live-v2.yml",
        "workflow_file_sha256": inputs.get("expected_workflow_sha256"),
        "code_revision": main_sha,
        "runner_os": "Linux",
        "runner_arch": "X64",
        "post_merge_ci_sha": main_sha,
    }
    if (
        not isinstance(release_chain, dict)
        or not isinstance(run_identity, dict)
        or not isinstance(post_merge_ci_proof, dict)
        or not isinstance(claim, dict)
        or run_identity != expected_run_identity
        or post_merge_ci_proof != expected_post_merge_ci_proof
        or inputs.get("expected_main_sha") != main_sha
        or inputs.get("post_merge_ci_sha") != main_sha
        or inputs.get("identity_run_id") != expected_identity_run_id
        or inputs.get("expected_generation_hash") != verify.get("generation_hash")
        or claim.get("mission_manifest_sha256")
        != inputs.get("expected_mission_manifest_sha256")
        or release_chain != expected_release_chain
        or embedded_bindings != verify.get("runtime_bindings")
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID")
    return cast(dict[str, object], semantics)


def _validated_live_bundle_cache_payloads(
    *,
    payloads: Mapping[str, bytes],
    attestation: Mapping[str, object],
    main_sha: str,
    run_id: str,
) -> dict[str, bytes]:
    """Bind every validated LIVE byte to the exact archive attestation."""

    from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import _ARTIFACT_NAMES

    members = attestation.get("members")
    if (
        set(attestation)
        != {
            "schema_version",
            "repository",
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
            "run_completed_observed_at",
            "artifact_id",
            "artifact_name",
            "archive_sha256",
            "members",
        }
        or attestation.get("schema_version") != "github-artifact-bundle-attestation-v2"
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path") != ".github/workflows/data-torrent-live-v2.yml"
        or attestation.get("run_id") != run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != main_sha
        or attestation.get("head_branch") != "main"
        or attestation.get("event") != "workflow_dispatch"
        or attestation.get("status") != "completed"
        or attestation.get("conclusion") != "success"
        or type(attestation.get("artifact_id")) is not int
        or cast(int, attestation["artifact_id"]) <= 0
        or attestation.get("artifact_name") != f"data-torrent-live-v2-{run_id}"
        or not isinstance(attestation.get("archive_sha256"), str)
        or not isinstance(members, list)
        or len(members) != len(_ARTIFACT_NAMES)
        or any(not isinstance(item, dict) for item in members)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID")
    try:
        require_hash(cast(str, attestation["archive_sha256"]), field="archive_sha256")
        _require_utc_instant(attestation.get("run_completed_observed_at"))
    except (ChronosProductionError, ValueError):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
        ) from None
    rows = cast(list[dict[str, object]], members)
    if tuple(cast(str, row.get("filename")) for row in rows) != _ARTIFACT_NAMES:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID")
    if tuple(sorted(payloads)) != _ARTIFACT_NAMES or any(
        not isinstance(payload, bytes) or not payload or len(payload) > 10 * 1024 * 1024
        for payload in payloads.values()
    ) or sum(len(payload) for payload in payloads.values()) > 10 * 1024 * 1024:
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
        )
    for row in rows:
        filename = cast(str, row.get("filename"))
        payload = payloads.get(filename)
        if (
            set(row) != {"filename", "payload_bytes", "payload_sha256"}
            or payload is None
            or type(row.get("payload_bytes")) is not int
            or row.get("payload_bytes") != len(payload)
            or not isinstance(row.get("payload_sha256"), str)
            or not hmac.compare_digest(
                cast(str, row["payload_sha256"]), hashlib.sha256(payload).hexdigest()
            )
        ):
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
            )
    return dict(payloads)


def _read_live_bundle_directory(bundle_dir: Path) -> dict[str, bytes]:
    from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import _ARTIFACT_NAMES

    payloads: dict[str, bytes] = {}
    try:
        entries = list(os.scandir(bundle_dir))
        if tuple(sorted(entry.name for entry in entries)) != _ARTIFACT_NAMES:
            raise ValueError
        for entry in entries:
            metadata = entry.stat(follow_symlinks=False)
            path = Path(entry.path)
            if (
                entry.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or _recovery_v2_path_is_reparse(path)
                or metadata.st_size <= 0
                or metadata.st_size > 10 * 1024 * 1024
            ):
                raise ValueError
            payloads[entry.name] = _recovery_v2_read_bytes(
                path,
                repository_root=bundle_dir,
                maximum_bytes=10 * 1024 * 1024,
            )
    except (ChronosProductionError, OSError, ValueError):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
        ) from None
    return payloads


def _decode_live_bundle_cache(
    *, payload: bytes, main_sha: str, run_id: str
) -> tuple[dict[str, object], dict[str, bytes]]:
    """Decode and fully revalidate one atomically published LIVE cache envelope."""

    try:
        if (
            not payload
            or len(payload) > 16 * 1024 * 1024
            or not payload.endswith(b"\n")
            or payload.startswith(b"\xef\xbb\xbf")
            or b"\x00" in payload
            or b"\r" in payload
        ):
            raise ValueError
        cache = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(cache, dict) or payload != (
            json.dumps(cache, sort_keys=True) + "\n"
        ).encode("utf-8"):
            raise ValueError
        attestation = cache.get("attestation")
        rows = cache.get("artifacts")
        if (
            set(cache)
            != {"schema_version", "main_sha", "run_id", "attestation", "artifacts"}
            or cache.get("schema_version")
            != "data-torrent-recovery-v2-live-bundle-cache-v1"
            or cache.get("main_sha") != main_sha
            or cache.get("run_id") != run_id
            or not isinstance(attestation, dict)
            or not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise ValueError
        payloads: dict[str, bytes] = {}
        for row in cast(list[dict[str, object]], rows):
            filename = row.get("filename")
            encoded = row.get("payload_base64")
            if (
                set(row) != {"filename", "payload_base64"}
                or not isinstance(filename, str)
                or not isinstance(encoded, str)
                or filename in payloads
            ):
                raise ValueError
            decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
            if not decoded or len(decoded) > 10 * 1024 * 1024:
                raise ValueError
            payloads[filename] = decoded
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
        ) from None
    validated = _validated_live_bundle_cache_payloads(
        payloads=payloads,
        attestation=cast(dict[str, object], attestation),
        main_sha=main_sha,
        run_id=run_id,
    )
    return cast(dict[str, object], attestation), validated


def _cache_validated_live_bundle(
    *,
    bundle_dir: Path,
    attestation: Mapping[str, object],
    main_sha: str,
    run_id: str,
) -> None:
    """Publish the first validated LIVE archive exactly once for local reuse."""

    payloads = _validated_live_bundle_cache_payloads(
        payloads=_read_live_bundle_directory(bundle_dir),
        attestation=attestation,
        main_sha=main_sha,
        run_id=run_id,
    )
    cache_document = {
        "schema_version": "data-torrent-recovery-v2-live-bundle-cache-v1",
        "main_sha": main_sha,
        "run_id": run_id,
        "attestation": dict(attestation),
        "artifacts": [
            {
                "filename": filename,
                "payload_base64": base64.b64encode(payloads[filename]).decode("ascii"),
            }
            for filename in sorted(payloads)
        ],
    }
    try:
        _recovery_v2_prepare_repository_directory(
            _LIVE_BUNDLE_CACHE_PATH.parent,
            repository_root=_REPOSITORY_ROOT,
        )
        _write_receipt(
            _LIVE_BUNDLE_CACHE_PATH,
            cache_document,
            exclusive=True,
        )
    except FileExistsError:
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        ) from None
    except RecoveryV2ControllerError:
        raise
    except (ChronosProductionError, OSError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RECEIPT_INVALID") from None


def _terminalize_current_stage(
    *,
    stage: str,
    main_sha: str,
    run_id: int,
    inputs: Mapping[str, str],
    pre_effect_proof: Mapping[str, object] | None = None,
    token: str,
    run_loader: Callable[[str, str], Mapping[str, object]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    success_loader: Callable[..., dict[str, Any]] | None = None,
    failure_loader: Callable[..., dict[str, Any]] | None = None,
    bundle_loader: Callable[..., dict[str, Any]] | None = None,
    terminalization_deadline_epoch: float,
) -> dict[str, object]:
    """Wait, attest, and semantically decide one already-consumed workflow dispatch."""

    load_run = run_loader or (
        lambda path, supplied_token: _github_get(
            path,
            supplied_token,
            effect_deadline_epoch=terminalization_deadline_epoch,
        )
    )
    terminal_run, observations = _wait_for_terminal_run(
        stage=stage,
        main_sha=main_sha,
        run_id=run_id,
        token=token,
        run_loader=load_run,
        sleeper=sleeper,
        clock=clock,
        terminalization_deadline_epoch=terminalization_deadline_epoch,
    )
    conclusion = terminal_run["conclusion"]
    run_id_text = str(run_id)
    if conclusion != "success":
        proof: dict[str, object] = {
            "outcome": "FAILURE",
            "terminal_run": terminal_run,
            "run_observations": observations,
            "failure_class": "WORKFLOW_TERMINAL_NON_SUCCESS",
        }
        if conclusion == "failure":
            load_failure = failure_loader or attest_and_download_failure_v2
            with tempfile.TemporaryDirectory(prefix="robin-controller-failure-v2-") as name:
                try:
                    proof["failure_attestation"] = load_failure(
                        stage=stage,
                        run_id=run_id_text,
                        main_sha=main_sha,
                    output_path=Path(name) / "sanitized-failure.json",
                    effect_deadline_epoch=terminalization_deadline_epoch,
                    )
                except Exception as error:
                    proof["failure_attestation_status"] = "AMBIGUOUS_OR_MISSING"
                    proof["failure_attestation_code"] = (
                        str(error)
                        if isinstance(error, RecoveryV2ControllerError)
                        else "RECOVERY_V2_CONTROLLER_FAILURE_ATTESTATION_INVALID"
                    )
        return proof

    if stage == "LIVE_ONCE":
        from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import _ARTIFACT_NAMES

        load_bundle = bundle_loader or attest_and_download_bundle_v2
        with tempfile.TemporaryDirectory(prefix="robin-controller-live-v2-") as name:
            bundle_dir = Path(name) / "bundle"
            try:
                attestation = load_bundle(
                    repository=EXPECTED_REPOSITORY,
                    workflow_path=".github/workflows/data-torrent-live-v2.yml",
                    run_id=run_id_text,
                    main_sha=main_sha,
                    artifact_name=f"data-torrent-live-v2-{run_id_text}",
                    expected_filenames=_ARTIFACT_NAMES,
                    output_dir=bundle_dir,
                    effect_deadline_epoch=terminalization_deadline_epoch,
                )
            except Exception as error:
                return {
                    "outcome": "AMBIGUOUS",
                    "terminal_run": terminal_run,
                    "run_observations": observations,
                    "failure_class": "WORKFLOW_SUCCESS_ATTESTATION_AMBIGUOUS",
                    "failure_code": (
                        str(error)
                        if isinstance(error, RecoveryV2ControllerError)
                        else "RECOVERY_V2_CONTROLLER_LIVE_ATTESTATION_INVALID"
                    ),
                }
            try:
                if pre_effect_proof is None:
                    raise RecoveryV2ControllerError(
                        "RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID"
                    )
                semantics = _validate_live_success_bundle(
                    bundle_dir=bundle_dir,
                    main_sha=main_sha,
                    run_id=run_id_text,
                    inputs=inputs,
                    pre_effect_proof=pre_effect_proof,
                )
                _cache_validated_live_bundle(
                    bundle_dir=bundle_dir,
                    attestation=attestation,
                    main_sha=main_sha,
                    run_id=run_id_text,
                )
            except Exception as error:
                return {
                    "outcome": "FAILURE",
                    "terminal_run": terminal_run,
                    "run_observations": observations,
                    "attestation": attestation,
                    "failure_class": "WORKFLOW_SUCCESS_SEMANTIC_NO_GO",
                    "failure_code": (
                        str(error)
                        if isinstance(error, RecoveryV2ControllerError)
                        else "RECOVERY_V2_CONTROLLER_LIVE_SEMANTICS_INVALID"
                    ),
                }
        return {
            "outcome": "SUCCESS",
            "terminal_run": terminal_run,
            "run_observations": observations,
            "attestation": attestation,
            "semantic_verdict": "DATA_TORRENT_READY",
            "semantic_projection_sha256": _object_sha256(semantics),
        }

    artifact = _SUCCESS_ARTIFACTS[stage]
    load_success = success_loader or attest_and_download_v2
    with tempfile.TemporaryDirectory(prefix="robin-controller-success-v2-") as name:
        output = Path(name) / artifact["artifact_filename"]
        try:
            attestation = load_success(
                repository=EXPECTED_REPOSITORY,
                workflow_path=artifact["workflow_path"],
                run_id=run_id_text,
                main_sha=main_sha,
                artifact_name=artifact["artifact_prefix"] + run_id_text,
                artifact_filename=artifact["artifact_filename"],
                output_path=output,
                effect_deadline_epoch=terminalization_deadline_epoch,
            )
        except Exception as error:
            return {
                "outcome": "AMBIGUOUS",
                "terminal_run": terminal_run,
                "run_observations": observations,
                "failure_class": "WORKFLOW_SUCCESS_ATTESTATION_AMBIGUOUS",
                "failure_code": (
                    str(error)
                    if isinstance(error, RecoveryV2ControllerError)
                    else "RECOVERY_V2_CONTROLLER_SUCCESS_ATTESTATION_INVALID"
                ),
            }
        try:
            payload, document = _strict_temporary_json_document(
                output,
                maximum_bytes=10 * 1024 * 1024,
            )
            _validate_success_attestation(
                stage=stage,
                main_sha=main_sha,
                run_id=run_id_text,
                payload=payload,
                attestation=attestation,
            )
            _validate_stage_success_document(
                stage=stage,
                document=document,
                main_sha=main_sha,
                run_id=run_id_text,
                inputs=inputs,
            )
            _cache_validated_predecessor(
                kind=artifact["kind"],
                artifact_filename=artifact["artifact_filename"],
                payload=payload,
                attestation=attestation,
            )
        except Exception as error:
            return {
                "outcome": "FAILURE",
                "terminal_run": terminal_run,
                "run_observations": observations,
                "attestation": attestation,
                "failure_class": "WORKFLOW_SUCCESS_SEMANTIC_NO_GO",
                "failure_code": (
                    str(error)
                    if isinstance(error, RecoveryV2ControllerError)
                    else "RECOVERY_V2_CONTROLLER_SUCCESS_SEMANTICS_INVALID"
                ),
            }
    return {
        "outcome": "SUCCESS",
        "terminal_run": terminal_run,
        "run_observations": observations,
        "attestation": attestation,
        "semantic_verdict": artifact["semantic_verdict"],
    }


def _validate_dispatch_ordinal(
    *,
    stage: str,
    main_sha: str,
    inputs: Mapping[str, str],
    token: str,
    expected_prior_run_ids: list[int],
    effect_deadline_epoch: float | None = None,
) -> dict[str, object]:
    contract = STAGES[stage]
    workflow = cast(str, contract["workflow"])
    expected_count = cast(int, contract["expected_prior_dispatches"])
    try:
        cutoff = datetime.fromisoformat(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE.replace("Z", "+00:00"))
        document = _github_get(
            f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/{workflow}/runs"
            "?event=workflow_dispatch&per_page=100",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    except (ChronosProductionError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID") from None
    runs = document.get("workflow_runs")
    total = document.get("total_count")
    if (
        not isinstance(runs, list)
        or type(total) is not int
        or total != len(runs)
        or total > 100
        or any(not isinstance(item, dict) for item in runs)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
    authority_runs: list[tuple[datetime, int, dict[str, Any]]] = []
    seen: set[int] = set()
    for raw in runs:
        run = cast(dict[str, Any], raw)
        identifier = run.get("id")
        created_at = run.get("created_at")
        if (
            type(identifier) is not int
            or identifier <= 0
            or identifier in seen
            or run.get("event") != "workflow_dispatch"
            or not isinstance(created_at, str)
            or not created_at.endswith("Z")
            or type(run.get("run_attempt")) is not int
            or run.get("run_attempt") != 1
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
        seen.add(identifier)
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID") from None
        if created.tzinfo is None or created.utcoffset() != UTC.utcoffset(created):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
        if created >= cutoff:
            if (
                run.get("head_branch") != "main"
                or run.get("head_sha") != main_sha
                or (expected_count > 0 and run.get("status") != "completed")
                or (expected_count > 0 and run.get("conclusion") != "success")
            ):
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
            authority_runs.append((created, identifier, run))
    if (
        len(authority_runs) != expected_count
        or len(expected_prior_run_ids) != expected_count
        or any(
            type(identifier) is not int or identifier <= 0 for identifier in expected_prior_run_ids
        )
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
    authority_runs.sort(key=lambda item: (item[0], item[1]))
    observed_ids = [item[1] for item in authority_runs]
    if observed_ids != expected_prior_run_ids:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ORDINAL_INVALID")
    return {
        "authority_window_not_before": DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        "expected_prior_dispatches": expected_count,
        "observed_prior_dispatches": len(authority_runs),
        "observed_prior_run_ids": observed_ids,
    }


def _bounded_response_body(response: requests.Response) -> bytes:
    raw_headers = getattr(response.raw, "headers", None)
    getlist = getattr(raw_headers, "getlist", None)
    lengths = (
        [str(value) for value in getlist("Content-Length")]
        if callable(getlist)
        else ([response.headers["Content-Length"]] if "Content-Length" in response.headers else [])
    )
    if len(lengths) > 1:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    declared: int | None = None
    if lengths:
        try:
            declared = int(lengths[0])
        except ValueError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS") from None
        if declared < 0 or declared > _MAX_MUTATION_RESPONSE_BYTES:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    if response.headers.get("Content-Encoding", "identity").casefold() != "identity":
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not isinstance(chunk, bytes):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
        body.extend(chunk)
        if len(body) > _MAX_MUTATION_RESPONSE_BYTES:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    if declared is not None and declared != len(body):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    return bytes(body)


def _canonical_controller_receipt(stage: str) -> Path:
    return (
        _REPOSITORY_ROOT
        / ".torrent"
        / "release"
        / f"recovery-v2-controller-{stage.casefold().replace('_', '-')}.json"
    )


def _canonical_quarantine_receipt() -> Path:
    return (
        _REPOSITORY_ROOT
        / ".torrent"
        / "release"
        / "recovery-v2-postmerge-quarantine.json"
    )


def _canonical_provider_neutralization_receipt() -> Path:
    return (
        _REPOSITORY_ROOT
        / ".torrent"
        / "release"
        / "recovery-v2-provider-neutralization.json"
    )


def _same_repository_path(left: Path, right: Path) -> bool:
    return Path(os.path.abspath(left)) == Path(os.path.abspath(right))


def _bounded_git_arguments_valid(arguments: tuple[str, ...]) -> bool:
    if not arguments:
        return False
    if arguments[0] == "cat-file":
        return (
            len(arguments) == 3
            and arguments[1] == "-e"
            and arguments[2].endswith("^{commit}")
            and re.fullmatch(r"[0-9a-f]{40}\^\{commit\}", arguments[2]) is not None
        )
    if arguments[0] == "merge-base":
        return (
            len(arguments) == 4
            and arguments[1] == "--is-ancestor"
            and all(re.fullmatch(r"[0-9a-f]{40}", value) for value in arguments[2:])
        )
    if arguments[0] == "ls-remote":
        return arguments == (
            "ls-remote",
            "--refs",
            _EXPECTED_PUSH_URL,
            "refs/heads/main",
            _LEGACY_PROVIDER_REF,
        )
    if arguments[0] == "push":
        return (
            len(arguments) == 4
            and arguments[:3] == ("push", "--porcelain", _EXPECTED_PUSH_URL)
            and re.fullmatch(
                rf"[0-9a-f]{{40}}:{re.escape(_LEGACY_PROVIDER_REF)}",
                arguments[3],
            )
            is not None
        )
    return False


def _local_git_object_directory(environment: Mapping[str, str]) -> Path:
    try:
        result = run_captured_child_once(
            (
                "git",
                "--no-replace-objects",
                "-c",
                "credential.helper=",
                "-c",
                "core.hooksPath=",
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ),
            cwd=_REPOSITORY_ROOT,
            environment=environment,
            timeout_seconds=10,
            maximum_stdout_bytes=32_768,
            maximum_stderr_bytes=32_768,
        )
    except (OSError, RecoveryV2SupervisionError):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    if (
        result.returncode != 0
        or len(result.stdout) > 32_768
        or len(result.stderr) > 32_768
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS")
    try:
        common_text = result.stdout.decode("utf-8", errors="strict").strip()
        result.stderr.decode("utf-8", errors="strict")
        common = Path(common_text)
        if (
            not common_text
            or "\n" in common_text
            or "\r" in common_text
            or not common.is_absolute()
        ):
            raise ValueError
        objects = common / "objects"
        resolved = objects.resolve(strict=True)
        if not resolved.is_dir() or _recovery_v2_path_is_reparse(resolved):
            raise ValueError
    except (OSError, UnicodeDecodeError, ValueError):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    return resolved


def _run_bounded_git(
    arguments: tuple[str, ...],
    *,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> str:
    if not _bounded_git_arguments_valid(arguments):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS")
    network_operation = arguments[0] in {"ls-remote", "push"}
    if network_operation:
        if effect_deadline_epoch is None:
            raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS")
        monotonic_now = time.monotonic()
        if effect_deadline_monotonic is None:
            wall_now = time.time()
            initial_remaining = _require_effect_window(
                effect_deadline_epoch,
                margin_seconds=CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS + 1.0,
                observed_epoch=wall_now,
            )
            effect_deadline_monotonic = monotonic_now + initial_remaining
        elif (
            isinstance(effect_deadline_monotonic, bool)
            or not isinstance(effect_deadline_monotonic, (int, float))
            or not math.isfinite(float(effect_deadline_monotonic))
            or float(effect_deadline_monotonic) - monotonic_now
            <= CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS + 1.0
        ):
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED"
            )
        effect_deadline_monotonic = float(effect_deadline_monotonic)
    inherited_names = {
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
    }
    environment = {name: os.environ[name] for name in inherited_names if name in os.environ}
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GCM_INTERACTIVE": "never",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "LC_ALL": "C",
        }
    )
    try:
        object_directory = _local_git_object_directory(environment)
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-git-isolation-") as name:
            isolation = Path(name)
            hooks = isolation / "hooks"
            hooks.mkdir()
            bare_repository = isolation / "repository.git"
            askpass_python = isolation / "askpass.py"
            askpass_python.write_text(
                "import os, sys\n"
                "prompt = sys.argv[1] if len(sys.argv) == 2 else ''\n"
                "if 'Username' in prompt:\n"
                "    print('x-access-token')\n"
                "elif 'Password' in prompt:\n"
                "    token = os.environ.get('RECOVERY_V2_GIT_ASKPASS_TOKEN', '')\n"
                "    if not token:\n"
                "        raise SystemExit(1)\n"
                "    print(token)\n"
                "else:\n"
                "    raise SystemExit(1)\n",
                encoding="utf-8",
                newline="\n",
            )
            if os.name == "nt":
                askpass = isolation / "askpass.cmd"
                askpass.write_text(
                    f'@"{sys.executable}" "{askpass_python}" %*\r\n',
                    encoding="utf-8",
                    newline="",
                )
            else:
                askpass = isolation / "askpass"
                askpass.write_text(
                    f"#!{sys.executable}\nexec({askpass_python.read_text(encoding='utf-8')!r})\n",
                    encoding="utf-8",
                    newline="\n",
                )
                askpass.chmod(0o700)
            environment.update(
                {
                    "GIT_ASKPASS": str(askpass),
                    "GIT_ASKPASS_REQUIRE": "force",
                    "RECOVERY_V2_GIT_ASKPASS_TOKEN": (
                        os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
                    ),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(object_directory),
                }
            )
            initialized = run_captured_child_once(
                ("git", "init", "--bare", "--quiet", str(bare_repository)),
                cwd=isolation,
                environment=environment,
                timeout_seconds=10,
                maximum_stdout_bytes=32_768,
                maximum_stderr_bytes=32_768,
            )
            if (
                initialized.returncode != 0
                or len(initialized.stdout) > 32_768
                or len(initialized.stderr) > 32_768
            ):
                raise RecoveryV2ControllerError(
                    "RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS"
                )
            try:
                initialized.stdout.decode("utf-8", errors="strict")
                initialized.stderr.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise RecoveryV2ControllerError(
                    "RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS"
                ) from None
            command = (
                "git",
                "--no-replace-objects",
                f"--git-dir={bare_repository}",
                "-c",
                f"core.hooksPath={hooks}",
                "-c",
                "credential.helper=",
                "-c",
                "credential.https://github.com.helper=",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "push.followTags=false",
                "-c",
                "push.recurseSubmodules=no",
                "-c",
                "submodule.recurse=false",
                "-c",
                "remote.origin.mirror=false",
                "-c",
                "http.followRedirects=false",
                "-c",
                "http.proxy=",
                "-c",
                "https.proxy=",
                "-c",
                "http.sslVerify=true",
                "-c",
                "http.extraHeader=",
                "-c",
                "http.curloptResolve=",
                "-c",
                "http.maxRequests=1",
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.https.allow=always",
                *arguments,
            )
            command_timeout = _GIT_COMMAND_TIMEOUT_SECONDS
            command_deadline_monotonic: float | None = None
            cleanup_deadline_monotonic: float | None = None
            if network_operation:
                if effect_deadline_epoch is None or effect_deadline_monotonic is None:
                    raise RecoveryV2ControllerError(
                        "RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS"
                    )
                observed_epoch = time.time()
                observed_monotonic = time.monotonic()
                wall_remaining = _require_effect_window(
                    effect_deadline_epoch,
                    margin_seconds=CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS + 1.0,
                    observed_epoch=observed_epoch,
                )
                monotonic_remaining = effect_deadline_monotonic - observed_monotonic
                if monotonic_remaining <= CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS + 1.0:
                    raise RecoveryV2ControllerError(
                        "RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED"
                    )
                cleanup_remaining = min(wall_remaining, monotonic_remaining)
                cleanup_deadline_monotonic = observed_monotonic + cleanup_remaining
                command_remaining = min(
                    float(command_timeout),
                    cleanup_remaining - CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS,
                )
                if command_remaining <= 1.0:
                    raise RecoveryV2ControllerError(
                        "RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED"
                    )
                command_deadline_monotonic = observed_monotonic + command_remaining
                command_timeout = min(command_timeout, math.floor(command_remaining))
            result = run_captured_child_once(
                command,
                cwd=isolation,
                environment=environment,
                timeout_seconds=command_timeout,
                maximum_stdout_bytes=_GIT_OUTPUT_LIMIT_BYTES,
                maximum_stderr_bytes=_GIT_OUTPUT_LIMIT_BYTES,
                absolute_deadline_monotonic=command_deadline_monotonic,
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            )
    except (OSError, RecoveryV2SupervisionError):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    deadline_crossed = (
        network_operation
        and effect_deadline_epoch is not None
        and effect_deadline_monotonic is not None
        and (
            time.time() >= effect_deadline_epoch
            or time.monotonic() >= effect_deadline_monotonic
        )
    )
    if (
        result.returncode != 0
        or len(result.stdout) > _GIT_OUTPUT_LIMIT_BYTES
        or len(result.stderr) > _GIT_OUTPUT_LIMIT_BYTES
        or deadline_crossed
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS")
    try:
        output = result.stdout.decode("utf-8", errors="strict")
        result.stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    return output


def _observe_provider_refs(
    git_runner: Callable[[tuple[str, ...]], str],
) -> dict[str, str]:
    output = git_runner(
        (
            "ls-remote",
            "--refs",
            _EXPECTED_PUSH_URL,
            "refs/heads/main",
            _LEGACY_PROVIDER_REF,
        )
    )
    observed: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[1] not in {"refs/heads/main", _LEGACY_PROVIDER_REF}:
            raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_REF_OBSERVATION_INVALID")
        sha, ref = fields
        if ref in observed:
            raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_REF_OBSERVATION_INVALID")
        try:
            observed[ref] = require_sha(sha, field="provider_remote_sha")
        except ChronosProductionError:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_PROVIDER_REF_OBSERVATION_INVALID"
            ) from None
    if set(observed) != {"refs/heads/main", _LEGACY_PROVIDER_REF}:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_REF_OBSERVATION_INVALID")
    return observed


def run_legacy_provider_branch_neutralization(
    *,
    main_sha: str,
    receipt_path: Path,
    git_runner: Callable[[tuple[str, ...]], str] | None = None,
    pre_hold_validator: Callable[[], Mapping[str, object]] | None = None,
    post_hold_validator: Callable[[], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Guard the sole authorized ordinary fast-forward provider ref update."""

    try:
        assert_production_safety_locks(os.environ)
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage="E1"
        )
        validate_data_torrent_recovery_v2_council_release()
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_AUTHORITY_INVALID") from None
    deadline_anchor_monotonic = time.monotonic()
    deadline_anchor_epoch = time.time()
    effect_deadline_epoch = _operation_deadline_epoch(
        authority_deadline,
        maximum_runtime_seconds=_LOCAL_E1_STAGE_TIMEOUT_SECONDS,
        observed_epoch=deadline_anchor_epoch,
    )
    effect_deadline_monotonic = deadline_anchor_monotonic + (
        effect_deadline_epoch - deadline_anchor_epoch
    )
    expected_sha = require_sha(main_sha, field="main_sha")
    if expected_sha == DATA_TORRENT_RECOVERY_V2_START_SHA:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TARGET_INVALID")
    if not _same_repository_path(receipt_path, _canonical_provider_neutralization_receipt()):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_RECEIPT_PATH_FORBIDDEN")

    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > 2_048:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TOKEN_MISSING")
    try:
        _recovery_v2_prepare_repository_directory(
            receipt_path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_RECEIPT_PATH_FORBIDDEN") from None
    if os.path.lexists(receipt_path):
        try:
            _recovery_v2_require_repository_file(
                receipt_path,
                repository_root=_REPOSITORY_ROOT,
            )
        except ChronosProductionError:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_PROVIDER_RECEIPT_PATH_FORBIDDEN"
            ) from None
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        )
    try:
        _recovery_v2_require_unused_repository_output(
            receipt_path,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_RECEIPT_PATH_FORBIDDEN") from None
    initial_reservation: dict[str, object] = {
        "schema_version": "data-torrent-recovery-v2-provider-neutralization-reservation-v1",
        "verdict": "INVOCATION_RESERVED_BEFORE_EXTERNAL_READ",
        "branch": _LEGACY_PROVIDER_BRANCH,
        "target_main_sha": expected_sha,
        "automatic_retries": 0,
    }
    _write_receipt(receipt_path, initial_reservation, exclusive=True)
    validate_pre_hold = pre_hold_validator or (
        lambda: verify_hold(
            required_successful_ci_sha=expected_sha,
            recovery_v2=True,
            recovery_v2_provider_precondition=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )
    try:
        _require_effect_window(effect_deadline_epoch)
        pre_hold = dict(validate_pre_hold())
        _validated_post_merge_hold(
            pre_hold,
            main_sha=expected_sha,
            allow_new_active=True,
            expected_legacy_sha=DATA_TORRENT_RECOVERY_V2_START_SHA,
        )
    except (ChronosProductionError, RecoveryV2ControllerError):
        try:
            _write_receipt(
                receipt_path,
                {**initial_reservation, "verdict": "FAIL_AND_STOP"},
            )
        except RecoveryV2ControllerError:
            pass
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_PRECONDITION_INVALID") from None

    reservation: dict[str, object] = {
        "schema_version": "data-torrent-recovery-v2-provider-neutralization-v1",
        "verdict": "INVOCATION_RESERVED",
        "branch": _LEGACY_PROVIDER_BRANCH,
        "required_current_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "target_main_sha": expected_sha,
        "fast_forward_ancestry_confirmed": False,
        "push_mode": "ORDINARY_NON_FORCE_FAST_FORWARD",
        "push_attempts": 0,
        "remote_ref_observations": 0,
        "non_fast_forward_updates": 0,
        "branch_deletes": 0,
        "automatic_retries": 0,
        "pre_hold": pre_hold,
        "pre_hold_sha256": _object_sha256(pre_hold),
    }
    _write_receipt(receipt_path, reservation)

    selected_git_runner = _run_bounded_git if git_runner is None else git_runner

    def bounded_git(arguments: tuple[str, ...]) -> str:
        _require_effect_window(effect_deadline_epoch)
        if time.monotonic() >= effect_deadline_monotonic:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED"
            )
        if selected_git_runner is _run_bounded_git:
            return _run_bounded_git(
                arguments,
                effect_deadline_epoch=effect_deadline_epoch,
                effect_deadline_monotonic=effect_deadline_monotonic,
            )
        return selected_git_runner(arguments)

    try:
        bounded_git(("cat-file", "-e", f"{DATA_TORRENT_RECOVERY_V2_START_SHA}^{{commit}}"))
        bounded_git(("cat-file", "-e", f"{expected_sha}^{{commit}}"))
        bounded_git(
            (
                "merge-base",
                "--is-ancestor",
                DATA_TORRENT_RECOVERY_V2_START_SHA,
                expected_sha,
            )
        )
        before = _observe_provider_refs(bounded_git)
    except RecoveryV2ControllerError:
        try:
            _write_receipt(receipt_path, {**reservation, "verdict": "FAIL_AND_STOP"})
        except RecoveryV2ControllerError:
            pass
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_PRECONDITION_INVALID") from None
    reservation = {
        **reservation,
        "fast_forward_ancestry_confirmed": True,
        "remote_ref_observations": 1,
    }
    _write_receipt(receipt_path, reservation)
    if (
        before["refs/heads/main"] != expected_sha
        or before[_LEGACY_PROVIDER_REF] != DATA_TORRENT_RECOVERY_V2_START_SHA
    ):
        _write_receipt(receipt_path, {**reservation, "verdict": "FAIL_AND_STOP"})
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_PRECONDITION_INVALID")
    attempted = {**reservation, "verdict": "PUSH_ATTEMPT_RESERVED", "push_attempts": 1}
    _write_receipt(receipt_path, attempted)
    try:
        bounded_git(
            (
                "push",
                "--porcelain",
                _EXPECTED_PUSH_URL,
                f"{expected_sha}:{_LEGACY_PROVIDER_REF}",
            )
        )
    except RecoveryV2ControllerError:
        try:
            _write_receipt(receipt_path, {**attempted, "verdict": "FAIL_AND_STOP"})
        except RecoveryV2ControllerError:
            pass
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    post_observation = {
        **attempted,
        "verdict": "POST_PUSH_OBSERVATION_RESERVED",
        "remote_ref_observations": 2,
    }
    _write_receipt(receipt_path, post_observation)
    try:
        after = _observe_provider_refs(bounded_git)
    except RecoveryV2ControllerError:
        try:
            _write_receipt(
                receipt_path,
                {**post_observation, "verdict": "FAIL_AND_STOP"},
            )
        except RecoveryV2ControllerError:
            pass
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS") from None
    if after != {
        "refs/heads/main": expected_sha,
        _LEGACY_PROVIDER_REF: expected_sha,
    }:
        _write_receipt(
            receipt_path,
            {
                **post_observation,
                "verdict": "FAIL_AND_STOP",
            },
        )
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_POSTCONDITION_INVALID")
    validate_post_hold = post_hold_validator or (
        lambda: verify_hold(
            required_successful_ci_sha=expected_sha,
            recovery_v2=True,
            recovery_v2_quarantine_precondition=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )
    try:
        _require_effect_window(effect_deadline_epoch)
        post_hold = dict(validate_post_hold())
        _validated_post_merge_hold(
            post_hold,
            main_sha=expected_sha,
            allow_new_active=True,
        )
    except (ChronosProductionError, RecoveryV2ControllerError):
        _write_receipt(
            receipt_path,
            {
                **post_observation,
                "verdict": "FAIL_AND_STOP",
            },
        )
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_POSTCONDITION_INVALID") from None
    receipt = {
        **post_observation,
        "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
        "confirmed_sha": expected_sha,
        "post_hold": post_hold,
        "post_hold_sha256": _object_sha256(post_hold),
    }
    _write_receipt(receipt_path, receipt)
    return receipt


def _write_receipt(path: Path, document: Mapping[str, object], *, exclusive: bool = False) -> None:
    payload = (json.dumps(dict(document), sort_keys=True) + "\n").encode("utf-8")
    try:
        _recovery_v2_prepare_repository_directory(
            path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
        if exclusive:
            _recovery_v2_publish_exclusive_bytes(
                path,
                payload,
                repository_root=_REPOSITORY_ROOT,
            )
            return
        _recovery_v2_replace_bytes(
            path,
            payload,
            repository_root=_REPOSITORY_ROOT,
        )
    except FileExistsError:
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        ) from None
    except (ChronosProductionError, OSError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RECEIPT_INVALID") from None


def _validated_post_merge_hold(
    observed: Mapping[str, object],
    *,
    main_sha: str,
    allow_new_active: bool,
    expected_legacy_sha: str | None = None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    post_merge = observed.get("post_merge_ci")
    scope_job = observed.get("recovery_v2_scope_guard")
    quarantine = observed.get("recovery_v2_production_workflow_quarantine")
    legacy_ci = observed.get("legacy_ci_workflow_quarantine")
    nonterminal = observed.get("nonterminal_run_counts")
    environment = observed.get("production_environment_policy")
    if (
        set(observed) != _RECOVERY_HOLD_FIELDS
        or observed.get("schema_version") != "chronos-production-workflow-hold-live-v3"
        or observed.get("verdict") != "WORKFLOW_HOLD_ESTABLISHED"
        or type(observed.get("active_after")) is not int
        or cast(int, observed["active_after"]) < 0
        or type(observed.get("disabled_after")) is not int
        or cast(int, observed["disabled_after"]) < 0
        or any(
            type(observed.get(field)) is not int
            for field in {
                "queued_after",
                "in_progress_after",
                "current_run_excluded",
                "provider_calls",
                "r2_operations",
            }
        )
        or observed.get("queued_after") != 0
        or observed.get("in_progress_after") != 0
        or not isinstance(nonterminal, dict)
        or any(type(value) is not int for value in nonterminal.values())
        or nonterminal
        != {"requested": 0, "waiting": 0, "pending": 0, "queued": 0, "in_progress": 0}
        or observed.get("current_run_excluded") != 0
        or observed.get("unauthorized_active_workflows") != []
        or observed.get("legacy_secret_branch_sha") != (expected_legacy_sha or main_sha)
        or observed.get("provider_calls") != 0
        or observed.get("r2_operations") != 0
        or not isinstance(post_merge, dict)
        or set(post_merge)
        != {
            "workflow_path",
            "run_id",
            "run_attempt",
            "head_sha",
            "head_branch",
            "event",
            "status",
            "conclusion",
        }
        or post_merge.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or type(post_merge.get("run_id")) is not int
        or cast(int, post_merge["run_id"]) <= 0
        or type(post_merge.get("run_attempt")) is not int
        or post_merge.get("run_attempt") != 1
        or post_merge.get("head_sha") != main_sha
        or post_merge.get("head_branch") != "main"
        or post_merge.get("event") != "push"
        or post_merge.get("status") != "completed"
        or post_merge.get("conclusion") != "success"
        or not isinstance(scope_job, dict)
        or set(scope_job) != {"job_id", "name", "run_id", "head_sha", "status", "conclusion"}
        or type(scope_job.get("job_id")) is not int
        or cast(int, scope_job["job_id"]) <= 0
        or type(scope_job.get("run_id")) is not int
        or scope_job.get("name") != "Recovery V2 — scope guard exact"
        or scope_job.get("run_id") != post_merge.get("run_id")
        or scope_job.get("head_sha") != main_sha
        or scope_job.get("status") != "completed"
        or scope_job.get("conclusion") != "success"
        or not isinstance(legacy_ci, dict)
        or set(legacy_ci) != {"workflow_id", "workflow_path", "state"}
        or type(legacy_ci.get("workflow_id")) is not int
        or cast(int, legacy_ci["workflow_id"]) <= 0
        or legacy_ci.get("workflow_path") != ".github/workflows/ci.yml"
        or legacy_ci.get("state") != "disabled_manually"
        or not isinstance(environment, dict)
        or set(environment)
        != {
            "environment",
            "can_admins_bypass",
            "protected_branches",
            "custom_branch_policies",
            "allowed_branches",
        }
        or environment.get("environment") != "chronos-control-plane-production"
        or environment.get("can_admins_bypass") is not False
        or environment.get("protected_branches") is not False
        or environment.get("custom_branch_policies") is not True
        or environment.get("allowed_branches") != ["main"]
        or not isinstance(quarantine, list)
        or len(quarantine) != len(RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS)
        or any(not isinstance(item, dict) for item in quarantine)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
    inventory: dict[str, dict[str, object]] = {}
    for raw in quarantine:
        entry = cast(dict[str, object], raw)
        path = entry.get("workflow_path")
        if (
            set(entry) != {"workflow_id", "workflow_path", "state"}
            or not isinstance(path, str)
            or path not in RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS
            or path in inventory
            or type(entry.get("workflow_id")) is not int
            or cast(int, entry["workflow_id"]) <= 0
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
        allowed_states = (
            {"active", "disabled_manually"}
            if allow_new_active and path in RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS
            else {"disabled_manually"}
        )
        if entry.get("state") not in allowed_states:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
        inventory[path] = entry
    if set(inventory) != RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
    canonical_inventory = [dict(inventory[path]) for path in sorted(inventory)]
    if quarantine != canonical_inventory:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
    new_inventory = [dict(inventory[path]) for path in _QUARANTINE_WORKFLOWS]
    return cast(dict[str, object], post_merge), new_inventory


def _validate_provider_neutralization_receipt(*, main_sha: str) -> dict[str, object]:
    payload, receipt = _strict_json_document(
        _canonical_provider_neutralization_receipt(), maximum_bytes=512 * 1024
    )
    expected_fields = {
        "schema_version",
        "verdict",
        "branch",
        "required_current_sha",
        "target_main_sha",
        "fast_forward_ancestry_confirmed",
        "push_mode",
        "push_attempts",
        "remote_ref_observations",
        "non_fast_forward_updates",
        "branch_deletes",
        "automatic_retries",
        "pre_hold",
        "pre_hold_sha256",
        "confirmed_sha",
        "post_hold",
        "post_hold_sha256",
    }
    pre_hold = receipt.get("pre_hold")
    post_hold = receipt.get("post_hold")
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version") != "data-torrent-recovery-v2-provider-neutralization-v1"
        or receipt.get("verdict") != "LEGACY_PROVIDER_BRANCH_NEUTRALIZED"
        or receipt.get("branch") != _LEGACY_PROVIDER_BRANCH
        or receipt.get("required_current_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or receipt.get("target_main_sha") != main_sha
        or receipt.get("fast_forward_ancestry_confirmed") is not True
        or receipt.get("push_mode") != "ORDINARY_NON_FORCE_FAST_FORWARD"
        or any(
            type(receipt.get(field)) is not int
            for field in {
                "push_attempts",
                "remote_ref_observations",
                "non_fast_forward_updates",
                "branch_deletes",
                "automatic_retries",
            }
        )
        or receipt.get("push_attempts") != 1
        or receipt.get("remote_ref_observations") != 2
        or receipt.get("non_fast_forward_updates") != 0
        or receipt.get("branch_deletes") != 0
        or receipt.get("automatic_retries") != 0
        or receipt.get("confirmed_sha") != main_sha
        or not isinstance(pre_hold, dict)
        or not isinstance(post_hold, dict)
        or receipt.get("pre_hold_sha256") != _object_sha256(pre_hold)
        or receipt.get("post_hold_sha256") != _object_sha256(post_hold)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_RECEIPT_INVALID")
    _validated_post_merge_hold(
        pre_hold,
        main_sha=main_sha,
        allow_new_active=True,
        expected_legacy_sha=DATA_TORRENT_RECOVERY_V2_START_SHA,
    )
    _validated_post_merge_hold(post_hold, main_sha=main_sha, allow_new_active=True)
    return {
        "path": ".torrent/release/recovery-v2-provider-neutralization.json",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
    }


def _validate_postmerge_quarantine_receipt(*, main_sha: str) -> dict[str, object]:
    payload, receipt = _strict_json_document(
        _canonical_quarantine_receipt(), maximum_bytes=256 * 1024
    )
    expected_fields = {
        "schema_version",
        "verdict",
        "main_sha",
        "automatic_retries",
        "pre_effect_proof",
        "pre_effect_proof_sha256",
        "initial_workflows",
        "disable_attempted_paths",
        "disable_confirmed_paths",
        "disable_outcomes",
        "unconfirmed_paths",
        "already_disabled_paths",
        "post_hold",
        "post_hold_sha256",
        "github_api_gets_upper_bound",
        "disable_attempts_maximum",
        "enable_mutations",
        "dispatch_mutations",
        "provider_neutralization_provenance",
    }
    initial = receipt.get("initial_workflows")
    attempted = receipt.get("disable_attempted_paths")
    confirmed = receipt.get("disable_confirmed_paths")
    outcomes = receipt.get("disable_outcomes")
    unconfirmed = receipt.get("unconfirmed_paths")
    already = receipt.get("already_disabled_paths")
    proof = receipt.get("pre_effect_proof")
    post_hold = receipt.get("post_hold")
    try:
        provider_provenance = _validate_provider_neutralization_receipt(main_sha=main_sha)
    except RecoveryV2ControllerError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID") from None
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version") != "data-torrent-recovery-v2-postmerge-quarantine-v1"
        or receipt.get("verdict") != "POSTMERGE_QUARANTINE_CONFIRMED"
        or receipt.get("main_sha") != main_sha
        or any(
            type(receipt.get(field)) is not int
            for field in {
                "automatic_retries",
                "github_api_gets_upper_bound",
                "disable_attempts_maximum",
                "enable_mutations",
                "dispatch_mutations",
            }
        )
        or receipt.get("automatic_retries") != 0
        or receipt.get("github_api_gets_upper_bound") != 25
        or receipt.get("disable_attempts_maximum") != 4
        or receipt.get("enable_mutations") != 0
        or receipt.get("dispatch_mutations") != 0
        or receipt.get("provider_neutralization_provenance") != provider_provenance
        or not isinstance(initial, list)
        or len(initial) != 4
        or any(not isinstance(item, dict) for item in initial)
        or not isinstance(attempted, list)
        or not isinstance(confirmed, list)
        or attempted != confirmed
        or any(not isinstance(path, str) for path in attempted)
        or not isinstance(outcomes, list)
        or not isinstance(unconfirmed, list)
        or unconfirmed != []
        or not isinstance(already, list)
        or any(not isinstance(path, str) for path in already)
        or not isinstance(proof, dict)
        or receipt.get("pre_effect_proof_sha256") != _object_sha256(proof)
        or not isinstance(post_hold, dict)
        or receipt.get("post_hold_sha256") != _object_sha256(post_hold)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID")
    initial_inventory: dict[str, dict[str, object]] = {}
    for raw in initial:
        entry = cast(dict[str, object], raw)
        path = entry.get("workflow_path")
        if (
            set(entry) != {"workflow_id", "workflow_path", "state"}
            or not isinstance(path, str)
            or path not in RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS
            or path in initial_inventory
            or type(entry.get("workflow_id")) is not int
            or cast(int, entry["workflow_id"]) <= 0
            or entry.get("state") not in {"active", "disabled_manually"}
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID")
        initial_inventory[path] = entry
    if set(initial_inventory) != RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID")
    canonical_initial = [dict(initial_inventory[path]) for path in _QUARANTINE_WORKFLOWS]
    active_paths = [
        path for path in _QUARANTINE_WORKFLOWS if initial_inventory[path]["state"] == "active"
    ]
    disabled_paths = [
        path
        for path in _QUARANTINE_WORKFLOWS
        if initial_inventory[path]["state"] == "disabled_manually"
    ]
    proof_post_merge = proof.get("post_merge_ci")
    proof_scope = proof.get("scope_guard")
    if (
        initial != canonical_initial
        or attempted != active_paths
        or outcomes
        != [
            {"workflow_path": path, "outcome": "CONFIRMED"}
            for path in active_paths
        ]
        or already != disabled_paths
        or set(proof)
        != {
            "post_merge_ci",
            "scope_guard",
            "current_main_sha",
            "global_queue_inventory_validations",
            "initial_workflows",
            "precondition_hold_sha256",
        }
        or proof.get("current_main_sha") != main_sha
        or proof.get("global_queue_inventory_validations") != 5
        or proof.get("initial_workflows") != canonical_initial
        or not isinstance(proof.get("precondition_hold_sha256"), str)
        or not isinstance(proof_post_merge, dict)
        or proof_post_merge.get("workflow_path") != ".github/workflows/ci-safe-v2.yml"
        or proof_post_merge.get("head_sha") != main_sha
        or proof_post_merge.get("head_branch") != "main"
        or proof_post_merge.get("event") != "push"
        or proof_post_merge.get("status") != "completed"
        or proof_post_merge.get("conclusion") != "success"
        or proof_post_merge.get("run_attempt") != 1
        or type(proof_post_merge.get("run_id")) is not int
        or cast(int, proof_post_merge["run_id"]) <= 0
        or not isinstance(proof_scope, dict)
        or proof_scope.get("name") != "Recovery V2 — scope guard exact"
        or proof_scope.get("run_id") != proof_post_merge.get("run_id")
        or proof_scope.get("head_sha") != main_sha
        or proof_scope.get("status") != "completed"
        or proof_scope.get("conclusion") != "success"
        or type(proof_scope.get("job_id")) is not int
        or cast(int, proof_scope["job_id"]) <= 0
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID")
    try:
        require_hash(
            cast(str, proof["precondition_hold_sha256"]),
            field="precondition_hold_sha256",
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_QUARANTINE_INVALID") from None
    _validated_post_merge_hold(post_hold, main_sha=main_sha, allow_new_active=False)
    return {
        "predecessor_kind": "LIVE_GITHUB_POSTMERGE_HOLD_V2",
        "predecessor_attestation": None,
        "predecessor_controller_receipt_sha256": None,
        "quarantine_journal_provenance": {
            "path": ".torrent/release/recovery-v2-postmerge-quarantine.json",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "authoritative": False,
        },
        "predecessor_semantic_verdict": "LIVE_GITHUB_HOLD_REPROVED_BY_CONTROLLER",
        "expected_prior_run_ids": [],
    }


def _validate_pre_effect_proof(
    *,
    stage: str,
    main_sha: str,
    inputs_sha256: str,
    proof: Mapping[str, object],
) -> None:
    """Re-prove every parent gate inside the private mutation child."""

    common_fields = {
        "stage_inputs",
        "predecessor_kind",
        "predecessor_attestation",
        "predecessor_semantic_verdict",
        "predecessor_controller_receipt_sha256",
        "expected_prior_run_ids",
        "authority_window_not_before",
        "expected_prior_dispatches",
        "observed_prior_dispatches",
        "observed_prior_run_ids",
        "post_merge_ci_run_id",
        "global_hold_full_validations",
        "live_postmerge_holds",
        "live_postmerge_hold_sha256",
        "current_main_sha",
    }
    expected_fields = set(common_fields)
    if stage == "RECOVERY_IDENTITY_V2":
        expected_fields.add("quarantine_journal_provenance")
    stage_inputs = proof.get("stage_inputs")
    live_holds = proof.get("live_postmerge_holds")
    prior_run_ids = proof.get("expected_prior_run_ids")
    observed_run_ids = proof.get("observed_prior_run_ids")
    if (
        stage not in STAGES
        or set(proof) != expected_fields
        or not isinstance(stage_inputs, dict)
        or not isinstance(live_holds, list)
        or len(live_holds) != 2
        or any(not isinstance(item, dict) for item in live_holds)
        or live_holds[0] != live_holds[1]
        or proof.get("current_main_sha") != main_sha
        or type(proof.get("global_hold_full_validations")) is not int
        or proof.get("global_hold_full_validations") != 2
        or not isinstance(proof.get("live_postmerge_hold_sha256"), str)
        or type(proof.get("post_merge_ci_run_id")) is not int
        or cast(int, proof["post_merge_ci_run_id"]) <= 0
        or proof.get("authority_window_not_before") != DATA_TORRENT_RECOVERY_V2_NOT_BEFORE
        or type(proof.get("expected_prior_dispatches")) is not int
        or type(proof.get("observed_prior_dispatches")) is not int
        or not isinstance(prior_run_ids, list)
        or not isinstance(observed_run_ids, list)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    live_hold = cast(dict[str, object], live_holds[0])
    if proof.get("live_postmerge_hold_sha256") != _object_sha256(live_hold):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    try:
        validated_inputs = _validate_inputs(
            stage=stage,
            main_sha=main_sha,
            inputs=stage_inputs,
            require_dispatch_binding=True,
        )
        require_hash(
            cast(str, proof["live_postmerge_hold_sha256"]),
            field="live_postmerge_hold_sha256",
        )
        _validated_post_merge_hold(
            live_hold,
            main_sha=main_sha,
            allow_new_active=False,
        )
    except (ChronosProductionError, RecoveryV2ControllerError):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID") from None
    if not hmac.compare_digest(_inputs_sha256(validated_inputs), inputs_sha256):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    post_merge = cast(dict[str, object], live_hold["post_merge_ci"])
    if proof.get("post_merge_ci_run_id") != post_merge.get("run_id"):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")

    expected_count = cast(int, STAGES[stage]["expected_prior_dispatches"])
    if (
        proof.get("expected_prior_dispatches") != expected_count
        or proof.get("observed_prior_dispatches") != expected_count
        or prior_run_ids != observed_run_ids
        or len(prior_run_ids) != expected_count
        or any(type(run_id) is not int or run_id <= 0 for run_id in prior_run_ids)
        or len(prior_run_ids) != len(set(cast(list[int], prior_run_ids)))
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")

    if stage == "RECOVERY_IDENTITY_V2":
        provenance = proof.get("quarantine_journal_provenance")
        if (
            proof.get("predecessor_kind") != "LIVE_GITHUB_POSTMERGE_HOLD_V2"
            or proof.get("predecessor_attestation") is not None
            or proof.get("predecessor_controller_receipt_sha256") is not None
            or proof.get("predecessor_semantic_verdict")
            != "LIVE_GITHUB_HOLD_REPROVED_BY_CONTROLLER"
            or prior_run_ids != []
            or not isinstance(provenance, dict)
            or set(provenance) != {"path", "sha256", "authoritative"}
            or provenance.get("path") != ".torrent/release/recovery-v2-postmerge-quarantine.json"
            or provenance.get("authoritative") is not False
            or not isinstance(provenance.get("sha256"), str)
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
        try:
            journal_payload, _journal = _strict_json_document(
                _canonical_quarantine_receipt(), maximum_bytes=256 * 1024
            )
            journal_hash = require_hash(
                cast(str, provenance["sha256"]), field="quarantine_journal_sha256"
            )
        except (ChronosProductionError, RecoveryV2ControllerError):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID") from None
        if not hmac.compare_digest(hashlib.sha256(journal_payload).hexdigest(), journal_hash):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
        return

    predecessor = _PREDECESSORS[stage]
    attestation = proof.get("predecessor_attestation")
    run_id = validated_inputs[predecessor["run_id_field"]]
    if (
        proof.get("predecessor_kind") != predecessor["kind"]
        or proof.get("predecessor_semantic_verdict") != _PREDECESSOR_SEMANTIC_VERDICTS[stage]
        or not isinstance(proof.get("predecessor_controller_receipt_sha256"), str)
        or not isinstance(attestation, dict)
        or set(attestation)
        != {
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
        or attestation.get("schema_version") != "github-artifact-attestation-v2"
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path") != predecessor["workflow_path"]
        or attestation.get("run_id") != run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != main_sha
        or type(attestation.get("artifact_id")) is not int
        or cast(int, attestation["artifact_id"]) <= 0
        or attestation.get("artifact_name") != predecessor["artifact_prefix"] + run_id
        or not isinstance(attestation.get("payload_sha256"), str)
        or not isinstance(attestation.get("archive_sha256"), str)
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    try:
        require_hash(cast(str, attestation["payload_sha256"]), field="payload_sha256")
        require_hash(cast(str, attestation["archive_sha256"]), field="archive_sha256")
        predecessor_receipt_sha256 = _validate_predecessor_controller_receipt(
            stage={
                "IDENTITY": "RECOVERY_IDENTITY_V2",
                "IDENTITY_SEAL": "DURABLE_IDENTITY_SEAL_V2",
                "PREFLIGHT": "PRODUCTION_PREFLIGHT_V2",
                "MIGRATION": "MIGRATE_0015",
                "VERIFY": "VERIFY_0015",
            }[predecessor["kind"]],
            main_sha=main_sha,
            run_id=run_id,
            attestation=cast(dict[str, object], attestation),
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID") from None
    except RecoveryV2ControllerError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID") from None
    if not hmac.compare_digest(
        cast(str, proof["predecessor_controller_receipt_sha256"]),
        predecessor_receipt_sha256,
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if stage == "MIGRATE_0015" and prior_run_ids != [int(run_id)]:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if stage == "VERIFY_0015" and (len(prior_run_ids) != 2 or prior_run_ids[1] != int(run_id)):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if stage not in {"MIGRATE_0015", "VERIFY_0015"} and prior_run_ids != []:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")


def _validate_mutation_envelope(
    *,
    stage: str,
    main_sha: str,
    inputs_sha256: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    effect_deadline_epoch: float,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    if stage not in STAGES:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    contract = STAGES[stage]
    workflow = cast(str, contract["workflow"])
    scale_stage = cast(str, contract["scale_stage"])
    base_path = f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/{workflow}"
    operation: str
    if method == "PUT" and path == f"{base_path}/enable" and payload is None:
        operation = "ENABLE"
    elif method == "PUT" and path == f"{base_path}/disable" and payload is None:
        operation = "DISABLE"
    elif method == "POST" and path == f"{base_path}/dispatches":
        operation = "DISPATCH"
        if not isinstance(payload, dict) or set(payload) != {
            "ref",
            "inputs",
            "return_run_details",
        }:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
        if payload.get("ref") != "main" or payload.get("return_run_details") is not True:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
        validated = _validate_inputs(
            stage=stage,
            main_sha=main_sha,
            inputs=payload.get("inputs"),
            require_dispatch_binding=True,
        )
        if not hmac.compare_digest(_inputs_sha256(validated), inputs_sha256):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    else:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if not _same_repository_path(receipt_path, _canonical_controller_receipt(stage)):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if operation == "DISABLE":
        try:
            require_sha(main_sha, field="main_sha")
            require_hash(inputs_sha256, field="inputs_sha256")
            require_hash(pre_effect_proof_sha256, field="pre_effect_proof_sha256")
        except ChronosProductionError:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID") from None
        return
    _payload, receipt = _strict_json_document(receipt_path, maximum_bytes=128 * 1024)
    attempted = receipt.get("mutations_attempted")
    confirmed = receipt.get("mutations_confirmed")
    proof = receipt.get("pre_effect_proof")
    receipt_proof_hash = receipt.get("pre_effect_proof_sha256")
    mutation_state_valid = (
        operation == "ENABLE" and attempted == ["ENABLE"] and confirmed == []
    ) or (
        operation == "DISPATCH" and attempted == ["ENABLE", "DISPATCH"] and confirmed == ["ENABLE"]
    )
    if (
        set(receipt)
        != {
            "schema_version",
            "verdict",
            "stage",
            "main_sha",
            "inputs_sha256",
            "automatic_retries",
            "mutations_attempted",
            "mutations_confirmed",
            "pre_effect_proof",
            "pre_effect_proof_sha256",
        }
        or receipt.get("schema_version") != "data-torrent-recovery-v2-controller-cycle-v1"
        or receipt.get("verdict") != "PRE_EFFECT_GATES_CONFIRMED"
        or receipt.get("stage") != stage
        or receipt.get("main_sha") != main_sha
        or receipt.get("inputs_sha256") != inputs_sha256
        or receipt.get("automatic_retries") != 0
        or not isinstance(proof, dict)
        or not isinstance(receipt_proof_hash, str)
        or not hmac.compare_digest(receipt_proof_hash, pre_effect_proof_sha256)
        or not hmac.compare_digest(_object_sha256(proof), pre_effect_proof_sha256)
        or not isinstance(attempted, list)
        or not isinstance(confirmed, list)
        or not mutation_state_valid
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    _validate_pre_effect_proof(
        stage=stage,
        main_sha=main_sha,
        inputs_sha256=inputs_sha256,
        proof=proof,
    )
    stage_inputs = proof.get("stage_inputs")
    if (
        not isinstance(stage_inputs, dict)
        or stage_inputs.get(_DISPATCH_EFFECT_DEADLINE_INPUT)
        != str(math.floor(effect_deadline_epoch))
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    if operation == "DISPATCH" and cast(dict[str, object], payload).get("inputs") != proof.get(
        "stage_inputs"
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    validate_data_torrent_recovery_v2_authority(scale_stage=scale_stage)


def _mutation_direct(
    *,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    effect_deadline_epoch: float,
    cleanup_after_deadline: bool = False,
) -> dict[str, object] | None:
    if (
        (method, path) not in _AUTHORIZED_MUTATIONS
        or not token
        or len(token.encode("utf-8")) > 2_048
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    retries = Retry(
        total=0,
        connect=0,
        read=0,
        redirect=0,
        status=0,
        other=0,
        raise_on_redirect=True,
        respect_retry_after_header=False,
    )
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", HTTPAdapter(max_retries=retries))
    response: requests.Response | None = None
    try:
        if not cleanup_after_deadline:
            remaining = _require_effect_window(effect_deadline_epoch)
        else:
            remaining = _MUTATION_TOTAL_TIMEOUT_SECONDS
        response = session.request(
            method,
            _API_ROOT + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            json=cast(Any, payload),
            timeout=(min(4.0, remaining), min(6.0, remaining)),
            allow_redirects=False,
            stream=True,
        )
        if path.endswith("/dispatches"):
            if response.status_code != 200:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
            try:
                document = json.loads(
                    _bounded_response_body(response), object_pairs_hook=_unique_object
                )
            except (UnicodeDecodeError, ValueError):
                raise RecoveryV2ControllerError(
                    "RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS"
                ) from None
            if not isinstance(document, dict) or set(document) != {
                "workflow_run_id",
                "run_url",
                "html_url",
            }:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
            run_id = document.get("workflow_run_id")
            if (
                type(run_id) is not int
                or run_id <= 0
                or document.get("run_url")
                != f"https://api.github.com/repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}"
                or document.get("html_url")
                != f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{run_id}"
            ):
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
            return cast(dict[str, object], document)
        if response.status_code != 204:
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
        return None
    except requests.RequestException:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def _mutation_worker(
    connection: Any,
    *,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    stage: str,
    main_sha: str,
    inputs_sha256: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    effect_deadline_epoch: float,
) -> None:
    try:
        cleanup_only = method == "PUT" and path.endswith("/disable")
        if not cleanup_only:
            assert_production_safety_locks(os.environ)
        _validate_mutation_envelope(
            stage=stage,
            main_sha=main_sha,
            inputs_sha256=inputs_sha256,
            pre_effect_proof_sha256=pre_effect_proof_sha256,
            receipt_path=receipt_path,
            effect_deadline_epoch=effect_deadline_epoch,
            method=method,
            path=path,
            payload=payload,
        )
        result = _mutation_direct(
            token=token,
            method=method,
            path=path,
            payload=payload,
            effect_deadline_epoch=effect_deadline_epoch,
            cleanup_after_deadline=cleanup_only,
        )
        connection.send(("CONFIRMED", result))
    except Exception:
        connection.send(("FAILED", None))
    finally:
        connection.close()


def _run_private_mutation_child(
    *,
    target: Callable[..., None],
    kwargs: dict[str, object],
    error_code: str,
    effect_deadline_epoch: float | None = None,
    cleanup_after_deadline: bool = False,
) -> object:
    """Run one mutation child with the shared terminate/kill fail-closed boundary."""

    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=target,
        kwargs={"connection": sender, **kwargs},
    )
    total_timeout = _MUTATION_TOTAL_TIMEOUT_SECONDS
    if effect_deadline_epoch is not None and not cleanup_after_deadline:
        total_timeout = min(
            total_timeout,
            _require_effect_window(effect_deadline_epoch),
        )
    deadline = time.monotonic() + total_timeout
    process.start()
    sender.close()
    process.join(min(_MUTATION_WORK_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic())))
    if process.is_alive():
        process.terminate()
        process.join(
            min(_MUTATION_TERMINATE_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic()))
        )
    if process.is_alive():
        process.kill()
        process.join(max(0.0, deadline - time.monotonic()))
    try:
        message = receiver.recv() if receiver.poll() else ("FAILED", None)
    except (EOFError, OSError):
        message = ("FAILED", None)
    receiver.close()
    exit_code = process.exitcode
    if not process.is_alive():
        process.close()
    if (
        exit_code != 0
        or not isinstance(message, tuple)
        or len(message) != 2
        or message[0] != "CONFIRMED"
    ):
        raise RecoveryV2ControllerError(error_code) from None
    return message[1]


def _mutation_once(
    *,
    token: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    stage: str,
    main_sha: str,
    inputs_sha256: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    effect_deadline_epoch: float,
) -> dict[str, object] | None:
    encoded = json.dumps(
        {
            "method": method,
            "path": path,
            "payload": payload,
            "stage": stage,
            "main_sha": main_sha,
            "inputs_sha256": inputs_sha256,
            "pre_effect_proof_sha256": pre_effect_proof_sha256,
            "receipt_path": str(receipt_path),
            "effect_deadline_epoch": effect_deadline_epoch,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _MAX_INPUT_BYTES or (method, path) not in _AUTHORIZED_MUTATIONS:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_INVALID")
    result = _run_private_mutation_child(
        target=_mutation_worker,
        kwargs={
            "token": token,
            "method": method,
            "path": path,
            "payload": payload,
            "stage": stage,
            "main_sha": main_sha,
            "inputs_sha256": inputs_sha256,
            "pre_effect_proof_sha256": pre_effect_proof_sha256,
            "receipt_path": receipt_path,
            "effect_deadline_epoch": effect_deadline_epoch,
        },
        error_code="RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS",
        effect_deadline_epoch=effect_deadline_epoch,
        cleanup_after_deadline=method == "PUT" and path.endswith("/disable"),
    )
    if result is not None and not isinstance(result, dict):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
    return cast(dict[str, object] | None, result)


def _validate_quarantine_disable_request(
    *,
    main_sha: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    path: str,
) -> None:
    expected_paths = {
        f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/{workflow.rsplit('/', 1)[-1]}/disable"
        for workflow in _QUARANTINE_WORKFLOWS
    }
    try:
        require_sha(main_sha, field="main_sha")
        require_hash(pre_effect_proof_sha256, field="pre_effect_proof_sha256")
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_INVALID") from None
    if (
        path not in expected_paths
        or not _same_repository_path(receipt_path, _canonical_quarantine_receipt())
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_INVALID")


def _quarantine_disable_worker(
    connection: Any,
    *,
    token: str,
    path: str,
    main_sha: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    effect_deadline_epoch: float,
) -> None:
    """Run a bounded cleanup-only mutation; cleanup cannot be blocked by gate drift."""

    try:
        _validate_quarantine_disable_request(
            main_sha=main_sha,
            pre_effect_proof_sha256=pre_effect_proof_sha256,
            receipt_path=receipt_path,
            path=path,
        )
        result = _mutation_direct(
            token=token,
            method="PUT",
            path=path,
            payload=None,
            effect_deadline_epoch=effect_deadline_epoch,
            cleanup_after_deadline=True,
        )
        if result is not None:
            raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")
        connection.send(("CONFIRMED", None))
    except Exception:
        connection.send(("FAILED", None))
    finally:
        connection.close()


def _quarantine_disable_once(
    *,
    token: str,
    path: str,
    main_sha: str,
    pre_effect_proof_sha256: str,
    receipt_path: Path,
    effect_deadline_epoch: float,
) -> None:
    _validate_quarantine_disable_request(
        main_sha=main_sha,
        pre_effect_proof_sha256=pre_effect_proof_sha256,
        receipt_path=receipt_path,
        path=path,
    )
    result = _run_private_mutation_child(
        target=_quarantine_disable_worker,
        kwargs={
            "token": token,
            "path": path,
            "main_sha": main_sha,
            "pre_effect_proof_sha256": pre_effect_proof_sha256,
            "receipt_path": receipt_path,
            "effect_deadline_epoch": effect_deadline_epoch,
        },
        error_code="RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS",
        effect_deadline_epoch=effect_deadline_epoch,
        cleanup_after_deadline=True,
    )
    if result is not None:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")


def run_postmerge_quarantine(
    *,
    main_sha: str,
    receipt_path: Path,
    pre_hold_validator: Callable[[], Mapping[str, object]] | None = None,
    post_hold_validator: Callable[[], Mapping[str, object]] | None = None,
    mutator: Callable[..., None] = _quarantine_disable_once,
) -> dict[str, object]:
    """Disable each newly merged Recovery V2 workflow that GitHub made active."""

    try:
        assert_production_safety_locks(os.environ)
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage="E1"
        )
        validate_data_torrent_recovery_v2_council_release()
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_AUTHORITY_INVALID") from None
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > 2_048:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_TOKEN_MISSING")
    effect_deadline_epoch = _operation_deadline_epoch(
        authority_deadline,
        maximum_runtime_seconds=_LOCAL_E1_STAGE_TIMEOUT_SECONDS,
    )
    expected_sha = require_sha(main_sha, field="main_sha")
    try:
        provider_provenance = _validate_provider_neutralization_receipt(main_sha=expected_sha)
    except RecoveryV2ControllerError:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_AUTHORITY_INVALID") from None
    if not _same_repository_path(receipt_path, _canonical_quarantine_receipt()):
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_RECEIPT_PATH_FORBIDDEN")
    try:
        _recovery_v2_prepare_repository_directory(
            receipt_path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_RECEIPT_PATH_FORBIDDEN") from None
    try:
        _recovery_v2_require_unused_repository_output(
            receipt_path,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        try:
            _recovery_v2_require_repository_file(
                receipt_path,
                repository_root=_REPOSITORY_ROOT,
            )
        except ChronosProductionError:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_QUARANTINE_RECEIPT_PATH_FORBIDDEN"
            ) from None
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        ) from None
    reservation = {
        "schema_version": "data-torrent-recovery-v2-postmerge-quarantine-v1",
        "verdict": "INVOCATION_RESERVED",
        "main_sha": expected_sha,
        "automatic_retries": 0,
        "disable_attempted_paths": [],
        "disable_confirmed_paths": [],
        "disable_outcomes": [],
        "unconfirmed_paths": [],
        "enable_mutations": 0,
        "dispatch_mutations": 0,
        "provider_neutralization_provenance": provider_provenance,
    }
    _write_receipt(receipt_path, reservation, exclusive=True)
    validate_pre_hold = pre_hold_validator or (
        lambda: verify_hold(
            required_successful_ci_sha=expected_sha,
            recovery_v2=True,
            recovery_v2_quarantine_precondition=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )
    try:
        _require_effect_window(effect_deadline_epoch)
        pre_hold = dict(validate_pre_hold())
        post_merge_ci, initial_workflows = _validated_post_merge_hold(
            pre_hold,
            main_sha=expected_sha,
            allow_new_active=True,
        )
        main_reference = _github_get(
            f"/repos/{EXPECTED_REPOSITORY}/git/ref/heads/main",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    except (ChronosProductionError, RecoveryV2ControllerError):
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_PRECONDITION_INVALID") from None
    main_target = main_reference.get("object")
    if (
        main_reference.get("ref") != "refs/heads/main"
        or not isinstance(main_target, dict)
        or main_target.get("type") != "commit"
        or main_target.get("sha") != expected_sha
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_PRECONDITION_INVALID")
    active_paths = [
        cast(str, item["workflow_path"]) for item in initial_workflows if item["state"] == "active"
    ]
    already_disabled = [
        cast(str, item["workflow_path"])
        for item in initial_workflows
        if item["state"] == "disabled_manually"
    ]
    pre_effect_proof = {
        "post_merge_ci": post_merge_ci,
        "scope_guard": pre_hold["recovery_v2_scope_guard"],
        "current_main_sha": expected_sha,
        "global_queue_inventory_validations": 5,
        "initial_workflows": initial_workflows,
        "precondition_hold_sha256": _object_sha256(pre_hold),
    }
    pre_effect_proof_sha256 = _object_sha256(pre_effect_proof)
    gate_receipt = {
        **reservation,
        "verdict": "PRE_EFFECT_GATES_CONFIRMED",
        "pre_effect_proof": pre_effect_proof,
        "pre_effect_proof_sha256": pre_effect_proof_sha256,
        "initial_workflows": initial_workflows,
        "already_disabled_paths": already_disabled,
        "github_api_gets_upper_bound": 25,
        "disable_attempts_maximum": 4,
    }
    _write_receipt(receipt_path, gate_receipt)
    attempted: list[str] = []
    confirmed: list[str] = []
    outcomes: list[dict[str, str]] = []
    primary_error: RecoveryV2ControllerError | None = None

    def record_progress() -> None:
        _write_receipt(
            receipt_path,
            {
                **gate_receipt,
                "disable_attempted_paths": attempted,
                "disable_confirmed_paths": confirmed,
                "disable_outcomes": outcomes,
                "unconfirmed_paths": [path for path in active_paths if path not in confirmed],
            },
        )

    for workflow_path in active_paths:
        attempted.append(workflow_path)
        try:
            record_progress()
        except Exception as error:
            primary_error = (
                error
                if isinstance(error, RecoveryV2ControllerError)
                else RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")
            )
            break
        try:
            mutator(
                token=token,
                path=(
                    f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/"
                    f"{workflow_path.rsplit('/', 1)[-1]}/disable"
                ),
                main_sha=expected_sha,
                pre_effect_proof_sha256=pre_effect_proof_sha256,
                receipt_path=receipt_path,
                effect_deadline_epoch=effect_deadline_epoch,
            )
            confirmed.append(workflow_path)
            outcomes.append({"workflow_path": workflow_path, "outcome": "CONFIRMED"})
            try:
                record_progress()
            except Exception as error:
                primary_error = primary_error or (
                    error
                    if isinstance(error, RecoveryV2ControllerError)
                    else RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")
                )
                break
        except Exception as error:
            primary_error = primary_error or (
                error
                if isinstance(error, RecoveryV2ControllerError)
                else RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")
            )
            outcomes.append({"workflow_path": workflow_path, "outcome": "AMBIGUOUS"})
            try:
                record_progress()
            except Exception as journal_error:
                primary_error = primary_error or (
                    journal_error
                    if isinstance(journal_error, RecoveryV2ControllerError)
                    else RecoveryV2ControllerError(
                        "RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS"
                    )
                )
                break
    validate_post_hold = post_hold_validator or (
        lambda: verify_hold(
            required_successful_ci_sha=expected_sha,
            recovery_v2=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )
    post_hold: dict[str, object] | None = None
    post_hold_error: RecoveryV2ControllerError | None = None
    try:
        _require_effect_window(effect_deadline_epoch)
        post_hold = dict(validate_post_hold())
        _validated_post_merge_hold(post_hold, main_sha=expected_sha, allow_new_active=False)
    except Exception:
        post_hold_error = RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_POST_HOLD_INVALID")
    if primary_error is not None or post_hold_error is not None:
        failure: dict[str, object] = {
            **gate_receipt,
            "verdict": "FAIL_AND_STOP",
            "disable_attempted_paths": attempted,
            "disable_confirmed_paths": confirmed,
            "disable_outcomes": outcomes,
            "unconfirmed_paths": [path for path in active_paths if path not in confirmed],
        }
        if post_hold is not None:
            failure["post_hold"] = post_hold
            failure["post_hold_sha256"] = _object_sha256(post_hold)
        try:
            _write_receipt(receipt_path, failure)
        except RecoveryV2ControllerError:
            pass
        raise primary_error or cast(RecoveryV2ControllerError, post_hold_error)
    if post_hold is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_POST_HOLD_INVALID")
    receipt = {
        **gate_receipt,
        "verdict": "POSTMERGE_QUARANTINE_CONFIRMED",
        "disable_attempted_paths": attempted,
        "disable_confirmed_paths": confirmed,
        "disable_outcomes": outcomes,
        "unconfirmed_paths": [],
        "post_hold": post_hold,
        "post_hold_sha256": _object_sha256(post_hold),
    }
    _write_receipt(receipt_path, receipt)
    return receipt


def run_cycle(
    *,
    stage: str,
    main_sha: str,
    inputs: object,
    receipt_path: Path,
    hold_validator: Callable[[], Mapping[str, object]] | None = None,
    mutator: Callable[..., dict[str, object] | None] = _mutation_once,
    terminalizer: Callable[..., dict[str, object]] | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    """Gate, dispatch once, then require an attested terminal semantic GO."""

    effective_wall_clock = wall_clock or time.time
    try:
        assert_production_safety_locks(os.environ)
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_SAFETY_LOCK_INVALID") from None
    if stage not in STAGES:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_STAGE_INVALID")
    expected_sha = require_sha(main_sha, field="main_sha")
    contract = STAGES[stage]
    try:
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage=cast(str, contract["scale_stage"])
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID") from None
    effect_deadline_epoch, terminalization_deadline_epoch = (
        _stage_operation_deadlines_epoch(
            authority_deadline,
            stage=stage,
        )
    )
    business_inputs = _validate_inputs(
        stage=stage,
        main_sha=expected_sha,
        inputs=inputs,
        require_dispatch_binding=False,
    )
    validated_inputs = _validate_inputs(
        stage=stage,
        main_sha=expected_sha,
        inputs={
            **business_inputs,
            _DISPATCH_EFFECT_DEADLINE_INPUT: str(math.floor(effect_deadline_epoch)),
            _DISPATCH_NONCE_INPUT: hashlib.sha256(os.urandom(32)).hexdigest(),
        },
        require_dispatch_binding=True,
    )
    inputs_sha256 = _inputs_sha256(validated_inputs)
    expected_receipt = _canonical_controller_receipt(stage)
    if not _same_repository_path(receipt_path, expected_receipt):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RECEIPT_PATH_FORBIDDEN")
    try:
        _recovery_v2_prepare_repository_directory(
            receipt_path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RECEIPT_PATH_FORBIDDEN") from None
    try:
        _recovery_v2_require_unused_repository_output(
            receipt_path,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        try:
            _recovery_v2_require_repository_file(
                receipt_path,
                repository_root=_REPOSITORY_ROOT,
            )
        except ChronosProductionError:
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_RECEIPT_PATH_FORBIDDEN"
            ) from None
        raise RecoveryV2ControllerError(
            "RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED"
        ) from None
    reservation = {
        "schema_version": "data-torrent-recovery-v2-controller-cycle-v1",
        "verdict": "INVOCATION_RESERVED",
        "stage": stage,
        "main_sha": expected_sha,
        "inputs_sha256": inputs_sha256,
        "automatic_retries": 0,
        "mutations_attempted": [],
        "mutations_confirmed": [],
    }

    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > 2_048:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_TOKEN_MISSING")
    predecessor = _validate_predecessor(
        stage=stage,
        main_sha=expected_sha,
        inputs=validated_inputs,
    )
    _write_receipt(receipt_path, reservation, exclusive=True)
    validate_hold = hold_validator or (
        lambda: verify_hold(
            required_successful_ci_sha=expected_sha,
            recovery_v2=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )
    attempted: list[str] = []
    confirmed: list[str] = []
    workflow = cast(str, contract["workflow"])
    workflow_path = f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/{workflow}"

    def require_hold() -> dict[str, object]:
        try:
            _require_effect_window(effect_deadline_epoch)
            observed = dict(validate_hold())
            _validated_post_merge_hold(
                observed,
                main_sha=expected_sha,
                allow_new_active=False,
            )
        except (ChronosProductionError, RecoveryV2ControllerError):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID") from None
        return observed

    live_hold = require_hold()
    post_merge_ci = cast(dict[str, object], live_hold["post_merge_ci"])
    ordinal = _validate_dispatch_ordinal(
        stage=stage,
        main_sha=expected_sha,
        inputs=validated_inputs,
        token=token,
        expected_prior_run_ids=cast(list[int], predecessor.get("expected_prior_run_ids", [])),
        effect_deadline_epoch=effect_deadline_epoch,
    )
    final_live_hold = require_hold()
    if final_live_hold != live_hold:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_HOLD_INVALID")
    try:
        main_reference = _github_get(
            f"/repos/{EXPECTED_REPOSITORY}/git/ref/heads/main",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    except ChronosProductionError:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MAIN_REF_INVALID") from None
    main_target = main_reference.get("object")
    if (
        main_reference.get("ref") != "refs/heads/main"
        or not isinstance(main_target, dict)
        or main_target.get("type") != "commit"
        or main_target.get("sha") != expected_sha
    ):
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MAIN_REF_INVALID")
    pre_effect_proof = {
        **predecessor,
        **ordinal,
        "stage_inputs": validated_inputs,
        "post_merge_ci_run_id": post_merge_ci["run_id"],
        "global_hold_full_validations": 2,
        "live_postmerge_holds": [live_hold, final_live_hold],
        "live_postmerge_hold_sha256": _object_sha256(live_hold),
        "current_main_sha": expected_sha,
    }
    pre_effect_proof_sha256 = _object_sha256(pre_effect_proof)
    gate_receipt = {
        **reservation,
        "verdict": "PRE_EFFECT_GATES_CONFIRMED",
        "pre_effect_proof": pre_effect_proof,
        "pre_effect_proof_sha256": pre_effect_proof_sha256,
    }
    _write_receipt(receipt_path, gate_receipt)
    primary_error: RecoveryV2ControllerError | None = None
    enabled_attempted = False
    dispatch_result: dict[str, object] | None = None
    workflow_run_id: int | None = None

    def record_progress() -> None:
        progress: dict[str, object] = {
            **gate_receipt,
            "mutations_attempted": attempted,
            "mutations_confirmed": confirmed,
        }
        if workflow_run_id is not None:
            progress["workflow_run_id"] = workflow_run_id
        _write_receipt(
            receipt_path,
            progress,
        )

    mutation_context = {
        "token": token,
        "stage": stage,
        "main_sha": expected_sha,
        "inputs_sha256": inputs_sha256,
        "pre_effect_proof_sha256": pre_effect_proof_sha256,
        "receipt_path": receipt_path,
        "effect_deadline_epoch": effect_deadline_epoch,
    }
    try:
        attempted.append("ENABLE")
        record_progress()
        enabled_attempted = True
        mutator(
            **mutation_context,
            method="PUT",
            path=f"{workflow_path}/enable",
            payload=None,
        )
        confirmed.append("ENABLE")
        record_progress()
        attempted.append("DISPATCH")
        record_progress()
        dispatch_result = mutator(
            **mutation_context,
            method="POST",
            path=f"{workflow_path}/dispatches",
            payload={
                "ref": "main",
                "inputs": validated_inputs,
                "return_run_details": True,
            },
        )
        if (
            not isinstance(dispatch_result, dict)
            or type(dispatch_result.get("workflow_run_id")) is not int
            or cast(int, dispatch_result["workflow_run_id"]) <= 0
        ):
            raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RUN_ID_INVALID")
        workflow_run_id = cast(int, dispatch_result["workflow_run_id"])
        confirmed.append("DISPATCH")
        record_progress()
    except Exception as error:
        primary_error = (
            error
            if isinstance(error, RecoveryV2ControllerError)
            else RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
        )
    finally:
        if enabled_attempted:
            attempted.append("DISABLE")
            try:
                record_progress()
            except Exception as error:
                normalized = (
                    error
                    if isinstance(error, RecoveryV2ControllerError)
                    else RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
                )
                primary_error = primary_error or normalized
            try:
                mutator(
                    **mutation_context,
                    method="PUT",
                    path=f"{workflow_path}/disable",
                    payload=None,
                )
                confirmed.append("DISABLE")
                try:
                    record_progress()
                except Exception as error:
                    normalized = (
                        error
                        if isinstance(error, RecoveryV2ControllerError)
                        else RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
                    )
                    primary_error = primary_error or normalized
            except Exception as error:
                normalized = (
                    error
                    if isinstance(error, RecoveryV2ControllerError)
                    else RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_MUTATION_AMBIGUOUS")
                )
                primary_error = primary_error or normalized
    if primary_error is not None:
        failure: dict[str, object] = {
            **gate_receipt,
            "verdict": "FAIL_AND_STOP",
            "mutations_attempted": attempted,
            "mutations_confirmed": confirmed,
            "workflow_path": f".github/workflows/{workflow}",
        }
        if workflow_run_id is not None:
            failure["workflow_run_id"] = workflow_run_id
        _write_receipt(
            receipt_path,
            failure,
        )
        raise primary_error
    if workflow_run_id is None:
        raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_RUN_ID_INVALID")
    terminalization_effect_reservation = {
        "reservation_status": "CONSERVATIVE_UPPER_BOUNDS_RESERVED_BEFORE_FIRST_TERMINAL_GET",
        "workflow_run_id": workflow_run_id,
        "workflow_effect_deadline_epoch": effect_deadline_epoch,
        "post_effect_workflow_terminal_grace_seconds": (
            _POST_EFFECT_WORKFLOW_TERMINAL_GRACE_SECONDS[stage]
        ),
        "controller_terminalization_deadline_epoch": terminalization_deadline_epoch,
        "terminal_artifact_attestation_reserve_seconds": int(
            _TERMINAL_ATTESTATION_RESERVE_SECONDS
        ),
        "workflow_run_observations_conservatively_consumed": (
            _TERMINAL_RUN_OBSERVATIONS_MAXIMUM
        ),
        "artifact_attestation_gets_conservatively_consumed": 3,
        "artifact_downloads_conservatively_consumed": 1,
        "automatic_retries": 0,
        "second_terminalization_invocation_allowed": False,
    }
    pending_receipt = {
        **gate_receipt,
        "verdict": "TERMINALIZATION_PENDING",
        "mutations_attempted": attempted,
        "mutations_confirmed": confirmed,
        "workflow_path": f".github/workflows/{workflow}",
        "workflow_run_id": workflow_run_id,
        "terminalization_effect_reservation": terminalization_effect_reservation,
    }
    _write_receipt(receipt_path, pending_receipt)
    terminalize = terminalizer or _terminalize_current_stage
    try:
        terminal = terminalize(
            stage=stage,
            main_sha=expected_sha,
            run_id=workflow_run_id,
            inputs=validated_inputs,
            pre_effect_proof=pre_effect_proof,
            token=token,
            terminalization_deadline_epoch=terminalization_deadline_epoch,
        )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, RecoveryV2ControllerError)
            else "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
        )
        try:
            _write_receipt(
                receipt_path,
                {
                    **pending_receipt,
                    "verdict": "FAIL_AND_STOP",
                    "terminal_failure_code": code,
                    "terminal_evidence": {
                        "outcome": "AMBIGUOUS",
                        "workflow_run_id": workflow_run_id,
                        "main_sha": expected_sha,
                        "failure_code": code,
                        "terminalization_effect_reservation": (
                            terminalization_effect_reservation
                        ),
                    },
                },
            )
        except RecoveryV2ControllerError:
            pass
        raise RecoveryV2ControllerError(code) from None
    if not isinstance(terminal, dict) or terminal.get("outcome") != "SUCCESS":
        failure_code = "RECOVERY_V2_CONTROLLER_TERMINAL_SEMANTIC_FAILURE"
        bounded_terminal: dict[str, object] = {
            "outcome": "AMBIGUOUS",
            "workflow_run_id": workflow_run_id,
            "main_sha": expected_sha,
            "failure_code": failure_code,
        }
        if isinstance(terminal, dict):
            try:
                encoded_terminal = json.dumps(
                    terminal,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                if len(encoded_terminal) <= 2 * 1024 * 1024:
                    bounded_terminal = terminal
            except (TypeError, ValueError):
                pass
        _write_receipt(
            receipt_path,
            {
                **pending_receipt,
                "verdict": "FAIL_AND_STOP",
                "terminal_failure_code": failure_code,
                "terminal_evidence": bounded_terminal,
            },
        )
        raise RecoveryV2ControllerError(failure_code)
    try:
        terminal = _validate_terminal_success_evidence(
            stage=stage,
            main_sha=expected_sha,
            run_id=str(workflow_run_id),
            terminal=terminal,
        )
        terminal_run = cast(dict[str, object], terminal["terminal_run"])
        terminal_updated_at = datetime.fromisoformat(
            cast(str, terminal_run["updated_at"]).replace("Z", "+00:00")
        )
        if not (
            datetime.fromisoformat(
                DATA_TORRENT_RECOVERY_V2_NOT_BEFORE.replace("Z", "+00:00")
            )
            <= terminal_updated_at
            <= datetime.fromtimestamp(terminalization_deadline_epoch, tz=UTC)
        ):
            raise RecoveryV2ControllerError(
                "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
            )
        terminalization_completed_at = _terminalization_completed_at(
            deadline_epoch=terminalization_deadline_epoch,
            clock=effective_wall_clock,
        )
    except Exception as error:
        failure_code = (
            str(error)
            if isinstance(error, RecoveryV2ControllerError)
            else "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
        )
        _write_receipt(
            receipt_path,
            {
                **pending_receipt,
                "verdict": "FAIL_AND_STOP",
                "terminal_failure_code": failure_code,
                "terminal_evidence": {
                    "outcome": "AMBIGUOUS",
                    "workflow_run_id": workflow_run_id,
                    "main_sha": expected_sha,
                    "failure_code": failure_code,
                    "terminalization_effect_reservation": (
                        terminalization_effect_reservation
                    ),
                },
            },
        )
        raise RecoveryV2ControllerError(failure_code) from None
    receipt = {
        **pending_receipt,
        "verdict": "TERMINAL_SUCCESS_CONFIRMED",
        "terminalization_completed_at": terminalization_completed_at,
        "terminal_evidence": terminal,
    }
    _write_receipt(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=tuple(STAGES))
    parser.add_argument("--postmerge-quarantine", action="store_true")
    parser.add_argument("--neutralize-provider-branch", action="store_true")
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--inputs-json", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.neutralize_provider_branch:
            if args.postmerge_quarantine or args.stage is not None or args.inputs_json is not None:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ARGUMENTS_INVALID")
            result = run_legacy_provider_branch_neutralization(
                main_sha=args.main_sha,
                receipt_path=args.receipt,
            )
        elif args.postmerge_quarantine:
            if args.stage is not None or args.inputs_json is not None:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ARGUMENTS_INVALID")
            result = run_postmerge_quarantine(
                main_sha=args.main_sha,
                receipt_path=args.receipt,
            )
        else:
            if args.stage is None or args.inputs_json is None:
                raise RecoveryV2ControllerError("RECOVERY_V2_CONTROLLER_ARGUMENTS_INVALID")
            payload = args.inputs_json.read_bytes()
            if not payload or len(payload) > _MAX_INPUT_BYTES or args.inputs_json.is_symlink():
                raise ValueError
            inputs = json.loads(payload, object_pairs_hook=_unique_object)
            result = run_cycle(
                stage=args.stage,
                main_sha=args.main_sha,
                inputs=inputs,
                receipt_path=args.receipt,
            )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, RecoveryV2ControllerError)
            else "RECOVERY_V2_CONTROLLER_UNCLASSIFIED_FAILURE"
        )
        print(code)
        return 1
    print(result["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
