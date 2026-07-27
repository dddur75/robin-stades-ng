"""Planification déterministe du backfill historique."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from robin.historical.contracts import BackfillTask, QuotaMode


@dataclass(frozen=True)
class CompetitionTarget:
    name: str
    country: str
    search: str
    priority: str
    seasons: tuple[int, ...]


COMPETITION_TARGETS = (
    CompetitionTarget(
        "Ligue 1",
        "France",
        "Ligue 1",
        "A",
        tuple(range(2018, 2026)),
    ),
    CompetitionTarget(
        "Premier League",
        "England",
        "Premier League",
        "B",
        tuple(range(2018, 2026)),
    ),
    CompetitionTarget("La Liga", "Spain", "La Liga", "B", tuple(range(2018, 2026))),
    CompetitionTarget(
        "Bundesliga",
        "Germany",
        "Bundesliga",
        "B",
        tuple(range(2018, 2026)),
    ),
    CompetitionTarget("Serie A", "Italy", "Serie A", "B", tuple(range(2018, 2026))),
    CompetitionTarget(
        "UEFA Champions League",
        "World",
        "Champions League",
        "B",
        tuple(range(2018, 2026)),
    ),
)

CORE_ENDPOINTS = (
    "leagues",
    "teams",
    "fixtures",
    "standings",
    "players",
    "players/squads",
    "fixtures/events",
    "fixtures/statistics",
    "fixtures/players",
    "fixtures/lineups",
    "injuries",
)

SECONDARY_ENDPOINTS = ("teams/statistics", "coachs", "transfers")

BUSINESS_PRIORITY_ORDER = {
    "P0_MARKET": 0,
    "P0_TEAM_IDENTITY": 1,
    "P1_PLAYER_MATCH_STATS": 2,
    "P1_LINEUPS": 3,
    "P1_TEAM_MATCH_STATS": 4,
    "P2_EVENTS": 5,
    "P3_SECONDARY": 6,
    "P4_DEFERRED": 7,
}


def business_value_priority(
    *,
    competition: str,
    season: int,
    endpoint: str,
) -> str:
    """Prioriser les appels qui ferment un gate sans supprimer le plan initial."""

    normalized = endpoint.strip("/")
    external = competition in {
        "Premier League",
        "La Liga",
        "Bundesliga",
        "Serie A",
        "UEFA Champions League",
    }
    recent = season in {2022, 2023, 2024, 2025}
    if (
        competition in {"Serie A", "UEFA Champions League"}
        and normalized in {"leagues", "teams", "fixtures"}
    ):
        return "P0_TEAM_IDENTITY"
    if external and recent and normalized == "fixtures/players":
        return "P1_PLAYER_MATCH_STATS"
    if external and recent and normalized == "fixtures/lineups":
        return "P1_LINEUPS"
    if external and recent and normalized == "fixtures/statistics":
        return "P1_TEAM_MATCH_STATS"
    if external and recent and normalized == "fixtures/events":
        return "P2_EVENTS"
    if normalized in SECONDARY_ENDPOINTS:
        return "P3_SECONDARY"
    return "P4_DEFERRED"


def storage_allows_business_priority(
    storage_status: str,
    business_priority: str,
) -> bool:
    """Suspendre P3/P4 quand la projection haute franchit la pause."""

    return not (
        storage_status == "OBJECT_STORAGE_REQUIRED"
        and business_priority in {"P3_SECONDARY", "P4_DEFERRED"}
    )


def stable_task_id(
    competition_id: int,
    season: int,
    endpoint: str,
    *,
    page: int = 1,
    fixture_id: int | None = None,
    team_id: int | None = None,
) -> str:
    payload = (
        f"api-football:{competition_id}:{season}:{endpoint}:"
        f"{page}:{fixture_id or '-'}:{team_id or '-'}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_backfill_plan(
    validated_ids: dict[str, int],
    *,
    include_secondary: bool = False,
) -> list[BackfillTask]:
    tasks: list[BackfillTask] = []
    endpoints = CORE_ENDPOINTS + (SECONDARY_ENDPOINTS if include_secondary else ())
    for target in COMPETITION_TARGETS:
        competition_id = validated_ids.get(target.name)
        if competition_id is None:
            continue
        for season in target.seasons:
            for endpoint in endpoints:
                priority = (
                    "D"
                    if endpoint in SECONDARY_ENDPOINTS
                    else "C"
                    if target.priority != "A" and season < 2022
                    else target.priority
                )
                tasks.append(
                    BackfillTask(
                        task_id=stable_task_id(competition_id, season, endpoint),
                        competition_id=competition_id,
                        season=season,
                        endpoint=endpoint,
                        priority=priority,
                        business_value_priority=business_value_priority(
                            competition=target.name,
                            season=season,
                            endpoint=endpoint,
                        ),
                    )
                )
    return sorted(
        tasks,
        key=lambda task: (
            task.priority,
            0 if task.competition_id == validated_ids.get("Ligue 1") else 1,
            -task.season,
            task.endpoint,
        ),
    )


@dataclass(frozen=True)
class QuotaDecision:
    mode: QuotaMode
    callable_budget: int
    reserve: int


def quota_decision(
    remaining: int | None,
    *,
    requested_calls: int,
    reserve: int,
    accelerated: bool,
) -> QuotaDecision:
    if remaining is None:
        return QuotaDecision(QuotaMode.CONSERVATIVE, min(requested_calls, 25), reserve)
    if remaining <= reserve:
        return QuotaDecision(QuotaMode.PAUSED, 0, reserve)
    callable_budget = min(requested_calls, remaining - reserve)
    ratio = remaining / max(remaining + requested_calls, 1)
    if callable_budget <= reserve or ratio < 0.1:
        mode = QuotaMode.CRITICAL_RESERVE
    elif accelerated:
        mode = QuotaMode.ACCELERATED
    else:
        mode = QuotaMode.NORMAL
    return QuotaDecision(mode, callable_budget, reserve)


def select_validated_competition(
    records: tuple[dict[str, object], ...],
    *,
    expected_name: str,
    expected_country: str,
) -> tuple[int, dict[str, object]] | None:
    normalized_name = expected_name.casefold()
    normalized_country = expected_country.casefold()
    candidates: list[tuple[int, dict[str, object]]] = []
    for record in records:
        league = record.get("league")
        country = record.get("country")
        if not isinstance(league, dict) or not isinstance(country, dict):
            continue
        name = str(league.get("name", "")).casefold()
        country_name = str(country.get("name", "")).casefold()
        provider_id = league.get("id")
        if (
            name == normalized_name
            and country_name == normalized_country
            and isinstance(provider_id, int)
        ):
            candidates.append((provider_id, record))
    return candidates[0] if len(candidates) == 1 else None
