from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

from scripts import run_phase_c_v2_campaign as campaign

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "reports/hypothesis-research/v2"


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_exact_atomic_pair_and_campaign_denominators() -> None:
    atomic = read_json(REPORT_ROOT / "atomic-results-summary-v2.json")
    pairs = read_json(REPORT_ROOT / "pair-results-summary-v2.json")
    multiplicity = read_json(REPORT_ROOT / "campaign-multiplicity-v2.json")
    assert atomic["tag_count"] == 150
    assert atomic["property_count"] == 16
    assert atomic["canonical_test_count"] == 300
    assert sum(atomic["status_counts"].values()) == 150  # type: ignore[union-attr]
    assert pairs["pair_count"] == 3_590
    assert pairs["canonical_test_count"] == 7_180
    assert pairs["campaign_test_count"] == 7_480
    assert sum(pairs["status_counts"].values()) == 3_590  # type: ignore[union-attr]
    assert pairs["surviving_test_count"] == 0
    assert multiplicity["atomic_test_count"] == 300
    assert multiplicity["pair_test_count"] == 7_180
    assert multiplicity["campaign_test_count"] == 7_480


def test_no_pair_survivor_keeps_triples_locked() -> None:
    multiplicity = read_json(REPORT_ROOT / "campaign-multiplicity-v2.json")
    assert multiplicity["surviving_pair_test_count"] == 0
    assert multiplicity["triple_search_locked"] is True
    assert (
        multiplicity["triple_verdict"]
        == "TRIPLE_SEARCH_REMAINS_LOCKED_NO_PAIR_SURVIVOR"
    )
    pair_summary = read_json(REPORT_ROOT / "pair-results-summary-v2.json")
    assert pair_summary["triple_search_locked"] is True
    assert pair_summary["roi"] is None
    assert pair_summary["profit"] is None
    assert pair_summary["clv"] is None
    assert pair_summary["drawdown"] is None


def test_all_eight_negative_controls_execute_and_none_survive() -> None:
    controls = read_json(REPORT_ROOT / "negative-controls-v2.json")
    assert controls["control_count"] == 8
    assert controls["guard_control_count"] == 4
    assert controls["modeled_control_count"] == 4
    assert controls["modeled_track_target_test_count"] == 16
    assert controls["surviving_control_count"] == 0
    assert controls["negative_control_gate"] == "PASS"
    assert len(controls["guard_records"]) == 4  # type: ignore[arg-type]
    modeled = controls["modeled_records"]
    assert isinstance(modeled, list)
    assert len(modeled) == 16
    assert {row["track"] for row in modeled} == {"ATOMIC", "PAIR"}
    assert {row["execution"] for row in modeled} == {"MODELED_FIVE_FOLD_OOF"}
    assert {row["status"] for row in modeled} == {"REJECTED"}


def test_full_result_shards_are_git_durable_small_and_exact_union() -> None:
    manifest = campaign.verify_results(ROOT)
    assert manifest["durability"] == "GIT_FULL_SANITIZED_EVIDENCE"
    assert manifest["atomic_shard_count"] == 16
    assert manifest["pair_shard_count"] == 64
    assert manifest["eligible_pair_count"] == 3_590
    gzip_files = [row for row in manifest["files"] if row["path"].endswith(".gz")]
    assert len(gzip_files) == 80
    assert max(int(row["bytes"]) for row in gzip_files) < 300_000


def test_full_result_content_hash_tamper_is_rejected(tmp_path: Path) -> None:
    copied_root = tmp_path / "copy"
    shutil.copytree(REPORT_ROOT, copied_root / "reports/hypothesis-research/v2")
    manifest_path = copied_root / "reports/hypothesis-research/v2/full-results-manifest-v2.json"
    manifest = read_json(manifest_path)
    gzip_record = next(row for row in manifest["files"] if row["path"].endswith(".gz"))  # type: ignore[union-attr]
    gzip_record["content_sha256"] = "0" * 64
    manifest["manifest_hash"] = campaign.v2.object_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    manifest_path.write_bytes(campaign.v2.canonical_bytes(manifest) + b"\n")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_RESULT_CONTENT_MISMATCH"):
        campaign.verify_results(copied_root)


def test_full_result_campaign_lineage_tamper_is_rejected(tmp_path: Path) -> None:
    copied_root = tmp_path / "copy"
    shutil.copytree(REPORT_ROOT, copied_root / "reports/hypothesis-research/v2")
    manifest_path = copied_root / "reports/hypothesis-research/v2/full-results-manifest-v2.json"
    manifest = read_json(manifest_path)
    manifest["campaign_hash"] = "0" * 64
    manifest["manifest_hash"] = campaign.v2.object_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    manifest_path.write_bytes(campaign.v2.canonical_bytes(manifest) + b"\n")
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_RESULT_CAMPAIGN_LINEAGE_MISMATCH"
    ):
        campaign.verify_results(copied_root)


def test_replay_two_fresh_campaigns_and_reducers_is_byte_identical() -> None:
    replay = campaign.verify_replay_manifest()
    assert replay["fresh_campaign_runs"] == 2
    assert replay["fresh_reducers"] == 2
    assert replay["result_file_count"] == 86
    assert replay["byte_identical_a_b_git"] is True
    assert replay["source_bundle_replay_runs"] == 2
    assert replay["source_bundle_replay_identical"] is True
    assert replay["additional_network_reads"] == 0
    assert replay["fresh_directory_contract"] == {
        "work_root_count": 2,
        "output_root_count": 2,
        "all_four_roots_resolved_disjoint": True,
        "all_four_roots_empty_before_run": True,
    }
    receipts = replay["fresh_run_receipts"]
    assert [row["run_label"] for row in receipts] == ["A", "B"]
    assert all(
        shard["resumed_from"] == shard["recomputed_prefix_count"] == 0
        for receipt in receipts
        for shard in receipt["shards"]
    )


def test_cursor_17_resume_equals_clean_without_prefix_recompute() -> None:
    receipt = campaign.verify_checkpoint_receipt()
    assert receipt["forced_interrupt_cursor"] == 17
    assert receipt["resumed_from"] == 17
    assert receipt["recomputed_prefix_count"] == 0
    assert receipt["prefix_17_preserved"] is True
    assert receipt["resume_equals_clean"] is True
    assert receipt["clean_results_hash"] == receipt["resumed_results_hash"]
    assert receipt["completed_shard_skip_verified"] is True


def test_replay_self_hash_and_freshness_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "campaign-replay-v2.json"
    replay = read_json(REPORT_ROOT / "campaign-replay-v2.json")
    replay["fresh_directory_contract"]["all_four_roots_empty_before_run"] = False
    replay["replay_hash"] = campaign.v2.object_hash(
        {key: value for key, value in replay.items() if key != "replay_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(replay) + b"\n")
    monkeypatch.setattr(campaign, "CAMPAIGN_REPLAY", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_REPLAY_FRESH_DIRECTORY_CONTRACT_MISMATCH"
    ):
        campaign.verify_replay_manifest()


def test_replay_rehashed_a_b_shard_and_effect_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "campaign-replay-v2.json"
    replay = read_json(REPORT_ROOT / "campaign-replay-v2.json")
    receipt_a = replay["fresh_run_receipts"][0]
    receipt_a["shards"][0]["pair_count"] = 999
    receipt_a["shards"][0]["results_hash"] = "5" * 64
    receipt_a["receipt_hash"] = campaign.v2.object_hash(
        {key: value for key, value in receipt_a.items() if key != "receipt_hash"}
    )
    replay["additional_network_reads"] = 9
    replay["external_effects"]["provider_calls"] = 9
    replay["replay_hash"] = campaign.v2.object_hash(
        {key: value for key, value in replay.items() if key != "replay_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(replay) + b"\n")
    monkeypatch.setattr(campaign, "CAMPAIGN_REPLAY", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_FRESH_RUN_RECEIPT_LINEAGE_MISMATCH"
    ):
        campaign.verify_replay_manifest()


def test_resume_receipt_rehashed_lineage_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "checkpoint-resume-receipt-v2.json"
    receipt = read_json(REPORT_ROOT / "checkpoint-resume-receipt-v2.json")
    receipt["campaign_hash"] = "4" * 64
    receipt["receipt_hash"] = campaign.v2.object_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(receipt) + b"\n")
    monkeypatch.setattr(campaign, "CHECKPOINT_RECEIPT", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_RESUME_RECEIPT_LINEAGE_MISMATCH"
    ):
        campaign.verify_checkpoint_receipt()


def test_resume_receipt_rehashed_counts_hashes_and_effects_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "checkpoint-resume-receipt-v2.json"
    receipt = read_json(REPORT_ROOT / "checkpoint-resume-receipt-v2.json")
    receipt["shard_pair_count"] = 999
    receipt["interrupted_checkpoint_hash"] = "not-a-hash"
    receipt["external_effects"]["provider_calls"] = 9
    receipt["receipt_hash"] = campaign.v2.object_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(receipt) + b"\n")
    monkeypatch.setattr(campaign, "CHECKPOINT_RECEIPT", copied)
    with pytest.raises(RuntimeError, match="PHASE_C_V2_RESUME_RECEIPT_INVALID_HASH"):
        campaign.verify_checkpoint_receipt()


def test_resume_receipt_rehashed_clean_result_cross_link_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "checkpoint-resume-receipt-v2.json"
    receipt = read_json(REPORT_ROOT / "checkpoint-resume-receipt-v2.json")
    receipt["clean_results_hash"] = "6" * 64
    receipt["resumed_results_hash"] = "6" * 64
    receipt["receipt_hash"] = campaign.v2.object_hash(
        {key: value for key, value in receipt.items() if key != "receipt_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(receipt) + b"\n")
    monkeypatch.setattr(campaign, "CHECKPOINT_RECEIPT", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_RESUME_RECEIPT_LINEAGE_MISMATCH"
    ):
        campaign.verify_checkpoint_receipt()


def test_replay_roots_must_be_fresh_and_disjoint(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("a", "b", "c", "d")]
    campaign.require_disjoint_replay_roots(roots)
    for index, root in enumerate(roots):
        assert campaign.require_fresh_directory(root, str(index)) == root.resolve()
    (roots[0] / "existing").write_text("checkpoint", encoding="utf-8")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_REPLAY_ROOT_NOT_FRESH"):
        campaign.require_fresh_directory(roots[0], "A")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_REPLAY_ROOTS_NOT_DISTINCT"):
        campaign.require_disjoint_replay_roots([roots[0], roots[0]])


def test_checkpoint_tamper_is_fail_closed(tmp_path: Path) -> None:
    pairs = campaign.eligible_pairs_for_shard(0)
    pair_ids = [str(row["pair_id"]) for row in pairs]
    rows = [
        {"pair_id": pair_ids[0], "value": 1},
        {"pair_id": pair_ids[1], "value": 2},
    ]
    progress = tmp_path / "progress-v2.jsonl"
    checkpoint = tmp_path / "checkpoint-v2.json"
    for row in rows:
        campaign.append_jsonl(progress, row)
    campaign.write_checkpoint(
        checkpoint,
        shard_id=0,
        pair_ids=pair_ids,
        completed_rows=rows,
        previous_checkpoint_hash=None,
        complete=False,
    )
    tampered = rows.copy()
    tampered[0] = {"pair_id": pair_ids[1], "value": 1}
    progress.write_bytes(
        b"".join(campaign.v2.canonical_bytes(row) + b"\n" for row in tampered)
    )
    with pytest.raises(RuntimeError, match="PHASE_C_V2_RESUME_LINEAGE_MISMATCH"):
        campaign.validate_resume_checkpoint(checkpoint, progress, 0, pair_ids)


def test_dashboard_is_data_only_and_forbids_betting_outputs() -> None:
    dashboard = read_json(REPORT_ROOT / "dashboard-data-contract-v2.json")
    assert dashboard["data_only"] is True
    assert dashboard["point_in_time_price_provenance"] is False
    assert dashboard["triple_search_locked"] is True
    assert {"roi", "profit", "clv", "drawdown", "bet", "odds"}.issubset(
        set(dashboard["forbidden_fields"])  # type: ignore[arg-type]
    )


def test_every_gzip_descriptor_matches_decompressed_content() -> None:
    manifest = read_json(REPORT_ROOT / "full-results-manifest-v2.json")
    for descriptor in manifest["files"]:  # type: ignore[union-attr]
        if not descriptor["path"].endswith(".gz"):
            continue
        path = ROOT / descriptor["path"]
        with gzip.open(path, "rb") as stream:
            content = stream.read()
        assert campaign.hashlib.sha256(content).hexdigest() == descriptor["content_sha256"]


def test_closure_report_has_explicit_effect_counters_and_final_verdicts() -> None:
    closure = campaign.verify_closure_report()
    effects = closure["deployments_and_publications"]
    assert isinstance(effects, dict)
    assert effects["automatic_repository_pages_deployments_observed"] == 1
    assert effects["mission_initiated_deployments"] == 0
    assert effects["phase_c_workflow_deployments"] == 0
    assert effects["manual_pages_dispatches"] == 0
    assert effects["forbidden_data_publications"] == 0
    assert effects["heavy_phase_c_evidence_publications"] == 0
    assert effects["provider_payload_publications"] == 0
    assert effects["secret_publications"] == 0
    assert closure["properties"]["candidate_property_count"] == 25  # type: ignore[index]
    assert closure["properties"]["selected_property_count"] == 16  # type: ignore[index]
    assert closure["properties"]["blocked_candidate_count"] == 9  # type: ignore[index]
    assert closure["verdicts"] == [
        "AUTOMATIC_GITHUB_PAGES_SIDE_EFFECT_RECLASSIFIED",
        "PUBLICATION_EXPOSURE_AUDIT_PASSED",
        "PHASE_C_V2_RESUMED_AFTER_NON_BLOCKING_SIDE_EFFECT",
        "PHASE_C_FULL_BOUNDED_EXPANSION_READY",
        "TRIPLE_SEARCH_REMAINS_LOCKED_NO_PAIR_SURVIVOR",
    ]


def test_closure_rehashed_roi_triple_and_cost_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "phase-c-v2-full-bounded-expansion-closure-v1.json"
    closure = read_json(
        ROOT / "reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json"
    )
    closure["prices_and_bets"]["roi"] = 123
    closure["security"]["triple_search_executed"] = True
    closure["security"]["max_depth"] = 3
    closure["costs"]["provider_calls"] = 9
    closure["report_hash"] = campaign.v2.object_hash(
        {key: value for key, value in closure.items() if key != "report_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(closure) + b"\n")
    monkeypatch.setattr(campaign, "CLOSURE_REPORT", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_CLOSURE_SAFETY_CONTRACT_MISMATCH"
    ):
        campaign.verify_closure_report()


def test_closure_rehashed_duplicate_effect_counter_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "phase-c-v2-full-bounded-expansion-closure-v1.json"
    closure = read_json(
        ROOT / "reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json"
    )
    closure["deployments_and_publications"]["provider_calls"] = 9
    closure["report_hash"] = campaign.v2.object_hash(
        {key: value for key, value in closure.items() if key != "report_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(closure) + b"\n")
    monkeypatch.setattr(campaign, "CLOSURE_REPORT", copied)
    with pytest.raises(
        RuntimeError, match="PHASE_C_V2_CLOSURE_EFFECT_ACCOUNTING_MISMATCH"
    ):
        campaign.verify_closure_report()


def test_closure_rehashed_unlisted_semantic_tamper_is_rejected_by_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "phase-c-v2-full-bounded-expansion-closure-v1.json"
    closure = read_json(
        ROOT / "reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json"
    )
    closure["properties"]["difference_from_up_to_25_explained"] = "TAMPERED"
    closure["report_hash"] = campaign.v2.object_hash(
        {key: value for key, value in closure.items() if key != "report_hash"}
    )
    copied.write_bytes(campaign.v2.canonical_bytes(closure) + b"\n")
    monkeypatch.setattr(campaign, "CLOSURE_REPORT", copied)
    with pytest.raises(RuntimeError, match="PHASE_C_V2_CLOSURE_REBUILD_MISMATCH"):
        campaign.verify_closure_report()
