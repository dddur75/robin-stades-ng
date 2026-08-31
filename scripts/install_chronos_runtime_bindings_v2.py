"""Install the four exact Recovery V2 runtime bindings once, in fixed order."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import multiprocessing
import os
import re
import secrets
import shutil
import subprocess  # nosec B404 - fixed argv GitHub CLI invocation.
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from robin.chronos_production import (
    EXPECTED_ENVIRONMENT,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    DirectPostgresTarget,
    _recovery_v2_evidence_bytes,
    _recovery_v2_path_is_reparse,
    _recovery_v2_prepare_repository_directory,
    _recovery_v2_publish_exclusive_bytes,
    _recovery_v2_replace_bytes,
    _recovery_v2_require_repository_file,
    _recovery_v2_require_unused_repository_output,
    assert_production_safety_locks,
    build_generation_bound_password,
    build_scoped_database_url,
    generation_hash,
    require_hash,
    require_sha,
    sign_document,
    validate_data_torrent_recovery_v2_authority,
)
from scripts.check_chronos_github_hold_v3 import (
    GITHUB_GET_TOTAL_TIMEOUT_SECONDS,
    _github_get,
    verify_hold,
    verify_no_concurrent_runs,
)
from scripts.chronos_production_recovery_v2 import validate_preflight_artifact_v2
from scripts.dispatch_data_torrent_recovery_v2_stage import (
    RecoveryV2ControllerError,
    validate_preflight_controller_handoff_v2,
)

BINDINGS = (
    ("CHRONOS_AUTHORITY_DATABASE_URL", "chronos_authority_runtime_login"),
    ("CHRONOS_RUNTIME_DATABASE_URL", "chronos_effect_runtime_login"),
    ("CHRONOS_READER_DATABASE_URL", "chronos_reader_login"),
)
BINDING_ORDER = [name for name, _login in BINDINGS] + ["CHRONOS_CONTROL_PLANE_GENERATION_NONCE"]
_REPOSITORY_ROOT = Path(os.path.abspath(Path(__file__))).parents[1]
CANONICAL_REPORT_PATH = (
    _REPOSITORY_ROOT
    / ".torrent"
    / "release"
    / "chronos-runtime-bindings-v2.json"
)
_EFFECT_ADMISSION_DEADLINE_SECONDS = 480.0
_STAGE_OUTER_TIMEOUT_SECONDS = 600.0
_GITHUB_GET_TIMEOUT_SECONDS = GITHUB_GET_TOTAL_TIMEOUT_SECONDS
_FULL_HOLD_GITHUB_GETS = 12
_CONCURRENCY_GITHUB_GETS = 5
# The immutable effect contract keeps this three-GET reserve in the reported
# ceiling.  R4 performs no new attestation GET: it consumes the attestation
# already sealed in the canonical R3 predecessor cache and final controller
# journal.
_CACHED_ATTESTATION_CONTRACTUAL_GET_RESERVE = 3
_MAIN_REF_GITHUB_GETS = 4
_SECRET_PUBLIC_KEY_GITHUB_GETS = 1
_SECRET_ENCRYPT_TIMEOUT_SECONDS = 25.0
_SECRET_PUT_TOTAL_TIMEOUT_SECONDS = 15.0
_SECRET_WRITE_TIMEOUT_SECONDS = _SECRET_ENCRYPT_TIMEOUT_SECONDS + _SECRET_PUT_TOTAL_TIMEOUT_SECONDS
_EFFECT_SAFETY_MARGIN_SECONDS = 15.0
_PINNED_GH_CLI_VERSION = "2.96.0"
_PINNED_GH_CLI_SHA256 = "cd79f16203f1fbe56937c4c96e2b6eadd10549418dcb241d91576ac77af0ac8b"
_PINNED_GH_CLI_SIZE = 41_504_056
_PINNED_GH_CLI_VERSION_LINES = (
    "gh version 2.96.0 (2026-07-02)",
    "https://github.com/cli/cli/releases/tag/v2.96.0",
)
_GITHUB_HOST = "github.com"
_GITHUB_API_ROOT = "https://api.github.com"
_MAX_GH_ENCRYPT_OUTPUT_BYTES = 16 * 1024
_MAX_GH_DEBUG_OUTPUT_BYTES = 64 * 1024
_MAX_SECRET_PUT_PROCESS_INPUT_BYTES = 32 * 1024
_SECRET_PUT_WORK_TIMEOUT_SECONDS = 10.0
_FULL_HOLD_MAX_SECONDS = _FULL_HOLD_GITHUB_GETS * _GITHUB_GET_TIMEOUT_SECONDS
_CONCURRENCY_MAX_SECONDS = _CONCURRENCY_GITHUB_GETS * _GITHUB_GET_TIMEOUT_SECONDS


def _remaining_effect_schedule_seconds(*, writes_remaining: int) -> float:
    return float(
        writes_remaining * (_CONCURRENCY_MAX_SECONDS + _SECRET_WRITE_TIMEOUT_SECONDS)
        + _FULL_HOLD_MAX_SECONDS
        + _EFFECT_SAFETY_MARGIN_SECONDS
    )


_FULL_EFFECT_SCHEDULE_SECONDS = _FULL_HOLD_MAX_SECONDS + _remaining_effect_schedule_seconds(
    writes_remaining=len(BINDING_ORDER)
)


class BindingInstallerV2Error(RuntimeError):
    """Sanitized terminal binding error; no recovery or retry is implied."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _load_preflight_source(
    path: Path,
    *,
    main_sha: str,
    run_id: str,
) -> tuple[bytes, dict[str, object]]:
    """Unwrap the canonical R3 predecessor cache and bind its embedded attestation."""

    try:
        source = _recovery_v2_evidence_bytes(
            path,
            repository_root=_REPOSITORY_ROOT,
            maximum_bytes=16 * 1024 * 1024,
        )
        document = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (ChronosProductionError, UnicodeDecodeError, ValueError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID") from None
    if not source or not isinstance(document, dict):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID")
    encoded_payload = document.get("payload_base64")
    attestation = document.get("attestation")
    if (
        set(document)
        != {
            "schema_version",
            "kind",
            "artifact_filename",
            "payload_base64",
            "attestation",
        }
        or document.get("schema_version")
        != "data-torrent-recovery-v2-singleton-cache-v1"
        or document.get("kind") != "PREFLIGHT"
        or document.get("artifact_filename") != "production-preflight-v2.json"
        or not isinstance(encoded_payload, str)
        or not isinstance(attestation, dict)
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID")
    try:
        payload = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID") from None
    expected_attestation_fields = {
        "schema_version",
        "repository",
        "workflow_path",
        "run_id",
        "run_attempt",
        "head_sha",
        "artifact_id",
        "artifact_name",
        "payload_sha256",
        "archive_sha256",
    }
    if (
        set(attestation) != expected_attestation_fields
        or attestation.get("schema_version") != "github-artifact-attestation-v2"
        or attestation.get("repository") != EXPECTED_REPOSITORY
        or attestation.get("workflow_path")
        != ".github/workflows/chronos-production-bootstrap-v4.yml"
        or attestation.get("run_id") != run_id
        or attestation.get("run_attempt") != "1"
        or attestation.get("head_sha") != main_sha
        or type(attestation.get("artifact_id")) is not int
        or int(attestation["artifact_id"]) <= 0
        or attestation.get("artifact_name") != f"production-preflight-v2-{run_id}"
        or attestation.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID")
    try:
        require_hash(str(attestation.get("archive_sha256", "")), field="archive_sha256")
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID") from None
    if (
        not payload
        or len(payload) > 10 * 1024 * 1024
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\x00" in payload
        or b"\r" in payload
        or not payload.endswith(b"\n")
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID")
    return payload, dict(attestation)


def _require_external_write_window(
    deadline_epoch: float,
    *,
    deadline_monotonic: float,
    margin_seconds: float,
) -> None:
    """Refuse to begin a secret operation without its full bounded time window."""

    if (
        isinstance(deadline_epoch, bool)
        or not isinstance(deadline_epoch, (int, float))
        or not math.isfinite(float(deadline_epoch))
        or isinstance(deadline_monotonic, bool)
        or not isinstance(deadline_monotonic, (int, float))
        or not math.isfinite(float(deadline_monotonic))
        or isinstance(margin_seconds, bool)
        or not isinstance(margin_seconds, (int, float))
        or not math.isfinite(float(margin_seconds))
        or margin_seconds < 0
        or time.time() + float(margin_seconds) >= float(deadline_epoch)
        or time.monotonic() + float(margin_seconds) >= float(deadline_monotonic)
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED")


def _same_path(left: Path, right: Path) -> bool:
    return Path(os.path.abspath(left)) == Path(os.path.abspath(right))


def _require_canonical_preflight_cache_path(path: Path) -> None:
    expected = (
        _REPOSITORY_ROOT
        / ".torrent"
        / "release"
        / "recovery-v2-predecessor-cache"
        / "production-preflight-v2.json"
    )
    if not _same_path(path, expected):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_PATH_FORBIDDEN")


def _require_absolute_no_reparse_file(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    chain = [candidate, *candidate.parents]
    for component in reversed(chain):
        try:
            component.lstat()
        except OSError:
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID") from None
        if _recovery_v2_path_is_reparse(component):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    if not candidate.is_file():
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    return candidate


def _write_report(path: Path, payload: bytes, *, exclusive: bool) -> None:
    try:
        _recovery_v2_prepare_repository_directory(
            path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
        if exclusive:
            _recovery_v2_publish_exclusive_bytes(
                path,
                payload,
                repository_root=_REPOSITORY_ROOT,
            )
            return
        _recovery_v2_replace_bytes(
            path,
            payload,
            repository_root=_REPOSITORY_ROOT,
        )
    except FileExistsError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_INVOCATION_ALREADY_CONSUMED") from None
    except (ChronosProductionError, OSError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_REPORT_PATH_FORBIDDEN") from None


def _github_cli_environment(*, config_dir: Path, require_token: bool = False) -> dict[str, str]:
    """Build an isolated github.com-only environment for the pinned CLI."""

    environment: dict[str, str] = {}
    ambient = {key.casefold(): (key, value) for key, value in os.environ.items()}
    for allowed in ("systemroot", "windir", "comspec", "pathext", "temp", "tmp"):
        item = ambient.get(allowed)
        if item is not None:
            environment[item[0]] = item[1]
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if require_token and (not token or len(token.encode("utf-8")) > 2_048):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    if token:
        environment["GH_TOKEN"] = token
    environment.update(
        {
            "GH_HOST": _GITHUB_HOST,
            "GH_CONFIG_DIR": str(config_dir),
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1",
            "GH_TELEMETRY": "0",
            "DO_NOT_TRACK": "1",
            "GH_SPINNER_DISABLED": "1",
            "NO_COLOR": "1",
            # The no-store command makes one GET on a fresh HTTP/1 connection.
            # Go's transport does not replay a request on a fresh connection.
            "GODEBUG": "http2client=0",
        }
    )
    return environment


def _require_pinned_gh_cli() -> Path:
    candidate = shutil.which("gh")
    if candidate is None:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    path = _require_absolute_no_reparse_file(Path(candidate))
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID") from None
    if (
        size != _PINNED_GH_CLI_SIZE
        or not hmac.compare_digest(digest, _PINNED_GH_CLI_SHA256)
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    try:
        with tempfile.TemporaryDirectory(prefix="robin-gh-config-v2-") as config_name:
            completed = subprocess.run(  # nosec B603 B607 - fixed local version query.
                [str(path), "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
                env=_github_cli_environment(config_dir=Path(config_name)),
            )
    except (OSError, subprocess.SubprocessError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID") from None
    if not completed.stdout or len(completed.stdout) > 4_096:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    try:
        lines = tuple(completed.stdout.decode("utf-8", errors="strict").splitlines())
    except UnicodeDecodeError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID") from None
    if lines != _PINNED_GH_CLI_VERSION_LINES:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_VERSION_INVALID")
    return path


def _validate_global_hold(*, repository: str, main_sha: str) -> None:
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    try:
        report = verify_hold(
            required_successful_ci_sha=main_sha,
            recovery_v2=True,
            repository_override=repository,
            token_override=token,
            current_run_id=0,
        )
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GLOBAL_HOLD_INVALID") from None
    if report.get("verdict") != "WORKFLOW_HOLD_ESTABLISHED":
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GLOBAL_HOLD_INVALID")


def _validate_no_concurrent_runs(*, repository: str) -> None:
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    try:
        verify_no_concurrent_runs(
            repository=repository,
            token=token,
            current_run_id=0,
        )
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GLOBAL_HOLD_INVALID") from None


def assert_current_main(*, repository: str, main_sha: str) -> str:
    """Bind main through the bounded direct github.com transport."""

    if repository != EXPECTED_REPOSITORY:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_TARGET_FORBIDDEN")
    expected_sha = str(require_sha(main_sha, field="main_sha"))
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    try:
        reference = _github_get(f"/repos/{repository}/git/ref/heads/main", token)
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_MAIN_REF_INVALID") from None
    target = reference.get("object")
    if (
        reference.get("ref") != "refs/heads/main"
        or not isinstance(target, dict)
        or target.get("type") != "commit"
        or target.get("sha") != expected_sha
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_MAIN_REF_INVALID")
    return expected_sha


def _public_key_trace(*, stderr: bytes, repository: str, environment: str) -> str:
    if not stderr or len(stderr) > _MAX_GH_DEBUG_OUTPUT_BYTES:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID")
    try:
        trace = stderr.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID") from None
    expected_path = f"/repos/{repository}/environments/{environment}/secrets/public-key"
    expected_url = _GITHUB_API_ROOT + expected_path
    request_lines = re.findall(
        r"(?m)^> (?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^\r\n]+$",
        trace,
    )
    response_lines = re.findall(r"(?m)^< HTTP/[0-9.]+ [0-9]{3}[^\r\n]*$", trace)
    if (
        request_lines != [f"> GET {expected_path} HTTP/1.1"]
        or len(response_lines) != 1
        or not response_lines[0].startswith("< HTTP/1.1 200 ")
        or trace.count(expected_url) != 1
        or re.search(r"(?im)^< location:", trace) is not None
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID")
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for offset, character in enumerate(trace):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(trace, offset)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and set(value) == {"key_id", "key"}:
            candidates.append(value)
    if len(candidates) != 1:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID")
    key_id = candidates[0].get("key_id")
    encoded_key = candidates[0].get("key")
    if (
        not isinstance(key_id, str)
        or not 1 <= len(key_id) <= 256
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_=-"
            for character in key_id
        )
        or not isinstance(encoded_key, str)
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID")
    try:
        decoded_key = base64.b64decode(encoded_key, validate=True)
    except ValueError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID") from None
    if len(decoded_key) != 32:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID")
    return key_id


def _encrypt_secret_once(
    *,
    name: str,
    value: str,
    repository: str,
    environment: str,
    gh_cli_path: Path,
) -> tuple[str, str]:
    """Use the pinned CLI for one public-key GET and local encryption only."""

    try:
        with tempfile.TemporaryDirectory(prefix="robin-gh-config-v2-") as config_name:
            cli_environment = _github_cli_environment(
                config_dir=Path(config_name), require_token=True
            )
            cli_environment["GH_DEBUG"] = "api"
            completed = subprocess.run(  # nosec B603 - exact pinned binary and fixed argv.
                [
                    str(gh_cli_path),
                    "secret",
                    "set",
                    name,
                    "--repo",
                    f"{_GITHUB_HOST}/{repository}",
                    "--env",
                    environment,
                    "--no-store",
                ],
                input=value.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=_SECRET_ENCRYPT_TIMEOUT_SECONDS,
                env=cli_environment,
            )
    except (OSError, subprocess.SubprocessError):
        raise BindingInstallerV2Error(f"CHRONOS_BINDING_V2_WRITE_AMBIGUOUS:{name}") from None
    if not completed.stdout or len(completed.stdout) > _MAX_GH_ENCRYPT_OUTPUT_BYTES:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_ENCRYPTION_INVALID")
    try:
        encoded = completed.stdout.decode("ascii", errors="strict").strip()
        ciphertext = base64.b64decode(encoded, validate=True)
    except (UnicodeDecodeError, ValueError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_ENCRYPTION_INVALID") from None
    if len(ciphertext) != len(value.encode("utf-8")) + 48:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_ENCRYPTION_INVALID")
    return encoded, _public_key_trace(
        stderr=completed.stderr,
        repository=repository,
        environment=environment,
    )


def _put_encrypted_secret_direct(
    *,
    name: str,
    encrypted_value: str,
    key_id: str,
    repository: str,
    environment: str,
    token: str,
    external_deadline_epoch: float,
    external_deadline_monotonic: float,
) -> None:
    """Perform the child's one direct PUT with proxies and retries disabled."""

    if not token or len(token.encode("utf-8")) > 2_048:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    retries = Retry(
        total=0,
        connect=0,
        read=0,
        redirect=0,
        status=0,
        other=0,
        raise_on_redirect=True,
        respect_retry_after_header=False,
    )
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", HTTPAdapter(max_retries=retries))
    response: requests.Response | None = None
    try:
        _require_external_write_window(
            external_deadline_epoch,
            deadline_monotonic=external_deadline_monotonic,
            margin_seconds=_SECRET_PUT_WORK_TIMEOUT_SECONDS,
        )
        response = session.put(
            f"{_GITHUB_API_ROOT}/repos/{repository}/environments/{environment}/secrets/{name}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"encrypted_value": encrypted_value, "key_id": key_id},
            timeout=(4, 6),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code not in {201, 204}:
            raise BindingInstallerV2Error(f"CHRONOS_BINDING_V2_WRITE_AMBIGUOUS:{name}")
        _require_external_write_window(
            external_deadline_epoch,
            deadline_monotonic=external_deadline_monotonic,
            margin_seconds=0.0,
        )
    except requests.RequestException:
        raise BindingInstallerV2Error(f"CHRONOS_BINDING_V2_WRITE_AMBIGUOUS:{name}") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def _reservation_document(*, main_sha: str, preflight_run_id: str) -> dict[str, object]:
    return {
        "schema_version": "chronos-runtime-bindings-invocation-v2",
        "verdict": "INVOCATION_RESERVED",
        "main_sha": main_sha,
        "preflight_run_id": preflight_run_id,
        "effect_counter_certainty": "CONSERVATIVE_UPPER_BOUNDS",
        "secret_writes_attempted_upper_bound": 4,  # nosec B105
        "secret_writes_confirmed_upper_bound": 4,  # nosec B105
        "secret_names_in_order": list(BINDING_ORDER),
        "other_secret_writes": 0,  # nosec B105
        "secret_value_readbacks": 0,  # nosec B105
        "automatic_retries": 0,
        "secret_values_observed": False,  # nosec B105
    }


def _reservation_bytes(*, main_sha: str, preflight_run_id: str) -> bytes:
    return (
        json.dumps(
            _reservation_document(main_sha=main_sha, preflight_run_id=preflight_run_id),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _secret_put_worker(
    connection: Any,
    *,
    name: str,
    encrypted_value: str,
    key_id: str,
    repository: str,
    environment: str,
    token: str,
    expected_main_sha: str,
    expected_preflight_run_id: str,
    reservation_sha256: str,
    report_path: Path,
    external_deadline_epoch: float,
    external_deadline_monotonic: float,
) -> None:
    try:
        assert_production_safety_locks(os.environ)
        validate_data_torrent_recovery_v2_authority(scale_stage="E3A")
        expected_reservation = _reservation_bytes(
            main_sha=expected_main_sha,
            preflight_run_id=expected_preflight_run_id,
        )
        if (
            name not in BINDING_ORDER
            or repository != EXPECTED_REPOSITORY
            or environment != EXPECTED_ENVIRONMENT
            or not _same_path(report_path, CANONICAL_REPORT_PATH)
            or hashlib.sha256(expected_reservation).hexdigest() != reservation_sha256
        ):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_WRITE_INVALID")
        observed_reservation = _recovery_v2_evidence_bytes(
            report_path,
            repository_root=_REPOSITORY_ROOT,
            maximum_bytes=4 * 1024,
        )
        if (
            len(observed_reservation) > 4 * 1024
            or not hmac.compare_digest(observed_reservation, expected_reservation)
            or not hmac.compare_digest(
                hashlib.sha256(observed_reservation).hexdigest(),
                reservation_sha256,
            )
        ):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_WRITE_INVALID")
        _require_external_write_window(
            external_deadline_epoch,
            deadline_monotonic=external_deadline_monotonic,
            margin_seconds=_SECRET_PUT_WORK_TIMEOUT_SECONDS,
        )
        assert_current_main(repository=repository, main_sha=expected_main_sha)
        _require_external_write_window(
            external_deadline_epoch,
            deadline_monotonic=external_deadline_monotonic,
            margin_seconds=_SECRET_PUT_WORK_TIMEOUT_SECONDS,
        )
        _put_encrypted_secret_direct(
            name=name,
            encrypted_value=encrypted_value,
            key_id=key_id,
            repository=repository,
            environment=environment,
            token=token,
            external_deadline_epoch=external_deadline_epoch,
            external_deadline_monotonic=external_deadline_monotonic,
        )
        connection.send(("CONFIRMED", None))
    except Exception:
        try:
            connection.send(("FAILED", None))
        except (BrokenPipeError, EOFError, OSError):
            return
    finally:
        connection.close()


def _put_encrypted_secret_once(
    *,
    name: str,
    encrypted_value: str,
    key_id: str,
    repository: str,
    environment: str,
    expected_main_sha: str,
    expected_preflight_run_id: str,
    reservation_sha256: str,
    report_path: Path,
    external_deadline_epoch: float,
    external_deadline_monotonic: float,
) -> None:
    """Kill the disposable write child at one total deadline; never retry it."""

    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    encoded_request = json.dumps(
        {
            "name": name,
            "encrypted_value": encrypted_value,
            "key_id": key_id,
            "repository": repository,
            "environment": environment,
            "expected_main_sha": expected_main_sha,
            "expected_preflight_run_id": expected_preflight_run_id,
            "reservation_sha256": reservation_sha256,
            "report_path": str(report_path),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if (
        not token
        or len(token.encode("utf-8")) > 2_048
        or len(encoded_request) > _MAX_SECRET_PUT_PROCESS_INPUT_BYTES
    ):
        raise BindingInstallerV2Error(f"CHRONOS_BINDING_V2_WRITE_AMBIGUOUS:{name}")
    _require_external_write_window(
        external_deadline_epoch,
        deadline_monotonic=external_deadline_monotonic,
        margin_seconds=_SECRET_PUT_TOTAL_TIMEOUT_SECONDS,
    )
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_secret_put_worker,
        kwargs={
            "connection": sender,
            "name": name,
            "encrypted_value": encrypted_value,
            "key_id": key_id,
            "repository": repository,
            "environment": environment,
            "token": token,
            "expected_main_sha": expected_main_sha,
            "expected_preflight_run_id": expected_preflight_run_id,
            "reservation_sha256": reservation_sha256,
            "report_path": report_path,
            "external_deadline_epoch": external_deadline_epoch,
            "external_deadline_monotonic": external_deadline_monotonic,
        },
    )
    deadline = min(
        time.monotonic() + _SECRET_PUT_TOTAL_TIMEOUT_SECONDS,
        external_deadline_monotonic,
    )
    process.start()
    sender.close()
    process.join(min(_SECRET_PUT_WORK_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic())))
    if process.is_alive():
        process.terminate()
        process.join(min(2.0, max(0.0, deadline - time.monotonic())))
    if process.is_alive():
        process.kill()
        process.join(max(0.0, deadline - time.monotonic()))
    try:
        message = receiver.recv() if receiver.poll() else ("FAILED", None)
    except (EOFError, OSError):
        message = ("FAILED", None)
    receiver.close()
    exit_code = process.exitcode
    alive = process.is_alive()
    if not alive:
        process.close()
    deadline_crossed = (
        time.time() >= external_deadline_epoch
        or time.monotonic() >= external_deadline_monotonic
    )
    if alive or exit_code != 0 or message != ("CONFIRMED", None) or deadline_crossed:
        raise BindingInstallerV2Error(f"CHRONOS_BINDING_V2_WRITE_AMBIGUOUS:{name}") from None


def _set_secret(
    *,
    name: str,
    value: str,
    repository: str,
    environment: str,
    gh_cli_path: Path,
    expected_main_sha: str,
    expected_preflight_run_id: str,
    reservation_sha256: str,
    report_path: Path,
    external_deadline_epoch: float,
    external_deadline_monotonic: float,
) -> None:
    try:
        validate_data_torrent_recovery_v2_authority(scale_stage="E3A")
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_AUTHORITY_INVALID") from None
    if (
        name not in BINDING_ORDER
        or repository != EXPECTED_REPOSITORY
        or environment != EXPECTED_ENVIRONMENT
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_TARGET_FORBIDDEN")
    _require_external_write_window(
        external_deadline_epoch,
        deadline_monotonic=external_deadline_monotonic,
        margin_seconds=_SECRET_WRITE_TIMEOUT_SECONDS,
    )
    encrypted_value, key_id = _encrypt_secret_once(
        name=name,
        value=value,
        repository=repository,
        environment=environment,
        gh_cli_path=gh_cli_path,
    )
    _require_external_write_window(
        external_deadline_epoch,
        deadline_monotonic=external_deadline_monotonic,
        margin_seconds=_SECRET_PUT_TOTAL_TIMEOUT_SECONDS,
    )
    _put_encrypted_secret_once(
        name=name,
        encrypted_value=encrypted_value,
        key_id=key_id,
        repository=repository,
        environment=environment,
        expected_main_sha=expected_main_sha,
        expected_preflight_run_id=expected_preflight_run_id,
        reservation_sha256=reservation_sha256,
        report_path=report_path,
        external_deadline_epoch=external_deadline_epoch,
        external_deadline_monotonic=external_deadline_monotonic,
    )


def install(
    *,
    preflight_artifact: Path,
    expected_main_sha: str,
    expected_preflight_run_id: str,
    report_path: Path,
    repository: str = EXPECTED_REPOSITORY,
    environment: str = EXPECTED_ENVIRONMENT,
    observed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    hold_validator: Callable[[], None] | None = None,
    concurrency_validator: Callable[[], None] | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Perform four writes exactly; any ambiguous response is terminal."""

    stage_started = monotonic_clock()
    stage_deadline = stage_started + _STAGE_OUTER_TIMEOUT_SECONDS
    stage_started_epoch = wall_clock()
    stage_deadline_epoch = stage_started_epoch + _STAGE_OUTER_TIMEOUT_SECONDS
    try:
        assert_production_safety_locks(os.environ)
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_SAFETY_LOCK_INVALID") from None
    if repository != EXPECTED_REPOSITORY or environment != EXPECTED_ENVIRONMENT:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_TARGET_FORBIDDEN")
    try:
        expected_main_sha = require_sha(expected_main_sha, field="main_sha")
        nonce = require_hash(
            os.getenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", ""),
            field="generation_nonce",
        )
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GENERATION_NONCE_INVALID") from None
    if (
        not expected_preflight_run_id.isascii()
        or not expected_preflight_run_id.isdigit()
        or expected_preflight_run_id == "0"
        or len(expected_preflight_run_id) > 18
        or str(int(expected_preflight_run_id)) != expected_preflight_run_id
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_RUN_MISMATCH")
    if not _same_path(report_path, CANONICAL_REPORT_PATH):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_REPORT_PATH_FORBIDDEN")
    validate_data_torrent_recovery_v2_authority(scale_stage="E3A")
    try:
        _recovery_v2_prepare_repository_directory(
            report_path.parent,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_REPORT_PATH_FORBIDDEN") from None
    try:
        _recovery_v2_require_unused_repository_output(
            report_path,
            repository_root=_REPOSITORY_ROOT,
        )
    except ChronosProductionError:
        try:
            _recovery_v2_require_repository_file(
                report_path,
                repository_root=_REPOSITORY_ROOT,
            )
        except ChronosProductionError:
            raise BindingInstallerV2Error(
                "CHRONOS_BINDING_V2_REPORT_PATH_FORBIDDEN"
            ) from None
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_INVOCATION_ALREADY_CONSUMED") from None
    _require_canonical_preflight_cache_path(preflight_artifact)
    if (
        monotonic_clock() >= stage_deadline
        or wall_clock() >= stage_deadline_epoch
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED")
    payload, cached_attestation = _load_preflight_source(
        preflight_artifact,
        main_sha=expected_main_sha,
        run_id=expected_preflight_run_id,
    )
    try:
        preflight_controller_receipt_sha256 = validate_preflight_controller_handoff_v2(
            main_sha=expected_main_sha,
            run_id=expected_preflight_run_id,
            attestation=cached_attestation,
        )
        preflight_controller_receipt_sha256 = require_hash(
            preflight_controller_receipt_sha256,
            field="preflight_controller_receipt_sha256",
        )
    except RecoveryV2ControllerError:
        raise BindingInstallerV2Error(
            "CHRONOS_BINDING_V2_PREFLIGHT_CONTROLLER_INVALID"
        ) from None
    except ChronosProductionError:
        raise BindingInstallerV2Error(
            "CHRONOS_BINDING_V2_PREFLIGHT_CONTROLLER_INVALID"
        ) from None
    try:
        raw = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        artifact = validate_preflight_artifact_v2(raw, main_sha=expected_main_sha)
    except Exception:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID") from None
    if artifact.get("preflight_run_id") != expected_preflight_run_id:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_RUN_MISMATCH")
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > 2_048:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_GITHUB_TOKEN_MISSING")
    gh_cli_path = _require_pinned_gh_cli()
    try:
        created_at = datetime.fromisoformat(
            str(artifact["created_at"]).replace("Z", "+00:00")
        ).astimezone(UTC)
        expires_at = datetime.fromisoformat(
            str(artifact["expires_at"]).replace("Z", "+00:00")
        ).astimezone(UTC)
    except (KeyError, ValueError):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_INVALID") from None
    if observed_at is not None and clock is not None:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_CLOCK_CONFLICT")

    def require_unexpired(margin_seconds: float = 0.0) -> datetime:
        effective_now = (
            observed_at if observed_at is not None else (clock or (lambda: datetime.now(UTC)))()
        ).astimezone(UTC)
        if (
            margin_seconds < 0
            or created_at > effective_now
            or effective_now + timedelta(seconds=margin_seconds) >= expires_at
        ):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_PREFLIGHT_EXPIRED")
        return effective_now

    target = DirectPostgresTarget(
        host=str(artifact["database_host"]),
        port=int(artifact["database_port"]),
        database=str(artifact["database_name"]),
        username="bootstrap-placeholder",
        sslmode=str(artifact["sslmode"]),
        channel_binding=str(artifact["channel_binding"]),
    )
    nonce_hash = generation_hash(nonce)
    pending: list[tuple[str, str]] = []
    for name, login in BINDINGS:
        password = build_generation_bound_password(
            nonce_hex=nonce,
            entropy=secrets.token_urlsafe(48),
        )
        pending.append((name, build_scoped_database_url(target, username=login, password=password)))
    pending.append(("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", nonce))
    admission_now = require_unexpired(_FULL_EFFECT_SCHEDULE_SECONDS)
    if (
        monotonic_clock() + _FULL_EFFECT_SCHEDULE_SECONDS >= stage_deadline
        or wall_clock() + _FULL_EFFECT_SCHEDULE_SECONDS >= stage_deadline_epoch
    ):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED")
    reservation = _reservation_bytes(
        main_sha=expected_main_sha,
        preflight_run_id=expected_preflight_run_id,
    )
    reservation_sha256 = hashlib.sha256(reservation).hexdigest()
    _write_report(report_path, reservation, exclusive=True)
    attestation = cached_attestation
    if hashlib.sha256(payload).hexdigest() != attestation.get("payload_sha256"):
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_ATTESTATION_HASH_MISMATCH")
    attempted: list[str] = []
    confirmed: list[str] = []
    signed_report: dict[str, Any] | None = None
    validate_hold = hold_validator or (
        lambda: _validate_global_hold(repository=repository, main_sha=expected_main_sha)
    )
    validate_concurrency = concurrency_validator or (
        lambda: _validate_no_concurrent_runs(repository=repository)
    )
    effect_started = monotonic_clock()
    effect_deadline = min(
        effect_started + _EFFECT_ADMISSION_DEADLINE_SECONDS,
        stage_deadline,
    )
    effect_deadline_epoch = min(
        wall_clock() + _EFFECT_ADMISSION_DEADLINE_SECONDS,
        stage_deadline_epoch,
    )
    remaining_preflight_seconds = max(0.0, (expires_at - admission_now).total_seconds())
    preflight_deadline_monotonic = effect_started + remaining_preflight_seconds
    preflight_deadline_epoch = wall_clock() + remaining_preflight_seconds
    external_write_deadline_monotonic = min(
        effect_deadline,
        preflight_deadline_monotonic,
    )
    external_write_deadline_epoch = min(
        effect_deadline_epoch,
        preflight_deadline_epoch,
    )
    full_hold_attempts = 0
    full_hold_confirmed = 0
    concurrency_attempts = 0
    concurrency_confirmed = 0
    def require_operation_time(margin_seconds: float) -> None:
        if (
            monotonic_clock() + margin_seconds >= external_write_deadline_monotonic
            or wall_clock() + margin_seconds >= external_write_deadline_epoch
        ):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED")

    def require_stage_time(margin_seconds: float = 0.0) -> None:
        if (
            monotonic_clock() + margin_seconds >= stage_deadline
            or wall_clock() + margin_seconds >= stage_deadline_epoch
        ):
            raise BindingInstallerV2Error("CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED")

    def run_full_hold() -> None:
        nonlocal full_hold_attempts, full_hold_confirmed
        full_hold_attempts += 1
        validate_hold()
        full_hold_confirmed += 1

    def run_concurrency_inventory() -> None:
        nonlocal concurrency_attempts, concurrency_confirmed
        concurrency_attempts += 1
        validate_concurrency()
        concurrency_confirmed += 1

    try:
        require_stage_time(
            _FULL_HOLD_MAX_SECONDS
            + _remaining_effect_schedule_seconds(writes_remaining=len(pending))
        )
        require_operation_time(
            _FULL_HOLD_MAX_SECONDS
            + _remaining_effect_schedule_seconds(writes_remaining=len(pending))
        )
        run_full_hold()
        for index, (name, value) in enumerate(pending):
            writes_remaining = len(pending) - index
            require_unexpired()
            require_operation_time(
                _remaining_effect_schedule_seconds(writes_remaining=writes_remaining)
            )
            run_concurrency_inventory()
            require_unexpired(_SECRET_WRITE_TIMEOUT_SECONDS)
            require_operation_time(
                _SECRET_WRITE_TIMEOUT_SECONDS
                + _remaining_effect_schedule_seconds(writes_remaining=writes_remaining - 1)
            )
            attempted.append(name)
            _set_secret(
                name=name,
                value=value,
                repository=repository,
                environment=environment,
                gh_cli_path=gh_cli_path,
                expected_main_sha=expected_main_sha,
                expected_preflight_run_id=expected_preflight_run_id,
                reservation_sha256=reservation_sha256,
                report_path=report_path,
                external_deadline_epoch=external_write_deadline_epoch,
                external_deadline_monotonic=external_write_deadline_monotonic,
            )
            confirmed.append(name)
        require_operation_time(_FULL_HOLD_MAX_SECONDS + _EFFECT_SAFETY_MARGIN_SECONDS)
        run_full_hold()
        require_operation_time(_EFFECT_SAFETY_MARGIN_SECONDS)
        require_stage_time(_EFFECT_SAFETY_MARGIN_SECONDS)
        installed_at = require_unexpired()
        report = {
            "schema_version": "chronos-runtime-bindings-v2",
            "verdict": "FOUR_RUNTIME_BINDINGS_INSTALLED_V2",
            "repository": repository,
            "environment": environment,
            "main_sha": expected_main_sha,
            "preflight_run_id": expected_preflight_run_id,
            "preflight_hash": artifact["preflight_hash"],
            "preflight_controller_receipt_sha256": preflight_controller_receipt_sha256,
            "secret_writes_attempted": 4,  # nosec B105 - numeric audit counter.
            "secret_writes_confirmed": 4,  # nosec B105 - numeric audit counter.
            "secret_names_in_order": confirmed,
            "secret_value_readbacks": 0,  # nosec B105 - numeric audit counter.
            "automatic_retries": 0,
            "global_hold_full_validations": full_hold_confirmed,
            "concurrent_run_inventory_validations": concurrency_confirmed,
            "github_api_gets_upper_bound": (
                _CACHED_ATTESTATION_CONTRACTUAL_GET_RESERVE
                + _MAIN_REF_GITHUB_GETS
                + full_hold_confirmed * _FULL_HOLD_GITHUB_GETS
                + concurrency_confirmed * _CONCURRENCY_GITHUB_GETS
                + len(confirmed) * _SECRET_PUBLIC_KEY_GITHUB_GETS
            ),
            "github_api_gets_exact": False,
            "github_cli_version": _PINNED_GH_CLI_VERSION,
            "github_cli_sha256": _PINNED_GH_CLI_SHA256,
            "effect_admission_deadline_seconds": int(_EFFECT_ADMISSION_DEADLINE_SECONDS),
            "stage_outer_timeout_seconds": int(_STAGE_OUTER_TIMEOUT_SECONDS),
            "generation_hash": nonce_hash,
            "installed_at": installed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "secret_values_observed": False,  # nosec B105 - boolean audit field.
        }
        signed_report = sign_document(report, nonce)
        _write_report(
            report_path,
            (json.dumps(signed_report, sort_keys=True) + "\n").encode("utf-8"),
            exclusive=False,
        )
    except BindingInstallerV2Error:
        failure = {
            "schema_version": "chronos-runtime-bindings-failure-v2",
            "verdict": "FAIL_AND_STOP",
            "main_sha": expected_main_sha,
            "preflight_run_id": expected_preflight_run_id,
            "preflight_hash": artifact["preflight_hash"],
            "preflight_controller_receipt_sha256": preflight_controller_receipt_sha256,
            "secret_writes_attempted": len(attempted),
            "secret_writes_confirmed": len(confirmed),
            "secret_names_attempted": attempted,
            "secret_value_readbacks": 0,  # nosec B105 - numeric audit counter.
            "automatic_retries": 0,
            "global_hold_validations_attempted": full_hold_attempts,
            "global_hold_validations_confirmed": full_hold_confirmed,
            "concurrent_run_inventory_validations_attempted": concurrency_attempts,
            "concurrent_run_inventory_validations_confirmed": concurrency_confirmed,
            "github_api_gets_upper_bound": (
                _CACHED_ATTESTATION_CONTRACTUAL_GET_RESERVE
                + _MAIN_REF_GITHUB_GETS
                + full_hold_attempts * _FULL_HOLD_GITHUB_GETS
                + concurrency_attempts * _CONCURRENCY_GITHUB_GETS
                + len(attempted) * _SECRET_PUBLIC_KEY_GITHUB_GETS
            ),
            "github_api_gets_exact": False,
            "github_cli_version": _PINNED_GH_CLI_VERSION if gh_cli_path is not None else None,
            "github_cli_sha256": _PINNED_GH_CLI_SHA256 if gh_cli_path is not None else None,
            "effect_outcome_ambiguous": len(attempted) > len(confirmed),
            "secret_values_observed": False,  # nosec B105 - boolean audit field.
        }
        _write_report(
            report_path,
            (json.dumps(failure, sort_keys=True) + "\n").encode("utf-8"),
            exclusive=False,
        )
        raise
    finally:
        for index, (name, _value) in enumerate(pending):
            pending[index] = (name, "")
        nonce = ""
    if signed_report is None:
        raise BindingInstallerV2Error("CHRONOS_BINDING_V2_RECEIPT_MISSING")
    return signed_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-artifact", type=Path, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--expected-preflight-run-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        install(
            preflight_artifact=args.preflight_artifact,
            expected_main_sha=args.expected_main_sha,
            expected_preflight_run_id=args.expected_preflight_run_id,
            report_path=args.report,
        )
    except Exception as error:
        print(
            str(error)
            if isinstance(error, BindingInstallerV2Error)
            else "CHRONOS_BINDING_V2_FAILED"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
