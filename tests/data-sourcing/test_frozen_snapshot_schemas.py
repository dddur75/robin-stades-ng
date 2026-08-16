from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import robin.data_snapshot.freeze as freeze_module
from robin.data_snapshot.contracts import (
    SYNTHETIC_BATCH_ID,
    SnapshotValidationError,
    pretty_json_bytes,
)
from robin.data_snapshot.freeze import _document_matches_schema, build_frozen_snapshot

ROOT = Path(__file__).parents[2]
GENERATOR_PATH = ROOT / "tools" / "data-sourcing" / "generate_synthetic_frozen_batch_v1.py"
PROTOCOLS = ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
READINESS_MATRIX = ROOT / "reports" / "data-sourcing" / "experiment-data-window-matrix-v1.json"
MANIFEST_SCHEMA = ROOT / "schemas" / "data-sourcing" / "frozen-snapshot-manifest-v1.schema.json"
REPORTS_SCHEMA = ROOT / "schemas" / "data-sourcing" / "frozen-snapshot-reports-v1.schema.json"
NON_EXECUTION_WITNESS = (
    ROOT / "reports" / "data-sourcing" / "five-canary-batch-non-execution-witness-v1.json"
)
REPORT_ARTIFACTS = {
    "experiment-readiness-gate-v1.json": "experiment-readiness-gate-v1",
    "first-accumulation-candidates-v1.json": "first-accumulation-candidates-v1",
    "first-snapshot-external-reference-v1.json": "first-snapshot-external-reference-v1",
    "five-canary-batch-quality-summary-v1.json": "five-canary-batch-quality-summary-v1",
    "five-canary-schema-drift-v1.json": "five-canary-schema-drift-v1",
    "five-canary-temporal-coverage-v1.json": "five-canary-temporal-coverage-v1",
    "frozen-snapshot-contract-v1.json": "frozen-snapshot-contract-v1",
}


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_module(GENERATOR_PATH, "generate_synthetic_frozen_batch_v1_schemas")


def _document(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(path: Path) -> Draft202012Validator:
    schema = _document(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _reseal_synthetic_manifest(source: Path, manifest: dict[str, object]) -> None:
    marker_path = source / "FINALIZED.json"
    sums_path = source / "sha256sums.txt"
    marker = _document(marker_path)
    assert isinstance(marker, dict)
    marker_path.unlink()
    sums_path.unlink()
    manifest_bytes = pretty_json_bytes(manifest)
    (source / "capture-manifest.json").write_bytes(manifest_bytes)
    files = sorted(path for path in source.rglob("*") if path.is_file())
    sums_path.write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(source).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
        newline="\n",
    )
    marker["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    marker_path.write_bytes(pretty_json_bytes(marker))


def _assert_schema_parity(
    document: dict[str, object],
    schema: dict[str, object],
    validator: Draft202012Validator,
    *,
    expected: bool,
) -> None:
    reference_result = validator.is_valid(document)
    assert reference_result is expected
    assert _document_matches_schema(document, schema) is reference_result


def test_generated_manifest_and_seven_committable_reports_match_schemas(
    tmp_path: Path,
) -> None:
    source = cast(Callable[[Path], Path], GENERATOR.generate_batch)(tmp_path / "source")
    reports = tmp_path / "reports"
    result = build_frozen_snapshot(
        source_root=source,
        output_root=tmp_path / "snapshots",
        protocols_path=PROTOCOLS,
        readiness_matrix_path=READINESS_MATRIX,
        reports_output=reports,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )

    manifest_validator = _validator(MANIFEST_SCHEMA)
    report_validator = _validator(REPORTS_SCHEMA)
    manifest = _document(result.snapshot_directory / "manifest.json")
    assert isinstance(manifest, dict)
    manifest_validator.validate(manifest)

    report_paths = {path.name: path for path in reports.glob("*.json")}
    assert set(report_paths) == set(REPORT_ARTIFACTS)
    report_documents: dict[str, dict[str, object]] = {}
    for name, expected_artifact in sorted(REPORT_ARTIFACTS.items()):
        report = _document(report_paths[name])
        assert isinstance(report, dict)
        assert report["artifact"] == expected_artifact
        report_validator.validate(report)
        report_documents[name] = report

    witness = _document(NON_EXECUTION_WITNESS)
    assert isinstance(witness, dict)
    report_validator.validate(witness)
    assert witness["real_batch_status"] == "NOT_EXECUTED"
    assert witness["real_capture_count"] == 0
    assert witness["real_snapshot_count"] == 0
    assert witness["accumulation_candidates"] == []
    witness_with_path = copy.deepcopy(witness)
    witness_with_path["local_path"] = "C:\\forbidden"
    assert not report_validator.is_valid(witness_with_path)

    manifest_schema = _document(MANIFEST_SCHEMA)
    reports_schema = _document(REPORTS_SCHEMA)
    assert isinstance(manifest_schema, dict) and isinstance(reports_schema, dict)
    manifest_defs = manifest_schema["$defs"]
    assert isinstance(manifest_defs, dict)
    assert manifest_defs["dateTime"] == {
        "type": "string",
        "format": "date-time",
    }
    _assert_schema_parity(manifest, manifest_schema, manifest_validator, expected=True)
    for report in report_documents.values():
        _assert_schema_parity(report, reports_schema, report_validator, expected=True)

    # The stable roots are deliberately fail-closed, and artifact is the union discriminator.
    manifest_with_unknown_field = copy.deepcopy(manifest)
    manifest_with_unknown_field["uncontracted"] = True
    assert not manifest_validator.is_valid(manifest_with_unknown_field)

    for field in (
        "receipt_ids",
        "raw_payload_sha256_list",
        "normalized_partition_hashes",
        "request_fingerprints",
        "fixture_mapping_statuses",
        "schema_fingerprints",
        "quota_observations",
        "raw_delete_after_values",
    ):
        short_manifest = copy.deepcopy(manifest)
        collection = short_manifest[field]
        assert isinstance(collection, list | dict)
        if isinstance(collection, list):
            collection.pop()
        else:
            collection.pop(next(iter(collection)))
        assert not manifest_validator.is_valid(short_manifest), field

    quota_observations = manifest["quota_observations"]
    assert isinstance(quota_observations, dict)
    quota_label = next(iter(quota_observations))
    quota = quota_observations[quota_label]
    assert isinstance(quota, dict)
    for field, invalid_value in (
        ("observed_at", None),
        ("requests_last", None),
        ("requests_remaining", -1),
        ("requests_used", True),
    ):
        invalid_manifest = copy.deepcopy(manifest)
        invalid_quotas = invalid_manifest["quota_observations"]
        assert isinstance(invalid_quotas, dict)
        invalid_quota = invalid_quotas[quota_label]
        assert isinstance(invalid_quota, dict)
        invalid_quota[field] = invalid_value
        _assert_schema_parity(
            invalid_manifest,
            manifest_schema,
            manifest_validator,
            expected=False,
        )

    invalid_timestamp = copy.deepcopy(manifest)
    invalid_timestamp_quotas = invalid_timestamp["quota_observations"]
    assert isinstance(invalid_timestamp_quotas, dict)
    invalid_timestamp_quota = invalid_timestamp_quotas[quota_label]
    assert isinstance(invalid_timestamp_quota, dict)
    invalid_timestamp_quota["observed_at"] = "not-a-date"
    assert not _document_matches_schema(invalid_timestamp, manifest_schema)

    missing_observed_at = copy.deepcopy(manifest)
    missing_quotas = missing_observed_at["quota_observations"]
    assert isinstance(missing_quotas, dict)
    missing_quota = missing_quotas[quota_label]
    assert isinstance(missing_quota, dict)
    missing_quota.pop("observed_at")
    assert not manifest_validator.is_valid(missing_observed_at)

    contract_report = copy.deepcopy(report_documents["frozen-snapshot-contract-v1.json"])
    contract_report["artifact"] = "unknown-report-v1"
    assert not report_validator.is_valid(contract_report)

    quality_report = copy.deepcopy(report_documents["five-canary-batch-quality-summary-v1.json"])
    capture_quality = quality_report["capture_quality"]
    assert isinstance(capture_quality, list)
    capture_quality.pop()
    assert not report_validator.is_valid(quality_report)

    schema_drift_report = copy.deepcopy(report_documents["five-canary-schema-drift-v1.json"])
    captures = schema_drift_report["captures"]
    assert isinstance(captures, list)
    captures.pop()
    assert not report_validator.is_valid(schema_drift_report)

    schema_drift_report = copy.deepcopy(report_documents["five-canary-schema-drift-v1.json"])
    pairwise = schema_drift_report["pairwise_comparisons"]
    assert isinstance(pairwise, list)
    pairwise.pop()
    assert not report_validator.is_valid(schema_drift_report)

    external_reference = copy.deepcopy(
        report_documents["first-snapshot-external-reference-v1.json"]
    )
    external_hashes = external_reference["raw_payload_sha256_list"]
    assert isinstance(external_hashes, list)
    external_hashes.pop()
    assert not report_validator.is_valid(external_reference)

    readiness = copy.deepcopy(report_documents["experiment-readiness-gate-v1.json"])
    protocols = readiness["protocols"]
    assert isinstance(protocols, list)
    assert isinstance(protocols[0], dict) and isinstance(protocols[1], dict)
    protocols[1]["experiment_id"] = protocols[0]["experiment_id"]
    assert not report_validator.is_valid(readiness)

    accumulation = copy.deepcopy(report_documents["first-accumulation-candidates-v1.json"])
    candidates = accumulation["candidates"]
    assert isinstance(candidates, list)
    assert candidates == []
    assert accumulation["candidate_count"] == 0
    assert accumulation["verdict"] == ("ZERO_ACCUMULATION_CANDIDATES_WITH_CLOSED_DATA_GATE")
    assert accumulation["real_accumulation_claimed"] is False

    accumulation = copy.deepcopy(report_documents["first-accumulation-candidates-v1.json"])
    accumulation["candidate_count"] = 4
    assert not report_validator.is_valid(accumulation)

    blocked_accumulation = copy.deepcopy(report_documents["first-accumulation-candidates-v1.json"])
    blocked_accumulation.update(
        {
            "candidate_count": 0,
            "candidates": [],
            "meaning": "DATA_GATE_BLOCKED_NO_SUBSTANTIAL_CAPTURE_CLAIM",
            "verdict": "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE",
        }
    )
    report_validator.validate(blocked_accumulation)

    blocked_with_capability_claim = copy.deepcopy(blocked_accumulation)
    blocked_with_capability_claim["meaning"] = (
        "PIPELINE_CAN_CAPTURE_A_SUBSTANTIAL_PART_OF_REQUIRED_DATA_ONLY"
    )
    assert not report_validator.is_valid(blocked_with_capability_claim)

    blocked_with_candidate_verdict = copy.deepcopy(blocked_accumulation)
    blocked_with_candidate_verdict["verdict"] = "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED"
    assert not report_validator.is_valid(blocked_with_candidate_verdict)

    open_gate_without_candidates = copy.deepcopy(blocked_accumulation)
    open_gate_without_candidates.update(
        {
            "candidate_count": 3,
            "meaning": "PIPELINE_CAN_CAPTURE_A_SUBSTANTIAL_PART_OF_REQUIRED_DATA_ONLY",
            "verdict": "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED",
        }
    )
    assert not report_validator.is_valid(open_gate_without_candidates)

    invalid_role = copy.deepcopy(report_documents["five-canary-temporal-coverage-v1.json"])
    temporal_entries = invalid_role["entries"]
    assert isinstance(temporal_entries, list) and isinstance(temporal_entries[0], dict)
    temporal_entries[0]["temporal_role"] = "NOT_A_ROLE"
    _assert_schema_parity(invalid_role, reports_schema, report_validator, expected=False)

    invalid_timestamp = copy.deepcopy(report_documents["five-canary-temporal-coverage-v1.json"])
    timestamp_entries = invalid_timestamp["entries"]
    assert isinstance(timestamp_entries, list) and isinstance(timestamp_entries[0], dict)
    timestamp_entries[0]["kickoff"] = 7
    _assert_schema_parity(invalid_timestamp, reports_schema, report_validator, expected=False)

    missing_required = copy.deepcopy(manifest)
    missing_required.pop("status")
    _assert_schema_parity(
        missing_required,
        manifest_schema,
        manifest_validator,
        expected=False,
    )
    _assert_schema_parity(
        manifest_with_unknown_field,
        manifest_schema,
        manifest_validator,
        expected=False,
    )
    _assert_schema_parity(contract_report, reports_schema, report_validator, expected=False)
    _assert_schema_parity(readiness, reports_schema, report_validator, expected=False)


def test_runtime_schema_validator_rejects_unknown_schema_keywords() -> None:
    schema = _document(MANIFEST_SCHEMA)
    assert isinstance(schema, dict)
    schema["unsupportedKeyword"] = True
    with pytest.raises(
        SnapshotValidationError,
        match="FROZEN_SNAPSHOT_SCHEMA_CONTRACT_INVALID",
    ):
        _document_matches_schema({}, schema)


def test_permissive_runtime_schema_substitution_fails_before_any_builder_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = cast(Callable[[Path], Path], GENERATOR.generate_batch)(tmp_path / "source")
    output = tmp_path / "snapshots"
    reports = tmp_path / "reports"
    original_read = Path.read_bytes
    schema_reads = 0

    def substituted_schema_read(path: Path) -> bytes:
        nonlocal schema_reads
        if path == MANIFEST_SCHEMA.resolve():
            schema_reads += 1
            return b"{}\n"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", substituted_schema_read)
    with pytest.raises(
        SnapshotValidationError,
        match="FROZEN_SNAPSHOT_SCHEMA_CONTRACT_HASH_MISMATCH",
    ):
        build_frozen_snapshot(
            source_root=source,
            output_root=output,
            protocols_path=PROTOCOLS,
            readiness_matrix_path=READINESS_MATRIX,
            reports_output=reports,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert schema_reads == 1
    assert not output.exists()
    assert not reports.exists()


@pytest.mark.parametrize("invalid_name", (None, *sorted(REPORT_ARTIFACTS)))
def test_invalid_in_memory_document_causes_zero_snapshot_or_report_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_name: str | None,
) -> None:
    source = cast(Callable[[Path], Path], GENERATOR.generate_batch)(tmp_path / "source")
    output = tmp_path / "snapshots"
    reports = tmp_path / "reports"

    if invalid_name is None:
        original_expected_files = freeze_module._expected_files

        def invalid_expected_files(*args: Any, **kwargs: Any) -> Any:
            snapshot_id, manifest, files, report_hashes = original_expected_files(*args, **kwargs)
            invalid_files = dict(files)
            invalid_manifest = copy.deepcopy(manifest)
            invalid_manifest["uncontracted"] = True
            invalid_files["manifest.json"] = pretty_json_bytes(invalid_manifest)
            return snapshot_id, manifest, invalid_files, report_hashes

        monkeypatch.setattr(freeze_module, "_expected_files", invalid_expected_files)
        expected_code = "FROZEN_SNAPSHOT_MANIFEST_SCHEMA_INVALID"
    else:
        original_reports = freeze_module._committable_reports

        def invalid_reports(*args: Any, **kwargs: Any) -> dict[str, bytes]:
            documents = original_reports(*args, **kwargs)
            invalid_documents = dict(documents)
            invalid_report = json.loads(invalid_documents[invalid_name])
            assert isinstance(invalid_report, dict)
            invalid_report["artifact"] = "unknown-report-v1"
            invalid_documents[invalid_name] = pretty_json_bytes(invalid_report)
            return invalid_documents

        monkeypatch.setattr(freeze_module, "_committable_reports", invalid_reports)
        expected_code = "FROZEN_SNAPSHOT_REPORT_SCHEMA_INVALID"

    with pytest.raises(SnapshotValidationError, match=expected_code):
        build_frozen_snapshot(
            source_root=source,
            output_root=output,
            protocols_path=PROTOCOLS,
            readiness_matrix_path=READINESS_MATRIX,
            reports_output=reports,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert not output.exists()
    assert not reports.exists()


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        ("temporal_role", "NOT_A_ROLE", "CAPTURE_WINDOW_TEMPORAL_ROLE_INVALID"),
        ("kickoff", "not-a-date", "CAPTURE_WINDOW_KICKOFF_INVALID"),
    ),
)
def test_invalid_source_window_is_rejected_before_any_builder_write(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    source = cast(Callable[[Path], Path], GENERATOR.generate_batch)(tmp_path / "source")
    manifest = _document(source / "capture-manifest.json")
    assert isinstance(manifest, dict)
    windows = manifest["capture_windows"]
    assert isinstance(windows, list) and isinstance(windows[0], dict)
    windows[0][field] = value
    _reseal_synthetic_manifest(source, manifest)
    output = tmp_path / "snapshots"
    reports = tmp_path / "reports"

    with pytest.raises(SnapshotValidationError, match=expected_code):
        build_frozen_snapshot(
            source_root=source,
            output_root=output,
            protocols_path=PROTOCOLS,
            readiness_matrix_path=READINESS_MATRIX,
            reports_output=reports,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert not output.exists()
    assert not reports.exists()
