"""Fail-closed production contracts for the Chronos V3 bootstrap."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import psycopg
from psycopg import Connection

EXPECTED_REPOSITORY = "dddur75/robin-stades-ng"
EXPECTED_REF = "refs/heads/main"
EXPECTED_BEFORE_REVISION = "0013_historical_evidence_index"
EXPECTED_BEFORE_REVISIONS = (
    EXPECTED_BEFORE_REVISION,
    "0014_chronos_control_plane_v2",
)
EXPECTED_AFTER_REVISION = "0015_data_torrent_opportunity"
EXPECTED_ENVIRONMENT = "chronos-control-plane-production"
DATA_TORRENT_MISSION_ID = "data-torrent-ready-v1"
DATA_TORRENT_OWNER_DIRECTIVE_SHA256 = (
    "c03e218ca8f69d30f3fe998f7534d3edb11e2ba71bdd3ca022ada7ee08a2295d"
)
DATA_TORRENT_MISSION_MANIFEST_SHA256 = (
    "22e64bb33bd54aeeb528a416c7f6d0ca1c0719a27677302b8065249923ca96e7"
)
DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256 = (
    "9a9d44db699bfb39c5f8006b90ce6273a9de643be49c6e179487d4703fd09785"
)
DATA_TORRENT_ONE_SHOT_NOT_BEFORE = "2026-08-30T06:36:00Z"
DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT = "2026-09-01T22:00:00Z"
DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS = 3600
MIGRATION_TARGET = EXPECTED_AFTER_REVISION
SCOPED_LOGINS = (
    (
        "chronos_authority_runtime_login",
        "chronos_authority_executor",
        "CHRONOS_AUTHORITY_DATABASE_URL",
    ),
    (
        "chronos_effect_runtime_login",
        "chronos_runtime_writer",
        "CHRONOS_RUNTIME_DATABASE_URL",
    ),
    (
        "chronos_reader_login",
        "chronos_reader",
        "CHRONOS_READER_DATABASE_URL",
    ),
)
PRODUCTION_SAFETY_LOCKS = {
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
    "API_FOOTBALL_CALLS_ALLOWED": "0",
}

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SAFE_NEON_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.neon\.tech$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_GENERATION_PASSWORD_ENTROPY = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_SAFE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_SAFE_QUERY_KEYS = frozenset({"sslmode", "channel_binding"})
_LIBPQ_ENVIRONMENT = re.compile(r"^PG[A-Z0-9_]+$")


def _is_neon_pooler_host(host: str) -> bool:
    return host.split(".", 1)[0].endswith("-pooler")


def libpq_environment_variable_names(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return only ambient libpq variable names, never their values."""

    source = os.environ if environment is None else environment
    return tuple(
        sorted(
            {
                name.upper()
                for name in source
                if _LIBPQ_ENVIRONMENT.fullmatch(name.upper()) is not None
            }
        )
    )


def require_libpq_environment_clean() -> None:
    if libpq_environment_variable_names():
        raise ChronosProductionError("CHRONOS_LIBPQ_ENVIRONMENT_FORBIDDEN")


def connect_direct_postgres(
    database_url: str,
    *,
    connector: Callable[..., Connection[Any]] = psycopg.connect,
) -> Connection[Any]:
    """Open one canonical direct connection without ambient libpq influence."""

    target = validate_direct_postgres_url(database_url)
    require_libpq_environment_clean()
    return connector(
        database_url,
        host=target.host,
        port=target.port,
        dbname=target.database,
        user=target.username,
        sslmode=target.sslmode,
        channel_binding=target.channel_binding,
        connect_timeout=10,
    )


class ChronosProductionError(RuntimeError):
    """A sanitized fail-closed production contract error."""


def _authority_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ChronosProductionError(f"CHRONOS_MISSION_AUTHORITY_{field.upper()}_INVALID")
    return parsed.astimezone(UTC)


def validate_data_torrent_authority(
    *,
    now: datetime | None = None,
    repository_root: Path | None = None,
) -> datetime:
    """Verify the immutable owner authority and its unexpired execution window."""

    root = Path(__file__).resolve().parents[2] if repository_root is None else repository_root
    manifest_path = root / "configs" / "execution" / "data-torrent-ready-v1.json"
    effect_path = (
        root / "configs" / "execution" / "data-torrent-ready-v1-controlled-go-effect-contract.json"
    )
    documents: list[dict[str, Any]] = []
    for path, expected_hash in (
        (manifest_path, DATA_TORRENT_MISSION_MANIFEST_SHA256),
        (effect_path, DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256),
    ):
        try:
            payload = path.read_bytes()
        except OSError:
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_MISSING") from None
        if (
            not payload
            or len(payload) > 65_536
            or path.is_symlink()
            or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_hash)
        ):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_HASH_MISMATCH")
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID") from None
        if not isinstance(document, dict):
            raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID")
        documents.append(document)

    manifest, effect_contract = documents
    if set(manifest) != {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_INVALID")
    if (
        manifest.get("mission_id") != DATA_TORRENT_MISSION_ID
        or effect_contract.get("mission_id") != DATA_TORRENT_MISSION_ID
        or manifest.get("source_hash") != DATA_TORRENT_OWNER_DIRECTIVE_SHA256
        or effect_contract.get("owner_directive_source_sha256")
        != DATA_TORRENT_OWNER_DIRECTIVE_SHA256
        or effect_contract.get("parent_manifest_sha256") != DATA_TORRENT_MISSION_MANIFEST_SHA256
        or effect_contract.get("expands_parent_authority") is not False
        or effect_contract.get("expires_at") != manifest.get("expires_at")
        or effect_contract.get("one_shot_not_before") != DATA_TORRENT_ONE_SHOT_NOT_BEFORE
        or effect_contract.get("latest_effect_admission_at")
        != DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT
        or effect_contract.get("maximum_effect_runtime_seconds")
        != DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS
    ):
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_BINDING_MISMATCH")
    expiry = _authority_timestamp(manifest.get("expires_at"), field="expiry")
    not_before = _authority_timestamp(
        effect_contract.get("one_shot_not_before"), field="not_before"
    )
    admission_close = _authority_timestamp(
        effect_contract.get("latest_effect_admission_at"),
        field="effect_admission",
    )
    observed_now = datetime.now(UTC) if now is None else now
    if observed_now.tzinfo is None:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_NOW_INVALID")
    observed_now = observed_now.astimezone(UTC)
    if (
        not_before >= admission_close
        or admission_close >= expiry
        or expiry - admission_close < timedelta(seconds=DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS)
    ):
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_WINDOW_INVALID")
    if observed_now < not_before:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_NOT_YET_ACTIVE")
    if observed_now >= expiry:
        raise ChronosProductionError("CHRONOS_MISSION_AUTHORITY_EXPIRED")
    if observed_now >= admission_close:
        raise ChronosProductionError("CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED")
    return expiry


def assert_production_safety_locks(environment: Mapping[str, str]) -> None:
    invalid = [
        name
        for name, expected in PRODUCTION_SAFETY_LOCKS.items()
        if environment.get(name, "").strip().lower() != expected
    ]
    if invalid:
        raise ChronosProductionError(f"CHRONOS_PRODUCTION_SAFETY_LOCK_MISMATCH:{','.join(invalid)}")


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
    channel_binding: str | None = "require"

    def __post_init__(self) -> None:
        if (
            self.host != self.host.lower()
            or _SAFE_NEON_HOST.fullmatch(self.host) is None
            or _is_neon_pooler_host(self.host)
        ):
            raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
        if self.port != 5432:
            raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID")
        if not self.database or "/" in self.database:
            raise ChronosProductionError("CHRONOS_DATABASE_NAME_INVALID")
        if not self.username:
            raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_MISSING")
        if self.sslmode not in _SAFE_SSL_MODES:
            raise ChronosProductionError("CHRONOS_SSL_REQUIRED")
        if self.channel_binding != "require":
            raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")


def validate_direct_postgres_url(value: str) -> DirectPostgresTarget:
    """Apply the canonical fail-closed Chronos production DSN contract."""

    if not isinstance(value, str) or not value.startswith("postgresql://"):
        raise ChronosProductionError("CHRONOS_DATABASE_SCHEME_INVALID")
    if _INVALID_PERCENT_ESCAPE.search(value) is not None:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID")
    try:
        parsed = urlparse(value)
        parsed_port = parsed.port
        port = 5432 if parsed_port is None else parsed_port
        username = unquote(parsed.username or "", errors="strict")
        database = unquote(parsed.path.removeprefix("/"), errors="strict")
        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
        raw_query_keys = []
        for field in parsed.query.split("&"):
            if field.count("=") != 1:
                raise ValueError("malformed query field")
            raw_query_keys.append(field.partition("=")[0])
    except (TypeError, UnicodeError, ValueError):
        raise ChronosProductionError("CHRONOS_DATABASE_URL_INVALID") from None
    if parsed.scheme != "postgresql":
        raise ChronosProductionError("CHRONOS_DATABASE_SCHEME_INVALID")
    if parsed.params or parsed.fragment or ";" in parsed.path:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    if parsed.netloc.count("@") != 1:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    raw_userinfo, _, _ = parsed.netloc.partition("@")
    if raw_userinfo.count(":") != 1:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    raw_host = parsed.hostname or ""
    host = raw_host.lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
    if "%" in raw_host or _SAFE_NEON_HOST.fullmatch(host) is None:
        raise ChronosProductionError("CHRONOS_DIRECT_DATABASE_HOST_INVALID")
    if _is_neon_pooler_host(host):
        raise ChronosProductionError("CHRONOS_POOLED_ENDPOINT_FORBIDDEN")
    try:
        password = unquote(parsed.password or "", errors="strict")
    except (UnicodeError, ValueError):
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID") from None
    if not username or not password:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_MISSING")
    if len(password) < 8:
        raise ChronosProductionError("CHRONOS_DATABASE_CREDENTIALS_INVALID")
    if not database or "/" in database:
        raise ChronosProductionError("CHRONOS_DATABASE_NAME_INVALID")
    query: dict[str, str] = {}
    if any(key not in _SAFE_QUERY_KEYS for key in raw_query_keys):
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    for key, item in query_items:
        if key not in _SAFE_QUERY_KEYS or not item or key in query:
            raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
        query[key] = item
    if set(query) != _SAFE_QUERY_KEYS:
        raise ChronosProductionError("CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN")
    sslmode = query["sslmode"]
    if sslmode not in _SAFE_SSL_MODES:
        raise ChronosProductionError("CHRONOS_SSL_REQUIRED")
    channel_binding = query.get("channel_binding")
    if channel_binding != "require":
        raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")
    return DirectPostgresTarget(
        host=host,
        port=port,
        database=database,
        username=username,
        sslmode=sslmode,
        channel_binding=channel_binding,
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
    query_items = [("sslmode", target.sslmode)]
    if target.channel_binding is not None:
        if target.channel_binding != "require":
            raise ChronosProductionError("CHRONOS_CHANNEL_BINDING_REQUIRED")
        query_items.append(("channel_binding", target.channel_binding))
    return urlunparse(
        (
            "postgresql",
            netloc,
            "/" + quote(target.database, safe=""),
            "",
            urlencode(query_items),
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


def build_generation_bound_password(*, nonce_hex: str, entropy: str) -> str:
    """Bind a scoped credential to the nonce that activates its generation."""

    digest = generation_hash(nonce_hex)
    if _GENERATION_PASSWORD_ENTROPY.fullmatch(entropy) is None:
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_ENTROPY_INVALID")
    return f"g1_{digest}_{entropy}"


def require_generation_bound_password(*, password: str, nonce_hex: str) -> str:
    """Reject a partial or mixed GitHub secret rotation before any DB effect."""

    parts = password.split("_", 2)
    if (
        len(parts) != 3
        or parts[0] != "g1"
        or _HEX_64.fullmatch(parts[1]) is None
        or _GENERATION_PASSWORD_ENTROPY.fullmatch(parts[2]) is None
        or not hmac.compare_digest(parts[1], generation_hash(nonce_hex))
    ):
        raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_GENERATION_MISMATCH")
    return password


def validate_controlled_go_binding(
    value: object,
    *,
    main_sha: str,
) -> dict[str, Any]:
    """Validate the exact immutable controlled-wake release-chain binding."""

    expected_main_sha = require_sha(main_sha, field="main_sha")
    fields = {
        "schema_version",
        "workflow_path",
        "run_id",
        "run_attempt",
        "main_sha",
        "report_schema",
        "report_sha256",
        "endpoint_pre_wake_state",
        "compute_wake_events",
        "postgresql_connection_attempts",
        "production_sql_writes",
        "neon_mutations",
        "durable_store",
        "conditional_put_outcome",
        "durable_object_key",
        "durable_readback_sha256",
        "seal_workflow_path",
        "seal_run_id",
        "seal_run_attempt",
        "seal_receipt_sha256",
        "seal_r2_puts",
        "seal_r2_gets",
        "seal_r2_objects_created",
        "preflight_readback_sha256",
        "preflight_r2_gets",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ChronosProductionError("CHRONOS_CONTROLLED_GO_BINDING_INVALID")
    binding = dict(value)
    controlled_run_id = binding.get("run_id")
    seal_run_id = binding.get("seal_run_id")
    report_sha256 = binding.get("report_sha256")
    if (
        binding.get("schema_version") != "chronos-controlled-go-binding-v1"
        or binding.get("workflow_path")
        != ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"
        or not isinstance(controlled_run_id, str)
        or _RUN_ID.fullmatch(controlled_run_id) is None
        or binding.get("run_attempt") != "1"
        or binding.get("main_sha") != expected_main_sha
        or binding.get("report_schema") != "chronos-neon-controlled-idle-wake-readonly-v1"
        or not isinstance(report_sha256, str)
        or _HEX_64.fullmatch(report_sha256) is None
        or binding.get("endpoint_pre_wake_state") not in {"active", "idle"}
        or type(binding.get("compute_wake_events")) is not int
        or binding.get("compute_wake_events") != 1
        or type(binding.get("postgresql_connection_attempts")) is not int
        or binding.get("postgresql_connection_attempts") != 1
        or type(binding.get("production_sql_writes")) is not int
        or binding.get("production_sql_writes") != 0
        or type(binding.get("neon_mutations")) is not int
        or binding.get("neon_mutations") != 0
        or binding.get("durable_store") != "R2_IMMUTABLE"
        or binding.get("conditional_put_outcome") != "CREATED"
        or binding.get("durable_object_key")
        != (
            "data-torrent-ready-v1/control-plane/controlled-go/"
            f"main_sha={expected_main_sha}/run_id={controlled_run_id}/"
            f"report-{report_sha256}.json"
        )
        or binding.get("durable_readback_sha256") != report_sha256
        or binding.get("seal_workflow_path")
        != ".github/workflows/chronos-controlled-go-durable-seal-v1.yml"
        or not isinstance(seal_run_id, str)
        or _RUN_ID.fullmatch(seal_run_id) is None
        or binding.get("seal_run_attempt") != "1"
        or not isinstance(binding.get("seal_receipt_sha256"), str)
        or _HEX_64.fullmatch(str(binding.get("seal_receipt_sha256"))) is None
        or type(binding.get("seal_r2_puts")) is not int
        or binding.get("seal_r2_puts") != 1
        or type(binding.get("seal_r2_gets")) is not int
        or binding.get("seal_r2_gets") != 1
        or type(binding.get("seal_r2_objects_created")) is not int
        or binding.get("seal_r2_objects_created") != 1
        or binding.get("preflight_readback_sha256") != report_sha256
        or type(binding.get("preflight_r2_gets")) is not int
        or binding.get("preflight_r2_gets") != 1
    ):
        raise ChronosProductionError("CHRONOS_CONTROLLED_GO_BINDING_INVALID")
    return binding


def assert_exact_preflight_binding(
    document: dict[str, Any],
    *,
    main_sha: str,
    workflow_sha: str,
    project_id: str,
    production_branch_id: str,
    recovery_branch_id: str,
    current_revision: str = EXPECTED_BEFORE_REVISION,
) -> None:
    """Reject stale, replayed, or cross-project PREFLIGHT artifacts."""

    expected: dict[str, object] = {
        "main_sha": require_sha(main_sha, field="main_sha"),
        "workflow_sha": require_sha(workflow_sha, field="workflow_sha"),
        "project_id": project_id,
        "production_branch_id": production_branch_id,
        "current_revision": current_revision,
        "recovery_branch_id": recovery_branch_id,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            raise ChronosProductionError(f"CHRONOS_PREFLIGHT_{field.upper()}_MISMATCH")
    supplied_hash = document.get("preflight_hash")
    if not isinstance(supplied_hash, str) or supplied_hash != preflight_hash(document):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_HASH_MISMATCH")
    if document.get("golden_gate") != "CHRONOS_MIGRATION_READY":
        raise ChronosProductionError("CHRONOS_MIGRATION_BLOCKED")


__all__ = [
    "DATA_TORRENT_CONTROLLED_EFFECT_CONTRACT_SHA256",
    "DATA_TORRENT_LATEST_EFFECT_ADMISSION_AT",
    "DATA_TORRENT_MAXIMUM_EFFECT_RUNTIME_SECONDS",
    "DATA_TORRENT_MISSION_ID",
    "DATA_TORRENT_MISSION_MANIFEST_SHA256",
    "DATA_TORRENT_ONE_SHOT_NOT_BEFORE",
    "DATA_TORRENT_OWNER_DIRECTIVE_SHA256",
    "EXPECTED_AFTER_REVISION",
    "EXPECTED_BEFORE_REVISION",
    "EXPECTED_BEFORE_REVISIONS",
    "EXPECTED_ENVIRONMENT",
    "EXPECTED_REF",
    "EXPECTED_REPOSITORY",
    "MIGRATION_TARGET",
    "SCOPED_LOGINS",
    "PRODUCTION_SAFETY_LOCKS",
    "ChronosProductionError",
    "DirectPostgresTarget",
    "assert_exact_preflight_binding",
    "assert_production_safety_locks",
    "build_scoped_database_url",
    "build_generation_bound_password",
    "canonical_json_bytes",
    "connect_direct_postgres",
    "generation_hash",
    "preflight_hash",
    "require_hash",
    "require_generation_bound_password",
    "require_identifier",
    "require_sha",
    "sign_document",
    "validate_direct_postgres_url",
    "validate_data_torrent_authority",
    "validate_controlled_go_binding",
    "libpq_environment_variable_names",
    "require_libpq_environment_clean",
    "verify_signed_document",
]
