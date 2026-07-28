from __future__ import annotations

import json
from pathlib import Path

from robin.prospective_observatory.costs import (
    API_DATA_CALLS_PER_FIXTURE,
    API_ENDPOINT_DATA_CALLS_PER_FIXTURE,
    API_FRESHNESS_CALLS_PER_FIXTURE,
    API_PROVIDER_CALL_GUARDS_PER_FIXTURE,
    ODDS_PROVIDER_CALL_GUARDS_PER_FIXTURE,
    SEMANTIC_WINDOWS_PER_FIXTURE,
    build_season_cost_projection,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "jalon12" / "season-cost-projection.json"
CAPABILITIES = (
    ROOT
    / "docs"
    / "prospective-observatory"
    / "PROVIDER-CAPABILITY-MATRIX.md"
)


def _scope(report: dict[str, object], scope_id: str) -> dict[str, object]:
    scopes = report["scopes"]
    assert isinstance(scopes, list)
    return next(
        scope
        for scope in scopes
        if isinstance(scope, dict) and scope.get("scope_id") == scope_id
    )


def test_cost_projection_is_pure_and_matches_versioned_report() -> None:
    first = build_season_cost_projection()
    second = build_season_cost_projection()
    assert first == second
    assert json.loads(REPORT.read_text("utf-8")) == first


def test_option_b_window_and_endpoint_call_accounting() -> None:
    report = build_season_cost_projection()
    policy = report["window_policy"]
    assert isinstance(policy, dict)
    assert policy["semantic_windows_per_fixture"] == SEMANTIC_WINDOWS_PER_FIXTURE == 49
    assert (
        policy["api_endpoint_data_calls_per_fixture"]
        == API_ENDPOINT_DATA_CALLS_PER_FIXTURE
        == 22
    )
    assert (
        policy["api_freshness_calls_per_fixture"]
        == API_FRESHNESS_CALLS_PER_FIXTURE
        == 8
    )
    assert (
        policy["api_data_calls_per_fixture"]
        == API_DATA_CALLS_PER_FIXTURE
        == 30
    )
    assert (
        policy["api_provider_call_guards_per_fixture"]
        == API_PROVIDER_CALL_GUARDS_PER_FIXTURE
        == 65
    )
    assert (
        policy["odds_provider_call_guards_per_fixture"]
        == ODDS_PROVIDER_CALL_GUARDS_PER_FIXTURE
        == 6
    )
    assert policy["family_windows_per_fixture"] == {
        "FIXTURE": 8,
        "TEAM": 8,
        "EVENT_STATUS": 8,
        "SQUAD": 3,
        "PLAYER_STATUS": 6,
        "INJURY": 6,
        "LINEUP": 2,
        "FORMATION": 2,
        "ODDS": 6,
    }


def test_pilot_caps_and_p1_off_are_machine_checked() -> None:
    report = build_season_cost_projection()
    activation = report["activation_policy"]
    assert isinstance(activation, dict)
    assert activation["P0"] == "LIGUE_1_ONLY"
    assert activation["P1"] == "OFF"
    assert activation["five_leagues_projection_authorizes_activation"] is False

    pilot = _scope(report, "pilot_9")
    scenarios = pilot["scenarios"]
    assert isinstance(scenarios, dict)
    for scenario in scenarios.values():
        assert isinstance(scenario, dict)
        api = scenario["api_football"]
        odds = scenario["odds_api"]
        assert isinstance(api, dict)
        assert isinstance(odds, dict)
        assert api["within_pilot_cap"] is True
        assert odds["within_pilot_cap"] is True
        assert api["total_calls"] <= 5_000
        assert odds["credits"] <= 250


def test_storage_and_compute_unknowns_are_not_invented() -> None:
    report = build_season_cost_projection()
    season = _scope(report, "ligue1_season_306")
    scenarios = season["scenarios"]
    assert isinstance(scenarios, dict)
    central = scenarios["central"]
    assert isinstance(central, dict)
    r2 = central["r2"]
    postgres = central["postgresql"]
    gha = central["github_actions"]
    assert isinstance(r2, dict)
    assert isinstance(postgres, dict)
    assert isinstance(gha, dict)
    assert r2["durable_capture_objects"] == 306 * (49 + 8 + 1) * 3
    assert r2["provider_budget_objects"] > 0
    assert r2["provider_call_guard_objects"] == 306 * (65 + 6)
    assert (
        r2["provider_call_completion_objects"]
        == r2["provider_call_guard_objects"]
    )
    assert (
        r2["provider_budget_objects"]
        == r2["provider_transport_budget_objects"]
        + r2["provider_call_guard_objects"]
        + r2["provider_call_completion_objects"]
    )
    assert (
        r2["known_objects_without_registry_refresh_or_retry_payloads"]
        == r2["durable_capture_objects"] + r2["provider_budget_objects"]
    )
    assert r2["objects_upper_bound"] is None
    assert r2["bytes"] is None
    assert r2["cost"] is None
    assert postgres["bytes"] is None
    assert postgres["cost"] is None
    assert gha["minutes"] is None
    assert gha["cost"] is None


def test_capability_matrix_covers_all_families_and_fail_closed_limits() -> None:
    document = CAPABILITIES.read_text("utf-8")
    for family in (
        "FIXTURE",
        "TEAM",
        "SQUAD",
        "PLAYER_STATUS",
        "INJURY",
        "LINEUP",
        "FORMATION",
        "EVENT_STATUS",
        "ODDS",
    ):
        assert f"`{family}`" in document
    for endpoint in (
        "`/fixtures`",
        "`/players/squads`",
        "`/injuries`",
        "`/fixtures/lineups`",
        "`/v4/sports/{sport}/odds`",
    ):
        assert endpoint in document
    assert "P1_OFF" in document
    assert "horodatage fournisseur" in document
    assert "non mappé" in document
    assert "CAPTURED_EMPTY" in document
