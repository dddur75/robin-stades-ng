from __future__ import annotations

import json
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.chronos_neon_branch_identity_v2 as identity
import scripts.chronos_neon_pure_readonly_preflight_v4 as base
from robin.chronos_production import (
    PRODUCTION_SAFETY_LOCKS,
    ChronosProductionError,
    validate_neon_branch_identity_go_v2,
)
from scripts.chronos_live_path_artifact_guard_v2 import load_guarded_report
from scripts.chronos_neon_branch_identity_v2 import (
    BRANCH_INVENTORY_FAILURE_CLASSES,
    BranchInventoryFailure,
    stable_branch_inventory,
)
from scripts.chronos_neon_pure_readonly_preflight_v4 import NeonReadOnlyClient, PreflightNoGo

PROJECT_ID = "synthetic-project"
DEFAULT_ID = "branch-default"
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "chronos-neon-branch-identity-v2.yml"


@pytest.fixture(autouse=True)
def _exact_safety_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PRODUCTION_SAFETY_LOCKS.items():
        monkeypatch.setenv(name, value)


class _GitHubResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        assert chunk_size == 64 * 1024
        return [b"{}"]

    def close(self) -> None:
        return None


class _GitHubSession:
    calls = 0

    def __init__(self) -> None:
        self.trust_env = True

    def get(self, *_args: object, **_kwargs: object) -> _GitHubResponse:
        type(self).calls += 1
        return _GitHubResponse()

    def close(self) -> None:
        return None


def test_v2_github_read_uses_injected_authority_and_fails_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token")
    monkeypatch.setattr(base.requests, "Session", _GitHubSession)
    _GitHubSession.calls = 0
    v2_calls = 0

    def v2_open() -> None:
        nonlocal v2_calls
        v2_calls += 1

    assert base._github_get("/synthetic", authority_validator=v2_open) == {}
    assert v2_calls == _GitHubSession.calls == 1

    def v2_closed() -> None:
        raise ChronosProductionError("V2_CLOSED")

    with pytest.raises(PreflightNoGo) as caught:
        base._github_get("/must-not-dispatch", authority_validator=v2_closed)
    assert caught.value.gate == "mission_authority_inactive"
    assert _GitHubSession.calls == 1


def _branch(
    branch_id: str,
    *,
    default: bool = False,
    project_id: str = PROJECT_ID,
) -> dict[str, object]:
    return {
        "id": branch_id,
        "project_id": project_id,
        "name": branch_id,
        "default": default,
        "current_state": "ready",
        "pending_state": None,
        "parent_id": None if default else DEFAULT_ID,
    }


def _page(
    branches: list[dict[str, object]],
    *,
    next_cursor: object = None,
    include_pagination: bool = True,
) -> dict[str, object]:
    document: dict[str, object] = {"branches": branches, "annotations": {}}
    if include_pagination:
        document["pagination"] = {
            "next": next_cursor,
            "previous": "opaque-previous-is-non-authoritative",
            "sort_by": "updated_at",
            "sort_order": "asc",
        }
    return document


class _ScriptedClient:
    def __init__(
        self,
        documents: list[dict[str, Any] | BaseException],
        *,
        maximum_gets: int = 25,
    ) -> None:
        self.documents = list(documents)
        self.maximum_gets = maximum_gets
        self.get_count = 0
        self.network_calls = 0
        self.paths: list[tuple[str, Mapping[str, object] | None]] = []

    def require_get_budget(self, required: int, gate: str) -> None:
        if required < 1 or self.get_count + required > self.maximum_gets:
            raise RuntimeError(f"budget:{gate}")

    def get(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if self.get_count >= self.maximum_gets:
            raise RuntimeError("budget:network-boundary")
        self.get_count += 1
        self.network_calls += 1
        self.paths.append((path, query))
        if not self.documents:
            raise AssertionError("unexpected GET")
        value = self.documents.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _run(
    documents: list[dict[str, Any] | BaseException],
    *,
    dsn_branch_id: str = DEFAULT_ID,
    endpoint_branch_id: str = DEFAULT_ID,
    maximum_gets: int = 25,
    max_pages: int = 3,
    max_items: int = 30_000,
) -> tuple[list[dict[str, Any]], dict[str, object], _ScriptedClient]:
    client = _ScriptedClient(documents, maximum_gets=maximum_gets)
    branches, evidence = stable_branch_inventory(
        client,
        PROJECT_ID,
        dsn_branch_id=dsn_branch_id,
        endpoint_branch_id=endpoint_branch_id,
        max_pages=max_pages,
        max_items=max_items,
    )
    return branches, evidence.sanitized(), client


def test_single_page_terminates_by_cardinality_without_pagination() -> None:
    branches, evidence, client = _run(
        [
            {"count": 1},
            _page([_branch(DEFAULT_ID, default=True)], include_pagination=False),
            {"count": 1},
        ]
    )
    assert [branch["id"] for branch in branches] == [DEFAULT_ID]
    assert client.get_count == 3
    assert client.documents == []
    assert evidence == {
        "branch_count_before": 1,
        "branch_count_after": 1,
        "branches_observed": 1,
        "branch_pages_read": 1,
        "branch_count_reads": 2,
        "inventory_exhaustive": True,
        "terminal_by_cardinality": True,
        "continuation_required": False,
        "continuation_followed_count": 0,
        "terminal_pagination_metadata_present": False,
        "default_branch_count": 1,
        "dsn_branch_matches_default": True,
        "branch_endpoint_concordant": True,
        "identity_intersection_size": 1,
        "branch_inventory_failure_class": "NONE",
    }


def test_terminal_pagination_metadata_is_non_authoritative() -> None:
    terminal = _page([_branch(DEFAULT_ID, default=True)])
    terminal["pagination"] = {"unexpected": {"next": ["not", "a", "cursor"]}}
    _, evidence, client = _run([{"count": 1}, terminal, {"count": 1}])
    assert client.get_count == 3
    assert evidence["terminal_by_cardinality"] is True
    assert evidence["terminal_pagination_metadata_present"] is True


def test_multi_page_inventory_follows_only_required_continuations() -> None:
    branches, evidence, client = _run(
        [
            {"count": 3},
            _page(
                [_branch(DEFAULT_ID, default=True), _branch("branch-second")],
                next_cursor="cursor-1",
            ),
            _page([_branch("branch-third")], next_cursor="ignored-terminal"),
            {"count": 3},
        ]
    )
    assert {branch["id"] for branch in branches} == {
        DEFAULT_ID,
        "branch-second",
        "branch-third",
    }
    assert evidence["branch_pages_read"] == 2
    assert evidence["continuation_required"] is True
    assert evidence["continuation_followed_count"] == 1
    assert client.get_count == 4
    assert client.paths[2][1] is not None
    assert client.paths[2][1]["cursor"] == "cursor-1"


@pytest.mark.parametrize(
    ("documents", "failure_class", "kwargs"),
    [
        ([{"count": True}], "COUNT_CONTRACT_INVALID", {}),
        (
            [
                {"count": 1},
                _page([_branch(DEFAULT_ID, default=True)]),
                {"count": 2},
            ],
            "COUNT_DRIFT",
            {},
        ),
        (
            [
                {"count": 1},
                _page([_branch(DEFAULT_ID, default=True), _branch("branch-extra")]),
            ],
            "COUNT_OVERFLOW",
            {},
        ),
        (
            [{"count": 2}, _page([_branch(DEFAULT_ID, default=True)], next_cursor=None)],
            "COUNT_NOT_REACHED_NO_NEXT",
            {},
        ),
        (
            [{"count": 2}, _page([_branch(DEFAULT_ID, default=True)], next_cursor=7)],
            "NEXT_INVALID",
            {},
        ),
        ([{"count": 1}, _page([], next_cursor="cursor")], "EMPTY_PAGE_BEFORE_COUNT", {}),
        (
            [
                {"count": 3},
                _page([_branch(DEFAULT_ID, default=True)], next_cursor="cursor-1"),
                _page([_branch(DEFAULT_ID, default=True)], next_cursor="cursor-2"),
            ],
            "PAGE_REPEAT",
            {},
        ),
        (
            [
                {"count": 3},
                _page([_branch(DEFAULT_ID, default=True)], next_cursor="cursor-1"),
                _page([_branch("branch-second")], next_cursor="cursor-1"),
            ],
            "CURSOR_CYCLE",
            {},
        ),
        (
            [
                {"count": 4},
                _page([_branch(DEFAULT_ID, default=True)], next_cursor="cursor-1"),
                _page([_branch("branch-second")], next_cursor="cursor-2"),
                _page([_branch("branch-third")], next_cursor="cursor-3"),
            ],
            "PAGE_LIMIT",
            {"max_pages": 3},
        ),
        (
            [
                {"count": 2},
                _page(
                    [_branch(DEFAULT_ID, default=True), _branch("branch-second")],
                    next_cursor="cursor",
                ),
            ],
            "ITEM_LIMIT",
            {"max_items": 1},
        ),
        (
            [{"count": 1}, _page([{"project_id": PROJECT_ID, "default": True}])],
            "BRANCH_CONTRACT_INVALID",
            {},
        ),
        (
            [
                {"count": 2},
                _page(
                    [_branch(DEFAULT_ID, default=True), _branch(DEFAULT_ID)],
                    next_cursor="cursor",
                ),
            ],
            "DUPLICATE_BRANCH_ID",
            {},
        ),
        (
            [
                {"count": 1},
                _page([_branch(DEFAULT_ID, default=True, project_id="other-project")]),
            ],
            "PROJECT_MISMATCH",
            {},
        ),
        (
            [
                {"count": 2},
                _page(
                    [
                        _branch(DEFAULT_ID, default=True),
                        _branch("branch-second", default=True),
                    ]
                ),
                {"count": 2},
            ],
            "DEFAULT_BRANCH_CONTRADICTION",
            {},
        ),
        (
            [
                {"count": 1},
                _page([_branch(DEFAULT_ID, default=True)]),
                {"count": 1},
            ],
            "DSN_BRANCH_CONTRADICTION",
            {"dsn_branch_id": "branch-other"},
        ),
        (
            [
                {"count": 1},
                _page([_branch(DEFAULT_ID, default=True)]),
                {"count": 1},
            ],
            "BRANCH_ENDPOINT_CONTRADICTION",
            {"endpoint_branch_id": "branch-other"},
        ),
        ([{"count": 1}], "BUDGET_EXHAUSTED", {"maximum_gets": 4}),
        ([RuntimeError("synthetic transport")], "TRANSPORT_AMBIGUOUS", {}),
    ],
)
def test_failure_taxonomy_is_exact_and_fail_closed(
    documents: list[dict[str, Any] | BaseException],
    failure_class: str,
    kwargs: dict[str, object],
) -> None:
    client = _ScriptedClient(
        documents,
        maximum_gets=int(kwargs.get("maximum_gets", 25)),
    )
    with pytest.raises(BranchInventoryFailure) as caught:
        stable_branch_inventory(
            client,
            PROJECT_ID,
            dsn_branch_id=str(kwargs.get("dsn_branch_id", DEFAULT_ID)),
            endpoint_branch_id=str(kwargs.get("endpoint_branch_id", DEFAULT_ID)),
            max_pages=int(kwargs.get("max_pages", 3)),
            max_items=int(kwargs.get("max_items", 30_000)),
        )
    assert caught.value.failure_class == failure_class
    assert caught.value.evidence.branch_inventory_failure_class == failure_class
    assert client.get_count <= client.maximum_gets
    if failure_class == "BUDGET_EXHAUSTED":
        assert client.network_calls == 0


def test_failure_enum_matches_the_owner_contract() -> None:
    assert BRANCH_INVENTORY_FAILURE_CLASSES == (
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


def test_deterministic_fuzz_covers_exactly_ten_thousand_valid_partitions() -> None:
    rng = random.Random(20260830)
    for case_index in range(10_000):
        count = 1 + rng.randrange(12)
        ids = [DEFAULT_ID, *(f"branch-{case_index}-{index}" for index in range(1, count))]
        rng.shuffle(ids)
        cut_count = rng.randrange(1, min(3, count) + 1)
        cuts = sorted(rng.sample(range(1, count), cut_count - 1)) if count > 1 else []
        partitions: list[list[str]] = []
        start = 0
        for end in [*cuts, count]:
            partitions.append(ids[start:end])
            start = end
        documents: list[dict[str, Any] | BaseException] = [{"count": count}]
        for page_index, partition in enumerate(partitions):
            rows = [_branch(branch_id, default=branch_id == DEFAULT_ID) for branch_id in partition]
            if page_index + 1 == len(partitions):
                terminal = _page(rows)
                terminal["pagination"] = {
                    "terminal_noise": rng.choice([None, False, 0, "", [], {"next": 7}])
                }
                documents.append(terminal)
            else:
                documents.append(_page(rows, next_cursor=f"cursor-{case_index}-{page_index}"))
        documents.append({"count": count})
        branches, evidence, client = _run(documents)
        assert {str(branch["id"]) for branch in branches} == set(ids)
        assert evidence["branch_count_before"] == count
        assert evidence["branch_count_after"] == count
        assert evidence["branch_count_reads"] == 2
        assert evidence["inventory_exhaustive"] is True
        assert evidence["branch_inventory_failure_class"] == "NONE"
        assert client.get_count == 2 + len(partitions)
        assert client.get_count <= 25


def _valid_go_report() -> dict[str, object]:
    neon_fields = {
        "identity_path": "POSITIVE_ENDPOINT_WITNESS",
        "identity_proof_mode": "POSITIVE_OWNERSHIP",
        "project_identity_verdict": "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN",
        "neon_project_identity_verdict": "NEON_PROJECT_IDENTITY_PROVEN",
        "project_inventory_exhaustive": True,
        "project_pages_read": 2,
        "projects_observed": 1,
        "endpoint_projects_inspected": 1,
        "endpoint_inventory_reads": 1,
        "endpoint_detail_reads": 1,
        "project_detail_reads": 1,
        "branch_pages_read": 1,
        "branch_endpoint_reads": 1,
        "cursor_continuation_requested": False,
        "cursor_cycle_encountered": False,
        "positive_witness_checks": [
            "EXACT_DSN_HOST_MATCH",
            "PROJECT_SCOPED_ENDPOINT_INVENTORY",
            "ENDPOINT_DETAIL_CONCORDANT",
            "PROJECT_DETAIL_CONCORDANT",
            "DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT",
            "BRANCH_ENDPOINT_CONCORDANT",
        ],
        "project_id_sha256": "1" * 64,
        "project_name_sha256": "2" * 64,
        "region": "3" * 64,
        "production_branch_id_sha256": "4" * 64,
        "production_branch_name_sha256": "5" * 64,
        "production_branch_default": True,
        "production_branch_parent_id_sha256": None,
        "recovery_parent_id_sha256": "4" * 64,
        "endpoint_id_sha256": "6" * 64,
        "endpoint_host_sha256": "7" * 64,
        "endpoint_state": "idle",
        "suspend_timeout_seconds": 300,
        "branch_state": "ready",
        "owner_id_sha256": "8" * 64,
        "owner_branch_count": 1,
        "branch_limit": 10,
        "branch_capacity_proven": True,
        "bill_free_branch_capacity_proven": True,
        "owner_scope_verdict": "ORGANIZATION_WIDE_API_KEY",
        "branch_count_reads": 2,
        "subscription_type": "free_v3",
        "billing_plan": "free",
        "target_project_branch_count": 1,
        "history_retention_seconds": 86_400,
        "postgresql_major": 16,
        "autoscaling_limit_max_cu": 1.0,
        "api_get_count": 10,
        "api_post_count": 0,
        "api_put_count": 0,
        "api_patch_count": 0,
        "api_delete_count": 0,
        "branch_count_before": 1,
        "branch_count_after": 1,
        "branches_observed": 1,
        "inventory_exhaustive": True,
        "terminal_by_cardinality": True,
        "continuation_required": False,
        "continuation_followed_count": 0,
        "terminal_pagination_metadata_present": True,
        "default_branch_count": 1,
        "dsn_branch_matches_default": True,
        "branch_endpoint_concordant": True,
        "identity_intersection_size": 1,
        "branch_inventory_failure_class": "NONE",
    }
    return {
        "schema_version": "neon-branch-identity-go-v2",
        "observed_at": "2026-08-30T13:00:00Z",
        "source": {
            "repository": "dddur75/robin-stades-ng",
            "ref": "refs/heads/main",
            "main_sha": "a" * 40,
            "workflow_path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
            "run_id": "123",
            "run_attempt": "1",
        },
        "verdict": "NEON_BRANCH_IDENTITY_GO_V2",
        "effect_counter_certainty": "OBSERVED",
        "github_actions": {
            "queued": 0,
            "in_progress": 0,
            "current_run_excluded": 123,
            "exact_main_dispatch_count": 1,
            "authority_window_dispatch_count": 1,
        },
        "neon": neon_fields,
        "effects": {
            "neon_gets": 10,
            "neon_post": 0,
            "neon_patch": 0,
            "neon_delete": 0,
            "compute_wakes": 0,
            "postgresql_connections": 0,
            "sql_statements": 0,
            "r2_operations": 0,
            "official_reads": 0,
            "odds_requests": 0,
            "secret_writes": 0,
            "purchases": 0,
            "http_retries": 0,
            "redirects_followed": 0,
        },
    }


def test_go_guard_accepts_only_the_exact_v2_semantics() -> None:
    report = _valid_go_report()
    assert validate_neon_branch_identity_go_v2(report, main_sha="a" * 40) == report
    for mutation in (
        {"schema_version": "chronos-neon-controlled-idle-wake-readonly-v1"},
        {"verdict": "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"},
        {"unknown": True},
    ):
        candidate = dict(report)
        candidate.update(mutation)
        with pytest.raises(ChronosProductionError, match="IDENTITY_GO_V2_INVALID"):
            validate_neon_branch_identity_go_v2(candidate, main_sha="a" * 40)


def test_go_guard_rejects_counter_and_identity_contradictions() -> None:
    for mutate in (
        lambda report: report["effects"].update(neon_gets=11),  # type: ignore[union-attr]
        lambda report: report["neon"].update(branch_count_after=2),  # type: ignore[union-attr]
        lambda report: report["neon"].update(dsn_branch_matches_default=False),  # type: ignore[union-attr]
        lambda report: report["neon"].update(project_pages_read=-1),  # type: ignore[union-attr]
        lambda report: report["neon"].update(continuation_followed_count=-1),  # type: ignore[union-attr]
        lambda report: report["neon"].update(recovery_parent_id_sha256="9" * 64),  # type: ignore[union-attr]
        lambda report: report["neon"].update(positive_witness_checks=["Bearer secret"]),  # type: ignore[union-attr]
    ):
        report = _valid_go_report()
        mutate(report)
        with pytest.raises(ChronosProductionError, match="IDENTITY_GO_V2_INVALID"):
            validate_neon_branch_identity_go_v2(report, main_sha="a" * 40)


def test_failure_guard_rejects_extra_or_sensitive_fields(tmp_path: Path) -> None:
    for neon in (
        {"branch_inventory_failure_class": "COUNT_DRIFT", "host": "secret"},
        {"branch_inventory_failure_class": "COUNT_DRIFT", "payload": {"branch_id": "raw"}},
    ):
        path = tmp_path / f"failure-{len(list(tmp_path.iterdir()))}.json"
        path.write_text(
            __import__("json").dumps(
                {
                    "schema_version": "neon-branch-identity-go-v2",
                    "observed_at": "2026-08-30T13:00:00Z",
                    "verdict": "NEON_BRANCH_IDENTITY_NO_GO_V2",
                    "branch_inventory_failure_class": "COUNT_DRIFT",
                    "neon": neon,
                    "secret_values_observed": False,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ChronosProductionError, match="REPORT_INVALID"):
            load_guarded_report(path, expected_main_sha="a" * 40)


def test_supervisor_timeout_always_materializes_a_conservative_sanitized_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(
        identity,
        "run_child_once",
        lambda *_args, **_kwargs: identity.SUPERVISOR_TIMEOUT_EXIT,
    )
    output = tmp_path / "identity-timeout.json"
    assert identity._supervised_identity(output) == 124
    report = load_guarded_report(output, expected_main_sha="a" * 40)
    assert report["verdict"] == "NEON_BRANCH_IDENTITY_NO_GO_V2"
    assert report["effect_counter_certainty"] == "UNKNOWN_OR_UPPER_BOUND"
    assert report["effects"]["neon_gets"] == 25
    assert report["effects"]["neon_gets_exact"] is False
    serialized = json.dumps(report)
    assert "synthetic-token" not in serialized


@pytest.mark.parametrize(
    ("return_code", "candidate_payload"),
    ((-15, b'{"truncated":'), (0, b'{"api_key":"secret"}\n')),
)
def test_identity_supervisor_never_promotes_signaled_or_invalid_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    return_code: int,
    candidate_payload: bytes,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")

    def child(command: tuple[str, ...], **_kwargs: object) -> int:
        Path(command[-1]).write_bytes(candidate_payload)
        return return_code

    monkeypatch.setattr(identity, "run_child_once", child)
    output = tmp_path / "identity-supervised.json"
    observed = identity._supervised_identity(output)
    assert observed == (return_code if return_code != 0 else identity.SUPERVISOR_EXPORT_EXIT)
    report = load_guarded_report(output, expected_main_sha="a" * 40)
    assert report["verdict"] == "NEON_BRANCH_IDENTITY_NO_GO_V2"
    assert report["effect_counter_certainty"] == "UNKNOWN_OR_UPPER_BOUND"
    assert report["effects"]["neon_gets"] == 25


def test_identity_workflow_uses_the_evidence_preserving_supervisor() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "--supervise" in source
    assert "timeout --signal" not in source
    assert "steps.artifact_guard.outcome == 'success'" in source


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    @staticmethod
    def iter_content(*, chunk_size: int) -> list[bytes]:
        assert chunk_size == 64 * 1024
        return [b"{}"]

    @staticmethod
    def close() -> None:
        return None


class _CountingSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, *_args: object, **_kwargs: object) -> _Response:
        self.calls += 1
        return _Response()


def test_v2_client_refuses_the_twenty_sixth_get_before_network() -> None:
    session = _CountingSession()
    client = NeonReadOnlyClient(
        "synthetic",
        session=session,  # type: ignore[arg-type]
        authority_validator=lambda: None,
        maximum_gets=25,
    )
    for _ in range(25):
        assert client.get("/projects") == {}
    with pytest.raises(PreflightNoGo) as caught:
        client.get("/projects")
    assert caught.value.gate == "neon_get_budget_exhausted"
    assert client.get_count == 25
    assert session.calls == 25


def test_identity_requires_all_safety_locks_before_authority_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRODUCTION_LOCKED")
    monkeypatch.setattr(
        identity,
        "_v2_authority",
        lambda: pytest.fail("authority reached before safety locks"),
    )
    with pytest.raises(ChronosProductionError, match="SAFETY_LOCK_MISMATCH"):
        identity.run_identity()


def test_identity_rechecks_exact_main_after_dispatch_window_before_neon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.setattr(identity, "_v2_authority", lambda: None)
    events: list[str] = []

    def dispatch_window(*_args: object, **_kwargs: object) -> int:
        events.append("DISPATCH_WINDOW")
        return 1

    def terminal_main(*_args: object, **_kwargs: object) -> tuple[int, int, int]:
        events.append("EXACT_MAIN")
        raise ChronosProductionError("SYNTHETIC_MAIN_DRIFT")

    monkeypatch.setattr(base, "_github_authority_window_dispatch_count", dispatch_window)
    monkeypatch.setattr(base, "_github_actions_state", terminal_main)
    monkeypatch.setattr(
        base,
        "NeonReadOnlyClient",
        lambda *_args, **_kwargs: pytest.fail("Neon reached after main drift"),
    )

    with pytest.raises(ChronosProductionError, match="SYNTHETIC_MAIN_DRIFT"):
        identity.run_identity()
    assert events == ["DISPATCH_WINDOW", "EXACT_MAIN"]


def test_identity_and_seal_workflows_materialize_every_safety_lock() -> None:
    workflows = (
        ROOT / ".github" / "workflows" / "chronos-neon-branch-identity-v2.yml",
        ROOT / ".github" / "workflows" / "chronos-identity-seal-v2.yml",
    )
    for path in workflows:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        job = next(iter(document["jobs"].values()))
        assert {name: str(job["env"].get(name, "")) for name in PRODUCTION_SAFETY_LOCKS} == (
            PRODUCTION_SAFETY_LOCKS
        )


def test_identity_workflow_is_manual_single_attempt_and_neon_only() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trigger = document.get("on", document.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert document["concurrency"] == {
        "group": "chronos-data-torrent-production-global-v1",
        "cancel-in-progress": False,
    }
    job = document["jobs"]["identity"]
    assert "if" not in job
    assert job["environment"] == "chronos-control-plane-production"
    assert job["timeout-minutes"] == 10
    for step in job["steps"]:
        action = step.get("uses")
        if action is not None:
            assert len(str(action).rsplit("@", 1)[1].split()[0]) == 40
    serialized = yaml.safe_dump(document)
    assert "NEON_API_KEY" in serialized
    assert "NEON_BOOTSTRAP_DATABASE_URL" in serialized
    for forbidden in (
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "R2_ACCESS_KEY_ID",
        "ODDS_API_KEY",
        "API_FOOTBALL_KEY",
    ):
        assert forbidden not in serialized
    assert "--require-go" in WORKFLOW.read_text(encoding="utf-8")
