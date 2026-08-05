from __future__ import annotations

from collections import Counter

from tests.coverage.denominator_oracle import build_p0_cells, load_contract


def test_authoritative_p0_grid_exists_even_without_observations() -> None:
    contract = load_contract()
    cells = build_p0_cells(contract)
    dimensions = [
        (cell["competition"], cell["season"], cell["family"]) for cell in cells
    ]
    assert len(cells) == len(set(dimensions)) == 480
    assert set(Counter(cell["competition"] for cell in cells).values()) == {96}
    assert set(Counter(cell["season"] for cell in cells).values()) == {80}
    assert set(Counter(cell["family"] for cell in cells).values()) == {30}
    assert Counter(cell["family"] for cell in cells)["suspensions"] == 30


def test_e0_cells_never_claim_empirical_closure() -> None:
    cells = build_p0_cells(load_contract())
    assert {cell["closure_state"] for cell in cells} == {"OPEN_NOT_EVALUATED"}
    assert {cell["population_kind"] for cell in cells} == {"P0_FULL"}
    assert {cell["evaluation_level"] for cell in cells} == {"E0"}
    assert all(
        cell["diagnostics"]["linked_empirical_observations"] == 0 for cell in cells
    )
    assert all(cell["diagnostics"]["census_evidence"] is False for cell in cells)
    assert all(cell["diagnostics"]["provider_calls"] == 0 for cell in cells)


def test_only_p0_dimensions_are_present() -> None:
    contract = load_contract()
    cells = build_p0_cells(contract)
    assert {cell["competition"] for cell in cells} == set(
        contract["grid"]["competitions"]
    )
    assert {cell["season"] for cell in cells} == set(contract["grid"]["seasons"])
    assert {cell["family"] for cell in cells} == set(contract["grid"]["families"])
    assert not {"coaches", "sidelined", "sidelined_periods"} & {
        cell["family"] for cell in cells
    }
