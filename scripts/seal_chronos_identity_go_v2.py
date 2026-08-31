"""Seal one exact Recovery V2 identity GO in immutable R2 storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    assert_production_safety_locks,
    require_sha,
    validate_data_torrent_recovery_v2_authority,
    validate_neon_branch_identity_go_v2,
)
from robin.prospective_observatory.chronos_control_plane import ConditionalPutOutcome
from robin.prospective_observatory.chronos_r2 import ChronosR2ConditionalStore
from scripts import chronos_neon_pure_readonly_preflight_v4 as readonly
from scripts.chronos_live_path_artifact_guard_v2 import load_guarded_seal
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

REPORT_SCHEMA = "durable-identity-seal-v2"
WORKFLOW_FILE = "chronos-identity-seal-v2.yml"
IDENTITY_WORKFLOW_PATH = ".github/workflows/chronos-neon-branch-identity-v2.yml"
OBJECT_PREFIX = "data-torrent-recovery-v2/control-plane/identity-go"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class IdentitySealError(RuntimeError):
    """Sanitized terminal V2 seal error."""


def _v2_authority() -> None:
    validate_data_torrent_recovery_v2_authority(scale_stage="E2")


@dataclass(slots=True)
class SealEffectsV2:
    r2_puts: int = 0
    r2_gets: int = 0
    r2_objects_created: int = 0
    r2_objects_created_exact: bool = True


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise IdentitySealError(f"IDENTITY_SEAL_CONTEXT_MISSING:{name}")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = path.read_bytes()
    except OSError:
        raise IdentitySealError("IDENTITY_SEAL_INPUT_MISSING") from None
    if not payload or len(payload) > 65_536 or path.is_symlink() or b"\x00" in payload:
        raise IdentitySealError("IDENTITY_SEAL_INPUT_INVALID")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise IdentitySealError("IDENTITY_SEAL_INPUT_INVALID") from None
    if not isinstance(document, dict):
        raise IdentitySealError("IDENTITY_SEAL_INPUT_INVALID")
    return payload, document


def _object_key(*, main_sha: str, identity_run_id: str, payload_sha256: str) -> str:
    return (
        f"{OBJECT_PREFIX}/main_sha={main_sha}/run_id={identity_run_id}/report-{payload_sha256}.json"
    )


def seal_identity_go(
    identity_report_path: Path,
    attestation_path: Path,
    *,
    expected_main_sha: str,
    identity_run_id: str,
    store: ChronosR2ConditionalStore | None = None,
    effects: SealEffectsV2 | None = None,
) -> dict[str, object]:
    """Validate, create once, and exact-key read back the identity bytes."""

    try:
        assert_production_safety_locks(os.environ)
        _v2_authority()
    except ChronosProductionError:
        raise IdentitySealError("IDENTITY_SEAL_SAFETY_OR_AUTHORITY_INACTIVE") from None
    repository = _required("GITHUB_REPOSITORY")
    git_ref = _required("GITHUB_REF")
    github_sha = require_sha(_required("GITHUB_SHA"), field="github_sha")
    expected_sha = require_sha(expected_main_sha, field="expected_main_sha")
    seal_run_id = _required("GITHUB_RUN_ID")
    if (
        repository != EXPECTED_REPOSITORY
        or git_ref != EXPECTED_REF
        or github_sha != expected_sha
        or _required("GITHUB_RUN_ATTEMPT") != "1"
        or not identity_run_id.isascii()
        or not identity_run_id.isdigit()
        or identity_run_id == "0"
        or len(identity_run_id) > 18
        or not seal_run_id.isascii()
        or not seal_run_id.isdigit()
        or seal_run_id == "0"
        or len(seal_run_id) > 18
    ):
        raise IdentitySealError("IDENTITY_SEAL_SOURCE_INVALID")
    authority_dispatches = readonly._github_authority_window_dispatch_count(
        repository,
        int(seal_run_id),
        github_sha,
        workflow_file=WORKFLOW_FILE,
        not_before=DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        authority_validator=_v2_authority,
    )
    queued, in_progress, dispatches = readonly._github_actions_state(
        repository,
        int(seal_run_id),
        github_sha,
        workflow_file=WORKFLOW_FILE,
        authority_validator=_v2_authority,
    )
    if queued != 0 or in_progress != 0 or dispatches != 1 or authority_dispatches != 1:
        raise IdentitySealError("IDENTITY_SEAL_DISPATCH_INVALID")

    report_bytes, identity_document = _read_json(identity_report_path)
    try:
        validated_identity = validate_neon_branch_identity_go_v2(
            identity_document,
            main_sha=github_sha,
        )
    except Exception:
        raise IdentitySealError("IDENTITY_REPORT_INVALID") from None
    identity_source = validated_identity.get("source")
    if not isinstance(identity_source, dict) or identity_source.get("run_id") != identity_run_id:
        raise IdentitySealError("IDENTITY_REPORT_RUN_MISMATCH")
    _, attestation = _read_json(attestation_path)
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
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    artifact_id = attestation.get("artifact_id")
    archive_sha256 = attestation.get("archive_sha256")
    if (
        set(attestation) != attestation_fields
        or attestation.get("schema_version") != "github-artifact-attestation-v2"
        or attestation.get("repository") != repository
        or attestation.get("workflow_path") != IDENTITY_WORKFLOW_PATH
        or attestation.get("run_id") != identity_run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != github_sha
        or type(artifact_id) is not int
        or artifact_id < 1
        or attestation.get("artifact_name") != f"neon-branch-identity-go-v2-{identity_run_id}"
        or attestation.get("payload_sha256") != report_sha256
        or not isinstance(archive_sha256, str)
        or _HEX_64.fullmatch(archive_sha256) is None
    ):
        raise IdentitySealError("IDENTITY_ATTESTATION_INVALID")
    account = _required("R2_ACCOUNT_ID")
    bucket = _required("R2_BUCKET_NAME")
    store_identity_sha256 = hashlib.sha256(f"{account}\x00{bucket}".encode()).hexdigest()
    key = _object_key(
        main_sha=github_sha,
        identity_run_id=identity_run_id,
        payload_sha256=report_sha256,
    )
    metadata = {
        "schema": "neon-branch-identity-go-v2",
        "sha256": report_sha256,
        "main_sha": github_sha,
        "identity_run_id": identity_run_id,
        "artifact_id": str(artifact_id),
        "archive_sha256": archive_sha256,
        "store_identity_sha256": store_identity_sha256,
    }
    counters = effects if effects is not None else SealEffectsV2()
    durable_store = store or ChronosR2ConditionalStore.from_environment(os.environ)

    def before_put() -> None:
        _v2_authority()
        if counters.r2_puts != 0:
            raise IdentitySealError("IDENTITY_SEAL_SECOND_PUT_FORBIDDEN")
        counters.r2_puts = 1
        counters.r2_objects_created = 1
        counters.r2_objects_created_exact = False

    try:
        outcome = durable_store.put_if_absent(
            key,
            report_bytes,
            metadata=metadata,
            on_dispatch=before_put,
        )
    except Exception:
        raise IdentitySealError("IDENTITY_SEAL_PUT_AMBIGUOUS") from None
    if (
        outcome.outcome is ConditionalPutOutcome.AMBIGUOUS
        or outcome.transport_attempts != 1
        or outcome.automatic_retry_possible
    ):
        counters.r2_puts = max(counters.r2_puts, outcome.transport_attempts)
        counters.r2_objects_created = 1
        counters.r2_objects_created_exact = False
        raise IdentitySealError("IDENTITY_SEAL_PUT_AMBIGUOUS")
    if outcome.outcome is not ConditionalPutOutcome.CREATED:
        counters.r2_objects_created = 0
        counters.r2_objects_created_exact = True
        raise IdentitySealError("IDENTITY_SEAL_PUT_NOT_CREATED")
    counters.r2_objects_created_exact = True
    _v2_authority()
    if counters.r2_gets != 0:
        raise IdentitySealError("IDENTITY_SEAL_SECOND_GET_FORBIDDEN")
    counters.r2_gets = 1
    try:
        observed = durable_store.get_object(key)
    except Exception:
        raise IdentitySealError("IDENTITY_SEAL_GET_AMBIGUOUS") from None
    if (
        observed is None
        or observed.data != report_bytes
        or observed.metadata != metadata
        or hashlib.sha256(observed.data).hexdigest() != report_sha256
    ):
        raise IdentitySealError("IDENTITY_SEAL_READBACK_MISMATCH")
    return {
        "schema_version": REPORT_SCHEMA,
        "verdict": "DURABLE_IDENTITY_SEAL_V2",
        "sealed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": repository,
            "ref": git_ref,
            "main_sha": github_sha,
            "run_id": seal_run_id,
            "run_attempt": "1",
        },
        "identity_go": {
            **attestation,
            "durable_store": "R2_IMMUTABLE",
            "conditional_put_outcome": "CREATED",
            "durable_object_key": key,
            "durable_metadata": metadata,
            "durable_readback_sha256": report_sha256,
            "store_identity_sha256": store_identity_sha256,
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


def _write(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _supervisor_fallback() -> dict[str, object]:
    return {
        "schema_version": "durable-identity-seal-supervisor-failure-v2",
        "verdict": "DURABLE_IDENTITY_SEAL_FAILED_V2",
        "failure_class": "TRANSPORT_AMBIGUOUS",
        "effect_counter_certainty": "UNKNOWN_OR_UPPER_BOUND",
        "effects": {
            "r2_puts": 1,
            "r2_gets": 1,
            "r2_objects_created": 1,
            "r2_objects_created_exact": False,
            "automatic_retries": 0,
        },
        "secret_values_observed": False,  # nosec B105 - boolean audit field.
    }


def _supervise(
    *,
    identity_report: Path,
    attestation: Path,
    expected_main_sha: str,
    identity_run_id: str,
    report: Path,
) -> int:
    fallback_sha256 = adopt_or_create_json_fallback(report, _supervisor_fallback())
    with tempfile.TemporaryDirectory(prefix=".seal-v2-candidate-", dir=report.parent) as raw:
        candidate = Path(raw) / report.name
        timeout_seconds = remaining_effect_timeout(480)
        if timeout_seconds == 0:
            return SUPERVISOR_TIMEOUT_EXIT
        return_code = run_child_once(
            (
                sys.executable,
                "-m",
                "scripts.seal_chronos_identity_go_v2",
                "--identity-report",
                str(identity_report),
                "--attestation",
                str(attestation),
                "--expected-main-sha",
                expected_main_sha,
                "--identity-run-id",
                identity_run_id,
                "--report",
                str(candidate),
            ),
            timeout_seconds=timeout_seconds,
        )
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
                candidate_report = load_guarded_seal(
                    path,
                    expected_main_sha=expected_main_sha,
                    expected_identity_run_id=identity_run_id,
                )
                success = candidate_report.get("verdict") == "DURABLE_IDENTITY_SEAL_V2"
                if success is not (return_code == 0):
                    raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_REPORT_INVALID")
                return candidate_report

            validated = promote_validated_file(
                candidate,
                report,
                expected_fallback_sha256=fallback_sha256,
                validator=validate_candidate,
            )
        except (ChronosProductionError, RecoveryV2SupervisionError):
            return SUPERVISOR_EXPORT_EXIT
        if validated.get("verdict") != (
            "DURABLE_IDENTITY_SEAL_V2"
            if return_code == 0
            else "DURABLE_IDENTITY_SEAL_FAILED_V2"
        ):
            return SUPERVISOR_EXPORT_EXIT
        return return_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-report", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--identity-run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    if getattr(args, "supervise", False):
        return _supervise(
            identity_report=args.identity_report,
            attestation=args.attestation,
            expected_main_sha=args.expected_main_sha,
            identity_run_id=args.identity_run_id,
            report=args.report,
        )
    effects = SealEffectsV2()
    try:
        report = seal_identity_go(
            args.identity_report,
            args.attestation,
            expected_main_sha=args.expected_main_sha,
            identity_run_id=args.identity_run_id,
            effects=effects,
        )
    except Exception:
        report = {
            "schema_version": "durable-identity-seal-failure-v2",
            "verdict": "DURABLE_IDENTITY_SEAL_FAILED_V2",
            "error_code": "IDENTITY_SEAL_EXECUTION_FAILED",
            "failure_class": "EXECUTION_FAILED",
            "effect_counter_certainty": "EXACT_DISPATCH_ACCOUNTING",
            "effects": {
                "r2_puts": effects.r2_puts,
                "r2_gets": effects.r2_gets,
                "r2_objects_created": effects.r2_objects_created,
                "r2_objects_created_exact": effects.r2_objects_created_exact,
                "automatic_retries": 0,
            },
            "secret_values_observed": False,  # nosec B105 - boolean audit field.
        }
        _write(args.report, report)
        return 2
    _write(args.report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
