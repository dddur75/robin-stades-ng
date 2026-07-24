import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from robin.domain.enums import DataAvailability, DataOrigin, QuotePhase
from robin.ingestion.raw_store import LocalRawStore
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import RateLimitError, TransientProviderError
from robin.providers.http import JsonHttpProvider
from robin.providers.mock import MockFootballProvider
from robin.providers.the_odds_api import TheOddsApiProvider, parse_odds_snapshot


class FakeResponse:
    def __init__(
        self,
        payload: object,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.content = json.dumps(payload).encode()

    def json(self) -> object:
        return self.payload


class FakeTransport:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls = 0

    def get(self, *_: Any, **__: Any) -> FakeResponse:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize(
    "method",
    [
        "get_competitions",
        "get_seasons",
        "get_teams",
        "get_players",
        "get_fixtures",
        "get_results",
        "get_lineups",
        "get_events",
        "get_team_statistics",
        "get_player_statistics",
        "get_injuries",
        "get_suspensions",
        "get_odds",
    ],
)
def test_mock_expose_tous_les_contrats_sans_inventer_de_donnees(method: str) -> None:
    provider = MockFootballProvider({"fixtures": ({"id": "f1"},)})
    result = getattr(provider, method)()
    assert result.origin == DataOrigin.DEMO_DATA
    if method == "get_fixtures":
        assert result.availability == DataAvailability.PRESENT
    else:
        assert result.availability == DataAvailability.ABSENT


def test_mode_hors_ligne_et_cle_absente_sont_des_absences_pas_des_erreurs() -> None:
    offline = TheOddsApiProvider(api_key="unused", offline=True)
    missing = TheOddsApiProvider(api_key=None)
    assert offline.get_fixtures().message == "mode hors ligne"
    assert missing.get_fixtures().message == "credential_absent"
    assert missing.get_fixtures().availability == DataAvailability.ABSENT


def test_http_archive_brut_quota_et_masque_le_secret(tmp_path: Path) -> None:
    transport = FakeTransport(
        [
            FakeResponse(
                [{"id": 1}],
                headers={
                    "x-requests-used": "12",
                    "x-requests-remaining": "488",
                    "x-requests-last": "2",
                },
            )
        ]
    )
    store = LocalRawStore(tmp_path / "raw")
    provider = JsonHttpProvider(
        provider_name="fixture",
        base_url="https://example.test",
        credential="top-secret",
        credential_param="apiKey",
        raw_store=store,
        transport=transport,
    )
    result = provider._request("/events")
    observation = store.iter_observations()[0]
    assert result.quota.remaining == 488
    assert result.quota.last_cost == 2
    assert result.raw_observation_id == observation.observation_id
    assert observation.request_parameters["apiKey"] == "[REDACTED]"


def test_http_reessaie_429_puis_reussit() -> None:
    transport = FakeTransport([FakeResponse({}, 429), FakeResponse([{"id": 1}])])
    provider = JsonHttpProvider(
        provider_name="fixture",
        base_url="https://example.test",
        credential="x",
        credential_header="x-api-key",
        transport=transport,
        sleeper=lambda _: None,
    )
    assert provider._request("/events").availability == DataAvailability.PRESENT
    assert transport.calls == 2


def test_http_429_persistant_et_500_persistant_echouent_clairement() -> None:
    rate = FakeTransport([FakeResponse({}, 429)])
    server = FakeTransport([FakeResponse({}, 503)])
    common = {
        "provider_name": "fixture",
        "base_url": "https://example.test",
        "credential": "x",
        "credential_header": "x-api-key",
        "sleeper": lambda _: None,
        "max_retries": 1,
    }
    with pytest.raises(RateLimitError):
        JsonHttpProvider(transport=rate, **common)._request("/events")
    with pytest.raises(TransientProviderError):
        JsonHttpProvider(transport=server, **common)._request("/events")


def test_api_football_prepare_les_endpoints_sans_cle() -> None:
    provider = ApiFootballProvider(api_key=None, season=2026)
    results = [
        provider.get_competitions(),
        provider.get_teams(),
        provider.get_players(),
        provider.get_fixtures(),
        provider.get_injuries(),
        provider.get_odds(),
    ]
    assert all(result.message == "credential_absent" for result in results)


def test_parser_cotes_canonise_1x2_et_total() -> None:
    observed = datetime(2026, 8, 1, 10, tzinfo=UTC)
    event = {
        "id": "evt-1",
        "commence_time": "2026-08-02T18:00:00Z",
        "home_team": "Paris",
        "away_team": "Lyon",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Paris", "price": 1.8},
                            {"name": "Draw", "price": 3.6},
                            {"name": "Lyon", "price": 4.2},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 2.5, "price": 1.9},
                            {"name": "Under", "point": 2.5, "price": 1.95},
                        ],
                    },
                ],
            }
        ],
    }
    snapshot = parse_odds_snapshot(
        event,
        observed_at=observed,
        ingested_at=observed,
        raw_observation_id="raw-1",
        phase=QuotePhase.INTERMEDIATE,
    )
    assert len(snapshot.quotes) == 5
    assert snapshot.snapshot_id == snapshot.model_copy().snapshot_id
    assert snapshot.time_to_kickoff_seconds > 0
    assert not snapshot.is_live
