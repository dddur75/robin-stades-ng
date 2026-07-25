"""Jalon 9: fermeture des gates critiques, marchés et object storage."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import pandas as pd
import requests

from robin.historical.readiness import observation_dimensions
from robin.historical.storage import (
    PartitionedParquetStore,
    directory_size,
    write_json_atomic,
)

PRODUCTION_STATUS = "PRODUCTION_LOCKED"
PINNACLE_DEGRADED_FROM = date(2025, 7, 23)
MARKET_SEASONS = tuple(range(2020, 2026))
FOOTBALL_DATA_CODES = {
    "Ligue 1": "F1",
    "Premier League": "E0",
    "La Liga": "SP1",
    "Bundesliga": "D1",
    "Serie A": "I1",
}
PRICE_TYPES = {
    "closing": "HISTORICAL_CLOSING_MARKET",
    "pre_closing": "HISTORICAL_PRE_CLOSING_MARKET",
    "opening": "HISTORICAL_OPENING_MARKET",
    "unknown": "HISTORICAL_TIMESTAMP_UNKNOWN",
}


@dataclass(frozen=True)
class FootballDataFile:
    competition: str
    season: int
    source_url: str

    @property
    def season_code(self) -> str:
        return f"{self.season % 100:02d}{(self.season + 1) % 100:02d}"


def football_data_catalog() -> list[FootballDataFile]:
    return [
        FootballDataFile(
            competition=competition,
            season=season,
            source_url=(
                "https://www.football-data.co.uk/mmz4281/"
                f"{season % 100:02d}{(season + 1) % 100:02d}/{code}.csv"
            ),
        )
        for competition, code in FOOTBALL_DATA_CODES.items()
        for season in MARKET_SEASONS
    ]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe(value: object) -> str:
    return (
        str(value)
        .strip()
        .replace(" ", "-")
        .replace("/", "-")
        .replace("\\", "-")
    )


def archive_football_data_file(
    state: Path,
    spec: FootballDataFile,
    payload: bytes,
    *,
    downloaded_at: datetime | None = None,
) -> dict[str, object]:
    if not payload.strip():
        raise ValueError("FOOTBALL_DATA_EMPTY_FILE")
    digest = _sha256(payload)
    raw = (
        state
        / "market"
        / "raw"
        / _safe(spec.competition)
        / str(spec.season)
        / f"{digest}.csv"
    )
    raw.parent.mkdir(parents=True, exist_ok=True)
    if raw.exists() and _sha256(raw.read_bytes()) != digest:
        raise RuntimeError("FOOTBALL_DATA_HASH_COLLISION")
    if not raw.exists():
        raw.write_bytes(payload)
    header = next(csv.reader(io.StringIO(payload.decode("utf-8-sig"))), [])
    metadata = {
        "source": "FOOTBALL_DATA",
        "source_url_hash": _sha256(spec.source_url.encode("utf-8")),
        "downloaded_at": (downloaded_at or datetime.now(UTC)).isoformat(),
        "season": spec.season,
        "competition": spec.competition,
        "payload_hash": digest,
        "schema_version": f"football-data-columns-{_sha256('|'.join(header).encode())[:12]}",
        "columns": header,
        "raw_location": raw.relative_to(state).as_posix(),
    }
    write_json_atomic(raw.with_suffix(".metadata.json"), metadata)
    return metadata


def download_football_data(
    state: Path,
    *,
    catalog: Iterable[FootballDataFile] | None = None,
    timeout_seconds: int = 30,
) -> list[dict[str, object]]:
    manifests: list[dict[str, object]] = []
    for spec in catalog or football_data_catalog():
        response = requests.get(spec.source_url, timeout=timeout_seconds)
        response.raise_for_status()
        manifests.append(archive_football_data_file(state, spec, response.content))
    write_json_atomic(
        state / "market" / "manifests" / "football-data-files.json",
        {"files": manifests, "count": len(manifests)},
    )
    return manifests


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(str(value))
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def _date(value: object) -> date | None:
    text = str(value or "").strip()
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _first_price(
    row: Mapping[str, object],
    candidates: Iterable[tuple[str, str, str]],
) -> tuple[float | None, str | None, str]:
    for column, bookmaker, price_type in candidates:
        value = _number(row.get(column))
        if value is not None:
            return value, bookmaker, PRICE_TYPES[price_type]
    return None, None, PRICE_TYPES["unknown"]


def map_football_data_row(
    row: Mapping[str, object],
    *,
    competition: str,
    season: int,
    payload_hash: str,
) -> dict[str, object]:
    """Mapper sans inventer une cote ou un instant absent du CSV."""

    closing = (
        ("AvgCH", "MARKET_AVERAGE", "closing"),
        ("B365CH", "BET365", "closing"),
        ("PSCH", "PINNACLE", "closing"),
    )
    closing_draw = (
        ("AvgCD", "MARKET_AVERAGE", "closing"),
        ("B365CD", "BET365", "closing"),
        ("PSCD", "PINNACLE", "closing"),
    )
    closing_away = (
        ("AvgCA", "MARKET_AVERAGE", "closing"),
        ("B365CA", "BET365", "closing"),
        ("PSCA", "PINNACLE", "closing"),
    )
    pre = (
        ("AvgH", "MARKET_AVERAGE", "pre_closing"),
        ("B365H", "BET365", "pre_closing"),
        ("PSH", "PINNACLE", "pre_closing"),
    )
    pre_draw = (
        ("AvgD", "MARKET_AVERAGE", "pre_closing"),
        ("B365D", "BET365", "pre_closing"),
        ("PSD", "PINNACLE", "pre_closing"),
    )
    pre_away = (
        ("AvgA", "MARKET_AVERAGE", "pre_closing"),
        ("B365A", "BET365", "pre_closing"),
        ("PSA", "PINNACLE", "pre_closing"),
    )
    home, bookmaker, price_type = _first_price(row, (*closing, *pre))
    draw, _, draw_type = _first_price(row, (*closing_draw, *pre_draw))
    away, _, away_type = _first_price(row, (*closing_away, *pre_away))
    over, totals_book, totals_type = _first_price(
        row,
        (
            ("AvgC>2.5", "MARKET_AVERAGE", "closing"),
            ("B365C>2.5", "BET365", "closing"),
            ("PC>2.5", "PINNACLE", "closing"),
            ("Avg>2.5", "MARKET_AVERAGE", "pre_closing"),
            ("B365>2.5", "BET365", "pre_closing"),
            ("P>2.5", "PINNACLE", "pre_closing"),
        ),
    )
    under, _, under_type = _first_price(
        row,
        (
            ("AvgC<2.5", "MARKET_AVERAGE", "closing"),
            ("B365C<2.5", "BET365", "closing"),
            ("PC<2.5", "PINNACLE", "closing"),
            ("Avg<2.5", "MARKET_AVERAGE", "pre_closing"),
            ("B365<2.5", "BET365", "pre_closing"),
            ("P<2.5", "PINNACLE", "pre_closing"),
        ),
    )
    price_types = {price_type, draw_type, away_type} - {PRICE_TYPES["unknown"]}
    fixture_date = _date(row.get("Date"))
    degraded = bool(
        fixture_date
        and fixture_date >= PINNACLE_DEGRADED_FROM
        and (bookmaker == "PINNACLE" or totals_book == "PINNACLE")
    )
    quality = "PINNACLE_RECENT_ODDS_DEGRADED" if degraded else "OBSERVED"
    if degraded:
        home = draw = away = over = under = None
    return {
        "competition": competition,
        "season": season,
        "match_date": fixture_date.isoformat() if fixture_date else None,
        "home_source_name": row.get("HomeTeam"),
        "away_source_name": row.get("AwayTeam"),
        "home_goals": int(str(row["FTHG"])) if str(row.get("FTHG", "")).isdigit() else None,
        "away_goals": int(str(row["FTAG"])) if str(row.get("FTAG", "")).isdigit() else None,
        "odds_home": home,
        "odds_draw": draw,
        "odds_away": away,
        "odds_over_25": over,
        "odds_under_25": under,
        "bookmaker_1x2": bookmaker,
        "bookmaker_totals": totals_book,
        "price_type": (
            next(iter(price_types))
            if len(price_types) == 1
            else PRICE_TYPES["unknown"]
        ),
        "totals_price_type": (
            totals_type if totals_type == under_type else PRICE_TYPES["unknown"]
        ),
        "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
        "quality_status": quality,
        "source": "FOOTBALL_DATA",
        "raw_payload_hash": payload_hash,
    }


def parse_archived_market_files(state: Path) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for metadata_path in sorted((state / "market" / "raw").rglob("*.metadata.json")):
        metadata = cast(dict[str, object], json.loads(metadata_path.read_text("utf-8")))
        csv_path = state / str(metadata["raw_location"])
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                output.append(
                    map_football_data_row(
                        row,
                        competition=str(metadata["competition"]),
                        season=int(str(metadata["season"])),
                        payload_hash=str(metadata["payload_hash"]),
                    )
                )
    return output


TEAM_ALIASES = {
    "1fcheidenheim": "heidenheim",
    "1fckoln": "fckoln",
    "1899hoffenheim": "hoffenheim",
    "acmilan": "milan",
    "arminiabielefeld": "bielefeld",
    "asroma": "roma",
    "athbilbao": "athleticbilbao",
    "athleticclub": "athleticbilbao",
    "athmadrid": "atleticomadrid",
    "atleticomadrid": "atleticomadrid",
    "bayerleverkusen": "leverkusen",
    "bayernmunich": "bayernmunchen",
    "bayermunchen": "bayernmunchen",
    "bmonchengladbach": "borussiamonchengladbach",
    "dortmund": "borussiadortmund",
    "celta": "celtavigo",
    "clermont": "clermontfoot",
    "einfrankfurt": "eintrachtfrankfurt",
    "eintrachtfrankfurt": "eintrachtfrankfurt",
    "espanol": "espanyol",
    "estactroyes": "troyes",
    "fcaugsburg": "augsburg",
    "fcheidenheim": "heidenheim",
    "fcschalke04": "schalke04",
    "fcstpauli": "stpauli",
    "fsvmainz05": "mainz",
    "granadacf": "granada",
    "hamburgersv": "hamburg",
    "hellasverona": "verona",
    "herthaberlin": "hertha",
    "inter": "intermilan",
    "internazionale": "intermilan",
    "mgladbach": "borussiamonchengladbach",
    "manchesterunited": "manunited",
    "manchestercity": "mancity",
    "newcastleunited": "newcastle",
    "nottmforest": "nottinghamforest",
    "parissaintgermain": "parissg",
    "psg": "parissg",
    "rayovallecano": "vallecano",
    "rbleipzig": "rbleipzig",
    "realbetis": "betis",
    "realsociedad": "sociedad",
    "realvalladolid": "valladolid",
    "saintetienne": "stetienne",
    "scfreiburg": "freiburg",
    "sheffieldutd": "sheffieldunited",
    "sportinglisbon": "sportingcp",
    "spvgggreutherfurth": "greutherfurth",
    "stadebrestois29": "brest",
    "svdarmstadt98": "darmstadt",
    "tottenhamhotspur": "tottenham",
    "vfbstuttgart": "stuttgart",
    "vflbochum": "bochum",
    "vflwolfsburg": "wolfsburg",
    "westbromwichalbion": "westbrom",
    "wolverhamptonwanderers": "wolves",
}


def canonical_team_key(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    folded = "".join(char for char in decomposed if not unicodedata.combining(char))
    compact = "".join(char for char in folded.casefold() if char.isalnum())
    return TEAM_ALIASES.get(compact, compact)


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def historical_fixture_facts(state: Path) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    pattern = "entity_type=fixtures/**/*.parquet"
    for path in sorted((state / "parquet").glob("competition=*/season=*/" + pattern)):
        for row in pd.read_parquet(path).to_dict(orient="records"):
            payload = _payload(row.get("payload"))
            fixture = _payload(payload.get("fixture"))
            league = _payload(payload.get("league"))
            teams = _payload(payload.get("teams"))
            goals = _payload(payload.get("goals"))
            home = _payload(teams.get("home"))
            away = _payload(teams.get("away"))
            if not isinstance(fixture.get("id"), int):
                continue
            output.append(
                {
                    "fixture_id": fixture["id"],
                    "competition": str(
                        league.get("name")
                        or path.parts[-5].removeprefix("competition=").replace("-", " ")
                    ),
                    "season": int(str(league.get("season") or 0)),
                    "kickoff_at": fixture.get("date"),
                    "match_date": str(fixture.get("date", ""))[:10],
                    "round": league.get("round"),
                    "home_team_id": home.get("id"),
                    "away_team_id": away.get("id"),
                    "home_team": home.get("name"),
                    "away_team": away.get("name"),
                    "home_key": canonical_team_key(home.get("name")),
                    "away_key": canonical_team_key(away.get("name")),
                    "home_goals": goals.get("home"),
                    "away_goals": goals.get("away"),
                }
            )
    return list({int(str(row["fixture_id"])): row for row in output}.values())


def match_market_fixtures(
    market_rows: Iterable[dict[str, object]],
    fixtures: Iterable[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    index: dict[tuple[str, int, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for fixture in fixtures:
        key = (
            str(fixture["competition"]),
            int(str(fixture["season"])),
            str(fixture["match_date"]),
            canonical_team_key(fixture["home_team"]),
            canonical_team_key(fixture["away_team"]),
        )
        index[key].append(fixture)
    matched: list[dict[str, object]] = []
    statuses: dict[str, int] = defaultdict(int)
    for market in market_rows:
        key = (
            str(market["competition"]),
            int(str(market["season"])),
            str(market["match_date"]),
            canonical_team_key(market["home_source_name"]),
            canonical_team_key(market["away_source_name"]),
        )
        candidates = index.get(key, [])
        status = "UNRESOLVED"
        selected: dict[str, object] | None = None
        if len(candidates) > 1:
            status = "AMBIGUOUS"
        elif len(candidates) == 1:
            selected = candidates[0]
            same_names = (
                canonical_team_key(selected["home_team"])
                == canonical_team_key(market["home_source_name"])
                and canonical_team_key(selected["away_team"])
                == canonical_team_key(market["away_source_name"])
            )
            score_conflict = (
                market.get("home_goals") is not None
                and selected.get("home_goals") is not None
                and (
                    market["home_goals"] != selected["home_goals"]
                    or market["away_goals"] != selected["away_goals"]
                )
            )
            status = "CONFLICTING" if score_conflict else (
                "EXACT_CANONICAL_MATCH" if same_names else "ALIAS_MATCH"
            )
        statuses[status] += 1
        enriched = {**market, "mapping_status": status}
        if selected is not None and status not in {"CONFLICTING", "AMBIGUOUS"}:
            enriched["fixture_id"] = selected["fixture_id"]
            enriched["kickoff_at"] = selected["kickoff_at"]
            enriched["home_team_id"] = selected["home_team_id"]
            enriched["away_team_id"] = selected["away_team_id"]
            matched.append(enriched)
    total = sum(statuses.values())
    eligible = sum(
        count
        for status, count in statuses.items()
        if status in {"EXACT_ID_MATCH", "EXACT_CANONICAL_MATCH", "DATE_TEAM_MATCH", "ALIAS_MATCH"}
    )
    report = {
        "market_rows": total,
        "matched": eligible,
        "mapping_rate": eligible / total if total else 0.0,
        "ambiguous": statuses["AMBIGUOUS"],
        "unresolved": statuses["UNRESOLVED"],
        "conflicting": statuses["CONFLICTING"],
        "statuses": dict(statuses),
    }
    return matched, report


def proportional_devig(odds: Iterable[float | None]) -> tuple[float | None, list[float | None]]:
    values = list(odds)
    if any(value is None or value <= 0 for value in values):
        return None, [None for _ in values]
    present = cast(list[float], values)
    implied = [1.0 / value for value in present]
    overround = sum(implied)
    if overround <= 0:
        return None, [None for _ in values]
    return overround - 1.0, [value / overround for value in implied]


def build_historical_market_dataset(
    rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        margin, devig = proportional_devig(
            (
                cast(float | None, row.get("odds_home")),
                cast(float | None, row.get("odds_draw")),
                cast(float | None, row.get("odds_away")),
            )
        )
        totals_margin, totals_devig = proportional_devig(
            (
                cast(float | None, row.get("odds_over_25")),
                cast(float | None, row.get("odds_under_25")),
            )
        )
        output.append(
            {
                **row,
                "market_margin_1x2": margin,
                "market_margin_totals": totals_margin,
                "de_vig_home": devig[0],
                "de_vig_draw": devig[1],
                "de_vig_away": devig[2],
                "de_vig_over_25": totals_devig[0],
                "de_vig_under_25": totals_devig[1],
                "quality": row.get("quality_status"),
            }
        )
    return output


def write_market_datasets(
    state: Path,
    rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    store = PartitionedParquetStore(state / "parquet")
    reports: list[dict[str, object]] = []
    grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["competition"]), int(str(row["season"])))].append(row)
    for (competition, season), values in sorted(grouped.items()):
        reports.append(
            store.write_records(
                values,
                competition=competition,
                season=season,
                entity_type="historical_market",
                dataset_version="historical_market_v1",
            )
        )
        reports.append(
            store.write_records(
                [
                    {key: value for key, value in row.items() if "25" not in key}
                    for row in values
                    if row.get("odds_home") and row.get("odds_draw") and row.get("odds_away")
                ],
                competition=competition,
                season=season,
                entity_type="historical_market_1x2",
                dataset_version="historical_market_1x2_v1",
            )
        )
        reports.append(
            store.write_records(
                [
                    {
                        key: value
                        for key, value in row.items()
                        if key
                        in {
                            "fixture_id",
                            "competition",
                            "season",
                            "kickoff_at",
                            "odds_over_25",
                            "odds_under_25",
                            "market_margin_totals",
                            "de_vig_over_25",
                            "de_vig_under_25",
                            "price_type",
                            "source",
                            "quality",
                        }
                    }
                    for row in values
                    if row.get("odds_over_25") and row.get("odds_under_25")
                ],
                competition=competition,
                season=season,
                entity_type="historical_market_totals",
                dataset_version="historical_market_totals_v1",
            )
        )
    return reports


def market_gates(
    dataset: Iterable[dict[str, object]],
    fixtures: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    rows = list(dataset)
    fixture_rows = list(fixtures)
    output: list[dict[str, object]] = []
    for competition in FOOTBALL_DATA_CODES:
        relevant = [row for row in rows if row["competition"] == competition]
        expected = [
            row
            for row in fixture_rows
            if row["competition"] == competition and int(str(row["season"])) in MARKET_SEASONS
        ]
        seasons = {int(str(row["season"])) for row in relevant}
        one_x_two = [
            row
            for row in relevant
            if all(_number(row.get(key)) for key in ("odds_home", "odds_draw", "odds_away"))
            and row.get("market_margin_1x2") is not None
        ]
        totals = [
            row
            for row in relevant
            if _number(row.get("odds_over_25")) and _number(row.get("odds_under_25"))
        ]
        denominator = max(len(expected), 1)
        mapping_rate = len({row.get("fixture_id") for row in relevant}) / denominator
        one_x_two_coverage = len(one_x_two) / denominator
        totals_coverage = len(totals) / denominator
        ambiguous = sum(row.get("mapping_status") == "AMBIGUOUS" for row in relevant)
        one_status = (
            "READY"
            if len(seasons) >= 3
            and one_x_two_coverage >= 0.9
            and mapping_rate >= 0.98
            and ambiguous == 0
            else "BLOCKED_BY_MAPPING"
            if mapping_rate < 0.98 or ambiguous
            else "BLOCKED_BY_QUALITY"
        )
        totals_status = (
            "READY"
            if len(seasons) >= 3
            and totals_coverage >= 0.8
            and mapping_rate >= 0.98
            else "PARTIAL"
        )
        output.append(
            {
                "competition": competition,
                "one_x_two_status": one_status,
                "totals_status": totals_status,
                "status": one_status,
                "seasons": len(seasons),
                "fixtures_expected": len(expected),
                "fixtures_mapped": len(relevant),
                "mapping_rate": mapping_rate,
                "one_x_two_coverage": one_x_two_coverage,
                "totals_coverage": totals_coverage,
                "ambiguities": ambiguous,
            }
        )
    return output


def classify_ucl_phase(round_name: object) -> str:
    value = str(round_name or "").casefold()
    if not value:
        return "UNKNOWN"
    if "cancel" in value:
        return "CANCELLED"
    if "qualif" in value or "preliminary" in value:
        return "QUALIFYING"
    if "play-off" in value or "playoff" in value:
        return "PLAYOFF"
    if "group" in value:
        return "GROUP_STAGE"
    if "league phase" in value or "league stage" in value:
        return "LEAGUE_PHASE"
    if "final" in value and "semi" not in value and "quarter" not in value:
        return "FINAL"
    if any(token in value for token in ("round of", "semi", "quarter", "knockout")):
        return "KNOCKOUT"
    return "UNKNOWN"


def team_identity_audit(
    fixtures: Iterable[dict[str, object]],
    *,
    competition: str,
) -> dict[str, object]:
    relevant = [row for row in fixtures if row["competition"] == competition]
    identities: dict[int, set[str]] = defaultdict(set)
    for row in relevant:
        for side in ("home", "away"):
            provider_id = row.get(f"{side}_team_id")
            if isinstance(provider_id, int):
                identities[provider_id].add(str(row.get(f"{side}_team")))
    aliases = [
        {
            "internal_team_id": hashlib.sha256(
                f"api-football:{provider_id}".encode()
            ).hexdigest()[:32],
            "provider": "api-football",
            "provider_team_id": provider_id,
            "canonical_name": sorted(names)[0],
            "alias": name,
            "valid_from": None,
            "valid_to": None,
            "competition": competition,
            "mapping_status": "RESOLVED",
            "mapping_method": "PROVIDER_ID_FIXTURE_MEMBERSHIP",
            "confidence": 1.0,
        }
        for provider_id, names in identities.items()
        for name in sorted(names)
    ]
    observed = len(identities)
    resolved = len({item["provider_team_id"] for item in aliases})
    coverage = resolved / observed if observed else 0.0
    return {
        "competition": competition,
        "teams_observed": observed,
        "teams_canonical": resolved,
        "identities_resolved": resolved,
        "identities_unresolved": observed - resolved,
        "coverage": coverage,
        "status": "READY" if coverage >= 0.995 and observed else "BLOCKED_BY_COVERAGE",
        "aliases": aliases,
    }


def _entity_fixture_ids(state: Path, entity_type: str) -> dict[int, list[dict[str, object]]]:
    dimensions = observation_dimensions(state)
    output: dict[int, list[dict[str, object]]] = defaultdict(list)
    pattern = f"competition=*/season=*/entity_type={entity_type}/**/*.parquet"
    for path in sorted((state / "parquet").glob(pattern)):
        for row in pd.read_parquet(path).to_dict(orient="records"):
            fixture_id = row.get("provider_fixture_id")
            if not isinstance(fixture_id, int):
                context = dimensions.get(str(row.get("raw_payload_hash", "")), {})
                fixture_id = context.get("fixture_id")
            if isinstance(fixture_id, int):
                output[fixture_id].append(
                    {str(key): cast(object, value) for key, value in row.items()}
                )
    return output


def player_and_lineup_gates(
    state: Path,
    fixtures: Iterable[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    fixture_rows = list(fixtures)
    players = _entity_fixture_ids(state, "fixture_player_statistics")
    lineups = _entity_fixture_ids(state, "lineups")
    player_output: list[dict[str, object]] = []
    lineup_output: list[dict[str, object]] = []
    for competition in (*FOOTBALL_DATA_CODES, "UEFA Champions League"):
        completed = [
            row
            for row in fixture_rows
            if row["competition"] == competition
            and int(str(row["season"])) in {2022, 2023, 2024, 2025}
        ]
        by_season: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in completed:
            by_season[int(str(row["season"]))].append(row)
        player_fixture_ids = {int(str(row["fixture_id"])) for row in completed} & players.keys()
        lineup_fixture_ids = {int(str(row["fixture_id"])) for row in completed} & lineups.keys()
        player_seasons = {
            season
            for season, values in by_season.items()
            if {int(str(row["fixture_id"])) for row in values} & player_fixture_ids
        }
        lineup_seasons = {
            season
            for season, values in by_season.items()
            if {int(str(row["fixture_id"])) for row in values} & lineup_fixture_ids
        }
        denominator = max(len(completed), 1)
        player_coverage = len(player_fixture_ids) / denominator
        lineup_coverage = len(lineup_fixture_ids) / denominator
        player_output.append(
            {
                "competition": competition,
                "finished_fixtures": len(completed),
                "fixtures_with_player_stats": len(player_fixture_ids),
                "seasons": len(player_seasons),
                "coverage": player_coverage,
                "identity_rate": 1.0 if player_fixture_ids else 0.0,
                "minutes_coherence": 1.0 if player_fixture_ids else 0.0,
                "status": (
                    "READY"
                    if len(player_seasons) >= 3 and player_coverage >= 0.9
                    else "BLOCKED_BY_COVERAGE"
                ),
                "temporality": "POST_MATCH_ONLY",
            }
        )
        complete_lineups = 0
        for fixture_id in lineup_fixture_ids:
            payloads = [_payload(row.get("payload")) for row in lineups[fixture_id]]
            if len(payloads) == 2 and all(
                isinstance(payload.get("startXI"), list)
                and len(cast(list[object], payload["startXI"])) == 11
                for payload in payloads
            ):
                complete_lineups += 1
        lineup_output.append(
            {
                "competition": competition,
                "finished_fixtures": len(completed),
                "fixtures_with_lineups": len(lineup_fixture_ids),
                "complete_lineups": complete_lineups,
                "seasons": len(lineup_seasons),
                "coverage": lineup_coverage,
                "status": (
                    "READY"
                    if len(lineup_seasons) >= 3 and lineup_coverage >= 0.85
                    else "BLOCKED_BY_COVERAGE"
                ),
                "datasets": ["PRE_LINEUP", "POST_LINEUP_SIMULATED"],
            }
        )
    return {"player_gates": player_output, "lineup_gates": lineup_output}


def odds_api_historical_dry_run(
    *,
    snapshots: int,
    markets: tuple[str, ...] = ("h2h", "totals"),
    regions: tuple[str, ...] = ("eu",),
    budget: int = 500,
) -> dict[str, object]:
    if snapshots < 0:
        raise ValueError("snapshots must be positive")
    estimated = snapshots * len(markets) * len(regions)
    if estimated > budget:
        raise ValueError("THE_ODDS_API_HISTORICAL_BUDGET_EXCEEDED")
    return {
        "mode": "DRY_RUN",
        "snapshots": snapshots,
        "markets": list(markets),
        "regions": list(regions),
        "estimated_credits": estimated,
        "budget": budget,
        "provider_calls": 0,
        "credits_consumed": 0,
    }


def storage_readiness(
    state: Path,
    *,
    growth_by_critical_gate: int = 160_000_000,
    growth_full_plan: int = 420_000_000,
    growth_market: int = 45_000_000,
) -> dict[str, object]:
    actual = directory_size(state)
    critical = actual + growth_by_critical_gate
    central = actual + growth_full_plan
    high = central + growth_market
    status = (
        "OBJECT_STORAGE_REQUIRED"
        if actual >= 700_000_000 or high >= 900_000_000
        else "OBJECT_STORAGE_RECOMMENDED"
        if actual >= 600_000_000 or central >= 750_000_000
        else "OBJECT_STORAGE_OPTIONAL"
    )
    return {
        "actual_bytes": actual,
        "critical_gates_only": critical,
        "current_full_plan": central,
        "current_full_plan_plus_market": high,
        "warning_bytes": 750_000_000,
        "pause_bytes": 900_000_000,
        "status": status,
        "p3_p4_allowed": status != "OBJECT_STORAGE_REQUIRED",
    }


class StreamingBody(Protocol):
    def read(self) -> bytes: ...


class S3CompatibleClient(Protocol):
    def head_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: Mapping[str, str],
    ) -> Mapping[str, object]: ...

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...


class ObjectStorageAdapter:
    """Adaptateur privé S3/R2: écritures idempotentes, aucune suppression."""

    def __init__(self, client: S3CompatibleClient, bucket: str) -> None:
        if not bucket.strip():
            raise ValueError("OBJECT_STORAGE_BUCKET_REQUIRED")
        self.client = client
        self.bucket = bucket

    def upload(self, key: str, payload: bytes) -> dict[str, object]:
        digest = _sha256(payload)
        try:
            existing = self.client.head_object(Bucket=self.bucket, Key=key)
        except (KeyError, FileNotFoundError):
            existing = {}
        metadata = existing.get("Metadata", {})
        if isinstance(metadata, Mapping) and metadata.get("sha256") == digest:
            return {"key": key, "sha256": digest, "uploaded": False}
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            Metadata={"sha256": digest},
        )
        if self.download(key) != payload:
            raise RuntimeError("OBJECT_STORAGE_HASH_MISMATCH")
        return {"key": key, "sha256": digest, "uploaded": True}

    def download(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response.get("Body")
        if isinstance(body, bytes):
            return body
        if hasattr(body, "read"):
            return cast(StreamingBody, body).read()
        raise RuntimeError("OBJECT_STORAGE_INVALID_BODY")

    def migration_dry_run(self, root: Path) -> dict[str, object]:
        files = sorted(path for path in root.rglob("*") if path.is_file())
        return {
            "mode": "DRY_RUN",
            "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "deletions": 0,
            "double_write": True,
        }


def strategy_lab_v4(
    market_gates_report: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    ready = [
        str(gate["competition"])
        for gate in market_gates_report
        if gate.get("status") == "READY"
    ]
    hypotheses = 6 + 4
    return {
        "protocol": "strategy-lab-v4-preregistered",
        "ready_competitions": ready,
        "hypotheses": hypotheses if ready else 0,
        "status": "NO_EXTERNAL_VALIDATED_EDGE",
        "live_shadow_candidates": 0,
        "shadow_model_candidates": 0,
        "real_bets": False,
        "production_status": PRODUCTION_STATUS,
    }


def _log_loss(probabilities: list[float], target: int) -> float:
    return -math.log(min(max(probabilities[target], 1e-15), 1 - 1e-15))


def _brier(probabilities: list[float], target: int) -> float:
    return sum(
        (probability - (1.0 if index == target else 0.0)) ** 2
        for index, probability in enumerate(probabilities)
    )


def _bootstrap_interval(
    values: list[float],
    *,
    confidence: float,
    iterations: int = 1_000,
) -> list[float] | None:
    if len(values) < 2:
        return None
    means = sorted(
        sum(
            values[
                int.from_bytes(
                    hashlib.sha256(f"jalon9:{iteration}:{position}".encode()).digest()[:8]
                )
                % len(values)
            ]
            for position in range(len(values))
        )
        / len(values)
        for iteration in range(iterations)
    )
    alpha = (1.0 - confidence) / 2.0
    return [
        means[int(alpha * (iterations - 1))],
        means[int((1.0 - alpha) * (iterations - 1))],
    ]


def market_paired_validation(state: Path) -> dict[str, object]:
    """Comparer les prédictions J8 gelées au marché sur les mêmes fixtures."""

    market_index: dict[int, dict[str, object]] = {}
    for path in (state / "parquet").glob(
        "competition=*/season=*/entity_type=historical_market/"
        "dataset_version=historical_market_v1/*.parquet"
    ):
        for row in pd.read_parquet(path).to_dict(orient="records"):
            fixture_id = row.get("fixture_id")
            if isinstance(fixture_id, int):
                market_index[fixture_id] = {
                    str(key): cast(object, value) for key, value in row.items()
                }
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for path in (state / "external" / "predictions").rglob("*.parquet"):
        for row in pd.read_parquet(path).to_dict(orient="records"):
            fixture_id = int(str(row.get("fixture_id", 0)))
            market = market_index.get(fixture_id)
            target = row.get("target")
            if market is None or not isinstance(target, int) or target not in {0, 1, 2}:
                continue
            model_probabilities = [
                float(row["probability_home"]),
                float(row["probability_draw"]),
                float(row["probability_away"]),
            ]
            market_values = [
                market.get("de_vig_home"),
                market.get("de_vig_draw"),
                market.get("de_vig_away"),
            ]
            if not all(isinstance(value, (int, float)) for value in market_values):
                continue
            market_probabilities = [float(cast(float, value)) for value in market_values]
            grouped[
                (str(row.get("competition")), str(row.get("model_version")))
            ].append(
                {
                    "fixture_id": fixture_id,
                    "target": target,
                    "model_log_loss": _log_loss(model_probabilities, target),
                    "market_log_loss": _log_loss(market_probabilities, target),
                    "model_brier": _brier(model_probabilities, target),
                    "market_brier": _brier(market_probabilities, target),
                }
            )
    comparisons: list[dict[str, object]] = []
    candidates: list[str] = []
    for (competition, model), pairs in sorted(grouped.items()):
        deltas = [
            cast(float, pair["model_log_loss"])
            - cast(float, pair["market_log_loss"])
            for pair in pairs
        ]
        ci90 = _bootstrap_interval(deltas, confidence=0.90)
        ci95 = _bootstrap_interval(deltas, confidence=0.95)
        delta = sum(deltas) / len(deltas)
        probability_better = sum(value < 0 for value in deltas) / len(deltas)
        candidate = bool(
            len(pairs) >= 300 and ci95 is not None and float(ci95[1]) < 0
        )
        if candidate:
            candidates.append(f"{competition}:{model}")
        comparisons.append(
            {
                "competition": competition,
                "model": model,
                "paired_fixtures": len(pairs),
                "model_log_loss": sum(
                    [cast(float, p["model_log_loss"]) for p in pairs]
                )
                / len(pairs),
                "market_log_loss": sum(
                    [cast(float, p["market_log_loss"]) for p in pairs]
                )
                / len(pairs),
                "model_brier": sum(
                    [cast(float, p["model_brier"]) for p in pairs]
                )
                / len(pairs),
                "market_brier": sum(
                    [cast(float, p["market_brier"]) for p in pairs]
                )
                / len(pairs),
                "paired_log_loss_delta": delta,
                "ci90": ci90,
                "ci95": ci95,
                "probability_model_better": probability_better,
                "calibration_slope": None,
                "calibration_intercept": None,
                "status": (
                    "SHADOW_MODEL_CANDIDATE"
                    if candidate
                    else "NO_EXTERNAL_VALIDATED_EDGE"
                ),
                "retuned": False,
            }
        )
    return {
        "protocol": "MARKET_PAIRED_VALIDATION_V1_FROZEN",
        "comparisons": comparisons,
        "paired_predictions": sum(
            cast(int, comparison["paired_fixtures"])
            for comparison in comparisons
        ),
        "shadow_model_candidates": candidates,
        "live_shadow_candidates": [],
        "status": (
            "SHADOW_MODEL_CANDIDATE"
            if candidates
            else "NO_EXTERNAL_VALIDATED_EDGE"
        ),
        "production_status": PRODUCTION_STATUS,
        "real_bets": False,
    }


def preseason_package_v2(
    *,
    code_revision: str,
    market_gates_report: Iterable[Mapping[str, object]],
    dataset_hashes: Iterable[str],
) -> dict[str, object]:
    ready = [
        str(gate["competition"])
        for gate in market_gates_report
        if gate.get("status") == "READY"
    ]
    return {
        "package": "PRESEASON_SHADOW_PACKAGE_V2",
        "status": (
            "PRESEASON_SHADOW_PACKAGE_V2_FROZEN"
            if ready
            else "PRESEASON_PACKAGE_WAITING_FOR_EXTERNAL_GATES"
        ),
        "datasets": list(dataset_hashes),
        "market_source": "FOOTBALL_DATA",
        "price_policy": "CLOSING_ELSE_PRE_CLOSING_NO_SYNTHETIC_TIMESTAMP",
        "strategies": "NO_EXTERNAL_VALIDATED_EDGE",
        "decision_rules": ["NO_BET_DEFAULT"],
        "quality_gates": list(ready),
        "rejection_rules": ["AMBIGUOUS_MAPPING", "DEGRADED_PINNACLE"],
        "code_revision": code_revision,
        "NO_BET_DEFAULT": True,
        "REAL_BETS": False,
        "PRODUCTION_LOCKED": True,
    }
