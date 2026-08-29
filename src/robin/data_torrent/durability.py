"""Chronos-attributed two-object R2 durability boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from robin.data_torrent.contracts import TorrentBudgets, utc_text
from robin.prospective_observatory.chronos_control_plane import (
    AttributableR2EffectExecutor,
    ConditionalPutResult,
    EffectEvent,
    EffectEventType,
    EffectOperation,
    GitHubRunIdentity,
    PostgresAuthorityIssuer,
    PostgresEffectLedger,
)
from robin.prospective_observatory.chronos_r2 import ChronosR2ConditionalStore

_TERMINAL = frozenset({EffectEventType.CREATED_CONFIRMED, EffectEventType.PREEXISTING_CONFIRMED})


class DurableObjectUploadError(RuntimeError):
    """A durable non-success R2 terminal with explicit physical-consumption state."""

    def __init__(
        self,
        code: str,
        *,
        put_permit_consumed: bool,
        terminal_event: EffectEventType,
        operation_id: str,
    ) -> None:
        super().__init__(code)
        self.put_permit_consumed = put_permit_consumed
        self.terminal_event = terminal_event
        self.operation_id = operation_id


class CountingR2Store:
    """Expose no LIST/HEAD/DELETE and enforce the mission-wide physical caps."""

    def __init__(self, store: ChronosR2ConditionalStore, budgets: TorrentBudgets) -> None:
        self._store = store
        self._budgets = budgets
        self.puts = 0
        self.gets = 0
        self.lists = 0
        self.deletes = 0
        self.results: list[ConditionalPutResult] = []

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str],
        on_dispatch: Any,
    ) -> ConditionalPutResult:
        if self.puts >= self._budgets.r2_puts_max:
            raise RuntimeError("DATA_TORRENT_R2_PUT_BUDGET_EXCEEDED")
        self.puts += 1
        result = self._store.put_if_absent(
            key,
            data,
            metadata=metadata,
            on_dispatch=on_dispatch,
        )
        self.results.append(result)
        return result

    def get_object(self, key: str) -> Any:
        if self.gets >= self._budgets.r2_gets_max:
            raise RuntimeError("DATA_TORRENT_R2_GET_BUDGET_EXCEEDED")
        self.gets += 1
        return self._store.get_object(key)

    def counters(self) -> dict[str, int]:
        return {
            "puts": self.puts,
            "gets": self.gets,
            "lists": self.lists,
            "deletes": self.deletes,
        }


class RecordingLedger:
    def __init__(self, ledger: PostgresEffectLedger) -> None:
        self._ledger = ledger
        self.events: list[EffectEvent] = []

    def append_event(
        self,
        *,
        authority_id: str,
        operation: EffectOperation,
        generation_token: str,
        event_type: EffectEventType,
    ) -> EffectEvent:
        event = self._ledger.append_event(
            authority_id=authority_id,
            operation=operation,
            generation_token=generation_token,
            event_type=event_type,
        )
        self.events.append(event)
        return event

    def latest_event(self, operation_id: str) -> EffectEvent | None:
        event = self._ledger.latest_event(operation_id)
        if event is not None:
            self.events.append(event)
        return event


@dataclass(frozen=True, slots=True)
class DurableObjectReceipt:
    role: str
    object_key: str
    object_bytes: int
    object_sha256: str
    operation_id: str
    authority_id: str
    authority_receipt_hash: str
    terminal_event: str
    terminal_event_hash: str
    etag: str | None
    events: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _event_json(event: EffectEvent) -> dict[str, Any]:
    document = asdict(event)
    document["event_type"] = event.event_type.value
    document["db_recorded_at"] = utc_text(event.db_recorded_at)
    return document


def _deduplicated(events: list[EffectEvent]) -> tuple[EffectEvent, ...]:
    return tuple(
        sorted(
            {item.event_hash: item for item in events}.values(),
            key=lambda item: item.event_seq,
        )
    )


def upload_immutable_object(
    *,
    role: str,
    object_key: str,
    payload: bytes,
    mission_id: str,
    identity: GitHubRunIdentity,
    generation_token: str,
    issuer: PostgresAuthorityIssuer,
    base_ledger: PostgresEffectLedger,
    store: CountingR2Store,
) -> DurableObjectReceipt:
    operation = EffectOperation(
        mission_id=mission_id,
        identity=identity,
        resource_kind="R2_OBJECT",
        canonical_key=object_key,
        canonical_payload_hash=hashlib.sha256(payload).hexdigest(),
        code_revision=identity.github_sha,
    )
    authority_id = issuer.issue_authority(
        mission_id=mission_id,
        identity=identity,
        generation_token=generation_token,
        ttl_seconds=900,
        code_revision=identity.github_sha,
    )
    authority = base_ledger.claim_effect_authority(
        authority_id=authority_id,
        operation=operation,
        generation_token=generation_token,
    )
    recorder = RecordingLedger(base_ledger)
    reserved = base_ledger.latest_event(operation.operation_id)
    if reserved is None:
        raise RuntimeError("DATA_TORRENT_R2_RESERVATION_MISSING")
    recorder.events.append(reserved)
    executor = AttributableR2EffectExecutor(ledger=recorder, store=store)
    result = executor.dispatch_reserved(
        authority_id=authority_id,
        authority_receipt_hash=authority.authority_receipt_hash,
        operation=operation,
        generation_token=generation_token,
        payload=payload,
    )
    if result.event.event_type not in _TERMINAL:
        raise DurableObjectUploadError(
            "DATA_TORRENT_R2_DURABILITY_AMBIGUOUS",
            put_permit_consumed=result.put_permit_consumed,
            terminal_event=result.event.event_type,
            operation_id=operation.operation_id,
        )
    chain = _deduplicated(recorder.events)
    if not chain or chain[0].event_type is not EffectEventType.EFFECT_RESERVED:
        raise RuntimeError("DATA_TORRENT_R2_EVENT_CHAIN_INVALID")
    etag = store.results[-1].etag if store.results else None
    return DurableObjectReceipt(
        role=role,
        object_key=object_key,
        object_bytes=len(payload),
        object_sha256=operation.canonical_payload_hash,
        operation_id=operation.operation_id,
        authority_id=authority_id,
        authority_receipt_hash=authority.authority_receipt_hash,
        terminal_event=result.event.event_type.value,
        terminal_event_hash=result.event.event_hash,
        etag=etag,
        events=tuple(_event_json(event) for event in chain),
    )


__all__ = [
    "CountingR2Store",
    "DurableObjectUploadError",
    "DurableObjectReceipt",
    "upload_immutable_object",
]
