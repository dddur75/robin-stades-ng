from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from robin.historical.critical_closure import (
    FootballDataFile,
    ObjectStorageAdapter,
    archive_football_data_file,
    build_historical_market_dataset,
    canonical_team_key,
    classify_ucl_phase,
    map_football_data_row,
    market_gates,
    market_paired_validation,
    match_market_fixtures,
    odds_api_historical_dry_run,
    preseason_package_v2,
    proportional_devig,
    storage_readiness,
    strategy_lab_v4,
)
from robin.historical.normalization import normalize_records
from robin.historical.orchestrator import (
    BUSINESS_PRIORITY_ORDER,
    build_backfill_plan,
    business_value_priority,
)


def test_business_priorities_close_gates_and_keep_deferred_tasks() -> None:
    assert business_value_priority(
        competition="Serie A", season=2025, endpoint="fixtures"
    ) == "P0_TEAM_IDENTITY"
    assert business_value_priority(
        competition="Premier League", season=2024, endpoint="fixtures/players"
    ) == "P1_PLAYER_MATCH_STATS"
    assert business_value_priority(
        competition="La Liga", season=2023, endpoint="fixtures/lineups"
    ) == "P1_LINEUPS"
    assert business_value_priority(
        competition="Bundesliga", season=2022, endpoint="fixtures/statistics"
    ) == "P1_TEAM_MATCH_STATS"
    assert business_value_priority(
        competition="Serie A", season=2024, endpoint="coachs"
    ) == "P3_SECONDARY"
    assert business_value_priority(
        competition="Ligue 1", season=2018, endpoint="standings"
    ) == "P4_DEFERRED"


def test_plan_contains_business_priority_and_no_task_is_removed() -> None:
    plan = build_backfill_plan(
        {"Ligue 1": 61, "Serie A": 135, "UEFA Champions League": 2},
        include_secondary=True,
    )
    assert plan
    assert all(task.business_value_priority in BUSINESS_PRIORITY_ORDER for task in plan)
    assert any(task.business_value_priority == "P4_DEFERRED" for task in plan)
    assert any(task.endpoint == "transfers" for task in plan)


def test_fixture_request_context_is_normalized() -> None:
    rows = normalize_records(
        "fixtures/players",
        [{"team": {"id": 1}, "players": []}],
        competition_id=39,
        season=2025,
        ingestion_run_id="run",
        raw_payload_hash="abc",
        request_params={"fixture": 123, "team": 1},
    )
    assert rows[0]["provider_fixture_id"] == 123
    assert rows[0]["provider_team_id"] == 1


@pytest.mark.parametrize(
    ("round_name", "expected"),
    [
        ("1st Qualifying Round", "QUALIFYING"),
        ("Play-offs", "PLAYOFF"),
        ("Group Stage - 1", "GROUP_STAGE"),
        ("League Phase - 3", "LEAGUE_PHASE"),
        ("League Stage - 3", "LEAGUE_PHASE"),
        ("Round of 16", "KNOCKOUT"),
        ("Semi-finals", "KNOCKOUT"),
        ("Final", "FINAL"),
        ("", "UNKNOWN"),
    ],
)
def test_ucl_phase_policy(round_name: str, expected: str) -> None:
    assert classify_ucl_phase(round_name) == expected


def test_archives_csv_with_hash_and_versioned_schema(tmp_path: Path) -> None:
    payload = b"Date,HomeTeam,AwayTeam,B365H\n01/01/25,A,B,2.0\n"
    metadata = archive_football_data_file(
        tmp_path,
        FootballDataFile("Premier League", 2024, "https://example.invalid/E0.csv"),
        payload,
    )
    assert metadata["payload_hash"] == hashlib.sha256(payload).hexdigest()
    assert str(metadata["schema_version"]).startswith("football-data-columns-")
    assert (tmp_path / str(metadata["raw_location"])).read_bytes() == payload


def test_mapping_prefers_closing_and_does_not_invent_missing_totals() -> None:
    mapped = map_football_data_row(
        {
            "Date": "01/02/2024",
            "HomeTeam": "A",
            "AwayTeam": "B",
            "AvgCH": "2.0",
            "AvgCD": "3.0",
            "AvgCA": "4.0",
            "AvgH": "9.0",
        },
        competition="Premier League",
        season=2023,
        payload_hash="hash",
    )
    assert mapped["odds_home"] == 2.0
    assert mapped["price_type"] == "HISTORICAL_CLOSING_MARKET"
    assert mapped["odds_over_25"] is None
    assert mapped["observed_time_status"] == "SOURCE_PRICE_CLASS_ONLY"


def test_mapping_falls_back_to_pre_closing_across_schema_change() -> None:
    mapped = map_football_data_row(
        {
            "Date": "01/02/2021",
            "HomeTeam": "A",
            "AwayTeam": "B",
            "B365H": "2.1",
            "B365D": "3.2",
            "B365A": "3.4",
        },
        competition="Serie A",
        season=2020,
        payload_hash="hash",
    )
    assert mapped["price_type"] == "HISTORICAL_PRE_CLOSING_MARKET"


def test_recent_pinnacle_is_retained_as_degraded_not_aggregated() -> None:
    mapped = map_football_data_row(
        {
            "Date": "24/07/2025",
            "HomeTeam": "A",
            "AwayTeam": "B",
            "PSCH": "2.0",
            "PSCD": "3.0",
            "PSCA": "4.0",
        },
        competition="Premier League",
        season=2025,
        payload_hash="hash",
    )
    assert mapped["quality_status"] == "PINNACLE_RECENT_ODDS_DEGRADED"
    assert mapped["odds_home"] is None


def test_alias_matching_is_canonical_and_score_conflict_is_excluded() -> None:
    fixtures = [
        {
            "fixture_id": 1,
            "competition": "Premier League",
            "season": 2024,
            "match_date": "2025-01-01",
            "kickoff_at": "2025-01-01T15:00:00Z",
            "home_team": "Manchester United",
            "away_team": "Wolverhampton Wanderers",
            "home_team_id": 10,
            "away_team_id": 20,
            "home_goals": 2,
            "away_goals": 0,
        }
    ]
    market = [
        {
            "competition": "Premier League",
            "season": 2024,
            "match_date": "2025-01-01",
            "home_source_name": "Man United",
            "away_source_name": "Wolves",
            "home_goals": 2,
            "away_goals": 0,
        }
    ]
    matched, report = match_market_fixtures(market, fixtures)
    assert canonical_team_key("Manchester United") == canonical_team_key("Man United")
    assert len(matched) == 1
    assert report["ambiguous"] == 0
    conflicting = [{**market[0], "home_goals": 1}]
    rejected, conflict_report = match_market_fixtures(conflicting, fixtures)
    assert rejected == []
    assert conflict_report["conflicting"] == 1


def test_ambiguous_mapping_is_never_used() -> None:
    fixture = {
        "fixture_id": 1,
        "competition": "Serie A",
        "season": 2024,
        "match_date": "2025-01-01",
        "home_team": "Inter",
        "away_team": "Milan",
    }
    market = {
        "competition": "Serie A",
        "season": 2024,
        "match_date": "2025-01-01",
        "home_source_name": "Internazionale",
        "away_source_name": "Milan",
    }
    matched, report = match_market_fixtures([market], [fixture, {**fixture, "fixture_id": 2}])
    assert matched == []
    assert report["ambiguous"] == 1


def test_margin_and_proportional_devig() -> None:
    margin, probabilities = proportional_devig([2.0, 4.0, 4.0])
    assert margin == 0.0
    assert probabilities == [0.5, 0.25, 0.25]
    invalid_margin, invalid = proportional_devig([2.0, None, 4.0])
    assert invalid_margin is None
    assert invalid == [None, None, None]


def test_market_dataset_never_synthesizes_odds() -> None:
    rows = build_historical_market_dataset(
        [
            {
                "fixture_id": 1,
                "odds_home": 2.0,
                "odds_draw": 3.0,
                "odds_away": 4.0,
                "odds_over_25": None,
                "odds_under_25": None,
                "quality_status": "OBSERVED",
            }
        ]
    )
    assert rows[0]["market_margin_1x2"] == pytest.approx(1 / 12)
    assert rows[0]["odds_over_25"] is None
    assert rows[0]["de_vig_over_25"] is None


def test_market_gate_1x2_does_not_depend_on_totals() -> None:
    fixtures = [
        {
            "fixture_id": season,
            "competition": "Premier League",
            "season": season,
        }
        for season in (2020, 2021, 2022)
    ]
    rows = [
        {
            **fixture,
            "odds_home": 2.0,
            "odds_draw": 3.0,
            "odds_away": 4.0,
            "market_margin_1x2": 0.08,
            "odds_over_25": None,
            "odds_under_25": None,
            "mapping_status": "EXACT_CANONICAL_MATCH",
        }
        for fixture in fixtures
    ]
    gate = next(
        item for item in market_gates(rows, fixtures) if item["competition"] == "Premier League"
    )
    assert gate["one_x_two_status"] == "READY"
    assert gate["totals_status"] == "PARTIAL"


def test_odds_api_pilot_is_dry_and_bounded() -> None:
    dry_run = odds_api_historical_dry_run(snapshots=100)
    assert dry_run["estimated_credits"] == 200
    assert dry_run["credits_consumed"] == 0
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        odds_api_historical_dry_run(snapshots=251)


def test_storage_gate_thresholds(tmp_path: Path) -> None:
    optional = storage_readiness(
        tmp_path,
        growth_by_critical_gate=1,
        growth_full_plan=2,
        growth_market=3,
    )
    assert optional["status"] == "OBJECT_STORAGE_OPTIONAL"
    recommended = storage_readiness(
        tmp_path,
        growth_by_critical_gate=1,
        growth_full_plan=750_000_000,
        growth_market=1,
    )
    assert recommended["status"] == "OBJECT_STORAGE_RECOMMENDED"
    required = storage_readiness(
        tmp_path,
        growth_by_critical_gate=1,
        growth_full_plan=899_999_999,
        growth_market=2,
    )
    assert required["status"] == "OBJECT_STORAGE_REQUIRED"
    assert required["p3_p4_allowed"] is False


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise FileNotFoundError(Key)
        return {"Metadata": self.metadata[Key]}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: dict[str, str],
    ) -> dict[str, object]:
        self.objects[Key] = Body
        self.metadata[Key] = Metadata
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        return {"Body": BytesIO(self.objects[Key])}


def test_r2_adapter_upload_replay_double_write_and_no_delete(tmp_path: Path) -> None:
    client = FakeS3()
    adapter = ObjectStorageAdapter(client, "private")
    first = adapter.upload("raw/a", b"payload")
    second = adapter.upload("raw/a", b"payload")
    assert first["uploaded"] is True
    assert second["uploaded"] is False
    assert adapter.download("raw/a") == b"payload"
    (tmp_path / "a").write_bytes(b"x")
    dry_run = adapter.migration_dry_run(tmp_path)
    assert dry_run == {
        "mode": "DRY_RUN",
        "files": 1,
        "bytes": 1,
        "deletions": 0,
        "double_write": True,
    }
    assert not hasattr(adapter, "delete")


def test_strategy_and_package_keep_production_locked() -> None:
    gates: list[dict[str, Any]] = [{"competition": "Ligue 1", "status": "READY"}]
    strategy = strategy_lab_v4(gates)
    package = preseason_package_v2(
        code_revision="abc",
        market_gates_report=gates,
        dataset_hashes=["hash"],
    )
    assert strategy["status"] == "NO_EXTERNAL_VALIDATED_EDGE"
    assert strategy["real_bets"] is False
    assert package["NO_BET_DEFAULT"] is True
    assert package["REAL_BETS"] is False
    assert package["PRODUCTION_LOCKED"] is True


def test_market_validation_without_pairs_is_honest(tmp_path: Path) -> None:
    result = market_paired_validation(tmp_path)
    assert result["paired_predictions"] == 0
    assert result["status"] == "NO_EXTERNAL_VALIDATED_EDGE"
    assert result["real_bets"] is False
