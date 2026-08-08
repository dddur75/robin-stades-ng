from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def test_raw_census_is_complete_and_contains_no_raw_values() -> None:
    report = load("reports/data-quality/raw-field-census-v1.json")
    assert report["normalized_row_count"] == 286_075
    assert report["scientific_fixture_count"] == 1_756
    assert report["entity_type_count"] == 11
    assert report["entity_path_count"] == 223
    assert report["row_envelope_path_count"] == 40
    assert report["scalar_path_count"] == 212
    assert report["array_path_count"] == 11
    assert report["always_null_data_path_count"] == 4
    assert report["partial_null_data_path_count"] == 74
    assert report["raw_values_in_git"] is False
    records = report["records"]
    assert isinstance(records, list) and len(records) == 263
    assert all("sample_hashes" in row and "sample_values" not in row for row in records)


def test_genome_486_by_28_reconciliation_is_fail_closed() -> None:
    report = load("reports/hypothesis-genome/e3-property-reconciliation-v1.json")
    assert report["genome_property_count"] == 486
    assert report["family_count"] == 28
    assert report["strict_materializable_count"] == 0
    assert report["baseline_bucket_counts"] == {
        "BLOCKED": 344,
        "PARTIAL": 46,
        "READY": 46,
        "UNKNOWN": 50,
    }
    counts = report["materialization_status_counts"]
    assert sum(counts.values()) == 486
    assert counts["MATERIALIZABLE_RECONSTRUCTED"] == 28
    assert counts["MATERIALIZABLE_TARGET_ONLY"] == 18
    assert report["point_in_time_source_provenance"] is False


def test_tag_registry_and_two_mask_manifest_are_canonical() -> None:
    registry = load("configs/hypothesis-tags/canonical-tag-registry-v1.json")
    assert registry["tag_count"] == 80
    tags = registry["tags"]
    ids = [row["tag_id"] for row in tags]
    assert ids == sorted(ids) and len(set(ids)) == 80
    assert registry["registry_hash"] == canonical_hash(tags)
    assert registry["strict_tag_count"] == 0

    manifest = load("reports/hypothesis-masks/atomic-mask-manifest-v1.json")
    assert manifest["mask_count"] == 80
    assert manifest["universe"]["fixture_count"] == 1_756
    assert manifest["format"]["known_then_true_bytes"] == 440
    assert manifest["format"]["tail_bits_zero"] is True
    assert manifest["store_durability"] == "MASK_STORE_DURABILITY_PARTIAL"
    for row in manifest["records"]:
        assert row["true_count"] <= row["known_count"] <= 1_756
        assert row["true_count"] + row["false_count"] + row["unknown_count"] == 1_756


def test_atomic_and_pair_denominators_are_frozen_and_bounded() -> None:
    config = load("configs/hypothesis-campaigns/atomic-property-campaign-v1.json")
    assert config["mode"] == "PREDICTIVE_ONLY"
    assert config["markets"] == [] and config["price_contracts"] == []
    assert config["multiple_testing_policy"]["atomic_denominator"] == 160
    assert config["multiple_testing_policy"]["pair_denominator"] == 240
    assert config["triple_search_locked"] is True

    atomic = load("reports/hypothesis-research/atomic-results-v1.json")
    assert atomic["atomic_property_count"] == 80
    assert atomic["canonical_test_count"] == 160
    assert atomic["point_in_time_source_provenance"] is False
    assert not {row["status"] for row in atomic["results"]} & {
        "VALIDATED",
        "PRODUCTION_READY",
        "REAL_BET",
    }
    for row in atomic["results"]:
        for metric in row["target_metrics"].values():
            assert metric["frequency_baseline_log_loss"] is not None
            assert metric["league_baseline_log_loss"] is not None
            assert metric["simple_log_loss"] is not None
            assert metric["review_gate"] in {"STANDARD_REVIEW", "SUSPICIOUS_EDGE_REVIEW"}

    space = load("reports/hypothesis-research/pair-search-space-v1.json")
    assert space["theoretical_pairs"] == 117_855
    assert space["compatible_pairs"] == 120
    assert space["pruned_pairs"] == 117_735
    assert space["quotas"] == {"AWAY_AWAY": 30, "CROSS_SIDE": 60, "HOME_HOME": 30}
    assert space["selection_is_target_blind"] is True
    pairs = load("reports/hypothesis-research/pair-results-v1.json")
    assert pairs["pair_count"] == 120
    assert pairs["canonical_test_count"] == 240
    assert not {row["status"] for row in pairs["results"]} & {
        "VALIDATED",
        "PRODUCTION_READY",
        "REAL_BET",
    }
    assert all(
        metric["review_gate"] in {"STANDARD_REVIEW", "SUSPICIOUS_EDGE_REVIEW"}
        for row in pairs["results"]
        for metric in row["target_metrics"].values()
    )


def test_negative_controls_and_triple_lock() -> None:
    for name in ("atomic", "pair"):
        report = load(f"reports/hypothesis-research/{name}-negative-controls-v1.json")
        assert report["control_count"] == 8
        assert report["negative_control_gate"] == "PASS"
        assert report["surviving_control_count"] == 0
        assert all(row["promoted"] is False for row in report["records"])
    triple = load("configs/hypothesis-campaigns/triple-campaign-lock-v1.json")
    assert triple["compiled"] is True
    assert triple["executed"] is False
    assert triple["status"] == "TRIPLE_SEARCH_LOCKED"
    assert triple["maximum_depth_executed"] == 2


def test_phase_c_workflows_are_manual_distinct_dormant_and_read_only() -> None:
    workflow_paths = sorted((ROOT / ".github/workflows").glob("8[6-9]-p0-phase-c-*.yml"))
    assert len(workflow_paths) == 4
    groups: set[str] = set()
    expected_pins = {
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    }
    for path in workflow_paths:
        raw = path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(raw)
        trigger = workflow.get("on", workflow.get(True))
        assert set(trigger) == {"workflow_dispatch"}
        assert workflow["permissions"] == {"contents": "read", "actions": "read"}
        assert workflow["concurrency"]["cancel-in-progress"] is False
        groups.add(workflow["concurrency"]["group"])
        assert "secrets." not in raw
        assert "schedule:" not in raw and "push:" not in raw and "pull_request:" not in raw
        assert 'TRIPLE_SEARCH_LOCKED: "true"' in raw
        assert all(job["timeout-minutes"] <= 15 for job in workflow["jobs"].values())
        uses = {
            step["uses"]
            for job in workflow["jobs"].values()
            for step in job["steps"]
            if "uses" in step
        }
        assert uses <= expected_pins
        assert any(item.startswith("actions/download-artifact@") for item in uses)
        assert any(item.startswith("actions/upload-artifact@") for item in uses)
    assert len(groups) == 4
    activation = load("configs/execution/phase-c-execution-activation-v1.json")
    assert activation["activation_status"] == "HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH"
    assert activation["allowed_execution_sha"] is None
    assert activation["triple_search_locked"] is True
    assert all(value == 0 for value in activation["external_effect_budgets"].values())
