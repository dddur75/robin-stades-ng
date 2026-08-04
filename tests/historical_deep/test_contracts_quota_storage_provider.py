from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from robin.historical_deep import (
    ApiFootballDeepClient,
    AppendOnlyViolation,
    CircuitOpenError,
    GateStatus,
    HarvestTask,
    HarvestVerdict,
    InMemoryObjectStore,
    ProviderRateLimitError,
    ProviderStatus,
    ProviderStatusError,
    QuotaController,
    QuotaExhaustedError,
    QuotaStatusExpiredError,
    R2FirstRepository,
    TaskStatus,
    TemporalClass,
    build_task_id,
    load_campaign_contract,
)
from robin.historical_deep.provider import ProviderAuthenticationError

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


class FakeTime:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return NOW + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


def _status(
    *,
    checked_at: datetime = NOW,
    expires_at: datetime | None = None,
    daily_limit: int = 200_000,
    daily_remaining: int = 180_000,
) -> ProviderStatus:
    return ProviderStatus(
        plan="Mega",
        active=True,
        daily_limit=daily_limit,
        daily_used=daily_limit - daily_remaining,
        daily_remaining=daily_remaining,
        checked_at=checked_at,
        expires_at=expires_at or checked_at + timedelta(minutes=5),
        subscription_end=checked_at + timedelta(days=31),
    )


def _task() -> HarvestTask:
    contract = load_campaign_contract()
    competition = contract.competition("api-football:39")
    return HarvestTask.create(
        campaign_id=contract.campaign_id,
        competition=competition,
        season=2024,
        family="fixtures",
        endpoint="/fixtures",
        temporal_class=TemporalClass.FIXTURE_SPECIFIC_POST_HOC,
        params={"league": 39, "season": 2024},
    )


def test_campaign_contract_is_exact_typed_and_fail_closed(tmp_path) -> None:
    contract = load_campaign_contract()

    assert contract.subscription_requirements.plan == "Mega"
    assert contract.subscription_requirements.active is True
    assert contract.task_statuses == tuple(TaskStatus)
    assert contract.temporal_classes == tuple(TemporalClass)
    assert contract.gate_statuses == tuple(GateStatus)
    assert contract.verdicts == tuple(HarvestVerdict)
    assert contract.storage.namespace == "historical-deep-data/schema-v1"
    assert len(contract.contract_hash) == 64

    invalid = contract.model_dump(mode="json", by_alias=True)
    invalid["task_statuses"] = invalid["task_statuses"][:-1]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValidationError, match="HARVEST_ENUM_CONTRACT"):
        load_campaign_contract(path)


def test_task_id_is_canonical_and_rejects_sensitive_parameters() -> None:
    task = _task()
    expected = build_task_id(
        campaign_id=task.campaign_id,
        competition=task.competition,
        season=task.season,
        family=task.family,
        endpoint=task.endpoint,
        params={"season": 2024, "league": 39},
    )

    assert task.task_id == expected
    assert len(task.task_id) == 64
    with pytest.raises(ValueError, match="SENSITIVE"):
        build_task_id(
            campaign_id=task.campaign_id,
            competition=task.competition,
            season=task.season,
            family=task.family,
            endpoint=task.endpoint,
            params={"x-apisports-key": "must-not-be-read"},
        )


def test_quota_formula_headers_and_durable_mission_usage() -> None:
    controller = QuotaController(
        _status(),
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
        initial_mission_used=25,
    )

    assert controller.budget.reserve == 40_000
    assert controller.budget.available == 140_000
    assert controller.budget.mission_cap == 100_000
    assert controller.mission_used == 25

    controller.before_request()
    controller.observe_headers(
        {
            "X-RateLimit-Requests-Limit": "200000",
            "X-RateLimit-Requests-Remaining": "179999",
            "X-RateLimit-Rps-Limit": "4",
            "X-RateLimit-Limit": "240",
            "X-RateLimit-Remaining": "239",
        }
    )

    assert controller.mission_used == 26
    assert controller.budget.mission_used == 26
    assert controller.requests_per_second == 4
    assert controller.requests_per_minute == 240
    assert controller.status.per_minute_remaining == 239


def test_expired_status_blocks_data_calls_but_allows_status_refresh() -> None:
    controller = QuotaController(
        _status(
            checked_at=NOW - timedelta(minutes=10),
            expires_at=NOW - timedelta(minutes=5),
        ),
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
    )

    with pytest.raises(QuotaStatusExpiredError, match="STATUS_PROOF_EXPIRED"):
        controller.before_request()
    controller.before_status_refresh()
    assert controller.mission_used == 1


def test_header_remaining_does_not_double_decrement_durable_mission_cap() -> None:
    controller = QuotaController(
        _status(),
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
        initial_mission_used=50_000,
        initial_mission_cap=100_000,
    )

    controller.observe_headers(
        {
            "x-ratelimit-requests-limit": "200000",
            "x-ratelimit-requests-remaining": "130000",
        }
    )

    assert controller.mission_cap == 100_000
    assert controller.budget.available == 90_000
    assert controller.budget.mission_remaining == 50_000


def test_zero_minute_remaining_waits_for_bounded_reset_before_transport() -> None:
    fake_time = FakeTime()
    controller = QuotaController(
        _status(),
        sleeper=fake_time.sleep,
        clock=fake_time.monotonic,
        now=fake_time.now,
    )
    controller.observe_headers(
        {
            "x-ratelimit-limit": "480",
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "2",
        }
    )

    controller.before_request()

    assert fake_time.sleeps == [2.0]
    assert controller.mission_used == 1
    assert controller.status.per_minute_remaining == 479

    controller.before_request()
    assert fake_time.sleeps == [2.0, 0.125]
    assert controller.mission_used == 2


@pytest.mark.parametrize(
    ("headers", "error_code"),
    [
        (
            {"x-ratelimit-remaining": "0"},
            "MINUTE_QUOTA_EXHAUSTED_RESET_UNKNOWN",
        ),
        (
            {
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "61",
            },
            "MINUTE_QUOTA_RESET_WAIT_EXCEEDS_BOUND",
        ),
    ],
)
def test_zero_minute_remaining_fails_closed_without_bounded_reset(
    headers: Mapping[str, str],
    error_code: str,
) -> None:
    fake_time = FakeTime()
    controller = QuotaController(
        _status(),
        sleeper=fake_time.sleep,
        clock=fake_time.monotonic,
        now=fake_time.now,
    )
    controller.observe_headers(headers)

    with pytest.raises(QuotaExhaustedError, match=error_code):
        controller.before_request()

    assert fake_time.sleeps == []
    assert controller.mission_used == 0


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(headers or {})

    def json(self) -> object:
        return self._payload


class FakeTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: int,
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_status_is_mega_active_sanitized_fresh_and_header_backed() -> None:
    transport = FakeTransport(
        [
            FakeResponse(
                200,
                {
                    "response": {
                        "account": {
                            "email": "private@example.test",
                            "api_key": "must-not-survive",
                        },
                        "subscription": {
                            "plan": "Mega",
                            "active": True,
                            "end": "2026-08-30T12:00:00Z",
                        },
                        "requests": {"current": 12, "limit_day": 200_000},
                    }
                },
                {
                    "X-RateLimit-Requests-Limit": "200000",
                    "X-RateLimit-Requests-Remaining": "180000",
                    "X-RateLimit-Rps-Limit": "4",
                    "X-RateLimit-Limit": "300",
                    "X-RateLimit-Remaining": "299",
                    "X-RateLimit-Requests-Reset": "60",
                    "Set-Cookie": "private",
                },
            )
        ]
    )
    client = ApiFootballDeepClient(
        api_key="top-secret",
        transport=transport,
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
    )

    status = client.get_status()

    assert status.plan == "Mega" and status.active is True
    assert status.daily_used == 20_000
    assert status.daily_remaining == 180_000
    assert status.requests_per_second == 4
    assert status.requests_per_minute == 300
    assert status.per_minute_remaining == 299
    assert status.days_remaining == 31
    assert status.next_quota_reset == NOW + timedelta(seconds=60)
    assert status.status_expires_at == NOW + timedelta(minutes=5)
    serialized = json.dumps(status.model_dump(mode="json"))
    assert "top-secret" not in serialized
    assert "private@example.test" not in serialized
    assert "api_key" not in serialized
    assert "set-cookie" not in status.sanitized_headers
    request = transport.calls[0]
    assert request["url"] == "https://v3.football.api-sports.io/status"
    assert "top-secret" not in str(request["url"])
    assert request["params"] == {}
    assert request["headers"] == {
        "accept": "application/json",
        "x-apisports-key": "top-secret",
    }


def test_non_mega_status_is_rejected_without_leaking_payload() -> None:
    transport = FakeTransport(
        [
            FakeResponse(
                200,
                {
                    "response": {
                        "subscription": {
                            "plan": "Pro",
                            "active": True,
                            "end": "2026-08-30",
                        },
                        "requests": {"current": 1, "limit_day": 1000},
                    }
                },
            )
        ]
    )
    client = ApiFootballDeepClient(
        api_key="secret",
        transport=transport,
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
    )

    with pytest.raises(ProviderStatusError, match="MEGA_ACTIVE_REQUIRED"):
        client.get_status()


@pytest.mark.parametrize("http_status", [401, 403])
def test_authentication_errors_are_typed_and_never_leak_body_or_secret(
    http_status: int,
) -> None:
    leaked_body = "provider-body-private"
    secret = "top-secret-credential"
    transport = FakeTransport(
        [
            FakeResponse(
                http_status,
                {"errors": {"token": leaked_body}},
                {"Authorization": secret, "Set-Cookie": leaked_body},
            )
        ]
    )
    client = ApiFootballDeepClient(
        api_key=secret,
        transport=transport,
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
    )

    with pytest.raises(ProviderAuthenticationError) as captured:
        client.get_status()

    assert str(captured.value) == "API_FOOTBALL_AUTHENTICATION_FAILED"
    assert secret not in str(captured.value)
    assert leaked_body not in str(captured.value)
    assert len(transport.calls) == 1


def test_429_has_three_retries_then_opens_circuit() -> None:
    transport = FakeTransport(
        [FakeResponse(429, {}) for _ in range(4)]
    )
    quota = QuotaController(
        _status(),
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
        now=lambda: NOW,
    )
    client = ApiFootballDeepClient(
        api_key="secret",
        quota=quota,
        transport=transport,
        sleeper=lambda _seconds: None,
        jitter=lambda: 0.0,
        clock=lambda: 1.0,
        now=lambda: NOW,
        circuit_failure_threshold=1,
    )

    with pytest.raises(ProviderRateLimitError, match="RETRY_EXHAUSTED"):
        client.get("/fixtures", params={"league": 39, "season": 2024})
    assert len(transport.calls) == 4
    assert quota.mission_used == 4
    with pytest.raises(CircuitOpenError):
        client.get("/fixtures", params={"league": 39, "season": 2024})


class CrashOnceStore(InMemoryObjectStore):
    def __init__(self, suffix: str) -> None:
        super().__init__()
        self.suffix = suffix
        self.failed = False

    def put_if_absent(self, key: str, data: bytes) -> bool:
        if key.endswith(self.suffix) and not self.failed:
            self.failed = True
            raise RuntimeError("SIMULATED_CRASH")
        return super().put_if_absent(key, data)


def test_r2_first_key_metadata_idempotence_and_no_raw_duplication() -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    task = _task()
    payload = {"response": [{"fixture": {"id": 1001}}]}
    captured = repository.capture(
        task=task,
        payload=payload,
        requested_at=NOW,
        received_at=NOW + timedelta(seconds=1),
        sanitized_quota_headers={
            "x-ratelimit-requests-remaining": "179999",
        },
        source_commit="deadbeef",
        attempts=2,
        provider_calls=2,
    )

    expected_prefix = (
        "historical-deep-data/schema-v1/"
        "competition=api-football:39/season=2024/family=fixtures/"
        f"endpoint=fixtures/task={task.task_id}/payload-"
    )
    assert captured.receipt.payload_key.startswith(expected_prefix)
    assert captured.receipt.payload_key.endswith(
        f"{captured.receipt.payload_sha256}.json.gz"
    )
    assert captured.receipt.parameters == {"league": 39, "season": 2024}
    assert captured.receipt.parameters_hash
    assert captured.receipt.source_commit == "deadbeef"
    assert captured.receipt.attempts == captured.receipt.provider_calls == 2
    assert captured.receipt.sanitized_quota_headers == {
        "x-ratelimit-requests-remaining": "179999"
    }

    gzip_keys = [
        key for key in store.iter_keys(repository.namespace) if key.endswith(".json.gz")
    ]
    assert gzip_keys == [captured.receipt.payload_key]
    recovery = store.get_object(captured.receipt.recovery_key)
    assert recovery is not None
    assert b"compressed_payload_base64" not in recovery
    assert len(recovery) < captured.receipt.stored_bytes + 2_000

    second = repository.capture(
        task=task,
        payload=payload,
        requested_at=NOW,
        received_at=NOW + timedelta(seconds=1),
        source_commit="deadbeef",
        attempts=2,
        provider_calls=2,
    )
    assert not second.payload_created
    assert repository.payload_for(task) == payload
    assert list(repository.iter_captures())[0].payload == payload
    with pytest.raises(AppendOnlyViolation, match="TASK_PAYLOAD_MISMATCH"):
        repository.capture(
            task=task,
            payload={"response": [{"fixture": {"id": 2002}}]},
            requested_at=NOW,
            received_at=NOW + timedelta(seconds=1),
        )


@pytest.mark.parametrize("crash_suffix", ["recovery-intent.json", "receipt.json"])
def test_crash_after_single_raw_write_recovers_without_provider(
    crash_suffix: str,
) -> None:
    store = CrashOnceStore(crash_suffix)
    repository = R2FirstRepository(store)
    task = _task()
    payload = {"response": [{"fixture": {"id": 1001}}]}

    with pytest.raises(RuntimeError, match="SIMULATED_CRASH"):
        repository.capture(
            task=task,
            payload=payload,
            requested_at=NOW,
            received_at=NOW + timedelta(seconds=1),
        )

    recovered = repository.resume_pending()
    assert len(recovered) == 1
    assert recovered[0].task_id == task.task_id
    assert repository.payload_for(task) == payload
    assert len(
        [
            key
            for key in store.iter_keys(repository.namespace)
            if key.endswith(".json.gz")
        ]
    ) == 1


def test_task_lookup_recovers_only_the_requested_incomplete_capture() -> None:
    store = CrashOnceStore("receipt.json")
    repository = R2FirstRepository(store)
    task = _task()
    payload = {"response": [{"fixture": {"id": 1001}}]}

    with pytest.raises(RuntimeError, match="SIMULATED_CRASH"):
        repository.capture(
            task=task,
            payload=payload,
            requested_at=NOW,
            received_at=NOW + timedelta(seconds=1),
        )

    recovered = R2FirstRepository(store).receipt_for(task)
    assert recovered is not None
    assert recovered.task_id == task.task_id
    assert R2FirstRepository(store).payload_for(task) == payload


def test_crash_writing_payload_resumes_preexisting_version_on_retry() -> None:
    store = CrashOnceStore(".json.gz")
    repository = R2FirstRepository(store)
    task = _task()
    payload = {"response": [{"fixture": {"id": 1001}}]}

    with pytest.raises(RuntimeError, match="SIMULATED_CRASH"):
        repository.capture(
            task=task,
            payload=payload,
            requested_at=NOW,
            received_at=NOW + timedelta(seconds=1),
            source_commit="first-attempt",
        )

    assert store.get_object(
        f"historical-deep-data/schema-v1/"
        f"competition=api-football:39/season=2024/family=fixtures/"
        f"endpoint=fixtures/task={task.task_id}/version.json"
    ) is not None
    assert not any(key.endswith(".json.gz") for key in store.iter_keys(""))

    resumed = repository.capture(
        task=task,
        payload=payload,
        requested_at=NOW + timedelta(minutes=5),
        received_at=NOW + timedelta(minutes=5, seconds=1),
        source_commit="retry-attempt",
    )

    assert resumed.version_created is False
    assert resumed.payload_created is True
    assert resumed.receipt.requested_at == NOW
    assert resumed.receipt.source_commit == "first-attempt"
    assert repository.payload_for(task) == payload
    assert len(
        [key for key in store.iter_keys("") if key.endswith(".json.gz")]
    ) == 1


def test_crash_writing_payload_rejects_different_retry_payload() -> None:
    store = CrashOnceStore(".json.gz")
    repository = R2FirstRepository(store)
    task = _task()

    with pytest.raises(RuntimeError, match="SIMULATED_CRASH"):
        repository.capture(
            task=task,
            payload={"response": [{"fixture": {"id": 1001}}]},
            requested_at=NOW,
            received_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(AppendOnlyViolation, match="TASK_PAYLOAD_MISMATCH"):
        repository.capture(
            task=task,
            payload={"response": [{"fixture": {"id": 2002}}]},
            requested_at=NOW + timedelta(minutes=5),
            received_at=NOW + timedelta(minutes=5, seconds=1),
        )

    assert not any(key.endswith(".json.gz") for key in store.iter_keys(""))
