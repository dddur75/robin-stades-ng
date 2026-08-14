from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from robin.backtesting.v3 import StrategyParameters, run_backtest
from robin.historical.features import build_team_feature_rows
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    FeatureSnapshotRegistry,
    freeze_feature_snapshot,
    persist_source_receipt,
    verify_source_receipt_artifact,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    ModelRole,
    ModelScope,
    PredictionMarket,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_factory import (
    PrequentialLearningFactory,
    initial_model_versions,
)
from robin.prospective_observatory.prequential_storage import (
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
)
from robin.shadow.decision import decide_shadow_bet
from robin.storage.database import build_engine
from robin.storage.models import Base
from robin.storage.prospective_models import ProspectiveFixtureModel
from robin.temporal.lineage import (
    SourceReceipt,
    TemporalDecisionLineage,
    TemporalFeatureLineage,
    TemporalProofLevel,
    asof_select,
)
from scripts.run_prequential_learning_factory import _latest_fixtures

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)
CONTRACT = {
    "version": "prequential-features-v1",
    "missing_value_policy": "NULL_WITH_RECEIPT_PROVENANCE",
}
_ISSUED_TEST_RECEIPTS: dict[str, SourceReceipt] = {}
_DEFAULT_RECEIPT_PAYLOAD = object()


def _receipt_provenance(
    repository: PrequentialArtifactRepository,
    *,
    observed_at: datetime,
    marker: str,
    value: object,
    fixture_id: str,
    fixture_record_id: str,
) -> dict[str, object]:
    receipt = persist_source_receipt(
        repository,
        source_name="TEST_CAPTURE",
        request_identity=f"test-request:{marker}",
        payload={
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "family": marker,
            "value": value,
        },
        observed_at=observed_at,
        ingested_at=observed_at,
        code_revision="test",
    )
    return {
        **receipt.as_dict(),
        "source": receipt.source_name,
        "source_identity": receipt.storage_identity,
        "observed_at": receipt.robin_first_observed_at.isoformat(),
    }


def _feature_values() -> tuple[dict[str, object], dict[str, bool]]:
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        "bookmaker": "TEST",
    }
    values["team"] = {
        "home": "home",
        "away": "away",
        "competition": "Ligue 1",
        "kickoff_at": (NOW + timedelta(hours=2)).isoformat(),
        "provider": "api-football",
        "provider_fixture_id": "test-provider-fixture",
    }
    availability["market"] = True
    availability["team"] = True
    return values, availability


def test_late_arriving_pre_cutoff_event_is_excluded_when_observed_after_cutoff() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    old = ProspectiveFixtureModel(
        id="fixture-record-before-cutoff",
        idempotency_key="fixture:before",
        fixture_id="api-football:42",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home-v1",
        away_team_id="away-v1",
        kickoff_at=NOW + timedelta(hours=2),
        provider="api-football",
        provider_fixture_id="42",
        registered_at=NOW - timedelta(hours=1),
        registry_hash="a" * 64,
        code_revision="test",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )
    late_revision = ProspectiveFixtureModel(
        id="fixture-record-after-cutoff",
        idempotency_key="fixture:after",
        fixture_id="api-football:42",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home-v2-future-mutation",
        away_team_id="away-v2-future-mutation",
        kickoff_at=NOW + timedelta(hours=5),
        provider="api-football",
        provider_fixture_id="42",
        registered_at=NOW + timedelta(seconds=1),
        registry_hash="b" * 64,
        code_revision="test",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )
    with Session(engine) as session, session.begin():
        session.add_all((old, late_revision))

    selected = _latest_fixtures(engine, as_of=NOW)
    assert tuple(row.id for row in selected) == ("fixture-record-before-cutoff",)
    assert selected[0].home_team_id == "home-v1"


def test_future_value_mutation_does_not_change_past_feature_snapshot() -> None:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    registry = FeatureSnapshotRegistry()
    values, availability = _feature_values()
    observed_at = NOW - timedelta(minutes=10)
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=registry,
        fixture_record_id="fixture-record-1",
        fixture_id="fixture-1",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=NOW,
        created_at=observed_at,
        feature_contract_version="prequential-features-v1",
        feature_contract=CONTRACT,
        values=values,
        availability=availability,
        provenance={
            family: _receipt_provenance(
                repository,
                observed_at=observed_at,
                marker=family,
                value=values[family],
                fixture_id="fixture-1",
                fixture_record_id="fixture-record-1",
            )
            for family in ("market", "team")
        },
        quality={"status": "TEST_ONLY"},
        code_revision="test",
    )
    frozen_hash = snapshot.snapshot_hash
    market = values["market"]
    assert isinstance(market, dict)
    decimal_odds = market["decimal_odds"]
    assert isinstance(decimal_odds, dict)
    decimal_odds["HOME"] = 99.0

    assert snapshot.snapshot_hash == frozen_hash
    assert snapshot.values["market"]["decimal_odds"]["HOME"] == 2.2  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.values["market"]["decimal_odds"]["HOME"] = 98.0  # type: ignore[index]


def test_future_value_mutation_does_not_change_past_decision_hash() -> None:
    from robin.temporal.lineage import asof_select

    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    historical_odds = {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4}
    future_odds = {"HOME": 1.2, "DRAW": 9.0, "AWAY": 12.0}

    def stored_row(
        *,
        marker: str,
        observed_at: datetime,
        odds: dict[str, float],
    ) -> dict[str, object]:
        receipt = persist_source_receipt(
            repository,
            source_name="TEST_DECISION_ODDS",
            request_identity=f"decision:{marker}",
            payload={"entity": "fixture-1:1X2", "odds": odds},
            observed_at=observed_at,
            ingested_at=observed_at,
            code_revision="test",
        )
        return {
            "entity": "fixture-1:1X2",
            **receipt.as_dict(),
            "payload_hash": receipt.payload_sha256,
            "odds": odds,
        }

    historical = stored_row(
        marker="historical",
        observed_at=NOW - timedelta(minutes=10),
        odds=historical_odds,
    )
    future = stored_row(
        marker="future",
        observed_at=NOW + timedelta(minutes=10),
        odds=future_odds,
    )

    def selected(rows: list[dict[str, object]]) -> dict[str, object]:
        value = asof_select(
            rows,
            entity_key="entity",
            available_at_key="available_at",
            payload_hash_key="payload_hash",
            cutoff_at=NOW,
            expected_entity="fixture-1:1X2",
            receipt_verifier=lambda receipt: verify_source_receipt_artifact(
                repository,
                receipt,
            ),
            projection_verifier=lambda receipt, row: (
                verify_source_receipt_artifact(
                    repository,
                    receipt,
                    expected_payload={
                        "entity": row["entity"],
                        "odds": row["odds"],
                    },
                )
            ),
        )
        assert isinstance(value, dict)
        return value

    baseline = selected([historical, future])
    mutated_future = dict(future)
    mutated_future["odds"] = {"HOME": 25.0, "DRAW": 1.1, "AWAY": 30.0}
    after = selected([mutated_future, historical])
    assert baseline == after == historical
    corrupt_future_receipt = dict(future)
    corrupt_future_receipt["receipt_id"] = "0" * 64
    assert selected([corrupt_future_receipt, historical]) == historical
    forged_historical = dict(historical)
    forged_historical["odds"] = {"HOME": 9.0, "DRAW": 9.0, "AWAY": 9.0}
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SOURCE_RECEIPT_PROJECTION_MISMATCH",
    ):
        selected([forged_historical])

    def decide(row: dict[str, object]) -> str:
        odds = row["odds"]
        assert isinstance(odds, dict)
        decision = decide_shadow_bet(
            fixture_id="fixture-1",
            market_key="1X2",
            selection="HOME",
            market_odds=odds,
            model_probability=0.6,
            devig_method="PROPORTIONAL",
            strategy_version="temporal-test-v1",
            quality_ok=True,
            cutoff_at=NOW,
            feature_lineage_hash="5" * 64,
            odds_receipt_id=str(row["receipt_id"]),
            odds_available_at=datetime.fromisoformat(str(row["available_at"])),
            model_registry_hash="6" * 64,
            model_available_at=NOW - timedelta(days=1),
            temporal_contract_version="robin-point-in-time-lineage-v1",
            point_in_time_status="POINT_IN_TIME_VALID",
            decided_at=NOW,
        )
        return decision.decision_input_hash

    assert decide(baseline) == decide(after)


def test_append_change_delete_and_reorder_future_rows_leave_past_team_features_exact() -> None:
    past = {
        "match_id": "past",
        "date": "2026-01-01T12:00:00Z",
        "season": 2026,
        "home": "A",
        "away": "B",
        "fthg": 1,
        "ftag": 0,
    }
    target = {
        "match_id": "target",
        "date": "2026-01-02T12:00:00Z",
        "season": 2026,
        "home": "A",
        "away": "C",
        "fthg": 0,
        "ftag": 0,
    }
    future = {
        "match_id": "future",
        "date": "2026-01-03T12:00:00Z",
        "season": 2026,
        "home": "A",
        "away": "D",
        "fthg": 9,
        "ftag": 0,
    }

    def past_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            row
            for row in build_team_feature_rows(rows)
            if row["fixture_id"] in {"past", "target"}
        ]

    baseline = past_rows([past, target, future])
    changed = {**future, "fthg": 0, "ftag": 12, "home": "C"}
    assert past_rows([changed, target, past]) == baseline
    assert past_rows([target, past]) == baseline
    appended = {
        **future,
        "match_id": "future-2",
        "date": "2026-01-04T12:00:00+00:00",
        "fthg": 50,
    }
    assert past_rows([appended, future, past, target]) == baseline


def test_current_fixture_result_is_not_in_peer_rolling_window() -> None:
    seed = {
        "match_id": "seed",
        "date": "2025-12-01T12:00:00Z",
        "season": 2025,
        "home": "A",
        "away": "B",
        "fthg": 1,
        "ftag": 0,
    }
    first = {
        "match_id": "same-1",
        "date": "2026-01-01T12:00:00Z",
        "season": 2026,
        "home": "A",
        "away": "C",
        "fthg": 10,
        "ftag": 0,
    }
    second = {
        "match_id": "same-2",
        "date": "2026-01-01T14:00:00+02:00",
        "season": 2026,
        "home": "A",
        "away": "D",
        "fthg": 0,
        "ftag": 10,
    }
    rows = {
        str(row["fixture_id"]): row
        for row in build_team_feature_rows([second, seed, first])
    }
    assert rows["same-1"]["home_form_5"] == rows["same-2"]["home_form_5"]
    assert rows["same-1"]["home_goals_for_5"] == rows["same-2"]["home_goals_for_5"]


def test_late_retroactive_correction_and_newer_provider_version_are_excluded() -> None:
    original = _asof_row(
        entity="fixture-1",
        receipt=_source_receipt(
            observed_at=NOW - timedelta(minutes=1),
            marker="original",
            payload_value={"score": 1, "ranking": 5},
        ),
        value={"score": 1, "ranking": 5},
    )
    late_correction = _asof_row(
        entity="fixture-1",
        receipt=_source_receipt(
            observed_at=NOW + timedelta(microseconds=1),
            marker="late-correction",
            payload_value={"score": 9, "ranking": 1},
        ),
        value={"score": 9, "ranking": 1},
    )
    for rows in ([original, late_correction], [late_correction, original]):
        assert asof_select(
            rows,
            entity_key="entity",
            available_at_key="available_at",
            payload_hash_key="payload_hash",
            cutoff_at=NOW,
            expected_entity="fixture-1",
            receipt_verifier=_verify_test_receipt,
            projection_verifier=_verify_test_projection,
        ) == original


def test_duplicate_and_repeated_payload_receipts_are_order_invariant() -> None:
    rows = sorted(
        (
            _asof_row(
                entity="fixture-1",
                receipt=_source_receipt(
                    observed_at=NOW,
                    marker=marker,
                    payload_marker="same-payload",
                    payload_value={"odds": [2.0, 3.5, 4.0]},
                ),
                value={"odds": [2.0, 3.5, 4.0]},
            )
            for marker in ("duplicate-a", "duplicate-b")
        ),
        key=lambda row: str(row["receipt_id"]),
    )
    first, duplicate = rows
    selected_forward = asof_select(
        [first, duplicate],
        entity_key="entity",
        available_at_key="available_at",
        payload_hash_key="payload_hash",
        cutoff_at=NOW,
        expected_entity="fixture-1",
        receipt_verifier=_verify_test_receipt,
        projection_verifier=_verify_test_projection,
    )
    selected_reverse = asof_select(
        [duplicate, first],
        entity_key="entity",
        available_at_key="available_at",
        payload_hash_key="payload_hash",
        cutoff_at=NOW,
        expected_entity="fixture-1",
        receipt_verifier=_verify_test_receipt,
        projection_verifier=_verify_test_projection,
    )
    assert selected_forward == selected_reverse == first


def test_provider_publication_order_and_clock_skew_are_conservative() -> None:
    published_before = _source_receipt(
        observed_at=NOW,
        published_at=NOW - timedelta(minutes=5),
        marker="published-before",
    )
    assert published_before.available_at == NOW
    published_after = _source_receipt(
        observed_at=NOW - timedelta(minutes=5),
        published_at=NOW + timedelta(microseconds=1),
        marker="published-after",
    )
    assert published_after.available_at > NOW
    with pytest.raises(ValueError, match="TEMPORAL_FEATURE_INPUT_AFTER_CUTOFF"):
        TemporalFeatureLineage(
            feature_name="clock-skewed-provider-value",
            feature_contract_version="v1",
            input_receipts=(published_after,),
            cutoff_at=NOW,
            computed_at=NOW,
            code_revision="test",
        )
    with pytest.raises(ValueError, match="INGESTION_BEFORE_OBSERVATION"):
        SourceReceipt.create(
            source_name="TEST_SOURCE",
            request_identity="request:bad-clock",
            payload_sha256="b" * 64,
            source_published_at=None,
            robin_first_observed_at=NOW,
            robin_ingested_at=NOW - timedelta(microseconds=1),
            capture_code_revision="test",
            storage_identity="memory://bad-clock",
            availability_status=TemporalProofLevel.RECEIPT_ATTESTED,
        )


def test_finished_result_verified_before_kickoff_is_rejected() -> None:
    with pytest.raises(ValueError, match="FINAL_RESULT_VERIFIED_BEFORE_KICKOFF"):
        VerifiedFixtureResult(
            fixture_record_id="record-1",
            fixture_id="fixture-1",
            competition="Ligue 1",
            kickoff_at=NOW,
            status=FixtureResultStatus.FINISHED,
            verified_at=NOW - timedelta(microseconds=1),
            home_goals=1,
            away_goals=0,
            source_hash="a" * 64,
        )


def test_lineup_received_after_cutoff_is_rejected() -> None:
    lineup = _source_receipt(
        observed_at=NOW + timedelta(microseconds=1),
        event_at=NOW - timedelta(hours=1),
        marker="late-lineup",
    )
    with pytest.raises(ValueError, match="TEMPORAL_FEATURE_INPUT_AFTER_CUTOFF"):
        TemporalFeatureLineage(
            feature_name="confirmed-lineup",
            feature_contract_version="v1",
            input_receipts=(lineup,),
            cutoff_at=NOW,
            computed_at=NOW,
            code_revision="test",
        )


def test_calibration_artifact_created_after_cutoff_is_rejected_with_model_bundle() -> None:
    # The covered prequential path has no independently executed calibrator:
    # model_registry_hash identifies the complete model/calibration bundle.
    with pytest.raises(ValueError, match="POINT_IN_TIME_DECISION_INPUT_AFTER_CUTOFF"):
        TemporalDecisionLineage(
            cutoff_at=NOW,
            predicted_at=NOW,
            decided_at=NOW,
            feature_lineage_hash="1" * 64,
            odds_receipt_id="2" * 64,
            odds_available_at=NOW,
            model_registry_hash="3" * 64,
            model_available_at=NOW + timedelta(microseconds=1),
        )


def test_structural_decision_lineage_cannot_claim_point_in_time_valid() -> None:
    with pytest.raises(ValueError, match="POINT_IN_TIME_STATUS_OVERCLAIMED"):
        TemporalDecisionLineage(
            cutoff_at=NOW,
            predicted_at=NOW,
            decided_at=NOW,
            feature_lineage_hash="1" * 64,
            odds_receipt_id="2" * 64,
            odds_available_at=NOW,
            model_registry_hash="3" * 64,
            model_available_at=NOW,
            point_in_time_status="POINT_IN_TIME_VALID",
        )


def test_missing_availability_receipt_fails_closed() -> None:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    values, availability = _feature_values()
    observed_at = NOW - timedelta(minutes=10)
    with pytest.raises(
        ValueError,
        match="FEATURE_PROVENANCE_SOURCE_RECEIPT_REQUIRED",
    ):
        freeze_feature_snapshot(
            repository=repository,
            registry=FeatureSnapshotRegistry(),
            fixture_record_id="fixture-record-1",
            fixture_id="fixture-1",
            competition="Ligue 1",
            market=PredictionMarket.ONE_X_TWO,
            cutoff_name=CutoffName.H_2,
            cutoff_at=NOW,
            created_at=observed_at,
            feature_contract_version="prequential-features-v1",
            feature_contract=CONTRACT,
            values=values,
            availability=availability,
            provenance={
                family: {
                    "source": "SELF_DECLARED_WITHOUT_RECEIPT",
                    "observed_at": observed_at.isoformat(),
                }
                for family in ("market", "team")
            },
            quality={"status": "TEST_ONLY"},
            code_revision="test",
        )


def test_model_created_after_cutoff_is_rejected() -> None:
    models = initial_model_versions(
        created_at=NOW + timedelta(seconds=1),
        feature_contract_hash=canonical_sha256(CONTRACT),
        code_revision="future-model",
    )
    factory = PrequentialLearningFactory(
        artifact_repository=PrequentialArtifactRepository(
            InMemoryArtifactStore()
        ),
        models=models,
        devig_method="PROPORTIONAL",
    )
    reference = next(
        model
        for model in models
        if model.role is ModelRole.REFERENCE
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    with pytest.raises(ValueError, match="MODEL_NOT_AVAILABLE_AT_CUTOFF"):
        factory.forecast(
            fixture_record_id="fixture-record-1",
            fixture_id="fixture-1",
            competition="Ligue 1",
            market=PredictionMarket.ONE_X_TWO,
            cutoff_name=CutoffName.H_2,
            cutoff_at=NOW,
            kickoff_at=NOW + timedelta(hours=2),
            predicted_at=NOW - timedelta(minutes=5),
            model_id=reference.model_id,
            model_version=reference.version,
            feature_snapshot_id="feature-existing",
            gate_statuses={"fixture": True},
            required_gates=("fixture",),
            decimal_odds={"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
            odds_snapshot_id="odds-existing",
            challenger_probabilities=None,
            code_revision="test",
        )


def _source_receipt(
    *,
    observed_at: datetime,
    published_at: datetime | None = None,
    event_at: datetime | None = None,
    marker: str = "receipt",
    payload_marker: str | None = None,
    ingested_at: datetime | None = None,
    payload_value: object = _DEFAULT_RECEIPT_PAYLOAD,
) -> SourceReceipt:
    payload = (
        {"payload": payload_marker or marker}
        if payload_value is _DEFAULT_RECEIPT_PAYLOAD
        else {"value": payload_value}
    )
    receipt = SourceReceipt.create(
        source_name="TEST_SOURCE",
        request_identity=f"request:{marker}",
        payload_sha256=canonical_sha256(payload),
        source_published_at=published_at,
        robin_first_observed_at=observed_at,
        robin_ingested_at=ingested_at or observed_at,
        capture_code_revision="test-revision",
        storage_identity=f"memory://{marker}",
        availability_status=(
            TemporalProofLevel.SOURCE_AND_RECEIPT_ATTESTED
            if published_at is not None
            else TemporalProofLevel.RECEIPT_ATTESTED
        ),
        event_at=event_at,
    )
    _ISSUED_TEST_RECEIPTS[receipt.receipt_id] = receipt
    return receipt


def _verify_test_receipt(receipt: SourceReceipt) -> None:
    if _ISSUED_TEST_RECEIPTS.get(receipt.receipt_id) != receipt:
        raise ValueError("TEST_SOURCE_RECEIPT_NOT_PERSISTED")


def _verify_test_projection(
    receipt: SourceReceipt,
    row: dict[str, object] | Mapping[str, object],
) -> None:
    if canonical_sha256({"value": row["value"]}) != receipt.payload_sha256:
        raise ValueError("POINT_IN_TIME_RECEIPT_PROJECTION_MISMATCH")


def _asof_row(
    *,
    entity: str,
    receipt: SourceReceipt,
    **values: object,
) -> dict[str, object]:
    return {
        "entity": entity,
        **receipt.as_dict(),
        "payload_hash": receipt.payload_sha256,
        **values,
    }


def test_receipt_available_at_is_conservative_and_event_time_never_substitutes() -> None:
    old_event = NOW - timedelta(days=30)
    observed_after_cutoff = NOW + timedelta(seconds=1)
    receipt = _source_receipt(
        observed_at=observed_after_cutoff,
        published_at=NOW - timedelta(days=1),
        event_at=old_event,
    )
    assert receipt.available_at == observed_after_cutoff
    with pytest.raises(ValueError, match="TEMPORAL_FEATURE_INPUT_AFTER_CUTOFF"):
        TemporalFeatureLineage(
            feature_name="late-result",
            feature_contract_version="v1",
            input_receipts=(receipt,),
            cutoff_at=NOW,
            computed_at=NOW,
            code_revision="test",
        )


def test_available_at_equal_cutoff_is_admissible_but_after_cutoff_is_not() -> None:
    at_boundary = _source_receipt(observed_at=NOW, marker="boundary")
    lineage = TemporalFeatureLineage(
        feature_name="boundary-feature",
        feature_contract_version="v1",
        input_receipts=(at_boundary,),
        cutoff_at=NOW,
        computed_at=NOW,
        code_revision="test",
    )
    assert lineage.feature_available_at == NOW
    with pytest.raises(ValueError, match="TEMPORAL_FEATURE_INPUT_AFTER_CUTOFF"):
        TemporalFeatureLineage(
            feature_name="after-boundary",
            feature_contract_version="v1",
            input_receipts=(
                _source_receipt(
                    observed_at=NOW + timedelta(microseconds=1),
                    marker="after",
                ),
            ),
            cutoff_at=NOW,
            computed_at=NOW,
            code_revision="test",
        )


@pytest.mark.parametrize(
    "bad_time",
    [datetime(2026, 10, 25, 2, 30), "2026-08-14"],
)
def test_naive_dst_fold_and_date_only_temporal_keys_are_rejected(
    bad_time: datetime | str,
) -> None:
    from robin.temporal.lineage import parse_utc

    with pytest.raises(ValueError, match="UTC_REQUIRED"):
        parse_utc(bad_time, field="available_at")


def test_equivalent_timezone_offsets_have_one_receipt_identity() -> None:
    first = _source_receipt(
        observed_at=datetime.fromisoformat("2026-08-14T14:00:00+02:00"),
        marker="offset",
    )
    second = _source_receipt(observed_at=NOW, marker="offset")
    assert first.receipt_id == second.receipt_id
    assert first.robin_first_observed_at == second.robin_first_observed_at == NOW


def test_asof_equal_time_tie_is_deterministic_or_fails_closed() -> None:
    matching = sorted(
        (
            _asof_row(
                entity="fixture-1",
                receipt=_source_receipt(
                    observed_at=NOW,
                    marker=marker,
                    payload_marker="tie-payload",
                    payload_value=7,
                ),
                value=7,
            )
            for marker in ("tie-a", "tie-b")
        ),
        key=lambda row: str(row["receipt_id"]),
    )
    first, duplicate = matching
    assert asof_select(
        [duplicate, first],
        entity_key="entity",
        available_at_key="available_at",
        payload_hash_key="payload_hash",
        cutoff_at=NOW,
        expected_entity="fixture-1",
        receipt_verifier=_verify_test_receipt,
        projection_verifier=_verify_test_projection,
    ) == first
    contradictory = _asof_row(
        entity="fixture-1",
        receipt=_source_receipt(
            observed_at=NOW,
            marker="tie-contradiction",
            payload_value=99,
        ),
        value=99,
    )
    with pytest.raises(ValueError, match="ASOF_JOIN_AMBIGUOUS"):
        asof_select(
            [first, contradictory],
            entity_key="entity",
            available_at_key="available_at",
            payload_hash_key="payload_hash",
            cutoff_at=NOW,
            expected_entity="fixture-1",
            receipt_verifier=_verify_test_receipt,
            projection_verifier=_verify_test_projection,
        )


def test_asof_rejects_valid_looking_self_declared_receipt_mapping() -> None:
    _ISSUED_TEST_RECEIPTS.clear()
    forged_receipt = SourceReceipt.create(
        source_name="FORGED",
        request_identity="forged-request",
        payload_sha256=canonical_sha256({"value": 42}),
        source_published_at=None,
        robin_first_observed_at=NOW,
        robin_ingested_at=NOW,
        capture_code_revision="forged",
        storage_identity="memory://does-not-exist",
        availability_status=TemporalProofLevel.RECEIPT_ATTESTED,
    )
    self_declared = _asof_row(
        entity="fixture-self-declared",
        receipt=forged_receipt,
        value=42,
    )
    with pytest.raises(ValueError, match="TEST_SOURCE_RECEIPT_NOT_PERSISTED"):
        asof_select(
            [self_declared],
            entity_key="entity",
            available_at_key="available_at",
            payload_hash_key="payload_hash",
            cutoff_at=NOW,
            expected_entity="fixture-self-declared",
            receipt_verifier=_verify_test_receipt,
            projection_verifier=_verify_test_projection,
        )


def test_shadow_without_complete_temporal_lineage_defaults_to_no_bet() -> None:
    decision = decide_shadow_bet(
        fixture_id="fixture-unproven",
        market_key="1X2",
        selection="HOME",
        market_odds={"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        model_probability=0.6,
        devig_method="PROPORTIONAL",
        strategy_version="temporal-v1",
        quality_ok=True,
        decided_at=NOW,
    )
    assert decision.accepted is False
    assert decision.point_in_time_status == "POINT_IN_TIME_NOT_PROVEN"
    assert decision.primary_reason is not None


def test_source_receipt_rejects_non_content_addressed_identifier() -> None:
    receipt = _source_receipt(observed_at=NOW, marker="tamper")
    with pytest.raises(ValueError, match="CONTENT_ADDRESS_MISMATCH"):
        SourceReceipt(
            receipt_id="f" * 64,
            source_name=receipt.source_name,
            request_identity=receipt.request_identity,
            payload_sha256=receipt.payload_sha256,
            source_published_at=receipt.source_published_at,
            robin_first_observed_at=receipt.robin_first_observed_at,
            robin_ingested_at=receipt.robin_ingested_at,
            capture_code_revision=receipt.capture_code_revision,
            storage_identity=receipt.storage_identity,
            availability_status=receipt.availability_status,
            event_at=receipt.event_at,
        )


def test_historical_backtest_without_receipt_lineage_produces_no_decision() -> None:
    result = run_backtest(
        [
            {
                "fixture_id": "legacy-unproven",
                "kickoff_at": "2026-08-15T18:00:00Z",
                "probability_home": 0.8,
                "probability_draw": 0.1,
                "probability_away": 0.1,
                "odds_home": 2.0,
                "odds_draw": 5.0,
                "odds_away": 8.0,
                "target": 0,
                "origin": "OOS HISTORICAL",
            }
        ],
        StrategyParameters("unproven", "1X2", minimum_edge=0.01),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 0
    assert result["temporal_rejected_rows"] == 1
    assert result["point_in_time_status"] == "POINT_IN_TIME_NOT_PROVEN"
    assert result["promotion"] == "NO_PROMOTION"


def test_historical_backtest_rejects_self_declared_point_in_time_scalars() -> None:
    result = run_backtest(
        [
            {
                "fixture_id": "forged-pit-row",
                "kickoff_at": "2026-08-15T18:00:00Z",
                "cutoff_at": "2026-08-15T17:00:00Z",
                "predicted_at": "2026-08-15T16:55:00Z",
                "decided_at": "2026-08-15T16:56:00Z",
                "feature_lineage_hash": "1" * 64,
                "odds_receipt_id": "2" * 64,
                "odds_available_at": "2026-08-15T16:50:00Z",
                "model_registry_hash": "3" * 64,
                "model_available_at": "2026-08-15T16:45:00Z",
                "temporal_contract_version": "POINT_IN_TIME_LINEAGE_V1",
                "point_in_time_status": "POINT_IN_TIME_VALID",
                "probability_home": 0.8,
                "probability_draw": 0.1,
                "probability_away": 0.1,
                "odds_home": 2.0,
                "odds_draw": 5.0,
                "odds_away": 8.0,
                "target": 0,
                "origin": "OOS HISTORICAL",
            }
        ],
        StrategyParameters("forged", "1X2", minimum_edge=0.01),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 0
    assert result["temporal_admissible_rows"] == 0
    assert result["temporal_rejected_rows"] == 1
    assert result["temporal_rejection_reasons"] == {
        "POINT_IN_TIME_RECEIPT_VERIFIER_REQUIRED": 1
    }
    assert result["point_in_time_status"] == "POINT_IN_TIME_NOT_PROVEN"
