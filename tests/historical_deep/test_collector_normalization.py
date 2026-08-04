from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector, make_task_id
from robin.historical_deep.normalization import (
    SUPPORTED_FAMILIES,
    NormalizationError,
    canonical_sha256,
    classify_temporal,
    normalize_family,
    normalize_payload,
)
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository

FIXED_NOW = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)


def _task_id(task: object) -> str:
    if isinstance(task, Mapping):
        return str(task["task_id"])
    return str(getattr(task, "task_id"))


class FakeProvider:
    def __init__(
        self,
        responder: Callable[[str, dict[str, object]], object],
    ) -> None:
        self.responder = responder
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(
        self,
        endpoint: str,
        params: Mapping[str, object] | None = None,
    ) -> object:
        copied = dict(params or {})
        self.calls.append((endpoint, copied))
        return self.responder(endpoint, copied)


class FakeRepository:
    def __init__(self) -> None:
        self.receipts: dict[str, dict[str, object]] = {}
        self.payloads: dict[str, object] = {}
        self.capture_count = 0

    def contains(self, task: object) -> bool:
        return _task_id(task) in self.receipts

    def receipt_for(self, task: object) -> object | None:
        return self.receipts.get(_task_id(task))

    load_receipt = receipt_for

    def payload_for(self, task: object) -> object | None:
        return self.payloads.get(_task_id(task))

    def capture(
        self,
        *,
        task: object,
        payload: object,
        requested_at: datetime,
        received_at: datetime,
        http_status: int | None,
    ) -> dict[str, object]:
        del requested_at, received_at, http_status
        task_id = _task_id(task)
        receipt = {
            "task_id": task_id,
            "payload_key": f"fake/{task_id}.json.gz",
            "payload_sha256": canonical_sha256(payload),
        }
        self.receipts[task_id] = receipt
        self.payloads[task_id] = payload
        self.capture_count += 1
        return receipt


def _clock() -> datetime:
    return FIXED_NOW


class Tick:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.125
        return self.value


def _fixture(
    fixture_id: int,
    *,
    events: list[dict[str, object]] | None = None,
    deep: bool = False,
) -> dict[str, object]:
    record: dict[str, object] = {
        "fixture": {
            "id": fixture_id,
            "date": "2024-08-10T15:00:00+00:00",
            "referee": "Stéphanie Frappart",
            "venue": {"id": 90, "name": "Test Ground", "city": None},
            "status": {"short": None},
        },
        "league": {"id": 39, "season": 2024, "round": "Regular Season - 1"},
        "teams": {
            "home": {"id": 1, "name": "Home"},
            "away": {"id": 2, "name": "Away"},
        },
    }
    if events is not None:
        record["events"] = events
    if deep:
        record.update(
            {
                "lineups": [
                    {
                        "team": {"id": 1, "name": "Home"},
                        "formation": "4-3-3",
                        "startXI": [
                            {
                                "player": {
                                    "id": 11,
                                    "name": "Player Eleven",
                                    "grid": "1:1",
                                }
                            }
                        ],
                        "substitutes": [],
                    }
                ],
                "statistics": [
                    {
                        "team": {"id": 1},
                        "statistics": [{"type": "Shots on Goal", "value": None}],
                    }
                ],
                "players": [
                    {
                        "team": {"id": 1},
                        "players": [
                            {
                                "player": {"id": 11, "name": "Player Eleven"},
                                "statistics": [{"games": {"minutes": None}}],
                            }
                        ],
                    }
                ],
            }
        )
    return record


def _payload(response: list[object], *, current: int = 1, total: int = 1) -> dict[str, object]:
    return {
        "response": response,
        "paging": {"current": current, "total": total},
        "errors": [],
    }


def test_coverage_census_checks_five_leagues_and_advertised_vs_actual() -> None:
    competitions = [
        {"canonical_key": f"api-football:{league}", "provider_league_id": league}
        for league in (61, 39, 140, 78, 135)
    ]

    def responder(endpoint: str, params: dict[str, object]) -> object:
        if endpoint == "/leagues":
            return _payload(
                [
                    {
                        "league": {"id": params["id"]},
                        "seasons": [
                            {
                                "year": params["season"],
                                "coverage": {
                                    "fixtures": {
                                        "events": True,
                                        "lineups": False,
                                        "statistics_fixtures": True,
                                        "statistics_players": True,
                                    },
                                    "standings": True,
                                    "injuries": True,
                                },
                            }
                        ],
                    }
                ]
            )
        if endpoint == "/fixtures":
            fixture_id = (
                int(params["league"])
                if "league" in params
                else int(str(params["ids"]).split("-")[0])
            )
            return _payload([_fixture(fixture_id)])
        if endpoint in {"/players", "/injuries", "/standings"}:
            return _payload([])
        raise AssertionError(f"unexpected census endpoint: {endpoint}")

    provider = FakeProvider(responder)
    result = HistoricalDeepCollector(provider, clock=_clock).coverage_census(
        competitions,
        [2024],
        requested_families=("fixtures", "events", "lineups", "injuries"),
        sample_limit=1,
    )

    assert result["observation_count"] == 5
    assert len(provider.calls) == 30
    for observation in result["observations"]:
        matrix = observation["field_matrix"]
        assert matrix["events"]["advertised_flag"] is True
        assert matrix["events"]["actual_content"] is False
        assert matrix["events"]["state"] == "ADVERTISED_NOT_OBSERVED"
        assert matrix["lineups"]["state"] == "NOT_ADVERTISED_NOT_OBSERVED"


def test_fixture_bundle_pilot_measures_20_10_5_1() -> None:
    def responder(endpoint: str, params: dict[str, object]) -> object:
        assert endpoint == "/fixtures"
        ids = [int(value) for value in str(params["ids"]).split("-")]
        return _payload([_fixture(value, events=[], deep=True) for value in ids])

    provider = FakeProvider(responder)
    result = HistoricalDeepCollector(
        provider,
        clock=_clock,
        monotonic=Tick(),
    ).pilot_fixture_bundles(
        list(range(1, 21)),
        competition=39,
        season=2024,
    )

    assert [item["candidate_size"] for item in result["measurements"]] == [20, 10, 5, 1]
    assert all(item["completeness"] == 1.0 for item in result["measurements"])
    assert all(item["response_size_bytes"] > 0 for item in result["measurements"])
    assert all(item["memory_bytes"] > 0 for item in result["measurements"])
    assert result["recommended_size"] == 20
    assert [len(str(params["ids"]).split("-")) for _, params in provider.calls] == [
        20,
        10,
        5,
        1,
    ]


def test_bundle_fallbacks_are_strictly_targeted_and_receipted() -> None:
    def responder(endpoint: str, params: dict[str, object]) -> object:
        if endpoint == "/fixtures":
            return _payload([_fixture(501)])
        if endpoint == "/fixtures/events":
            return _payload(
                [
                    {
                        "time": {"elapsed": 4},
                        "team": {"id": 1},
                        "player": {"id": 11},
                        "type": "Goal",
                    }
                ]
            )
        if endpoint == "/fixtures/players":
            return _payload(
                [
                    {
                        "team": {"id": 1},
                        "players": [
                            {
                                "player": {"id": 11},
                                "statistics": [{"games": {"minutes": 90}}],
                            }
                        ],
                    }
                ]
            )
        raise AssertionError(f"unexpected provider call: {endpoint} {params}")

    provider = FakeProvider(responder)
    result = HistoricalDeepCollector(provider, clock=_clock).harvest_fixture_bundles(
        [501],
        competition=39,
        season=2024,
        coverage_flags={
            "events": True,
            "lineups": False,
            "team_match_statistics": None,
            "player_match_statistics": True,
        },
    )

    assert [endpoint for endpoint, _ in provider.calls] == [
        "/fixtures",
        "/fixtures/events",
        "/fixtures/players",
    ]
    receipts = {item["missing_family"]: item for item in result["fallback_receipts"]}
    assert set(receipts) == {"events", "lineups", "statistics", "players"}
    assert receipts["events"]["calls"] == 1
    assert receipts["events"]["result"] == "COLLECTED"
    assert receipts["lineups"]["reason"] == "COVERAGE_NOT_ADVERTISED"
    assert receipts["statistics"]["reason"] == "COVERAGE_FLAG_UNKNOWN"
    assert receipts["players"]["calls"] == 1
    for receipt in receipts.values():
        assert {
            "fixture",
            "missing_family",
            "flag",
            "bundle_checked",
            "endpoint",
            "calls",
            "result",
            "hash",
            "reason",
        } <= receipt.keys()
        without_hash = {key: value for key, value in receipt.items() if key != "hash"}
        assert receipt["hash"] == canonical_sha256(without_hash)


def test_player_pagination_and_task_idempotence() -> None:
    def responder(endpoint: str, params: dict[str, object]) -> object:
        assert endpoint == "/players"
        page = int(params["page"])
        return _payload(
            [
                {
                    "player": {
                        "id": page,
                        "name": f"Player {page}",
                        "birth": {"date": None},
                    },
                    "statistics": [
                        {
                            "team": {"id": 10 + page},
                            "league": {"id": 39, "season": 2024},
                            "games": {"appearences": None},
                        }
                    ],
                }
            ],
            current=page,
            total=2,
        )

    provider = FakeProvider(responder)
    store = FakeRepository()
    collector = HistoricalDeepCollector(provider, store, clock=_clock)
    first = collector.harvest_player_pages(39, 2024)
    second = collector.harvest_player_pages(39, 2024)

    assert first["pages_collected"] == 2
    assert first["stop_reason"] == "PAGING_COMPLETE"
    assert len(first["normalized"]["players"]) == 2
    assert len(first["normalized"]["player_season_statistics"]) == 2
    assert len(provider.calls) == 2
    assert store.capture_count == 2
    assert all(call["reused"] is True for call in second["calls"])
    assert first["hash"] != second["hash"]


def test_r2_payload_reuse_replays_without_provider_call() -> None:
    def first_responder(endpoint: str, params: dict[str, object]) -> object:
        assert endpoint == "/players"
        return _payload(
            [
                {
                    "player": {"id": 7, "name": "Stored Player"},
                    "statistics": [
                        {
                            "team": {"id": 1},
                            "league": {"id": 39, "season": 2024},
                        }
                    ],
                }
            ]
        )

    repository = R2FirstRepository(InMemoryObjectStore())
    first_provider = FakeProvider(first_responder)
    first = HistoricalDeepCollector(
        first_provider,
        repository,
        clock=_clock,
    ).harvest_player_pages(39, 2024)

    def forbidden_responder(endpoint: str, params: dict[str, object]) -> object:
        raise AssertionError(f"provider called during R2 replay: {endpoint} {params}")

    replay_provider = FakeProvider(forbidden_responder)
    replayed = HistoricalDeepCollector(
        replay_provider,
        repository,
        clock=_clock,
    ).harvest_player_pages(39, 2024)

    assert len(first_provider.calls) == 1
    assert replay_provider.calls == []
    assert replayed["calls"][0]["reused"] is True
    assert replayed["normalized"] == first["normalized"]


def test_injuries_are_collected_before_bounded_sidelined() -> None:
    def responder(endpoint: str, params: dict[str, object]) -> object:
        if endpoint == "/injuries":
            return _payload(
                [
                    {
                        "player": {"id": player_id},
                        "team": {"id": 1},
                        "league": {"id": 39, "season": 2024},
                        "fixture": {"id": 100 + player_id},
                        "type": "Red Card" if player_id == 2 else "Knee Injury",
                        "reason": None,
                    }
                    for player_id in (3, 1, 2)
                ]
            )
        assert endpoint == "/sidelined"
        return _payload(
            [
                {
                    "player": {"id": params["player"]},
                    "type": "Knee Injury",
                    "start": "2024-08-01",
                    "end": None,
                }
            ]
        )

    provider = FakeProvider(responder)
    result = HistoricalDeepCollector(provider, clock=_clock).harvest_injuries_sidelined(
        39,
        2024,
        max_sidelined_players=2,
    )

    assert [endpoint for endpoint, _ in provider.calls] == [
        "/injuries",
        "/sidelined",
        "/sidelined",
    ]
    assert result["sidelined_players_selected"] == [1, 2]
    assert result["sidelined_players_omitted"] == 1
    assert len(result["normalized"]["injuries"]) == 2
    assert len(result["normalized"]["suspensions"]) == 1
    assert len(result["normalized"]["sidelined"]) == 2


def test_normalization_covers_every_family_preserves_null_and_provenance() -> None:
    fixture_payload = _payload(
        [
            _fixture(
                501,
                events=[
                    {
                        "time": {"elapsed": 4},
                        "team": {"id": 1},
                        "player": {"id": 11},
                        "type": "Goal",
                    }
                ],
                deep=True,
            )
        ]
    )
    player_payload = _payload(
        [
            {
                "player": {
                    "id": 11,
                    "name": "Player Eleven",
                    "birth": {"date": None},
                },
                "statistics": [
                    {
                        "team": {"id": 1},
                        "league": {"id": 39, "season": 2024},
                        "games": {"minutes": None},
                    }
                ],
            }
        ]
    )
    injury_payload = _payload(
        [
            {
                "player": {"id": 12},
                "team": {"id": 1},
                "fixture": {"id": 502},
                "league": {"id": 39, "season": 2024},
                "type": "Knee Injury",
                "reason": None,
            },
            {
                "player": {"id": 11},
                "team": {"id": 1},
                "fixture": {"id": 501},
                "league": {"id": 39, "season": 2024},
                "type": "Red Card",
                "reason": None,
            },
        ]
    )
    payloads: dict[str, tuple[str, object]] = {
        **{
            family: ("/fixtures", fixture_payload)
            for family in (
                "fixtures",
                "teams",
                "venues",
                "referees",
                "events",
                "lineups",
                "lineup_players",
                "formations",
                "team_match_statistics",
                "player_match_statistics",
                "rounds",
            )
        },
        "players": ("/players", player_payload),
        "player_season_statistics": ("/players", player_payload),
        "injuries": ("/injuries", injury_payload),
        "suspensions": ("/injuries", injury_payload),
        "sidelined": (
            "/sidelined",
            _payload(
                [
                    {
                        "player": {"id": 11},
                        "type": "Injury",
                        "start": "2024-08-01",
                        "end": None,
                    }
                ]
            ),
        ),
        "coaches": (
            "/coaches",
            _payload(
                [
                    {
                        "id": 7,
                        "name": "Coach",
                        "birth": {"date": None},
                        "team": {"id": 1},
                    }
                ]
            ),
        ),
        "standings": (
            "/standings",
            _payload(
                [
                    {
                        "league": {
                            "id": 39,
                            "season": 2024,
                            "standings": [[{"rank": 1, "team": {"id": 1}}]],
                        }
                    }
                ]
            ),
        ),
    }

    assert set(payloads) == set(SUPPORTED_FAMILIES)
    normalized: dict[str, list[dict[str, object]]] = {}
    for family, (endpoint, payload) in payloads.items():
        normalized[family] = normalize_family(
            family,
            payload,
            endpoint=endpoint,
            competition_id=39,
            season=2024,
            task_id="task-1",
            observed_at=FIXED_NOW,
            ingested_at=FIXED_NOW,
        )
        assert normalized[family], family
        row = normalized[family][0]
        assert row["provider"] == "api-football"
        assert row["canonical_id"].startswith("api-football:")
        assert row["source_payload_hash"]
        assert row["record_hash"]
        assert row["normalizer_version"] == "historical-deep-normalizer-v2"
        assert row["temporal_gate"] == "BLOCKED_BY_TEMPORALITY"

    fixture_data = normalized["fixtures"][0]["data"]
    assert fixture_data["fixture"]["status"]["short"] is None
    statistic_data = normalized["team_match_statistics"][0]["data"]
    assert statistic_data["value"] is None
    assert (
        normalized["fixtures"][0]
        == normalize_family(
            "fixtures",
            fixture_payload,
            endpoint="/fixtures",
            competition_id=39,
            season=2024,
            task_id="task-1",
            observed_at=FIXED_NOW,
            ingested_at=FIXED_NOW,
        )[0]
    )


def test_null_only_venue_is_preserved_but_not_materialized_as_entity() -> None:
    venue = {"id": None, "name": None, "city": None}
    payload = _payload([{"fixture": {"id": 501, "venue": venue}}])

    normalized = normalize_payload(
        payload,
        endpoint="/fixtures",
        competition_id=39,
        season=2024,
        task_id="task-null-venue",
        observed_at=FIXED_NOW,
        ingested_at=FIXED_NOW,
    )

    assert set(normalized) == {"fixtures"}
    assert normalized["fixtures"][0]["data"]["fixture"]["venue"] == venue


def test_venue_without_provider_id_still_derives_identity_from_real_data() -> None:
    payload = _payload(
        [
            {
                "fixture": {
                    "id": 501,
                    "venue": {"id": None, "name": "Test Ground", "city": None},
                }
            }
        ]
    )

    normalized = normalize_payload(
        payload,
        endpoint="/fixtures",
        competition_id=39,
        season=2024,
        task_id="task-derived-venue",
        observed_at=FIXED_NOW,
        ingested_at=FIXED_NOW,
    )

    assert normalized["venues"][0]["identity_status"] == "DERIVED_NO_PROVIDER_ID"


def test_venue_with_other_real_data_but_no_identity_still_fails_closed() -> None:
    payload = _payload(
        [
            {
                "fixture": {
                    "id": 501,
                    "venue": {
                        "id": None,
                        "name": None,
                        "city": None,
                        "surface": "grass",
                    },
                }
            }
        ]
    )

    with pytest.raises(NormalizationError, match="MISSING_IDENTITY:venue"):
        normalize_payload(
            payload,
            endpoint="/fixtures",
            competition_id=39,
            season=2024,
            task_id="task-invalid-venue",
            observed_at=FIXED_NOW,
            ingested_at=FIXED_NOW,
        )


@pytest.mark.parametrize(
    ("family", "expected"),
    [
        ("fixtures", "FIXTURE_SPECIFIC_POST_HOC"),
        ("events", "EVENT_TIME_USABLE"),
        ("lineups", "POST_LINEUP_RECONSTRUCTED"),
        ("team_match_statistics", "POST_MATCH_ONLY"),
        ("players", "STATIC_PROFILE"),
        ("standings", "SEASON_FINAL_AGGREGATE"),
        ("injuries", "HISTORICAL_INTERVAL_RECONSTRUCTED"),
    ],
)
def test_temporal_classes_are_explicit_and_fail_closed(
    family: str,
    expected: str,
) -> None:
    assert classify_temporal(family).value == expected


def test_only_explicit_prematch_evidence_can_open_strict_gate() -> None:
    payload = _payload([_fixture(501, events=[], deep=True)])
    before_kickoff = datetime(2024, 8, 10, 14, 0, tzinfo=UTC)
    teams = normalize_family(
        "teams",
        payload,
        endpoint="/fixtures",
        competition_id=39,
        season=2024,
        task_id="task-team",
        observed_at=FIXED_NOW,
        ingested_at=FIXED_NOW,
        source_available_at=before_kickoff,
    )
    lineups = normalize_family(
        "lineups",
        payload,
        endpoint="/fixtures",
        competition_id=39,
        season=2024,
        task_id="task-lineup",
        observed_at=FIXED_NOW,
        ingested_at=FIXED_NOW,
        source_available_at=before_kickoff,
    )

    assert teams[0]["temporal_gate"] == "READY_STRICT"
    assert teams[0]["strict_prematch_eligible"] is True
    assert lineups[0]["temporal_gate"] == "BLOCKED_BY_TEMPORALITY"
    assert lineups[0]["strict_prematch_eligible"] is False


def test_task_identity_is_order_independent_and_changes_with_scope() -> None:
    first = make_task_id(
        campaign_id="campaign",
        phase="players",
        competition=39,
        season=2024,
        family="players",
        endpoint="/players",
        params={"season": 2024, "league": 39, "page": 1},
    )
    reordered = make_task_id(
        campaign_id="campaign",
        phase="players",
        competition=39,
        season=2024,
        family="players",
        endpoint="/players",
        params={"page": 1, "league": 39, "season": 2024},
    )
    next_page = make_task_id(
        campaign_id="campaign",
        phase="players",
        competition=39,
        season=2024,
        family="players",
        endpoint="/players",
        params={"page": 2, "league": 39, "season": 2024},
    )

    assert first == reordered
    assert first != next_page
