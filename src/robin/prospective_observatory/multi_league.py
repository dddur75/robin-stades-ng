"""Five-league capture profiles and fail-closed adaptive budget admission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from robin.prospective_observatory.contracts import CaptureFamily


class CaptureProfile(StrEnum):
    FULL = "FULL"
    DEEP_FULL_ODDS_REDUCED = "DEEP_FULL_ODDS_REDUCED"
    FIXTURE_ONLY = "FIXTURE_ONLY"
    DISABLED = "DISABLED"


class LeagueActivationStatus(StrEnum):
    ACTIVE_FULL = "ACTIVE_FULL"
    ACTIVE_ODDS_REDUCED = "ACTIVE_ODDS_REDUCED"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    BLOCKED_IDENTITY = "BLOCKED_IDENTITY"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    DISABLED = "DISABLED"


class OddsWindowPriority(StrEnum):
    NEAR_KICKOFF = "NEAR_KICKOFF"
    H_2 = "H-2"
    J_1 = "J-1"
    H_6 = "H-6"
    J_3 = "J-3"
    J_7 = "J-7"


ODDS_WINDOW_PRIORITY = (
    OddsWindowPriority.NEAR_KICKOFF.value,
    OddsWindowPriority.H_2.value,
    OddsWindowPriority.J_1.value,
    OddsWindowPriority.H_6.value,
    OddsWindowPriority.J_3.value,
    OddsWindowPriority.J_7.value,
)
REDUCED_ODDS_WINDOWS = frozenset(ODDS_WINDOW_PRIORITY[:3])


@dataclass(frozen=True, slots=True)
class CompetitionPolicy:
    competition: str
    provider: str
    provider_id: int
    capture_profile: CaptureProfile
    odds_sport_key: str

    @property
    def enabled(self) -> bool:
        return self.capture_profile is not CaptureProfile.DISABLED

    @property
    def expected_active_status(self) -> LeagueActivationStatus:
        if self.capture_profile is CaptureProfile.FULL:
            return LeagueActivationStatus.ACTIVE_FULL
        if self.capture_profile is CaptureProfile.DEEP_FULL_ODDS_REDUCED:
            return LeagueActivationStatus.ACTIVE_ODDS_REDUCED
        if self.capture_profile is CaptureProfile.DISABLED:
            return LeagueActivationStatus.DISABLED
        return LeagueActivationStatus.ACTIVE_FULL


def competition_registry(
    policy: Mapping[str, object],
) -> tuple[CompetitionPolicy, ...]:
    raw_registry = policy.get("competition_registry")
    if not isinstance(raw_registry, list):
        raise ValueError("PROSPECTIVE_COMPETITION_REGISTRY_INVALID")
    output: list[CompetitionPolicy] = []
    seen_names: set[str] = set()
    seen_provider_ids: set[tuple[str, int]] = set()
    for raw in raw_registry:
        if not isinstance(raw, Mapping):
            raise ValueError("PROSPECTIVE_COMPETITION_INVALID")
        competition = str(raw.get("competition", "")).strip()
        provider = str(raw.get("provider", "")).strip()
        odds_sport_key = str(raw.get("odds_sport_key", "")).strip()
        provider_id = raw.get("provider_id")
        try:
            profile = CaptureProfile(str(raw.get("capture_profile", "")))
        except ValueError as error:
            raise ValueError("PROSPECTIVE_CAPTURE_PROFILE_INVALID") from error
        if (
            not competition
            or not provider
            or isinstance(provider_id, bool)
            or not isinstance(provider_id, int)
            or provider_id <= 0
            or (profile is not CaptureProfile.DISABLED and not odds_sport_key)
        ):
            raise ValueError("PROSPECTIVE_COMPETITION_INVALID")
        provider_key = (provider, provider_id)
        if competition in seen_names or provider_key in seen_provider_ids:
            raise ValueError("PROSPECTIVE_COMPETITION_DUPLICATED")
        seen_names.add(competition)
        seen_provider_ids.add(provider_key)
        output.append(
            CompetitionPolicy(
                competition=competition,
                provider=provider,
                provider_id=provider_id,
                capture_profile=profile,
                odds_sport_key=odds_sport_key,
            )
        )
    return tuple(output)


def active_competitions(
    policy: Mapping[str, object],
) -> tuple[CompetitionPolicy, ...]:
    return tuple(item for item in competition_registry(policy) if item.enabled)


def labels_for_profile(
    profile: CaptureProfile,
    family: CaptureFamily,
    canonical_labels: Sequence[str],
) -> tuple[str, ...]:
    """Return the registered labels allowed by one competition profile."""

    if profile is CaptureProfile.DISABLED:
        return ()
    if profile is CaptureProfile.FIXTURE_ONLY:
        return tuple(canonical_labels) if family is CaptureFamily.FIXTURE else ()
    if (
        profile is CaptureProfile.DEEP_FULL_ODDS_REDUCED
        and family is CaptureFamily.ODDS
    ):
        return tuple(label for label in canonical_labels if label in REDUCED_ODDS_WINDOWS)
    return tuple(canonical_labels)


@dataclass(frozen=True, slots=True)
class ScopedBudgetUsage:
    run: int = 0
    day: int = 0
    week: int = 0
    competition_run: int = 0
    competition_day: int = 0
    season: int = 0

    def __post_init__(self) -> None:
        if min(
            self.run,
            self.day,
            self.week,
            self.competition_run,
            self.competition_day,
            self.season,
        ) < 0:
            raise ValueError("PROVIDER_BUDGET_USAGE_INVALID")


@dataclass(frozen=True, slots=True)
class BudgetAdmission:
    allowed: bool
    reason: str
    estimated_units: int
    provider_remaining: int
    provider_reserve: int
    remaining_run: int
    remaining_day: int
    remaining_competition_day: int
    remaining_week: int | None
    remaining_season: int | None


def _positive_int(value: object, *, error: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(error)
    return value


def provider_budget_policy(
    policy: Mapping[str, object],
    provider: str,
) -> Mapping[str, object]:
    budgets = policy.get("provider_budgets")
    if not isinstance(budgets, Mapping):
        raise ValueError("PROSPECTIVE_POLICY_BUDGETS_INVALID")
    value = budgets.get(provider)
    if not isinstance(value, Mapping):
        raise ValueError("PROSPECTIVE_PROVIDER_BUDGET_INVALID")
    return value


def authorize_scoped_budget(
    *,
    policy: Mapping[str, object],
    provider: str,
    competition: str,
    estimated_units: int,
    provider_remaining: int,
    usage: ScopedBudgetUsage = ScopedBudgetUsage(),
) -> BudgetAdmission:
    """Authorize one bounded provider scope against every configured ceiling."""

    if not competition:
        raise ValueError("PROSPECTIVE_BUDGET_COMPETITION_REQUIRED")
    if estimated_units < 0 or provider_remaining < 0:
        raise ValueError("PROSPECTIVE_BUDGET_ESTIMATE_INVALID")
    budget = provider_budget_policy(policy, provider)
    per_run = _positive_int(budget.get("per_run"), error="PROVIDER_RUN_CAP_INVALID")
    per_day = _positive_int(budget.get("per_day"), error="PROVIDER_DAY_CAP_INVALID")
    per_competition_run = _positive_int(
        budget.get("per_competition_per_run"),
        error="PROVIDER_COMPETITION_RUN_CAP_INVALID",
    )
    per_competition_day = _positive_int(
        budget.get("per_competition_per_day"),
        error="PROVIDER_COMPETITION_DAY_CAP_INVALID",
    )
    provider_reserve = _positive_int(
        budget.get("provider_reserve"),
        error="PROVIDER_RESERVE_INVALID",
    )
    per_week_raw = budget.get("per_week")
    per_season_raw = budget.get("per_season")
    per_week = (
        _positive_int(per_week_raw, error="PROVIDER_WEEK_CAP_INVALID")
        if per_week_raw is not None
        else None
    )
    per_season = (
        _positive_int(per_season_raw, error="PROVIDER_SEASON_CAP_INVALID")
        if per_season_raw is not None
        else None
    )
    checks = (
        ("BLOCKED_RUN_BUDGET", usage.run + estimated_units <= per_run),
        ("BLOCKED_DAILY_BUDGET", usage.day + estimated_units <= per_day),
        (
            "BLOCKED_COMPETITION_RUN_BUDGET",
            usage.competition_run + estimated_units <= per_competition_run,
        ),
        (
            "BLOCKED_COMPETITION_DAILY_BUDGET",
            usage.competition_day + estimated_units <= per_competition_day,
        ),
        (
            "BLOCKED_WEEKLY_BUDGET",
            per_week is None or usage.week + estimated_units <= per_week,
        ),
        (
            "BLOCKED_SEASON_BUDGET",
            per_season is None or usage.season + estimated_units <= per_season,
        ),
        (
            "BLOCKED_PROVIDER_RESERVE",
            provider_remaining - estimated_units >= provider_reserve,
        ),
    )
    reason = next((name for name, passed in checks if not passed), "AUTHORIZED")
    return BudgetAdmission(
        allowed=reason == "AUTHORIZED",
        reason=reason,
        estimated_units=estimated_units,
        provider_remaining=provider_remaining,
        provider_reserve=provider_reserve,
        remaining_run=max(per_run - usage.run - estimated_units, 0),
        remaining_day=max(per_day - usage.day - estimated_units, 0),
        remaining_competition_day=max(
            per_competition_day - usage.competition_day - estimated_units,
            0,
        ),
        remaining_week=(
            max(per_week - usage.week - estimated_units, 0)
            if per_week is not None
            else None
        ),
        remaining_season=(
            max(per_season - usage.season - estimated_units, 0)
            if per_season is not None
            else None
        ),
    )


def prioritize_odds_windows(
    labels: Sequence[str],
    *,
    maximum_units: int,
    units_per_window: int = 2,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Preserve closest windows first and shed distant windows fail-closed."""

    if maximum_units < 0 or units_per_window <= 0:
        raise ValueError("ODDS_PRIORITY_BUDGET_INVALID")
    requested = set(labels)
    unknown = requested - set(ODDS_WINDOW_PRIORITY)
    if unknown:
        raise ValueError("ODDS_WINDOW_PRIORITY_UNKNOWN")
    capacity = maximum_units // units_per_window
    ordered = tuple(label for label in ODDS_WINDOW_PRIORITY if label in requested)
    return ordered[:capacity], ordered[capacity:]
