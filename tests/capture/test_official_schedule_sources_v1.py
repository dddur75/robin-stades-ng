from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfWriter

import robin.capture.official_schedule_sources as official_sources_module
from robin.capture.official_schedule_sources import (
    DFB_DATACENTER_HTML_V1,
    LALIGA_PUBLIC_MATCHES_JSON_V1,
    LEGA_SERIE_A_CALENDAR_PDF_V1,
    LIGUE1_CALENDAR_JSON_V1,
    LIGUE1_CALENDAR_URL,
    LIGUE1_GAMEWEEK_URL_TEMPLATE,
    MAXIMUM_SOURCE_BYTES,
    PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    BuiltinHttpsOfficialScheduleFetcher,
    OfficialFetchResult,
    OfficialHttpResponse,
    OfficialScheduleSourceError,
    OfficialSourceSpec,
    RedirectHop,
    SupportingOfficialRead,
    build_official_schedule_evidence,
    default_pdf_text_extractor,
    fetch_official_schedule_source,
    load_official_source_plan_bytes,
)

NOW = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 9, 8, tzinfo=UTC)
URLS = {
    "soccer_epl": "https://www.premierleague.com/en/news/season",
    "soccer_spain_la_liga": (
        "https://apim.laliga.com/public-service/api/v1/matches?"
        "subscription=laliga-easports-2026&competition=primera-division&limit=100&offset=300"
    ),
    "soccer_germany_bundesliga": "https://datencenter.dfb.de/competitions/12/seasons/current",
    "soccer_italy_serie_a": "https://images.legaseriea.it/calendar.pdf",
    "soccer_france_ligue_one": LIGUE1_CALENDAR_URL,
}
ADAPTERS = {
    "soccer_epl": PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    "soccer_spain_la_liga": LALIGA_PUBLIC_MATCHES_JSON_V1,
    "soccer_germany_bundesliga": DFB_DATACENTER_HTML_V1,
    "soccer_italy_serie_a": LEGA_SERIE_A_CALENDAR_PDF_V1,
    "soccer_france_ligue_one": LIGUE1_CALENDAR_JSON_V1,
}
CONTENT_TYPES = {
    "soccer_epl": "text/html; charset=utf-8",
    "soccer_spain_la_liga": "application/json",
    "soccer_germany_bundesliga": "text/html",
    "soccer_italy_serie_a": "application/pdf",
    "soccer_france_ligue_one": "application/json",
}


class FakeFetcher:
    def __init__(self, response: OfficialHttpResponse) -> None:
        self.response = response
        self.calls = 0

    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
        self.calls += 1
        return self.response


class ForbiddenFetcher:
    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
        raise AssertionError(f"connection forbidden for {source.url}")


def source(sport_key: str) -> OfficialSourceSpec:
    return OfficialSourceSpec(
        sport_key=sport_key,
        adapter=ADAPTERS[sport_key],
        url=URLS[sport_key],
    )


def accepted_result(
    sport_key: str,
    payload: bytes,
    *,
    supporting_payloads: tuple[bytes, ...] = (),
    supporting_gameweeks: tuple[int, ...] | None = None,
) -> OfficialFetchResult:
    selected = source(sport_key)
    supporting_raw = (
        b'<script id="__NEXT_DATA__">'
        b'{"runtimeConfig":{"backendSubscription":"public-test-subscription"}}'
        b"</script>"
    )
    supporting: tuple[SupportingOfficialRead, ...] = (
        (
            SupportingOfficialRead(
                requested_url="https://www.laliga.com/en-GB/laliga-easports/results",
                final_url="https://www.laliga.com/en-GB/laliga-easports/results",
                official_domain="www.laliga.com",
                status_code=200,
                content_type="text/html",
                byte_count=len(supporting_raw),
                raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
                redirect_chain=(),
            ),
        )
        if sport_key == "soccer_spain_la_liga"
        else ()
    )
    if sport_key == "soccer_france_ligue_one":
        selected_gameweeks = (
            tuple(json.loads(raw)["matches"][0]["gameWeekNumber"] for raw in supporting_payloads)
            if supporting_gameweeks is None
            else supporting_gameweeks
        )
        supporting = tuple(
            SupportingOfficialRead(
                requested_url=LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=gameweek),
                final_url=LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=gameweek),
                official_domain="ma-api.ligue1.fr",
                status_code=200,
                content_type="application/json",
                byte_count=len(raw),
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                redirect_chain=(),
            )
            for raw, gameweek in zip(
                supporting_payloads,
                selected_gameweeks,
                strict=True,
            )
        )
    fetcher = FakeFetcher(
        OfficialHttpResponse(
            status_code=200,
            final_url=selected.url,
            content_type=CONTENT_TYPES[sport_key],
            body=payload,
            supporting_official_reads=supporting,
            supporting_official_raw_bytes=(
                supporting_payloads
                if sport_key == "soccer_france_ligue_one"
                else ((supporting_raw,) if supporting else ())
            ),
        )
    )
    return fetch_official_schedule_source(selected, fetcher=fetcher, observed_at_utc=NOW)


def plan_payload(*, laliga_url: str | None = None) -> bytes:
    document = {
        "schema_version": "robin-official-schedule-source-plan-v1",
        "season": "2026-2027",
        "sources": {
            sport_key: {
                "adapter": ADAPTERS[sport_key],
                "url": laliga_url if sport_key == "soccer_spain_la_liga" and laliga_url else url,
            }
            for sport_key, url in URLS.items()
        },
    }
    return json.dumps(document, sort_keys=True).encode()


def round_robin_rounds(clubs: list[str], count: int) -> list[list[tuple[str, str]]]:
    rotating = list(clubs)
    rounds: list[list[tuple[str, str]]] = []
    for round_index in range(count):
        pairings = [
            (rotating[index], rotating[-index - 1])
            if round_index % 2 == 0
            else (rotating[-index - 1], rotating[index])
            for index in range(len(rotating) // 2)
        ]
        rounds.append(pairings)
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    return rounds


def epl_payload(*, missing_time_round: int | None = None) -> bytes:
    clubs = [f"Club {index:02d}" for index in range(20)]
    first_leg = round_robin_rounds(clubs, 19)
    second_leg = [[(away, home) for home, away in games] for games in first_leg]
    rounds = [*first_leg, *second_leg]
    rows: list[str] = []
    season_start = datetime(2026, 8, 15)
    for round_index, games in enumerate(rounds):
        matchday = season_start + timedelta(days=round_index * 7)
        rows.append(f"{matchday.strftime('%A')} {matchday.day} {matchday.strftime('%B %Y')}")
        for home, away in games:
            prefix = "" if missing_time_round == round_index else "15:00 "
            rows.append(f"{prefix}{home} v {away}")
    return (
        "<html>all 380 matches are below; untimed fixtures use 15:00 UK time"
        f"<p>{'<br>'.join(rows)}</p></html>"
    ).encode()


def laliga_payload(
    *,
    duplicate: bool = False,
    missing_kickoff: bool = False,
    midnight_placeholder: bool = False,
    foreign_club: bool = False,
    self_match: bool = False,
) -> bytes:
    matches: list[dict[str, object]] = []
    latest = datetime(2026, 9, 7, 21, 0, tzinfo=UTC)
    clubs = [f"Liga Club {index:02d}" for index in range(20)]
    for week_index, games in enumerate(round_robin_rounds(clubs, 8), start=1):
        for game_index, (home, away) in enumerate(games):
            index = len(matches)
            item: dict[str, object] = {
                "id": f"laliga-{index:03d}",
                "competition": {"slug": "primera-division"},
                "date": (latest - timedelta(days=week_index - 1, minutes=game_index))
                .isoformat()
                .replace("+00:00", "Z"),
                "home_team": {"name": home},
                "away_team": {"name": away},
                "gameweek": {"week": week_index},
            }
            matches.append(item)
    if duplicate:
        matches[1]["home_team"] = matches[0]["home_team"]
        matches[1]["away_team"] = matches[0]["away_team"]
        matches[1]["date"] = matches[0]["date"]
    if missing_kickoff:
        matches[0].pop("date")
    if midnight_placeholder:
        matches[0]["date"] = "2026-09-07T00:00:00Z"
    if foreign_club:
        matches[0]["home_team"] = {"name": "Liga Club 20"}
    if self_match:
        matches[0]["away_team"] = matches[0]["home_team"]
    return json.dumps({"total": 380, "matches": matches}, sort_keys=True).encode()


def bundesliga_payload(*, partial: bool = False, foreign_club: bool = False) -> bytes:
    sections: list[str] = []
    base = datetime(2026, 8, 29, 15, 30)
    weekdays = {
        0: "Montag",
        1: "Dienstag",
        2: "Mittwoch",
        3: "Donnerstag",
        4: "Freitag",
        5: "Samstag",
        6: "Sonntag",
    }
    clubs = [f"Bund Club {index:02d}" for index in range(18)]
    rounds = round_robin_rounds(clubs, 5)
    fixture_index = 0
    for matchday in range(1, 35):
        rows: list[str] = []
        if matchday <= 5:
            for game_index, (home, away_name) in enumerate(rounds[matchday - 1]):
                value = base + timedelta(days=matchday - 1, minutes=game_index)
                if foreign_club and matchday == 2 and game_index == 0:
                    home = "Bund Club 18"
                away = (
                    ""
                    if partial and fixture_index == 0
                    else (f'<div class="c-MatchTable-team--away"><a href="#">{away_name}</a></div>')
                )
                rows.append(
                    '<div class="c-MatchTable-row">'
                    f'<span id="match_{1000 + fixture_index}"></span>'
                    f"{weekdays[value.weekday()]}, {value.strftime('%d.%m.%Y %H:%M')} Uhr"
                    '<div class="c-MatchTable-team--home"><a href="#">'
                    f"{home}</a></div>{away}</div>"
                )
                fixture_index += 1
        sections.append(f"<h2>{matchday}. Spieltag</h2>{''.join(rows)}")
    return f"Bundesliga 2026/27 der Spielplan{''.join(sections)}".encode()


def serie_a_text(
    *,
    ambiguous_in_horizon: bool = False,
    ambiguous_outside_horizon: bool = False,
    missing_later_row: bool = False,
) -> str:
    lines = ["SERIE A ENILIVE 2026/2027", "n. 208", "24 giugno 2026"]
    lines.extend(f"{index} GIORNATA" for index in range(1, 6))
    clubs = [f"SerieClub{index:02d}" for index in range(20)]
    for index in range(10):
        lines.append(f"22/08/2026 Sabato 18.30 {clubs[index]}-{clubs[index + 10]} DAZN")
    for index in range(10):
        game = f"{clubs[index + 10]}-{clubs[(index + 1) % 10]}"
        if ambiguous_in_horizon and index == 0:
            game = "Lazio-Milan/Sassuolo-Juventus"
        lines.append(f"29/08/2026 Sabato 18.30 {game} DAZN")
    for index in range(30):
        if missing_later_row and index == 10:
            continue
        date = (
            datetime(2026, 9, 20)
            if ambiguous_outside_horizon and index == 29
            else datetime(2026, 9, 4) + timedelta(days=index // 10)
        )
        game = (
            "Lazio-Milan/Sassuolo-Juventus"
            if ambiguous_outside_horizon and index == 29
            else f"{clubs[index % 20]}-{clubs[(index + 7) % 20]}"
        )
        lines.append(f"{date.strftime('%d/%m/%Y')} Sabato 15.00 {game} DAZN")
    return "\n".join(lines)


def ligue1_bundle(
    *,
    identical: bool = False,
    extra: bool = False,
    missing_id: bool = False,
    wrong_gameweek: bool = False,
    naive_date: bool = False,
    conflicting_club_name: bool = False,
) -> tuple[bytes, tuple[bytes, ...]]:
    season_start = datetime(2026, 8, 21, 18, 45, tzinfo=UTC)
    calendar_rows: list[dict[str, object]] = []
    gameweek_payloads: list[bytes] = []
    for gameweek in range(1, 35):
        first_kickoff = season_start + timedelta(days=7 * (gameweek - 1))
        match_ids = [gameweek * 100 + index for index in range(9)]
        calendar_rows.append(
            {
                "gameWeekNumber": gameweek,
                "matchesIds": match_ids,
                "startDate": (first_kickoff - timedelta(hours=2)).isoformat(),
                "endDate": (first_kickoff + timedelta(days=2, hours=5)).isoformat(),
                "displayEndDate": (first_kickoff + timedelta(days=2, hours=5)).isoformat(),
                "lastRegularMatchDate": (first_kickoff + timedelta(days=2, hours=5)).isoformat(),
            }
        )
        if gameweek not in {2, 3, 4}:
            continue
        matches: list[dict[str, object]] = []
        for index, match_id in enumerate(match_ids):
            home_id = index + 1
            away_id = index + 10
            if identical and gameweek == 2 and index == 0:
                away_id = home_id
            kickoff = first_kickoff + timedelta(hours=6 * index)
            home_name = f"Ligue Club {home_id:02d}"
            if conflicting_club_name and gameweek == 3 and index == 0:
                home_name = "Conflicting Ligue Club"
            matches.append(
                {
                    "unknownMatch": False,
                    "matchId": match_id,
                    "championshipId": 1,
                    "gameWeekNumber": (
                        gameweek + 1
                        if wrong_gameweek and gameweek == 2 and index == 0
                        else gameweek
                    ),
                    "date": (
                        kickoff.replace(tzinfo=None).isoformat()
                        if naive_date and gameweek == 2 and index == 0
                        else kickoff.isoformat()
                    ),
                    "home": {
                        "clubId": home_id,
                        "clubIdentity": {"id": home_id, "name": home_name},
                    },
                    "away": {
                        "clubId": away_id,
                        "clubIdentity": {"id": away_id, "name": f"Ligue Club {away_id:02d}"},
                    },
                }
            )
        if missing_id and gameweek == 2:
            matches[0]["matchId"] = 999999
        if extra and gameweek == 2:
            matches.append(dict(matches[-1]))
        gameweek_payloads.append(json.dumps({"matches": matches}, sort_keys=True).encode())
    return (
        json.dumps({"gameWeeks": calendar_rows}, sort_keys=True).encode(),
        tuple(gameweek_payloads),
    )


def test_source_plan_accepts_exact_five_league_adapters_and_offset_300() -> None:
    plan = load_official_source_plan_bytes(plan_payload())
    assert len(plan.sources) == 5
    assert len(plan.canonical_sha256) == 64
    assert plan.source("soccer_spain_la_liga").url.endswith("offset=300")
    assert plan.source("soccer_france_ligue_one").url == LIGUE1_CALENDAR_URL
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_PLAN_INVALID"):
        load_official_source_plan_bytes(plan_payload().replace(b"2026-2027", b"2025-2026"))
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_PLAN_INVALID"):
        load_official_source_plan_bytes(
            plan_payload().replace(b'"season":', b'"season":"x","season":')
        )
    for unsafe_url in (
        b"https://www.premierleague.com:444/en/news/season",
        b"https://www.premierleague.com/en/news/season#fragment",
    ):
        with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_URL_INVALID"):
            load_official_source_plan_bytes(
                plan_payload().replace(URLS["soccer_epl"].encode(), unsafe_url)
            )
    with pytest.raises(OfficialScheduleSourceError, match="LIGUE1_CALENDAR_AUTHORITY_INVALID"):
        load_official_source_plan_bytes(
            plan_payload().replace(
                LIGUE1_CALENDAR_URL.encode(),
                b"https://ma-api.ligue1.fr/championship-calendar/1?season=2025",
            )
        )


def test_source_plan_rejects_laliga_wrong_page_and_provider_hostname_before_connection() -> None:
    with pytest.raises(
        OfficialScheduleSourceError,
        match="LALIGA_PAGINATION_AUTHORITY_INVALID",
    ):
        load_official_source_plan_bytes(
            plan_payload(laliga_url=URLS["soccer_spain_la_liga"].replace("offset=300", "offset=0"))
        )
    provider = replace(source("soccer_epl"), url="https://api.the-odds-api.com/v4/sports")
    with pytest.raises(OfficialScheduleSourceError) as raised:
        fetch_official_schedule_source(provider, fetcher=ForbiddenFetcher(), observed_at_utc=NOW)
    assert raised.value.code == "OFFICIAL_SOURCE_PROVIDER_HOST_FORBIDDEN"
    assert raised.value.receipt is not None
    assert raised.value.receipt.byte_count == 0


def test_fetch_boundary_rejects_external_redirect_wrong_type_and_oversize() -> None:
    selected = source("soccer_epl")
    external = FakeFetcher(
        OfficialHttpResponse(
            status_code=200,
            final_url="https://evil.example/schedule",
            content_type="text/html",
            body=b"never accepted",
            redirect_chain=(RedirectHop(selected.url, 302, "https://evil.example/schedule"),),
        )
    )
    with pytest.raises(OfficialScheduleSourceError) as redirected:
        fetch_official_schedule_source(selected, fetcher=external, observed_at_utc=NOW)
    assert redirected.value.code == "OFFICIAL_SOURCE_HOST_FORBIDDEN"
    assert redirected.value.receipt is not None
    assert redirected.value.receipt.accepted is False

    wrong_type = FakeFetcher(OfficialHttpResponse(200, selected.url, "application/json", b"{}"))
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_CONTENT_TYPE_INVALID"):
        fetch_official_schedule_source(selected, fetcher=wrong_type, observed_at_utc=NOW)

    oversize = FakeFetcher(
        OfficialHttpResponse(
            200,
            selected.url,
            "text/html",
            b"x" * (MAXIMUM_SOURCE_BYTES + 1),
        )
    )
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_RESPONSE_TOO_LARGE"):
        fetch_official_schedule_source(selected, fetcher=oversize, observed_at_utc=NOW)


def test_public_apis_reject_crosswired_adapter_and_forged_receipt() -> None:
    crosswired = replace(source("soccer_epl"), adapter=LALIGA_PUBLIC_MATCHES_JSON_V1)
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_SPORT_ADAPTER_MISMATCH"):
        fetch_official_schedule_source(
            crosswired,
            fetcher=ForbiddenFetcher(),
            observed_at_utc=NOW,
        )
    result = accepted_result("soccer_epl", epl_payload())
    forged = replace(
        result,
        receipt=replace(
            result.receipt,
            final_url="https://evil.example/forged",
            official_domain="evil.example",
            http_status=201,
            byte_count=len(result.raw_bytes) + 1,
        ),
    )
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_FETCH_RECEIPT_INVALID"):
        build_official_schedule_evidence(
            source("soccer_epl"),
            forged,
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )


def test_epl_adapter_requires_complete_380_and_converts_london_to_utc() -> None:
    evidence = build_official_schedule_evidence(
        source("soccer_epl"),
        accepted_result("soccer_epl", epl_payload()),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(evidence.fixtures) == 20
    assert evidence.fixtures[0].kickoff_utc.hour == 14
    serialized = evidence.to_json()
    assert serialized["adapter_revision"] == PREMIER_LEAGUE_FULL_SEASON_HTML_V1
    assert serialized["parser_metadata"]["full_source_fixture_count"] == 380
    with pytest.raises(OfficialScheduleSourceError, match="EPL_FULL_SEASON_COMPLETENESS_INVALID"):
        build_official_schedule_evidence(
            source("soccer_epl"),
            accepted_result(
                "soccer_epl", epl_payload().replace(b"Club 00 v Club 01", b"Club 00 v Club 00", 1)
            ),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )
    with pytest.raises(OfficialScheduleSourceError, match="EPL_HORIZON_KICKOFF_UNCONFIRMED"):
        build_official_schedule_evidence(
            source("soccer_epl"),
            accepted_result("soccer_epl", epl_payload(missing_time_round=2)),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )
    outside_unconfirmed = build_official_schedule_evidence(
        source("soccer_epl"),
        accepted_result("soccer_epl", epl_payload(missing_time_round=0)),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(outside_unconfirmed.fixtures) == 20
    assert outside_unconfirmed.parser_metadata["unconfirmed_kickoff_count_outside_horizon"] == 10


def test_laliga_adapter_rejects_duplicate_missing_kickoff_and_naive_time() -> None:
    evidence = build_official_schedule_evidence(
        source("soccer_spain_la_liga"),
        accepted_result("soccer_spain_la_liga", laliga_payload()),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(evidence.fixtures) == 80
    for payload, code in (
        (laliga_payload(duplicate=True), "LALIGA_PAGINATION_AUTHORITY_INVALID"),
        (laliga_payload(foreign_club=True), "LALIGA_PAGINATION_AUTHORITY_INVALID"),
        (laliga_payload(self_match=True), "LALIGA_PAGINATION_AUTHORITY_INVALID"),
        (laliga_payload(missing_kickoff=True), "OFFICIAL_SCHEDULE_KICKOFF_MISSING"),
        (laliga_payload(midnight_placeholder=True), "OFFICIAL_SCHEDULE_KICKOFF_PLACEHOLDER"),
        (laliga_payload().replace(b"Z", b"", 1), "OFFICIAL_SCHEDULE_KICKOFF_TIMEZONE_INVALID"),
    ):
        with pytest.raises(OfficialScheduleSourceError) as raised:
            build_official_schedule_evidence(
                source("soccer_spain_la_liga"),
                accepted_result("soccer_spain_la_liga", payload),
                horizon_not_before_utc=NOW,
                horizon_expires_at_utc=HORIZON_END,
            )
        assert raised.value.code == code

    outside_placeholder = json.loads(laliga_payload())
    outside_placeholder["matches"][0]["date"] = "2026-10-11T00:00:00Z"
    accepted = build_official_schedule_evidence(
        source("soccer_spain_la_liga"),
        accepted_result(
            "soccer_spain_la_liga",
            json.dumps(outside_placeholder, sort_keys=True).encode(),
        ),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(accepted.fixtures) == 79


def test_bundesliga_adapter_rejects_partial_dated_horizon() -> None:
    evidence = build_official_schedule_evidence(
        source("soccer_germany_bundesliga"),
        accepted_result("soccer_germany_bundesliga", bundesliga_payload()),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(evidence.fixtures) == 45
    with pytest.raises(OfficialScheduleSourceError, match="BUNDESLIGA_HORIZON_PARTIAL"):
        build_official_schedule_evidence(
            source("soccer_germany_bundesliga"),
            accepted_result("soccer_germany_bundesliga", bundesliga_payload(partial=True)),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )
    with pytest.raises(
        OfficialScheduleSourceError,
        match="BUNDESLIGA_EXACT_DATED_TABLE_INVALID",
    ):
        build_official_schedule_evidence(
            source("soccer_germany_bundesliga"),
            accepted_result(
                "soccer_germany_bundesliga",
                bundesliga_payload(foreign_club=True),
            ),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )


def test_serie_a_adapter_uses_injected_pdf_tool_and_rejects_ambiguous_table() -> None:
    valid_text = serie_a_text()
    evidence = build_official_schedule_evidence(
        source("soccer_italy_serie_a"),
        accepted_result("soccer_italy_serie_a", b"synthetic-pdf"),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
        pdf_text_extractor=lambda _: valid_text,
    )
    assert len(evidence.fixtures) == 40
    with pytest.raises(OfficialScheduleSourceError, match="SERIE_A_AMBIGUOUS_TABLE"):
        build_official_schedule_evidence(
            source("soccer_italy_serie_a"),
            accepted_result("soccer_italy_serie_a", b"ambiguous-pdf"),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
            pdf_text_extractor=lambda _: serie_a_text(ambiguous_in_horizon=True),
        )
    with pytest.raises(OfficialScheduleSourceError, match="SERIE_A_TABLE_COMPLETENESS_INVALID"):
        build_official_schedule_evidence(
            source("soccer_italy_serie_a"),
            accepted_result("soccer_italy_serie_a", b"partial-pdf"),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
            pdf_text_extractor=lambda _: serie_a_text(missing_later_row=True),
        )
    forward_ambiguous = build_official_schedule_evidence(
        source("soccer_italy_serie_a"),
        accepted_result("soccer_italy_serie_a", b"forward-ambiguous-pdf"),
        horizon_not_before_utc=NOW,
        horizon_expires_at_utc=HORIZON_END,
        pdf_text_extractor=lambda _: serie_a_text(ambiguous_outside_horizon=True),
    )
    assert len(forward_ambiguous.fixtures) == 39


def test_serie_a_default_pdf_extractor_is_available_in_project_runtime() -> None:
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    assert default_pdf_text_extractor(stream.getvalue()) == ""


def test_ligue1_calendar_bundle_is_complete_and_each_fixture_has_gameweek_provenance() -> None:
    selected = source("soccer_france_ligue_one")
    calendar, gameweeks = ligue1_bundle()
    result = accepted_result(
        "soccer_france_ligue_one",
        calendar,
        supporting_payloads=gameweeks[:2],
    )
    evidence = build_official_schedule_evidence(
        selected,
        result,
        horizon_not_before_utc=datetime(2026, 8, 29, tzinfo=UTC),
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(evidence.fixtures) == 17
    assert all(item.kickoff_utc >= datetime(2026, 8, 29, tzinfo=UTC) for item in evidence.fixtures)
    assert evidence.parser_metadata["gameweeks_fetched"] == [2, 3]
    assert evidence.parser_metadata["calendar_ids_expected"] == 18
    assert evidence.parser_metadata["calendar_ids_accounted"] == 18
    assert evidence.parser_metadata["calendar_gameweeks_total"] == 34
    assert evidence.parser_metadata["calendar_match_ids_total"] == 306
    assert evidence.parser_metadata["calendar_club_identities_total"] == 18
    assert len(str(evidence.parser_metadata["calendar_club_identities_sha256"])) == 64
    assert evidence.parser_metadata["complete_official_horizon"] is True
    assert all(item.source_pointer is not None for item in evidence.fixtures)
    assert {item.source_authority for item in evidence.fixtures} == {
        LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=2),
        LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=3),
    }

    invalid_bundles = (
        (ligue1_bundle(identical=True), "LIGUE1_GAMEWEEK_AUTHORITY_INVALID"),
        (ligue1_bundle(extra=True), "LIGUE1_GAMEWEEK_AUTHORITY_INVALID"),
        (ligue1_bundle(missing_id=True), "LIGUE1_GAMEWEEK_AUTHORITY_INVALID"),
        (ligue1_bundle(wrong_gameweek=True), "LIGUE1_GAMEWEEK_AUTHORITY_INVALID"),
        (ligue1_bundle(naive_date=True), "LIGUE1_GAMEWEEK_AUTHORITY_INVALID"),
        (
            ligue1_bundle(conflicting_club_name=True),
            "LIGUE1_CLUB_IDENTITY_INCONSISTENT",
        ),
    )
    for (invalid_calendar, invalid_gameweeks), code in invalid_bundles:
        with pytest.raises(OfficialScheduleSourceError, match=code):
            build_official_schedule_evidence(
                selected,
                accepted_result(
                    "soccer_france_ligue_one",
                    invalid_calendar,
                    supporting_payloads=invalid_gameweeks[:2],
                    supporting_gameweeks=(2, 3),
                ),
                horizon_not_before_utc=datetime(2026, 8, 29, tzinfo=UTC),
                horizon_expires_at_utc=HORIZON_END,
            )

    with pytest.raises(OfficialScheduleSourceError, match="LIGUE1_GAMEWEEK_BUNDLE_INCOMPLETE"):
        build_official_schedule_evidence(
            selected,
            accepted_result(
                "soccer_france_ligue_one",
                calendar,
                supporting_payloads=gameweeks[:1],
            ),
            horizon_not_before_utc=datetime(2026, 8, 29, tzinfo=UTC),
            horizon_expires_at_utc=HORIZON_END,
        )

    truncated = json.loads(calendar)
    truncated["gameWeeks"] = [
        item for item in truncated["gameWeeks"] if item["gameWeekNumber"] != 4
    ]
    with pytest.raises(
        OfficialScheduleSourceError,
        match="LIGUE1_CALENDAR_COMPLETENESS_INVALID",
    ):
        build_official_schedule_evidence(
            selected,
            accepted_result(
                "soccer_france_ligue_one",
                json.dumps(truncated, sort_keys=True).encode(),
                supporting_payloads=(gameweeks[1],),
                supporting_gameweeks=(3,),
            ),
            horizon_not_before_utc=datetime(2026, 9, 1, tzinfo=UTC),
            horizon_expires_at_utc=datetime(2026, 9, 15, tzinfo=UTC),
        )


def test_ligue1_fetcher_reads_calendar_first_then_bounded_gameweeks_without_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar, gameweeks = ligue1_bundle()
    selected = source("soccer_france_ligue_one")
    payload_by_url = {
        selected.url: calendar,
        **{
            LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=gameweek): payload
            for gameweek, payload in zip((2, 3, 4), gameweeks, strict=True)
        },
    }
    calls: list[tuple[str, int | None]] = []
    fetcher = BuiltinHttpsOfficialScheduleFetcher(
        horizon_not_before_utc=datetime(2026, 8, 29, tzinfo=UTC),
        horizon_expires_at_utc=datetime(2026, 9, 12, tzinfo=UTC),
    )

    def fake_request(
        requested_source: OfficialSourceSpec,
        requested_url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        maximum_redirects: int | None = None,
    ) -> OfficialHttpResponse:
        assert requested_source == selected
        assert extra_headers is None
        calls.append((requested_url, maximum_redirects))
        return OfficialHttpResponse(
            200,
            requested_url,
            "application/json",
            payload_by_url[requested_url],
        )

    monkeypatch.setattr(fetcher, "_request", fake_request)
    response = fetcher.fetch(selected)
    assert calls == [
        (selected.url, 0),
        (LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=2), 0),
        (LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=3), 0),
        (LIGUE1_GAMEWEEK_URL_TEMPLATE.format(gameweek=4), 0),
    ]
    assert response.body == calendar
    assert response.supporting_official_raw_bytes == gameweeks

    start = datetime(2026, 8, 29, tzinfo=UTC)
    rows = []
    for gameweek in range(1, 35):
        boundary = (
            start + timedelta(days=gameweek - 1)
            if gameweek <= 6
            else start + timedelta(days=30 + 7 * (gameweek - 7))
        )
        rows.append(
            {
                "gameWeekNumber": gameweek,
                "matchesIds": [gameweek * 100 + index for index in range(9)],
                "startDate": boundary.isoformat(),
                "endDate": (boundary + timedelta(hours=12)).isoformat(),
                "displayEndDate": (boundary + timedelta(hours=12)).isoformat(),
                "lastRegularMatchDate": (boundary + timedelta(hours=12)).isoformat(),
            }
        )
    oversized_calendar = json.dumps({"gameWeeks": rows}, sort_keys=True).encode()
    limit_calls: list[str] = []
    limited = BuiltinHttpsOfficialScheduleFetcher(
        horizon_not_before_utc=start,
        horizon_expires_at_utc=start + timedelta(days=14),
    )

    def calendar_only(
        _requested_source: OfficialSourceSpec,
        requested_url: str,
        *,
        extra_headers: dict[str, str] | None = None,
        maximum_redirects: int | None = None,
    ) -> OfficialHttpResponse:
        assert extra_headers is None
        assert maximum_redirects == 0
        limit_calls.append(requested_url)
        return OfficialHttpResponse(200, requested_url, "application/json", oversized_calendar)

    monkeypatch.setattr(limited, "_request", calendar_only)
    with pytest.raises(OfficialScheduleSourceError, match="LIGUE1_GAMEWEEK_READ_LIMIT_EXCEEDED"):
        limited.fetch(selected)
    assert limit_calls == [selected.url]


def test_physical_dispatch_callback_precedes_network_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class FailingConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> None:
            assert observed == [URLS["soccer_germany_bundesliga"]]
            raise OSError("synthetic timeout after dispatch")

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(
        official_sources_module.http.client,
        "HTTPSConnection",
        FailingConnection,
    )
    fetcher = BuiltinHttpsOfficialScheduleFetcher(on_dispatch=observed.append)
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_NETWORK_FAILED"):
        fetcher.fetch(source("soccer_germany_bundesliga"))
    assert observed == [URLS["soccer_germany_bundesliga"]]


def test_official_body_is_observed_before_oversize_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"x" * 11

    class Response:
        status = 200

        @staticmethod
        def getheader(name: str, default: str | None = None) -> str | None:
            return "text/html" if name == "Content-Type" else default

        @staticmethod
        def getheaders() -> list[tuple[str, str]]:
            return [("Content-Type", "text/html")]

        @staticmethod
        def read(_amount: int) -> bytes:
            return body

    class Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def getresponse() -> Response:
            return Response()

        @staticmethod
        def close() -> None:
            pass

    observed: list[bytes] = []
    partial: list[bytes] = []
    monkeypatch.setattr(official_sources_module.http.client, "HTTPSConnection", Connection)
    fetcher = BuiltinHttpsOfficialScheduleFetcher(
        maximum_bytes=10,
        on_response=lambda response: observed.append(response.body),
        on_partial_response=lambda response: partial.append(response.body),
    )
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_RESPONSE_TOO_LARGE"):
        fetcher.fetch(source("soccer_epl"))
    assert observed == []
    assert partial == [body]


def test_official_incomplete_body_is_sent_to_partial_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = b"partial-body"

    class Response:
        status = 200

        @staticmethod
        def getheader(name: str, default: str | None = None) -> str | None:
            return "text/html" if name == "Content-Type" else default

        @staticmethod
        def getheaders() -> list[tuple[str, str]]:
            return [("Content-Type", "text/html")]

        @staticmethod
        def read(_amount: int) -> bytes:
            raise official_sources_module.http.client.IncompleteRead(partial, 100)

    class Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def getresponse() -> Response:
            return Response()

        @staticmethod
        def close() -> None:
            pass

    observed: list[bytes] = []
    monkeypatch.setattr(official_sources_module.http.client, "HTTPSConnection", Connection)
    fetcher = BuiltinHttpsOfficialScheduleFetcher(
        on_partial_response=lambda response: observed.append(response.body),
    )
    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_NETWORK_FAILED"):
        fetcher.fetch(source("soccer_epl"))
    assert observed == [partial]


def test_official_slow_final_read_is_sent_to_partial_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick = [0.0]

    class Response:
        status = 200

        @staticmethod
        def getheader(name: str, default: str | None = None) -> str | None:
            return "text/html" if name == "Content-Type" else default

        @staticmethod
        def getheaders() -> list[tuple[str, str]]:
            return [("Content-Type", "text/html")]

        @staticmethod
        def read(_amount: int) -> bytes:
            tick[0] = 99.0
            return b"observed-before-deadline"

    class Connection:
        sock = None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def getresponse() -> Response:
            return Response()

        @staticmethod
        def close() -> None:
            pass

    partial: list[bytes] = []
    monkeypatch.setattr(official_sources_module.http.client, "HTTPSConnection", Connection)
    fetcher = BuiltinHttpsOfficialScheduleFetcher(
        timeout_seconds=1,
        monotonic=lambda: tick[0],
        on_partial_response=lambda response: partial.append(response.body),
    )

    with pytest.raises(OfficialScheduleSourceError, match="OFFICIAL_SOURCE_NETWORK_FAILED"):
        fetcher.fetch(source("soccer_epl"))

    assert partial == [b"observed-before-deadline"]


@pytest.mark.parametrize(
    ("anchor", "supporting_slice", "gameweeks"),
    (
        (datetime(2026, 8, 29, tzinfo=UTC), slice(None), (2, 3, 4)),
        (datetime(2026, 8, 31, tzinfo=UTC), slice(1, None), (3, 4)),
        (datetime(2026, 9, 1, 23, 59, 59, tzinfo=UTC), slice(1, None), (3, 4)),
    ),
)
def test_ligue1_rolling_fourteen_day_horizon_remains_complete_after_matchday_two(
    anchor: datetime,
    supporting_slice: slice,
    gameweeks: tuple[int, ...],
) -> None:
    calendar, all_gameweeks = ligue1_bundle()
    expires = anchor + timedelta(days=14)
    evidence = build_official_schedule_evidence(
        source("soccer_france_ligue_one"),
        accepted_result(
            "soccer_france_ligue_one",
            calendar,
            supporting_payloads=all_gameweeks[supporting_slice],
            supporting_gameweeks=gameweeks,
        ),
        horizon_not_before_utc=anchor,
        horizon_expires_at_utc=expires,
    )
    assert evidence.fixtures
    assert evidence.parser_metadata["gameweeks_fetched"] == list(gameweeks)
    assert evidence.parser_metadata["complete_official_horizon"] is True
    assert all(anchor <= item.kickoff_utc < expires for item in evidence.fixtures)
    assert any(item.round_number == 4 for item in evidence.fixtures)
