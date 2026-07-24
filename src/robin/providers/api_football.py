"""Adaptateur API-Football v3, prêt à activer avec une clé."""

from __future__ import annotations

from typing import Any

from robin.providers.contracts import ProviderResult
from robin.providers.http import JsonHttpProvider


class ApiFootballProvider(JsonHttpProvider):
    LIGUE_1_ID = 61

    def __init__(self, *, api_key: str | None, season: int = 2026, **kwargs: Any) -> None:
        super().__init__(
            provider_name="api-football",
            base_url="https://v3.football.api-sports.io",
            credential=api_key,
            credential_header="x-apisports-key",
            **kwargs,
        )
        self.season = season

    def get_competitions(self) -> ProviderResult:
        return self._request("/leagues", params={"id": self.LIGUE_1_ID})

    def get_seasons(self) -> ProviderResult:
        return self.get_competitions()

    def get_teams(self) -> ProviderResult:
        return self._request(
            "/teams",
            params={"league": self.LIGUE_1_ID, "season": self.season},
        )

    def get_players(self) -> ProviderResult:
        return self._request(
            "/players",
            params={"league": self.LIGUE_1_ID, "season": self.season, "page": 1},
        )

    def get_fixtures(self) -> ProviderResult:
        return self._request(
            "/fixtures",
            params={"league": self.LIGUE_1_ID, "season": self.season},
        )

    def get_results(self) -> ProviderResult:
        return self._request(
            "/fixtures",
            params={"league": self.LIGUE_1_ID, "season": self.season, "status": "FT"},
        )

    def get_lineups(self) -> ProviderResult:
        return self._request("/fixtures/lineups", params={"fixture": "required"})

    def get_events(self) -> ProviderResult:
        return self._request("/fixtures/events", params={"fixture": "required"})

    def get_team_statistics(self) -> ProviderResult:
        return self._request(
            "/teams/statistics",
            params={
                "league": self.LIGUE_1_ID,
                "season": self.season,
                "team": "required",
            },
        )

    def get_player_statistics(self) -> ProviderResult:
        return self.get_players()

    def get_injuries(self) -> ProviderResult:
        return self._request(
            "/injuries",
            params={"league": self.LIGUE_1_ID, "season": self.season},
        )

    def get_suspensions(self) -> ProviderResult:
        return self.get_injuries()

    def get_odds(self) -> ProviderResult:
        return self._request(
            "/odds",
            params={"league": self.LIGUE_1_ID, "season": self.season, "page": 1},
        )
