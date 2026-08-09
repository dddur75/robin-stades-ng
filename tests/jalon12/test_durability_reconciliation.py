from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, select

import scripts.run_prospective_observatory as observatory_script
from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
    ProspectiveR2Repository,
    ProviderKind,
)
from robin.prospective_observatory.r2 import (
    DurableProviderBudget,
    StoredCapture,
)
from robin.prospective_observatory.temporal import (
    reconstructible_legacy_windows,
)
from robin.providers.contracts import ProviderResult, QuotaState
from robin.storage.database import build_engine
from scripts.run_prospective_observatory import (
    MemoryOperationalState,
    SQLAlchemyOperationalState,
    _reconcile_provider_budget_journal,
    run_capture,
    run_fixture_registry,
    run_replay_audit,
    run_scheduler,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
NOW = datetime(2026, 8, 9, 8, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=1)


def _fixture_record() -> dict[str, object]:
    return {
        "fixture": {
            "id": 9001,
            "date": KICKOFF.isoformat(),
            "status": {"short": "NS"},
        },
        "league": {
            "id": 61,
            "name": "Ligue 1",
            "season": 2026,
            "round": "Regular Season - 1",
        },
        "teams": {
            "home": {"id": 18002, "name": "Home 9001"},
            "away": {"id": 18003, "name": "Away 9001"},
        },
    }


def _cache(path: Path) -> Path:
    fixture = _fixture_record()
    path.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [fixture],
                "payloads": {
                    "api-football:9001": {
                        "FIXTURE": [fixture],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _args(
    command_name: str,
    *,
    output: Path,
    cache: Path | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command_name,
        policy=POLICY,
        output=output,
        now=NOW.isoformat(),
        code_revision="durability-reconciliation-test",
        cache=cache,
        object_store_root=None,
        estimate=False,
        execute=False,
        estimate_file=None,
        competition="Ligue 1",
        max_attempts=2,
        max_objects=250,
    )


def _signed_args(
    command_name: str,
    *,
    output: Path,
    state: MemoryOperationalState,
    repository: ProspectiveR2Repository,
) -> argparse.Namespace:
    estimate = _args(command_name, output=output)
    estimate.estimate = True
    run_capture(estimate, state=state, repository=repository)
    execute = _args(command_name, output=output)
    execute.execute = True
    execute.estimate_file = (
        output
        / {
            "capture-general": "general-capture-estimate.json",
            "capture-player": "player-capture-estimate.json",
            "capture-lineup": "lineup-capture-estimate.json",
            "capture-odds": "odds-capture-estimate.json",
        }[command_name]
    )
    return execute


class _CountingObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def put_if_absent(self, key: str, data: bytes) -> bool:
        self.put_calls += 1
        if key in self.objects:
            return False
        self.objects[key] = bytes(data)
        return True

    def iter_keys(self, prefix: str) -> tuple[str, ...]:
        return tuple(sorted(key for key in self.objects if key.startswith(prefix)))

    def clear(self) -> None:
        self.objects.clear()


class _FailOnceAfterR2State(MemoryOperationalState):
    __slots__ = ("fail_next_window_receipt",)

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_window_receipt = True

    def persist_capture(self, capture: StoredCapture) -> bool:
        if self.fail_next_window_receipt and capture.receipt.window_id is not None:
            self.fail_next_window_receipt = False
            raise RuntimeError("SIMULATED_SQL_PERSIST_FAILURE")
        return super().persist_capture(capture)


class _FailOnceBeforeR2Repository(ProspectiveR2Repository):
    def __init__(self, store: _CountingObjectStore) -> None:
        super().__init__(store)
        self.fail_next_window_capture = True

    def capture(
        self,
        *,
        payload: object,
        context: CaptureContext,
    ) -> StoredCapture:
        if self.fail_next_window_capture and context.window_id is not None:
            self.fail_next_window_capture = False
            raise RuntimeError("SIMULATED_STOP_AFTER_PROVIDER_BEFORE_R2")
        return super().capture(payload=payload, context=context)


class _FailOnceAfterFreshnessR2State(MemoryOperationalState):
    __slots__ = ("fail_next_freshness_projection",)

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_freshness_projection = False

    def persist_capture(self, capture: StoredCapture) -> bool:
        if (
            self.fail_next_freshness_projection
            and capture.receipt.window_id is None
            and capture.receipt.family is CaptureFamily.FIXTURE
            and capture.receipt.source_endpoint == "/fixtures"
        ):
            self.fail_next_freshness_projection = False
            raise RuntimeError("SIMULATED_STOP_AFTER_FRESHNESS_R2")
        return super().persist_capture(capture)


class _LiveApiFootball:
    def __init__(self) -> None:
        self.status_calls = 0
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

    def get_fixtures(self, **_kwargs: object) -> ProviderResult:
        self.fixture_calls += 1
        fixture = _fixture_record()
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures",
            availability=DataAvailability.PRESENT,
            records=(fixture,),
            raw_payload={"response": [fixture]},
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )


class _LiveLineupApiFootball(_LiveApiFootball):
    def __init__(self) -> None:
        super().__init__()
        self.lineup_calls = 0

    def get_lineups(self, **_kwargs: object) -> ProviderResult:
        self.lineup_calls += 1
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures/lineups",
            availability=DataAvailability.ABSENT,
            records=(),
            raw_payload={"response": []},
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
            message="réponse valide sans donnée",
        )


class _ProviderMustNotBeCalled:
    def get_status(self) -> ProviderResult:
        raise AssertionError("provider called after durable reconciliation")

    def get_fixtures(self, **_kwargs: object) -> ProviderResult:
        raise AssertionError("provider called after durable reconciliation")

    def get_competitions(self) -> ProviderResult:
        raise AssertionError("provider called for a zero-due operation")

    def get_odds(self) -> ProviderResult:
        raise AssertionError("provider called for a zero-due operation")


def _migrated_state(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> SQLAlchemyOperationalState:
    database_url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", database_url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return SQLAlchemyOperationalState(build_engine(database_url))


def _provider_billed_capture(
    repository: ProspectiveR2Repository,
) -> StoredCapture:
    fixture = _fixture_record()
    return repository.capture(
        payload={
            "raw_payload_kind": "CANONICAL_PROVIDER_RECORDS",
            "raw_provider_payload": [fixture],
            "normalized_family_records": [fixture],
        },
        context=CaptureContext(
            window_id=None,
            window_label="REGISTRY",
            fixture_id="api-football:9001",
            competition="Ligue 1",
            season="2026",
            provider="api-football",
            family=CaptureFamily.FIXTURE,
            requested_at=NOW,
            response_received_at=NOW,
            observed_at=NOW,
            kickoff_at=KICKOFF,
            cutoff_at=KICKOFF - timedelta(microseconds=1),
            http_status=200,
            source_endpoint="/fixtures",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision="durability-reconciliation-test",
            materialized_at=NOW,
        ),
    )


def test_r2_capture_survives_sql_failure_and_replays_before_provider(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    cache = _cache(tmp_path / "registry-cache.json")
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    state = _FailOnceAfterR2State()
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    due_fixture_window = next(
        window
        for window in state.windows()
        if window.family is CaptureFamily.FIXTURE and window.label == "NEAR_KICKOFF"
    )
    state.window_rows = {
        due_fixture_window.window_id: due_fixture_window,
    }
    execute = _signed_args(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
    )
    provider = _LiveApiFootball()

    with pytest.raises(
        RuntimeError,
        match="SIMULATED_SQL_PERSIST_FAILURE",
    ):
        run_capture(
            execute,
            state=state,
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
        )

    assert provider.status_calls == 1
    assert provider.fixture_calls == 1
    assert not any(
        receipt.window_id == due_fixture_window.window_id for receipt in state.receipts()
    )
    assert any(
        capture.receipt.window_id == due_fixture_window.window_id
        for capture in repository.iter_captures()
    )

    replay = run_replay_audit(
        _args("replay-audit", output=output),
        state=state,
        repository=repository,
    )
    assert replay["status"] == "R2_REPLAY_VERIFIED"

    estimate = _args("capture-general", output=output)
    estimate.estimate = True
    estimate_report = run_capture(
        estimate,
        state=state,
        repository=repository,
    )
    assert estimate_report["windows_due"] == 0
    second_execute = _args("capture-general", output=output)
    second_execute.execute = True
    second_execute.estimate_file = output / "general-capture-estimate.json"
    report = run_capture(
        second_execute,
        state=state,
        repository=repository,
        provider=_ProviderMustNotBeCalled(),  # type: ignore[arg-type]
    )

    assert report["status"] == "CANARY_NOT_DUE_SCHEDULER_READY"
    assert report["provider_calls"] == 0
    assert report["capture_attempts"] == 0
    assert any(receipt.window_id == due_fixture_window.window_id for receipt in state.receipts())


def test_provider_response_before_r2_is_fail_closed_without_second_call(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    cache = _cache(tmp_path / "registry-cache.json")
    store = _CountingObjectStore()
    repository = _FailOnceBeforeR2Repository(store)
    state = MemoryOperationalState()
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    due_fixture_window = next(
        window
        for window in state.windows()
        if window.family is CaptureFamily.FIXTURE
        and window.label == "NEAR_KICKOFF"
    )
    state.window_rows = {
        due_fixture_window.window_id: due_fixture_window,
    }
    execute = _signed_args(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
    )
    provider = _LiveApiFootball()

    with pytest.raises(
        RuntimeError,
        match="SIMULATED_STOP_AFTER_PROVIDER_BEFORE_R2",
    ):
        run_capture(
            execute,
            state=state,
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
        )
    assert provider.status_calls == 1
    assert provider.fixture_calls == 1
    assert state.budget_used(ProviderKind.API_FOOTBALL) == 2
    assert not any(
        receipt.window_id == due_fixture_window.window_id
        for receipt in state.receipts()
    )

    second_execute = _signed_args(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
    )
    with pytest.raises(
        RuntimeError,
        match="PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED",
    ):
        run_capture(
            second_execute,
            state=state,
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
        )

    assert provider.status_calls == 1
    assert provider.fixture_calls == 1
    assert state.budget_used(ProviderKind.API_FOOTBALL) == 2
    guards = [
        record
        for record in repository.provider_budgets()
        if record.reason.startswith("GUARDED_BEFORE_PROVIDER_CALL:")
    ]
    assert len(guards) == 1
    assert guards[0].units == 0
    assert len(guards[0].idempotency_key) <= 250
    assert len(guards[0].reason) <= 250


def test_completed_freshness_guard_replays_receipt_and_allows_deep_call(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    cache = _cache(tmp_path / "registry-cache.json")
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    state = _FailOnceAfterFreshnessR2State()
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    due_lineup_windows = {
        window.window_id: window
        for window in state.windows()
        if window.family in {CaptureFamily.LINEUP, CaptureFamily.FORMATION}
        and window.label == "NEAR_KICKOFF"
    }
    assert len(due_lineup_windows) == 2
    state.window_rows = due_lineup_windows
    state.fail_next_freshness_projection = True
    execute = _signed_args(
        "capture-lineup",
        output=output,
        state=state,
        repository=repository,
    )
    provider = _LiveLineupApiFootball()

    with pytest.raises(
        RuntimeError,
        match="SIMULATED_STOP_AFTER_FRESHNESS_R2",
    ):
        run_capture(
            execute,
            state=state,
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
        )
    assert provider.status_calls == 1
    assert provider.fixture_calls == 1
    assert provider.lineup_calls == 0

    replay = run_replay_audit(
        _args("replay-audit", output=output),
        state=state,
        repository=repository,
    )
    assert replay["status"] == "R2_REPLAY_VERIFIED"

    second_execute = _signed_args(
        "capture-lineup",
        output=output,
        state=state,
        repository=repository,
    )
    report = run_capture(
        second_execute,
        state=state,
        repository=repository,
        provider=provider,  # type: ignore[arg-type]
    )

    assert provider.status_calls == 2
    assert provider.fixture_calls == 1
    assert provider.lineup_calls == 1
    assert report["attempts"] == 2
    assert report["captured_empty"] == 2
    assert report["provider_calls"] == 2
    assert all(
        receipt.window_id is not None
        for receipt in state.receipts()
        if receipt.family in {CaptureFamily.LINEUP, CaptureFamily.FORMATION}
    )
    budget_records = repository.provider_budgets()
    assert budget_records
    assert max(len(record.idempotency_key) for record in budget_records) <= 250
    assert max(len(record.reason) for record in budget_records) <= 250
    assert any(
        record.idempotency_key.startswith("pcc1:")
        for record in budget_records
    )


def test_replay_rejects_sql_receipt_and_index_absent_from_r2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    capture = _provider_billed_capture(repository)
    state = _migrated_state(tmp_path / "parity.db", monkeypatch)
    state.persist_capture(capture)
    assert len(state.receipts()) == 1
    assert (
        state.engine.connect()
        .execute(select(func.count()).select_from(state.tables["prospective_payload_index"]))
        .scalar_one()
        == 1
    )
    store.clear()

    with pytest.raises(
        RuntimeError,
        match="R2_POSTGRESQL_CAPTURE_RECEIPT_PARITY_FAILED",
    ):
        run_replay_audit(
            _args("replay-audit", output=tmp_path / "reports"),
            state=state,
            repository=repository,
        )


def test_duplicate_sql_receipt_uses_restored_exact_mirror_without_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ProspectiveR2Repository(_CountingObjectStore())
    capture = _provider_billed_capture(repository)
    state = _migrated_state(tmp_path / "receipt-fast-path.db", monkeypatch)
    assert state.persist_capture(capture) is True
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(state.engine, "before_cursor_execute", record_statement)
    try:
        assert state.persist_capture(capture) is False
    finally:
        event.remove(
            state.engine,
            "before_cursor_execute",
            record_statement,
        )
    assert statements == []


def test_r2_budget_journal_rebuilds_fresh_sqlite_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    repository.record_provider_budget(
        DurableProviderBudget(
            idempotency_key="capture-general:stable:provider-step:status",
            provider=ProviderKind.API_FOOTBALL.value,
            units=1,
            provider_remaining=74_999,
            provider_reserve=5_000,
            recorded_at=NOW,
            reason="RESERVED_BEFORE_PROVIDER_CALL:status",
            code_revision="durability-reconciliation-test",
        )
    )
    database_path = tmp_path / "budget-rebuild.db"
    state = _migrated_state(database_path, monkeypatch)
    first = run_replay_audit(
        _args("replay-audit", output=tmp_path / "reports"),
        state=state,
        repository=repository,
    )
    restarted = SQLAlchemyOperationalState(build_engine(f"sqlite:///{database_path.as_posix()}"))
    second = run_replay_audit(
        _args("replay-audit", output=tmp_path / "reports"),
        state=restarted,
        repository=repository,
    )

    assert first["budget_records_reconstructed"] == 1
    assert second["budget_records_reconstructed"] == 1
    assert restarted.budget_used(ProviderKind.API_FOOTBALL) == 1
    with restarted.engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(restarted.tables["provider_budget_ledger"])
            ).scalar_one()
            == 1
        )


def test_billed_r2_capture_without_budget_fails_closed_on_non_sqlite_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ProspectiveR2Repository(_CountingObjectStore())
    capture = _provider_billed_capture(repository)
    state = _migrated_state(tmp_path / "missing-budget.db", monkeypatch)
    monkeypatch.setattr(state.engine.dialect, "name", "postgresql")

    with pytest.raises(
        RuntimeError,
        match="R2_PROVIDER_BUDGET_HISTORY_REQUIRED",
    ):
        _reconcile_provider_budget_journal(
            state=state,
            repository=repository,
            captures=(capture,),
        )


def test_zero_due_operation_has_exactly_zero_side_effects(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "empty-cache.json"
    cache.write_text("{}", encoding="utf-8")
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    state = MemoryOperationalState()

    report = run_capture(
        _args("capture-odds", output=tmp_path / "reports", cache=cache),
        state=state,
        repository=repository,
        provider=_ProviderMustNotBeCalled(),  # type: ignore[arg-type]
    )

    assert report["status"] == "CANARY_NOT_DUE_SCHEDULER_READY"
    assert report["provider_calls"] == 0
    assert report["odds_api_credits"] == 0
    assert report["r2_puts"] == 0
    assert report["capture_attempts"] == 0
    assert report["attempts"] == 0
    assert store.put_calls == 0
    assert state.attempts() == ()
    assert state.budget_used(ProviderKind.ODDS_API) == 0


def test_zero_due_capture_does_not_reconcile_missing_r2_objects(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "empty-cache.json"
    cache.write_text("{}", encoding="utf-8")
    store = _CountingObjectStore()
    repository = ProspectiveR2Repository(store)
    capture = _provider_billed_capture(repository)
    store.objects.pop(capture.receipt.r2_key)
    store.objects.pop(capture.receipt.receipt_r2_key)

    report = run_capture(
        _args("capture-odds", output=tmp_path / "reports", cache=cache),
        state=MemoryOperationalState(),
        repository=repository,
        provider=_ProviderMustNotBeCalled(),  # type: ignore[arg-type]
    )

    assert report["status"] == "CANARY_NOT_DUE_SCHEDULER_READY"
    assert report["r2_puts"] == 0
    assert report["recovery_r2_puts"] == 0
    assert report["provider_calls"] == 0
    assert report["capture_attempts"] == 0
    assert capture.receipt.r2_key not in store.objects
    assert capture.receipt.receipt_r2_key not in store.objects


def test_extra_postgresql_projection_is_rejected_by_r2_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path / "player-cache.json")
    cache_value = json.loads(cache.read_text(encoding="utf-8"))
    cache_value["payloads"]["api-football:9001"].update(
        {
            "PLAYER_STATUS": [
                {
                    "team": {"id": 18002},
                    "player": {"id": 7, "type": "Questionable"},
                }
            ],
            "INJURY": [
                {
                    "team": {"id": 18002},
                    "player": {
                        "id": 7,
                        "type": "Questionable",
                        "reason": "test",
                    },
                }
            ],
        }
    )
    cache.write_text(json.dumps(cache_value), encoding="utf-8")
    repository = ProspectiveR2Repository(_CountingObjectStore())
    state = _migrated_state(tmp_path / "projection-parity.db", monkeypatch)
    output = tmp_path / "reports"
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    run_capture(
        _args("capture-player", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    receipt = next(
        item
        for item in state.receipts()
        if item.family is CaptureFamily.PLAYER_STATUS
        and item.window_id is not None
    )
    receipt_table = state.tables["capture_receipts"]
    projection_table = state.tables["prospective_player_status"]
    with state.engine.begin() as connection:
        receipt_id = connection.execute(
            select(receipt_table.c.id).where(
                receipt_table.c.receipt_hash == receipt.receipt_hash
            )
        ).scalar_one()
        connection.execute(
            projection_table.insert().values(
                id="00000000-0000-0000-0000-000000000001",
                receipt_id=receipt_id,
                fixture_id=receipt.fixture_id,
                team_id=receipt.fixture_id,
                player_id="not-in-r2",
                status="INJECTED",
                reason=None,
                observed_at=receipt.observed_at,
                cutoff_at=receipt.cutoff_at,
                projection_hash="0" * 64,
                code_revision=receipt.code_revision,
                append_only=True,
            )
        )

    with pytest.raises(
        RuntimeError,
        match=(
            "R2_POSTGRESQL_PROJECTION_PARITY_FAILED:"
            "prospective_player_status"
        ),
    ):
        run_replay_audit(
            _args("replay-audit", output=output),
            state=state,
            repository=repository,
        )


def test_post_watermark_sql_projection_is_ignored_by_replay_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path / "post-watermark-cache.json")
    repository = ProspectiveR2Repository(_CountingObjectStore())
    state = _migrated_state(tmp_path / "post-watermark.db", monkeypatch)
    output = tmp_path / "post-watermark-reports"
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    run_capture(
        _args("capture-player", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    receipt = next(
        item
        for item in state.receipts()
        if item.family is CaptureFamily.PLAYER_STATUS
        and item.window_id is not None
    )
    original_watermark = observatory_script._capture_sql_replay_watermark

    def watermark_then_concurrent_insert(
        current_state: SQLAlchemyOperationalState,
    ) -> dict[str, set[tuple[object, ...]]]:
        watermark = original_watermark(current_state)
        receipt_table = current_state.tables["capture_receipts"]
        projection_table = current_state.tables[
            "prospective_player_status"
        ]
        with current_state.engine.begin() as connection:
            receipt_id = connection.execute(
                select(receipt_table.c.id).where(
                    receipt_table.c.receipt_hash == receipt.receipt_hash
                )
            ).scalar_one()
            connection.execute(
                projection_table.insert().values(
                    id="00000000-0000-0000-0000-000000000002",
                    receipt_id=receipt_id,
                    fixture_id=receipt.fixture_id,
                    team_id=receipt.fixture_id,
                    player_id="post-watermark",
                    status="CONCURRENT",
                    reason=None,
                    observed_at=receipt.observed_at,
                    cutoff_at=receipt.cutoff_at,
                    projection_hash="1" * 64,
                    code_revision=receipt.code_revision,
                    append_only=True,
                )
            )
        return watermark

    monkeypatch.setattr(
        observatory_script,
        "_capture_sql_replay_watermark",
        watermark_then_concurrent_insert,
    )
    report = run_replay_audit(
        _args("replay-audit", output=output),
        state=state,
        repository=repository,
    )

    assert report["status"] == "R2_REPLAY_VERIFIED"


def test_replay_with_durable_authority_selects_only_canary_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = json.loads(
        (
            ROOT / "configs/operations/robin-chronos-canary-v1.json"
        ).read_text(encoding="utf-8")
    )
    canary["authorized_at"] = "2026-07-31T00:00:00Z"
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(json.dumps(canary), encoding="utf-8")
    monkeypatch.setenv("CHRONOS_CANARY_POLICY", str(canary_path))

    cache = _cache(tmp_path / "scoped-cache.json")
    repository = ProspectiveR2Repository(_CountingObjectStore())
    state = _migrated_state(tmp_path / "scoped.db", monkeypatch)
    output = tmp_path / "scoped-reports"
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    run_capture(
        _args("capture-player", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    repository.capture(
        payload={"normalized_family_records": []},
        context=CaptureContext(
            window_id=None,
            window_label="REGISTRY",
            fixture_id="api-football:outside-canary",
            competition="Ligue 1",
            season="2026",
            provider="cache-test",
            family=CaptureFamily.FIXTURE,
            requested_at=NOW,
            response_received_at=NOW,
            observed_at=NOW,
            kickoff_at=KICKOFF,
            cutoff_at=KICKOFF - timedelta(microseconds=1),
            http_status=200,
            source_endpoint="cache://outside-canary",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=0,
            code_revision="durability-reconciliation-test",
            materialized_at=NOW,
        ),
    )

    report = run_replay_audit(
        _args("replay-audit", output=output),
        state=state,
        repository=repository,
    )

    assert report["status"] == "R2_REPLAY_VERIFIED"
    assert report["replay_scope"] == (
        "CANARY_COHORT_SCIENTIFIC_PROJECTIONS_AND_PROVIDER_BUDGETS"
    )
    assert report["chronos_canary_fixture_count"] == 1
    assert report["namespace_receipts_examined"] > report["payloads_replayed"]
    assert "api-football:outside-canary" not in {
        fixture.fixture_id for fixture in state.fixtures()
    }


def test_partial_legacy_budget_seed_completes_and_rebuilds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ProspectiveR2Repository(_CountingObjectStore())
    state = _migrated_state(tmp_path / "partial-budget.db", monkeypatch)
    rows = (
        {
            "idempotency_key": "legacy-step-b",
            "recorded_at": NOW + timedelta(seconds=1),
            "provider_remaining": 74_998,
        },
        {
            "idempotency_key": "legacy-step-a",
            "recorded_at": NOW,
            "provider_remaining": 74_999,
        },
    )
    for row in rows:
        state.append_budget(
            idempotency_key=str(row["idempotency_key"]),
            provider=ProviderKind.API_FOOTBALL,
            units=1,
            provider_remaining=int(row["provider_remaining"]),
            provider_reserve=5_000,
            recorded_at=row["recorded_at"],  # type: ignore[arg-type]
            reason="LEGACY_SQL_BUDGET",
            code_revision="durability-reconciliation-test",
        )
    repository.record_provider_budget(
        DurableProviderBudget(
            idempotency_key="legacy-step-a",
            provider=ProviderKind.API_FOOTBALL.value,
            units=1,
            provider_remaining=74_999,
            provider_reserve=5_000,
            recorded_at=NOW,
            reason="LEGACY_SQL_BUDGET",
            code_revision="durability-reconciliation-test",
        )
    )

    assert (
        _reconcile_provider_budget_journal(
            state=state,
            repository=repository,
            captures=(),
        )
        == 2
    )
    assert [item.idempotency_key for item in repository.provider_budgets()] == [
        "legacy-step-a",
        "legacy-step-b",
    ]

    rebuilt = _migrated_state(tmp_path / "rebuilt-budget.db", monkeypatch)
    assert (
        _reconcile_provider_budget_journal(
            state=rebuilt,
            repository=repository,
            captures=(),
        )
        == 2
    )
    assert rebuilt.budget_used(ProviderKind.API_FOOTBALL) == 2


def test_v1_versioned_window_rebuilds_from_r2_without_sql_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path / "legacy-window-cache.json")
    repository = ProspectiveR2Repository(_CountingObjectStore())
    source_state = MemoryOperationalState()
    run_fixture_registry(
        _args("fixture-registry", output=tmp_path / "source", cache=cache),
        state=source_state,
        repository=repository,
    )
    fixture = source_state.fixtures()[0]
    legacy_window = next(
        window
        for window in reconstructible_legacy_windows(
            fixture,
            CaptureFamily.LINEUP,
            scheduled_at=NOW,
        )
        if window.window_id.startswith("prospective-window-v2:")
        and window.label == "H-0:45"
    )
    lineup_records = [
        {
            "team": {"id": team_id},
            "formation": formation,
            "startXI": [
                {"player": {"id": start + index}}
                for index in range(11)
            ],
        }
        for team_id, formation, start in (
            (18002, "4-3-3", 1),
            (18003, "4-4-2", 20),
        )
    ]
    repository.capture(
        payload={
            "raw_payload_kind": "CANONICAL_PROVIDER_RECORDS",
            "raw_provider_payload": lineup_records,
            "normalized_family_records": lineup_records,
        },
        context=CaptureContext(
            window_id=legacy_window.window_id,
            window_label=legacy_window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="cache-test",
            family=CaptureFamily.LINEUP,
            requested_at=NOW,
            response_received_at=NOW,
            observed_at=NOW,
            kickoff_at=fixture.kickoff_at,
            cutoff_at=legacy_window.cutoff_at,
            http_status=200,
            source_endpoint="cache://lineup",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=0,
            code_revision=fixture.code_revision,
            materialized_at=NOW,
        ),
    )
    rebuilt = _migrated_state(tmp_path / "legacy-window.db", monkeypatch)

    report = run_replay_audit(
        _args("replay-audit", output=tmp_path / "replay"),
        state=rebuilt,
        repository=repository,
    )

    assert report["status"] == "R2_REPLAY_VERIFIED"
    assert legacy_window.window_id in {
        window.window_id for window in rebuilt.windows()
    }
    with rebuilt.engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).select_from(
                    rebuilt.tables["prospective_lineups"]
                )
            ).scalar_one()
            == 2
        )


def test_batch_crossing_cutoff_skips_freshness_and_deep_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path / "late-batch-cache.json")
    repository = ProspectiveR2Repository(_CountingObjectStore())
    state = MemoryOperationalState()
    output = tmp_path / "late-batch"
    run_fixture_registry(
        _args("fixture-registry", output=output, cache=cache),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    estimate = _args("capture-player", output=output)
    estimate.estimate = True
    run_capture(estimate, state=state, repository=repository)

    class StatusOnlyProvider:
        def __init__(self) -> None:
            self.status_calls = 0
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
                                "current": 1,
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

        def get_fixtures(self, **_kwargs: object) -> ProviderResult:
            self.fixture_calls += 1
            raise AssertionError("freshness call after cutoff")

        def get_injuries(self, **_kwargs: object) -> ProviderResult:
            raise AssertionError("deep call after cutoff")

        def get_squads(self, **_kwargs: object) -> ProviderResult:
            raise AssertionError("deep call after cutoff")

    clock_values = iter((NOW,))
    monkeypatch.setattr(
        "scripts.run_prospective_observatory._utc_now",
        lambda: next(clock_values, KICKOFF),
    )
    execute = _args("capture-player", output=output)
    execute.now = None
    execute.execute = True
    execute.estimate_file = output / "player-capture-estimate.json"
    provider = StatusOnlyProvider()

    report = run_capture(
        execute,
        state=state,
        repository=repository,
        provider=provider,  # type: ignore[arg-type]
    )

    assert provider.status_calls == 1
    assert provider.fixture_calls == 0
    assert report["status"] == "CAPTURE_WINDOWS_MISSED"
    assert report["provider_calls"] == 1
    assert report["captured"] == 0
    assert report["skipped_after_cutoff"] == 2
    assert {
        attempt.status for attempt in state.attempts()
    } == {AvailabilityStatus.MISSED_WINDOW}
