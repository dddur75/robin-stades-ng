from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from robin.prospective_observatory import (
    AvailabilityStatus,
    CaptureAttempt,
    CaptureContext,
    CaptureFamily,
    EvidenceEventKindV3,
    GateEvaluation,
    GateName,
    GateStatus,
    InMemoryObjectStore,
    ProspectiveFixture,
    ProspectiveR2Repository,
    build_observatory_ledger,
    observatory_ledger_summary,
    schedule_windows,
)
from robin.prospective_observatory.contracts import RetryDisposition

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=3)


def test_operational_ledger_reconstructs_capture_and_gate_evidence_only() -> None:
    fixture = ProspectiveFixture(
        fixture_id="fixture-1",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season - 1",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=KICKOFF,
        provider="api-football",
        provider_fixture_id="9001",
        registered_at=NOW - timedelta(hours=1),
        code_revision="revision-j12",
    )
    windows = schedule_windows(
        fixture,
        CaptureFamily.LINEUP,
        scheduled_at=NOW - timedelta(minutes=30),
        tolerance=timedelta(hours=1),
    )
    captured_window = next(window for window in windows if window.label == "H-2")
    failed_window = next(window for window in windows if window.label == "H-1")
    repository = ProspectiveR2Repository(InMemoryObjectStore())
    stored = repository.capture(
        payload={"normalized_family_records": [{"team": "home"}]},
        context=CaptureContext(
            window_id=captured_window.window_id,
            window_label=captured_window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="api-football",
            family=CaptureFamily.LINEUP,
            requested_at=NOW,
            response_received_at=NOW + timedelta(seconds=1),
            observed_at=NOW + timedelta(seconds=1),
            kickoff_at=KICKOFF,
            cutoff_at=captured_window.cutoff_at,
            http_status=200,
            source_endpoint="/fixtures/lineups",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision="revision-j12",
        ),
    )
    attempts = (
        CaptureAttempt(
            attempt_id="capture-attempt",
            idempotency_key="capture-attempt-1",
            window_id=captured_window.window_id,
            fixture_id=fixture.fixture_id,
            provider="api-football",
            family=CaptureFamily.LINEUP,
            attempted_at=NOW,
            status=AvailabilityStatus.CAPTURED,
            attempt_number=1,
            http_status=200,
            provider_calls=1,
            code_revision="revision-j12",
        ),
        CaptureAttempt(
            attempt_id="failed-attempt",
            idempotency_key="failed-attempt-1",
            window_id=failed_window.window_id,
            fixture_id=fixture.fixture_id,
            provider="api-football",
            family=CaptureFamily.LINEUP,
            attempted_at=NOW + timedelta(hours=1),
            status=AvailabilityStatus.PROVIDER_UNAVAILABLE,
            retry_disposition=RetryDisposition.RETRY_EXHAUSTED,
            attempt_number=1,
            provider_calls=1,
            error_code="TRANSIENT_PROVIDER_ERROR",
            code_revision="revision-j12",
        ),
    )
    gates = (
        GateEvaluation(
            gate=GateName.PROSPECTIVE_LINEUP_GATE,
            fixture_id=fixture.fixture_id,
            status=GateStatus.PASSED,
            observations=1,
            reason="COMPLETE_LINEUP_RECEIVED_BEFORE_KICKOFF",
            evidence={"starter_count": 11},
        ),
    )

    ledger = build_observatory_ledger(
        fixtures=(fixture,),
        windows=(captured_window, failed_window),
        attempts=attempts,
        receipts=(stored.receipt,),
        gates=gates,
        frozen_at=KICKOFF,
        code_revision="revision-j12",
    )
    summary = observatory_ledger_summary(ledger)
    kinds = Counter(event.event_kind for event in ledger.events)

    assert summary["status"] == "HASH_CHAIN_VERIFIED"
    assert kinds[EvidenceEventKindV3.FIXTURE_REGISTERED] == 1
    assert kinds[EvidenceEventKindV3.CAPTURE_WINDOW_SCHEDULED] == 2
    assert kinds[EvidenceEventKindV3.CAPTURE_ATTEMPTED] == 2
    assert kinds[EvidenceEventKindV3.CAPTURE_SUCCEEDED] == 1
    assert kinds[EvidenceEventKindV3.CAPTURE_FAILED] == 1
    assert kinds[EvidenceEventKindV3.CAPTURE_WINDOW_MISSED] == 1
    assert kinds[EvidenceEventKindV3.TEMPORAL_GATE_PASSED] == 1
    assert kinds[EvidenceEventKindV3.DATASET_VERSION_FROZEN] == 1
    assert summary["bet_decisions"] == 0
    assert summary["real_bets"] is False
    assert summary["social_publishing_enabled"] is False
