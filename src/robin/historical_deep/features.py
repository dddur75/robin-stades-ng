"""Leakage-safe historical features built from admissible prior fixtures only."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime


def _datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field.upper()}_INVALID") from exc
    else:
        raise ValueError(f"{field.upper()}_REQUIRED")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return result.astimezone(UTC)


def _source_kickoff(row: Mapping[str, object]) -> datetime:
    for field in (
        "source_fixture_kickoff",
        "fixture_kickoff",
        "kickoff_at",
        "source_kickoff_at",
        "target_kickoff_at",
    ):
        if row.get(field) not in (None, ""):
            return _datetime(row[field], field="source_fixture_kickoff")
    raise ValueError("SOURCE_FIXTURE_KICKOFF_REQUIRED")


def _fixture_id(row: Mapping[str, object]) -> str:
    for field in (
        "source_fixture_id",
        "fixture_id",
        "match_id",
        "provider_fixture_id",
        "canonical_fixture_id",
    ):
        if row.get(field) not in (None, ""):
            return str(row[field])
    raise ValueError("SOURCE_FIXTURE_ID_REQUIRED")


def admissible_prior_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
) -> tuple[Mapping[str, object], ...]:
    """Select only rows whose source kickoff is strictly before the target."""

    target = _datetime(target_fixture_kickoff, field="target_fixture_kickoff")
    output = [
        row
        for row in rows
        if _fixture_id(row) != str(target_fixture_id)
        and _source_kickoff(row) < target
        and row.get("strict_prematch_usable", True) is True
    ]
    output.sort(key=lambda row: (_source_kickoff(row), _fixture_id(row)))
    return tuple(output)


def assert_only_admissible_past(
    rows: Sequence[Mapping[str, object]],
    *,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
) -> None:
    target = _datetime(target_fixture_kickoff, field="target_fixture_kickoff")
    for row in rows:
        fixture_id = _fixture_id(row)
        if fixture_id == str(target_fixture_id):
            raise ValueError(f"TARGET_FIXTURE_FEATURE_LEAKAGE:{fixture_id}")
        if _source_kickoff(row) >= target:
            raise ValueError(f"NON_PRIOR_FIXTURE_FEATURE_LEAKAGE:{fixture_id}")
        if row.get("strict_prematch_usable", True) is not True:
            raise ValueError(f"NON_STRICT_DATASET_FEATURE_LEAKAGE:{fixture_id}")


def _numeric(row: Mapping[str, object], *fields: str) -> float | None:
    mappings: list[Mapping[str, object]] = [row]
    data = row.get("data")
    if isinstance(data, Mapping):
        mappings.append(data)
        statistics = data.get("statistics")
        if isinstance(statistics, Mapping):
            mappings.append(statistics)
            mappings.extend(
                value
                for value in statistics.values()
                if isinstance(value, Mapping)
            )
            paths = {
                "minutes": ("games", "minutes"),
                "goals": ("goals", "total"),
                "assists": ("goals", "assists"),
                "shots": ("shots", "total"),
                "total_shots": ("shots", "total"),
                "yellow_cards": ("cards", "yellow"),
                "red_cards": ("cards", "red"),
            }
            for field in fields:
                path = paths.get(field)
                if path is None:
                    continue
                bucket = statistics.get(path[0])
                if not isinstance(bucket, Mapping):
                    continue
                value = bucket.get(path[1])
                if value is None or isinstance(value, (bool, Mapping, list, tuple)):
                    continue
                text = str(value).strip().removesuffix("%")
                try:
                    return float(text)
                except ValueError as exc:
                    raise ValueError(f"FEATURE_NON_NUMERIC:{field}") from exc
    for field in fields:
        for mapping in mappings:
            value = mapping.get(field)
            if value is None or isinstance(value, (bool, Mapping, list, tuple)):
                continue
            text = str(value).strip().removesuffix("%")
            try:
                return float(text)
            except ValueError as exc:
                raise ValueError(f"FEATURE_NON_NUMERIC:{field}") from exc
    return None


def _typed_statistic(
    row: Mapping[str, object],
    *labels: str,
) -> float | None:
    data = row.get("data")
    if not isinstance(data, Mapping):
        return None
    observed = str(data.get("type", "")).strip().casefold().replace(" ", "_")
    expected = {label.casefold().replace(" ", "_") for label in labels}
    if observed not in expected:
        return None
    value = data.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip().removesuffix("%"))
    except ValueError as exc:
        raise ValueError(f"FEATURE_NON_NUMERIC:{observed}") from exc


def _started(row: Mapping[str, object]) -> bool | None:
    value = row.get("started")
    if isinstance(value, bool):
        return value
    data = row.get("data")
    if not isinstance(data, Mapping):
        return None
    statistics = data.get("statistics")
    if not isinstance(statistics, Mapping):
        return None
    games = statistics.get("games")
    if not isinstance(games, Mapping):
        return None
    substitute = games.get("substitute")
    return not substitute if isinstance(substitute, bool) else None


def _identifier(row: Mapping[str, object], *fields: str) -> str:
    candidates: list[object] = [row.get(field) for field in fields]
    data = row.get("data")
    if isinstance(data, Mapping):
        candidates.extend(data.get(field) for field in fields)
        for entity in ("team", "player"):
            nested = data.get(entity)
            if isinstance(nested, Mapping):
                candidates.extend(nested.get(field) for field in ("id", *fields))
    return next(
        (
            str(value)
            for value in candidates
            if value is not None and str(value).strip()
        ),
        "",
    )


def _complete_sum(values: Sequence[float | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _complete_mean(values: Sequence[float | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    return statistics.fmean(value for value in values if value is not None)


def _team_perspective(
    row: Mapping[str, object],
    *,
    team_id: str,
) -> dict[str, float | bool | None] | None:
    direct_team = _identifier(
        row,
        "team_id",
        "provider_team_id",
        "canonical_team_id",
    )
    home = str(row.get("home_team_id", row.get("home_team", "")))
    away = str(row.get("away_team_id", row.get("away_team", "")))
    if direct_team and direct_team != team_id:
        return None
    if not direct_team and team_id not in {home, away}:
        return None
    data = row.get("data")
    data_mapping = data if isinstance(data, Mapping) else {}
    is_home = (
        team_id == home
        if not direct_team
        else row.get("is_home", data_mapping.get("is_home"))
    )
    if is_home is None and data_mapping.get("side") in {"home", "away"}:
        is_home = data_mapping.get("side") == "home"
    if is_home is None:
        is_home_value: bool | None = None
    else:
        is_home_value = bool(is_home)
    goals_for = _numeric(row, "goals_for")
    goals_against = _numeric(row, "goals_against")
    if goals_for is None and is_home_value is not None:
        goals_for = _numeric(row, "home_goals" if is_home_value else "away_goals")
    if goals_against is None and is_home_value is not None:
        goals_against = _numeric(
            row,
            "away_goals" if is_home_value else "home_goals",
        )
    points = _numeric(row, "points")
    if points is None and goals_for is not None and goals_against is not None:
        points = 3.0 if goals_for > goals_against else 1.0 if goals_for == goals_against else 0.0
    yellow_cards = _numeric(row, "yellow_cards", "team_yellow_cards")
    red_cards = _numeric(row, "red_cards", "team_red_cards")
    return {
        "goals_for": goals_for,
        "goals_against": goals_against,
        "points": points,
        "yellow_cards": (
            yellow_cards
            if yellow_cards is not None
            else _typed_statistic(row, "yellow cards", "yellow_cards")
        ),
        "red_cards": (
            red_cards
            if red_cards is not None
            else _typed_statistic(row, "red cards", "red_cards")
        ),
        "is_home": is_home_value,
    }


def build_team_features(
    rows: Sequence[Mapping[str, object]],
    *,
    team_id: str,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
    windows: Sequence[int] = (3, 5, 10),
) -> dict[str, object]:
    if not windows or any(window <= 0 for window in windows):
        raise ValueError("TEAM_FEATURE_WINDOWS_MUST_BE_POSITIVE")
    if tuple(sorted(set(windows))) != tuple(windows):
        raise ValueError("TEAM_FEATURE_WINDOWS_MUST_BE_SORTED_UNIQUE")
    target = _datetime(target_fixture_kickoff, field="target_fixture_kickoff")
    prior = admissible_prior_rows(
        rows,
        target_fixture_id=target_fixture_id,
        target_fixture_kickoff=target,
    )
    grouped: dict[
        str,
        tuple[Mapping[str, object], dict[str, float | bool | None]],
    ] = {}
    for row in prior:
        values = _team_perspective(row, team_id=team_id)
        if values is None:
            continue
        fixture_id = _fixture_id(row)
        if fixture_id not in grouped:
            grouped[fixture_id] = (row, dict(values))
            continue
        representative, existing = grouped[fixture_id]
        for field, value in values.items():
            current = existing.get(field)
            if current is not None and value is not None and current != value:
                raise ValueError(f"TEAM_FEATURE_CONFLICT:{fixture_id}:{field}")
            if current is None:
                existing[field] = value
        grouped[fixture_id] = (representative, existing)
    perspective = sorted(
        grouped.values(),
        key=lambda item: (_source_kickoff(item[0]), _fixture_id(item[0])),
    )
    result: dict[str, object] = {
        "team_id": team_id,
        "target_fixture_id": str(target_fixture_id),
        "target_fixture_kickoff": target.isoformat(),
        "feature_cutoff": "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        "prior_matches_available": len(perspective),
        "rest_days": (
            (target - _source_kickoff(perspective[-1][0])).total_seconds() / 86_400
            if perspective
            else None
        ),
        "matches_last_7_days": sum(
            0 < (target - _source_kickoff(row)).total_seconds() <= 7 * 86_400
            for row, _ in perspective
        )
        if perspective
        else None,
        "matches_last_14_days": sum(
            0 < (target - _source_kickoff(row)).total_seconds() <= 14 * 86_400
            for row, _ in perspective
        )
        if perspective
        else None,
    }
    for window in windows:
        sample = [values for _, values in perspective[-window:]]
        result[f"matches_{window}"] = len(sample)
        result[f"history_status_{window}"] = (
            "SUFFICIENT_HISTORY"
            if len(sample) == window
            else "INSUFFICIENT_HISTORY"
        )
        result[f"points_{window}"] = _complete_sum(
            [value["points"] for value in sample]
        )
        result[f"goals_for_avg_{window}"] = _complete_mean(
            [value["goals_for"] for value in sample]
        )
        result[f"goals_against_avg_{window}"] = _complete_mean(
            [value["goals_against"] for value in sample]
        )
        result[f"yellow_cards_{window}"] = _complete_sum(
            [value["yellow_cards"] for value in sample]
        )
        result[f"red_cards_{window}"] = _complete_sum(
            [value["red_cards"] for value in sample]
        )
    return result


def build_player_features(
    rows: Sequence[Mapping[str, object]],
    *,
    player_id: str,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
    windows: Sequence[int] = (3, 5),
) -> dict[str, object]:
    if not windows or any(window <= 0 for window in windows):
        raise ValueError("PLAYER_FEATURE_WINDOWS_MUST_BE_POSITIVE")
    target = _datetime(target_fixture_kickoff, field="target_fixture_kickoff")
    prior_rows = [
        row
        for row in admissible_prior_rows(
            rows,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target,
        )
        if _identifier(
            row,
            "player_id",
            "provider_player_id",
            "canonical_player_id",
        )
        == str(player_id)
    ]
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in prior_rows:
        grouped.setdefault(_fixture_id(row), []).append(row)
    prior = sorted(
        grouped.items(),
        key=lambda item: (_source_kickoff(item[1][0]), item[0]),
    )

    def metric(
        fixture_rows: Sequence[Mapping[str, object]],
        *fields: str,
    ) -> float | None:
        values = [
            value
            for row in fixture_rows
            if (value := _numeric(row, *fields)) is not None
        ]
        if not values:
            return None
        if any(value != values[0] for value in values[1:]):
            raise ValueError(
                f"PLAYER_FEATURE_CONFLICT:{_fixture_id(fixture_rows[0])}:{fields[0]}"
            )
        return values[0]

    def started(
        fixture_rows: Sequence[Mapping[str, object]],
    ) -> float | None:
        values = [
            value
            for row in fixture_rows
            if (value := _started(row)) is not None
        ]
        if not values:
            return None
        if any(value is not values[0] for value in values[1:]):
            raise ValueError(
                f"PLAYER_FEATURE_CONFLICT:{_fixture_id(fixture_rows[0])}:started"
            )
        return 1.0 if values[0] else 0.0

    result: dict[str, object] = {
        "player_id": str(player_id),
        "target_fixture_id": str(target_fixture_id),
        "feature_cutoff": "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        "prior_appearances_available": len(prior),
    }
    for window in windows:
        sample = [rows_for_fixture for _, rows_for_fixture in prior[-window:]]
        minutes = [metric(rows_for_fixture, "minutes") for rows_for_fixture in sample]
        starts = [started(rows_for_fixture) for rows_for_fixture in sample]
        result[f"appearances_{window}"] = len(sample)
        result[f"history_status_{window}"] = (
            "SUFFICIENT_HISTORY"
            if len(sample) == window
            else "INSUFFICIENT_HISTORY"
        )
        result[f"minutes_{window}"] = _complete_sum(minutes)
        result[f"starts_{window}"] = _complete_sum(starts)
        result[f"goals_{window}"] = _complete_sum(
            [metric(rows_for_fixture, "goals") for rows_for_fixture in sample]
        )
        result[f"assists_{window}"] = _complete_sum(
            [metric(rows_for_fixture, "assists") for rows_for_fixture in sample]
        )
        result[f"shots_{window}"] = _complete_sum(
            [
                metric(rows_for_fixture, "shots", "total_shots")
                for rows_for_fixture in sample
            ]
        )
        result[f"yellow_cards_{window}"] = _complete_sum(
            [
                metric(rows_for_fixture, "yellow_cards")
                for rows_for_fixture in sample
            ]
        )
        result[f"red_cards_{window}"] = _complete_sum(
            [
                metric(rows_for_fixture, "red_cards")
                for rows_for_fixture in sample
            ]
        )
    return result


def _lineup_players(row: Mapping[str, object]) -> tuple[str, ...] | None:
    data = row.get("data")
    data_mapping = data if isinstance(data, Mapping) else {}
    raw = row.get(
        "starters",
        row.get(
            "player_ids",
            row.get(
                "lineup",
                data_mapping.get("starters", data_mapping.get("startXI")),
            ),
        ),
    )
    if not isinstance(raw, (list, tuple)):
        return None
    players: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            nested_player = item.get("player")
            player = item.get(
                "player_id",
                item.get(
                    "id",
                    nested_player.get("id")
                    if isinstance(nested_player, Mapping)
                    else None,
                ),
            )
        else:
            player = item
        if player in (None, ""):
            return None
        players.append(str(player))
    if len(players) != len(set(players)):
        return None
    return tuple(players)


def _formation(row: Mapping[str, object]) -> object | None:
    value = row.get("formation")
    if value not in (None, ""):
        return value
    data = row.get("data")
    return data.get("formation") if isinstance(data, Mapping) else None


def build_lineup_continuity_features(
    rows: Sequence[Mapping[str, object]],
    *,
    team_id: str,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
    baseline_window: int = 5,
) -> dict[str, object]:
    if baseline_window <= 0:
        raise ValueError("LINEUP_BASELINE_WINDOW_MUST_BE_POSITIVE")
    prior = [
        row
        for row in admissible_prior_rows(
            rows,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target_fixture_kickoff,
        )
        if _identifier(
            row,
            "team_id",
            "provider_team_id",
            "canonical_team_id",
        )
        == str(team_id)
    ]
    complete = [
        (row, players)
        for row in prior
        if (players := _lineup_players(row)) is not None and len(players) == 11
    ]
    latest = complete[-1][1] if complete else None
    previous = complete[-2][1] if len(complete) >= 2 else None
    sample = complete[-baseline_window:]
    counts = Counter(player for _, lineup in sample for player in lineup)
    baseline = (
        tuple(
            sorted(
                (
                    player
                    for player, count in counts.items()
                    if count >= (baseline_window + 1) // 2
                ),
                key=lambda player: (-counts[player], player),
            )
        )
        if len(sample) == baseline_window
        else ()
    )
    return {
        "team_id": str(team_id),
        "target_fixture_id": str(target_fixture_id),
        "feature_cutoff": "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        "complete_prior_lineups": len(complete),
        "latest_prior_lineup_fixture_id": (
            _fixture_id(complete[-1][0]) if complete else None
        ),
        "prior_to_prior_continuity": (
            len(set(latest) & set(previous)) / 11.0
            if latest is not None and previous is not None
            else None
        ),
        "usual_starters_prior_only": list(baseline[:11]),
        "usual_starters_complete": (
            len(sample) == baseline_window and len(baseline) >= 11
        ),
        "starter_baseline_history_status": (
            "SUFFICIENT_HISTORY"
            if len(sample) == baseline_window
            else "INSUFFICIENT_HISTORY"
        ),
        "latest_prior_formation": _formation(complete[-1][0]) if complete else None,
        "formation_changed_between_last_two_prior": (
            _formation(complete[-1][0]) != _formation(complete[-2][0])
            if len(complete) >= 2
            and _formation(complete[-1][0]) is not None
            and _formation(complete[-2][0]) is not None
            else None
        ),
    }


def build_discipline_features(
    rows: Sequence[Mapping[str, object]],
    *,
    entity_id: str,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
    window: int = 5,
) -> dict[str, object]:
    if window <= 0:
        raise ValueError("DISCIPLINE_WINDOW_MUST_BE_POSITIVE")
    prior = [
        row
        for row in admissible_prior_rows(
            rows,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target_fixture_kickoff,
        )
        if _identifier(
            row,
            "entity_id",
            "team_id",
            "player_id",
            "provider_team_id",
            "provider_player_id",
            "canonical_team_id",
            "canonical_player_id",
        )
        == str(entity_id)
    ][-window:]
    return {
        "entity_id": str(entity_id),
        "target_fixture_id": str(target_fixture_id),
        "feature_cutoff": "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        "observations": len(prior),
        "yellow_cards": _complete_sum(
            [_numeric(row, "yellow_cards") for row in prior]
        ),
        "red_cards": _complete_sum(
            [_numeric(row, "red_cards") for row in prior]
        ),
        "second_yellow_cards": _complete_sum(
            [_numeric(row, "second_yellow_cards") for row in prior]
        ),
        "suspension_matches": _complete_sum(
            [_numeric(row, "suspension_matches") for row in prior]
        ),
    }


def build_historical_feature_bundle(
    *,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
    team_id: str,
    team_rows: Sequence[Mapping[str, object]],
    player_rows: Sequence[Mapping[str, object]],
    lineup_rows: Sequence[Mapping[str, object]],
    discipline_rows: Sequence[Mapping[str, object]],
    player_ids: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "target_fixture_id": str(target_fixture_id),
        "team": build_team_features(
            team_rows,
            team_id=team_id,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target_fixture_kickoff,
        ),
        "players": {
            str(player_id): build_player_features(
                player_rows,
                player_id=str(player_id),
                target_fixture_id=target_fixture_id,
                target_fixture_kickoff=target_fixture_kickoff,
            )
            for player_id in player_ids
        },
        "lineup_continuity": build_lineup_continuity_features(
            lineup_rows,
            team_id=team_id,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target_fixture_kickoff,
        ),
        "discipline": build_discipline_features(
            discipline_rows,
            entity_id=team_id,
            target_fixture_id=target_fixture_id,
            target_fixture_kickoff=target_fixture_kickoff,
        ),
        "production_status": "PRODUCTION_LOCKED",
        "promotion": "NO_PROMOTION",
    }
