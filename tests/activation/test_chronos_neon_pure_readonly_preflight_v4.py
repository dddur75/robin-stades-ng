from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

import scripts.chronos_neon_pure_readonly_preflight_v4 as preflight_module
from robin.chronos_production import DirectPostgresTarget
from scripts.chronos_neon_pure_readonly_preflight_v4 import (
    GO_VERDICT,
    MAX_NEON_GETS,
    MAX_SQL_STATEMENTS,
    NO_GO_REASONS,
    NO_GO_VERDICT,
    SQL_STATEMENTS,
    GateChecks,
    NeonObservation,
    NeonReadOnlyClient,
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
    assert document["schema_version"] == (
        "chronos-neon-pure-readonly-preflight-v4-golden-pack"
    )
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
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == {
        "group": "chronos-neon-pure-readonly-preflight-v4",
        "cancel-in-progress": False,
    }
    job = document["jobs"]["preflight"]
    assert job["environment"] == "chronos-control-plane-production"
    assert job["timeout-minutes"] == 15
    setup = next(step for step in job["steps"] if "actions/setup-python@" in step.get("uses", ""))
    assert setup["with"]["python-version"] == "3.12.10"
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
    assert "GITHUB_TOKEN" not in serialized


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
    allowed_leaders = {"BEGIN", "SHOW", "SELECT", "ROLLBACK"}
    for statement in SQL_STATEMENTS:
        tokens = set(re.findall(r"\b[A-Z_]+\b", statement.upper()))
        assert statement.split(maxsplit=1)[0].upper() in allowed_leaders
        assert not (FORBIDDEN_SQL & tokens)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in source
    assert "statement_timeout=15000" in source
    assert "lock_timeout=3000" in source
    assert "sql_write_count\": 0" in source
    assert "ORDER BY version_num" in SQL_STATEMENTS[7]
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

    def json(self) -> dict[str, object]:
        return {}


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

    def get(self, path: str) -> dict[str, Any]:
        self.get_count += 1
        if path == "/projects?limit=12":
            return cast(dict[str, Any], self.fixture["projects"])
        if path == "/projects/synthetic-project":
            return cast(dict[str, Any], self.fixture["project_detail"])
        if path == "/projects/synthetic-project/branches?limit=10000":
            return cast(dict[str, Any], self.fixture["branches"])
        if path == "/projects/synthetic-project/endpoints":
            return cast(dict[str, Any], self.fixture["endpoints"])
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
    assert client.get_count == 4


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("pagination", {"next": "another-page"}, "RECOVERY_BRANCH_NOT_FEASIBLE"),
        ("pagination", "malformed", "RECOVERY_BRANCH_NOT_FEASIBLE"),
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


def test_sanitized_neon_observation_hashes_branch_name() -> None:
    sentinel = "provider-branch-name-must-not-leak"
    observed = NeonObservation(
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
        owner_branch_count=1,
        branch_limit=5,
        history_retention_seconds=1,
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
