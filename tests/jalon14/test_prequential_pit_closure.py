from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from robin.prospective_observatory import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
    InMemoryObjectStore,
    ProspectiveR2Repository,
)
from robin.prospective_observatory.contracts import (
    canonical_json_bytes,
    canonical_sha256,
)
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    _source_observation_manifest,
    persist_source_receipt,
    verify_source_receipt_artifact,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FeatureSnapshot,
    FixtureResultStatus,
    FixtureSettlementRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionStatus,
    TrainingDatasetManifest,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_storage import (
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
    StoredArtifact,
)
from robin.prospective_observatory.prequential_training import (
    challenger_model_version,
    eligible_training_examples,
    training_manifest_record_id,
)
from robin.prospective_observatory.r2 import (
    operational_odds_replay_projection,
    project_odds_rows,
)
from robin.storage.database import build_engine
from robin.storage.prospective_models import (
    CaptureReceiptModel,
    CaptureWindowModel,
    ProspectiveFixtureModel,
    ProspectiveOddsSnapshotModel,
    ProspectivePayloadIndexModel,
)
from robin.temporal.lineage import SourceReceipt, TemporalProofLevel
from scripts.run_prequential_learning_factory import (
    FixtureIdentity,
    _canonical_selection,
    _latest_fixtures,
    _odds_evidence,
    _select_odds_evidence,
    _training_run_id,
    _utc,
    _verified_result_from_record,
    _verify_replay_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=4)


def test_prequential_active_boundary_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="PREQUENTIAL_DATETIME_UTC_REQUIRED"):
        _utc(datetime(2026, 8, 14, 12))


def _config(url: str) -> Config:
    value = Config(str(ROOT / "alembic.ini"))
    value.set_main_option("script_location", str(ROOT / "migrations"))
    value.set_main_option("sqlalchemy.url", url)
    return value


def _upgrade(tmp_path: Path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'pit.db').as_posix()}"
    command.upgrade(_config(url), "head")
    return build_engine(url)


def _persist_result_observation(
    repository: PrequentialArtifactRepository,
    *,
    fixture_id: str,
    fixture_record_id: str,
    provider_fixture_id: str,
    attempt: int,
    observed_at: datetime,
    record: dict[str, object],
) -> StoredArtifact:
    guard_identity = {
        "fixture_id": fixture_id,
        "fixture_record_id": fixture_record_id,
        "provider_fixture_id": provider_fixture_id,
        "attempt": attempt,
        "operation": "VERIFY_FINAL_RESULT",
    }
    guard = repository.put_manifest(
        "provider-call-guards",
        {
            "schema_version": "prequential-provider-call-guard-v1",
            **guard_identity,
            "guard_id": canonical_sha256(guard_identity),
            "guarded_at": (observed_at - timedelta(seconds=1)).isoformat(),
        },
    )
    observation = repository.put_manifest(
        "result-observations",
        {
            "schema_version": "prequential-result-observation-v1",
            "provider": "api-football",
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "provider_fixture_id": provider_fixture_id,
            "attempt": attempt,
            "observed_at": observed_at.isoformat(),
            "availability": "PRESENT",
            "http_status": 200,
            "record": record,
            "provider_calls": 1,
        },
    )
    repository.put_manifest(
        "provider-call-completions",
        {
            "schema_version": "prequential-provider-call-completion-v1",
            "guard_sha256": guard.sha256,
            "observation_sha256": observation.sha256,
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "attempt": attempt,
            "completed_at": observed_at.isoformat(),
        },
    )
    return observation


def _fixture(
    *,
    record_id: str,
    registered_at: datetime,
    registry_hash: str,
) -> ProspectiveFixtureModel:
    return ProspectiveFixtureModel(
        id=record_id,
        idempotency_key=f"fixture:{record_id}",
        fixture_id="api-football:pit-42",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=KICKOFF,
        provider="api-football",
        provider_fixture_id="42",
        registered_at=registered_at,
        registry_hash=registry_hash,
        code_revision="test-pit",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )


def test_future_fixture_revision_cannot_change_as_of_head(tmp_path: Path) -> None:
    engine = _upgrade(tmp_path)
    with Session(engine) as session, session.begin():
        session.add_all(
            (
                _fixture(
                    record_id="fixture-record-v1",
                    registered_at=NOW - timedelta(minutes=1),
                    registry_hash="a" * 64,
                ),
                _fixture(
                    record_id="fixture-record-v2",
                    registered_at=NOW + timedelta(minutes=1),
                    registry_hash="b" * 64,
                ),
            )
        )
    assert [row.id for row in _latest_fixtures(engine, as_of=NOW)] == [
        "fixture-record-v1"
    ]


def test_source_receipt_rejects_cross_family_odds_capture_as_team_projection() -> None:
    store = InMemoryObjectStore()
    raw_repository = ProspectiveR2Repository(store)
    observed_at = NOW - timedelta(minutes=2)
    capture = raw_repository.capture(
        payload={
            "raw_payload_kind": "PROVIDER_RESPONSE_ENVELOPE",
            "raw_provider_payload": {"response": []},
            "normalized_family_records": [],
        },
        context=CaptureContext(
            window_id="fixture:ODDS:H-2",
            window_label="H-2",
            fixture_id="api-football:pit-42",
            competition="Ligue 1",
            season="2026",
            provider="api-football",
            family=CaptureFamily.ODDS,
            requested_at=observed_at - timedelta(seconds=2),
            response_received_at=observed_at - timedelta(seconds=1),
            observed_at=observed_at,
            cutoff_at=NOW,
            kickoff_at=KICKOFF,
            http_status=200,
            source_endpoint="https://v3.football.api-sports.io/odds",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision="test-pit",
            materialized_at=observed_at,
        ),
    )
    raw_receipt = capture.receipt
    team_value = {
        "home_team_id": "home-1",
        "away_team_id": "away-1",
        "kickoff_at": KICKOFF.isoformat(),
        "competition": "Ligue 1",
        "provider": "api-football",
        "provider_fixture_id": "pit-42",
    }
    closure_payload = {
        "schema_version": "prequential-prospective-source-closure-v1",
        "fixture_id": raw_receipt.fixture_id,
        "fixture_record_id": "fixture-record-v1",
        "raw_receipt_hash": raw_receipt.receipt_hash,
        "raw_payload_sha256": raw_receipt.payload_sha256,
        "raw_receipt_r2_key": raw_receipt.receipt_r2_key,
        "raw_payload_r2_key": raw_receipt.r2_key,
        "family": "team",
        "value": team_value,
        "payload_index": {
            "receipt_id": "receipt-row-1",
            "indexed_at": raw_receipt.materialized_at.isoformat(),
            "consumable_at": raw_receipt.materialized_at.isoformat(),
            "code_revision": raw_receipt.code_revision,
        },
    }
    provisional = SourceReceipt.create(
        source_name=raw_receipt.provider,
        request_identity=raw_receipt.receipt_hash,
        payload_sha256="0" * 64,
        source_published_at=raw_receipt.provider_updated_at,
        robin_first_observed_at=raw_receipt.response_received_at,
        robin_ingested_at=raw_receipt.materialized_at,
        capture_code_revision=raw_receipt.code_revision,
        storage_identity="pending://cross-family-source-observation",
        availability_status=TemporalProofLevel.PROSPECTIVE_CAPTURED,
        event_at=raw_receipt.event_time,
    )
    artifacts = PrequentialArtifactRepository(store)
    stored = artifacts.put_manifest(
        "source-observations",
        _source_observation_manifest(provisional, payload=closure_payload),
    )
    forged = SourceReceipt.create(
        source_name=provisional.source_name,
        request_identity=provisional.request_identity,
        payload_sha256=stored.sha256,
        source_published_at=provisional.source_published_at,
        robin_first_observed_at=provisional.robin_first_observed_at,
        robin_ingested_at=provisional.robin_ingested_at,
        capture_code_revision=provisional.capture_code_revision,
        storage_identity=stored.key,
        availability_status=provisional.availability_status,
        event_at=provisional.event_at,
    )

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SOURCE_RECEIPT_RAW_FAMILY_MISMATCH",
    ):
        verify_source_receipt_artifact(
            artifacts,
            forged,
            expected_family="team",
            expected_value=team_value,
            expected_fixture_id=raw_receipt.fixture_id,
            expected_fixture_record_id="fixture-record-v1",
        )


def test_source_receipt_rejects_backdated_market_closure_for_late_materialization() -> None:
    store = InMemoryObjectStore()
    raw_repository = ProspectiveR2Repository(store)
    capture_cutoff = NOW
    observed_at = capture_cutoff - timedelta(seconds=1)
    capture = raw_repository.capture(
        payload={
            "raw_payload_kind": "PROVIDER_RESPONSE_ENVELOPE",
            "raw_provider_payload": {"response": []},
            "normalized_family_records": [],
        },
        context=CaptureContext(
            window_id="fixture:ODDS:H-2-LATE-MATERIALIZATION",
            window_label="H-2",
            fixture_id="api-football:pit-42",
            competition="Ligue 1",
            season="2026",
            provider="api-football",
            family=CaptureFamily.ODDS,
            requested_at=observed_at - timedelta(seconds=2),
            response_received_at=observed_at,
            observed_at=observed_at,
            cutoff_at=capture_cutoff,
            kickoff_at=KICKOFF,
            http_status=200,
            source_endpoint="https://v3.football.api-sports.io/odds",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision="test-pit",
            materialized_at=capture_cutoff + timedelta(minutes=1),
        ),
    )
    raw_receipt = capture.receipt
    market_value = {
        "decimal_odds": {"HOME": 2.0, "DRAW": 3.4, "AWAY": 4.1},
        "bookmaker": "Book",
        "margin": 0.0,
        "coverage": 1.0,
    }
    artifacts = PrequentialArtifactRepository(store)

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SOURCE_RECEIPT_R2_MISMATCH",
    ):
        persist_source_receipt(
            artifacts,
            source_name=raw_receipt.provider,
            request_identity=raw_receipt.receipt_hash,
            payload={
                "schema_version": "prequential-prospective-source-closure-v1",
                "fixture_id": raw_receipt.fixture_id,
                "fixture_record_id": "fixture-record-v1",
                "raw_receipt_hash": raw_receipt.receipt_hash,
                "raw_payload_sha256": raw_receipt.payload_sha256,
                "raw_receipt_r2_key": raw_receipt.receipt_r2_key,
                "raw_payload_r2_key": raw_receipt.r2_key,
                "family": "market",
                "value": market_value,
                "payload_index": {
                    "receipt_id": "receipt-row-1",
                    "indexed_at": observed_at.isoformat(),
                    "consumable_at": observed_at.isoformat(),
                    "code_revision": raw_receipt.code_revision,
                },
            },
            source_published_at=raw_receipt.provider_updated_at,
            observed_at=raw_receipt.response_received_at,
            ingested_at=observed_at,
            code_revision=raw_receipt.code_revision,
            availability_status=TemporalProofLevel.PROSPECTIVE_CAPTURED,
            event_at=raw_receipt.event_time,
        )


def test_odds_requires_receipt_index_window_r2_and_ties_fail_closed(
    tmp_path: Path,
) -> None:
    engine = _upgrade(tmp_path)
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    capture_cutoff = KICKOFF - timedelta(hours=2)
    observed_at = capture_cutoff - timedelta(minutes=1)
    context = CaptureContext(
        window_id="fixture:ODDS:H-2",
        window_label="H-2",
        fixture_id="api-football:pit-42",
        competition="Ligue 1",
        season="2026",
        provider="api-football",
        family=CaptureFamily.ODDS,
        requested_at=observed_at - timedelta(seconds=2),
        response_received_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at,
        cutoff_at=capture_cutoff,
        kickoff_at=KICKOFF,
        http_status=200,
        source_endpoint="https://v3.football.api-sports.io/odds",
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=1,
        code_revision="test-pit",
        materialized_at=observed_at,
    )
    odds_record = {
        "bookmakers": [
            {
                "key": "Book",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "HOME", "price": 2.0},
                            {"name": "DRAW", "price": 3.4},
                            {"name": "AWAY", "price": 4.1},
                        ],
                    }
                ],
            }
        ]
    }
    capture = repository.capture(
        payload={
            "raw_payload_kind": "PROVIDER_RESPONSE_ENVELOPE",
            "raw_provider_payload": {"response": [odds_record]},
            "normalized_family_records": [odds_record],
        },
        context=context,
    )
    receipt = capture.receipt
    projected_rows = project_odds_rows(
        receipt,
        operational_odds_replay_projection(receipt, capture.payload),
    )
    assert len(projected_rows) == 3
    receipt_row_id = str(projected_rows[0]["receipt_id"])
    with Session(engine) as session, session.begin():
        session.add(
            _fixture(
                record_id="fixture-record-v1",
                registered_at=NOW - timedelta(days=1),
                registry_hash="a" * 64,
            )
        )
        session.flush()
        session.add(
            CaptureWindowModel(
                id="window-row-1",
                window_id="fixture:ODDS:H-2",
                fixture_record_id="fixture-record-v1",
                fixture_id=receipt.fixture_id,
                family=CaptureFamily.ODDS.value,
                label="H-2",
                due_at=capture_cutoff - timedelta(minutes=5),
                opens_at=capture_cutoff - timedelta(hours=1),
                cutoff_at=capture_cutoff,
                kickoff_at=KICKOFF,
                scheduled_at=NOW,
                operational_tolerance_seconds=3600,
                status=AvailabilityStatus.COMPLETE.value,
                policy_version="test-pit-v1",
                code_revision="test-pit",
                append_only=True,
            )
        )
        session.flush()
        session.add(
            CaptureReceiptModel(
                id=receipt_row_id,
                receipt_hash=receipt.receipt_hash,
                window_id=receipt.window_id,
                window_record_id="window-row-1",
                fixture_id=receipt.fixture_id,
                competition=receipt.competition,
                season=receipt.season,
                provider=receipt.provider,
                family=receipt.family.value,
                window_label=receipt.window_label,
                requested_at=receipt.requested_at,
                response_received_at=receipt.response_received_at,
                observed_at=receipt.observed_at,
                event_time=receipt.event_time,
                provider_updated_at=receipt.provider_updated_at,
                cutoff_at=receipt.cutoff_at,
                kickoff_at=receipt.kickoff_at,
                materialized_at=receipt.materialized_at,
                seconds_before_kickoff=receipt.seconds_before_kickoff,
                http_status=receipt.http_status,
                payload_sha256=receipt.payload_sha256,
                payload_bytes=receipt.payload_bytes,
                stored_bytes=receipt.stored_bytes,
                r2_key=receipt.r2_key,
                receipt_r2_key=receipt.receipt_r2_key,
                source_endpoint=receipt.source_endpoint,
                complete=receipt.complete,
                quality_status=receipt.quality_status.value,
                provider_calls=receipt.provider_calls,
                code_revision=receipt.code_revision,
                append_only=True,
            )
        )
        session.flush()
        for projected in projected_rows:
            session.add(
                ProspectiveOddsSnapshotModel(
                    **projected,
                )
            )

    with pytest.raises(ValueError, match="PREQUENTIAL_ODDS_PAYLOAD_INDEX_MISSING"):
        _odds_evidence(
            engine,
            fixture_record_id="fixture-record-v1",
            fixture_id=receipt.fixture_id,
            market=PredictionMarket.ONE_X_TWO,
            cutoff_at=capture_cutoff,
            identity=FixtureIdentity("Home FC", "Away FC"),
            repository=repository,
        )

    with Session(engine) as session, session.begin():
        session.add(
            ProspectivePayloadIndexModel(
                id="payload-index-1",
                receipt_id=receipt_row_id,
                fixture_id=receipt.fixture_id,
                family=receipt.family.value,
                r2_key=receipt.r2_key,
                receipt_r2_key=receipt.receipt_r2_key,
                payload_sha256=receipt.payload_sha256,
                payload_bytes=receipt.payload_bytes,
                stored_bytes=receipt.stored_bytes,
                observed_at=receipt.observed_at,
                indexed_at=receipt.materialized_at + timedelta(seconds=1),
                code_revision="test-pit",
                append_only=True,
            )
        )
    evidence = _odds_evidence(
        engine,
        fixture_record_id="fixture-record-v1",
        fixture_id=receipt.fixture_id,
        market=PredictionMarket.ONE_X_TWO,
        cutoff_at=capture_cutoff,
        identity=FixtureIdentity("Home FC", "Away FC"),
        repository=repository,
    )
    assert evidence is not None
    assert evidence.receipt_id == receipt.receipt_hash
    assert evidence.source_receipt.robin_ingested_at == (
        receipt.materialized_at + timedelta(seconds=1)
    )
    verify_source_receipt_artifact(
        PrequentialArtifactRepository(store),
        evidence.source_receipt,
    )
    late_observed_at = observed_at + timedelta(seconds=10)
    late_context = CaptureContext(
        window_id="fixture:ODDS:H-2-LATE",
        window_label="H-2",
        fixture_id=receipt.fixture_id,
        competition=receipt.competition,
        season=receipt.season,
        provider=receipt.provider,
        family=CaptureFamily.ODDS,
        requested_at=late_observed_at - timedelta(seconds=2),
        response_received_at=late_observed_at - timedelta(seconds=1),
        observed_at=late_observed_at,
        cutoff_at=capture_cutoff,
        kickoff_at=KICKOFF,
        http_status=200,
        source_endpoint=receipt.source_endpoint,
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=1,
        code_revision="test-pit",
        materialized_at=capture_cutoff + timedelta(minutes=1),
    )
    late_record = {
        "bookmakers": [
            {
                "key": "LateBook",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "HOME", "price": 9.0},
                            {"name": "DRAW", "price": 9.0},
                            {"name": "AWAY", "price": 9.0},
                        ],
                    }
                ],
            }
        ]
    }
    late_capture = repository.capture(
        payload={
            "raw_payload_kind": "PROVIDER_RESPONSE_ENVELOPE",
            "raw_provider_payload": {"response": [late_record]},
            "normalized_family_records": [late_record],
        },
        context=late_context,
    )
    late_receipt = late_capture.receipt
    # Simulate a SQL projection that is appended only after the decision
    # cutoff.  The operational projector correctly refuses to produce this
    # late group, so the adversarial rows are built explicitly; the selector
    # must exclude them before trusting or reprojecting their contents.
    late_receipt_row_id = "receipt-row-late"
    late_projected_rows = tuple(
        {
            **row,
            "id": f"odds-row-late-{row['selection']}",
            "receipt_id": late_receipt_row_id,
            "bookmaker": "LateBook",
            "odds": 9.0,
            "observed_at": late_receipt.observed_at,
            "snapshot_hash": canonical_sha256(
                {"late": True, "selection": row["selection"]}
            ),
        }
        for row in projected_rows
    )
    with Session(engine) as session, session.begin():
        session.add(
            CaptureWindowModel(
                id="window-row-late",
                window_id=late_receipt.window_id,
                fixture_record_id="fixture-record-v1",
                fixture_id=late_receipt.fixture_id,
                family=CaptureFamily.ODDS.value,
                label="H-2",
                due_at=capture_cutoff - timedelta(minutes=5),
                opens_at=capture_cutoff - timedelta(hours=1),
                cutoff_at=capture_cutoff,
                kickoff_at=KICKOFF,
                scheduled_at=NOW,
                operational_tolerance_seconds=3600,
                status=AvailabilityStatus.COMPLETE.value,
                policy_version="test-pit-v1",
                code_revision="test-pit",
                append_only=True,
            )
        )
        session.flush()
        session.add(
            CaptureReceiptModel(
                id=late_receipt_row_id,
                receipt_hash=late_receipt.receipt_hash,
                window_id=late_receipt.window_id,
                window_record_id="window-row-late",
                fixture_id=late_receipt.fixture_id,
                competition=late_receipt.competition,
                season=late_receipt.season,
                provider=late_receipt.provider,
                family=late_receipt.family.value,
                window_label=late_receipt.window_label,
                requested_at=late_receipt.requested_at,
                response_received_at=late_receipt.response_received_at,
                observed_at=late_receipt.observed_at,
                event_time=late_receipt.event_time,
                provider_updated_at=late_receipt.provider_updated_at,
                cutoff_at=late_receipt.cutoff_at,
                kickoff_at=late_receipt.kickoff_at,
                materialized_at=late_receipt.materialized_at,
                seconds_before_kickoff=late_receipt.seconds_before_kickoff,
                http_status=late_receipt.http_status,
                payload_sha256=late_receipt.payload_sha256,
                payload_bytes=late_receipt.payload_bytes,
                stored_bytes=late_receipt.stored_bytes,
                r2_key=late_receipt.r2_key,
                receipt_r2_key=late_receipt.receipt_r2_key,
                source_endpoint=late_receipt.source_endpoint,
                complete=late_receipt.complete,
                quality_status=late_receipt.quality_status.value,
                provider_calls=late_receipt.provider_calls,
                code_revision=late_receipt.code_revision,
                append_only=True,
            )
        )
        session.flush()
        session.add(
            ProspectivePayloadIndexModel(
                id="payload-index-late",
                receipt_id=late_receipt_row_id,
                fixture_id=late_receipt.fixture_id,
                family=late_receipt.family.value,
                r2_key=late_receipt.r2_key,
                receipt_r2_key=late_receipt.receipt_r2_key,
                payload_sha256=late_receipt.payload_sha256,
                payload_bytes=late_receipt.payload_bytes,
                stored_bytes=late_receipt.stored_bytes,
                observed_at=late_receipt.observed_at,
                indexed_at=late_receipt.materialized_at,
                code_revision="test-pit",
                append_only=True,
            )
        )
        session.add_all(
            ProspectiveOddsSnapshotModel(**row)
            for row in late_projected_rows
        )
    after_late_materialization = _odds_evidence(
        engine,
        fixture_record_id="fixture-record-v1",
        fixture_id=receipt.fixture_id,
        market=PredictionMarket.ONE_X_TWO,
        cutoff_at=capture_cutoff,
        identity=FixtureIdentity("Home FC", "Away FC"),
        repository=repository,
    )
    assert after_late_materialization is not None
    assert after_late_materialization.snapshot_id == evidence.snapshot_id
    assert after_late_materialization.decimal_odds == evidence.decimal_odds
    artifact_repository = PrequentialArtifactRepository(store)
    closure_manifest = json.loads(
        artifact_repository.read_verified(
            evidence.source_receipt.storage_identity,
            evidence.source_receipt.payload_sha256,
        )
    )
    closure_manifest["payload"]["value"]["decimal_odds"]["HOME"] = 99.0
    forged_closure = artifact_repository.put_manifest(
        "source-observations",
        closure_manifest,
    )
    forged_receipt = SourceReceipt.create(
        source_name=evidence.source_receipt.source_name,
        request_identity=evidence.source_receipt.request_identity,
        payload_sha256=forged_closure.sha256,
        source_published_at=evidence.source_receipt.source_published_at,
        robin_first_observed_at=(
            evidence.source_receipt.robin_first_observed_at
        ),
        robin_ingested_at=evidence.source_receipt.robin_ingested_at,
        capture_code_revision=evidence.source_receipt.capture_code_revision,
        storage_identity=forged_closure.key,
        availability_status=evidence.source_receipt.availability_status,
        event_at=evidence.source_receipt.event_at,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SOURCE_RECEIPT_RAW_PROJECTION_MISMATCH",
    ):
        verify_source_receipt_artifact(
            artifact_repository,
            forged_receipt,
        )
    with pytest.raises(ValueError, match="PREQUENTIAL_ODDS_EVIDENCE_AMBIGUOUS"):
        _select_odds_evidence(
            (evidence, replace(evidence, snapshot_id="odds-ambiguous"))
        )
    odds_table = sa.Table(
        "prospective_odds_snapshots",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        trigger_names = tuple(
            connection.execute(
                sa.text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND tbl_name = :table_name"
                ),
                {"table_name": "prospective_odds_snapshots"},
            ).scalars()
        )
        for trigger_name in trigger_names:
            if "update" in trigger_name:
                connection.exec_driver_sql(f'DROP TRIGGER "{trigger_name}"')
        connection.execute(
            odds_table.update()
            .where(odds_table.c.selection == "HOME")
            .values(odds=9.0)
        )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_ODDS_RAW_PROJECTION_MISMATCH",
    ):
        _odds_evidence(
            engine,
            fixture_record_id="fixture-record-v1",
            fixture_id=receipt.fixture_id,
            market=PredictionMarket.ONE_X_TWO,
            cutoff_at=capture_cutoff,
            identity=FixtureIdentity("Home FC", "Away FC"),
            repository=repository,
        )


def test_mutable_identity_mapping_cannot_change_canonical_odds_outcome() -> None:
    first = FixtureIdentity("Home FC", "Away FC")
    mutated = FixtureIdentity("Away FC", "Home FC")
    for selection, expected in (
        ("HOME", "HOME"),
        ("DRAW", "DRAW"),
        ("AWAY", "AWAY"),
    ):
        assert _canonical_selection(
            market=PredictionMarket.ONE_X_TWO,
            selection=selection,
            identity=first,
        ) == _canonical_selection(
            market=PredictionMarket.ONE_X_TWO,
            selection=selection,
            identity=mutated,
        ) == expected
    assert (
        _canonical_selection(
            market=PredictionMarket.ONE_X_TWO,
            selection="Home FC",
            identity=first,
        )
        is None
    )
    assert (
        _canonical_selection(
            market=PredictionMarket.ONE_X_TWO,
            selection="X",
            identity=first,
        )
        is None
    )


def test_replay_artifacts_reject_training_manifest_and_challenger_tamper() -> None:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    snapshots: list[FeatureSnapshot] = []
    settlements: list[FixtureSettlementRecord] = []
    for index in range(30):
        suffix = f"{index:02d}"
        competition = "Ligue 1" if index < 15 else "Premier League"
        provider_fixture_id = f"provider-{suffix}"
        observation = _persist_result_observation(
            repository,
            fixture_id=f"fixture-{suffix}",
            fixture_record_id=f"fixture-record-{suffix}",
            provider_fixture_id=provider_fixture_id,
            attempt=1,
            observed_at=NOW - timedelta(hours=2),
            record={
                "fixture": {
                    "id": provider_fixture_id,
                    "status": {"short": "FT"},
                },
                "goals": {"home": 1, "away": 0},
            },
        )
        feature_values: dict[str, object] = {
            family: None for family in FEATURE_FAMILIES
        }
        feature_values["market"] = {
            "decimal_odds": {"HOME": 2.0, "DRAW": 3.4, "AWAY": 4.1},
            "bookmaker": "Book",
        }
        feature_values["team"] = {
            "home": "home",
            "away": "away",
            "competition": competition,
            "kickoff_at": (NOW - timedelta(hours=2)).isoformat(),
            "provider": "api-football",
            "provider_fixture_id": provider_fixture_id,
        }
        feature_missingness = {
            family: family not in {"market", "team"}
            for family in FEATURE_FAMILIES
        }
        feature_provenance: dict[str, dict[str, object]] = {}
        for family in ("market", "team"):
            source_receipt = persist_source_receipt(
                repository,
                source_name="TEST",
                request_identity=f"fixture-{suffix}:{family}",
                payload={
                    "fixture_id": f"fixture-{suffix}",
                    "fixture_record_id": f"fixture-record-{suffix}",
                    "family": family,
                    "value": feature_values[family],
                },
                observed_at=NOW - timedelta(hours=5),
                ingested_at=NOW - timedelta(hours=5),
                code_revision="test-pit",
            )
            feature_provenance[family] = {
                **source_receipt.as_dict(),
                "source_identity": source_receipt.storage_identity,
            }
        snapshots.append(
            FeatureSnapshot(
                snapshot_id=f"feature-{suffix}",
                fixture_record_id=f"fixture-record-{suffix}",
                fixture_id=f"fixture-{suffix}",
                competition=competition,
                market=PredictionMarket.ONE_X_TWO,
                cutoff_name=CutoffName.H_2,
                cutoff_at=NOW - timedelta(hours=4),
                created_at=NOW - timedelta(hours=5),
                feature_contract_version="test-v1",
                feature_contract_hash="a" * 64,
                values=feature_values,
                missingness=feature_missingness,
                provenance=feature_provenance,
                quality={},
                code_revision="test-pit",
                r2_manifest_key=(
                    "prequential-learning/feature-snapshots/"
                    f"feature-{suffix}.json"
                ),
            )
        )
        settlements.append(
            FixtureSettlementRecord(
                settlement_id=f"settlement-{suffix}",
                result=VerifiedFixtureResult(
                    fixture_record_id=f"fixture-record-{suffix}",
                    fixture_id=f"fixture-{suffix}",
                    competition=competition,
                    kickoff_at=NOW - timedelta(days=1),
                    status=FixtureResultStatus.FINISHED,
                    verified_at=NOW - timedelta(hours=2),
                    home_goals=1,
                    away_goals=0,
                    result_version=1,
                    source_hash=observation.sha256,
                ),
                settled_at=NOW - timedelta(hours=1),
                effective_status=PredictionStatus.SETTLED,
            )
        )
    previous_model = ModelVersion(
        model_id="challenger-global_five_leagues",
        scope=ModelScope.GLOBAL_FIVE_LEAGUES,
        role=ModelRole.CHALLENGER,
        version="untrained-v1",
        artifact_sha256=canonical_sha256(
            {
                "family": "UNTRAINED_CHALLENGER",
                "scope": ModelScope.GLOBAL_FIVE_LEAGUES.value,
                "predictions": 0,
            }
        ),
        created_at=NOW - timedelta(days=2),
        feature_contract_hash="a" * 64,
        code_revision="test-pit",
        status=ModelStatus.INSUFFICIENT_TRAINING_SUPPORT,
    )
    training_examples = eligible_training_examples(
        settlements=settlements,
        snapshots=snapshots,
        training_cutoff=NOW,
    )
    manifest_id = training_manifest_record_id(
        previous_model_registry_hash=previous_model.registry_hash,
        training_cutoff=NOW,
        examples=training_examples,
    )
    training_metrics = {
        "fixtures": 30,
        "examples": 30,
        "represented_leagues": 2,
        "outcomes_by_market": {"1X2": {"HOME": 30}},
    }
    fixture_ids = [snapshot.fixture_id for snapshot in snapshots]
    settlement_ids = [settlement.settlement_id for settlement in settlements]
    competitions = ["Ligue 1", "Premier League"]
    feature_snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
    hyperparameters = {
        "family": "EMPIRICAL_REGULARIZED_CHALLENGER_V1",
        "smoothing": 1.0,
    }
    manifest_body = {
        "schema_version": "prequential-training-dataset-v1",
        "manifest_id": manifest_id,
        "created_at": NOW.isoformat(),
        "training_cutoff": NOW.isoformat(),
        "fixture_ids": fixture_ids,
        "settlement_ids": settlement_ids,
        "competitions": competitions,
        "feature_snapshot_ids": feature_snapshot_ids,
        "feature_contract_hash": "a" * 64,
        "hyperparameters": hyperparameters,
        "training_metrics": training_metrics,
        "code_revision": "test-pit",
    }
    stored_manifest = repository.put_manifest(
        "training-manifests",
        manifest_body,
    )
    manifest = TrainingDatasetManifest(
        manifest_id=manifest_id,
        created_at=NOW,
        training_cutoff=NOW,
        fixture_ids=tuple(fixture_ids),
        settlement_ids=tuple(settlement_ids),
        competitions=tuple(competitions),
        feature_snapshot_ids=tuple(feature_snapshot_ids),
        feature_contract_hash="a" * 64,
        hyperparameters=hyperparameters,
        code_revision="test-pit",
        r2_key=stored_manifest.key,
        training_metrics=training_metrics,
    )
    challenger_body = {
        "schema_version": "prequential-challenger-artifact-v1",
        "training_manifest_hash": manifest.manifest_hash,
        "training_cutoff": NOW.isoformat(),
        "counts_by_market": {"1X2": {"HOME": 30}},
        "support_fixtures": 30,
        "support_examples": 30,
        "competitions": competitions,
        "promotion_status": "PROMOTION_LOCKED",
    }
    stored_challenger = repository.put_artifact(
        "challenger-models",
        canonical_json_bytes(challenger_body),
    )
    next_version = challenger_model_version(
        training_cutoff=NOW,
        artifact_sha256=stored_challenger.sha256,
    )
    training_run_id = _training_run_id(
        model_id="challenger-global_five_leagues",
        previous_version="untrained-v1",
        training_cutoff=NOW,
        status="CHALLENGER_VERSION_CREATED",
        manifest_hash=manifest.manifest_hash,
        code_revision="test-pit",
    )
    training_row: dict[str, object] = {
        "id": training_run_id,
        "training_run_id": training_run_id,
        "model_id": "challenger-global_five_leagues",
        "previous_model_version": "untrained-v1",
        "next_model_version": next_version,
        "status": "CHALLENGER_VERSION_CREATED",
        "started_at": NOW.isoformat(),
        "training_cutoff": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "eligible_fixtures": 30,
        "represented_leagues": 2,
        "dataset_manifest_hash": manifest.manifest_hash,
        "dataset_manifest_r2_key": stored_manifest.key,
        "artifact_sha256": stored_challenger.sha256,
        "artifact_r2_key": stored_challenger.key,
        "fixture_ids": fixture_ids,
        "settlement_ids": settlement_ids,
        "competitions": competitions,
        "feature_snapshot_ids": feature_snapshot_ids,
        "hyperparameters": hyperparameters,
        "training_metrics": training_metrics,
        "code_revision": "test-pit",
        "promotion_status": "PROMOTION_LOCKED",
    }
    previous_model_id = f"model-{previous_model.registry_hash}"
    next_model = ModelVersion(
        model_id="challenger-global_five_leagues",
        scope=ModelScope.GLOBAL_FIVE_LEAGUES,
        role=ModelRole.CHALLENGER,
        version=next_version,
        artifact_sha256=stored_challenger.sha256,
        artifact_r2_key=stored_challenger.key,
        created_at=NOW,
        training_cutoff=NOW,
        feature_contract_hash="a" * 64,
        code_revision="test-pit",
        status=ModelStatus.ACTIVE,
        parent_version="untrained-v1",
    )
    model_row: dict[str, object] = {
        "id": f"model-{next_model.registry_hash}",
        "model_id": "challenger-global_five_leagues",
        "model_version": next_version,
        "scope": ModelScope.GLOBAL_FIVE_LEAGUES.value,
        "role": ModelRole.CHALLENGER.value,
        "artifact_sha256": stored_challenger.sha256,
        "artifact_r2_key": stored_challenger.key,
        "created_at": NOW.isoformat(),
        "training_cutoff": NOW.isoformat(),
        "feature_contract_hash": "a" * 64,
        "code_revision": "test-pit",
        "status": ModelStatus.ACTIVE.value,
        "parent_version_id": previous_model_id,
        "registry_hash": next_model.registry_hash,
    }
    previous_model_row: dict[str, object] = {
        "id": previous_model_id,
        "model_id": "challenger-global_five_leagues",
        "model_version": "untrained-v1",
        "scope": ModelScope.GLOBAL_FIVE_LEAGUES.value,
        "role": ModelRole.CHALLENGER.value,
        "artifact_sha256": previous_model.artifact_sha256,
        "artifact_r2_key": None,
        "created_at": (NOW - timedelta(days=2)).isoformat(),
        "training_cutoff": None,
        "feature_contract_hash": "a" * 64,
        "code_revision": "test-pit",
        "status": ModelStatus.INSUFFICIENT_TRAINING_SUPPORT.value,
        "parent_version_id": None,
        "registry_hash": previous_model.registry_hash,
    }
    settlement_rows = [
        {
            "settlement_id": settlement.settlement_id,
            "fixture_record_id": settlement.result.fixture_record_id,
            "fixture_id": settlement.result.fixture_id,
            "competition": settlement.result.competition,
            "kickoff_at": settlement.result.kickoff_at.isoformat(),
            "result_status": settlement.result.status.value,
            "effective_status": settlement.effective_status.value,
            "verified_at": settlement.result.verified_at.isoformat(),
            "settled_at": settlement.settled_at.isoformat(),
            "home_goals": settlement.result.home_goals,
            "away_goals": settlement.result.away_goals,
            "result_version": settlement.result.result_version,
            "source_hash": settlement.result.source_hash,
            "supersedes_id": settlement.supersedes_id,
        }
        for settlement in settlements
    ]
    snapshot_rows = [
        {
            **snapshot.as_manifest(),
            "snapshot_hash": snapshot.snapshot_hash,
        }
        for snapshot in snapshots
    ]
    ledger_rows = [
        {
            "kind": "CHALLENGER_TRAINING_STARTED",
            "model_id": "challenger-global_five_leagues",
            "model_version": "untrained-v1",
            "recorded_at": NOW.isoformat(),
            "evidence_hashes": [manifest.manifest_hash],
        },
        {
            "kind": "CHALLENGER_VERSION_CREATED",
            "model_id": "challenger-global_five_leagues",
            "model_version": next_version,
            "recorded_at": NOW.isoformat(),
            "evidence_hashes": [
                manifest.manifest_hash,
                next_model.registry_hash,
            ],
        },
        {
            "kind": "PROMOTION_BLOCKED",
            "model_id": "challenger-global_five_leagues",
            "model_version": next_version,
            "recorded_at": NOW.isoformat(),
            "evidence_hashes": [next_model.registry_hash],
        },
    ]
    rows = {
        "prequential_training_runs": [training_row],
        "prequential_model_versions": [previous_model_row, model_row],
        "prequential_fixture_settlements": settlement_rows,
        "prequential_feature_snapshots": snapshot_rows,
        "prequential_ledger_events": ledger_rows,
    }
    _verify_replay_artifacts(artifacts=repository, rows=rows)

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_TRAINING_HEAD_AMBIGUOUS",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_training_runs": [training_row, dict(training_row)],
            },
        )

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_ACTIVE_CHALLENGER_TRAINING_EDGE_MISSING",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={**rows, "prequential_training_runs": []},
        )

    forked_model_row = {
        **model_row,
        "id": "model-forked-active-challenger",
        "model_version": "v-forked-active-challenger",
        "created_at": (NOW + timedelta(days=1)).isoformat(),
        "training_cutoff": (NOW + timedelta(days=1)).isoformat(),
        "registry_hash": "e" * 64,
    }
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_CHALLENGER_MODEL_CHAIN_FORK",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_model_versions": [
                    previous_model_row,
                    model_row,
                    forked_model_row,
                ],
            },
        )

    forged_result_row = {
        **settlement_rows[0],
        "home_goals": 0,
        "away_goals": 4,
    }
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_RESULT_OBSERVATION_PROJECTION_MISMATCH",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_fixture_settlements": [
                    forged_result_row,
                    *settlement_rows[1:],
                ],
            },
        )

    missing_result_artifact = {
        **settlement_rows[0],
        "source_hash": "e" * 64,
    }
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_RESULT_OBSERVATION_BYTES_INVALID",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_fixture_settlements": [
                    missing_result_artifact,
                    *settlement_rows[1:],
                ],
            },
        )

    noncanonical_result_chain = {
        **settlement_rows[0],
        "result_version": 2,
    }
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SETTLEMENT_RESTORE_CHAIN_INVALID",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_fixture_settlements": [
                    noncanonical_result_chain,
                    *settlement_rows[1:],
                ],
            },
        )

    future_parent_row = {
        **previous_model_row,
        "created_at": (NOW + timedelta(seconds=1)).isoformat(),
    }
    with pytest.raises(
        ValueError,
        match=(
            "PREQUENTIAL_REPLAY_(PARENT_MODEL_AFTER_TRAINING_CUTOFF|"
            "CHALLENGER_CHAIN_TIME_INVALID)"
        ),
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_model_versions": [future_parent_row, model_row],
            },
        )

    tampered_manifest_row = {**training_row, "dataset_manifest_hash": "f" * 64}
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_TRAINING_MANIFEST_HASH_INVALID",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_training_runs": [tampered_manifest_row],
            },
        )

    tampered_artifact_row = {**training_row, "artifact_sha256": "e" * 64}
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_BYTES_INVALID",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={
                **rows,
                "prequential_training_runs": [tampered_artifact_row],
            },
        )


def test_void_result_has_first_version_without_unbound_local() -> None:
    fixture = _fixture(
        record_id="fixture-record-void",
        registered_at=NOW - timedelta(days=1),
        registry_hash="c" * 64,
    )
    result = _verified_result_from_record(
        fixture=fixture,
        record={"fixture": {"id": 42, "status": {"short": "CANC"}}},
        verified_at=NOW,
        source_hash="d" * 64,
    )
    assert result is not None
    assert result.status is FixtureResultStatus.CANCELLED
    assert result.result_version == 1


def test_replay_rejects_tampered_deferred_training_decision() -> None:
    repository = PrequentialArtifactRepository(InMemoryObjectStore())
    previous = ModelVersion(
        model_id="challenger-global_five_leagues",
        scope=ModelScope.GLOBAL_FIVE_LEAGUES,
        role=ModelRole.CHALLENGER,
        version="untrained-v1",
        artifact_sha256=canonical_sha256(
            {
                "family": "UNTRAINED_CHALLENGER",
                "scope": ModelScope.GLOBAL_FIVE_LEAGUES.value,
                "predictions": 0,
            }
        ),
        created_at=NOW - timedelta(days=2),
        feature_contract_hash="a" * 64,
        code_revision="test-pit",
        status=ModelStatus.INSUFFICIENT_TRAINING_SUPPORT,
    )
    model_row = {
        "id": f"model-{previous.registry_hash}",
        "model_id": previous.model_id,
        "model_version": previous.version,
        "scope": previous.scope.value,
        "role": previous.role.value,
        "artifact_sha256": previous.artifact_sha256,
        "artifact_r2_key": None,
        "created_at": previous.created_at.isoformat(),
        "training_cutoff": None,
        "feature_contract_hash": previous.feature_contract_hash,
        "code_revision": previous.code_revision,
        "status": previous.status.value,
        "parent_version_id": None,
        "registry_hash": previous.registry_hash,
    }
    status = "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT"
    reason = "MINIMUM_30_FIXTURES_AND_2_LEAGUES_REQUIRED"
    run_id = _training_run_id(
        model_id=previous.model_id,
        previous_version=previous.version,
        training_cutoff=NOW,
        status=status,
        manifest_hash=None,
        code_revision="test-pit",
    )
    evidence_hash = canonical_sha256(
        {
            "status": status,
            "eligible": 0,
            "leagues": 0,
            "reason": reason,
            "model_id": previous.model_id,
            "previous_version": previous.version,
            "training_cutoff": NOW.isoformat(),
            "code_revision": "test-pit",
        }
    )
    training_row: dict[str, object] = {
        "id": run_id,
        "training_run_id": run_id,
        "model_id": previous.model_id,
        "previous_model_version": previous.version,
        "next_model_version": None,
        "status": status,
        "started_at": NOW.isoformat(),
        "training_cutoff": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "eligible_fixtures": 0,
        "represented_leagues": 0,
        "dataset_manifest_hash": None,
        "dataset_manifest_r2_key": None,
        "artifact_sha256": None,
        "artifact_r2_key": None,
        "fixture_ids": [],
        "settlement_ids": [],
        "competitions": [],
        "feature_snapshot_ids": [],
        "hyperparameters": {},
        "training_metrics": {},
        "code_revision": "test-pit",
        "promotion_status": "PROMOTION_LOCKED",
    }
    ledger_event = {
        "kind": "TRAINING_DEFERRED",
        "model_id": previous.model_id,
        "model_version": previous.version,
        "recorded_at": NOW.isoformat(),
        "evidence_hashes": [evidence_hash],
        "details": {"status": status},
    }
    rows = {
        "prequential_training_runs": [training_row],
        "prequential_model_versions": [model_row],
        "prequential_feature_snapshots": [],
        "prequential_fixture_settlements": [],
        "prequential_ledger_events": [ledger_event],
    }
    _verify_replay_artifacts(artifacts=repository, rows=rows)

    tampered = dict(training_row)
    tampered["eligible_fixtures"] = 999
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_DEFERRED_TRAINING_DECISION_MISMATCH",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={**rows, "prequential_training_runs": [tampered]},
        )

    forged_id = dict(training_row)
    forged_id["id"] = forged_id["training_run_id"] = "training-forged"
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_TRAINING_RUN_ID_MISMATCH",
    ):
        _verify_replay_artifacts(
            artifacts=repository,
            rows={**rows, "prequential_training_runs": [forged_id]},
        )
