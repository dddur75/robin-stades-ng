from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from robin.historical import dataset_factory
from robin.historical.dataset_factory import build_player_feature_datasets
from robin.historical.features import build_team_feature_rows
from robin.historical.normalization import availability_for_endpoint


def test_target_match_cannot_feed_its_own_team_features() -> None:
    rows = build_team_feature_rows(
        [
            {
                "match_id": "first",
                "date": "2024-01-01T18:00:00Z",
                "home": "A",
                "away": "B",
                "season": 2024,
                "fthg": 3,
                "ftag": 0,
            },
            {
                "match_id": "target",
                "date": "2024-01-08T18:00:00Z",
                "home": "A",
                "away": "B",
                "season": 2024,
                "fthg": 0,
                "ftag": 4,
            },
        ]
    )
    assert rows[0]["home_form_5"] is None
    assert rows[1]["home_form_5"] == 3.0
    assert rows[1]["home_goals_for_5"] == 3.0


def _fact(
    fixture_id: int,
    player_id: int,
    team_id: int,
    kickoff: str,
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "competition": "Ligue 1",
        "season": 2024,
        "kickoff_at": kickoff,
        "player_id": player_id,
        "player_name": f"P{player_id}",
        "team_id": team_id,
        "position": "Midfielder",
        "minutes": 90,
        "starter": True,
        "rating": 7.0,
        "goals": None,
        "assists": None,
        "shots": None,
        "shots_on_goal": None,
        "key_passes": None,
        "tackles": None,
        "interceptions": None,
        "duels": None,
        "duels_won": None,
        "fouls": None,
        "yellow_cards": None,
        "red_cards": None,
        "source": "API-FOOTBALL HISTORICAL",
        "availability_status": "POST_MATCH_ONLY",
        "raw_payload_hash": "a" * 64,
    }


def test_target_lineup_is_only_available_in_simulated_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_facts = [
        *[_fact(1, player, 10, "2024-01-01T18:00:00Z") for player in range(1, 12)],
        *[_fact(1, player, 20, "2024-01-01T18:00:00Z") for player in range(21, 32)],
    ]
    monkeypatch.setattr(
        dataset_factory,
        "player_match_facts",
        lambda state, seasons: first_facts,
    )
    monkeypatch.setattr(
        dataset_factory,
        "_lineups",
        lambda state, seasons: {
            (2, 10): {
                "starting_ids": list(range(1, 12)),
                "bench_ids": [],
                "formation": "4-3-3",
            },
            (2, 20): {
                "starting_ids": list(range(21, 32)),
                "bench_ids": [],
                "formation": "3-4-3",
            },
        },
    )
    team_rows = [
        {
            "fixture_id": 1,
            "competition": "Ligue 1",
            "season": 2024,
            "kickoff_at": "2024-01-01T18:00:00+00:00",
            "as_of_time": "2024-01-01T18:00:00+00:00",
            "home_team_id": 10,
            "away_team_id": 20,
            "availability_status": "POINT_IN_TIME_SAFE",
        },
        {
            "fixture_id": 2,
            "competition": "Ligue 1",
            "season": 2024,
            "kickoff_at": "2024-01-08T18:00:00+00:00",
            "as_of_time": "2024-01-08T18:00:00+00:00",
            "home_team_id": 10,
            "away_team_id": 20,
            "availability_status": "POINT_IN_TIME_SAFE",
        },
    ]
    _, pre, post = build_player_feature_datasets(
        tmp_path,
        team_rows=team_rows,
        seasons=(2024,),
    )
    target_pre = next(row for row in pre if row["fixture_id"] == 2)
    target_post = next(row for row in post if row["fixture_id"] == 2)
    assert target_pre["home_expected_formation"] is None
    assert target_post["home_confirmed_formation"] == "4-3-3"
    assert target_post["temporal_policy"] == "POST_LINEUP_SIMULATED"


def test_missing_player_values_never_become_zero() -> None:
    values = dataset_factory._feature_values([], datetime.now(UTC))
    assert values["minutes_last_5"] is None
    assert values["goals_last_10"] is None
    assert values["player_strength"] is None


def test_transferred_player_keeps_provider_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    facts = [
        _fact(1, 77, 10, "2024-01-01T18:00:00Z"),
        _fact(2, 77, 20, "2024-01-08T18:00:00Z"),
    ]
    monkeypatch.setattr(
        dataset_factory,
        "player_match_facts",
        lambda state, seasons: facts,
    )
    monkeypatch.setattr(dataset_factory, "_lineups", lambda state, seasons: {})
    team_rows = [
        {
            "fixture_id": fixture_id,
            "competition": "Ligue 1",
            "season": 2024,
            "kickoff_at": kickoff.replace("Z", "+00:00"),
            "as_of_time": kickoff.replace("Z", "+00:00"),
            "home_team_id": 10,
            "away_team_id": 20,
            "availability_status": "POINT_IN_TIME_SAFE",
        }
        for fixture_id, kickoff in (
            (1, "2024-01-01T18:00:00Z"),
            (2, "2024-01-08T18:00:00Z"),
            (3, "2024-01-15T18:00:00Z"),
        )
    ]
    features, _, _ = build_player_feature_datasets(
        tmp_path,
        team_rows=team_rows,
        seasons=(2024,),
    )
    after_transfer = [
        row
        for row in features
        if row["fixture_id"] == 3 and row["player_id"] == 77
    ]
    assert after_transfer
    assert {row["team_id"] for row in after_transfer} == {20}


def test_injuries_without_historical_timestamp_remain_excluded() -> None:
    assert (
        availability_for_endpoint("injuries").value
        == "HISTORICAL_NON_POINT_IN_TIME"
    )
