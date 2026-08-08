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
DECISION_ID = "RCV3-20260808-074"
GENERATED_AT = "2026-08-08T13:25:00Z"
EXECUTION_ID = "local-phase-c-bounded-20260808-b2395964"
SCIENTIFIC_LINEAGE_ID = "hypothesis-tag-mask-pair-factory-v1-bounded"
DATASET_LINEAGE_ID = "PHASE_C_SOURCE_RUN_30853757779_ATTEMPT_1_INVENTORY_87326EBA"


def _file_hash(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


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
) -> dict[str, Any]:
    return {
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
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
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
            status="PARTIAL",
            verified_by=["DP6", "DP2"],
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
            status="VERIFIED",
            verified_by=["DP6", "DP2", "DP5"],
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
            verified_by=["DP6", "DP2", "DP5"],
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
            verified_by=["DP6", "DP2", "DP5"],
        ),
    ]


def main() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise TypeError("EVIDENCE_GRAPH_OBJECT_REQUIRED")
    records = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line
    ]
    ledger_hashes = {record["decision_id"]: record["hash"] for record in records}
    if DECISION_ID not in ledger_hashes:
        raise RuntimeError("PHASE_C_METADATA_DECISION_MISSING")
    claims = _claims()
    claim_ids = {claim["claim_id"] for claim in claims}
    relationships = [(claim["claim_id"], DECISION_ID) for claim in claims]
    edge_ids = {f"EDGE.{index:03d}" for index in range(241, 252)}
    graph["claims"] = [
        claim for claim in graph["claims"] if claim["claim_id"] not in claim_ids
    ]
    graph["claims"].extend(claims)
    graph["decision_nodes"] = [
        node for node in graph["decision_nodes"] if node["decision_id"] != DECISION_ID
    ]
    graph["decision_nodes"].append(
        {"decision_id": DECISION_ID, "ledger_record_hash": ledger_hashes[DECISION_ID]}
    )
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if edge["edge_id"] not in edge_ids and edge["from_claim_id"] not in claim_ids
    ]
    for index, (claim_id, decision_id) in enumerate(relationships, start=241):
        graph["edges"].append(
            {
                "edge_id": f"EDGE.{index:03d}",
                "from_claim_id": claim_id,
                "to_decision_id": decision_id,
                "relation": "SUPPORTS",
                "status": "RECORDED",
            }
        )
    graph["generated_at"] = GENERATED_AT
    GRAPH.write_text(_compact_json(graph) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
