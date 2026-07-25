"""Canonicalisation générique des fixtures historiques."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CanonicalScope(StrEnum):
    REGULAR_SEASON_CANONICAL = "REGULAR_SEASON_CANONICAL"
    RESCHEDULED_VERSION = "RESCHEDULED_VERSION"
    DUPLICATE_FIXTURE = "DUPLICATE_FIXTURE"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    PLAYOFF = "PLAYOFF"
    RELEGATION_PLAYOFF = "RELEGATION_PLAYOFF"
    NON_REGULAR_PHASE = "NON_REGULAR_PHASE"
    INVALID_IDENTITY = "INVALID_IDENTITY"
    UNKNOWN_SCOPE = "UNKNOWN_SCOPE"


@dataclass(frozen=True)
class CompetitionFormat:
    """Format attendu d'une phase, sans constante propre à un championnat."""

    team_count: int
    legs: int = 2
    phase_prefix: str = "Regular Season"

    @property
    def expected_fixtures(self) -> int:
        return self.team_count * (self.team_count - 1) * self.legs // 2


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _business_identity(
    home_id: object,
    away_id: object,
    round_name: str,
) -> tuple[str, str, str]:
    return (_text(home_id), _text(away_id), round_name.casefold())


def _base_scope(round_name: str, status: str, phase_prefix: str) -> CanonicalScope:
    if status in {"CANC", "PST"}:
        return CanonicalScope.CANCELLED if status == "CANC" else CanonicalScope.RESCHEDULED_VERSION
    if status in {"ABD", "INT", "SUSP"}:
        return CanonicalScope.ABANDONED
    folded = round_name.casefold()
    if folded.startswith(phase_prefix.casefold()):
        return CanonicalScope.REGULAR_SEASON_CANONICAL
    if "relegation" in folded or folded in {"semi-finals", "final"}:
        return CanonicalScope.RELEGATION_PLAYOFF
    if any(token in folded for token in ("playoff", "play-off", "quarter-final")):
        return CanonicalScope.PLAYOFF
    if round_name:
        return CanonicalScope.NON_REGULAR_PHASE
    return CanonicalScope.UNKNOWN_SCOPE


def canonicalize_fixtures(
    records: Iterable[Mapping[str, Any]],
    *,
    competition_id: int,
    season: int,
    competition_format: CompetitionFormat,
) -> list[dict[str, object]]:
    """Classer chaque observation et conserver les exclusions explicites."""

    rows: list[dict[str, object]] = []
    identities: dict[tuple[str, str, str], int] = {}
    provider_ids: set[str] = set()
    for source in records:
        payload = _mapping(source.get("payload", source))
        fixture = _mapping(payload.get("fixture"))
        league = _mapping(payload.get("league"))
        teams = _mapping(payload.get("teams"))
        home = _mapping(teams.get("home"))
        away = _mapping(teams.get("away"))
        provider_id = fixture.get("id")
        round_name = _text(league.get("round"))
        status = _text(_mapping(fixture.get("status")).get("short")).upper()
        identity = _business_identity(home.get("id"), away.get("id"), round_name)
        scope = _base_scope(round_name, status, competition_format.phase_prefix)
        invalid_identity = (
            not isinstance(provider_id, int)
            or not isinstance(home.get("id"), int)
            or not isinstance(away.get("id"), int)
            or home.get("id") == away.get("id")
        )
        provider_key = _text(provider_id)
        if invalid_identity:
            scope = CanonicalScope.INVALID_IDENTITY
        elif provider_key in provider_ids:
            scope = CanonicalScope.DUPLICATE_FIXTURE
        elif identity in identities:
            previous_index = identities[identity]
            previous = rows[previous_index]
            if previous["kickoff"] != fixture.get("date"):
                scope = CanonicalScope.RESCHEDULED_VERSION
            else:
                scope = CanonicalScope.DUPLICATE_FIXTURE
        provider_ids.add(provider_key)
        identities.setdefault(identity, len(rows))
        internal_id = source.get("internal_id")
        if internal_id is None:
            raw = f"api-football:{competition_id}:{season}:{provider_key}"
            internal_id = hashlib.sha256(raw.encode()).hexdigest()[:32]
        exclusion_reason = (
            None
            if scope == CanonicalScope.REGULAR_SEASON_CANONICAL
            else scope.value
        )
        rows.append(
            {
                "provider_fixture_id": provider_id,
                "internal_fixture_id": internal_id,
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_team_id": home.get("id"),
                "away_team_id": away.get("id"),
                "round": round_name,
                "stage": round_name.split(" - ", 1)[0] if round_name else None,
                "status": status,
                "kickoff": fixture.get("date"),
                "last_update": source.get("observed_at"),
                "competition_id": competition_id,
                "season": season,
                "canonical_scope": scope.value,
                "exclusion_reason": exclusion_reason,
            }
        )
    return rows


def validate_canonical_cardinality(
    rows: Iterable[Mapping[str, object]],
    competition_format: CompetitionFormat,
) -> dict[str, object]:
    items = list(rows)
    canonical = [
        row
        for row in items
        if row.get("canonical_scope") == CanonicalScope.REGULAR_SEASON_CANONICAL
    ]
    team_ids = {
        int(team_id)
        for row in canonical
        for team_id in (row.get("home_team_id"), row.get("away_team_id"))
        if isinstance(team_id, int)
    }
    expected = competition_format.expected_fixtures
    status = (
        "PASSED"
        if len(canonical) == expected and len(team_ids) == competition_format.team_count
        else "FAILED"
    )
    return {
        "status": status,
        "received_fixtures": len(items),
        "canonical_fixtures": len(canonical),
        "expected_fixtures": expected,
        "received_teams": len(
            {
                team_id
                for row in items
                for team_id in (row.get("home_team_id"), row.get("away_team_id"))
                if isinstance(team_id, int)
            }
        ),
        "canonical_teams": len(team_ids),
        "expected_teams": competition_format.team_count,
        "classifications": dict(
            sorted(Counter(str(row.get("canonical_scope")) for row in items).items())
        ),
    }


def canonical_dataset_hash(rows: Iterable[Mapping[str, object]]) -> str:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()
