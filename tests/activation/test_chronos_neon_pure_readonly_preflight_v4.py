from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

import scripts.chronos_neon_pure_readonly_preflight_v4 as preflight_module
from robin.chronos_production import DirectPostgresTarget
from scripts.chronos_neon_pure_readonly_preflight_v4 import (
    GO_VERDICT,
    MAX_NEON_GETS,
    MAX_PROJECT_ITEMS,
    MAX_PROJECT_PAGES,
    MAX_SQL_STATEMENTS,
    NO_GO_REASONS,
    NO_GO_VERDICT,
    PROJECT_PAGE_LIMIT,
    SQL_STATEMENTS,
    GateChecks,
    NeonObservation,
    NeonReadOnlyClient,
    _inspect_database,
    _list_projects_bounded,
    _read_authority_inventory,
    _read_revisions,
    _resolve_neon_identity,
    _sanitized_neon,
    _validated_psycopg_url,
    evaluate_checks,
    run_preflight,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "chronos-neon-pure-readonly-preflight-v4.yml"
SCRIPT = ROOT / "scripts" / "chronos_neon_pure_readonly_preflight_v4.py"
LOCK = ROOT / "requirements-chronos-neon-readonly-v4.lock"
GOLDEN = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_pure_readonly_preflight_v4_golden_pack.json"
)
NEON_API_FIXTURE = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_pure_readonly_preflight_v4_neon_api.json"
)
IDENTITY_GOLDEN = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_project_identity_pagination_v1_golden_pack.json"
)
POSITIVE_WITNESS_GOLDEN = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_positive_project_ownership_witness_v1_golden_pack.json"
)
FORBIDDEN_SQL = frozenset(
    {
        "CREATE",
        "ALTER",
        "DROP",
        "GRANT",
        "REVOKE",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "COPY",
        "CALL",
        "DO",
        "VACUUM",
        "ANALYZE",
    }
)


def _on(document: dict[object, object]) -> object:
    return document.get("on", document.get(True))


def _golden_cases() -> list[dict[str, Any]]:
    document = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert document["schema_version"] == ("chronos-neon-pure-readonly-preflight-v4-golden-pack")
    return cast(list[dict[str, Any]], document["cases"])


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda case: case["case_id"])
def test_synthetic_golden_pack(case: dict[str, Any]) -> None:
    checks = GateChecks(**case["checks"])
    decision = evaluate_checks(checks)
    assert decision.verdict == case["expected_verdict"]
    assert decision.reason == case["expected_reason"]


def test_workflow_is_manual_environment_protected_and_single_attempt() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert set(_on(document)) == {"workflow_dispatch"}
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert document["concurrency"] == {
        "group": "chronos-neon-pure-readonly-preflight-v4",
        "cancel-in-progress": False,
    }
    job = document["jobs"]["preflight"]
    assert job["environment"] == "chronos-control-plane-production"
    assert job["timeout-minutes"] == 15
    setup = next(step for step in job["steps"] if "actions/setup-python@" in step.get("uses", ""))
    assert setup["with"]["python-version"] == "3.12.10"
    assert "cache" not in setup["with"]
    assert job["if"] == "${{ github.run_attempt == 1 }}"
    assert job["steps"][0]["name"] == "Refuser toute relance"
    content = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$GITHUB_RUN_ATTEMPT" = "1"' in content
    assert "schedule:" not in content
    assert "workflow_run:" not in content
    assert "repository_dispatch:" not in content
    assert "alembic" not in content.lower()
    for forbidden in ("R2_", "API_FOOTBALL", "ODDS_API_KEY"):
        assert forbidden not in content


def test_workflow_actions_are_sha_pinned_and_artifact_is_sanitized_only() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["preflight"]["steps"]
    for step in steps:
        action = step.get("uses")
        if action is not None:
            assert len(str(action).rsplit("@", 1)[1]) == 40
    serialized = yaml.safe_dump(document)
    assert "persist-credentials: false" in serialized
    assert "include-hidden-files: true" in serialized
    assert "chronos-neon-pure-readonly-preflight-v4.json" in serialized
    assert "NEON_API_KEY" in serialized
    assert "NEON_BOOTSTRAP_DATABASE_URL" in serialized
    assert "NEON_ORG_ID" in serialized
    assert "GITHUB_TOKEN" in serialized
    live = next(step for step in steps if step.get("id") == "live_preflight")
    guard = next(step for step in steps if step.get("id") == "artifact_guard")
    upload = next(
        step for step in steps if "actions/upload-artifact@" in step.get("uses", "")
    )
    assert live["working-directory"] == "${{ github.workspace }}"
    assert live["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "timeout --signal=TERM --kill-after=5s 120s" in live["run"]
    assert "python -m scripts.chronos_neon_pure_readonly_preflight_v4" in live["run"]
    assert guard["if"] == "always()"
    assert guard["working-directory"] == "${{ github.workspace }}"
    assert "--schema chronos-neon-pure-readonly-preflight-v4" in guard["run"]
    assert 'steps.live_preflight.outcome' in guard["run"]
    assert set(guard["env"]) == {
        "GITHUB_TOKEN",
        "NEON_API_KEY",
        "NEON_BOOTSTRAP_DATABASE_URL",
        "NEON_PROJECT_ID",
        "NEON_ORG_ID",
    }
    assert upload["if"] == (
        "${{ always() && steps.artifact_guard.outcome == 'success' }}"
    )
    test_step = next(
        step
        for step in steps
        if "test_chronos_neon_pure_readonly_preflight_v4.py" in step.get("run", "")
    )
    assert "test_chronos_neon_controlled_idle_wake_readonly_v1.py" in test_step["run"]
    assert "test_chronos_end_to_end_live_path_v1.py" in test_step["run"]


def test_supply_chain_lock_is_minimal_hashed_and_mutator_free() -> None:
    lines = [
        line
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lines) == 15
    assert all("==" in line and "--hash=sha256:" in line for line in lines)
    names = {line.split("==", 1)[0].lower() for line in lines}
    assert {"requests", "psycopg", "psycopg-binary", "pytest", "pyyaml"} <= names
    assert not ({"alembic", "boto3", "botocore", "s3transfer", "sqlalchemy"} & names)
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "--require-hashes" in workflow
    assert "--only-binary=:all:" in workflow
    assert "requirements-chronos-neon-readonly-v4.lock" in workflow


def test_neon_client_exposes_get_only_and_has_hard_budget() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    network_calls = {
        node.func.attr.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "get" in network_calls
    assert not ({"post", "put", "patch", "delete", "request"} & network_calls)
    assert MAX_NEON_GETS == 25
    assert "allow_redirects=False" in SCRIPT.read_text(encoding="utf-8")


def test_sql_is_bounded_and_has_no_mutating_statement() -> None:
    assert len(SQL_STATEMENTS) <= MAX_SQL_STATEMENTS == 25
    assert SQL_STATEMENTS[0] == "BEGIN READ ONLY"
    assert SQL_STATEMENTS[-1] == "ROLLBACK"
    allowed_leaders = {"BEGIN", "SHOW", "SELECT", "WITH", "LOCK", "ROLLBACK"}
    for statement in SQL_STATEMENTS:
        without_literals = re.sub(r"'[^']*'", "''", statement)
        tokens = set(re.findall(r"\b[A-Z_]+\b", without_literals.upper()))
        assert statement.split(maxsplit=1)[0].upper() in allowed_leaders
        assert not (FORBIDDEN_SQL & tokens)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in source
    assert "statement_timeout=15000" in source
    assert "lock_timeout=3000" in source
    assert 'sql_write_count": 0' in source
    assert "pg_catalog.pg_class" in SQL_STATEMENTS[
        preflight_module.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK
    ]
    assert "IN SHARE MODE" in SQL_STATEMENTS[preflight_module.SQL_LOCK_ALEMBIC_VERSION]
    assert "ORDER BY version_num" in SQL_STATEMENTS[preflight_module.SQL_REVISION]
    assert "FROM ONLY public.alembic_version" in SQL_STATEMENTS[
        preflight_module.SQL_REVISION
    ]
    for ordinal in (
        preflight_module.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK,
        preflight_module.SQL_TARGET_CLASSIFICATION_AFTER_LOCK,
    ):
        classification = SQL_STATEMENTS[ordinal]
        assert "FROM pg_catalog.pg_trigger tg" in classification
        assert "FROM pg_catalog.pg_rewrite rw" in classification
        assert "con.conname='alembic_version_pkc'" in classification
        assert "pg_catalog.count(*) FROM pg_catalog.pg_constraint" in classification
        assert "pg_catalog.count(*) FROM pg_catalog.pg_index" in classification
        assert "pg_catalog.pg_attrdef" in classification
        assert "att.attacl" in classification
        assert "acl.privilege_type='CREATE'" in classification
    inventory = SQL_STATEMENTS[preflight_module.SQL_CHRONOS_OBJECTS]
    for collision in (
        "uq_chronos_authority_run_revision",
        "uq_chronos_event_operation_type",
        "uq_chronos_event_operation_sequence",
        "uq_chronos_event_authority_sequence",
        "uq_chronos_event_previous_hash",
    ):
        assert collision in inventory
    assert 'endpoint_state == "active"' in source


def test_script_has_only_approved_no_go_reasons_and_verdicts() -> None:
    assert GO_VERDICT == "CHRONOS_NEON_MIGRATION_READY_FOR_SEPARATE_AUTHORIZATION"
    assert NO_GO_VERDICT == "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"
    assert NO_GO_REASONS == {
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        "DIRECT_ENDPOINT_NOT_PROVEN",
        "UNEXPECTED_DATABASE_REVISION",
        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
        "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
        "ENDPOINT_STATE_UNSUPPORTED",
        "RECOVERY_BRANCH_NOT_FEASIBLE",
        "PURCHASE_REQUIRED",
        "SECRET_MISSING",
    }


class _NeverCalledSession:
    def get(self, *_args: object, **_kwargs: object) -> Any:
        raise AssertionError("network must not be reached")


def test_neon_client_rejects_non_project_route_before_network() -> None:
    client = NeonReadOnlyClient("synthetic-only", session=_NeverCalledSession())
    with pytest.raises(RuntimeError, match="NEON_PROJECT_IDENTITY_AMBIGUOUS"):
        client.get("/organizations")


class _SyntheticResponse:
    status_code = 200
    headers: dict[str, str] = {}

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        assert chunk_size == 64 * 1024
        return [b"{}"]

    def close(self) -> None:
        return None


class _CountingSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, *_args: object, **_kwargs: object) -> _SyntheticResponse:
        self.calls += 1
        return _SyntheticResponse()


def test_neon_get_budget_fails_before_call_26() -> None:
    session = _CountingSession()
    client = NeonReadOnlyClient("synthetic-only", session=session)  # type: ignore[arg-type]
    for _ in range(MAX_NEON_GETS):
        assert client.get("/projects") == {}
    with pytest.raises(RuntimeError, match="NEON_PROJECT_IDENTITY_AMBIGUOUS"):
        client.get("/projects")
    assert session.calls == MAX_NEON_GETS


class _FixtureNeonClient:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture
        self.get_count = 0

    def require_get_budget(self, required: int, gate: str) -> None:
        if self.get_count + required > MAX_NEON_GETS:
            raise RuntimeError(gate)

    def get(
        self,
        path: str,
        *,
        query: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        self.get_count += 1
        if path == "/auth":
            return cast(dict[str, Any], self.fixture["auth"])
        if path == "/organizations/synthetic-owner":
            return cast(dict[str, Any], self.fixture["organization"])
        if path == "/projects":
            return cast(dict[str, Any], self.fixture["projects"])
        if path == "/projects/synthetic-project":
            return cast(dict[str, Any], self.fixture["project_detail"])
        if path == "/projects/synthetic-project/branches":
            return cast(dict[str, Any], self.fixture["branches"])
        if path == "/projects/synthetic-project/endpoints":
            return cast(dict[str, Any], self.fixture["endpoints"])
        if path == "/projects/synthetic-project/endpoints/synthetic-endpoint":
            return {"endpoint": deepcopy(self.fixture["endpoints"]["endpoints"][0])}
        if path == "/projects/synthetic-project/branches/synthetic-branch/endpoints":
            return cast(dict[str, Any], self.fixture["endpoints"])
        if path == "/projects/synthetic-project/branches/count":
            return cast(dict[str, Any], self.fixture["branch_count"])
        raise AssertionError(f"unexpected synthetic route: {path}")


def _neon_api_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(NEON_API_FIXTURE.read_text(encoding="utf-8")),
    )


def _synthetic_target() -> DirectPostgresTarget:
    return DirectPostgresTarget(
        host="ep-synthetic.neon.tech",
        port=5432,
        database="synthetic_database",
        username="synthetic_user",
        sslmode="require",
    )


def test_neon_api_fixture_proves_exact_identity_and_owner_branch_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    client = _FixtureNeonClient(_neon_api_fixture())
    observed = _resolve_neon_identity(  # type: ignore[arg-type]
        client,
        _synthetic_target(),
    )
    assert observed.project_id == "synthetic-project"
    assert observed.branch_id == "synthetic-branch"
    assert observed.endpoint_state == "active"
    assert observed.owner_branch_count == 1
    assert observed.branch_limit == 5
    assert observed.identity_path == "CONFIGURED_PROJECT_ID"
    assert observed.identity_verdict == "CONFIGURED_PROJECT_IDENTITY_PROVEN"
    assert observed.project_pages_read == 1
    assert observed.project_inventory_exhaustive is True
    assert observed.branch_capacity_proven is True
    assert observed.endpoint_detail_reads == 1
    assert observed.branch_endpoint_reads == 1
    assert client.get_count == 9


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("pagination", {"cursor": "wrong-parser"}, "NEON_PRODUCTION_BRANCH_AMBIGUOUS"),
        ("pagination", "malformed", "NEON_PRODUCTION_BRANCH_AMBIGUOUS"),
    ],
)
def test_neon_branch_inventory_fails_closed_when_pagination_is_not_complete(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    reason: str,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    fixture = deepcopy(_neon_api_fixture())
    fixture["branches"][field] = value
    with pytest.raises(RuntimeError, match=reason):
        _resolve_neon_identity(  # type: ignore[arg-type]
            _FixtureNeonClient(fixture),
            _synthetic_target(),
        )


def test_neon_missing_branch_limit_is_unknown_not_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    fixture = deepcopy(_neon_api_fixture())
    del fixture["project_detail"]["project"]["owner"]["branches_limit"]
    with pytest.raises(RuntimeError, match="RECOVERY_BRANCH_NOT_FEASIBLE"):
        _resolve_neon_identity(  # type: ignore[arg-type]
            _FixtureNeonClient(fixture),
            _synthetic_target(),
        )


class _ApiResponse:
    def __init__(self, document: dict[str, Any], status_code: int = 200) -> None:
        self._document = deepcopy(document)
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        assert chunk_size == 64 * 1024
        return [json.dumps(self._document).encode("utf-8")]

    def close(self) -> None:
        return None


class _ScriptedNeonSession:
    def __init__(
        self,
        *,
        project_pages: list[dict[str, Any]] | None = None,
        details: dict[str, dict[str, Any]] | None = None,
        branches: dict[str, list[dict[str, Any]]] | None = None,
        endpoints: dict[str, dict[str, Any]] | None = None,
        endpoint_details: dict[str, dict[str, Any]] | None = None,
        branch_endpoints: dict[str, dict[str, Any]] | None = None,
        detail_status: dict[str, int] | None = None,
        enforce_candidate_first: bool = False,
        account_id: str = "owner-shared",
        auth_method: str = "api_key_org",
        organization_status: int = 200,
        account_branch_limit: int = 20,
        account_plan: str = "launch",
        user_organization_id: str = "owner-shared",
        user_organization_count: int = 1,
        user_organization_role: str = "admin",
        member_pagination_next: str | None = None,
        member_contains_self: bool = True,
        member_second_page_contains_self: bool = False,
        branch_count_overrides: dict[str, int] | None = None,
    ) -> None:
        self.project_pages = project_pages or []
        self.details = details or {}
        self.branches = branches or {}
        self.endpoints = endpoints or {}
        self.endpoint_details = endpoint_details or {
            project_id: {"endpoint": deepcopy(document["endpoints"][0])}
            for project_id, document in self.endpoints.items()
            if document.get("endpoints")
        }
        self.branch_endpoints = branch_endpoints or deepcopy(self.endpoints)
        self.detail_status = detail_status or {}
        self.enforce_candidate_first = enforce_candidate_first
        self.account_id = account_id
        self.auth_method = auth_method
        self.organization_status = organization_status
        self.account_branch_limit = account_branch_limit
        self.account_plan = account_plan
        self.user_organization_id = user_organization_id
        self.user_organization_count = user_organization_count
        self.user_organization_ids = [user_organization_id] + [
            f"{user_organization_id}-{index}"
            for index in range(2, user_organization_count + 1)
        ]
        self.user_organization_role = user_organization_role
        self.member_pagination_next = member_pagination_next
        self.member_contains_self = member_contains_self
        self.member_second_page_contains_self = member_second_page_contains_self
        self.member_page_index = 0
        self.branch_count_overrides = branch_count_overrides or {}
        self.project_page_index = 0
        self.branch_page_indexes: dict[str, int] = {}
        self.urls: list[str] = []
        self.paths: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _ApiResponse:
        self.urls.append(url)
        parsed = urlparse(url)
        path = parsed.path.removeprefix("/api/v2")
        query = parse_qs(parsed.query, keep_blank_values=True)
        self.paths.append(path)
        if path == "/auth":
            return _ApiResponse(
                {"account_id": self.account_id, "auth_method": self.auth_method}
            )
        if path == f"/organizations/{self.account_id}":
            return _ApiResponse(
                {"id": self.account_id, "plan": self.account_plan},
                self.organization_status,
            )
        if path == "/users/me":
            return _ApiResponse(
                {
                    "id": self.account_id,
                    "branches_limit": self.account_branch_limit,
                    "plan": self.account_plan,
                }
            )
        if path == "/users/me/organizations":
            return _ApiResponse(
                {
                    "organizations": [
                        {
                            "id": organization_id,
                            "plan": self.account_plan,
                        }
                        for organization_id in self.user_organization_ids
                    ]
                }
            )
        member_match = re.fullmatch(r"/organizations/([^/]+)/members", path)
        if member_match is not None:
            organization_id = member_match.group(1)
            assert organization_id in self.user_organization_ids
            expected_member_query = {
                "limit": ["500"],
                "sort_by": ["role"],
                "sort_order": ["asc"],
            }
            if self.member_page_index:
                expected_member_query["cursor"] = [self.member_pagination_next]
            assert query == expected_member_query
            contains_self = self.member_contains_self or (
                self.member_page_index == 1
                and self.member_second_page_contains_self
            )
            next_cursor = (
                self.member_pagination_next
                if self.member_page_index == 0
                else None
            )
            self.member_page_index += 1
            return _ApiResponse(
                {
                    "members": ([
                        {
                            "member": {
                                "id": "00000000-0000-0000-0000-000000000001",
                                "user_id": self.account_id,
                                "org_id": organization_id,
                                "role": self.user_organization_role,
                            },
                            "user": {},
                        }
                    ] if contains_self else []),
                    "pagination": (
                        {"next": next_cursor}
                        if next_cursor is not None
                        else {}
                    ),
                }
            )
        if path == "/projects":
            assert query["limit"] == [str(PROJECT_PAGE_LIMIT)]
            if self.project_page_index:
                if self.enforce_candidate_first:
                    assert self.paths[-2].endswith("/endpoints")
                previous = self.project_pages[self.project_page_index - 1]
                assert query["cursor"] == [previous["pagination"]["cursor"]]
            else:
                assert "cursor" not in query
            page = self.project_pages[self.project_page_index]
            self.project_page_index += 1
            return _ApiResponse(page)
        match = re.fullmatch(r"/projects/([a-z0-9-]{1,60})(.*)", path)
        if match is None:
            raise AssertionError(f"unexpected synthetic route: {path}")
        project_id, suffix = match.groups()
        if suffix == "":
            status = self.detail_status.get(project_id, 200)
            return _ApiResponse(self.details.get(project_id, {}), status)
        if suffix == "/endpoints":
            return _ApiResponse(self.endpoints[project_id])
        if re.fullmatch(r"/endpoints/[a-z0-9-]{1,60}", suffix):
            return _ApiResponse(self.endpoint_details[project_id])
        if suffix == "/branches":
            assert query["limit"] == ["10000"]
            assert query["sort_by"] == ["updated_at"]
            assert query["sort_order"] == ["asc"]
            assert query["include_deleted"] == ["false"]
            index = self.branch_page_indexes.get(project_id, 0)
            pages = self.branches[project_id]
            if index:
                assert query["cursor"] == [pages[index - 1]["pagination"]["next"]]
            else:
                assert "cursor" not in query
            self.branch_page_indexes[project_id] = index + 1
            return _ApiResponse(pages[index])
        if suffix == "/branches/count":
            if project_id in self.branch_count_overrides:
                return _ApiResponse(
                    {"count": self.branch_count_overrides[project_id]}
                )
            pages = self.branches.get(project_id, [])
            return _ApiResponse(
                {"count": sum(len(page.get("branches", [])) for page in pages)}
            )
        if re.fullmatch(
            r"/branches/[a-z0-9-]{1,60}/endpoints",
            suffix,
        ):
            return _ApiResponse(self.branch_endpoints[project_id])
        raise AssertionError(f"unexpected synthetic route: {path}")


def _project(project_id: str) -> dict[str, Any]:
    return {
        "id": project_id,
        "name": f"name-{project_id}",
        "owner_id": "owner-shared",
        "org_id": "owner-shared",
    }


def _project_page(
    project_ids: list[str],
    *,
    cursor: str | None = None,
    unavailable: list[str] | None = None,
) -> dict[str, Any]:
    page: dict[str, Any] = {
        "projects": [_project(project_id) for project_id in project_ids],
        "unavailable_project_ids": unavailable or [],
    }
    if cursor is not None:
        page["pagination"] = {"cursor": cursor}
    return page


def _detail(project_id: str) -> dict[str, Any]:
    return {
        "project": {
            "id": project_id,
            "name": f"name-{project_id}",
            "owner_id": "owner-shared",
            "org_id": "owner-shared",
            "region_id": "aws-eu-synthetic-1",
            "history_retention_seconds": 86_400,
            "pg_version": 16,
            "owner": {"branches_limit": 20, "subscription_type": "launch"},
        }
    }


def _branch(
    *,
    branch_id: str = "branch-production",
    project_id: str = "synthetic-project",
    default: bool = True,
) -> dict[str, Any]:
    return {
        "id": branch_id,
        "project_id": project_id,
        "name": "production",
        "current_state": "ready",
        "default": default,
    }


def _endpoint(
    project_id: str,
    *,
    endpoint_id: str = "endpoint-production",
    branch_id: str = "branch-production",
    host: str = "ep-synthetic.neon.tech",
    state: str = "active",
) -> dict[str, Any]:
    return {
        "id": endpoint_id,
        "project_id": project_id,
        "branch_id": branch_id,
        "host": host,
        "type": "read_write",
        "current_state": state,
        "autoscaling_limit_max_cu": 1,
        "suspend_timeout_seconds": 300,
        "pooler_enabled": False,
        "disabled": False,
        "region_id": "aws-eu-synthetic-1",
    }


def _client(session: _ScriptedNeonSession) -> NeonReadOnlyClient:
    return NeonReadOnlyClient("synthetic-only", session=session)  # type: ignore[arg-type]


def _identity_golden_cases() -> dict[str, dict[str, Any]]:
    document = json.loads(IDENTITY_GOLDEN.read_text(encoding="utf-8"))
    assert document["schema_version"] == ("chronos-neon-project-identity-pagination-v1-golden-pack")
    return {case["case_id"]: case for case in document["cases"]}


def _project_pagination_scenario(case_id: str) -> tuple[list[dict[str, Any]], int]:
    if case_id == "PROJECTS_ONE_PAGE":
        return [_project_page(["project-a"])], 0
    if case_id == "PROJECTS_TWO_PAGES":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-b"]),
        ], 0
    if case_id == "PROJECTS_THREE_PAGES":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-b"], cursor="cursor-two"),
            _project_page(["project-c"]),
        ], 0
    if case_id == "PROJECTS_TERMINAL_EMPTY_REPEATED_CURSOR":
        return [
            _project_page(["project-a"], cursor="cursor-terminal"),
            _project_page([], cursor="cursor-terminal"),
        ], 0
    if case_id == "PROJECTS_TERMINAL_EMPTY_UNAVAILABLE":
        return [
            _project_page(["project-a"], cursor="cursor-terminal"),
            _project_page(
                [], cursor="cursor-terminal", unavailable=["project-missing"]
            ),
        ], 0
    if case_id == "PROJECTS_TERMINAL_EMPTY_MALFORMED_PAGINATION":
        terminal = _project_page([])
        terminal["pagination"] = {}
        return [
            _project_page(["project-a"], cursor="cursor-terminal"),
            terminal,
        ], 0
    if case_id == "PROJECTS_CURSOR_REPEATED":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-b"], cursor="cursor-one"),
        ], 0
    if case_id == "PROJECTS_CURSOR_CYCLE":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-b"], cursor="cursor-two"),
            _project_page(["project-c"], cursor="cursor-one"),
        ], 0
    if case_id == "PROJECTS_DUPLICATE_ID_ACROSS_PAGES":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-a", "project-b"]),
        ], 0
    if case_id == "PROJECTS_UNAVAILABLE_NON_EMPTY":
        return [_project_page(["project-a"], unavailable=["project-missing"])], 0
    if case_id == "PROJECTS_MALFORMED_PAGINATION":
        page = _project_page(["project-a"])
        page["pagination"] = {}
        return [page], 0
    if case_id == "PROJECTS_TOO_MANY_PAGES":
        return [
            _project_page(["project-a"], cursor="cursor-one"),
            _project_page(["project-b"], cursor="cursor-two"),
            _project_page(["project-c"], cursor="cursor-three"),
        ], 0
    if case_id == "PROJECTS_TOO_MANY_ITEMS":
        ids = [f"project-{index}" for index in range(MAX_PROJECT_ITEMS + 1)]
        return [_project_page(ids)], 0
    if case_id == "PROJECTS_GET_BUDGET_EXHAUSTED":
        return [_project_page(["project-a"])], MAX_NEON_GETS - 4
    raise AssertionError(case_id)


@pytest.mark.parametrize(
    "case_id",
    [
        "PROJECTS_ONE_PAGE",
        "PROJECTS_TWO_PAGES",
        "PROJECTS_THREE_PAGES",
        "PROJECTS_TERMINAL_EMPTY_REPEATED_CURSOR",
        "PROJECTS_TERMINAL_EMPTY_UNAVAILABLE",
        "PROJECTS_TERMINAL_EMPTY_MALFORMED_PAGINATION",
        "PROJECTS_CURSOR_CYCLE",
        "PROJECTS_CURSOR_REPEATED",
        "PROJECTS_DUPLICATE_ID_ACROSS_PAGES",
        "PROJECTS_UNAVAILABLE_NON_EMPTY",
        "PROJECTS_MALFORMED_PAGINATION",
        "PROJECTS_TOO_MANY_PAGES",
        "PROJECTS_TOO_MANY_ITEMS",
        "PROJECTS_GET_BUDGET_EXHAUSTED",
    ],
)
def test_project_pagination_golden_pack(case_id: str) -> None:
    case = _identity_golden_cases()[case_id]
    pages, initial_get_count = _project_pagination_scenario(case_id)
    session = _ScriptedNeonSession(project_pages=pages)
    client = _client(session)
    client.get_count = initial_get_count
    audit = preflight_module.IdentityAudit("BOUNDED_DISCOVERY")
    if case["expected_gate"] is None:
        projects = _list_projects_bounded(client, audit)
        assert len(projects) == sum(len(page["projects"]) for page in pages)
        assert audit.project_pages_read == len(pages)
        assert audit.project_inventory_exhaustive is True
    else:
        with pytest.raises(preflight_module.PreflightNoGo) as caught:
            _list_projects_bounded(client, audit)
        assert caught.value.gate == case["expected_gate"]
    assert client.get_count <= MAX_NEON_GETS
    assert audit.project_pages_read <= MAX_PROJECT_PAGES


def _configured_session(case_id: str) -> _ScriptedNeonSession:
    project_id = "synthetic-project"
    detail_status = {project_id: 404} if case_id == "CONFIGURED_ID_NOT_FOUND" else {}
    branch = _branch(default=case_id != "CONFIGURED_ID_NON_DEFAULT_BRANCH")
    endpoints = [_endpoint(project_id)]
    if case_id == "CONFIGURED_ID_ENDPOINT_MISSING":
        endpoints[0]["host"] = "ep-other.neon.tech"
    elif case_id == "CONFIGURED_ID_ENDPOINT_DUPLICATED":
        endpoints.append(_endpoint(project_id, endpoint_id="endpoint-duplicate"))
    elif case_id == "CONFIGURED_ID_WRONG_BRANCH":
        endpoints[0]["branch_id"] = "branch-other"
    elif case_id == "CONFIGURED_ID_IDLE_ENDPOINT":
        endpoints[0]["current_state"] = "idle"
    return _ScriptedNeonSession(
        project_pages=[_project_page([project_id])],
        details={project_id: _detail(project_id)},
        branches={project_id: [{"branches": [branch], "pagination": {}}]},
        endpoints={project_id: {"endpoints": endpoints}},
        detail_status=detail_status,
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "CONFIGURED_ID_VALID_EXACT_ENDPOINT",
        "CONFIGURED_ID_NOT_FOUND",
        "CONFIGURED_ID_INVALID",
        "CONFIGURED_ID_ENDPOINT_MISSING",
        "CONFIGURED_ID_ENDPOINT_DUPLICATED",
        "CONFIGURED_ID_WRONG_BRANCH",
        "CONFIGURED_ID_NON_DEFAULT_BRANCH",
        "CONFIGURED_ID_IDLE_ENDPOINT",
    ],
)
def test_configured_project_identity_golden_pack(
    case_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _identity_golden_cases()[case_id]
    configured = "invalid/project" if case_id == "CONFIGURED_ID_INVALID" else "synthetic-project"
    monkeypatch.setenv("NEON_PROJECT_ID", configured)
    session = _configured_session(case_id)
    client = _client(session)
    if case["expected_gate"] is None:
        observed = _resolve_neon_identity(client, _synthetic_target())
        assert observed.identity_verdict == case["expected_identity_verdict"]
        assert observed.project_pages_read == 1
        assert observed.endpoint_projects_inspected == 1
        assert observed.project_inventory_exhaustive is True
        assert observed.branch_capacity_proven is True
    else:
        with pytest.raises(preflight_module.PreflightNoGo) as caught:
            _resolve_neon_identity(client, _synthetic_target())
        assert caught.value.gate == case["expected_gate"]
    if case_id != "CONFIGURED_ID_INVALID":
        assert "/projects" in session.paths
    assert client.get_count <= MAX_NEON_GETS


@pytest.mark.parametrize(
    ("location", "expected_gate"),
    [
        ("summary", "project_inventory_incomplete"),
        ("detail", "project_detail_id_or_owner_mismatch"),
    ],
)
def test_configured_project_owner_and_org_identity_must_agree(
    monkeypatch: pytest.MonkeyPatch,
    location: str,
    expected_gate: str,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    session = _configured_session("CONFIGURED_ID_VALID_EXACT_ENDPOINT")
    if location == "summary":
        session.project_pages[0]["projects"][0]["org_id"] = "owner-other"
    else:
        session.details["synthetic-project"]["project"]["org_id"] = "owner-other"
    with pytest.raises(preflight_module.PreflightNoGo) as caught:
        _resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == expected_gate


def test_legacy_project_owner_without_org_id_remains_semantically_unambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    session = _configured_session("CONFIGURED_ID_VALID_EXACT_ENDPOINT")
    session.project_pages[0]["projects"][0].pop("org_id")
    session.details["synthetic-project"]["project"].pop("org_id")
    observed = _resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.identity_verdict == "CONFIGURED_PROJECT_IDENTITY_PROVEN"


@pytest.mark.parametrize(
    ("location", "expected_gate"),
    [
        ("summary", "project_inventory_incomplete"),
        ("detail", "project_detail_id_or_owner_mismatch"),
    ],
)
def test_project_without_org_id_binds_legacy_owner_to_selected_organization(
    monkeypatch: pytest.MonkeyPatch,
    location: str,
    expected_gate: str,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    session = _configured_session("CONFIGURED_ID_VALID_EXACT_ENDPOINT")
    summary = session.project_pages[0]["projects"][0]
    detail = session.details["synthetic-project"]["project"]
    summary.pop("org_id")
    detail.pop("org_id")
    (summary if location == "summary" else detail)["owner_id"] = "owner-other"
    with pytest.raises(preflight_module.PreflightNoGo) as caught:
        _resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == expected_gate


def _discovery_session(case_id: str) -> _ScriptedNeonSession:
    if case_id == "DISCOVERY_BUDGET_TOO_SMALL":
        ids = [f"project-{index}" for index in range(MAX_PROJECT_ITEMS + 1)]
        return _ScriptedNeonSession(project_pages=[_project_page(ids)])
    project_ids = ["project-a"]
    pages = [_project_page(project_ids)]
    if case_id in {"DISCOVERY_MULTIPLE_ENDPOINT_MATCH", "DISCOVERY_PAGINATED_UNIQUE_MATCH"}:
        project_ids = ["project-a", "project-b"]
    if case_id == "DISCOVERY_PAGINATED_UNIQUE_MATCH":
        pages = [
            _project_page(["project-a"], cursor="opaque:/?& cursor"),
            _project_page(["project-b"]),
        ]
    elif len(project_ids) == 2:
        pages = [_project_page(project_ids)]
    details = {project_id: _detail(project_id) for project_id in project_ids}
    branches = {
        project_id: [
            {"branches": [_branch(project_id=project_id)], "pagination": {}}
        ]
        for project_id in project_ids
    }
    endpoints: dict[str, dict[str, Any]] = {}
    for index, project_id in enumerate(project_ids):
        host = "ep-other.neon.tech"
        if case_id == "DISCOVERY_UNIQUE_ENDPOINT_MATCH":
            host = "ep-synthetic.neon.tech"
        elif case_id == "DISCOVERY_MULTIPLE_ENDPOINT_MATCH":
            host = "ep-synthetic.neon.tech"
        elif case_id == "DISCOVERY_PAGINATED_UNIQUE_MATCH" and index == 1:
            host = "ep-synthetic.neon.tech"
        endpoints[project_id] = {"endpoints": [_endpoint(project_id, host=host)]}
    return _ScriptedNeonSession(
        project_pages=pages,
        details=details,
        branches=branches,
        endpoints=endpoints,
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "DISCOVERY_UNIQUE_ENDPOINT_MATCH",
        "DISCOVERY_ZERO_ENDPOINT_MATCH",
        "DISCOVERY_MULTIPLE_ENDPOINT_MATCH",
        "DISCOVERY_BUDGET_TOO_SMALL",
        "DISCOVERY_PAGINATED_UNIQUE_MATCH",
    ],
)
def test_bounded_discovery_golden_pack(
    case_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    case = _identity_golden_cases()[case_id]
    session = _discovery_session(case_id)
    client = _client(session)
    if case["expected_gate"] is None:
        observed = _resolve_neon_identity(client, _synthetic_target())
        assert observed.identity_verdict == case["expected_identity_verdict"]
        assert observed.project_pages_read == len(session.project_pages)
        assert observed.endpoint_projects_inspected == len(session.endpoints)
    else:
        with pytest.raises(preflight_module.PreflightNoGo) as caught:
            _resolve_neon_identity(client, _synthetic_target())
        assert caught.value.gate == case["expected_gate"]
        if case_id == "DISCOVERY_BUDGET_TOO_SMALL":
            assert caught.value.sanitized_evidence is not None
            assert session.paths == [
                "/auth",
                "/organizations/owner-shared",
                "/projects",
            ]
    assert client.get_count <= MAX_NEON_GETS
    if case_id == "DISCOVERY_PAGINATED_UNIQUE_MATCH":
        cursor_url = next(url for url in session.urls if "cursor=" in url)
        assert "opaque:/?& cursor" not in cursor_url
        assert "cursor=opaque%3A%2F%3F%26+cursor" in cursor_url


def _positive_witness_cases() -> dict[str, dict[str, Any]]:
    document = json.loads(POSITIVE_WITNESS_GOLDEN.read_text(encoding="utf-8"))
    assert document["schema_version"] == (
        "chronos-neon-positive-project-ownership-witness-v1-golden-pack"
    )
    return {case["case_id"]: case for case in document["cases"]}


def _positive_witness_session(case_id: str) -> _ScriptedNeonSession:
    project_ids = ["project-a"]
    pages = [_project_page(project_ids)]
    matching_project = "project-a"
    if case_id == "FIRST_PAGE_MULTIPLE_PROJECTS_ONE_EXACT_MATCH":
        project_ids = ["project-a", "project-b", "project-c"]
        matching_project = "project-b"
        pages = [_project_page(project_ids)]
    elif case_id == "FIRST_PAGE_NO_MATCH_CURSOR_CONTINUES":
        project_ids = ["project-a", "project-b"]
        matching_project = "project-b"
        pages = [
            _project_page(["project-a"], cursor="cursor-a"),
            _project_page(["project-b"]),
        ]
    elif case_id == "FIRST_PAGE_MATCH_CURSOR_FOLLOWED":
        project_ids = ["project-a", "project-b"]
        pages = [
            _project_page(["project-a"], cursor="cursor-followed"),
            _project_page(["project-b"]),
        ]
    elif case_id == "MATCH_THEN_TERMINAL_EMPTY_CURSOR_ECHO":
        pages = [
            _project_page(["project-a"], cursor="cursor-terminal"),
            _project_page([], cursor="cursor-terminal"),
        ]
    elif case_id == "MATCH_THEN_NONEMPTY_CURSOR_CYCLE":
        project_ids = ["project-a", "project-b"]
        pages = [
            _project_page(["project-a"], cursor="cursor-cycle"),
            _project_page(["project-b"], cursor="cursor-cycle"),
        ]
    elif case_id == "FIRST_PAGE_MULTIPLE_EXACT_MATCHES":
        project_ids = ["project-a", "project-b"]
        pages = [_project_page(project_ids)]
    elif case_id == "NO_MATCH_THEN_CURSOR_CYCLE":
        project_ids = ["project-a", "project-b"]
        matching_project = ""
        pages = [
            _project_page(["project-a"], cursor="cursor-cycle"),
            _project_page(["project-b"], cursor="cursor-cycle"),
        ]

    details = {project_id: _detail(project_id) for project_id in project_ids}
    branches = {
        project_id: [
            {"branches": [_branch(project_id=project_id)], "pagination": {}}
        ]
        for project_id in project_ids
    }
    endpoints: dict[str, dict[str, Any]] = {}
    for project_id in project_ids:
        exact = project_id == matching_project
        if case_id == "FIRST_PAGE_MULTIPLE_EXACT_MATCHES":
            exact = True
        endpoints[project_id] = {
            "endpoints": [
                _endpoint(
                    project_id,
                    host=(
                        "ep-synthetic.neon.tech"
                        if exact
                        else f"ep-other-{project_id}.neon.tech"
                    ),
                )
            ]
        }
    endpoint_details = {
        project_id: {"endpoint": deepcopy(document["endpoints"][0])}
        for project_id, document in endpoints.items()
    }
    branch_endpoints = deepcopy(endpoints)

    if case_id == "ENDPOINT_DETAIL_PROJECT_MISMATCH":
        endpoint_details[matching_project]["endpoint"]["project_id"] = "project-other"
    elif case_id == "ENDPOINT_DETAIL_BRANCH_MISMATCH":
        endpoint_details[matching_project]["endpoint"]["branch_id"] = "branch-other"
    elif case_id == "ENDPOINT_DETAIL_HOST_MISMATCH":
        endpoint_details[matching_project]["endpoint"]["host"] = "ep-other.neon.tech"
    elif case_id == "PROJECT_DETAIL_ID_MISMATCH":
        details[matching_project]["project"]["id"] = "project-other"
    elif case_id == "BRANCH_RELATIONSHIP_MISSING":
        branches[matching_project] = [
            {
                "branches": [
                    _branch(branch_id="branch-other", project_id=matching_project)
                ],
                "pagination": {},
            }
        ]
    elif case_id == "BRANCH_NOT_DEFAULT":
        branches[matching_project] = [
            {
                "branches": [_branch(project_id=matching_project, default=False)],
                "pagination": {},
            }
        ]
    elif case_id == "BRANCH_ENDPOINT_CONFIRMATION_MISMATCH":
        branch_endpoints[matching_project]["endpoints"][0]["host"] = (
            "ep-other.neon.tech"
        )
    return _ScriptedNeonSession(
        project_pages=pages,
        details=details,
        branches=branches,
        endpoints=endpoints,
        endpoint_details=endpoint_details,
        branch_endpoints=branch_endpoints,
        enforce_candidate_first=True,
    )


@pytest.mark.parametrize("case_id", list(_positive_witness_cases()))
def test_positive_project_ownership_witness_golden_pack(
    case_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    case = _positive_witness_cases()[case_id]
    session = _positive_witness_session(case_id)
    client = _client(session)
    if case["expected_gate"] is None:
        observed = _resolve_neon_identity(client, _synthetic_target())
        assert observed.identity_path == "POSITIVE_ENDPOINT_WITNESS"
        assert observed.identity_verdict == (
            "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
        )
        assert observed.project_inventory_exhaustive is True
        assert observed.endpoint_detail_reads == 1
        assert observed.project_detail_reads == 1
        assert observed.branch_endpoint_reads == 1
        assert observed.cursor_cycle_encountered is False
        assert len(observed.positive_witness_checks) == 6
    else:
        with pytest.raises(preflight_module.PreflightNoGo) as caught:
            _resolve_neon_identity(client, _synthetic_target())
        assert caught.value.gate == case["expected_gate"]
        assert caught.value.sanitized_evidence is not None
    assert client.get_count <= MAX_NEON_GETS

    if case_id == "FIRST_PAGE_MATCH_CURSOR_FOLLOWED":
        assert session.project_page_index == 2
        assert any("cursor=" in url for url in session.urls)
    if case_id == "MATCH_THEN_TERMINAL_EMPTY_CURSOR_ECHO":
        assert session.project_page_index == 2
        assert observed.cursor_continuation_requested is True
        assert observed.cursor_cycle_encountered is False
    if case_id == "MATCH_THEN_NONEMPTY_CURSOR_CYCLE":
        assert session.project_page_index == 2
        assert caught.value.sanitized_evidence["cursor_continuation_requested"] is True
        assert caught.value.sanitized_evidence["cursor_cycle_encountered"] is True
    if case_id == "FIRST_PAGE_ONE_PROJECT_EXACT_ENDPOINT_MATCH":
        assert session.paths[2:4] == [
            "/projects",
            "/projects/project-a/endpoints",
        ]
        assert session.project_page_index == 1
    if case_id == "FIRST_PAGE_NO_MATCH_CURSOR_CONTINUES":
        assert session.paths[2:6] == [
            "/projects",
            "/projects/project-a/endpoints",
            "/projects",
            "/projects/project-b/endpoints",
        ]
    if case_id == "NO_MATCH_THEN_CURSOR_CYCLE":
        assert caught.value.sanitized_evidence["cursor_continuation_requested"] is True
        assert caught.value.sanitized_evidence["cursor_cycle_encountered"] is True


def test_project_endpoint_inventory_rejects_dangling_branch_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session(
        "FIRST_PAGE_ONE_PROJECT_EXACT_ENDPOINT_MATCH"
    )
    dangling = deepcopy(session.endpoints["project-a"]["endpoints"][0])
    dangling["id"] = "endpoint-dangling"
    dangling["branch_id"] = "branch-does-not-exist"
    dangling["host"] = "ep-unrelated.neon.tech"
    session.endpoints["project-a"]["endpoints"].append(dangling)

    with pytest.raises(preflight_module.PreflightNoGo) as caught:
        _resolve_neon_identity(_client(session), _synthetic_target())

    assert caught.value.gate == "branch_endpoint_confirmation_mismatch"


@pytest.mark.parametrize("surface", ["endpoint", "branch"])
def test_external_lifecycle_enums_are_case_sensitive(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session(
        "FIRST_PAGE_ONE_PROJECT_EXACT_ENDPOINT_MATCH"
    )
    if surface == "endpoint":
        session.endpoints["project-a"]["endpoints"][0]["current_state"] = "ACTIVE"
        session.endpoint_details["project-a"]["endpoint"]["current_state"] = "ACTIVE"
    else:
        session.branches["project-a"][0]["branches"][0]["current_state"] = "READY"

    with pytest.raises(preflight_module.PreflightNoGo):
        _resolve_neon_identity(_client(session), _synthetic_target())


@pytest.mark.parametrize("contradiction", ["endpoint_detail", "branch_endpoint"])
def test_configured_identity_requires_endpoint_and_branch_corroboration(
    monkeypatch: pytest.MonkeyPatch,
    contradiction: str,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    session = _configured_session("CONFIGURED_ID_VALID_EXACT_ENDPOINT")
    if contradiction == "endpoint_detail":
        session.endpoint_details["synthetic-project"]["endpoint"]["disabled"] = True
        expected_gate = "endpoint_detail_disabled"
    else:
        session.branch_endpoints["synthetic-project"]["endpoints"][0][
            "branch_id"
        ] = "branch-other"
        expected_gate = "branch_endpoint_confirmation_mismatch"

    with pytest.raises(preflight_module.PreflightNoGo) as caught:
        _resolve_neon_identity(_client(session), _synthetic_target())

    assert caught.value.gate == expected_gate


def test_positive_witness_is_order_independent_and_never_selects_by_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    fingerprints: set[str] = set()
    for order in (
        ["project-a", "project-b", "project-c"],
        ["project-c", "project-a", "project-b"],
        ["project-b", "project-c", "project-a"],
    ):
        session = _positive_witness_session(
            "FIRST_PAGE_MULTIPLE_PROJECTS_ONE_EXACT_MATCH"
        )
        session.project_pages = [_project_page(order)]
        observed = _resolve_neon_identity(_client(session), _synthetic_target())
        fingerprints.add(_sanitized_neon(observed)["project_id_sha256"])
    assert len(fingerprints) == 1


def test_positive_witness_sanitization_rejects_raw_identity_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    success = _resolve_neon_identity(
        _client(_positive_witness_session("FIRST_PAGE_ONE_PROJECT_EXACT_ENDPOINT_MATCH")),
        _synthetic_target(),
    )
    serialized = json.dumps(_sanitized_neon(success), sort_keys=True)
    for forbidden in (
        success.project_id,
        success.endpoint_id,
        success.branch_id,
        success.endpoint_host,
    ):
        assert forbidden not in serialized

    cycle_client = _client(_positive_witness_session("NO_MATCH_THEN_CURSOR_CYCLE"))
    with pytest.raises(preflight_module.PreflightNoGo) as caught:
        _resolve_neon_identity(cycle_client, _synthetic_target())
    refusal = json.dumps(caught.value.sanitized_evidence, sort_keys=True)
    assert "cursor-cycle" not in refusal
    assert "project-a" not in refusal
    assert "project-b" not in refusal


def test_projects_and_branches_use_distinct_pagination_parsers() -> None:
    project_page = _project_page(["project-a"])
    project_page["pagination"] = {"next": "branch-style"}
    project_client = _client(_ScriptedNeonSession(project_pages=[project_page]))
    with pytest.raises(preflight_module.PreflightNoGo) as project_error:
        _list_projects_bounded(
            project_client,
            preflight_module.IdentityAudit("BOUNDED_DISCOVERY"),
        )
    assert project_error.value.gate == "project_pagination_invalid"

    fixture = _neon_api_fixture()
    fixture["branches"]["pagination"] = {"cursor": "project-style"}
    client = _FixtureNeonClient(fixture)
    with pytest.raises(preflight_module.PreflightNoGo) as branch_error:
        preflight_module._list_branches_bounded(
            client,  # type: ignore[arg-type]
            "synthetic-project",
            preflight_module.IdentityAudit("CONFIGURED_PROJECT_ID"),
            reserve_after=0,
        )
    assert branch_error.value.gate == "branch_inventory_truncated"


def test_branch_cursor_is_followed_encoded_and_never_reported_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEON_PROJECT_ID", "synthetic-project")
    raw_cursor = "branch:/?& cursor"
    session = _ScriptedNeonSession(
        project_pages=[_project_page(["synthetic-project"])],
        details={"synthetic-project": _detail("synthetic-project")},
        branches={
            "synthetic-project": [
                {
                    "branches": [_branch()],
                    "pagination": {
                        "next": raw_cursor,
                        "sort_by": "updated_at",
                        "sort_order": "asc",
                    },
                },
                {
                    "branches": [
                        _branch(branch_id="branch-secondary", default=False)
                    ]
                },
            ]
        },
        endpoints={"synthetic-project": {"endpoints": [_endpoint("synthetic-project")]}},
    )
    observed = _resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.api_get_count == 10
    cursor_url = next(url for url in session.urls if "cursor=" in url)
    assert raw_cursor not in cursor_url
    assert "cursor=branch%3A%2F%3F%26+cursor" in cursor_url
    assert raw_cursor not in json.dumps(_sanitized_neon(observed), sort_keys=True)


def test_sanitized_neon_observation_hashes_branch_name() -> None:
    sentinel = "provider-branch-name-must-not-leak"
    observed = NeonObservation(
        identity_path="CONFIGURED_PROJECT_ID",
        identity_verdict="CONFIGURED_PROJECT_IDENTITY_PROVEN",
        project_id="project",
        project_name="project-name",
        region="region",
        branch_id="branch",
        branch_name=sentinel,
        branch_default=True,
        branch_parent_id=None,
        endpoint_id="endpoint",
        endpoint_host="endpoint.neon.tech",
        endpoint_state="active",
        branch_state="ready",
        owner_id="owner-shared",
        owner_branch_count=1,
        branch_limit=5,
        history_retention_seconds=1,
        postgresql_major=16,
        project_pages_read=0,
        projects_observed=1,
        endpoint_projects_inspected=1,
        api_get_count=4,
    )
    serialized = json.dumps(_sanitized_neon(observed), sort_keys=True)
    assert sentinel not in serialized
    assert "production_branch_name_sha256" in serialized


@pytest.mark.parametrize(
    "suffix",
    [
        "&host=attacker.example",
        "&port=6543",
        "#host=attacker.example",
        ";host=attacker.example",
    ],
)
def test_database_url_rejects_libpq_override_parameters(suffix: str) -> None:
    dsn = (
        "postgresql://synthetic_user:synthetic_password@"
        f"ep-synthetic.neon.tech/synthetic_database?sslmode=require{suffix}"
    )
    with pytest.raises(RuntimeError, match="DIRECT_ENDPOINT_NOT_PROVEN"):
        _validated_psycopg_url(dsn)


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=require&channel_binding=require",
        "channel_binding=require&sslmode=verify-full",
    ],
)
def test_preflight_uses_shared_secure_dsn_contract(query: str) -> None:
    dsn = (
        "postgresql://synthetic_user:synthetic_password@"
        f"ep-synthetic.neon.tech/synthetic_database?{query}"
    )
    normalized, target = _validated_psycopg_url(dsn)
    assert normalized.startswith("postgresql://")
    assert target.sslmode in {"require", "verify-full"}
    assert target.channel_binding == "require"


def test_unexpected_query_name_is_hashed_in_sanitized_failure_profile() -> None:
    unexpected_name = "synthetic_sensitive_parameter_name"
    dsn = (
        "postgresql://synthetic_user:synthetic_password@"
        "ep-synthetic.neon.tech/synthetic_database?sslmode=require&"
        f"{unexpected_name}=synthetic_value"
    )
    with pytest.raises(RuntimeError, match="DIRECT_ENDPOINT_NOT_PROVEN") as caught:
        _validated_psycopg_url(dsn)
    profile = caught.value.dsn_security_profile
    assert profile["contract_verdict"] == ("NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT")
    assert profile["unexpected_parameter_count"] == 1
    assert unexpected_name not in json.dumps(profile, sort_keys=True)
    assert caught.value.gate == "database_url_parameters_forbidden"


@pytest.mark.parametrize(
    "override",
    [
        "host=attacker.example",
        "hostaddr=192.0.2.10",
        "port=6543",
        "dbname=other",
        "user=other",
        "service=other",
    ],
)
def test_libpq_redirection_fails_before_psycopg_connect(
    monkeypatch: pytest.MonkeyPatch,
    override: str,
) -> None:
    connect_calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("psycopg.connect must remain unreachable")

    monkeypatch.setattr(preflight_module.psycopg, "connect", forbidden_connect)
    dsn = (
        "postgresql://synthetic_user:synthetic_password@"
        "ep-synthetic.neon.tech/synthetic_database?sslmode=require&" + override
    )
    with pytest.raises(RuntimeError, match="DIRECT_ENDPOINT_NOT_PROVEN"):
        _inspect_database(dsn, expected_postgresql_major=16)
    assert connect_calls == 0


@pytest.mark.parametrize(
    "host",
    [
        "ep-synthetic-%70ooler.eu.neon.tech",
        "ep-safe.eu.neon.tech%2Cep-other.eu.neon.tech",
        "%2Ftmp%2Fep-safe.eu.neon.tech",
    ],
)
def test_encoded_host_redirection_fails_before_preflight_connect(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    connect_calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("psycopg.connect must remain unreachable")

    monkeypatch.setattr(preflight_module.psycopg, "connect", forbidden_connect)
    dsn = (
        "postgresql://synthetic_user:synthetic_password@"
        f"{host}/synthetic_database?sslmode=require&channel_binding=require"
    )
    with pytest.raises(RuntimeError, match="DIRECT_ENDPOINT_NOT_PROVEN"):
        _inspect_database(dsn, expected_postgresql_major=16)
    assert connect_calls == 0


@pytest.mark.parametrize(
    "netloc",
    [
        "synthetic_user:synthetic_password@ep-first.eu.neon.tech,ep-second.eu.neon.tech@ep-legit.eu.neon.tech",
        "synthetic_user:synthetic_password@@ep-legit.eu.neon.tech",
    ],
)
def test_ambiguous_userinfo_fails_before_preflight_connect(
    monkeypatch: pytest.MonkeyPatch,
    netloc: str,
) -> None:
    connect_calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("psycopg.connect must remain unreachable")

    monkeypatch.setattr(preflight_module.psycopg, "connect", forbidden_connect)
    dsn = f"postgresql://{netloc}/synthetic_database?sslmode=require&channel_binding=require"
    with pytest.raises(RuntimeError, match="DIRECT_ENDPOINT_NOT_PROVEN"):
        _inspect_database(dsn, expected_postgresql_major=16)
    assert connect_calls == 0


class _FailingSqlCursor:
    def execute(self, _statement: str) -> None:
        raise RuntimeError("synthetic SQL refusal")


def test_missing_alembic_table_has_exact_revision_no_go_reason() -> None:
    with pytest.raises(RuntimeError, match="UNEXPECTED_DATABASE_REVISION"):
        _read_revisions(_FailingSqlCursor())  # type: ignore[arg-type]


def test_denied_privileged_catalog_has_exact_authority_no_go_reason() -> None:
    with pytest.raises(RuntimeError, match="BOOTSTRAP_AUTHORITY_INSUFFICIENT"):
        _read_authority_inventory(_FailingSqlCursor())  # type: ignore[arg-type]


def test_missing_required_secret_fails_before_provider_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "1" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(
        preflight_module,
        "_github_actions_state",
        lambda *_args: (0, 0, 1),
    )
    monkeypatch.delenv("NEON_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_MISSING"):
        run_preflight()


def test_second_dispatch_fails_before_secret_or_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", "1" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(
        preflight_module,
        "_github_actions_state",
        lambda *_args: (0, 0, 2),
    )

    def forbidden_provider_access(_value: str) -> object:
        raise AssertionError("provider path must remain unreachable")

    monkeypatch.setattr(
        preflight_module,
        "_validated_psycopg_url",
        forbidden_provider_access,
    )
    with pytest.raises(RuntimeError, match="RECOVERY_BRANCH_NOT_FEASIBLE"):
        run_preflight()
