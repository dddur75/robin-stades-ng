"""Lossless, provenance-first normalization for historical deep data.

The normalizer deliberately keeps raw values (including ``None``) and adds
identity, lineage, version, and temporal metadata around them.  Historical
responses are never silently promoted to point-in-time evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from robin.historical_deep.contracts import TemporalClass

PROVIDER = "api-football"
NORMALIZER_VERSION = "historical-deep-normalizer-v1"
NORMALIZED_SCHEMA_VERSION = "historical-deep-normalized-v1"

SUPPORTED_FAMILIES = frozenset(
    {
        "fixtures",
        "teams",
        "venues",
        "referees",
        "events",
        "lineups",
        "lineup_players",
        "formations",
        "team_match_statistics",
        "player_match_statistics",
        "players",
        "player_season_statistics",
        "injuries",
        "suspensions",
        "sidelined",
        "coaches",
        "standings",
        "rounds",
    }
)

_TEMPORAL_CLASS_NAMES = {
    "fixtures": "FIXTURE_SPECIFIC_POST_HOC",
    "teams": "STATIC_PROFILE",
    "venues": "STATIC_PROFILE",
    "referees": "STATIC_PROFILE",
    "events": "EVENT_TIME_USABLE",
    "lineups": "POST_LINEUP_RECONSTRUCTED",
    "lineup_players": "POST_LINEUP_RECONSTRUCTED",
    "formations": "POST_LINEUP_RECONSTRUCTED",
    "team_match_statistics": "POST_MATCH_ONLY",
    "player_match_statistics": "POST_MATCH_ONLY",
    "players": "STATIC_PROFILE",
    "player_season_statistics": "SEASON_FINAL_AGGREGATE",
    "injuries": "HISTORICAL_INTERVAL_RECONSTRUCTED",
    "suspensions": "HISTORICAL_INTERVAL_RECONSTRUCTED",
    "sidelined": "HISTORICAL_INTERVAL_RECONSTRUCTED",
    "coaches": "STATIC_PROFILE",
    "standings": "SEASON_FINAL_AGGREGATE",
    "rounds": "STATIC_PROFILE",
}

_SUSPENSION_PATTERN = re.compile(
    r"\b(suspend(?:ed|u|ue|ido|ido)?|suspension|red card|yellow cards?)\b",
    flags=re.IGNORECASE,
)


class NormalizationError(ValueError):
    """A source record cannot satisfy the fail-closed normalization contract."""


@dataclass(frozen=True, slots=True)
class NormalizationContext:
    endpoint: str
    competition_id: int | None
    season: int | None
    task_id: str
    source_payload_hash: str
    observed_at: datetime
    ingested_at: datetime
    request_params: Mapping[str, object]
    fixture_id: int | None = None
    source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.ingested_at, "ingested_at")
        if self.source_available_at is not None:
            _require_aware(self.source_available_at, "source_available_at")
        if self.observed_at > self.ingested_at:
            raise NormalizationError("OBSERVATION_AFTER_INGESTION")


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NormalizationError(f"{name.upper()}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return _require_aware(value, "datetime").isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def canonical_json_bytes(value: object) -> bytes:
    """Canonical UTF-8 JSON used before gzip and for every content hash."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def classify_temporal(family: str) -> TemporalClass:
    normalized = family.strip().casefold()
    try:
        member_name = _TEMPORAL_CLASS_NAMES[normalized]
    except KeyError as exc:
        raise NormalizationError(f"UNSUPPORTED_FAMILY:{family}") from exc
    try:
        return TemporalClass[member_name]
    except KeyError as exc:
        raise NormalizationError(f"TEMPORAL_CLASS_UNAVAILABLE:{member_name}") from exc


def _temporal_value(value: TemporalClass) -> str:
    return str(getattr(value, "value", value))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _clean(value: object) -> object:
    """Copy JSON-like values without replacing nulls or inventing defaults."""

    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_clean(item) for item in value]
    if isinstance(value, datetime):
        return _require_aware(value, "source_datetime").isoformat()
    return value


def _response_items(payload: object) -> list[object]:
    if isinstance(payload, Mapping):
        response = payload.get("response")
        if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
            return list(response)
        return [payload]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return list(payload)
    return []


def _provider_id(value: object) -> int | str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)) and str(value).strip():
        return value
    return None


def _fixture_id(record: Mapping[str, Any], context: NormalizationContext) -> int | None:
    fixture = record.get("fixture")
    if isinstance(fixture, Mapping):
        value = fixture.get("id")
    else:
        value = fixture
    candidate = _provider_id(value)
    if isinstance(candidate, int):
        return candidate
    request_value = _provider_id(context.request_params.get("fixture"))
    if isinstance(request_value, int):
        return request_value
    return context.fixture_id


def _competition_id(
    record: Mapping[str, Any],
    context: NormalizationContext,
) -> int | None:
    league = _mapping(record.get("league"))
    candidate = _provider_id(league.get("id"))
    return candidate if isinstance(candidate, int) else context.competition_id


def _season(record: Mapping[str, Any], context: NormalizationContext) -> int | None:
    league = _mapping(record.get("league"))
    candidate = _provider_id(league.get("season"))
    return candidate if isinstance(candidate, int) else context.season


def _canonical_identity(
    entity_type: str,
    provider_id: int | str | None,
    *,
    derived_parts: Iterable[object] = (),
) -> tuple[str, str]:
    if provider_id is not None:
        return f"{PROVIDER}:{entity_type}:{provider_id}", "PROVIDER_ID_VERIFIED"
    parts = tuple(derived_parts)
    if not parts or all(part is None or part == "" for part in parts):
        raise NormalizationError(f"MISSING_IDENTITY:{entity_type}")
    fingerprint = canonical_sha256([entity_type, *parts])
    return f"{PROVIDER}:{entity_type}:derived:{fingerprint}", "DERIVED_NO_PROVIDER_ID"


def _iso(value: datetime | None) -> str | None:
    return _require_aware(value, "datetime").isoformat() if value is not None else None


def _kickoff(record: Mapping[str, Any]) -> datetime | None:
    fixture = _mapping(record.get("fixture"))
    value = fixture.get("date")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _base_row(
    *,
    family: str,
    entity_type: str,
    provider_id: int | str | None,
    context: NormalizationContext,
    source_record: object,
    data: Mapping[str, object],
    derived_identity_parts: Iterable[object] = (),
    fixture_id: int | None = None,
    team_id: int | None = None,
    player_id: int | None = None,
    competition_id: int | None = None,
    season: int | None = None,
    kickoff_at: datetime | None = None,
) -> dict[str, object]:
    canonical_id, identity_status = _canonical_identity(
        entity_type,
        provider_id,
        derived_parts=derived_identity_parts,
    )
    temporal_class = classify_temporal(family)
    available_at = context.source_available_at
    strict_prematch = bool(
        available_at is not None
        and kickoff_at is not None
        and available_at < kickoff_at
        and _temporal_value(temporal_class)
        in {"STATIC_PROFILE", "PRIOR_MATCH_USABLE", "PROSPECTIVE_POINT_IN_TIME"}
    )
    normalized: dict[str, object] = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "provider": PROVIDER,
        "family": family,
        "entity_type": entity_type,
        "provider_id": provider_id,
        "canonical_id": canonical_id,
        "identity_status": identity_status,
        "provider_competition_id": competition_id,
        "canonical_competition_id": (
            f"{PROVIDER}:competition:{competition_id}" if competition_id is not None else None
        ),
        "provider_fixture_id": fixture_id,
        "canonical_fixture_id": (
            f"{PROVIDER}:fixture:{fixture_id}" if fixture_id is not None else None
        ),
        "provider_team_id": team_id,
        "canonical_team_id": (f"{PROVIDER}:team:{team_id}" if team_id is not None else None),
        "provider_player_id": player_id,
        "canonical_player_id": (
            f"{PROVIDER}:player:{player_id}" if player_id is not None else None
        ),
        "season": season,
        "temporal_class": _temporal_value(temporal_class),
        "temporal_evidence_at": _iso(available_at),
        "target_kickoff_at": _iso(kickoff_at),
        "strict_prematch_eligible": strict_prematch,
        "temporal_gate": "READY_STRICT" if strict_prematch else "BLOCKED_BY_TEMPORALITY",
        "observed_at": _iso(context.observed_at),
        "ingested_at": _iso(context.ingested_at),
        "source_endpoint": context.endpoint,
        "source_request_params": _clean(context.request_params),
        "source_payload_hash": context.source_payload_hash,
        "source_record_hash": canonical_sha256(source_record),
        "task_id": context.task_id,
        "data": _clean(data),
        "provenance": {
            "provider": PROVIDER,
            "endpoint": context.endpoint,
            "task_id": context.task_id,
            "payload_sha256": context.source_payload_hash,
            "source_record_sha256": canonical_sha256(source_record),
            "schema_version": NORMALIZED_SCHEMA_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
        },
    }
    normalized["record_hash"] = canonical_sha256(normalized)
    return normalized


def detect_integrated_families(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Return only families with sampled, non-empty content in a fixture bundle."""

    found: set[str] = set()
    fixture = _mapping(record.get("fixture"))
    if fixture:
        found.add("fixtures")
        if fixture.get("venue") is not None:
            found.add("venues")
        if fixture.get("referee") not in (None, ""):
            found.add("referees")
    league = _mapping(record.get("league"))
    if league.get("round") not in (None, ""):
        found.add("rounds")
    teams = _mapping(record.get("teams"))
    if any(_mapping(teams.get(side)) for side in ("home", "away")):
        found.add("teams")
    if _sequence(record.get("events")):
        found.add("events")
    lineups = _sequence(record.get("lineups"))
    if lineups:
        found.update({"lineups", "formations"})
        if any(
            _sequence(_mapping(lineup).get("startXI"))
            or _sequence(_mapping(lineup).get("substitutes"))
            for lineup in lineups
        ):
            found.add("lineup_players")
    if _sequence(record.get("statistics")):
        found.add("team_match_statistics")
    if _sequence(record.get("players")):
        found.add("player_match_statistics")
    return tuple(sorted(found))


def _fixture_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        fixture = _mapping(record.get("fixture"))
        fixture_id = _provider_id(fixture.get("id"))
        if not isinstance(fixture_id, int):
            raise NormalizationError("FIXTURE_PROVIDER_ID_REQUIRED")
        output.append(
            _base_row(
                family="fixtures",
                entity_type="fixture",
                provider_id=fixture_id,
                context=context,
                source_record=record,
                data=record,
                fixture_id=fixture_id,
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=_kickoff(record),
            )
        )
    return output


def _team_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        fixture_id = _fixture_id(record, context)
        teams = _mapping(record.get("teams"))
        candidates: list[tuple[str | None, Mapping[str, Any]]] = []
        if teams:
            candidates.extend((side, _mapping(teams.get(side))) for side in ("home", "away"))
        elif _mapping(record.get("team")):
            candidates.append((None, _mapping(record.get("team"))))
        for side, team in candidates:
            if not team:
                continue
            team_id = _provider_id(team.get("id"))
            output.append(
                _base_row(
                    family="teams",
                    entity_type="team",
                    provider_id=team_id,
                    context=context,
                    source_record=team,
                    data={"side": side, **dict(team)},
                    derived_identity_parts=(team.get("name"), team.get("code")),
                    fixture_id=fixture_id,
                    team_id=team_id if isinstance(team_id, int) else None,
                    competition_id=_competition_id(record, context),
                    season=_season(record, context),
                    kickoff_at=_kickoff(record),
                )
            )
    return output


def _venue_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        fixture = _mapping(record.get("fixture"))
        venue = _mapping(fixture.get("venue")) or _mapping(record.get("venue"))
        if not venue:
            continue
        venue_id = _provider_id(venue.get("id"))
        output.append(
            _base_row(
                family="venues",
                entity_type="venue",
                provider_id=venue_id,
                context=context,
                source_record=venue,
                data=venue,
                derived_identity_parts=(venue.get("name"), venue.get("city")),
                fixture_id=_fixture_id(record, context),
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=_kickoff(record),
            )
        )
    return output


def _referee_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        referee = _mapping(record.get("fixture")).get("referee")
        if not isinstance(referee, str) or not referee.strip():
            continue
        normalized_name = " ".join(
            "".join(
                char
                for char in unicodedata.normalize("NFKD", referee)
                if not unicodedata.combining(char)
            )
            .casefold()
            .split()
        )
        output.append(
            _base_row(
                family="referees",
                entity_type="referee",
                provider_id=None,
                context=context,
                source_record={"name": referee},
                data={"name": referee},
                derived_identity_parts=(normalized_name,),
                fixture_id=_fixture_id(record, context),
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=_kickoff(record),
            )
        )
    return output


def _event_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        fixture_id = _fixture_id(record, context)
        nested = _sequence(record.get("events"))
        direct_endpoint = context.endpoint.strip("/") == "fixtures/events"
        events = nested if nested else (record,) if direct_endpoint else ()
        for position, event_value in enumerate(events):
            event = _mapping(event_value)
            if not event:
                continue
            team_id = _provider_id(_mapping(event.get("team")).get("id"))
            player_id = _provider_id(_mapping(event.get("player")).get("id"))
            output.append(
                _base_row(
                    family="events",
                    entity_type="fixture_event",
                    provider_id=_provider_id(event.get("id")),
                    context=context,
                    source_record=event,
                    data=event,
                    derived_identity_parts=(
                        fixture_id,
                        position,
                        event.get("type"),
                        event.get("detail"),
                        _mapping(event.get("time")).get("elapsed"),
                        player_id,
                    ),
                    fixture_id=fixture_id,
                    team_id=team_id if isinstance(team_id, int) else None,
                    player_id=player_id if isinstance(player_id, int) else None,
                    competition_id=_competition_id(record, context),
                    season=_season(record, context),
                    kickoff_at=_kickoff(record),
                )
            )
    return output


def _lineup_entries(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], int | None, datetime | None]]:
    output: list[tuple[Mapping[str, Any], Mapping[str, Any], int | None, datetime | None]] = []
    for record_value in records:
        record = _mapping(record_value)
        nested = _sequence(record.get("lineups"))
        lineups = nested if nested else (record,)
        for lineup_value in lineups:
            lineup = _mapping(lineup_value)
            if lineup and _mapping(lineup.get("team")):
                output.append((record, lineup, _fixture_id(record, context), _kickoff(record)))
    return output


def _lineup_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record, lineup, fixture_id, kickoff in _lineup_entries(records, context):
        team = _mapping(lineup.get("team"))
        team_id = _provider_id(team.get("id"))
        output.append(
            _base_row(
                family="lineups",
                entity_type="lineup",
                provider_id=None,
                context=context,
                source_record=lineup,
                data=lineup,
                derived_identity_parts=(fixture_id, team_id),
                fixture_id=fixture_id,
                team_id=team_id if isinstance(team_id, int) else None,
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=kickoff,
            )
        )
    return output


def _lineup_player_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record, lineup, fixture_id, kickoff in _lineup_entries(records, context):
        team_id = _provider_id(_mapping(lineup.get("team")).get("id"))
        for role, key in (("STARTING_XI", "startXI"), ("SUBSTITUTE", "substitutes")):
            for position, entry_value in enumerate(_sequence(lineup.get(key))):
                entry = _mapping(entry_value)
                player = _mapping(entry.get("player"))
                player_id = _provider_id(player.get("id"))
                output.append(
                    _base_row(
                        family="lineup_players",
                        entity_type="lineup_player",
                        provider_id=None,
                        context=context,
                        source_record=entry,
                        data={"role": role, "position": position, **dict(entry)},
                        derived_identity_parts=(fixture_id, team_id, player_id, role),
                        fixture_id=fixture_id,
                        team_id=team_id if isinstance(team_id, int) else None,
                        player_id=player_id if isinstance(player_id, int) else None,
                        competition_id=_competition_id(record, context),
                        season=_season(record, context),
                        kickoff_at=kickoff,
                    )
                )
    return output


def _formation_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record, lineup, fixture_id, kickoff in _lineup_entries(records, context):
        team_id = _provider_id(_mapping(lineup.get("team")).get("id"))
        formation = lineup.get("formation")
        if formation in (None, ""):
            continue
        output.append(
            _base_row(
                family="formations",
                entity_type="formation",
                provider_id=None,
                context=context,
                source_record={"formation": formation},
                data={"formation": formation},
                derived_identity_parts=(fixture_id, team_id, formation),
                fixture_id=fixture_id,
                team_id=team_id if isinstance(team_id, int) else None,
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=kickoff,
            )
        )
    return output


def _team_statistic_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        fixture_id = _fixture_id(record, context)
        nested = _sequence(record.get("statistics"))
        buckets = nested if nested else (record,)
        for bucket_value in buckets:
            bucket = _mapping(bucket_value)
            team_id = _provider_id(_mapping(bucket.get("team")).get("id"))
            statistics = _sequence(bucket.get("statistics"))
            for position, statistic_value in enumerate(statistics):
                statistic = _mapping(statistic_value)
                output.append(
                    _base_row(
                        family="team_match_statistics",
                        entity_type="team_match_statistic",
                        provider_id=None,
                        context=context,
                        source_record=statistic,
                        data=statistic,
                        derived_identity_parts=(
                            fixture_id,
                            team_id,
                            statistic.get("type"),
                            position,
                        ),
                        fixture_id=fixture_id,
                        team_id=team_id if isinstance(team_id, int) else None,
                        competition_id=_competition_id(record, context),
                        season=_season(record, context),
                        kickoff_at=_kickoff(record),
                    )
                )
    return output


def _player_bucket_entries(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], int | None]]:
    output: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], int | None]] = []
    for record_value in records:
        record = _mapping(record_value)
        nested = _sequence(record.get("players"))
        buckets = nested if nested else (record,)
        for bucket_value in buckets:
            bucket = _mapping(bucket_value)
            team = _mapping(bucket.get("team"))
            players = _sequence(bucket.get("players"))
            for entry_value in players:
                entry = _mapping(entry_value)
                if _mapping(entry.get("player")):
                    output.append((record, team, entry, _fixture_id(record, context)))
    return output


def _player_match_statistic_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record, team, entry, fixture_id in _player_bucket_entries(records, context):
        player = _mapping(entry.get("player"))
        player_id = _provider_id(player.get("id"))
        team_id = _provider_id(team.get("id"))
        statistics = _sequence(entry.get("statistics"))
        if not statistics:
            statistics = ({},)
        for position, statistic_value in enumerate(statistics):
            statistic = _mapping(statistic_value)
            output.append(
                _base_row(
                    family="player_match_statistics",
                    entity_type="player_match_statistic",
                    provider_id=None,
                    context=context,
                    source_record=entry,
                    data={"player": dict(player), "statistics": dict(statistic)},
                    derived_identity_parts=(fixture_id, team_id, player_id, position),
                    fixture_id=fixture_id,
                    team_id=team_id if isinstance(team_id, int) else None,
                    player_id=player_id if isinstance(player_id, int) else None,
                    competition_id=_competition_id(record, context),
                    season=_season(record, context),
                    kickoff_at=_kickoff(record),
                )
            )
    return output


def _player_profile_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        player = _mapping(record.get("player"))
        if not player:
            continue
        player_id = _provider_id(player.get("id"))
        output.append(
            _base_row(
                family="players",
                entity_type="player",
                provider_id=player_id,
                context=context,
                source_record=player,
                data=player,
                derived_identity_parts=(
                    player.get("name"),
                    _mapping(player.get("birth")).get("date"),
                ),
                player_id=player_id if isinstance(player_id, int) else None,
                competition_id=_competition_id(record, context),
                season=_season(record, context),
            )
        )
    return output


def _player_season_statistic_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        player = _mapping(record.get("player"))
        player_id = _provider_id(player.get("id"))
        for position, statistic_value in enumerate(_sequence(record.get("statistics"))):
            statistic = _mapping(statistic_value)
            team_id = _provider_id(_mapping(statistic.get("team")).get("id"))
            league = _mapping(statistic.get("league"))
            competition_id = _provider_id(league.get("id"))
            season = _provider_id(league.get("season"))
            output.append(
                _base_row(
                    family="player_season_statistics",
                    entity_type="player_season_statistic",
                    provider_id=None,
                    context=context,
                    source_record=statistic,
                    data=statistic,
                    derived_identity_parts=(
                        player_id,
                        team_id,
                        competition_id,
                        season,
                        position,
                    ),
                    team_id=team_id if isinstance(team_id, int) else None,
                    player_id=player_id if isinstance(player_id, int) else None,
                    competition_id=(
                        competition_id
                        if isinstance(competition_id, int)
                        else context.competition_id
                    ),
                    season=season if isinstance(season, int) else context.season,
                )
            )
    return output


def _injury_like_rows(
    family: str,
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    entity_types = {
        "injuries": "injury",
        "suspensions": "suspension",
        "sidelined": "sidelined_period",
    }
    output: list[dict[str, object]] = []
    for position, record_value in enumerate(records):
        record = _mapping(record_value)
        if not record:
            continue
        description = " ".join(
            str(record.get(key) or "") for key in ("type", "reason", "description")
        )
        is_suspension = bool(_SUSPENSION_PATTERN.search(description))
        if family == "injuries" and is_suspension:
            continue
        if family == "suspensions" and not is_suspension:
            continue
        player_id = _provider_id(_mapping(record.get("player")).get("id"))
        team_id = _provider_id(_mapping(record.get("team")).get("id"))
        fixture_id = _fixture_id(record, context)
        output.append(
            _base_row(
                family=family,
                entity_type=entity_types[family],
                provider_id=_provider_id(record.get("id")),
                context=context,
                source_record=record,
                data=record,
                derived_identity_parts=(
                    player_id,
                    team_id,
                    fixture_id,
                    record.get("date"),
                    record.get("type"),
                    record.get("reason"),
                    position,
                ),
                fixture_id=fixture_id,
                team_id=team_id if isinstance(team_id, int) else None,
                player_id=player_id if isinstance(player_id, int) else None,
                competition_id=_competition_id(record, context),
                season=_season(record, context),
                kickoff_at=_kickoff(record),
            )
        )
    return output


def _coach_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        if not record:
            continue
        coach_id = _provider_id(record.get("id"))
        team_id = _provider_id(_mapping(record.get("team")).get("id"))
        output.append(
            _base_row(
                family="coaches",
                entity_type="coach",
                provider_id=coach_id,
                context=context,
                source_record=record,
                data=record,
                derived_identity_parts=(
                    record.get("name"),
                    _mapping(record.get("birth")).get("date"),
                ),
                team_id=team_id if isinstance(team_id, int) else None,
                competition_id=context.competition_id,
                season=context.season,
            )
        )
    return output


def _standing_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for record_value in records:
        record = _mapping(record_value)
        league = _mapping(record.get("league"))
        competition_id = _provider_id(league.get("id"))
        season = _provider_id(league.get("season"))
        groups = _sequence(league.get("standings"))
        if not groups and record.get("rank") is not None:
            groups = ((record,),)
        for group_position, group_value in enumerate(groups):
            for row_position, row_value in enumerate(_sequence(group_value)):
                row = _mapping(row_value)
                team_id = _provider_id(_mapping(row.get("team")).get("id"))
                output.append(
                    _base_row(
                        family="standings",
                        entity_type="standing",
                        provider_id=None,
                        context=context,
                        source_record=row,
                        data=row,
                        derived_identity_parts=(
                            competition_id,
                            season,
                            team_id,
                            group_position,
                            row_position,
                        ),
                        team_id=team_id if isinstance(team_id, int) else None,
                        competition_id=(
                            competition_id
                            if isinstance(competition_id, int)
                            else context.competition_id
                        ),
                        season=season if isinstance(season, int) else context.season,
                    )
                )
    return output


def _round_rows(
    records: Sequence[object],
    context: NormalizationContext,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for position, value in enumerate(records):
        round_name: object
        if isinstance(value, str):
            round_name = value
            source: object = value
        else:
            record = _mapping(value)
            round_name = _mapping(record.get("league")).get("round") or record.get("round")
            source = record
        if not isinstance(round_name, str) or not round_name:
            continue
        output.append(
            _base_row(
                family="rounds",
                entity_type="round",
                provider_id=None,
                context=context,
                source_record=source,
                data={"name": round_name, "position": position},
                derived_identity_parts=(
                    context.competition_id,
                    context.season,
                    round_name,
                ),
                competition_id=context.competition_id,
                season=context.season,
            )
        )
    return output


def normalize_family(
    family: str,
    payload: object,
    *,
    endpoint: str,
    competition_id: int | None,
    season: int | None,
    task_id: str,
    source_payload_hash: str | None = None,
    request_params: Mapping[str, object] | None = None,
    observed_at: datetime | None = None,
    ingested_at: datetime | None = None,
    fixture_id: int | None = None,
    source_available_at: datetime | None = None,
) -> list[dict[str, object]]:
    """Normalize one family without coercing absent source values."""

    normalized_family = family.strip().casefold()
    if normalized_family not in SUPPORTED_FAMILIES:
        raise NormalizationError(f"UNSUPPORTED_FAMILY:{family}")
    now = datetime.now(UTC)
    context = NormalizationContext(
        endpoint="/" + endpoint.strip("/"),
        competition_id=competition_id,
        season=season,
        task_id=task_id,
        source_payload_hash=source_payload_hash or canonical_sha256(payload),
        observed_at=observed_at or now,
        ingested_at=ingested_at or now,
        request_params=dict(request_params or {}),
        fixture_id=fixture_id,
        source_available_at=source_available_at,
    )
    records = _response_items(payload)
    dispatch = {
        "fixtures": _fixture_rows,
        "teams": _team_rows,
        "venues": _venue_rows,
        "referees": _referee_rows,
        "events": _event_rows,
        "lineups": _lineup_rows,
        "lineup_players": _lineup_player_rows,
        "formations": _formation_rows,
        "team_match_statistics": _team_statistic_rows,
        "player_match_statistics": _player_match_statistic_rows,
        "players": _player_profile_rows,
        "player_season_statistics": _player_season_statistic_rows,
        "injuries": lambda values, ctx: _injury_like_rows("injuries", values, ctx),
        "suspensions": lambda values, ctx: _injury_like_rows("suspensions", values, ctx),
        "sidelined": lambda values, ctx: _injury_like_rows("sidelined", values, ctx),
        "coaches": _coach_rows,
        "standings": _standing_rows,
        "rounds": _round_rows,
    }
    return dispatch[normalized_family](records, context)


def families_for_endpoint(endpoint: str, payload: object) -> tuple[str, ...]:
    normalized = endpoint.strip("/").casefold()
    direct = {
        "fixtures/events": ("events",),
        "fixtures/lineups": ("lineups", "lineup_players", "formations"),
        "fixtures/statistics": ("team_match_statistics",),
        "fixtures/players": ("player_match_statistics",),
        "players": ("players", "player_season_statistics"),
        "injuries": ("injuries", "suspensions"),
        "sidelined": ("sidelined",),
        "coachs": ("coaches",),
        "coaches": ("coaches",),
        "standings": ("standings",),
        "fixtures/rounds": ("rounds",),
        "rounds": ("rounds",),
    }
    if normalized in direct:
        return direct[normalized]
    if normalized == "fixtures":
        families: set[str] = set()
        for item in _response_items(payload):
            families.update(detect_integrated_families(_mapping(item)))
        return tuple(sorted(families or {"fixtures"}))
    if normalized == "teams":
        return ("teams", "venues")
    return ()


def normalize_payload(
    payload: object,
    *,
    endpoint: str,
    competition_id: int | None,
    season: int | None,
    task_id: str,
    families: Iterable[str] | None = None,
    source_payload_hash: str | None = None,
    request_params: Mapping[str, object] | None = None,
    observed_at: datetime | None = None,
    ingested_at: datetime | None = None,
    fixture_id: int | None = None,
    source_available_at: datetime | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Normalize every requested or actually observed family in a payload."""

    selected = tuple(families or families_for_endpoint(endpoint, payload))
    if not selected:
        raise NormalizationError(f"ENDPOINT_WITHOUT_NORMALIZER:{endpoint}")
    payload_hash = source_payload_hash or canonical_sha256(payload)
    return {
        family: normalize_family(
            family,
            payload,
            endpoint=endpoint,
            competition_id=competition_id,
            season=season,
            task_id=task_id,
            source_payload_hash=payload_hash,
            request_params=request_params,
            observed_at=observed_at,
            ingested_at=ingested_at,
            fixture_id=fixture_id,
            source_available_at=source_available_at,
        )
        for family in selected
    }


normalize_response = normalize_payload

__all__ = [
    "NORMALIZED_SCHEMA_VERSION",
    "NORMALIZER_VERSION",
    "NormalizationContext",
    "NormalizationError",
    "SUPPORTED_FAMILIES",
    "TemporalClass",
    "canonical_json_bytes",
    "canonical_sha256",
    "classify_temporal",
    "detect_integrated_families",
    "families_for_endpoint",
    "normalize_family",
    "normalize_payload",
    "normalize_response",
]
