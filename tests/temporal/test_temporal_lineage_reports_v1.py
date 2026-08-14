from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import scripts.build_temporal_lineage_reports_v1 as temporal_builder
from scripts.build_temporal_lineage_reports_v1 import (
    AUDIT_MANIFEST_SHA256,
    AUDIT_TARGET_REVISION,
    AUDIT_TARGET_TREE,
    LOOP55_EVIDENCE_IDS,
    LOOP55_MANIFEST_SHA256,
    LOOP55_SOURCE_AUTHORITY_SHA256,
    REPORT_FILENAMES,
    _git_changed_paths,
    _verify_audit_root,
    _verify_loop55_root,
    _verify_loop55_source_authority,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = REPO_ROOT / "reports" / "temporal-lineage"
GENESIS_HASH = "0" * 64


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(filename: str) -> dict[str, Any]:
    value = json.loads((REPORT_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_changed_path_inventory_includes_staged_and_untracked_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "pit@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "PIT Test"],
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-q", "-m", "base"],
        check=True,
    )
    base_revision = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked.write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
    (repository / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    monkeypatch.setattr(temporal_builder, "BASE_REVISION", base_revision)

    assert _git_changed_paths(repository) == ("tracked.txt", "untracked.txt")


def test_exact_report_set_and_shared_deterministic_envelope() -> None:
    assert tuple(sorted(path.name for path in REPORT_ROOT.glob("*.json"))) == tuple(
        sorted(REPORT_FILENAMES)
    )

    for filename in REPORT_FILENAMES:
        document = _load(filename)
        content_sha256 = document.pop("content_sha256")
        assert content_sha256 == _canonical_sha256(document)
        assert document["content_hash_algorithm"] == (
            "SHA256_CANONICAL_JSON_EXCLUDING_CONTENT_SHA256"
        )
        assert document["immutable_review_base_revision"] == (
            "71833964e5d7ba7f5882bfff49b39d567fd5473b"
        )
        assert document["mission_status"] == "ROBIN_POINT_IN_TIME_LINEAGE_V1_PARTIAL"
        assert document["production_status"] == "PRODUCTION_LOCKED"
        assert document["promotion_status"] == "NO_PROMOTION"
        assert document["effect_budget_authority"] == (
            temporal_builder.POINT_IN_TIME_LINEAGE_EFFECT_BUDGET
        )
        assert document["external_effects"] == temporal_builder.ZERO_EXTERNAL_EFFECTS
        assert document["authorized_local_effects"] == (
            temporal_builder.AUTHORIZED_LOCAL_EFFECTS
        )
        # Source schemas may legitimately contain a field named generated_at. The
        # deterministic envelope itself must not add a wall-clock build timestamp.
        assert "generated_at" not in document
        assert document["audit_source"] == {
            "evidence_ids": ["AUDIT:E2013"],
            "logical_root": "audit-evidence/ROBIN-SCIENTIFIC-AUDIT-V1",
            "manifest_sha256": AUDIT_MANIFEST_SHA256,
            "target_sha": AUDIT_TARGET_REVISION,
            "target_tree": AUDIT_TARGET_TREE,
        }
        assert document["loop55_source"] == {
            "candidate_source": {
                "aggregate_sha256": (
                    "a0322568fe62250130d3ff469a73d91b3f300b9ba30d78504fff4a61cc5677c7"
                ),
                "excluded_path_count": 26,
                "included_path_count": 55,
                "manifest_sha256": (
                    "1a12c73bdbd955560b1aeebc7d8eba94bd9cb66dff08b988a46f1f8145803e87"
                ),
                "outside_allowlist_count": 0,
            },
            "corrective_artifact_proof": "LOOP55:E0009",
            "corrective_authority_validation_proof": "LOOP55:E0010",
            "evidence_ids": [f"LOOP55:{item}" for item in LOOP55_EVIDENCE_IDS],
            "exact_head_ci_failure_trigger": "LOOP55:E0007",
            "historical_pre_correction_bounded_component_proof": "LOOP55:E0004",
            "historical_pre_correction_component_proofs": [
                "LOOP55:E0002",
                "LOOP55:E0003",
                "LOOP55:E0004",
                "LOOP55:E0006",
            ],
            "invalid_corrective_harness_receipt": {
                "classification": (
                    "INVALID_CORRECTIVE_HARNESS_PATH_RETAINED_NOT_PROOF"
                ),
                "evidence_id": "LOOP55:E0008",
                "proof_status": "NOT_PROOF",
            },
            "invalid_harness_receipt": {
                "classification": "INVALID_HARNESS_COMMAND_RETAINED_NOT_PROOF",
                "evidence_id": "LOOP55:E0005",
                "proof_status": "NOT_PROOF",
            },
            "logical_root": "audit-evidence/ROBIN-POINT-IN-TIME-LINEAGE-V2",
            "manifest_sha256": LOOP55_MANIFEST_SHA256,
            "namespace": "LOOP55",
            "red_proof": "LOOP55:E0001",
            "source_authority_sha256": LOOP55_SOURCE_AUTHORITY_SHA256,
            "supersedes_unavailable_pack": {
                "candidate_aggregate_status": (
                    "CANONICAL_DIGEST_REPRODUCIBLE_BUT_INSUFFICIENT_FOR_BYTE_EXACT_RESTORATION"
                ),
                "candidate_manifest_sha256": (
                    "d153ea4a1bdaf49399bad5e2eef73cd155951dfae42bc1fd31477851c94d9ffa"
                ),
                "manifest_sha256": (
                    "58fcc690534f719c80bb4ac00cddd08d8fd1cf29ffb25c0ca6a34b0c82c70835"
                ),
                "status": "LOST_OVERWRITTEN_NOT_AVAILABLE",
            },
        }
        assert document["report_generation_receipt"] == {
            "binding": "DETACHED_MANIFEST_CLAIM_IN_EVIDENCE_GRAPH",
            "evidence_id": "LOOP55_REPORTS:E0006",
            "logical_root": (
                "audit-evidence/ROBIN-POINT-IN-TIME-LINEAGE-V1-REPORTS-RECEIPT-V5"
            ),
            "namespace": "LOOP55_REPORTS",
        }
        assert document["reproducibility"] == {
            "builder": "scripts/build_temporal_lineage_reports_v1.py",
            "command_evidence_ids": ["LOOP55_REPORTS:E0006"],
            "mode": "DUAL_PINNED_ROOTS_FAIL_CLOSED",
        }


def test_e2013_denominator_and_all_720_field_rows_are_preserved() -> None:
    inventory = _load("temporal-surface-inventory-v1.json")
    assert inventory["verdict"] == "ROBIN_TEMPORAL_SURFACE_INVENTORY_COMPLETE"
    assert inventory["counts"] == {
        "absent": 8,
        "canonical_timestamp_fields": 720,
        "external_unobserved": 37,
        "file_surfaces": 35,
        "historically_point_in_time_proven": 0,
        "historically_receipt_bounded": 0,
        "historically_reconstructed_not_proven": 19,
        "historically_unknown": 53,
        "invalid_after_cutoff": 0,
        "materialized": 27,
        "postgresql_surfaces": 37,
        "surfaces": 72,
    }

    surfaces = inventory["surfaces"]
    assert [surface["surface_ordinal"] for surface in surfaces] == list(range(1, 73))
    assert len({surface["surface_id"] for surface in surfaces}) == 72
    assert all(len(surface["timestamp_mappings"]) == 10 for surface in surfaces)
    assert [
        mapping["csv_data_row"]
        for surface in surfaces
        for mapping in surface["timestamp_mappings"]
    ] == list(range(1, 721))
    assert Counter(surface["historical_classification"] for surface in surfaces) == {
        "RECONSTRUCTED_NOT_PROVEN": 19,
        "UNKNOWN": 53,
    }
    assert Counter(
        surface["historical_evidence_availability"]["materialization"]
        for surface in surfaces
    ) == {"PRESENT": 27, "ABSENT": 8, "EXTERNAL_UNOBSERVED": 37}
    assert inventory["observation_denominator"] == {
        "classification_counts": {
            "invalid_after_cutoff": 0,
            "point_in_time_proven": 0,
            "receipt_bounded": 0,
            "reconstructed_not_proven": 11_401,
            "unknown": 92_853,
        },
        "global_observation_denominator": "UNKNOWN_NOT_ENUMERABLE",
        "materialized_e2013_observations": 104_254,
        "non_enumerable_surface_counts": {
            "absent": 8,
            "external_unobserved": 37,
        },
        "scope": "27_MATERIALIZED_E2013_SURFACES_ONLY",
    }
    active_input_ids = {
        "legacy_matches",
        "optional_xg",
        "phase_c_v2_team_facts_01",
        "phase_c_v2_team_facts_02",
        "phase_c_v2_team_facts_03",
        "phase_c_v2_team_facts_04",
        "phase_c_v2_team_facts_05",
        "phase_c_v2_restored_source",
    }
    assert {
        surface["surface_id"]
        for surface in surfaces
        if surface["surface_id"] in active_input_ids
        and surface["decision_influence"]
        == "CAN_INFLUENCE_FEATURE_OR_DECISION"
    } == active_input_ids
    assert not any(surface["strict_point_in_time_proven"] for surface in surfaces)
    assert not any(surface["receipt_bounded_proven"] for surface in surfaces)


def test_historical_receipt_and_replay_claims_remain_fail_closed() -> None:
    receipts = _load("source-receipt-inventory-v1.json")
    assert receipts["counts"]["e2013_surfaces"] == 72
    assert receipts["counts"]["historical_receipt_objects_observed"] == 0
    assert receipts["counts"]["historically_point_in_time_proven_surfaces"] == 0
    assert receipts["counts"]["historically_receipt_bounded_surfaces"] == 0
    assert receipts["storage_status"] == "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS"

    replay = _load("historical-point-in-time-replay-v1.json")
    assert replay["verdict"] == "ROBIN_HISTORICAL_POINT_IN_TIME_REPLAY_NOT_POSSIBLE"
    assert replay["summary"] == {
        "full_lineage_replay": 0,
        "logical_results": 15,
        "physical_occurrences": 45,
        "point_in_time_replay_complete": 0,
        "point_in_time_replay_partial": 0,
        "point_in_time_unreplayable": 15,
        "receipt_bounded_replay": 0,
        "unreplayable": 15,
    }
    assert len(replay["results"]) == 15
    assert all(result["replayability"] == "UNREPLAYABLE" for result in replay["results"])
    assert all(
        result["point_in_time_status"] == "POINT_IN_TIME_UNREPLAYABLE"
        for result in replay["results"]
    )
    assert all(
        result["legacy_status"] == "LEGACY_UNVERSIONED_NOT_CANONICAL"
        for result in replay["results"]
    )


def test_bounded_prospective_claims_and_q1_to_q10_answers() -> None:
    contract = _load("temporal-contract-v1.json")
    decision = _load("decision-lineage-trace-v1.json")
    matrix = _load("future-mutation-matrix-v1.json")

    assert contract["verdict"] == "ROBIN_AVAILABILITY_TIME_CONTRACT_V1_READY"
    assert contract["status"] == "PARTIAL"
    assert contract["prospective_status"] == (
        "ROBIN_PROSPECTIVE_POINT_IN_TIME_FAIL_CLOSED_PARTIAL"
    )
    assert contract["storage_resolution"]["status"] == (
        "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS"
    )
    assert contract["metric_semantics"]["metric_definition_version"] == (
        "PREQUENTIAL_METRIC_DEFINITION_V1_REPORT_BOUND"
    )
    assert "do not yet persist" in contract["metric_semantics"][
        "persistence_limit"
    ]
    assert decision["verdict"] == "PRODUCTION_DECISION_PATH_POINT_IN_TIME_STILL_NOT_PROVEN"
    assert decision["durability"]["status"] == (
        "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS"
    )
    assert [item["question_id"] for item in decision["review_questions"]] == [
        f"Q{index}" for index in range(1, 11)
    ]
    assert [item["answer"] for item in decision["review_questions"]] == ["NO"] * 10
    q5 = decision["review_questions"][4]
    assert q5["scope"] == (
        "NO_IN_BOUNDED_REPOSITORY_BACKED_PROVENANCE_GLOBAL_RUNTIME_PARTIAL"
    )
    assert q5["evidence_ref"] == (
        "tests/jalon14/test_prequential_factory.py::"
        "test_self_declared_receipt_and_late_ingestion_fail_closed"
    )
    q2 = decision["review_questions"][1]
    assert q2["evidence_ref"] == (
        "tests/temporal/test_point_in_time_lineage_v1.py::"
        "test_append_change_delete_and_reorder_future_rows_leave_past_team_features_exact"
    )
    q6 = decision["review_questions"][5]
    assert q6["scope"] == (
        "NO_IN_BOUNDED_PREQUENTIAL_GATE_CONTRACT_GLOBAL_RUNTIME_PARTIAL"
    )
    assert q6["evidence_ref"] == (
        "tests/jalon14/test_prequential_factory.py::"
        "test_factory_rejects_content_addressed_snapshot_with_unknown_availability"
    )

    assert matrix["verdict"] == "ADVERSARIAL_FUTURE_MUTATION_INVARIANCE_PARTIAL"
    assert matrix["counts"] == {
        "not_covered": 0,
        "partial": 0,
        "pass": 25,
        "required_cases": 25,
    }
    assert matrix["matrix_execution_status"] == "PASS"
    assert len(matrix["records"]) == 25
    assert Counter(record["status"] for record in matrix["records"]) == {
        "PASS": 25,
    }
    assert matrix["records"][1]["test"] == (
        "test_append_change_delete_and_reorder_future_rows_leave_past_team_features_exact"
    )
    out_of_order = matrix["records"][12]
    assert out_of_order == {
        "case_id": "PIT-MUTATION-13",
        "mutation": "out-of-order ingestion",
        "status": "PASS",
        "test": "test_self_declared_receipt_and_late_ingestion_fail_closed",
        "test_path": "tests/jalon14/test_prequential_factory.py",
    }

    coverage = _load("temporal-test-coverage-v1.json")
    assert coverage["summary"] == {
        "adversarial_value_mutation_tests": 2,
        "boundary_tests": 2,
        "immutability_alias_mutation_tests": 1,
        "mandatory_tests": 5,
        "mandatory_tests_present": 5,
        "mutation_matrix_cases_passed": 25,
        "repository_receipt_boundary_tests": 8,
        "uncovered_active_symbols": 10,
    }
    assert {
        (item["path"], item["test"])
        for item in coverage["repository_receipt_tests"]
    } == {
        (
            "tests/jalon14/test_prequential_pit_closure.py",
            "test_odds_requires_receipt_index_window_r2_and_ties_fail_closed",
        ),
        (
            "tests/jalon14/test_prequential_factory.py",
            "test_self_declared_receipt_and_late_ingestion_fail_closed",
        ),
        (
            "tests/temporal/test_point_in_time_lineage_v1.py",
            "test_asof_rejects_valid_looking_self_declared_receipt_mapping",
        ),
        (
            "tests/jalon14/test_prequential_factory.py",
            "test_forecast_reverifies_source_receipt_bytes",
        ),
        (
            "tests/jalon14/test_prequential_factory.py",
            "test_feature_snapshot_rejects_receipt_payload_value_mismatch",
        ),
        (
            "tests/jalon14/test_prequential_factory.py",
            "test_feature_snapshot_rejects_receipts_from_another_fixture",
        ),
        (
            "tests/jalon14/test_prequential_pit_closure.py",
            "test_source_receipt_rejects_cross_family_odds_capture_as_team_projection",
        ),
        (
            "tests/jalon14/test_prequential_pit_closure.py",
            "test_source_receipt_rejects_backdated_market_closure_for_late_materialization",
        ),
    }


def test_temporal_invalidation_ledger_is_append_only_and_hash_chained() -> None:
    ledger = _load("temporal-invalidation-ledger-v1.json")
    assert ledger["append_only"] is True
    assert ledger["counts"] == {
        "logical_results": 15,
        "physical_occurrences": 45,
        "records": 15,
        "temporal_validity_not_proven": 15,
    }

    previous = GENESIS_HASH
    for sequence, record in enumerate(ledger["records"], 1):
        assert record["sequence"] == sequence
        assert record["previous_record_hash"] == previous
        record_hash = record["record_hash"]
        assert record_hash == _canonical_sha256(
            {key: value for key, value in record.items() if key != "record_hash"}
        )
        previous = record_hash
    assert ledger["chain_tip"] == previous


def test_defect_inventory_closes_p0_p1_without_hiding_p2_blockers() -> None:
    defects = _load("temporal-defect-inventory-v1.json")
    assert defects["counts"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 8,
        "resolved_p1": 7,
        "total": 15,
    }
    assert defects["storage_status"] == "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS"
    assert all(
        defect["severity"] not in {"P0", "P1"}
        for defect in defects["defects"]
        if defect["status"].startswith("OPEN_")
    )
    by_id = {item["defect_id"]: item for item in defects["defects"]}
    assert by_id["PIT55-007"]["status"] == (
        "RESOLVED_BOUNDED_REPOSITORY_RECEIPT_FAIL_CLOSED"
    )
    assert "not positive production PIT proof" in by_id["PIT55-007"]["summary"]
    assert by_id["PIT55-009"]["status"] == "RESOLVED_FAIL_CLOSED_NO_PIT_PROOF"
    assert by_id["PIT55-010"]["status"] == (
        "RESOLVED_FAIL_CLOSED_NO_HISTORICAL_RECLASSIFICATION"
    )
    assert by_id["PIT55-011"]["status"] == (
        "RESOLVED_FAIL_CLOSED_NO_EXTERNAL_READY_CLAIM"
    )
    assert by_id["PIT55-012"]["status"] == (
        "RESOLVED_FAIL_CLOSED_NO_COCKPIT_PIT_CLAIM"
    )


def test_pinned_audit_root_verification_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PINNED_AUDIT_FILE_MISSING"):
        _verify_audit_root(tmp_path)

    (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="PINNED_AUDIT_FILE_MISSING|PINNED_AUDIT_HASH_MISMATCH"):
        _verify_audit_root(tmp_path)


def test_pinned_loop55_root_verification_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PINNED_LOOP55_SEAL_MISSING"):
        _verify_loop55_root(tmp_path, REPO_ROOT)

    (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "sha256sums.txt").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="PINNED_LOOP55_MANIFEST_HASH_MISMATCH"):
        _verify_loop55_root(tmp_path, REPO_ROOT)


def test_pinned_loop55_source_authority_fails_closed() -> None:
    assert LOOP55_SOURCE_AUTHORITY_SHA256 == (
        "ad864e0fb8345cc5864b79dc2671758e2dab1b2ec23b44a92b7267ac16656454"
    )
    _verify_loop55_source_authority(
        {"source_authority_sha256": LOOP55_SOURCE_AUTHORITY_SHA256}
    )
    with pytest.raises(ValueError, match="PINNED_LOOP55_SOURCE_AUTHORITY_MISMATCH"):
        _verify_loop55_source_authority(
            {
                "source_authority_sha256": (
                    "ad864e0fd5f48612c233dc5625c1dd0cd79a61d07569b26b821e8e41943d2ae7"
                )
            }
        )
