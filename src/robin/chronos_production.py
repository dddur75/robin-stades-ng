"""Fail-closed production contracts for the Chronos V3 bootstrap."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

EXPECTED_REPOSITORY = "dddur75/robin-stades-ng"
EXPECTED_REF = "refs/heads/main"
EXPECTED_BEFORE_REVISION = "0013_historical_evidence_index"
EXPECTED_AFTER_REVISION = "0014_chronos_control_plane_v2"
EXPECTED_ENVIRONMENT = "chronos-control-plane-production"
MIGRATION_TARGET = EXPECTED_AFTER_REVISION
SCOPED_LOGINS = (
    (
        "chronos_authority_runtime_login",
        "chronos_authority_executor",
        "CHRONOS_BOOTSTRAP_AUTHORITY_PASSWORD",
    ),
    (
        "chronos_effect_runtime_login",
        "chronos_runtime_writer",
        "CHRONOS_BOOTSTRAP_RUNTIME_PASSWORD",
    ),
    (
        "chronos_reader_login",
        "chronos_reader",
        "CHRONOS_BOOTSTRAP_READER_PASSWORD",
    ),
)

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SAFE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})


class ChronosProductionError(RuntimeError):
    """A sanitized fail-closed production contract error."""


def require_sha(value: str, *, field: str) -> str:
    """Require a Git SHA without retaining an unsafe value in the error."""

    if _HEX_40.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


def require_hash(value: str, *, field: str) -> str:
    if _HEX_64.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


def require_identifier(value: str, *, field: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ChronosProductionError(f"CHRONOS_{field.upper()}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class DirectPostgresTarget:
    """Non-secret connection metadata approved for reports and artifacts."""

    host: str
    port: int
    database: str
    username: str
    sslmode: str


def validate_direct_postgres_url(value: str) -> DirectPostgresTarget:
    """Reject non-PostgreSQL, pooled, passwordless, or non-TLS URLs."""

    try:
        parsed = urlparse(value)
        port = parsed.port or 5432
    except (TypeError, ValueError):
        raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID") from None
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ChronosProductionError("CHRONOS_DATABASE_SCHEME_INVALID")
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
    if "pooler" in host or "-pool" in host or ".pool." in host:
        raise ChronosProductionError("CHRONOS_POOLED_ENDPOINT_FORBIDDEN")
    if parsed.username is None or parsed.password is None:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_MISSING")
    database = parsed.path.removeprefix("/")
    if not database or "/" in database:
        raise ChronosProductionError("CHRONOS_DATABASE_NAME_INVALID")
    query = parse_qs(parsed.query, keep_blank_values=True)
    ssl_values = query.get("sslmode", [])
    if len(ssl_values) != 1 or ssl_values[0] not in _SAFE_SSL_MODES:
        raise ChronosProductionError("CHRONOS_SSL_REQUIRED")
    return DirectPostgresTarget(
        host=host,
        port=port,
        database=database,
        username=parsed.username,
        sslmode=ssl_values[0],
    )


def build_scoped_database_url(
    target: DirectPostgresTarget,
    *,
    username: str,
    password: str,
) -> str:
    """Build a URL outside logs with RFC3986-encoded credentials."""

    require_identifier(username, field="scoped_username")
    if not password:
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_MISSING")
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{target.host}"
    if target.port != 5432:
        netloc += f":{target.port}"
    return urlunparse(
        (
            "postgresql+psycopg",
            netloc,
            "/" + quote(target.database, safe=""),
            "",
            urlencode({"sslmode": target.sslmode}),
            "",
        )
    )


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_document(document: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a detached HMAC envelope without logging key material."""

    if not key:
        raise ChronosProductionError("CHRONOS_SIGNING_KEY_MISSING")
    unsigned = dict(document)
    unsigned.pop("signature", None)
    digest = hmac.new(
        key.encode("utf-8"), canonical_json_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    return {
        **unsigned,
        "signature": {
            "algorithm": "HMAC-SHA256",
            "value": digest,
        },
    }


def verify_signed_document(document: dict[str, Any], key: str) -> dict[str, Any]:
    """Verify an HMAC envelope and return only the unsigned document."""

    signature = document.get("signature")
    if not isinstance(signature, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_MISSING")
    if signature.get("algorithm") != "HMAC-SHA256":
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_ALGORITHM_INVALID")
    supplied = signature.get("value")
    if not isinstance(supplied, str) or _HEX_64.fullmatch(supplied) is None:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_INVALID")
    unsigned = dict(document)
    unsigned.pop("signature", None)
    expected = hmac.new(
        key.encode("utf-8"), canonical_json_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_SIGNATURE_MISMATCH")
    return unsigned


def preflight_hash(document: dict[str, Any]) -> str:
    unsigned = dict(document)
    unsigned.pop("signature", None)
    unsigned.pop("preflight_hash", None)
    return hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()


def generation_hash(nonce_hex: str) -> str:
    require_hash(nonce_hex, field="generation_nonce")
    return hashlib.sha256(bytes.fromhex(nonce_hex)).hexdigest()


def assert_exact_preflight_binding(
    document: dict[str, Any],
    *,
    main_sha: str,
    workflow_sha: str,
    project_id: str,
    production_branch_id: str,
    recovery_branch_id: str,
) -> None:
    """Reject stale, replayed, or cross-project PREFLIGHT artifacts."""

    expected: dict[str, object] = {
        "main_sha": require_sha(main_sha, field="main_sha"),
        "workflow_sha": require_sha(workflow_sha, field="workflow_sha"),
        "project_id": project_id,
        "production_branch_id": production_branch_id,
        "current_revision": EXPECTED_BEFORE_REVISION,
        "recovery_branch_id": recovery_branch_id,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            raise ChronosProductionError(
                f"CHRONOS_PREFLIGHT_{field.upper()}_MISMATCH"
            )
    supplied_hash = document.get("preflight_hash")
    if not isinstance(supplied_hash, str) or supplied_hash != preflight_hash(document):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_HASH_MISMATCH")
    if document.get("golden_gate") != "CHRONOS_MIGRATION_READY":
        raise ChronosProductionError("CHRONOS_MIGRATION_BLOCKED")


__all__ = [
    "EXPECTED_AFTER_REVISION",
    "EXPECTED_BEFORE_REVISION",
    "EXPECTED_ENVIRONMENT",
    "EXPECTED_REF",
    "EXPECTED_REPOSITORY",
    "MIGRATION_TARGET",
    "SCOPED_LOGINS",
    "ChronosProductionError",
    "DirectPostgresTarget",
    "assert_exact_preflight_binding",
    "build_scoped_database_url",
    "canonical_json_bytes",
    "generation_hash",
    "preflight_hash",
    "require_hash",
    "require_identifier",
    "require_sha",
    "sign_document",
    "validate_direct_postgres_url",
    "verify_signed_document",
]
