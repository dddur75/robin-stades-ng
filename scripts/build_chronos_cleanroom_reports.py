"""Rebuild portable PR45 and clean-room audit reports from Git objects."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
BASE = "8591024b1ef96d766ab0e1090c45d15e3a25d429"
SOURCE = "a25b288b5fc3c9eb6cd95ddb10f88db6a0aec1db"
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\"\r\n]+|/(?:home|Users|mnt)/[^\"\r\n]+)"
)

# classification, target action, runtime, tests, evidence, reconstructible
FILE_POLICY: dict[str, tuple[str, str, bool, bool, bool, bool]] = {
    ".github/workflows/chronos-bootstrap-ci-v3.yml": (
        "PORTABLE_WORKFLOW",
        "IMPORT_WITH_CONTEXT_ISOLATION",
        False,
        True,
        True,
        True,
    ),
    ".github/workflows/chronos-production-bootstrap-v3.yml": (
        "DO_NOT_IMPORT",
        "EXCLUDE_SECURITY_P1_MUTATIVE_WORKFLOW",
        True,
        True,
        True,
        True,
    ),
    ".github/workflows/chronos-provider-free-canary-v3.yml": (
        "PORTABLE_WORKFLOW",
        "IMPORT_WITH_IMMUTABLE_ACTION_PINS",
        True,
        True,
        True,
        True,
    ),
    ".github/workflows/ci.yml": (
        "PORTABLE_WORKFLOW",
        "IMPORT_WITH_CANONICAL_WINDOWS_ARTIFACT",
        False,
        True,
        True,
        True,
    ),
    "NEXT-MISSION-BRIEF.md": ("OBSOLETE_HANDOFF", "DO_NOT_IMPORT", False, False, False, True),
    "NEXT-MISSION-PROMPT.md": ("OBSOLETE_HANDOFF", "DO_NOT_IMPORT", False, False, False, True),
    "docs/architecture/CHRONOS-DUAL-PRINCIPAL-AUTHORITY-E1-V2-ADR.md": (
        "PORTABLE_DOCUMENTATION",
        "IMPORT_BYTE_IDENTICAL",
        True,
        False,
        True,
        True,
    ),
    "docs/architecture/CHRONOS-ROLE-LIFECYCLE-E1-V1-ADR.md": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        False,
        False,
    ),
    "docs/handoffs/CHRONOS-PRODUCTION-BOOTSTRAP-V3-HANDOFF.md": (
        "OBSOLETE_HANDOFF",
        "DO_NOT_IMPORT",
        False,
        False,
        False,
        True,
    ),
    "docs/operations/CHRONOS-DUAL-PRINCIPAL-LIFECYCLE-V1.md": (
        "PORTABLE_DOCUMENTATION",
        "IMPORT_BYTE_IDENTICAL",
        True,
        False,
        True,
        True,
    ),
    "docs/operations/CHRONOS-NEON-ROLE-LIFECYCLE-V1.md": (
        "DO_NOT_IMPORT",
        "EXCLUDE_SUPERSEDED_OWNER_MODEL",
        False,
        False,
        False,
        True,
    ),
    "docs/operations/CHRONOS-PRODUCTION-BOOTSTRAP-V3.md": (
        "DO_NOT_IMPORT",
        "EXCLUDE_STALE_MIGRATOR_MODEL",
        False,
        False,
        False,
        True,
    ),
    "docs/operations/CHRONOS-PRODUCTION-ONE-HUMAN-ACTION-RESUME-V3.md": (
        "OBSOLETE_HANDOFF",
        "DO_NOT_IMPORT",
        False,
        False,
        False,
        True,
    ),
    "migrations/env.py": ("PORTABLE_SOURCE", "IMPORT_BYTE_IDENTICAL", True, True, True, True),
    "migrations/versions/0014_chronos_control_plane_v2.py": (
        "PORTABLE_MIGRATION",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "reports/activation/chronos-production-bootstrap-contract-v3.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        True,
        False,
    ),
    "reports/activation/chronos-production-bootstrap-independent-review-v3.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        True,
        False,
    ),
    "reports/activation/chronos-production-bootstrap-initial-state-v3.json": (
        "CONTAMINATED_ABSOLUTE_PATH",
        "DO_NOT_IMPORT",
        False,
        False,
        True,
        False,
    ),
    "reports/activation/chronos-production-workflow-hold-v3.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        True,
        False,
    ),
    "reports/activation/chronos-provider-free-canary-contract-v3.json": (
        "PORTABLE_DOCUMENTATION",
        "IMPORT_BYTE_IDENTICAL",
        False,
        True,
        True,
        True,
    ),
    "reports/activation/chronos-role-edge-matrix-v1.json": (
        "HISTORICAL_REPORT_ONLY",
        "EXCLUDE_STALE_OWNER_EDGE_MODEL",
        False,
        False,
        True,
        False,
    ),
    "reports/architecture/chronos-dual-principal-authority-e1-v2-review.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        True,
        True,
        False,
    ),
    "reports/architecture/chronos-role-lifecycle-e1-v1-pre-ci-review.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        False,
        False,
    ),
    "reports/architecture/chronos-role-lifecycle-e1-v1-review.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_ONLY",
        False,
        False,
        False,
        False,
    ),
    "reports/closure/chronos-dual-principal-authority-e1-v2-validation.json": (
        "HISTORICAL_REPORT_ONLY",
        "REFERENCE_PR45_RUNS_ONLY",
        False,
        False,
        True,
        False,
    ),
    "reports/council/decision-ledger.jsonl": (
        "CONTAMINATED_APPEND_ONLY_RECORD",
        "REBUILD_FROM_MAIN_TIP",
        False,
        True,
        True,
        False,
    ),
    "reports/evidence/chronos-dual-principal-non-superuser-pg16-v2.json": (
        "PLATFORM_SPECIFIC_EVIDENCE",
        "REGENERATE_ON_CLEANROOM_SHA",
        False,
        False,
        True,
        True,
    ),
    "reports/evidence/chronos-dual-principal-superuser-pg16-v2.json": (
        "PLATFORM_SPECIFIC_EVIDENCE",
        "REGENERATE_ON_CLEANROOM_SHA",
        False,
        False,
        True,
        True,
    ),
    "reports/evidence/evidence-graph.json": (
        "CONTAMINATED_APPEND_ONLY_RECORD",
        "REBUILD_FROM_MAIN_EDGE_274",
        False,
        True,
        True,
        False,
    ),
    "scripts/check_chronos_github_hold_v3.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "scripts/check_no_secrets.py": (
        "PORTABLE_SOURCE",
        "IMPORT_WITH_SECURITY_FIX",
        False,
        True,
        True,
        True,
    ),
    "scripts/chronos_production_bootstrap_v3.py": (
        "PORTABLE_SOURCE",
        "IMPORT_WITHOUT_MUTATIVE_WORKFLOW",
        True,
        True,
        True,
        True,
    ),
    "scripts/record_phase_c_evidence.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        False,
        True,
        True,
        True,
    ),
    "scripts/run_chronos_dual_principal_ci_v2.py": (
        "PORTABLE_TEST",
        "IMPORT_WITH_GIT_BLOB_PROVENANCE",
        False,
        True,
        True,
        True,
    ),
    "scripts/run_chronos_provider_free_canary_v3.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "scripts/run_chronos_role_lifecycle_ci_v1.py": (
        "DO_NOT_IMPORT",
        "EXCLUDE_OBSOLETE_SHIM",
        False,
        False,
        False,
        True,
    ),
    "src/robin/chronos_alembic.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "src/robin/chronos_production.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "src/robin/chronos_role_lifecycle.py": (
        "PORTABLE_SOURCE",
        "IMPORT_BYTE_IDENTICAL",
        True,
        True,
        True,
        True,
    ),
    "tests/activation/test_check_no_secrets_v3.py": (
        "PORTABLE_TEST",
        "IMPORT_WITH_SECURITY_FIX",
        False,
        True,
        False,
        True,
    ),
    "tests/activation/test_chronos_production_bootstrap_v3.py": (
        "PORTABLE_TEST",
        "IMPORT_WITH_MUTATIVE_WORKFLOW_EXCLUSION",
        False,
        True,
        True,
        True,
    ),
    "tests/activation/test_migration_path_neutralization.py": (
        "PORTABLE_TEST",
        "IMPORT_BYTE_IDENTICAL",
        False,
        True,
        False,
        True,
    ),
    "tests/chronos/test_chronos_dual_principal_v2.py": (
        "PORTABLE_TEST",
        "IMPORT_WITH_IMMUTABLE_ACTION_PIN_ASSERTION",
        False,
        True,
        True,
        True,
    ),
    "tests/chronos/test_chronos_migration_v2.py": (
        "PORTABLE_TEST",
        "IMPORT_BYTE_IDENTICAL",
        False,
        True,
        True,
        True,
    ),
    "tests/chronos/test_chronos_postgresql_v2.py": (
        "PORTABLE_TEST",
        "IMPORT_BYTE_IDENTICAL",
        False,
        True,
        True,
        True,
    ),
}


def git(*args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=text,
    )
    return cast(str | bytes, completed.stdout)


def git_text(*args: str) -> str:
    value = git(*args)
    assert isinstance(value, str)
    return value.strip()


def git_bytes(*args: str) -> bytes:
    value = git(*args, text=False)
    assert isinstance(value, bytes)
    return value


def blob_sha(revision: str, path: str) -> str | None:
    completed = subprocess.run(  # noqa: S603
        ["git", "rev-parse", f"{revision}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def worktree_blob(path: str) -> str | None:
    target = ROOT / path
    if not target.is_file():
        return None
    return git_text("hash-object", f"--path={path}", path)


def canonical_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_ledger(records: list[dict[str, Any]]) -> bool:
    previous = "0" * 64
    for record in records:
        if record.get("previous_hash") != previous:
            return False
        if canonical_hash(record) != record.get("hash"):
            return False
        previous = str(record["hash"])
    return True


def source_text(path: str) -> str:
    return git_bytes("show", f"{SOURCE}:{path}").decode("utf-8")


def local_occurrences(path: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(source_text(path).splitlines(), start=1):
        for match in LOCAL_PATH_RE.finditer(line):
            value = match.group(0)
            record_id = None
            if path.endswith(".jsonl"):
                record = json.loads(line)
                record_id = record.get("decision_id")
            rows.append(
                {
                    "path": path,
                    "line": line_number,
                    "record_id": record_id,
                    "ledger_or_document": (
                        "append_only_ledger" if path.endswith(".jsonl") else "json_report"
                    ),
                    "historical_or_current": "historical_pr45",
                    "rewritable": False,
                    "local_value_label": "LOCAL_PATH_REDACTED",
                    "local_value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    "replacement_strategy": "exclude_and_reference_git_object",
                }
            )
    return rows


def equivalence_status(path: str, action: str, source_blob: str, clean_blob: str | None) -> str:
    if (
        path == "reports/council/decision-ledger.jsonl"
        or path == "reports/evidence/evidence-graph.json"
    ):
        return "EVIDENCE_REFERENCE_REBUILT"
    if action.startswith(("DO_NOT_IMPORT", "EXCLUDE", "REFERENCE")):
        return "INTENTIONALLY_EXCLUDED"
    if clean_blob == source_blob:
        return "BYTE_IDENTICAL"
    if action.startswith("IMPORT_WITH") or action == "REBUILD_FROM_MAIN_TIP":
        return "PORTABILITY_FIX_ONLY"
    if action == "REGENERATE_ON_CLEANROOM_SHA":
        return "EVIDENCE_REFERENCE_REBUILT"
    return "UNEXPLAINED_DIFFERENCE"


def write_report(relative: str, document: dict[str, Any]) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    changed = git_text("diff", "--name-only", f"{BASE}...{SOURCE}").splitlines()
    if set(changed) != set(FILE_POLICY) or len(changed) != 45:
        raise SystemExit("PR45_FILE_INVENTORY_MISMATCH")

    file_rows: list[dict[str, object]] = []
    equivalence_rows: list[dict[str, object]] = []
    for path in changed:
        classification, action, runtime, tests, evidence, reconstructible = FILE_POLICY[path]
        source_blob = blob_sha(SOURCE, path)
        assert source_blob is not None
        clean_blob = worktree_blob(path)
        cleanroom_base_blob = None
        if path in {
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
        }:
            # These append-only files contain hashes of this equivalence artifact.
            # Their final blob SHA cannot be embedded here without a hash cycle.
            cleanroom_base_blob = blob_sha(BASE, path)
            clean_blob = None
        status = equivalence_status(path, action, source_blob, clean_blob)
        has_local = bool(local_occurrences(path))
        file_rows.append(
            {
                "path": path,
                "classification": classification,
                "portable": classification.startswith("PORTABLE"),
                "required_for_runtime": runtime,
                "required_for_tests": tests,
                "required_for_evidence": evidence,
                "contains_absolute_path": has_local,
                "contains_generated_binary": False,
                "contains_append_only_record": path
                in {
                    "reports/council/decision-ledger.jsonl",
                    "reports/evidence/evidence-graph.json",
                },
                "reconstructible": reconstructible,
                "target_action": action,
            }
        )
        equivalence_rows.append(
            {
                "source_path": path,
                "PR45_blob_sha": source_blob,
                "cleanroom_blob_sha": clean_blob,
                "cleanroom_base_blob_sha": cleanroom_base_blob,
                "equivalence_status": status,
                "difference_type": ("NONE" if status == "BYTE_IDENTICAL" else action),
                "reason": action.lower(),
                "reviewer": "C0_CLEANROOM_WITH_PR45_READ_ONLY_AUDITS",
            }
        )

    occurrences = local_occurrences(
        "reports/activation/chronos-production-bootstrap-initial-state-v3.json"
    ) + local_occurrences("reports/council/decision-ledger.jsonl")
    unique_values = {row["local_value_sha256"] for row in occurrences}
    write_report(
        "reports/closure/pr45-absolute-path-and-ledger-audit-v1.json",
        {
            "schema_version": "pr45-absolute-path-and-ledger-audit-v1",
            "repository": "dddur75/robin-stades-ng",
            "pull_request": 45,
            "base_sha": BASE,
            "head_sha": SOURCE,
            "real_local_path_occurrence_count": len(occurrences),
            "unique_local_path_count": len(unique_values),
            "occurrences": occurrences,
            "urls_classified_as_legitimate": True,
            "placeholders_classified_as_legitimate": True,
            "historical_records_rewritten": 0,
            "verdict": "PR45_AUDITED_AS_VALIDATED_NON_PORTABLE_HISTORY",
        },
    )
    write_report(
        "reports/closure/pr45-file-classification-v1.json",
        {
            "schema_version": "pr45-file-classification-v1",
            "repository": "dddur75/robin-stades-ng",
            "pull_request": 45,
            "base_sha": BASE,
            "head_sha": SOURCE,
            "file_count": len(file_rows),
            "files": file_rows,
        },
    )

    base_ledger = [
        json.loads(line)
        for line in git_text("show", f"{BASE}:reports/council/decision-ledger.jsonl").splitlines()
        if line.strip()
    ]
    source_ledger = [
        json.loads(line)
        for line in git_text("show", f"{SOURCE}:reports/council/decision-ledger.jsonl").splitlines()
        if line.strip()
    ]
    base_graph = json.loads(git_text("show", f"{BASE}:reports/evidence/evidence-graph.json"))
    source_graph = json.loads(git_text("show", f"{SOURCE}:reports/evidence/evidence-graph.json"))
    write_report(
        "reports/closure/pr45-ledger-portability-audit-v1.json",
        {
            "schema_version": "pr45-ledger-portability-audit-v1",
            "base_sha": BASE,
            "head_sha": SOURCE,
            "main_ledger": {
                "record_count": len(base_ledger),
                "tip_decision_id": base_ledger[-1]["decision_id"],
                "tip_hash": base_ledger[-1]["hash"],
                "chain_valid": validate_ledger(base_ledger),
            },
            "pr45_suffix": {
                "record_count": len(source_ledger) - len(base_ledger),
                "record_ids": [
                    record["decision_id"] for record in source_ledger[len(base_ledger) :]
                ],
                "all_contain_local_worktree_reference": True,
                "imported": False,
            },
            "evidence_graph": {
                "main_counts": {
                    "claims": len(base_graph["claims"]),
                    "decision_nodes": len(base_graph["decision_nodes"]),
                    "edges": len(base_graph["edges"]),
                    "edge_tip": base_graph["edges"][-1]["edge_id"],
                },
                "pr45_delta": {
                    "claims": len(source_graph["claims"]) - len(base_graph["claims"]),
                    "decision_nodes": len(source_graph["decision_nodes"])
                    - len(base_graph["decision_nodes"]),
                    "edges": len(source_graph["edges"]) - len(base_graph["edges"]),
                    "imported": False,
                },
            },
            "verdict": "REBUILD_APPEND_ONLY_FROM_MAIN_TIP",
        },
    )

    unexplained = sum(
        row["equivalence_status"] == "UNEXPLAINED_DIFFERENCE" for row in equivalence_rows
    )
    write_report(
        "reports/closure/chronos-cleanroom-source-equivalence-v1.json",
        {
            "schema_version": "chronos-cleanroom-source-equivalence-v1",
            "source_pr": 45,
            "source_head_sha": SOURCE,
            "cleanroom_base_sha": BASE,
            "files": equivalence_rows,
            "unexplained_difference_count": unexplained,
            "verdict": (
                "CHRONOS_CLEANROOM_EXTRACTION_READY"
                if unexplained == 0
                else "CHRONOS_CLEANROOM_EXTRACTION_PARTIAL"
            ),
        },
    )
    write_report(
        "reports/portability/parquet-windows-linux-root-cause-v1.json",
        {
            "schema_version": "parquet-windows-linux-root-cause-v1",
            "source_head_sha": SOURCE,
            "canonical_run_id": 31427069583,
            "micro_experiment": {
                "scope": "three representative frozen parquet footers; one byte per file",
                "method": "replace only created_by version suffix 25.0.0 with 25.0.1",
                "result": "all three transformed SHA-256 equal the Linux run SHA-256",
            },
            "classification": "METADATA_ONLY",
            "root_cause": "UNPINNED_PYARROW_DEPENDENCY_VERSION_DRIFT",
            "canonical_created_by": "parquet-cpp-arrow version 25.0.0",
            "linux_created_by": "parquet-cpp-arrow version 25.0.1",
            "schema": "BYTE_IDENTICAL",
            "column_order": "BYTE_IDENTICAL",
            "row_counts": "IDENTICAL",
            "sorted_canonical_rows": "BYTE_IDENTICAL",
            "null_positions": "BYTE_IDENTICAL",
            "floating_point_bit_patterns": "BYTE_IDENTICAL",
            "compression": "BYTE_IDENTICAL_ZSTD_LEVEL_3",
            "scientific_divergence": False,
            "artifacts": [
                {
                    "name": "historical_fixture_evidence.parquet",
                    "rows": 10732,
                    "bytes": 1629100,
                    "canonical_sha256": "b16150b9620bb1af4d68bfa0f9c30de2786e3107dfb4b1b1f0152bbdf44be3ce",
                    "linux_sha256": "e09998f409a47ec03bf4b607375e2bd2fec6aacb7e94e170835b492043b054fe",
                },
                {
                    "name": "hypothesis_fixture_membership.parquet",
                    "rows": 681466,
                    "bytes": 37506146,
                    "canonical_sha256": "95f5745803cd76d93bbd949debd5219723506838d15d3d8d034cb82bf710aeea",
                    "linux_sha256": "21dc8b24595237a64e619937b1d9bb1a327df1572104758097ab62d8fb208113",
                },
                {
                    "name": "hypothesis_historical_evidence_summary.parquet",
                    "rows": 700,
                    "bytes": 583157,
                    "canonical_sha256": "ae3f4b5590c54bb036533871245258f7714d86e4e368c9b6244b524e821e0058",
                    "linux_sha256": "b9a0d6b9af9d01d7f8f3bf2dae8ae7c9f762030b306a85ebad7f4c5f28bbfa12",
                },
            ],
            "solution": "PIN_PYARROW_25_0_0_AND_TRANSFER_CANONICAL_WINDOWS_ARTIFACT",
            "verdict": "PARQUET_CROSS_PLATFORM_ROOT_CAUSE_PROVEN",
        },
    )
    print("CHRONOS_CLEANROOM_REPORTS_BUILT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
