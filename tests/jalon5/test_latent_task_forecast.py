from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Mapping, cast

import pytest

from robin.historical.forecast import (
    Registry,
    Scenario,
    estimate_complete_forecast,
    load_dependency_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "configs" / "historical_dependency_registry_v1.json"


@pytest.fixture
def registry() -> Registry:
    return load_dependency_registry(REGISTRY_PATH)


def task(
    endpoint: str,
    *,
    competition_id: int = 61,
    season: int = 2024,
    priority: str = "A",
    status: str = "READY",
    fixture_id: int | None = None,
    team_id: int | None = None,
) -> dict[str, object]:
    return {
        "task_id": (
            f"{competition_id}-{season}-{endpoint}-"
            f"{fixture_id or 'parent'}-{team_id or 'parent'}"
        ),
        "competition_id": competition_id,
        "season": season,
        "endpoint": endpoint,
        "priority": priority,
        "status": status,
        "fixture_id": fixture_id,
        "team_id": team_id,
        "estimated_calls": 1,
    }


def forecast(
    tasks: list[dict[str, object]],
    registry: Registry,
    *,
    cache_rates: dict[str, float] | None = None,
) -> dict[str, object]:
    typed_cache = (
        cast(Mapping[Scenario, float], cache_rates)
        if cache_rates is not None
        else None
    )
    return estimate_complete_forecast(
        plan={
            "tasks": tasks,
            "completed_this_run": 0,
            "expanded_this_run": 0,
        },
        registry=registry,
        pagination={
            "players": {"low": 39, "base": 40, "high": 46},
            "injuries": {"low": 1, "base": 1, "high": 2},
        },
        current_storage_bytes=1_000_000,
        storage_bytes_per_call=2_000,
        cache_rates=typed_cache,
    )


def test_aucune_tache_latente(registry: Registry) -> None:
    result = forecast([task("fixtures", status="COMPLETED")], registry)
    assert result["latent_fixture_tasks"] == 0
    assert result["latent_team_tasks"] == 0
    assert result["latent_player_pages"] == 0
    assert result["calls_remaining_base"] == 0


def test_endpoint_fixture_non_developpe_ne_tombe_pas_a_zero(
    registry: Registry,
) -> None:
    result = forecast([task("fixtures/events")], registry)
    assert result["latent_fixture_tasks"] == 306
    assert result["calls_remaining_base"] == 306


def test_quatre_endpoints_fixture_non_developpes(registry: Registry) -> None:
    endpoints = (
        "fixtures/events",
        "fixtures/statistics",
        "fixtures/players",
        "fixtures/lineups",
    )
    result = forecast([task(endpoint) for endpoint in endpoints], registry)
    assert result["latent_fixture_tasks"] == 4 * 306
    assert result["calls_remaining_base"] == 4 * 306


def test_endpoint_equipe_non_developpe(registry: Registry) -> None:
    result = forecast([task("players/squads")], registry)
    assert result["latent_team_tasks"] == 18
    assert result["calls_remaining_base"] == 18


def test_pagination_joueurs_utilise_les_pages_observees(registry: Registry) -> None:
    result = forecast([task("players")], registry)
    assert result["latent_player_pages"] == 39
    assert result["calls_remaining_base"] == 40


@pytest.mark.parametrize(
    ("season", "expected"),
    [(2024, 306), (2022, 380)],
)
def test_formats_ligue1_18_et_20_equipes(
    registry: Registry,
    season: int,
    expected: int,
) -> None:
    result = forecast([task("fixtures/events", season=season)], registry)
    assert result["latent_fixture_tasks"] == expected


@pytest.mark.parametrize(
    ("season", "expected"),
    [(2023, 125), (2024, 189)],
)
def test_competition_multi_phase(
    registry: Registry,
    season: int,
    expected: int,
) -> None:
    result = forecast(
        [
            task(
                "fixtures/events",
                competition_id=2,
                season=season,
                priority="B",
            )
        ],
        registry,
    )
    assert result["latent_fixture_tasks"] == expected


def test_barrages_exclus_du_format_regulier(registry: Registry) -> None:
    result = forecast([task("fixtures/events", season=2024)], registry)
    assert result["latent_fixture_tasks"] == 306
    assert result["latent_fixture_tasks"] != 308


def test_endpoint_indisponible_ne_projette_aucun_appel(
    registry: Registry,
) -> None:
    modified = deepcopy(registry)
    transfer = next(
        item for item in modified["endpoints"] if item["endpoint"] == "transfers"
    )
    transfer["dependency_type"] = "UNAVAILABLE"
    result = forecast([task("transfers")], modified)
    assert result["calls_remaining_base"] == 0


def test_cache_complet_annule_les_appels_fournisseur(registry: Registry) -> None:
    result = forecast(
        [task("fixtures/events"), task("players")],
        registry,
        cache_rates={"low": 1.0, "base": 1.0, "high": 1.0},
    )
    assert result["calls_remaining_low"] == 0
    assert result["calls_remaining_base"] == 0
    assert result["calls_remaining_high"] == 0


def test_scenarios_bas_central_haut_sont_ordonnes(registry: Registry) -> None:
    result = forecast(
        [
            task("fixtures/events"),
            task("players/squads"),
            task("players"),
            task("fixtures"),
        ],
        registry,
    )
    assert (
        int(result["calls_remaining_low"])
        <= int(result["calls_remaining_base"])
        <= int(result["calls_remaining_high"])
    )
    assert (
        int(result["storage_projected_low"])
        <= int(result["storage_projected_base"])
        <= int(result["storage_projected_high"])
    )


def test_expansion_reelle_conserve_la_prevision(registry: Registry) -> None:
    before = forecast([task("fixtures/events")], registry)
    expanded = [
        task("fixtures/events", status="COMPLETED"),
        *[
            task("fixtures/events", fixture_id=fixture_id)
            for fixture_id in range(1, 307)
        ],
    ]
    after = forecast(expanded, registry)
    assert before["calls_remaining_base"] == 306
    assert after["latent_fixture_tasks"] == 0
    assert after["calls_remaining_base"] == 306


def test_convergence_progressive_apres_completion_des_enfants(
    registry: Registry,
) -> None:
    expanded: list[dict[str, object]] = [
        task("fixtures/events", status="COMPLETED")
    ]
    expanded.extend(
        task(
            "fixtures/events",
            fixture_id=fixture_id,
            status="COMPLETED" if fixture_id <= 100 else "READY",
        )
        for fixture_id in range(1, 307)
    )
    result = forecast(expanded, registry)
    assert result["latent_fixture_tasks"] == 0
    assert result["materialized_tasks_completed"] == 101
    assert result["calls_remaining_base"] == 206
    assert result["calls_remaining_base"] != 0


def test_registre_expose_tous_les_champs_obligatoires(
    registry: Registry,
) -> None:
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
    assert registry["version"] == "historical-dependency-registry-v1"
    assert all(required <= set(item) for item in registry["endpoints"])
