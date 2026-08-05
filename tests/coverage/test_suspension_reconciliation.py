from __future__ import annotations

import copy

import pytest

from tests.coverage.denominator_oracle import (
    DenominatorError,
    classify_absence,
    reconcile_absences,
)


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "fixture_id": 1,
        "player_id": 10,
        "team_id": 2,
        "type": "Knee injury",
        "reason": "Injury",
        "start": None,
        "end": None,
        "description": "",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize("text", ["Suspendu", "Suspendido", "Red card", "Yellow cards"])
def test_multilingual_suspensions_match_the_frozen_rule(text: str) -> None:
    assert classify_absence(_record(type=text, reason="")) == "SUSPENSION"


def test_partition_is_exhaustive_and_exact_duplicates_do_not_inflate() -> None:
    injury = _record()
    suspension = _record(player_id=11, type="Suspendu", reason="Red card")
    unknown = _record(player_id=12, type="", reason="", description="")
    result = reconcile_absences(
        [injury, suspension, unknown, copy.deepcopy(injury)], pages_complete=True
    )
    assert result["source_records_distinct"] == 3
    assert result["injuries"] + result["suspensions"] + result["unclassifiable"] == 3
    assert result["duplicates_ignored"] == 1


def test_incomplete_pages_and_conflicting_duplicates_block() -> None:
    with pytest.raises(DenominatorError, match="OPEN_MISSING_SCOPE"):
        reconcile_absences([_record()], pages_complete=False)
    first = _record(description="first")
    second = _record(description="conflict")
    with pytest.raises(DenominatorError, match="OPEN_CONFLICTING_DUPLICATE"):
        reconcile_absences([first, second], pages_complete=True)


def test_zero_suspension_is_empty_valid_only_after_complete_pages() -> None:
    result = reconcile_absences([_record()], pages_complete=True)
    assert result["suspensions"] == 0
    assert result["absence_scope_completion_rate"]["value"] == 1.0
    assert result["absence_classification_integrity_rate"]["value"] == 1.0
    assert result["classification_state"] == "DENOMINATOR_CLASSIFICATION_READY"


def test_ambiguous_non_injury_reason_never_becomes_an_injury() -> None:
    ambiguous = _record(type="Personal reasons", reason="")
    assert classify_absence(ambiguous) == "UNCLASSIFIABLE"
    result = reconcile_absences([ambiguous], pages_complete=True)
    assert result["injuries"] == 0
    assert result["unclassifiable"] == 1
    assert result["absence_classification_integrity_rate"]["value"] == 0.0
    assert result["classification_state"] == "OPEN_CLASSIFICATION_AMBIGUOUS"
