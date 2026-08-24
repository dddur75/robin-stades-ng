from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pypdf import PdfWriter

from robin.capture.official_schedule_sources import (
    DFB_DATACENTER_HTML_V1,
    LALIGA_PUBLIC_MATCHES_JSON_V1,
    LEGA_SERIE_A_CALENDAR_PDF_V1,
    LIGUE1_PROGRAMMATION_HTML_V1,
    MAXIMUM_SOURCE_BYTES,
    PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
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
    "soccer_france_ligue_one": "https://ligue1.com/fr/articles/j2",
}
ADAPTERS = {
    "soccer_epl": PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    "soccer_spain_la_liga": LALIGA_PUBLIC_MATCHES_JSON_V1,
    "soccer_germany_bundesliga": DFB_DATACENTER_HTML_V1,
    "soccer_italy_serie_a": LEGA_SERIE_A_CALENDAR_PDF_V1,
    "soccer_france_ligue_one": LIGUE1_PROGRAMMATION_HTML_V1,
}
CONTENT_TYPES = {
    "soccer_epl": "text/html; charset=utf-8",
    "soccer_spain_la_liga": "application/json",
    "soccer_germany_bundesliga": "text/html",
    "soccer_italy_serie_a": "application/pdf",
    "soccer_france_ligue_one": "text/html",
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


def accepted_result(sport_key: str, payload: bytes) -> OfficialFetchResult:
    selected = source(sport_key)
    supporting_raw = (
        b'<script id="__NEXT_DATA__">'
        b'{"runtimeConfig":{"backendSubscription":"public-test-subscription"}}'
        b"</script>"
    )
    supporting = (
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
    fetcher = FakeFetcher(
        OfficialHttpResponse(
            status_code=200,
            final_url=selected.url,
            content_type=CONTENT_TYPES[sport_key],
            body=payload,
            supporting_official_reads=supporting,
            supporting_official_raw_bytes=(supporting_raw,) if supporting else (),
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


def ligue1_payload(*, identical: bool = False, extra: bool = False) -> bytes:
    games = [
        ("Vendredi 28 août à 20h45 sur Ligue 1+", [("LOSC", "Paris SG")]),
        ("Samedi 29 août à 17h15 sur Ligue 1+", [("Strasbourg", "Lens")]),
        (
            "Samedi 29 août à 20h45 sur Ligue 1+",
            [
                ("Lyon", "Le Havre"),
                ("Lorient", "Troyes"),
                ("Brest", "Toulouse"),
                ("Auxerre", "Angers"),
            ],
        ),
        ("Dimanche 30 août à 15h00 sur Ligue 1+", [("Paris FC", "Nice")]),
        ("Dimanche 30 août à 17h15 sur Ligue 1+", [("Rennes", "Le Mans")]),
        ("Dimanche 30 août 2026 à 20h45 sur Ligue 1+", [("Monaco", "Marseille")]),
    ]
    if identical:
        games[0] = (games[0][0], [("LOSC", "LOSC")])
    if extra:
        games[-1][1].append(("Extra FC", "Drift FC"))
    paragraphs = "".join(
        f"<p>{heading}<br>{'<br>'.join(f'{home} – {away}' for home, away in fixtures)}</p>"
        for heading, fixtures in games
    )
    return (
        f"<html><title>2e journée 2026/27 Ligue 1 McDonald's</title>{paragraphs}</html>"
    ).encode()


def test_source_plan_accepts_exact_five_league_adapters_and_offset_300() -> None:
    plan = load_official_source_plan_bytes(plan_payload())
    assert len(plan.sources) == 5
    assert len(plan.canonical_sha256) == 64
    assert plan.source("soccer_spain_la_liga").url.endswith("offset=300")
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


def test_ligue1_forward_horizon_excludes_past_fixture_without_requiring_past_day() -> None:
    selected = source("soccer_france_ligue_one")
    result = accepted_result("soccer_france_ligue_one", ligue1_payload())
    evidence = build_official_schedule_evidence(
        selected,
        result,
        horizon_not_before_utc=datetime(2026, 8, 29, tzinfo=UTC),
        horizon_expires_at_utc=HORIZON_END,
    )
    assert len(evidence.fixtures) == 8
    assert all(item.kickoff_utc >= datetime(2026, 8, 29, tzinfo=UTC) for item in evidence.fixtures)
    with pytest.raises(OfficialScheduleSourceError):
        build_official_schedule_evidence(
            selected,
            accepted_result("soccer_france_ligue_one", ligue1_payload(identical=True)),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )
    with pytest.raises(OfficialScheduleSourceError, match="LIGUE1_FORWARD_HORIZON_INCOMPLETE"):
        build_official_schedule_evidence(
            selected,
            accepted_result("soccer_france_ligue_one", ligue1_payload(extra=True)),
            horizon_not_before_utc=NOW,
            horizon_expires_at_utc=HORIZON_END,
        )
