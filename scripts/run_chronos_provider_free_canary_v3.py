"""Execute one provider-free Chronos canary with bounded R2 effects."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from robin.chronos_production import (
    EXPECTED_AFTER_REVISION,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    generation_hash,
    require_hash,
    require_sha,
    validate_direct_postgres_url,
)
from robin.prospective_observatory.chronos_control_plane import (
    AttributableR2EffectExecutor,
    EffectEvent,
    EffectEventType,
    EffectOperation,
    GitHubRunIdentity,
    PostgresAuthorityIssuer,
    PostgresEffectLedger,
)
from robin.prospective_observatory.chronos_postgres import (
    SQLAlchemyPostgresFunctionClient,
)
from robin.prospective_observatory.chronos_r2 import (
    ChronosR2ConditionalStore,
)
from robin.storage.database import build_engine

TERMINAL_READY = frozenset(
    {
        EffectEventType.CREATED_CONFIRMED,
        EffectEventType.PREEXISTING_CONFIRMED,
    }
)
TERMINAL_PENDING = frozenset(
    {
        EffectEventType.PUT_COMMITTED_ACTUAL_PENDING,
        EffectEventType.RECOVERY_OBSERVED_MATCHING_OBJECT,
    }
)


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_SECRET:{name}")
    return value


def _context(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_CONTEXT:{name}")
    return value


def _canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class RecordingLedger:
    """Record only sanitized returned events while delegating durable writes."""

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


class CountingStore:
    """Expose only PUT-if-absent and exact-key GET, with explicit counters."""

    def __init__(self, store: ChronosR2ConditionalStore) -> None:
        self._store = store
        self.put = 0
        self.get = 0
        self.list = 0
        self.head = 0
        self.delete = 0

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: Mapping[str, str],
        on_dispatch: Any,
    ) -> Any:
        self.put += 1
        if self.put > 1:
            raise ChronosProductionError("CHRONOS_R2_PUT_BUDGET_EXCEEDED")
        return self._store.put_if_absent(
            key,
            data,
            metadata=metadata,
            on_dispatch=on_dispatch,
        )

    def get_object(self, key: str) -> Any:
        self.get += 1
        if self.get > 1:
            raise ChronosProductionError("CHRONOS_R2_GET_BUDGET_EXCEEDED")
        return self._store.get_object(key)

    def counters(self) -> dict[str, int]:
        return {
            "put": self.put,
            "get": self.get,
            "list": self.list,
            "head": self.head,
            "delete": self.delete,
        }


def _accounting(engine: sa.Engine) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT * FROM public.chronos_effect_accounting")
        ).mappings().one()
    return {str(name): int(value) for name, value in row.items()}


def _revision_and_epoch(engine: sa.Engine) -> tuple[str, str]:
    with engine.connect() as connection:
        revision = str(
            connection.scalar(
                sa.text("SELECT version_num FROM public.alembic_version")
            )
        )
        epoch = str(
            connection.scalar(sa.text("SELECT pg_catalog.pg_postmaster_start_time()"))
        )
    return revision, epoch


def _event_document(event: EffectEvent) -> dict[str, Any]:
    document = asdict(event)
    document["event_type"] = event.event_type.value
    document["db_recorded_at"] = event.db_recorded_at.isoformat()
    return document


def _deduplicated_chain(events: list[EffectEvent]) -> list[EffectEvent]:
    by_hash: dict[str, EffectEvent] = {}
    for event in events:
        by_hash[event.event_hash] = event
    return sorted(by_hash.values(), key=lambda item: item.event_seq)


def _verify_recorded_chain(events: list[EffectEvent]) -> None:
    if not events or events[0].event_seq != 1:
        raise ChronosProductionError("CHRONOS_CANARY_CHAIN_INCOMPLETE")
    if events[0].event_type is not EffectEventType.EFFECT_RESERVED:
        raise ChronosProductionError("CHRONOS_CANARY_CHAIN_INCOMPLETE")
    if events[0].previous_event_hash is None:
        raise ChronosProductionError("CHRONOS_CANARY_AUTHORITY_GRANT_HASH_MISSING")
    for previous, current in zip(events, events[1:], strict=False):
        if current.event_seq != previous.event_seq + 1:
            raise ChronosProductionError("CHRONOS_CANARY_EVENT_SEQUENCE_INVALID")
        if current.previous_event_hash != previous.event_hash:
            raise ChronosProductionError("CHRONOS_CANARY_HASH_CHAIN_INVALID")


def execute_canary(output: Path) -> dict[str, Any]:
    if _context("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    if _context("GITHUB_REF") != EXPECTED_REF:
        raise ChronosProductionError("CHRONOS_REF_MISMATCH")
    github_sha = require_sha(_context("GITHUB_SHA"), field="github_sha")
    workflow_sha = require_sha(
        _context("GITHUB_WORKFLOW_SHA"), field="github_workflow_sha"
    )
    expected_main = require_sha(
        _context("CHRONOS_EXPECTED_MAIN_SHA"), field="expected_main_sha"
    )
    if github_sha != expected_main:
        raise ChronosProductionError("CHRONOS_MAIN_SHA_MISMATCH")
    nonce = require_hash(
        _required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
        field="generation_nonce",
    )
    expected_generation = require_hash(
        _context("CHRONOS_EXPECTED_GENERATION_HASH"),
        field="expected_generation_hash",
    )
    if generation_hash(nonce) != expected_generation:
        raise ChronosProductionError("CHRONOS_GENERATION_HASH_MISMATCH")
    if _context("CHRONOS_OFFLINE_GUARDS_VERIFIED") != "true":
        raise ChronosProductionError("CHRONOS_OFFLINE_GUARDS_REQUIRED")

    authority_url = _required("CHRONOS_AUTHORITY_DATABASE_URL")
    runtime_url = _required("CHRONOS_RUNTIME_DATABASE_URL")
    reader_url = _required("CHRONOS_READER_DATABASE_URL")
    authority_target = validate_direct_postgres_url(authority_url)
    runtime_target = validate_direct_postgres_url(runtime_url)
    reader_target = validate_direct_postgres_url(reader_url)
    targets = {
        (target.host, target.port, target.database, target.sslmode)
        for target in (authority_target, runtime_target, reader_target)
    }
    if len(targets) != 1:
        raise ChronosProductionError("CHRONOS_SCOPED_DATABASE_TARGET_MISMATCH")

    authority_engine = build_engine(authority_url)
    runtime_engine = build_engine(runtime_url)
    reader_engine = build_engine(reader_url)
    try:
        revision, server_epoch = _revision_and_epoch(reader_engine)
        if revision != EXPECTED_AFTER_REVISION:
            raise ChronosProductionError("CHRONOS_CANARY_REVISION_MISMATCH")
        accounting_before = _accounting(reader_engine)
        identity = GitHubRunIdentity(
            github_run_id=int(_context("GITHUB_RUN_ID")),
            github_run_attempt=int(_context("GITHUB_RUN_ATTEMPT")),
            github_sha=github_sha,
            github_workflow_ref=_context("GITHUB_WORKFLOW_REF"),
            github_workflow_sha=workflow_sha,
            github_repository=EXPECTED_REPOSITORY,
            github_ref=EXPECTED_REF,
        )
        base_payload = {
            "schema_version": "chronos-provider-free-canary-payload-v3",
            "synthetic": True,
            "football_data": False,
            "provider": None,
            "github_run_id": identity.github_run_id,
            "github_run_attempt": identity.github_run_attempt,
            "github_sha": identity.github_sha,
            "github_workflow_sha": identity.github_workflow_sha,
        }
        object_operation_id = hashlib.sha256(
            b"chronos-provider-free-canary-object-v3\0" + _canonical(base_payload)
        ).hexdigest()
        payload = _canonical(
            {**base_payload, "object_operation_id": object_operation_id}
        )
        key = f"chronos/provider-free-canary/v3/{object_operation_id}.json"
        operation = EffectOperation(
            mission_id="chronos-provider-free-canary-v3",
            identity=identity,
            resource_kind="R2_OBJECT",
            canonical_key=key,
            canonical_payload_hash=hashlib.sha256(payload).hexdigest(),
            code_revision=github_sha,
        )
        issuer = PostgresAuthorityIssuer(
            SQLAlchemyPostgresFunctionClient(authority_engine)
        )
        base_ledger = PostgresEffectLedger(
            SQLAlchemyPostgresFunctionClient(runtime_engine)
        )
        ledger = RecordingLedger(base_ledger)
        store = CountingStore(ChronosR2ConditionalStore.from_environment(os.environ))
        executor = AttributableR2EffectExecutor(ledger=ledger, store=store)
        authority_id = issuer.issue_authority(
            mission_id=operation.mission_id,
            identity=identity,
            generation_token=nonce,
            ttl_seconds=900,
            code_revision=github_sha,
        )
        receipt = base_ledger.claim_effect_authority(
            authority_id=authority_id,
            operation=operation,
            generation_token=nonce,
        )
        reserved = base_ledger.latest_event(operation.operation_id)
        if reserved is None:
            raise ChronosProductionError("CHRONOS_CANARY_RESERVATION_MISSING")
        ledger.events.append(reserved)
        first = executor.dispatch_reserved(
            authority_id=authority_id,
            authority_receipt_hash=receipt.authority_receipt_hash,
            operation=operation,
            generation_token=nonce,
            payload=payload,
        )
        first_counters = store.counters()
        first_event_hash = first.event.event_hash
        second = executor.dispatch_reserved(
            authority_id=authority_id,
            authority_receipt_hash=receipt.authority_receipt_hash,
            operation=operation,
            generation_token=nonce,
            payload=payload,
        )
        second_counters = store.counters()
        if second_counters != first_counters:
            raise ChronosProductionError("CHRONOS_REPLAY_EMITTED_NETWORK")
        if second.event.event_hash != first_event_hash:
            raise ChronosProductionError("CHRONOS_REPLAY_STATE_DIVERGED")
        if first_counters["put"] != 1 or first_counters["get"] > 1:
            raise ChronosProductionError("CHRONOS_CANARY_NETWORK_BUDGET_INVALID")
        if any(first_counters[name] != 0 for name in ("list", "head", "delete")):
            raise ChronosProductionError("CHRONOS_CANARY_FORBIDDEN_R2_OPERATION")
        chain = _deduplicated_chain(ledger.events)
        _verify_recorded_chain(chain)
        accounting_after = _accounting(reader_engine)
        if first.event.event_type in TERMINAL_READY:
            verdict = "CHRONOS_PROVIDER_FREE_CANARY_READY"
        elif first.event.event_type in TERMINAL_PENDING:
            verdict = "CHRONOS_PROVIDER_FREE_CANARY_PENDING_HONEST"
        else:
            verdict = "CHRONOS_PROVIDER_FREE_CANARY_FAILED"
        result: dict[str, Any] = {
            "schema_version": "chronos-provider-free-canary-v3",
            "verdict": verdict,
            "run": identity.github_run_id,
            "attempt": identity.github_run_attempt,
            "sha": identity.github_sha,
            "workflow_sha": identity.github_workflow_sha,
            "workflow_ref": identity.github_workflow_ref,
            "repository": identity.github_repository,
            "ref": identity.github_ref,
            "revision": revision,
            "server_epoch": server_epoch,
            "generation_hash": expected_generation,
            "authority_id": authority_id,
            "authority_receipt_hash": receipt.authority_receipt_hash,
            "operation_id": operation.operation_id,
            "object_operation_id": object_operation_id,
            "object_key": key,
            "payload_hash": operation.canonical_payload_hash,
            "terminal_event": first.event.event_type.value,
            "events_observed": [_event_document(event) for event in chain],
            "authority_grant_hash": chain[0].previous_event_hash,
            "accounting_before": accounting_before,
            "accounting_after": accounting_after,
            "r2": first_counters,
            "replay": {
                "new_authorities": 0,
                "new_reservations": 0,
                "new_put": 0,
                "new_get": 0,
                "same_terminal_event_hash": True,
            },
            "offline_negative_matrix": {
                "expiry": "REFUSED_BEFORE_NETWORK",
                "run_id": "REFUSED_BEFORE_NETWORK",
                "run_attempt": "REFUSED_BEFORE_NETWORK",
                "sha": "REFUSED_BEFORE_NETWORK",
                "workflow_sha": "REFUSED_BEFORE_NETWORK",
                "repository": "REFUSED_BEFORE_NETWORK",
                "ref": "REFUSED_BEFORE_NETWORK",
                "generation": "REFUSED_BEFORE_NETWORK",
                "server_epoch": "REFUSED_BEFORE_NETWORK",
                "restored_authority": "RESTORED_AUTHORITY_REJECTED",
            },
            "provider_calls": 0,
            "odds_credits": 0,
            "football_payloads": 0,
            "r2_deletes": 0,
            "purchases": 0,
        }
    finally:
        authority_engine.dispose()
        runtime_engine.dispose()
        reader_engine.dispose()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    output = Path(_context("CHRONOS_CANARY_REPORT"))
    try:
        result = execute_canary(output)
    except Exception as error:
        code = str(error) if isinstance(error, ChronosProductionError) else (
            "CHRONOS_PROVIDER_FREE_CANARY_FAILED"
        )
        print(f"CHRONOS_PROVIDER_FREE_CANARY_FAILED:{code}")
        raise SystemExit(1) from None
    print(str(result["verdict"]))


if __name__ == "__main__":
    main()
