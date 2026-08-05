"""Eleven targeted acceptance cases for the minimal Council V3.1 contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from robin.governance.autoscale import (
    STAGE_SEQUENCE,
    DecisionState,
    EvidenceStage,
    FailureAction,
    FailureKey,
    FailureRecord,
    HashedJournal,
    JournalEvent,
    JournalRecord,
    MissionManifest,
    TransitionRequest,
    apply_two_failure_rule,
    validate_transition,
)

FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
SOURCE_HASH = "a" * 64
ARCHITECTURE_HASH = "b" * 64
REDESIGNED_ARCHITECTURE_HASH = "c" * 64


def mission(
    *,
    maximum_stage: EvidenceStage = EvidenceStage.E4,
    external_effects: tuple[str, ...] = (),
) -> MissionManifest:
    maximum_index = STAGE_SEQUENCE.index(maximum_stage)
    return MissionManifest(
        mission_id="e1-e4-local",
        authorized_stages=STAGE_SEQUENCE[: maximum_index + 1],
        maximum_stage=maximum_stage,
        external_effects=external_effects,
        compute_budget=100,
        time_budget=900,
        source_hash=SOURCE_HASH,
        expires_at=FUTURE,
    )


def transition(
    current_stage: EvidenceStage,
    next_stage: EvidenceStage,
) -> TransitionRequest:
    return TransitionRequest(
        current_stage=current_stage,
        next_stage=next_stage,
        current_stage_proven=True,
        criteria_satisfied=True,
        observed_source_hash=SOURCE_HASH,
    )


def test_e1_to_e2_is_authorized() -> None:
    manifest = mission()

    result = validate_transition(
        manifest,
        transition(EvidenceStage.E1, EvidenceStage.E2),
    )

    assert result.state is DecisionState.PASS_AND_SCALE
    assert result.permits_scale
    assert len(DecisionState) == 5
    with pytest.raises(FrozenInstanceError):
        manifest.maximum_stage = EvidenceStage.E3A  # type: ignore[misc]


def test_e2_to_e3a_is_authorized() -> None:
    result = validate_transition(
        mission(),
        transition(EvidenceStage.E2, EvidenceStage.E3A),
    )

    assert result.state is DecisionState.PASS_AND_SCALE


def test_e3a_to_e3b_is_authorized() -> None:
    result = validate_transition(
        mission(),
        transition(EvidenceStage.E3A, EvidenceStage.E3B),
    )

    assert result.state is DecisionState.PASS_AND_SCALE


def test_e3b_to_e4_is_authorized() -> None:
    result = validate_transition(
        mission(),
        transition(EvidenceStage.E3B, EvidenceStage.E4),
    )

    assert result.state is DecisionState.PASS_AND_SCALE


def test_stage_skip_is_forbidden() -> None:
    result = validate_transition(
        mission(),
        transition(EvidenceStage.E1, EvidenceStage.E3A),
    )

    assert result.state is DecisionState.FAIL_AND_STOP
    assert result.reason == "non_adjacent_stage"


def test_mission_ceiling_is_enforced() -> None:
    result = validate_transition(
        mission(maximum_stage=EvidenceStage.E3A),
        transition(EvidenceStage.E3A, EvidenceStage.E3B),
    )

    assert result.state is DecisionState.PASS_AND_HOLD
    assert result.reason == "maximum_stage_exceeded"
    with pytest.raises(ValueError, match="contiguous prefix"):
        MissionManifest(
            mission_id="invalid-gap",
            authorized_stages=(EvidenceStage.E2, EvidenceStage.E3A),
            maximum_stage=EvidenceStage.E3A,
            external_effects=(),
            compute_budget=100,
            time_budget=900,
            source_hash=SOURCE_HASH,
            expires_at=FUTURE,
        )
    with pytest.raises(TypeError, match="maximum_stage"):
        replace(mission(), maximum_stage="E4")  # type: ignore[arg-type]


def test_external_effect_is_default_denied() -> None:
    request = replace(
        transition(EvidenceStage.E1, EvidenceStage.E2),
        requested_external_effects=("r2_write",),
    )

    result = validate_transition(mission(external_effects=("r2_write",)), request)

    assert result.state is DecisionState.BLOCKED_EXTERNAL_ACTION
    assert result.reason == "separate_external_authorization_required"


def test_absent_required_source_stops_transition() -> None:
    request = replace(
        transition(EvidenceStage.E1, EvidenceStage.E2),
        source_available=False,
    )

    result = validate_transition(mission(), request)

    assert result.state is DecisionState.FAIL_AND_STOP
    assert result.reason == "required_source_absent"


def test_third_unchanged_attempt_is_forbidden_by_two_failure_rule() -> None:
    key = FailureKey("SOURCE_ABSENT", "missing_source_rows", "E1")
    first_failure = FailureRecord(key, ARCHITECTURE_HASH)
    second_failure = FailureRecord(key, ARCHITECTURE_HASH)

    first_outcome = apply_two_failure_rule((first_failure,), key=key)
    second_outcome = apply_two_failure_rule(
        (first_failure, second_failure),
        key=key,
    )
    third_outcome = apply_two_failure_rule(
        (first_failure, second_failure),
        key=key,
        proposed_architecture_hash=ARCHITECTURE_HASH,
    )
    redesigned_outcome = apply_two_failure_rule(
        (first_failure, second_failure),
        key=key,
        proposed_architecture_hash=REDESIGNED_ARCHITECTURE_HASH,
    )

    assert first_outcome.action is FailureAction.MINIMAL_FIX
    assert first_outcome.decision is DecisionState.PASS_AND_HOLD
    assert second_outcome.action is FailureAction.REDESIGN_REQUIRED
    assert second_outcome.decision is DecisionState.FAIL_AND_REDESIGN
    assert second_outcome.return_stage is EvidenceStage.E1
    assert third_outcome.action is FailureAction.IDENTICAL_ATTEMPT_FORBIDDEN
    assert third_outcome.decision is DecisionState.FAIL_AND_STOP
    assert not third_outcome.retry_allowed
    assert redesigned_outcome.action is FailureAction.REDESIGN_REQUIRED
    assert redesigned_outcome.retry_allowed


def test_critical_veto_and_unmet_current_gates_hold_transition() -> None:
    base = transition(EvidenceStage.E1, EvidenceStage.E2)
    blocked_requests = (
        replace(base, critical_veto_open=True),
        replace(base, current_stage_proven=False),
        replace(base, criteria_satisfied=False),
        replace(base, observed_source_hash="d" * 64),
        replace(base, compute_used=101),
        replace(base, time_used=901),
    )

    results = tuple(validate_transition(mission(), request) for request in blocked_requests)

    assert tuple(result.state for result in results) == (
        DecisionState.PASS_AND_HOLD,
        DecisionState.PASS_AND_HOLD,
        DecisionState.PASS_AND_HOLD,
        DecisionState.FAIL_AND_STOP,
        DecisionState.PASS_AND_HOLD,
        DecisionState.PASS_AND_HOLD,
    )
    assert tuple(result.reason for result in results) == (
        "critical_veto_open",
        "current_stage_not_proven",
        "current_stage_criteria_not_met",
        "source_hash_mismatch",
        "compute_budget_exceeded",
        "time_budget_exceeded",
    )


def test_append_only_journal_is_restricted_hashed_and_deterministic() -> None:
    left = HashedJournal().append(
        JournalEvent.MISSION_AUTHORIZED,
        {"mission_id": "e1-e4-local", "budgets": {"time": 900, "compute": 100}},
    )
    right = HashedJournal().append(
        JournalEvent.MISSION_AUTHORIZED,
        {"budgets": {"compute": 100, "time": 900}, "mission_id": "e1-e4-local"},
    )

    assert left.records[0].record_hash == right.records[0].record_hash
    assert left.to_jsonl() == right.to_jsonl()
    assert len(HashedJournal().records) == 0
    assert {event.value for event in JournalEvent} == {
        "MISSION_AUTHORIZED",
        "STAGE_STARTED",
        "STAGE_FINISHED",
        "DECISION",
        "FAILURE",
        "VETO",
        "REDESIGN",
    }

    complete = left
    for event in tuple(JournalEvent)[1:]:
        previous = complete
        complete = complete.append(event, {"event": event.value})
        assert len(complete.records) == len(previous.records) + 1
        assert complete.records[-1].previous_hash == previous.records[-1].record_hash
    with pytest.raises(TypeError):
        complete.append("deployment", {})  # type: ignore[arg-type]
    valid = left.records[0]
    with pytest.raises(ValueError, match="sequence"):
        HashedJournal(
            (
                JournalRecord(
                    sequence=True,  # type: ignore[arg-type]
                    event=valid.event,
                    payload_json=valid.payload_json,
                    previous_hash=valid.previous_hash,
                    record_hash=valid.record_hash,
                ),
            )
        )
