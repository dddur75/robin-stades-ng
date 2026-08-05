from __future__ import annotations

import copy

import pytest

from tests.coverage.denominator_oracle import (
    DenominatorError,
    build_p0_cells,
    load_contract,
    make_rate,
    partition_observations_by_scope,
    validate_cell_closure,
)


def _observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "competition": "api-football:61",
        "season": 2020,
        "family": "fixtures",
        "scope_complete": True,
        "evidence": "fixture-census",
    }
    value.update(overrides)
    return value


def test_partial_and_outside_observations_are_non_gating_extended() -> None:
    complete = _observation()
    partial = _observation(family="events", scope_complete=False)
    outside = _observation(season=2019)
    partition = partition_observations_by_scope(
        [complete, copy.deepcopy(complete), partial, outside], load_contract()
    )
    assert partition["P0_2020_2025"] == [complete]
    assert partition["EXTENDED_ALL_AVAILABLE"] == [partial, outside]


def test_conflicting_observation_for_same_dimension_blocks() -> None:
    with pytest.raises(DenominatorError, match="OPEN_CONFLICTING_DUPLICATE"):
        partition_observations_by_scope(
            [_observation(evidence="a"), _observation(evidence="b")],
            load_contract(),
        )


def _closed_candidate(*, level: str, expected: int) -> dict[str, object]:
    cell = copy.deepcopy(build_p0_cells(load_contract())[0])
    cell.update(
        {
            "evaluation_level": level,
            "closure_state": "DENOMINATOR_CLOSED_FULL_SCOPE",
            "expected_count": expected,
            "received_count": expected,
            "empty_valid_count": 0,
            "invalid_count": 0,
            "coverage_percent": 1.0 if expected else None,
            "payload_hash": "a" * 64,
            "receipt_hash": "b" * 64,
            "rates": {
                "scope_completion": make_rate(
                    expected, expected, grain="scope", complete_scope=True
                ),
                "normalization_integrity": make_rate(
                    expected, expected, grain="identity", complete_scope=True
                ),
                "content_presence": make_rate(None, None, grain="content"),
            },
        }
    )
    return cell


def test_real_closure_requires_level_authorization() -> None:
    candidate = _closed_candidate(level="E4", expected=10)
    with pytest.raises(
        DenominatorError, match="REAL_CELL_CLOSURE_REQUIRES_LEVEL_AUTHORIZATION"
    ):
        validate_cell_closure(candidate)
    validate_cell_closure(candidate, authorizations={"E4": True})


def test_empty_valid_can_close_only_with_full_proof_and_authorization() -> None:
    candidate = _closed_candidate(level="E3", expected=0)
    validate_cell_closure(candidate, authorizations={"E3": True})
