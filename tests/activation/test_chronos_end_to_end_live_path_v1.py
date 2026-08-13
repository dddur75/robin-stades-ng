from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

import robin.chronos_production as production_contract
import scripts.chronos_live_path_artifact_guard_v1 as guard
import scripts.chronos_neon_controlled_idle_wake_readonly_v1 as controlled
import scripts.chronos_neon_pure_readonly_preflight_v4 as base
from robin.chronos_production import libpq_environment_variable_names
from scripts.chronos_live_path_artifact_guard_v1 import (
    _MAX_REPORT_BYTES,
    NO_GO_VERDICT,
    _valid_report,
    ensure_artifact,
)
from scripts.chronos_live_path_artifact_guard_v1 import (
    _validated_direct_postgres_url as guard_validated_direct_postgres_url,
)
from tests.activation.test_chronos_neon_controlled_idle_wake_readonly_v1 import (
    _database,
    _IdleIdentitySession,
    _neon,
    _run_synthetic,
)
from tests.activation.test_chronos_neon_pure_readonly_preflight_v4 import (
    _branch,
    _client,
    _detail,
    _endpoint,
    _positive_witness_session,
    _project_page,
    _ScriptedNeonSession,
    _synthetic_target,
)

ROOT = Path(__file__).resolve().parents[2]
LIVE_STRUCTURES = (
    ROOT
    / "tests"
    / "activation"
    / "fixtures"
    / "chronos_neon_live_contract_structures_v1.json"
)
DSN = (
    "postgresql://synthetic_user:synthetic_password@"
    "ep-synthetic.neon.tech/synthetic_database?"
    "sslmode=require&channel_binding=require"
)
_REAL_NEON_READONLY_CLIENT = base.NeonReadOnlyClient


def test_loop53_mission_governance_is_exact_and_triple_keyed() -> None:
    manifest = json.loads(
        (
            ROOT
            / "configs"
            / "execution"
            / "chronos-residual-defect-extermination-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert set(manifest) == {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    assert manifest["mission_id"] == "CHRONOS_LOOP53"
    assert manifest["authorized_stages"] == ["E1", "E2", "E3A", "E3B", "E4"]
    assert manifest["maximum_stage"] == "E4"
    assert manifest["source_hash"] == (
        "5f40475be65fa358a2b409edb2f320993596124e2055a1b5056e8641db0ab498"
    )

    matrix = json.loads(
        (ROOT / "configs" / "agents" / "mission-activation-matrix-v3.json").read_text(
            encoding="utf-8"
        )
    )
    mission = matrix["missions"]["CHRONOS_LOOP53"]
    assert mission["writer"] == "C0"
    assert set(mission["agents"]) == {"C0", "C4", "DP5", "DP6"}
    assert mission["delivery_keys"] == {
        "platform": ["DP5"],
        "data": ["DP6"],
        "security": ["C4"],
    }
    dispatch_authority = matrix["authorization"]["chronos_loop53_dispatch"]
    assert "EXACTLY_ONE_NEW_ATTEMPT_ONE_DISPATCH" in dispatch_authority
    assert "CHRONOS_NEON_CONTROLLED_IDLE_WAKE_READONLY_V1" in dispatch_authority
    assert "GREEN_MERGED_MAIN_PAGES_QUIESCENCE" in dispatch_authority
    assert "FORBID_RERUN_31587004959" in dispatch_authority
    assert (
        "FORBID_SECOND_DISPATCH_6140e09cb38b5fecee5da85882aa8a879dbce780"
        in dispatch_authority
    )
    assert "CHRONOS_LOOP53_MAXIMUM_25_NEON_GETS_ZERO_MUTATIONS" in matrix[
        "authorization"
    ]["provider_calls"]
    delivery_authority = matrix["authorization"]["chronos_loop53_delivery"]
    assert "CHRONOS_RESIDUAL_DEFECT_EXTERMINATION_V1" in delivery_authority
    assert "DP5_DP6_C4_P0_ZERO_P1_ZERO_SCORE_AT_LEAST_95" in delivery_authority
    assert "MERGE_COMMIT_ONLY" in delivery_authority
    assert "FORBID_SQUASH_REBASE_FORCE_PUSH_AND_BRANCH_DELETE" in delivery_authority

    schema = json.loads(
        (ROOT / "configs" / "agents" / "agent-report-schema-v3.json").read_text(
            encoding="utf-8"
        )
    )
    assert "CHRONOS_LOOP53" in schema["properties"]["mission_id"]["enum"]

    inventory = json.loads(
        (
            ROOT
            / "reports"
            / "activation"
            / "chronos-residual-defect-inventory-v1.json"
        ).read_text(encoding="utf-8")
    )
    defects = inventory["defects"]
    assert inventory["counts"]["discovered"] == len(defects)
    assert inventory["counts"]["fixed"] == sum(
        defect["status"] == "FIXED" for defect in defects
    )
    assert inventory["counts"]["known_live_reachable_defects"] == 0
    assert inventory["counts"]["known_untested_live_path_stages"] == 0

    certification = json.loads(
        (
            ROOT
            / "reports"
            / "activation"
            / "chronos-end-to-end-live-path-certification-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert certification["claim_id"] != inventory["claim_id"]
    assert certification["inventory_claim_id"] == inventory["claim_id"]
    assert certification["quality_gates"] == {
        "known_live_reachable_defects": 0,
        "known_untested_live_path_stages": 0,
        "defects_intentionally_deferred": 0,
        "open_p0": 0,
        "open_p1": 0,
    }


def test_sanitized_live_contract_fixture_never_claims_unobserved_raw_shape() -> None:
    fixture = json.loads(LIVE_STRUCTURES.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "chronos-neon-live-contract-structures-v1"
    privacy = fixture["privacy_contract"]
    assert not any(
        privacy[key]
        for key in (
            "raw_api_keys",
            "raw_dsns",
            "raw_hostnames",
            "raw_cursors",
            "raw_project_branch_endpoint_ids",
        )
    )
    live = next(
        item
        for item in fixture["fixtures"]
        if item["classification"] == "LIVE_SANITIZED"
    )
    assert live["source_run"] == 31587004959
    assert live["unknown_raw_envelope_preserved"] is False
    assert "pagination_shape" not in live
    serialized = json.dumps(fixture)
    assert "postgresql://" not in serialized
    assert ".neon.tech" not in serialized


def test_branch_pagination_accepts_terminal_legacy_and_additive_metadata() -> None:
    audit = base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS")
    assert base._branch_page_cursor({}, audit) is None
    assert base._branch_page_cursor({"pagination": {}}, audit) is None
    assert base._branch_page_cursor({"pagination": {"next": None}}, audit) is None
    assert (
        base._branch_page_cursor(
            {
                "pagination": {
                    "previous": None,
                    "next": "opaque-next",
                    "sort_by": "updated_at",
                    "sort_order": "asc",
                    "request_id": "benign-structural-metadata",
                }
            },
            audit,
        )
        == "opaque-next"
    )


@pytest.mark.parametrize(
    "pagination",
    [
        {"next": ""},
        {"next": 3},
        {"next": "opaque", "cursor": "conflict"},
        {"next": "opaque", "has_more": False},
        {"next": "opaque", "is_truncated": True},
        {"previous": ""},
        {"previous": "opaque-previous", "next": "opaque-next"},
        {"sort_by": "created_at"},
        {"sort_order": "desc"},
    ],
)
def test_branch_pagination_refuses_ambiguous_semantics(
    pagination: dict[str, object],
) -> None:
    with pytest.raises(base.PreflightNoGo) as caught:
        base._branch_page_cursor(
            {"pagination": pagination}, base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS")
        )
    assert caught.value.gate == "branch_inventory_truncated"


def test_branch_pagination_cycle_is_recorded_without_cursor_exposure() -> None:
    audit = base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS")
    document = {"pagination": {"next": "opaque-cycle"}}
    assert base._branch_page_cursor(document, audit) == "opaque-cycle"
    with pytest.raises(base.PreflightNoGo):
        base._branch_page_cursor(document, audit)
    assert audit.cursor_cycle_encountered is True
    assert "opaque-cycle" not in json.dumps(audit.sanitized(api_get_count=2))


def test_project_pagination_is_forward_compatible_but_semantically_strict() -> None:
    assert (
        base._project_page_cursor(
            {"pagination": {"cursor": "opaque", "request_id": "benign"}}
        )
        == "opaque"
    )


@pytest.mark.parametrize(
    ("document", "parser", "expected_gate"),
    [
        (
            {"projects": [], "links": {"next": "opaque"}},
            "project",
            "project_pagination_invalid",
        ),
        (
            {"branches": [], "metadata": {"has_more": True}},
            "branch",
            "branch_inventory_truncated",
        ),
        (
            {"endpoints": [], "links": {"continuation": "opaque"}},
            "endpoint",
            "endpoint_inventory_pagination_ambiguous",
        ),
    ],
)
def test_nested_unknown_continuation_semantics_fail_closed(
    document: dict[str, object],
    parser: str,
    expected_gate: str,
) -> None:
    with pytest.raises(base.PreflightNoGo) as caught:
        if parser == "project":
            base._project_page_cursor(document)
        elif parser == "branch":
            base._branch_page_cursor(
                document,
                base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS"),
            )
        else:
            base._project_endpoints(document, "project-a", gate="endpoint-invalid")
    assert caught.value.gate == expected_gate


def test_nested_unknown_metadata_without_continuation_semantics_is_accepted() -> None:
    assert (
        base._project_page_cursor(
            {"projects": [], "metadata": {"request_id": "synthetic"}}
        )
        is None
    )
    for pagination in (
        {},
        {"cursor": None},
        {"cursor": ""},
        {"cursor": "opaque", "next": "conflict"},
    ):
        with pytest.raises(base.PreflightNoGo):
            base._project_page_cursor({"pagination": pagination})


@pytest.mark.parametrize(
    "document",
    [
        {"PAGINATION": {"cursor": "opaque"}},
        {"pagination": {"CURSOR": "opaque"}},
        {"pagination": {"PAGINATION": {"cursor": "opaque"}}},
    ],
)
def test_project_pagination_casing_cannot_hide_continuation(
    document: dict[str, object],
) -> None:
    with pytest.raises(base.PreflightNoGo) as caught:
        base._project_page_cursor(document)
    assert caught.value.gate == "project_pagination_invalid"


@pytest.mark.parametrize(
    "document",
    [
        {"branches": [], "PAGINATION": {"next": "opaque"}},
        {"pagination": {"NEXT": "opaque"}},
        {"pagination": {"PAGINATION": {"next": "opaque"}}},
    ],
)
def test_branch_pagination_casing_cannot_hide_continuation(
    document: dict[str, object],
) -> None:
    with pytest.raises(base.PreflightNoGo) as caught:
        base._branch_page_cursor(
            document,
            base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS"),
        )
    assert caught.value.gate == "branch_inventory_truncated"


def test_documented_resource_maps_do_not_turn_identity_names_into_pagination() -> None:
    project_id = "next-generation-12345678"
    branch_id = "br-blinking-sun-12345678"
    assert base._project_page_cursor(
        {
            "projects": [],
            "unavailable_project_ids": [],
            "applications": {project_id: ["vercel"]},
            "integrations": {project_id: []},
        }
    ) is None
    assert base._branch_page_cursor(
        {
            "branches": [],
            "annotations": {branch_id: {}},
        },
        base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS"),
    ) is None


def test_endpoint_inventory_rejects_duplicates_and_undocumented_pagination() -> None:
    endpoint = _endpoint("project-a")
    duplicate = deepcopy(endpoint)
    duplicate["host"] = "ep-other.neon.tech"
    for document in (
        {"endpoints": [endpoint, duplicate]},
        {"endpoints": [endpoint], "pagination": {"next": "opaque"}},
    ):
        with pytest.raises(base.PreflightNoGo):
            base._project_endpoints(document, "project-a", gate="endpoint_fault")


def test_branch_endpoint_inventory_rejects_any_foreign_branch_member() -> None:
    target = _endpoint("project-a")
    foreign = deepcopy(target)
    foreign["id"] = "endpoint-foreign"
    foreign["branch_id"] = "branch-other"
    with pytest.raises(base.PreflightNoGo) as caught:
        base._project_endpoints(
            {"endpoints": [target, foreign]},
            "project-a",
            expected_branch_id=str(target["branch_id"]),
            gate="branch_endpoint_confirmation_mismatch",
        )
    assert caught.value.gate == "branch_endpoint_confirmation_mismatch"


@pytest.mark.parametrize(
    "branches",
    [
        [_branch(project_id="project-a"), _branch(branch_id="branch-two", project_id="project-a")],
        [_branch(project_id="project-other")],
        [{**_branch(project_id="project-a"), "default": "false"}],
        [{key: value for key, value in _branch(project_id="project-a").items() if key != "current_state"}],
    ],
)
def test_branch_inventory_rejects_identity_and_type_contradictions(
    branches: list[dict[str, Any]],
) -> None:
    session = _ScriptedNeonSession(
        branches={"project-a": [{"branches": branches, "pagination": {}}]}
    )
    with pytest.raises(base.PreflightNoGo):
        base._list_branches_bounded(
            _client(session),
            "project-a",
            base.IdentityAudit("POSITIVE_ENDPOINT_WITNESS"),
            reserve_after=0,
        )


def test_endpoint_transition_and_json_coercions_fail_closed() -> None:
    candidate = _endpoint("project-a")
    detail = deepcopy(candidate)
    detail["pending_state"] = "active"
    with pytest.raises(base.PreflightNoGo) as transitioning:
        base._endpoint_detail(
            {"endpoint": detail},
            project_id="project-a",
            candidate=candidate,
            target=_synthetic_target(),
        )
    assert transitioning.value.gate == "endpoint_detail_transitioning"
    with pytest.raises(base.PreflightNoGo):
        base._bounded_int(
            "5",
            minimum=1,
            reason="RECOVERY_BRANCH_NOT_FEASIBLE",
            gate="numeric_string_forbidden",
        )
    with pytest.raises(base.PreflightNoGo):
        base._safe_identifier(7)


def test_deprecated_pooler_flag_does_not_override_canonical_direct_hostname() -> None:
    endpoint = _endpoint("project-a")
    endpoint["pooler_enabled"] = True
    assert base._positive_endpoint_candidate(
        endpoint, project_id="project-a", target=_synthetic_target()
    )
    assert base._is_pooler_host("ep-synthetic-pooler.eu.neon.tech")
    assert not base._is_pooler_host("ep-pooler-word-but-direct.eu.neon.tech")


def test_first_page_match_does_not_hide_later_duplicate_target() -> None:
    session = _ScriptedNeonSession(
        project_pages=[
            _project_page(["project-a"], cursor="follow-me"),
            _project_page(["project-b"]),
        ],
        endpoints={
            "project-a": {"endpoints": [_endpoint("project-a")]},
            "project-b": {"endpoints": [_endpoint("project-b", endpoint_id="endpoint-two")]},
        },
    )
    audit = base.IdentityAudit(
        "POSITIVE_ENDPOINT_WITNESS",
        owner_id="owner-shared",
        owner_scope_proven=True,
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        base._progressive_positive_candidate(_client(session), _synthetic_target(), audit)
    assert caught.value.gate == "positive_endpoint_match_not_unique"
    assert session.project_page_index == 2


def test_multiple_projects_prove_owner_wide_recovery_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    neon = base._resolve_neon_identity(
        _client(_positive_witness_session("FIRST_PAGE_MULTIPLE_PROJECTS_ONE_EXACT_MATCH")),
        _synthetic_target(),
    )
    assert neon.project_inventory_exhaustive is True
    assert neon.branch_capacity_proven is True
    report = _run_synthetic(monkeypatch, neon=neon)
    assert report["verdict"] == base.GO_VERDICT
    assert report["connection_attempt_count"] == 1
    assert report["compute_wake_events"] == 1


def _capacity_boundary_session(
    project_count: int,
    *,
    personal_admin: bool,
) -> _ScriptedNeonSession:
    project_ids = ["project-a"] + [
        f"project-{index}" for index in range(2, project_count + 1)
    ]
    details = {project_id: _detail(project_id) for project_id in project_ids}
    branches = {
        project_id: [
            {
                "branches": [_branch(project_id=project_id)],
                "pagination": {},
            }
        ]
        for project_id in project_ids
    }
    endpoints = {
        project_id: {
            "endpoints": [
                _endpoint(
                    project_id,
                    endpoint_id=f"endpoint-{index}",
                    host=(
                        "ep-synthetic.neon.tech"
                        if project_id == "project-a"
                        else f"ep-other-{index}.neon.tech"
                    ),
                )
            ]
        }
        for index, project_id in enumerate(project_ids, start=1)
    }
    session = _ScriptedNeonSession(
        project_pages=[_project_page(project_ids)],
        details=details,
        branches=branches,
        endpoints=endpoints,
        endpoint_details={
            project_id: {"endpoint": deepcopy(document["endpoints"][0])}
            for project_id, document in endpoints.items()
        },
        branch_endpoints=deepcopy(endpoints),
    )
    if personal_admin:
        session.auth_method = "api_key_user"
        session.account_id = "opaque-user-account"
    return session


@pytest.mark.parametrize(
    ("personal_admin", "accepted_projects", "rejected_projects"),
    [(False, 7, 8), (True, 6, 7)],
)
def test_project_discovery_budget_boundaries_never_exceed_twenty_five_gets(
    monkeypatch: pytest.MonkeyPatch,
    personal_admin: bool,
    accepted_projects: int,
    rejected_projects: int,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEON_ORG_ID", raising=False)
    accepted_session = _capacity_boundary_session(
        accepted_projects,
        personal_admin=personal_admin,
    )
    observation = base._resolve_neon_identity(
        _client(accepted_session),
        _synthetic_target(),
    )
    assert observation.api_get_count == 21
    assert observation.branch_count_reads == accepted_projects

    rejected_session = _capacity_boundary_session(
        rejected_projects,
        personal_admin=personal_admin,
    )
    client = _client(rejected_session)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(client, _synthetic_target())
    assert caught.value.gate == "project_identity_discovery_budget_exceeded"
    assert client.get_count <= base.MAX_NEON_GETS


def test_authoritative_branch_count_must_match_exhaustive_target_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.branch_count_overrides["project-a"] = 2
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "branch_count_inventory_contradiction"


def test_production_branch_with_a_parent_fails_before_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.branches["project-a"][0]["branches"][0]["parent_id"] = (
        "unexpected-parent"
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.reason == "NEON_PRODUCTION_BRANCH_AMBIGUOUS"
    assert caught.value.gate == "production_branch_parent_unexpected"


def test_personal_admin_scope_proves_selected_organization_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    opaque_owner = "opaque:user@example.invalid:0123456789"
    session = _positive_witness_session("FIRST_PAGE_MULTIPLE_PROJECTS_ONE_EXACT_MATCH")
    session.account_id = opaque_owner
    session.auth_method = "api_key_user"
    session.account_branch_limit = 20
    session.user_organization_id = "org-personal"
    session.user_organization_ids = ["org-personal"]
    for project in session.project_pages[0]["projects"]:
        project["org_id"] = "org-personal"
        project["owner_id"] = (
            "org-personal" if project["id"] == "project-b" else "shared:foreign@owner"
        )
    session.details["project-b"]["project"]["org_id"] = "org-personal"
    session.details["project-b"]["project"]["owner_id"] = "org-personal"
    observed = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN"
    assert observed.branch_capacity_proven is True
    assert observed.projects_observed == 3
    assert observed.endpoint_projects_inspected == 3
    project_url = next(url for url in session.urls if "/projects?" in url)
    assert "org_id=org-personal" in project_url


def test_personal_multi_organization_key_requires_and_binds_explicit_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.user_organization_count = 2
    session.user_organization_ids = ["owner-shared", "owner-other"]

    with pytest.raises(base.PreflightNoGo) as ambiguous:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert ambiguous.value.gate == "user_organization_scope_ambiguous"

    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.user_organization_count = 2
    session.user_organization_ids = ["owner-shared", "owner-other"]
    monkeypatch.setenv("NEON_ORG_ID", "owner-shared")
    observed = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.owner_id == "owner-shared"
    assert observed.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN"
    assert any("org_id=owner-shared" in url for url in session.urls)


def test_explicit_organization_scope_mismatch_fails_before_project_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.setenv("NEON_ORG_ID", "owner-not-accessible")
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.user_organization_count = 2
    session.user_organization_ids = ["owner-shared", "owner-other"]
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "configured_organization_scope_mismatch"
    assert not any("/projects?" in url for url in session.urls)


def test_positive_witness_rejects_project_owner_org_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session(
        "FIRST_PAGE_ONE_PROJECT_EXACT_ENDPOINT_MATCH"
    )
    session.project_pages[0]["projects"][0]["org_id"] = "owner-other"
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "project_inventory_incomplete"
    assert session.paths == ["/auth", "/organizations/owner-shared", "/projects"]


@pytest.mark.parametrize("role", ["member", "editor", "viewer", "collaborator"])
def test_personal_non_admin_scope_never_claims_owner_wide_capacity(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.user_organization_role = role
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "personal_api_key_owner_capacity_unproven"
    assert not any("/projects?" in url for url in session.urls)


def test_personal_admin_membership_witness_need_not_exhaust_unrelated_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEON_ORG_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.member_pagination_next = "more-unrelated-members"
    observed = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN"
    assert sum("/members?" in url for url in session.urls) == 1

    missing = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    missing.auth_method = "api_key_user"
    missing.member_pagination_next = "more-unrelated-members"
    missing.member_contains_self = False
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(missing), _synthetic_target())
    assert caught.value.gate == "personal_api_key_owner_capacity_unproven"


def test_personal_admin_membership_witness_follows_a_bounded_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEON_ORG_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.auth_method = "api_key_user"
    session.member_contains_self = False
    session.member_pagination_next = "second-member-page"
    session.member_second_page_contains_self = True
    observed = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.owner_scope_verdict == "PERSONAL_ADMIN_ORGANIZATION_PROVEN"
    assert sum("/members?" in url for url in session.urls) == 2
    assert observed.api_get_count <= base.MAX_NEON_GETS
    assert _valid_report(_run_synthetic(monkeypatch, neon=observed)) is True


def test_project_scoped_organization_key_cannot_prove_recovery_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.organization_status = 403
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "project_scoped_api_key_owner_capacity_unproven"
    assert not any("/projects?" in url for url in session.urls)


@pytest.mark.parametrize("postgresql_major", [17, 18])
def test_neon_postgresql_major_without_chronos_certification_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    postgresql_major: int,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.details["project-a"]["project"]["pg_version"] = postgresql_major
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "chronos_postgresql_version_not_certified"


def test_launch_branch_allowance_blocks_purchase_before_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.branches["project-a"][0]["branches"] = [
        _branch(
            branch_id=("branch-production" if index == 0 else f"branch-{index}"),
            project_id="project-a",
            default=index == 0,
        )
        for index in range(10)
    ]
    neon = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert neon.target_project_branch_count == 10
    assert neon.branch_capacity_proven is True
    assert neon.bill_free_branch_capacity_proven is False
    report = _run_synthetic(monkeypatch, neon=neon)
    assert report["verdict"] == base.NO_GO_VERDICT
    assert report["failed_gate"] == "purchase_required"
    assert report["purchase_required"] is True
    assert report["connection_attempt_count"] == 0
    assert report["effects"]["postgresql_connection_attempts"] == 0


@pytest.mark.parametrize(
    ("billing_plan", "subscription_type", "branch_count", "bill_free"),
    [
        ("free", "UNKNOWN", 9, True),
        ("free", "UNKNOWN", 10, False),
        ("launch", "launch", 9, True),
        ("launch", "launch", 10, False),
        ("scale", "scale", 24, True),
        ("scale", "scale", 25, False),
    ],
)
def test_authoritative_billing_plan_proves_branch_allowance_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    billing_plan: str,
    subscription_type: str,
    branch_count: int,
    bill_free: bool,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.account_plan = billing_plan
    session.details["project-a"]["project"]["owner"].update(
        {"branches_limit": 100, "subscription_type": subscription_type}
    )
    session.branches["project-a"][0]["branches"] = [
        _branch(
            branch_id=("branch-production" if index == 0 else f"branch-{index}"),
            project_id="project-a",
            default=index == 0,
        )
        for index in range(branch_count)
    ]
    observed = base._resolve_neon_identity(_client(session), _synthetic_target())
    assert observed.billing_plan == billing_plan
    assert observed.subscription_type == subscription_type
    assert observed.target_project_branch_count == branch_count
    assert observed.bill_free_branch_capacity_proven is bill_free


def test_billing_plan_and_subscription_contradiction_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.account_plan = "free"
    session.details["project-a"]["project"]["owner"]["subscription_type"] = "scale"
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "billing_plan_subscription_contradiction"


@pytest.mark.parametrize("billing_plan", ["UNKNOWN", "business", "direct_sales"])
def test_unknown_billing_plan_never_claims_purchase_free_capacity(
    monkeypatch: pytest.MonkeyPatch,
    billing_plan: str,
) -> None:
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    session = _positive_witness_session("DISCOVERY_UNIQUE_ENDPOINT_MATCH")
    session.account_plan = billing_plan
    with pytest.raises(base.PreflightNoGo) as caught:
        base._resolve_neon_identity(_client(session), _synthetic_target())
    assert caught.value.gate == "purchase_requirement_ambiguous"


@pytest.mark.parametrize("maximum_cu", [16.25, 32.0, 56.0, 1_000_001.0])
def test_scale_to_zero_is_independent_of_finite_maximum_compute(
    maximum_cu: float,
) -> None:
    classification, timeout = controlled._scale_to_zero_contract(
        replace(_neon(), autoscaling_limit_max_cu=maximum_cu)
    )
    assert classification == "FINITE_SCALE_TO_ZERO"
    assert timeout == 300


def _github_documents(run_id: int, sha: str) -> list[dict[str, object]]:
    return [
        {
            "total_count": 1,
            "workflow_runs": [{"id": run_id, "status": "queued"}],
        },
        {"total_count": 0, "workflow_runs": []},
        {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": run_id,
                    "head_sha": sha,
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "run_attempt": 1,
                }
            ],
        },
    ]


def test_github_state_proves_exact_sha_uniqueness_with_authoritative_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "a" * 40
    documents = iter(_github_documents(42, sha))
    paths: list[str] = []

    def get(path: str) -> dict[str, Any]:
        paths.append(path)
        if path.endswith("/git/ref/heads/main"):
            return {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": sha},
            }
        return next(documents)  # type: ignore[return-value]

    monkeypatch.setattr(base, "_github_get", get)
    assert base._github_actions_state("owner/repo", 42, sha) == (0, 0, 1)
    assert f"head_sha={sha}" in paths[-2]
    assert paths[-1].endswith("/git/ref/heads/main")


@pytest.mark.parametrize("document_index", [0, 1, 2])
def test_github_state_rejects_duplicate_run_identities(
    monkeypatch: pytest.MonkeyPatch,
    document_index: int,
) -> None:
    sha = "a" * 40
    documents = _github_documents(42, sha)
    duplicate: dict[str, object]
    if document_index == 2:
        duplicate = deepcopy(documents[document_index]["workflow_runs"])[0]  # type: ignore[index]
    else:
        duplicate = {
            "id": 42,
            "status": "queued" if document_index == 0 else "in_progress",
        }
    documents[document_index]["workflow_runs"] = [duplicate, deepcopy(duplicate)]
    documents[document_index]["total_count"] = 2
    responses = iter(documents)
    monkeypatch.setattr(
        base,
        "_github_get",
        lambda path: (
            {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": sha},
            }
            if path.endswith("/git/ref/heads/main")
            else next(responses)
        ),
    )

    with pytest.raises(base.PreflightNoGo) as caught:
        base._github_actions_state("owner/repo", 42, sha)

    assert caught.value.gate in {
        "github_actions_runs_invalid",
        "github_dispatch_history_invalid",
    }


def test_github_state_rejects_dispatch_of_sha_that_is_no_longer_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched_sha = "a" * 40
    current_main_sha = "b" * 40
    documents = iter(_github_documents(42, dispatched_sha))
    monkeypatch.setattr(
        base,
        "_github_get",
        lambda path: (
            {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": current_main_sha},
            }
            if path.endswith("/git/ref/heads/main")
            else next(documents)
        ),
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        base._github_actions_state("owner/repo", 42, dispatched_sha)
    assert caught.value.reason == "NEON_PROJECT_IDENTITY_AMBIGUOUS"
    assert caught.value.gate == "github_main_ref_mismatch"


@pytest.mark.parametrize(
    "main_ref",
    [
        {},
        {"ref": "refs/heads/other", "object": {"type": "commit", "sha": "a" * 40}},
        {"ref": "refs/heads/main", "object": {"type": "tag", "sha": "a" * 40}},
        {"ref": "refs/heads/main", "object": {"type": "commit", "sha": "invalid"}},
    ],
)
def test_github_state_rejects_malformed_authoritative_main_ref(
    monkeypatch: pytest.MonkeyPatch,
    main_ref: dict[str, object],
) -> None:
    documents = iter(_github_documents(42, "a" * 40))
    monkeypatch.setattr(
        base,
        "_github_get",
        lambda path: (
            main_ref
            if path.endswith("/git/ref/heads/main")
            else next(documents)
        ),
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        base._github_actions_state("owner/repo", 42, "a" * 40)
    assert caught.value.reason == "RECOVERY_BRANCH_NOT_FEASIBLE"
    assert caught.value.gate == "github_main_ref_invalid"


class _RawJsonResponse:
    status_code = 200

    def __init__(self, raw: str) -> None:
        self.raw = raw

    def json(self, **kwargs: object) -> object:
        return json.loads(self.raw, **kwargs)


class _RawJsonSession:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.trust_env = True
        self.headers: dict[str, str] | None = None
        self.allow_redirects: bool | None = None
        self.closed = False

    def get(self, _url: str, **kwargs: object) -> _RawJsonResponse:
        self.headers = kwargs.get("headers")  # type: ignore[assignment]
        self.allow_redirects = kwargs.get("allow_redirects")  # type: ignore[assignment]
        return _RawJsonResponse(self.raw)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "raw",
    [
        '{"projects":[],"projects":[]}',
        '{"pagination":{"next":"a","next":"b"}}',
    ],
)
def test_neon_json_duplicate_keys_are_rejected_at_the_transport_boundary(
    raw: str,
) -> None:
    client = base.NeonReadOnlyClient(
        "synthetic-api-key",
        session=_RawJsonSession(raw),  # type: ignore[arg-type]
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        client.get("/projects")
    assert caught.value.gate == "neon_api_invalid_json"


def test_external_http_clients_disable_ambient_requests_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neon = base.NeonReadOnlyClient("synthetic-api-key")
    assert neon._session.trust_env is False  # noqa: SLF001

    github_session = _RawJsonSession('{"total_count":0,"workflow_runs":[]}')
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setattr(base.requests, "Session", lambda: github_session)
    assert base._github_get("/synthetic") == {
        "total_count": 0,
        "workflow_runs": [],
    }
    assert github_session.trust_env is False
    assert github_session.headers is not None
    assert github_session.headers["Authorization"] == "Bearer synthetic-github-token"
    assert github_session.allow_redirects is False
    assert github_session.closed is True


def test_github_json_duplicate_keys_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RawJsonSession(
        '{"total_count":1,"workflow_runs":[],"workflow_runs":[{"id":1}]}'
    )
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setattr(base.requests, "Session", lambda: session)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._github_get("/synthetic")
    assert caught.value.gate == "github_actions_state_invalid"


@pytest.mark.parametrize(
    "bad_document",
    [
        {"total_count": 1, "workflow_runs": [None]},
        {"total_count": 2, "workflow_runs": [{"id": 1}]},
        {"total_count": 1, "workflow_runs": [{"id": "1"}]},
        {"total_count": 101, "workflow_runs": [{"id": index + 1} for index in range(101)]},
    ],
)
def test_github_state_never_infers_quiescence_from_malformed_or_truncated_data(
    monkeypatch: pytest.MonkeyPatch,
    bad_document: dict[str, object],
) -> None:
    monkeypatch.setattr(base, "_github_get", lambda _path: bad_document)
    with pytest.raises(base.PreflightNoGo):
        base._github_actions_state("owner/repo", 1, "a" * 40)


@pytest.mark.parametrize(
    "name",
    [
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGCHANNELBINDING",
        "PGSSLMODE",
        "PGOPTIONS",
    ],
)
def test_ambient_libpq_environment_fails_before_connection(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    calls = 0

    def forbidden_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("connection must remain unreachable")

    monkeypatch.setenv(name, "synthetic-value")
    monkeypatch.setattr(base.psycopg, "connect", forbidden_connect)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    assert caught.value.gate == "libpq_environment_forbidden"
    assert calls == 0
    serialized = json.dumps(caught.value.sanitized_evidence)
    assert "synthetic-value" not in serialized


def test_short_api_and_database_credentials_fail_before_external_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEON_API_KEY", "short")
    with pytest.raises(base.PreflightNoGo) as api_error:
        base._required_sensitive_context("NEON_API_KEY")
    assert api_error.value.gate == "sensitive_value_too_short"

    short_password = DSN.replace("synthetic_password", "short")
    with pytest.raises(base.PreflightNoGo) as dsn_error:
        base._validated_psycopg_url(short_password)
    assert dsn_error.value.gate == "direct_database_url_invalid"


def test_libpq_environment_name_detection_is_case_insensitive_and_value_free() -> None:
    names = libpq_environment_variable_names(
        {"pGhOsTaDdR": "secret-address", "PATH": "safe", "PGPORT": "6543"}
    )
    assert names == ("PGHOSTADDR", "PGPORT")
    assert "secret-address" not in repr(names)


def test_mutating_bootstrap_connection_uses_the_same_libpq_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.10")
    monkeypatch.setattr(
        production_contract.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("must fail before connect"),
    )
    with pytest.raises(RuntimeError, match="CHRONOS_LIBPQ_ENVIRONMENT_FORBIDDEN"):
        production_contract.connect_direct_postgres(DSN)


class _FakeCursor:
    def __init__(
        self,
        *,
        identity: dict[str, object] | None = None,
        fail_at: int | None = None,
        rollback_raises: bool = False,
        response_overrides: dict[str, list[dict[str, object]]] | None = None,
    ) -> None:
        self.identity = identity or {
            "current_database": "synthetic_database",
            "session_user": "synthetic_user",
            "current_user": "synthetic_user",
            "postgresql_version": "16.14",
            "postgresql_version_num": "160014",
        }
        self.fail_at = fail_at
        self.rollback_raises = rollback_raises
        self.response_overrides = response_overrides or {}
        self.statements: list[str] = []
        self.rows: list[dict[str, object]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        ordinal = len(self.statements)
        self.statements.append(statement)
        if statement == base.SQL_STATEMENTS[base.SQL_ROLLBACK] and self.rollback_raises:
            raise RuntimeError("synthetic rollback failure")
        if self.fail_at == ordinal:
            raise RuntimeError("synthetic statement failure")
        responses: dict[str, list[dict[str, object]]] = {
            base.SQL_STATEMENTS[base.SQL_DEFAULT_TRANSACTION_READ_ONLY]: [
                {"default_transaction_read_only": "on"}
            ],
            base.SQL_STATEMENTS[base.SQL_TRANSACTION_READ_ONLY]: [
                {"transaction_read_only": "on"}
            ],
            base.SQL_STATEMENTS[base.SQL_STATEMENT_TIMEOUT]: [
                {"statement_timeout": "15s"}
            ],
            base.SQL_STATEMENTS[base.SQL_LOCK_TIMEOUT]: [{"lock_timeout": "3s"}],
            base.SQL_STATEMENTS[base.SQL_SEARCH_PATH]: [{"search_path": "pg_catalog"}],
            base.SQL_STATEMENTS[base.SQL_IDENTITY]: [self.identity],
            base.SQL_STATEMENTS[base.SQL_SSL]: [{"ssl": True}],
            base.SQL_STATEMENTS[base.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK]: [
                {
                    "schema_oid": 2200,
                    "table_oid": 16_384,
                    "public_schema_exists": True,
                    "alembic_version_is_plain_permanent_table": True,
                    "schema_usage_grantable": True,
                    "schema_create_grantable": True,
                    "table_select_grantable": True,
                    "table_insert_grantable": True,
                    "table_update_grantable": True,
                    "table_delete_grantable": True,
                    "authority_role_memberships_clean": True,
                }
            ],
            base.SQL_STATEMENTS[base.SQL_TARGET_CLASSIFICATION_AFTER_LOCK]: [
                {
                    "schema_oid": 2200,
                    "table_oid": 16_384,
                    "public_schema_exists": True,
                    "alembic_version_is_plain_permanent_table": True,
                    "schema_usage_grantable": True,
                    "schema_create_grantable": True,
                    "table_select_grantable": True,
                    "table_insert_grantable": True,
                    "table_update_grantable": True,
                    "table_delete_grantable": True,
                    "authority_role_memberships_clean": True,
                }
            ],
            base.SQL_STATEMENTS[base.SQL_REVISION]: [
                {"version_num": base.EXPECTED_REVISION}
            ],
            base.SQL_STATEMENTS[base.SQL_LIFECYCLE_ADMIN]: [
                {
                    "rolcanlogin": True,
                    "rolsuper": True,
                    "rolcreatedb": True,
                    "rolcreaterole": True,
                    "rolreplication": False,
                    "rolbypassrls": False,
                }
            ],
            base.SQL_STATEMENTS[base.SQL_PRIVILEGED_CATALOG]: [{"visible": True}],
            base.SQL_STATEMENTS[base.SQL_CHRONOS_ROLES]: [],
            base.SQL_STATEMENTS[base.SQL_CHRONOS_MEMBERSHIPS]: [],
            base.SQL_STATEMENTS[base.SQL_CHRONOS_OBJECTS]: [],
        }
        self.rows = self.response_overrides.get(statement, responses.get(statement, []))

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor, *, close_raises: bool = False) -> None:
        self._cursor = cursor
        self._close_raises = close_raises

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        if self._close_raises:
            raise RuntimeError("synthetic close failure")
        return None


def _install_fake_database(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity: dict[str, object] | None = None,
    fail_at: int | None = None,
    rollback_raises: bool = False,
    response_overrides: dict[str, list[dict[str, object]]] | None = None,
    close_raises: bool = False,
) -> tuple[_FakeCursor, list[dict[str, object]]]:
    cursor = _FakeCursor(
        identity=identity,
        fail_at=fail_at,
        rollback_raises=rollback_raises,
        response_overrides=response_overrides,
    )
    calls: list[dict[str, object]] = []

    def connect(_dsn: str, **kwargs: object) -> _FakeConnection:
        calls.append(kwargs)
        return _FakeConnection(cursor, close_raises=close_raises)

    monkeypatch.setattr(base.psycopg, "connect", connect)
    return cursor, calls


def test_database_happy_path_binds_target_and_preserves_exact_effect_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor, calls = _install_fake_database(monkeypatch)
    observation = base._inspect_database(DSN, expected_postgresql_major=16)
    assert cursor.statements == list(base.SQL_STATEMENTS)
    assert observation.database_name == "synthetic_database"
    assert observation.session_user == "synthetic_user"
    assert observation.postgresql_version_num == 160014
    assert observation.sql_statement_count == len(base.SQL_STATEMENTS) == 18
    assert observation.sql_statement_completed_count == 18
    assert observation.sql_read_attempt_count == observation.sql_read_count == 15
    assert calls == [
        {
            "host": "ep-synthetic.neon.tech",
            "port": 5432,
            "dbname": "synthetic_database",
            "user": "synthetic_user",
            "autocommit": True,
            "sslmode": "require",
            "channel_binding": "require",
            "connect_timeout": 10,
            "options": base.READONLY_STARTUP_OPTIONS,
            "row_factory": base.dict_row,
        }
    ]


def test_catalog_proof_excludes_noncanonical_storage_replication_and_ddl_hooks() -> None:
    for ordinal in (
        base.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK,
        base.SQL_TARGET_CLASSIFICATION_AFTER_LOCK,
    ):
        statement = base.SQL_STATEMENTS[ordinal]
        assert "FROM pg_catalog.pg_trigger tg" in statement
        assert "FROM pg_catalog.pg_rewrite rw" in statement
        assert "pg_catalog.pg_inherits" in statement
        assert "i.inhparent=c.oid OR i.inhrelid=c.oid" in statement
        assert "am.amname='heap'" in statement
        assert "c.reloftype=0" in statement
        assert "c.reloptions IS NULL" in statement
        assert "c.reltoastrelid=0" in statement
        assert "c.relreplident='d'" in statement
        assert "c.relnatts=1" in statement
        assert "NOT c.relhasrules" in statement
        assert "NOT c.relhastriggers" in statement
        assert "NOT c.relhassubclass" in statement
        assert "pg_catalog.pg_policy" in statement
        assert "pg_catalog.pg_publication_tables" in statement
        assert "pg_catalog.pg_subscription_rel" in statement
        assert "pg_catalog.pg_event_trigger" in statement
        assert "pg_catalog.pg_statistic_ext" in statement
        assert "auto_dep.deptype='x'" in statement
        assert "auto_idx.indrelid=c.oid" in statement
        assert (
            "dep.refclassid='pg_catalog.pg_extension'::pg_catalog.regclass"
            in statement
        )
        assert "dep.classid='pg_catalog.pg_type'::pg_catalog.regclass" in statement
        assert "dep.classid='pg_catalog.pg_namespace'::pg_catalog.regclass" in statement
        assert "row_type.typarray" in statement
        assert "att.attstorage=(SELECT typstorage" in statement
        assert "att.attcompression=''" in statement
        assert "att.attstattarget=-1" in statement
        assert "att.attoptions IS NULL" in statement
        assert "NOT att.atthasmissing" in statement
        assert "att.attmissingval IS NULL" in statement
        assert "NOT att.atthasdef" in statement
        assert "att.attfdwoptions IS NULL" in statement
        assert "att.attislocal AND att.attinhcount=0 AND att.attndims=0" in statement
        assert "con.conname='alembic_version_pkc'" in statement
        assert "con.coninhcount=0 AND con.conislocal" in statement
        assert "AND con.connoinherit" in statement
        assert "idx_am.amname='btree'" in statement
        assert "opclass.opcname='text_ops'" in statement
        assert "att.attcollation=(SELECT typcollation" in statement
        assert "idx.indcollation[0]=att.attcollation" in statement
        assert "NOT idx.indnullsnotdistinct" in statement
        assert "pg_catalog.pg_attrdef" in statement
        assert "att.attacl" in statement
        assert "acl.privilege_type='CREATE'" in statement
        assert "FROM pg_catalog.pg_auth_members membership" in statement
        assert "AS authority_role_memberships_clean" in statement
        assert "platform_grantee.rolname='neon_superuser'" in statement
        assert "NOT platform_grantee.rolcanlogin" in statement
        assert "pg_catalog.pg_has_role(a.role_oid,platform_grantee.oid,'MEMBER')" in statement
        assert "WITH RECURSIVE platform_descendants(member)" in statement
        assert "platform_membership.roleid=platform_grantee.oid" in statement
        assert "nested_membership.roleid=descendants.member" in statement
        assert "platform_descendants WHERE member<>a.role_oid" in statement
        assert "WITH RECURSIVE authority_descendants(member)" in statement
        assert "authority_descendants WHERE member<>targets.role_oid" in statement
        assert "current_db.datdba ELSE n.nspowner" in statement
        assert "targets.effective_schema_owner_oid" in statement
        assert "current_db.datdba ELSE c.relowner" in statement
        assert "targets.effective_table_owner_oid" in statement
        assert "global_writer_descendants(member)" in statement
        assert "global_writer.rolname='pg_write_all_data'" in statement
        assert "pg_has_role(global_writer.oid,'pg_write_all_data','MEMBER')" not in statement
        assert "WITH RECURSIVE protected_descendants(member)" in statement
        assert "member_role.rolcanlogin" in statement
        assert "acl.is_grantable" in statement
    inventory = base.SQL_STATEMENTS[base.SQL_CHRONOS_OBJECTS]
    assert "FROM pg_catalog.pg_type t" in inventory
    assert "t.typrelid=0" in inventory
    assert "uq_chronos_authority_run_revision" in inventory
    privileged_catalog = base.SQL_STATEMENTS[base.SQL_PRIVILEGED_CATALOG]
    assert "rolpassword IS NULL" in privileged_catalog
    assert "SELECT count(*) = 1 AS visible" not in privileged_catalog

    runner_source = (ROOT / "scripts/run_chronos_dual_principal_ci_v2.py").read_text(
        encoding="utf-8"
    )
    for mutation in (
        "SET STORAGE PLAIN",
        "SET STATISTICS 0",
        "SET (n_distinct=-0.5)",
        "SET COMPRESSION pglz",
        "atthasmissing AND attmissingval IS NOT NULL",
        "CREATE STATISTICS public.chronos_ci_hostile_stats",
        "DROP COLUMN chronos_ci_hostile_dropped",
        "ALTER EXTENSION plpgsql ADD TABLE public.alembic_version",
        "ALTER EXTENSION plpgsql ADD SCHEMA public",
        "ALTER EXTENSION plpgsql ADD TYPE public.alembic_version",
        "ALTER EXTENSION plpgsql ADD TYPE public._alembic_version",
        "DROP RULE chronos_ci_hostile_rule",
        "DROP TRIGGER chronos_ci_hostile_trigger",
        "DROP TABLE public.chronos_ci_hostile_child",
    ):
        assert mutation in runner_source


@pytest.mark.parametrize(
    "identity",
    [
        {
            "current_database": "wrong_database",
            "session_user": "synthetic_user",
            "current_user": "synthetic_user",
            "postgresql_version": "16.14",
            "postgresql_version_num": "160014",
        },
        {
            "current_database": "synthetic_database",
            "session_user": "other_principal",
            "current_user": "other_principal",
            "postgresql_version": "16.14",
            "postgresql_version_num": "160014",
        },
        {
            "current_database": "synthetic_database",
            "session_user": "synthetic_user",
            "current_user": "elevated_role",
            "postgresql_version": "16.14",
            "postgresql_version_num": "160014",
        },
    ],
)
def test_database_identity_mismatch_stops_before_ssl_and_revision(
    monkeypatch: pytest.MonkeyPatch,
    identity: dict[str, object],
) -> None:
    cursor, _calls = _install_fake_database(monkeypatch, identity=identity)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    assert caught.value.gate == "postgresql_target_identity_mismatch"
    assert cursor.statements == [
        *base.SQL_STATEMENTS[: base.SQL_IDENTITY + 1],
        base.SQL_STATEMENTS[base.SQL_ROLLBACK],
    ]
    assert caught.value.effect_counts["sql_statement_count"] == len(cursor.statements)
    assert caught.value.effect_counts["sql_write_count"] == 0


def test_database_rejects_members_of_the_lifecycle_or_owner_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe = deepcopy(
        _FakeCursor().response_overrides.get(
            base.SQL_STATEMENTS[base.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK],
            [],
        )
    )
    if not unsafe:
        unsafe = [
            {
                "schema_oid": 2200,
                "table_oid": 16_384,
                "public_schema_exists": True,
                "alembic_version_is_plain_permanent_table": True,
                "schema_usage_grantable": True,
                "schema_create_grantable": True,
                "table_select_grantable": True,
                "table_insert_grantable": True,
                "table_update_grantable": True,
                "table_delete_grantable": True,
                "authority_role_memberships_clean": False,
            }
        ]
    overrides = {
        base.SQL_STATEMENTS[base.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK]: unsafe,
        base.SQL_STATEMENTS[base.SQL_TARGET_CLASSIFICATION_AFTER_LOCK]: deepcopy(unsafe),
    }
    cursor, _calls = _install_fake_database(
        monkeypatch,
        response_overrides=overrides,
    )

    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)

    assert caught.value.gate == "bootstrap_authority_capabilities_insufficient"
    assert base.SQL_STATEMENTS[base.SQL_PRIVILEGED_CATALOG] not in cursor.statements


def test_pg_authid_column_only_visibility_is_an_authority_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor, _calls = _install_fake_database(monkeypatch)
    execute = cursor.execute

    def deny_password_column(statement: str) -> None:
        if statement == base.SQL_STATEMENTS[base.SQL_PRIVILEGED_CATALOG]:
            cursor.statements.append(statement)
            raise base.psycopg.errors.InsufficientPrivilege(
                "synthetic rolpassword denial"
            )
        execute(statement)

    monkeypatch.setattr(cursor, "execute", deny_password_column)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    assert caught.value.reason == "BOOTSTRAP_AUTHORITY_INSUFFICIENT"
    assert caught.value.gate == "privileged_catalog_not_visible"
    assert caught.value.sanitized_postgresql_evidence is not None
    assert caught.value.sanitized_postgresql_evidence[
        "privileged_catalog_visible"
    ] is False
    assert caught.value.effect_counts["sql_statement_count"] == 15
    assert caught.value.effect_counts["sql_statement_completed_count"] == 14
    report = controlled._controlled_no_go_report(
        base.PreflightNoGo(
            caught.value.reason,
            caught.value.gate,
            sanitized_evidence=base._sanitized_neon(_neon()),
            sanitized_postgresql_evidence=(
                caught.value.sanitized_postgresql_evidence
            ),
            effect_counts=caught.value.effect_counts,
        ),
        controlled.ConnectionWakeAudit(
            endpoint_pre_wake_state="idle",
            identity_complete_before_wake=True,
            connection_attempt_count=1,
            connection_succeeded=True,
            compute_wake_events=1,
            compute_wake_events_observed=1,
            wake_verdict="CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE",
        ),
    )
    assert _valid_report(report) is True


def test_postgresql_major_mismatch_is_a_target_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = deepcopy(_FakeCursor().identity)
    identity["postgresql_version"] = "17.5"
    identity["postgresql_version_num"] = "170005"
    cursor, _calls = _install_fake_database(monkeypatch, identity=identity)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    assert caught.value.gate == "postgresql_major_version_mismatch"
    assert base.SQL_STATEMENTS[base.SQL_SSL] not in cursor.statements


def test_primary_postgresql_gate_preserves_secondary_close_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cursor, _calls = _install_fake_database(
        monkeypatch,
        identity={
            "current_database": "wrong_database",
            "session_user": "synthetic_user",
            "current_user": "synthetic_user",
            "postgresql_version": "16.14",
            "postgresql_version_num": "160014",
        },
        close_raises=True,
    )

    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)

    assert caught.value.gate == "postgresql_target_identity_mismatch"
    assert caught.value.sanitized_postgresql_evidence is not None
    assert (
        caught.value.sanitized_postgresql_evidence[
            "connection_close_completed"
        ]
        is False
    )


def _run_boundary_integrated_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    session: _IdleIdentitySession | None = None,
    response_overrides: dict[str, list[dict[str, object]]] | None = None,
    close_raises: bool = False,
) -> tuple[dict[str, Any], _FakeCursor, list[dict[str, object]], Path]:
    sha = "b" * 40
    for name, value in {
        "GITHUB_REPOSITORY": base.EXPECTED_REPOSITORY,
        "GITHUB_REF": base.EXPECTED_REF,
        "GITHUB_SHA": sha,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "4242",
        "GITHUB_TOKEN": "synthetic-github-token",
        "NEON_API_KEY": "synthetic-api-key",
        "NEON_BOOTSTRAP_DATABASE_URL": DSN,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NEON_PROJECT_ID", raising=False)
    for name in libpq_environment_variable_names():
        monkeypatch.delenv(name, raising=False)

    github_documents = iter(_github_documents(4242, sha))
    monkeypatch.setattr(
        base,
        "_github_get",
        lambda path: (
            {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": sha},
            }
            if path.endswith("/git/ref/heads/main")
            else next(github_documents)
        ),
    )
    live_session = session or _IdleIdentitySession()
    monkeypatch.setattr(
        base,
        "NeonReadOnlyClient",
        lambda api_key: _REAL_NEON_READONLY_CLIENT(api_key, session=live_session),
    )
    cursor, calls = _install_fake_database(
        monkeypatch,
        response_overrides=response_overrides,
        close_raises=close_raises,
    )
    report_path = tmp_path / ".chronos" / "reports" / "integrated.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["chronos-controlled", "--report", str(report_path)],
    )
    controlled.main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    before_guard = report_path.read_bytes()
    assert ensure_artifact(report_path, live_outcome="success") is True
    assert report_path.read_bytes() == before_guard
    return report, cursor, calls, report_path


def test_full_live_path_replay_only_mocks_external_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = _IdleIdentitySession()
    report, cursor, calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path,
        session=session,
    )
    assert report["verdict"] == base.GO_VERDICT
    assert report["global_verdict"] == (
        "CHRONOS_NEON_CONTROLLED_WAKE_AND_READONLY_PREFLIGHT_CLOSED"
    )
    assert session.paths == [
        "/auth",
        "/organizations/owner-production",
        "/projects",
        "/projects/project-production/endpoints",
        "/projects/project-production/branches/count",
        "/projects/project-production/endpoints/endpoint-production",
        "/projects/project-production",
        "/projects/project-production/branches",
        "/projects/project-production/branches/branch-production/endpoints",
    ]
    assert len(calls) == 1
    assert cursor.statements == list(base.SQL_STATEMENTS)
    assert report["effects"]["postgresql_connection_attempts"] == 1
    assert report["effects"]["sql_statement_count"] == 18
    assert report["effects"]["sql_write_count"] == 0
    assert report["effects"]["neon_mutations"] == 0


@pytest.mark.parametrize(
    ("scenario", "expected_gate", "not_reached_sql"),
    [
        ("branch_ambiguity", "endpoint_detail_project_mismatch", None),
        ("ssl_false", "ssl_not_proven", base.SQL_TARGET_CLASSIFICATION_BEFORE_LOCK),
        ("revision_0014", "unexpected_database_revision", base.SQL_LIFECYCLE_ADMIN),
        (
            "bootstrap_insufficient",
            "bootstrap_authority_capabilities_insufficient",
            base.SQL_PRIVILEGED_CATALOG,
        ),
        ("recovery_impossible", "recovery_branch_not_feasible", None),
        ("purchase_required", "purchase_required", None),
    ],
)
def test_full_no_go_replays_stop_at_the_correct_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    expected_gate: str,
    not_reached_sql: int | None,
) -> None:
    session = _IdleIdentitySession()
    overrides: dict[str, list[dict[str, object]]] = {}
    if scenario == "branch_ambiguity":
        session = _IdleIdentitySession(project_id_mismatch=True)
    elif scenario == "ssl_false":
        overrides[base.SQL_STATEMENTS[base.SQL_SSL]] = [{"ssl": False}]
    elif scenario == "revision_0014":
        overrides[base.SQL_STATEMENTS[base.SQL_REVISION]] = [
            {"version_num": "0014_chronos_control_plane_v2"}
        ]
    elif scenario == "bootstrap_insufficient":
        overrides[base.SQL_STATEMENTS[base.SQL_LIFECYCLE_ADMIN]] = [
            {
                "rolcanlogin": True,
                "rolsuper": False,
                "rolcreatedb": False,
                "rolcreaterole": False,
                "rolreplication": False,
                "rolbypassrls": False,
            }
        ]
    elif scenario == "recovery_impossible":
        session = _IdleIdentitySession(history_retention_seconds=0)
    elif scenario == "purchase_required":
        session = _IdleIdentitySession(branch_count=10)
    report, cursor, calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path,
        session=session,
        response_overrides=overrides,
    )
    assert report["verdict"] == base.NO_GO_VERDICT
    assert report["failed_gate"] == expected_gate
    assert report["effects"]["sql_write_count"] == 0
    assert report["effects"]["neon_mutations"] == 0
    if scenario in {"branch_ambiguity", "recovery_impossible", "purchase_required"}:
        assert calls == []
        assert cursor.statements == []
        assert report["effects"]["postgresql_connection_attempts"] == 0
    else:
        assert len(calls) == 1
        assert not_reached_sql is not None
        assert base.SQL_STATEMENTS[not_reached_sql] not in cursor.statements
        assert cursor.statements[-1] == base.SQL_STATEMENTS[base.SQL_ROLLBACK]
        postgresql = report["postgresql"]
        assert postgresql["connection_established"] is True
        assert postgresql["default_transaction_read_only"] is True
        assert postgresql["transaction_read_only"] is True
        assert postgresql["statement_timeout_ms"] == 15_000
        assert postgresql["lock_timeout_ms"] == 3_000
        assert postgresql["database_target_verified"] is True
        assert postgresql["principal_target_verified"] is True
        if scenario == "ssl_false":
            assert postgresql["ssl_verified"] is False
            assert postgresql["revision_class"] == "NOT_OBSERVED"
            assert postgresql["revision_count"] is None
            disconnected = deepcopy(report)
            disconnected["postgresql"]["connection_established"] = False
            disconnected["postgresql"]["connection_close_completed"] = None
            disconnected["effects"]["postgresql_connection_successes"] = 0
            assert _valid_report(disconnected) is False
            no_sql = deepcopy(report)
            for key in (
                "sql_statement_count",
                "sql_statement_completed_count",
                "sql_read_attempt_count",
                "sql_read_count",
                "begin_read_only_attempted",
                "begin_read_only_completed",
                "rollback_attempted",
                "rollback_completed",
            ):
                no_sql["effects"][key] = 0
            assert _valid_report(no_sql) is False
            impossible_version = deepcopy(report)
            impossible_version["postgresql"]["postgresql_version_num"] = 999_999
            impossible_version["postgresql"]["postgresql_major_verified"] = True
            assert _valid_report(impossible_version) is False
        elif scenario == "revision_0014":
            assert postgresql["ssl_verified"] is True
            assert postgresql["alembic_target_safe"] is True
            assert postgresql["revision_class"] == (
                "0014_chronos_control_plane_v2"
            )
            assert postgresql["revision_count"] == 1
        else:
            assert postgresql["revision_class"] == base.EXPECTED_REVISION
            assert postgresql["revision_count"] == 1
            assert (
                postgresql["bootstrap_authority_capabilities_proven"]
                is False
            )


@pytest.mark.parametrize("ordinal", range(len(base.SQL_STATEMENTS)))
def test_every_sql_ordinal_failure_is_sanitized_counted_and_never_retried(
    monkeypatch: pytest.MonkeyPatch,
    ordinal: int,
) -> None:
    _cursor, calls = _install_fake_database(monkeypatch, fail_at=ordinal)
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    effects = caught.value.effect_counts
    assert effects["postgresql_connection_attempts"] == 1
    assert effects["postgresql_connection_successes"] == 1
    assert effects["postgresql_retries"] == 0
    assert effects["sql_write_count"] == 0
    assert effects["sql_statement_count"] <= len(base.SQL_STATEMENTS)
    assert effects["rollback_attempted"] == (0 if ordinal == 0 else 1)
    assert len(calls) == 1
    assert caught.value.sanitized_postgresql_evidence is not None
    assert (
        caught.value.sanitized_postgresql_evidence["inspection_failure_class"]
        in {"SQL_EXECUTION_EXCEPTION", "ROLLBACK_EXCEPTION"}
    )
    report = controlled._controlled_no_go_report(
        base.PreflightNoGo(
            caught.value.reason,
            caught.value.gate,
            sanitized_evidence=base._sanitized_neon(_neon()),
            sanitized_postgresql_evidence=(
                caught.value.sanitized_postgresql_evidence
            ),
            effect_counts=caught.value.effect_counts,
        ),
        controlled.ConnectionWakeAudit(
            endpoint_pre_wake_state="idle",
            identity_complete_before_wake=True,
            connection_attempt_count=1,
            connection_succeeded=True,
            compute_wake_events=1,
            compute_wake_events_observed=1,
            wake_verdict="CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE",
        ),
    )
    assert _valid_report(report) is True


def test_primary_sql_failure_survives_a_secondary_rollback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cursor, calls = _install_fake_database(
        monkeypatch,
        fail_at=base.SQL_SSL,
        rollback_raises=True,
    )
    with pytest.raises(base.PreflightNoGo) as caught:
        base._inspect_database(DSN, expected_postgresql_major=16)
    assert caught.value.gate == "postgresql_readonly_inspection_failed"
    assert caught.value.sanitized_postgresql_evidence is not None
    assert (
        caught.value.sanitized_postgresql_evidence["inspection_failure_class"]
        == "SQL_EXECUTION_EXCEPTION"
    )
    assert caught.value.effect_counts["rollback_attempted"] == 1
    assert caught.value.effect_counts["rollback_completed"] == 0
    assert len(calls) == 1
    report = controlled._controlled_no_go_report(
        base.PreflightNoGo(
            caught.value.reason,
            caught.value.gate,
            sanitized_evidence=base._sanitized_neon(_neon()),
            sanitized_postgresql_evidence=(
                caught.value.sanitized_postgresql_evidence
            ),
            effect_counts=caught.value.effect_counts,
        ),
        controlled.ConnectionWakeAudit(
            endpoint_pre_wake_state="idle",
            identity_complete_before_wake=True,
            connection_attempt_count=1,
            connection_succeeded=True,
            compute_wake_events=1,
            compute_wake_events_observed=1,
            wake_verdict="CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE",
        ),
    )
    assert _valid_report(report) is True


def test_bootstrap_authority_requires_targets_capabilities_and_clean_inventory() -> None:
    superuser = _database()
    assert base._bootstrap_authority_plausible(superuser)
    non_superuser = replace(
        superuser,
        lifecycle_admin_superuser=False,
        lifecycle_admin_createrole=True,
    )
    assert base._bootstrap_authority_plausible(non_superuser)
    for capability in non_superuser.bootstrap_grantable_capabilities:
        reduced = replace(
            non_superuser,
            bootstrap_grantable_capabilities=tuple(
                item
                for item in non_superuser.bootstrap_grantable_capabilities
                if item != capability
            ),
        )
        assert not base._bootstrap_authority_plausible(reduced)
    assert not base._bootstrap_authority_plausible(
        replace(non_superuser, bootstrap_targets_valid=False)
    )
    assert not base._bootstrap_authority_plausible(
        replace(non_superuser, chronos_roles=({"rolname": "chronos_partial"},))
    )
    assert not base._bootstrap_authority_plausible(
        replace(
            non_superuser,
            chronos_memberships=(
                {
                    "granted_role": "chronos_reader",
                    "member_role": "attacker",
                    "grantor_role": "admin",
                    "admin_option": True,
                },
            ),
        )
    )
    assert not base._bootstrap_authority_plausible(
        replace(
            non_superuser,
            chronos_objects=(
                {
                    "object_type": "relation",
                    "schema_name": "public",
                    "object_name": "chronos_backdoor",
                    "owner_role": "attacker",
                    "acl_entry_count": 1,
                },
            ),
        )
    )


def test_existing_object_owner_is_fingerprinted_in_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "highly_sensitive_admin"
    database = replace(
        _database(),
        chronos_objects=(
            {
                "object_type": "relation",
                "schema_name": "public",
                "object_name": "chronos_backdoor",
                "owner_role": owner,
                "acl_entry_count": 1,
            },
        ),
    )
    serialized = json.dumps(_run_synthetic(monkeypatch, database=database))
    assert owner not in serialized
    assert "owner_role_sha256" in serialized


def test_exact_module_command_with_malformed_run_id_still_writes_report(
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_REPOSITORY": base.EXPECTED_REPOSITORY,
            "GITHUB_REF": base.EXPECTED_REF,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_RUN_ID": "not-an-integer",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.chronos_neon_controlled_idle_wake_readonly_v1",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    guarded = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.chronos_live_path_artifact_guard_v1",
            "--report",
            str(report),
            "--schema",
            controlled.REPORT_SCHEMA,
            "--live-outcome",
            "success",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert guarded.returncode == 0, guarded.stdout + guarded.stderr
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["verdict"] == NO_GO_VERDICT
    assert document["failed_gate"] == "invalid:GITHUB_RUN_ID"
    assert document["reason"] == "RECOVERY_BRANCH_NOT_FEASIBLE"
    assert set(document["effects"].values()) == {0}


def test_wrong_cwd_and_wrong_python_modes_are_detected_offline(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    wrong_cwd = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.chronos_neon_controlled_idle_wake_readonly_v1",
            "--help",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    no_site_packages = subprocess.run(
        [
            sys.executable,
            "-S",
            "-m",
            "scripts.chronos_neon_controlled_idle_wake_readonly_v1",
            "--help",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_cwd.returncode != 0
    assert no_site_packages.returncode != 0
    for outcome, expected_attempts, expected_sql in (
        ("skipped", 0, 0),
        ("failure", 1, 25),
    ):
        report = tmp_path / f"guard-{outcome}.json"
        guard = subprocess.run(
            [
                sys.executable,
                "-S",
                "-m",
                "scripts.chronos_live_path_artifact_guard_v1",
                "--report",
                str(report),
                "--live-outcome",
                outcome,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert guard.returncode == 0, guard.stdout + guard.stderr
        recovered = json.loads(report.read_text(encoding="utf-8"))
        assert recovered["verdict"] == NO_GO_VERDICT
        assert recovered["effects"]["postgresql_connection_attempts"] == (
            expected_attempts
        )
        assert recovered["effects"]["sql_statement_count"] == expected_sql


@pytest.mark.parametrize(
    "dsn",
    [
        DSN,
        DSN.replace("sslmode=require", "sslmode=verify-ca"),
        DSN.replace("sslmode=require", "sslmode=verify-full"),
        DSN.replace("synthetic_password", "encoded%2Dpassword"),
        DSN.replace("postgresql://", "postgresql+psycopg://"),
        DSN.replace("ep-synthetic.neon.tech", "localhost"),
        DSN.replace("ep-synthetic", "ep-synthetic-pooler"),
        DSN.replace(".neon.tech/", ".neon.tech:6543/"),
        DSN.replace("&channel_binding=require", ""),
        DSN + "&application_name=chronos",
        DSN.replace("synthetic_password", "short"),
        "postgresql://[bad",
    ],
)
def test_stdlib_guard_dsn_parser_matches_the_canonical_runtime_contract(
    dsn: str,
) -> None:
    try:
        canonical = production_contract.validate_direct_postgres_url(dsn)
    except production_contract.ChronosProductionError:
        canonical = None
    guarded = guard_validated_direct_postgres_url(dsn)
    assert (canonical is None) == (guarded is None)
    if canonical is not None and guarded is not None:
        assert (
            guarded.host,
            guarded.port,
            guarded.database,
            guarded.username,
            guarded.sslmode,
            guarded.channel_binding,
        ) == (
            canonical.host,
            canonical.port,
            canonical.database,
            canonical.username,
            canonical.sslmode,
            canonical.channel_binding,
        )


@pytest.mark.skipif(os.name == "nt", reason="GNU timeout is exercised on Linux CI")
def test_exact_gnu_timeout_kills_a_term_resistant_child_within_bound() -> None:
    started = time.monotonic()
    completed = subprocess.run(
        [
            "timeout",
            "--signal=TERM",
            "--kill-after=1s",
            "1s",
            sys.executable,
            "-c",
            (
                "import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(30)"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert time.monotonic() - started < 5


def test_live_guard_and_upload_use_one_exact_file_path() -> None:
    workflow_paths = (
        ROOT
        / ".github"
        / "workflows"
        / "chronos-neon-controlled-idle-wake-readonly-v1.yml",
        ROOT
        / ".github"
        / "workflows"
        / "chronos-neon-pure-readonly-preflight-v4.yml",
    )
    for workflow_path in workflow_paths:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        job = workflow["jobs"]["preflight"]
        steps = job["steps"]
        assert job["if"] == "${{ github.run_attempt == 1 }}"
        assert steps[0]["name"] == "Refuser toute relance"
        assert 'test "$GITHUB_RUN_ATTEMPT" = "1"' in steps[0]["run"]
        setup = next(
            step for step in steps if "actions/setup-python@" in step.get("uses", "")
        )
        assert "cache" not in setup["with"]
        live = next(step for step in steps if step.get("id") == "live_preflight")
        guard = next(step for step in steps if step.get("id") == "artifact_guard")
        upload = next(
            step for step in steps if "upload-artifact@" in step.get("uses", "")
        )
        live_path = live["run"].split("--report ", 1)[1].split()[0]
        guard_path = guard["run"].split("--report ", 1)[1].split()[0]
        assert live_path == guard_path == upload["with"]["path"]
        assert not live_path.endswith("/")
        assert upload["with"]["if-no-files-found"] == "error"
        assert upload["with"]["include-hidden-files"] is True
        assert upload["with"]["retention-days"] == 14


def test_postgresql_profile_replay_checks_out_the_exact_pr_head() -> None:
    canonical = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    caller = canonical["jobs"]["chronos-postgresql-profiles"]
    assert caller["with"]["checkout_ref"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )

    reusable = yaml.safe_load(
        (
            ROOT / ".github" / "workflows" / "chronos-bootstrap-ci-v3.yml"
        ).read_text(encoding="utf-8")
    )
    triggers = reusable.get("on", reusable.get(True))
    assert triggers["workflow_call"]["inputs"]["checkout_ref"]["required"] is True
    checkouts = [
        step
        for job in reusable["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert len(checkouts) == 4
    assert all(
        step["with"]["ref"] == "${{ inputs.checkout_ref || github.sha }}"
        for step in checkouts
    )


def test_secret_mask_workflow_commands_escape_percent_cr_and_lf() -> None:
    for workflow_path in (
        ROOT
        / ".github"
        / "workflows"
        / "chronos-neon-controlled-idle-wake-readonly-v1.yml",
        ROOT
        / ".github"
        / "workflows"
        / "chronos-neon-pure-readonly-preflight-v4.yml",
    ):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        mask_step = next(
            step
            for step in workflow["jobs"]["preflight"]["steps"]
            if step.get("name") == "Masquer et verifier les secrets requis"
        )
        command = mask_step["run"]
        assert "value=\"${value//'%'/'%25'}\"" in command
        assert "value=\"${value//$'\\r'/'%0D'}\"" in command
        assert "value=\"${value//$'\\n'/'%0A'}\"" in command
        assert 'echo "::add-mask::${!name}"' not in command
        assert 'echo "::add-mask::$NEON_' not in command


def test_artifact_guard_recovers_missing_invalid_and_secret_bearing_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / ".chronos" / "reports" / "report.json"
    assert ensure_artifact(path) is False
    recovered = json.loads(path.read_text(encoding="utf-8"))
    assert recovered["verdict"] == NO_GO_VERDICT
    assert recovered["failed_gate"] == "artifact_guard_recovered_missing_or_invalid_report"
    assert recovered["effect_counter_certainty"] == "CONSERVATIVE_UPPER_BOUNDS_ONLY"
    assert recovered["effects"]["postgresql_connection_attempts"] == 1
    assert recovered["effects"]["compute_wake_events"] == 1
    assert recovered["effects"]["sql_statement_count"] == 25
    path.write_text("{partial", encoding="utf-8")
    assert ensure_artifact(path) is False
    path.write_text("[" * 10_000 + "0" + "]" * 10_000, encoding="utf-8")
    assert ensure_artifact(path) is False
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == NO_GO_VERDICT
    path.write_bytes(b" " * (_MAX_REPORT_BYTES + 1))
    assert ensure_artifact(path) is False
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == NO_GO_VERDICT
    path.write_text("{\"oversized_integer\":" + "9" * 5_000 + "}", encoding="utf-8")
    assert ensure_artifact(path) is False
    assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == NO_GO_VERDICT
    for field, malformed in (
        ("effect_counter_certainty", []),
        ("verdict", {}),
    ):
        document = guard._fallback_report(report_schema=guard.REPORT_SCHEMA)
        document[field] = malformed
        path.write_text(json.dumps(document), encoding="utf-8")
        assert ensure_artifact(path) is False
        assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == NO_GO_VERDICT
    go_document = _run_synthetic(monkeypatch)
    for field, malformed in (
        ("project_identity_verdict", []),
        ("autoscaling_limit_max_cu", 10**1_000),
    ):
        malformed_go = deepcopy(go_document)
        malformed_go["neon"][field] = malformed
        path.write_text(json.dumps(malformed_go), encoding="utf-8")
        assert ensure_artifact(path) is False
        assert json.loads(path.read_text(encoding="utf-8"))["verdict"] == NO_GO_VERDICT
    secret = "synthetic-secret-value"
    monkeypatch.setenv("NEON_API_KEY", secret)
    compromised = deepcopy(recovered)
    compromised["leak"] = secret
    path.write_text(json.dumps(compromised), encoding="utf-8")
    assert ensure_artifact(path) is False
    assert secret not in path.read_text(encoding="utf-8")


def test_controlled_technical_fallback_bounds_all_neon_gets() -> None:
    report = controlled._conservative_technical_failure_report(
        "unexpected_sanitized_failure"
    )
    assert report["effect_counter_certainty"] == "CONSERVATIVE_UPPER_BOUNDS_ONLY"
    assert report["effects"]["neon_get_count"] == base.MAX_NEON_GETS
    assert _valid_report(report) is True


def test_a_directory_at_the_report_path_fails_closed_before_upload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    path.mkdir()
    with pytest.raises(OSError):
        ensure_artifact(path, live_outcome="failure")


def test_artifact_guard_rejects_minimal_go_and_raw_identity_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    minimal_go = {
        "schema_version": controlled.REPORT_SCHEMA,
        "verdict": base.GO_VERDICT,
        "effects": {
            key: 0
            for key in (
                "neon_mutations",
                "production_sql_writes",
                "recovery_branch_creations",
                "role_creations",
                "migration_0014",
                "r2_operations",
                "provider_calls",
                "purchases",
                "sensitive_values_exposed",
                "sql_write_count",
                "postgresql_retries",
            )
        },
    }
    assert _valid_report(minimal_go) is False

    password = "artifact-password-value"
    hostname = "ep-raw-artifact.neon.tech"
    cursor = "raw-opaque-cursor"
    monkeypatch.setenv(
        "NEON_BOOTSTRAP_DATABASE_URL",
        f"postgresql://admin:{password}@{hostname}/neondb",
    )
    path = tmp_path / "report.json"
    ensure_artifact(path)
    compromised = json.loads(path.read_text(encoding="utf-8"))
    compromised["neon"] = {
        "password": password,
        "endpoint_host": hostname,
        "cursor": cursor,
    }
    path.write_text(json.dumps(compromised), encoding="utf-8")
    assert ensure_artifact(path) is False
    sanitized = path.read_text(encoding="utf-8")
    assert password not in sanitized
    assert hostname not in sanitized
    assert cursor not in sanitized


def test_artifact_guard_preserves_a_valid_sanitized_no_go(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    ensure_artifact(path)
    before = path.read_bytes()
    assert ensure_artifact(path) is True
    assert path.read_bytes() == before


def test_artifact_guard_accepts_only_a_complete_synthetic_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    assert report["verdict"] == base.GO_VERDICT
    assert _valid_report(report) is True


@pytest.mark.parametrize(
    ("needle", "injection"),
    [
        (
            '"reason": null',
            '"reason": "P0_DUPLICATE_KEY_SECRET_7x9", "reason": null',
        ),
        (
            '"project_id_sha256":',
            (
                '"project_id_sha256": "P0_DUPLICATE_KEY_SECRET_7x9", '
                '"project_id_sha256":'
            ),
        ),
    ],
)
def test_artifact_guard_replaces_json_with_duplicate_keys_before_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    needle: str,
    injection: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    secret = "P0_DUPLICATE_KEY_SECRET_7x9"
    monkeypatch.setenv("NEON_API_KEY", secret)
    raw = json.dumps(report)
    assert needle in raw
    raw = raw.replace(needle, injection, 1)
    path = tmp_path / "report.json"
    path.write_text(raw, encoding="utf-8")

    assert ensure_artifact(path, live_outcome="success") is False
    recovered = path.read_text(encoding="utf-8")
    assert secret not in recovered
    assert json.loads(recovered)["failed_gate"] == (
        "artifact_guard_recovered_missing_or_invalid_report"
    )


@pytest.mark.parametrize(
    ("environment_name", "environment_value"),
    [
        ("NEON_API_KEY", "deadbeefcafebabe"),
        ("NEON_BOOTSTRAP_DATABASE_URL", "deadbeef"),
        ("NEON_PROJECT_ID", "cafebabedeadbeef"),
    ],
)
def test_artifact_guard_rejects_a_secret_embedded_inside_a_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    environment_value: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    secret = environment_value
    if environment_name == "NEON_BOOTSTRAP_DATABASE_URL":
        monkeypatch.setenv(
            environment_name,
            DSN.replace("synthetic_password", secret),
        )
    else:
        monkeypatch.setenv(environment_name, secret)
    report["neon"]["project_name_sha256"] = (secret + ("0" * 64))[:64]
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    ("environment_name", "padded", "normalized"),
    [
        ("NEON_PROJECT_ID", " abc1234 ", "abc1234"),
        ("NEON_ORG_ID", " deadbeef ", "deadbeef"),
    ],
)
def test_guard_scans_normalized_configured_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    padded: str,
    normalized: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv(environment_name, padded)
    if environment_name == "NEON_ORG_ID":
        report["neon"]["owner_id_sha256"] = base._fingerprint(normalized)
    report["neon"]["project_name_sha256"] = (
        normalized + ("0" * 64)
    )[:64]
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    ("environment_name", "environment_value"),
    [
        ("NEON_API_KEY", "OBSERVED"),
        ("NEON_BOOTSTRAP_DATABASE_URL", "OBSERVED"),
        ("NEON_BOOTSTRAP_DATABASE_URL", "readonly-v1"),
    ],
)
def test_fixed_vocabulary_collision_does_not_make_a_valid_go_look_secret_bearing(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    environment_value: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    if environment_name == "NEON_BOOTSTRAP_DATABASE_URL":
        monkeypatch.setenv(
            environment_name,
            DSN.replace("synthetic_password", environment_value),
        )
    else:
        monkeypatch.setenv(environment_name, environment_value)
    assert _valid_report(report) is True


@pytest.mark.parametrize(
    "environment_name",
    ["NEON_API_KEY", "NEON_BOOTSTRAP_DATABASE_URL"],
)
def test_secret_collision_with_a_dynamic_timestamp_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    timestamp = report["observed_at"]
    assert isinstance(timestamp, str)
    if environment_name == "NEON_BOOTSTRAP_DATABASE_URL":
        encoded = timestamp.replace(":", "%3A")
        monkeypatch.setenv(
            environment_name,
            DSN.replace("synthetic_password", encoded),
        )
    else:
        monkeypatch.setenv(environment_name, timestamp)
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    "field",
    ["dsn_security_profile", "effect_counter_certainty"],
)
def test_artifact_guard_requires_every_critical_go_field(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    del report[field]
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    "injected_key",
    ["checks", "postgresql", "github_actions", "lifecycle"],
)
def test_artifact_guard_rejects_unvalidated_no_go_subdocuments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    injected_key: str,
) -> None:
    path = tmp_path / "report.json"
    assert ensure_artifact(path) is False
    report = json.loads(path.read_text(encoding="utf-8"))
    report[injected_key] = {
        "debug": "opaque-raw-project-identity",
        "id": "raw-identity",
    }
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    "live_outcome",
    ["failure", "cancelled", "skipped", "unknown"],
)
def test_artifact_guard_never_preserves_a_go_after_non_successful_live_step(
    monkeypatch: pytest.MonkeyPatch,
    live_outcome: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    assert _valid_report(report, live_outcome=live_outcome) is False


@pytest.mark.parametrize("sslmode", ["require", "verify-ca", "verify-full"])
def test_pure_guard_accepts_configured_identity_and_all_secure_ssl_modes(
    monkeypatch: pytest.MonkeyPatch,
    sslmode: str,
) -> None:
    _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_PROJECT_ID", "project-production")
    neon = replace(
        _neon(state="active"),
        identity_path="CONFIGURED_PROJECT_ID",
        identity_verdict="CONFIGURED_PROJECT_IDENTITY_PROVEN",
        endpoint_detail_reads=1,
        branch_endpoint_reads=1,
        api_get_count=9,
    )
    checks = base.GateChecks(
        secrets_present=True,
        project_identity_verified=True,
        production_branch_verified=True,
        direct_endpoint_verified=True,
        ssl_verified=True,
        expected_revision_verified=True,
        bootstrap_authority_plausible=True,
        recovery_branch_feasible=True,
        purchase_required=False,
        github_queue_empty=True,
        github_in_progress_empty=True,
        github_dispatch_unique=True,
    )
    profile = base._target_dsn_security_profile(
        replace(_synthetic_target(), sslmode=sslmode)
    )
    monkeypatch.setenv(
        "NEON_BOOTSTRAP_DATABASE_URL",
        DSN.replace("sslmode=require", f"sslmode={sslmode}"),
    )
    report = base._report(
        checks=checks,
        decision=base.GateDecision(base.GO_VERDICT, None),
        neon=neon,
        database=_database(),
        queue_count=0,
        in_progress_count=0,
        dispatch_count=1,
        dsn_security_profile=profile,
    )
    assert _valid_report(report, report_schema=base.REPORT_SCHEMA) is True


@pytest.mark.parametrize(
    "field",
    [
        "NEON_API_KEY",
        "NEON_BOOTSTRAP_DATABASE_URL",
    ],
)
def test_artifact_guard_requires_live_secrets_for_go(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.delenv(field)
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PGHOST", "evil.example"),
        ("PGOPTIONS", "-c default_transaction_read_only=off"),
        ("PGSSLMODE", "disable"),
    ],
)
def test_artifact_guard_rejects_go_with_ambient_libpq_override(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv(name, value)
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "synthetic-dsn",
        "postgresql://[bad",
        (
            "postgresql://synthetic_user:synthetic_password@"
            "ep-wrong.neon.tech/synthetic_database?"
            "sslmode=disable&channel_binding=disable"
        ),
    ],
)
def test_artifact_guard_binds_go_to_the_canonical_environment_dsn(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_BOOTSTRAP_DATABASE_URL", database_url)
    assert _valid_report(report) is False


def test_artifact_guard_recovers_from_a_malformed_sensitive_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEON_BOOTSTRAP_DATABASE_URL", "postgresql://[bad")
    path = tmp_path / "report.json"
    assert ensure_artifact(path) is False
    serialized = path.read_text(encoding="utf-8")
    assert "postgresql://[bad" not in serialized
    assert json.loads(serialized)["verdict"] == base.NO_GO_VERDICT


def test_artifact_guard_fallback_cannot_collide_with_benign_dsn_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "NEON_BOOTSTRAP_DATABASE_URL",
        "postgresql://synthetic_user:read@ep-synthetic.neon.tech/readonly?"  # SECRET_SCANNER_TEST_FIXTURE
        "sslmode=require&channel_binding=require",
    )
    path = tmp_path / "report.json"
    assert ensure_artifact(path, live_outcome="failure") is False
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["verdict"] == base.NO_GO_VERDICT
    assert report["effect_counter_certainty"] == "CONSERVATIVE_UPPER_BOUNDS_ONLY"


@pytest.mark.parametrize(
    ("api_key", "password"),
    [
        ("api-z8q7w6v5", "pass-k4j3h2g1"),
        ("api-m9n8b7v6", "pass-c5x4z3a2"),
    ],
)
def test_valid_go_accepts_noncolliding_artifact_safe_credentials(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str,
    password: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_API_KEY", api_key)
    monkeypatch.setenv(
        "NEON_BOOTSTRAP_DATABASE_URL",
        (
            f"postgresql://synthetic_user:{password}@"
            "ep-synthetic.neon.tech/synthetic_database?"
            "sslmode=require&channel_binding=require"
        ),
    )
    assert _valid_report(report) is True


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("NEON_API_KEY", "a"),
        ("NEON_API_KEY", "deadbee"),
        ("NEON_BOOTSTRAP_DATABASE_URL", "read"),
        ("NEON_PROJECT_ID", "abc1234"),
        ("NEON_ORG_ID", "org1234"),
    ],
)
def test_guard_fails_closed_when_sensitive_values_are_too_short_to_scan(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    value: str,
) -> None:
    report = _run_synthetic(monkeypatch)
    if environment_name == "NEON_BOOTSTRAP_DATABASE_URL":
        monkeypatch.setenv(environment_name, DSN.replace("synthetic_password", value))
    else:
        monkeypatch.setenv(environment_name, value)
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("failed_gate", "xreadx"),
        ("neon.gate", "xreadx"),
        ("neon.region", "aws-xreadx-1"),
    ],
)
def test_short_password_substrings_are_never_accepted_in_external_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    monkeypatch.setenv(
        "NEON_BOOTSTRAP_DATABASE_URL",
        "postgresql://synthetic_user:read@ep-synthetic.neon.tech/readonly?"  # SECRET_SCANNER_TEST_FIXTURE
        "sslmode=require&channel_binding=require",
    )
    path = tmp_path / "report.json"
    assert ensure_artifact(path, report_schema=base.REPORT_SCHEMA) is False
    report = json.loads(path.read_text(encoding="utf-8"))
    if field.startswith("neon."):
        report["neon"] = {field.split(".", 1)[1]: value}
    else:
        report[field] = value
    assert (
        _valid_report(report, report_schema=base.REPORT_SCHEMA)
        is False
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("observed_at",), "project-production"),
        (("postgresql", "postgresql_version"), "project-production"),
        (("neon", "project_pages_read"), 0),
        (("neon", "endpoint_projects_inspected"), 0),
        (("neon", "endpoint_inventory_reads"), 0),
        (("neon", "endpoint_detail_reads"), 0),
        (("neon", "project_detail_reads"), 0),
        (("neon", "branch_pages_read"), 0),
        (("neon", "branch_endpoint_reads"), 0),
        (("neon", "recovery_parent_id_sha256"), "f" * 64),
        (("neon", "endpoint_host_sha256"), "f" * 64),
        (("postgresql", "database_name_sha256"), "f" * 64),
        (("postgresql", "lifecycle_admin_sha256"), "f" * 64),
        (("neon", "api_get_count"), 1),
        (("neon", "api_get_count"), 25),
        (("neon", "projects_observed"), 999),
        (("neon", "project_pages_read"), 25),
        (("neon", "owner_branch_count"), 0),
        (("neon", "target_project_branch_count"), 2),
        (("neon", "target_project_branch_count"), 0),
        (("neon", "endpoint_projects_inspected"), 2),
        (("neon", "branch_pages_read"), 2),
    ],
)
def test_artifact_guard_rejects_contradictory_or_identity_bearing_go_fields(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: object,
) -> None:
    report = _run_synthetic(monkeypatch)
    target: dict[str, Any] = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert _valid_report(report) is False


def test_artifact_guard_rejects_a_self_parented_production_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    report["neon"]["production_branch_parent_id_sha256"] = report["neon"][
        "production_branch_id_sha256"
    ]
    assert _valid_report(report) is False


def test_controlled_guard_treats_project_variable_as_sanitization_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_PROJECT_ID", "different-authoritative-project")
    assert _valid_report(report) is True


def test_artifact_guard_binds_go_to_explicit_organization_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_ORG_ID", "owner-shared")
    assert _valid_report(report) is True
    monkeypatch.setenv("NEON_ORG_ID", "owner-other")
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("neon", "endpoint_state"), "active"),
        (
            ("compute_wake_certainty",),
            "CONSERVATIVE_UPPER_BOUND_FROM_ACTIVE_SNAPSHOT",
        ),
        (("lifecycle", "configured_suspend_timeout_seconds"), 600),
        (("lifecycle", "effective_suspend_timeout_seconds"), 600),
        (("lifecycle", "scale_to_zero_classification"), "DEFAULT_SCALE_TO_ZERO"),
    ],
)
def test_artifact_guard_binds_controlled_lifecycle_to_neon_observation(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: object,
) -> None:
    report = _run_synthetic(monkeypatch)
    target: dict[str, Any] = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert _valid_report(report) is False


def test_pure_guard_requires_active_endpoint_and_configured_identity_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_synthetic(monkeypatch)
    monkeypatch.setenv("NEON_PROJECT_ID", "project-production")
    neon = replace(
        _neon(state="active"),
        identity_path="CONFIGURED_PROJECT_ID",
        identity_verdict="CONFIGURED_PROJECT_IDENTITY_PROVEN",
        endpoint_detail_reads=1,
        branch_endpoint_reads=1,
        api_get_count=9,
    )
    checks = base.GateChecks(
        secrets_present=True,
        project_identity_verified=True,
        production_branch_verified=True,
        direct_endpoint_verified=True,
        ssl_verified=True,
        expected_revision_verified=True,
        bootstrap_authority_plausible=True,
        recovery_branch_feasible=True,
        purchase_required=False,
        github_queue_empty=True,
        github_in_progress_empty=True,
        github_dispatch_unique=True,
    )
    report = base._report(
        checks=checks,
        decision=base.GateDecision(base.GO_VERDICT, None),
        neon=neon,
        database=_database(),
        queue_count=0,
        in_progress_count=0,
        dispatch_count=1,
        dsn_security_profile=base._target_dsn_security_profile(
            _synthetic_target()
        ),
    )
    assert _valid_report(report, report_schema=base.REPORT_SCHEMA)
    report["neon"]["endpoint_state"] = "idle"
    assert not _valid_report(report, report_schema=base.REPORT_SCHEMA)
    report["neon"]["endpoint_state"] = "active"
    monkeypatch.setenv("NEON_PROJECT_ID", "different-project")
    assert not _valid_report(report, report_schema=base.REPORT_SCHEMA)
    monkeypatch.delenv("NEON_PROJECT_ID")
    assert not _valid_report(report, report_schema=base.REPORT_SCHEMA)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", "project-production"),
        ("reason", "project-production"),
        ("failed_gate", "branch-production"),
    ],
)
def test_artifact_guard_rejects_identity_bearing_no_go_fields(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = tmp_path / "report.json"
    assert ensure_artifact(path) is False
    report = json.loads(path.read_text(encoding="utf-8"))
    report[field] = value
    assert _valid_report(report) is False


@pytest.mark.parametrize(
    "gate",
    ["opaque_raw_cursor", "branch_production", "endpoint_production"],
)
def test_artifact_guard_rejects_unlisted_no_go_gates(
    tmp_path: Path,
    gate: str,
) -> None:
    path = tmp_path / "report.json"
    assert ensure_artifact(path) is False
    report = json.loads(path.read_text(encoding="utf-8"))
    report["failed_gate"] = gate
    assert _valid_report(report) is False


def test_artifact_guard_classifies_defensive_budget_gates() -> None:
    for controlled_schema in (False, True):
        assert guard._no_go_phase(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "sql_budget_exhausted",
            controlled=controlled_schema,
        ) == "POSTGRESQL"
    assert guard._no_go_phase(
        "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
        "production_postgresql_connection_attempt_not_unique",
        controlled=True,
    ) == "POSTGRESQL"
    assert (
        guard._no_go_phase(
            "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
            "production_postgresql_connection_attempt_not_unique",
            controlled=False,
        )
        is None
    )


def test_artifact_guard_binds_no_go_reason_gate_phase_and_exact_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    early = controlled._controlled_no_go_report(
        base.PreflightNoGo("SECRET_MISSING", "missing:NEON_API_KEY"),
        controlled.ConnectionWakeAudit(),
    )
    assert _valid_report(early) is True
    for reason, gate in (
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_ref_mismatch"),
        ("RECOVERY_BRANCH_NOT_FEASIBLE", "github_main_ref_invalid"),
    ):
        authoritative_main_failure = controlled._controlled_no_go_report(
            base.PreflightNoGo(reason, gate),
            controlled.ConnectionWakeAudit(),
        )
        assert _valid_report(authoritative_main_failure) is True
        assert authoritative_main_failure["effects"]["neon_get_count"] == 0

    impossible_effects = deepcopy(early)
    impossible_effects["effects"].update(
        {
            "postgresql_connection_attempts": 1,
            "postgresql_connection_successes": 1,
            "sql_statement_count": 18,
            "sql_statement_completed_count": 18,
            "sql_read_attempt_count": 15,
            "sql_read_count": 15,
            "begin_read_only_attempted": 1,
            "begin_read_only_completed": 1,
            "rollback_attempted": 1,
            "rollback_completed": 1,
            "compute_wake_events": 1,
        }
    )
    impossible_effects["connection_attempt_count"] = 1
    impossible_effects["compute_wake_events"] = 1
    impossible_effects["lifecycle"].update(
        {
            "connection_attempt_count": 1,
            "connection_succeeded": True,
            "compute_wake_events": 1,
        }
    )
    assert _valid_report(impossible_effects) is False

    for reason, gate in (
        ("SECRET_MISSING", "postgresql_target_identity_mismatch"),
        ("UNEXPECTED_DATABASE_REVISION", "missing:NEON_API_KEY"),
        ("PURCHASE_REQUIRED", "postgresql_target_identity_mismatch"),
    ):
        mismatch = deepcopy(early)
        mismatch["reason"] = reason
        mismatch["failed_gate"] = gate
        assert _valid_report(mismatch) is False

    post_neon = controlled._controlled_no_go_report(
        base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_return_to_idle_not_proven",
            sanitized_evidence=base._sanitized_neon(
                replace(_neon(), suspend_timeout_seconds=-1)
            ),
        ),
        controlled.ConnectionWakeAudit(),
    )
    assert post_neon["effects"]["neon_get_count"] > 0
    assert _valid_report(post_neon) is True
    for mutation_count in (
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
    ):
        contradicted_mutation = deepcopy(post_neon)
        contradicted_mutation["neon"][mutation_count] = 1
        assert _valid_report(contradicted_mutation) is False
    missing_neon_proof = deepcopy(post_neon)
    missing_neon_proof.pop("neon")
    missing_neon_proof["effects"]["neon_get_count"] = 0
    assert _valid_report(missing_neon_proof) is False
    empty_neon_proof = deepcopy(post_neon)
    empty_neon_proof["neon"] = {}
    empty_neon_proof["effects"]["neon_get_count"] = 1
    assert _valid_report(empty_neon_proof) is False

    for reason, gate in (
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "identity_incomplete_before_connection"),
        ("RECOVERY_BRANCH_NOT_FEASIBLE", "branch_capacity_ambiguous"),
        ("RECOVERY_BRANCH_NOT_FEASIBLE", "branch_capacity_exhausted"),
        ("PURCHASE_REQUIRED", "purchase_required"),
        ("RECOVERY_BRANCH_NOT_FEASIBLE", "recovery_branch_not_feasible"),
        ("COMPUTE_RETURN_TO_IDLE_NOT_PROVEN", "compute_return_to_idle_not_proven"),
    ):
        contradicted = controlled._controlled_no_go_report(
            base.PreflightNoGo(
                reason,
                gate,
                sanitized_evidence=base._sanitized_neon(_neon()),
            ),
            controlled.ConnectionWakeAudit(),
        )
        assert _valid_report(contradicted) is False

    for reason, gate in (
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "configured_project_invalid"),
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "configured_project_not_accessible"),
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_owner_scope_identity_mismatch"),
        ("NEON_PROJECT_IDENTITY_AMBIGUOUS", "dsn_endpoint_match_missing"),
        ("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "default_branch_not_unique"),
        ("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "production_branch_not_ready"),
        ("ENDPOINT_STATE_UNSUPPORTED", "endpoint_state_unsupported"),
        ("RECOVERY_BRANCH_NOT_FEASIBLE", "branch_count_inventory_contradiction"),
    ):
        impossible_full_observation = controlled._controlled_no_go_report(
            base.PreflightNoGo(
                reason,
                gate,
                sanitized_evidence=base._sanitized_neon(_neon()),
            ),
            controlled.ConnectionWakeAudit(),
        )
        assert _valid_report(impossible_full_observation) is False

    pre_get_project = base._no_go_report(
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "configured_project_invalid",
    )
    assert _valid_report(
        pre_get_project,
        report_schema=base.REPORT_SCHEMA,
    ) is True
    pre_get_organization = controlled._controlled_no_go_report(
        base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "configured_organization_scope_mismatch",
            sanitized_evidence=base.IdentityAudit(
                identity_path="POSITIVE_ENDPOINT_WITNESS"
            ).sanitized(api_get_count=0),
        ),
        controlled.ConnectionWakeAudit(),
    )
    assert _valid_report(pre_get_organization) is True


def test_artifact_guard_rejects_generic_postgresql_gate_over_specific_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path,
        response_overrides={
            base.SQL_STATEMENTS[base.SQL_SSL]: [{"ssl": False}],
        },
    )
    assert report["failed_gate"] == "ssl_not_proven"
    assert _valid_report(report) is True
    partial_identity = deepcopy(report)
    partial_identity["neon"] = base.IdentityAudit(
        identity_path="BOUNDED_DISCOVERY"
    ).sanitized(api_get_count=report["effects"]["neon_get_count"])
    assert _valid_report(partial_identity) is False
    disguised = deepcopy(report)
    disguised["failed_gate"] = "postgresql_readonly_inspection_failed"
    assert _valid_report(disguised) is False

    close_failed, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path / "close",
        close_raises=True,
    )
    assert close_failed["failed_gate"] == "postgresql_connection_close_failed"
    assert _valid_report(close_failed) is True
    close_failed["failed_gate"] = "postgresql_readonly_inspection_failed"
    assert _valid_report(close_failed) is False

    terminal_passed, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path / "terminal-passed",
        response_overrides={
            base.SQL_STATEMENTS[base.SQL_DEFAULT_TRANSACTION_READ_ONLY]: [
                {"unexpected": "on"}
            ]
        },
    )
    assert terminal_passed["failed_gate"] == "postgresql_readonly_inspection_failed"
    assert _valid_report(terminal_passed) is True
    terminal_passed["postgresql"]["default_transaction_read_only"] = True
    assert _valid_report(terminal_passed) is False


def test_artifact_guard_binds_row_missing_timeout_and_revision_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    row_missing, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path,
        response_overrides={base.SQL_STATEMENTS[base.SQL_SSL]: []},
    )
    assert row_missing["failed_gate"] == "postgresql_row_missing"
    assert _valid_report(row_missing) is True
    disguised_row_missing = deepcopy(row_missing)
    disguised_row_missing["failed_gate"] = "postgresql_readonly_inspection_failed"
    assert _valid_report(disguised_row_missing) is False
    for observed in (True, False):
        contradicted = deepcopy(row_missing)
        contradicted["postgresql"]["ssl_verified"] = observed
        assert _valid_report(contradicted) is False

    timeout_invalid, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path / "timeout",
        response_overrides={
            base.SQL_STATEMENTS[base.SQL_STATEMENT_TIMEOUT]: [
                {"statement_timeout": "garbage"}
            ]
        },
    )
    assert timeout_invalid["failed_gate"] == "timeout_setting_invalid"
    assert _valid_report(timeout_invalid) is True
    disguised_timeout = deepcopy(timeout_invalid)
    disguised_timeout["failed_gate"] = "postgresql_readonly_inspection_failed"
    assert _valid_report(disguised_timeout) is False
    timeout_invalid["postgresql"]["statement_timeout_ms"] = 15_000
    assert _valid_report(timeout_invalid) is False

    unavailable, _cursor, _calls, _path = _run_boundary_integrated_main(
        monkeypatch,
        tmp_path / "revision",
        response_overrides={base.SQL_STATEMENTS[base.SQL_REVISION]: [{}]},
    )
    assert unavailable["failed_gate"] == "alembic_revision_unavailable"
    assert _valid_report(unavailable) is True
    unavailable["postgresql"]["revision_class"] = base.EXPECTED_REVISION
    unavailable["postgresql"]["revision_count"] = 1
    assert _valid_report(unavailable) is False


def test_main_recovers_a_first_serialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    monkeypatch.setattr(
        controlled,
        "run_preflight",
        lambda: {"schema_version": controlled.REPORT_SCHEMA, "bad": object()},
    )
    real_write = base._write_report
    calls = 0

    def fail_once(report_path: Path, report: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TypeError("synthetic serialization failure")
        real_write(report_path, report)

    monkeypatch.setattr(base, "_write_report", fail_once)
    monkeypatch.setattr(
        sys,
        "argv",
        ["chronos-controlled", "--report", str(path)],
    )
    controlled.main()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["verdict"] == NO_GO_VERDICT
    assert document["failed_gate"] == "report_serialization_or_write_failure"
