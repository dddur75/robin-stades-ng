from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from robin.prospective_observatory.budgets import (
    BudgetEntry,
    ProviderKind,
)
from robin.prospective_observatory.contracts import (
    CaptureFamily,
    ProspectiveFixture,
    canonical_sha256,
)
from robin.prospective_observatory.multi_league import (
    CaptureProfile,
    LeagueActivationStatus,
    ScopedBudgetUsage,
    active_competitions,
    authorize_scoped_budget,
    labels_for_profile,
    prioritize_odds_windows,
)
from scripts import run_five_league_expansion as expansion
from scripts.run_prospective_observatory import (
    MemoryOperationalState,
    ObservatoryPolicy,
    _prospective_fixture,
    run_scheduler,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "configs" / "prospective_observatory_v1.json"
NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _policy() -> dict[str, object]:
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _fixture(competition: str, fixture_id: int) -> ProspectiveFixture:
    return ProspectiveFixture(
        fixture_id=f"api-football:{fixture_id}",
        competition=competition,
        season="2026",
        phase="Regular Season - 1",
        home_team_id=f"{fixture_id}1",
        away_team_id=f"{fixture_id}2",
        kickoff_at=NOW + timedelta(days=8),
        provider="api-football",
        provider_fixture_id=str(fixture_id),
        registered_at=NOW,
        code_revision="test",
    )


def test_registry_contains_exactly_five_active_leagues_and_profiles() -> None:
    registry = active_competitions(_policy())
    assert [(item.competition, item.provider_id) for item in registry] == [
        ("Ligue 1", 61),
        ("Premier League", 39),
        ("Liga", 140),
        ("Bundesliga", 78),
        ("Serie A", 135),
    ]
    assert registry[0].capture_profile is CaptureProfile.FULL
    assert {
        item.capture_profile for item in registry[1:]
    } == {CaptureProfile.DEEP_FULL_ODDS_REDUCED}
    assert len({item.odds_sport_key for item in registry}) == 5


def test_registry_horizon_is_extended_without_changing_matchday_cap() -> None:
    policy = _policy()
    fixture_registry = policy["fixture_registry"]
    assert isinstance(fixture_registry, dict)
    assert fixture_registry["horizon_days"] == 45
    assert fixture_registry["max_matchdays_per_competition"] == 3


def test_discovery_horizon_is_not_part_of_fixture_business_identity() -> None:
    fixture = _fixture("Liga", 14_000)
    assert fixture.model_copy(update={"horizon_days": 30}).business_hash == (
        fixture.model_copy(update={"horizon_days": 45}).business_hash
    )


def test_registry_gate_distinguishes_waiting_horizon_and_provider_error() -> None:
    policy = ObservatoryPolicy.load(POLICY_PATH)
    liga = next(
        item
        for item in active_competitions(policy.value)
        if item.competition == "Liga"
    )
    base = {
        "fixtures_valid": 0,
        "identity_slots_verified": 0,
        "identity_slots_expected": 0,
        "quota_remaining": 6_000,
        "provider_response_valid": True,
        "provider_payload_schema_errors": 0,
    }
    assert expansion._activation_from_registry_report(
        {
            **base,
            "fixtures_received": 0,
            "records_in_current_horizon": 0,
            "records_outside_current_horizon": 0,
        },
        competition=liga,
        provider_reserve=5_000,
    ) is LeagueActivationStatus.WAITING_FOR_FIXTURES
    assert expansion._activation_from_registry_report(
        {
            **base,
            "fixtures_received": 2,
            "records_in_current_horizon": 0,
            "records_outside_current_horizon": 2,
        },
        competition=liga,
        provider_reserve=5_000,
    ) is LeagueActivationStatus.NO_FIXTURES_IN_CURRENT_HORIZON
    assert expansion._activation_from_registry_report(
        {
            **base,
            "fixtures_received": 1,
            "records_in_current_horizon": 1,
            "records_outside_current_horizon": 0,
            "provider_payload_schema_errors": 1,
        },
        competition=liga,
        provider_reserve=5_000,
    ) is LeagueActivationStatus.BLOCKED_PROVIDER_ERROR


def test_targeted_registry_estimate_never_spends_on_other_leagues(
    tmp_path: Path,
) -> None:
    report = expansion.run_registry(
        argparse.Namespace(
            policy=POLICY_PATH,
            output=tmp_path,
            now=NOW.isoformat(),
            code_revision="test",
            estimate=True,
            execute=False,
            estimate_file=None,
            competition="Bundesliga",
        )
    )
    assert report["competition_scope"] == "Bundesliga"
    assert report["estimated_calls"] == 3
    assert report["odds_api_credits"] == 0
    assert [
        row["competition"]
        for row in report["competitions"]  # type: ignore[union-attr]
    ] == ["Bundesliga"]


def test_waiting_league_activates_and_schedules_without_code_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimate_args = argparse.Namespace(
        policy=POLICY_PATH,
        output=tmp_path,
        now=NOW.isoformat(),
        code_revision="same-revision",
        estimate=True,
        execute=False,
        estimate_file=None,
        competition="Liga",
    )
    estimate = expansion.run_registry(estimate_args)
    policy_hash = estimate["policy_sha256"]
    state = MemoryOperationalState()
    monkeypatch.setattr(expansion, "_database_state", lambda: state)
    monkeypatch.setattr(expansion, "_repository", lambda: object())
    executions = 0

    def fake_registry(
        args: argparse.Namespace,
        *,
        state: object,
        repository: object,
    ) -> dict[str, object]:
        nonlocal executions
        del repository
        if args.estimate:
            return {"status": "ESTIMATED"}
        assert isinstance(state, MemoryOperationalState)
        executions += 1
        for index in range(3):
            state.append_budget(
                idempotency_key=f"liga-cycle-{executions}-{index}",
                provider=ProviderKind.API_FOOTBALL,
                units=1,
                provider_remaining=6_000 - index,
                provider_reserve=5_000,
                recorded_at=NOW + timedelta(minutes=executions),
                reason="RESERVED_BEFORE_PROVIDER_CALL:registry;SCOPE=Liga",
                code_revision="same-revision",
            )
        fixtures_valid = int(executions > 1)
        if fixtures_valid:
            fixture = _fixture("Liga", 14_001)
            state.fixture_rows[fixture.fixture_id] = (
                fixture.registry_hash,
                fixture,
            )
        return {
            "provider_season": 2026,
            "fixtures_received": fixtures_valid,
            "provider_response_valid": True,
            "provider_response_empty": fixtures_valid == 0,
            "records_in_current_horizon": fixtures_valid,
            "records_outside_current_horizon": 0,
            "provider_payload_schema_errors": 0,
            "fixtures_valid": fixtures_valid,
            "identity_slots_verified": fixtures_valid * 2,
            "identity_slots_expected": fixtures_valid * 2,
            "teams_verified": fixtures_valid * 2,
            "kickoffs_reliable": fixtures_valid,
            "provider_calls": 3,
            "quota_remaining": 6_000,
            "observatory": {
                "r2": {"objects_added": fixtures_valid * 2, "bytes": 100},
                "postgresql": {
                    "inserts": fixtures_valid,
                    "duplicates_avoided": 0,
                },
            },
        }

    monkeypatch.setattr(expansion, "run_fixture_registry", fake_registry)
    execute_args = argparse.Namespace(
        **{
            **vars(estimate_args),
            "estimate": False,
            "execute": True,
            "estimate_file": tmp_path
            / "five-league-registry-estimate.json",
        }
    )
    waiting = expansion.run_registry(execute_args)
    activated = expansion.run_registry(execute_args)
    assert waiting["policy_sha256"] == activated["policy_sha256"] == policy_hash
    assert waiting["leagues"][0]["gate"] == (  # type: ignore[index]
        LeagueActivationStatus.WAITING_FOR_FIXTURES.value
    )
    assert activated["leagues"][0]["gate"] == (  # type: ignore[index]
        LeagueActivationStatus.ACTIVE_ODDS_REDUCED.value
    )
    assert activated["odds_api_credits"] == 0

    scheduler_args = argparse.Namespace(
        policy=POLICY_PATH,
        output=tmp_path,
        now=NOW.isoformat(),
        code_revision="same-revision",
        cache=None,
        object_store_root=None,
    )
    first_plan = run_scheduler(scheduler_args, state=state)
    second_plan = run_scheduler(scheduler_args, state=state)
    assert first_plan["windows_inserted"] > 0
    assert second_plan["windows_inserted"] == 0
    assert second_plan["duplicates_avoided"] == first_plan["windows_inserted"]


def test_reduced_profile_keeps_all_deep_families_but_only_three_odds_windows() -> None:
    canonical = ("J-7", "J-3", "J-1", "H-6", "H-2", "NEAR_KICKOFF")
    assert labels_for_profile(
        CaptureProfile.DEEP_FULL_ODDS_REDUCED,
        CaptureFamily.ODDS,
        canonical,
    ) == ("J-1", "H-2", "NEAR_KICKOFF")
    assert labels_for_profile(
        CaptureProfile.DEEP_FULL_ODDS_REDUCED,
        CaptureFamily.INJURY,
        canonical,
    ) == canonical
    assert labels_for_profile(
        CaptureProfile.FIXTURE_ONLY,
        CaptureFamily.SQUAD,
        canonical,
    ) == ()


def test_scheduler_applies_competition_profile_without_hardcoded_fixture_data(
    tmp_path: Path,
) -> None:
    state = MemoryOperationalState()
    state.fixture_rows = {
        fixture.fixture_id: (fixture.registry_hash, fixture)
        for fixture in (
            _fixture("Ligue 1", 1),
            _fixture("Premier League", 2),
        )
    }
    args = argparse.Namespace(
        policy=POLICY_PATH,
        output=tmp_path,
        now=NOW.isoformat(),
        code_revision="test",
        cache=None,
        object_store_root=None,
    )
    run_scheduler(args, state=state)
    fixture_by_id = {
        fixture.fixture_id: fixture for fixture in state.fixtures()
    }
    odds_labels: dict[str, set[str]] = {}
    for window in state.windows():
        if window.family is CaptureFamily.ODDS:
            competition = fixture_by_id[window.fixture_id].competition
            odds_labels.setdefault(competition, set()).add(window.label)
    assert odds_labels["Ligue 1"] == {
        "J-7",
        "J-3",
        "J-1",
        "H-6",
        "H-2",
        "NEAR_KICKOFF",
    }
    assert odds_labels["Premier League"] == {
        "J-1",
        "H-2",
        "NEAR_KICKOFF",
    }


def test_adaptive_budgets_fail_closed_per_run_day_league_week_and_season() -> None:
    policy = _policy()
    allowed = authorize_scoped_budget(
        policy=policy,
        provider="api_football",
        competition="Liga",
        estimated_units=3,
        provider_remaining=6_000,
    )
    assert allowed.allowed is True
    assert allowed.provider_reserve == 5_000

    blocked_league = authorize_scoped_budget(
        policy=policy,
        provider="api_football",
        competition="Liga",
        estimated_units=3,
        provider_remaining=6_000,
        usage=ScopedBudgetUsage(competition_day=239),
    )
    assert blocked_league.allowed is False
    assert blocked_league.reason == "BLOCKED_COMPETITION_DAILY_BUDGET"

    blocked_week = authorize_scoped_budget(
        policy=policy,
        provider="odds_api",
        competition="Serie A",
        estimated_units=2,
        provider_remaining=5_000,
        usage=ScopedBudgetUsage(week=599),
    )
    assert blocked_week.allowed is False
    assert blocked_week.reason == "BLOCKED_WEEKLY_BUDGET"

    blocked_reserve = authorize_scoped_budget(
        policy=policy,
        provider="api_football",
        competition="Bundesliga",
        estimated_units=3,
        provider_remaining=5_002,
    )
    assert blocked_reserve.allowed is False
    assert blocked_reserve.reason == "BLOCKED_PROVIDER_RESERVE"


def test_odds_budget_sheds_distant_windows_in_required_priority_order() -> None:
    kept, shed = prioritize_odds_windows(
        ("J-7", "J-3", "J-1", "H-6", "H-2", "NEAR_KICKOFF"),
        maximum_units=6,
    )
    assert kept == ("NEAR_KICKOFF", "H-2", "J-1")
    assert shed == ("H-6", "J-3", "J-7")


def test_postponed_fixture_is_retained_as_an_immutable_tombstone() -> None:
    record = {
        "fixture": {
            "id": 100,
            "date": (NOW + timedelta(days=2)).isoformat(),
            "status": {"short": "PST"},
        },
        "league": {"season": 2026, "round": "Regular Season - 1"},
        "teams": {
            "home": {"id": 1, "name": "Home"},
            "away": {"id": 2, "name": "Away"},
        },
    }
    fixture = _prospective_fixture(
        record,
        competition="Liga",
        registered_at=NOW,
        code_revision="test",
        horizon_days=30,
        excluded_statuses={"PST"},
        require_verified_phase=True,
        require_reliable_utc_kickoff=True,
    )
    assert fixture is not None
    assert fixture.cancelled is True


def test_provider_fixture_before_registry_time_is_skipped_not_fatal() -> None:
    record = {
        "fixture": {
            "id": 101,
            "date": (NOW - timedelta(hours=2)).isoformat(),
            "status": {"short": "NS"},
        },
        "league": {"season": 2026, "round": "Regular Season - 1"},
        "teams": {
            "home": {"id": 1, "name": "Home"},
            "away": {"id": 2, "name": "Away"},
        },
    }
    assert _prospective_fixture(
        record,
        competition="Liga",
        registered_at=NOW,
        code_revision="test",
        horizon_days=30,
        excluded_statuses={"PST"},
        require_verified_phase=True,
        require_reliable_utc_kickoff=True,
    ) is None


def test_registry_pilot_isolates_one_league_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    estimate_args = argparse.Namespace(
        policy=POLICY_PATH,
        output=tmp_path,
        now=NOW.isoformat(),
        code_revision="test",
        estimate=True,
        execute=False,
        estimate_file=None,
    )
    expansion.run_registry(estimate_args)

    state = MemoryOperationalState()
    repository = object()
    monkeypatch.setattr(expansion, "_database_state", lambda: state)
    monkeypatch.setattr(expansion, "_repository", lambda: repository)

    def fake_registry(
        args: argparse.Namespace,
        *,
        state: object,
        repository: object,
    ) -> dict[str, object]:
        del repository
        if args.estimate:
            return {"status": "ESTIMATED"}
        assert isinstance(state, MemoryOperationalState)
        reserved_calls = 2 if args.competition == "Liga" else 3
        for index in range(reserved_calls):
            state.append_budget(
                idempotency_key=(
                    f"{args.competition}:provider-step:{index}"
                ),
                provider=ProviderKind.API_FOOTBALL,
                units=1,
                provider_remaining=6_000 - index,
                provider_reserve=5_000,
                recorded_at=NOW,
                reason=(
                    "RESERVED_BEFORE_PROVIDER_CALL:registry;"
                    f"SCOPE={args.competition}"
                ),
                code_revision="test",
            )
        if args.competition == "Liga":
            raise RuntimeError("SIMULATED_PROVIDER_FAILURE")
        return {
            "provider_season": 2026,
            "fixtures_received": 10,
            "fixtures_valid": 1,
            "identity_slots_verified": 2,
            "identity_slots_expected": 2,
            "teams_verified": 2,
            "kickoffs_reliable": 1,
            "provider_calls": 3,
            "quota_remaining": 6_000,
            "observatory": {
                "r2": {"objects_added": 2, "bytes": 100},
                "postgresql": {
                    "inserts": 1,
                    "duplicates_avoided": 0,
                },
            },
        }

    monkeypatch.setattr(expansion, "run_fixture_registry", fake_registry)
    execute_args = argparse.Namespace(
        **{
            **vars(estimate_args),
            "estimate": False,
            "execute": True,
            "estimate_file": tmp_path
            / "five-league-registry-estimate.json",
        }
    )
    report = expansion.run_registry(execute_args)
    assert report["status"] == "FIVE_LEAGUE_REGISTRY_PILOT_PARTIAL"
    assert report["competitions_active"] == 4
    assert report["provider_calls"] == 14
    rows = {
        row["competition"]: row
        for row in report["leagues"]  # type: ignore[union-attr]
    }
    assert rows["Liga"]["gate"] == (
        LeagueActivationStatus.BLOCKED_PROVIDER_ERROR.value
    )
    assert rows["Liga"]["provider_calls"] == 2
    assert rows["Premier League"]["gate"] == (
        LeagueActivationStatus.ACTIVE_ODDS_REDUCED.value
    )


def test_cost_projection_is_bounded_and_never_authorizes_promotion() -> None:
    report = expansion.build_cost_projection(
        ObservatoryPolicy.load(POLICY_PATH)
    )
    assert report["within_configured_season_api_cap"] is True
    assert report["promotion_authorized"] is False
    totals = report["totals"]
    assert isinstance(totals, dict)
    assert totals["fixtures"] == 1_752
    assert totals["odds_api_credits_per_week_average"] < 600
    assert totals["bytes"] is None
    assert totals["storage_cost"] is None
    assert report["budgets"] == _policy()["provider_budgets"]


def test_schedule_wait_is_ready_only_with_four_active_leagues() -> None:
    assert expansion._expansion_verdict(
        active=5,
        waiting=0,
        replay_green=True,
        postgres_green=True,
    ) == "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY"
    assert expansion._expansion_verdict(
        active=4,
        waiting=1,
        replay_green=True,
        postgres_green=True,
    ) == "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY_WITH_SCHEDULE_WAIT"
    assert expansion._expansion_verdict(
        active=3,
        waiting=2,
        replay_green=True,
        postgres_green=True,
    ) == "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL"
    assert expansion._expansion_verdict(
        active=4,
        waiting=1,
        replay_green=False,
        postgres_green=True,
    ) == "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL"


def test_provider_free_summary_uses_durable_scoped_budget_and_all_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = ObservatoryPolicy.load(POLICY_PATH)
    competitions = active_competitions(policy.value)
    fixtures = tuple(
        SimpleNamespace(
            fixture_id=f"fixture-{index}",
            competition=competition.competition,
            kickoff_at=NOW + timedelta(days=index + 1),
            home_team_id=f"home-{index}",
            away_team_id=f"away-{index}",
        )
        for index, competition in enumerate(competitions)
    )
    budget_entries = tuple(
        BudgetEntry(
            idempotency_key=f"budget-{index}",
            provider=ProviderKind.API_FOOTBALL,
            units=3,
            recorded_at=NOW,
            reason=(
                "RESERVED_BEFORE_PROVIDER_CALL:registry;"
                f"SCOPE={competition.competition}"
            ),
        )
        for index, competition in enumerate(competitions)
    )
    state = SimpleNamespace(
        fixtures=lambda: fixtures,
        receipts=lambda: (),
        budget_entries=lambda: budget_entries,
    )
    identities = {
        fixture.fixture_id: ("Home", "Away", fixture.kickoff_at)
        for fixture in fixtures
    }
    monkeypatch.setattr(expansion, "_database_state", lambda: state)
    monkeypatch.setattr(expansion, "_repository", lambda: object())
    monkeypatch.setattr(expansion, "_fixture_identities", lambda _: identities)
    monkeypatch.setattr(expansion, "_active_windows", lambda _: ())

    replay = {
        "command": "replay-audit",
        "policy_sha256": policy.sha256,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "status": "R2_REPLAY_VERIFIED",
        "data_loss": 0,
        "deletions": 0,
        "physical_unique_objects": 15,
        "physical_unique_bytes": 1_500,
        "observatory": {"r2": {"lag": 0}},
    }
    replay["report_sha256"] = canonical_sha256(replay)
    gate = {
        "command": "gate-report",
        "policy_sha256": policy.sha256,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "observatory": {"postgresql": {"payload_body_rows": 0}},
    }
    gate["report_sha256"] = canonical_sha256(gate)
    replay_path = tmp_path / "r2-replay-audit.json"
    gate_path = tmp_path / "gate-report.json"
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    report = expansion.run_summary(
        argparse.Namespace(
            policy=POLICY_PATH,
            output=tmp_path,
            now=NOW.isoformat(),
            registry_report=tmp_path / "missing-registry.json",
            replay_report=replay_path,
            gate_report=gate_path,
        )
    )
    assert report["verdict"] == "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY"
    assert report["competitions_active"] == 5
    assert report["provider_calls_for_summary"] == 0
    assert report["odds_api_credits_for_summary"] == 0
    rows = report["leagues"]
    assert isinstance(rows, list)
    assert {row["api_football_calls"] for row in rows} == {3}
    assert {row["odds_api_credits"] for row in rows} == {0}
    assert rows[0]["fixtures_from"] is not None
    assert report["model_promotion_authorized"] is False
