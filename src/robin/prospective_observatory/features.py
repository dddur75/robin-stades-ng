"""Research-ready prospective features without any betting decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class PlayerAppearance:
    fixture_id: str
    player_id: str
    kickoff_at: datetime
    minutes: int
    started: bool
    position: str
    goals: int | None


@dataclass(frozen=True, slots=True)
class OddsPoint:
    window_label: str
    bookmaker: str
    market: str
    selection: str
    odds: float
    margin: float
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ProspectiveFeatureInputs:
    fixture_id: str
    cutoff_at: datetime
    kickoff_at: datetime
    prior_appearances: tuple[PlayerAppearance, ...]
    expected_starters: tuple[str, ...] | None
    observed_starters: tuple[str, ...] | None
    goalkeeper_id: str | None
    centre_back_ids: tuple[str, ...] | None
    known_absent_player_ids: tuple[str, ...]
    formation: str | None
    prior_formation: str | None
    prior_fixture_kickoffs: tuple[datetime, ...]
    odds_points: tuple[OddsPoint, ...]


@dataclass(frozen=True, slots=True)
class ProspectiveFeatureRow:
    fixture_id: str
    as_of_at: datetime
    features: dict[str, object]
    production_status: str = "PRODUCTION_LOCKED"
    real_bets: bool = False
    no_bet_default: bool = True


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return value.astimezone(UTC)


def build_prospective_feature_row(
    inputs: ProspectiveFeatureInputs,
) -> ProspectiveFeatureRow:
    cutoff = _utc(inputs.cutoff_at, "cutoff_at")
    kickoff = _utc(inputs.kickoff_at, "kickoff_at")
    if cutoff >= kickoff:
        raise ValueError("PROSPECTIVE_FEATURE_CUTOFF_MUST_PRECEDE_KICKOFF")
    prior = tuple(
        appearance
        for appearance in inputs.prior_appearances
        if _utc(appearance.kickoff_at, "appearance_kickoff_at") < cutoff
        and appearance.fixture_id != inputs.fixture_id
    )
    if len(prior) != len(inputs.prior_appearances):
        raise ValueError("PROSPECTIVE_FEATURE_TARGET_OR_FUTURE_APPEARANCE_FORBIDDEN")

    by_player: dict[str, list[PlayerAppearance]] = {}
    for appearance in sorted(prior, key=lambda item: item.kickoff_at, reverse=True):
        by_player.setdefault(appearance.player_id, []).append(appearance)

    player_form: dict[str, dict[str, object]] = {}
    for player_id, appearances in sorted(by_player.items()):
        last_five = appearances[:5]
        last_three = appearances[:3]
        known_goals = [item.goals for item in last_three if item.goals is not None]
        player_form[player_id] = {
            "minutes_last_3": sum(item.minutes for item in last_three),
            "minutes_last_5": sum(item.minutes for item in last_five),
            "in_form": (
                sum(known_goals) > 0 if len(known_goals) == len(last_three) else None
            ),
            "usual_starter": (
                sum(1 for item in last_five if item.started) >= 3
                if len(last_five) == 5
                else None
            ),
        }

    observed = set(inputs.observed_starters or ())
    expected = set(inputs.expected_starters or ())
    known_absences = set(inputs.known_absent_player_ids)
    centre_backs = set(inputs.centre_back_ids or ())
    continuity: float | None = None
    if inputs.observed_starters is not None and inputs.expected_starters is not None:
        continuity = len(observed & expected) / 11.0
    prior_pair = set(
        player_id
        for player_id, appearances in by_player.items()
        if appearances
        and appearances[0].started
        and appearances[0].position.upper() in {"CB", "CENTRE_BACK"}
    )
    new_central_pair: bool | None = None
    if inputs.centre_back_ids is not None and len(centre_backs) == 2:
        new_central_pair = not centre_backs <= prior_pair

    prior_kickoffs = tuple(
        sorted(
            (_utc(value, "prior_fixture_kickoff") for value in inputs.prior_fixture_kickoffs),
            reverse=True,
        )
    )
    if any(value >= cutoff for value in prior_kickoffs):
        raise ValueError("PROSPECTIVE_FEATURE_FUTURE_FIXTURE_FORBIDDEN")
    rest_days = (
        (kickoff - prior_kickoffs[0]).total_seconds() / 86_400
        if prior_kickoffs
        else None
    )
    congestion = (
        sum(1 for value in prior_kickoffs if kickoff - value <= timedelta(days=14))
        if prior_kickoffs
        else None
    )

    odds_by_window: dict[str, list[dict[str, object]]] = {}
    for point in inputs.odds_points:
        observed_at = _utc(point.observed_at, "odds_observed_at")
        if observed_at >= cutoff:
            raise ValueError("PROSPECTIVE_FEATURE_POST_CUTOFF_ODDS_FORBIDDEN")
        odds_by_window.setdefault(point.window_label, []).append(
            {
                "bookmaker": point.bookmaker,
                "market": point.market,
                "selection": point.selection,
                "odds": point.odds,
                "margin": point.margin,
                "observed_at": observed_at.isoformat(),
            }
        )

    return ProspectiveFeatureRow(
        fixture_id=inputs.fixture_id,
        as_of_at=cutoff,
        features={
            "player_form": player_form,
            "usual_goalkeeper": (
                player_form.get(inputs.goalkeeper_id, {}).get("usual_starter")
                if inputs.goalkeeper_id is not None
                else None
            ),
            "usual_centre_backs": (
                all(
                    player_form.get(player_id, {}).get("usual_starter") is True
                    for player_id in centre_backs
                )
                if len(centre_backs) == 2
                else None
            ),
            "known_absences": sorted(known_absences),
            "two_centre_backs_absent": (
                len(centre_backs & known_absences) >= 2 if centre_backs else None
            ),
            "lineup_continuity": continuity,
            "new_central_pair": new_central_pair,
            "formation": inputs.formation,
            "formation_changed": (
                inputs.formation != inputs.prior_formation
                if inputs.formation is not None and inputs.prior_formation is not None
                else None
            ),
            "rest_days": rest_days,
            "fixtures_last_14_days": congestion,
            "market_prices_by_window": odds_by_window,
        },
    )
