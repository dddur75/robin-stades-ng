"""Append-only Public Evidence Ledger V2 with a deterministic hash chain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class EvidenceEventKind(StrEnum):
    HYPOTHESIS_REGISTERED = "HYPOTHESIS_REGISTERED"
    DATA_GATE_EVALUATED = "DATA_GATE_EVALUATED"
    PATTERN_REJECTED = "PATTERN_REJECTED"
    PATTERN_PROMOTED_TO_WATCHLIST = "PATTERN_PROMOTED_TO_WATCHLIST"
    PATTERN_PROMOTED_TO_SHADOW_CANDIDATE = (
        "PATTERN_PROMOTED_TO_SHADOW_CANDIDATE"
    )
    SHADOW_DECISION = "SHADOW_DECISION"
    SETTLEMENT = "SETTLEMENT"


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    sequence_no: int
    event_kind: EvidenceEventKind
    recorded_at: str
    code_revision: str
    dataset_hashes: tuple[str, ...]
    status: str
    reason: str
    payload: dict[str, object]
    previous_hash: str
    record_hash: str


def _hash_payload(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class PublicEvidenceLedgerV2:
    def __init__(self) -> None:
        self._events: list[EvidenceEvent] = []

    @property
    def events(self) -> tuple[EvidenceEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        event_kind: EvidenceEventKind,
        code_revision: str,
        dataset_hashes: tuple[str, ...],
        status: str,
        reason: str,
        payload: dict[str, object] | None = None,
        recorded_at: datetime | None = None,
    ) -> EvidenceEvent:
        sequence_no = len(self._events)
        previous_hash = self._events[-1].record_hash if self._events else "0" * 64
        timestamp = (recorded_at or datetime.now(UTC)).astimezone(UTC).isoformat()
        body: dict[str, object] = {
            "sequence_no": sequence_no,
            "event_kind": event_kind.value,
            "recorded_at": timestamp,
            "code_revision": code_revision,
            "dataset_hashes": list(dataset_hashes),
            "status": status,
            "reason": reason,
            "payload": payload or {},
            "previous_hash": previous_hash,
        }
        event = EvidenceEvent(
            sequence_no=sequence_no,
            event_kind=event_kind,
            recorded_at=timestamp,
            code_revision=code_revision,
            dataset_hashes=dataset_hashes,
            status=status,
            reason=reason,
            payload=payload or {},
            previous_hash=previous_hash,
            record_hash=_hash_payload(body),
        )
        self._events.append(event)
        return event

    def audit(self) -> dict[str, object]:
        previous_hash = "0" * 64
        for position, event in enumerate(self._events):
            body = {
                key: value
                for key, value in asdict(event).items()
                if key != "record_hash"
            }
            body["event_kind"] = event.event_kind.value
            body["dataset_hashes"] = list(event.dataset_hashes)
            if (
                event.sequence_no != position
                or event.previous_hash != previous_hash
                or event.record_hash != _hash_payload(body)
            ):
                return {
                    "status": "HASH_CHAIN_INVALID",
                    "events": len(self._events),
                    "failed_sequence": position,
                }
            previous_hash = event.record_hash
        return {
            "status": "HASH_CHAIN_VERIFIED",
            "events": len(self._events),
            "head_hash": previous_hash,
        }

    def write_jsonl(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError("PUBLIC_EVIDENCE_LEDGER_APPEND_ONLY")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(
                    {
                        **asdict(event),
                        "event_kind": event.event_kind.value,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for event in self._events
            ),
            encoding="utf-8",
        )
