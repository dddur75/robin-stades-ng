"""Content-addressed append-only storage for Robin Chronos V1."""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from robin.prospective_observatory.contracts import canonical_json_bytes
from robin.prospective_observatory.prequential_storage import (
    ArtifactIntegrityError,
    ArtifactStore,
)

ChronosArtifactKind = Literal["facts", "prices", "receipts", "recovery"]


@dataclass(frozen=True, slots=True)
class StoredChronosArtifact:
    key: str
    sha256: str
    byte_size: int
    inserted: bool


def _deterministic_gzip(data: bytes) -> bytes:
    stream = BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0, filename="") as archive:
        archive.write(data)
    return stream.getvalue()


class ChronosArtifactRepository:
    """No-update/no-delete surface for the four mandated R2 prefixes."""

    PREFIXES = {
        "facts": "known-at/facts/schema-v1",
        "prices": "known-at/prices/schema-v1",
        "receipts": "known-at/receipts/schema-v1",
        "recovery": "known-at/recovery/schema-v1",
    }

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def put_json(
        self,
        kind: ChronosArtifactKind,
        payload: object,
        *,
        compress: bool = True,
    ) -> StoredChronosArtifact:
        canonical = canonical_json_bytes(payload)
        digest = hashlib.sha256(canonical).hexdigest()
        data = _deterministic_gzip(canonical) if compress else canonical
        prefix = self.PREFIXES[kind]
        suffix = "json.gz" if compress else "json"
        key = f"{prefix}/sha256/{digest[:2]}/{digest[2:4]}/{digest}.{suffix}"
        inserted = self.store.put_if_absent(key, data)
        actual = self.store.get_object(key)
        if actual != data:
            raise ArtifactIntegrityError(f"CHRONOS_APPEND_ONLY_CONFLICT:{key}")
        return StoredChronosArtifact(
            key=key,
            sha256=digest,
            byte_size=len(data),
            inserted=inserted,
        )

    def read_json(self, artifact: StoredChronosArtifact) -> bytes:
        data = self.store.get_object(artifact.key)
        if data is None:
            raise ArtifactIntegrityError(f"CHRONOS_ARTIFACT_MISSING:{artifact.key}")
        try:
            decoded = gzip.decompress(data) if artifact.key.endswith(".gz") else data
        except (gzip.BadGzipFile, EOFError) as error:
            raise ArtifactIntegrityError(
                f"CHRONOS_ARTIFACT_ENCODING_INVALID:{artifact.key}"
            ) from error
        if hashlib.sha256(decoded).hexdigest() != artifact.sha256:
            raise ArtifactIntegrityError(
                f"CHRONOS_ARTIFACT_HASH_MISMATCH:{artifact.key}"
            )
        return decoded


__all__ = ["ChronosArtifactRepository", "StoredChronosArtifact"]
