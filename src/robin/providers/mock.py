"""Fournisseur déterministe complet pour tests, CI et mode dégradé."""

from __future__ import annotations

from datetime import UTC, datetime

from robin.domain.enums import DataAvailability, DataOrigin
from robin.providers.contracts import ProviderResult


class MockFootballProvider:
    def __init__(self, records: dict[str, tuple[dict[str, object], ...]]) -> None:
        self.records = records

    def _result(self, endpoint: str) -> ProviderResult:
        records = self.records.get(endpoint, ())
        return ProviderResult(
            provider="mock-football",
            endpoint=endpoint,
            availability=(
                DataAvailability.PRESENT if records else DataAvailability.ABSENT
            ),
            records=records,
            observed_at=datetime(2026, 7, 24, tzinfo=UTC),
            origin=DataOrigin.DEMO_DATA,
            message=None if records else "fixture absente",
        )

    def get_competitions(self) -> ProviderResult:
        return self._result("competitions")

    def get_seasons(self) -> ProviderResult:
        return self._result("seasons")

    def get_teams(self) -> ProviderResult:
        return self._result("teams")

    def get_players(self) -> ProviderResult:
        return self._result("players")

    def get_fixtures(self) -> ProviderResult:
        return self._result("fixtures")

    def get_results(self) -> ProviderResult:
        return self._result("results")

    def get_lineups(self) -> ProviderResult:
        return self._result("lineups")

    def get_events(self) -> ProviderResult:
        return self._result("events")

    def get_team_statistics(self) -> ProviderResult:
        return self._result("team_statistics")

    def get_player_statistics(self) -> ProviderResult:
        return self._result("player_statistics")

    def get_injuries(self) -> ProviderResult:
        return self._result("injuries")

    def get_suspensions(self) -> ProviderResult:
        return self._result("suspensions")

    def get_odds(self) -> ProviderResult:
        return self._result("odds")
