"""Minimal policy contract for Council V3.1.

This module decides whether one evidence transition is authorized.  It does not
schedule work, execute workloads, rotate authority, or persist remote state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence, cast


class EvidenceStage(StrEnum):
    """Evidence levels understood by the minimal policy."""

    E1 = "E1"
    E2 = "E2"
    E3A = "E3A"
    E3B = "E3B"
    E4 = "E4"


STAGE_SEQUENCE: tuple[EvidenceStage, ...] = (
    EvidenceStage.E1,
    EvidenceStage.E2,
    EvidenceStage.E3A,
    EvidenceStage.E3B,
    EvidenceStage.E4,
)
_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_SEQUENCE)}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class DecisionState(StrEnum):
    """The five and only five Council level decisions."""

    PASS_AND_SCALE = "PASS_AND_SCALE"
    PASS_AND_HOLD = "PASS_AND_HOLD"
    FAIL_AND_REDESIGN = "FAIL_AND_REDESIGN"
    FAIL_AND_STOP = "FAIL_AND_STOP"
    BLOCKED_EXTERNAL_ACTION = "BLOCKED_EXTERNAL_ACTION"


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _require_strict_bool(value: bool, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a bool")


@dataclass(frozen=True, slots=True)
class MissionManifest:
    """Immutable authorization envelope for one evidence mission."""

    mission_id: str
    authorized_stages: tuple[EvidenceStage, ...]
    maximum_stage: EvidenceStage
    external_effects: tuple[str, ...]
    compute_budget: int
    time_budget: int
    source_hash: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.mission_id, str) or not self.mission_id.strip():
            raise ValueError("mission_id must be a non-empty string")

        stages = tuple(self.authorized_stages)
        if not stages or any(not isinstance(stage, EvidenceStage) for stage in stages):
            raise ValueError("authorized_stages must contain EvidenceStage values")
        if len(stages) != len(set(stages)):
            raise ValueError("authorized_stages must not contain duplicates")
        if stages != tuple(sorted(stages, key=_STAGE_INDEX.__getitem__)):
            raise ValueError("authorized_stages must follow the evidence ladder")
        if stages != STAGE_SEQUENCE[: len(stages)]:
            raise ValueError("authorized_stages must be a contiguous prefix from E1")
        if not isinstance(self.maximum_stage, EvidenceStage):
            raise TypeError("maximum_stage must be an EvidenceStage")
        if self.maximum_stage not in stages:
            raise ValueError("maximum_stage must be authorized")
        if any(_STAGE_INDEX[stage] > _STAGE_INDEX[self.maximum_stage] for stage in stages):
            raise ValueError("authorized_stages cannot exceed maximum_stage")
        object.__setattr__(self, "authorized_stages", stages)

        effects = tuple(sorted(set(self.external_effects)))
        if any(not isinstance(effect, str) or not effect.strip() for effect in effects):
            raise ValueError("external_effects must contain non-empty strings")
        object.__setattr__(self, "external_effects", effects)

        if type(self.compute_budget) is not int or self.compute_budget <= 0:
            raise ValueError("compute_budget must be a positive integer")
        if type(self.time_budget) is not int or self.time_budget <= 0:
            raise ValueError("time_budget must be a positive integer")
        _require_sha256(self.source_hash, "source_hash")
        if not isinstance(self.expires_at, datetime) or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    """Facts supplied to the policy for one requested transition."""

    current_stage: EvidenceStage
    next_stage: EvidenceStage
    current_stage_proven: bool
    criteria_satisfied: bool
    critical_veto_open: bool = False
    source_available: bool = True
    observed_source_hash: str = ""
    compute_used: int = 0
    time_used: int = 0
    requested_external_effects: tuple[str, ...] = ()
    separate_external_authorization_proven: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.current_stage, EvidenceStage):
            raise TypeError("current_stage must be an EvidenceStage")
        if not isinstance(self.next_stage, EvidenceStage):
            raise TypeError("next_stage must be an EvidenceStage")
        _require_strict_bool(self.current_stage_proven, "current_stage_proven")
        _require_strict_bool(self.criteria_satisfied, "criteria_satisfied")
        _require_strict_bool(self.critical_veto_open, "critical_veto_open")
        _require_strict_bool(self.source_available, "source_available")
        _require_strict_bool(
            self.separate_external_authorization_proven,
            "separate_external_authorization_proven",
        )
        if self.source_available:
            _require_sha256(self.observed_source_hash, "observed_source_hash")
        elif self.observed_source_hash:
            _require_sha256(self.observed_source_hash, "observed_source_hash")
        if type(self.compute_used) is not int or self.compute_used < 0:
            raise ValueError("compute_used must be a non-negative integer")
        if type(self.time_used) is not int or self.time_used < 0:
            raise ValueError("time_used must be a non-negative integer")

        effects = tuple(sorted(set(self.requested_external_effects)))
        if any(not isinstance(effect, str) or not effect.strip() for effect in effects):
            raise ValueError("requested_external_effects must contain non-empty strings")
        object.__setattr__(self, "requested_external_effects", effects)


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """A deterministic policy decision; it never executes the transition."""

    state: DecisionState
    current_stage: EvidenceStage
    next_stage: EvidenceStage
    reason: str

    @property
    def permits_scale(self) -> bool:
        return self.state is DecisionState.PASS_AND_SCALE


def validate_transition(
    manifest: MissionManifest,
    request: TransitionRequest,
    *,
    evaluated_at: datetime | None = None,
) -> TransitionDecision:
    """Validate one immediate transition inside an immutable mission envelope."""

    now = evaluated_at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("evaluated_at must be a timezone-aware datetime")

    if (
        request.requested_external_effects
        and not request.separate_external_authorization_proven
    ):
        return TransitionDecision(
            DecisionState.BLOCKED_EXTERNAL_ACTION,
            request.current_stage,
            request.next_stage,
            "separate_external_authorization_required",
        )
    forbidden_effects = set(request.requested_external_effects) - set(manifest.external_effects)
    if forbidden_effects:
        return TransitionDecision(
            DecisionState.BLOCKED_EXTERNAL_ACTION,
            request.current_stage,
            request.next_stage,
            "external_effect_default_deny:" + ",".join(sorted(forbidden_effects)),
        )
    if not request.source_available:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "required_source_absent",
        )
    if request.observed_source_hash != manifest.source_hash:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "source_hash_mismatch",
        )
    if now >= manifest.expires_at:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "mission_expired",
        )
    if request.current_stage not in manifest.authorized_stages:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "current_stage_not_authorized",
        )
    if _STAGE_INDEX[request.next_stage] > _STAGE_INDEX[manifest.maximum_stage]:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "maximum_stage_exceeded",
        )
    if request.next_stage not in manifest.authorized_stages:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "next_stage_not_authorized",
        )
    if _STAGE_INDEX[request.next_stage] != _STAGE_INDEX[request.current_stage] + 1:
        return TransitionDecision(
            DecisionState.FAIL_AND_STOP,
            request.current_stage,
            request.next_stage,
            "non_adjacent_stage",
        )
    if not request.current_stage_proven:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "current_stage_not_proven",
        )
    if not request.criteria_satisfied:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "current_stage_criteria_not_met",
        )
    if request.critical_veto_open:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "critical_veto_open",
        )
    if request.compute_used > manifest.compute_budget:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "compute_budget_exceeded",
        )
    if request.time_used > manifest.time_budget:
        return TransitionDecision(
            DecisionState.PASS_AND_HOLD,
            request.current_stage,
            request.next_stage,
            "time_budget_exceeded",
        )
    return TransitionDecision(
        DecisionState.PASS_AND_SCALE,
        request.current_stage,
        request.next_stage,
        "immediate_transition_authorized",
    )


@dataclass(frozen=True, slots=True)
class FailureKey:
    """Canonical similarity key required by the minimal retry policy."""

    failure_taxonomy: str
    root_cause_signature: str
    scope: str

    def __post_init__(self) -> None:
        for field_name in ("failure_taxonomy", "root_cause_signature", "scope"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class FailureRecord:
    """One observed failure, grouped by the exact canonical three-part key."""

    key: FailureKey
    architecture_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, FailureKey):
            raise TypeError("key must be a FailureKey")
        _require_sha256(self.architecture_hash, "architecture_hash")


class FailureAction(StrEnum):
    """Operational instruction produced by the two-failure rule."""

    MINIMAL_FIX = "MINIMAL_FIX"
    REDESIGN_REQUIRED = "REDESIGN_REQUIRED"
    IDENTICAL_ATTEMPT_FORBIDDEN = "IDENTICAL_ATTEMPT_FORBIDDEN"


@dataclass(frozen=True, slots=True)
class FailureResolution:
    """Bounded response to repeated similar failures."""

    action: FailureAction
    decision: DecisionState
    return_stage: EvidenceStage | None
    retry_allowed: bool
    similar_failure_count: int


def apply_two_failure_rule(
    history: Sequence[FailureRecord],
    *,
    key: FailureKey,
    proposed_architecture_hash: str | None = None,
) -> FailureResolution:
    """Apply minimal-fix, redesign, and unchanged-third-attempt rules.

    ``history`` contains failures already observed.  After two matching failures,
    callers may inspect the redesign decision or ask whether a proposed third
    architecture is unchanged.
    """

    if not isinstance(key, FailureKey):
        raise TypeError("key must be a FailureKey")
    if proposed_architecture_hash is not None:
        _require_sha256(proposed_architecture_hash, "proposed_architecture_hash")

    similar = tuple(record for record in history if record.key == key)
    if not similar:
        raise ValueError("history must contain at least one matching failure")
    if len(similar) == 1:
        return FailureResolution(
            FailureAction.MINIMAL_FIX,
            DecisionState.PASS_AND_HOLD,
            None,
            True,
            1,
        )

    unchanged_third_attempt = (
        proposed_architecture_hash is not None
        and proposed_architecture_hash == similar[-1].architecture_hash
    )
    if len(similar) >= 3 or unchanged_third_attempt:
        return FailureResolution(
            FailureAction.IDENTICAL_ATTEMPT_FORBIDDEN,
            DecisionState.FAIL_AND_STOP,
            EvidenceStage.E1,
            False,
            len(similar),
        )
    return FailureResolution(
        FailureAction.REDESIGN_REQUIRED,
        DecisionState.FAIL_AND_REDESIGN,
        EvidenceStage.E1,
        True,
        2,
    )


class JournalEvent(StrEnum):
    """The only event types accepted by the minimal append-only journal."""

    MISSION_AUTHORIZED = "MISSION_AUTHORIZED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_FINISHED = "STAGE_FINISHED"
    DECISION = "DECISION"
    FAILURE = "FAILURE"
    VETO = "VETO"
    REDESIGN = "REDESIGN"


_GENESIS_HASH = "0" * 64


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("journal payload must be finite JSON data") from exc


def _record_hash(
    sequence: int,
    event: JournalEvent,
    payload_json: str,
    previous_hash: str,
) -> str:
    body = {
        "event": event.value,
        "payload": json.loads(payload_json),
        "previous_hash": previous_hash,
        "sequence": sequence,
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class JournalRecord:
    """One immutable record in a deterministic hash chain."""

    sequence: int
    event: JournalEvent
    payload_json: str
    previous_hash: str
    record_hash: str

    @property
    def payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.payload_json))


@dataclass(frozen=True, slots=True)
class HashedJournal:
    """An immutable logical journal; append returns a new hash chain."""

    records: tuple[JournalRecord, ...] = ()

    def __post_init__(self) -> None:
        records = tuple(self.records)
        previous_hash = _GENESIS_HASH
        for expected_sequence, record in enumerate(records, start=1):
            if type(record.sequence) is not int or record.sequence != expected_sequence:
                raise ValueError("journal sequence is not append-only")
            if not isinstance(record.event, JournalEvent):
                raise ValueError("journal contains a forbidden event type")
            if record.previous_hash != previous_hash:
                raise ValueError("journal previous_hash chain is invalid")
            try:
                decoded_payload = json.loads(record.payload_json)
            except json.JSONDecodeError as exc:
                raise ValueError("journal payload_json is invalid") from exc
            if not isinstance(decoded_payload, dict):
                raise ValueError("journal payload must be a JSON object")
            if _canonical_json(decoded_payload) != record.payload_json:
                raise ValueError("journal payload_json is not canonical")
            expected_hash = _record_hash(
                record.sequence,
                record.event,
                record.payload_json,
                previous_hash,
            )
            if record.record_hash != expected_hash:
                raise ValueError("journal record hash is invalid")
            previous_hash = record.record_hash
        object.__setattr__(self, "records", records)

    def append(
        self,
        event: JournalEvent,
        payload: Mapping[str, Any],
    ) -> HashedJournal:
        """Return a new journal with exactly one allowed event appended."""

        if not isinstance(event, JournalEvent):
            raise TypeError("event must be a JournalEvent")
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        payload_json = _canonical_json(dict(payload))
        if not isinstance(json.loads(payload_json), dict):
            raise ValueError("journal payload must be a JSON object")
        previous_hash = self.records[-1].record_hash if self.records else _GENESIS_HASH
        sequence = len(self.records) + 1
        record = JournalRecord(
            sequence=sequence,
            event=event,
            payload_json=payload_json,
            previous_hash=previous_hash,
            record_hash=_record_hash(sequence, event, payload_json, previous_hash),
        )
        return HashedJournal(self.records + (record,))

    def to_jsonl(self) -> str:
        """Serialize the validated chain without mutating or writing anything."""

        lines = (
            _canonical_json(
                {
                    "event": record.event.value,
                    "payload": record.payload,
                    "previous_hash": record.previous_hash,
                    "record_hash": record.record_hash,
                    "sequence": record.sequence,
                }
            )
            for record in self.records
        )
        return "\n".join(lines)
