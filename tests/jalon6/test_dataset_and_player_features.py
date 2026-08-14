from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from robin.historical import dataset_factory
from robin.historical.dataset_factory import (
    build_player_feature_datasets,
    write_dataset,
)
from robin.historical.features import (
    TEMPORAL_VALIDITY_NOT_PROVEN,
    build_team_feature_rows,
)
from robin.historical.normalization import availability_for_endpoint
from robin.historical.storage import load_dataset_snapshot, write_json_atomic
from scripts.run_historical_pipeline import _dataset_rows


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
    assert target_post["temporal_policy"] == TEMPORAL_VALIDITY_NOT_PROVEN
    assert target_post["feature_cutoff_stage"] == "POST_LINEUP_SIMULATED"


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


def _snapshot_row(fixture_id: int, *, season: int = 2024) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "competition": "Ligue 1",
        "season": season,
        "kickoff_at": f"{season}-01-{fixture_id:02d}T18:00:00+00:00",
        "as_of_time": f"{season}-01-{fixture_id:02d}T18:00:00+00:00",
        "availability_status": TEMPORAL_VALIDITY_NOT_PROVEN,
        "temporal_policy": TEMPORAL_VALIDITY_NOT_PROVEN,
        "source": "LOCAL_TEST_FIXTURE",
    }


def test_dataset_snapshot_is_immutable_content_addressed_and_exactly_loaded(
    tmp_path: Path,
) -> None:
    first_rows = [_snapshot_row(1)]
    first = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=first_rows,
        code_revision="one",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    second_rows = [_snapshot_row(2)]
    second = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=second_rows,
        code_revision="two",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    assert first["sha256"] != second["sha256"]
    assert first["partitions"][0]["path"] != second["partitions"][0]["path"]  # type: ignore[index]
    assert load_dataset_snapshot(
        tmp_path,
        first,
        expected_dataset_name="api_team_pre_match_v1",
    ) == first_rows
    assert load_dataset_snapshot(
        tmp_path,
        second,
        expected_dataset_name="api_team_pre_match_v1",
    ) == second_rows
    write_json_atomic(
        tmp_path / "datasets" / "api_team_pre_match_v1.json",
        second,
    )
    loaded = _dataset_rows(tmp_path, "api_team_pre_match_v1")
    assert [row["fixture_id"] for row in loaded] == [2]
    assert {row["dataset_hash"] for row in loaded} == {second["sha256"]}


def test_identical_historical_rows_produce_byte_stable_scientific_manifest(
    tmp_path: Path,
) -> None:
    rows = [_snapshot_row(1), _snapshot_row(2)]
    first = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=rows,
        code_revision="same-revision",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    second = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=rows,
        code_revision="same-revision",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    assert first == second
    assert first["generated_at"] is None
    assert first["generated_at_status"] == (
        "NOT_RECORDED_IN_SCIENTIFIC_IDENTITY"
    )


def test_snapshot_loader_preserves_manifest_row_order_across_partitions(
    tmp_path: Path,
) -> None:
    rows = [
        _snapshot_row(1, season=2025),
        _snapshot_row(2, season=2024),
        _snapshot_row(3, season=2025),
    ]
    manifest = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=rows,
        code_revision="one",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    assert load_dataset_snapshot(
        tmp_path,
        manifest,
        expected_dataset_name="api_team_pre_match_v1",
    ) == rows


def test_dataset_loader_fails_closed_on_partition_or_manifest_tampering(
    tmp_path: Path,
) -> None:
    manifest = write_dataset(
        tmp_path,
        name="api_team_pre_match_v1",
        rows=[_snapshot_row(1)],
        code_revision="one",
        temporal_policy=TEMPORAL_VALIDITY_NOT_PROVEN,
    )
    tampered_manifest = dict(manifest)
    tampered_manifest["sha256"] = "f" * 64
    with pytest.raises(RuntimeError, match="PARTITION_IDENTITY_MISMATCH"):
        load_dataset_snapshot(
            tmp_path,
            tampered_manifest,
            expected_dataset_name="api_team_pre_match_v1",
        )

    partition = manifest["partitions"][0]  # type: ignore[index]
    partition_path = tmp_path / str(partition["path"])
    partition_path.write_bytes(partition_path.read_bytes() + b"tamper")
    with pytest.raises(RuntimeError, match="PARTITION_HASH_MISMATCH"):
        load_dataset_snapshot(
            tmp_path,
            manifest,
            expected_dataset_name="api_team_pre_match_v1",
        )
