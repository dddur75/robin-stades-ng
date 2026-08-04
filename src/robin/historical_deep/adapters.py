"""Infrastructure adapters for the append-only historical-deep lane."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from robin.historical.object_storage_migration import create_r2_client


class R2UnavailableError(RuntimeError):
    """Raised when the durable object store cannot be read or written."""


class R2ObjectStore:
    """Cloudflare R2 adapter deliberately exposing no deletion operation."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        self.client, self.bucket = create_r2_client(environment)

    @staticmethod
    def _error_code(error: ClientError) -> str:
        details = error.response.get("Error", {})
        return str(details.get("Code", "UNKNOWN")) if isinstance(details, Mapping) else "UNKNOWN"

    def get_object(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise R2UnavailableError(f"R2_GET_FAILED:{self._error_code(error)}") from error
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise R2UnavailableError("R2_BODY_INVALID")
        payload = body.read()
        if not isinstance(payload, bytes):
            raise R2UnavailableError("R2_BODY_INVALID")
        return payload

    def put_if_absent(self, key: str, data: bytes) -> bool:
        try:
            cast(Any, self.client).put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
                Metadata={
                    "lane": "historical-deep-data",
                    "append-only": "true",
                    "schema": "v1",
                },
            )
            return True
        except ClientError as error:
            code = self._error_code(error)
            if code in {
                "409",
                "412",
                "ConditionalRequestConflict",
                "PreconditionFailed",
            }:
                return False
            raise R2UnavailableError(f"R2_PUT_FAILED:{code}") from error

    def iter_keys(self, prefix: str) -> Iterable[str]:
        continuation: str | None = None
        while True:
            arguments: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation is not None:
                arguments["ContinuationToken"] = continuation
            try:
                response = cast(Any, self.client).list_objects_v2(**arguments)
            except ClientError as error:
                raise R2UnavailableError(
                    f"R2_LIST_FAILED:{self._error_code(error)}"
                ) from error
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise R2UnavailableError("R2_LIST_RESPONSE_INVALID")
            for item in contents:
                if isinstance(item, Mapping) and isinstance(item.get("Key"), str):
                    yield str(item["Key"])
            if not bool(response.get("IsTruncated")):
                return
            candidate = response.get("NextContinuationToken")
            if not isinstance(candidate, str) or not candidate:
                raise R2UnavailableError("R2_LIST_CURSOR_MISSING")
            continuation = candidate


class DirectoryObjectStore:
    """Local append-only adapter for dry-runs, tests, and cache-only replay."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / Path(key)).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("OBJECT_KEY_OUTSIDE_CACHE_ROOT")
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
        prefix_root = self._path(f"{prefix.rstrip('/')}/_prefix").parent
        if not prefix_root.exists():
            return ()
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in prefix_root.rglob("*")
                if path.is_file()
            )
        )


def build_object_store(
    environment: Mapping[str, str],
    *,
    cache_root: Path | None = None,
) -> R2ObjectStore | DirectoryObjectStore:
    """Select local cache explicitly; otherwise require the durable R2 store."""

    if cache_root is not None:
        return DirectoryObjectStore(cache_root)
    return R2ObjectStore(environment)


def assert_safety_locks(environment: Mapping[str, str]) -> None:
    """Fail closed before any provider call or durable write."""

    required = {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
        "THE_ODDS_API_HISTORICAL_CREDITS": "false",
    }
    invalid = [
        name
        for name, expected in required.items()
        if environment.get(name, "").strip().lower() != expected
    ]
    if invalid:
        raise RuntimeError(f"HISTORICAL_DEEP_SAFETY_LOCK_MISMATCH:{','.join(invalid)}")


def validate_r2_round_trip(store: R2ObjectStore | DirectoryObjectStore, *, key: str) -> None:
    """Verify a harmless immutable sentinel without providing a delete surface."""

    payload = b'{"append_only":true,"lane":"historical-deep-data","schema":"v1"}'
    created = store.put_if_absent(key, payload)
    stored = store.get_object(key)
    if stored != payload:
        raise R2UnavailableError("R2_SENTINEL_HASH_MISMATCH")
    if not created and stored != payload:
        raise R2UnavailableError("R2_SENTINEL_APPEND_ONLY_MISMATCH")
