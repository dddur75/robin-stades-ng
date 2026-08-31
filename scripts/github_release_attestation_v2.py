"""Attest exact first-attempt GitHub artifacts, including archive and payload hashes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import multiprocessing
import os
import re
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from robin.chronos_production import (
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    canonical_json_bytes,
    require_sha,
)

_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_MAX_BYTES = 10 * 1024 * 1024
_MAX_TOKEN_BYTES = 2_048
_API_CHILD_TOTAL_TIMEOUT_SECONDS = 65.0
_API_CHILD_WORK_TIMEOUT_SECONDS = 55.0
_API_CHILD_TERMINATE_TIMEOUT_SECONDS = 5.0
_GITHUB_API_ROOT = "https://api.github.com/"
_GITHUB_API_VERSION = "2026-03-10"
_ARTIFACT_HOST_SUFFIXES = (
    ".actions.githubusercontent.com",
    ".blob.core.windows.net",
)
_RUN_API_PATH = re.compile(
    rf"^repos/{re.escape(EXPECTED_REPOSITORY)}/actions/runs/"
    r"[1-9][0-9]{0,17}(?:/artifacts\?per_page=100)?$"
)
_ARTIFACT_API_PATH = re.compile(
    rf"^repos/{re.escape(EXPECTED_REPOSITORY)}/actions/artifacts/"
    r"[1-9][0-9]{0,17}/zip$"
)
_MAIN_REF_API_PATH = f"repos/{EXPECTED_REPOSITORY}/git/ref/heads/main"
_MAX_BUNDLE_MEMBERS = 64
_FAILURE_ARTIFACTS = {
    "RECOVERY_IDENTITY_V2": (
        ".github/workflows/chronos-neon-branch-identity-v2.yml",
        "neon-branch-identity-go-v2-",
        "neon-branch-identity-go-v2.json",
    ),
    "DURABLE_IDENTITY_SEAL_V2": (
        ".github/workflows/chronos-identity-seal-v2.yml",
        "durable-identity-seal-v2-",
        "durable-identity-seal-v2.json",
    ),
    "PRODUCTION_PREFLIGHT_V2": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "production-preflight-v2-",
        "production-preflight-v2.json",
    ),
    "MIGRATE_0015": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "chronos-production-migrate-v2-",
        "chronos-production-migrate-v2.json",
    ),
    "VERIFY_0015": (
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        "chronos-production-verify-v2-",
        "chronos-production-verify-v2.json",
    ),
    "LIVE_ONCE": (
        ".github/workflows/data-torrent-live-v2.yml",
        "data-torrent-live-v2-",
        "torrent-run-failure-v2.json",
    ),
}


class GitHubReleaseAttestationV2Error(RuntimeError):
    """Sanitized V2 release-attestation error."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _content_lengths(response: requests.Response) -> list[str]:
    raw_headers = getattr(response.raw, "headers", None)
    getlist = getattr(raw_headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist("Content-Length")]
    value = response.headers.get("Content-Length")
    return [] if value is None else [value]


def _bounded_body(response: requests.Response) -> bytes:
    lengths = _content_lengths(response)
    if len(lengths) > 1:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
    declared: int | None = None
    if lengths:
        try:
            declared = int(lengths[0])
        except ValueError:
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID") from None
        if declared < 0 or declared > _MAX_BYTES:
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_RESPONSE_TOO_LARGE")
    if response.headers.get("Content-Encoding", "identity").casefold() != "identity":
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not isinstance(chunk, bytes):
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
        body.extend(chunk)
        if len(body) > _MAX_BYTES:
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_RESPONSE_TOO_LARGE")
    if declared is not None and declared != len(body):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
    return bytes(body)


def _artifact_location(value: str) -> str:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path
        or parsed.fragment
        or not any(hostname.endswith(suffix) for suffix in _ARTIFACT_HOST_SUFFIXES)
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_REDIRECT_INVALID")
    return value


def _effect_timeout(
    effect_deadline_epoch: float | None,
    *,
    maximum: float,
    effect_deadline_monotonic: float | None = None,
) -> float:
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, (int, float))
        or not math.isfinite(float(maximum))
        or maximum <= 0
        or (
            effect_deadline_epoch is not None
            and (
                isinstance(effect_deadline_epoch, bool)
                or not isinstance(effect_deadline_epoch, (int, float))
                or not math.isfinite(float(effect_deadline_epoch))
            )
        )
        or (
            effect_deadline_monotonic is not None
            and (
                isinstance(effect_deadline_monotonic, bool)
                or not isinstance(effect_deadline_monotonic, (int, float))
                or not math.isfinite(float(effect_deadline_monotonic))
            )
        )
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_DEADLINE_INVALID")
    remaining = float(maximum)
    if effect_deadline_epoch is not None:
        remaining = min(remaining, float(effect_deadline_epoch) - time.time())
    if effect_deadline_monotonic is not None:
        remaining = min(
            remaining,
            float(effect_deadline_monotonic) - time.monotonic(),
        )
    if remaining <= 0:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_DEADLINE_EXCEEDED")
    return remaining


def _api_direct(
    path: str,
    *,
    token: str,
    binary: bool,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> bytes:
    """One proxy-free streaming API read; archive redirects are narrowly pinned."""

    session = requests.Session()
    session.trust_env = False
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
    session.mount("https://", HTTPAdapter(max_retries=retries))
    response: requests.Response | None = None
    try:
        remaining = _effect_timeout(
            effect_deadline_epoch,
            maximum=15.0,
            effect_deadline_monotonic=effect_deadline_monotonic,
        )
        response = session.get(
            _GITHUB_API_ROOT + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            },
            timeout=(min(5.0, remaining), min(10.0, remaining)),
            allow_redirects=False,
            stream=True,
        )
        if binary:
            if response.status_code != 302:
                raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_FAILED")
            location = _artifact_location(response.headers.get("Location", ""))
            response.close()
            remaining = _effect_timeout(
                effect_deadline_epoch,
                maximum=15.0,
                effect_deadline_monotonic=effect_deadline_monotonic,
            )
            response = session.get(
                location,
                headers={"Accept-Encoding": "identity"},
                timeout=(min(5.0, remaining), min(10.0, remaining)),
                allow_redirects=False,
                stream=True,
            )
        if response.status_code != 200:
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_FAILED")
        return _bounded_body(response)
    except requests.RequestException:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_FAILED") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def _api_worker(
    connection: Any,
    *,
    path: str,
    token: str,
    binary: bool,
    effect_deadline_epoch: float | None,
    effect_deadline_monotonic: float | None,
) -> None:
    try:
        body = _api_direct(
            path,
            token=token,
            binary=binary,
            effect_deadline_epoch=effect_deadline_epoch,
            effect_deadline_monotonic=effect_deadline_monotonic,
        )
        connection.send(("CONFIRMED", body))
    except Exception:
        connection.send(("FAILED", b""))
    finally:
        connection.close()


def _api(
    path: str,
    *,
    binary: bool = False,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> bytes | dict[str, Any]:
    path_valid = (
        _ARTIFACT_API_PATH.fullmatch(path) is not None
        if binary
        else path == _MAIN_REF_API_PATH or _RUN_API_PATH.fullmatch(path) is not None
    )
    if not path_valid:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_TOKEN_INVALID")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_api_worker,
        kwargs={
            "connection": sender,
            "path": path,
            "token": token,
            "binary": binary,
            "effect_deadline_epoch": effect_deadline_epoch,
            "effect_deadline_monotonic": effect_deadline_monotonic,
        },
    )
    total_timeout = _effect_timeout(
        effect_deadline_epoch,
        maximum=_API_CHILD_TOTAL_TIMEOUT_SECONDS,
        effect_deadline_monotonic=effect_deadline_monotonic,
    )
    deadline = time.monotonic() + total_timeout
    process.start()
    sender.close()
    message: tuple[str, bytes] = ("FAILED", b"")
    try:
        if receiver.poll(
            min(
                _API_CHILD_WORK_TIMEOUT_SECONDS,
                max(0.0, deadline - time.monotonic()),
            )
        ):
            received = receiver.recv()
            if (
                isinstance(received, tuple)
                and len(received) == 2
                and isinstance(received[0], str)
                and isinstance(received[1], bytes)
            ):
                message = received
    except (EOFError, OSError):
        message = ("FAILED", b"")
    if message[0] == "CONFIRMED":
        process.join(max(0.0, deadline - time.monotonic()))
    if process.is_alive():
        process.terminate()
        process.join(
            min(
                _API_CHILD_TERMINATE_TIMEOUT_SECONDS,
                max(0.0, deadline - time.monotonic()),
            )
        )
    if process.is_alive():
        process.kill()
        process.join(max(0.0, deadline - time.monotonic()))
    receiver.close()
    exit_code = process.exitcode
    if not process.is_alive():
        process.close()
    deadline_crossed = (
        effect_deadline_epoch is not None and time.time() >= effect_deadline_epoch
    ) or (
        effect_deadline_monotonic is not None
        and time.monotonic() >= effect_deadline_monotonic
    )
    if exit_code != 0 or message[0] != "CONFIRMED" or deadline_crossed:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_FAILED") from None
    body = message[1]
    if len(body) > _MAX_BYTES:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_RESPONSE_TOO_LARGE")
    if binary:
        return body
    try:
        document = json.loads(body, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID") from None
    if not isinstance(document, dict):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_API_INVALID")
    return cast(dict[str, Any], document)


def exact_main_sha_v2(
    *,
    repository: str = EXPECTED_REPOSITORY,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> str:
    """Read the canonical main ref once through the bounded direct child."""

    if repository != EXPECTED_REPOSITORY:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
    document = cast(
        dict[str, Any],
        _api(
            f"repos/{repository}/git/ref/heads/main",
            effect_deadline_epoch=effect_deadline_epoch,
            effect_deadline_monotonic=effect_deadline_monotonic,
        ),
    )
    target = document.get("object")
    if (
        document.get("ref") != "refs/heads/main"
        or not isinstance(target, dict)
        or target.get("type") != "commit"
        or not isinstance(target.get("sha"), str)
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_MAIN_REF_INVALID")
    try:
        return require_sha(cast(str, target["sha"]), field="main_sha")
    except ChronosProductionError:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_MAIN_REF_INVALID") from None


def _attested_archive_v2(
    *,
    repository: str,
    workflow_path: str,
    run_id: str,
    main_sha: str,
    artifact_name: str,
    expected_conclusion: Literal["success", "failure"],
    require_only_artifact: bool = False,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> tuple[str, int, bytes, str, str]:
    """Return one bounded archive after proving one exact terminal run."""

    try:
        expected_sha = require_sha(main_sha, field="main_sha")
    except ChronosProductionError:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID") from None
    if (
        repository != EXPECTED_REPOSITORY
        or _RUN_ID.fullmatch(run_id) is None
        or not workflow_path.startswith(".github/workflows/")
        or not workflow_path.endswith((".yml", ".yaml"))
        or not artifact_name
        or expected_conclusion not in {"success", "failure"}
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
    run = cast(
        dict[str, Any],
        _api(
            f"repos/{repository}/actions/runs/{run_id}",
            effect_deadline_epoch=effect_deadline_epoch,
            effect_deadline_monotonic=effect_deadline_monotonic,
        ),
    )
    run_repository = run.get("repository")
    run_completed_observed_at = run.get("updated_at")
    completed: datetime | None = None
    if isinstance(run_completed_observed_at, str):
        try:
            completed = datetime.fromisoformat(
                run_completed_observed_at.replace("Z", "+00:00")
            )
        except ValueError:
            completed = None
    if (
        type(run.get("id")) is not int
        or run.get("id") != int(run_id)
        or type(run.get("run_attempt")) is not int
        or run.get("run_attempt") != 1
        or run.get("head_sha") != expected_sha
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != expected_conclusion
        or not isinstance(run_completed_observed_at, str)
        or not run_completed_observed_at.endswith("Z")
        or completed is None
        or completed.utcoffset() != UTC.utcoffset(completed)
        or completed.isoformat(timespec="seconds").replace("+00:00", "Z")
        != run_completed_observed_at
        or run.get("path") != workflow_path
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != repository
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_RUN_MISMATCH")
    listing = cast(
        dict[str, Any],
        _api(
            f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
            effect_deadline_epoch=effect_deadline_epoch,
            effect_deadline_monotonic=effect_deadline_monotonic,
        ),
    )
    artifacts = listing.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or type(listing.get("total_count")) is not int
        or listing.get("total_count") != len(artifacts)
        or len(artifacts) > 100
        or (require_only_artifact and len(artifacts) != 1)
        or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_LIST_INVALID")
    matches = [
        item for item in artifacts if isinstance(item, dict) and item.get("name") == artifact_name
    ]
    if len(matches) != 1:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARTIFACT_MISMATCH")
    artifact = cast(dict[str, Any], matches[0])
    artifact_id = artifact.get("id")
    workflow_run = artifact.get("workflow_run")
    if (
        type(artifact_id) is not int
        or artifact_id < 1
        or artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < cast(int, artifact["size_in_bytes"]) <= _MAX_BYTES
        or not isinstance(workflow_run, dict)
        or type(workflow_run.get("id")) is not int
        or workflow_run.get("id") != int(run_id)
        or workflow_run.get("head_sha") != expected_sha
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARTIFACT_MISMATCH")
    archive = cast(
        bytes,
        _api(
            f"repos/{repository}/actions/artifacts/{artifact_id}/zip",
            binary=True,
            effect_deadline_epoch=effect_deadline_epoch,
            effect_deadline_monotonic=effect_deadline_monotonic,
        ),
    )
    archive_sha = hashlib.sha256(archive).hexdigest()
    server_digest = artifact.get("digest")
    if len(archive) != artifact["size_in_bytes"]:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARCHIVE_SIZE_MISMATCH")
    if server_digest != f"sha256:{archive_sha}":
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARCHIVE_DIGEST_MISMATCH")
    return expected_sha, artifact_id, archive, archive_sha, run_completed_observed_at


def _attest_and_download_file_v2(
    *,
    repository: str,
    workflow_path: str,
    run_id: str,
    main_sha: str,
    artifact_name: str,
    artifact_filename: str,
    output_path: Path,
    expected_conclusion: Literal["success", "failure"],
    publish: bool = True,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Download exactly one file from one immutable terminal workflow artifact."""

    if (
        not artifact_filename
        or "\\" in artifact_filename
        or PurePosixPath(artifact_filename).name != artifact_filename
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
    expected_sha, artifact_id, archive, archive_sha, completed_at = _attested_archive_v2(
        repository=repository,
        workflow_path=workflow_path,
        run_id=run_id,
        main_sha=main_sha,
        artifact_name=artifact_name,
        expected_conclusion=expected_conclusion,
        require_only_artifact=True,
        effect_deadline_epoch=effect_deadline_epoch,
        effect_deadline_monotonic=effect_deadline_monotonic,
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if (
                len(members) != 1
                or members[0].is_dir()
                or "\\" in members[0].filename
                or PurePosixPath(members[0].filename).is_absolute()
                or members[0].filename != artifact_filename
            ):
                raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_FILE_MISMATCH")
            if members[0].file_size <= 0 or members[0].file_size > _MAX_BYTES:
                raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_FILE_INVALID")
            payload = bundle.read(members[0])
    except GitHubReleaseAttestationV2Error:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARCHIVE_INVALID") from None
    if publish:
        _publish_payload_v2(output_path, payload)
    report = {
        "schema_version": "github-artifact-attestation-v2",
        "repository": repository,
        "workflow_path": workflow_path,
        "run_id": run_id,
        "run_attempt": "1",
        "head_sha": expected_sha,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "archive_sha256": archive_sha,
    }
    if expected_conclusion == "failure":
        report.update(
            {
                "schema_version": "github-artifact-failure-attestation-v2",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "main",
                "event": "workflow_dispatch",
                "run_completed_observed_at": completed_at,
                "artifact_filename": artifact_filename,
            }
        )
    if not publish:
        report["_payload"] = payload
    return report


def _publish_payload_v2(output_path: Path, payload: bytes) -> None:
    """Publish validated bytes once without overwriting an existing receipt."""

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except (FileExistsError, OSError):
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_OUTPUT_INVALID"
        ) from None


def _strict_failure_document_v2(payload: bytes) -> dict[str, Any]:
    if not payload or len(payload) > 1_048_576 or b"\x00" in payload or b"\r" in payload:
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        )
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        ) from None
    if not isinstance(document, dict):
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        )
    return cast(dict[str, Any], document)


def _validate_failure_payload_v2(
    *,
    stage: str,
    payload: bytes,
    main_sha: str,
) -> dict[str, Any]:
    """Validate ordinary failures and require byte-exact supervisor fallbacks."""

    document = _strict_failure_document_v2(payload)
    schema = document.get("schema_version")
    expected_fallback: dict[str, Any] | dict[str, object] | None = None
    if stage == "RECOVERY_IDENTITY_V2" and document.get(
        "effect_counter_certainty"
    ) == "UNKNOWN_OR_UPPER_BOUND":
        from scripts.chronos_neon_branch_identity_v2 import (
            IdentityExecutionState,
            _failure_report,
        )

        observed_at = document.get("observed_at")
        if not isinstance(observed_at, str):
            raise GitHubReleaseAttestationV2Error(
                "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
            )
        try:
            parsed_observed_at = datetime.fromisoformat(
                observed_at.replace("Z", "+00:00")
            )
        except ValueError:
            raise GitHubReleaseAttestationV2Error(
                "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
            ) from None
        if (
            not observed_at.endswith("Z")
            or parsed_observed_at.utcoffset() != UTC.utcoffset(parsed_observed_at)
            or parsed_observed_at.isoformat(timespec="seconds").replace("+00:00", "Z")
            != observed_at
        ):
            raise GitHubReleaseAttestationV2Error(
                "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
            )
        expected_fallback = _failure_report(
            RuntimeError("TRANSPORT_AMBIGUOUS"),
            IdentityExecutionState(),
            conservative_timeout=True,
            observed_at=observed_at,
        )
    elif stage == "DURABLE_IDENTITY_SEAL_V2" and schema == (
        "durable-identity-seal-supervisor-failure-v2"
    ):
        from scripts.seal_chronos_identity_go_v2 import (
            _supervisor_fallback as seal_supervisor_fallback,
        )

        expected_fallback = seal_supervisor_fallback()
    elif stage in {"PRODUCTION_PREFLIGHT_V2", "MIGRATE_0015", "VERIFY_0015"} and schema == (
        "chronos-production-recovery-supervisor-failure-v2"
    ):
        from scripts.chronos_production_recovery_v2 import (
            _supervisor_fallback as bootstrap_supervisor_fallback,
        )

        mode = {
            "PRODUCTION_PREFLIGHT_V2": "PREFLIGHT",
            "MIGRATE_0015": "MIGRATE",
            "VERIFY_0015": "VERIFY",
        }[stage]
        expected_fallback = bootstrap_supervisor_fallback(mode)
    elif stage == "LIVE_ONCE" and schema == "robin-data-torrent-run-supervisor-failure-v2":
        from scripts.run_data_torrent_v2 import (
            _supervisor_fallback as live_supervisor_fallback,
        )

        expected_fallback = live_supervisor_fallback()
    if expected_fallback is not None and payload != canonical_json_bytes(expected_fallback) + b"\n":
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        )

    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="recovery-v2-failure-validation-") as raw:
            candidate = Path(raw) / "failure.json"
            candidate.write_bytes(payload)
            if stage == "RECOVERY_IDENTITY_V2":
                from scripts.chronos_live_path_artifact_guard_v2 import load_guarded_report

                failure = load_guarded_report(candidate, expected_main_sha=main_sha)
                if failure.get("verdict") != "NEON_BRANCH_IDENTITY_NO_GO_V2":
                    raise ChronosProductionError("unexpected identity success")
            elif stage == "DURABLE_IDENTITY_SEAL_V2":
                from scripts.chronos_live_path_artifact_guard_v2 import load_guarded_seal

                failure = load_guarded_seal(
                    candidate,
                    expected_main_sha=main_sha,
                    expected_identity_run_id="1",
                )
                if failure.get("verdict") != "DURABLE_IDENTITY_SEAL_FAILED_V2":
                    raise ChronosProductionError("unexpected seal success")
            elif stage in {"PRODUCTION_PREFLIGHT_V2", "MIGRATE_0015", "VERIFY_0015"}:
                from scripts.chronos_production_recovery_v2 import _load_supervised_export

                mode = {
                    "PRODUCTION_PREFLIGHT_V2": "PREFLIGHT",
                    "MIGRATE_0015": "MIGRATE",
                    "VERIFY_0015": "VERIFY",
                }[stage]
                failure = _load_supervised_export(candidate, mode=mode)
                if failure.get("status") != "FAILED":
                    raise ChronosProductionError("unexpected bootstrap success")
            elif stage == "LIVE_ONCE":
                from scripts.run_data_torrent_v2 import _load_guarded_failure

                failure = _load_guarded_failure(candidate)
                if failure.get("status") != "FAILED":
                    raise ChronosProductionError("unexpected live success")
            else:
                raise ChronosProductionError("unexpected stage")
    except GitHubReleaseAttestationV2Error:
        raise
    except Exception:
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        ) from None
    return failure


def attest_and_download_v2(
    *,
    repository: str,
    workflow_path: str,
    run_id: str,
    main_sha: str,
    artifact_name: str,
    artifact_filename: str,
    output_path: Path,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Download exactly one file from one immutable successful workflow artifact."""

    return _attest_and_download_file_v2(
        repository=repository,
        workflow_path=workflow_path,
        run_id=run_id,
        main_sha=main_sha,
        artifact_name=artifact_name,
        artifact_filename=artifact_filename,
        output_path=output_path,
        expected_conclusion="success",
        effect_deadline_epoch=effect_deadline_epoch,
        effect_deadline_monotonic=effect_deadline_monotonic,
    )


def attest_and_download_failure_v2(
    *,
    stage: str,
    run_id: str,
    main_sha: str,
    output_path: Path,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Attest one exact failed first attempt and validate its bounded failure receipt."""

    mapping = _FAILURE_ARTIFACTS.get(stage)
    if mapping is None:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
    workflow_path, artifact_prefix, artifact_filename = mapping
    attestation = _attest_and_download_file_v2(
        repository=EXPECTED_REPOSITORY,
        workflow_path=workflow_path,
        run_id=run_id,
        main_sha=main_sha,
        artifact_name=artifact_prefix + run_id,
        artifact_filename=artifact_filename,
        output_path=output_path,
        expected_conclusion="failure",
        publish=False,
        effect_deadline_epoch=effect_deadline_epoch,
        effect_deadline_monotonic=effect_deadline_monotonic,
    )
    payload = attestation.pop("_payload", None)
    if not isinstance(payload, bytes):
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        )
    try:
        failure = _validate_failure_payload_v2(
            stage=stage,
            payload=payload,
            main_sha=main_sha,
        )
        effects = failure.get("effects")
        semantic_verdict = failure.get("verdict", failure.get("status"))
        if not isinstance(effects, dict) or not isinstance(semantic_verdict, str):
            raise ChronosProductionError("failure evidence missing")
        failure_class = failure.get(
            "failure_class",
            failure.get("branch_inventory_failure_class", failure.get("error_code")),
        )
        effect_counter_certainty = failure.get(
            "effect_counter_certainty",
            effects.get("effect_counter_certainty"),
        )
        if (
            not isinstance(failure_class, str)
            or not isinstance(effect_counter_certainty, str)
            or failure.get("secret_values_observed") is not False
        ):
            raise ChronosProductionError("failure evidence incomplete")
    except GitHubReleaseAttestationV2Error:
        raise
    except Exception:
        raise GitHubReleaseAttestationV2Error(
            "GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID"
        ) from None
    _publish_payload_v2(output_path, payload)
    return {
        **attestation,
        "stage": stage,
        "failure_payload_schema_version": failure["schema_version"],
        "semantic_verdict": semantic_verdict,
        "failure_class": failure_class,
        "effect_counter_certainty": effect_counter_certainty,
        "secret_values_observed": False,  # nosec B105
        "effect_counters": effects,
    }


def attest_and_download_bundle_v2(
    *,
    repository: str,
    workflow_path: str,
    run_id: str,
    main_sha: str,
    artifact_name: str,
    expected_filenames: tuple[str, ...],
    output_dir: Path,
    effect_deadline_epoch: float | None = None,
    effect_deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Download one exact flat bundle and bind every member to its payload hash."""

    if (
        not expected_filenames
        or len(expected_filenames) > _MAX_BUNDLE_MEMBERS
        or tuple(sorted(set(expected_filenames))) != expected_filenames
        or any(
            not name
            or "\\" in name
            or PurePosixPath(name).name != name
            or PurePosixPath(name).is_absolute()
            for name in expected_filenames
        )
    ):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
    expected_sha, artifact_id, archive, archive_sha, run_completed_observed_at = (
        _attested_archive_v2(
        repository=repository,
        workflow_path=workflow_path,
        run_id=run_id,
        main_sha=main_sha,
        artifact_name=artifact_name,
        expected_conclusion="success",
        require_only_artifact=True,
        effect_deadline_epoch=effect_deadline_epoch,
        effect_deadline_monotonic=effect_deadline_monotonic,
        )
    )
    payloads: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            names = tuple(sorted(member.filename for member in members))
            if (
                len(members) != len(expected_filenames)
                or names != expected_filenames
                or len(names) != len(set(names))
                or any(
                    member.is_dir()
                    or "\\" in member.filename
                    or PurePosixPath(member.filename).is_absolute()
                    or PurePosixPath(member.filename).name != member.filename
                    or member.flag_bits & 0x1
                    or member.file_size <= 0
                    or member.file_size > _MAX_BYTES
                    for member in members
                )
                or sum(member.file_size for member in members) > _MAX_BYTES
            ):
                raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_FILE_MISMATCH")
            for member in members:
                payload = bundle.read(member)
                if len(payload) != member.file_size:
                    raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARCHIVE_INVALID")
                payloads[member.filename] = payload
    except GitHubReleaseAttestationV2Error:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_ARCHIVE_INVALID") from None
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
        for filename in expected_filenames:
            (output_dir / filename).write_bytes(payloads[filename])
    except OSError:
        raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_OUTPUT_INVALID") from None
    return {
        "schema_version": "github-artifact-bundle-attestation-v2",
        "repository": repository,
        "workflow_path": workflow_path,
        "run_id": run_id,
        "run_attempt": "1",
        "head_sha": expected_sha,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "run_completed_observed_at": run_completed_observed_at,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "archive_sha256": archive_sha,
        "members": [
            {
                "filename": filename,
                "payload_bytes": len(payloads[filename]),
                "payload_sha256": hashlib.sha256(payloads[filename]).hexdigest(),
            }
            for filename in expected_filenames
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-main-sha", action="store_true")
    parser.add_argument("--repository", default=EXPECTED_REPOSITORY)
    parser.add_argument("--workflow-path")
    parser.add_argument("--run-id")
    parser.add_argument("--main-sha")
    parser.add_argument("--artifact-name")
    parser.add_argument("--artifact-filename")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--failure-stage", choices=tuple(_FAILURE_ARTIFACTS))
    args = parser.parse_args()
    try:
        raw_deadline = os.getenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH")
        effect_deadline_epoch = None if raw_deadline is None else float(raw_deadline)
        if raw_deadline is not None:
            _effect_timeout(effect_deadline_epoch, maximum=15.0)
        if args.exact_main_sha:
            if any(
                value is not None
                for value in (
                    args.workflow_path,
                    args.run_id,
                    args.main_sha,
                    args.artifact_name,
                    args.artifact_filename,
                    args.output,
                    args.report,
                    args.failure_stage,
                )
            ):
                raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
            print(exact_main_sha_v2(effect_deadline_epoch=effect_deadline_epoch))
            return 0
        common = (args.run_id, args.main_sha, args.output, args.report)
        if any(value is None for value in common):
            raise GitHubReleaseAttestationV2Error("GITHUB_ATTESTATION_V2_INPUT_INVALID")
        run_id = cast(str, args.run_id)
        main_sha = cast(str, args.main_sha)
        output = cast(Path, args.output)
        report_path = cast(Path, args.report)
        if args.failure_stage is not None:
            if (
                args.repository != EXPECTED_REPOSITORY
                or any(
                    value is not None
                    for value in (
                        args.workflow_path,
                        args.artifact_name,
                        args.artifact_filename,
                    )
                )
            ):
                raise GitHubReleaseAttestationV2Error(
                    "GITHUB_ATTESTATION_V2_INPUT_INVALID"
                )
            report = attest_and_download_failure_v2(
                stage=cast(str, args.failure_stage),
                run_id=run_id,
                main_sha=main_sha,
                output_path=output,
                effect_deadline_epoch=effect_deadline_epoch,
            )
        else:
            if any(
                value is None
                for value in (
                    args.workflow_path,
                    args.artifact_name,
                    args.artifact_filename,
                )
            ):
                raise GitHubReleaseAttestationV2Error(
                    "GITHUB_ATTESTATION_V2_INPUT_INVALID"
                )
            report = attest_and_download_v2(
                repository=args.repository,
                workflow_path=cast(str, args.workflow_path),
                run_id=run_id,
                main_sha=main_sha,
                artifact_name=cast(str, args.artifact_name),
                artifact_filename=cast(str, args.artifact_filename),
                output_path=output,
                effect_deadline_epoch=effect_deadline_epoch,
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, GitHubReleaseAttestationV2Error)
            else "GITHUB_ATTESTATION_V2_FAILED"
        )
        print(code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
