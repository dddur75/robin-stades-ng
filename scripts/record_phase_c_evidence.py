"""Record the independently reviewed, bounded Phase C evidence claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
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
DRAFT_PUBLICATION_DECISION_ID = "RCV3-20260808-080"
AUTHORITY_SCOPE_DECISION_ID = "RCV3-20260808-081"
CLOSURE_AUDIT_DECISION_ID = "RCV3-20260808-082"
CLOSURE_RUNTIME_CORRECTION_DECISION_ID = "RCV3-20260808-083"
CLOSURE_SANITIZATION_DECISION_ID = "RCV3-20260808-084"
MAIN_INTEGRATION_DECISION_ID = "RCV3-20260808-085"
MAIN_MERGE_RECEIPT_DECISION_ID = "RCV3-20260808-086"
TEST_PORTABILITY_DECISION_ID = "RCV3-20260808-087"
DELIVERY_DECISION_ID = "RCV3-20260808-088"
PAGES_RECLASSIFICATION_DECISION_ID = "RCV3-20260808-089"
V2_FREEZE_COMMIT_DECISION_ID = "RCV3-20260808-090"
V2_EXACT_COMMIT_REVIEW_DECISION_ID = "RCV3-20260808-091"
PR38_CLOSURE_DECISION_ID = "RCV3-20260809-092"
GENERATED_AT = "2026-08-09T05:22:39Z"
V2_CODE_REVISION = "a8a2bba20abcb8dbe320519b95e6cf5737a8b1d9"
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
    portable = PurePosixPath(relative)
    if portable.is_absolute() or ".." in portable.parts or "\\" in relative:
        raise ValueError(f"PHASE_C_ARTIFACT_PATH_NOT_PORTABLE:{relative}")
    artifact = ROOT.joinpath(*portable.parts)
    payload = artifact.read_bytes()
    if artifact.suffix.casefold() in {".csv", ".json", ".jsonl", ".md", ".yaml", ".yml"}:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


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
        _claim(
            claim_id="GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            claim=(
                "At reviewed head 008396bad19885386bd7d17ab07c75ee79bb0a9e, "
                "PR37 contained 39 changed files and 2,230,743 changed Git blob bytes, "
                "with no blob larger than 298,597 bytes. The closure successor keeps "
                "all detailed V1 audit evidence and adds sanitized durable Git evidence "
                "instead of relying on temporary artifacts or further compaction."
            ),
            scope="PHASE_C_PR37_SIZE_RECONSTRUCTIBILITY_AND_ENGINE_CLOSURE_AUDIT",
            source="Git blobs, exact-head GitHub metadata and two fresh sealed-source replays",
            grain="one_pull_request_closure_audit",
            temporal_class="CODE_AND_REMOTE_STATE_AS_OF",
            artifact="reports/closure/pr37-size-evidence-and-reconstructibility-audit-v1.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5"],
            code_revision="008396bad19885386bd7d17ab07c75ee79bb0a9e",
            execution_id="local-phase-c-pr37-closure-20260808",
        ),
        _claim(
            claim_id="GOV.PHASE_C.PAGES.SIDE_EFFECT.V1.001",
            claim=(
                "The authorized PR37 merge triggered one repository-configured GitHub "
                "Pages deployment. The staging artifact contains no forbidden heavy Phase C "
                "evidence path, provider payload or demonstrated secret. It does publish the "
                "pre-existing bounded V1 scientific summary, recorded separately from "
                "mission-initiated publication and Phase C workflow deployments."
            ),
            scope="PR37_AUTOMATIC_REPOSITORY_PAGES_SIDE_EFFECT_RECLASSIFICATION",
            source="GitHub Pages run, deployment, artifact inventory and terminal main CI",
            grain="one_automatic_repository_pages_deployment",
            temporal_class="REMOTE_DELIVERY_STATE_AS_OF",
            artifact="reports/closure/automatic-pages-side-effect-reclassification-v1.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5"],
            code_revision="d4ce1836ef8f42f37e284126a7190ebf051f6dbf",
            execution_id="github-pages-run-31274388390",
        ),
        _claim(
            claim_id="DATA.PHASE_C.V2.SANITIZED_SOURCE_BUNDLE.V1.001",
            claim=(
                "The durable sanitized V2 source bundle deterministically represents "
                "286,075 locked source rows as 1,756 fixture ordinals and 3,512 team-fixture "
                "facts, with target labels physically separated and no provider identifier, "
                "raw payload, credential, URL or absolute path committed."
            ),
            scope="PHASE_C_V2_SANITIZED_LOCKED_SOURCE_BUNDLE",
            source="five exact attempt-1 E3 source artifacts and fail-closed exporter",
            grain="one_sanitized_fixture_or_team_fixture_fact",
            temporal_class="HISTORICAL_RECONSTRUCTED_ONLY",
            artifact="reports/closure/phase-c-v2-source-evidence/source-evidence-manifest-v2.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="FEATURE.PHASE_C.V2.PROPERTY_TAG_MASK_FREEZE.V1.001",
            claim=(
                "The label-blind V2 freeze selects 16 of 25 candidate properties and "
                "materializes 150 tri-state tag masks: all eighty V1 tags remain identical "
                "and seventy V2 tags are added under a historical-reconstruction ceiling; "
                "strict point-in-time provenance remains false."
            ),
            scope="PHASE_C_V2_16_PROPERTY_150_TAG_MASK_FREEZE",
            source="property contract, canonical registry, source-field registry and masks",
            grain="one_canonical_tri_state_tag_mask",
            temporal_class="HISTORICAL_RECONSTRUCTED_ONLY",
            artifact="reports/hypothesis-masks/atomic-mask-manifest-v2.json",
            status="PARTIAL",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="EVAL.PHASE_C.V2.FULL_BOUNDED_CAMPAIGN.V1.001",
            claim=(
                "The complete bounded V2 campaign evaluates 300 atomic tests and all 3,590 "
                "target-blind admissible tag pairs through 7,180 pair tests and 7,480 "
                "campaign-wide hypotheses. No pair survives campaign multiplicity, so no "
                "promotion, betting interpretation or triple search is authorized."
            ),
            scope="PHASE_C_V2_FULL_BOUNDED_ATOMIC_AND_PAIR_CAMPAIGN",
            source="full Git-sharded result manifest and campaign multiplicity reducer",
            grain="one_atomic_or_pair_target_test",
            temporal_class="FIVE_FOLD_HISTORICAL_RECONSTRUCTED_EVALUATION",
            artifact="reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json",
            status="PARTIAL",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="REPLAY.PHASE_C.V2.FRESH_DETERMINISM.V1.001",
            claim=(
                "Two disjoint fresh zero-egress campaign roots and two disjoint fresh reducer "
                "roots reproduce all 86 tracked V2 result files byte-for-byte; each of the "
                "64 pair shards starts from zero and recomputes no checkpoint prefix."
            ),
            scope="PHASE_C_V2_TWO_FRESH_CAMPAIGN_AND_REDUCER_REPLAY",
            source="code-bound fresh-run receipts and Git result hashes",
            grain="one_fresh_campaign_result_file_or_shard_receipt",
            temporal_class="CODE_AS_OF",
            artifact="reports/hypothesis-research/v2/campaign-replay-v2.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="REPLAY.PHASE_C.V2.CHECKPOINT_RESUME.V1.001",
            claim=(
                "The V2 checkpoint proof interrupts an exact pair shard at cursor 17, "
                "preserves the completed prefix, resumes without prefix recomputation and "
                "reproduces the clean shard output with fail-closed lineage cross-links."
            ),
            scope="PHASE_C_V2_CURSOR_17_CHECKPOINT_RESUME_PROOF",
            source="checkpoint, progress, fresh-run receipts and clean-versus-resumed hashes",
            grain="one_interrupted_and_resumed_v2_pair_shard",
            temporal_class="CODE_AS_OF",
            artifact="reports/hypothesis-research/v2/checkpoint-resume-receipt-v2.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="SECURITY.PHASE_C.V2.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
            claim=(
                "The bounded V2 construction and evaluation record zero provider, Odds, "
                "remote SQL and R2 effects, zero mission-initiated deployment, publication, "
                "real bet or promotion, and no triple execution. The separate historical "
                "automatic repository Pages deployment count remains one."
            ),
            scope="PHASE_C_V2_ZERO_EXTERNAL_EFFECTS_AND_TRIPLE_LOCK",
            source="closure effect accounting and independent security review",
            grain="one_complete_bounded_v2_campaign",
            temporal_class="CODE_AND_LOCAL_EXECUTION_AS_OF",
            artifact="reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json",
            status="VERIFIED",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
        _claim(
            claim_id="GOV.PHASE_C.V2.ACTIVATION.HOLD.V1.001",
            claim=(
                "Phase C V2 remains dormant after local completion: execution activation is "
                "HOLD with null allowed_execution_sha and empty stage locks. The exact commit "
                "may be published only to the existing draft PR for CI review; dispatch, "
                "Ready, merge and activation remain blocked."
            ),
            scope="PHASE_C_V2_DRAFT_PUBLICATION_AND_ACTIVATION_HOLD",
            source="activation contract, exact Git object and Council decision 091",
            grain="one_phase_c_v2_activation_and_delivery_state",
            temporal_class="CODE_AS_OF",
            artifact="configs/execution/phase-c-execution-activation-v1.json",
            status="BLOCKED",
            verified_by=["DP2", "DP5", "DP6"],
            code_revision=V2_CODE_REVISION,
            execution_id="local-phase-c-v2-bounded-a8a2bba2",
        ),
    ]


def main() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise TypeError("EVIDENCE_GRAPH_OBJECT_REQUIRED")
    existing_generated_at = graph.get("generated_at")
    if not isinstance(existing_generated_at, str):
        raise TypeError("EVIDENCE_GRAPH_GENERATED_AT_REQUIRED")
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
            DRAFT_PUBLICATION_DECISION_ID,
            AUTHORITY_SCOPE_DECISION_ID,
            CLOSURE_AUDIT_DECISION_ID,
            CLOSURE_RUNTIME_CORRECTION_DECISION_ID,
            CLOSURE_SANITIZATION_DECISION_ID,
            MAIN_INTEGRATION_DECISION_ID,
            MAIN_MERGE_RECEIPT_DECISION_ID,
            TEST_PORTABILITY_DECISION_ID,
            DELIVERY_DECISION_ID,
            PAGES_RECLASSIFICATION_DECISION_ID,
            V2_FREEZE_COMMIT_DECISION_ID,
            V2_EXACT_COMMIT_REVIEW_DECISION_ID,
            PR38_CLOSURE_DECISION_ID,
        }
    ]
    if recovery_ids != [
        RECOVERY_DECISION_ID,
        GRAPH_RECOVERY_DECISION_ID,
        PREFIX_ENFORCEMENT_DECISION_ID,
        DUPLICATE_GUARD_DECISION_ID,
        DRAFT_PUBLICATION_DECISION_ID,
        AUTHORITY_SCOPE_DECISION_ID,
        CLOSURE_AUDIT_DECISION_ID,
        CLOSURE_RUNTIME_CORRECTION_DECISION_ID,
        CLOSURE_SANITIZATION_DECISION_ID,
        MAIN_INTEGRATION_DECISION_ID,
        MAIN_MERGE_RECEIPT_DECISION_ID,
        TEST_PORTABILITY_DECISION_ID,
        DELIVERY_DECISION_ID,
        PAGES_RECLASSIFICATION_DECISION_ID,
        V2_FREEZE_COMMIT_DECISION_ID,
        V2_EXACT_COMMIT_REVIEW_DECISION_ID,
        PR38_CLOSURE_DECISION_ID,
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
        DRAFT_PUBLICATION_DECISION_ID,
        AUTHORITY_SCOPE_DECISION_ID,
        CLOSURE_AUDIT_DECISION_ID,
        CLOSURE_RUNTIME_CORRECTION_DECISION_ID,
        CLOSURE_SANITIZATION_DECISION_ID,
        MAIN_INTEGRATION_DECISION_ID,
        MAIN_MERGE_RECEIPT_DECISION_ID,
        TEST_PORTABILITY_DECISION_ID,
        DELIVERY_DECISION_ID,
        PAGES_RECLASSIFICATION_DECISION_ID,
        V2_FREEZE_COMMIT_DECISION_ID,
        V2_EXACT_COMMIT_REVIEW_DECISION_ID,
        PR38_CLOSURE_DECISION_ID,
    }
    if not decision_ids <= set(ledger_hashes):
        raise RuntimeError("PHASE_C_METADATA_DECISION_MISSING")
    claims = _claims()
    missing_correction_proof_claim_ids = [
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001",
        "EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001",
        "REPLAY.PHASE_C.DETERMINISM.V1.001",
        "SECURITY.PHASE_C.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
        "GOV.PHASE_C.ACTIVATION.HOLD.V1.001",
    ]
    expected_correction_tail_edges = [
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
    expected_closure_edges = [
        {
            "edge_id": "EDGE.260",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": CLOSURE_AUDIT_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.261",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": CLOSURE_RUNTIME_CORRECTION_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.262",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": CLOSURE_SANITIZATION_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.263",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": MAIN_INTEGRATION_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.264",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": MAIN_MERGE_RECEIPT_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.265",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": TEST_PORTABILITY_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.266",
            "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
            "to_decision_id": DELIVERY_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.267",
            "from_claim_id": "GOV.PHASE_C.PAGES.SIDE_EFFECT.V1.001",
            "to_decision_id": PAGES_RECLASSIFICATION_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
    ]
    v2_claim_ids = [
        "DATA.PHASE_C.V2.SANITIZED_SOURCE_BUNDLE.V1.001",
        "FEATURE.PHASE_C.V2.PROPERTY_TAG_MASK_FREEZE.V1.001",
        "EVAL.PHASE_C.V2.FULL_BOUNDED_CAMPAIGN.V1.001",
        "REPLAY.PHASE_C.V2.FRESH_DETERMINISM.V1.001",
        "REPLAY.PHASE_C.V2.CHECKPOINT_RESUME.V1.001",
        "SECURITY.PHASE_C.V2.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
        "GOV.PHASE_C.V2.ACTIVATION.HOLD.V1.001",
    ]
    expected_v2_edges = [
        {
            "edge_id": f"EDGE.{index:03d}",
            "from_claim_id": claim_id,
            "to_decision_id": V2_EXACT_COMMIT_REVIEW_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for index, claim_id in enumerate(v2_claim_ids, start=268)
    ]
    expected_tail_edges = (
        expected_correction_tail_edges + expected_closure_edges + expected_v2_edges
    )
    existing_tail_edges = graph["edges"][HISTORICAL_EDGE_COUNT:]
    allowed_incomplete_tails: tuple[list[Any], ...] = (
        [],
        expected_correction_tail_edges,
        expected_correction_tail_edges + expected_closure_edges[:1],
        expected_correction_tail_edges + expected_closure_edges[:2],
        expected_correction_tail_edges + expected_closure_edges[:3],
        expected_correction_tail_edges + expected_closure_edges[:4],
        expected_correction_tail_edges + expected_closure_edges[:5],
        expected_correction_tail_edges + expected_closure_edges[:6],
        expected_correction_tail_edges + expected_closure_edges[:7],
        expected_correction_tail_edges + expected_closure_edges,
        expected_tail_edges,
    )
    extension_edges: list[dict[str, object]] = []
    if existing_tail_edges in allowed_incomplete_tails:
        pass
    elif existing_tail_edges[: len(expected_tail_edges)] == expected_tail_edges:
        extension_edges = existing_tail_edges[len(expected_tail_edges) :]
        graph_claim_ids = {claim["claim_id"] for claim in graph["claims"]}
        first_extension_id = HISTORICAL_EDGE_COUNT + len(expected_tail_edges) + 1
        required_edge_fields = {
            "edge_id",
            "from_claim_id",
            "to_decision_id",
            "relation",
            "status",
        }
        for offset, edge in enumerate(extension_edges):
            if (
                not isinstance(edge, dict)
                or set(edge) != required_edge_fields
                or edge["edge_id"] != f"EDGE.{first_extension_id + offset:03d}"
                or edge["from_claim_id"] not in graph_claim_ids
                or edge["to_decision_id"] not in ledger_hashes
                or edge["relation"] != "SUPPORTS"
                or edge["status"] != "RECORDED"
            ):
                raise RuntimeError("PHASE_C_RECOVERY_EXTENSION_EDGE_INVALID")
    else:
        raise RuntimeError("PHASE_C_RECOVERY_EDGE_TAIL_MISMATCH")
    replacement_claims = {claim["claim_id"]: claim for claim in claims}
    seen_claim_ids: set[str] = set()
    preserved_claims: list[dict[str, Any]] = []
    for existing_claim in graph["claims"]:
        claim_id = existing_claim["claim_id"]
        if claim_id in replacement_claims:
            preserved_claims.append(replacement_claims[claim_id])
            seen_claim_ids.add(claim_id)
        else:
            preserved_claims.append(existing_claim)
    preserved_claims.extend(
        claim for claim in claims if claim["claim_id"] not in seen_claim_ids
    )
    graph["claims"] = preserved_claims

    phase_decision_ids = (
        ORIGINAL_DECISION_ID,
        CORRECTION_DECISION_ID,
        RECOVERY_DECISION_ID,
        GRAPH_RECOVERY_DECISION_ID,
        PREFIX_ENFORCEMENT_DECISION_ID,
        DUPLICATE_GUARD_DECISION_ID,
        DRAFT_PUBLICATION_DECISION_ID,
        AUTHORITY_SCOPE_DECISION_ID,
        CLOSURE_AUDIT_DECISION_ID,
        CLOSURE_RUNTIME_CORRECTION_DECISION_ID,
        CLOSURE_SANITIZATION_DECISION_ID,
        MAIN_INTEGRATION_DECISION_ID,
        MAIN_MERGE_RECEIPT_DECISION_ID,
        TEST_PORTABILITY_DECISION_ID,
        DELIVERY_DECISION_ID,
        PAGES_RECLASSIFICATION_DECISION_ID,
        V2_FREEZE_COMMIT_DECISION_ID,
        V2_EXACT_COMMIT_REVIEW_DECISION_ID,
        PR38_CLOSURE_DECISION_ID,
    )
    replacement_nodes = {
        decision_id: {
            "decision_id": decision_id,
            "ledger_record_hash": ledger_hashes[decision_id],
        }
        for decision_id in phase_decision_ids
    }
    seen_decision_ids: set[str] = set()
    preserved_nodes: list[dict[str, Any]] = []
    for existing_node in graph["decision_nodes"]:
        decision_id = existing_node["decision_id"]
        if decision_id in replacement_nodes:
            preserved_nodes.append(replacement_nodes[decision_id])
            seen_decision_ids.add(decision_id)
        else:
            preserved_nodes.append(existing_node)
    preserved_nodes.extend(
        replacement_nodes[decision_id]
        for decision_id in phase_decision_ids
        if decision_id not in seen_decision_ids
    )
    graph["decision_nodes"] = preserved_nodes
    graph["edges"] = historical_edges + expected_tail_edges + extension_edges
    graph["generated_at"] = existing_generated_at if extension_edges else GENERATED_AT
    GRAPH.write_text(_compact_json(graph) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
