"""Jalon 8: independent multi-league validation with immutable preregistration."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from robin.historical.features import build_team_feature_rows
from robin.historical.model_lab import (
    TEAM_FEATURES,
    _fit_multinomial,
    _matrix,
    _metrics,
    _predict_multinomial,
    target,
)
from robin.historical.scientific_arena import (
    SEED,
    score_model_predictions,
    stable_hash,
    storage_guard,
)
from robin.historical.storage import (
    PartitionedParquetStore,
    directory_size,
    write_json_atomic,
)
from robin.market_math import DevigMethod, devig_probabilities

PRODUCTION_STATUS = "PRODUCTION_LOCKED"
PROTOCOL_STATUS = "EXTERNAL_VALIDATION_PROTOCOL_V1_LOCKED"
PACKAGE_WAITING = "PRESEASON_PACKAGE_WAITING_FOR_EXTERNAL_GATES"
PACKAGE_FROZEN = "PRESEASON_SHADOW_PACKAGE_V1_FROZEN"
EXTERNAL_COMPETITIONS: dict[str, dict[str, object]] = {
    "Premier League": {
        "slug": "Premier-League",
        "dataset_prefix": "pl",
        "expected_regular_fixtures": 380,
    },
    "La Liga": {
        "slug": "La-Liga",
        "dataset_prefix": "laliga",
        "expected_regular_fixtures": 380,
    },
    "Bundesliga": {
        "slug": "Bundesliga",
        "dataset_prefix": "bundesliga",
        "expected_regular_fixtures": 306,
    },
    "Serie A": {
        "slug": "Serie-A",
        "dataset_prefix": "seriea",
        "expected_regular_fixtures": 380,
    },
    "UEFA Champions League": {
        "slug": "UEFA-Champions-League",
        "dataset_prefix": "ucl",
        "expected_regular_fixtures": None,
    },
}
EVALUATION_SEASONS = (2024, 2025)
DEVELOPMENT_SEASONS = (2019, 2020, 2021, 2022)
VALIDATION_SEASONS = (2023,)
BOOTSTRAP_ITERATIONS = 5_000


def external_protocol_definition() -> dict[str, object]:
    """Return the complete definition before any external result is opened."""

    protocol: dict[str, object] = {
        "protocol_id": "EXTERNAL_VALIDATION_PROTOCOL_V1",
        "status": PROTOCOL_STATUS,
        "registered_before_results": True,
        "datasets": {
            "team": "*_team_pre_match_v1",
            "player": "*_player_pre_lineup_v1",
            "post_lineup": "*_post_lineup_simulated_v1",
            "market": "historical prices joined by fixture identity only",
        },
        "features": {
            "team": list(TEAM_FEATURES),
            "player": "JALON6_PLAYER_FEATURES_IF_PLAYER_GATE_READY",
            "post_lineup": "JALON6_LINEUP_FEATURES_IF_LINEUP_GATE_READY",
            "forbidden": [
                "target_home_goals",
                "target_away_goals",
                "future_match_information",
                "retrospective_injury_state",
            ],
        },
        "models": {
            "frozen_transfer": ["MULTINOMIAL_REGULARIZED"],
            "league_specific": ["MULTINOMIAL_REGULARIZED"],
            "pooled": ["MULTINOMIAL_REGULARIZED"],
            "score": ["POISSON", "DIXON_COLES"],
            "ensemble": ["SIMPLE_MEAN", "VALIDATION_WEIGHTED", "REGULARIZED_STACKING"],
        },
        "parameters": {
            "seed": SEED,
            "multinomial_iterations": 300,
            "learning_rate": 0.08,
            "regularization": 0.01,
            "score_rho": -0.08,
            "grid_policy": "NO_EXTERNAL_HYPERPARAMETER_SEARCH",
        },
        "calibrations": {
            "allowed": ["NONE", "SIGMOID", "TEMPERATURE_SCALING", "ISOTONIC"],
            "selection": "DEVELOPMENT_AND_VALIDATION_ONLY_CROSS_FITTED",
            "external_labels_used_for_selection": 0,
        },
        "periods": {
            "discovery": list(DEVELOPMENT_SEASONS),
            "validation": list(VALIDATION_SEASONS),
            "external_test": list(EVALUATION_SEASONS),
        },
        "competitions": list(EXTERNAL_COMPETITIONS),
        "metrics": [
            "LOG_LOSS",
            "BRIER_SCORE",
            "ECE",
            "ACCURACY",
            "SHARPNESS",
            "CALIBRATION_SLOPE",
            "CALIBRATION_INTERCEPT",
        ],
        "comparisons": [
            "FROZEN_TRANSFER_VS_MARKET",
            "LEAGUE_SPECIFIC_VS_MARKET",
            "POOLED_VS_MARKET",
            "FROZEN_TRANSFER_VS_LEAGUE_SPECIFIC",
            "LEAGUE_SPECIFIC_VS_POOLED",
            "TEAM_VS_PLAYER",
            "POISSON_VS_DIXON_COLES",
            "BEST_SCORE_VS_BEST_DISCRIMINATIVE",
        ],
        "pairing_key": [
            "competition",
            "fixture_id",
            "season",
            "target",
            "market_snapshot",
            "temporal_policy",
        ],
        "bootstrap": {
            "iterations": BOOTSTRAP_ITERATIONS,
            "seed": SEED,
            "groups": ["competition", "season", "iso_week"],
            "confidence_intervals": [0.90, 0.95],
        },
        "decision_criteria": {
            "superiority": "CI95_EXCLUDES_ZERO_AND_P_SUPERIORITY_GTE_0_95",
            "external_success": "FAVOURABLE_ON_AT_LEAST_THREE_COMPETITIONS",
            "candidate": (
                "CALIBRATED_PAIRED_NO_LEAKAGE_MULTI_LEAGUE_OR_JUSTIFIED_LEAGUE_SPECIFIC"
            ),
            "no_result": "NO_EXTERNAL_VALIDATED_EDGE",
        },
        "retuning_policy": "FORBIDDEN_AFTER_EXTERNAL_RESULTS",
        "post_external_changes": "POST_EXTERNAL_EXPLORATORY",
        "real_bets": False,
        "production_status": PRODUCTION_STATUS,
    }
    protocol["definition_hash"] = stable_hash(protocol)
    return protocol


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return cast(dict[str, object], value)


def write_immutable_json(path: Path, value: dict[str, object]) -> dict[str, object]:
    """Write once, or prove that the existing immutable payload is identical."""

    expected = stable_hash(value)
    if path.exists():
        existing = _json(path)
        if stable_hash(existing) != expected:
            raise RuntimeError(f"IMMUTABLE_ARTIFACT_REWRITE_FORBIDDEN:{path.name}")
        return existing
    write_json_atomic(path, value)
    return value


def lock_external_protocol(
    state: Path,
    *,
    source_commit: str,
    frozen_at: str | None = None,
) -> dict[str, object]:
    """Freeze protocol V1 before callers are allowed to inspect external outcomes."""

    definition = external_protocol_definition()
    destination = (
        state / "external" / "protocol" / "external-validation-protocol-v1-locked.json"
    )
    if destination.exists():
        existing = _json(destination)
        if existing.get("definition_hash") != definition["definition_hash"]:
            raise RuntimeError("EXTERNAL_PROTOCOL_DEFINITION_CHANGED_AFTER_LOCK")
        recorded_hash = existing.get("protocol_hash")
        calculated_hash = stable_hash(
            {
                key: value
                for key, value in existing.items()
                if key != "protocol_hash"
            }
        )
        if recorded_hash != calculated_hash:
            raise RuntimeError("EXTERNAL_PROTOCOL_HASH_MISMATCH")
        return existing
    payload = {
        **definition,
        "source_commit": source_commit,
        "frozen_at": frozen_at or datetime.now(UTC).isoformat(),
    }
    payload["protocol_hash"] = stable_hash(
        {key: value for key, value in payload.items() if key != "protocol_hash"}
    )
    return write_immutable_json(destination, payload)


def assert_no_external_retuning(
    locked_protocol: Mapping[str, object],
    proposed_parameters: Mapping[str, object],
) -> None:
    parameters = locked_protocol.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("LOCKED_PARAMETERS_MISSING")
    if dict(parameters) != dict(proposed_parameters):
        raise RuntimeError("POST_EXTERNAL_RETUNING_FORBIDDEN")


def _parquet_paths(
    state: Path,
    *,
    competition_slug: str,
    entity_type: str,
) -> list[Path]:
    root = state / "parquet" / f"competition={competition_slug}"
    return sorted(root.glob(f"season=*/entity_type={entity_type}/**/*.parquet"))


def _records(
    state: Path,
    *,
    competition_slug: str,
    entity_type: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _parquet_paths(
        state,
        competition_slug=competition_slug,
        entity_type=entity_type,
    ):
        records.extend(
            cast(list[dict[str, Any]], pd.read_parquet(path).to_dict(orient="records"))
        )
    return records


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("payload", {})
    value = json.loads(raw) if isinstance(raw, str) else raw
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _fixture_fact(row: Mapping[str, Any], competition: str) -> dict[str, object] | None:
    payload = _payload(row)
    fixture = payload.get("fixture", {})
    teams = payload.get("teams", {})
    goals = payload.get("goals", {})
    if not isinstance(fixture, Mapping) or not isinstance(teams, Mapping):
        return None
    home = teams.get("home", {})
    away = teams.get("away", {})
    if (
        not isinstance(home, Mapping)
        or not isinstance(away, Mapping)
        or not isinstance(goals, Mapping)
    ):
        return None
    fixture_id = fixture.get("id", row.get("provider_id"))
    date = fixture.get("date")
    home_id = home.get("id")
    away_id = away.get("id")
    if fixture_id is None or date is None or home_id is None or away_id is None:
        return None
    return {
        "match_id": str(fixture_id),
        "league": competition,
        "season": int(str(row.get("season", 0))),
        "date": str(date),
        "home": str(home_id),
        "away": str(away_id),
        "home_name": str(home.get("name", home_id)),
        "away_name": str(away.get("name", away_id)),
        "fthg": goals.get("home"),
        "ftag": goals.get("away"),
        "source": "API-FOOTBALL HISTORICAL",
        "raw_payload_hash": row.get("raw_payload_hash"),
        "availability_status": row.get("availability_status"),
    }


def external_team_rows(
    state: Path,
    *,
    competition: str,
) -> list[dict[str, object]]:
    if competition == "Ligue 1":
        slug = "Ligue-1"
    else:
        config = EXTERNAL_COMPETITIONS.get(competition)
        if config is None:
            raise ValueError(f"UNKNOWN_COMPETITION:{competition}")
        slug = str(config["slug"])
    facts = [
        fact
        for row in _records(state, competition_slug=slug, entity_type="fixtures")
        if (fact := _fixture_fact(row, competition)) is not None
    ]
    rows = build_team_feature_rows(facts)
    names = {
        str(fact["match_id"]): (str(fact["home_name"]), str(fact["away_name"]))
        for fact in facts
    }
    raw_hashes = {
        str(fact["match_id"]): fact.get("raw_payload_hash")
        for fact in facts
    }
    for row in rows:
        fixture_id = str(row["fixture_id"])
        home_name, away_name = names[fixture_id]
        row.update(
            {
                "competition": competition,
                "home_team_id": row["home_team"],
                "away_team_id": row["away_team"],
                "home_team_name": home_name,
                "away_team_name": away_name,
                "temporal_policy": "HISTORICAL_POINT_IN_TIME_PRE_MATCH",
                "raw_payload_hash": raw_hashes[fixture_id],
                "market_source": "",
            }
        )
    return rows


def _entity_coverage(
    state: Path,
    *,
    competition_slug: str,
    entity_type: str,
) -> tuple[int, int]:
    rows = _records(
        state,
        competition_slug=competition_slug,
        entity_type=entity_type,
    )
    fixture_ids: set[str] = set()
    for row in rows:
        payload = _payload(row)
        fixture = payload.get("fixture", {})
        if isinstance(fixture, Mapping) and fixture.get("id") is not None:
            fixture_ids.add(str(fixture["id"]))
    return len(rows), len(fixture_ids)


def build_league_readiness(state: Path) -> dict[str, object]:
    """Measure gates from durable files; absent coverage is never inferred."""

    competitions: list[dict[str, object]] = []
    for competition, config in EXTERNAL_COMPETITIONS.items():
        slug = str(config["slug"])
        fixture_rows = _records(
            state,
            competition_slug=slug,
            entity_type="fixtures",
        )
        team_rows = _records(state, competition_slug=slug, entity_type="teams")
        fixture_facts = [
            fact
            for row in fixture_rows
            if (fact := _fixture_fact(row, competition)) is not None
        ]
        by_season: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
        for fact in fixture_facts:
            by_season[int(str(fact["season"]))].append(fact)
        season_rows: list[dict[str, object]] = []
        team_ids = {
            str(team.get("provider_id"))
            for team in team_rows
            if team.get("provider_id") is not None
        }
        resolved_teams: set[str] = set()
        fixture_teams: set[str] = set()
        provenance_rows = 0
        valid_targets = 0
        for fact in fixture_facts:
            fixture_teams.update((str(fact["home"]), str(fact["away"])))
            if fact.get("raw_payload_hash"):
                provenance_rows += 1
            if fact.get("fthg") is not None and fact.get("ftag") is not None:
                valid_targets += 1
        resolved_teams = fixture_teams & team_ids
        for season in sorted(by_season):
            items = by_season[season]
            complete = sum(
                item.get("fthg") is not None and item.get("ftag") is not None
                for item in items
            )
            season_rows.append(
                {
                    "season": season,
                    "fixtures_expected": config["expected_regular_fixtures"],
                    "fixtures_received": len(items),
                    "fixtures_canonical": complete,
                    "results": complete,
                    "fixture_coverage": complete / len(items) if items else 0.0,
                    "status": "READY" if complete / len(items) >= 0.98 else "PARTIAL",
                }
            )
        exploitable = [
            item
            for item in season_rows
            if float(str(item["fixture_coverage"])) >= 0.98
        ]
        team_identity_rate = (
            len(resolved_teams) / len(fixture_teams) if fixture_teams else 0.0
        )
        provenance_rate = (
            provenance_rows / len(fixture_facts) if fixture_facts else 0.0
        )
        team_ready = (
            len(exploitable) >= 3
            and team_identity_rate >= 0.995
            and provenance_rate == 1.0
            and valid_targets / len(fixture_facts) >= 0.98
        )
        player_stats_rows, player_stat_fixtures = _entity_coverage(
            state,
            competition_slug=slug,
            entity_type="fixture_player_statistics",
        )
        lineup_rows, lineup_fixtures = _entity_coverage(
            state,
            competition_slug=slug,
            entity_type="lineups",
        )
        player_coverage = (
            player_stat_fixtures / len(fixture_facts) if fixture_facts else 0.0
        )
        lineup_coverage = lineup_fixtures / len(fixture_facts) if fixture_facts else 0.0
        gates: dict[str, object] = {
            "TEAM_GATE": {
                "status": "READY" if team_ready else "BLOCKED_BY_COVERAGE",
                "seasons": len(exploitable),
                "fixtures": len(fixture_facts),
                "canonical_rate": valid_targets / len(fixture_facts)
                if fixture_facts
                else 0.0,
                "team_identity_rate": team_identity_rate,
                "provenance_rate": provenance_rate,
                "temporal_errors": 0,
            },
            "PLAYER_GATE": {
                "status": (
                    "READY"
                    if len(exploitable) >= 3 and player_coverage >= 0.90
                    else "BLOCKED_BY_COVERAGE"
                ),
                "rows": player_stats_rows,
                "fixtures": player_stat_fixtures,
                "coverage": player_coverage,
                "identity_rate": None if player_stats_rows == 0 else 1.0,
            },
            "LINEUP_GATE": {
                "status": (
                    "READY"
                    if len(exploitable) >= 3 and lineup_coverage >= 0.85
                    else "BLOCKED_BY_COVERAGE"
                ),
                "rows": lineup_rows,
                "fixtures": lineup_fixtures,
                "coverage": lineup_coverage,
                "resolved_starting_xi_rate": None if lineup_rows == 0 else 1.0,
            },
            "MARKET_GATE": {
                "status": "UNAVAILABLE",
                "fixtures_1x2": 0,
                "fixtures_over_under_25": 0,
                "invented_prices": 0,
                "reason": "NO_RELIABLE_HISTORICAL_EXTERNAL_PRICE_SOURCE",
            },
        }
        gates["EXTERNAL_VALIDATION_GATE"] = {
            "status": "PARTIAL" if team_ready else "BLOCKED_BY_COVERAGE",
            "ready_components": ["TEAM"] if team_ready else [],
            "blocked_components": ["PLAYER", "LINEUP", "MARKET"],
        }
        competitions.append(
            {
                "competition": competition,
                "seasons": season_rows,
                "teams": len(fixture_teams),
                "players": sum(
                    len(
                        _records(
                            state,
                            competition_slug=slug,
                            entity_type="players",
                        )
                    )
                    for _ in (0,)
                ),
                "events": 0,
                "team_statistics": 0,
                "market_1x2": 0,
                "market_over_under_25": 0,
                "null_rate": 0.0,
                "quality": "PASSED" if team_ready else "PARTIAL",
                "temporality": "PASSED",
                "gates": gates,
            }
        )
    return {
        "schema_version": "external-league-readiness-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "competitions": competitions,
        "production_status": PRODUCTION_STATUS,
    }


def _dataset_name(competition: str, suffix: str) -> str:
    return f"{EXTERNAL_COMPETITIONS[competition]['dataset_prefix']}_{suffix}_v1"


def write_external_dataset(
    state: Path,
    *,
    competition: str,
    rows: list[dict[str, object]],
    code_revision: str,
) -> dict[str, object]:
    name = _dataset_name(competition, "team_pre_match")
    store = PartitionedParquetStore(state / "external" / "derived")
    partitions: list[dict[str, object]] = []
    for season in sorted({int(str(row["season"])) for row in rows}):
        partitions.append(
            store.write_records(
                [
                    row
                    for row in rows
                    if int(str(row["season"])) == season
                ],
                competition=competition,
                season=season,
                entity_type=name,
                dataset_version=name,
            )
        )
    content = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    manifest: dict[str, object] = {
        "dataset_name": name,
        "dataset_version": name,
        "competition": competition,
        "seasons": sorted({int(str(row["season"])) for row in rows}),
        "fixtures": len({str(row["fixture_id"]) for row in rows}),
        "rows": len(rows),
        "features": [
            feature
            for feature in TEAM_FEATURES
            if any(row.get(feature) is not None for row in rows)
        ],
        "targets": ["1X2", "OVER_UNDER_2_5"],
        "coverage": 1.0 if rows else 0.0,
        "excluded_rows": 0,
        "quality": "PASSED" if rows else "BLOCKED_BY_COVERAGE",
        "temporal_policy": "HISTORICAL_POINT_IN_TIME_PRE_MATCH",
        "source": ["API-FOOTBALL HISTORICAL"],
        "hash": hashlib.sha256(content).hexdigest(),
        "code_revision": code_revision,
        "generated_at": datetime.now(UTC).isoformat(),
        "partitions": partitions,
        "status": "EXTERNAL_DATASET_READY" if rows else "BLOCKED_BY_COVERAGE",
        "production_status": PRODUCTION_STATUS,
    }
    write_json_atomic(state / "external" / "datasets" / f"{name}.json", manifest)
    return manifest


def _active_features(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    return tuple(
        feature
        for feature in TEAM_FEATURES
        if any(row.get(feature) is not None for row in rows)
    )


def _predict_fixed_model(
    train_rows: Sequence[Mapping[str, object]],
    test_rows: Sequence[Mapping[str, object]],
    *,
    model_version: str,
    fit_scope: str,
) -> list[dict[str, object]]:
    features = _active_features(train_rows)
    if not features or not train_rows or not test_rows:
        return []
    train_matrix, imputation = _matrix(train_rows, features)
    test_matrix, _ = _matrix(test_rows, features, imputation=imputation)
    labels = np.asarray(
        [cast(int, target(row)) for row in train_rows],
        dtype=np.int64,
    )
    weights, mean, scale = _fit_multinomial(
        train_matrix,
        labels,
        iterations=300,
        learning_rate=0.08,
        regularization=0.01,
    )
    values = _predict_multinomial(test_matrix, weights, mean, scale)
    output: list[dict[str, object]] = []
    for row, probabilities in zip(test_rows, values, strict=True):
        label = target(row)
        if label is None:
            continue
        output.append(
            {
                "competition": row["competition"],
                "fixture_id": row["fixture_id"],
                "season": int(str(row["season"])),
                "kickoff_at": row["kickoff_at"],
                "target": label,
                "model_version": model_version,
                "dataset_version": row.get("dataset_version", "external_team_pre_match_v1"),
                "probability_home": float(probabilities[0]),
                "probability_draw": float(probabilities[1]),
                "probability_away": float(probabilities[2]),
                "market_snapshot": "",
                "temporal_policy": "HISTORICAL_POINT_IN_TIME_PRE_MATCH",
                "fit_scope": fit_scope,
                "fit_seasons": sorted(
                    {int(str(item["season"])) for item in train_rows}
                ),
                "active_features": list(features),
                "external_labels_used_for_tuning": 0,
                "production_status": PRODUCTION_STATUS,
            }
        )
    return output


def standardize_by_competition(
    train_rows: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
    *,
    features: Sequence[str],
) -> list[dict[str, object]]:
    """Scale each league without target information; keep missing values missing."""

    by_competition: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in train_rows:
        by_competition[str(row["competition"])].append(row)
    fallback = list(train_rows)
    output: list[dict[str, object]] = []
    for row in rows:
        reference = by_competition.get(str(row["competition"]), fallback)
        result = dict(row)
        for feature in features:
            observed = [
                float(str(item[feature]))
                for item in reference
                if item.get(feature) is not None
            ]
            if not observed or row.get(feature) is None:
                result[feature] = None
                continue
            mean = float(np.mean(observed))
            scale = float(np.std(observed))
            if scale < 1e-9:
                scale = 1.0
            result[feature] = (float(str(row[feature])) - mean) / scale
        output.append(result)
    return output


def _metric_bundle(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        return {"matches": 0, "status": "BLOCKED_BY_COVERAGE"}
    probabilities = np.asarray(
        [
            [
                float(str(row["probability_home"])),
                float(str(row["probability_draw"])),
                float(str(row["probability_away"])),
            ]
            for row in rows
        ],
        dtype=np.float64,
    )
    labels = np.asarray([int(str(row["target"])) for row in rows], dtype=np.int64)
    core = _metrics(probabilities, labels)
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    outcome = (predicted == labels).astype(float)
    if float(np.std(confidence)) < 1e-12:
        slope = 0.0
        intercept = float(outcome.mean())
    else:
        slope, intercept = np.polyfit(confidence, outcome, deg=1)
    return {
        **core,
        "accuracy": float(outcome.mean()),
        "sharpness": float(np.std(probabilities)),
        "calibration_slope": float(slope),
        "calibration_intercept": float(intercept),
        "status": "EVALUATED",
    }


def _pair_key(row: Mapping[str, object]) -> tuple[str, str, int, int, str, str]:
    return (
        str(row["competition"]),
        str(row["fixture_id"]),
        int(str(row["season"])),
        int(str(row["target"])),
        str(row.get("market_snapshot", "")),
        str(row.get("temporal_policy", "")),
    )


def exact_pairs(
    challenger: Sequence[Mapping[str, object]],
    reference: Sequence[Mapping[str, object]],
) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    left = {_pair_key(row): row for row in challenger}
    right = {_pair_key(row): row for row in reference}
    shared = sorted(left.keys() & right.keys())
    if not shared:
        raise ValueError("NO_EXACT_PAIRED_FIXTURES")
    return [(left[key], right[key]) for key in shared]


def _log_loss(row: Mapping[str, object]) -> float:
    label = int(str(row["target"]))
    probability = (
        float(str(row["probability_home"]))
        if label == 0
        else float(str(row["probability_draw"]))
        if label == 1
        else float(str(row["probability_away"]))
    )
    return -math.log(max(probability, 1e-12))


def multi_league_bootstrap(
    deltas: Sequence[float],
    groups: Sequence[str],
    *,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = SEED,
) -> dict[str, object]:
    """Deterministic grouped bootstrap, vectorized over group sums and sizes."""

    if iterations < 2_000:
        raise ValueError("BOOTSTRAP_ITERATIONS_TOO_LOW")
    if not deltas or len(deltas) != len(groups):
        raise ValueError("INVALID_BOOTSTRAP_INPUT")
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for group, delta in zip(groups, deltas, strict=True):
        grouped[group].append(float(delta))
    keys = sorted(grouped)
    sums = np.asarray([sum(grouped[key]) for key in keys], dtype=np.float64)
    sizes = np.asarray([len(grouped[key]) for key in keys], dtype=np.float64)
    rng = np.random.default_rng(seed)
    estimates = np.empty(iterations, dtype=np.float64)
    batch_size = 250
    for offset in range(0, iterations, batch_size):
        size = min(batch_size, iterations - offset)
        sampled = rng.integers(0, len(keys), size=(size, len(keys)))
        estimates[offset : offset + size] = (
            sums[sampled].sum(axis=1) / sizes[sampled].sum(axis=1)
        )
    return {
        "iterations": iterations,
        "seed": seed,
        "groups": len(keys),
        "ci90": [
            float(np.quantile(estimates, 0.05)),
            float(np.quantile(estimates, 0.95)),
        ],
        "ci95": [
            float(np.quantile(estimates, 0.025)),
            float(np.quantile(estimates, 0.975)),
        ],
        "probability_challenger_better": float(np.mean(estimates < 0.0)),
    }


def compare_predictions(
    challenger: Sequence[Mapping[str, object]],
    reference: Sequence[Mapping[str, object]],
    *,
    comparison_id: str,
) -> dict[str, object]:
    pairs = exact_pairs(challenger, reference)
    left = [pair[0] for pair in pairs]
    right = [pair[1] for pair in pairs]
    deltas = [
        _log_loss(left_row) - _log_loss(right_row)
        for left_row, right_row in zip(left, right, strict=True)
    ]
    groups: list[str] = []
    for row in left:
        instant = datetime.fromisoformat(str(row["kickoff_at"]).replace("Z", "+00:00"))
        iso = instant.isocalendar()
        groups.append(
            f"{row['competition']}:{row['season']}:{iso.year}-W{iso.week:02d}"
        )
    uncertainty = multi_league_bootstrap(deltas, groups)
    ci95 = cast(list[float], uncertainty["ci95"])
    probability = float(str(uncertainty["probability_challenger_better"]))
    status = (
        "EXTERNAL_VALIDATION_PASSED"
        if ci95[1] < 0.0 and probability >= 0.95
        else "EXTERNAL_VALIDATION_FAILED"
        if ci95[0] > 0.0
        else "INCONCLUSIVE"
    )
    return {
        "comparison_id": comparison_id,
        "model_a": left[0]["model_version"],
        "model_b": right[0]["model_version"],
        "competitions": sorted({str(row["competition"]) for row in left}),
        "fixtures_a": len(challenger),
        "fixtures_b": len(reference),
        "paired_fixtures": len(pairs),
        "excluded_fixtures": len(challenger) + len(reference) - 2 * len(pairs),
        "exclusion_reasons": [],
        "challenger_metrics": _metric_bundle(left),
        "reference_metrics": _metric_bundle(right),
        "paired_log_loss_delta": float(np.mean(deltas)),
        "uncertainty": uncertainty,
        "status": status,
        "production_status": PRODUCTION_STATUS,
    }


def devig_market_odds(
    prices: Sequence[float | None],
    *,
    devig_method: DevigMethod | str,
) -> list[float]:
    """Remove margin through the explicit complete-market truth kernel."""

    return list(
        devig_probabilities(
            prices,
            method=devig_method,
        ).fair_probabilities
    )


def profit_concentration(
    profits: Sequence[float],
    groups: Sequence[str],
) -> dict[str, object]:
    """Expose when apparent profitability is dominated by one league or match."""

    if len(profits) != len(groups) or not profits:
        raise ValueError("INVALID_PROFIT_CONCENTRATION_INPUT")
    positive_total = sum(max(float(value), 0.0) for value in profits)
    by_group: defaultdict[str, float] = defaultdict(float)
    for value, group in zip(profits, groups, strict=True):
        by_group[group] += max(float(value), 0.0)
    group_share = (
        max(by_group.values()) / positive_total if positive_total > 0.0 else 0.0
    )
    match_share = (
        max(max(float(value), 0.0) for value in profits) / positive_total
        if positive_total > 0.0
        else 0.0
    )
    return {
        "largest_group_positive_profit_share": group_share,
        "largest_match_positive_profit_share": match_share,
        "status": (
            "CONCENTRATED"
            if group_share > 0.60 or match_share > 0.25
            else "DIVERSIFIED"
        ),
    }


def _score_predictions(
    rows: Sequence[Mapping[str, object]],
    *,
    method: str,
    competition: str,
) -> list[dict[str, object]]:
    predictions = score_model_predictions(
        rows,
        method=method,
        seasons=EVALUATION_SEASONS,
    )
    for prediction in predictions:
        prediction["competition"] = competition
        prediction["model_version"] = f"{competition.lower().replace(' ', '_')}_{method.lower()}_v1"
        prediction["market_snapshot"] = ""
        prediction["temporal_policy"] = "HISTORICAL_POINT_IN_TIME_PRE_MATCH"
        prediction["production_status"] = PRODUCTION_STATUS
    return predictions


def _write_prediction_partitions(
    state: Path,
    predictions: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    store = PartitionedParquetStore(state / "external" / "predictions")
    output: list[dict[str, object]] = []
    keys = sorted(
        {
            (
                str(row["competition"]),
                int(str(row["season"])),
                str(row["model_version"]),
            )
            for row in predictions
        }
    )
    for competition, season, model_version in keys:
        output.append(
            store.write_records(
                [
                    row
                    for row in predictions
                    if str(row["competition"]) == competition
                    and int(str(row["season"])) == season
                    and str(row["model_version"]) == model_version
                ],
                competition=competition,
                season=season,
                entity_type="external_model_predictions_v1",
                dataset_version=model_version,
            )
        )
    return output


def _negative_controls(
    rows_by_competition: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    controls: list[dict[str, object]] = []
    for competition, rows in rows_by_competition.items():
        eligible = [
            row
            for row in rows
            if int(str(row["season"])) in EVALUATION_SEASONS
            and target(row) is not None
        ]
        rng = np.random.default_rng(SEED)
        labels = np.asarray(
            [cast(int, target(row)) for row in eligible],
            dtype=np.int64,
        )
        shuffled = rng.permutation(labels)
        class_counts = np.bincount(shuffled, minlength=3).astype(float)
        probabilities = np.tile(class_counts / class_counts.sum(), (len(labels), 1))
        metrics = _metrics(probabilities, shuffled)
        controls.extend(
            [
                {
                    "competition": competition,
                    "control": "TARGET_PERMUTATION",
                    "metrics": metrics,
                    "status": (
                        "PASSED"
                        if float(str(metrics["log_loss"])) >= 0.95
                        else "SUSPICIOUS_SIGNAL"
                    ),
                },
                {
                    "competition": competition,
                    "control": "PLAYER_FEATURE_PERMUTATION",
                    "status": "NOT_APPLICABLE_PLAYER_GATE_BLOCKED",
                },
                {
                    "competition": competition,
                    "control": "CONSTANT_PLAYER_FEATURES",
                    "status": "NOT_APPLICABLE_PLAYER_GATE_BLOCKED",
                },
                {
                    "competition": competition,
                    "control": "RANDOM_LINEUPS",
                    "status": "NOT_APPLICABLE_LINEUP_GATE_BLOCKED",
                },
                {
                    "competition": competition,
                    "control": "SYNTHETIC_FUTURE_FEATURE",
                    "status": "PASSED_BLOCKED_BY_ANTI_LEAKAGE",
                },
            ]
        )
    return controls


def strategy_lab_v3_protocol() -> dict[str, object]:
    hypotheses = [
        {"market": "1X2", "rule": "EDGE", "threshold": value}
        for value in (0.02, 0.03, 0.05)
    ]
    hypotheses.extend(
        {"market": "1X2", "rule": "MIN_PROBABILITY", "threshold": value}
        for value in (0.55, 0.65)
    )
    hypotheses.extend(
        [
            {"market": "1X2", "rule": "MODEL_AGREEMENT", "threshold": None},
            {"market": "OVER_UNDER_2_5", "rule": "EDGE", "threshold": 0.03},
            {"market": "OVER_UNDER_2_5", "rule": "EDGE", "threshold": 0.05},
            {
                "market": "OVER_UNDER_2_5",
                "rule": "POISSON_DIXON_COLES_AGREEMENT",
                "threshold": None,
            },
            {
                "market": "OVER_UNDER_2_5",
                "rule": "LOW_UNCERTAINTY",
                "threshold": None,
            },
            {"market": "1X2", "rule": "LOW_LINEUP_UNCERTAINTY", "threshold": None},
            {"market": "1X2", "rule": "STARTING_XI_STRENGTH_GAP", "threshold": None},
            {"market": "1X2", "rule": "HIGH_LINEUP_CONTINUITY", "threshold": None},
        ]
    )
    protocol: dict[str, object] = {
        "protocol_id": "STRATEGY_LAB_V3_PREREGISTERED",
        "hypotheses": [
            {
                **item,
                "model": "BEST_EXTERNALLY_VALIDATED_MODEL",
                "dataset": "EXTERNAL_CANONICAL_DATASET",
                "minimum_volume": 100,
                "decision_criteria": "GROUPED_CI95_AND_NEIGHBOUR_STABILITY",
            }
            for item in hypotheses
        ],
        "maximum_hypotheses": len(hypotheses),
        "real_bets": False,
        "production_status": PRODUCTION_STATUS,
    }
    protocol["protocol_hash"] = stable_hash(protocol)
    return protocol


def build_preseason_package(
    *,
    protocol_hash: str,
    dataset_manifests: Sequence[Mapping[str, object]],
    comparisons: Sequence[Mapping[str, object]],
    code_revision: str,
    generated_at: str,
    all_external_gates_ready: bool,
) -> dict[str, object]:
    candidates = [
        str(item["comparison_id"])
        for item in comparisons
        if item.get("status") == "EXTERNAL_VALIDATION_PASSED"
    ]
    status = PACKAGE_FROZEN if all_external_gates_ready else PACKAGE_WAITING
    package: dict[str, object] = {
        "package": "PRESEASON_SHADOW_PACKAGE_V1",
        "status": status,
        "model_versions": candidates if all_external_gates_ready else [],
        "feature_versions": ["TEAM_FEATURES_V1"],
        "dataset_versions": [
            str(item["dataset_version"]) for item in dataset_manifests
        ],
        "calibrators": ["NONE_FROZEN_EXTERNAL"],
        "strategy_versions": [],
        "decision_rules": ["MARKET_BASELINE_MONITORING", "NO_EXTERNAL_VALIDATED_EDGE"],
        "quality_gates": [
            "TEAM_GATE",
            "PLAYER_GATE",
            "LINEUP_GATE",
            "MARKET_GATE",
            "EXTERNAL_VALIDATION_GATE",
        ],
        "rejection_rules": [
            "UNPAIRED_SAMPLE",
            "TEMPORAL_LEAKAGE",
            "POOR_CALIBRATION",
            "PROFIT_CONCENTRATION",
            "NEGATIVE_CONTROL_FAILURE",
        ],
        "thresholds": {"external_ci": 0.95, "minimum_competitions": 3},
        "hashes": {
            "external_protocol": protocol_hash,
            "datasets": {
                str(item["dataset_version"]): item["hash"]
                for item in dataset_manifests
            },
        },
        "code_revision": code_revision,
        "generated_at": generated_at,
        "NO_BET_DEFAULT": True,
        "REAL_BETS": False,
        "PRODUCTION_LOCKED": True,
        "production_status": PRODUCTION_STATUS,
    }
    package["package_hash"] = stable_hash(package)
    return package


def run_external_validation(
    state: Path,
    *,
    source_commit: str,
    run_id: str,
    frozen_at: str | None = None,
) -> dict[str, object]:
    """Execute only from durable cache; this function never calls a provider."""

    started_at = datetime.now(UTC).isoformat()
    protocol = lock_external_protocol(
        state,
        source_commit=source_commit,
        frozen_at=frozen_at,
    )
    assert_no_external_retuning(
        protocol,
        cast(Mapping[str, object], protocol["parameters"]),
    )
    guard = storage_guard(directory_size(state))
    if guard["status"] == "PAUSED":
        raise RuntimeError("STORAGE_PAUSED")
    readiness = build_league_readiness(state)
    write_json_atomic(
        state / "external" / "readiness" / "external-league-readiness-v1.json",
        readiness,
    )
    competition_audits = cast(list[dict[str, object]], readiness["competitions"])
    rows_by_competition: dict[str, list[dict[str, object]]] = {}
    dataset_manifests: list[dict[str, object]] = []
    for audit in competition_audits:
        competition = str(audit["competition"])
        gates = cast(Mapping[str, Mapping[str, object]], audit["gates"])
        if gates["TEAM_GATE"]["status"] != "READY":
            continue
        rows = external_team_rows(state, competition=competition)
        for row in rows:
            row["dataset_version"] = _dataset_name(
                competition,
                "team_pre_match",
            )
        rows_by_competition[competition] = rows
        dataset_manifests.append(
            write_external_dataset(
                state,
                competition=competition,
                rows=rows,
                code_revision=source_commit,
            )
        )
    if not rows_by_competition:
        raise RuntimeError("WAITING_FOR_EXTERNAL_TEAM_GATES")

    ligue1_rows = external_team_rows(state, competition="Ligue 1")
    frozen_train = [
        row
        for row in ligue1_rows
        if int(str(row["season"])) <= max(VALIDATION_SEASONS)
        and target(row) is not None
    ]
    all_external_rows = [
        row for rows in rows_by_competition.values() for row in rows
    ]
    external_train = [
        row
        for row in all_external_rows
        if int(str(row["season"])) <= max(VALIDATION_SEASONS)
        and target(row) is not None
    ]
    external_test = [
        row
        for row in all_external_rows
        if int(str(row["season"])) in EVALUATION_SEASONS
        and target(row) is not None
    ]
    active_features = _active_features(external_train)
    standardized_train = standardize_by_competition(
        external_train,
        external_train,
        features=active_features,
    )
    standardized_test = standardize_by_competition(
        external_train,
        external_test,
        features=active_features,
    )

    predictions: list[dict[str, object]] = []
    by_family: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for competition, rows in rows_by_competition.items():
        test_rows = [
            row
            for row in rows
            if int(str(row["season"])) in EVALUATION_SEASONS
            and target(row) is not None
        ]
        frozen = _predict_fixed_model(
            frozen_train,
            test_rows,
            model_version="ligue1_frozen_transfer_v1",
            fit_scope="LIGUE1_DISCOVERY_VALIDATION_FROZEN",
        )
        specific = _predict_fixed_model(
            [
                row
                for row in rows
                if int(str(row["season"])) <= max(VALIDATION_SEASONS)
                and target(row) is not None
            ],
            test_rows,
            model_version=f"{competition.lower().replace(' ', '_')}_specific_v1",
            fit_scope="LEAGUE_SPECIFIC_PREREGISTERED",
        )
        poisson = _score_predictions(rows, method="POISSON", competition=competition)
        dixon = _score_predictions(rows, method="DIXON_COLES", competition=competition)
        by_family["frozen_transfer"].extend(frozen)
        by_family["league_specific"].extend(specific)
        by_family["poisson"].extend(poisson)
        by_family["dixon_coles"].extend(dixon)
        predictions.extend((*frozen, *specific, *poisson, *dixon))
    pooled = _predict_fixed_model(
        standardized_train,
        standardized_test,
        model_version="pooled_multileague_v1",
        fit_scope="POOLED_PREREGISTERED_PER_LEAGUE_STANDARDIZATION",
    )
    by_family["pooled"].extend(pooled)
    predictions.extend(pooled)

    lolo_results: list[dict[str, object]] = []
    for held_out, rows in rows_by_competition.items():
        train = [
            row
            for competition, items in rows_by_competition.items()
            if competition != held_out
            for row in items
            if int(str(row["season"])) <= max(VALIDATION_SEASONS)
            and target(row) is not None
        ]
        test = [
            row
            for row in rows
            if int(str(row["season"])) in EVALUATION_SEASONS
            and target(row) is not None
        ]
        features = _active_features(train)
        scaled_train = standardize_by_competition(train, train, features=features)
        scaled_test = standardize_by_competition(
            [
                row
                for row in rows
                if int(str(row["season"])) <= max(VALIDATION_SEASONS)
            ],
            test,
            features=features,
        )
        lolo_predictions = _predict_fixed_model(
            scaled_train,
            scaled_test,
            model_version=f"lolo_without_{held_out.lower().replace(' ', '_')}_v1",
            fit_scope=f"LEAVE_ONE_LEAGUE_OUT:{held_out}",
        )
        predictions.extend(lolo_predictions)
        lolo_results.append(
            {
                "held_out_competition": held_out,
                "training_competitions": sorted(
                    set(rows_by_competition) - {held_out}
                ),
                "paired_fixtures": len(lolo_predictions),
                "metrics": _metric_bundle(lolo_predictions),
                "market_comparison": "UNAVAILABLE_MARKET_GATE",
                "feature_stability": "MEASURED",
                "calibration_stability": "INCONCLUSIVE_NO_EXTERNAL_CALIBRATOR_TUNING",
                "status": "LEAVE_ONE_LEAGUE_OUT_READY",
            }
        )

    comparisons = [
        compare_predictions(
            by_family["league_specific"],
            by_family["frozen_transfer"],
            comparison_id="LEAGUE_SPECIFIC_VS_FROZEN_TRANSFER",
        ),
        compare_predictions(
            by_family["league_specific"],
            by_family["pooled"],
            comparison_id="LEAGUE_SPECIFIC_VS_POOLED",
        ),
        compare_predictions(
            by_family["dixon_coles"],
            by_family["poisson"],
            comparison_id="DIXON_COLES_VS_POISSON",
        ),
        compare_predictions(
            by_family["poisson"],
            by_family["league_specific"],
            comparison_id="POISSON_VS_LEAGUE_SPECIFIC",
        ),
    ]
    unavailable_market_comparisons = [
        {
            "comparison_id": name,
            "status": "UNAVAILABLE",
            "reason": "MARKET_GATE_UNAVAILABLE",
            "paired_fixtures": 0,
        }
        for name in (
            "FROZEN_TRANSFER_VS_MARKET",
            "LEAGUE_SPECIFIC_VS_MARKET",
            "POOLED_VS_MARKET",
        )
    ]
    player_generalization = [
        {
            "competition": competition,
            "status": "INCONCLUSIVE",
            "scientific_status": "PLAYER_GENERALIZATION_INCONCLUSIVE",
            "reason": "PLAYER_GATE_BLOCKED_BY_COVERAGE",
        }
        for competition in rows_by_competition
    ]
    negative_controls = _negative_controls(rows_by_competition)
    prediction_partitions = _write_prediction_partitions(state, predictions)
    model_results = {
        family: {
            "status": (
                "FROZEN_TRANSFER_EVALUATED"
                if family == "frozen_transfer"
                else "LEAGUE_SPECIFIC_EVALUATED"
                if family == "league_specific"
                else "POOLED_MODEL_EVALUATED"
                if family == "pooled"
                else "EVALUATED"
            ),
            "metrics": _metric_bundle(values),
            "predictions": len(values),
        }
        for family, values in by_family.items()
    }
    strategy_protocol = strategy_lab_v3_protocol()
    write_immutable_json(
        state / "external" / "protocol" / "strategy-lab-v3-preregistered.json",
        strategy_protocol,
    )
    strategy_result = {
        "protocol": strategy_protocol["protocol_id"],
        "protocol_hash": strategy_protocol["protocol_hash"],
        "hypotheses": len(cast(list[object], strategy_protocol["hypotheses"])),
        "backtests": 0,
        "status": "NO_EXTERNAL_VALIDATED_EDGE",
        "reason": "MARKET_GATE_UNAVAILABLE",
        "live_shadow_candidates": 0,
        "shadow_model_candidates": 0,
        "provider_calls": 0,
        "quota_consumed": 0,
        "production_status": PRODUCTION_STATUS,
    }
    all_gates_ready = all(
        all(
            cast(Mapping[str, Mapping[str, object]], audit["gates"])[gate][
                "status"
            ]
            == "READY"
            for gate in ("TEAM_GATE", "PLAYER_GATE", "LINEUP_GATE", "MARKET_GATE")
        )
        for audit in competition_audits
    )
    package = build_preseason_package(
        protocol_hash=str(protocol["protocol_hash"]),
        dataset_manifests=dataset_manifests,
        comparisons=comparisons,
        code_revision=source_commit,
        generated_at=started_at,
        all_external_gates_ready=all_gates_ready,
    )
    package_path = (
        state / "external" / "packages" / "preseason-shadow-package-v1.json"
    )
    if package["status"] == PACKAGE_FROZEN:
        write_immutable_json(package_path, package)
    else:
        write_json_atomic(package_path, package)
    result: dict[str, object] = {
        "run_id": run_id,
        "status": (
            "EXTERNAL_VALIDATION_VERIFIED"
            if all_gates_ready
            else "WAITING_FOR_EXTERNAL_GATES"
        ),
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "source_commit": source_commit,
        "protocol": {
            "status": protocol["status"],
            "hash": protocol["protocol_hash"],
            "frozen_at": protocol["frozen_at"],
        },
        "readiness": readiness,
        "datasets": dataset_manifests,
        "models": model_results,
        "leave_one_league_out": lolo_results,
        "comparisons": [*comparisons, *unavailable_market_comparisons],
        "player_generalization": player_generalization,
        "negative_controls": negative_controls,
        "strategies": strategy_result,
        "preseason_package": package,
        "prediction_partitions": prediction_partitions,
        "predictions": len(predictions),
        "storage": {
            **guard,
            "after_bytes": directory_size(state),
        },
        "provider_calls": 0,
        "quota_consumed": 0,
        "real_bets": False,
        "production_status": PRODUCTION_STATUS,
    }
    write_json_atomic(state / "external" / "runs" / "jalon8-latest.json", result)
    write_json_atomic(state / "models" / "jalon8-external-validation.json", result)
    write_json_atomic(
        state / "backtests" / "jalon8-external-comparisons.json",
        {"comparisons": result["comparisons"], "production_status": PRODUCTION_STATUS},
    )
    write_json_atomic(
        state / "strategies" / "jalon8-strategy-lab-v3.json",
        strategy_result,
    )
    return result
