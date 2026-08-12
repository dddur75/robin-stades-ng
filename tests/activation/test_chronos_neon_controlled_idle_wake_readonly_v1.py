from __future__ import annotations

import ast
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

import scripts.chronos_neon_controlled_idle_wake_readonly_v1 as controlled
import scripts.chronos_neon_pure_readonly_preflight_v4 as base
from robin.chronos_production import DirectPostgresTarget

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "chronos_neon_controlled_idle_wake_readonly_v1.py"
BASE_SCRIPT = ROOT / "scripts" / "chronos_neon_pure_readonly_preflight_v4.py"
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "chronos-neon-controlled-idle-wake-readonly-v1.yml"
)
GOLDEN = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_controlled_idle_wake_readonly_v1_golden_pack.json"
)


class _Response:
    status_code = 200

    def __init__(self, document: dict[str, Any]) -> None:
        self._document = deepcopy(document)

    def json(self) -> dict[str, Any]:
        return deepcopy(self._document)


class _IdleIdentitySession:
    def __init__(
        self,
        *,
        state: str = "idle",
        suspend_timeout_seconds: int | None = 300,
        project_id_mismatch: bool = False,
    ) -> None:
        self.state = state
        self.suspend_timeout_seconds = suspend_timeout_seconds
        self.project_id_mismatch = project_id_mismatch
        self.paths: list[str] = []

    def _endpoint(self) -> dict[str, Any]:
        endpoint: dict[str, Any] = {
            "id": "endpoint-production",
            "project_id": (
                "project-other" if self.project_id_mismatch else "project-production"
            ),
            "branch_id": "branch-production",
            "host": "ep-synthetic.neon.tech",
            "type": "read_write",
            "current_state": self.state,
            "pending_state": None,
            "pooler_enabled": False,
            "disabled": False,
            "region_id": "aws-eu-synthetic-1",
        }
        if self.suspend_timeout_seconds is not None:
            endpoint["suspend_timeout_seconds"] = self.suspend_timeout_seconds
        return endpoint

    def get(self, url: str, **_kwargs: object) -> _Response:
        parsed = urlparse(url)
        path = parsed.path.removeprefix("/api/v2")
        query = parse_qs(parsed.query)
        self.paths.append(path)
        if path == "/projects":
            assert query["limit"] == [str(base.PROJECT_PAGE_LIMIT)]
            return _Response(
                {
                    "projects": [
                        {
                            "id": "project-production",
                            "name": "production",
                            "owner_id": "owner-production",
                        }
                    ],
                    "unavailable_project_ids": [],
                }
            )
        if path == "/projects/project-production/endpoints":
            endpoint = self._endpoint()
            endpoint["project_id"] = "project-production"
            return _Response({"endpoints": [endpoint]})
        if path == "/projects/project-production/endpoints/endpoint-production":
            return _Response({"endpoint": self._endpoint()})
        if path == "/projects/project-production":
            return _Response(
                {
                    "project": {
                        "id": "project-production",
                        "name": "production",
                        "owner_id": "owner-production",
                        "region_id": "aws-eu-synthetic-1",
                        "history_retention_seconds": 86_400,
                        "owner": {"branches_limit": 5},
                    }
                }
            )
        if path == "/projects/project-production/branches":
            return _Response(
                {
                    "branches": [
                        {
                            "id": "branch-production",
                            "project_id": "project-production",
                            "name": "production",
                            "current_state": "ready",
                            "default": True,
                        }
                    ],
                    "pagination": {},
                }
            )
        if path == (
            "/projects/project-production/branches/branch-production/endpoints"
        ):
            endpoint = self._endpoint()
            endpoint["project_id"] = "project-production"
            return _Response({"endpoints": [endpoint]})
        raise AssertionError(f"unexpected route: {path}")


def _target() -> DirectPostgresTarget:
    return DirectPostgresTarget(
        host="ep-synthetic.neon.tech",
        port=5432,
        database="synthetic_database",
        username="synthetic_user",
        sslmode="require",
    )


def _neon(
    *,
    state: str = "idle",
    suspend_timeout_seconds: int = 300,
    owner_branch_count: int = 1,
    branch_limit: int = 5,
) -> base.NeonObservation:
    return base.NeonObservation(
        identity_path="POSITIVE_ENDPOINT_WITNESS",
        identity_verdict="POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN",
        project_id="project-production",
        project_name="production",
        region="aws-eu-synthetic-1",
        branch_id="branch-production",
        branch_name="production",
        branch_default=True,
        branch_parent_id=None,
        endpoint_id="endpoint-production",
        endpoint_host="ep-synthetic.neon.tech",
        endpoint_state=state,
        branch_state="ready",
        owner_branch_count=owner_branch_count,
        branch_limit=branch_limit,
        history_retention_seconds=86_400,
        project_pages_read=1,
        projects_observed=1,
        endpoint_projects_inspected=1,
        api_get_count=6,
        suspend_timeout_seconds=suspend_timeout_seconds,
        endpoint_detail_reads=1,
        project_detail_reads=1,
        branch_pages_read=1,
        branch_endpoint_reads=1,
        positive_witness_checks=(
            "EXACT_DSN_HOST_MATCH",
            "PROJECT_SCOPED_ENDPOINT_INVENTORY",
            "ENDPOINT_DETAIL_CONCORDANT",
            "PROJECT_DETAIL_CONCORDANT",
            "DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT",
            "BRANCH_ENDPOINT_CONCORDANT",
        ),
    )


def _database(
    *,
    ssl: bool = True,
    transaction_read_only: bool = True,
    revision: str = base.EXPECTED_REVISION,
    revision_count: int = 1,
    authority: bool = True,
) -> base.DatabaseObservation:
    return base.DatabaseObservation(
        database_name="synthetic_database",
        session_user="bootstrap-owner",
        current_user="bootstrap-owner",
        postgresql_version="17.0",
        ssl=ssl,
        revision=revision,
        revision_count=revision_count,
        default_transaction_read_only=transaction_read_only,
        transaction_read_only=transaction_read_only,
        statement_timeout_ms=15_000,
        lock_timeout_ms=3_000,
        lifecycle_admin_can_login=True,
        lifecycle_admin_superuser=authority,
        lifecycle_admin_createrole=authority,
        privileged_catalog_visible=authority,
        chronos_roles=(),
        chronos_memberships=(),
        chronos_objects=(),
        sql_statement_count=14,
    )


def _run_synthetic(
    monkeypatch: pytest.MonkeyPatch,
    *,
    neon: base.NeonObservation | None = None,
    database: base.DatabaseObservation | None = None,
    identity_error: base.PreflightNoGo | None = None,
    connection_error: bool = False,
) -> dict[str, Any]:
    for name, value in {
        "GITHUB_REPOSITORY": base.EXPECTED_REPOSITORY,
        "GITHUB_REF": base.EXPECTED_REF,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "1234",
        "NEON_API_KEY": "synthetic-key",
        "NEON_BOOTSTRAP_DATABASE_URL": "synthetic-dsn",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.setattr(base, "_github_actions_state", lambda *_a, **_k: (0, 0, 1))
    monkeypatch.setattr(base, "_validated_psycopg_url", lambda _dsn: (_dsn, _target()))
    monkeypatch.setattr(
        base,
        "_target_dsn_security_profile",
        lambda _target: {
            "contract_verdict": "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"
        },
    )
    monkeypatch.setattr(base, "NeonReadOnlyClient", lambda _key: object())

    def resolve(*_args: object, **_kwargs: object) -> base.NeonObservation:
        if identity_error is not None:
            raise identity_error
        return neon or _neon()

    calls = 0

    def inspect(
        _dsn: str,
        *,
        before_connect: Any = None,
        after_connect: Any = None,
    ) -> base.DatabaseObservation:
        nonlocal calls
        calls += 1
        assert calls == 1
        before_connect()
        if connection_error:
            raise base.PreflightNoGo(
                "DIRECT_ENDPOINT_NOT_PROVEN",
                "postgresql_readonly_inspection_failed",
            )
        after_connect()
        return database or _database()

    monkeypatch.setattr(base, "_resolve_neon_identity", resolve)
    monkeypatch.setattr(base, "_inspect_database", inspect)
    return controlled.run_preflight()


def test_workflow_is_one_shot_bounded_and_environment_protected() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = document.get("on", document.get(True))
    assert set(on) == {"workflow_dispatch"}
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"]["cancel-in-progress"] is False
    job = document["jobs"]["preflight"]
    assert job["environment"] == "chronos-control-plane-production"
    live = next(step for step in job["steps"] if "run" in step and "timeout" in step["run"])
    assert "timeout --signal=TERM 120s" in live["run"]
    assert "NEON_PROJECT_ID" in live["env"]


def test_idle_endpoint_completes_identity_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _IdleIdentitySession()
    client = base.NeonReadOnlyClient("synthetic", session=session)  # type: ignore[arg-type]
    observed = base._resolve_neon_identity(client, _target(), allow_idle=True)
    assert observed.identity_verdict == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
    assert observed.endpoint_state == "idle"
    assert observed.suspend_timeout_seconds == 300
    assert session.paths == [
        "/projects",
        "/projects/project-production/endpoints",
        "/projects/project-production/endpoints/endpoint-production",
        "/projects/project-production",
        "/projects/project-production/branches",
        "/projects/project-production/branches/branch-production/endpoints",
    ]


def test_identity_failure_prevents_connection_and_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(
        monkeypatch,
        identity_error=base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_detail_id_or_owner_mismatch"
        ),
    )
    assert report["connection_attempt_count"] == 0
    assert report["compute_wake_events"] == 0
    assert report["failed_gate"] == "project_detail_id_or_owner_mismatch"


def test_idle_connection_is_attempted_once_and_counted_as_one_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    assert report["connection_attempt_count"] == 1
    assert report["compute_wake_events"] == 1
    assert report["lifecycle"]["identity_complete_before_wake"] is True
    assert report["lifecycle"]["wake_verdict"] == (
        "CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE"
    )


def test_active_endpoint_requires_no_wake(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _run_synthetic(monkeypatch, neon=_neon(state="active"))
    assert report["connection_attempt_count"] == 1
    assert report["compute_wake_events"] == 0
    assert report["lifecycle"]["wake_verdict"] == (
        "CONTROLLED_NEON_READONLY_WAKE_NOT_REQUIRED"
    )


def test_connection_failure_is_not_retried_and_wake_is_conservatively_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch, connection_error=True)
    assert report["connection_attempt_count"] == 1
    assert report["compute_wake_events"] == 1
    assert report["lifecycle"]["compute_wake_events"] == 1
    assert report["lifecycle"]["wake_verdict"] == (
        "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
    )
    assert report["reason"] == "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
    assert report["failed_gate"] == "single_connection_attempt_did_not_complete"


def test_active_connection_failure_does_not_invent_a_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(
        monkeypatch,
        neon=_neon(state="active"),
        connection_error=True,
    )
    assert report["connection_attempt_count"] == 1
    assert report["compute_wake_events"] == 0
    assert report["reason"] == "DIRECT_ENDPOINT_NOT_PROVEN"
    assert report["failed_gate"] == "postgresql_readonly_inspection_failed"


@pytest.mark.parametrize(
    ("timeout", "classification", "effective"),
    [(300, "FINITE_SCALE_TO_ZERO", 300), (0, "DEFAULT_SCALE_TO_ZERO", 300)],
)
def test_scale_to_zero_finite_and_default_contracts(
    timeout: int,
    classification: str,
    effective: int,
) -> None:
    assert controlled._scale_to_zero_contract(
        _neon(suspend_timeout_seconds=timeout)
    ) == (classification, effective)


@pytest.mark.parametrize("timeout", [-1, 60, 119])
def test_scale_to_zero_refuses_always_active_or_too_short(timeout: int) -> None:
    with pytest.raises(base.PreflightNoGo) as caught:
        controlled._scale_to_zero_contract(_neon(suspend_timeout_seconds=timeout))
    assert caught.value.reason == "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN"


def test_unknown_endpoint_state_and_missing_suspend_contract_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    for session, expected in (
        (_IdleIdentitySession(state="init"), "endpoint_state_unsupported"),
        (_IdleIdentitySession(suspend_timeout_seconds=None), "suspend_timeout_contract_invalid"),
    ):
        client = base.NeonReadOnlyClient("synthetic", session=session)  # type: ignore[arg-type]
        with pytest.raises(base.PreflightNoGo) as caught:
            base._resolve_neon_identity(client, _target(), allow_idle=True)
        assert caught.value.gate == expected


def test_readonly_startup_options_and_first_sql_are_hard_contracts() -> None:
    controlled._validate_readonly_connection_contract(
        base.READONLY_STARTUP_OPTIONS, base.SQL_STATEMENTS
    )
    with pytest.raises(base.PreflightNoGo) as missing:
        controlled._validate_readonly_connection_contract(
            "-c statement_timeout=15000 -c lock_timeout=3000",
            base.SQL_STATEMENTS,
        )
    assert missing.value.gate == "startup_options_required"
    with pytest.raises(base.PreflightNoGo) as first:
        controlled._validate_readonly_connection_contract(
            base.READONLY_STARTUP_OPTIONS,
            ("SELECT 1", "ROLLBACK"),
        )
    assert first.value.gate == "first_sql_not_begin_read_only"


@pytest.mark.parametrize(
    ("database", "expected_gate"),
    [
        (_database(transaction_read_only=False), "direct_endpoint_not_proven"),
        (_database(ssl=False), "ssl_not_proven"),
        (_database(revision="0014_chronos_control_plane_v2"), "unexpected_database_revision"),
        (_database(revision="NOT_SINGLETON", revision_count=2), "unexpected_database_revision"),
        (_database(authority=False), "bootstrap_authority_insufficient"),
    ],
)
def test_database_no_go_gates_are_exact(
    monkeypatch: pytest.MonkeyPatch,
    database: base.DatabaseObservation,
    expected_gate: str,
) -> None:
    report = _run_synthetic(monkeypatch, database=database)
    assert report["verdict"] == base.NO_GO_VERDICT
    assert report["failed_gate"] == expected_gate
    assert report["effects"]["production_sql_writes"] == 0


def test_recovery_and_purchase_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    ready = _run_synthetic(monkeypatch)
    assert ready["verdict"] == base.GO_VERDICT
    assert ready["bootstrap_authority_verdict"] == (
        "BOOTSTRAP_AUTHORITY_CAPABILITIES_PROVEN"
    )
    assert ready["recovery_verdict"] == "NEON_RECOVERY_BRANCH_CREATION_FEASIBLE"
    assert ready["postgresql"]["current_revision"] == base.EXPECTED_REVISION
    assert ready["postgresql"]["revision_count"] == 1


def test_purchase_required_remains_no_go(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _run_synthetic(
        monkeypatch,
        neon=_neon(owner_branch_count=5, branch_limit=5),
    )
    assert report["failed_gate"] == "purchase_required"
    assert report["recovery_verdict"] == "PURCHASE_REQUIRED"
    assert report["effects"]["purchases"] == 0


def test_neon_client_and_controlled_script_have_no_mutating_api_call() -> None:
    tree = ast.parse(BASE_SCRIPT.read_text(encoding="utf-8"))
    client = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NeonReadOnlyClient"
    )
    public_methods = {
        node.name
        for node in client.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_methods == {"require_get_budget", "get"}
    controlled_source = SCRIPT.read_text(encoding="utf-8").lower()
    workflow_source = WORKFLOW.read_text(encoding="utf-8").lower()
    for forbidden in ("/start", "/restart", "/suspend"):
        assert forbidden not in controlled_source
        assert forbidden not in workflow_source


def test_report_retains_nine_zero_effects_plus_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    effects = report["effects"]
    assert set(effects) == {
        "neon_mutations",
        "production_sql_writes",
        "recovery_branch_creations",
        "role_creations",
        "migration_0014",
        "r2_operations",
        "provider_calls",
        "purchases",
        "sensitive_values_exposed",
        "compute_wake_events",
    }
    assert effects["compute_wake_events"] == 1
    assert all(value == 0 for key, value in effects.items() if key != "compute_wake_events")


def test_golden_pack_has_all_required_scenarios() -> None:
    document = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert document["schema_version"] == (
        "chronos-neon-controlled-idle-wake-readonly-v1-golden-pack"
    )
    assert {case["case_id"] for case in document["cases"]} == {
        "IDENTITY_COMPLETE_ENDPOINT_ACTIVE",
        "IDENTITY_COMPLETE_ENDPOINT_IDLE",
        "IDLE_FINITE_SCALE_TO_ZERO",
        "IDLE_DEFAULT_SCALE_TO_ZERO",
        "IDLE_ALWAYS_ACTIVE_CONFIGURATION",
        "IDLE_SCALE_TO_ZERO_UNKNOWN",
        "IDLE_CONNECTION_WAKE_SUCCESS",
        "IDLE_CONNECTION_WAKE_FAILURE_NO_RETRY",
        "READ_ONLY_STARTUP_OPTIONS_MISSING",
        "FIRST_SQL_NOT_BEGIN_READ_ONLY",
        "TRANSACTION_READ_ONLY_FALSE",
        "SSL_FALSE",
        "EXPECTED_REVISION_0013",
        "UNEXPECTED_REVISION_0014",
        "MULTIPLE_ALEMBIC_REVISIONS",
        "BOOTSTRAP_AUTHORITY_SUFFICIENT",
        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        "RECOVERY_FEASIBLE",
        "PURCHASE_REQUIRED",
    }


def _raise(error: base.PreflightNoGo) -> NoReturn:
    raise error
