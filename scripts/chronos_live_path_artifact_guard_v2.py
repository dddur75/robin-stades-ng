"""Strict sanitized artifact guard for Recovery V2 identity evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, cast

from robin.chronos_production import (
    ChronosProductionError,
    validate_identity_seal_v2,
    validate_neon_branch_identity_go_v2,
)
from scripts.chronos_neon_branch_identity_v2 import (
    BRANCH_INVENTORY_FAILURE_CLASSES,
    GO_VERDICT,
    REPORT_SCHEMA,
)

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "database_url",
    "password",
    "secret_value",
    "access_key",
    "cursor_value",
    "raw_id",
)
_FAILURE_NEON_FIELDS = {
    "branch_count_before",
    "branch_count_after",
    "branches_observed",
    "branch_pages_read",
    "branch_count_reads",
    "inventory_exhaustive",
    "terminal_by_cardinality",
    "continuation_required",
    "continuation_followed_count",
    "terminal_pagination_metadata_present",
    "default_branch_count",
    "dsn_branch_matches_default",
    "branch_endpoint_concordant",
    "identity_intersection_size",
    "branch_inventory_failure_class",
}
_FAILURE_SOURCE_FIELDS = {
    "repository",
    "ref",
    "main_sha",
    "workflow_path",
    "run_id",
    "run_attempt",
}
_FAILURE_GITHUB_FIELDS = {
    "queued",
    "in_progress",
    "current_run_excluded",
    "exact_main_dispatch_count",
    "authority_window_dispatch_count",
}
_FAILURE_EFFECT_FIELDS = {
    "neon_gets",
    "neon_gets_exact",
    "neon_post",
    "neon_patch",
    "neon_delete",
    "compute_wakes",
    "postgresql_connections",
    "sql_statements",
    "r2_operations",
    "official_reads",
    "odds_requests",
    "secret_writes",
    "purchases",
    "http_retries",
    "redirects_followed",
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            (
                str(key) != "secret_values_observed"
                and any(part in str(key).lower() for part in _FORBIDDEN_KEY_PARTS)
            )
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def load_guarded_report(path: Path, *, expected_main_sha: str) -> dict[str, Any]:
    if _HEX_40.fullmatch(expected_main_sha) is None:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_EXPECTED_SHA_INVALID")
    try:
        payload = path.read_bytes()
    except OSError:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_MISSING") from None
    if not payload or len(payload) > 65_536 or path.is_symlink() or b"\x00" in payload:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID")
    try:
        report = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID") from None
    if not isinstance(report, dict) or _contains_forbidden_key(report):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID")
    if report.get("verdict") == GO_VERDICT:
        return validate_neon_branch_identity_go_v2(report, main_sha=expected_main_sha)
    neon = report.get("neon")
    source = report.get("source")
    github = report.get("github_actions")
    effects = report.get("effects")
    source_present = isinstance(source, dict) and set(source) == _FAILURE_SOURCE_FIELDS
    github_present = isinstance(github, dict) and set(github) == _FAILURE_GITHUB_FIELDS
    neon_gets = effects.get("neon_gets") if isinstance(effects, dict) else None
    certainty = report.get("effect_counter_certainty")
    timeout_upper_bound = certainty == "UNKNOWN_OR_UPPER_BOUND"
    if (
        set(report)
        != {
            "schema_version",
            "observed_at",
            "verdict",
            "branch_inventory_failure_class",
            "effect_counter_certainty",
            "source",
            "github_actions",
            "neon",
            "effects",
            "secret_values_observed",
        }
        or report.get("schema_version") != REPORT_SCHEMA
        or report.get("verdict") != "NEON_BRANCH_IDENTITY_NO_GO_V2"
        or report.get("branch_inventory_failure_class") not in BRANCH_INVENTORY_FAILURE_CLASSES[1:]
        or certainty not in {"EXACT_DISPATCH_ACCOUNTING", "UNKNOWN_OR_UPPER_BOUND"}
        or report.get("secret_values_observed") is not False
        or not isinstance(source, dict)
        or not isinstance(github, dict)
        or not isinstance(effects, dict)
        or set(effects) != _FAILURE_EFFECT_FIELDS
        or type(neon_gets) is not int
        or not 0 <= neon_gets <= 25
        or (
            timeout_upper_bound
            and (
                neon_gets != 25
                or effects.get("neon_gets_exact") is not False
                or report.get("branch_inventory_failure_class") != "TRANSPORT_AMBIGUOUS"
            )
        )
        or (
            not timeout_upper_bound
            and effects.get("neon_gets_exact") is not True
        )
        or any(
            effects.get(field) != 0
            for field in _FAILURE_EFFECT_FIELDS - {"neon_gets", "neon_gets_exact"}
        )
        or (
            bool(source)
            and (
                not source_present
                or source.get("repository") != "dddur75/robin-stades-ng"
                or source.get("ref") != "refs/heads/main"
                or source.get("main_sha") != expected_main_sha
                or source.get("workflow_path")
                != ".github/workflows/chronos-neon-branch-identity-v2.yml"
                or not isinstance(source.get("run_id"), str)
                or re.fullmatch(r"[1-9][0-9]{0,17}", cast(str, source.get("run_id")))
                is None
                or source.get("run_attempt") != "1"
            )
        )
        or (
            bool(github)
            and (
                not github_present
                or any(type(github.get(field)) is not int or github.get(field, -1) < 0 for field in _FAILURE_GITHUB_FIELDS)
                or not source_present
                or github.get("current_run_excluded") != int(cast(str, source.get("run_id")))
            )
        )
        or (
            not timeout_upper_bound
            and neon_gets > 0
            and (not source_present or not github_present)
        )
        or not isinstance(neon, dict)
        or set(neon) != _FAILURE_NEON_FIELDS
        or neon.get("branch_inventory_failure_class")
        != report.get("branch_inventory_failure_class")
        or any(
            type(neon.get(field)) is not int or cast(int, neon.get(field)) < 0
            for field in {
                "branches_observed",
                "branch_pages_read",
                "branch_count_reads",
                "continuation_followed_count",
                "default_branch_count",
                "identity_intersection_size",
            }
        )
        or any(
            value is not None and (type(value) is not int or value < 0)
            for value in (neon.get("branch_count_before"), neon.get("branch_count_after"))
        )
        or any(
            type(neon.get(field)) is not bool
            for field in {
                "inventory_exhaustive",
                "terminal_by_cardinality",
                "continuation_required",
                "terminal_pagination_metadata_present",
                "dsn_branch_matches_default",
                "branch_endpoint_concordant",
            }
        )
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID")
    return report


def load_guarded_seal(
    path: Path,
    *,
    expected_main_sha: str,
    expected_identity_run_id: str,
) -> dict[str, Any]:
    """Accept one exact V2 seal success or a bounded sanitized failure receipt."""

    try:
        payload = path.read_bytes()
        report = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_REPORT_INVALID") from None
    if (
        not payload
        or len(payload) > 65_536
        or path.is_symlink()
        or not isinstance(report, dict)
        or _contains_forbidden_key(report)
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_REPORT_INVALID")
    if report.get("verdict") == "DURABLE_IDENTITY_SEAL_V2":
        return validate_identity_seal_v2(
            report,
            main_sha=expected_main_sha,
            expected_identity_run_id=expected_identity_run_id,
        )
    effects = report.get("effects")
    ordinary_failure = set(report) == {
        "schema_version",
        "verdict",
        "error_code",
        "failure_class",
        "effect_counter_certainty",
        "effects",
        "secret_values_observed",
    } and (
        report.get("schema_version") == "durable-identity-seal-failure-v2"
        and report.get("error_code") == "IDENTITY_SEAL_EXECUTION_FAILED"
        and report.get("failure_class") == "EXECUTION_FAILED"
        and report.get("effect_counter_certainty") == "EXACT_DISPATCH_ACCOUNTING"
    )
    supervised_failure = set(report) == {
        "schema_version",
        "verdict",
        "failure_class",
        "effect_counter_certainty",
        "effects",
        "secret_values_observed",
    } and (
        report.get("schema_version") == "durable-identity-seal-supervisor-failure-v2"
        and report.get("failure_class") == "TRANSPORT_AMBIGUOUS"
        and report.get("effect_counter_certainty") == "UNKNOWN_OR_UPPER_BOUND"
    )
    if (
        not (ordinary_failure or supervised_failure)
        or report.get("verdict") != "DURABLE_IDENTITY_SEAL_FAILED_V2"
        or report.get("secret_values_observed") is not False
        or not isinstance(effects, dict)
        or set(effects)
        != {
            "r2_puts",
            "r2_gets",
            "r2_objects_created",
            "r2_objects_created_exact",
            "automatic_retries",
        }
        or any(
            type(effects.get(field)) is not int
            for field in {"r2_puts", "r2_gets", "r2_objects_created", "automatic_retries"}
        )
        or not 0 <= effects.get("r2_puts", -1) <= 1
        or not 0 <= effects.get("r2_gets", -1) <= 1
        or not 0 <= effects.get("r2_objects_created", -1) <= 1
        or effects.get("automatic_retries") != 0
        or type(effects.get("r2_objects_created_exact")) is not bool
        or (
            supervised_failure
            and effects
            != {
                "r2_puts": 1,
                "r2_gets": 1,
                "r2_objects_created": 1,
                "r2_objects_created_exact": False,
                "automatic_retries": 0,
            }
        )
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_SEAL_V2_REPORT_INVALID")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--kind", choices=("identity", "seal"), default="identity")
    parser.add_argument("--expected-identity-run-id")
    parser.add_argument("--require-go", action="store_true")
    args = parser.parse_args()
    if args.kind == "seal":
        if not args.expected_identity_run_id:
            return 2
        report = load_guarded_seal(
            args.report,
            expected_main_sha=args.expected_main_sha,
            expected_identity_run_id=args.expected_identity_run_id,
        )
        expected_verdict = "DURABLE_IDENTITY_SEAL_V2"
    else:
        report = load_guarded_report(args.report, expected_main_sha=args.expected_main_sha)
        expected_verdict = GO_VERDICT
    if args.require_go and report.get("verdict") != expected_verdict:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
