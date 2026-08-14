"""Build the deterministic LOOP55 point-in-time lineage reports.

The builder deliberately requires the immutable ROBIN-SCIENTIFIC-AUDIT-V1
root.  It never infers receipts from repository or filesystem metadata and it
never reads a production service.  The E2013 tables are the fixed historical
denominator; current code contracts are reported separately and cannot
revalidate that history.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, cast

BASE_REVISION = "71833964e5d7ba7f5882bfff49b39d567fd5473b"
AUDIT_TARGET_REVISION = "1ffeec1cd89e83deda008da39bb22540a70db896"
AUDIT_TARGET_TREE = "d751c18ea6233ab59ffeb07c3a38453212a9dd87"
AUDIT_MANIFEST_SHA256 = "38559704269d4e31b9406fc3ca90a8d8ba3fa4c16b0e8e8a89eaeaeaef6e5476"
LOOP54_REPLAY_SHA256 = "782ffe26a2a7fd1d4f10d3ea12075781c06d22e63b87c2763272f5ca8fc01987"
LOOP55_MANIFEST_SHA256 = "58fcc690534f719c80bb4ac00cddd08d8fd1cf29ffb25c0ca6a34b0c82c70835"
LOOP55_SOURCE_AUTHORITY_SHA256 = (
    "ad864e0fb8345cc5864b79dc2671758e2dab1b2ec23b44a92b7267ac16656454"
)
LOOP55_CANDIDATE_SOURCE_MANIFEST_SHA256 = (
    "d153ea4a1bdaf49399bad5e2eef73cd155951dfae42bc1fd31477851c94d9ffa"
)
LOOP55_CANDIDATE_SOURCE_AGGREGATE_SHA256 = (
    "c105c2a5d7729fa5d132be339e3b5525ce21acea6c16ef13bc6e3f9d7ed49aaa"
)
LOOP55_CHANGED_PATH_COUNT = 80
LOOP55_INCLUDED_PATH_COUNT = 65
LOOP55_EXCLUDED_PATH_COUNT = 15
LOOP55_ALLOWED_PATH_COUNT = 98
LOOP55_EVIDENCE_IDS = (
    "E0001",
    "E0002",
    "E0003",
    "E0004",
    "E0005",
    "E0006",
)
LOOP55_FINGERPRINT_COUNT = 23
LOOP55_EXIT_CODES = (1, 0, 0, 0, 1, 0)
LOOP55_CLASSIFICATIONS = (
    "EXPECTED_RED_NEGATIVE_CONTROL",
    "HISTORICAL_BOUNDED_PASS_SUPERSEDED_BY_E0004",
    "HISTORICAL_STATIC_PASS_SUPERSEDED_BY_E0006",
    "FINAL_BOUNDED_PASS",
    "INVALID_HARNESS_COMMAND_RETAINED_NOT_PROOF",
    "FINAL_STATIC_PASS",
)

AUDIT_FILES = {
    "commands/E2013.json": "ff800a5dd943df5c6e076a92c8acbba77c6db567b8aa3aec1f65571559581884",
    "harness/phase13_14_dataset_audit.py": "4da2e1f78d7f70148630d2123e2d5ab741831f8290792dde7a53b3b9b0a05d62",
    "manifest.json": AUDIT_MANIFEST_SHA256,
    "raw/E2013.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "raw/E2013.stdout": "e39af803a3a81a13c86b52c21d8713b7d0d4118be78723b519f8145acae016bc",
    "tables/dataset-lineage.csv": "a7497c74dd2c32ffa91997cf8dcfb882b2e64d046e5c0375246dd866122c985b",
    "tables/dataset-quality.csv": "dcd627455e767a80fe9658a07d1140c791d8fe6da850f622ee3279de9fdc64a0",
    "tables/phase13-14-lineage-summary.json": "fbdb417dc739b3d334df5bfa232a15b13db73ab88bcf0171d864d6990cd7a231",
    "tables/time-fields.csv": "8c09e249b937ae62ea374be87bcb0ece9c2d8f41ae0d22077c35be9e5b14e3a8",
}

REPORT_FILENAMES = (
    "temporal-surface-inventory-v1.json",
    "temporal-contract-v1.json",
    "source-receipt-inventory-v1.json",
    "asof-join-audit-v1.json",
    "temporal-test-coverage-v1.json",
    "future-mutation-matrix-v1.json",
    "decision-lineage-trace-v1.json",
    "historical-point-in-time-replay-v1.json",
    "temporal-invalidation-ledger-v1.json",
    "temporal-defect-inventory-v1.json",
)

CANONICAL_TIMESTAMPS = (
    "kickoff_at",
    "odds_captured_at",
    "data_available_at",
    "provider_updated_at",
    "feature_cutoff_at",
    "prediction_created_at",
    "decision_created_at",
    "result_available_at",
    "settled_at",
    "ingested_at",
)

RECONSTRUCTED_SURFACES = frozenset(
    {
        "phase_c_v1_atomic_compact",
        "phase_c_v1_pair_compact",
        "phase_c_v1_atomic_full_durable",
        "phase_c_v1_pair_full_durable",
        "phase_c_v1_atomic_controls",
        "phase_c_v1_pair_controls",
        "phase_c_v2_fixture_universe",
        "phase_c_v2_target_labels",
        "phase_c_v2_team_facts_01",
        "phase_c_v2_team_facts_02",
        "phase_c_v2_team_facts_03",
        "phase_c_v2_team_facts_04",
        "phase_c_v2_team_facts_05",
        "phase_c_v2_source_manifest",
        "phase_c_v2_atomic_summary",
        "phase_c_v2_pair_summary",
        "phase_c_v2_atomic_full",
        "phase_c_v2_pair_full",
        "phase_c_v2_controls",
    }
)

FILE_LOCATORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "legacy_matches": ("TABULAR_ROWS", ("rows",)),
    "optional_xg": ("TABULAR_ROWS", ("rows",)),
    "legacy_backtest_v1": ("TABULAR_ROWS", ("rows",)),
    "legacy_backtest_v2": ("TABULAR_ROWS", ("rows",)),
    "legacy_backtest_v2b": ("TABULAR_ROWS", ("rows",)),
    "legacy_oos_results": ("RFC6901", ("",)),
    "shadow_fixtures_runtime": ("RFC6901", ("",)),
    "shadow_odds_runtime": ("JSONL", ("line:*",)),
    "shadow_predictions_runtime": ("JSONL", ("line:*",)),
    "shadow_decisions_runtime": ("JSONL", ("line:*",)),
    "shadow_settlements_runtime": ("JSONL", ("line:*",)),
    "shadow_demo_fixtures": ("RFC6901", ("",)),
    "shadow_demo_predictions": ("RFC6901", ("",)),
    "shadow_demo_decisions": ("JSONL", ("line:*",)),
    "phase_c_v1_atomic_compact": ("RFC6901", ("/results",)),
    "phase_c_v1_pair_compact": ("RFC6901", ("/results",)),
    "phase_c_v1_atomic_full_declared": ("RFC6901", ("/results",)),
    "phase_c_v1_atomic_full_durable": ("RFC6901", ("/results",)),
    "phase_c_v1_pair_full_durable": ("RFC6901", ("/results",)),
    "phase_c_v1_atomic_controls": ("RFC6901", ("/records",)),
    "phase_c_v1_pair_controls": ("RFC6901", ("/records",)),
    "phase_c_v2_fixture_universe": ("RFC6901", ("/records",)),
    "phase_c_v2_target_labels": ("RFC6901", ("/records",)),
    "phase_c_v2_team_facts_01": ("RFC6901", ("/records",)),
    "phase_c_v2_team_facts_02": ("RFC6901", ("/records",)),
    "phase_c_v2_team_facts_03": ("RFC6901", ("/records",)),
    "phase_c_v2_team_facts_04": ("RFC6901", ("/records",)),
    "phase_c_v2_team_facts_05": ("RFC6901", ("/records",)),
    "phase_c_v2_source_manifest": ("RFC6901", ("",)),
    "phase_c_v2_restored_source": ("DIRECTORY", (".",)),
    "phase_c_v2_atomic_summary": ("RFC6901", ("/records",)),
    "phase_c_v2_pair_summary": ("RFC6901", ("/review_queue",)),
    "phase_c_v2_atomic_full": ("RFC6901", ("/records",)),
    "phase_c_v2_pair_full": ("RFC6901", ("/records",)),
    "phase_c_v2_controls": (
        "RFC6901",
        ("/guard_records", "/modeled_records"),
    ),
}

MODEL_FILES = (
    (36, 45, "src/robin/storage/models.py"),
    (46, 57, "src/robin/storage/prospective_models.py"),
    (58, 65, "src/robin/storage/prequential_models.py"),
    (66, 72, "src/robin/storage/hypothesis_models.py"),
)

RAW_OBSERVATION_LINKED = frozenset({"postgres_fixtures", "postgres_bookmaker_quotes"})
RECEIPT_ANCHORS = frozenset({"postgres_capture_receipts"})
RECEIPT_CHILDREN = frozenset(
    {
        "postgres_prospective_payload_index",
        "postgres_prospective_player_status",
        "postgres_prospective_injuries",
        "postgres_prospective_lineups",
        "postgres_prospective_formations",
        "postgres_prospective_odds_snapshots",
    }
)

MANDATORY_TESTS = (
    (
        "test_late_arriving_pre_cutoff_event_is_excluded_when_observed_after_cutoff",
        "ADVERSARIAL_VALUE_MUTATION",
        "prospective fixture version selection",
    ),
    (
        "test_future_value_mutation_does_not_change_past_feature_snapshot",
        "IMMUTABILITY_ALIAS_MUTATION",
        "prequential feature snapshot input alias after freeze",
    ),
    (
        "test_future_value_mutation_does_not_change_past_decision_hash",
        "ADVERSARIAL_VALUE_MUTATION",
        "as-of odds selection and shadow decision hash",
    ),
    (
        "test_missing_availability_receipt_fails_closed",
        "BOUNDARY_TEST",
        "receipt-backed feature provenance",
    ),
    (
        "test_model_created_after_cutoff_is_rejected",
        "BOUNDARY_TEST",
        "prequential model availability",
    ),
)

REPOSITORY_RECEIPT_TESTS = (
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
)
SELF_DECLARED_RECEIPT_TEST = REPOSITORY_RECEIPT_TESTS[1]
OUT_OF_ORDER_INGESTION_TEST = REPOSITORY_RECEIPT_TESTS[1]
FUTURE_ROW_VALUE_MUTATION_TEST = (
    "tests/temporal/test_point_in_time_lineage_v1.py",
    "test_append_change_delete_and_reorder_future_rows_leave_past_team_features_exact",
)
UNKNOWN_AVAILABILITY_GATE_TEST = (
    "tests/jalon14/test_prequential_factory.py",
    "test_factory_rejects_content_addressed_snapshot_with_unknown_availability",
)

MUTATION_CASES = (
    ("future row appended", "PASS", FUTURE_ROW_VALUE_MUTATION_TEST[1]),
    ("future row value changed", "PASS", FUTURE_ROW_VALUE_MUTATION_TEST[1]),
    ("future row deleted", "PASS", FUTURE_ROW_VALUE_MUTATION_TEST[1]),
    ("past event received late", "PASS", MANDATORY_TESTS[0][0]),
    ("retroactive correction received late", "PASS", "test_late_retroactive_correction_and_newer_provider_version_are_excluded"),
    ("same event with newer provider version", "PASS", "test_late_retroactive_correction_and_newer_provider_version_are_excluded"),
    ("missing available_at", "PASS", MANDATORY_TESTS[3][0]),
    ("naive datetime", "PASS", "test_naive_dst_fold_and_date_only_temporal_keys_are_rejected"),
    ("timezone offset", "PASS", "test_equivalent_timezone_offsets_have_one_receipt_identity"),
    ("DST transition", "PASS", "test_naive_dst_fold_and_date_only_temporal_keys_are_rejected"),
    ("date-only truncation", "PASS", "test_naive_dst_fold_and_date_only_temporal_keys_are_rejected"),
    ("identical available_at tie", "PASS", "test_asof_equal_time_tie_is_deterministic_or_fails_closed"),
    ("out-of-order ingestion", "PASS", OUT_OF_ORDER_INGESTION_TEST[1]),
    ("duplicate payload", "PASS", "test_duplicate_and_repeated_payload_receipts_are_order_invariant"),
    ("same payload received twice", "PASS", "test_duplicate_and_repeated_payload_receipts_are_order_invariant"),
    ("provider timestamp before receipt", "PASS", "test_provider_publication_order_and_clock_skew_are_conservative"),
    ("provider timestamp after receipt", "PASS", "test_provider_publication_order_and_clock_skew_are_conservative"),
    ("clock-skew contradiction", "PASS", "test_provider_publication_order_and_clock_skew_are_conservative"),
    ("current fixture accidentally included in rolling window", "PASS", "test_current_fixture_result_is_not_in_peer_rolling_window"),
    ("future fixture accidentally included in team history", "PASS", FUTURE_ROW_VALUE_MUTATION_TEST[1]),
    ("result data accidentally joined before kickoff", "PASS", "test_finished_result_verified_before_kickoff_is_rejected"),
    ("lineup received after cutoff", "PASS", "test_lineup_received_after_cutoff_is_rejected"),
    ("odds snapshot received after cutoff", "PASS", MANDATORY_TESTS[2][0]),
    ("model trained after cutoff", "PASS", MANDATORY_TESTS[4][0]),
    ("calibration artifact created after cutoff", "PASS", "test_calibration_artifact_created_after_cutoff_is_rejected_with_model_bundle"),
)

POINT_IN_TIME_LINEAGE_EFFECT_BUDGET = (
    "BUSINESS_DATA_NETWORK_CALLS_0;NEON_API_CALLS_0;"
    "POSTGRESQL_PRODUCTION_CONNECTIONS_0;PRODUCTION_SQL_READS_0;"
    "PRODUCTION_SQL_WRITES_0;"
    "LOCAL_TEMPORARY_SQLITE_READS_ALLOWED_FOR_TESTS_AND_OFFLINE_REPLAY_ONLY;"
    "LOCAL_TEMPORARY_SQLITE_WRITES_ALLOWED_FOR_TESTS_AND_OFFLINE_REPLAY_ONLY;"
    "LOCAL_TEMPORARY_SQLITE_MUST_USE_PYTEST_TMP_PATH_OR_OS_TEMP;"
    "PERSISTENT_LOCAL_DATABASE_MUTATIONS_0;"
    "EPHEMERAL_CI_POSTGRESQL_TEST_SERVICE_ALLOWED;R2_OPERATIONS_0;"
    "PROVIDER_CALLS_0;API_FOOTBALL_CALLS_0;ODDS_PROVIDER_CALLS_0;"
    "LIVE_WORKFLOW_DISPATCHES_0;MIGRATION_0014_0;"
    "NEW_DATABASE_MIGRATIONS_0;RECOVERY_BRANCH_CREATIONS_0;"
    "ROLE_CREATIONS_0;PURCHASES_0;REAL_BETS_0;PROMOTIONS_0;"
    "SOCIAL_PUBLICATIONS_0"
)

ZERO_EXTERNAL_EFFECTS = {
    "api_football_calls": 0,
    "business_data_network_calls": 0,
    "live_workflow_dispatches": 0,
    "migration_0014_production_applications": 0,
    "migration_0014_source_changes": 0,
    "neon_api_calls": 0,
    "new_database_migrations": 0,
    "odds_provider_calls": 0,
    "persistent_local_database_mutations": 0,
    "production_postgresql_connections": 0,
    "production_sql_reads": 0,
    "production_sql_writes": 0,
    "promotions": 0,
    "provider_calls": 0,
    "purchases": 0,
    "r2_operations": 0,
    "real_bets": 0,
    "recovery_branch_creations": 0,
    "role_creations": 0,
    "social_publications": 0,
}

AUTHORIZED_LOCAL_EFFECTS = {
    "ephemeral_ci_postgresql_test_service": "ALLOWED",
    "local_temporary_sqlite_migration_executions": (
        "BOUNDED_TEST_BOOTSTRAP_ALLOWED"
    ),
    "local_temporary_sqlite_path_constraint": "PYTEST_TMP_PATH_OR_OS_TEMP",
    "local_temporary_sqlite_reads": "TESTS_AND_OFFLINE_REPLAY_ONLY",
    "local_temporary_sqlite_writes": "TESTS_AND_OFFLINE_REPLAY_ONLY",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _repository_sha256(path: Path) -> str:
    return _sha256_bytes(
        path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    )


def _with_content_hash(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["content_hash_algorithm"] = "SHA256_CANONICAL_JSON_EXCLUDING_CONTENT_SHA256"
    result["content_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def _verify_content_hash(document: dict[str, Any]) -> None:
    stored = document.get("content_sha256")
    candidate = {key: value for key, value in document.items() if key != "content_sha256"}
    if stored != _sha256_bytes(_canonical_bytes(candidate)):
        raise ValueError(f"REPORT_CONTENT_HASH_MISMATCH:{document.get('report_id')}")


def _verify_audit_root(audit_root: Path) -> Path:
    try:
        root = audit_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("PINNED_AUDIT_ROOT_REQUIRED") from error
    for relative, expected in AUDIT_FILES.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"PINNED_AUDIT_FILE_MISSING:{relative}")
        actual = _sha256_file(path)
        if actual != expected:
            raise ValueError(f"PINNED_AUDIT_HASH_MISMATCH:{relative}:{actual}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    target = manifest.get("target", {})
    if (
        manifest.get("audit_name") != "ROBIN-SCIENTIFIC-AUDIT-V1"
        or target.get("sha") != AUDIT_TARGET_REVISION
        or target.get("tree") != AUDIT_TARGET_TREE
        or target.get("immutable") is not True
    ):
        raise ValueError("PINNED_AUDIT_TARGET_MISMATCH")
    return root


def _git_changed_paths(repo_root: Path) -> tuple[str, ...]:
    paths: set[str] = set()
    for arguments in (
        ("diff", "--name-only", "-z", BASE_REVISION, "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        result = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=True,
            capture_output=True,
        )
        paths.update(
            item.decode("utf-8").replace("\\", "/")
            for item in result.stdout.split(b"\0")
            if item
        )
    return tuple(sorted(paths))


def _candidate_path_is_detached(relative: str) -> bool:
    return (
        relative
        in {
            "docs/scientific/ROBIN-POINT-IN-TIME-LINEAGE-V1.md",
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "scripts/build_temporal_lineage_reports_v1.py",
            "tests/temporal/test_temporal_lineage_reports_v1.py",
        }
        or relative.startswith("reports/temporal-lineage/")
    )


def _verify_candidate_source(
    repo_root: Path,
    pack_root: Path,
    pack_manifest: dict[str, Any],
) -> None:
    try:
        repo = repo_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("PINNED_LOOP55_REPOSITORY_ROOT_REQUIRED") from error
    candidate_meta = pack_manifest.get("candidate_source")
    if not isinstance(candidate_meta, dict):
        raise ValueError("PINNED_LOOP55_CANDIDATE_SOURCE_REQUIRED")
    candidate_path = pack_root / "candidate-source-manifest.json"
    if (
        candidate_meta.get("manifest_path") != candidate_path.name
        or candidate_meta.get("manifest_sha256")
        != LOOP55_CANDIDATE_SOURCE_MANIFEST_SHA256
        or _sha256_file(candidate_path) != LOOP55_CANDIDATE_SOURCE_MANIFEST_SHA256
        or candidate_meta.get("aggregate_sha256")
        != LOOP55_CANDIDATE_SOURCE_AGGREGATE_SHA256
        or candidate_meta.get("included_path_count") != LOOP55_INCLUDED_PATH_COUNT
        or candidate_meta.get("excluded_path_count") != LOOP55_EXCLUDED_PATH_COUNT
        or candidate_meta.get("outside_allowlist") != []
    ):
        raise ValueError("PINNED_LOOP55_CANDIDATE_SOURCE_META_MISMATCH")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if (
        candidate.get("schema_version")
        != "robin-point-in-time-lineage-candidate-source-v1"
        or candidate.get("base_revision") != BASE_REVISION
        or candidate.get("base_tree") != "fc282035a9c5642b467e3287115a6e54acb2d109"
        or candidate.get("source_authority_sha256")
        != LOOP55_SOURCE_AUTHORITY_SHA256
        or candidate.get("aggregate_sha256")
        != LOOP55_CANDIDATE_SOURCE_AGGREGATE_SHA256
        or candidate.get("changed_path_count") != LOOP55_CHANGED_PATH_COUNT
        or candidate.get("included_path_count") != LOOP55_INCLUDED_PATH_COUNT
        or candidate.get("excluded_path_count") != LOOP55_EXCLUDED_PATH_COUNT
        or candidate.get("allowed_path_count") != LOOP55_ALLOWED_PATH_COUNT
        or candidate.get("outside_allowlist") != []
    ):
        raise ValueError("PINNED_LOOP55_CANDIDATE_SOURCE_CONTRACT_MISMATCH")
    excluded_paths = candidate.get("excluded_paths")
    if (
        not isinstance(excluded_paths, list)
        or len(excluded_paths) != LOOP55_EXCLUDED_PATH_COUNT
        or excluded_paths != sorted(excluded_paths)
        or any(not _candidate_path_is_detached(str(path)) for path in excluded_paths)
    ):
        raise ValueError("PINNED_LOOP55_CANDIDATE_EXCLUSIONS_MISMATCH")

    files = candidate.get("files")
    if not isinstance(files, list) or len(files) != LOOP55_INCLUDED_PATH_COUNT:
        raise ValueError("PINNED_LOOP55_CANDIDATE_FILE_COUNT_MISMATCH")
    aggregate = hashlib.sha256()
    included_paths: list[str] = []
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("PINNED_LOOP55_CANDIDATE_FILE_RECORD_INVALID")
        relative = str(row.get("path", ""))
        parts = relative.split("/")
        if (
            not relative
            or "\\" in relative
            or ":" in parts[0]
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError(f"PINNED_LOOP55_CANDIDATE_PATH_INVALID:{relative}")
        try:
            target = repo.joinpath(*parts).resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError(
                f"PINNED_LOOP55_CANDIDATE_FILE_MISSING:{relative}"
            ) from error
        if not target.is_file() or not target.is_relative_to(repo):
            raise ValueError(f"PINNED_LOOP55_CANDIDATE_PATH_INVALID:{relative}")
        raw = target.read_bytes()
        canonical_hash = _sha256_bytes(
            raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        )
        if (
            row.get("raw_bytes") != len(raw)
            or row.get("raw_sha256") != _sha256_bytes(raw)
            or row.get("canonical_lf_sha256") != canonical_hash
        ):
            raise ValueError(f"PINNED_LOOP55_CANDIDATE_FILE_DRIFT:{relative}")
        included_paths.append(relative)
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(bytes.fromhex(canonical_hash))
    if included_paths != sorted(set(included_paths)):
        raise ValueError("PINNED_LOOP55_CANDIDATE_FILE_ORDER_MISMATCH")
    if aggregate.hexdigest() != LOOP55_CANDIDATE_SOURCE_AGGREGATE_SHA256:
        raise ValueError("PINNED_LOOP55_CANDIDATE_AGGREGATE_MISMATCH")

    matrix = json.loads(
        (repo / "configs/agents/mission-activation-matrix-v3.json").read_text(
            encoding="utf-8"
        )
    )
    allowed_paths = matrix["missions"]["POINT_IN_TIME_LINEAGE"]["allowed_paths"]
    allowed_hash = _sha256_bytes(_canonical_bytes(allowed_paths))
    if (
        len(allowed_paths) != candidate["allowed_path_count"]
        or allowed_hash != candidate["allowed_paths_compact_json_sha256"]
        or matrix["authorization"].get("point_in_time_lineage_effect_budget")
        != POINT_IN_TIME_LINEAGE_EFFECT_BUDGET
    ):
        raise ValueError("PINNED_LOOP55_CANDIDATE_ALLOWLIST_MISMATCH")
    current_changed = _git_changed_paths(repo)
    current_unsealed = sorted(set(current_changed) - set(included_paths))
    if any(not _candidate_path_is_detached(path) for path in current_unsealed):
        raise ValueError("PINNED_LOOP55_CANDIDATE_UNSEALED_SOURCE_CHANGE")
    if set(current_changed) - set(allowed_paths):
        raise ValueError("PINNED_LOOP55_CANDIDATE_OUTSIDE_ALLOWLIST")


def _verify_loop55_root(loop55_root: Path, repo_root: Path) -> Path:
    try:
        root = loop55_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("PINNED_LOOP55_ROOT_REQUIRED") from error
    manifest_path = root / "manifest.json"
    sums_path = root / "sha256sums.txt"
    if not manifest_path.is_file() or not sums_path.is_file():
        raise ValueError("PINNED_LOOP55_SEAL_MISSING")
    if _sha256_file(manifest_path) != LOOP55_MANIFEST_SHA256:
        raise ValueError("PINNED_LOOP55_MANIFEST_HASH_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("evidence_pack_id") != "ROBIN-POINT-IN-TIME-LINEAGE-V1"
        or manifest.get("namespace") != "LOOP55"
        or manifest.get("base_revision") != BASE_REVISION
        or tuple(manifest.get("evidence_ids", ())) != LOOP55_EVIDENCE_IDS
        or manifest.get("command_count") != len(LOOP55_EVIDENCE_IDS)
        or manifest.get("fingerprint_count") != LOOP55_FINGERPRINT_COUNT
    ):
        raise ValueError("PINNED_LOOP55_MANIFEST_CONTRACT_MISMATCH")
    _verify_loop55_source_authority(manifest)
    if (
        manifest.get("effect_budget_authority")
        != POINT_IN_TIME_LINEAGE_EFFECT_BUDGET
        or manifest.get("external_effects") != ZERO_EXTERNAL_EFFECTS
        or manifest.get("authorized_local_effects") != AUTHORIZED_LOCAL_EFFECTS
    ):
        raise ValueError("PINNED_LOOP55_EFFECT_BUDGET_MISMATCH")
    green_proof = manifest.get("green_proof")
    if green_proof != {
        "bounded_evidence_id": "E0004",
        "historical_bounded_evidence_id": "E0002",
        "historical_static_evidence_id": "E0003",
        "invalid_harness_evidence_id": "E0005",
        "static_validation_evidence_id": "E0006",
        "status": "PASS",
    }:
        raise ValueError("PINNED_LOOP55_PROOF_ROLES_MISMATCH")
    if _sha256_file(sums_path) != manifest.get("sha256sums_sha256"):
        raise ValueError("PINNED_LOOP55_SUMS_HASH_MISMATCH")

    fingerprints: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        expected, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("PINNED_LOOP55_SUMS_FORMAT_INVALID")
        if relative in fingerprints:
            raise ValueError(f"PINNED_LOOP55_SUM_DUPLICATE:{relative}")
        fingerprints[relative] = expected
    if len(fingerprints) != manifest["fingerprint_count"]:
        raise ValueError("PINNED_LOOP55_FINGERPRINT_COUNT_MISMATCH")
    for relative, expected in fingerprints.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"PINNED_LOOP55_FILE_MISSING:{relative}")
        actual = _sha256_file(path)
        if actual != expected:
            raise ValueError(f"PINNED_LOOP55_FILE_HASH_MISMATCH:{relative}:{actual}")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    expected_files = set(fingerprints) | {"manifest.json", "sha256sums.txt"}
    if actual_files != expected_files:
        raise ValueError("PINNED_LOOP55_FILE_SET_MISMATCH")

    command_lines = (root / "commands.jsonl").read_text(encoding="utf-8").splitlines()
    if len(command_lines) != len(LOOP55_EVIDENCE_IDS):
        raise ValueError("PINNED_LOOP55_COMMAND_COUNT_MISMATCH")
    commands = [json.loads(line) for line in command_lines]
    if tuple(command["evidence_id"] for command in commands) != LOOP55_EVIDENCE_IDS:
        raise ValueError("PINNED_LOOP55_COMMAND_ORDER_MISMATCH")
    for command in commands:
        evidence_id = command["evidence_id"]
        command_file = json.loads(
            (root / f"commands/{evidence_id}.json").read_text(encoding="utf-8")
        )
        if command != command_file:
            raise ValueError(f"PINNED_LOOP55_COMMAND_RECORD_MISMATCH:{evidence_id}")
        if _sha256_file(root / command["stdout_path"]) != command["stdout_sha256"]:
            raise ValueError(f"PINNED_LOOP55_STDOUT_HASH_MISMATCH:{evidence_id}")
        if _sha256_file(root / command["stderr_path"]) != command["stderr_sha256"]:
            raise ValueError(f"PINNED_LOOP55_STDERR_HASH_MISMATCH:{evidence_id}")
    if tuple(command["exit_code"] for command in commands) != LOOP55_EXIT_CODES:
        raise ValueError("PINNED_LOOP55_EXIT_CONTRACT_MISMATCH")
    records = manifest.get("records")
    if (
        not isinstance(records, list)
        or tuple(record.get("evidence_id") for record in records)
        != LOOP55_EVIDENCE_IDS
        or tuple(record.get("classification") for record in records)
        != LOOP55_CLASSIFICATIONS
        or tuple(record.get("exit_code") for record in records)
        != LOOP55_EXIT_CODES
    ):
        raise ValueError("PINNED_LOOP55_EVIDENCE_CLASSIFICATION_MISMATCH")
    _verify_candidate_source(repo_root, root, manifest)
    return root


def _verify_loop55_source_authority(manifest: dict[str, Any]) -> None:
    if manifest.get("source_authority_sha256") != LOOP55_SOURCE_AUTHORITY_SHA256:
        raise ValueError("PINNED_LOOP55_SOURCE_AUTHORITY_MISMATCH")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _audit_source() -> dict[str, Any]:
    return {
        "evidence_ids": ["AUDIT:E2013"],
        "logical_root": "audit-evidence/ROBIN-SCIENTIFIC-AUDIT-V1",
        "manifest_sha256": AUDIT_MANIFEST_SHA256,
        "target_sha": AUDIT_TARGET_REVISION,
        "target_tree": AUDIT_TARGET_TREE,
    }


def _audit_sources() -> list[dict[str, Any]]:
    return [
        {
            "evidence_ids": ["AUDIT:E2013"],
            "logical_path": f"audit-evidence/ROBIN-SCIENTIFIC-AUDIT-V1/{path}",
            "sha256": sha256,
        }
        for path, sha256 in sorted(AUDIT_FILES.items())
        if path.startswith("tables/") or path == "commands/E2013.json"
    ]


def _loop55_source() -> dict[str, Any]:
    return {
        "candidate_source": {
            "aggregate_sha256": LOOP55_CANDIDATE_SOURCE_AGGREGATE_SHA256,
            "excluded_path_count": LOOP55_EXCLUDED_PATH_COUNT,
            "included_path_count": LOOP55_INCLUDED_PATH_COUNT,
            "manifest_sha256": LOOP55_CANDIDATE_SOURCE_MANIFEST_SHA256,
            "outside_allowlist_count": 0,
        },
        "evidence_ids": [f"LOOP55:{item}" for item in LOOP55_EVIDENCE_IDS],
        "green_proof": "LOOP55:E0004",
        "historical_superseded_proofs": ["LOOP55:E0002", "LOOP55:E0003"],
        "invalid_harness_receipt": {
            "classification": "INVALID_HARNESS_COMMAND_RETAINED_NOT_PROOF",
            "evidence_id": "LOOP55:E0005",
            "proof_status": "NOT_PROOF",
        },
        "logical_root": "audit-evidence/ROBIN-POINT-IN-TIME-LINEAGE-V1",
        "manifest_sha256": LOOP55_MANIFEST_SHA256,
        "namespace": "LOOP55",
        "red_proof": "LOOP55:E0001",
        "source_authority_sha256": LOOP55_SOURCE_AUTHORITY_SHA256,
        "static_validation": "LOOP55:E0006",
    }


def _repo_source(repo_root: Path, path: str, *, symbols: tuple[str, ...] = ()) -> dict[str, Any]:
    source = repo_root / path
    return {
        "evidence_status": "PROUVÉ",
        "path": path,
        "sha256": _repository_sha256(source),
        "symbols": list(symbols),
    }


def _base_report(
    report_id: str,
    *,
    status: str,
    verdict: str,
    evidence_status: str = "PROBABLE",
) -> dict[str, Any]:
    return {
        "audit_source": _audit_source(),
        "loop55_source": _loop55_source(),
        "evidence_status": evidence_status,
        "effect_budget_authority": POINT_IN_TIME_LINEAGE_EFFECT_BUDGET,
        "external_effects": dict(ZERO_EXTERNAL_EFFECTS),
        "authorized_local_effects": dict(AUTHORIZED_LOCAL_EFFECTS),
        "immutable_review_base_revision": BASE_REVISION,
        "mission_id": "POINT_IN_TIME_LINEAGE",
        "mission_status": "ROBIN_POINT_IN_TIME_LINEAGE_V1_PARTIAL",
        "production_status": "PRODUCTION_LOCKED",
        "promotion_status": "NO_PROMOTION",
        "report_generation_receipt": {
            "binding": "DETACHED_MANIFEST_CLAIM_IN_EVIDENCE_GRAPH",
            "evidence_id": "LOOP55_REPORTS:E0004",
            "logical_root": "audit-evidence/ROBIN-POINT-IN-TIME-LINEAGE-V1-REPORTS-RECEIPT-V3",
            "namespace": "LOOP55_REPORTS",
        },
        "report_id": report_id,
        "reproducibility": {
            "builder": "scripts/build_temporal_lineage_reports_v1.py",
            "command_evidence_ids": ["LOOP55_REPORTS:E0004"],
            "mode": "DUAL_PINNED_ROOTS_FAIL_CLOSED",
        },
        "schema_version": "robin-temporal-lineage-report-v1",
        "status": status,
        "verdict": verdict,
    }


def _model_contracts(repo_root: Path, lineage: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for first, last, relative in MODEL_FILES:
        source = repo_root / relative
        lines = source.read_text(encoding="utf-8").splitlines()
        declarations = {
            match.group(1): line_number
            for line_number, line in enumerate(lines, 1)
            if (match := re.search(r'__tablename__\s*=\s*"([^"]+)"', line))
        }
        for ordinal in range(first, last + 1):
            table = lineage[ordinal - 1]["dataset_id"].removeprefix("postgres_")
            if table not in declarations:
                raise ValueError(f"E2013_TABLE_DECLARATION_MISSING:{table}")
            result[table] = {
                "line": declarations[table],
                "path": relative,
                "sha256": _repository_sha256(source),
                "symbol": table,
            }
    return result


def _materialization(row: dict[str, str]) -> str:
    value = row["materialization"]
    if value.startswith("PRESENT:"):
        return "PRESENT"
    if value == "ABSENT":
        return "ABSENT"
    return "EXTERNAL_UNOBSERVED"


def _lifecycle(surface_id: str, active_role: str) -> str:
    if surface_id.startswith("legacy_"):
        return "LEGACY_ACTIVE_OR_REPORT"
    if surface_id.startswith("shadow_demo_"):
        return "DEMO_REFERENCE_ONLY"
    if surface_id.startswith("phase_c_"):
        return "ACTIVE_RESEARCH_NON_PROMOTABLE"
    if surface_id.startswith("postgres_"):
        return "ACTIVE_CODE_REFERENCED_EXTERNAL"
    if "ACTIVE_RUNTIME" in active_role:
        return "ACTIVE_RUNTIME_DECLARED"
    return "ACTIVE_OR_OPTIONAL"


def _data_family(surface_id: str) -> str:
    if surface_id.startswith("legacy_"):
        return "LEGACY_HISTORICAL_OR_REPORT"
    if surface_id.startswith("shadow_"):
        return "SHADOW_RUNTIME_OR_DEMO"
    if surface_id.startswith("phase_c_v1"):
        return "PHASE_C_V1_RESEARCH"
    if surface_id.startswith("phase_c_v2"):
        return "PHASE_C_V2_RESEARCH"
    if "prospective" in surface_id or "capture_" in surface_id or "temporal_data" in surface_id:
        return "PROSPECTIVE_CAPTURE"
    if "prequential" in surface_id:
        return "PREQUENTIAL"
    if "hypothesis" in surface_id:
        return "HYPOTHESIS_INTELLIGENCE"
    return "CORE_POSTGRESQL"


def _decision_influence(surface_id: str, active_role: str) -> str:
    if "REPORT" in active_role or "CONTROL" in active_role or "MANIFEST" in active_role:
        return "DERIVED_REPORT_OR_CONTROL_ONLY"
    if surface_id.startswith("shadow_demo_"):
        return "DEMO_ONLY_NOT_PRODUCTION"
    if "settlement" in surface_id:
        return "POST_DECISION_SETTLEMENT"
    if "_INPUT" in active_role:
        return "CAN_INFLUENCE_FEATURE_OR_DECISION"
    if any(token in surface_id for token in ("fixture", "feature", "odds", "prediction", "decision", "model")):
        return "CAN_INFLUENCE_FEATURE_OR_DECISION"
    return "INDIRECT_OR_NOT_ESTABLISHED"


def _field_descriptor(
    rows: list[dict[str, str]],
    canonical: str,
    *,
    receipt_backed: bool = False,
) -> dict[str, Any]:
    row = next(item for item in rows if item["canonical_timestamp"] == canonical)
    source_field: str | None = row["source_field"]
    if source_field in {"ABSENT/UNIDENTIFIED", "NON VÉRIFIÉ"}:
        source_field = None
    return {
        "canonical_field": canonical,
        "evidence_status": row["evidence_status"],
        "presence": row["presence"],
        "receipt_backed": receipt_backed,
        "semantic": row["semantic"],
        "source_field": source_field,
        "temporal_risk": row["temporal_risk"],
    }


def _receipt_contract_status(surface_id: str) -> str:
    if surface_id in RAW_OBSERVATION_LINKED:
        return "RAW_OBSERVATION_FK_SCHEMA_ONLY_UNOBSERVED"
    if surface_id in RECEIPT_ANCHORS:
        return "RECEIPT_ANCHOR_SCHEMA_ONLY_UNOBSERVED"
    if surface_id in RECEIPT_CHILDREN:
        return "RECEIPT_FK_SCHEMA_ONLY_UNOBSERVED"
    if surface_id.startswith("postgres_"):
        return "NO_DIRECT_RECEIPT_CONTRACT_OBSERVED"
    return "NO_OBSERVED_SOURCE_RECEIPT"


def _surface_join_rule(surface_id: str) -> str:
    rules = {
        "postgres_prospective_fixtures": "registered_at <= cutoff; registered_at is not a receipt-backed availability proof",
        "postgres_prequential_feature_snapshots": "all non-missing provenance must carry receipt_id, payload_sha256 and available_at <= cutoff in the prospective code contract",
        "postgres_prequential_model_versions": "created_at <= predicted_at and training_cutoff <= cutoff in the prospective code contract",
        "postgres_prequential_predictions": "the covered path validates odds_snapshot_id through a receipt-linked odds snapshot and immutable R2 payload; legacy rows remain UNKNOWN_NOT_REVALIDATED",
        "postgres_shadow_decisions": "the covered ShadowDecision persists complete lineage in append-only JSONL; the unobserved legacy SQL surface remains UNKNOWN_NOT_REVALIDATED",
    }
    if surface_id.startswith("phase_c_v2_team_facts_"):
        return "availability_proxy_at is a deterministic proxy and is forbidden as receipt proof"
    return rules.get(surface_id, "NO_RECEIPT_BACKED_ASOF_RULE_PROVEN_FOR_THIS_SURFACE")


def _surface_test(surface_id: str) -> tuple[str | None, str | None]:
    tests = {
        "postgres_prospective_fixtures": (MANDATORY_TESTS[0][0], MANDATORY_TESTS[0][0]),
        "postgres_prequential_feature_snapshots": (MANDATORY_TESTS[3][0], MANDATORY_TESTS[1][0]),
        "postgres_prequential_model_versions": (MANDATORY_TESTS[4][0], MANDATORY_TESTS[4][0]),
        "postgres_prequential_predictions": (MANDATORY_TESTS[4][0], MANDATORY_TESTS[2][0]),
        "postgres_shadow_decisions": (MANDATORY_TESTS[2][0], MANDATORY_TESTS[2][0]),
    }
    return tests.get(surface_id, (None, None))


def _prospective_enforcement(surface_id: str) -> str:
    if surface_id in {
        "postgres_prospective_fixtures",
        "postgres_prequential_feature_snapshots",
        "postgres_prequential_model_versions",
        "postgres_prequential_predictions",
        "postgres_shadow_decisions",
    }:
        return "COVERED_CODE_CONTRACT_STORAGE_OR_END_TO_END_PARTIAL"
    return "NOT_PROVEN_FOR_CURRENT_SURFACE"


def _required_repair(surface_id: str, materialization: str, proof_level: str) -> str:
    if surface_id in {"postgres_shadow_decisions", "postgres_prequential_predictions"}:
        return "Use the existing provenance JSON, content-addressed R2 manifests, snapshot-to-receipt chain or append-only shadow JSONL for covered future records; retain legacy rows as UNKNOWN_NOT_REVALIDATED"
    if proof_level == "RECONSTRUCTED_NOT_PROVEN":
        return "Preserve reconstruction status; never infer first observation; capture future source receipts prospectively"
    if materialization == "EXTERNAL_UNOBSERVED":
        return "Observe an independently authorized immutable database snapshot with receipt-to-row lineage; schema alone is insufficient"
    if materialization == "ABSENT":
        return "Keep unavailable; do not fabricate rows or timestamps"
    return "Retain historical UNKNOWN; add receipt-backed prospective capture and surface-specific mutation tests"


def _build_surface_inventory(
    repo_root: Path,
    lineage: list[dict[str, str]],
    quality: list[dict[str, str]],
    times: list[dict[str, str]],
) -> dict[str, Any]:
    if len(lineage) != 72 or len(quality) != 1083 or len(times) != 720:
        raise ValueError("E2013_DENOMINATOR_MISMATCH")
    time_by_surface: defaultdict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    quality_by_surface: defaultdict[str, list[int]] = defaultdict(list)
    for number, row in enumerate(times, 1):
        time_by_surface[row["dataset_id"]].append((number, row))
    for number, row in enumerate(quality, 1):
        quality_by_surface[row["dataset_id"]].append(number)
    contracts = _model_contracts(repo_root, lineage)
    surfaces: list[dict[str, Any]] = []
    for ordinal, row in enumerate(lineage, 1):
        surface_id = row["dataset_id"]
        time_pairs = time_by_surface[surface_id]
        if len(time_pairs) != 10 or tuple(item[1]["canonical_timestamp"] for item in time_pairs) != CANONICAL_TIMESTAMPS:
            raise ValueError(f"E2013_TIMESTAMP_MATRIX_MISMATCH:{surface_id}")
        time_rows = [item[1] for item in time_pairs]
        materialization = _materialization(row)
        proof_level = "RECONSTRUCTED_NOT_PROVEN" if surface_id in RECONSTRUCTED_SURFACES else "UNKNOWN"
        if ordinal <= 35:
            locator_syntax, record_pointers = FILE_LOCATORS[surface_id]
            contract = None
            line_or_symbol = f"{row['path']}#{'|'.join(record_pointers)}"
        else:
            table = surface_id.removeprefix("postgres_")
            locator_syntax, record_pointers = "SQL_TABLE", (table,)
            contract = contracts[table]
            line_or_symbol = f"{contract['path']}:{contract['line']}:{table}"
        temporal_test, adversarial_test = _surface_test(surface_id)
        qrows = quality_by_surface[surface_id]
        sha256 = row["sha256"] if re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) else None
        surfaces.append(
            {
                "active_or_legacy": _lifecycle(surface_id, row["active_role"]),
                "adversarial_mutation_test": adversarial_test,
                "caller": row["producer"],
                "consumer": row["consumers"],
                "current_cutoff_field": _field_descriptor(time_rows, "feature_cutoff_at"),
                "current_join_rule": _surface_join_rule(surface_id),
                "current_temporal_test": temporal_test,
                "data_family": _data_family(surface_id),
                "decision_influence": _decision_influence(surface_id, row["active_role"]),
                "e2013_evidence_rows": {
                    "dataset_lineage_data_row": ordinal,
                    "dataset_lineage_physical_line": ordinal + 1,
                    "dataset_quality_data_rows": [qrows[0], qrows[-1]],
                    "dataset_quality_physical_lines": [qrows[0] + 1, qrows[-1] + 1],
                    "time_fields_data_rows": [time_pairs[0][0], time_pairs[-1][0]],
                    "time_fields_physical_lines": [time_pairs[0][0] + 1, time_pairs[-1][0] + 1],
                },
                "e2013_lineage": row,
                "event_time_field": _field_descriptor(time_rows, "kickoff_at"),
                "first_observation_field": _field_descriptor(time_rows, "data_available_at"),
                "grain": {
                    "logical_key": [] if row["logical_key"] == "NON VÉRIFIÉ" else row["logical_key"].split(";"),
                    "status": "UNSPECIFIED" if row["logical_key"] == "NON VÉRIFIÉ" else "E2013_DECLARED",
                },
                "historical_classification": proof_level,
                "historical_evidence_availability": {
                    "evidence_status": row["evidence_status"],
                    "materialization": materialization,
                    "materialization_detail": row["materialization"],
                    "sha256": sha256,
                },
                "ingestion_field": _field_descriptor(time_rows, "ingested_at"),
                "line_or_symbol": line_or_symbol,
                "proof_level": proof_level,
                "prospective_enforcement": _prospective_enforcement(surface_id),
                "receipt_bounded_proven": False,
                "receipt_contract_status": _receipt_contract_status(surface_id),
                "record_locator": {
                    "pointers": list(record_pointers),
                    "schema_contract": contract,
                    "syntax": locator_syntax,
                },
                "repo_path": row["path"],
                "required_repair": _required_repair(surface_id, materialization, proof_level),
                "severity": "P2" if _decision_influence(surface_id, row["active_role"]) == "CAN_INFLUENCE_FEATURE_OR_DECISION" else "P3",
                "source_publication_field": {
                    **_field_descriptor(time_rows, "provider_updated_at"),
                    "trusted_as_source_publication": False,
                },
                "status": "TEMPORAL_VALIDITY_NOT_PROVEN",
                "strict_point_in_time_proven": False,
                "surface_id": surface_id,
                "surface_ordinal": ordinal,
                "timestamp_mappings": [
                    {"csv_data_row": data_row, "timestamp_ordinal": index, **time_row}
                    for index, (data_row, time_row) in enumerate(time_pairs, 1)
                ],
            }
        )
    materialization_counts = Counter(item["historical_evidence_availability"]["materialization"] for item in surfaces)
    class_counts = Counter(item["historical_classification"] for item in surfaces)
    if materialization_counts != {"PRESENT": 27, "ABSENT": 8, "EXTERNAL_UNOBSERVED": 37}:
        raise ValueError(f"E2013_MATERIALIZATION_COUNTS_MISMATCH:{dict(materialization_counts)}")
    if class_counts != {"RECONSTRUCTED_NOT_PROVEN": 19, "UNKNOWN": 53}:
        raise ValueError(f"E2013_CLASSIFICATION_COUNTS_MISMATCH:{dict(class_counts)}")
    observation_class_counts: Counter[str] = Counter()
    for surface in surfaces:
        if surface["historical_evidence_availability"]["materialization"] != "PRESENT":
            continue
        rows_value = surface["e2013_lineage"].get("rows")
        if not isinstance(rows_value, str) or not rows_value.isdecimal():
            raise ValueError(
                f"E2013_MATERIALIZED_OBSERVATION_COUNT_INVALID:{surface['surface_id']}"
            )
        observation_class_counts[surface["historical_classification"]] += int(
            rows_value
        )
    if observation_class_counts != {
        "RECONSTRUCTED_NOT_PROVEN": 11_401,
        "UNKNOWN": 92_853,
    }:
        raise ValueError(
            "E2013_MATERIALIZED_OBSERVATION_COUNTS_MISMATCH:"
            f"{dict(observation_class_counts)}"
        )
    report = _base_report(
        "temporal-surface-inventory-v1",
        status="VERIFIED",
        verdict="ROBIN_TEMPORAL_SURFACE_INVENTORY_COMPLETE",
        evidence_status="PROUVÉ",
    )
    report.update(
        {
            "classification_policy": {
                "exclusive_historical_levels": [
                    "POINT_IN_TIME_PROVEN",
                    "RECEIPT_BOUNDED",
                    "RECONSTRUCTED_NOT_PROVEN",
                    "UNKNOWN",
                    "INVALID_AFTER_CUTOFF",
                ],
                "receipt_inference_forbidden_from": [
                    "filesystem_mtime",
                    "git_commit_time",
                    "event_at",
                    "provider_updated_at_without_receipt",
                    "row_order",
                    "file_order",
                ],
            },
            "counts": {
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
            },
            "denominator_status": "FIXED_E2013_SELECTION_NOT_EXHAUSTIVE_CURRENT_STORAGE",
            "observation_denominator": {
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
            },
            "limitations": [
                "E2013 is an immutable historical selection, not a fresh certification of revision 71833964.",
                "The 37 PostgreSQL surfaces were schema-inspected only; no database rows were observed.",
                "A PRESENT timestamp field is not promoted to a receipt-backed availability proof.",
            ],
            "sources": _audit_sources(),
            "surfaces": surfaces,
        }
    )
    return _with_content_hash(report)


def _build_temporal_contract(repo_root: Path) -> dict[str, Any]:
    report = _base_report(
        "temporal-contract-v1",
        status="PARTIAL",
        verdict="ROBIN_AVAILABILITY_TIME_CONTRACT_V1_READY",
    )
    report.update(
        {
            "asof_rule": {
                "admissible": "available_at <= cutoff_at",
                "ambiguous_tie": "ASOF_JOIN_AMBIGUOUS",
                "boundary_equal": "ADMISSIBLE",
                "late": "available_at > cutoff_at is forbidden",
                "missing": "POINT_IN_TIME_INPUT_NOT_PROVEN",
                "version": "available_at_lte_cutoff_payload_conflict_fail_closed_v1",
            },
            "availability_rule": "max(trusted source_published_at when present, robin_first_observed_at)",
            "contract_version": "robin-point-in-time-lineage-v1",
            "metric_semantics": {
                "brier_score": "mean over market selections of (p_k - y_k)^2",
                "calibration_error": "10-bin uniform expected calibration error over flattened one-vs-rest prediction-selection pairs, weighted by pair count",
                "coverage": "latest distinct scored frozen prediction heads divided by all frozen predictions in the segment",
                "log_loss": "negative natural logarithm of the settled-outcome probability, clipped to [1e-15, 1-1e-15]",
                "metric_definition_version": "PREQUENTIAL_METRIC_DEFINITION_V1_REPORT_BOUND",
                "missingness": "true missing flags divided by all supplied feature-family flags for frozen predictions",
                "persistence_limit": "metric rows do not yet persist metric_definition_version; the convention is report-bound and source-hashed, so cross-version aggregation remains forbidden",
                "reference_log_loss_delta": "mean challenger-minus-reference log loss over scores with a non-null exact reference edge",
            },
            "decision_invariants": [
                "feature_available_at <= cutoff_at",
                "odds_available_at <= cutoff_at",
                "model_available_at <= predicted_at",
                "predicted_at <= cutoff_at",
                "cutoff_at < kickoff_at",
                "decided_at >= predicted_at",
            ],
            "fail_closed": {
                "missing_required_receipt": "POINT_IN_TIME_INPUT_NOT_PROVEN",
                "point_in_time_status_default": "POINT_IN_TIME_NOT_PROVEN",
                "promotion": "NO_PROMOTION",
                "real_bet": "NO_BET_DEFAULT",
            },
            "proof_levels": [
                "RECEIPT_ATTESTED",
                "SOURCE_AND_RECEIPT_ATTESTED",
                "PROSPECTIVE_CAPTURED",
                "RECONSTRUCTED_NOT_PROVEN",
                "UNKNOWN",
                "INVALID_AFTER_CUTOFF",
            ],
            "prospective_status": "ROBIN_PROSPECTIVE_POINT_IN_TIME_FAIL_CLOSED_PARTIAL",
            "sources": [
                _repo_source(
                    repo_root,
                    "src/robin/temporal/lineage.py",
                    symbols=("SourceReceipt", "TemporalFeatureLineage", "TemporalDecisionLineage", "asof_select"),
                ),
                _repo_source(
                    repo_root,
                    "src/robin/prospective_observatory/prequential_metrics.py",
                    symbols=(
                        "score_prediction",
                        "aggregate_metrics",
                        "segmented_metrics",
                    ),
                ),
                _repo_source(repo_root, "configs/temporal/known-at-fact-contract-v1.json"),
            ],
            "storage_resolution": {
                "covered_paths": [
                    "prequential feature provenance JSON plus content-addressed R2 manifest",
                    "prequential odds snapshot identity resolved through prospective_odds_snapshots.receipt_id and immutable capture receipts",
                    "append-only shadow decision JSONL fields",
                    "content-addressed immutable historical dataset manifests",
                ],
                "legacy_or_unobserved_surfaces": "UNKNOWN_NOT_REVALIDATED",
                "reason": "The covered prospective closure fits existing JSON, R2, snapshot-receipt and JSONL storage paths; no new migration is required for that bounded scope.",
                "status": "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS",
            },
            "timestamp_model": {
                "available_at": "Conservative usable time derived only from an immutable receipt and optionally a trusted source publication time.",
                "computed_at": "Feature or prediction computation time; it cannot prove source availability.",
                "cutoff_at": "Decision or feature boundary.",
                "decided_at": "Decision emission time.",
                "event_at": "Business event time; never availability proof.",
                "robin_first_observed_at": "First receipt-attested time Robin obtained the payload.",
                "robin_ingested_at": "Time Robin persisted the payload.",
                "source_published_at": "Trusted only when its semantics and bytes are retained in the receipt.",
            },
        }
    )
    return _with_content_hash(report)


def _build_receipt_inventory(repo_root: Path) -> dict[str, Any]:
    report = _base_report(
        "source-receipt-inventory-v1",
        status="PARTIAL",
        verdict="ROBIN_SOURCE_RECEIPT_INVENTORY_COMPLETE_HISTORICAL_RECEIPTS_NOT_OBSERVED",
    )
    report.update(
        {
            "counts": {
                "e2013_surfaces": 72,
                "historical_receipt_objects_observed": 0,
                "historically_point_in_time_proven_surfaces": 0,
                "historically_receipt_bounded_surfaces": 0,
                "raw_observation_fk_schema_surfaces": 2,
                "receipt_anchor_schema_surfaces": 1,
                "receipt_child_fk_schema_surfaces": 6,
            },
            "historical_artifacts_not_receipts": [
                {
                    "path": "reports/closure/phase-c-v2-source-evidence/source-export-receipt-v2.json",
                    "reason": "zero-network deterministic export execution receipt, not a source-data receipt",
                },
                {
                    "path": "reports/closure/phase-c-v2-source-evidence/source-evidence-manifest-v2.json",
                    "reason": "hash-pinned reconstruction whose availability is explicitly proxy-based",
                },
                {
                    "path": "reports/evidence/e2/e2-selection-manifest-v1.json",
                    "reason": "receipt hashes and object keys are references without local receipt bytes or response_received_at",
                },
            ],
            "inference_policy": {
                "forbidden": ["filesystem_mtime", "git_time", "event_time", "kickoff_time", "record_order"],
                "rule": "No robin_first_observed_at may be synthesized from these values.",
            },
            "limitations": [
                "Repository-backed tests prove bounded local receipt bytes, not active production capture.",
                "The E2013 historical receipt-object denominator remains zero after the prospective repair.",
            ],
            "receipt_contract": {
                "append_only": True,
                "content_addressed": True,
                "fields": [
                    "receipt_id",
                    "source_name",
                    "request_identity",
                    "payload_sha256",
                    "source_published_at",
                    "robin_first_observed_at",
                    "robin_ingested_at",
                    "capture_code_revision",
                    "storage_identity",
                    "availability_status",
                    "supersedes_receipt_id",
                ],
                "repository_bytes_reverified_before_forecast": True,
                "self_declared_sha_looking_mapping_rejected": True,
                "utc_aware": True,
            },
            "schema_capabilities": [
                {"surface_id": item, "status": _receipt_contract_status(item)}
                for item in sorted(RAW_OBSERVATION_LINKED | RECEIPT_ANCHORS | RECEIPT_CHILDREN)
            ],
            "sources": [
                *_audit_sources(),
                _repo_source(repo_root, "src/robin/temporal/lineage.py", symbols=("SourceReceipt",)),
                _repo_source(
                    repo_root,
                    "src/robin/prospective_observatory/feature_snapshots.py",
                    symbols=(
                        "persist_source_receipt",
                        "verify_source_receipt_artifact",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "src/robin/prospective_observatory/prequential_contracts.py",
                    symbols=("source_receipt_from_provenance",),
                ),
                _repo_source(repo_root, "src/robin/storage/models.py", symbols=("raw_observations", "fixtures", "bookmaker_quotes")),
                _repo_source(repo_root, "src/robin/storage/prospective_models.py", symbols=("capture_receipts",)),
                _repo_source(repo_root, "migrations/versions/0009_jalon12_prospective_observatory.py"),
                *[
                    _repo_source(
                        repo_root,
                        path,
                        symbols=tuple(
                            name
                            for candidate_path, name in REPOSITORY_RECEIPT_TESTS
                            if candidate_path == path
                        ),
                    )
                    for path in dict.fromkeys(
                        candidate_path
                        for candidate_path, _ in REPOSITORY_RECEIPT_TESTS
                    )
                ],
            ],
            "storage_status": "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS",
        }
    )
    return _with_content_hash(report)


def _build_asof_audit(repo_root: Path) -> dict[str, Any]:
    paths = [
        {
            "path": "src/robin/temporal/lineage.py",
            "symbol": "asof_select",
            "rule": "latest receipt-backed available_at <= cutoff; conflicting payloads at the latest time fail closed",
            "status": "PASS_BOUNDED_LAB",
        },
        {
            "path": "src/robin/prospective_observatory/prequential_contracts.py",
            "symbol": "FeatureSnapshot.__post_init__",
            "rule": "each non-missing family requires receipt and payload identities and available_at <= cutoff",
            "status": "PASS_BOUNDED_LAB",
        },
        {
            "path": "scripts/run_prequential_learning_factory.py",
            "symbol": "_latest_fixtures",
            "rule": "registered_at <= as_of with contradiction detection",
            "status": "PARTIAL_TIMESTAMP_NOT_RECEIPT_BACKED",
        },
        {
            "path": "scripts/run_prequential_learning_factory.py",
            "symbol": "_current_models",
            "rule": "created_at <= cutoff plus exact feature contract hash",
            "status": "PARTIAL_MODEL_ARTIFACT_RECEIPT_NOT_PERSISTED",
        },
        {
            "path": "src/robin/shadow/decision.py",
            "symbol": "decide_shadow_bet",
            "rule": "POINT_IN_TIME_VALID requires complete lineage persisted in append-only JSONL; missing lineage rejects acceptance",
            "status": "PARTIAL_ACTIVE_RUNTIME_RECEIPT_BINDING_NOT_PROVEN",
        },
        {
            "path": "scripts/run_shadow_pipeline.py",
            "symbol": "collect_odds/pre_match_shadow",
            "rule": "active runtime end-to-end receipt-backed as-of join",
            "status": "NOT_PROVEN",
        },
        {
            "path": "src/robin/historical/features.py",
            "symbol": "build_team_feature_rows",
            "rule": "historical rolling inputs receipt-backed at cutoff",
            "status": "NOT_PROVEN",
        },
    ]
    report = _base_report(
        "asof-join-audit-v1",
        status="PARTIAL",
        verdict="ROBIN_ASOF_JOIN_FAIL_CLOSED",
    )
    report.update(
        {
            "audited_paths": paths,
            "boundary_contract": {
                "available_at_equal_cutoff": "ADMISSIBLE",
                "available_at_missing": "POINT_IN_TIME_INPUT_NOT_PROVEN",
                "available_at_post_cutoff": "EXCLUDED",
                "contradictory_latest_payloads": "ASOF_JOIN_AMBIGUOUS",
            },
            "counts": dict(sorted(Counter(item["status"] for item in paths).items())),
            "limitations": [
                "The canonical primitive is proven only by bounded local tests.",
                "Not every active historical, shadow and rolling-window caller has been migrated to the primitive.",
                "No production runtime trace or database snapshot was used.",
            ],
            "sources": [
                _repo_source(repo_root, item["path"], symbols=(item["symbol"],))
                for item in paths
            ],
            "storage_status": "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS",
        }
    )
    return _with_content_hash(report)


def _symbol_span(repo_root: Path, path: str, qualified_name: str) -> dict[str, Any]:
    source_path = repo_root / path
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    parts = qualified_name.split(".")
    nodes: list[ast.AST] = list(tree.body)
    selected: ast.AST | None = None
    for part in parts:
        selected = next(
            (
                node
                for node in nodes
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == part
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"REPORT_SYMBOL_MISSING:{path}:{qualified_name}")
        nodes = list(getattr(selected, "body", ()))
    if not isinstance(selected, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError(f"REPORT_SYMBOL_MISSING:{path}:{qualified_name}")
    end = selected.end_lineno or selected.lineno
    return {
        "first_line": selected.lineno,
        "last_line": end,
        "loc": end - selected.lineno + 1,
        "path": path,
        "symbol": qualified_name,
    }


def _test_locations(
    repo_root: Path,
    paths: tuple[str, ...],
) -> dict[str, str]:
    locations: dict[str, str] = {}
    for path in paths:
        tree = ast.parse((repo_root / path).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            previous = locations.get(node.name)
            if previous is not None and previous != path:
                raise ValueError(f"TEMPORAL_TEST_NAME_AMBIGUOUS:{node.name}")
            locations[node.name] = path
    return locations


def _build_test_coverage(repo_root: Path) -> dict[str, Any]:
    test_path = repo_root / "tests/temporal/test_point_in_time_lineage_v1.py"
    test_names = {
        node.name
        for node in ast.parse(test_path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }
    missing = [name for name, _, _ in MANDATORY_TESTS if name not in test_names]
    if missing:
        raise ValueError(f"MANDATORY_TEMPORAL_TEST_MISSING:{','.join(missing)}")
    repository_test_paths = tuple(dict.fromkeys(path for path, _ in REPOSITORY_RECEIPT_TESTS))
    repository_test_locations = _test_locations(repo_root, repository_test_paths)
    missing_repository_tests = [
        name
        for path, name in REPOSITORY_RECEIPT_TESTS
        if repository_test_locations.get(name) != path
    ]
    if missing_repository_tests:
        raise ValueError(
            "REPOSITORY_RECEIPT_TEST_MISSING:"
            + ",".join(missing_repository_tests)
        )
    covered_specs = (
        ("src/robin/temporal/lineage.py", "asof_select"),
        ("src/robin/prospective_observatory/feature_snapshots.py", "freeze_feature_snapshot"),
        ("scripts/run_prequential_learning_factory.py", "_latest_fixtures"),
        ("src/robin/prospective_observatory/prequential_factory.py", "PrequentialLearningFactory.forecast"),
        ("src/robin/shadow/decision.py", "decide_shadow_bet"),
        ("src/robin/historical/features.py", "build_team_feature_rows"),
        ("src/robin/historical/scientific_arena.py", "_rolling_goal_rates"),
    )
    uncovered_specs = (
        ("src/robin/historical/dataset_factory.py", "build_api_team_pre_match"),
        ("src/robin/historical/dataset_factory.py", "build_player_feature_datasets"),
        ("src/robin/backtesting/v3.py", "run_backtest"),
        ("scripts/run_shadow_pipeline.py", "collect_odds"),
        ("scripts/run_shadow_pipeline.py", "pre_match_shadow"),
        ("scripts/run_shadow_pipeline.py", "post_match_settlement"),
        ("scripts/run_historical_pipeline.py", "build_observed_forecast"),
        ("scripts/run_historical_pipeline.py", "command_features"),
        ("scripts/run_historical_pipeline.py", "command_train"),
        ("scripts/run_historical_pipeline.py", "command_backtest"),
    )
    covered = [_symbol_span(repo_root, *spec) for spec in covered_specs]
    uncovered = [_symbol_span(repo_root, *spec) for spec in uncovered_specs]
    tests = [
        {
            "category": category,
            "component": component,
            "path": "tests/temporal/test_point_in_time_lineage_v1.py",
            "status": "PASS_IN_TARGETED_SUITE",
            "test": name,
        }
        for name, category, component in MANDATORY_TESTS
    ]
    report = _base_report(
        "temporal-test-coverage-v1",
        status="PARTIAL",
        verdict="ROBIN_TEMPORAL_TEST_COVERAGE_PARTIAL",
    )
    report.update(
        {
            "feature_builder_coverage": {
                "covered_decision_relevant_loc": sum(item["loc"] for item in covered),
                "covered_symbols": covered,
                "method": "AST function or method span for the bounded audited symbol list; not global line coverage",
                "uncovered_decision_relevant_loc": sum(item["loc"] for item in uncovered),
                "uncovered_symbols": uncovered,
            },
            "limitations": [
                "A declarative flag test is not counted as adversarial value mutation evidence.",
                "The initial five-test red output is sealed separately as LOOP55:E0001 and is not part of the historical E2013 audit root.",
                "Covered LOC is a bounded symbol inventory and is not point-in-time proof by itself.",
                "This is not an exhaustive keyword inventory of every repository test mentioning lookahead, leakage, future, cutoff, as_of, observed_at, available_at, stale, late or training_cutoff.",
            ],
            "red_phase_evidence": "LOOP55:E0001",
            "repository_receipt_tests": [
                {
                    "path": path,
                    "status": "PASS_IN_TARGETED_SUITE",
                    "test": name,
                }
                for path, name in REPOSITORY_RECEIPT_TESTS
            ],
            "sources": [
                _repo_source(
                    repo_root,
                    "tests/temporal/test_point_in_time_lineage_v1.py",
                    symbols=(
                        *(name for name, _, _ in MANDATORY_TESTS),
                        *(
                            name
                            for path, name in REPOSITORY_RECEIPT_TESTS
                            if path
                            == "tests/temporal/test_point_in_time_lineage_v1.py"
                        ),
                    ),
                ),
                _repo_source(repo_root, "tests/jalon7/test_scientific_arena.py", symbols=("test_equal_kickoff_score_rates_do_not_depend_on_peer_result",)),
                *[
                    _repo_source(
                        repo_root,
                        path,
                        symbols=tuple(
                            name
                            for candidate_path, name in REPOSITORY_RECEIPT_TESTS
                            if candidate_path == path
                        ),
                    )
                    for path in repository_test_paths
                    if path != "tests/temporal/test_point_in_time_lineage_v1.py"
                ],
            ],
            "summary": {
                "adversarial_value_mutation_tests": 2,
                "boundary_tests": 2,
                "immutability_alias_mutation_tests": 1,
                "mandatory_tests": 5,
                "mandatory_tests_present": 5,
                "mutation_matrix_cases_passed": 25,
                "repository_receipt_boundary_tests": len(REPOSITORY_RECEIPT_TESTS),
                "uncovered_active_symbols": len(uncovered),
            },
            "tests": tests,
        }
    )
    return _with_content_hash(report)


def _build_future_mutation_matrix(repo_root: Path) -> dict[str, Any]:
    test_paths = tuple(
        dict.fromkeys(
            (
                "tests/temporal/test_point_in_time_lineage_v1.py",
                OUT_OF_ORDER_INGESTION_TEST[0],
            )
        )
    )
    defined_tests = _test_locations(repo_root, test_paths)
    missing_tests = sorted(
        {
            str(test)
            for _, _, test in MUTATION_CASES
            if test is not None and test not in defined_tests
        }
    )
    if missing_tests:
        raise ValueError(f"FUTURE_MUTATION_TEST_MISSING:{','.join(missing_tests)}")
    records = [
        {
            "case_id": f"PIT-MUTATION-{index:02d}",
            "mutation": mutation,
            "status": status,
            "test": test,
            "test_path": defined_tests.get(str(test)) if test is not None else None,
        }
        for index, (mutation, status, test) in enumerate(MUTATION_CASES, 1)
    ]
    counts = Counter(record["status"] for record in records)
    report = _base_report(
        "future-mutation-matrix-v1",
        status="PARTIAL",
        verdict="ADVERSARIAL_FUTURE_MUTATION_INVARIANCE_PARTIAL",
    )
    report.update(
        {
            "counts": {
                "not_covered": counts["NOT_COVERED"],
                "partial": counts["PARTIAL"],
                "pass": counts["PASS"],
                "required_cases": len(records),
            },
            "matrix_execution_status": (
                "PASS" if counts["PASS"] == len(records) else "PARTIAL"
            ),
            "limitations": [
                "PASS applies only to the named bounded test and component.",
                "All 25 required mutation classes are executed, but this is not coverage of every decision-relevant repository symbol.",
                "The calibration case covers the current model-bound calibration identity; no independently executed calibrator exists on the covered prospective path.",
                "The out-of-order ingestion case is the explicit post-cutoff ingestion branch of its named repository-backed receipt test.",
            ],
            "records": records,
            "sources": [
                *[
                    _repo_source(
                        repo_root,
                        path,
                        symbols=tuple(
                            sorted(
                                name
                                for name, location in defined_tests.items()
                                if location == path
                            )
                        ),
                    )
                    for path in test_paths
                ],
            ],
        }
    )
    return _with_content_hash(report)


def _review_questions() -> list[dict[str, Any]]:
    questions = (
        ("Can a late-arriving pre-cutoff event influence an earlier decision?", "NO_IN_COVERED_PATHS_GLOBAL_PATH_PARTIAL", MANDATORY_TESTS[0][0]),
        (
            "Can a future value mutation change a past feature hash?",
            "NO_IN_COVERED_TEAM_FEATURE_BUILDER",
            f"{FUTURE_ROW_VALUE_MUTATION_TEST[0]}::{FUTURE_ROW_VALUE_MUTATION_TEST[1]}",
        ),
        ("Can a future value mutation change a past decision hash?", "NO_IN_COVERED_ASOF_SHADOW_TRACE", MANDATORY_TESTS[2][0]),
        ("Can event_at substitute for available_at?", "NO_BY_TEMPORAL_CONTRACT", "src/robin/temporal/lineage.py"),
        (
            "Can a self-declared observed_at pass without a receipt?",
            "NO_IN_BOUNDED_REPOSITORY_BACKED_PROVENANCE_GLOBAL_RUNTIME_PARTIAL",
            f"{SELF_DECLARED_RECEIPT_TEST[0]}::{SELF_DECLARED_RECEIPT_TEST[1]}",
        ),
        (
            "Can an unknown availability input be used with only a warning?",
            "NO_IN_BOUNDED_PREQUENTIAL_GATE_CONTRACT_GLOBAL_RUNTIME_PARTIAL",
            f"{UNKNOWN_AVAILABILITY_GATE_TEST[0]}::{UNKNOWN_AVAILABILITY_GATE_TEST[1]}",
        ),
        ("Can a model created after cutoff be used?", "NO_IN_COVERED_PREQUENTIAL_FORECAST", MANDATORY_TESTS[4][0]),
        ("Can an odds snapshot observed after cutoff be selected?", "NO_IN_COVERED_ASOF_SELECTION", MANDATORY_TESTS[2][0]),
        ("Can a historical reconstructed timestamp be labelled proven?", "NO_BY_E2013_CLASSIFICATION_POLICY", "AUDIT:E2013"),
        ("Can a prospective valid contract falsely revalidate all history?", "NO_BY_SEPARATE_HISTORICAL_AND_PROSPECTIVE_VERDICTS", "AUDIT:E2013"),
    )
    return [
        {
            "answer": "NO",
            "evidence_ref": evidence,
            "question": question,
            "question_id": f"Q{index}",
            "scope": scope,
        }
        for index, (question, scope, evidence) in enumerate(questions, 1)
    ]


def _build_decision_trace(repo_root: Path) -> dict[str, Any]:
    report = _base_report(
        "decision-lineage-trace-v1",
        status="PARTIAL",
        verdict="PRODUCTION_DECISION_PATH_POINT_IN_TIME_STILL_NOT_PROVEN",
    )
    report.update(
        {
            "bounded_trace": {
                "decision": "shadow decision hash includes supplied temporal lineage identities, while unverified runtime lineage remains POINT_IN_TIME_NOT_PROVEN with zero stake",
                "feature": "frozen snapshot reconstructs a content-addressed receipt for every non-missing family; forecast rereads repository bytes",
                "model": "created_at and training_cutoff are bounded before forecast",
                "odds": "asof_select excludes receipt-backed odds available after cutoff",
                "scope": "LOCAL_DETERMINISTIC_TEST_ONLY",
                "source": "bounded repository-backed receipts plus raw R2 reread",
                "status": "PASS_BOUNDED_LAB",
            },
            "devig": {
                "effective_method_recorded": True,
                "global_method_selected": False,
                "status": "DEVIG_PROTOCOL_CONFLICT",
            },
            "durability": {
                "prequential_feature_provenance_json_and_r2": True,
                "prequential_odds_snapshot_receipt_chain": True,
                "production_runtime_trace": False,
                "shadow_decision_append_only_jsonl": True,
                "status": "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS",
            },
            "review_questions": _review_questions(),
            "review_summary": {"answers_no": 10, "questions": 10},
            "limitations": [
                "Q5 is a bounded fail-closed result against repository-backed and valid-looking self-declared provenance; it is not positive production PIT proof.",
                "Self-declared shadow scalars still produce no bet and POINT_IN_TIME_NOT_PROVEN until an active runtime binds repository-verified receipts.",
            ],
            "sources": [
                _repo_source(repo_root, "src/robin/temporal/lineage.py", symbols=("TemporalDecisionLineage",)),
                _repo_source(repo_root, "src/robin/shadow/decision.py", symbols=("ShadowDecision", "decide_shadow_bet")),
                _repo_source(repo_root, "src/robin/prospective_observatory/prequential_contracts.py", symbols=("FeatureSnapshot",)),
                _repo_source(repo_root, "src/robin/prospective_observatory/prequential_factory.py", symbols=("PrequentialLearningFactory.forecast",)),
                _repo_source(repo_root, "tests/temporal/test_point_in_time_lineage_v1.py"),
                _repo_source(
                    repo_root,
                    "tests/jalon14/test_prequential_factory.py",
                    symbols=tuple(
                        dict.fromkeys(
                            (
                                *(
                                    name
                                    for path, name in REPOSITORY_RECEIPT_TESTS
                                    if path
                                    == "tests/jalon14/test_prequential_factory.py"
                                ),
                                UNKNOWN_AVAILABILITY_GATE_TEST[1],
                            )
                        )
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon14/test_prequential_pit_closure.py",
                    symbols=tuple(
                        name
                        for path, name in REPOSITORY_RECEIPT_TESTS
                        if path
                        == "tests/jalon14/test_prequential_pit_closure.py"
                    ),
                ),
            ],
        }
    )
    return _with_content_hash(report)


def _load_loop54_replay(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "reports/scientific-truth/historical-truth-replay-v1.json"
    actual = _sha256_file(path)
    if actual != LOOP54_REPLAY_SHA256:
        raise ValueError(f"LOOP54_REPLAY_HASH_MISMATCH:{actual}")
    document = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    _verify_content_hash(document)
    if len(document.get("results", [])) != 15 or document.get("source_inventory", {}).get("physical_occurrences") != 45:
        raise ValueError("LOOP54_REPLAY_DENOMINATOR_MISMATCH")
    return document


def _historical_rows(loop54: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "cutoff_at": None,
            "devig_effective_method": result["original"].get("devig_method", "UNKNOWN"),
            "devig_requested_method": "UNKNOWN",
            "feature_hash_new": None,
            "feature_hash_old": None,
            "input_receipt_hashes": [],
            "legacy_status": "LEGACY_UNVERSIONED_NOT_CANONICAL",
            "logical_result_id": result["logical_result_id"],
            "maximum_input_available_at": None,
            "new_decision": None,
            "old_decision": None,
            "physical_occurrences": len(result["source_occurrences"]),
            "point_in_time_status": "POINT_IN_TIME_UNREPLAYABLE",
            "reason": "Observation-level inputs, cutoffs and immutable receipt times were not published.",
            "replayability": "UNREPLAYABLE",
            "source_result_hash": result["repair_projection_sha256"],
            "strategy": result["strategy"],
            "temporal_classification": "UNKNOWN",
        }
        for result in loop54["results"]
    ]


def _build_historical_replay(repo_root: Path, loop54: dict[str, Any]) -> dict[str, Any]:
    rows = _historical_rows(loop54)
    report = _base_report(
        "historical-point-in-time-replay-v1",
        status="PARTIAL",
        verdict="ROBIN_HISTORICAL_POINT_IN_TIME_REPLAY_NOT_POSSIBLE",
    )
    report.update(
        {
            "devig_status": "DEVIG_PROTOCOL_CONFLICT",
            "limitations": [
                "No decision is replayed from a summary-only result.",
                "The formula replay from LOOP54 corrected ROI semantics but did not publish per-decision inputs or receipts.",
                "The 0-of-15 replayable subset must not be presented as representative evidence.",
            ],
            "results": rows,
            "sources": [
                {
                    "evidence_status": "PROUVÉ",
                    "path": "reports/scientific-truth/historical-truth-replay-v1.json",
                    "sha256": LOOP54_REPLAY_SHA256,
                },
                *_audit_sources(),
            ],
            "summary": {
                "full_lineage_replay": 0,
                "logical_results": 15,
                "physical_occurrences": 45,
                "point_in_time_replay_complete": 0,
                "point_in_time_replay_partial": 0,
                "point_in_time_unreplayable": 15,
                "receipt_bounded_replay": 0,
                "unreplayable": 15,
            },
        }
    )
    return _with_content_hash(report)


def _build_invalidation_ledger(loop54: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, result in enumerate(loop54["results"], 1):
        record = {
            "cutoff_at": None,
            "logical_result_id": result["logical_result_id"],
            "previous_record_hash": previous,
            "reason": "No observation-level receipt lineage proves that every input was available before its decision cutoff.",
            "receipt_hashes": [],
            "relation": "TEMPORAL_VALIDITY_NOT_PROVEN",
            "replacement_result_hash": None,
            "sequence": sequence,
            "source_result_hash": result["repair_projection_sha256"],
            "status": "POINT_IN_TIME_UNREPLAYABLE",
            "source_identity_status": "LEGACY_UNVERSIONED_NOT_CANONICAL",
            "temporal_contract_version": "robin-point-in-time-lineage-v1",
        }
        record["record_hash"] = _sha256_bytes(_canonical_bytes(record))
        previous = record["record_hash"]
        records.append(record)
    report = _base_report(
        "temporal-invalidation-ledger-v1",
        status="VERIFIED",
        verdict="ROBIN_TEMPORAL_INVALIDATION_LEDGER_APPEND_ONLY",
        evidence_status="PROUVÉ",
    )
    report.update(
        {
            "append_only": True,
            "chain_tip": previous,
            "counts": {
                "logical_results": 15,
                "physical_occurrences": 45,
                "records": 15,
                "temporal_validity_not_proven": 15,
            },
            "grain": "ONE_RELATION_PER_LOOP54_LOGICAL_RESULT",
            "records": records,
            "source": {
                "path": "reports/scientific-truth/historical-truth-replay-v1.json",
                "sha256": LOOP54_REPLAY_SHA256,
            },
        }
    )
    return _with_content_hash(report)


def _build_defect_inventory(repo_root: Path) -> dict[str, Any]:
    defects: list[dict[str, Any]] = [
        {
            "defect_id": "PIT55-001",
            "evidence_refs": ["AUDIT:E2013"],
            "required_repair": "Capture immutable receipt-backed availability prospectively; retain historical UNKNOWN/RECONSTRUCTED classifications.",
            "severity": "P2",
            "status": "OPEN_IRREVERSIBLE_HISTORICAL_GAP",
            "summary": "All 72 E2013 surfaces lack sufficient historical point-in-time proof.",
        },
        {
            "defect_id": "PIT55-002",
            "evidence_refs": ["src/robin/shadow/decision.py:310"],
            "required_repair": "Route every active shadow caller through complete receipt-backed lineage and retain the existing append-only JSONL regression.",
            "severity": "P2",
            "status": "OPEN_ACTIVE_PATH_COVERAGE_GAP",
            "summary": "ShadowDecision can persist cutoff, receipt, model and feature lineage in append-only JSONL, but the active runtime path is not proven end to end.",
        },
        {
            "defect_id": "PIT55-003",
            "evidence_refs": ["scripts/run_prequential_learning_factory.py:_odds_evidence"],
            "required_repair": "Retain the tested snapshot-to-capture-receipt and R2 verification chain; add full prediction replay coverage before a global claim.",
            "severity": "P2",
            "status": "OPEN_END_TO_END_REPLAY_COVERAGE_GAP",
            "summary": "The covered prequential path resolves odds_snapshot_id through receipt-linked snapshots and immutable R2 evidence, but global replay remains unproven.",
        },
        {
            "defect_id": "PIT55-004",
            "evidence_refs": ["reports/temporal-lineage/temporal-test-coverage-v1.json"],
            "required_repair": "Add value-mutation tests for the remaining active dataset builders, backtest orchestration and full shadow runtime paths before any promotion claim.",
            "severity": "P2",
            "status": "OPEN_COVERAGE_GAP",
            "summary": "Historical feature and rolling-rate builders are covered, but other decision-relevant dataset, backtest and shadow runtime symbols remain outside the bounded mutation proof.",
        },
        {
            "defect_id": "PIT55-005",
            "evidence_refs": ["reports/temporal-lineage/future-mutation-matrix-v1.json"],
            "required_repair": "Bind and verify the calibration artifact receipt in an observed active runtime trace before any global point-in-time claim; retain the bounded model-bundle mutation regression.",
            "severity": "P2",
            "status": "OPEN_ACTIVE_RUNTIME_CALIBRATION_RECEIPT_GAP",
            "summary": "The bounded model-bundle test rejects calibration identity created after cutoff, but no observed production runtime proves its calibration artifact receipt and availability.",
        },
        {
            "defect_id": "PIT55-013",
            "evidence_refs": [
                "src/robin/prospective_observatory/prequential_metrics.py",
                "reports/temporal-lineage/temporal-contract-v1.json",
            ],
            "required_repair": "Persist an exact metric_definition_version with metric rows before any aggregation across code revisions; retain the report-bound formulas meanwhile.",
            "severity": "P2",
            "status": "OPEN_METRIC_DEFINITION_PERSISTENCE_GAP",
            "summary": "Log-loss, normalized Brier, flattened 10-bin ECE, coverage, missingness and reference-delta formulas are source-hashed and documented, but durable metric rows do not carry their definition version.",
        },
        {
            "defect_id": "PIT55-014",
            "evidence_refs": [
                "src/robin/historical/dataset_factory.py::build_player_feature_datasets",
            ],
            "required_repair": "Batch every player-history update sharing the same kickoff before exposing any peer row to the next fixture, then add equal-kickoff permutation tests.",
            "severity": "P2",
            "status": "OPEN_HISTORICAL_EQUAL_KICKOFF_BATCHING_GAP",
            "summary": "Player feature datasets still update fixture-by-fixture at an equal kickoff; outputs remain TEMPORAL_VALIDITY_NOT_PROVEN and the builder is not counted as PIT-covered.",
        },
        {
            "defect_id": "PIT55-015",
            "evidence_refs": [
                "scripts/run_historical_pipeline.py::_dataset_rows",
                "scripts/run_historical_pipeline.py::command_backtest",
            ],
            "required_repair": "Bind the loaded dataset snapshot hash to the model and command input in one immutable read transaction; reject a current-pointer change before backtest/model-lab/arena consumption.",
            "severity": "P2",
            "status": "OPEN_HISTORICAL_POINTER_BINDING_GAP",
            "summary": "Historical current-manifest pointers and rows can be read at different instants; outputs remain non-promotable, but exact dataset-to-model replay is not proven.",
        },
        {
            "defect_id": "PIT55-006",
            "evidence_refs": [MANDATORY_TESTS[0][0]],
            "required_repair": "None in the covered selector; preserve regression.",
            "severity": "P1",
            "status": "RESOLVED_IN_CODE",
            "summary": "Late fixture revision could otherwise replace the pre-cutoff fixture version.",
        },
        {
            "defect_id": "PIT55-007",
            "evidence_refs": [
                f"{path}::{name}" for path, name in REPOSITORY_RECEIPT_TESTS
            ],
            "required_repair": "Preserve the repository-backed receipt, mapping-tamper, late-ingestion and byte-reread regressions; obtain an observed active-runtime trace before any global claim.",
            "severity": "P1",
            "status": "RESOLVED_BOUNDED_REPOSITORY_RECEIPT_FAIL_CLOSED",
            "summary": "Valid-looking self-declared mappings, tampered receipt identities, post-cutoff ingestion and missing repository bytes fail closed in bounded tests; this is not positive production PIT proof.",
        },
        {
            "defect_id": "PIT55-008",
            "evidence_refs": [MANDATORY_TESTS[4][0]],
            "required_repair": "None in the covered forecast; preserve regression.",
            "severity": "P1",
            "status": "RESOLVED_IN_CODE",
            "summary": "A model created after cutoff could otherwise be selected.",
        },
        {
            "defect_id": "PIT55-009",
            "evidence_refs": [
                "tests/jalon2/test_decisions_pipeline_workflows.py::test_shadow_self_declared_temporal_scalars_never_enable_stake",
                "tests/jalon6/test_scientific_truth_kernel_v1.py::test_declared_method_has_probability_parity_but_shadow_fails_closed",
            ],
            "required_repair": "Preserve the no-bet regressions and append-only JSONL lineage; bind the active shadow runtime to repository-verified receipts before any PIT-valid claim.",
            "severity": "P1",
            "status": "RESOLVED_FAIL_CLOSED_NO_PIT_PROOF",
            "summary": "Self-declared shadow scalars cannot authorize a stake: the decision remains rejected, zero-stake and POINT_IN_TIME_NOT_PROVEN; this closes betting fail-open, not PIT provenance.",
        },
        {
            "defect_id": "PIT55-010",
            "evidence_refs": [
                "tests/jalon5/test_deep_data_factory.py::test_normalisation_ne_transforme_pas_absence_en_zero",
                "tests/jalon5/test_deep_data_factory.py::test_legacy_rows_and_closing_odds_are_not_labeled_point_in_time_safe",
                "tests/jalon6/test_readiness_gates.py::test_eligible_unreceipted_data_stays_blocked_by_temporality",
            ],
            "required_repair": "Preserve UNKNOWN/TEMPORAL_VALIDITY_NOT_PROVEN classifications and the promotion gates; capture immutable receipts prospectively.",
            "severity": "P1",
            "status": "RESOLVED_FAIL_CLOSED_NO_HISTORICAL_RECLASSIFICATION",
            "summary": "Normalization, endpoint availability and closing odds cannot turn unreceipted legacy rows into point-in-time-safe inputs; otherwise apparently eligible data could bypass temporality gates.",
        },
        {
            "defect_id": "PIT55-011",
            "evidence_refs": [
                "tests/jalon8/test_external_validation.py::test_multileague_gates_measure_only_observed_coverage",
                "tests/jalon8/test_external_validation.py::test_preseason_package_rejects_ready_claim_without_receipt_repository_proof",
                "tests/jalon8/test_external_validation.py::test_full_external_run_is_cache_only_and_gate_honest",
            ],
            "required_repair": "Preserve research-only/BLOCKED_BY_TEMPORALITY status and require repository receipt proof before any external-ready package claim.",
            "severity": "P1",
            "status": "RESOLVED_FAIL_CLOSED_NO_EXTERNAL_READY_CLAIM",
            "summary": "External coverage flags cannot make unreceipted datasets or predictions ready: the package remains WAITING with no model versions even when declarative gates say ready.",
        },
        {
            "defect_id": "PIT55-012",
            "evidence_refs": [
                "tests/jalon5/test_deep_data_factory.py::test_cockpit_player_families_require_repository_verified_receipts",
            ],
            "required_repair": "Preserve repository-receipt requirements for cockpit squad and player families; do not infer PIT safety from season coverage.",
            "severity": "P1",
            "status": "RESOLVED_FAIL_CLOSED_NO_COCKPIT_PIT_CLAIM",
            "summary": "Squad and player cockpit families remain TEMPORAL_VALIDITY_NOT_PROVEN and BLOCKED_BY_TEMPORALITY even with two seasons of coverage unless repository receipts are verified.",
        },
    ]
    open_defects = [item for item in defects if item["status"].startswith("OPEN_")]
    report = _base_report(
        "temporal-defect-inventory-v1",
        status="PARTIAL",
        verdict="TEMPORAL_DEFECTS_P0_P1_CLOSED_P2_HISTORY_AND_COVERAGE_OPEN",
    )
    report.update(
        {
            "counts": {
                "open_p0": 0,
                "open_p1": 0,
                "open_p2": sum(item["severity"] == "P2" for item in open_defects),
                "resolved_p1": sum(item["severity"] == "P1" for item in defects if item["status"].startswith("RESOLVED_")),
                "total": len(defects),
            },
            "defects": defects,
            "limitations": [
                "RESOLVED_FAIL_CLOSED statuses close named fail-open regressions only; they do not reclassify legacy data or prove production PIT capture.",
                "Eight P2 evidence, coverage, formula-version, equal-kickoff, pointer-binding and irreversible-history gaps remain open.",
            ],
            "sources": [
                *_audit_sources(),
                _repo_source(repo_root, "src/robin/shadow/decision.py", symbols=("DecisionJournal",)),
                _repo_source(
                    repo_root,
                    "src/robin/prospective_observatory/feature_snapshots.py",
                    symbols=(
                        "freeze_feature_snapshot",
                        "persist_source_receipt",
                        "verify_feature_snapshot_artifact",
                        "verify_source_receipt_artifact",
                    ),
                ),
                _repo_source(repo_root, "scripts/run_prequential_learning_factory.py", symbols=("_odds_evidence",)),
                _repo_source(repo_root, "tests/temporal/test_point_in_time_lineage_v1.py"),
                _repo_source(
                    repo_root,
                    "tests/jalon14/test_prequential_factory.py",
                    symbols=(
                        "test_self_declared_receipt_and_late_ingestion_fail_closed",
                        "test_forecast_reverifies_source_receipt_bytes",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon14/test_prequential_pit_closure.py",
                    symbols=(
                        "test_odds_requires_receipt_index_window_r2_and_ties_fail_closed",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon2/test_decisions_pipeline_workflows.py",
                    symbols=(
                        "test_shadow_self_declared_temporal_scalars_never_enable_stake",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon5/test_deep_data_factory.py",
                    symbols=(
                        "test_normalisation_ne_transforme_pas_absence_en_zero",
                        "test_legacy_rows_and_closing_odds_are_not_labeled_point_in_time_safe",
                        "test_cockpit_player_families_require_repository_verified_receipts",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon6/test_readiness_gates.py",
                    symbols=(
                        "test_eligible_unreceipted_data_stays_blocked_by_temporality",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    symbols=(
                        "test_declared_method_has_probability_parity_but_shadow_fails_closed",
                    ),
                ),
                _repo_source(
                    repo_root,
                    "tests/jalon8/test_external_validation.py",
                    symbols=(
                        "test_multileague_gates_measure_only_observed_coverage",
                        "test_preseason_package_rejects_ready_claim_without_receipt_repository_proof",
                        "test_full_external_run_is_cache_only_and_gate_honest",
                    ),
                ),
            ],
            "storage_status": "NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS",
        }
    )
    return _with_content_hash(report)


def build_reports(
    repo_root: Path,
    audit_root: Path,
    loop55_root: Path,
) -> dict[str, dict[str, Any]]:
    audit = _verify_audit_root(audit_root)
    _verify_loop55_root(loop55_root, repo_root)
    lineage = _read_csv(audit / "tables/dataset-lineage.csv")
    quality = _read_csv(audit / "tables/dataset-quality.csv")
    times = _read_csv(audit / "tables/time-fields.csv")
    loop54 = _load_loop54_replay(repo_root)
    reports = {
        "temporal-surface-inventory-v1.json": _build_surface_inventory(repo_root, lineage, quality, times),
        "temporal-contract-v1.json": _build_temporal_contract(repo_root),
        "source-receipt-inventory-v1.json": _build_receipt_inventory(repo_root),
        "asof-join-audit-v1.json": _build_asof_audit(repo_root),
        "temporal-test-coverage-v1.json": _build_test_coverage(repo_root),
        "future-mutation-matrix-v1.json": _build_future_mutation_matrix(repo_root),
        "decision-lineage-trace-v1.json": _build_decision_trace(repo_root),
        "historical-point-in-time-replay-v1.json": _build_historical_replay(repo_root, loop54),
        "temporal-invalidation-ledger-v1.json": _build_invalidation_ledger(loop54),
        "temporal-defect-inventory-v1.json": _build_defect_inventory(repo_root),
    }
    if tuple(reports) != REPORT_FILENAMES:
        raise AssertionError("TEMPORAL_REPORT_SET_MISMATCH")
    for report in reports.values():
        _verify_content_hash(report)
    return reports


def _write_or_check(
    reports: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    check: bool,
) -> None:
    if check:
        for filename, document in reports.items():
            path = output_dir / filename
            if not path.is_file() or path.read_bytes() != _json_bytes(document):
                raise ValueError(f"TEMPORAL_REPORT_DRIFT:{filename}")
        extra = sorted(path.name for path in output_dir.glob("*.json") if path.name not in reports)
        if extra:
            raise ValueError(f"TEMPORAL_REPORT_UNDECLARED:{','.join(extra)}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, document in reports.items():
        (output_dir / filename).write_bytes(_json_bytes(document))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-root",
        type=Path,
        required=True,
        help="Exact immutable ROBIN-SCIENTIFIC-AUDIT-V1 root containing manifest.json.",
    )
    parser.add_argument(
        "--loop55-root",
        type=Path,
        required=True,
        help="Exact sealed ROBIN-POINT-IN-TIME-LINEAGE-V1 evidence root.",
    )
    parser.add_argument("--check", action="store_true", help="Fail if committed reports differ.")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir or repo_root / "reports/temporal-lineage"
    reports = build_reports(repo_root, args.audit_root, args.loop55_root)
    _write_or_check(reports, output_dir, check=args.check)
    print(
        json.dumps(
            {
                "audit_target": AUDIT_TARGET_REVISION,
                "loop55_manifest_sha256": LOOP55_MANIFEST_SHA256,
                "check": args.check,
                "output_dir": output_dir.as_posix(),
                "reports": len(reports),
                "status": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
