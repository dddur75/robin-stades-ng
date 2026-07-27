"""Append-only R2-first storage for prospective raw payloads."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from robin.prospective_observatory.contracts import (
    R2_SCHEMA_VERSION,
    CaptureContext,
    CaptureReceipt,
    canonical_json_bytes,
    receipt_scope_sha256,
)

R2_NAMESPACE = "prospective-deep-data"


class AppendOnlyViolation(RuntimeError):
    """Raised when an existing R2 object differs from the requested bytes."""


class PayloadIntegrityError(RuntimeError):
    """Raised when a stored payload no longer matches its immutable receipt."""


@runtime_checkable
class ObjectStore(Protocol):
    """Minimal object-store surface; deletion is deliberately not part of it."""

    def get_object(self, key: str) -> bytes | None: ...

    def put_if_absent(self, key: str, data: bytes) -> bool:
        """Atomically create *key*, returning False when it already exists."""

    def iter_keys(self, prefix: str) -> Iterable[str]: ...


class InMemoryObjectStore:
    """Strict test double with the same no-overwrite contract required from R2."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def get_object(self, key: str) -> bytes | None:
        return self._objects.get(key)

    def put_if_absent(self, key: str, data: bytes) -> bool:
        if key in self._objects:
            return False
        self._objects[key] = bytes(data)
        return True

    def iter_keys(self, prefix: str) -> Iterable[str]:
        return tuple(sorted(key for key in self._objects if key.startswith(prefix)))

    @property
    def object_count(self) -> int:
        return len(self._objects)


@dataclass(frozen=True, slots=True)
class StoredCapture:
    receipt: CaptureReceipt
    payload: object
    payload_created: bool
    receipt_created: bool


def _safe_segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("R2_KEY_SEGMENT_INVALID")
    return quote(value, safe="-_.~")


def deterministic_r2_prefix(context: CaptureContext) -> str:
    observed = context.observed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return (
        f"{R2_NAMESPACE}/{R2_SCHEMA_VERSION}/"
        f"competition={_safe_segment(context.competition)}/"
        f"season={_safe_segment(context.season)}/"
        f"fixture={_safe_segment(context.fixture_id)}/"
        f"source={_safe_segment(context.provider)}/"
        f"family={context.family.value}/"
        f"observed_at={observed}"
    )


def deterministic_r2_keys(
    context: CaptureContext,
    payload_sha256: str,
) -> tuple[str, str]:
    if len(payload_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in payload_sha256
    ):
        raise ValueError("PAYLOAD_SHA256_INVALID")
    prefix = deterministic_r2_prefix(context)
    receipt_scope = receipt_scope_sha256(
        window_id=context.window_id,
        window_label=context.window_label,
    )
    return (
        f"{prefix}/payload-{payload_sha256}.json.gz",
        f"{prefix}/receipt-{receipt_scope}-{payload_sha256}.json",
    )


class ProspectiveR2Repository:
    """Owns raw prospective bytes; Git and PostgreSQL only retain references."""

    def __init__(
        self,
        store: ObjectStore,
        *,
        namespace: str = R2_NAMESPACE,
    ) -> None:
        if namespace != R2_NAMESPACE:
            raise ValueError("PROSPECTIVE_R2_NAMESPACE_MUST_BE_VERSIONED_CANONICAL")
        self.store = store
        self.namespace = namespace

    @staticmethod
    def _put_immutable(store: ObjectStore, key: str, data: bytes) -> bool:
        created = store.put_if_absent(key, data)
        if created:
            return True
        existing = store.get_object(key)
        if existing is None:
            raise AppendOnlyViolation("R2_CONDITIONAL_WRITE_INCONSISTENT")
        if existing != data:
            raise AppendOnlyViolation(f"R2_APPEND_ONLY_OBJECT_MISMATCH:{key}")
        return False

    def capture(
        self,
        *,
        payload: object,
        context: CaptureContext,
    ) -> StoredCapture:
        canonical_payload = canonical_json_bytes(payload)
        import hashlib

        payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
        compressed = gzip.compress(canonical_payload, compresslevel=9, mtime=0)
        payload_key, receipt_key = deterministic_r2_keys(context, payload_sha256)
        materialized_at = context.materialized_at or context.response_received_at
        receipt = CaptureReceipt(
            window_id=context.window_id,
            window_label=context.window_label,
            fixture_id=context.fixture_id,
            competition=context.competition,
            season=context.season,
            provider=context.provider,
            family=context.family,
            requested_at=context.requested_at,
            response_received_at=context.response_received_at,
            observed_at=context.observed_at,
            kickoff_at=context.kickoff_at,
            cutoff_at=context.cutoff_at,
            seconds_before_kickoff=int(
                (context.kickoff_at - context.response_received_at).total_seconds()
            ),
            http_status=context.http_status,
            payload_sha256=payload_sha256,
            payload_bytes=len(canonical_payload),
            stored_bytes=len(compressed),
            r2_key=payload_key,
            receipt_r2_key=receipt_key,
            source_endpoint=context.source_endpoint,
            complete=context.complete,
            quality_status=context.quality_status,
            provider_calls=context.provider_calls,
            code_revision=context.code_revision,
            event_time=context.event_time,
            provider_updated_at=context.provider_updated_at,
            materialized_at=materialized_at,
        )
        receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json"))

        payload_created = self._put_immutable(self.store, payload_key, compressed)
        try:
            receipt_created = self._put_immutable(
                self.store,
                receipt_key,
                receipt_bytes,
            )
        except Exception:
            # The raw payload remains a valid immutable orphan and can be reconciled.
            # Deleting it would violate the lane's storage contract.
            raise
        return StoredCapture(
            receipt=receipt,
            payload=payload,
            payload_created=payload_created,
            receipt_created=receipt_created,
        )

    def read_capture(self, receipt_key: str) -> StoredCapture:
        receipt_bytes = self.store.get_object(receipt_key)
        if receipt_bytes is None:
            raise FileNotFoundError(receipt_key)
        try:
            receipt_data = json.loads(receipt_bytes)
            receipt = CaptureReceipt.model_validate(receipt_data)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise PayloadIntegrityError("R2_RECEIPT_INVALID") from error
        compressed = self.store.get_object(receipt.r2_key)
        if compressed is None:
            raise PayloadIntegrityError("R2_PAYLOAD_MISSING")
        try:
            canonical_payload = gzip.decompress(compressed)
            payload = json.loads(canonical_payload)
        except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PayloadIntegrityError("R2_PAYLOAD_INVALID") from error
        import hashlib

        if (
            hashlib.sha256(canonical_payload).hexdigest() != receipt.payload_sha256
            or len(canonical_payload) != receipt.payload_bytes
            or len(compressed) != receipt.stored_bytes
            or canonical_json_bytes(payload) != canonical_payload
        ):
            raise PayloadIntegrityError("R2_PAYLOAD_HASH_OR_SIZE_MISMATCH")
        return StoredCapture(
            receipt=receipt,
            payload=payload,
            payload_created=False,
            receipt_created=False,
        )

    def iter_captures(self) -> Iterator[StoredCapture]:
        prefix = f"{self.namespace}/{R2_SCHEMA_VERSION}/"
        receipt_keys = sorted(
            key
            for key in self.store.iter_keys(prefix)
            if key.rsplit("/", maxsplit=1)[-1].startswith("receipt-")
            and key.endswith(".json")
        )
        for receipt_key in receipt_keys:
            yield self.read_capture(receipt_key)
