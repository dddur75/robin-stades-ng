from __future__ import annotations

from tests.coverage.denominator_oracle import PACKS_PATH, initial_level_states, load_json


def test_only_e0_is_materialized_and_definitional() -> None:
    packs = load_json(PACKS_PATH)
    levels = packs["levels"]
    assert levels["E0"]["status"] == "MATERIALIZED"
    assert levels["E0"]["can_close_real_cell"] is False
    assert initial_level_states() == {
        "E0": "PASS_DEFINITION_ONLY",
        "E1": "NOT_RUN",
        "E2": "NOT_RUN",
        "E3": "NOT_RUN",
        "E4": "NOT_RUN",
    }
    assert levels["E1"]["status"] == "NOT_MATERIALIZED"
    assert levels["E1"]["scope"] == "EXACTLY_10_P0_REAL_FIXTURES"
    assert levels["E2"]["status"] == "NOT_MATERIALIZED"
    assert levels["E2"]["scope"] == "EXACTLY_50_P0_REAL_FIXTURES"
    assert levels["E3"]["status"] == "DECISION_REQUIRED"
    assert levels["E4"]["status"] == "SCALE_APPROVED_REQUIRED"
    assert packs["general_scan_before_e3_forbidden"] is True


def test_third_identical_attempt_is_forbidden() -> None:
    retry = load_json(PACKS_PATH)["retry_policy"]
    assert retry["maximum_similar_failures"] == 2
    assert retry["third_identical_attempt_forbidden"] is True
    assert retry["required_after_two"] == "REDESIGN_REQUIRED"
