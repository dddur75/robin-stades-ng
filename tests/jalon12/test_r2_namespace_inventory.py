from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
    canonical_json_bytes,
)
from robin.prospective_observatory.r2 import (
    InMemoryObjectStore,
    ProspectiveR2Repository,
    R2NamespaceIntegrityError,
    ReceiptRecoveryIntegrityError,
)
from robin.prospective_observatory.replay import (
    InMemoryProjectionSink,
    replay_from_r2,
)

KICKOFF = datetime(2026, 8, 3, 20, tzinfo=UTC)
OBSERVED_AT = KICKOFF - timedelta(hours=1)


def _context(
    *,
    window_id: str = "fixture:LINEUP:H-1",
    window_label: str = "H-1",
) -> CaptureContext:
    return CaptureContext(
        window_id=window_id,
        window_label=window_label,
        fixture_id="ligue1-2026-001",
        competition="Ligue 1",
        season="2026",
        provider="api-football",
        family=CaptureFamily.LINEUP,
        requested_at=OBSERVED_AT - timedelta(seconds=2),
        response_received_at=OBSERVED_AT - timedelta(seconds=1),
        observed_at=OBSERVED_AT,
        cutoff_at=KICKOFF - timedelta(minutes=30),
        kickoff_at=KICKOFF,
        http_status=200,
        source_endpoint="https://v3.football.api-sports.io/fixtures/lineups",
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=1,
        code_revision="revision-j12-inventory",
        materialized_at=OBSERVED_AT,
    )


class _CrashAfterIntentStore(InMemoryObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def put_if_absent(self, key: str, data: bytes) -> bool:
        if "/payload-" in key and not self.failed:
            self.failed = True
            raise RuntimeError("SIMULATED_CRASH_AFTER_INTENT")
        return super().put_if_absent(key, data)


class _CrashAfterPayloadStore(InMemoryObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def put_if_absent(self, key: str, data: bytes) -> bool:
        if "/receipt-" in key and not self.failed:
            self.failed = True
            raise RuntimeError("SIMULATED_CRASH_AFTER_PAYLOAD")
        return super().put_if_absent(key, data)


@pytest.mark.parametrize(
    ("store", "error"),
    [
        (_CrashAfterIntentStore(), "SIMULATED_CRASH_AFTER_INTENT"),
        (_CrashAfterPayloadStore(), "SIMULATED_CRASH_AFTER_PAYLOAD"),
    ],
)
def test_write_ahead_intent_recovers_both_interrupted_write_boundaries(
    store: InMemoryObjectStore,
    error: str,
) -> None:
    repository = ProspectiveR2Repository(store)

    with pytest.raises(RuntimeError, match=error):
        repository.capture(
            payload={"response": [{"team": 1}]},
            context=_context(),
        )

    sink = InMemoryProjectionSink()
    replay = replay_from_r2(repository, sink)

    assert replay.namespace_verified
    assert replay.payloads_replayed == 1
    assert replay.projections_inserted == 1
    assert replay.hash_mismatches == 0
    assert replay.data_loss == 0
    assert replay.objects_examined == 3
    assert replay.physical_recovery_objects == 1
    assert replay.physical_recovery_bytes > 0
    assert len(sink.rows) == 1
    second = replay_from_r2(repository, sink)
    assert second.projections_inserted == 0
    assert second.duplicates_avoided == 1
    inventory = repository.inventory_namespace()
    assert inventory.verified
    assert inventory.physical_unique_objects == 3
    assert inventory.physical_payload_objects == 1
    assert inventory.physical_receipt_objects == 1
    assert inventory.physical_recovery_objects == 1
    assert inventory.physical_recovery_bytes > 0
    assert inventory.physical_unique_objects == (
        inventory.physical_payload_objects
        + inventory.physical_receipt_objects
        + inventory.physical_recovery_objects
    )
    assert inventory.physical_unique_bytes == (
        inventory.physical_payload_bytes
        + inventory.physical_receipt_bytes
        + inventory.physical_recovery_bytes
    )
    assert inventory.logical_references == 1
    assert inventory.orphan_payload_keys == ()
    assert inventory.orphan_receipt_keys == ()


def test_unattributable_payload_orphan_remains_fail_closed() -> None:
    donor_store = InMemoryObjectStore()
    donor_repository = ProspectiveR2Repository(donor_store)
    stored = donor_repository.capture(
        payload={"response": [{"team": 1}]},
        context=_context(),
    )
    payload = donor_store.get_object(stored.receipt.r2_key)
    assert payload is not None

    store = InMemoryObjectStore()
    assert store.put_if_absent(stored.receipt.r2_key, payload)
    repository = ProspectiveR2Repository(store)
    inventory = repository.inventory_namespace()
    assert not inventory.verified
    assert inventory.physical_unique_objects == 1
    assert inventory.physical_recovery_objects == 0
    assert inventory.physical_recovery_bytes == 0
    assert inventory.orphan_payload_keys == (stored.receipt.r2_key,)

    with pytest.raises(
        R2NamespaceIntegrityError,
        match=r"orphan_payloads=1",
    ):
        replay_from_r2(repository, InMemoryProjectionSink())


def test_legacy_complete_capture_without_recovery_intent_remains_replayable() -> None:
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    repository.capture(
        payload={"response": [{"team": 1}]},
        context=_context(),
    )
    for key in tuple(store._objects):  # noqa: SLF001
        if key.startswith("prospective-deep-data-recovery/"):
            store._objects.pop(key)  # noqa: SLF001

    result = replay_from_r2(repository, InMemoryProjectionSink())

    assert result.namespace_verified
    assert result.payloads_replayed == 1
    assert result.objects_examined == 2
    assert result.physical_recovery_objects == 0
    assert result.physical_recovery_bytes == 0
    assert result.hash_mismatches == result.data_loss == 0


def test_tampered_recovery_intent_never_materializes_objects() -> None:
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    repository.capture(
        payload={"response": [{"team": 1}]},
        context=_context(),
    )
    intent_key = next(
        key
        for key in store._objects  # noqa: SLF001
        if key.startswith("prospective-deep-data-recovery/")
    )
    intent = json.loads(store._objects[intent_key])  # noqa: SLF001
    intent["compressed_payload_sha256"] = "0" * 64
    store._objects[intent_key] = canonical_json_bytes(intent)  # noqa: SLF001

    with pytest.raises(
        ReceiptRecoveryIntegrityError,
        match="R2_RECEIPT_RECOVERY_INTENT_MISMATCH",
    ):
        repository.reconcile_pending_receipts()


def test_shared_payload_counts_one_physical_object_and_two_logical_reads() -> None:
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    payload = {"response": [{"team": 1, "startXI": list(range(11))}]}
    first = repository.capture(payload=payload, context=_context())
    second = repository.capture(
        payload=payload,
        context=_context(
            window_id="fixture:LINEUP:H-0:45",
            window_label="H-0:45",
        ),
    )

    assert first.receipt.r2_key == second.receipt.r2_key
    inventory = repository.inventory_namespace()
    receipt_bytes = sum(
        len(store.get_object(key) or b"") for key in inventory.receipt_keys
    )
    physical_bytes = sum(
        len(store.get_object(key) or b"")
        for key in (
            *inventory.payload_keys,
            *inventory.receipt_keys,
            *inventory.recovery_keys,
        )
    )
    recovery_bytes = sum(
        len(store.get_object(key) or b"") for key in inventory.recovery_keys
    )

    assert inventory.verified
    assert inventory.physical_unique_objects == 5
    assert inventory.physical_unique_bytes == physical_bytes
    assert inventory.physical_payload_objects == 1
    assert inventory.physical_payload_bytes == first.receipt.stored_bytes
    assert inventory.physical_receipt_objects == 2
    assert inventory.physical_receipt_bytes == receipt_bytes
    assert inventory.physical_recovery_objects == 2
    assert inventory.physical_recovery_bytes == recovery_bytes
    assert inventory.physical_unique_objects == (
        inventory.physical_payload_objects
        + inventory.physical_receipt_objects
        + inventory.physical_recovery_objects
    )
    assert inventory.physical_unique_bytes == (
        inventory.physical_payload_bytes
        + inventory.physical_receipt_bytes
        + inventory.physical_recovery_bytes
    )
    assert inventory.logical_references == 2
    assert (
        inventory.logical_payload_bytes_read
        == first.receipt.stored_bytes * 2
    )
    assert inventory.logical_receipt_bytes_read == receipt_bytes
    assert inventory.logical_bytes_read == (
        first.receipt.stored_bytes * 2 + receipt_bytes
    )
    assert inventory.orphan_payload_keys == ()
    assert inventory.orphan_receipt_keys == ()

    result = replay_from_r2(repository, InMemoryProjectionSink())
    assert result.namespace_verified
    assert result.objects_examined == 5
    assert result.payloads_replayed == 2
    assert result.physical_unique_objects == 5
    assert result.physical_unique_bytes == physical_bytes
    assert result.physical_recovery_objects == 2
    assert result.physical_recovery_bytes == recovery_bytes
    assert result.logical_references == 2
    assert result.logical_payload_bytes_read == first.receipt.stored_bytes * 2
    assert result.logical_receipt_bytes_read == receipt_bytes
    assert result.logical_bytes_read == (
        result.logical_payload_bytes_read + result.logical_receipt_bytes_read
    )


def test_receipt_without_payload_is_restored_from_the_canonical_intent() -> None:
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    stored = repository.capture(
        payload={"response": [{"team": 1}]},
        context=_context(),
    )
    store._objects.pop(stored.receipt.r2_key)  # noqa: SLF001

    inventory = repository.inventory_namespace()
    assert inventory.verified
    assert inventory.physical_unique_objects == 3
    assert inventory.physical_payload_objects == 1
    assert inventory.physical_receipt_objects == 1
    assert inventory.physical_recovery_objects == 1
    assert inventory.physical_recovery_bytes > 0
    assert inventory.logical_references == 1
    assert inventory.orphan_payload_keys == ()
    assert inventory.orphan_receipt_keys == ()

    sink = InMemoryProjectionSink()
    replay = replay_from_r2(repository, sink)
    assert replay.payloads_replayed == 1
    assert replay.hash_mismatches == replay.data_loss == 0
    assert len(sink.rows) == 1


def test_unexpected_key_and_corrupt_payload_block_namespace_verification() -> None:
    store = InMemoryObjectStore()
    repository = ProspectiveR2Repository(store)
    stored = repository.capture(
        payload={"response": [{"team": 1}]},
        context=_context(),
    )
    unexpected_key = "prospective-deep-data/schema-v1/unexpected-object.bin"
    for key in tuple(store._objects):  # noqa: SLF001
        if key.startswith("prospective-deep-data-recovery/"):
            store._objects.pop(key)  # noqa: SLF001
    store._objects[unexpected_key] = b"unexpected"  # noqa: SLF001
    store._objects[stored.receipt.r2_key] = b"corrupt"  # noqa: SLF001

    inventory = repository.inventory_namespace()
    assert not inventory.verified
    assert inventory.physical_unique_objects == 3
    assert inventory.physical_recovery_objects == 0
    assert inventory.physical_recovery_bytes == 0
    assert inventory.unexpected_keys == (unexpected_key,)
    assert inventory.integrity_error_keys == (stored.receipt.r2_key,)
    assert any(
        error.startswith("R2_PAYLOAD_INVALID:")
        for error in inventory.integrity_errors
    )

    with pytest.raises(R2NamespaceIntegrityError):
        tuple(repository.iter_captures())
    with pytest.raises(R2NamespaceIntegrityError):
        replay_from_r2(repository, InMemoryProjectionSink())
