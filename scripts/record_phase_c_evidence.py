"""Record the independently reviewed, bounded Phase C evidence claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "reports/evidence/evidence-graph.json"
LEDGER = ROOT / "reports/council/decision-ledger.jsonl"
IMPLEMENTATION_REVISION = "b2395964faf08a61ac45df36d547025a4b132e13"
ORIGINAL_DECISION_ID = "RCV3-20260808-074"
CORRECTION_DECISION_ID = "RCV3-20260808-075"
RECOVERY_DECISION_ID = "RCV3-20260808-076"
GRAPH_RECOVERY_DECISION_ID = "RCV3-20260808-077"
PREFIX_ENFORCEMENT_DECISION_ID = "RCV3-20260808-078"
DUPLICATE_GUARD_DECISION_ID = "RCV3-20260808-079"
GENERATED_AT = "2026-08-08T15:40:00Z"
EXECUTION_ID = "local-phase-c-bounded-20260808-b2395964"
SCIENTIFIC_LINEAGE_ID = "hypothesis-tag-mask-pair-factory-v1-bounded"
DATASET_LINEAGE_ID = "PHASE_C_SOURCE_RUN_30853757779_ATTEMPT_1_INVENTORY_87326EBA"
HISTORICAL_EDGE_COUNT = 254
HISTORICAL_EDGES_CANONICAL_SHA256 = (
    "ade7fac218879648d46d8c9bedec93ee7937326220ef4017ef65eb7d1de67fbb"
)
HISTORICAL_LEDGER_PREFIX_BYTES = 203_268
HISTORICAL_LEDGER_D034_SHA256 = (
    "8b7201434786aff66a0328c3f2a76ab18a1b525315d5bf61a65d21edb0d0470d"
)


def _file_hash(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compact_json(value: object, level: int = 0) -> str:
    if isinstance(value, dict):
        rows = [
            " " * (level + 2)
            + json.dumps(str(key), ensure_ascii=False)
            + ":"
            + _compact_json(item, level + 2)
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(rows) + "\n" + " " * level + "}"
    if isinstance(value, list):
        if not value or all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ",".join(_compact_json(item, level) for item in value) + "]"
        if all(
            isinstance(item, dict)
            and all(not isinstance(child, (dict, list)) for child in item.values())
            for item in value
        ):
            rows = [
                " " * (level + 2)
                + json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in value
            ]
            return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
        rows = [" " * (level + 2) + _compact_json(item, level + 2) for item in value]
        return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _claim(
    *,
    claim_id: str,
    claim: str,
    scope: str,
    source: str,
    grain: str,
    temporal_class: str,
    artifact: str,
    status: str,
    verified_by: list[str],
    **extra: Any,
) -> dict[str, Any]:
    row = {
        "claim_id": claim_id,
        "claim": claim,
        "scope": scope,
        "source": source,
        "grain": grain,
        "temporal_class": temporal_class,
        "artifact": artifact,
        "hash": _file_hash(artifact),
        "code_revision": IMPLEMENTATION_REVISION,
        "execution_id": EXECUTION_ID,
        "scientific_lineage_id": SCIENTIFIC_LINEAGE_ID,
        "dataset_lineage_id": DATASET_LINEAGE_ID,
        "status": status,
        "verified_by": verified_by,
    }
    row.update(extra)
    return row


def _claims() -> list[dict[str, Any]]:
    return [
        _claim(
            claim_id="DATA.PHASE_C.RAW_FIELD_CENSUS.V1.001",
            claim=(
                "The sanitized Phase C census covers 286,075 normalized rows, eleven "
                "entity types, 223 entity paths plus forty envelope paths and exactly "
                "1,756 scientific fixtures without committing raw values or fixture IDs."
            ),
            scope="PHASE_C_FIVE_LOCKED_2024_SEGMENTS_SANITIZED_CENSUS",
            source="five immutable attempt-1 E3 artifact segments",
            grain="one_entity_type_and_json_path_census_record",
            temporal_class="SOURCE_SNAPSHOT_AS_OF",
            artifact="reports/data-quality/raw-field-census-v1.json",
            status="VERIFIED",
            verified_by=["DP6", "DP2"],
        ),
        _claim(
            claim_id="FEATURE.PHASE_C.RECONCILIATION.V1.001",
            claim=(
                "The fail-closed reconciliation classifies all 486 Genome properties "
                "across 28 families as 46 READY, 46 PARTIAL, 344 BLOCKED and 50 UNKNOWN; "
                "the bounded campaign selects seven READY properties and explicitly "
                "defers eighteen other public-hypothesis-eligible properties."
            ),
            scope="PHASE_C_486_PROPERTY_RECONCILIATION_BOUNDED_SELECTION",
            source="exact property registry, source-field registry and E3 evidence",
            grain="one_canonical_property_id",
            temporal_class="MIXED_ROLE_FAIL_CLOSED",
            artifact="reports/hypothesis-genome/e3-property-reconciliation-v1.json",
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
        ),
        _claim(
            claim_id="FEATURE.PHASE_C.TAG_MASK_STORE.V1.001",
            claim=(
                "The bounded materialization builds eighty deterministic tag masks from "
                "seven selected properties over 1,756 fixtures, preserving TRUE, FALSE "
                "and UNKNOWN and exact definition, threshold and source lineage; durable "
                "remote mask storage is not claimed."
            ),
            scope="PHASE_C_80_TAG_MASKS_LOCAL_BOUNDED_STORE",
            source="canonical tag registry and deterministic mask-v1 payloads",
            grain="one_tag_mask_over_the_frozen_fixture_universe",
            temporal_class="PRIOR_FIXTURES_ONLY_OR_RECONSTRUCTED",
            artifact="reports/hypothesis-masks/atomic-mask-manifest-v1.json",
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
        ),
        _claim(
            claim_id="EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001",
            claim=(
                "The bounded atomic campaign executes 160 corrected tests over eighty "
                "tags with 78 raw survivors, one multiplicity survivor and one temporal "
                "survivor; all remain suspicious and no hypothesis is promoted."
            ),
            scope="PHASE_C_80_TAG_160_TEST_ATOMIC_CAMPAIGN",
            source="out-of-fold atomic evaluation with global and family corrections",
            grain="one_tag_target_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_EVALUATION",
            artifact="reports/hypothesis-research/atomic-results-v1.json",
            status="INVALIDATED",
            verified_by=["C0"],
            invalidation_reason=(
                "The claim mixed tag-level 78/1/1 counts with a tag-target-test grain and "
                "incorrectly described all tests as suspicious."
            ),
        ),
        _claim(
            claim_id="EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.002",
            claim=(
                "The bounded atomic campaign executes 160 corrected tag-target tests: "
                "158 raw historical signals, one multiplicity survivor and one temporal "
                "survivor. Only the two post-raw survivors require suspicious-edge review, "
                "and no hypothesis is promoted."
            ),
            scope="PHASE_C_80_TAG_160_TEST_ATOMIC_CAMPAIGN",
            source="out-of-fold atomic evaluation with global and family corrections",
            grain="one_tag_target_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_EVALUATION",
            artifact="reports/hypothesis-research/atomic-results-v1.json",
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
            successor_of="EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001",
        ),
        _claim(
            claim_id="EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001",
            claim=(
                "The bounded pair campaign represents all 21 selected-property pairs but "
                "executes only 120 of 1,398 structurally eligible tag pairs and 240 tests, "
                "yielding 45 raw survivors, 51 rejected and 24 deferred with zero final "
                "survivors; compatible-pair completeness is not claimed."
            ),
            scope="PHASE_C_120_OF_1398_TAG_PAIR_CAMPAIGN",
            source="eight deterministic pair shards and comparator-safe OOF evaluation",
            grain="one_canonical_tag_pair_target_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_EVALUATION",
            artifact="reports/hypothesis-research/pair-results-v1.json",
            status="INVALIDATED",
            verified_by=["C0"],
            invalidation_reason=(
                "The claim mixed pair-level 45/51/24 counts with a pair-target-test grain."
            ),
        ),
        _claim(
            claim_id="EVAL.PHASE_C.PAIR_CAMPAIGN.V1.002",
            claim=(
                "The bounded pair campaign represents all 21 selected-property pairs but "
                "executes only 120 of 1,398 structurally eligible tag pairs. Its 240 "
                "pair-target tests contain 50 raw historical signals, 142 rejected tests "
                "and 48 long-tail deferrals with zero final survivors; compatible-pair "
                "completeness is not claimed."
            ),
            scope="PHASE_C_120_OF_1398_TAG_PAIR_CAMPAIGN",
            source="eight deterministic pair shards and comparator-safe OOF evaluation",
            grain="one_canonical_tag_pair_target_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_EVALUATION",
            artifact="reports/hypothesis-research/pair-results-v1.json",
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
            successor_of="EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001",
        ),
        _claim(
            claim_id="CONTROL.PHASE_C.ATOMIC_NEGATIVE.V1.001",
            claim=(
                "Atomic negative controls execute the declared modeled and common-guard "
                "tracks with UNKNOWN preserved and no surviving control."
            ),
            scope="PHASE_C_ATOMIC_NEGATIVE_CONTROL_TRACK",
            source="modeled controls and fail-closed guards over the atomic folds",
            grain="one_negative_control_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_OR_FAIL_CLOSED_GUARD",
            artifact="reports/hypothesis-research/atomic-negative-controls-v1.json",
            status="VERIFIED",
            verified_by=["DP6", "DP2"],
        ),
        _claim(
            claim_id="CONTROL.PHASE_C.PAIR_NEGATIVE.V1.001",
            claim=(
                "Pair negative controls execute the declared modeled and common-guard "
                "tracks over 1,053 eligible observations with UNKNOWN preserved and no "
                "surviving control."
            ),
            scope="PHASE_C_PAIR_NEGATIVE_CONTROL_TRACK",
            source="modeled controls and fail-closed guards over the pair folds",
            grain="one_negative_control_test",
            temporal_class="FIVE_FOLD_PRIOR_ONLY_OR_FAIL_CLOSED_GUARD",
            artifact="reports/hypothesis-research/pair-negative-controls-v1.json",
            status="VERIFIED",
            verified_by=["DP6", "DP2"],
        ),
        _claim(
            claim_id="REPLAY.PHASE_C.DETERMINISM.V1.001",
            claim=(
                "Two fresh zero-effect Phase C builds reproduce all twenty tracked "
                "artifacts byte-for-byte, including the atomic and pair full gzip outputs."
            ),
            scope="PHASE_C_LOCAL_TWO_FRESH_BUILD_REPLAY",
            source="two fresh isolated local output and store roots",
            grain="one_tracked_phase_c_artifact",
            temporal_class="CODE_AS_OF",
            artifact="reports/hypothesis-research/campaign-replay-v1.json",
            status="INVALIDATED",
            verified_by=["C0"],
            invalidation_reason=(
                "The replay manifest tracks twenty Git artifacts but no gzip path; full "
                "gzip equality is separate evidence and was incorrectly included."
            ),
        ),
        _claim(
            claim_id="REPLAY.PHASE_C.DETERMINISM.V1.002",
            claim=(
                "Two fresh zero-effect Phase C builds reproduce all twenty Git-tracked "
                "artifacts byte-for-byte. Full gzip outputs are intentionally outside this "
                "claim and are bound separately by compact descriptors and the local "
                "checkpoint-resume proof."
            ),
            scope="PHASE_C_LOCAL_TWO_FRESH_BUILD_REPLAY",
            source="two fresh isolated local output roots",
            grain="one_git_tracked_phase_c_artifact",
            temporal_class="CODE_AS_OF",
            artifact="reports/hypothesis-research/campaign-replay-v1.json",
            status="VERIFIED",
            verified_by=["DP6", "DP2", "DP5"],
            successor_of="REPLAY.PHASE_C.DETERMINISM.V1.001",
        ),
        _claim(
            claim_id="EXECUTION.PHASE_C.CHECKPOINT_RESUME.V1.001",
            claim=(
                "A sanitized local zero-egress proof interrupts pair processing after "
                "cursor 17, resumes from the hash-bound checkpoint without recomputing "
                "the completed prefix and reproduces the clean compact and full outputs."
            ),
            scope="PHASE_C_LOCAL_CURSOR_17_RESUME_PROOF",
            source="code-bound checkpoint, progress snapshot and clean-versus-resumed hashes",
            grain="one_interrupted_and_resumed_pair_shard_execution",
            temporal_class="CODE_AS_OF",
            artifact="reports/hypothesis-research/checkpoint-resume-proof-v1.json",
            status="VERIFIED",
            verified_by=["DP6", "DP2", "DP5"],
        ),
        _claim(
            claim_id="SECURITY.PHASE_C.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
            claim=(
                "The bounded local campaign records zero provider, R2, SQL and Odds use, "
                "no deployment, publication, bet or promotion, and no triple execution; "
                "all Phase C workflows retain read-only permissions and network-isolated "
                "calculation steps."
            ),
            scope="PHASE_C_BOUNDED_LOCAL_EXTERNAL_EFFECTS_AND_DEPTH_LOCK",
            source="campaign cost report, workflow contracts and independent SRE review",
            grain="one_bounded_phase_c_campaign",
            temporal_class="CODE_AND_LOCAL_EXECUTION_AS_OF",
            artifact="reports/hypothesis-research/campaign-costs-v1.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5"],
        ),
        _claim(
            claim_id="GOV.PHASE_C.ACTIVATION.HOLD.V1.001",
            claim=(
                "Phase C remains dormant: allowed_execution_sha is null, stage locks are "
                "empty and no remote Phase C artifact exists; dispatch, activation, scale, "
                "merge and production-readiness claims remain blocked."
            ),
            scope="PHASE_C_DEFAULT_BRANCH_ACTIVATION_GATE",
            source="trusted-main activation and artifact-lock contracts",
            grain="one_phase_c_activation_state",
            temporal_class="CODE_AS_OF",
            artifact="configs/execution/phase-c-execution-activation-v1.json",
            status="BLOCKED",
            verified_by=["DP2", "DP5"],
        ),
    ]


def main() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise TypeError("EVIDENCE_GRAPH_OBJECT_REQUIRED")
    historical_edges = graph["edges"][:HISTORICAL_EDGE_COUNT]
    if (
        len(historical_edges) != HISTORICAL_EDGE_COUNT
        or _canonical_hash(historical_edges) != HISTORICAL_EDGES_CANONICAL_SHA256
    ):
        raise RuntimeError("PHASE_C_HISTORICAL_EDGE_PREFIX_MISMATCH")
    ledger_bytes = LEDGER.read_bytes()
    if (
        len(ledger_bytes) < HISTORICAL_LEDGER_PREFIX_BYTES
        or hashlib.sha256(
            ledger_bytes[:HISTORICAL_LEDGER_PREFIX_BYTES]
        ).hexdigest()
        != HISTORICAL_LEDGER_D034_SHA256
    ):
        raise RuntimeError("PHASE_C_HISTORICAL_LEDGER_PREFIX_MISMATCH")
    records = [
        json.loads(line)
        for line in ledger_bytes.decode("utf-8").splitlines()
        if line
    ]
    record_ids = [record["decision_id"] for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise RuntimeError("PHASE_C_DUPLICATE_DECISION_ID")
    recovery_ids = [
        record["decision_id"]
        for record in records
        if record["decision_id"]
        in {
            RECOVERY_DECISION_ID,
            GRAPH_RECOVERY_DECISION_ID,
            PREFIX_ENFORCEMENT_DECISION_ID,
            DUPLICATE_GUARD_DECISION_ID,
        }
    ]
    if recovery_ids != [
        RECOVERY_DECISION_ID,
        GRAPH_RECOVERY_DECISION_ID,
        PREFIX_ENFORCEMENT_DECISION_ID,
        DUPLICATE_GUARD_DECISION_ID,
    ]:
        raise RuntimeError("PHASE_C_RECOVERY_DECISION_SEQUENCE_MISMATCH")
    ledger_hashes = {record["decision_id"]: record["hash"] for record in records}
    decision_ids = {
        ORIGINAL_DECISION_ID,
        CORRECTION_DECISION_ID,
        RECOVERY_DECISION_ID,
        GRAPH_RECOVERY_DECISION_ID,
        PREFIX_ENFORCEMENT_DECISION_ID,
        DUPLICATE_GUARD_DECISION_ID,
    }
    if not decision_ids <= set(ledger_hashes):
        raise RuntimeError("PHASE_C_METADATA_DECISION_MISSING")
    claims = _claims()
    claim_ids = {claim["claim_id"] for claim in claims}
    missing_correction_proof_claim_ids = [
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001",
        "EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001",
        "REPLAY.PHASE_C.DETERMINISM.V1.001",
        "SECURITY.PHASE_C.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
        "GOV.PHASE_C.ACTIVATION.HOLD.V1.001",
    ]
    expected_tail_edges = [
        {
            "edge_id": f"EDGE.{index:03d}",
            "from_claim_id": claim_id,
            "to_decision_id": CORRECTION_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for index, claim_id in enumerate(
            missing_correction_proof_claim_ids, start=HISTORICAL_EDGE_COUNT + 1
        )
    ]
    existing_tail_edges = graph["edges"][HISTORICAL_EDGE_COUNT:]
    if existing_tail_edges not in ([], expected_tail_edges):
        raise RuntimeError("PHASE_C_RECOVERY_EDGE_TAIL_MISMATCH")
    graph["claims"] = [
        claim for claim in graph["claims"] if claim["claim_id"] not in claim_ids
    ]
    graph["claims"].extend(claims)
    graph["decision_nodes"] = [
        node
        for node in graph["decision_nodes"]
        if node["decision_id"] not in decision_ids
    ]
    for decision_id in (
        ORIGINAL_DECISION_ID,
        CORRECTION_DECISION_ID,
        RECOVERY_DECISION_ID,
        GRAPH_RECOVERY_DECISION_ID,
        PREFIX_ENFORCEMENT_DECISION_ID,
        DUPLICATE_GUARD_DECISION_ID,
    ):
        graph["decision_nodes"].append(
            {"decision_id": decision_id, "ledger_record_hash": ledger_hashes[decision_id]}
        )
    graph["edges"] = historical_edges + expected_tail_edges
    graph["generated_at"] = GENERATED_AT
    GRAPH.write_text(_compact_json(graph) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
