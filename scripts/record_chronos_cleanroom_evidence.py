"""Append the portable Chronos clean-room decisions and evidence graph nodes."""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
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
CORRECTION_ID = "RCV3-20260810-116"
CORRECTION_REPORT = "reports/closure/chronos-cleanroom-full-suite-correction-v1.json"
DELIVERY_TIP_HASH = "d034d69a372147ed704c0c0bf0b06207b38b365cb1a269f8afe6b7092d8ca966"
CORRECTION_TIP_HASH = "49b94117cabc79af013065190ad239a5f818dc0b1dc46ae1621a203d8702b82a"
CORRECTION_REPORT_SHA256 = "78213c715dd59724c88fc048970f61627cc5d8bac7021c7a2adf610c7b5090f3"
CORRECTION_GENERATED_AT = "2026-08-10T23:05:00Z"
CORRECTION_CLAIM_ID = "GOV.CHRONOS.CLEANROOM.FULL_SUITE.CORRECTION.V1.001"
CI1_CORRECTION_ID = "RCV3-20260810-117"
CI1_CORRECTION_REPORT = "reports/closure/chronos-cleanroom-ci1-correction-v1.json"
CI1_CORRECTION_REPORT_SHA256 = "09e0019373fde42688958d6fe8eed38c322424979124965a592c4f18a7257349"
CI1_CORRECTION_TIP_HASH = "ea40d55aec25913956cc7ec4c8dec88dc34152c6c37ad48b572423cafc27b221"
CI1_CORRECTION_GENERATED_AT = "2026-08-10T23:36:00Z"
CI1_CORRECTION_CLAIM_ID = "GOV.CHRONOS.CLEANROOM.CI1.CORRECTION.V1.001"
PORTABILITY_CORRECTION_ID = "RCV3-20260811-118"
PORTABILITY_CORRECTION_REPORT = (
    "reports/portability/frozen-evidence-manifest-cross-platform-root-cause-v1.json"
)
PORTABILITY_CORRECTION_REPORT_SHA256 = (
    "0bbc800296eac20f5dcaf89db452f316592159745070a61fccac812632b2cf57"
)
PORTABILITY_CORRECTION_TIP_HASH = (
    "45bdecf73253f05f64b38a5170e30d6c90ea0eca7321b84aa15789964f30a51d"
)
PORTABILITY_CORRECTION_GENERATED_AT = "2026-08-11T05:31:52Z"
PORTABILITY_CORRECTION_CLAIM_ID = (
    "PORT.CHRONOS.FROZEN_MANIFEST.GIT_BLOB.V2.001"
)
PORTABILITY_REVIEWS_COMPLETE = True
TEMPORAL_CORRECTION_ID = "RCV3-20260811-119"
TEMPORAL_CORRECTION_REPORT = (
    "reports/governance/council-temporal-determinism-root-cause-v1.json"
)
TEMPORAL_CORRECTION_REPORT_SHA256 = (
    "261863c1f34f74dd247061c8677874fc4db09b31bca70b33e1000fa9548c0506"
)
TEMPORAL_CORRECTION_TIP_HASH = (
    "a1951937a6af243fa64945eb5c246c2c1cc40d72e07f6275fabedfe843fe0889"
)
TEMPORAL_CORRECTION_GENERATED_AT = "2026-08-11T10:46:57Z"
TEMPORAL_CORRECTION_CLAIM_ID = "GOV.COUNCIL.TEMPORAL.DETERMINISM.V1.001"
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
    result = subprocess.run(  # nosec B603 B607
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


def full_suite_correction_claim() -> dict[str, Any]:
    return claim(
        CORRECTION_CLAIM_ID,
        "The clean-LF full suite exposed and bounded one Phase C recorder portability defect; LF-normalized text hashes and extension-aware generated_at preservation restore byte-idempotence without changing any scientific evidence.",
        "CLEANROOM_POST_REVIEW_FULL_SUITE_PORTABILITY_CORRECTION",
        "clean-LF full-suite failure, targeted reproduction and three read-only corrective reviews",
        CORRECTION_REPORT,
        ["C0", "DP5", "DP6", "C4"],
    )


def full_suite_correction_record(correction_claim: dict[str, Any]) -> dict[str, Any]:
    return record(
        CORRECTION_ID,
        "FULL_SUITE_PORTABILITY_CORRECTION",
        "2026-08-10T23:05:00Z",
        "Accept the bounded Phase C recorder idempotence correction discovered by the first clean-LF full suite.",
        [
            "The first clean-LF full suite passed 1509 tests, skipped 21 environment-bound tests and failed one recorder idempotence test.",
            "The correction changes neither historical claims nor scientific values and performs no external operation.",
        ],
        [correction_claim["claim_id"]],
        "PASS_BOUNDED_CORRECTION. Authorize one local corrective commit and Draft PR CI; Ready and merge remain gated on the repeated clean-LF full suite and exact-head CI.",
        {
            **common_context(),
            "first_cleanroom_commit": "ddf776045a7f5c95186b163b19de6502a41a810e",
            "reviewed_correction_tree_sha": "359c5fdbe5dace77e7e1875bda07232d62874418",
            "correction_report": CORRECTION_REPORT,
            "first_full_suite": {"passed": 1509, "skipped": 21, "failed": 1},
            "targeted_idempotence_test": "PASS",
            "reviews": {
                "DP5": {"roles": ["PORT", "SRE"], "verdict": "PASS"},
                "DP6": {"roles": ["EVIDENCE", "DBA"], "verdict": "PASS", "score": 99},
                "C4": {"roles": ["SEC", "RED"], "verdict": "PASS", "score": 98},
            },
            "p0": 0,
            "p1": 0,
        },
        DELIVERY_TIP_HASH,
    )


def verify_graph_shape(
    records: list[dict[str, Any]],
    graph: dict[str, Any],
) -> None:
    claims = graph["claims"]
    nodes = graph["decision_nodes"]
    edges = graph["edges"]
    claim_ids = [item["claim_id"] for item in claims]
    decision_ids = [item["decision_id"] for item in records]
    if len(claim_ids) != len(set(claim_ids)):
        raise SystemExit("GRAPH_DUPLICATE_CLAIM_ID")
    if len(nodes) != len(records):
        raise SystemExit("GRAPH_DECISION_NODE_COUNT_MISMATCH")
    if len(edges) != len({item["edge_id"] for item in edges}):
        raise SystemExit("GRAPH_DUPLICATE_EDGE_ID")
    required_edge_fields = {
        "edge_id",
        "from_claim_id",
        "to_decision_id",
        "relation",
        "status",
    }
    for index, edge in enumerate(edges, start=1):
        if (
            set(edge) != required_edge_fields
            or edge["edge_id"] != f"EDGE.{index:03d}"
            or edge["from_claim_id"] not in claim_ids
            or edge["to_decision_id"] not in decision_ids
            or edge["relation"] != "SUPPORTS"
            or edge["status"] != "RECORDED"
        ):
            raise SystemExit(f"GRAPH_EDGE_INVALID:{index}")


def verify_delivery_final(records: list[dict[str, Any]], graph: dict[str, Any]) -> None:
    verify_final(records, graph)
    verify_graph_shape(records, graph)
    if (
        len(records) != 108
        or len(graph["claims"]) != 124
        or len(graph["decision_nodes"]) != 108
        or len(graph["edges"]) != 295
        or records[-1]["decision_id"] != NEW_IDS[-1]
        or records[-1]["hash"] != DELIVERY_TIP_HASH
        or graph.get("generated_at") != "2026-08-10T20:14:00Z"
    ):
        raise SystemExit("CLEANROOM_DELIVERY_FINAL_STATE_INVALID")


def verify_correction_final(records: list[dict[str, Any]], graph: dict[str, Any]) -> None:
    verify_final(records, graph)
    verify_graph_shape(records, graph)
    expected_claim = full_suite_correction_claim()
    expected_record = full_suite_correction_record(expected_claim)
    expected_node = {
        "decision_id": CORRECTION_ID,
        "ledger_record_hash": CORRECTION_TIP_HASH,
    }
    expected_edge = {
        "edge_id": "EDGE.296",
        "from_claim_id": CORRECTION_CLAIM_ID,
        "to_decision_id": CORRECTION_ID,
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    if file_sha256(CORRECTION_REPORT) != CORRECTION_REPORT_SHA256:
        raise SystemExit("CLEANROOM_CORRECTION_REPORT_HASH_INVALID")
    if (
        len(records) != 109
        or len(graph["claims"]) != 125
        or len(graph["decision_nodes"]) != 109
        or len(graph["edges"]) != 296
        or records[-2]["hash"] != DELIVERY_TIP_HASH
        or records[-1] != expected_record
        or records[-1]["hash"] != CORRECTION_TIP_HASH
        or graph["claims"][-1] != expected_claim
        or graph["decision_nodes"][-1] != expected_node
        or graph["edges"][-1] != expected_edge
        or graph.get("generated_at") != CORRECTION_GENERATED_AT
    ):
        raise SystemExit("CLEANROOM_CORRECTION_FINAL_STATE_INVALID")


def append_full_suite_correction(
    original_ledger: str,
    records: list[dict[str, Any]],
    graph: dict[str, Any],
) -> None:
    verify_delivery_final(records, graph)
    correction_claim = full_suite_correction_claim()
    correction_record = full_suite_correction_record(correction_claim)
    records.append(correction_record)
    graph["generated_at"] = CORRECTION_GENERATED_AT
    graph["claims"].append(correction_claim)
    graph["decision_nodes"].append(
        {
            "decision_id": correction_record["decision_id"],
            "ledger_record_hash": correction_record["hash"],
        }
    )
    graph["edges"].append(
        {
            "edge_id": "EDGE.296",
            "from_claim_id": correction_claim["claim_id"],
            "to_decision_id": correction_record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
    )
    separator = "" if original_ledger.endswith("\n") else "\n"
    appended = json.dumps(
        correction_record, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
    LEDGER.write_text(
        original_ledger + separator + appended,
        encoding="utf-8",
        newline="\n",
    )
    GRAPH.write_text(compact_json(graph) + "\n", encoding="utf-8", newline="\n")
    verify_correction_final(records, graph)


def ci1_correction_claim() -> dict[str, Any]:
    return claim(
        CI1_CORRECTION_CLAIM_ID,
        "CI1 failed before dependency installation because Python 3.12.13 is unavailable on Windows 2025; Python 3.12.10 is the latest exact Windows/Linux runtime and preserves every scientific and manifest binding.",
        "CLEANROOM_CI1_DETERMINISTIC_RUNTIME_AVAILABILITY_CORRECTION",
        "GitHub run 31442379957 logs, official actions/python-versions manifest and three read-only reviews",
        CI1_CORRECTION_REPORT,
        ["C0", "DP5", "DP6", "C4"],
    )


def ci1_correction_record(correction_claim: dict[str, Any]) -> dict[str, Any]:
    return record(
        CI1_CORRECTION_ID,
        "CI1_BOUNDED_CORRECTION",
        "2026-08-10T23:36:00Z",
        "Replace unavailable Python 3.12.13 with exact cross-platform Python 3.12.10 in the canonical evidence producer and both consumers.",
        [
            "CI1 must not be rerun on its old SHA.",
            "No lock, expected hash, scientific value, job dependency or fail-closed gate may be weakened.",
        ],
        [correction_claim["claim_id"]],
        "CI2_BOUNDED_CORRECTION_AUTHORIZED. Authorize one local commit and one non-force push to the Draft PR; Ready and merge remain gated on exact-head CI2 success.",
        {
            **common_context(),
            "pull_request": 46,
            "ci1_run_id": 31442379957,
            "ci1_head_sha": "49498bc1dfb785937f680306bf72a00cb9dff9ed",
            "ci1_failed_job_id": 93629584236,
            "reviewed_correction_tree_sha": "3f04489597fe5ef913a9786eb841c4eb24e6bd65",
            "correction_report": CI1_CORRECTION_REPORT,
            "python_version_before": "3.12.13",
            "python_version_after": "3.12.10",
            "reviews": {
                "DP5": {"roles": ["PORT", "SRE"], "verdict": "PASS", "score": 99},
                "DP6": {"roles": ["EVIDENCE", "DBA"], "verdict": "PASS", "score": 99},
                "C4": {"roles": ["SEC", "RED"], "verdict": "PASS", "score": 99},
            },
            "corrective_ci_cycles_used": 1,
            "corrective_ci_cycles_maximum": 2,
            "p0": 0,
            "p1": 0,
        },
        CORRECTION_TIP_HASH,
    )


def verify_ci1_correction_final(
    records: list[dict[str, Any]], graph: dict[str, Any]
) -> None:
    verify_final(records, graph)
    verify_graph_shape(records, graph)
    correction_claim = ci1_correction_claim()
    correction_record = ci1_correction_record(correction_claim)
    expected_node = {
        "decision_id": CI1_CORRECTION_ID,
        "ledger_record_hash": CI1_CORRECTION_TIP_HASH,
    }
    expected_edge = {
        "edge_id": "EDGE.297",
        "from_claim_id": CI1_CORRECTION_CLAIM_ID,
        "to_decision_id": CI1_CORRECTION_ID,
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    if file_sha256(CI1_CORRECTION_REPORT) != CI1_CORRECTION_REPORT_SHA256:
        raise SystemExit("CLEANROOM_CI1_CORRECTION_REPORT_HASH_INVALID")
    if (
        len(records) != 110
        or len(graph["claims"]) != 126
        or len(graph["decision_nodes"]) != 110
        or len(graph["edges"]) != 297
        or records[-2]["hash"] != CORRECTION_TIP_HASH
        or records[-1] != correction_record
        or records[-1]["hash"] != CI1_CORRECTION_TIP_HASH
        or graph["claims"][-1] != correction_claim
        or graph["decision_nodes"][-1] != expected_node
        or graph["edges"][-1] != expected_edge
        or graph.get("generated_at") != CI1_CORRECTION_GENERATED_AT
    ):
        raise SystemExit("CLEANROOM_CI1_CORRECTION_FINAL_STATE_INVALID")


def append_ci1_correction(
    original_ledger: str,
    records: list[dict[str, Any]],
    graph: dict[str, Any],
) -> None:
    verify_correction_final(records, graph)
    correction_claim = ci1_correction_claim()
    correction_record = ci1_correction_record(correction_claim)
    records.append(correction_record)
    graph["generated_at"] = CI1_CORRECTION_GENERATED_AT
    graph["claims"].append(correction_claim)
    graph["decision_nodes"].append(
        {
            "decision_id": correction_record["decision_id"],
            "ledger_record_hash": correction_record["hash"],
        }
    )
    graph["edges"].append(
        {
            "edge_id": "EDGE.297",
            "from_claim_id": correction_claim["claim_id"],
            "to_decision_id": correction_record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
    )
    separator = "" if original_ledger.endswith("\n") else "\n"
    appended = json.dumps(
        correction_record, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
    LEDGER.write_text(
        original_ledger + separator + appended,
        encoding="utf-8",
        newline="\n",
    )
    GRAPH.write_text(compact_json(graph) + "\n", encoding="utf-8", newline="\n")
    verify_ci1_correction_final(records, graph)


def portability_correction_claim() -> dict[str, Any]:
    return {
        "claim_id": PORTABILITY_CORRECTION_CLAIM_ID,
        "claim": (
            "GitHub run 31443189487 proved that manifest v1 hashed tracked "
            "generator and dependency-lock worktree bytes; manifest v2 binds "
            "those fields to exact Git blobs at source_sha while retaining exact "
            "runtime and Parquet bytes."
        ),
        "scope": "FROZEN_EVIDENCE_CROSS_PLATFORM_PROVENANCE_CORRECTION",
        "source": (
            "GitHub run 31443189487 artifacts and logs, Git-object micro-experiment, "
            "LF/CRLF real-checkout simulation and three read-only reviews"
        ),
        "grain": "one_chronos_cleanroom_portable_integration",
        "temporal_class": "CODE_AND_LOCAL_EXECUTION_AS_OF",
        "artifact": PORTABILITY_CORRECTION_REPORT,
        "hash": file_sha256(PORTABILITY_CORRECTION_REPORT),
        "code_revision": "0b19c7fb83c3323117a626aff575c8abb335374b",
        "execution_id": "github-actions-31443189487-plus-local-git-blob-v2",
        "scientific_lineage_id": "chronos-dual-principal-authority-e1-v2",
        "dataset_lineage_id": "RUN_31443189487_CANONICAL_WINDOWS_ARTIFACTS",
        "status": "VERIFIED",
        "verified_by": ["C0", "DP5", "DP6", "C4"],
    }


def portability_correction_record(correction_claim: dict[str, Any]) -> dict[str, Any]:
    return record(
        PORTABILITY_CORRECTION_ID,
        "CI2_PORTABLE_MANIFEST_CORRECTION",
        PORTABILITY_CORRECTION_GENERATED_AT,
        "Bind frozen-evidence tracked provenance to exact Git blobs at source_sha and preserve runtime inputs as transferred bytes.",
        [
            "Run 31443189487 failed only because manifest v1 depended on Windows CRLF worktree materialization.",
            "requirements-evidence.lock would produce the same deterministic mismatch if it remained worktree-bound.",
            "A third corrective architecture cycle is forbidden after this bounded final correction.",
        ],
        [correction_claim["claim_id"]],
        "PASS_BOUNDED_FINAL_CORRECTION. Authorize one local commit and one non-force push to PR46; Ready and merge remain gated on exact-head CI success.",
        {
            **common_context(),
            "pull_request": 46,
            "failed_run_id": 31443189487,
            "failed_head_sha": "0b19c7fb83c3323117a626aff575c8abb335374b",
            "failed_tree_sha": "2060a1dfeaf642d92ae1e01745869f21f17462a3",
            "failed_job_id": 93635337472,
            "failed_step": "Verifier les bytes et le manifeste canoniques",
            "failed_code": "FROZEN_EVIDENCE_GENERATOR_HASH_MISMATCH",
            "root_cause": "WORKTREE_LINE_ENDING_DEPENDENCE",
            "correction_report": PORTABILITY_CORRECTION_REPORT,
            "schema_before": "frozen-evidence-portable-manifest-v1",
            "schema_after": "frozen-evidence-portable-manifest-v2",
            "generator_hash_basis": "git_blob_bytes_at_source_sha",
            "dependency_lock_hash_basis": "git_blob_bytes_at_source_sha",
            "inputs_hash_basis": "runtime_file_bytes",
            "cross_platform_manifest_sha256": (
                "1bfdf0dd72786149e1181e3d017c17d917e3d0ea05b733852291569dc1bfea03"
            ),
            "targeted_tests": {"passed": 62, "skipped": 2, "failed": 0},
            "reviews": {
                "DP5": {"roles": ["PORT", "SRE"], "verdict": "PASS", "score": 98},
                "DP6": {
                    "roles": ["EVIDENCE", "DBA"],
                    "verdict": "PASS",
                    "score": 98,
                },
                "C4": {"roles": ["SEC", "RED"], "verdict": "PASS", "score": 98},
            },
            "corrective_ci_cycles_used": 2,
            "corrective_ci_cycles_maximum": 2,
            "third_architectural_cycle_authorized": False,
            "next_source_sha_binding": "EXACT_COMMIT_CONTAINING_THIS_RECORD",
            "next_ci_run_binding": "AUTOMATIC_PR46_EXACT_HEAD_RUN",
            "p0": 0,
            "p1": 0,
        },
        CI1_CORRECTION_TIP_HASH,
    )


def verify_portability_correction_final(
    records: list[dict[str, Any]], graph: dict[str, Any]
) -> None:
    verify_final(records, graph)
    verify_graph_shape(records, graph)
    correction_claim = portability_correction_claim()
    correction_record = portability_correction_record(correction_claim)
    expected_node = {
        "decision_id": PORTABILITY_CORRECTION_ID,
        "ledger_record_hash": PORTABILITY_CORRECTION_TIP_HASH,
    }
    expected_edge = {
        "edge_id": "EDGE.298",
        "from_claim_id": PORTABILITY_CORRECTION_CLAIM_ID,
        "to_decision_id": PORTABILITY_CORRECTION_ID,
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    if file_sha256(PORTABILITY_CORRECTION_REPORT) != PORTABILITY_CORRECTION_REPORT_SHA256:
        raise SystemExit("CLEANROOM_PORTABILITY_CORRECTION_REPORT_HASH_INVALID")
    if (
        len(records) != 111
        or len(graph["claims"]) != 127
        or len(graph["decision_nodes"]) != 111
        or len(graph["edges"]) != 298
        or records[-2]["hash"] != CI1_CORRECTION_TIP_HASH
        or records[-1] != correction_record
        or records[-1]["hash"] != PORTABILITY_CORRECTION_TIP_HASH
        or graph["claims"][-1] != correction_claim
        or graph["decision_nodes"][-1] != expected_node
        or graph["edges"][-1] != expected_edge
        or graph.get("generated_at") != PORTABILITY_CORRECTION_GENERATED_AT
    ):
        raise SystemExit("CLEANROOM_PORTABILITY_CORRECTION_FINAL_STATE_INVALID")


def append_portability_correction(
    original_ledger: str,
    records: list[dict[str, Any]],
    graph: dict[str, Any],
) -> None:
    if not PORTABILITY_REVIEWS_COMPLETE:
        raise SystemExit("CLEANROOM_PORTABILITY_REVIEWS_PENDING")
    verify_ci1_correction_final(records, graph)
    correction_claim = portability_correction_claim()
    correction_record = portability_correction_record(correction_claim)
    records.append(correction_record)
    graph["generated_at"] = PORTABILITY_CORRECTION_GENERATED_AT
    graph["claims"].append(correction_claim)
    graph["decision_nodes"].append(
        {
            "decision_id": correction_record["decision_id"],
            "ledger_record_hash": correction_record["hash"],
        }
    )
    graph["edges"].append(
        {
            "edge_id": "EDGE.298",
            "from_claim_id": correction_claim["claim_id"],
            "to_decision_id": correction_record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
    )
    separator = "" if original_ledger.endswith("\n") else "\n"
    appended = json.dumps(
        correction_record, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
    LEDGER.write_text(
        original_ledger + separator + appended,
        encoding="utf-8",
        newline="\n",
    )
    GRAPH.write_text(compact_json(graph) + "\n", encoding="utf-8", newline="\n")
    verify_portability_correction_final(records, graph)


def temporal_correction_claim() -> dict[str, Any]:
    return {
        "claim_id": TEMPORAL_CORRECTION_CLAIM_ID,
        "claim": (
            "GitHub run 31462358073 proved that frozen contract validation was "
            "coupled to the live Council clock; static contract validation is now "
            "time-invariant while live validation still rejects at and after expiry."
        ),
        "scope": "FROZEN_GOVERNANCE_TEMPORAL_DETERMINISM_CORRECTION",
        "source": (
            "GitHub run 31462358073 logs, complete validator call-site audit and "
            "the deterministic expiry-boundary micro-proof"
        ),
        "grain": "one_council_activation_contract",
        "temporal_class": "CODE_AND_LOCAL_EXECUTION_AS_OF",
        "artifact": TEMPORAL_CORRECTION_REPORT,
        "hash": file_sha256(TEMPORAL_CORRECTION_REPORT),
        "code_revision": "eba31bf562d41d45bebda46fc831e308a8668566",
        "execution_id": "github-actions-31462358073-plus-local-temporal-proof-v1",
        "scientific_lineage_id": "chronos-dual-principal-authority-e1-v2",
        "dataset_lineage_id": "NO_DATASET_GOVERNANCE_VALIDATION_ONLY",
        "status": "VERIFIED",
        "verified_by": ["C0", "DP5", "DP6", "C4"],
    }


def temporal_correction_record(correction_claim: dict[str, Any]) -> dict[str, Any]:
    return record(
        TEMPORAL_CORRECTION_ID,
        "COUNCIL_TEMPORAL_TEST_DETERMINISM_DECISION",
        TEMPORAL_CORRECTION_GENERATED_AT,
        (
            "Separate deterministic frozen-contract validation from the live "
            "Council expiration decision without changing the expired authority."
        ),
        [
            "A historical contract test must not change result with calendar time.",
            "Any live preflight or execution must still fail at or after expires_at.",
            "No Council, R2, Neon, PostgreSQL or provider authority is renewed.",
        ],
        [correction_claim["claim_id"]],
        (
            "PASS_BOUNDED_CORRECTION. Add a non-authorizing frozen-contract "
            "validator and preserve validate_manifest as the live fail-closed "
            "entrypoint; authorize one non-force PR46 publication cycle for this "
            "independent failure taxonomy."
        ),
        {
            **common_context(),
            "pull_request": 46,
            "old_ci_run_id": 31462358073,
            "old_head_sha": "eba31bf562d41d45bebda46fc831e308a8668566",
            "failure_taxonomy": "GOVERNANCE_TEST_TIME_DEPENDENCE",
            "root_cause": "FROZEN_GOVERNANCE_TEST_DEPENDS_ON_WALL_CLOCK",
            "correction_report": TEMPORAL_CORRECTION_REPORT,
            "worktree": "WORKTREE:chronos-cleanroom-portable-integration-v1",
            "branch": "codex/chronos-cleanroom-portable-integration-v1",
            "head": "eba31bf562d41d45bebda46fc831e308a8668566",
            "writer": "C0_DESIGNATED_ROOT",
            "files": [
                "reports/council/decision-ledger.jsonl",
                "reports/evidence/evidence-graph.json",
                TEMPORAL_CORRECTION_REPORT,
                "scripts/record_chronos_cleanroom_evidence.py",
                "src/robin/governance/capability_launch_preflight.py",
                "tests/portability/test_chronos_cleanroom_evidence_recorder.py",
                "tests/preflight/test_p0_capability_launch_readiness_v1.py",
            ],
            "expired_authority_modified": False,
            "new_authority_granted": False,
            "r2_authority_renewed": False,
            "live_expiration_guard_weakened": False,
            "live_council_expiry_guard": "PRESERVED",
            "targeted_tests": {
                "preflight": "38 passed",
                "governance_activation_and_recorder": "108 passed",
            },
            "reused_evidence": [
                "GitHub Actions run 31462358073",
                "PR46 old head eba31bf562d41d45bebda46fc831e308a8668566",
                "Council blob SHA-256 e700d754a853de1a7b39e5edd76e759c1acca711992ef1712848eda6bfd51ad4",
            ],
            "reviews": {
                "DP5": {"roles": ["PLATFORM", "SRE"], "score": 99},
                "DP6": {"roles": ["EVIDENCE", "DBA"], "score": 99},
                "C4": {"roles": ["SEC", "RED"], "score": 99},
            },
            "call_site_audit": {
                "contract_validator_non_test_imports": 0,
                "live_validator_requires_expiry_guard": True,
            },
            "next_ci_run_binding": "AUTOMATIC_PR46_EXACT_HEAD_RUN",
            "p0": 0,
            "p1": 0,
        },
        PORTABILITY_CORRECTION_TIP_HASH,
    )


def verify_temporal_correction_final(
    records: list[dict[str, Any]], graph: dict[str, Any]
) -> None:
    verify_final(records, graph)
    verify_graph_shape(records, graph)
    correction_claim = temporal_correction_claim()
    correction_record = temporal_correction_record(correction_claim)
    expected_node = {
        "decision_id": TEMPORAL_CORRECTION_ID,
        "ledger_record_hash": TEMPORAL_CORRECTION_TIP_HASH,
    }
    expected_edge = {
        "edge_id": "EDGE.299",
        "from_claim_id": TEMPORAL_CORRECTION_CLAIM_ID,
        "to_decision_id": TEMPORAL_CORRECTION_ID,
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    if file_sha256(TEMPORAL_CORRECTION_REPORT) != TEMPORAL_CORRECTION_REPORT_SHA256:
        raise SystemExit("COUNCIL_TEMPORAL_CORRECTION_REPORT_HASH_INVALID")
    if (
        len(records) != 112
        or len(graph["claims"]) != 128
        or len(graph["decision_nodes"]) != 112
        or len(graph["edges"]) != 299
        or records[-2]["hash"] != PORTABILITY_CORRECTION_TIP_HASH
        or records[-1] != correction_record
        or records[-1]["hash"] != TEMPORAL_CORRECTION_TIP_HASH
        or graph["claims"][-1] != correction_claim
        or graph["decision_nodes"][-1] != expected_node
        or graph["edges"][-1] != expected_edge
        or graph.get("generated_at") != TEMPORAL_CORRECTION_GENERATED_AT
    ):
        raise SystemExit("COUNCIL_TEMPORAL_CORRECTION_FINAL_STATE_INVALID")


def append_temporal_correction(
    original_ledger: str,
    records: list[dict[str, Any]],
    graph: dict[str, Any],
) -> None:
    verify_portability_correction_final(records, graph)
    correction_claim = temporal_correction_claim()
    correction_record = temporal_correction_record(correction_claim)
    records.append(correction_record)
    graph["generated_at"] = TEMPORAL_CORRECTION_GENERATED_AT
    graph["claims"].append(correction_claim)
    graph["decision_nodes"].append(
        {
            "decision_id": correction_record["decision_id"],
            "ledger_record_hash": correction_record["hash"],
        }
    )
    graph["edges"].append(
        {
            "edge_id": "EDGE.299",
            "from_claim_id": correction_claim["claim_id"],
            "to_decision_id": correction_record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
    )
    separator = "" if original_ledger.endswith("\n") else "\n"
    appended = json.dumps(
        correction_record, ensure_ascii=False, separators=(",", ":")
    ) + "\n"
    LEDGER.write_text(
        original_ledger + separator + appended,
        encoding="utf-8",
        newline="\n",
    )
    GRAPH.write_text(compact_json(graph) + "\n", encoding="utf-8", newline="\n")
    verify_temporal_correction_final(records, graph)


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
    if records[-1]["decision_id"] == TEMPORAL_CORRECTION_ID:
        verify_temporal_correction_final(records, graph)
        print("COUNCIL_TEMPORAL_CORRECTION_VERIFIED")
        return
    if records[-1]["decision_id"] == PORTABILITY_CORRECTION_ID:
        append_temporal_correction(original_ledger, records, graph)
        print("COUNCIL_TEMPORAL_CORRECTION_RECORDED")
        return
    if records[-1]["decision_id"] == CI1_CORRECTION_ID:
        append_portability_correction(original_ledger, records, graph)
        print("CHRONOS_CLEANROOM_PORTABILITY_CORRECTION_RECORDED")
        return
    if records[-1]["decision_id"] == CORRECTION_ID:
        append_ci1_correction(original_ledger, records, graph)
        print("CHRONOS_CLEANROOM_CI1_CORRECTION_RECORDED")
        return
    if records[-1]["decision_id"] == NEW_IDS[-1]:
        append_full_suite_correction(original_ledger, records, graph)
        print("CHRONOS_CLEANROOM_CORRECTION_RECORDED")
        return
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
