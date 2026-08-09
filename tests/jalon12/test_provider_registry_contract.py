from __future__ import annotations

from collections.abc import Mapping

import pytest
import requests

from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import TransientProviderError
from robin.providers.the_odds_api import TheOddsApiProvider


class _Response:
    status_code = 200
    content = b'{"response":[]}'
    headers: Mapping[str, str] = {}

    def json(self) -> dict[str, object]:
        return {"response": []}


class _Transport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: int,
    ) -> _Response:
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return _Response()


def _provider(transport: _Transport) -> ApiFootballProvider:
    return ApiFootballProvider(
        api_key="test-only-secret",
        transport=transport,
        sleeper=lambda _: None,
        randomizer=lambda: 0.0,
    )


def test_current_season_resolution_uses_provider_contract() -> None:
    transport = _Transport()
    _provider(transport).get_competitions(league_id=61, current=True)

    call = transport.calls[0]
    assert call["params"] == {"id": 61, "current": "true"}
    assert "test-only-secret" not in repr(call["params"])
    assert call["headers"] == {
        "accept": "application/json",
        "x-apisports-key": "test-only-secret",
    }


def test_fixture_horizon_is_bounded_by_dates_and_resolved_season() -> None:
    transport = _Transport()
    _provider(transport).get_fixtures(
        league_id=61,
        season=2026,
        date_from="2026-07-27",
        date_to="2026-08-26",
    )

    call = transport.calls[0]
    params = call["params"]
    assert isinstance(params, dict)
    assert params == {
        "league": 61,
        "season": 2026,
        "from": "2026-07-27",
        "to": "2026-08-26",
    }
    assert "test-only-secret" not in repr(params)


class _FailingTransport:
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: int,
    ) -> _Response:
        del headers, timeout
        raise requests.ConnectionError(
            f"failed GET {url}?apiKey={params.get('apiKey')}"
        )


def test_transport_error_never_leaks_query_parameter_secret() -> None:
    secret = "must-never-reach-workflow-logs"
    provider = TheOddsApiProvider(
        api_key=secret,
        transport=_FailingTransport(),
        max_retries=0,
    )

    with pytest.raises(TransientProviderError) as captured:
        provider.get_odds()

    assert str(captured.value) == "the-odds-api: transport_error"
    assert secret not in repr(captured.value)


def test_chronos_odds_request_freezes_french_region_and_books() -> None:
    transport = _Transport()
    provider = TheOddsApiProvider(
        api_key="test-only-secret",
        transport=transport,
    )

    provider.get_odds()

    params = transport.calls[0]["params"]
    assert isinstance(params, dict)
    assert params == {
        "regions": "fr",
        "bookmakers": "betclic_fr,netbet_fr,pmu_fr,unibet_fr,winamax_fr",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
        "apiKey": "test-only-secret",
    }


def test_chronos_odds_request_rejects_bookmaker_substitution() -> None:
    with pytest.raises(ValueError, match="ODDS_API_BOOKMAKER_KEYS_INVALID"):
        TheOddsApiProvider(
            api_key="test-only-secret",
            bookmaker_keys=("pinnacle",),
        )
