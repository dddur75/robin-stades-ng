"""Materialize one bounded, read-only GitHub delivery proof for Recovery V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
import subprocess  # nosec B404 - fixed git executable and closed argument vectors only.
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
    DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT,
    DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS,
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    DATA_TORRENT_RECOVERY_V2_START_SHA,
    DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    _recovery_v2_evidence_bytes,
    _recovery_v2_publish_exclusive_bytes,
    _recovery_v2_require_unused_repository_output,
    assert_production_safety_locks,
    canonical_json_bytes,
    validate_data_torrent_recovery_v2_authority,
    validate_data_torrent_recovery_v2_phase_one_council_closure,
    validate_data_torrent_recovery_v2_terminal_runtime_evidence,
)
from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import (
    TerminalEvidenceV2Error,
    _reserve_materializer_execution,
    _validate_authoritative_intent_set,
)

_ROOT = Path(os.path.abspath(Path(__file__))).parents[1]
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_BRANCH = "codex/data-torrent-recovery-v2"
_WORKFLOW_PATH = ".github/workflows/ci-safe-v2.yml"
_API_TOTAL_TIMEOUT_SECONDS = 25.0
_API_WORK_TIMEOUT_SECONDS = 20.0
_API_TERMINATE_TIMEOUT_SECONDS = 3.0
_MAX_TOKEN_BYTES = 2_048
_MAX_API_BYTES = 10 * 1024 * 1024
_GITHUB_API_ROOT = "https://api.github.com/"
_OBSERVER_POLL_SECONDS = 30.0
_OBSERVER_MAXIMUM_RUNTIME_SECONDS = 1_200
_MATERIALIZER_MAXIMUM_RUNTIME_SECONDS = 1_200
_OBSERVER_PHASE_GET_LIMITS = {"C1": 30, "C2": 30, "POSTMERGE": 19}
_OBSERVER_STATE_DIRECTORY = (
    Path("RobinCouncilOS")
    / EXPECTED_REPOSITORY.replace("/", "__")
    / "data-torrent-recovery-v2"
    / DATA_TORRENT_RECOVERY_V2_START_SHA
)
_OBSERVER_RESULT_NAMES = {
    "C1": "pr-c-c1-observer-result-v1.json",
    "C2": "pr-c-c2-observer-result-v1.json",
    "POSTMERGE": "pr-c-postmerge-observer-result-v1.json",
}
_OBSERVER_RESERVATION_NAMES = {
    "C1": "pr-c-c1-observer-reservation-v1.json",
    "C2": "pr-c-c2-observer-reservation-v1.json",
    "POSTMERGE": "pr-c-postmerge-observer-reservation-v1.json",
}
_NONTERMINAL_RUN_STATUSES = frozenset(
    {"requested", "waiting", "pending", "queued", "in_progress"}
)
_TERMINAL_CONCLUSIONS = frozenset(
    {
        "success",
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
        "stale",
        "neutral",
        "skipped",
    }
)
_EXACT_HEAD_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
    "EXACT_HEAD_SAFE_V2.CYCLE_1.CORRECTION.RELEASE.001"
)
_POST_202_B101_CORRECTION_RELEASE_CLAIM = (
    "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.POSIX_ROLLBACK."
    "FAIL_CLOSED.CORRECTION.RELEASE.001"
)
_PR_B_RELEASE_CLAIM = "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.003"


class DeliveryEvidenceV2Error(RuntimeError):
    """Sanitized fail-closed delivery observation error."""


def _release_claim_matches_engineering_chain(
    active_release_claim: object,
    *,
    pr_b_number: int | None,
) -> bool:
    """Admit only the exact active release matching the observed PR topology."""

    return (
        active_release_claim == _POST_202_B101_CORRECTION_RELEASE_CLAIM
        and pr_b_number is None
    ) or (
        active_release_claim == _PR_B_RELEASE_CLAIM
        and type(pr_b_number) is int
        and pr_b_number > 0
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"


def _write_exclusive(path: Path, payload: bytes, *, root: Path) -> None:
    try:
        _recovery_v2_publish_exclusive_bytes(path, payload, repository_root=root)
    except FileExistsError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_INVOCATION_ALREADY_CONSUMED") from None
    except (ChronosProductionError, OSError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_LOCAL_WRITE_INVALID") from None


def _assert_unused_output(path: Path, *, root: Path) -> None:
    try:
        _recovery_v2_require_unused_repository_output(path, repository_root=root)
    except ChronosProductionError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_OUTPUT_ROOT_INVALID") from None


def _run_git(arguments: tuple[str, ...], *, root: Path) -> str:
    environment = {
        key: os.environ[key]
        for key in (
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
        )
        if key in os.environ
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "LC_ALL": "C",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-delivery-git-hooks-") as hooks:
            result = subprocess.run(  # noqa: S603  # nosec B603
                (
                    "git",
                    "--no-replace-objects",
                    "-c",
                    "core.quotepath=false",
                    "-c",
                    f"core.hooksPath={hooks}",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-c",
                    "submodule.recurse=false",
                    "-c",
                    "protocol.allow=never",
                    *arguments,
                ),
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.TimeoutExpired):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_GIT_INVALID") from None
    if result.returncode != 0 or len(result.stdout) > 2 * 1024 * 1024:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_GIT_INVALID")
    try:
        decoded = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_GIT_INVALID") from None
    return decoded[:-1] if decoded.endswith("\n") else decoded


def _assert_index_flags_clear(*, root: Path) -> None:
    raw = _run_git(("ls-files", "-v", "-z"), root=root)
    records = [record for record in raw.split("\0") if record]
    paths = [record[2:] for record in records]
    if (
        any(len(record) < 3 or not record.startswith("H ") for record in records)
        or any(not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_WORKTREE_INVALID")


def _assert_delivery_worktree(
    *,
    root: Path,
    evidence_commit_sha: str,
    runtime_main_sha: str,
    reservation_commit_sha: str,
) -> None:
    reservation_parents, _subject, _body = _commit_shape(
        root=root,
        sha=reservation_commit_sha,
    )
    successors = _run_git(
        (
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{runtime_main_sha}..{evidence_commit_sha}",
        ),
        root=root,
    ).splitlines()
    if (
        _run_git(("rev-parse", "HEAD"), root=root) != evidence_commit_sha
        or _run_git(("branch", "--show-current"), root=root) != _BRANCH
        or _run_git(("status", "--porcelain=v1", "--untracked-files=no"), root=root) != ""
        or reservation_parents != [runtime_main_sha]
        or successors != [reservation_commit_sha, evidence_commit_sha]
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_WORKTREE_INVALID")
    _assert_index_flags_clear(root=root)


def _content_lengths(response: requests.Response) -> list[str]:
    raw_headers = getattr(response.raw, "headers", None)
    getlist = getattr(raw_headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist("Content-Length")]
    value = response.headers.get("Content-Length")
    return [] if value is None else [value]


def _header_values(response: requests.Response, name: str) -> list[str]:
    raw_headers = getattr(response.raw, "headers", None)
    getlist = getattr(raw_headers, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(name)]
    value = response.headers.get(name)
    return [] if value is None else [value]


def _bounded_body(response: requests.Response) -> bytes:
    lengths = _content_lengths(response)
    if len(lengths) > 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    declared: int | None = None
    if lengths:
        try:
            declared = int(lengths[0])
        except ValueError:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID") from None
        if declared < 0 or declared > _MAX_API_BYTES:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    if response.headers.get("Content-Encoding", "identity").casefold() != "identity":
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    content_type = response.headers.get("Content-Type", "").casefold()
    if not content_type.startswith("application/json"):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not isinstance(chunk, bytes):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
        body.extend(chunk)
        if len(body) > _MAX_API_BYTES:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    if declared is not None and declared != len(body):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    return bytes(body)


def _api_direct(
    path: str,
    *,
    token: str,
    effect_deadline_epoch: float | None = None,
) -> tuple[bytes, tuple[str, ...]]:
    session = requests.Session()
    session.trust_env = False
    session.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(
                total=0,
                connect=0,
                read=0,
                redirect=0,
                status=0,
                other=0,
                raise_on_redirect=True,
                respect_retry_after_header=False,
            )
        ),
    )
    response: requests.Response | None = None
    try:
        if effect_deadline_epoch is not None and time.time() >= effect_deadline_epoch:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_EFFECT_DEADLINE_EXCEEDED")
        response = session.get(
            _GITHUB_API_ROOT + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            timeout=(5, 10),
            allow_redirects=False,
            stream=True,
        )
        if response.status_code != 200:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_FAILED")
        return _bounded_body(response), tuple(_header_values(response, "Link"))
    except requests.RequestException:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_FAILED") from None
    finally:
        if response is not None:
            response.close()
        session.close()


def _api_worker(
    connection: Any,
    *,
    path: str,
    token: str,
    effect_deadline_epoch: float | None,
) -> None:
    try:
        body, links = _api_direct(
            path,
            token=token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        connection.send(("CONFIRMED", body, links))
    except Exception:
        connection.send(("FAILED", b"", ()))
    finally:
        connection.close()


def _runs_path() -> str:
    return (
        f"repos/{EXPECTED_REPOSITORY}/actions/workflows/ci-safe-v2.yml/runs?"
        f"event=pull_request&branch={quote(_BRANCH, safe='')}&per_page=100"
    )


def _open_pr_path() -> str:
    encoded_branch = quote(_BRANCH, safe="")
    return (
        f"repos/{EXPECTED_REPOSITORY}/pulls?state=open&head=dddur75%3A{encoded_branch}"
        "&base=main&per_page=100"
    )


def _allowed_api_path(
    path: str,
    *,
    engineering_numbers: tuple[int, ...],
    safe_run_ids: frozenset[int],
    observer_paths: frozenset[str] = frozenset(),
) -> bool:
    if path in observer_paths:
        return True
    if path in {f"repos/{EXPECTED_REPOSITORY}/pulls/{number}" for number in engineering_numbers}:
        return True
    if path in {_runs_path(), _open_pr_path()}:
        return True
    return path in {
        f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100"
        for run_id in safe_run_ids
    }


def _api_json(
    path: str,
    *,
    token: str,
    engineering_numbers: tuple[int, ...],
    safe_run_ids: frozenset[int] = frozenset(),
    observer_paths: frozenset[str] = frozenset(),
    effect_deadline_epoch: float | None = None,
) -> object:
    if not _allowed_api_path(
        path,
        engineering_numbers=engineering_numbers,
        safe_run_ids=safe_run_ids,
        observer_paths=observer_paths,
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_PATH_INVALID")
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_api_worker,
        kwargs={
            "connection": sender,
            "path": path,
            "token": token,
            "effect_deadline_epoch": effect_deadline_epoch,
        },
    )
    remaining_effect_seconds = (
        _API_TOTAL_TIMEOUT_SECONDS
        if effect_deadline_epoch is None
        else max(0.0, effect_deadline_epoch - time.time())
    )
    deadline = time.monotonic() + min(
        _API_TOTAL_TIMEOUT_SECONDS,
        remaining_effect_seconds,
    )
    if remaining_effect_seconds <= 0:
        receiver.close()
        sender.close()
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_EFFECT_DEADLINE_EXCEEDED")
    process.start()
    sender.close()
    message: tuple[str, bytes, tuple[str, ...]] = ("FAILED", b"", ())
    try:
        if receiver.poll(min(_API_WORK_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic()))):
            received = receiver.recv()
            if (
                isinstance(received, tuple)
                and len(received) == 3
                and isinstance(received[0], str)
                and isinstance(received[1], bytes)
                and isinstance(received[2], tuple)
                and all(isinstance(value, str) for value in received[2])
            ):
                message = received
    except (EOFError, OSError):
        message = ("FAILED", b"", ())
    if message[0] == "CONFIRMED":
        process.join(max(0.0, deadline - time.monotonic()))
    if process.is_alive():
        process.terminate()
        process.join(min(_API_TERMINATE_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic())))
    if process.is_alive():
        process.kill()
        process.join(max(0.0, deadline - time.monotonic()))
    receiver.close()
    exit_code = process.exitcode
    if not process.is_alive():
        process.close()
    body = message[1]
    if (
        exit_code != 0
        or message[0] != "CONFIRMED"
        or not body
        or len(body) > _MAX_API_BYTES
        or message[2]
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_FAILED")
    try:
        document = json.loads(
            body,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID") from None
    if not isinstance(document, (dict, list)):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_API_INVALID")
    return document


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TIMESTAMP_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TIMESTAMP_INVALID")
    return parsed.astimezone(UTC)


def _commit_shape(*, root: Path, sha: str) -> tuple[list[str], str, str]:
    fields = _run_git(("rev-list", "--parents", "-n", "1", sha), root=root).split()
    if not fields or fields[0] != sha:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")
    subject = _run_git(("show", "-s", "--format=%s", sha), root=root)
    body = _run_git(("show", "-s", "--format=%b", sha), root=root)
    return fields[1:], subject, body


def _local_engineering_chain(*, root: Path, runtime_main_sha: str) -> list[dict[str, object]]:
    output = _run_git(
        (
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{DATA_TORRENT_RECOVERY_V2_START_SHA}..{runtime_main_sha}",
        ),
        root=root,
    )
    commits = [line for line in output.splitlines() if line]
    if len(commits) not in {1, 2} or any(_SHA.fullmatch(commit) is None for commit in commits):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")
    expected_parent = DATA_TORRENT_RECOVERY_V2_START_SHA
    rows: list[dict[str, object]] = []
    for index, commit in enumerate(commits):
        role = "PR_A" if index == 0 else "PR_B"
        parents, subject, body = _commit_shape(root=root, sha=commit)
        expected_subject = f"[DATA_TORRENT_RECOVERY_V2] PR-{'A' if role == 'PR_A' else 'B'}"
        if (
            len(parents) != 2
            or parents[0] != expected_parent
            or subject != expected_subject
            or body != ""
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")
        rows.append(
            {
                "role": role,
                "merge_commit_sha": commit,
                "first_parent_sha": parents[0],
                "second_parent_sha": parents[1],
                "merge_commit_subject": subject,
                "merge_commit_body": body,
            }
        )
        expected_parent = commit
    if expected_parent != runtime_main_sha:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")
    return rows


def _engineering_pr(
    *,
    document: object,
    number: int,
    local: dict[str, object],
) -> tuple[dict[str, object], datetime]:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PR_INVALID")
    head = document.get("head")
    base = document.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PR_INVALID")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    role = cast(str, local["role"])
    slot = "A" if role == "PR_A" else "B"
    merge_sha = document.get("merge_commit_sha")
    head_sha = head.get("sha")
    if (
        document.get("number") != number
        or document.get("title") != f"[DATA_TORRENT_RECOVERY_V2] PR-{slot}"
        or document.get("state") != "closed"
        or document.get("merged") is not True
        or head.get("ref") != _BRANCH
        or base.get("ref") != "main"
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(base_repo, dict)
        or base_repo.get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(head_sha, str)
        or _SHA.fullmatch(head_sha) is None
        or merge_sha != local["merge_commit_sha"]
        or head_sha != local["second_parent_sha"]
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PR_INVALID")
    merged_at = _timestamp(document.get("merged_at"))
    return (
        {
            "role": role,
            "number": number,
            "head_ref": _BRANCH,
            "head_sha": head_sha,
            "base_ref": "main",
            "merged_at": cast(str, document["merged_at"]),
            "state": "MERGED",
            "merge_commit_sha": merge_sha,
            "merge_method": "MERGE_COMMIT",
            "first_parent_sha": local["first_parent_sha"],
            "second_parent_sha": local["second_parent_sha"],
            "merge_commit_subject": local["merge_commit_subject"],
            "merge_commit_body": local["merge_commit_body"],
        },
        merged_at,
    )


def _terminal_pr(
    *,
    document: object,
    runtime_main_sha: str,
    evidence_commit_sha: str,
    reservation_commit_sha: str,
) -> tuple[dict[str, object], datetime]:
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TERMINAL_PR_INVALID")
    pull = cast(dict[str, Any], document[0])
    head = pull.get("head")
    base = pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TERMINAL_PR_INVALID")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    number = pull.get("number")
    if (
        type(number) is not int
        or number <= 0
        or pull.get("title") != "[DATA_TORRENT_RECOVERY_V2] PR-C"
        or pull.get("state") != "open"
        or pull.get("draft") is not False
        or head.get("ref") != _BRANCH
        or head.get("sha") != evidence_commit_sha
        or base.get("ref") != "main"
        or base.get("sha") != runtime_main_sha
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(base_repo, dict)
        or base_repo.get("full_name") != EXPECTED_REPOSITORY
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TERMINAL_PR_INVALID")
    created_at = _timestamp(pull.get("created_at"))
    return (
        {
            "role": "PR_C",
            "number": number,
            "head_ref": _BRANCH,
            "observed_head_sha": evidence_commit_sha,
            "observed_head_parent_sha": reservation_commit_sha,
            "base_ref": "main",
            "base_sha": runtime_main_sha,
            "state": "OPEN",
            "open_prs_for_exact_head_ref": 1,
            "created_at": cast(str, pull["created_at"]),
        },
        created_at,
    )


def _pull_number_from_run(run: Mapping[str, Any]) -> int:
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list) or len(pull_requests) != 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    pull = pull_requests[0]
    if not isinstance(pull, dict) or type(pull.get("number")) is not int:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    head = pull.get("head")
    base = pull.get("base")
    if (
        not isinstance(head, dict)
        or not isinstance(base, dict)
        or head.get("ref") != _BRANCH
        or head.get("sha") != run.get("head_sha")
        or base.get("ref") != "main"
        or not isinstance(head.get("repo"), dict)
        or cast(dict[str, Any], head["repo"]).get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(base.get("repo"), dict)
        or cast(dict[str, Any], base["repo"]).get("full_name") != EXPECTED_REPOSITORY
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    return cast(int, pull["number"])


def _safe_run_inventory(
    *,
    document: object,
    engineering: list[dict[str, object]],
    terminal_pr_number: int,
    terminal_head_sha: str,
) -> tuple[
    dict[int, list[dict[str, Any]]],
    dict[int, dict[str, Any]],
    dict[str, Any],
]:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    runs = document.get("workflow_runs")
    if (
        not isinstance(runs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(runs)
        or not 1 <= len(runs) <= 100
        or any(not isinstance(run, dict) for run in runs)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    engineering_numbers = {cast(int, row["number"]) for row in engineering}
    allowed_numbers = engineering_numbers | {terminal_pr_number}
    grouped: dict[int, list[dict[str, Any]]] = {
        number: [] for number in engineering_numbers
    }
    exact_success: dict[int, dict[str, Any]] = {}
    terminal_runs: list[dict[str, Any]] = []
    not_before = _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE)
    by_number = {cast(int, row["number"]): row for row in engineering}
    for value in runs:
        run = cast(dict[str, Any], value)
        repository = run.get("repository")
        head_repository = run.get("head_repository")
        run_id = run.get("id")
        head_sha = run.get("head_sha")
        if (
            type(run_id) is not int
            or _RUN_ID.fullmatch(str(run_id)) is None
            or run.get("path") != _WORKFLOW_PATH
            or run.get("head_branch") != _BRANCH
            or not isinstance(head_sha, str)
            or _SHA.fullmatch(head_sha) is None
            or run.get("event") != "pull_request"
            or run.get("run_attempt") != 1
            or run.get("status") != "completed"
            or run.get("conclusion") not in _TERMINAL_CONCLUSIONS
            or not isinstance(repository, dict)
            or repository.get("full_name") != EXPECTED_REPOSITORY
            or not isinstance(head_repository, dict)
            or head_repository.get("full_name") != EXPECTED_REPOSITORY
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        created_at = _timestamp(run.get("created_at"))
        updated_at = _timestamp(run.get("updated_at"))
        if created_at < not_before or updated_at < created_at:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        number = _pull_number_from_run(run)
        if number not in allowed_numbers:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        if number == terminal_pr_number:
            terminal_runs.append(run)
            continue
        row = by_number[number]
        if updated_at > _timestamp(row["merged_at"]):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        grouped[number].append(run)
    total_cycles = sum(len(values) for values in grouped.values())
    if total_cycles > 6:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    for row in engineering:
        number = cast(int, row["number"])
        values = grouped[number]
        if not 1 <= len(values) <= 3 or len({cast(int, run["id"]) for run in values}) != len(values):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        candidates = [
            run
            for run in values
            if run.get("head_sha") == row["head_sha"] and run.get("conclusion") == "success"
        ]
        if len(candidates) != 1:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
        exact_success[number] = candidates[0]
    if (
        len(terminal_runs) != 1
        or terminal_runs[0].get("head_sha") != terminal_head_sha
        or terminal_runs[0].get("conclusion") != "failure"
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_SAFE_INVALID")
    return grouped, exact_success, terminal_runs[0]


def _phase_one_jobs(
    *,
    document: object,
    run: Mapping[str, Any],
    pull_request_number: int,
) -> dict[str, object]:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_SAFE_INVALID")
    jobs = document.get("jobs")
    if (
        not isinstance(jobs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(jobs)
        or not 1 <= len(jobs) <= 100
        or any(not isinstance(job, dict) for job in jobs)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_SAFE_INVALID")
    scope_matches = [
        cast(dict[str, Any], job)
        for job in jobs
        if cast(dict[str, Any], job).get("name") == "Recovery V2 — scope guard exact"
    ]
    tests_matches = [
        cast(dict[str, Any], job)
        for job in jobs
        if cast(dict[str, Any], job).get("name") == "tests"
    ]
    if len(scope_matches) != 1 or len(tests_matches) != 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_SAFE_INVALID")
    scope = scope_matches[0]
    tests = tests_matches[0]
    gate_steps = tests.get("steps")
    matching_steps = (
        [
            cast(dict[str, Any], step)
            for step in gate_steps
            if isinstance(step, dict)
            and step.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
        ]
        if isinstance(gate_steps, list)
        else []
    )
    run_id = run.get("id")
    scope_id = scope.get("id")
    tests_id = tests.get("id")
    if (
        type(run_id) is not int
        or _RUN_ID.fullmatch(str(run_id)) is None
        or any(
            type(value) is not int or _RUN_ID.fullmatch(str(value)) is None
            for value in (scope_id, tests_id)
        )
        or scope.get("run_id") != run_id
        or tests.get("run_id") != run_id
        or scope.get("run_attempt") != 1
        or tests.get("run_attempt") != 1
        or scope.get("head_sha") != run.get("head_sha")
        or tests.get("head_sha") != run.get("head_sha")
        or scope.get("status") != "completed"
        or scope.get("conclusion") != "success"
        or tests.get("status") != "completed"
        or tests.get("conclusion") != "failure"
        or len(matching_steps) != 1
        or matching_steps[0].get("status") != "completed"
        or matching_steps[0].get("conclusion") != "failure"
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_SAFE_INVALID")
    return {
        "workflow_path": _WORKFLOW_PATH,
        "run_id": run_id,
        "run_attempt": 1,
        "event": "pull_request",
        "pull_request_number": pull_request_number,
        "head_ref": _BRANCH,
        "head_sha": run["head_sha"],
        "status": "completed",
        "conclusion": "failure",
        "scope_guard_job_id": scope_id,
        "scope_guard_conclusion": "success",
        "tests_job_id": tests_id,
        "tests_conclusion": "failure",
        "gate_step_conclusion": "failure",
        "run_completed_observed_at": run["updated_at"],
    }


def _safe_jobs(
    *,
    document: object,
    run: dict[str, Any],
    pull_request_number: int,
) -> dict[str, object]:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    jobs = document.get("jobs")
    if (
        not isinstance(jobs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(jobs)
        or not 1 <= len(jobs) <= 100
        or any(not isinstance(job, dict) for job in jobs)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    run_id = cast(int, run["id"])
    scope_jobs = [
        cast(dict[str, Any], job)
        for job in jobs
        if cast(dict[str, Any], job).get("name") == "Recovery V2 — scope guard exact"
    ]
    if len(scope_jobs) != 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    scope = scope_jobs[0]
    scope_id = scope.get("id")
    run_completed = _timestamp(run.get("updated_at"))
    scope_completed = _timestamp(scope.get("completed_at"))
    if (
        type(scope_id) is not int
        or scope_id <= 0
        or scope.get("run_id") != run_id
        or scope.get("run_attempt") != 1
        or scope.get("head_sha") != run.get("head_sha")
        or scope.get("status") != "completed"
        or scope.get("conclusion") != "success"
        or scope_completed > run_completed
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_SAFE_INVALID")
    return {
        "workflow_path": _WORKFLOW_PATH,
        "run_id": run_id,
        "run_attempt": 1,
        "event": "pull_request",
        "pull_request_number": pull_request_number,
        "head_ref": _BRANCH,
        "head_sha": run["head_sha"],
        "status": "completed",
        "conclusion": "success",
        "run_completed_observed_at": run["updated_at"],
        "scope_guard_job_id": scope_id,
        "scope_guard_name": scope["name"],
        "scope_guard_status": scope["status"],
        "scope_guard_conclusion": scope["conclusion"],
        "scope_guard_completed_at": scope["completed_at"],
    }


def _observer_state_context(*, root: Path) -> tuple[Path, str]:
    try:
        from scripts.verify_data_torrent_recovery_v2_postmerge_gate import (
            _host_identity_sha256,
            _state_base,
        )

        state_base = Path(os.path.abspath(_state_base()))
        host_identity_sha256 = _host_identity_sha256()
    except Exception:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_STATE_ROOT_INVALID") from None
    lexical_root = Path(os.path.abspath(root))
    lexical_target = Path(os.path.abspath(state_base / _OBSERVER_STATE_DIRECTORY))
    if (
        lexical_target.is_relative_to(lexical_root)
        or host_identity_sha256 != DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_HOST_IDENTITY_INVALID")
    return state_base, host_identity_sha256


def _observer_relative_path(*, phase: str, reservation: bool) -> Path:
    names = _OBSERVER_RESERVATION_NAMES if reservation else _OBSERVER_RESULT_NAMES
    try:
        name = names[phase]
    except KeyError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PHASE_INVALID") from None
    return _OBSERVER_STATE_DIRECTORY / name


def _strict_observer_json(path: Path, *, state_base: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = _recovery_v2_evidence_bytes(
            path,
            repository_root=state_base,
            maximum_bytes=262_144,
        )
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (ChronosProductionError, UnicodeDecodeError, ValueError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_EVIDENCE_INVALID") from None
    if (
        not isinstance(document, dict)
        or payload != canonical_json_bytes(cast(dict[str, Any], document)) + b"\n"
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_EVIDENCE_INVALID")
    return payload, cast(dict[str, Any], document)


def _observer_result_common_valid(
    document: Mapping[str, Any],
    *,
    phase: str,
    pr_number: int,
    head_sha: str,
    host_identity_sha256: str,
) -> bool:
    fields = {
        "schema_version",
        "phase",
        "verdict",
        "mission_id",
        "repository",
        "program_start_sha",
        "host_identity_sha256",
        "pr_number",
        "head_sha",
        "runtime_main_sha",
        "phase_one_sha",
        "candidate_sha",
        "merge_sha",
        "observed_at",
        "reservation",
        "predecessor_results",
        "run",
        "github_gets_exact",
        "github_gets_conservative_limit",
        "automatic_retries",
    }
    expected_verdict = {
        "C1": "PR_C_C1_EXPECTED_HOLD_CONFIRMED",
        "C2": "PR_C_C2_SUCCESS_CONFIRMED",
        "POSTMERGE": "PR_C_POSTMERGE_SUCCESS_CONFIRMED",
    }[phase]
    counters = document.get("github_gets_exact")
    jobs = 0 if phase == "POSTMERGE" else 1
    maximum_observations = 18 if phase == "POSTMERGE" else 28
    if not isinstance(counters, dict):
        return False
    observations = counters.get("run_inventory_observations")
    pull_request_gets = counters.get("pull_request")
    rechecks = counters.get("final_run_inventory_rechecks_exact")
    exact_run_jobs = counters.get("exact_run_jobs")
    total_gets = counters.get("total")
    return (
        set(document) == fields
        and document.get("schema_version") == "data-torrent-recovery-v2-pr-c-observer-result-v1"
        and document.get("phase") == phase
        and document.get("verdict") == expected_verdict
        and document.get("mission_id") == "data-torrent-recovery-v2"
        and document.get("repository") == EXPECTED_REPOSITORY
        and document.get("program_start_sha") == DATA_TORRENT_RECOVERY_V2_START_SHA
        and document.get("host_identity_sha256") == host_identity_sha256
        and document.get("pr_number") == pr_number
        and document.get("head_sha") == head_sha
        and isinstance(document.get("runtime_main_sha"), str)
        and _SHA.fullmatch(cast(str, document.get("runtime_main_sha"))) is not None
        and isinstance(document.get("observed_at"), str)
        and type(observations) is int
        and type(pull_request_gets) is int
        and type(rechecks) is int
        and type(exact_run_jobs) is int
        and type(total_gets) is int
        and 2 <= observations <= maximum_observations
        and counters
        == {
            "pull_request": 1,
            "run_inventory_observations": observations,
            "final_run_inventory_rechecks_exact": 1,
            "exact_run_jobs": jobs,
            "total": observations + jobs + 1,
        }
        and type(document.get("github_gets_conservative_limit")) is int
        and document.get("github_gets_conservative_limit")
        == _OBSERVER_PHASE_GET_LIMITS[phase]
        and type(document.get("automatic_retries")) is int
        and document.get("automatic_retries") == 0
    )


def _validate_observer_reservation(
    document: Mapping[str, Any],
    *,
    phase: str,
    pr_number: int,
    head_sha: str,
    runtime_main_sha: str,
    host_identity_sha256: str,
    predecessor_results: Mapping[str, str],
) -> None:
    if (
        set(document)
        != {
            "schema_version",
            "reservation_status",
            "mission_id",
            "repository",
            "program_start_sha",
            "phase",
            "expected_head_sha",
            "expected_base_sha",
            "pr_number",
            "host_identity_sha256",
            "observed_at",
            "github_api_gets_conservatively_consumed",
            "automatic_retries",
            "second_invocation_allowed",
            "predecessor_results",
        }
        or document.get("schema_version")
        != "data-torrent-recovery-v2-pr-c-observer-reservation-v1"
        or document.get("reservation_status")
        != "RESERVED_BEFORE_FIRST_EXTERNAL_READ"
        or document.get("mission_id") != "data-torrent-recovery-v2"
        or document.get("repository") != EXPECTED_REPOSITORY
        or document.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or document.get("phase") != phase
        or document.get("expected_head_sha") != head_sha
        or document.get("expected_base_sha") != runtime_main_sha
        or document.get("pr_number") != pr_number
        or document.get("host_identity_sha256") != host_identity_sha256
        or not isinstance(document.get("observed_at"), str)
        or type(document.get("github_api_gets_conservatively_consumed")) is not int
        or document.get("github_api_gets_conservatively_consumed")
        != _OBSERVER_PHASE_GET_LIMITS[phase]
        or type(document.get("automatic_retries")) is not int
        or document.get("automatic_retries") != 0
        or document.get("second_invocation_allowed") is not False
        or document.get("predecessor_results") != dict(predecessor_results)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESERVATION_INVALID")
    _timestamp(document["observed_at"])


def _validate_observer_run_result(
    run: Mapping[str, Any],
    *,
    phase: str,
    pr_number: int,
    expected_head_sha: str,
) -> None:
    run_id = run.get("run_id")
    if phase == "POSTMERGE":
        if (
            set(run)
            != {
                "workflow_path",
                "run_id",
                "run_attempt",
                "event",
                "head_branch",
                "head_sha",
                "status",
                "conclusion",
                "created_at",
                "completed_at",
            }
            or run.get("workflow_path") != _WORKFLOW_PATH
            or type(run_id) is not int
            or _RUN_ID.fullmatch(str(run_id)) is None
            or type(run.get("run_attempt")) is not int
            or run.get("run_attempt") != 1
            or run.get("event") != "push"
            or run.get("head_branch") != "main"
            or run.get("head_sha") != expected_head_sha
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    else:
        expected = "failure" if phase == "C1" else "success"
        scope_id = run.get("scope_guard_job_id")
        tests_id = run.get("tests_job_id")
        if (
            set(run)
            != {
                "workflow_path",
                "run_id",
                "run_attempt",
                "event",
                "pull_request_number",
                "head_ref",
                "head_sha",
                "status",
                "conclusion",
                "created_at",
                "completed_at",
                "scope_guard_job_id",
                "scope_guard_conclusion",
                "tests_job_id",
                "tests_conclusion",
                "gate_step_conclusion",
            }
            or run.get("workflow_path") != _WORKFLOW_PATH
            or type(run_id) is not int
            or _RUN_ID.fullmatch(str(run_id)) is None
            or type(run.get("run_attempt")) is not int
            or run.get("run_attempt") != 1
            or run.get("event") != "pull_request"
            or run.get("pull_request_number") != pr_number
            or run.get("head_ref") != _BRANCH
            or run.get("head_sha") != expected_head_sha
            or run.get("status") != "completed"
            or run.get("conclusion") != expected
            or any(
                type(value) is not int or _RUN_ID.fullmatch(str(value)) is None
                for value in (scope_id, tests_id)
            )
            or scope_id == tests_id
            or run.get("scope_guard_conclusion") != "success"
            or run.get("tests_conclusion") != expected
            or run.get("gate_step_conclusion") != expected
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    created_at = _timestamp(run.get("created_at"))
    completed_at = _timestamp(run.get("completed_at"))
    if created_at < _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE) or completed_at < created_at:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")


def _load_observer_result(
    *,
    phase: str,
    root: Path,
    pr_number: int,
    expected_head_sha: str,
    not_after: datetime,
    state_base: Path | None = None,
    host_identity_sha256: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    if (
        _SHA.fullmatch(expected_head_sha) is None
        or type(pr_number) is not int
        or pr_number <= 0
        or not_after.tzinfo is None
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    not_after = not_after.astimezone(UTC).replace(microsecond=0)
    if state_base is None or host_identity_sha256 is None:
        state_base, host_identity_sha256 = _observer_state_context(root=root)
    predecessors: dict[str, tuple[bytes, dict[str, Any]]] = {}
    if phase in {"C2", "POSTMERGE"}:
        c1_result_path = state_base / _observer_relative_path(phase="C1", reservation=False)
        _c1_probe_payload, c1_probe = _strict_observer_json(
            c1_result_path,
            state_base=state_base,
        )
        c1_head = c1_probe.get("head_sha")
        if not isinstance(c1_head, str) or _SHA.fullmatch(c1_head) is None:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
        c1_payload, c1 = _load_observer_result(
            phase="C1",
            root=root,
            pr_number=pr_number,
            expected_head_sha=c1_head,
            not_after=not_after,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        predecessors["C1"] = (c1_payload, c1)
    if phase == "POSTMERGE":
        c2_result_path = state_base / _observer_relative_path(phase="C2", reservation=False)
        _c2_probe_payload, c2_probe = _strict_observer_json(
            c2_result_path,
            state_base=state_base,
        )
        c2_head = c2_probe.get("head_sha")
        if c2_head != expected_head_sha:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
        c2_payload, c2 = _load_observer_result(
            phase="C2",
            root=root,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            not_after=not_after,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        predecessors["C2"] = (c2_payload, c2)
    reservation_path = state_base / _observer_relative_path(phase=phase, reservation=True)
    result_path = state_base / _observer_relative_path(phase=phase, reservation=False)
    reservation_payload, reservation = _strict_observer_json(
        reservation_path,
        state_base=state_base,
    )
    result_payload, result = _strict_observer_json(result_path, state_base=state_base)
    predecessor_hashes = {
        name: hashlib.sha256(value[0]).hexdigest() for name, value in predecessors.items()
    }
    _validate_observer_reservation(
        reservation,
        phase=phase,
        pr_number=pr_number,
        head_sha=expected_head_sha,
        runtime_main_sha=cast(str, result.get("runtime_main_sha")),
        host_identity_sha256=host_identity_sha256,
        predecessor_results=predecessor_hashes,
    )
    if not _observer_result_common_valid(
        result,
        phase=phase,
        pr_number=pr_number,
        head_sha=expected_head_sha,
        host_identity_sha256=host_identity_sha256,
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    reservation_binding = result.get("reservation")
    if (
        reservation_binding
        != {
            "namespace": _observer_relative_path(phase=phase, reservation=True).as_posix(),
            "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
            "conservative_github_api_gets": _OBSERVER_PHASE_GET_LIMITS[phase],
            "second_invocation_allowed": False,
        }
        or result.get("predecessor_results") != predecessor_hashes
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    _timestamp(result["observed_at"])
    run = result.get("run")
    if not isinstance(run, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    c1 = predecessors.get("C1", (b"", {}))[1]
    if phase == "C1":
        _validate_observer_run_result(
            run,
            phase=phase,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
        )
        if (
            result.get("phase_one_sha") != expected_head_sha
            or _SHA.fullmatch(cast(str, result.get("runtime_main_sha"))) is None
            or result.get("candidate_sha") is not None
            or result.get("merge_sha") is not None
            or run.get("head_sha") != expected_head_sha
            or run.get("conclusion") != "failure"
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    elif phase == "C2":
        _validate_observer_run_result(
            run,
            phase=phase,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
        )
        c1_run = c1.get("run")
        if (
            not isinstance(c1_run, dict)
            or result.get("runtime_main_sha") != c1.get("runtime_main_sha")
            or result.get("phase_one_sha") != c1.get("head_sha")
            or result.get("candidate_sha") != expected_head_sha
            or result.get("merge_sha") is not None
            or run.get("head_sha") != expected_head_sha
            or run.get("conclusion") != "success"
            or run.get("run_id") == c1_run.get("run_id")
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
    else:
        c2 = predecessors["C2"][1]
        merge_sha = result.get("merge_sha")
        if (
            result.get("phase_one_sha") != c1.get("head_sha")
            or result.get("runtime_main_sha") != c1.get("runtime_main_sha")
            or result.get("candidate_sha") != c2.get("head_sha")
            or result.get("head_sha") != c2.get("head_sha")
            or not isinstance(merge_sha, str)
            or _SHA.fullmatch(merge_sha) is None
            or run.get("head_sha") != merge_sha
            or run.get("event") != "push"
            or run.get("conclusion") != "success"
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_INVALID")
        _validate_observer_run_result(
            run,
            phase=phase,
            pr_number=pr_number,
            expected_head_sha=merge_sha,
        )
    reservation_at = _timestamp(reservation["observed_at"])
    result_at = _timestamp(result["observed_at"])
    completed_at = _timestamp(run["completed_at"])
    not_before = _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE)
    admission_close = _timestamp(DATA_TORRENT_RECOVERY_V2_LATEST_EFFECT_ADMISSION_AT)
    budget_deadline = not_before + timedelta(
        seconds=DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
    )
    predecessor_observed_at = [
        _timestamp(value[1]["observed_at"]) for value in predecessors.values()
    ]
    if (
        not not_before <= reservation_at <= result_at < budget_deadline
        or reservation_at >= admission_close
        or result_at - reservation_at
        > timedelta(seconds=DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS)
        or completed_at > result_at
        or result_at > not_after
        or any(observed > reservation_at for observed in predecessor_observed_at)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_TEMPORAL_INVALID")
    return result_payload, result


def _reserve_observer(
    *,
    phase: str,
    state_base: Path,
    pr_number: int,
    head_sha: str,
    runtime_main_sha: str,
    host_identity_sha256: str,
    predecessor_results: Mapping[str, str],
    observed_at: datetime,
) -> tuple[bytes, dict[str, Any]]:
    reservation = {
        "schema_version": "data-torrent-recovery-v2-pr-c-observer-reservation-v1",
        "reservation_status": "RESERVED_BEFORE_FIRST_EXTERNAL_READ",
        "mission_id": "data-torrent-recovery-v2",
        "repository": EXPECTED_REPOSITORY,
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "phase": phase,
        "expected_head_sha": head_sha,
        "expected_base_sha": runtime_main_sha,
        "pr_number": pr_number,
        "host_identity_sha256": host_identity_sha256,
        "observed_at": observed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "github_api_gets_conservatively_consumed": _OBSERVER_PHASE_GET_LIMITS[phase],
        "automatic_retries": 0,
        "second_invocation_allowed": False,
        "predecessor_results": dict(predecessor_results),
    }
    payload = canonical_json_bytes(reservation) + b"\n"
    target = state_base / _observer_relative_path(phase=phase, reservation=True)
    try:
        _recovery_v2_publish_exclusive_bytes(target, payload, repository_root=state_base)
    except (ChronosProductionError, FileExistsError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_INVOCATION_ALREADY_RESERVED") from None
    return payload, reservation


def _observer_pull_request(
    document: object,
    *,
    pr_number: int,
    head_sha: str,
    expected_base_sha: str,
    merged: bool,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PR_INVALID")
    head = document.get("head")
    base = document.get("base")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (
        document.get("number") != pr_number
        or document.get("title") != "[DATA_TORRENT_RECOVERY_V2] PR-C"
        or document.get("draft") is not False
        or document.get("merged") is not merged
        or document.get("state") != ("closed" if merged else "open")
        or not isinstance(head, dict)
        or head.get("ref") != _BRANCH
        or head.get("sha") != head_sha
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or (not merged and base.get("sha") != expected_base_sha)
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(base_repo, dict)
        or base_repo.get("full_name") != EXPECTED_REPOSITORY
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PR_INVALID")
    _timestamp(document.get("created_at"))
    if merged:
        merge_sha = document.get("merge_commit_sha")
        if not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PR_INVALID")
        _timestamp(document.get("merged_at"))
    return cast(dict[str, Any], document)


def _observer_runs_path(*, phase: str, merge_sha: str | None = None) -> str:
    if phase == "POSTMERGE":
        if not isinstance(merge_sha, str) or _SHA.fullmatch(merge_sha) is None:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
        return (
            f"repos/{EXPECTED_REPOSITORY}/actions/workflows/ci-safe-v2.yml/runs?"
            f"event=push&head_sha={merge_sha}&per_page=100"
        )
    return (
        f"repos/{EXPECTED_REPOSITORY}/actions/workflows/ci-safe-v2.yml/runs?"
        f"event=pull_request&branch={quote(_BRANCH, safe='')}&per_page=100"
    )


def _observer_target_run(
    document: object,
    *,
    phase: str,
    pr_number: int,
    expected_head_sha: str,
    predecessor_run: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
    runs = document.get("workflow_runs")
    total_count = document.get("total_count")
    if (
        not isinstance(runs, list)
        or type(total_count) is not int
        or total_count != len(runs)
        or len(runs) > 100
        or any(not isinstance(run, dict) for run in runs)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
    candidates: list[dict[str, Any]] = []
    predecessor_matches = 0
    for value in runs:
        run = cast(dict[str, Any], value)
        if phase != "POSTMERGE":
            if _pull_number_from_run(run) != pr_number:
                continue
            allowed_heads = {expected_head_sha}
            if predecessor_run is not None:
                predecessor_head = predecessor_run.get("head_sha")
                if not isinstance(predecessor_head, str):
                    raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
                allowed_heads.add(predecessor_head)
            if run.get("head_sha") not in allowed_heads:
                raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
        elif run.get("head_sha") != expected_head_sha:
            continue
        repository = run.get("repository")
        head_repository = run.get("head_repository")
        run_id = run.get("id")
        status = run.get("status")
        conclusion = run.get("conclusion")
        if (
            type(run_id) is not int
            or _RUN_ID.fullmatch(str(run_id)) is None
            or run.get("path") != _WORKFLOW_PATH
            or run.get("event") != ("push" if phase == "POSTMERGE" else "pull_request")
            or run.get("head_branch") != ("main" if phase == "POSTMERGE" else _BRANCH)
            or type(run.get("run_attempt")) is not int
            or run.get("run_attempt") != 1
            or status not in (_NONTERMINAL_RUN_STATUSES | {"completed"})
            or (status != "completed" and conclusion is not None)
            or (status == "completed" and conclusion not in _TERMINAL_CONCLUSIONS)
            or not isinstance(repository, dict)
            or repository.get("full_name") != EXPECTED_REPOSITORY
            or not isinstance(head_repository, dict)
            or head_repository.get("full_name") != EXPECTED_REPOSITORY
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
        created_at = _timestamp(run.get("created_at"))
        updated_at = _timestamp(run.get("updated_at"))
        if created_at < _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE) or updated_at < created_at:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
        if run.get("head_sha") == expected_head_sha:
            candidates.append(run)
        else:
            if (
                predecessor_run is None
                or run.get("id") != predecessor_run.get("run_id")
                or run.get("run_attempt") != predecessor_run.get("run_attempt")
                or run.get("status") != "completed"
                or run.get("conclusion") != predecessor_run.get("conclusion")
            ):
                raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
            predecessor_matches += 1
    if len(candidates) > 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
    if predecessor_run is not None and predecessor_matches != 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_INVALID")
    return candidates[0] if candidates else None


def _observer_run_projection(
    run: Mapping[str, Any], *, phase: str
) -> dict[str, Any]:
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    return {
        "id": run.get("id"),
        "run_attempt": run.get("run_attempt"),
        "path": run.get("path"),
        "event": run.get("event"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "pull_request_number": (
            None if phase == "POSTMERGE" else _pull_number_from_run(run)
        ),
        "repository": (
            repository.get("full_name") if isinstance(repository, dict) else None
        ),
        "head_repository": (
            head_repository.get("full_name")
            if isinstance(head_repository, dict)
            else None
        ),
    }


def _observer_jobs(
    document: object,
    *,
    run: Mapping[str, Any],
    phase: str,
    pr_number: int,
) -> dict[str, Any]:
    if phase not in {"C1", "C2"} or not isinstance(document, dict):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_JOBS_INVALID")
    jobs = document.get("jobs")
    if (
        not isinstance(jobs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(jobs)
        or not 1 <= len(jobs) <= 100
        or any(not isinstance(job, dict) for job in jobs)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_JOBS_INVALID")
    scope_matches = [
        cast(dict[str, Any], job)
        for job in jobs
        if cast(dict[str, Any], job).get("name") == "Recovery V2 — scope guard exact"
    ]
    tests_matches = [
        cast(dict[str, Any], job)
        for job in jobs
        if cast(dict[str, Any], job).get("name") == "tests"
    ]
    if len(scope_matches) != 1 or len(tests_matches) != 1:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_JOBS_INVALID")
    scope, tests = scope_matches[0], tests_matches[0]
    steps = tests.get("steps")
    gate_steps = (
        [
            cast(dict[str, Any], step)
            for step in steps
            if isinstance(step, dict)
            and step.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
        ]
        if isinstance(steps, list)
        else []
    )
    expected = "failure" if phase == "C1" else "success"
    run_id = run.get("id")
    scope_id = scope.get("id")
    tests_id = tests.get("id")
    if (
        any(type(value) is not int or _RUN_ID.fullmatch(str(value)) is None for value in (run_id, scope_id, tests_id))
        or scope_id == tests_id
        or scope.get("run_id") != run_id
        or tests.get("run_id") != run_id
        or type(scope.get("run_attempt")) is not int
        or scope.get("run_attempt") != 1
        or type(tests.get("run_attempt")) is not int
        or tests.get("run_attempt") != 1
        or scope.get("head_sha") != run.get("head_sha")
        or tests.get("head_sha") != run.get("head_sha")
        or scope.get("status") != "completed"
        or scope.get("conclusion") != "success"
        or tests.get("status") != "completed"
        or tests.get("conclusion") != expected
        or len(gate_steps) != 1
        or gate_steps[0].get("status") != "completed"
        or gate_steps[0].get("conclusion") != expected
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_JOBS_INVALID")
    return {
        "workflow_path": _WORKFLOW_PATH,
        "run_id": run_id,
        "run_attempt": 1,
        "event": "pull_request",
        "pull_request_number": pr_number,
        "head_ref": _BRANCH,
        "head_sha": run["head_sha"],
        "status": "completed",
        "conclusion": expected,
        "created_at": run["created_at"],
        "completed_at": run["updated_at"],
        "scope_guard_job_id": scope_id,
        "scope_guard_conclusion": "success",
        "tests_job_id": tests_id,
        "tests_conclusion": expected,
        "gate_step_conclusion": expected,
    }


def _observer_local_head(*, root: Path, expected_head_sha: str) -> None:
    if (
        _SHA.fullmatch(expected_head_sha) is None
        or _run_git(("rev-parse", "HEAD"), root=root) != expected_head_sha
        or _run_git(("branch", "--show-current"), root=root) != _BRANCH
        or _run_git(("status", "--porcelain=v1", "--untracked-files=all"), root=root) != ""
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_WORKTREE_INVALID")
    ancestry = _run_git(
        ("merge-base", "--is-ancestor", DATA_TORRENT_RECOVERY_V2_START_SHA, expected_head_sha),
        root=root,
    )
    if ancestry != "":
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_WORKTREE_INVALID")
    _assert_index_flags_clear(root=root)


def observe_pr_c_phase(
    *,
    phase: str,
    pr_number: int,
    expected_head_sha: str,
    root: Path = _ROOT,
    api_loader: Any = _api_json,
    sleeper: Any = time.sleep,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if phase not in _OBSERVER_PHASE_GET_LIMITS or type(pr_number) is not int or pr_number <= 0:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_ARGUMENT_INVALID")
    root = Path(os.path.abspath(root))
    live_clock = clock or (lambda: datetime.now(UTC))
    observed_now = (now or live_clock()).astimezone(UTC).replace(microsecond=0)
    try:
        assert_production_safety_locks(os.environ)
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage="E4",
            now=observed_now,
            repository_root=root,
            council_closure_phase=(
                "PHASE_ONE" if phase == "C1" else "TERMINAL"
            ),
        )
    except ChronosProductionError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_AUTHORITY_INVALID") from None
    operation_deadline = min(
        authority_deadline,
        observed_now + timedelta(seconds=_OBSERVER_MAXIMUM_RUNTIME_SECONDS),
    )
    _observer_local_head(root=root, expected_head_sha=expected_head_sha)
    state_base, host_identity_sha256 = _observer_state_context(root=root)
    predecessor_documents: dict[str, tuple[bytes, dict[str, Any]]] = {}
    runtime_main_sha: str | None = None
    if phase == "C1":
        try:
            validate_data_torrent_recovery_v2_phase_one_council_closure(
                repository_root=root
            )
            terminal_runtime = validate_data_torrent_recovery_v2_terminal_runtime_evidence(
                repository_root=root
            )
        except ChronosProductionError:
            raise DeliveryEvidenceV2Error(
                "RECOVERY_V2_OBSERVER_PHASE_ONE_AUTHORITY_INVALID"
            ) from None
        candidate_runtime_main_sha = terminal_runtime.get("runtime_main_sha")
        if not isinstance(candidate_runtime_main_sha, str):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
        runtime_main_sha = candidate_runtime_main_sha
    if phase in {"C2", "POSTMERGE"}:
        c1_path = state_base / _observer_relative_path(phase="C1", reservation=False)
        _c1_probe_raw, c1_probe = _strict_observer_json(c1_path, state_base=state_base)
        c1_head = c1_probe.get("head_sha")
        if not isinstance(c1_head, str):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
        c1_raw, c1 = _load_observer_result(
            phase="C1",
            root=root,
            pr_number=pr_number,
            expected_head_sha=c1_head,
            not_after=observed_now,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        predecessor_documents["C1"] = (c1_raw, c1)
        candidate_runtime_main_sha = c1.get("runtime_main_sha")
        if not isinstance(candidate_runtime_main_sha, str):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
        runtime_main_sha = candidate_runtime_main_sha
    if phase == "POSTMERGE":
        c2_path = state_base / _observer_relative_path(phase="C2", reservation=False)
        _c2_probe_raw, c2_probe = _strict_observer_json(c2_path, state_base=state_base)
        if c2_probe.get("head_sha") != expected_head_sha:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
        c2_raw, c2 = _load_observer_result(
            phase="C2",
            root=root,
            pr_number=pr_number,
            expected_head_sha=expected_head_sha,
            not_after=observed_now,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        predecessor_documents["C2"] = (c2_raw, c2)
    if not isinstance(runtime_main_sha, str) or _SHA.fullmatch(runtime_main_sha) is None:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    if phase in {"C2", "POSTMERGE"}:
        try:
            from scripts.verify_data_torrent_recovery_v2_postmerge_gate import (
                _local_candidate,
            )

            local_candidate = _local_candidate(root, observed_now=observed_now)
        except Exception:
            raise DeliveryEvidenceV2Error(
                "RECOVERY_V2_OBSERVER_TERMINAL_CANDIDATE_INVALID"
            ) from None
        if (
            local_candidate.get("runtime_main_sha") != runtime_main_sha
            or local_candidate.get("phase_one_sha")
            != predecessor_documents["C1"][1].get("head_sha")
            or local_candidate.get("candidate_sha") != expected_head_sha
            or local_candidate.get("pr_number") != pr_number
            or local_candidate.get("c1_observer_result_raw_sha256")
            != hashlib.sha256(predecessor_documents["C1"][0]).hexdigest()
            or local_candidate.get("c1_observer_run_id")
            != cast(
                dict[str, Any],
                predecessor_documents["C1"][1].get("run", {}),
            ).get("run_id")
        ):
            raise DeliveryEvidenceV2Error(
                "RECOVERY_V2_OBSERVER_TERMINAL_CANDIDATE_INVALID"
            )
    predecessor_hashes = {
        name: hashlib.sha256(value[0]).hexdigest()
        for name, value in predecessor_documents.items()
    }
    token_values = [
        value for value in (os.getenv("GH_TOKEN", ""), os.getenv("GITHUB_TOKEN", "")) if value
    ]
    if (
        not token_values
        or len(set(token_values)) != 1
        or len(token_values[0].encode("utf-8")) > _MAX_TOKEN_BYTES
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_TOKEN_INVALID")
    token = token_values[0]
    if (
        live_clock().astimezone(UTC)
        + timedelta(seconds=_API_TOTAL_TIMEOUT_SECONDS + 1)
        >= operation_deadline
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_EFFECT_DEADLINE_EXCEEDED")
    reservation_payload, _reservation = _reserve_observer(
        phase=phase,
        state_base=state_base,
        pr_number=pr_number,
        head_sha=expected_head_sha,
        runtime_main_sha=runtime_main_sha,
        host_identity_sha256=host_identity_sha256,
        predecessor_results=predecessor_hashes,
        observed_at=observed_now,
    )
    github_gets = 0

    def observer_get(path: str) -> object:
        nonlocal github_gets
        if github_gets >= _OBSERVER_PHASE_GET_LIMITS[phase]:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_GET_BUDGET_EXHAUSTED")
        current = live_clock().astimezone(UTC)
        if current + timedelta(seconds=_API_TOTAL_TIMEOUT_SECONDS + 1) >= operation_deadline:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_EFFECT_DEADLINE_EXCEEDED")
        github_gets += 1
        result = api_loader(
            path,
            token=token,
            engineering_numbers=(),
            observer_paths=frozenset({path}),
            effect_deadline_epoch=operation_deadline.timestamp(),
        )
        if live_clock().astimezone(UTC) >= operation_deadline:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_EFFECT_DEADLINE_EXCEEDED")
        return result

    pr_path = f"repos/{EXPECTED_REPOSITORY}/pulls/{pr_number}"
    pr = _observer_pull_request(
        observer_get(pr_path),
        pr_number=pr_number,
        head_sha=expected_head_sha,
        expected_base_sha=runtime_main_sha,
        merged=phase == "POSTMERGE",
    )
    merge_sha = cast(str | None, pr.get("merge_commit_sha")) if phase == "POSTMERGE" else None
    runs_path = _observer_runs_path(phase=phase, merge_sha=merge_sha)
    maximum_observations = 18 if phase == "POSTMERGE" else 28
    maximum_wait_observations = maximum_observations - 1
    expected_conclusion = "failure" if phase == "C1" else "success"
    run: dict[str, Any] | None = None
    observations = 0
    predecessor_run = (
        cast(dict[str, Any], predecessor_documents["C1"][1].get("run"))
        if phase == "C2"
        and isinstance(predecessor_documents["C1"][1].get("run"), dict)
        else None
    )
    while observations < maximum_wait_observations:
        observations += 1
        candidate = _observer_target_run(
            observer_get(runs_path),
            phase=phase,
            pr_number=pr_number,
            expected_head_sha=cast(str, merge_sha) if phase == "POSTMERGE" else expected_head_sha,
            predecessor_run=predecessor_run,
        )
        if candidate is not None and candidate.get("status") == "completed":
            if candidate.get("conclusion") != expected_conclusion:
                raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_UNEXPECTED_CONCLUSION")
            run = candidate
            break
        if observations < maximum_wait_observations:
            sleeper(_OBSERVER_POLL_SECONDS)
    if run is None:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_OBSERVATION_BUDGET_EXHAUSTED")
    if phase == "POSTMERGE":
        run_proof: dict[str, Any] = {
            "workflow_path": _WORKFLOW_PATH,
            "run_id": run["id"],
            "run_attempt": 1,
            "event": "push",
            "head_branch": "main",
            "head_sha": run["head_sha"],
            "status": "completed",
            "conclusion": "success",
            "created_at": run["created_at"],
            "completed_at": run["updated_at"],
        }
        jobs_count = 0
    else:
        jobs_path = f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run['id']}/jobs?per_page=100"
        run_proof = _observer_jobs(
            observer_get(jobs_path),
            run=run,
            phase=phase,
            pr_number=pr_number,
        )
        jobs_count = 1
    final_run = _observer_target_run(
        observer_get(runs_path),
        phase=phase,
        pr_number=pr_number,
        expected_head_sha=cast(str, merge_sha) if phase == "POSTMERGE" else expected_head_sha,
        predecessor_run=predecessor_run,
    )
    observations += 1
    if (
        final_run is None
        or _observer_run_projection(final_run, phase=phase)
        != _observer_run_projection(run, phase=phase)
        or final_run.get("status") != "completed"
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RUN_DRIFT")
    if phase == "C2":
        c1_run = predecessor_documents["C1"][1].get("run")
        if not isinstance(c1_run, dict) or c1_run.get("run_id") == run_proof.get("run_id"):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_PREDECESSOR_INVALID")
    phase_one_sha = (
        expected_head_sha
        if phase == "C1"
        else cast(str, predecessor_documents["C1"][1]["head_sha"])
    )
    candidate_sha = expected_head_sha if phase in {"C2", "POSTMERGE"} else None
    final_observed_at = live_clock().astimezone(UTC).replace(microsecond=0)
    if (
        github_gets != observations + jobs_count + 1
        or final_observed_at >= operation_deadline
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_EFFECT_DEADLINE_EXCEEDED")
    _observer_local_head(root=root, expected_head_sha=expected_head_sha)
    final_state_base, final_host_identity = _observer_state_context(root=root)
    if final_state_base != state_base or final_host_identity != host_identity_sha256:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_STATE_DRIFT")
    for predecessor_phase, (expected_payload, expected_document) in predecessor_documents.items():
        revalidated_payload, revalidated_document = _load_observer_result(
            phase=predecessor_phase,
            root=root,
            pr_number=pr_number,
            expected_head_sha=cast(str, expected_document["head_sha"]),
            not_after=final_observed_at,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        if (
            revalidated_payload != expected_payload
            or revalidated_document != expected_document
        ):
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_STATE_DRIFT")
    if phase in {"C2", "POSTMERGE"}:
        try:
            from scripts.verify_data_torrent_recovery_v2_postmerge_gate import (
                _local_candidate,
            )

            final_local_candidate = _local_candidate(root, observed_now=final_observed_at)
        except Exception:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_STATE_DRIFT") from None
        if final_local_candidate != local_candidate:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_LOCAL_STATE_DRIFT")
    final_observed_at = live_clock().astimezone(UTC).replace(microsecond=0)
    if final_observed_at >= operation_deadline:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_EFFECT_DEADLINE_EXCEEDED")
    result = {
        "schema_version": "data-torrent-recovery-v2-pr-c-observer-result-v1",
        "phase": phase,
        "verdict": {
            "C1": "PR_C_C1_EXPECTED_HOLD_CONFIRMED",
            "C2": "PR_C_C2_SUCCESS_CONFIRMED",
            "POSTMERGE": "PR_C_POSTMERGE_SUCCESS_CONFIRMED",
        }[phase],
        "mission_id": "data-torrent-recovery-v2",
        "repository": EXPECTED_REPOSITORY,
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "host_identity_sha256": host_identity_sha256,
        "pr_number": pr_number,
        "head_sha": expected_head_sha,
        "runtime_main_sha": runtime_main_sha,
        "phase_one_sha": phase_one_sha,
        "candidate_sha": candidate_sha,
        "merge_sha": merge_sha,
        "observed_at": final_observed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reservation": {
            "namespace": _observer_relative_path(phase=phase, reservation=True).as_posix(),
            "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
            "conservative_github_api_gets": _OBSERVER_PHASE_GET_LIMITS[phase],
            "second_invocation_allowed": False,
        },
        "predecessor_results": predecessor_hashes,
        "run": run_proof,
        "github_gets_exact": {
            "pull_request": 1,
            "run_inventory_observations": observations,
            "final_run_inventory_rechecks_exact": 1,
            "exact_run_jobs": jobs_count,
            "total": github_gets,
        },
        "github_gets_conservative_limit": _OBSERVER_PHASE_GET_LIMITS[phase],
        "automatic_retries": 0,
    }
    target = state_base / _observer_relative_path(phase=phase, reservation=False)
    try:
        _recovery_v2_publish_exclusive_bytes(
            target,
            canonical_json_bytes(result) + b"\n",
            repository_root=state_base,
        )
    except (ChronosProductionError, FileExistsError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_RESULT_WRITE_INVALID") from None
    _load_observer_result(
        phase=phase,
        root=root,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        not_after=final_observed_at,
        state_base=state_base,
        host_identity_sha256=host_identity_sha256,
    )
    return result


def materialize_delivery_evidence(
    *,
    pr_a_number: int,
    reservation_commit_sha: str,
    pr_b_number: int | None = None,
    root: Path = _ROOT,
    api_loader: Any = _api_json,
) -> dict[str, object]:
    root = Path(os.path.abspath(root))
    if type(pr_a_number) is not int or pr_a_number <= 0 or (
        pr_b_number is not None
        and (type(pr_b_number) is not int or pr_b_number <= 0 or pr_b_number == pr_a_number)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_ARGUMENT_INVALID")
    engineering_numbers = (pr_a_number,) if pr_b_number is None else (pr_a_number, pr_b_number)
    durable_reservation_path = root / DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH
    receipt_path = root / DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH
    for path in (durable_reservation_path, receipt_path):
        _assert_unused_output(path, root=root)
    try:
        assert_production_safety_locks(os.environ)
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage="E4",
            repository_root=root,
            council_closure_phase="PHASE_ONE",
        )
        validate_data_torrent_recovery_v2_phase_one_council_closure(repository_root=root)
        phase_one = validate_data_torrent_recovery_v2_terminal_runtime_evidence(
            repository_root=root
        )
    except ChronosProductionError:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_AUTHORITY_INVALID") from None
    operation_deadline = min(
        authority_deadline.astimezone(UTC),
        datetime.now(UTC) + timedelta(seconds=_MATERIALIZER_MAXIMUM_RUNTIME_SECONDS),
    )
    if datetime.now(UTC) >= operation_deadline:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_EFFECT_DEADLINE_EXCEEDED")
    runtime_main_sha = phase_one.get("runtime_main_sha")
    quiescence = phase_one.get("quiescence")
    if (
        not isinstance(runtime_main_sha, str)
        or _SHA.fullmatch(runtime_main_sha) is None
        or not isinstance(quiescence, dict)
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_INVALID")
    evidence_commit_sha = _run_git(("rev-parse", "HEAD"), root=root)
    if _SHA.fullmatch(evidence_commit_sha) is None:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_WORKTREE_INVALID")
    _assert_delivery_worktree(
        root=root,
        evidence_commit_sha=evidence_commit_sha,
        runtime_main_sha=runtime_main_sha,
        reservation_commit_sha=reservation_commit_sha,
    )
    observer_state_base, observer_host_identity = _observer_state_context(root=root)
    c1_result_path = observer_state_base / _observer_relative_path(
        phase="C1",
        reservation=False,
    )
    _c1_unvalidated_payload, c1_unvalidated = _strict_observer_json(
        c1_result_path,
        state_base=observer_state_base,
    )
    observed_pr_c_number = c1_unvalidated.get("pr_number")
    if type(observed_pr_c_number) is not int or observed_pr_c_number <= 0:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    _c1_observer_payload, c1_observer = _load_observer_result(
        phase="C1",
        root=root,
        pr_number=observed_pr_c_number,
        expected_head_sha=evidence_commit_sha,
        not_after=datetime.now(UTC),
        state_base=observer_state_base,
        host_identity_sha256=observer_host_identity,
    )
    if c1_observer.get("runtime_main_sha") != runtime_main_sha:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    local_chain = _local_engineering_chain(root=root, runtime_main_sha=runtime_main_sha)
    if [row["role"] for row in local_chain] != (
        ["PR_A"] if pr_b_number is None else ["PR_A", "PR_B"]
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")
    try:
        ledger_payload = _recovery_v2_evidence_bytes(
            root / "reports" / "council" / "decision-ledger.jsonl",
            repository_root=root,
            maximum_bytes=16 * 1024 * 1024,
        )
        last_record = json.loads(ledger_payload.splitlines()[-1])
        active_release_claim = last_record["proof"][0]
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_COUNCIL_INVALID") from None
    if not _release_claim_matches_engineering_chain(
        active_release_claim,
        pr_b_number=pr_b_number,
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_COUNCIL_INVALID")
    token_values = [
        value for value in (os.getenv("GH_TOKEN", ""), os.getenv("GITHUB_TOKEN", "")) if value
    ]
    if (
        not token_values
        or len(set(token_values)) != 1
        or len(token_values[0].encode("utf-8")) > _MAX_TOKEN_BYTES
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TOKEN_INVALID")
    token = token_values[0]
    get_count = 2 * len(engineering_numbers) + 3
    counters = {
        "engineering_pull_requests": len(engineering_numbers),
        "safe_v2_run_inventory": 1,
        "safe_v2_exact_head_jobs": len(engineering_numbers),
        "terminal_phase_one_jobs": 1,
        "terminal_open_pr_inventory": 1,
        "total": get_count,
    }
    live_run_id = quiescence.get("observed_after_live_run_id")
    if type(live_run_id) is not int or _RUN_ID.fullmatch(str(live_run_id)) is None:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_PHASE_ONE_INVALID")
    try:
        (
            local_terminal_payload,
            _local_terminal_intent,
            local_reservation_payload,
            _local_delivery_intent,
            local_validated_head_sha,
        ) = _validate_authoritative_intent_set(
            root=root,
            main_sha=runtime_main_sha,
            live_run_id=str(live_run_id),
            engineering_numbers=engineering_numbers,
            reservation_commit_sha=reservation_commit_sha,
            require_head_equals_reservation=False,
            verify_remote=False,
        )
        _reserve_materializer_execution(
            kind="DELIVERY",
            root=root,
            main_sha=runtime_main_sha,
            head_sha=local_validated_head_sha,
            reservation_commit_sha=reservation_commit_sha,
            terminal_intent_payload=local_terminal_payload,
            delivery_intent_payload=local_reservation_payload,
            remote_reads_conservatively_consumed=get_count + 1,
            github_gets_conservatively_consumed=get_count,
            artifact_downloads_conservatively_consumed=0,
            additional_binding={
                "c1_observer_result_raw_sha256": hashlib.sha256(
                    _c1_observer_payload
                ).hexdigest(),
                "engineering_pull_request_numbers": list(engineering_numbers),
                "pr_c_number": observed_pr_c_number,
            },
        )
        (
            _terminal_payload,
            _terminal_intent,
            reservation_payload,
            reservation,
            validated_head_sha,
        ) = _validate_authoritative_intent_set(
            root=root,
            main_sha=runtime_main_sha,
            live_run_id=str(live_run_id),
            engineering_numbers=engineering_numbers,
            reservation_commit_sha=reservation_commit_sha,
            require_head_equals_reservation=False,
            effect_deadline_epoch=operation_deadline.timestamp(),
        )
    except TerminalEvidenceV2Error:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_RESERVATION_INVALID") from None
    if (
        validated_head_sha != evidence_commit_sha
        or reservation.get("github_gets_upper_bound") != counters
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_RESERVATION_INVALID")

    api_gets = 0

    def delivery_get(path: str, **bindings: object) -> object:
        nonlocal api_gets
        if api_gets >= get_count:
            raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_GET_BUDGET_EXHAUSTED")
        if (
            datetime.now(UTC) + timedelta(seconds=_API_TOTAL_TIMEOUT_SECONDS + 1)
            >= operation_deadline
        ):
            raise DeliveryEvidenceV2Error(
                "RECOVERY_V2_DELIVERY_EFFECT_DEADLINE_EXCEEDED"
            )
        api_gets += 1
        result = api_loader(
            path,
            token=token,
            effect_deadline_epoch=operation_deadline.timestamp(),
            **bindings,
        )
        if datetime.now(UTC) >= operation_deadline:
            raise DeliveryEvidenceV2Error(
                "RECOVERY_V2_DELIVERY_EFFECT_DEADLINE_EXCEEDED"
            )
        return result

    engineering: list[dict[str, object]] = []
    merge_times: list[datetime] = []
    for number, local in zip(engineering_numbers, local_chain, strict=True):
        document = delivery_get(
            f"repos/{EXPECTED_REPOSITORY}/pulls/{number}",
            engineering_numbers=engineering_numbers,
        )
        row, merged_at = _engineering_pr(document=document, number=number, local=local)
        engineering.append(row)
        merge_times.append(merged_at)
    if any(later <= earlier for earlier, later in zip(merge_times, merge_times[1:])):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_MERGE_INVALID")

    terminal_document = delivery_get(
        _open_pr_path(),
        engineering_numbers=engineering_numbers,
    )
    terminal_pr, terminal_created_at = _terminal_pr(
        document=terminal_document,
        runtime_main_sha=runtime_main_sha,
        evidence_commit_sha=evidence_commit_sha,
        reservation_commit_sha=reservation_commit_sha,
    )
    if (
        terminal_pr.get("number") != observed_pr_c_number
        or c1_observer.get("pr_number") != terminal_pr.get("number")
        or cast(dict[str, Any], c1_observer.get("run", {})).get("run_id")
        is None
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    if merge_times[-1] >= terminal_created_at:
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TERMINAL_PR_INVALID")

    runs_document = delivery_get(
        _runs_path(),
        engineering_numbers=engineering_numbers,
    )
    grouped, exact_runs, phase_one_run = _safe_run_inventory(
        document=runs_document,
        engineering=engineering,
        terminal_pr_number=cast(int, terminal_pr["number"]),
        terminal_head_sha=evidence_commit_sha,
    )
    by_role: list[dict[str, object]] = []
    for row in engineering:
        role = cast(str, row["role"])
        number = cast(int, row["number"])
        run = exact_runs[number]
        run_id = cast(int, run["id"])
        jobs_document = delivery_get(
            f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100",
            engineering_numbers=engineering_numbers,
            safe_run_ids=frozenset({run_id}),
        )
        by_role.append(
            {
                "role": role,
                "pull_request_number": number,
                "cycles_observed": len(grouped[number]),
                "run_ids": sorted(cast(int, value["id"]) for value in grouped[number]),
                "exact_head_safe_v2": _safe_jobs(
                    document=jobs_document,
                    run=run,
                    pull_request_number=number,
                ),
            }
        )
    phase_one_run_id = cast(int, phase_one_run["id"])
    phase_one_jobs_document = delivery_get(
        f"repos/{EXPECTED_REPOSITORY}/actions/runs/{phase_one_run_id}/jobs?per_page=100",
        engineering_numbers=engineering_numbers,
        safe_run_ids=frozenset({phase_one_run_id}),
    )
    phase_one_safe = _phase_one_jobs(
        document=phase_one_jobs_document,
        run=phase_one_run,
        pull_request_number=cast(int, terminal_pr["number"]),
    )
    c1_observed_run = c1_observer.get("run")
    if (
        not isinstance(c1_observed_run, dict)
        or c1_observed_run.get("run_id") != phase_one_safe.get("run_id")
        or c1_observed_run.get("head_sha") != phase_one_safe.get("head_sha")
        or c1_observed_run.get("scope_guard_job_id")
        != phase_one_safe.get("scope_guard_job_id")
        or c1_observed_run.get("tests_job_id") != phase_one_safe.get("tests_job_id")
        or c1_observed_run.get("tests_conclusion") != "failure"
        or c1_observed_run.get("gate_step_conclusion") != "failure"
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_BINDING_INVALID")
    safe_cycles = {
        "by_role": by_role,
        "engineering_cycles_observed": sum(
            cast(int, row["cycles_observed"]) for row in by_role
        ),
        "cycles_per_engineering_pr_maximum": 3,
        "engineering_cycles_total_maximum": 6,
        "failed_run_reruns": 0,
        "historical_ci_runs": 0,
        "phase_budgets_fungible": False,
    }
    quiescence_observed_at = _timestamp(quiescence.get("observed_at"))
    observed_now = datetime.now(UTC).replace(microsecond=0)
    if (
        api_gets != get_count
        or observed_now >= operation_deadline
        or not quiescence_observed_at <= terminal_created_at <= observed_now
    ):
        raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_TEMPORAL_INVALID")
    observed_at = observed_now.isoformat().replace("+00:00", "Z")
    receipt = {
        "schema_version": "data-torrent-recovery-v2-delivery-receipt-v1",
        "verdict": "ENGINEERING_DELIVERY_AND_TERMINAL_PR_OPEN_CONFIRMED",
        "repository": EXPECTED_REPOSITORY,
        "runtime_main_sha": runtime_main_sha,
        "observed_at": observed_at,
        "engineering_pull_requests": engineering,
        "active_engineering_role": engineering[-1]["role"],
        "safe_v2_cycles": safe_cycles,
        "terminal_pull_request": terminal_pr,
        "terminal_phase_one_expected_hold": phase_one_safe,
        "pr_c_observer_evidence": {
            "phase": "C1",
            "scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
            "namespace": _observer_relative_path(phase="C1", reservation=False).as_posix(),
            "raw_sha256": hashlib.sha256(_c1_observer_payload).hexdigest(),
            "run_id": c1_observed_run["run_id"],
            "authoritative": False,
        },
        "reservation": {
            "source_path": DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            "durable_path": DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
            "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
            "reservation_commit_sha": reservation_commit_sha,
            "remote_branch_verified_before_github_reads": True,
        },
        "phase_one_git_effects_exact": {
            "commits": 1,
            "non_force_pushes": 1,
            "force_pushes": 0,
        },
        "github_gets_exact": counters,
        "git_remote_ref_observations_exact": 1,
        "remote_gets_exact_total": get_count + 1,
        "automatic_retries": 0,
    }
    _assert_delivery_worktree(
        root=root,
        evidence_commit_sha=evidence_commit_sha,
        runtime_main_sha=runtime_main_sha,
        reservation_commit_sha=reservation_commit_sha,
    )
    _write_exclusive(durable_reservation_path, reservation_payload, root=root)
    _write_exclusive(receipt_path, _json_bytes(receipt), root=root)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe-phase", choices=("C1", "C2", "POSTMERGE"))
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--pr-a-number", type=int)
    parser.add_argument("--pr-b-number", type=int)
    parser.add_argument("--reservation-commit-sha")
    args = parser.parse_args()
    try:
        if args.observe_phase is not None:
            if (
                args.pr_number is None
                or args.expected_head_sha is None
                or args.pr_a_number is not None
                or args.pr_b_number is not None
                or args.reservation_commit_sha is not None
            ):
                raise DeliveryEvidenceV2Error("RECOVERY_V2_OBSERVER_ARGUMENT_INVALID")
            result = observe_pr_c_phase(
                phase=cast(str, args.observe_phase),
                pr_number=cast(int, args.pr_number),
                expected_head_sha=cast(str, args.expected_head_sha),
            )
        else:
            if (
                args.pr_number is not None
                or args.expected_head_sha is not None
                or args.pr_a_number is None
                or args.reservation_commit_sha is None
            ):
                raise DeliveryEvidenceV2Error("RECOVERY_V2_DELIVERY_ARGUMENT_INVALID")
            result = materialize_delivery_evidence(
                pr_a_number=cast(int, args.pr_a_number),
                pr_b_number=cast(int | None, args.pr_b_number),
                reservation_commit_sha=cast(str, args.reservation_commit_sha),
            )
    except Exception as error:
        print(
            str(error)
            if isinstance(error, DeliveryEvidenceV2Error)
            else "RECOVERY_V2_DELIVERY_MATERIALIZATION_FAILED"
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
