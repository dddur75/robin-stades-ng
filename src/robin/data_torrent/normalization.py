"""Deterministic official-fixture and odds normalization with explicit rejects."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from robin.capture.bootstrap_contracts import canonical_team_name_v1
from robin.capture.official_schedule_sources import OfficialScheduleEvidence
from robin.data_torrent.contracts import (
    RawResponseEnvelope,
    canonical_json_bytes,
    strict_json_loads,
    utc_text,
)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("DATETIME_MISSING")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("DATETIME_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("DATETIME_TIMEZONE_MISSING")
    return parsed.astimezone(UTC)


def _text(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(code)
    return value.strip()


def _record_id(*parts: object) -> str:
    return hashlib.sha256(canonical_json_bytes(list(parts))).hexdigest()


def load_team_aliases(path: Path) -> dict[str, str]:
    """Load the reviewed exact alias table without YAML coercion or duplicate loss."""

    raw = path.read_bytes()
    if not raw or len(raw) > 65_536:
        raise ValueError("DATA_TORRENT_TEAM_ALIASES_INVALID")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("DATA_TORRENT_TEAM_ALIASES_INVALID") from None
    aliases: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            item = strict_json_loads(
                "{" + stripped + "}",
                duplicate_code="DATA_TORRENT_TEAM_ALIASES_DUPLICATE",
                non_finite_code="DATA_TORRENT_TEAM_ALIASES_INVALID",
            )
        except (ValueError, TypeError) as error:
            if str(error) == "DATA_TORRENT_TEAM_ALIASES_DUPLICATE":
                raise ValueError("DATA_TORRENT_TEAM_ALIASES_DUPLICATE") from None
            raise ValueError("DATA_TORRENT_TEAM_ALIASES_INVALID") from None
        if (
            not isinstance(item, dict)
            or len(item) != 1
            or not all(isinstance(value, str) for value in item.values())
        ):
            raise ValueError("DATA_TORRENT_TEAM_ALIASES_INVALID")
        source, target = next(iter(item.items()))
        canonical_source = canonical_team_name_v1(source)
        canonical_target = canonical_team_name_v1(cast(str, target))
        if canonical_source in aliases:
            raise ValueError("DATA_TORRENT_TEAM_ALIASES_DUPLICATE")
        aliases[canonical_source] = canonical_target
    if not aliases:
        raise ValueError("DATA_TORRENT_TEAM_ALIASES_INVALID")
    if any(target in aliases and target != source for source, target in aliases.items()):
        raise ValueError("DATA_TORRENT_TEAM_ALIASES_CHAIN_FORBIDDEN")
    return dict(sorted(aliases.items()))


def _team_key(value: str, aliases: Mapping[str, str]) -> str:
    canonical = canonical_team_name_v1(value)
    return aliases.get(canonical, canonical)


def team_alias_registry_document(aliases: Mapping[str, str]) -> dict[str, Any]:
    mapping = dict(sorted(aliases.items()))
    return {
        "schema_version": "robin-data-torrent-team-alias-registry-v1",
        "normalization": "NFKC_COLLAPSED_WHITESPACE_CASEFOLD_V1",
        "resolution": "ONE_HOP_EXACT_ONLY",
        "mapping_sha256": hashlib.sha256(canonical_json_bytes(mapping)).hexdigest(),
        "aliases": [
            {"source_match_key": source, "target_match_key": target}
            for source, target in mapping.items()
        ],
    }


@dataclass(frozen=True, slots=True)
class NormalizedBatch:
    records: tuple[dict[str, Any], ...]
    rejects: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]
    raw_events_observed: int
    raw_events_accounted: int
    silent_drops: int
    logical_duplicates: int
    temporal_leakage: int
    canonical_dataset_sha256: str
    canonical_dataset_bytes: bytes
    rejects_bytes: bytes


def _official_records(
    evidences: tuple[OfficialScheduleEvidence, ...],
    *,
    response_by_lineage: dict[tuple[str, str, str], RawResponseEnvelope],
    run_identity: str,
    claim_identity: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for evidence in evidences:
        for fixture_index, fixture in enumerate(evidence.fixtures):
            provenance_values = (
                fixture.source_authority,
                fixture.source_content_sha256,
                fixture.source_pointer,
                fixture.source_record_ordinal,
            )
            if any(value is not None for value in provenance_values) and any(
                value is None for value in provenance_values
            ):
                raise ValueError("DATA_TORRENT_OFFICIAL_FIXTURE_PROVENANCE_INVALID")
            source_authority = fixture.source_authority or evidence.source_authority
            source_sha256 = fixture.source_content_sha256 or evidence.source_content_sha256
            source = response_by_lineage.get((evidence.sport_key, source_authority, source_sha256))
            if source is None:
                raise ValueError("DATA_TORRENT_OFFICIAL_FIXTURE_RAW_RESPONSE_MISSING")
            source_pointer = (
                fixture.source_pointer
                if fixture.source_pointer is not None
                else f"adapter_projection.fixtures[{fixture_index}]"
            )
            source_record_ordinal = (
                fixture.source_record_ordinal
                if fixture.source_record_ordinal is not None
                else fixture_index
            )
            if (
                not evidence.horizon_not_before_utc
                <= fixture.kickoff_utc
                < evidence.horizon_expires_at_utc
                or source.retrieved_at_utc >= fixture.kickoff_utc
            ):
                raise ValueError("DATA_TORRENT_OFFICIAL_TEMPORAL_LEAKAGE")
            record_id = _record_id(
                "OFFICIAL_FIXTURE",
                evidence.sport_key,
                fixture.official_id,
                utc_text(fixture.kickoff_utc),
                fixture.home,
                fixture.away,
            )
            rows.append(
                {
                    "record_id": record_id,
                    "record_type": "OFFICIAL_FIXTURE",
                    "sport_key": evidence.sport_key,
                    "official_fixture_id": fixture.official_id,
                    "home_team": fixture.home,
                    "away_team": fixture.away,
                    "kickoff_utc": utc_text(fixture.kickoff_utc),
                    "known_at_utc": utc_text(source.retrieved_at_utc),
                    "source_response_id": source.response_id,
                    "source_raw_sha256": source.sha256,
                    "source_record_ordinal": source_record_ordinal,
                    "source_pointer": source_pointer,
                    "source_pointer_domain": (
                        "RAW_RESPONSE_JSON_POINTER"
                        if fixture.source_pointer is not None
                        else "DETERMINISTIC_ADAPTER_PROJECTION"
                    ),
                    "source_adapter_revision": evidence.adapter_revision,
                    "run_identity": run_identity,
                    "claim_identity": claim_identity,
                    "temporal_role": "PRE_EVENT_OFFICIAL_SCHEDULE",
                }
            )
    return rows


def _fixture_candidates(
    evidences: tuple[OfficialScheduleEvidence, ...],
    *,
    team_aliases: Mapping[str, str],
) -> dict[tuple[str, datetime, str, str], tuple[str, ...]]:
    candidates: dict[tuple[str, datetime, str, str], list[str]] = {}
    for evidence in evidences:
        for fixture in evidence.fixtures:
            record_id = _record_id(
                "OFFICIAL_FIXTURE",
                evidence.sport_key,
                fixture.official_id,
                utc_text(fixture.kickoff_utc),
                fixture.home,
                fixture.away,
            )
            key = (
                evidence.sport_key,
                fixture.kickoff_utc.astimezone(UTC),
                _team_key(fixture.home, team_aliases),
                _team_key(fixture.away, team_aliases),
            )
            candidates.setdefault(key, []).append(record_id)
    projected = {key: tuple(sorted(values)) for key, values in candidates.items()}
    if any(len(values) != 1 for values in projected.values()):
        raise ValueError("DATA_TORRENT_TEAM_ALIAS_FIXTURE_COLLISION")
    return projected


def validate_official_team_aliases(
    evidences: tuple[OfficialScheduleEvidence, ...],
    *,
    team_aliases: Mapping[str, str],
) -> None:
    """Fail before provider access if reviewed aliases collapse an official fixture."""

    for evidence in evidences:
        original_by_match_key: dict[str, str] = {}
        for fixture in evidence.fixtures:
            home_original = canonical_team_name_v1(fixture.home)
            away_original = canonical_team_name_v1(fixture.away)
            home_key = _team_key(fixture.home, team_aliases)
            away_key = _team_key(fixture.away, team_aliases)
            if home_key == away_key:
                raise ValueError("DATA_TORRENT_TEAM_ALIAS_SELF_FIXTURE")
            for original, match_key in (
                (home_original, home_key),
                (away_original, away_key),
            ):
                previous = original_by_match_key.setdefault(match_key, original)
                if previous != original:
                    raise ValueError("DATA_TORRENT_TEAM_ALIAS_SPORT_COLLISION")
    _fixture_candidates(evidences, team_aliases=team_aliases)


def _reject(
    *,
    response: RawResponseEnvelope,
    raw_event_index: int,
    reason: str,
    detail: str,
    source_pointer: str | None = None,
    market_key: str | None = None,
) -> dict[str, Any]:
    return {
        "reject_id": _record_id(
            response.response_id,
            raw_event_index,
            reason,
            detail,
            source_pointer,
            market_key,
        ),
        "response_id": response.response_id,
        "sport_key": response.sport_key,
        "raw_event_index": raw_event_index,
        "source_pointer": source_pointer or f"events[{raw_event_index}]",
        "market_key": market_key,
        "reason": reason,
        "detail": detail,
        "source_raw_sha256": response.sha256,
        "run_identity": response.run_identity,
        "claim_identity": response.claim_identity,
    }


def _normalize_odds_response(
    response: RawResponseEnvelope,
    *,
    fixture_candidates: dict[tuple[str, datetime, str, str], tuple[str, ...]],
    team_aliases: Mapping[str, str],
    team_aliases_sha256: str,
    horizon_not_before_utc: datetime,
    horizon_expires_at_utc: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, int, set[str]]:
    records: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    returned_markets: set[str] = set()
    try:
        payload = strict_json_loads(
            response.body,
            duplicate_code="ODDS_RESPONSE_JSON_DUPLICATE_KEY",
            non_finite_code="ODDS_RESPONSE_JSON_NON_FINITE",
        )
    except ValueError as error:
        reason = str(error)
        if reason not in {
            "ODDS_RESPONSE_JSON_DUPLICATE_KEY",
            "ODDS_RESPONSE_JSON_NON_FINITE",
        }:
            reason = "ODDS_RESPONSE_JSON_INVALID"
        rejects.append(
            _reject(
                response=response,
                raw_event_index=0,
                reason=reason,
                detail="response body failed strict UTF-8 JSON parsing",
            )
        )
        return records, rejects, 1, 1, returned_markets
    if not isinstance(payload, list):
        rejects.append(
            _reject(
                response=response,
                raw_event_index=0,
                reason="ODDS_RESPONSE_ROOT_INVALID",
                detail="root must be a list",
            )
        )
        return records, rejects, 1, 1, returned_markets
    accounted_events = 0
    provider_event_by_fixture: dict[str, str] = {}
    fixture_by_provider_event: dict[str, str] = {}
    for event_index, raw_event in enumerate(payload):
        event_records_before = len(records)
        event_rejects_before = len(rejects)
        try:
            if not isinstance(raw_event, dict):
                raise ValueError("EVENT_NOT_OBJECT")
            event_id = _text(raw_event.get("id"), code="EVENT_ID_INVALID")
            sport_key = _text(raw_event.get("sport_key"), code="SPORT_KEY_INVALID")
            if sport_key != response.sport_key:
                raise ValueError("SPORT_KEY_MISMATCH")
            commence = _parse_utc(raw_event.get("commence_time"))
            home = _text(raw_event.get("home_team"), code="HOME_TEAM_INVALID")
            away = _text(raw_event.get("away_team"), code="AWAY_TEAM_INVALID")
            if home == away:
                raise ValueError("TEAM_IDENTITY_INVALID")
            if commence <= response.retrieved_at_utc:
                raise ValueError("POST_EVENT_ODDS_FORBIDDEN")
            if not horizon_not_before_utc <= commence < horizon_expires_at_utc:
                raise ValueError("OUTSIDE_AUTHORIZED_HORIZON")
            candidates = fixture_candidates.get(
                (
                    sport_key,
                    commence,
                    _team_key(home, team_aliases),
                    _team_key(away, team_aliases),
                ),
                (),
            )
            if not candidates:
                raise ValueError("PROVIDER_EVENT_UNMATCHED")
            if len(candidates) != 1:
                raise ValueError("PROVIDER_EVENT_AMBIGUOUS")
            canonical_fixture_id = candidates[0]
            home_match_key = _team_key(home, team_aliases)
            away_match_key = _team_key(away, team_aliases)
            previous_provider_event = provider_event_by_fixture.get(canonical_fixture_id)
            if previous_provider_event is not None and previous_provider_event != event_id:
                raise ValueError("PROVIDER_FIXTURE_ONE_TO_ONE_CONFLICT")
            previous_fixture = fixture_by_provider_event.get(event_id)
            if previous_fixture is not None and previous_fixture != canonical_fixture_id:
                raise ValueError("PROVIDER_EVENT_ONE_TO_ONE_CONFLICT")
            provider_event_by_fixture[canonical_fixture_id] = event_id
            fixture_by_provider_event[event_id] = canonical_fixture_id
            bookmakers = raw_event.get("bookmakers")
            if not isinstance(bookmakers, list):
                raise ValueError("BOOKMAKERS_INVALID")
            for bookmaker_index, raw_bookmaker in enumerate(bookmakers):
                if not isinstance(raw_bookmaker, dict):
                    rejects.append(
                        _reject(
                            response=response,
                            raw_event_index=event_index,
                            reason="BOOKMAKER_INVALID",
                            detail=f"bookmaker_index={bookmaker_index}",
                            source_pointer=(f"events[{event_index}].bookmakers[{bookmaker_index}]"),
                        )
                    )
                    continue
                try:
                    bookmaker_key = _text(
                        raw_bookmaker.get("key"),
                        code="BOOKMAKER_KEY_INVALID",
                    )
                    bookmaker_title = _text(
                        raw_bookmaker.get("title"),
                        code="BOOKMAKER_TITLE_INVALID",
                    )
                    bookmaker_update = _parse_utc(raw_bookmaker.get("last_update"))
                except ValueError as error:
                    rejects.append(
                        _reject(
                            response=response,
                            raw_event_index=event_index,
                            reason=str(error),
                            detail=f"bookmaker_index={bookmaker_index}",
                            source_pointer=(f"events[{event_index}].bookmakers[{bookmaker_index}]"),
                        )
                    )
                    continue
                if bookmaker_update > response.retrieved_at_utc:
                    rejects.append(
                        _reject(
                            response=response,
                            raw_event_index=event_index,
                            reason="BOOKMAKER_FUTURE_TIMESTAMP",
                            detail=f"bookmaker={bookmaker_key}",
                            source_pointer=(f"events[{event_index}].bookmakers[{bookmaker_index}]"),
                        )
                    )
                    continue
                markets = raw_bookmaker.get("markets")
                if not isinstance(markets, list):
                    rejects.append(
                        _reject(
                            response=response,
                            raw_event_index=event_index,
                            reason="MARKETS_INVALID",
                            detail=f"bookmaker={bookmaker_key}",
                            source_pointer=(
                                f"events[{event_index}].bookmakers[{bookmaker_index}].markets"
                            ),
                        )
                    )
                    continue
                for market_index, raw_market in enumerate(markets):
                    if not isinstance(raw_market, dict):
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="MARKET_INVALID",
                                detail=(f"bookmaker={bookmaker_key};market_index={market_index}"),
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}]"
                                ),
                            )
                        )
                        continue
                    market_key = raw_market.get("key")
                    if market_key not in {"h2h", "totals"}:
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="MARKET_NOT_ENABLED",
                                detail=f"market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}]"
                                ),
                                market_key=(market_key if isinstance(market_key, str) else None),
                            )
                        )
                        continue
                    returned_markets.add(cast(str, market_key))
                    try:
                        market_update = _parse_utc(raw_market.get("last_update"))
                    except ValueError as error:
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason=str(error),
                                detail=f"market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].last_update"
                                ),
                                market_key=cast(str, market_key),
                            )
                        )
                        continue
                    if market_update > response.retrieved_at_utc:
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="MARKET_FUTURE_TIMESTAMP",
                                detail=f"market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].last_update"
                                ),
                                market_key=cast(str, market_key),
                            )
                        )
                        continue
                    outcomes = raw_market.get("outcomes")
                    if not isinstance(outcomes, list):
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="OUTCOMES_INVALID",
                                detail=f"market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].outcomes"
                                ),
                                market_key=cast(str, market_key),
                            )
                        )
                        continue
                    if not outcomes:
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="OUTCOMES_EMPTY",
                                detail=f"market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].outcomes"
                                ),
                                market_key=cast(str, market_key),
                            )
                        )
                        continue
                    market_records_before = len(records)
                    for outcome_index, raw_outcome in enumerate(outcomes):
                        try:
                            if not isinstance(raw_outcome, dict):
                                raise ValueError("OUTCOME_INVALID")
                            outcome_name = _text(
                                raw_outcome.get("name"),
                                code="OUTCOME_NAME_INVALID",
                            )
                            price_raw = raw_outcome.get("price")
                            if isinstance(price_raw, bool) or not isinstance(
                                price_raw, (int, float)
                            ):
                                raise ValueError("OUTCOME_PRICE_INVALID")
                            price = float(price_raw)
                            if not math.isfinite(price) or price <= 1.0:
                                raise ValueError("OUTCOME_PRICE_INVALID")
                            point_raw = raw_outcome.get("point")
                            if point_raw is not None and (
                                isinstance(point_raw, bool)
                                or not isinstance(point_raw, (int, float))
                            ):
                                raise ValueError("OUTCOME_POINT_INVALID")
                            point = None if point_raw is None else float(point_raw)
                            if point is not None and not math.isfinite(point):
                                raise ValueError("OUTCOME_POINT_INVALID")
                            if market_key == "h2h":
                                if point is not None:
                                    raise ValueError("H2H_POINT_FORBIDDEN")
                                if outcome_name not in {home, away, "Draw"}:
                                    raise ValueError("H2H_OUTCOME_NAME_INVALID")
                            else:
                                if point is None:
                                    raise ValueError("TOTALS_POINT_REQUIRED")
                                if outcome_name not in {"Over", "Under"}:
                                    raise ValueError("TOTALS_OUTCOME_NAME_INVALID")
                        except (OverflowError, TypeError, ValueError) as error:
                            rejects.append(
                                _reject(
                                    response=response,
                                    raw_event_index=event_index,
                                    reason=str(error),
                                    detail=(
                                        f"bookmaker={bookmaker_key};market={market_key};"
                                        f"outcome_index={outcome_index}"
                                    ),
                                    source_pointer=(
                                        f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                        f".markets[{market_index}].outcomes[{outcome_index}]"
                                    ),
                                    market_key=cast(str, market_key),
                                )
                            )
                            continue
                        record_id = _record_id(
                            "ODDS_OUTCOME",
                            sport_key,
                            event_id,
                            bookmaker_key,
                            market_key,
                            outcome_name,
                            point,
                        )
                        records.append(
                            {
                                "record_id": record_id,
                                "record_type": "ODDS_OUTCOME",
                                "sport_key": sport_key,
                                "provider_event_id": event_id,
                                "canonical_fixture_id": canonical_fixture_id,
                                "official_fixture_record_id": canonical_fixture_id,
                                "home_team": home,
                                "away_team": away,
                                "home_team_match_key": home_match_key,
                                "away_team_match_key": away_match_key,
                                "home_team_mapping_method": (
                                    "REVIEWED_ALIAS"
                                    if canonical_team_name_v1(home) != home_match_key
                                    else "EXACT_CANONICAL"
                                ),
                                "away_team_mapping_method": (
                                    "REVIEWED_ALIAS"
                                    if canonical_team_name_v1(away) != away_match_key
                                    else "EXACT_CANONICAL"
                                ),
                                "team_alias_mapping_sha256": team_aliases_sha256,
                                "kickoff_utc": utc_text(commence),
                                "bookmaker_key": bookmaker_key,
                                "bookmaker_title": bookmaker_title,
                                "market_key": market_key,
                                "outcome_name": outcome_name,
                                "point": point,
                                "decimal_price": price,
                                "bookmaker_last_update_utc": utc_text(bookmaker_update),
                                "market_last_update_utc": utc_text(market_update),
                                "retrieved_at_utc": utc_text(response.retrieved_at_utc),
                                "source_response_id": response.response_id,
                                "source_raw_sha256": response.sha256,
                                "source_record_ordinal": event_index,
                                "source_pointer": (
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].outcomes[{outcome_index}]"
                                ),
                                "run_identity": response.run_identity,
                                "claim_identity": response.claim_identity,
                                "temporal_role": "PRE_EVENT_PROVIDER_ODDS",
                            }
                        )
                    market_records = records[market_records_before:]
                    if market_key == "h2h":
                        complete = (
                            len(market_records) == 3
                            and {str(item["outcome_name"]) for item in market_records}
                            == {home, away, "Draw"}
                            and all(item["point"] is None for item in market_records)
                        )
                    else:
                        totals_pairs: dict[float, set[str]] = {}
                        for item in market_records:
                            item_point = cast(float, item["point"])
                            totals_pairs.setdefault(item_point, set()).add(
                                cast(str, item["outcome_name"])
                            )
                        complete = (
                            bool(totals_pairs)
                            and len(market_records) == 2 * len(totals_pairs)
                            and all(names == {"Over", "Under"} for names in totals_pairs.values())
                        )
                    if not complete:
                        del records[market_records_before:]
                        rejects.append(
                            _reject(
                                response=response,
                                raw_event_index=event_index,
                                reason="MARKET_OUTCOMES_INCOMPLETE",
                                detail=f"bookmaker={bookmaker_key};market={market_key}",
                                source_pointer=(
                                    f"events[{event_index}].bookmakers[{bookmaker_index}]"
                                    f".markets[{market_index}].outcomes"
                                ),
                                market_key=cast(str, market_key),
                            )
                        )
        except ValueError as error:
            rejects.append(
                _reject(
                    response=response,
                    raw_event_index=event_index,
                    reason=str(error),
                    detail="event rejected before outcome normalization",
                )
            )
        if len(records) > event_records_before or len(rejects) > event_rejects_before:
            accounted_events += 1
        else:
            rejects.append(
                _reject(
                    response=response,
                    raw_event_index=event_index,
                    reason="EVENT_EMPTY_AFTER_NORMALIZATION",
                    detail="no outcomes or explicit nested rejects",
                )
            )
            accounted_events += 1
    return records, rejects, len(payload), accounted_events, returned_markets


def normalize_batch(
    *,
    evidences: tuple[OfficialScheduleEvidence, ...],
    raw_responses: tuple[RawResponseEnvelope, ...],
    league_names: dict[str, str],
    requested_markets: tuple[str, ...],
    run_identity: str,
    claim_identity: str,
    team_aliases: Mapping[str, str] | None = None,
) -> NormalizedBatch:
    aliases = {} if team_aliases is None else dict(team_aliases)
    aliases_sha256 = hashlib.sha256(canonical_json_bytes(aliases)).hexdigest()
    expected_sports = {item.sport_key for item in evidences}
    official_items = tuple(item for item in raw_responses if item.family == "OFFICIAL")
    official_main = {item.sport_key: item for item in official_items}
    official_raw_items = tuple(
        item for item in raw_responses if item.family in {"OFFICIAL", "OFFICIAL_SUPPORTING"}
    )
    odds_items = tuple(item for item in raw_responses if item.family == "ODDS")
    if (
        expected_sports != set(league_names)
        or len(official_items) != len(expected_sports)
        or set(official_main) != expected_sports
        or len(odds_items) != len(expected_sports)
        or {item.sport_key for item in odds_items} != expected_sports
        or len({item.response_id for item in raw_responses}) != len(raw_responses)
        or len({item.response_sequence for item in raw_responses}) != len(raw_responses)
        or any(
            item.run_identity != run_identity
            or item.claim_identity != claim_identity
            or item.sport_key not in expected_sports
            or item.disposition != "ACCEPTED"
            for item in raw_responses
        )
        or tuple(sorted(item.response_sequence for item in raw_responses))
        != tuple(range(1, len(raw_responses) + 1))
    ):
        raise ValueError("DATA_TORRENT_OFFICIAL_RAW_LINEAGE_INCOMPLETE")
    official_operations = {item.external_operation_id for item in official_items}
    odds_operations = {item.external_operation_id for item in odds_items}
    if (
        len(official_operations) != len(expected_sports)
        or len(odds_operations) != len(expected_sports)
        or official_operations & odds_operations
        or {item.external_effect_sequence for item in official_items}
        != set(range(1, len(expected_sports) + 1))
        or {item.external_effect_sequence for item in odds_items}
        != set(range(1, len(expected_sports) + 1))
    ):
        raise ValueError("DATA_TORRENT_EXTERNAL_EFFECT_LINEAGE_INVALID")
    for evidence in evidences:
        main = official_main[evidence.sport_key]
        if (
            evidence.source_content_sha256 != main.sha256
            or evidence.source_authority != main.source
            or evidence.source_observed_at_utc != main.retrieved_at_utc
        ):
            raise ValueError("DATA_TORRENT_OFFICIAL_RAW_HASH_MISMATCH")
    main_operations = {
        (item.sport_key, item.external_operation_id): (
            item.external_effect_sequence,
            item.permit_hash,
            item.dispatch_event_hash,
            item.confirmation_event_hash,
        )
        for item in official_items
    }
    if any(
        main_operations.get((item.sport_key, item.external_operation_id))
        != (
            item.external_effect_sequence,
            item.permit_hash,
            item.dispatch_event_hash,
            item.confirmation_event_hash,
        )
        for item in raw_responses
        if item.family == "OFFICIAL_SUPPORTING"
    ):
        raise ValueError("DATA_TORRENT_OFFICIAL_SUPPORTING_LINEAGE_INCOMPLETE")
    official_lineage_keys = tuple(
        (item.sport_key, item.source, item.sha256) for item in official_raw_items
    )
    if len(official_lineage_keys) != len(set(official_lineage_keys)):
        raise ValueError("DATA_TORRENT_OFFICIAL_RAW_LINEAGE_AMBIGUOUS")
    official_by_lineage = {
        key: item for key, item in zip(official_lineage_keys, official_raw_items, strict=True)
    }
    evidence_by_sport = {item.sport_key: item for item in evidences}
    latest_official_by_sport = {
        sport_key: max(
            item.retrieved_at_utc for item in official_raw_items if item.sport_key == sport_key
        )
        for sport_key in expected_sports
    }
    if any(item.retrieved_at_utc < latest_official_by_sport[item.sport_key] for item in odds_items):
        raise ValueError("DATA_TORRENT_CROSS_SOURCE_TEMPORAL_ORDER_INVALID")
    records = _official_records(
        evidences,
        response_by_lineage=official_by_lineage,
        run_identity=run_identity,
        claim_identity=claim_identity,
    )
    candidates = _fixture_candidates(evidences, team_aliases=aliases)
    rejects: list[dict[str, Any]] = []
    raw_events_observed = 0
    raw_events_accounted = 0
    markets_by_sport: dict[str, set[str]] = {key: set() for key in league_names}
    for response in raw_responses:
        if response.family != "ODDS":
            continue
        evidence = evidence_by_sport[response.sport_key]
        normalized, rejected, observed, accounted, markets = _normalize_odds_response(
            response,
            fixture_candidates=candidates,
            team_aliases=aliases,
            team_aliases_sha256=aliases_sha256,
            horizon_not_before_utc=evidence.horizon_not_before_utc,
            horizon_expires_at_utc=evidence.horizon_expires_at_utc,
        )
        records.extend(normalized)
        rejects.extend(rejected)
        raw_events_observed += observed
        raw_events_accounted += accounted
        markets_by_sport[response.sport_key].update(markets)
    ids = [cast(str, item["record_id"]) for item in records]
    logical_duplicates = len(ids) - len(set(ids))
    temporal_leakage = sum(
        1
        for item in records
        if item["record_type"] == "ODDS_OUTCOME"
        and (
            _parse_utc(item["kickoff_utc"]) <= _parse_utc(item["retrieved_at_utc"])
            or _parse_utc(item["bookmaker_last_update_utc"]) > _parse_utc(item["retrieved_at_utc"])
            or _parse_utc(item["market_last_update_utc"]) > _parse_utc(item["retrieved_at_utc"])
        )
    )
    silent_drops = raw_events_observed - raw_events_accounted
    sorted_records = tuple(sorted(records, key=lambda item: cast(str, item["record_id"])))
    sorted_rejects = tuple(sorted(rejects, key=lambda item: cast(str, item["reject_id"])))
    dataset_bytes = b"".join(canonical_json_bytes(item) + b"\n" for item in sorted_records)
    reject_bytes = b"".join(canonical_json_bytes(item) + b"\n" for item in sorted_rejects)
    coverage: list[dict[str, Any]] = []
    for sport_key, name in league_names.items():
        fixture_count = len(evidence_by_sport[sport_key].fixtures)
        for market in requested_markets:
            market_records = sum(
                1
                for item in sorted_records
                if item["record_type"] == "ODDS_OUTCOME"
                and item["sport_key"] == sport_key
                and item["market_key"] == market
            )
            exact_market_rejects = sum(
                1
                for item in sorted_rejects
                if item["sport_key"] == sport_key and item["market_key"] == market
            )
            unscoped_rejects = sum(
                1
                for item in sorted_rejects
                if item["sport_key"] == sport_key and item["market_key"] is None
            )
            market_rejects = exact_market_rejects
            captured_fixtures = {
                cast(str, item["canonical_fixture_id"])
                for item in sorted_records
                if item["record_type"] == "ODDS_OUTCOME"
                and item["sport_key"] == sport_key
                and item["market_key"] == market
            }
            returned = market in markets_by_sport[sport_key]
            coverage.append(
                {
                    "league": name,
                    "sport_key": sport_key,
                    "fixtures_available": fixture_count,
                    "fixtures_captured": len(captured_fixtures),
                    "market": market,
                    "markets_requested": 1,
                    "markets_returned": int(returned),
                    "records_normalized": market_records,
                    "records_rejected": market_rejects,
                    "coverage_percentage": (
                        round(100.0 * len(captured_fixtures) / fixture_count, 4)
                        if fixture_count
                        else 0.0
                    ),
                    "absence_reason": (
                        "NONE"
                        if market_records > 0
                        else "ALL_RETURNED_RECORDS_REJECTED"
                        if returned
                        else "RESPONSE_REJECTED_BEFORE_MARKET"
                        if unscoped_rejects
                        else "PROVIDER_MARKET_NOT_RETURNED"
                    ),
                }
            )
    return NormalizedBatch(
        records=sorted_records,
        rejects=sorted_rejects,
        coverage=tuple(coverage),
        raw_events_observed=raw_events_observed,
        raw_events_accounted=raw_events_accounted,
        silent_drops=silent_drops,
        logical_duplicates=logical_duplicates,
        temporal_leakage=temporal_leakage,
        canonical_dataset_sha256=hashlib.sha256(dataset_bytes).hexdigest(),
        canonical_dataset_bytes=dataset_bytes,
        rejects_bytes=reject_bytes,
    )


__all__ = [
    "NormalizedBatch",
    "load_team_aliases",
    "normalize_batch",
    "team_alias_registry_document",
    "validate_official_team_aliases",
]
