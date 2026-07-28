"""Bounded five-league registry pilot, replay summary and cost projection."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from robin.prospective_observatory.budgets import ProviderKind
from robin.prospective_observatory.contracts import (
    CaptureWindow,
    canonical_sha256,
)
from robin.prospective_observatory.multi_league import (
    CaptureProfile,
    CompetitionPolicy,
    LeagueActivationStatus,
    active_competitions,
)

try:
    from scripts.run_prospective_observatory import (
        ObservatoryPolicy,
        _active_windows,
        _budget_scope,
        _database_state,
        _fixture_identities,
        _repository,
        run_fixture_registry,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from run_prospective_observatory import (  # type: ignore[import-not-found,no-redef]
        ObservatoryPolicy,
        _active_windows,
        _budget_scope,
        _database_state,
        _fixture_identities,
        _repository,
        run_fixture_registry,
    )

DEFAULT_POLICY = Path("configs/prospective_observatory_v1.json")
DEFAULT_OUTPUT = Path("artifacts/prospective-observatory")
FIXTURES_PER_SEASON = {
    "Ligue 1": 306,
    "Premier League": 380,
    "Liga": 380,
    "Bundesliga": 306,
    "Serie A": 380,
}
MATCHDAYS_PER_SEASON = {
    "Ligue 1": 34,
    "Premier League": 38,
    "Liga": 38,
    "Bundesliga": 34,
    "Serie A": 38,
}


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("FIVE_LEAGUE_REPORT_INVALID")
    return cast(dict[str, object], value)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _verify_signed_report(
    report: Mapping[str, object],
    *,
    policy: ObservatoryPolicy,
    command: str | None = None,
) -> None:
    unsigned = dict(report)
    report_sha256 = unsigned.pop("report_sha256", None)
    if (
        not isinstance(report_sha256, str)
        or report_sha256 != canonical_sha256(unsigned)
        or report.get("policy_sha256") != policy.sha256
        or report.get("production_status") != "PRODUCTION_LOCKED"
        or report.get("real_bets") is not False
        or (command is not None and report.get("command") != command)
    ):
        raise ValueError("FIVE_LEAGUE_SOURCE_REPORT_INVALID")


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NOW_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _selected_competitions(
    policy: ObservatoryPolicy,
    selection: str | None,
) -> tuple[CompetitionPolicy, ...]:
    competitions = active_competitions(policy.value)
    if selection is None or selection.strip().upper() == "ALL":
        return competitions
    selected = tuple(
        item for item in competitions if item.competition == selection.strip()
    )
    if len(selected) != 1:
        raise ValueError("FIVE_LEAGUE_COMPETITION_SCOPE_INVALID")
    return selected


def _estimate(
    policy: ObservatoryPolicy,
    *,
    now: datetime,
    competition: str | None,
) -> dict[str, object]:
    competitions = _selected_competitions(policy, competition)
    rows = [
        {
            "competition": item.competition,
            "provider_id": item.provider_id,
            "capture_profile": item.capture_profile.value,
            "estimated_calls": 3,
            "max_initial_calls": 3,
        }
        for item in competitions
    ]
    estimated_calls = sum(int(row["estimated_calls"]) for row in rows)
    api_budget = policy.provider_budget(ProviderKind.API_FOOTBALL)
    estimate: dict[str, object] = {
        "schema_version": "five-league-registry-estimate-v1",
        "generated_at": now.isoformat(),
        "policy_sha256": policy.sha256,
        "competition_scope": (
            "ALL" if len(competitions) == 5 else competitions[0].competition
        ),
        "competitions": rows,
        "estimated_calls": estimated_calls,
        "run_cap": api_budget["per_run"],
        "daily_cap": api_budget["per_day"],
        "provider_reserve": api_budget["provider_reserve"],
        "authorized_by_static_caps": (
            estimated_calls <= int(str(api_budget["per_run"]))
            and all(
                int(row["estimated_calls"])
                <= int(str(api_budget["per_competition_per_run"]))
                for row in rows
            )
        ),
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
    }
    estimate["estimate_sha256"] = canonical_sha256(estimate)
    return estimate


def _verified_estimate(
    path: Path,
    *,
    policy: ObservatoryPolicy,
    competition: str | None,
) -> dict[str, object]:
    recorded = _read_json(path)
    recorded_hash = recorded.pop("estimate_sha256", None)
    if recorded_hash != canonical_sha256(recorded):
        raise ValueError("FIVE_LEAGUE_ESTIMATE_HASH_INVALID")
    generated_at = recorded.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("FIVE_LEAGUE_ESTIMATE_TIMESTAMP_INVALID")
    expected = _estimate(
        policy,
        now=_parse_now(generated_at),
        competition=competition,
    )
    if recorded != {
        key: value
        for key, value in expected.items()
        if key != "estimate_sha256"
    }:
        raise ValueError("FIVE_LEAGUE_ESTIMATE_SCOPE_CHANGED")
    if recorded.get("authorized_by_static_caps") is not True:
        raise ValueError("FIVE_LEAGUE_ESTIMATE_NOT_AUTHORIZED")
    recorded["estimate_sha256"] = recorded_hash
    return recorded


def _scoped_budget_units(
    state: object,
    *,
    provider: ProviderKind,
    competition: str,
) -> int | None:
    reader = getattr(state, "budget_entries", None)
    if not callable(reader):
        return None
    return int(
        sum(
        entry.units
        for entry in reader()
        if entry.provider is provider
        and entry.units > 0
        and _budget_scope(entry.reason) == competition
        )
    )


def _provider_remaining(
    state: object,
    *,
    now: datetime,
) -> int | None:
    reader = getattr(state, "external_quota_remaining", None)
    if not callable(reader):
        return None
    value = reader(ProviderKind.API_FOOTBALL, now=now)
    return value if isinstance(value, int) and value >= 0 else None


def _compact_error_details(error: Exception) -> list[dict[str, object]]:
    reader = getattr(error, "errors", None)
    if not callable(reader):
        return []
    details: list[dict[str, object]] = []
    for item in reader():
        if not isinstance(item, Mapping):
            continue
        location = item.get("loc")
        details.append(
            {
                "type": str(item.get("type", "VALIDATION_ERROR"))[:120],
                "location": (
                    [str(value)[:80] for value in location]
                    if isinstance(location, tuple | list)
                    else []
                ),
            }
        )
    return details[:10]


def _activation_from_registry_report(
    report: Mapping[str, object],
    *,
    competition: CompetitionPolicy,
    provider_reserve: int,
) -> LeagueActivationStatus:
    fixtures = int(str(report.get("fixtures_valid", 0)))
    identities = int(str(report.get("identity_slots_verified", 0)))
    expected_identities = int(
        str(report.get("identity_slots_expected", 0))
    )
    schema_errors = int(
        str(report.get("provider_payload_schema_errors", 0))
    )
    received = int(str(report.get("fixtures_received", 0)))
    in_horizon = int(
        str(report.get("records_in_current_horizon", received))
    )
    outside_horizon = int(
        str(report.get("records_outside_current_horizon", 0))
    )
    quota_remaining = int(str(report.get("quota_remaining", 0)))
    if report.get("provider_response_valid") is False or schema_errors:
        return LeagueActivationStatus.BLOCKED_PROVIDER_ERROR
    if fixtures == 0:
        if received == 0:
            return LeagueActivationStatus.WAITING_FOR_FIXTURES
        if outside_horizon > 0 and in_horizon == 0:
            return LeagueActivationStatus.NO_FIXTURES_IN_CURRENT_HORIZON
        return LeagueActivationStatus.WAITING_FOR_FIXTURES
    if identities != expected_identities:
        return LeagueActivationStatus.BLOCKED_IDENTITY
    if quota_remaining < provider_reserve:
        return LeagueActivationStatus.BLOCKED_BUDGET
    return competition.expected_active_status


def _activation_from_exception(
    error: Exception,
) -> LeagueActivationStatus | None:
    message = f"{type(error).__name__}:{error}".upper()
    if "BUDGET" in message or "RESERVE" in message:
        return LeagueActivationStatus.BLOCKED_BUDGET
    if any(
        marker in message
        for marker in (
            "API_FOOTBALL",
            "PROVIDER",
            "HTTP",
            "AUTH",
            "TIMEOUT",
        )
    ):
        return LeagueActivationStatus.BLOCKED_PROVIDER_ERROR
    return None


def _child_args(
    args: argparse.Namespace,
    *,
    competition: str,
    output: Path,
    estimate: bool,
    execute: bool,
    estimate_file: Path | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="fixture-registry",
        policy=args.policy,
        output=output,
        now=args.now,
        code_revision=args.code_revision,
        cache=None,
        object_store_root=None,
        estimate=estimate,
        execute=execute,
        estimate_file=estimate_file,
        competition=competition,
        max_attempts=1,
    )


def run_registry(args: argparse.Namespace) -> dict[str, object]:
    now = _parse_now(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    competition_scope = getattr(args, "competition", None)
    competitions = _selected_competitions(policy, competition_scope)
    estimate = _estimate(
        policy,
        now=now,
        competition=competition_scope,
    )
    estimate_path = args.output / "five-league-registry-estimate.json"
    if args.estimate:
        _write_json(estimate_path, estimate)
        return estimate
    if not args.execute or args.estimate_file is None:
        raise ValueError("FIVE_LEAGUE_REGISTRY_EXECUTION_REQUIRES_ESTIMATE")
    _verified_estimate(
        args.estimate_file,
        policy=policy,
        competition=competition_scope,
    )

    state = _database_state()
    repository = _repository()
    league_rows: list[dict[str, object]] = []
    provider_calls = 0
    r2_objects = 0
    r2_bytes = 0
    postgresql_inserts = 0
    for competition in competitions:
        child_output = args.output / ".five-league" / competition.competition
        child_estimate = child_output / "fixture-registry-estimate.json"
        calls_before = _scoped_budget_units(
            state,
            provider=ProviderKind.API_FOOTBALL,
            competition=competition.competition,
        )
        try:
            run_fixture_registry(
                _child_args(
                    args,
                    competition=competition.competition,
                    output=child_output,
                    estimate=True,
                    execute=False,
                    estimate_file=None,
                ),
                state=state,
                repository=repository,
            )
            report = run_fixture_registry(
                _child_args(
                    args,
                    competition=competition.competition,
                    output=child_output,
                    estimate=False,
                    execute=True,
                    estimate_file=child_estimate,
                ),
                state=state,
                repository=repository,
            )
            observatory = report.get("observatory")
            if not isinstance(observatory, Mapping):
                raise RuntimeError("FIVE_LEAGUE_CHILD_OBSERVATORY_INVALID")
            r2 = observatory.get("r2")
            postgresql = observatory.get("postgresql")
            if not isinstance(r2, Mapping) or not isinstance(postgresql, Mapping):
                raise RuntimeError("FIVE_LEAGUE_CHILD_STORAGE_INVALID")
            quota_remaining = int(str(report.get("quota_remaining", 0)))
            fixtures = int(str(report.get("fixtures_valid", 0)))
            identities = int(str(report.get("identity_slots_verified", 0)))
            expected_identities = int(
                str(report.get("identity_slots_expected", 0))
            )
            gate = _activation_from_registry_report(
                report,
                competition=competition,
                provider_reserve=policy.provider_reserve(
                    ProviderKind.API_FOOTBALL
                ),
            )
            calls_after = _scoped_budget_units(
                state,
                provider=ProviderKind.API_FOOTBALL,
                competition=competition.competition,
            )
            calls = (
                calls_after - calls_before
                if calls_before is not None and calls_after is not None
                else int(str(report.get("provider_calls", 0)))
            )
            if not 0 <= calls <= 3:
                raise RuntimeError("FIVE_LEAGUE_CALL_BOUND_VIOLATED")
            provider_calls += calls
            r2_objects += int(str(r2.get("objects_added", 0)))
            r2_bytes += int(str(r2.get("bytes", 0)))
            postgresql_inserts += int(str(postgresql.get("inserts", 0)))
            league_rows.append(
                {
                    "competition": competition.competition,
                    "provider_id": competition.provider_id,
                    "season": report.get("provider_season"),
                    "horizon_from": report.get("horizon_from"),
                    "horizon_to": report.get("horizon_to"),
                    "capture_profile": competition.capture_profile.value,
                    "fixtures_received": report.get("fixtures_received", 0),
                    "provider_response_valid": report.get(
                        "provider_response_valid",
                        True,
                    ),
                    "provider_response_empty": report.get(
                        "provider_response_empty",
                        False,
                    ),
                    "records_in_current_horizon": report.get(
                        "records_in_current_horizon",
                        report.get("fixtures_received", 0),
                    ),
                    "records_outside_current_horizon": report.get(
                        "records_outside_current_horizon",
                        0,
                    ),
                    "provider_payload_schema_errors": report.get(
                        "provider_payload_schema_errors",
                        0,
                    ),
                    "fixtures": fixtures,
                    "teams": report.get("teams_verified", 0),
                    "identity_slots_verified": identities,
                    "identity_slots_expected": expected_identities,
                    "kickoffs_reliable": report.get("kickoffs_reliable", 0),
                    "provider_calls": calls,
                    "quota_remaining": quota_remaining,
                    "r2_objects_added": r2.get("objects_added", 0),
                    "r2_bytes": r2.get("bytes", 0),
                    "postgresql_inserts": postgresql.get("inserts", 0),
                    "duplicates_avoided": postgresql.get(
                        "duplicates_avoided",
                        0,
                    ),
                    "gate": gate.value,
                    "error": None,
                    "error_details": [],
                }
            )
        except Exception as error:  # isolate one league without hiding evidence
            calls_after = _scoped_budget_units(
                state,
                provider=ProviderKind.API_FOOTBALL,
                competition=competition.competition,
            )
            calls = (
                calls_after - calls_before
                if calls_before is not None and calls_after is not None
                else 0
            )
            if not 0 <= calls <= 3:
                raise RuntimeError(
                    "FIVE_LEAGUE_CALL_BOUND_VIOLATED"
                ) from error
            error_gate = _activation_from_exception(error)
            if error_gate is None:
                raise
            provider_calls += calls
            league_rows.append(
                {
                    "competition": competition.competition,
                    "provider_id": competition.provider_id,
                    "season": None,
                    "capture_profile": competition.capture_profile.value,
                    "fixtures_received": 0,
                    "fixtures": 0,
                    "teams": 0,
                    "identity_slots_verified": 0,
                    "identity_slots_expected": 0,
                    "kickoffs_reliable": 0,
                    "provider_calls": calls,
                    "quota_remaining": _provider_remaining(state, now=now),
                    "r2_objects_added": 0,
                    "r2_bytes": 0,
                    "postgresql_inserts": 0,
                    "duplicates_avoided": 0,
                    "gate": error_gate.value,
                    "error": type(error).__name__,
                    "error_details": _compact_error_details(error),
                }
            )

    active = sum(
        row["gate"]
        in {
            LeagueActivationStatus.ACTIVE_FULL.value,
            LeagueActivationStatus.ACTIVE_ODDS_REDUCED.value,
        }
        for row in league_rows
    )
    waiting_statuses = {
        LeagueActivationStatus.WAITING_FOR_FIXTURES.value,
        LeagueActivationStatus.NO_FIXTURES_IN_CURRENT_HORIZON.value,
    }
    waiting = sum(row["gate"] in waiting_statuses for row in league_rows)
    status = (
        "FIVE_LEAGUE_REGISTRY_PILOT_VERIFIED"
        if active == len(league_rows)
        else (
            "FIVE_LEAGUE_REGISTRY_PILOT_READY_WITH_SCHEDULE_WAIT"
            if active + waiting == len(league_rows)
            else "FIVE_LEAGUE_REGISTRY_PILOT_PARTIAL"
        )
    )
    report = {
        "schema_version": "five-league-registry-pilot-v1",
        "generated_at": now.isoformat(),
        "policy_sha256": policy.sha256,
        "status": status,
        "competition_scope": (
            "ALL" if len(competitions) == 5 else competitions[0].competition
        ),
        "competitions_requested": len(competitions),
        "competitions_active": active,
        "competitions_waiting": waiting,
        "leagues": league_rows,
        "fixtures": sum(int(str(row["fixtures"])) for row in league_rows),
        "teams": sum(int(str(row["teams"])) for row in league_rows),
        "provider_calls": provider_calls,
        "max_provider_calls": 3 * len(competitions),
        "odds_api_credits": 0,
        "r2_objects_added": r2_objects,
        "r2_bytes": r2_bytes,
        "postgresql_inserts": postgresql_inserts,
        "deletions": 0,
        "raw_payloads_in_git": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
    }
    report["report_sha256"] = canonical_sha256(report)
    _write_json(args.output / "five-league-registry.json", report)
    return report


def build_cost_projection(policy: ObservatoryPolicy) -> dict[str, object]:
    competitions = active_competitions(policy.value)
    rows: list[dict[str, object]] = []
    api_total = 0
    odds_credits_total = 0
    semantic_windows_total = 0
    for competition in competitions:
        fixtures = FIXTURES_PER_SEASON[competition.competition]
        matchdays = MATCHDAYS_PER_SEASON[competition.competition]
        odds_windows = (
            6
            if competition.capture_profile is CaptureProfile.FULL
            else 3
        )
        semantic_windows = 49 - (6 - odds_windows)
        api_calls = fixtures * 30 + matchdays * 32
        odds_calls = matchdays * odds_windows
        odds_credits = odds_calls * 2
        api_total += api_calls
        odds_credits_total += odds_credits
        semantic_windows_total += fixtures * semantic_windows
        rows.append(
            {
                "competition": competition.competition,
                "capture_profile": competition.capture_profile.value,
                "fixtures": fixtures,
                "matchdays": matchdays,
                "semantic_windows": fixtures * semantic_windows,
                "api_football_calls": api_calls,
                "odds_windows": odds_windows,
                "odds_api_calls": odds_calls,
                "odds_api_credits": odds_credits,
            }
        )
    registry_calls = 365 * 3 * len(competitions)
    api_total += registry_calls
    known_receipts = semantic_windows_total + sum(FIXTURES_PER_SEASON.values())
    known_r2_objects = known_receipts * 3
    report: dict[str, object] = {
        "schema_version": "five-league-season-cost-projection-v1",
        "policy_sha256": policy.sha256,
        "assumptions": {
            "scenario": "central_without_retries",
            "registry_calls_per_league_day": 3,
            "api_calls_per_fixture": 30,
            "api_status_cohorts_per_matchday": 32,
            "odds_credits_per_competition_window": 2,
            "raw_payloads_in_git": 0,
            "r2_objects_per_capture": 3,
        },
        "leagues": rows,
        "totals": {
            "fixtures": sum(FIXTURES_PER_SEASON.values()),
            "registry_calls": registry_calls,
            "api_football_calls": api_total,
            "api_football_calls_per_day_average": round(api_total / 365, 2),
            "odds_api_credits": odds_credits_total,
            "odds_api_credits_per_week_average": round(
                odds_credits_total / 52,
                2,
            ),
            "semantic_windows": semantic_windows_total,
            "known_r2_objects": known_r2_objects,
            "known_postgresql_receipt_rows": known_receipts,
            "bytes": None,
            "storage_cost": None,
        },
        "budgets": policy.budgets,
        "within_configured_season_api_cap": (
            api_total
            <= int(
                str(
                    policy.provider_budget(
                        ProviderKind.API_FOOTBALL
                    )["per_season"]
                )
            )
        ),
        "promotion_authorized": False,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def _expansion_verdict(
    *,
    active: int,
    waiting: int,
    replay_green: bool,
    postgres_green: bool,
) -> str:
    if active == 5 and replay_green and postgres_green:
        return "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY"
    if (
        active == 4
        and waiting == 1
        and replay_green
        and postgres_green
    ):
        return "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY_WITH_SCHEDULE_WAIT"
    if active > 0:
        return "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL"
    return "FIVE_LEAGUE_PROSPECTIVE_EXPANSION_FAILED"


def run_summary(args: argparse.Namespace) -> dict[str, object]:
    policy = ObservatoryPolicy.load(args.policy)
    summary_now = _parse_now(args.now)
    registry = (
        _read_json(args.registry_report)
        if args.registry_report.exists()
        else {"leagues": [], "report_sha256": None}
    )
    replay = _read_json(args.replay_report)
    gate = _read_json(args.gate_report)
    _verify_signed_report(replay, policy=policy, command="replay-audit")
    _verify_signed_report(gate, policy=policy, command="gate-report")
    if registry.get("report_sha256") is not None:
        _verify_signed_report(registry, policy=policy)
    state = _database_state()
    repository = _repository()
    fixtures = tuple(state.fixtures())
    receipts = tuple(state.receipts())
    identities = _fixture_identities(repository)
    windows = _active_windows(state)
    fixture_by_id = {fixture.fixture_id: fixture for fixture in fixtures}
    fixture_counts = Counter(fixture.competition for fixture in fixtures)
    team_ids: dict[str, set[str]] = {}
    for fixture in fixtures:
        team_ids.setdefault(fixture.competition, set()).update(
            (fixture.home_team_id, fixture.away_team_id)
        )
    window_counts = Counter(
        fixture_by_id[window.fixture_id].competition
        for window in windows
        if window.fixture_id in fixture_by_id
    )
    completed_window_ids = {
        receipt.window_id
        for receipt in receipts
        if receipt.window_id is not None
        and receipt.quality_status.value
        in {"CAPTURED", "CAPTURED_EMPTY", "COMPLETE"}
    }
    pending_windows_by_competition: dict[str, list[CaptureWindow]] = {}
    for window in windows:
        pending_fixture = fixture_by_id.get(window.fixture_id)
        if (
            pending_fixture is not None
            and window.window_id not in completed_window_ids
            and window.cutoff_at > summary_now
        ):
            pending_windows_by_competition.setdefault(
                pending_fixture.competition,
                [],
            ).append(window)
    receipt_counts = Counter(receipt.competition for receipt in receipts)
    deep_receipt_counts = Counter(
        receipt.competition
        for receipt in receipts
        if receipt.family.value
        not in {"FIXTURE", "TEAM", "EVENT_STATUS"}
    )
    empty_receipt_counts = Counter(
        receipt.competition
        for receipt in receipts
        if receipt.quality_status.value == "CAPTURED_EMPTY"
    )
    ledger_api_calls: Counter[str] = Counter()
    ledger_odds_credits: Counter[str] = Counter()
    for entry in state.budget_entries():
        scope = _budget_scope(entry.reason)
        if scope is None or entry.units <= 0:
            continue
        if entry.provider is ProviderKind.API_FOOTBALL:
            ledger_api_calls[scope] += entry.units
        elif entry.provider is ProviderKind.ODDS_API:
            ledger_odds_credits[scope] += entry.units
    registry_rows = {
        str(row["competition"]): row
        for row in cast(list[dict[str, object]], registry.get("leagues", []))
        if isinstance(row, dict) and row.get("competition")
    }
    replay_green = (
        replay.get("status") == "R2_REPLAY_VERIFIED"
        and replay.get("data_loss") == 0
        and replay.get("deletions") == 0
    )
    gate_observatory = gate.get("observatory")
    replay_observatory = replay.get("observatory")
    replay_r2 = (
        replay_observatory.get("r2")
        if isinstance(replay_observatory, Mapping)
        else None
    )
    postgres_green = (
        isinstance(gate_observatory, Mapping)
        and isinstance(gate_observatory.get("postgresql"), Mapping)
        and cast(Mapping[str, object], gate_observatory["postgresql"]).get(
            "payload_body_rows"
        )
        == 0
    )
    league_rows: list[dict[str, object]] = []
    for competition in active_competitions(policy.value):
        registered = fixture_counts[competition.competition]
        scoped_fixture_dates = [
            fixture.kickoff_at
            for fixture in fixtures
            if fixture.competition == competition.competition
        ]
        identity_slots = sum(
            2
            for fixture in fixtures
            if fixture.competition == competition.competition
            and fixture.fixture_id in identities
        )
        registry_gate = str(
            registry_rows.get(competition.competition, {}).get(
                "gate",
                LeagueActivationStatus.WAITING_FOR_FIXTURES.value,
            )
        )
        waiting_statuses = {
            LeagueActivationStatus.WAITING_FOR_FIXTURES.value,
            LeagueActivationStatus.NO_FIXTURES_IN_CURRENT_HORIZON.value,
        }
        if registered == 0:
            activation = (
                LeagueActivationStatus(registry_gate)
                if registry_gate
                in {
                    *waiting_statuses,
                    LeagueActivationStatus.BLOCKED_PROVIDER_ERROR.value,
                    LeagueActivationStatus.BLOCKED_BUDGET.value,
                    LeagueActivationStatus.DISABLED.value,
                }
                else LeagueActivationStatus.WAITING_FOR_FIXTURES
            )
        elif identity_slots != registered * 2:
            activation = LeagueActivationStatus.BLOCKED_IDENTITY
        elif (
            registry_gate
            == LeagueActivationStatus.BLOCKED_PROVIDER_ERROR.value
        ):
            activation = LeagueActivationStatus.BLOCKED_PROVIDER_ERROR
        elif registry_gate == LeagueActivationStatus.BLOCKED_BUDGET.value:
            activation = LeagueActivationStatus.BLOCKED_BUDGET
        else:
            activation = competition.expected_active_status
        league_rows.append(
            {
                "competition": competition.competition,
                "capture_profile": competition.capture_profile.value,
                "fixtures": registered,
                "teams": len(team_ids.get(competition.competition, set())),
                "identity_slots_verified": identity_slots,
                "identity_slots_expected": registered * 2,
                "windows": window_counts[competition.competition],
                "next_captures": len(
                    pending_windows_by_competition.get(
                        competition.competition,
                        [],
                    )
                ),
                "next_capture_at": (
                    min(
                        window.due_at
                        for window in pending_windows_by_competition[
                            competition.competition
                        ]
                    ).isoformat()
                    if pending_windows_by_competition.get(
                        competition.competition
                    )
                    else None
                ),
                "horizon_from": registry_rows.get(
                    competition.competition,
                    {},
                ).get("horizon_from"),
                "horizon_to": registry_rows.get(
                    competition.competition,
                    {},
                ).get("horizon_to"),
                "fixtures_from": (
                    min(scoped_fixture_dates).date().isoformat()
                    if scoped_fixture_dates
                    else None
                ),
                "fixtures_to": (
                    max(scoped_fixture_dates).date().isoformat()
                    if scoped_fixture_dates
                    else None
                ),
                "captures": receipt_counts[competition.competition],
                "deep_observations": deep_receipt_counts[
                    competition.competition
                ],
                "empty_responses": empty_receipt_counts[
                    competition.competition
                ],
                "api_football_calls": (
                    ledger_api_calls[competition.competition]
                    or int(
                        str(
                            registry_rows.get(
                                competition.competition,
                                {},
                            ).get("provider_calls", 0)
                        )
                    )
                ),
                "odds_api_credits": ledger_odds_credits[
                    competition.competition
                ],
                "r2": "VERIFIED" if replay_green else "BLOCKED",
                "postgresql": "VERIFIED" if postgres_green else "BLOCKED",
                "replay": "VERIFIED" if replay_green else "BLOCKED",
                "gate": activation.value,
            }
        )
    active = sum(
        row["gate"]
        in {
            LeagueActivationStatus.ACTIVE_FULL.value,
            LeagueActivationStatus.ACTIVE_ODDS_REDUCED.value,
        }
        for row in league_rows
    )
    waiting = sum(
        row["gate"]
        in {
            LeagueActivationStatus.WAITING_FOR_FIXTURES.value,
            LeagueActivationStatus.NO_FIXTURES_IN_CURRENT_HORIZON.value,
        }
        for row in league_rows
    )
    verdict = _expansion_verdict(
        active=active,
        waiting=waiting,
        replay_green=replay_green,
        postgres_green=postgres_green,
    )
    report: dict[str, object] = {
        "schema_version": "five-league-expansion-summary-v1",
        "generated_at": summary_now.isoformat(),
        "policy_sha256": policy.sha256,
        "verdict": verdict,
        "leagues": league_rows,
        "competitions_active": active,
        "competitions_waiting": waiting,
        "fixtures": len(fixtures),
        "identity_slots_verified": sum(
            int(str(row["identity_slots_verified"])) for row in league_rows
        ),
        "windows": len(windows),
        "registry_report_sha256": registry.get("report_sha256"),
        "replay_report_sha256": replay.get("report_sha256"),
        "gate_report_sha256": gate.get("report_sha256"),
        "r2": {
            "objects": replay.get("physical_unique_objects"),
            "bytes": replay.get("physical_unique_bytes"),
            "lag": replay_r2.get("lag") if isinstance(replay_r2, Mapping) else None,
            "deletions": replay.get("deletions"),
            "replay": replay.get("status"),
        },
        "postgresql": {
            "payload_body_rows": (
                cast(Mapping[str, object], gate_observatory["postgresql"]).get(
                    "payload_body_rows"
                )
                if isinstance(gate_observatory, Mapping)
                and isinstance(gate_observatory.get("postgresql"), Mapping)
                else None
            )
        },
        "provider_calls_for_summary": 0,
        "odds_api_credits_for_summary": 0,
        "deletions": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "model_promotion_authorized": False,
    }
    report["report_sha256"] = canonical_sha256(report)
    _write_json(args.output / "five-league-expansion-summary.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    registry = commands.add_parser("registry")
    mode = registry.add_mutually_exclusive_group(required=True)
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--execute", action="store_true")
    registry.add_argument("--estimate-file", type=Path)
    registry.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    registry.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    registry.add_argument("--now")
    registry.add_argument("--code-revision")
    registry.add_argument(
        "--competition",
        default="ALL",
        help="ALL or one configured competition name",
    )

    projection = commands.add_parser("projection")
    projection.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    projection.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/prospective-observatory/"
            "five-league-cost-projection.json"
        ),
    )

    summary = commands.add_parser("summary")
    summary.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    summary.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    summary.add_argument("--now")
    summary.add_argument(
        "--registry-report",
        type=Path,
        default=DEFAULT_OUTPUT / "five-league-registry.json",
    )
    summary.add_argument(
        "--replay-report",
        type=Path,
        default=DEFAULT_OUTPUT / "r2-replay-audit.json",
    )
    summary.add_argument(
        "--gate-report",
        type=Path,
        default=DEFAULT_OUTPUT / "gate-report.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "registry":
        result = run_registry(args)
    elif args.command == "projection":
        policy = ObservatoryPolicy.load(args.policy)
        result = build_cost_projection(policy)
        _write_json(args.output, result)
    else:
        result = run_summary(args)
    print(
        json.dumps(
            {
                "command": args.command,
                "status": result.get(
                    "status",
                    result.get("verdict", "REPORT_WRITTEN"),
                ),
                "report_sha256": result.get("report_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
