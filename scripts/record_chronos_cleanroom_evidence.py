"""Append the portable Chronos clean-room decisions and evidence graph nodes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "reports/council/decision-ledger.jsonl"
GRAPH = ROOT / "reports/evidence/evidence-graph.json"

BASE_SHA = "8591024b1ef96d766ab0e1090c45d15e3a25d429"
SOURCE_SHA = "a25b288b5fc3c9eb6cd95ddb10f88db6a0aec1db"
BASE_TIP_ID = "RCV3-20260809-101"
BASE_TIP_HASH = "e6dd93c253e9449ea70ad33fe22c0728b22b0b74dd109c52a9664284da891828"
NEW_IDS = [f"RCV3-20260810-{suffix:03d}" for suffix in range(109, 116)]
REPORTS = {
    "audit": "reports/closure/pr45-file-classification-v1.json",
    "paths": "reports/closure/pr45-absolute-path-and-ledger-audit-v1.json",
    "ledger": "reports/closure/pr45-ledger-portability-audit-v1.json",
    "equivalence": "reports/closure/chronos-cleanroom-source-equivalence-v1.json",
    "parquet": "reports/portability/parquet-windows-linux-root-cause-v1.json",
    "main_paths": "reports/activation/chronos-activation-initial-state-v1.json",
    "review": "reports/closure/chronos-cleanroom-pre-ci-review-v1.json",
}


def canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def compact_json(value: object, level: int = 0) -> str:
    """Use the repository's established evidence-graph serialization."""
    if isinstance(value, dict):
        rows = [
            " " * (level + 2)
            + json.dumps(str(key), ensure_ascii=False)
            + ":"
            + compact_json(item, level + 2)
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(rows) + "\n" + " " * level + "}"
    if isinstance(value, list):
        if not value or all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ",".join(compact_json(item, level) for item in value) + "]"
        if all(
            isinstance(item, dict)
            and all(not isinstance(child, (dict, list)) for child in item.values())
            for item in value
        ):
            rows = [
                " " * (level + 2) + json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in value
            ]
            return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
        rows = [" " * (level + 2) + compact_json(item, level + 2) for item in value]
        return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def file_sha256(path: str) -> str:
    artifact = ROOT / path
    payload = artifact.read_bytes()
    if artifact.suffix.casefold() in {
        ".csv",
        ".json",
        ".jsonl",
        ".md",
        ".py",
        ".toml",
        ".yaml",
        ".yml",
    }:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def changed_files() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    paths: set[str] = {
        LEDGER.relative_to(ROOT).as_posix(),
        GRAPH.relative_to(ROOT).as_posix(),
    }
    for line in result.stdout.splitlines():
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        paths.add(raw.replace("\\", "/").strip('"'))
    missing = sorted(path for path in paths if not (ROOT / path).is_file())
    if missing:
        raise SystemExit(f"PRECOMMIT_FILE_MISSING:{','.join(missing)}")
    return sorted(paths)


def governance_allowed_paths() -> list[str]:
    matrix = json.loads(
        (ROOT / "configs/agents/mission-activation-matrix-v3.json").read_text(encoding="utf-8")
    )
    return sorted(matrix["missions"]["GOVERNANCE"]["allowed_paths"])


def claim(
    claim_id: str,
    statement: str,
    scope: str,
    source: str,
    artifact: str,
    verified_by: list[str],
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim": statement,
        "scope": scope,
        "source": source,
        "grain": "one_chronos_cleanroom_portable_integration",
        "temporal_class": "CODE_AND_LOCAL_EXECUTION_AS_OF",
        "artifact": artifact,
        "hash": file_sha256(artifact),
        "code_revision": BASE_SHA,
        "execution_id": "chronos-cleanroom-portable-integration-v1-precommit",
        "scientific_lineage_id": "chronos-dual-principal-authority-e1-v2",
        "dataset_lineage_id": "PR45_VALIDATION_RUNS_31413302734_31427069583",
        "status": "VERIFIED",
        "verified_by": verified_by,
    }


def common_context() -> dict[str, Any]:
    return {
        "branch": "codex/chronos-cleanroom-portable-integration-v1",
        "base_sha": BASE_SHA,
        "source_pr": 45,
        "source_head_sha": SOURCE_SHA,
        "specialized_ci_run": 31413302734,
        "canonical_ci_run": 31427069583,
        "excluded_pr45_record_ids": [f"RCV3-20260810-{suffix:03d}" for suffix in range(102, 109)],
        "neon_api_calls": 0,
        "production_postgresql_reads": 0,
        "production_postgresql_writes": 0,
        "r2_operations": 0,
        "provider_calls": 0,
        "migration_dispatches": 0,
        "migration_authorized": False,
    }


def record(
    decision_id: str,
    record_type: str,
    date: str,
    proposal: str,
    objections: list[str],
    proof: list[str],
    decision: str,
    context: dict[str, Any],
    previous_hash: str,
) -> dict[str, Any]:
    value = {
        "decision_id": decision_id,
        "record_type": record_type,
        "date": date,
        "proposal": proposal,
        "objections": objections,
        "proof": proof,
        "decision": decision,
        "dissent": None,
        "responsible": "C0",
        "context": context,
        "previous_hash": previous_hash,
        "hash_algorithm": "SHA-256",
    }
    value["hash"] = canonical_hash(value)
    return value


def validate_chain(records: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    for item in records:
        if item["previous_hash"] != previous:
            raise SystemExit(f"LEDGER_PREVIOUS_HASH_INVALID:{item['decision_id']}")
        if (
            canonical_hash({key: value for key, value in item.items() if key != "hash"})
            != item["hash"]
        ):
            raise SystemExit(f"LEDGER_HASH_INVALID:{item['decision_id']}")
        previous = item["hash"]


def build_claims() -> list[dict[str, Any]]:
    return [
        claim(
            "GOV.CHRONOS.CLEANROOM.PR45.AUDIT.V1.001",
            "All 45 PR45 files are classified from exact Git objects; contaminated, stale and non-portable evidence is excluded without modifying PR45.",
            "PR45_EXACT_FILE_CLASSIFICATION_AND_EXTRACTION_POLICY",
            "PR45 Git tree and three read-only role audits",
            REPORTS["audit"],
            ["C0", "DP5", "DP6", "C4"],
        ),
        claim(
            "SECURITY.CHRONOS.CLEANROOM.PATHS.V1.001",
            "Four unique local paths and nine occurrences are isolated to the PR45 initial-state report and records 102 through 108; none is imported.",
            "PR45_ABSOLUTE_PATH_AND_APPEND_ONLY_CONTAMINATION",
            "full PR45 text scan and append-only audit",
            REPORTS["paths"],
            ["C0", "DP6", "C4"],
        ),
        claim(
            "GOV.CHRONOS.CLEANROOM.LEDGER.REBUILD.V1.001",
            "The clean-room ledger and graph preserve the exact main prefix and rebuild only new portable records, claims and edges from the main tip.",
            "CLEANROOM_APPEND_ONLY_PREFIX_PRESERVATION",
            "main and PR45 ledger-chain and evidence-graph comparison",
            REPORTS["ledger"],
            ["C0", "DP6", "C4"],
        ),
        claim(
            "GOV.CHRONOS.CLEANROOM.EQUIVALENCE.V1.001",
            "Every critical PR45 file is byte-identical, portably adapted, rebuilt by evidence reference or intentionally excluded; unexplained differences equal zero.",
            "PR45_TO_CLEANROOM_SOURCE_EQUIVALENCE",
            "Git blob comparison against exact PR45 head",
            REPORTS["equivalence"],
            ["C0", "DP5", "DP6", "C4"],
        ),
        claim(
            "PORT.CHRONOS.PARQUET.VERSION_DRIFT.V1.001",
            "The three canonical Parquet differences are metadata-only PyArrow writer-version drift; rows, schema, nulls, float bits and scientific payload are unchanged.",
            "CANONICAL_PARQUET_WINDOWS_LINUX_ROOT_CAUSE",
            "canonical run artifacts and deterministic footer micro-experiment",
            REPORTS["parquet"],
            ["C0", "DP5", "DP6"],
        ),
        claim(
            "SECURITY.CHRONOS.MAIN.PATHS.SANITIZED.V1.001",
            "Four pre-existing main worktree values are replaced by stable labels while their original values remain attributable through SHA-256 fingerprints.",
            "MAIN_NON_LEDGER_LOCAL_PATH_SUCCESSOR_SANITIZATION",
            "tracked-path gate and append-only successor decision",
            REPORTS["main_paths"],
            ["C0", "DP6", "C4"],
        ),
        claim(
            "GOV.CHRONOS.CLEANROOM.PRE_CI.REVIEW.V1.001",
            "PORT, EVIDENCE, DBA, SRE, SEC and RED independently passed the exact staged clean-room index with no P0 or P1 and a minimum score of 97.",
            "CLEANROOM_EXACT_STAGED_INDEX_PRE_CI_REVIEW",
            "independent read-only reviews DP5, DP6 and C4",
            REPORTS["review"],
            ["DP5", "DP6", "C4"],
        ),
    ]


def build_records(claims: list[dict[str, Any]], files: list[str]) -> list[dict[str, Any]]:
    claim_ids = {item["claim_id"] for item in claims}
    review_claim_id = "GOV.CHRONOS.CLEANROOM.PRE_CI.REVIEW.V1.001"
    technical_claim_ids = claim_ids - {review_claim_id}
    contexts = common_context()
    specs = [
        (
            "CLEANROOM_EXTRACTION_DECISION",
            "Extract only the portable and necessary PR45 components from exact origin/main without merging or rewriting PR45.",
            [
                "PR45 contains local absolute paths and contaminated append-only records.",
                "Several production documents and a mutative workflow retain stale or unsafe authority assumptions.",
            ],
            [
                "GOV.CHRONOS.CLEANROOM.PR45.AUDIT.V1.001",
                "SECURITY.CHRONOS.CLEANROOM.PATHS.V1.001",
            ],
            "PASS. Accept the selective clean-room extraction policy and keep PR45 as validated non-portable history.",
        ),
        (
            "PR45_EXTERNAL_VALIDATION_REFERENCE",
            "Preserve PR45 architecture validation through exact GitHub run and commit identifiers rather than copied local reports.",
            [
                "The specialized run is green but does not publish the exact protected tests context.",
                "The canonical visual failure is attributable to dependency metadata drift and remains an integration blocker until redesigned CI passes.",
            ],
            [
                "GOV.CHRONOS.CLEANROOM.PR45.AUDIT.V1.001",
                "PORT.CHRONOS.PARQUET.VERSION_DRIFT.V1.001",
            ],
            "PASS_AND_HOLD. Reuse runs 31413302734 and 31427069583 as external historical validation only; do not authorize merge from them.",
        ),
        (
            "MAIN_PATH_PORTABILITY_CORRECTION",
            "Remove four pre-existing local worktree values from a mutable main activation snapshot without rewriting any ledger record.",
            [
                "The new tracked-path gate correctly identifies four historical values already present on main.",
                "Deleting attribution entirely would lose the historical binding.",
            ],
            [
                "SECURITY.CHRONOS.MAIN.PATHS.SANITIZED.V1.001",
                "SECURITY.CHRONOS.CLEANROOM.PATHS.V1.001",
            ],
            "PASS. Replace only mutable snapshot values with stable worktree labels, preserve original-value SHA-256 fingerprints, and record this successor; keep all prior ledger bytes unchanged.",
        ),
        (
            "PORTABILITY_REDESIGN_DECISION",
            "Make Windows the canonical frozen-evidence producer and require Linux consumers to verify, not rebuild, the immutable artifact.",
            [
                "Unpinned PyArrow patch versions change Parquet footer bytes and therefore frozen container hashes.",
                "Replacing expected hashes or weakening scientific checks is forbidden.",
            ],
            [
                "PORT.CHRONOS.PARQUET.VERSION_DRIFT.V1.001",
                "GOV.CHRONOS.CLEANROOM.EQUIVALENCE.V1.001",
            ],
            "PASS. Pin PyArrow 25.0.0, produce exact historical bytes on Windows, publish a source-bound manifest and verify it fail-closed on Linux.",
        ),
        (
            "PRE_COMMIT",
            "Record the bounded clean-room change set and targeted validations before its first commit.",
            [
                "PostgreSQL 16 runtime profiles and the complete repository suite remain pending canonical CI and the single pre-merge full-suite gate.",
                "No Neon, production PostgreSQL, R2 or provider access is authorized during clean-room integration.",
            ],
            sorted(technical_claim_ids),
            "PASS_AND_HOLD. Freeze the bounded staged scope for independent review; no commit, publication, Ready transition or merge is authorized by this record.",
        ),
        (
            "PRE_CI_REVIEW_REQUEST",
            "Request PORT, EVIDENCE, DBA/DP6, SRE, SEC and RED read-only review of the exact staged diff before CI publication.",
            [
                "The exact staged diff must be reviewed independently before any delivery verdict can be recorded.",
                "Any P0 or P1 introduced by the final diff must fail the delivery gate.",
            ],
            sorted(technical_claim_ids),
            "HOLD_PENDING_INDEPENDENT_REVIEW. This record attributes no reviewer verdict and authorizes neither commit nor publication.",
        ),
        (
            "DELIVERY_REVIEW",
            "Accept the six-role independent pre-CI review of the exact staged clean-room index.",
            [
                "DP5 passed PORT and SRE at 98 with no P0 or P1.",
                "DP6 passed EVIDENCE and DBA at 98 with no P0 or P1.",
                "C4 passed SEC and RED at 97 with no P0 or P1.",
            ],
            [review_claim_id],
            "PASS_PRE_CI. Authorize one local clean-room commit and non-force publication to a Draft PR; Ready and merge remain gated on the clean-LF full suite and exact-head canonical CI.",
        ),
    ]
    result: list[dict[str, Any]] = []
    previous = BASE_TIP_HASH
    for index, spec in enumerate(specs):
        context = dict(contexts)
        if spec[0] == "PRE_COMMIT":
            context.update(
                {
                    "worktree": "WORKTREE:chronos-cleanroom-portable-integration-v1",
                    "branch": "codex/chronos-cleanroom-portable-integration-v1",
                    "head": BASE_SHA,
                    "pr": None,
                    "writer": "C0_DESIGNATED_ROOT",
                    "files": governance_allowed_paths(),
                    "files_contract": "LEGACY_GOVERNANCE_ALLOWED_PATHS_REQUIRED_BY_COUNCIL_SCHEMA",
                    "delivery_files": files,
                    "targeted_tests": [
                        "225 targeted portability, activation, Chronos and evidence tests passed; 12 environment-bound tests skipped",
                        "Parquet canonical full evidence rebuild matched all three frozen SHA-256 values",
                        "Ruff and YAML parsing passed on the targeted clean-room scope",
                    ],
                    "reused_evidence": [
                        f"PR45 exact head {SOURCE_SHA}",
                        "specialized validation run 31413302734",
                        "canonical root-cause run 31427069583",
                        f"main ledger tip {BASE_TIP_ID} {BASE_TIP_HASH}",
                    ],
                }
            )
        if spec[0] == "DELIVERY_REVIEW":
            context.update(
                {
                    "review_report": REPORTS["review"],
                    "reviewed_index_tree_sha": "c47c4f54a9afd57fbce6f3394360447cdad97a5a",
                    "reviewers": {
                        "DP5": {"roles": ["PORT", "SRE"], "score": 98},
                        "DP6": {"roles": ["EVIDENCE", "DBA"], "score": 98},
                        "C4": {"roles": ["SEC", "RED"], "score": 97},
                    },
                    "verdict": "PASS_PRE_CI",
                    "p0": 0,
                    "p1": 0,
                    "minimum_score": 97,
                }
            )
        decided_at = (
            "2026-08-10T22:49:00Z"
            if spec[0] == "DELIVERY_REVIEW"
            else f"2026-08-10T20:{10 + index:02d}:00Z"
        )
        item = record(
            NEW_IDS[index],
            spec[0],
            decided_at,
            spec[1],
            spec[2],
            spec[3],
            spec[4],
            context,
            previous,
        )
        result.append(item)
        previous = item["hash"]
    return result


def verify_final(records: list[dict[str, Any]], graph: dict[str, Any]) -> None:
    validate_chain(records)
    by_id = {record["decision_id"]: record["hash"] for record in records}
    nodes = {node["decision_id"]: node["ledger_record_hash"] for node in graph["decision_nodes"]}
    if nodes != by_id:
        raise SystemExit("GRAPH_LEDGER_NODE_MISMATCH")
    claim_ids = {item["claim_id"] for item in graph["claims"]}
    if any(set(item["proof"]) - claim_ids for item in records):
        raise SystemExit("LEDGER_PROOF_CLAIM_MISSING")
    if any(
        file_sha256(item["artifact"]) != item["hash"]
        for item in graph["claims"]
        if item["claim_id"].startswith(
            ("GOV.CHRONOS.CLEANROOM", "SECURITY.CHRONOS.CLEANROOM", "PORT.CHRONOS.PARQUET")
        )
    ):
        raise SystemExit("CLEANROOM_CLAIM_ARTIFACT_HASH_MISMATCH")


def main() -> None:
    original_ledger = LEDGER.read_text(encoding="utf-8")
    records = [json.loads(line) for line in original_ledger.splitlines() if line.strip()]
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if len(records) > 101:
        validate_chain(records)
        suffix_length = len(records) - 101
        expected_suffix = [
            f"RCV3-20260810-{suffix:03d}"
            for suffix in range(109, 109 + suffix_length)
        ]
        if [item["decision_id"] for item in records[101:]] != expected_suffix:
            raise SystemExit("CLEANROOM_EXISTING_SUFFIX_INVALID")
        records = records[:101]
        original_ledger = "".join(
            original_ledger.splitlines(keepends=True)[: len(records)]
        )
        graph["claims"] = graph["claims"][:117]
        graph["decision_nodes"] = graph["decision_nodes"][:101]
        graph["edges"] = graph["edges"][:274]
    validate_chain(records)
    if (
        len(records) != 101
        or records[-1]["decision_id"] != BASE_TIP_ID
        or records[-1]["hash"] != BASE_TIP_HASH
    ):
        raise SystemExit("CLEANROOM_LEDGER_NOT_AT_EXACT_MAIN_TIP")
    if (len(graph["claims"]), len(graph["decision_nodes"]), len(graph["edges"])) != (117, 101, 274):
        raise SystemExit("CLEANROOM_GRAPH_NOT_AT_EXACT_MAIN_BASE")
    if graph["edges"][-1]["edge_id"] != "EDGE.274":
        raise SystemExit("CLEANROOM_GRAPH_EDGE_TIP_INVALID")

    claims = build_claims()
    new_records = build_records(claims, changed_files())
    records.extend(new_records)
    graph["generated_at"] = "2026-08-10T20:14:00Z"
    graph["claims"].extend(claims)
    graph["decision_nodes"].extend(
        {"decision_id": item["decision_id"], "ledger_record_hash": item["hash"]}
        for item in new_records
    )
    edge_index = 275
    for item in new_records:
        for claim_id in item["proof"]:
            graph["edges"].append(
                {
                    "edge_id": f"EDGE.{edge_index}",
                    "from_claim_id": claim_id,
                    "to_decision_id": item["decision_id"],
                    "relation": "SUPPORTS",
                    "status": "RECORDED",
                }
            )
            edge_index += 1

    separator = "" if original_ledger.endswith("\n") else "\n"
    appended = "".join(
        json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in new_records
    )
    LEDGER.write_text(
        original_ledger + separator + appended,
        encoding="utf-8",
        newline="\n",
    )
    GRAPH.write_text(compact_json(graph) + "\n", encoding="utf-8", newline="\n")
    verify_final(records, graph)
    print("CHRONOS_CLEANROOM_EVIDENCE_REBUILT")


if __name__ == "__main__":
    main()
