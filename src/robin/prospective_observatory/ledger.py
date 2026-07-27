"""Public Evidence Ledger V3 for capture evidence, never betting decisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureAttempt,
    CaptureReceipt,
    CaptureWindow,
    ProspectiveFixture,
    canonical_sha256,
    ensure_utc,
)
from robin.prospective_observatory.gates import GateEvaluation, GateStatus

GENESIS_HASH = "0" * 64


class EvidenceEventKindV3(StrEnum):
    FIXTURE_REGISTERED = "FIXTURE_REGISTERED"
    CAPTURE_WINDOW_SCHEDULED = "CAPTURE_WINDOW_SCHEDULED"
    CAPTURE_ATTEMPTED = "CAPTURE_ATTEMPTED"
    CAPTURE_SUCCEEDED = "CAPTURE_SUCCEEDED"
    CAPTURE_EMPTY = "CAPTURE_EMPTY"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    CAPTURE_WINDOW_MISSED = "CAPTURE_WINDOW_MISSED"
    TEMPORAL_GATE_PASSED = "TEMPORAL_GATE_PASSED"
    TEMPORAL_GATE_FAILED = "TEMPORAL_GATE_FAILED"
    DATASET_VERSION_FROZEN = "DATASET_VERSION_FROZEN"


@dataclass(frozen=True, slots=True)
class EvidenceEventV3:
    sequence_no: int
    event_kind: EvidenceEventKindV3
    recorded_at: str
    code_revision: str
    fixture_id: str | None
    evidence_hashes: tuple[str, ...]
    status: str
    reason: str
    payload: dict[str, object]
    previous_hash: str
    record_hash: str
    production_status: str = "PRODUCTION_LOCKED"
    real_bets: bool = False
    social_publishing_enabled: bool = False


def _event_hash(body: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _assert_no_betting_payload(value: object, *, path: str = "payload") -> None:
    forbidden_tokens = {"bet", "betting", "decision", "stake", "wager"}
    if isinstance(value, dict):
        for key, nested in value.items():
            split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
            normalized_tokens = {
                token
                for token in re.split(r"[^a-z0-9]+", split_camel.casefold())
                if token
            }
            compact = "".join(normalized_tokens)
            if normalized_tokens & forbidden_tokens or compact.startswith(
                ("betdecision", "realbet", "stakeamount", "wageramount")
            ):
                raise ValueError(
                    f"JALON12_LEDGER_BETTING_FIELD_FORBIDDEN:{path}.{key}"
                )
            _assert_no_betting_payload(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_no_betting_payload(nested, path=f"{path}[{index}]")


class PublicEvidenceLedgerV3:
    def __init__(self) -> None:
        self._events: list[EvidenceEventV3] = []

    @property
    def events(self) -> tuple[EvidenceEventV3, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        event_kind: EvidenceEventKindV3,
        recorded_at: datetime,
        code_revision: str,
        fixture_id: str | None,
        evidence_hashes: tuple[str, ...],
        status: str,
        reason: str,
        payload: dict[str, object] | None = None,
    ) -> EvidenceEventV3:
        _assert_no_betting_payload(payload or {})
        if any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in evidence_hashes
        ):
            raise ValueError("JALON12_LEDGER_EVIDENCE_HASH_INVALID")
        timestamp = ensure_utc(recorded_at, field="recorded_at").isoformat()
        previous_hash = self._events[-1].record_hash if self._events else GENESIS_HASH
        body: dict[str, object] = {
            "sequence_no": len(self._events),
            "event_kind": event_kind.value,
            "recorded_at": timestamp,
            "code_revision": code_revision,
            "fixture_id": fixture_id,
            "evidence_hashes": list(evidence_hashes),
            "status": status,
            "reason": reason,
            "payload": payload or {},
            "previous_hash": previous_hash,
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "social_publishing_enabled": False,
        }
        event = EvidenceEventV3(
            sequence_no=len(self._events),
            event_kind=event_kind,
            recorded_at=timestamp,
            code_revision=code_revision,
            fixture_id=fixture_id,
            evidence_hashes=evidence_hashes,
            status=status,
            reason=reason,
            payload=payload or {},
            previous_hash=previous_hash,
            record_hash=_event_hash(body),
        )
        self._events.append(event)
        return event

    def audit(self) -> dict[str, object]:
        previous_hash = GENESIS_HASH
        for sequence_no, event in enumerate(self._events):
            body = asdict(event)
            record_hash = str(body.pop("record_hash"))
            body["event_kind"] = event.event_kind.value
            body["evidence_hashes"] = list(event.evidence_hashes)
            if (
                event.sequence_no != sequence_no
                or event.previous_hash != previous_hash
                or record_hash != _event_hash(body)
                or event.real_bets
                or event.social_publishing_enabled
                or event.production_status != "PRODUCTION_LOCKED"
            ):
                return {
                    "status": "HASH_CHAIN_INVALID",
                    "events": len(self._events),
                    "failed_sequence": sequence_no,
                }
            previous_hash = event.record_hash
        return {
            "status": "HASH_CHAIN_VERIFIED",
            "events": len(self._events),
            "head_hash": previous_hash,
        }

    def write_jsonl(self, path: Path) -> None:
        if path.exists():
            raise FileExistsError("PUBLIC_EVIDENCE_LEDGER_V3_APPEND_ONLY")
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


def build_observatory_ledger(
    *,
    fixtures: Iterable[ProspectiveFixture],
    windows: Iterable[CaptureWindow],
    attempts: Iterable[CaptureAttempt],
    receipts: Iterable[CaptureReceipt],
    gates: Iterable[GateEvaluation],
    frozen_at: datetime,
    code_revision: str,
) -> PublicEvidenceLedgerV3:
    """Reconstruct the compact V3 evidence chain from durable state.

    The function is deliberately provider-free and deterministic for the same
    state and ``frozen_at``. It emits evidence events only—never candidates,
    betting decisions, stakes, or settlements.
    """

    frozen_at = ensure_utc(frozen_at, field="frozen_at")
    fixture_rows = tuple(fixtures)
    window_rows = tuple(windows)
    attempt_rows = tuple(attempts)
    receipt_rows = tuple(receipts)
    gate_rows = tuple(gates)
    receipts_by_window = {
        receipt.window_id: receipt
        for receipt in receipt_rows
        if receipt.window_id is not None
    }
    events: list[
        tuple[
            datetime,
            int,
            EvidenceEventKindV3,
            str,
            str | None,
            tuple[str, ...],
            str,
            str,
            dict[str, object],
        ]
    ] = []

    for fixture in fixture_rows:
        events.append(
            (
                fixture.registered_at,
                0,
                EvidenceEventKindV3.FIXTURE_REGISTERED,
                fixture.code_revision,
                fixture.fixture_id,
                (fixture.registry_hash,),
                "REGISTERED",
                "PROVIDER_FIXTURE_VERSION_RETAINED",
                {"competition": fixture.competition, "season": fixture.season},
            )
        )
    for window in window_rows:
        window_hash = canonical_sha256(window.model_dump(mode="json"))
        events.append(
            (
                window.scheduled_at,
                1,
                EvidenceEventKindV3.CAPTURE_WINDOW_SCHEDULED,
                window.code_revision,
                window.fixture_id,
                (window_hash,),
                window.status.value,
                "PRE_REGISTERED_CAPTURE_WINDOW",
                {"family": window.family.value, "label": window.label},
            )
        )
        if window.cutoff_at <= frozen_at and window.window_id not in receipts_by_window:
            events.append(
                (
                    window.cutoff_at,
                    4,
                    EvidenceEventKindV3.CAPTURE_WINDOW_MISSED,
                    window.code_revision,
                    window.fixture_id,
                    (window_hash,),
                    AvailabilityStatus.MISSED_WINDOW.value,
                    "NO_ADMISSIBLE_RECEIPT_BEFORE_CUTOFF",
                    {"family": window.family.value, "label": window.label},
                )
            )
    for attempt in attempt_rows:
        attempt_hash = canonical_sha256(attempt.model_dump(mode="json"))
        events.append(
            (
                attempt.attempted_at,
                2,
                EvidenceEventKindV3.CAPTURE_ATTEMPTED,
                attempt.code_revision,
                attempt.fixture_id,
                (attempt_hash,),
                attempt.status.value,
                "DURABLE_PROVIDER_ATTEMPT",
                {
                    "family": attempt.family.value,
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        receipt = receipts_by_window.get(attempt.window_id)
        evidence_hash = receipt.receipt_hash if receipt is not None else attempt_hash
        if attempt.status is AvailabilityStatus.CAPTURED:
            kind = EvidenceEventKindV3.CAPTURE_SUCCEEDED
        elif attempt.status is AvailabilityStatus.CAPTURED_EMPTY:
            kind = EvidenceEventKindV3.CAPTURE_EMPTY
        else:
            kind = EvidenceEventKindV3.CAPTURE_FAILED
        events.append(
            (
                attempt.attempted_at,
                3,
                kind,
                attempt.code_revision,
                attempt.fixture_id,
                (evidence_hash,),
                attempt.status.value,
                attempt.error_code or "CAPTURE_ATTEMPT_CLASSIFIED",
                {"family": attempt.family.value},
            )
        )
    for evaluation in gate_rows:
        evidence_hash = canonical_sha256(
            {
                "gate": evaluation.gate.value,
                "fixture_id": evaluation.fixture_id,
                "status": evaluation.status.value,
                "observations": evaluation.observations,
                "reason": evaluation.reason,
                "evidence": evaluation.evidence,
            }
        )
        events.append(
            (
                frozen_at,
                5,
                (
                    EvidenceEventKindV3.TEMPORAL_GATE_PASSED
                    if evaluation.status is GateStatus.PASSED
                    else EvidenceEventKindV3.TEMPORAL_GATE_FAILED
                ),
                code_revision,
                evaluation.fixture_id,
                (evidence_hash,),
                evaluation.status.value,
                evaluation.reason,
                {"gate": evaluation.gate.value},
            )
        )
    dataset_hash = canonical_sha256(
        sorted(receipt.receipt_hash for receipt in receipt_rows)
    )
    events.append(
        (
            frozen_at,
            6,
            EvidenceEventKindV3.DATASET_VERSION_FROZEN,
            code_revision,
            None,
            (dataset_hash,),
            "FROZEN",
            "PROSPECTIVE_EVIDENCE_SNAPSHOT",
            {
                "fixtures": len(fixture_rows),
                "receipts": len(receipt_rows),
                "dataset_hash": dataset_hash,
            },
        )
    )

    ledger = PublicEvidenceLedgerV3()
    for (
        recorded_at,
        _,
        event_kind,
        revision,
        fixture_id,
        evidence_hashes,
        status,
        reason,
        payload,
    ) in sorted(events, key=lambda item: (item[0], item[1], item[4] or "", item[2].value)):
        ledger.append(
            event_kind=event_kind,
            recorded_at=recorded_at,
            code_revision=revision,
            fixture_id=fixture_id,
            evidence_hashes=evidence_hashes,
            status=status,
            reason=reason,
            payload=payload,
        )
    return ledger


def observatory_ledger_summary(
    ledger: PublicEvidenceLedgerV3,
) -> dict[str, object]:
    audit = ledger.audit()
    counts = Counter(event.event_kind.value for event in ledger.events)
    return {
        "schema_version": "public-evidence-ledger-v3",
        "status": audit["status"],
        "events": len(ledger.events),
        "head_hash": audit.get("head_hash"),
        "event_counts": dict(sorted(counts.items())),
        "bet_decisions": 0,
        "real_bets": False,
        "social_publishing_enabled": False,
    }
