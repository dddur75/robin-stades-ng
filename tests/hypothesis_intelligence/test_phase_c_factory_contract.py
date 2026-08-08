from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from scripts import export_phase_c_v1_durable_evidence, record_phase_c_evidence
from scripts import run_hypothesis_tag_mask_pair_factory as factory

ROOT = Path(__file__).resolve().parents[2]


def load(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def test_phase_c_v1_detailed_evidence_is_durable_and_sanitized(
    tmp_path: Path,
) -> None:
    evidence_root = ROOT / "reports/closure/phase-c-v1-durable-evidence"
    export_phase_c_v1_durable_evidence.verify(evidence_root)
    manifest = load(
        "reports/closure/phase-c-v1-durable-evidence/"
        "durable-evidence-manifest-v1.json"
    )
    assert manifest["raw_provider_rows_included"] is False
    assert manifest["raw_fixture_ids_included"] is False
    assert manifest["raw_provider_identifiers_included"] is False
    assert manifest["regenerated_gzip_python_runtime"]
    assert manifest["regenerated_gzip_zlib_compile_version"]
    assert manifest["regenerated_gzip_zlib_runtime_version"]
    assert manifest["regenerated_gzip_identity"] == (
        "canonical_uncompressed_content_sha256"
    )
    assert manifest["mask_count"] == 80
    assert manifest["structurally_eligible_tag_pairs"] == 1_398
    assert manifest["selected_tag_pairs"] == 120
    assert manifest["eligible_not_selected_tag_pairs"] == 1_278
    assert manifest["provider_calls"] == 0
    assert manifest["r2_operations"] == 0
    assert manifest["remote_sql_queries"] == 0
    assert manifest["odds_credits"] == 0
    assert manifest["triples_executed"] == 0
    regenerated = {
        "analysis-core-sanitized-v1.json.gz",
        "mask-payload-bundle-v1.json.gz",
        "eligible-tag-pair-census-v1.json.gz",
    }
    assert all(
        row["reconstruction_identity"] == "content_sha256"
        and row["transport_sha256_runtime_bound"] is True
        for row in manifest["files"]
        if row["path"] in regenerated
    )
    tampered_root = tmp_path / "durable-evidence"
    shutil.copytree(evidence_root, tampered_root)
    tampered_manifest_path = tampered_root / "durable-evidence-manifest-v1.json"
    tampered_manifest = json.loads(tampered_manifest_path.read_text(encoding="utf-8"))
    tampered_manifest["files"][0]["content_sha256"] = "0" * 64
    tampered_manifest_path.write_text(
        json.dumps(tampered_manifest, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="DURABLE_EVIDENCE_CONTENT_HASH_MISMATCH"):
        export_phase_c_v1_durable_evidence.verify(tampered_root)


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
    records = report["records"]
    reviewed = [
        row for row in records if row["reconciliation_bucket"] in {"READY", "PARTIAL"}
    ]
    assert len(reviewed) == 92
    assert all(row["source_fields"] and row["required_capabilities"] for row in reviewed)
    assert all(
        field in report["source_field_registry"]
        for row in reviewed
        for field in row["source_fields"]
    )
    assert all(
        {"entity_type", "json_path", "temporal_use", "transform_version"} <= set(definition)
        for definition in report["source_field_registry"].values()
    )
    unknown = {row["property_id"] for row in records if row["reconciliation_bucket"] == "UNKNOWN"}
    assert len(unknown) == 50
    assert "football:data_quality:identity_confidence" in unknown
    assert "football:strength_form:elo" in unknown
    assert report["campaign_scope_status"] == (
        "BOUNDED_7_PROPERTY_SUBCAMPAIGN_REQUIRES_COUNCIL_RESCOPING"
    )
    assert report["campaign_v1_disposition_counts"] == {
        "BLOCKED_SOURCE_OR_DATA": 344,
        "DEFERRED_PARTIAL_SOURCE": 46,
        "DEFERRED_PUBLIC_ELIGIBLE_NOT_TESTED_V1": 18,
        "DEFERRED_SEMANTIC_REVIEW": 50,
        "NON_PREDICTIVE_IDENTITY_QUALITY_OR_CONTEXT": 21,
        "SELECTED_PREDICTOR": 7,
    }
    assert len(report["omitted_public_hypothesis_eligible_property_ids"]) == 18
    dispositions = {row["property_id"]: row["campaign_v1_disposition"] for row in records}
    assert set(report["lagged_predictor_transform_property_ids"]) == {
        property_id
        for property_id, disposition in dispositions.items()
        if disposition == "SELECTED_PREDICTOR"
    }


def test_tag_registry_and_two_mask_manifest_are_canonical() -> None:
    registry = load("configs/hypothesis-tags/canonical-tag-registry-v1.json")
    assert registry["tag_count"] == 80
    tags = registry["tags"]
    ids = [row["tag_id"] for row in tags]
    assert ids == sorted(ids) and len(set(ids)) == 80
    assert registry["registry_hash"] == canonical_hash(tags)
    assert registry["strict_tag_count"] == 0
    assert all(row["feature_id"].startswith("feature:") for row in tags)
    assert all(row["source_fields"] and row["required_capabilities"] for row in tags)
    assert not any("FORMATION_CHANGE_RATE" in row["tag_id"] for row in tags)
    assert len({canonical_hash(row["source_fields"]) for row in tags}) >= 2
    discipline = [
        row
        for row in tags
        if row["property_id"] == "football:discipline_referee:recent_cards"
    ]
    assert discipline
    assert all(row["required_capabilities"] == ["EVENTS"] for row in discipline)
    source_registry = load(
        "reports/hypothesis-genome/e3-property-reconciliation-v1.json"
    )["source_field_registry"]
    assert all(
        {
            (
                source_registry[field_id]["entity_type"],
                source_registry[field_id]["json_path"],
                source_registry[field_id]["temporal_use"],
            )
            for field_id in row["source_fields"]
        }
        == {
            ("fixture_event", "data.team.id", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
            ("fixture_event", "data.type", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
        }
        for row in discipline
    )

    manifest = load("reports/hypothesis-masks/atomic-mask-manifest-v1.json")
    assert manifest["mask_count"] == 80
    assert manifest["universe"]["fixture_count"] == 1_756
    assert manifest["format"]["known_then_true_bytes"] == 440
    assert manifest["format"]["tail_bits_zero"] is True
    assert manifest["store_durability"] == "MASK_STORE_DURABILITY_PARTIAL"
    for row in manifest["records"]:
        assert row["true_count"] <= row["known_count"] <= 1_756
        assert row["true_count"] + row["false_count"] + row["unknown_count"] == 1_756
        assert row["definition_hash"]
        assert row["tag_snapshot_hash"]
        assert row["thresholds_by_competition"]


def test_atomic_and_pair_denominators_are_frozen_and_bounded() -> None:
    config = load("configs/hypothesis-campaigns/atomic-property-campaign-v1.json")
    assert config["mode"] == "PREDICTIVE_ONLY"
    assert config["markets"] == [] and config["price_contracts"] == []
    assert config["multiple_testing_policy"]["atomic_denominator"] == 160
    assert config["multiple_testing_policy"]["pair_denominator"] == 240
    assert config["triple_search_locked"] is True
    assert config["scope_contract"] == {
        "genome_properties_reconciled": 486,
        "ready_properties": 46,
        "selected_predictor_properties": 7,
        "deferred_public_hypothesis_eligible_properties": 18,
        "scope_status": "BOUNDED_SUBCAMPAIGN_PENDING_COUNCIL_RESCOPING",
    }

    atomic = load("reports/hypothesis-research/atomic-results-v1.json")
    atomic_summary = load("reports/hypothesis-research/atomic-campaign-summary-v1.json")
    assert atomic_summary["verdict"] == "ATOMIC_SUBCAMPAIGN_READY_GLOBAL_SCOPE_PARTIAL"
    assert atomic_summary["scope_verdict"] == (
        "BOUNDED_7_PROPERTY_SUBCAMPAIGN_COMPLETE_GLOBAL_SCOPE_PARTIAL"
    )
    assert atomic["atomic_tag_count"] == 80
    assert atomic["materialized_property_count"] == 7
    assert atomic["canonical_test_count"] == 160
    assert atomic["point_in_time_source_provenance"] is False
    assert atomic["result_detail"] == "COMPACT_GIT_SUMMARY_FULL_ROWS_IN_GITHUB_ARTIFACT"
    assert atomic["full_results_artifact"]["git_committed"] is False
    assert atomic["full_results_artifact"]["artifact_relative_path"].endswith(".json.gz")
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
            assert metric["q_value"] == max(
                metric["q_value_global"], metric["q_value_family"]
            )
            assert metric["hypothesis_id"].startswith("hypothesis:")
            if metric["status"].startswith("SURVIVED"):
                assert metric["delta_log_loss"] > 0
                assert metric["delta_brier"] > 0

    space = load("reports/hypothesis-research/pair-search-space-v1.json")
    assert space["theoretical_pairs"] == 117_855
    assert space["materialized_property_pairs"] == 21
    assert space["compatible_pairs"] == 21
    assert space["pruned_pairs"] == 117_834
    assert space["candidate_tag_pairs"] == 3_160
    assert space["structurally_eligible_tag_pairs"] == 1_398
    assert space["selected_tag_pairs"] == 120
    assert space["quotas"] == {"AWAY_AWAY": 30, "CROSS_SIDE": 60, "HOME_HOME": 30}
    assert space["selection_is_target_blind"] is True
    pairs = load("reports/hypothesis-research/pair-results-v1.json")
    assert pairs["pair_count"] == 120
    assert pairs["unique_property_pair_count"] == 21
    assert pairs["canonical_test_count"] == 240
    assert pairs["verdict"] == "PAIR_CAMPAIGN_PARTIAL"
    assert pairs["result_detail"] == "COMPACT_GIT_SUMMARY_FULL_ROWS_IN_GITHUB_ARTIFACT"
    assert pairs["full_results_artifact"]["git_committed"] is False
    assert pairs["full_results_artifact"]["artifact_relative_path"].endswith(".json.gz")
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
    assert all(row["parent_property_a"] != row["parent_property_b"] for row in pairs["results"])
    assert {row["shard_id"] for row in space["pairs"]} == set(range(8))
    for row in pairs["results"]:
        for metric in row["target_metrics"].values():
            assert "best_comparator_log_loss" not in metric
            assert set(metric["p_values_raw_by_comparator"]) == {
                "PARENT_A",
                "PARENT_B",
                "ADDITIVE",
            }
            assert metric["p_value_raw_intersection_union"] == max(
                metric["p_values_raw_by_comparator"].values()
            )
            assert metric["pair_snapshot_hash"]
            assert metric["hypothesis_id"] == "hypothesis:" + canonical_hash(
                {
                    "pair_id": row["pair_id"],
                    "parents": [row["parent_a"], row["parent_b"]],
                    "pair_snapshot_hash": metric["pair_snapshot_hash"],
                    "target_id": next(
                        target_id
                        for target_id, candidate in row["target_metrics"].items()
                        if candidate is metric
                    ),
                    "campaign": "PHASE-C-PAIR-120-X-2-2024-V1",
                }
            )

    assert (ROOT / "reports/hypothesis-genome/e3-property-reconciliation-v1.json").stat().st_size <= 300_000
    assert (ROOT / "reports/hypothesis-research/atomic-results-v1.json").stat().st_size <= 300_000
    assert (ROOT / "reports/hypothesis-research/pair-results-v1.json").stat().st_size <= 300_000


def test_negative_controls_and_triple_lock() -> None:
    for name in ("atomic", "pair"):
        report = load(f"reports/hypothesis-research/{name}-negative-controls-v1.json")
        assert report["control_count"] == 8
        assert report["negative_control_gate"] == "PASS"
        assert report["surviving_control_count"] == 0
        assert all(row["promoted"] is False for row in report["records"])
        assert report["modeled_control_count"] == 4
        assert report["admissibility_guard_control_count"] == 4
        assert all(
            row["folds"] or row["detector_result"] == "BLOCKED_AS_EXPECTED"
            for row in report["records"]
        )
        guards = [row for row in report["records"] if not row["folds"]]
        assert all(row["detector"] == "predictor_admissibility_reasons" for row in guards)
        assert all(row["detector_observation_count"] == 1_053 for row in guards)
        assert all(row["detector_blocked_count"] == 1_053 for row in guards)
        random_control = next(
            row
            for row in report["records"]
            if row["control_id"] == "RANDOM_FEATURE_MATCHED_PREVALENCE_UNKNOWN"
        )
        assert sum(fold["unknown_count"] for fold in random_control["folds"]) > 0
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
        assert "ref: main" in raw
        assert "trusted-main/scripts/validate_phase_c_workflow_contract.py" in raw
        assert "resume_run_id:" in raw and "resume_attempt:" in raw
        assert "timeout --signal=TERM" in raw
        assert "--soft-deadline-seconds" in raw
        assert "seal-stage" in raw
        assert "replay-stage" in raw
    assert len(groups) == 4
    pair_workflow = (ROOT / ".github/workflows/89-p0-phase-c-compatible-pair-search.yml").read_text()
    assert "shard: [0, 1, 2, 3, 4, 5, 6, 7]" in pair_workflow
    assert "max-parallel: 4" in pair_workflow
    assert "reduce-pair-shards" in pair_workflow
    assert "30853757779" not in (ROOT / ".github/workflows/88-p0-phase-c-atomic-property-search.yml").read_text()
    assert "30853757779" not in pair_workflow
    activation = load("configs/execution/phase-c-execution-activation-v1.json")
    assert activation["activation_status"] == "HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH"
    assert activation["allowed_execution_sha"] is None
    assert activation["triple_search_locked"] is True
    assert all(value == 0 for value in activation["external_effect_budgets"].values())
    assert activation["preflight_sha256"]
    assert activation["artifact_budgets_bytes"] == {
        "atomic_property_search_upload_max": 5_000_000,
        "compatible_pair_search_upload_max": 25_000_000,
        "derived_stage_download_max": 120_000_000,
        "pair_shard_upload_max": 2_000_000,
        "pair_shards_total_max": 16_000_000,
        "raw_field_census_upload_max": 5_000_000,
        "source_workflow_download_max": 120_000_000,
        "tag_mask_build_upload_max": 5_000_000,
    }
    assert activation["activation_authority"] == "TRUSTED_DEFAULT_BRANCH_ONLY_NEVER_CANDIDATE_CHECKOUT"
    assert activation["generator_sha256"] == hashlib.sha256(
        (ROOT / "scripts/run_hypothesis_tag_mask_pair_factory.py").read_bytes()
    ).hexdigest()
    assert activation["preflight_sha256"] == hashlib.sha256(
        (ROOT / "scripts/validate_phase_c_workflow_contract.py").read_bytes()
    ).hexdigest()
    assert activation["source_lock_sha256"] == hashlib.sha256(
        (ROOT / "configs/execution/p0-e3-artifact-lock-v1.json")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    ).hexdigest()
    assert activation["workflow_sha256"] == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in workflow_paths
    }
    activation_without_hash = dict(activation)
    assert activation_without_hash.pop("contract_hash") == canonical_hash(
        activation_without_hash
    )
    artifact_lock = load("configs/execution/phase-c-artifact-lock-v1.json")
    assert artifact_lock["status"] == "EMPTY_DRAFT_REQUIRES_SUCCESSOR_ON_DEFAULT_BRANCH"
    assert artifact_lock["stage_locks"] == {}
    artifact_lock_without_hash = dict(artifact_lock)
    assert artifact_lock_without_hash.pop("lock_hash") == canonical_hash(
        artifact_lock_without_hash
    )
    preflight_source = (
        ROOT / "scripts/validate_phase_c_workflow_contract.py"
    ).read_text(encoding="utf-8")
    assert "actions/runs/{source['source_run_id']}/attempts/" in preflight_source
    assert "actions/runs/{stage['run_id']}/attempts/" in preflight_source
    assert "actions/runs/{int(raw_run_id)}/attempts/" in preflight_source
    assert "repository_text_hash(SOURCE_LOCK)" in preflight_source

    assert "pair-results-full-v1.json.gz" in pair_workflow
    assert "--soft-deadline-seconds 210" in pair_workflow
    runner_source = (
        ROOT / "scripts/run_hypothesis_tag_mask_pair_factory.py"
    ).read_text(encoding="utf-8")
    reducer_source = runner_source.split("def reduce_pair_shards(", 1)[1].split(
        "def parse_args(", 1
    )[0]
    assert "write_heavy_json_artifact(" in reducer_source
    assert "compact_pair_report(report, heavy_artifact)" in reducer_source
    assert reducer_source.count("enforce_soft_deadline()") >= 8


def test_checkpoint_resume_and_stage_manifest_fail_closed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    factory.write_initial_checkpoint(
        store,
        "ATOMIC_PROPERTY_SEARCH",
        "a" * 40,
        "LOCAL-ALL",
        1,
        None,
    )
    records = [{"tag_id": "tag:a"}, {"tag_id": "tag:b"}]
    factory.persist_resume_progress(store, "ATOMIC_PROPERTY_SEARCH", records)
    checkpoint = load_from_path(store / "checkpoint-v1.json")
    assert checkpoint["cursor"] == 2
    assert checkpoint["completed"] is False
    without_hash = dict(checkpoint)
    assert without_hash.pop("checkpoint_hash") == canonical_hash(without_hash)

    factory.ACTIVE_RESUME_ROOT = store
    factory.ACTIVE_RESUME_CHECKPOINT = checkpoint
    try:
        assert factory.load_resume_progress("ATOMIC_PROPERTY_SEARCH") == records
        progress_path = store / str(checkpoint["resume_progress_path"])
        progress_path.write_bytes(progress_path.read_bytes() + b"tamper")
        with pytest.raises(RuntimeError, match="RESUME_PROGRESS_HASH_MISMATCH"):
            factory.load_resume_progress("ATOMIC_PROPERTY_SEARCH")
    finally:
        factory.ACTIVE_RESUME_ROOT = None
        factory.ACTIVE_RESUME_CHECKPOINT = None

    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "result.json").write_text('{"ok":true}\n', encoding="utf-8")
    factory.write_initial_checkpoint(
        artifact,
        "RAW_FIELD_CENSUS",
        "b" * 40,
        "LOCAL-ALL",
        1,
        None,
    )
    manifest = factory.seal_stage_artifact(
        artifact, "RAW_FIELD_CENSUS", "b" * 40, "LOCAL-ALL"
    )
    factory.verify_stage_artifact(
        artifact,
        str(manifest["manifest_hash"]),
        "RAW_FIELD_CENSUS",
        "b" * 40,
        5_000_000,
    )
    (artifact / "result.json").write_text('{"ok":false}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="STAGE_MANIFEST_FILE_HASH_MISMATCH"):
        factory.verify_stage_artifact(
            artifact,
            str(manifest["manifest_hash"]),
            "RAW_FIELD_CENSUS",
            "b" * 40,
            5_000_000,
        )


def test_checkpoint_cursor_17_receipt_is_sanitized_and_code_bound() -> None:
    receipt = load("reports/hypothesis-research/checkpoint-resume-proof-v1.json")
    without_hash = dict(receipt)
    assert without_hash.pop("proof_hash") == canonical_hash(without_hash)
    assert receipt["candidate_generator_sha256"] == hashlib.sha256(
        (ROOT / "scripts/run_hypothesis_tag_mask_pair_factory.py").read_bytes()
    ).hexdigest()
    assert receipt["source_lock_sha256"] == factory.repository_text_sha256(
        ROOT / "configs/execution/p0-e3-artifact-lock-v1.json"
    )
    interruption = receipt["forced_interruption"]
    assert interruption["cursor"] == 17
    assert interruption["completed"] is False
    assert interruption["expected_nonzero_exit"] is True
    assert interruption["progress_file_sha256"] == interruption[
        "checkpoint_referenced_progress_sha256"
    ]
    resume = receipt["resume"]
    assert resume["resumed_from_cursor"] == 17
    assert resume["completed_prefix_records_recomputed"] == 0
    assert resume["previous_checkpoint_hash"] == interruption[
        "checkpoint_object_hash"
    ]
    assert resume["completed"] is True
    byte_identity = receipt["byte_identity"]
    assert byte_identity["full_results_identical"] is True
    assert byte_identity["compact_results_identical"] is True
    assert byte_identity["clean_pair_results_full_gzip_sha256"] == byte_identity[
        "resumed_pair_results_full_gzip_sha256"
    ]
    assert byte_identity["clean_pair_results_compact_sha256"] == byte_identity[
        "resumed_pair_results_compact_sha256"
    ]
    assert all(value == 0 for value in receipt["external_effect_counters"].values())
    assert not any(receipt["sanitization"].values())


def test_phase_c_evidence_claims_are_bounded_and_recorder_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph_path = ROOT / "reports/evidence/evidence-graph.json"
    before = graph_path.read_bytes()
    record_phase_c_evidence.main()
    first = graph_path.read_bytes()
    record_phase_c_evidence.main()
    assert before == first == graph_path.read_bytes()
    graph = load("reports/evidence/evidence-graph.json")
    claims = {
        row["claim_id"]: row
        for row in graph["claims"]
        if str(row["claim_id"]).startswith(
            (
                "DATA.PHASE_C.",
                "FEATURE.PHASE_C.",
                "EVAL.PHASE_C.",
                "CONTROL.PHASE_C.",
                "REPLAY.PHASE_C.",
                "EXECUTION.PHASE_C.",
                "SECURITY.PHASE_C.",
                "GOV.PHASE_C.",
            )
        )
    }
    assert len(claims) == 15
    implementation_claims = {
        claim_id: row
        for claim_id, row in claims.items()
        if claim_id != "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001"
    }
    assert {row["code_revision"] for row in implementation_claims.values()} == {
        "b2395964faf08a61ac45df36d547025a4b132e13"
    }
    assert claims["GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001"]["code_revision"] == (
        "008396bad19885386bd7d17ab07c75ee79bb0a9e"
    )
    assert claims["FEATURE.PHASE_C.RECONCILIATION.V1.001"]["status"] == "PARTIAL"
    assert claims["EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001"]["status"] == "INVALIDATED"
    assert claims["EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.002"]["status"] == "PARTIAL"
    assert "158 raw historical signals" in claims[
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.002"
    ]["claim"]
    assert claims["EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001"]["status"] == "INVALIDATED"
    assert claims["EVAL.PHASE_C.PAIR_CAMPAIGN.V1.002"]["status"] == "PARTIAL"
    assert "142 rejected tests" in claims["EVAL.PHASE_C.PAIR_CAMPAIGN.V1.002"][
        "claim"
    ]
    assert claims["REPLAY.PHASE_C.DETERMINISM.V1.001"]["status"] == "INVALIDATED"
    assert claims["REPLAY.PHASE_C.DETERMINISM.V1.002"]["status"] == "VERIFIED"
    assert "twenty Git-tracked" in claims[
        "REPLAY.PHASE_C.DETERMINISM.V1.002"
    ]["claim"]
    assert claims["GOV.PHASE_C.ACTIVATION.HOLD.V1.001"]["status"] == "BLOCKED"
    dp6_claim_ids = {
        claim_id for claim_id, row in claims.items() if "DP6" in row["verified_by"]
    }
    assert dp6_claim_ids == {
        "DATA.PHASE_C.RAW_FIELD_CENSUS.V1.001",
        "FEATURE.PHASE_C.RECONCILIATION.V1.001",
        "FEATURE.PHASE_C.TAG_MASK_STORE.V1.001",
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.002",
        "EVAL.PHASE_C.PAIR_CAMPAIGN.V1.002",
        "CONTROL.PHASE_C.ATOMIC_NEGATIVE.V1.001",
        "CONTROL.PHASE_C.PAIR_NEGATIVE.V1.001",
        "REPLAY.PHASE_C.DETERMINISM.V1.002",
        "EXECUTION.PHASE_C.CHECKPOINT_RESUME.V1.001",
    }
    ledger_path = ROOT / "reports/council/decision-ledger.jsonl"
    ledger_bytes = ledger_path.read_bytes()
    assert hashlib.sha256(ledger_bytes[:203_268]).hexdigest() == (
        "8b7201434786aff66a0328c3f2a76ab18a1b525315d5bf61a65d21edb0d0470d"
    )
    ledger = [
        json.loads(line)
        for line in ledger_bytes.decode("utf-8").splitlines()
    ]
    recovery_ids = [
        row["decision_id"]
        for row in ledger
        if row["decision_id"]
        in {
            "RCV3-20260808-076",
            "RCV3-20260808-077",
            "RCV3-20260808-078",
            "RCV3-20260808-079",
            "RCV3-20260808-080",
            "RCV3-20260808-081",
            "RCV3-20260808-082",
            "RCV3-20260808-083",
            "RCV3-20260808-084",
            "RCV3-20260808-085",
            "RCV3-20260808-086",
        }
    ]
    assert recovery_ids == [
        "RCV3-20260808-076",
        "RCV3-20260808-077",
        "RCV3-20260808-078",
        "RCV3-20260808-079",
        "RCV3-20260808-080",
        "RCV3-20260808-081",
        "RCV3-20260808-082",
        "RCV3-20260808-083",
        "RCV3-20260808-084",
        "RCV3-20260808-085",
        "RCV3-20260808-086",
    ]
    record_075 = next(
        row for row in ledger if row["decision_id"] == "RCV3-20260808-075"
    )
    assert record_075["hash"] == (
        "f66b7852b2c1c7da0c51f1b2e2e3ced99b147cfdc416f06779fe2fb83d58b970"
    )
    record_076 = next(
        row for row in ledger if row["decision_id"] == "RCV3-20260808-076"
    )
    assert record_076["decision"].startswith("PASS_AND_HOLD")
    assert record_076["context"]["supersedes_decision_id"] == record_075["decision_id"]
    assert record_076["context"]["historical_record_075_authoritative"] is False
    edges_to_075 = {
        edge["from_claim_id"]
        for edge in graph["edges"]
        if edge["to_decision_id"] == "RCV3-20260808-075"
    }
    assert edges_to_075 == set(record_075["proof"])
    edge_by_id = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert canonical_hash(graph["edges"][:254]) == (
        "ade7fac218879648d46d8c9bedec93ee7937326220ef4017ef65eb7d1de67fbb"
    )
    assert edge_by_id["EDGE.252"]["from_claim_id"] == (
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.002"
    )
    assert edge_by_id["EDGE.253"]["from_claim_id"] == (
        "EVAL.PHASE_C.PAIR_CAMPAIGN.V1.002"
    )
    assert edge_by_id["EDGE.254"]["from_claim_id"] == (
        "REPLAY.PHASE_C.DETERMINISM.V1.002"
    )
    assert [edge_by_id[f"EDGE.{index:03d}"]["from_claim_id"] for index in range(255, 260)] == [
        "EVAL.PHASE_C.ATOMIC_CAMPAIGN.V1.001",
        "EVAL.PHASE_C.PAIR_CAMPAIGN.V1.001",
        "REPLAY.PHASE_C.DETERMINISM.V1.001",
        "SECURITY.PHASE_C.ZERO_EFFECTS.TRIPLE_LOCK.V1.001",
        "GOV.PHASE_C.ACTIVATION.HOLD.V1.001",
    ]
    assert edge_by_id["EDGE.260"] == {
        "edge_id": "EDGE.260",
        "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
        "to_decision_id": "RCV3-20260808-082",
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    assert edge_by_id["EDGE.261"] == {
        "edge_id": "EDGE.261",
        "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
        "to_decision_id": "RCV3-20260808-083",
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    assert edge_by_id["EDGE.262"] == {
        "edge_id": "EDGE.262",
        "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
        "to_decision_id": "RCV3-20260808-084",
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    assert edge_by_id["EDGE.263"] == {
        "edge_id": "EDGE.263",
        "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
        "to_decision_id": "RCV3-20260808-085",
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    assert edge_by_id["EDGE.264"] == {
        "edge_id": "EDGE.264",
        "from_claim_id": "GOV.PHASE_C.PR37.CLOSURE_AUDIT.V1.001",
        "to_decision_id": "RCV3-20260808-086",
        "relation": "SUPPORTS",
        "status": "RECORDED",
    }
    audit = load("reports/closure/pr37-size-evidence-and-reconstructibility-audit-v1.json")
    assert audit["compaction_decision"]["verdict"] == "KEEP_DETAILED_EVIDENCE_IN_GIT"
    assert audit["pull_request_size"]["changed_git_blob_bytes"] == 2_230_743
    assert audit["fresh_reconstruction"]["replay_identical"] is True
    assert all(
        row["recommended_action"] != "REMOVE_FROM_GIT"
        for row in audit["audited_files"]
    )
    assert "SUPERSEDED_BEFORE_EXECUTION" in (
        ROOT / "NEXT-MISSION-PROMPT.md"
    ).read_text(encoding="utf-8")
    valid_graph_bytes = graph_path.read_bytes()
    tampered_graph_path = tmp_path / "evidence-graph.json"
    tampered_graph_path.write_bytes(valid_graph_bytes)
    tampered_ledger_path = tmp_path / "decision-ledger.jsonl"
    duplicate_076 = json.dumps(record_076, ensure_ascii=False, separators=(",", ":"))
    tampered_ledger_path.write_bytes(
        ledger_bytes + duplicate_076.encode("utf-8") + b"\n"
    )
    monkeypatch.setattr(record_phase_c_evidence, "GRAPH", tampered_graph_path)
    monkeypatch.setattr(record_phase_c_evidence, "LEDGER", tampered_ledger_path)
    with pytest.raises(RuntimeError, match="PHASE_C_DUPLICATE_DECISION_ID"):
        record_phase_c_evidence.main()
    assert tampered_graph_path.read_bytes() == valid_graph_bytes

    tampered_graph = json.loads(graph_path.read_text(encoding="utf-8"))
    tampered_graph["edges"][0], tampered_graph["edges"][1] = (
        tampered_graph["edges"][1],
        tampered_graph["edges"][0],
    )
    tampered_graph_path.write_text(
        json.dumps(tampered_graph, ensure_ascii=False), encoding="utf-8"
    )
    tampered_ledger_path.write_bytes(ledger_bytes)
    with pytest.raises(RuntimeError, match="PHASE_C_HISTORICAL_EDGE_PREFIX_MISMATCH"):
        record_phase_c_evidence.main()
    assert not any(
        forbidden in row["claim"].lower()
        for row in claims.values()
        for forbidden in ("production ready", "all 1,398", "all 486 ready")
    )


def load_from_path(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
