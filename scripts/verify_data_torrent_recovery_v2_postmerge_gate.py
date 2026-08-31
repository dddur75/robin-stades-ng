"""Verify the external PR-C postmerge facts that cannot be committed in PR-C itself."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import re
import stat
import subprocess  # nosec B404 - fixed local git executable and argument vectors only.
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS,
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_REPORT_SCHEMA,
    DATA_TORRENT_RECOVERY_V2_START_SHA,
    DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH,
    DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    _recovery_v2_publish_exclusive_bytes,
    canonical_json_bytes,
    data_torrent_recovery_v2_postmerge_final_gate_contract,
    validate_data_torrent_recovery_v2_authority,
    validate_data_torrent_recovery_v2_terminal_council_closure,
)

if __package__:
    from scripts.check_chronos_github_hold_v3 import (
        LEGACY_PROVIDER_BRANCH,
        RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS,
        _github_get,
        verify_hold,
    )
    from scripts.check_data_torrent_recovery_v2_scope import (
        _TERMINAL_EVIDENCE_PREFIX,
        _allowed_paths,
        _candidate_topology,
    )
    from scripts.github_release_attestation_v2 import _api
else:
    from check_chronos_github_hold_v3 import (  # type: ignore[import-not-found,no-redef]
        LEGACY_PROVIDER_BRANCH,
        RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS,
        _github_get,
        verify_hold,
    )
    from check_data_torrent_recovery_v2_scope import (  # type: ignore[import-not-found,no-redef]
        _TERMINAL_EVIDENCE_PREFIX,
        _allowed_paths,
        _candidate_topology,
    )
    from github_release_attestation_v2 import _api  # type: ignore[import-not-found,no-redef]

_BRANCH = "codex/data-torrent-recovery-v2"
_WORKFLOW_PATH = ".github/workflows/ci-safe-v2.yml"
_PR_C_TITLE = "[DATA_TORRENT_RECOVERY_V2] PR-C"
_SCOPE_JOB_NAME = "Recovery V2 — scope guard exact"
_WITNESS_JOB_NAME = "Recovery V2 — final gate witness"
_TESTS_JOB_NAME = "tests"
_WITNESS_FILENAME = "data-torrent-recovery-v2-final-gate-witness-v1.json"
_WITNESS_SCHEMA = "data-torrent-recovery-v2-final-gate-witness-v1"
_FINAL_SCHEMA = DATA_TORRENT_RECOVERY_V2_POSTMERGE_FINAL_REPORT_SCHEMA
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_MAX_GIT_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_WITNESS_BYTES = 1024 * 1024
_FINAL_GITHUB_GETS_EXACT = 34
_FINAL_ARTIFACT_DOWNLOADS_EXACT = 1
_GITHUB_JSON_READ_MARGIN_SECONDS = 7
_GITHUB_ARTIFACT_READ_MARGIN_SECONDS = 66
_FULL_HOLD_READ_MARGIN_SECONDS = 75
_RESERVATION_RELATIVE_PATH = Path(
    "RobinCouncilOS"
    "/dddur75__robin-stades-ng"
    "/data-torrent-recovery-v2"
    f"/{DATA_TORRENT_RECOVERY_V2_START_SHA}"
    "/postmerge-final-gate-reservation-v1.json"
)
_PREREQUISITE_JOBS = frozenset(
    {
        "data-torrent-recovery-v2-scope-guard",
        "historical-deep-quality",
        "bounded-live-canary-ubuntu",
        "bounded-live-canary-windows",
        "frozen-evidence-windows",
        "chronos-postgresql-profiles",
        "chronos-end-to-end-live-path-replay",
        "chronos-residual-fault-matrix",
        "chronos-exact-workflow-entrypoint",
        "historical-authority-workflows-disabled",
        "tests",
        "visual-regression",
    }
)


class RecoveryV2PostmergeGateError(RuntimeError):
    """Sanitized final-gate rejection."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecoveryV2PostmergeGateError(f"RECOVERY_V2_FINAL_{field}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RecoveryV2PostmergeGateError(f"RECOVERY_V2_FINAL_{field}_INVALID") from None
    if (
        parsed.utcoffset() != UTC.utcoffset(parsed)
        or parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value
    ):
        raise RecoveryV2PostmergeGateError(f"RECOVERY_V2_FINAL_{field}_INVALID")
    return parsed


def _clock_utc(clock: Callable[[], datetime]) -> datetime:
    current = clock()
    if current.tzinfo is None:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_CLOCK_INVALID")
    return current.astimezone(UTC)


def _require_effect_window(
    clock: Callable[[], datetime],
    *,
    deadline: datetime,
    margin_seconds: int,
) -> datetime:
    current = _clock_utc(clock)
    if current + timedelta(seconds=margin_seconds) >= deadline:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_EFFECT_DEADLINE_EXCEEDED")
    return current


def _require_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX_40.fullmatch(value) is None:
        raise RecoveryV2PostmergeGateError(f"RECOVERY_V2_FINAL_{field}_INVALID")
    return value


def _git(root: Path, *arguments: str) -> bytes:
    inherited_names = {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
    }
    environment = {name: os.environ[name] for name in inherited_names if name in os.environ}
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "LC_ALL": "C",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-final-git-hooks-") as hooks:
            completed = subprocess.run(  # nosec B603 B607 - fixed executable and local args.
                [
                    "git",
                    "--no-replace-objects",
                    "-c",
                    "core.quotepath=false",
                    "-c",
                    f"core.hooksPath={hooks}",
                    "-c",
                    "submodule.recurse=false",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-c",
                    "protocol.allow=never",
                    *arguments,
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )
    except (OSError, subprocess.SubprocessError):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_GIT_INVALID") from None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_GIT_INVALID")
    return completed.stdout


def _strict_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        payload = path.read_bytes()
    except OSError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_EVIDENCE_INVALID") from None
    if (
        not payload
        or len(payload) > _MAX_WITNESS_BYTES
        or payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in payload
        or not payload.endswith(b"\n")
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_EVIDENCE_INVALID")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_EVIDENCE_INVALID") from None
    if not isinstance(document, dict) or payload != canonical_json_bytes(document) + b"\n":
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_EVIDENCE_INVALID")
    return payload, cast(dict[str, Any], document)


def _terminal_council_binding(
    root: Path,
    *,
    terminal_record_hash: str,
) -> tuple[bytes, str]:
    ledger_path = root / "reports" / "council" / "decision-ledger.jsonl"
    try:
        ledger_payload = ledger_path.read_bytes()
    except OSError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID") from None
    if (
        not ledger_payload
        or len(ledger_payload) > 16 * 1024 * 1024
        or ledger_payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in ledger_payload
        or not ledger_payload.endswith(b"\n")
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID")
    try:
        record = json.loads(
            ledger_payload.splitlines()[-1],
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        context = record["context"]
        terminal_binding = context["terminal_report"]
    except (IndexError, KeyError, TypeError, UnicodeDecodeError, ValueError):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID") from None
    if (
        not isinstance(record, dict)
        or record.get("hash") != terminal_record_hash
        or not isinstance(context, dict)
        or not isinstance(terminal_binding, dict)
        or set(terminal_binding) != {"path", "raw_sha256"}
        or terminal_binding.get("path") != DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
        or not isinstance(terminal_binding.get("raw_sha256"), str)
        or _HEX_64.fullmatch(cast(str, terminal_binding["raw_sha256"])) is None
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID")
    return ledger_payload, cast(str, terminal_binding["raw_sha256"])


def _host_identity_sha256() -> str:
    try:
        if os.name == "nt":
            import ctypes
            import winreg

            username = ctypes.create_unicode_buffer(257)
            username_size = ctypes.c_ulong(len(username))
            if not ctypes.windll.advapi32.GetUserNameW(
                username, ctypes.byref(username_size)
            ):
                raise OSError
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                machine_guid = str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip().lower()
            if not machine_guid or not username.value:
                raise OSError
            material = f"windows\0{machine_guid}\0{username.value.casefold()}".encode("utf-8")
        else:
            import pwd

            getuid = getattr(os, "getuid", None)
            getpwuid = getattr(pwd, "getpwuid", None)
            if not callable(getuid) or not callable(getpwuid):
                raise OSError
            uid = getuid()
            principal = getpwuid(uid)
            machine_id = next(
                (
                    path.read_text(encoding="ascii").strip().lower()
                    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
                    if path.is_file()
                ),
                "",
            )
            if not machine_id or not principal.pw_name:
                raise OSError
            material = f"posix\0{machine_id}\0{uid}\0{principal.pw_name}".encode("utf-8")
    except (OSError, KeyError, UnicodeError):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOST_IDENTITY_INVALID") from None
    return hashlib.sha256(b"data-torrent-recovery-v2-host-v1\0" + material).hexdigest()


def _state_base() -> Path:
    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32_768)
            result = ctypes.windll.shell32.SHGetFolderPathW(
                None,
                0x001C,
                None,
                0,
                buffer,
            )
            if result != 0 or not buffer.value:
                raise OSError
            base = Path(os.path.abspath(buffer.value))
        except (OSError, ValueError):
            raise RecoveryV2PostmergeGateError(
                "RECOVERY_V2_FINAL_STATE_ROOT_INVALID"
            ) from None
    else:
        try:
            import pwd

            getuid = getattr(os, "getuid", None)
            getpwuid = getattr(pwd, "getpwuid", None)
            if not callable(getuid) or not callable(getpwuid):
                raise OSError
            principal = getpwuid(getuid())
            base = Path(os.path.abspath(principal.pw_dir))
        except (KeyError, OSError):
            raise RecoveryV2PostmergeGateError(
                "RECOVERY_V2_FINAL_STATE_ROOT_INVALID"
            ) from None
    try:
        metadata = base.stat()
    except OSError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_STATE_ROOT_INVALID") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_STATE_ROOT_INVALID")
    getuid = getattr(os, "getuid", None)
    if callable(getuid) and (metadata.st_uid != getuid() or metadata.st_mode & 0o022):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_STATE_ROOT_INVALID")
    return base


def _reserve_final_gate(
    root: Path,
    *,
    state_base: Path,
    local: Mapping[str, Any],
    pr_number: int,
    postmerge_run_id: int,
    observed_at: datetime,
    host_identity_sha256: str,
    observer_chain_result_raw_sha256: str,
) -> dict[str, Any]:
    candidate_report = local.get("candidate_report")
    conditional_gate = (
        candidate_report.get("postmerge_final_gate")
        if isinstance(candidate_report, dict)
        else None
    )
    conditional_hash = (
        conditional_gate.get("conditional_contract_sha256")
        if isinstance(conditional_gate, dict)
        else None
    )
    if (
        not isinstance(conditional_hash, str)
        or _HEX_64.fullmatch(conditional_hash) is None
        or _HEX_64.fullmatch(observer_chain_result_raw_sha256) is None
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    reservation = {
        "artifact_downloads_conservatively_consumed": _FINAL_ARTIFACT_DOWNLOADS_EXACT,
        "automatic_retries": 0,
        "candidate_sha": local["candidate_sha"],
        "candidate_tree_sha": local["candidate_tree_sha"],
        "conditional_contract_sha256": conditional_hash,
        "github_api_gets_conservatively_consumed": _FINAL_GITHUB_GETS_EXACT,
        "host_identity_sha256": host_identity_sha256,
        "local_receipt_authoritative": False,
        "mission_id": "data-torrent-recovery-v2",
        "observer_chain_result_raw_sha256": observer_chain_result_raw_sha256,
        "observed_at": observed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "postmerge_run_id": postmerge_run_id,
        "pr_number": pr_number,
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "repository": EXPECTED_REPOSITORY,
        "reservation_status": "RESERVED_BEFORE_FIRST_EXTERNAL_READ",
        "schema_version": "data-torrent-recovery-v2-postmerge-final-gate-reservation-v1",
        "second_invocation_allowed": False,
    }
    payload = canonical_json_bytes(reservation) + b"\n"
    target = state_base / _RESERVATION_RELATIVE_PATH
    lexical_root = Path(os.path.abspath(root))
    lexical_target = Path(os.path.abspath(target))
    if lexical_target.is_relative_to(lexical_root):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_STATE_ROOT_INVALID")
    try:
        _recovery_v2_publish_exclusive_bytes(
            target,
            payload,
            repository_root=state_base,
        )
    except (ChronosProductionError, FileExistsError):
        raise RecoveryV2PostmergeGateError(
            "RECOVERY_V2_FINAL_INVOCATION_ALREADY_RESERVED"
        ) from None
    return {
        "path_scope": "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE",
        "namespace": _RESERVATION_RELATIVE_PATH.as_posix(),
        "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "local_receipt_authoritative": False,
        "conservative_github_api_gets": _FINAL_GITHUB_GETS_EXACT,
        "conservative_artifact_downloads": _FINAL_ARTIFACT_DOWNLOADS_EXACT,
        "host_identity_sha256": host_identity_sha256,
        "observer_chain_result_raw_sha256": observer_chain_result_raw_sha256,
    }


def _local_candidate(root: Path, *, observed_now: datetime) -> dict[str, Any]:
    try:
        terminal_record_hash = validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=observed_now,
        )
    except ChronosProductionError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID") from None
    ledger_payload, council_terminal_sha256 = _terminal_council_binding(
        root,
        terminal_record_hash=terminal_record_hash,
    )
    if _git(root, "status", "--porcelain=v2", "--untracked-files=all") != b"":
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_WORKTREE_NOT_CLEAN")
    if _git(root, "branch", "--show-current").decode("utf-8").strip() != _BRANCH:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_BRANCH_INVALID")
    head_sha = _require_sha(
        _git(root, "rev-parse", "HEAD").decode("ascii").strip(),
        field="C2_SHA",
    )
    index = _git(root, "ls-files", "-v", "-z")
    try:
        index_lines = [item.decode("utf-8") for item in index.split(b"\0") if item]
    except UnicodeDecodeError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_INDEX_INVALID") from None
    if any(not line.startswith("H ") for line in index_lines):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_INDEX_INVALID")
    terminal_payload, terminal = _strict_json(root / DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH)
    delivery_payload, delivery_receipt = _strict_json(
        root / DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH
    )
    _quiescence_payload, quiescence = _strict_json(
        root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH
    )
    if hashlib.sha256(terminal_payload).hexdigest() != council_terminal_sha256:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID")
    runtime_main_sha = _require_sha(terminal.get("runtime_main_sha"), field="RUNTIME_MAIN_SHA")
    delivery = terminal.get("delivery")
    expected_final_gate = data_torrent_recovery_v2_postmerge_final_gate_contract(root)
    if (
        terminal.get("report_role") != "CANDIDATE_NOT_TERMINAL"
        or terminal.get("mission_complete") is not False
        or terminal.get("data_torrent_ready") is not False
        or terminal.get("global_quiescence") is not False
        or terminal.get("final_verdict") != "PASS_AND_HOLD"
        or terminal.get("postmerge_final_gate") != expected_final_gate
        or not isinstance(delivery, dict)
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    phase_one_sha = _require_sha(
        cast(dict[str, Any], delivery).get("pr_c_phase_one_head_sha"),
        field="C1_SHA",
    )
    pr_number = cast(dict[str, Any], delivery).get("pr_c")
    c1_observer = delivery_receipt.get("pr_c_observer_evidence")
    if (
        type(pr_number) is not int
        or pr_number <= 0
        or not isinstance(c1_observer, dict)
        or c1_observer.get("phase") != "C1"
        or c1_observer.get("scope") != "HOST_LOCAL_OS_STATE_OUTSIDE_WORKTREE"
        or c1_observer.get("authoritative") is not False
        or not isinstance(c1_observer.get("raw_sha256"), str)
        or _HEX_64.fullmatch(cast(str, c1_observer["raw_sha256"])) is None
        or type(c1_observer.get("run_id")) is not int
        or _RUN_ID.fullmatch(str(c1_observer.get("run_id"))) is None
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_INVALID")
    allowed = _allowed_paths(root)
    topology = _candidate_topology(
        root,
        base=runtime_main_sha,
        tip=head_sha,
        phase="PR_C",
        terminal_evidence={
            path for path in allowed if path.startswith(_TERMINAL_EVIDENCE_PREFIX)
        },
    )
    if len(topology) != 3 or topology[1].get("sha") != phase_one_sha:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_CANDIDATE_TOPOLOGY_INVALID")
    tree_sha = _require_sha(
        _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip(),
        field="C2_TREE_SHA",
    )
    terminal_all_payloads = terminal.get("all_payload_sha256")
    if (
        not isinstance(terminal_all_payloads, list)
        or hashlib.sha256(delivery_payload).hexdigest() not in terminal_all_payloads
        or terminal.get("runtime_close_quiescence")
        != {
            "path": DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            "raw_sha256": hashlib.sha256(_quiescence_payload).hexdigest(),
        }
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_SNAPSHOT_INVALID")
    final_ledger_payload, final_council_terminal_sha256 = _terminal_council_binding(
        root,
        terminal_record_hash=terminal_record_hash,
    )
    if (
        final_ledger_payload != ledger_payload
        or final_council_terminal_sha256 != council_terminal_sha256
        or _strict_json(root / DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH)[0]
        != terminal_payload
        or _strict_json(root / DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH)[0]
        != delivery_payload
        or _strict_json(root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH)[0]
        != _quiescence_payload
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_STATE_DRIFT")
    return {
        "terminal_record_hash": terminal_record_hash,
        "terminal_report_sha256": hashlib.sha256(terminal_payload).hexdigest(),
        "delivery_receipt_sha256": hashlib.sha256(delivery_payload).hexdigest(),
        "runtime_main_sha": runtime_main_sha,
        "phase_one_sha": phase_one_sha,
        "candidate_sha": head_sha,
        "candidate_tree_sha": tree_sha,
        "pr_number": pr_number,
        "c1_observer_result_raw_sha256": c1_observer["raw_sha256"],
        "c1_observer_run_id": c1_observer["run_id"],
        "runtime_close_observed_at": quiescence.get("observed_at"),
        "delivery_observed_at": delivery_receipt.get("observed_at"),
        "candidate_report_generated_at": terminal.get("generated_at"),
        "candidate_topology": topology,
        "candidate_report": terminal,
    }


def _compose_final_report(
    *,
    local: Mapping[str, Any],
    reservation: Mapping[str, Any],
    pr: Mapping[str, Any],
    runs: list[dict[str, Any]],
    premerge_job_proof: Mapping[str, Any],
    postmerge: Mapping[str, Any],
    scope_job: Mapping[str, Any],
    witness_job: Mapping[str, Any],
    artifact: Mapping[str, Any],
    witness: Mapping[str, Any],
    hold: Mapping[str, Any],
    merge_sha: str,
    final_observed_at: datetime,
    authority_started_at: datetime,
    authority_expiry: datetime,
    github_gets: int,
) -> dict[str, Any]:
    candidate = local.get("candidate_report")
    if not isinstance(candidate, dict):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    final = cast(dict[str, Any], copy.deepcopy(candidate))
    conditional_gate = candidate.get("postmerge_final_gate")
    if not isinstance(conditional_gate, dict):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    conditional_hash = conditional_gate.get("conditional_contract_sha256")
    if not isinstance(conditional_hash, str) or _HEX_64.fullmatch(conditional_hash) is None:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    completion = final.get("completion_states")
    delivery = final.get("delivery")
    if not isinstance(completion, dict) or not isinstance(delivery, dict):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_COUNCIL_CANDIDATE_INVALID")
    final["schema_version"] = _FINAL_SCHEMA
    final["report_role"] = "FINAL_EXTERNAL_COMPOSITE_NON_DURABLE"
    final["generated_at"] = final_observed_at.isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    mission_started_at = _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE, field="MISSION_STARTED_AT")
    final["duration_seconds"] = int((final_observed_at - mission_started_at).total_seconds())
    final["mission_complete"] = True
    final["data_torrent_ready"] = True
    final["semantic_verdict"] = "DATA_TORRENT_READY"
    final["final_verdict"] = "PASS_AND_HOLD"
    final["completion_states"] = {field: True for field in completion}
    final_delivery = cast(dict[str, Any], copy.deepcopy(delivery))
    final_delivery.update(
        {
            "final_main_sha": merge_sha,
            "final_main_sha_definition": "EXACT_PR_C_MERGE_COMMIT_AFTER_POSTMERGE_SAFE_V2",
            "pr_c_merge": dict(pr),
            "pr_c_premerge_safe_v2": {
                "phase_one_expected_hold": {
                    "run_id": runs[0]["id"],
                    "head_sha": runs[0]["head_sha"],
                    "conclusion": "failure",
                },
                "candidate_exact_head": {
                    "run_id": runs[1]["id"],
                    "head_sha": runs[1]["head_sha"],
                    "conclusion": "success",
                },
                **dict(premerge_job_proof),
                "cycles_exact": 2,
                "inventory_observations_exact": 2,
                "reruns": 0,
            },
            "pr_c_postmerge_safe_v2": dict(postmerge),
        }
    )
    final["delivery"] = final_delivery
    final["postmerge_final_gate"] = {
        "state": "SATISFIED",
        "committed_in_pr_c": False,
        "conditional_contract_sha256": conditional_hash,
        "candidate_report_sha256": local["terminal_report_sha256"],
        "candidate_terminal_record_hash": local["terminal_record_hash"],
        "entrypoint": conditional_gate["entrypoint"],
        "result_schema": _FINAL_SCHEMA,
        "remote_authority": "GITHUB_RUN_JOB_ARTIFACT_AND_LIVE_API_STATE",
        "local_receipt_authoritative": False,
        "invocation_reservation": dict(reservation),
        "authority_window": {
            "scale_stage": "E4",
            "admitted_at": authority_started_at.isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "expires_at": authority_expiry.isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "maximum_gate_runtime_seconds": (
                DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS
            ),
            "mission_time_budget_seconds": DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS,
        },
        "evidence": {
            "pr_c": dict(pr),
            "premerge_safe_v2": final_delivery["pr_c_premerge_safe_v2"],
            "postmerge_safe_v2": dict(postmerge),
            "scope_guard_job": dict(scope_job),
            "final_witness_job": dict(witness_job),
            "witness_artifact": dict(artifact),
            "witness": dict(witness),
            "legacy_provider_branch": {
                "ref": f"refs/heads/{LEGACY_PROVIDER_BRANCH}",
                "sha": local["runtime_main_sha"],
            },
            "production_workflows": copy.deepcopy(hold["recovery_v2_production_workflow_quarantine"]),
            "nonterminal_run_counts": dict(hold["nonterminal_run_counts"]),
            "stable_full_holds_exact": 2,
            "premerge_inventory_observations_exact": 2,
            "main_commit_reads_exact": 3,
            "final_local_c2_revalidated": True,
        },
        "effect_counters": {
            "github_api_gets_exact": github_gets,
            "artifact_downloads_exact": _FINAL_ARTIFACT_DOWNLOADS_EXACT,
            "validated_artifact_redirects_exact": 1,
            "physical_https_gets_exact": github_gets + 1,
            "automatic_retries": 0,
        },
        "observed_at": final["generated_at"],
    }
    final["global_quiescence"] = True
    final["worktree_status"] = "CLEAN"
    final["all_run_ids"] = sorted(
        {
            *cast(list[int], final.get("all_run_ids", [])),
            cast(int, runs[0]["id"]),
            cast(int, runs[1]["id"]),
            cast(int, postmerge["run_id"]),
        }
    )
    final["all_artifact_ids"] = sorted(
        {
            *cast(list[int], final.get("all_artifact_ids", [])),
            cast(int, artifact["artifact_id"]),
        }
    )
    final["all_payload_sha256"] = sorted(
        {
            *cast(list[str], final.get("all_payload_sha256", [])),
            cast(str, artifact["payload_sha256"]),
        }
    )
    final["all_archive_sha256"] = sorted(
        {
            *cast(list[str], final.get("all_archive_sha256", [])),
            cast(str, artifact["archive_sha256"]),
        }
    )
    unchanged_exceptions = {
        "schema_version",
        "report_role",
        "generated_at",
        "duration_seconds",
        "mission_complete",
        "data_torrent_ready",
        "semantic_verdict",
        "final_verdict",
        "completion_states",
        "delivery",
        "postmerge_final_gate",
        "global_quiescence",
        "worktree_status",
        "all_run_ids",
        "all_artifact_ids",
        "all_payload_sha256",
        "all_archive_sha256",
    }
    if any(
        final.get(field) != candidate.get(field)
        for field in set(candidate) - unchanged_exceptions
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_CANDIDATE_COPY_INVALID")
    if (
        final["duration_seconds"] < cast(int, candidate["duration_seconds"])
        or final["duration_seconds"] > DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
        or final["postmerge_final_gate"]["effect_counters"]
        != {
            "github_api_gets_exact": _FINAL_GITHUB_GETS_EXACT,
            "artifact_downloads_exact": 1,
            "validated_artifact_redirects_exact": 1,
            "physical_https_gets_exact": _FINAL_GITHUB_GETS_EXACT + 1,
            "automatic_retries": 0,
        }
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_REPORT_INVALID")
    _validate_final_report(final, candidate=candidate)
    return final


def _validate_final_report(
    report: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> None:
    completion = report.get("completion_states")
    delivery = report.get("delivery")
    gate = report.get("postmerge_final_gate")
    candidate_gate = candidate.get("postmerge_final_gate")
    if (
        report.get("schema_version") != _FINAL_SCHEMA
        or report.get("report_role") != "FINAL_EXTERNAL_COMPOSITE_NON_DURABLE"
        or report.get("mission_id") != "DATA_TORRENT_RECOVERY_V2"
        or report.get("program_start_sha") != DATA_TORRENT_RECOVERY_V2_START_SHA
        or report.get("mission_complete") is not True
        or report.get("data_torrent_ready") is not True
        or report.get("semantic_verdict") != "DATA_TORRENT_READY"
        or report.get("final_verdict") != "PASS_AND_HOLD"
        or report.get("global_quiescence") is not True
        or report.get("worktree_status") != "CLEAN"
        or not isinstance(completion, dict)
        or not completion
        or any(value is not True for value in completion.values())
        or not isinstance(delivery, dict)
        or delivery.get("final_main_sha_definition")
        != "EXACT_PR_C_MERGE_COMMIT_AFTER_POSTMERGE_SAFE_V2"
        or not isinstance(delivery.get("pr_c_merge"), dict)
        or not isinstance(delivery.get("pr_c_premerge_safe_v2"), dict)
        or not isinstance(delivery.get("pr_c_postmerge_safe_v2"), dict)
        or not isinstance(gate, dict)
        or gate.get("state") != "SATISFIED"
        or gate.get("committed_in_pr_c") is not False
        or gate.get("local_receipt_authoritative") is not False
        or not isinstance(candidate_gate, dict)
        or gate.get("conditional_contract_sha256")
        != candidate_gate.get("conditional_contract_sha256")
        or not isinstance(gate.get("evidence"), dict)
        or not isinstance(gate.get("effect_counters"), dict)
        or any(
            not isinstance(report.get(field), list)
            or cast(list[Any], report[field]) != sorted(set(cast(list[Any], report[field])))
            for field in (
                "all_run_ids",
                "all_artifact_ids",
                "all_payload_sha256",
                "all_archive_sha256",
            )
        )
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_REPORT_INVALID")
    payload = canonical_json_bytes(dict(report)) + b"\n"
    if len(payload) > 2 * 1024 * 1024 or b"\r" in payload:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_REPORT_INVALID")


def _pull_request(document: Mapping[str, Any], *, local: Mapping[str, Any]) -> dict[str, Any]:
    head = document.get("head")
    base = document.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_INVALID")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    merge_sha = _require_sha(document.get("merge_commit_sha"), field="MERGE_SHA")
    if (
        document.get("number") != local["pr_number"]
        or document.get("title") != _PR_C_TITLE
        or document.get("state") != "closed"
        or document.get("merged") is not True
        or document.get("draft") is not False
        or head.get("ref") != _BRANCH
        or head.get("sha") != local["candidate_sha"]
        or base.get("ref") != "main"
        or not isinstance(head_repo, dict)
        or head_repo.get("full_name") != EXPECTED_REPOSITORY
        or not isinstance(base_repo, dict)
        or base_repo.get("full_name") != EXPECTED_REPOSITORY
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_INVALID")
    return {
        "number": local["pr_number"],
        "head_sha": local["candidate_sha"],
        "base_ref": "main",
        "merge_commit_sha": merge_sha,
        "created_at": document.get("created_at"),
        "merged_at": document.get("merged_at"),
        "state": "MERGED",
        "merge_method": "MERGE_COMMIT",
    }


def _main_commit(document: Mapping[str, Any], *, local: Mapping[str, Any], merge_sha: str) -> None:
    commit = document.get("commit")
    parents = document.get("parents")
    if not isinstance(commit, dict) or not isinstance(parents, list):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_MAIN_COMMIT_INVALID")
    tree = commit.get("tree")
    if (
        document.get("sha") != merge_sha
        or commit.get("message") != _PR_C_TITLE
        or not isinstance(tree, dict)
        or tree.get("sha") != local["candidate_tree_sha"]
        or len(parents) != 2
        or any(not isinstance(parent, dict) for parent in parents)
        or [parent.get("sha") for parent in parents]
        != [local["runtime_main_sha"], local["candidate_sha"]]
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_MAIN_COMMIT_INVALID")


def _run_pull_number(run: Mapping[str, Any]) -> int | None:
    pulls = run.get("pull_requests")
    if not isinstance(pulls, list) or len(pulls) != 1 or not isinstance(pulls[0], dict):
        return None
    number = pulls[0].get("number")
    return number if type(number) is int and number > 0 else None


def _strict_run(run: Mapping[str, Any], *, pr_number: int) -> dict[str, Any]:
    run_id = run.get("id")
    if (
        type(run_id) is not int
        or _RUN_ID.fullmatch(str(run_id)) is None
        or type(run.get("run_attempt")) is not int
        or run.get("run_attempt") != 1
        or run.get("event") != "pull_request"
        or run.get("head_branch") != _BRANCH
        or run.get("path") != _WORKFLOW_PATH
        or run.get("status") != "completed"
        or run.get("conclusion") not in {"failure", "success"}
        or _run_pull_number(run) != pr_number
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_RUNS_INVALID")
    _require_sha(run.get("head_sha"), field="PREMERGE_HEAD_SHA")
    _timestamp(run.get("created_at"), field="PREMERGE_CREATED_AT")
    _timestamp(run.get("updated_at"), field="PREMERGE_UPDATED_AT")
    return cast(dict[str, Any], dict(run))


def _premerge_runs(document: Mapping[str, Any], *, local: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_runs = document.get("workflow_runs")
    if (
        not isinstance(raw_runs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(raw_runs)
        or len(raw_runs) > 100
        or any(not isinstance(run, dict) for run in raw_runs)
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_RUNS_INVALID")
    relevant = [run for run in raw_runs if _run_pull_number(cast(dict[str, Any], run)) == local["pr_number"]]
    if len(relevant) != 2:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_RUNS_INVALID")
    runs = [_strict_run(cast(dict[str, Any], run), pr_number=cast(int, local["pr_number"])) for run in relevant]
    by_head = {cast(str, run["head_sha"]): run for run in runs}
    if (
        set(by_head) != {local["phase_one_sha"], local["candidate_sha"]}
        or by_head[cast(str, local["phase_one_sha"])]["conclusion"] != "failure"
        or by_head[cast(str, local["candidate_sha"])]["conclusion"] != "success"
        or len({run["id"] for run in runs}) != 2
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_RUNS_INVALID")
    return [by_head[cast(str, local["phase_one_sha"])], by_head[cast(str, local["candidate_sha"])]]


def _job(document: Mapping[str, Any], *, run: Mapping[str, Any], name: str) -> dict[str, Any]:
    jobs = document.get("jobs")
    if (
        not isinstance(jobs, list)
        or type(document.get("total_count")) is not int
        or document.get("total_count") != len(jobs)
        or len(jobs) > 100
        or any(not isinstance(item, dict) for item in jobs)
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_JOBS_INVALID")
    matches = [cast(dict[str, Any], item) for item in jobs if item.get("name") == name]
    if len(matches) != 1:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_JOBS_INVALID")
    result = matches[0]
    job_id = result.get("id")
    if (
        type(job_id) is not int
        or _RUN_ID.fullmatch(str(job_id)) is None
        or type(result.get("run_attempt")) is not int
        or result.get("run_attempt") != 1
        or result.get("run_id") != run.get("id")
        or result.get("head_sha") != run.get("head_sha")
        or result.get("status") != "completed"
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_JOBS_INVALID")
    return result


def _premerge_jobs(
    phase_one_document: Mapping[str, Any],
    candidate_document: Mapping[str, Any],
    *,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    phase_one_scope = _job(phase_one_document, run=runs[0], name=_SCOPE_JOB_NAME)
    phase_one_tests = _job(phase_one_document, run=runs[0], name=_TESTS_JOB_NAME)
    candidate_scope = _job(candidate_document, run=runs[1], name=_SCOPE_JOB_NAME)
    candidate_tests = _job(candidate_document, run=runs[1], name=_TESTS_JOB_NAME)
    phase_one_steps = phase_one_tests.get("steps")
    candidate_steps = candidate_tests.get("steps")
    if not isinstance(phase_one_steps, list) or not isinstance(candidate_steps, list):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_JOBS_INVALID")
    phase_one_gate_steps = [
        item
        for item in phase_one_steps
        if isinstance(item, dict)
        and item.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
    ]
    candidate_gate_steps = [
        item
        for item in candidate_steps
        if isinstance(item, dict)
        and item.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
    ]
    if (
        phase_one_scope.get("conclusion") != "success"
        or phase_one_tests.get("conclusion") != "failure"
        or candidate_scope.get("conclusion") != "success"
        or candidate_tests.get("conclusion") != "success"
        or len(phase_one_gate_steps) != 1
        or phase_one_gate_steps[0].get("status") != "completed"
        or phase_one_gate_steps[0].get("conclusion") != "failure"
        or len(candidate_gate_steps) != 1
        or candidate_gate_steps[0].get("status") != "completed"
        or candidate_gate_steps[0].get("conclusion") != "success"
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_JOBS_INVALID")
    return {
        "phase_one_scope_job_id": phase_one_scope["id"],
        "phase_one_hold_job_id": phase_one_tests["id"],
        "candidate_scope_job_id": candidate_scope["id"],
        "candidate_tests_job_id": candidate_tests["id"],
    }


def _artifact(
    listing: Mapping[str, Any],
    archive: bytes,
    *,
    run_id: int,
    merge_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifacts = listing.get("artifacts")
    expected_name = f"data-torrent-recovery-v2-final-gate-{run_id}-1"
    if (
        not isinstance(artifacts, list)
        or type(listing.get("total_count")) is not int
        or listing.get("total_count") != len(artifacts)
        or not 1 <= len(artifacts) <= 100
        or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    matches = [cast(dict[str, Any], item) for item in artifacts if item.get("name") == expected_name]
    if len(matches) != 1:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    item = matches[0]
    artifact_id = item.get("id")
    workflow_run = item.get("workflow_run")
    archive_sha = hashlib.sha256(archive).hexdigest()
    if (
        type(artifact_id) is not int
        or _RUN_ID.fullmatch(str(artifact_id)) is None
        or item.get("expired") is not False
        or type(item.get("size_in_bytes")) is not int
        or not 0 < cast(int, item["size_in_bytes"]) <= _MAX_WITNESS_BYTES
        or len(archive) != item.get("size_in_bytes")
        or item.get("digest") != f"sha256:{archive_sha}"
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != merge_sha
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = bundle.infolist()
            if (
                len(members) != 1
                or members[0].is_dir()
                or members[0].flag_bits & 0x1
                or stat.S_ISLNK(members[0].external_attr >> 16)
                or PurePosixPath(members[0].filename).name != _WITNESS_FILENAME
                or members[0].filename != _WITNESS_FILENAME
                or not 0 < members[0].file_size <= _MAX_WITNESS_BYTES
            ):
                raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
            payload = bundle.read(members[0])
    except RecoveryV2PostmergeGateError:
        raise
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID") from None
    if (
        payload.startswith(b"\xef\xbb\xbf")
        or b"\r" in payload
        or not payload.endswith(b"\n")
        or len(payload) > _MAX_WITNESS_BYTES
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_WITNESS_INVALID")
    try:
        witness = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_WITNESS_INVALID") from None
    if not isinstance(witness, dict) or payload != canonical_json_bytes(witness) + b"\n":
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_WITNESS_INVALID")
    expected_fields = {
        "artifact_uploads_planned",
        "current_run_completion_claimed",
        "data_torrent_ready_claimed",
        "event",
        "github_api_gets",
        "global_quiescence_claimed",
        "head_branch",
        "head_sha",
        "merge_subject",
        "phase",
        "prerequisite_results",
        "ref",
        "repository",
        "run_attempt",
        "run_id",
        "schema_version",
        "scope_guard_outputs",
        "verdict",
        "workflow_path",
    }
    if (
        set(witness) != expected_fields
        or witness.get("schema_version") != _WITNESS_SCHEMA
        or witness.get("verdict") != "PR_C_POSTMERGE_PREREQUISITES_COMPLETE"
        or witness.get("repository") != EXPECTED_REPOSITORY
        or witness.get("workflow_path") != _WORKFLOW_PATH
        or witness.get("event") != "push"
        or witness.get("ref") != "refs/heads/main"
        or witness.get("head_branch") != "main"
        or witness.get("head_sha") != merge_sha
        or witness.get("run_id") != run_id
        or type(witness.get("run_attempt")) is not int
        or witness.get("run_attempt") != 1
        or witness.get("phase") != "PR_C"
        or witness.get("merge_subject") != _PR_C_TITLE
        or witness.get("scope_guard_outputs")
        != {"phase": "PR_C", "terminal_candidate_complete": "true"}
        or witness.get("prerequisite_results")
        != {name: "success" for name in sorted(_PREREQUISITE_JOBS)}
        or witness.get("current_run_completion_claimed") is not False
        or witness.get("global_quiescence_claimed") is not False
        or witness.get("data_torrent_ready_claimed") is not False
        or witness.get("artifact_uploads_planned") != 1
        or witness.get("github_api_gets") != 0
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_WITNESS_INVALID")
    return (
        {
            "artifact_id": artifact_id,
            "artifact_name": expected_name,
            "archive_sha256": archive_sha,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_filename": _WITNESS_FILENAME,
            "expired": False,
        },
        cast(dict[str, Any], witness),
    )


def verify_postmerge_gate(
    *,
    repository_root: Path,
    pr_number: int,
    postmerge_run_id: int,
    now: datetime | None = None,
    api_loader: Callable[[str, str], dict[str, Any]] | None = None,
    artifact_loader: Callable[..., bytes | dict[str, Any]] | None = None,
    hold_loader: Callable[..., dict[str, Any]] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Return READY only after all local C2 and external postmerge facts agree."""

    injected = (
        now is not None,
        api_loader is not None,
        artifact_loader is not None,
        hold_loader is not None,
        clock is not None,
    )
    if any(injected) and not all(injected):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_TEST_INJECTION_INVALID")
    if (
        type(pr_number) is not int
        or pr_number <= 0
        or type(postmerge_run_id) is not int
        or _RUN_ID.fullmatch(str(postmerge_run_id)) is None
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARGUMENT_INVALID")
    token_values = [value for value in (os.getenv("GH_TOKEN", ""), os.getenv("GITHUB_TOKEN", "")) if value]
    if not token_values or len(set(token_values)) != 1 or len(token_values[0].encode("utf-8")) > 2_048:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_TOKEN_INVALID")
    token = token_values[0]
    live_clock = clock or (lambda: datetime.now(UTC))
    observed_now = (now or _clock_utc(live_clock)).astimezone(UTC)
    if observed_now.microsecond:
        observed_now = observed_now.replace(microsecond=0)
    root = Path(os.path.abspath(repository_root))
    try:
        authority_expiry = validate_data_torrent_recovery_v2_authority(
            scale_stage="E4",
            now=observed_now,
            repository_root=root,
            council_closure_phase="TERMINAL",
        )
    except ChronosProductionError:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_AUTHORITY_INVALID") from None
    mission_started_at = _timestamp(
        DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        field="MISSION_STARTED_AT",
    )
    mission_deadline = mission_started_at + timedelta(
        seconds=DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
    )
    effect_deadline = min(
        authority_expiry,
        mission_deadline,
        observed_now
        + timedelta(seconds=DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS),
    )
    if observed_now >= mission_deadline:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_TIME_BUDGET_EXCEEDED")
    local = _local_candidate(root, observed_now=observed_now)
    if local["pr_number"] != pr_number:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_INVALID")
    candidate_report = local.get("candidate_report")
    candidate_duration = (
        candidate_report.get("duration_seconds")
        if isinstance(candidate_report, dict)
        else None
    )
    elapsed_before_effects = int((observed_now - mission_started_at).total_seconds())
    if (
        type(candidate_duration) is not int
        or candidate_duration > elapsed_before_effects
        or candidate_duration > DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_TIME_BUDGET_EXCEEDED")
    host_identity_sha256 = _host_identity_sha256()
    if host_identity_sha256 != DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOST_IDENTITY_MISMATCH")
    state_base = _state_base()
    try:
        from scripts.materialize_data_torrent_recovery_v2_delivery_evidence import (
            _load_observer_result,
        )

        c1_observer_payload, c1_observer = _load_observer_result(
            phase="C1",
            root=root,
            pr_number=pr_number,
            expected_head_sha=cast(str, local["phase_one_sha"]),
            not_after=observed_now,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        c2_observer_payload, c2_observer = _load_observer_result(
            phase="C2",
            root=root,
            pr_number=pr_number,
            expected_head_sha=cast(str, local["candidate_sha"]),
            not_after=observed_now,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
        _postmerge_observer_payload, postmerge_observer = _load_observer_result(
            phase="POSTMERGE",
            root=root,
            pr_number=pr_number,
            expected_head_sha=cast(str, local["candidate_sha"]),
            not_after=observed_now,
            state_base=state_base,
            host_identity_sha256=host_identity_sha256,
        )
    except (ImportError, RuntimeError):
        raise RecoveryV2PostmergeGateError(
            "RECOVERY_V2_FINAL_OBSERVER_EVIDENCE_INVALID"
        ) from None
    observer_run = postmerge_observer.get("run")
    if (
        hashlib.sha256(c1_observer_payload).hexdigest()
        != local["c1_observer_result_raw_sha256"]
        or postmerge_observer.get("predecessor_results", {}).get("C2")
        != hashlib.sha256(c2_observer_payload).hexdigest()
        or c2_observer.get("predecessor_results", {}).get("C1")
        != local["c1_observer_result_raw_sha256"]
        or c1_observer.get("runtime_main_sha") != local["runtime_main_sha"]
        or c1_observer.get("head_sha") != local["phase_one_sha"]
        or c2_observer.get("runtime_main_sha") != local["runtime_main_sha"]
        or c2_observer.get("phase_one_sha") != local["phase_one_sha"]
        or c2_observer.get("head_sha") != local["candidate_sha"]
        or postmerge_observer.get("runtime_main_sha") != local["runtime_main_sha"]
        or postmerge_observer.get("phase_one_sha") != local["phase_one_sha"]
        or postmerge_observer.get("candidate_sha") != local["candidate_sha"]
        or postmerge_observer.get("pr_number") != pr_number
        or not isinstance(observer_run, dict)
        or observer_run.get("run_id") != postmerge_run_id
        or postmerge_observer.get("predecessor_results", {}).get("C1")
        != local["c1_observer_result_raw_sha256"]
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_OBSERVER_EVIDENCE_INVALID")
    _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=1)
    reservation = _reserve_final_gate(
        root,
        state_base=state_base,
        local=local,
        pr_number=pr_number,
        postmerge_run_id=postmerge_run_id,
        observed_at=observed_now,
        host_identity_sha256=host_identity_sha256,
        observer_chain_result_raw_sha256=hashlib.sha256(
            _postmerge_observer_payload
        ).hexdigest(),
    )
    json_loader = api_loader or (
        lambda path, supplied_token: _github_get(
            path,
            supplied_token,
            effect_deadline_epoch=effect_deadline.timestamp(),
        )
    )
    binary_loader = artifact_loader or (
        lambda path, binary=False: _api(
            path,
            binary=binary,
            effect_deadline_epoch=effect_deadline.timestamp(),
        )
    )
    final_hold_loader = hold_loader or verify_hold
    gets = 0

    def get(path: str) -> dict[str, Any]:
        nonlocal gets
        if gets >= _FINAL_GITHUB_GETS_EXACT:
            raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_READ_BUDGET_EXHAUSTED")
        _require_effect_window(
            live_clock,
            deadline=effect_deadline,
            margin_seconds=_GITHUB_JSON_READ_MARGIN_SECONDS,
        )
        gets += 1
        try:
            result = json_loader(path, token)
        except Exception:
            raise RecoveryV2PostmergeGateError(
                "RECOVERY_V2_FINAL_GITHUB_READ_FAILED"
            ) from None
        if not isinstance(result, dict):
            raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_GITHUB_RESPONSE_INVALID")
        _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=0)
        return result

    pr = _pull_request(
        get(f"/repos/{EXPECTED_REPOSITORY}/pulls/{pr_number}"),
        local=local,
    )
    merge_sha = cast(str, pr["merge_commit_sha"])
    if postmerge_observer.get("merge_sha") != merge_sha:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_OBSERVER_EVIDENCE_INVALID")
    _main_commit(
        get(f"/repos/{EXPECTED_REPOSITORY}/commits/main"),
        local=local,
        merge_sha=merge_sha,
    )
    runs = _premerge_runs(
        get(
            f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/ci-safe-v2.yml/runs"
            f"?event=pull_request&branch={_BRANCH}&per_page=100"
        ),
        local=local,
    )
    phase_one_jobs = get(
        f"/repos/{EXPECTED_REPOSITORY}/actions/runs/{runs[0]['id']}/jobs?per_page=100"
    )
    candidate_jobs = get(
        f"/repos/{EXPECTED_REPOSITORY}/actions/runs/{runs[1]['id']}/jobs?per_page=100"
    )
    premerge_job_proof = _premerge_jobs(
        phase_one_jobs,
        candidate_jobs,
        runs=runs,
    )
    c1_observer_run = c1_observer.get("run")
    c2_observer_run = c2_observer.get("run")
    if (
        not isinstance(c1_observer_run, dict)
        or not isinstance(c2_observer_run, dict)
        or c1_observer_run.get("run_id") != runs[0].get("id")
        or c1_observer_run.get("run_id") != local["c1_observer_run_id"]
        or c1_observer_run.get("run_attempt") != runs[0].get("run_attempt")
        or c1_observer_run.get("head_sha") != runs[0].get("head_sha")
        or c1_observer_run.get("conclusion") != runs[0].get("conclusion")
        or c1_observer_run.get("scope_guard_job_id")
        != premerge_job_proof.get("phase_one_scope_job_id")
        or c1_observer_run.get("tests_job_id")
        != premerge_job_proof.get("phase_one_hold_job_id")
        or c1_observer_run.get("scope_guard_conclusion") != "success"
        or c1_observer_run.get("tests_conclusion") != "failure"
        or c1_observer_run.get("gate_step_conclusion") != "failure"
        or c2_observer_run.get("run_id") != runs[1].get("id")
        or c2_observer_run.get("run_attempt") != runs[1].get("run_attempt")
        or c2_observer_run.get("head_sha") != runs[1].get("head_sha")
        or c2_observer_run.get("conclusion") != runs[1].get("conclusion")
        or c2_observer_run.get("scope_guard_job_id")
        != premerge_job_proof.get("candidate_scope_job_id")
        or c2_observer_run.get("tests_job_id")
        != premerge_job_proof.get("candidate_tests_job_id")
        or c2_observer_run.get("scope_guard_conclusion") != "success"
        or c2_observer_run.get("tests_conclusion") != "success"
        or c2_observer_run.get("gate_step_conclusion") != "success"
    ):
        raise RecoveryV2PostmergeGateError(
            "RECOVERY_V2_FINAL_OBSERVER_EVIDENCE_INVALID"
        )
    gets += 12
    if gets > _FINAL_GITHUB_GETS_EXACT:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_READ_BUDGET_EXHAUSTED")
    _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=_FULL_HOLD_READ_MARGIN_SECONDS,
    )
    try:
        hold = final_hold_loader(
            required_successful_ci_sha=merge_sha,
            recovery_v2=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            expected_successful_ci_run_id=postmerge_run_id,
            expected_legacy_branch_sha=local["runtime_main_sha"],
            require_recovery_v2_final_witness=True,
            effect_deadline_epoch=effect_deadline.timestamp(),
        )
    except Exception:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOLD_INVALID") from None
    _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=0)
    postmerge = hold.get("post_merge_ci")
    scope_job = hold.get("recovery_v2_scope_guard")
    witness_job = hold.get("recovery_v2_final_witness")
    production_workflows = hold.get("recovery_v2_production_workflow_quarantine")
    if (
        not isinstance(postmerge, dict)
        or postmerge.get("run_id") != postmerge_run_id
        or postmerge.get("head_sha") != merge_sha
        or postmerge.get("run_attempt") != 1
        or postmerge.get("status") != "completed"
        or postmerge.get("conclusion") != "success"
        or not isinstance(scope_job, dict)
        or scope_job.get("status") != "completed"
        or scope_job.get("conclusion") != "success"
        or not isinstance(witness_job, dict)
        or witness_job.get("status") != "completed"
        or witness_job.get("conclusion") != "success"
        or hold.get("current_run_excluded") != 0
        or hold.get("legacy_secret_branch_sha") != local["runtime_main_sha"]
        or hold.get("nonterminal_run_counts")
        != {status: 0 for status in ("requested", "waiting", "pending", "queued", "in_progress")}
        or not isinstance(production_workflows, list)
        or {item.get("workflow_path") for item in production_workflows if isinstance(item, dict)}
        != set(RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS)
        or any(
            not isinstance(item, dict) or item.get("state") != "disabled_manually"
            for item in production_workflows
        )
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOLD_INVALID")
    _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=_GITHUB_ARTIFACT_READ_MARGIN_SECONDS,
    )
    try:
        listing_raw = binary_loader(
            f"repos/{EXPECTED_REPOSITORY}/actions/runs/{postmerge_run_id}/artifacts?per_page=100"
        )
    except Exception:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_READ_FAILED") from None
    _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=0)
    gets += 1
    if not isinstance(listing_raw, dict):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    artifacts = listing_raw.get("artifacts")
    expected_artifact_name = f"data-torrent-recovery-v2-final-gate-{postmerge_run_id}-1"
    matches = (
        [item for item in artifacts if isinstance(item, dict) and item.get("name") == expected_artifact_name]
        if isinstance(artifacts, list)
        else []
    )
    if (
        len(matches) != 1
        or type(matches[0].get("id")) is not int
        or _RUN_ID.fullmatch(str(matches[0].get("id"))) is None
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=_GITHUB_ARTIFACT_READ_MARGIN_SECONDS,
    )
    try:
        archive_raw = binary_loader(
            f"repos/{EXPECTED_REPOSITORY}/actions/artifacts/{matches[0]['id']}/zip",
            binary=True,
        )
    except Exception:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_READ_FAILED") from None
    _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=0)
    gets += 1
    if not isinstance(archive_raw, bytes):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_ARTIFACT_INVALID")
    artifact, witness = _artifact(
        listing_raw,
        archive_raw,
        run_id=postmerge_run_id,
        merge_sha=merge_sha,
    )
    _main_commit(
        get(f"/repos/{EXPECTED_REPOSITORY}/commits/main"),
        local=local,
        merge_sha=merge_sha,
    )
    gets += 12
    if gets > _FINAL_GITHUB_GETS_EXACT:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_READ_BUDGET_EXHAUSTED")
    _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=_FULL_HOLD_READ_MARGIN_SECONDS,
    )
    try:
        hold_recheck = final_hold_loader(
            required_successful_ci_sha=merge_sha,
            recovery_v2=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            expected_successful_ci_run_id=postmerge_run_id,
            expected_legacy_branch_sha=local["runtime_main_sha"],
            require_recovery_v2_final_witness=True,
            effect_deadline_epoch=effect_deadline.timestamp(),
        )
    except Exception:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOLD_INVALID") from None
    _require_effect_window(live_clock, deadline=effect_deadline, margin_seconds=0)
    if hold_recheck != hold:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_HOLD_DRIFT")
    runs_recheck = _premerge_runs(
        get(
            f"/repos/{EXPECTED_REPOSITORY}/actions/workflows/ci-safe-v2.yml/runs"
            f"?event=pull_request&branch={_BRANCH}&per_page=100"
        ),
        local=local,
    )
    if runs_recheck != runs:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_PR_C_RUNS_DRIFT")
    _main_commit(
        get(f"/repos/{EXPECTED_REPOSITORY}/commits/main"),
        local=local,
        merge_sha=merge_sha,
    )
    runtime_close = _timestamp(local["runtime_close_observed_at"], field="RUNTIME_CLOSE_AT")
    delivery_at = _timestamp(local["delivery_observed_at"], field="DELIVERY_AT")
    report_at = _timestamp(local["candidate_report_generated_at"], field="CANDIDATE_REPORT_AT")
    phase_one_created = _timestamp(runs[0].get("created_at"), field="C1_CREATED_AT")
    phase_one_completed = _timestamp(runs[0].get("updated_at"), field="C1_COMPLETED_AT")
    candidate_created = _timestamp(runs[1].get("created_at"), field="C2_CREATED_AT")
    candidate_completed = _timestamp(runs[1].get("updated_at"), field="C2_COMPLETED_AT")
    pr_created = _timestamp(pr.get("created_at"), field="PR_C_CREATED_AT")
    merged_at = _timestamp(pr.get("merged_at"), field="PR_C_MERGED_AT")
    postmerge_created = _timestamp(postmerge.get("created_at"), field="POSTMERGE_CREATED_AT")
    witness_completed = _timestamp(witness_job.get("completed_at"), field="WITNESS_COMPLETED_AT")
    postmerge_completed = _timestamp(postmerge.get("updated_at"), field="POSTMERGE_COMPLETED_AT")
    final_observed_at = _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=0,
    )
    if not (
        runtime_close
        <= pr_created
        <= phase_one_created
        <= phase_one_completed
        <= delivery_at
        <= report_at
        <= candidate_created
        <= candidate_completed
        <= merged_at
        <= postmerge_created
        <= witness_completed
        <= postmerge_completed
        <= final_observed_at
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_TEMPORAL_ORDER_INVALID")
    if (
        final_observed_at >= effect_deadline
        or final_observed_at - observed_now
        > timedelta(seconds=DATA_TORRENT_RECOVERY_V2_MAXIMUM_EFFECT_RUNTIME_SECONDS)
    ):
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_AUTHORITY_WINDOW_EXCEEDED")
    if _local_candidate(root, observed_now=final_observed_at) != local:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_LOCAL_STATE_DRIFT")
    final_observed_at = _require_effect_window(
        live_clock,
        deadline=effect_deadline,
        margin_seconds=0,
    )
    if gets != _FINAL_GITHUB_GETS_EXACT:
        raise RecoveryV2PostmergeGateError("RECOVERY_V2_FINAL_READ_ACCOUNTING_INVALID")
    return _compose_final_report(
        local=local,
        reservation=reservation,
        pr=pr,
        runs=runs,
        premerge_job_proof=premerge_job_proof,
        postmerge=postmerge,
        scope_job=scope_job,
        witness_job=witness_job,
        artifact=artifact,
        witness=witness,
        hold=hold,
        merge_sha=merge_sha,
        final_observed_at=final_observed_at,
        authority_started_at=observed_now,
        authority_expiry=authority_expiry,
        github_gets=gets,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--postmerge-run-id", type=int, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(os.path.abspath(Path(__file__))).parents[1],
    )
    args = parser.parse_args()
    try:
        result = verify_postmerge_gate(
            repository_root=args.repository_root,
            pr_number=args.pr_number,
            postmerge_run_id=args.postmerge_run_id,
        )
    except (ChronosProductionError, RecoveryV2PostmergeGateError) as error:
        print(str(error))
        return 1
    except Exception:
        print("RECOVERY_V2_FINAL_GATE_FAILED")
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
