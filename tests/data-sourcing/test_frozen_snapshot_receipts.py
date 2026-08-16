from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from robin.capture import (
    CaptureBudget,
    CaptureHarness,
    CaptureStore,
    FixtureMapping,
    InternalRetentionPolicy,
    ProviderRequestSpec,
)
from robin.capture.contracts import (
    AdmissionStatus,
    CaptureManifest,
    MappingStatus,
    RawPayloadReceipt,
)
from robin.data_snapshot.contracts import (
    EXPECTED_CAPTURE_CODE_REVISION,
    EXPECTED_CAPTURE_HARNESS_VERSION,
    SYNTHETIC_BATCH_ID,
    SnapshotValidationError,
    canonical_json_bytes,
    json_object_from_bytes,
    json_value_from_bytes,
    pretty_json_bytes,
)
from robin.data_snapshot.profiling import _capture_coverage, _temporal_report
from robin.data_snapshot.source import (
    _capture_metadata_for_receipt,
    _contains_secret_or_authenticated_url,
    _mapping_status,
    _require_real_admitted_receipt_contract,
    _require_real_selected_fixtures,
    _require_real_terminal_manifest,
    _verify_intake_receipt,
    verify_finalized_batch,
)

ROOT = Path(__file__).parents[2]
CANARY_FIXTURE = (
    ROOT / "tests" / "capture" / "fixtures" / "synthetic-canary-structural-equivalent-v1.json"
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _seal(root: Path) -> None:
    marker_path = root / "FINALIZED.json"
    sums_path = root / "sha256sums.txt"
    marker_path.unlink(missing_ok=True)
    sums_path.unlink(missing_ok=True)
    files = sorted(path for path in root.rglob("*") if path.is_file())
    sums_path.write_text(
        "".join(
            f"{_sha(path.read_bytes())}  {path.relative_to(root).as_posix()}\n" for path in files
        ),
        encoding="utf-8",
        newline="\n",
    )
    manifest_bytes = (root / "capture-manifest.json").read_bytes()
    marker_path.write_bytes(
        pretty_json_bytes(
            {
                "batch_id": SYNTHETIC_BATCH_ID,
                "finalized_at": "2030-02-05T12:30:00Z",
                "manifest_path": "capture-manifest.json",
                "manifest_sha256": _sha(manifest_bytes),
                "sha256sums_path": "sha256sums.txt",
                "status": "FINALIZED",
            }
        )
    )


def _technical_batch(tmp_path: Path) -> tuple[Path, str]:
    fixture = cast(dict[str, Any], json.loads(CANARY_FIXTURE.read_text(encoding="utf-8")))
    events = cast(list[dict[str, Any]], fixture["responses"]["structural_optional_timestamp_paths"])
    payload = canonical_json_bytes(events)
    root = tmp_path / "technical-batch"
    policy = InternalRetentionPolicy()
    store = CaptureStore(root, policy, approved_local_root=root)
    mappings = tuple(
        FixtureMapping(
            provider_event_id=str(event["id"]),
            fixture_id=f"fixture-synthetic-{index + 1:03d}",
            status=MappingStatus.MAPPED,
            candidate_fixture_ids=(f"fixture-synthetic-{index + 1:03d}",),
            mapping_revision="synthetic-pr59-strict-v1",
        )
        for index, event in enumerate(events)
    )
    manifest = CaptureHarness(
        store, CaptureBudget(maximum_requests=1, maximum_credits=2)
    ).record_offline_response(
        ProviderRequestSpec(
            endpoint="/v4/sports/soccer_synthetic_alpha/odds",
            sport_key="soccer_synthetic_alpha",
            markets=("h2h", "totals"),
        ),
        payload=payload,
        http_status=200,
        response_headers={
            "x-requests-last": "2",
            "x-requests-remaining": "998",
            "x-requests-used": "2",
        },
        mappings=mappings,
        first_observed_at=datetime(2030, 2, 5, 12, 0, tzinfo=UTC),
        ingested_at=datetime(2030, 2, 5, 12, 0, 1, tzinfo=UTC),
    )
    policy_path = root / "INTERNAL-MARKET-DATA-RETENTION-POLICY-V1.json"
    policy_path.write_bytes(pretty_json_bytes(policy.model_dump(mode="json")))
    admitted = RawPayloadReceipt.model_validate_json(
        (root / "receipts" / f"{manifest.receipt_id}.json").read_bytes()
    )
    proven_mappings = [
        {
            "away_team_unique": True,
            "candidate_fixture_ids": list(mapping.candidate_fixture_ids),
            "fixture_id": mapping.fixture_id,
            "home_team_unique": True,
            "kickoff_compatible": True,
            "league_exact": True,
            "mapping_revision": mapping.mapping_revision,
            "no_concurrent_candidate": True,
            "provider_event_id": mapping.provider_event_id,
            "provider_event_unique": True,
            "status": "MAPPED",
        }
        for mapping in mappings
    ]
    selected_fixtures = [
        {
            "away_team": event["away_team"],
            "fixture_id": mapping.fixture_id,
            "home_team": event["home_team"],
            "kickoff_at": event["commence_time"],
            "provider_event_id": mapping.provider_event_id,
            "sport_key": event["sport_key"],
        }
        for event, mapping in zip(events, mappings, strict=True)
    ]
    top_manifest = {
        "batch_id": SYNTHETIC_BATCH_ID,
        "capture_code_revision": EXPECTED_CAPTURE_CODE_REVISION,
        "capture_harness_version": EXPECTED_CAPTURE_HARNESS_VERSION,
        "captures": [
            {
                "capture_label": "C3",
                "fixture_mappings": proven_mappings,
                "raw_payload_sha256": manifest.raw_payload_sha256,
                "receipt_id": manifest.receipt_id,
                "snapshot_id": manifest.snapshot_id,
            }
        ],
        "fixture_mappings": proven_mappings,
        "retention_policy_sha256": _sha(policy_path.read_bytes()),
        "selected_fixtures": selected_fixtures,
        "status": "FINALIZED",
    }
    (root / "capture-manifest.json").write_bytes(pretty_json_bytes(top_manifest))
    _seal(root)
    assert admitted.intake_receipt_id is not None
    return root, admitted.intake_receipt_id


def _verify(root: Path) -> None:
    verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )


def _receipt(root: Path, status: AdmissionStatus) -> RawPayloadReceipt:
    return next(
        receipt
        for path in (root / "receipts").glob("*.json")
        if (receipt := RawPayloadReceipt.model_validate_json(path.read_bytes())).admission_status
        is status
    )


def _write_receipt(root: Path, receipt: RawPayloadReceipt) -> Path:
    path = root / "receipts" / f"{receipt.receipt_id}.json"
    path.write_bytes(canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n")
    return path


def _valid_window(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "capture-manifest.json").read_text(encoding="utf-8"))
    selected = manifest["selected_fixtures"][0]
    return {
        "capture_label": "C3",
        "earliest_admissible": "2030-02-05T11:00:00Z",
        "fixture_id": selected["fixture_id"],
        "kickoff": selected["kickoff_at"],
        "latest_admissible": "2030-02-05T12:30:00Z",
        "provider_event_id": selected["provider_event_id"],
        "temporal_role": "PREDICTOR",
        "window_id": "H2",
    }


def _rewrite_normalized_and_manifest(
    root: Path,
    mutate: Any,
) -> None:
    manifest_path = next((root / "manifests").glob("*.json"))
    manifest = CaptureManifest.model_validate_json(manifest_path.read_bytes())
    normalized_path = root / manifest.normalized_storage_key
    rows = [
        json.loads(line)
        for line in normalized_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    mutate(rows)
    normalized_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    normalized_path.write_bytes(normalized_bytes)
    material = manifest.model_dump(mode="python", exclude={"manifest_sha256"})
    material["schema_fingerprint"] = manifest.schema_fingerprint
    material["fixture_mappings"] = manifest.fixture_mappings
    material["normalized_sha256"] = _sha(normalized_bytes)
    material["observation_count"] = len(rows)
    replacement = CaptureManifest.issue(**material)
    manifest_path.write_bytes(canonical_json_bytes(replacement.model_dump(mode="json")) + b"\n")
    _seal(root)


def test_pr59_receipt_manifest_intake_and_rows_are_verified_end_to_end(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    assert len(batch.captures) == 1
    assert batch.captures[0].label == "C3"
    assert batch.captures[0].technical_harness_contract_verified is True
    assert batch.captures[0].mapping_statuses == ("FIXTURE_MAPPING_PROVEN",)


def test_pr59_receipt_inventory_is_exact_and_graph_associations_are_explicit(
    tmp_path: Path,
) -> None:
    root, intake_id = _technical_batch(tmp_path)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    capture = batch.captures[0]
    manifest = CaptureManifest.model_validate_json(
        next((root / "manifests").glob("*.json")).read_bytes()
    )
    entries = {entry.logical_path: entry for entry in batch.inventory}
    assert entries[f"receipts/{capture.receipt_id}.json"].receipt_association == (
        capture.receipt_id,
    )
    assert entries[f"receipts/{intake_id}.json"].receipt_association == (intake_id,)
    for logical in (
        f"raw/sha256/{capture.raw_payload_sha256[:2]}/{capture.raw_payload_sha256}.bin",
        manifest.normalized_storage_key,
        f"manifests/{manifest.snapshot_id}.json",
        "capture-manifest.json",
    ):
        assert entries[logical].capture_association == ("C3",)
        assert entries[logical].receipt_association == tuple(
            sorted((capture.receipt_id, intake_id))
        )


def test_inventory_never_associates_a_supporting_path_by_label_substring(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    (root / "support-C3.txt").write_text("unrelated\n", encoding="utf-8", newline="\n")
    _seal(root)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    entry = next(item for item in batch.inventory if item.logical_path == "support-C3.txt")
    assert entry.capture_association == ()
    assert entry.receipt_association == ()


def test_extra_quarantined_receipt_without_raw_is_not_ignored(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    intake = _receipt(root, AdmissionStatus.INTAKE_PENDING)
    quarantined = RawPayloadReceipt.issue(
        intake_receipt_id=None,
        request_fingerprint_sha256="d" * 64,
        payload_sha256="e" * 64,
        payload_byte_length=1,
        http_status=500,
        quota=None,
        robin_first_observed_at=intake.robin_first_observed_at,
        robin_ingested_at=intake.robin_ingested_at,
        available_at=intake.available_at,
        raw_expires_at=intake.raw_expires_at,
        raw_storage_key=None,
        schema_fingerprint_sha256=None,
        admission_status=AdmissionStatus.QUARANTINED,
        rejection_code="TEST_QUARANTINED",
    )
    _write_receipt(root, quarantined)
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="BATCH_RECEIPT_DISPOSITION_INVALID"):
        _verify(root)


def test_extra_unbound_intake_receipt_linked_to_existing_raw_is_not_ignored(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    intake = _receipt(root, AdmissionStatus.INTAKE_PENDING)
    extra = RawPayloadReceipt.issue(
        intake_receipt_id=None,
        request_fingerprint_sha256="f" * 64,
        payload_sha256=intake.payload_sha256,
        payload_byte_length=intake.payload_byte_length,
        http_status=intake.http_status,
        quota=None,
        robin_first_observed_at=intake.robin_first_observed_at,
        robin_ingested_at=intake.robin_ingested_at,
        available_at=intake.available_at,
        raw_expires_at=intake.raw_expires_at,
        raw_storage_key=intake.raw_storage_key,
        schema_fingerprint_sha256=None,
        admission_status=AdmissionStatus.INTAKE_PENDING,
        rejection_code=None,
    )
    _write_receipt(root, extra)
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="BATCH_RECEIPT_DISPOSITION_INVALID"):
        _verify(root)


@pytest.mark.parametrize(
    "relative_path",
    (
        "receipts/orphan.txt",
        "receipts/nested/x.json",
        "foo-receipts.jsonl",
    ),
)
def test_declared_noncanonical_receipt_paths_are_rejected(
    tmp_path: Path,
    relative_path: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8", newline="\n")
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="BATCH_RECEIPT_PATH_GRAMMAR_INVALID"):
        _verify(root)


def test_declared_raw_copy_under_wrong_shard_is_rejected(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    raw_path = next((root / "raw" / "sha256").glob("*/*.bin"))
    wrong_shard = "00" if raw_path.parent.name != "00" else "01"
    copied = root / "raw" / "sha256" / wrong_shard / raw_path.name
    copied.parent.mkdir(parents=True)
    copied.write_bytes(raw_path.read_bytes())
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="BATCH_RAW_PATH_GRAMMAR_INVALID"):
        _verify(root)


def test_declared_normalized_copy_outside_manifest_path_is_rejected(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    normalized = next((root / "normalized").glob("*.jsonl"))
    (root / "normalized" / "copy.jsonl").write_bytes(normalized.read_bytes())
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="BATCH_NORMALIZED_PATH_DISPOSITION_MISMATCH",
    ):
        _verify(root)


def test_declared_orphan_technical_manifest_is_rejected(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    (root / "manifests" / "orphan.json").write_text(
        "{}\n",
        encoding="utf-8",
        newline="\n",
    )
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="BATCH_TECHNICAL_MANIFEST_DISPOSITION_MISMATCH",
    ):
        _verify(root)


@pytest.mark.parametrize(
    "field",
    ("raw_payload_sha256", "snapshot_id", "normalized_sha256"),
)
def test_terminal_capture_entry_cannot_contradict_hash_bound_pr59_fields(
    tmp_path: Path,
    field: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["captures"][0][field] = "0" * 64
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="CAPTURE_TERMINAL_MANIFEST_BINDING_MISMATCH",
    ):
        _verify(root)


def test_terminal_capture_entry_is_uniquely_keyed_by_final_receipt(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    duplicate = dict(manifest["captures"][0])
    duplicate["capture_label"] = "C4"
    manifest["captures"].append(duplicate)
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="CAPTURE_TERMINAL_MANIFEST_ENTRY_DUPLICATED",
    ):
        _verify(root)


def test_terminal_capture_relation_ignores_shared_non_identity_bindings(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    receipt = _receipt(root, AdmissionStatus.ADMITTED)
    technical = CaptureManifest.model_validate_json(
        next((root / "manifests").glob("*.json")).read_bytes()
    )
    captures = []
    for index in range(5):
        captures.append(
            {
                "capture_label": f"C{index}",
                "normalized_observation_count": technical.observation_count,
                "raw_payload_sha256": technical.raw_payload_sha256,
                "receipt_id": receipt.receipt_id if index == 3 else str(index + 1) * 64,
                "request_fingerprint_sha256": technical.request_fingerprint_sha256,
                "schema_fingerprint_sha256": technical.schema_fingerprint.schema_sha256,
                "snapshot_id": technical.snapshot_id if index == 3 else str(index + 1) * 64,
            }
        )
    metadata = _capture_metadata_for_receipt(
        {"captures": captures},
        receipt_id=receipt.receipt_id,
        raw_payload_sha256=receipt.payload_sha256,
        snapshot_id=technical.snapshot_id,
        technical_receipt=receipt,
        technical_manifest=technical,
    )
    assert metadata["capture_label"] == "C3"


def test_window_receipt_reference_is_not_a_second_terminal_capture_entry(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window["receipt_id"] = manifest["captures"][0]["receipt_id"]
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    _verify(root)


def test_finalization_timestamp_cannot_precede_capture_evidence(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    marker_path = root / "FINALIZED.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["finalized_at"] = "2000-01-01T00:00:00Z"
    marker_path.write_bytes(pretty_json_bytes(marker))
    with pytest.raises(SnapshotValidationError, match="FINALIZED_MARKER_PRECEDES_CAPTURE"):
        _verify(root)


def test_finalization_marker_aliases_cannot_contradict_canonical_fields(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    marker_path = root / "FINALIZED.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["state"] = "NOT_FINALIZED"
    marker_path.write_bytes(pretty_json_bytes(marker))
    with pytest.raises(SnapshotValidationError, match="FINALIZED_MARKER_STATUS_INVALID"):
        _verify(root)


def test_continuous_observer_rejects_mutation_restored_before_final_scan(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    target = root / "capture-manifest.json"
    original = target.read_bytes()
    mutation_blocked = False

    def mutate_and_restore(_seconds: float) -> None:
        nonlocal mutation_blocked
        try:
            target.write_bytes(original + b" ")
            target.write_bytes(original)
        except PermissionError:
            mutation_blocked = True

    mutation_detected = False
    try:
        verify_finalized_batch(
            root,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            sleeper=mutate_and_restore,
            test_only_allow_short_observation=True,
        )
    except SnapshotValidationError as exc:
        assert str(exc) == "FINALIZED_BATCH_MUTATED"
        mutation_detected = True
    assert mutation_blocked or mutation_detected


def test_continuous_observer_has_no_public_injection_parameter(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    assert "continuous_observation" not in inspect.signature(verify_finalized_batch).parameters
    with pytest.raises(TypeError):
        verify_finalized_batch(
            root,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
            continuous_observation=object(),  # type: ignore[call-arg]
        )


@pytest.mark.parametrize("fault", ("PRICE", "OMISSION", "AVAILABLE_AT"))
def test_pr59_normalized_rows_must_equal_public_raw_renormalization(
    tmp_path: Path,
    fault: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)

    def mutate(rows: list[dict[str, Any]]) -> None:
        if fault == "PRICE":
            rows[0]["price"] = "999.99"
        elif fault == "OMISSION":
            rows.pop()
        else:
            rows[0]["available_at"] = "2030-02-06T00:00:00Z"

    _rewrite_normalized_and_manifest(root, mutate)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_NORMALIZED_REPLAY_MISMATCH"):
        _verify(root)


def test_pr59_mapped_and_six_declared_booleans_do_not_prove_without_canonical_selection(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    top_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    top_manifest["selected_fixtures"] = [
        {"fixture_id": fixture["fixture_id"]} for fixture in top_manifest["selected_fixtures"]
    ]
    manifest_path.write_bytes(pretty_json_bytes(top_manifest))
    _seal(root)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    assert batch.captures[0].mapping_statuses == ("FIXTURE_MAPPING_UNPROVEN",)


@pytest.mark.parametrize(
    "candidate_universe_fault",
    (
        "PROVIDER_ABSENT",
        "OTHER_SELECTED_INCOMPLETE",
        "PROVIDER_DUPLICATED",
        "CANONICAL_CONCURRENT",
    ),
)
def test_pr59_mapping_requires_a_complete_unique_selected_candidate_universe(
    tmp_path: Path,
    candidate_universe_fault: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    top_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = top_manifest["selected_fixtures"]
    if candidate_universe_fault == "PROVIDER_ABSENT":
        selected[0].pop("provider_event_id")
    elif candidate_universe_fault == "OTHER_SELECTED_INCOMPLETE":
        selected[1].pop("sport_key")
    elif candidate_universe_fault == "PROVIDER_DUPLICATED":
        selected[1]["provider_event_id"] = selected[0]["provider_event_id"]
    else:
        for field in ("sport_key", "kickoff_at", "home_team", "away_team"):
            selected[1][field] = selected[0][field]
    manifest_path.write_bytes(pretty_json_bytes(top_manifest))
    _seal(root)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    assert batch.captures[0].mapping_statuses == ("FIXTURE_MAPPING_UNPROVEN",)
    assert all(
        mapping["status"] == "FIXTURE_MAPPING_UNPROVEN"
        for mapping in batch.captures[0].fixture_mappings
    )


@pytest.mark.parametrize(
    ("field", "contradiction"),
    (
        ("sport_key", "soccer_other_league"),
        ("kickoff_at", "2030-02-01T21:00:00Z"),
        ("home_team", "Contradictory Home"),
        ("away_team", "Contradictory Away"),
    ),
)
def test_pr59_mapping_is_unproven_when_raw_and_selected_canonical_fields_disagree(
    tmp_path: Path,
    field: str,
    contradiction: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    top_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    top_manifest["selected_fixtures"][0][field] = contradiction
    manifest_path.write_bytes(pretty_json_bytes(top_manifest))
    _seal(root)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    mappings = {
        mapping["provider_event_id"]: mapping for mapping in batch.captures[0].fixture_mappings
    }
    assert mappings["event-synthetic-001"]["status"] == "FIXTURE_MAPPING_UNPROVEN"
    assert mappings["event-synthetic-002"]["status"] == "FIXTURE_MAPPING_PROVEN"


@pytest.mark.parametrize("owner", ("capture", "top_level"))
def test_top_mapping_fixture_must_match_the_hash_bound_pr59_mapping(
    tmp_path: Path,
    owner: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    top_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mappings = (
        top_manifest["captures"][0]["fixture_mappings"]
        if owner == "capture"
        else top_manifest["fixture_mappings"]
    )
    mappings[0]["fixture_id"] = "fixture-contradictory"
    mappings[0]["candidate_fixture_ids"] = ["fixture-contradictory"]
    manifest_path.write_bytes(pretty_json_bytes(top_manifest))
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="FIXTURE_MAPPING_TECHNICAL_CONTRACT_MISMATCH",
    ):
        _verify(root)


def test_pr59_final_receipt_requires_its_intake_receipt(tmp_path: Path) -> None:
    root, intake_id = _technical_batch(tmp_path)
    (root / "receipts" / f"{intake_id}.json").unlink()
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_INTAKE_RECEIPT_MISSING"):
        _verify(root)


def test_declared_retention_policy_hash_must_match_the_unique_policy_file(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["retention_policy_sha256"] = "0" * 64
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="BATCH_RETENTION_POLICY_HASH_MISMATCH"):
        _verify(root)


def test_retention_policy_re_read_is_hash_bound_after_stability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    retention_path = (root / "INTERNAL-MARKET-DATA-RETENTION-POLICY-V1.json").resolve()
    original = Path.read_bytes
    retention_reads = 0

    def substitute_final_read(path: Path) -> bytes:
        nonlocal retention_reads
        if path.resolve() == retention_path:
            retention_reads += 1
            if retention_reads == 2:
                return b'{"policy_id":"substituted-after-stability"}\n'
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", substitute_final_read)
    with pytest.raises(SnapshotValidationError, match="BATCH_RETENTION_POLICY_HASH_MISMATCH"):
        _verify(root)
    assert retention_reads == 2


def test_pr59_final_receipt_rejects_a_different_valid_intake(tmp_path: Path) -> None:
    root, intake_id = _technical_batch(tmp_path)
    intake_path = root / "receipts" / f"{intake_id}.json"
    original = RawPayloadReceipt.model_validate_json(intake_path.read_bytes())
    replacement = RawPayloadReceipt.issue(
        intake_receipt_id=None,
        request_fingerprint_sha256="f" * 64,
        payload_sha256=original.payload_sha256,
        payload_byte_length=original.payload_byte_length,
        http_status=original.http_status,
        quota=None,
        robin_first_observed_at=original.robin_first_observed_at,
        robin_ingested_at=original.robin_ingested_at,
        available_at=original.available_at,
        raw_expires_at=original.raw_expires_at,
        raw_storage_key=original.raw_storage_key,
        schema_fingerprint_sha256=None,
        admission_status=original.admission_status,
        rejection_code=None,
    )
    replacement_path = root / "receipts" / f"{replacement.receipt_id}.json"
    replacement_path.write_bytes(canonical_json_bytes(replacement.model_dump(mode="json")) + b"\n")
    admitted = next(
        RawPayloadReceipt.model_validate_json(path.read_bytes())
        for path in (root / "receipts").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["admission_status"] == "ADMITTED"
    )
    mismatched_final = RawPayloadReceipt.issue(
        intake_receipt_id=replacement.receipt_id,
        request_fingerprint_sha256=admitted.request_fingerprint_sha256,
        payload_sha256=admitted.payload_sha256,
        payload_byte_length=admitted.payload_byte_length,
        http_status=admitted.http_status,
        quota=admitted.quota,
        robin_first_observed_at=admitted.robin_first_observed_at,
        robin_ingested_at=admitted.robin_ingested_at,
        available_at=admitted.available_at,
        raw_expires_at=admitted.raw_expires_at,
        raw_storage_key=admitted.raw_storage_key,
        schema_fingerprint_sha256=admitted.schema_fingerprint_sha256,
        admission_status=admitted.admission_status,
        rejection_code=admitted.rejection_code,
    )
    with pytest.raises(SnapshotValidationError, match="CAPTURE_INTAKE_RECEIPT_LINK_MISMATCH"):
        _verify_intake_receipt(root, mismatched_final)


@pytest.mark.parametrize("fault", ("INVALID_ITEM", "EXACT_DUPLICATE"))
def test_selected_fixture_collection_never_filters_invalid_or_duplicate_items(
    tmp_path: Path,
    fault: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if fault == "INVALID_ITEM":
        manifest["selected_fixtures"].append(42)
        expected = "BATCH_SELECTED_FIXTURES_CONTRACT_INVALID"
    else:
        manifest["selected_fixtures"].append(dict(manifest["selected_fixtures"][0]))
        expected = "BATCH_SELECTED_FIXTURE_DUPLICATED"
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match=expected):
        _verify(root)


def test_capture_window_collection_rejects_an_exact_duplicate(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    manifest["capture_windows"] = [window, dict(window)]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_WINDOW_IDENTITY_DUPLICATED"):
        _verify(root)


def test_capture_window_identity_does_not_depend_on_optional_provider_alias(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with_provider = _valid_window(root)
    without_provider = dict(with_provider)
    without_provider.pop("provider_event_id")
    manifest["capture_windows"] = [with_provider, without_provider]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_WINDOW_IDENTITY_DUPLICATED"):
        _verify(root)


def test_capture_window_bounds_cannot_create_a_second_logical_requirement(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = _valid_window(root)
    first["temporal_role"] = "TARGET"
    second = dict(first)
    second["earliest_admissible"] = "2030-02-05T11:30:00Z"
    manifest["capture_windows"] = [first, second]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match="CAPTURE_WINDOW_IDENTITY_DUPLICATED"):
        _verify(root)


def test_temporal_profiler_cannot_count_a_duplicate_logical_requirement(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    first = _valid_window(root)
    second = dict(first)
    second["earliest_admissible"] = "2030-02-05T11:30:00Z"
    with pytest.raises(SnapshotValidationError, match="TEMPORAL_WINDOW_IDENTITY_DUPLICATED"):
        _temporal_report(replace(batch, capture_windows=(first, second)))


def test_capture_window_fixture_and_provider_pair_must_match_pr59(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window["provider_event_id"] = manifest["selected_fixtures"][1]["provider_event_id"]
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="CAPTURE_WINDOW_FIXTURE_MAPPING_MISMATCH",
    ):
        _verify(root)


def test_capture_window_receipt_id_must_match_its_capture_label(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window["receipt_id"] = "0" * 64
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(
        SnapshotValidationError,
        match="CAPTURE_WINDOW_RECEIPT_BINDING_MISMATCH",
    ):
        _verify(root)


def test_temporal_profiler_never_substitutes_label_for_a_conflicting_receipt(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    window = _valid_window(root)
    window["receipt_id"] = "0" * 64
    report, _observed = _temporal_report(replace(batch, capture_windows=(window,)))
    entry = report["entries"][0]
    assert entry["status"] == "WINDOW_RECEIPT_INVALID"
    assert entry["window_contract_issue"] == "WINDOW_RECEIPT_BINDING_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("kickoff_at", "2040-01-01T00:00:00Z", "CAPTURE_WINDOW_ALIAS_CONFLICT"),
        ("capture", "OTHER", "CAPTURE_WINDOW_ALIAS_CONFLICT"),
        ("event_id", "event-contradictory", "CAPTURE_WINDOW_ALIAS_CONFLICT"),
        ("provider_event_id", 42, "CAPTURE_WINDOW_IDENTITY_INVALID"),
    ),
)
def test_capture_window_aliases_cannot_disagree(
    tmp_path: Path,
    field: str,
    value: object,
    expected: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window[field] = value
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)
    with pytest.raises(SnapshotValidationError, match=expected):
        _verify(root)


@pytest.mark.parametrize("temporal_role", ("NOT_A_ROLE", "predictor", "", 7, None))
def test_capture_window_temporal_role_is_an_exact_closed_enum(
    tmp_path: Path,
    temporal_role: object,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window["temporal_role"] = temporal_role
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)

    with pytest.raises(
        SnapshotValidationError,
        match="CAPTURE_WINDOW_TEMPORAL_ROLE_INVALID",
    ):
        _verify(root)


def test_capture_window_unspecified_temporal_role_is_admitted_exactly(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window["temporal_role"] = "UNSPECIFIED"
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)

    _verify(root)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("earliest_admissible", "not-a-date", "CAPTURE_WINDOW_EARLIEST_ADMISSIBLE_INVALID"),
        ("latest_admissible", "2030-02-05", "CAPTURE_WINDOW_LATEST_ADMISSIBLE_INVALID"),
        ("kickoff", "not-a-date", "CAPTURE_WINDOW_KICKOFF_INVALID"),
        ("kickoff", "2030-02-05T13:30:00+01:00", "CAPTURE_WINDOW_KICKOFF_INVALID"),
    ),
)
def test_capture_window_timestamps_are_canonical_utc_at_ingestion(
    tmp_path: Path,
    field: str,
    value: str,
    expected: str,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    manifest_path = root / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = _valid_window(root)
    window[field] = value
    manifest["capture_windows"] = [window]
    manifest_path.write_bytes(pretty_json_bytes(manifest))
    _seal(root)

    with pytest.raises(SnapshotValidationError, match=expected):
        _verify(root)


def test_real_receipt_contract_rejects_missing_quota_without_false_zero(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    admitted = _receipt(root, AdmissionStatus.ADMITTED)
    material = admitted.model_dump(mode="python", exclude={"receipt_id", "quota"})
    replacement = RawPayloadReceipt.issue(quota=None, **material)
    document = replacement.model_dump(mode="json")
    with pytest.raises(SnapshotValidationError, match="REAL_BATCH_QUOTA_EVIDENCE_REQUIRED"):
        _require_real_admitted_receipt_contract(replacement, document)


@pytest.mark.parametrize(("field", "value"), (("requests_last", True), ("requests_used", "2")))
def test_real_receipt_quota_counts_are_exact_non_boolean_integers(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    admitted = _receipt(root, AdmissionStatus.ADMITTED)
    document = admitted.model_dump(mode="json")
    document["quota"][field] = value
    with pytest.raises(SnapshotValidationError, match="REAL_BATCH_QUOTA_EVIDENCE_REQUIRED"):
        _require_real_admitted_receipt_contract(admitted, document)


def test_real_admitted_receipt_requires_http_200(tmp_path: Path) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    admitted = _receipt(root, AdmissionStatus.ADMITTED)
    material = admitted.model_dump(
        mode="python",
        exclude={"receipt_id", "http_status", "quota"},
    )
    replacement = RawPayloadReceipt.issue(
        http_status=500,
        quota=admitted.quota,
        **material,
    )
    with pytest.raises(SnapshotValidationError, match="REAL_BATCH_ADMITTED_HTTP_STATUS_INVALID"):
        _require_real_admitted_receipt_contract(
            replacement,
            replacement.model_dump(mode="json"),
        )


@pytest.mark.parametrize("missing", ("batch_id", "status", "captures"))
def test_real_terminal_manifest_requires_mission_identity_and_capture_inventory(
    missing: str,
) -> None:
    batch_id = "real-batch"
    manifest: dict[str, Any] = {
        "batch_id": batch_id,
        "capture_windows": [{}],
        "captures": [{"receipt_id": str(index) * 64} for index in range(5)],
        "selected_fixtures": [{"fixture_id": f"fixture-{index}"} for index in range(5)],
        "status": "FINALIZED",
    }
    manifest.pop(missing)
    with pytest.raises(
        SnapshotValidationError,
        match="REAL_BATCH_TERMINAL_MANIFEST_CONTRACT_INVALID",
    ):
        _require_real_terminal_manifest(manifest, batch_id)


def test_real_selected_fixture_ids_are_exactly_five_and_unique() -> None:
    selections = tuple(
        {
            "fixture_id": "fixture-duplicate" if index < 2 else f"fixture-{index}",
            "provider_event_id": f"event-{index}",
            "selection_note": f"distinct-{index}",
        }
        for index in range(5)
    )
    with pytest.raises(
        SnapshotValidationError,
        match="REAL_BATCH_FIVE_SELECTED_FIXTURES_REQUIRED",
    ):
        _require_real_selected_fixtures(selections)


def test_invalid_bookmaker_timestamp_is_not_present_or_market_contractual(
    tmp_path: Path,
) -> None:
    root, _intake_id = _technical_batch(tmp_path)
    batch = verify_finalized_batch(
        root,
        expected_batch_id=SYNTHETIC_BATCH_ID,
        observation_seconds=0,
        test_only_allow_short_observation=True,
    )
    capture = batch.captures[0]
    baseline, *_rest = _capture_coverage(capture, [], 0)
    payload = json.loads(json.dumps(capture.raw_payload))
    payload[0]["bookmakers"][0]["last_update"] = "garbage"
    mutated = replace(capture, raw_payload=payload)
    report, _events, _bookmakers, _markets, contract_markets = _capture_coverage(
        mutated,
        [],
        0,
    )
    coverage = report["bookmaker_timestamp_coverage"]
    assert coverage["numerator"] == baseline["bookmaker_timestamp_coverage"]["numerator"] - 1
    assert report["missingness"]["invalid_timestamp_count"] == 1
    assert contract_markets == set()


def test_six_self_declared_predicates_can_never_prove_a_mapping() -> None:
    proof = {
        "away_team_unique": True,
        "home_team_unique": True,
        "kickoff_compatible": True,
        "league_exact": True,
        "no_concurrent_candidate": True,
        "provider_event_unique": True,
        "status": "FIXTURE_MAPPING_PROVEN",
    }
    assert _mapping_status(proof) == "FIXTURE_MAPPING_UNPROVEN"


@pytest.mark.parametrize(
    "payload",
    (
        b'{"batch_id":"first","batch_id":"second"}',
        b'{"outer":{"value":1,"value":2}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b'{"value":1e400}',
    ),
)
def test_snapshot_json_parser_rejects_duplicate_keys_and_non_finite_numbers(
    payload: bytes,
) -> None:
    with pytest.raises(SnapshotValidationError, match="STRICT_JSON_INVALID"):
        json_object_from_bytes(payload, code="STRICT_JSON_INVALID")
    with pytest.raises(SnapshotValidationError, match="STRICT_JSON_INVALID"):
        json_value_from_bytes(payload, code="STRICT_JSON_INVALID")


def test_secret_placeholder_must_be_the_entire_value() -> None:
    assert not _contains_secret_or_authenticated_url(
        b'api_key = os.environ["THE_ODDS_API_KEY"]\n'
        b'url = "https://example.invalid?apiKey={api_key}"\n'
    )
    assert _contains_secret_or_authenticated_url(b'api_key = "real-prefix${ENV_KEY}"\n')
    assert _contains_secret_or_authenticated_url(
        b'authorization = "Bearer-real-prefix<redacted>"\n'
    )


@pytest.mark.parametrize(
    "key",
    (
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "password",
        "passwd",
        "private_key",
        "client_secret",
        "api_key",
        "auth",
        "authorization",
        "cookie",
        "set-cookie",
        "secret",
    ),
)
def test_recursive_json_secret_keys_are_detected(key: str) -> None:
    payload = canonical_json_bytes({"nested": {key: "real-value-0123456789"}})
    assert _contains_secret_or_authenticated_url(payload)


@pytest.mark.parametrize("placeholder", ("${TOKEN}", "<redacted>", "not_set"))
def test_recursive_json_secret_placeholders_require_a_full_match(placeholder: str) -> None:
    assert not _contains_secret_or_authenticated_url(
        canonical_json_bytes({"nested": {"access_token": placeholder}})
    )
    assert _contains_secret_or_authenticated_url(
        canonical_json_bytes({"nested": {"access_token": f"prefix-{placeholder}"}})
    )


@pytest.mark.parametrize(
    "assignment",
    (
        'api_key = os.environ["THE_ODDS_API_KEY"]',
        "api_key = os.environ['THE_ODDS_API_KEY']",
        'api_key = os.getenv("THE_ODDS_API_KEY")',
        "api_key = os.getenv('THE_ODDS_API_KEY')",
        "api_key = ${THE_ODDS_API_KEY}",
        'api_key = "${THE_ODDS_API_KEY}"',
        "api_key=${THE_ODDS_API_KEY}",
    ),
)
def test_source_assignment_allows_only_complete_environment_placeholders(
    assignment: str,
) -> None:
    assert not _contains_secret_or_authenticated_url((assignment + "\n").encode())


@pytest.mark.parametrize(
    "assignment",
    (
        "api_key = os.environ[",
        'api_key = os.environ["THE_ODDS_API_KEY"] + "-literal-suffix"',
        'api_key = "prefix-${THE_ODDS_API_KEY}"',
        "api_key = REAL${THE_ODDS_API_KEY}",
        'token = """actual-triple-quoted-token"""',
        "token = '''actual-triple-quoted-token'''",
        'refresh_token = "actual-refresh-token"',
        "cookie=session=actual-cookie",
    ),
)
def test_source_assignment_rejects_incomplete_mixed_or_literal_secrets(
    assignment: str,
) -> None:
    assert _contains_secret_or_authenticated_url((assignment + "\n").encode())


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid/object?X-Amz-Signature=deadbeefcafebabe",
        "https://example.invalid/object?X-Amz-Credential=scope",
        "https://example.invalid/object?X-Amz-Security-Token=actual-token",
        "https://example.invalid/container?sv=2025-01-01&sp=r&se=2026-08-17&sig=actual-sas",
        "https://storage.googleapis.invalid/object?X-Goog-Signature=deadbeefcafebabe",
        "https://storage.googleapis.invalid/object?GoogleAccessId=identity&Signature=actual",
    ),
)
def test_source_scan_rejects_signed_urls(url: str) -> None:
    assert _contains_secret_or_authenticated_url(canonical_json_bytes({"url": url}))


def test_source_scan_recurses_into_json_string_values_for_embedded_assignments() -> None:
    assert not _contains_secret_or_authenticated_url(
        canonical_json_bytes({"note": "api_key=${SOURCE_API_KEY}"})
    )
    assert _contains_secret_or_authenticated_url(
        canonical_json_bytes({"note": "api_key=actual-secret-0123456789"})
    )
    assert _contains_secret_or_authenticated_url(
        canonical_json_bytes({"note": "api_key=prefix-${SOURCE_API_KEY}"})
    )


def test_source_scan_duplicate_json_key_fallback_still_detects_embedded_secret() -> None:
    assert _contains_secret_or_authenticated_url(
        b'{"note":"safe","note":"api_key=actual-secret-0123456789"}'
    )


def test_source_scan_detects_signed_url_after_json_escape_decoding() -> None:
    assert _contains_secret_or_authenticated_url(
        rb'{"url":"https:\/\/example.invalid\/object?X-Amz-Signature=actual-signature"}'
    )
