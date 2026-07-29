"""Append-only object storage for prequential manifests and model artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from robin.prospective_observatory.contracts import canonical_json_bytes

PREQUENTIAL_R2_NAMESPACE = "prequential-learning/schema-v1"


class ArtifactStore(Protocol):
    def get_object(self, key: str) -> bytes | None: ...

    def put_if_absent(self, key: str, data: bytes) -> bool: ...

    def iter_keys(self, prefix: str) -> Iterable[str]: ...


class ArtifactIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    key: str
    sha256: str
    byte_size: int
    inserted: bool


class InMemoryArtifactStore:
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


class DirectoryArtifactStore:
    """Local append-only adapter for isolated pilots and tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / Path(key)).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("PREQUENTIAL_OBJECT_KEY_OUTSIDE_ROOT")
        return candidate

    def get_object(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def put_if_absent(self, key: str, data: bytes) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            return False
        return True

    def iter_keys(self, prefix: str) -> Iterable[str]:
        marker = self._path(f"{prefix.rstrip('/')}/_marker")
        root = marker.parent
        if not root.exists():
            return ()
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
        )


class R2ArtifactStore:
    """Cloudflare R2 adapter with conditional writes and no deletion API."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        from robin.historical.object_storage_migration import create_r2_client

        self.client, self.bucket = create_r2_client(environment)

    @staticmethod
    def _missing(error: ClientError) -> bool:
        details = error.response.get("Error", {})
        return isinstance(details, Mapping) and str(details.get("Code", "")) in {
            "404",
            "NoSuchKey",
            "NotFound",
        }

    def get_object(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._missing(error):
                return None
            raise
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise ArtifactIntegrityError("PREQUENTIAL_R2_BODY_INVALID")
        data = body.read()
        if not isinstance(data, bytes):
            raise ArtifactIntegrityError("PREQUENTIAL_R2_BODY_INVALID")
        return data

    def put_if_absent(self, key: str, data: bytes) -> bool:
        try:
            cast(Any, self.client).put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
                Metadata={
                    "lane": "prequential-learning",
                    "append-only": "true",
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
            )
            return True
        except ClientError as error:
            details = error.response.get("Error", {})
            code = str(details.get("Code", "")) if isinstance(details, Mapping) else ""
            if code in {
                "409",
                "412",
                "ConditionalRequestConflict",
                "PreconditionFailed",
            }:
                return False
            raise

    def iter_keys(self, prefix: str) -> Iterable[str]:
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if token is not None:
                kwargs["ContinuationToken"] = token
            response = cast(Any, self.client).list_objects_v2(**kwargs)
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise ArtifactIntegrityError("PREQUENTIAL_R2_LIST_INVALID")
            for item in contents:
                if isinstance(item, Mapping) and isinstance(item.get("Key"), str):
                    yield str(item["Key"])
            if not bool(response.get("IsTruncated")):
                return
            candidate = response.get("NextContinuationToken")
            if not isinstance(candidate, str) or not candidate:
                raise ArtifactIntegrityError("PREQUENTIAL_R2_CURSOR_MISSING")
            token = candidate


def _safe_kind(value: str) -> str:
    if not value or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in value):
        raise ValueError("PREQUENTIAL_ARTIFACT_KIND_INVALID")
    return value


class PrequentialArtifactRepository:
    """Content-addressed repository with no update or delete surface."""

    def __init__(
        self,
        store: ArtifactStore,
        *,
        namespace: str = PREQUENTIAL_R2_NAMESPACE,
    ) -> None:
        if namespace != PREQUENTIAL_R2_NAMESPACE:
            raise ValueError("PREQUENTIAL_R2_NAMESPACE_INVALID")
        self.store = store
        self.namespace = namespace

    def _put(self, *, kind: str, data: bytes, suffix: str) -> StoredArtifact:
        safe_kind = _safe_kind(kind)
        digest = hashlib.sha256(data).hexdigest()
        key = f"{self.namespace}/{safe_kind}/{digest}.{suffix}"
        inserted = self.store.put_if_absent(key, data)
        actual = self.store.get_object(key)
        if actual != data:
            raise ArtifactIntegrityError(
                f"PREQUENTIAL_APPEND_ONLY_ARTIFACT_CONFLICT:{key}"
            )
        return StoredArtifact(
            key=key,
            sha256=digest,
            byte_size=len(data),
            inserted=inserted,
        )

    def put_manifest(
        self,
        kind: str,
        value: Mapping[str, object],
    ) -> StoredArtifact:
        return self._put(
            kind=kind,
            data=canonical_json_bytes(dict(value)),
            suffix="json",
        )

    def put_artifact(self, kind: str, data: bytes) -> StoredArtifact:
        if not data:
            raise ValueError("PREQUENTIAL_EMPTY_ARTIFACT_FORBIDDEN")
        return self._put(kind=kind, data=data, suffix="bin")

    def read_verified(self, key: str, expected_sha256: str) -> bytes:
        if not key.startswith(f"{self.namespace}/"):
            raise ValueError("PREQUENTIAL_ARTIFACT_NAMESPACE_INVALID")
        data = self.store.get_object(key)
        if data is None:
            raise ArtifactIntegrityError(f"PREQUENTIAL_ARTIFACT_MISSING:{key}")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ArtifactIntegrityError(
                f"PREQUENTIAL_ARTIFACT_HASH_MISMATCH:{key}"
            )
        return data

    def inventory(self) -> dict[str, object]:
        keys = tuple(self.store.iter_keys(f"{self.namespace}/"))
        invalid: list[str] = []
        total_bytes = 0
        for key in keys:
            data = self.store.get_object(key)
            if data is None:
                invalid.append(key)
                continue
            total_bytes += len(data)
            digest = hashlib.sha256(data).hexdigest()
            filename = key.rsplit("/", 1)[-1]
            if not filename.startswith(digest):
                invalid.append(key)
        return {
            "namespace": self.namespace,
            "objects": len(keys),
            "bytes": total_bytes,
            "integrity_errors": invalid,
            "verified": not invalid,
        }


__all__ = [
    "ArtifactIntegrityError",
    "ArtifactStore",
    "DirectoryArtifactStore",
    "InMemoryArtifactStore",
    "PREQUENTIAL_R2_NAMESPACE",
    "PrequentialArtifactRepository",
    "R2ArtifactStore",
    "StoredArtifact",
]
