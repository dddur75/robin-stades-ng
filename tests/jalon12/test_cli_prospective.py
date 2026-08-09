from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, event, func, select

from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory.budgets import BudgetExceeded, ProviderKind
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
    ProspectiveFixture,
    canonical_sha256,
)
from robin.prospective_observatory.r2 import ProspectiveR2Repository
from robin.prospective_observatory.temporal import schedule_windows
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import (
    CircuitOpenError,
    ProviderResult,
    QuotaState,
    TransientProviderError,
)
from robin.storage.database import build_engine
from scripts.build_cockpit_snapshot import build_prospective_observatory
from scripts.run_prospective_observatory import (
    CanaryBoundObjectStore,
    DirectoryObjectStore,
    MemoryOperationalState,
    ObservatoryPolicy,
    OddsFixtureIdentityError,
    SQLAlchemyOperationalState,
    _capture_payload_complete,
    _filter_fixtures,
    _fixture_freshness_error,
    _match_odds_records,
    _provider_quota_remaining,
    _renormalize_r2_payload,
    run_capture,
    run_fixture_registry,
    run_gate_report,
    run_next_due_report,
    run_replay_audit,
    run_scheduler,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _fixture_record(
    fixture_id: int,
    kickoff_at: datetime,
    *,
    round_name: str = "Regular Season - 1",
) -> dict[str, object]:
    return {
        "fixture": {
            "id": fixture_id,
            "date": kickoff_at.isoformat(),
            "status": {"short": "NS"},
        },
        "league": {
            "id": 61,
            "name": "Ligue 1",
            "season": 2026,
            "round": round_name,
        },
        "teams": {
            "home": {"id": fixture_id * 2, "name": f"Home {fixture_id}"},
            "away": {"id": fixture_id * 2 + 1, "name": f"Away {fixture_id}"},
        },
    }


def _cache(path: Path, *, now: datetime = NOW) -> Path:
    fixture_id = "api-football:9001"
    value = {
        "current_season": 2026,
        "fixtures": [_fixture_record(9001, now + timedelta(hours=1))],
        "payloads": {
            fixture_id: {
                "FIXTURE": [
                    _fixture_record(9001, now + timedelta(hours=1))
                ],
                "TEAM": [{"home": {"id": 18002}, "away": {"id": 18003}}],
                "EVENT_STATUS": [
                    {
                        "fixture": {
                            "id": 9001,
                            "status": {"short": "NS"},
                        }
                    }
                ],
                "PLAYER_STATUS": [
                    {
                        "team": {"id": 18002},
                        "player": {"id": 7, "type": "Questionable"},
                    }
                ],
                "INJURY": [
                    {
                        "team": {"id": 18002},
                        "player": {
                            "id": 7,
                            "type": "Missing Fixture",
                            "reason": "Test cache",
                        },
                    }
                ],
                "LINEUP": [
                    {
                        "team": {"id": 18002},
                        "formation": "4-3-3",
                        "startXI": [
                            {"player": {"id": player_id}}
                            for player_id in range(1, 12)
                        ],
                    },
                    {
                        "team": {"id": 18003},
                        "formation": "4-4-2",
                        "startXI": [
                            {"player": {"id": player_id}}
                            for player_id in range(12, 23)
                        ],
                    },
                ],
                "FORMATION": [
                    {"team": {"id": 18002}, "formation": "4-3-3"},
                    {"team": {"id": 18003}, "formation": "4-4-2"},
                ],
                "ODDS": [
                    {
                        "id": "odds-9001",
                        "home_team": "Home 9001",
                        "away_team": "Away 9001",
                        "commence_time": (
                            now + timedelta(hours=1)
                        ).isoformat(),
                        "bookmakers": [
                            {
                                "key": "betclic_fr",
                                "markets": [
                                    {
                                        "key": "h2h",
                                        "outcomes": [
                                            {"name": "Home 9001", "price": 2.0},
                                            {"name": "Draw", "price": 3.5},
                                            {"name": "Away 9001", "price": 4.0},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _args(
    command_name: str,
    *,
    output: Path,
    cache: Path | None = None,
    object_store_root: Path | None = None,
    now: datetime = NOW,
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command_name,
        policy=POLICY,
        output=output,
        now=now.isoformat(),
        code_revision="test-revision",
        cache=cache,
        object_store_root=object_store_root,
        estimate=False,
        execute=False,
        estimate_file=None,
        competition="Ligue 1",
        max_attempts=2,
        max_objects=250,
    )


def _migrated_engine(path: Path, monkeypatch: object) -> object:
    database_url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", database_url)  # type: ignore[attr-defined]
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    return build_engine(database_url)


def _five_book_odds_cache(
    path: Path,
    *,
    last_update: datetime,
    h2h_prices: tuple[float, float, float] = (2.0, 3.5, 4.0),
    total_prices: tuple[float, float] = (1.91, 1.91),
) -> Path:
    cache = _cache(path)
    value = json.loads(cache.read_text(encoding="utf-8"))
    event = value["payloads"]["api-football:9001"]["ODDS"][0]
    event["bookmakers"] = [
        {
            "key": bookmaker,
            "last_update": last_update.isoformat(),
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Home 9001", "price": h2h_prices[0]},
                        {"name": "Draw", "price": h2h_prices[1]},
                        {"name": "Away 9001", "price": h2h_prices[2]},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {
                            "name": "Over",
                            "price": total_prices[0],
                            "point": 2.5,
                        },
                        {
                            "name": "Under",
                            "price": total_prices[1],
                            "point": 2.5,
                        },
                    ],
                },
            ],
        }
        for bookmaker in (
            "betclic_fr",
            "netbet_fr",
            "pmu_fr",
            "unibet_fr",
            "winamax_fr",
        )
    ]
    cache.write_text(json.dumps(value), encoding="utf-8")
    return cache


def _run_sql_odds_capture(
    tmp_path: Path,
    monkeypatch: object,
    *,
    cache: Path,
) -> tuple[object, SQLAlchemyOperationalState, dict[str, object], DirectoryObjectStore]:
    output = tmp_path / "reports"
    store = DirectoryObjectStore(tmp_path / "objects")
    repository = ProspectiveR2Repository(store)
    engine = _migrated_engine(tmp_path / "chronos-price.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    report = run_capture(
        _args(
            "capture-odds",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    return engine, state, report, store


class _FakeApiFootball:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.fixture_calls = 0
        self.status_calls = 0

    def get_status(self) -> ProviderResult:
        self.status_calls += 1
        return ProviderResult(
            provider="api-football",
            endpoint="/status",
            availability=DataAvailability.PRESENT,
            records=({"response": {"requests": {"current": 1, "limit_day": 75_000}}},),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            quota=QuotaState(remaining=74_999),
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )

    def get_fixtures(self, **_kwargs: object) -> ProviderResult:
        self.fixture_calls += 1
        availability = (
            DataAvailability.ERROR if self.fail else DataAvailability.PRESENT
        )
        records = (
            ()
            if self.fail
            else (_fixture_record(9001, NOW + timedelta(hours=1)),)
        )
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures",
            availability=availability,
            records=records,
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            raw_payload={"response": list(records)},
            http_status=503 if self.fail else 200,
            requested_at=NOW,
            received_at=NOW,
            message="provider_response_errors" if self.fail else None,
        )


class _FakeOdds:
    def __init__(
        self,
        *,
        include_quota_headers: bool,
        actual_cost: int = 2,
    ) -> None:
        self.include_quota_headers = include_quota_headers
        self.actual_cost = actual_cost
        self.preflight_calls = 0
        self.odds_calls = 0

    def get_competitions(self) -> ProviderResult:
        self.preflight_calls += 1
        return ProviderResult(
            provider="the-odds-api",
            endpoint="/sports",
            availability=DataAvailability.PRESENT,
            records=({"key": "soccer_france_ligue_one"},),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            quota=QuotaState(
                remaining=5_000 if self.include_quota_headers else None
            ),
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )

    def get_odds(self) -> ProviderResult:
        self.odds_calls += 1
        event = {
            "id": "odds-9001",
            "home_team": "Home 9001",
            "away_team": "Away 9001",
            "commence_time": (NOW + timedelta(hours=1)).isoformat(),
            "bookmakers": [],
        }
        return ProviderResult(
            provider="the-odds-api",
            endpoint="/sports/soccer_france_ligue_one/odds",
            availability=DataAvailability.PRESENT,
            records=(event,),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            raw_payload=[event],
            quota=QuotaState(
                remaining=5_000 - self.actual_cost,
                last_cost=self.actual_cost,
            ),
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )


class _CircuitResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.content = json.dumps(payload).encode()

    def json(self) -> object:
        return self.payload


class _CircuitTransport:
    def __init__(self, *, status_first: bool) -> None:
        self.status_first = status_first
        self.calls = 0

    def get(self, *_args: Any, **_kwargs: Any) -> _CircuitResponse:
        self.calls += 1
        if self.status_first and self.calls == 1:
            return _CircuitResponse(
                {
                    "response": [
                        {
                            "requests": {
                                "current": 1,
                                "limit_day": 75_000,
                            }
                        }
                    ]
                },
                status_code=200,
                headers={"x-ratelimit-requests-remaining": "74999"},
            )
        return _CircuitResponse({}, status_code=503)


def _execute_capture(
    command_name: str,
    *,
    output: Path,
    state: MemoryOperationalState | SQLAlchemyOperationalState,
    repository: ProspectiveR2Repository,
    provider: object,
) -> dict[str, object]:
    estimate_args = _args(command_name, output=output)
    estimate_args.estimate = True
    run_capture(estimate_args, state=state, repository=repository)
    execute_args = _args(command_name, output=output)
    execute_args.execute = True
    execute_args.estimate_file = (
        output
        / {
            "capture-general": "general-capture-estimate.json",
            "capture-player": "player-capture-estimate.json",
            "capture-lineup": "lineup-capture-estimate.json",
            "capture-odds": "odds-capture-estimate.json",
        }[command_name]
    )
    return run_capture(
        execute_args,
        state=state,
        repository=repository,
        provider=provider,  # type: ignore[arg-type]
    )


def test_quota_parser_reads_nested_real_api_football_shape() -> None:
    result = ProviderResult(
        provider="api-football",
        endpoint="/status",
        availability=DataAvailability.PRESENT,
        records=(
            {
                "response": {
                    "requests": {
                        "current": 123,
                        "limit_day": 75_000,
                    }
                }
            },
        ),
        observed_at=NOW,
        origin=DataOrigin.LIVE_SOURCE,
    )
    assert _provider_quota_remaining(result) == 74_877


def test_http_circuit_preflight_is_typed_and_never_reaches_transport() -> None:
    transport = _CircuitTransport(status_first=False)
    provider = ApiFootballProvider(
        api_key="test-key",
        transport=transport,
        max_retries=0,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=600,
    )
    for _ in range(3):
        with pytest.raises(TransientProviderError):
            provider.get_fixtures(fixture_id=9001)
    assert transport.calls == 3

    with pytest.raises(CircuitOpenError, match="circuit_open"):
        provider.assert_transport_available()
    assert transport.calls == 3


def test_nonempty_malformed_payload_cannot_complete_a_window(
    tmp_path: Path,
) -> None:
    cache_path = _cache(tmp_path / "cache.json")
    cache_value = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_value["payloads"]["api-football:9001"]["LINEUP"] = [
        {
            "team": {"id": 18002},
            "startXI": [
                {"player": {"id": player_id}} for player_id in range(1, 12)
            ],
        }
    ]
    cache_value["payloads"]["api-football:9001"]["FORMATION"] = [
        {"team": {"id": 18002}, "formation": "BANANA"},
        {"team": {"id": 18003}, "formation": "4-4-2"},
    ]
    cache_path.write_text(json.dumps(cache_value), encoding="utf-8")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache_path,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    fixture = state.fixtures()[0]
    malformed = cache_value["payloads"]["api-football:9001"]["LINEUP"]
    assert not _capture_payload_complete(
        family=CaptureFamily.LINEUP,
        payload=malformed,
        fixture=fixture,
    )
    report = run_capture(
        _args(
            "capture-lineup",
            output=output,
            cache=cache_path,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    assert report["invalid_payloads"] > 0
    assert all(
        attempt.status is AvailabilityStatus.INVALID_PAYLOAD
        for attempt in state.attempts()
        if attempt.family is CaptureFamily.LINEUP
    )
    assert all(
        projection["family"] != CaptureFamily.LINEUP.value
        and projection["family"] != CaptureFamily.FORMATION.value
        for _, projection in state.sink.rows.values()
    )


def test_fixture_filter_keeps_three_chronologically_nearest_rounds() -> None:
    policy = ObservatoryPolicy.load(POLICY)
    records = [
        _fixture_record(100 + index, NOW + timedelta(days=day), round_name=round_name)
        for index, (day, round_name) in enumerate(
            (
                (20, "Round Z"),
                (1, "Round C"),
                (8, "Round B"),
                (3, "Round A"),
                (15, "Round D"),
            )
        )
    ]
    selected = _filter_fixtures(
        records,
        policy=policy,
        competition="Ligue 1",
        now=NOW,
        code_revision="test",
        expected_season=2026,
    )
    assert {fixture.phase for fixture, _ in selected} == {
        "Round C",
        "Round A",
        "Round B",
    }


def test_odds_fixture_matching_is_exact_and_fails_closed() -> None:
    identities = {
        "api-football:9001": (
            "Home 9001",
            "Away 9001",
            NOW + timedelta(hours=1),
        )
    }
    exact = {
        "id": "exact",
        "home_team": "Home 9001",
        "away_team": "Away 9001",
        "commence_time": (NOW + timedelta(hours=1)).isoformat(),
    }
    assert _match_odds_records(
        [exact],
        fixture_id="api-football:9001",
        identities=identities,
    ) == [exact]

    with pytest.raises(
        OddsFixtureIdentityError,
        match="ODDS_FIXTURE_MATCH_MISSING",
    ):
        _match_odds_records(
            [{**exact, "away_team": "Another team"}],
            fixture_id="api-football:9001",
            identities=identities,
        )

    with pytest.raises(
        OddsFixtureIdentityError,
        match="ODDS_FIXTURE_MATCH_AMBIGUOUS",
    ):
        _match_odds_records(
            [exact, {**exact, "id": "duplicate"}],
            fixture_id="api-football:9001",
            identities=identities,
        )


def test_odds_capture_requires_fresh_quota_headers_and_charges_actual_cost(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    engine = _migrated_engine(tmp_path / "odds.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    missing_headers = _FakeOdds(include_quota_headers=False)
    with pytest.raises(
        RuntimeError,
        match="ODDS_API_FRESH_QUOTA_PREFLIGHT_FAILED",
    ):
        _execute_capture(
            "capture-odds",
            output=output,
            state=state,
            repository=repository,
            provider=missing_headers,
        )
    assert missing_headers.preflight_calls == 1
    assert missing_headers.odds_calls == 0

    provider = _FakeOdds(include_quota_headers=True)
    report = _execute_capture(
        "capture-odds",
        output=output,
        state=state,
        repository=repository,
        provider=provider,
    )
    assert provider.preflight_calls == 1
    assert provider.odds_calls == 1
    assert report["provider_calls"] == 2
    assert report["odds_api_credits"] == 2
    assert state.budget_used(ProviderKind.ODDS_API) == 2
    engine.dispose()  # type: ignore[attr-defined]
    restarted_engine = build_engine(
        f"sqlite:///{(tmp_path / 'odds.db').as_posix()}"
    )
    restarted = SQLAlchemyOperationalState(restarted_engine)
    assert restarted.budget_used(ProviderKind.ODDS_API) == 2


def test_odds_capture_fails_closed_if_actual_cost_breaks_signed_estimate(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    provider = _FakeOdds(
        include_quota_headers=True,
        actual_cost=3,
    )
    with pytest.raises(
        RuntimeError,
        match="ODDS_ACTUAL_COST_CONTRACT_MISMATCH",
    ):
        _execute_capture(
            "capture-odds",
            output=output,
            state=state,
            repository=repository,
            provider=provider,
        )
    assert provider.odds_calls == 1
    assert state.budget_used(ProviderKind.ODDS_API) == 3
    assert not any(
        receipt.quality_status is AvailabilityStatus.CAPTURED
        for receipt in state.receipts()
        if receipt.family is CaptureFamily.ODDS
    )


def test_odds_internal_reserve_blocks_cost_drift_at_cap_boundary(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    state.append_budget(
        idempotency_key="existing-odds-cost",
        provider=ProviderKind.ODDS_API,
        units=248,
        provider_remaining=5_000,
        provider_reserve=4_000,
        recorded_at=NOW,
        reason="PREVIOUS_VERIFIED_CAPTURE",
        code_revision="test-revision",
    )
    provider = _FakeOdds(
        include_quota_headers=True,
        actual_cost=3,
    )
    with pytest.raises(
        BudgetExceeded,
        match="PROSPECTIVE_ADAPTIVE_BUDGET_BLOCKED.*BLOCKED_DAILY_BUDGET",
    ):
        _execute_capture(
            "capture-odds",
            output=output,
            state=state,
            repository=repository,
            provider=provider,
        )
    assert provider.preflight_calls == 0
    assert provider.odds_calls == 0
    assert state.budget_used(ProviderKind.ODDS_API) == 248


def test_cache_capture_replay_and_second_operation_are_zero_cost(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()

    registry = run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    first = run_capture(
        _args(
            "capture-player",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    second = run_capture(
        _args(
            "capture-player",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    replay = run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )

    assert registry["provider_calls"] == 0
    assert first["provider_calls"] == 0
    assert second["status"] == "CANARY_NOT_DUE_SCHEDULER_READY"
    assert second["provider_calls"] == 0
    assert second["odds_api_credits"] == 0
    assert replay["second_pass_inserts"] == 0
    assert replay["provider_calls"] == 0
    assert replay["odds_api_credits"] == 0
    serialized = json.dumps(replay)
    assert "secret" not in serialized.casefold()
    assert replay["deletions"] == 0
    registry_capture = next(
        capture
        for capture in repository.iter_captures()
        if capture.receipt.window_id is None
    )
    assert isinstance(registry_capture.payload, dict)
    mutated_normalized = {
        **registry_capture.payload,
        "normalized_family_records": [{"fixture": {"id": "tampered"}}],
    }
    with pytest.raises(RuntimeError, match="R2_RAW_NORMALIZATION_MISMATCH"):
        _renormalize_r2_payload(
            registry_capture.receipt,
            mutated_normalized,
        )
    mutated_raw = {
        **registry_capture.payload,
        "raw_provider_payload": {"fixture": {"id": "tampered"}},
    }
    with pytest.raises(RuntimeError, match="R2_RAW_NORMALIZATION_MISMATCH"):
        _renormalize_r2_payload(registry_capture.receipt, mutated_raw)


def test_gate_report_cockpit_preserves_full_replay_and_fixture_previews(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    report_now = NOW
    cache = _cache(tmp_path / "cache.json", now=report_now)
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
            now=report_now,
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output, now=report_now), state=state)
    replay = run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
            now=report_now,
        ),
        state=state,
        repository=repository,
    )
    gate_report = run_gate_report(
        _args("gate-report", output=output, now=report_now),
        state=state,
    )
    gate_observatory = gate_report["observatory"]
    assert gate_observatory["fixtures"]["next"]
    assert gate_observatory["windows"]["next"]
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(output))  # type: ignore[attr-defined]
    cockpit = build_prospective_observatory()
    assert replay["status"] == "R2_REPLAY_VERIFIED"
    assert cockpit["r2"]["replay_status"] == "R2_REPLAY_VERIFIED"
    assert (
        cockpit["postgresql"]["reconstruction_status"]
        == "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2"
    )
    assert cockpit["postgresql"]["duplicates_avoided"] > 0
    assert cockpit["fixtures"]["next"]
    assert cockpit["windows"]["next"]


def test_next_due_report_is_provider_free_and_covers_all_families(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    cache_value = json.loads(cache.read_text(encoding="utf-8"))
    far_kickoff = NOW + timedelta(days=22)
    cache_value["fixtures"][0]["fixture"]["date"] = far_kickoff.isoformat()
    cache.write_text(json.dumps(cache_value), encoding="utf-8")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    args = _args("next-due-report", output=output)
    args.report_path = tmp_path / "next-due-windows.json"

    report = run_next_due_report(args, state=state)

    entries = report["entries"]
    assert isinstance(entries, list)
    assert len(entries) == len(CaptureFamily) == 9
    assert {entry["family"] for entry in entries} == {
        family.value for family in CaptureFamily
    }
    assert all(entry["workflow"] for entry in entries)
    assert all(entry["max_cost"] for entry in entries)
    assert report["active_windows"] == 49
    assert report["provider_calls"] == 0
    assert report["odds_api_credits"] == 0
    assert report["capture_attempts"] == 0
    assert args.report_path.exists()


def test_fixture_freshness_rejects_kickoff_and_lifecycle_changes(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    state = MemoryOperationalState()
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=tmp_path / "reports",
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    fixture = state.fixtures()[0]
    valid_record = _fixture_record(9001, fixture.kickoff_at)

    def freshness(record: dict[str, object]) -> ProviderResult:
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures",
            availability=DataAvailability.PRESENT,
            records=(record,),
            observed_at=NOW,
            origin=DataOrigin.LIVE_SOURCE,
            http_status=200,
            requested_at=NOW,
            received_at=NOW,
        )

    assert _fixture_freshness_error(
        freshness(valid_record),
        fixture,
    ) is None
    stale_records: list[dict[str, object]] = []
    for kickoff_delta in (-timedelta(minutes=30), timedelta(minutes=30)):
        stale_records.append(
            _fixture_record(9001, fixture.kickoff_at + kickoff_delta)
        )
    for lifecycle_status in (
        "PST",
        "CANC",
        "TBD",
        "ABD",
        "1H",
        "HT",
        "2H",
        "ET",
        "FT",
    ):
        record = _fixture_record(9001, fixture.kickoff_at)
        record["fixture"]["status"]["short"] = lifecycle_status  # type: ignore[index]
        stale_records.append(record)
    changed_team = _fixture_record(9001, fixture.kickoff_at)
    changed_team["teams"]["home"]["id"] = 999_999  # type: ignore[index]
    stale_records.append(changed_team)

    assert all(
        _fixture_freshness_error(freshness(record), fixture)
        == "REGISTRY_STALE"
        for record in stale_records
    )


def test_replay_is_complete_beyond_the_legacy_250_object_bound(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    fixture = state.fixtures()[0]
    for index in range(130):
        normalized = [
            {
                "team": {"id": fixture.home_team_id},
                "player": {
                    "id": f"player-{index}",
                    "status": "AVAILABLE",
                },
            }
        ]
        repository.capture(
            payload={
                "raw_payload_kind": "CANONICAL_PROVIDER_RECORDS",
                "raw_provider_payload": normalized,
                "normalized_family_records": normalized,
            },
            context=CaptureContext(
                window_id=f"replay-window-{index}",
                window_label=f"REPLAY-{index}",
                fixture_id=fixture.fixture_id,
                competition=fixture.competition,
                season=fixture.season,
                provider="api-football",
                family=CaptureFamily.PLAYER_STATUS,
                requested_at=NOW,
                response_received_at=NOW,
                observed_at=NOW,
                kickoff_at=fixture.kickoff_at,
                cutoff_at=fixture.kickoff_at - timedelta(minutes=1),
                http_status=200,
                source_endpoint="/injuries",
                complete=True,
                quality_status=AvailabilityStatus.CAPTURED,
                provider_calls=0,
                code_revision="test-revision",
                materialized_at=NOW,
            ),
        )

    replay = run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    assert replay["complete_replay"] is True
    assert replay["selection_truncated"] is False
    assert replay["objects_examined"] == 393
    assert replay["physical_recovery_objects"] == 131
    assert replay["physical_recovery_bytes"] > 0
    assert replay["payloads_replayed"] == 131
    assert replay["second_pass_inserts"] == 0


def test_sqlite_restart_and_r2_reconstruction_are_idempotent(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    engine = _migrated_engine(tmp_path / "primary.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    capture_window_inserts: list[bool] = []

    def record_capture_window_insert(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO CAPTURE_WINDOWS"):
            capture_window_inserts.append(executemany)

    event.listen(
        engine,
        "before_cursor_execute",
        record_capture_window_insert,
    )
    first_schedule = run_scheduler(
        _args("scheduler", output=output),
        state=state,
    )
    event.remove(
        engine,
        "before_cursor_execute",
        record_capture_window_insert,
    )
    assert first_schedule["windows_inserted"] > 1
    assert capture_window_inserts == [True]
    for capture_command in (
        "capture-general",
        "capture-player",
        "capture-lineup",
        "capture-odds",
    ):
        run_capture(
            _args(
                capture_command,
                output=output,
                cache=cache,
                object_store_root=tmp_path / "objects",
            ),
            state=state,
            repository=repository,
        )
    temporal_gate_inserts: list[bool] = []

    def record_temporal_gate_insert(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(
            "INSERT INTO TEMPORAL_DATA_GATES"
        ):
            temporal_gate_inserts.append(executemany)

    event.listen(
        engine,
        "before_cursor_execute",
        record_temporal_gate_insert,
    )
    first_gates = run_gate_report(
        _args("gate-report", output=output),
        state=state,
    )
    event.remove(
        engine,
        "before_cursor_execute",
        record_temporal_gate_insert,
    )
    repeated_gates = run_gate_report(
        _args("gate-report", output=output),
        state=state,
    )
    assert first_gates["gate_rows_inserted"] > 1
    assert temporal_gate_inserts == [True]
    assert repeated_gates["gate_rows_inserted"] == 0
    assert repeated_gates["gate_duplicates_avoided"] == first_gates[
        "gate_evaluations"
    ]
    engine.dispose()  # type: ignore[attr-defined]

    restarted_engine = build_engine(
        f"sqlite:///{(tmp_path / 'primary.db').as_posix()}"
    )
    restarted = SQLAlchemyOperationalState(restarted_engine)
    second_schedule = run_scheduler(
        _args("scheduler", output=output),
        state=restarted,
    )
    assert second_schedule["windows_inserted"] == 0
    assert second_schedule["duplicates_avoided"] > 0

    rebuilt_engine = _migrated_engine(tmp_path / "rebuilt.db", monkeypatch)
    rebuilt = SQLAlchemyOperationalState(rebuilt_engine)  # type: ignore[arg-type]
    first_replay = run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
        ),
        state=rebuilt,
        repository=repository,
    )
    second_replay = run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
        ),
        state=rebuilt,
        repository=repository,
    )
    assert first_replay["status"] == "R2_REPLAY_VERIFIED"
    assert first_replay["replay_scope"] == (
        "SCIENTIFIC_CAPTURE_PROJECTIONS_AND_PROVIDER_BUDGETS"
    )
    assert first_replay["control_plane_reconstruction"] == (
        "PRESERVED_NOT_REPLAYED_AUTHORITY_IS_NOT_RECONSTRUCTED"
    )
    assert second_replay["observatory"]["postgresql"]["inserts"] == 0
    assert second_replay["observatory"]["postgresql"]["duplicates_avoided"] > 0
    assert second_replay["observatory"]["postgresql"]["payload_body_rows"] == 0
    assert second_replay["observatory"]["postgresql"]["tables"] == 25
    with rebuilt_engine.connect() as connection:  # type: ignore[attr-defined]
        for table_name in (
            "prospective_fixtures",
            "capture_windows",
            "prospective_injuries",
            "prospective_lineups",
            "prospective_formations",
        ):
            table = Table(table_name, MetaData(), autoload_with=rebuilt_engine)
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() > 0
        odds = Table(
            "prospective_odds_snapshots",
            MetaData(),
            autoload_with=rebuilt_engine,
        )
        assert connection.execute(select(func.count()).select_from(odds)).scalar_one() == 0


def test_provider_error_then_success_uses_durable_attempt_number(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    engine = _migrated_engine(tmp_path / "retry.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    failed_provider = _FakeApiFootball(fail=True)
    first = _execute_capture(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
        provider=failed_provider,
    )
    assert first["provider_errors"] > 0
    assert {attempt.attempt_number for attempt in state.attempts()} == {1}
    engine.dispose()  # type: ignore[attr-defined]

    restarted_engine = build_engine(
        f"sqlite:///{(tmp_path / 'retry.db').as_posix()}"
    )
    restarted = SQLAlchemyOperationalState(restarted_engine)
    successful_provider = _FakeApiFootball(fail=False)
    second = _execute_capture(
        "capture-general",
        output=output,
        state=restarted,
        repository=repository,
        provider=successful_provider,
    )
    assert second["captured"] > 0
    assert second["retries"] > 0
    assert {attempt.attempt_number for attempt in restarted.attempts()} == {1, 2}
    run_replay_audit(
        _args(
            "replay-audit",
            output=output,
            object_store_root=tmp_path / "objects",
        ),
        state=restarted,
        repository=repository,
    )
    gates = run_gate_report(
        _args("gate-report", output=output),
        state=restarted,
    )
    observatory = gates["observatory"]
    assert observatory["captures"]["attempted"] > 0
    assert observatory["captures"]["captured"] > 0
    assert observatory["providers"]["api_football_calls"] == 4
    assert observatory["providers"]["retries"] > 0
    assert observatory["r2"]["objects_added"] > 0
    assert observatory["ledger"]["events"] > 0
    assert gates["ledger_events"] > 0
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "scripts.build_cockpit_snapshot._utc_now",
        lambda: NOW,
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(output))  # type: ignore[attr-defined]
    cockpit = build_prospective_observatory()
    # The fixture registry was intentionally seeded from a cache in this
    # SQLite recovery test. Mixed cache/live evidence must never be labelled
    # as a fully live prospective dataset.
    assert cockpit["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"
    assert gates["capture_provenance"]["cache_test_receipts"] == 1
    assert cockpit["captures"]["attempted"] > 0
    assert cockpit["providers"]["api_football_calls"] == 4
    assert cockpit["ledger"]["events"] > 0


def test_exhausted_windows_make_no_third_provider_call(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    engine = _migrated_engine(tmp_path / "exhausted.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    for expected_attempt in (1, 2):
        provider = _FakeApiFootball(fail=True)
        report = _execute_capture(
            "capture-general",
            output=output,
            state=state,
            repository=repository,
            provider=provider,
        )
        assert provider.fixture_calls == 1
        assert max(
            attempt.attempt_number for attempt in state.attempts()
        ) == expected_attempt
        assert report["provider_errors"] > 0

    unused_provider = _FakeApiFootball(fail=True)
    third = _execute_capture(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
        provider=unused_provider,
    )
    assert third["status"] == "CANARY_NOT_DUE_SCHEDULER_READY"
    assert unused_provider.status_calls == 0
    assert unused_provider.fixture_calls == 0


def test_canary_one_fixture_per_league_bounds_failures_before_circuit(
    tmp_path: Path,
) -> None:
    fixtures = [
        _fixture_record(
            fixture_id,
            NOW + timedelta(hours=1),
        )
        for fixture_id in range(9001, 9007)
    ]
    cache = tmp_path / "fixtures.json"
    cache.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": fixtures,
                "payloads": {},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)

    transport = _CircuitTransport(status_first=True)
    provider = ApiFootballProvider(
        api_key="test-key",
        transport=transport,
        max_retries=0,
        circuit_failure_threshold=3,
        circuit_cooldown_seconds=600,
    )
    report = _execute_capture(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
        provider=provider,
    )

    assert report["status"] == "CAPTURE_PARTIAL_PROVIDER_UNAVAILABLE"
    assert report["circuit_open"] is False
    assert report["selected_fixture_ids"] == ["api-football:9001"]
    assert transport.calls == 2
    assert report["provider_calls"] == 2
    assert state.budget_used(ProviderKind.API_FOOTBALL) == 2
    assert report["provider_errors"] == 1


def test_durable_canary_usage_is_cumulative_across_restart(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    engine = _migrated_engine(tmp_path / "canary-usage.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    policy = json.loads(
        (ROOT / "configs/operations/robin-chronos-canary-v1.json").read_text(
            encoding="utf-8"
        )
    )
    policy_hash = canonical_sha256(policy)
    mission_id = state.ensure_chronos_canary_mission(
        policy=policy,
        policy_hash=policy_hash,
        code_revision="canary-test",
    )
    state.activate_canary_guard(
        canary_run_id=mission_id,
        policy=policy,
        recorded_at=NOW,
        code_revision="canary-test",
    )
    for index in range(20):
        operation_key = f"odds-credit-{index}"
        assert state.record_canary_usage(
            resource_kind="ODDS_CREDIT",
            operation_key=operation_key,
            units=1,
            actual=False,
        )
        assert state.record_canary_usage(
            resource_kind="ODDS_CREDIT",
            operation_key=operation_key,
            units=1,
            actual=True,
        )
    engine.dispose()  # type: ignore[union-attr]

    restarted_engine = build_engine(
        f"sqlite:///{(tmp_path / 'canary-usage.db').as_posix()}"
    )
    restarted = SQLAlchemyOperationalState(restarted_engine)
    restarted_mission_id = restarted.ensure_chronos_canary_mission(
        policy=policy,
        policy_hash=policy_hash,
        code_revision="canary-test",
    )
    assert restarted_mission_id == mission_id
    restarted.activate_canary_guard(
        canary_run_id=restarted_mission_id,
        policy=policy,
        recorded_at=NOW + timedelta(minutes=1),
        code_revision="canary-test",
    )
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_CANARY_CUMULATIVE_ODDS_CREDIT_LIMIT",
    ):
        restarted.record_canary_usage(
            resource_kind="ODDS_CREDIT",
            operation_key="odds-credit-overflow",
            units=1,
            actual=False,
        )
    assert restarted.canary_usage_totals()["ODDS_CREDIT"] == {
        "reserved": 20,
        "actual": 20,
    }
    canaries = restarted.tables["chronos_canary_runs"]
    with restarted_engine.connect() as connection:
        rows = list(connection.execute(select(canaries)).mappings())
    assert len(rows) == 1
    assert rows[0]["planned_at"].replace(tzinfo=UTC) == datetime(
        2026, 8, 9, tzinfo=UTC
    )


def test_durable_canary_cohort_is_global_across_invocations(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    competitions = (
        (9001, 61, "Ligue 1"),
        (9002, 39, "Premier League"),
        (9003, 140, "Liga"),
        (9004, 78, "Bundesliga"),
        (9005, 135, "Serie A"),
        (9006, 61, "Ligue 1"),
    )
    fixture_map = {}
    windows_by_fixture = {}
    for fixture_id, league_id, league_name in competitions:
        fixture = ProspectiveFixture(
            fixture_id=f"api-football:{fixture_id}",
            competition=league_name,
            season="2026",
            phase="Regular Season - 1",
            home_team_id=str(fixture_id * 2),
            away_team_id=str(fixture_id * 2 + 1),
            kickoff_at=NOW + timedelta(hours=2),
            provider="api-football",
            provider_fixture_id=str(fixture_id),
            registered_at=NOW,
            code_revision="canary-test",
        )
        fixture_map[fixture.fixture_id] = fixture
        windows_by_fixture[fixture.fixture_id] = schedule_windows(
            fixture,
            CaptureFamily.ODDS,
            scheduled_at=NOW,
        )
    engine = _migrated_engine(tmp_path / "cohort.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    policy = json.loads(
        (ROOT / "configs/operations/robin-chronos-canary-v1.json").read_text(
            encoding="utf-8"
        )
    )
    policy_hash = canonical_sha256(policy)
    mission_id = state.ensure_chronos_canary_mission(
        policy=policy,
        policy_hash=policy_hash,
        code_revision="canary-test",
    )
    state.activate_canary_guard(
        canary_run_id=mission_id,
        policy=policy,
        recorded_at=NOW,
        code_revision="canary-test",
    )
    first_ids = {f"api-football:{fixture_id}" for fixture_id in range(9001, 9005)}
    second_ids = {"api-football:9005", "api-football:9006"}
    first_windows = tuple(
        window
        for fixture_id in first_ids
        for window in windows_by_fixture[fixture_id]
    )
    assert len(
        state.reserve_chronos_canary_cohort(
            canary_run_id=mission_id,
            windows=first_windows,
            fixtures=fixture_map,
            maximum=5,
            selected_at=NOW,
            code_revision="canary-test",
        )
    ) == 4

    restarted = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    assert restarted.ensure_chronos_canary_mission(
        policy=policy,
        policy_hash=policy_hash,
        code_revision="canary-test",
    ) == mission_id
    restarted.activate_canary_guard(
        canary_run_id=mission_id,
        policy=policy,
        recorded_at=NOW + timedelta(minutes=1),
        code_revision="canary-test",
    )
    selected_second = restarted.reserve_chronos_canary_cohort(
        canary_run_id=mission_id,
        windows=tuple(
            window
            for fixture_id in second_ids
            for window in windows_by_fixture[fixture_id]
        ),
        fixtures=fixture_map,
        maximum=5,
        selected_at=NOW + timedelta(minutes=1),
        code_revision="canary-test",
    )
    assert selected_second == ("api-football:9005",)
    cohort = restarted.tables["chronos_canary_cohort_fixtures"]
    with engine.connect() as connection:  # type: ignore[union-attr]
        rows = list(connection.execute(select(cohort)).mappings())
    assert len(rows) == 5
    assert len({row["competition"] for row in rows}) == 5
    assert "api-football:9006" not in {row["fixture_id"] for row in rows}


def test_canary_counts_actual_sql_and_r2_writes_before_overflow(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    engine = _migrated_engine(tmp_path / "canary-actual.db", monkeypatch)
    state = SQLAlchemyOperationalState(engine)  # type: ignore[arg-type]
    policy = json.loads(
        (ROOT / "configs/operations/robin-chronos-canary-v1.json").read_text(
            encoding="utf-8"
        )
    )
    policy.update(
        {
            "mission_id": "CANARY_ACTUAL_WRITE_TEST",
            "postgresql_rows_max": 2,
            "r2_object_writes_max": 1,
        }
    )
    mission_id = state.ensure_chronos_canary_mission(
        policy=policy,
        policy_hash=canonical_sha256(policy),
        code_revision="canary-test",
    )
    state.activate_canary_guard(
        canary_run_id=mission_id,
        policy=policy,
        recorded_at=NOW,
        code_revision="canary-test",
    )

    def dq_values(event_hash: str) -> dict[str, object]:
        return {
            "id": event_hash[:8] + "-0000-0000-0000-000000000000",
            "event_id": event_hash,
            "fixture_id": "fixture-canary",
            "cutoff_id": "NEAR_KICKOFF",
            "source": "the-odds-api",
            "family": "ODDS",
            "event_code": "NO_PRICE",
            "severity": "WARN",
            "subject_type": "MARKET",
            "subject_id": "fixture-canary:market",
            "detected_at": NOW,
            "evidence_hash": "e" * 64,
            "receipt_id": None,
            "intent_id": None,
            "summary": "canary accounting test",
            "code_revision": "canary-test",
            "append_only": True,
        }

    first_event = "a" * 64
    assert state._insert_exact(  # noqa: SLF001 - direct guard contract test
        "data_quality_events",
        key_values={"event_id": first_event},
        values=dq_values(first_event),
    )
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_CANARY_CUMULATIVE_POSTGRES_ROW_LIMIT",
    ):
        second_event = "b" * 64
        state._insert_exact(  # noqa: SLF001 - direct guard contract test
            "data_quality_events",
            key_values={"event_id": second_event},
            values=dq_values(second_event),
        )

    store = CanaryBoundObjectStore(
        DirectoryObjectStore(tmp_path / "canary-objects"),
        state,
    )
    assert store.put_if_absent("known-at/test/one.json", b"one")
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_CANARY_CUMULATIVE_R2_OBJECT_LIMIT",
    ):
        store.put_if_absent("known-at/test/two.json", b"two")
    assert state.canary_usage_totals() == {
        "POSTGRES_ROW": {"reserved": 2, "actual": 2},
        "R2_OBJECT": {"reserved": 1, "actual": 1},
    }


def test_five_book_price_consensus_and_chronos_artifacts_are_materialized(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _five_book_odds_cache(
        tmp_path / "cache.json",
        last_update=NOW - timedelta(seconds=30),
    )
    engine, state, report, store = _run_sql_odds_capture(
        tmp_path,
        monkeypatch,
        cache=cache,
    )
    with engine.connect() as connection:  # type: ignore[union-attr]
        price_count = connection.execute(
            select(func.count()).select_from(state.tables["price_snapshot_metadata"])
        ).scalar_one()
        derivation_count = connection.execute(
            select(func.count()).select_from(
                state.tables["price_derivation_metadata"]
            )
        ).scalar_one()
        aggregate_rows = list(
            connection.execute(
                select(state.tables["market_snapshot_metadata"])
            ).mappings()
        )
        dq_count = connection.execute(
            select(func.count()).select_from(state.tables["data_quality_events"])
        ).scalar_one()
        canary_links = connection.execute(
            select(func.count()).select_from(
                state.tables["chronos_canary_run_windows"]
            )
        ).scalar_one()
    assert report["captured"] >= 1
    assert price_count >= 25
    assert derivation_count >= 25
    assert {row["market"] for row in aggregate_rows} == {
        "MATCH_RESULT_90M",
        "TOTAL_GOALS_2_5_90M",
    }
    assert all(row["confirmatory_admissible"] for row in aggregate_rows)
    assert dq_count == 0
    assert canary_links >= 1
    keys = tuple(store.iter_keys("known-at/"))
    assert all(
        any(key.startswith(prefix) for key in keys)
        for prefix in (
            "known-at/facts/schema-v1/",
            "known-at/prices/schema-v1/",
            "known-at/receipts/schema-v1/",
            "known-at/recovery/schema-v1/",
        )
    )


def test_overround_rejection_emits_dq_and_never_reaches_legacy_prices(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _five_book_odds_cache(
        tmp_path / "cache.json",
        last_update=NOW - timedelta(seconds=30),
        h2h_prices=(1.5, 1.5, 1.5),
        total_prices=(1.5, 1.5),
    )
    engine, state, report, _ = _run_sql_odds_capture(
        tmp_path,
        monkeypatch,
        cache=cache,
    )
    with engine.connect() as connection:  # type: ignore[union-attr]
        counts = {
            table_name: connection.execute(
                select(func.count()).select_from(state.tables[table_name])
            ).scalar_one()
            for table_name in (
                "price_snapshot_metadata",
                "price_derivation_metadata",
                "market_snapshot_metadata",
                "prospective_odds_snapshots",
                "data_quality_events",
            )
        }
        dq_rows = list(
            connection.execute(select(state.tables["data_quality_events"]))
            .mappings()
        )
    assert report["captured"] >= 1
    assert counts == {
        "price_snapshot_metadata": 25,
        "price_derivation_metadata": 0,
        "market_snapshot_metadata": 0,
        "prospective_odds_snapshots": 0,
        "data_quality_events": 10,
    }
    assert {row["event_code"] for row in dq_rows} == {"NO_PRICE"}
    assert all("outside the frozen" in row["summary"] for row in dq_rows)


def test_stale_prices_never_reach_active_prequential_legacy_table(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    cache = _five_book_odds_cache(
        tmp_path / "cache.json",
        last_update=NOW - timedelta(seconds=601),
    )
    engine, state, report, _ = _run_sql_odds_capture(
        tmp_path,
        monkeypatch,
        cache=cache,
    )
    with engine.connect() as connection:  # type: ignore[union-attr]
        legacy_count = connection.execute(
            select(func.count()).select_from(
                state.tables["prospective_odds_snapshots"]
            )
        ).scalar_one()
        derivation_count = connection.execute(
            select(func.count()).select_from(
                state.tables["price_derivation_metadata"]
            )
        ).scalar_one()
        dq_count = connection.execute(
            select(func.count()).select_from(state.tables["data_quality_events"])
        ).scalar_one()
    assert report["captured"] >= 1
    assert legacy_count == 0
    assert derivation_count == 0
    assert dq_count == 25


def test_price_contract_mutation_fails_before_provider_call(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path / "cache.json")
    output = tmp_path / "reports"
    repository = ProspectiveR2Repository(
        DirectoryObjectStore(tmp_path / "objects")
    )
    state = MemoryOperationalState()
    run_fixture_registry(
        _args(
            "fixture-registry",
            output=output,
            cache=cache,
            object_store_root=tmp_path / "objects",
        ),
        state=state,
        repository=repository,
    )
    run_scheduler(_args("scheduler", output=output), state=state)
    mutated_contract = json.loads(
        (ROOT / "configs/prices/point-in-time-price-contract-v1.json").read_text(
            encoding="utf-8"
        )
    )
    mutated_contract["aggregation"] = "UNAUTHORIZED_MUTATION"
    mutated_path = tmp_path / "mutated-price-contract.json"
    mutated_path.write_text(json.dumps(mutated_contract), encoding="utf-8")
    args = _args(
        "capture-odds",
        output=output,
        cache=cache,
        object_store_root=tmp_path / "objects",
    )
    args.chronos_price_contract = mutated_path
    unused_provider = _FakeApiFootball(fail=False)
    with pytest.raises(
        RuntimeError,
        match="CHRONOS_PRICE_CONTRACT_NOT_FAIL_CLOSED",
    ):
        run_capture(
            args,
            state=state,
            repository=repository,
            provider=unused_provider,  # type: ignore[arg-type]
        )
    assert unused_provider.status_calls == 0
    assert unused_provider.fixture_calls == 0
