"""Deterministic unit forecast for the Jalon 12 prospective observatory.

The forecast deliberately reports provider units and durable object/row counts,
not currency. No price, byte size, compression ratio, or execution duration is
assumed without an observed source.
"""

from __future__ import annotations

from dataclasses import dataclass

PROJECTION_SCHEMA_VERSION = "jalon12-season-cost-projection-v1"
WINDOW_POLICY_VERSION = "prospective-capture-window-v2-option-b"

PILOT_API_FOOTBALL_CAP = 5_000
PILOT_ODDS_API_CAP = 250

GENERAL_WINDOWS_PER_FIXTURE = 8
SQUAD_WINDOWS_PER_FIXTURE = 3
INJURY_STATUS_WINDOWS_PER_FIXTURE = 6
LINEUP_FORMATION_WINDOWS_PER_FIXTURE = 2
ODDS_WINDOWS_PER_FIXTURE = 6

SEMANTIC_WINDOWS_PER_FIXTURE = (
    3 * GENERAL_WINDOWS_PER_FIXTURE
    + SQUAD_WINDOWS_PER_FIXTURE
    + 2 * INJURY_STATUS_WINDOWS_PER_FIXTURE
    + 2 * LINEUP_FORMATION_WINDOWS_PER_FIXTURE
    + ODDS_WINDOWS_PER_FIXTURE
)

# One endpoint response is shared by the families which use the same payload:
# FIXTURE/TEAM/EVENT_STATUS, INJURY/PLAYER_STATUS, and LINEUP/FORMATION.
API_ENDPOINT_DATA_CALLS_PER_FIXTURE = (
    GENERAL_WINDOWS_PER_FIXTURE
    + 2 * SQUAD_WINDOWS_PER_FIXTURE
    + INJURY_STATUS_WINDOWS_PER_FIXTURE
    + LINEUP_FORMATION_WINDOWS_PER_FIXTURE
)
# The player and lineup workflows also re-read `/fixtures?id=...` immediately
# before their deep endpoint. This is a billed freshness call and must never be
# hidden inside the semantic-family mutualisation above.
API_FRESHNESS_CALLS_PER_FIXTURE = (
    INJURY_STATUS_WINDOWS_PER_FIXTURE
    + LINEUP_FORMATION_WINDOWS_PER_FIXTURE
)
API_DATA_CALLS_PER_FIXTURE = (
    API_ENDPOINT_DATA_CALLS_PER_FIXTURE
    + API_FRESHNESS_CALLS_PER_FIXTURE
)
# The fail-closed transport guard is one immutable zero-unit budget object per
# affected semantic window and physical data call. Shared endpoint responses
# therefore retain one guard per family/window, while SQUAD has two guarded
# transports and the player/lineup freshness calls guard every affected family.
API_PROVIDER_CALL_GUARDS_PER_FIXTURE = (
    3 * GENERAL_WINDOWS_PER_FIXTURE
    + 2 * SQUAD_WINDOWS_PER_FIXTURE
    + 2 * INJURY_STATUS_WINDOWS_PER_FIXTURE
    + 2 * LINEUP_FORMATION_WINDOWS_PER_FIXTURE
    + (2 * INJURY_STATUS_WINDOWS_PER_FIXTURE + SQUAD_WINDOWS_PER_FIXTURE)
    + 2 * LINEUP_FORMATION_WINDOWS_PER_FIXTURE
)
ODDS_PROVIDER_CALL_GUARDS_PER_FIXTURE = ODDS_WINDOWS_PER_FIXTURE
API_CAPTURE_RUNS_PER_MATCHDAY = (
    GENERAL_WINDOWS_PER_FIXTURE
    + INJURY_STATUS_WINDOWS_PER_FIXTURE
    + LINEUP_FORMATION_WINDOWS_PER_FIXTURE
)
ODDS_CREDITS_PER_CALL = 2
R2_OBJECTS_PER_CAPTURE = 3
REGISTRY_CALLS_PER_DAY = 3


@dataclass(frozen=True, slots=True)
class ProjectionScope:
    scope_id: str
    fixtures: int
    matchdays: int
    calendar_days: int
    activation: str


@dataclass(frozen=True, slots=True)
class ProjectionScenario:
    scenario_id: str
    api_cohorts_per_matchday: int
    odds_fixtures_per_cohort: int
    retry_percent: int


SCOPES: tuple[ProjectionScope, ...] = (
    ProjectionScope("pilot_9", 9, 1, 1, "P0_ACTIVE_BOUNDED_PILOT"),
    ProjectionScope("ligue1_matchday_9", 9, 1, 22, "P0_ACTIVE"),
    ProjectionScope("ligue1_month_36", 36, 4, 30, "P0_ACTIVE"),
    ProjectionScope("ligue1_season_306", 306, 34, 365, "P0_ACTIVE"),
    ProjectionScope("five_leagues_season_1752", 1_752, 186, 365, "P1_OFF_PLANNING_ONLY"),
)

SCENARIOS: tuple[ProjectionScenario, ...] = (
    ProjectionScenario("low", 1, 10, 0),
    ProjectionScenario("central", 2, 3, 0),
    ProjectionScenario("high", 3, 1, 0),
    ProjectionScenario("high_with_retries", 3, 1, 10),
)


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _retry_units(units: int, percent: int) -> int:
    return _ceil_div(units * percent, 100) if percent else 0


def _scenario_projection(
    scope: ProjectionScope,
    scenario: ProjectionScenario,
) -> dict[str, object]:
    semantic_captures = scope.fixtures * SEMANTIC_WINDOWS_PER_FIXTURE
    api_endpoint_data_calls = (
        scope.fixtures * API_ENDPOINT_DATA_CALLS_PER_FIXTURE
    )
    api_freshness_calls = (
        scope.fixtures * API_FRESHNESS_CALLS_PER_FIXTURE
    )
    api_data_calls = api_endpoint_data_calls + api_freshness_calls
    api_status_calls = (
        scope.matchdays
        * API_CAPTURE_RUNS_PER_MATCHDAY
        * scenario.api_cohorts_per_matchday
    )
    api_registry_calls = scope.calendar_days * REGISTRY_CALLS_PER_DAY
    api_retry_calls = _retry_units(
        api_data_calls + api_status_calls,
        scenario.retry_percent,
    )
    api_total = (
        api_data_calls
        + api_status_calls
        + api_registry_calls
        + api_retry_calls
    )

    odds_cohorts_per_window = max(
        scope.matchdays,
        _ceil_div(scope.fixtures, scenario.odds_fixtures_per_cohort),
    )
    odds_calls = odds_cohorts_per_window * ODDS_WINDOWS_PER_FIXTURE
    odds_retry_calls = _retry_units(odds_calls, scenario.retry_percent)
    odds_credits = (odds_calls + odds_retry_calls) * ODDS_CREDITS_PER_CALL
    odds_quota_preflight_calls = odds_calls + odds_retry_calls
    odds_total_http_calls = (
        odds_calls + odds_retry_calls + odds_quota_preflight_calls
    )

    api_capture_runs = api_status_calls
    odds_capture_runs = odds_calls + odds_retry_calls
    gha_runs_lower_bound = (
        scope.calendar_days + api_capture_runs + odds_capture_runs
    )

    api_guard_objects = (
        scope.fixtures * API_PROVIDER_CALL_GUARDS_PER_FIXTURE
    )
    api_guard_objects += _retry_units(
        api_guard_objects,
        scenario.retry_percent,
    )
    api_transport_budget_objects = api_total
    # Zero-credit quota preflights are journalled too: two durable transport
    # records per Odds capture run (preflight + billed data request).
    odds_transport_budget_objects = 2 * (odds_calls + odds_retry_calls)
    odds_guard_objects = (
        scope.fixtures * ODDS_PROVIDER_CALL_GUARDS_PER_FIXTURE
    )
    odds_guard_objects += _retry_units(
        odds_guard_objects,
        scenario.retry_percent,
    )
    api_completion_objects = api_guard_objects
    odds_completion_objects = odds_guard_objects
    api_budget_objects = (
        api_transport_budget_objects
        + api_guard_objects
        + api_completion_objects
    )
    odds_budget_objects = (
        odds_transport_budget_objects
        + odds_guard_objects
        + odds_completion_objects
    )
    freshness_captures = (
        scope.fixtures * API_FRESHNESS_CALLS_PER_FIXTURE
    )
    registry_captures_minimum = scope.fixtures
    durable_capture_objects = (
        semantic_captures
        + freshness_captures
        + registry_captures_minimum
    ) * R2_OBJECTS_PER_CAPTURE
    known_r2_objects = (
        durable_capture_objects
        + api_budget_objects
        + odds_budget_objects
    )
    receipt_rows = (
        semantic_captures
        + freshness_captures
        + registry_captures_minimum
    )

    return {
        "api_football": {
            "endpoint_data_calls": api_endpoint_data_calls,
            "freshness_calls": api_freshness_calls,
            "data_calls": api_data_calls,
            "status_calls": api_status_calls,
            "registry_calls": api_registry_calls,
            "retry_calls": api_retry_calls,
            "total_calls": api_total,
            "pilot_cap": PILOT_API_FOOTBALL_CAP,
            "within_pilot_cap": api_total <= PILOT_API_FOOTBALL_CAP,
        },
        "odds_api": {
            "capture_cohorts_per_window": odds_cohorts_per_window,
            "calls": odds_calls,
            "retry_calls": odds_retry_calls,
            "quota_preflight_calls": odds_quota_preflight_calls,
            "total_http_calls": odds_total_http_calls,
            "credits": odds_credits,
            "pilot_cap": PILOT_ODDS_API_CAP,
            "within_pilot_cap": odds_credits <= PILOT_ODDS_API_CAP,
        },
        "github_actions": {
            "workflow_runs_lower_bound": gha_runs_lower_bound,
            "registry_runs": scope.calendar_days,
            "api_capture_runs": api_capture_runs,
            "odds_capture_runs": odds_capture_runs,
            "minutes": None,
            "cost": None,
        },
        "r2": {
            "semantic_captures": semantic_captures,
            "freshness_captures": freshness_captures,
            "registry_captures_minimum": registry_captures_minimum,
            "objects_per_capture": R2_OBJECTS_PER_CAPTURE,
            "durable_capture_objects": durable_capture_objects,
            "provider_budget_objects": (
                api_budget_objects + odds_budget_objects
            ),
            "provider_transport_budget_objects": (
                api_transport_budget_objects
                + odds_transport_budget_objects
            ),
            "provider_call_guard_objects": (
                api_guard_objects + odds_guard_objects
            ),
            "provider_call_completion_objects": (
                api_completion_objects + odds_completion_objects
            ),
            "known_objects_without_registry_refresh_or_retry_payloads": (
                known_r2_objects
            ),
            "objects_upper_bound": None,
            "bytes": None,
            "cost": None,
        },
        "postgresql": {
            "capture_receipt_rows_without_registry_refresh": receipt_rows,
            "payload_index_rows_without_registry_refresh": receipt_rows,
            "capture_attempt_rows_without_retries": semantic_captures,
            "capture_window_rows": semantic_captures,
            "provider_budget_rows": (
                api_budget_objects + odds_budget_objects
            ),
            "provider_call_guard_rows": (
                api_guard_objects + odds_guard_objects
            ),
            "provider_call_completion_rows": (
                api_completion_objects + odds_completion_objects
            ),
            "retry_attempt_rows": None,
            "bytes": None,
            "cost": None,
        },
    }


def build_season_cost_projection() -> dict[str, object]:
    """Return the canonical projection as a pure JSON-compatible value."""

    scopes: list[dict[str, object]] = []
    for scope in SCOPES:
        scenarios = {
            scenario.scenario_id: _scenario_projection(scope, scenario)
            for scenario in SCENARIOS
        }
        scopes.append(
            {
                "scope_id": scope.scope_id,
                "fixtures": scope.fixtures,
                "matchdays": scope.matchdays,
                "calendar_days": scope.calendar_days,
                "activation": scope.activation,
                "scenarios": scenarios,
            }
        )

    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "window_policy": {
            "version": WINDOW_POLICY_VERSION,
            "option": "B_CONSOLIDATED_NON_OVERLAPPING",
            "family_windows_per_fixture": {
                "FIXTURE": GENERAL_WINDOWS_PER_FIXTURE,
                "TEAM": GENERAL_WINDOWS_PER_FIXTURE,
                "EVENT_STATUS": GENERAL_WINDOWS_PER_FIXTURE,
                "SQUAD": SQUAD_WINDOWS_PER_FIXTURE,
                "PLAYER_STATUS": INJURY_STATUS_WINDOWS_PER_FIXTURE,
                "INJURY": INJURY_STATUS_WINDOWS_PER_FIXTURE,
                "LINEUP": LINEUP_FORMATION_WINDOWS_PER_FIXTURE,
                "FORMATION": LINEUP_FORMATION_WINDOWS_PER_FIXTURE,
                "ODDS": ODDS_WINDOWS_PER_FIXTURE,
            },
            "semantic_windows_per_fixture": SEMANTIC_WINDOWS_PER_FIXTURE,
            "api_endpoint_data_calls_per_fixture": (
                API_ENDPOINT_DATA_CALLS_PER_FIXTURE
            ),
            "api_freshness_calls_per_fixture": (
                API_FRESHNESS_CALLS_PER_FIXTURE
            ),
            "api_data_calls_per_fixture": API_DATA_CALLS_PER_FIXTURE,
            "api_provider_call_guards_per_fixture": (
                API_PROVIDER_CALL_GUARDS_PER_FIXTURE
            ),
            "odds_provider_call_guards_per_fixture": (
                ODDS_PROVIDER_CALL_GUARDS_PER_FIXTURE
            ),
        },
        "scenario_assumptions": {
            scenario.scenario_id: {
                "api_cohorts_per_matchday": scenario.api_cohorts_per_matchday,
                "odds_fixtures_per_cohort": scenario.odds_fixtures_per_cohort,
                "retry_percent": scenario.retry_percent,
            }
            for scenario in SCENARIOS
        },
        "accounting_assumptions": {
            "api_status": "one /status call per API capture cohort/run",
            "api_freshness": (
                "one billed /fixtures?id=... call for each player-status "
                "and lineup capture window, before the deep endpoint"
            ),
            "registry": "three API-Football calls per active calendar day",
            "odds": (
                "six windows, one quota preflight plus one data request per "
                "global cohort, and two credits per data request; a request "
                "may mutualize several fixtures"
            ),
            "r2": (
                "three append-only objects per semantic capture plus one "
                "zero-unit fail-closed guard and one immutable receipt-link "
                "completion per affected window/transport"
            ),
            "postgresql": (
                "row counts only; payload bodies remain in R2 and retry-row "
                "fan-out is intentionally unestimated"
            ),
            "unknown_values": (
                "bytes, compression, execution minutes and monetary costs stay "
                "null until observed"
            ),
        },
        "activation_policy": {
            "P0": "LIGUE_1_ONLY",
            "P1": "OFF",
            "pilot_api_football_cap": PILOT_API_FOOTBALL_CAP,
            "pilot_odds_api_cap": PILOT_ODDS_API_CAP,
            "five_leagues_projection_authorizes_activation": False,
        },
        "scopes": scopes,
    }
