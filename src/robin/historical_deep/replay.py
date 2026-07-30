"""Deterministic, provider-free replay of historical R2 evidence.

The replay boundary deliberately accepts plain mappings and sequences.  It can
therefore be used by the collector, a workflow, or a unit test without importing
provider clients or persistence code.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

Normalizer = Callable[[Mapping[str, object], object], Mapping[str, object]]


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"REPLAY_VALUE_NOT_JSON_SERIALIZABLE:{type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Return the one canonical representation used by replay evidence hashes."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _decode_payload(value: object) -> tuple[object, tuple[str, ...]]:
    """Decode JSON/gzip inputs and return every valid physical/semantic hash.

    R2 adapters do not all expose the same layer: some return the stored gzip
    bytes, while others return decompressed JSON.  The receipt hash is accepted
    only when it matches one of the exact representations actually observed.
    """

    candidates: set[str] = set()
    decoded: object = value
    if isinstance(value, bytes):
        candidates.add(hashlib.sha256(value).hexdigest())
        raw = value
        if value[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(value)
            except (EOFError, OSError) as exc:
                raise ValueError("REPLAY_GZIP_PAYLOAD_INVALID") from exc
            candidates.add(hashlib.sha256(raw).hexdigest())
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("REPLAY_PAYLOAD_MUST_BE_JSON") from exc
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("REPLAY_PAYLOAD_MUST_BE_JSON") from exc
        candidates.add(hashlib.sha256(value.encode("utf-8")).hexdigest())
    candidates.add(canonical_sha256(decoded))
    return decoded, tuple(sorted(candidates))


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        mapped = asdict(value)
        if isinstance(mapped, Mapping):
            return mapped
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        mapped = model_dump(mode="json")
        if isinstance(mapped, Mapping):
            return mapped
    raise TypeError(f"{label}_MUST_BE_A_MAPPING")


def _receipt_key(receipt: Mapping[str, object]) -> str:
    for field in ("payload_key", "r2_key", "object_key", "key"):
        value = receipt.get(field)
        if value is not None and str(value).strip():
            return str(value)
    raise ValueError("REPLAY_RECEIPT_PAYLOAD_KEY_REQUIRED")


def _receipt_id(receipt: Mapping[str, object]) -> str:
    for field in ("receipt_hash", "receipt_id", "task_id", "id"):
        value = receipt.get(field)
        if value is not None and str(value).strip():
            return str(value)
    return canonical_sha256(receipt)


def _payload_index(
    payloads: Mapping[str, object] | Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if isinstance(payloads, Mapping):
        return {str(key): value for key, value in payloads.items()}
    output: dict[str, object] = {}
    for item in payloads:
        mapped = _mapping(item, label="REPLAY_PAYLOAD_ENTRY")
        key = next(
            (
                str(mapped[field])
                for field in ("payload_key", "r2_key", "object_key", "key")
                if mapped.get(field) is not None and str(mapped[field]).strip()
            ),
            None,
        )
        if key is None:
            raise ValueError("REPLAY_PAYLOAD_ENTRY_KEY_REQUIRED")
        if key in output:
            raise ValueError(f"REPLAY_DUPLICATE_PAYLOAD_KEY:{key}")
        output[key] = mapped.get("payload", mapped.get("body", mapped.get("value")))
    return output


def _expected_payload_hash(receipt: Mapping[str, object]) -> str | None:
    for field in ("payload_sha256", "content_sha256", "object_sha256"):
        value = receipt.get(field)
        if value is not None and str(value).strip():
            expected = str(value).lower()
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                raise ValueError(f"REPLAY_RECEIPT_HASH_INVALID:{field}")
            return expected
    return None


def _default_normalizer(
    receipt: Mapping[str, object],
    payload: object,
) -> Mapping[str, object]:
    return {
        "receipt_id": _receipt_id(receipt),
        "payload_key": _receipt_key(receipt),
        "family": receipt.get("family"),
        "competition": receipt.get("competition"),
        "season": receipt.get("season"),
        "task_id": receipt.get("task_id"),
        "payload": payload,
    }


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    receipt_id: str
    payload_key: str
    payload_sha256: str
    projection_sha256: str
    projection: dict[str, object] | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReplayResult:
    status: str
    payloads_replayed: int
    receipts_verified: int
    provider_calls: int
    provider_credits: int
    hash_mismatches: int
    missing_payloads: int
    extra_payloads: int
    source_hash: str
    replay_hash: str
    expected_replay_hash: str | None
    hash_identical: bool
    entries: tuple[ReplayEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def replay_stream_cache_only(
    evidence_pairs: Iterable[
        tuple[Mapping[str, object] | object, object]
    ],
    *,
    normalizer: Normalizer | None = None,
    expected_replay_hash: str | None = None,
    known_payload_keys: Iterable[str] | None = None,
    require_all_payloads_referenced: bool = True,
    retain_projections: bool = True,
) -> ReplayResult:
    """Replay receipt/payload pairs while retaining only compact proof.

    Each receipt must reference one payload and, when present, its payload hash
    must match the exact stored, decompressed, or canonical JSON representation.
    The aggregate replay hash is deterministic and can be pinned by the caller.
    """

    normalize = normalizer or _default_normalizer
    entries: list[ReplayEntry] = []
    seen_receipts: set[str] = set()
    referenced_keys: set[str] = set()
    receipt_hashes: set[str] = set()

    for receipt_value, payload_value in evidence_pairs:
        receipt = _mapping(receipt_value, label="REPLAY_RECEIPT")
        receipt_id = _receipt_id(receipt)
        if receipt_id in seen_receipts:
            raise ValueError(f"REPLAY_DUPLICATE_RECEIPT:{receipt_id}")
        seen_receipts.add(receipt_id)
        payload_key = _receipt_key(receipt)
        referenced_keys.add(payload_key)
        payload, payload_hash_candidates = _decode_payload(payload_value)
        expected_payload_hash = _expected_payload_hash(receipt)
        if (
            expected_payload_hash is not None
            and expected_payload_hash not in payload_hash_candidates
        ):
            raise ValueError(f"REPLAY_PAYLOAD_HASH_MISMATCH:{payload_key}")
        pinned_value = receipt.get("replay_hash") or receipt.get("dataset_hash")
        if pinned_value:
            receipt_hashes.add(str(pinned_value))
        payload_sha256 = expected_payload_hash or canonical_sha256(payload)
        projection_value = normalize(receipt, payload)
        projection = dict(_mapping(projection_value, label="REPLAY_PROJECTION"))
        entries.append(
            ReplayEntry(
                receipt_id=receipt_id,
                payload_key=payload_key,
                payload_sha256=payload_sha256,
                projection_sha256=canonical_sha256(projection),
                # Full normalized projections can be as large as the raw evidence.
                # The runner only needs their digest, so allow it to release each
                # decoded payload before moving to the next receipt.
                projection=projection if retain_projections else None,
            )
        )

    extra_keys = (
        set(str(key) for key in known_payload_keys) - referenced_keys
        if known_payload_keys is not None
        else set()
    )
    if require_all_payloads_referenced and extra_keys:
        raise ValueError(f"REPLAY_UNREFERENCED_PAYLOADS:{len(extra_keys)}")
    entries.sort(key=lambda item: (item.payload_key, item.receipt_id))
    evidence = [
        {
            "receipt_id": item.receipt_id,
            "payload_key": item.payload_key,
            "payload_sha256": item.payload_sha256,
            "projection_sha256": item.projection_sha256,
        }
        for item in entries
    ]
    source_hash = canonical_sha256(
        [
            {
                "receipt_id": item.receipt_id,
                "payload_key": item.payload_key,
                "payload_sha256": item.payload_sha256,
            }
            for item in entries
        ]
    )
    replay_hash = canonical_sha256(evidence)
    pinned_hash = expected_replay_hash
    if pinned_hash is None:
        if len(receipt_hashes) > 1:
            raise ValueError("REPLAY_RECEIPT_DATASET_HASH_CONFLICT")
        pinned_hash = next(iter(receipt_hashes), None)
    identical = pinned_hash is None or replay_hash == pinned_hash
    if not identical:
        raise ValueError("REPLAY_DATASET_HASH_MISMATCH")
    return ReplayResult(
        status="CACHE_ONLY_REPLAY_VERIFIED",
        payloads_replayed=len(entries),
        receipts_verified=len(entries),
        provider_calls=0,
        provider_credits=0,
        hash_mismatches=0,
        missing_payloads=0,
        extra_payloads=len(extra_keys),
        source_hash=source_hash,
        replay_hash=replay_hash,
        expected_replay_hash=pinned_hash,
        hash_identical=identical,
        entries=tuple(entries),
    )


def replay_cache_only(
    payloads: Mapping[str, object] | Sequence[Mapping[str, object]],
    receipts: Sequence[Mapping[str, object] | object],
    *,
    normalizer: Normalizer | None = None,
    expected_replay_hash: str | None = None,
    require_all_payloads_referenced: bool = True,
    retain_projections: bool = True,
) -> ReplayResult:
    """Replay an in-memory cache through the same streaming verifier."""

    indexed_payloads = _payload_index(payloads)

    def pairs() -> Iterable[
        tuple[Mapping[str, object] | object, object]
    ]:
        for receipt_value in receipts:
            receipt = _mapping(receipt_value, label="REPLAY_RECEIPT")
            payload_key = _receipt_key(receipt)
            if payload_key not in indexed_payloads:
                raise ValueError(f"REPLAY_PAYLOAD_MISSING:{payload_key}")
            yield receipt, indexed_payloads[payload_key]

    return replay_stream_cache_only(
        pairs(),
        normalizer=normalizer,
        expected_replay_hash=expected_replay_hash,
        known_payload_keys=indexed_payloads,
        require_all_payloads_referenced=require_all_payloads_referenced,
        retain_projections=retain_projections,
    )


def replay_from_r2(
    payloads: Mapping[str, object] | Sequence[Mapping[str, object]],
    receipts: Sequence[Mapping[str, object] | object],
    **kwargs: Any,
) -> ReplayResult:
    """Compatibility name for the provider-free replay boundary."""

    return replay_cache_only(payloads, receipts, **kwargs)
