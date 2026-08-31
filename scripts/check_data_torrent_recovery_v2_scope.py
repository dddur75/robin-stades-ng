"""Prove that a Recovery V2 candidate changes only its frozen allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # nosec B404 - fixed git executable and argument vectors only.
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

from robin.chronos_production import (
    ChronosProductionError,
    _recovery_v2_evidence_bytes,
    _recovery_v2_prepare_repository_directory,
    _recovery_v2_require_unused_repository_output,
)

START_SHA = "fcbf2a4fedd413251ee9da94ec2a444c6b917e63"
MISSION = "DATA_TORRENT_RECOVERY_V2"
EXPECTED_ALLOWED_PATHS_SHA256 = "9a0358ef0f4b4161385efe4785a9f5653ececc71dc42d179c4d116bf12a6c9fd"
EXPECTED_PHASE_ALLOWED_PATHS_SHA256 = {
    "PR_A": "20f13358feb1f2cfb1e48617f178dc6925f43a765105b9f7ee039fd4cc28a2e1",
    "PR_B": "2ecb01d91b1ee2e2a13d27bff9665025866a149e221f0e79fec06c01bcb5a4d2",
    "PR_C": "51fca9760fd1a209877ec32ce60adeac791296e377e1fccd88b850e1056ef14b",
}
EXPECTED_TERMINAL_EVIDENCE_PATH_COUNT = 43
_HEX_40 = frozenset("0123456789abcdef")
_MAX_GIT_OUTPUT_BYTES = 1024 * 1024
_PHASE_LABELS = {
    "PR_A": "[DATA_TORRENT_RECOVERY_V2] PR-A",
    "PR_B": "[DATA_TORRENT_RECOVERY_V2] PR-B",
    "PR_C": "[DATA_TORRENT_RECOVERY_V2] PR-C",
}
_CORRECTION_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-ci-correction-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-ci-correction-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-ci-correction-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-ci-correction-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-ci-correction-final-review-v3.json",
    }
)
_LOCAL_CORRECTION_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-post-196-correction-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-196-correction-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-196-correction-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-196-correction-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-196-correction-final-review-v3.json",
    }
)
_STATIC_CORRECTION_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-post-198-static-correction-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-198-static-correction-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-198-static-correction-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-198-static-correction-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-198-static-correction-final-review-v3.json",
    }
)
_EXACT_HEAD_CI_CORRECTION_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-exact-head-ci-cycle-1-final-review-v3.json",
    }
)
_POST_202_B101_CORRECTION_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-post-202-b101-correction-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-202-b101-correction-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-202-b101-correction-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-post-202-b101-correction-final-review-v3.json",
    }
)
_PR_B_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-pr-b-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-pr-b-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-pr-b-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-pr-b-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-pr-b-final-review-v3.json",
    }
)
_INITIAL_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-dp6-review-v3.json",
        "reports/council/data-torrent-recovery-v2-final-review-v3.json",
    }
)
_TERMINAL_REVIEW_PATHS = frozenset(
    {
        "reports/council/data-torrent-recovery-v2-terminal-a2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-terminal-c2-review-v3.json",
        "reports/council/data-torrent-recovery-v2-terminal-c4-review-v3.json",
        "reports/council/data-torrent-recovery-v2-terminal-dp6-review-v3.json",
    }
)
_TERMINAL_REPORT_PATH = "reports/council/data-torrent-recovery-v2-terminal-report-v1.json"
_LEDGER_PATH = "reports/council/decision-ledger.jsonl"
_GRAPH_PATH = "reports/evidence/evidence-graph.json"
_OWNER_MANIFEST_PATH = "configs/execution/data-torrent-recovery-v2.json"
_TERMINAL_EVIDENCE_PREFIX = (
    "reports/council/data-torrent-recovery-v2-terminal-evidence/"
)
_TERMINAL_INTENT_PREFIX = (
    "reports/council/data-torrent-recovery-v2-terminal-intents/"
)
_TERMINAL_INTENT_PATHS = frozenset(
    {
        f"{_TERMINAL_INTENT_PREFIX}delivery-observation-reservation-v1.json",
        f"{_TERMINAL_INTENT_PREFIX}terminal-evidence-reservation-v1.json",
    }
)
_DELIVERY_EVIDENCE_PATHS = frozenset(
    {
        f"{_TERMINAL_EVIDENCE_PREFIX}delivery-observation-reservation-v1.json",
        f"{_TERMINAL_EVIDENCE_PREFIX}delivery-receipt-v1.json",
    }
)


class ScopeGuardError(RuntimeError):
    """A sanitized, fail-closed scope guard rejection."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _git(root: Path, *arguments: str, check: bool = True) -> bytes:
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
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-scope-git-hooks-") as hooks:
            completed = subprocess.run(  # nosec B603 B607 - fixed git and bounded arguments.
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
                timeout=10,
            )
    except (OSError, subprocess.SubprocessError):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_FAILED") from None
    if check and completed.returncode != 0:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_FAILED")
    if len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_OUTPUT_TOO_LARGE")
    return completed.stdout


def _require_sha(value: str) -> str:
    if len(value) != 40 or any(character not in _HEX_40 for character in value):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_HEAD_INVALID")
    return value


def _require_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PATH_INVALID")
    return value


def _paths_sha256(paths: list[str]) -> str:
    return hashlib.sha256(("\n".join(paths) + "\n").encode("utf-8")).hexdigest()


def _allowed_paths(root: Path) -> list[str]:
    matrix_path = root / "configs" / "agents" / "mission-activation-matrix-v3.json"
    try:
        payload = _recovery_v2_evidence_bytes(
            matrix_path,
            repository_root=root,
            maximum_bytes=2 * 1024 * 1024,
        )
        document = json.loads(
            payload,
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        missions = document["missions"]
        mission = missions[MISSION]
        raw_paths = mission["allowed_paths"]
    except (
        ChronosProductionError,
        KeyError,
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MATRIX_INVALID") from None
    if (
        not isinstance(document, dict)
        or not isinstance(missions, dict)
        or not isinstance(mission, dict)
        or mission.get("writer") != "C0"
        or mission.get("scale_ceiling") != "E4"
        or not isinstance(raw_paths, list)
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MATRIX_INVALID")
    paths = [_require_path(value) for value in cast(list[object], raw_paths)]
    if (
        not paths
        or paths != sorted(paths)
        or len(paths) != len(set(paths))
        or _paths_sha256(paths) != EXPECTED_ALLOWED_PATHS_SHA256
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MATRIX_INVALID")
    return paths


def _phase_allowed_paths(allowed: list[str], *, phase: str) -> list[str]:
    """Derive and pin the immutable per-phase path boundary."""

    if phase not in _PHASE_LABELS:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_INVALID")
    allowed_set = set(allowed)
    terminal_evidence = {
        path for path in allowed_set if path.startswith(_TERMINAL_EVIDENCE_PREFIX)
    }
    terminal_only = (
        terminal_evidence
        | set(_TERMINAL_INTENT_PATHS)
        | set(_TERMINAL_REVIEW_PATHS)
        | {_TERMINAL_REPORT_PATH}
    )
    if (
        len(terminal_evidence) != EXPECTED_TERMINAL_EVIDENCE_PATH_COUNT
        or not terminal_only.issubset(allowed_set)
        or not (
            _CORRECTION_REVIEW_PATHS
            | _LOCAL_CORRECTION_REVIEW_PATHS
            | _STATIC_CORRECTION_REVIEW_PATHS
            | _EXACT_HEAD_CI_CORRECTION_REVIEW_PATHS
            | _POST_202_B101_CORRECTION_REVIEW_PATHS
            | _PR_B_REVIEW_PATHS
            | _INITIAL_REVIEW_PATHS
        ).issubset(allowed_set)
        or {_LEDGER_PATH, _GRAPH_PATH, _OWNER_MANIFEST_PATH} - allowed_set
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MATRIX_INVALID")
    if phase == "PR_A":
        phase_paths = allowed_set - terminal_only - set(_PR_B_REVIEW_PATHS)
    elif phase == "PR_B":
        phase_paths = (
            allowed_set
            - terminal_only
            - set(_INITIAL_REVIEW_PATHS)
            - set(_CORRECTION_REVIEW_PATHS)
            - set(_LOCAL_CORRECTION_REVIEW_PATHS)
            - set(_STATIC_CORRECTION_REVIEW_PATHS)
            - set(_EXACT_HEAD_CI_CORRECTION_REVIEW_PATHS)
            - set(_POST_202_B101_CORRECTION_REVIEW_PATHS)
            - {_OWNER_MANIFEST_PATH}
        )
    else:
        phase_paths = terminal_only | {_LEDGER_PATH, _GRAPH_PATH}
    result = sorted(phase_paths)
    if _paths_sha256(result) != EXPECTED_PHASE_ALLOWED_PATHS_SHA256[phase]:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_SET_INVALID")
    return result


def _latest_council_context(root: Path) -> dict[str, object]:
    ledger_path = root / _LEDGER_PATH
    try:
        payload = _recovery_v2_evidence_bytes(
            ledger_path,
            repository_root=root,
            maximum_bytes=16 * 1024 * 1024,
        )
        if not payload or len(payload) > 16 * 1024 * 1024 or b"\r" in payload:
            raise ValueError
        lines = payload.splitlines()
        records = [
            json.loads(
                line,
                object_pairs_hook=_strict_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            for line in lines
        ]
    except (
        ChronosProductionError,
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_LEDGER_INVALID") from None
    if not records or not isinstance(records[-1], dict):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_LEDGER_INVALID")
    context = cast(dict[str, object], records[-1]).get("context")
    if not isinstance(context, dict):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_LEDGER_INVALID")
    return cast(dict[str, object], context)


def _changed_paths(root: Path, *, base: str, head: str) -> list[str]:
    _git(root, "merge-base", "--is-ancestor", base, head)
    raw = _git(
        root,
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        f"{base}..{head}",
    )
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PATH_INVALID") from None
    fields = decoded.split("\x00")
    if not fields or fields[-1] != "":
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_OUTPUT_INVALID")
    changed = [_require_path(value) for value in fields[:-1]]
    if not changed or len(changed) != len(set(changed)):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_OUTPUT_INVALID")
    return sorted(changed)


def _range_commits(root: Path, *, base: str, head: str) -> list[str]:
    """Return every reachable candidate commit and reject an empty range."""

    _git(root, "merge-base", "--is-ancestor", base, head)
    try:
        output = _git(root, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").decode(
            "ascii"
        )
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_COMMIT_HISTORY_INVALID") from None
    commits = [_require_sha(line) for line in output.splitlines() if line]
    if not commits or len(commits) != len(set(commits)):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_COMMIT_HISTORY_INVALID")
    return commits


def _commit_changed_paths(root: Path, *, commit: str) -> list[str]:
    raw = _git(
        root,
        "diff-tree",
        "--root",
        "-m",
        "--no-commit-id",
        "--no-renames",
        "--name-only",
        "-z",
        "-r",
        commit,
    )
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PATH_INVALID") from None
    fields = decoded.split("\x00")
    if not fields or fields[-1] != "":
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_OUTPUT_INVALID")
    return sorted({_require_path(value) for value in fields[:-1]})


def _history_changed_paths(root: Path, *, base: str, head: str) -> list[str]:
    """Union paths touched by every commit, including later deletions/reverts."""

    paths: set[str] = set()
    for commit in _range_commits(root, base=base, head=head):
        paths.update(_commit_changed_paths(root, commit=commit))
    if not paths:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_GIT_OUTPUT_INVALID")
    return sorted(paths)


def _candidate_topology(
    root: Path,
    *,
    base: str,
    tip: str,
    phase: str,
    terminal_evidence: set[str],
) -> list[dict[str, object]]:
    """Require the exact linear C0 reservation, C1 evidence, C2 candidate chain."""

    commits = _range_commits(root, base=base, head=tip)
    expected_parent = base
    result: list[dict[str, object]] = []
    for commit in commits:
        parents, subject, _body = _commit_shape(root, commit)
        if parents != [expected_parent]:
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_COMMIT_HISTORY_INVALID")
        paths = _commit_changed_paths(root, commit=commit)
        result.append(
            {
                "sha": commit,
                "parent_sha": expected_parent,
                "subject": subject,
                "changed_paths_sha256": _paths_sha256(paths),
                "changed_path_count": len(paths),
            }
        )
        expected_parent = commit
    if expected_parent != tip:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_COMMIT_HISTORY_INVALID")
    if phase != "PR_C":
        return result
    if len(commits) not in {1, 2, 3}:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PR_C_TOPOLOGY_INVALID")
    reservation_paths = set(_TERMINAL_INTENT_PATHS) | {
        _LEDGER_PATH,
        _GRAPH_PATH,
    }
    phase_one_paths = (terminal_evidence - set(_DELIVERY_EVIDENCE_PATHS)) | {
        _LEDGER_PATH,
        _GRAPH_PATH,
    }
    closure_paths = (
        set(_DELIVERY_EVIDENCE_PATHS)
        | set(_TERMINAL_REVIEW_PATHS)
        | {_TERMINAL_REPORT_PATH, _LEDGER_PATH, _GRAPH_PATH}
    )
    if (
        set(_commit_changed_paths(root, commit=commits[0])) != reservation_paths
        or (
            len(commits) >= 2
            and set(_commit_changed_paths(root, commit=commits[1])) != phase_one_paths
        )
        or (
            len(commits) == 3
            and set(_commit_changed_paths(root, commit=commits[2])) != closure_paths
        )
    ):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PR_C_TOPOLOGY_INVALID")
    return result


def _commit_shape(root: Path, sha: str) -> tuple[list[str], str, str]:
    try:
        parent_line = _git(root, "rev-list", "--parents", "-n", "1", sha).decode(
            "ascii"
        ).strip()
        message = _git(root, "show", "-s", "--format=%s%x00%b", sha)
        if not message.endswith(b"\n") or message.count(b"\x00") != 1:
            raise UnicodeDecodeError("utf-8", message, 0, len(message), "invalid framing")
        subject_raw, body_raw = message[:-1].split(b"\x00", 1)
        subject = subject_raw.decode("utf-8")
        body = body_raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MERGE_PARENT_INVALID") from None
    fields = parent_line.split()
    if not fields or fields[0] != sha:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MERGE_PARENT_INVALID")
    return fields[1:], subject, body


def _engineering_chain(root: Path, *, runtime_base: str) -> list[dict[str, object]]:
    _git(root, "cat-file", "-e", f"{START_SHA}^{{commit}}")
    _git(root, "merge-base", "--is-ancestor", START_SHA, runtime_base)
    try:
        output = _git(
            root,
            "rev-list",
            "--first-parent",
            "--reverse",
            f"{START_SHA}..{runtime_base}",
        ).decode("ascii")
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID") from None
    commits = [line for line in output.splitlines() if line]
    if len(commits) not in {0, 1, 2}:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID")
    expected_parent = START_SHA
    result: list[dict[str, object]] = []
    for index, commit in enumerate(commits):
        commit = _require_sha(commit)
        parents, subject, body = _commit_shape(root, commit)
        role = "PR_A" if index == 0 else "PR_B"
        if (
            len(parents) != 2
            or parents[0] != expected_parent
            or subject != _PHASE_LABELS[role]
            or body
        ):
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID")
        result.append(
            {
                "role": role,
                "merge_commit_sha": commit,
                "first_parent_sha": parents[0],
                "second_parent_sha": parents[1],
            }
        )
        expected_parent = commit
    if expected_parent != runtime_base:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID")
    return result


def verify_scope(
    *,
    repository_root: Path,
    expected_head: str,
    expected_base: str,
    phase: str,
    event_label: str,
    output: Path,
    expected_first_parent: str | None = None,
) -> dict[str, Any]:
    """Validate the global mission scope and the exact A/B/C phase delta."""

    root = Path(os.path.abspath(repository_root))
    output = Path(os.path.abspath(root / output if not output.is_absolute() else output))
    head = _require_sha(expected_head)
    base = _require_sha(expected_base)
    if phase not in _PHASE_LABELS or event_label != _PHASE_LABELS[phase]:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_INVALID")
    try:
        observed_head = _git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    except UnicodeDecodeError:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_HEAD_INVALID") from None
    if observed_head != head:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_HEAD_MISMATCH")
    merge_first_parent: str | None = None
    merge_parent_count: int | None = None
    candidate_tip = head
    if expected_first_parent is not None:
        first_parent = _require_sha(expected_first_parent)
        parents, subject, body = _commit_shape(root, head)
        if (
            base != first_parent
            or len(parents) != 2
            or parents[0] != first_parent
            or subject != event_label
            or body
        ):
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MERGE_PARENT_INVALID")
        try:
            merge_tree = _require_sha(
                _git(root, "rev-parse", f"{head}^{{tree}}").decode("ascii").strip()
            )
            candidate_tree = _require_sha(
                _git(root, "rev-parse", f"{parents[1]}^{{tree}}").decode("ascii").strip()
            )
        except UnicodeDecodeError:
            raise ScopeGuardError(
                "DATA_TORRENT_RECOVERY_V2_SCOPE_MERGE_PARENT_INVALID"
            ) from None
        if merge_tree != candidate_tree:
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_MERGE_PARENT_INVALID")
        merge_first_parent = first_parent
        merge_parent_count = 2
        candidate_tip = parents[1]
    chain = _engineering_chain(root, runtime_base=base)
    observed_roles = [cast(str, row["role"]) for row in chain]
    expected_roles = {
        "PR_A": [],
        "PR_B": ["PR_A"],
        "PR_C": ["PR_A"],
    }
    if phase == "PR_C":
        if observed_roles not in (["PR_A"], ["PR_A", "PR_B"]):
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID")
    elif observed_roles != expected_roles[phase]:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_ENGINEERING_CHAIN_INVALID")
    changed = _changed_paths(root, base=START_SHA, head=head)
    phase_changed = _changed_paths(root, base=base, head=head)
    allowed = _allowed_paths(root)
    phase_allowed = _phase_allowed_paths(allowed, phase=phase)
    terminal_evidence = {
        path for path in allowed if path.startswith(_TERMINAL_EVIDENCE_PREFIX)
    }
    candidate_topology = _candidate_topology(
        root,
        base=base,
        tip=candidate_tip,
        phase=phase,
        terminal_evidence=terminal_evidence,
    )
    history_changed = _history_changed_paths(root, base=START_SHA, head=head)
    phase_history_changed = _history_changed_paths(root, base=base, head=head)
    outside = sorted((set(changed) | set(history_changed)) - set(allowed))
    phase_outside = sorted(
        (set(phase_changed) | set(phase_history_changed)) - set(phase_allowed)
    )
    if outside or phase_outside:
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_OUTSIDE_ALLOWLIST")
    if phase == "PR_B" and not (
        _PR_B_REVIEW_PATHS | {_LEDGER_PATH, _GRAPH_PATH}
    ).issubset(phase_changed):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_CONTENT_INVALID")
    if phase == "PR_B":
        latest_context = _latest_council_context(root)
        if (
            latest_context.get("phase") != "PR_B_CORRECTION_RELEASE_AFTER_INDEPENDENT_QA"
            or latest_context.get("head") != base
            or latest_context.get("files") != sorted(phase_changed)
        ):
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_CONTENT_INVALID")
    terminal_candidate_complete = phase != "PR_C" or len(candidate_topology) == 3
    if phase == "PR_C":
        topology_length = len(candidate_topology)
        reservation_paths = set(_TERMINAL_INTENT_PATHS) | {
            _LEDGER_PATH,
            _GRAPH_PATH,
        }
        phase_one_paths = (terminal_evidence - set(_DELIVERY_EVIDENCE_PATHS)) | {
            _LEDGER_PATH,
            _GRAPH_PATH,
        }
        expected_phase_changed = reservation_paths
        if topology_length >= 2:
            expected_phase_changed |= phase_one_paths
        if topology_length == 3:
            expected_phase_changed |= (
                set(_DELIVERY_EVIDENCE_PATHS)
                | set(_TERMINAL_REVIEW_PATHS)
                | {_TERMINAL_REPORT_PATH, _LEDGER_PATH, _GRAPH_PATH}
            )
        if set(phase_changed) != expected_phase_changed:
            raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_PHASE_CONTENT_INVALID")
    receipt = {
        "schema_version": "data-torrent-recovery-v2-scope-guard-v4",
        "start_sha": START_SHA,
        "phase": phase,
        "event_label": event_label,
        "base_sha": base,
        "head_sha": head,
        "allowed_paths_sha256": _paths_sha256(allowed),
        "phase_allowed_paths_sha256": _paths_sha256(phase_allowed),
        "changed_paths_sha256": _paths_sha256(changed),
        "changed_path_count": len(changed),
        "phase_changed_paths_sha256": _paths_sha256(phase_changed),
        "phase_changed_path_count": len(phase_changed),
        "history_changed_paths_sha256": _paths_sha256(history_changed),
        "history_changed_path_count": len(history_changed),
        "phase_history_changed_paths_sha256": _paths_sha256(phase_history_changed),
        "phase_history_changed_path_count": len(phase_history_changed),
        "candidate_tip_sha": candidate_tip,
        "candidate_topology": candidate_topology,
        "engineering_chain": chain,
        "merge_first_parent": merge_first_parent,
        "merge_parent_count": merge_parent_count,
        "outside_paths": [],
        "phase_outside_paths": [],
        "terminal_candidate_complete": terminal_candidate_complete,
        "verdict": "SCOPE_GUARD_PASS",
    }
    try:
        _recovery_v2_prepare_repository_directory(output.parent, repository_root=root)
        _recovery_v2_require_unused_repository_output(output, repository_root=root)
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n")
    except (ChronosProductionError, OSError):
        raise ScopeGuardError("DATA_TORRENT_RECOVERY_V2_SCOPE_RECEIPT_INVALID") from None
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--phase", choices=tuple(_PHASE_LABELS), required=True)
    parser.add_argument("--event-label", required=True)
    parser.add_argument("--expected-first-parent")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(os.path.abspath(Path(__file__))).parents[1],
    )
    args = parser.parse_args()
    try:
        receipt = verify_scope(
            repository_root=args.repository_root,
            expected_head=args.expected_head,
            expected_base=args.expected_base,
            phase=args.phase,
            event_label=args.event_label,
            output=args.output,
            expected_first_parent=args.expected_first_parent,
        )
    except ScopeGuardError as error:
        print(str(error))
        return 1
    print(receipt["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
