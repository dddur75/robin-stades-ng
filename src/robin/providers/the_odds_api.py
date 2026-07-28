"""Adaptateur réel The Odds API v4."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from robin.domain.enums import (
    DataAvailability,
    DataOrigin,
    MarketScope,
    MarketType,
    QuotePhase,
    Selection,
)
from robin.domain.odds import (
    BookmakerQuoteContract,
    MarketKey,
    OddsSnapshot,
    stable_internal_id,
)
from robin.providers.contracts import ProviderResult
from robin.providers.http import JsonHttpProvider


class TheOddsApiProvider(JsonHttpProvider):
    SPORT_KEY = "soccer_france_ligue_one"

    def __init__(
        self,
        *,
        api_key: str | None,
        sport_key: str = SPORT_KEY,
        **kwargs: Any,
    ) -> None:
        if not sport_key or any(
            character not in "abcdefghijklmnopqrstuvwxyz_"
            for character in sport_key
        ):
            raise ValueError("ODDS_API_SPORT_KEY_INVALID")
        self.sport_key = sport_key
        super().__init__(
            provider_name="the-odds-api",
            base_url="https://api.the-odds-api.com/v4",
            credential=api_key,
            credential_param="apiKey",
            **kwargs,
        )

    def get_competitions(self) -> ProviderResult:
        return self._request("/sports")

    def get_seasons(self) -> ProviderResult:
        return self._unsupported("/seasons")

    def get_teams(self) -> ProviderResult:
        return self._unsupported("/teams")

    def get_players(self) -> ProviderResult:
        return self._unsupported("/players")

    def get_fixtures(self) -> ProviderResult:
        return self._request(f"/sports/{self.sport_key}/events")

    def get_results(self) -> ProviderResult:
        return self._request(
            f"/sports/{self.sport_key}/scores",
            params={"daysFrom": 3, "dateFormat": "iso"},
        )

    def get_lineups(self) -> ProviderResult:
        return self._unsupported("/lineups")

    def get_events(self) -> ProviderResult:
        return self.get_fixtures()

    def get_team_statistics(self) -> ProviderResult:
        return self._unsupported("/team-statistics")

    def get_player_statistics(self) -> ProviderResult:
        return self._unsupported("/player-statistics")

    def get_injuries(self) -> ProviderResult:
        return self._unsupported("/injuries")

    def get_suspensions(self) -> ProviderResult:
        return self._unsupported("/suspensions")

    def get_odds(self) -> ProviderResult:
        return self.get_odds_for_sport(self.sport_key)

    def get_odds_for_sport(self, sport_key: str) -> ProviderResult:
        if not sport_key or any(
            character not in "abcdefghijklmnopqrstuvwxyz_"
            for character in sport_key
        ):
            raise ValueError("ODDS_API_SPORT_KEY_INVALID")
        return self._request(
            f"/sports/{sport_key}/odds",
            params={
                "regions": "eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )

    def get_event_odds(self, event_id: str) -> ProviderResult:
        return self._request(
            f"/sports/{self.sport_key}/events/{event_id}/odds",
            params={
                "regions": "eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )

    def _unsupported(self, endpoint: str) -> ProviderResult:
        return ProviderResult(
            provider=self.provider_name,
            endpoint=endpoint,
            availability=DataAvailability.ABSENT,
            observed_at=datetime.now(UTC),
            origin=DataOrigin.LIVE_SOURCE,
            message="endpoint non fourni par cette source",
        )


def _selection(
    market_key: str,
    outcome: Mapping[str, object],
    *,
    home_team: str,
    away_team: str,
) -> tuple[MarketType, Selection, Decimal | None] | None:
    name = str(outcome.get("name", ""))
    point = outcome.get("point")
    if market_key == "h2h":
        if name == home_team:
            return MarketType.ONE_X_TWO, Selection.HOME, None
        if name == away_team:
            return MarketType.ONE_X_TWO, Selection.AWAY, None
        if name.lower() == "draw":
            return MarketType.ONE_X_TWO, Selection.DRAW, None
    if market_key == "totals" and point is not None:
        if name.lower() == "over":
            return MarketType.TOTAL_GOALS, Selection.OVER, Decimal(str(point))
        if name.lower() == "under":
            return MarketType.TOTAL_GOALS, Selection.UNDER, Decimal(str(point))
    return None


def _mapping_records(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def parse_odds_snapshot(
    event: Mapping[str, object],
    *,
    observed_at: datetime,
    ingested_at: datetime,
    raw_observation_id: str,
    phase: QuotePhase,
) -> OddsSnapshot:
    provider_event_id = str(event["id"])
    home_team = str(event["home_team"])
    away_team = str(event["away_team"])
    fixture_id = stable_internal_id("fixture", "the-odds-api", provider_event_id)
    quotes: list[BookmakerQuoteContract] = []
    for bookmaker_value in _mapping_records(event.get("bookmakers")):
        bookmaker_key = str(bookmaker_value.get("key", ""))
        bookmaker_id = stable_internal_id("bookmaker", "the-odds-api", bookmaker_key)
        for market_value in _mapping_records(bookmaker_value.get("markets")):
            market_key = str(market_value.get("key", ""))
            for outcome_value in _mapping_records(market_value.get("outcomes")):
                mapped = _selection(
                    market_key,
                    outcome_value,
                    home_team=home_team,
                    away_team=away_team,
                )
                if mapped is None:
                    continue
                market_type, selection, line = mapped
                quotes.append(
                    BookmakerQuoteContract(
                        market=MarketKey(
                            fixture_id=fixture_id,
                            market_type=market_type,
                            market_scope=MarketScope.MATCH,
                            selection=selection,
                            line_value=line,
                        ),
                        bookmaker_id=bookmaker_id,
                        odds_decimal=Decimal(str(outcome_value["price"])),
                        observed_at=observed_at,
                        phase=phase,
                        source_observation_id=raw_observation_id,
                        bookmaker_rule_version="the-odds-api-v4",
                    )
                )
    kickoff = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
    return OddsSnapshot(
        provider="the-odds-api",
        provider_fixture_id=provider_event_id,
        fixture_id=fixture_id,
        fixture_kickoff_at=kickoff.astimezone(UTC),
        fixture_kickoff_local=kickoff.astimezone().isoformat(),
        observed_at=observed_at,
        ingested_at=ingested_at,
        phase=phase,
        quotes=tuple(quotes),
        schema_version="the-odds-api-v4",
    )
