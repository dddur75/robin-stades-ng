"""Prévision complète du backfill, y compris le travail latent."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Literal, Mapping, TypedDict, cast

from robin.historical.storage import storage_inventory

Scenario = Literal["low", "base", "high"]
SCENARIOS: tuple[Scenario, ...] = ("low", "base", "high")
REMAINING_STATUSES = {
    "PENDING",
    "READY",
    "RETRYABLE",
    "SKIPPED_QUOTA",
    "PARTIAL",
}


class EndpointRule(TypedDict, total=False):
    endpoint: str
    dependency_type: str
    parent_entity: str
    expected_child_tasks: object
    observed_child_tasks: object
    calls_per_child_low: float
    calls_per_child_base: float
    calls_per_child_high: float
    coverage_status: str
    default_pages_low: int
    default_pages_base: int
    default_pages_high: int


class CompetitionPeriod(TypedDict):
    from_season: int
    to_season: int
    teams: int
    canonical_fixtures: int


class CompetitionProfile(TypedDict):
    competition: str
    provider_id: int
    multi_phase: bool
    playoffs_excluded: bool
    periods: list[CompetitionPeriod]


class Registry(TypedDict):
    version: str
    scenario_policy: dict[str, object]
    endpoints: list[EndpointRule]
    competition_profiles: list[CompetitionProfile]


def load_dependency_registry(path: Path) -> Registry:
    """Charger la définition versionnée et refuser une structure incomplète."""

    payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError("DEPENDENCY_REGISTRY_INVALID")
    version = payload.get("version")
    endpoints = payload.get("endpoints")
    profiles = payload.get("competition_profiles")
    policy = payload.get("scenario_policy")
    if (
        not isinstance(version, str)
        or not isinstance(endpoints, list)
        or not isinstance(profiles, list)
        or not isinstance(policy, dict)
    ):
        raise ValueError("DEPENDENCY_REGISTRY_INVALID")
    required = {
        "endpoint",
        "dependency_type",
        "parent_entity",
        "expected_child_tasks",
        "observed_child_tasks",
        "calls_per_child_low",
        "calls_per_child_base",
        "calls_per_child_high",
        "coverage_status",
    }
    for item in endpoints:
        if not isinstance(item, dict) or not required <= set(item):
            raise ValueError("DEPENDENCY_ENDPOINT_INVALID")
    return cast(Registry, payload)


def _profile_period(
    profiles: Mapping[int, CompetitionProfile],
    competition_id: int,
    season: int,
) -> CompetitionPeriod | None:
    profile = profiles.get(competition_id)
    if profile is None:
        return None
    for period in profile["periods"]:
        if period["from_season"] <= season <= period["to_season"]:
            return period
    return None


def _task_group_key(task: Mapping[str, object]) -> tuple[int, int, str]:
    return (
        int(str(task.get("competition_id", 0))),
        int(str(task.get("season", 0))),
        str(task.get("endpoint", "")),
    )


def _rule_factor(rule: EndpointRule, scenario: Scenario) -> float:
    if scenario == "low":
        return float(rule["calls_per_child_low"])
    if scenario == "base":
        return float(rule["calls_per_child_base"])
    return float(rule["calls_per_child_high"])


def _pagination_from_state(
    state: Path,
    rules: Mapping[str, EndpointRule],
) -> dict[str, dict[Scenario, int]]:
    observations: dict[str, list[int]] = defaultdict(list)
    for path in sorted((state / "checkpoints").rglob("*.json")):
        endpoint = path.stem
        if endpoint not in rules or rules[endpoint]["dependency_type"] != "PAGINATED":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        pages = payload.get("pages", [])
        if isinstance(pages, list) and pages:
            observations[endpoint].append(len(pages))
    pilot_path = state / "runs" / "pilot-ligue-1-2025.json"
    if pilot_path.exists():
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
        for report in pilot.get("endpoints", []):
            if not isinstance(report, dict):
                continue
            endpoint = str(report.get("endpoint", ""))
            pages = int(str(report.get("pages", 0)))
            if (
                endpoint in rules
                and rules[endpoint]["dependency_type"] == "PAGINATED"
                and pages > 0
            ):
                observations[endpoint].append(pages)
    result: dict[str, dict[Scenario, int]] = {}
    for endpoint, rule in rules.items():
        if rule["dependency_type"] != "PAGINATED":
            continue
        values = observations.get(endpoint, [])
        defaults: dict[Scenario, int] = {
            "low": int(str(rule.get("default_pages_low", 1))),
            "base": int(str(rule.get("default_pages_base", 1))),
            "high": int(str(rule.get("default_pages_high", 1))),
        }
        if not values:
            result[endpoint] = defaults
            continue
        result[endpoint] = {
            "low": max(1, min(min(values), defaults["low"])),
            "base": max(1, round(statistics.median(values))),
            "high": max(max(values), defaults["high"]),
        }
    return result


def _storage_bytes_per_call(state: Path, plan: Mapping[str, object]) -> float:
    raw_and_parquet = sum(
        path.stat().st_size
        for root in (state / "raw", state / "parquet")
        for path in root.rglob("*")
        if path.is_file()
    )
    pilot_path = state / "runs" / "pilot-ligue-1-2025.json"
    pilot_calls = 0
    if pilot_path.exists():
        pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
        pilot_calls = int(str(pilot.get("provider_calls", 0)))
    observed_calls = pilot_calls + int(str(plan.get("provider_calls", 0)))
    return raw_and_parquet / max(1, observed_calls)


def estimate_complete_forecast(
    *,
    plan: Mapping[str, object],
    registry: Registry,
    pagination: Mapping[str, Mapping[Scenario, int]],
    current_storage_bytes: int,
    storage_bytes_per_call: float,
    cache_rates: Mapping[Scenario, float] | None = None,
) -> dict[str, object]:
    """Estimer le travail matérialisé et latent sans masquer les parents."""

    raw_tasks = plan.get("tasks", [])
    tasks = (
        [cast(Mapping[str, object], task) for task in raw_tasks if isinstance(task, dict)]
        if isinstance(raw_tasks, list)
        else []
    )
    rules = {rule["endpoint"]: rule for rule in registry["endpoints"]}
    profiles = {
        profile["provider_id"]: profile
        for profile in registry["competition_profiles"]
    }
    policy = registry["scenario_policy"]
    daily_calls = int(str(policy.get("calls_per_day", 30_000)))
    effective_cache = cache_rates or {
        "low": float(str(policy.get("cache_rate_low", 0.25))),
        "base": float(str(policy.get("cache_rate_base", 0.0))),
        "high": float(str(policy.get("cache_rate_high", 0.0))),
    }

    fixture_children: dict[tuple[int, int, str], set[int]] = defaultdict(set)
    team_children: dict[tuple[int, int, str], set[int]] = defaultdict(set)
    for task in tasks:
        key = _task_group_key(task)
        fixture_id = task.get("fixture_id")
        team_id = task.get("team_id")
        if fixture_id is not None:
            fixture_children[key].add(int(str(fixture_id)))
        if team_id is not None:
            team_children[key].add(int(str(team_id)))

    materialized_calls: dict[Scenario, dict[str, float]] = {
        scenario: defaultdict(float) for scenario in SCENARIOS
    }
    latent_calls: dict[Scenario, dict[str, float]] = {
        scenario: defaultdict(float) for scenario in SCENARIOS
    }
    latent_fixture_tasks: dict[Scenario, int] = defaultdict(int)
    latent_team_tasks: dict[Scenario, int] = defaultdict(int)
    latent_player_pages: dict[Scenario, int] = defaultdict(int)
    dependency_rows: dict[str, dict[str, object]] = {}

    for endpoint, rule in rules.items():
        dependency_rows[endpoint] = {
            **rule,
            "expected_child_tasks": 0,
            "observed_child_tasks": (
                sum(
                    len(value)
                    for key, value in fixture_children.items()
                    if key[2] == endpoint
                )
                + sum(
                    len(value)
                    for key, value in team_children.items()
                    if key[2] == endpoint
                )
            ),
        }

    for task in tasks:
        if str(task.get("status", "")) not in REMAINING_STATUSES:
            continue
        endpoint = str(task.get("endpoint", ""))
        selected_rule = rules.get(endpoint)
        priority = str(task.get("priority", "UNKNOWN"))
        if selected_rule is None:
            estimated = max(1, int(str(task.get("estimated_calls", 1))))
            for scenario in SCENARIOS:
                materialized_calls[scenario][priority] += estimated
            continue
        dependency_type = selected_rule["dependency_type"]
        competition_id, season, _ = _task_group_key(task)
        fixture_id = task.get("fixture_id")
        team_id = task.get("team_id")

        if dependency_type == "FIXTURE_DEPENDENT" and fixture_id is None:
            period = _profile_period(profiles, competition_id, season)
            expected = period["canonical_fixtures"] if period is not None else 0
            existing = len(fixture_children[_task_group_key(task)])
            for scenario in SCENARIOS:
                count = max(0, expected - existing)
                latent_fixture_tasks[scenario] += count
                latent_calls[scenario][priority] += count * _rule_factor(
                    selected_rule, scenario
                )
            dependency_rows[endpoint]["expected_child_tasks"] = int(
                str(dependency_rows[endpoint]["expected_child_tasks"])
            ) + expected
            continue
        if dependency_type == "TEAM_DEPENDENT" and team_id is None:
            period = _profile_period(profiles, competition_id, season)
            expected = period["teams"] if period is not None else 0
            existing = len(team_children[_task_group_key(task)])
            for scenario in SCENARIOS:
                count = max(0, expected - existing)
                latent_team_tasks[scenario] += count
                latent_calls[scenario][priority] += count * _rule_factor(
                    selected_rule, scenario
                )
            dependency_rows[endpoint]["expected_child_tasks"] = int(
                str(dependency_rows[endpoint]["expected_child_tasks"])
            ) + expected
            continue
        if dependency_type == "PAGINATED":
            pages = pagination.get(endpoint, {"low": 1, "base": 1, "high": 1})
            for scenario in SCENARIOS:
                page_count = max(1, int(pages[scenario]))
                materialized_calls[scenario][priority] += _rule_factor(
                    selected_rule, scenario
                )
                extra = page_count - 1
                latent_player_pages[scenario] += extra
                latent_calls[scenario][priority] += extra * _rule_factor(
                    selected_rule, scenario
                )
            dependency_rows[endpoint]["expected_child_tasks"] = int(
                str(dependency_rows[endpoint]["expected_child_tasks"])
            ) + int(pages["base"])
            continue
        if dependency_type == "UNAVAILABLE":
            continue
        for scenario in SCENARIOS:
            estimated = max(1, int(str(task.get("estimated_calls", 1))))
            materialized_calls[scenario][priority] += (
                estimated * _rule_factor(selected_rule, scenario)
            )

    scenario_rows: dict[str, dict[str, object]] = {}
    storage_multipliers = {
        "low": float(str(policy.get("storage_multiplier_low", 0.6))),
        "base": float(str(policy.get("storage_multiplier_base", 1.0))),
        "high": float(str(policy.get("storage_multiplier_high", 1.5))),
    }
    for scenario in SCENARIOS:
        cache_factor = max(0.0, 1.0 - float(effective_cache[scenario]))
        priority_calls: dict[str, int] = {}
        priorities = set(materialized_calls[scenario]) | set(latent_calls[scenario])
        for priority in priorities:
            priority_calls[priority] = math.ceil(
                (
                    materialized_calls[scenario][priority]
                    + latent_calls[scenario][priority]
                )
                * cache_factor
            )
        calls = sum(priority_calls.values())
        priority_a = priority_calls.get("A", 0)
        priority_b = priority_a + priority_calls.get("B", 0)
        scenario_rows[scenario] = {
            "calls_remaining": calls,
            "calls_by_priority": priority_calls,
            "eta_priority_a_days": round(priority_a / daily_calls, 2),
            "eta_priority_b_days": round(priority_b / daily_calls, 2),
            "eta_full_days": round(calls / daily_calls, 2),
            "storage_projected_bytes": current_storage_bytes
            + math.ceil(
                calls
                * storage_bytes_per_call
                * storage_multipliers[scenario]
            ),
        }

    remaining_materialized = sum(
        str(task.get("status", "")) in REMAINING_STATUSES for task in tasks
    )
    completed = sum(str(task.get("status", "")) == "COMPLETED" for task in tasks)
    materialized_calls_base = math.ceil(
        sum(materialized_calls["base"].values())
    )
    result: dict[str, object] = {
        "status": "COMPLETE_LATENT_TASK_FORECAST",
        "forecast_scope": "MATERIALIZED_PLUS_LATENT",
        "registry_version": registry["version"],
        "materialized_tasks_total": len(tasks),
        "materialized_tasks_completed": completed,
        "materialized_tasks_remaining": remaining_materialized,
        "materialized_calls_remaining": materialized_calls_base,
        "materialized_eta_days": round(materialized_calls_base / daily_calls, 2),
        "materialized_eta_label": "MATERIALIZED_TASKS_ONLY",
        "completed_this_run": int(str(plan.get("completed_this_run", 0))),
        "expanded_this_run": int(str(plan.get("expanded_this_run", 0))),
        "new_latent_tasks_materialized": int(
            str(plan.get("expanded_this_run", 0))
        ),
        "remaining_materialized_tasks": remaining_materialized,
        "latent_fixture_tasks": latent_fixture_tasks["base"],
        "latent_team_tasks": latent_team_tasks["base"],
        "latent_player_pages": latent_player_pages["base"],
        "dependency_register": list(dependency_rows.values()),
        "scenarios": scenario_rows,
        "calls_per_day": daily_calls,
        "production_status": "PRODUCTION_LOCKED",
    }
    for scenario in SCENARIOS:
        row = scenario_rows[scenario]
        result[f"latent_calls_{scenario}"] = math.ceil(
            sum(latent_calls[scenario].values())
            * max(0.0, 1.0 - float(effective_cache[scenario]))
        )
        result[f"calls_remaining_{scenario}"] = row["calls_remaining"]
        result[f"eta_priority_a_{scenario}"] = row["eta_priority_a_days"]
        result[f"eta_priority_b_{scenario}"] = row["eta_priority_b_days"]
        result[f"eta_full_{scenario}"] = row["eta_full_days"]
        result[f"storage_projected_{scenario}"] = row[
            "storage_projected_bytes"
        ]
    return result


def build_complete_forecast(
    state: Path,
    registry_path: Path,
) -> dict[str, object]:
    """Construire le forecast complet depuis l'état durable restauré."""

    plan_path = state / "tasks" / "backfill-plan.json"
    plan_object = cast(object, json.loads(plan_path.read_text(encoding="utf-8")))
    if not isinstance(plan_object, dict):
        raise ValueError("BACKFILL_PLAN_INVALID")
    plan = cast(Mapping[str, object], plan_object)
    registry = load_dependency_registry(registry_path)
    rules = {rule["endpoint"]: rule for rule in registry["endpoints"]}
    pagination = _pagination_from_state(state, rules)
    inventory = storage_inventory(state)
    measured_storage_bytes_per_call = _storage_bytes_per_call(state, plan)
    observed_storage_bytes_per_call = float(
        str(
            registry["scenario_policy"].get(
                "storage_bytes_per_call_observed",
                0,
            )
        )
    )
    return estimate_complete_forecast(
        plan=plan,
        registry=registry,
        pagination=pagination,
        current_storage_bytes=int(str(inventory["bytes"])),
        storage_bytes_per_call=max(
            measured_storage_bytes_per_call,
            observed_storage_bytes_per_call,
        ),
    )
