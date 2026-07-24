"""Feature factory historique strictement point-in-time."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def season_start(value: object) -> int:
    text = str(value).strip()
    try:
        return int(text[:4])
    except ValueError as exc:
        raise ValueError(f"saison invalide: {text}") from exc


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


@dataclass
class TeamState:
    elo: float = 1500.0
    goals_for: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    goals_against: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    points: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    last_match_at: datetime | None = None


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _tail_mean(values: deque[float], size: int) -> float | None:
    return _mean(list(values)[-size:])


def _result_points(goals_for: float, goals_against: float) -> float:
    if goals_for > goals_against:
        return 3.0
    if goals_for == goals_against:
        return 1.0
    return 0.0


def _elo_expected(home_elo: float, away_elo: float, home_advantage: float = 60.0) -> float:
    return float(
        1.0 / (1.0 + 10.0 ** (-(home_elo + home_advantage - away_elo) / 400.0))
    )


def build_team_feature_rows(
    matches: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Calculer les features avant de mettre à jour l'état avec le match cible."""

    ordered = sorted(
        matches,
        key=lambda row: (
            datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")),
            str(row.get("match_id", "")),
        ),
    )
    states: defaultdict[str, TeamState] = defaultdict(TeamState)
    output: list[dict[str, object]] = []
    for match in ordered:
        kickoff = datetime.fromisoformat(str(match["date"]).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        home = str(match["home"])
        away = str(match["away"])
        home_state = states[home]
        away_state = states[away]
        home_goals = _number(match.get("fthg"))
        away_goals = _number(match.get("ftag"))
        feature_row: dict[str, object] = {
            "fixture_id": str(match.get("match_id", f"{home}:{away}:{kickoff.isoformat()}")),
            "competition": str(match.get("league", "unknown")),
            "season": season_start(match.get("season")),
            "kickoff_at": kickoff.isoformat(),
            "as_of_time": (kickoff.replace(microsecond=0)).isoformat(),
            "home_team": home,
            "away_team": away,
            "home_elo": home_state.elo,
            "away_elo": away_state.elo,
            "elo_difference": home_state.elo - away_state.elo,
            "home_form_5": _tail_mean(home_state.points, 5),
            "away_form_5": _tail_mean(away_state.points, 5),
            "home_form_10": _tail_mean(home_state.points, 10),
            "away_form_10": _tail_mean(away_state.points, 10),
            "home_goals_for_5": _tail_mean(home_state.goals_for, 5),
            "away_goals_for_5": _tail_mean(away_state.goals_for, 5),
            "home_goals_against_5": _tail_mean(home_state.goals_against, 5),
            "away_goals_against_5": _tail_mean(away_state.goals_against, 5),
            "home_rest_days": (
                (kickoff - home_state.last_match_at).days
                if home_state.last_match_at is not None
                else None
            ),
            "away_rest_days": (
                (kickoff - away_state.last_match_at).days
                if away_state.last_match_at is not None
                else None
            ),
            "availability_status": "POINT_IN_TIME_SAFE",
            "source": str(match.get("source", "LEGACY SOURCE")),
            "target_home_goals": home_goals,
            "target_away_goals": away_goals,
            "target_availability": "POST_MATCH_ONLY",
            "odds_home": _number(match.get("psch") or match.get("psh")),
            "odds_draw": _number(match.get("pscd") or match.get("psd")),
            "odds_away": _number(match.get("psca") or match.get("psa")),
            "odds_over_25": _number(match.get("pc_o25") or match.get("p_o25")),
            "odds_under_25": _number(match.get("pc_u25") or match.get("p_u25")),
        }
        output.append(feature_row)

        if home_goals is None or away_goals is None:
            continue
        expected_home = _elo_expected(home_state.elo, away_state.elo)
        score_home = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        delta = 20.0 * (score_home - expected_home)
        home_state.elo += delta
        away_state.elo -= delta
        home_state.goals_for.append(home_goals)
        home_state.goals_against.append(away_goals)
        away_state.goals_for.append(away_goals)
        away_state.goals_against.append(home_goals)
        home_state.points.append(_result_points(home_goals, away_goals))
        away_state.points.append(_result_points(away_goals, home_goals))
        home_state.last_match_at = kickoff
        away_state.last_match_at = kickoff
    return output


def assert_temporal_integrity(rows: Iterable[Mapping[str, object]]) -> None:
    for row in rows:
        kickoff = datetime.fromisoformat(str(row["kickoff_at"]).replace("Z", "+00:00"))
        as_of = datetime.fromisoformat(str(row["as_of_time"]).replace("Z", "+00:00"))
        if as_of > kickoff:
            raise ValueError(f"feature future pour {row.get('fixture_id')}")
        if row.get("availability_status") != "POINT_IN_TIME_SAFE":
            raise ValueError(f"feature non sûre pour {row.get('fixture_id')}")


def dataset_manifest(
    rows: Iterable[Mapping[str, object]],
    *,
    name: str,
    code_version: str,
    policy: str = "PRE_LINEUP",
) -> dict[str, object]:
    items = [dict(row) for row in rows]
    serialized = json.dumps(
        items,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    seasons = sorted({int(str(row["season"])) for row in items})
    competitions = sorted({str(row["competition"]) for row in items})
    return {
        "dataset_name": name,
        "dataset_version": name,
        "competitions": competitions,
        "seasons": seasons,
        "matches": len(items),
        "rows": len(items),
        "features": sorted(
            key
            for key in items[0].keys()
            if items and key not in {"target_home_goals", "target_away_goals"}
        )
        if items
        else [],
        "exclusions": [],
        "coverage": 1.0 if items else 0.0,
        "quality": "PASSED" if items else "NO_OUTPUT",
        "created_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "code_version": code_version,
        "temporal_policy": policy,
        "target": "1X2_AND_TOTAL_2_5",
        "odds_availability": sum(
            1 for row in items if row.get("odds_home") is not None
        ),
        "origin": sorted({str(row.get("source", "UNKNOWN")) for row in items}),
    }
