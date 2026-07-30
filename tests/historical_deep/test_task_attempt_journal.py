from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import (
    CAMPAIGN_SCHEMA_VERSION,
    CompetitionSpec,
    HarvestTask,
    TaskStatus,
)
from robin.historical_deep.normalization import classify_temporal
from robin.historical_deep.provider import (
    ProviderAuthenticationError,
    ProviderResponseError,
    ProviderTransportError,
)
from robin.historical_deep.quota import QuotaStatusExpiredError
from robin.historical_deep.runtime import DurableRuntimeLedger
from robin.historical_deep.storage import (
    InMemoryObjectStore,
    R2FirstRepository,
    TaskAttemptEvent,
)

NOW = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)


def _task() -> HarvestTask:
    return HarvestTask.create(
        campaign_id=CAMPAIGN_SCHEMA_VERSION,
        competition=CompetitionSpec(
            canonical_key="api-football:39",
            name="Premier League",
            provider_league_id=39,
        ),
        season=2024,
        family="players",
        endpoint="/players",
        temporal_class=classify_temporal("players"),
        params={"league": 39, "page": 1, "season": 2024},
        page=1,
    )


class FixedProvider:
    def __init__(self, result: object) -> None:
        self.result = result

    def get(
        self,
        endpoint: str,
        params: Mapping[str, object] | None = None,
    ) -> object:
        del endpoint, params
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_attempt_journal_is_append_only_secret_safe_and_receipt_independent() -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    task = _task()

    repository.record_task_attempt(
        task=task,
        attempt_number=1,
        status=TaskStatus.PENDING,
        started_at=NOW,
        recorded_at=NOW,
    )
    repository.record_task_attempt(
        task=task,
        attempt_number=1,
        status=TaskStatus.RUNNING,
        started_at=NOW,
        recorded_at=NOW + timedelta(seconds=1),
    )
    repository.record_task_attempt(
        task=task,
        attempt_number=1,
        status=TaskStatus.RETRYABLE,
        started_at=NOW,
        recorded_at=NOW + timedelta(seconds=2),
        attempts=1,
        provider_calls=1,
        error=RuntimeError("TOPSECRET_DO_NOT_PERSIST"),
    )

    first_attempt = tuple(repository.iter_task_attempts(task))
    assert [event.status for event in first_attempt] == [
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        TaskStatus.RETRYABLE,
    ]
    assert first_attempt[-1].error_class == "RuntimeError"
    assert first_attempt[-1].error_message == "UNCLASSIFIED_ERROR"
    assert repository.next_task_attempt_number(task) == 2
    assert b"TOPSECRET_DO_NOT_PERSIST" not in b"".join(
        store.get_object(key) or b""
        for key in store.iter_keys(repository.namespace)
    )

    repository.record_task_attempt(
        task=task,
        attempt_number=2,
        status=TaskStatus.PENDING,
        started_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
    )
    repository.record_task_attempt(
        task=task,
        attempt_number=2,
        status=TaskStatus.RUNNING,
        started_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1, seconds=1),
    )
    stored = repository.capture(
        task=task,
        payload={"response": [{"player": {"id": 7}}]},
        requested_at=NOW + timedelta(minutes=1, seconds=1),
        received_at=NOW + timedelta(minutes=1, seconds=2),
    )
    receipt_bytes = store.get_object(stored.receipt.receipt_key)
    repository.record_task_attempt(
        task=task,
        attempt_number=2,
        status=TaskStatus.COMPLETE,
        started_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1, seconds=3),
        attempts=1,
        provider_calls=1,
    )

    assert store.get_object(stored.receipt.receipt_key) == receipt_bytes
    assert [event.status for event in repository.iter_task_attempts(task)][-3:] == [
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETE,
    ]
    metrics = DurableRuntimeLedger(store).evidence_metrics()
    assert metrics["task_events"] == 6
    assert metrics["tasks"] == metrics["tasks_completed"] == 1
    assert metrics["tasks_remaining"] == metrics["tasks_failed"] == 0
    assert metrics["task_statuses"] == {"COMPLETE": 1}


def test_storage_uses_exact_quota_header_allowlist() -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)

    with pytest.raises(ValueError, match="UNAPPROVED_QUOTA_HEADER"):
        repository.capture(
            task=_task(),
            payload={"response": []},
            requested_at=NOW,
            received_at=NOW,
            sanitized_quota_headers={
                "x-ratelimit-secret": "must-not-survive",
            },
        )

    assert b"must-not-survive" not in b"".join(
        store.get_object(key) or b"" for key in store.iter_keys("")
    )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_message"),
    [
        (
            ProviderAuthenticationError("API_FOOTBALL_AUTHENTICATION_FAILED"),
            TaskStatus.BLOCKED_PROVIDER,
            "API_FOOTBALL_AUTHENTICATION_FAILED",
        ),
        (
            ProviderTransportError("API_FOOTBALL_TRANSPORT_FAILED"),
            TaskStatus.RETRYABLE,
            "API_FOOTBALL_TRANSPORT_FAILED",
        ),
        (
            QuotaStatusExpiredError("API_FOOTBALL_STATUS_PROOF_EXPIRED"),
            TaskStatus.RETRYABLE,
            "API_FOOTBALL_STATUS_PROOF_EXPIRED",
        ),
        (
            ProviderResponseError("provider body: token=never-store"),
            TaskStatus.FAILED,
            "UNCLASSIFIED_ERROR",
        ),
    ],
)
def test_collector_centrally_journals_sanitized_failures(
    error: Exception,
    expected_status: TaskStatus,
    expected_message: str,
) -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    collector = HistoricalDeepCollector(
        FixedProvider(error),
        repository,
        clock=lambda: NOW,
    )

    with pytest.raises(type(error)):
        collector.harvest_player_pages(39, 2024)

    events = tuple(repository.iter_task_attempts(_task()))
    assert [event.status for event in events] == [
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        expected_status,
    ]
    assert events[-1].attempts == events[-1].provider_calls == 1
    assert events[-1].error_class == type(error).__name__
    assert events[-1].error_message == expected_message
    durable = b"".join(
        store.get_object(key) or b"" for key in store.iter_keys("")
    )
    assert b"never-store" not in durable


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        ([], TaskStatus.EMPTY_VALID),
        ([{"player": {"id": 7}, "statistics": []}], TaskStatus.COMPLETE),
    ],
)
def test_collector_journals_success_after_immutable_capture(
    response: list[object],
    expected_status: TaskStatus,
) -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    collector = HistoricalDeepCollector(
        FixedProvider(
            {
                "response": response,
                "paging": {"current": 1, "total": 1},
                "errors": [],
            }
        ),
        repository,
        clock=lambda: NOW,
    )

    collector.harvest_player_pages(39, 2024)

    events = tuple(repository.iter_task_attempts(_task()))
    assert [event.status for event in events] == [
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        expected_status,
    ]
    assert all(isinstance(event, TaskAttemptEvent) for event in events)
    receipt = repository.receipt_for(_task())
    assert receipt is not None
    assert events[-1].payload_hash == receipt.payload_sha256
    assert events[-1].r2_key == receipt.payload_key
    assert events[-1].rows_normalized == 0
    assert events[-1].rows_received == len(response)
