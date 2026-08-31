"""Small immutable contracts shared by the data-torrent runtime."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from robin.capture.live_contracts import (
    LIVE_ALLOWED_MARKETS,
    LIVE_ALLOWED_REGION,
    LIVE_ALLOWED_SPORT_KEYS,
)
from robin.capture.official_schedule_sources import (
    SOURCE_PLAN_SCHEMA,
    OfficialSourceSpec,
    load_official_source_plan_bytes,
)

_ALLOWED_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "etag",
        "last-modified",
        "date",
        "x-requests-last",
        "x-requests-used",
        "x-requests-remaining",
    }
)
_FORBIDDEN_CONTROL_TEXT = (
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "set-cookie",
    "cookie",
    "password",
    "secret",
    "access_token",
)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("DATA_TORRENT_TIMEZONE_REQUIRED")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_request_contract_safety(request_contract: object) -> None:
    """Reject non-canonical or secret-bearing persisted request metadata."""

    if not isinstance(request_contract, dict):
        raise ValueError("DATA_TORRENT_REQUEST_CONTRACT_INVALID")
    try:
        request_bytes = canonical_json_bytes(request_contract)
    except (TypeError, ValueError):
        raise ValueError("DATA_TORRENT_REQUEST_CONTRACT_INVALID") from None
    lowered = request_bytes.lower()
    if len(lowered) > 65_536 or any(
        token.encode("ascii") in lowered for token in _FORBIDDEN_CONTROL_TEXT
    ):
        raise ValueError("DATA_TORRENT_REQUEST_CONTRACT_SECRET_FORBIDDEN")


def validate_response_metadata_safety(
    *,
    source: object,
    response_headers: object,
) -> None:
    """Apply the producer's persisted-source and response-header safety contract."""

    if (
        type(source) is not str
        or not source
        or source.strip() != source
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in source)
        or len(source) > 2_048
    ):
        raise ValueError("DATA_TORRENT_RAW_RESPONSE_INVALID")
    if type(response_headers) is not dict:
        raise ValueError("DATA_TORRENT_RESPONSE_HEADER_INVALID")
    headers = cast(dict[object, object], response_headers)
    if set(headers) - _ALLOWED_RESPONSE_HEADERS:
        raise ValueError("DATA_TORRENT_RESPONSE_HEADER_FORBIDDEN")
    if any(
        type(name) is not str
        or type(value) is not str
        or name != name.casefold()
        or not value.isascii()
        or len(value) > 512
        or any(character in value for character in "\r\n\x00")
        for name, value in headers.items()
    ):
        raise ValueError("DATA_TORRENT_RESPONSE_HEADER_INVALID")


@dataclass(frozen=True, slots=True)
class LeagueConfig:
    sport_key: str
    name: str
    official_source: OfficialSourceSpec


@dataclass(frozen=True, slots=True)
class TorrentBudgets:
    official_physical_reads_max: int
    odds_provider_requests_max: int
    odds_credits_max: int
    automatic_retries: int
    r2_puts_max: int
    r2_gets_max: int
    r2_lists_max: int
    r2_deletes_max: int


@dataclass(frozen=True, slots=True)
class TorrentConfig:
    schema_version: str
    opportunity_kind: str
    season: str
    region: str
    markets: tuple[str, ...]
    leagues: tuple[LeagueConfig, ...]
    primary_horizon_days: int
    fallback_horizon_days: int
    fallback_if_fixtures_below: int
    budgets: TorrentBudgets
    replay_multiplier: int
    minimum_throughput_ratio: float
    canonical_sha256: str


@dataclass(frozen=True, slots=True)
class RawResponseEnvelope:
    response_id: str
    family: Literal["OFFICIAL", "OFFICIAL_SUPPORTING", "ODDS"]
    sport_key: str
    source: str
    request_contract: dict[str, Any]
    retrieved_at_utc: datetime
    http_status: int
    content_type: str
    response_headers: dict[str, str]
    body: bytes
    run_identity: str
    claim_identity: str
    response_sequence: int
    external_effect_sequence: int
    external_operation_id: str
    permit_hash: str
    dispatch_event_hash: str
    confirmation_event_hash: str
    physical_reads: int = 1
    provider_requests: int = 0
    provider_credits: int = 0
    disposition: str = "ACCEPTED"
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.family not in {"OFFICIAL", "OFFICIAL_SUPPORTING", "ODDS"}:
            raise ValueError("DATA_TORRENT_RESPONSE_FAMILY_INVALID")
        if self.sport_key not in LIVE_ALLOWED_SPORT_KEYS:
            raise ValueError("DATA_TORRENT_SPORT_KEY_INVALID")
        if self.retrieved_at_utc.tzinfo is None or self.retrieved_at_utc.utcoffset() is None:
            raise ValueError("DATA_TORRENT_RETRIEVED_TIME_INVALID")
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.response_id) is None
            or not self.source
            or self.source.strip() != self.source
            or "\x00" in self.source
            or len(self.source) > 2048
            or not isinstance(self.body, bytes)
            or not self.run_identity
            or self.run_identity.strip() != self.run_identity
            or "\x00" in self.run_identity
            or len(self.run_identity) > 512
            or not self.claim_identity
            or re.fullmatch(r"[0-9a-f]{64}", self.claim_identity) is None
            or type(self.http_status) is not int
            or not 100 <= self.http_status <= 599
            or not self.content_type
            or self.content_type.strip() != self.content_type
            or "\x00" in self.content_type
            or len(self.content_type) > 255
        ):
            raise ValueError("DATA_TORRENT_RAW_RESPONSE_INVALID")
        if (
            type(self.response_sequence) is not int
            or type(self.external_effect_sequence) is not int
            or type(self.physical_reads) is not int
            or self.response_sequence <= 0
            or self.external_effect_sequence <= 0
            or self.physical_reads != 1
        ):
            raise ValueError("DATA_TORRENT_EFFECT_SEQUENCE_INVALID")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (
                self.external_operation_id,
                self.permit_hash,
                self.dispatch_event_hash,
                self.confirmation_event_hash,
            )
        ):
            raise ValueError("DATA_TORRENT_EFFECT_HASH_INVALID")
        if (
            type(self.provider_requests) is not int
            or type(self.provider_credits) is not int
            or self.provider_requests not in {0, 1}
            or self.provider_credits < 0
            or (
                self.family == "ODDS"
                and (
                    self.provider_requests != 1
                    or (self.disposition == "ACCEPTED" and self.http_status != 200)
                )
            )
            or (
                self.family != "ODDS"
                and (self.provider_requests != 0 or self.provider_credits != 0)
            )
            or (
                self.family == "OFFICIAL"
                and self.disposition == "ACCEPTED"
                and self.http_status != 200
            )
        ):
            raise ValueError("DATA_TORRENT_PROVIDER_ACCOUNTING_INVALID")
        if self.disposition not in {"ACCEPTED", "REJECTED"} or (
            (self.disposition == "ACCEPTED") != (self.rejection_reason is None)
        ):
            raise ValueError("DATA_TORRENT_DISPOSITION_INVALID")
        validate_request_contract_safety(self.request_contract)
        validate_response_metadata_safety(
            source=self.source,
            response_headers=self.response_headers,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def index_entry(self, *, archive_path: str) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "family": self.family,
            "sport_key": self.sport_key,
            "source": self.source,
            "request_contract": self.request_contract,
            "retrieved_at_utc": utc_text(self.retrieved_at_utc),
            "http_status": self.http_status,
            "content_type": self.content_type,
            "response_headers": self.response_headers,
            "raw_bytes": len(self.body),
            "raw_sha256": self.sha256,
            "response_sequence": self.response_sequence,
            "run_identity": self.run_identity,
            "claim_identity": self.claim_identity,
            "effect_accounting": {
                "effect_id": self.external_operation_id,
                "permit_hash": self.permit_hash,
                "dispatch_event_hash": self.dispatch_event_hash,
                "confirmation_event_hash": self.confirmation_event_hash,
                "sequence": self.external_effect_sequence,
                "attempt": 1,
                "physical_reads": self.physical_reads,
                "provider_requests": self.provider_requests,
                "provider_credits": self.provider_credits,
                "automatic_retries": 0,
            },
            "archive_path": archive_path,
            "disposition": self.disposition,
            "rejection_reason": self.rejection_reason,
        }


def _exact_keys(value: object, keys: set[str], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(code)
    return cast(dict[str, Any], value)


def strict_json_loads(
    value: str | bytes,
    *,
    duplicate_code: str,
    non_finite_code: str,
) -> Any:
    """Parse strict JSON without duplicate-member or non-finite-number loss."""

    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(duplicate_code)
            result[key] = item
        return result

    def reject_constant(_constant: str) -> None:
        raise ValueError(non_finite_code)

    return json.loads(
        value,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


def _exact_int(value: object, *, code: str) -> int:
    if type(value) is not int:
        raise ValueError(code)
    return value


def load_torrent_config(path: Path) -> TorrentConfig:
    raw_bytes = path.read_bytes()
    try:
        root = strict_json_loads(
            raw_bytes,
            duplicate_code="DATA_TORRENT_CONFIG_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_CONFIG_NON_FINITE",
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("DATA_TORRENT_CONFIG_INVALID") from None
    document = _exact_keys(
        root,
        {
            "schema_version",
            "opportunity_kind",
            "season",
            "region",
            "markets",
            "leagues",
            "horizon",
            "budgets",
            "replay",
        },
        code="DATA_TORRENT_CONFIG_INVALID",
    )
    raw_markets = document["markets"]
    schema_version = document["schema_version"]
    if (
        schema_version
        not in {"robin-data-torrent-live-config-v1", "robin-data-torrent-live-config-v2"}
        or document["season"] != "2026-2027"
        or document["region"] != LIVE_ALLOWED_REGION
        or not isinstance(raw_markets, list)
        or any(not isinstance(item, str) for item in raw_markets)
        or tuple(raw_markets) != LIVE_ALLOWED_MARKETS
    ):
        raise ValueError("DATA_TORRENT_CONFIG_SCOPE_INVALID")
    raw_leagues = document["leagues"]
    if not isinstance(raw_leagues, list) or len(raw_leagues) != len(LIVE_ALLOWED_SPORT_KEYS):
        raise ValueError("DATA_TORRENT_CONFIG_LEAGUES_INVALID")
    league_documents: list[tuple[str, str, str, str]] = []
    for expected_sport, raw_league in zip(
        LIVE_ALLOWED_SPORT_KEYS,
        raw_leagues,
        strict=True,
    ):
        league = _exact_keys(
            raw_league,
            {"sport_key", "name", "official_adapter", "official_url"},
            code="DATA_TORRENT_CONFIG_LEAGUE_INVALID",
        )
        if league["sport_key"] != expected_sport:
            raise ValueError("DATA_TORRENT_CONFIG_LEAGUE_ORDER_INVALID")
        if any(
            not isinstance(league[field], str) or not league[field].strip()
            for field in ("sport_key", "name", "official_adapter", "official_url")
        ):
            raise ValueError("DATA_TORRENT_CONFIG_LEAGUE_INVALID")
        league_documents.append(
            (
                cast(str, league["sport_key"]),
                cast(str, league["name"]),
                cast(str, league["official_adapter"]),
                cast(str, league["official_url"]),
            )
        )
    plan_document = {
        "schema_version": SOURCE_PLAN_SCHEMA,
        "season": document["season"],
        "sources": {
            sport_key: {"adapter": adapter, "url": url}
            for sport_key, _name, adapter, url in league_documents
        },
    }
    source_plan = load_official_source_plan_bytes(canonical_json_bytes(plan_document))
    leagues = [
        LeagueConfig(
            sport_key=sport_key,
            name=name,
            official_source=source_plan.source(sport_key),
        )
        for sport_key, name, _adapter, _url in league_documents
    ]
    horizon = _exact_keys(
        document["horizon"],
        {"primary_days", "fallback_days", "fallback_if_fixtures_below"},
        code="DATA_TORRENT_CONFIG_HORIZON_INVALID",
    )
    budgets_raw = _exact_keys(
        document["budgets"],
        {
            "official_physical_reads_max",
            "odds_provider_requests_max",
            "odds_credits_max",
            "automatic_retries",
            "r2_puts_max",
            "r2_gets_max",
            "r2_lists_max",
            "r2_deletes_max",
        },
        code="DATA_TORRENT_CONFIG_BUDGETS_INVALID",
    )
    replay = _exact_keys(
        document["replay"],
        {"multiplier", "minimum_throughput_ratio"},
        code="DATA_TORRENT_CONFIG_REPLAY_INVALID",
    )
    budgets = TorrentBudgets(
        **{
            key: _exact_int(value, code="DATA_TORRENT_CONFIG_BUDGETS_INVALID")
            for key, value in budgets_raw.items()
        }
    )
    recovery_v2 = schema_version == "robin-data-torrent-live-config-v2"
    primary_days = _exact_int(horizon["primary_days"], code="DATA_TORRENT_CONFIG_HORIZON_INVALID")
    fallback_days = _exact_int(horizon["fallback_days"], code="DATA_TORRENT_CONFIG_HORIZON_INVALID")
    fallback_threshold = _exact_int(
        horizon["fallback_if_fixtures_below"],
        code="DATA_TORRENT_CONFIG_HORIZON_INVALID",
    )
    replay_multiplier = _exact_int(replay["multiplier"], code="DATA_TORRENT_CONFIG_REPLAY_INVALID")
    ratio_raw = replay["minimum_throughput_ratio"]
    if isinstance(ratio_raw, bool) or not isinstance(ratio_raw, (int, float)):
        raise ValueError("DATA_TORRENT_CONFIG_REPLAY_INVALID")
    try:
        minimum_ratio = float(ratio_raw)
    except OverflowError:
        raise ValueError("DATA_TORRENT_CONFIG_REPLAY_INVALID") from None
    if (
        primary_days != 7
        or fallback_days != 14
        or fallback_threshold != 20
        or budgets.official_physical_reads_max != 50
        or budgets.odds_provider_requests_max != 5
        or budgets.odds_credits_max != 1000
        or budgets.automatic_retries != 0
        or budgets.r2_puts_max != (2 if recovery_v2 else 20)
        or budgets.r2_gets_max != (1 if recovery_v2 else 20)
        or budgets.r2_lists_max != (0 if recovery_v2 else 2)
        or budgets.r2_deletes_max != 0
        or (recovery_v2 and replay_multiplier != 100)
        or (not recovery_v2 and replay_multiplier < 100)
        or not math.isfinite(minimum_ratio)
        or minimum_ratio < 5.0
    ):
        raise ValueError("DATA_TORRENT_CONFIG_BOUNDS_INVALID")
    opportunity_kind_raw = document["opportunity_kind"]
    if not isinstance(opportunity_kind_raw, str) or not opportunity_kind_raw.strip():
        raise ValueError("DATA_TORRENT_CONFIG_OPPORTUNITY_INVALID")
    opportunity_kind = opportunity_kind_raw
    canonical = canonical_json_bytes(document)
    return TorrentConfig(
        schema_version=cast(str, schema_version),
        opportunity_kind=opportunity_kind,
        season=cast(str, document["season"]),
        region=cast(str, document["region"]),
        markets=tuple(cast(list[str], raw_markets)),
        leagues=tuple(leagues),
        primary_horizon_days=primary_days,
        fallback_horizon_days=fallback_days,
        fallback_if_fixtures_below=fallback_threshold,
        budgets=budgets,
        replay_multiplier=replay_multiplier,
        minimum_throughput_ratio=minimum_ratio,
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = [
    "LeagueConfig",
    "RawResponseEnvelope",
    "TorrentBudgets",
    "TorrentConfig",
    "canonical_json_bytes",
    "load_torrent_config",
    "strict_json_loads",
    "utc_text",
]
