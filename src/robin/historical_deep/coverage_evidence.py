"""Pinned, read-only P0 coverage evidence ladder.

This module deliberately exposes no storage mutation, prefix discovery, provider,
SQL, or deployment surface. Its only external boundary is one exact S3-compatible
get-object method. The signed replay inventory is verified before its listed
receipt and payload keys become eligible for reads.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import unquote

from robin.historical.object_storage_migration import create_r2_client
from robin.historical_deep.contracts import build_task_id
from robin.historical_deep.normalization import (
    NormalizationError,
    canonical_json_bytes,
    canonical_sha256,
    normalize_payload,
)
from robin.historical_deep.replay import replay_stream_cache_only
from robin.historical_deep.segmented_replay import validate_inventory
from robin.historical_deep.storage import HarvestReceipt

INVENTORY_SCHEMA_VERSION = "historical-deep-replay-inventory-v2"
SELECTION_SCHEMA_VERSION = "p0-coverage-evidence-selection-v1"
PLAN_SCHEMA_VERSION = "p0-coverage-partition-plan-v1"
PARTITION_SCHEMA_VERSION = "p0-coverage-partition-receipt-v1"
FAMILY_COUNTS_SCHEMA_VERSION = "p0-coverage-family-counts-v2"
CHECKPOINT_SCHEMA_VERSION = "p0-coverage-partition-checkpoint-v1"
STAGE_SCHEMA_VERSION = "p0-coverage-stage-receipt-v1"
ALGORITHM_VERSION = "p0-coverage-evidence-algorithm-v2"
ABSENCE_CLASSIFICATION_RULE_VERSION = "absence-partition-rule-v2"
ABSENCE_PROFILE_SCHEMA_VERSION = "p0-absence-residual-profile-v1"
ABSENCE_NORMALIZATION_VERSION = "nfkc-casefold-whitespace-v1"
ABSENCE_SUPPLEMENT_SCHEMA_VERSION = "p0-absence-taxonomy-supplement-v1"
ABSENCE_SUPPLEMENT_REVIEWER_IDS = ("A1", "C2")
ABSENCE_UNKNOWN_EXACT_VALUES = (
    "n/a",
    "not available",
    "unknown",
)
ABSENCE_NONMEDICAL_KNOWN_VALUES = (
    "personal reason",
    "personal reasons",
)
CANONICAL_JOURNAL_BOUNDARY_ID = "RCV3-20260812-137"
CANONICAL_JOURNAL_BOUNDARY_HASH = (
    "da9a13824573dcb7b02675df62332da430f28963d8c9c70c92f580f87555fe38"
)
CANONICAL_JOURNAL_PREFIX_COUNT = 129
CANONICAL_JOURNAL_PREFIX_TIP_HASH = (
    "a882c44b09abba2c28c76411c52ea5e80abe9958dfb6e86a02242fef19ff344f"
)
CANONICAL_JOURNAL_RECORD_TYPES = frozenset(
    {
        "MISSION_AUTHORIZED",
        "STAGE_STARTED",
        "STAGE_FINISHED",
        "DECISION",
        "FAILURE",
        "VETO",
        "REDESIGN",
    }
)
CANONICAL_JOURNAL_DECISIONS = frozenset(
    {
        "PASS_AND_SCALE",
        "PASS_AND_HOLD",
        "FAIL_AND_REDESIGN",
        "FAIL_AND_STOP",
        "BLOCKED_EXTERNAL_ACTION",
    }
)
ABSENCE_CLASSIFICATION_FRAMEWORK = {
    "version": ABSENCE_CLASSIFICATION_RULE_VERSION,
    "base_lexical_contract_version": "absence-partition-rule-v1",
    "categories": [
        "INJURY",
        "SUSPENSION",
        "UNCLASSIFIABLE",
    ],
    "normalization": {
        "version": ABSENCE_NORMALIZATION_VERSION,
        "operations": ["NFKC", "CASEFOLD", "TRIM", "CONDENSE_WHITESPACE"],
        "accent_removal": False,
        "fuzzy_matching": False,
        "maximum_codepoints_per_field": 256,
    },
    "nonmedical_absence_policy": {
        "known_values": list(ABSENCE_NONMEDICAL_KNOWN_VALUES),
        "category": "UNCLASSIFIABLE",
        "reason": "OUTSIDE_SIGNED_THREE_WAY_PARTITION",
    },
    "explicit_unknown_policy": {
        "known_values": list(ABSENCE_UNKNOWN_EXACT_VALUES),
        "category": "UNCLASSIFIABLE",
        "precedence": "BEFORE_LEXICAL_SIGNALS",
    },
    "provider_placeholder_policy": {
        "known_values": ["missing fixture"],
        "alone": "UNCLASSIFIABLE",
        "with_one_closed_lexical_signal": "USE_CLOSED_SIGNAL",
    },
    "execution_authority": {
        "classification_source": "VERIFIED_RAW_PAYLOAD_RECORD_HASHES",
        "legacy_normalizer_role": "INTERMEDIATE_ROWS_ONLY_REASSIGNED_BY_RAW_HASH",
        "legacy_denominator_oracle_role": "DEFINITION_TEST_ONLY_NOT_EXECUTION",
    },
    "conflict_policy": "UNCLASSIFIABLE",
    "unknown_policy": "UNCLASSIFIABLE",
    "supplement_policy": {
        "source": "SIGNED_SLOT_ONE_RESIDUAL_PROFILE",
        "reviewers_required": 2,
        "reviewer_ids": list(ABSENCE_SUPPLEMENT_REVIEWER_IDS),
        "attestation_model": "ROLE_BOUND_CONTENT_ADDRESSING_UNDER_GIT_REVIEW",
        "local_adjudications_authoritative": False,
        "allowed_result": "UNCLASSIFIABLE",
        "promotion_categories": [],
        "promotion_requires": "NEW_FRAMEWORK_ARCHITECTURE_AND_NEW_MISSION_IF_LIMIT_REACHED",
        "all_signatures_adjudicated": True,
        "disagreement_result": "UNCLASSIFIABLE",
        "third_unchanged_attempt": "FAIL_AND_STOP",
    },
}
ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256 = canonical_sha256(
    ABSENCE_CLASSIFICATION_FRAMEWORK
)
MISSION_ACCOUNTING_EXACT = "EXACT_OBSERVED"
MISSION_ACCOUNTING_CONSERVATIVE = "CONSERVATIVE_FULL_ATTEMPT_CHARGE"
MISSION_ACCOUNTING_BASELINE_SCHEMA = "p0-coverage-mission-accounting-baseline-v1"

SOURCE_CONFIG_PATH = Path("configs/data/p0-coverage-source-config-v1.json")
MISSION_PATH = Path("configs/data/p0-coverage-evidence-mission-v1.json")
MAPPING_PATH = Path("configs/data/coverage-scale-pack-manifests-v2.json")
HISTORICAL_AUTHORITY_MATRIX_PATH = Path(
    "configs/agents/mission-activation-matrix-v3.json"
)
HISTORICAL_AUTHORITY_MATRIX_SNAPSHOT_PATH = Path(
    "configs/data/p0-coverage-authority-matrix-snapshot-v1.json"
)
HISTORICAL_AUTHORITY_MATRIX_SHA256 = (
    "52306f04d9e751b8bf32ffff6f6517e5b090754ef789a59276ac75af30d64266"
)
HISTORICAL_SOURCE_CONFIG_SHA256 = (
    "52fb07c0549458a04b5253a1171c3e87c6837bef78ad20279257c2a04011d82e"
)
HISTORICAL_MISSION_SHA256 = (
    "d3c9df38ca02a4d7d5feaa0d1561541c26ea6313fb8755d04de5690367c6262f"
)
HISTORICAL_MAPPING_SHA256 = (
    "d702b88c964d64d984cc69d2b297f37fbb74f087347934f8d3eee7a22597409f"
)

DOMAIN_STAGES = ("E1A", "E1B", "E2", "E3A", "E3B", "E4")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9._~%:-]+$")
COMPETITION = re.compile(r"^api-football:[1-9][0-9]*$")
NAMESPACE_PARTS = ("historical-deep-data", "schema-v1")

INVENTORY_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "continuation_id",
        "continuation_of",
        "run_purpose",
        "code_revision",
        "partition_key",
        "limits",
        "objects_expected",
        "logical_bytes",
        "stored_bytes",
        "segments_expected",
        "objects",
        "segments",
        "provider_calls",
        "manifest_sha256",
    }
)
INVENTORY_OBJECT_FIELDS = frozenset(
    {
        "object_id",
        "receipt_id",
        "receipt_hash",
        "receipt_key",
        "payload_key",
        "payload_sha256",
        "stored_sha256",
        "logical_bytes",
        "stored_bytes",
        "competition",
        "season",
        "family",
        "task_id",
        "provider_calls",
        "rows_received",
    }
)
INVENTORY_SEGMENT_FIELDS = frozenset(
    {
        "competition",
        "season",
        "family",
        "segment",
        "object_ids",
        "segment_id",
        "object_count",
        "logical_bytes",
        "estimated_seconds",
        "oversized_single_object",
    }
)

FAMILY_GROUPS = {
    "CORE_FIXTURE_IDENTITY": (
        "fixtures",
        "teams",
        "venues",
        "referees",
    ),
    "MATCH_EVENTS_TEAM": (
        "events",
        "rounds",
        "team_match_statistics",
        "standings",
    ),
    "LINEUP_PLAYER_MATCH": (
        "lineups",
        "lineup_players",
        "formations",
        "player_match_statistics",
    ),
    "SEASON_ABSENCE": (
        "players",
        "player_season_statistics",
        "injuries",
        "suspensions",
    ),
}
RAW_FAMILIES_BY_GROUP = {
    "CORE_FIXTURE_IDENTITY": frozenset({"fixtures"}),
    "MATCH_EVENTS_TEAM": frozenset({"fixtures", "events", "rounds", "standings"}),
    "LINEUP_PLAYER_MATCH": frozenset({"fixtures"}),
    "SEASON_ABSENCE": frozenset({"players", "injuries"}),
}
FIXTURE_SCOPED_FAMILIES = frozenset(
    {
        "fixtures",
        "events",
        "lineups",
        "lineup_players",
        "formations",
        "team_match_statistics",
        "player_match_statistics",
        "referees",
        "venues",
        "teams",
    }
)
DEEP_FIXTURE_FAMILIES = frozenset(
    {
        "events",
        "lineups",
        "lineup_players",
        "formations",
        "team_match_statistics",
        "player_match_statistics",
    }
)
FIXTURE_CENSUS_DEPENDENT_FAMILIES = (
    frozenset(
        {
            "fixtures",
            "teams",
            "venues",
            "referees",
            "rounds",
            "standings",
        }
    )
    | DEEP_FIXTURE_FAMILIES
)
FAMILY_SOURCE_BINDINGS = {
    "fixtures": ("fixtures", "fixtures"),
    "teams": ("fixtures", "fixtures"),
    "venues": ("fixtures", "fixtures"),
    "referees": ("fixtures", "fixtures"),
    "events": ("events", "fixtures/events"),
    "lineups": ("fixtures", "fixtures/lineups"),
    "lineup_players": ("fixtures", "fixtures/lineups"),
    "formations": ("fixtures", "fixtures/lineups"),
    "team_match_statistics": ("fixtures", "fixtures/statistics"),
    "player_match_statistics": ("fixtures", "fixtures/players"),
    "rounds": ("rounds", "fixtures/rounds"),
    "standings": ("standings", "standings"),
    "players": ("players", "players"),
    "player_season_statistics": ("players", "players"),
    "injuries": ("injuries", "injuries"),
    "suspensions": ("injuries", "injuries"),
}
ZERO_EFFECTS = {
    "provider_calls": 0,
    "provider_credits": 0,
    "r2_writes": 0,
    "r2_deletes": 0,
    "remote_sql_reads": 0,
    "remote_sql_writes": 0,
    "deployments": 0,
    "purchases": 0,
    "odds_credits": 0,
    "real_bets": 0,
    "promotion": False,
    "publication": False,
}


class R2GetObjectClient(Protocol):
    """The complete external object-store surface permitted to this module."""

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class AccessLimits:
    bootstrap_gets: int
    bootstrap_compressed_bytes: int
    bootstrap_decompressed_bytes: int
    gets_per_job: int
    stored_bytes_per_job: int
    logical_bytes_per_job: int
    mission_gets: int


@dataclass(frozen=True, slots=True)
class InventoryObject:
    object_id: str
    receipt_id: str
    receipt_hash: str
    receipt_key: str
    payload_key: str
    payload_sha256: str
    stored_sha256: str
    logical_bytes: int
    stored_bytes: int
    competition: str
    season: int
    family: str
    task_id: str
    provider_calls: int
    rows_received: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class InventorySegment:
    competition: str
    season: int
    family: str
    segment: int
    object_ids: tuple[str, ...]
    segment_id: str
    object_count: int
    logical_bytes: int
    estimated_seconds: float
    oversized_single_object: bool


@dataclass(frozen=True, slots=True)
class VerifiedInventory:
    manifest_sha256: str
    code_revision: str
    objects: tuple[InventoryObject, ...]
    segments: tuple[InventorySegment, ...]

    @property
    def by_id(self) -> dict[str, InventoryObject]:
        return {item.object_id: item for item in self.objects}


@dataclass(frozen=True, slots=True)
class VerifiedEvidencePair:
    entry: InventoryObject
    receipt: HarvestReceipt
    payload: object
    normalized: Mapping[str, tuple[Mapping[str, object], ...]]
    replay_source_hash: str
    replay_hash: str


@dataclass(slots=True)
class ReadTelemetry:
    bootstrap_requested: int = 0
    bootstrap_succeeded: int = 0
    bootstrap_failed: int = 0
    receipt_requested: int = 0
    receipt_succeeded: int = 0
    receipt_failed: int = 0
    payload_requested: int = 0
    payload_succeeded: int = 0
    payload_failed: int = 0
    bootstrap_stored_bytes: int = 0
    bootstrap_logical_bytes: int = 0
    receipt_bytes: int = 0
    payload_stored_bytes: int = 0
    payload_logical_bytes: int = 0
    pairs_verified: int = 0
    peak_pair_bytes: int = 0

    @property
    def evidence_gets(self) -> int:
        return self.receipt_requested + self.payload_requested

    @property
    def evidence_stored_bytes(self) -> int:
        return self.receipt_bytes + self.payload_stored_bytes

    def as_dict(self) -> dict[str, object]:
        return {
            "logical_gets": {
                "bootstrap": {
                    "requested": self.bootstrap_requested,
                    "succeeded": self.bootstrap_succeeded,
                    "failed": self.bootstrap_failed,
                },
                "receipt": {
                    "requested": self.receipt_requested,
                    "succeeded": self.receipt_succeeded,
                    "failed": self.receipt_failed,
                },
                "payload": {
                    "requested": self.payload_requested,
                    "succeeded": self.payload_succeeded,
                    "failed": self.payload_failed,
                },
                "evidence_total": self.evidence_gets,
                "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
            },
            "bytes": {
                "bootstrap_stored": self.bootstrap_stored_bytes,
                "bootstrap_logical": self.bootstrap_logical_bytes,
                "receipt": self.receipt_bytes,
                "payload_stored": self.payload_stored_bytes,
                "payload_logical": self.payload_logical_bytes,
                "peak_pair": self.peak_pair_bytes,
            },
            "pairs_verified": self.pairs_verified,
            "quota": "UNKNOWN_NOT_OBSERVED",
            "monetary_cost": "UNKNOWN_NOT_OBSERVED",
            "effects": dict(ZERO_EFFECTS),
        }


@dataclass(frozen=True, slots=True)
class CoverageAuthority:
    root: Path
    source_config: Mapping[str, object]
    mission: Mapping[str, object]
    mapping: Mapping[str, object]
    source_config_sha256: str
    mission_sha256: str
    mapping_sha256: str
    stage: str
    council_stage: str
    competitions: tuple[str, ...]
    seasons: tuple[int, ...]
    normalized_families: tuple[str, ...]
    raw_families: tuple[str, ...]
    identity_architecture_hash: str
    absence_suspension_regex: str
    absence_injury_regex: str
    limits: AccessLimits


def evidence_architecture_fingerprint(authority: CoverageAuthority) -> str:
    return canonical_sha256(
        {
            "algorithm_version": ALGORITHM_VERSION,
            "absence_classification_framework_sha256": (
                ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
            ),
            "identity_architecture_hash": authority.identity_architecture_hash,
        }
    )


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}_MUST_BE_A_MAPPING")
    return value


def canonical_journal_suffix(root: Path) -> tuple[Mapping[str, object], ...]:
    """Validate the immutable legacy prefix and return only canonical authority."""

    path = root / "reports/council/decision-ledger.jsonl"
    records: list[Mapping[str, object]] = []
    previous_hash = "0" * 64
    boundary_index: int | None = None
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("COUNCIL_JOURNAL_DUPLICATE_KEY")
            value[key] = item
        return value

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            decoded = json.loads(
                line,
                object_pairs_hook=object_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"COUNCIL_JOURNAL_NONFINITE:{value}")
                ),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("COUNCIL_JOURNAL_JSON_INVALID") from exc
        record = _mapping(decoded, label="COUNCIL_JOURNAL_RECORD")
        if record.get("previous_hash") != previous_hash:
            raise ValueError("COUNCIL_JOURNAL_PREVIOUS_HASH_INVALID")
        if record.get("hash_algorithm") != "SHA-256":
            raise ValueError("COUNCIL_JOURNAL_HASH_ALGORITHM_INVALID")
        canonical = json.dumps(
            {key: item for key, item in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        observed_hash = record.get("hash")
        if not isinstance(observed_hash, str) or hashlib.sha256(canonical).hexdigest() != observed_hash:
            raise ValueError("COUNCIL_JOURNAL_RECORD_HASH_INVALID")
        records.append(record)
        previous_hash = observed_hash
        if record.get("decision_id") == CANONICAL_JOURNAL_BOUNDARY_ID:
            if boundary_index is not None:
                raise ValueError("COUNCIL_JOURNAL_BOUNDARY_DUPLICATE")
            boundary_index = len(records) - 1
            if (
                boundary_index != CANONICAL_JOURNAL_PREFIX_COUNT
                or record.get("previous_hash") != CANONICAL_JOURNAL_PREFIX_TIP_HASH
                or observed_hash != CANONICAL_JOURNAL_BOUNDARY_HASH
            ):
                raise ValueError("COUNCIL_JOURNAL_BOUNDARY_INVALID")

    if boundary_index is None:
        raise ValueError("COUNCIL_JOURNAL_BOUNDARY_MISSING")
    suffix = records[boundary_index:]
    if any(
        record.get("record_type") not in CANONICAL_JOURNAL_RECORD_TYPES
        or record.get("decision") not in CANONICAL_JOURNAL_DECISIONS
        for record in suffix
    ):
        raise ValueError("COUNCIL_JOURNAL_CANONICAL_SUFFIX_INVALID")
    return tuple(suffix)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    raise ValueError(f"{label}_MUST_BE_A_SEQUENCE")


def _integer(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label}_INTEGER_INVALID")
    return value


def _number(value: object, *, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}_NUMBER_INVALID")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < minimum:
        raise ValueError(f"{label}_NUMBER_INVALID")
    return parsed


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}_TEXT_INVALID")
    return value


def _sha(value: object, *, label: str) -> str:
    parsed = _text(value, label=label)
    if HEX64.fullmatch(parsed) is None:
        raise ValueError(f"{label}_SHA256_INVALID")
    return parsed


def _json_no_duplicates(raw: bytes, *, label: str) -> object:
    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"{label}_DUPLICATE_JSON_KEY")
            output[key] = value
        return output

    def reject_constant(_value: str) -> None:
        raise ValueError(f"{label}_NON_FINITE_JSON")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_JSON_INVALID") from error


def _bounded_gzip(data: bytes, *, limit: int, label: str) -> bytes:
    if len(data) < 2 or data[:2] != b"\x1f\x8b":
        raise ValueError(f"{label}_GZIP_REQUIRED")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            logical = stream.read(limit + 1)
    except (EOFError, OSError) as error:
        raise ValueError(f"{label}_GZIP_INVALID") from error
    if len(logical) > limit:
        raise ValueError(f"{label}_LOGICAL_SIZE_LIMIT_EXCEEDED")
    return logical


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _historical_contract_hash_matches(
    root: Path,
    *,
    relative: Path,
    expected: str,
    source_sha: str,
    mission_sha: str,
    mapping_sha: str,
) -> bool:
    """Resolve only the one content-addressed authority snapshot frozen by P0 v1."""

    current = root / relative
    if current.is_file() and _lf_sha256(current) == expected:
        return True
    historical_tuple = (
        relative == HISTORICAL_AUTHORITY_MATRIX_PATH
        and expected == HISTORICAL_AUTHORITY_MATRIX_SHA256
        and source_sha == HISTORICAL_SOURCE_CONFIG_SHA256
        and mission_sha == HISTORICAL_MISSION_SHA256
        and mapping_sha == HISTORICAL_MAPPING_SHA256
    )
    snapshot = root / HISTORICAL_AUTHORITY_MATRIX_SNAPSHOT_PATH
    return bool(
        historical_tuple
        and snapshot.is_file()
        and _lf_sha256(snapshot) == HISTORICAL_AUTHORITY_MATRIX_SHA256
    )


def _signed(value: Mapping[str, object], *, field: str) -> dict[str, object]:
    if field in value:
        raise ValueError("P0_SIGNATURE_FIELD_RESERVED")
    result = dict(value)
    result[field] = canonical_sha256(value)
    return result


def _verify_signed(value: Mapping[str, object], *, field: str, label: str) -> str:
    signature = _sha(value.get(field), label=f"{label}_{field}")
    unsigned = {key: item for key, item in value.items() if key != field}
    if canonical_sha256(unsigned) != signature:
        raise ValueError(f"{label}_SIGNATURE_MISMATCH")
    return signature


def _inventory_key_parts(
    key: str,
    *,
    item: Mapping[str, object],
    payload: bool,
) -> None:
    if "\\" in key or any(ord(character) < 32 for character in key):
        raise ValueError("P0_INVENTORY_KEY_CONTROL_INVALID")
    parts = key.split("/")
    if len(parts) != 8 or tuple(parts[:2]) != NAMESPACE_PARTS:
        raise ValueError("P0_INVENTORY_KEY_NAMESPACE_INVALID")
    expected = (
        f"competition={item['competition']}",
        f"season={item['season']}",
        f"family={item['family']}",
    )
    if tuple(parts[2:5]) != expected:
        raise ValueError("P0_INVENTORY_KEY_DIMENSION_MISMATCH")
    if (
        not parts[5].startswith("endpoint=")
        or SAFE_KEY_SEGMENT.fullmatch(parts[5][len("endpoint=") :]) is None
    ):
        raise ValueError("P0_INVENTORY_KEY_ENDPOINT_INVALID")
    if parts[6] != f"task={item['task_id']}":
        raise ValueError("P0_INVENTORY_KEY_TASK_MISMATCH")
    expected_name = f"payload-{item['payload_sha256']}.json.gz" if payload else "receipt.json"
    if parts[7] != expected_name:
        raise ValueError("P0_INVENTORY_KEY_SUFFIX_INVALID")


def _inventory_object(value: object) -> InventoryObject:
    item = _mapping(value, label="P0_INVENTORY_OBJECT")
    if set(item) != INVENTORY_OBJECT_FIELDS:
        raise ValueError("P0_INVENTORY_OBJECT_FIELDS_INVALID")
    parsed = InventoryObject(
        object_id=_sha(item.get("object_id"), label="P0_OBJECT_ID"),
        receipt_id=_sha(item.get("receipt_id"), label="P0_RECEIPT_ID"),
        receipt_hash=_sha(item.get("receipt_hash"), label="P0_RECEIPT_HASH"),
        receipt_key=_text(item.get("receipt_key"), label="P0_RECEIPT_KEY"),
        payload_key=_text(item.get("payload_key"), label="P0_PAYLOAD_KEY"),
        payload_sha256=_sha(item.get("payload_sha256"), label="P0_PAYLOAD_HASH"),
        stored_sha256=_sha(item.get("stored_sha256"), label="P0_STORED_HASH"),
        logical_bytes=_integer(item.get("logical_bytes"), label="P0_LOGICAL_BYTES", minimum=0),
        stored_bytes=_integer(item.get("stored_bytes"), label="P0_STORED_BYTES", minimum=1),
        competition=_text(item.get("competition"), label="P0_COMPETITION"),
        season=_integer(item.get("season"), label="P0_SEASON", minimum=1888),
        family=_text(item.get("family"), label="P0_RAW_FAMILY"),
        task_id=_sha(item.get("task_id"), label="P0_TASK_ID"),
        provider_calls=_integer(
            item.get("provider_calls"),
            label="P0_HISTORICAL_PROVIDER_CALLS",
            minimum=1,
        ),
        rows_received=_integer(item.get("rows_received"), label="P0_ROWS_RECEIVED", minimum=0),
    )
    if parsed.receipt_id != parsed.task_id:
        raise ValueError("P0_INVENTORY_RECEIPT_TASK_MISMATCH")
    if COMPETITION.fullmatch(parsed.competition) is None or parsed.season > 2100:
        raise ValueError("P0_INVENTORY_SCOPE_ID_INVALID")
    _inventory_key_parts(parsed.receipt_key, item=item, payload=False)
    _inventory_key_parts(parsed.payload_key, item=item, payload=True)
    if parsed.receipt_key.rsplit("/", 1)[0] != parsed.payload_key.rsplit("/", 1)[0]:
        raise ValueError("P0_INVENTORY_PAIR_PREFIX_MISMATCH")
    expected_id = canonical_sha256(
        {
            "receipt_key": parsed.receipt_key,
            "receipt_hash": parsed.receipt_hash,
            "payload_key": parsed.payload_key,
            "payload_sha256": parsed.payload_sha256,
        }
    )
    if parsed.object_id != expected_id:
        raise ValueError("P0_INVENTORY_OBJECT_ID_MISMATCH")
    return parsed


def deep_validate_inventory(
    value: Mapping[str, object],
    *,
    source_config: Mapping[str, object],
) -> VerifiedInventory:
    """Validate the signed durable inventory beyond its root signature."""

    if set(value) != INVENTORY_ROOT_FIELDS:
        raise ValueError("P0_INVENTORY_ROOT_FIELDS_INVALID")
    if value.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise ValueError("P0_INVENTORY_SCHEMA_INVALID")
    signature = validate_inventory(value)
    pin = _mapping(source_config.get("inventory"), label="P0_SOURCE_INVENTORY_PIN")
    if signature != _sha(pin.get("manifest_sha256"), label="P0_PINNED_INVENTORY"):
        raise ValueError("P0_INVENTORY_PIN_MISMATCH")
    exact_root = {
        "continuation_id": "continuation_id",
        "continuation_of": "continuation_of",
        "run_purpose": "run_purpose",
        "code_revision": "code_revision",
        "objects_expected": "objects_expected",
        "segments_expected": "segments_expected",
        "logical_bytes": "logical_bytes",
        "stored_bytes": "stored_bytes",
    }
    for root_field, pin_field in exact_root.items():
        if value.get(root_field) != pin.get(pin_field):
            raise ValueError(f"P0_INVENTORY_PINNED_{root_field.upper()}_MISMATCH")
    if value.get("partition_key") != [
        "competition",
        "season",
        "family",
        "segment",
    ]:
        raise ValueError("P0_INVENTORY_PARTITION_KEY_INVALID")
    if value.get("provider_calls") != 0:
        raise ValueError("P0_INVENTORY_BUILD_PROVIDER_CALLS_NONZERO")

    source_scope = _mapping(source_config.get("scope"), label="P0_SOURCE_SCOPE")
    pinned_competitions = {
        _text(
            _mapping(item, label="P0_COMPETITION_PIN").get("canonical_key"),
            label="P0_COMPETITION_PIN",
        )
        for item in _sequence(source_scope.get("competitions"), label="P0_COMPETITION_PINS")
    }
    pinned_raw_families = {
        _text(item, label="P0_RAW_FAMILY_PIN")
        for item in _sequence(
            source_scope.get("raw_inventory_families"),
            label="P0_RAW_FAMILY_PINS",
        )
    }
    objects = tuple(
        _inventory_object(item)
        for item in _sequence(value.get("objects"), label="P0_INVENTORY_OBJECTS")
    )
    if len(objects) != _integer(
        value.get("objects_expected"), label="P0_OBJECTS_EXPECTED", minimum=1
    ):
        raise ValueError("P0_INVENTORY_OBJECT_COUNT_MISMATCH")
    expected_order = tuple(
        sorted(
            objects,
            key=lambda item: (
                item.competition,
                item.season,
                item.family,
                item.payload_key,
                item.receipt_id,
            ),
        )
    )
    if objects != expected_order:
        raise ValueError("P0_INVENTORY_OBJECT_ORDER_INVALID")
    if any(
        item.competition not in pinned_competitions or item.family not in pinned_raw_families
        for item in objects
    ):
        raise ValueError("P0_INVENTORY_OBJECT_OUTSIDE_PINNED_CAMPAIGN")
    for attribute in ("object_id", "task_id", "receipt_key", "payload_key"):
        values = [getattr(item, attribute) for item in objects]
        if len(values) != len(set(values)):
            raise ValueError(f"P0_INVENTORY_DUPLICATE_{attribute.upper()}")
    if sum(item.logical_bytes for item in objects) != _integer(
        value.get("logical_bytes"), label="P0_INVENTORY_LOGICAL_BYTES"
    ):
        raise ValueError("P0_INVENTORY_LOGICAL_BYTES_MISMATCH")
    if sum(item.stored_bytes for item in objects) != _integer(
        value.get("stored_bytes"), label="P0_INVENTORY_STORED_BYTES"
    ):
        raise ValueError("P0_INVENTORY_STORED_BYTES_MISMATCH")

    limits = _mapping(value.get("limits"), label="P0_INVENTORY_LIMITS")
    if set(limits) != {
        "objects",
        "logical_bytes",
        "estimated_seconds",
        "checkpoint_objects",
        "checkpoint_seconds",
    }:
        raise ValueError("P0_INVENTORY_LIMIT_FIELDS_INVALID")
    max_objects = _integer(limits.get("objects"), label="P0_SEGMENT_MAX_OBJECTS", minimum=1)
    max_logical = _integer(
        limits.get("logical_bytes"),
        label="P0_SEGMENT_MAX_LOGICAL_BYTES",
        minimum=1,
    )
    max_seconds = _number(
        limits.get("estimated_seconds"),
        label="P0_SEGMENT_MAX_SECONDS",
        minimum=0.001,
    )
    _integer(
        limits.get("checkpoint_objects"),
        label="P0_CHECKPOINT_OBJECTS",
        minimum=1,
    )
    checkpoint_seconds = _number(
        limits.get("checkpoint_seconds"),
        label="P0_CHECKPOINT_SECONDS",
        minimum=0.001,
    )
    if checkpoint_seconds > 300.0:
        raise ValueError("P0_INVENTORY_CHECKPOINT_LIMIT_INVALID")
    object_index = {item.object_id: item for item in objects}
    seen_object_ids: set[str] = set()
    seen_segment_ids: set[str] = set()
    partition_ordinals: dict[tuple[str, int, str], int] = defaultdict(int)
    segments: list[InventorySegment] = []
    raw_segments = _sequence(value.get("segments"), label="P0_INVENTORY_SEGMENTS")
    for global_ordinal, raw_segment in enumerate(raw_segments, start=1):
        segment = _mapping(raw_segment, label="P0_INVENTORY_SEGMENT")
        if set(segment) != INVENTORY_SEGMENT_FIELDS:
            raise ValueError("P0_INVENTORY_SEGMENT_FIELDS_INVALID")
        competition = _text(segment.get("competition"), label="P0_SEGMENT_COMPETITION")
        season = _integer(segment.get("season"), label="P0_SEGMENT_SEASON", minimum=1888)
        family = _text(segment.get("family"), label="P0_SEGMENT_FAMILY")
        partition = (competition, season, family)
        partition_ordinals[partition] += 1
        local_ordinal = _integer(segment.get("segment"), label="P0_SEGMENT_ORDINAL", minimum=1)
        if local_ordinal != partition_ordinals[partition]:
            raise ValueError("P0_INVENTORY_SEGMENT_PARTITION_ORDER_INVALID")
        object_ids = tuple(
            _sha(item, label="P0_SEGMENT_OBJECT_ID")
            for item in _sequence(segment.get("object_ids"), label="P0_SEGMENT_OBJECT_IDS")
        )
        if not object_ids or len(object_ids) != len(set(object_ids)):
            raise ValueError("P0_INVENTORY_SEGMENT_OBJECT_IDS_INVALID")
        if seen_object_ids.intersection(object_ids):
            raise ValueError("P0_INVENTORY_SEGMENT_OBJECT_DUPLICATED")
        try:
            members = tuple(object_index[object_id] for object_id in object_ids)
        except KeyError as error:
            raise ValueError("P0_INVENTORY_SEGMENT_OBJECT_UNKNOWN") from error
        if any((item.competition, item.season, item.family) != partition for item in members):
            raise ValueError("P0_INVENTORY_SEGMENT_PARTITION_MISMATCH")
        object_count = _integer(
            segment.get("object_count"), label="P0_SEGMENT_OBJECT_COUNT", minimum=1
        )
        logical_bytes = _integer(
            segment.get("logical_bytes"),
            label="P0_SEGMENT_LOGICAL_BYTES",
            minimum=0,
        )
        estimated_seconds = _number(
            segment.get("estimated_seconds"),
            label="P0_SEGMENT_ESTIMATED_SECONDS",
        )
        oversized = segment.get("oversized_single_object")
        if not isinstance(oversized, bool):
            raise ValueError("P0_SEGMENT_OVERSIZED_FLAG_INVALID")
        if object_count != len(object_ids) or logical_bytes != sum(
            item.logical_bytes for item in members
        ):
            raise ValueError("P0_INVENTORY_SEGMENT_AGGREGATE_MISMATCH")
        expected_oversized = len(members) == 1 and (
            logical_bytes > max_logical or estimated_seconds > max_seconds
        )
        if oversized is not expected_oversized:
            raise ValueError("P0_INVENTORY_SEGMENT_OVERSIZED_FLAG_MISMATCH")
        if len(members) > 1 and (
            object_count > max_objects
            or logical_bytes > max_logical
            or estimated_seconds > max_seconds
        ):
            raise ValueError("P0_INVENTORY_SEGMENT_LIMIT_EXCEEDED")
        identity = {
            "competition": competition,
            "season": season,
            "family": family,
            "segment": local_ordinal,
            "object_ids": list(object_ids),
        }
        expected_segment_id = f"seg-{global_ordinal:06d}-{canonical_sha256(identity)[:16]}"
        segment_id = _text(segment.get("segment_id"), label="P0_SEGMENT_ID")
        if segment_id != expected_segment_id or segment_id in seen_segment_ids:
            raise ValueError("P0_INVENTORY_SEGMENT_ID_INVALID")
        seen_object_ids.update(object_ids)
        seen_segment_ids.add(segment_id)
        segments.append(
            InventorySegment(
                competition=competition,
                season=season,
                family=family,
                segment=local_ordinal,
                object_ids=object_ids,
                segment_id=segment_id,
                object_count=object_count,
                logical_bytes=logical_bytes,
                estimated_seconds=estimated_seconds,
                oversized_single_object=oversized,
            )
        )
    if len(segments) != _integer(
        value.get("segments_expected"), label="P0_SEGMENTS_EXPECTED", minimum=1
    ):
        raise ValueError("P0_INVENTORY_SEGMENT_COUNT_MISMATCH")
    if seen_object_ids != set(object_index):
        raise ValueError("P0_INVENTORY_SEGMENT_COVERAGE_MISMATCH")
    return VerifiedInventory(
        manifest_sha256=signature,
        code_revision=_text(value.get("code_revision"), label="P0_INVENTORY_CODE_REVISION"),
        objects=objects,
        segments=tuple(segments),
    )


class PinnedInventoryReader:
    """Stateful exact-key reader backed by one verified inventory."""

    _RECEIPT_LIMIT = 262_144

    def __init__(
        self,
        client: R2GetObjectClient,
        *,
        bucket: str,
        source_config: Mapping[str, object],
    ) -> None:
        if not bucket:
            raise ValueError("P0_R2_BUCKET_REQUIRED")
        policy = _mapping(source_config.get("access_policy"), label="P0_ACCESS_POLICY")
        inventory_pin = _mapping(source_config.get("inventory"), label="P0_INVENTORY_PIN")
        bootstrap_keys = tuple(
            _text(item, label="P0_BOOTSTRAP_KEY")
            for item in _sequence(policy.get("bootstrap_exact_keys"), label="P0_BOOTSTRAP_KEYS")
        )
        durable_key = _text(inventory_pin.get("durable_key"), label="P0_INVENTORY_DURABLE_KEY")
        if (
            policy.get("mode") != "EXACT_GET_READ_ONLY"
            or bootstrap_keys != (durable_key,)
            or policy.get("post_bootstrap_get_policy")
            != "ONLY_RECEIPT_AND_PAYLOAD_KEYS_LISTED_BY_VERIFIED_INVENTORY"
        ):
            raise ValueError("P0_ACCESS_POLICY_NOT_EXACT_GET_ONLY")
        for forbidden_flag in (
            "raw_prefix_listing_allowed",
            "derived_prefix_listing_allowed",
            "head_allowed",
            "copy_allowed",
            "multipart_allowed",
        ):
            if policy.get(forbidden_flag) is not False:
                raise ValueError("P0_ACCESS_POLICY_FORBIDDEN_CAPABILITY_ENABLED")
        if any(policy.get(field) != 0 for field in ("r2_writes", "r2_deletes", "provider_calls")):
            raise ValueError("P0_ACCESS_POLICY_EFFECT_NONZERO")
        self._client = client
        self._bucket = bucket
        self._source_config = source_config
        self._bootstrap_key = durable_key
        self._limits = AccessLimits(
            bootstrap_gets=_integer(
                policy.get("max_bootstrap_gets"),
                label="P0_MAX_BOOTSTRAP_GETS",
                minimum=1,
            ),
            bootstrap_compressed_bytes=_integer(
                policy.get("max_bootstrap_compressed_bytes"),
                label="P0_MAX_BOOTSTRAP_STORED_BYTES",
                minimum=1,
            ),
            bootstrap_decompressed_bytes=_integer(
                policy.get("max_bootstrap_decompressed_bytes"),
                label="P0_MAX_BOOTSTRAP_LOGICAL_BYTES",
                minimum=1,
            ),
            gets_per_job=_integer(
                policy.get("max_gets_per_job"),
                label="P0_MAX_GETS_PER_JOB",
                minimum=1,
            ),
            stored_bytes_per_job=_integer(
                policy.get("max_stored_bytes_per_job"),
                label="P0_MAX_STORED_BYTES_PER_JOB",
                minimum=1,
            ),
            logical_bytes_per_job=_integer(
                policy.get("max_logical_bytes_per_job"),
                label="P0_MAX_LOGICAL_BYTES_PER_JOB",
                minimum=1,
            ),
            mission_gets=_integer(
                policy.get("max_mission_gets"),
                label="P0_MAX_MISSION_GETS",
                minimum=1,
            ),
        )
        self._telemetry = ReadTelemetry()
        self._inventory: VerifiedInventory | None = None
        self._receipt_cache: dict[str, tuple[HarvestReceipt, int]] = {}
        self._pair_cache: dict[str, VerifiedEvidencePair] = {}

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        source_config: Mapping[str, object],
    ) -> PinnedInventoryReader:
        try:
            client, bucket = create_r2_client(environment)
        except Exception:
            raise RuntimeError("P0_COVERAGE_R2_INIT_FAILED") from None
        return cls(
            cast(R2GetObjectClient, client),
            bucket=bucket,
            source_config=source_config,
        )

    @property
    def limits(self) -> AccessLimits:
        return self._limits

    @property
    def telemetry(self) -> ReadTelemetry:
        return self._telemetry

    def _get(self, key: str, *, limit: int, category: str) -> bytes:
        if category == "bootstrap":
            self._telemetry.bootstrap_requested += 1
            if self._telemetry.bootstrap_requested > self._limits.bootstrap_gets:
                raise ValueError("P0_BOOTSTRAP_GET_LIMIT_EXCEEDED")
        else:
            if (
                self._telemetry.bootstrap_requested + self._telemetry.evidence_gets
                >= self._limits.gets_per_job
            ):
                raise ValueError("P0_EVIDENCE_GET_LIMIT_EXCEEDED")
            remaining_stored_bytes = (
                self._limits.stored_bytes_per_job - self._telemetry.evidence_stored_bytes
            )
            if remaining_stored_bytes < 1:
                raise ValueError("P0_EVIDENCE_STORED_BYTE_LIMIT_EXCEEDED")
            limit = min(limit, remaining_stored_bytes)
            if category == "receipt":
                self._telemetry.receipt_requested += 1
            elif category == "payload":
                self._telemetry.payload_requested += 1
            else:
                raise ValueError("P0_GET_CATEGORY_INVALID")
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            content_length = response.get("ContentLength")
            if content_length is not None:
                if (
                    isinstance(content_length, bool)
                    or not isinstance(content_length, int)
                    or content_length < 0
                    or content_length > limit
                ):
                    raise ValueError("P0_R2_CONTENT_LENGTH_INVALID")
            body = response.get("Body")
            read = getattr(body, "read", None)
            if not callable(read):
                raise ValueError("P0_R2_BODY_INVALID")
            try:
                data = read(limit + 1)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
            if not isinstance(data, bytes) or len(data) > limit:
                raise ValueError("P0_R2_BODY_SIZE_LIMIT_EXCEEDED")
        except ValueError:
            if category == "bootstrap":
                self._telemetry.bootstrap_failed += 1
            elif category == "receipt":
                self._telemetry.receipt_failed += 1
            else:
                self._telemetry.payload_failed += 1
            raise
        except Exception:
            if category == "bootstrap":
                self._telemetry.bootstrap_failed += 1
            elif category == "receipt":
                self._telemetry.receipt_failed += 1
            else:
                self._telemetry.payload_failed += 1
            raise RuntimeError("P0_COVERAGE_R2_GET_FAILED") from None
        if category == "bootstrap":
            self._telemetry.bootstrap_succeeded += 1
            self._telemetry.bootstrap_stored_bytes += len(data)
        elif category == "receipt":
            self._telemetry.receipt_succeeded += 1
            self._telemetry.receipt_bytes += len(data)
        else:
            self._telemetry.payload_succeeded += 1
            self._telemetry.payload_stored_bytes += len(data)
        if (
            category != "bootstrap"
            and self._telemetry.evidence_stored_bytes > self._limits.stored_bytes_per_job
        ):
            raise ValueError("P0_EVIDENCE_STORED_BYTE_LIMIT_EXCEEDED")
        return data

    def fetch_inventory_once(self) -> VerifiedInventory:
        if self._inventory is not None:
            raise ValueError("P0_INVENTORY_BOOTSTRAP_ALREADY_USED")
        stored = self._get(
            self._bootstrap_key,
            limit=self._limits.bootstrap_compressed_bytes,
            category="bootstrap",
        )
        logical = _bounded_gzip(
            stored,
            limit=self._limits.bootstrap_decompressed_bytes,
            label="P0_INVENTORY",
        )
        self._telemetry.bootstrap_logical_bytes = len(logical)
        value = _mapping(
            _json_no_duplicates(logical, label="P0_INVENTORY"),
            label="P0_INVENTORY",
        )
        if canonical_json_bytes(value) != logical:
            raise ValueError("P0_INVENTORY_CANONICAL_BYTES_MISMATCH")
        inventory = deep_validate_inventory(
            value,
            source_config=self._source_config,
        )
        self._inventory = inventory
        return inventory

    def _entry(self, object_id: str) -> InventoryObject:
        if self._inventory is None:
            raise ValueError("P0_INVENTORY_REQUIRED_BEFORE_EVIDENCE")
        if HEX64.fullmatch(object_id) is None:
            raise ValueError("P0_EVIDENCE_OBJECT_ID_INVALID")
        try:
            return self._inventory.by_id[object_id]
        except KeyError:
            raise ValueError("P0_EVIDENCE_OBJECT_NOT_IN_INVENTORY") from None

    def fetch_receipt(self, object_id: str) -> HarvestReceipt:
        entry = self._entry(object_id)
        cached = self._receipt_cache.get(entry.object_id)
        if cached is not None:
            return cached[0]
        raw = self._get(
            entry.receipt_key,
            limit=self._RECEIPT_LIMIT,
            category="receipt",
        )
        value = _mapping(
            _json_no_duplicates(raw, label="P0_RECEIPT"),
            label="P0_RECEIPT",
        )
        if canonical_json_bytes(value) != raw:
            raise ValueError("P0_RECEIPT_CANONICAL_BYTES_MISMATCH")
        try:
            receipt = HarvestReceipt.model_validate(value)
        except ValueError:
            raise ValueError("P0_RECEIPT_CONTRACT_INVALID") from None
        expected_task_id = build_task_id(
            campaign_id=receipt.campaign_id,
            competition=receipt.competition,
            season=receipt.season,
            family=receipt.family,
            endpoint=receipt.endpoint,
            params=receipt.parameters,
            page=receipt.page,
        )
        exact_values = {
            "task_id": entry.task_id,
            "receipt_key": entry.receipt_key,
            "payload_key": entry.payload_key,
            "competition": entry.competition,
            "season": entry.season,
            "family": entry.family,
            "payload_sha256": entry.payload_sha256,
            "stored_sha256": entry.stored_sha256,
            "payload_bytes": entry.logical_bytes,
            "stored_bytes": entry.stored_bytes,
            "provider_calls": entry.provider_calls,
            "rows_normalized": entry.rows_received,
        }
        if (
            receipt.task_id != entry.receipt_id
            or receipt.receipt_hash != entry.receipt_hash
            or expected_task_id != receipt.task_id
            or any(getattr(receipt, field) != expected for field, expected in exact_values.items())
            or receipt.competition != f"api-football:{receipt.league_id}"
        ):
            raise ValueError("P0_RECEIPT_INVENTORY_MISMATCH")
        self._receipt_cache[entry.object_id] = (receipt, len(raw))
        return receipt

    def fetch_pair(self, object_id: str) -> VerifiedEvidencePair:
        entry = self._entry(object_id)
        cached_pair = self._pair_cache.get(entry.object_id)
        if cached_pair is not None:
            return cached_pair
        receipt = self.fetch_receipt(object_id)
        if (
            self._telemetry.payload_logical_bytes + entry.logical_bytes
            > self._limits.logical_bytes_per_job
        ):
            raise ValueError("P0_EVIDENCE_LOGICAL_BYTE_LIMIT_EXCEEDED")
        if (
            self._telemetry.evidence_stored_bytes + entry.stored_bytes
            > self._limits.stored_bytes_per_job
        ):
            raise ValueError("P0_EVIDENCE_STORED_BYTE_LIMIT_EXCEEDED")
        stored = self._get(
            entry.payload_key,
            limit=entry.stored_bytes,
            category="payload",
        )
        if (
            len(stored) != entry.stored_bytes
            or hashlib.sha256(stored).hexdigest() != entry.stored_sha256
        ):
            raise ValueError("P0_PAYLOAD_STORED_INTEGRITY_MISMATCH")
        logical = _bounded_gzip(
            stored,
            limit=entry.logical_bytes,
            label="P0_PAYLOAD",
        )
        if len(logical) != entry.logical_bytes:
            raise ValueError("P0_PAYLOAD_LOGICAL_SIZE_MISMATCH")
        payload = _json_no_duplicates(logical, label="P0_PAYLOAD")
        if (
            canonical_json_bytes(payload) != logical
            or hashlib.sha256(logical).hexdigest() != entry.payload_sha256
        ):
            raise ValueError("P0_PAYLOAD_LOGICAL_INTEGRITY_MISMATCH")
        if str(receipt.status.value) == "EMPTY_VALID" and not _payload_empty(payload):
            raise ValueError("P0_EMPTY_VALID_PAYLOAD_NOT_EMPTY")
        try:
            fixture_parameter = receipt.parameters.get("fixture")
            fixture_id = (
                fixture_parameter
                if isinstance(fixture_parameter, int)
                and not isinstance(fixture_parameter, bool)
                and fixture_parameter > 0
                else None
            )
            normalized_raw = normalize_payload(
                payload,
                endpoint=receipt.endpoint,
                competition_id=receipt.league_id,
                season=receipt.season,
                task_id=receipt.task_id,
                source_payload_hash=receipt.payload_sha256,
                request_params=receipt.parameters,
                observed_at=receipt.received_at,
                ingested_at=receipt.completed_at,
                fixture_id=fixture_id,
            )
        except (NormalizationError, ValueError, TypeError):
            raise ValueError("P0_PAYLOAD_NORMALIZATION_FAILED") from None
        normalized = {
            family: tuple(_mapping(row, label="P0_NORMALIZED_ROW") for row in rows)
            for family, rows in normalized_raw.items()
        }

        def compact_normalizer(
            _receipt: Mapping[str, object],
            _payload: object,
        ) -> Mapping[str, object]:
            return {
                "normalized_counts": {
                    family: len(rows) for family, rows in sorted(normalized.items())
                },
                "normalized_hash": canonical_sha256(normalized_raw),
            }

        replay = replay_stream_cache_only(
            [(receipt.model_dump(mode="json"), payload)],
            normalizer=compact_normalizer,
            known_payload_keys=(entry.payload_key,),
            require_all_payloads_referenced=False,
            retain_projections=False,
        )
        if (
            replay.provider_calls != 0
            or replay.provider_credits != 0
            or replay.hash_mismatches != 0
            or replay.payloads_replayed != 1
            or replay.receipts_verified != 1
        ):
            raise ValueError("P0_PAIR_REPLAY_INTEGRITY_FAILED")
        self._telemetry.payload_logical_bytes += len(logical)
        self._telemetry.pairs_verified += 1
        receipt_bytes = self._receipt_cache[entry.object_id][1]
        self._telemetry.peak_pair_bytes = max(
            self._telemetry.peak_pair_bytes,
            receipt_bytes + len(stored),
        )
        verified_pair = VerifiedEvidencePair(
            entry=entry,
            receipt=receipt,
            payload=payload,
            normalized=normalized,
            replay_source_hash=replay.source_hash,
            replay_hash=replay.replay_hash,
        )
        self._pair_cache[entry.object_id] = verified_pair
        return verified_pair


def _payload_empty(payload: object) -> bool:
    if payload in (None, [], {}):
        return True
    if isinstance(payload, Mapping):
        response = payload.get("response")
        results = payload.get("results")
        return response in (None, [], {}) and results in (None, 0)
    return False


def _load_json(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ValueError(f"{label}_INVALID") from error
    value = _json_no_duplicates(raw, label=label)
    return _mapping(value, label=label)


def _parse_access_limits(source_config: Mapping[str, object]) -> AccessLimits:
    policy = _mapping(source_config.get("access_policy"), label="P0_ACCESS_POLICY")
    return AccessLimits(
        bootstrap_gets=_integer(
            policy.get("max_bootstrap_gets"),
            label="P0_MAX_BOOTSTRAP_GETS",
            minimum=1,
        ),
        bootstrap_compressed_bytes=_integer(
            policy.get("max_bootstrap_compressed_bytes"),
            label="P0_MAX_BOOTSTRAP_STORED_BYTES",
            minimum=1,
        ),
        bootstrap_decompressed_bytes=_integer(
            policy.get("max_bootstrap_decompressed_bytes"),
            label="P0_MAX_BOOTSTRAP_LOGICAL_BYTES",
            minimum=1,
        ),
        gets_per_job=_integer(
            policy.get("max_gets_per_job"),
            label="P0_MAX_GETS_PER_JOB",
            minimum=1,
        ),
        stored_bytes_per_job=_integer(
            policy.get("max_stored_bytes_per_job"),
            label="P0_MAX_STORED_BYTES_PER_JOB",
            minimum=1,
        ),
        logical_bytes_per_job=_integer(
            policy.get("max_logical_bytes_per_job"),
            label="P0_MAX_LOGICAL_BYTES_PER_JOB",
            minimum=1,
        ),
        mission_gets=_integer(
            policy.get("max_mission_gets"),
            label="P0_MAX_MISSION_GETS",
            minimum=1,
        ),
    )


def load_authority(
    root: Path,
    *,
    stage: str,
    now: datetime | None = None,
) -> CoverageAuthority:
    """Load and cross-check the committed mission, mapping, and source pin."""

    if stage not in DOMAIN_STAGES:
        raise ValueError("P0_DOMAIN_STAGE_INVALID")
    source_path = root / SOURCE_CONFIG_PATH
    mission_path = root / MISSION_PATH
    mapping_path = root / MAPPING_PATH
    source = _load_json(source_path, label="P0_SOURCE_CONFIG")
    mission = _load_json(mission_path, label="P0_MISSION")
    mapping = _load_json(mapping_path, label="P0_STAGE_MAPPING")
    source_sha = _lf_sha256(source_path)
    mission_sha = _lf_sha256(mission_path)
    mapping_sha = _lf_sha256(mapping_path)
    if set(mission) != {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }:
        raise ValueError("P0_MISSION_FIELDS_INVALID")
    if (
        mission.get("mission_id") != "p0-coverage-evidence-ladder-v1"
        or mission.get("maximum_stage") != "E4"
        or mission.get("source_hash") != source_sha
        or mission.get("compute_budget") != 480
        or mission.get("time_budget") != 144_000
        or set(_sequence(mission.get("external_effects"), label="P0_MISSION_EFFECTS"))
        != {
            "github_actions_execute_read_only",
            "r2_read_existing_immutable_evidence",
        }
    ):
        raise ValueError("P0_MISSION_AUTHORITY_INVALID")
    try:
        expires_at = datetime.fromisoformat(
            _text(mission.get("expires_at"), label="P0_MISSION_EXPIRY").replace("Z", "+00:00")
        )
    except ValueError:
        raise ValueError("P0_MISSION_EXPIRY_INVALID") from None
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("P0_MISSION_EXPIRY_UTC_REQUIRED")
    if observed_at >= expires_at.astimezone(UTC):
        raise ValueError("P0_MISSION_EXPIRED")

    contracts = _mapping(source.get("contracts"), label="P0_SOURCE_CONTRACTS")
    for binding in contracts.values():
        contract = _mapping(binding, label="P0_SOURCE_CONTRACT")
        relative = Path(_text(contract.get("path"), label="P0_CONTRACT_PATH"))
        expected = _sha(contract.get("file_sha256_lf"), label="P0_CONTRACT_HASH")
        if not _historical_contract_hash_matches(
            root,
            relative=relative,
            expected=expected,
            source_sha=source_sha,
            mission_sha=mission_sha,
            mapping_sha=mapping_sha,
        ):
            raise ValueError(f"P0_CONTRACT_HASH_MISMATCH:{relative.as_posix()}")
    denominator_binding = _mapping(
        contracts.get("denominator"),
        label="P0_DENOMINATOR_BINDING",
    )
    denominator_contract = _load_json(
        root
        / Path(_text(denominator_binding.get("path"), label="P0_DENOMINATOR_PATH")),
        label="P0_DENOMINATOR_CONTRACT",
    )
    absence_rule = _mapping(
        denominator_contract.get("absence_partition_rule"),
        label="P0_ABSENCE_PARTITION_RULE",
    )
    if (
        absence_rule.get("version") != "absence-partition-rule-v1"
        or tuple(
            _text(item, label="P0_ABSENCE_CATEGORY")
            for item in _sequence(
                absence_rule.get("categories"),
                label="P0_ABSENCE_CATEGORIES",
            )
        )
        != ("SUSPENSION", "INJURY", "UNCLASSIFIABLE")
        or absence_rule.get("page_position_excluded_from_key") is not True
    ):
        raise ValueError("P0_ABSENCE_PARTITION_RULE_INVALID")
    absence_suspension_regex = _text(
        absence_rule.get("suspension_regex"),
        label="P0_SUSPENSION_REGEX",
    )
    absence_injury_regex = _text(
        absence_rule.get("injury_regex"),
        label="P0_INJURY_REGEX",
    )
    try:
        re.compile(absence_suspension_regex, flags=re.IGNORECASE)
        re.compile(absence_injury_regex, flags=re.IGNORECASE)
    except re.error:
        raise ValueError("P0_ABSENCE_REGEX_INVALID") from None
    mapping_binding = _mapping(contracts.get("stage_mapping"), label="P0_MAPPING_BINDING")
    if mapping_binding.get("file_sha256_lf") != mapping_sha:
        raise ValueError("P0_MAPPING_SOURCE_BINDING_MISMATCH")
    if (
        mapping.get("schema_version") != "coverage-scale-pack-manifests-v2"
        or mapping.get("contract_role") != "DOMAIN_STAGE_MAPPING_ONLY_NO_EXECUTION_AUTHORITY"
        or mapping.get("immutable") is not True
    ):
        raise ValueError("P0_MAPPING_CONTRACT_INVALID")
    family_groups = _mapping(mapping.get("family_groups"), label="P0_FAMILY_GROUPS")
    if {
        group: tuple(_sequence(families, label="P0_GROUP_FAMILIES"))
        for group, families in family_groups.items()
    } != FAMILY_GROUPS:
        raise ValueError("P0_FAMILY_GROUPS_MISMATCH")
    levels = _mapping(mapping.get("levels"), label="P0_MAPPING_LEVELS")
    level = _mapping(levels.get(stage), label="P0_MAPPING_LEVEL")
    council_stage = _text(level.get("council_stage"), label="P0_COUNCIL_STAGE")
    if council_stage not in set(
        _sequence(mission.get("authorized_stages"), label="P0_AUTHORIZED_STAGES")
    ):
        raise ValueError("P0_STAGE_NOT_AUTHORIZED")
    if any(
        value not in (0, False)
        for value in _mapping(mapping.get("effects"), label="P0_MAPPING_EFFECTS").values()
    ):
        raise ValueError("P0_MAPPING_EFFECT_NONZERO")
    scope = _mapping(source.get("scope"), label="P0_SOURCE_SCOPE")
    competitions = tuple(
        _text(
            _mapping(item, label="P0_COMPETITION_PIN").get("canonical_key"),
            label="P0_COMPETITION_PIN",
        )
        for item in _sequence(scope.get("competitions"), label="P0_COMPETITIONS")
    )
    seasons = tuple(
        _integer(item, label="P0_PINNED_SEASON", minimum=1888)
        for item in _sequence(scope.get("seasons"), label="P0_PINNED_SEASONS")
    )
    normalized_families = tuple(
        _text(item, label="P0_NORMALIZED_FAMILY")
        for item in _sequence(scope.get("normalized_p0_families"), label="P0_NORMALIZED_FAMILIES")
    )
    raw_families = tuple(
        _text(item, label="P0_RAW_FAMILY")
        for item in _sequence(scope.get("raw_inventory_families"), label="P0_RAW_FAMILIES")
    )
    if (
        len(competitions) != 5
        or len(seasons) != 6
        or len(normalized_families) != 16
        or len(set(competitions)) != len(competitions)
        or len(set(seasons)) != len(seasons)
        or len(set(normalized_families)) != len(normalized_families)
        or set(normalized_families)
        != {family for families in FAMILY_GROUPS.values() for family in families}
    ):
        raise ValueError("P0_SCOPE_SHAPE_INVALID")
    identity = _mapping(source.get("identity_registry"), label="P0_IDENTITY_REGISTRY")
    if (
        identity.get("natural_key_policy") != "SEMANTIC_NON_POSITIONAL_KEYS_ONLY"
        or identity.get("position_fields_forbidden") is not True
        or tuple(
            _text(item, label="P0_IDENTITY_ABSENCE_CATEGORY")
            for item in _sequence(
                identity.get("absence_partition"),
                label="P0_IDENTITY_ABSENCE_PARTITION",
            )
        )
        != ("SUSPENSION", "INJURY", "UNCLASSIFIABLE")
        or identity.get("third_unchanged_attempt") != "FAIL_AND_STOP"
    ):
        raise ValueError("P0_IDENTITY_POLICY_INVALID")
    return CoverageAuthority(
        root=root,
        source_config=source,
        mission=mission,
        mapping=mapping,
        source_config_sha256=source_sha,
        mission_sha256=mission_sha,
        mapping_sha256=mapping_sha,
        stage=stage,
        council_stage=council_stage,
        competitions=competitions,
        seasons=seasons,
        normalized_families=normalized_families,
        raw_families=raw_families,
        identity_architecture_hash=_sha(
            identity.get("architecture_hash"), label="P0_IDENTITY_ARCHITECTURE"
        ),
        absence_suspension_regex=absence_suspension_regex,
        absence_injury_regex=absence_injury_regex,
        limits=_parse_access_limits(source),
    )


def validate_predecessor(authority: CoverageAuthority) -> None:
    predecessor = {
        "E1A": None,
        "E1B": "E1A",
        "E2": "E1B",
        "E3A": "E2",
        "E3B": "E3A",
        "E4": "E3B",
    }[authority.stage]
    if predecessor is None:
        return
    path = (
        authority.root / "reports" / "coverage" / f"p0-evidence-ladder-stage-{predecessor}-v1.json"
    )
    receipt = _load_json(path, label="P0_PREDECESSOR_RECEIPT")
    _verify_signed(
        receipt,
        field="stage_receipt_sha256",
        label="P0_PREDECESSOR_RECEIPT",
    )
    predecessor_authority = load_authority(authority.root, stage=predecessor)
    predecessor_selection = _load_json(
        authority.root
        / "configs"
        / "data"
        / f"p0-coverage-evidence-selection-{predecessor}-v1.json",
        label="P0_PREDECESSOR_SELECTION",
    )
    predecessor_selection_sha = validate_selection(
        predecessor_selection,
        authority=predecessor_authority,
        stage=predecessor,
    )
    expected_council_decision = "PASS_AND_HOLD" if predecessor == "E1A" else "PASS_AND_SCALE"
    try:
        _validated_mission_accounting(
            receipt,
            authority=authority,
            label="P0_PREDECESSOR_MISSION_ACCOUNTING",
        )
    except ValueError:
        raise ValueError("P0_PREDECESSOR_NOT_PROVEN") from None
    if (
        receipt.get("schema_version") != STAGE_SCHEMA_VERSION
        or receipt.get("stage") != predecessor
        or receipt.get("mission_id") != authority.mission.get("mission_id")
        or receipt.get("mission_sha256") != authority.mission_sha256
        or receipt.get("architecture_fingerprint") != evidence_architecture_fingerprint(authority)
        or receipt.get("architecture_ordinal") != predecessor_selection.get("architecture_ordinal")
        or receipt.get("mission_architecture_registry")
        != predecessor_selection.get("mission_architecture_registry")
        or receipt.get("council_stage") != predecessor_authority.council_stage
        or receipt.get("selection_sha256") != predecessor_selection_sha
        or receipt.get("scientific_gate") != "PASS"
        or receipt.get("checkpoint_gate") != "PASS"
        or receipt.get("domain_decision") != "PASS_AND_SCALE"
        or receipt.get("council_decision") != expected_council_decision
        or _mapping(
            receipt.get("effects"),
            label="P0_PREDECESSOR_EFFECTS",
        )
        != ZERO_EFFECTS
    ):
        raise ValueError("P0_PREDECESSOR_NOT_PROVEN")


def _current_stage_receipt(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
) -> Mapping[str, object]:
    path = (
        authority.root
        / "reports"
        / "coverage"
        / f"p0-evidence-ladder-stage-{authority.stage}-v1.json"
    )
    receipt = _load_json(path, label="P0_CURRENT_STAGE_RECEIPT")
    _verify_signed(
        receipt,
        field="stage_receipt_sha256",
        label="P0_CURRENT_STAGE_RECEIPT",
    )
    selection_sha = validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    if (
        receipt.get("schema_version") != STAGE_SCHEMA_VERSION
        or receipt.get("stage") != authority.stage
        or receipt.get("mission_id") != authority.mission.get("mission_id")
        or receipt.get("mission_sha256") != authority.mission_sha256
        or receipt.get("selection_sha256") != selection_sha
        or receipt.get("architecture_fingerprint") != evidence_architecture_fingerprint(authority)
        or receipt.get("architecture_ordinal") != selection.get("architecture_ordinal")
        or receipt.get("mission_architecture_registry")
        != selection.get("mission_architecture_registry")
        or _mapping(
            receipt.get("effects"),
            label="P0_CURRENT_STAGE_EFFECTS",
        )
        != ZERO_EFFECTS
    ):
        raise ValueError("P0_CURRENT_STAGE_RECEIPT_INVALID")
    return receipt


def _validated_mission_accounting(
    receipt: Mapping[str, object],
    *,
    authority: CoverageAuthority,
    label: str,
) -> tuple[int, int | None, int, str]:
    planned = _integer(
        receipt.get("planned_mission_logical_gets"),
        label=f"{label}_PLANNED_GETS",
    )
    charged = _integer(
        receipt.get("cumulative_mission_logical_gets_charged"),
        label=f"{label}_CHARGED_GETS",
    )
    lower_bound = _integer(
        receipt.get("cumulative_mission_logical_gets_observed_lower_bound"),
        label=f"{label}_OBSERVED_LOWER_BOUND",
    )
    basis = _text(
        receipt.get("mission_budget_accounting_basis"),
        label=f"{label}_ACCOUNTING_BASIS",
    )
    observed_value = receipt.get("cumulative_mission_logical_gets_observed")
    observed = (
        None
        if observed_value == "UNKNOWN_NOT_OBSERVED"
        else _integer(observed_value, label=f"{label}_OBSERVED_GETS")
    )
    exact = receipt.get("mission_budget_exact") is True
    if (
        receipt.get("mission_budget_gate") != "PASS"
        or charged != planned
        or charged > authority.limits.mission_gets
        or lower_bound > charged
        or basis not in {MISSION_ACCOUNTING_EXACT, MISSION_ACCOUNTING_CONSERVATIVE}
        or (
            exact
            and (
                basis != MISSION_ACCOUNTING_EXACT
                or observed is None
                or observed != charged
                or lower_bound != charged
            )
        )
        or (
            not exact
            and (
                basis != MISSION_ACCOUNTING_CONSERVATIVE
                or observed is not None
                and not lower_bound <= observed <= charged
            )
        )
    ):
        raise ValueError(f"{label}_INVALID")
    return charged, observed, lower_bound, basis


def _prior_mission_accounting(
    authority: CoverageAuthority,
) -> tuple[int, int | None, int, str]:
    predecessor = {
        "E1A": None,
        "E1B": "E1A",
        "E2": "E1B",
        "E3A": "E2",
        "E3B": "E3A",
        "E4": "E3B",
    }[authority.stage]
    if predecessor is None:
        return 0, 0, 0, MISSION_ACCOUNTING_EXACT
    receipt = _load_json(
        authority.root / "reports" / "coverage" / f"p0-evidence-ladder-stage-{predecessor}-v1.json",
        label="P0_PRIOR_STAGE_RECEIPT",
    )
    _verify_signed(
        receipt,
        field="stage_receipt_sha256",
        label="P0_PRIOR_STAGE_RECEIPT",
    )
    if (
        receipt.get("schema_version") != STAGE_SCHEMA_VERSION
        or receipt.get("stage") != predecessor
        or receipt.get("mission_id") != authority.mission.get("mission_id")
        or receipt.get("mission_sha256") != authority.mission_sha256
    ):
        raise ValueError("P0_PRIOR_STAGE_RECEIPT_INVALID")
    return _validated_mission_accounting(
        receipt,
        authority=authority,
        label="P0_PRIOR_MISSION_ACCOUNTING",
    )


def _mission_architecture_registry(
    value: object,
    *,
    label: str,
) -> tuple[tuple[int, str], ...]:
    entries = tuple(
        _mapping(item, label=f"{label}_ENTRY") for item in _sequence(value, label=label)
    )
    parsed = tuple(
        (
            _integer(
                item.get("ordinal"),
                label=f"{label}_ORDINAL",
                minimum=1,
            ),
            _sha(item.get("architecture_fingerprint"), label=f"{label}_FINGERPRINT"),
        )
        for item in entries
        if set(item) == {"ordinal", "architecture_fingerprint"}
    )
    if (
        len(parsed) != len(entries)
        or not 1 <= len(parsed) <= 2
        or tuple(item[0] for item in parsed) != tuple(range(1, len(parsed) + 1))
        or len({item[1] for item in parsed}) != len(parsed)
    ):
        raise ValueError(f"{label}_INVALID")
    return parsed


def _mission_receipt_candidate(
    authority: CoverageAuthority,
    *,
    stage: str,
    path: Path,
    selection_identity: Mapping[str, object],
) -> Mapping[str, object]:
    receipt = _load_json(path, label="P0_MISSION_ACCOUNTING_RECEIPT")
    receipt_sha = _verify_signed(
        receipt,
        field="stage_receipt_sha256",
        label="P0_MISSION_ACCOUNTING_RECEIPT",
    )
    fingerprint = _sha(
        receipt.get("architecture_fingerprint"),
        label="P0_MISSION_ACCOUNTING_ARCHITECTURE",
    )
    selection_sha = _sha(
        receipt.get("selection_sha256"),
        label="P0_MISSION_ACCOUNTING_SELECTION",
    )
    ordinal = _integer(
        receipt.get("architecture_ordinal"),
        label="P0_MISSION_ACCOUNTING_ARCHITECTURE_ORDINAL",
        minimum=1,
    )
    registry = _mission_architecture_registry(
        receipt.get("mission_architecture_registry"),
        label="P0_MISSION_ACCOUNTING_ARCHITECTURE_REGISTRY",
    )
    ancestors = tuple(
        _sha(item, label="P0_MISSION_ACCOUNTING_ANCESTOR")
        for item in _sequence(
            receipt.get("mission_accounting_ancestor_receipt_sha256s"),
            label="P0_MISSION_ACCOUNTING_ANCESTORS",
        )
    )
    parent_value = receipt.get("accounting_parent_receipt_sha256")
    parent = (
        None if parent_value is None else _sha(parent_value, label="P0_MISSION_ACCOUNTING_PARENT")
    )
    charged, observed, lower_bound, basis = _validated_mission_accounting(
        receipt,
        authority=authority,
        label="P0_MISSION_ACCOUNTING_RECEIPT",
    )
    selection_fingerprint = selection_identity.get("fingerprint")
    selection_ordinal = selection_identity.get("ordinal")
    selection_registry = selection_identity.get("registry")
    current_selection_binding = (
        selection_sha == selection_identity.get("selection_sha256")
        and fingerprint == selection_fingerprint
        and ordinal == selection_ordinal
        and registry == selection_registry
    )
    selection = _mapping(
        selection_identity.get("selection"),
        label="P0_MISSION_ACCOUNTING_SELECTION",
    )
    expected_redesign_baseline = {
        "schema_version": MISSION_ACCOUNTING_BASELINE_SCHEMA,
        "source": "STAGE_RECEIPT",
        "source_stage": stage,
        "source_stage_receipt_sha256": receipt_sha,
        "source_architecture_fingerprint": fingerprint,
        "source_receipt_ancestor_sha256s": list(ancestors),
        "cumulative_mission_logical_gets_charged": charged,
        "cumulative_mission_logical_gets_observed": (
            observed if observed is not None else "UNKNOWN_NOT_OBSERVED"
        ),
        "cumulative_mission_logical_gets_observed_lower_bound": lower_bound,
        "mission_budget_accounting_basis": basis,
    }
    redesign_predecessor_binding = (
        ordinal == 1
        and selection_ordinal == 2
        and cast(tuple[tuple[int, str], ...], selection_registry)[:-1] == registry
        and selection_fingerprint != fingerprint
        and receipt.get("attempt_slot") == 2
        and receipt.get("scientific_gate") == "FAIL"
        and receipt.get("scale_gate") == "FAIL"
        and receipt.get("measurement_integrity_gate") == "PASS"
        and receipt.get("read_accounting_gate") == "PASS"
        and receipt.get("checkpoint_gate") == "PASS"
        and receipt.get("domain_decision") == "FAIL_AND_REDESIGN"
        and receipt.get("council_decision") == "FAIL_AND_REDESIGN"
        and receipt.get("mission_budget_exact") is True
        and basis == MISSION_ACCOUNTING_EXACT
        and observed == charged
        and lower_bound == charged
        and selection.get("mission_accounting_baseline") == expected_redesign_baseline
    )
    if (
        receipt.get("schema_version") != STAGE_SCHEMA_VERSION
        or receipt.get("stage") != stage
        or receipt.get("mission_id") != authority.mission.get("mission_id")
        or receipt.get("mission_sha256") != authority.mission_sha256
        or selection_identity.get("stage") != stage
        or not (current_selection_binding or redesign_predecessor_binding)
        or ordinal not in {1, 2}
        or len(registry) != ordinal
        or registry[-1] != (ordinal, fingerprint)
        or len(ancestors) != len(set(ancestors))
        or receipt_sha in ancestors
        or (parent is None and ancestors)
        or (parent is not None and (not ancestors or ancestors[-1] != parent))
        or _mapping(
            receipt.get("effects"),
            label="P0_MISSION_ACCOUNTING_EFFECTS",
        )
        != ZERO_EFFECTS
    ):
        raise ValueError("P0_MISSION_ACCOUNTING_RECEIPT_INVALID")
    return {
        "receipt": receipt,
        "receipt_sha256": receipt_sha,
        "stage": stage,
        "selection_sha256": selection_sha,
        "fingerprint": fingerprint,
        "ordinal": ordinal,
        "registry": registry,
        "selection_binding": (
            "CURRENT_SELECTION" if current_selection_binding else "REDESIGN_PREDECESSOR"
        ),
        "ancestors": ancestors,
        "charged": charged,
        "observed": observed,
        "lower_bound": lower_bound,
        "basis": basis,
    }


def _mission_selection_identity(
    authority: CoverageAuthority,
    *,
    stage: str,
    path: Path,
) -> Mapping[str, object]:
    selection = _load_json(path, label="P0_MISSION_ACCOUNTING_SELECTION")
    selection_sha = _verify_signed(
        selection,
        field="selection_sha256",
        label="P0_MISSION_ACCOUNTING_SELECTION",
    )
    algorithm_version = _text(
        selection.get("algorithm_version"),
        label="P0_MISSION_ACCOUNTING_ALGORITHM_VERSION",
    )
    identity_hash = _sha(
        selection.get("identity_architecture_hash"),
        label="P0_MISSION_ACCOUNTING_IDENTITY_ARCHITECTURE",
    )
    fingerprint_payload = {
        "algorithm_version": algorithm_version,
        "identity_architecture_hash": identity_hash,
    }
    framework_value = selection.get("absence_classification_framework_sha256")
    if framework_value is not None:
        fingerprint_payload["absence_classification_framework_sha256"] = _sha(
            framework_value,
            label="P0_MISSION_ACCOUNTING_ABSENCE_FRAMEWORK",
        )
    fingerprint = canonical_sha256(fingerprint_payload)
    ordinal = _integer(
        selection.get("architecture_ordinal"),
        label="P0_MISSION_ACCOUNTING_SELECTION_ORDINAL",
        minimum=1,
    )
    registry = _mission_architecture_registry(
        selection.get("mission_architecture_registry"),
        label="P0_MISSION_ACCOUNTING_SELECTION_REGISTRY",
    )
    if (
        selection.get("schema_version") != SELECTION_SCHEMA_VERSION
        or selection.get("mission_id") != authority.mission.get("mission_id")
        or selection.get("mission_sha256") != authority.mission_sha256
        or selection.get("domain_stage") != stage
        or ordinal not in {1, 2}
        or len(registry) != ordinal
        or registry[-1] != (ordinal, fingerprint)
        or _mapping(
            selection.get("effects"),
            label="P0_MISSION_ACCOUNTING_SELECTION_EFFECTS",
        )
        != ZERO_EFFECTS
    ):
        raise ValueError("P0_MISSION_ACCOUNTING_SELECTION_INVALID")
    return {
        "selection": selection,
        "selection_sha256": selection_sha,
        "stage": stage,
        "fingerprint": fingerprint,
        "ordinal": ordinal,
        "registry": registry,
    }


def _mission_accounting_state(
    authority: CoverageAuthority,
) -> tuple[
    Mapping[str, object],
    int,
    tuple[Mapping[str, object], ...],
    tuple[Mapping[str, object], ...],
]:
    candidates: list[Mapping[str, object]] = []
    selections: list[Mapping[str, object]] = []
    fingerprints_to_ordinals: dict[str, int] = {}
    ordinals_to_fingerprints: dict[int, str] = {}

    def register_architecture(*, fingerprint: str, ordinal: int) -> None:
        prior_ordinal = fingerprints_to_ordinals.setdefault(fingerprint, ordinal)
        prior_fingerprint = ordinals_to_fingerprints.setdefault(ordinal, fingerprint)
        if prior_ordinal != ordinal or prior_fingerprint != fingerprint:
            raise ValueError("P0_MISSION_ARCHITECTURE_BIJECTION_INVALID")

    identities_by_stage: dict[str, Mapping[str, object]] = {}
    for stage in DOMAIN_STAGES:
        selection_path = (
            authority.root / "configs" / "data" / f"p0-coverage-evidence-selection-{stage}-v1.json"
        )
        if selection_path.exists():
            identity = _mission_selection_identity(
                authority,
                stage=stage,
                path=selection_path,
            )
            identities_by_stage[stage] = identity
            selections.append(identity)
            for registry_ordinal, registry_fingerprint in cast(
                tuple[tuple[int, str], ...], identity["registry"]
            ):
                register_architecture(
                    fingerprint=registry_fingerprint,
                    ordinal=registry_ordinal,
                )
            register_architecture(
                fingerprint=cast(str, identity["fingerprint"]),
                ordinal=cast(int, identity["ordinal"]),
            )

    selection_stages_by_hash = {
        cast(str, identity["selection_sha256"]): stage
        for stage, identity in identities_by_stage.items()
    }
    if len(selection_stages_by_hash) != len(identities_by_stage):
        raise ValueError("P0_MISSION_SELECTION_STAGE_BINDING_AMBIGUOUS")

    for stage in DOMAIN_STAGES:
        receipt_path = (
            authority.root / "reports" / "coverage" / f"p0-evidence-ladder-stage-{stage}-v1.json"
        )
        if receipt_path.exists():
            stage_identity = identities_by_stage.get(stage)
            if stage_identity is None:
                raise ValueError("P0_MISSION_ACCOUNTING_RECEIPT_SELECTION_MISSING")
            candidate = _mission_receipt_candidate(
                authority,
                stage=stage,
                path=receipt_path,
                selection_identity=stage_identity,
            )
            linked_stage = selection_stages_by_hash.get(cast(str, candidate["selection_sha256"]))
            if linked_stage is not None and linked_stage != stage:
                raise ValueError("P0_MISSION_ACCOUNTING_RECEIPT_INVALID")
            candidates.append(candidate)
            for registry_ordinal, registry_fingerprint in cast(
                tuple[tuple[int, str], ...], candidate["registry"]
            ):
                register_architecture(
                    fingerprint=registry_fingerprint,
                    ordinal=registry_ordinal,
                )
            register_architecture(
                fingerprint=cast(str, candidate["fingerprint"]),
                ordinal=cast(int, candidate["ordinal"]),
            )
    if len(fingerprints_to_ordinals) > 2:
        raise ValueError("P0_MISSION_ARCHITECTURE_LIMIT_EXCEEDED")

    charged_values = [cast(int, candidate["charged"]) for candidate in candidates]
    if len(charged_values) != len(set(charged_values)):
        raise ValueError("P0_MISSION_ACCOUNTING_MAXIMUM_AMBIGUOUS")
    ordered_candidates = sorted(candidates, key=lambda candidate: cast(int, candidate["charged"]))
    for ancestor_candidate, descendant_candidate in zip(
        ordered_candidates,
        ordered_candidates[1:],
        strict=False,
    ):
        descendant_ancestors = cast(tuple[str, ...], descendant_candidate["ancestors"])
        ancestor_sha = cast(str, ancestor_candidate["receipt_sha256"])
        if ancestor_sha not in descendant_ancestors:
            raise ValueError("P0_MISSION_ACCOUNTING_CHAIN_FORK")
        ancestor_position = descendant_ancestors.index(ancestor_sha)
        if descendant_ancestors[:ancestor_position] != cast(
            tuple[str, ...], ancestor_candidate["ancestors"]
        ):
            raise ValueError("P0_MISSION_ACCOUNTING_CHAIN_FORK")
    winner: Mapping[str, object] | None = (
        max(candidates, key=lambda candidate: cast(int, candidate["charged"]))
        if candidates
        else None
    )
    if winner is not None:
        winner_ancestors = set(cast(tuple[str, ...], winner["ancestors"]))
        if any(
            candidate["receipt_sha256"] not in winner_ancestors
            for candidate in candidates
            if candidate is not winner
        ):
            raise ValueError("P0_MISSION_ACCOUNTING_CHAIN_FORK")

    absorbed_selections = {
        (candidate["stage"], candidate["selection_sha256"]) for candidate in candidates
    }
    pending = tuple(
        selection
        for selection in selections
        if (selection["stage"], selection["selection_sha256"]) not in absorbed_selections
    )
    if len(pending) > 1:
        raise ValueError("P0_MISSION_MULTIPLE_PENDING_SELECTIONS")

    current_fingerprint = evidence_architecture_fingerprint(authority)
    if current_fingerprint in fingerprints_to_ordinals:
        current_ordinal = fingerprints_to_ordinals[current_fingerprint]
        if max(ordinals_to_fingerprints, default=1) == 2 and current_ordinal == 1:
            raise ValueError("P0_MISSION_ARCHITECTURE_ROLLBACK_FORBIDDEN")
    else:
        current_ordinal = len(fingerprints_to_ordinals) + 1
        if current_ordinal > 2:
            raise ValueError("P0_MISSION_ARCHITECTURE_LIMIT_EXCEEDED")
        if winner is not None:
            winner_receipt = cast(Mapping[str, object], winner["receipt"])
            if (
                authority.stage != "E1A"
                or winner["ordinal"] != 1
                or winner_receipt.get("attempt_slot") != 2
                or winner_receipt.get("scientific_gate") != "FAIL"
                or winner_receipt.get("scale_gate") != "FAIL"
                or winner_receipt.get("measurement_integrity_gate") != "PASS"
                or winner_receipt.get("read_accounting_gate") != "PASS"
                or winner_receipt.get("checkpoint_gate") != "PASS"
                or winner_receipt.get("domain_decision") != "FAIL_AND_REDESIGN"
                or winner_receipt.get("council_decision") != "FAIL_AND_REDESIGN"
                or winner_receipt.get("mission_budget_exact") is not True
                or winner.get("basis") != MISSION_ACCOUNTING_EXACT
                or winner.get("observed") != winner.get("charged")
                or winner.get("lower_bound") != winner.get("charged")
            ):
                raise ValueError("P0_MISSION_REDESIGN_NOT_AUTHORIZED")
        register_architecture(
            fingerprint=current_fingerprint,
            ordinal=current_ordinal,
        )

    if winner is None:
        baseline: Mapping[str, object] = {
            "schema_version": MISSION_ACCOUNTING_BASELINE_SCHEMA,
            "source": "MISSION_START",
            "source_stage": None,
            "source_stage_receipt_sha256": None,
            "source_architecture_fingerprint": None,
            "source_receipt_ancestor_sha256s": [],
            "cumulative_mission_logical_gets_charged": 0,
            "cumulative_mission_logical_gets_observed": 0,
            "cumulative_mission_logical_gets_observed_lower_bound": 0,
            "mission_budget_accounting_basis": MISSION_ACCOUNTING_EXACT,
        }
    else:
        baseline = {
            "schema_version": MISSION_ACCOUNTING_BASELINE_SCHEMA,
            "source": "STAGE_RECEIPT",
            "source_stage": winner["stage"],
            "source_stage_receipt_sha256": winner["receipt_sha256"],
            "source_architecture_fingerprint": winner["fingerprint"],
            "source_receipt_ancestor_sha256s": list(cast(tuple[str, ...], winner["ancestors"])),
            "cumulative_mission_logical_gets_charged": winner["charged"],
            "cumulative_mission_logical_gets_observed": (
                winner["observed"] if winner["observed"] is not None else "UNKNOWN_NOT_OBSERVED"
            ),
            "cumulative_mission_logical_gets_observed_lower_bound": winner["lower_bound"],
            "mission_budget_accounting_basis": winner["basis"],
        }
    registry = tuple(
        {
            "ordinal": ordinal,
            "architecture_fingerprint": ordinals_to_fingerprints[ordinal],
        }
        for ordinal in sorted(ordinals_to_fingerprints)
    )
    return baseline, current_ordinal, pending, registry


def _validated_selection_mission_baseline(
    selection: Mapping[str, object],
    *,
    authority: CoverageAuthority,
) -> tuple[int, int | None, int, str]:
    baseline = _mapping(
        selection.get("mission_accounting_baseline"),
        label="P0_SELECTION_MISSION_ACCOUNTING_BASELINE",
    )
    if set(baseline) != {
        "schema_version",
        "source",
        "source_stage",
        "source_stage_receipt_sha256",
        "source_architecture_fingerprint",
        "source_receipt_ancestor_sha256s",
        "cumulative_mission_logical_gets_charged",
        "cumulative_mission_logical_gets_observed",
        "cumulative_mission_logical_gets_observed_lower_bound",
        "mission_budget_accounting_basis",
    }:
        raise ValueError("P0_SELECTION_MISSION_BASELINE_FIELDS_INVALID")
    source = _text(baseline.get("source"), label="P0_SELECTION_MISSION_BASELINE_SOURCE")
    charged = _integer(
        baseline.get("cumulative_mission_logical_gets_charged"),
        label="P0_SELECTION_MISSION_BASELINE_CHARGED",
    )
    lower_bound = _integer(
        baseline.get("cumulative_mission_logical_gets_observed_lower_bound"),
        label="P0_SELECTION_MISSION_BASELINE_LOWER_BOUND",
    )
    observed_value = baseline.get("cumulative_mission_logical_gets_observed")
    observed = (
        None
        if observed_value == "UNKNOWN_NOT_OBSERVED"
        else _integer(observed_value, label="P0_SELECTION_MISSION_BASELINE_OBSERVED")
    )
    basis = _text(
        baseline.get("mission_budget_accounting_basis"),
        label="P0_SELECTION_MISSION_BASELINE_BASIS",
    )
    ancestors = tuple(
        _sha(item, label="P0_SELECTION_MISSION_BASELINE_ANCESTOR")
        for item in _sequence(
            baseline.get("source_receipt_ancestor_sha256s"),
            label="P0_SELECTION_MISSION_BASELINE_ANCESTORS",
        )
    )
    ordinal = _integer(
        selection.get("architecture_ordinal"),
        label="P0_SELECTION_ARCHITECTURE_ORDINAL",
        minimum=1,
    )
    current_fingerprint = evidence_architecture_fingerprint(authority)
    registry = _mission_architecture_registry(
        selection.get("mission_architecture_registry"),
        label="P0_SELECTION_ARCHITECTURE_REGISTRY",
    )
    source_stage = baseline.get("source_stage")
    source_receipt = baseline.get("source_stage_receipt_sha256")
    source_fingerprint = baseline.get("source_architecture_fingerprint")
    source_binding_valid = False
    if source == "MISSION_START":
        source_binding_valid = (
            source_stage is None
            and source_receipt is None
            and source_fingerprint is None
            and not ancestors
            and charged == 0
            and observed == 0
            and lower_bound == 0
            and basis == MISSION_ACCOUNTING_EXACT
            and ordinal == 1
        )
    elif source == "STAGE_RECEIPT":
        parsed_stage = _text(source_stage, label="P0_SELECTION_MISSION_BASELINE_STAGE")
        parsed_receipt = _sha(
            source_receipt,
            label="P0_SELECTION_MISSION_BASELINE_RECEIPT",
        )
        parsed_fingerprint = _sha(
            source_fingerprint,
            label="P0_SELECTION_MISSION_BASELINE_ARCHITECTURE",
        )
        source_binding_valid = (
            parsed_stage in DOMAIN_STAGES
            and parsed_receipt not in ancestors
            and len(ancestors) == len(set(ancestors))
            and (parsed_fingerprint == current_fingerprint or ordinal == 2)
        )
    accounting_valid = (
        charged <= authority.limits.mission_gets
        and lower_bound <= charged
        and basis in {MISSION_ACCOUNTING_EXACT, MISSION_ACCOUNTING_CONSERVATIVE}
        and (
            basis != MISSION_ACCOUNTING_EXACT
            or observed is not None
            and observed == charged
            and lower_bound == charged
        )
        and (
            basis != MISSION_ACCOUNTING_CONSERVATIVE
            or observed is None
            or lower_bound <= observed <= charged
        )
    )
    if (
        baseline.get("schema_version") != MISSION_ACCOUNTING_BASELINE_SCHEMA
        or ordinal not in {1, 2}
        or len(registry) != ordinal
        or registry[-1] != (ordinal, current_fingerprint)
        or not source_binding_valid
        or not accounting_valid
    ):
        raise ValueError("P0_SELECTION_MISSION_BASELINE_INVALID")
    return charged, observed, lower_bound, basis


def _validate_live_selection_mission_baseline(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
) -> None:
    expected_baseline, expected_ordinal, pending, expected_registry = _mission_accounting_state(
        authority
    )
    selection_sha = _verify_signed(
        selection,
        field="selection_sha256",
        label="P0_LIVE_SELECTION",
    )
    current_receipt_path = (
        authority.root
        / "reports"
        / "coverage"
        / f"p0-evidence-ladder-stage-{authority.stage}-v1.json"
    )
    current_receipt_matches = False
    if current_receipt_path.exists():
        current_receipt = _load_json(
            current_receipt_path,
            label="P0_LIVE_CURRENT_STAGE_RECEIPT",
        )
        _verify_signed(
            current_receipt,
            field="stage_receipt_sha256",
            label="P0_LIVE_CURRENT_STAGE_RECEIPT",
        )
        current_receipt_matches = current_receipt.get("selection_sha256") == selection_sha
    pending_hashes = {item["selection_sha256"] for item in pending}
    if (
        selection.get("architecture_ordinal") != expected_ordinal
        or selection.get("mission_architecture_registry") != list(expected_registry)
        or (
            not current_receipt_matches
            and (
                selection_sha not in pending_hashes
                or selection.get("mission_accounting_baseline") != expected_baseline
            )
        )
    ):
        raise ValueError("P0_SELECTION_MISSION_BASELINE_STALE")


def validate_stage_attempt(
    authority: CoverageAuthority,
    *,
    operation: str,
    attempt_slot: int,
) -> None:
    """Reject duplicates and bind slot two to a safe prior failure."""

    if operation not in {"freeze", "measure"}:
        raise ValueError("P0_ATTEMPT_OPERATION_INVALID")
    if attempt_slot not in {1, 2}:
        raise ValueError("P0_ATTEMPT_SLOT_INVALID")
    selection_path = (
        authority.root
        / "configs"
        / "data"
        / f"p0-coverage-evidence-selection-{authority.stage}-v1.json"
    )
    stage_receipt_path = (
        authority.root
        / "reports"
        / "coverage"
        / f"p0-evidence-ladder-stage-{authority.stage}-v1.json"
    )
    if operation == "freeze":
        if selection_path.exists():
            existing = _load_json(
                selection_path,
                label="P0_EXISTING_STAGE_SELECTION",
            )
            _verify_signed(
                existing,
                field="selection_sha256",
                label="P0_EXISTING_STAGE_SELECTION",
            )
            if (
                existing.get("schema_version") != SELECTION_SCHEMA_VERSION
                or existing.get("mission_id") != authority.mission.get("mission_id")
                or existing.get("domain_stage") != authority.stage
                or _mapping(
                    existing.get("effects"),
                    label="P0_EXISTING_STAGE_SELECTION_EFFECTS",
                )
                != ZERO_EFFECTS
            ):
                raise ValueError("P0_EXISTING_STAGE_SELECTION_INVALID")
            if (
                existing.get("algorithm_version") == ALGORITHM_VERSION
                and existing.get("identity_architecture_hash")
                == authority.identity_architecture_hash
                and existing.get("absence_classification_framework_sha256")
                == ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
            ):
                raise ValueError("P0_STAGE_SELECTION_ALREADY_COMMITTED")
        baseline, architecture_ordinal, pending, _registry = _mission_accounting_state(authority)
        if pending:
            raise ValueError("P0_MISSION_PENDING_SELECTION_BLOCKS_FREEZE")
        if architecture_ordinal == 2 and attempt_slot != 1:
            raise ValueError("P0_ARCHITECTURE_TWO_FIRST_FREEZE_REQUIRES_SLOT_ONE")
        prior_charge = _integer(
            baseline.get("cumulative_mission_logical_gets_charged"),
            label="P0_FREEZE_MISSION_BASELINE_CHARGED",
        )
        freeze_attempt_charge = authority.limits.gets_per_job * attempt_slot
        if prior_charge + freeze_attempt_charge > authority.limits.mission_gets:
            raise ValueError("P0_FREEZE_ATTEMPT_MISSION_BUDGET_EXCEEDED")
        return
    selection = _load_json(selection_path, label="P0_CURRENT_STAGE_SELECTION")
    validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    _validate_live_selection_mission_baseline(
        authority,
        selection=selection,
    )
    if attempt_slot == 1:
        if stage_receipt_path.exists():
            existing_receipt = _load_json(
                stage_receipt_path,
                label="P0_EXISTING_STAGE_RECEIPT",
            )
            _verify_signed(
                existing_receipt,
                field="stage_receipt_sha256",
                label="P0_EXISTING_STAGE_RECEIPT",
            )
            if (
                existing_receipt.get("schema_version") != STAGE_SCHEMA_VERSION
                or existing_receipt.get("stage") != authority.stage
                or _mapping(
                    existing_receipt.get("effects"),
                    label="P0_EXISTING_STAGE_RECEIPT_EFFECTS",
                )
                != ZERO_EFFECTS
            ):
                raise ValueError("P0_EXISTING_STAGE_RECEIPT_INVALID")
            if existing_receipt.get(
                "architecture_fingerprint"
            ) == evidence_architecture_fingerprint(authority):
                raise ValueError("P0_STAGE_ATTEMPT_ALREADY_COMMITTED")
        return
    prior = _current_stage_receipt(authority, selection=selection)
    try:
        retry_baseline_gets, prior_observed, _prior_lower_bound, accounting_basis = (
            _validated_mission_accounting(
                prior,
                authority=authority,
                label="P0_SECOND_ATTEMPT_MISSION_ACCOUNTING",
            )
        )
    except ValueError:
        raise ValueError("P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT")
    common_failure = (
        prior.get("attempt_slot") == 1
        and prior.get("scale_gate") == "FAIL"
        and prior.get("scientific_gate") == "FAIL"
    )
    exact_scientific_failure = (
        prior.get("measurement_integrity_gate") == "PASS"
        and prior.get("read_accounting_gate") == "PASS"
        and prior.get("checkpoint_gate") == "PASS"
        and prior.get("domain_decision") == "FAIL_AND_REDESIGN"
        and prior.get("council_decision") == "FAIL_AND_REDESIGN"
        and prior.get("mission_budget_exact") is True
        and accounting_basis == MISSION_ACCOUNTING_EXACT
        and prior_observed == retry_baseline_gets
    )
    operational_interruption = (
        prior.get("measurement_integrity_gate") == "FAIL"
        and prior.get("read_accounting_gate") == "FAIL"
        and prior.get("checkpoint_gate") == "FAIL"
        and prior.get("domain_decision") == "FAIL_AND_STOP"
        and prior.get("council_decision") == "FAIL_AND_STOP"
        and prior.get("mission_budget_exact") is False
        and accounting_basis == MISSION_ACCOUNTING_CONSERVATIVE
        and prior_observed is None
        and (
            bool(prior.get("missing_partition_ids"))
            or _integer(
                prior.get("invalid_shards"),
                label="P0_SECOND_ATTEMPT_INVALID_SHARDS",
            )
            > 0
        )
    )
    if not common_failure or not (exact_scientific_failure or operational_interruption):
        raise ValueError("P0_SECOND_ATTEMPT_PRIOR_FAILURE_NOT_EXACT")
    if selection.get("architecture_ordinal") == 2 and exact_scientific_failure:
        _load_absence_taxonomy_supplement(
            authority,
            selection=selection,
            prior=prior,
        )
    retry_gets = sum(
        1
        + _integer(
            _mapping(item, label="P0_RETRY_PARTITION").get("planned_evidence_gets"),
            label="P0_RETRY_PLANNED_EVIDENCE_GETS",
        )
        for item in _sequence(
            selection.get("partitions"),
            label="P0_RETRY_PARTITIONS",
        )
    )
    if retry_baseline_gets + retry_gets > authority.limits.mission_gets:
        raise ValueError("P0_SECOND_ATTEMPT_MISSION_BUDGET_EXCEEDED")


def _scope_objects(
    authority: CoverageAuthority,
    inventory: VerifiedInventory,
) -> tuple[InventoryObject, ...]:
    competitions = set(authority.competitions)
    seasons = set(authority.seasons)
    in_scope = tuple(
        item
        for item in inventory.objects
        if item.competition in competitions and item.season in seasons
    )
    supported_sources = {
        ("fixtures", "fixtures"),
        ("fixtures", "fixtures/lineups"),
        ("fixtures", "fixtures/players"),
        ("fixtures", "fixtures/statistics"),
        ("events", "fixtures/events"),
        ("rounds", "fixtures/rounds"),
        ("standings", "standings"),
        ("players", "players"),
        ("injuries", "injuries"),
    }
    objects: list[InventoryObject] = []
    for item in in_scope:
        endpoint_segment = item.receipt_key.split("/")[5]
        endpoint = unquote(endpoint_segment.removeprefix("endpoint="))
        source = (item.family, endpoint)
        if source == ("fixtures", "leagues"):
            # Competition metadata is part of the signed replay inventory but is
            # not one of the sixteen P0 evidence families.
            continue
        if source not in supported_sources:
            raise ValueError(f"P0_INVENTORY_SOURCE_ENDPOINT_UNSUPPORTED:{item.family}:{endpoint}")
        objects.append(item)
    expected_scopes = {
        (competition, season)
        for competition in authority.competitions
        for season in authority.seasons
    }
    observed_scopes = {(item.competition, item.season) for item in objects}
    if observed_scopes != expected_scopes:
        raise ValueError("P0_INVENTORY_SCOPE_GRID_INCOMPLETE")
    return tuple(objects)


def _stage_scopes(
    authority: CoverageAuthority,
    objects: Sequence[InventoryObject],
) -> tuple[tuple[str, int], ...]:
    by_scope: dict[tuple[str, int], list[InventoryObject]] = defaultdict(list)
    for item in objects:
        by_scope[(item.competition, item.season)].append(item)
    if authority.stage in {"E1A", "E3A"}:
        ranked = sorted(
            by_scope,
            key=lambda scope: (
                -sum(item.logical_bytes for item in by_scope[scope]),
                scope[0],
                scope[1],
            ),
        )
        return (ranked[0],)
    if authority.stage in {"E1B", "E2", "E3B"}:
        # The last season in the frozen scope can be incomplete at capture time.
        # The immediately preceding common season is therefore the deterministic
        # completed-season canary (2024 for the pinned P0 grid).
        common_season = authority.seasons[-2]
        scopes = tuple((competition, common_season) for competition in authority.competitions)
        if any(scope not in by_scope for scope in scopes):
            raise ValueError("P0_COMMON_SEASON_SCOPE_MISSING")
        return scopes
    return tuple(
        (competition, season)
        for competition in authority.competitions
        for season in authority.seasons
    )


def _fixture_proof(
    row: Mapping[str, object],
    *,
    pair: VerifiedEvidencePair,
) -> Mapping[str, object]:
    fixture_id = row.get("provider_fixture_id")
    kickoff = row.get("target_kickoff_at")
    data = _mapping(row.get("data"), label="P0_FIXTURE_DATA")
    teams = _mapping(data.get("teams"), label="P0_FIXTURE_TEAMS")
    home = _mapping(teams.get("home"), label="P0_FIXTURE_HOME")
    away = _mapping(teams.get("away"), label="P0_FIXTURE_AWAY")
    home_id = home.get("id")
    away_id = away.get("id")
    if (
        isinstance(fixture_id, bool)
        or not isinstance(fixture_id, int)
        or fixture_id < 1
        or isinstance(home_id, bool)
        or not isinstance(home_id, int)
        or home_id < 1
        or isinstance(away_id, bool)
        or not isinstance(away_id, int)
        or away_id < 1
        or home_id == away_id
        or not isinstance(kickoff, str)
    ):
        raise ValueError("P0_FIXTURE_PROVIDER_IDENTITY_INVALID")
    try:
        kickoff_at = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("P0_FIXTURE_KICKOFF_INVALID") from None
    if kickoff_at.tzinfo is None or kickoff_at.utcoffset() is None:
        raise ValueError("P0_FIXTURE_KICKOFF_UTC_REQUIRED")
    canonical_fixture = f"api-football:fixture:{fixture_id}"
    if row.get("canonical_fixture_id") != canonical_fixture:
        raise ValueError("P0_FIXTURE_CANONICAL_ID_MISMATCH")
    source_record_hash = _sha(row.get("source_record_hash"), label="P0_FIXTURE_SOURCE_RECORD_HASH")
    competition_id = int(pair.entry.competition.split(":", 1)[1])
    if (
        row.get("provider_competition_id") != competition_id
        or row.get("season") != pair.entry.season
    ):
        raise ValueError("P0_FIXTURE_SCOPE_IDENTITY_MISMATCH")
    return {
        "fixture_id": fixture_id,
        "canonical_fixture_id": canonical_fixture,
        "kickoff_utc": kickoff_at.astimezone(UTC).isoformat(),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "source_object_id": pair.entry.object_id,
        "receipt_hash": pair.entry.receipt_hash,
        "payload_sha256": pair.entry.payload_sha256,
        "source_record_hash": source_record_hash,
    }


def _is_full_fixture_scope_receipt(
    receipt: HarvestReceipt,
    *,
    competition: str,
    season: int,
) -> bool:
    """Recognize only the league-season fixture census query.

    Fixture bundles (``ids``), point lookups, date windows, team filters, and
    round filters are deliberately excluded. They cannot prove the global
    earliest-fixture ordering required by the frozen sample.
    """

    league_id = int(competition.split(":", 1)[1])
    parameters = dict(receipt.parameters)
    page_parameter = parameters.pop("page", receipt.page)
    return (
        receipt.competition == competition
        and receipt.season == season
        and receipt.family == "fixtures"
        and receipt.endpoint.strip("/").casefold() == "fixtures"
        and page_parameter == receipt.page
        and parameters == {"league": league_id, "season": season}
    )


def _newest_page_candidate(
    candidates: Sequence[tuple[HarvestReceipt, InventoryObject]],
    *,
    page: int,
) -> tuple[HarvestReceipt, InventoryObject]:
    matching = tuple(item for item in candidates if item[0].page == page)
    if not matching:
        raise ValueError("P0_FIXTURE_FULL_SCOPE_PAGE_MISSING")
    return sorted(
        matching,
        key=lambda item: (
            -item[0].completed_at.timestamp(),
            str(getattr(item[1], "object_id", "")),
        ),
    )[0]


def _fixture_payload_total(pair: VerifiedEvidencePair) -> int:
    payload = _mapping(pair.payload, label="P0_FIXTURE_FULL_SCOPE_PAYLOAD")
    paging = _mapping(payload.get("paging"), label="P0_FIXTURE_FULL_SCOPE_PAGING")
    current = _integer(
        paging.get("current"),
        label="P0_FIXTURE_FULL_SCOPE_CURRENT",
        minimum=1,
    )
    total = _integer(
        paging.get("total"),
        label="P0_FIXTURE_FULL_SCOPE_TOTAL",
        minimum=1,
    )
    if current != pair.receipt.page:
        raise ValueError("P0_FIXTURE_FULL_SCOPE_PAGE_MISMATCH")
    return total


def _sample_fixtures(
    reader: PinnedInventoryReader,
    *,
    objects: Sequence[InventoryObject],
    competition: str,
    season: int,
    target: int,
) -> tuple[tuple[Mapping[str, object], ...], tuple[str, ...]]:
    fixture_entries = tuple(
        item
        for item in objects
        if item.competition == competition
        and item.season == season
        and item.family == "fixtures"
        and "/endpoint=fixtures/" in item.receipt_key
    )
    if not fixture_entries:
        raise ValueError("P0_FIXTURE_SOURCE_OBJECTS_MISSING")
    # Receipts are small enough to inspect within the frozen reader envelope.
    # Reading every payload is not: the pinned 2024 inventory contains many
    # overlapping ``ids`` bundles. Select the one complete league-season query
    # from receipt metadata, then fetch only its required page payloads.
    receipts = tuple((reader.fetch_receipt(item.object_id), item) for item in fixture_entries)
    full_scope = tuple(
        item
        for item in receipts
        if _is_full_fixture_scope_receipt(
            item[0],
            competition=competition,
            season=season,
        )
    )
    if not full_scope:
        raise ValueError("P0_FIXTURE_FULL_SCOPE_CENSUS_MISSING")
    first_receipt, first_entry = _newest_page_candidate(full_scope, page=1)
    del first_receipt
    if (
        reader.telemetry.bootstrap_requested + reader.telemetry.evidence_gets + 1
        > reader.limits.gets_per_job
    ):
        raise ValueError("P0_FIXTURE_FULL_SCOPE_CENSUS_BUDGET_EXCEEDED")
    first_pair = reader.fetch_pair(first_entry.object_id)
    pages_expected = _fixture_payload_total(first_pair)
    selected_entries = [first_entry]
    for page in range(2, pages_expected + 1):
        _receipt, entry = _newest_page_candidate(full_scope, page=page)
        selected_entries.append(entry)
    remaining_payloads = len(selected_entries) - 1
    if (
        reader.telemetry.bootstrap_requested + reader.telemetry.evidence_gets + remaining_payloads
        > reader.limits.gets_per_job
    ):
        raise ValueError("P0_FIXTURE_FULL_SCOPE_CENSUS_BUDGET_EXCEEDED")
    pairs = (first_pair,) + tuple(
        reader.fetch_pair(entry.object_id) for entry in selected_entries[1:]
    )
    pagination = _pagination_evidence(
        pairs,
        raw_family="fixtures",
        endpoint="fixtures",
    )
    if (
        pagination.get("status") != "COMPLETE"
        or pagination.get("query_scopes") != 1
        or pagination.get("pages_expected") != len(pairs)
    ):
        raise ValueError("P0_FIXTURE_FULL_SCOPE_CENSUS_INCOMPLETE")
    candidates: dict[int, Mapping[str, object]] = {}
    for pair in pairs:
        for row in pair.normalized.get("fixtures", ()):
            proof = _fixture_proof(row, pair=pair)
            fixture_id = cast(int, proof["fixture_id"])
            if fixture_id in candidates:
                raise ValueError("P0_FIXTURE_FULL_SCOPE_IDENTITY_DUPLICATED")
            candidates[fixture_id] = proof
    ordered = tuple(
        sorted(
            candidates.values(),
            key=lambda item: (
                _text(item.get("kickoff_utc"), label="P0_FIXTURE_KICKOFF"),
                _integer(item.get("fixture_id"), label="P0_FIXTURE_ID", minimum=1),
            ),
        )[:target]
    )
    if len(ordered) != target:
        raise ValueError("P0_FIXTURE_SAMPLE_TARGET_NOT_MET")
    return ordered, tuple(sorted(entry.object_id for entry in selected_entries))


def _partition_id(
    *,
    stage: str,
    competition: str,
    season: int,
    family_group: str,
) -> str:
    league_id = competition.split(":", 1)[1]
    group = "all16" if family_group == "ALL_16" else family_group.casefold().replace("_", "-")
    partition_id = f"p0-{stage.casefold()}-{league_id}-{season}-{group}"
    if SAFE_ID.fullmatch(partition_id) is None:
        raise ValueError("P0_PARTITION_ID_INVALID")
    return partition_id


def freeze_selection(
    authority: CoverageAuthority,
    *,
    inventory: VerifiedInventory,
    reader: PinnedInventoryReader,
    code_revision: str,
    attempt_slot: int,
) -> Mapping[str, object]:
    """Freeze exact sample identities and/or immutable inventory object IDs."""

    if HEX40.fullmatch(code_revision) is None:
        raise ValueError("P0_FREEZE_CODE_REVISION_INVALID")
    if attempt_slot not in {1, 2}:
        raise ValueError("P0_FREEZE_ATTEMPT_SLOT_INVALID")
    validate_predecessor(authority)
    scope_objects = _scope_objects(authority, inventory)
    scopes = _stage_scopes(authority, scope_objects)
    sample_target = {"E1A": 10, "E1B": 2, "E2": 20}.get(authority.stage)
    fixture_samples: list[dict[str, object]] = []
    freeze_evidence_ids: set[str] = set()
    if sample_target is not None:
        for competition, season in scopes:
            fixtures, evidence_ids = _sample_fixtures(
                reader,
                objects=scope_objects,
                competition=competition,
                season=season,
                target=sample_target,
            )
            fixture_samples.append(
                {
                    "competition": competition,
                    "season": season,
                    "fixture_count": len(fixtures),
                    "fixtures": list(fixtures),
                }
            )
            freeze_evidence_ids.update(evidence_ids)

    partitions: list[dict[str, object]] = []
    family_groups = ("ALL_16",) if sample_target is not None else tuple(FAMILY_GROUPS)
    for competition, season in scopes:
        scoped = tuple(
            item
            for item in scope_objects
            if item.competition == competition and item.season == season
        )
        for family_group in family_groups:
            raw_families = (
                frozenset(authority.raw_families)
                if family_group == "ALL_16"
                else RAW_FAMILIES_BY_GROUP[family_group]
            )
            selected = tuple(item for item in scoped if item.family in raw_families)
            if not selected:
                raise ValueError("P0_PARTITION_SOURCE_OBJECTS_EMPTY")
            planned_gets = len(selected) * 2
            planned_stored = sum(item.stored_bytes for item in selected)
            planned_logical = sum(item.logical_bytes for item in selected)
            if (
                planned_gets + authority.limits.bootstrap_gets > authority.limits.gets_per_job
                or planned_stored > authority.limits.stored_bytes_per_job
                or planned_logical > authority.limits.logical_bytes_per_job
            ):
                raise ValueError("P0_PARTITION_BUDGET_EXCEEDED")
            partitions.append(
                {
                    "partition_id": _partition_id(
                        stage=authority.stage,
                        competition=competition,
                        season=season,
                        family_group=family_group,
                    ),
                    "competition": competition,
                    "season": season,
                    "family_group": family_group,
                    "normalized_families": (
                        list(authority.normalized_families)
                        if family_group == "ALL_16"
                        else list(FAMILY_GROUPS[family_group])
                    ),
                    "evidence_object_ids": [item.object_id for item in selected],
                    "planned_evidence_gets": planned_gets,
                    "planned_payload_stored_bytes": planned_stored,
                    "planned_payload_logical_bytes": planned_logical,
                }
            )
    if len(partitions) > 120 or len({item["partition_id"] for item in partitions}) != len(
        partitions
    ):
        raise ValueError("P0_PARTITION_MATRIX_INVALID")
    (
        mission_accounting_baseline,
        architecture_ordinal,
        pending,
        mission_architecture_registry,
    ) = _mission_accounting_state(authority)
    if pending:
        raise ValueError("P0_MISSION_PENDING_SELECTION_BLOCKS_FREEZE")
    baseline_charged_gets = _integer(
        mission_accounting_baseline.get("cumulative_mission_logical_gets_charged"),
        label="P0_FREEZE_MISSION_BASELINE_CHARGED",
    )
    failed_freeze_conservative_charge = authority.limits.gets_per_job if attempt_slot == 2 else 0
    freeze_observed_logical_gets = 1 + reader.telemetry.evidence_gets
    planned_mission_gets = (
        baseline_charged_gets
        + failed_freeze_conservative_charge
        + freeze_observed_logical_gets
        + sum(1 + cast(int, item["planned_evidence_gets"]) for item in partitions)
    )
    if planned_mission_gets > authority.limits.mission_gets:
        raise ValueError("P0_MISSION_GET_BUDGET_EXCEEDED")
    unsigned: dict[str, object] = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "mission_id": authority.mission["mission_id"],
        "domain_stage": authority.stage,
        "council_stage": authority.council_stage,
        "scope_id": "P0_2020_2025",
        "source_config_sha256": authority.source_config_sha256,
        "mission_sha256": authority.mission_sha256,
        "stage_mapping_sha256": authority.mapping_sha256,
        "inventory_sha256": inventory.manifest_sha256,
        "identity_architecture_hash": authority.identity_architecture_hash,
        "algorithm_version": ALGORITHM_VERSION,
        "absence_classification_framework_sha256": (
            ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        ),
        "architecture_ordinal": architecture_ordinal,
        "mission_architecture_registry": list(mission_architecture_registry),
        "freeze_code_revision": code_revision,
        "competition_seasons": [
            {"competition": competition, "season": season} for competition, season in scopes
        ],
        "fixture_selection": {
            "policy": (
                "KICKOFF_UTC_THEN_PROVIDER_FIXTURE_ID"
                if sample_target is not None
                else "ALL_FIXTURES_FROM_FROZEN_INVENTORY_OBJECT_SET"
            ),
            "target_per_competition": sample_target,
            "samples": fixture_samples,
            "evidence_object_ids": sorted(freeze_evidence_ids),
        },
        "partitions": partitions,
        "partition_count": len(partitions),
        "mission_accounting_baseline": dict(mission_accounting_baseline),
        "freeze_attempt_slot": attempt_slot,
        "failed_freeze_conservative_charge": failed_freeze_conservative_charge,
        "freeze_observed_logical_gets": freeze_observed_logical_gets,
        "planned_mission_logical_gets": planned_mission_gets,
        "closure_policy": {
            "real_cell_closure_forbidden": authority.stage in {"E1A", "E1B", "E2"},
            "authoritative_denominator_required": True,
            "unknown_is_not_zero": True,
            "inventory_rows_received_is_denominator": False,
        },
        "effects": dict(ZERO_EFFECTS),
    }
    selection = _signed(unsigned, field="selection_sha256")
    validate_selection_inventory_binding(
        authority,
        selection=selection,
        inventory=inventory,
    )
    return selection


def _contains_r2_key(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith("historical-deep-data/schema-v1/")
    if isinstance(value, Mapping):
        return any(_contains_r2_key(key) or _contains_r2_key(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_r2_key(item) for item in value)
    return False


def validate_selection(
    selection: Mapping[str, object],
    *,
    authority: CoverageAuthority,
    stage: str,
) -> str:
    signature = _verify_signed(selection, field="selection_sha256", label="P0_SELECTION")
    expected_root_fields = {
        "schema_version",
        "mission_id",
        "domain_stage",
        "council_stage",
        "scope_id",
        "source_config_sha256",
        "mission_sha256",
        "stage_mapping_sha256",
        "inventory_sha256",
        "identity_architecture_hash",
        "algorithm_version",
        "absence_classification_framework_sha256",
        "architecture_ordinal",
        "mission_architecture_registry",
        "freeze_code_revision",
        "competition_seasons",
        "fixture_selection",
        "partitions",
        "partition_count",
        "mission_accounting_baseline",
        "freeze_attempt_slot",
        "failed_freeze_conservative_charge",
        "freeze_observed_logical_gets",
        "planned_mission_logical_gets",
        "closure_policy",
        "effects",
        "selection_sha256",
    }
    if (
        set(selection) != expected_root_fields
        or stage not in DOMAIN_STAGES
        or authority.stage != stage
        or selection.get("schema_version") != SELECTION_SCHEMA_VERSION
        or selection.get("mission_id") != authority.mission.get("mission_id")
        or selection.get("domain_stage") != stage
        or selection.get("council_stage") != authority.council_stage
        or selection.get("scope_id") != "P0_2020_2025"
        or selection.get("source_config_sha256") != authority.source_config_sha256
        or selection.get("mission_sha256") != authority.mission_sha256
        or selection.get("stage_mapping_sha256") != authority.mapping_sha256
        or selection.get("identity_architecture_hash") != authority.identity_architecture_hash
        or selection.get("algorithm_version") != ALGORITHM_VERSION
        or selection.get("absence_classification_framework_sha256")
        != ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        or HEX64.fullmatch(str(selection.get("inventory_sha256"))) is None
        or HEX40.fullmatch(str(selection.get("freeze_code_revision"))) is None
        or _contains_r2_key(selection)
    ):
        raise ValueError("P0_SELECTION_BINDING_INVALID")

    scope_values = tuple(
        _mapping(item, label="P0_SELECTION_SCOPE")
        for item in _sequence(
            selection.get("competition_seasons"),
            label="P0_SELECTION_SCOPES",
        )
    )
    if any(set(item) != {"competition", "season"} for item in scope_values):
        raise ValueError("P0_SELECTION_SCOPE_FIELDS_INVALID")
    scopes = tuple(
        (
            _text(item.get("competition"), label="P0_SELECTION_COMPETITION"),
            _integer(item.get("season"), label="P0_SELECTION_SEASON", minimum=1888),
        )
        for item in scope_values
    )
    allowed_scopes = {
        (competition, season)
        for competition in authority.competitions
        for season in authority.seasons
    }
    expected_scope_counts = {"E1A": 1, "E1B": 5, "E2": 5, "E3A": 1, "E3B": 5, "E4": 30}
    if (
        len(scopes) != expected_scope_counts[stage]
        or len(set(scopes)) != len(scopes)
        or any(scope not in allowed_scopes for scope in scopes)
    ):
        raise ValueError("P0_SELECTION_SCOPE_SHAPE_INVALID")
    if stage in {"E1B", "E2", "E3B"}:
        expected_scopes = tuple(
            (competition, authority.seasons[-2]) for competition in authority.competitions
        )
        if scopes != expected_scopes:
            raise ValueError("P0_SELECTION_COMMON_SEASON_SCOPE_INVALID")
    elif stage == "E4":
        expected_scopes = tuple(
            (competition, season)
            for competition in authority.competitions
            for season in authority.seasons
        )
        if scopes != expected_scopes:
            raise ValueError("P0_SELECTION_FULL_GRID_SCOPE_INVALID")

    fixture_selection = _mapping(
        selection.get("fixture_selection"),
        label="P0_SELECTION_FIXTURE_SELECTION",
    )
    if set(fixture_selection) != {
        "policy",
        "target_per_competition",
        "samples",
        "evidence_object_ids",
    }:
        raise ValueError("P0_SELECTION_FIXTURE_SELECTION_FIELDS_INVALID")
    sample_target = {"E1A": 10, "E1B": 2, "E2": 20}.get(stage)
    expected_policy = (
        "KICKOFF_UTC_THEN_PROVIDER_FIXTURE_ID"
        if sample_target is not None
        else "ALL_FIXTURES_FROM_FROZEN_INVENTORY_OBJECT_SET"
    )
    samples = tuple(
        _mapping(item, label="P0_SELECTION_FIXTURE_SAMPLE")
        for item in _sequence(
            fixture_selection.get("samples"),
            label="P0_SELECTION_FIXTURE_SAMPLES",
        )
    )
    freeze_evidence_ids = tuple(
        _sha(item, label="P0_SELECTION_FREEZE_EVIDENCE_ID")
        for item in _sequence(
            fixture_selection.get("evidence_object_ids"),
            label="P0_SELECTION_FREEZE_EVIDENCE_IDS",
        )
    )
    if (
        fixture_selection.get("policy") != expected_policy
        or fixture_selection.get("target_per_competition") != sample_target
        or list(freeze_evidence_ids) != sorted(freeze_evidence_ids)
        or len(freeze_evidence_ids) != len(set(freeze_evidence_ids))
    ):
        raise ValueError("P0_SELECTION_FIXTURE_POLICY_INVALID")
    if sample_target is None:
        if samples or freeze_evidence_ids:
            raise ValueError("P0_SELECTION_UNEXPECTED_FIXTURE_SAMPLE")
    else:
        if len(samples) != len(scopes) or not freeze_evidence_ids:
            raise ValueError("P0_SELECTION_FIXTURE_SAMPLE_COUNT_INVALID")
        fixture_ids_seen: set[int] = set()
        proof_object_ids: set[str] = set()
        proof_fields = {
            "fixture_id",
            "canonical_fixture_id",
            "kickoff_utc",
            "home_team_id",
            "away_team_id",
            "source_object_id",
            "receipt_hash",
            "payload_sha256",
            "source_record_hash",
        }
        for sample, scope in zip(samples, scopes, strict=True):
            if set(sample) != {"competition", "season", "fixture_count", "fixtures"}:
                raise ValueError("P0_SELECTION_FIXTURE_SAMPLE_FIELDS_INVALID")
            sample_scope = (
                _text(sample.get("competition"), label="P0_SELECTION_SAMPLE_COMPETITION"),
                _integer(sample.get("season"), label="P0_SELECTION_SAMPLE_SEASON", minimum=1888),
            )
            fixtures = tuple(
                _mapping(item, label="P0_SELECTION_FIXTURE_PROOF")
                for item in _sequence(
                    sample.get("fixtures"),
                    label="P0_SELECTION_FIXTURE_PROOFS",
                )
            )
            if (
                sample_scope != scope
                or sample.get("fixture_count") != sample_target
                or len(fixtures) != sample_target
            ):
                raise ValueError("P0_SELECTION_FIXTURE_SAMPLE_SHAPE_INVALID")
            ordering: list[tuple[datetime, int]] = []
            for proof in fixtures:
                if set(proof) != proof_fields:
                    raise ValueError("P0_SELECTION_FIXTURE_PROOF_FIELDS_INVALID")
                fixture_id = _integer(
                    proof.get("fixture_id"),
                    label="P0_SELECTION_FIXTURE_ID",
                    minimum=1,
                )
                home_team_id = _integer(
                    proof.get("home_team_id"),
                    label="P0_SELECTION_HOME_TEAM_ID",
                    minimum=1,
                )
                away_team_id = _integer(
                    proof.get("away_team_id"),
                    label="P0_SELECTION_AWAY_TEAM_ID",
                    minimum=1,
                )
                kickoff = _text(
                    proof.get("kickoff_utc"),
                    label="P0_SELECTION_FIXTURE_KICKOFF",
                )
                try:
                    kickoff_at = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
                except ValueError:
                    raise ValueError("P0_SELECTION_FIXTURE_KICKOFF_INVALID") from None
                source_object_id = _sha(
                    proof.get("source_object_id"),
                    label="P0_SELECTION_FIXTURE_SOURCE_OBJECT_ID",
                )
                if (
                    home_team_id == away_team_id
                    or fixture_id in fixture_ids_seen
                    or proof.get("canonical_fixture_id") != f"api-football:fixture:{fixture_id}"
                    or kickoff_at.tzinfo is None
                    or kickoff_at.utcoffset() is None
                    or kickoff_at.astimezone(UTC).isoformat() != kickoff
                ):
                    raise ValueError("P0_SELECTION_FIXTURE_IDENTITY_INVALID")
                _sha(proof.get("receipt_hash"), label="P0_SELECTION_FIXTURE_RECEIPT_HASH")
                _sha(proof.get("payload_sha256"), label="P0_SELECTION_FIXTURE_PAYLOAD_HASH")
                _sha(
                    proof.get("source_record_hash"),
                    label="P0_SELECTION_FIXTURE_SOURCE_RECORD_HASH",
                )
                fixture_ids_seen.add(fixture_id)
                proof_object_ids.add(source_object_id)
                ordering.append((kickoff_at, fixture_id))
            if ordering != sorted(ordering):
                raise ValueError("P0_SELECTION_FIXTURE_ORDER_INVALID")
        if not proof_object_ids.issubset(set(freeze_evidence_ids)):
            raise ValueError("P0_SELECTION_FIXTURE_EVIDENCE_BINDING_INVALID")

    partitions = tuple(
        _mapping(item, label="P0_SELECTION_PARTITION")
        for item in _sequence(selection.get("partitions"), label="P0_SELECTION_PARTITIONS")
    )
    expected_partition_counts = {"E1A": 1, "E1B": 5, "E2": 5, "E3A": 4, "E3B": 20, "E4": 120}
    family_groups = ("ALL_16",) if sample_target is not None else tuple(FAMILY_GROUPS)
    expected_partition_specs = tuple(
        (scope[0], scope[1], family_group) for scope in scopes for family_group in family_groups
    )
    if (
        len(partitions) != expected_partition_counts[stage]
        or selection.get("partition_count") != len(partitions)
        or len(
            {
                _text(
                    item.get("partition_id"),
                    label="P0_SELECTION_PARTITION_ID",
                )
                for item in partitions
            }
        )
        != len(partitions)
    ):
        raise ValueError("P0_SELECTION_PARTITIONS_INVALID")
    partition_object_ids: set[str] = set()
    for partition, expected_spec in zip(partitions, expected_partition_specs, strict=True):
        if set(partition) != {
            "partition_id",
            "competition",
            "season",
            "family_group",
            "normalized_families",
            "evidence_object_ids",
            "planned_evidence_gets",
            "planned_payload_stored_bytes",
            "planned_payload_logical_bytes",
        }:
            raise ValueError("P0_SELECTION_PARTITION_FIELDS_INVALID")
        partition_id = _text(partition.get("partition_id"), label="P0_SELECTION_PARTITION_ID")
        competition = _text(
            partition.get("competition"),
            label="P0_SELECTION_PARTITION_COMPETITION",
        )
        season = _integer(
            partition.get("season"),
            label="P0_SELECTION_PARTITION_SEASON",
            minimum=1888,
        )
        family_group = _text(
            partition.get("family_group"),
            label="P0_SELECTION_PARTITION_FAMILY_GROUP",
        )
        normalized_families = tuple(
            _text(item, label="P0_SELECTION_NORMALIZED_FAMILY")
            for item in _sequence(
                partition.get("normalized_families"),
                label="P0_SELECTION_NORMALIZED_FAMILIES",
            )
        )
        object_ids = tuple(
            _sha(item, label="P0_SELECTION_OBJECT_ID")
            for item in _sequence(
                partition.get("evidence_object_ids"),
                label="P0_SELECTION_OBJECT_IDS",
            )
        )
        planned_gets = _integer(
            partition.get("planned_evidence_gets"),
            label="P0_SELECTION_PLANNED_GETS",
        )
        planned_stored = _integer(
            partition.get("planned_payload_stored_bytes"),
            label="P0_SELECTION_PLANNED_STORED_BYTES",
        )
        planned_logical = _integer(
            partition.get("planned_payload_logical_bytes"),
            label="P0_SELECTION_PLANNED_LOGICAL_BYTES",
        )
        expected_normalized_families = (
            authority.normalized_families
            if family_group == "ALL_16"
            else FAMILY_GROUPS.get(family_group, ())
        )
        if (
            SAFE_ID.fullmatch(partition_id) is None
            or (competition, season, family_group) != expected_spec
            or partition_id
            != _partition_id(
                stage=stage,
                competition=competition,
                season=season,
                family_group=family_group,
            )
            or normalized_families != tuple(expected_normalized_families)
            or not object_ids
            or len(object_ids) != len(set(object_ids))
            or planned_gets != len(object_ids) * 2
            or planned_gets + authority.limits.bootstrap_gets > authority.limits.gets_per_job
            or planned_stored > authority.limits.stored_bytes_per_job
            or planned_logical > authority.limits.logical_bytes_per_job
        ):
            raise ValueError("P0_SELECTION_PARTITION_BUDGET_INVALID")
        partition_object_ids.update(object_ids)
    if not set(freeze_evidence_ids).issubset(partition_object_ids):
        raise ValueError("P0_SELECTION_FREEZE_EVIDENCE_NOT_MEASURED")
    baseline_charged_gets, _baseline_observed, _baseline_lower_bound, _baseline_basis = (
        _validated_selection_mission_baseline(
            selection,
            authority=authority,
        )
    )
    freeze_attempt_slot = _integer(
        selection.get("freeze_attempt_slot"),
        label="P0_SELECTION_FREEZE_ATTEMPT_SLOT",
        minimum=1,
    )
    failed_freeze_conservative_charge = _integer(
        selection.get("failed_freeze_conservative_charge"),
        label="P0_SELECTION_FAILED_FREEZE_CHARGE",
    )
    expected_failed_freeze_charge = authority.limits.gets_per_job if freeze_attempt_slot == 2 else 0
    planned_mission_gets = _integer(
        selection.get("planned_mission_logical_gets"),
        label="P0_SELECTION_MISSION_GETS",
    )
    freeze_observed_logical_gets = _integer(
        selection.get("freeze_observed_logical_gets"),
        label="P0_SELECTION_FREEZE_OBSERVED_GETS",
        minimum=1,
    )
    minimum_freeze_gets = authority.limits.bootstrap_gets + len(freeze_evidence_ids) * 2
    exact_mission_gets = (
        baseline_charged_gets
        + failed_freeze_conservative_charge
        + freeze_observed_logical_gets
        + sum(
            1
            + len(_sequence(partition.get("evidence_object_ids"), label="P0_SELECTION_OBJECT_IDS"))
            * 2
            for partition in partitions
        )
    )
    if (
        freeze_attempt_slot not in {1, 2}
        or failed_freeze_conservative_charge != expected_failed_freeze_charge
        or freeze_observed_logical_gets < minimum_freeze_gets
        or freeze_observed_logical_gets > authority.limits.gets_per_job
        or planned_mission_gets != exact_mission_gets
        or planned_mission_gets > authority.limits.mission_gets
    ):
        raise ValueError("P0_SELECTION_MISSION_BUDGET_INVALID")
    closure_policy = _mapping(
        selection.get("closure_policy"),
        label="P0_SELECTION_CLOSURE_POLICY",
    )
    if closure_policy != {
        "real_cell_closure_forbidden": stage in {"E1A", "E1B", "E2"},
        "authoritative_denominator_required": True,
        "unknown_is_not_zero": True,
        "inventory_rows_received_is_denominator": False,
    }:
        raise ValueError("P0_SELECTION_CLOSURE_POLICY_INVALID")
    if _mapping(selection.get("effects"), label="P0_SELECTION_EFFECTS") != ZERO_EFFECTS:
        raise ValueError("P0_SELECTION_EFFECT_NONZERO")
    return signature


def build_partition_plan(
    selection: Mapping[str, object],
    *,
    authority: CoverageAuthority,
) -> Mapping[str, object]:
    selection_sha = validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    partitions = [
        {
            "partition_id": _text(
                _mapping(item, label="P0_PLAN_PARTITION").get("partition_id"),
                label="P0_PLAN_PARTITION_ID",
            )
        }
        for item in _sequence(selection.get("partitions"), label="P0_PLAN_PARTITIONS")
    ]
    unsigned: dict[str, object] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "stage": authority.stage,
        "selection_sha256": selection_sha,
        "partition_count": len(partitions),
        "partitions": partitions,
        "matrix": {"include": partitions},
        "max_parallel": 5,
    }
    return _signed(unsigned, field="plan_sha256")


def validate_selection_inventory_binding(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    inventory: VerifiedInventory,
) -> None:
    """Recompute every selected object set and budget from the pinned inventory."""

    validate_selection(selection, authority=authority, stage=authority.stage)
    if selection.get("inventory_sha256") != inventory.manifest_sha256:
        raise ValueError("P0_SELECTION_INVENTORY_BINDING_MISMATCH")
    scope_objects = _scope_objects(authority, inventory)
    inventory_index = inventory.by_id
    for partition_value in _sequence(
        selection.get("partitions"),
        label="P0_INVENTORY_BOUND_PARTITIONS",
    ):
        partition = _mapping(
            partition_value,
            label="P0_INVENTORY_BOUND_PARTITION",
        )
        competition = _text(
            partition.get("competition"),
            label="P0_INVENTORY_BOUND_COMPETITION",
        )
        season = _integer(
            partition.get("season"),
            label="P0_INVENTORY_BOUND_SEASON",
            minimum=1888,
        )
        family_group = _text(
            partition.get("family_group"),
            label="P0_INVENTORY_BOUND_FAMILY_GROUP",
        )
        raw_families = (
            frozenset(authority.raw_families)
            if family_group == "ALL_16"
            else RAW_FAMILIES_BY_GROUP[family_group]
        )
        expected_entries = tuple(
            item
            for item in scope_objects
            if item.competition == competition
            and item.season == season
            and item.family in raw_families
        )
        observed_ids = tuple(
            _sha(item, label="P0_INVENTORY_BOUND_OBJECT_ID")
            for item in _sequence(
                partition.get("evidence_object_ids"),
                label="P0_INVENTORY_BOUND_OBJECT_IDS",
            )
        )
        if (
            observed_ids != tuple(item.object_id for item in expected_entries)
            or partition.get("planned_evidence_gets") != len(expected_entries) * 2
            or partition.get("planned_payload_stored_bytes")
            != sum(item.stored_bytes for item in expected_entries)
            or partition.get("planned_payload_logical_bytes")
            != sum(item.logical_bytes for item in expected_entries)
        ):
            raise ValueError("P0_SELECTION_INVENTORY_OBJECT_SET_MISMATCH")

    fixture_selection = _mapping(
        selection.get("fixture_selection"),
        label="P0_INVENTORY_BOUND_FIXTURE_SELECTION",
    )
    for sample_value in _sequence(
        fixture_selection.get("samples"),
        label="P0_INVENTORY_BOUND_FIXTURE_SAMPLES",
    ):
        sample = _mapping(sample_value, label="P0_INVENTORY_BOUND_FIXTURE_SAMPLE")
        competition = _text(
            sample.get("competition"),
            label="P0_INVENTORY_BOUND_SAMPLE_COMPETITION",
        )
        season = _integer(
            sample.get("season"),
            label="P0_INVENTORY_BOUND_SAMPLE_SEASON",
            minimum=1888,
        )
        for proof_value in _sequence(
            sample.get("fixtures"),
            label="P0_INVENTORY_BOUND_FIXTURE_PROOFS",
        ):
            proof = _mapping(
                proof_value,
                label="P0_INVENTORY_BOUND_FIXTURE_PROOF",
            )
            object_id = _sha(
                proof.get("source_object_id"),
                label="P0_INVENTORY_BOUND_SOURCE_OBJECT_ID",
            )
            try:
                entry = inventory_index[object_id]
            except KeyError:
                raise ValueError("P0_FIXTURE_PROOF_OBJECT_NOT_IN_INVENTORY") from None
            if (
                entry.competition != competition
                or entry.season != season
                or entry.family != "fixtures"
                or proof.get("receipt_hash") != entry.receipt_hash
                or proof.get("payload_sha256") != entry.payload_sha256
            ):
                raise ValueError("P0_FIXTURE_PROOF_INVENTORY_BINDING_MISMATCH")


def _payload_records(payload: object) -> tuple[object, ...]:
    if not isinstance(payload, Mapping):
        return ()
    response = payload.get("response")
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
        return tuple(response)
    return ()


def _select_full_fixture_pairs(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    competition: str,
    season: int,
) -> tuple[VerifiedEvidencePair, ...]:
    candidates = tuple(
        pair
        for pair in pairs
        if _is_full_fixture_scope_receipt(
            pair.receipt,
            competition=competition,
            season=season,
        )
    )
    if not candidates:
        return ()

    def newest(page: int) -> VerifiedEvidencePair:
        matching = tuple(pair for pair in candidates if pair.receipt.page == page)
        if not matching:
            raise ValueError("P0_FIXTURE_FULL_SCOPE_PAGE_MISSING")
        return sorted(
            matching,
            key=lambda pair: (
                -pair.receipt.completed_at.timestamp(),
                pair.entry.object_id,
            ),
        )[0]

    first = newest(1)
    selected = (first,) + tuple(
        newest(page) for page in range(2, _fixture_payload_total(first) + 1)
    )
    pagination = _pagination_evidence(
        selected,
        raw_family="fixtures",
        endpoint="fixtures",
    )
    if (
        pagination.get("status") != "COMPLETE"
        or pagination.get("query_scopes") != 1
        or pagination.get("pages_expected") != len(selected)
    ):
        raise ValueError("P0_FIXTURE_FULL_SCOPE_CENSUS_INCOMPLETE")
    return selected


def _select_required_fixture_census_pairs(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    target_families: Sequence[str],
    competition: str,
    season: int,
) -> tuple[VerifiedEvidencePair, ...]:
    """Read a fixture census only for cells whose calculation depends on it."""

    if FIXTURE_CENSUS_DEPENDENT_FAMILIES.isdisjoint(target_families):
        return ()
    return _select_full_fixture_pairs(
        pairs,
        competition=competition,
        season=season,
    )


def _pair_matches_family_source(pair: VerifiedEvidencePair, *, family: str) -> bool:
    raw_family, endpoint = FAMILY_SOURCE_BINDINGS[family]
    direct = (
        pair.entry.family == raw_family and pair.receipt.endpoint.strip("/").casefold() == endpoint
    )
    if direct:
        return True
    # The pinned harvest also contains intentional ``/fixtures?ids=...`` detail
    # bundles. They are authoritative witnesses only for deep families actually
    # materialized by the normalizer; absence from an integrated bundle is not
    # promoted to EMPTY_VALID evidence.
    return (
        family in DEEP_FIXTURE_FAMILIES
        and pair.entry.family == "fixtures"
        and pair.receipt.endpoint.strip("/").casefold() == "fixtures"
        and family in pair.normalized
    )


def _receipt_fixture_scope_ids(receipt: HarvestReceipt) -> frozenset[int]:
    fixture_ids: set[int] = set()
    fixture = receipt.parameters.get("fixture")
    if isinstance(fixture, int) and not isinstance(fixture, bool) and fixture > 0:
        fixture_ids.add(fixture)
    elif isinstance(fixture, str) and fixture.isdecimal() and int(fixture) > 0:
        fixture_ids.add(int(fixture))
    bundle = receipt.parameters.get("ids")
    if isinstance(bundle, str):
        for item in bundle.split("-"):
            if item.isdecimal() and int(item) > 0:
                fixture_ids.add(int(item))
    return frozenset(fixture_ids)


def _pair_intersects_fixture_sample(
    pair: VerifiedEvidencePair,
    *,
    family: str,
    sample_ids: set[int],
) -> bool:
    if _receipt_fixture_scope_ids(pair.receipt) & sample_ids:
        return True
    return any(
        _row_int(row, "provider_fixture_id") in sample_ids
        for row in pair.normalized.get(family, ())
    )


def _raw_record_fixture_id(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    fixture_value = value.get("fixture")
    fixture = fixture_value if isinstance(fixture_value, Mapping) else {}
    fixture_id = fixture.get("id") if fixture else fixture_value
    if isinstance(fixture_id, bool) or not isinstance(fixture_id, int) or fixture_id < 1:
        return None
    return fixture_id


def _integrated_detail_envelope_evidence(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    authoritative_fixture_ids: set[int],
) -> Mapping[str, object]:
    returned_ids: set[int] = set()
    requested_ids: set[int] = set()
    source_object_ids: set[str] = set()
    family_returned_ids: dict[str, set[int]] = {family: set() for family in DEEP_FIXTURE_FAMILIES}
    family_source_object_ids: dict[str, set[str]] = {
        family: set() for family in DEEP_FIXTURE_FAMILIES
    }
    family_invalid_identity: dict[str, int] = {family: 0 for family in DEEP_FIXTURE_FAMILIES}
    invalid_identity = 0
    for pair in pairs:
        if (
            pair.entry.family != "fixtures"
            or pair.receipt.endpoint.strip("/").casefold() != "fixtures"
            or "ids" not in pair.receipt.parameters
        ):
            continue
        requested = set(_receipt_fixture_scope_ids(pair.receipt))
        if not requested:
            invalid_identity += 1
            continue
        requested_ids.update(requested)
        source_object_ids.add(pair.entry.object_id)
        pair_returned_ids: set[int] = set()
        pair_invalid_identity = 0
        for record in _payload_records(pair.payload):
            fixture_id = _raw_record_fixture_id(record)
            if fixture_id is None or fixture_id not in requested:
                invalid_identity += 1
                pair_invalid_identity += 1
                continue
            pair_returned_ids.add(fixture_id)
            returned_ids.add(fixture_id)
        # A generic integrated fixture envelope proves processing only for the
        # deep families actually materialized by the normalizer.  Merely seeing
        # the fixture in the bundle is not proof that an absent family was
        # queried or validly empty.
        for family in DEEP_FIXTURE_FAMILIES:
            if family not in pair.normalized:
                continue
            family_source_object_ids[family].add(pair.entry.object_id)
            family_invalid_identity[family] += pair_invalid_identity
            for row in pair.normalized[family]:
                fixture_id = _row_int(row, "provider_fixture_id")
                if (
                    fixture_id is None
                    or fixture_id not in requested
                    or fixture_id not in pair_returned_ids
                ):
                    family_invalid_identity[family] += 1
                    continue
                family_returned_ids[family].add(fixture_id)
    unexpected = returned_ids - authoritative_fixture_ids
    return {
        "returned_ids": frozenset(returned_ids),
        "requested_ids": frozenset(requested_ids),
        "source_object_ids": frozenset(source_object_ids),
        "families": {
            family: {
                "returned_ids": frozenset(family_returned_ids[family]),
                "source_object_ids": frozenset(family_source_object_ids[family]),
                "invalid_identity": family_invalid_identity[family],
            }
            for family in sorted(DEEP_FIXTURE_FAMILIES)
        },
        "invalid_identity": invalid_identity,
        "unexpected_fixture_ids": frozenset(unexpected),
    }


def _processing_scope_evidence(
    *,
    family: str,
    pairs: Sequence[VerifiedEvidencePair],
    detail_envelopes: Mapping[str, object],
    authoritative_fixture_ids: set[int],
    target_fixture_ids: set[int],
) -> Mapping[str, object]:
    if family not in DEEP_FIXTURE_FAMILIES:
        return {
            "completed": 0,
            "expected": None,
            "gate": "NOT_APPLICABLE",
            "expected_set_hash": None,
            "observed_set_hash": None,
            "missing_scopes": 0,
            "unexpected_scopes": 0,
            "source_object_ids": [],
            "source_object_set_hash": canonical_sha256([]),
        }
    envelope_families = _mapping(
        detail_envelopes.get("families"),
        label="P0_DETAIL_ENVELOPE_FAMILIES",
    )
    family_envelope = _mapping(
        envelope_families.get(family),
        label="P0_DETAIL_ENVELOPE_FAMILY",
    )
    observed = set(cast(frozenset[int], family_envelope.get("returned_ids")))
    source_object_ids = set(cast(frozenset[str], family_envelope.get("source_object_ids")))
    invalid_identity = _integer(
        family_envelope.get("invalid_identity"),
        label="P0_DETAIL_ENVELOPE_FAMILY_INVALID_IDENTITY",
    )
    raw_family, endpoint = FAMILY_SOURCE_BINDINGS[family]
    for pair in pairs:
        if (
            pair.entry.family != raw_family
            or pair.receipt.endpoint.strip("/").casefold() != endpoint
        ):
            continue
        source_object_ids.add(pair.entry.object_id)
        receipt_scope_ids = set(_receipt_fixture_scope_ids(pair.receipt))
        if not receipt_scope_ids:
            invalid_identity += 1
        pair_ids: set[int] = set()
        for row in pair.normalized.get(family, ()):
            fixture_id = _row_int(row, "provider_fixture_id")
            if fixture_id is None or fixture_id not in receipt_scope_ids:
                invalid_identity += 1
                continue
            pair_ids.add(fixture_id)
        if str(pair.receipt.status.value) == "EMPTY_VALID":
            pair_ids.update(receipt_scope_ids)
        observed.update(pair_ids)
    unexpected = observed - authoritative_fixture_ids
    observed_target = observed & target_fixture_ids
    missing = target_fixture_ids - observed_target
    if invalid_identity or unexpected:
        gate = "FAIL"
    elif not missing:
        gate = "PASS"
    else:
        gate = "PARTIAL"
    return {
        "completed": len(observed_target),
        "expected": len(target_fixture_ids),
        "gate": gate,
        "expected_set_hash": canonical_sha256(sorted(target_fixture_ids)),
        "observed_set_hash": canonical_sha256(sorted(observed_target)),
        "missing_scopes": len(missing),
        "unexpected_scopes": len(unexpected),
        "source_object_ids": sorted(source_object_ids),
        "source_object_set_hash": canonical_sha256(sorted(source_object_ids)),
    }


def _pagination_evidence(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    raw_family: str,
    endpoint: str,
) -> Mapping[str, object]:
    relevant = tuple(
        pair
        for pair in pairs
        if pair.entry.family == raw_family
        and pair.receipt.endpoint.strip("/").casefold() == endpoint
    )
    if not relevant:
        return {
            "status": "UNKNOWN",
            "pages_expected": None,
            "pages_verified": 0,
            "raw_records": 0,
        }
    pages_by_query: dict[str, dict[int, VerifiedEvidencePair]] = defaultdict(dict)
    totals_by_query: dict[str, set[int]] = defaultdict(set)
    raw_records = 0
    for pair in relevant:
        payload = _mapping(pair.payload, label="P0_PAGINATED_PAYLOAD")
        paging = _mapping(payload.get("paging"), label="P0_PAYLOAD_PAGING")
        current = _integer(paging.get("current"), label="P0_PAGING_CURRENT", minimum=1)
        total = _integer(paging.get("total"), label="P0_PAGING_TOTAL", minimum=1)
        records = _payload_records(payload)
        results = _integer(payload.get("results"), label="P0_PAYLOAD_RESULTS", minimum=0)
        query_parameters = dict(pair.receipt.parameters)
        query_parameters.pop("page", None)
        query_id = canonical_sha256(query_parameters)
        query_pages = pages_by_query[query_id]
        if current != pair.receipt.page or results != len(records) or current in query_pages:
            raise ValueError("P0_PAGINATION_RECEIPT_MISMATCH")
        query_pages[current] = pair
        totals_by_query[query_id].add(total)
        raw_records += len(records)
    if any(len(totals) != 1 for totals in totals_by_query.values()):
        raise ValueError("P0_PAGINATION_TOTAL_CONFLICT")
    expected_pages = sum(next(iter(totals)) for totals in totals_by_query.values())
    complete = all(
        set(pages) == set(range(1, next(iter(totals_by_query[query_id])) + 1))
        for query_id, pages in pages_by_query.items()
    )
    return {
        "status": "COMPLETE" if complete else "PARTIAL",
        "query_scopes": len(pages_by_query),
        "query_scope_set_hash": canonical_sha256(sorted(pages_by_query)),
        "pages_expected": expected_pages,
        "pages_verified": sum(len(pages) for pages in pages_by_query.values()),
        "raw_records": raw_records,
    }


def _row_int(row: Mapping[str, object], field: str) -> int | None:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _data_mapping(row: Mapping[str, object]) -> Mapping[str, object]:
    value = row.get("data")
    return value if isinstance(value, Mapping) else {}


def _validate_normalized_row_scope(
    row: Mapping[str, object],
    *,
    competition_id: int,
    season: int,
) -> None:
    row_competition = row.get("provider_competition_id")
    row_season = row.get("season")
    if row_competition is not None and (
        isinstance(row_competition, bool)
        or not isinstance(row_competition, int)
        or row_competition != competition_id
    ):
        raise ValueError("P0_NORMALIZED_ROW_COMPETITION_SCOPE_MISMATCH")
    if row_season is not None and (
        isinstance(row_season, bool) or not isinstance(row_season, int) or row_season != season
    ):
        raise ValueError("P0_NORMALIZED_ROW_SEASON_SCOPE_MISMATCH")


def _semantic_key(
    family: str,
    row: Mapping[str, object],
) -> tuple[object, ...]:
    fixture_id = _row_int(row, "provider_fixture_id")
    team_id = _row_int(row, "provider_team_id")
    player_id = _row_int(row, "provider_player_id")
    competition_id = _row_int(row, "provider_competition_id")
    season = row.get("season")
    data = _data_mapping(row)
    if family == "fixtures":
        return (family, fixture_id) if fixture_id is not None else ()
    if family == "teams":
        return (
            (family, fixture_id, team_id) if fixture_id is not None and team_id is not None else ()
        )
    if family in {"venues", "referees"}:
        canonical_id = row.get("canonical_id")
        return (
            (family, fixture_id, canonical_id)
            if fixture_id is not None and canonical_id is not None
            else ()
        )
    if family == "events":
        assist_value = data.get("assist")
        assist = assist_value if isinstance(assist_value, Mapping) else {}
        time_value = data.get("time")
        event_time = time_value if isinstance(time_value, Mapping) else {}
        event_identity = (
            fixture_id,
            team_id,
            player_id,
            _row_int(assist, "id"),
            event_time.get("elapsed"),
            event_time.get("extra"),
            data.get("type"),
            data.get("detail"),
            data.get("comments"),
        )
        return (
            (family, *event_identity)
            if fixture_id is not None
            and data.get("type") is not None
            and data.get("detail") is not None
            else ()
        )
    if family in {"lineups", "formations"}:
        return (
            (family, fixture_id, team_id) if fixture_id is not None and team_id is not None else ()
        )
    if family == "lineup_players":
        role = data.get("role")
        return (
            (family, fixture_id, team_id, player_id, role)
            if None not in (fixture_id, team_id, player_id, role)
            else ()
        )
    if family == "team_match_statistics":
        metric = data.get("type")
        return (
            (family, fixture_id, team_id, metric)
            if None not in (fixture_id, team_id, metric)
            else ()
        )
    if family == "player_match_statistics":
        return (
            (family, fixture_id, team_id, player_id)
            if None not in (fixture_id, team_id, player_id)
            else ()
        )
    if family == "players":
        return (
            (family, competition_id, season, player_id)
            if None not in (competition_id, season, player_id)
            else ()
        )
    if family == "player_season_statistics":
        player_season_identity = (
            competition_id,
            season,
            player_id,
        )
        return (family, *player_season_identity) if None not in player_season_identity else ()
    if family in {"injuries", "suspensions"}:
        player_value = data.get("player")
        player = player_value if isinstance(player_value, Mapping) else {}
        absence_type = data.get("type") or player.get("type")
        absence_reason = data.get("reason") or player.get("reason")
        absence_identity = (
            fixture_id,
            player_id,
            team_id,
            absence_type,
            absence_reason,
        )
        return (
            (
                family,
                *absence_identity,
                data.get("start"),
                data.get("end"),
            )
            if None not in absence_identity
            else ()
        )
    if family == "standings":
        standing_identity = (
            competition_id,
            season,
            team_id,
        )
        return (family, *standing_identity) if None not in standing_identity else ()
    if family == "rounds":
        round_identity = (competition_id, season, data.get("name"))
        return (family, *round_identity) if None not in round_identity else ()
    canonical_id = row.get("canonical_id")
    return (family, canonical_id) if canonical_id is not None else ()


def _semantic_content(
    family: str,
    row: Mapping[str, object],
) -> object:
    data = dict(_data_mapping(row))
    if family == "rounds":
        return {"name": data.get("name")}
    return data


def _deduplicate_rows(
    family: str,
    rows: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    if family == "player_season_statistics":
        player_buckets: dict[tuple[object, ...], dict[tuple[object, ...], str]] = defaultdict(dict)
        invalid_identity = 0
        exact_duplicates = 0
        contradictions = 0
        for row in rows:
            key = _semantic_key(family, row)
            team_id = _row_int(row, "provider_team_id")
            data = _data_mapping(row)
            league_value = data.get("league")
            league = league_value if isinstance(league_value, Mapping) else {}
            bucket_key = (team_id, league.get("id"), league.get("season"))
            if not key or team_id is None:
                invalid_identity += 1
                continue
            content_hash = canonical_sha256(data)
            prior = player_buckets[key].get(bucket_key)
            if prior is None:
                player_buckets[key][bucket_key] = content_hash
            elif prior == content_hash:
                exact_duplicates += 1
            else:
                contradictions += 1
        return {
            "normalized_rows": len(rows),
            "normalized_unique": len(player_buckets),
            "invalid_identity": invalid_identity,
            "exact_duplicates": exact_duplicates,
            "contradictory_duplicates": contradictions,
            "identity_key_set_hash": canonical_sha256(
                [list(key) for key in sorted(player_buckets, key=canonical_sha256)]
            ),
            "identity_set_hash": canonical_sha256(
                [
                    [
                        list(key),
                        [
                            [list(bucket_key), content_hash]
                            for bucket_key, content_hash in sorted(
                                buckets.items(), key=lambda item: canonical_sha256(item[0])
                            )
                        ],
                    ]
                    for key, buckets in sorted(
                        player_buckets.items(), key=lambda item: canonical_sha256(item[0])
                    )
                ]
            ),
        }
    identities: dict[tuple[object, ...], str] = {}
    exact_duplicates = 0
    contradictions = 0
    for row in rows:
        key = _semantic_key(family, row)
        if not key:
            continue
        content_hash = canonical_sha256(_semantic_content(family, row))
        prior = identities.get(key)
        if prior is None:
            identities[key] = content_hash
        elif prior == content_hash:
            exact_duplicates += 1
        else:
            contradictions += 1
    return {
        "normalized_rows": len(rows),
        "normalized_unique": len(identities),
        "invalid_identity": len(rows) - len(identities) - exact_duplicates - contradictions,
        "exact_duplicates": exact_duplicates,
        "contradictory_duplicates": contradictions,
        "identity_key_set_hash": canonical_sha256(
            [
                list(key)
                for key in sorted(
                    identities,
                    key=canonical_sha256,
                )
            ]
        ),
        "identity_set_hash": canonical_sha256(
            [
                [list(key), content_hash]
                for key, content_hash in sorted(
                    identities.items(), key=lambda item: canonical_sha256(item[0])
                )
            ]
        ),
    }


def _fixture_row_census(
    fixture_rows: Sequence[Mapping[str, object]],
    *,
    pagination: Mapping[str, object],
) -> Mapping[str, object]:
    deduplicated = _deduplicate_rows("fixtures", fixture_rows)
    rows_by_fixture: dict[int, Mapping[str, object]] = {}
    for row in fixture_rows:
        fixture_id = _row_int(row, "provider_fixture_id")
        if fixture_id is not None and fixture_id not in rows_by_fixture:
            rows_by_fixture[fixture_id] = row
    fixture_ids: set[int] = set()
    terminal_fixture_ids: set[int] = set()
    non_cancelled_fixture_ids: set[int] = set()
    team_ids: set[int] = set()
    rounds: set[str] = set()
    terminal = 0
    not_applicable = 0
    blocking_statuses: dict[str, int] = defaultdict(int)
    for fixture_id, row in rows_by_fixture.items():
        fixture_ids.add(fixture_id)
        data = _data_mapping(row)
        teams = _mapping(data.get("teams"), label="P0_CENSUS_TEAMS")
        for side in ("home", "away"):
            team_id = _mapping(teams.get(side), label="P0_CENSUS_TEAM").get("id")
            if isinstance(team_id, int) and not isinstance(team_id, bool):
                team_ids.add(team_id)
        league = _mapping(data.get("league"), label="P0_CENSUS_LEAGUE")
        round_name = league.get("round")
        if isinstance(round_name, str) and round_name:
            rounds.add(round_name)
        fixture = _mapping(data.get("fixture"), label="P0_CENSUS_FIXTURE")
        status = _mapping(fixture.get("status"), label="P0_CENSUS_FIXTURE_STATUS").get("short")
        if status in {"FT", "AET", "PEN"}:
            terminal += 1
            terminal_fixture_ids.add(fixture_id)
            non_cancelled_fixture_ids.add(fixture_id)
        elif status in {"PST", "CANC", "NS", "TBD"}:
            not_applicable += 1
            if status != "CANC":
                non_cancelled_fixture_ids.add(fixture_id)
        else:
            blocking_statuses[str(status or "UNKNOWN")] += 1
    complete = (
        pagination.get("status") == "COMPLETE"
        and deduplicated["invalid_identity"] == 0
        and deduplicated["contradictory_duplicates"] == 0
        and deduplicated["normalized_unique"] == len(fixture_ids)
        and not blocking_statuses
    )
    return {
        "status": "COMPLETE" if complete else "PARTIAL",
        "pagination": pagination,
        "fixtures": len(fixture_ids),
        "team_slots": len(fixture_ids) * 2,
        "terminal_team_slots": len(terminal_fixture_ids) * 2,
        "distinct_teams": len(team_ids),
        "terminal_fixtures": terminal,
        "applicable_venue_fixtures": len(non_cancelled_fixture_ids),
        "not_applicable_fixtures": not_applicable,
        "blocking_fixture_statuses": dict(sorted(blocking_statuses.items())),
        "distinct_rounds": len(rounds),
        "fixture_set_hash": canonical_sha256(sorted(fixture_ids)),
        "terminal_fixture_set_hash": canonical_sha256(sorted(terminal_fixture_ids)),
        "applicable_venue_fixture_set_hash": canonical_sha256(sorted(non_cancelled_fixture_ids)),
    }


def _fixture_applicability_sets(
    fixture_rows: Sequence[Mapping[str, object]],
) -> Mapping[str, frozenset[int]]:
    rows_by_fixture: dict[int, Mapping[str, object]] = {}
    for row in fixture_rows:
        fixture_id = _row_int(row, "provider_fixture_id")
        if fixture_id is not None and fixture_id not in rows_by_fixture:
            rows_by_fixture[fixture_id] = row
    all_fixtures = frozenset(rows_by_fixture)
    terminal: set[int] = set()
    venue_applicable: set[int] = set()
    for fixture_id, row in rows_by_fixture.items():
        fixture = _mapping(
            _data_mapping(row).get("fixture"),
            label="P0_APPLICABILITY_FIXTURE",
        )
        status = _mapping(
            fixture.get("status"),
            label="P0_APPLICABILITY_STATUS",
        ).get("short")
        if status in {"FT", "AET", "PEN"}:
            terminal.add(fixture_id)
        if status in {"FT", "AET", "PEN", "PST", "NS", "TBD"}:
            venue_applicable.add(fixture_id)
    return {
        "all": all_fixtures,
        "terminal": frozenset(terminal),
        "venue": frozenset(venue_applicable),
    }


def _fixture_census(
    pairs: Sequence[VerifiedEvidencePair],
) -> Mapping[str, object]:
    pagination = _pagination_evidence(
        pairs,
        raw_family="fixtures",
        endpoint="fixtures",
    )
    fixture_rows = [row for pair in pairs for row in pair.normalized.get("fixtures", ())]
    return _fixture_row_census(fixture_rows, pagination=pagination)


def _raw_fixture_identity_evidence(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    sample_ids: set[int] | None,
) -> Mapping[str, object]:
    pagination = _pagination_evidence(
        pairs,
        raw_family="fixtures",
        endpoint="fixtures",
    )
    fixture_contents: dict[tuple[object, ...], str] = {}
    team_contents: dict[tuple[object, ...], str] = {}
    invalid = 0
    contradictions = 0
    for pair in pairs:
        if (
            pair.entry.family != "fixtures"
            or pair.receipt.endpoint.strip("/").casefold() != "fixtures"
        ):
            continue
        for record_value in _payload_records(pair.payload):
            if not isinstance(record_value, Mapping):
                invalid += 1
                continue
            fixture_value = record_value.get("fixture")
            fixture = fixture_value if isinstance(fixture_value, Mapping) else {}
            fixture_id = fixture.get("id")
            if isinstance(fixture_id, bool) or not isinstance(fixture_id, int) or fixture_id < 1:
                invalid += 1
                continue
            if sample_ids is not None and fixture_id not in sample_ids:
                continue
            fixture_key = ("fixtures", fixture_id)
            fixture_hash = canonical_sha256(record_value)
            prior_fixture = fixture_contents.get(fixture_key)
            if prior_fixture is None:
                fixture_contents[fixture_key] = fixture_hash
            elif prior_fixture != fixture_hash:
                contradictions += 1
            teams_value = record_value.get("teams")
            teams = teams_value if isinstance(teams_value, Mapping) else {}
            for side in ("home", "away"):
                team_value = teams.get(side)
                team = team_value if isinstance(team_value, Mapping) else {}
                team_id = team.get("id")
                if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id < 1:
                    invalid += 1
                    continue
                team_key = ("teams", fixture_id, team_id)
                team_hash = canonical_sha256(team_value)
                prior_team = team_contents.get(team_key)
                if prior_team is None:
                    team_contents[team_key] = team_hash
                elif prior_team != team_hash:
                    contradictions += 1
    if sample_ids is not None and {cast(int, key[1]) for key in fixture_contents} != sample_ids:
        invalid += len(
            sample_ids.symmetric_difference({cast(int, key[1]) for key in fixture_contents})
        )
    complete = pagination.get("status") == "COMPLETE" and invalid == 0 and contradictions == 0

    def evidence(values: Mapping[tuple[object, ...], str]) -> Mapping[str, object]:
        return {
            "raw_eligible_unique": len(values),
            "identity_key_set_hash": canonical_sha256(
                [list(key) for key in sorted(values, key=canonical_sha256)]
            ),
        }

    return {
        "status": "COMPLETE" if complete else "PARTIAL",
        "invalid_raw_identity": invalid,
        "contradictory_raw_identity": contradictions,
        "families": {
            "fixtures": evidence(fixture_contents),
            "teams": evidence(team_contents),
        },
    }


_ABSENCE_SEMANTIC_FIELDS = ("type", "reason", "description")
_ABSENCE_UNKNOWN_VALUES = frozenset(ABSENCE_UNKNOWN_EXACT_VALUES)
_ABSENCE_SUPPLEMENT_CATEGORIES = frozenset(
    {"UNCLASSIFIABLE"}
)


def _absence_rule_patterns(
    authority: CoverageAuthority,
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    try:
        return (
            re.compile(authority.absence_suspension_regex, flags=re.IGNORECASE),
            re.compile(authority.absence_injury_regex, flags=re.IGNORECASE),
        )
    except re.error:
        raise ValueError("P0_ABSENCE_REGEX_INVALID") from None


def _normalize_absence_value(value: object) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str):
        return f"sha256:{canonical_sha256(value)}", "INVALID_SEMANTIC_TYPE"
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        return f"sha256:{canonical_sha256(normalized)}", "CONTROL_CHARACTER"
    normalized = " ".join(normalized.strip().split())
    if not normalized:
        return None, None
    if len(normalized) > 256:
        return f"sha256:{canonical_sha256(normalized)}", "OVERSIZE_SEMANTIC_VALUE"
    return normalized, None


def _absence_semantic_evidence(record: Mapping[str, object]) -> Mapping[str, object]:
    player_value = record.get("player")
    player = player_value if isinstance(player_value, Mapping) else {}
    normalized_fields: dict[str, list[str]] = {}
    resolved_fields: dict[str, str | None] = {}
    issues: set[str] = set()
    flat_nested_conflict = False
    for field in _ABSENCE_SEMANTIC_FIELDS:
        flat, flat_issue = _normalize_absence_value(record.get(field))
        nested, nested_issue = _normalize_absence_value(player.get(field))
        issues.update(issue for issue in (flat_issue, nested_issue) if issue is not None)
        values = sorted({value for value in (flat, nested) if value is not None})
        normalized_fields[f"normalized_{field}_values"] = values
        if flat is not None and nested is not None and flat != nested:
            flat_nested_conflict = True
        resolved_fields[field] = values[0] if len(values) == 1 else None

    if sum(len(value) for values in normalized_fields.values() for value in values) > 768:
        issues.add("OVERSIZE_SEMANTIC_TOTAL")
        normalized_fields = {
            field: sorted({f"sha256:{canonical_sha256(value)}" for value in values})
            for field, values in normalized_fields.items()
        }
        resolved_fields = {field: None for field in _ABSENCE_SEMANTIC_FIELDS}

    descriptors = tuple(
        value
        for field in _ABSENCE_SEMANTIC_FIELDS
        if (value := resolved_fields[field]) is not None
    )
    profile_fields = dict(normalized_fields)
    description_values = profile_fields["normalized_description_values"]
    description_redacted = bool(description_values)
    if description_redacted:
        profile_fields["normalized_description_values"] = sorted(
            {f"sha256:{canonical_sha256(value)}" for value in description_values}
        )
    signature_unsigned: dict[str, object] = {
        **profile_fields,
        "normalization_version": ABSENCE_NORMALIZATION_VERSION,
    }
    signature_sha = canonical_sha256(signature_unsigned)
    return {
        **signature_unsigned,
        "signature_sha256": signature_sha,
        "resolved_fields": resolved_fields,
        "descriptors": descriptors,
        "issues": tuple(sorted(issues)),
        "flat_nested_conflict": flat_nested_conflict,
        "description_redacted": description_redacted,
    }


def _base_absence_category(
    semantic: Mapping[str, object],
    *,
    suspension_pattern: re.Pattern[str],
    injury_pattern: re.Pattern[str],
) -> tuple[str, str]:
    issues = tuple(
        _text(item, label="P0_ABSENCE_SEMANTIC_ISSUE")
        for item in _sequence(semantic.get("issues"), label="P0_ABSENCE_SEMANTIC_ISSUES")
    )
    if issues:
        return "UNCLASSIFIABLE", issues[0]
    if semantic.get("flat_nested_conflict") is True:
        return "UNCLASSIFIABLE", "FLAT_NESTED_CONFLICT"
    descriptors = tuple(
        _text(item, label="P0_ABSENCE_DESCRIPTOR")
        for item in _sequence(
            semantic.get("descriptors"),
            label="P0_ABSENCE_DESCRIPTORS",
        )
    )
    description = " ".join(descriptors)
    suspension_signal = bool(suspension_pattern.search(description))
    injury_signal = bool(injury_pattern.search(description))
    descriptor_set = set(descriptors)
    personal_signal = bool(
        descriptor_set.intersection(ABSENCE_NONMEDICAL_KNOWN_VALUES)
    )
    if descriptor_set.intersection(_ABSENCE_UNKNOWN_VALUES):
        return "UNCLASSIFIABLE", "UNKNOWN_MARKER"
    if personal_signal and (injury_signal or suspension_signal):
        return "UNCLASSIFIABLE", "MULTIPLE_SEMANTIC_SIGNALS"
    signals = [
        category
        for category, present in (
            ("SUSPENSION", suspension_signal),
            ("INJURY", injury_signal),
        )
        if present
    ]
    if len(signals) == 1:
        return signals[0], "BASE_CLOSED_RULE"
    if len(signals) > 1:
        return "UNCLASSIFIABLE", "MULTIPLE_SEMANTIC_SIGNALS"
    if not descriptors:
        return "UNCLASSIFIABLE", "NO_SEMANTIC_SIGNAL"
    if "missing fixture" in descriptor_set:
        return "UNCLASSIFIABLE", "PROVIDER_PLACEHOLDER_WITHOUT_CLOSED_SIGNAL"
    if personal_signal:
        return "UNCLASSIFIABLE", "NONMEDICAL_ABSENCE_OUTSIDE_AUTHORIZED_PARTITION"
    if semantic.get("description_redacted") is True:
        return "UNCLASSIFIABLE", "FREE_TEXT_DESCRIPTION_REDACTED"
    return "UNCLASSIFIABLE", "UNRECOGNIZED_SEMANTICS"


def _classify_absence_source(
    pairs: Sequence[VerifiedEvidencePair],
    *,
    suspension_pattern: re.Pattern[str],
    injury_pattern: re.Pattern[str],
) -> Mapping[str, object]:
    categories: dict[str, set[str]] = {
        "SUSPENSION": set(),
        "INJURY": set(),
        "UNCLASSIFIABLE": set(),
    }
    identity_contents: dict[str, dict[tuple[object, ...], str]] = {
        category: {} for category in categories
    }
    residual_groups: dict[str, dict[str, object]] = {}
    all_identity_contents: dict[tuple[object, ...], str] = {}
    invalid_identity = 0
    contradictions = 0
    for pair in pairs:
        if (
            pair.entry.family != "injuries"
            or pair.receipt.endpoint.strip("/").casefold() != "injuries"
        ):
            continue
        for record_value in _payload_records(pair.payload):
            if not isinstance(record_value, Mapping):
                invalid_identity += 1
                continue
            record_hash = canonical_sha256(record_value)
            semantic = _absence_semantic_evidence(record_value)
            category, reason_code = _base_absence_category(
                semantic,
                suspension_pattern=suspension_pattern,
                injury_pattern=injury_pattern,
            )
            profile_reason_code = reason_code
            if category == "UNCLASSIFIABLE":
                if any(
                    str(value).startswith("sha256:")
                    for field in ("type", "reason")
                    for value in cast(
                        Sequence[object],
                        semantic[f"normalized_{field}_values"],
                    )
                ):
                    profile_reason_code = "REDACTED_TYPE_OR_REASON_FAIL_CLOSED"
                elif semantic.get("description_redacted") is True:
                    profile_reason_code = "DESCRIPTION_BEARING_RESIDUAL_FAIL_CLOSED"
            semantic_signature_sha = _sha(
                semantic.get("signature_sha256"),
                label="P0_ABSENCE_SIGNATURE",
            )
            signature_sha = canonical_sha256(
                {
                    "semantic_signature_sha256": semantic_signature_sha,
                    "reason_code": profile_reason_code,
                }
            )
            categories[category].add(record_hash)
            if category == "UNCLASSIFIABLE":
                group = residual_groups.setdefault(
                    signature_sha,
                    {
                        "signature_sha256": signature_sha,
                        "normalized_type_values": semantic["normalized_type_values"],
                        "normalized_reason_values": semantic["normalized_reason_values"],
                        "normalized_description_values": semantic[
                            "normalized_description_values"
                        ],
                        "normalization_version": ABSENCE_NORMALIZATION_VERSION,
                        "reason_code": profile_reason_code,
                        "record_hashes": set(),
                    },
                )
                if group.get("reason_code") != profile_reason_code:
                    raise ValueError("P0_ABSENCE_SIGNATURE_REASON_CONFLICT")
                cast(set[str], group["record_hashes"]).add(record_hash)
            fixture_value = record_value.get("fixture")
            fixture = fixture_value if isinstance(fixture_value, Mapping) else {}
            fixture_id = fixture.get("id") if fixture else fixture_value
            player_value = record_value.get("player")
            player = player_value if isinstance(player_value, Mapping) else {}
            team_value = record_value.get("team")
            team = team_value if isinstance(team_value, Mapping) else {}
            resolved = _mapping(
                semantic.get("resolved_fields"),
                label="P0_ABSENCE_RESOLVED_FIELDS",
            )
            natural_key = (
                fixture_id,
                player.get("id"),
                team.get("id"),
                resolved.get("type"),
                resolved.get("reason"),
                record_value.get("start"),
                record_value.get("end"),
            )
            if any(value is None or isinstance(value, bool) for value in natural_key[:5]):
                invalid_identity += 1
                continue
            prior = all_identity_contents.get(natural_key)
            if prior is None:
                all_identity_contents[natural_key] = record_hash
            elif prior != record_hash:
                contradictions += 1
            identity_contents[category].setdefault(natural_key, record_hash)
    raw_hashes = set().union(*categories.values())
    semantic_signatures = []
    for signature_sha, group in sorted(residual_groups.items()):
        record_hashes = cast(set[str], group.pop("record_hashes"))
        semantic_signatures.append({**group, "count": len(record_hashes)})
    if sum(cast(int, item["count"]) for item in semantic_signatures) != len(
        categories["UNCLASSIFIABLE"]
    ):
        raise ValueError("P0_ABSENCE_RESIDUAL_PROFILE_COUNT_MISMATCH")
    return {
        "raw_hashes": frozenset(raw_hashes),
        "categories": {category: frozenset(values) for category, values in categories.items()},
        "invalid_identity": invalid_identity,
        "contradictory_identity": contradictions,
        "identity_key_set_hashes": {
            category: canonical_sha256([list(key) for key in sorted(values, key=canonical_sha256)])
            for category, values in identity_contents.items()
        },
        "identity_counts": {
            category: len(values) for category, values in identity_contents.items()
        },
        "semantic_signatures": semantic_signatures,
    }


def _validate_absence_semantic_signature(
    value: object,
    *,
    label: str,
    suspension_pattern: re.Pattern[str],
    injury_pattern: re.Pattern[str],
) -> Mapping[str, object]:
    signature = _mapping(value, label=label)
    if set(signature) != {
        "signature_sha256",
        "normalized_type_values",
        "normalized_reason_values",
        "normalized_description_values",
        "normalization_version",
        "reason_code",
        "count",
    }:
        raise ValueError(f"{label}_FIELDS_INVALID")
    normalized_fields: dict[str, list[str]] = {}
    normalized_total = 0
    for field in _ABSENCE_SEMANTIC_FIELDS:
        values = [
            _text(item, label=f"{label}_{field.upper()}")
            for item in _sequence(
                signature.get(f"normalized_{field}_values"),
                label=f"{label}_{field.upper()}_VALUES",
            )
        ]
        if (
            values != sorted(set(values))
            or any(len(item) > 256 for item in values)
            or len(values) > 2
            or (
                field != "description"
                and any(
                    (
                        re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None
                        if item.startswith("sha256:")
                        else _normalize_absence_value(item) != (item, None)
                    )
                    for item in values
                )
            )
            or (
                field == "description"
                and any(re.fullmatch(r"sha256:[0-9a-f]{64}", item) is None for item in values)
            )
        ):
            raise ValueError(f"{label}_{field.upper()}_VALUES_INVALID")
        normalized_fields[f"normalized_{field}_values"] = values
        normalized_total += sum(len(item) for item in values)
    if normalized_total > 768:
        raise ValueError(f"{label}_TOTAL_LENGTH_INVALID")
    if signature.get("normalization_version") != ABSENCE_NORMALIZATION_VERSION:
        raise ValueError(f"{label}_NORMALIZATION_INVALID")
    semantic_sha = canonical_sha256(
        {
            **normalized_fields,
            "normalization_version": ABSENCE_NORMALIZATION_VERSION,
        }
    )
    reason_code = _text(signature.get("reason_code"), label=f"{label}_REASON")
    type_or_reason_redacted = any(
        value.startswith("sha256:")
        for field in ("type", "reason")
        for value in normalized_fields[f"normalized_{field}_values"]
    )
    if type_or_reason_redacted:
        if reason_code != "REDACTED_TYPE_OR_REASON_FAIL_CLOSED":
            raise ValueError(f"{label}_REDACTED_REASON_MISMATCH")
    elif normalized_fields["normalized_description_values"]:
        if reason_code != "DESCRIPTION_BEARING_RESIDUAL_FAIL_CLOSED":
            raise ValueError(f"{label}_DESCRIPTION_REASON_MISMATCH")
    else:
        resolved_fields = {
            field: (
                normalized_fields[f"normalized_{field}_values"][0]
                if len(normalized_fields[f"normalized_{field}_values"]) == 1
                else None
            )
            for field in _ABSENCE_SEMANTIC_FIELDS
        }
        derived_category, derived_reason = _base_absence_category(
            {
                "issues": (),
                "flat_nested_conflict": any(
                    len(normalized_fields[f"normalized_{field}_values"]) > 1
                    for field in _ABSENCE_SEMANTIC_FIELDS
                ),
                "descriptors": tuple(
                    value
                    for field, value in resolved_fields.items()
                    if field != "description" and value is not None
                ),
                "description_redacted": False,
            },
            suspension_pattern=suspension_pattern,
            injury_pattern=injury_pattern,
        )
        if derived_category != "UNCLASSIFIABLE" or reason_code != derived_reason:
            raise ValueError(f"{label}_DERIVED_REASON_MISMATCH")
    expected_sha = canonical_sha256(
        {
            "semantic_signature_sha256": semantic_sha,
            "reason_code": reason_code,
        }
    )
    if _sha(signature.get("signature_sha256"), label=f"{label}_SHA") != expected_sha:
        raise ValueError(f"{label}_HASH_MISMATCH")
    _integer(signature.get("count"), label=f"{label}_COUNT", minimum=1)
    return signature


def _build_absence_residual_profile(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    selection_sha256: str,
    partition_id: str,
    inventory_sha256: str,
    attempt_slot: int,
    absence_source_object_ids: Sequence[str],
    semantic_signatures: Sequence[Mapping[str, object]],
    classification_supplement_sha256: str | None,
) -> Mapping[str, object]:
    ordered = sorted(
        (dict(item) for item in semantic_signatures),
        key=lambda item: str(item.get("signature_sha256")),
    )
    unsigned: dict[str, object] = {
        "schema_version": ABSENCE_PROFILE_SCHEMA_VERSION,
        "stage": authority.stage,
        "partition_id": partition_id,
        "selection_sha256": selection_sha256,
        "inventory_sha256": inventory_sha256,
        "architecture_fingerprint": evidence_architecture_fingerprint(authority),
        "architecture_ordinal": selection.get("architecture_ordinal"),
        "attempt_slot": attempt_slot,
        "classification_rule_version": ABSENCE_CLASSIFICATION_RULE_VERSION,
        "classification_framework_sha256": ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256,
        "classification_supplement_sha256": classification_supplement_sha256,
        "normalization_version": ABSENCE_NORMALIZATION_VERSION,
        "source_absence_object_set_hash": canonical_sha256(
            sorted(absence_source_object_ids)
        ),
        "unclassifiable_record_count": sum(
            _integer(item.get("count"), label="P0_ABSENCE_PROFILE_BUILD_COUNT", minimum=1)
            for item in ordered
        ),
        "distinct_semantic_signature_count": len(ordered),
        "semantic_signatures": ordered,
        "effects": dict(ZERO_EFFECTS),
    }
    profile = _signed(unsigned, field="profile_sha256")
    _validate_absence_residual_profile(
        profile,
        authority=authority,
        selection=selection,
        expected_selection_sha256=selection_sha256,
        expected_inventory_sha256=inventory_sha256,
        expected_attempt_slot=attempt_slot,
    )
    return profile


def _validate_absence_residual_profile(
    value: object,
    *,
    authority: CoverageAuthority,
    selection: Mapping[str, object],
    expected_selection_sha256: str,
    expected_inventory_sha256: str,
    expected_attempt_slot: int,
) -> Mapping[str, object]:
    suspension_pattern, injury_pattern = _absence_rule_patterns(authority)
    profile = _mapping(value, label="P0_ABSENCE_RESIDUAL_PROFILE")
    _verify_signed(
        profile,
        field="profile_sha256",
        label="P0_ABSENCE_RESIDUAL_PROFILE",
    )
    if set(profile) != {
        "schema_version",
        "stage",
        "partition_id",
        "selection_sha256",
        "inventory_sha256",
        "architecture_fingerprint",
        "architecture_ordinal",
        "attempt_slot",
        "classification_rule_version",
        "classification_framework_sha256",
        "classification_supplement_sha256",
        "normalization_version",
        "source_absence_object_set_hash",
        "unclassifiable_record_count",
        "distinct_semantic_signature_count",
        "semantic_signatures",
        "effects",
        "profile_sha256",
    }:
        raise ValueError("P0_ABSENCE_RESIDUAL_PROFILE_FIELDS_INVALID")
    signatures = tuple(
        _validate_absence_semantic_signature(
            item,
            label="P0_ABSENCE_RESIDUAL_SIGNATURE",
            suspension_pattern=suspension_pattern,
            injury_pattern=injury_pattern,
        )
        for item in _sequence(
            profile.get("semantic_signatures"),
            label="P0_ABSENCE_RESIDUAL_SIGNATURES",
        )
    )
    signature_hashes = [str(item["signature_sha256"]) for item in signatures]
    supplement_value = profile.get("classification_supplement_sha256")
    if supplement_value is not None:
        _sha(supplement_value, label="P0_ABSENCE_PROFILE_SUPPLEMENT")
    if (
        profile.get("schema_version") != ABSENCE_PROFILE_SCHEMA_VERSION
        or profile.get("stage") != authority.stage
        or SAFE_ID.fullmatch(str(profile.get("partition_id"))) is None
        or profile.get("selection_sha256") != expected_selection_sha256
        or profile.get("inventory_sha256") != expected_inventory_sha256
        or profile.get("architecture_fingerprint")
        != evidence_architecture_fingerprint(authority)
        or profile.get("architecture_ordinal") != selection.get("architecture_ordinal")
        or profile.get("attempt_slot") != expected_attempt_slot
        or profile.get("classification_rule_version")
        != ABSENCE_CLASSIFICATION_RULE_VERSION
        or profile.get("classification_framework_sha256")
        != ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        or profile.get("normalization_version") != ABSENCE_NORMALIZATION_VERSION
        or HEX64.fullmatch(str(profile.get("source_absence_object_set_hash"))) is None
        or signature_hashes != sorted(set(signature_hashes))
        or profile.get("distinct_semantic_signature_count") != len(signatures)
        or profile.get("unclassifiable_record_count")
        != sum(cast(int, item["count"]) for item in signatures)
        or _mapping(profile.get("effects"), label="P0_ABSENCE_PROFILE_EFFECTS")
        != ZERO_EFFECTS
        or _contains_r2_key(profile)
    ):
        raise ValueError("P0_ABSENCE_RESIDUAL_PROFILE_INVALID")
    return profile


def _absence_profile_catalog(
    profiles: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    catalog: dict[str, Mapping[str, object]] = {}
    for profile in profiles:
        for item in _sequence(
            profile.get("semantic_signatures"),
            label="P0_ABSENCE_PROFILE_CATALOG_SIGNATURES",
        ):
            signature = _mapping(item, label="P0_ABSENCE_PROFILE_CATALOG_SIGNATURE")
            signature_sha = _sha(
                signature.get("signature_sha256"),
                label="P0_ABSENCE_PROFILE_CATALOG_SHA",
            )
            semantic = {
                key: value
                for key, value in signature.items()
                if key != "count"
            }
            prior = catalog.setdefault(signature_sha, semantic)
            if prior != semantic:
                raise ValueError("P0_ABSENCE_PROFILE_SIGNATURE_CONFLICT")
    return catalog


def _load_absence_taxonomy_supplement(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    prior: Mapping[str, object],
) -> tuple[str, Mapping[str, str]]:
    selection_sha = _verify_signed(
        selection,
        field="selection_sha256",
        label="P0_ABSENCE_SUPPLEMENT_SELECTION",
    )
    profiles = tuple(
        _validate_absence_residual_profile(
            item,
            authority=authority,
            selection=selection,
            expected_selection_sha256=selection_sha,
            expected_inventory_sha256=_sha(
                selection.get("inventory_sha256"),
                label="P0_ABSENCE_SUPPLEMENT_INVENTORY",
            ),
            expected_attempt_slot=1,
        )
        for item in _sequence(
            prior.get("absence_residual_profiles"),
            label="P0_ABSENCE_SUPPLEMENT_SOURCE_PROFILES",
        )
    )
    profile_hashes = sorted(
        _sha(item.get("profile_sha256"), label="P0_ABSENCE_SUPPLEMENT_PROFILE_SHA")
        for item in profiles
    )
    profile_set_sha = canonical_sha256(profile_hashes)
    expected_partition_ids = sorted(
        _text(
            _mapping(item, label="P0_ABSENCE_SUPPLEMENT_PARTITION").get(
                "partition_id"
            ),
            label="P0_ABSENCE_SUPPLEMENT_PARTITION_ID",
        )
        for item in _sequence(
            selection.get("partitions"),
            label="P0_ABSENCE_SUPPLEMENT_PARTITIONS",
        )
    )
    observed_partition_ids = sorted(
        _text(item.get("partition_id"), label="P0_ABSENCE_SUPPLEMENT_PROFILE_PARTITION")
        for item in profiles
    )
    if (
        not profiles
        or observed_partition_ids != expected_partition_ids
        or any(item.get("classification_supplement_sha256") is not None for item in profiles)
        or prior.get("attempt_slot") != 1
        or prior.get("measurement_integrity_gate") != "PASS"
        or prior.get("read_accounting_gate") != "PASS"
        or prior.get("checkpoint_gate") != "PASS"
        or prior.get("scientific_gate") != "FAIL"
        or prior.get("absence_residual_profile_set_sha256") != profile_set_sha
    ):
        raise ValueError("P0_ABSENCE_SUPPLEMENT_SOURCE_ATTEMPT_INVALID")
    catalog = _absence_profile_catalog(profiles)
    expected_signatures = set(catalog)
    if not expected_signatures:
        raise ValueError("P0_ABSENCE_SUPPLEMENT_SOURCE_PROFILE_EMPTY")
    path = (
        authority.root
        / "configs"
        / "data"
        / f"p0-absence-taxonomy-supplement-{authority.stage}-v1.json"
    )
    supplement = _load_json(path, label="P0_ABSENCE_TAXONOMY_SUPPLEMENT")
    supplement_sha = _verify_signed(
        supplement,
        field="supplement_sha256",
        label="P0_ABSENCE_TAXONOMY_SUPPLEMENT",
    )
    if set(supplement) != {
        "schema_version",
        "mission_id",
        "mission_sha256",
        "stage",
        "architecture_fingerprint",
        "architecture_ordinal",
        "classification_framework_sha256",
        "selection_sha256",
        "inventory_sha256",
        "source_attempt_slot",
        "source_stage_receipt_sha256",
        "source_profile_set_sha256",
        "classifications",
        "reviewer_adjudications",
        "effects",
        "supplement_sha256",
    }:
        raise ValueError("P0_ABSENCE_TAXONOMY_SUPPLEMENT_FIELDS_INVALID")
    classifications: dict[str, str] = {}
    classification_values = tuple(
        _mapping(item, label="P0_ABSENCE_SUPPLEMENT_CLASSIFICATION")
        for item in _sequence(
            supplement.get("classifications"),
            label="P0_ABSENCE_SUPPLEMENT_CLASSIFICATIONS",
        )
    )
    for item in classification_values:
        if set(item) != {"signature_sha256", "category"}:
            raise ValueError("P0_ABSENCE_SUPPLEMENT_CLASSIFICATION_FIELDS_INVALID")
        signature_sha = _sha(
            item.get("signature_sha256"),
            label="P0_ABSENCE_SUPPLEMENT_CLASSIFICATION_SHA",
        )
        category = _text(
            item.get("category"),
            label="P0_ABSENCE_SUPPLEMENT_CLASSIFICATION_CATEGORY",
        )
        if category not in _ABSENCE_SUPPLEMENT_CATEGORIES or signature_sha in classifications:
            raise ValueError("P0_ABSENCE_SUPPLEMENT_CLASSIFICATION_INVALID")
        classifications[signature_sha] = category
    if set(classifications) != expected_signatures or list(classifications) != sorted(
        classifications
    ):
        raise ValueError("P0_ABSENCE_SUPPLEMENT_SIGNATURE_SET_MISMATCH")

    reviewer_values = tuple(
        _mapping(item, label="P0_ABSENCE_SUPPLEMENT_REVIEWER")
        for item in _sequence(
            supplement.get("reviewer_adjudications"),
            label="P0_ABSENCE_SUPPLEMENT_REVIEWERS",
        )
    )
    if len(reviewer_values) != 2:
        raise ValueError("P0_ABSENCE_SUPPLEMENT_TWO_REVIEWERS_REQUIRED")
    reviewer_ids: set[str] = set()
    reviewer_decisions: list[dict[str, str]] = []
    for reviewer in reviewer_values:
        if set(reviewer) != {
            "reviewer_id",
            "mission_id",
            "stage",
            "architecture_fingerprint",
            "classification_framework_sha256",
            "selection_sha256",
            "source_stage_receipt_sha256",
            "source_profile_set_sha256",
            "decisions",
            "adjudication_sha256",
        }:
            raise ValueError("P0_ABSENCE_SUPPLEMENT_REVIEWER_FIELDS_INVALID")
        _verify_signed(
            reviewer,
            field="adjudication_sha256",
            label="P0_ABSENCE_SUPPLEMENT_REVIEWER",
        )
        reviewer_id = _text(
            reviewer.get("reviewer_id"),
            label="P0_ABSENCE_SUPPLEMENT_REVIEWER_ID",
        )
        if (
            reviewer_id not in ABSENCE_SUPPLEMENT_REVIEWER_IDS
            or reviewer_id in reviewer_ids
            or reviewer.get("mission_id") != authority.mission.get("mission_id")
            or reviewer.get("stage") != authority.stage
            or reviewer.get("architecture_fingerprint")
            != evidence_architecture_fingerprint(authority)
            or reviewer.get("classification_framework_sha256")
            != ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
            or reviewer.get("selection_sha256") != selection_sha
            or reviewer.get("source_stage_receipt_sha256")
            != prior.get("stage_receipt_sha256")
            or reviewer.get("source_profile_set_sha256") != profile_set_sha
        ):
            raise ValueError("P0_ABSENCE_SUPPLEMENT_REVIEWER_ID_INVALID")
        reviewer_ids.add(reviewer_id)
        decisions: dict[str, str] = {}
        for decision_value in _sequence(
            reviewer.get("decisions"),
            label="P0_ABSENCE_SUPPLEMENT_REVIEWER_DECISIONS",
        ):
            decision = _mapping(
                decision_value,
                label="P0_ABSENCE_SUPPLEMENT_REVIEWER_DECISION",
            )
            if set(decision) != {"signature_sha256", "category"}:
                raise ValueError("P0_ABSENCE_SUPPLEMENT_DECISION_FIELDS_INVALID")
            signature_sha = _sha(
                decision.get("signature_sha256"),
                label="P0_ABSENCE_SUPPLEMENT_DECISION_SHA",
            )
            category = _text(
                decision.get("category"),
                label="P0_ABSENCE_SUPPLEMENT_DECISION_CATEGORY",
            )
            if category not in _ABSENCE_SUPPLEMENT_CATEGORIES or signature_sha in decisions:
                raise ValueError("P0_ABSENCE_SUPPLEMENT_DECISION_INVALID")
            decisions[signature_sha] = category
        if set(decisions) != expected_signatures or list(decisions) != sorted(decisions):
            raise ValueError("P0_ABSENCE_SUPPLEMENT_REVIEWER_SIGNATURE_SET_MISMATCH")
        reviewer_decisions.append(decisions)
    if reviewer_ids != set(ABSENCE_SUPPLEMENT_REVIEWER_IDS) or [
        reviewer.get("reviewer_id") for reviewer in reviewer_values
    ] != list(ABSENCE_SUPPLEMENT_REVIEWER_IDS):
        raise ValueError("P0_ABSENCE_SUPPLEMENT_REVIEWER_ROLES_INVALID")
    for signature_sha, category in classifications.items():
        consensus_values = {reviewer[signature_sha] for reviewer in reviewer_decisions}
        expected_category = (
            next(iter(consensus_values))
            if len(consensus_values) == 1
            else "UNCLASSIFIABLE"
        )
        if category != expected_category:
            raise ValueError("P0_ABSENCE_SUPPLEMENT_CONSENSUS_INVALID")
    if (
        supplement.get("schema_version") != ABSENCE_SUPPLEMENT_SCHEMA_VERSION
        or supplement.get("mission_id") != authority.mission.get("mission_id")
        or supplement.get("mission_sha256") != authority.mission_sha256
        or supplement.get("stage") != authority.stage
        or supplement.get("architecture_fingerprint")
        != evidence_architecture_fingerprint(authority)
        or supplement.get("architecture_ordinal") != selection.get("architecture_ordinal")
        or supplement.get("classification_framework_sha256")
        != ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
        or supplement.get("selection_sha256") != selection_sha
        or supplement.get("inventory_sha256") != selection.get("inventory_sha256")
        or supplement.get("source_attempt_slot") != 1
        or supplement.get("source_stage_receipt_sha256")
        != prior.get("stage_receipt_sha256")
        or supplement.get("source_profile_set_sha256") != profile_set_sha
        or _mapping(supplement.get("effects"), label="P0_ABSENCE_SUPPLEMENT_EFFECTS")
        != ZERO_EFFECTS
        or _contains_r2_key(supplement)
    ):
        raise ValueError("P0_ABSENCE_TAXONOMY_SUPPLEMENT_INVALID")
    return supplement_sha, classifications


def _scope_completion_counts(
    *,
    family: str,
    pairs: Sequence[VerifiedEvidencePair],
    census: Mapping[str, object],
) -> Mapping[str, object]:
    paginated_sources = {
        "fixtures": ("fixtures", "fixtures"),
        "teams": ("fixtures", "fixtures"),
        "venues": ("fixtures", "fixtures"),
        "referees": ("fixtures", "fixtures"),
        "rounds": ("rounds", "fixtures/rounds"),
        "standings": ("standings", "standings"),
        "players": ("players", "players"),
        "player_season_statistics": ("players", "players"),
        "injuries": ("injuries", "injuries"),
        "suspensions": ("injuries", "injuries"),
    }
    paginated = paginated_sources.get(family)
    if paginated is not None:
        evidence = _pagination_evidence(
            pairs,
            raw_family=paginated[0],
            endpoint=paginated[1],
        )
        complete = evidence.get("status") == "COMPLETE"
        return {
            "completed": 1 if complete else 0,
            "expected": 1,
            "basis": f"PAGINATION:{paginated[1]}",
            "identity_gate": "PASS" if complete else "PARTIAL",
            "expected_set_hash": evidence.get("query_scope_set_hash"),
            "observed_set_hash": evidence.get("query_scope_set_hash"),
            "unexpected_scopes": 0,
        }
    endpoint = FAMILY_SOURCE_BINDINGS[family][1]
    if census.get("status") != "COMPLETE":
        return {
            "completed": 0,
            "expected": None,
            "basis": f"FIXTURE_SCOPE_UNPROVED:{endpoint}",
            "identity_gate": "UNKNOWN",
            "expected_set_hash": None,
            "observed_set_hash": None,
            "unexpected_scopes": 0,
        }
    # Direct deep endpoints require signed coverage/applicability evidence
    # (lineups flag, eligible team-fixtures, eligible event/player scopes).
    # Terminal fixture status alone is not that denominator, so retain UNKNOWN.
    return {
        "completed": 0,
        "expected": None,
        "basis": f"APPLICABILITY_UNPROVED:{endpoint}",
        "identity_gate": "UNKNOWN",
        "expected_set_hash": None,
        "observed_set_hash": None,
        "unexpected_scopes": 0,
    }


def _rate(
    numerator: int,
    denominator: int | None,
    *,
    empty_valid: bool = False,
) -> Mapping[str, object]:
    if numerator < 0 or denominator is not None and denominator < 0:
        raise ValueError("P0_RATE_NEGATIVE_COUNT")
    if denominator is None:
        return {
            "numerator": numerator,
            "denominator": None,
            "status": "UNKNOWN",
            "value": None,
        }
    if numerator > denominator:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "status": "INVALID",
            "value": None,
        }
    if denominator == 0:
        return {
            "numerator": numerator,
            "denominator": 0,
            "status": "EMPTY_VALID" if empty_valid and numerator == 0 else "INVALID",
            "value": None,
        }
    return {
        "numerator": numerator,
        "denominator": denominator,
        "status": "KNOWN",
        "value": round(numerator / denominator, 12),
    }


def _rate_complete(rate: Mapping[str, object]) -> bool:
    return (rate.get("status") == "KNOWN" and rate.get("value") == 1.0) or rate.get(
        "status"
    ) == "EMPTY_VALID"


def _rate_probe_acceptable(rate: Mapping[str, object]) -> bool:
    return rate.get("status") == "UNKNOWN" or _rate_complete(rate)


def _sample_fixture_proofs(
    selection: Mapping[str, object],
    *,
    competition: str,
    season: int,
) -> dict[int, Mapping[str, object]] | None:
    fixture_selection = _mapping(selection.get("fixture_selection"), label="P0_FIXTURE_SELECTION")
    target = fixture_selection.get("target_per_competition")
    if target is None:
        return None
    for sample_value in _sequence(fixture_selection.get("samples"), label="P0_FIXTURE_SAMPLES"):
        sample = _mapping(sample_value, label="P0_FIXTURE_SAMPLE")
        if sample.get("competition") == competition and sample.get("season") == season:
            proofs: dict[int, Mapping[str, object]] = {}
            for item in _sequence(sample.get("fixtures"), label="P0_SAMPLE_FIXTURES"):
                proof = _mapping(item, label="P0_FIXTURE_PROOF")
                fixture_id = _integer(
                    proof.get("fixture_id"),
                    label="P0_SAMPLE_FIXTURE_ID",
                    minimum=1,
                )
                if fixture_id in proofs:
                    raise ValueError("P0_FIXTURE_SAMPLE_ID_DUPLICATED")
                proofs[fixture_id] = proof
            return proofs
    raise ValueError("P0_FIXTURE_SAMPLE_SCOPE_MISSING")


def _known_expected_counts(
    *,
    family: str,
    census: Mapping[str, object],
    pairs: Sequence[VerifiedEvidencePair],
) -> tuple[int | None, str]:
    if census.get("status") == "COMPLETE":
        census_fields = {
            "fixtures": "fixtures",
            "teams": "team_slots",
            "venues": "applicable_venue_fixtures",
            "referees": "terminal_fixtures",
            "rounds": "distinct_rounds",
            "standings": "distinct_teams",
        }
        field = census_fields.get(family)
        if field is not None:
            if family == "standings" and not any(
                pair.entry.family == "standings" for pair in pairs
            ):
                return None, "STANDINGS_SOURCE_SCOPE_MISSING"
            return cast(int, census[field]), "AUTHORITATIVE_FIXTURE_CENSUS"
    return None, "DENOMINATOR_UNKNOWN"


def measure_partition(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    partition_id: str,
    inventory: VerifiedInventory,
    reader: PinnedInventoryReader,
    code_revision: str,
    attempt_slot: int = 1,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Measure exactly one committed selection partition."""

    if HEX40.fullmatch(code_revision) is None:
        raise ValueError("P0_MEASURE_CODE_REVISION_INVALID")
    if attempt_slot not in {1, 2}:
        raise ValueError("P0_MEASURE_ATTEMPT_SLOT_INVALID")
    selection_sha = validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    validate_selection_inventory_binding(
        authority,
        selection=selection,
        inventory=inventory,
    )
    supplement_sha256: str | None = None
    if selection.get("architecture_ordinal") == 2 and attempt_slot == 2:
        prior = _current_stage_receipt(authority, selection=selection)
        if (
            prior.get("measurement_integrity_gate") == "PASS"
            and prior.get("scientific_gate") == "FAIL"
        ):
            supplement_sha256, _quarantined_classifications = (
                _load_absence_taxonomy_supplement(
                    authority,
                    selection=selection,
                    prior=prior,
                )
            )
    matching = [
        _mapping(item, label="P0_MEASURE_PARTITION")
        for item in _sequence(selection.get("partitions"), label="P0_MEASURE_PARTITIONS")
        if _mapping(item, label="P0_MEASURE_PARTITION").get("partition_id") == partition_id
    ]
    if len(matching) != 1:
        raise ValueError("P0_MEASURE_PARTITION_NOT_UNIQUE")
    partition = matching[0]
    if selection.get("inventory_sha256") != inventory.manifest_sha256:
        raise ValueError("P0_MEASURE_INVENTORY_BINDING_MISMATCH")
    competition = _text(partition.get("competition"), label="P0_MEASURE_COMPETITION")
    season = _integer(partition.get("season"), label="P0_MEASURE_SEASON", minimum=1888)
    target_families = tuple(
        _text(item, label="P0_MEASURE_FAMILY")
        for item in _sequence(
            partition.get("normalized_families"),
            label="P0_MEASURE_FAMILIES",
        )
    )
    object_ids = tuple(
        _sha(item, label="P0_MEASURE_OBJECT_ID")
        for item in _sequence(
            partition.get("evidence_object_ids"),
            label="P0_MEASURE_OBJECT_IDS",
        )
    )
    inventory_index = inventory.by_id
    try:
        entries = tuple(inventory_index[object_id] for object_id in object_ids)
    except KeyError:
        raise ValueError("P0_MEASURE_OBJECT_NOT_IN_INVENTORY") from None
    if any(item.competition != competition or item.season != season for item in entries):
        raise ValueError("P0_MEASURE_OBJECT_SCOPE_MISMATCH")
    pairs = tuple(reader.fetch_pair(object_id) for object_id in object_ids)
    sample_proofs = _sample_fixture_proofs(
        selection,
        competition=competition,
        season=season,
    )
    sample_ids = None if sample_proofs is None else set(sample_proofs)
    fixture_census_pairs = _select_required_fixture_census_pairs(
        pairs,
        target_families=target_families,
        competition=competition,
        season=season,
    )
    authoritative_fixture_ids = {
        fixture_id
        for pair in fixture_census_pairs
        for row in pair.normalized.get("fixtures", ())
        if (fixture_id := _row_int(row, "provider_fixture_id")) is not None
    }
    processing_target_fixture_ids = authoritative_fixture_ids if sample_ids is None else sample_ids
    detail_envelopes = _integrated_detail_envelope_evidence(
        pairs,
        authoritative_fixture_ids=authoritative_fixture_ids,
    )
    fixture_census_object_ids = {pair.entry.object_id for pair in fixture_census_pairs}
    core_fixture_families = {"fixtures", "teams", "venues", "referees"}
    source_pairs_by_family: dict[str, tuple[VerifiedEvidencePair, ...]] = {}
    for family in target_families:
        if family in core_fixture_families:
            candidates = tuple(
                pair
                for pair in pairs
                if pair.entry.object_id in fixture_census_object_ids
                and _pair_matches_family_source(pair, family=family)
            )
        else:
            candidates = tuple(
                pair for pair in pairs if _pair_matches_family_source(pair, family=family)
            )
        if sample_ids is not None and family in FIXTURE_SCOPED_FAMILIES:
            candidates = tuple(
                pair
                for pair in candidates
                if family in core_fixture_families
                or _pair_intersects_fixture_sample(
                    pair,
                    family=family,
                    sample_ids=sample_ids,
                )
            )
        source_pairs_by_family[family] = candidates

    all_rows_by_family: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    provider_competition_id = int(competition.split(":", 1)[1])
    for family, source_pairs in source_pairs_by_family.items():
        for pair in source_pairs:
            for row in pair.normalized.get(family, ()):
                _validate_normalized_row_scope(
                    row,
                    competition_id=provider_competition_id,
                    season=season,
                )
                all_rows_by_family[family].append(row)
    rows_by_family: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for family, collected_rows in all_rows_by_family.items():
        if sample_ids is not None and family in FIXTURE_SCOPED_FAMILIES:
            rows_by_family[family].extend(
                row for row in collected_rows if _row_int(row, "provider_fixture_id") in sample_ids
            )
        else:
            rows_by_family[family].extend(collected_rows)
    fixture_applicability = _fixture_applicability_sets(rows_by_family.get("fixtures", []))
    for applicable_family, applicability_name in (
        ("venues", "venue"),
        ("referees", "terminal"),
    ):
        applicable_ids = fixture_applicability[applicability_name]
        rows_by_family[applicable_family] = [
            row
            for row in rows_by_family.get(applicable_family, [])
            if _row_int(row, "provider_fixture_id") in applicable_ids
        ]
    source_census = _fixture_census(fixture_census_pairs)
    census = source_census
    if sample_ids is not None:
        census = _fixture_row_census(
            rows_by_family.get("fixtures", []),
            pagination=_mapping(
                source_census.get("pagination"),
                label="P0_SAMPLE_SOURCE_PAGINATION",
            ),
        )
    raw_fixture_evidence = _raw_fixture_identity_evidence(
        fixture_census_pairs,
        sample_ids=sample_ids,
    )
    raw_fixture_families = _mapping(
        raw_fixture_evidence.get("families"),
        label="P0_RAW_FIXTURE_FAMILIES",
    )
    contracts = _mapping(authority.source_config.get("contracts"), label="P0_SOURCE_CONTRACTS")
    grain_binding = _mapping(contracts.get("grain_catalog"), label="P0_GRAIN_BINDING")
    grain_catalog = _load_json(
        authority.root / Path(_text(grain_binding.get("path"), label="P0_GRAIN_PATH")),
        label="P0_GRAIN_CATALOG",
    )
    family_bindings = _mapping(
        grain_catalog.get("family_bindings"),
        label="P0_GRAIN_FAMILY_BINDINGS",
    )
    grains = _mapping(grain_catalog.get("grains"), label="P0_GRAINS")
    suspension_pattern, injury_pattern = _absence_rule_patterns(authority)
    absence_source_pairs = tuple(
        {
            pair.entry.object_id: pair
            for family in ("injuries", "suspensions")
            for pair in source_pairs_by_family.get(family, ())
        }.values()
    )
    absence_classification = _classify_absence_source(
        absence_source_pairs,
        suspension_pattern=suspension_pattern,
        injury_pattern=injury_pattern,
    )
    absence_categories = _mapping(
        absence_classification.get("categories"),
        label="P0_ABSENCE_CLASSIFICATION_CATEGORIES",
    )
    injury_source_hashes = set(cast(frozenset[str], absence_categories.get("INJURY")))
    suspension_source_hashes = set(cast(frozenset[str], absence_categories.get("SUSPENSION")))
    unclassifiable_source_hashes = set(
        cast(frozenset[str], absence_categories.get("UNCLASSIFIABLE"))
    )
    raw_absence_hashes = set(cast(frozenset[str], absence_classification.get("raw_hashes")))
    # The versioned legacy normalizer remains an intermediate row producer.
    # P0 classification is authoritative on verified raw records above, then
    # reassigns only matching raw hashes; the legacy route cannot decide P0.
    normalized_absence_rows = [
        *all_rows_by_family.get("injuries", []),
        *all_rows_by_family.get("suspensions", []),
    ]
    normalized_absence_hashes = {
        _sha(row.get("source_record_hash"), label="P0_ABSENCE_SOURCE_HASH")
        for row in normalized_absence_rows
    }
    rows_by_family["injuries"] = [
        row
        for row in normalized_absence_rows
        if _sha(row.get("source_record_hash"), label="P0_INJURY_SOURCE_HASH")
        in injury_source_hashes
    ]
    rows_by_family["suspensions"] = [
        row
        for row in normalized_absence_rows
        if _sha(row.get("source_record_hash"), label="P0_SUSPENSION_SOURCE_HASH")
        in suspension_source_hashes
    ]
    absence_pagination = _pagination_evidence(
        absence_source_pairs,
        raw_family="injuries",
        endpoint="injuries",
    )
    absence_partition_valid = (
        absence_pagination.get("status") in {"COMPLETE", "UNKNOWN"}
        and raw_absence_hashes
        == injury_source_hashes
        | suspension_source_hashes
        | unclassifiable_source_hashes
        and len(raw_absence_hashes)
        == len(injury_source_hashes)
        + len(suspension_source_hashes)
        + len(unclassifiable_source_hashes)
        and not unclassifiable_source_hashes
        and normalized_absence_hashes.issubset(raw_absence_hashes)
        and (injury_source_hashes | suspension_source_hashes).issubset(normalized_absence_hashes)
        and absence_classification.get("invalid_identity") == 0
        and absence_classification.get("contradictory_identity") == 0
    )
    unclassifiable_absence_count = len(unclassifiable_source_hashes)
    absence_residual_profile = _build_absence_residual_profile(
        authority,
        selection=selection,
        selection_sha256=selection_sha,
        partition_id=partition_id,
        inventory_sha256=inventory.manifest_sha256,
        attempt_slot=attempt_slot,
        absence_source_object_ids=tuple(
            sorted(pair.entry.object_id for pair in absence_source_pairs)
        ),
        semantic_signatures=tuple(
            _mapping(item, label="P0_ABSENCE_RESIDUAL_PROFILE_INPUT")
            for item in _sequence(
                absence_classification.get("semantic_signatures"),
                label="P0_ABSENCE_RESIDUAL_PROFILE_INPUTS",
            )
        ),
        classification_supplement_sha256=supplement_sha256,
    )
    family_records: list[dict[str, object]] = []
    closure_forbidden = authority.stage in {"E1A", "E1B", "E2"}
    for family in target_families:
        family_rows = rows_by_family.get(family, [])
        counts = dict(_deduplicate_rows(family, family_rows))
        # Fixture-scoped families use the frozen sample census at E1/E2. Season-
        # scoped families remain unfiltered, so their denominator must come from
        # the complete source census or stay unknown; mixing a sample denominator
        # with full-season rows would manufacture numerator > denominator.
        denominator_census = census if family in FIXTURE_SCOPED_FAMILIES else source_census
        expected, denominator_basis = _known_expected_counts(
            family=family,
            census=denominator_census,
            pairs=source_pairs_by_family.get(family, ()),
        )
        if sample_ids is not None and family == "fixtures":
            expected = len(sample_ids)
            denominator_basis = "FROZEN_FIXTURE_SAMPLE"
        elif sample_ids is not None and family == "teams":
            expected = len(sample_ids) * 2
            denominator_basis = "FROZEN_FIXTURE_SAMPLE_TEAM_SLOTS"
        scope_evidence = _scope_completion_counts(
            family=family,
            pairs=source_pairs_by_family.get(family, ()),
            census=census,
        )
        completed_scopes = _integer(
            scope_evidence.get("completed"),
            label="P0_COMPLETED_SCOPES",
        )
        expected_scopes_value = scope_evidence.get("expected")
        expected_scopes = (
            None
            if expected_scopes_value is None
            else _integer(
                expected_scopes_value,
                label="P0_EXPECTED_SCOPES",
            )
        )
        scope_basis = _text(
            scope_evidence.get("basis"),
            label="P0_SCOPE_BASIS",
        )
        scope_identity_gate = _text(
            scope_evidence.get("identity_gate"),
            label="P0_SCOPE_IDENTITY_GATE",
        )
        raw_family_evidence = raw_fixture_families.get(family)
        raw_denominator: int | None = None
        expected_identity_key_hash: str | None = None
        if raw_fixture_evidence.get("status") == "COMPLETE" and isinstance(
            raw_family_evidence, Mapping
        ):
            raw_denominator = _integer(
                raw_family_evidence.get("raw_eligible_unique"),
                label="P0_RAW_ELIGIBLE_UNIQUE",
            )
            expected_identity_key_hash = _sha(
                raw_family_evidence.get("identity_key_set_hash"),
                label="P0_RAW_IDENTITY_KEY_SET_HASH",
            )
        if family in {"injuries", "suspensions"} and absence_pagination.get("status") == "COMPLETE":
            category = "INJURY" if family == "injuries" else "SUSPENSION"
            identity_counts = _mapping(
                absence_classification.get("identity_counts"),
                label="P0_ABSENCE_IDENTITY_COUNTS",
            )
            identity_hashes = _mapping(
                absence_classification.get("identity_key_set_hashes"),
                label="P0_ABSENCE_IDENTITY_HASHES",
            )
            raw_denominator = _integer(
                identity_counts.get(category),
                label="P0_ABSENCE_RAW_DENOMINATOR",
            )
            expected = raw_denominator
            denominator_basis = "SIGNED_ABSENCE_PARTITION_RULE"
            expected_identity_key_hash = _sha(
                identity_hashes.get(category),
                label="P0_ABSENCE_IDENTITY_KEY_SET_HASH",
            )
        normalized_unique = cast(int, counts["normalized_unique"])
        contradictions = cast(int, counts["contradictory_duplicates"])
        invalid = cast(int, counts["invalid_identity"])
        if family in {"fixtures", "teams"}:
            invalid += _integer(
                raw_fixture_evidence.get("invalid_raw_identity"),
                label="P0_RAW_FIXTURE_INVALID_IDENTITY",
            )
            contradictions += _integer(
                raw_fixture_evidence.get("contradictory_raw_identity"),
                label="P0_RAW_FIXTURE_CONTRADICTORY_IDENTITY",
            )
        if family == "player_season_statistics":
            observed_player_ids = {
                _row_int(row, "provider_player_id")
                for row in family_rows
                if _row_int(row, "provider_player_id") is not None
            }
            content_observed = len(observed_player_ids)
        elif family == "team_match_statistics":
            content_observed = len(
                {
                    (
                        _row_int(row, "provider_fixture_id"),
                        _row_int(row, "provider_team_id"),
                    )
                    for row in family_rows
                    if _row_int(row, "provider_fixture_id") is not None
                    and _row_int(row, "provider_team_id") is not None
                }
            )
        else:
            content_observed = normalized_unique
        scope_rate = _rate(
            completed_scopes,
            expected_scopes,
            empty_valid=True,
        )
        if scope_identity_gate == "FAIL":
            scope_rate = {
                "numerator": completed_scopes,
                "denominator": expected_scopes,
                "status": "INVALID",
                "value": None,
            }
        rates = {
            "scope_completion": scope_rate,
            "normalization_integrity": _rate(
                normalized_unique,
                raw_denominator,
                empty_valid=True,
            ),
            "content_presence": _rate(
                content_observed,
                expected,
                empty_valid=True,
            ),
        }

        unclassifiable_count = (
            unclassifiable_absence_count if family in {"injuries", "suspensions"} else 0
        )
        closure_state = "OPEN_MISSING_SCOPE"
        if closure_forbidden:
            closure_state = "OPEN_NOT_EVALUATED"
        elif contradictions:
            closure_state = "OPEN_CONFLICTING_DUPLICATE"
        elif invalid or unclassifiable_count:
            closure_state = "OPEN_CLASSIFICATION_AMBIGUOUS"
        elif (
            expected_identity_key_hash is not None
            and counts.get("identity_key_set_hash") == expected_identity_key_hash
            and scope_identity_gate == "PASS"
            and all(_rate_complete(rate) for rate in rates.values())
        ):
            closure_state = "DENOMINATOR_CLOSED_FULL_SCOPE"
        binding = _mapping(
            family_bindings.get(family),
            label="P0_FAMILY_GRAIN_BINDING",
        )
        grain = _mapping(
            grains.get(_text(binding.get("grain_id"), label="P0_GRAIN_ID")),
            label="P0_FAMILY_GRAIN",
        )
        source_pairs = source_pairs_by_family.get(family, ())
        processing_evidence = _processing_scope_evidence(
            family=family,
            pairs=pairs,
            detail_envelopes=detail_envelopes,
            authoritative_fixture_ids=authoritative_fixture_ids,
            target_fixture_ids=processing_target_fixture_ids,
        )
        dependency_pairs = {pair.entry.object_id: pair for pair in source_pairs}
        # The cell lineage covers every payload used by the calculation, not only
        # the payloads that materialized rows for the target family.  Fixture
        # census pages define several denominators and every deep-family
        # processing scope; deep envelope/direct-endpoint witnesses also prove
        # that the frozen target fixture set was actually processed.
        if family in FIXTURE_CENSUS_DEPENDENT_FAMILIES:
            dependency_pairs.update({pair.entry.object_id: pair for pair in fixture_census_pairs})
        processing_source_object_ids = tuple(
            _sha(item, label="P0_PROCESSING_SOURCE_OBJECT_ID")
            for item in _sequence(
                processing_evidence.get("source_object_ids"),
                label="P0_PROCESSING_SOURCE_OBJECT_IDS",
            )
        )
        pair_index = {pair.entry.object_id: pair for pair in pairs}
        try:
            dependency_pairs.update(
                {object_id: pair_index[object_id] for object_id in processing_source_object_ids}
            )
        except KeyError:
            raise ValueError("P0_PROCESSING_SOURCE_OBJECT_NOT_IN_PARTITION") from None
        source_lineage = sorted(
            (
                {
                    "object_id": pair.entry.object_id,
                    "receipt_hash": pair.entry.receipt_hash,
                    "payload_sha256": pair.entry.payload_sha256,
                }
                for pair in dependency_pairs.values()
            ),
            key=lambda item: str(item["object_id"]),
        )
        source_lineage_hash = canonical_sha256(source_lineage)
        processing_gate = _text(
            processing_evidence.get("gate"),
            label="P0_PROCESSING_SCOPE_GATE",
        )
        empty_valid_count = sum(
            str(pair.receipt.status.value) == "EMPTY_VALID" for pair in source_pairs
        )
        probe_gate = (
            bool(source_pairs)
            and scope_identity_gate != "FAIL"
            and processing_gate in {"PASS", "NOT_APPLICABLE"}
            and _rate_probe_acceptable(scope_rate)
            and _rate_probe_acceptable(
                _mapping(
                    rates["normalization_integrity"],
                    label="P0_NORMALIZATION_RATE",
                )
            )
            and (
                content_observed > 0
                or empty_valid_count > 0
                or _mapping(
                    rates["normalization_integrity"],
                    label="P0_NORMALIZATION_RATE",
                ).get("status")
                == "EMPTY_VALID"
            )
            and invalid == 0
            and contradictions == 0
            and unclassifiable_count == 0
        )
        content_rate = _mapping(
            rates["content_presence"],
            label="P0_CONTENT_RATE",
        )
        record: dict[str, object] = {
            "scope": "P0_2020_2025",
            "competition": competition,
            "season": season,
            "family": family,
            "grain": grain.get("grain"),
            "grain_id": binding.get("grain_id"),
            "source": grain.get("source"),
            "temporal_class": grain.get("temporal_class"),
            "source_lineage_hash": source_lineage_hash,
            "source_lineage": source_lineage,
            "source_object_count": len(source_lineage),
            "materialized_source_object_count": len(source_pairs),
            "source_object_set_hash": canonical_sha256(
                sorted(str(item["object_id"]) for item in source_lineage)
            ),
            "source_scopes_expected": expected_scopes,
            "source_scopes_verified": completed_scopes,
            "scope_basis": scope_basis,
            "scope_identity_gate": scope_identity_gate,
            "expected_scope_set_hash": scope_evidence.get("expected_set_hash"),
            "observed_scope_set_hash": scope_evidence.get("observed_set_hash"),
            "unexpected_scope_count": scope_evidence.get("unexpected_scopes"),
            "processing_scopes_expected": processing_evidence.get("expected"),
            "processing_scopes_verified": processing_evidence.get("completed"),
            "processing_scope_gate": processing_gate,
            "processing_expected_set_hash": processing_evidence.get("expected_set_hash"),
            "processing_observed_set_hash": processing_evidence.get("observed_set_hash"),
            "processing_missing_scope_count": processing_evidence.get("missing_scopes"),
            "processing_unexpected_scope_count": processing_evidence.get("unexpected_scopes"),
            "processing_source_object_ids": list(processing_source_object_ids),
            "processing_source_object_set_hash": processing_evidence.get("source_object_set_hash"),
            "counts": counts,
            "denominator_basis": denominator_basis,
            "raw_eligible_unique_entities": raw_denominator,
            "expected_content_slots": expected,
            "observed_content_slots": content_observed,
            "expected_count": expected,
            "received_count": content_observed,
            "empty_valid_count": empty_valid_count,
            "invalid_count": invalid,
            "unclassifiable_count": unclassifiable_count,
            "exact_duplicates": counts["exact_duplicates"],
            "contradictory_duplicates": contradictions,
            "coverage_percent": (
                content_rate.get("value") if content_rate.get("status") == "KNOWN" else None
            ),
            "normalization_integrity": rates["normalization_integrity"],
            "content_presence": rates["content_presence"],
            "null_rate": None,
            "null_rate_status": "UNKNOWN_NOT_PROVEN",
            "rates": rates,
            "closure_state": closure_state,
            "gate": ("READY" if closure_state == "DENOMINATOR_CLOSED_FULL_SCOPE" else "PARTIAL"),
            "probe_gate": "PASS" if probe_gate else "FAIL",
            "reason": closure_state,
        }
        record["cell_hash"] = canonical_sha256(record)
        family_records.append(record)
    family_unsigned: dict[str, object] = {
        "schema_version": FAMILY_COUNTS_SCHEMA_VERSION,
        "stage": authority.stage,
        "partition_id": partition_id,
        "selection_sha256": selection_sha,
        "competition": competition,
        "season": season,
        "family_group": partition.get("family_group"),
        "fixture_census": census,
        "source_fixture_census": source_census,
        "absence_partition": {
            "raw_distinct": len(raw_absence_hashes),
            "injuries_distinct": len(injury_source_hashes),
            "suspensions_distinct": len(suspension_source_hashes),
            "unclassifiable_distinct": unclassifiable_absence_count,
            "classification_rule_version": ABSENCE_CLASSIFICATION_RULE_VERSION,
            "classification_framework_sha256": (
                ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
            ),
            "classification_supplement_sha256": supplement_sha256,
            "classification_set_hash": canonical_sha256(
                {
                    "injuries": sorted(injury_source_hashes),
                    "suspensions": sorted(suspension_source_hashes),
                    "unclassifiable": sorted(unclassifiable_source_hashes),
                }
            ),
            "residual_profile": absence_residual_profile,
            "invariant": "PASS" if absence_partition_valid else "FAIL",
        },
        "families": family_records,
        "effects": dict(ZERO_EFFECTS),
    }
    family_counts = _signed(family_unsigned, field="counts_sha256")
    family_identity_gate = absence_partition_valid and all(
        record.get("invalid_count") == 0 and record.get("contradictory_duplicates") == 0
        for record in family_records
    )
    processing_identity_gate = all(
        record.get("processing_scope_gate") in {"PASS", "NOT_APPLICABLE"}
        for record in family_records
    )
    sample_fixture_proof_gate = True
    sample_identity_gate = family_identity_gate
    if sample_ids is not None and sample_proofs is not None:
        fixture_identity = _deduplicate_rows("fixtures", rows_by_family.get("fixtures", []))
        team_identity = _deduplicate_rows("teams", rows_by_family.get("teams", []))
        observed_proofs: dict[int, Mapping[str, object]] = {}
        proof_contradictions = 0
        for pair in fixture_census_pairs:
            for row in pair.normalized.get("fixtures", ()):
                fixture_id = _row_int(row, "provider_fixture_id")
                if fixture_id not in sample_ids:
                    continue
                proof = _fixture_proof(row, pair=pair)
                prior_proof = observed_proofs.get(fixture_id)
                if prior_proof is None:
                    observed_proofs[fixture_id] = proof
                elif prior_proof != proof:
                    proof_contradictions += 1
        sample_fixture_proof_gate = proof_contradictions == 0 and observed_proofs == sample_proofs
        sample_identity_gate = (
            sample_fixture_proof_gate
            and family_identity_gate
            and fixture_identity["normalized_unique"] == len(sample_ids)
            and fixture_identity["invalid_identity"] == 0
            and fixture_identity["contradictory_duplicates"] == 0
            and team_identity["normalized_unique"] == len(sample_ids) * 2
            and team_identity["invalid_identity"] == 0
            and team_identity["contradictory_duplicates"] == 0
        )
    receipt_unsigned: dict[str, object] = {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "stage": authority.stage,
        "partition_id": partition_id,
        "selection_sha256": selection_sha,
        "inventory_sha256": inventory.manifest_sha256,
        "measure_code_revision": code_revision,
        "competition": competition,
        "season": season,
        "family_group": partition.get("family_group"),
        "evidence_object_count": len(object_ids),
        "evidence_object_set_hash": canonical_sha256(sorted(object_ids)),
        "pairs_verified": len(pairs),
        "family_counts_sha256": family_counts["counts_sha256"],
        "family_lineage_hashes": {
            _text(record.get("family"), label="P0_RECEIPT_LINEAGE_FAMILY"): _sha(
                record.get("source_lineage_hash"),
                label="P0_RECEIPT_LINEAGE_HASH",
            )
            for record in family_records
        },
        "frozen_fixture_proof_gate": ("PASS" if sample_fixture_proof_gate else "FAIL")
        if sample_ids is not None
        else "NOT_APPLICABLE",
        "family_identity_gate": "PASS" if family_identity_gate else "FAIL",
        "sample_identity_gate": ("PASS" if sample_identity_gate else "FAIL"),
        "sample_processing_gate": ("PASS" if processing_identity_gate else "FAIL")
        if sample_ids is not None
        else "NOT_APPLICABLE",
        "scientific_status": ("MEASURED" if sample_identity_gate else "FAILED_IDENTITY_GATE"),
        "effects": dict(ZERO_EFFECTS),
    }
    return (
        _signed(receipt_unsigned, field="partition_receipt_sha256"),
        family_counts,
    )


def _load_shard_files(
    shards_directory: Path,
) -> tuple[
    tuple[
        tuple[
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
        ],
        ...,
    ],
    int,
]:
    expected_names = {
        "partition-receipt.json",
        "family-counts.json",
        "cost-report.json",
        "checkpoint-final.json",
    }
    directories = sorted(
        {path.parent for path in shards_directory.rglob("*.json") if path.name in expected_names}
    )
    output: list[
        tuple[
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
        ]
    ] = []
    invalid = 0
    for directory in directories:
        try:
            output.append(
                (
                    _load_json(
                        directory / "partition-receipt.json",
                        label="P0_SHARD_RECEIPT",
                    ),
                    _load_json(
                        directory / "family-counts.json",
                        label="P0_SHARD_FAMILY_COUNTS",
                    ),
                    _load_json(
                        directory / "cost-report.json",
                        label="P0_SHARD_COST",
                    ),
                    _load_json(
                        directory / "checkpoint-final.json",
                        label="P0_SHARD_CHECKPOINT",
                    ),
                )
            )
        except (ValueError, TypeError):
            invalid += 1
    return tuple(output), invalid


def _weighted_rates(
    family_records: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Aggregate rate numerators and denominators without averaging percentages."""

    output: dict[str, object] = {}
    for rate_name in (
        "scope_completion",
        "normalization_integrity",
        "content_presence",
    ):
        numerator = 0
        denominator = 0
        known_cells = 0
        empty_valid_cells = 0
        unknown_cells = 0
        invalid_cells = 0
        for record in family_records:
            rates = _mapping(record.get("rates"), label="P0_WEIGHTED_RATES")
            if set(rates) != {
                "scope_completion",
                "normalization_integrity",
                "content_presence",
            }:
                raise ValueError("P0_CELL_RATE_FIELDS_INVALID")
            rate = _mapping(
                rates.get(rate_name),
                label=f"P0_WEIGHTED_RATE_{rate_name.upper()}",
            )
            if set(rate) != {"numerator", "denominator", "status", "value"}:
                raise ValueError("P0_CELL_RATE_SHAPE_INVALID")
            cell_numerator = _integer(
                rate.get("numerator"),
                label="P0_CELL_RATE_NUMERATOR",
            )
            cell_denominator_value = rate.get("denominator")
            status = _text(rate.get("status"), label="P0_CELL_RATE_STATUS")
            value = rate.get("value")
            if status == "KNOWN":
                cell_denominator = _integer(
                    cell_denominator_value,
                    label="P0_CELL_RATE_DENOMINATOR",
                    minimum=1,
                )
                if (
                    cell_numerator > cell_denominator
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isclose(
                        float(value),
                        round(cell_numerator / cell_denominator, 12),
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                ):
                    raise ValueError("P0_CELL_KNOWN_RATE_INVALID")
                numerator += cell_numerator
                denominator += cell_denominator
                known_cells += 1
            elif status == "EMPTY_VALID":
                if cell_numerator != 0 or cell_denominator_value != 0 or value is not None:
                    raise ValueError("P0_CELL_EMPTY_VALID_RATE_INVALID")
                empty_valid_cells += 1
            elif status == "UNKNOWN":
                if cell_denominator_value is not None or value is not None:
                    raise ValueError("P0_CELL_UNKNOWN_RATE_INVALID")
                unknown_cells += 1
            elif status == "INVALID":
                if (
                    isinstance(cell_denominator_value, bool)
                    or not isinstance(cell_denominator_value, int)
                    or cell_denominator_value < 0
                    or value is not None
                ):
                    raise ValueError("P0_CELL_INVALID_RATE_INVALID")
                invalid_cells += 1
            else:
                raise ValueError("P0_CELL_RATE_STATUS_INVALID")
        if invalid_cells:
            aggregate_status = "INVALID"
            aggregate_value: float | None = None
        elif unknown_cells or not family_records:
            aggregate_status = "UNKNOWN"
            aggregate_value = None
        elif denominator == 0:
            aggregate_status = "EMPTY_VALID"
            aggregate_value = None
        else:
            aggregate_status = "KNOWN"
            aggregate_value = round(numerator / denominator, 12)
        output[rate_name] = {
            "numerator": numerator,
            "denominator": denominator,
            "status": aggregate_status,
            "value": aggregate_value,
            "known_cells": known_cells,
            "empty_valid_cells": empty_valid_cells,
            "unknown_cells": unknown_cells,
            "invalid_cells": invalid_cells,
            "aggregation": "SUM_NUMERATORS_AND_DENOMINATORS_NEVER_MEAN_OF_RATES",
        }
    return output


def _stage_time_limit_seconds(authority: CoverageAuthority) -> float:
    levels = _mapping(authority.mapping.get("levels"), label="P0_STAGE_LEVELS")
    level = _mapping(levels.get(authority.stage), label="P0_STAGE_LEVEL")
    field = {
        "E1A": "max_minutes_per_operation",
        "E1B": "max_minutes_per_operation",
        "E2": "max_minutes_per_operation",
        "E3A": "max_minutes_per_job",
        "E3B": "max_minutes_per_job",
        "E4": "absolute_max_minutes_per_job",
    }[authority.stage]
    return _number(level.get(field), label="P0_STAGE_MAX_MINUTES") * 60.0


def _checkpoint_time_limit_seconds(authority: CoverageAuthority) -> float:
    if authority.stage != "E4":
        return _stage_time_limit_seconds(authority)
    levels = _mapping(authority.mapping.get("levels"), label="P0_STAGE_LEVELS")
    level = _mapping(levels.get(authority.stage), label="P0_STAGE_LEVEL")
    return (
        _number(
            level.get("max_checkpoint_minutes"),
            label="P0_STAGE_MAX_CHECKPOINT_MINUTES",
        )
        * 60.0
    )


def _partition_cost_observation(
    cost: Mapping[str, object],
    *,
    expected_pairs: int,
) -> tuple[int, int, int]:
    """Validate successful read telemetry and return exact GET/stored/logical totals."""

    telemetry = _mapping(cost.get("telemetry"), label="P0_COST_TELEMETRY")
    if set(telemetry) != {
        "logical_gets",
        "bytes",
        "pairs_verified",
        "quota",
        "monetary_cost",
        "effects",
    }:
        raise ValueError("P0_COST_TELEMETRY_FIELDS_INVALID")
    gets = _mapping(telemetry.get("logical_gets"), label="P0_COST_TELEMETRY_GETS")
    if set(gets) != {
        "bootstrap",
        "receipt",
        "payload",
        "evidence_total",
        "physical_http_requests",
    }:
        raise ValueError("P0_COST_TELEMETRY_GET_FIELDS_INVALID")

    def exact_bucket(name: str, expected: int) -> None:
        bucket = _mapping(
            gets.get(name),
            label=f"P0_COST_TELEMETRY_{name.upper()}",
        )
        if set(bucket) != {"requested", "succeeded", "failed"} or (
            _integer(
                bucket.get("requested"),
                label=f"P0_COST_TELEMETRY_{name.upper()}_REQUESTED",
            )
            != expected
            or _integer(
                bucket.get("succeeded"),
                label=f"P0_COST_TELEMETRY_{name.upper()}_SUCCEEDED",
            )
            != expected
            or _integer(
                bucket.get("failed"),
                label=f"P0_COST_TELEMETRY_{name.upper()}_FAILED",
            )
            != 0
        ):
            raise ValueError("P0_COST_TELEMETRY_SUCCESS_COUNTS_INVALID")

    exact_bucket("bootstrap", 1)
    exact_bucket("receipt", expected_pairs)
    exact_bucket("payload", expected_pairs)
    evidence_gets = expected_pairs * 2
    if (
        gets.get("evidence_total") != evidence_gets
        or gets.get("physical_http_requests") != "UNKNOWN_NOT_OBSERVED"
        or telemetry.get("pairs_verified") != expected_pairs
        or telemetry.get("quota") != "UNKNOWN_NOT_OBSERVED"
        or telemetry.get("monetary_cost") != "UNKNOWN_NOT_OBSERVED"
        or _mapping(
            telemetry.get("effects"),
            label="P0_COST_TELEMETRY_EFFECTS",
        )
        != ZERO_EFFECTS
    ):
        raise ValueError("P0_COST_TELEMETRY_TOTALS_INVALID")
    byte_fields = _mapping(telemetry.get("bytes"), label="P0_COST_TELEMETRY_BYTES")
    expected_byte_fields = {
        "bootstrap_stored",
        "bootstrap_logical",
        "receipt",
        "payload_stored",
        "payload_logical",
        "peak_pair",
    }
    if set(byte_fields) != expected_byte_fields:
        raise ValueError("P0_COST_TELEMETRY_BYTE_FIELDS_INVALID")
    byte_values = {
        field: _integer(
            byte_fields.get(field),
            label=f"P0_COST_TELEMETRY_{field.upper()}",
        )
        for field in expected_byte_fields
    }
    logical_gets = 1 + evidence_gets
    stored_bytes = (
        byte_values["bootstrap_stored"] + byte_values["receipt"] + byte_values["payload_stored"]
    )
    logical_bytes = (
        byte_values["bootstrap_logical"] + byte_values["receipt"] + byte_values["payload_logical"]
    )
    reads = _mapping(cost.get("reads"), label="P0_COST_READS")
    if set(reads) != {
        "logical_gets",
        "physical_http_requests",
        "stored_bytes",
        "logical_bytes",
    } or reads != {
        "logical_gets": logical_gets,
        "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
        "stored_bytes": stored_bytes,
        "logical_bytes": logical_bytes,
    }:
        raise ValueError("P0_COST_READ_TELEMETRY_MISMATCH")
    return logical_gets, stored_bytes, logical_bytes


def build_partition_checkpoint(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    partition_id: str,
    code_revision: str,
    attempt_slot: int,
    status: str,
    elapsed_seconds: float,
    output_bindings: Mapping[str, object] | None = None,
    failure_code: str | None = None,
    github_run_id: str = "LOCAL_TEST",
    github_run_attempt: str = "1",
) -> Mapping[str, object]:
    """Build a signed, secret-free partition progress checkpoint.

    A completed checkpoint is reusable only when it binds the three successful
    shard outputs. STARTED and FAILED checkpoints remain operational evidence;
    they cannot satisfy a scientific predecessor gate.
    """

    selection_sha = validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    if HEX40.fullmatch(code_revision) is None:
        raise ValueError("P0_CHECKPOINT_CODE_REVISION_INVALID")
    if attempt_slot not in {1, 2}:
        raise ValueError("P0_CHECKPOINT_ATTEMPT_SLOT_INVALID")
    if status not in {"STARTED", "COMPLETED", "FAILED"}:
        raise ValueError("P0_CHECKPOINT_STATUS_INVALID")
    if SAFE_ID.fullmatch(partition_id) is None:
        raise ValueError("P0_CHECKPOINT_PARTITION_ID_INVALID")
    partitions = tuple(
        _mapping(item, label="P0_CHECKPOINT_PARTITION")
        for item in _sequence(
            selection.get("partitions"),
            label="P0_CHECKPOINT_PARTITIONS",
        )
        if _mapping(item, label="P0_CHECKPOINT_PARTITION").get("partition_id") == partition_id
    )
    if len(partitions) != 1:
        raise ValueError("P0_CHECKPOINT_PARTITION_NOT_UNIQUE")
    elapsed = _number(
        elapsed_seconds,
        label="P0_CHECKPOINT_ELAPSED_SECONDS",
    )
    maximum_interval = _checkpoint_time_limit_seconds(authority)
    bindings = dict(output_bindings or {})
    expected_bindings = {
        "partition_receipt_sha256",
        "family_counts_sha256",
        "cost_sha256",
    }
    if status == "COMPLETED":
        if set(bindings) != expected_bindings:
            raise ValueError("P0_CHECKPOINT_OUTPUT_BINDINGS_INVALID")
        bindings = {
            key: _sha(value, label=f"P0_CHECKPOINT_{key.upper()}")
            for key, value in bindings.items()
        }
        if failure_code is not None:
            raise ValueError("P0_CHECKPOINT_COMPLETED_FAILURE_CODE_INVALID")
    else:
        if bindings:
            raise ValueError("P0_CHECKPOINT_NONCOMPLETED_OUTPUT_BINDING")
        if status == "STARTED" and failure_code is not None:
            raise ValueError("P0_CHECKPOINT_STARTED_FAILURE_CODE_INVALID")
        if status == "FAILED" and (
            not isinstance(failure_code, str) or SAFE_ID.fullmatch(failure_code) is None
        ):
            raise ValueError("P0_CHECKPOINT_FAILURE_CODE_INVALID")
    checkpoint_gate = (
        "PASS"
        if status == "COMPLETED" and elapsed <= maximum_interval
        else ("PENDING" if status == "STARTED" else "FAIL")
    )
    unsigned: dict[str, object] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "stage": authority.stage,
        "partition_id": partition_id,
        "selection_sha256": selection_sha,
        "inventory_sha256": selection.get("inventory_sha256"),
        "code_revision": code_revision,
        "architecture_fingerprint": evidence_architecture_fingerprint(authority),
        "attempt_slot": attempt_slot,
        "status": status,
        "elapsed_seconds_since_measurement_start": round(elapsed, 6),
        "maximum_checkpoint_interval_seconds": maximum_interval,
        "checkpoint_gate": checkpoint_gate,
        "reusable": checkpoint_gate == "PASS",
        "output_bindings": bindings,
        "failure_code": failure_code,
        "failed_read_accounting": (
            "UNKNOWN_NOT_OBSERVED" if status == "FAILED" else "NOT_APPLICABLE"
        ),
        "github_run_id": _text(github_run_id, label="P0_CHECKPOINT_GITHUB_RUN_ID"),
        "github_run_attempt": _text(
            github_run_attempt,
            label="P0_CHECKPOINT_GITHUB_RUN_ATTEMPT",
        ),
        "durability": "REQUIRES_GIT_COMMIT_BEFORE_SCALE",
        "github_artifact_is_unique_scientific_proof": False,
        "effects": dict(ZERO_EFFECTS),
    }
    return _signed(unsigned, field="checkpoint_sha256")


def _scale_failure_decision(
    *,
    selection: Mapping[str, object],
    attempt_slot: int,
    missing_source_cell_keys: Sequence[object],
    scientific_failure: bool,
) -> str:
    return (
        "FAIL_AND_STOP"
        if missing_source_cell_keys
        or (
            selection.get("architecture_ordinal") == 2
            and (scientific_failure or attempt_slot == 2)
        )
        else "FAIL_AND_REDESIGN"
    )


def aggregate_stage(
    authority: CoverageAuthority,
    *,
    selection: Mapping[str, object],
    shards_directory: Path,
    attempt_slot: int = 1,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
]:
    if attempt_slot not in {1, 2}:
        raise ValueError("P0_AGGREGATE_ATTEMPT_SLOT_INVALID")
    selection_sha = validate_selection(
        selection,
        authority=authority,
        stage=authority.stage,
    )
    committed_selection_path = (
        authority.root
        / "configs"
        / "data"
        / f"p0-coverage-evidence-selection-{authority.stage}-v1.json"
    )
    if committed_selection_path.exists():
        _validate_live_selection_mission_baseline(
            authority,
            selection=selection,
        )
    if attempt_slot == 2:
        # Aggregation is also a public CLI/API boundary. Reapply the exact retry
        # preconditions here so callers cannot bypass the workflow preflight.
        validate_stage_attempt(
            authority,
            operation="measure",
            attempt_slot=attempt_slot,
        )
    expected_supplement_sha256: str | None = None
    if selection.get("architecture_ordinal") == 2 and attempt_slot == 2:
        supplement_prior = _current_stage_receipt(authority, selection=selection)
        if (
            supplement_prior.get("measurement_integrity_gate") == "PASS"
            and supplement_prior.get("scientific_gate") == "FAIL"
        ):
            expected_supplement_sha256, _classifications = (
                _load_absence_taxonomy_supplement(
                    authority,
                    selection=selection,
                    prior=supplement_prior,
                )
            )
    expected_partitions: dict[str, Mapping[str, object]] = {}
    expected_cell_keys: set[tuple[str, int, str]] = set()
    for partition_value in _sequence(
        selection.get("partitions"),
        label="P0_AGGREGATE_PARTITIONS",
    ):
        partition = _mapping(partition_value, label="P0_AGGREGATE_PARTITION")
        partition_id = _text(
            partition.get("partition_id"),
            label="P0_AGGREGATE_PARTITION_ID",
        )
        competition = _text(
            partition.get("competition"),
            label="P0_AGGREGATE_COMPETITION",
        )
        season = _integer(
            partition.get("season"),
            label="P0_AGGREGATE_SEASON",
            minimum=1888,
        )
        families = tuple(
            _text(item, label="P0_AGGREGATE_EXPECTED_FAMILY")
            for item in _sequence(
                partition.get("normalized_families"),
                label="P0_AGGREGATE_EXPECTED_FAMILIES",
            )
        )
        expected_partitions[partition_id] = partition
        expected_cell_keys.update((competition, season, family) for family in families)
    expected_ids = set(expected_partitions)
    shards, malformed_shards = _load_shard_files(shards_directory)
    observed_ids: list[str] = []
    observed_cell_keys: list[tuple[str, int, str]] = []
    family_records: list[Mapping[str, object]] = []
    cost_reports: list[Mapping[str, object]] = []
    checkpoint_hashes: dict[str, str] = {}
    absence_residual_profiles: list[Mapping[str, object]] = []
    observed_attempt_slots: list[int] = []
    resource_reports: list[tuple[str, float, int | None]] = []
    failed_scientific_partition_ids: list[str] = []
    invalid_shards = malformed_shards
    for receipt, counts, cost, checkpoint in shards:
        try:
            if set(receipt) != {
                "schema_version",
                "stage",
                "partition_id",
                "selection_sha256",
                "inventory_sha256",
                "measure_code_revision",
                "competition",
                "season",
                "family_group",
                "evidence_object_count",
                "evidence_object_set_hash",
                "pairs_verified",
                "family_counts_sha256",
                "family_lineage_hashes",
                "frozen_fixture_proof_gate",
                "family_identity_gate",
                "sample_identity_gate",
                "sample_processing_gate",
                "scientific_status",
                "effects",
                "partition_receipt_sha256",
            }:
                raise ValueError("P0_PARTITION_RECEIPT_FIELDS_INVALID")
            if set(counts) != {
                "schema_version",
                "stage",
                "partition_id",
                "selection_sha256",
                "competition",
                "season",
                "family_group",
                "fixture_census",
                "source_fixture_census",
                "absence_partition",
                "families",
                "effects",
                "counts_sha256",
            }:
                raise ValueError("P0_FAMILY_COUNTS_FIELDS_INVALID")
            if set(cost) != {
                "schema_version",
                "stage",
                "partition_id",
                "attempt_slot",
                "selection_sha256",
                "reads",
                "resources",
                "telemetry",
                "quota",
                "monetary_cost",
                "effects",
                "cost_sha256",
            }:
                raise ValueError("P0_PARTITION_COST_FIELDS_INVALID")
            if set(checkpoint) != {
                "schema_version",
                "stage",
                "partition_id",
                "selection_sha256",
                "inventory_sha256",
                "code_revision",
                "architecture_fingerprint",
                "attempt_slot",
                "status",
                "elapsed_seconds_since_measurement_start",
                "maximum_checkpoint_interval_seconds",
                "checkpoint_gate",
                "reusable",
                "output_bindings",
                "failure_code",
                "failed_read_accounting",
                "github_run_id",
                "github_run_attempt",
                "durability",
                "github_artifact_is_unique_scientific_proof",
                "effects",
                "checkpoint_sha256",
            }:
                raise ValueError("P0_PARTITION_CHECKPOINT_FIELDS_INVALID")
            receipt_hash = _verify_signed(
                receipt,
                field="partition_receipt_sha256",
                label="P0_PARTITION_RECEIPT",
            )
            del receipt_hash
            counts_hash = _verify_signed(counts, field="counts_sha256", label="P0_FAMILY_COUNTS")
            cost_hash = _verify_signed(cost, field="cost_sha256", label="P0_PARTITION_COST")
            checkpoint_hash = _verify_signed(
                checkpoint,
                field="checkpoint_sha256",
                label="P0_PARTITION_CHECKPOINT",
            )
            partition_id = _text(receipt.get("partition_id"), label="P0_SHARD_PARTITION_ID")
            expected_partition = expected_partitions.get(partition_id)
            if expected_partition is None:
                observed_ids.append(partition_id)
                raise ValueError("P0_SHARD_PARTITION_UNEXPECTED")
            competition = _text(
                expected_partition.get("competition"),
                label="P0_SHARD_EXPECTED_COMPETITION",
            )
            season = _integer(
                expected_partition.get("season"),
                label="P0_SHARD_EXPECTED_SEASON",
                minimum=1888,
            )
            family_group = _text(
                expected_partition.get("family_group"),
                label="P0_SHARD_EXPECTED_FAMILY_GROUP",
            )
            expected_families = tuple(
                _text(item, label="P0_SHARD_EXPECTED_FAMILY")
                for item in _sequence(
                    expected_partition.get("normalized_families"),
                    label="P0_SHARD_EXPECTED_FAMILIES",
                )
            )
            expected_object_ids = tuple(
                _sha(item, label="P0_SHARD_EXPECTED_OBJECT_ID")
                for item in _sequence(
                    expected_partition.get("evidence_object_ids"),
                    label="P0_SHARD_EXPECTED_OBJECT_IDS",
                )
            )
            receipt_lineages = _mapping(
                receipt.get("family_lineage_hashes"),
                label="P0_SHARD_FAMILY_LINEAGES",
            )
            absence_partition = _mapping(
                counts.get("absence_partition"),
                label="P0_SHARD_ABSENCE_PARTITION",
            )
            if set(absence_partition) != {
                "raw_distinct",
                "injuries_distinct",
                "suspensions_distinct",
                "unclassifiable_distinct",
                "classification_rule_version",
                "classification_framework_sha256",
                "classification_supplement_sha256",
                "classification_set_hash",
                "residual_profile",
                "invariant",
            }:
                raise ValueError("P0_SHARD_ABSENCE_PARTITION_FIELDS_INVALID")
            absence_raw = _integer(
                absence_partition.get("raw_distinct"),
                label="P0_SHARD_ABSENCE_RAW_DISTINCT",
            )
            absence_injuries = _integer(
                absence_partition.get("injuries_distinct"),
                label="P0_SHARD_ABSENCE_INJURIES_DISTINCT",
            )
            absence_suspensions = _integer(
                absence_partition.get("suspensions_distinct"),
                label="P0_SHARD_ABSENCE_SUSPENSIONS_DISTINCT",
            )
            absence_unclassifiable = _integer(
                absence_partition.get("unclassifiable_distinct"),
                label="P0_SHARD_ABSENCE_UNCLASSIFIABLE_DISTINCT",
            )
            absence_classified = (
                absence_injuries
                + absence_suspensions
                + absence_unclassifiable
            )
            shard_attempt_slot = _integer(
                cost.get("attempt_slot"),
                label="P0_SHARD_ABSENCE_ATTEMPT_SLOT",
                minimum=1,
            )
            absence_residual_profile = _validate_absence_residual_profile(
                absence_partition.get("residual_profile"),
                authority=authority,
                selection=selection,
                expected_selection_sha256=selection_sha,
                expected_inventory_sha256=_sha(
                    selection.get("inventory_sha256"),
                    label="P0_SHARD_ABSENCE_INVENTORY",
                ),
                expected_attempt_slot=shard_attempt_slot,
            )
            absence_invariant = absence_partition.get("invariant")
            if (
                absence_raw != absence_classified
                or absence_partition.get("classification_rule_version")
                != ABSENCE_CLASSIFICATION_RULE_VERSION
                or absence_partition.get("classification_framework_sha256")
                != ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256
                or HEX64.fullmatch(str(absence_partition.get("classification_set_hash"))) is None
                or absence_residual_profile.get("partition_id") != partition_id
                or absence_residual_profile.get("unclassifiable_record_count")
                != absence_unclassifiable
                or (
                    shard_attempt_slot == 1
                    and absence_partition.get("classification_supplement_sha256") is not None
                )
                or absence_partition.get("classification_supplement_sha256")
                != absence_residual_profile.get("classification_supplement_sha256")
                or absence_partition.get("classification_supplement_sha256")
                != expected_supplement_sha256
                or absence_invariant not in {"PASS", "FAIL"}
                or (absence_invariant == "PASS" and absence_unclassifiable != 0)
            ):
                raise ValueError("P0_SHARD_ABSENCE_PARTITION_INVALID")
            fixture_proof_gate = receipt.get("frozen_fixture_proof_gate")
            family_identity_gate = receipt.get("family_identity_gate")
            sample_identity_gate = receipt.get("sample_identity_gate")
            scientific_status = receipt.get("scientific_status")
            if authority.stage in {"E1A", "E1B", "E2"}:
                fixture_proof_gate_valid = fixture_proof_gate in {"PASS", "FAIL"}
            else:
                fixture_proof_gate_valid = fixture_proof_gate == "NOT_APPLICABLE"
            identity_outcome_valid = (
                family_identity_gate in {"PASS", "FAIL"}
                and sample_identity_gate in {"PASS", "FAIL"}
                and (sample_identity_gate != "PASS" or family_identity_gate == "PASS")
                and (
                    scientific_status
                    == ("MEASURED" if sample_identity_gate == "PASS" else "FAILED_IDENTITY_GATE")
                )
                and (sample_identity_gate != "PASS" or fixture_proof_gate != "FAIL")
            )
            if (
                receipt.get("schema_version") != PARTITION_SCHEMA_VERSION
                or receipt.get("stage") != authority.stage
                or receipt.get("selection_sha256") != selection_sha
                or receipt.get("inventory_sha256") != selection.get("inventory_sha256")
                or receipt.get("family_counts_sha256") != counts_hash
                or receipt.get("competition") != competition
                or receipt.get("season") != season
                or receipt.get("family_group") != family_group
                or receipt.get("evidence_object_count") != len(expected_object_ids)
                or receipt.get("evidence_object_set_hash")
                != canonical_sha256(sorted(expected_object_ids))
                or receipt.get("pairs_verified") != len(expected_object_ids)
                or not fixture_proof_gate_valid
                or not identity_outcome_valid
                or set(receipt_lineages) != set(expected_families)
                or counts.get("schema_version") != FAMILY_COUNTS_SCHEMA_VERSION
                or counts.get("stage") != authority.stage
                or counts.get("partition_id") != partition_id
                or counts.get("selection_sha256") != selection_sha
                or counts.get("competition") != competition
                or counts.get("season") != season
                or counts.get("family_group") != family_group
                or cost.get("schema_version") != "p0-coverage-partition-cost-v1"
                or cost.get("stage") != authority.stage
                or cost.get("partition_id") != partition_id
                or cost.get("attempt_slot") not in {1, 2}
                or cost.get("selection_sha256") != selection_sha
                or checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
                or checkpoint.get("stage") != authority.stage
                or checkpoint.get("partition_id") != partition_id
                or checkpoint.get("selection_sha256") != selection_sha
                or checkpoint.get("inventory_sha256") != selection.get("inventory_sha256")
                or checkpoint.get("code_revision") != receipt.get("measure_code_revision")
                or checkpoint.get("architecture_fingerprint")
                != evidence_architecture_fingerprint(authority)
                or checkpoint.get("attempt_slot") not in {1, 2}
                or checkpoint.get("attempt_slot") != cost.get("attempt_slot")
                or checkpoint.get("status") != "COMPLETED"
                or checkpoint.get("checkpoint_gate") != "PASS"
                or checkpoint.get("reusable") is not True
                or checkpoint.get("failure_code") is not None
                or checkpoint.get("failed_read_accounting") != "NOT_APPLICABLE"
                or checkpoint.get("maximum_checkpoint_interval_seconds")
                != _checkpoint_time_limit_seconds(authority)
                or _number(
                    checkpoint.get("elapsed_seconds_since_measurement_start"),
                    label="P0_SHARD_CHECKPOINT_ELAPSED_SECONDS",
                )
                > _checkpoint_time_limit_seconds(authority)
                or _mapping(
                    checkpoint.get("output_bindings"),
                    label="P0_SHARD_CHECKPOINT_OUTPUT_BINDINGS",
                )
                != {
                    "partition_receipt_sha256": receipt.get("partition_receipt_sha256"),
                    "family_counts_sha256": counts_hash,
                    "cost_sha256": cost_hash,
                }
                or checkpoint.get("durability") != "REQUIRES_GIT_COMMIT_BEFORE_SCALE"
                or checkpoint.get("github_artifact_is_unique_scientific_proof") is not False
                or _mapping(receipt.get("effects"), label="P0_SHARD_EFFECTS") != ZERO_EFFECTS
                or _mapping(counts.get("effects"), label="P0_COUNTS_EFFECTS") != ZERO_EFFECTS
                or _mapping(cost.get("effects"), label="P0_COST_EFFECTS") != ZERO_EFFECTS
                or _mapping(checkpoint.get("effects"), label="P0_CHECKPOINT_EFFECTS")
                != ZERO_EFFECTS
            ):
                raise ValueError("P0_SHARD_BINDING_INVALID")
            shard_family_records = tuple(
                _mapping(item, label="P0_AGGREGATE_FAMILY")
                for item in _sequence(
                    counts.get("families"),
                    label="P0_AGGREGATE_FAMILIES",
                )
            )
            required_cell_fields = {
                "scope",
                "competition",
                "season",
                "family",
                "grain",
                "grain_id",
                "source",
                "temporal_class",
                "source_lineage_hash",
                "source_lineage",
                "source_object_count",
                "materialized_source_object_count",
                "source_object_set_hash",
                "source_scopes_expected",
                "source_scopes_verified",
                "scope_basis",
                "scope_identity_gate",
                "expected_scope_set_hash",
                "observed_scope_set_hash",
                "unexpected_scope_count",
                "processing_scopes_expected",
                "processing_scopes_verified",
                "processing_scope_gate",
                "processing_expected_set_hash",
                "processing_observed_set_hash",
                "processing_missing_scope_count",
                "processing_unexpected_scope_count",
                "processing_source_object_ids",
                "processing_source_object_set_hash",
                "counts",
                "denominator_basis",
                "raw_eligible_unique_entities",
                "expected_content_slots",
                "observed_content_slots",
                "expected_count",
                "received_count",
                "empty_valid_count",
                "invalid_count",
                "unclassifiable_count",
                "exact_duplicates",
                "contradictory_duplicates",
                "coverage_percent",
                "normalization_integrity",
                "content_presence",
                "null_rate",
                "null_rate_status",
                "rates",
                "closure_state",
                "gate",
                "probe_gate",
                "reason",
                "cell_hash",
            }
            for cell in shard_family_records:
                _verify_signed(cell, field="cell_hash", label="P0_COVERAGE_CELL")
                family = _text(cell.get("family"), label="P0_CELL_FAMILY")
                rates = _mapping(cell.get("rates"), label="P0_CELL_RATES")
                scope_rate = _mapping(
                    rates.get("scope_completion"),
                    label="P0_CELL_SCOPE_RATE",
                )
                content_rate = _mapping(
                    rates.get("content_presence"),
                    label="P0_CELL_CONTENT_RATE",
                )
                source_object_count = _integer(
                    cell.get("source_object_count"),
                    label="P0_CELL_SOURCE_OBJECT_COUNT",
                )
                materialized_source_object_count = _integer(
                    cell.get("materialized_source_object_count"),
                    label="P0_CELL_MATERIALIZED_SOURCE_OBJECT_COUNT",
                )
                invalid_count = _integer(
                    cell.get("invalid_count"),
                    label="P0_CELL_INVALID_COUNT",
                )
                contradictory_duplicates = _integer(
                    cell.get("contradictory_duplicates"),
                    label="P0_CELL_CONTRADICTORY_DUPLICATES",
                )
                exact_duplicates = _integer(
                    cell.get("exact_duplicates"),
                    label="P0_CELL_EXACT_DUPLICATES",
                )
                received_count = _integer(
                    cell.get("received_count"),
                    label="P0_CELL_RECEIVED_COUNT",
                )
                empty_valid_count = _integer(
                    cell.get("empty_valid_count"),
                    label="P0_CELL_EMPTY_VALID_COUNT",
                )
                unclassifiable_count = _integer(
                    cell.get("unclassifiable_count"),
                    label="P0_CELL_UNCLASSIFIABLE_COUNT",
                )
                _text(cell.get("scope_basis"), label="P0_CELL_SCOPE_BASIS")
                _text(
                    cell.get("denominator_basis"),
                    label="P0_CELL_DENOMINATOR_BASIS",
                )
                source_scopes_verified = _integer(
                    cell.get("source_scopes_verified"),
                    label="P0_CELL_SOURCE_SCOPES_VERIFIED",
                )
                source_scopes_expected_value = cell.get("source_scopes_expected")
                source_scopes_expected = (
                    None
                    if source_scopes_expected_value is None
                    else _integer(
                        source_scopes_expected_value,
                        label="P0_CELL_SOURCE_SCOPES_EXPECTED",
                    )
                )
                identity_counts = _mapping(
                    cell.get("counts"),
                    label="P0_CELL_IDENTITY_COUNTS",
                )
                if set(identity_counts) != {
                    "normalized_rows",
                    "normalized_unique",
                    "invalid_identity",
                    "exact_duplicates",
                    "contradictory_duplicates",
                    "identity_key_set_hash",
                    "identity_set_hash",
                }:
                    raise ValueError("P0_CELL_IDENTITY_COUNT_FIELDS_INVALID")
                for count_field in (
                    "normalized_rows",
                    "normalized_unique",
                    "invalid_identity",
                    "exact_duplicates",
                    "contradictory_duplicates",
                ):
                    _integer(
                        identity_counts.get(count_field),
                        label=f"P0_CELL_{count_field.upper()}",
                    )
                normalized_unique = _integer(
                    identity_counts.get("normalized_unique"),
                    label="P0_CELL_NORMALIZED_UNIQUE",
                )
                identity_invalid = _integer(
                    identity_counts.get("invalid_identity"),
                    label="P0_CELL_IDENTITY_INVALID",
                )
                identity_exact_duplicates = _integer(
                    identity_counts.get("exact_duplicates"),
                    label="P0_CELL_IDENTITY_EXACT_DUPLICATES",
                )
                identity_contradictions = _integer(
                    identity_counts.get("contradictory_duplicates"),
                    label="P0_CELL_IDENTITY_CONTRADICTIONS",
                )
                _sha(
                    identity_counts.get("identity_key_set_hash"),
                    label="P0_CELL_IDENTITY_KEY_SET_HASH",
                )
                _sha(
                    identity_counts.get("identity_set_hash"),
                    label="P0_CELL_IDENTITY_SET_HASH",
                )
                raw_eligible_value = cell.get("raw_eligible_unique_entities")
                raw_eligible = (
                    None
                    if raw_eligible_value is None
                    else _integer(
                        raw_eligible_value,
                        label="P0_CELL_RAW_ELIGIBLE_UNIQUE_ENTITIES",
                    )
                )
                expected_content_value = cell.get("expected_content_slots")
                expected_content_slots = (
                    None
                    if expected_content_value is None
                    else _integer(
                        expected_content_value,
                        label="P0_CELL_EXPECTED_CONTENT_SLOTS",
                    )
                )
                observed_content_slots = _integer(
                    cell.get("observed_content_slots"),
                    label="P0_CELL_OBSERVED_CONTENT_SLOTS",
                )
                normalization_rate = _mapping(
                    rates.get("normalization_integrity"),
                    label="P0_CELL_NORMALIZATION_RATE",
                )
                source_lineage = tuple(
                    _mapping(item, label="P0_CELL_SOURCE_LINEAGE_ITEM")
                    for item in _sequence(
                        cell.get("source_lineage"),
                        label="P0_CELL_SOURCE_LINEAGE",
                    )
                )
                lineage_object_ids: list[str] = []
                for item in source_lineage:
                    if set(item) != {"object_id", "receipt_hash", "payload_sha256"}:
                        raise ValueError("P0_CELL_SOURCE_LINEAGE_FIELDS_INVALID")
                    lineage_object_ids.append(
                        _sha(item.get("object_id"), label="P0_CELL_LINEAGE_OBJECT_ID")
                    )
                    _sha(item.get("receipt_hash"), label="P0_CELL_LINEAGE_RECEIPT_HASH")
                    _sha(item.get("payload_sha256"), label="P0_CELL_LINEAGE_PAYLOAD_HASH")
                processing_scope_gate = _text(
                    cell.get("processing_scope_gate"),
                    label="P0_CELL_PROCESSING_SCOPE_GATE",
                )
                processing_verified = _integer(
                    cell.get("processing_scopes_verified"),
                    label="P0_CELL_PROCESSING_SCOPES_VERIFIED",
                )
                processing_missing = _integer(
                    cell.get("processing_missing_scope_count"),
                    label="P0_CELL_PROCESSING_SCOPES_MISSING",
                )
                processing_unexpected = _integer(
                    cell.get("processing_unexpected_scope_count"),
                    label="P0_CELL_PROCESSING_SCOPES_UNEXPECTED",
                )
                processing_source_object_ids = tuple(
                    _sha(item, label="P0_CELL_PROCESSING_SOURCE_OBJECT_ID")
                    for item in _sequence(
                        cell.get("processing_source_object_ids"),
                        label="P0_CELL_PROCESSING_SOURCE_OBJECT_IDS",
                    )
                )
                processing_expected_value = cell.get("processing_scopes_expected")
                processing_expected = (
                    None
                    if processing_expected_value is None
                    else _integer(
                        processing_expected_value,
                        label="P0_CELL_PROCESSING_SCOPES_EXPECTED",
                    )
                )
                expected_probe_gate = (
                    materialized_source_object_count > 0
                    and cell.get("scope_identity_gate") != "FAIL"
                    and processing_scope_gate in {"PASS", "NOT_APPLICABLE"}
                    and _rate_probe_acceptable(
                        _mapping(
                            rates.get("scope_completion"),
                            label="P0_CELL_SCOPE_RATE",
                        )
                    )
                    and _rate_probe_acceptable(normalization_rate)
                    and (
                        received_count > 0
                        or empty_valid_count > 0
                        or normalization_rate.get("status") == "EMPTY_VALID"
                    )
                    and invalid_count == 0
                    and contradictory_duplicates == 0
                    and unclassifiable_count == 0
                )
                if (
                    set(cell) != required_cell_fields
                    or cell.get("scope") != "P0_2020_2025"
                    or _sha(
                        cell.get("source_lineage_hash"),
                        label="P0_CELL_SOURCE_LINEAGE_HASH",
                    )
                    != cell.get("source_lineage_hash")
                    or receipt_lineages.get(family) != cell.get("source_lineage_hash")
                    or list(lineage_object_ids) != sorted(lineage_object_ids)
                    or len(lineage_object_ids) != len(set(lineage_object_ids))
                    or not set(lineage_object_ids).issubset(expected_object_ids)
                    or canonical_sha256(list(source_lineage)) != cell.get("source_lineage_hash")
                    or source_object_count != len(source_lineage)
                    or materialized_source_object_count > source_object_count
                    or observed_content_slots != received_count
                    or cell.get("expected_content_slots") != cell.get("expected_count")
                    or scope_rate.get("numerator") != source_scopes_verified
                    or scope_rate.get("denominator") != source_scopes_expected
                    or normalization_rate.get("numerator") != normalized_unique
                    or normalization_rate.get("denominator") != raw_eligible
                    or content_rate.get("numerator") != observed_content_slots
                    or content_rate.get("denominator") != expected_content_slots
                    or exact_duplicates != identity_exact_duplicates
                    or (
                        family in {"fixtures", "teams"}
                        and (
                            invalid_count < identity_invalid
                            or contradictory_duplicates < identity_contradictions
                        )
                    )
                    or (
                        family not in {"fixtures", "teams"}
                        and (
                            invalid_count != identity_invalid
                            or contradictory_duplicates != identity_contradictions
                        )
                    )
                    or canonical_sha256(sorted(lineage_object_ids))
                    != cell.get("source_object_set_hash")
                    or _sha(
                        cell.get("source_object_set_hash"),
                        label="P0_CELL_SOURCE_OBJECT_SET_HASH",
                    )
                    != cell.get("source_object_set_hash")
                    or cell.get("scope_identity_gate") not in {"PASS", "PARTIAL", "FAIL", "UNKNOWN"}
                    or processing_scope_gate
                    not in {"PASS", "PARTIAL", "FAIL", "UNKNOWN", "NOT_APPLICABLE"}
                    or (
                        processing_scope_gate == "NOT_APPLICABLE"
                        and (
                            processing_expected is not None
                            or processing_verified != 0
                            or processing_missing != 0
                            or processing_unexpected != 0
                            or cell.get("processing_expected_set_hash") is not None
                            or cell.get("processing_observed_set_hash") is not None
                        )
                    )
                    or (
                        processing_scope_gate != "NOT_APPLICABLE"
                        and (
                            processing_expected is None
                            or HEX64.fullmatch(str(cell.get("processing_expected_set_hash")))
                            is None
                            or HEX64.fullmatch(str(cell.get("processing_observed_set_hash")))
                            is None
                            or processing_verified + processing_missing != processing_expected
                        )
                    )
                    or (
                        processing_scope_gate == "PASS"
                        and (
                            processing_verified != processing_expected
                            or processing_missing != 0
                            or processing_unexpected != 0
                            or cell.get("processing_expected_set_hash")
                            != cell.get("processing_observed_set_hash")
                        )
                    )
                    or HEX64.fullmatch(str(cell.get("processing_source_object_set_hash"))) is None
                    or list(processing_source_object_ids) != sorted(processing_source_object_ids)
                    or len(processing_source_object_ids) != len(set(processing_source_object_ids))
                    or not set(processing_source_object_ids).issubset(lineage_object_ids)
                    or canonical_sha256(sorted(processing_source_object_ids))
                    != cell.get("processing_source_object_set_hash")
                    or cell.get("probe_gate") != ("PASS" if expected_probe_gate else "FAIL")
                    or cell.get("normalization_integrity") != rates.get("normalization_integrity")
                    or cell.get("content_presence") != rates.get("content_presence")
                    or cell.get("null_rate") is not None
                    or cell.get("null_rate_status") != "UNKNOWN_NOT_PROVEN"
                    or "coverage_rate" in cell
                    or "overall_rate" in cell
                    or _contains_r2_key(cell)
                ):
                    raise ValueError("P0_COVERAGE_CELL_CONTRACT_INVALID")
            observed_families = tuple(
                _text(item.get("family"), label="P0_SHARD_FAMILY") for item in shard_family_records
            )
            cell_by_family = {
                _text(item.get("family"), label="P0_SHARD_IDENTITY_FAMILY"): item
                for item in shard_family_records
            }
            absence_cell_families = set(cell_by_family).intersection(
                {"injuries", "suspensions"}
            )
            if absence_cell_families not in (
                set(),
                {"injuries", "suspensions"},
            ):
                raise ValueError("P0_SHARD_ABSENCE_CELL_SET_INCOMPLETE")
            absence_source_object_ids = sorted(
                {
                    _sha(
                        _mapping(
                            lineage_item,
                            label="P0_SHARD_ABSENCE_SOURCE_LINEAGE_ITEM",
                        ).get("object_id"),
                        label="P0_SHARD_ABSENCE_SOURCE_OBJECT_ID",
                    )
                    for absence_family in ("injuries", "suspensions")
                    if absence_family in absence_cell_families
                    for lineage_item in _sequence(
                        _mapping(
                            cell_by_family.get(absence_family),
                            label=f"P0_SHARD_{absence_family.upper()}_SOURCE_CELL",
                        ).get("source_lineage"),
                        label=f"P0_SHARD_{absence_family.upper()}_SOURCE_LINEAGE",
                    )
                }
            )
            if absence_residual_profile.get(
                "source_absence_object_set_hash"
            ) != canonical_sha256(absence_source_object_ids):
                raise ValueError("P0_SHARD_ABSENCE_PROFILE_SOURCE_SET_MISMATCH")
            if any(
                _mapping(
                    cell_by_family.get(family),
                    label=f"P0_SHARD_{family.upper()}_SOURCE_BINDING_CELL",
                ).get("source_object_set_hash")
                != absence_residual_profile.get("source_absence_object_set_hash")
                for family in absence_cell_families
            ):
                raise ValueError("P0_SHARD_ABSENCE_CELL_SOURCE_SET_MISMATCH")
            if not absence_cell_families and (
                absence_raw != 0
                or absence_injuries != 0
                or absence_suspensions != 0
                or absence_unclassifiable != 0
                or absence_residual_profile.get("unclassifiable_record_count") != 0
                or absence_residual_profile.get("semantic_signatures") != []
            ):
                raise ValueError("P0_SHARD_NONABSENCE_PARTITION_NOT_EMPTY")
            for family, category_distinct in (
                ("injuries", absence_injuries),
                ("suspensions", absence_suspensions),
            ):
                if family not in absence_cell_families:
                    continue
                absence_cell = _mapping(
                    cell_by_family.get(family),
                    label=f"P0_SHARD_{family.upper()}_CELL",
                )
                absence_cell_counts = _mapping(
                    absence_cell.get("counts"),
                    label=f"P0_SHARD_{family.upper()}_COUNTS",
                )
                absence_cell_normalized = _integer(
                    absence_cell_counts.get("normalized_unique"),
                    label=f"P0_SHARD_{family.upper()}_NORMALIZED_UNIQUE",
                )
                absence_cell_raw_value = absence_cell.get("raw_eligible_unique_entities")
                absence_cell_raw = (
                    None
                    if absence_cell_raw_value is None
                    else _integer(
                        absence_cell_raw_value,
                        label=f"P0_SHARD_{family.upper()}_RAW_ELIGIBLE",
                    )
                )
                absence_cell_expected_value = absence_cell.get("expected_count")
                absence_cell_expected = (
                    None
                    if absence_cell_expected_value is None
                    else _integer(
                        absence_cell_expected_value,
                        label=f"P0_SHARD_{family.upper()}_EXPECTED_COUNT",
                    )
                )
                if (
                    _integer(
                        absence_cell.get("unclassifiable_count"),
                        label=f"P0_SHARD_{family.upper()}_UNCLASSIFIABLE_COUNT",
                    )
                    != absence_unclassifiable
                    or (
                        absence_invariant == "PASS"
                        and (
                            absence_cell_normalized != category_distinct
                            or _integer(
                                absence_cell.get("received_count"),
                                label=f"P0_SHARD_{family.upper()}_RECEIVED_COUNT",
                            )
                            != category_distinct
                            or absence_cell_raw not in {None, category_distinct}
                            or absence_cell_expected not in {None, category_distinct}
                        )
                    )
                ):
                    raise ValueError("P0_SHARD_ABSENCE_CELL_BINDING_INVALID")
            expected_family_identity_gate = (
                "PASS"
                if absence_invariant == "PASS"
                and all(
                    _integer(
                        item.get("invalid_count"),
                        label="P0_SHARD_IDENTITY_INVALID_COUNT",
                    )
                    == 0
                    and _integer(
                        item.get("contradictory_duplicates"),
                        label="P0_SHARD_IDENTITY_CONTRADICTIONS",
                    )
                    == 0
                    for item in shard_family_records
                )
                else "FAIL"
            )
            sample_proofs = _sample_fixture_proofs(
                selection,
                competition=competition,
                season=season,
            )
            if sample_proofs is None:
                expected_sample_identity_gate = expected_family_identity_gate
            else:
                fixture_cell = _mapping(
                    cell_by_family.get("fixtures"),
                    label="P0_SHARD_SAMPLE_FIXTURE_CELL",
                )
                team_cell = _mapping(
                    cell_by_family.get("teams"),
                    label="P0_SHARD_SAMPLE_TEAM_CELL",
                )
                fixture_counts = _mapping(
                    fixture_cell.get("counts"),
                    label="P0_SHARD_SAMPLE_FIXTURE_COUNTS",
                )
                team_counts = _mapping(
                    team_cell.get("counts"),
                    label="P0_SHARD_SAMPLE_TEAM_COUNTS",
                )
                expected_sample_identity_gate = (
                    "PASS"
                    if fixture_proof_gate == "PASS"
                    and expected_family_identity_gate == "PASS"
                    and fixture_counts.get("normalized_unique") == len(sample_proofs)
                    and fixture_counts.get("invalid_identity") == 0
                    and fixture_counts.get("contradictory_duplicates") == 0
                    and team_counts.get("normalized_unique") == len(sample_proofs) * 2
                    and team_counts.get("invalid_identity") == 0
                    and team_counts.get("contradictory_duplicates") == 0
                    else "FAIL"
                )
            expected_sample_processing_gate = (
                "PASS"
                if all(
                    item.get("processing_scope_gate") in {"PASS", "NOT_APPLICABLE"}
                    for item in shard_family_records
                )
                else "FAIL"
            )
            if authority.stage not in {"E1A", "E1B", "E2"}:
                expected_sample_processing_gate = "NOT_APPLICABLE"
            if (
                observed_families != expected_families
                or family_identity_gate != expected_family_identity_gate
                or sample_identity_gate != expected_sample_identity_gate
                or any(
                    item.get("competition") != competition
                    or item.get("season") != season
                    or item.get("closure_state")
                    not in {
                        "OPEN_NOT_EVALUATED",
                        "OPEN_MISSING_SCOPE",
                        "OPEN_CLASSIFICATION_AMBIGUOUS",
                        "OPEN_CONFLICTING_DUPLICATE",
                        "DENOMINATOR_CLOSED_FULL_SCOPE",
                    }
                    for item in shard_family_records
                )
                or receipt.get("sample_processing_gate") != expected_sample_processing_gate
            ):
                raise ValueError("P0_SHARD_CELL_SET_INVALID")
            _weighted_rates(shard_family_records)
            (
                observed_logical_gets,
                observed_stored_bytes,
                observed_logical_bytes,
            ) = _partition_cost_observation(
                cost,
                expected_pairs=len(expected_object_ids),
            )
            resources = _mapping(cost.get("resources"), label="P0_SHARD_COST_RESOURCES")
            if set(resources) != {
                "measurement_elapsed_seconds",
                "process_peak_rss_bytes",
                "process_peak_rss_source",
                "signed_memory_limit_bytes",
                "memory_budget_gate",
            }:
                raise ValueError("P0_SHARD_RESOURCE_FIELDS_INVALID")
            elapsed_seconds = _number(
                resources.get("measurement_elapsed_seconds"),
                label="P0_SHARD_ELAPSED_SECONDS",
            )
            if elapsed_seconds < 0:
                raise ValueError("P0_SHARD_ELAPSED_SECONDS_INVALID")
            peak_rss_value = resources.get("process_peak_rss_bytes")
            if isinstance(peak_rss_value, int) and not isinstance(peak_rss_value, bool):
                peak_rss_bytes: int | None = _integer(
                    peak_rss_value,
                    label="P0_SHARD_PEAK_RSS_BYTES",
                    minimum=1,
                )
                expected_rss_source = "LINUX_PROC_STATUS_VMHWM"
            elif peak_rss_value == "UNKNOWN_NOT_OBSERVED":
                peak_rss_bytes = None
                expected_rss_source = "UNKNOWN_NOT_OBSERVED"
            else:
                raise ValueError("P0_SHARD_PEAK_RSS_INVALID")
            if (
                observed_logical_gets != 1 + len(expected_object_ids) * 2
                or observed_stored_bytes
                > authority.limits.bootstrap_compressed_bytes
                + authority.limits.stored_bytes_per_job
                or observed_logical_bytes
                > authority.limits.bootstrap_decompressed_bytes
                + authority.limits.stored_bytes_per_job
                + authority.limits.logical_bytes_per_job
                or cost.get("quota") != "UNKNOWN_NOT_OBSERVED"
                or cost.get("monetary_cost") != "UNKNOWN_NOT_OBSERVED"
                or resources.get("process_peak_rss_source") != expected_rss_source
                or resources.get("signed_memory_limit_bytes") is not None
                or resources.get("memory_budget_gate") != "UNKNOWN_NO_SIGNED_LIMIT"
            ):
                raise ValueError("P0_SHARD_COST_BUDGET_INVALID")
            observed_ids.append(partition_id)
            family_records.extend(shard_family_records)
            absence_residual_profiles.append(absence_residual_profile)
            observed_cell_keys.extend((competition, season, family) for family in observed_families)
            cost_reports.append(cost)
            checkpoint_hashes[partition_id] = checkpoint_hash
            if scientific_status != "MEASURED":
                failed_scientific_partition_ids.append(partition_id)
            observed_attempt_slots.append(
                _integer(
                    cost.get("attempt_slot"),
                    label="P0_SHARD_ATTEMPT_SLOT",
                    minimum=1,
                )
            )
            resource_reports.append((partition_id, elapsed_seconds, peak_rss_bytes))
        except (ValueError, TypeError):
            invalid_shards += 1
    observed_set = set(observed_ids)
    missing_ids = sorted(expected_ids - observed_set)
    extra_ids = sorted(observed_set - expected_ids)
    duplicate_ids = sorted(
        partition_id for partition_id in observed_set if observed_ids.count(partition_id) > 1
    )
    observed_cell_set = set(observed_cell_keys)
    missing_cell_keys = sorted(expected_cell_keys - observed_cell_set)
    extra_cell_keys = sorted(observed_cell_set - expected_cell_keys)
    duplicate_cell_keys = sorted(
        cell_key for cell_key in observed_cell_set if observed_cell_keys.count(cell_key) > 1
    )
    weighted_rates = _weighted_rates(family_records)
    invalid_rate_cells = sum(
        _integer(
            _mapping(value, label="P0_AGGREGATE_WEIGHTED_RATE").get("invalid_cells"),
            label="P0_AGGREGATE_INVALID_RATE_CELLS",
        )
        for value in weighted_rates.values()
    )
    observed_measure_logical_gets = sum(
        _integer(
            _mapping(report.get("reads"), label="P0_COST_READS").get("logical_gets"),
            label="P0_COST_LOGICAL_GETS",
        )
        for report in cost_reports
    )
    attempt_slot_exact = len(observed_attempt_slots) == len(expected_ids) and all(
        observed == attempt_slot for observed in observed_attempt_slots
    )
    current_measure_planned_gets = sum(
        1
        + _integer(
            partition.get("planned_evidence_gets"),
            label="P0_AGGREGATE_PARTITION_PLANNED_GETS",
        )
        for partition in expected_partitions.values()
    )
    if attempt_slot == 2:
        prior_attempt = _current_stage_receipt(authority, selection=selection)
        (
            baseline_charged_gets,
            baseline_observed_gets,
            baseline_observed_lower_bound,
            _prior_accounting_basis,
        ) = _validated_mission_accounting(
            prior_attempt,
            authority=authority,
            label="P0_RETRY_BASELINE_ACCOUNTING",
        )
        planned_mission_logical_gets = baseline_charged_gets + current_measure_planned_gets
        accounting_parent_receipt_sha256: str | None = _sha(
            prior_attempt.get("stage_receipt_sha256"),
            label="P0_RETRY_ACCOUNTING_PARENT",
        )
        mission_accounting_ancestors = [
            *(
                _sha(item, label="P0_RETRY_ACCOUNTING_ANCESTOR")
                for item in _sequence(
                    prior_attempt.get("mission_accounting_ancestor_receipt_sha256s"),
                    label="P0_RETRY_ACCOUNTING_ANCESTORS",
                )
            ),
            accounting_parent_receipt_sha256,
        ]
    else:
        (
            mission_baseline_charged_gets,
            mission_baseline_observed_gets,
            mission_baseline_observed_lower_bound,
            _prior_accounting_basis,
        ) = _validated_selection_mission_baseline(
            selection,
            authority=authority,
        )
        mission_baseline = _mapping(
            selection.get("mission_accounting_baseline"),
            label="P0_AGGREGATE_MISSION_BASELINE",
        )
        failed_freeze_charge = _integer(
            selection.get("failed_freeze_conservative_charge"),
            label="P0_AGGREGATE_FAILED_FREEZE_CHARGE",
        )
        freeze_observed_gets = _integer(
            selection.get("freeze_observed_logical_gets"),
            label="P0_AGGREGATE_FREEZE_GETS",
            minimum=1,
        )
        baseline_charged_gets = (
            mission_baseline_charged_gets + failed_freeze_charge + freeze_observed_gets
        )
        baseline_observed_lower_bound = mission_baseline_observed_lower_bound + freeze_observed_gets
        baseline_observed_gets = (
            mission_baseline_observed_gets + freeze_observed_gets
            if mission_baseline_observed_gets is not None and failed_freeze_charge == 0
            else None
        )
        parent_value = mission_baseline.get("source_stage_receipt_sha256")
        accounting_parent_receipt_sha256 = (
            None if parent_value is None else _sha(parent_value, label="P0_ACCOUNTING_PARENT")
        )
        mission_accounting_ancestors = [
            *(
                _sha(item, label="P0_ACCOUNTING_ANCESTOR")
                for item in _sequence(
                    mission_baseline.get("source_receipt_ancestor_sha256s"),
                    label="P0_ACCOUNTING_ANCESTORS",
                )
            ),
            *(
                [accounting_parent_receipt_sha256]
                if accounting_parent_receipt_sha256 is not None
                else []
            ),
        ]
        planned_mission_logical_gets = _integer(
            selection.get("planned_mission_logical_gets"),
            label="P0_AGGREGATE_PLANNED_MISSION_GETS",
        )
    read_accounting_complete = (
        not missing_ids
        and not extra_ids
        and not duplicate_ids
        and invalid_shards == 0
        and observed_set == expected_ids
        and len(cost_reports) == len(expected_ids)
        and attempt_slot_exact
    )
    checkpoint_pass = (
        set(checkpoint_hashes) == expected_ids
        and len(checkpoint_hashes) == len(expected_ids)
        and attempt_slot_exact
    )
    cumulative_mission_logical_gets_charged = baseline_charged_gets + current_measure_planned_gets
    if cumulative_mission_logical_gets_charged != planned_mission_logical_gets:
        raise ValueError("P0_AGGREGATE_MISSION_CHARGE_PLAN_MISMATCH")
    observed_lower_bound_gets = baseline_observed_lower_bound + observed_measure_logical_gets
    cumulative_mission_logical_gets: int | str = (
        baseline_observed_gets + observed_measure_logical_gets
        if baseline_observed_gets is not None and read_accounting_complete
        else "UNKNOWN_NOT_OBSERVED"
    )
    mission_budget_gate = (
        "PASS"
        if cumulative_mission_logical_gets_charged <= authority.limits.mission_gets
        else "FAIL"
    )
    mission_logical_gets_remaining = (
        authority.limits.mission_gets - cumulative_mission_logical_gets_charged
    )
    mission_budget_exact = (
        isinstance(cumulative_mission_logical_gets, int)
        and cumulative_mission_logical_gets == cumulative_mission_logical_gets_charged
        and observed_lower_bound_gets == cumulative_mission_logical_gets_charged
        and mission_budget_gate == "PASS"
    )
    mission_budget_accounting_basis = (
        MISSION_ACCOUNTING_EXACT if mission_budget_exact else MISSION_ACCOUNTING_CONSERVATIVE
    )
    current_measure_plan_exact = (
        read_accounting_complete and observed_measure_logical_gets == current_measure_planned_gets
    )
    measurement_integrity_pass = (
        not missing_ids
        and not extra_ids
        and not duplicate_ids
        and not missing_cell_keys
        and not extra_cell_keys
        and not duplicate_cell_keys
        and invalid_shards == 0
        and invalid_rate_cells == 0
        and current_measure_plan_exact
        and mission_budget_gate == "PASS"
        and checkpoint_pass
        and observed_set == expected_ids
        and observed_cell_set == expected_cell_keys
    )
    missing_source_cell_keys = sorted(
        (
            _text(record.get("competition"), label="P0_SOURCE_CELL_COMPETITION"),
            _integer(
                record.get("season"),
                label="P0_SOURCE_CELL_SEASON",
                minimum=1888,
            ),
            _text(record.get("family"), label="P0_SOURCE_CELL_FAMILY"),
        )
        for record in family_records
        if _integer(
            record.get("materialized_source_object_count"),
            label="P0_MATERIALIZED_SOURCE_CELL_OBJECT_COUNT",
        )
        == 0
    )
    failed_probe_cell_keys = sorted(
        (
            _text(record.get("competition"), label="P0_PROBE_CELL_COMPETITION"),
            _integer(
                record.get("season"),
                label="P0_PROBE_CELL_SEASON",
                minimum=1888,
            ),
            _text(record.get("family"), label="P0_PROBE_CELL_FAMILY"),
        )
        for record in family_records
        if record.get("probe_gate") != "PASS"
    )
    unknown_null_cell_keys = sorted(
        (
            _text(record.get("competition"), label="P0_NULL_CELL_COMPETITION"),
            _integer(
                record.get("season"),
                label="P0_NULL_CELL_SEASON",
                minimum=1888,
            ),
            _text(record.get("family"), label="P0_NULL_CELL_FAMILY"),
        )
        for record in family_records
        if record.get("null_rate_status") != "KNOWN"
    )
    stage_time_limit_seconds = _stage_time_limit_seconds(authority)
    overtime_partition_ids = sorted(
        partition_id
        for partition_id, elapsed_seconds, _peak_rss in resource_reports
        if elapsed_seconds > stage_time_limit_seconds
    )
    time_budget_pass = (
        read_accounting_complete
        and len(resource_reports) == len(expected_ids)
        and not overtime_partition_ids
    )
    peak_rss_values = [peak_rss for _partition_id, _elapsed_seconds, peak_rss in resource_reports]
    memory_observation_pass = (
        read_accounting_complete
        and len(peak_rss_values) == len(expected_ids)
        and all(value is not None for value in peak_rss_values)
    )
    # No immutable authority file defines a byte-valued process-memory ceiling.
    # Report the observation, but E2 cannot claim its explicit memory gate.
    memory_budget_gate = "UNKNOWN_NO_SIGNED_LIMIT"
    e2_measurement_objectives_pass = authority.stage != "E2" or (
        memory_budget_gate == "PASS" and not unknown_null_cell_keys
    )
    resource_budget_pass = time_budget_pass and e2_measurement_objectives_pass
    scale_gate_pass = (
        measurement_integrity_pass
        and checkpoint_pass
        and not failed_scientific_partition_ids
        and not failed_probe_cell_keys
        and resource_budget_pass
    )
    scientific_pass = scale_gate_pass
    closed_cells = sum(
        record.get("closure_state") == "DENOMINATOR_CLOSED_FULL_SCOPE" for record in family_records
    )
    scope_cells = {
        "E1A": 0,
        "E1B": 0,
        "E2": 0,
        "E3A": 16,
        "E3B": 80,
        "E4": 480,
    }[authority.stage]
    if closed_cells > scope_cells:
        raise ValueError("P0_AGGREGATE_CLOSED_CELL_CEILING_EXCEEDED")
    if authority.stage in {"E1A", "E1B", "E2"} and closed_cells != 0:
        raise ValueError("P0_SAMPLE_STAGE_CLOSED_REAL_CELL")
    if not read_accounting_complete:
        domain_decision = "FAIL_AND_STOP"
    elif not measurement_integrity_pass:
        domain_decision = _scale_failure_decision(
            selection=selection,
            attempt_slot=attempt_slot,
            missing_source_cell_keys=missing_source_cell_keys,
            scientific_failure=False,
        )
    elif not scale_gate_pass:
        domain_decision = _scale_failure_decision(
            selection=selection,
            attempt_slot=attempt_slot,
            missing_source_cell_keys=missing_source_cell_keys,
            scientific_failure=True,
        )
    elif authority.stage == "E4":
        domain_decision = "PASS_AND_HOLD"
    else:
        domain_decision = "PASS_AND_SCALE"
    council_decision = {
        "E1A": "PASS_AND_HOLD",
        "E1B": "PASS_AND_SCALE",
        "E2": "PASS_AND_SCALE",
        "E3A": "PASS_AND_SCALE",
        "E3B": "PASS_AND_SCALE",
        "E4": "PASS_AND_HOLD",
    }[authority.stage]
    if not read_accounting_complete:
        council_decision = "FAIL_AND_STOP"
    elif not measurement_integrity_pass:
        council_decision = _scale_failure_decision(
            selection=selection,
            attempt_slot=attempt_slot,
            missing_source_cell_keys=missing_source_cell_keys,
            scientific_failure=False,
        )
    elif not scale_gate_pass:
        council_decision = _scale_failure_decision(
            selection=selection,
            attempt_slot=attempt_slot,
            missing_source_cell_keys=missing_source_cell_keys,
            scientific_failure=True,
        )
    lineage_objects: dict[str, Mapping[str, object]] = {}
    lineage_sets: dict[str, tuple[str, ...]] = {}
    lineage_cells: list[dict[str, object]] = []
    for record in family_records:
        cell_lineage = tuple(
            _mapping(item, label="P0_STAGE_LINEAGE_ITEM")
            for item in _sequence(
                record.get("source_lineage"),
                label="P0_STAGE_CELL_LINEAGE",
            )
        )
        lineage_hash = _sha(
            record.get("source_lineage_hash"),
            label="P0_STAGE_CELL_LINEAGE_HASH",
        )
        object_ids = tuple(
            _sha(item.get("object_id"), label="P0_STAGE_LINEAGE_OBJECT_ID") for item in cell_lineage
        )
        prior_set = lineage_sets.setdefault(lineage_hash, object_ids)
        if prior_set != object_ids or canonical_sha256(list(cell_lineage)) != lineage_hash:
            raise ValueError("P0_STAGE_LINEAGE_SET_CONFLICT")
        for item, object_id in zip(cell_lineage, object_ids, strict=True):
            normalized_item = {
                "object_id": object_id,
                "receipt_hash": _sha(
                    item.get("receipt_hash"),
                    label="P0_STAGE_LINEAGE_RECEIPT_HASH",
                ),
                "payload_sha256": _sha(
                    item.get("payload_sha256"),
                    label="P0_STAGE_LINEAGE_PAYLOAD_HASH",
                ),
            }
            prior_item = lineage_objects.setdefault(object_id, normalized_item)
            if prior_item != normalized_item:
                raise ValueError("P0_STAGE_LINEAGE_OBJECT_CONFLICT")
        lineage_cells.append(
            {
                "competition": _text(
                    record.get("competition"),
                    label="P0_STAGE_LINEAGE_COMPETITION",
                ),
                "season": _integer(
                    record.get("season"),
                    label="P0_STAGE_LINEAGE_SEASON",
                    minimum=1888,
                ),
                "family": _text(
                    record.get("family"),
                    label="P0_STAGE_LINEAGE_FAMILY",
                ),
                "source_lineage_hash": lineage_hash,
            }
        )
    lineage_manifest = _signed(
        {
            "schema_version": "p0-coverage-stage-lineage-v1",
            "stage": authority.stage,
            "selection_sha256": selection_sha,
            "inventory_sha256": selection.get("inventory_sha256"),
            "objects": sorted(lineage_objects.values(), key=lambda item: str(item["object_id"])),
            "lineage_sets": [
                {
                    "source_lineage_hash": lineage_hash,
                    "object_ids": list(object_ids),
                }
                for lineage_hash, object_ids in sorted(lineage_sets.items())
            ],
            "cells": sorted(
                lineage_cells,
                key=lambda item: (
                    str(item["competition"]),
                    _integer(item["season"], label="P0_STAGE_LINEAGE_SORT_SEASON"),
                    str(item["family"]),
                ),
            ),
            "effects": dict(ZERO_EFFECTS),
        },
        field="lineage_manifest_sha256",
    )
    stage_unsigned: dict[str, object] = {
        "schema_version": STAGE_SCHEMA_VERSION,
        "mission_id": authority.mission["mission_id"],
        "mission_sha256": authority.mission_sha256,
        "stage": authority.stage,
        "council_stage": authority.council_stage,
        "architecture_fingerprint": evidence_architecture_fingerprint(authority),
        "architecture_ordinal": selection.get("architecture_ordinal"),
        "mission_architecture_registry": selection.get("mission_architecture_registry"),
        "selection_sha256": selection_sha,
        "mission_accounting_baseline": selection.get("mission_accounting_baseline"),
        "accounting_parent_receipt_sha256": accounting_parent_receipt_sha256,
        "mission_accounting_ancestor_receipt_sha256s": mission_accounting_ancestors,
        "scientific_gate": "PASS" if scientific_pass else "FAIL",
        "measurement_integrity_gate": ("PASS" if measurement_integrity_pass else "FAIL"),
        "scale_gate": "PASS" if scale_gate_pass else "FAIL",
        "domain_decision": domain_decision,
        "council_decision": council_decision,
        "partition_count_expected": len(expected_ids),
        "partition_count_verified": len(observed_set & expected_ids),
        "missing_partition_ids": missing_ids,
        "extra_partition_ids": extra_ids,
        "duplicate_partition_ids": duplicate_ids,
        "cell_count_expected": len(expected_cell_keys),
        "cell_count_verified": len(observed_cell_set & expected_cell_keys),
        "missing_cell_keys": [list(item) for item in missing_cell_keys],
        "extra_cell_keys": [list(item) for item in extra_cell_keys],
        "duplicate_cell_keys": [list(item) for item in duplicate_cell_keys],
        "invalid_shards": invalid_shards,
        "invalid_rate_cells": invalid_rate_cells,
        "attempt_slot": attempt_slot,
        "checkpoint_gate": "PASS" if checkpoint_pass else "FAIL",
        "checkpoint_hashes": {
            partition_id: checkpoint_hashes[partition_id]
            for partition_id in sorted(checkpoint_hashes)
        },
        "read_accounting_gate": "PASS" if read_accounting_complete else "FAIL",
        "resource_budget_gate": "PASS" if resource_budget_pass else "FAIL",
        "time_budget_gate": "PASS" if time_budget_pass else "FAIL",
        "time_limit_seconds_per_partition": stage_time_limit_seconds,
        "overtime_partition_ids": overtime_partition_ids,
        "memory_observation_gate": "PASS" if memory_observation_pass else "FAIL",
        "memory_budget_gate": memory_budget_gate,
        "null_measurement_gate": ("PASS" if not unknown_null_cell_keys else "UNKNOWN_NOT_PROVEN"),
        "unknown_null_cell_keys": [list(item) for item in unknown_null_cell_keys],
        "maximum_process_peak_rss_bytes_observed": (
            max(value for value in peak_rss_values if value is not None)
            if any(value is not None for value in peak_rss_values)
            else "UNKNOWN_NOT_OBSERVED"
        ),
        "missing_source_cell_keys": [list(item) for item in missing_source_cell_keys],
        "failed_probe_cell_keys": [list(item) for item in failed_probe_cell_keys],
        "absence_residual_profiles": sorted(
            absence_residual_profiles,
            key=lambda item: str(item.get("partition_id")),
        ),
        "absence_residual_profile_set_sha256": canonical_sha256(
            sorted(
                _sha(
                    item.get("profile_sha256"),
                    label="P0_STAGE_ABSENCE_PROFILE_SHA",
                )
                for item in absence_residual_profiles
            )
        ),
        "planned_mission_logical_gets": planned_mission_logical_gets,
        "cumulative_mission_logical_gets_observed_lower_bound": observed_lower_bound_gets,
        "cumulative_mission_logical_gets_observed": cumulative_mission_logical_gets,
        "cumulative_mission_logical_gets_charged": (cumulative_mission_logical_gets_charged),
        "mission_logical_gets_remaining": mission_logical_gets_remaining,
        "mission_budget_gate": mission_budget_gate,
        "mission_budget_accounting_basis": mission_budget_accounting_basis,
        "mission_budget_exact": mission_budget_exact,
        "scope_cells": scope_cells,
        "closed_cells": closed_cells,
        "open_cells": scope_cells - closed_cells,
        "global_p0_cells": 480,
        "global_p0_closed_cells_after_stage": (closed_cells if authority.stage == "E4" else None),
        "source_lineage_manifest": lineage_manifest,
        "effects": dict(ZERO_EFFECTS),
    }
    stage_receipt = _signed(stage_unsigned, field="stage_receipt_sha256")
    sanitized_family_records = [
        {
            key: value
            for key, value in record.items()
            if key not in {"source_lineage", "processing_source_object_ids"}
        }
        for record in family_records
    ]
    feed_unsigned: dict[str, object] = {
        "schema_version": "p0-coverage-feed-v2",
        "stage": authority.stage,
        "selection_sha256": selection_sha,
        "weighted_rates": weighted_rates,
        "aggregation_policy": "SUM_NUMERATORS_AND_DENOMINATORS_NEVER_MEAN_OF_RATES",
        "cells": sorted(
            sanitized_family_records,
            key=lambda item: (
                str(item.get("competition")),
                _integer(
                    item.get("season"),
                    label="P0_FEED_SEASON",
                    minimum=1888,
                ),
                str(item.get("family")),
            ),
        ),
        "dashboard_sanitized": True,
        "forbidden_detail_fields_excluded": [
            "fixture_ids",
            "source_endpoints",
            "payload_hashes",
            "receipt_hashes",
            "processing_source_object_ids",
            "r2_keys",
        ],
    }
    coverage_feed = _signed(feed_unsigned, field="feed_sha256")
    gate_report = _signed(
        {
            "schema_version": "p0-coverage-stage-gate-v1",
            "stage": authority.stage,
            "architecture_fingerprint": evidence_architecture_fingerprint(authority),
            "architecture_ordinal": selection.get("architecture_ordinal"),
            "attempt_slot": attempt_slot,
            "selection_sha256": selection_sha,
            "scientific_gate": stage_receipt["scientific_gate"],
            "measurement_integrity_gate": stage_receipt["measurement_integrity_gate"],
            "read_accounting_gate": stage_receipt["read_accounting_gate"],
            "checkpoint_gate": stage_receipt["checkpoint_gate"],
            "checkpoint_hashes": stage_receipt["checkpoint_hashes"],
            "resource_budget_gate": stage_receipt["resource_budget_gate"],
            "time_budget_gate": stage_receipt["time_budget_gate"],
            "memory_observation_gate": stage_receipt["memory_observation_gate"],
            "memory_budget_gate": stage_receipt["memory_budget_gate"],
            "null_measurement_gate": stage_receipt["null_measurement_gate"],
            "unknown_null_cell_keys": stage_receipt["unknown_null_cell_keys"],
            "overtime_partition_ids": overtime_partition_ids,
            "scale_gate": stage_receipt["scale_gate"],
            "domain_decision": domain_decision,
            "council_decision": council_decision,
            "closed_cells": closed_cells,
            "scope_cells": scope_cells,
            "missing_source_cell_keys": stage_receipt["missing_source_cell_keys"],
            "failed_probe_cell_keys": stage_receipt["failed_probe_cell_keys"],
            "absence_residual_profile_set_sha256": stage_receipt[
                "absence_residual_profile_set_sha256"
            ],
            "mission_budget_exact": mission_budget_exact,
            "mission_budget_gate": mission_budget_gate,
            "mission_budget_accounting_basis": mission_budget_accounting_basis,
            "cumulative_mission_logical_gets_observed": cumulative_mission_logical_gets,
            "cumulative_mission_logical_gets_charged": (cumulative_mission_logical_gets_charged),
            "source_lineage_manifest_sha256": lineage_manifest["lineage_manifest_sha256"],
            "effects": dict(ZERO_EFFECTS),
        },
        field="gate_sha256",
    )
    logical_gets = 0
    stored_bytes = 0
    logical_bytes = 0
    for report in cost_reports:
        reads = _mapping(report.get("reads"), label="P0_COST_READS")
        logical_gets += _integer(reads.get("logical_gets"), label="P0_COST_LOGICAL_GETS")
        stored_bytes += _integer(reads.get("stored_bytes"), label="P0_COST_STORED_BYTES")
        logical_bytes += _integer(reads.get("logical_bytes"), label="P0_COST_LOGICAL_BYTES")
    cost_report = _signed(
        {
            "schema_version": "p0-coverage-stage-cost-v1",
            "stage": authority.stage,
            "architecture_fingerprint": evidence_architecture_fingerprint(authority),
            "architecture_ordinal": selection.get("architecture_ordinal"),
            "attempt_slot": attempt_slot,
            "selection_sha256": selection_sha,
            "reads": {
                "logical_gets": (
                    logical_gets if read_accounting_complete else "UNKNOWN_NOT_OBSERVED"
                ),
                "logical_gets_observed_lower_bound": logical_gets,
                "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
                "stored_bytes": (
                    stored_bytes if read_accounting_complete else "UNKNOWN_NOT_OBSERVED"
                ),
                "stored_bytes_observed_lower_bound": stored_bytes,
                "logical_bytes": (
                    logical_bytes if read_accounting_complete else "UNKNOWN_NOT_OBSERVED"
                ),
                "logical_bytes_observed_lower_bound": logical_bytes,
            },
            "resources": {
                "partition_time_limit_seconds": stage_time_limit_seconds,
                "measurement_elapsed_seconds_total": (
                    round(
                        sum(elapsed for _partition, elapsed, _peak in resource_reports),
                        6,
                    )
                    if read_accounting_complete
                    else "UNKNOWN_NOT_OBSERVED"
                ),
                "measurement_elapsed_seconds_observed_lower_bound": round(
                    sum(elapsed for _partition, elapsed, _peak in resource_reports),
                    6,
                ),
                "measurement_elapsed_seconds_maximum": (
                    max(elapsed for _partition, elapsed, _peak in resource_reports)
                    if resource_reports
                    else "UNKNOWN_NOT_OBSERVED"
                ),
                "overtime_partition_ids": overtime_partition_ids,
                "time_budget_gate": "PASS" if time_budget_pass else "FAIL",
                "process_peak_rss_bytes_maximum_observed": (
                    max(value for value in peak_rss_values if value is not None)
                    if any(value is not None for value in peak_rss_values)
                    else "UNKNOWN_NOT_OBSERVED"
                ),
                "memory_observation_gate": ("PASS" if memory_observation_pass else "FAIL"),
                "signed_memory_limit_bytes": None,
                "memory_budget_gate": memory_budget_gate,
            },
            "mission_accounting_baseline": selection.get("mission_accounting_baseline"),
            "accounting_parent_receipt_sha256": accounting_parent_receipt_sha256,
            "failed_freeze_conservative_charge": selection.get("failed_freeze_conservative_charge"),
            "freeze_observed_logical_gets": selection.get("freeze_observed_logical_gets"),
            "cumulative_mission_logical_gets_observed": cumulative_mission_logical_gets,
            "cumulative_mission_logical_gets_observed_lower_bound": observed_lower_bound_gets,
            "cumulative_mission_logical_gets_charged": (cumulative_mission_logical_gets_charged),
            "mission_logical_gets_limit": authority.limits.mission_gets,
            "mission_logical_gets_remaining": mission_logical_gets_remaining,
            "mission_budget_gate": mission_budget_gate,
            "mission_budget_accounting_basis": mission_budget_accounting_basis,
            "read_accounting_gate": "PASS" if read_accounting_complete else "FAIL",
            "quota": "UNKNOWN_NOT_OBSERVED",
            "monetary_cost": "UNKNOWN_NOT_OBSERVED",
            "effects": dict(ZERO_EFFECTS),
        },
        field="cost_sha256",
    )
    return stage_receipt, coverage_feed, gate_report, cost_report


__all__ = [
    "ALGORITHM_VERSION",
    "ABSENCE_CLASSIFICATION_FRAMEWORK_SHA256",
    "ABSENCE_CLASSIFICATION_RULE_VERSION",
    "ABSENCE_NORMALIZATION_VERSION",
    "ABSENCE_PROFILE_SCHEMA_VERSION",
    "ABSENCE_SUPPLEMENT_SCHEMA_VERSION",
    "CHECKPOINT_SCHEMA_VERSION",
    "CoverageAuthority",
    "FAMILY_COUNTS_SCHEMA_VERSION",
    "PinnedInventoryReader",
    "ReadTelemetry",
    "VerifiedEvidencePair",
    "VerifiedInventory",
    "ZERO_EFFECTS",
    "aggregate_stage",
    "build_partition_checkpoint",
    "build_partition_plan",
    "deep_validate_inventory",
    "evidence_architecture_fingerprint",
    "freeze_selection",
    "load_authority",
    "measure_partition",
    "validate_predecessor",
    "validate_selection",
    "validate_stage_attempt",
]
