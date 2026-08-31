"""Materialize the one-shot Recovery V2 terminal evidence bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import stat
import subprocess  # nosec B404 - fixed git executable, closed argument vectors only.
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
    DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS,
    DATA_TORRENT_RECOVERY_V2_START_SHA,
    DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR,
    DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
    DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    _recovery_v2_directory_identity,
    _recovery_v2_evidence_bytes,
    _recovery_v2_fsync_repository_directory,
    _recovery_v2_path_is_reparse,
    _recovery_v2_prepare_repository_directory,
    _recovery_v2_publish_exclusive_bytes,
    _recovery_v2_require_unused_repository_output,
    _recovery_v2_terminal_hold,
    _recovery_v2_terminalization_effect_reservation,
    assert_production_safety_locks,
    canonical_json_bytes,
    validate_data_torrent_recovery_v2_authority,
    validate_data_torrent_recovery_v2_council_release,
    validate_data_torrent_recovery_v2_reservation_council_closure,
)
from scripts.check_chronos_github_hold_v3 import verify_hold
from scripts.github_release_attestation_v2 import exact_main_sha_v2

_ROOT = Path(os.path.abspath(Path(__file__))).parents[1]
_RUN_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_BRANCH = "codex/data-torrent-recovery-v2"
_EXPECTED_REMOTE_URL = "https://github.com/dddur75/robin-stades-ng.git"
_ARTIFACT_NAMES = (
    "hypothesis-backlog-from-real-data-v1.md",
    "hypothesis-ready-field-dictionary-v1.json",
    "robin-data-torrent-operations-pack-v1.md",
    "robin-data-torrent-recovery-pack-v1.md",
    "torrent-canonical-dataset-hash-v1.json",
    "torrent-control-plane-event-chain-v1.json",
    "torrent-load-replay-report-v1.json",
    "torrent-load-replay-report-v1.md",
    "torrent-official-read-receipts-v1.json",
    "torrent-opportunity-claim-receipt-v1.json",
    "torrent-provider-credit-receipt-v1.json",
    "torrent-qa-acceptance-matrix-v1.json",
    "torrent-r2-inventory-v1.json",
    "torrent-raw-to-normalized-lineage-v1.json",
    "torrent-real-batch-coverage-matrix-v1.csv",
    "torrent-real-batch-manifest-v1.json",
    "torrent-real-batch-normalized-index-v1.json",
    "torrent-real-batch-quality-report-v1.json",
    "torrent-real-batch-raw-index-v1.json",
)
_CACHE_SLUGS = {
    "RECOVERY_IDENTITY_V2": "recovery-identity-v2",
    "DURABLE_IDENTITY_SEAL_V2": "durable-identity-seal-v2",
    "PRODUCTION_PREFLIGHT_V2": "production-preflight-v2",
    "MIGRATE_0015": "migrate-0015",
    "VERIFY_0015": "verify-0015",
}
_CACHE_KINDS = {
    "RECOVERY_IDENTITY_V2": "IDENTITY",
    "DURABLE_IDENTITY_SEAL_V2": "IDENTITY_SEAL",
    "PRODUCTION_PREFLIGHT_V2": "PREFLIGHT",
    "MIGRATE_0015": "MIGRATION",
    "VERIFY_0015": "VERIFY",
}
_CACHE_ONLY_SOURCE = "__RECOVERY_V2_CACHE_ONLY__"
_EXECUTION_RESERVATION_NAMES = {
    "TERMINAL": "terminal-materializer-execution-reservation-v1.json",
    "DELIVERY": "delivery-materializer-execution-reservation-v1.json",
}
_EXECUTION_STATE_DIRECTORY = (
    Path("RobinCouncilOS")
    / EXPECTED_REPOSITORY.replace("/", "__")
    / "data-torrent-recovery-v2"
    / DATA_TORRENT_RECOVERY_V2_START_SHA
)
_MATERIALIZER_MAXIMUM_RUNTIME_SECONDS = 1_200


class TerminalEvidenceV2Error(RuntimeError):
    """A sanitized fail-closed terminal materialization error."""


def _materializer_deadline_epoch(authority_deadline: datetime) -> float:
    if not isinstance(authority_deadline, datetime) or authority_deadline.tzinfo is None:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_AUTHORITY_INVALID")
    observed = datetime.now(UTC)
    deadline = min(
        authority_deadline.astimezone(UTC),
        observed + timedelta(seconds=_MATERIALIZER_MAXIMUM_RUNTIME_SECONDS),
    ).timestamp()
    if deadline <= time.time():
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EFFECT_DEADLINE_EXCEEDED")
    return deadline


def _require_effect_window(
    effect_deadline_epoch: float,
    *,
    margin_seconds: float = 0.0,
) -> float:
    if (
        isinstance(effect_deadline_epoch, bool)
        or not isinstance(effect_deadline_epoch, (int, float))
        or not math.isfinite(float(effect_deadline_epoch))
        or isinstance(margin_seconds, bool)
        or not isinstance(margin_seconds, (int, float))
        or not math.isfinite(float(margin_seconds))
        or margin_seconds < 0
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EFFECT_DEADLINE_INVALID")
    remaining = float(effect_deadline_epoch) - time.time()
    if remaining <= float(margin_seconds):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EFFECT_DEADLINE_EXCEEDED")
    return remaining


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"


def _write_exclusive(path: Path, payload: bytes, *, root: Path) -> None:
    try:
        _recovery_v2_publish_exclusive_bytes(path, payload, repository_root=root)
    except FileExistsError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_INVOCATION_ALREADY_CONSUMED") from None
    except (ChronosProductionError, OSError):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_LOCAL_WRITE_INVALID") from None


def _execution_state_context(*, root: Path) -> tuple[Path, str]:
    try:
        from scripts.verify_data_torrent_recovery_v2_postmerge_gate import (
            _host_identity_sha256,
            _state_base,
        )

        state_base = Path(os.path.abspath(_state_base()))
        host_identity_sha256 = _host_identity_sha256()
    except Exception:
        raise TerminalEvidenceV2Error("RECOVERY_V2_MATERIALIZER_STATE_ROOT_INVALID") from None
    state_target = Path(os.path.abspath(state_base / _EXECUTION_STATE_DIRECTORY))
    if (
        state_target.is_relative_to(Path(os.path.abspath(root)))
        or host_identity_sha256 != DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_MATERIALIZER_HOST_IDENTITY_INVALID")
    return state_base, host_identity_sha256


def _reserve_materializer_execution(
    *,
    kind: str,
    root: Path,
    main_sha: str,
    head_sha: str,
    reservation_commit_sha: str,
    terminal_intent_payload: bytes,
    delivery_intent_payload: bytes,
    remote_reads_conservatively_consumed: int,
    github_gets_conservatively_consumed: int,
    artifact_downloads_conservatively_consumed: int,
    additional_binding: Mapping[str, object],
    observed_at: datetime | None = None,
) -> dict[str, object]:
    if (
        kind not in _EXECUTION_RESERVATION_NAMES
        or _SHA.fullmatch(main_sha) is None
        or _SHA.fullmatch(head_sha) is None
        or _SHA.fullmatch(reservation_commit_sha) is None
        or type(remote_reads_conservatively_consumed) is not int
        or remote_reads_conservatively_consumed <= 0
        or type(github_gets_conservatively_consumed) is not int
        or github_gets_conservatively_consumed < 0
        or type(artifact_downloads_conservatively_consumed) is not int
        or artifact_downloads_conservatively_consumed < 0
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_MATERIALIZER_RESERVATION_INVALID")
    state_base, host_identity_sha256 = _execution_state_context(root=root)
    relative = _EXECUTION_STATE_DIRECTORY / _EXECUTION_RESERVATION_NAMES[kind]
    reservation = {
        "schema_version": "data-torrent-recovery-v2-materializer-execution-reservation-v1",
        "reservation_status": "RESERVED_BEFORE_FIRST_EXTERNAL_READ",
        "mission_id": "data-torrent-recovery-v2",
        "repository": EXPECTED_REPOSITORY,
        "program_start_sha": DATA_TORRENT_RECOVERY_V2_START_SHA,
        "kind": kind,
        "runtime_main_sha": main_sha,
        "head_sha": head_sha,
        "reservation_commit_sha": reservation_commit_sha,
        "terminal_intent_raw_sha256": hashlib.sha256(terminal_intent_payload).hexdigest(),
        "delivery_intent_raw_sha256": hashlib.sha256(delivery_intent_payload).hexdigest(),
        "host_identity_sha256": host_identity_sha256,
        "observed_at": (observed_at or datetime.now(UTC))
        .astimezone(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "remote_reads_conservatively_consumed": remote_reads_conservatively_consumed,
        "github_gets_conservatively_consumed": github_gets_conservatively_consumed,
        "artifact_downloads_conservatively_consumed": (
            artifact_downloads_conservatively_consumed
        ),
        "automatic_retries": 0,
        "second_invocation_allowed": False,
        "additional_binding": dict(additional_binding),
    }
    payload = canonical_json_bytes(reservation) + b"\n"
    try:
        _recovery_v2_publish_exclusive_bytes(
            state_base / relative,
            payload,
            repository_root=state_base,
        )
    except (ChronosProductionError, FileExistsError):
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_MATERIALIZER_INVOCATION_ALREADY_RESERVED"
        ) from None
    return {
        "namespace": relative.as_posix(),
        "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "host_identity_sha256": host_identity_sha256,
        "local_receipt_authoritative": False,
        "second_invocation_allowed": False,
    }


def _run_git(
    arguments: tuple[str, ...],
    *,
    root: Path,
    effect_deadline_epoch: float | None = None,
) -> bytes:
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
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "LC_ALL": "C",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-terminal-git-hooks-") as hooks:
            command_timeout = 30.0
            is_remote_read = bool(arguments) and arguments[0] == "ls-remote"
            if is_remote_read:
                if effect_deadline_epoch is None:
                    raise TerminalEvidenceV2Error(
                        "RECOVERY_V2_TERMINAL_EFFECT_DEADLINE_INVALID"
                    )
                command_timeout = min(
                    command_timeout,
                    _require_effect_window(effect_deadline_epoch),
                )
            result = subprocess.run(  # noqa: S603  # nosec B603
                (
                    "git",
                    "--no-replace-objects",
                    "-c",
                    f"core.hooksPath={hooks}",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-c",
                    "http.followRedirects=false",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.https.allow=always",
                    "-c",
                    "submodule.recurse=false",
                    *arguments,
                ),
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=command_timeout,
            )
    except (OSError, subprocess.TimeoutExpired):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_GIT_INVALID") from None
    deadline_crossed = (
        bool(arguments)
        and arguments[0] == "ls-remote"
        and effect_deadline_epoch is not None
        and time.time() >= effect_deadline_epoch
    )
    if (
        result.returncode != 0
        or len(result.stdout) > 2 * 1024 * 1024
        or deadline_crossed
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_GIT_INVALID")
    return result.stdout


def _assert_remote_transport(*, root: Path) -> None:
    """Pin the only remote endpoint and reject repository-local transport rewrites."""

    remote_urls = _run_git(("remote", "get-url", "--push", "--all", "origin"), root=root)
    if remote_urls != f"{_EXPECTED_REMOTE_URL}\n".encode("ascii"):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_REMOTE_INVALID")
    local_config = _run_git(("config", "--local", "--null", "--list"), root=root)
    for record in (item for item in local_config.split(b"\0") if item):
        try:
            key = record.split(b"\n", 1)[0].decode("utf-8", errors="strict").casefold()
        except UnicodeDecodeError:
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_REMOTE_INVALID") from None
        if (
            (key.startswith("url.") and key.endswith(".insteadof"))
            or key.startswith("http.")
            or key in {"core.gitproxy", "remote.origin.proxy"}
        ):
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_REMOTE_INVALID")


def _relative(path: Path, *, root: Path) -> str:
    try:
        return Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(root))).as_posix()
    except ValueError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_INVALID") from None


def _assert_index_flags_clear(*, root: Path) -> None:
    raw = _run_git(("ls-files", "-v", "-z"), root=root)
    records = [record for record in raw.split(b"\0") if record]
    try:
        paths = [record[2:].decode("utf-8") for record in records]
    except UnicodeDecodeError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TRACKED_WORKTREE_DIRTY") from None
    if (
        any(len(record) < 3 or record[:2] != b"H " for record in records)
        or any(not path for path in paths)
        or len(paths) != len(set(paths))
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TRACKED_WORKTREE_DIRTY")


def _assert_regular_repository_file(
    path: Path,
    *,
    root: Path,
    maximum_bytes: int = 10 * 1024 * 1024,
) -> bytes:
    try:
        return _recovery_v2_evidence_bytes(
            path,
            repository_root=root,
            maximum_bytes=maximum_bytes,
        )
    except ChronosProductionError as error:
        if str(error).endswith("MISSING"):
            raise TerminalEvidenceV2Error(
                "RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_MISSING"
            ) from None
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_INVALID") from None


def _assert_unused_repository_output(path: Path, *, root: Path) -> None:
    """Reject existing, dangling-reparse, or externally redirected output paths."""

    try:
        _recovery_v2_require_unused_repository_output(path, repository_root=root)
    except ChronosProductionError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_OUTPUT_ROOT_INVALID") from None


def _source_destinations(root: Path) -> dict[Path, str]:
    release = root / ".torrent" / "release"
    sources: dict[Path, str] = {}
    for stage, paths in DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS.items():
        receipt = release / f"recovery-v2-controller-{stage.casefold().replace('_', '-')}.json"
        sources[receipt] = paths["controller"]
        if stage == "LIVE_ONCE":
            continue
        cache = release / "recovery-v2-predecessor-cache" / f"{_CACHE_SLUGS[stage]}.json"
        sources[cache] = _CACHE_ONLY_SOURCE
    sources[release / "chronos-runtime-bindings-v2.json"] = (
        DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH
    )
    sources[release / "recovery-v2-provider-neutralization.json"] = (
        DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH
    )
    sources[release / "recovery-v2-postmerge-quarantine.json"] = (
        DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH
    )
    sources[release / "recovery-v2-live-bundle-cache.json"] = _CACHE_ONLY_SOURCE
    return sources


def _inventory_regular_files_no_follow(*, directory: Path, root: Path) -> list[str]:
    """Inventory an existing repository subtree without following reparses."""

    try:
        _recovery_v2_prepare_repository_directory(directory, repository_root=root)
    except ChronosProductionError:
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID"
        ) from None
    pending = [directory]
    files: list[str] = []
    while pending:
        current = pending.pop()
        if _recovery_v2_path_is_reparse(current):
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID")
        try:
            entries = list(os.scandir(current))
        except OSError:
            raise TerminalEvidenceV2Error(
                "RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID"
            ) from None
        if current != directory and not entries:
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID")
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                raise TerminalEvidenceV2Error(
                    "RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID"
                ) from None
            if entry.is_symlink() or _recovery_v2_path_is_reparse(path):
                raise TerminalEvidenceV2Error(
                    "RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID"
                )
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(_relative(path, root=root))
            else:
                raise TerminalEvidenceV2Error(
                    "RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID"
                )
    return sorted(files)


def _snapshot_worktree(
    *,
    root: Path,
    main_sha: str,
    expected_sources: Mapping[Path, str],
    expected_source_payloads: Mapping[Path, bytes],
) -> tuple[dict[str, object], dict[Path, bytes]]:
    tracked = _run_git(("status", "--porcelain=v1", "--untracked-files=no"), root=root)
    if tracked != b"":
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TRACKED_WORKTREE_DIRTY")
    _assert_index_flags_clear(root=root)
    raw_untracked = _run_git(("ls-files", "--others", "--exclude-standard", "-z"), root=root)
    try:
        untracked = [item.decode("utf-8") for item in raw_untracked.split(b"\0") if item]
    except UnicodeDecodeError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_UNTRACKED_INVALID") from None
    expected_paths = sorted(_relative(path, root=root) for path in expected_sources)
    if sorted(untracked) != expected_paths or len(untracked) != len(set(untracked)):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_UNTRACKED_INVALID")
    release_root = root / ".torrent" / "release"
    physical = _inventory_regular_files_no_follow(directory=release_root, root=root)
    if physical != expected_paths:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_EPHEMERAL_ROOT_INVALID")
    if set(expected_source_payloads) != set(expected_sources):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_SOURCE_DRIFT")
    revalidated_source_payloads: dict[Path, bytes] = {}
    source_by_relative: dict[str, Path] = {}
    for source in expected_sources:
        relative = _relative(source, root=root)
        payload = _assert_regular_repository_file(
            source,
            root=root,
            maximum_bytes=(
                16 * 1024 * 1024
                if expected_sources[source] == _CACHE_ONLY_SOURCE
                else 10 * 1024 * 1024
            ),
        )
        if payload != expected_source_payloads[source]:
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_SOURCE_DRIFT")
        revalidated_source_payloads[source] = payload
        source_by_relative[relative] = source
    bindings = []
    for relative in expected_paths:
        source_path = source_by_relative.get(relative)
        payload = (
            revalidated_source_payloads[source_path]
            if source_path is not None
            else _assert_regular_repository_file(root / relative, root=root)
        )
        bindings.append({"path": relative, "raw_sha256": hashlib.sha256(payload).hexdigest()})
    return (
        {
            "head_sha": main_sha,
            "tracked_status": "CLEAN",
            "tracked_status_porcelain_sha256": _EMPTY_SHA256,
            "nonignored_untracked_allowlist": bindings,
            "unexpected_nonignored_untracked_paths": [],
            "ephemeral_release_root": ".torrent/release",
            "ephemeral_release_paths_exact": True,
        },
        revalidated_source_payloads,
    )


def _assert_pre_reservation_worktree(
    *,
    root: Path,
    expected_sources: Mapping[Path, str],
    allowed_existing_outputs: Mapping[Path, bytes] | None = None,
) -> None:
    if _run_git(("status", "--porcelain=v1", "--untracked-files=no"), root=root) != b"":
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TRACKED_WORKTREE_DIRTY")
    _assert_index_flags_clear(root=root)
    raw_untracked = _run_git(("ls-files", "--others", "--exclude-standard", "-z"), root=root)
    try:
        observed = sorted(item.decode("utf-8") for item in raw_untracked.split(b"\0") if item)
    except UnicodeDecodeError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_UNTRACKED_INVALID") from None
    allowed_existing_outputs = allowed_existing_outputs or {}
    existing_outputs: list[Path] = []
    for path, expected_payload in allowed_existing_outputs.items():
        if not os.path.lexists(path):
            continue
        if _assert_regular_repository_file(path, root=root) != expected_payload:
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
        existing_outputs.append(path)
    if allowed_existing_outputs:
        intent_parents = {path.parent for path in allowed_existing_outputs}
        if len(intent_parents) != 1:
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
        intent_dir = next(iter(intent_parents))
        if os.path.lexists(intent_dir):
            physical_intents = _inventory_regular_files_no_follow(directory=intent_dir, root=root)
            if physical_intents != sorted(
                _relative(path, root=root) for path in existing_outputs
            ):
                raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    source_paths = sorted(_relative(path, root=root) for path in expected_sources)
    expected = sorted(
        source_paths + [_relative(path, root=root) for path in existing_outputs]
    )
    release_root = root / ".torrent" / "release"
    physical = _inventory_regular_files_no_follow(directory=release_root, root=root)
    if observed != expected or physical != source_paths or len(observed) != len(set(observed)):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_UNTRACKED_INVALID")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _utc_instant(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError
    return parsed


def _decode_singleton_cache(
    payload: bytes,
    *,
    expected_kind: str,
    expected_filename: str,
) -> tuple[dict[str, object], bytes]:
    try:
        if (
            not payload
            or len(payload) > 16 * 1024 * 1024
            or not payload.endswith(b"\n")
            or payload.startswith(b"\xef\xbb\xbf")
            or b"\x00" in payload
            or b"\r" in payload
        ):
            raise ValueError
        cache = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(cache, dict) or payload != (
            json.dumps(cache, sort_keys=True) + "\n"
        ).encode("utf-8"):
            raise ValueError
        encoded = cache.get("payload_base64")
        attestation = cache.get("attestation")
        if (
            set(cache)
            != {
                "schema_version",
                "kind",
                "artifact_filename",
                "payload_base64",
                "attestation",
            }
            or cache.get("schema_version")
            != "data-torrent-recovery-v2-singleton-cache-v1"
            or cache.get("kind") != expected_kind
            or cache.get("artifact_filename") != expected_filename
            or not isinstance(encoded, str)
            or not isinstance(attestation, dict)
        ):
            raise ValueError
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
        if not decoded or len(decoded) > 10 * 1024 * 1024:
            raise ValueError
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_INVALID"
        ) from None
    return cast(dict[str, object], attestation), decoded


def _validate_live_controller_cache_binding(
    *,
    controller_payload: bytes,
    attestation: Mapping[str, object],
    semantics: Mapping[str, object],
    main_sha: str,
    live_run_id: str,
) -> None:
    try:
        controller = json.loads(
            controller_payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(controller, dict) or controller_payload != _json_bytes(controller):
            raise ValueError
        proof = controller.get("pre_effect_proof")
        inputs = proof.get("stage_inputs") if isinstance(proof, dict) else None
        terminal = controller.get("terminal_evidence")
        try:
            expected_terminalization_reservation = (
                _recovery_v2_terminalization_effect_reservation(
                    stage="LIVE_ONCE",
                    workflow_run_id=int(live_run_id),
                    stage_inputs=(
                        cast(dict[str, object], inputs) if isinstance(inputs, dict) else {}
                    ),
                )
            )
            terminal_run = terminal.get("terminal_run") if isinstance(terminal, dict) else None
            terminal_updated_at = _utc_instant(
                terminal_run.get("updated_at") if isinstance(terminal_run, dict) else None
            )
            terminalization_completed_at = _utc_instant(
                controller.get("terminalization_completed_at")
            )
            terminal_deadline = datetime.fromtimestamp(
                cast(
                    int,
                    expected_terminalization_reservation[
                        "controller_terminalization_deadline_epoch"
                    ],
                ),
                tz=UTC,
            )
            if not (
                _utc_instant(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE)
                <= terminal_updated_at
                <= terminalization_completed_at
                <= terminal_deadline
            ):
                raise ValueError
        except (ChronosProductionError, TypeError, ValueError):
            raise ValueError from None
        if (
            set(controller)
            != {
                "schema_version",
                "verdict",
                "stage",
                "main_sha",
                "inputs_sha256",
                "automatic_retries",
                "mutations_attempted",
                "mutations_confirmed",
                "pre_effect_proof",
                "pre_effect_proof_sha256",
                "workflow_path",
                "workflow_run_id",
                "terminalization_effect_reservation",
                "terminalization_completed_at",
                "terminal_evidence",
            }
            or controller.get("schema_version")
            != "data-torrent-recovery-v2-controller-cycle-v1"
            or controller.get("verdict") != "TERMINAL_SUCCESS_CONFIRMED"
            or controller.get("stage") != "LIVE_ONCE"
            or controller.get("main_sha") != main_sha
            or controller.get("automatic_retries") != 0
            or controller.get("mutations_attempted") != ["ENABLE", "DISPATCH", "DISABLE"]
            or controller.get("mutations_confirmed") != ["ENABLE", "DISPATCH", "DISABLE"]
            or controller.get("workflow_path")
            != ".github/workflows/data-torrent-live-v2.yml"
            or controller.get("workflow_run_id") != int(live_run_id)
            or controller.get("terminalization_effect_reservation")
            != expected_terminalization_reservation
            or not isinstance(proof, dict)
            or not isinstance(inputs, dict)
            or controller.get("inputs_sha256")
            != hashlib.sha256(
                json.dumps(inputs, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
            or controller.get("pre_effect_proof_sha256")
            != hashlib.sha256(
                json.dumps(proof, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
            or not isinstance(terminal, dict)
            or terminal.get("attestation") != attestation
            or terminal.get("semantic_projection_sha256")
            != hashlib.sha256(
                json.dumps(semantics, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest()
        ):
            raise ValueError
        from scripts.dispatch_data_torrent_recovery_v2_stage import (
            _validate_terminal_success_evidence,
        )

        _validate_terminal_success_evidence(
            stage="LIVE_ONCE",
            main_sha=main_sha,
            run_id=live_run_id,
            terminal=terminal,
            expected_attestation=attestation,
        )
    except Exception:
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_INVALID"
        ) from None


def _intent_documents(
    *,
    main_sha: str,
    live_run_id: str,
    engineering_numbers: tuple[int, ...],
) -> tuple[dict[str, object], dict[str, object]]:
    delivery_gets = 2 * len(engineering_numbers) + 3
    common: dict[str, object] = {
        "verdict": "RESERVED_NOT_ATTEMPTED",
        "repository": EXPECTED_REPOSITORY,
        "runtime_main_sha": main_sha,
        "reservation_parent_sha": main_sha,
        "pr_c_branch": _BRANCH,
        "automatic_retries": 0,
    }
    terminal: dict[str, object] = {
        **common,
        "schema_version": "data-torrent-recovery-v2-terminal-evidence-reservation-v1",
        "live_run_id": live_run_id,
        "terminal_evidence_dir": DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR,
        "github_gets_upper_bound": {
            "runtime_close_live_bundle": 0,
            "runtime_close_hold": 12,
            "runtime_close_main_ref": 1,
            "pr_c_c1_status_observations": 30,
            "pr_c_c2_status_observations": 30,
            "postmerge_run_observation": 19,
            "postmerge_final_gate": 34,
            "total": 126,
        },
        "artifact_downloads_upper_bound": {
            "runtime_close_live_bundle": 0,
            "postmerge_final_gate": 1,
            "total": 1,
        },
        "git_remote_ref_observations_upper_bound": 1,
        "pr_c_safe_v2_cycles": {
            "reservation_before_pr": 0,
            "phase_one_expected_hold": 1,
            "candidate_exact_head": 1,
            "postmerge": 1,
            "total": 3,
            "reruns": 0,
        },
        "pr_c_pull_request_writes_upper_bound": {
            "create": 1,
            "ready_for_review": 0,
            "total": 1,
        },
        "shared_pr_c_git_effects_upper_bound": {
            "commits": 3,
            "non_force_pushes": 3,
            "force_pushes": 0,
        },
    }
    delivery: dict[str, object] = {
        **common,
        "schema_version": "data-torrent-recovery-v2-delivery-observation-reservation-v1",
        "engineering_pull_request_numbers": list(engineering_numbers),
        "github_gets_upper_bound": {
            "engineering_pull_requests": len(engineering_numbers),
            "safe_v2_run_inventory": 1,
            "safe_v2_exact_head_jobs": len(engineering_numbers),
            "terminal_phase_one_jobs": 1,
            "terminal_open_pr_inventory": 1,
            "total": delivery_gets,
        },
        "artifact_downloads_upper_bound": {"total": 0},
        "git_remote_ref_observations_upper_bound": 1,
        "shared_pr_c_git_effects_accounted_by": "TERMINAL_INTENT",
        "terminal_read_budget_accounted_by": "TERMINAL_INTENT",
    }
    intent_set_sha256 = hashlib.sha256(
        canonical_json_bytes({"delivery": delivery, "terminal": terminal})
    ).hexdigest()
    terminal["intent_set_sha256"] = intent_set_sha256
    delivery["intent_set_sha256"] = intent_set_sha256
    return terminal, delivery


def reserve_terminal_and_delivery_evidence(
    *,
    main_sha: str,
    live_run_id: str,
    pr_a_number: int,
    pr_b_number: int | None = None,
    root: Path = _ROOT,
) -> dict[str, object]:
    """Create the two local intents that must be committed and pushed before any GET."""

    root = Path(os.path.abspath(root))
    if (
        _SHA.fullmatch(main_sha) is None
        or _RUN_ID.fullmatch(live_run_id) is None
        or type(pr_a_number) is not int
        or pr_a_number <= 0
        or (
            pr_b_number is not None
            and (
                type(pr_b_number) is not int
                or pr_b_number <= 0
                or pr_b_number == pr_a_number
            )
        )
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_ARGUMENT_INVALID")
    engineering_numbers = (
        (pr_a_number,) if pr_b_number is None else (pr_a_number, pr_b_number)
    )
    terminal_path = root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH
    delivery_path = root / DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH
    intent_dir = terminal_path.parent
    if delivery_path.parent != intent_dir:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_LOCAL_WRITE_INVALID")
    try:
        assert_production_safety_locks(os.environ)
        validate_data_torrent_recovery_v2_authority(scale_stage="E4", repository_root=root)
        validate_data_torrent_recovery_v2_council_release(repository_root=root)
    except ChronosProductionError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_AUTHORITY_INVALID") from None
    if (
        _run_git(("rev-parse", "HEAD"), root=root).decode("ascii").strip() != main_sha
        or _run_git(("branch", "--show-current"), root=root).decode("utf-8").strip()
        != _BRANCH
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_HEAD_INVALID")
    terminal, delivery = _intent_documents(
        main_sha=main_sha,
        live_run_id=live_run_id,
        engineering_numbers=engineering_numbers,
    )
    terminal_payload = _json_bytes(terminal)
    delivery_payload = _json_bytes(delivery)
    sources = _source_destinations(root)
    _assert_pre_reservation_worktree(
        root=root,
        expected_sources=sources,
        allowed_existing_outputs={
            terminal_path: terminal_payload,
            delivery_path: delivery_payload,
        },
    )
    try:
        _recovery_v2_prepare_repository_directory(intent_dir, repository_root=root)
        for path, payload in (
            (terminal_path, terminal_payload),
            (delivery_path, delivery_payload),
        ):
            if os.path.lexists(path):
                if _assert_regular_repository_file(path, root=root) != payload:
                    raise TerminalEvidenceV2Error(
                        "RECOVERY_V2_TERMINAL_RESERVATION_INVALID"
                    )
                continue
            try:
                _write_exclusive(path, payload, root=root)
            except TerminalEvidenceV2Error as error:
                if (
                    str(error) != "RECOVERY_V2_TERMINAL_INVOCATION_ALREADY_CONSUMED"
                    or _assert_regular_repository_file(path, root=root) != payload
                ):
                    raise
        intent_identity = _recovery_v2_directory_identity(
            intent_dir,
            repository_root=root,
        )
        _recovery_v2_fsync_repository_directory(
            intent_dir,
            intent_identity,
            repository_root=root,
        )
    except (ChronosProductionError, OSError):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_LOCAL_WRITE_INVALID") from None
    return {
        "terminal_intent": terminal,
        "delivery_intent": delivery,
    }


def _strict_intent(path: Path, *, root: Path) -> tuple[bytes, dict[str, object]]:
    payload = _assert_regular_repository_file(path, root=root)
    if b"\r" in payload or not payload.endswith(b"\n"):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    try:
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID") from None
    if not isinstance(document, dict):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    return payload, document


def _validate_authoritative_intent_set(
    *,
    root: Path,
    main_sha: str,
    live_run_id: str,
    engineering_numbers: tuple[int, ...],
    reservation_commit_sha: str,
    require_head_equals_reservation: bool,
    verify_remote: bool = True,
    effect_deadline_epoch: float | None = None,
) -> tuple[bytes, dict[str, object], bytes, dict[str, object], str]:
    if _SHA.fullmatch(reservation_commit_sha) is None:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    terminal_path = root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH
    delivery_path = root / DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH
    terminal_payload, terminal = _strict_intent(terminal_path, root=root)
    delivery_payload, delivery = _strict_intent(delivery_path, root=root)
    expected_terminal, expected_delivery = _intent_documents(
        main_sha=main_sha,
        live_run_id=live_run_id,
        engineering_numbers=engineering_numbers,
    )
    if terminal != expected_terminal or delivery != expected_delivery:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    head_sha = _run_git(("rev-parse", "HEAD"), root=root).decode("ascii").strip()
    parents = _run_git(
        ("rev-list", "--parents", "-n", "1", reservation_commit_sha),
        root=root,
    ).decode("ascii").split()
    if (
        _run_git(("branch", "--show-current"), root=root).decode("utf-8").strip()
        != _BRANCH
        or _SHA.fullmatch(head_sha) is None
        or parents != [reservation_commit_sha, main_sha]
        or (require_head_equals_reservation and head_sha != reservation_commit_sha)
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    _run_git(("merge-base", "--is-ancestor", reservation_commit_sha, head_sha), root=root)
    if (
        _run_git(
            (
                "show",
                f"{reservation_commit_sha}:{DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH}",
            ),
            root=root,
        )
        != terminal_payload
        or _run_git(
            (
                "show",
                f"{reservation_commit_sha}:{DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH}",
            ),
            root=root,
        )
        != delivery_payload
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_INVALID")
    _assert_remote_transport(root=root)
    if verify_remote:
        remote = _run_git(
            ("ls-remote", "--refs", _EXPECTED_REMOTE_URL, f"refs/heads/{_BRANCH}"),
            root=root,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        if remote != f"{head_sha}\trefs/heads/{_BRANCH}\n".encode("ascii"):
            raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_RESERVATION_NOT_DURABLE")
    if _run_git(("status", "--porcelain=v1", "--untracked-files=no"), root=root) != b"":
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TRACKED_WORKTREE_DIRTY")
    _assert_index_flags_clear(root=root)
    return terminal_payload, terminal, delivery_payload, delivery, head_sha


def _materialize_reserved_terminal_evidence(
    *,
    main_sha: str,
    live_run_id: str,
    root: Path,
    final_dir: Path,
    reservation_payload: bytes,
    reservation_commit_sha: str,
    sources: Mapping[Path, str],
    source_payloads: Mapping[Path, bytes],
    token: str,
    hold_loader: Callable[..., dict[str, Any]],
    main_loader: Callable[..., str],
    effect_deadline_epoch: float,
) -> dict[str, object]:
    """Collect and atomically materialize terminal evidence after reservation."""

    live_cache_path = root / ".torrent" / "release" / "recovery-v2-live-bundle-cache.json"
    live_controller_path = (
        root / ".torrent" / "release" / "recovery-v2-controller-live-once.json"
    )
    try:
        from scripts.dispatch_data_torrent_recovery_v2_stage import (
            _decode_live_bundle_cache,
            _validate_live_success_payloads,
        )

        live_attestation, live_payloads = _decode_live_bundle_cache(
            payload=source_payloads[live_cache_path],
            main_sha=main_sha,
            run_id=live_run_id,
        )
        live_controller = json.loads(
            source_payloads[live_controller_path],
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        live_pre_effect_proof = (
            live_controller.get("pre_effect_proof")
            if isinstance(live_controller, dict)
            else None
        )
        live_inputs = (
            live_pre_effect_proof.get("stage_inputs")
            if isinstance(live_pre_effect_proof, dict)
            else None
        )
        if not isinstance(live_pre_effect_proof, dict) or not isinstance(
            live_inputs, dict
        ):
            raise ValueError
        live_semantics = _validate_live_success_payloads(
            artifacts=live_payloads,
            main_sha=main_sha,
            run_id=live_run_id,
            inputs=cast(dict[str, str], live_inputs),
            pre_effect_proof=cast(dict[str, object], live_pre_effect_proof),
        )
        _validate_live_controller_cache_binding(
            controller_payload=source_payloads[live_controller_path],
            attestation=live_attestation,
            semantics=live_semantics,
            main_sha=main_sha,
            live_run_id=live_run_id,
        )
    except TerminalEvidenceV2Error:
        raise
    except Exception:
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_LOCAL_EVIDENCE_INVALID"
        ) from None
    try:
        _require_effect_window(effect_deadline_epoch)
        hold = hold_loader(
            required_successful_ci_sha=main_sha,
            recovery_v2=True,
            repository_override=EXPECTED_REPOSITORY,
            token_override=token,
            current_run_id=0,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        _require_effect_window(effect_deadline_epoch)
        _recovery_v2_terminal_hold(hold, runtime_main_sha=main_sha)
        observed_main = main_loader(
            repository=EXPECTED_REPOSITORY,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        _require_effect_window(effect_deadline_epoch)
    except Exception:
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_REMOTE_EVIDENCE_INVALID"
        ) from None
    if observed_main != main_sha:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_MAIN_DRIFT")
    if (
        _run_git(("rev-parse", "HEAD"), root=root).decode("ascii").strip()
        != reservation_commit_sha
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_HEAD_DRIFT")
    worktree, revalidated_source_payloads = _snapshot_worktree(
        root=root,
        main_sha=reservation_commit_sha,
        expected_sources=sources,
        expected_source_payloads=source_payloads,
    )
    revalidated_live_attestation, revalidated_live_payloads = _decode_live_bundle_cache(
        payload=revalidated_source_payloads[live_cache_path],
        main_sha=main_sha,
        run_id=live_run_id,
    )
    if (
        revalidated_live_attestation != live_attestation
        or revalidated_live_payloads != live_payloads
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_SOURCE_DRIFT")
    live_attestation_payload = _json_bytes(live_attestation)
    singleton_outputs: dict[str, tuple[dict[str, object], bytes]] = {}
    for stage, slug in _CACHE_SLUGS.items():
        paths = DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS[stage]
        cache_path = (
            root
            / ".torrent"
            / "release"
            / "recovery-v2-predecessor-cache"
            / f"{slug}.json"
        )
        singleton_outputs[stage] = _decode_singleton_cache(
            revalidated_source_payloads[cache_path],
            expected_kind=_CACHE_KINDS[stage],
            expected_filename=Path(paths["payload"]).name,
        )
    observed_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    quiescence = {
        "schema_version": "data-torrent-recovery-v2-terminal-quiescence-v1",
        "repository": EXPECTED_REPOSITORY,
        "runtime_main_sha": main_sha,
        "observed_at": observed_at,
        "observed_after_live_run_id": int(live_run_id),
        "live_bundle_attestation": {
            "path": DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
            "raw_sha256": hashlib.sha256(live_attestation_payload).hexdigest(),
            "run_id": int(live_run_id),
            "artifact_id": live_attestation["artifact_id"],
            "archive_sha256": live_attestation["archive_sha256"],
        },
        "main_ref_sha": observed_main,
        "full_hold": hold,
        "full_hold_sha256": hashlib.sha256(canonical_json_bytes(hold)).hexdigest(),
        "quiescence_scope": "RUNTIME_CLOSE_BEFORE_PR_C",
        "production_workflows_quiescent_at_runtime_close": True,
        "global_queue_empty_at_runtime_close": True,
        "worktree": worktree,
        "reservation": {
            "source_path": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            "durable_path": DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
            "raw_sha256": hashlib.sha256(reservation_payload).hexdigest(),
            "reservation_commit_sha": reservation_commit_sha,
            "remote_branch_verified_before_github_reads": True,
        },
        "reservation_git_effects_exact": {
            "commits": 1,
            "non_force_pushes": 1,
            "force_pushes": 0,
        },
        "observed_before_terminal_output_materialization": True,
        "github_gets_exact": {
            "live_bundle": 0,
            "final_hold": 12,
            "main_ref": 1,
            "total": 13,
        },
        "artifact_downloads_exact": {"live_bundle": 0, "total": 0},
        "git_remote_ref_observations_exact": 1,
        "remote_gets_exact_total": 14,
        "automatic_retries": 0,
    }

    try:
        _recovery_v2_prepare_repository_directory(final_dir, repository_root=root)
        for source, destination_relative in sources.items():
            if destination_relative == _CACHE_ONLY_SOURCE:
                continue
            _write_exclusive(
                root / destination_relative,
                revalidated_source_payloads[source],
                root=root,
            )
        for stage, (attestation, payload) in singleton_outputs.items():
            paths = DATA_TORRENT_RECOVERY_V2_STAGE_EVIDENCE_PATHS[stage]
            _write_exclusive(root / paths["attestation"], _json_bytes(attestation), root=root)
            _write_exclusive(root / paths["payload"], payload, root=root)
        for filename, payload in revalidated_live_payloads.items():
            _write_exclusive(final_dir / "artifacts" / filename, payload, root=root)
        _write_exclusive(
            root / DATA_TORRENT_RECOVERY_V2_LIVE_BUNDLE_ATTESTATION_PATH,
            live_attestation_payload,
            root=root,
        )
        _write_exclusive(
            root / DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_EVIDENCE_PATH,
            reservation_payload,
            root=root,
        )
        # The quiescence receipt is the sole completion marker and is published last.
        _write_exclusive(
            root / DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            _json_bytes(quiescence),
            root=root,
        )
    except (ChronosProductionError, OSError):
        raise TerminalEvidenceV2Error(
            "RECOVERY_V2_TERMINAL_MATERIALIZATION_INVALID"
        ) from None
    return quiescence


def materialize_terminal_evidence(
    *,
    main_sha: str,
    live_run_id: str,
    pr_a_number: int,
    reservation_commit_sha: str,
    pr_b_number: int | None = None,
    root: Path = _ROOT,
    hold_loader: Callable[..., dict[str, Any]] = verify_hold,
    main_loader: Callable[..., str] = exact_main_sha_v2,
) -> dict[str, object]:
    root = Path(os.path.abspath(root))
    if (
        _SHA.fullmatch(main_sha) is None
        or _RUN_ID.fullmatch(live_run_id) is None
        or type(pr_a_number) is not int
        or pr_a_number <= 0
        or (
            pr_b_number is not None
            and (
                type(pr_b_number) is not int
                or pr_b_number <= 0
                or pr_b_number == pr_a_number
            )
        )
    ):
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_ARGUMENT_INVALID")
    engineering_numbers = (
        (pr_a_number,) if pr_b_number is None else (pr_a_number, pr_b_number)
    )
    final_dir = root / DATA_TORRENT_RECOVERY_V2_TERMINAL_EVIDENCE_DIR
    _assert_unused_repository_output(final_dir, root=root)
    try:
        assert_production_safety_locks(os.environ)
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage="E4",
            repository_root=root,
            council_closure_phase="RESERVATION",
        )
        validate_data_torrent_recovery_v2_reservation_council_closure(
            repository_root=root
        )
    except ChronosProductionError:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_AUTHORITY_INVALID") from None
    effect_deadline_epoch = _materializer_deadline_epoch(authority_deadline)
    token = os.getenv("GH_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if not token or len(token.encode("utf-8")) > 2_048:
        raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_TOKEN_MISSING")
    sources = _source_destinations(root)
    _assert_pre_reservation_worktree(root=root, expected_sources=sources)
    source_payloads = {
        source: _assert_regular_repository_file(
            source,
            root=root,
            maximum_bytes=(
                16 * 1024 * 1024
                if sources[source] == _CACHE_ONLY_SOURCE
                else 10 * 1024 * 1024
            ),
        )
        for source in sources
    }
    (
        local_reservation_payload,
        _local_terminal,
        local_delivery_payload,
        _local_delivery,
        local_head_sha,
    ) = (
        _validate_authoritative_intent_set(
            root=root,
            main_sha=main_sha,
            live_run_id=live_run_id,
            engineering_numbers=engineering_numbers,
            reservation_commit_sha=reservation_commit_sha,
            require_head_equals_reservation=True,
            verify_remote=False,
        )
    )
    _reserve_materializer_execution(
        kind="TERMINAL",
        root=root,
        main_sha=main_sha,
        head_sha=local_head_sha,
        reservation_commit_sha=reservation_commit_sha,
        terminal_intent_payload=local_reservation_payload,
        delivery_intent_payload=local_delivery_payload,
        remote_reads_conservatively_consumed=14,
        github_gets_conservatively_consumed=13,
        artifact_downloads_conservatively_consumed=0,
        additional_binding={
            "engineering_pull_request_numbers": list(engineering_numbers),
            "live_run_id": live_run_id,
        },
    )
    reservation_payload, _terminal, _delivery_payload, _delivery, _head_sha = (
        _validate_authoritative_intent_set(
            root=root,
            main_sha=main_sha,
            live_run_id=live_run_id,
            engineering_numbers=engineering_numbers,
            reservation_commit_sha=reservation_commit_sha,
            require_head_equals_reservation=True,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    )

    return _materialize_reserved_terminal_evidence(
        main_sha=main_sha,
        live_run_id=live_run_id,
        root=root,
        final_dir=final_dir,
        reservation_payload=reservation_payload,
        reservation_commit_sha=reservation_commit_sha,
        sources=sources,
        source_payloads=source_payloads,
        token=token,
        hold_loader=hold_loader,
        main_loader=main_loader,
        effect_deadline_epoch=effect_deadline_epoch,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--live-run-id", required=True)
    parser.add_argument("--pr-a-number", type=int, required=True)
    parser.add_argument("--pr-b-number", type=int)
    parser.add_argument("--reservation-commit-sha")
    parser.add_argument("--reserve-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.reserve_only:
            if args.reservation_commit_sha is not None:
                raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_ARGUMENT_INVALID")
            result = reserve_terminal_and_delivery_evidence(
                main_sha=cast(str, args.main_sha),
                live_run_id=cast(str, args.live_run_id),
                pr_a_number=cast(int, args.pr_a_number),
                pr_b_number=cast(int | None, args.pr_b_number),
            )
        else:
            if args.reservation_commit_sha is None:
                raise TerminalEvidenceV2Error("RECOVERY_V2_TERMINAL_ARGUMENT_INVALID")
            result = materialize_terminal_evidence(
                main_sha=cast(str, args.main_sha),
                live_run_id=cast(str, args.live_run_id),
                pr_a_number=cast(int, args.pr_a_number),
                pr_b_number=cast(int | None, args.pr_b_number),
                reservation_commit_sha=cast(str, args.reservation_commit_sha),
            )
    except Exception as error:
        print(
            str(error)
            if isinstance(error, TerminalEvidenceV2Error)
            else "RECOVERY_V2_TERMINAL_MATERIALIZATION_FAILED"
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
