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
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from robin.deep_football.campaigns import campaign_manifest
from robin.deep_football.contracts import (
    SCIENTIFIC_FLOAT_CONTRACT_VERSION,
    DataGateStatus,
    normalize_scientific_evidence,
    scientific_evidence_hash,
)
from robin.deep_football.datasets import deterministic_dataset_hash
from robin.deep_football.matchups import (
    evaluate_hypothesis_eligibility,
    owner_hypotheses,
)
from robin.deep_football.models import paired_score
from robin.deep_football.persistence import PROTOCOL_AMENDMENT_HASH
from robin.deep_football.promotion import PROMOTION_CRITERIA, evaluate_promotion
from robin.deep_football.public_evidence import (
    EvidenceEventKind,
    PublicEvidenceLedgerV2,
)
from robin.deep_football.statistics import (
    family_and_global_bh,
    impossible_outcome_control,
    strict_cluster_p_value,
)
from robin.deep_football.temporal import (
    TemporalInput,
    assert_feature_allowlist,
    assert_input_available_strictly_before_cutoff,
)
from robin.historical.external_validation import external_team_rows
from robin.historical.model_lab import (
    _fit_multinomial,
    _predict_multinomial,
)
from robin.modeling.reference import poisson_probabilities

SEED = 11_011
LEDGER_FROZEN_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
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
    "TEAM_GATE": DataGateStatus.PARTIAL,
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
    feature_boundaries = pd.to_datetime(
        joined["as_of_time"],
        utc=True,
        errors="raise",
    )
    target_kickoffs = pd.to_datetime(
        joined["kickoff_at_market"],
        utc=True,
        errors="raise",
    )
    future_boundaries = int((feature_boundaries > target_kickoffs).sum())
    if future_boundaries:
        raise RuntimeError(
            f"TEAM_FEATURE_BOUNDARY_AFTER_KICKOFF:{future_boundaries}"
        )
    strict_boundaries = int((feature_boundaries < target_kickoffs).sum())
    equal_boundaries = int((feature_boundaries == target_kickoffs).sum())
    joined["research_mode"] = "PRE_LINEUP"
    joined["feature_cutoff"] = "TARGET_KICKOFF_EXCLUSIVE_STATE_BEFORE_UPDATE"
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
            "feature_boundary_strictly_before_rows": strict_boundaries,
            "feature_boundary_equal_kickoff_rows": equal_boundaries,
            "feature_boundary_after_kickoff_rows": future_boundaries,
            "feature_state_update_order": "TARGET_ROW_EMITTED_BEFORE_TARGET_RESULT_UPDATE",
            "source_inputs_strictly_prior": "ALGORITHMIC_PRIOR_FIXTURE_STATE",
            "row_level_source_observed_at_proven": False,
            "market_exact_observed_at": False,
            "market_observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
            "team_temporal_gate": "PARTIAL",
            "passed_for_descriptive_historical_research": True,
            "passed_for_promotion": False,
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
            "10732/10732 feature materialization boundaries equal target kickoff",
            "Prior-fixture update order is algorithmic; row-level source observed_at is unavailable",
            "Descriptive diagnostics are allowed but promotion remains blocked",
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
        "feature_cutoff": "TARGET_KICKOFF_EXCLUSIVE_STATE_BEFORE_UPDATE",
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
                "feature_cutoff": "TARGET_KICKOFF_EXCLUSIVE_STATE_BEFORE_UPDATE",
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


def _poisson_rows(
    frame: pd.DataFrame,
    *,
    medians: dict[str, float],
    dixon_coles: bool,
) -> list[dict[str, object]]:
    probabilities: list[list[float]] = []
    for _, row in frame.iterrows():
        def value(column: str) -> float:
            raw = row[column]
            return (
                float(raw)
                if not bool(pd.isna(raw))
                else float(medians[column])
            )

        expected_home = max(
            0.2,
            min(
                4.0,
                (
                    value("home_goals_for_5")
                    + value("away_goals_against_5")
                )
                / 2.0,
            ),
        )
        expected_away = max(
            0.2,
            min(
                4.0,
                (
                    value("away_goals_for_5")
                    + value("home_goals_against_5")
                )
                / 2.0,
            ),
        )
        prediction = poisson_probabilities(
            expected_home,
            expected_away,
            dixon_coles=dixon_coles,
            rho=-0.08,
        )
        probabilities.append(
            [prediction.home, prediction.draw, prediction.away]
        )
    return _prediction_rows(frame, np.asarray(probabilities, dtype=float))


def _calibration_error(
    rows: list[dict[str, object]],
    *,
    bins: int = 10,
) -> float:
    confidences: list[float] = []
    correct: list[float] = []
    outcomes = {"HOME": 0, "DRAW": 1, "AWAY": 2}
    for row in rows:
        probabilities = (
            float(row["p_home"]),
            float(row["p_draw"]),
            float(row["p_away"]),
        )
        prediction = max(range(3), key=probabilities.__getitem__)
        confidences.append(probabilities[prediction])
        correct.append(
            float(prediction == outcomes[str(row["outcome"])])
        )
    total = len(rows)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            position
            for position, confidence in enumerate(confidences)
            if lower <= confidence < upper
            or (index == bins - 1 and confidence == upper)
        ]
        if not selected:
            continue
        accuracy = sum(correct[position] for position in selected) / len(selected)
        confidence = sum(confidences[position] for position in selected) / len(
            selected
        )
        error += len(selected) / total * abs(accuracy - confidence)
    return error


def _market_log_odds_matrix(frame: pd.DataFrame) -> np.ndarray:
    probabilities = _market_probabilities(frame)
    clipped = np.clip(probabilities, 1e-12, 1.0)
    return np.column_stack(
        [
            np.log(clipped[:, 0] / clipped[:, 2]),
            np.log(clipped[:, 1] / clipped[:, 2]),
        ]
    )


def _market_plus_team_matrix(
    frame: pd.DataFrame,
    *,
    medians: np.ndarray | None = None,
    active: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    team, medians, active = _matrix(
        frame,
        medians=medians,
        active=active,
    )
    return (
        np.column_stack([_market_log_odds_matrix(frame), team]),
        medians,
        active,
    )


def _cluster_bootstrap_mean_interval(
    values: list[float],
    clusters: list[str],
    *,
    draws: int = 999,
) -> tuple[float, float]:
    if len(values) != len(clusters) or not values:
        raise ValueError("CLUSTER_BOOTSTRAP_INPUT_MISMATCH")
    grouped: dict[str, list[float]] = {}
    for value, cluster in zip(values, clusters, strict=True):
        grouped.setdefault(cluster, []).append(value)
    keys = sorted(grouped)
    generator = np.random.default_rng(SEED)
    estimates = np.empty(draws, dtype=float)
    for index in range(draws):
        selected = generator.choice(keys, size=len(keys), replace=True)
        total = 0.0
        observations = 0
        for key in selected:
            group = grouped[str(key)]
            total += sum(group)
            observations += len(group)
        estimates[index] = total / observations
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return float(lower), float(upper)


def _cross_league_transfer(
    eligible: pd.DataFrame,
) -> dict[str, object]:
    rotations: list[dict[str, object]] = []
    for index, first in enumerate(COMPETITIONS):
        second = COMPETITIONS[(index + 1) % len(COMPETITIONS)]
        validation = {first, second}
        discovery = [
            competition
            for competition in COMPETITIONS
            if competition not in validation
        ]
        train = eligible.loc[
            eligible["competition"].isin(discovery)
            & (eligible["season"] <= 2021)
        ].copy()
        test = eligible.loc[
            eligible["competition"].isin(validation)
            & (eligible["season"] >= 2022)
        ].copy()
        market_train = _market_log_odds_matrix(train)
        market_test = _market_log_odds_matrix(test)
        market_weights, market_mean, market_scale = _fit_multinomial(
            market_train,
            _outcomes(train),
            iterations=300,
            learning_rate=0.08,
            regularization=0.01,
        )
        train_matrix, medians, active = _market_plus_team_matrix(train)
        test_matrix, _, _ = _market_plus_team_matrix(
            test,
            medians=medians,
            active=active,
        )
        weights, mean, scale = _fit_multinomial(
            train_matrix,
            _outcomes(train),
            iterations=300,
            learning_rate=0.08,
            regularization=0.01,
        )
        challenger = _prediction_rows(
            test,
            _predict_multinomial(test_matrix, weights, mean, scale),
        )
        reference = _prediction_rows(
            test,
            _predict_multinomial(
                market_test,
                market_weights,
                market_mean,
                market_scale,
            ),
        )
        score = paired_score(reference, challenger)
        rotations.append(
            {
                "discovery_leagues": discovery,
                "validation_leagues": sorted(validation),
                "train_seasons": [2020, 2021],
                "validation_seasons": [2022, 2023, 2024, 2025],
                "support": len(test),
                "delta_log_loss": score.delta_log_loss,
                "delta_brier": score.delta_brier,
                "descriptive_direction_positive": score.delta_log_loss < 0,
                "promotion_eligible": False,
            }
        )
    return {
        "status": "DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC",
        "rotations": rotations,
        "descriptive_positive_rotations": sum(
            bool(rotation["descriptive_direction_positive"])
            for rotation in rotations
        ),
        "cross_league_survivors": 0,
        "promotion_eligible": False,
        "limitations": [
            "TEAM_GATE_PARTIAL",
            "OVERLAPPING_VALIDATION_ROTATIONS",
            "LEAGUE_AND_TIME_SHIFT_CONFOUNDED",
            "NO_ROTATION_LEVEL_MULTIPLICITY_INFERENCE",
        ],
        "provider_calls": 0,
        "odds_api_credits": 0,
    }


def _sign_flip_p_value(
    improvements: list[float],
    clusters: list[str],
    *,
    permutations: int = 999,
) -> float:
    if len(improvements) != len(clusters) or not improvements:
        raise ValueError("CLUSTER_SIGN_FLIP_INPUT_MISMATCH")
    grouped: dict[str, float] = {}
    for improvement, cluster in zip(improvements, clusters, strict=True):
        grouped[cluster] = grouped.get(cluster, 0.0) + improvement
    observed = sum(improvements) / len(improvements)
    generator = random.Random(SEED)  # nosec B311
    extreme = 0
    for _ in range(permutations):
        value = sum(
            cluster_total if generator.random() >= 0.5 else -cluster_total
            for cluster_total in grouped.values()
        ) / len(improvements)
        if value >= observed:
            extreme += 1
    return (extreme + 1) / (permutations + 1)


def _run_negative_controls(
    reference: list[dict[str, object]],
    challenger: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    if len(reference) != len(challenger) or not reference:
        raise ValueError("NEGATIVE_CONTROL_SAMPLE_INVALID")
    generator = random.Random(SEED)  # nosec B311
    shuffled_labels = [str(row["outcome"]) for row in reference]
    strata: dict[tuple[str, int], list[int]] = {}
    for position, row in enumerate(reference):
        key = (str(row["competition"]), int(row["season"]))
        strata.setdefault(key, []).append(position)
    for positions in strata.values():
        labels = [shuffled_labels[position] for position in positions]
        generator.shuffle(labels)
        for position, label in zip(positions, labels, strict=True):
            shuffled_labels[position] = label
    shuffled_reference = [
        {**row, "outcome": shuffled_labels[position]}
        for position, row in enumerate(reference)
    ]
    shuffled_challenger = [
        {**row, "outcome": shuffled_labels[position]}
        for position, row in enumerate(challenger)
    ]
    shuffled_score = paired_score(
        shuffled_reference,
        shuffled_challenger,
    )

    home_probabilities = np.tile(
        np.asarray([[0.999998, 0.000001, 0.000001]], dtype=float),
        (len(reference), 1),
    )
    home_rows = [
        {
            **row,
            "p_home": float(home_probabilities[position, 0]),
            "p_draw": float(home_probabilities[position, 1]),
            "p_away": float(home_probabilities[position, 2]),
        }
        for position, row in enumerate(reference)
    ]
    home_score = paired_score(reference, home_rows)

    wrong_fixture_status = "FAILED_TO_REJECT"
    wrong_fixture = [dict(row) for row in challenger]
    wrong_fixture[0]["fixture_id"] = (
        str(wrong_fixture[0]["fixture_id"]) + ":WRONG_FIXTURE_CONTROL"
    )
    try:
        paired_score(reference, wrong_fixture)
    except ValueError as exc:
        if str(exc).startswith("PAIRED_SAMPLE_KEYSET_MISMATCH"):
            wrong_fixture_status = "REJECTED_BY_PAIRING_GUARD"

    cutoff = datetime(2026, 7, 27, 15, tzinfo=UTC)
    post_kickoff_status = "FAILED_TO_REJECT"
    try:
        assert_input_available_strictly_before_cutoff(
            [
                TemporalInput(
                    input_id="NEGATIVE_POST_KICKOFF_LINEUP",
                    available_at=cutoff,
                    cutoff_at=cutoff,
                    lineage_hash="a" * 64,
                    source="NEGATIVE_CONTROL",
                )
            ]
        )
    except ValueError as exc:
        if str(exc).startswith("INPUT_NOT_STRICTLY_BEFORE_CUTOFF"):
            post_kickoff_status = "REJECTED_BY_TEMPORAL_GUARD"

    post_result_status = "FAILED_TO_REJECT"
    try:
        assert_feature_allowlist(
            {"outcome": "HOME"},
            ["outcome"],
        )
    except ValueError as exc:
        if str(exc) == "TARGET_FIELD_IN_FEATURE_ALLOWLIST":
            post_result_status = "REJECTED_BY_FEATURE_ALLOWLIST"

    return {
        "shuffled_labels_stratified": {
            "status": "EXECUTED_NO_PROMOTION",
            "support": len(reference),
            "delta_log_loss": shuffled_score.delta_log_loss,
            "delta_brier": shuffled_score.delta_brier,
            "promotion_eligible": False,
        },
        "home_team_systematic": {
            "status": "EXECUTED_NO_PROMOTION",
            "support": len(reference),
            "delta_log_loss": home_score.delta_log_loss,
            "delta_brier": home_score.delta_brier,
            "promotion_eligible": False,
        },
        "wrong_fixture_odds": {
            "status": wrong_fixture_status,
            "support": 1,
            "promotion_eligible": False,
        },
        "post_kickoff_lineup": {
            "status": post_kickoff_status,
            "support": 1,
            "promotion_eligible": False,
        },
        "post_result_rule": {
            "status": post_result_status,
            "support": 1,
            "promotion_eligible": False,
        },
        "impossible_condition": impossible_outcome_control(reference),
        "formation_shifted_one_match": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
        "absence_shifted": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
        "random_player": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
        "false_footedness": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
        "false_centre_back_pair": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
        "random_tactical_interaction": {
            "status": "DATA_GATE_BLOCKED",
            "support": 0,
            "promotion_eligible": False,
        },
    }


def run_team_campaign(frame: pd.DataFrame, output: Path) -> dict[str, object]:
    eligible = frame.loc[
        frame[["de_vig_home", "de_vig_draw", "de_vig_away"]]
        .notna()
        .all(axis=1)
    ].copy()
    attrition = len(frame) - len(eligible)
    all_market: list[dict[str, object]] = []
    all_market_recalibrated: list[dict[str, object]] = []
    all_logistic: list[dict[str, object]] = []
    all_boosting: list[dict[str, object]] = []
    all_poisson: list[dict[str, object]] = []
    all_dixon_coles: list[dict[str, object]] = []
    all_incremental_logistic: list[dict[str, object]] = []
    all_incremental_boosting: list[dict[str, object]] = []
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
        market_train = _market_log_odds_matrix(train)
        market_test = _market_log_odds_matrix(test)
        market_weights, market_mean, market_scale = _fit_multinomial(
            market_train,
            train_labels,
            iterations=300,
            learning_rate=0.08,
            regularization=0.01,
        )
        market_recalibrated = _predict_multinomial(
            market_test,
            market_weights,
            market_mean,
            market_scale,
        )
        augmented_train, augmented_medians, augmented_active = (
            _market_plus_team_matrix(train)
        )
        augmented_test, _, _ = _market_plus_team_matrix(
            test,
            medians=augmented_medians,
            active=augmented_active,
        )
        incremental_weights, incremental_mean, incremental_scale = (
            _fit_multinomial(
                augmented_train,
                train_labels,
                iterations=300,
                learning_rate=0.08,
                regularization=0.01,
            )
        )
        incremental_logistic = _predict_multinomial(
            augmented_test,
            incremental_weights,
            incremental_mean,
            incremental_scale,
        )
        incremental_boosting_model = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_depth=3,
            max_iter=100,
            l2_regularization=1.0,
            random_state=SEED,
        )
        incremental_boosting_model.fit(augmented_train, train_labels)
        incremental_boosting = incremental_boosting_model.predict_proba(
            augmented_test
        )
        market_rows = _prediction_rows(test, _market_probabilities(test))
        market_recalibrated_rows = _prediction_rows(
            test,
            market_recalibrated,
        )
        logistic_rows = _prediction_rows(test, logistic)
        boosting_rows = _prediction_rows(test, boosting)
        incremental_logistic_rows = _prediction_rows(
            test,
            incremental_logistic,
        )
        incremental_boosting_rows = _prediction_rows(
            test,
            incremental_boosting,
        )
        goal_columns = (
            "home_goals_for_5",
            "away_goals_for_5",
            "home_goals_against_5",
            "away_goals_against_5",
        )
        goal_medians = {
            column: float(train[column].median()) for column in goal_columns
        }
        poisson_rows = _poisson_rows(
            test,
            medians=goal_medians,
            dixon_coles=False,
        )
        dixon_coles_rows = _poisson_rows(
            test,
            medians=goal_medians,
            dixon_coles=True,
        )
        logistic_score = paired_score(market_rows, logistic_rows)
        boosting_score = paired_score(market_rows, boosting_rows)
        poisson_score = paired_score(market_rows, poisson_rows)
        dixon_coles_score = paired_score(market_rows, dixon_coles_rows)
        market_recalibration_score = paired_score(
            market_rows,
            market_recalibrated_rows,
        )
        incremental_logistic_score = paired_score(
            market_recalibrated_rows,
            incremental_logistic_rows,
        )
        incremental_boosting_score = paired_score(
            market_recalibrated_rows,
            incremental_boosting_rows,
        )
        incremental_logistic_vs_raw_score = paired_score(
            market_rows,
            incremental_logistic_rows,
        )
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
                "poisson": {
                    "delta_log_loss": poisson_score.delta_log_loss,
                    "delta_brier": poisson_score.delta_brier,
                },
                "dixon_coles": {
                    "delta_log_loss": dixon_coles_score.delta_log_loss,
                    "delta_brier": dixon_coles_score.delta_brier,
                },
                "market_recalibrated_vs_raw": {
                    "delta_log_loss": market_recalibration_score.delta_log_loss,
                    "delta_brier": market_recalibration_score.delta_brier,
                },
                "incremental_logistic_vs_recalibrated_market": {
                    "delta_log_loss": incremental_logistic_score.delta_log_loss,
                    "delta_brier": incremental_logistic_score.delta_brier,
                },
                "incremental_logistic_vs_raw_market": {
                    "delta_log_loss": (
                        incremental_logistic_vs_raw_score.delta_log_loss
                    ),
                    "delta_brier": (
                        incremental_logistic_vs_raw_score.delta_brier
                    ),
                },
                "incremental_boosting_vs_recalibrated_market": {
                    "delta_log_loss": incremental_boosting_score.delta_log_loss,
                    "delta_brier": incremental_boosting_score.delta_brier,
                },
            }
        )
        all_market.extend(market_rows)
        all_market_recalibrated.extend(market_recalibrated_rows)
        all_logistic.extend(logistic_rows)
        all_boosting.extend(boosting_rows)
        all_poisson.extend(poisson_rows)
        all_dixon_coles.extend(dixon_coles_rows)
        all_incremental_logistic.extend(incremental_logistic_rows)
        all_incremental_boosting.extend(incremental_boosting_rows)
    if not folds:
        raise RuntimeError("TEAM_CAMPAIGN_NO_ELIGIBLE_FOLD")
    logistic_score = paired_score(all_market, all_logistic)
    boosting_score = paired_score(all_market, all_boosting)
    poisson_score = paired_score(all_market, all_poisson)
    dixon_coles_score = paired_score(all_market, all_dixon_coles)
    market_recalibration_score = paired_score(
        all_market,
        all_market_recalibrated,
    )
    incremental_logistic_score = paired_score(
        all_market_recalibrated,
        all_incremental_logistic,
    )
    incremental_logistic_vs_raw_score = paired_score(
        all_market,
        all_incremental_logistic,
    )
    incremental_boosting_score = paired_score(
        all_market_recalibrated,
        all_incremental_boosting,
    )
    primary_name = "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"
    primary_reference_rows = all_market_recalibrated
    primary_rows = all_incremental_logistic
    primary_score = incremental_logistic_score
    improvements: list[float] = []
    clusters: list[str] = []
    for reference_row, model_row in zip(
        primary_reference_rows,
        primary_rows,
        strict=True,
    ):
        label = {"HOME": 0, "DRAW": 1, "AWAY": 2}[
            str(reference_row["outcome"])
        ]
        reference_probability = (
            float(reference_row["p_home"]),
            float(reference_row["p_draw"]),
            float(reference_row["p_away"]),
        )[label]
        model_probability = (
            float(model_row["p_home"]),
            float(model_row["p_draw"]),
            float(model_row["p_away"]),
        )[label]
        improvements.append(
            -math.log(max(reference_probability, 1e-12))
            + math.log(max(model_probability, 1e-12))
        )
        clusters.append(str(model_row["cluster"]))
    cr1_p = strict_cluster_p_value(improvements, clusters)
    permutation_p = _sign_flip_p_value(improvements, clusters)
    primary_p = max(cr1_p, permutation_p)
    bootstrap_lower, bootstrap_upper = _cluster_bootstrap_mean_interval(
        [-value for value in improvements],
        clusters,
    )
    multiplicity_records: list[dict[str, object]] = [
        {
            "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
            "family": "team",
            "p_value": primary_p,
            "eligible": True,
        }
    ]
    multiplicity_records.extend(
        {
            "hypothesis_id": hypothesis.hypothesis_id,
            "family": hypothesis.statistical_family,
            "p_value": None,
            "eligible": False,
        }
        for hypothesis in owner_hypotheses()
    )
    correction = family_and_global_bh(
        multiplicity_records
    )
    evidence = {criterion: False for criterion in PROMOTION_CRITERIA}
    evidence.update(
        {
            "data_gate_ready": False,
            "no_leakage": False,
            "preregistered_support": len(primary_rows) >= 80,
            "three_eligible_periods": len(folds) >= 3,
            "stable_direction": all(
                float(
                    fold[
                        "incremental_logistic_vs_recalibrated_market"
                    ]["delta_log_loss"]
                )
                < 0
                for fold in folds
            ),
            "positive_last_fold": (
                float(
                    folds[-1][
                        "incremental_logistic_vs_recalibrated_market"
                    ]["delta_log_loss"]
                )
                < 0
            ),
            "family_bh_passed": (
                correction.family_q_values["H11-A-TEAM-INCREMENTAL"] <= 0.05
            ),
            "global_control_passed": (
                correction.global_q_values["H11-A-TEAM-INCREMENTAL"] <= 0.05
            ),
            "permutation_passed": permutation_p <= 0.05,
            "bootstrap_lower_coherent": bootstrap_upper < 0,
            "incremental_score_vs_market_positive": (
                primary_score.delta_log_loss < 0
            ),
            "rule_interpretable": True,
            "live_information_available": False,
            "live_market_exact_observed_at": False,
            "decision_reproducible_before_kickoff": False,
        }
    )
    promotion = evaluate_promotion(evidence)
    summary: dict[str, object] = {
        "schema_version": "jalon11-team-campaign-v1",
        "numeric_evidence_contract": SCIENTIFIC_FLOAT_CONTRACT_VERSION,
        "campaign": "11A",
        "status": "DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC",
        "promotion_eligible": False,
        "team_gate": "PARTIAL",
        "seed": SEED,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "market_rows": len(frame),
        "paired_1x2_rows": len(all_market),
        "explicit_market_attrition": attrition,
        "folds": folds,
        "models": {
            "B0_MARKET": {
                "log_loss": market_recalibration_score.reference_log_loss,
                "brier": market_recalibration_score.reference_brier,
                "calibration_error": _calibration_error(all_market),
                "calibration_status": "RAW_DEVIGGED_MARKET",
            },
            "B0_MARKET_RECALIBRATED_TRAIN_ONLY": {
                "log_loss": market_recalibration_score.challenger_log_loss,
                "brier": market_recalibration_score.challenger_brier,
                "delta_log_loss_vs_raw_market": (
                    market_recalibration_score.delta_log_loss
                ),
                "delta_brier_vs_raw_market": (
                    market_recalibration_score.delta_brier
                ),
                "calibration_error": _calibration_error(
                    all_market_recalibrated
                ),
                "calibration_status": "TRAIN_ONLY_MULTINOMIAL_LOG_ODDS",
            },
            "B1_TEAM_ONLY_REGULARIZED_MULTINOMIAL": {
                "log_loss": logistic_score.challenger_log_loss,
                "brier": logistic_score.challenger_brier,
                "delta_log_loss": logistic_score.delta_log_loss,
                "delta_brier": logistic_score.delta_brier,
                "calibration_error": _calibration_error(all_logistic),
                "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
            },
            "B1_TEAM_ONLY_BOUNDED_GRADIENT_BOOSTING": {
                "log_loss": boosting_score.challenger_log_loss,
                "brier": boosting_score.challenger_brier,
                "delta_log_loss": boosting_score.delta_log_loss,
                "delta_brier": boosting_score.delta_brier,
                "calibration_error": _calibration_error(all_boosting),
                "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
            },
            "B1_TEAM_ONLY_POISSON": {
                "log_loss": poisson_score.challenger_log_loss,
                "brier": poisson_score.challenger_brier,
                "delta_log_loss": poisson_score.delta_log_loss,
                "delta_brier": poisson_score.delta_brier,
                "calibration_error": _calibration_error(all_poisson),
                "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
            },
            "B1_TEAM_ONLY_DIXON_COLES": {
                "log_loss": dixon_coles_score.challenger_log_loss,
                "brier": dixon_coles_score.challenger_brier,
                "delta_log_loss": dixon_coles_score.delta_log_loss,
                "delta_brier": dixon_coles_score.delta_brier,
                "calibration_error": _calibration_error(all_dixon_coles),
                "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
            },
            "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL": {
                "reference": "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
                "log_loss": primary_score.challenger_log_loss,
                "brier": primary_score.challenger_brier,
                "delta_log_loss": primary_score.delta_log_loss,
                "delta_brier": primary_score.delta_brier,
                "delta_log_loss_vs_raw_market": (
                    incremental_logistic_vs_raw_score.delta_log_loss
                ),
                "delta_brier_vs_raw_market": (
                    incremental_logistic_vs_raw_score.delta_brier
                ),
                "calibration_error": _calibration_error(
                    all_incremental_logistic
                ),
                "status": "PRIMARY_CORRECTIVE_NON_PROMOTABLE_TEAM_GATE_PARTIAL",
            },
            "B1_MARKET_PLUS_TEAM_BOUNDED_GRADIENT_BOOSTING": {
                "reference": "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
                "log_loss": incremental_boosting_score.challenger_log_loss,
                "brier": incremental_boosting_score.challenger_brier,
                "delta_log_loss": incremental_boosting_score.delta_log_loss,
                "delta_brier": incremental_boosting_score.delta_brier,
                "calibration_error": _calibration_error(
                    all_incremental_boosting
                ),
                "status": "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE",
            },
            "primary_for_inference": primary_name,
            "model_selection_on_test": False,
        },
        "statistics": {
            "cr1_one_sided_p": cr1_p,
            "cr1_cluster": "MATCH_DATE",
            "clusters": len(set(clusters)),
            "sign_flip_permutations": 999,
            "sign_flip_unit": "MATCH_DATE",
            "sign_flip_p": permutation_p,
            "family_q": correction.family_q_values[
                "H11-A-TEAM-INCREMENTAL"
            ],
            "global_q": correction.global_q_values[
                "H11-A-TEAM-INCREMENTAL"
            ],
            "multiplicity_hypotheses": len(multiplicity_records),
            "tested_hypotheses": 1,
            "blocked_hypotheses_as_p1": 8,
            "delta_log_loss_bootstrap_ci95": [
                bootstrap_lower,
                bootstrap_upper,
            ],
            "bootstrap_unit": "MATCH_DATE",
            "serial_team_dependence_limitation": True,
        },
        "cross_league": _cross_league_transfer(eligible),
        "negative_controls": _run_negative_controls(
            primary_reference_rows,
            primary_rows,
        ),
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
    normalized_summary = normalize_scientific_evidence(summary)
    if not isinstance(normalized_summary, dict):
        raise TypeError("JALON11_CAMPAIGN_SUMMARY_OBJECT_REQUIRED")
    summary = normalized_summary
    summary["result_hash"] = scientific_evidence_hash(summary)
    _write_json(output / "campaign-11a-summary.json", summary)
    return summary


def build_red_team_report(
    audit: dict[str, object],
    campaign: dict[str, object],
) -> dict[str, object]:
    market_attrition = int(campaign["explicit_market_attrition"])
    objections = {
        "chance": "CONTROLLED_WITH_CR1_CLUSTER_SIGN_FLIP_CLUSTER_BOOTSTRAP_AND_BH",
        "leakage": "TARGET_EXCLUDED_BUT_TEAM_SOURCE_OBSERVED_AT_UNPROVEN_GATE_PARTIAL",
        "concentration": "NO_STRATEGY_PROMOTED",
        "dependence": "MATCH_DATE_CLUSTERED_TEAM_SERIAL_DEPENDENCE_REMAINS_LIMITATION",
        "wrong_odds": "EXACT_FIXTURE_PAIRING_VERIFIED",
        "wrong_cutoff": "TARGET_KICKOFF_EXCLUSIVE_BOUNDARY_NOT_STRICT_OBSERVED_AT",
        "threshold_selection": "PRIMARY_FIXED_NO_TEST_SET_MODEL_SELECTION",
        "incomplete_sample": (
            "NO_1X2_MARKET_ATTRITION"
            if market_attrition == 0
            else f"EXPLICIT_1X2_MARKET_ATTRITION:{market_attrition}"
        ),
        "confounding": "NO_CAUSAL_CLAIM",
        "join_error": "ONE_TO_ONE_EXACT_JOIN",
        "formation_normalization": "CAMPAIGN_BLOCKED",
        "absence_classification": "CAMPAIGN_BLOCKED",
        "calibration": "MARKET_RECALIBRATED_TRAIN_ONLY_TOP_LABEL_ECE_DIAGNOSTIC",
        "multiplicity": "ONE_TESTED_PLUS_EIGHT_BLOCKED_HYPOTHESES_INCLUDED",
        "negative_controls": "SIX_COMPUTATIONAL_OR_GUARD_CONTROLS_EXECUTED_SIX_DATA_GATED",
    }
    return {
        "schema_version": "jalon11-red-team-v1",
        "campaign_result_hash": campaign["result_hash"],
        "audit_source_commit": audit["source_commit"],
        "objections": objections,
        "major_unresolved_objections": [],
        "blocking_limitations": [
            "TEAM_GATE_PARTIAL",
            "PLAYER_ABSENCE_LINEUP_FORMATION_FOOTEDNESS_GATES_BLOCKED",
            "EXACT_LIVE_MARKET_OBSERVED_AT_UNAVAILABLE",
            "TEAM_SERIAL_DEPENDENCE_SENSITIVITY_NOT_MULTIWAY",
        ],
        "negative_controls": campaign["negative_controls"],
        "promotion_allowed": False,
        "reason": "DEEP_DATA_GATES_AND_EXACT_LIVE_MARKET_CUTOFF_REMAIN_CLOSED",
        "independent_review_verdict": "REVISED_AND_FAIL_CLOSED",
        "replay_required": True,
    }


def build_ledger(
    output: Path,
    *,
    code_revision: str,
    dataset_hash: str,
    campaign: dict[str, object],
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
            recorded_at=LEDGER_FROZEN_AT
            + timedelta(microseconds=len(ledger.events)),
        )
        eligibility = evaluate_hypothesis_eligibility(hypothesis, GATE_STATUSES)
        ledger.append(
            event_kind=EvidenceEventKind.DATA_GATE_EVALUATED,
            code_revision=code_revision,
            dataset_hashes=(dataset_hash,),
            status=eligibility.status.value,
            reason=";".join(eligibility.blocking_gates) or "ALL_GATES_READY",
            payload={"hypothesis_id": hypothesis.hypothesis_id},
            recorded_at=LEDGER_FROZEN_AT
            + timedelta(microseconds=len(ledger.events)),
        )
        if not eligibility.eligible:
            ledger.append(
                event_kind=EvidenceEventKind.PATTERN_REJECTED,
                code_revision=code_revision,
                dataset_hashes=(dataset_hash,),
                status="DATA_GATE_BLOCKED",
                reason=";".join(eligibility.blocking_gates),
                payload={"hypothesis_id": hypothesis.hypothesis_id},
                recorded_at=LEDGER_FROZEN_AT
                + timedelta(microseconds=len(ledger.events)),
            )
    models = campaign.get("models")
    statistics = campaign.get("statistics")
    if not isinstance(models, dict) or not isinstance(statistics, dict):
        raise ValueError("JALON11_PRIMARY_LEDGER_EVIDENCE_REQUIRED")
    primary_model_key = str(models.get("primary_for_inference", ""))
    primary_model = models.get(primary_model_key)
    if not primary_model_key or not isinstance(primary_model, dict):
        raise ValueError("JALON11_PRIMARY_LEDGER_MODEL_REQUIRED")
    campaign_result_hash = str(campaign.get("result_hash", ""))
    if len(campaign_result_hash) != 64:
        raise ValueError("JALON11_PRIMARY_LEDGER_RESULT_HASH_REQUIRED")
    sample = campaign.get("sample")
    support_raw = campaign.get("paired_1x2_rows")
    if support_raw is None and isinstance(sample, dict):
        support_raw = sample.get("paired_evaluation_rows")
    if support_raw is None:
        raise ValueError("JALON11_PRIMARY_LEDGER_SUPPORT_REQUIRED")
    delta_log_loss = float(primary_model["delta_log_loss"])
    primary_payload = {
        "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
        "protocol_amendment_hash": PROTOCOL_AMENDMENT_HASH,
        "campaign_result_hash": campaign_result_hash,
        "reference": str(primary_model.get("reference", "")),
        "challenger": primary_model_key,
        "support": int(support_raw),
        "promotion_eligible": False,
    }
    ledger.append(
        event_kind=EvidenceEventKind.HYPOTHESIS_REGISTERED,
        code_revision=code_revision,
        dataset_hashes=(dataset_hash,),
        status="CORRECTIVE_PROTOCOL_AMENDMENT",
        reason="RECORDED_AFTER_TEAM_ONLY_DIAGNOSTICS_BEFORE_AUTHORITATIVE_INCREMENTAL_RUN",
        payload={
            **primary_payload,
            "frozen_before_results": False,
            "model_selection_on_test": False,
        },
        recorded_at=LEDGER_FROZEN_AT
        + timedelta(microseconds=len(ledger.events)),
    )
    ledger.append(
        event_kind=EvidenceEventKind.DATA_GATE_EVALUATED,
        code_revision=code_revision,
        dataset_hashes=(dataset_hash,),
        status="PARTIAL",
        reason="TEAM_GATE_PARTIAL;EXACT_MARKET_OBSERVED_AT_UNAVAILABLE",
        payload={
            **primary_payload,
            "team_gate": str(campaign.get("team_gate", "PARTIAL")),
        },
        recorded_at=LEDGER_FROZEN_AT
        + timedelta(microseconds=len(ledger.events)),
    )
    ledger.append(
        event_kind=EvidenceEventKind.PATTERN_REJECTED,
        code_revision=code_revision,
        dataset_hashes=(dataset_hash,),
        status="DOMINATED" if delta_log_loss >= 0.0 else "DATA_GATE_BLOCKED",
        reason="NO_INCREMENTAL_GAIN_AND_DATA_GATES_CLOSED",
        payload={
            **primary_payload,
            "delta_log_loss": delta_log_loss,
            "delta_brier": float(primary_model["delta_brier"]),
            "cr1_one_sided_p": float(statistics["cr1_one_sided_p"]),
            "sign_flip_p": float(statistics["sign_flip_p"]),
            "family_q": float(statistics["family_q"]),
            "global_q": float(statistics["global_q"]),
        },
        recorded_at=LEDGER_FROZEN_AT
        + timedelta(microseconds=len(ledger.events)),
    )
    destination = output / "public-evidence-ledger-v2.jsonl"
    ledger.write_jsonl(destination)
    summary = ledger.audit()
    _write_json(output / "ledger-audit.json", summary)
    return summary


def build_watchlist(
    output: Path,
    *,
    campaign: dict[str, object],
) -> dict[str, object]:
    watchlist = {
        "schema_version": "deep-football-watchlist-v1",
        "campaign_result_hash": campaign["result_hash"],
        "entries": [],
        "count": 0,
        "status": "EMPTY_NO_ROBUST_DEEP_MATCHUP",
        "not_a_bet": True,
        "production_status": "PRODUCTION_LOCKED",
    }
    _write_json(output / "prospective-watchlist.json", watchlist)
    return watchlist


def build_shadow_candidate_decision(
    output: Path,
    *,
    campaign: dict[str, object],
) -> dict[str, object]:
    promotion = campaign.get("promotion")
    if not isinstance(promotion, dict):
        raise ValueError("JALON11_CAMPAIGN_PROMOTION_REQUIRED")
    candidate_count = int(promotion.get("shadow_candidates", 0))
    if candidate_count != 0 or promotion.get("promoted") is True:
        raise ValueError("JALON11_LIVE_CANDIDATE_REQUIRES_POINT_IN_TIME_PACKAGE")
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
        "exact_observed_at_required": True,
        "real_bets": False,
        "production_status": "PRODUCTION_LOCKED",
    }
    _write_json(output / "shadow-candidate-decision.json", decision)
    return decision


def build_watchlist_and_decision(
    output: Path,
    *,
    campaign: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    return (
        build_watchlist(output, campaign=campaign),
        build_shadow_candidate_decision(output, campaign=campaign),
    )


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


def _complete_run(
    *,
    state: Path,
    output: Path,
    candidate_output: Path,
    source_commit: str,
    main_commit: str,
    main_ci_run_id: str,
    replay: bool,
    previous_campaign: dict[str, object] | None,
    previous_manifest: dict[str, object] | None,
    previous_ledger: dict[str, object] | None,
    previous_ledger_file_hash: str | None,
) -> dict[str, object]:
    """Build a replay candidate away from the immutable primary artifacts."""

    audit = audit_state(
        state,
        source_commit=source_commit,
        main_commit=main_commit,
        main_ci_run_id=main_ci_run_id,
    )
    _write_json(candidate_output / "audit-summary.json", audit)
    manifest = build_team_dataset(state, candidate_output)
    frame, _ = build_team_market_frame(state)
    campaign = run_team_campaign(frame, candidate_output)
    red_team = build_red_team_report(audit, campaign)
    _write_json(candidate_output / "red-team-report.json", red_team)
    watchlist, decision = build_watchlist_and_decision(
        candidate_output,
        campaign=campaign,
    )
    ledger = build_ledger(
        candidate_output,
        code_revision=main_commit,
        dataset_hash=str(manifest["dataset_hash"]),
        campaign=campaign,
    )
    candidate_ledger_file_hash = hashlib.sha256(
        (candidate_output / "public-evidence-ledger-v2.jsonl").read_bytes()
    ).hexdigest()
    build_social_exports(candidate_output)

    hash_comparisons = {
        "campaign_result_hash": (
            previous_campaign is not None
            and previous_campaign.get("result_hash")
            == campaign.get("result_hash")
        ),
        "dataset_hash": (
            previous_manifest is not None
            and previous_manifest.get("dataset_hash")
            == manifest.get("dataset_hash")
        ),
        "parquet_sha256": (
            previous_manifest is not None
            and previous_manifest.get("parquet_sha256")
            == manifest.get("parquet_sha256")
        ),
        "ledger_hash_chain": (
            previous_ledger is not None
            and previous_ledger == ledger
            and previous_ledger_file_hash == candidate_ledger_file_hash
        ),
    }
    data_loss = (
        abs(
            int(previous_manifest.get("rows", 0))
            - int(manifest.get("rows", 0))
        )
        if previous_manifest is not None
        else 0
    )
    hash_mismatches = (
        sum(not matched for matched in hash_comparisons.values())
        if replay
        else 0
    )
    identical = replay and all(hash_comparisons.values()) and data_loss == 0
    if replay and not identical:
        _write_json(
            output / "replay-mismatch.json",
            {
                "status": "JALON11_REPLAY_NON_DETERMINISTIC_PRIMARY_PRESERVED",
                "hash_comparisons": hash_comparisons,
                "data_loss": data_loss,
                "hash_mismatches": hash_mismatches,
                "provider_calls": 0,
                "odds_api_credits": 0,
                "production_status": "PRODUCTION_LOCKED",
            },
        )
        raise RuntimeError(
            "JALON11_REPLAY_NON_DETERMINISTIC_PRIMARY_PRESERVED"
        )

    report = manifest.get("report", {})
    pairing = (
        report.get("pairing", {})
        if isinstance(report, dict)
        else {}
    )
    replay_report = {
        "mode": "REPLAY" if replay else "PRIMARY",
        "status": (
            "REPLAY_FULL_HASH_VERIFIED"
            if replay
            else "PRIMARY_WRITTEN_REPLAY_REQUIRED"
        ),
        "identical": identical,
        "primary_result_hash": (
            previous_campaign.get("result_hash")
            if previous_campaign is not None
            else campaign["result_hash"]
        ),
        "result_hash": campaign["result_hash"],
        "primary_dataset_hash": (
            previous_manifest.get("dataset_hash")
            if previous_manifest is not None
            else manifest["dataset_hash"]
        ),
        "dataset_hash": manifest["dataset_hash"],
        "parquet_sha256": manifest["parquet_sha256"],
        "ledger_head_hash": ledger.get("head_hash"),
        "hash_comparisons": hash_comparisons,
        "code_revision": main_commit,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "business_duplicates": int(pairing.get("duplicate_keys", 0)),
        "data_loss": data_loss,
        "hash_mismatches": hash_mismatches,
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
    candidate_path = output / "campaign-11a-summary.json"
    manifest_path = output / "dataset-manifest.json"
    ledger_path = output / "ledger-audit.json"
    ledger_jsonl_path = output / "public-evidence-ledger-v2.jsonl"
    previous_campaign = (
        json.loads(candidate_path.read_text("utf-8"))
        if replay and candidate_path.exists()
        else None
    )
    previous_manifest = (
        json.loads(manifest_path.read_text("utf-8"))
        if replay and manifest_path.exists()
        else None
    )
    previous_ledger = (
        json.loads(ledger_path.read_text("utf-8"))
        if replay and ledger_path.exists()
        else None
    )
    previous_ledger_file_hash = (
        hashlib.sha256(ledger_jsonl_path.read_bytes()).hexdigest()
        if replay and ledger_jsonl_path.exists()
        else None
    )
    if replay and any(
        value is None
        for value in (
            previous_campaign,
            previous_manifest,
            previous_ledger,
            previous_ledger_file_hash,
        )
    ):
        raise RuntimeError("JALON11_REPLAY_PRIMARY_ARTIFACTS_REQUIRED")
    if replay:
        with tempfile.TemporaryDirectory(
            prefix=".j11-replay-",
            dir=output,
        ) as replay_candidate:
            return _complete_run(
                state=state,
                output=output,
                candidate_output=Path(replay_candidate),
                source_commit=source_commit,
                main_commit=main_commit,
                main_ci_run_id=main_ci_run_id,
                replay=True,
                previous_campaign=previous_campaign,
                previous_manifest=previous_manifest,
                previous_ledger=previous_ledger,
                previous_ledger_file_hash=previous_ledger_file_hash,
            )
    return _complete_run(
        state=state,
        output=output,
        candidate_output=output,
        source_commit=source_commit,
        main_commit=main_commit,
        main_ci_run_id=main_ci_run_id,
        replay=False,
        previous_campaign=None,
        previous_manifest=None,
        previous_ledger=None,
        previous_ledger_file_hash=None,
    )


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
    parser.add_argument("--campaign-file", type=Path)
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
    elif args.command in {"campaign", "validate"}:
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
        else:
            audit = json.loads(audit_path.read_text("utf-8"))
            result = build_red_team_report(audit, campaign)
            _write_json(args.output / "red-team-report.json", result)
    elif args.command in {"watchlist", "decision"}:
        if args.campaign_file is None:
            raise SystemExit("CAMPAIGN_FILE_REQUIRED")
        campaign_value = json.loads(args.campaign_file.read_text("utf-8"))
        if not isinstance(campaign_value, dict):
            raise SystemExit("CAMPAIGN_OBJECT_REQUIRED")
        if args.command == "watchlist":
            result = build_watchlist(args.output, campaign=campaign_value)
        else:
            result = build_shadow_candidate_decision(
                args.output,
                campaign=campaign_value,
            )
    else:
        raise AssertionError("UNREACHABLE_COMMAND")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
