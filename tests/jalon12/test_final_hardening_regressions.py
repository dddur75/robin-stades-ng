from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, select

from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory import (
    AvailabilityStatus,
    CaptureAttempt,
    CaptureContext,
    CaptureFamily,
    EvidenceEventKindV3,
    InMemoryObjectStore,
    ProspectiveFixture,
    ProspectiveR2Repository,
    ProviderKind,
    build_observatory_ledger,
    schedule_windows,
)
from robin.prospective_observatory.contracts import canonical_sha256
from robin.providers.contracts import ProviderResult, QuotaState
from robin.storage.database import build_engine
from scripts.build_cockpit_snapshot import (
    _sanitize_preview,
    build_prospective_observatory,
)
from scripts.run_prospective_observatory import (
    DirectoryObjectStore,
    MemoryOperationalState,
    SQLAlchemyOperationalState,
    _active_windows,
    run_capture,
    run_fixture_registry,
    run_gate_report,
    run_replay_audit,
    run_scheduler,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _fixture_record(
    *,
    kickoff_at: datetime,
    phase: str = "Regular Season - 1",
    home_id: int = 1,
    away_id: int = 2,
) -> dict[str, object]:
    return {
        "fixture": {
            "id": 9001,
            "date": kickoff_at.isoformat(),
            "status": {"short": "NS"},
        },
        "league": {
            "id": 61,
            "name": "Ligue 1",
            "season": 2026,
            "round": phase,
        },
        "teams": {
            "home": {"id": home_id, "name": f"Home {home_id}"},
            "away": {"id": away_id, "name": f"Away {away_id}"},
        },
    }


def _write_cache(
    path: Path,
    *,
    kickoff_at: datetime,
    phase: str = "Regular Season - 1",
    home_id: int = 1,
    away_id: int = 2,
) -> Path:
    fixture = _fixture_record(
        kickoff_at=kickoff_at,
        phase=phase,
        home_id=home_id,
        away_id=away_id,
    )
    path.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [fixture],
                "payloads": {
                    "api-football:9001": {
                        "FIXTURE": [fixture],
                        "TEAM": [
                            {
                                "home": {
                                    "id": home_id,
                                    "name": f"Home {home_id}",
                                },
                                "away": {
                                    "id": away_id,
                                    "name": f"Away {away_id}",
                                },
                            }
                        ],
                        "EVENT_STATUS": [
                            {
                                "fixture": {
                                    "id": 9001,
                                    "status": {"short": "NS"},
                                }
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _args(
    command: str,
    *,
    output: Path,
    now: datetime = NOW,
    cache: Path | None = None,
    object_store_root: Path | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command,
        policy=POLICY,
        output=output,
        now=now.isoformat(),
        code_revision="hardening-regression",
        cache=cache,
        object_store_root=object_store_root,
        estimate=False,
        execute=False,
        estimate_file=None,
        competition="Ligue 1",
        max_attempts=3,
        max_objects=250,
    )


def _signed_execution_args(
    command: str,
    *,
    output: Path,
    state: MemoryOperationalState,
    now: datetime = NOW,
    cache: Path | None = None,
    object_store_root: Path | None = None,
) -> argparse.Namespace:
    estimate_args = _args(
        command,
        output=output,
        now=now,
        cache=cache,
        object_store_root=object_store_root,
    )
    estimate_args.estimate = True
    if command == "fixture-registry":
        run_fixture_registry(estimate_args, state=state)
        estimate_name = "fixture-registry-estimate.json"
    else:
        run_capture(estimate_args, state=state)
        estimate_name = {
            "capture-general": "general-capture-estimate.json",
            "capture-player": "player-capture-estimate.json",
            "capture-lineup": "lineup-capture-estimate.json",
            "capture-odds": "odds-capture-estimate.json",
        }[command]
    execute_args = _args(
        command,
        output=output,
        now=now,
        cache=cache,
        object_store_root=object_store_root,
    )
    execute_args.execute = True
    execute_args.estimate_file = output / estimate_name
    return execute_args


class _NoNetworkApiFootball:
    def __init__(
        self,
        *,
        invalid_current_season: bool = False,
        fixtures_error: bool = False,
        fixture: dict[str, object] | None = None,
    ) -> None:
        self.invalid_current_season = invalid_current_season
        self.fixtures_error = fixtures_error
        self.fixture = fixture or _fixture_record(
            kickoff_at=NOW + timedelta(hours=1)
        )
        self.status_calls = 0
        self.competition_calls = 0
        self.fixture_calls = 0

    def get_status(self) -> ProviderResult:
        self.status_calls += 1
        return ProviderResult(
            provider="api-football",
            endpoint="/status",
            availability=DataAvailability.PRESENT,
            records=(
                {
                    "response": {
                        "requests": {
                            "current": self.status_calls,
                            "limit_day": 75_000,
                        }
                    }
                },
            ),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            quota=QuotaState(remaining=74_999),
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )

    def get_competitions(self, **_kwargs: object) -> ProviderResult:
        self.competition_calls += 1
        seasons: list[dict[str, object]]
        if self.invalid_current_season:
            seasons = [
                {"year": 2025, "current": True},
                {"year": 2026, "current": True},
            ]
        else:
            seasons = [{"year": 2026, "current": True}]
        return ProviderResult(
            provider="api-football",
            endpoint="/leagues",
            availability=DataAvailability.PRESENT,
            records=({"seasons": seasons},),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )

    def get_fixtures(self, **_kwargs: object) -> ProviderResult:
        self.fixture_calls += 1
        records: tuple[dict[str, object], ...] = (
            () if self.fixtures_error else (self.fixture,)
        )
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures",
            availability=(
                DataAvailability.ERROR
                if self.fixtures_error
                else DataAvailability.PRESENT
            ),
            records=records,
            raw_payload={"response": list(records)},
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            http_status=503 if self.fixtures_error else 200,
            requested_at=NOW,
            received_at=NOW,
            message="upstream unavailable" if self.fixtures_error else None,
        )


class _FailingCaptureRepository:
    def __init__(self) -> None:
        self.capture_calls = 0

    def capture(self, *, payload: object, context: CaptureContext) -> Any:
        del payload, context
        self.capture_calls += 1
        raise RuntimeError("R2_WRITE_FAILED_AFTER_PROVIDER_CALL")


@pytest.mark.parametrize(
    "mutation",
    [
        {"phase": "Regular Season - 2"},
        {"home_id": 3, "away_id": 4},
    ],
)
def test_fixture_business_change_replaces_active_windows_at_same_kickoff(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    kickoff = NOW + timedelta(hours=2)
    cache = _write_cache(tmp_path / "fixtures.json", kickoff_at=kickoff)
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()

    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            now=NOW,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output, now=NOW), state=state)
    original_window_ids = {window.window_id for window in state.windows()}

    _write_cache(
        cache,
        kickoff_at=kickoff,
        phase=str(mutation.get("phase", "Regular Season - 1")),
        home_id=int(mutation.get("home_id", 1)),
        away_id=int(mutation.get("away_id", 2)),
    )
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            now=NOW + timedelta(minutes=5),
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(
        _args(
            "scheduler",
            output=output,
            now=NOW + timedelta(minutes=5),
        ),
        state=state,
    )

    replacement_window_ids = {
        window.window_id for window in state.windows()
    } - original_window_ids
    active_window_ids = {window.window_id for window in _active_windows(state)}
    assert replacement_window_ids
    assert original_window_ids.isdisjoint(replacement_window_ids)
    assert active_window_ids == replacement_window_ids
    assert original_window_ids.isdisjoint(active_window_ids)


def test_fixture_tbd_appends_tombstone_and_deactivates_existing_windows(
    tmp_path: Path,
) -> None:
    kickoff = NOW + timedelta(hours=2)
    cache = _write_cache(tmp_path / "fixtures.json", kickoff_at=kickoff)
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()

    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            now=NOW,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output, now=NOW), state=state)
    historical_window_ids = {
        window.window_id for window in state.windows()
    }
    assert historical_window_ids
    assert len(state.fixtures()) == 1

    cache_payload = json.loads(cache.read_text(encoding="utf-8"))
    cache_payload["fixtures"][0]["fixture"]["status"]["short"] = "TBD"
    cache.write_text(json.dumps(cache_payload), encoding="utf-8")
    report = run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            now=NOW + timedelta(minutes=5),
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    scheduler = run_scheduler(
        _args(
            "scheduler",
            output=output,
            now=NOW + timedelta(minutes=5),
        ),
        state=state,
    )

    assert report["fixture_tombstones_registered"] == 1
    assert report["fixtures_registered"] == 1
    assert state.fixtures() == ()
    assert len(state.fixture_versions()) == 2
    assert any(fixture.cancelled for fixture in state.fixture_versions())
    assert {window.window_id for window in state.windows()} == historical_window_ids
    assert _active_windows(state) == ()
    assert scheduler["windows_inserted"] == 0
    assert scheduler["windows_due"] == 0


def test_cache_receipts_are_non_live_in_the_cockpit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_now = datetime.now(UTC)
    cache = _write_cache(
        tmp_path / "fixtures.json",
        kickoff_at=report_now + timedelta(hours=1),
    )
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            now=report_now,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(
        _args("scheduler", output=output, now=report_now),
        state=state,
    )
    run_capture(
        _args(
            "capture-general",
            output=output,
            now=report_now,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            now=report_now,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    gate_report = run_gate_report(
        _args("gate-report", output=output, now=report_now),
        state=state,
    )

    receipts = state.receipts()
    assert receipts
    assert {receipt.provider for receipt in receipts} == {"cache-test"}
    assert gate_report["capture_provenance"] == {
        "live_provider_receipts": 0,
        "cache_test_receipts": len(receipts),
        "unverified_receipts": 0,
        "provider_calls_recorded": 0,
    }
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(output))
    cockpit = build_prospective_observatory()
    assert cockpit["origin"] != "LIVE_PROSPECTIVE_CAPTURE"


@pytest.mark.parametrize(
    ("cache_enabled", "local_store_enabled", "expected_error"),
    [
        (
            True,
            False,
            "CACHE_INPUT_FORBIDDEN_FOR_DURABLE_EXECUTION",
        ),
        (
            False,
            True,
            "LOCAL_OBJECT_STORE_FORBIDDEN_FOR_PROVIDER_EXECUTION",
        ),
    ],
)
def test_execute_rejects_cache_and_local_object_store_adapters(
    tmp_path: Path,
    cache_enabled: bool,
    local_store_enabled: bool,
    expected_error: str,
) -> None:
    output = tmp_path / "reports"
    cache = (
        _write_cache(
            tmp_path / "fixtures.json",
            kickoff_at=NOW + timedelta(hours=1),
        )
        if cache_enabled
        else None
    )
    state = MemoryOperationalState()
    execute_args = _signed_execution_args(
        "fixture-registry",
        output=output,
        state=state,
        cache=cache,
        object_store_root=(
            tmp_path / "local-objects" if local_store_enabled else None
        ),
    )
    provider = _NoNetworkApiFootball()
    with pytest.raises(ValueError, match=expected_error):
        run_fixture_registry(
            execute_args,
            state=state,
            repository=ProspectiveR2Repository(InMemoryObjectStore()),
            provider=provider,  # type: ignore[arg-type]
        )
    assert provider.status_calls == 0
    assert provider.competition_calls == 0
    assert provider.fixture_calls == 0


def test_fixture_registry_charges_both_calls_before_season_parse_failure(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    state = MemoryOperationalState()
    execute_args = _signed_execution_args(
        "fixture-registry",
        output=output,
        state=state,
    )
    provider = _NoNetworkApiFootball(invalid_current_season=True)

    for expected_budget in (2, 4):
        with pytest.raises(
            RuntimeError,
            match="API_FOOTBALL_CURRENT_SEASON_NOT_UNIQUE",
        ):
            run_fixture_registry(
                execute_args,
                state=state,
                repository=ProspectiveR2Repository(
                    InMemoryObjectStore()
                ),
                provider=provider,  # type: ignore[arg-type]
            )
        assert state.budget_used(ProviderKind.API_FOOTBALL) == expected_budget

    assert provider.status_calls == 2
    assert provider.competition_calls == 2
    assert provider.fixture_calls == 0


def test_fixture_registry_error_response_fails_explicitly_and_is_charged(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    state = MemoryOperationalState()
    execute_args = _signed_execution_args(
        "fixture-registry",
        output=output,
        state=state,
    )
    provider = _NoNetworkApiFootball(fixtures_error=True)

    with pytest.raises(
        RuntimeError,
        match="API_FOOTBALL_FIXTURES_FAILED:HTTP_503",
    ):
        run_fixture_registry(
            execute_args,
            state=state,
            repository=ProspectiveR2Repository(InMemoryObjectStore()),
            provider=provider,  # type: ignore[arg-type]
        )

    assert provider.status_calls == 1
    assert provider.competition_calls == 1
    assert provider.fixture_calls == 1
    assert state.budget_used(ProviderKind.API_FOOTBALL) == 3


def test_capture_r2_failure_preserves_and_recounts_physical_provider_calls(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    cache = _write_cache(
        tmp_path / "fixtures.json",
        kickoff_at=NOW + timedelta(hours=1),
    )
    bootstrap_repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "bootstrap-objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "bootstrap-objects",
        ),
        state=state,
        repository=bootstrap_repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    execute_args = _signed_execution_args(
        "capture-general",
        output=output,
        state=state,
    )
    provider = _NoNetworkApiFootball()
    failing_repository = _FailingCaptureRepository()

    for expected_budget in (2, 4):
        with pytest.raises(
            RuntimeError,
            match="R2_WRITE_FAILED_AFTER_PROVIDER_CALL",
        ):
            run_capture(
                execute_args,
                state=state,
                repository=failing_repository,  # type: ignore[arg-type]
                provider=provider,  # type: ignore[arg-type]
            )
        assert state.budget_used(ProviderKind.API_FOOTBALL) == expected_budget

    assert provider.status_calls == 2
    assert provider.fixture_calls == 2
    assert failing_repository.capture_calls == 2
    assert state.attempts() == ()


def test_gate_report_reconciles_receipts_missing_compact_attempts(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    cache = _write_cache(
        tmp_path / "fixtures.json",
        kickoff_at=NOW + timedelta(hours=1),
    )
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    run_capture(
        _args(
            "capture-general",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    window_receipts = tuple(
        receipt for receipt in state.receipts() if receipt.window_id is not None
    )
    assert window_receipts
    state.attempt_rows.clear()

    run_gate_report(_args("gate-report", output=output), state=state)

    reconciled = state.attempts()
    assert len(reconciled) == len(window_receipts)
    assert {
        (attempt.window_id, attempt.idempotency_key.rsplit(":", 1)[-1])
        for attempt in reconciled
    } == {
        (receipt.window_id, receipt.payload_sha256)
        for receipt in window_receipts
    }


def _ledger_fixture() -> ProspectiveFixture:
    return ProspectiveFixture(
        fixture_id="fixture-ledger",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season - 1",
        home_team_id="1",
        away_team_id="2",
        kickoff_at=NOW + timedelta(hours=3),
        provider="api-football",
        provider_fixture_id="9001",
        registered_at=NOW - timedelta(hours=1),
        code_revision="hardening-regression",
    )


def test_invalid_receipt_does_not_hide_a_missed_window() -> None:
    fixture = _ledger_fixture()

    window = next(
        item
        for item in schedule_windows(
            fixture,
            CaptureFamily.LINEUP,
            scheduled_at=NOW - timedelta(minutes=30),
            tolerance=timedelta(hours=1),
        )
        if item.label == "H-2"
    )
    stored = ProspectiveR2Repository(InMemoryObjectStore()).capture(
        payload={"normalized_family_records": [{"invalid": True}]},
        context=CaptureContext(
            window_id=window.window_id,
            window_label=window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="api-football",
            family=window.family,
            requested_at=NOW,
            response_received_at=NOW + timedelta(seconds=1),
            observed_at=NOW + timedelta(seconds=1),
            kickoff_at=fixture.kickoff_at,
            cutoff_at=window.cutoff_at,
            http_status=200,
            source_endpoint="/fixtures/lineups",
            complete=False,
            quality_status=AvailabilityStatus.INVALID_PAYLOAD,
            provider_calls=1,
            code_revision="hardening-regression",
        ),
    )

    ledger = build_observatory_ledger(
        fixtures=(fixture,),
        windows=(window,),
        attempts=(),
        receipts=(stored.receipt,),
        gates=(),
        frozen_at=fixture.kickoff_at,
        code_revision="hardening-regression",
    )
    kinds = Counter(event.event_kind for event in ledger.events)
    assert kinds[EvidenceEventKindV3.CAPTURE_WINDOW_MISSED] == 1


def test_attempt_never_links_to_a_receipt_created_after_the_attempt() -> None:
    fixture = _ledger_fixture()

    window = next(
        item
        for item in schedule_windows(
            fixture,
            CaptureFamily.LINEUP,
            scheduled_at=NOW - timedelta(minutes=30),
            tolerance=timedelta(hours=1),
        )
        if item.label == "H-1"
    )
    stored = ProspectiveR2Repository(InMemoryObjectStore()).capture(
        payload={"normalized_family_records": [{"team": "home"}]},
        context=CaptureContext(
            window_id=window.window_id,
            window_label=window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="api-football",
            family=window.family,
            requested_at=NOW + timedelta(minutes=10),
            response_received_at=NOW + timedelta(minutes=11),
            observed_at=NOW + timedelta(minutes=11),
            kickoff_at=fixture.kickoff_at,
            cutoff_at=window.cutoff_at,
            http_status=200,
            source_endpoint="/fixtures/lineups",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision="hardening-regression",
        ),
    )
    attempt = CaptureAttempt(
        attempt_id="attempt-before-receipt",
        idempotency_key=(
            f"{window.window_id}:attempt:1:{stored.receipt.payload_sha256}"
        ),
        window_id=window.window_id,
        fixture_id=fixture.fixture_id,
        provider="api-football",
        family=window.family,
        attempted_at=NOW,
        status=AvailabilityStatus.CAPTURED,
        attempt_number=1,
        http_status=200,
        provider_calls=1,
        code_revision="hardening-regression",
    )

    ledger = build_observatory_ledger(
        fixtures=(fixture,),
        windows=(window,),
        attempts=(attempt,),
        receipts=(stored.receipt,),
        gates=(),
        frozen_at=fixture.kickoff_at,
        code_revision="hardening-regression",
    )
    success = next(
        event
        for event in ledger.events
        if event.event_kind is EvidenceEventKindV3.CAPTURE_SUCCEEDED
    )
    attempt_hash = canonical_sha256(attempt.model_dump(mode="json"))
    assert success.evidence_hashes == (attempt_hash,)
    assert success.evidence_hashes != (stored.receipt.receipt_hash,)


def test_r2_replay_preserves_two_fixture_versions_and_window_foreign_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kickoff_at = NOW + timedelta(hours=3)
    first_fixture = ProspectiveFixture(
        fixture_id="api-football:9001",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season - 1",
        home_team_id="1",
        away_team_id="2",
        kickoff_at=kickoff_at,
        provider="api-football",
        provider_fixture_id="9001",
        registered_at=NOW - timedelta(hours=1),
        code_revision="fixture-version-one",
    )
    second_fixture = first_fixture.model_copy(
        update={
            "home_team_id": "3",
            "away_team_id": "4",
            "registered_at": NOW + timedelta(minutes=5),
            "code_revision": "fixture-version-two",
        }
    )
    fixtures = (first_fixture, second_fixture)
    requested_times = (NOW, NOW + timedelta(minutes=10))
    windows = tuple(
        next(
            window
            for window in schedule_windows(
                fixture,
                CaptureFamily.TEAM,
                scheduled_at=requested_at,
                tolerance=timedelta(hours=1),
            )
            if window.label == "H-2"
        )
        for fixture, requested_at in zip(
            fixtures,
            requested_times,
            strict=True,
        )
    )
    assert windows[0].window_id != windows[1].window_id

    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "versioned-r2")
    )
    for fixture in fixtures:
        provider_record = _fixture_record(
            kickoff_at=kickoff_at,
            home_id=int(fixture.home_team_id),
            away_id=int(fixture.away_team_id),
        )
        registered = fixture.registered_at
        repository.capture(
            payload={
                "raw_payload_kind": "CANONICAL_PROVIDER_RECORDS",
                "raw_provider_payload": [provider_record],
                "normalized_family_records": [provider_record],
                "fixture_contract": fixture.model_dump(mode="json"),
            },
            context=CaptureContext(
                window_id=None,
                window_label="REGISTRY",
                fixture_id=fixture.fixture_id,
                competition=fixture.competition,
                season=fixture.season,
                provider="api-football",
                family=CaptureFamily.FIXTURE,
                requested_at=registered,
                response_received_at=registered + timedelta(seconds=1),
                observed_at=registered + timedelta(seconds=1),
                kickoff_at=kickoff_at,
                cutoff_at=kickoff_at - timedelta(microseconds=1),
                http_status=200,
                source_endpoint="/fixtures",
                complete=True,
                quality_status=AvailabilityStatus.CAPTURED,
                provider_calls=1,
                code_revision=fixture.code_revision,
                materialized_at=registered + timedelta(seconds=2),
            ),
        )
    for fixture, window, requested_at in zip(
        fixtures,
        windows,
        requested_times,
        strict=True,
    ):
        normalized = [
            {
                "home": {"id": int(fixture.home_team_id)},
                "away": {"id": int(fixture.away_team_id)},
            }
        ]
        repository.capture(
            payload={
                "raw_payload_kind": "CANONICAL_PROVIDER_RECORDS",
                "raw_provider_payload": normalized,
                "normalized_family_records": normalized,
            },
            context=CaptureContext(
                window_id=window.window_id,
                window_label=window.label,
                fixture_id=fixture.fixture_id,
                competition=fixture.competition,
                season=fixture.season,
                provider="api-football",
                family=window.family,
                requested_at=requested_at,
                response_received_at=requested_at + timedelta(seconds=1),
                observed_at=requested_at + timedelta(seconds=1),
                kickoff_at=kickoff_at,
                cutoff_at=window.cutoff_at,
                http_status=200,
                source_endpoint="/fixtures",
                complete=True,
                quality_status=AvailabilityStatus.CAPTURED,
                provider_calls=1,
                code_revision=fixture.code_revision,
                materialized_at=requested_at + timedelta(seconds=2),
            ),
        )

    database_url = f"sqlite:///{(tmp_path / 'replayed.db').as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", database_url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = build_engine(database_url)
    state = SQLAlchemyOperationalState(engine)
    replay_args = _args(
        "replay-audit",
        output=tmp_path / "reports",
        now=NOW + timedelta(minutes=30),
        object_store_root=tmp_path / "versioned-r2",
    )

    first_replay = run_replay_audit(
        replay_args,
        state=state,
        repository=repository,
    )
    fixture_table = Table(
        "prospective_fixtures",
        MetaData(),
        autoload_with=engine,
    )
    window_table = Table(
        "capture_windows",
        MetaData(),
        autoload_with=engine,
    )
    with engine.connect() as connection:
        fixture_rows = connection.execute(
            select(
                fixture_table.c.id,
                fixture_table.c.registry_hash,
            )
        ).mappings().all()
        window_rows = connection.execute(
            select(
                window_table.c.window_id,
                window_table.c.fixture_record_id,
            )
        ).mappings().all()
    fixture_ids_by_hash = {
        str(row["registry_hash"]): str(row["id"]) for row in fixture_rows
    }
    window_foreign_keys = {
        str(row["window_id"]): str(row["fixture_record_id"])
        for row in window_rows
    }
    assert set(fixture_ids_by_hash) == {
        fixture.registry_hash for fixture in fixtures
    }
    assert set(window_foreign_keys) == {
        window.window_id for window in windows
    }
    assert window_foreign_keys == {
        window.window_id: fixture_ids_by_hash[fixture.registry_hash]
        for fixture, window in zip(fixtures, windows, strict=True)
    }

    second_replay = run_replay_audit(
        replay_args,
        state=state,
        repository=repository,
    )
    assert first_replay["status"] == "R2_REPLAY_VERIFIED"
    assert second_replay["status"] == "R2_REPLAY_VERIFIED"
    assert second_replay["observatory"]["postgresql"]["inserts"] == 0
    assert (
        second_replay["observatory"]["postgresql"]["duplicates_avoided"]
        == second_replay["payloads_replayed"]
    )
    with engine.connect() as connection:
        assert len(
            connection.execute(select(fixture_table.c.id)).all()
        ) == 2
        assert len(
            connection.execute(select(window_table.c.id)).all()
        ) == 2


def test_captured_window_preview_is_rejected() -> None:
    with pytest.raises(
        RuntimeError,
        match="fen.tre d'aper.u Jalon 12 invalide",
    ):
        _sanitize_preview(
            [
                {
                    "fixture_id": "api-football:9001",
                    "family": "LINEUP",
                    "label": "H-1",
                    "due_at": NOW.isoformat(),
                    "status": "CAPTURED",
                }
            ],
            path="windows.next",
        )
