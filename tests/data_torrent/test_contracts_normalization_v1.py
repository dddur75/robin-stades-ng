from __future__ import annotations

import hashlib
import io
import json
import tarfile
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

import robin.data_torrent.runtime as data_torrent_runtime
from robin.capture.official_schedule_sources import OfficialFixture, OfficialScheduleEvidence
from robin.chronos_production import DirectPostgresTarget, generation_hash, sign_document
from robin.data_torrent.archive import (
    artifact_index,
    coverage_csv,
    deterministic_tar_gz,
    json_artifact,
)
from robin.data_torrent.contracts import (
    RawResponseEnvelope,
    canonical_json_bytes,
    load_torrent_config,
    utc_text,
)
from robin.data_torrent.normalization import (
    load_team_aliases,
    normalize_batch,
    validate_official_team_aliases,
)
from robin.data_torrent.reporting import qa_matrix, verify_qa_matrix
from robin.data_torrent.runtime import (
    FINAL_ARTIFACT_NAMES,
    MISSION_MANIFEST_PATH,
    MISSION_MANIFEST_SHA256,
    MISSION_SOURCE_SHA256,
    NORMALIZED_CORE_MEMBER_NAMES,
    DataTorrentRuntimeError,
    _assert_chronos_verify_database_targets,
    _assert_meaningful_breadth,
    _decode_replay_archive,
    _lineage,
    _normalized_evidence_archive,
    _normalized_evidence_binding,
    _opportunity,
    _runtime_identity,
    _secret_scan,
    _validated_chronos_verify_artifact,
    _validated_hold_report,
    _validated_mission_manifest,
)
from robin.data_torrent.sources import OfficialCapture

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "data" / "torrent-live-v1.json"
ANCHOR = datetime(2026, 8, 29, 12, tzinfo=UTC)
QA_GATES = (
    "baseline_identity",
    "cross_run_claim",
    "loser_replay_no_reads",
    "migration_rbac",
    "production_bindings",
    "ordering_one_shot",
    "ledger_caps",
    "forbidden_effects",
    "secret_safety",
    "temporal_safety",
    "scope_horizon",
    "official_breadth",
    "odds_breadth",
    "raw_durability",
    "normalization_lineage",
    "fixture_mapping_coverage",
    "replay",
    "load",
    "artifact_closure",
    "ops_recovery_science",
    "ci_merge_postmerge",
)

_QA_ROW_PROOF_KEYS = (
    "gate_id",
    "priority",
    "predicate_id",
    "comparison",
    "observed",
    "required",
    "evidence_file",
    "evidence_pointer",
    "evidence",
    "dependency_proof_sha256",
)


def _qa_test_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _reconstruct_qa_matrix(document: dict[str, Any]) -> None:
    """Test-only resolver that does not rely on the production verifier."""

    rows = document["gates"]
    assert isinstance(rows, list)
    proof_hashes: list[str] = []
    reconstructed_statuses: list[str] = []
    for index, row in enumerate(rows):
        assert isinstance(row, dict)
        assert set(row) == {*_QA_ROW_PROOF_KEYS, "status", "proof_sha256"}
        assert row["comparison"] == "BOOLEAN_EQUALS"
        assert type(row["observed"]) is bool
        assert type(row["required"]) is bool
        evidence = row["evidence"]
        assert isinstance(evidence, list) and evidence
        for binding in evidence:
            assert set(binding) == {
                "evidence_file",
                "evidence_pointer",
                "evidence_role",
                "binding_sha256",
            }
            binding_payload = {
                "evidence_file": binding["evidence_file"],
                "evidence_pointer": binding["evidence_pointer"],
                "evidence_role": binding["evidence_role"],
            }
            assert binding["binding_sha256"] == _qa_test_hash(binding_payload)
        assert row["evidence_file"] == evidence[0]["evidence_file"]
        assert row["evidence_pointer"] == evidence[0]["evidence_pointer"]

        dependencies = row["dependency_proof_sha256"]
        assert isinstance(dependencies, list)
        if row["gate_id"] == "qa_terminal":
            assert index == len(rows) - 1
            assert dependencies == proof_hashes
            assert row["observed"] is all(status == "PASS" for status in reconstructed_statuses)
            assert [binding["evidence_pointer"] for binding in evidence] == [
                f"/gates/{prior}/proof_sha256" for prior in range(index)
            ]
        else:
            assert dependencies == []

        proof = {key: row[key] for key in _QA_ROW_PROOF_KEYS}
        expected_status = "PASS" if row["observed"] == row["required"] else "FAIL"
        assert row["status"] == expected_status
        assert row["proof_sha256"] == _qa_test_hash(proof)
        proof_hashes.append(row["proof_sha256"])
        reconstructed_statuses.append(expected_status)

    failed_priorities = {
        priority: sum(row["priority"] == priority and row["status"] == "FAIL" for row in rows)
        for priority in ("P0", "P1", "P2")
    }
    passed = sum(status == "PASS" for status in reconstructed_statuses)
    summary = {
        "passed": passed,
        "total": len(rows),
        "qa_acceptance_percent": int(100 * passed / len(rows)),
        **{priority.lower(): count for priority, count in failed_priorities.items()},
        "open_threads": len(rows) - passed,
    }
    assert document["summary"] == summary
    matrix_proof = {
        "schema_version": document["schema_version"],
        "generated_at_utc": document["generated_at_utc"],
        "gate_proof_sha256": proof_hashes,
        "summary": summary,
        "remaining_non_blocking_debt": document["remaining_non_blocking_debt"],
    }
    assert document["matrix_proof_sha256"] == _qa_test_hash(matrix_proof)


def _hex(sequence: int) -> str:
    return f"{sequence:064x}"


def _envelope(
    *,
    sequence: int,
    family: str,
    sport_key: str,
    source: str,
    observed_at: datetime,
    body: bytes,
    external_effect_sequence: int | None = None,
) -> RawResponseEnvelope:
    provider = family == "ODDS"
    return RawResponseEnvelope(
        response_id=_hex(1000 + sequence),
        family=family,  # type: ignore[arg-type]
        sport_key=sport_key,
        source=source,
        request_contract={
            "method": "GET",
            "sanitized_endpoint": source,
            "sport_key": sport_key,
        },
        retrieved_at_utc=observed_at,
        http_status=200,
        content_type="application/json",
        response_headers={"content-type": "application/json"},
        body=body,
        run_identity="github:dddur75/robin-stades-ng:99:1:" + "1" * 40,
        claim_identity="c" * 64,
        response_sequence=sequence,
        external_effect_sequence=(
            external_effect_sequence
            if external_effect_sequence is not None
            else sequence
            if sequence <= 5
            else sequence - 5
        ),
        external_operation_id=_hex(sequence),
        permit_hash=_hex(100 + sequence),
        dispatch_event_hash=_hex(200 + sequence),
        confirmation_event_hash=_hex(300 + sequence),
        provider_requests=int(provider),
        provider_credits=int(provider),
    )


def _synthetic_batch() -> tuple[
    tuple[OfficialScheduleEvidence, ...],
    tuple[RawResponseEnvelope, ...],
    dict[str, str],
]:
    config = load_torrent_config(CONFIG)
    evidences: list[OfficialScheduleEvidence] = []
    official: list[RawResponseEnvelope] = []
    odds: list[RawResponseEnvelope] = []
    for index, league in enumerate(config.leagues, start=1):
        home = f"Home {index}"
        away = f"Away {index}"
        kickoff = ANCHOR + timedelta(days=1, hours=index)
        official_body = json.dumps({"sport": league.sport_key}).encode()
        official_source = f"https://official.example/{league.sport_key}"
        official.append(
            _envelope(
                sequence=index,
                family="OFFICIAL",
                sport_key=league.sport_key,
                source=official_source,
                observed_at=ANCHOR,
                body=official_body,
            )
        )
        evidences.append(
            OfficialScheduleEvidence(
                sport_key=league.sport_key,
                source_authority=official_source,
                source_content_sha256=hashlib.sha256(official_body).hexdigest(),
                source_observed_at_utc=ANCHOR,
                horizon_not_before_utc=ANCHOR,
                horizon_expires_at_utc=ANCHOR + timedelta(days=14),
                fixtures=(
                    OfficialFixture(
                        home=home,
                        away=away,
                        kickoff_utc=kickoff,
                        official_id=f"fixture-{index}",
                    ),
                ),
                adapter_revision="SYNTHETIC_OFFICIAL_V1",
                parser_metadata={"synthetic": True},
            )
        )
        odds_body = json.dumps(
            [
                {
                    "id": f"event-{index}",
                    "sport_key": league.sport_key,
                    "commence_time": kickoff.isoformat().replace("+00:00", "Z"),
                    "home_team": home,
                    "away_team": away,
                    "bookmakers": [
                        {
                            "key": "book",
                            "title": "Book",
                            "last_update": (ANCHOR + timedelta(seconds=15))
                            .isoformat()
                            .replace("+00:00", "Z"),
                            "markets": [
                                {
                                    "key": "h2h",
                                    "last_update": (ANCHOR + timedelta(seconds=20))
                                    .isoformat()
                                    .replace("+00:00", "Z"),
                                    "outcomes": [
                                        {"name": home, "price": 2.1},
                                        {"name": "Draw", "price": 3.2},
                                        {"name": away, "price": 3.4},
                                    ],
                                },
                                {
                                    "key": "totals",
                                    "last_update": (ANCHOR + timedelta(seconds=20))
                                    .isoformat()
                                    .replace("+00:00", "Z"),
                                    "outcomes": [
                                        {"name": "Over", "price": 1.9, "point": 2.5},
                                        {"name": "Under", "price": 1.9, "point": 2.5},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
            separators=(",", ":"),
        ).encode()
        odds.append(
            _envelope(
                sequence=5 + index,
                family="ODDS",
                sport_key=league.sport_key,
                source=f"https://api.the-odds-api.com/v4/sports/{league.sport_key}/odds",
                observed_at=ANCHOR + timedelta(minutes=1),
                body=odds_body,
            )
        )
    return (
        tuple(evidences),
        tuple((*official, *odds)),
        {item.sport_key: item.name for item in config.leagues},
    )


def test_config_is_strict_exact_and_rejects_duplicate_or_overflow(tmp_path: Path) -> None:
    config = load_torrent_config(CONFIG)
    assert len(config.leagues) == 5
    assert config.markets == ("h2h", "totals")
    duplicate = CONFIG.read_bytes().replace(
        b'"schema_version":',
        b'"schema_version":"duplicate","schema_version":',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_bytes(duplicate)
    with pytest.raises(ValueError, match="DATA_TORRENT_CONFIG_INVALID"):
        load_torrent_config(duplicate_path)
    document = json.loads(CONFIG.read_bytes())
    document["replay"]["minimum_throughput_ratio"] = 10**400
    overflow_path = tmp_path / "overflow.json"
    overflow_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="DATA_TORRENT_CONFIG_REPLAY_INVALID"):
        load_torrent_config(overflow_path)


def test_normalization_is_exact_accounted_and_idempotent() -> None:
    evidences, responses, league_names = _synthetic_batch()
    first = normalize_batch(
        evidences=evidences,
        raw_responses=responses,
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    second = normalize_batch(
        evidences=evidences,
        raw_responses=responses,
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    assert first.canonical_dataset_bytes == second.canonical_dataset_bytes
    assert first.canonical_dataset_sha256 == second.canonical_dataset_sha256
    assert len(first.records) == 30
    assert len(first.rejects) == 0
    assert len(first.coverage) == 10
    assert first.raw_events_observed == first.raw_events_accounted == 5
    assert first.silent_drops == first.logical_duplicates == first.temporal_leakage == 0
    official_records = [item for item in first.records if item["record_type"] == "OFFICIAL_FIXTURE"]
    assert all(
        item["source_pointer"] == "adapter_projection.fixtures[0]"
        and item["source_pointer_domain"] == "DETERMINISTIC_ADAPTER_PROJECTION"
        and item["source_adapter_revision"] == "SYNTHETIC_OFFICIAL_V1"
        for item in official_records
    )
    _assert_meaningful_breadth(
        config=load_torrent_config(CONFIG),
        evidences=evidences,
        batch=first,
    )


def test_reviewed_exact_team_alias_maps_provider_to_official_fixture(tmp_path: Path) -> None:
    aliases = load_team_aliases(ROOT / "config" / "alias_equipes.yaml")
    assert aliases["paris saint germain"] == "paris sg"
    duplicate = tmp_path / "aliases.yaml"
    duplicate.write_text('"Paris Saint Germain": "Paris SG"\n"Paris Saint Germain": "PSG"\n')
    with pytest.raises(ValueError, match="DATA_TORRENT_TEAM_ALIASES_DUPLICATE"):
        load_team_aliases(duplicate)
    chain = tmp_path / "chain.yaml"
    chain.write_text('"Alias A": "Alias B"\n"Alias B": "Stable"\n')
    with pytest.raises(ValueError, match="DATA_TORRENT_TEAM_ALIASES_CHAIN_FORBIDDEN"):
        load_team_aliases(chain)

    evidences, responses, league_names = _synthetic_batch()
    first_evidence = evidences[0]
    first_fixture = first_evidence.fixtures[0]
    aliased_evidence = replace(
        first_evidence,
        fixtures=(replace(first_fixture, home="Paris Saint-Germain"),),
    )
    provider_payload = json.loads(responses[5].body)
    provider_payload[0]["home_team"] = "Paris Saint Germain"
    provider_payload[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["name"] = (
        "Paris Saint Germain"
    )
    aliased_response = replace(
        responses[5],
        body=json.dumps(provider_payload, separators=(",", ":")).encode(),
    )
    batch = normalize_batch(
        evidences=(aliased_evidence, *evidences[1:]),
        raw_responses=(*responses[:5], aliased_response, *responses[6:]),
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
        team_aliases=aliases,
    )
    assert not any(item["reason"] == "PROVIDER_EVENT_UNMATCHED" for item in batch.rejects)
    assert any(
        item["record_type"] == "ODDS_OUTCOME"
        and item["sport_key"] == first_evidence.sport_key
        and item["home_team_mapping_method"] == "REVIEWED_ALIAS"
        and item["team_alias_mapping_sha256"]
        for item in batch.records
    )

    collision = replace(
        aliased_evidence,
        fixtures=(
            replace(first_fixture, home="Paris Saint-Germain"),
            replace(
                first_fixture,
                official_id="official-alias-collision",
                kickoff_utc=first_fixture.kickoff_utc + timedelta(hours=1),
                home="Paris Saint Germain",
            ),
        ),
    )
    with pytest.raises(ValueError, match="DATA_TORRENT_TEAM_ALIAS_SPORT_COLLISION"):
        validate_official_team_aliases((collision,), team_aliases=aliases)


@pytest.mark.parametrize(
    ("fixtures_captured", "coverage_percentage"),
    ((1, 5.0), (19, 95.0), (19, 100.0)),
)
def test_meaningful_breadth_requires_every_available_fixture(
    fixtures_captured: int,
    coverage_percentage: float,
) -> None:
    evidences, responses, league_names = _synthetic_batch()
    batch = normalize_batch(
        evidences=evidences,
        raw_responses=responses,
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    incomplete = replace(
        batch,
        coverage=(
            {
                **batch.coverage[0],
                "fixtures_available": 20,
                "fixtures_captured": fixtures_captured,
                "coverage_percentage": coverage_percentage,
            },
            *batch.coverage[1:],
        ),
    )
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_MEANINGFUL_BREADTH_FAILED"):
        _assert_meaningful_breadth(
            config=load_torrent_config(CONFIG),
            evidences=evidences,
            batch=incomplete,
        )


def test_duplicate_json_member_is_one_explicit_accounted_reject() -> None:
    evidences, responses, league_names = _synthetic_batch()
    first_odds = responses[5]
    malformed = replace(
        first_odds,
        body=b'[{"id":"one","id":"two"}]',
    )
    batch = normalize_batch(
        evidences=evidences,
        raw_responses=(*responses[:5], malformed, *responses[6:]),
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    assert any(item["reason"] == "ODDS_RESPONSE_JSON_DUPLICATE_KEY" for item in batch.rejects)
    assert batch.raw_events_observed == batch.raw_events_accounted == 5
    assert batch.silent_drops == 0
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_MEANINGFUL_BREADTH_FAILED"):
        _assert_meaningful_breadth(
            config=load_torrent_config(CONFIG),
            evidences=evidences,
            batch=batch,
        )


def test_archive_and_coverage_are_deterministic() -> None:
    rows = [
        {
            "league": "League",
            "sport_key": "soccer_epl",
            "market": "h2h",
            "fixtures_available": 1,
            "fixtures_captured": 1,
            "markets_requested": 1,
            "markets_returned": 1,
            "records_normalized": 3,
            "records_rejected": 0,
            "coverage_percentage": 100.0,
            "absence_reason": "NONE",
        }
    ]
    header = coverage_csv(rows).splitlines()[0].decode()
    assert header == (
        "league,sport_key,market,fixtures_available,fixtures_captured,"
        "markets_requested,markets_returned,records_normalized,records_rejected,"
        "coverage_percentage,absence_reason"
    )
    members = {"b/data.json": b"two", "a/data.json": b"one"}
    assert deterministic_tar_gz(members) == deterministic_tar_gz(
        dict(reversed(list(members.items())))
    )


def _synthetic_replay_archive() -> tuple[bytes, tuple[RawResponseEnvelope, ...]]:
    config = load_torrent_config(CONFIG)
    _evidences, initial, _league_names = _synthetic_batch()
    responses: list[RawResponseEnvelope] = []
    for item in initial:
        source = (
            config.leagues[item.response_sequence - 1].official_source.url
            if item.family == "OFFICIAL"
            else item.source
        )
        response_id = hashlib.sha256(
            canonical_json_bytes(
                {
                    "family": item.family,
                    "sport_key": item.sport_key,
                    "sequence": item.response_sequence,
                    "raw_sha256": hashlib.sha256(item.body).hexdigest(),
                }
            )
        ).hexdigest()
        responses.append(replace(item, response_id=response_id, source=source))
    response_tuple = tuple(responses)
    members = {
        f"responses/{item.response_sequence:03d}-{item.response_id}.bin": item.body
        for item in response_tuple
    }
    entries = [
        item.index_entry(
            archive_path=f"responses/{item.response_sequence:03d}-{item.response_id}.bin"
        )
        for item in response_tuple
    ]
    members["indexes/raw-index-core-v1.json"] = json_artifact(
        {
            "schema_version": "robin-data-torrent-real-batch-raw-index-v1",
            "mission_id": "data-torrent-ready-v1",
            "generated_at_utc": utc_text(ANCHOR),
            "run_identity": {"synthetic": True},
            "claim_identity": response_tuple[0].claim_identity,
            "responses": entries,
            "totals": {
                "raw_responses": len(response_tuple),
                "raw_bytes": sum(len(item.body) for item in response_tuple),
                "official_physical_reads": sum(
                    item.physical_reads for item in response_tuple if item.family != "ODDS"
                ),
                "odds_provider_requests": sum(item.provider_requests for item in response_tuple),
                "odds_credits_used": sum(item.provider_credits for item in response_tuple),
                "odds_dns_resolutions": len(config.leagues),
                "accounting_status": "PENDING_NORMALIZATION",
            },
        }
    )
    official_receipts = []
    for league, response in zip(config.leagues, response_tuple[:5], strict=True):
        official_receipts.append(
            {
                "schema_version": "robin-official-schedule-fetch-receipt-v1",
                "sport_key": league.sport_key,
                "adapter_revision": league.official_source.adapter,
                "requested_url": response.source,
                "final_url": response.source,
                "official_domain": "official.example",
                "observed_at_utc": utc_text(response.retrieved_at_utc),
                "http_status": response.http_status,
                "content_type": response.content_type,
                "byte_count": len(response.body),
                "raw_sha256": response.sha256,
                "redirect_chain": [],
                "accepted": True,
                "rejection_code": None,
                "supporting_official_reads": [],
            }
        )
    members["receipts/official-v1.json"] = json_artifact({"reads": official_receipts})
    members["receipts/provider-credit-v1.json"] = json_artifact({"synthetic": True})
    return deterministic_tar_gz(members), response_tuple


def test_replay_inputs_are_reconstructed_only_from_bound_raw_archive() -> None:
    archive, expected = _synthetic_replay_archive()
    official, reconstructed, raw_bytes = _decode_replay_archive(
        config=load_torrent_config(CONFIG),
        raw_archive=archive,
        expected_archive_sha256=hashlib.sha256(archive).hexdigest(),
        expected_run_identity=expected[0].run_identity,
        expected_claim_identity=expected[0].claim_identity,
    )
    assert [item.body for item in reconstructed] == [item.body for item in expected]
    assert set(official.results) == {item.sport_key for item in load_torrent_config(CONFIG).leagues}
    assert raw_bytes == sum(len(item.body) for item in expected)


def test_replay_archive_rejects_tampered_body_and_unindexed_member() -> None:
    archive, expected = _synthetic_replay_archive()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        members = {
            item.name: source.extractfile(item).read()  # type: ignore[union-attr]
            for item in source.getmembers()
        }
    first_path = next(name for name in sorted(members) if name.startswith("responses/"))
    members[first_path] += b"tampered"
    tampered = deterministic_tar_gz(members)
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_REPLAY_INDEX_BINDING_INVALID",
    ):
        _decode_replay_archive(
            config=load_torrent_config(CONFIG),
            raw_archive=tampered,
            expected_archive_sha256=hashlib.sha256(tampered).hexdigest(),
            expected_run_identity=expected[0].run_identity,
            expected_claim_identity=expected[0].claim_identity,
        )
    members[first_path] = expected[0].body
    members["unexpected.bin"] = b"forbidden"
    unexpected = deterministic_tar_gz(members)
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_REPLAY_INDEX_INVALID"):
        _decode_replay_archive(
            config=load_torrent_config(CONFIG),
            raw_archive=unexpected,
            expected_archive_sha256=hashlib.sha256(unexpected).hexdigest(),
            expected_run_identity=expected[0].run_identity,
            expected_claim_identity=expected[0].claim_identity,
        )


@pytest.mark.parametrize(
    ("container", "field", "forged_value"),
    (
        ("effect_accounting", "attempt", True),
        ("effect_accounting", "automatic_retries", False),
        ("effect_accounting", "physical_reads", True),
        ("effect_accounting", "provider_credits", 1.0),
        ("entry", "response_sequence", 1.0),
        ("entry", "http_status", "200"),
    ),
)
def test_replay_archive_rejects_json_type_smuggling(
    container: str,
    field: str,
    forged_value: object,
) -> None:
    archive, expected = _synthetic_replay_archive()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        members = {
            item.name: source.extractfile(item).read()  # type: ignore[union-attr]
            for item in source.getmembers()
        }
    raw_index = json.loads(members["indexes/raw-index-core-v1.json"])
    target = next(item for item in raw_index["responses"] if item["family"] == "ODDS")
    if container == "effect_accounting":
        target["effect_accounting"][field] = forged_value
    else:
        target[field] = forged_value
    members["indexes/raw-index-core-v1.json"] = json_artifact(raw_index)
    forged = deterministic_tar_gz(members)

    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_REPLAY_INDEX_INVALID"):
        _decode_replay_archive(
            config=load_torrent_config(CONFIG),
            raw_archive=forged,
            expected_archive_sha256=hashlib.sha256(forged).hexdigest(),
            expected_run_identity=expected[0].run_identity,
            expected_claim_identity=expected[0].claim_identity,
        )


def test_replay_archive_rejects_boolean_raw_totals() -> None:
    archive, expected = _synthetic_replay_archive()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        members = {
            item.name: source.extractfile(item).read()  # type: ignore[union-attr]
            for item in source.getmembers()
        }
    raw_index = json.loads(members["indexes/raw-index-core-v1.json"])
    raw_index["totals"]["odds_dns_resolutions"] = True
    members["indexes/raw-index-core-v1.json"] = json_artifact(raw_index)
    forged = deterministic_tar_gz(members)

    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_REPLAY_TOTALS_INVALID"):
        _decode_replay_archive(
            config=load_torrent_config(CONFIG),
            raw_archive=forged,
            expected_archive_sha256=hashlib.sha256(forged).hexdigest(),
            expected_run_identity=expected[0].run_identity,
            expected_claim_identity=expected[0].claim_identity,
        )


def test_measured_replay_reconstructs_archive_on_every_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(
        load_torrent_config(CONFIG),
        replay_multiplier=2,
        minimum_throughput_ratio=0.0,
    )
    archive, expected = _synthetic_replay_archive()
    evidences, _initial_responses, league_names = _synthetic_batch()
    original_decode = data_torrent_runtime._decode_replay_archive
    _baseline_official, reconstructed, expected_raw_bytes = original_decode(
        config=config,
        raw_archive=archive,
        expected_archive_sha256=hashlib.sha256(archive).hexdigest(),
        expected_run_identity=expected[0].run_identity,
        expected_claim_identity=expected[0].claim_identity,
    )
    official_by_sport = {
        item.sport_key: item for item in reconstructed if item.family == "OFFICIAL"
    }
    replay_evidences = tuple(
        replace(item, source_authority=official_by_sport[item.sport_key].source)
        for item in evidences
    )
    original = normalize_batch(
        evidences=replay_evidences,
        raw_responses=reconstructed,
        league_names=league_names,
        requested_markets=config.markets,
        run_identity=expected[0].run_identity,
        claim_identity=expected[0].claim_identity,
    )
    decoded_official: list[OfficialCapture] = []
    selected_official: list[OfficialCapture] = []

    def decode_with_previous_iteration_poisoned(
        **arguments: Any,
    ) -> tuple[OfficialCapture, tuple[RawResponseEnvelope, ...], int]:
        if decoded_official:
            decoded_official[-1].results.clear()
        decoded = original_decode(**arguments)
        decoded_official.append(decoded[0])
        return decoded

    def select_synthetic_evidence(
        *,
        official: OfficialCapture,
        **_arguments: Any,
    ) -> tuple[tuple[OfficialScheduleEvidence, ...], dict[str, Any]]:
        assert set(official.results) == {item.sport_key for item in config.leagues}
        selected_official.append(official)
        return replay_evidences, {}

    monkeypatch.setattr(
        data_torrent_runtime,
        "_decode_replay_archive",
        decode_with_previous_iteration_poisoned,
    )
    monkeypatch.setattr(data_torrent_runtime, "_select_evidence", select_synthetic_evidence)
    measurement = data_torrent_runtime._measure_replay(
        config=config,
        raw_archive=archive,
        raw_archive_sha256=hashlib.sha256(archive).hexdigest(),
        league_names=league_names,
        team_aliases={},
        run_identity=expected[0].run_identity,
        claim_identity=expected[0].claim_identity,
        anchor=ANCHOR,
        reconciliation_observed_at=ANCHOR,
        original=original,
        capture_started=ANCHOR,
        capture_ended=ANCHOR + timedelta(seconds=10),
        counter_snapshot=lambda: {"official_reads": 0, "provider_requests": 0},
    )

    assert len(decoded_official) == 2
    assert selected_official == decoded_official
    assert decoded_official[0].results == {}
    assert set(decoded_official[1].results) == {item.sport_key for item in config.leagues}
    assert decoded_official[0] is not decoded_official[1]
    assert measurement.final_batch.canonical_dataset_sha256 == original.canonical_dataset_sha256
    assert measurement.report["input"]["raw_archive_decode_count"] == 2
    assert measurement.report["input"]["raw_payload_parse_iterations"] == 2
    assert measurement.report["replay"]["total_bytes_processed"] == expected_raw_bytes * 2


def _set_json_pointer(document: dict[str, Any], pointer: str) -> None:
    tokens = pointer.removeprefix("/").split("/")
    current: Any = document
    for index, token in enumerate(tokens):
        last = index == len(tokens) - 1
        next_is_index = not last and tokens[index + 1].isdigit()
        if isinstance(current, dict):
            if last:
                current.setdefault(token, True)
            elif token not in current or not isinstance(current[token], (dict, list)):
                current[token] = [] if next_is_index else {}
            current = current[token]
        else:
            position = int(token)
            while len(current) <= position:
                current.append({})
            if last:
                current[position] = True
            current = current[position]


def _synthetic_final_artifacts() -> tuple[dict[str, bytes], dict[str, Any]]:
    binding = _normalized_evidence_binding(
        opportunity_id="a" * 64,
        object_key=f"data-torrent/v1/{'a' * 64}/normalized-evidence.tar.gz",
    )
    qa = qa_matrix(
        generated_at=ANCHOR,
        statuses={gate_id: True for gate_id in QA_GATES},
    )
    documents: dict[str, dict[str, Any]] = {
        name: {} for name in FINAL_ARTIFACT_NAMES if name.endswith(".json")
    }
    for gate in qa["gates"]:
        for evidence in gate["evidence"]:
            name = evidence["evidence_file"]
            pointer = evidence["evidence_pointer"]
            if pointer and name != "torrent-qa-acceptance-matrix-v1.json":
                _set_json_pointer(documents[name], pointer)
    documents["torrent-real-batch-normalized-index-v1.json"]["archive_object"] = binding
    documents["torrent-real-batch-quality-report-v1.json"].setdefault("durability", {})[
        "normalized_evidence_binding"
    ] = binding
    documents["torrent-r2-inventory-v1.json"]["objects"] = [{"role": "RAW"}, binding]
    documents["torrent-control-plane-event-chain-v1.json"]["events"] = {
        "external_sources": True,
        "normalized_evidence_terminal_resolver": binding,
    }
    manifest = documents["torrent-real-batch-manifest-v1.json"]
    manifest["schema_version"] = "robin-data-torrent-real-batch-manifest-v1"
    manifest["evidence_validity"] = {
        "mode": "CONDITIONAL_APPEND_ONLY_EXTERNAL_BINDING_V1",
        "binding": binding,
        "unbound_status": "INVALID",
    }
    artifacts = {
        name: (
            json_artifact(qa)
            if name == "torrent-qa-acceptance-matrix-v1.json"
            else json_artifact(documents[name])
            if name.endswith(".json") and name != "torrent-real-batch-manifest-v1.json"
            else b"synthetic-evidence\n"
        )
        for name in FINAL_ARTIFACT_NAMES
        if name != "torrent-real-batch-manifest-v1.json"
    }
    manifest["artifacts"] = artifact_index(artifacts)
    artifacts["torrent-real-batch-manifest-v1.json"] = json_artifact(manifest)
    return artifacts, binding


def test_normalized_evidence_archive_contains_exact_final_artifact_bytes() -> None:
    artifacts, binding = _synthetic_final_artifacts()
    normalized_members = {name: f"core:{name}".encode() for name in NORMALIZED_CORE_MEMBER_NAMES}
    archive = _normalized_evidence_archive(
        normalized_members=normalized_members,
        artifacts=artifacts,
        normalized_binding=binding,
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as extracted:
        observed = {
            member.name: extracted.extractfile(member).read()  # type: ignore[union-attr]
            for member in extracted.getmembers()
        }
    assert observed == {
        **normalized_members,
        **{f"evidence/{name}": payload for name, payload in artifacts.items()},
    }

    tampered = {**artifacts, "torrent-provider-credit-receipt-v1.json": b"{}\n"}
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_FINAL_ARTIFACT_INDEX_INVALID"):
        _normalized_evidence_archive(
            normalized_members=normalized_members,
            artifacts=tampered,
            normalized_binding=binding,
        )
    missing = dict(artifacts)
    missing.pop("torrent-provider-credit-receipt-v1.json")
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_FINAL_ARTIFACT_SET_INVALID"):
        _normalized_evidence_archive(
            normalized_members=normalized_members,
            artifacts=missing,
            normalized_binding=binding,
        )


def test_raw_envelope_rejects_secret_shaped_request_contract() -> None:
    base = _envelope(
        sequence=1,
        family="OFFICIAL",
        sport_key="soccer_epl",
        source="https://official.example/epl",
        observed_at=ANCHOR,
        body=b"payload",
    )
    with pytest.raises(ValueError, match="DATA_TORRENT_REQUEST_CONTRACT_SECRET_FORBIDDEN"):
        replace(base, request_contract={"api_key": "forbidden"})


def test_incomplete_market_is_removed_and_explicitly_accounted() -> None:
    evidences, responses, league_names = _synthetic_batch()
    first_odds = responses[5]
    payload = json.loads(first_odds.body)
    payload[0]["bookmakers"][0]["markets"][0]["outcomes"] = payload[0]["bookmakers"][0]["markets"][
        0
    ]["outcomes"][:2]
    incomplete = replace(
        first_odds,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    batch = normalize_batch(
        evidences=evidences,
        raw_responses=(*responses[:5], incomplete, *responses[6:]),
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    sport_key = evidences[0].sport_key
    assert not any(
        item["record_type"] == "ODDS_OUTCOME"
        and item["sport_key"] == sport_key
        and item["market_key"] == "h2h"
        for item in batch.records
    )
    assert (
        sum(
            item["reason"] == "MARKET_OUTCOMES_INCOMPLETE"
            and item["sport_key"] == sport_key
            and item["market_key"] == "h2h"
            for item in batch.rejects
        )
        == 1
    )
    assert batch.raw_events_observed == batch.raw_events_accounted == 5
    assert batch.silent_drops == 0


def test_provider_event_mapping_is_bijective_and_conflict_is_accounted() -> None:
    evidences, responses, league_names = _synthetic_batch()
    first_evidence = evidences[0]
    second_fixture = OfficialFixture(
        home="Second Home",
        away="Second Away",
        kickoff_utc=ANCHOR + timedelta(days=2, hours=1),
        official_id="fixture-second",
    )
    expanded_evidence = replace(
        first_evidence,
        fixtures=(*first_evidence.fixtures, second_fixture),
    )
    first_odds = responses[5]
    payload = json.loads(first_odds.body)
    conflicting = json.loads(json.dumps(payload[0]))
    conflicting.update(
        {
            "commence_time": second_fixture.kickoff_utc.isoformat().replace("+00:00", "Z"),
            "home_team": second_fixture.home,
            "away_team": second_fixture.away,
        }
    )
    payload.append(conflicting)
    duplicated_provider_id = replace(
        first_odds,
        body=json.dumps(payload, separators=(",", ":")).encode(),
    )
    batch = normalize_batch(
        evidences=(expanded_evidence, *evidences[1:]),
        raw_responses=(*responses[:5], duplicated_provider_id, *responses[6:]),
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    assert (
        sum(item["reason"] == "PROVIDER_EVENT_ONE_TO_ONE_CONFLICT" for item in batch.rejects) == 1
    )
    assert batch.raw_events_observed == batch.raw_events_accounted == 6
    assert batch.silent_drops == 0


def test_response_and_external_effect_sequences_are_distinct_and_lineage_is_complete() -> None:
    evidences, responses, league_names = _synthetic_batch()
    first_main = responses[0]
    supporting_body = json.dumps(
        {
            "matches": [
                {
                    "matchId": evidences[0].fixtures[0].official_id,
                    "date": utc_text(evidences[0].fixtures[0].kickoff_utc),
                }
            ]
        },
        sort_keys=True,
    ).encode()
    supporting = replace(
        first_main,
        response_id=_hex(9000),
        family="OFFICIAL_SUPPORTING",
        source="https://official.example/supporting",
        request_contract={
            **first_main.request_contract,
            "sanitized_endpoint": "https://official.example/supporting",
            "physical_response_index": 0,
        },
        body=supporting_body,
        response_sequence=1,
    )
    linked_fixture = replace(
        evidences[0].fixtures[0],
        source_authority=supporting.source,
        source_content_sha256=supporting.sha256,
        source_pointer="/matches/0",
        source_record_ordinal=0,
    )
    linked_evidences = (
        replace(evidences[0], fixtures=(linked_fixture,)),
        *evidences[1:],
    )
    shifted = tuple(
        replace(item, response_sequence=item.response_sequence + 1) for item in responses
    )
    raw_responses = (supporting, *shifted)
    batch = normalize_batch(
        evidences=linked_evidences,
        raw_responses=raw_responses,
        league_names=league_names,
        requested_markets=("h2h", "totals"),
        run_identity=responses[0].run_identity,
        claim_identity=responses[0].claim_identity,
    )
    lineage = _lineage(raw_responses=raw_responses, batch=batch)
    supporting_row = lineage["raw_responses"][0]
    first_odds_row = lineage["raw_responses"][6]
    assert supporting_row["response_sequence"] == 1
    assert supporting_row["external_effect_sequence"] == 1
    assert supporting_row["accounting_role"] == "NORMALIZED_SOURCE"
    assert supporting_row["linked_primary_response_id"] == shifted[0].response_id
    assert lineage["raw_responses"][1]["accounting_role"] == "PRIMARY_OFFICIAL_SELECTION_EVIDENCE"
    assert first_odds_row["family"] == "ODDS"
    assert first_odds_row["response_sequence"] == 7
    assert first_odds_row["external_effect_sequence"] == 1
    assert lineage["summary"]["raw_responses_observed"] == 11
    assert lineage["summary"]["raw_responses_accounted"] == 11
    assert lineage["summary"]["silent_responses"] == 0
    normalized_fixture = next(
        item
        for item in batch.records
        if item["record_type"] == "OFFICIAL_FIXTURE"
        and item["sport_key"] == linked_evidences[0].sport_key
    )
    assert normalized_fixture["source_response_id"] == supporting.response_id
    assert normalized_fixture["source_raw_sha256"] == supporting.sha256
    assert normalized_fixture["source_pointer"] == "/matches/0"
    assert normalized_fixture["source_pointer_domain"] == "RAW_RESPONSE_JSON_POINTER"
    odds_index = raw_responses[6].index_entry(archive_path="responses/007.bin")
    assert odds_index["response_sequence"] == 7
    assert odds_index["effect_accounting"]["sequence"] == 1


def test_qa_matrix_is_evidence_driven_and_terminal_fail_closed() -> None:
    passing = {gate_id: True for gate_id in QA_GATES}
    accepted = qa_matrix(generated_at=ANCHOR, statuses=passing)
    verify_qa_matrix(accepted)
    _reconstruct_qa_matrix(accepted)
    assert accepted["summary"] == {
        "passed": 22,
        "total": 22,
        "qa_acceptance_percent": 100,
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "open_threads": 0,
    }
    gates = {row["gate_id"]: row for row in accepted["gates"]}
    evidence = {
        gate_id: {
            (item["evidence_file"], item["evidence_pointer"], item["evidence_role"])
            for item in row["evidence"]
        }
        for gate_id, row in gates.items()
    }
    assert evidence["migration_rbac"] == {
        (
            "torrent-real-batch-manifest-v1.json",
            "/production/database_revision",
            "EXACT_PRODUCTION_DATABASE_REVISION",
        ),
        (
            "torrent-real-batch-manifest-v1.json",
            "/chronos_release_chain_proof",
            "ATTESTED_MIGRATION_RBAC_RELEASE_CHAIN",
        ),
    }
    assert {pointer for _file_name, pointer, _role in evidence["production_bindings"]} == {
        "/production/runtime_bindings_present",
        "/run_identity",
        "/chronos_release_chain_proof/database_target",
    }
    assert {pointer for _file_name, pointer, _role in evidence["ledger_caps"]} >= {
        "/effect_summary/actual",
        "/effect_summary/limits",
        "/counters",
        "/limits",
    }
    assert {file_name for file_name, _pointer, _role in evidence["secret_safety"]} == {
        "torrent-real-batch-manifest-v1.json"
    }
    assert {file_name for file_name, _pointer, _role in evidence["ops_recovery_science"]} == {
        "hypothesis-ready-field-dictionary-v1.json",
        "hypothesis-backlog-from-real-data-v1.md",
        "robin-data-torrent-operations-pack-v1.md",
        "robin-data-torrent-recovery-pack-v1.md",
    }
    assert evidence["artifact_closure"] == {
        (
            "torrent-real-batch-manifest-v1.json",
            "/artifacts",
            "FINAL_ARTIFACT_HASH_INVENTORY_EXCLUDING_MANIFEST_SELF",
        ),
        (
            "torrent-real-batch-manifest-v1.json",
            "/schema_version",
            "MANIFEST_SELF_WITNESS",
        ),
    }
    assert len(gates["qa_terminal"]["dependency_proof_sha256"]) == len(QA_GATES)

    failing = {**passing, "fixture_mapping_coverage": False}
    rejected = qa_matrix(generated_at=ANCHOR, statuses=failing)
    verify_qa_matrix(rejected)
    _reconstruct_qa_matrix(rejected)
    assert rejected["summary"] == {
        "passed": 20,
        "total": 22,
        "qa_acceptance_percent": 90,
        "p0": 0,
        "p1": 1,
        "p2": 1,
        "open_threads": 2,
    }
    assert rejected["gates"][-1]["gate_id"] == "qa_terminal"
    assert rejected["gates"][-1]["status"] == "FAIL"

    missing_evidence = deepcopy(accepted)
    missing_evidence["gates"][8]["evidence"].pop()
    with pytest.raises(AssertionError):
        _reconstruct_qa_matrix(missing_evidence)
    with pytest.raises(ValueError, match="DATA_TORRENT_QA_PROOF_INVALID"):
        verify_qa_matrix(missing_evidence)

    contradictory = deepcopy(accepted)
    contradictory["gates"][0]["status"] = "FAIL"
    with pytest.raises(AssertionError):
        _reconstruct_qa_matrix(contradictory)
    with pytest.raises(ValueError, match="DATA_TORRENT_QA_PROOF_INVALID"):
        verify_qa_matrix(contradictory)


def test_runtime_identity_binds_exact_linux_main_workflow_and_postmerge(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github" / "workflows" / "data-torrent-live-v1.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(b"name: exact-workflow\n")
    main_sha = "1" * 40
    workflow_hash = hashlib.sha256(workflow.read_bytes()).hexdigest()
    environment = {
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": main_sha,
        "GITHUB_WORKFLOW_SHA": main_sha,
        "GITHUB_WORKFLOW_REF": (
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        "DATA_TORRENT_EXPECTED_MAIN_SHA": main_sha,
        "DATA_TORRENT_POST_MERGE_CI_SHA": main_sha,
        "DATA_TORRENT_EXPECTED_WORKFLOW_SHA256": workflow_hash,
    }
    identity = _runtime_identity(
        repository_root=tmp_path,
        environment=environment,
        system_platform="linux",
    )
    assert identity.github.github_sha == main_sha
    assert identity.workflow_file_sha256 == workflow_hash
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_RERUN_FORBIDDEN"):
        _runtime_identity(
            repository_root=tmp_path,
            environment={**environment, "GITHUB_RUN_ATTEMPT": "2"},
            system_platform="linux",
        )
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_POST_MERGE_CI_MISMATCH"):
        _runtime_identity(
            repository_root=tmp_path,
            environment={**environment, "DATA_TORRENT_POST_MERGE_CI_SHA": "2" * 40},
            system_platform="linux",
        )
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_UBUNTU_REQUIRED"):
        _runtime_identity(
            repository_root=tmp_path,
            environment=environment,
            system_platform="win32",
        )


def test_immutable_mission_manifest_is_attested_before_live_clients(tmp_path: Path) -> None:
    target = tmp_path / MISSION_MANIFEST_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes((ROOT / MISSION_MANIFEST_PATH).read_bytes())
    environment = {
        "DATA_TORRENT_MISSION_MANIFEST": MISSION_MANIFEST_PATH,
        "DATA_TORRENT_EXPECTED_MISSION_MANIFEST_SHA256": MISSION_MANIFEST_SHA256,
    }
    manifest = _validated_mission_manifest(
        repository_root=tmp_path,
        environment=environment,
        observed_at_utc=ANCHOR,
    )
    assert manifest["manifest_sha256"] == MISSION_MANIFEST_SHA256
    assert manifest["source_hash"] == MISSION_SOURCE_SHA256
    first = _opportunity(manifest)
    mutable_config_metadata = {**manifest, "config_sha256": "a" * 64}
    second = _opportunity(mutable_config_metadata)
    assert first == second
    assert first.opportunity_kind == "DATA_TORRENT_MISSION_AUTHORIZATION"

    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_MISSION_MANIFEST_HASH_MISMATCH",
    ):
        _validated_mission_manifest(
            repository_root=tmp_path,
            environment=environment,
            observed_at_utc=ANCHOR,
        )


def test_immutable_mission_manifest_expires_fail_closed() -> None:
    environment = {
        "DATA_TORRENT_MISSION_MANIFEST": MISSION_MANIFEST_PATH,
        "DATA_TORRENT_EXPECTED_MISSION_MANIFEST_SHA256": MISSION_MANIFEST_SHA256,
    }
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_MISSION_MANIFEST_EXPIRED",
    ):
        _validated_mission_manifest(
            repository_root=ROOT,
            environment=environment,
            observed_at_utc=datetime(2026, 9, 2, tzinfo=UTC),
        )


def test_runtime_binds_sanitized_github_ci_receipt_before_claim(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "data-torrent-live-v1.yml"
    ci_workflow = tmp_path / ".github" / "workflows" / "ci-safe-v2.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(b"name: exact-workflow\n")
    ci_workflow.write_bytes(b"run: pytest tests/data_torrent/test_postgresql_v1.py\n")
    main_sha = "1" * 40
    environment = {
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": main_sha,
        "GITHUB_WORKFLOW_SHA": main_sha,
        "GITHUB_WORKFLOW_REF": (
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        "DATA_TORRENT_EXPECTED_MAIN_SHA": main_sha,
        "DATA_TORRENT_POST_MERGE_CI_SHA": main_sha,
        "DATA_TORRENT_EXPECTED_WORKFLOW_SHA256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
        "DATA_TORRENT_HOLD_REPORT": (".torrent/hold/chronos-production-workflow-hold-live-v3.json"),
    }
    identity = _runtime_identity(
        repository_root=tmp_path,
        environment=environment,
        system_platform="linux",
    )
    hold_path = tmp_path / environment["DATA_TORRENT_HOLD_REPORT"]
    hold_path.parent.mkdir(parents=True)
    hold: dict[str, Any] = {
        "schema_version": "chronos-production-workflow-hold-live-v3",
        "verdict": "WORKFLOW_HOLD_ESTABLISHED",
        "queued_after": 0,
        "in_progress_after": 0,
        "current_run_excluded": 123,
        "unauthorized_active_workflows": [],
        "provider_calls": 0,
        "r2_operations": 0,
        "legacy_secret_branch_sha": main_sha,
        "legacy_ci_workflow_quarantine": {
            "workflow_id": 319500816,
            "workflow_path": ".github/workflows/ci.yml",
            "state": "disabled_manually",
        },
        "production_environment_policy": {
            "environment": "chronos-control-plane-production",
            "can_admins_bypass": False,
            "protected_branches": False,
            "custom_branch_policies": True,
            "allowed_branches": ["main"],
        },
        "post_merge_ci": {
            "workflow_path": ".github/workflows/ci-safe-v2.yml",
            "run_id": 456,
            "run_attempt": 1,
            "head_sha": main_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        },
    }
    hold_path.write_text(json.dumps(hold), encoding="utf-8")
    proof = _validated_hold_report(
        repository_root=tmp_path,
        environment=environment,
        identity=identity,
    )
    assert proof["run_id"] == 456
    assert proof["head_sha"] == main_sha
    assert proof["conclusion"] == "success"
    assert proof["receipt_sha256"] == hashlib.sha256(hold_path.read_bytes()).hexdigest()
    hold["post_merge_ci"]["run_attempt"] = 2
    hold_path.write_text(json.dumps(hold), encoding="utf-8")
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_POST_MERGE_CI_PROOF_INVALID",
    ):
        _validated_hold_report(
            repository_root=tmp_path,
            environment=environment,
            identity=identity,
        )
    hold["post_merge_ci"]["run_attempt"] = 1
    hold["post_merge_ci"]["conclusion"] = "failure"
    hold_path.write_text(json.dumps(hold), encoding="utf-8")
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_POST_MERGE_CI_PROOF_INVALID",
    ):
        _validated_hold_report(
            repository_root=tmp_path,
            environment=environment,
            identity=identity,
        )


def test_runtime_binds_signed_chronos_verify_chain_before_claim(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "data-torrent-live-v1.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(b"name: exact-workflow\n")
    main_sha = "1" * 40
    nonce = "ab" * 32
    environment = {
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": main_sha,
        "GITHUB_WORKFLOW_SHA": main_sha,
        "GITHUB_WORKFLOW_REF": (
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        "DATA_TORRENT_EXPECTED_MAIN_SHA": main_sha,
        "DATA_TORRENT_POST_MERGE_CI_SHA": main_sha,
        "DATA_TORRENT_EXPECTED_WORKFLOW_SHA256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
        "DATA_TORRENT_EXPECTED_VERIFY_RUN_ID": "789",
        "DATA_TORRENT_VERIFY_ARTIFACT": (".torrent/release/chronos-production-verify-v3.json"),
    }
    identity = _runtime_identity(
        repository_root=tmp_path,
        environment=environment,
        system_platform="linux",
    )
    controlled_report_sha = "b" * 64
    controlled_go = {
        "schema_version": "chronos-controlled-go-binding-v1",
        "workflow_path": (".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"),
        "run_id": "111",
        "run_attempt": "1",
        "main_sha": main_sha,
        "report_schema": "chronos-neon-controlled-idle-wake-readonly-v1",
        "report_sha256": controlled_report_sha,
        "endpoint_pre_wake_state": "idle",
        "compute_wake_events": 1,
        "postgresql_connection_attempts": 1,
        "production_sql_writes": 0,
        "neon_mutations": 0,
        "durable_store": "R2_IMMUTABLE",
        "conditional_put_outcome": "CREATED",
        "durable_object_key": (
            "data-torrent-ready-v1/control-plane/controlled-go/"
            f"main_sha={main_sha}/run_id=111/"
            f"report-{controlled_report_sha}.json"
        ),
        "durable_readback_sha256": controlled_report_sha,
        "seal_workflow_path": (".github/workflows/chronos-controlled-go-durable-seal-v1.yml"),
        "seal_run_id": "222",
        "seal_run_attempt": "1",
        "seal_receipt_sha256": "c" * 64,
        "seal_r2_puts": 1,
        "seal_r2_gets": 1,
        "seal_r2_objects_created": 1,
        "preflight_readback_sha256": controlled_report_sha,
        "preflight_r2_gets": 1,
    }
    artifact = sign_document(
        {
            "schema_version": "chronos-production-verify-v3",
            "verdict": "CHRONOS_SCOPED_IDENTITIES_READY",
            "revision": "0015_data_torrent_opportunity",
            "main_sha": main_sha,
            "workflow_sha": main_sha,
            "post_merge_ci_sha": main_sha,
            "generation_hash": generation_hash(nonce),
            "preflight_run_id": "456",
            "preflight_hash": "d" * 64,
            "migration_run_id": "654",
            "migration_run_attempt": "1",
            "verify_run_id": "789",
            "verify_run_attempt": "1",
            "business_data_modified": False,
            "forbidden_membership": 0,
            "migrator_runtime_membership": 0,
            "runtime_effective_bootstrap_edge": 0,
            "provider_calls": 0,
            "r2_operations": 0,
            "controlled_go": controlled_go,
            "identities": {
                role: {
                    "database_host": "ep-test.eu-central-1.aws.neon.tech",
                    "database_port": 5432,
                    "database_name": "neondb",
                    "sslmode": "require",
                    "channel_binding": "require",
                    "current_user": login,
                    "revision": "0015_data_torrent_opportunity",
                    "server_epoch": "2026-08-29T12:00:00Z",
                    "memberships": [{"granted_role": group}],
                }
                for role, (login, group) in zip(
                    ("authority", "runtime", "reader"),
                    (
                        ("chronos_authority_runtime_login", "chronos_authority_executor"),
                        ("chronos_effect_runtime_login", "chronos_runtime_writer"),
                        ("chronos_reader_login", "chronos_reader"),
                    ),
                    strict=True,
                )
            },
        },
        nonce,
    )
    artifact_path = tmp_path / environment["DATA_TORRENT_VERIFY_ARTIFACT"]
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    proof = _validated_chronos_verify_artifact(
        repository_root=tmp_path,
        environment=environment,
        identity=identity,
        generation_token=nonce,
        expected_generation_hash=generation_hash(nonce),
    )
    assert proof["verify_run_id"] == "789"
    assert proof["migration_run_id"] == "654"
    assert proof["preflight_hash"] == "d" * 64
    assert proof["generation_hash"] == generation_hash(nonce)
    assert proof["controlled_go"] == controlled_go
    exact_targets = [
        DirectPostgresTarget(
            host="ep-test.eu-central-1.aws.neon.tech",
            port=5432,
            database="neondb",
            username=login,
            sslmode="require",
            channel_binding="require",
        )
        for login in (
            "chronos_authority_runtime_login",
            "chronos_effect_runtime_login",
            "chronos_reader_login",
        )
    ]
    _assert_chronos_verify_database_targets(proof=proof, targets=exact_targets)
    drifted = [
        *exact_targets[:2],
        DirectPostgresTarget(
            host="ep-other.eu-central-1.aws.neon.tech",
            port=5432,
            database="neondb",
            username="chronos_reader_login",
            sslmode="require",
            channel_binding="require",
        ),
    ]
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_VERIFY_DATABASE_TARGET_MISMATCH",
    ):
        _assert_chronos_verify_database_targets(proof=proof, targets=drifted)
    controlled_tamper = json.loads(json.dumps(artifact))
    controlled_tamper.pop("signature")
    controlled_tamper["controlled_go"]["seal_r2_puts"] = 2
    artifact_path.write_text(
        json.dumps(sign_document(controlled_tamper, nonce)),
        encoding="utf-8",
    )
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_VERIFY_CONTROLLED_GO_INVALID",
    ):
        _validated_chronos_verify_artifact(
            repository_root=tmp_path,
            environment=environment,
            identity=identity,
            generation_token=nonce,
            expected_generation_hash=generation_hash(nonce),
        )
    artifact["main_sha"] = "2" * 40
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_VERIFY_ARTIFACT_SIGNATURE_INVALID",
    ):
        _validated_chronos_verify_artifact(
            repository_root=tmp_path,
            environment=environment,
            identity=identity,
            generation_token=nonce,
            expected_generation_hash=generation_hash(nonce),
        )


def test_real_data_workflow_and_lock_are_frozen_for_one_shot_linux() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "data-torrent-live-v1.yml"
    content = workflow_path.read_text(encoding="utf-8")
    document = yaml.safe_load(content)
    triggers = document.get("on", document.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert set(triggers["workflow_dispatch"]["inputs"]) == {
        "expected_main_sha",
        "expected_workflow_sha256",
        "expected_mission_manifest_sha256",
        "expected_generation_hash",
        "post_merge_ci_sha",
        "verify_run_id",
    }
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert document["concurrency"] == {
        "group": "chronos-data-torrent-production-global-v1",
        "cancel-in-progress": False,
    }
    assert set(document["jobs"]) == {"validate", "torrent"}
    assert document["env"] == {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
        "THE_ODDS_API_HISTORICAL_CREDITS": "false",
        "API_FOOTBALL_CALLS_ALLOWED": "0",
    }
    validation = document["jobs"]["validate"]
    validation_source = validation["steps"][0]["run"]
    assert "GITHUB_RUN_ATTEMPT" in validation_source
    assert "git/ref/heads/main" in validation_source
    assert "VERIFY_RUN_ID" in validation_source
    job = document["jobs"]["torrent"]
    assert job["needs"] == "validate"
    assert job["runs-on"] == "ubuntu-latest"
    assert job["environment"] == "chronos-control-plane-production"
    assert job["env"]["PYTHONPATH"] == "${{ github.workspace }}/src"
    uses = {step["uses"] for step in job["steps"] if "uses" in step}
    assert uses == {
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    }
    setup = next(step for step in job["steps"] if "actions/setup-python@" in step.get("uses", ""))
    assert setup["with"] == {
        "python-version": "3.12.10",
        "cache": "pip",
        "cache-dependency-path": "requirements-data-torrent.lock",
    }
    hold_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Revalidate the protected GitHub workflow hold"
    )
    execute_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Execute the single real data torrent"
    )
    assert hold_index < execute_index
    assert "--required-successful-ci-sha" in job["steps"][hold_index]["run"]
    attestation_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Attest and download the exact successful Chronos VERIFY artifact"
    )
    main_revalidation_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Revalidate current main immediately before the one-shot effect"
    )
    assert attestation_index < hold_index < main_revalidation_index < execute_index
    assert "github_release_attestation_v1.py" in job["steps"][attestation_index]["run"]
    execute_environment = job["steps"][execute_index]["env"]
    secret_bindings = {
        name: value for name, value in execute_environment.items() if "secrets." in value
    }
    assert secret_bindings == {
        "CHRONOS_AUTHORITY_DATABASE_URL": "${{ secrets.CHRONOS_AUTHORITY_DATABASE_URL }}",
        "CHRONOS_RUNTIME_DATABASE_URL": "${{ secrets.CHRONOS_RUNTIME_DATABASE_URL }}",
        "CHRONOS_READER_DATABASE_URL": "${{ secrets.CHRONOS_READER_DATABASE_URL }}",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE": (
            "${{ secrets.CHRONOS_CONTROL_PLANE_GENERATION_NONCE }}"
        ),
        "THE_ODDS_API_KEY": "${{ secrets.ODDS_API_KEY }}",
        "R2_ACCOUNT_ID": "${{ secrets.R2_ACCOUNT_ID }}",
        "R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}",
        "R2_SECRET_ACCESS_KEY": "${{ secrets.R2_SECRET_ACCESS_KEY }}",
        "R2_BUCKET_NAME": "${{ secrets.R2_BUCKET_NAME }}",
    }
    assert execute_environment["DATA_TORRENT_EXPECTED_VERIFY_RUN_ID"] == (
        "${{ inputs.verify_run_id }}"
    )
    assert execute_environment["DATA_TORRENT_MISSION_MANIFEST"] == MISSION_MANIFEST_PATH
    assert execute_environment["DATA_TORRENT_EXPECTED_MISSION_MANIFEST_SHA256"] == (
        "${{ inputs.expected_mission_manifest_sha256 }}"
    )
    assert execute_environment["DATA_TORRENT_VERIFY_ARTIFACT"] == (
        ".torrent/release/chronos-production-verify-v3.json"
    )
    assert "secrets.NEON_" not in content
    assert "secrets.API_FOOTBALL_KEY" not in content
    assert "schedule:" not in content
    upload = next(
        step for step in job["steps"] if "actions/upload-artifact@" in step.get("uses", "")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["path"].splitlines() == [
        ".torrent/artifacts/**",
        ".torrent/hold/**",
        ".torrent/release/**",
    ]
    lock_lines = [
        line
        for line in (ROOT / "requirements-data-torrent.lock")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lock_lines) == 24
    assert all("==" in line and " --hash=sha256:" in line for line in lock_lines)


def test_secret_scan_includes_every_runtime_binding_and_bucket() -> None:
    environment = {
        "CHRONOS_AUTHORITY_DATABASE_URL": "postgresql://authority-secret",
        "CHRONOS_RUNTIME_DATABASE_URL": "postgresql://runtime-secret",
        "CHRONOS_READER_DATABASE_URL": "postgresql://reader-secret",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE": "a" * 64,
        "THE_ODDS_API_KEY": "provider-secret",
        "R2_ACCOUNT_ID": "account-secret",
        "R2_ACCESS_KEY_ID": "access-secret",
        "R2_SECRET_ACCESS_KEY": "object-secret",
        "R2_BUCKET_NAME": "bucket-secret",
    }
    _secret_scan(artifacts={"safe.json": b'{"status":"PASS"}'}, environment=environment)
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_SECRET_IN_ARTIFACT"):
        _secret_scan(
            artifacts={"unsafe.json": b'{"bucket":"bucket-secret"}'},
            environment=environment,
        )


def test_secret_scan_rejects_extracted_and_encoded_database_passwords() -> None:
    environment = {
        "CHRONOS_RUNTIME_DATABASE_URL": (
            "postgresql://runtime:s3cr%65t-X@db.example.invalid/chronos"
        ),
    }
    for leaked in (b"s3cret-X", b"s3cr%65t-X"):
        with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_SECRET_IN_ARTIFACT"):
            _secret_scan(artifacts={"unsafe.json": leaked}, environment=environment)
