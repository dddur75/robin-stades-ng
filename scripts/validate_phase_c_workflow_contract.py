"""Validate trusted-main Phase-C activation, locks, workflows and artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = ROOT / "configs/execution/phase-c-execution-activation-v1.json"
PHASE_LOCK = ROOT / "configs/execution/phase-c-artifact-lock-v1.json"
SOURCE_LOCK = ROOT / "configs/execution/p0-e3-artifact-lock-v1.json"
SOURCE_NAMES = {
    8875626108: "historical-deep-74d-current-r2-gate-batch-0105-30853757779-1",
    8875918562: "historical-deep-74d-current-r2-gate-batch-0142-30853757779-1",
    8876203323: "historical-deep-74d-current-r2-gate-batch-0179-30853757779-1",
    8875016575: "historical-deep-74d-current-r2-gate-batch-0031-30853757779-1",
    8875329908: "historical-deep-74d-current-r2-gate-batch-0068-30853757779-1",
}


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_text_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def api(path: str) -> dict[str, Any]:
    repository = os.environ["GH_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise TypeError("GITHUB_API_OBJECT_REQUIRED")
    return value


def append_outputs(values: dict[str, object]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def validate_authority() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    activation = read_object(ACTIVATION)
    lock = read_object(PHASE_LOCK)
    source = read_object(SOURCE_LOCK)
    execution_sha = os.environ["EXECUTION_SHA"]
    branch = os.environ["PHASE_C_BRANCH"]
    if (
        len(execution_sha) != 40
        or any(character not in "0123456789abcdef" for character in execution_sha)
        or activation.get("activation_status") != "ACTIVE"
        or activation.get("allowed_execution_sha") != execution_sha
        or activation.get("branch") != branch
    ):
        raise RuntimeError("PHASE_C_TRUSTED_MAIN_ACTIVATION_HOLD")
    activation_payload = {
        key: value for key, value in activation.items() if key != "contract_hash"
    }
    lock_payload = {key: value for key, value in lock.items() if key != "lock_hash"}
    if canonical_hash(activation_payload) != activation.get("contract_hash"):
        raise RuntimeError("PHASE_C_ACTIVATION_CANONICAL_HASH_MISMATCH")
    if canonical_hash(lock_payload) != lock.get("lock_hash"):
        raise RuntimeError("PHASE_C_ARTIFACT_LOCK_CANONICAL_HASH_MISMATCH")
    if activation.get("phase_c_artifact_lock_hash") != lock.get("lock_hash"):
        raise RuntimeError("PHASE_C_ARTIFACT_LOCK_AUTHORITY_MISMATCH")
    if repository_text_hash(SOURCE_LOCK) != activation.get("source_lock_sha256"):
        raise RuntimeError("PHASE_C_SOURCE_LOCK_HASH_MISMATCH")
    if file_hash(Path(__file__)) != activation.get("preflight_sha256"):
        raise RuntimeError("PHASE_C_PREFLIGHT_HASH_MISMATCH")
    if file_hash(ROOT / "scripts/run_hypothesis_tag_mask_pair_factory.py") != activation.get(
        "generator_sha256"
    ):
        raise RuntimeError("PHASE_C_GENERATOR_HASH_MISMATCH")
    workflows = activation.get("workflow_sha256")
    if not isinstance(workflows, dict) or set(workflows) != {
        "86-p0-phase-c-raw-field-census.yml",
        "87-p0-phase-c-tag-mask-build.yml",
        "88-p0-phase-c-atomic-property-search.yml",
        "89-p0-phase-c-compatible-pair-search.yml",
    }:
        raise RuntimeError("PHASE_C_WORKFLOW_HASH_SET_MISMATCH")
    for filename, expected in workflows.items():
        if file_hash(ROOT / ".github/workflows" / filename) != expected:
            raise RuntimeError(f"PHASE_C_WORKFLOW_HASH_MISMATCH:{filename}")
    return activation, lock, source


def validate_source(activation: dict[str, Any], source: dict[str, Any]) -> None:
    run = api(
        f"actions/runs/{source['source_run_id']}/attempts/{source['source_run_attempt']}"
    )
    if (
        run.get("run_attempt") != source["source_run_attempt"]
        or run.get("head_sha") != source["source_head_sha"]
    ):
        raise RuntimeError("SOURCE_WORKFLOW_RUN_MISMATCH")
    artifacts = source.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 5:
        raise RuntimeError("SOURCE_ARTIFACT_CARDINALITY_MISMATCH")
    total = 0
    ids: list[str] = []
    for expected in artifacts:
        if not isinstance(expected, dict):
            raise TypeError("SOURCE_ARTIFACT_LOCK_OBJECT_REQUIRED")
        artifact_id = int(expected["artifact_id"])
        actual = api(f"actions/artifacts/{artifact_id}")
        if (
            actual.get("expired")
            or actual.get("name") != SOURCE_NAMES[artifact_id]
            or actual.get("size_in_bytes") != expected["size_in_bytes"]
            or actual.get("digest") != expected["artifact_digest"]
            or actual.get("workflow_run", {}).get("id") != source["source_run_id"]
            or actual.get("workflow_run", {}).get("head_sha") != source["source_head_sha"]
        ):
            raise RuntimeError(f"SOURCE_ARTIFACT_METADATA_MISMATCH:{artifact_id}")
        total += int(actual["size_in_bytes"])
        ids.append(str(artifact_id))
    limit = int(activation["artifact_budgets_bytes"]["source_workflow_download_max"])
    if total != source["mission_source_bytes"] or total > limit:
        raise RuntimeError("SOURCE_ARTIFACT_BYTE_BUDGET_MISMATCH")
    append_outputs(
        {
            "generator_sha": activation["generator_sha256"],
            "source_run_id": source["source_run_id"],
            "artifact_ids": ",".join(ids),
        }
    )


def validate_stage(
    activation: dict[str, Any], lock: dict[str, Any], stage_names: list[str]
) -> None:
    stage_locks = lock.get("stage_locks")
    if not isinstance(stage_locks, dict):
        raise RuntimeError("PHASE_C_STAGE_LOCKS_OBJECT_REQUIRED")
    outputs: dict[str, object] = {"generator_sha": activation["generator_sha256"]}
    total = 0
    for stage_name in stage_names:
        stage = stage_locks.get(stage_name)
        if not isinstance(stage, dict):
            raise RuntimeError(f"UPSTREAM_STAGE_LOCK_MISSING:{stage_name}")
        run = api(f"actions/runs/{stage['run_id']}/attempts/{stage['run_attempt']}")
        if (
            run.get("id") != stage["run_id"]
            or run.get("run_attempt") != stage["run_attempt"]
            or run.get("head_sha") != stage["head_sha"]
            or run.get("head_sha") != os.environ["EXECUTION_SHA"]
            or run.get("workflow_id") != stage["workflow_id"]
            or run.get("path") != stage["workflow_path"]
            or run.get("event") != "workflow_dispatch"
            or run.get("conclusion") != "success"
        ):
            raise RuntimeError(f"UPSTREAM_STAGE_RUN_MISMATCH:{stage_name}")
        actual = api(f"actions/artifacts/{stage['artifact_id']}")
        if (
            actual.get("expired")
            or actual.get("name") != stage["artifact_name"]
            or actual.get("size_in_bytes") != stage["size_in_bytes"]
            or actual.get("digest") != stage["digest"]
            or actual.get("workflow_run", {}).get("id") != stage["run_id"]
            or actual.get("workflow_run", {}).get("head_sha") != stage["head_sha"]
        ):
            raise RuntimeError(f"UPSTREAM_STAGE_ARTIFACT_MISMATCH:{stage_name}")
        total += int(stage["size_in_bytes"])
        prefix = stage_name.lower()
        outputs[f"{prefix}_run_id"] = stage["run_id"]
        outputs[f"{prefix}_artifact_id"] = stage["artifact_id"]
        outputs[f"{prefix}_manifest_hash"] = stage["stage_manifest_hash"]
    limit = int(activation["artifact_budgets_bytes"]["derived_stage_download_max"])
    if total > limit:
        raise RuntimeError("DERIVED_STAGE_DOWNLOAD_BYTE_BUDGET_EXCEEDED")
    append_outputs(outputs)


def validate_resume(workflow_path: str | None) -> None:
    raw_run_id = os.environ.get("RESUME_RUN_ID", "")
    raw_attempt = os.environ.get("RESUME_ATTEMPT", "")
    if not raw_run_id and not raw_attempt:
        return
    if not raw_run_id.isdigit() or not raw_attempt.isdigit() or not workflow_path:
        raise RuntimeError("RESUME_INPUT_CONTRACT_MISMATCH")
    run = api(f"actions/runs/{int(raw_run_id)}/attempts/{int(raw_attempt)}")
    if (
        run.get("id") != int(raw_run_id)
        or run.get("run_attempt") != int(raw_attempt)
        or run.get("head_sha") != os.environ["EXECUTION_SHA"]
        or run.get("path") != workflow_path
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
    ):
        raise RuntimeError("RESUME_RUN_LINEAGE_MISMATCH")
    append_outputs({"resume_run_id": raw_run_id, "resume_attempt": raw_attempt})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("source", "stage"))
    parser.add_argument("--stage", action="append", default=[])
    parser.add_argument("--resume-workflow-path")
    args = parser.parse_args()
    activation, lock, source = validate_authority()
    if args.mode == "source":
        validate_source(activation, source)
    else:
        if not args.stage:
            raise RuntimeError("UPSTREAM_STAGE_REQUIRED")
        validate_stage(activation, lock, args.stage)
    validate_resume(args.resume_workflow_path)
    print(json.dumps({"validated": True, "mode": args.mode}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
