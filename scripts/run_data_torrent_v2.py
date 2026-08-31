"""Run the single Recovery V2 LIVE plus in-process replay workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from robin.chronos_production import ChronosProductionError
from robin.data_torrent.runtime import (
    FINAL_ARTIFACT_NAMES,
    DataTorrentRuntimeError,
    _assert_final_artifact_closure,
    _json_artifact_document,
    execute_data_torrent_v2,
)
from robin.recovery_v2_filesystem import (
    anchored_temporary_directory,
    prepare_repository_directory,
    publish_directory_noreplace,
    require_inherited_windows_directory_capability,
)
from scripts.recovery_v2_supervision import (
    SUPERVISOR_CHILD_STUCK_EXIT,
    SUPERVISOR_EXPORT_EXIT,
    SUPERVISOR_TIMEOUT_EXIT,
    RecoveryV2SupervisionError,
    adopt_or_create_json_fallback,
    promote_validated_file,
    remaining_effect_timeout,
    require_effect_deadline_open,
    run_child_once,
)

ROOT = Path(__file__).resolve().parents[1]
_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]*(?::[A-Z0-9_.-]+)*$")
_FORBIDDEN_EXPORT_KEY_PARTS = (
    "api_key",
    "database_url",
    "password",
    "secret_value",
    "access_key",
    "private_key",
)
_MAX_LIVE_EXPORT_BYTES = 10 * 1024 * 1024
_LIVE_SUPERVISOR_TIMEOUT_SECONDS = 1_080


def _zero_effects() -> dict[str, Any]:
    return {
        "schema_version": "robin-data-torrent-live-runtime-effects-v1",
        "accounting_status": "COMPLETE_CONSERVATIVE",
        "postgresql": {
            "read_transactions_attempted": 0,
            "function_reads_attempted": 0,
            "mutating_function_calls_attempted": 0,
            "mutating_function_calls_completed": 0,
            "mutating_function_outcomes_ambiguous": 0,
            "possible_durable_mutations_upper_bound": 0,
            "connection_attempts_upper_bound": 0,
            "connection_attempts_maximum": 53,
            "automatic_retries": 0,
        },
        "official": {"physical_reads_attempted": 0, "automatic_retries": 0},
        "odds": {
            "dns_resolutions_attempted": 0,
            "provider_requests_attempted": 0,
            "credits_used_upper_bound": 0,
            "automatic_retries": 0,
        },
        "r2": {
            "puts_attempted": 0,
            "gets_attempted": 0,
            "lists_attempted": 0,
            "deletes_attempted": 0,
            "put_outcomes_ambiguous_upper_bound": 0,
            "automatic_retries": 0,
        },
    }


def _supervisor_effects() -> dict[str, Any]:
    effects = _zero_effects()
    effects["accounting_status"] = "UNKNOWN_OR_UPPER_BOUND"
    effects["postgresql"] = {
        "read_transactions_attempted": 6,
        "function_reads_attempted": 6,
        "mutating_function_calls_attempted": 41,
        "mutating_function_calls_completed": 0,
        "mutating_function_outcomes_ambiguous": 41,
        "possible_durable_mutations_upper_bound": 41,
        "connection_attempts_upper_bound": 53,
        "connection_attempts_maximum": 53,
        "automatic_retries": 0,
    }
    effects["official"] = {"physical_reads_attempted": 50, "automatic_retries": 0}
    effects["odds"] = {
        "dns_resolutions_attempted": 5,
        "provider_requests_attempted": 5,
        "credits_used_upper_bound": 1_000,
        "automatic_retries": 0,
    }
    effects["r2"] = {
        "puts_attempted": 2,
        "gets_attempted": 1,
        "lists_attempted": 0,
        "deletes_attempted": 0,
        "put_outcomes_ambiguous_upper_bound": 2,
        "automatic_retries": 0,
    }
    return effects


def _write_failure(
    output_dir: Path,
    code: str,
    *,
    effects: Mapping[str, Any] | None = None,
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "torrent-run-failure-v2.json"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "robin-data-torrent-run-failure-v2",
                        "mission_id": "data-torrent-recovery-v2",
                        "status": "FAILED",
                        "error_code": code,
                        "effects": dict(effects) if effects is not None else _zero_effects(),
                        "secret_values_observed": False,  # nosec B105 - boolean audit field.
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError:
        return


def _safe_error_code(error: BaseException) -> str:
    raw = str(error)
    if len(raw) <= 160 and _SAFE_ERROR_CODE.fullmatch(raw) is not None:
        return raw
    return "DATA_TORRENT_UNCLASSIFIED_FAILURE"


def _validated_effect_receipt(value: object) -> Mapping[str, Any] | None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "accounting_status",
        "postgresql",
        "official",
        "odds",
        "r2",
    }:
        return None
    expected_nested = {
        "postgresql": {
            "read_transactions_attempted",
            "function_reads_attempted",
            "mutating_function_calls_attempted",
            "mutating_function_calls_completed",
            "mutating_function_outcomes_ambiguous",
            "possible_durable_mutations_upper_bound",
            "connection_attempts_upper_bound",
            "connection_attempts_maximum",
            "automatic_retries",
        },
        "official": {"physical_reads_attempted", "automatic_retries"},
        "odds": {
            "dns_resolutions_attempted",
            "provider_requests_attempted",
            "credits_used_upper_bound",
            "automatic_retries",
        },
        "r2": {
            "puts_attempted",
            "gets_attempted",
            "lists_attempted",
            "deletes_attempted",
            "put_outcomes_ambiguous_upper_bound",
            "automatic_retries",
        },
    }
    if value.get("schema_version") != "robin-data-torrent-live-runtime-effects-v1" or value.get(
        "accounting_status"
    ) not in {"COMPLETE_CONSERVATIVE", "UNKNOWN_OR_UPPER_BOUND"}:
        return None
    for section, fields in expected_nested.items():
        observed = value.get(section)
        if (
            not isinstance(observed, dict)
            or set(observed) != fields
            or any(type(counter) is not int or counter < 0 for counter in observed.values())
            or observed.get("automatic_retries") != 0
        ):
            return None
    postgresql = value["postgresql"]
    official = value["official"]
    odds = value["odds"]
    r2 = value["r2"]
    if (
        postgresql["read_transactions_attempted"] > 6
        or postgresql["function_reads_attempted"] > 6
        or postgresql["mutating_function_calls_attempted"] > 41
        or postgresql["mutating_function_calls_completed"]
        > postgresql["mutating_function_calls_attempted"]
        or postgresql["mutating_function_outcomes_ambiguous"]
        > postgresql["mutating_function_calls_attempted"]
        or postgresql["possible_durable_mutations_upper_bound"]
        > postgresql["mutating_function_calls_attempted"]
        or postgresql["connection_attempts_upper_bound"]
        != postgresql["read_transactions_attempted"]
        + postgresql["function_reads_attempted"]
        + postgresql["mutating_function_calls_attempted"]
        or postgresql["connection_attempts_maximum"] != 53
        or official["physical_reads_attempted"] > 50
        or odds["dns_resolutions_attempted"] > 5
        or odds["provider_requests_attempted"] > 5
        or odds["credits_used_upper_bound"] > 1_000
        or r2["puts_attempted"] > 2
        or r2["gets_attempted"] > 1
        or r2["lists_attempted"] != 0
        or r2["deletes_attempted"] != 0
        or r2["put_outcomes_ambiguous_upper_bound"] > r2["puts_attempted"]
    ):
        return None
    if value.get("accounting_status") == "UNKNOWN_OR_UPPER_BOUND" and value != _supervisor_effects():
        return None
    return value


def _safe_effect_receipt(error: BaseException) -> Mapping[str, Any] | None:
    return _validated_effect_receipt(getattr(error, "effect_receipt", None))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _contains_forbidden_export_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (
                not (
                    (str(key) == "secret_values_observed" and item is False)
                    or (str(key) == "secret_value_readbacks" and item == 0)
                    or (str(key) == "password_null" and type(item) is bool)
                )
                and any(part in str(key).lower() for part in _FORBIDDEN_EXPORT_KEY_PARTS)
            )
            or _contains_forbidden_export_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_export_key(item) for item in value)
    return False


def _supervisor_fallback() -> dict[str, Any]:
    return {
        "schema_version": "robin-data-torrent-run-supervisor-failure-v2",
        "mission_id": "data-torrent-recovery-v2",
        "status": "FAILED",
        "error_code": "DATA_TORRENT_SUPERVISOR_AMBIGUOUS",
        "failure_class": "TRANSPORT_AMBIGUOUS",
        "effect_counter_certainty": "UNKNOWN_OR_UPPER_BOUND",
        "effects": _supervisor_effects(),
        "secret_values_observed": False,  # nosec B105 - boolean audit field.
    }


def _load_guarded_failure(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        payload = path.read_bytes()
        document = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError("DATA_TORRENT_FAILURE_EXPORT_INVALID") from None
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    ordinary = isinstance(document, dict) and set(document) == {
        "schema_version",
        "mission_id",
        "status",
        "error_code",
        "effects",
        "secret_values_observed",
    } and document.get("schema_version") == "robin-data-torrent-run-failure-v2"
    supervised = isinstance(document, dict) and set(document) == {
        "schema_version",
        "mission_id",
        "status",
        "error_code",
        "failure_class",
        "effect_counter_certainty",
        "effects",
        "secret_values_observed",
    } and (
        document.get("schema_version") == "robin-data-torrent-run-supervisor-failure-v2"
        and document.get("failure_class") == "TRANSPORT_AMBIGUOUS"
        and document.get("effect_counter_certainty") == "UNKNOWN_OR_UPPER_BOUND"
    )
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or bool(attributes & reparse)
        or not payload
        or len(payload) > 1_048_576
        or b"\x00" in payload
        or b"\r" in payload
        or not (ordinary or supervised)
        or document.get("mission_id") != "data-torrent-recovery-v2"
        or document.get("status") != "FAILED"
        or not isinstance(document.get("error_code"), str)
        or _SAFE_ERROR_CODE.fullmatch(document["error_code"]) is None
        or (
            supervised
            and document.get("error_code") != "DATA_TORRENT_SUPERVISOR_AMBIGUOUS"
        )
        or document.get("secret_values_observed") is not False
        or _contains_forbidden_export_key(document)
        or _validated_effect_receipt(document.get("effects")) is None
        or (supervised and document.get("effects") != _supervisor_effects())
    ):
        raise ChronosProductionError("DATA_TORRENT_FAILURE_EXPORT_INVALID")
    return cast(dict[str, Any], document)


def _validate_success_directory(path: Path) -> dict[str, str]:
    try:
        entries = list(path.iterdir())
    except OSError:
        raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID") from None
    if {entry.name for entry in entries} != set(FINAL_ARTIFACT_NAMES):
        raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID")
    total = 0
    artifacts: dict[str, bytes] = {}
    for entry in entries:
        try:
            metadata = entry.lstat()
            payload = entry.read_bytes()
        except OSError:
            raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID") from None
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        total += len(payload)
        artifacts[entry.name] = payload
        if (
            not stat.S_ISREG(metadata.st_mode)
            or entry.is_symlink()
            or bool(attributes & reparse)
            or not payload
            or b"\x00" in payload
            or total > _MAX_LIVE_EXPORT_BYTES
        ):
            raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID")
        if entry.suffix == ".json":
            try:
                document = json.loads(
                    payload,
                    object_pairs_hook=_unique_object,
                    parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID") from None
            if _contains_forbidden_export_key(document):
                raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID")
        else:
            try:
                payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID") from None
    try:
        manifest = _json_artifact_document(artifacts["torrent-real-batch-manifest-v1.json"])
        evidence_validity = manifest.get("evidence_validity")
        normalized_binding = (
            evidence_validity.get("binding") if isinstance(evidence_validity, dict) else None
        )
        if (
            manifest.get("status") != "SUCCESS"
            or manifest.get("data_torrent_ready") is not True
            or not isinstance(normalized_binding, dict)
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_EVIDENCE_BINDING_INVALID")
        _assert_final_artifact_closure(
            artifacts=artifacts,
            normalized_binding=normalized_binding,
        )
    except (DataTorrentRuntimeError, KeyError, TypeError, ValueError):
        raise ChronosProductionError("DATA_TORRENT_SUCCESS_EXPORT_INVALID") from None
    return {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in artifacts.items()
    }


def _validated_supervised_child_output(
    output_dir: Path,
    *,
    capability_fd: int | None,
    capability_handle: int | None,
) -> Path:
    """Accept only the supervisor's repository-contained output capability."""

    candidate = Path(os.path.abspath(output_dir))
    if os.name == "nt":
        if capability_fd is not None or type(capability_handle) is not int:
            raise RecoveryV2SupervisionError(
                "DATA_TORRENT_SUPERVISED_OUTPUT_INVALID"
            )
        try:
            require_inherited_windows_directory_capability(
                capability_handle,
                candidate.parent,
                repository_root=ROOT,
            )
        except OSError:
            raise RecoveryV2SupervisionError(
                "DATA_TORRENT_SUPERVISED_OUTPUT_INVALID"
            ) from None
        return candidate

    if capability_handle is not None or type(capability_fd) is not int or capability_fd < 0:
        raise RecoveryV2SupervisionError("DATA_TORRENT_SUPERVISED_OUTPUT_INVALID")
    capability = Path(f"/proc/self/fd/{capability_fd}")
    if candidate != capability / "artifacts":
        raise RecoveryV2SupervisionError("DATA_TORRENT_SUPERVISED_OUTPUT_INVALID")
    try:
        metadata = os.fstat(capability_fd)
        resolved_capability = Path(os.path.realpath(capability))
        resolved_root = Path(os.path.realpath(ROOT))
        resolved_capability.relative_to(resolved_root)
    except (OSError, ValueError):
        raise RecoveryV2SupervisionError(
            "DATA_TORRENT_SUPERVISED_OUTPUT_INVALID"
        ) from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryV2SupervisionError("DATA_TORRENT_SUPERVISED_OUTPUT_INVALID")
    return candidate


def _supervise(*, config: Path, output_dir: Path, failure_report: Path) -> int:
    try:
        fallback_sha256 = adopt_or_create_json_fallback(
            failure_report,
            _supervisor_fallback(),
        )
    except RecoveryV2SupervisionError:
        return SUPERVISOR_EXPORT_EXIT
    output_dir = Path(os.path.abspath(output_dir))
    try:
        prepare_repository_directory(output_dir.parent, repository_root=ROOT)
    except OSError:
        return SUPERVISOR_EXPORT_EXIT
    if os.path.lexists(output_dir):
        return SUPERVISOR_EXPORT_EXIT
    try:
        with anchored_temporary_directory(
            output_dir.parent,
            prefix=".live-v2-candidate-",
            repository_root=ROOT,
        ) as lease:
            candidate = lease.path / "artifacts"
            runtime_candidate = lease.runtime_path / "artifacts"
            timeout_seconds = remaining_effect_timeout(_LIVE_SUPERVISOR_TIMEOUT_SECONDS)
            if timeout_seconds == 0:
                return SUPERVISOR_TIMEOUT_EXIT
            try:
                lease.require_attached()
            except OSError:
                return SUPERVISOR_EXPORT_EXIT
            child_command = [
                sys.executable,
                "-m",
                "scripts.run_data_torrent_v2",
                "--config",
                str(config),
                "--output-dir",
                str(runtime_candidate),
                "--supervised-child",
            ]
            if lease.pass_fds:
                if len(lease.pass_fds) != 1:
                    return SUPERVISOR_EXPORT_EXIT
                child_command.extend(
                    ("--output-capability-fd", str(lease.pass_fds[0]))
                )
            if lease.pass_handles:
                if len(lease.pass_handles) != 1:
                    return SUPERVISOR_EXPORT_EXIT
                child_command.extend(
                    ("--output-capability-handle", str(lease.pass_handles[0]))
                )
            return_code = run_child_once(
                tuple(child_command),
                timeout_seconds=timeout_seconds,
                pass_fds=lease.pass_fds,
                pass_handles=lease.pass_handles,
            )
            if return_code in {
                SUPERVISOR_TIMEOUT_EXIT,
                SUPERVISOR_EXPORT_EXIT,
                SUPERVISOR_CHILD_STUCK_EXIT,
            }:
                return return_code
            if return_code < 0:
                return return_code
            if return_code == 0:
                try:
                    expected_files = _validate_success_directory(runtime_candidate)
                    lease.require_attached()
                    require_effect_deadline_open()
                    publish_directory_noreplace(
                        candidate,
                        output_dir,
                        repository_root=ROOT,
                        expected_files=expected_files,
                    )
                except (OSError, ChronosProductionError, RecoveryV2SupervisionError):
                    return SUPERVISOR_EXPORT_EXIT
                return 0
            candidate_failure = runtime_candidate / "torrent-run-failure-v2.json"
            try:

                def validate_candidate(path: Path) -> dict[str, Any]:
                    document = _load_guarded_failure(path)
                    if document.get("status") != "FAILED" or return_code == 0:
                        raise ChronosProductionError(
                            "DATA_TORRENT_FAILURE_EXPORT_INVALID"
                        )
                    return document

                promote_validated_file(
                    candidate_failure,
                    failure_report,
                    expected_fallback_sha256=fallback_sha256,
                    validator=validate_candidate,
                )
            except (ChronosProductionError, RecoveryV2SupervisionError):
                return SUPERVISOR_EXPORT_EXIT
            return return_code
    except OSError:
        # Candidate trees are intentionally retained. Recursive path cleanup here could
        # erase a substituted tree after the anchored publication handles are released.
        return SUPERVISOR_EXPORT_EXIT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "data" / "torrent-live-v2.json",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--failure-report", type=Path)
    parser.add_argument("--supervise", action="store_true")
    parser.add_argument("--supervised-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output-capability-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--output-capability-handle", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--validate-failure-report", type=Path)
    args = parser.parse_args()
    validate_failure = getattr(args, "validate_failure_report", None)
    if validate_failure is not None:
        _load_guarded_failure(validate_failure)
        return 0
    output_dir = getattr(args, "output_dir", None)
    if output_dir is None:
        parser.error("--output-dir is required")
    if getattr(args, "supervise", False):
        if getattr(args, "supervised_child", False):
            parser.error("--supervise and --supervised-child are mutually exclusive")
        failure_report = getattr(args, "failure_report", None)
        if failure_report is None:
            parser.error("--failure-report is required with --supervise")
        return _supervise(
            config=args.config,
            output_dir=output_dir,
            failure_report=failure_report,
        )
    if not getattr(args, "supervised_child", False):
        parser.error("direct execution is forbidden; use --supervise")
    try:
        output_dir = _validated_supervised_child_output(
            output_dir,
            capability_fd=getattr(args, "output_capability_fd", None),
            capability_handle=getattr(args, "output_capability_handle", None),
        )
    except (OSError, RecoveryV2SupervisionError):
        return SUPERVISOR_EXPORT_EXIT
    try:
        result = execute_data_torrent_v2(
            repository_root=ROOT,
            config_path=args.config,
            output_dir=output_dir,
        )
    except (ChronosProductionError, DataTorrentRuntimeError, ValueError) as error:
        code = _safe_error_code(error)
        _write_failure(output_dir, code, effects=_safe_effect_receipt(error))
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    except Exception as error:
        code = "DATA_TORRENT_UNCLASSIFIED_FAILURE"
        _write_failure(output_dir, code, effects=_safe_effect_receipt(error))
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    if result.get("data_torrent_ready") is not True:
        code = "DATA_TORRENT_LOSER_ZERO_POST_CLAIM_EFFECTS"
        observed = result.get("runtime_effects")
        _write_failure(
            output_dir,
            code,
            effects=_validated_effect_receipt(observed),
        )
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
