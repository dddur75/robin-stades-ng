"""Provider-free deterministic replay from R2 raw objects."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from robin.prospective_observatory.contracts import CaptureReceipt, canonical_sha256
from robin.prospective_observatory.r2 import ProspectiveR2Repository

NormalizedProjection = Mapping[str, object]
Normalizer = Callable[[CaptureReceipt, object], NormalizedProjection]


class ProjectionSink(Protocol):
    def insert_capture(
        self,
        receipt: CaptureReceipt,
        projection: NormalizedProjection,
        projection_hash: str,
    ) -> bool:
        """Return True for a new projection and False for an exact duplicate."""


class InMemoryProjectionSink:
    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, dict[str, object]]] = {}

    @property
    def rows(self) -> dict[str, tuple[str, dict[str, object]]]:
        return dict(self._rows)

    def insert_capture(
        self,
        receipt: CaptureReceipt,
        projection: NormalizedProjection,
        projection_hash: str,
    ) -> bool:
        key = receipt.receipt_hash
        value = (projection_hash, dict(projection))
        existing = self._rows.get(key)
        if existing is not None:
            if existing != value:
                raise ValueError("PROJECTION_IDEMPOTENCY_CONFLICT")
            return False
        self._rows[key] = value
        return True


@dataclass(frozen=True, slots=True)
class ReplayResult:
    objects_examined: int
    payloads_replayed: int
    projections_inserted: int
    duplicates_avoided: int
    provider_calls: int
    provider_credits: int
    bytes_read: int
    hash_mismatches: int
    data_loss: int
    dataset_hash: str


def _default_normalizer(
    receipt: CaptureReceipt,
    _payload: object,
) -> NormalizedProjection:
    """Index-only default; family projection requires an explicit normalizer."""

    return {
        "fixture_id": receipt.fixture_id,
        "family": receipt.family.value,
        "observed_at": receipt.observed_at.isoformat(),
        "response_received_at": receipt.response_received_at.isoformat(),
        "payload_sha256": receipt.payload_sha256,
        "r2_key": receipt.r2_key,
        "quality_status": receipt.quality_status.value,
        "complete": receipt.complete,
    }


def replay_from_r2(
    repository: ProspectiveR2Repository,
    sink: ProjectionSink,
    *,
    normalizer: Normalizer | None = None,
) -> ReplayResult:
    normalize = normalizer or _default_normalizer
    inserted = 0
    duplicates = 0
    bytes_read = 0
    evidence: list[dict[str, object]] = []
    captures = 0
    for stored in repository.iter_captures():
        captures += 1
        projection = normalize(stored.receipt, stored.payload)
        projection_hash = canonical_sha256(dict(projection))
        if sink.insert_capture(stored.receipt, projection, projection_hash):
            inserted += 1
        else:
            duplicates += 1
        bytes_read += stored.receipt.stored_bytes
        evidence.append(
            {
                "receipt_hash": stored.receipt.receipt_hash,
                "payload_sha256": stored.receipt.payload_sha256,
                "projection_hash": projection_hash,
            }
        )
    return ReplayResult(
        objects_examined=captures * 2,
        payloads_replayed=captures,
        projections_inserted=inserted,
        duplicates_avoided=duplicates,
        provider_calls=0,
        provider_credits=0,
        bytes_read=bytes_read,
        hash_mismatches=0,
        data_loss=0,
        dataset_hash=canonical_sha256(evidence),
    )
