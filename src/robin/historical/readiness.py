"""Gates factuels du Jalon 6, calculés depuis l'état durable restauré."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REGULAR_PREFIX = "Regular Season"
TERMINAL_EXCLUSIONS = {"CANC", "ABD", "INT", "SUSP"}


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _partition(state: Path, season: int, entity: str) -> Path | None:
    candidates = sorted(
        (
            state
            / "parquet"
            / "competition=Ligue-1"
            / f"season={season}"
            / f"entity_type={entity}"
        ).rglob("*.parquet")
    )
    return candidates[0] if candidates else None


def observation_dimensions(state: Path) -> dict[str, dict[str, object]]:
    """Relier un payload compacté à la fixture demandée, sans appel fournisseur."""

    dimensions: dict[str, dict[str, object]] = {}
    for path in sorted((state / "raw" / "observations").rglob("*.json")):
        observation = json.loads(path.read_text("utf-8"))
        payload_hash = str(observation.get("payload_hash", ""))
        parameters = observation.get("request_parameters", {})
        if not payload_hash or not isinstance(parameters, Mapping):
            continue
        dimensions[payload_hash] = {
            "endpoint": observation.get("endpoint"),
            "fixture_id": parameters.get("fixture"),
            "season": parameters.get("season"),
            "observed_at": observation.get("received_at"),
        }
    return dimensions


def _null_counts(value: object) -> tuple[int, int]:
    if isinstance(value, Mapping):
        totals = [_null_counts(item) for item in value.values()]
    elif isinstance(value, list):
        totals = [_null_counts(item) for item in value]
    else:
        return (1 if value is None else 0, 1)
    return sum(item[0] for item in totals), sum(item[1] for item in totals)


def _identity_values(payload: Mapping[str, Any], entity: str) -> list[object]:
    if entity == "fixture_player_statistics":
        return [
            item.get("player", {}).get("id")
            for item in payload.get("players", [])
            if isinstance(item, Mapping)
        ]
    if entity == "lineups":
        return [
            item.get("player", {}).get("id")
            for item in [
                *payload.get("startXI", []),
                *payload.get("substitutes", []),
            ]
            if isinstance(item, Mapping)
        ]
    if entity in {"players", "injuries"}:
        player = payload.get("player", {})
        return [player.get("id")] if isinstance(player, Mapping) else []
    return []


def _minutes_values(payload: Mapping[str, Any]) -> list[object]:
    values: list[object] = []
    for item in payload.get("players", []):
        if not isinstance(item, Mapping):
            continue
        statistics = item.get("statistics", [])
        if not isinstance(statistics, list):
            continue
        for statistic in statistics:
            if not isinstance(statistic, Mapping):
                continue
            games = statistic.get("games", {})
            if isinstance(games, Mapping):
                values.append(games.get("minutes"))
    return values


def _season_report(
    state: Path,
    season: int,
    dimensions: Mapping[str, Mapping[str, object]],
) -> dict[str, Any]:
    fixture_path = _partition(state, season, "fixtures")
    if fixture_path is None:
        return {
            "season": season,
            "status": "UNAVAILABLE",
            "fixtures_expected": 0,
            "fixtures_received": 0,
            "canonical_fixtures": 0,
            "results_received": 0,
            "team_identity_rate": None,
            "endpoints": {},
        }
    frame = pd.read_parquet(fixture_path)
    canonical: dict[int, dict[str, Any]] = {}
    classifications = {
        "REGULAR_SEASON_CANONICAL": 0,
        "PLAYOFF_EXCLUDED": 0,
        "CANCELLED": 0,
        "ABANDONED": 0,
        "DUPLICATE": 0,
        "UNAVAILABLE": 0,
    }
    all_team_ids: list[object] = []
    results = 0
    for raw in frame["payload"].tolist():
        payload = _payload(raw)
        fixture = payload.get("fixture", {})
        league = payload.get("league", {})
        teams = payload.get("teams", {})
        goals = payload.get("goals", {})
        if not all(
            isinstance(value, Mapping)
            for value in (fixture, league, teams, goals)
        ):
            classifications["UNAVAILABLE"] += 1
            continue
        fixture_id = fixture.get("id")
        status = str(fixture.get("status", {}).get("short", "")).upper()
        round_name = str(league.get("round", ""))
        if status == "CANC":
            classifications["CANCELLED"] += 1
            continue
        if status in {"ABD", "INT", "SUSP"}:
            classifications["ABANDONED"] += 1
            continue
        if not round_name.startswith(REGULAR_PREFIX):
            classifications["PLAYOFF_EXCLUDED"] += 1
            continue
        if not isinstance(fixture_id, int):
            classifications["UNAVAILABLE"] += 1
            continue
        if fixture_id in canonical:
            classifications["DUPLICATE"] += 1
            continue
        canonical[fixture_id] = payload
        classifications["REGULAR_SEASON_CANONICAL"] += 1
        home = teams.get("home", {})
        away = teams.get("away", {})
        if isinstance(home, Mapping):
            all_team_ids.append(home.get("id"))
        if isinstance(away, Mapping):
            all_team_ids.append(away.get("id"))
        if goals.get("home") is not None and goals.get("away") is not None:
            results += 1
    team_ids = {int(value) for value in all_team_ids if isinstance(value, int)}
    expected = len(team_ids) * (len(team_ids) - 1)
    canonical_ids = set(canonical)
    endpoints: dict[str, object] = {}
    for entity in (
        "teams",
        "players",
        "squads",
        "fixture_team_statistics",
        "fixture_player_statistics",
        "fixture_events",
        "lineups",
        "standings_snapshots",
        "injuries",
    ):
        path = _partition(state, season, entity)
        if path is None:
            endpoints[entity] = {
                "status": "UNAVAILABLE",
                "rows_received": 0,
                "fixtures_received": 0,
                "coverage": 0.0,
                "null_rate": None,
                "identity_rate": None,
                "temporality": "NOT_OBSERVED",
            }
            continue
        endpoint_frame = pd.read_parquet(path)
        fixture_ids: set[int] = set()
        identities: list[object] = []
        exact_elevens: list[bool] = []
        minutes: list[object] = []
        nulls = 0
        cells = 0
        for row in endpoint_frame.to_dict(orient="records"):
            payload = _payload(row.get("payload"))
            payload_nulls, payload_cells = _null_counts(payload)
            nulls += payload_nulls
            cells += payload_cells
            context = dimensions.get(str(row.get("raw_payload_hash", "")), {})
            fixture_id = context.get("fixture_id")
            if isinstance(fixture_id, int):
                fixture_ids.add(fixture_id)
            identities.extend(_identity_values(payload, entity))
            if entity == "fixture_player_statistics":
                minutes.extend(_minutes_values(payload))
            if entity == "lineups":
                start_xi = payload.get("startXI", [])
                exact_elevens.append(isinstance(start_xi, list) and len(start_xi) == 11)
        covered = fixture_ids & canonical_ids
        identity_rate = (
            sum(value is not None for value in identities) / len(identities)
            if identities
            else None
        )
        coherent_minutes = [
            value
            for value in minutes
            if value is None
            or (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= float(value) <= 130
            )
        ]
        fixture_scoped = entity in {
            "fixture_team_statistics",
            "fixture_player_statistics",
            "fixture_events",
            "lineups",
        }
        coverage = (
            len(covered) / expected
            if fixture_scoped and expected
            else 1.0 if len(endpoint_frame) else 0.0
        )
        endpoints[entity] = {
            "status": "AVAILABLE" if len(endpoint_frame) else "UNAVAILABLE",
            "rows_received": len(endpoint_frame),
            "fixtures_received": len(covered),
            "coverage": round(coverage, 6),
            "null_rate": round(nulls / cells, 6) if cells else None,
            "identity_rate": (
                round(identity_rate, 6) if identity_rate is not None else None
            ),
            "minutes_coherence_rate": (
                round(len(coherent_minutes) / len(minutes), 6)
                if minutes
                else None
            ),
            "exact_starting_xi_rate": (
                round(sum(exact_elevens) / len(exact_elevens), 6)
                if exact_elevens
                else None
            ),
            "temporality": (
                "HISTORICAL_NON_POINT_IN_TIME"
                if entity == "injuries"
                else "POST_MATCH_LAG_REQUIRED"
                if fixture_scoped
                else "POINT_IN_TIME_SAFE"
            ),
        }
    team_identity_rate = (
        sum(value is not None for value in all_team_ids) / len(all_team_ids)
        if all_team_ids
        else 0.0
    )
    fixture_rate = len(canonical) / expected if expected else 0.0
    return {
        "season": season,
        "status": (
            "REGULAR_SEASON_CANONICAL"
            if fixture_rate >= 0.98 and results / expected >= 0.98
            else "PARTIAL"
        ),
        "fixtures_expected": expected,
        "fixtures_received": len(frame),
        "canonical_fixtures": len(canonical),
        "fixture_coverage": round(fixture_rate, 6),
        "results_received": results,
        "results_coverage": round(results / expected, 6) if expected else 0.0,
        "teams_received": len(team_ids),
        "team_identity_rate": round(team_identity_rate, 6),
        "classifications": classifications,
        "endpoints": endpoints,
    }


def _minimum(values: Iterable[float | None], default: float = 0.0) -> float:
    present = [value for value in values if value is not None and not math.isnan(value)]
    return min(present) if present else default


def build_multiseason_readiness(
    state: Path,
    *,
    seasons: tuple[int, ...] = tuple(range(2018, 2026)),
) -> dict[str, object]:
    """Évaluer les quatre gates et conserver les raisons de chaque décision."""

    dimensions = observation_dimensions(state)
    season_reports: list[dict[str, Any]] = [
        _season_report(state, season, dimensions) for season in seasons
    ]
    quality_path = state / "quality" / "latest.json"
    quality: dict[str, Any] = (
        json.loads(quality_path.read_text("utf-8"))
        if quality_path.exists()
        else {}
    )
    actual_normalized_rows = sum(
        len(pd.read_parquet(path))
        for path in sorted((state / "parquet").rglob("*.parquet"))
    )
    quality_passed = quality.get("status") == "PASSED"
    provenance_complete = (
        quality_passed
        and int(quality.get("normalized_rows", 0))
        == int(quality.get("provenance_rows", -1))
        == actual_normalized_rows
    )
    canonical_seasons = [
        report
        for report in season_reports
        if float(report.get("fixture_coverage", 0.0)) >= 0.98
        and float(report.get("results_coverage", 0.0)) >= 0.98
    ]
    team_identity = _minimum(
        float(report["team_identity_rate"])
        for report in canonical_seasons
        if report.get("team_identity_rate") is not None
    )
    critical_duplicates = sum(
        int(
            dict(report.get("classifications", {})).get("DUPLICATE", 0)
        )
        for report in season_reports
    )
    temporal_errors = next(
        (
            int(check.get("value", 0))
            for check in quality.get("checks", [])
            if check.get("check") == "NO_FUTURE_DATA"
        ),
        -1,
    )
    gate_a_passed = (
        len(canonical_seasons) >= 5
        and team_identity >= 0.995
        and provenance_complete
        and temporal_errors == 0
        and critical_duplicates == 0
    )

    player_seasons: list[dict[str, Any]] = []
    lineup_seasons: list[dict[str, Any]] = []
    for report in season_reports:
        endpoints = report.get("endpoints", {})
        if not isinstance(endpoints, Mapping):
            continue
        player = endpoints.get("fixture_player_statistics", {})
        if isinstance(player, Mapping) and float(player.get("coverage", 0.0)) >= 0.9:
            player_seasons.append(report)
        lineup = endpoints.get("lineups", {})
        if isinstance(lineup, Mapping) and float(lineup.get("coverage", 0.0)) >= 0.9:
            lineup_seasons.append(report)
    player_identity = _minimum(
        float(
            dict(report["endpoints"])["fixture_player_statistics"].get(
                "identity_rate",
                0.0,
            )
        )
        for report in player_seasons
    )
    minutes_coherence = _minimum(
        float(
            dict(report["endpoints"])["fixture_player_statistics"].get(
                "minutes_coherence_rate",
                0.0,
            )
        )
        for report in player_seasons
    )
    gate_b_passed = (
        len(player_seasons) >= 4
        and player_identity >= 0.99
        and minutes_coherence >= 0.99
        and quality_passed
    )
    lineup_identity = _minimum(
        float(dict(report["endpoints"])["lineups"].get("identity_rate", 0.0))
        for report in lineup_seasons
    )
    exact_elevens = _minimum(
        float(
            dict(report["endpoints"])["lineups"].get(
                "exact_starting_xi_rate",
                0.0,
            )
        )
        for report in lineup_seasons
    )
    gate_c_passed = (
        len(lineup_seasons) >= 3
        and lineup_identity >= 0.99
        and exact_elevens >= 0.99
        and quality_passed
    )
    gate_d_passed = False
    gates = {
        "A": {
            "name": "API_TEAM_DATASET",
            "passed": gate_a_passed,
            "status": "API_TEAM_DATASET_READY" if gate_a_passed else "BLOCKED_BY_COVERAGE",
            "eligible_seasons": [int(report["season"]) for report in canonical_seasons],
            "canonical_seasons": len(canonical_seasons),
            "team_identity_rate": team_identity,
            "provenance_complete": provenance_complete,
            "temporal_errors": temporal_errors,
            "critical_business_duplicates": critical_duplicates,
        },
        "B": {
            "name": "API_PLAYER_DATASET",
            "passed": gate_b_passed,
            "status": "API_PLAYER_DATASET_READY" if gate_b_passed else "BLOCKED_BY_COVERAGE",
            "eligible_seasons": [
                int(str(report["season"])) for report in player_seasons
            ],
            "exploitable_seasons": len(player_seasons),
            "player_identity_rate": player_identity,
            "minutes_coherence_rate": minutes_coherence,
        },
        "C": {
            "name": "POST_LINEUP_SIMULATED",
            "passed": gate_c_passed,
            "status": (
                "POST_LINEUP_SIMULATED_READY"
                if gate_c_passed
                else "BLOCKED_BY_COVERAGE"
            ),
            "eligible_seasons": [
                int(str(report["season"])) for report in lineup_seasons
            ],
            "exploitable_seasons": len(lineup_seasons),
            "lineup_identity_rate": lineup_identity,
            "exact_starting_xi_rate": exact_elevens,
        },
        "D": {
            "name": "INJURY_AVAILABILITY",
            "passed": gate_d_passed,
            "status": "BLOCKED_BY_TEMPORALITY",
            "reason": (
                "Les blessures historiques sont observées rétrospectivement sans "
                "preuve de disponibilité avant le coup d'envoi cible."
            ),
        },
    }
    return {
        "schema_version": "jalon6-readiness-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": "Ligue 1",
        "seasons": season_reports,
        "gates": gates,
        "quality_status": quality.get("status", "NOT_RUN"),
        "provenance_rows": quality.get("provenance_rows", 0),
        "normalized_rows": actual_normalized_rows,
        "status": (
            "DATA_FACTORY_READY"
            if gate_a_passed
            else "WAITING_FOR_BACKFILL_GATES"
        ),
        "production_status": "PRODUCTION_LOCKED",
    }


def readiness_markdown(report: Mapping[str, object]) -> str:
    seasons = report.get("seasons", [])
    gates = report.get("gates", {})
    lines = [
        "# Ligue 1 — readiness multi-saison",
        "",
        f"Généré : `{report.get('generated_at')}`.",
        "",
        "Les couvertures sont calculées depuis les Parquet et observations du "
        "registre durable. Une absence reste une absence ; elle n'est jamais "
        "remplacée par zéro.",
        "",
        "## Gates",
        "",
        "| Gate | Statut | Saisons éligibles |",
        "|---|---|---|",
    ]
    if isinstance(gates, Mapping):
        for gate_name in ("A", "B", "C", "D"):
            gate = gates.get(gate_name, {})
            if not isinstance(gate, Mapping):
                continue
            eligible = gate.get("eligible_seasons", [])
            lines.append(
                f"| {gate_name} | {gate.get('status')} | "
                f"{', '.join(map(str, eligible)) if eligible else '—'} |"
            )
    lines.extend(
        [
            "",
            "## Couverture",
            "",
            "| Saison | Fixtures | Résultats | Stats joueurs | Compositions | Statut |",
            "|---:|---:|---:|---:|---:|---|",
        ]
    )
    if isinstance(seasons, list):
        for season in seasons:
            if not isinstance(season, Mapping):
                continue
            endpoints = season.get("endpoints", {})
            endpoints = endpoints if isinstance(endpoints, Mapping) else {}
            players = endpoints.get("fixture_player_statistics", {})
            lineups = endpoints.get("lineups", {})
            players = players if isinstance(players, Mapping) else {}
            lineups = lineups if isinstance(lineups, Mapping) else {}
            lines.append(
                "| {season} | {fixtures}/{expected} | {results}/{expected} | "
                "{players:.1%} | {lineups:.1%} | {status} |".format(
                    season=season.get("season"),
                    fixtures=season.get("canonical_fixtures", 0),
                    results=season.get("results_received", 0),
                    expected=season.get("fixtures_expected", 0),
                    players=float(players.get("coverage", 0.0)),
                    lineups=float(lineups.get("coverage", 0.0)),
                    status=season.get("status"),
                )
            )
    lines.extend(
        [
            "",
            "## Temporalité",
            "",
            "Les statistiques de la fixture cible restent `POST_MATCH_ONLY`. Les "
            "compositions cibles ne sont autorisées que dans "
            "`POST_LINEUP_SIMULATED`. Les blessures restent "
            "`HISTORICAL_NON_POINT_IN_TIME` et sont exclues des modèles causaux.",
            "",
            "Production : `PRODUCTION_LOCKED`.",
            "",
        ]
    )
    return "\n".join(lines)
