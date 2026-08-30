"""Durably seal one exact controlled read-only GO in immutable R2 storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from robin.chronos_production import (
    DATA_TORRENT_ONE_SHOT_NOT_BEFORE,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    require_sha,
    validate_data_torrent_authority,
)
from robin.prospective_observatory.chronos_control_plane import (
    ConditionalPutOutcome,
)
from robin.prospective_observatory.chronos_r2 import (
    ChronosR2ConditionalStore,
)
from scripts import chronos_neon_pure_readonly_preflight_v4 as readonly
from scripts.chronos_production_bootstrap_v3 import _controlled_readonly_go

REPORT_SCHEMA = "chronos-controlled-go-durable-seal-v1"
WORKFLOW_FILE = "chronos-controlled-go-durable-seal-v1.yml"
CONTROLLED_WORKFLOW_PATH = ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"
OBJECT_PREFIX = "data-torrent-ready-v1/control-plane/controlled-go"


class ControlledGoSealError(RuntimeError):
    """Sanitized terminal seal error."""


@dataclass(slots=True)
class SealEffects:
    r2_puts: int = 0
    r2_gets: int = 0
    r2_objects_created: int = 0
    r2_objects_created_exact: bool = True


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ControlledGoSealError(f"CONTROLLED_GO_SEAL_CONTEXT_MISSING:{name}")
    return value


def _object_key(*, main_sha: str, controlled_run_id: str, report_sha256: str) -> str:
    return (
        f"{OBJECT_PREFIX}/main_sha={main_sha}/run_id={controlled_run_id}/"
        f"report-{report_sha256}.json"
    )


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def seal_controlled_go(
    controlled_report_path: Path,
    *,
    expected_main_sha: str,
    controlled_run_id: str,
    store: ChronosR2ConditionalStore | None = None,
    effects: SealEffects | None = None,
) -> dict[str, object]:
    """Validate, conditionally create, and read back one immutable GO object."""

    try:
        validate_data_torrent_authority()
    except ChronosProductionError:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_AUTHORITY_INACTIVE") from None
    repository = _required("GITHUB_REPOSITORY")
    git_ref = _required("GITHUB_REF")
    github_sha = require_sha(_required("GITHUB_SHA"), field="github_sha")
    run_attempt = _required("GITHUB_RUN_ATTEMPT")
    seal_run_id = _required("GITHUB_RUN_ID")
    expected_sha = require_sha(expected_main_sha, field="expected_main_sha")
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_SOURCE_MISMATCH")
    if github_sha != expected_sha:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_MAIN_SHA_MISMATCH")
    for value in (controlled_run_id, seal_run_id):
        if not value.isascii() or not value.isdigit() or value == "0":
            raise ControlledGoSealError("CONTROLLED_GO_SEAL_RUN_ID_INVALID")
    if run_attempt != "1":
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_RERUN_FORBIDDEN")

    queue_count, in_progress_count, dispatch_count = readonly._github_actions_state(
        repository,
        int(seal_run_id),
        github_sha,
        workflow_file=WORKFLOW_FILE,
    )
    if dispatch_count != 1:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_DISPATCH_NOT_UNIQUE")
    if queue_count != 0 or in_progress_count != 0:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_ACTIONS_NOT_QUIESCENT")
    try:
        authority_window_dispatch_count = readonly._github_authority_window_dispatch_count(
            repository,
            int(seal_run_id),
            github_sha,
            workflow_file=WORKFLOW_FILE,
            not_before=DATA_TORRENT_ONE_SHOT_NOT_BEFORE,
        )
    except Exception:
        raise ControlledGoSealError(
            "CONTROLLED_GO_SEAL_AUTHORITY_DISPATCH_HISTORY_INVALID"
        ) from None
    if authority_window_dispatch_count != 1:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_AUTHORITY_DISPATCH_NOT_UNIQUE")

    controlled = _controlled_readonly_go(
        controlled_report_path,
        expected_main_sha=github_sha,
        expected_run_id=controlled_run_id,
    )
    report_bytes = controlled_report_path.read_bytes()
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    if controlled["artifact_sha256"] != report_sha256:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_REPORT_HASH_MISMATCH")
    key = _object_key(
        main_sha=github_sha,
        controlled_run_id=controlled_run_id,
        report_sha256=report_sha256,
    )
    metadata = {
        "schema": "chronos-controlled-go-v1",
        "sha256": report_sha256,
        "main_sha": github_sha,
        "controlled_run_id": controlled_run_id,
    }
    effect_counts = effects if effects is not None else SealEffects()
    durable_store = store or ChronosR2ConditionalStore.from_environment(os.environ)

    def before_put() -> None:
        try:
            validate_data_torrent_authority()
        except ChronosProductionError:
            raise ControlledGoSealError("CONTROLLED_GO_SEAL_AUTHORITY_INACTIVE") from None
        if effect_counts.r2_puts != 0:
            raise ControlledGoSealError("CONTROLLED_GO_SEAL_SECOND_PUT_FORBIDDEN")
        effect_counts.r2_puts = 1
        # Once bytes may have left the process, an exception or AMBIGUOUS
        # response cannot prove that the conditional create did not commit.
        effect_counts.r2_objects_created = 1
        effect_counts.r2_objects_created_exact = False

    outcome = durable_store.put_if_absent(
        key,
        report_bytes,
        metadata=metadata,
        on_dispatch=before_put,
    )
    if outcome.outcome in {
        ConditionalPutOutcome.PRECONDITION_FAILED,
        ConditionalPutOutcome.DEFINITE_FAILURE,
        ConditionalPutOutcome.CONFLICT,
    }:
        effect_counts.r2_objects_created = 0
        effect_counts.r2_objects_created_exact = True
    if (
        outcome.outcome is not ConditionalPutOutcome.CREATED
        or outcome.transport_attempts != 1
        or outcome.automatic_retry_possible
    ):
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_PUT_NOT_CREATED")
    effect_counts.r2_objects_created = 1
    effect_counts.r2_objects_created_exact = True
    try:
        validate_data_torrent_authority()
    except ChronosProductionError:
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_AUTHORITY_INACTIVE") from None
    effect_counts.r2_gets = 1
    observed = durable_store.get_object(key)
    if (
        observed is None
        or observed.data != report_bytes
        or observed.metadata != metadata
        or hashlib.sha256(observed.data).hexdigest() != report_sha256
    ):
        raise ControlledGoSealError("CONTROLLED_GO_SEAL_READBACK_MISMATCH")

    return {
        "schema_version": REPORT_SCHEMA,
        "verdict": "CHRONOS_CONTROLLED_GO_DURABLY_SEALED",
        "sealed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": repository,
            "ref": git_ref,
            "main_sha": github_sha,
            "run_id": seal_run_id,
            "run_attempt": "1",
        },
        "controlled_go": {
            "schema_version": "chronos-controlled-go-binding-v1",
            "workflow_path": CONTROLLED_WORKFLOW_PATH,
            "run_id": controlled_run_id,
            "run_attempt": "1",
            "main_sha": github_sha,
            "report_schema": controlled["schema_version"],
            "report_sha256": report_sha256,
            "durable_store": "R2_IMMUTABLE",
            "conditional_put_outcome": "CREATED",
            "durable_object_key": key,
            "durable_readback_sha256": report_sha256,
        },
        "github_actions": {
            "queued": 0,
            "in_progress": 0,
            "exact_main_dispatch_count": 1,
            "authority_window_dispatch_count": authority_window_dispatch_count,
        },
        "effects": {
            "r2_puts": effect_counts.r2_puts,
            "r2_gets": effect_counts.r2_gets,
            "r2_objects_created": effect_counts.r2_objects_created,
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


def _failure(error: Exception, effects: SealEffects) -> dict[str, object]:
    code = str(error) if isinstance(error, ControlledGoSealError) else "CONTROLLED_GO_SEAL_FAILED"
    return {
        "schema_version": "chronos-controlled-go-durable-seal-failure-v1",
        "status": "FAILED",
        "error_code": code,
        "effect_counter_certainty": "CONSERVATIVE_DISPATCH_ACCOUNTING",
        "effects": {
            "r2_puts": effects.r2_puts,
            "r2_gets": effects.r2_gets,
            "r2_objects_created": effects.r2_objects_created,
            "r2_objects_created_exact": effects.r2_objects_created_exact,
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
        "automatic_retries": 0,
        "secret_values_observed": False,  # nosec B105
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controlled-report", type=Path, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--controlled-run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    effects = SealEffects()
    try:
        report = seal_controlled_go(
            args.controlled_report,
            expected_main_sha=args.expected_main_sha,
            controlled_run_id=args.controlled_run_id,
            effects=effects,
        )
    except Exception as error:
        failure = _failure(error, effects)
        _write_report(args.report, failure)
        print(str(failure["error_code"]))
        raise SystemExit(1) from None
    _write_report(args.report, report)
    print(str(report["verdict"]))


if __name__ == "__main__":
    main()
