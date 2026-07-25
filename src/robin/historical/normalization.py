"""Normalisation minimale et traçable des réponses API-Football."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from robin.historical.contracts import AvailabilityStatus


def internal_id(entity_type: str, provider_id: object) -> str:
    return str(uuid5(NAMESPACE_URL, f"robin:api-football:{entity_type}:{provider_id}"))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _provider_id(record: Mapping[str, Any], endpoint: str) -> object | None:
    fixture = _mapping(record.get("fixture"))
    team = _mapping(record.get("team"))
    player = _mapping(record.get("player"))
    league = _mapping(record.get("league"))
    if endpoint.startswith("fixtures"):
        return fixture.get("id") or record.get("id")
    if endpoint.startswith("players"):
        return player.get("id") or record.get("id")
    if endpoint.startswith("teams"):
        return team.get("id") or record.get("id")
    if endpoint == "leagues":
        return league.get("id") or record.get("id")
    return record.get("id")


def entity_type_for_endpoint(endpoint: str) -> str:
    return {
        "leagues": "competitions",
        "teams": "teams",
        "players": "players",
        "players/squads": "squads",
        "fixtures": "fixtures",
        "fixtures/events": "fixture_events",
        "fixtures/statistics": "fixture_team_statistics",
        "fixtures/players": "fixture_player_statistics",
        "fixtures/lineups": "lineups",
        "standings": "standings_snapshots",
        "injuries": "injuries",
        "coachs": "coaches",
        "transfers": "transfers",
    }.get(endpoint.strip("/"), endpoint.strip("/").replace("/", "_"))


def availability_for_endpoint(endpoint: str) -> AvailabilityStatus:
    normalized = endpoint.strip("/")
    if normalized in {
        "fixtures/events",
        "fixtures/statistics",
        "fixtures/players",
        "fixtures/lineups",
    }:
        return AvailabilityStatus.POST_MATCH_ONLY
    if normalized in {"injuries", "transfers"}:
        return AvailabilityStatus.HISTORICAL_NON_POINT_IN_TIME
    return AvailabilityStatus.POINT_IN_TIME_SAFE


def normalize_records(
    endpoint: str,
    records: Iterable[Mapping[str, Any]],
    *,
    competition_id: int | None,
    season: int | None,
    ingestion_run_id: str,
    raw_payload_hash: str | None,
    request_params: Mapping[str, object] | None = None,
    observed_at: datetime | None = None,
) -> list[dict[str, object]]:
    """Conserver le payload utile sans convertir les absences en zéros."""

    normalized_endpoint = endpoint.strip("/")
    entity_type = entity_type_for_endpoint(normalized_endpoint)
    availability = availability_for_endpoint(normalized_endpoint)
    timestamp = observed_at or datetime.now(UTC)
    output: list[dict[str, object]] = []
    parameters = request_params or {}
    requested_fixture_id = parameters.get("fixture")
    requested_team_id = parameters.get("team")
    for position, record in enumerate(records):
        provider_id = _provider_id(record, normalized_endpoint)
        canonical = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        fallback_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        stable_provider_id = provider_id if provider_id is not None else fallback_id
        output.append(
            {
                "internal_id": internal_id(entity_type, stable_provider_id),
                "provider": "api-football",
                "provider_id": provider_id,
                "provider_fixture_id": (
                    requested_fixture_id
                    if isinstance(requested_fixture_id, int)
                    else None
                ),
                "provider_team_id": (
                    requested_team_id if isinstance(requested_team_id, int) else None
                ),
                "entity_type": entity_type,
                "competition_id": competition_id,
                "season": season,
                "position_in_payload": position,
                "observed_at": timestamp.isoformat(),
                "availability_status": availability.value,
                "quality_status": "OBSERVED",
                "ingestion_run_id": ingestion_run_id,
                "raw_payload_hash": raw_payload_hash,
                "payload": dict(record),
            }
        )
    return output
