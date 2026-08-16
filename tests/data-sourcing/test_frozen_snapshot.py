from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from robin.capture import CaptureManifest
from robin.data_snapshot.contracts import SYNTHETIC_BATCH_ID, SnapshotValidationError
from robin.data_snapshot.freeze import (
    _materialize_snapshot,
    build_frozen_snapshot,
    scan_committable_reports,
)
from robin.data_snapshot.source import _mapping_status, verify_finalized_batch

ROOT = Path(__file__).parents[2]
GENERATOR_PATH = ROOT / "tools" / "data-sourcing" / "generate_synthetic_frozen_batch_v1.py"
PROTOCOLS = ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
READINESS_MATRIX = ROOT / "reports" / "data-sourcing" / "experiment-data-window-matrix-v1.json"
SPEC = ROOT / "tests" / "data-sourcing" / "fixtures" / "synthetic-frozen-batch-spec-v1.json"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = _load_module(GENERATOR_PATH, "generate_synthetic_frozen_batch_v1")


def _source(
    tmp_path: Path,
    name: str = "source",
    *,
    payload_market_mode: str = "CONTRACT",
) -> Path:
    path = tmp_path / name
    cast(Callable[..., Path], GENERATOR.generate_batch)(
        path, payload_market_mode=payload_market_mode
    )
    return path


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _build(
    source: Path,
    output: Path,
    reports: Path | None = None,
    *,
    check: bool = False,
) -> Any:
    return build_frozen_snapshot(
        source_root=source,
        output_root=output,
        protocols_path=PROTOCOLS,
        reports_output=reports,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        check=check,
        test_only_allow_short_observation=True,
    )


def _verify(source: Path, **kwargs: Any) -> Any:
    return verify_finalized_batch(
        source,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        test_only_allow_short_observation=True,
        **kwargs,
    )


def _reseal(source: Path) -> None:
    manifest = source / "capture-manifest.json"
    marker_path = source / "FINALIZED.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    indexed = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.name not in {"FINALIZED.json", "sha256sums.txt"}
    )
    sums = (
        "\n".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
            f"{path.relative_to(source).as_posix()}"
            for path in indexed
        )
        + "\n"
    )
    (source / "sha256sums.txt").write_text(sums, encoding="utf-8", newline="\n")
    marker_path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_synthetic_fixture_contract_is_exact_and_provider_free(tmp_path: Path) -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    source = _source(tmp_path)
    assert spec == {
        "batch_id": "SYNTHETIC_FIVE_CANARY_RECEIPT_BATCH_V1",
        "capture_labels": ["C0", "C1", "C2", "C3", "C4"],
        "fixture_count": 5,
        "markets": ["h2h", "totals"],
        "provenance": "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD",
        "window_ids": ["H24", "H12", "H6", "H2", "H1"],
    }
    receipt_documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (source / "receipts").glob("*.json")
    ]
    assert len(receipt_documents) == 10
    assert sum(receipt["admission_status"] == "ADMITTED" for receipt in receipt_documents) == 5
    assert (
        sum(receipt["admission_status"] == "INTAKE_PENDING" for receipt in receipt_documents) == 5
    )
    assert len(list((source / "manifests").glob("*.json"))) == 5
    batch = _verify(source, observation_seconds=0)
    assert len(batch.captures) == 5
    assert all(capture.technical_harness_contract_verified for capture in batch.captures)
    assert all(
        capture.mapping_statuses == ("FIXTURE_MAPPING_PROVEN",) for capture in batch.captures
    )
    assert len(batch.selected_fixtures) == 5
    assert all(
        {
            "away_team",
            "fixture_id",
            "home_team",
            "kickoff_at",
            "provider_event_id",
            "sport_key",
        }
        <= set(fixture)
        for fixture in batch.selected_fixtures
    )


def test_builder_rejects_blocked_scientific_gate_before_any_output_write(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    output = tmp_path / "blocked-snapshots"
    reports = tmp_path / "blocked-reports"
    manifest_path = source / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["selected_fixtures"][0].pop("provider_event_id")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _reseal(source)
    batch = _verify(source, observation_seconds=0)
    assert all(
        capture.mapping_statuses == ("FIXTURE_MAPPING_UNPROVEN",) for capture in batch.captures
    )

    with pytest.raises(SnapshotValidationError, match="SCIENTIFIC_DATA_GATE_BLOCKED"):
        _build(source, output, reports)

    assert not output.exists()
    assert not reports.exists()


def test_builder_rejects_proven_spreads_only_batch_before_any_output_write(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, payload_market_mode="SPREADS_ONLY")
    output = tmp_path / "spreads-only-snapshots"
    reports = tmp_path / "spreads-only-reports"
    batch = _verify(source, observation_seconds=0)
    assert all(
        capture.mapping_statuses == ("FIXTURE_MAPPING_PROVEN",) for capture in batch.captures
    )

    with pytest.raises(SnapshotValidationError, match="SCIENTIFIC_DATA_GATE_BLOCKED"):
        _build(source, output, reports)

    assert not output.exists()
    assert not reports.exists()


def test_builder_rejects_missing_h2h_market_timestamp_before_any_output_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_events = cast(Callable[..., list[dict[str, Any]]], GENERATOR._events)

    def events_without_h2h_timestamp(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        events = original_events(*args, **kwargs)
        for event in events:
            for bookmaker in cast(list[dict[str, Any]], event["bookmakers"]):
                for market in cast(list[dict[str, Any]], bookmaker["markets"]):
                    if market["key"] == "h2h":
                        market.pop("last_update")
        return events

    monkeypatch.setattr(GENERATOR, "_events", events_without_h2h_timestamp)
    source = _source(tmp_path)
    output = tmp_path / "missing-h2h-timestamp-snapshots"
    reports = tmp_path / "missing-h2h-timestamp-reports"

    with pytest.raises(SnapshotValidationError, match="SCIENTIFIC_DATA_GATE_BLOCKED"):
        _build(source, output, reports)

    assert not output.exists()
    assert not reports.exists()


def test_builder_rejects_missing_common_predictor_h2_before_any_output_write(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    output = tmp_path / "missing-h2-snapshots"
    reports = tmp_path / "missing-h2-reports"
    manifest_path = source / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    h2_windows = [
        window
        for window in manifest["capture_windows"]
        if window["temporal_role"] == "PREDICTOR" and window["window_id"] == "H2"
    ]
    assert len(h2_windows) == 5
    for window in h2_windows:
        window["earliest_admissible"] = "2030-02-05T13:00:00Z"
        window["latest_admissible"] = "2030-02-05T13:05:00Z"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _reseal(source)

    with pytest.raises(SnapshotValidationError, match="SCIENTIFIC_DATA_GATE_BLOCKED"):
        _build(source, output, reports)

    assert not output.exists()
    assert not reports.exists()


def test_builder_is_byte_reproducible_in_two_roots_and_check_mode(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = _build(source, tmp_path / "snapshots-a", tmp_path / "reports-a")
    second = _build(source, tmp_path / "snapshots-b", tmp_path / "reports-b")
    assert "FROZEN_SNAPSHOT_SYNTHETIC_REPRODUCIBLE" not in first.verdicts
    assert "FROZEN_SNAPSHOT_SYNTHETIC_REPRODUCIBLE" not in second.verdicts
    assert first.snapshot_id == second.snapshot_id
    assert first.manifest_sha256 == second.manifest_sha256
    assert _tree(first.snapshot_directory) == _tree(second.snapshot_directory)
    assert _tree(tmp_path / "reports-a") == _tree(tmp_path / "reports-b")
    checked = _build(
        source,
        tmp_path / "snapshots-a",
        tmp_path / "reports-a",
        check=True,
    )
    assert checked.check_only is True
    assert checked.snapshot_id == first.snapshot_id
    assert checked.real_market_data_leak_count == 0
    assert "FROZEN_SNAPSHOT_SYNTHETIC_REPRODUCIBLE" in checked.verdicts
    assert "NO_REAL_SNAPSHOT_CREATED" in checked.verdicts
    assert "NO_EXPERIMENT_READINESS_CLAIMED" in checked.verdicts
    assert "ZERO_ACCUMULATION_CANDIDATES_WITH_CLOSED_DATA_GATE" in checked.verdicts


def test_snapshot_id_binds_external_reference_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import robin.data_snapshot.freeze as freeze_module

    source = _source(tmp_path)
    first = _build(source, tmp_path / "snapshots-a")
    original = freeze_module._external_reference

    def changed_external_reference(batch: Any, snapshot_id: str) -> dict[str, Any]:
        document = dict(original(batch, snapshot_id))
        document["raw_payload_sha256_list"] = list(
            reversed(cast(list[str], document["raw_payload_sha256_list"]))
        )
        return document

    monkeypatch.setattr(freeze_module, "_external_reference", changed_external_reference)
    second = _build(source, tmp_path / "snapshots-b")

    assert second.snapshot_id != first.snapshot_id


def test_snapshot_id_binds_frozen_marker_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import robin.data_snapshot.freeze as freeze_module

    source = _source(tmp_path)
    first = _build(source, tmp_path / "snapshots-a")
    original = freeze_module._frozen_marker_contract

    def changed_marker_contract(*, synthetic_contract: bool) -> dict[str, Any]:
        document = dict(original(synthetic_contract=synthetic_contract))
        document["status"] = "MUTATED_MARKER_CONTRACT"
        return document

    monkeypatch.setattr(freeze_module, "_frozen_marker_contract", changed_marker_contract)
    second = _build(source, tmp_path / "snapshots-b")

    assert second.snapshot_id != first.snapshot_id


def test_finalized_marker_is_required_and_read_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    reads: list[str] = []
    original = Path.read_bytes

    def recording_read(path: Path) -> bytes:
        if source.resolve() in path.resolve().parents:
            reads.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    _verify(source, observation_seconds=0)
    assert reads[0] == "FINALIZED.json"

    missing = _source(tmp_path, "missing")
    (missing / "FINALIZED.json").unlink()
    with pytest.raises(SnapshotValidationError, match="FINALIZED_MARKER_REQUIRED"):
        _verify(missing, observation_seconds=0)


def test_post_finalization_mutation_and_manifest_hash_drift_are_rejected(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    mutation_blocked = False

    def mutate(_: float) -> None:
        nonlocal mutation_blocked
        path = source / "capture-manifest.json"
        try:
            path.write_bytes(path.read_bytes() + b" ")
        except PermissionError:
            mutation_blocked = True

    mutation_detected = False
    try:
        _verify(source, observation_seconds=300, sleeper=mutate)
    except SnapshotValidationError as error:
        assert str(error) == "FINALIZED_BATCH_MUTATED"
        mutation_detected = True
    assert mutation_blocked or mutation_detected


@pytest.mark.parametrize("late_target", ("protocols", "output", "reports"))
def test_builder_revalidates_all_auxiliary_roots_after_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_target: str
) -> None:
    import robin.data_snapshot.freeze as freeze_module
    import robin.data_snapshot.source as source_module

    source = _source(tmp_path)
    output = tmp_path / "output"
    reports = tmp_path / "reports"
    targets = {"protocols": PROTOCOLS, "output": output, "reports": reports}
    target = Path(os.path.abspath(targets[late_target]))
    armed = False
    original_verify = cast(Callable[..., Any], getattr(freeze_module, "verify_finalized_batch"))
    original_reparse = source_module._is_reparse_point

    def verify_then_arm(*args: Any, **kwargs: Any) -> Any:
        nonlocal armed
        batch = original_verify(*args, **kwargs)
        armed = True
        return batch

    def late_reparse(path: Path) -> bool:
        return (armed and path == target) or original_reparse(path)

    monkeypatch.setattr(freeze_module, "verify_finalized_batch", verify_then_arm)
    monkeypatch.setattr(source_module, "_is_reparse_point", late_reparse)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        _build(source, output, reports)

    assert not output.exists()

    drift = _source(tmp_path, "drift")
    (drift / "capture-manifest.json").write_bytes(b"{}\n")
    with pytest.raises(SnapshotValidationError, match="FINALIZED_MANIFEST_HASH_MISMATCH"):
        _verify(drift, observation_seconds=0)


def test_receipt_raw_binding_is_checked_after_integrity_index(tmp_path: Path) -> None:
    source = _source(tmp_path)
    raw = next((source / "raw" / "sha256").glob("*/*.bin"))
    raw.write_bytes(raw.read_bytes() + b" ")
    _reseal(source)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_RAW_HASH_MISMATCH"):
        _verify(source, observation_seconds=0)


def test_normalized_observations_are_bound_to_their_raw_receipt(tmp_path: Path) -> None:
    source = _source(tmp_path)
    top_manifest = json.loads((source / "capture-manifest.json").read_text(encoding="utf-8"))
    capture = next(item for item in top_manifest["captures"] if item["capture_label"] == "C0")
    technical_manifest_path = source / "manifests" / f"{capture['snapshot_id']}.json"
    technical_manifest = CaptureManifest.model_validate_json(technical_manifest_path.read_bytes())
    normalized_path = source / technical_manifest.normalized_storage_key
    rows = normalized_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["payload_sha256"] = "0" * 64
    rows[0] = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    normalized_path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    manifest_material = technical_manifest.model_dump(mode="python", exclude={"manifest_sha256"})
    manifest_material["schema_fingerprint"] = technical_manifest.schema_fingerprint
    manifest_material["fixture_mappings"] = technical_manifest.fixture_mappings
    manifest_material["normalized_sha256"] = hashlib.sha256(
        normalized_path.read_bytes()
    ).hexdigest()
    replacement = CaptureManifest.issue(**manifest_material)
    technical_manifest_path.write_text(
        json.dumps(
            replacement.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    capture["normalized_sha256"] = replacement.normalized_sha256
    (source / "capture-manifest.json").write_text(
        json.dumps(top_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _reseal(source)
    with pytest.raises(
        SnapshotValidationError, match="CAPTURE_NORMALIZED_TECHNICAL_BINDING_MISMATCH"
    ):
        _verify(source, observation_seconds=0)


def test_secret_scan_allows_environment_reference_but_rejects_literal_secret(
    tmp_path: Path,
) -> None:
    safe = _source(tmp_path, "safe")
    runtime = safe / "runtime"
    runtime.mkdir()
    (runtime / "canary.py").write_text(
        'api_key = os.environ["THE_ODDS_API_KEY"]\nurl = "https://example.invalid?apiKey={api_key}"\n',
        encoding="utf-8",
        newline="\n",
    )
    _reseal(safe)
    _verify(safe, observation_seconds=0)

    leaked = _source(tmp_path, "leaked")
    leaked_runtime = leaked / "runtime"
    leaked_runtime.mkdir()
    (leaked_runtime / "canary.py").write_text(
        'api_key = "0123456789abcdef0123456789abcdef"\n',
        encoding="utf-8",
        newline="\n",
    )
    _reseal(leaked)
    with pytest.raises(SnapshotValidationError, match="BATCH_SECRET_OR_AUTHENTICATED_URL_DETECTED"):
        _verify(leaked, observation_seconds=0)


def test_proven_technical_mapping_evaluates_timing_before_mutualization(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    manifest_path = source / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capture_windows"][0]["earliest_admissible"] = "2030-02-05T13:00:00Z"
    manifest["capture_windows"][0]["latest_admissible"] = "2030-02-05T13:05:00Z"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _reseal(source)
    result = _build(source, tmp_path / "snapshots", tmp_path / "reports")
    temporal = json.loads(
        (tmp_path / "reports" / "five-canary-temporal-coverage-v1.json").read_text(encoding="utf-8")
    )
    assert temporal["status_counts"] == {"WINDOW_MISSED": 1, "WINDOW_VALID": 24}
    assert temporal["window_claims_backdated"] == 0
    assert temporal["mutualized_window_count"] == 19
    assert result.provider_calls == result.secret_reads == 0


def test_denominators_deduplication_totals_and_readiness_are_explicit(tmp_path: Path) -> None:
    source = _source(tmp_path)
    _build(source, tmp_path / "snapshots", tmp_path / "reports")
    quality = json.loads(
        (tmp_path / "reports" / "five-canary-batch-quality-summary-v1.json").read_text(
            encoding="utf-8"
        )
    )
    required = {
        "selected_fixture_count",
        "uniquely_mapped_fixture_count",
        "ambiguous_fixture_count",
        "capture_window_count",
        "satisfied_window_count",
        "missed_window_count",
        "mutualized_window_count",
        "HTTP_request_count",
        "billable_request_count",
        "credit_count",
        "raw_payload_count",
        "receipt_count",
        "event_count",
        "unique_bookmaker_count",
        "event_bookmaker_occurrence_count",
        "h2h_market_object_count",
        "totals_market_object_count",
        "h2h_outcome_count",
        "totals_outcome_count",
        "normalized_observation_count",
    }
    assert set(quality["denominators"]) == required
    assert quality["duplicate_observation_count"] == 0
    assert "SYNTHETIC_TOTALS_CONTRACT_VALIDATED" in quality["quality_limits"]
    assert "REAL_TOTALS_COVERAGE_NOT_ASSESSED" in quality["quality_limits"]
    assert quality["tooling_status"] == "OFFLINE_DRAFT_READY"
    assert quality["synthetic_validation_status"] == "PASS"
    assert quality["real_data_status"] == "NOT_AVAILABLE"
    assert quality["real_capture_count"] == 0
    for capture in quality["capture_quality"]:
        for metric in (
            "h2h_presence",
            "h2h_completeness",
            "totals_presence",
            "totals_completeness",
            "market_timestamp_coverage",
            "bookmaker_timestamp_coverage",
            "line_consistency",
        ):
            assert set(capture[metric]) == {"numerator", "denominator", "grain", "ratio"}

    readiness = json.loads(
        (tmp_path / "reports" / "experiment-readiness-gate-v1.json").read_text(encoding="utf-8")
    )
    assert readiness["protocol_count"] == 25
    assert len({row["experiment_id"] for row in readiness["protocols"]}) == 25
    assert readiness["executable_protocol_count"] == 0
    assert readiness["execution_count"] == 0
    assert readiness["performance_selection_used"] is False
    assert readiness["experiment_readiness_status"] == "NOT_ASSESSED_ON_REAL_DATA"
    assert readiness["real_readiness_claimed"] is False
    assert {row["status"] for row in readiness["protocols"]} <= {
        "DATA_GATE_BLOCKED",
        "PROTOCOL_SUCCESSOR_REQUIRED",
    }

    accumulation = json.loads(
        (tmp_path / "reports" / "first-accumulation-candidates-v1.json").read_text(encoding="utf-8")
    )
    assert accumulation["candidate_count"] == 0
    assert accumulation["candidates"] == []
    assert accumulation["verdict"] == "ZERO_ACCUMULATION_CANDIDATES_WITH_CLOSED_DATA_GATE"
    assert all(row["status"] != "EXECUTABLE" for row in readiness["protocols"])


def test_synthetic_reports_never_publish_positive_real_data_or_experiment_claims(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    reports = tmp_path / "reports"
    _build(source, tmp_path / "snapshots", reports)

    def strings(value: object) -> list[str]:
        if isinstance(value, dict):
            return [item for child in value.values() for item in strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in strings(child)]
        return [value] if isinstance(value, str) else []

    values = [
        value
        for path in reports.glob("*.json")
        for value in strings(json.loads(path.read_text(encoding="utf-8")))
    ]
    forbidden = {
        "ACCUMULATION_STARTED",
        "CAPABILITY_PROVEN",
        "EXECUTABLE",
        "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED",
        "FIVE_CANARY_BATCH_QUALITY_PROFILED",
        "PRODUCTION",
        "READY_FOR_EXPERIMENT",
        "REAL_MARKET_SCHEMA_DRIFT_CLASSIFIED",
        "REAL_TEMPORAL_WINDOW_COVERAGE_PROFILED",
        "ROBIN_FIRST_25_EXPERIMENT_READINESS_REASSESSED",
    }
    assert forbidden.isdisjoint(values)


def test_protocol_count_and_successor_gate_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path)
    protocols = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
    protocols["experiments"].pop()
    altered = tmp_path / "protocols.json"
    altered.write_text(json.dumps(protocols), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="PROTOCOL_SOURCE_HASH_MISMATCH"):
        build_frozen_snapshot(
            source_root=source,
            output_root=tmp_path / "snapshots",
            protocols_path=altered,
            readiness_matrix_path=READINESS_MATRIX,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    result = _build(source, tmp_path / "good", tmp_path / "reports")
    readiness = json.loads(
        (tmp_path / "reports" / "experiment-readiness-gate-v1.json").read_text(encoding="utf-8")
    )
    exp009 = next(row for row in readiness["protocols"] if row["experiment_id"] == "RDS-EXP-V1-009")
    assert exp009["status"] == "PROTOCOL_SUCCESSOR_REQUIRED"
    assert result.network_calls == 0


def test_mapping_cannot_be_proven_by_six_self_declared_identity_predicates() -> None:
    proof = {
        "away_team_unique": True,
        "home_team_unique": True,
        "kickoff_compatible": True,
        "league_exact": True,
        "no_concurrent_candidate": True,
        "provider_event_unique": True,
        "status": "MAPPED",
    }
    assert _mapping_status(proof) == "FIXTURE_MAPPING_UNPROVEN"
    proof["kickoff_compatible"] = False
    assert _mapping_status(proof) == "FIXTURE_MAPPING_UNPROVEN"


def test_reports_exclude_real_tokens_paths_secrets_and_authenticated_urls(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    result = _build(source, tmp_path / "snapshots", tmp_path / "reports")
    batch = _verify(source, observation_seconds=0)
    reports = _tree(tmp_path / "reports")
    scan = scan_committable_reports(
        reports,
        batch,
        forbidden_paths=(str(source), str(tmp_path / "snapshots")),
    )
    assert scan == {
        "absolute_path_occurrences": 0,
        "authenticated_url_occurrences": 0,
        "exact_forbidden_path_occurrences": 0,
        "real_market_data_categories": {
            "bookmaker_identities": 0,
            "price_fragments": 0,
            "provider_event_ids": 0,
            "team_names": 0,
        },
        "real_market_data_leak_count": 0,
        "structured_secret_occurrences": 0,
        "total_failure_count": 0,
        "verdict": "PASS",
    }
    assert result.real_market_data_leak_count == 0


@pytest.mark.parametrize(
    "leaked_path",
    (
        r"C:\Temp\secret.json",
        r"D:\research\batch\raw.bin",
        "/tmp/robin/secret.json",
        "/workspace/private/batch.json",
    ),
)
def test_report_scan_rejects_json_escaped_absolute_paths(tmp_path: Path, leaked_path: str) -> None:
    source = _source(tmp_path)
    batch = _verify(source, observation_seconds=0)
    reports = {
        "leaked.json": (
            json.dumps({"local_path": leaked_path}, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
    }

    scan = scan_committable_reports(reports, batch, forbidden_paths=(leaked_path,))

    assert scan["absolute_path_occurrences"] > 0
    assert scan["exact_forbidden_path_occurrences"] > 0
    assert scan["verdict"] == "FAIL"


@pytest.mark.parametrize("leaked_price", (1.91, "1.91"))
def test_report_scan_rejects_structured_detailed_prices(
    tmp_path: Path, leaked_price: float | str
) -> None:
    source = _source(tmp_path)
    batch = _verify(source, observation_seconds=0)
    reports = {
        "leaked.json": (
            json.dumps({"outcome_price": leaked_price}, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
    }

    scan = scan_committable_reports(reports, batch, forbidden_paths=())

    assert scan["real_market_data_categories"]["price_fragments"] > 0
    assert scan["real_market_data_leak_count"] > 0
    assert scan["verdict"] == "FAIL"


@pytest.mark.parametrize("real_token", (r"Bookmaker\Alias", 'Club "Quoted"'))
def test_report_scan_matches_real_tokens_after_json_decoding(
    tmp_path: Path, real_token: str
) -> None:
    source = _source(tmp_path)
    batch = _verify(source, observation_seconds=0)
    batch = replace(
        batch,
        leak_tokens={
            "bookmaker_identities": frozenset({real_token.encode("utf-8")}),
            "price_fragments": frozenset(),
            "provider_event_ids": frozenset(),
            "team_names": frozenset(),
        },
    )
    reports = {
        "leaked.json": (
            json.dumps({"leaked": real_token}, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
    }

    scan = scan_committable_reports(reports, batch, forbidden_paths=())

    assert scan["real_market_data_categories"]["bookmaker_identities"] > 0
    assert scan["real_market_data_leak_count"] > 0
    assert scan["verdict"] == "FAIL"


def test_network_is_blocked_secret_is_not_read_and_frozen_marker_is_written_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    attempts = 0

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        del args, kwargs
        attempts += 1
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = _build(source, tmp_path / "snapshots")
    assert attempts == 0
    assert result.network_calls == result.provider_calls == result.secret_reads == 0

    order: list[str] = []
    import robin.data_snapshot.freeze as freeze_module

    original = freeze_module._write_file

    def recording_write(path: Path, value: bytes) -> None:
        order.append(path.name)
        original(path, value)

    monkeypatch.setattr(freeze_module, "_write_file", recording_write)
    target = _materialize_snapshot(
        tmp_path / "marker-order",
        "a" * 64,
        {"manifest.json": b"{}\n", "sha256sums.txt": b"", "FROZEN.json": b"{}\n"},
    )
    assert target.name == "a" * 64
    assert order[-1] == "FROZEN.json"
