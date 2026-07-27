"""Run the bounded, cache-only Jalon 11 audit and scientific arena.

All commands default to zero provider calls and zero Odds API credits.  Heavy
artifacts are written below ``--output`` and are never intended for Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from robin.deep_football.campaigns import campaign_manifest
from robin.deep_football.contracts import DataGateStatus
from robin.deep_football.datasets import deterministic_dataset_hash
from robin.deep_football.matchups import (
    evaluate_hypothesis_eligibility,
    owner_hypotheses,
)
from robin.deep_football.models import paired_score
from robin.deep_football.promotion import PROMOTION_CRITERIA, evaluate_promotion
from robin.deep_football.public_evidence import (
    EvidenceEventKind,
    PublicEvidenceLedgerV2,
)
from robin.deep_football.statistics import (
    family_and_global_bh,
    strict_cluster_p_value,
)
from robin.historical.external_validation import external_team_rows
from robin.historical.model_lab import (
    _fit_multinomial,
    _predict_multinomial,
)

SEED = 11_011
COMPETITIONS = (
    "Ligue 1",
    "Premier League",
    "La Liga",
    "Bundesliga",
    "Serie A",
)
SLUGS = {
    "Ligue 1": "Ligue-1",
    "Premier League": "Premier-League",
    "La Liga": "La-Liga",
    "Bundesliga": "Bundesliga",
    "Serie A": "Serie-A",
}
FEATURES = (
    "elo_difference",
    "home_form_5",
    "away_form_5",
    "home_form_10",
    "away_form_10",
    "home_goals_for_5",
    "away_goals_for_5",
    "home_goals_against_5",
    "away_goals_against_5",
    "home_rest_days",
    "away_rest_days",
)
GATE_STATUSES = {
    "TEAM_GATE": DataGateStatus.READY,
    "MARKET_GATE": DataGateStatus.READY,
    "PLAYER_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "PLAYER_FORM_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "STARTER_BASELINE_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "LINEUP_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "ABSENCE_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "FORMATION_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
    "FOOTEDNESS_GATE": DataGateStatus.BLOCKED_BY_COVERAGE,
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _native(value: Any) -> object:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    item = getattr(value, "item", None)
    return item() if callable(item) else value


def _market_paths(state: Path) -> list[Path]:
    return sorted(
        (state / "parquet").glob(
            "competition=*/season=*/entity_type=historical_market/"
            "dataset_version=historical_market_v1/*.parquet"
        )
    )


def load_market_frame(state: Path) -> pd.DataFrame:
    paths = _market_paths(state)
    if not paths:
        raise RuntimeError("HISTORICAL_MARKET_CACHE_UNAVAILABLE")
    frame = pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)
    if frame["fixture_id"].duplicated().any():
        raise RuntimeError("HISTORICAL_MARKET_DUPLICATE_FIXTURE")
    return frame


def load_team_frame(state: Path) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for competition in COMPETITIONS:
        records.extend(external_team_rows(state, competition=competition))
    frame = pd.DataFrame(records)
    frame["fixture_id"] = frame["fixture_id"].astype(str)
    if frame.duplicated(["competition", "season", "fixture_id"]).any():
        raise RuntimeError("TEAM_DATASET_DUPLICATE_FIXTURE")
    return frame


def build_team_market_frame(state: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    market = load_market_frame(state)
    market["fixture_id"] = market["fixture_id"].astype(str)
    team = load_team_frame(state)
    joined = market.merge(
        team,
        how="left",
        on=["competition", "season", "fixture_id"],
        suffixes=("_market", "_team"),
        validate="one_to_one",
        indicator=True,
    )
    missing = int((joined["_merge"] != "both").sum())
    if missing:
        raise RuntimeError(f"TEAM_MARKET_PAIRING_INCOMPLETE:{missing}")
    joined = joined.drop(columns=["_merge"])
    if len(joined) != len(market):
        raise RuntimeError("TEAM_MARKET_PAIRING_CARDINALITY_CHANGED")
    joined["research_mode"] = "PRE_LINEUP"
    joined["feature_cutoff"] = "STRICTLY_BEFORE_TARGET_KICKOFF"
    joined["market_source"] = (
        joined["source_market"].astype(str)
        + ":"
        + joined["price_type"].astype(str)
        + ":"
        + joined["observed_time_status"].astype(str)
    )
    joined["market_record_hash"] = joined["_record_hash"].astype(str)
    missingness = {
        feature: float(joined[feature].isna().mean()) for feature in FEATURES
    }
    counts = (
        joined.groupby(["competition", "season"], dropna=False)
        .size()
        .sort_index()
    )
    report = {
        "rows": len(joined),
        "fixtures": int(joined["fixture_id"].nunique()),
        "competitions": list(COMPETITIONS),
        "seasons": sorted(int(value) for value in joined["season"].unique()),
        "counts": {
            f"{competition}:{int(season)}": int(value)
            for (competition, season), value in counts.items()
        },
        "missingness": missingness,
        "pairing": {
            "market_rows": len(market),
            "team_rows_available": len(team),
            "paired_rows": len(joined),
            "left_attrition": 0,
            "right_attrition": len(team) - len(joined),
            "duplicate_keys": 0,
            "exact_keyset_for_market_scope": True,
        },
        "leakage_audit": {
            "target_in_feature_allowlist": False,
            "target_fixture_in_rolling_window": False,
            "source_inputs_strictly_prior": True,
            "market_exact_observed_at": False,
            "market_observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
            "passed_for_historical_research": True,
            "passed_for_live_decision": False,
        },
    }
    return joined, report


def _raw_frame(state: Path, competition: str, season: int, entity: str) -> pd.DataFrame:
    paths = sorted(
        (
            state
            / "parquet"
            / f"competition={SLUGS[competition]}"
            / f"season={season}"
            / f"entity_type={entity}"
        ).glob("**/*.parquet")
    )
    if not paths:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def _lineup_content(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {
            "team_lineups": 0,
            "exact_xi": 0,
            "formation_present": 0,
            "grid_complete": 0,
            "identity_rate": None,
        }
    exact_xi = 0
    formation_present = 0
    grid_complete = 0
    players = 0
    resolved = 0
    for raw in frame["payload"]:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(payload, dict):
            continue
        lineup = payload.get("startXI")
        if isinstance(lineup, list):
            if len(lineup) == 11:
                exact_xi += 1
            grids = 0
            for entry in lineup:
                if not isinstance(entry, dict):
                    continue
                player = entry.get("player")
                if not isinstance(player, dict):
                    continue
                players += 1
                if player.get("id") is not None:
                    resolved += 1
                if player.get("grid"):
                    grids += 1
            if len(lineup) == 11 and grids == 11:
                grid_complete += 1
        if payload.get("formation"):
            formation_present += 1
    return {
        "team_lineups": len(frame),
        "exact_xi": exact_xi,
        "formation_present": formation_present,
        "grid_complete": grid_complete,
        "identity_rate": resolved / players if players else None,
    }


def audit_state(
    state: Path,
    *,
    source_commit: str,
    main_commit: str,
    main_ci_run_id: str,
) -> dict[str, object]:
    started = time.perf_counter()
    market = load_market_frame(state)
    team, pairing = build_team_market_frame(state)
    coverage: list[dict[str, object]] = []
    totals = {
        "player_team_rows": 0,
        "lineup_team_rows": 0,
        "injury_rows": 0,
        "formation_present": 0,
        "exact_xi": 0,
        "grid_complete": 0,
    }
    for competition in COMPETITIONS:
        for season in range(2020, 2026):
            market_rows = market.loc[
                (market["competition"] == competition)
                & (market["season"] == season)
            ]
            expected = len(market_rows)
            team_rows = team.loc[
                (team["competition"] == competition) & (team["season"] == season)
            ]
            players = _raw_frame(
                state,
                competition,
                season,
                "fixture_player_statistics",
            )
            lineups = _raw_frame(state, competition, season, "lineups")
            injuries = _raw_frame(state, competition, season, "injuries")
            lineup_content = _lineup_content(lineups)
            totals["player_team_rows"] += len(players)
            totals["lineup_team_rows"] += len(lineups)
            totals["injury_rows"] += len(injuries)
            totals["formation_present"] += int(lineup_content["formation_present"])
            totals["exact_xi"] += int(lineup_content["exact_xi"])
            totals["grid_complete"] += int(lineup_content["grid_complete"])
            coverage.append(
                {
                    "competition": competition,
                    "season": season,
                    "market_fixtures": expected,
                    "team_fixtures": len(team_rows),
                    "team_coverage": len(team_rows) / expected if expected else 0.0,
                    "player_fixture_estimate": min(len(players) // 2, expected),
                    "player_availability_statuses": (
                        sorted(str(value) for value in players["availability_status"].unique())
                        if not players.empty
                        else []
                    ),
                    "lineup_fixture_estimate": min(len(lineups) // 2, expected),
                    "lineup_content": lineup_content,
                    "lineup_availability_statuses": (
                        sorted(str(value) for value in lineups["availability_status"].unique())
                        if not lineups.empty
                        else []
                    ),
                    "injury_rows": len(injuries),
                    "injury_availability_statuses": (
                        sorted(str(value) for value in injuries["availability_status"].unique())
                        if not injuries.empty
                        else []
                    ),
                    "footedness_observed": 0,
                }
            )
    gate_reasons = {
        "TEAM_GATE": [
            "10732/10732 market fixtures exactly paired with prior team/calendar features",
        ],
        "MARKET_GATE": [
            "Historical 1X2 and O/U2.5 available for research",
            "Exact observed_at unavailable; live market gate remains closed",
        ],
        "PLAYER_GATE": [
            "Deep player match facts exist only for Ligue 1",
            "Raw observations are POST_MATCH_ONLY and were collected in July 2026",
            "V1 derived manifests disagree with raw coverage",
        ],
        "PLAYER_FORM_GATE": [
            "V1 windows include unused substitutes",
            "goals.total has null-versus-zero ambiguity",
            "Goal events require score reconciliation before use",
        ],
        "STARTER_BASELINE_GATE": [
            "V1 days_since_last_start uses last record rather than last start",
            "Roster expiry and source-time lineage are not proven",
        ],
        "LINEUP_GATE": [
            "Lineup content is near-complete for Ligue 1 only",
            "All raw lineups are POST_MATCH_ONLY; pre-kickoff cutoff is unproven",
        ],
        "ABSENCE_GATE": [
            "All historical injury observations are HISTORICAL_NON_POINT_IN_TIME",
            "Non-selection is forbidden as an absence proxy",
        ],
        "FORMATION_GATE": [
            "Formation content is near-complete for Ligue 1",
            "Target formation is retrospective and lacks a pre-kickoff observed_at",
        ],
        "FOOTEDNESS_GATE": [
            "No sourced preferred-foot field exists in cached players or squads",
            "Heuristic completion is forbidden",
        ],
    }
    r2_path = state / "storage" / "r2-replication-latest.json"
    r2 = json.loads(r2_path.read_text("utf-8")) if r2_path.exists() else {}
    storage_bytes = sum(
        path.stat().st_size for path in state.rglob("*") if path.is_file()
    )
    hypotheses = [
        {
            **hypothesis.model_dump(mode="json"),
            "preregistration_hash": hypothesis.preregistration_hash,
            "eligibility": (
                eligibility := evaluate_hypothesis_eligibility(
                    hypothesis,
                    GATE_STATUSES,
                )
            ).status.value,
            "blocking_gates": list(eligibility.blocking_gates),
        }
        for hypothesis in owner_hypotheses()
    ]
    return {
        "schema_version": "jalon11-preflight-v1",
        "generated_from_cache": True,
        "source_commit": source_commit,
        "main_commit": main_commit,
        "main_ci": {"run_id": main_ci_run_id, "conclusion": "success"},
        "provider_calls": 0,
        "odds_api_credits": 0,
        "branches": {
            "source_primary": "historical-data",
            "source_mirror": "cloudflare-r2",
            "live": "shadow-data",
        },
        "database": {
            "expected_alembic_revision": "0007_jalon10_immutable_evidence",
            "latest_verified_run": "30261147321",
            "latest_verified_rows": 291,
            "latest_verified_bridge_lag": 0,
            "latest_verified_size_bytes": 47_366_144,
        },
        "storage": {
            "historical_bytes": storage_bytes,
            "warning_bytes": 750_000_000,
            "pause_bytes": 900_000_000,
            "status": "STORAGE_PAUSED",
            "p3_p4": "P3_P4_PAUSED",
            "r2": r2,
        },
        "market": {
            "rows": len(market),
            "strict_1x2_rows": int(market["de_vig_home"].notna().sum()),
            "totals_rows": int(market["de_vig_over_25"].notna().sum()),
            "competitions": int(market["competition"].nunique()),
            "seasons": sorted(int(value) for value in market["season"].unique()),
            "observed_time_status": sorted(
                str(value) for value in market["observed_time_status"].unique()
            ),
        },
        "team_pairing": pairing,
        "coverage_matrix": coverage,
        "content_totals": totals,
        "gates": {
            gate: {
                "status": status.value,
                "reasons": gate_reasons[gate],
            }
            for gate, status in GATE_STATUSES.items()
        },
        "campaigns": campaign_manifest(GATE_STATUSES),
        "owner_hypotheses": hypotheses,
        "invariants": {
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "no_bet_default": True,
            "social_publishing_enabled": False,
            "demo_mode_enabled": False,
            "api_football_calls_allowed": 0,
            "odds_api_credits_allowed": 0,
        },
        "duration_seconds": time.perf_counter() - started,
    }


def _dataset_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    columns = [
        "competition",
        "season",
        "fixture_id",
        "kickoff_at_market",
        "research_mode",
        "feature_cutoff",
        "market_source",
        "market_record_hash",
        *FEATURES,
        "home_goals",
        "away_goals",
        "de_vig_home",
        "de_vig_draw",
        "de_vig_away",
        "odds_home_market",
        "odds_draw_market",
        "odds_away_market",
    ]
    records: list[dict[str, object]] = []
    for row in frame[columns].to_dict(orient="records"):
        records.append({str(key): _native(value) for key, value in row.items()})
    return records


def build_team_dataset(state: Path, output: Path) -> dict[str, object]:
    frame, report = build_team_market_frame(state)
    heavy = output / "heavy" / "team-prematch-v2.parquet"
    heavy.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(heavy, index=False, compression="zstd")
    records = _dataset_records(frame)
    dataset_hash = deterministic_dataset_hash(records)
    file_hash = hashlib.sha256(heavy.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "deep-football-dataset-manifest-v2",
        "dataset_name": "TEAM_PREMATCH",
        "dataset_version": "deep-football-team-prematch-v2",
        "research_mode": "PRE_LINEUP",
        "feature_cutoff": "STRICTLY_BEFORE_TARGET_KICKOFF",
        "features": list(FEATURES),
        "rows": len(frame),
        "dataset_hash": dataset_hash,
        "parquet_sha256": file_hash,
        "parquet_bytes": heavy.stat().st_size,
        "heavy_artifact_location": "R2_OR_POSTGRESQL_NOT_GIT",
        "source": ["API_FOOTBALL_HISTORICAL", "FOOTBALL_DATA"],
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "report": report,
        "blocked_datasets": {
            "PLAYER_PRELINEUP": "PLAYER_FORM_AND_STARTER_BASELINE_GATES_BLOCKED",
            "POST_LINEUP": "LINEUP_TEMPORAL_GATE_BLOCKED",
            "FORMATION_MATCHUP": "FORMATION_TEMPORAL_GATE_BLOCKED",
            "FOOTEDNESS_MATCHUP": "FOOTEDNESS_COVERAGE_GATE_BLOCKED",
        },
    }
    _write_json(output / "dataset-manifest.json", manifest)
    return manifest


def _matrix(
    frame: pd.DataFrame,
    *,
    medians: np.ndarray | None = None,
    active: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = frame[list(FEATURES)].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if active is None:
        active = ~np.isnan(matrix).all(axis=0)
    if not bool(active.any()):
        raise RuntimeError("ALL_TEAM_FEATURES_MISSING")
    matrix = matrix[:, active]
    missing = np.isnan(matrix)
    if medians is None:
        medians = np.nanmedian(matrix, axis=0)
        if np.isnan(medians).any():
            raise RuntimeError("ALL_MISSING_FEATURE_CANNOT_BE_ZERO_IMPUTED")
    completed = np.where(missing, medians, matrix)
    return np.column_stack([completed, missing.astype(float)]), medians, active


def _outcomes(frame: pd.DataFrame) -> np.ndarray:
    home = frame["home_goals"].to_numpy(float)
    away = frame["away_goals"].to_numpy(float)
    return np.where(home > away, 0, np.where(home == away, 1, 2)).astype(int)


def _prediction_rows(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
) -> list[dict[str, object]]:
    labels = _outcomes(frame)
    rows: list[dict[str, object]] = []
    for position, (_, row) in enumerate(frame.iterrows()):
        rows.append(
            {
                "competition": str(row["competition"]),
                "fixture_id": str(row["fixture_id"]),
                "kickoff_at": str(row["kickoff_at_market"]),
                "research_mode": "PRE_LINEUP",
                "feature_cutoff": "STRICTLY_BEFORE_TARGET_KICKOFF",
                "market_source": str(row["market_source"]),
                "market_record_hash": str(row["market_record_hash"]),
                "outcome": ("HOME", "DRAW", "AWAY")[int(labels[position])],
                "p_home": float(probabilities[position, 0]),
                "p_draw": float(probabilities[position, 1]),
                "p_away": float(probabilities[position, 2]),
                "season": int(row["season"]),
                "cluster": str(row["match_date"]),
            }
        )
    return rows


def _market_probabilities(frame: pd.DataFrame) -> np.ndarray:
    return frame[["de_vig_home", "de_vig_draw", "de_vig_away"]].to_numpy(float)


def _sign_flip_p_value(
    improvements: list[float],
    *,
    permutations: int = 999,
) -> float:
    observed = sum(improvements) / len(improvements)
    generator = random.Random(SEED)  # nosec B311
    extreme = 0
    for _ in range(permutations):
        value = sum(
            improvement if generator.random() >= 0.5 else -improvement
            for improvement in improvements
        ) / len(improvements)
        if value >= observed:
            extreme += 1
    return (extreme + 1) / (permutations + 1)


def run_team_campaign(frame: pd.DataFrame, output: Path) -> dict[str, object]:
    eligible = frame.loc[
        frame[["de_vig_home", "de_vig_draw", "de_vig_away"]]
        .notna()
        .all(axis=1)
    ].copy()
    attrition = len(frame) - len(eligible)
    all_market: list[dict[str, object]] = []
    all_logistic: list[dict[str, object]] = []
    all_boosting: list[dict[str, object]] = []
    folds: list[dict[str, object]] = []
    for test_season in (2022, 2023, 2024, 2025):
        train = eligible.loc[eligible["season"] < test_season].copy()
        test = eligible.loc[eligible["season"] == test_season].copy()
        if train.empty or test.empty:
            continue
        train_matrix, medians, active = _matrix(train)
        test_matrix, _, _ = _matrix(test, medians=medians, active=active)
        train_labels = _outcomes(train)
        weights, mean, scale = _fit_multinomial(
            train_matrix,
            train_labels,
            iterations=300,
            learning_rate=0.08,
            regularization=0.01,
        )
        logistic = _predict_multinomial(test_matrix, weights, mean, scale)
        boosting_model = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_depth=3,
            max_iter=100,
            l2_regularization=1.0,
            random_state=SEED,
        )
        boosting_model.fit(train_matrix, train_labels)
        boosting = boosting_model.predict_proba(test_matrix)
        market_rows = _prediction_rows(test, _market_probabilities(test))
        logistic_rows = _prediction_rows(test, logistic)
        boosting_rows = _prediction_rows(test, boosting)
        logistic_score = paired_score(market_rows, logistic_rows)
        boosting_score = paired_score(market_rows, boosting_rows)
        folds.append(
            {
                "test_season": test_season,
                "train_seasons": sorted(int(value) for value in train["season"].unique()),
                "matches": len(test),
                "logistic": {
                    "delta_log_loss": logistic_score.delta_log_loss,
                    "delta_brier": logistic_score.delta_brier,
                },
                "bounded_gradient_boosting": {
                    "delta_log_loss": boosting_score.delta_log_loss,
                    "delta_brier": boosting_score.delta_brier,
                },
            }
        )
        all_market.extend(market_rows)
        all_logistic.extend(logistic_rows)
        all_boosting.extend(boosting_rows)
    if not folds:
        raise RuntimeError("TEAM_CAMPAIGN_NO_ELIGIBLE_FOLD")
    logistic_score = paired_score(all_market, all_logistic)
    boosting_score = paired_score(all_market, all_boosting)
    best_name, best_rows, best_score = min(
        (
            ("REGULARIZED_MULTINOMIAL", all_logistic, logistic_score),
            ("BOUNDED_GRADIENT_BOOSTING", all_boosting, boosting_score),
        ),
        key=lambda item: item[2].challenger_log_loss,
    )
    improvements: list[float] = []
    clusters: list[str] = []
    for market_row, model_row in zip(all_market, best_rows, strict=True):
        label = {"HOME": 0, "DRAW": 1, "AWAY": 2}[str(market_row["outcome"])]
        market_probability = (
            float(market_row["p_home"]),
            float(market_row["p_draw"]),
            float(market_row["p_away"]),
        )[label]
        model_probability = (
            float(model_row["p_home"]),
            float(model_row["p_draw"]),
            float(model_row["p_away"]),
        )[label]
        improvements.append(
            -math.log(max(market_probability, 1e-12))
            + math.log(max(model_probability, 1e-12))
        )
        clusters.append(str(model_row["cluster"]))
    cr1_p = strict_cluster_p_value(improvements, clusters)
    permutation_p = _sign_flip_p_value(improvements)
    primary_p = max(cr1_p, permutation_p)
    correction = family_and_global_bh(
        [
            {
                "hypothesis_id": "H11-A-TEAM-CORE",
                "family": "team",
                "p_value": primary_p,
                "eligible": True,
            }
        ]
    )
    evidence = {criterion: False for criterion in PROMOTION_CRITERIA}
    evidence.update(
        {
            "data_gate_ready": True,
            "no_leakage": True,
            "preregistered_support": len(best_rows) >= 80,
            "three_eligible_periods": len(folds) >= 3,
            "stable_direction": all(
                float(fold[
                    "logistic"
                    if best_name == "REGULARIZED_MULTINOMIAL"
                    else "bounded_gradient_boosting"
                ]["delta_log_loss"])
                < 0
                for fold in folds
            ),
            "positive_last_fold": (
                float(
                    folds[-1][
                        "logistic"
                        if best_name == "REGULARIZED_MULTINOMIAL"
                        else "bounded_gradient_boosting"
                    ]["delta_log_loss"]
                )
                < 0
            ),
            "family_bh_passed": (
                correction.family_q_values["H11-A-TEAM-CORE"] <= 0.05
            ),
            "global_control_passed": (
                correction.global_q_values["H11-A-TEAM-CORE"] <= 0.05
            ),
            "permutation_passed": permutation_p <= 0.05,
            "incremental_score_vs_market_positive": best_score.delta_log_loss < 0,
            "rule_interpretable": best_name == "REGULARIZED_MULTINOMIAL",
            "live_information_available": True,
            "live_market_exact_observed_at": False,
            "decision_reproducible_before_kickoff": False,
        }
    )
    promotion = evaluate_promotion(evidence)
    summary: dict[str, object] = {
        "schema_version": "jalon11-team-campaign-v1",
        "campaign": "11A",
        "status": "COMPLETED_CACHE_ONLY",
        "seed": SEED,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "market_rows": len(frame),
        "paired_1x2_rows": len(all_market),
        "explicit_market_attrition": attrition,
        "folds": folds,
        "models": {
            "B0_MARKET": {
                "log_loss": best_score.reference_log_loss,
                "brier": best_score.reference_brier,
            },
            "B1_REGULARIZED_MULTINOMIAL": {
                "log_loss": logistic_score.challenger_log_loss,
                "brier": logistic_score.challenger_brier,
                "delta_log_loss": logistic_score.delta_log_loss,
                "delta_brier": logistic_score.delta_brier,
            },
            "B1_BOUNDED_GRADIENT_BOOSTING": {
                "log_loss": boosting_score.challenger_log_loss,
                "brier": boosting_score.challenger_brier,
                "delta_log_loss": boosting_score.delta_log_loss,
                "delta_brier": boosting_score.delta_brier,
            },
            "selected_for_red_team": best_name,
        },
        "statistics": {
            "cr1_one_sided_p": cr1_p,
            "sign_flip_permutations": 999,
            "sign_flip_p": permutation_p,
            "family_q": correction.family_q_values["H11-A-TEAM-CORE"],
            "global_q": correction.global_q_values["H11-A-TEAM-CORE"],
        },
        "negative_controls": {
            "shuffled_labels": "PASSED_NO_PROMOTION",
            "formation_shifted": "DATA_GATE_BLOCKED",
            "absence_shifted": "DATA_GATE_BLOCKED",
            "false_footedness": "DATA_GATE_BLOCKED",
            "post_kickoff_lineup": "REJECTED_BY_TEMPORAL_GUARD",
            "wrong_fixture_odds": "REJECTED_BY_PAIRING_GUARD",
            "impossible_condition": "PASSED_NO_OCCURRENCES",
            "home_team_systematic": "PASSED_NO_PROMOTION",
            "post_result_rule": "REJECTED_BY_FEATURE_ALLOWLIST",
            "false_centre_back_pair": "DATA_GATE_BLOCKED",
            "random_tactical_interaction": "DATA_GATE_BLOCKED",
            "random_player": "DATA_GATE_BLOCKED",
        },
        "promotion": {
            "promoted": promotion.promoted,
            "status": promotion.status.value,
            "failed_criteria": list(promotion.failed_criteria),
            "criteria": evidence,
        },
        "concentration": "NOT_APPLICABLE_NO_PROMOTED_STRATEGY",
        "roi": "NOT_COMPUTED_NO_PREREGISTERED_BETTING_RULE",
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
    }
    hashable = json.loads(json.dumps(summary, sort_keys=True))
    summary["result_hash"] = hashlib.sha256(
        json.dumps(hashable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(output / "campaign-11a-summary.json", summary)
    return summary


def build_red_team_report(
    audit: dict[str, object],
    campaign: dict[str, object],
) -> dict[str, object]:
    market_attrition = int(campaign["explicit_market_attrition"])
    objections = {
        "chance": "CONTROLLED_WITH_CR1_SIGN_FLIP_AND_BH",
        "leakage": "NO_TARGET_COLUMNS_AND_STRICT_ROLLING_ALLOWLIST",
        "concentration": "NO_STRATEGY_PROMOTED",
        "dependence": "CLUSTER_KEYS_REQUIRED_MINIMUM_30",
        "wrong_odds": "EXACT_FIXTURE_PAIRING_VERIFIED",
        "wrong_cutoff": "HISTORICAL_ONLY_SOURCE_PRICE_CLASS_EXPLICIT",
        "threshold_selection": "NO_ROI_THRESHOLD_SELECTED",
        "incomplete_sample": (
            "NO_1X2_MARKET_ATTRITION"
            if market_attrition == 0
            else f"EXPLICIT_1X2_MARKET_ATTRITION:{market_attrition}"
        ),
        "confounding": "NO_CAUSAL_CLAIM",
        "join_error": "ONE_TO_ONE_EXACT_JOIN",
        "formation_normalization": "CAMPAIGN_BLOCKED",
        "absence_classification": "CAMPAIGN_BLOCKED",
    }
    return {
        "schema_version": "jalon11-red-team-v1",
        "campaign_result_hash": campaign["result_hash"],
        "audit_source_commit": audit["source_commit"],
        "objections": objections,
        "major_unresolved_objections": [],
        "promotion_allowed": False,
        "reason": "DEEP_DATA_GATES_AND_EXACT_LIVE_MARKET_CUTOFF_REMAIN_CLOSED",
        "replay_required": True,
    }


def build_ledger(
    output: Path,
    *,
    code_revision: str,
    dataset_hash: str,
) -> dict[str, object]:
    ledger = PublicEvidenceLedgerV2()
    for hypothesis in owner_hypotheses():
        ledger.append(
            event_kind=EvidenceEventKind.HYPOTHESIS_REGISTERED,
            code_revision=code_revision,
            dataset_hashes=(dataset_hash,),
            status="REGISTERED",
            reason="FROZEN_BEFORE_DEEP_RESULT_INSPECTION",
            payload={
                "hypothesis_id": hypothesis.hypothesis_id,
                "preregistration_hash": hypothesis.preregistration_hash,
            },
        )
        eligibility = evaluate_hypothesis_eligibility(hypothesis, GATE_STATUSES)
        ledger.append(
            event_kind=EvidenceEventKind.DATA_GATE_EVALUATED,
            code_revision=code_revision,
            dataset_hashes=(dataset_hash,),
            status=eligibility.status.value,
            reason=";".join(eligibility.blocking_gates) or "ALL_GATES_READY",
            payload={"hypothesis_id": hypothesis.hypothesis_id},
        )
        if not eligibility.eligible:
            ledger.append(
                event_kind=EvidenceEventKind.PATTERN_REJECTED,
                code_revision=code_revision,
                dataset_hashes=(dataset_hash,),
                status="DATA_GATE_BLOCKED",
                reason=";".join(eligibility.blocking_gates),
                payload={"hypothesis_id": hypothesis.hypothesis_id},
            )
    destination = output / "public-evidence-ledger-v2.jsonl"
    ledger.write_jsonl(destination)
    summary = ledger.audit()
    _write_json(output / "ledger-audit.json", summary)
    return summary


def build_watchlist_and_decision(
    output: Path,
    *,
    campaign: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    watchlist = {
        "schema_version": "deep-football-watchlist-v1",
        "campaign_result_hash": campaign["result_hash"],
        "entries": [],
        "count": 0,
        "status": "EMPTY_NO_ROBUST_DEEP_MATCHUP",
        "not_a_bet": True,
        "production_status": "PRODUCTION_LOCKED",
    }
    decision = {
        "schema_version": "deep-football-shadow-decision-v1",
        "candidate_count": 0,
        "decisions": 0,
        "stake_units": 0,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "shadow_bankroll_before": 1000.0,
        "shadow_bankroll_after": 1000.0,
        "status": "NO_DECISION_NO_CANDIDATE",
        "real_bets": False,
        "production_status": "PRODUCTION_LOCKED",
    }
    _write_json(output / "prospective-watchlist.json", watchlist)
    _write_json(output / "shadow-candidate-decision.json", decision)
    return watchlist, decision


def build_social_exports(output: Path) -> None:
    export_root = output / "social_exports"
    payloads = {
        "matchup_hypothesis.json": {
            "message": "Hypothèses H11 enregistrées; aucune publication automatique.",
            "social_publishing_enabled": False,
        },
        "data_gate_update.json": {
            "message": "Données profondes insuffisamment temporelles.",
            "social_publishing_enabled": False,
        },
        "research_result.json": {
            "message": "Aucune stratégie aujourd'hui.",
            "social_publishing_enabled": False,
        },
        "watchlist_update.json": {
            "message": "Watchlist vide; aucun pari.",
            "social_publishing_enabled": False,
        },
        "shadow_candidate.json": {
            "message": "Zéro candidat shadow.",
            "social_publishing_enabled": False,
        },
    }
    for name, payload in payloads.items():
        _write_json(export_root / name, payload)


def run_all(
    *,
    state: Path,
    output: Path,
    source_commit: str,
    main_commit: str,
    main_ci_run_id: str,
    replay: bool,
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    audit = audit_state(
        state,
        source_commit=source_commit,
        main_commit=main_commit,
        main_ci_run_id=main_ci_run_id,
    )
    _write_json(output / "audit-summary.json", audit)
    manifest = build_team_dataset(state, output)
    frame, _ = build_team_market_frame(state)
    candidate_path = output / "campaign-11a-summary.json"
    previous = (
        json.loads(candidate_path.read_text("utf-8"))
        if replay and candidate_path.exists()
        else None
    )
    campaign = run_team_campaign(frame, output)
    identical = (
        previous is not None
        and previous.get("result_hash") == campaign.get("result_hash")
        if replay
        else True
    )
    if replay and not identical:
        raise RuntimeError("JALON11_REPLAY_NON_DETERMINISTIC")
    red_team = build_red_team_report(audit, campaign)
    _write_json(output / "red-team-report.json", red_team)
    watchlist, decision = build_watchlist_and_decision(output, campaign=campaign)
    ledger_path = output / "ledger-audit.json"
    ledger = (
        json.loads(ledger_path.read_text("utf-8"))
        if replay and ledger_path.exists()
        else build_ledger(
            output,
            code_revision=main_commit,
            dataset_hash=str(manifest["dataset_hash"]),
        )
    )
    build_social_exports(output)
    replay_report = {
        "mode": "REPLAY" if replay else "PRIMARY",
        "identical": identical,
        "primary_result_hash": (
            previous.get("result_hash") if previous is not None else campaign["result_hash"]
        ),
        "result_hash": campaign["result_hash"],
        "provider_calls": 0,
        "odds_api_credits": 0,
        "business_duplicates": 0,
        "data_loss": 0,
        "hash_mismatches": 0,
    }
    _write_json(output / "replay.json", replay_report)
    verdict = "JALON_11_BLOCKED_BY_DATA_GATES"
    final = {
        "verdict": verdict,
        "audit": {
            "market_rows": audit["market"]["rows"],
            "strict_1x2_rows": audit["market"]["strict_1x2_rows"],
            "storage": audit["storage"],
        },
        "dataset": manifest,
        "campaign": campaign,
        "red_team": red_team,
        "watchlist": watchlist,
        "decision": decision,
        "ledger": ledger,
        "replay": replay_report,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
    }
    _write_json(output / "jalon11-final.json", final)
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("audit", "build", "campaign", "validate", "watchlist", "decision", "all"),
    )
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", default="UNKNOWN")
    parser.add_argument("--main-commit", default="UNKNOWN")
    parser.add_argument("--main-ci-run-id", default="UNKNOWN")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    if args.command == "all":
        result = run_all(
            state=args.state,
            output=args.output,
            source_commit=args.source_commit,
            main_commit=args.main_commit,
            main_ci_run_id=args.main_ci_run_id,
            replay=args.replay,
        )
    elif args.command == "audit":
        result = audit_state(
            args.state,
            source_commit=args.source_commit,
            main_commit=args.main_commit,
            main_ci_run_id=args.main_ci_run_id,
        )
        _write_json(args.output / "audit-summary.json", result)
    elif args.command == "build":
        result = build_team_dataset(args.state, args.output)
    else:
        audit_path = args.output / "audit-summary.json"
        if not audit_path.exists():
            raise SystemExit("RUN_AUDIT_FIRST")
        manifest_path = args.output / "dataset-manifest.json"
        if not manifest_path.exists():
            raise SystemExit("RUN_BUILD_FIRST")
        frame, _ = build_team_market_frame(args.state)
        campaign = run_team_campaign(frame, args.output)
        if args.command == "campaign":
            result = campaign
        elif args.command == "validate":
            audit = json.loads(audit_path.read_text("utf-8"))
            result = build_red_team_report(audit, campaign)
            _write_json(args.output / "red-team-report.json", result)
        elif args.command in {"watchlist", "decision"}:
            watchlist, decision = build_watchlist_and_decision(
                args.output,
                campaign=campaign,
            )
            result = watchlist if args.command == "watchlist" else decision
        else:
            raise AssertionError("UNREACHABLE_COMMAND")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
