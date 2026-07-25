"""Baselines interprétables et backtest walk-forward sans fuite OOS."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime


def _probabilities(row: Mapping[str, object]) -> tuple[float, float, float]:
    difference = float(str(row["elo_difference"]))
    home_no_draw = 1.0 / (1.0 + 10.0 ** (-(difference + 60.0) / 400.0))
    draw = 0.26
    return home_no_draw * (1.0 - draw), draw, (1.0 - home_no_draw) * (1.0 - draw)


def _target(row: Mapping[str, object]) -> int | None:
    home = row.get("target_home_goals")
    away = row.get("target_away_goals")
    if home is None or away is None:
        return None
    home_goals, away_goals = float(str(home)), float(str(away))
    return 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2


def _metrics(rows: Iterable[Mapping[str, object]]) -> dict[str, float | int]:
    losses: list[float] = []
    briers: list[float] = []
    for row in rows:
        target = _target(row)
        if target is None:
            continue
        probabilities = _probabilities(row)
        losses.append(-math.log(max(probabilities[target], 1e-12)))
        briers.append(
            sum(
                (probability - (1.0 if index == target else 0.0)) ** 2
                for index, probability in enumerate(probabilities)
            )
            / 3.0
        )
    return {
        "matches": len(losses),
        "log_loss": sum(losses) / len(losses) if losses else float("nan"),
        "brier_score": sum(briers) / len(briers) if briers else float("nan"),
    }


def train_elo_baseline(
    rows: Iterable[Mapping[str, object]],
    *,
    dataset_hash: str,
    discovery: tuple[int, ...] = (2018, 2019, 2020, 2021, 2022),
    validation: tuple[int, ...] = (2023,),
    oos: tuple[int, ...] = (2024, 2025),
) -> dict[str, object]:
    items = [dict(row) for row in rows]
    discovery_rows = [
        row for row in items if int(str(row["season"])) in discovery
    ]
    validation_rows = [
        row for row in items if int(str(row["season"])) in validation
    ]
    oos_rows = [row for row in items if int(str(row["season"])) in oos]
    parameters = {
        "k_factor": 20.0,
        "home_advantage": 60.0,
        "draw_probability": 0.26,
    }
    artifact_hash = hashlib.sha256(
        json.dumps(
            {"dataset_hash": dataset_hash, "parameters": parameters},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "model_name": "elo",
        "model_version": "elo_v1",
        "dataset_hash": dataset_hash,
        "features": ["elo_difference"],
        "parameters": parameters,
        "discovery_period": list(discovery),
        "validation_period": list(validation),
        "oos_period": list(oos),
        "discovery_metrics": _metrics(discovery_rows),
        "validation_metrics": _metrics(validation_rows),
        "oos_metrics": _metrics(oos_rows),
        "calibration": "FIXED_INTERPRETABLE_BASELINE",
        "artifact_hash": artifact_hash,
        "trained_at": datetime.now(UTC).isoformat(),
        "status": "OOS_BACKTEST_V1_READY" if oos_rows else "BLOCKED_BY_COVERAGE",
        "production_status": "PRODUCTION_LOCKED",
    }


def backtest_fixed_stake(
    rows: Iterable[Mapping[str, object]],
    *,
    seasons: tuple[int, ...] = (2024, 2025),
    minimum_edge: float = 0.05,
) -> dict[str, object]:
    bets: list[dict[str, object]] = []
    bankroll = 100.0
    peak = bankroll
    max_drawdown = 0.0
    for row in rows:
        if int(str(row["season"])) not in seasons:
            continue
        target = _target(row)
        if target is None:
            continue
        probabilities = _probabilities(row)
        odds = (row.get("odds_home"), row.get("odds_draw"), row.get("odds_away"))
        candidates: list[tuple[int, float, float]] = []
        for index, (probability, price) in enumerate(
            zip(probabilities, odds, strict=True)
        ):
            if price is None:
                continue
            numeric_price = float(str(price))
            if numeric_price > 1.0:
                candidates.append((index, probability, numeric_price))
        if not candidates:
            continue
        selection, probability, price = max(
            candidates,
            key=lambda candidate: candidate[1] * candidate[2] - 1.0,
        )
        edge = probability * price - 1.0
        if edge < minimum_edge:
            continue
        profit = price - 1.0 if selection == target else -1.0
        bankroll += profit
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, peak - bankroll)
        bets.append(
            {
                "fixture_id": row["fixture_id"],
                "season": row["season"],
                "selection": selection,
                "probability": probability,
                "odds": price,
                "edge": edge,
                "profit": profit,
                "bankroll": bankroll,
            }
        )
    profit = bankroll - 100.0
    return {
        "backtest_version": "historical_backtest_v2",
        "model_version": "elo_v1",
        "strategy": "elo_edge_5pct_fixed_stake",
        "market": "1X2",
        "oos_period": list(seasons),
        "bets": len(bets),
        "profit_units": profit,
        "roi": profit / len(bets) if bets else None,
        "max_drawdown_units": max_drawdown,
        "status": "REJECTED",
        "production_status": "PRODUCTION_LOCKED",
        "details": bets,
        "generated_at": datetime.now(UTC).isoformat(),
    }
