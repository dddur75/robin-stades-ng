from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from botocore.exceptions import ClientError, EndpointConnectionError

from robin.historical_deep import coverage_evidence as coverage_evidence_module
from robin.historical_deep import coverage_proof as coverage_proof_module
from robin.historical_deep.contracts import load_campaign_contract
from robin.historical_deep.coverage_evidence import (
    FAMILY_COUNTS_SCHEMA_VERSION,
    ZERO_EFFECTS,
    CoverageAuthority,
    InventoryObject,
    PinnedInventoryReader,
    VerifiedEvidencePair,
    VerifiedInventory,
    aggregate_stage,
    build_partition_checkpoint,
    build_partition_plan,
    canonical_journal_suffix,
    deep_validate_inventory,
    evidence_architecture_fingerprint,
    load_authority,
    measure_partition,
    validate_stage_attempt,
)
from robin.historical_deep.coverage_proof import (
    DERIVED_PREFIX,
    NO_CENSUS_EVIDENCE_SOURCE,
    DerivedR2ReadOnlyStore,
    assert_secret_free,
    build_coverage_proof,
    render_coverage_csv,
    render_coverage_json,
    write_coverage_artifacts,
)
from robin.historical_deep.e1b_canary import (
    file_sha256_lf,
    require_selection_ready,
)
from robin.historical_deep.gates import GATE_NAMES
from robin.historical_deep.normalization import canonical_sha256
from robin.historical_deep.segmented_replay import (
    PROJECTION_SCHEMA_VERSION,
    STAGING_MANIFEST_SCHEMA_VERSION,
    STAGING_PART_SCHEMA_VERSION,
    STAGING_TABLES,
)
from scripts import run_p0_e1b_five_league_canary as e1b_runner
from scripts import run_p0_e2_capability_sample as e2_runner

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs" / "historical-deep-data-harvest-v1.json"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "81-historical-deep-coverage-proof-export.yml"
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
MODULE_PATH = ROOT / "src" / "robin" / "historical_deep" / "coverage_proof.py"
SCRIPT_PATH = ROOT / "scripts" / "export_historical_deep_coverage.py"
P0_MODULE_PATH = ROOT / "src" / "robin" / "historical_deep" / "coverage_evidence.py"
P0_SCRIPT_PATH = ROOT / "scripts" / "run_p0_coverage_evidence.py"

SOURCE_REVISION = "1" * 40
EXPORTER_REVISION = "2" * 40
SOURCE_RUN_TOKEN = "30593227942:1"
RECORDED_AT = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _ledger_hash(record: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _append_canonical_decision(
    root: Path,
    *,
    decision_id: str,
    context: Mapping[str, object],
) -> None:
    ledger = root / "reports/council/decision-ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    previous = json.loads(lines[-1])
    record: dict[str, object] = {
        "decision_id": decision_id,
        "record_type": "DECISION",
        "date": "2026-08-12T22:00:00Z",
        "proposal": "Synthetic canonical authority fixture.",
        "objections": [],
        "proof": [],
        "decision": "PASS_AND_SCALE",
        "dissent": None,
        "responsible": "TEST_ONLY",
        "context": dict(context),
        "previous_hash": previous["hash"],
        "hash_algorithm": "SHA-256",
    }
    record["hash"] = _ledger_hash(record)
    ledger.write_text(
        "\n".join([*lines, json.dumps(record, ensure_ascii=False, separators=(",", ":"))])
        + "\n",
        encoding="utf-8",
    )


def test_p0_authority_uses_only_the_exact_historical_matrix_snapshot(
    tmp_path: Path,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    assert authority.source_config_sha256 == (
        coverage_evidence_module.HISTORICAL_SOURCE_CONFIG_SHA256
    )
    assert authority.mission_sha256 == (
        coverage_evidence_module.HISTORICAL_MISSION_SHA256
    )
    assert authority.mapping_sha256 == (
        coverage_evidence_module.HISTORICAL_MAPPING_SHA256
    )
    current_matrix = ROOT / coverage_evidence_module.HISTORICAL_AUTHORITY_MATRIX_PATH
    snapshot = (
        ROOT / coverage_evidence_module.HISTORICAL_AUTHORITY_MATRIX_SNAPSHOT_PATH
    )
    assert coverage_evidence_module._lf_sha256(current_matrix) != (
        coverage_evidence_module.HISTORICAL_AUTHORITY_MATRIX_SHA256
    )
    assert coverage_evidence_module._lf_sha256(snapshot) == (
        coverage_evidence_module.HISTORICAL_AUTHORITY_MATRIX_SHA256
    )

    shutil.copytree(ROOT / "configs", tmp_path / "configs")
    temporary_snapshot = (
        tmp_path / coverage_evidence_module.HISTORICAL_AUTHORITY_MATRIX_SNAPSHOT_PATH
    )
    original_snapshot = temporary_snapshot.read_bytes()
    temporary_snapshot.unlink()
    with pytest.raises(ValueError, match="P0_CONTRACT_HASH_MISMATCH"):
        load_authority(
            tmp_path,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        )

    temporary_snapshot.write_bytes(original_snapshot + b" ")
    with pytest.raises(ValueError, match="P0_CONTRACT_HASH_MISMATCH"):
        load_authority(
            tmp_path,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        )

    temporary_snapshot.write_bytes(original_snapshot)
    source_path = tmp_path / coverage_evidence_module.SOURCE_CONFIG_PATH
    mission_path = tmp_path / coverage_evidence_module.MISSION_PATH
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["frozen_at"] = "2026-08-05T07:45:01Z"
    source_path.write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
    mission = json.loads(mission_path.read_text(encoding="utf-8"))
    mission["source_hash"] = coverage_evidence_module._lf_sha256(source_path)
    mission_path.write_text(json.dumps(mission, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="P0_CONTRACT_HASH_MISMATCH"):
        load_authority(
            tmp_path,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        )


def test_canonical_journal_boundary_revokes_legacy_e1b_and_e2_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = canonical_journal_suffix(ROOT)
    assert suffix[0]["decision_id"] == "RCV3-20260812-137"
    assert suffix[0]["record_type"] == "VETO"
    assert suffix[0]["decision"] == "PASS_AND_HOLD"

    e1b_hash = file_sha256_lf(
        ROOT / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    )
    with pytest.raises(ValueError, match="E1B_SELECTION_READY_DECISION_REQUIRED"):
        require_selection_ready(ROOT, e1b_hash)
    e2_selection = json.loads(
        (ROOT / "reports/evidence/e2/e2-selection-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(RuntimeError, match="E2_SELECTION_DECISION_MISSING"):
        e2_runner._require_ready(ROOT, str(e2_selection["selection_hash"]))

    def unexpected_reader(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("reader must not be constructed before canonical authority")

    monkeypatch.setattr(
        PinnedInventoryReader,
        "from_environment",
        unexpected_reader,
    )
    with pytest.raises(ValueError, match="E1B_SELECTION_READY_DECISION_REQUIRED"):
        e1b_runner._measure(ROOT, tmp_path / "e1b")
    with pytest.raises(RuntimeError, match="E2_SELECTION_DECISION_MISSING"):
        e2_runner._measure(ROOT, tmp_path / "e2")

    shutil.copytree(ROOT / "reports", tmp_path / "reports")
    ledger = tmp_path / "reports/council/decision-ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    boundary = json.loads(lines[129])
    boundary["decision"] = "PASS_AND_SCALE"
    canonical = json.dumps(
        {key: value for key, value in boundary.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    boundary["hash"] = hashlib.sha256(canonical).hexdigest()
    lines[129] = json.dumps(boundary, ensure_ascii=False, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_BOUNDARY_INVALID"):
        canonical_journal_suffix(tmp_path)


def test_canonical_journal_suffix_parser_and_exact_grants_fail_closed(
    tmp_path: Path,
) -> None:
    shutil.copytree(ROOT / "reports", tmp_path / "reports")
    ledger = tmp_path / "reports/council/decision-ledger.jsonl"
    original = ledger.read_text(encoding="utf-8").splitlines()

    ledger.write_text("\n".join(original[:129]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_BOUNDARY_MISSING"):
        canonical_journal_suffix(tmp_path)

    duplicate = original.copy()
    duplicate[129] = duplicate[129][:-1] + ',"decision":"PASS_AND_HOLD"}'
    ledger.write_text("\n".join(duplicate) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_JSON_INVALID"):
        canonical_journal_suffix(tmp_path)

    nonfinite = original.copy()
    nonfinite[129] = nonfinite[129][:-1] + ',"unsafe":NaN}'
    ledger.write_text("\n".join(nonfinite) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_JSON_INVALID"):
        canonical_journal_suffix(tmp_path)

    tampered = original.copy()
    tampered[-1] = tampered[-1].replace("PASS_AND_HOLD", "PASS_AND_SCALE", 1)
    ledger.write_text("\n".join(tampered) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_RECORD_HASH_INVALID"):
        canonical_journal_suffix(tmp_path)

    invalid_suffix = [json.loads(line) for line in original]
    invalid_suffix[-1]["record_type"] = "EVIDENCE_CORRECTION"
    invalid_suffix[-1]["hash"] = _ledger_hash(invalid_suffix[-1])
    ledger.write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in invalid_suffix
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="COUNCIL_JOURNAL_CANONICAL_SUFFIX_INVALID"):
        canonical_journal_suffix(tmp_path)

    ledger.write_text("\n".join(original) + "\n", encoding="utf-8")
    e1b_hash = file_sha256_lf(
        ROOT / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    )
    e2_selection = json.loads(
        (ROOT / "reports/evidence/e2/e2-selection-manifest-v1.json").read_text(
            encoding="utf-8"
        )
    )
    reviewers = ["DP5", "DP6", "C2"]
    _append_canonical_decision(
        tmp_path,
        decision_id="TEST-E1B-READY-1",
        context={
            "selection_state": "E1B_SELECTION_READY",
            "selection_sha256": e1b_hash,
            "reviewed_by": reviewers,
        },
    )
    _append_canonical_decision(
        tmp_path,
        decision_id="TEST-E2-READY-1",
        context={
            "selection_state": "E2_SELECTION_READY",
            "selection_hash": str(e2_selection["selection_hash"]),
            "reviewed_by": reviewers,
        },
    )
    require_selection_ready(tmp_path, e1b_hash)
    e2_runner._require_ready(tmp_path, str(e2_selection["selection_hash"]))

    _append_canonical_decision(
        tmp_path,
        decision_id="TEST-E1B-READY-2",
        context={
            "selection_state": "E1B_SELECTION_READY",
            "selection_sha256": e1b_hash,
            "reviewed_by": reviewers,
        },
    )
    with pytest.raises(ValueError, match="E1B_SELECTION_READY_DECISION_REQUIRED"):
        require_selection_ready(tmp_path, e1b_hash)

    _append_canonical_decision(
        tmp_path,
        decision_id="TEST-E2-READY-2",
        context={
            "selection_state": "E2_SELECTION_READY",
            "selection_hash": str(e2_selection["selection_hash"]),
            "reviewed_by": reviewers,
        },
    )
    with pytest.raises(RuntimeError, match="E2_SELECTION_DECISION_NOT_UNIQUE"):
        e2_runner._require_ready(tmp_path, str(e2_selection["selection_hash"]))


class MemoryDerivedReader:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {
            "historical-deep-data/schema-v1/competition=raw/payload.json.gz": b"raw"
        }
        self.iterated_prefixes: list[str] = []
        self.read_keys: list[str] = []
        self.write_attempts = 0

    def iter_keys(self, prefix: str) -> Iterable[str]:
        self.iterated_prefixes.append(prefix)
        return tuple(key for key in sorted(self.objects) if key.startswith(prefix))

    def get_object(self, key: str) -> bytes | None:
        self.read_keys.append(key)
        return self.objects.get(key)

    def put_if_absent(self, _key: str, _data: bytes) -> bool:
        self.write_attempts += 1
        raise AssertionError("the exporter must never call a write method")


class StubStreamingBody:
    def __init__(
        self,
        payload: bytes = b"",
        *,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.read_limits: list[int] = []

    def read(self, amount: int) -> bytes:
        self.read_limits.append(amount)
        if self.error is not None:
            raise self.error
        return self.payload[:amount]


class StubR2Client:
    def __init__(
        self,
        *,
        response: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or {}
        self.error = error

    def get_object(self, **_arguments: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        return self.response

    def list_objects_v2(self, **_arguments: object) -> dict[str, object]:
        if self.error is not None:
            raise self.error
        return self.response


def _r2_store(client: StubR2Client) -> DerivedR2ReadOnlyStore:
    store = object.__new__(DerivedR2ReadOnlyStore)
    setattr(store, "_client", client)
    setattr(store, "_bucket", "coverage-proof-test")
    return store


def _envelope_key(category: str, recorded_at: datetime, digest: str) -> str:
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{DERIVED_PREFIX}{category}/record-{timestamp}-{digest}.json.gz"


def _put_envelope(
    reader: MemoryDerivedReader,
    *,
    campaign_id: str,
    category: str,
    value: object,
    recorded_at: datetime,
) -> None:
    envelope = {
        "schema_version": "historical-deep-derived-envelope-v1",
        "campaign_id": campaign_id,
        "category": category,
        "recorded_at": recorded_at.isoformat(),
        "value": value,
    }
    digest = canonical_sha256(envelope)
    body = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    reader.objects[_envelope_key(category, recorded_at, digest)] = gzip.compress(
        body,
        compresslevel=9,
        mtime=0,
    )


def _sample_values(*, complete_census: bool = True) -> dict[str, dict[str, object]]:
    contract = load_campaign_contract(CONTRACT_PATH)
    observation = {
        "competition": "api-football:39",
        "provider_league_id": 39,
        "season": 2024,
        "field_matrix": {
            "players": {
                "advertised_flag": True,
                "sample_non_null_count": 10,
                "sample_denominator": 20,
                "sample_coverage_rate": 0.5,
                "evidence_source": "/players:page=1",
            }
        },
        "null_rates": {"players": 0.5},
    }
    if complete_census:
        census: dict[str, object] = {
            "schema_version": "historical-deep-census-run-v1",
            "status": "COMPLETE",
            "competition_count": 5,
            "observation_count": 1,
            "observations": [observation],
            "provider_calls": 5,
            "code_revision": SOURCE_REVISION,
            "run_token": SOURCE_RUN_TOKEN,
        }
        census["hash"] = canonical_sha256(census)
    else:
        census = {
            "schema_version": "historical-deep-bounded-run-v1",
            "status": "PARTIAL",
            "reason": "JOB_DURATION_LIMIT_REACHED",
            "provider_calls": 439,
            "tasks_completed": 4,
            "resume": "R2_RECEIPTS_AND_CHECKPOINT",
            "code_revision": SOURCE_REVISION,
            "run_token": SOURCE_RUN_TOKEN,
        }

    normalized_rows = [
        {
            "normalized_family": "players",
            "family": "players",
            "provider_competition_id": 39,
            "season": 2024,
            "temporal_class": "STATIC_PROFILE",
            "canonical_id": f"api-football:player:{player_id}",
            "data": {"display_name": f"private-source-row-{player_id}"},
            "source_request_params": {"page": 1},
        }
        for player_id in (7, 8)
    ]
    projection_hash = canonical_sha256(normalized_rows)
    projection = {
        "schema_version": "historical-deep-normalized-replay-v1",
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
        "rows": normalized_rows,
        "row_count": len(normalized_rows),
        "normalization_errors": [],
        "projection_hash": projection_hash,
        "provider_calls": 0,
    }

    entries = [
        {
            "receipt_id": "a" * 64,
            "payload_key": (
                "historical-deep-data/schema-v1/competition=api-football:39/"
                "season=2024/family=players/payload-b.json.gz"
            ),
            "payload_sha256": "b" * 64,
            "projection_sha256": "c" * 64,
        }
    ]
    replay_hash = canonical_sha256(entries)
    source_hash = canonical_sha256(
        [
            {
                "receipt_id": entry["receipt_id"],
                "payload_key": entry["payload_key"],
                "payload_sha256": entry["payload_sha256"],
            }
            for entry in entries
        ]
    )
    replay = {
        "status": "CACHE_ONLY_REPLAY_VERIFIED",
        "payloads_replayed": 1,
        "receipts_verified": 1,
        "provider_calls": 0,
        "provider_credits": 0,
        "hash_mismatches": 0,
        "missing_payloads": 0,
        "extra_payloads": 0,
        "source_hash": source_hash,
        "replay_hash": replay_hash,
        "expected_replay_hash": None,
        "hash_identical": True,
        "entries": entries,
        "normalized_rows": len(normalized_rows),
        "normalization_errors": [],
        "normalized_projection_hash": projection_hash,
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
    }
    quality_hash = "d" * 64
    quality = {
        "exact_replay": True,
        "before_hash": quality_hash,
        "after_hash": quality_hash,
        "mismatches": [],
        "null_to_zero_conversions": 0,
        "normalization_errors": [],
        "normalized_rows": len(normalized_rows),
        "targeted_rows": len(normalized_rows),
        "source_replay_hash": replay_hash,
        "source_projection_hash": projection_hash,
        "provider_calls": 0,
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
    }
    feature_manifests = {
        "schema_version": "historical-deep-feature-manifests-v1",
        "status": "COMPLETE",
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
        "feature_hash": "e" * 64,
        "bundle_count": 2,
        "dataset_manifests": {"PLAYER_PREMATCH_STRICT": {"row_count": 2}},
        "provider_calls": 0,
    }
    gates: dict[str, object] = {
        name: {
            "gate": name,
            "status": "PARTIAL",
            "eligible_seasons": [],
            "observed_seasons": [2024],
            "coverage_rate": 0.5,
            "identity_rate": 1.0,
            "reasons": ["ELIGIBLE_SEASONS:1"],
            "source_status": "AVAILABLE",
            "threshold": {},
            "status_counts": {"PARTIAL": 1},
            "code_revision": SOURCE_REVISION,
            "run_token": SOURCE_RUN_TOKEN,
        }
        for name in GATE_NAMES
    }
    gate_report = {
        "schema_version": "historical-deep-gate-report-v1",
        "status": "COMPLETE",
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
        "gate_hash": canonical_sha256(gates),
        "gates": gates,
        "provider_calls": 0,
    }
    report: dict[str, object] = {
        "schema_version": "historical-deep-report-v1",
        "campaign_id": contract.campaign_id,
        "verdict": "HISTORICAL_DEEP_DATA_HARVEST_PARTIAL",
        "provider": {},
        "replay": replay,
        "quality_v2": quality,
        "datasets": {},
        "gates": gates,
        "backtest": {},
        "fatal_errors": [],
        "partial_reasons": ["DATASET_EMPTY"],
        "safety": {
            "cache_only": True,
            "provider_calls_during_replay_and_backtest": 0,
            "new_purchases": False,
            "secrets_exposed": False,
            "r2_deletions": 0,
            "raw_payloads_in_git": 0,
            "real_bets": False,
        },
        "operations": {"coverage_census": census},
        "code_revision": SOURCE_REVISION,
        "run_token": SOURCE_RUN_TOKEN,
    }
    report["report_hash"] = canonical_sha256(report)
    return {
        "collection/census": census,
        "replay/projection": projection,
        "replay": replay,
        "quality": quality,
        "feature-manifests": feature_manifests,
        "gate-report": gate_report,
        "report": report,
    }


def _sample_reader(*, complete_census: bool = True) -> MemoryDerivedReader:
    return _reader_from_values(_sample_values(complete_census=complete_census))


def _manifest_projection_reader() -> MemoryDerivedReader:
    values = _sample_values()
    projection = values["replay/projection"]
    rows = list(projection.pop("rows"))
    continuation_id = "coverage-proof-test"
    inventory_sha256 = "9" * 64
    manifests: dict[str, object] = {}
    reader = MemoryDerivedReader()
    for table in STAGING_TABLES:
        table_rows = [row for row in rows if row["normalized_family"] == table]
        table_sha256 = canonical_sha256(table_rows)
        parts: list[dict[str, object]] = []
        if table_rows:
            part_sha256 = canonical_sha256(table_rows)
            key = (
                f"{DERIVED_PREFIX}staging-v3/continuation={continuation_id}/"
                f"inventory={inventory_sha256}/table={table}/"
                f"part-000001-{part_sha256}.json.gz"
            )
            part = {
                "schema_version": STAGING_PART_SCHEMA_VERSION,
                "continuation_id": continuation_id,
                "inventory_sha256": inventory_sha256,
                "table": table,
                "table_sha256": table_sha256,
                "part_ordinal": 1,
                "rows": table_rows,
                "row_count": len(table_rows),
                "part_sha256": part_sha256,
            }
            reader.objects[key] = gzip.compress(
                json.dumps(part, sort_keys=True, separators=(",", ":")).encode()
            )
            parts.append(
                {
                    "part_ordinal": 1,
                    "row_count": len(table_rows),
                    "part_sha256": part_sha256,
                    "staging_key": key,
                }
            )
        manifests[table] = {
            "schema_version": STAGING_MANIFEST_SCHEMA_VERSION,
            "row_count": len(table_rows),
            "table_sha256": table_sha256,
            "part_count": len(parts),
            "parts": parts,
            "created": True,
        }
    projection.update(
        {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "continuation_id": continuation_id,
            "inventory_sha256": inventory_sha256,
            "staging_tables": manifests,
        }
    )
    return _reader_from_values(values, reader=reader)


def _reader_from_values(
    values: dict[str, dict[str, object]],
    *,
    reader: MemoryDerivedReader | None = None,
) -> MemoryDerivedReader:
    contract = load_campaign_contract(CONTRACT_PATH)
    selected_reader = reader or MemoryDerivedReader()
    for offset, (category, value) in enumerate(values.items()):
        _put_envelope(
            selected_reader,
            campaign_id=contract.campaign_id,
            category=category,
            value=value,
            recorded_at=RECORDED_AT + timedelta(microseconds=offset),
        )
    return selected_reader


def _rehash_census_and_report(values: dict[str, dict[str, object]]) -> None:
    census = values["collection/census"]
    census.pop("hash", None)
    census["hash"] = canonical_sha256(census)
    report = values["report"]
    report.pop("report_hash", None)
    report["report_hash"] = canonical_sha256(report)


def _sample_census_evidence(
    values: dict[str, dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    census = values["collection/census"]
    observations = census["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    matrix = observation["field_matrix"]
    assert isinstance(matrix, dict)
    evidence = matrix["players"]
    assert isinstance(evidence, dict)
    null_rates = observation["null_rates"]
    assert isinstance(null_rates, dict)
    return evidence, null_rates


def _build(reader: MemoryDerivedReader) -> dict[str, object]:
    return build_coverage_proof(
        reader,
        contract=load_campaign_contract(CONTRACT_PATH),
        source_code_revision=SOURCE_REVISION,
        source_run_token=SOURCE_RUN_TOKEN,
        exporter_code_revision=EXPORTER_REVISION,
        generated_at=RECORDED_AT + timedelta(hours=1),
    )


def _all_mapping_keys(value: object) -> set[str]:
    output: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            output.add(str(key))
            output.update(_all_mapping_keys(item))
    elif isinstance(value, list):
        for item in value:
            output.update(_all_mapping_keys(item))
    return output


def test_export_is_lineage_pinned_compact_and_strictly_read_only() -> None:
    reader = _sample_reader()
    proof = _build(reader)

    assert proof["source_code_revision"] == SOURCE_REVISION
    assert proof["source_run_token"] == SOURCE_RUN_TOKEN
    assert proof["exporter_code_revision"] == EXPORTER_REVISION
    assert proof["contract_hash"] == load_campaign_contract(CONTRACT_PATH).contract_hash
    assert proof["coverage_count"] == 1
    assert proof["normalized_row_count"] == 2
    coverage = proof["coverage"]
    assert isinstance(coverage, list)
    assert coverage == [
        {
            "league": "Premier League",
            "season": 2024,
            "family": "players",
            "advertised_flag": True,
            "sample_verified_numerator": 10,
            "sample_verified_denominator": 20,
            "sample_verified_rate": 0.5,
            "sample_verified_basis": "/players:page=1",
            "normalized_row_count": 2,
            "null_rate": 0.5,
            "temporal_classes": ["STATIC_PROFILE"],
            "gate": "PLAYER",
            "gate_status": "PARTIAL",
            "gate_scope": "LINEAGE_GLOBAL",
        }
    ]
    assert proof["quality"] == {
        "exact_replay": True,
        "hash_identical": True,
        "hash_mismatches": 0,
        "missing_payloads": 0,
        "extra_payloads": 0,
        "provider_calls": 0,
        "provider_credits": 0,
    }
    forbidden = {"payload", "entries", "rows", "data", "parameters"}
    output_keys = _all_mapping_keys(proof)
    assert not forbidden & output_keys
    assert not any(name.endswith("_key") for name in output_keys)
    rendered = render_coverage_json(proof).decode("utf-8")
    assert "private-source-row" not in rendered
    assert "payload-b.json.gz" not in rendered
    assert all(prefix.startswith(DERIVED_PREFIX) for prefix in reader.iterated_prefixes)
    assert all(key.startswith(DERIVED_PREFIX) for key in reader.read_keys)
    assert reader.write_attempts == 0


def test_manifest_projection_is_hydrated_and_verified_from_derived_parts() -> None:
    reader = _manifest_projection_reader()
    proof = _build(reader)

    assert proof["normalized_row_count"] == 2
    staging_reads = [key for key in reader.read_keys if "/staging-v3/" in key]
    assert len(staging_reads) == 1
    assert reader.write_attempts == 0

    staging_key = staging_reads[0]
    part = json.loads(gzip.decompress(reader.objects[staging_key]))
    part["rows"][0]["season"] = 2023
    reader.objects[staging_key] = gzip.compress(
        json.dumps(part, sort_keys=True, separators=(",", ":")).encode()
    )
    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_PROJECTION_STAGING_INVALID:STAGING_PROJECTION_PART_CONTRACT_MISMATCH",
    ):
        _build(reader)


def test_partial_census_does_not_borrow_or_invent_sample_evidence() -> None:
    proof = _build(_sample_reader(complete_census=False))
    coverage = proof["coverage"]
    assert isinstance(coverage, list)
    assert coverage[0]["advertised_flag"] is None
    assert coverage[0]["sample_verified_numerator"] is None
    assert coverage[0]["sample_verified_denominator"] is None
    assert coverage[0]["sample_verified_rate"] is None
    assert coverage[0]["sample_verified_basis"] == NO_CENSUS_EVIDENCE_SOURCE
    assert coverage[0]["null_rate"] is None
    assert coverage[0]["normalized_row_count"] == 2


def test_source_lineage_and_hash_mismatches_fail_closed() -> None:
    reader = _sample_reader()
    with pytest.raises(
        ValueError,
        match=r"COVERAGE_PROOF_SOURCE_LINEAGE_MISSING:collection/census",
    ):
        build_coverage_proof(
            reader,
            contract=load_campaign_contract(CONTRACT_PATH),
            source_code_revision="3" * 40,
            source_run_token=SOURCE_RUN_TOKEN,
            exporter_code_revision=EXPORTER_REVISION,
        )

    values = _sample_values()
    values["replay/projection"]["row_count"] = 999
    tampered = MemoryDerivedReader()
    contract = load_campaign_contract(CONTRACT_PATH)
    for offset, (category, value) in enumerate(values.items()):
        _put_envelope(
            tampered,
            campaign_id=contract.campaign_id,
            category=category,
            value=value,
            recorded_at=RECORDED_AT + timedelta(microseconds=offset),
        )
    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_PROJECTION_ROW_COUNT_MISMATCH",
    ):
        _build(tampered)

    missing_features = _sample_values()
    missing_features.pop("feature-manifests")
    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_SOURCE_LINEAGE_MISSING:feature-manifests",
    ):
        _build(_reader_from_values(missing_features))

    missing_gate_report = _sample_values()
    missing_gate_report.pop("gate-report")
    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_SOURCE_LINEAGE_MISSING:gate-report",
    ):
        _build(_reader_from_values(missing_gate_report))


def test_lineage_selection_streams_history_and_retains_latest_match() -> None:
    class InterleavedReader(MemoryDerivedReader):
        def iter_keys(self, prefix: str) -> Iterable[str]:
            self.iterated_prefixes.append(prefix)
            previous: str | None = None
            for key in sorted(self.objects):
                if not key.startswith(prefix):
                    continue
                if previous is not None and previous not in self.read_keys:
                    raise AssertionError("keys were materialized before object reads")
                yield key
                previous = key

    values = _sample_values()
    reader = _reader_from_values(values, reader=InterleavedReader())
    contract = load_campaign_contract(CONTRACT_PATH)
    base = values["collection/census"]
    for offset in range(128):
        historical = dict(base)
        historical["provider_calls"] = offset
        historical["code_revision"] = SOURCE_REVISION if offset == 127 else "3" * 40
        historical.pop("hash", None)
        historical["hash"] = canonical_sha256(historical)
        _put_envelope(
            reader,
            campaign_id=contract.campaign_id,
            category="collection/census",
            value=historical,
            recorded_at=RECORDED_AT - timedelta(seconds=128 - offset),
        )

    proof = _build(reader)

    assert proof["coverage_count"] == 1
    assert len(reader.read_keys) == 128 + len(_sample_values())


def test_duplicate_latest_lineage_envelopes_remain_ambiguous() -> None:
    values = _sample_values()
    reader = _reader_from_values(values)
    duplicate = dict(values["collection/census"])
    duplicate["provider_calls"] = 999
    duplicate.pop("hash", None)
    duplicate["hash"] = canonical_sha256(duplicate)
    _put_envelope(
        reader,
        campaign_id=load_campaign_contract(CONTRACT_PATH).campaign_id,
        category="collection/census",
        value=duplicate,
        recorded_at=RECORDED_AT,
    )

    with pytest.raises(
        ValueError,
        match=r"COVERAGE_PROOF_SOURCE_LINEAGE_AMBIGUOUS:collection/census",
    ):
        _build(reader)


def test_duplicate_listed_record_key_is_rejected() -> None:
    class DuplicateKeyReader(MemoryDerivedReader):
        def iter_keys(self, prefix: str) -> Iterable[str]:
            keys = tuple(key for key in sorted(self.objects) if key.startswith(prefix))
            for key in keys:
                yield key
                yield key

    reader = _reader_from_values(_sample_values(), reader=DuplicateKeyReader())
    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_DERIVED_RECORD_KEY_DUPLICATE",
    ):
        _build(reader)


@pytest.mark.parametrize(
    "evidence_source",
    [
        "fixtures_sample_and_bundle",
        "/players:page=1",
        "/injuries",
        "/standings",
    ],
)
def test_evidence_source_accepts_only_actual_producer_values(
    evidence_source: str,
) -> None:
    values = _sample_values()
    evidence, _null_rates = _sample_census_evidence(values)
    evidence["evidence_source"] = evidence_source
    _rehash_census_and_report(values)

    coverage = _build(_reader_from_values(values))["coverage"]

    assert isinstance(coverage, list)
    assert coverage[0]["sample_verified_basis"] == evidence_source


@pytest.mark.parametrize(
    ("evidence_source", "expected_error"),
    [
        ("/players:page=1\n", "COVERAGE_PROOF_CENSUS_BASIS_CONTROL_INVALID"),
        (" =HYPERLINK(1)", "COVERAGE_PROOF_CENSUS_BASIS_FORMULA_PREFIX_INVALID"),
        ("https://example.invalid", "COVERAGE_PROOF_CENSUS_BASIS_NOT_ALLOWED"),
    ],
)
def test_evidence_source_controls_formulas_and_unknown_values_fail_closed(
    evidence_source: str,
    expected_error: str,
) -> None:
    values = _sample_values()
    evidence, _null_rates = _sample_census_evidence(values)
    evidence["evidence_source"] = evidence_source
    _rehash_census_and_report(values)

    with pytest.raises(ValueError, match=expected_error):
        _build(_reader_from_values(values))


@pytest.mark.parametrize(
    ("numerator", "denominator", "rate", "null_rate", "expected_error"),
    [
        (1, None, None, None, "SAMPLE_TRIPLET_INCONSISTENT"),
        (None, 20, 0.5, 0.5, "SAMPLE_TRIPLET_INCONSISTENT"),
        (10, 20, None, None, "SAMPLE_TRIPLET_INCONSISTENT"),
        (0, 0, 0.0, 1.0, "SAMPLE_TRIPLET_INCONSISTENT"),
        (0, 0, None, 1.0, "NULL_RATE_MISMATCH"),
        (10, 20, 0.4, 0.6, "SAMPLE_RATE_MISMATCH"),
    ],
)
def test_census_sample_triplet_and_null_rate_inconsistencies_fail_closed(
    numerator: int | None,
    denominator: int | None,
    rate: float | None,
    null_rate: float | None,
    expected_error: str,
) -> None:
    values = _sample_values()
    evidence, null_rates = _sample_census_evidence(values)
    evidence["sample_non_null_count"] = numerator
    evidence["sample_denominator"] = denominator
    evidence["sample_coverage_rate"] = rate
    null_rates["players"] = null_rate
    if denominator is None:
        evidence["evidence_source"] = None
    _rehash_census_and_report(values)

    with pytest.raises(ValueError, match=expected_error):
        _build(_reader_from_values(values))


def test_valid_partial_census_triplets_are_preserved_without_invention() -> None:
    values = _sample_values()
    evidence, null_rates = _sample_census_evidence(values)
    evidence["sample_non_null_count"] = 0
    evidence["sample_denominator"] = None
    evidence["sample_coverage_rate"] = None
    evidence["evidence_source"] = None
    null_rates["players"] = None
    _rehash_census_and_report(values)

    coverage = _build(_reader_from_values(values))["coverage"]

    assert isinstance(coverage, list)
    assert coverage[0]["sample_verified_numerator"] == 0
    assert coverage[0]["sample_verified_denominator"] is None
    assert coverage[0]["sample_verified_rate"] is None
    assert coverage[0]["sample_verified_basis"] == NO_CENSUS_EVIDENCE_SOURCE
    assert coverage[0]["null_rate"] is None


@pytest.mark.parametrize("renderer", [render_coverage_json, render_coverage_csv])
def test_renderers_recompute_and_verify_proof_hash(
    renderer: Callable[[Mapping[str, object]], bytes],
) -> None:
    proof = _build(_sample_reader())
    proof["exporter_code_revision"] = "3" * 40

    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_OUTPUT_PROOF_HASH_MISMATCH",
    ):
        renderer(proof)


def test_renderers_reject_formula_basis_even_with_recomputed_proof_hash() -> None:
    proof = _build(_sample_reader())
    coverage = proof["coverage"]
    assert isinstance(coverage, list)
    coverage[0]["sample_verified_basis"] = "=HYPERLINK(1)"
    proof["proof_hash"] = canonical_sha256(
        {key: value for key, value in proof.items() if key != "proof_hash"}
    )

    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_CENSUS_BASIS_FORMULA_PREFIX_INVALID",
    ):
        render_coverage_csv(proof)


@pytest.mark.parametrize(
    ("league", "expected_error"),
    [
        ("=HYPERLINK(1)", "COVERAGE_PROOF_CSV_FORMULA_PREFIX_INVALID"),
        ("Premier\nLeague", "COVERAGE_PROOF_CSV_CONTROL_CHARACTER_INVALID"),
    ],
)
def test_csv_rejects_unsafe_text_in_every_string_field(
    league: str,
    expected_error: str,
) -> None:
    proof = _build(_sample_reader())
    coverage = proof["coverage"]
    assert isinstance(coverage, list)
    coverage[0]["league"] = league
    proof["proof_hash"] = canonical_sha256(
        {key: value for key, value in proof.items() if key != "proof_hash"}
    )

    with pytest.raises(ValueError, match=expected_error):
        render_coverage_csv(proof)


def test_r2_reader_rejects_content_length_before_streaming_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coverage_proof_module, "MAX_SOURCE_OBJECT_BYTES", 8)
    body = StubStreamingBody(b"x" * 32)
    store = _r2_store(StubR2Client(response={"ContentLength": 9, "Body": body}))

    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_SOURCE_OBJECT_TOO_LARGE",
    ):
        store.get_object(f"{DERIVED_PREFIX}report/object.json.gz")

    assert body.read_limits == []


def test_r2_reader_bounds_stream_read_and_rejects_oversize_afterward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coverage_proof_module, "MAX_SOURCE_OBJECT_BYTES", 8)
    body = StubStreamingBody(b"x" * 32)
    store = _r2_store(StubR2Client(response={"Body": body}))

    with pytest.raises(
        ValueError,
        match="COVERAGE_PROOF_SOURCE_OBJECT_TOO_LARGE",
    ):
        store.get_object(f"{DERIVED_PREFIX}report/object.json.gz")

    assert body.read_limits == [9]


@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="https://credential-bearing-endpoint.invalid"),
        ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "secret endpoint details",
                }
            },
            "GetObject",
        ),
    ],
)
def test_r2_get_exceptions_are_sanitized(error: Exception) -> None:
    store = _r2_store(StubR2Client(error=error))

    with pytest.raises(RuntimeError) as captured:
        store.get_object(f"{DERIVED_PREFIX}report/object.json.gz")

    assert str(captured.value) == "COVERAGE_PROOF_R2_GET_FAILED"
    assert captured.value.__cause__ is None
    assert "endpoint" not in str(captured.value).casefold()
    assert "secret" not in str(captured.value).casefold()


def test_r2_stream_and_list_exceptions_are_sanitized() -> None:
    stream_error = EndpointConnectionError(
        endpoint_url="https://credential-bearing-endpoint.invalid"
    )
    stream_store = _r2_store(StubR2Client(response={"Body": StubStreamingBody(error=stream_error)}))
    with pytest.raises(RuntimeError) as stream_captured:
        stream_store.get_object(f"{DERIVED_PREFIX}report/object.json.gz")
    assert str(stream_captured.value) == "COVERAGE_PROOF_R2_GET_FAILED"
    assert stream_captured.value.__cause__ is None

    list_store = _r2_store(StubR2Client(error=stream_error))
    with pytest.raises(RuntimeError) as list_captured:
        tuple(list_store.iter_keys(f"{DERIVED_PREFIX}report/"))
    assert str(list_captured.value) == "COVERAGE_PROOF_R2_LIST_FAILED"
    assert list_captured.value.__cause__ is None


def test_r2_client_initialization_exception_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_endpoint_error(_environment: Mapping[str, str]) -> None:
        raise EndpointConnectionError(endpoint_url="https://credential-bearing-endpoint.invalid")

    monkeypatch.setattr(
        coverage_proof_module,
        "create_r2_client",
        raise_endpoint_error,
    )

    with pytest.raises(RuntimeError) as captured:
        DerivedR2ReadOnlyStore({})

    assert str(captured.value) == "COVERAGE_PROOF_R2_INIT_FAILED"
    assert captured.value.__cause__ is None


def test_json_csv_allowlist_secret_scan_and_size_bound(tmp_path: Path) -> None:
    proof = _build(_sample_reader())
    json_bytes = render_coverage_json(proof)
    csv_bytes = render_coverage_csv(proof)
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert len(rows) == 1
    assert rows[0]["league"] == "Premier League"
    assert rows[0]["temporal_classes"] == "STATIC_PROFILE"
    assert "source_code_revision" not in rows[0]

    secret = "R2-SECRET-DO-NOT-EXPORT"
    assert_secret_free(json_bytes, secret_values=(secret,))
    with pytest.raises(ValueError, match="COVERAGE_PROOF_SECRET_VALUE_DETECTED"):
        assert_secret_free(
            json_bytes + secret.encode("utf-8"),
            secret_values=(secret,),
        )
    with pytest.raises(ValueError, match="COVERAGE_PROOF_SECRET_PATTERN_DETECTED"):
        assert_secret_free(b"authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(ValueError, match="COVERAGE_PROOF_OUTPUT_TOO_LARGE"):
        write_coverage_artifacts(
            proof,
            output_directory=tmp_path,
            max_output_bytes=1_000,
        )

    json_path, csv_path = write_coverage_artifacts(
        proof,
        output_directory=tmp_path,
        max_output_bytes=100_000,
        secret_values=(secret,),
    )
    assert json_path.read_bytes() == json_bytes
    assert csv_path.read_bytes() == csv_bytes


def test_workflow_81_preserves_legacy_call_and_export_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    dispatch = triggers["workflow_dispatch"]
    call = triggers["workflow_call"]
    assert isinstance(dispatch, dict)
    assert isinstance(call, dict)
    assert set(dispatch["inputs"]) == {
        "operation",
        "stage",
        "attempt_slot",
        "source_code_revision",
        "source_run_token",
        "max_output_bytes",
    }
    assert dispatch["inputs"]["operation"] == {
        "description": "Opération autorisée (legacy, gel, mesure, ou reprise sans R2)",
        "type": "choice",
        "required": True,
        "default": "legacy_export",
        "options": ["legacy_export", "freeze", "measure", "recover_measure"],
    }
    assert dispatch["inputs"]["stage"]["options"] == [
        "E1A",
        "E1B",
        "E2",
        "E3A",
        "E3B",
        "E4",
    ]
    assert dispatch["inputs"]["attempt_slot"] == {
        "description": "Créneau borné de la même architecture (1 puis 2, jamais 3)",
        "type": "choice",
        "required": True,
        "default": "1",
        "options": ["1", "2"],
    }
    assert dispatch["inputs"]["source_code_revision"]["required"] is False
    assert dispatch["inputs"]["source_run_token"]["required"] is False
    assert set(call["inputs"]) == set(dispatch["inputs"])
    assert call["inputs"]["operation"] == {
        "type": "string",
        "required": False,
        "default": "legacy_export",
    }
    assert call["inputs"]["stage"] == {
        "type": "string",
        "required": False,
        "default": "E1A",
    }
    assert call["inputs"]["attempt_slot"] == {
        "type": "string",
        "required": False,
        "default": "1",
    }
    assert call["inputs"]["source_code_revision"]["required"] is True
    assert call["inputs"]["source_run_token"]["required"] is True
    for trigger in (dispatch, call):
        assert trigger["inputs"]["max_output_bytes"]["type"] == "number"
        assert trigger["inputs"]["max_output_bytes"]["default"] == 2_000_000
    assert set(call["secrets"]) == {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }
    assert "API_FOOTBALL_KEY" not in text
    assert 'API_FOOTBALL_CALLS_ALLOWED: "0"' in text
    assert 'ODDS_API_CREDITS_ALLOWED: "0"' in text
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert workflow["concurrency"] == {
        "group": "${{ inputs.operation == 'legacy_export' && "
        "'historical-deep-r2-coverage-proof' || 'coverage-evidence-manual' }}",
        "cancel-in-progress": False,
    }
    job = workflow["jobs"]["export"]
    assert job["if"] == "${{ inputs.operation == 'legacy_export' }}"
    assert job["timeout-minutes"] == 20
    assert job["env"]["MAX_OUTPUT_BYTES"] == "${{ inputs.max_output_bytes }}"
    steps = job["steps"]
    source_checkout = next(
        step for step in steps if step.get("name") == "Checkout du contrat source exact"
    )
    assert source_checkout["with"]["ref"] == "${{ inputs.source_code_revision }}"
    export_step = next(
        step
        for step in steps
        if "scripts/export_historical_deep_coverage.py" in str(step.get("run", ""))
    )
    assert '--max-output-bytes "${MAX_OUTPUT_BYTES}"' in export_step["run"]
    assert "inputs.max_output_bytes" not in export_step["run"]
    upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
    paths = upload["with"]["path"]
    assert paths == (
        "artifacts/historical-deep-coverage-proof/coverage-proof.json\n"
        "artifacts/historical-deep-coverage-proof/coverage-proof.csv\n"
    )
    assert "**" not in paths


def test_workflow_81_p0_lane_is_branch_locked_read_only_and_bounded() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert set(jobs) == {
        "export",
        "ladder-guard",
        "freeze",
        "plan",
        "attempt-reservation",
        "measure",
        "recovery-guard",
        "aggregate",
    }
    assert all(1 <= job["timeout-minutes"] <= 20 for name, job in jobs.items() if name != "measure")

    guard = jobs["ladder-guard"]
    assert guard["if"] == "${{ inputs.operation != 'legacy_export' }}"
    assert guard["env"]["EXACT_LADDER_REF"] == ("refs/heads/codex/p0-coverage-evidence-ladder-v1")
    guard_step = guard["steps"][0]
    assert guard_step["env"]["REQUESTED_REF"] == "${{ github.ref }}"
    guard_source = guard_step["run"]
    for token in (
        '"freeze", "measure", "recover_measure"',
        '"E1A", "E1B", "E2", "E3A", "E3B", "E4"',
        'os.environ["EVENT_NAME"] != "workflow_dispatch"',
        'os.environ["RUN_ATTEMPT"] != "1"',
        'os.environ["ATTEMPT_SLOT"] not in {"1", "2"}',
        'os.environ["REQUESTED_REF"] != os.environ["EXACT_LADDER_REF"]',
    ):
        assert token in guard_source
    assert guard["steps"][1] == {
        "uses": "actions/checkout@v4",
        "with": {"persist-credentials": False},
    }
    exact_ci_step = guard["steps"][2]
    assert exact_ci_step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "EXACT_HEAD_SHA": "${{ github.sha }}",
        "REPOSITORY": "${{ github.repository }}",
        "EXACT_LADDER_BRANCH": "codex/p0-coverage-evidence-ladder-v1",
    }
    exact_ci_source = exact_ci_step["run"]
    for token in (
        "actions/workflows/ci.yml/runs",
        'test "$(git rev-parse HEAD)" = "${EXACT_HEAD_SHA}"',
        "git/ref/heads/${EXACT_LADDER_BRANCH}",
        '-f branch="${EXACT_LADDER_BRANCH}"',
        '-f head_sha="${EXACT_HEAD_SHA}"',
        "P0_REMOTE_BRANCH_HEAD_MOVED",
        "P0_EXACT_HEAD_PUSH_CI_SUCCESS_REQUIRED",
        'run.get("event") == "push"',
        'run.get("head_branch") == os.environ["EXACT_LADDER_BRANCH"]',
        'newest.get("conclusion") != "success"',
        "newest = max(",
        "P0_EXACT_HEAD_PUSH_CI_RUN_REQUIRED",
    ):
        assert token in exact_ci_source
    assert "-f status=completed" not in exact_ci_source

    freeze = jobs["freeze"]
    plan = jobs["plan"]
    reservation = jobs["attempt-reservation"]
    measure = jobs["measure"]
    recovery = jobs["recovery-guard"]
    aggregate = jobs["aggregate"]
    assert freeze["needs"] == "attempt-reservation"
    assert freeze["if"] == (
        "${{ always() && inputs.operation == 'freeze' && "
        "needs.attempt-reservation.result == 'success' }}"
    )
    assert plan["needs"] == "ladder-guard"
    assert reservation["needs"] == ["ladder-guard", "plan"]
    assert measure["needs"] == ["plan", "attempt-reservation"]
    assert recovery["needs"] == "ladder-guard"
    assert aggregate["needs"] == ["attempt-reservation", "measure", "recovery-guard"]
    assert measure["strategy"] == {
        "fail-fast": False,
        "max-parallel": 5,
        "matrix": "${{ fromJSON(needs.plan.outputs.matrix) }}",
    }
    assert measure["timeout-minutes"] == 15
    measurement_step = next(
        step for step in measure["steps"] if step.get("id") == "partition_measurement"
    )
    assert measurement_step["continue-on-error"] is True
    assert measurement_step["timeout-minutes"] == (
        "${{ (inputs.stage == 'E1A' || inputs.stage == 'E1B' || "
        "inputs.stage == 'E4') && 4 || (inputs.stage == 'E2' && 9 || 14) }}"
    )
    assert plan["outputs"] == {"matrix": "${{ steps.partition-plan.outputs.matrix }}"}
    assert plan["env"]["SELECTION_PATH"] == (
        "configs/data/p0-coverage-evidence-selection-${{ inputs.stage }}-v1.json"
    )
    assert measure["env"]["SELECTION_PATH"] == plan["env"]["SELECTION_PATH"]
    assert aggregate["env"]["SELECTION_PATH"] == plan["env"]["SELECTION_PATH"]

    r2_secret_names = {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }
    secret_steps: list[tuple[str, str]] = []
    for job_name, job in jobs.items():
        assert not any("secrets." in str(value) for value in job.get("env", {}).values())
        for step in job["steps"]:
            secret_env = {
                key: value for key, value in step.get("env", {}).items() if "secrets." in str(value)
            }
            if secret_env:
                assert set(secret_env) == r2_secret_names
                assert set(step["env"]) == r2_secret_names
                secret_steps.append((job_name, step["name"]))
    assert secret_steps == [
        ("export", "Exporter la preuve R2 dérivée et sanitizée"),
        ("freeze", "Geler la sélection par lectures R2 exactes"),
        ("measure", "Mesurer une partition par lectures R2 exactes"),
    ]
    for job in (freeze, measure):
        secret_step = next(
            step
            for step in job["steps"]
            if any("secrets." in str(value) for value in step.get("env", {}).values())
        )
        secret_source = str(secret_step["run"])
        assert secret_source.index(
            "git/ref/heads/${EXACT_LADDER_BRANCH}"
        ) < secret_source.index("run_p0_coverage_evidence.py")
    reservation_identity_index = next(
        index
        for index, step in enumerate(reservation["steps"])
        if step.get("id") == "reserve"
    )
    reservation_revalidation_indices = [
        index
        for index, step in enumerate(reservation["steps"])
        if "git/ref/heads/${GITHUB_REF_NAME}" in str(step.get("run", ""))
    ]
    reservation_upload_index = next(
        index
        for index, step in enumerate(reservation["steps"])
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert reservation_revalidation_indices[0] < reservation_identity_index
    assert reservation_identity_index < reservation_revalidation_indices[-1]
    assert reservation_revalidation_indices[-1] < reservation_upload_index
    for forbidden in (
        "API_FOOTBALL_KEY",
        "DATABASE_URL",
        "SUPABASE_DB_URL",
        "ODDS_API_KEY",
        "provider_factory",
        "run_historical_deep_harvest.py",
    ):
        assert forbidden not in text

    freeze_commands = "\n".join(str(step.get("run", "")) for step in freeze["steps"])
    plan_commands = "\n".join(str(step.get("run", "")) for step in plan["steps"])
    measure_commands = "\n".join(str(step.get("run", "")) for step in measure["steps"])
    aggregate_commands = "\n".join(str(step.get("run", "")) for step in aggregate["steps"])
    recovery_commands = "\n".join(str(step.get("run", "")) for step in recovery["steps"])
    reservation_commands = "\n".join(str(step.get("run", "")) for step in reservation["steps"])
    assert "run_p0_coverage_evidence.py freeze" in freeze_commands
    assert '--stage "${STAGE}"' in freeze_commands
    assert "--output-directory artifacts/p0-coverage-evidence/freeze" in freeze_commands
    assert "run_p0_coverage_evidence.py plan" in plan_commands
    assert '--selection "${SELECTION_PATH}"' in plan_commands
    assert 'test "${partition_count}" -le 120' in plan_commands
    assert "[.matrix.include[].partition_id] | unique | length" in plan_commands
    assert 'keys == ["include"]' in plan_commands
    assert 'keys == ["partition_id"]' in plan_commands
    assert 'test("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")' in plan_commands
    assert "'.max_parallel'" in plan_commands
    assert "-eq 5" in plan_commands
    assert "jq -c '.matrix'" in plan_commands
    assert "run_p0_coverage_evidence.py measure" in measure_commands
    assert '--partition-id "${PARTITION_ID}"' in measure_commands
    assert "--output-directory artifacts/p0-coverage-evidence/shard" in measure_commands
    assert 'os.environ["PARTITION_ID"]' in measure_commands
    assert "P0_PARTITION_ID_UNSAFE" in measure_commands
    assert 'Path("artifacts/p0-coverage-evidence/shards") / partition_id' in measure_commands
    for output_name in (
        "partition-receipt.json",
        "family-counts.json",
        "cost-report.json",
        "checkpoint-start.json",
        "checkpoint-final.json",
    ):
        assert output_name in measure_commands
    assert "run_p0_coverage_evidence.py checkpoint" in measure_commands
    assert "--status STARTED" in measure_commands
    assert "run_p0_coverage_evidence.py aggregate" in aggregate_commands
    assert '--attempt-slot "${ATTEMPT_SLOT}"' in aggregate_commands
    assert aggregate["env"]["ATTEMPT_SLOT"] == "${{ inputs.attempt_slot }}"
    assert "--shards-directory artifacts/p0-coverage-evidence/shards" in aggregate_commands
    assert recovery["if"] == "${{ inputs.operation == 'recover_measure' }}"
    assert recovery["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "run_p0_coverage_evidence.py preflight" in recovery_commands
    assert "--operation measure" in recovery_commands
    assert '--attempt-slot "${ATTEMPT_SLOT}"' in recovery_commands
    assert "target_marker" in recovery_commands
    assert "P0_RECOVERY_MARKER_SEQUENCE_INVALID" in recovery_commands
    assert "P0_RECOVERY_EXACT_REVISION_REQUIRED" in recovery_commands
    assert "P0_RECOVERY_EXACT_FAILED_RUN_REQUIRED" in recovery_commands
    assert "P0_RECOVERY_RESERVATION_INVALID" in recovery_commands
    assert "/actions/runs/${run_id}/attempts/1" in recovery_commands
    assert 'IN("failure", "cancelled", "timed_out")' in recovery_commands
    assert "(.run_attempt == 1)" in recovery_commands
    assert '(.event == "workflow_dispatch")' in recovery_commands
    assert "(.head_branch == $branch)" in recovery_commands
    assert '(.path | split("@")[0])' in recovery_commands
    assert "gh run download" in recovery_commands
    assert '"marker_retention_days": 90' in recovery_commands
    assert "P0_DURABLE_ATTEMPT_ALREADY_RESERVED" in reservation_commands
    assert "P0_ATTEMPT_RESUME_ALREADY_USED" in reservation_commands
    assert "P0_ATTEMPT_RESUME_BLOCKED_AFTER_SECOND_ATTEMPT" in reservation_commands
    assert "P0_ATTEMPT_RESUME_REQUIRES_MINIMAL_FIX_REVISION" in reservation_commands
    assert "P0_ATTEMPT_RESUME_SOURCE_RUN_INVALID" in reservation_commands
    assert "P0_ATTEMPT_RESUME_REQUIRES_UNCONSUMED_FREEZE" in reservation_commands
    assert "P0_ATTEMPT_RESUME_RESERVATION_INVALID" in reservation_commands
    assert "PREVIOUS_FREEZE_JOB_SKIPPED_BEFORE_SECRET_MOUNT" in reservation_commands
    assert 'test "${OPERATION}" = "freeze"' in reservation_commands
    assert "/actions/runs/${prior_run_id}/attempts/1" in reservation_commands
    assert '.name == "freeze" and .conclusion == "skipped"' in reservation_commands
    assert "attempt-resume.json" in reservation_commands
    assert "/actions/artifacts?name=$1" in reservation_commands
    assert "P0_SECOND_ATTEMPT_REQUIRES_FIRST" in reservation_commands
    assert "P0_SECOND_ATTEMPT_REQUIRES_MINIMAL_FIX_REVISION" in reservation_commands
    assert "P0_MISSION_ARCHITECTURE_LIMIT_EXCEEDED" in reservation_commands
    assert "P0_NEW_MISSION_REQUIRED_AFTER_UNRECORDED_FREEZE" in reservation_commands
    assert "P0_MISSION_ARCHITECTURE_ROLLBACK_FORBIDDEN" in reservation_commands
    assert "gh api --paginate" in reservation_commands
    assert "unexpired-artifacts.tsv" in reservation_commands
    assert "evidence_architecture_fingerprint" in reservation_commands
    assert '--operation "${OPERATION}"' in reservation_commands
    assert '--attempt-slot "${ATTEMPT_SLOT}"' in reservation_commands
    assert '"github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"]' in reservation_commands
    assert '"mission_expires_at": mission.get("expires_at")' in reservation_commands
    assert '"marker_retention_days": 90' in reservation_commands
    reservation_upload = next(
        step for step in reservation["steps"] if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert reservation_upload["with"]["retention-days"] == 90
    assert reservation_upload["if"] == (
        "${{ steps.attempt-audit.outputs.reuse_reservation != 'true' }}"
    )
    resume_upload = next(
        step
        for step in reservation["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
        and step["with"]["path"].endswith("attempt-resume.json")
    )
    assert resume_upload["if"] == ("${{ steps.attempt-audit.outputs.reuse_reservation == 'true' }}")
    assert resume_upload["with"]["name"] == "${{ steps.reserve.outputs.resume_marker }}"
    assert resume_upload["with"]["retention-days"] == 90

    ci_source = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert ci_source.count("scripts/run_p0_coverage_evidence.py") == 4

    expected_upload_paths = {
        "export": (
            "artifacts/historical-deep-coverage-proof/coverage-proof.json\n"
            "artifacts/historical-deep-coverage-proof/coverage-proof.csv\n"
        ),
        "freeze": (
            "artifacts/p0-coverage-evidence/freeze/selection-manifest.json\n"
            "artifacts/p0-coverage-evidence/freeze/freeze-receipt.json\n"
            "artifacts/p0-coverage-evidence/freeze/cost-report.json\n"
        ),
        "plan": "artifacts/p0-coverage-evidence/plan/partition-plan.json",
        "attempt-reservation": ("artifacts/p0-coverage-evidence/attempt/attempt-reservation.json"),
        "measure": "artifacts/p0-coverage-evidence/shards",
        "aggregate": (
            "artifacts/p0-coverage-evidence/stage/stage-receipt.json\n"
            "artifacts/p0-coverage-evidence/stage/coverage-feed.json\n"
            "artifacts/p0-coverage-evidence/stage/gate-report.json\n"
            "artifacts/p0-coverage-evidence/stage/cost-report.json\n"
        ),
    }
    for job_name, expected_path in expected_upload_paths.items():
        uploads = [
            step
            for step in jobs[job_name]["steps"]
            if step.get("uses") == "actions/upload-artifact@v4"
        ]
        assert any(upload["with"]["path"] == expected_path for upload in uploads)
        assert "**" not in expected_path
    progress_upload = next(
        step
        for step in measure["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
        and step["with"]["path"].endswith("checkpoint-start.json")
    )
    assert progress_upload["with"]["compression-level"] == 0
    download = next(
        step for step in aggregate["steps"] if step.get("uses") == "actions/download-artifact@v4"
    )
    assert download["if"] == "${{ inputs.operation == 'measure' }}"
    assert download["with"] == {
        "pattern": "p0-coverage-evidence-shard-${{ inputs.stage }}-*",
        "path": "artifacts/p0-coverage-evidence/shards",
        "merge-multiple": True,
    }


def test_exporter_source_has_no_provider_or_r2_write_surface() -> None:
    module = MODULE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "put_object" not in module
    assert "put_if_absent" not in module
    assert "ApiFootball" not in module + script
    assert "provider_factory" not in module + script
    assert "validate_r2_round_trip" not in module + script
    assert "API_FOOTBALL_KEY" not in module
    assert "API_FOOTBALL_KEY_MUST_NOT_BE_MOUNTED" in script
    assert "DERIVED_PREFIX" in module


def _synthetic_p0_inventory() -> tuple[dict[str, object], dict[str, object]]:
    source = json.loads(
        (ROOT / "configs/data/p0-coverage-source-config-v1.json").read_text(encoding="utf-8")
    )
    task_id = "a" * 64
    receipt_hash = "b" * 64
    payload_hash = "c" * 64
    stored_hash = "d" * 64
    prefix = (
        "historical-deep-data/schema-v1/competition=api-football:135/"
        f"season=2024/family=fixtures/endpoint=fixtures/task={task_id}"
    )
    receipt_key = f"{prefix}/receipt.json"
    payload_key = f"{prefix}/payload-{payload_hash}.json.gz"
    object_id = canonical_sha256(
        {
            "receipt_key": receipt_key,
            "receipt_hash": receipt_hash,
            "payload_key": payload_key,
            "payload_sha256": payload_hash,
        }
    )
    entry = {
        "object_id": object_id,
        "receipt_id": task_id,
        "receipt_hash": receipt_hash,
        "receipt_key": receipt_key,
        "payload_key": payload_key,
        "payload_sha256": payload_hash,
        "stored_sha256": stored_hash,
        "logical_bytes": 2,
        "stored_bytes": 3,
        "competition": "api-football:135",
        "season": 2024,
        "family": "fixtures",
        "task_id": task_id,
        "provider_calls": 1,
        "rows_received": 0,
    }
    segment_identity = {
        "competition": "api-football:135",
        "season": 2024,
        "family": "fixtures",
        "segment": 1,
        "object_ids": [object_id],
    }
    segment = {
        **segment_identity,
        "segment_id": f"seg-000001-{canonical_sha256(segment_identity)[:16]}",
        "object_count": 1,
        "logical_bytes": 2,
        "estimated_seconds": 2.4,
        "oversized_single_object": False,
    }
    unsigned = {
        "schema_version": "historical-deep-replay-inventory-v2",
        "continuation_id": "synthetic-p0-reader",
        "continuation_of": "1:1",
        "run_purpose": "P0_READER_TEST",
        "code_revision": "1" * 40,
        "partition_key": ["competition", "season", "family", "segment"],
        "limits": {
            "objects": 100,
            "logical_bytes": 10_000,
            "estimated_seconds": 600.0,
            "checkpoint_objects": 20,
            "checkpoint_seconds": 300.0,
        },
        "objects_expected": 1,
        "logical_bytes": 2,
        "stored_bytes": 3,
        "segments_expected": 1,
        "objects": [entry],
        "segments": [segment],
        "provider_calls": 0,
    }
    manifest = {
        **unsigned,
        "manifest_sha256": canonical_sha256(unsigned),
    }
    inventory_pin = source["inventory"]
    assert isinstance(inventory_pin, dict)
    inventory_pin.update(
        {
            "manifest_sha256": manifest["manifest_sha256"],
            "durable_key": "synthetic-inventory.json.gz",
            "continuation_id": unsigned["continuation_id"],
            "continuation_of": unsigned["continuation_of"],
            "run_purpose": unsigned["run_purpose"],
            "code_revision": unsigned["code_revision"],
            "objects_expected": 1,
            "segments_expected": 1,
            "logical_bytes": 2,
            "stored_bytes": 3,
        }
    )
    access = source["access_policy"]
    assert isinstance(access, dict)
    access["bootstrap_exact_keys"] = ["synthetic-inventory.json.gz"]
    return source, manifest


def test_p0_inventory_deep_validation_recomputes_every_layer() -> None:
    source, manifest = _synthetic_p0_inventory()

    verified = deep_validate_inventory(manifest, source_config=source)

    assert verified.manifest_sha256 == manifest["manifest_sha256"]
    assert len(verified.objects) == 1
    assert len(verified.segments) == 1

    tampered = json.loads(json.dumps(manifest))
    tampered["segments"][0]["logical_bytes"] = 3
    unsigned = {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    tampered["manifest_sha256"] = canonical_sha256(unsigned)
    inventory_pin = source["inventory"]
    assert isinstance(inventory_pin, dict)
    inventory_pin["manifest_sha256"] = tampered["manifest_sha256"]
    with pytest.raises(
        ValueError,
        match="P0_INVENTORY_SEGMENT_AGGREGATE_MISMATCH",
    ):
        deep_validate_inventory(tampered, source_config=source)

    checkpoint_tampered = json.loads(json.dumps(manifest))
    checkpoint_tampered["limits"]["checkpoint_seconds"] = 301.0
    checkpoint_unsigned = {
        key: value for key, value in checkpoint_tampered.items() if key != "manifest_sha256"
    }
    checkpoint_tampered["manifest_sha256"] = canonical_sha256(checkpoint_unsigned)
    inventory_pin["manifest_sha256"] = checkpoint_tampered["manifest_sha256"]
    with pytest.raises(ValueError, match="P0_INVENTORY_CHECKPOINT_LIMIT_INVALID"):
        deep_validate_inventory(checkpoint_tampered, source_config=source)


def test_p0_reader_bootstraps_once_and_rejects_unlisted_ids_before_sdk() -> None:
    source, manifest = _synthetic_p0_inventory()
    logical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    stored = gzip.compress(logical, compresslevel=9, mtime=0)

    class Body:
        def __init__(self, value: bytes) -> None:
            self.value = value
            self.closed = False

        def read(self, amount: int) -> bytes:
            return self.value[:amount]

        def close(self) -> None:
            self.closed = True

    class ExactClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
            assert Bucket == "p0-test"
            self.calls.append(Key)
            body = Body(stored)
            return {"ContentLength": len(stored), "Body": body}

    client = ExactClient()
    reader = PinnedInventoryReader(
        client,
        bucket="p0-test",
        source_config=source,
    )
    object_id = manifest["objects"][0]["object_id"]
    assert isinstance(object_id, str)
    with pytest.raises(ValueError, match="P0_INVENTORY_REQUIRED_BEFORE_EVIDENCE"):
        reader.fetch_pair(object_id)
    reader.fetch_inventory_once()
    with pytest.raises(ValueError, match="P0_INVENTORY_BOOTSTRAP_ALREADY_USED"):
        reader.fetch_inventory_once()
    with pytest.raises(ValueError, match="P0_EVIDENCE_OBJECT_NOT_IN_INVENTORY"):
        reader.fetch_pair("e" * 64)
    assert client.calls == ["synthetic-inventory.json.gz"]
    assert (
        reader.telemetry.as_dict()["logical_gets"]["physical_http_requests"]
        == "UNKNOWN_NOT_OBSERVED"
    )


def _signed_p0(value: Mapping[str, object], *, field: str) -> dict[str, object]:
    unsigned = dict(value)
    return {**unsigned, field: canonical_sha256(unsigned)}


def _p0_fixture_material() -> tuple[
    list[dict[str, object]],
    dict[str, tuple[Mapping[str, object], ...]],
    list[dict[str, object]],
]:
    object_id = "a" * 64
    raw_records: list[dict[str, object]] = []
    normalized_fixtures: list[Mapping[str, object]] = []
    normalized_teams: list[Mapping[str, object]] = []
    proofs: list[dict[str, object]] = []
    for index in range(38):
        fixture_id = 1_000 + index
        home_team_id = 2_000 + index * 2
        away_team_id = home_team_id + 1
        kickoff = (datetime(2024, 8, 1, 18, tzinfo=UTC) + timedelta(days=index)).isoformat()
        home = {"id": home_team_id, "name": f"Home {index}"}
        away = {"id": away_team_id, "name": f"Away {index}"}
        raw_record: dict[str, object] = {
            "fixture": {
                "id": fixture_id,
                "date": kickoff,
                "status": {"short": "FT"},
            },
            "league": {
                "id": 135,
                "season": 2024,
                "round": f"Regular Season - {index + 1}",
            },
            "teams": {"home": home, "away": away},
        }
        source_record_hash = canonical_sha256(raw_record)
        raw_records.append(raw_record)
        normalized_fixtures.append(
            {
                "canonical_fixture_id": f"api-football:fixture:{fixture_id}",
                "provider_fixture_id": fixture_id,
                "provider_competition_id": 135,
                "season": 2024,
                "target_kickoff_at": kickoff,
                "source_record_hash": source_record_hash,
                "data": raw_record,
            }
        )
        for team in (home, away):
            normalized_teams.append(
                {
                    "provider_fixture_id": fixture_id,
                    "provider_team_id": team["id"],
                    "provider_competition_id": 135,
                    "season": 2024,
                    "source_record_hash": canonical_sha256(team),
                    "data": team,
                }
            )
        if index < 10:
            proofs.append(
                {
                    "fixture_id": 1_000 + index,
                    "canonical_fixture_id": f"api-football:fixture:{1_000 + index}",
                    "kickoff_utc": kickoff,
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "source_object_id": object_id,
                    "receipt_hash": "d" * 64,
                    "payload_sha256": "e" * 64,
                    "source_record_hash": source_record_hash,
                }
            )
    normalized_rounds = tuple(
        {
            "provider_competition_id": 135,
            "season": 2024,
            "source_record_hash": canonical_sha256({"round": index + 1}),
            "data": {"name": f"Regular Season - {index + 1}"},
        }
        for index in range(38)
    )
    return (
        raw_records,
        {
            "fixtures": tuple(normalized_fixtures),
            "teams": tuple(normalized_teams),
            "rounds": normalized_rounds,
        },
        proofs,
    )


def _p0_e1a_selection(authority: CoverageAuthority) -> dict[str, object]:
    _, _, fixtures = _p0_fixture_material()
    object_id = "a" * 64
    partition = {
        "partition_id": "p0-e1a-135-2024-all16",
        "competition": "api-football:135",
        "season": 2024,
        "family_group": "ALL_16",
        "normalized_families": list(authority.normalized_families),
        "evidence_object_ids": [object_id],
        "planned_evidence_gets": 2,
        "planned_payload_stored_bytes": 1,
        "planned_payload_logical_bytes": 1,
    }
    unsigned = {
        "schema_version": "p0-coverage-evidence-selection-v1",
        "mission_id": authority.mission["mission_id"],
        "domain_stage": "E1A",
        "council_stage": "E1",
        "scope_id": "P0_2020_2025",
        "source_config_sha256": authority.source_config_sha256,
        "mission_sha256": authority.mission_sha256,
        "stage_mapping_sha256": authority.mapping_sha256,
        "inventory_sha256": "b" * 64,
        "identity_architecture_hash": authority.identity_architecture_hash,
        "algorithm_version": coverage_evidence_module.ALGORITHM_VERSION,
        "absence_classification_framework_sha256": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        ),
        "architecture_ordinal": 1,
        "mission_architecture_registry": [
            {
                "ordinal": 1,
                "architecture_fingerprint": evidence_architecture_fingerprint(authority),
            }
        ],
        "freeze_code_revision": "c" * 40,
        "competition_seasons": [{"competition": "api-football:135", "season": 2024}],
        "fixture_selection": {
            "policy": "KICKOFF_UTC_THEN_PROVIDER_FIXTURE_ID",
            "target_per_competition": 10,
            "samples": [
                {
                    "competition": "api-football:135",
                    "season": 2024,
                    "fixture_count": 10,
                    "fixtures": fixtures,
                }
            ],
            "evidence_object_ids": [object_id],
        },
        "partitions": [partition],
        "partition_count": 1,
        "mission_accounting_baseline": {
            "schema_version": "p0-coverage-mission-accounting-baseline-v1",
            "source": "MISSION_START",
            "source_stage": None,
            "source_stage_receipt_sha256": None,
            "source_architecture_fingerprint": None,
            "source_receipt_ancestor_sha256s": [],
            "cumulative_mission_logical_gets_charged": 0,
            "cumulative_mission_logical_gets_observed": 0,
            "cumulative_mission_logical_gets_observed_lower_bound": 0,
            "mission_budget_accounting_basis": "EXACT_OBSERVED",
        },
        "freeze_attempt_slot": 1,
        "failed_freeze_conservative_charge": 0,
        "freeze_observed_logical_gets": 3,
        "planned_mission_logical_gets": 6,
        "closure_policy": {
            "real_cell_closure_forbidden": True,
            "authoritative_denominator_required": True,
            "unknown_is_not_zero": True,
            "inventory_rows_received_is_denominator": False,
        },
        "effects": dict(ZERO_EFFECTS),
    }
    return _signed_p0(unsigned, field="selection_sha256")


def _p0_authority_with_committed_selection(
    root: Path,
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
) -> CoverageAuthority:
    selection_path = (
        root / "configs" / "data" / "p0-coverage-evidence-selection-E1A-v1.json"
    )
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(
        json.dumps(selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return replace(authority, root=root)


def _p0_e1a_inventory(authority: CoverageAuthority) -> VerifiedInventory:
    objects: list[InventoryObject] = []
    for competition in authority.competitions:
        for season in authority.seasons:
            selected = competition == "api-football:135" and season == 2024
            object_id = (
                "a" * 64
                if selected
                else canonical_sha256({"competition": competition, "season": season})
            )
            task_id = canonical_sha256({"object_id": object_id})
            receipt_hash = "d" * 64 if selected else canonical_sha256({"receipt": object_id})
            payload_sha256 = "e" * 64 if selected else canonical_sha256({"payload": object_id})
            prefix = (
                "historical-deep-data/schema-v1/"
                f"competition={competition}/season={season}/family=fixtures/"
                f"endpoint=fixtures/task={task_id}"
            )
            objects.append(
                InventoryObject(
                    object_id=object_id,
                    receipt_id=task_id,
                    receipt_hash=receipt_hash,
                    receipt_key=f"{prefix}/receipt.json",
                    payload_key=f"{prefix}/payload-{payload_sha256}.json.gz",
                    payload_sha256=payload_sha256,
                    stored_sha256=canonical_sha256({"stored": object_id}),
                    logical_bytes=1,
                    stored_bytes=1,
                    competition=competition,
                    season=season,
                    family="fixtures",
                    task_id=task_id,
                    provider_calls=1,
                    rows_received=38 if selected else 0,
                )
            )
    return VerifiedInventory(
        manifest_sha256="b" * 64,
        code_revision="c" * 40,
        objects=tuple(objects),
        segments=(),
    )


class _P0PairReader:
    def __init__(self, pair: VerifiedEvidencePair) -> None:
        self.pair = pair
        self.requested: list[str] = []

    def fetch_pair(self, object_id: str) -> VerifiedEvidencePair:
        self.requested.append(object_id)
        if object_id != self.pair.entry.object_id:
            raise AssertionError("unexpected synthetic evidence object")
        return self.pair


def _p0_e1a_pair(inventory: VerifiedInventory) -> VerifiedEvidencePair:
    raw_records, normalized, _ = _p0_fixture_material()
    entry = inventory.by_id["a" * 64]
    receipt = SimpleNamespace(
        competition="api-football:135",
        season=2024,
        family="fixtures",
        endpoint="fixtures",
        page=1,
        completed_at=datetime(2025, 1, 1, tzinfo=UTC),
        status=SimpleNamespace(value="COMPLETE"),
        parameters={"league": 135, "season": 2024},
    )
    return VerifiedEvidencePair(
        entry=entry,
        receipt=receipt,
        payload={
            "paging": {"current": 1, "total": 1},
            "results": len(raw_records),
            "response": raw_records,
        },
        normalized=normalized,
        replay_source_hash="f" * 64,
        replay_hash="1" * 64,
    )


def test_p0_fixture_sample_reads_all_receipts_but_only_full_scope_payload() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    inventory = _p0_e1a_inventory(authority)
    full_entry = inventory.by_id["a" * 64]
    bundle_entry = InventoryObject(
        **{
            **full_entry.as_dict(),
            "object_id": "2" * 64,
            "receipt_id": "3" * 64,
            "receipt_hash": "4" * 64,
            "payload_sha256": "5" * 64,
        }
    )
    full_pair = _p0_e1a_pair(inventory)
    bundle_receipt = SimpleNamespace(
        competition="api-football:135",
        season=2024,
        family="fixtures",
        endpoint="fixtures",
        page=1,
        completed_at=datetime(2025, 1, 2, tzinfo=UTC),
        status=SimpleNamespace(value="COMPLETE"),
        parameters={"ids": "1000-1001"},
    )

    class BoundedReader:
        def __init__(self) -> None:
            self.telemetry = coverage_evidence_module.ReadTelemetry(bootstrap_requested=1)
            self.limits = coverage_evidence_module.AccessLimits(
                bootstrap_gets=1,
                bootstrap_compressed_bytes=1_000_000,
                bootstrap_decompressed_bytes=1_000_000,
                gets_per_job=200,
                stored_bytes_per_job=1_000_000,
                logical_bytes_per_job=1_000_000,
                mission_gets=10_000,
            )
            self.receipt_ids: list[str] = []
            self.pair_ids: list[str] = []

        def fetch_receipt(self, object_id: str) -> object:
            self.telemetry.receipt_requested += 1
            self.receipt_ids.append(object_id)
            return full_pair.receipt if object_id == full_entry.object_id else bundle_receipt

        def fetch_pair(self, object_id: str) -> VerifiedEvidencePair:
            self.telemetry.payload_requested += 1
            self.pair_ids.append(object_id)
            if object_id != full_entry.object_id:
                raise AssertionError("bundle payload must stay unread")
            return full_pair

    reader = BoundedReader()
    sample, evidence_ids = coverage_evidence_module._sample_fixtures(
        reader,  # type: ignore[arg-type]
        objects=(full_entry, bundle_entry),
        competition="api-football:135",
        season=2024,
        target=10,
    )

    assert [item["fixture_id"] for item in sample] == list(range(1_000, 1_010))
    assert set(reader.receipt_ids) == {full_entry.object_id, bundle_entry.object_id}
    assert reader.pair_ids == [full_entry.object_id]
    assert evidence_ids == (full_entry.object_id,)
    assert reader.telemetry.evidence_gets == 3


def test_p0_integrated_fixture_bundle_is_a_deep_source_only_when_materialized() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    inventory = _p0_e1a_inventory(authority)
    raw_records, _, _ = _p0_fixture_material()
    record = json.loads(json.dumps(raw_records[0]))
    record.update(
        {
            "events": [
                {
                    "time": {"elapsed": 12, "extra": None},
                    "team": {"id": 2_000},
                    "player": {"id": 9_001},
                    "type": "Card",
                    "detail": "Yellow Card",
                }
            ],
            "lineups": [
                {
                    "team": {"id": 2_000, "name": "Home"},
                    "formation": "4-3-3",
                    "startXI": [{"player": {"id": 9_001, "name": "Player", "grid": "1:1"}}],
                    "substitutes": [],
                }
            ],
            "statistics": [
                {
                    "team": {"id": 2_000},
                    "statistics": [{"type": "Shots on Goal", "value": 3}],
                }
            ],
            "players": [
                {
                    "team": {"id": 2_000},
                    "players": [
                        {
                            "player": {"id": 9_001, "name": "Player"},
                            "statistics": [{"games": {"minutes": 90}}],
                        }
                    ],
                }
            ],
        }
    )
    shallow_record = json.loads(json.dumps(raw_records[1]))
    payload = {
        "paging": {"current": 1, "total": 1},
        "results": 2,
        "response": [record, shallow_record],
    }
    normalized = coverage_evidence_module.normalize_payload(
        payload,
        endpoint="fixtures",
        competition_id=135,
        season=2024,
        task_id="bundle-task",
        request_params={"ids": "1000-1001"},
        observed_at=datetime(2025, 1, 1, tzinfo=UTC),
        ingested_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    receipt = SimpleNamespace(
        endpoint="fixtures",
        parameters={"ids": "1000-1001"},
        status=SimpleNamespace(value="COMPLETE"),
    )
    pair = VerifiedEvidencePair(
        entry=inventory.by_id["a" * 64],
        receipt=receipt,
        payload=payload,
        normalized={family: tuple(rows) for family, rows in normalized.items()},
        replay_source_hash="6" * 64,
        replay_hash="7" * 64,
    )
    deep_families = {
        "events",
        "lineups",
        "lineup_players",
        "formations",
        "team_match_statistics",
        "player_match_statistics",
    }

    assert deep_families.issubset(pair.normalized)
    assert all(
        coverage_evidence_module._pair_matches_family_source(pair, family=family)
        for family in deep_families
    )
    shallow_pair = VerifiedEvidencePair(
        entry=pair.entry,
        receipt=pair.receipt,
        payload=pair.payload,
        normalized={"fixtures": pair.normalized["fixtures"]},
        replay_source_hash=pair.replay_source_hash,
        replay_hash=pair.replay_hash,
    )
    assert not coverage_evidence_module._pair_matches_family_source(
        shallow_pair,
        family="events",
    )
    detail_envelopes = coverage_evidence_module._integrated_detail_envelope_evidence(
        (pair,),
        authoritative_fixture_ids=set(range(1_000, 1_038)),
    )
    detail_families = detail_envelopes["families"]
    assert isinstance(detail_families, Mapping)
    event_envelope = detail_families["events"]
    assert isinstance(event_envelope, Mapping)
    assert event_envelope["returned_ids"] == frozenset({1_000})
    processing = coverage_evidence_module._processing_scope_evidence(
        family="events",
        pairs=(pair,),
        detail_envelopes=detail_envelopes,
        authoritative_fixture_ids=set(range(1_000, 1_038)),
        target_fixture_ids=set(range(1_000, 1_010)),
    )
    assert processing["completed"] == 1
    assert processing["expected"] == 10
    assert processing["missing_scopes"] == 9
    assert processing["gate"] == "PARTIAL"

    shallow_envelopes = coverage_evidence_module._integrated_detail_envelope_evidence(
        (shallow_pair,),
        authoritative_fixture_ids=set(range(1_000, 1_038)),
    )
    shallow_processing = coverage_evidence_module._processing_scope_evidence(
        family="events",
        pairs=(shallow_pair,),
        detail_envelopes=shallow_envelopes,
        authoritative_fixture_ids=set(range(1_000, 1_038)),
        target_fixture_ids=set(range(1_000, 1_010)),
    )
    assert shallow_processing["completed"] == 0
    assert shallow_processing["missing_scopes"] == 10
    assert shallow_processing["source_object_ids"] == []
    assert shallow_processing["gate"] == "PARTIAL"

    first_direct = VerifiedEvidencePair(
        entry=replace(
            pair.entry,
            object_id="d" * 64,
            receipt_id="e" * 64,
            receipt_hash="f" * 64,
            family="events",
        ),
        receipt=SimpleNamespace(
            endpoint="fixtures/events",
            parameters={"fixture": "1000"},
            status=SimpleNamespace(value="COMPLETE"),
        ),
        payload={"response": []},
        normalized={"events": ({"provider_fixture_id": 1_001},)},
        replay_source_hash="1" * 64,
        replay_hash="2" * 64,
    )
    second_direct = VerifiedEvidencePair(
        entry=replace(
            pair.entry,
            object_id="3" * 64,
            receipt_id="4" * 64,
            receipt_hash="5" * 64,
            family="events",
        ),
        receipt=SimpleNamespace(
            endpoint="fixtures/events",
            parameters={"fixture": "1001"},
            status=SimpleNamespace(value="COMPLETE"),
        ),
        payload={"response": []},
        normalized={"events": ({"provider_fixture_id": 1_000},)},
        replay_source_hash="6" * 64,
        replay_hash="7" * 64,
    )
    direct_envelopes = coverage_evidence_module._integrated_detail_envelope_evidence(
        (first_direct, second_direct),
        authoritative_fixture_ids=set(range(1_000, 1_038)),
    )
    swapped_processing = coverage_evidence_module._processing_scope_evidence(
        family="events",
        pairs=(first_direct, second_direct),
        detail_envelopes=direct_envelopes,
        authoritative_fixture_ids=set(range(1_000, 1_038)),
        target_fixture_ids={1_000, 1_001},
    )
    assert swapped_processing["completed"] == 0
    assert swapped_processing["source_object_ids"] == ["3" * 64, "d" * 64]
    assert swapped_processing["gate"] == "FAIL"


def test_p0_unproven_deep_applicability_never_becomes_a_known_denominator() -> None:
    census = {
        "status": "COMPLETE",
        "fixtures": 10,
        "team_slots": 20,
        "terminal_team_slots": 20,
    }
    expected, basis = coverage_evidence_module._known_expected_counts(
        family="team_match_statistics",
        census=census,
        pairs=(),
    )
    scope = coverage_evidence_module._scope_completion_counts(
        family="team_match_statistics",
        pairs=(),
        census=census,
    )

    assert expected is None
    assert basis == "DENOMINATOR_UNKNOWN"
    assert scope["expected"] is None
    assert scope["identity_gate"] == "UNKNOWN"


def test_p0_player_season_buckets_and_signed_absence_partition_preserve_identity() -> None:
    player_rows = [
        {
            "provider_competition_id": 135,
            "season": 2024,
            "provider_player_id": 77,
            "provider_team_id": team_id,
            "data": {"team": {"id": team_id}, "games": {"appearences": appearances}},
        }
        for team_id, appearances in ((1, 3), (2, 4))
    ]
    deduplicated = coverage_evidence_module._deduplicate_rows(
        "player_season_statistics",
        player_rows,
    )
    assert deduplicated["normalized_unique"] == 1
    assert deduplicated["contradictory_duplicates"] == 0

    entry = InventoryObject(
        object_id="8" * 64,
        receipt_id="9" * 64,
        receipt_hash="a" * 64,
        receipt_key="receipt.json",
        payload_key="payload.json.gz",
        payload_sha256="b" * 64,
        stored_sha256="c" * 64,
        logical_bytes=1,
        stored_bytes=1,
        competition="api-football:135",
        season=2024,
        family="injuries",
        task_id="d" * 64,
        provider_calls=1,
        rows_received=3,
    )
    absence_records = [
        {
            "fixture": {"id": 1},
            "player": {"id": 2},
            "team": {"id": 3},
            "type": "Red Card",
            "reason": "Suspended",
            "start": "2024-01-01",
            "end": "2024-01-02",
        },
        {
            "fixture": {"id": 4},
            "player": {"id": 5},
            "team": {"id": 6},
            "type": "Knee Injury",
            "reason": "Injured",
            "start": "2024-01-01",
            "end": "2024-01-02",
        },
        {
            "fixture": {"id": 7},
            "player": {"id": 8},
            "team": {"id": 9},
            "type": "Personal reason",
            "reason": "Unknown",
            "start": "2024-01-01",
            "end": "2024-01-02",
        },
    ]
    pair = VerifiedEvidencePair(
        entry=entry,
        receipt=SimpleNamespace(endpoint="injuries"),
        payload={"response": absence_records},
        normalized={},
        replay_source_hash="e" * 64,
        replay_hash="f" * 64,
    )
    classified = coverage_evidence_module._classify_absence_source(
        (pair,),
        suspension_pattern=re.compile(r"red card|suspend", re.IGNORECASE),
        injury_pattern=re.compile(r"injur", re.IGNORECASE),
    )
    categories = classified["categories"]
    assert isinstance(categories, Mapping)
    assert {name: len(values) for name, values in categories.items()} == {
        "SUSPENSION": 1,
        "INJURY": 1,
        "UNCLASSIFIABLE": 1,
    }
    assert len(set().union(*categories.values())) == 3
    assert classified["invalid_identity"] == 0
    assert classified["contradictory_identity"] == 0
    assert classified["identity_counts"] == {
        "SUSPENSION": 1,
        "INJURY": 1,
        "UNCLASSIFIABLE": 1,
    }

    conflicting_unclassifiable = json.loads(json.dumps(absence_records[2]))
    conflicting_unclassifiable["provider_note"] = "different source content"
    conflicting_pair = replace(
        pair,
        payload={"response": [absence_records[2], conflicting_unclassifiable]},
    )
    conflicting = coverage_evidence_module._classify_absence_source(
        (conflicting_pair,),
        suspension_pattern=re.compile(r"red card|suspend", re.IGNORECASE),
        injury_pattern=re.compile(r"injur", re.IGNORECASE),
    )
    assert conflicting["invalid_identity"] == 0
    assert conflicting["contradictory_identity"] == 1


def test_p0_absence_classifier_reads_nested_player_fields_without_sidelined_dates() -> None:
    entry = InventoryObject(
        object_id="8" * 64,
        receipt_id="9" * 64,
        receipt_hash="a" * 64,
        receipt_key="receipt.json",
        payload_key="payload.json.gz",
        payload_sha256="b" * 64,
        stored_sha256="c" * 64,
        logical_bytes=1,
        stored_bytes=1,
        competition="api-football:135",
        season=2024,
        family="injuries",
        task_id="d" * 64,
        provider_calls=1,
        rows_received=2,
    )
    records = [
        {
            "fixture": {"id": 1},
            "player": {
                "id": 2,
                "type": "Missing Fixture",
                "reason": "Knee Injury",
            },
            "team": {"id": 3},
        },
        {
            "fixture": {"id": 4},
            "player": {
                "id": 5,
                "type": "Missing Fixture",
                "reason": "Red Card",
            },
            "team": {"id": 6},
        },
    ]
    pair = VerifiedEvidencePair(
        entry=entry,
        receipt=SimpleNamespace(endpoint="injuries"),
        payload={"response": records},
        normalized={},
        replay_source_hash="e" * 64,
        replay_hash="f" * 64,
    )

    classified = coverage_evidence_module._classify_absence_source(
        (pair,),
        suspension_pattern=re.compile(r"red card|suspend", re.IGNORECASE),
        injury_pattern=re.compile(r"injur", re.IGNORECASE),
    )

    categories = classified["categories"]
    assert isinstance(categories, Mapping)
    assert {name: len(values) for name, values in categories.items()} == {
        "SUSPENSION": 1,
        "INJURY": 1,
        "UNCLASSIFIABLE": 0,
    }
    assert classified["invalid_identity"] == 0
    assert classified["contradictory_identity"] == 0
    nested_row = {
        "provider_fixture_id": 1,
        "provider_player_id": 2,
        "provider_team_id": 3,
        "data": records[0],
    }
    assert coverage_evidence_module._semantic_key("injuries", nested_row) == (
        "injuries",
        1,
        2,
        3,
        "Missing Fixture",
        "Knee Injury",
        None,
        None,
    )


def test_p0_absence_architecture_two_golden_and_canary_are_fail_closed() -> None:
    entry = InventoryObject(
        object_id="8" * 64,
        receipt_id="9" * 64,
        receipt_hash="a" * 64,
        receipt_key="receipt.json",
        payload_key="payload.json.gz",
        payload_sha256="b" * 64,
        stored_sha256="c" * 64,
        logical_bytes=1,
        stored_bytes=1,
        competition="api-football:135",
        season=2024,
        family="injuries",
        task_id="d" * 64,
        provider_calls=1,
        rows_received=13,
    )

    def record(
        fixture_id: int,
        *,
        absence_type: object = "Missing Fixture",
        reason: object = "Unknown",
        nested_type: object | None = None,
        nested_reason: object | None = None,
        description: object | None = None,
    ) -> dict[str, object]:
        player: dict[str, object] = {"id": fixture_id + 100}
        if nested_type is not None:
            player["type"] = nested_type
        if nested_reason is not None:
            player["reason"] = nested_reason
        output: dict[str, object] = {
            "fixture": {"id": fixture_id},
            "player": player,
            "team": {"id": fixture_id + 200},
            "type": absence_type,
            "reason": reason,
            "start": None,
            "end": None,
        }
        if description is not None:
            output["description"] = description
        return output

    golden = [
        record(1, absence_type=None, reason=None, nested_reason="  Knee   Injury  "),
        record(2, absence_type="Red Card", reason="Suspended"),
        record(3, reason="PERSONAL REASONS"),
        record(4, reason="unknown"),
        record(5, reason="Knee Injury and Red Card"),
        record(
            6,
            absence_type="Knee Injury",
            reason="Injured",
            nested_type="Red Card",
            nested_reason="Injured",
        ),
    ]
    canary = [
        record(7, absence_type=None, reason=None, nested_reason="Concussion"),
        record(8, reason="Match ban"),
        record(9, reason="ＰＥＲＳＯＮＡＬ ＲＥＡＳＯＮ"),
        record(10, absence_type=None, reason="not available"),
        record(11, absence_type="Unknown", reason="Knee Injury"),
        record(12, absence_type="Personal reason", reason="Red Card"),
        record(13, absence_type="N/A", reason="Red Card"),
    ]

    def classify(records: list[dict[str, object]]) -> Mapping[str, object]:
        pair = VerifiedEvidencePair(
            entry=entry,
            receipt=SimpleNamespace(endpoint="injuries"),
            payload={"response": records},
            normalized={},
            replay_source_hash="e" * 64,
            replay_hash="f" * 64,
        )
        return coverage_evidence_module._classify_absence_source(
            (pair,),
            suspension_pattern=re.compile(r"red card|suspend", re.IGNORECASE),
            injury_pattern=re.compile(r"injur|fracture", re.IGNORECASE),
        )

    golden_expected = (
        "INJURY",
        "SUSPENSION",
        "UNCLASSIFIABLE",
        "UNCLASSIFIABLE",
        "UNCLASSIFIABLE",
        "UNCLASSIFIABLE",
    )
    canary_expected = ("UNCLASSIFIABLE",) * len(canary)

    def assert_exact_labels(
        result: Mapping[str, object],
        records: list[dict[str, object]],
        expected: tuple[str, ...],
    ) -> None:
        categories = result["categories"]
        assert isinstance(categories, Mapping)
        for item, expected_category in zip(records, expected, strict=True):
            record_hash = canonical_sha256(item)
            assert record_hash in categories[expected_category]
            assert all(
                record_hash not in values
                for category, values in categories.items()
                if category != expected_category
            )

    assert_exact_labels(classify(golden), golden, golden_expected)
    assert_exact_labels(classify(canary), canary, canary_expected)
    classified = classify([*golden, *canary])
    assert_exact_labels(
        classified,
        [*golden, *canary],
        (*golden_expected, *canary_expected),
    )
    permuted = classify(list(reversed([*golden, *canary])))
    categories = classified["categories"]
    assert isinstance(categories, Mapping)
    assert {name: len(values) for name, values in categories.items()} == {
        "SUSPENSION": 1,
        "INJURY": 1,
        "UNCLASSIFIABLE": 11,
    }
    assert classified["categories"] == permuted["categories"]
    assert classified["semantic_signatures"] == permuted["semantic_signatures"]
    residual = classified["semantic_signatures"]
    assert isinstance(residual, list)
    assert sum(int(item["count"]) for item in residual) == 11
    assert all(
        set(item)
        == {
            "signature_sha256",
            "normalized_type_values",
            "normalized_reason_values",
            "normalized_description_values",
            "normalization_version",
            "reason_code",
            "count",
        }
        for item in residual
    )
    golden_signatures = {
        coverage_evidence_module._absence_semantic_evidence(item)["signature_sha256"]
        for item in golden
    }
    canary_signatures = {
        coverage_evidence_module._absence_semantic_evidence(item)["signature_sha256"]
        for item in canary
    }
    assert golden_signatures.isdisjoint(canary_signatures)


@pytest.mark.parametrize(
    ("semantic_fields", "expected_reason"),
    (
        ({"type": "Unknown", "reason": "Knee Injury"}, "UNKNOWN_MARKER"),
        ({"type": "N/A", "reason": "Red Card"}, "UNKNOWN_MARKER"),
        ({"type": "not available", "reason": "Suspended"}, "UNKNOWN_MARKER"),
        (
            {"type": "Missing Fixture", "reason": "Opaque absence"},
            "PROVIDER_PLACEHOLDER_WITHOUT_CLOSED_SIGNAL",
        ),
        (
            {"type": "Personal reason", "reason": "Knee Injury"},
            "MULTIPLE_SEMANTIC_SIGNALS",
        ),
        ({"type": "opaque\x00value"}, "REDACTED_TYPE_OR_REASON_FAIL_CLOSED"),
        ({"type": "x" * 257}, "REDACTED_TYPE_OR_REASON_FAIL_CLOSED"),
        ({"type": 123}, "REDACTED_TYPE_OR_REASON_FAIL_CLOSED"),
        (
            {"type": "Opaque A", "player": {"type": "Opaque B"}},
            "FLAT_NESTED_CONFLICT",
        ),
        (
            {"type": "Opaque", "description": "Private clinical note"},
            "DESCRIPTION_BEARING_RESIDUAL_FAIL_CLOSED",
        ),
    ),
)
def test_p0_residual_profiles_cannot_reseal_protected_semantics_as_supplementable(
    semantic_fields: Mapping[str, object],
    expected_reason: str,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    partition = next(iter(selection["partitions"]))
    assert isinstance(partition, Mapping)
    player = {"id": 2}
    nested_player = semantic_fields.get("player")
    if isinstance(nested_player, Mapping):
        player.update(nested_player)
    record = {
        "fixture": {"id": 1},
        "player": player,
        "team": {"id": 3},
        **{key: value for key, value in semantic_fields.items() if key != "player"},
    }
    entry = InventoryObject(
        object_id="8" * 64,
        receipt_id="9" * 64,
        receipt_hash="a" * 64,
        receipt_key="receipt.json",
        payload_key="payload.json.gz",
        payload_sha256="b" * 64,
        stored_sha256="c" * 64,
        logical_bytes=1,
        stored_bytes=1,
        competition="api-football:135",
        season=2024,
        family="injuries",
        task_id="d" * 64,
        provider_calls=1,
        rows_received=1,
    )
    pair = VerifiedEvidencePair(
        entry=entry,
        receipt=SimpleNamespace(endpoint="injuries"),
        payload={"response": [record]},
        normalized={},
        replay_source_hash="e" * 64,
        replay_hash="f" * 64,
    )
    suspension_pattern, injury_pattern = coverage_evidence_module._absence_rule_patterns(
        authority
    )
    classified = coverage_evidence_module._classify_absence_source(
        (pair,),
        suspension_pattern=suspension_pattern,
        injury_pattern=injury_pattern,
    )
    signature = dict(next(iter(classified["semantic_signatures"])))
    assert signature["reason_code"] == expected_reason
    if semantic_fields.get("description") is not None:
        assert all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in signature["normalized_description_values"]
        )
    coverage_evidence_module._build_absence_residual_profile(
        authority,
        selection=selection,
        selection_sha256=str(selection["selection_sha256"]),
        partition_id=str(partition["partition_id"]),
        inventory_sha256=str(selection["inventory_sha256"]),
        attempt_slot=1,
        absence_source_object_ids=(entry.object_id,),
        semantic_signatures=(signature,),
        classification_supplement_sha256=None,
    )

    forged = dict(signature)
    forged["reason_code"] = "UNRECOGNIZED_SEMANTICS"
    semantic_sha = canonical_sha256(
        {
            "normalized_type_values": forged["normalized_type_values"],
            "normalized_reason_values": forged["normalized_reason_values"],
            "normalized_description_values": forged["normalized_description_values"],
            "normalization_version": forged["normalization_version"],
        }
    )
    forged["signature_sha256"] = canonical_sha256(
        {
            "semantic_signature_sha256": semantic_sha,
            "reason_code": forged["reason_code"],
        }
    )
    with pytest.raises(ValueError, match="P0_ABSENCE_RESIDUAL_SIGNATURE_"):
        coverage_evidence_module._build_absence_residual_profile(
            authority,
            selection=selection,
            selection_sha256=str(selection["selection_sha256"]),
            partition_id=str(partition["partition_id"]),
            inventory_sha256=str(selection["inventory_sha256"]),
            attempt_slot=1,
            absence_source_object_ids=(entry.object_id,),
            semantic_signatures=(forged,),
            classification_supplement_sha256=None,
        )


@pytest.mark.parametrize(
    "forged_value",
    ("UNKNOWN", " unknown ", "unknown\x00", "sha256:not-a-digest"),
)
def test_p0_residual_profile_rejects_noncanonical_semantic_values(
    forged_value: str,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    suspension_pattern, injury_pattern = coverage_evidence_module._absence_rule_patterns(
        authority
    )
    unsigned = {
        "normalized_type_values": [],
        "normalized_reason_values": [forged_value],
        "normalized_description_values": [],
        "normalization_version": coverage_evidence_module.ABSENCE_NORMALIZATION_VERSION,
    }
    semantic_sha = canonical_sha256(unsigned)
    signature = {
        **unsigned,
        "reason_code": "UNRECOGNIZED_SEMANTICS",
        "count": 1,
        "signature_sha256": canonical_sha256(
            {
                "semantic_signature_sha256": semantic_sha,
                "reason_code": "UNRECOGNIZED_SEMANTICS",
            }
        ),
    }

    with pytest.raises(ValueError, match="P0_TEST_SIGNATURE_REASON_VALUES_INVALID"):
        coverage_evidence_module._validate_absence_semantic_signature(
            signature,
            label="P0_TEST_SIGNATURE",
            suspension_pattern=suspension_pattern,
            injury_pattern=injury_pattern,
        )


def _p0_unknown_rate() -> dict[str, object]:
    return {
        "numerator": 0,
        "denominator": None,
        "status": "UNKNOWN",
        "value": None,
    }


def _p0_complete_rate() -> dict[str, object]:
    return {
        "numerator": 1,
        "denominator": 1,
        "status": "KNOWN",
        "value": 1.0,
    }


def _p0_cell(*, family: str, probe_pass: bool = True) -> dict[str, object]:
    source_object_ids = ["a" * 64] if probe_pass else []
    identity_count = (
        {"fixtures": 10, "teams": 20}.get(family, 1)
        if probe_pass
        else 0
    )
    source_lineage = (
        [
            {
                "object_id": "a" * 64,
                "receipt_hash": "d" * 64,
                "payload_sha256": "e" * 64,
            }
        ]
        if probe_pass
        else []
    )
    rates = {
        "scope_completion": _p0_complete_rate() if probe_pass else _p0_unknown_rate(),
        "normalization_integrity": (
            {
                "numerator": identity_count,
                "denominator": identity_count,
                "status": "KNOWN",
                "value": 1.0,
            }
            if probe_pass
            else _p0_unknown_rate()
        ),
        "content_presence": {
            **_p0_unknown_rate(),
            "numerator": 1 if probe_pass else 0,
        },
    }
    unsigned: dict[str, object] = {
        "scope": "P0_2020_2025",
        "competition": "api-football:135",
        "season": 2024,
        "family": family,
        "grain": "synthetic_test_grain",
        "grain_id": "synthetic-test-grain-v1",
        "source": "synthetic_read_only_fixture",
        "temporal_class": "PRE_MATCH",
        "source_lineage_hash": canonical_sha256(source_lineage),
        "source_lineage": source_lineage,
        "source_object_count": len(source_object_ids),
        "materialized_source_object_count": len(source_object_ids),
        "source_object_set_hash": canonical_sha256(source_object_ids),
        "source_scopes_expected": 1 if probe_pass else None,
        "source_scopes_verified": 1 if probe_pass else 0,
        "scope_basis": "SYNTHETIC_TEST_SCOPE",
        "scope_identity_gate": "PASS" if probe_pass else "UNKNOWN",
        "expected_scope_set_hash": (canonical_sha256(["scope"]) if probe_pass else None),
        "observed_scope_set_hash": (canonical_sha256(["scope"]) if probe_pass else None),
        "unexpected_scope_count": 0,
        "processing_scopes_expected": None,
        "processing_scopes_verified": 0,
        "processing_scope_gate": "NOT_APPLICABLE",
        "processing_expected_set_hash": None,
        "processing_observed_set_hash": None,
        "processing_missing_scope_count": 0,
        "processing_unexpected_scope_count": 0,
        "processing_source_object_ids": [],
        "processing_source_object_set_hash": canonical_sha256([]),
        "counts": {
            "normalized_rows": identity_count,
            "normalized_unique": identity_count,
            "invalid_identity": 0,
            "exact_duplicates": 0,
            "contradictory_duplicates": 0,
            "identity_key_set_hash": canonical_sha256([[family, "identity"]]),
            "identity_set_hash": canonical_sha256([[family, "identity", "content"]]),
        },
        "denominator_basis": "DENOMINATOR_UNKNOWN",
        "raw_eligible_unique_entities": identity_count if probe_pass else None,
        "expected_content_slots": None,
        "observed_content_slots": 1 if probe_pass else 0,
        "expected_count": None,
        "received_count": 1 if probe_pass else 0,
        "empty_valid_count": 0,
        "invalid_count": 0,
        "unclassifiable_count": 0,
        "exact_duplicates": 0,
        "contradictory_duplicates": 0,
        "coverage_percent": None,
        "normalization_integrity": rates["normalization_integrity"],
        "content_presence": rates["content_presence"],
        "null_rate": None,
        "null_rate_status": "UNKNOWN_NOT_PROVEN",
        "rates": rates,
        "closure_state": "OPEN_NOT_EVALUATED",
        "gate": "PARTIAL",
        "probe_gate": "PASS" if probe_pass else "FAIL",
        "reason": "OPEN_NOT_EVALUATED",
    }
    return _signed_p0(unsigned, field="cell_hash")


def _p0_absence_profile(
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
    partition: Mapping[str, object],
    attempt_slot: int,
    unclassifiable_count: int = 0,
    absence_source_object_ids: tuple[str, ...] | None = None,
) -> Mapping[str, object]:
    semantic_signatures: list[Mapping[str, object]] = []
    if unclassifiable_count:
        semantic = coverage_evidence_module._absence_semantic_evidence(
            {"type": "Unmapped absence", "reason": "Needs adjudication"}
        )
        semantic_signature_sha = str(semantic["signature_sha256"])
        reason_code = "UNRECOGNIZED_SEMANTICS"
        semantic_signatures.append(
            {
                "signature_sha256": canonical_sha256(
                    {
                        "semantic_signature_sha256": semantic_signature_sha,
                        "reason_code": reason_code,
                    }
                ),
                "normalized_type_values": semantic["normalized_type_values"],
                "normalized_reason_values": semantic["normalized_reason_values"],
                "normalized_description_values": semantic[
                    "normalized_description_values"
                ],
                "normalization_version": (
                    coverage_evidence_module.ABSENCE_NORMALIZATION_VERSION
                ),
                "reason_code": reason_code,
                "count": unclassifiable_count,
            }
        )
    return coverage_evidence_module._build_absence_residual_profile(
        authority,
        selection=selection,
        selection_sha256=str(selection["selection_sha256"]),
        partition_id=str(partition["partition_id"]),
        inventory_sha256=str(selection["inventory_sha256"]),
        attempt_slot=attempt_slot,
        absence_source_object_ids=(
            absence_source_object_ids
            if absence_source_object_ids is not None
            else tuple(str(item) for item in partition["evidence_object_ids"])
        ),
        semantic_signatures=semantic_signatures,
        classification_supplement_sha256=None,
    )


def _write_p0_e1a_shard(
    directory: Path,
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
    cells: list[dict[str, object]],
    attempt_slot: int = 1,
) -> None:
    partition = next(iter(selection["partitions"]))
    assert isinstance(partition, Mapping)
    selection_sha = selection["selection_sha256"]
    cell_by_family = {cell["family"]: cell for cell in cells}

    def absence_distinct(family: str) -> int:
        cell = cell_by_family.get(family)
        if cell is None:
            return 0
        identity_counts = cell.get("counts")
        assert isinstance(identity_counts, Mapping)
        return int(identity_counts["normalized_unique"])

    injury_distinct = absence_distinct("injuries")
    suspension_distinct = absence_distinct("suspensions")
    absence_source_object_ids = tuple(
        sorted(
            {
                str(lineage_item["object_id"])
                for family in ("injuries", "suspensions")
                if (cell := cell_by_family.get(family)) is not None
                for lineage_item in cell["source_lineage"]
            }
        )
    )
    counts = _signed_p0(
        {
            "schema_version": FAMILY_COUNTS_SCHEMA_VERSION,
            "stage": "E1A",
            "partition_id": partition["partition_id"],
            "selection_sha256": selection_sha,
            "competition": partition["competition"],
            "season": partition["season"],
            "family_group": partition["family_group"],
            "fixture_census": {},
            "source_fixture_census": {},
            "absence_partition": {
                "raw_distinct": injury_distinct + suspension_distinct,
                "injuries_distinct": injury_distinct,
                "suspensions_distinct": suspension_distinct,
                "unclassifiable_distinct": 0,
                "classification_rule_version": (
                    coverage_evidence_module.ABSENCE_CLASSIFICATION_RULE_VERSION
                ),
                "classification_framework_sha256": (
                    coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
                ),
                "classification_supplement_sha256": None,
                "classification_set_hash": canonical_sha256(
                    {
                        "injuries": ["1" * 64] * injury_distinct,
                        "suspensions": ["2" * 64] * suspension_distinct,
                        "unclassifiable": [],
                    }
                ),
                "residual_profile": _p0_absence_profile(
                    authority=authority,
                    selection=selection,
                    partition=partition,
                    attempt_slot=attempt_slot,
                    absence_source_object_ids=absence_source_object_ids,
                ),
                "invariant": "PASS",
            },
            "families": cells,
            "effects": dict(ZERO_EFFECTS),
        },
        field="counts_sha256",
    )
    sample_size = len(selection["fixture_selection"]["samples"][0]["fixtures"])
    fixture_counts = cell_by_family["fixtures"]["counts"]
    team_counts = cell_by_family["teams"]["counts"]
    sample_identity_pass = (
        fixture_counts["normalized_unique"] == sample_size
        and fixture_counts["invalid_identity"] == 0
        and fixture_counts["contradictory_duplicates"] == 0
        and team_counts["normalized_unique"] == sample_size * 2
        and team_counts["invalid_identity"] == 0
        and team_counts["contradictory_duplicates"] == 0
    )
    receipt = _signed_p0(
        {
            "schema_version": "p0-coverage-partition-receipt-v1",
            "stage": "E1A",
            "partition_id": partition["partition_id"],
            "selection_sha256": selection_sha,
            "inventory_sha256": selection["inventory_sha256"],
            "measure_code_revision": "2" * 40,
            "competition": partition["competition"],
            "season": partition["season"],
            "family_group": partition["family_group"],
            "evidence_object_count": 1,
            "evidence_object_set_hash": canonical_sha256(["a" * 64]),
            "pairs_verified": 1,
            "family_counts_sha256": counts["counts_sha256"],
            "family_lineage_hashes": {
                cell["family"]: cell["source_lineage_hash"] for cell in cells
            },
            "frozen_fixture_proof_gate": "PASS",
            "family_identity_gate": "PASS",
            "sample_identity_gate": "PASS" if sample_identity_pass else "FAIL",
            "sample_processing_gate": "PASS",
            "scientific_status": (
                "MEASURED" if sample_identity_pass else "FAILED_IDENTITY_GATE"
            ),
            "effects": dict(ZERO_EFFECTS),
        },
        field="partition_receipt_sha256",
    )
    cost = _signed_p0(
        {
            "schema_version": "p0-coverage-partition-cost-v1",
            "stage": "E1A",
            "partition_id": partition["partition_id"],
            "attempt_slot": attempt_slot,
            "selection_sha256": selection_sha,
            "reads": {
                "logical_gets": 3,
                "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
                "stored_bytes": 1,
                "logical_bytes": 1,
            },
            "resources": {
                "measurement_elapsed_seconds": 1.0,
                "process_peak_rss_bytes": 1_000_000,
                "process_peak_rss_source": "LINUX_PROC_STATUS_VMHWM",
                "signed_memory_limit_bytes": None,
                "memory_budget_gate": "UNKNOWN_NO_SIGNED_LIMIT",
            },
            "telemetry": {
                "logical_gets": {
                    "bootstrap": {"requested": 1, "succeeded": 1, "failed": 0},
                    "receipt": {"requested": 1, "succeeded": 1, "failed": 0},
                    "payload": {"requested": 1, "succeeded": 1, "failed": 0},
                    "evidence_total": 2,
                    "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
                },
                "bytes": {
                    "bootstrap_stored": 1,
                    "bootstrap_logical": 1,
                    "receipt": 0,
                    "payload_stored": 0,
                    "payload_logical": 0,
                    "peak_pair": 0,
                },
                "pairs_verified": 1,
                "quota": "UNKNOWN_NOT_OBSERVED",
                "monetary_cost": "UNKNOWN_NOT_OBSERVED",
                "effects": dict(ZERO_EFFECTS),
            },
            "quota": "UNKNOWN_NOT_OBSERVED",
            "monetary_cost": "UNKNOWN_NOT_OBSERVED",
            "effects": dict(ZERO_EFFECTS),
        },
        field="cost_sha256",
    )
    checkpoint = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id=str(partition["partition_id"]),
        code_revision="2" * 40,
        attempt_slot=attempt_slot,
        status="COMPLETED",
        elapsed_seconds=1.0,
        output_bindings={
            "partition_receipt_sha256": receipt["partition_receipt_sha256"],
            "family_counts_sha256": counts["counts_sha256"],
            "cost_sha256": cost["cost_sha256"],
        },
    )
    shard = directory / "p0-e1a-135-2024-all16"
    shard.mkdir(parents=True)
    for name, value in (
        ("partition-receipt.json", receipt),
        ("family-counts.json", counts),
        ("cost-report.json", cost),
        ("checkpoint-final.json", checkpoint),
    ):
        (shard / name).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )


def _resign_p0_e1a_shard(
    shard: Path,
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
    counts: dict[str, object],
    receipt_updates: Mapping[str, object] | None = None,
) -> None:
    families = counts.get("families")
    assert isinstance(families, list)
    for cell in families:
        assert isinstance(cell, dict)
        cell.pop("cell_hash", None)
        cell.update(_signed_p0(cell, field="cell_hash"))
    counts.pop("counts_sha256", None)
    counts.update(_signed_p0(counts, field="counts_sha256"))

    receipt = json.loads((shard / "partition-receipt.json").read_text(encoding="utf-8"))
    receipt["family_counts_sha256"] = counts["counts_sha256"]
    receipt.update(receipt_updates or {})
    receipt.pop("partition_receipt_sha256", None)
    receipt.update(_signed_p0(receipt, field="partition_receipt_sha256"))

    cost = json.loads((shard / "cost-report.json").read_text(encoding="utf-8"))
    checkpoint = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id=str(receipt["partition_id"]),
        code_revision=str(receipt["measure_code_revision"]),
        attempt_slot=int(cost["attempt_slot"]),
        status="COMPLETED",
        elapsed_seconds=1.0,
        output_bindings={
            "partition_receipt_sha256": receipt["partition_receipt_sha256"],
            "family_counts_sha256": counts["counts_sha256"],
            "cost_sha256": cost["cost_sha256"],
        },
    )
    for name, value in (
        ("partition-receipt.json", receipt),
        ("family-counts.json", counts),
        ("checkpoint-final.json", checkpoint),
    ):
        (shard / name).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )


def _rewrite_p0_e1a_shard_as_identity_failure(
    shard: Path,
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
    coherent_receipt: bool,
) -> None:
    counts = json.loads((shard / "family-counts.json").read_text(encoding="utf-8"))
    cost = json.loads((shard / "cost-report.json").read_text(encoding="utf-8"))
    attempt_slot = int(cost["attempt_slot"])
    counts["absence_partition"] = {
        "raw_distinct": 1,
        "injuries_distinct": 0,
        "suspensions_distinct": 0,
        "unclassifiable_distinct": 1,
        "classification_rule_version": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_RULE_VERSION
        ),
        "classification_framework_sha256": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        ),
        "classification_supplement_sha256": None,
        "classification_set_hash": canonical_sha256(
            {
                "injuries": [],
                "suspensions": [],
                "unclassifiable": ["f" * 64],
            }
        ),
        "residual_profile": _p0_absence_profile(
            authority=authority,
            selection=selection,
            partition=next(iter(selection["partitions"])),
            attempt_slot=attempt_slot,
            unclassifiable_count=1,
        ),
        "invariant": "FAIL",
    }
    for cell in counts["families"]:
        if cell["family"] not in {"injuries", "suspensions"}:
            continue
        cell["unclassifiable_count"] = 1
        cell["probe_gate"] = "FAIL"
    _resign_p0_e1a_shard(
        shard,
        authority=authority,
        selection=selection,
        counts=counts,
        receipt_updates=(
            {
                "family_identity_gate": "FAIL",
                "sample_identity_gate": "FAIL",
                "scientific_status": "FAILED_IDENTITY_GATE",
            }
            if coherent_receipt
            else None
        ),
    )


def test_p0_absence_supplement_requires_two_bound_adjudications(
    tmp_path: Path,
) -> None:
    authority = replace(
        load_authority(
            ROOT,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        ),
        root=tmp_path,
    )
    selection = _p0_e1a_selection(authority)
    partition = next(iter(selection["partitions"]))
    assert isinstance(partition, Mapping)
    profile = _p0_absence_profile(
        authority=authority,
        selection=selection,
        partition=partition,
        attempt_slot=1,
        unclassifiable_count=1,
    )
    signature = next(iter(profile["semantic_signatures"]))
    assert isinstance(signature, Mapping)
    signature_sha = str(signature["signature_sha256"])
    profile_set_sha = canonical_sha256([profile["profile_sha256"]])
    prior = {
        "attempt_slot": 1,
        "measurement_integrity_gate": "PASS",
        "read_accounting_gate": "PASS",
        "checkpoint_gate": "PASS",
        "scientific_gate": "FAIL",
        "absence_residual_profiles": [profile],
        "absence_residual_profile_set_sha256": profile_set_sha,
        "stage_receipt_sha256": "f" * 64,
    }

    def reviewer(reviewer_id: str, category: str) -> Mapping[str, object]:
        return _signed_p0(
            {
                "reviewer_id": reviewer_id,
                "mission_id": authority.mission["mission_id"],
                "stage": "E1A",
                "architecture_fingerprint": evidence_architecture_fingerprint(
                    authority
                ),
                "classification_framework_sha256": (
                    coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
                ),
                "selection_sha256": selection["selection_sha256"],
                "source_stage_receipt_sha256": prior["stage_receipt_sha256"],
                "source_profile_set_sha256": profile_set_sha,
                "decisions": [
                    {"signature_sha256": signature_sha, "category": category}
                ],
            },
            field="adjudication_sha256",
        )

    def supplement(
        *,
        consensus: str,
        reviewer_categories: tuple[str, str],
        reviewer_ids: tuple[str, str] = ("A1", "C2"),
    ) -> Mapping[str, object]:
        return _signed_p0(
            {
                "schema_version": (
                    coverage_evidence_module.ABSENCE_SUPPLEMENT_SCHEMA_VERSION
                ),
                "mission_id": authority.mission["mission_id"],
                "mission_sha256": authority.mission_sha256,
                "stage": "E1A",
                "architecture_fingerprint": evidence_architecture_fingerprint(
                    authority
                ),
                "architecture_ordinal": selection["architecture_ordinal"],
                "classification_framework_sha256": (
                    coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
                ),
                "selection_sha256": selection["selection_sha256"],
                "inventory_sha256": selection["inventory_sha256"],
                "source_attempt_slot": 1,
                "source_stage_receipt_sha256": prior["stage_receipt_sha256"],
                "source_profile_set_sha256": profile_set_sha,
                "classifications": [
                    {"signature_sha256": signature_sha, "category": consensus}
                ],
                "reviewer_adjudications": [
                    reviewer(reviewer_ids[0], reviewer_categories[0]),
                    reviewer(reviewer_ids[1], reviewer_categories[1]),
                ],
                "effects": dict(ZERO_EFFECTS),
            },
            field="supplement_sha256",
        )

    path = (
        tmp_path
        / "configs"
        / "data"
        / "p0-absence-taxonomy-supplement-E1A-v1.json"
    )
    path.parent.mkdir(parents=True)
    agreed = supplement(
        consensus="INJURY",
        reviewer_categories=("INJURY", "INJURY"),
    )
    path.write_text(json.dumps(agreed), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="P0_ABSENCE_SUPPLEMENT_CLASSIFICATION_INVALID",
    ):
        coverage_evidence_module._load_absence_taxonomy_supplement(
            authority,
            selection=selection,
            prior=prior,
        )

    rogue_roles = supplement(
        consensus="UNCLASSIFIABLE",
        reviewer_categories=("UNCLASSIFIABLE", "UNCLASSIFIABLE"),
        reviewer_ids=("scientific-a", "scientific-b"),
    )
    path.write_text(json.dumps(rogue_roles), encoding="utf-8")
    with pytest.raises(ValueError, match="P0_ABSENCE_SUPPLEMENT_REVIEWER_ID_INVALID"):
        coverage_evidence_module._load_absence_taxonomy_supplement(
            authority,
            selection=selection,
            prior=prior,
        )

    quarantined = supplement(
        consensus="UNCLASSIFIABLE",
        reviewer_categories=("UNCLASSIFIABLE", "UNCLASSIFIABLE"),
    )
    path.write_text(json.dumps(quarantined), encoding="utf-8")
    supplement_sha, classifications = (
        coverage_evidence_module._load_absence_taxonomy_supplement(
            authority,
            selection=selection,
            prior=prior,
        )
    )
    assert supplement_sha == quarantined["supplement_sha256"]
    assert classifications == {signature_sha: "UNCLASSIFIABLE"}

    invalid_reviewer_promotion = supplement(
        consensus="UNCLASSIFIABLE",
        reviewer_categories=("INJURY", "INJURY"),
    )
    path.write_text(json.dumps(invalid_reviewer_promotion), encoding="utf-8")
    with pytest.raises(ValueError, match="P0_ABSENCE_SUPPLEMENT_DECISION_INVALID"):
        coverage_evidence_module._load_absence_taxonomy_supplement(
            authority,
            selection=selection,
            prior=prior,
        )


def test_p0_selection_plan_is_committed_scope_only_and_fail_closed() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)

    plan = build_partition_plan(selection, authority=authority)

    assert plan["matrix"] == {"include": [{"partition_id": "p0-e1a-135-2024-all16"}]}
    assert plan["partition_count"] == 1
    tampered = dict(selection)
    tampered["domain_stage"] = "E2"
    with pytest.raises(ValueError, match="P0_SELECTION_SIGNATURE_MISMATCH"):
        build_partition_plan(tampered, authority=authority)

    identity_tampered = json.loads(json.dumps(selection))
    identity_tampered["fixture_selection"]["samples"][0]["fixtures"][0]["canonical_fixture_id"] = (
        "api-football:fixture:999999"
    )
    unsigned_identity_tampered = {
        key: value for key, value in identity_tampered.items() if key != "selection_sha256"
    }
    identity_tampered["selection_sha256"] = canonical_sha256(unsigned_identity_tampered)
    with pytest.raises(ValueError, match="P0_SELECTION_FIXTURE_IDENTITY_INVALID"):
        build_partition_plan(identity_tampered, authority=authority)


def test_p0_reader_source_has_only_exact_get_boundary() -> None:
    module = P0_MODULE_PATH.read_text(encoding="utf-8")
    script = P0_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "replay_stream_cache_only" in module
    assert "normalize_payload" in module
    assert "create_r2_client" in module
    assert "API_FOOTBALL_KEY" not in module
    assert "API_FOOTBALL_KEY_MUST_NOT_BE_MOUNTED" in script
    for forbidden_method in (
        "list_objects_v2",
        "head_object",
        "put_object",
        "delete_object",
        "copy_object",
        "create_multipart_upload",
        "upload_part",
    ):
        assert forbidden_method not in module + script


def test_p0_measure_partition_binds_exact_frozen_sample_and_all_families() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    inventory = _p0_e1a_inventory(authority)
    reader = _P0PairReader(_p0_e1a_pair(inventory))

    receipt, counts = measure_partition(
        authority,
        selection=selection,
        partition_id="p0-e1a-135-2024-all16",
        inventory=inventory,
        reader=reader,  # type: ignore[arg-type]
        code_revision="2" * 40,
    )

    assert reader.requested == ["a" * 64]
    assert receipt["scientific_status"] == "MEASURED"
    assert receipt["frozen_fixture_proof_gate"] == "PASS"
    assert receipt["family_identity_gate"] == "PASS"
    assert receipt["sample_identity_gate"] == "PASS"
    assert receipt["sample_processing_gate"] == "FAIL"
    families = counts["families"]
    assert isinstance(families, list)
    assert [cell["family"] for cell in families] == list(authority.normalized_families)
    fixture_cell = next(cell for cell in families if cell["family"] == "fixtures")
    team_cell = next(cell for cell in families if cell["family"] == "teams")
    assert fixture_cell["rates"]["normalization_integrity"] == {
        "numerator": 10,
        "denominator": 10,
        "status": "KNOWN",
        "value": 1.0,
    }
    assert team_cell["rates"]["normalization_integrity"] == {
        "numerator": 20,
        "denominator": 20,
        "status": "KNOWN",
        "value": 1.0,
    }
    assert all(rate["status"] != "INVALID" for cell in families for rate in cell["rates"].values())


def test_p0_raw_fixture_identity_failure_cannot_be_laundered_by_normalization() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    inventory = _p0_e1a_inventory(authority)
    pair = _p0_e1a_pair(inventory)
    damaged_payload = json.loads(json.dumps(pair.payload))
    del damaged_payload["response"][0]["teams"]["away"]
    reader = _P0PairReader(replace(pair, payload=damaged_payload))

    receipt, counts = measure_partition(
        authority,
        selection=selection,
        partition_id="p0-e1a-135-2024-all16",
        inventory=inventory,
        reader=reader,  # type: ignore[arg-type]
        code_revision="2" * 40,
    )

    families = counts["families"]
    assert isinstance(families, list)
    fixture_cell = next(cell for cell in families if cell["family"] == "fixtures")
    team_cell = next(cell for cell in families if cell["family"] == "teams")
    assert receipt["family_identity_gate"] == "FAIL"
    assert receipt["sample_identity_gate"] == "FAIL"
    assert fixture_cell["invalid_count"] >= 1
    assert team_cell["invalid_count"] >= 1
    assert fixture_cell["probe_gate"] == "FAIL"
    assert team_cell["probe_gate"] == "FAIL"


def test_p0_real_measurement_cells_are_accepted_by_stage_aggregation(tmp_path: Path) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    inventory = _p0_e1a_inventory(authority)
    reader = _P0PairReader(_p0_e1a_pair(inventory))
    receipt, counts = measure_partition(
        authority,
        selection=selection,
        partition_id="p0-e1a-135-2024-all16",
        inventory=inventory,
        reader=reader,  # type: ignore[arg-type]
        code_revision="2" * 40,
    )

    shards = tmp_path / "shards"
    _write_p0_e1a_shard(
        shards,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    shard = shards / "p0-e1a-135-2024-all16"
    cost = json.loads((shard / "cost-report.json").read_text(encoding="utf-8"))
    checkpoint = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id="p0-e1a-135-2024-all16",
        code_revision="2" * 40,
        attempt_slot=1,
        status="COMPLETED",
        elapsed_seconds=1.0,
        output_bindings={
            "partition_receipt_sha256": receipt["partition_receipt_sha256"],
            "family_counts_sha256": counts["counts_sha256"],
            "cost_sha256": cost["cost_sha256"],
        },
    )
    for name, value in (
        ("partition-receipt.json", receipt),
        ("family-counts.json", counts),
        ("checkpoint-final.json", checkpoint),
    ):
        (shard / name).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    stage, feed, gate, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=shards,
    )

    assert stage["partition_count_verified"] == 1
    assert len(feed["cells"]) == len(authority.normalized_families)
    assert gate["stage"] == "E1A"


def test_p0_scope_filters_league_metadata_without_hiding_unknown_endpoints() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    inventory = _p0_e1a_inventory(authority)
    fixture = inventory.by_id["a" * 64]
    league_metadata = InventoryObject(
        object_id="9" * 64,
        receipt_id="8" * 64,
        receipt_hash="7" * 64,
        receipt_key=fixture.receipt_key.replace("endpoint=fixtures", "endpoint=leagues"),
        payload_key=fixture.payload_key.replace("endpoint=fixtures", "endpoint=leagues"),
        payload_sha256="6" * 64,
        stored_sha256="5" * 64,
        logical_bytes=1,
        stored_bytes=1,
        competition=fixture.competition,
        season=fixture.season,
        family="fixtures",
        task_id="8" * 64,
        provider_calls=1,
        rows_received=1,
    )
    with_metadata = VerifiedInventory(
        manifest_sha256=inventory.manifest_sha256,
        code_revision=inventory.code_revision,
        objects=(*inventory.objects, league_metadata),
        segments=(),
    )

    scoped = coverage_evidence_module._scope_objects(authority, with_metadata)

    assert len(scoped) == 30
    assert league_metadata not in scoped
    unsupported = InventoryObject(
        **{
            **league_metadata.as_dict(),
            "object_id": "4" * 64,
            "receipt_key": fixture.receipt_key.replace(
                "endpoint=fixtures", "endpoint=fixtures%2Funknown"
            ),
        }
    )
    with pytest.raises(ValueError, match="P0_INVENTORY_SOURCE_ENDPOINT_UNSUPPORTED"):
        coverage_evidence_module._scope_objects(
            authority,
            VerifiedInventory(
                manifest_sha256=inventory.manifest_sha256,
                code_revision=inventory.code_revision,
                objects=(*inventory.objects, unsupported),
                segments=(),
            ),
        )


def test_p0_fixture_census_deduplicates_and_keeps_status_applicability_explicit() -> None:
    def row(fixture_id: int, status: str) -> Mapping[str, object]:
        return {
            "provider_fixture_id": fixture_id,
            "data": {
                "fixture": {"status": {"short": status}},
                "league": {"round": f"Round {fixture_id}"},
                "teams": {
                    "home": {"id": fixture_id * 2},
                    "away": {"id": fixture_id * 2 + 1},
                },
            },
        }

    complete = coverage_evidence_module._fixture_row_census(
        [row(1, "FT"), row(1, "FT"), row(2, "PST")],
        pagination={"status": "COMPLETE"},
    )
    blocked = coverage_evidence_module._fixture_row_census(
        [row(1, "FT"), row(2, "1H")],
        pagination={"status": "COMPLETE"},
    )

    assert complete["status"] == "COMPLETE"
    assert complete["fixtures"] == 2
    assert complete["team_slots"] == 4
    assert complete["terminal_fixtures"] == 1
    assert complete["not_applicable_fixtures"] == 1
    assert blocked["status"] == "PARTIAL"
    assert blocked["blocking_fixture_statuses"] == {"1H": 1}


def test_p0_season_absence_partition_does_not_require_fixture_objects() -> None:
    selected = coverage_evidence_module._select_required_fixture_census_pairs(
        (object(),),  # type: ignore[arg-type]
        target_families=(
            "players",
            "player_season_statistics",
            "injuries",
            "suspensions",
        ),
        competition="api-football:135",
        season=2024,
    )

    assert selected == ()
    assert coverage_evidence_module._fixture_census(selected)["status"] == "PARTIAL"


def test_p0_semantic_identity_ignores_position_and_non_grain_fields() -> None:
    standing = {
        "provider_competition_id": 135,
        "season": 2024,
        "provider_team_id": 10,
        "data": {"group": "A"},
    }
    moved_standing = json.loads(json.dumps(standing))
    moved_standing["data"]["group"] = "B"
    event = {
        "canonical_id": "position:1",
        "provider_fixture_id": 100,
        "provider_team_id": 10,
        "provider_player_id": 20,
        "data": {
            "time": {"elapsed": 12, "extra": None},
            "type": "Card",
            "detail": "Yellow Card",
            "comments": None,
        },
    }
    moved_event = json.loads(json.dumps(event))
    moved_event["canonical_id"] = "position:999"

    assert coverage_evidence_module._semantic_key(
        "standings", standing
    ) == coverage_evidence_module._semantic_key("standings", moved_standing)
    assert coverage_evidence_module._semantic_key(
        "events", event
    ) == coverage_evidence_module._semantic_key("events", moved_event)


def test_p0_aggregate_requires_exact_cells_and_rejects_invalid_rates(tmp_path: Path) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    valid_cells = [_p0_cell(family=family) for family in authority.normalized_families]
    valid_dir = tmp_path / "valid"
    _write_p0_e1a_shard(
        valid_dir,
        authority=authority,
        selection=selection,
        cells=valid_cells,
    )

    stage, feed, gate, cost = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=valid_dir,
    )

    assert stage["scientific_gate"] == "PASS"
    assert stage["domain_decision"] == "PASS_AND_SCALE"
    assert stage["council_decision"] == "PASS_AND_HOLD"
    assert stage["cell_count_verified"] == 16
    assert stage["mission_budget_exact"] is True
    assert stage["resource_budget_gate"] == "PASS"
    assert stage["checkpoint_gate"] == "PASS"
    assert len(stage["checkpoint_hashes"]) == 1
    assert stage["time_budget_gate"] == "PASS"
    assert stage["memory_budget_gate"] == "UNKNOWN_NO_SIGNED_LIMIT"
    lineage_manifest = stage["source_lineage_manifest"]
    assert gate["scientific_gate"] == "PASS"
    assert gate["architecture_fingerprint"] == stage["architecture_fingerprint"]
    assert gate["attempt_slot"] == 1
    assert gate["checkpoint_gate"] == "PASS"
    assert gate["checkpoint_hashes"] == stage["checkpoint_hashes"]
    assert gate["source_lineage_manifest_sha256"] == lineage_manifest["lineage_manifest_sha256"]
    assert cost["architecture_fingerprint"] == stage["architecture_fingerprint"]
    assert cost["architecture_ordinal"] == stage["architecture_ordinal"]
    assert cost["attempt_slot"] == 1
    assert cost["mission_accounting_baseline"] == stage["mission_accounting_baseline"]
    assert cost["accounting_parent_receipt_sha256"] is None
    assert cost["cumulative_mission_logical_gets_observed"] == 6
    assert feed["weighted_rates"]["content_presence"]["status"] == "UNKNOWN"
    assert lineage_manifest["schema_version"] == "p0-coverage-stage-lineage-v1"
    assert len(lineage_manifest["objects"]) == 1
    assert len(lineage_manifest["cells"]) == 16
    assert all(
        "source_lineage" not in cell and "processing_source_object_ids" not in cell
        for cell in feed["cells"]
    )

    unproven_dir = tmp_path / "unproven"
    unproven_cells = [
        _p0_cell(family=family, probe_pass=False) for family in authority.normalized_families
    ]
    _write_p0_e1a_shard(
        unproven_dir,
        authority=authority,
        selection=selection,
        cells=unproven_cells,
    )
    unproven_stage, _, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=unproven_dir,
    )
    assert unproven_stage["scientific_gate"] == "FAIL"
    assert unproven_stage["scale_gate"] == "FAIL"
    assert unproven_stage["domain_decision"] == "FAIL_AND_STOP"
    assert len(unproven_stage["missing_source_cell_keys"]) == 16

    missing_dir = tmp_path / "missing"
    _write_p0_e1a_shard(
        missing_dir,
        authority=authority,
        selection=selection,
        cells=valid_cells[:-1],
    )
    missing_stage, _, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=missing_dir,
    )
    assert missing_stage["scientific_gate"] == "FAIL"
    assert missing_stage["domain_decision"] == "FAIL_AND_STOP"
    assert missing_stage["read_accounting_gate"] == "FAIL"
    assert missing_stage["cumulative_mission_logical_gets_observed"] == ("UNKNOWN_NOT_OBSERVED")

    invalid_cells = json.loads(json.dumps(valid_cells))
    invalid_rate = {
        "numerator": 10,
        "denominator": 0,
        "status": "INVALID",
        "value": None,
    }
    invalid_cells[0]["rates"]["normalization_integrity"] = invalid_rate
    invalid_cells[0]["normalization_integrity"] = invalid_rate
    invalid_cells[0]["raw_eligible_unique_entities"] = 0
    invalid_cells[0]["probe_gate"] = "FAIL"
    invalid_cells[0].pop("cell_hash")
    invalid_cells[0] = _signed_p0(invalid_cells[0], field="cell_hash")
    invalid_dir = tmp_path / "invalid"
    _write_p0_e1a_shard(
        invalid_dir,
        authority=authority,
        selection=selection,
        cells=invalid_cells,
    )
    invalid_stage, _, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=invalid_dir,
    )
    assert invalid_stage["scientific_gate"] == "FAIL"
    assert invalid_stage["invalid_rate_cells"] == 1

    ambiguous_cells = json.loads(json.dumps(valid_cells))
    ambiguous_cells[0]["unclassifiable_count"] = 1
    ambiguous_cells[0]["probe_gate"] = "FAIL"
    ambiguous_cells[0].pop("cell_hash")
    ambiguous_cells[0] = _signed_p0(ambiguous_cells[0], field="cell_hash")
    ambiguous_dir = tmp_path / "ambiguous"
    _write_p0_e1a_shard(
        ambiguous_dir,
        authority=authority,
        selection=selection,
        cells=ambiguous_cells,
    )
    ambiguous_stage, _, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=ambiguous_dir,
    )
    assert ambiguous_stage["scientific_gate"] == "FAIL"


def test_p0_aggregate_preserves_complete_scientific_identity_failure(
    tmp_path: Path,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    cells = [_p0_cell(family=family) for family in authority.normalized_families]
    failed_dir = tmp_path / "scientific-failure"
    _write_p0_e1a_shard(
        failed_dir,
        authority=authority,
        selection=selection,
        cells=cells,
    )
    _rewrite_p0_e1a_shard_as_identity_failure(
        failed_dir / "p0-e1a-135-2024-all16",
        authority=authority,
        selection=selection,
        coherent_receipt=True,
    )

    stage, feed, gate, cost = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=failed_dir,
    )

    assert stage["invalid_shards"] == 0
    assert stage["partition_count_verified"] == 1
    assert stage["cell_count_verified"] == 16
    assert stage["measurement_integrity_gate"] == "PASS"
    assert stage["read_accounting_gate"] == "PASS"
    assert stage["checkpoint_gate"] == "PASS"
    assert stage["mission_budget_exact"] is True
    assert stage["scientific_gate"] == "FAIL"
    assert stage["scale_gate"] == "FAIL"
    assert stage["domain_decision"] == "FAIL_AND_REDESIGN"
    assert stage["council_decision"] == "FAIL_AND_REDESIGN"
    assert len(feed["cells"]) == 16
    assert gate["measurement_integrity_gate"] == "PASS"
    assert cost["read_accounting_gate"] == "PASS"

    inconsistent_dir = tmp_path / "inconsistent-failure"
    _write_p0_e1a_shard(
        inconsistent_dir,
        authority=authority,
        selection=selection,
        cells=cells,
    )
    _rewrite_p0_e1a_shard_as_identity_failure(
        inconsistent_dir / "p0-e1a-135-2024-all16",
        authority=authority,
        selection=selection,
        coherent_receipt=False,
    )
    inconsistent_stage, inconsistent_feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=inconsistent_dir,
    )
    assert inconsistent_stage["invalid_shards"] == 1
    assert inconsistent_stage["measurement_integrity_gate"] == "FAIL"
    assert inconsistent_feed["cells"] == []


@pytest.mark.parametrize(
    "identity_field",
    ("invalid_identity", "contradictory_duplicates", "exact_duplicates"),
)
def test_p0_aggregate_rejects_signed_nested_identity_count_mismatch(
    tmp_path: Path,
    identity_field: str,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    shard_directory = tmp_path / f"nested-{identity_field}"
    _write_p0_e1a_shard(
        shard_directory,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    shard = shard_directory / "p0-e1a-135-2024-all16"
    counts = json.loads((shard / "family-counts.json").read_text(encoding="utf-8"))
    injury_cell = next(
        cell for cell in counts["families"] if cell["family"] == "injuries"
    )
    injury_cell["counts"][identity_field] = 1
    _resign_p0_e1a_shard(
        shard,
        authority=authority,
        selection=selection,
        counts=counts,
    )

    stage, feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=shard_directory,
    )

    assert stage["invalid_shards"] == 1
    assert stage["measurement_integrity_gate"] == "FAIL"
    assert stage["scale_gate"] == "FAIL"
    assert feed["cells"] == []


def test_p0_aggregate_rejects_resealed_foreign_absence_profile_source_set(
    tmp_path: Path,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    shard_directory = tmp_path / "foreign-absence-source"
    _write_p0_e1a_shard(
        shard_directory,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    shard = shard_directory / "p0-e1a-135-2024-all16"
    counts = json.loads((shard / "family-counts.json").read_text(encoding="utf-8"))
    profile = dict(counts["absence_partition"]["residual_profile"])
    profile["source_absence_object_set_hash"] = canonical_sha256(["b" * 64])
    profile.pop("profile_sha256")
    counts["absence_partition"]["residual_profile"] = _signed_p0(
        profile,
        field="profile_sha256",
    )
    _resign_p0_e1a_shard(
        shard,
        authority=authority,
        selection=selection,
        counts=counts,
    )

    stage, feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=shard_directory,
    )

    assert stage["invalid_shards"] == 1
    assert stage["measurement_integrity_gate"] == "FAIL"
    assert feed["cells"] == []


def test_p0_aggregate_rejects_signed_absence_invariant_and_cell_mismatch(
    tmp_path: Path,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    shard_directory = tmp_path / "absence-binding"
    _write_p0_e1a_shard(
        shard_directory,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    shard = shard_directory / "p0-e1a-135-2024-all16"
    counts = json.loads((shard / "family-counts.json").read_text(encoding="utf-8"))
    counts["absence_partition"] = {
        "raw_distinct": 1,
        "injuries_distinct": 0,
        "suspensions_distinct": 0,
        "unclassifiable_distinct": 1,
        "classification_rule_version": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_RULE_VERSION
        ),
        "classification_framework_sha256": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        ),
        "classification_supplement_sha256": None,
        "classification_set_hash": canonical_sha256(
            {
                "injuries": [],
                "suspensions": [],
                "unclassifiable": ["f" * 64],
            }
        ),
        "residual_profile": _p0_absence_profile(
            authority=authority,
            selection=selection,
            partition=next(iter(selection["partitions"])),
            attempt_slot=1,
            unclassifiable_count=1,
        ),
        "invariant": "PASS",
    }
    _resign_p0_e1a_shard(
        shard,
        authority=authority,
        selection=selection,
        counts=counts,
    )

    stage, feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=shard_directory,
    )

    assert stage["invalid_shards"] == 1
    assert stage["measurement_integrity_gate"] == "FAIL"
    assert stage["scale_gate"] == "FAIL"
    assert feed["cells"] == []

    category_directory = tmp_path / "absence-category-binding"
    _write_p0_e1a_shard(
        category_directory,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    category_shard = category_directory / "p0-e1a-135-2024-all16"
    category_counts = json.loads(
        (category_shard / "family-counts.json").read_text(encoding="utf-8")
    )
    category_counts["absence_partition"] = {
        "raw_distinct": 3,
        "injuries_distinct": 2,
        "suspensions_distinct": 1,
        "unclassifiable_distinct": 0,
        "classification_rule_version": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_RULE_VERSION
        ),
        "classification_framework_sha256": (
            coverage_evidence_module.ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        ),
        "classification_supplement_sha256": None,
        "classification_set_hash": canonical_sha256(
            {
                "injuries": ["1" * 64, "3" * 64],
                "suspensions": ["2" * 64],
                "unclassifiable": [],
            }
        ),
        "residual_profile": _p0_absence_profile(
            authority=authority,
            selection=selection,
            partition=next(iter(selection["partitions"])),
            attempt_slot=1,
        ),
        "invariant": "PASS",
    }
    _resign_p0_e1a_shard(
        category_shard,
        authority=authority,
        selection=selection,
        counts=category_counts,
    )

    category_stage, category_feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=category_directory,
    )

    assert category_stage["invalid_shards"] == 1
    assert category_stage["measurement_integrity_gate"] == "FAIL"
    assert category_stage["scale_gate"] == "FAIL"
    assert category_feed["cells"] == []


@pytest.mark.parametrize(
    ("rate_name", "source_field"),
    (
        ("scope_completion", "source_scopes_expected"),
        ("normalization_integrity", "raw_eligible_unique_entities"),
        ("content_presence", "expected_content_slots"),
    ),
)
def test_p0_aggregate_rejects_rates_detached_from_source_counts(
    tmp_path: Path,
    rate_name: str,
    source_field: str,
) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    aggregate_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    cells = [_p0_cell(family=family) for family in authority.normalized_families]
    for cell in cells:
        cell[source_field] = 999
        if rate_name == "content_presence":
            cell["expected_count"] = 999
            cell["rates"][rate_name] = _p0_complete_rate()
            cell[rate_name] = cell["rates"][rate_name]
            cell["coverage_percent"] = 1.0
        cell.pop("cell_hash")
        cell.update(_signed_p0(cell, field="cell_hash"))
    detached_dir = tmp_path / rate_name
    _write_p0_e1a_shard(
        detached_dir,
        authority=authority,
        selection=selection,
        cells=cells,
    )

    stage, feed, _, _ = aggregate_stage(
        aggregate_authority,
        selection=selection,
        shards_directory=detached_dir,
    )

    assert stage["measurement_integrity_gate"] == "FAIL"
    assert stage["scientific_gate"] == "FAIL"
    assert stage["invalid_shards"] == 1
    assert feed["cells"] == []


def test_p0_checkpoints_and_second_attempts_are_fail_closed(tmp_path: Path) -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    selection = _p0_e1a_selection(authority)
    partition = next(iter(selection["partitions"]))
    assert isinstance(partition, Mapping)
    partition_id = str(partition["partition_id"])
    started = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id=partition_id,
        code_revision="2" * 40,
        attempt_slot=1,
        status="STARTED",
        elapsed_seconds=0,
    )
    failed = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id=partition_id,
        code_revision="2" * 40,
        attempt_slot=1,
        status="FAILED",
        elapsed_seconds=1,
        failure_code="MEASUREMENT_STEP_FAILED",
    )
    e4_authority = load_authority(
        ROOT,
        stage="E4",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    assert started["checkpoint_gate"] == "PENDING"
    assert started["reusable"] is False
    assert failed["checkpoint_gate"] == "FAIL"
    assert failed["failed_read_accounting"] == "UNKNOWN_NOT_OBSERVED"
    assert coverage_evidence_module._checkpoint_time_limit_seconds(e4_authority) == 300

    temp_authority = _p0_authority_with_committed_selection(
        tmp_path,
        authority=authority,
        selection=selection,
    )
    validate_stage_attempt(
        temp_authority,
        operation="measure",
        attempt_slot=1,
    )

    shard_directory = tmp_path / "shards"
    _write_p0_e1a_shard(
        shard_directory,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
    )
    successful_stage, _, _, _ = aggregate_stage(
        temp_authority,
        selection=selection,
        shards_directory=shard_directory,
    )
    stage_path = tmp_path / "reports" / "coverage" / "p0-evidence-ladder-stage-E1A-v1.json"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_text(
        json.dumps(successful_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_STAGE_ATTEMPT_ALREADY_COMMITTED"):
        validate_stage_attempt(
            temp_authority,
            operation="measure",
            attempt_slot=1,
        )
    with pytest.raises(ValueError, match="P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT"):
        validate_stage_attempt(
            temp_authority,
            operation="measure",
            attempt_slot=2,
        )
    with pytest.raises(ValueError, match="P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT"):
        aggregate_stage(
            temp_authority,
            selection=selection,
            shards_directory=shard_directory,
            attempt_slot=2,
        )

    operational_directory = tmp_path / "operational-interruption"
    operational_directory.mkdir()
    operational_stage, _, _, _ = aggregate_stage(
        temp_authority,
        selection=selection,
        shards_directory=operational_directory,
        attempt_slot=1,
    )
    assert operational_stage["attempt_slot"] == 1
    assert operational_stage["read_accounting_gate"] == "FAIL"
    assert operational_stage["checkpoint_gate"] == "FAIL"
    assert operational_stage["cumulative_mission_logical_gets_observed"] == ("UNKNOWN_NOT_OBSERVED")
    assert operational_stage["cumulative_mission_logical_gets_charged"] == 6
    assert operational_stage["mission_budget_accounting_basis"] == (
        "CONSERVATIVE_FULL_ATTEMPT_CHARGE"
    )
    assert operational_stage["mission_budget_gate"] == "PASS"
    stage_path.write_text(
        json.dumps(operational_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    validate_stage_attempt(
        temp_authority,
        operation="measure",
        attempt_slot=2,
    )

    retry_directory = tmp_path / "operational-retry"
    _write_p0_e1a_shard(
        retry_directory,
        authority=temp_authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
        attempt_slot=2,
    )
    retry_stage, _, _, _ = aggregate_stage(
        temp_authority,
        selection=selection,
        shards_directory=retry_directory,
        attempt_slot=2,
    )
    assert retry_stage["scientific_gate"] == "PASS"
    assert retry_stage["scale_gate"] == "PASS"
    assert retry_stage["cumulative_mission_logical_gets_observed"] == ("UNKNOWN_NOT_OBSERVED")
    assert retry_stage["cumulative_mission_logical_gets_observed_lower_bound"] == 6
    assert retry_stage["cumulative_mission_logical_gets_charged"] == 9
    assert retry_stage["mission_budget_exact"] is False
    assert retry_stage["mission_budget_gate"] == "PASS"
    stage_path.write_text(
        json.dumps(retry_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT"):
        validate_stage_attempt(
            temp_authority,
            operation="measure",
            attempt_slot=2,
        )

    freeze_root = tmp_path / "freeze-retry"
    freeze_authority = replace(authority, root=freeze_root)
    validate_stage_attempt(
        freeze_authority,
        operation="freeze",
        attempt_slot=2,
    )
    insufficient_freeze_budget = replace(
        freeze_authority,
        limits=replace(
            freeze_authority.limits,
            mission_gets=freeze_authority.limits.gets_per_job * 2 - 1,
        ),
    )
    with pytest.raises(ValueError, match="P0_FREEZE_ATTEMPT_MISSION_BUDGET_EXCEEDED"):
        validate_stage_attempt(
            insufficient_freeze_budget,
            operation="freeze",
            attempt_slot=2,
        )
    slot_two_selection = json.loads(json.dumps(selection))
    slot_two_selection["freeze_attempt_slot"] = 2
    slot_two_selection["failed_freeze_conservative_charge"] = authority.limits.gets_per_job
    slot_two_selection["planned_mission_logical_gets"] = (
        int(selection["planned_mission_logical_gets"]) + authority.limits.gets_per_job
    )
    slot_two_selection.pop("selection_sha256")
    slot_two_selection = _signed_p0(slot_two_selection, field="selection_sha256")
    coverage_evidence_module.validate_selection(
        slot_two_selection,
        authority=authority,
        stage="E1A",
    )

    retryable_unsigned = {
        key: value for key, value in successful_stage.items() if key != "stage_receipt_sha256"
    }
    retryable_unsigned.update(
        {
            "scientific_gate": "FAIL",
            "scale_gate": "FAIL",
            "domain_decision": "FAIL_AND_REDESIGN",
            "council_decision": "FAIL_AND_REDESIGN",
        }
    )
    retryable_stage = _signed_p0(
        retryable_unsigned,
        field="stage_receipt_sha256",
    )
    stage_path.write_text(
        json.dumps(retryable_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    validate_stage_attempt(
        temp_authority,
        operation="measure",
        attempt_slot=2,
    )
    current_charge = 1 + int(partition["planned_evidence_gets"])
    insufficient_budget = replace(
        temp_authority,
        limits=replace(
            temp_authority.limits,
            mission_gets=int(retryable_stage["cumulative_mission_logical_gets_observed"])
            + current_charge
            - 1,
        ),
    )
    with pytest.raises(ValueError, match="P0_SECOND_ATTEMPT_MISSION_BUDGET_EXCEEDED"):
        validate_stage_attempt(
            insufficient_budget,
            operation="measure",
            attempt_slot=2,
        )

    slot_two_unsigned = {
        key: value for key, value in retryable_stage.items() if key != "stage_receipt_sha256"
    }
    slot_two_unsigned["attempt_slot"] = 2
    slot_two_stage = _signed_p0(
        slot_two_unsigned,
        field="stage_receipt_sha256",
    )
    stage_path.write_text(
        json.dumps(slot_two_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT"):
        validate_stage_attempt(
            temp_authority,
            operation="measure",
            attempt_slot=2,
        )


def test_p0_mission_accounting_is_monotone_across_redesigns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = replace(
        load_authority(
            ROOT,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        ),
        root=tmp_path,
    )
    selection = _p0_e1a_selection(authority)
    selection_path = tmp_path / "configs" / "data" / "p0-coverage-evidence-selection-E1A-v1.json"
    selection_path.parent.mkdir(parents=True)
    selection_path.write_text(
        json.dumps(selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    stage_path = tmp_path / "reports" / "coverage" / "p0-evidence-ladder-stage-E1A-v1.json"
    stage_path.parent.mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()

    slot_one_shards = tmp_path / "slot-one-shards"
    _write_p0_e1a_shard(
        slot_one_shards,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
        attempt_slot=1,
    )
    _rewrite_p0_e1a_shard_as_identity_failure(
        slot_one_shards / "p0-e1a-135-2024-all16",
        authority=authority,
        selection=selection,
        coherent_receipt=True,
    )

    slot_one, _, _, _ = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=slot_one_shards,
        attempt_slot=1,
    )
    stage_path.write_text(
        json.dumps(slot_one, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    slot_two_shards = tmp_path / "slot-two-shards"
    _write_p0_e1a_shard(
        slot_two_shards,
        authority=authority,
        selection=selection,
        cells=[_p0_cell(family=family) for family in authority.normalized_families],
        attempt_slot=2,
    )
    _rewrite_p0_e1a_shard_as_identity_failure(
        slot_two_shards / "p0-e1a-135-2024-all16",
        authority=authority,
        selection=selection,
        coherent_receipt=True,
    )
    slot_two, _, _, _ = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=slot_two_shards,
        attempt_slot=2,
    )
    assert slot_two["attempt_slot"] == 2
    assert slot_two["scientific_gate"] == "FAIL"
    assert slot_two["cumulative_mission_logical_gets_charged"] == 9
    assert slot_two["accounting_parent_receipt_sha256"] == slot_one["stage_receipt_sha256"]
    assert slot_two["mission_accounting_ancestor_receipt_sha256s"] == [
        slot_one["stage_receipt_sha256"]
    ]
    stage_path.write_text(
        json.dumps(slot_two, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        coverage_evidence_module,
        "ALGORITHM_VERSION",
        "p0-coverage-evidence-algorithm-v3",
    )
    insufficient = replace(
        authority,
        limits=replace(authority.limits, mission_gets=10),
    )
    with pytest.raises(ValueError, match="P0_FREEZE_ATTEMPT_MISSION_BUDGET_EXCEEDED"):
        validate_stage_attempt(
            insufficient,
            operation="freeze",
            attempt_slot=1,
        )

    baseline, ordinal, pending, registry = coverage_evidence_module._mission_accounting_state(
        authority
    )
    assert baseline["source_stage_receipt_sha256"] == slot_two["stage_receipt_sha256"]
    assert baseline["cumulative_mission_logical_gets_charged"] == 9
    assert ordinal == 2
    assert pending == ()
    assert len(registry) == 2

    redesigned = _p0_e1a_selection(authority)
    redesigned["algorithm_version"] = coverage_evidence_module.ALGORITHM_VERSION
    redesigned["architecture_ordinal"] = ordinal
    redesigned["mission_architecture_registry"] = list(registry)
    redesigned["mission_accounting_baseline"] = dict(baseline)
    redesigned["planned_mission_logical_gets"] = 15
    redesigned.pop("selection_sha256")
    redesigned = _signed_p0(redesigned, field="selection_sha256")
    coverage_evidence_module.validate_selection(
        redesigned,
        authority=authority,
        stage="E1A",
    )

    stale = json.loads(json.dumps(redesigned))
    stale_baseline = stale["mission_accounting_baseline"]
    assert isinstance(stale_baseline, dict)
    stale_baseline["cumulative_mission_logical_gets_charged"] = 0
    stale_baseline["cumulative_mission_logical_gets_observed"] = 0
    stale_baseline["cumulative_mission_logical_gets_observed_lower_bound"] = 0
    stale_baseline["mission_budget_accounting_basis"] = "EXACT_OBSERVED"
    stale["planned_mission_logical_gets"] = 6
    stale.pop("selection_sha256")
    stale = _signed_p0(stale, field="selection_sha256")
    selection_path.write_text(
        json.dumps(stale, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_MISSION_ACCOUNTING_RECEIPT_INVALID"):
        validate_stage_attempt(
            authority,
            operation="measure",
            attempt_slot=1,
        )

    selection_path.write_text(
        json.dumps(redesigned, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    redesigned_stage, _, _, _ = aggregate_stage(
        authority,
        selection=redesigned,
        shards_directory=empty,
        attempt_slot=1,
    )
    assert redesigned_stage["architecture_ordinal"] == 2
    assert redesigned_stage["cumulative_mission_logical_gets_charged"] == 15
    assert redesigned_stage["cumulative_mission_logical_gets_observed"] == ("UNKNOWN_NOT_OBSERVED")
    assert (
        redesigned_stage["accounting_parent_receipt_sha256"] == (slot_two["stage_receipt_sha256"])
    )
    assert redesigned_stage["mission_accounting_ancestor_receipt_sha256s"] == [
        slot_one["stage_receipt_sha256"],
        slot_two["stage_receipt_sha256"],
    ]
    stage_path.write_text(
        json.dumps(redesigned_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    next_baseline, next_ordinal, next_pending, next_registry = (
        coverage_evidence_module._mission_accounting_state(authority)
    )
    assert next_baseline["cumulative_mission_logical_gets_charged"] == 15
    assert next_ordinal == 2
    assert next_pending == ()
    assert next_registry == registry

    monkeypatch.setattr(
        coverage_evidence_module,
        "ALGORITHM_VERSION",
        "p0-coverage-evidence-algorithm-v4",
    )
    with pytest.raises(ValueError, match="P0_MISSION_ARCHITECTURE_LIMIT_EXCEEDED"):
        validate_stage_attempt(
            authority,
            operation="freeze",
            attempt_slot=1,
        )


def test_committed_arch2_freeze_preserves_exact_329_baseline() -> None:
    authority = load_authority(
        ROOT,
        stage="E1A",
        now=datetime(2026, 8, 5, 8, tzinfo=UTC),
    )
    baseline, ordinal, pending, registry = coverage_evidence_module._mission_accounting_state(
        authority
    )
    assert baseline == {
        "schema_version": "p0-coverage-mission-accounting-baseline-v1",
        "source": "STAGE_RECEIPT",
        "source_stage": "E1A",
        "source_stage_receipt_sha256": (
            "d9431bb2a5e8eadcbc5bf1418460a92e83bd851fd33eb6b6eaecb416dbbb49cc"
        ),
        "source_architecture_fingerprint": (
            "1f311bafdd51a45fa08ac8ac6fb3c125d33d1fe402928e03061f9ddd1352fb21"
        ),
        "source_receipt_ancestor_sha256s": [
            "e4958efcb00a6355f23d6cb2f38879f954bf86b90414ebb2970a98a0d3945861"
        ],
        "cumulative_mission_logical_gets_charged": 329,
        "cumulative_mission_logical_gets_observed": 329,
        "cumulative_mission_logical_gets_observed_lower_bound": 329,
        "mission_budget_accounting_basis": "EXACT_OBSERVED",
    }
    assert ordinal == 2
    assert len(pending) == 1
    frozen = pending[0]
    assert frozen["selection_sha256"] == (
        "7bc29b41098767e1a93616eed104a5bd0ff2ae6de4dcafaf514d52f254ccf903"
    )
    assert frozen["stage"] == "E1A"
    assert frozen["ordinal"] == 2
    assert frozen["fingerprint"] == evidence_architecture_fingerprint(authority)
    assert registry[-1] == {
        "ordinal": 2,
        "architecture_fingerprint": evidence_architecture_fingerprint(authority),
    }

    selection = frozen["selection"]
    assert isinstance(selection, Mapping)
    freeze_gets = int(selection["freeze_observed_logical_gets"])
    measurement_gets = sum(
        1 + int(partition["planned_evidence_gets"])
        for partition in selection["partitions"]
    )
    assert (freeze_gets, measurement_gets) == (23, 153)
    assert 329 + freeze_gets + measurement_gets == 505
    validate_stage_attempt(authority, operation="measure", attempt_slot=1)
    with pytest.raises(
        ValueError,
        match="P0_STAGE_SELECTION_ALREADY_COMMITTED",
    ):
        validate_stage_attempt(authority, operation="freeze", attempt_slot=1)
    with pytest.raises(ValueError, match="P0_CURRENT_STAGE_RECEIPT_INVALID"):
        validate_stage_attempt(authority, operation="measure", attempt_slot=2)


def test_p0_architecture_two_scientific_failure_is_terminal() -> None:
    assert coverage_evidence_module._scale_failure_decision(
        selection={"architecture_ordinal": 2},
        attempt_slot=1,
        missing_source_cell_keys=(),
        scientific_failure=True,
    ) == "FAIL_AND_STOP"
    assert coverage_evidence_module._scale_failure_decision(
        selection={"architecture_ordinal": 2},
        attempt_slot=1,
        missing_source_cell_keys=(),
        scientific_failure=False,
    ) == "FAIL_AND_REDESIGN"
    assert coverage_evidence_module._scale_failure_decision(
        selection={"architecture_ordinal": 2},
        attempt_slot=2,
        missing_source_cell_keys=(),
        scientific_failure=False,
    ) == "FAIL_AND_STOP"
    assert coverage_evidence_module._scale_failure_decision(
        selection={"architecture_ordinal": 1},
        attempt_slot=2,
        missing_source_cell_keys=(("api-football:135", 2024, "injuries"),),
        scientific_failure=False,
    ) == "FAIL_AND_STOP"


def test_p0_mission_accounting_rejects_ambiguous_maximum(tmp_path: Path) -> None:
    authority = replace(
        load_authority(
            ROOT,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        ),
        root=tmp_path,
    )
    selection = _p0_e1a_selection(authority)
    selection_path = tmp_path / "configs" / "data" / "p0-coverage-evidence-selection-E1A-v1.json"
    selection_path.parent.mkdir(parents=True)
    selection_path.write_text(
        json.dumps(selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    receipt, _, _, _ = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=empty,
    )
    reports = tmp_path / "reports" / "coverage"
    reports.mkdir(parents=True)
    (reports / "p0-evidence-ladder-stage-E1A-v1.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    e1b_selection = json.loads(json.dumps(selection))
    e1b_selection["domain_stage"] = "E1B"
    e1b_selection.pop("selection_sha256")
    e1b_selection = _signed_p0(e1b_selection, field="selection_sha256")
    (selection_path.parent / "p0-coverage-evidence-selection-E1B-v1.json").write_text(
        json.dumps(e1b_selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    conflicting = {key: value for key, value in receipt.items() if key != "stage_receipt_sha256"}
    conflicting["stage"] = "E1B"
    conflicting["council_stage"] = "E1"
    conflicting["selection_sha256"] = e1b_selection["selection_sha256"]
    conflicting = _signed_p0(conflicting, field="stage_receipt_sha256")
    (reports / "p0-evidence-ladder-stage-E1B-v1.json").write_text(
        json.dumps(conflicting, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="P0_MISSION_ACCOUNTING_MAXIMUM_AMBIGUOUS"):
        coverage_evidence_module._mission_accounting_state(authority)


def test_p0_mission_accounting_rejects_cross_stage_selection_absorption(
    tmp_path: Path,
) -> None:
    authority = replace(
        load_authority(
            ROOT,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        ),
        root=tmp_path,
    )
    selection = _p0_e1a_selection(authority)
    selection_directory = tmp_path / "configs" / "data"
    selection_directory.mkdir(parents=True)
    (selection_directory / "p0-coverage-evidence-selection-E1A-v1.json").write_text(
        json.dumps(selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    receipt, _, _, _ = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=empty,
    )
    e1b_selection = json.loads(json.dumps(selection))
    e1b_selection["domain_stage"] = "E1B"
    e1b_selection.pop("selection_sha256")
    e1b_selection = _signed_p0(e1b_selection, field="selection_sha256")
    (selection_directory / "p0-coverage-evidence-selection-E1B-v1.json").write_text(
        json.dumps(e1b_selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    cross_stage = {key: value for key, value in receipt.items() if key != "stage_receipt_sha256"}
    cross_stage["stage"] = "E1B"
    cross_stage["council_stage"] = "E1"
    cross_stage["attempt_slot"] = 2
    cross_stage = _signed_p0(cross_stage, field="stage_receipt_sha256")
    reports = tmp_path / "reports" / "coverage"
    reports.mkdir(parents=True)
    (reports / "p0-evidence-ladder-stage-E1B-v1.json").write_text(
        json.dumps(cross_stage, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="P0_MISSION_ACCOUNTING_RECEIPT_INVALID"):
        coverage_evidence_module._mission_accounting_state(authority)


def test_p0_mission_accounting_rejects_predeclared_architecture(tmp_path: Path) -> None:
    authority = replace(
        load_authority(
            ROOT,
            stage="E1A",
            now=datetime(2026, 8, 5, 8, tzinfo=UTC),
        ),
        root=tmp_path,
    )
    selection = _p0_e1a_selection(authority)
    selection_path = tmp_path / "configs" / "data" / "p0-coverage-evidence-selection-E1A-v1.json"
    selection_path.parent.mkdir(parents=True)
    selection_path.write_text(
        json.dumps(selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    receipt, _, _, _ = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=empty,
    )
    stage_path = tmp_path / "reports" / "coverage" / "p0-evidence-ladder-stage-E1A-v1.json"
    stage_path.parent.mkdir(parents=True)

    predeclared_receipt = json.loads(json.dumps(receipt))
    predeclared_receipt.pop("stage_receipt_sha256")
    receipt_registry = predeclared_receipt["mission_architecture_registry"]
    assert isinstance(receipt_registry, list)
    receipt_registry.append(
        {
            "ordinal": 2,
            "architecture_fingerprint": "d" * 64,
        }
    )
    predeclared_receipt = _signed_p0(
        predeclared_receipt,
        field="stage_receipt_sha256",
    )
    stage_path.write_text(
        json.dumps(predeclared_receipt, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_MISSION_ACCOUNTING_RECEIPT_INVALID"):
        coverage_evidence_module._mission_accounting_state(authority)

    stage_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    predeclared_selection = json.loads(json.dumps(selection))
    predeclared_selection.pop("selection_sha256")
    selection_registry = predeclared_selection["mission_architecture_registry"]
    assert isinstance(selection_registry, list)
    selection_registry.append(
        {
            "ordinal": 2,
            "architecture_fingerprint": "d" * 64,
        }
    )
    predeclared_selection = _signed_p0(
        predeclared_selection,
        field="selection_sha256",
    )
    selection_path.write_text(
        json.dumps(predeclared_selection, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="P0_MISSION_ACCOUNTING_SELECTION_INVALID"):
        coverage_evidence_module._mission_accounting_state(authority)


def test_workflow_81_aggregates_partial_shards_for_diagnostics() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    aggregate = workflow["jobs"]["aggregate"]
    assert aggregate["if"] == (
        "${{ always() && !cancelled() && "
        "((inputs.operation == 'measure' && needs.attempt-reservation.result == 'success') || "
        "(inputs.operation == 'recover_measure' && needs.recovery-guard.result == 'success')) }}"
    )
    download = next(
        step for step in aggregate["steps"] if step.get("uses") == "actions/download-artifact@v4"
    )
    assert download["continue-on-error"] is True
