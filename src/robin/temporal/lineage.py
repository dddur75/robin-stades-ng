"""Fail-closed point-in-time contracts shared by decision paths.

``event_at`` and business timestamps never prove availability.  Only an
immutable receipt may establish ``robin_first_observed_at`` and therefore an
``available_at`` usable by a feature or decision.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TypeAlias, cast

TEMPORAL_CONTRACT_VERSION = "robin-point-in-time-lineage-v1"
ASOF_RULE_VERSION = "available_at_lte_cutoff_payload_conflict_fail_closed_v1"
SHA256_LENGTH = 64

FrozenJson: TypeAlias = (
    None | bool | int | float | str | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]
)


class TemporalProofLevel(StrEnum):
    RECEIPT_ATTESTED = "RECEIPT_ATTESTED"
    SOURCE_AND_RECEIPT_ATTESTED = "SOURCE_AND_RECEIPT_ATTESTED"
    PROSPECTIVE_CAPTURED = "PROSPECTIVE_CAPTURED"
    RECONSTRUCTED_NOT_PROVEN = "RECONSTRUCTED_NOT_PROVEN"
    UNKNOWN = "UNKNOWN"
    INVALID_AFTER_CUTOFF = "INVALID_AFTER_CUTOFF"


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _require_sha256(value: object, *, field: str) -> str:
    if not _is_sha256(value):
        raise ValueError(f"{field.upper()}_SHA256_INVALID")
    return cast(str, value)


def parse_utc(value: datetime | str, *, field: str) -> datetime:
    candidate = value
    if isinstance(candidate, str):
        try:
            candidate = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field.upper()}_UTC_INVALID") from error
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return candidate.astimezone(UTC)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def freeze_json(value: object) -> FrozenJson:
    """Detach and recursively freeze one JSON-compatible value."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("TEMPORAL_JSON_NON_FINITE")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJson] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("TEMPORAL_JSON_KEY_INVALID")
            frozen[key] = freeze_json(item)
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    raise ValueError(f"TEMPORAL_JSON_VALUE_INVALID:{type(value).__name__}")


def thaw_json(value: object) -> object:
    """Return plain JSON dict/list values from a recursively frozen value."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _availability_from_receipt(
    *,
    source_published_at: datetime | None,
    robin_first_observed_at: datetime,
) -> datetime:
    if source_published_at is None:
        return robin_first_observed_at
    return max(source_published_at, robin_first_observed_at)


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    receipt_id: str
    source_name: str
    request_identity: str
    payload_sha256: str
    source_published_at: datetime | None
    robin_first_observed_at: datetime
    robin_ingested_at: datetime
    capture_code_revision: str
    storage_identity: str
    availability_status: TemporalProofLevel
    supersedes_receipt_id: str | None = None
    event_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        source_name: str,
        request_identity: str,
        payload_sha256: str,
        source_published_at: datetime | None,
        robin_first_observed_at: datetime,
        robin_ingested_at: datetime,
        capture_code_revision: str,
        storage_identity: str,
        availability_status: TemporalProofLevel,
        supersedes_receipt_id: str | None = None,
        event_at: datetime | None = None,
    ) -> SourceReceipt:
        """Build a receipt whose identifier is its canonical immutable content."""

        normalized = cls._identity_payload(
            source_name=source_name,
            request_identity=request_identity,
            payload_sha256=payload_sha256,
            source_published_at=source_published_at,
            robin_first_observed_at=robin_first_observed_at,
            robin_ingested_at=robin_ingested_at,
            capture_code_revision=capture_code_revision,
            storage_identity=storage_identity,
            availability_status=availability_status,
            supersedes_receipt_id=supersedes_receipt_id,
            event_at=event_at,
        )
        return cls(
            receipt_id=_canonical_sha256(normalized),
            source_name=source_name,
            request_identity=request_identity,
            payload_sha256=payload_sha256,
            source_published_at=source_published_at,
            robin_first_observed_at=robin_first_observed_at,
            robin_ingested_at=robin_ingested_at,
            capture_code_revision=capture_code_revision,
            storage_identity=storage_identity,
            availability_status=availability_status,
            supersedes_receipt_id=supersedes_receipt_id,
            event_at=event_at,
        )

    @staticmethod
    def _identity_payload(
        *,
        source_name: str,
        request_identity: str,
        payload_sha256: str,
        source_published_at: datetime | None,
        robin_first_observed_at: datetime,
        robin_ingested_at: datetime,
        capture_code_revision: str,
        storage_identity: str,
        availability_status: TemporalProofLevel,
        supersedes_receipt_id: str | None,
        event_at: datetime | None,
    ) -> dict[str, object]:
        observed = parse_utc(robin_first_observed_at, field="robin_first_observed_at")
        ingested = parse_utc(robin_ingested_at, field="robin_ingested_at")
        published = (
            parse_utc(source_published_at, field="source_published_at")
            if source_published_at is not None
            else None
        )
        normalized_event = (
            parse_utc(event_at, field="event_at") if event_at is not None else None
        )
        return {
            "source_name": source_name,
            "request_identity": request_identity,
            "payload_sha256": payload_sha256,
            "source_published_at": published.isoformat() if published else None,
            "robin_first_observed_at": observed.isoformat(),
            "robin_ingested_at": ingested.isoformat(),
            "capture_code_revision": capture_code_revision,
            "storage_identity": storage_identity,
            "availability_status": availability_status.value,
            "supersedes_receipt_id": supersedes_receipt_id,
            "event_at": normalized_event.isoformat() if normalized_event else None,
        }

    def __post_init__(self) -> None:
        _require_sha256(self.receipt_id, field="receipt_id")
        _require_sha256(self.payload_sha256, field="payload")
        observed = parse_utc(
            self.robin_first_observed_at,
            field="robin_first_observed_at",
        )
        ingested = parse_utc(self.robin_ingested_at, field="robin_ingested_at")
        published = (
            parse_utc(self.source_published_at, field="source_published_at")
            if self.source_published_at is not None
            else None
        )
        event = (
            parse_utc(self.event_at, field="event_at")
            if self.event_at is not None
            else None
        )
        if ingested < observed:
            raise ValueError("SOURCE_RECEIPT_INGESTION_BEFORE_OBSERVATION")
        if self.availability_status not in {
            TemporalProofLevel.RECEIPT_ATTESTED,
            TemporalProofLevel.SOURCE_AND_RECEIPT_ATTESTED,
            TemporalProofLevel.PROSPECTIVE_CAPTURED,
        }:
            raise ValueError("SOURCE_RECEIPT_PROOF_LEVEL_NOT_ATTESTED")
        if (
            self.availability_status
            is TemporalProofLevel.SOURCE_AND_RECEIPT_ATTESTED
            and published is None
        ):
            raise ValueError("SOURCE_PUBLISHED_AT_REQUIRED")
        if not all(
            (
                self.source_name,
                self.request_identity,
                self.capture_code_revision,
                self.storage_identity,
            )
        ):
            raise ValueError("SOURCE_RECEIPT_IDENTITY_INVALID")
        if self.supersedes_receipt_id is not None:
            _require_sha256(self.supersedes_receipt_id, field="supersedes_receipt")
        expected_receipt_id = _canonical_sha256(
            self._identity_payload(
                source_name=self.source_name,
                request_identity=self.request_identity,
                payload_sha256=self.payload_sha256,
                source_published_at=published,
                robin_first_observed_at=observed,
                robin_ingested_at=ingested,
                capture_code_revision=self.capture_code_revision,
                storage_identity=self.storage_identity,
                availability_status=self.availability_status,
                supersedes_receipt_id=self.supersedes_receipt_id,
                event_at=event,
            )
        )
        if self.receipt_id != expected_receipt_id:
            raise ValueError("SOURCE_RECEIPT_CONTENT_ADDRESS_MISMATCH")
        object.__setattr__(self, "robin_first_observed_at", observed)
        object.__setattr__(self, "robin_ingested_at", ingested)
        object.__setattr__(self, "source_published_at", published)
        object.__setattr__(self, "event_at", event)

    @property
    def available_at(self) -> datetime:
        return _availability_from_receipt(
            source_published_at=self.source_published_at,
            robin_first_observed_at=self.robin_first_observed_at,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "source_name": self.source_name,
            "request_identity": self.request_identity,
            "payload_sha256": self.payload_sha256,
            "source_published_at": (
                self.source_published_at.isoformat()
                if self.source_published_at is not None
                else None
            ),
            "robin_first_observed_at": self.robin_first_observed_at.isoformat(),
            "robin_ingested_at": self.robin_ingested_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "capture_code_revision": self.capture_code_revision,
            "storage_identity": self.storage_identity,
            "availability_status": self.availability_status.value,
            "supersedes_receipt_id": self.supersedes_receipt_id,
            "event_at": self.event_at.isoformat() if self.event_at is not None else None,
        }


def source_receipt_from_mapping(value: Mapping[str, object]) -> SourceReceipt:
    """Reconstruct a complete receipt and verify its content-addressed ID."""

    required = (
        "receipt_id",
        "source_name",
        "request_identity",
        "payload_sha256",
        "robin_first_observed_at",
        "robin_ingested_at",
        "capture_code_revision",
        "storage_identity",
        "availability_status",
    )
    if any(field not in value for field in required):
        raise ValueError("POINT_IN_TIME_SOURCE_RECEIPT_REQUIRED")
    try:
        proof_level = TemporalProofLevel(str(value["availability_status"]))
    except ValueError as error:
        raise ValueError("POINT_IN_TIME_SOURCE_RECEIPT_PROOF_INVALID") from error
    source_published_raw = value.get("source_published_at")
    supersedes_raw = value.get("supersedes_receipt_id")
    event_raw = value.get("event_at")
    return SourceReceipt(
        receipt_id=str(value["receipt_id"]),
        source_name=str(value["source_name"]),
        request_identity=str(value["request_identity"]),
        payload_sha256=str(value["payload_sha256"]),
        source_published_at=(
            parse_utc(
                cast(datetime | str, source_published_raw),
                field="source_published_at",
            )
            if source_published_raw is not None
            else None
        ),
        robin_first_observed_at=parse_utc(
            cast(datetime | str, value["robin_first_observed_at"]),
            field="robin_first_observed_at",
        ),
        robin_ingested_at=parse_utc(
            cast(datetime | str, value["robin_ingested_at"]),
            field="robin_ingested_at",
        ),
        capture_code_revision=str(value["capture_code_revision"]),
        storage_identity=str(value["storage_identity"]),
        availability_status=proof_level,
        supersedes_receipt_id=(
            str(supersedes_raw) if supersedes_raw is not None else None
        ),
        event_at=(
            parse_utc(cast(datetime | str, event_raw), field="event_at")
            if event_raw is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class TemporalFeatureLineage:
    feature_name: str
    feature_contract_version: str
    input_receipts: tuple[SourceReceipt, ...]
    cutoff_at: datetime
    computed_at: datetime
    code_revision: str
    asof_rule_version: str = ASOF_RULE_VERSION
    temporal_contract_version: str = TEMPORAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        cutoff = parse_utc(self.cutoff_at, field="cutoff_at")
        computed = parse_utc(self.computed_at, field="computed_at")
        if not self.feature_name or not self.feature_contract_version or not self.code_revision:
            raise ValueError("TEMPORAL_FEATURE_IDENTITY_INVALID")
        if (
            self.asof_rule_version != ASOF_RULE_VERSION
            or self.temporal_contract_version != TEMPORAL_CONTRACT_VERSION
        ):
            raise ValueError("TEMPORAL_FEATURE_CONTRACT_VERSION_INVALID")
        if not self.input_receipts:
            raise ValueError("POINT_IN_TIME_INPUT_NOT_PROVEN")
        if computed > cutoff:
            raise ValueError("TEMPORAL_FEATURE_COMPUTED_AFTER_CUTOFF")
        if any(
            receipt.available_at > cutoff
            or receipt.robin_ingested_at > cutoff
            for receipt in self.input_receipts
        ):
            raise ValueError("TEMPORAL_FEATURE_INPUT_AFTER_CUTOFF")
        receipt_ids = tuple(receipt.receipt_id for receipt in self.input_receipts)
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("TEMPORAL_FEATURE_RECEIPT_DUPLICATE")
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "computed_at", computed)
        object.__setattr__(
            self,
            "input_receipts",
            tuple(sorted(self.input_receipts, key=lambda item: item.receipt_id)),
        )

    @property
    def feature_available_at(self) -> datetime:
        return max(receipt.available_at for receipt in self.input_receipts)

    @property
    def lineage_hash(self) -> str:
        return _canonical_sha256(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_name": self.feature_name,
            "feature_contract_version": self.feature_contract_version,
            "input_receipt_ids": [item.receipt_id for item in self.input_receipts],
            "input_payload_hashes": [
                item.payload_sha256 for item in self.input_receipts
            ],
            "input_available_at": [
                item.available_at.isoformat() for item in self.input_receipts
            ],
            "feature_available_at": self.feature_available_at.isoformat(),
            "cutoff_at": self.cutoff_at.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "asof_rule_version": self.asof_rule_version,
            "temporal_contract_version": self.temporal_contract_version,
            "code_revision": self.code_revision,
            "status": "STRUCTURALLY_VALID_NOT_REPOSITORY_PROVEN",
        }


@dataclass(frozen=True, slots=True)
class TemporalDecisionLineage:
    cutoff_at: datetime
    predicted_at: datetime
    decided_at: datetime
    feature_lineage_hash: str
    odds_receipt_id: str
    odds_available_at: datetime
    model_registry_hash: str
    model_available_at: datetime
    temporal_contract_version: str = TEMPORAL_CONTRACT_VERSION
    point_in_time_status: str = "STRUCTURALLY_VALID_NOT_REPOSITORY_PROVEN"

    def __post_init__(self) -> None:
        cutoff = parse_utc(self.cutoff_at, field="cutoff_at")
        predicted = parse_utc(self.predicted_at, field="predicted_at")
        decided = parse_utc(self.decided_at, field="decided_at")
        odds_available = parse_utc(
            self.odds_available_at,
            field="odds_available_at",
        )
        model_available = parse_utc(
            self.model_available_at,
            field="model_available_at",
        )
        for field, value in (
            ("feature_lineage", self.feature_lineage_hash),
            ("odds_receipt", self.odds_receipt_id),
            ("model_registry", self.model_registry_hash),
        ):
            _require_sha256(value, field=field)
        if self.point_in_time_status != "STRUCTURALLY_VALID_NOT_REPOSITORY_PROVEN":
            raise ValueError("POINT_IN_TIME_STATUS_OVERCLAIMED")
        if self.temporal_contract_version != TEMPORAL_CONTRACT_VERSION:
            raise ValueError("POINT_IN_TIME_CONTRACT_VERSION_INVALID")
        if predicted > cutoff or odds_available > cutoff or model_available > predicted:
            raise ValueError("POINT_IN_TIME_DECISION_INPUT_AFTER_CUTOFF")
        if decided < predicted:
            raise ValueError("POINT_IN_TIME_DECISION_BEFORE_PREDICTION")
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "predicted_at", predicted)
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "odds_available_at", odds_available)
        object.__setattr__(self, "model_available_at", model_available)

    @property
    def lineage_hash(self) -> str:
        return _canonical_sha256(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "cutoff_at": self.cutoff_at.isoformat(),
            "predicted_at": self.predicted_at.isoformat(),
            "decided_at": self.decided_at.isoformat(),
            "feature_lineage_hash": self.feature_lineage_hash,
            "odds_receipt_id": self.odds_receipt_id,
            "odds_available_at": self.odds_available_at.isoformat(),
            "model_registry_hash": self.model_registry_hash,
            "model_available_at": self.model_available_at.isoformat(),
            "temporal_contract_version": self.temporal_contract_version,
            "point_in_time_status": self.point_in_time_status,
        }


def asof_select(
    rows: Iterable[Mapping[str, object]],
    *,
    entity_key: str,
    available_at_key: str,
    payload_hash_key: str,
    cutoff_at: datetime,
    expected_entity: object,
    receipt_verifier: Callable[[SourceReceipt], None],
    projection_verifier: Callable[
        [SourceReceipt, Mapping[str, object]],
        None,
    ],
) -> Mapping[str, object]:
    """Select the latest receipt-backed row available at or before cutoff.

    Rows without a proven availability timestamp are never candidates.  The
    caller must both re-read the receipt artifact and project the exact row
    values attested by its payload hash.  Two different payloads at the maximal
    admissible instant are an unresolved contradiction and therefore fail
    closed rather than depending on order.
    """

    cutoff = parse_utc(cutoff_at, field="cutoff_at")
    scoped: list[
        tuple[datetime, str, str, SourceReceipt, Mapping[str, object]]
    ] = []
    saw_entity = False
    for row in rows:
        if row.get(entity_key) != expected_entity:
            continue
        saw_entity = True
        raw_available = row.get(available_at_key)
        if raw_available is None:
            raise ValueError("POINT_IN_TIME_INPUT_NOT_PROVEN")
        available = parse_utc(
            cast(datetime | str, raw_available),
            field=available_at_key,
        )
        # A row whose declared availability is strictly after the decision
        # boundary cannot influence that decision.  Exclude it before parsing
        # or verifying the rest of its receipt so corrupt/mutated future-only
        # metadata cannot change an already reproducible past result.
        if available > cutoff:
            continue
        receipt = source_receipt_from_mapping(row)
        payload_hash = _require_sha256(
            row.get(payload_hash_key),
            field=payload_hash_key,
        )
        if available != receipt.available_at:
            raise ValueError("POINT_IN_TIME_RECEIPT_AVAILABILITY_MISMATCH")
        if payload_hash != receipt.payload_sha256:
            raise ValueError("POINT_IN_TIME_RECEIPT_PAYLOAD_MISMATCH")
        if receipt.robin_ingested_at > cutoff:
            continue
        scoped.append(
            (available, payload_hash, receipt.receipt_id, receipt, row)
        )
    if not scoped:
        if saw_entity:
            raise ValueError("POINT_IN_TIME_INPUT_NOT_PROVEN")
        raise ValueError("ASOF_ENTITY_NOT_FOUND")
    latest_available = max(item[0] for item in scoped)
    latest = [item for item in scoped if item[0] == latest_available]
    distinct_payloads = {item[1] for item in latest}
    if len(distinct_payloads) > 1:
        raise ValueError("ASOF_JOIN_AMBIGUOUS")
    for item in latest:
        receipt_verifier(item[3])
        projection_verifier(item[3], item[4])
    selected = min(latest, key=lambda item: (item[1], item[2]))[4]
    thawed = thaw_json(freeze_json(dict(selected)))
    if not isinstance(thawed, dict):
        raise AssertionError("ASOF_SELECTED_ROW_INVALID")
    return thawed


__all__ = [
    "ASOF_RULE_VERSION",
    "TEMPORAL_CONTRACT_VERSION",
    "SourceReceipt",
    "TemporalDecisionLineage",
    "TemporalFeatureLineage",
    "TemporalProofLevel",
    "asof_select",
    "freeze_json",
    "parse_utc",
    "source_receipt_from_mapping",
    "thaw_json",
]
