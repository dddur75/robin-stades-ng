"""Recovery V2 stable-cardinality Neon branch inventory.

This module is deliberately transport-agnostic.  Its caller supplies the
bounded GET-only Neon client; the inventory exposes only sanitized counters and
booleans and never emits project, branch, endpoint, or cursor values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never, Protocol, cast

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    assert_production_safety_locks,
    validate_data_torrent_recovery_v2_authority,
    validate_neon_branch_identity_go_v2,
)
from scripts import chronos_neon_pure_readonly_preflight_v4 as base
from scripts.recovery_v2_supervision import (
    SUPERVISOR_CHILD_STUCK_EXIT,
    SUPERVISOR_EXPORT_EXIT,
    SUPERVISOR_TIMEOUT_EXIT,
    RecoveryV2SupervisionError,
    adopt_or_create_json_fallback,
    promote_validated_file,
    remaining_effect_timeout,
    run_child_once,
)

BRANCH_INVENTORY_FAILURE_CLASSES = (
    "NONE",
    "COUNT_CONTRACT_INVALID",
    "COUNT_DRIFT",
    "COUNT_OVERFLOW",
    "COUNT_NOT_REACHED_NO_NEXT",
    "NEXT_INVALID",
    "EMPTY_PAGE_BEFORE_COUNT",
    "PAGE_REPEAT",
    "CURSOR_CYCLE",
    "PAGE_LIMIT",
    "ITEM_LIMIT",
    "BRANCH_CONTRACT_INVALID",
    "DUPLICATE_BRANCH_ID",
    "PROJECT_MISMATCH",
    "DEFAULT_BRANCH_CONTRADICTION",
    "DSN_BRANCH_CONTRADICTION",
    "BRANCH_ENDPOINT_CONTRADICTION",
    "BUDGET_EXHAUSTED",
    "TRANSPORT_AMBIGUOUS",
)

_SAFE_ID = re.compile(r"^[a-z0-9-]{1,60}$")
REPORT_SCHEMA = "neon-branch-identity-go-v2"
GO_VERDICT = "NEON_BRANCH_IDENTITY_GO_V2"
WORKFLOW_FILE = "chronos-neon-branch-identity-v2.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate key")
        document[key] = value
    return document
V2_WITNESS_GET_RESERVE = 1 + 1 + 1 + base.MAX_BRANCH_PAGES + 1 + 1


class BoundedGetClient(Protocol):
    get_count: int

    def require_get_budget(self, required: int, gate: str) -> None: ...

    def get(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class BranchInventoryEvidence:
    branch_count_before: int | None = None
    branch_count_after: int | None = None
    branches_observed: int = 0
    branch_pages_read: int = 0
    branch_count_reads: int = 0
    inventory_exhaustive: bool = False
    terminal_by_cardinality: bool = False
    continuation_required: bool = False
    continuation_followed_count: int = 0
    terminal_pagination_metadata_present: bool = False
    default_branch_count: int = 0
    dsn_branch_matches_default: bool = False
    branch_endpoint_concordant: bool = False
    identity_intersection_size: int = 0
    branch_inventory_failure_class: str = "NONE"

    def sanitized(self) -> dict[str, object]:
        return {
            "branch_count_before": self.branch_count_before,
            "branch_count_after": self.branch_count_after,
            "branches_observed": self.branches_observed,
            "branch_pages_read": self.branch_pages_read,
            "branch_count_reads": self.branch_count_reads,
            "inventory_exhaustive": self.inventory_exhaustive,
            "terminal_by_cardinality": self.terminal_by_cardinality,
            "continuation_required": self.continuation_required,
            "continuation_followed_count": self.continuation_followed_count,
            "terminal_pagination_metadata_present": (self.terminal_pagination_metadata_present),
            "default_branch_count": self.default_branch_count,
            "dsn_branch_matches_default": self.dsn_branch_matches_default,
            "branch_endpoint_concordant": self.branch_endpoint_concordant,
            "identity_intersection_size": self.identity_intersection_size,
            "branch_inventory_failure_class": self.branch_inventory_failure_class,
        }


class BranchInventoryFailure(RuntimeError):
    """Sanitized terminal inventory failure."""

    def __init__(self, failure_class: str, evidence: BranchInventoryEvidence) -> None:
        if failure_class not in BRANCH_INVENTORY_FAILURE_CLASSES or failure_class == "NONE":
            raise ValueError("BRANCH_INVENTORY_FAILURE_CLASS_INVALID")
        evidence.branch_inventory_failure_class = failure_class
        self.failure_class = failure_class
        self.evidence = evidence
        super().__init__(failure_class)


@dataclass(slots=True)
class IdentityExecutionState:
    """Sanitized dispatch state retained even when identity observation fails."""

    source: dict[str, object] = field(default_factory=dict)
    github_actions: dict[str, int] = field(default_factory=dict)
    neon_gets: int = 0


def _fail(failure_class: str, evidence: BranchInventoryEvidence) -> Never:
    raise BranchInventoryFailure(failure_class, evidence)


def _require_budget(
    client: BoundedGetClient,
    required: int,
    evidence: BranchInventoryEvidence,
) -> None:
    try:
        client.require_get_budget(required, "recovery_v2_branch_inventory")
    except Exception:
        _fail("BUDGET_EXHAUSTED", evidence)


def _get(
    client: BoundedGetClient,
    path: str,
    evidence: BranchInventoryEvidence,
    *,
    query: Mapping[str, object] | None = None,
    before_dispatch: Callable[[], None] | None = None,
) -> dict[str, Any]:
    _require_budget(client, 1, evidence)
    if before_dispatch is not None:
        before_dispatch()
    try:
        return client.get(path, query=query)
    except BranchInventoryFailure:
        raise
    except Exception as error:
        if str(error).startswith("budget:"):
            _fail("BUDGET_EXHAUSTED", evidence)
        _fail("TRANSPORT_AMBIGUOUS", evidence)


def _read_count(
    client: BoundedGetClient,
    project_id: str,
    evidence: BranchInventoryEvidence,
    *,
    max_items: int,
) -> int:
    document = _get(
        client,
        f"/projects/{project_id}/branches/count",
        evidence,
        before_dispatch=lambda: setattr(
            evidence,
            "branch_count_reads",
            evidence.branch_count_reads + 1,
        ),
    )
    if set(document) != {"count"}:
        _fail("COUNT_CONTRACT_INVALID", evidence)
    value = document.get("count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail("COUNT_CONTRACT_INVALID", evidence)
    if value > max_items:
        _fail("ITEM_LIMIT", evidence)
    return value


def _validated_page(
    document: Mapping[str, Any],
    *,
    project_id: str,
    evidence: BranchInventoryEvidence,
) -> list[dict[str, Any]]:
    if not set(document) <= {"branches", "annotations", "pagination"}:
        _fail("NEXT_INVALID", evidence)
    value = document.get("branches")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _fail("BRANCH_CONTRACT_INVALID", evidence)
    branches = cast(list[dict[str, Any]], value)
    for branch in branches:
        branch_id = branch.get("id")
        if (
            not isinstance(branch_id, str)
            or _SAFE_ID.fullmatch(branch_id) is None
            or not isinstance(branch.get("default"), bool)
            or not isinstance(branch.get("current_state"), str)
            or not branch.get("current_state")
            or branch.get("pending_state") is not None
        ):
            _fail("BRANCH_CONTRACT_INVALID", evidence)
        if branch.get("project_id") != project_id:
            _fail("PROJECT_MISMATCH", evidence)
        parent = branch.get("parent_id")
        if parent is not None and (
            not isinstance(parent, str) or _SAFE_ID.fullmatch(parent) is None
        ):
            _fail("BRANCH_CONTRACT_INVALID", evidence)
    return branches


def _next_cursor(
    document: Mapping[str, Any],
    evidence: BranchInventoryEvidence,
) -> str:
    if "pagination" not in document:
        _fail("COUNT_NOT_REACHED_NO_NEXT", evidence)
    pagination = document.get("pagination")
    if not isinstance(pagination, dict):
        _fail("NEXT_INVALID", evidence)
    if "next" not in pagination or pagination.get("next") is None:
        _fail("COUNT_NOT_REACHED_NO_NEXT", evidence)
    cursor = pagination.get("next")
    if not isinstance(cursor, str) or not cursor:
        _fail("NEXT_INVALID", evidence)
    return cursor


def stable_branch_inventory(
    client: BoundedGetClient,
    project_id: str,
    *,
    dsn_branch_id: str,
    endpoint_branch_id: str,
    max_pages: int = 3,
    max_items: int = 30_000,
    page_limit: int = 10_000,
    reserve_after: int = 0,
) -> tuple[list[dict[str, Any]], BranchInventoryEvidence]:
    """Prove count-before == exhaustive inventory == count-after.

    Cardinality is the only successful terminal signal.  Pagination metadata on
    the cardinality-completing page is recorded as present or absent but is
    never interpreted.
    """

    evidence = BranchInventoryEvidence()
    if (
        _SAFE_ID.fullmatch(project_id) is None
        or _SAFE_ID.fullmatch(dsn_branch_id) is None
        or _SAFE_ID.fullmatch(endpoint_branch_id) is None
        or max_pages < 1
        or max_items < 1
        or page_limit < 1
        or reserve_after < 0
    ):
        _fail("BRANCH_CONTRACT_INVALID", evidence)
    _require_budget(client, 2 + max_pages + reserve_after, evidence)
    count_before = _read_count(client, project_id, evidence, max_items=max_items)
    evidence.branch_count_before = count_before

    branches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pages: set[tuple[str, ...]] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    while len(branches) < count_before:
        if evidence.branch_pages_read >= max_pages:
            _fail("PAGE_LIMIT", evidence)
        query: dict[str, object] = {
            "limit": page_limit,
            "sort_by": "updated_at",
            "sort_order": "asc",
            "include_deleted": "false",
        }
        if cursor is not None:
            query["cursor"] = cursor
        document = _get(
            client,
            f"/projects/{project_id}/branches",
            evidence,
            query=query,
            before_dispatch=lambda: setattr(
                evidence,
                "branch_pages_read",
                evidence.branch_pages_read + 1,
            ),
        )
        page = _validated_page(document, project_id=project_id, evidence=evidence)
        if not page:
            _fail("EMPTY_PAGE_BEFORE_COUNT", evidence)
        page_ids = tuple(cast(str, branch["id"]) for branch in page)
        if page_ids in seen_pages:
            _fail("PAGE_REPEAT", evidence)
        seen_pages.add(page_ids)
        for branch, branch_id in zip(page, page_ids, strict=True):
            if branch_id in seen_ids:
                _fail("DUPLICATE_BRANCH_ID", evidence)
            seen_ids.add(branch_id)
            branches.append(branch)
        evidence.branches_observed = len(branches)
        if len(branches) > max_items:
            _fail("ITEM_LIMIT", evidence)
        if len(branches) > count_before:
            _fail("COUNT_OVERFLOW", evidence)
        if len(branches) == count_before:
            evidence.terminal_by_cardinality = True
            evidence.terminal_pagination_metadata_present = "pagination" in document
            break
        evidence.continuation_required = True
        next_cursor = _next_cursor(document, evidence)
        if next_cursor in seen_cursors:
            _fail("CURSOR_CYCLE", evidence)
        if evidence.branch_pages_read >= max_pages:
            _fail("PAGE_LIMIT", evidence)
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        evidence.continuation_followed_count += 1

    count_after = _read_count(client, project_id, evidence, max_items=max_items)
    evidence.branch_count_after = count_after
    if count_before != count_after:
        _fail("COUNT_DRIFT", evidence)
    if len(branches) > count_after:
        _fail("COUNT_OVERFLOW", evidence)
    if len(branches) != count_after:
        _fail("COUNT_DRIFT", evidence)

    defaults = [cast(str, branch["id"]) for branch in branches if branch["default"] is True]
    evidence.default_branch_count = len(defaults)
    if len(defaults) != 1:
        _fail("DEFAULT_BRANCH_CONTRADICTION", evidence)
    default_id = defaults[0]
    evidence.dsn_branch_matches_default = dsn_branch_id == default_id
    if not evidence.dsn_branch_matches_default:
        _fail("DSN_BRANCH_CONTRADICTION", evidence)
    evidence.branch_endpoint_concordant = endpoint_branch_id == default_id
    if not evidence.branch_endpoint_concordant:
        _fail("BRANCH_ENDPOINT_CONTRADICTION", evidence)
    evidence.identity_intersection_size = len({default_id} & {dsn_branch_id} & {endpoint_branch_id})
    if evidence.identity_intersection_size != 1:
        _fail("BRANCH_ENDPOINT_CONTRADICTION", evidence)
    evidence.inventory_exhaustive = True
    return branches, evidence


def _v2_authority() -> object:
    return validate_data_torrent_recovery_v2_authority(scale_stage="E2")


def _required_context(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ChronosProductionError(f"CHRONOS_IDENTITY_GO_V2_{name}_MISSING")
    return value


def run_identity(*, execution_state: IdentityExecutionState | None = None) -> dict[str, object]:
    """Execute the single bounded Neon-only Recovery identity observation."""

    state = execution_state if execution_state is not None else IdentityExecutionState()
    assert_production_safety_locks(os.environ)
    _v2_authority()
    repository = _required_context("GITHUB_REPOSITORY")
    git_ref = _required_context("GITHUB_REF")
    main_sha = _required_context("GITHUB_SHA")
    raw_run_id = _required_context("GITHUB_RUN_ID")
    run_attempt = _required_context("GITHUB_RUN_ATTEMPT")
    if (
        repository != EXPECTED_REPOSITORY
        or git_ref != EXPECTED_REF
        or re.fullmatch(r"[0-9a-f]{40}", main_sha) is None
        or re.fullmatch(r"[1-9][0-9]{0,17}", raw_run_id) is None
        or run_attempt != "1"
    ):
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_SOURCE_INVALID")
    run_id = int(raw_run_id)
    state.source = {
        "repository": repository,
        "ref": git_ref,
        "main_sha": main_sha,
        "workflow_path": WORKFLOW_PATH,
        "run_id": str(run_id),
        "run_attempt": run_attempt,
    }
    if os.getenv("NEON_PROJECT_ID", "").strip():
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_PROJECT_OVERRIDE_FORBIDDEN")
    authority_dispatches = base._github_authority_window_dispatch_count(
        repository,
        run_id,
        main_sha,
        workflow_file=WORKFLOW_FILE,
        not_before=DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        authority_validator=_v2_authority,
    )
    queued, in_progress, dispatch_count = base._github_actions_state(
        repository,
        run_id,
        main_sha,
        workflow_file=WORKFLOW_FILE,
        authority_validator=_v2_authority,
    )
    state.github_actions = {
        "queued": queued,
        "in_progress": in_progress,
        "current_run_excluded": run_id,
        "exact_main_dispatch_count": dispatch_count,
        "authority_window_dispatch_count": authority_dispatches,
    }
    if queued != 0 or in_progress != 0 or dispatch_count != 1 or authority_dispatches != 1:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_DISPATCH_INVALID")
    api_key = _required_context("NEON_API_KEY")
    database_url = _required_context("NEON_BOOTSTRAP_DATABASE_URL")
    _, target = base._validated_psycopg_url(database_url)
    base._reject_libpq_environment()
    client = base.NeonReadOnlyClient(
        api_key,
        authority_validator=_v2_authority,
        maximum_gets=25,
    )
    stable_evidence: BranchInventoryEvidence | None = None

    def stable_loader(
        bounded_client: BoundedGetClient,
        project_id: str,
        audit: base.IdentityAudit,
        reserve_after: int,
        dsn_branch_id: str,
        endpoint_branch_id: str,
    ) -> list[dict[str, Any]]:
        nonlocal stable_evidence
        branches, evidence = stable_branch_inventory(
            bounded_client,
            project_id,
            dsn_branch_id=dsn_branch_id,
            endpoint_branch_id=endpoint_branch_id,
            max_pages=base.MAX_BRANCH_PAGES,
            max_items=base.MAX_BRANCH_ITEMS,
            page_limit=base.MAX_BRANCH_PAGE,
            reserve_after=reserve_after,
        )
        stable_evidence = evidence
        audit.branch_pages_read += evidence.branch_pages_read
        audit.cursor_continuation_requested = evidence.continuation_required
        audit.branch_counts_by_project[project_id] = cast(int, evidence.branch_count_after)
        return branches

    try:
        neon = base._resolve_neon_identity(
            client,
            target,
            allow_idle=True,
            branch_inventory=stable_loader,
            witness_get_reserve=V2_WITNESS_GET_RESERVE,
        )
        base.require_neon_recovery_feasibility(neon)
    except BranchInventoryFailure:
        raise
    except base.PreflightNoGo as error:
        raise ChronosProductionError(
            f"CHRONOS_IDENTITY_GO_V2_NO_GO:{error.reason}:{error.gate}"
        ) from None
    finally:
        state.neon_gets = client.get_count
    if stable_evidence is None:
        raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_INVENTORY_MISSING")
    sanitized_neon = base._sanitized_neon(neon)
    sanitized_neon.update(stable_evidence.sanitized())
    effects = {
        "neon_gets": client.get_count,
        "neon_post": 0,
        "neon_patch": 0,
        "neon_delete": 0,
        "compute_wakes": 0,
        "postgresql_connections": 0,
        "sql_statements": 0,
        "r2_operations": 0,
        "official_reads": 0,
        "odds_requests": 0,
        "secret_writes": 0,  # nosec B105 - numeric audit counter, never a credential.
        "purchases": 0,
        "http_retries": 0,
        "redirects_followed": 0,
    }
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": repository,
            "ref": git_ref,
            "main_sha": main_sha,
            "workflow_path": WORKFLOW_PATH,
            "run_id": str(run_id),
            "run_attempt": run_attempt,
        },
        "verdict": GO_VERDICT,
        "effect_counter_certainty": "OBSERVED",
        "github_actions": {
            "queued": queued,
            "in_progress": in_progress,
            "current_run_excluded": run_id,
            "exact_main_dispatch_count": dispatch_count,
            "authority_window_dispatch_count": authority_dispatches,
        },
        "neon": sanitized_neon,
        "effects": effects,
    }
    return validate_neon_branch_identity_go_v2(report, main_sha=main_sha)


def _failure_report(
    error: Exception,
    execution_state: IdentityExecutionState,
    *,
    conservative_timeout: bool = False,
    observed_at: str | None = None,
) -> dict[str, object]:
    if isinstance(error, BranchInventoryFailure):
        failure_class = error.failure_class
        neon = error.evidence.sanitized()
    else:
        failure_class = "TRANSPORT_AMBIGUOUS"
        neon = BranchInventoryEvidence(branch_inventory_failure_class=failure_class).sanitized()
    zero_effects = {
        "neon_gets": 25 if conservative_timeout else execution_state.neon_gets,
        "neon_gets_exact": not conservative_timeout,
        "neon_post": 0,
        "neon_patch": 0,
        "neon_delete": 0,
        "compute_wakes": 0,
        "postgresql_connections": 0,
        "sql_statements": 0,
        "r2_operations": 0,
        "official_reads": 0,
        "odds_requests": 0,
        "secret_writes": 0,  # nosec B105 - numeric audit counter.
        "purchases": 0,
        "http_retries": 0,
        "redirects_followed": 0,
    }
    return {
        "schema_version": REPORT_SCHEMA,
        "observed_at": observed_at
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "verdict": "NEON_BRANCH_IDENTITY_NO_GO_V2",
        "branch_inventory_failure_class": failure_class,
        "effect_counter_certainty": (
            "UNKNOWN_OR_UPPER_BOUND"
            if conservative_timeout
            else "EXACT_DISPATCH_ACCOUNTING"
        ),
        "source": execution_state.source,
        "github_actions": execution_state.github_actions,
        "neon": neon,
        "effects": zero_effects,
        "secret_values_observed": False,  # nosec B105 - boolean audit field.
    }


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _supervised_identity(output: Path) -> int:
    """Run the observer below the job deadline and always leave sanitized evidence."""

    state = IdentityExecutionState()
    main_sha = os.getenv("GITHUB_SHA", "")
    fallback_observed_at = os.getenv("RECOVERY_V2_FALLBACK_OBSERVED_AT", "") or None
    if fallback_observed_at is not None:
        try:
            parsed_fallback_time = datetime.fromisoformat(
                fallback_observed_at.replace("Z", "+00:00")
            )
        except ValueError:
            return SUPERVISOR_EXPORT_EXIT
        if (
            not fallback_observed_at.endswith("Z")
            or parsed_fallback_time.tzinfo is None
            or parsed_fallback_time.utcoffset() != UTC.utcoffset(parsed_fallback_time)
            or parsed_fallback_time.isoformat(timespec="seconds").replace("+00:00", "Z")
            != fallback_observed_at
        ):
            return SUPERVISOR_EXPORT_EXIT
    fallback_sha256 = adopt_or_create_json_fallback(
        output,
        _failure_report(
            RuntimeError("TRANSPORT_AMBIGUOUS"),
            state,
            conservative_timeout=True,
            observed_at=fallback_observed_at,
        ),
    )
    with tempfile.TemporaryDirectory(
        prefix=".recovery-v2-identity-",
        dir=output.parent,
    ) as temporary_name:
        child_output = Path(temporary_name) / "identity.json"
        timeout_seconds = remaining_effect_timeout(110)
        if timeout_seconds == 0:
            return SUPERVISOR_TIMEOUT_EXIT
        return_code = run_child_once(
            (
                sys.executable,
                "-m",
                "scripts.chronos_neon_branch_identity_v2",
                "--output",
                str(child_output),
            ),
            timeout_seconds=timeout_seconds,
        )
        if return_code in {
            SUPERVISOR_TIMEOUT_EXIT,
            SUPERVISOR_EXPORT_EXIT,
            SUPERVISOR_CHILD_STUCK_EXIT,
        }:
            return return_code
        if return_code != 0:
            return return_code

        def validate_candidate(path: Path) -> dict[str, Any]:
            try:
                payload = path.read_bytes()
                document = json.loads(
                    payload,
                    object_pairs_hook=lambda pairs: _unique_json_object(pairs),
                    parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID") from None
            if not payload or len(payload) > 65_536 or b"\x00" in payload or not isinstance(
                document, dict
            ):
                raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID")
            validated = validate_neon_branch_identity_go_v2(document, main_sha=main_sha)
            if validated.get("verdict") != GO_VERDICT:
                raise ChronosProductionError("CHRONOS_IDENTITY_GO_V2_REPORT_INVALID")
            return validated

        try:
            promote_validated_file(
                child_output,
                output,
                expected_fallback_sha256=fallback_sha256,
                validator=validate_candidate,
            )
        except (ChronosProductionError, RecoveryV2SupervisionError):
            return SUPERVISOR_EXPORT_EXIT
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supervise", action="store_true")
    args = parser.parse_args()
    if args.supervise:
        return _supervised_identity(args.output)
    execution_state = IdentityExecutionState()
    try:
        report = run_identity(execution_state=execution_state)
        exit_code = 0
    except Exception as error:
        report = _failure_report(error, execution_state)
        exit_code = 2
    _write_report(args.output, report)
    return exit_code


__all__ = [
    "BRANCH_INVENTORY_FAILURE_CLASSES",
    "BranchInventoryEvidence",
    "BranchInventoryFailure",
    "stable_branch_inventory",
]


if __name__ == "__main__":
    raise SystemExit(main())
