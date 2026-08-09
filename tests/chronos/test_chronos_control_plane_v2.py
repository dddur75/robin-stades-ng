from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any

import pytest

from robin.prospective_observatory.chronos_control_plane import (
    AttributableR2EffectExecutor,
    ChronosControlPlaneError,
    ConditionalPutOutcome,
    ConditionalPutResult,
    EffectEventType,
    EffectOperation,
    GitHubRunIdentity,
    MemoryChronosControlPlane,
    ObservedObject,
    PostgresAuthorityIssuer,
    PostgresEffectLedger,
    derive_event_hash,
    derive_operation_id,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
EPOCH = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
GENERATION = "ab" * 32
OTHER_GENERATION = "cd" * 32
SHA = "1" * 40
PAYLOAD = b'{"chronos":"v2"}'
PAYLOAD_HASH = hashlib.sha256(PAYLOAD).hexdigest()


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def identity(**changes: object) -> GitHubRunIdentity:
    values: dict[str, object] = {
        "github_run_id": 123456,
        "github_run_attempt": 2,
        "github_sha": SHA,
        "github_workflow_ref": "dddur75/robin-stades-ng/.github/workflows/x.yml@refs/heads/main",
        "github_workflow_sha": "2" * 40,
        "github_repository": "dddur75/robin-stades-ng",
        "github_ref": "refs/heads/main",
    }
    values.update(changes)
    return GitHubRunIdentity(**values)  # type: ignore[arg-type]


def operation(
    *, run: GitHubRunIdentity | None = None, payload_hash: str = PAYLOAD_HASH
) -> EffectOperation:
    return EffectOperation(
        mission_id="chronos-e1",
        identity=run or identity(),
        resource_kind="R2_OBJECT",
        canonical_key="chronos/e1/payload.json",
        canonical_payload_hash=payload_hash,
        code_revision=(run or identity()).github_sha,
    )


def issued(
    *, ttl_seconds: int = 60
) -> tuple[MutableClock, MemoryChronosControlPlane, str, EffectOperation]:
    clock = MutableClock()
    ledger = MemoryChronosControlPlane(clock=clock, postgres_server_epoch=EPOCH)
    item = operation()
    authority_id = ledger.issue_authority(
        mission_id=item.mission_id,
        identity=item.identity,
        generation_token=GENERATION,
        ttl_seconds=ttl_seconds,
        code_revision=item.code_revision,
    )
    return clock, ledger, authority_id, item


def reserved(
    *, ttl_seconds: int = 60
) -> tuple[MutableClock, MemoryChronosControlPlane, str, EffectOperation, str]:
    clock, ledger, authority_id, item = issued(ttl_seconds=ttl_seconds)
    receipt = ledger.claim_effect_authority(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
    )
    return clock, ledger, authority_id, item, receipt.authority_receipt_hash


class FakeStore:
    def __init__(self, mode: str, *, observed: bytes | None = None) -> None:
        self.mode = mode
        self.observed = observed
        self.put_calls = 0
        self.get_calls = 0
        self.metadata: dict[str, str] = {}

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str],
        on_dispatch: Callable[[], None],
    ) -> ConditionalPutResult:
        del key
        if self.mode == "before":
            raise OSError("before dispatch")
        on_dispatch()
        self.put_calls += 1
        self.metadata = dict(metadata)
        if self.mode == "ack_lost":
            self.observed = data
            raise TimeoutError("response lost")
        if self.mode == "created":
            self.observed = data
            return ConditionalPutResult(ConditionalPutOutcome.CREATED)
        if self.mode == "created_retried":
            self.observed = data
            return ConditionalPutResult(
                ConditionalPutOutcome.CREATED,
                transport_attempts=2,
                automatic_retry_possible=True,
            )
        if self.mode in {"preexisting", "get_error", "mismatch"}:
            return ConditionalPutResult(ConditionalPutOutcome.PRECONDITION_FAILED)
        if self.mode == "preexisting_retried":
            return ConditionalPutResult(
                ConditionalPutOutcome.PRECONDITION_FAILED,
                transport_attempts=2,
                automatic_retry_possible=True,
            )
        if self.mode == "definite_retried":
            return ConditionalPutResult(
                ConditionalPutOutcome.DEFINITE_FAILURE,
                transport_attempts=2,
                automatic_retry_possible=True,
            )
        if self.mode == "definite":
            return ConditionalPutResult(ConditionalPutOutcome.DEFINITE_FAILURE)
        if self.mode == "conflict":
            return ConditionalPutResult(ConditionalPutOutcome.CONFLICT)
        self.observed = data
        return ConditionalPutResult(ConditionalPutOutcome.AMBIGUOUS)

    def get_object(self, key: str) -> ObservedObject | None:
        del key
        self.get_calls += 1
        if self.mode == "get_error":
            raise OSError("read unavailable")
        if self.mode == "mismatch":
            return ObservedObject(data=b"different", metadata={})
        if self.observed is None:
            return None
        return ObservedObject(data=self.observed, metadata={})


def dispatch(mode: str, *, observed: bytes | None = None) -> tuple[Any, FakeStore, Any]:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    store = FakeStore(mode, observed=observed)
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    result = executor.dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    return result, store, ledger


def test_operation_id_golden_and_run_attempt_binding() -> None:
    assert derive_operation_id(
        mission_id="mission-e1",
        github_run_id=123456,
        github_run_attempt=2,
        resource_kind="R2_OBJECT",
        canonical_key="chronos/test.json",
        canonical_payload_hash="ab" * 32,
    ) == "88f560d254938d04a563b12aec9d6b428910a0a064056a0ff33092afd7739b3e"
    first = operation()
    assert first.operation_id == operation().operation_id
    assert first.operation_id != operation(
        run=identity(github_run_attempt=3)
    ).operation_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("github_run_id", 987654),
        ("github_run_attempt", 3),
        ("github_sha", "3" * 40),
        ("github_workflow_ref", "org/repo/.github/workflows/y.yml@refs/heads/main"),
        ("github_workflow_sha", "4" * 40),
        ("github_repository", "other/repo"),
        ("github_ref", "refs/heads/other"),
    ],
)
def test_every_github_identity_field_is_bound(field: str, value: object) -> None:
    _, ledger, authority_id, _ = issued()
    changed = operation(run=identity(**{field: value}))
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH",
    ):
        ledger.claim_effect_authority(
            authority_id=authority_id,
            operation=changed,
            generation_token=GENERATION,
        )


def test_claim_is_atomic_idempotent_and_hash_chained() -> None:
    _, ledger, authority_id, item = issued()
    first = ledger.claim_effect_authority(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
    )
    second = ledger.claim_effect_authority(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
    )
    events = ledger.operation_events(item.operation_id)
    assert first == second
    assert [event.event_type for event in events] == [
        EffectEventType.AUTHORITY_GRANTED,
        EffectEventType.EFFECT_RESERVED,
    ]
    assert events[1].previous_event_hash == events[0].event_hash
    assert events[0].event_hash == derive_event_hash(
        event_seq=events[0].event_seq,
        operation_id=events[0].operation_id,
        authority_id=events[0].authority_id,
        event_type=events[0].event_type,
        resource_kind=events[0].resource_kind,
        resource_key=events[0].resource_key,
        payload_hash=events[0].payload_hash,
        db_recorded_at=events[0].db_recorded_at,
        github_run_id=events[0].github_run_id,
        github_run_attempt=events[0].github_run_attempt,
        code_revision=events[0].code_revision,
        previous_event_hash=events[0].previous_event_hash,
    )


def test_half_open_expiry_blocks_claim_and_dispatch_without_put() -> None:
    clock, ledger, authority_id, item = issued(ttl_seconds=1)
    clock.value = NOW + timedelta(seconds=1)
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_AUTHORITY_NOT_ACTIVE"):
        ledger.claim_effect_authority(
            authority_id=authority_id,
            operation=item,
            generation_token=GENERATION,
        )

    clock, ledger, authority_id, item, receipt_hash = reserved(ttl_seconds=1)
    clock.value += timedelta(seconds=1)
    assert ledger.claim_effect_authority(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
    ).authority_receipt_hash == receipt_hash
    store = FakeStore("created")
    result = AttributableR2EffectExecutor(ledger=ledger, store=store).dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert result.event.event_type is EffectEventType.FAILED_BEFORE_DISPATCH
    assert result.put_permit_consumed is False
    assert store.put_calls == 0
    assert ledger.accounting().r2_put_requests_dispatched == 0


def test_finalization_after_expiry_is_allowed_but_epoch_is_not() -> None:
    clock, ledger, authority_id, item, _ = reserved(ttl_seconds=1)
    ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.PUT_DISPATCHED,
    )
    clock.value += timedelta(seconds=2)
    assert ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.CREATED_CONFIRMED,
    ).event_type is EffectEventType.CREATED_CONFIRMED

    _, ledger, authority_id, item, _ = reserved()
    ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.PUT_DISPATCHED,
    )
    ledger.restart_server_for_test(EPOCH + timedelta(hours=1))
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_SERVER_EPOCH_MISMATCH"):
        ledger.append_event(
            authority_id=authority_id,
            operation=item,
            generation_token=GENERATION,
            event_type=EffectEventType.CREATED_CONFIRMED,
        )


def test_restore_generation_fence_rejects_every_mutation() -> None:
    _, ledger, authority_id, item, _ = reserved()
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH",
    ):
        ledger.append_event(
            authority_id=authority_id,
            operation=item,
            generation_token=OTHER_GENERATION,
            event_type=EffectEventType.PUT_DISPATCHED,
        )


@pytest.mark.parametrize(
    ("mode", "observed", "expected"),
    [
        ("created", None, EffectEventType.CREATED_CONFIRMED),
        ("preexisting", PAYLOAD, EffectEventType.PREEXISTING_CONFIRMED),
        ("preexisting", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("get_error", PAYLOAD, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("mismatch", None, EffectEventType.INTEGRITY_CONFLICT),
        ("ack_lost", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("ambiguous", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("conflict", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("definite", None, EffectEventType.FAILED_AFTER_DISPATCH),
        ("created_retried", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("preexisting_retried", PAYLOAD, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
        ("definite_retried", None, EffectEventType.PUT_COMMITTED_ACTUAL_PENDING),
    ],
)
def test_r2_outcome_attribution_is_honest(
    mode: str,
    observed: bytes | None,
    expected: EffectEventType,
) -> None:
    result, store, ledger = dispatch(mode, observed=observed)
    assert result.event.event_type is expected
    assert result.put_permit_consumed is True
    assert store.put_calls == 1
    counters = ledger.accounting()
    assert counters.r2_write_units_reserved == 1
    assert counters.r2_put_requests_dispatched == 1
    expected_gets = int(mode in {"preexisting", "get_error", "mismatch"})
    assert store.get_calls == expected_gets
    assert counters.r2_get_requests_dispatched == expected_gets


def test_failure_before_dispatch_costs_no_put_budget() -> None:
    result, store, ledger = dispatch("before")
    assert result.event.event_type is EffectEventType.FAILED_BEFORE_DISPATCH
    assert result.put_permit_consumed is False
    assert store.put_calls == 0
    assert ledger.accounting().r2_put_requests_dispatched == 0


def test_replay_after_permit_never_sends_a_second_put() -> None:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.PUT_DISPATCHED,
    )
    store = FakeStore("created")
    result = AttributableR2EffectExecutor(ledger=ledger, store=store).dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert result.event.event_type is EffectEventType.PUT_COMMITTED_ACTUAL_PENDING
    assert result.put_permit_consumed is True
    assert store.put_calls == 0
    assert ledger.accounting().r2_put_requests_dispatched == 1


def test_recovery_never_promotes_presence_to_created() -> None:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    store = FakeStore("ack_lost")
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    first = executor.dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    recovered = executor.observe_pending(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert first.event.event_type is EffectEventType.PUT_COMMITTED_ACTUAL_PENDING
    assert recovered.event.event_type is EffectEventType.RECOVERY_OBSERVED_MATCHING_OBJECT
    assert store.get_calls == 1
    assert ledger.accounting().r2_get_requests_dispatched == 1
    assert ledger.accounting().r2_objects_created_confirmed == 0
    assert ledger.accounting().r2_write_outcomes_pending == 1
    replay = executor.observe_pending(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert replay.event.event_type is EffectEventType.RECOVERY_OBSERVED_MATCHING_OBJECT
    assert store.get_calls == 1
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_R2_PAYLOAD_HASH_MISMATCH",
    ):
        executor.observe_pending(
            authority_id=authority_id,
            operation=item,
            generation_token=GENERATION,
            payload=b"wrong",
        )


def test_restore_fence_is_checked_before_recovery_get() -> None:
    _, ledger, authority_id, item, receipt_hash = reserved()
    store = FakeStore("ambiguous")
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    assert executor.dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    ).event.event_type is EffectEventType.PUT_COMMITTED_ACTUAL_PENDING
    ledger.restart_server_for_test(EPOCH + timedelta(hours=1))
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_SERVER_EPOCH_MISMATCH"):
        executor.observe_pending(
            authority_id=authority_id,
            operation=item,
            generation_token=GENERATION,
            payload=PAYLOAD,
        )
    assert store.get_calls == 0
    assert ledger.accounting().r2_get_requests_dispatched == 0


def test_get_permit_is_consumed_once_across_crash_and_replay() -> None:
    _, ledger, authority_id, item, receipt_hash = reserved()
    store = FakeStore("ambiguous")
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    executor.dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    permit = ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.R2_GET_DISPATCHED,
    )
    replay = executor.observe_pending(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert replay.event == permit
    assert store.get_calls == 0
    assert ledger.accounting().r2_get_requests_dispatched == 1


def test_immediate_412_get_consumes_the_only_read_permit() -> None:
    _, store, ledger = dispatch("preexisting", observed=None)
    assert store.get_calls == 1
    events = ledger.operation_events(operation().operation_id)
    assert [event.event_type for event in events][-2:] == [
        EffectEventType.R2_GET_DISPATCHED,
        EffectEventType.PUT_COMMITTED_ACTUAL_PENDING,
    ]


def test_payload_and_receipt_hashes_are_checked_before_network() -> None:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    store = FakeStore("created")
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
    with pytest.raises(ValueError, match="CHRONOS_AUTHORITY_RECEIPT_HASH_INVALID"):
        executor.dispatch_reserved(
            authority_id=authority_id,
            authority_receipt_hash="not-a-hash",
            operation=item,
            generation_token=GENERATION,
            payload=PAYLOAD,
        )
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_R2_PAYLOAD_HASH_MISMATCH"):
        executor.dispatch_reserved(
            authority_id=authority_id,
            authority_receipt_hash=receipt_hash,
            operation=item,
            generation_token=GENERATION,
            payload=b"wrong",
        )
    assert store.put_calls == 0


def test_receipt_hash_is_exactly_bound_into_object_metadata() -> None:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    store = FakeStore("created")
    AttributableR2EffectExecutor(ledger=ledger, store=store).dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=receipt_hash,
        operation=item,
        generation_token=GENERATION,
        payload=PAYLOAD,
    )
    assert store.metadata["authority_receipt_hash"] == receipt_hash
    assert store.metadata["operation_id"] == item.operation_id


def test_concurrent_claims_have_one_atomic_chain() -> None:
    _, ledger, authority_id, item = issued()
    other = replace(item, canonical_key="chronos/e1/other.json")

    def claim(candidate: EffectOperation) -> str:
        try:
            ledger.claim_effect_authority(
                authority_id=authority_id,
                operation=candidate,
                generation_token=GENERATION,
            )
        except ChronosControlPlaneError as error:
            return str(error)
        return "claimed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (item, other)))
    assert sorted(results) == ["CHRONOS_AUTHORITY_ALREADY_CONSUMED", "claimed"]
    all_events = ledger.operation_events(item.operation_id) + ledger.operation_events(
        other.operation_id
    )
    assert [event.event_type for event in all_events] == [
        EffectEventType.AUTHORITY_GRANTED,
        EffectEventType.EFFECT_RESERVED,
    ]


def test_two_dispatchers_create_one_permit_and_at_most_one_put() -> None:
    clock, ledger, authority_id, item, receipt_hash = reserved()
    del clock
    barrier = Barrier(2)

    class RacingStore(FakeStore):
        def put_if_absent(
            self,
            key: str,
            data: bytes,
            *,
            metadata: Mapping[str, str],
            on_dispatch: Callable[[], None],
        ) -> ConditionalPutResult:
            barrier.wait()
            return super().put_if_absent(
                key,
                data,
                metadata=metadata,
                on_dispatch=on_dispatch,
            )

    store = RacingStore("created")
    executor = AttributableR2EffectExecutor(ledger=ledger, store=store)

    def run() -> EffectEventType:
        return executor.dispatch_reserved(
            authority_id=authority_id,
            authority_receipt_hash=receipt_hash,
            operation=item,
            generation_token=GENERATION,
            payload=PAYLOAD,
        ).event.event_type

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(run), pool.submit(run))]
    assert store.put_calls == 1
    assert ledger.accounting().r2_put_requests_dispatched == 1
    assert set(results) <= {
        EffectEventType.CREATED_CONFIRMED,
        EffectEventType.PUT_COMMITTED_ACTUAL_PENDING,
    }


class CaptureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def fetch_one(
        self,
        statement: str,
        parameters: Sequence[object],
    ) -> dict[str, object]:
        values = tuple(parameters)
        self.calls.append((statement, values))
        if "issue" in statement:
            return {"authority_id": "authority"}
        return {
            "authority_id": "authority",
            "db_authorized_at": NOW,
            "expires_at": NOW + timedelta(minutes=1),
            "postgres_server_epoch": EPOCH,
            "authority_receipt_hash": "f" * 64,
        }


@pytest.mark.parametrize("name", ["now", "--now", "injected_clock", "test_now", "fake_now"])
def test_postgresql_adapters_reject_every_clock_injection(name: str) -> None:
    client = CaptureClient()
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_PRODUCTION_CLOCK_INJECTION_FORBIDDEN",
    ):
        PostgresAuthorityIssuer(client, **{name: NOW})
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_PRODUCTION_CLOCK_INJECTION_FORBIDDEN",
    ):
        PostgresEffectLedger(client, **{name: NOW})
    assert not client.calls


def test_postgresql_claim_binds_code_revision_and_raw_generation_nonce() -> None:
    client = CaptureClient()
    ledger = PostgresEffectLedger(client)
    item = operation()
    ledger.claim_effect_authority(
        authority_id="authority",
        operation=item,
        generation_token=GENERATION,
    )
    statement, parameters = client.calls[-1]
    assert statement.count("%s") == 15
    assert parameters[9] == bytes.fromhex(GENERATION)
    assert parameters[-1] == item.code_revision
    for method in (
        PostgresAuthorityIssuer.issue_authority,
        PostgresEffectLedger.claim_effect_authority,
        PostgresEffectLedger.append_event,
    ):
        assert "now" not in inspect.signature(method).parameters


def test_code_revision_and_generation_nonce_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="CHRONOS_CODE_REVISION_MISMATCH"):
        replace(operation(), code_revision="9" * 40)
    _, ledger, authority_id, item = issued()
    with pytest.raises(ValueError, match="CHRONOS_GENERATION_TOKEN_INVALID"):
        ledger.claim_effect_authority(
            authority_id=authority_id,
            operation=item,
            generation_token="short",
        )


def test_illegal_state_transition_is_refused() -> None:
    _, ledger, authority_id, item, _ = reserved()
    with pytest.raises(
        ChronosControlPlaneError,
        match="CHRONOS_EFFECT_TRANSITION_FORBIDDEN",
    ):
        ledger.append_event(
            authority_id=authority_id,
            operation=item,
            generation_token=GENERATION,
            event_type=EffectEventType.CREATED_CONFIRMED,
        )


def test_preexisting_and_conflict_require_a_durable_get_permit() -> None:
    _, ledger, authority_id, item, _ = reserved()
    ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.PUT_DISPATCHED,
    )
    for event_type in (
        EffectEventType.PREEXISTING_CONFIRMED,
        EffectEventType.INTEGRITY_CONFLICT,
    ):
        with pytest.raises(
            ChronosControlPlaneError,
            match="CHRONOS_EFFECT_TRANSITION_FORBIDDEN",
        ):
            ledger.append_event(
                authority_id=authority_id,
                operation=item,
                generation_token=GENERATION,
                event_type=event_type,
            )
    ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.R2_GET_DISPATCHED,
    )
    assert ledger.append_event(
        authority_id=authority_id,
        operation=item,
        generation_token=GENERATION,
        event_type=EffectEventType.PREEXISTING_CONFIRMED,
    ).event_type is EffectEventType.PREEXISTING_CONFIRMED


def test_no_ambiguous_physical_write_counter_exists() -> None:
    counters = MemoryChronosControlPlane(
        clock=MutableClock(), postgres_server_epoch=EPOCH
    ).accounting()
    assert not hasattr(counters, "r2_writes")
    assert not hasattr(counters, "physical_writes_actual")
