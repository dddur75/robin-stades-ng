"""Append-only hash-chained hypothesis evidence ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from robin.hypothesis_intelligence.contracts import (
    HypothesisEventKind,
    canonical_sha256,
    utc,
)

ZERO_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class HypothesisLedgerEvent:
    event_id: str
    sequence_no: int
    kind: HypothesisEventKind
    recorded_at: datetime
    code_revision: str
    hypothesis_id: str
    evidence_hashes: tuple[str, ...]
    details: dict[str, object]
    previous_hash: str
    automatic: bool = True
    production_locked: bool = True
    real_bets: bool = False
    promoted: bool = False

    def __post_init__(self) -> None:
        utc(self.recorded_at, field_name="recorded_at")
        if (
            self.sequence_no < 0
            or len(self.previous_hash) != 64
            or any(len(item) != 64 for item in self.evidence_hashes)
            or not self.production_locked
            or self.real_bets
            or self.promoted
        ):
            raise ValueError("HYPOTHESIS_LEDGER_EVENT_INVALID")
        if self.kind is HypothesisEventKind.HYPOTHESIS_VALIDATED and self.automatic:
            raise ValueError("AUTOMATIC_HYPOTHESIS_VALIDATION_FORBIDDEN")

    @property
    def event_hash(self) -> str:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["recorded_at"] = self.recorded_at.isoformat()
        return canonical_sha256(payload)


class HypothesisLedger:
    def __init__(self) -> None:
        self._events: list[HypothesisLedgerEvent] = []

    @property
    def events(self) -> tuple[HypothesisLedgerEvent, ...]:
        return tuple(self._events)

    @property
    def head_hash(self) -> str:
        return self._events[-1].event_hash if self._events else ZERO_HASH

    def append(
        self,
        *,
        kind: HypothesisEventKind,
        recorded_at: datetime,
        code_revision: str,
        hypothesis_id: str,
        evidence_hashes: tuple[str, ...],
        details: dict[str, object],
        automatic: bool = True,
    ) -> HypothesisLedgerEvent:
        identity = canonical_sha256(
            {
                "sequence_no": len(self._events),
                "kind": kind.value,
                "hypothesis_id": hypothesis_id,
                "evidence_hashes": evidence_hashes,
                "previous_hash": self.head_hash,
            }
        )
        event = HypothesisLedgerEvent(
            event_id=f"hypothesis-event-{identity}",
            sequence_no=len(self._events),
            kind=kind,
            recorded_at=recorded_at,
            code_revision=code_revision,
            hypothesis_id=hypothesis_id,
            evidence_hashes=evidence_hashes,
            details=details,
            previous_hash=self.head_hash,
            automatic=automatic,
        )
        self._events.append(event)
        return event

    def audit(self) -> dict[str, object]:
        previous = ZERO_HASH
        for index, event in enumerate(self._events):
            if event.sequence_no != index or event.previous_hash != previous:
                raise ValueError("HYPOTHESIS_LEDGER_CHAIN_INVALID")
            previous = event.event_hash
        return {
            "events": len(self._events),
            "head_hash": previous,
            "valid": True,
            "automatic_validation_events": sum(
                event.kind is HypothesisEventKind.HYPOTHESIS_VALIDATED and event.automatic
                for event in self._events
            ),
        }


__all__ = ["HypothesisLedger", "HypothesisLedgerEvent", "ZERO_HASH"]
