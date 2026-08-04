from __future__ import annotations

import csv
import gzip
import io
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from botocore.exceptions import ClientError, EndpointConnectionError

from robin.historical_deep import coverage_proof as coverage_proof_module
from robin.historical_deep.contracts import load_campaign_contract
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
from robin.historical_deep.gates import GATE_NAMES
from robin.historical_deep.normalization import canonical_sha256
from robin.historical_deep.segmented_replay import (
    PROJECTION_SCHEMA_VERSION,
    STAGING_MANIFEST_SCHEMA_VERSION,
    STAGING_PART_SCHEMA_VERSION,
    STAGING_TABLES,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs" / "historical-deep-data-harvest-v1.json"
WORKFLOW_PATH = (
    ROOT / ".github" / "workflows" / "81-historical-deep-coverage-proof-export.yml"
)
MODULE_PATH = ROOT / "src" / "robin" / "historical_deep" / "coverage_proof.py"
SCRIPT_PATH = ROOT / "scripts" / "export_historical_deep_coverage.py"

SOURCE_REVISION = "1" * 40
EXPORTER_REVISION = "2" * 40
SOURCE_RUN_TOKEN = "30593227942:1"
RECORDED_AT = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


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
        match="COVERAGE_PROOF_PROJECTION_STAGING_INVALID:"
        "STAGING_PROJECTION_PART_CONTRACT_MISMATCH",
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
        historical["code_revision"] = (
            SOURCE_REVISION if offset == 127 else "3" * 40
        )
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
            keys = tuple(
                key for key in sorted(self.objects) if key.startswith(prefix)
            )
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
    store = _r2_store(
        StubR2Client(response={"ContentLength": 9, "Body": body})
    )

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
        EndpointConnectionError(
            endpoint_url="https://credential-bearing-endpoint.invalid"
        ),
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
    stream_store = _r2_store(
        StubR2Client(response={"Body": StubStreamingBody(error=stream_error)})
    )
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
        raise EndpointConnectionError(
            endpoint_url="https://credential-bearing-endpoint.invalid"
        )

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


def test_workflow_81_has_only_r2_secrets_and_exact_artifact_paths() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    for trigger_name in ("workflow_dispatch", "workflow_call"):
        trigger = triggers[trigger_name]
        assert isinstance(trigger, dict)
        inputs = trigger["inputs"]
        assert isinstance(inputs, dict)
        assert inputs["source_code_revision"]["required"] is True
        assert inputs["source_run_token"]["required"] is True
        assert inputs["max_output_bytes"]["type"] == "number"
        assert inputs["max_output_bytes"]["default"] == 2_000_000
    call = triggers["workflow_call"]
    assert isinstance(call, dict)
    assert set(call["secrets"]) == {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }
    assert "API_FOOTBALL_KEY" not in text
    assert 'API_FOOTBALL_CALLS_ALLOWED: "0"' in text
    assert 'ODDS_API_CREDITS_ALLOWED: "0"' in text
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["export"]
    assert job["timeout-minutes"] == 45
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
    upload = next(
        step for step in steps if step.get("uses") == "actions/upload-artifact@v4"
    )
    paths = upload["with"]["path"]
    assert paths == (
        "artifacts/historical-deep-coverage-proof/coverage-proof.json\n"
        "artifacts/historical-deep-coverage-proof/coverage-proof.csv\n"
    )
    assert "**" not in paths


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
