#!/usr/bin/env python3
"""Recalculate the read-only Robin data/hypothesis convergence bundle.

The script reads immutable Git objects from an analysis clone, embeds only public
calendar facts collected for this design review, and performs no network call.
It writes only to the explicit output directory; in-repository output is restricted
to reports/data-sourcing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess  # nosec B404
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, cast

BASELINE = "6cb8de636890959bd2ddb7e1c791a2eb04ee8763"
PR56_HEAD = "81211569f7f5ae1139a4be50b90c643a00d3fdd6"
PR57_INITIAL_HEAD = "ccaaff94b4b4a3bdec9ec2738efbebba3fe23d43"
PR57_FINAL_HEAD = "ccaaff94b4b4a3bdec9ec2738efbebba3fe23d43"
PR57_MERGE_SHA = "124bad7b2bd8ca5aaee6770f0a5a3a0c947692b1"
PR58_FINAL_HEAD = "bdb5be144ee0f6e9cf33b446f32a1808ada74de1"
PR58_MERGE_SHA = "72e6cd625f7668fdcc095e63a847b6e7e9cf860f"
CONVERGENCE_MANIFEST_SHA256 = "269f4066b13e88f4397aecd6f1a3d7ba154dc8468415581ce0f6b8922f1537b4"
ACCESS_DATE = "2026-08-15"

STATUS = [
    "DESIGN_ONLY",
    "NOT_ACTIVATED",
    "NOT_AUTHORIZED",
    "NO_PROVIDER_CALL",
    "NO_PURCHASE",
    "NO_PROMOTION",
    "NO_BET",
]

SOURCE_URLS: dict[str, dict[str, Any]] = {
    "odds_home": {
        "url": "https://the-odds-api.com/",
        "authority": "The Odds API official domain",
        "supports": ["public plans", "monthly credits"],
    },
    "odds_v4": {
        "url": "https://the-odds-api.com/liveapi/guides/v4/",
        "authority": "The Odds API v4 official documentation",
        "supports": ["endpoint costs", "schemas", "quota headers", "market timestamps"],
    },
    "odds_markets": {
        "url": "https://the-odds-api.com/sports-odds-data/betting-markets.html",
        "authority": "The Odds API official market guide",
        "supports": ["totals availability warning"],
    },
    "odds_intervals": {
        "url": "https://the-odds-api.com/sports-odds-data/update-intervals.html",
        "authority": "The Odds API official update-interval guide",
        "supports": ["prematch refresh intervals"],
    },
    "odds_faq": {
        "url": "https://the-odds-api.com/manage/faqs.html",
        "authority": "The Odds API official account FAQ",
        "supports": ["monthly reset"],
    },
    "odds_errors": {
        "url": "https://the-odds-api.com/liveapi/guides/v4/api-error-codes.html",
        "authority": "The Odds API official error guide",
        "supports": ["quota exhaustion", "HTTP 429"],
    },
    "odds_terms": {
        "url": "https://the-odds-api.com/terms-and-conditions.html",
        "authority": "The Odds API public terms",
        "supports": [
            "analytics use",
            "standalone redistribution prohibition",
            "no accuracy warranty",
        ],
    },
    "odds_privacy": {
        "url": "https://the-odds-api.com/privacy.html",
        "authority": "The Odds API privacy notice",
        "supports": ["public legal context"],
    },
    "odds_warning": {
        "url": "https://the-odds-api.com/impersonation-warning.html",
        "authority": "The Odds API official impersonation warning",
        "supports": ["the-odds-api.com is the only official domain"],
    },
    "sportmonks_core": {
        "url": "https://www.sportmonks.com/football-api/",
        "authority": "Sportmonks official Football API page",
        "supports": ["fixture/result provider candidate", "plan-dependent structured coverage"],
    },
    "sportmonks_pricing": {
        "url": "https://www.sportmonks.com/football-api/plans-pricing/",
        "authority": "Sportmonks official plans page",
        "supports": ["candidate pricing requiring re-verification before purchase"],
    },
    "sportmonks_terms": {
        "url": "https://www.sportmonks.com/terms-of-service/",
        "authority": "Sportmonks terms of service",
        "supports": ["commercial/storage conditions", "raw resale prohibition"],
    },
    "wikidata_access": {
        "url": "https://www.wikidata.org/wiki/Wikidata:Data_access",
        "authority": "Wikidata data-access documentation",
        "supports": ["revision-addressed venue geography candidate"],
    },
    "wikidata_licence": {
        "url": "https://www.wikidata.org/wiki/Wikidata:Licensing",
        "authority": "Wikidata licensing page",
        "supports": ["CC0 structured data"],
    },
    "ligue1_calendar": {
        "url": "https://ligue1.com/fr/articles/l1_article_5284-",
        "authority": "Ligue 1 / LFP",
        "supports": ["2026-27 calendar", "306 fixtures"],
    },
    "ligue1_pdf": {
        "url": "https://s3.eu-west-1.amazonaws.com/image.mpg/L1MD_2627_CALENDRIER.pdf",
        "authority": "LFP calendar PDF",
        "supports": ["34 matchdays", "fixture pairs"],
    },
    "ligue1_times": {
        "url": "https://ligue1.com/fr/articles/l1_article_5435-programmation-tv-des-2-premieres-journees-de-ligue-1-mcdonald-s-2627",
        "authority": "Ligue 1 / LFP",
        "supports": ["exact J1-J2 kickoff times"],
    },
    "premier_league": {
        "url": "https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season",
        "authority": "Premier League",
        "supports": ["380 fixtures", "published kickoff times", "subject-to-change caveat"],
    },
    "laliga_rfef": {
        "url": "https://rfef.es/es/noticias/calendario-completo-primera-division-temporada-202627",
        "authority": "RFEF",
        "supports": ["2026-27 Primera Division calendar", "380 fixtures"],
    },
    "laliga_pdf": {
        "url": "https://rfef.es/sites/default/files/2026-06/Campeonato_de_Primera_Division_0.pdf",
        "authority": "RFEF",
        "supports": ["38 matchdays", "fixture pairs"],
    },
    "laliga_times": {
        "url": "https://www.laliga.com/calendar-2026-2027/laliga-easports",
        "authority": "LaLiga",
        "supports": ["published display times", "mutable schedule"],
    },
    "bundesliga_calendar": {
        "url": "https://www.bundesliga.com/en/bundesliga/news/2026-27-fixture-lists-now-available-38068",
        "authority": "DFL / Bundesliga",
        "supports": ["306 fixtures", "2026-27 fixture list"],
    },
    "bundesliga_pdf": {
        "url": "https://media.dfl.de/sites/3/2026/07/EN_eFyJmg6k_Bundesliga_Fixture-List_2026_27.pdf",
        "authority": "DFL",
        "supports": ["numbered fixtures 1-306", "matchday structure"],
    },
    "bundesliga_times": {
        "url": "https://www.bundesliga.com/en/bundesliga/news/confirmed-kick-off-times-dates-2026-27-fixtures-23955",
        "authority": "DFL / Bundesliga",
        "supports": ["confirmed J1-J4 kickoff times"],
    },
    "serie_a_calendar": {
        "url": "https://www.legaseriea.it/serie-a/news/calendario-della-serie-a-enilive-2026-27",
        "authority": "Lega Serie A",
        "supports": ["2026-27 calendar", "380 fixtures"],
    },
    "serie_a_times": {
        "url": "https://images.legaseriea.it/image/private/fl_attachment/prd/czailts3apyt3kuxjran.pdf",
        "authority": "Lega Serie A official communication 208",
        "supports": ["exact J1-J5 kickoff times", "conditional fixtures caveat"],
    },
}

LEAGUES: dict[str, dict[str, Any]] = {
    "L1": {
        "competition": "Ligue 1",
        "sport_key": "soccer_france_ligue_one",
        "season": "2026-27",
        "full_season_fixtures": 306,
        "matchdays": 34,
        "planning_groups_per_matchday": 6,
        "source_ids": ["ligue1_calendar", "ligue1_pdf", "ligue1_times"],
        "kickoff_time_status": "OFFICIAL_EXACT_UTC_FOR_INCLUDED_J1_J2",
    },
    "EPL": {
        "competition": "Premier League",
        "sport_key": "soccer_epl",
        "season": "2026-27",
        "full_season_fixtures": 380,
        "matchdays": 38,
        "planning_groups_per_matchday": 8,
        "source_ids": ["premier_league"],
        "kickoff_time_status": "OFFICIAL_EXACT_UTC_FOR_INCLUDED_J1_J2_SUBJECT_TO_CHANGE",
    },
    "LL": {
        "competition": "La Liga",
        "sport_key": "soccer_spain_la_liga",
        "season": "2026-27",
        "full_season_fixtures": 380,
        "matchdays": 38,
        "planning_groups_per_matchday": 10,
        "source_ids": ["laliga_rfef", "laliga_pdf", "laliga_times"],
        "kickoff_time_status": "DISPLAY_TIME_INTERPRETATION_TO_BE_RECONFIRMED_BEFORE_CAPTURE",
    },
    "BL": {
        "competition": "Bundesliga",
        "sport_key": "soccer_germany_bundesliga",
        "season": "2026-27",
        "full_season_fixtures": 306,
        "matchdays": 34,
        "planning_groups_per_matchday": 5,
        "source_ids": ["bundesliga_calendar", "bundesliga_pdf", "bundesliga_times"],
        "kickoff_time_status": "OFFICIAL_EXACT_UTC_FOR_INCLUDED_J1_SUBJECT_TO_CHANGE",
    },
    "SA": {
        "competition": "Serie A",
        "sport_key": "soccer_italy_serie_a",
        "season": "2026-27",
        "full_season_fixtures": 380,
        "matchdays": 38,
        "planning_groups_per_matchday": 8,
        "source_ids": ["serie_a_calendar", "serie_a_times"],
        "kickoff_time_status": "OFFICIAL_EXACT_UTC_FOR_INCLUDED_J1_SUBJECT_TO_CHANGE",
    },
}


def fixture(
    league: str,
    matchday: int,
    sequence: int,
    kickoff_at: str,
    home: str,
    away: str,
) -> dict[str, Any]:
    return {
        "fixture_id": f"{league}-2026-27-MD{matchday:02d}-{sequence:02d}",
        "league_code": league,
        "competition": LEAGUES[league]["competition"],
        "season": "2026-27",
        "matchday": matchday,
        "kickoff_at": kickoff_at,
        "home_team": home,
        "away_team": away,
        "sport_key": LEAGUES[league]["sport_key"],
        "region": "eu",
        "source_ids": LEAGUES[league]["source_ids"],
        "kickoff_time_status": LEAGUES[league]["kickoff_time_status"],
        "provider_event_id": None,
        "mapping_status": "PROVISIONAL_UNTIL_PROVIDER_EVENT_ID_RECEIPT",
    }


FIXTURES: list[dict[str, Any]] = [
    # Ligue 1, official J1-J2 times (CEST converted to UTC).
    fixture("L1", 1, 1, "2026-08-21T18:45:00Z", "Marseille", "Strasbourg"),
    fixture("L1", 1, 2, "2026-08-22T15:15:00Z", "Lens", "Auxerre"),
    fixture("L1", 1, 3, "2026-08-22T18:45:00Z", "Toulouse", "Lyon"),
    fixture("L1", 1, 4, "2026-08-22T18:45:00Z", "Nice", "Lorient"),
    fixture("L1", 1, 5, "2026-08-22T18:45:00Z", "Troyes", "Paris FC"),
    fixture("L1", 1, 6, "2026-08-22T18:45:00Z", "Le Mans", "Brest"),
    fixture("L1", 1, 7, "2026-08-23T13:00:00Z", "Angers", "Lille"),
    fixture("L1", 1, 8, "2026-08-23T15:15:00Z", "Le Havre", "Monaco"),
    fixture("L1", 1, 9, "2026-08-23T18:45:00Z", "Paris Saint-Germain", "Rennes"),
    fixture("L1", 2, 1, "2026-08-28T18:45:00Z", "Lille", "Paris Saint-Germain"),
    fixture("L1", 2, 2, "2026-08-29T15:15:00Z", "Strasbourg", "Lens"),
    fixture("L1", 2, 3, "2026-08-29T18:45:00Z", "Lyon", "Le Havre"),
    fixture("L1", 2, 4, "2026-08-29T18:45:00Z", "Lorient", "Troyes"),
    fixture("L1", 2, 5, "2026-08-29T18:45:00Z", "Brest", "Toulouse"),
    fixture("L1", 2, 6, "2026-08-29T18:45:00Z", "Auxerre", "Angers"),
    fixture("L1", 2, 7, "2026-08-30T13:00:00Z", "Paris FC", "Nice"),
    fixture("L1", 2, 8, "2026-08-30T15:15:00Z", "Rennes", "Le Mans"),
    fixture("L1", 2, 9, "2026-08-30T18:45:00Z", "Monaco", "Marseille"),
    # Premier League, official J1-J2 local times converted from BST to UTC.
    fixture("EPL", 1, 1, "2026-08-21T19:00:00Z", "Arsenal", "Coventry City"),
    fixture("EPL", 1, 2, "2026-08-22T11:30:00Z", "Hull City", "Manchester United"),
    fixture("EPL", 1, 3, "2026-08-22T14:00:00Z", "Everton", "Crystal Palace"),
    fixture("EPL", 1, 4, "2026-08-22T14:00:00Z", "Ipswich Town", "Sunderland"),
    fixture("EPL", 1, 5, "2026-08-22T14:00:00Z", "Nottingham Forest", "Leeds United"),
    fixture("EPL", 1, 6, "2026-08-22T16:30:00Z", "Brentford", "Tottenham Hotspur"),
    fixture("EPL", 1, 7, "2026-08-23T13:00:00Z", "Brighton", "Aston Villa"),
    fixture("EPL", 1, 8, "2026-08-23T13:00:00Z", "Manchester City", "Bournemouth"),
    fixture("EPL", 1, 9, "2026-08-23T15:30:00Z", "Newcastle United", "Liverpool"),
    fixture("EPL", 1, 10, "2026-08-24T19:00:00Z", "Fulham", "Chelsea"),
    fixture("EPL", 2, 1, "2026-08-28T19:00:00Z", "Crystal Palace", "Manchester City"),
    fixture("EPL", 2, 2, "2026-08-29T11:30:00Z", "Liverpool", "Nottingham Forest"),
    fixture("EPL", 2, 3, "2026-08-29T14:00:00Z", "Bournemouth", "Everton"),
    fixture("EPL", 2, 4, "2026-08-29T14:00:00Z", "Coventry City", "Hull City"),
    fixture("EPL", 2, 5, "2026-08-29T16:30:00Z", "Tottenham Hotspur", "Newcastle United"),
    fixture("EPL", 2, 6, "2026-08-30T13:00:00Z", "Chelsea", "Brighton"),
    fixture("EPL", 2, 7, "2026-08-30T13:00:00Z", "Leeds United", "Brentford"),
    fixture("EPL", 2, 8, "2026-08-30T13:00:00Z", "Sunderland", "Fulham"),
    fixture("EPL", 2, 9, "2026-08-30T15:30:00Z", "Manchester United", "Ipswich Town"),
    fixture("EPL", 2, 10, "2026-08-31T19:00:00Z", "Aston Villa", "Arsenal"),
    # La Liga: official display times; timezone interpretation must be re-confirmed.
    fixture("LL", 1, 1, "2026-08-15T17:30:00Z", "Alaves", "Getafe"),
    fixture("LL", 1, 2, "2026-08-15T19:30:00Z", "Sevilla", "Rayo Vallecano"),
    fixture("LL", 1, 3, "2026-08-16T15:00:00Z", "Racing Santander", "Villarreal"),
    fixture("LL", 1, 4, "2026-08-16T17:00:00Z", "Espanyol", "Levante"),
    fixture("LL", 1, 5, "2026-08-16T19:30:00Z", "Celta Vigo", "Osasuna"),
    fixture("LL", 1, 6, "2026-08-17T19:00:00Z", "Deportivo La Coruna", "Elche"),
    fixture("LL", 1, 7, "2026-08-19T19:00:00Z", "Atletico Madrid", "Malaga"),
    fixture("LL", 1, 8, "2026-08-25T19:00:00Z", "Valencia", "Real Betis"),
    fixture("LL", 1, 9, "2026-08-26T19:00:00Z", "Real Madrid", "Real Sociedad"),
    fixture("LL", 1, 10, "2026-08-27T19:00:00Z", "Barcelona", "Athletic Club"),
    # Bundesliga, official J1 times (CEST converted to UTC).
    fixture("BL", 1, 1, "2026-08-28T18:30:00Z", "Bayern Munich", "VfB Stuttgart"),
    fixture("BL", 1, 2, "2026-08-29T13:30:00Z", "SV Elversberg", "Bayer Leverkusen"),
    fixture("BL", 1, 3, "2026-08-29T13:30:00Z", "Cologne", "Hoffenheim"),
    fixture("BL", 1, 4, "2026-08-29T13:30:00Z", "Union Berlin", "Eintracht Frankfurt"),
    fixture("BL", 1, 5, "2026-08-29T13:30:00Z", "Mainz", "Paderborn"),
    fixture("BL", 1, 6, "2026-08-29T13:30:00Z", "RB Leipzig", "Borussia Monchengladbach"),
    fixture("BL", 1, 7, "2026-08-29T16:30:00Z", "Borussia Dortmund", "Hamburg"),
    fixture("BL", 1, 8, "2026-08-30T13:30:00Z", "Freiburg", "Werder Bremen"),
    fixture("BL", 1, 9, "2026-08-30T15:30:00Z", "Augsburg", "Schalke"),
    # Serie A, official J1 local times converted from CEST to UTC.
    fixture("SA", 1, 1, "2026-08-22T16:30:00Z", "Inter", "Monza"),
    fixture("SA", 1, 2, "2026-08-22T16:30:00Z", "Udinese", "Como"),
    fixture("SA", 1, 3, "2026-08-22T18:45:00Z", "Genoa", "Napoli"),
    fixture("SA", 1, 4, "2026-08-22T18:45:00Z", "Parma", "Cagliari"),
    fixture("SA", 1, 5, "2026-08-23T16:30:00Z", "Frosinone", "Juventus"),
    fixture("SA", 1, 6, "2026-08-23T16:30:00Z", "Venezia", "Lecce"),
    fixture("SA", 1, 7, "2026-08-23T18:45:00Z", "Atalanta", "Sassuolo"),
    fixture("SA", 1, 8, "2026-08-23T18:45:00Z", "Torino", "Milan"),
    fixture("SA", 1, 9, "2026-08-24T16:30:00Z", "Bologna", "Lazio"),
    fixture("SA", 1, 10, "2026-08-24T18:45:00Z", "Roma", "Fiorentina"),
]

WINDOWS: dict[str, dict[str, Any]] = {
    "H24": {
        "role": "PREDICTOR",
        "role_class": "PREDICTOR_CAPTURE",
        "protocol_role_bindings": {
            "PREDICTOR": ["RDS-EXP-V1-006", "RDS-EXP-V1-008", "RDS-EXP-V1-009", "RDS-EXP-V1-010"],
            "TARGET": [],
        },
        "ideal_minutes_before_kickoff": 1440,
        "earliest_minutes_before_kickoff": 1560,
        "latest_minutes_before_kickoff": 1440,
        "maximum_staleness_minutes": 120,
        "authority": "FROZEN_PR57",
        "protocols": ["RDS-EXP-V1-006", "RDS-EXP-V1-008", "RDS-EXP-V1-009", "RDS-EXP-V1-010"],
    },
    "H12": {
        "role": "PREDICTOR",
        "role_class": "PREDICTOR_CAPTURE",
        "protocol_role_bindings": {"PREDICTOR": ["RDS-EXP-V1-009"], "TARGET": []},
        "ideal_minutes_before_kickoff": 720,
        "earliest_minutes_before_kickoff": 720,
        "latest_minutes_before_kickoff": 720,
        "maximum_staleness_minutes": None,
        "authority": "PROPOSED_NOT_FROZEN_FOR_EXP009",
        "protocols": ["RDS-EXP-V1-009"],
    },
    "H6": {
        "role": "PREDICTOR",
        "role_class": "PREDICTOR_CAPTURE",
        "protocol_role_bindings": {"PREDICTOR": ["RDS-EXP-V1-009"], "TARGET": []},
        "ideal_minutes_before_kickoff": 360,
        "earliest_minutes_before_kickoff": 360,
        "latest_minutes_before_kickoff": 360,
        "maximum_staleness_minutes": None,
        "authority": "PROPOSED_NOT_FROZEN_FOR_EXP009",
        "protocols": ["RDS-EXP-V1-009"],
    },
    "H2": {
        "role": "MIXED_BY_PROTOCOL_WITH_DISTINCT_BINDINGS",
        "role_class": "PREDICTOR_CAPTURE_WITH_EXP006_TARGET_BINDING",
        "protocol_role_bindings": {
            "PREDICTOR": [f"RDS-EXP-V1-{i:03d}" for i in range(1, 26) if i != 6],
            "TARGET": ["RDS-EXP-V1-006"],
        },
        "ideal_minutes_before_kickoff": 120,
        "earliest_minutes_before_kickoff": 135,
        "latest_minutes_before_kickoff": 120,
        "maximum_staleness_minutes": 15,
        "authority": "FROZEN_PR57",
        "protocols": [f"RDS-EXP-V1-{i:03d}" for i in range(1, 26) if i != 6],
    },
    "H1": {
        "role": "TARGET",
        "role_class": "TARGET_CAPTURE",
        "protocol_role_bindings": {"PREDICTOR": [], "TARGET": ["RDS-EXP-V1-005", "RDS-EXP-V1-023"]},
        "ideal_minutes_before_kickoff": 60,
        "earliest_minutes_before_kickoff": 65,
        "latest_minutes_before_kickoff": 55,
        "maximum_staleness_minutes": None,
        "authority": "STRICT_CONVERGENCE_GUARD_PROPOSED_FROM_FROZEN_5_MIN_TOLERANCE",
        "protocols": ["RDS-EXP-V1-005", "RDS-EXP-V1-023"],
        "pr57_formal_rule": "cutoff_at < available_at <= kickoff_at-PT1H+PT5M",
        "ambiguity": "PR57 does not freeze the lower H1 bound or latest/nearest selection rule.",
    },
}

MINIMAL_WINDOWS = ["H24", "H2", "H1"]
FULL_WINDOWS = ["H24", "H12", "H6", "H2", "H1"]


def run_git(repo: Path, *args: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git executable not found")
    # The executable is resolved, argv is fixed, and shell execution is never used.
    result = subprocess.run(  # nosec B603
        [git_executable, "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8")


def git_json(repo: Path, ref: str, path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(run_git(repo, "show", f"{ref}:{path}")))


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"naive datetime forbidden: {value}")
    return parsed.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def short_id(experiment_id: str) -> int:
    return int(experiment_id.rsplit("-", 1)[1])


def class_for_experiment(number: int) -> str:
    if 1 <= number <= 8:
        return "A"
    if number in {11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22}:
        return "B"
    if number in {9, 10, 23, 24, 25}:
        return "C"
    if number == 20:
        return "D"
    raise AssertionError(number)


def source_candidates(number: int) -> list[str]:
    if number <= 10:
        return ["The Odds API current", "official fixture authority", "Source 2 fixture+settlement"]
    if number in {11, 12, 13}:
        return ["Sportmonks Football core + contracted xG add-on", "Source 2 settlement"]
    if number == 14:
        return [
            "Sportmonks Football core",
            "Wikidata revisioned venue coordinates",
            "Source 2 settlement",
        ]
    if number == 15:
        return ["official league promotion/competition publications", "Sportmonks Football core"]
    if number == 16:
        return [
            "versioned preseason derby registry",
            "The Odds API event odds",
            "Source 2 settlement",
        ]
    if number in {17, 18, 19}:
        return [
            "Sportmonks multi-competition fixtures/results",
            "Wikidata revisioned venue coordinates",
        ]
    if number == 20:
        return ["NO_ADMISSIBLE_VERSIONED_COACH_EFFECTIVE_AT_PIPELINE_IDENTIFIED"]
    if number in {21, 22}:
        return [
            "Sportmonks tables/results",
            "contracted xG/strength derivation",
            "Source 2 settlement",
        ]
    return ["The Odds API event odds", "official fixture authority", "Source 2 settlement"]


def convergence_gates(number: int) -> list[str]:
    gates = ["NO_MATERIALIZED_RECEIPT_BACKED_CAPTURE", "NO_SETTLEMENT_LABEL_SOURCE_SELECTED"]
    if number in {9}:
        gates.append("EXP009_INTERMEDIATE_WINDOWS_NOT_FROZEN")
        gates.append("EXP009_PROTOCOL_SUCCESSOR_REQUIRED_BEFORE_EXECUTION")
    if number in {10, 16, 23, 24, 25}:
        gates.append("TOTALS_COVERAGE_TO_BE_PROVEN")
    if number in {10, 23}:
        gates.append("MARKET_LEVEL_TIMESTAMP_PRESENCE_AND_PAIRING_TO_BE_EMPIRICALLY_PROVEN")
    if number == 10:
        gates.append(
            "EXP010_RECEIPT_TIME_VS_MARKET_LAST_UPDATE_CLOCK_SEMANTICS_AND_H24_H2_DEPENDENCY_MUST_BE_FROZEN"
        )
    if number in {11, 12, 13, 21, 22}:
        gates.append("XG_XGA_OR_STRENGTH_SOURCE_NOT_ACTIVATED")
    if number in {14, 15, 16}:
        gates.append("VERSIONED_VENUE_PROMOTION_DERBY_REGISTRIES_NOT_MATERIALIZED")
    if number in {17, 18, 19}:
        gates.append("MULTI_COMPETITION_CALENDAR_AND_COMPLETION_RECEIPTS_NOT_MATERIALIZED")
    if number == 20:
        gates.append("DATA_NOT_PROSPECTIVELY_OBSERVABLE_COACH_EFFECTIVE_AT")
    return gates


def minimum_snapshot_contract(number: int, experiment: dict[str, Any]) -> dict[str, Any]:
    threshold = experiment["thresholds"]["operational_thresholds"].get("minimum_snapshots")
    target = experiment["point_in_time"].get("post_cutoff_target_admissibility")
    if threshold is not None:
        return {
            "predictor_snapshots": threshold,
            "target_snapshots": 0,
            "protocol_statement": "Only the count is frozen; intermediate windows are not frozen.",
        }
    if number == 8:
        return {"predictor_snapshots": 2, "target_snapshots": 0, "windows": ["H24", "H2"]}
    if number == 10:
        return {
            "predictor_snapshots": 2,
            "target_snapshots": 0,
            "windows": ["H24", "H2"],
            "fail_closed_interpretation": "The named H24+H2 dependency is enforced. PR57 must still freeze whether skew uses receipt time or provider market.last_update.",
        }
    if number == 6:
        return {"predictor_snapshots": 1, "target_snapshots": 1, "windows": ["H24", "H2 TARGET"]}
    if target:
        return {"predictor_snapshots": 1, "target_snapshots": 1}
    return {"predictor_snapshots": 1, "target_snapshots": 0}


def build_matrix(protocols: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for experiment in protocols["experiments"]:
        number = short_id(experiment["experiment_id"])
        dependencies = experiment["dataset_required"]["dependencies"]
        predictors = [d for d in dependencies if d["role"] in {"FEATURE", "ODDS"}]
        targets = [d for d in dependencies if d["role"] == "TARGET"]
        labels = [d for d in dependencies if d["role"] == "LABEL"]
        metadata = [d for d in dependencies if d["role"] == "METADATA"]
        markets = sorted(
            {
                "h2h" if component["market"] == "1X2" else "totals:2.5"
                for branch in experiment["devig_protocol"]["branches"]
                for component in branch["components"]
            }
        )
        thresholds = experiment["thresholds"]["operational_thresholds"]
        if number == 7:
            bookmaker_grain: dict[str, Any] = {
                "unit": "fixture×bookmaker×receipt",
                "low_coverage": "5-6 complete bookmakers",
                "excluded": "7-9 complete bookmakers",
                "reference": ">=10 complete bookmakers",
            }
            minimum_bookmakers: Any = {"eligible_min": 5, "reference_min": 10}
        else:
            minimum_bookmakers = thresholds.get("minimum_complete_bookmakers", 5)
            bookmaker_grain = {
                "unit": "fixture×bookmaker×receipt",
                "consensus": "median across complete bookmakers",
                "minimum_complete_bookmakers": minimum_bookmakers,
            }
        cutoff = experiment["point_in_time"]["cutoff_at"]
        target_window = experiment["point_in_time"].get("post_cutoff_target_admissibility")
        staleness: dict[str, Any] = {}
        if cutoff["cutoff_id"] == "H24":
            staleness["H24_predictor_minutes"] = 120
        else:
            staleness["H2_predictor_minutes"] = 15
        if number in {8, 9, 10}:
            staleness = {"H24_predictor_minutes": 120, "H2_predictor_minutes": 15}
        if number == 9:
            staleness["intermediate_snapshot_minutes"] = None
        row = {
            "experiment_id": experiment["experiment_id"],
            "hypothesis_id": experiment["hypothesis_id"],
            "title": experiment["title"],
            "family": experiment["multiplicity_family"],
            "primary_estimand": experiment["operational_definition"]["estimand"],
            "predictors": predictors,
            "targets": targets,
            "labels": labels,
            "metadata": metadata,
            "markets": markets,
            "bookmaker_grain": bookmaker_grain,
            "league_grain": {
                "analysis": "league-season fixed effects unless the frozen model states otherwise",
                "league_holdout": experiment["league_holdout"],
                "season_holdout": experiment["season_holdout"],
            },
            "predictor_cutoff": cutoff,
            "target_window": target_window,
            "maximum_staleness": staleness,
            "minimum_bookmakers": minimum_bookmakers,
            "minimum_snapshots": minimum_snapshot_contract(number, experiment),
            "receipt_requirements": {
                "predictor": experiment["point_in_time"]["predictor_receipt_fields_required"],
                "target": experiment["point_in_time"]["post_cutoff_target_receipt_fields_required"],
                "availability_rule": "available_at=max(trusted source_published_at, robin_first_observed_at); available_at<=cutoff_at; robin_ingested_at<=cutoff_at",
            },
            "settlement_requirements": {
                "sources": experiment["point_in_time"]["label_receipt_backed_sources_required"],
                "fields": experiment["point_in_time"]["label_receipt_fields_required"],
                "admissibility": experiment["point_in_time"]["label_admissibility"],
            },
            "de_vig_branches": experiment["devig_protocol"]["branches"],
            "negative_controls": experiment["negative_control_ids"],
            "minimum_sample": experiment["minimum_sample"],
            "source_candidates": source_candidates(number),
            "supportability_category": class_for_experiment(number),
            "current_data_gate": {
                "pr57_status": experiment["point_in_time"]["prospective_observability_status"],
                "convergence_gates": convergence_gates(number),
            },
            "execution_status": experiment["execution_status"],
            "execution_authority": experiment["execution_authority"],
            "promotion_status": "NOT_PROMOTED",
            "profitability_status": "NOT_QUALIFIED_PROFITABLE",
            "capture_design_status": (
                "EXP009_CAPTURE_DESIGN_CANDIDATE"
                if number == 9
                else "FROZEN_PR57_WINDOW_REQUIREMENTS_ONLY"
            ),
        }
        rows.append(row)

    ids = [row["experiment_id"] for row in rows]
    if len(rows) != 25 or len(set(ids)) != 25:
        raise AssertionError("exactly 25 unique experiments required")
    if any(
        row["targets"] and any(item in row["predictors"] for item in row["targets"]) for row in rows
    ):
        raise AssertionError("target/predictor role collision")
    return {
        "schema_version": "robin-experiment-data-window-matrix-v1",
        "status": STATUS,
        "source_protocol_sha256": protocols["content_sha256"],
        "row_count": len(rows),
        "category_counts": dict(
            sorted(Counter(row["supportability_category"] for row in rows).items())
        ),
        "role_policy": {
            "PREDICTOR": "FEATURE or ODDS dependency available and ingested no later than cutoff",
            "TARGET": "post-cutoff outcome snapshot; never eligible as a predictor",
            "LABEL": "settled post-event outcome with result and settlement receipts",
            "METADATA": "receipt-backed pre-cutoff identity/context",
        },
        "experiments": rows,
    }


def requirement_interval(kickoff: datetime, window_id: str) -> tuple[datetime, datetime, datetime]:
    window = WINDOWS[window_id]
    earliest = kickoff - timedelta(minutes=window["earliest_minutes_before_kickoff"])
    latest = kickoff - timedelta(minutes=window["latest_minutes_before_kickoff"])
    ideal = kickoff - timedelta(minutes=window["ideal_minutes_before_kickoff"])
    if not earliest <= ideal <= latest:
        raise AssertionError(window_id)
    return earliest, latest, ideal


def make_due_items(
    fixtures: Iterable[dict[str, Any]],
    windows: Iterable[str],
    markets_by_window: dict[str, tuple[str, ...]] | None = None,
    endpoint_family: str = "bulk_odds",
) -> list[dict[str, Any]]:
    markets_by_window = markets_by_window or {window: ("h2h",) for window in windows}
    items: list[dict[str, Any]] = []
    for match in fixtures:
        kickoff = parse_utc(match["kickoff_at"])
        for window_id in windows:
            earliest, latest, ideal = requirement_interval(kickoff, window_id)
            markets = tuple(sorted(markets_by_window[window_id]))
            role = WINDOWS[window_id]["role"]
            role_class = WINDOWS[window_id]["role_class"]
            request_key = {
                "source": "THE_ODDS_API_V4",
                "endpoint_family": endpoint_family,
                "sport_key": match["sport_key"],
                "region": "eu",
                "markets": list(markets),
                "odds_format": "decimal",
                "date_format": "iso",
                "temporal_role_class": role_class,
            }
            if endpoint_family == "event_odds":
                request_key["provider_event_identity"] = match["fixture_id"]
            items.append(
                {
                    "requirement_id": f"{match['fixture_id']}:{window_id}:{endpoint_family}:{'+'.join(markets)}",
                    "fixture_id": match["fixture_id"],
                    "competition": match["competition"],
                    "kickoff_at": match["kickoff_at"],
                    "window_id": window_id,
                    "temporal_role": role,
                    "protocol_role_bindings": WINDOWS[window_id]["protocol_role_bindings"],
                    "window_authority": WINDOWS[window_id]["authority"],
                    "earliest_admissible_time": iso(earliest),
                    "latest_admissible_time": iso(latest),
                    "ideal_capture_time": iso(ideal),
                    "markets": list(markets),
                    "source_request_key": request_key,
                    "credit_cost_if_ungrouped": len(markets),
                }
            )
    return sorted(items, key=lambda item: item["requirement_id"])


def canonical_key(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def group_due_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        buckets[canonical_key(item["source_request_key"])].append(item)

    raw_groups: list[dict[str, Any]] = []
    for key, bucket in sorted(buckets.items()):
        remaining = sorted(
            bucket, key=lambda item: (item["latest_admissible_time"], item["requirement_id"])
        )
        while remaining:
            scheduled = parse_utc(remaining[0]["latest_admissible_time"])
            covered = [
                item
                for item in remaining
                if parse_utc(item["earliest_admissible_time"])
                <= scheduled
                <= parse_utc(item["latest_admissible_time"])
            ]
            covered_ids = {item["requirement_id"] for item in covered}
            remaining = [item for item in remaining if item["requirement_id"] not in covered_ids]
            request_key = json.loads(key)
            role_classes = sorted(
                {item["source_request_key"]["temporal_role_class"] for item in covered}
            )
            roles = sorted({item["temporal_role"] for item in covered})
            if len(role_classes) != 1:
                raise AssertionError("predictor and target requirements may not share a call group")
            raw_groups.append(
                {
                    "scheduled_at": iso(scheduled),
                    "source_request_key": request_key,
                    "temporal_role": roles[0],
                    "temporal_role_class": role_classes[0],
                    "role_binding_rule": "A neutral raw receipt may support different experiments, but every experiment gets an explicit role-bound snapshot; EXP006 H2 is TARGET and never enters its predictor pipeline.",
                    "requirement_ids": sorted(covered_ids),
                    "fixture_ids": sorted({item["fixture_id"] for item in covered}),
                    "windows_satisfied": sorted({item["window_id"] for item in covered}),
                    "credit_cost": len(request_key["markets"]),
                    "compatibility_proof": {
                        "same_sport_key": True,
                        "same_markets": True,
                        "same_region": True,
                        "scheduled_inside_every_interval": True,
                        "no_cutoff_violated": True,
                        "target_not_used_as_predictor": True,
                    },
                }
            )

    groups = sorted(
        raw_groups,
        key=lambda group: (group["scheduled_at"], canonical_key(group["source_request_key"])),
    )
    for index, group in enumerate(groups, start=1):
        group["call_group_id"] = f"CALL-GROUP-{index:04d}"
    return groups


def grouping_metrics(items: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls_before_grouping": len(items),
        "calls_after_grouping": len(groups),
        "calls_saved": len(items) - len(groups),
        "credits_before_grouping": sum(item["credit_cost_if_ungrouped"] for item in items),
        "credits_after_grouping": sum(group["credit_cost"] for group in groups),
        "credits_saved": sum(item["credit_cost_if_ungrouped"] for item in items)
        - sum(group["credit_cost"] for group in groups),
        "protocols_preserved": sorted(
            {p for item in items for p in WINDOWS[item["window_id"]]["protocols"]}
        ),
        "protocols_preserved_meaning": "Temporal-window admissibility only; this is not evidence that markets, labels, supplementary sources or sample-size gates are satisfied.",
    }


def verify_call_group_contract(schedule: dict[str, Any]) -> None:
    """Recompute grouping coverage, keys, roles, and time bounds from requirements."""
    for window_id, expected_window in WINDOWS.items():
        observed_window = schedule["window_definitions"].get(window_id)
        for field in (
            "authority",
            "role",
            "role_class",
            "protocol_role_bindings",
            "maximum_staleness_minutes",
        ):
            if observed_window is None or observed_window.get(field) != expected_window.get(field):
                raise AssertionError(f"window authority mismatch: {window_id}:{field}")
    requirements = schedule["capture_requirements"]
    by_id = {item["requirement_id"]: item for item in requirements}
    if len(by_id) != len(requirements):
        raise AssertionError("duplicate capture requirement id")

    coverage: Counter[str] = Counter()
    for group in schedule["call_groups"]:
        scheduled = parse_utc(group["scheduled_at"])
        members = [by_id[requirement_id] for requirement_id in group["requirement_ids"]]
        if not members:
            raise AssertionError(f"empty call group: {group['call_group_id']}")
        coverage.update(group["requirement_ids"])
        if any(member["source_request_key"] != group["source_request_key"] for member in members):
            raise AssertionError(f"request-key mismatch: {group['call_group_id']}")
        if any(
            not (
                parse_utc(member["earliest_admissible_time"])
                <= scheduled
                <= parse_utc(member["latest_admissible_time"])
            )
            for member in members
        ):
            raise AssertionError(f"admissible interval violated: {group['call_group_id']}")
        for member in members:
            expected_window = WINDOWS[member["window_id"]]
            bindings = member["protocol_role_bindings"]
            if set(bindings["PREDICTOR"]) & set(bindings["TARGET"]):
                raise AssertionError(f"protocol role collision: {member['requirement_id']}")
            if (
                member["temporal_role"] != expected_window["role"]
                or bindings != expected_window["protocol_role_bindings"]
                or member["window_authority"] != expected_window["authority"]
                or member["source_request_key"]["temporal_role_class"]
                != expected_window["role_class"]
            ):
                raise AssertionError(f"window binding mismatch: {member['requirement_id']}")
            expected = requirement_interval(parse_utc(member["kickoff_at"]), member["window_id"])
            observed = (
                parse_utc(member["earliest_admissible_time"]),
                parse_utc(member["latest_admissible_time"]),
                parse_utc(member["ideal_capture_time"]),
            )
            if observed != expected:
                raise AssertionError(
                    f"kickoff-derived interval mismatch: {member['requirement_id']}"
                )
        if sorted({member["fixture_id"] for member in members}) != group["fixture_ids"]:
            raise AssertionError(f"fixture membership mismatch: {group['call_group_id']}")
        if sorted({member["window_id"] for member in members}) != group["windows_satisfied"]:
            raise AssertionError(f"window membership mismatch: {group['call_group_id']}")
        roles = {member["temporal_role"] for member in members}
        role_classes = {member["source_request_key"]["temporal_role_class"] for member in members}
        if roles != {group["temporal_role"]} or role_classes != {group["temporal_role_class"]}:
            raise AssertionError(f"temporal role collision: {group['call_group_id']}")
        if group["credit_cost"] != len(group["source_request_key"]["markets"]):
            raise AssertionError(f"credit cost mismatch: {group['call_group_id']}")

    expected_coverage = Counter({requirement_id: 1 for requirement_id in by_id})
    if coverage != expected_coverage:
        raise AssertionError("capture requirements must be covered exactly once")


def grouped_candidate_snapshot_calls(
    fixtures: list[dict[str, Any]], offsets_hours: list[float]
) -> int:
    """Minimum bulk h2h calls for one all-predictor candidate via interval stabbing."""
    buckets: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for match in fixtures:
        kickoff = parse_utc(match["kickoff_at"])
        for offset in offsets_hours:
            if math.isclose(offset, 24.0):
                earliest, latest = kickoff - timedelta(hours=26), kickoff - timedelta(hours=24)
            elif math.isclose(offset, 2.0):
                earliest, latest = (
                    kickoff - timedelta(hours=2, minutes=15),
                    kickoff - timedelta(hours=2),
                )
            else:
                earliest = latest = kickoff - timedelta(hours=offset)
            # Match the portfolio scheduler's fail-closed role partition: H2 also
            # binds the EXP006 TARGET and is not coalesced with pure predictors.
            role_partition = (
                "H2_WITH_EXP006_TARGET_BINDING" if math.isclose(offset, 2.0) else "PURE_PREDICTOR"
            )
            buckets[f"{match['sport_key']}|{role_partition}"].append((earliest, latest))
    calls = 0
    for intervals in buckets.values():
        remaining = sorted(intervals, key=lambda interval: interval[1])
        while remaining:
            point = remaining[0][1]
            calls += 1
            remaining = [
                interval for interval in remaining if not (interval[0] <= point <= interval[1])
            ]
    return calls


def four_snapshot_analysis() -> dict[str, Any]:
    alternatives: list[dict[str, Any]] = [
        {"id": "ALT_A", "windows": [24, 12, 6, 2], "complexity": 1, "label": "H24/H12/H6/H2"},
        {"id": "ALT_B", "windows": [24, 8, 4, 2], "complexity": 1, "label": "H24/H8/H4/H2"},
        {
            "id": "ALT_C",
            "windows": [24, 16 + 40 / 60, 9 + 20 / 60, 2],
            "complexity": 3,
            "label": "H24/H16h40/H9h20/H2 equal grid",
        },
    ]
    max_grouped_calls = 0
    for alt in alternatives:
        gaps = [round(alt["windows"][i] - alt["windows"][i + 1], 4) for i in range(3)]
        alt["calls_per_fixture"] = 4
        alt["h2h_credits_per_fixture"] = 4
        alt["exact_67_fixture_calls_before_grouping"] = len(FIXTURES) * 4
        alt["exact_67_fixture_calls_after_grouping"] = grouped_candidate_snapshot_calls(
            FIXTURES, alt["windows"]
        )
        alt["exact_67_fixture_h2h_credits_after_grouping"] = alt[
            "exact_67_fixture_calls_after_grouping"
        ]
        l1_fixtures = [match for match in FIXTURES if match["league_code"] == "L1"]
        alt["ligue1_18_fixture_calls_before_grouping"] = len(l1_fixtures) * 4
        alt["ligue1_18_fixture_calls_after_grouping"] = grouped_candidate_snapshot_calls(
            l1_fixtures, alt["windows"]
        )
        alt["gaps_hours"] = gaps
        alt["maximum_unsampled_gap_hours"] = max(gaps)
        alt["last_gap_before_h2_hours"] = gaps[-1]
        alt["complexity_scale_1_low_3_high"] = alt.pop("complexity")
        max_grouped_calls = max(max_grouped_calls, alt["exact_67_fixture_calls_after_grouping"])
    for alt in alternatives:
        alt["weighted_design_score_lower_is_better"] = round(
            0.25 * (alt["exact_67_fixture_calls_after_grouping"] / max_grouped_calls)
            + 0.35 * (alt["maximum_unsampled_gap_hours"] / 16)
            + 0.20 * (alt["last_gap_before_h2_hours"] / (22 / 3))
            + 0.20 * (alt["complexity_scale_1_low_3_high"] / 3),
            4,
        )
        alt["authority"] = "DESIGN_CANDIDATE_ONLY_NOT_DERIVED_AS_A_FROZEN_PR57_WINDOW_SET"
    selected = min(alternatives, key=lambda item: item["weighted_design_score_lower_is_better"])
    return {
        "protocol_fact": "EXP009 freezes minimum_snapshots=4 but names no intermediate windows or staleness bounds.",
        "scoring": {
            "per_fixture_calls_and_credits": "tied at four, but event-aware grouped calls differ and are explicitly scored",
            "weights": {
                "event_aware_grouped_calls": 0.25,
                "maximum_gap": 0.35,
                "last_gap_before_H2": 0.20,
                "scheduling_complexity": 0.20,
            },
            "normalization": {
                "grouped_calls": max_grouped_calls,
                "maximum_gap_hours": 16,
                "last_gap_hours": 22 / 3,
                "complexity_max": 3,
            },
        },
        "alternatives": alternatives,
        "selected_candidate": selected["label"],
        "selected_status": "PROPOSED_NOT_FROZEN_REQUIRES_PR57_AMENDMENT_BEFORE_ACTIVATION",
        "why": "ALT_A has the lowest declared score after including grouped calls/credits; it accepts more calls than ALT_B in exchange for a materially shorter maximum unsampled gap, with the same whole-hour complexity.",
    }


def build_event_schedule() -> dict[str, Any]:
    due = make_due_items(FIXTURES, FULL_WINDOWS)
    groups = group_due_items(due)
    exact_by_league: list[dict[str, Any]] = []
    for code, league in LEAGUES.items():
        league_fixtures = [item for item in FIXTURES if item["league_code"] == code]
        league_due = [item for item in due if item["competition"] == league["competition"]]
        req_ids = {item["requirement_id"] for item in league_due}
        league_groups = [
            group for group in groups if any(req in req_ids for req in group["requirement_ids"])
        ]
        full_season_groups_per_window = league["matchdays"] * league["planning_groups_per_matchday"]
        minimal_after = full_season_groups_per_window * len(MINIMAL_WINDOWS)
        full_after = full_season_groups_per_window * len(FULL_WINDOWS)
        exact_by_league.append(
            {
                "league_code": code,
                "competition": league["competition"],
                "full_season_fixture_count_official": league["full_season_fixtures"],
                "matchdays": league["matchdays"],
                "included_exact_horizon_fixtures": len(league_fixtures),
                "included_matchdays": sorted({item["matchday"] for item in league_fixtures}),
                "included_distinct_kickoff_groups": len(
                    {item["kickoff_at"] for item in league_fixtures}
                ),
                "included_full_window_captures_before_grouping": len(league_due),
                "included_full_window_calls_after_grouping": len(league_groups),
                "planning_groups_per_matchday": league["planning_groups_per_matchday"],
                "planning_basis": "ceil or conservative uplift from currently confirmed kickoff-group sample; refresh when official times change",
                "full_season_planning_groups_per_window": full_season_groups_per_window,
                "minimal_three_window_calls_before_grouping": league["full_season_fixtures"]
                * len(MINIMAL_WINDOWS),
                "minimal_three_window_calls_after_grouping": minimal_after,
                "full_five_window_calls_before_grouping": league["full_season_fixtures"]
                * len(FULL_WINDOWS),
                "full_five_window_calls_after_grouping": full_after,
                "minimal_calls_per_active_week": round(minimal_after / 44, 2),
                "minimal_calls_per_active_month": math.ceil(minimal_after / 10),
                "minimal_peak_month_proxy": math.ceil((minimal_after / 10) * 1.25),
                "full_calls_per_active_week": round(full_after / 44, 2),
                "full_calls_per_active_month": math.ceil(full_after / 10),
                "full_peak_month_proxy": math.ceil((full_after / 10) * 1.25),
                "source_ids": league["source_ids"],
                "kickoff_time_status": league["kickoff_time_status"],
            }
        )
    return {
        "schema_version": "robin-event-aware-capture-schedule-v1",
        "status": STATUS,
        "calendar_access_date": ACCESS_DATE,
        "scope": {
            "included_exact_fixture_horizon": "67 fixtures with currently published display/exact times across five leagues",
            "full_season_fixture_count": sum(v["full_season_fixtures"] for v in LEAGUES.values()),
            "full_season_exact_kickoff_limitation": "Most later kickoffs are not yet officially fixed; fixture-level UTC requirements must be regenerated after every official revision.",
            "unknown_time_policy": "KICKOFF_TIME_TO_BE_CONFIRMED; never synthesize UTC from a matchday date.",
        },
        "window_definitions": WINDOWS,
        "minimal_window_set": {
            "windows": MINIMAL_WINDOWS,
            "note": "H24 is a predictor. H2 is a predictor for most protocols but a distinct TARGET for EXP006. H1 is TARGET for EXP005/EXP023. Role-bound snapshots never cross within an experiment.",
        },
        "full_planning_candidate": {
            "windows": FULL_WINDOWS,
            "note": "H12/H6 and the strict lower bound for H1 require a PR57 amendment before activation.",
        },
        "four_snapshot_analysis": four_snapshot_analysis(),
        "grouping_algorithm": {
            "name": "greedy minimum interval stabbing by immutable source request key",
            "steps": [
                "partition by source, endpoint family, sport_key, region, exact markets and temporal role",
                "sort requirements by latest admissible time",
                "schedule at the first remaining latest time",
                "cover every interval containing that time, then repeat",
            ],
            "optimality": "For intervals on a line inside one request-key partition, earliest-finish greedy minimizes capture times.",
            "prohibitions": [
                "no cross-sport grouping",
                "no cross-region grouping",
                "no cross-market-key grouping",
                "no TARGET/PREDICTOR group sharing",
                "no request outside any member interval",
            ],
        },
        "exact_horizon_metrics": grouping_metrics(due, groups),
        "league_summaries": exact_by_league,
        "fixtures": FIXTURES,
        "capture_requirements": due,
        "call_groups": groups,
    }


def scenario(
    scenario_id: str,
    label: str,
    league_codes: list[str],
    window_market_counts: list[tuple[str, int]],
    capture_surface_candidates: list[str],
    additional_calls: int = 0,
    additional_credits: int = 0,
    additional_call_detail: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    fixtures = sum(LEAGUES[code]["full_season_fixtures"] for code in league_codes)
    groups_per_window = sum(
        LEAGUES[code]["matchdays"] * LEAGUES[code]["planning_groups_per_matchday"]
        for code in league_codes
    )
    calls_before = fixtures * len(window_market_counts) + additional_calls
    calls_after = groups_per_window * len(window_market_counts) + additional_calls
    credits_before = (
        fixtures * sum(markets for _, markets in window_market_counts) + additional_credits
    )
    annual_credits = (
        groups_per_window * sum(markets for _, markets in window_market_counts) + additional_credits
    )
    active_month_calls = math.ceil(calls_after / 10)
    active_month_credits = math.ceil(annual_credits / 10)
    peak_calls = math.ceil((calls_after / 10) * 1.25)
    peak_credits = math.ceil((annual_credits / 10) * 1.25)
    reserve = math.ceil(peak_credits * 0.20)
    required_capacity = peak_credits + reserve
    return {
        "scenario_id": scenario_id,
        "label": label,
        "league_codes": league_codes,
        "window_market_pattern": [
            {"window_id": window, "market_count": markets}
            for window, markets in window_market_counts
        ],
        "additional_ungroupable_calls": {
            "calls": additional_calls,
            "credits": additional_credits,
            "detail": additional_call_detail,
        },
        "calls_before_grouping": calls_before,
        "calls_after_grouping": calls_after,
        "calls_saved": calls_before - calls_after,
        "calls_per_active_week": round(calls_after / 44, 2),
        "calls_per_calendar_week_annualized": round(calls_after / 52, 2),
        "calls_per_active_month": active_month_calls,
        "peak_month_calls_proxy": peak_calls,
        "credits_before_grouping": credits_before,
        "credits_saved": credits_before - annual_credits,
        "credits_per_active_week": round(annual_credits / 44, 2),
        "credits_per_active_month": active_month_credits,
        "peak_month_credits_proxy": peak_credits,
        "annual_credits": annual_credits,
        "safety_reserve": {
            "rate": 0.20,
            "credits_on_peak_month": reserve,
            "monthly_capacity_required": required_capacity,
        },
        "free_plan_compatible": required_capacity <= 500,
        "paid_plan_compatible": True,
        "lowest_public_plan_fitting_peak_plus_reserve": "Starter 500"
        if required_capacity <= 500
        else "20K ($30/month)",
        "protocols_enabled": [],
        "protocol_capture_surface_candidates": capture_surface_candidates,
        "execution_note": "No protocol is executable from a budget alone; receipts, labels, source contracts, minimum sample and authorization remain required.",
        "note": note,
    }


def build_budgets() -> dict[str, Any]:
    ids_1_8 = [f"RDS-EXP-V1-{i:03d}" for i in range(1, 9)]
    cross = [
        "RDS-EXP-V1-009",
        "RDS-EXP-V1-010",
        "RDS-EXP-V1-023",
        "RDS-EXP-V1-024",
        "RDS-EXP-V1-025",
    ]
    scenarios = [
        scenario(
            "S0",
            "Ligue 1, h2h, minimal H24/H2/H1",
            ["L1"],
            [(w, 1) for w in MINIMAL_WINDOWS],
            ids_1_8,
        ),
        scenario(
            "S1",
            "Ligue 1, h2h+totals at every minimal window",
            ["L1"],
            [(w, 2) for w in MINIMAL_WINDOWS],
            ids_1_8 + ["RDS-EXP-V1-016", "RDS-EXP-V1-024", "RDS-EXP-V1-025"],
            note="Coverage comparison only: totals-derived candidates remain conditional on paired 2.5 coverage; bulk odds cannot support EXP010/EXP023 market skew.",
        ),
        scenario(
            "S2",
            "Ligue 1, all necessary windows with event-specific synchronization",
            ["L1"],
            [("H12", 1), ("H6", 1)],
            ids_1_8 + cross + ["RDS-EXP-V1-016"],
            additional_calls=LEAGUES["L1"]["full_season_fixtures"] * 3,
            additional_credits=LEAGUES["L1"]["full_season_fixtures"] * 3 * 2,
            additional_call_detail="One combined event-odds h2h+totals call per fixture at H24, H2 and H1; bulk h2h only at H12/H6.",
            note="H12/H6 are design candidates only; event-specific calls enforce EXP010 H24/H2 and EXP023 H2/H1 clock observability.",
        ),
        scenario(
            "S3",
            "Ligue 1 + Premier League, h2h minimal",
            ["L1", "EPL"],
            [(w, 1) for w in MINIMAL_WINDOWS],
            ids_1_8,
        ),
        scenario(
            "S4",
            "Five leagues, h2h minimal",
            list(LEAGUES),
            [(w, 1) for w in MINIMAL_WINDOWS],
            ids_1_8,
        ),
        scenario(
            "S5",
            "Five leagues h2h systematic + five-fixture/month event-odds totals canary",
            list(LEAGUES),
            [(w, 1) for w in MINIMAL_WINDOWS],
            ids_1_8 + cross[1:],
            additional_calls=150,
            additional_credits=300,
            additional_call_detail="5 canary fixtures × H24/H2/H1 × 10 active months; combined event-odds h2h+totals, ungroupable by event ID.",
            note="Canary covers EXP010 H24/H2 and EXP023 H2/H1. /events discovery is free and excluded.",
        ),
        scenario(
            "S6",
            "Five leagues, full event-specific synchronization coverage",
            list(LEAGUES),
            [("H12", 1), ("H6", 1)],
            ids_1_8 + cross + ["RDS-EXP-V1-016"],
            additional_calls=sum(v["full_season_fixtures"] for v in LEAGUES.values()) * 3,
            additional_credits=sum(v["full_season_fixtures"] for v in LEAGUES.values()) * 3 * 2,
            additional_call_detail="One combined event-odds h2h+totals call per fixture at H24, H2 and H1; bulk h2h only at H12/H6.",
            note="Includes EXP010 H24/H2 and EXP023 H2/H1 market-level clocks. 20% reserve is applied to the peak-month proxy; exact future kickoffs must replace extrapolation before purchase.",
        ),
    ]
    return {
        "schema_version": "robin-credit-budget-scenarios-v1",
        "status": STATUS,
        "pricing_access_date": ACCESS_DATE,
        "provider": {
            "name": "The Odds API",
            "official_domain": "the-odds-api.com",
            "impersonator_domain_forbidden": "theoddsapi.com",
            "bulk_odds_credit_formula": "requested markets × requested regions",
            "explicit_bookmaker_equivalence": "each started block of 10 bookmakers counts as one region",
            "event_odds_credit_formula": "unique markets returned × regions; empty response not charged",
            "free_endpoints": ["/v4/sports", "/v4/sports/{sport}/events"],
            "quota_headers": ["x-requests-remaining", "x-requests-used", "x-requests-last"],
            "monthly_reset": "first day of each month",
            "plans_usd_per_month": [
                {"name": "Starter", "credits": 500, "price_usd": 0, "historical": False},
                {"name": "20K", "credits": 20000, "price_usd": 30, "historical": True},
                {"name": "100K", "credits": 100000, "price_usd": 59, "historical": True},
                {"name": "5M", "credits": 5000000, "price_usd": 119, "historical": True},
                {"name": "15M", "credits": 15000000, "price_usd": 249, "historical": True},
            ],
            "public_rate_limit": "No numeric requests-per-second limit published; HTTP 429 is documented.",
        },
        "annualization_method": {
            "official_full_season_fixtures": sum(
                v["full_season_fixtures"] for v in LEAGUES.values()
            ),
            "official_matchdays": sum(v["matchdays"] for v in LEAGUES.values()),
            "planned_kickoff_groups_per_window": sum(
                v["matchdays"] * v["planning_groups_per_matchday"] for v in LEAGUES.values()
            ),
            "active_weeks": 44,
            "active_months": 10,
            "peak_month_factor": 1.25,
            "important_limit": "Kickoff-group counts are conservative extrapolations from the confirmed horizon, not final season call counts.",
            "cross_window_coalescence": "Not assumed in annual scenarios; this avoids optimistic savings. Exact-horizon schedule does allow valid interval intersections.",
        },
        "scenarios": scenarios,
    }


RECEIPT_FIELDS = [
    "receipt_id",
    "source_name",
    "source_url",
    "request_identity",
    "request_identity_secret_redacted",
    "payload_sha256",
    "payload_byte_length",
    "http_status",
    "safe_response_headers",
    "source_published_at",
    "robin_first_observed_at",
    "robin_ingested_at",
    "available_at",
    "capture_code_revision",
    "mapping_revision",
    "projection_revision",
    "storage_identity",
    "availability_status",
    "supersedes_receipt_id",
    "schema_fingerprint",
    "licence_status",
    "snapshot_candidate_id",
    "receipt_canonical_sha256",
    "x_requests_remaining",
    "x_requests_used",
    "x_requests_last",
    "target_window_id",
    "target_window_end",
    "result_available_at",
    "settlement_receipt_at",
]


def build_pilot() -> dict[str, Any]:
    pilot_fixtures = [item for item in FIXTURES if item["league_code"] == "L1"]
    bulk_due = make_due_items(pilot_fixtures, FULL_WINDOWS)
    bulk_groups = group_due_items(bulk_due)
    canary_ids = [
        "L1-2026-27-MD01-01",
        "L1-2026-27-MD01-02",
        "L1-2026-27-MD01-09",
        "L1-2026-27-MD02-01",
        "L1-2026-27-MD02-09",
    ]
    canary_fixtures = [item for item in pilot_fixtures if item["fixture_id"] in canary_ids]
    canary_calls: list[dict[str, Any]] = []
    for match in canary_fixtures:
        kickoff = parse_utc(match["kickoff_at"])
        for window_id in ["H24", "H2", "H1"]:
            _, _, ideal = requirement_interval(kickoff, window_id)
            canary_calls.append(
                {
                    "fixture_id": match["fixture_id"],
                    "window_id": window_id,
                    "temporal_role": WINDOWS[window_id]["role"],
                    "protocol_role_bindings": WINDOWS[window_id]["protocol_role_bindings"],
                    "scheduled_at": iso(ideal),
                    "endpoint": "/v4/sports/{sport}/events/{eventId}/odds",
                    "markets": ["h2h", "totals"],
                    "region": "eu",
                    "maximum_credit_cost": 2,
                    "purpose": "same-receipt bookmaker×market last_update and paired totals 2.5 coverage",
                }
            )
    bulk_calls = len(bulk_groups)
    event_discovery_calls = 2
    chargeable_calls = bulk_calls + len(canary_calls)
    total_http_calls = chargeable_calls + event_discovery_calls
    credits = sum(group["credit_cost"] for group in bulk_groups) + sum(
        call["maximum_credit_cost"] for call in canary_calls
    )
    return {
        "schema_version": "robin-first-pilot-specification-v1",
        "status": STATUS + ["ROBIN_FIRST_RECEIPT_BACKED_CAPTURE_PILOT_SPECIFIED_NOT_AUTHORIZED"],
        "pilot_id": "ROBIN-L1-J1-J2-2026-27-RECEIPT-CANARY-V1",
        "authorization": "NOT_AUTHORIZED",
        "scope": {
            "competition": "Ligue 1",
            "matchdays": [1, 2],
            "fixture_count": len(pilot_fixtures),
            "canary_fixture_count": len(canary_fixtures),
            "no_backfill": True,
            "fixtures": pilot_fixtures,
            "market_sync_canary_fixture_ids": canary_ids,
        },
        "markets": {
            "systematic": ["h2h"],
            "pilot": ["h2h", "totals:2.5"],
            "totals_status": "TOTALS_COVERAGE_TO_BE_PROVEN",
            "paired_definition": "same fixture, bookmaker, combined event-odds receipt, complete h2h, bilateral totals outcome at point=2.5",
            "strategy_comparison": [
                {
                    "strategy": "H2H_ONLY",
                    "status": "SYSTEMATIC_BASELINE",
                    "credits_per_region": 1,
                },
                {
                    "strategy": "H2H_PLUS_TOTALS_SYSTEMATIC",
                    "status": "REJECTED_UNTIL_TOTALS_COVERAGE_PROVEN",
                    "credits_per_region": 2,
                },
                {
                    "strategy": "H2H_SYSTEMATIC_PLUS_TOTALS_PILOT",
                    "status": "SELECTED_DESIGN_ONLY",
                    "credits_per_region": "1 systematic; 2 on five canaries",
                },
                {
                    "strategy": "TOTALS_AFTER_COVERAGE_THRESHOLD",
                    "status": "GATED_BY_TOTALS_COVERAGE_TO_BE_PROVEN",
                    "credits_per_region": 2,
                },
            ],
        },
        "windows": {
            "systematic_bulk": FULL_WINDOWS,
            "event_odds_canary": ["H24", "H2", "H1"],
            "authority_caveat": "H12/H6, the strict H1 lower bound and EXP010 market-clock semantics must be frozen in an amended protocol before any activation.",
        },
        "planned_calls": {
            "bulk_h2h_calls_before_grouping": len(bulk_due),
            "bulk_h2h_calls_after_grouping": bulk_calls,
            "combined_event_odds_canary_calls": len(canary_calls),
            "free_event_discovery_calls": event_discovery_calls,
            "the_odds_api_chargeable_calls": chargeable_calls,
            "the_odds_api_total_http_calls": total_http_calls,
            "settlement_source_calls": None,
            "settlement_source_status": "SOURCE_2_NOT_SELECTED",
        },
        "planned_credits": {
            "bulk_h2h": sum(group["credit_cost"] for group in bulk_groups),
            "combined_event_odds_canary_maximum": sum(
                call["maximum_credit_cost"] for call in canary_calls
            ),
            "total_maximum": credits,
            "free_plan_capacity": 500,
        },
        "bulk_call_groups": bulk_groups,
        "event_odds_canary_calls": canary_calls,
        "payloads_retained_if_authorized": [
            "exact raw response bytes",
            "HTTP status, content type, byte length and safe headers without API key",
            "canonical request identity with secret redacted",
            "quota headers",
            "receipt JSON and canonical receipt SHA-256",
            "fixture mapping projection",
            "bookmaker×market×outcome projection including market.last_update",
            "explicit absence/partial-market evidence",
        ],
        "receipt_contract": {
            "required_fields": RECEIPT_FIELDS,
            "field_applicability": {
                "all_receipts": [
                    field
                    for field in RECEIPT_FIELDS
                    if field
                    not in {
                        "target_window_id",
                        "target_window_end",
                        "result_available_at",
                        "settlement_receipt_at",
                    }
                ],
                "TARGET_receipts_add": ["target_window_id", "target_window_end"],
                "LABEL_receipts_add": ["result_available_at", "settlement_receipt_at"],
            },
            "time_invariants": [
                "robin_first_observed_at <= robin_ingested_at",
                "available_at=max(trusted source_published_at, robin_first_observed_at)",
                "PREDICTOR: available_at<=cutoff_at and robin_ingested_at<=cutoff_at",
                "TARGET: target_window_id and target_window_end required; stored separately and never exposed to feature computation",
                "LABEL: result_available_at and settlement_receipt_at are required",
            ],
            "licence_invariant": "licence_status must equal APPROVED before admission",
            "storage": "immutable append-only raw bytes and receipts outside Git; no secret in path, payload metadata or logs",
        },
        "snapshot_schema": {
            "identity": [
                "snapshot_id",
                "fixture_id",
                "receipt_id",
                "payload_sha256",
                "projection_sha256",
            ],
            "temporal": [
                "window_id",
                "temporal_role",
                "cutoff_at",
                "available_at",
                "robin_ingested_at",
                "target_window_id",
                "target_window_end",
                "result_available_at",
                "settlement_receipt_at",
            ],
            "market": [
                "bookmaker_key",
                "market_key",
                "market_last_update",
                "outcome_name",
                "price",
                "point",
            ],
            "lineage": [
                "capture_code_revision",
                "mapping_revision",
                "projection_revision",
                "schema_fingerprint",
            ],
            "role_isolation": "PREDICTOR, TARGET and LABEL snapshots have distinct identities and storage prefixes.",
            "shared_raw_receipt_rule": "One neutral raw payload may map to different roles in different experiments; role-bound snapshot IDs and feature access controls prevent within-experiment leakage. EXP006 H2 is TARGET.",
        },
        "retention": {
            "status": "RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED",
            "provisional_mechanics": "append-only immutable storage; exact duration intentionally unset",
            "stop_rule": "No raw provider payload is retained until written permission covers internal receipt-backed retention.",
        },
        "thresholds": {
            "h2h": "at least five complete 1X2 bookmakers for at least 80% of all 18 fixtures at each required frozen window",
            "totals": "at least five same-receipt paired bookmakers with complete h2h and bilateral point=2.5 totals for at least 80% (4/5) canary fixtures at H24, H2 and H1",
            "market_timestamp": "both market-level last_update values non-null for every admitted pair; provider freshness skew computed within one combined receipt",
            "mapping": "100% deterministic one-to-one event mapping with kickoff/team normalization evidence",
        },
        "success_criteria": [
            "100% raw payloads and canonical receipts have SHA-256",
            "100% calls have robin_first_observed_at and robin_ingested_at",
            "available_at is never backdated and ingestion is no later than cutoff for predictors",
            "100% fixture mappings are deterministic and unambiguous",
            "offline replay produces byte-identical canonical projections without network",
            "TARGET is never used as a feature",
            "h2h and paired totals thresholds pass",
            "market-level timestamps are present for both markets in one receipt",
            f"The Odds API credit consumption is <= {credits} and quota headers reconcile exactly",
            "zero secret is present in payload metadata, receipts, logs or repository artifacts",
        ],
        "stop_criteria": [
            "legal retention not confirmed in writing",
            "H12/H6 or H1 lower-bound contract not frozen",
            "EXP010 market clock/window semantics not frozen",
            "fixture/settlement Source 2 not selected and approved",
            "schema instability or incomplete receipt",
            "ambiguous fixture mapping",
            "market-level timestamps absent or not pairable",
            "fewer than five complete h2h books on 80% of fixtures",
            "paired totals 2.5 threshold fails",
            "observed quota exceeds the model",
            "offline byte-identical replay fails",
            "source host is not the official the-odds-api.com domain",
            "a secret appears in any artifact or log",
        ],
        "experiments_execution_unblocked": [],
        "capture_mechanics_tested_for": [
            f"RDS-EXP-V1-{i:03d}" for i in list(range(1, 11)) + [23, 24, 25]
        ],
        "experiments_still_blocked": {
            "all_25": "No experiment reaches its frozen minimum sample and no settled labels are collected by this design mission.",
            "B": "supplementary feature sources remain unselected/unmaterialized",
            "C": "protocol or totals/synchronization gates remain",
            "D": "coach effective-at pipeline remains unavailable",
        },
    }


def blocker_entry(row: dict[str, Any]) -> dict[str, Any]:
    category = row["supportability_category"]
    if category == "A":
        cost = "Odds capture fits S0/S2 planning; Source 2 cost TBD"
        legal = (
            "The Odds API raw-retention permission and Source 2 licence require written approval"
        )
        priority = "P0"
    elif category == "B":
        cost = "Supplementary provider/add-on quote plus odds capture; exact cost not frozen"
        legal = (
            "Contracted redistribution/retention and source-specific field rights require review"
        )
        priority = "P1"
    elif category == "C":
        cost = (
            "Small canary fits free quota; scale prohibited until empirical gate/protocol amendment"
        )
        legal = "Raw-retention approval required; provider timestamp is not proven bookmaker-native"
        priority = "P0_DESIGN_GATE"
    else:
        cost = "Unknown until an admissible coach-claims source exists"
        legal = "No effective-at, versioned, receipt-backed coach source identified"
        priority = "P2"
    return {
        "experiment_id": row["experiment_id"],
        "supportability_category": category,
        "execution_status": row["execution_status"],
        "missing_data_or_contract": row["current_data_gate"]["convergence_gates"],
        "source_candidates": row["source_candidates"],
        "temporal_proof_required": [
            "raw payload SHA-256 and canonical receipt",
            "available_at=max(trusted source_published_at, robin_first_observed_at)",
            "robin_ingested_at no later than predictor cutoff",
            "distinct settled label receipt after event",
        ],
        "cost": cost,
        "legal_risk": legal,
        "priority": priority,
        "unblock_action": {
            "A": "close retention + Source 2, freeze missing target rules, then run receipt canary",
            "B": "complete A plus contract and materialize the named enrichment source",
            "C": "amend protocol and/or pass empirical totals/timestamp canary before scale",
            "D": "identify and contract a versioned coach effective-at source; otherwise remain blocked",
        }[category],
    }


def build_blocked(matrix: dict[str, Any]) -> dict[str, Any]:
    entries = [blocker_entry(row) for row in matrix["experiments"]]
    return {
        "schema_version": "robin-blocked-experiments-v1",
        "status": STATUS,
        "summary": {
            "experiments": len(entries),
            "execution_ready_now": 0,
            "category_counts": matrix["category_counts"],
            "universal_blockers": [
                "no receipt-backed odds corpus materialized",
                "no approved fixture+settlement Source 2",
                "minimum samples not reached",
                "no execution authorization",
            ],
        },
        "experiments": entries,
    }


def build_roadmap() -> dict[str, Any]:
    gaps = [
        {
            "data_domain": "odds h2h",
            "experiments": "001-010, 011-025 as declared",
            "current_coverage": "schema/documentation only; no receipts",
            "candidate": "The Odds API current",
            "temporal_proof": "combined raw bytes, quota headers, local observation/ingestion and cutoff",
            "cost": "500 credits/month free; $30/month for 20K",
            "legal_risk": "raw retention duration not stated publicly",
            "priority": "P0",
        },
        {
            "data_domain": "totals 2.5",
            "experiments": "010,016,023,024,025",
            "current_coverage": "COVERAGE_TO_BE_PROVEN",
            "candidate": "The Odds API combined event-odds canary",
            "temporal_proof": "same receipt, fixture, bookmaker, complete h2h+totals point 2.5, market.last_update",
            "cost": "up to 2 credits per event request in one region",
            "legal_risk": "same retention caveat; no European coverage warranty",
            "priority": "P0_GATE",
        },
        {
            "data_domain": "fixtures + kickoff revisions",
            "experiments": "all 25",
            "current_coverage": "official calendars prove pairs; most future exact UTC times remain mutable",
            "candidate": "official league publications for bootstrap; Sportmonks Football core as Source 2 candidate",
            "temporal_proof": "versioned raw fixture receipt, published/first-observed/ingested times and supersession chain",
            "cost": "Sportmonks base €29/month quoted by PR56; reverify before decision",
            "legal_risk": "contract and retention review; official calendars not a licence to republish full lists",
            "priority": "P0",
        },
        {
            "data_domain": "settled results/labels",
            "experiments": "all 25",
            "current_coverage": "no prospective settlement recommendation in PR56",
            "candidate": "Source 2 fixture+settlement provider",
            "temporal_proof": "result_available_at and settlement_receipt_at with immutable supersession",
            "cost": "TBD after provider selection",
            "legal_risk": "result rights, corrections and retention must be contractual",
            "priority": "P0",
        },
        {
            "data_domain": "xG/xGA",
            "experiments": "011-013,021",
            "current_coverage": "data/xg.parquet absent",
            "candidate": "contracted Sportmonks xG add-on or equivalent",
            "temporal_proof": "pre-cutoff historical match receipts; current-match xG barred before settlement",
            "cost": "add-on price not quantified in PR56; written quote required",
            "legal_risk": "field-level predictive/retention rights require contract",
            "priority": "P1_SOURCE3",
        },
        {
            "data_domain": "form + strength + standings",
            "experiments": "011-013,021-022",
            "current_coverage": "derived legacy surfaces are not PIT-proven",
            "candidate": "derive from approved Source 2 results plus Source 3 xG",
            "temporal_proof": "expanding training-only snapshots frozen before cutoff",
            "cost": "derived compute plus Source 2/3",
            "legal_risk": "inherits source contracts",
            "priority": "P1",
        },
        {
            "data_domain": "promoted cohorts",
            "experiments": "015 (and dependency overreach in 014/016)",
            "current_coverage": "no PR56 family/source/receipt",
            "candidate": "official season membership/publication captured before season",
            "temporal_proof": "versioned preseason registry with source receipt and effective season",
            "cost": "low internal curation after Source 2",
            "legal_risk": "citation/derived metadata only; no bulk republication",
            "priority": "P1",
        },
        {
            "data_domain": "derby registry",
            "experiments": "016 (and dependency overreach in 014/015)",
            "current_coverage": "PR56 omitted config/derbys.yaml; existing seed is unversioned/unreceipted for science",
            "candidate": "human-approved versioned preseason registry with primary/public sources",
            "temporal_proof": "freeze before season; source URLs, observed_at, revision and pair identity",
            "cost": "low curation; review time",
            "legal_risk": "source-specific citation and database-right review",
            "priority": "P1",
        },
        {
            "data_domain": "multi-competition calendars, rest, congestion, Europe",
            "experiments": "017-019",
            "current_coverage": "no PIT-complete multi-competition calendar",
            "candidate": "Sportmonks multi-competition fixtures/results + official revisions",
            "temporal_proof": "kickoff/status/completion/extra-time receipts with supersession",
            "cost": "base/coverage quote to reverify",
            "legal_risk": "fixture rights and retention review",
            "priority": "P1",
        },
        {
            "data_domain": "venue coordinates",
            "experiments": "014,017-019",
            "current_coverage": "not bound to fixture-effective receipts",
            "candidate": "Wikidata revisions (CC0) plus Source 2 venue identity",
            "temporal_proof": "revision ID, retrieved_at, venue-effective interval and neutral-site flag",
            "cost": "free",
            "legal_risk": "low, completeness/identity QA remains",
            "priority": "P1",
        },
        {
            "data_domain": "coach changes/tenure",
            "experiments": "020 (over-specified dependency also affects 021-022)",
            "current_coverage": "no prospective effective-at source pipeline",
            "candidate": "none admissible yet; official club/league claims need a versioned capture design",
            "temporal_proof": "official_effective_at plus first observed/ingested receipt and supersession",
            "cost": "unknown",
            "legal_risk": "claim provenance and automated capture rights unresolved",
            "priority": "P2_BLOCKED",
        },
    ]
    return {
        "schema_version": "robin-source-gap-roadmap-v1",
        "status": STATUS,
        "minimal_three_source_sequence": [
            {
                "order": 0,
                "gate": "Unify PR56/PR57 receipt contracts, freeze H12/H6 and H1 selection, obtain written raw-retention approval.",
            },
            {
                "order": 1,
                "source": "The Odds API current",
                "purpose": "odds h2h plus event-specific totals/timestamp canary",
                "activation": "NOT_AUTHORIZED",
            },
            {
                "order": 2,
                "source": "fixture + settlement provider (Sportmonks Football core candidate)",
                "purpose": "event identity, kickoff revisions, results and settled labels",
                "activation": "SOURCE_SELECTION_AND_CONTRACT_PENDING",
            },
            {
                "order": 3,
                "source": "first enriched source: contracted xG/xGA add-on",
                "purpose": "unlock highest-priority B experiments 011-013 and support 021",
                "activation": "QUOTE_RIGHTS_AND_SCHEMA_PENDING",
            },
        ],
        "gaps": gaps,
        "exact_pr56_continuation": [
            "Integrate both dependent commits 88c20ffe3bf05bfba6580bd489f859af695a85c4 then 81211569f7f5ae1139a4be50b90c643a00d3fdd6, or merge the full head ancestry; keep inventory/recommendation-only status.",
            "Add a source→field→experiment matrix covering settlement, xG/xGA, promoted cohorts, derbies, multi-competition calendars, rest, congestion and coach tenure.",
            "Unify PR56/PR57 into one receipt superset with ingested_at<=cutoff, approved licence, receipt hash, mapping/projection revisions and distinct TARGET/LABEL receipts.",
            "Replace matchday budgets with fixture interval scheduling and rerun quota/monthly peak calculations after official kickoff revisions.",
            "Define paired h2h/totals on one combined event receipt, same fixture/bookmaker, point 2.5, market freshness/skew and joint coverage threshold.",
            "Select an approved prospective fixture/revision/settlement authority.",
            "Confirm The Odds API raw-retention terms in writing and reverify prices/quotas and Sportmonks add-ons.",
            "Add deterministic generators, schemas and golden replay tests for hand-authored reports and complete receipts.",
            "Only under separate authorization, preserve expiring external evidence first; never backdate.",
            "Then run one future Ligue 1 canary; scale only after two matchdays, valid receipts, replay, rights, coverage and quota gates.",
        ],
    }


def build_assumptions(protocols: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "robin-assumptions-and-official-sources-v1",
        "status": STATUS,
        "analysis_dates": {"public_sources_accessed": ACCESS_DATE},
        "git_authority": {
            "repository": "dddur75/robin-stades-ng",
            "baseline": BASELINE,
            "pr56_initial_head": PR56_HEAD,
            "pr56_state_at_generation": "OPEN_DRAFT_MAIN_MERGED",
            "pr57_initial_head": PR57_INITIAL_HEAD,
            "pr57_final_head": PR57_FINAL_HEAD,
            "pr57_head_changed": PR57_FINAL_HEAD != PR57_INITIAL_HEAD,
            "pr57_merge_sha": PR57_MERGE_SHA,
            "pr57_merge_parents": [BASELINE, PR57_FINAL_HEAD],
            "pr57_final_head_is_second_parent": True,
            "pr57_protocol_content_sha256": protocols["content_sha256"],
            "pr58_final_head": PR58_FINAL_HEAD,
            "current_main_merged": PR58_MERGE_SHA,
            "convergence_manifest_sha256": CONVERGENCE_MANIFEST_SHA256,
        },
        "provider_facts": {
            "official_domain_only": "https://the-odds-api.com/",
            "forbidden_impostor_domain": "https://theoddsapi.com/",
            "bulk_odds_cost": "requested market count × requested region count",
            "market_sync_field": "bookmakers[].markets[].last_update",
            "market_sync_grain": "bookmaker_market",
            "market_sync_observation": "The official event-odds schema exposes last_update at market level under each bookmaker; the bulk odds schema also exposes bookmaker-level last_update.",
            "market_sync_semantics": "provider freshness for a bookmaker-market pair; real paired h2h/totals coverage remains to be measured",
            "market_sync_official_proof": SOURCE_URLS["odds_v4"]["url"],
            "market_synchronization_verdict": "MARKET_SYNCHRONIZATION_OBSERVABLE_DESIGN_ONLY",
            "totals_verdict": "TOTALS_COVERAGE_TO_BE_PROVEN",
            "public_pricing": {
                "starter_monthly_credits": 500,
                "20K": {"monthly_credits": 20000, "monthly_usd": 30},
                "100K": {"monthly_credits": 100000, "monthly_usd": 59},
                "5M": {"monthly_credits": 5000000, "monthly_usd": 119},
                "15M": {"monthly_credits": 15000000, "monthly_usd": 249},
            },
            "retention_verdict": "RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED",
        },
        "calendar_assumptions": {
            "official_full_season_fixture_counts": {
                code: data["full_season_fixtures"] for code, data in LEAGUES.items()
            },
            "included_exact_or_display_time_fixtures": Counter(
                item["league_code"] for item in FIXTURES
            ),
            "planning_groups_per_matchday": {
                code: data["planning_groups_per_matchday"] for code, data in LEAGUES.items()
            },
            "annualization": "44 active weeks, 10 active months, peak proxy 1.25× active-month average",
            "non_final_kickoff_policy": "refresh from official sources; KICKOFF_TIME_TO_BE_CONFIRMED until exact timezone-aware publication",
            "laliga_limit": "display-time timezone interpretation must be independently re-confirmed before scheduling",
        },
        "design_assumptions": {
            "minimal_windows": MINIMAL_WINDOWS,
            "exp009": "Only the count four is frozen. H12/H6 are a selected candidate, not a protocol fact.",
            "exp010": "The source exposes provider market-level last_update, but PR57 calls the exposure receipt-time skew and its dependency names H24/H2. Clock semantics and required windows must be amended before execution.",
            "h1": "Scheduler uses a conservative ±5-minute guard, but PR57 lacks a formal lower bound/latest-nearest rule; amendment is mandatory.",
            "h2_roles": "H2 is PREDICTOR for most protocols and a separately bound TARGET for EXP006; a neutral raw receipt never grants TARGET data to that experiment's feature path.",
            "annual_grouping": "planning groups are extrapolated and do not assume cross-window coincidences",
            "pilot": "all 18 Ligue 1 J1/J2 fixtures; five canary fixtures; no data call in this mission",
        },
        "provenance_boundary": {
            "deterministic_reproduction_scope": "Pinned Git authorities plus embedded, dated public facts produce the same repository reports byte-for-byte.",
            "does_not_claim": "Immutable provenance of live official web-page bytes; no web payload is committed.",
            "external_pack": {
                "status": "EXTERNAL_INPUT_NOT_REPRODUCIBLE_FROM_REPOSITORY",
                "manifest_sha256_reference": CONVERGENCE_MANIFEST_SHA256,
                "repository_evidence": "NOT_COMMITTED_BY_MISSION_RULE",
            },
        },
        "official_sources": [
            dict(source_id=key, accessed_at=ACCESS_DATE, **value)
            for key, value in SOURCE_URLS.items()
        ],
        "legal_caveats": [
            "The Odds API public terms allow analytics/apps but forbid resale/repackaging/redistribution as a standalone data product.",
            "Public terms do not state a raw-payload retention duration; written confirmation is a pilot stop gate.",
            "Official calendars are used for internal source mapping and derived timing, not bulk republication.",
            "Provider accuracy/freshness is not warranted; runtime mapping and operator verification remain required.",
        ],
    }


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def esc(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(map(esc, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(map(esc, row)) + " |" for row in rows)
    return "\n".join(lines)


def build_decision(
    matrix: dict[str, Any],
    schedule: dict[str, Any],
    budgets: dict[str, Any],
    pilot: dict[str, Any],
    roadmap: dict[str, Any],
    sealed_at: str,
) -> str:
    category_rows = []
    for category in "ABCD":
        members = [
            row["experiment_id"][-3:]
            for row in matrix["experiments"]
            if row["supportability_category"] == category
        ]
        meaning = {
            "A": "Odds API + fixture metadata + settlement",
            "B": "supplementary source identified",
            "C": "partially observable, not executable",
            "D": "hard data gate",
        }[category]
        category_rows.append([category, len(members), ", ".join(members), meaning])
    league_rows = [
        [
            row["competition"],
            row["full_season_fixture_count_official"],
            row["included_exact_horizon_fixtures"],
            row["included_distinct_kickoff_groups"],
            row["minimal_three_window_calls_after_grouping"],
            row["minimal_calls_per_active_week"],
            row["minimal_calls_per_active_month"],
            row["minimal_peak_month_proxy"],
        ]
        for row in schedule["league_summaries"]
    ]
    budget_rows = [
        [
            row["scenario_id"],
            row["calls_before_grouping"],
            row["calls_after_grouping"],
            row["calls_per_active_week"],
            row["calls_per_active_month"],
            row["peak_month_calls_proxy"],
            row["annual_credits"],
            row["safety_reserve"]["monthly_capacity_required"],
            "yes" if row["free_plan_compatible"] else "no",
            row["lowest_public_plan_fitting_peak_plus_reserve"],
        ]
        for row in budgets["scenarios"]
    ]
    exact = schedule["exact_horizon_metrics"]
    p_calls = pilot["planned_calls"]
    p_credits = pilot["planned_credits"]
    continuation = "\n".join(
        f"{i}. {item}" for i, item in enumerate(roadmap["exact_pr56_continuation"], start=1)
    )
    sources = "\n".join(
        f"- [{SOURCE_URLS[source_id]['authority']}]({SOURCE_URLS[source_id]['url']}) — consulté le {ACCESS_DATE}."
        for source_id in [
            "odds_home",
            "odds_v4",
            "odds_markets",
            "odds_terms",
            "odds_warning",
            "sportmonks_core",
            "sportmonks_terms",
            "wikidata_access",
            "wikidata_licence",
            "ligue1_times",
            "premier_league",
            "laliga_rfef",
            "bundesliga_times",
            "serie_a_times",
        ]
    )
    return f"""# Robin Data × Hypothesis Convergence — décision V1

Scellé le `{sealed_at}`. Statut : `{" · ".join(STATUS)}`.

## Décision

Le plan event-aware est prêt pour revue, mais le pilote reste **spécifié et non autorisé**. PR56 est un inventaire/recommandation sans donnée récupérée : `0` reçu source historique, `0/72` surface point-in-time prouvée et aucun snapshot odds. PR57 garde les 25 expériences `NOT_RUN`. Le premier mouvement utile n’est donc pas cinq ligues : c’est un canari Ligue 1 J1-J2, après fermeture juridique, unification des reçus, choix de la source de settlement et amendement des fenêtres ambiguës.

Deux conclusions gouvernent le design :

- `totals` n’a aucune matrice publique de couverture européenne suffisante ; le seuil doit être prouvé sur le pilote.
- la synchronisation h2h/totals est mesurable au niveau **fraîcheur provider bookmaker×marché** uniquement par une requête event-odds combinée. Le bulk `/odds` ne suffit pas et deux requêtes successives sont interdites. EXP010 parle toutefois de « receipt-time skew » et nomme une dépendance H24/H2 : il faut figer l'horloge `market.last_update` et les fenêtres requises avant exécution.

## Autorité Git

- PR56 head : `{PR56_HEAD}` — PR ouverte, draft, non fusionnée.
- PR57 initial head : `{PR57_INITIAL_HEAD}`.
- PR57 final head : `{PR57_FINAL_HEAD}` — inchangé.
- PR57 merge SHA : `{PR57_MERGE_SHA}`.
- Parents du merge : `{BASELINE}` puis `{PR57_FINAL_HEAD}` ; la tête finale est bien le second parent.

## Les 25 expériences

{md_table(["Classe", "Nombre", "Expériences", "Interprétation"], category_rows)}

Les 25 identifiants apparaissent exactement une fois dans `experiment-data-window-matrix.json`. Toutes les TARGET restent post-cutoff et isolées ; aucune n’est reclassée en prédicteur. `0/25` protocole est exécutable aujourd’hui, faute de reçus, labels settled, minimum d’échantillon et autorisation.

## Fenêtres minimales et volatilité

Le noyau utile est `H24 / H2 / H1`. H24 est PREDICTOR. H2 est PREDICTOR pour la plupart des protocoles mais TARGET distincte pour EXP006 ; H1 est TARGET pour EXP005/EXP023. H24 admet `[T-26h,T-24h]`; H2 prédicteur admet `[T-2h15,T-2h]` — jamais une heure. Chaque rôle possède un snapshot lié distinct, même si un payload brut neutre sert plusieurs expériences. Le scheduler utilise pour H1 un garde-fou proposé `[T-1h05,T-55m]`, mais PR57 ne fige formellement que `(cutoff,T-55m]`; une règle lower-bound/latest-nearest doit être amendée avant activation.

EXP009 fige seulement `minimum_snapshots=4`. Il ne fige ni H12, ni H8, ni H6, ni H4, ni leur staleness. Chaque candidat fait quatre appels par fixture, mais le regroupement event-aware diffère : `H24/H12/H6/H2 = 180`, `H24/H8/H4/H2 = 169`, grille égale `= 183` appels sur les 67 fixtures (respectivement 46/42/48 sur les 18 fixtures Ligue 1). Le score pondère appels groupés 25 %, gap maximal 35 %, dernier gap 20 % et complexité 20 % ; il choisit provisoirement `H24/H12/H6/H2`. Statut : `PROPOSED_NOT_FROZEN_REQUIRES_PR57_AMENDMENT_BEFORE_ACTIVATION`.

## Calendriers et ordonnanceur fixture-level

L’horizon exact/display-time contient `{len(FIXTURES)}` fixtures et `{sum(len({f["kickoff_at"] for f in FIXTURES if f["league_code"] == code}) for code in LEAGUES)}` groupes de kickoff league-scoped. Avec cinq fenêtres, il produit `{exact["calls_before_grouping"]}` exigences fixture-fenêtre, regroupées en `{exact["calls_after_grouping"]}` appels compatibles, soit `{exact["calls_saved"]}` appels et `{exact["credits_saved"]}` crédits h2h économisés. Les horaires LaLiga restent exclus d’une activation tant que le fuseau d’affichage n’est pas reconfirmé.

{md_table(["Ligue", "Fixtures saison", "Fixtures horodatées", "Groupes observés", "Appels/an 3 fenêtres", "Appels/sem. active", "Appels/mois actif", "Pic proxy"], league_rows)}

Les appels annuels sont des estimations prudentes par groupes de kickoff, pas des appels par journée. Faute d'horaires officiels complets, les pics mensuels sont des proxies `1,25×` et non un replay du calendrier saisonnier intégral. Les kickoffs futurs inconnus restent `KICKOFF_TIME_TO_BE_CONFIRMED` et doivent être régénérés à chaque révision officielle.

## Crédits The Odds API

Au {ACCESS_DATE}, le bulk odds coûte `marchés demandés × régions demandées`. En région `eu`, h2h coûte 1 crédit ; h2h+totals en coûte 2. Les endpoints sports/events sont gratuits. Le plan Starter offre 500 crédits/mois ; les plans publics sont 20K/$30, 100K/$59, 5M/$119 et 15M/$249. Les scénarios n’assument pas de coalescence inter-fenêtres annuelle et réservent 20 % au-dessus d’un pic mensuel proxy.

{md_table(["Scénario", "Avant", "Après", "/sem.", "/mois", "Pic appels", "Crédits/an", "Capacité mensuelle", "Gratuit", "Plan minimal"], budget_rows)}

PR56 annonçait 648 appels/1 296 crédits en multipliant journées×fenêtres. C’est un minimum théorique à kickoffs simultanés, pas une projection event-aware. La borne fixture-fenêtre documentaire PR56 est 6 174 appels et 12 348 crédits ; le présent plan recalcule chaque intersection depuis `kickoff_at`.

## Pilote recommandé — non autorisé

- Ligue 1 J1-J2, 18 fixtures, sans backfill ; cinq fixtures de canari sync/totals.
- Bulk h2h aux fenêtres H24/H12/H6/H2/H1 : `{p_calls["bulk_h2h_calls_before_grouping"]}` besoins ramenés à `{p_calls["bulk_h2h_calls_after_grouping"]}` appels.
- Event-odds combiné h2h+totals aux H24, H2 et H1 des cinq canaris : `{p_calls["combined_event_odds_canary_calls"]}` appels.
- Découverte `/events` : `{p_calls["free_event_discovery_calls"]}` appels gratuits.
- Total The Odds API : `{p_calls["the_odds_api_total_http_calls"]}` appels HTTP, `{p_calls["the_odds_api_chargeable_calls"]}` appels facturables, au plus `{p_credits["total_maximum"]}` crédits.
- Settlement : 18 reçus requis, mais appels/coût indéterminés tant que Source 2 n’est pas choisie.
- Seuil h2h : ≥5 bookmakers complets sur ≥80 % des 18 fixtures à chaque fenêtre gelée.
- Seuil totals : ≥5 bookmakers appariés h2h+totals 2.5 dans le même reçu sur ≥4/5 canaris, à H24, H2 et H1.
- Rétention : `RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED`; son absence arrête le pilote.

Le pilote ne « débloque » statistiquement aucune expérience : les minima vont de 1 003 à 2 400 unités et aucun label n’est capturé ici. Il valide seulement la mécanique pour 001-010 et 023-025. Les expériences B attendent Source 2/3 ; EXP020 reste bloquée faute de pipeline coach effective-at.

## Sources recommandées

1. Source 1 : The Odds API current, h2h systématique et canari event-odds h2h+totals.
2. Source 2 : fournisseur contractuel fixture+révisions+settlement ; Sportmonks Football core est le candidat PR56, à rechiffrer et auditer.
3. Source 3 : premier enrichissement xG/xGA contractuel, prioritaire pour 011-013 et 021 ; prix/add-on non gelé.

Les calendriers officiels servent au bootstrap et au contrôle, pas de licence implicite de republication intégrale. Les données de forme, classement, repos et congestion doivent être dérivées uniquement de reçus admissibles ; promus et derbies exigent des registres versionnés ; coachs exige une source effective-at encore inconnue.

## Réserve juridique et technique

Les conditions publiques The Odds API permettent les outils analytiques mais interdisent la revente/repackaging d’un flux brut autonome. Elles ne fixent aucune durée publique de rétention des payloads. Avant tout appel : confirmation écrite de rétention, licence `APPROVED`, secret hors reçus/logs, stockage append-only et replay byte-identique. `market.last_update` est un timestamp de fraîcheur provider, pas une preuve de timestamp natif bookmaker.

## Continuation exacte requise pour PR56

{continuation}

## Sources officielles principales

{sources}

## Verdicts

```text
ROBIN_DATA_HYPOTHESIS_CONVERGENCE_V1_COMPLETE
ROBIN_EVENT_AWARE_CAPTURE_PLAN_V1_READY_FOR_REVIEW
ROBIN_FIRST_RECEIPT_BACKED_CAPTURE_PILOT_SPECIFIED_NOT_AUTHORIZED
TOTALS_COVERAGE_TO_BE_PROVEN
MARKET_SYNCHRONIZATION_OBSERVABLE_DESIGN_ONLY
```
"""


def validate_bundle_objects(
    matrix: dict[str, Any],
    schedule: dict[str, Any],
    budgets: dict[str, Any],
    pilot: dict[str, Any],
) -> list[dict[str, Any]]:
    verify_call_group_contract(schedule)
    rows = matrix["experiments"]
    ids = [row["experiment_id"] for row in rows]
    checks = [
        {"check": "exactly_25_experiments", "passed": len(ids) == 25 and len(set(ids)) == 25},
        {"check": "categories_cover_25", "passed": sum(matrix["category_counts"].values()) == 25},
        {
            "check": "no_target_is_predictor",
            "passed": all(
                not (
                    {d["dataset"] for d in row["targets"]}
                    & {d["dataset"] for d in row["predictors"]}
                )
                for row in rows
            ),
        },
        {
            "check": "totals_gate_literal",
            "passed": pilot["markets"]["totals_status"] == "TOTALS_COVERAGE_TO_BE_PROVEN",
        },
        {"check": "no_activation", "passed": pilot["authorization"] == "NOT_AUTHORIZED"},
        {
            "check": "call_groups_recomputed_from_requirements",
            "passed": True,
        },
        {
            "check": "h2_staleness_15m",
            "passed": schedule["window_definitions"]["H2"]["maximum_staleness_minutes"] == 15,
        },
        {
            "check": "h1_is_target",
            "passed": schedule["window_definitions"]["H1"]["role"] == "TARGET",
        },
        {
            "check": "exp006_h2_is_target_bound",
            "passed": schedule["window_definitions"]["H2"]["protocol_role_bindings"]["TARGET"]
            == ["RDS-EXP-V1-006"],
        },
        {
            "check": "budget_scenarios_s0_s6",
            "passed": [x["scenario_id"] for x in budgets["scenarios"]]
            == [f"S{i}" for i in range(7)],
        },
        {"check": "pilot_at_least_five_fixtures", "passed": pilot["scope"]["fixture_count"] >= 5},
        {"check": "pilot_max_two_matchdays", "passed": len(pilot["scope"]["matchdays"]) <= 2},
        {
            "check": "no_protocol_executed",
            "passed": all(row["execution_status"] == "NOT_RUN" for row in rows),
        },
    ]
    failed = [check["check"] for check in checks if not check["passed"]]
    if failed:
        raise AssertionError(f"validation failures: {failed}")
    return checks


def build_convergence_report(
    matrix: dict[str, Any],
    schedule: dict[str, Any],
    budgets: dict[str, Any],
    pilot: dict[str, Any],
    blocked: dict[str, Any],
    assumptions: dict[str, Any],
    validations: list[dict[str, Any]],
    sealed_at: str,
) -> dict[str, Any]:
    """Build the compact, repository-facing convergence decision."""
    exact = schedule["exact_horizon_metrics"]
    s6 = next(item for item in budgets["scenarios"] if item["scenario_id"] == "S6")
    provider = assumptions["provider_facts"]
    return {
        "schema_version": "robin-data-hypothesis-convergence-v1",
        "sealed_at": sealed_at,
        "source_pack_manifest_sha256": CONVERGENCE_MANIFEST_SHA256,
        "reproducibility_scope": {
            "verdict": "DATA_HYPOTHESIS_CONVERGENCE_REPRODUCIBLE",
            "proves": "Deterministic transformation of pinned Git authorities and embedded dated facts into eight byte-identical repository reports.",
            "does_not_prove": "Immutable provenance of live official web-page bytes or future provider coverage.",
            "external_pack_boundary": {
                "status": "EXTERNAL_INPUT_NOT_REPRODUCIBLE_FROM_REPOSITORY",
                "manifest_sha256_reference": CONVERGENCE_MANIFEST_SHA256,
                "repository_evidence": "NOT_COMMITTED_BY_MISSION_RULE",
            },
        },
        "status": STATUS + ["DATA_HYPOTHESIS_CONVERGENCE_REPRODUCIBLE"],
        "git_authority": assumptions["git_authority"],
        "reproduced_metrics": {
            "experiments_mapped_exactly_once": len(matrix["experiments"]),
            "class_counts": matrix["category_counts"],
            "fixture_window_requirements": exact["calls_before_grouping"],
            "calls_after_grouping": exact["calls_after_grouping"],
            "calls_saved": exact["calls_saved"],
            "credits_saved": exact["credits_saved"],
            "protocols_preserved": len(exact["protocols_preserved"]),
            "currently_executable": blocked["summary"]["execution_ready_now"],
            "pilot": {
                "competition": pilot["scope"]["competition"],
                "fixtures_maximum": pilot["scope"]["fixture_count"],
                "canaries": pilot["scope"]["canary_fixture_count"],
                "http_calls": pilot["planned_calls"]["the_odds_api_total_http_calls"],
                "billable_calls": pilot["planned_calls"]["the_odds_api_chargeable_calls"],
                "credits_maximum": pilot["planned_credits"]["total_maximum"],
            },
            "scenario_s6": {
                "annual_credits": s6["annual_credits"],
                "monthly_capacity_with_reserve": s6["safety_reserve"]["monthly_capacity_required"],
            },
        },
        "temporal_role_contract": {
            "H24": {"role": "PREDICTOR", "maximum_staleness_minutes": 120},
            "H2": {
                "role": "PREDICTOR_OR_DISTINCT_TARGET_BY_PROTOCOL",
                "maximum_staleness_minutes": 15,
            },
            "H1": {"role": "TARGET_WHEN_REQUIRED"},
            "LABEL": "POST_MATCH_ONLY",
            "target_as_predictor_forbidden": True,
        },
        "market_synchronization": {
            "verdict": provider["market_synchronization_verdict"],
            "field": provider["market_sync_field"],
            "grain": provider["market_sync_grain"],
            "semantics": provider["market_sync_semantics"],
            "official_proof": provider["market_sync_official_proof"],
            "real_coverage": "TO_BE_PROVEN_DURING_PILOT",
        },
        "gates": {
            "totals": "TOTALS_COVERAGE_TO_BE_PROVEN",
            "exp009": "EXP009_PROTOCOL_SUCCESSOR_REQUIRED_BEFORE_EXECUTION",
            "raw_payload_retention": "RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED",
            "pilot_authorization": "NOT_AUTHORIZED",
        },
        "official_source_revalidation": {
            "accessed_at": ACCESS_DATE,
            "provenance_status": "LIVE_OFFICIAL_PAGES_REVALIDATED_NO_PAGE_BYTES_COMMITTED",
            "official_domain": provider["official_domain_only"],
            "forbidden_impostor_domain": provider["forbidden_impostor_domain"],
            "cost_formula": provider["bulk_odds_cost"],
            "quota_headers": ["x-requests-remaining", "x-requests-used", "x-requests-last"],
            "documented_markets": ["h2h", "spreads", "totals", "outrights"],
            "public_plans": {
                "starter_monthly_credits": 500,
                "20K_monthly_credits": 20000,
                "20K_monthly_usd": 30,
                "100K_monthly_credits": 100000,
                "100K_monthly_usd": 59,
                "5M_monthly_credits": 5000000,
                "5M_monthly_usd": 119,
                "15M_monthly_credits": 15000000,
                "15M_monthly_usd": 249,
            },
            "terms": SOURCE_URLS["odds_terms"]["url"],
            "impersonator_warning": SOURCE_URLS["odds_warning"]["url"],
        },
        "validation": validations,
        "external_effects": {
            "provider_calls": 0,
            "purchases": 0,
            "promotions": 0,
            "real_bets": 0,
            "production_connections": 0,
            "r2_operations": 0,
            "workflow_live_dispatches": 0,
        },
        "verdicts": [
            "ROBIN_DATA_HYPOTHESIS_CONVERGENCE_V1_INTEGRATED",
            "DATA_HYPOTHESIS_CONVERGENCE_REPRODUCIBLE",
            "ROBIN_EVENT_AWARE_CAPTURE_PLAN_V1_FROZEN",
            "ROBIN_FIRST_RECEIPT_BACKED_CAPTURE_PILOT_SPECIFIED_NOT_AUTHORIZED",
            "EXP009_PROTOCOL_SUCCESSOR_REQUIRED_BEFORE_EXECUTION",
            "TOTALS_COVERAGE_TO_BE_PROVEN",
            "RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED",
            "MARKET_SYNCHRONIZATION_OBSERVABLE_DESIGN_ONLY",
            "NO_PROVIDER_CALL",
            "NO_PURCHASE",
            "NO_PROMOTION",
            "NO_BET",
        ],
    }


def verify_git_authority(repo: Path) -> None:
    required = [
        BASELINE,
        PR56_HEAD,
        PR57_INITIAL_HEAD,
        PR57_FINAL_HEAD,
        PR57_MERGE_SHA,
        PR58_FINAL_HEAD,
        PR58_MERGE_SHA,
    ]
    for ref in required:
        run_git(repo, "cat-file", "-e", f"{ref}^{{commit}}")
    parents = run_git(repo, "show", "-s", "--format=%P", PR57_MERGE_SHA).strip().split()
    if parents != [BASELINE, PR57_FINAL_HEAD]:
        raise AssertionError(f"unexpected PR57 merge parents: {parents}")
    pr58_parents = run_git(repo, "show", "-s", "--format=%P", PR58_MERGE_SHA).strip().split()
    if pr58_parents != [PR57_MERGE_SHA, PR58_FINAL_HEAD]:
        raise AssertionError(f"unexpected PR58 merge parents: {pr58_parents}")


def build_documents(repo: Path, sealed_at: str) -> dict[str, str]:
    verify_git_authority(repo)
    protocols = git_json(
        repo,
        PR57_FINAL_HEAD,
        "reports/hypothesis-lab/first-25-experiment-protocols-v1.json",
    )
    # Read all four mandated PR57 authorities, even when only the protocol file is transformed row-wise.
    git_json(repo, PR57_FINAL_HEAD, "tools/hypothesis-lab/portfolio-strata-v1.json")
    git_json(repo, PR57_FINAL_HEAD, "reports/hypothesis-lab/negative-control-plan-v1.json")
    run_git(
        repo,
        "show",
        f"{PR57_FINAL_HEAD}:docs/hypothesis-lab/ROBIN-HYPOTHESIS-RESEARCH-PROTOCOL-V1.md",
    )

    matrix = build_matrix(protocols)
    schedule = build_event_schedule()
    budgets = build_budgets()
    pilot = build_pilot()
    blocked = build_blocked(matrix)
    roadmap = build_roadmap()
    assumptions = build_assumptions(protocols)
    validations = validate_bundle_objects(matrix, schedule, budgets, pilot)
    convergence = build_convergence_report(
        matrix,
        schedule,
        budgets,
        pilot,
        blocked,
        assumptions,
        validations,
        sealed_at,
    )
    return {
        "data-hypothesis-convergence-v1.json": json_text(convergence),
        "experiment-data-window-matrix-v1.json": json_text(matrix),
        "event-aware-capture-plan-v1.json": json_text(schedule),
        "credit-budget-scenarios-v1.json": json_text(budgets),
        "first-receipt-backed-capture-pilot-v1.json": json_text(pilot),
        "blocked-experiments-v1.json": json_text(blocked),
        "source-gap-roadmap-v1.json": json_text(roadmap),
        "official-source-assumptions-v1.json": json_text(assumptions),
    }


def write_documents(output: Path, documents: dict[str, str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        (output / name).write_text(text, encoding="utf-8", newline="\n")


def check_documents(output: Path, expected: dict[str, str]) -> None:
    failures: list[str] = []
    expected_names = set(expected)
    actual_names = {path.name for path in output.iterdir() if path.is_file()}
    missing_names = expected_names - actual_names
    if missing_names:
        failures.append(f"missing generated reports: {sorted(missing_names)}")
    for name, text in expected.items():
        path = output / name
        if not path.exists() or path.read_bytes() != text.encode("utf-8"):
            failures.append(name)
    if failures:
        raise SystemExit("CHECK FAILED: " + "; ".join(failures))
    print(
        f"CHECK PASSED: {len(expected_names)} repository reports byte-identical; "
        "25 experiments; no external calls"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        required=True,
        help="read-only analysis clone containing pinned Git objects",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="output directory, either external or reports/data-sourcing in the repository",
    )
    parser.add_argument(
        "--sealed-at", required=True, help="fixed ISO-8601 timestamp used for deterministic sealing"
    )
    parser.add_argument(
        "--check", action="store_true", help="recalculate in memory and compare byte-for-byte"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"not an analysis Git clone: {repo}")
    repository_output = repo / "reports" / "data-sourcing"
    if repo == output or (repo in output.parents and output != repository_output):
        raise SystemExit("repository output is restricted to reports/data-sourcing")
    parse_utc(args.sealed_at)
    documents = build_documents(repo, args.sealed_at)
    if args.check:
        check_documents(output, documents)
    else:
        write_documents(output, documents)
        print(f"WROTE {len(documents)} repository reports to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
