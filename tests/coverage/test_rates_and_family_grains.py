from __future__ import annotations

import pytest

from tests.coverage.denominator_oracle import (
    DenominatorError,
    aggregate_weighted_rate,
    load_contract,
    load_grain_catalog,
    make_rate,
)


def test_three_rates_are_named_and_never_aggregated() -> None:
    contract = load_contract()
    assert set(contract["rates"]) == {
        "scope_completion",
        "normalization_integrity",
        "content_presence",
    }
    assert contract["forbidden_fields"] == ["coverage_rate", "overall_rate"]
    catalog = load_grain_catalog()
    assert len(catalog["family_bindings"]) == 16
    assert contract["grain_catalog"]["authoritative"] is True


def test_unknown_empty_valid_and_known_are_distinct() -> None:
    assert make_rate(None, None, grain="scope")["status"] == "UNKNOWN"
    assert (
        make_rate(0, 0, grain="suspensions", complete_scope=True)["status"]
        == "EMPTY_VALID"
    )
    known = make_rate(8, 10, grain="fixtures")
    assert known["status"] == "KNOWN"
    assert known["value"] == 0.8


@pytest.mark.parametrize(
    ("numerator", "denominator", "code"),
    [
        (1, None, "RATE_PARTIAL_TRIPLET_FORBIDDEN"),
        (11, 10, "RATE_NUMERATOR_EXCEEDS_DENOMINATOR"),
        (0, 0, "RATE_ZERO_DENOMINATOR_NOT_PROVEN_EMPTY"),
        (-1, 2, "RATE_NEGATIVE_COUNT"),
    ],
)
def test_invalid_rate_inputs_fail_closed(
    numerator: int | None, denominator: int | None, code: str
) -> None:
    with pytest.raises(DenominatorError, match=code):
        make_rate(numerator, denominator, grain="scope")


def test_weighted_rate_uses_denominators_and_unknown_fails_closed() -> None:
    weighted = aggregate_weighted_rate(
        [make_rate(1, 2, grain="a"), make_rate(9, 10, grain="b")]
    )
    assert weighted["numerator"] == 10
    assert weighted["denominator"] == 12
    assert weighted["value"] == pytest.approx(10 / 12)
    unknown = aggregate_weighted_rate(
        [make_rate(1, 2, grain="a"), make_rate(None, None, grain="b")]
    )
    assert unknown["status"] == "UNKNOWN"
    assert unknown["value"] is None
