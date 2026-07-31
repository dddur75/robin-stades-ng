"""Sanitized, lineage-pinned coverage proof built from derived R2 evidence only.

This module deliberately exposes a read-only object-store protocol.  It never
enumerates the raw namespace and never returns normalized source rows.  The
only publishable material is an allow-listed league/season/family aggregation.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
)

from robin.historical.object_storage_migration import create_r2_client
from robin.historical_deep.contracts import (
    CampaignContract,
    GateStatus,
    TemporalClass,
)
from robin.historical_deep.gates import GATE_NAMES
from robin.historical_deep.normalization import (
    SUPPORTED_FAMILIES,
    canonical_sha256,
)
from robin.historical_deep.runtime import DERIVED_NAMESPACE

EXPORT_SCHEMA_VERSION = "historical-deep-coverage-proof-export-v1"
DERIVED_PREFIX = f"{DERIVED_NAMESPACE}/"
DEFAULT_MAX_OUTPUT_BYTES = 2_000_000
MAX_SOURCE_OBJECT_BYTES = 128 * 1024 * 1024
MAX_DECOMPRESSED_SOURCE_BYTES = 512 * 1024 * 1024
MAX_COVERAGE_CELLS = 10_000
MAX_CATEGORY_RECORD_KEYS = 100_000

NO_CENSUS_EVIDENCE_SOURCE = "NO_CENSUS_EVIDENCE_SOURCE"
_ALLOWED_EVIDENCE_SOURCES = frozenset(
    {
        "fixtures_sample_and_bundle",
        "/players:page=1",
        "/injuries",
        "/standings",
        NO_CENSUS_EVIDENCE_SOURCE,
    }
)
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")

SOURCE_CATEGORIES = (
    "collection/census",
    "replay/projection",
    "replay",
    "quality",
    "gates",
    "report",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_RUN_TOKEN_PATTERN = re.compile(r"^[0-9]+:[1-9][0-9]*$")
_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RECORD_PATTERN = re.compile(
    r"^record-(?P<timestamp>[0-9]{8}T[0-9]{12}Z)-"
    r"(?P<digest>[0-9a-f]{64})\.json\.gz$"
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:authorization|x-apisports-key)\s*[:=]\s*\S+"),
)
_FORBIDDEN_OUTPUT_FIELDS = frozenset(
    {"payload", "entries", "rows", "data", "parameters"}
)
_ROOT_OUTPUT_FIELDS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "contract_hash",
        "source_code_revision",
        "source_run_token",
        "exporter_code_revision",
        "generated_at",
        "coverage_count",
        "normalized_row_count",
        "quality",
        "source_hashes",
        "coverage",
        "proof_hash",
    }
)
_QUALITY_OUTPUT_FIELDS = frozenset(
    {
        "exact_replay",
        "hash_identical",
        "hash_mismatches",
        "missing_payloads",
        "extra_payloads",
        "provider_calls",
        "provider_credits",
    }
)
_SOURCE_HASH_FIELDS = frozenset(
    {
        "census",
        "normalized_projection",
        "replay_source",
        "replay",
        "quality_before",
        "quality_after",
        "gates",
        "report",
        "census_envelope",
        "normalized_projection_envelope",
        "replay_envelope",
        "quality_envelope",
        "gates_envelope",
        "report_envelope",
    }
)
_COVERAGE_OUTPUT_FIELDS = (
    "league",
    "season",
    "family",
    "advertised_flag",
    "sample_verified_numerator",
    "sample_verified_denominator",
    "sample_verified_rate",
    "sample_verified_basis",
    "normalized_row_count",
    "null_rate",
    "temporal_classes",
    "gate",
    "gate_status",
    "gate_scope",
)

_FAMILY_GATE = {
    "fixtures": "TEAM",
    "teams": "TEAM",
    "events": "DISCIPLINE",
    "lineups": "LINEUP",
    "lineup_players": "LINEUP",
    "formations": "FORMATION",
    "team_match_statistics": "TEAM",
    "player_match_statistics": "PLAYER_FORM",
    "players": "PLAYER",
    "player_season_statistics": "PLAYER",
    "injuries": "ABSENCE",
    "suspensions": "ABSENCE",
    "sidelined": "ABSENCE",
}


class DerivedObjectReader(Protocol):
    """The complete storage surface available to the exporter."""

    def get_object(self, key: str) -> bytes | None: ...

    def iter_keys(self, prefix: str) -> Iterable[str]: ...


class DerivedR2ReadOnlyStore:
    """Cloudflare R2 reader with no write or delete method."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        try:
            self._client, self._bucket = create_r2_client(environment)
        except BotoCoreError:
            raise RuntimeError("COVERAGE_PROOF_R2_INIT_FAILED") from None

    @staticmethod
    def _assert_derived(value: str) -> None:
        if not value.startswith(DERIVED_PREFIX):
            raise ValueError("COVERAGE_PROOF_NON_DERIVED_R2_ACCESS_BLOCKED")

    @staticmethod
    def _error_code(error: ClientError) -> str:
        details = error.response.get("Error", {})
        if not isinstance(details, Mapping):
            return "UNKNOWN"
        return str(details.get("Code", "UNKNOWN"))

    def get_object(self, key: str) -> bytes | None:
        self._assert_derived(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if self._error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise RuntimeError("COVERAGE_PROOF_R2_GET_FAILED") from None
        except BotoCoreError:
            raise RuntimeError("COVERAGE_PROOF_R2_GET_FAILED") from None
        content_length = response.get("ContentLength")
        if content_length is not None:
            if (
                isinstance(content_length, bool)
                or not isinstance(content_length, int)
                or content_length < 0
            ):
                raise RuntimeError("COVERAGE_PROOF_R2_CONTENT_LENGTH_INVALID")
            if content_length > MAX_SOURCE_OBJECT_BYTES:
                raise ValueError("COVERAGE_PROOF_SOURCE_OBJECT_TOO_LARGE")
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise RuntimeError("COVERAGE_PROOF_R2_BODY_INVALID")
        try:
            value = body.read(MAX_SOURCE_OBJECT_BYTES + 1)
        except BotoCoreError:
            raise RuntimeError("COVERAGE_PROOF_R2_GET_FAILED") from None
        if not isinstance(value, bytes):
            raise RuntimeError("COVERAGE_PROOF_R2_BODY_INVALID")
        if len(value) > MAX_SOURCE_OBJECT_BYTES:
            raise ValueError("COVERAGE_PROOF_SOURCE_OBJECT_TOO_LARGE")
        return value

    def iter_keys(self, prefix: str) -> Iterable[str]:
        self._assert_derived(prefix)
        continuation: str | None = None
        while True:
            arguments: dict[str, object] = {
                "Bucket": self._bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation is not None:
                arguments["ContinuationToken"] = continuation
            try:
                response = cast(Any, self._client).list_objects_v2(**arguments)
            except (ClientError, BotoCoreError):
                raise RuntimeError("COVERAGE_PROOF_R2_LIST_FAILED") from None
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RuntimeError("COVERAGE_PROOF_R2_LIST_RESPONSE_INVALID")
            for item in contents:
                if not isinstance(item, Mapping):
                    continue
                key = item.get("Key")
                if isinstance(key, str):
                    self._assert_derived(key)
                    yield key
            if not bool(response.get("IsTruncated")):
                return
            candidate = response.get("NextContinuationToken")
            if not isinstance(candidate, str) or not candidate:
                raise RuntimeError("COVERAGE_PROOF_R2_LIST_CURSOR_MISSING")
            continuation = candidate


@dataclass(frozen=True, slots=True)
class DerivedEnvelope:
    category: str
    recorded_at: datetime
    value: Mapping[str, object]
    envelope_hash: str


@dataclass(frozen=True, slots=True)
class CensusCell:
    advertised_flag: bool | None
    numerator: int | None
    denominator: int | None
    rate: float | None
    basis: str
    null_rate: float | None


@dataclass(slots=True)
class NormalizedCell:
    count: int = 0
    temporal_classes: set[str] = field(default_factory=set)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}_MUST_BE_OBJECT")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label}_MUST_BE_ARRAY")
    return value


def _integer(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}_INVALID")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}_INVALID") from error
    if result < minimum:
        raise ValueError(f"{label}_BELOW_MINIMUM")
    return result


def _optional_integer(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return _integer(value, label=label)


def _optional_rate(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label}_INVALID")
    try:
        result = float(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label}_INVALID") from error
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{label}_OUTSIDE_UNIT_INTERVAL")
    return result


def _evidence_source(value: object) -> str:
    if value is None or value == "":
        return NO_CENSUS_EVIDENCE_SOURCE
    if not isinstance(value, str):
        raise ValueError("COVERAGE_PROOF_CENSUS_BASIS_INVALID")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise ValueError("COVERAGE_PROOF_CENSUS_BASIS_CONTROL_INVALID")
    if value.lstrip().startswith(_CSV_FORMULA_PREFIXES):
        raise ValueError("COVERAGE_PROOF_CENSUS_BASIS_FORMULA_PREFIX_INVALID")
    if value not in _ALLOWED_EVIDENCE_SOURCES:
        raise ValueError("COVERAGE_PROOF_CENSUS_BASIS_NOT_ALLOWED")
    return value


def _required_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label}_INVALID")
    return value


def _parse_recorded_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("COVERAGE_PROOF_ENVELOPE_RECORDED_AT_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("COVERAGE_PROOF_ENVELOPE_RECORDED_AT_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("COVERAGE_PROOF_ENVELOPE_RECORDED_AT_NAIVE")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"COVERAGE_PROOF_SOURCE_DUPLICATE_KEY:{key}")
        output[key] = value
    return output


def _decode_envelope(data: bytes) -> Mapping[str, object]:
    if len(data) > MAX_SOURCE_OBJECT_BYTES:
        raise ValueError("COVERAGE_PROOF_SOURCE_OBJECT_TOO_LARGE")
    if not data.startswith(b"\x1f\x8b"):
        raise ValueError("COVERAGE_PROOF_DERIVED_OBJECT_MUST_BE_GZIP")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            decoded = stream.read(MAX_DECOMPRESSED_SOURCE_BYTES + 1)
    except (OSError, EOFError) as error:
        raise ValueError("COVERAGE_PROOF_DERIVED_OBJECT_GZIP_INVALID") from error
    if len(decoded) > MAX_DECOMPRESSED_SOURCE_BYTES:
        raise ValueError("COVERAGE_PROOF_SOURCE_DECOMPRESSED_TOO_LARGE")
    try:
        value = json.loads(decoded, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("COVERAGE_PROOF_DERIVED_OBJECT_JSON_INVALID") from error
    return _mapping(value, label="COVERAGE_PROOF_DERIVED_ENVELOPE")


def _iter_category_envelopes(
    reader: DerivedObjectReader,
    *,
    contract: CampaignContract,
    category: str,
) -> Iterable[DerivedEnvelope]:
    prefix = f"{DERIVED_PREFIX}{category.strip('/')}/"
    seen_keys: set[str] = set()
    for key in reader.iter_keys(prefix):
        if key in seen_keys:
            raise ValueError("COVERAGE_PROOF_DERIVED_RECORD_KEY_DUPLICATE")
        if len(seen_keys) >= MAX_CATEGORY_RECORD_KEYS:
            raise ValueError("COVERAGE_PROOF_DERIVED_RECORD_KEY_LIMIT_EXCEEDED")
        seen_keys.add(key)
        if not key.startswith(prefix):
            raise ValueError("COVERAGE_PROOF_READER_RETURNED_KEY_OUTSIDE_PREFIX")
        relative = key[len(prefix) :]
        if "/" in relative:
            continue
        match = _RECORD_PATTERN.fullmatch(relative)
        if match is None:
            raise ValueError("COVERAGE_PROOF_DERIVED_RECORD_KEY_INVALID")
        body = reader.get_object(key)
        if body is None:
            raise ValueError("COVERAGE_PROOF_DERIVED_RECORD_MISSING")
        envelope = _decode_envelope(body)
        if set(envelope) != {
            "schema_version",
            "campaign_id",
            "category",
            "recorded_at",
            "value",
        }:
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_FIELDS_INVALID")
        if envelope.get("schema_version") != "historical-deep-derived-envelope-v1":
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_SCHEMA_INVALID")
        if envelope.get("campaign_id") != contract.campaign_id:
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_CAMPAIGN_MISMATCH")
        if envelope.get("category") != category:
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_CATEGORY_MISMATCH")
        recorded_at = _parse_recorded_at(envelope.get("recorded_at"))
        digest = canonical_sha256(envelope)
        if digest != match.group("digest"):
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_HASH_MISMATCH")
        if _timestamp(recorded_at) != match.group("timestamp"):
            raise ValueError("COVERAGE_PROOF_DERIVED_ENVELOPE_TIMESTAMP_MISMATCH")
        yield DerivedEnvelope(
            category=category,
            recorded_at=recorded_at,
            value=_mapping(
                envelope.get("value"),
                label="COVERAGE_PROOF_DERIVED_VALUE",
            ),
            envelope_hash=digest,
        )


def _lineage_markers(value: Mapping[str, object], field: str) -> set[str]:
    markers: set[str] = set()
    direct = value.get(field)
    if isinstance(direct, str) and direct:
        markers.add(direct)
    for item in value.values():
        if not isinstance(item, Mapping):
            continue
        child = item.get(field)
        provenance = item.get("provenance")
        provenance_value = (
            provenance.get(field) if isinstance(provenance, Mapping) else None
        )
        for candidate in (child, provenance_value):
            if isinstance(candidate, str) and candidate:
                markers.add(candidate)
    return markers


def _select_lineage_envelope(
    reader: DerivedObjectReader,
    *,
    contract: CampaignContract,
    category: str,
    source_code_revision: str,
    source_run_token: str,
) -> DerivedEnvelope:
    latest: DerivedEnvelope | None = None
    latest_count = 0
    for envelope in _iter_category_envelopes(
        reader,
        contract=contract,
        category=category,
    ):
        if (
            _lineage_markers(envelope.value, "code_revision")
            != {source_code_revision}
            or _lineage_markers(envelope.value, "run_token")
            != {source_run_token}
        ):
            continue
        if latest is None or envelope.recorded_at > latest.recorded_at:
            latest = envelope
            latest_count = 1
        elif envelope.recorded_at == latest.recorded_at:
            latest_count += 1
    if latest is None:
        raise ValueError(f"COVERAGE_PROOF_SOURCE_LINEAGE_MISSING:{category}")
    if latest_count != 1:
        raise ValueError(f"COVERAGE_PROOF_SOURCE_LINEAGE_AMBIGUOUS:{category}")
    return latest


def _assert_direct_lineage(
    value: Mapping[str, object],
    *,
    source_code_revision: str,
    source_run_token: str,
    label: str,
) -> None:
    if value.get("code_revision") != source_code_revision:
        raise ValueError(f"{label}_CODE_REVISION_MISMATCH")
    if value.get("run_token") != source_run_token:
        raise ValueError(f"{label}_RUN_TOKEN_MISMATCH")


def _validate_census(
    value: Mapping[str, object],
    *,
    contract: CampaignContract,
    source_code_revision: str,
    source_run_token: str,
) -> tuple[tuple[Mapping[str, object], ...], str]:
    _assert_direct_lineage(
        value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        label="COVERAGE_PROOF_CENSUS",
    )
    schema = value.get("schema_version")
    if schema not in {
        "historical-deep-census-run-v1",
        "historical-deep-bounded-run-v1",
    }:
        raise ValueError("COVERAGE_PROOF_CENSUS_SCHEMA_INVALID")
    observations_raw = value.get("observations", ())
    observations = (
        _sequence(observations_raw, label="COVERAGE_PROOF_CENSUS_OBSERVATIONS")
        if observations_raw != ()
        else ()
    )
    mapped_observations = tuple(
        _mapping(item, label="COVERAGE_PROOF_CENSUS_OBSERVATION")
        for item in observations
    )
    stored_hash = value.get("hash")
    if stored_hash is not None:
        expected = _required_sha256(
            stored_hash,
            label="COVERAGE_PROOF_CENSUS_HASH",
        )
        material = {
            key: item
            for key, item in value.items()
            if key not in {"hash", "durable_key"}
        }
        if canonical_sha256(material) != expected:
            raise ValueError("COVERAGE_PROOF_CENSUS_HASH_MISMATCH")
        census_hash = expected
    else:
        if schema == "historical-deep-census-run-v1":
            raise ValueError("COVERAGE_PROOF_CENSUS_HASH_MISSING")
        census_hash = canonical_sha256(value)
    discovery = value.get("discovery")
    if discovery is not None:
        mapped_discovery = _mapping(
            discovery,
            label="COVERAGE_PROOF_CENSUS_DISCOVERY",
        )
        if mapped_discovery.get("campaign_id") != contract.campaign_id:
            raise ValueError("COVERAGE_PROOF_CENSUS_DISCOVERY_CAMPAIGN_MISMATCH")
        _assert_direct_lineage(
            mapped_discovery,
            source_code_revision=source_code_revision,
            source_run_token=source_run_token,
            label="COVERAGE_PROOF_CENSUS_DISCOVERY",
        )
        discovery_hash = _required_sha256(
            mapped_discovery.get("hash"),
            label="COVERAGE_PROOF_CENSUS_DISCOVERY_HASH",
        )
        competitions = _mapping(
            mapped_discovery.get("competitions"),
            label="COVERAGE_PROOF_CENSUS_DISCOVERY_COMPETITIONS",
        )
        if canonical_sha256(competitions) != discovery_hash:
            raise ValueError("COVERAGE_PROOF_CENSUS_DISCOVERY_HASH_MISMATCH")
    return mapped_observations, census_hash


def _competition_maps(
    contract: CampaignContract,
) -> tuple[dict[int, str], dict[int, str]]:
    names: dict[int, str] = {}
    canonical: dict[int, str] = {}
    observed_names: set[str] = set()
    for competition in contract.competitions:
        if competition.provider_league_id in names:
            raise ValueError("COVERAGE_PROOF_CONTRACT_DUPLICATE_LEAGUE_ID")
        if competition.name in observed_names:
            raise ValueError("COVERAGE_PROOF_CONTRACT_DUPLICATE_LEAGUE_NAME")
        names[competition.provider_league_id] = competition.name
        canonical[competition.provider_league_id] = competition.canonical_key
        observed_names.add(competition.name)
    return names, canonical


def _census_cells(
    observations: Sequence[Mapping[str, object]],
    *,
    contract: CampaignContract,
) -> dict[tuple[int, int, str], CensusCell]:
    names, canonical = _competition_maps(contract)
    output: dict[tuple[int, int, str], CensusCell] = {}
    for observation in observations:
        league_id = _integer(
            observation.get("provider_league_id"),
            label="COVERAGE_PROOF_CENSUS_LEAGUE_ID",
            minimum=1,
        )
        if league_id not in names:
            raise ValueError("COVERAGE_PROOF_CENSUS_LEAGUE_OUTSIDE_CONTRACT")
        competition = observation.get("competition")
        if competition is not None and competition != canonical[league_id]:
            raise ValueError("COVERAGE_PROOF_CENSUS_CANONICAL_LEAGUE_MISMATCH")
        season = _integer(
            observation.get("season"),
            label="COVERAGE_PROOF_CENSUS_SEASON",
            minimum=1,
        )
        matrix = _mapping(
            observation.get("field_matrix"),
            label="COVERAGE_PROOF_CENSUS_FIELD_MATRIX",
        )
        null_rates = _mapping(
            observation.get("null_rates", {}),
            label="COVERAGE_PROOF_CENSUS_NULL_RATES",
        )
        for family_value, evidence_value in matrix.items():
            family = str(family_value)
            if (
                not _FAMILY_PATTERN.fullmatch(family)
                or family not in SUPPORTED_FAMILIES
            ):
                raise ValueError("COVERAGE_PROOF_CENSUS_FAMILY_INVALID")
            evidence = _mapping(
                evidence_value,
                label="COVERAGE_PROOF_CENSUS_FAMILY_EVIDENCE",
            )
            advertised_raw = evidence.get("advertised_flag")
            if advertised_raw is not None and not isinstance(advertised_raw, bool):
                raise ValueError("COVERAGE_PROOF_CENSUS_ADVERTISED_FLAG_INVALID")
            numerator = _optional_integer(
                evidence.get("sample_non_null_count"),
                label="COVERAGE_PROOF_CENSUS_SAMPLE_NUMERATOR",
            )
            denominator = _optional_integer(
                evidence.get("sample_denominator"),
                label="COVERAGE_PROOF_CENSUS_SAMPLE_DENOMINATOR",
            )
            rate = _optional_rate(
                evidence.get("sample_coverage_rate"),
                label="COVERAGE_PROOF_CENSUS_SAMPLE_RATE",
            )
            if denominator is None:
                if numerator not in (None, 0) or rate is not None:
                    raise ValueError(
                        "COVERAGE_PROOF_CENSUS_SAMPLE_TRIPLET_INCONSISTENT"
                    )
            elif denominator == 0:
                if numerator != 0 or rate is not None:
                    raise ValueError(
                        "COVERAGE_PROOF_CENSUS_SAMPLE_TRIPLET_INCONSISTENT"
                    )
            else:
                if numerator is None or rate is None:
                    raise ValueError(
                        "COVERAGE_PROOF_CENSUS_SAMPLE_TRIPLET_INCONSISTENT"
                    )
                if numerator > denominator:
                    raise ValueError(
                        "COVERAGE_PROOF_CENSUS_SAMPLE_NUMERATOR_ABOVE_DENOMINATOR"
                    )
                expected_rate = numerator / denominator
                if not math.isclose(rate, expected_rate):
                    raise ValueError("COVERAGE_PROOF_CENSUS_SAMPLE_RATE_MISMATCH")
            null_rate = _optional_rate(
                null_rates.get(family),
                label="COVERAGE_PROOF_CENSUS_NULL_RATE",
            )
            if rate is None and null_rate is not None or rate is not None and (
                null_rate is None or not math.isclose(null_rate, 1.0 - rate)
            ):
                raise ValueError("COVERAGE_PROOF_CENSUS_NULL_RATE_MISMATCH")
            basis = _evidence_source(evidence.get("evidence_source"))
            if denominator is None and basis != NO_CENSUS_EVIDENCE_SOURCE:
                raise ValueError("COVERAGE_PROOF_CENSUS_BASIS_WITHOUT_SAMPLE")
            if denominator is not None and basis == NO_CENSUS_EVIDENCE_SOURCE:
                raise ValueError("COVERAGE_PROOF_CENSUS_SAMPLE_WITHOUT_BASIS")
            key = (league_id, season, family)
            if key in output:
                raise ValueError("COVERAGE_PROOF_CENSUS_SCOPE_DUPLICATE")
            output[key] = CensusCell(
                advertised_flag=advertised_raw,
                numerator=numerator,
                denominator=denominator,
                rate=rate,
                basis=basis,
                null_rate=null_rate,
            )
    return output


def _validate_projection(
    value: Mapping[str, object],
    *,
    contract: CampaignContract,
    source_code_revision: str,
    source_run_token: str,
) -> tuple[dict[tuple[int, int, str], NormalizedCell], str, int]:
    _assert_direct_lineage(
        value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        label="COVERAGE_PROOF_PROJECTION",
    )
    if value.get("schema_version") != "historical-deep-normalized-replay-v1":
        raise ValueError("COVERAGE_PROOF_PROJECTION_SCHEMA_INVALID")
    if value.get("provider_calls") != 0:
        raise ValueError("COVERAGE_PROOF_PROJECTION_PROVIDER_CALLS_NONZERO")
    rows = _sequence(
        value.get("rows"),
        label="COVERAGE_PROOF_PROJECTION_ROWS",
    )
    row_count = _integer(
        value.get("row_count"),
        label="COVERAGE_PROOF_PROJECTION_ROW_COUNT",
    )
    if row_count != len(rows):
        raise ValueError("COVERAGE_PROOF_PROJECTION_ROW_COUNT_MISMATCH")
    projection_hash = _required_sha256(
        value.get("projection_hash"),
        label="COVERAGE_PROOF_PROJECTION_HASH",
    )
    if canonical_sha256(rows) != projection_hash:
        raise ValueError("COVERAGE_PROOF_PROJECTION_HASH_MISMATCH")
    names, _canonical = _competition_maps(contract)
    output: dict[tuple[int, int, str], NormalizedCell] = {}
    temporal_values = {item.value for item in TemporalClass}
    for row_value in rows:
        row = _mapping(row_value, label="COVERAGE_PROOF_NORMALIZED_ROW")
        family = str(row.get("normalized_family", row.get("family", "")))
        source_family = row.get("family")
        if (
            not _FAMILY_PATTERN.fullmatch(family)
            or family not in SUPPORTED_FAMILIES
            or source_family is not None
            and str(source_family) != family
        ):
            raise ValueError("COVERAGE_PROOF_NORMALIZED_FAMILY_INVALID")
        league_id = _integer(
            row.get("provider_competition_id"),
            label="COVERAGE_PROOF_NORMALIZED_LEAGUE_ID",
            minimum=1,
        )
        if league_id not in names:
            raise ValueError("COVERAGE_PROOF_NORMALIZED_LEAGUE_OUTSIDE_CONTRACT")
        season = _integer(
            row.get("season"),
            label="COVERAGE_PROOF_NORMALIZED_SEASON",
            minimum=1,
        )
        temporal_class = row.get("temporal_class")
        if not isinstance(temporal_class, str) or temporal_class not in temporal_values:
            raise ValueError("COVERAGE_PROOF_NORMALIZED_TEMPORAL_CLASS_INVALID")
        cell = output.setdefault((league_id, season, family), NormalizedCell())
        cell.count += 1
        cell.temporal_classes.add(temporal_class)
    if sum(cell.count for cell in output.values()) != row_count:
        raise ValueError("COVERAGE_PROOF_NORMALIZED_AGGREGATION_MISMATCH")
    return output, projection_hash, row_count


def _validate_replay(
    value: Mapping[str, object],
    *,
    projection_hash: str,
    projection_row_count: int,
    source_code_revision: str,
    source_run_token: str,
) -> tuple[str, str]:
    _assert_direct_lineage(
        value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        label="COVERAGE_PROOF_REPLAY",
    )
    if value.get("status") != "CACHE_ONLY_REPLAY_VERIFIED":
        raise ValueError("COVERAGE_PROOF_REPLAY_STATUS_INVALID")
    for name in ("provider_calls", "provider_credits", "hash_mismatches", "missing_payloads"):
        if value.get(name) != 0:
            raise ValueError(f"COVERAGE_PROOF_REPLAY_{name.upper()}_NONZERO")
    if value.get("extra_payloads") != 0 or value.get("hash_identical") is not True:
        raise ValueError("COVERAGE_PROOF_REPLAY_INTEGRITY_INVALID")
    if value.get("normalized_projection_hash") != projection_hash:
        raise ValueError("COVERAGE_PROOF_REPLAY_PROJECTION_HASH_MISMATCH")
    if value.get("normalized_rows") != projection_row_count:
        raise ValueError("COVERAGE_PROOF_REPLAY_NORMALIZED_ROW_COUNT_MISMATCH")
    entries = _sequence(
        value.get("entries"),
        label="COVERAGE_PROOF_REPLAY_ENTRIES",
    )
    payload_count = _integer(
        value.get("payloads_replayed"),
        label="COVERAGE_PROOF_REPLAY_PAYLOAD_COUNT",
    )
    receipt_count = _integer(
        value.get("receipts_verified"),
        label="COVERAGE_PROOF_REPLAY_RECEIPT_COUNT",
    )
    if len(entries) != payload_count or receipt_count != payload_count:
        raise ValueError("COVERAGE_PROOF_REPLAY_EVIDENCE_COUNT_MISMATCH")
    normalized_entries: list[dict[str, object]] = []
    source_entries: list[dict[str, object]] = []
    for entry_value in entries:
        entry = _mapping(entry_value, label="COVERAGE_PROOF_REPLAY_ENTRY")
        if set(entry) != {
            "receipt_id",
            "payload_key",
            "payload_sha256",
            "projection_sha256",
        }:
            raise ValueError("COVERAGE_PROOF_REPLAY_ENTRY_FIELDS_INVALID")
        receipt_id = _required_sha256(
            entry.get("receipt_id"),
            label="COVERAGE_PROOF_REPLAY_RECEIPT_ID",
        )
        payload_sha256 = _required_sha256(
            entry.get("payload_sha256"),
            label="COVERAGE_PROOF_REPLAY_PAYLOAD_HASH",
        )
        projection_sha256 = _required_sha256(
            entry.get("projection_sha256"),
            label="COVERAGE_PROOF_REPLAY_ENTRY_PROJECTION_HASH",
        )
        payload_key = entry.get("payload_key")
        if not isinstance(payload_key, str) or not payload_key:
            raise ValueError("COVERAGE_PROOF_REPLAY_PAYLOAD_REFERENCE_INVALID")
        normalized_entries.append(
            {
                "receipt_id": receipt_id,
                "payload_key": payload_key,
                "payload_sha256": payload_sha256,
                "projection_sha256": projection_sha256,
            }
        )
        source_entries.append(
            {
                "receipt_id": receipt_id,
                "payload_key": payload_key,
                "payload_sha256": payload_sha256,
            }
        )
    replay_hash = _required_sha256(
        value.get("replay_hash"),
        label="COVERAGE_PROOF_REPLAY_HASH",
    )
    source_hash = _required_sha256(
        value.get("source_hash"),
        label="COVERAGE_PROOF_REPLAY_SOURCE_HASH",
    )
    if canonical_sha256(normalized_entries) != replay_hash:
        raise ValueError("COVERAGE_PROOF_REPLAY_HASH_MISMATCH")
    if canonical_sha256(source_entries) != source_hash:
        raise ValueError("COVERAGE_PROOF_REPLAY_SOURCE_HASH_MISMATCH")
    return source_hash, replay_hash


def _validate_quality(
    value: Mapping[str, object],
    *,
    projection_hash: str,
    replay_hash: str,
    projection_row_count: int,
    source_code_revision: str,
    source_run_token: str,
) -> tuple[str, str]:
    _assert_direct_lineage(
        value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        label="COVERAGE_PROOF_QUALITY",
    )
    if value.get("provider_calls") != 0:
        raise ValueError("COVERAGE_PROOF_QUALITY_PROVIDER_CALLS_NONZERO")
    if value.get("source_replay_hash") != replay_hash:
        raise ValueError("COVERAGE_PROOF_QUALITY_REPLAY_HASH_MISMATCH")
    if value.get("source_projection_hash") != projection_hash:
        raise ValueError("COVERAGE_PROOF_QUALITY_PROJECTION_HASH_MISMATCH")
    if value.get("exact_replay") is not True:
        raise ValueError("COVERAGE_PROOF_QUALITY_REPLAY_NOT_EXACT")
    mismatches = _sequence(
        value.get("mismatches", ()),
        label="COVERAGE_PROOF_QUALITY_MISMATCHES",
    )
    errors = _sequence(
        value.get("normalization_errors", ()),
        label="COVERAGE_PROOF_QUALITY_NORMALIZATION_ERRORS",
    )
    if mismatches or errors or value.get("null_to_zero_conversions", 0) not in (0, None):
        raise ValueError("COVERAGE_PROOF_QUALITY_INTEGRITY_INVALID")
    normalized_rows = _integer(
        value.get("normalized_rows"),
        label="COVERAGE_PROOF_QUALITY_NORMALIZED_ROWS",
    )
    if normalized_rows > projection_row_count:
        raise ValueError("COVERAGE_PROOF_QUALITY_ROW_COUNT_INVALID")
    before_hash = _required_sha256(
        value.get("before_hash"),
        label="COVERAGE_PROOF_QUALITY_BEFORE_HASH",
    )
    after_hash = _required_sha256(
        value.get("after_hash"),
        label="COVERAGE_PROOF_QUALITY_AFTER_HASH",
    )
    if before_hash != after_hash:
        raise ValueError("COVERAGE_PROOF_QUALITY_HASH_MISMATCH")
    return before_hash, after_hash


def _validate_gates(
    value: Mapping[str, object],
    *,
    source_code_revision: str,
    source_run_token: str,
) -> dict[str, str]:
    if set(value) != set(GATE_NAMES):
        raise ValueError("COVERAGE_PROOF_GATES_CONTRACT_INCOMPLETE")
    allowed_statuses = {item.value for item in GateStatus}
    output: dict[str, str] = {}
    for name in GATE_NAMES:
        gate = _mapping(value.get(name), label="COVERAGE_PROOF_GATE")
        _assert_direct_lineage(
            gate,
            source_code_revision=source_code_revision,
            source_run_token=source_run_token,
            label=f"COVERAGE_PROOF_GATE_{name}",
        )
        if gate.get("gate") != name:
            raise ValueError("COVERAGE_PROOF_GATE_NAME_MISMATCH")
        status = gate.get("status")
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError("COVERAGE_PROOF_GATE_STATUS_INVALID")
        output[name] = status
    return output


def _validate_report(
    value: Mapping[str, object],
    *,
    contract: CampaignContract,
    census: Mapping[str, object],
    replay: Mapping[str, object],
    quality: Mapping[str, object],
    gates: Mapping[str, object],
    source_code_revision: str,
    source_run_token: str,
) -> str:
    _assert_direct_lineage(
        value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        label="COVERAGE_PROOF_REPORT",
    )
    if value.get("schema_version") != "historical-deep-report-v1":
        raise ValueError("COVERAGE_PROOF_REPORT_SCHEMA_INVALID")
    if value.get("campaign_id") != contract.campaign_id:
        raise ValueError("COVERAGE_PROOF_REPORT_CAMPAIGN_MISMATCH")
    report_hash = _required_sha256(
        value.get("report_hash"),
        label="COVERAGE_PROOF_REPORT_HASH",
    )
    material = {
        key: item
        for key, item in value.items()
        if key not in {"report_hash", "durable_keys"}
    }
    if canonical_sha256(material) != report_hash:
        raise ValueError("COVERAGE_PROOF_REPORT_HASH_MISMATCH")
    if value.get("replay") != replay:
        raise ValueError("COVERAGE_PROOF_REPORT_REPLAY_MISMATCH")
    if value.get("quality_v2") != quality:
        raise ValueError("COVERAGE_PROOF_REPORT_QUALITY_MISMATCH")
    if value.get("gates") != gates:
        raise ValueError("COVERAGE_PROOF_REPORT_GATES_MISMATCH")
    operations = _mapping(
        value.get("operations"),
        label="COVERAGE_PROOF_REPORT_OPERATIONS",
    )
    if operations.get("coverage_census") != census:
        raise ValueError("COVERAGE_PROOF_REPORT_CENSUS_MISMATCH")
    safety = _mapping(
        value.get("safety"),
        label="COVERAGE_PROOF_REPORT_SAFETY",
    )
    expected_safety = {
        "cache_only": True,
        "provider_calls_during_replay_and_backtest": 0,
        "new_purchases": False,
        "secrets_exposed": False,
        "r2_deletions": 0,
        "raw_payloads_in_git": 0,
        "real_bets": False,
    }
    if any(safety.get(name) != expected for name, expected in expected_safety.items()):
        raise ValueError("COVERAGE_PROOF_REPORT_SAFETY_INVALID")
    return report_hash


def _gate_projection(
    family: str,
    gate_statuses: Mapping[str, str],
) -> tuple[str, str, str]:
    gate = _FAMILY_GATE.get(family)
    if gate is None:
        return "NOT_APPLICABLE", "NOT_ASSESSED", "NO_DEDICATED_GATE"
    status = gate_statuses.get(gate)
    if status is None:
        raise ValueError("COVERAGE_PROOF_GATE_MAPPING_MISSING")
    return gate, status, "LINEAGE_GLOBAL"


def _coverage_projection(
    *,
    contract: CampaignContract,
    census_cells: Mapping[tuple[int, int, str], CensusCell],
    normalized_cells: Mapping[tuple[int, int, str], NormalizedCell],
    gate_statuses: Mapping[str, str],
) -> list[dict[str, object]]:
    names, _canonical = _competition_maps(contract)
    keys = sorted(
        set(census_cells) | set(normalized_cells),
        key=lambda item: (names[item[0]], item[1], item[2]),
    )
    if len(keys) > MAX_COVERAGE_CELLS:
        raise ValueError("COVERAGE_PROOF_CELL_LIMIT_EXCEEDED")
    output: list[dict[str, object]] = []
    for league_id, season, family in keys:
        census = census_cells.get((league_id, season, family))
        normalized = normalized_cells.get((league_id, season, family))
        gate, gate_status, gate_scope = _gate_projection(family, gate_statuses)
        temporal_classes = (
            sorted(normalized.temporal_classes) if normalized is not None else []
        )
        output.append(
            {
                "league": names[league_id],
                "season": season,
                "family": family,
                "advertised_flag": (
                    census.advertised_flag if census is not None else None
                ),
                "sample_verified_numerator": (
                    census.numerator if census is not None else None
                ),
                "sample_verified_denominator": (
                    census.denominator if census is not None else None
                ),
                "sample_verified_rate": census.rate if census is not None else None,
                "sample_verified_basis": (
                    census.basis
                    if census is not None
                    else NO_CENSUS_EVIDENCE_SOURCE
                ),
                "normalized_row_count": normalized.count if normalized is not None else 0,
                "null_rate": census.null_rate if census is not None else None,
                "temporal_classes": temporal_classes,
                "gate": gate,
                "gate_status": gate_status,
                "gate_scope": gate_scope,
            }
        )
    return output


def _assert_no_forbidden_output_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name.casefold() in _FORBIDDEN_OUTPUT_FIELDS or name.casefold().endswith(
                "_key"
            ):
                raise ValueError(f"COVERAGE_PROOF_FORBIDDEN_OUTPUT_FIELD:{name}")
            _assert_no_forbidden_output_fields(item)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            _assert_no_forbidden_output_fields(item)


def _assert_output_allowlist(value: Mapping[str, object]) -> None:
    if set(value) != _ROOT_OUTPUT_FIELDS:
        raise ValueError("COVERAGE_PROOF_ROOT_OUTPUT_FIELDS_INVALID")
    quality = _mapping(value.get("quality"), label="COVERAGE_PROOF_OUTPUT_QUALITY")
    if set(quality) != _QUALITY_OUTPUT_FIELDS:
        raise ValueError("COVERAGE_PROOF_QUALITY_OUTPUT_FIELDS_INVALID")
    hashes = _mapping(
        value.get("source_hashes"),
        label="COVERAGE_PROOF_OUTPUT_SOURCE_HASHES",
    )
    if set(hashes) != _SOURCE_HASH_FIELDS:
        raise ValueError("COVERAGE_PROOF_SOURCE_HASH_OUTPUT_FIELDS_INVALID")
    for name, item in hashes.items():
        _required_sha256(item, label=f"COVERAGE_PROOF_OUTPUT_HASH_{name.upper()}")
    coverage = _sequence(
        value.get("coverage"),
        label="COVERAGE_PROOF_OUTPUT_COVERAGE",
    )
    if value.get("coverage_count") != len(coverage):
        raise ValueError("COVERAGE_PROOF_OUTPUT_COVERAGE_COUNT_MISMATCH")
    for item in coverage:
        cell = _mapping(item, label="COVERAGE_PROOF_OUTPUT_CELL")
        if set(cell) != set(_COVERAGE_OUTPUT_FIELDS):
            raise ValueError("COVERAGE_PROOF_CELL_OUTPUT_FIELDS_INVALID")
        basis = cell.get("sample_verified_basis")
        if _evidence_source(basis) != basis:
            raise ValueError("COVERAGE_PROOF_CELL_BASIS_INVALID")
    _assert_no_forbidden_output_fields(value)


def _assert_proof_hash(value: Mapping[str, object]) -> None:
    proof_hash = _required_sha256(
        value.get("proof_hash"),
        label="COVERAGE_PROOF_OUTPUT_PROOF_HASH",
    )
    material = {key: item for key, item in value.items() if key != "proof_hash"}
    if canonical_sha256(material) != proof_hash:
        raise ValueError("COVERAGE_PROOF_OUTPUT_PROOF_HASH_MISMATCH")


def assert_secret_free(
    data: bytes,
    *,
    secret_values: Iterable[str] = (),
) -> None:
    """Reject mounted credentials and common credential-shaped literals."""

    text = data.decode("utf-8")
    for secret in secret_values:
        if len(secret) >= 8 and secret in text:
            raise ValueError("COVERAGE_PROOF_SECRET_VALUE_DETECTED")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise ValueError("COVERAGE_PROOF_SECRET_PATTERN_DETECTED")


def _validate_revisions(
    *,
    source_code_revision: str,
    source_run_token: str,
    exporter_code_revision: str,
) -> None:
    if not _REVISION_PATTERN.fullmatch(source_code_revision):
        raise ValueError("COVERAGE_PROOF_SOURCE_CODE_REVISION_INVALID")
    if not _RUN_TOKEN_PATTERN.fullmatch(source_run_token):
        raise ValueError("COVERAGE_PROOF_SOURCE_RUN_TOKEN_INVALID")
    if not _REVISION_PATTERN.fullmatch(exporter_code_revision):
        raise ValueError("COVERAGE_PROOF_EXPORTER_CODE_REVISION_INVALID")


def build_coverage_proof(
    reader: DerivedObjectReader,
    *,
    contract: CampaignContract,
    source_code_revision: str,
    source_run_token: str,
    exporter_code_revision: str,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Build one sanitized proof without writing to R2 or retaining source rows."""

    _validate_revisions(
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
        exporter_code_revision=exporter_code_revision,
    )
    selected = {
        category: _select_lineage_envelope(
            reader,
            contract=contract,
            category=category,
            source_code_revision=source_code_revision,
            source_run_token=source_run_token,
        )
        for category in SOURCE_CATEGORIES
    }
    census_value = selected["collection/census"].value
    projection_value = selected["replay/projection"].value
    replay_value = selected["replay"].value
    quality_value = selected["quality"].value
    gates_value = selected["gates"].value
    report_value = selected["report"].value

    observations, census_hash = _validate_census(
        census_value,
        contract=contract,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    census = _census_cells(observations, contract=contract)
    normalized, projection_hash, projection_row_count = _validate_projection(
        projection_value,
        contract=contract,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    replay_source_hash, replay_hash = _validate_replay(
        replay_value,
        projection_hash=projection_hash,
        projection_row_count=projection_row_count,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    quality_before_hash, quality_after_hash = _validate_quality(
        quality_value,
        projection_hash=projection_hash,
        replay_hash=replay_hash,
        projection_row_count=projection_row_count,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    gate_statuses = _validate_gates(
        gates_value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    report_hash = _validate_report(
        report_value,
        contract=contract,
        census=census_value,
        replay=replay_value,
        quality=quality_value,
        gates=gates_value,
        source_code_revision=source_code_revision,
        source_run_token=source_run_token,
    )
    coverage = _coverage_projection(
        contract=contract,
        census_cells=census,
        normalized_cells=normalized,
        gate_statuses=gate_statuses,
    )
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("COVERAGE_PROOF_GENERATED_AT_NAIVE")
    body: dict[str, object] = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "campaign_id": contract.campaign_id,
        "contract_hash": contract.contract_hash,
        "source_code_revision": source_code_revision,
        "source_run_token": source_run_token,
        "exporter_code_revision": exporter_code_revision,
        "generated_at": timestamp.astimezone(UTC).isoformat(),
        "coverage_count": len(coverage),
        "normalized_row_count": projection_row_count,
        "quality": {
            "exact_replay": quality_value.get("exact_replay"),
            "hash_identical": replay_value.get("hash_identical"),
            "hash_mismatches": replay_value.get("hash_mismatches"),
            "missing_payloads": replay_value.get("missing_payloads"),
            "extra_payloads": replay_value.get("extra_payloads"),
            "provider_calls": replay_value.get("provider_calls"),
            "provider_credits": replay_value.get("provider_credits"),
        },
        "source_hashes": {
            "census": census_hash,
            "normalized_projection": projection_hash,
            "replay_source": replay_source_hash,
            "replay": replay_hash,
            "quality_before": quality_before_hash,
            "quality_after": quality_after_hash,
            "gates": canonical_sha256(gates_value),
            "report": report_hash,
            "census_envelope": selected["collection/census"].envelope_hash,
            "normalized_projection_envelope": selected[
                "replay/projection"
            ].envelope_hash,
            "replay_envelope": selected["replay"].envelope_hash,
            "quality_envelope": selected["quality"].envelope_hash,
            "gates_envelope": selected["gates"].envelope_hash,
            "report_envelope": selected["report"].envelope_hash,
        },
        "coverage": coverage,
    }
    body["proof_hash"] = canonical_sha256(body)
    _assert_output_allowlist(body)
    return body


def render_coverage_json(proof: Mapping[str, object]) -> bytes:
    _assert_output_allowlist(proof)
    _assert_proof_hash(proof)
    return (
        json.dumps(
            proof,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _csv_scalar(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        _assert_csv_text_safe(value)
        return value
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        items = [str(item) for item in value]
        for item in items:
            _assert_csv_text_safe(item)
        joined = "|".join(items)
        _assert_csv_text_safe(joined)
        return joined
    return value


def _assert_csv_text_safe(value: str) -> None:
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise ValueError("COVERAGE_PROOF_CSV_CONTROL_CHARACTER_INVALID")
    if value.lstrip().startswith(_CSV_FORMULA_PREFIXES):
        raise ValueError("COVERAGE_PROOF_CSV_FORMULA_PREFIX_INVALID")


def render_coverage_csv(proof: Mapping[str, object]) -> bytes:
    _assert_output_allowlist(proof)
    _assert_proof_hash(proof)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(_COVERAGE_OUTPUT_FIELDS),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    coverage = _sequence(
        proof.get("coverage"),
        label="COVERAGE_PROOF_OUTPUT_COVERAGE",
    )
    for item in coverage:
        cell = _mapping(item, label="COVERAGE_PROOF_OUTPUT_CELL")
        writer.writerow(
            {name: _csv_scalar(cell.get(name)) for name in _COVERAGE_OUTPUT_FIELDS}
        )
    return stream.getvalue().encode("utf-8")


def write_coverage_artifacts(
    proof: Mapping[str, object],
    *,
    output_directory: Path,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    secret_values: Iterable[str] = (),
) -> tuple[Path, Path]:
    if not 1_000 <= max_output_bytes <= 10_000_000:
        raise ValueError("COVERAGE_PROOF_OUTPUT_LIMIT_INVALID")
    json_bytes = render_coverage_json(proof)
    csv_bytes = render_coverage_csv(proof)
    if len(json_bytes) + len(csv_bytes) > max_output_bytes:
        raise ValueError("COVERAGE_PROOF_OUTPUT_TOO_LARGE")
    selected_secrets = tuple(secret_values)
    assert_secret_free(json_bytes, secret_values=selected_secrets)
    assert_secret_free(csv_bytes, secret_values=selected_secrets)
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "coverage-proof.json"
    csv_path = output_directory / "coverage-proof.csv"
    json_path.write_bytes(json_bytes)
    csv_path.write_bytes(csv_bytes)
    return json_path, csv_path


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DERIVED_PREFIX",
    "DerivedObjectReader",
    "DerivedR2ReadOnlyStore",
    "EXPORT_SCHEMA_VERSION",
    "NO_CENSUS_EVIDENCE_SOURCE",
    "assert_secret_free",
    "build_coverage_proof",
    "render_coverage_csv",
    "render_coverage_json",
    "write_coverage_artifacts",
]
