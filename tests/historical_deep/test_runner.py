from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from robin.historical_deep.contracts import (
    HarvestTask,
    ProviderStatus,
    TemporalClass,
    load_campaign_contract,
)
from robin.historical_deep.provider import (
    ProviderAuthenticationError,
    ProviderStatusError,
    ProviderTransportError,
)
from robin.historical_deep.runtime import DurableRuntimeLedger
from robin.historical_deep.storage import (
    InMemoryObjectStore,
    R2FirstRepository,
)
from scripts import run_historical_deep_harvest as runner

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "historical-deep-data-harvest-v1.json"
NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)
LOCKS = {
    "STORAGE_PAUSED": "true",
    "P3_P4_PAUSED": "true",
    "PRODUCTION_LOCKED": "true",
    "REAL_BETS": "false",
    "NO_BET_DEFAULT": "true",
    "PROMOTION_LOCKED": "true",
    "SOCIAL_PUBLISHING_ENABLED": "false",
    "DEMO_MODE_ENABLED": "false",
    "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
    "THE_ODDS_API_HISTORICAL_CREDITS": "false",
}


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW
        self.elapsed = 0.0

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=1)
        return value

    def monotonic(self) -> float:
        self.elapsed += 0.01
        return self.elapsed


def _coverage() -> dict[str, object]:
    return {
        "fixtures": {
            "events": True,
            "lineups": True,
            "statistics_fixtures": True,
            "statistics_players": True,
        },
        "players": True,
        "injuries": True,
    }


class FakeProvider:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.quota: object | None = None
        self.status_calls = 0
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_status(self) -> ProviderStatus:
        self.status_calls += 1
        checked_at = self.clock.now()
        return ProviderStatus(
            plan="Mega",
            active=True,
            daily_limit=200_000,
            daily_used=20_000,
            daily_remaining=180_000,
            checked_at=checked_at,
            expires_at=checked_at + timedelta(minutes=120),
            subscription_end=checked_at + timedelta(days=31),
        )

    def get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> object:
        before_request = getattr(self.quota, "before_request", None)
        if callable(before_request):
            before_request()
        copied = dict(params or {})
        self.calls.append((endpoint, copied))
        requested_at = self.clock.now()
        response: list[object]
        if endpoint == "/leagues":
            selected = copied.get("season")
            years = [int(selected)] if selected is not None else [2024, 2017]
            response = [
                {
                    "league": {"id": copied["id"]},
                    "seasons": [
                        {"year": year, "coverage": _coverage()}
                        for year in years
                    ],
                }
            ]
        elif endpoint == "/fixtures":
            league = int(copied.get("league", 39))
            season = int(copied.get("season", 2024))
            fixture_id = (
                int(str(copied["ids"]).split("-")[0])
                if "ids" in copied
                else league * 100_000 + season
            )
            response = [
                {
                    "fixture": {"id": fixture_id},
                    "league": {
                        "id": league,
                        "season": season,
                        "round": "Regular Season - 1",
                    },
                    "teams": {
                        "home": {"id": 1, "name": "Home"},
                        "away": {"id": 2, "name": "Away"},
                    },
                }
            ]
        elif endpoint == "/players":
            response = [
                {
                    "player": {"id": int(copied["league"]), "name": "Player"},
                    "statistics": [],
                }
            ]
        elif endpoint == "/injuries":
            response = [
                {
                    "player": {"id": int(copied["league"])},
                    "fixture": {"id": int(copied["season"])},
                }
            ]
        elif endpoint == "/standings":
            response = [
                {
                    "league": {
                        "id": int(copied["league"]),
                        "season": int(copied["season"]),
                        "standings": [],
                    }
                }
            ]
        elif endpoint == "/fixtures/rounds":
            response = ["Regular Season - 1"]
        elif endpoint == "/sidelined":
            response = []
        else:
            raise AssertionError(f"unexpected provider endpoint: {endpoint}")
        received_at = self.clock.now()
        return SimpleNamespace(
            payload={
                "response": response,
                "paging": {"current": 1, "total": 1},
                "errors": {},
            },
            http_status=200,
            headers={
                "x-ratelimit-requests-remaining": "179999",
                "set-cookie": "must-not-be-persisted",
            },
            attempts=1,
            requested_at=requested_at,
            received_at=received_at,
        )


class ProviderPool:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.instances: list[FakeProvider] = []

    def __call__(self, _api_key: str) -> FakeProvider:
        provider = FakeProvider(self.clock)
        self.instances.append(provider)
        return provider


def _services(
    clock: FakeClock,
    provider_factory: Any,
    store: InMemoryObjectStore | None = None,
) -> runner.RunnerServices:
    selected_store = store or InMemoryObjectStore()
    return runner.RunnerServices(
        now=clock.now,
        monotonic=clock.monotonic,
        provider_factory=provider_factory,
        store_factory=lambda _environment, _cache_root: selected_store,
    )


def _args(
    tmp_path: Path,
    command: str,
    *command_args: str,
) -> list[str]:
    return [
        "--config",
        str(CONFIG),
        "--output",
        str(tmp_path / "artifacts"),
        "--code-revision",
        "runner-test-revision",
        "--cache-root",
        str(tmp_path / "objects"),
        command,
        *command_args,
    ]


def _environment(*, with_key: bool = True) -> dict[str, str]:
    result = dict(LOCKS)
    if with_key:
        result["API_FOOTBALL_KEY"] = "not-a-real-key"
    return result


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("census", ["--execute", "--max-calls", "500", "--max-duration-minutes", "100"]),
        (
            "fixtures",
            [
                "--execute",
                "--priority",
                "P0",
                "--max-calls",
                "30000",
                "--max-duration-minutes",
                "100",
                "--mission-max-minutes",
                "720",
            ],
        ),
        ("players", ["--execute", "--priority", "P1", "--max-calls", "20000"]),
        ("injuries", ["--execute", "--priority", "auto", "--max-calls", "10000"]),
        ("replay", []),
        ("quality", []),
        ("features", []),
        ("backtest", []),
        ("report", []),
    ],
)
def test_parser_accepts_workflow_command_shapes(
    command: str,
    arguments: list[str],
) -> None:
    parsed = runner.build_parser().parse_args(
        ["--config", str(CONFIG), command, *arguments]
    )

    assert parsed.command == command


def test_dry_run_and_safety_fail_before_store_or_provider(tmp_path: Path) -> None:
    clock = FakeClock()

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("external service must not be constructed")

    services = runner.RunnerServices(
        now=clock.now,
        monotonic=clock.monotonic,
        provider_factory=forbidden,
        store_factory=forbidden,
    )
    assert runner.run(
        _args(tmp_path, "census"),
        environment=_environment(),
        services=services,
    ) == 0
    artifact = json.loads(
        (tmp_path / "artifacts" / "census.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "PLANNED_NOT_EXECUTED"
    assert artifact["provider_calls"] == 0
    assert "not-a-real-key" not in json.dumps(artifact)

    invalid_environment = _environment()
    invalid_environment["PRODUCTION_LOCKED"] = "false"
    assert runner.run(
        _args(tmp_path, "census", "--execute"),
        environment=invalid_environment,
        services=services,
    ) == 2


def test_real_executed_collection_refuses_local_cache_root(
    tmp_path: Path,
) -> None:
    assert runner.run(
        _args(tmp_path, "census", "--execute"),
        environment=_environment(),
    ) == 2
    artifact = json.loads(
        (tmp_path / "artifacts" / "census.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "FAILED"
    assert artifact["reason"] == "EXECUTED_COLLECTION_REQUIRES_DURABLE_R2"


def test_census_discovers_all_seasons_is_idempotent_and_drives_p2(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    providers = ProviderPool(clock)
    store = InMemoryObjectStore()
    services = _services(clock, providers, store)

    census_args = _args(tmp_path, "census", "--execute", "--max-calls", "500")
    assert runner.run(
        census_args,
        environment=_environment(),
        services=services,
    ) == 0
    first = providers.instances[-1]
    discovery_calls = [
        params
        for endpoint, params in first.calls
        if endpoint == "/leagues" and "season" not in params
    ]
    assert len(discovery_calls) == 5

    ledger = DurableRuntimeLedger(store)
    discovery = ledger.latest_value("coverage/discovery")
    assert isinstance(discovery, Mapping)
    competitions = discovery["competitions"]
    assert isinstance(competitions, Mapping)
    assert all(
        scoped["advertised_seasons"] == [2017, 2024]
        and scoped["verified_older_seasons"] == [2017]
        for scoped in competitions.values()
        if isinstance(scoped, Mapping)
    )
    _payloads, receipts = ledger.raw_evidence()
    raw_discovery = next(
        receipt
        for receipt in receipts
        if receipt.get("endpoint") == "/leagues"
        and receipt.get("parameters") == {"id": 39}
    )
    assert raw_discovery["sanitized_quota_headers"] == {
        "x-ratelimit-requests-remaining": "179999"
    }
    assert raw_discovery["attempts"] == raw_discovery["provider_calls"] == 1
    assert raw_discovery["collector_version"] == runner.COLLECTOR_VERSION
    assert raw_discovery["source_commit"] == "runner-test-revision"
    first_census = ledger.latest_value("collection/census")
    assert isinstance(first_census, Mapping)
    assert first_census["baseline_census_present"] is False
    first_observation = next(
        value
        for value in first_census["observations"]
        if isinstance(value, Mapping)
    )
    assert all(
        value is None
        for value in first_observation["coverage_before_mission"].values()
    )
    assert first_observation["coverage_after_mission"] == (
        first_observation["actual_coverage"]
    )

    artifact = json.loads(
        (tmp_path / "artifacts" / "census.json").read_text(encoding="utf-8")
    )
    assert "observations" not in artifact["result"]
    assert artifact["result"]["observations_count"] == 10
    assert "payload" not in json.dumps(artifact).casefold()

    assert runner.run(
        census_args,
        environment=_environment(),
        services=services,
    ) == 0
    second = providers.instances[-1]
    assert second.status_calls == 1
    assert second.calls == []
    second_census = ledger.latest_value("collection/census")
    assert isinstance(second_census, Mapping)
    assert second_census["baseline_census_present"] is True
    assert all(
        not value["coverage_changed_families"]
        for value in second_census["observations"]
        if isinstance(value, Mapping)
    )

    assert runner.run(
        _args(tmp_path, "players", "--execute", "--priority", "P2"),
        environment=_environment(),
        services=services,
    ) == 0
    p2 = providers.instances[-1]
    assert p2.calls == []
    progress = ledger.values("progress/players")
    assert len(progress) == 5
    assert all(
        envelope["value"]["season"] == 2017
        for envelope in progress
    )
    usage = [
        envelope["value"]["mission_calls_used"]
        for envelope in ledger.values("mission/usage")
    ]
    assert max(usage) == 508


def test_status_reservation_counts_retries_and_blocks_data_at_job_cap(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    providers = ProviderPool(clock)
    store = InMemoryObjectStore()

    assert runner.run(
        _args(tmp_path, "census", "--execute", "--max-calls", "4"),
        environment=_environment(),
        services=_services(clock, providers, store),
    ) == 0
    provider = providers.instances[0]
    assert provider.status_calls == 1
    assert provider.calls == []

    artifact = json.loads(
        (tmp_path / "artifacts" / "census.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "PARTIAL"
    assert artifact["provider_calls"] == 4
    assert artifact["result"]["reason"] == "JOB_PROVIDER_CALL_LIMIT_REACHED"
    ledger = DurableRuntimeLedger(store)
    usage = ledger.latest_value("mission/usage")
    assert isinstance(usage, Mapping)
    assert usage["mission_calls_used"] == 4
    assert usage["mission_call_cap"] == 100_000


def test_mission_attempts_are_pre_reserved_durably_in_bounded_chunks() -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()
    ledger = DurableRuntimeLedger(store)
    limits = runner.ExecutionLimits(
        phase="fixtures",
        ledger=ledger,
        now=clock.now,
        monotonic=clock.monotonic,
        job_started_at=NOW,
        mission_started_at=NOW,
        maximum_calls=1_000,
        maximum_minutes=100,
        mission_maximum_minutes=720,
        checkpoint_calls=500,
        checkpoint_minutes=20,
        provider_calls=4,
        mission_calls_used=4,
        mission_call_cap=100_000,
    )

    limits.before_provider_attempt()

    assert limits.provider_calls == 5
    assert limits.mission_calls_used == 504
    usage = ledger.latest_value("mission/usage")
    assert isinstance(usage, Mapping)
    assert usage["mission_calls_used"] == 504
    assert usage["accounting"] == "CONSERVATIVE_RESERVED_HIGH_WATER"
    assert runner._persisted_mission_calls(
        ledger,
        mission_started_at=NOW,
        mission_call_cap=100_000,
    ) == 504


def test_preseeded_global_cap_is_partial_without_building_provider(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()
    ledger = DurableRuntimeLedger(store)
    started_at = ledger.mission_start(
        now=NOW,
        code_revision="runner-test-revision",
        maximum_minutes=720,
    )
    ledger.put_json(
        "mission/usage",
        {
            "mission_started_at": started_at,
            "mission_call_cap": 100_000,
            "mission_calls_used": 100_000,
        },
        recorded_at=clock.now(),
    )

    def forbidden(_api_key: str) -> FakeProvider:
        raise AssertionError("provider must not be built after global cap")

    assert runner.run(
        _args(tmp_path, "census", "--execute"),
        environment=_environment(),
        services=_services(clock, forbidden, store),
    ) == 0
    artifact = json.loads(
        (tmp_path / "artifacts" / "census.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "PARTIAL"
    result = artifact["result"]
    assert isinstance(result, dict)
    assert result["reason"] == "GLOBAL_MISSION_CALL_CAP_REACHED"


def test_missing_key_and_status_failure_persist_sanitized_provider_block(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    missing_store = InMemoryObjectStore()

    def forbidden(_api_key: str) -> FakeProvider:
        raise AssertionError("provider must not be built without a key")

    assert runner.run(
        _args(tmp_path, "census", "--execute"),
        environment=_environment(with_key=False),
        services=_services(clock, forbidden, missing_store),
    ) == 0
    ledger = DurableRuntimeLedger(missing_store)
    missing_key = ledger.latest_value("provider/status")
    assert isinstance(missing_key, Mapping)
    assert missing_key["status"] == "BLOCKED_PROVIDER"
    assert missing_key["reason_class"] == "API_FOOTBALL_KEY_REQUIRED"

    class RejectedProvider(FakeProvider):
        def get_status(self) -> ProviderStatus:
            raise ProviderStatusError("secret-body-and-key")

    rejected_clock = FakeClock()
    rejected_store = InMemoryObjectStore()
    assert runner.run(
        _args(tmp_path / "rejected", "census", "--execute"),
        environment=_environment(),
        services=_services(
            rejected_clock,
            lambda _api_key: RejectedProvider(rejected_clock),
            rejected_store,
        ),
    ) == 0
    rejected_ledger = DurableRuntimeLedger(rejected_store)
    blocked = rejected_ledger.latest_value("provider/status")
    serialized = json.dumps(blocked)
    assert isinstance(blocked, Mapping)
    assert blocked["status"] == "BLOCKED_PROVIDER"
    assert blocked["reason_class"] == "ProviderStatusError"
    assert "secret-body-and-key" not in serialized

    class TransportFailureProvider(FakeProvider):
        def get_status(self) -> ProviderStatus:
            raise ProviderTransportError("safe-transport-code")

    partial_clock = FakeClock()
    partial_store = InMemoryObjectStore()
    assert runner.run(
        _args(tmp_path / "partial", "census", "--execute"),
        environment=_environment(),
        services=_services(
            partial_clock,
            lambda _api_key: TransportFailureProvider(partial_clock),
            partial_store,
        ),
    ) == 0
    partial_artifact = json.loads(
        (
            tmp_path
            / "partial"
            / "artifacts"
            / "census.json"
        ).read_text(encoding="utf-8")
    )
    assert partial_artifact["status"] == "PARTIAL"
    assert partial_artifact["result"]["reason"] == "ProviderTransportError"
    assert DurableRuntimeLedger(partial_store).latest_value("provider/status") is None


def test_endpoint_authentication_failure_cannot_be_overwritten_by_old_status(
    tmp_path: Path,
) -> None:
    class RevokedProvider(FakeProvider):
        def get(
            self,
            endpoint: str,
            *,
            params: Mapping[str, object] | None = None,
        ) -> object:
            raise ProviderAuthenticationError("secret-provider-body")

    clock = FakeClock()
    store = InMemoryObjectStore()
    services = _services(
        clock,
        lambda _api_key: RevokedProvider(clock),
        store,
    )

    assert runner.run(
        _args(tmp_path, "census", "--execute"),
        environment=_environment(),
        services=services,
    ) == 0

    provider = DurableRuntimeLedger(store).latest_value("provider/status")
    assert isinstance(provider, Mapping)
    assert provider["status"] == "BLOCKED_PROVIDER"
    assert provider["reason_class"] == "ProviderAuthenticationError"
    assert provider["code_revision"] == "runner-test-revision"
    assert "secret-provider-body" not in json.dumps(provider)

    def forbidden(_api_key: str) -> FakeProvider:
        raise AssertionError("report cannot construct a provider")

    assert runner.run(
        _args(tmp_path / "report", "report"),
        environment=_environment(),
        services=_services(clock, forbidden, store),
    ) == 0
    artifact = json.loads(
        (
            tmp_path
            / "report"
            / "artifacts"
            / "report.json"
        ).read_text(encoding="utf-8")
    )
    assert artifact["status"] == "HISTORICAL_DEEP_DATA_HARVEST_BLOCKED_BY_PROVIDER"
    assert artifact["result"]["provider"]["status"] == "BLOCKED_PROVIDER"


def _backtest_fixture_rows() -> list[dict[str, object]]:
    return [
        {
            "research_mode": "STRICT_PREMATCH",
            "period": period,
            "fixture_id": f"fixture-{index}",
            "kickoff_at": kickoff,
            "model_probability": probability,
            "market_probability": 0.5,
            "odds": 2.0,
            "target": index % 2,
            "competition": "api-football:39",
            "source_mode": "TRACKED_CACHE",
            "provider_calls": 0,
            "max_feature_source_kickoff": (
                datetime.fromisoformat(kickoff) - timedelta(days=7)
            ).isoformat(),
        }
        for index, (period, kickoff, probability) in enumerate(
            (
                ("2022", "2022-08-01T12:00:00+00:00", 0.55),
                ("2022", "2022-08-08T12:00:00+00:00", 0.65),
                ("2023", "2023-08-01T12:00:00+00:00", 0.60),
                ("2023", "2023-08-08T12:00:00+00:00", 0.70),
            ),
            start=1,
        )
    ]


def test_backtest_is_cache_only_executes_folds_and_never_builds_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()

    def forbidden(_api_key: str) -> FakeProvider:
        raise AssertionError("analysis commands cannot construct a provider")

    monkeypatch.setattr(
        runner,
        "build_cache_only_backtest_input",
        lambda _path: _backtest_fixture_rows(),
    )
    args = [
        *_args(tmp_path, "backtest"),
        "--matches-path",
        str(tmp_path / "matches.parquet"),
    ]
    # Global options must precede the subcommand.
    matches_index = args.index("--matches-path")
    moved = args[matches_index : matches_index + 2]
    del args[matches_index : matches_index + 2]
    command_index = args.index("backtest")
    args[command_index:command_index] = moved

    assert runner.run(
        args,
        environment=_environment(),
        services=_services(clock, forbidden, store),
    ) == 0
    ledger = DurableRuntimeLedger(store)
    backtest = ledger.latest_value("backtest")
    assert isinstance(backtest, Mapping)
    assert backtest["provider_calls"] == 0
    assert backtest["input_rows"] == 4
    assert backtest["evaluated_folds"] == 1
    assert backtest["status"] == "PARTIAL"
    assert backtest["deep_feature_rows"] == 0

    artifact = json.loads(
        (tmp_path / "artifacts" / "backtest.json").read_text(encoding="utf-8")
    )
    assert artifact["result"]["input_rows"] == 4
    assert artifact["result"]["evaluated_folds"] == 1
    assert "details" not in json.dumps(artifact)


def test_replay_never_builds_provider_or_materializes_all_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()

    def forbidden(_api_key: str) -> FakeProvider:
        raise AssertionError("replay cannot construct a provider")

    def forbidden_raw_evidence(_ledger: DurableRuntimeLedger) -> object:
        raise AssertionError("replay must stream raw evidence")

    def forbidden_global_recovery(_repository: R2FirstRepository) -> object:
        raise AssertionError("replay must not mutate raw evidence during recovery")

    monkeypatch.setattr(
        DurableRuntimeLedger,
        "raw_evidence",
        forbidden_raw_evidence,
    )
    monkeypatch.setattr(
        R2FirstRepository,
        "resume_pending",
        forbidden_global_recovery,
    )
    assert runner.run(
        _args(tmp_path, "replay"),
        environment=_environment(),
        services=_services(clock, forbidden, store),
    ) == 0
    replay = DurableRuntimeLedger(store).latest_value("replay")
    assert isinstance(replay, Mapping)
    assert replay["provider_calls"] == 0


def test_tracked_backtest_builder_uses_strictly_prior_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches_path = tmp_path / "matches.parquet"
    matches_path.write_bytes(b"test-placeholder")
    frame = pd.DataFrame(
        [
            {
                "league": "E0",
                "season": "2022",
                "date": f"2022-08-{day:02d}T12:00:00+00:00",
                "home": "A" if day % 2 else "B",
                "away": "B" if day % 2 else "A",
                "fthg": 2 if day % 2 else 0,
                "ftag": 1,
                "psh": 2.0,
                "psch": 1.9,
                "match_id": f"2022-{day}",
            }
            for day in (1, 8, 15)
        ]
        + [
            {
                "league": "E0",
                "season": "2023",
                "date": f"2023-08-{day:02d}T12:00:00+00:00",
                "home": "A" if day % 2 else "B",
                "away": "B" if day % 2 else "A",
                "fthg": 1,
                "ftag": 0,
                "psh": 2.1,
                "psch": 2.0,
                "match_id": f"2023-{day}",
            }
            for day in (1, 8, 15)
        ]
    )
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: frame)

    rows = runner.build_cache_only_backtest_input(matches_path)

    assert rows
    assert {row["season"] for row in rows} == {"2022", "2023"}
    assert all(
        datetime.fromisoformat(str(row["max_feature_source_kickoff"]))
        < datetime.fromisoformat(str(row["kickoff_at"]))
        for row in rows
    )
    assert all(row["provider_calls"] == 0 for row in rows)
    assert all(
        row["deep_player_features"] == "BLOCKED_BY_SOURCE"
        and row["deep_lineup_features"] == "BLOCKED_BY_SOURCE"
        for row in rows
    )


class TrackingStore:
    def __init__(self) -> None:
        self.delegate = InMemoryObjectStore()
        self.gets: list[str] = []
        self.prefixes: list[str] = []

    def get_object(self, key: str) -> bytes | None:
        self.gets.append(key)
        return self.delegate.get_object(key)

    def put_if_absent(self, key: str, data: bytes) -> bool:
        return self.delegate.put_if_absent(key, data)

    def iter_keys(self, prefix: str) -> Iterable[str]:
        self.prefixes.append(prefix)
        return self.delegate.iter_keys(prefix)


def _capture_fixture(
    repository: R2FirstRepository,
    task: HarvestTask,
    fixture_id: int,
) -> str:
    stored = repository.capture(
        task=task,
        payload={"response": [{"fixture": {"id": fixture_id}}]},
        requested_at=NOW,
        received_at=NOW + timedelta(seconds=1),
        source_commit="runner-test-revision",
    )
    return stored.receipt.payload_key


def test_runtime_inventory_uses_exact_prefix_and_filters_before_payload(
) -> None:
    contract = load_campaign_contract(CONFIG)
    tracking = TrackingStore()
    repository = R2FirstRepository(tracking)
    competition_39 = contract.competition("api-football:39")
    competition_61 = contract.competition("api-football:61")
    task_39 = HarvestTask.create(
        campaign_id=contract.campaign_id,
        competition=competition_39,
        season=2024,
        family="fixtures",
        endpoint="/fixtures",
        temporal_class=TemporalClass.FIXTURE_SPECIFIC_POST_HOC,
        params={"league": 39, "season": 2024},
    )
    task_61 = HarvestTask.create(
        campaign_id=contract.campaign_id,
        competition=competition_61,
        season=2024,
        family="fixtures",
        endpoint="/fixtures",
        temporal_class=TemporalClass.FIXTURE_SPECIFIC_POST_HOC,
        params={"league": 61, "season": 2024},
    )
    player_task = HarvestTask.create(
        campaign_id=contract.campaign_id,
        competition=competition_39,
        season=2024,
        family="players",
        endpoint="/players",
        temporal_class=TemporalClass.SEASON_FINAL_AGGREGATE,
        params={"league": 39, "season": 2024, "page": 1},
    )
    payload_39 = _capture_fixture(repository, task_39, 1001)
    payload_61 = _capture_fixture(repository, task_61, 2001)
    player_payload = repository.capture(
        task=player_task,
        payload={"response": [{"player": {"id": 10}}]},
        requested_at=NOW,
        received_at=NOW + timedelta(seconds=1),
        source_commit="runner-test-revision",
    ).receipt.payload_key
    tracking.gets.clear()
    tracking.prefixes.clear()

    inventory = DurableRuntimeLedger(tracking).fixture_inventory(
        league=39,
        season=2024,
    )

    assert inventory == (1001,)
    assert tracking.prefixes == [
        "historical-deep-data/schema-v1/"
        "competition=api-football:39/season=2024/"
    ]
    assert payload_39 in tracking.gets
    assert payload_61 not in tracking.gets
    assert player_payload not in tracking.gets
    assert not any(
        "competition=api-football:61" in key for key in tracking.gets
    )


def test_normalized_records_streams_without_materializing_raw_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = DurableRuntimeLedger(InMemoryObjectStore())

    def forbidden() -> object:
        raise AssertionError("normalized replay must stream receipts")

    monkeypatch.setattr(ledger, "raw_evidence", forbidden)
    assert ledger.normalized_records() == ([], ())


def test_quality_uses_stable_identity_and_detects_null_to_zero() -> None:
    common = {
        "task_id": "task-1",
        "normalized_family": "teams",
        "canonical_id": "api-football:team:1",
        "provider_fixture_id": 10,
        "source_record_hash": "source-1",
        "source_payload_hash": "a" * 64,
        "temporal_class": "PRIOR_MATCH_USABLE",
    }
    before = [{**common, "record_hash": "before", "value": None}]
    after = [{**common, "record_hash": "after", "value": 0}]

    comparison = runner.compare_quality_v2(
        runner._quality_keyed_rows(before),
        runner._quality_keyed_rows(after),
        key_fields=("quality_row_key",),
        required_fields=("record_hash",),
        fail_on_null_to_zero=False,
    )

    assert comparison.null_to_zero_conversions == 1
    assert any(
        mismatch.field == "value" and mismatch.kind == "NULL_TO_ZERO"
        for mismatch in comparison.mismatches
    )


def test_gate_coverage_uses_census_denominator_and_never_presence_only() -> None:
    datasets: dict[str, list[dict[str, object]]] = {
        name: []
        for name in (
            "TEAM_PREMATCH_STRICT",
            "PLAYER_PREMATCH_STRICT",
            "LINEUP_HISTORY_PREMATCH_STRICT",
            "TARGET_POST_LINEUP_RECONSTRUCTED",
            "INJURY_INTERVAL_RECONSTRUCTED",
            "POST_MATCH_DESCRIPTIVE",
        )
    }
    datasets["TEAM_PREMATCH_STRICT"] = [
        {
            "family": "team_match_statistics",
            "provider_competition_id": 39,
            "season": 2024,
            "canonical_id": "api-football:team:1",
            "identity_status": "PROVIDER_ID_VERIFIED",
        }
    ]
    census = {
        "observations": [
            {
                "provider_league_id": 39,
                "season": 2024,
                "field_matrix": {
                    "team_match_statistics": {
                        "sample_coverage_rate": 0.5,
                    }
                },
            }
        ]
    }

    assessments = runner.evaluate_gate_registry(
        runner._gate_evidence(
            datasets,
            coverage_census=census,
        )
    )

    assert assessments["TEAM"].coverage_rate == 0.5
    assert assessments["TEAM"].status != "READY_STRICT"
    assert assessments["DISCIPLINE"].status == "BLOCKED_BY_COVERAGE"


def test_quality_persists_rows_in_the_exact_manifest_hash_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()
    ledger = DurableRuntimeLedger(store)
    revision = "quality-hash-revision"
    run_token = "quality-hash-run:1"

    def row(
        *,
        task_id: str,
        family: str,
        canonical_id: str,
        fixture_id: int,
        kickoff: str,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "task_id": task_id,
            "normalized_family": family,
            "family": family,
            "canonical_id": canonical_id,
            "identity_status": "PROVIDER_ID_VERIFIED",
            "provider_competition_id": 39,
            "season": 2024,
            "provider_fixture_id": fixture_id,
            "target_kickoff_at": kickoff,
            "source_record_hash": runner.canonical_sha256(
                [task_id, fixture_id]
            ),
            "source_payload_hash": "a" * 64,
            "temporal_class": "FIXTURE_SPECIFIC_POST_HOC",
            "data": {},
        }
        value["record_hash"] = runner.canonical_sha256(value)
        return value

    normalized = [
        row(
            task_id="z-task",
            family="teams",
            canonical_id="api-football:team:2",
            fixture_id=20,
            kickoff="2024-02-01T12:00:00+00:00",
        ),
        row(
            task_id="a-task",
            family="teams",
            canonical_id="api-football:team:1",
            fixture_id=10,
            kickoff="2024-01-01T12:00:00+00:00",
        ),
        row(
            task_id="target-task",
            family="fixtures",
            canonical_id="api-football:fixture:30",
            fixture_id=30,
            kickoff="2024-06-01T12:00:00+00:00",
        ),
    ]
    ledger.put_json(
        "replay/projection",
        {
            "schema_version": "historical-deep-normalized-replay-v1",
            "code_revision": revision,
            "run_token": run_token,
            "rows": normalized,
            "normalization_errors": [],
            "projection_hash": runner.canonical_sha256(normalized),
        },
        recorded_at=clock.now(),
    )
    ledger.put_json(
        "replay",
        {
            "status": "CACHE_ONLY_REPLAY_VERIFIED",
            "code_revision": revision,
            "run_token": run_token,
            "replay_hash": "b" * 64,
        },
        recorded_at=clock.now(),
    )
    monkeypatch.setattr(
        ledger,
        "normalized_records",
        lambda: ([dict(value) for value in normalized], ()),
    )

    result = runner._run_quality(
        ledger=ledger,
        contract=load_campaign_contract(CONFIG),
        code_revision=revision,
        run_token=run_token,
        services=_services(clock, lambda _key: FakeProvider(clock), store),
    )

    manifest = result["datasets"]["TEAM_PREMATCH_STRICT"]
    assert isinstance(manifest, Mapping)
    stored = ledger.latest_value("datasets/TEAM_PREMATCH_STRICT")
    assert isinstance(stored, Mapping)
    stored_rows = stored["rows"]
    assert isinstance(stored_rows, list)
    assert stored_rows == sorted(stored_rows, key=runner.canonical_sha256)
    assert manifest["dataset_hash"] == runner.canonical_sha256(stored_rows)


def test_gate_coverage_fails_closed_without_a_real_denominator() -> None:
    evidence = runner._evidence_for_rows(
        [
            {
                "season": season,
                "canonical_id": f"api-football:team:{season}",
                "identity_status": "PROVIDER_ID_VERIFIED",
            }
            for season in (2022, 2023, 2024)
        ],
        reconstructed=False,
    )

    team_gate = runner.evaluate_gate_registry({"TEAM": evidence})["TEAM"]

    assert team_gate.coverage_rate is None
    assert team_gate.status == "BLOCKED_BY_COVERAGE"
    assert team_gate.ready is False


def test_analysis_failure_is_run_scoped_and_forces_failed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()
    services = _services(clock, lambda _key: FakeProvider(clock), store)
    old_environment = {
        **_environment(),
        "GITHUB_RUN_ID": "100",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    current_environment = {
        **_environment(),
        "GITHUB_RUN_ID": "200",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    old_args = _args(tmp_path / "old", "replay")
    assert runner.run(
        old_args,
        environment=old_environment,
        services=services,
    ) == 0

    def failed_replay(**_kwargs: object) -> dict[str, object]:
        raise ValueError("must-not-be-persisted")

    monkeypatch.setattr(runner, "_run_replay", failed_replay)
    assert runner.run(
        _args(tmp_path / "current", "replay"),
        environment=current_environment,
        services=services,
    ) == 2
    assert runner.run(
        _args(tmp_path / "report", "report"),
        environment=current_environment,
        services=services,
    ) == 0

    ledger = DurableRuntimeLedger(store)
    report = ledger.latest_value("report")
    assert isinstance(report, Mapping)
    assert report["verdict"] == "HISTORICAL_DEEP_DATA_HARVEST_FAILED"
    assert report["run_token"] == "200:1"
    assert report["replay"] == {}
    assert any(
        str(reason).startswith("ANALYSIS_REPLAY_FAILED:ValueError")
        for reason in report["fatal_errors"]
    )
    serialized = json.dumps(report)
    assert "must-not-be-persisted" not in serialized
    old_replay = runner._latest_mapping_for_lineage(
        ledger,
        "replay",
        "runner-test-revision",
        "100:1",
    )
    assert old_replay["code_revision"] == "runner-test-revision"
    assert old_replay["run_token"] == "100:1"


def test_compact_report_projection_keeps_proofs_and_manifest_counts() -> None:
    projection = runner._compact_result_projection(
        {
            "verdict": "HISTORICAL_DEEP_DATA_HARVEST_PARTIAL",
            "code_revision": "revision-1",
            "partial_reasons": ["BACKTEST_PARTIAL"],
            "provider": {
                "status": "AVAILABLE",
                "plan": "Mega",
                "active": True,
                "daily_remaining": 100_000,
                "secret": "must-not-leak",
            },
            "replay": {
                "status": "CACHE_ONLY_REPLAY_VERIFIED",
                "payloads_replayed": 42,
                "receipts_verified": 42,
                "replay_hash": "a" * 64,
                "entries": [{"payload": "raw"}],
            },
            "quality_v2": {
                "exact_replay": True,
                "mismatches": [],
                "normalization_errors": [],
                "null_to_zero_conversions": 0,
            },
            "datasets": {
                "TEAM_PREMATCH_STRICT": {
                    "row_count": 123,
                    "fixture_count": 12,
                    "dataset_hash": "b" * 64,
                    "provenance_hash": "c" * 64,
                    "cutoff_policy": "STRICT",
                    "allowed_usages": ["STRICT_PREMATCH"],
                }
            },
            "backtest": {
                "status": "PARTIAL",
                "input_rows": 5_000,
                "evaluated_folds": 3,
                "modes": {
                    "STRICT_PREMATCH": {
                        "rows": 5_000,
                        "folds": [{"details": [{"payload": "raw"}]}],
                    }
                },
            },
            "operations": {
                "storage": {
                    "receipts": 42,
                    "payload_objects": 42,
                    "stored_bytes": 1_024,
                },
                "mission_usage": {
                    "mission_calls_used": 500,
                    "mission_call_cap": 100_000,
                },
                "time_and_calls": {
                    "duration_seconds": 100.0,
                    "provider_calls": 500,
                    "requests_per_second_average": 5.0,
                    "errors": 1,
                    "retries": 2,
                    "batches_completed": 3,
                    "tasks_remaining": 4,
                    "eta_seconds": None,
                },
            },
        }
    )

    assert projection["dataset_row_counts"]["TEAM_PREMATCH_STRICT"] == 123
    assert projection["replay"]["payloads_replayed"] == 42
    assert projection["provider"]["plan"] == "Mega"
    assert projection["quality"]["mismatch_count"] == 0
    assert projection["backtest"]["evaluated_folds"] == 3
    assert projection["operations"]["time_and_calls"]["tasks_remaining"] == 4
    serialized = json.dumps(projection)
    assert "must-not-leak" not in serialized
    assert '"payload"' not in serialized
    assert '"details"' not in serialized


def test_capped_quota_delegates_exact_mission_counters() -> None:
    clock = FakeClock()
    store = InMemoryObjectStore()
    limits = runner.ExecutionLimits(
        phase="fixtures",
        ledger=DurableRuntimeLedger(store),
        now=clock.now,
        monotonic=clock.monotonic,
        job_started_at=NOW,
        mission_started_at=NOW,
        maximum_calls=100,
        maximum_minutes=100,
        mission_maximum_minutes=720,
        checkpoint_calls=500,
        checkpoint_minutes=20,
        provider_calls=4,
        mission_calls_used=4,
    )
    base = runner.QuotaController(
        FakeProvider(clock).get_status(),
        sleeper=lambda _seconds: None,
        clock=clock.monotonic,
        now=clock.now,
        initial_mission_used=17,
        initial_mission_cap=99_000,
    )
    capped = runner.CappedQuota(base, limits)

    assert capped.mission_used == 17
    assert capped.mission_cap == 99_000


def test_backtest_builder_isolates_leagues_and_same_kickoff_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matches_path = tmp_path / "matches.parquet"
    matches_path.write_bytes(b"test-placeholder")

    def match(
        match_id: str,
        league: str,
        kickoff: str,
        home: str,
        away: str,
        home_goals: int,
        away_goals: int,
    ) -> dict[str, object]:
        return {
            "league": league,
            "season": "2024",
            "date": kickoff,
            "home": home,
            "away": away,
            "fthg": home_goals,
            "ftag": away_goals,
            "psh": 2.0,
            "psch": 2.0,
            "match_id": match_id,
        }

    frame = pd.DataFrame(
        [
            match("f1-1", "F1", "2024-01-01T12:00:00+00:00", "Shared", "F", 3, 0),
            match("f1-2", "F1", "2024-01-08T12:00:00+00:00", "F", "Shared", 0, 2),
            match("e0-1", "E0", "2024-01-01T13:00:00+00:00", "Other", "X", 1, 0),
            match("e0-2", "E0", "2024-01-08T13:00:00+00:00", "X", "Other", 0, 1),
            match(
                "cross-league-target",
                "E0",
                "2024-01-15T12:00:00+00:00",
                "Shared",
                "Other",
                1,
                0,
            ),
            match("same-1", "E0", "2024-01-22T12:00:00+00:00", "Other", "X", 3, 0),
            match("same-2", "E0", "2024-01-22T12:00:00+00:00", "Other", "X", 0, 3),
        ]
    )
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: frame)

    rows = runner.build_cache_only_backtest_input(matches_path)
    by_fixture = {str(row["fixture_id"]): row for row in rows}

    assert "cross-league-target" not in by_fixture
    assert by_fixture["same-1"]["model_probability"] == by_fixture["same-2"][
        "model_probability"
    ]
    assert by_fixture["same-1"]["max_feature_source_kickoff"] == by_fixture[
        "same-2"
    ]["max_feature_source_kickoff"]
