"""Adaptateur typé API-Football v3.

La clé reste exclusivement dans l'en-tête ``x-apisports-key``. Les méthodes
acceptent les identifiants réellement exigés par le fournisseur et n'insèrent
jamais de valeur factice dans une requête.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from robin.providers.contracts import ProviderResult
from robin.providers.http import JsonHttpProvider


class ApiFootballProvider(JsonHttpProvider):
    """Client borné de l'API v3, utilisable en live comme en replay."""

    LIGUE_1_ID = 61

    def __init__(
        self,
        *,
        api_key: str | None,
        season: int = 2026,
        league_id: int = LIGUE_1_ID,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            provider_name="api-football",
            base_url="https://v3.football.api-sports.io",
            credential=api_key,
            credential_header="x-apisports-key",
            **kwargs,
        )
        self.season = season
        self.league_id = league_id

    def request(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> ProviderResult:
        return self._request(endpoint, params=params)

    def get_status(self) -> ProviderResult:
        return self._request("/status")

    def get_competitions(
        self,
        *,
        league_id: int | None = None,
        search: str | None = None,
        country: str | None = None,
        season: int | None = None,
        current: bool | None = None,
    ) -> ProviderResult:
        params: dict[str, object] = {}
        if league_id is not None:
            params["id"] = league_id
        elif search is None and country is None:
            params["id"] = self.league_id
        if search:
            params["search"] = search
        if country:
            params["country"] = country
        if season is not None:
            params["season"] = season
        if current is not None:
            params["current"] = "true" if current else "false"
        return self._request("/leagues", params=params)

    def get_seasons(self) -> ProviderResult:
        return self._request("/leagues/seasons")

    def get_teams(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
        team_id: int | None = None,
    ) -> ProviderResult:
        params: dict[str, object] = {}
        if team_id is not None:
            params["id"] = team_id
        else:
            params["league"] = league_id or self.league_id
            params["season"] = season or self.season
        return self._request("/teams", params=params)

    def get_squads(self, *, team_id: int | None = None) -> ProviderResult:
        return self._request(
            "/players/squads",
            params={"team": team_id} if team_id is not None else {},
        )

    def get_players(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
        team_id: int | None = None,
        player_id: int | None = None,
        page: int = 1,
    ) -> ProviderResult:
        params: dict[str, object] = {
            "season": season or self.season,
            "page": page,
        }
        if player_id is not None:
            params["id"] = player_id
        elif team_id is not None:
            params["team"] = team_id
        else:
            params["league"] = league_id or self.league_id
        return self._request("/players", params=params)

    def get_fixtures(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
        fixture_id: int | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> ProviderResult:
        params: dict[str, object]
        if fixture_id is not None:
            params = {"id": fixture_id}
        else:
            params = {
                "league": league_id or self.league_id,
                "season": season or self.season,
            }
        if status:
            params["status"] = status
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        return self._request("/fixtures", params=params)

    def get_results(self) -> ProviderResult:
        return self.get_fixtures(status="FT")

    def get_lineups(self, *, fixture_id: int | None = None) -> ProviderResult:
        return self._request(
            "/fixtures/lineups",
            params={"fixture": fixture_id} if fixture_id is not None else {},
        )

    def get_events(self, *, fixture_id: int | None = None) -> ProviderResult:
        return self._request(
            "/fixtures/events",
            params={"fixture": fixture_id} if fixture_id is not None else {},
        )

    def get_fixture_statistics(
        self,
        *,
        fixture_id: int | None = None,
    ) -> ProviderResult:
        return self._request(
            "/fixtures/statistics",
            params={"fixture": fixture_id} if fixture_id is not None else {},
        )

    def get_fixture_players(
        self,
        *,
        fixture_id: int | None = None,
    ) -> ProviderResult:
        return self._request(
            "/fixtures/players",
            params={"fixture": fixture_id} if fixture_id is not None else {},
        )

    def get_team_statistics(
        self,
        *,
        team_id: int | None = None,
        league_id: int | None = None,
        season: int | None = None,
        date: str | None = None,
    ) -> ProviderResult:
        params: dict[str, object] = {
            "league": league_id or self.league_id,
            "season": season or self.season,
        }
        if team_id is not None:
            params["team"] = team_id
        if date:
            params["date"] = date
        return self._request("/teams/statistics", params=params)

    def get_player_statistics(self) -> ProviderResult:
        return self.get_players()

    def get_standings(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
    ) -> ProviderResult:
        return self._request(
            "/standings",
            params={
                "league": league_id or self.league_id,
                "season": season or self.season,
            },
        )

    def get_injuries(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
        fixture_id: int | None = None,
    ) -> ProviderResult:
        params: dict[str, object] = {}
        if fixture_id is not None:
            params["fixture"] = fixture_id
        else:
            params["league"] = league_id or self.league_id
            params["season"] = season or self.season
        return self._request("/injuries", params=params)

    def get_suspensions(self) -> ProviderResult:
        # L'API regroupe les indisponibilités, dont les suspensions.
        return self.get_injuries()

    def get_coaches(self, *, team_id: int | None = None) -> ProviderResult:
        return self._request(
            "/coachs",
            params={"team": team_id} if team_id is not None else {},
        )

    def get_transfers(
        self,
        *,
        team_id: int | None = None,
        player_id: int | None = None,
    ) -> ProviderResult:
        params: dict[str, object] = {}
        if team_id is not None:
            params["team"] = team_id
        if player_id is not None:
            params["player"] = player_id
        return self._request("/transfers", params=params)

    def get_odds(
        self,
        *,
        league_id: int | None = None,
        season: int | None = None,
        page: int = 1,
    ) -> ProviderResult:
        return self._request(
            "/odds",
            params={
                "league": league_id or self.league_id,
                "season": season or self.season,
                "page": page,
            },
        )
