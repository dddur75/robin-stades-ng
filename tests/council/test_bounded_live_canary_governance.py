from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_V1"
SOURCE_HASH = "1dc339d2561fc97383c14fb3da10b17a6a2b754cba583937b0c0b399fecceda2"


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_capability_manifest_has_exactly_eight_fields_and_no_live_authority() -> None:
    manifest = _load("configs/execution/bounded-multi-league-live-canary-capability-v1.json")

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
    assert manifest["mission_id"] == MISSION_ID
    assert manifest["authorized_stages"] == ["E1"]
    assert manifest["maximum_stage"] == "E1"
    assert manifest["source_hash"] == SOURCE_HASH
    assert manifest == {
        "mission_id": MISSION_ID,
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": [
            "local_temporary_synthetic_capture_write",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ],
        "compute_budget": 5000,
        "time_budget": 345600,
        "source_hash": SOURCE_HASH,
        "expires_at": "2026-08-25T23:59:59Z",
    }
    serialized = json.dumps(manifest, sort_keys=True).casefold()
    assert "provider" not in serialized
    assert "secret" not in serialized
    assert "activation" not in serialized


def test_matrix_separates_capability_delivery_from_real_live_execution() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    authorization = matrix["authorization"]
    assert isinstance(authorization, dict)

    delivery = authorization["bounded_multi_league_live_canary_capability_v1_delivery"]
    real_live = authorization["bounded_multi_league_live_canary_capability_v1_real_live_execution"]
    effect_budget = authorization["bounded_multi_league_live_canary_capability_v1_effect_budget"]
    assert "CAPABILITY_DELIVERY_AUTHORIZED" in delivery
    assert "REAL_LIVE_EXECUTION_NOT_AUTHORIZED" in real_live
    assert "SEPARATE_EXTERNAL_OWNER_AUTHORIZATION" in real_live
    assert "REQUIRE_EXACT_BASE_780E224492CA9B689826857E9EDF6AA9AB95D8F5" in delivery
    assert "BRANCH_CODEX_BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_V1" in delivery
    assert "TITLED_BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_V1" in delivery
    assert effect_budget == (
        "LOCAL_TEMPORARY_SYNTHETIC_CAPTURE_WRITES_TEST_ONLY;"
        "LOCAL_TEMPORARY_SYNTHETIC_CAPTURE_WRITES_PYTEST_TMP_OR_OS_TEMP_ONLY;"
        "REAL_AUTHORIZATIONS_CREATED_0;REAL_ACTIVATIONS_CREATED_0;"
        "REAL_CAPTURE_ROOT_WRITES_0;REAL_PROVIDER_PAYLOAD_WRITES_0;"
        "PROVIDER_NETWORK_CALLS_0;PROVIDER_DNS_CALLS_0;"
        "REAL_PROVIDER_SECRET_READS_0;PURCHASES_0;REAL_BETS_0;PROMOTIONS_0;"
        "SOCIAL_PUBLICATIONS_0;PRODUCTION_DATABASE_EFFECTS_0;R2_EFFECTS_0;"
        "LIVE_WORKFLOW_DISPATCHES_0;REAL_BATCH_EXECUTIONS_0;REAL_SNAPSHOT_WRITES_0"
    )

    missions = matrix["missions"]
    assert isinstance(missions, dict)
    mission = missions[MISSION_ID]
    assert set(mission) == {
        "agents",
        "writer",
        "allowed_paths",
        "scale_ceiling",
        "delivery_keys",
    }
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E1"
    assert mission["agents"] == ["C0", "C2", "C4", "DP6"]
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
    }
    paths = mission["allowed_paths"]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths)) == 40
    assert (
        hashlib.sha256(
            json.dumps(paths, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        == "fafa054d0cb47f60367161f826696a119b86cf53f2eeb69bf31cb972acae55ea"
    )
    assert all(
        isinstance(path, str)
        and path
        and path == Path(path).as_posix()
        and not Path(path).is_absolute()
        and "\\" not in path
        and ":" not in path
        and not path.endswith("/")
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and not any(marker in path for marker in ("*", "?", "[", "]"))
        for path in paths
    )


def test_agent_report_schema_accepts_the_capability_mission_id() -> None:
    schema = _load("configs/agents/agent-report-schema-v3.json")
    mission_ids = schema["properties"]["mission_id"]["enum"]
    assert MISSION_ID in mission_ids


def test_three_independent_reports_are_schema_valid_and_aggregate_accepts() -> None:
    schema = _load("configs/agents/agent-report-schema-v3.json")
    reports = (
        "reports/council/bounded-live-canary-data-receipt-replay-review-v3.json",
        "reports/council/bounded-live-canary-security-review-v3.json",
        "reports/council/bounded-live-canary-governance-science-temporal-review-v3.json",
    )
    validator = Draft202012Validator(schema)
    agents: list[str] = []
    for path in reports:
        report = _load(path)
        validator.validate(report)
        assert report["mission_id"] == MISSION_ID
        agents.append(report["agent_id"])
    assert agents == ["DP6", "C4", "C2"]

    aggregate = _load("reports/council/bounded-live-canary-final-review-v3.json")
    assert aggregate["schema_version"] == "robin-bounded-live-canary-final-review-v3"
    assert aggregate["mission_id"] == MISSION_ID
    assert aggregate["claim_id"] == "GOV.BOUNDED_LIVE_CANARY.FINAL.REVIEW.V1.001"
    assert aggregate["aggregate_gate"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 4,
        "open_critical_threads": 0,
        "independent_review_count": 3,
        "required_axes_covered": True,
    }
    assert [review["agent_id"] for review in aggregate["reviewers"]] == agents
    assert all(review["verdict"] == "ACCEPT" for review in aggregate["reviewers"])
    assert aggregate["verdict"] == "ACCEPT_CAPABILITY_ONLY_FOR_DRAFT_DELIVERY"
    assert aggregate["delivery_gate"] == {
        "draft_delivery_authorized": True,
        "ready_for_review_authorized": False,
        "merge_authorized": False,
        "exact_head_ci": "PENDING",
        "github_review_threads": "NOT_OBSERVED_PRE_PR",
        "mergeable_state": "NOT_OBSERVED_PRE_PR",
        "required_merge_method": "MERGE_COMMIT",
    }
    assert aggregate["real_live_execution_authorized"] is False
    assert aggregate["real_execution_state"] == {
        "real_authorization": "NOT_CREATED",
        "real_activation": "NOT_CREATED",
        "provider_network_calls": 0,
        "provider_dns_calls": 0,
        "real_secret_reads": 0,
        "real_batch": "NOT_EXECUTED",
        "real_snapshot": "NOT_CREATED",
        "experiment_readiness": "NOT_ASSESSED_ON_REAL_DATA",
        "accumulation_candidates": [],
        "purchases": 0,
        "promotions": 0,
        "bets": 0,
    }
