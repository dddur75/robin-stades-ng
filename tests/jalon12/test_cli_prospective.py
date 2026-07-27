from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, func, select

from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory.budgets import BudgetExceeded, ProviderKind
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
)
from robin.prospective_observatory.r2 import ProspectiveR2Repository
from robin.providers.contracts import ProviderResult, QuotaState
from robin.storage.database import build_engine
from scripts.build_cockpit_snapshot import build_prospective_observatory
from scripts.run_prospective_observatory import (
    DirectoryObjectStore,
    MemoryOperationalState,
    ObservatoryPolicy,
    OddsFixtureIdentityError,
    SQLAlchemyOperationalState,
    _capture_payload_complete,
    _filter_fixtures,
    _match_odds_records,
    _provider_quota_remaining,
    _renormalize_r2_payload,
    run_capture,
    run_fixture_registry,
    run_gate_report,
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


def _cache(path: Path) -> Path:
    fixture_id = "api-football:9001"
    value = {
        "current_season": 2026,
        "fixtures": [_fixture_record(9001, NOW + timedelta(hours=1))],
        "payloads": {
            fixture_id: {
                "FIXTURE": [
                    _fixture_record(9001, NOW + timedelta(hours=1))
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
                            NOW + timedelta(hours=1)
                        ).isoformat(),
                        "bookmakers": [
                            {
                                "key": "book",
                                "markets": [
                                    {
                                        "key": "h2h",
                                        "outcomes": [
                                            {"name": "Home", "price": 2.0},
                                            {"name": "Draw", "price": 3.5},
                                            {"name": "Away", "price": 4.0},
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
) -> argparse.Namespace:
    return argparse.Namespace(
        command=command_name,
        policy=POLICY,
        output=output,
        now=NOW.isoformat(),
        code_revision="test-revision",
        cache=cache,
        object_store_root=object_store_root,
        estimate=False,
        execute=False,
        estimate_file=None,
        competition="Ligue 1",
        max_attempts=3,
        max_objects=250,
    )


def _migrated_engine(path: Path, monkeypatch: object) -> object:
    database_url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", database_url)  # type: ignore[attr-defined]
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    return build_engine(database_url)


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
    with pytest.raises(BudgetExceeded, match="PROSPECTIVE_PROVIDER_CAP_EXCEEDED"):
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
    assert second["status"] == "NO_CAPTURE_DUE"
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
    assert replay["objects_examined"] == 262
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
    run_scheduler(_args("scheduler", output=output), state=state)
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
    run_gate_report(_args("gate-report", output=output), state=state)
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
    assert second_replay["observatory"]["postgresql"]["inserts"] == 0
    assert second_replay["observatory"]["postgresql"]["duplicates_avoided"] > 0
    assert second_replay["observatory"]["postgresql"]["payload_body_rows"] == 0
    assert second_replay["observatory"]["postgresql"]["tables"] == 12
    with rebuilt_engine.connect() as connection:  # type: ignore[attr-defined]
        for table_name in (
            "prospective_fixtures",
            "capture_windows",
            "prospective_injuries",
            "prospective_lineups",
            "prospective_formations",
            "prospective_odds_snapshots",
        ):
            table = Table(table_name, MetaData(), autoload_with=rebuilt_engine)
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() > 0


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
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(output))  # type: ignore[attr-defined]
    cockpit = build_prospective_observatory()
    assert cockpit["origin"] == "LIVE_PROSPECTIVE_CAPTURE"
    assert cockpit["captures"]["attempted"] > 0
    assert cockpit["providers"]["api_football_calls"] == 4
    assert cockpit["ledger"]["events"] > 0


def test_exhausted_windows_make_no_fourth_provider_call(
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

    for expected_attempt in (1, 2, 3):
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
    fourth = _execute_capture(
        "capture-general",
        output=output,
        state=state,
        repository=repository,
        provider=unused_provider,
    )
    assert fourth["status"] == "NO_CAPTURE_DUE"
    assert unused_provider.status_calls == 0
    assert unused_provider.fixture_calls == 0
