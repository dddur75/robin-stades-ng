from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
import yaml

import robin.chronos_production as chronos_production
import scripts.check_data_torrent_recovery_v2_scope as scope_guard
import scripts.dispatch_data_torrent_recovery_v2_stage as controller
import scripts.materialize_data_torrent_recovery_v2_delivery_evidence as delivery_evidence
import scripts.recovery_v2_supervision as supervision
import scripts.verify_data_torrent_recovery_v2_postmerge_gate as final_gate
from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256,
    DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256,
    DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256,
    DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
    PRODUCTION_SAFETY_LOCKS,
    ChronosProductionError,
    data_torrent_recovery_v2_release_projection,
    validate_data_torrent_recovery_v2_authority,
    validate_data_torrent_recovery_v2_council_release,
    validate_data_torrent_recovery_v2_terminal_council_closure,
)
from robin.data_torrent.contracts import load_torrent_config
from scripts.check_chronos_github_hold_v3 import RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "configs" / "execution" / "data-torrent-recovery-v2.json"
EFFECT_CONTRACT = ROOT / "configs" / "execution" / "data-torrent-recovery-v2-effect-contract.json"
MATRIX = ROOT / "configs" / "agents" / "mission-activation-matrix-v3.json"
EVIDENCE_GRAPH = ROOT / "reports" / "evidence" / "evidence-graph.json"
SCALE_POLICY = ROOT / "configs" / "experiments" / "scale-policy-v3.json"
_TEST_EFFECT_DEADLINE_EPOCH = 1_788_152_400
_RECOVERY_V2_TEST_NOW = datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC)


def _test_authority_expiry(**_kwargs: object) -> datetime:
    return datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC)


def _canonical(document: object) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _single_path_projection(root: Path) -> dict[str, object]:
    return chronos_production._data_torrent_recovery_v2_projection(
        root,
        paths=("candidate.txt",),
        projection_schema="test-utf8-lf-v1",
        excluded_paths=[],
    )


def test_release_projection_is_utf8_lf_platform_invariant_and_content_sensitive(
    tmp_path: Path,
) -> None:
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    changed = tmp_path / "changed"
    for root, payload in (
        (lf, b"alpha\nbeta\n"),
        (crlf, b"alpha\r\nbeta\r\n"),
        (changed, b"alpha\ngamma\n"),
    ):
        root.mkdir()
        (root / "candidate.txt").write_bytes(payload)
    lf_projection = _single_path_projection(lf)
    crlf_projection = _single_path_projection(crlf)
    changed_projection = _single_path_projection(changed)
    assert lf_projection == crlf_projection
    assert lf_projection["projection_sha256"] != changed_projection["projection_sha256"]
    assert set(lf_projection["files"][0]) == {"path", "lf_sha256"}  # type: ignore[index]


@pytest.mark.parametrize("payload", [b"alpha\rbeta\n", b"\xff\xfe", b"alpha\x00beta\n"])
def test_release_projection_rejects_noncanonical_text(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "candidate.txt").write_bytes(payload)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        _single_path_projection(tmp_path)


def test_owner_manifest_is_exact_utf8_lf_and_hash_bound() -> None:
    payload = MANIFEST.read_bytes()
    document = json.loads(payload)
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    assert set(document) == {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    assert hashlib.sha256(payload).hexdigest() == DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256
    assert (
        hashlib.sha256(_canonical(document)).hexdigest()
        == DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256
    )
    assert document["source_hash"] == (
        "ff2e45ff7c6490919aa86900669c306e1d25c710f15db27f7c70861f1246bf31"
    )


def _live_counter_closure_fixture() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    actual = {"odds_dns_resolutions": 5}
    provider = {"dns_resolutions": 5}
    before = {
        "postgresql": {
            "read_transactions_attempted": 4,
            "function_reads_attempted": 5,
            "mutating_function_calls_attempted": 40,
            "connection_attempts_upper_bound": 49,
        },
        "odds": {"dns_resolutions_attempted": 5},
    }
    final = {
        "postgresql": {
            "read_transactions_attempted": 6,
            "function_reads_attempted": 5,
            "mutating_function_calls_attempted": 41,
            "connection_attempts_upper_bound": 52,
        },
        "odds": {"dns_resolutions_attempted": 5},
    }
    return actual, provider, before, final


def test_terminal_live_counter_closure_accepts_exact_hashed_call_graph_split() -> None:
    actual, provider, before, final = _live_counter_closure_fixture()
    chronos_production._validate_recovery_v2_terminal_live_counter_closure(
        actual=actual,
        provider=provider,
        live_runtime_before=before,
        live_runtime=final,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda actual, _provider, _before, _final: actual.__setitem__(
            "odds_dns_resolutions", 4
        ),
        lambda _actual, _provider, _before, final: cast(
            dict[str, object], final["odds"]
        ).__setitem__("dns_resolutions_attempted", 4),
        lambda _actual, _provider, _before, final: cast(
            dict[str, object], final["postgresql"]
        ).update(
            {
                "read_transactions_attempted": 1,
                "function_reads_attempted": 9,
                "mutating_function_calls_attempted": 41,
                "connection_attempts_upper_bound": 51,
            }
        ),
        lambda _actual, _provider, before, _final: cast(
            dict[str, object], before["postgresql"]
        ).update(
            {
                "read_transactions_attempted": 1,
                "function_reads_attempted": 9,
                "mutating_function_calls_attempted": 40,
                "connection_attempts_upper_bound": 50,
            }
        ),
    ],
)
def test_terminal_live_counter_closure_rejects_rebalanced_or_dns_mutants(
    mutate: object,
) -> None:
    actual, provider, before, final = _live_counter_closure_fixture()
    assert callable(mutate)
    mutate(actual, provider, before, final)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID",
    ):
        chronos_production._validate_recovery_v2_terminal_live_counter_closure(
            actual=actual,
            provider=provider,
            live_runtime_before=before,
            live_runtime=final,
        )


def test_terminal_live_response_observation_accepts_only_bound_time_window() -> None:
    capture_started = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
    dispatched_at = capture_started + timedelta(seconds=10)
    retrieved_at = dispatched_at + timedelta(seconds=1)
    terminal_at = retrieved_at + timedelta(seconds=1)
    capture_ended = terminal_at + timedelta(seconds=10)

    chronos_production._validate_recovery_v2_terminal_response_observation(
        retrieved_at=retrieved_at,
        dispatched_at=dispatched_at,
        terminal_at=terminal_at,
        capture_started=capture_started,
        capture_ended=capture_ended,
    )
    for mutant in (
        capture_started - timedelta(microseconds=1),
        capture_ended + timedelta(microseconds=1),
        dispatched_at - chronos_production._RECOVERY_V2_TERMINAL_CLOCK_SKEW - timedelta(
            microseconds=1
        ),
        terminal_at + chronos_production._RECOVERY_V2_TERMINAL_CLOCK_SKEW + timedelta(
            microseconds=1
        ),
    ):
        with pytest.raises(
            ChronosProductionError,
            match="CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID",
        ):
            chronos_production._validate_recovery_v2_terminal_response_observation(
                retrieved_at=mutant,
                dispatched_at=dispatched_at,
                terminal_at=terminal_at,
                capture_started=capture_started,
                capture_ended=capture_ended,
            )


@pytest.mark.parametrize(
    "field",
    (
        "raw_index_generated_at",
        "replay_generated_at",
        "quality_generated_at",
        "normalized_generated_at",
        "qa_generated_at",
        "manifest_generated_at",
    ),
)
def test_terminal_live_generated_chronology_rejects_each_reordered_timestamp(
    field: str,
) -> None:
    origin = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
    chronology = {
        "latest_retrieved_at": origin,
        "raw_index_generated_at": origin + timedelta(seconds=1),
        "capture_ended": origin + timedelta(seconds=2),
        "replay_generated_at": origin + timedelta(seconds=3),
        "quality_generated_at": origin + timedelta(seconds=4),
        "normalized_generated_at": origin + timedelta(seconds=5),
        "qa_generated_at": origin + timedelta(seconds=6),
        "manifest_generated_at": origin + timedelta(seconds=7),
    }
    chronos_production._validate_recovery_v2_terminal_generated_chronology(**chronology)
    chronology[field] = origin - timedelta(seconds=1)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_RECOVERY_V2_COUNCIL_RELEASE_INVALID",
    ):
        chronos_production._validate_recovery_v2_terminal_generated_chronology(**chronology)


@pytest.mark.parametrize(
    "mutation",
    ("endpoint", "method", "extra"),
)
def test_terminal_live_odds_request_contract_is_reconstructed_not_self_referential(
    mutation: str,
) -> None:
    config = load_torrent_config(ROOT / "configs/data/torrent-live-v2.json")
    anchor = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
    sport_key = "soccer_epl"
    expected = chronos_production._recovery_v2_terminal_expected_source_request_contract(
        family="ODDS",
        sport_key=sport_key,
        config=config,
        capture_started=anchor,
    )
    assert expected == {
        "schema_version": "robin-data-torrent-odds-request-v1",
        "method": "GET",
        "sanitized_endpoint": "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        "sport_key": "soccer_epl",
        "region": "eu",
        "markets": ["h2h", "totals"],
        "odds_format": "decimal",
        "date_format": "iso",
        "timeout_seconds": 30,
        "maximum_redirects": 0,
        "automatic_retries": 0,
        "certificate_verification_required": True,
        "environment_proxy_allowed": False,
    }
    mutant = deepcopy(expected)
    if mutation == "endpoint":
        mutant["sanitized_endpoint"] = "https://evil.example/v4/sports/soccer_epl/odds"
    elif mutation == "method":
        mutant["method"] = "POST"
    else:
        mutant["extra"] = True
    assert mutant != chronos_production._recovery_v2_terminal_expected_source_request_contract(
        family="ODDS",
        sport_key=sport_key,
        config=config,
        capture_started=anchor,
    )


def test_successor_effect_contract_is_exact_hash_bound_and_non_expanding() -> None:
    payload = EFFECT_CONTRACT.read_bytes()
    contract = json.loads(payload)
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    assert hashlib.sha256(payload).hexdigest() == (DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256)
    assert hashlib.sha256(_canonical(contract)).hexdigest() == (
        DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256
    )
    assert contract["expands_parent_authority"] is False
    assert contract["old_v1_authority_reuse"] is False
    assert contract["controller_pre_effect_gate"] == {
        "path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        "authority_guard_before_enable_and_dispatch": True,
        "full_hold_validations_before_enable": 2,
        "predecessor_attestation_and_semantic_validation_before_enable": True,
        "dispatch_ordinal_validation_before_enable": True,
        "final_main_ref_validation_before_enable": True,
        "pre_effect_proof_exact_schema": True,
        "pre_effect_proof_revalidated_in_mutation_child": True,
        "live_postmerge_holds_exact": 2,
        "live_postmerge_holds_identical": True,
        "github_run_id_decimal_digits_maximum": 18,
        "scope_guard_job_success_required": True,
        "mutation_order": ["ENABLE", "DISPATCH", "DISABLE"],
        "mutations_per_cycle": 3,
        "mutation_child_total_timeout_seconds": 15,
        "mutation_child_work_timeout_seconds": 11,
        "mutation_child_terminate_timeout_seconds": 2,
        "github_api_version": "2026-03-10",
        "dispatch_ref": "main",
        "dispatch_return_run_details": True,
        "dispatch_run_id_from_response": True,
        "terminal_run_observations_maximum": 3,
        "terminal_run_observations_are_retries": False,
        "terminal_artifact_attestation_gets_maximum": 3,
        "proxy_enabled": False,
        "redirects_enabled": False,
        "automatic_retries": 0,
        "disable_attempted_after_ambiguous_enable_or_dispatch": True,
        "disable_cleanup_target_allowlisted": True,
        "disable_cleanup_not_blocked_by_late_authority_or_lock_drift": True,
        "receipt_reservation_atomic_no_replace": True,
        "progress_receipt_atomic_replace": True,
        "receipt_file_fsync": True,
        "receipt_directory_ancestry_fsync": True,
    }
    assert contract["postmerge_workflow_quarantine"] == {
        "scale_stage": "E1",
        "invocations": 1,
        "workflow_paths": list(controller._QUARANTINE_WORKFLOWS),
        "initial_states_allowed": ["active", "disabled_manually"],
        "github_api_gets_maximum": 25,
        "disable_attempts_maximum": 4,
        "enable_mutations": 0,
        "dispatch_mutations": 0,
        "automatic_retries": 0,
        "mutation_child_total_timeout_seconds": 15,
        "progress_receipt_before_each_disable": True,
        "stop_after_first_ambiguous_disable": False,
        "continue_each_distinct_initially_active_workflow_once": True,
        "second_invocation_refused_before_get": True,
        "proxy_enabled": False,
        "redirects_enabled": False,
        "phase_budget_fungible": False,
        "provider_neutralization_receipt_required": True,
        "receipt_path": ".torrent/release/recovery-v2-postmerge-quarantine.json",
        "receipt_authoritative_without_live_revalidation": False,
        "progress_receipt_atomic_replace": True,
    }
    assert contract["legacy_provider_branch_neutralization"] == {
        "scale_stage": "E1",
        "branch": "codex/jalon-12-prospective-deep-data-observatory",
        "required_current_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
        "required_target": "EXACT_POSTMERGE_MAIN_SHA",
        "timing": "AFTER_POSTMERGE_SAFE_V2_GREEN_BEFORE_POSTMERGE_QUARANTINE",
        "authority_effect": "git_remote_write_non_force_within_successor_pr_budget",
        "delivery_slot": "ENGINEERING_REQUIRED",
        "controller_path": "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        "receipt_path": ".torrent/release/recovery-v2-provider-neutralization.json",
        "live_hold_validations_exact": 2,
        "github_api_gets_maximum": 24,
        "github_reads_charged_to_delivery_slot": "ENGINEERING_REQUIRED",
        "remote_ref_observations_maximum": 2,
        "fast_forward_ancestry_check": True,
        "ordinary_non_force_push": True,
        "push_attempts_maximum": 1,
        "server_non_fast_forward_rejection_required": True,
        "updates_maximum": 1,
        "non_fast_forward_updates": 0,
        "force_pushes": 0,
        "branch_deletes": 0,
        "automatic_retries": 0,
        "progress_receipt_atomic_replace": True,
    }
    assert contract["github_release_attestation_transport"] == {
        "api_host": "api.github.com",
        "artifact_download_host_suffixes": [
            ".actions.githubusercontent.com",
            ".blob.core.windows.net",
        ],
        "private_process": True,
        "maximum_response_bytes": 10_485_760,
        "child_total_timeout_seconds": 65,
        "child_work_timeout_seconds": 55,
        "child_terminate_timeout_seconds": 5,
        "proxy_enabled": False,
        "automatic_redirects_enabled": False,
        "validated_artifact_redirects_maximum": 1,
        "automatic_retries": 0,
        "ambient_gh_api_calls_in_v2_production_workflows": 0,
        "exact_main_reads_in_v2_production_workflows": 10,
        "github_run_id_decimal_digits_maximum": 18,
    }
    assert contract["effect_stage_supervision"] == {
        "helper_path": "scripts/recovery_v2_supervision.py",
        "deadline_environment": "RECOVERY_V2_EFFECT_DEADLINE_EPOCH",
        "fallback_precreated_before_checkout_setup_or_validation": True,
        "fallback_path_root": "RUNNER_TEMP",
        "fallback_precreated_before_child": True,
        "fallback_adoption_byte_exact": True,
        "pre_effect_failure_upload_always": True,
        "candidate_output_separate": True,
        "candidate_file_fsync_before_promotion": True,
        "promotion_atomic_after_validation": True,
        "promotion_directory_fsync": True,
        "success_requires_child_exit_zero_and_semantic_validation": True,
        "failure_export_sanitized": True,
        "child_process_group": True,
        "terminate_grace_seconds": 5,
        "kill_grace_seconds": 5,
        "finalization_margin_seconds": 20,
        "workflow_effect_deadline_seconds_maximum": {
            "RECOVERY_IDENTITY_V2": 600,
            "DURABLE_IDENTITY_SEAL_V2": 600,
            "PRODUCTION_PREFLIGHT_V2": 900,
            "MIGRATE_0015": 900,
            "VERIFY_0015": 900,
            "LIVE_ONCE": 1_200,
        },
        "post_effect_workflow_terminal_grace_seconds": {
            "RECOVERY_IDENTITY_V2": 630,
            "DURABLE_IDENTITY_SEAL_V2": 630,
            "PRODUCTION_PREFLIGHT_V2": 930,
            "MIGRATE_0015": 930,
            "VERIFY_0015": 930,
            "LIVE_ONCE": 1_230,
        },
        "terminal_status_propagation_margin_seconds": 30,
        "terminal_artifact_attestation_reserve_seconds": 210,
        "controller_terminalization_deadline_is_authority_bounded": True,
        "controller_terminalization_deadline_dispatched_to_workflow": False,
        "terminalization_completed_at_definition": (
            "REMOTE_TERMINALIZER_RETURNED_AND_TERMINAL_SEMANTICS_AND_LOCAL_CACHE_VALIDATED"
        ),
        "terminalization_completed_at_sampled_before_local_success_receipt_publication": True,
        "local_success_receipt_publication_is_external_authority": False,
        "terminalization_completion_must_not_exceed_controller_deadline": True,
        "latest_effect_admission_is_global_ceiling_not_full_cycle_guarantee": True,
        "stage_full_cycle_latest_admission_at": {
            "RECOVERY_IDENTITY_V2": "2026-09-06T12:22:58Z",
            "DURABLE_IDENTITY_SEAL_V2": "2026-09-06T12:22:58Z",
            "PRODUCTION_PREFLIGHT_V2": "2026-09-06T12:12:58Z",
            "MIGRATE_0015": "2026-09-06T12:12:58Z",
            "VERIFY_0015": "2026-09-06T12:12:58Z",
            "LIVE_ONCE": "2026-09-06T12:02:58Z",
        },
        "post_effect_closure_effects": [
            "github_artifact_upload",
            "github_workflow_terminal_state",
        ],
        "post_effect_production_api_calls_allowed": 0,
        "nonterminal_after_controller_deadline": "FAIL_AND_STOP_NO_RETRY",
        "outer_timeout_reserve_seconds": 120,
        "child_timeout_seconds_maximum": {
            "RECOVERY_IDENTITY_V2": 110,
            "DURABLE_IDENTITY_SEAL_V2": 480,
            "PRODUCTION_PREFLIGHT_V2": 780,
            "MIGRATE_0015": 780,
            "VERIFY_0015": 780,
            "LIVE_ONCE": 1_080,
        },
        "automatic_retries": 0,
    }
    assert contract["safe_v2_ci_budget"] == {
        "engineering_pull_requests_maximum": 2,
        "consolidated_exact_head_cycles_per_engineering_pr_maximum": 3,
        "engineering_exact_head_cycles_total_maximum": 6,
        "pr_c_phase_one_expected_hold_cycles": 1,
        "pr_c_candidate_exact_head_cycles": 1,
        "pr_c_postmerge_cycles": 1,
        "pr_c_cycles_total": 3,
        "failed_run_reruns": 0,
        "historical_ci_runs": 0,
        "phase_budgets_fungible": False,
    }
    assert contract["postmerge_scope_trigger"] == {
        "pull_request_head_ref": "codex/data-torrent-recovery-v2",
        "event_name": "push",
        "ref": "refs/heads/main",
        "merge_method": "merge",
        "merge_commit_subject_prefix": "[DATA_TORRENT_RECOVERY_V2] ",
        "merge_commit_subjects": [
            "[DATA_TORRENT_RECOVERY_V2] PR-A",
            "[DATA_TORRENT_RECOVERY_V2] PR-B",
            "[DATA_TORRENT_RECOVERY_V2] PR-C",
        ],
        "merge_commit_body": "",
        "merge_commit_parent_count": 2,
        "first_parent_binding": "github.event.before",
        "auto_merge": False,
        "squash": False,
        "rebase": False,
        "force": False,
    }
    assert contract["parent_manifest_raw_sha256"] == (DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256)
    assert contract["parent_manifest_canonical_sha256"] == (
        DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256
    )
    assert contract["scale_stage_mapping"] == {
        "E1": [
            "ENGINEERING_AND_INDEPENDENT_QA",
            "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION",
            "POSTMERGE_QUARANTINE",
        ],
        "E2": ["RECOVERY_IDENTITY_V2", "DURABLE_IDENTITY_SEAL_V2"],
        "E3A": ["PRODUCTION_PREFLIGHT_V2", "FOUR_RUNTIME_BINDINGS"],
        "E3B": ["MIGRATE_0015", "VERIFY_0015"],
        "E4": ["LIVE_ONCE", "REPLAY_100"],
    }
    assert contract["neon_phase_totals"] == {
        "recovery_identity_gets_maximum": 25,
        "preflight_gets_maximum": 39,
        "migrate_authority_validation_gets_maximum": 26,
        "mission_gets_maximum": 90,
        "phase_budgets_fungible": False,
    }
    migrate = contract["stage_effect_budgets"]["MIGRATE_0015"]
    bindings = contract["stage_effect_budgets"]["FOUR_RUNTIME_BINDINGS"]
    assert bindings["terminal_main_ref_validation_after_first_full_hold"] is True
    assert bindings["preflight_run_id_decimal_digits_maximum"] == 18
    assert bindings["secret_put_private_process"] is True
    assert bindings["secret_put_child_total_timeout_seconds"] == 15
    assert bindings["secret_put_child_work_timeout_seconds"] == 10
    assert bindings["secret_put_child_terminate_timeout_seconds"] == 2
    assert bindings["attestation_bounded_by_stage_outer_deadline"] is True
    assert bindings["preflight_expiry_revalidated_after_each_concurrency_inventory"] is True
    assert bindings["preflight_and_effect_deadline_revalidated_after_encryption"] is True
    assert bindings["secret_put_child_revalidates_external_deadline"] is True
    assert migrate["postgresql_drop_statements"] == 0
    assert migrate["retained_neutralized_bootstrap_executors"] == 1
    assert (
        migrate["bootstrap_executor_terminal_state"]
        == "NOLOGIN_PASSWORD_NULL_NO_MEMBERSHIPS_NO_CHRONOS_FUNCTIONAL_PRIVILEGES_NO_SESSIONS"
    )
    assert contract["forbidden_effects"]["postgresql_drop_statements"] == 0
    assert contract["r2_mission_totals"] == {
        "puts": 3,
        "gets": 3,
        "objects": 3,
        "lists": 0,
        "deletes": 0,
        "overwrites": 0,
        "retries": 0,
    }
    github = contract["github_read_budgets"]
    assert (
        sum(github["execution_stages"].values()) == github["execution_stages_total_maximum"] == 232
    )
    assert (
        sum(github["controller_cycles"].values())
        == github["controller_cycles_total_maximum"]
        == 192
    )
    assert sum(github["delivery_slots"].values()) == github["delivery_slots_total_maximum"] == 408
    assert github["engineering_required_delivery_breakdown"] == {
        "pull_request_and_safe_v2_reads_maximum": 112,
        "provider_pre_hold_gets_maximum": 12,
        "provider_post_hold_gets_maximum": 12,
        "total_maximum": 136,
        "phase_budget_fungible": False,
    }
    assert (
        sum(
            github["engineering_required_delivery_breakdown"][field]
            for field in (
                "pull_request_and_safe_v2_reads_maximum",
                "provider_pre_hold_gets_maximum",
                "provider_post_hold_gets_maximum",
            )
        )
        == github["delivery_slots"]["ENGINEERING_REQUIRED"]
    )
    assert github["postmerge_quarantine"] == 25
    assert github["mission_total_maximum"] == 232 + 192 + 408 + 25 == 857
    assert github["phase_budgets_fungible"] is False
    assert github["unclassified_github_reads"] == github["automatic_read_retries"] == 0
    assert github["artifact_downloads"] == {
        "execution_stages_maximum": 8,
        "controller_cycles_maximum": 6,
        "delivery_slots_maximum": 12,
        "mission_total_maximum": 26,
        "phase_budgets_fungible": False,
    }
    assert len(contract["qa_gates"]) == 22
    assert len(contract["terminal_artifacts"]) == 19


def test_recovery_authority_is_distinct_exact_and_time_limited() -> None:
    assert validate_data_torrent_recovery_v2_authority(
        scale_stage="E1",
        now=datetime(2026, 8, 30, 12, 46, 58, tzinfo=UTC),
    ) == datetime(2026, 9, 6, 12, 46, 58, tzinfo=UTC)
    with pytest.raises(ChronosProductionError, match="NOT_YET_ACTIVE"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E1",
            now=datetime(2026, 8, 30, 12, 46, 57, tzinfo=UTC),
        )
    with pytest.raises(ChronosProductionError, match="EFFECT_ADMISSION_CLOSED"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E4",
            now=datetime(2026, 9, 6, 12, 26, 58, tzinfo=UTC),
        )
    with pytest.raises(ChronosProductionError, match="TIME_BUDGET_EXHAUSTED"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E1",
            now=datetime(2026, 9, 6, 12, 46, 58, tzinfo=UTC),
        )
    with pytest.raises(ChronosProductionError, match="STAGE_INVALID"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="R1",
            now=datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC),
        )


def test_recovery_authority_rejects_byte_drift_before_any_effect(
    tmp_path: Path,
) -> None:
    execution = tmp_path / "configs" / "execution"
    execution.mkdir(parents=True)
    (execution / MANIFEST.name).write_bytes(MANIFEST.read_bytes())
    (execution / EFFECT_CONTRACT.name).write_bytes(EFFECT_CONTRACT.read_bytes() + b" ")
    with pytest.raises(ChronosProductionError, match="AUTHORITY_HASH_MISMATCH"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E1",
            now=datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC),
            repository_root=tmp_path,
        )


def _controller_receipt(tmp_path: Path, stage: str) -> Path:
    return (
        tmp_path
        / ".torrent"
        / "release"
        / f"recovery-v2-controller-{stage.casefold().replace('_', '-')}.json"
    )


def _quarantine_receipt(tmp_path: Path) -> Path:
    return tmp_path / ".torrent" / "release" / "recovery-v2-postmerge-quarantine.json"


def _provider_neutralization_receipt(tmp_path: Path) -> Path:
    return tmp_path / ".torrent" / "release" / "recovery-v2-provider-neutralization.json"


def _controller_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name, value in PRODUCTION_SAFETY_LOCKS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_council_release",
        lambda **_kwargs: "f" * 64,
    )
    monkeypatch.setattr(
        controller,
        "__file__",
        str(tmp_path / "scripts" / "dispatch_data_torrent_recovery_v2_stage.py"),
    )
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        controller,
        "_BINDINGS_RECEIPT",
        tmp_path / ".torrent" / "release" / "chronos-runtime-bindings-v2.json",
    )
    monkeypatch.setattr(
        controller,
        "_PREDECESSOR_CACHE_ROOT",
        tmp_path / ".torrent" / "release" / "recovery-v2-predecessor-cache",
    )
    monkeypatch.setattr(
        controller,
        "_LIVE_BUNDLE_CACHE_PATH",
        tmp_path / ".torrent" / "release" / "recovery-v2-live-bundle-cache.json",
    )
    monkeypatch.setattr(
        controller,
        "_validate_predecessor",
        lambda **_kwargs: {
            "predecessor_kind": "POST_MERGE_SAFE_V2",
            "predecessor_attestation": None,
            "predecessor_semantic_verdict": "POST_MERGE_SAFE_V2_GREEN",
            "predecessor_controller_receipt_sha256": None,
        },
    )
    monkeypatch.setattr(
        controller,
        "_validate_dispatch_ordinal",
        lambda **_kwargs: {
            "authority_window_not_before": chronos_production.DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
            "expected_prior_dispatches": 0,
            "observed_prior_dispatches": 0,
            "observed_prior_run_ids": [],
        },
    )
    monkeypatch.setattr(
        controller,
        "_validate_predecessor_controller_receipt",
        lambda **_kwargs: "e" * 64,
    )
    monkeypatch.setattr(
        controller,
        "_github_get",
        lambda *_args, **_kwargs: {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": "a" * 40},
        },
    )
    monkeypatch.setattr(
        controller,
        "_validate_provider_neutralization_receipt",
        lambda **_kwargs: {
            "path": ".torrent/release/recovery-v2-provider-neutralization.json",
            "sha256": "d" * 64,
            "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
        },
    )
    monkeypatch.setattr(
        controller,
        "_terminalize_current_stage",
        _synthetic_terminal_success,
    )


def _synthetic_terminal_success(**kwargs: object) -> dict[str, object]:
    stage = cast(str, kwargs["stage"])
    main_sha = cast(str, kwargs["main_sha"])
    run_id = int(cast(int, kwargs["run_id"]))
    workflow_path = f".github/workflows/{controller.STAGES[stage]['workflow']}"
    terminal_run = {
        "run_id": run_id,
        "run_attempt": 1,
        "workflow_path": workflow_path,
        "head_sha": main_sha,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "updated_at": "2026-08-30T12:50:00Z",
    }
    if stage == "LIVE_ONCE":
        return {
            "outcome": "SUCCESS",
            "terminal_run": terminal_run,
            "run_observations": 1,
            "attestation": {
                "schema_version": "github-artifact-bundle-attestation-v2",
                "repository": "dddur75/robin-stades-ng",
                "workflow_path": workflow_path,
                "run_id": str(run_id),
                "run_attempt": "1",
                "head_sha": main_sha,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "run_completed_observed_at": "2026-08-30T12:50:01Z",
                "artifact_id": 1000 + run_id,
                "artifact_name": f"data-torrent-live-v2-{run_id}",
                "archive_sha256": "c" * 64,
                "members": [],
            },
            "semantic_verdict": "DATA_TORRENT_READY",
            "semantic_projection_sha256": "d" * 64,
        }
    artifact = controller._SUCCESS_ARTIFACTS[stage]
    return {
        "outcome": "SUCCESS",
        "terminal_run": terminal_run,
        "run_observations": 1,
        "attestation": {
            "schema_version": "github-artifact-attestation-v2",
            "repository": "dddur75/robin-stades-ng",
            "workflow_path": workflow_path,
            "run_id": str(run_id),
            "run_attempt": "1",
            "head_sha": main_sha,
            "artifact_id": 1000 + run_id,
            "artifact_name": cast(str, artifact["artifact_prefix"]) + str(run_id),
            "payload_sha256": "b" * 64,
            "archive_sha256": "c" * 64,
        },
        "semantic_verdict": artifact["semantic_verdict"],
    }


def _controller_hold(main_sha: str = "a" * 40) -> dict[str, object]:
    return {
        "schema_version": "chronos-production-workflow-hold-live-v3",
        "verdict": "WORKFLOW_HOLD_ESTABLISHED",
        "active_after": 0,
        "disabled_after": len(RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS),
        "queued_after": 0,
        "in_progress_after": 0,
        "nonterminal_run_counts": {
            "requested": 0,
            "waiting": 0,
            "pending": 0,
            "queued": 0,
            "in_progress": 0,
        },
        "current_run_excluded": 0,
        "unauthorized_active_workflows": [],
        "post_merge_ci": {
            "workflow_path": ".github/workflows/ci-safe-v2.yml",
            "run_id": 99,
            "run_attempt": 1,
            "head_sha": main_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        },
        "recovery_v2_scope_guard": {
            "job_id": 100,
            "name": "Recovery V2 — scope guard exact",
            "run_id": 99,
            "head_sha": main_sha,
            "status": "completed",
            "conclusion": "success",
        },
        "legacy_secret_branch_sha": main_sha,
        "legacy_ci_workflow_quarantine": {
            "workflow_id": 900,
            "workflow_path": ".github/workflows/ci.yml",
            "state": "disabled_manually",
        },
        "recovery_v2_production_workflow_quarantine": [
            {
                "workflow_id": index,
                "workflow_path": path,
                "state": "disabled_manually",
            }
            for index, path in enumerate(sorted(RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS), 1)
        ],
        "production_environment_policy": {
            "environment": "chronos-control-plane-production",
            "can_admins_bypass": False,
            "protected_branches": False,
            "custom_branch_policies": True,
            "allowed_branches": ["main"],
        },
        "provider_calls": 0,
        "r2_operations": 0,
    }


def test_provider_neutralization_is_exact_cas_fast_forward_and_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_receipt_validator = controller._validate_provider_neutralization_receipt
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "b" * 40
    calls: list[tuple[str, ...]] = []
    observations = 0
    pre_hold = _controller_hold(main_sha)
    pre_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
    post_hold = _controller_hold(main_sha)

    def run_git(arguments: tuple[str, ...]) -> str:
        nonlocal observations
        calls.append(arguments)
        if arguments[0] == "ls-remote":
            observations += 1
            provider_sha = (
                chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
                if observations == 1
                else main_sha
            )
            return (
                f"{main_sha}\trefs/heads/main\n{provider_sha}\t{controller._LEGACY_PROVIDER_REF}\n"
            )
        return ""

    receipt_path = _provider_neutralization_receipt(tmp_path)
    receipt = controller.run_legacy_provider_branch_neutralization(
        main_sha=main_sha,
        receipt_path=receipt_path,
        git_runner=run_git,
        pre_hold_validator=lambda: pre_hold,
        post_hold_validator=lambda: post_hold,
    )
    expected_push = (
        "push",
        "--porcelain",
        controller._EXPECTED_PUSH_URL,
        f"{main_sha}:{controller._LEGACY_PROVIDER_REF}",
    )
    assert calls.count(expected_push) == 1
    assert all(not argument.startswith(("+", "--force")) for argument in expected_push)
    assert receipt == json.loads(receipt_path.read_bytes())
    assert receipt["verdict"] == "LEGACY_PROVIDER_BRANCH_NEUTRALIZED"
    assert receipt["push_attempts"] == 1
    assert receipt["remote_ref_observations"] == 2
    assert receipt["non_fast_forward_updates"] == 0
    assert receipt["confirmed_sha"] == main_sha
    assert real_receipt_validator(main_sha=main_sha) == {
        "path": ".torrent/release/recovery-v2-provider-neutralization.json",
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
    }

    calls.clear()
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=lambda arguments: calls.append(arguments) or "",
            pre_hold_validator=lambda: pytest.fail("second hold reached"),
            post_hold_validator=lambda: pytest.fail("second hold reached"),
        )
    assert calls == []


def test_provider_missing_token_uses_provider_error_before_reservation_or_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    receipt_path = _provider_neutralization_receipt(tmp_path)
    calls: list[tuple[str, ...]] = []
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TOKEN_MISSING",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha="b" * 40,
            receipt_path=receipt_path,
            git_runner=lambda arguments: calls.append(arguments) or "",
            pre_hold_validator=lambda: pytest.fail("hold reached"),
            post_hold_validator=lambda: pytest.fail("hold reached"),
        )
    assert calls == []
    assert not receipt_path.exists()


def test_provider_neutralization_shares_one_monotonic_deadline_across_git_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(controller.time, "monotonic", lambda: 500.0)
    main_sha = "b" * 40
    pre_hold = _controller_hold(main_sha)
    pre_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
    post_hold = _controller_hold(main_sha)
    deadlines: list[tuple[float | None, float | None]] = []
    observations = 0

    def run_git(
        arguments: tuple[str, ...],
        *,
        effect_deadline_epoch: float | None = None,
        effect_deadline_monotonic: float | None = None,
    ) -> str:
        nonlocal observations
        deadlines.append((effect_deadline_epoch, effect_deadline_monotonic))
        if arguments[0] == "ls-remote":
            observations += 1
            provider_sha = (
                chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
                if observations == 1
                else main_sha
            )
            return (
                f"{main_sha}\trefs/heads/main\n"
                f"{provider_sha}\t{controller._LEGACY_PROVIDER_REF}\n"
            )
        return ""

    monkeypatch.setattr(controller, "_run_bounded_git", run_git)
    controller.run_legacy_provider_branch_neutralization(
        main_sha=main_sha,
        receipt_path=_provider_neutralization_receipt(tmp_path),
        pre_hold_validator=lambda: pre_hold,
        post_hold_validator=lambda: post_hold,
    )
    assert len(deadlines) == 6
    assert len({deadline[0] for deadline in deadlines}) == 1
    assert len({deadline[1] for deadline in deadlines}) == 1
    assert deadlines[0] == (1_300.0, 800.0)


def test_provider_neutralization_refuses_stale_source_and_consumes_reserved_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "b" * 40
    calls: list[tuple[str, ...]] = []
    pre_hold = _controller_hold(main_sha)
    pre_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA

    def run_git(arguments: tuple[str, ...]) -> str:
        calls.append(arguments)
        if arguments[0] == "remote":
            return controller._EXPECTED_PUSH_URL + "\n"
        if arguments[0] == "ls-remote":
            return f"{main_sha}\trefs/heads/main\n{'c' * 40}\t{controller._LEGACY_PROVIDER_REF}\n"
        return ""

    receipt_path = _provider_neutralization_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_PRECONDITION_INVALID",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=run_git,
            pre_hold_validator=lambda: pre_hold,
            post_hold_validator=lambda: pytest.fail("post hold reached"),
        )
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["push_attempts"] == 0
    assert failure["remote_ref_observations"] == 1
    assert not any(arguments[0] == "push" for arguments in calls)


def test_provider_neutralization_ambiguous_push_is_consumed_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "b" * 40
    push_attempts = 0
    pre_hold = _controller_hold(main_sha)
    pre_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA

    def run_git(arguments: tuple[str, ...]) -> str:
        nonlocal push_attempts
        if arguments[0] == "remote":
            return controller._EXPECTED_PUSH_URL + "\n"
        if arguments[0] == "ls-remote":
            return (
                f"{main_sha}\trefs/heads/main\n"
                f"{chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA}"
                f"\t{controller._LEGACY_PROVIDER_REF}\n"
            )
        if arguments[0] == "push":
            push_attempts += 1
            raise controller.RecoveryV2ControllerError("RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS")
        return ""

    receipt_path = _provider_neutralization_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=run_git,
            pre_hold_validator=lambda: pre_hold,
            post_hold_validator=lambda: pytest.fail("post hold reached"),
        )
    assert push_attempts == 1
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["push_attempts"] == 1

    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=lambda _arguments: pytest.fail("second git call reached"),
            pre_hold_validator=lambda: pytest.fail("second hold reached"),
            post_hold_validator=lambda: pytest.fail("second hold reached"),
        )
    assert push_attempts == 1


def test_provider_neutralization_reserves_post_push_observation_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "b" * 40
    pre_hold = _controller_hold(main_sha)
    pre_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
    observations = 0

    def run_git(arguments: tuple[str, ...]) -> str:
        nonlocal observations
        if arguments[0] == "ls-remote":
            observations += 1
            if observations == 2:
                raise controller.RecoveryV2ControllerError(
                    "RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS"
                )
            return (
                f"{main_sha}\trefs/heads/main\n"
                f"{chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA}"
                f"\t{controller._LEGACY_PROVIDER_REF}\n"
            )
        return ""

    receipt_path = _provider_neutralization_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=run_git,
            pre_hold_validator=lambda: pre_hold,
            post_hold_validator=lambda: pytest.fail("post hold reached"),
        )
    failure = json.loads(receipt_path.read_bytes())
    assert observations == 2
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["push_attempts"] == 1
    assert failure["remote_ref_observations"] == 2


def test_provider_neutralization_requires_postmerge_safe_hold_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "b" * 40
    failed_hold = _controller_hold(main_sha)
    failed_hold["legacy_secret_branch_sha"] = chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
    failed_hold["post_merge_ci"]["conclusion"] = "failure"  # type: ignore[index]
    receipt_path = _provider_neutralization_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_PRECONDITION_INVALID",
    ):
        controller.run_legacy_provider_branch_neutralization(
            main_sha=main_sha,
            receipt_path=receipt_path,
            git_runner=lambda _arguments: pytest.fail("git reached before SAFE V2 hold"),
            pre_hold_validator=lambda: failed_hold,
            post_hold_validator=lambda: pytest.fail("post hold reached"),
        )
    failure = json.loads(receipt_path.read_bytes())
    assert failure == {
        "automatic_retries": 0,
        "branch": controller._LEGACY_PROVIDER_BRANCH,
        "schema_version": (
            "data-torrent-recovery-v2-provider-neutralization-reservation-v1"
        ),
        "target_main_sha": main_sha,
        "verdict": "FAIL_AND_STOP",
    }


def test_bounded_git_strips_ambient_git_and_token_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.https://evil.invalid/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")
    monkeypatch.setenv("GIT_SSH_COMMAND", "untrusted")
    monkeypatch.setenv("GIT_EXEC_PATH", "untrusted")
    monkeypatch.setenv("GH_TOKEN", "not-forwarded")
    monkeypatch.setenv("GITHUB_TOKEN", "not-forwarded")
    captured: dict[str, object] = {}

    def captured_run(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
        absolute_deadline_monotonic: float | None = None,
        cleanup_deadline_monotonic: float | None = None,
    ) -> supervision.CapturedChildResult:
        captured["arguments"] = arguments
        captured["cwd"] = cwd
        captured["environment"] = dict(environment)
        captured["timeout_seconds"] = timeout_seconds
        captured["maximum_stdout_bytes"] = maximum_stdout_bytes
        captured["maximum_stderr_bytes"] = maximum_stderr_bytes
        captured["absolute_deadline_monotonic"] = absolute_deadline_monotonic
        captured["cleanup_deadline_monotonic"] = cleanup_deadline_monotonic
        return supervision.CapturedChildResult(returncode=0, stdout=b"", stderr=b"")

    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)
    monkeypatch.setattr(controller, "run_captured_child_once", captured_run)
    assert controller._run_bounded_git(("cat-file", "-e", f"{'a' * 40}^{{commit}}")) == ""
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert "GH_TOKEN" not in environment
    assert "GITHUB_TOKEN" not in environment
    assert "GIT_CONFIG_COUNT" not in environment
    assert "GIT_CONFIG_KEY_0" not in environment
    assert "GIT_CONFIG_VALUE_0" not in environment
    assert "GIT_SSH_COMMAND" not in environment
    assert "GIT_EXEC_PATH" not in environment
    command = captured["arguments"]
    assert isinstance(command, tuple)
    assert "push.followTags=false" in command
    assert "push.recurseSubmodules=no" in command
    assert "http.followRedirects=false" in command
    assert "protocol.allow=never" in command
    assert captured["timeout_seconds"] == controller._GIT_COMMAND_TIMEOUT_SECONDS
    assert captured["maximum_stdout_bytes"] == controller._GIT_OUTPUT_LIMIT_BYTES
    assert captured["maximum_stderr_bytes"] == controller._GIT_OUTPUT_LIMIT_BYTES
    assert captured["absolute_deadline_monotonic"] is None
    assert captured["cleanup_deadline_monotonic"] is None


def test_bounded_git_sanitizes_unconfirmed_process_tree_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)

    def unconfirmed_tree(*args: object, **kwargs: object) -> supervision.CapturedChildResult:
        raise controller.RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
        )

    monkeypatch.setattr(controller, "run_captured_child_once", unconfirmed_tree)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS",
    ):
        controller._run_bounded_git(("cat-file", "-e", f"{'a' * 40}^{{commit}}"))


def test_bounded_network_git_reserves_tree_termination_before_effect_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(controller.time, "monotonic", lambda: 500.0)
    observed: dict[str, object] = {}

    def captured_run(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
        absolute_deadline_monotonic: float | None = None,
        cleanup_deadline_monotonic: float | None = None,
    ) -> supervision.CapturedChildResult:
        observed["timeout_seconds"] = timeout_seconds
        observed["absolute_deadline_monotonic"] = absolute_deadline_monotonic
        observed["cleanup_deadline_monotonic"] = cleanup_deadline_monotonic
        return supervision.CapturedChildResult(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(controller, "run_captured_child_once", captured_run)
    controller._run_bounded_git(
        (
            "ls-remote",
            "--refs",
            controller._EXPECTED_PUSH_URL,
            "refs/heads/main",
            controller._LEGACY_PROVIDER_REF,
        ),
        effect_deadline_epoch=1_032.5,
    )
    assert observed["timeout_seconds"] == 1
    assert observed["absolute_deadline_monotonic"] == 501.5
    assert observed["cleanup_deadline_monotonic"] == 532.5


def test_bounded_network_git_rejects_missing_tree_termination_reserve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(controller.time, "monotonic", lambda: 500.0)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED",
    ):
        controller._run_bounded_git(
            (
                "ls-remote",
                "--refs",
                controller._EXPECTED_PUSH_URL,
                "refs/heads/main",
                controller._LEGACY_PROVIDER_REF,
            ),
            effect_deadline_epoch=1_032.0,
        )


def test_bounded_network_git_cannot_recover_time_from_wall_clock_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)
    wall_values = iter((1_000.0, 900.0, 900.0))
    monotonic_values = iter((500.0, 507.5, 507.5))
    monkeypatch.setattr(controller.time, "time", lambda: next(wall_values))
    monkeypatch.setattr(controller.time, "monotonic", lambda: next(monotonic_values))
    observed: dict[str, int] = {}

    def captured_run(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: int,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
        absolute_deadline_monotonic: float | None = None,
        cleanup_deadline_monotonic: float | None = None,
    ) -> supervision.CapturedChildResult:
        observed["timeout_seconds"] = timeout_seconds
        observed["absolute_deadline_monotonic"] = absolute_deadline_monotonic
        observed["cleanup_deadline_monotonic"] = cleanup_deadline_monotonic
        return supervision.CapturedChildResult(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(controller, "run_captured_child_once", captured_run)
    controller._run_bounded_git(
        (
            "ls-remote",
            "--refs",
            controller._EXPECTED_PUSH_URL,
            "refs/heads/main",
            controller._LEGACY_PROVIDER_REF,
        ),
        effect_deadline_epoch=1_040.0,
    )
    assert observed["timeout_seconds"] == 1
    assert observed["absolute_deadline_monotonic"] == 509.0
    assert observed["cleanup_deadline_monotonic"] == 540.0


def test_bounded_network_git_rejects_monotonic_deadline_crossed_by_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)
    monotonic_values = iter((500.0, 500.0, 540.0))
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(controller.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        controller,
        "run_captured_child_once",
        lambda *args, **kwargs: supervision.CapturedChildResult(
            returncode=0, stdout=b"", stderr=b""
        ),
    )
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS",
    ):
        controller._run_bounded_git(
            (
                "ls-remote",
                "--refs",
                controller._EXPECTED_PUSH_URL,
                "refs/heads/main",
                controller._LEGACY_PROVIDER_REF,
            ),
            effect_deadline_epoch=1_040.0,
        )


@pytest.mark.parametrize(
    ("result", "accepted"),
    (
        (supervision.CapturedChildResult(0, b"x" * 65_536, b""), True),
        (supervision.CapturedChildResult(0, b"", b"x" * 65_536), True),
        (supervision.CapturedChildResult(0, b"x" * 65_537, b""), False),
        (supervision.CapturedChildResult(0, b"", b"x" * 65_537), False),
        (supervision.CapturedChildResult(1, b"", b""), False),
        (supervision.CapturedChildResult(0, b"", b"\xff"), False),
    ),
)
def test_bounded_git_validates_both_raw_streams_and_return_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: supervision.CapturedChildResult,
    accepted: bool,
) -> None:
    object_directory = tmp_path / "objects"
    object_directory.mkdir()
    monkeypatch.setattr(controller, "_local_git_object_directory", lambda _environment: object_directory)

    def captured_run(
        arguments: tuple[str, ...],
        **kwargs: object,
    ) -> supervision.CapturedChildResult:
        if arguments[1:3] == ("init", "--bare"):
            return supervision.CapturedChildResult(0, b"", b"")
        return result

    monkeypatch.setattr(controller, "run_captured_child_once", captured_run)
    arguments = ("cat-file", "-e", f"{'a' * 40}^{{commit}}")
    if accepted:
        assert len(controller._run_bounded_git(arguments)) == len(result.stdout)
        return
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_PROVIDER_TRANSPORT_AMBIGUOUS",
    ):
        controller._run_bounded_git(arguments)


def _migrate_controller_inputs(main_sha: str = "a" * 40) -> dict[str, str]:
    return {
        "mode": "MIGRATE",
        "expected_main_sha": main_sha,
        "post_merge_ci_sha": main_sha,
        "preflight_run_id": "41",
        "runtime_bindings_receipt_b64": "e30K",
        "recovery_v2_effect_deadline_epoch": str(_TEST_EFFECT_DEADLINE_EPOCH),
        "recovery_v2_dispatch_nonce": "f" * 64,
    }


def _migrate_pre_effect_proof(main_sha: str = "a" * 40) -> dict[str, object]:
    hold = _controller_hold(main_sha)
    inputs = _migrate_controller_inputs(main_sha)
    return {
        "stage_inputs": inputs,
        "predecessor_kind": "PREFLIGHT",
        "predecessor_attestation": {
            "schema_version": "github-artifact-attestation-v2",
            "repository": "dddur75/robin-stades-ng",
            "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
            "run_id": "41",
            "run_attempt": "1",
            "head_sha": main_sha,
            "artifact_id": 141,
            "artifact_name": "production-preflight-v2-41",
            "payload_sha256": "b" * 64,
            "archive_sha256": "c" * 64,
        },
        "predecessor_semantic_verdict": "CHRONOS_MIGRATION_READY",
        "predecessor_controller_receipt_sha256": "e" * 64,
        "expected_prior_run_ids": [41],
        "authority_window_not_before": chronos_production.DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
        "expected_prior_dispatches": 1,
        "observed_prior_dispatches": 1,
        "observed_prior_run_ids": [41],
        "post_merge_ci_run_id": 99,
        "global_hold_full_validations": 2,
        "live_postmerge_holds": [hold, deepcopy(hold)],
        "live_postmerge_hold_sha256": controller._object_sha256(hold),
        "current_main_sha": main_sha,
    }


def _write_controller_gate_receipt(
    path: Path,
    *,
    stage: str,
    main_sha: str,
    proof: dict[str, object],
    operation: str,
) -> tuple[str, str]:
    inputs = proof["stage_inputs"]
    assert isinstance(inputs, dict)
    inputs_sha256 = controller._inputs_sha256(inputs)
    proof_sha256 = controller._object_sha256(proof)
    attempted = ["ENABLE"] if operation == "ENABLE" else ["ENABLE", "DISPATCH"]
    confirmed = [] if operation == "ENABLE" else ["ENABLE"]
    receipt = {
        "schema_version": "data-torrent-recovery-v2-controller-cycle-v1",
        "verdict": "PRE_EFFECT_GATES_CONFIRMED",
        "stage": stage,
        "main_sha": main_sha,
        "inputs_sha256": inputs_sha256,
        "automatic_retries": 0,
        "mutations_attempted": attempted,
        "mutations_confirmed": confirmed,
        "pre_effect_proof": proof,
        "pre_effect_proof_sha256": proof_sha256,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return inputs_sha256, proof_sha256


def test_mutation_envelope_reproves_exact_causal_pre_effect_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "a" * 40
    stage = "MIGRATE_0015"
    proof = _migrate_pre_effect_proof(main_sha)
    receipt_path = _controller_receipt(tmp_path, stage)
    inputs_sha256, proof_sha256 = _write_controller_gate_receipt(
        receipt_path,
        stage=stage,
        main_sha=main_sha,
        proof=proof,
        operation="ENABLE",
    )
    controller._validate_mutation_envelope(
        stage=stage,
        main_sha=main_sha,
        inputs_sha256=inputs_sha256,
        pre_effect_proof_sha256=proof_sha256,
        receipt_path=receipt_path,
        effect_deadline_epoch=float(_TEST_EFFECT_DEADLINE_EPOCH),
        method="PUT",
        path=(
            "/repos/dddur75/robin-stades-ng/actions/workflows/"
            "chronos-production-bootstrap-v4.yml/enable"
        ),
        payload=None,
    )


def test_mutation_envelope_rejects_rehashed_semantic_proof_mutants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    main_sha = "a" * 40
    stage = "MIGRATE_0015"
    base = _migrate_pre_effect_proof(main_sha)

    def extra_field(proof: dict[str, object]) -> None:
        proof["forged"] = True

    def boolean_hold_count(proof: dict[str, object]) -> None:
        proof["global_hold_full_validations"] = True

    def second_hold_scope_drift(proof: dict[str, object]) -> None:
        holds = proof["live_postmerge_holds"]
        assert isinstance(holds, list) and isinstance(holds[1], dict)
        scope = holds[1]["recovery_v2_scope_guard"]
        assert isinstance(scope, dict)
        scope["job_id"] = 101

    def workflow_inventory_drift(proof: dict[str, object]) -> None:
        holds = proof["live_postmerge_holds"]
        assert isinstance(holds, list) and isinstance(holds[0], dict)
        inventory = holds[0]["recovery_v2_production_workflow_quarantine"]
        assert isinstance(inventory, list) and isinstance(inventory[0], dict)
        inventory[0]["state"] = "active"

    def causal_input_drift(proof: dict[str, object]) -> None:
        inputs = proof["stage_inputs"]
        assert isinstance(inputs, dict)
        inputs["preflight_run_id"] = "42"

    def ordinal_drift(proof: dict[str, object]) -> None:
        proof["expected_prior_run_ids"] = [42]
        proof["observed_prior_run_ids"] = [42]

    def attestation_drift(proof: dict[str, object]) -> None:
        attestation = proof["predecessor_attestation"]
        assert isinstance(attestation, dict)
        attestation["workflow_path"] = ".github/workflows/data-torrent-live-v2.yml"

    mutations = (
        extra_field,
        boolean_hold_count,
        second_hold_scope_drift,
        workflow_inventory_drift,
        causal_input_drift,
        ordinal_drift,
        attestation_drift,
    )
    receipt_path = _controller_receipt(tmp_path, stage)
    for mutate in mutations:
        proof = deepcopy(base)
        mutate(proof)
        inputs_sha256, proof_sha256 = _write_controller_gate_receipt(
            receipt_path,
            stage=stage,
            main_sha=main_sha,
            proof=proof,
            operation="ENABLE",
        )
        with pytest.raises(
            controller.RecoveryV2ControllerError,
            match="RECOVERY_V2_CONTROLLER_MUTATION_INVALID",
        ):
            controller._validate_mutation_envelope(
                stage=stage,
                main_sha=main_sha,
                inputs_sha256=inputs_sha256,
                pre_effect_proof_sha256=proof_sha256,
                    receipt_path=receipt_path,
                    effect_deadline_epoch=float(_TEST_EFFECT_DEADLINE_EPOCH),
                    method="PUT",
                path=(
                    "/repos/dddur75/robin-stades-ng/actions/workflows/"
                    "chronos-production-bootstrap-v4.yml/enable"
                ),
                payload=None,
            )


@pytest.mark.parametrize(
    ("stage", "prior_run_ids"),
    [
        ("RECOVERY_IDENTITY_V2", []),
        ("DURABLE_IDENTITY_SEAL_V2", []),
        ("PRODUCTION_PREFLIGHT_V2", []),
        ("MIGRATE_0015", [101]),
        ("VERIFY_0015", [101, 102]),
        ("LIVE_ONCE", []),
    ],
)
def test_dispatch_ordinal_accepts_exact_causal_history_for_all_six_cycles(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    prior_run_ids: list[int],
) -> None:
    runs = [
        {
            "id": run_id,
            "created_at": f"2026-08-30T12:47:{index:02d}Z",
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        for index, run_id in enumerate(prior_run_ids)
    ]
    monkeypatch.setattr(
        controller,
        "_github_get",
        lambda *_args, **_kwargs: {"total_count": len(runs), "workflow_runs": runs},
    )
    result = controller._validate_dispatch_ordinal(
        stage=stage,
        main_sha="a" * 40,
        inputs={},
        token="synthetic-token",
        expected_prior_run_ids=prior_run_ids,
    )
    assert result["expected_prior_dispatches"] == len(prior_run_ids)
    assert result["observed_prior_run_ids"] == prior_run_ids


def test_dispatch_ordinal_rejects_wrong_order_duplicate_or_extra_authority_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = [
        {
            "id": run_id,
            "created_at": f"2026-08-30T12:47:{index:02d}Z",
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        for index, run_id in enumerate((101, 102))
    ]
    monkeypatch.setattr(
        controller,
        "_github_get",
        lambda *_args, **_kwargs: {"total_count": len(runs), "workflow_runs": runs},
    )
    for expected in ([102, 101], [101, 101], [101, 102, 103]):
        with pytest.raises(
            controller.RecoveryV2ControllerError,
            match="RECOVERY_V2_CONTROLLER_ORDINAL_INVALID",
        ):
            controller._validate_dispatch_ordinal(
                stage="VERIFY_0015",
                main_sha="a" * 40,
                inputs={},
                token="synthetic-token",
                expected_prior_run_ids=expected,
            )
    extra = deepcopy(runs[-1])
    extra["id"] = 103
    extra["created_at"] = "2026-08-30T12:47:03Z"
    runs.append(extra)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_ORDINAL_INVALID",
    ):
        controller._validate_dispatch_ordinal(
            stage="VERIFY_0015",
            main_sha="a" * 40,
            inputs={},
            token="synthetic-token",
            expected_prior_run_ids=[101, 102],
        )


def test_controller_authority_guard_precedes_hold_enable_and_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    external_calls: list[str] = []

    def refuse(**_kwargs: object) -> None:
        raise ChronosProductionError("synthetic refusal")

    monkeypatch.setattr(controller, "validate_data_torrent_recovery_v2_authority", refuse)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_AUTHORITY_INVALID",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=_controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2"),
            hold_validator=lambda: external_calls.append("HOLD") or {},
            mutator=lambda **_kwargs: external_calls.append("MUTATION"),
        )
    assert external_calls == []


@pytest.mark.parametrize(
    ("stage", "effect_seconds", "terminal_grace_seconds"),
    (
        ("RECOVERY_IDENTITY_V2", 600, 630),
        ("DURABLE_IDENTITY_SEAL_V2", 600, 630),
        ("PRODUCTION_PREFLIGHT_V2", 900, 930),
        ("MIGRATE_0015", 900, 930),
        ("VERIFY_0015", 900, 930),
        ("LIVE_ONCE", 1_200, 1_230),
    ),
)
def test_controller_separates_effect_and_read_only_terminalization_deadlines(
    stage: str,
    effect_seconds: int,
    terminal_grace_seconds: int,
) -> None:
    now_epoch = 1_000.25
    authority = datetime.fromtimestamp(10_000, tz=UTC)
    effect, terminalization = controller._stage_operation_deadlines_epoch(
        authority,
        stage=stage,
        now_epoch=now_epoch,
    )
    assert effect == int(now_epoch + effect_seconds)
    assert terminalization == effect + terminal_grace_seconds + 210
    assert terminalization <= int(authority.timestamp())


def test_controller_refuses_insufficient_terminal_authority_before_effects() -> None:
    now_epoch = 1_000.25
    authority = datetime.fromtimestamp(2_000, tz=UTC)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_EFFECT_DEADLINE_EXCEEDED",
    ):
        controller._stage_operation_deadlines_epoch(
            authority,
            stage="LIVE_ONCE",
            now_epoch=now_epoch,
        )


def test_controller_terminal_run_observations_end_after_workflow_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic = [0.0]
    observed_at: list[float] = []
    documents = iter(
        (
            ("in_progress", None),
            ("in_progress", None),
            ("completed", "success"),
        )
    )
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)

    def load_run(_path: str, _token: str) -> dict[str, object]:
        observed_at.append(monotonic[0])
        status, conclusion = next(documents)
        return {
            "id": 101,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "path": ".github/workflows/chronos-neon-branch-identity-v2.yml",
            "repository": {"full_name": "dddur75/robin-stades-ng"},
            "status": status,
            "conclusion": conclusion,
            "updated_at": "2026-08-31T04:30:00Z",
        }

    terminal, count = controller._wait_for_terminal_run(
        stage="RECOVERY_IDENTITY_V2",
        main_sha="a" * 40,
        run_id=101,
        token="synthetic-token",
        run_loader=load_run,
        sleeper=lambda seconds: monotonic.__setitem__(0, monotonic[0] + seconds),
        clock=lambda: monotonic[0],
        terminalization_deadline_epoch=2_440.0,
    )
    assert terminal["status"] == "completed"
    assert count == 3
    assert observed_at == [0.0, 615.0, 1_230.0]


def test_controller_orders_guard_hold_enable_dispatch_disable_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    events: list[str] = []
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: events.append("AUTHORITY") or _test_authority_expiry(),
    )
    monkeypatch.setattr(
        controller,
        "_validate_predecessor",
        lambda **_kwargs: (
            events.append("PREDECESSOR")
            or {
                "predecessor_kind": "POST_MERGE_SAFE_V2",
                "predecessor_attestation": None,
                "predecessor_semantic_verdict": "POST_MERGE_SAFE_V2_GREEN",
                "predecessor_controller_receipt_sha256": None,
            }
        ),
    )
    monkeypatch.setattr(
        controller,
        "_validate_dispatch_ordinal",
        lambda **_kwargs: (
            events.append("ORDINAL")
            or {
                "authority_window_not_before": chronos_production.DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
                "expected_prior_dispatches": 0,
                "observed_prior_dispatches": 0,
                "observed_prior_run_ids": [],
            }
        ),
    )
    monkeypatch.setattr(
        controller,
        "_github_get",
        lambda *_args, **_kwargs: (
            events.append("MAIN")
            or {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": "a" * 40},
            }
        ),
    )

    dispatch_payloads: list[object] = []
    terminal_deadlines: list[int] = []

    def mutate(**kwargs: object) -> dict[str, object] | None:
        operation = str(kwargs["path"]).rsplit("/", 1)[-1].upper()
        events.append(operation)
        if operation == "DISPATCHES":
            dispatch_payloads.append(kwargs["payload"])
            return {
                "workflow_run_id": 101,
                "run_url": "https://api.github.com/repos/dddur75/robin-stades-ng/actions/runs/101",
                "html_url": "https://github.com/dddur75/robin-stades-ng/actions/runs/101",
            }
        return None

    def terminalize(**kwargs: object) -> dict[str, object]:
        terminal_deadlines.append(int(cast(int, kwargs["terminalization_deadline_epoch"])))
        return _synthetic_terminal_success(**kwargs)

    receipt = controller.run_cycle(
        stage="RECOVERY_IDENTITY_V2",
        main_sha="a" * 40,
        inputs={"expected_main_sha": "a" * 40},
        receipt_path=_controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2"),
        hold_validator=lambda: events.append("HOLD") or _controller_hold(),
        mutator=mutate,
        terminalizer=terminalize,
    )
    assert events == [
        "AUTHORITY",
        "PREDECESSOR",
        "HOLD",
        "ORDINAL",
        "HOLD",
        "MAIN",
        "ENABLE",
        "DISPATCHES",
        "DISABLE",
    ]
    assert len(dispatch_payloads) == 1
    dispatch_payload = cast(dict[str, object], dispatch_payloads[0])
    assert dispatch_payload["ref"] == "main"
    assert dispatch_payload["return_run_details"] is True
    dispatch_inputs = cast(dict[str, str], dispatch_payload["inputs"])
    assert dispatch_inputs["expected_main_sha"] == "a" * 40
    assert int(dispatch_inputs["recovery_v2_effect_deadline_epoch"]) > 0
    assert re.fullmatch(r"[0-9a-f]{64}", dispatch_inputs["recovery_v2_dispatch_nonce"])
    assert terminal_deadlines == [
        int(dispatch_inputs["recovery_v2_effect_deadline_epoch"]) + 630 + 210
    ]
    assert receipt["mutations_attempted"] == ["ENABLE", "DISPATCH", "DISABLE"]
    assert receipt["mutations_confirmed"] == ["ENABLE", "DISPATCH", "DISABLE"]
    assert receipt["workflow_run_id"] == 101
    terminal_run = cast(dict[str, object], receipt["terminal_evidence"])["terminal_run"]
    assert isinstance(terminal_run, dict)
    completed_at = datetime.fromisoformat(
        cast(str, receipt["terminalization_completed_at"]).replace("Z", "+00:00")
    )
    terminal_updated_at = datetime.fromisoformat(
        cast(str, terminal_run["updated_at"]).replace("Z", "+00:00")
    )
    assert terminal_updated_at <= completed_at <= datetime.fromtimestamp(
        terminal_deadlines[0], tz=UTC
    )


def test_controller_rejects_completion_sample_after_terminalization_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    completion_epoch = [0.0]

    def mutate(**kwargs: object) -> dict[str, object] | None:
        if str(kwargs["path"]).endswith("/dispatches"):
            return {"workflow_run_id": 101}
        return None

    def terminalize(**kwargs: object) -> dict[str, object]:
        completion_epoch[0] = (
            float(cast(int, kwargs["terminalization_deadline_epoch"])) + 0.000001
        )
        return _synthetic_terminal_success(**kwargs)

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_TERMINALIZATION_DEADLINE_EXCEEDED",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
            terminalizer=terminalize,
            wall_clock=lambda: completion_epoch[0],
        )
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert (
        failure["terminal_failure_code"]
        == "RECOVERY_V2_CONTROLLER_TERMINALIZATION_DEADLINE_EXCEEDED"
    )
    assert "terminalization_completed_at" not in failure


@pytest.mark.parametrize(
    "mutation",
    ["ABSENT", "MALFORMED", "BEFORE_TERMINAL", "AFTER_DEADLINE"],
)
def test_predecessor_controller_receipt_rejects_invalid_completion_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    validate_receipt = controller._validate_predecessor_controller_receipt
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )

    def mutate_remote(**kwargs: object) -> dict[str, object] | None:
        if str(kwargs["path"]).endswith("/dispatches"):
            return {"workflow_run_id": 101}
        return None

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    receipt = controller.run_cycle(
        stage="RECOVERY_IDENTITY_V2",
        main_sha="a" * 40,
        inputs={"expected_main_sha": "a" * 40},
        receipt_path=receipt_path,
        hold_validator=_controller_hold,
        mutator=mutate_remote,
        terminalizer=_synthetic_terminal_success,
        wall_clock=lambda: datetime.now(tz=UTC).timestamp(),
    )
    monkeypatch.setattr(controller, "_validate_pre_effect_proof", lambda **_kwargs: None)
    terminal_evidence = cast(dict[str, object], receipt["terminal_evidence"])
    attestation = cast(dict[str, object], terminal_evidence["attestation"])
    assert validate_receipt(
        stage="RECOVERY_IDENTITY_V2",
        main_sha="a" * 40,
        run_id="101",
        attestation=attestation,
    ) == hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    mutant = deepcopy(receipt)
    if mutation == "ABSENT":
        mutant.pop("terminalization_completed_at")
    elif mutation == "MALFORMED":
        mutant["terminalization_completed_at"] = "not-an-instant"
    elif mutation == "BEFORE_TERMINAL":
        mutant["terminalization_completed_at"] = "2026-08-30T12:49:59Z"
    else:
        reservation = cast(
            dict[str, object], mutant["terminalization_effect_reservation"]
        )
        deadline = cast(int, reservation["controller_terminalization_deadline_epoch"])
        mutant["terminalization_completed_at"] = (
            datetime.fromtimestamp(deadline + 0.000001, tz=UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    receipt_path.write_text(
        json.dumps(mutant, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_PREDECESSOR_INVALID",
    ):
        validate_receipt(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            run_id="101",
            attestation=attestation,
        )


def test_controller_malformed_terminal_success_is_durably_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    terminal_calls: list[int] = []

    def mutate(**kwargs: object) -> dict[str, object] | None:
        if str(kwargs["path"]).endswith("/dispatches"):
            return {"workflow_run_id": 101}
        return None

    def malformed_terminalizer(**kwargs: object) -> dict[str, object]:
        terminal_calls.append(int(cast(int, kwargs["run_id"])))
        return {"outcome": "SUCCESS"}

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
            terminalizer=malformed_terminalizer,
        )
    failure = json.loads(receipt_path.read_bytes())
    assert terminal_calls == [101]
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["workflow_run_id"] == 101
    assert (
        failure["terminal_failure_code"]
        == "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
    )
    assert failure["terminal_evidence"]["workflow_run_id"] == 101
    effect_deadline = int(
        failure["pre_effect_proof"]["stage_inputs"][
            "recovery_v2_effect_deadline_epoch"
        ]
    )
    assert failure["terminalization_effect_reservation"] == {
        "reservation_status": (
            "CONSERVATIVE_UPPER_BOUNDS_RESERVED_BEFORE_FIRST_TERMINAL_GET"
        ),
        "workflow_run_id": 101,
        "workflow_effect_deadline_epoch": effect_deadline,
        "post_effect_workflow_terminal_grace_seconds": 630,
        "controller_terminalization_deadline_epoch": effect_deadline + 840,
        "terminal_artifact_attestation_reserve_seconds": 210,
        "workflow_run_observations_conservatively_consumed": 3,
        "artifact_attestation_gets_conservatively_consumed": 3,
        "artifact_downloads_conservatively_consumed": 1,
        "automatic_retries": 0,
        "second_terminalization_invocation_allowed": False,
    }
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=lambda: pytest.fail("second hold reached"),
            mutator=lambda **_kwargs: pytest.fail("second mutation reached"),
            terminalizer=lambda **_kwargs: pytest.fail("second terminalizer reached"),
        )


def test_controller_terminalizer_exception_is_durably_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )

    def mutate(**kwargs: object) -> dict[str, object] | None:
        if str(kwargs["path"]).endswith("/dispatches"):
            return {"workflow_run_id": 102}
        return None

    def broken_terminalizer(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("synthetic terminalizer crash")

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
            terminalizer=broken_terminalizer,
        )
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["workflow_run_id"] == 102
    assert (
        failure["terminal_failure_code"]
        == "RECOVERY_V2_CONTROLLER_TERMINALIZATION_INVALID"
    )
    assert failure["terminal_evidence"]["outcome"] == "AMBIGUOUS"
    assert failure["terminal_evidence"]["workflow_run_id"] == 102
    assert failure["terminal_evidence"]["terminalization_effect_reservation"] == (
        failure["terminalization_effect_reservation"]
    )
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=lambda: pytest.fail("second hold reached"),
            mutator=lambda **_kwargs: pytest.fail("second mutation reached"),
            terminalizer=lambda **_kwargs: pytest.fail("second terminalizer reached"),
        )


def test_controller_dispatch_failure_still_uses_single_disable_and_consumes_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    mutations: list[str] = []

    def mutate(**kwargs: object) -> None:
        operation = str(kwargs["path"]).rsplit("/", 1)[-1].upper()
        mutations.append(operation)
        if operation == "DISPATCHES":
            raise controller.RecoveryV2ControllerError("ambiguous dispatch")

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(controller.RecoveryV2ControllerError, match="ambiguous dispatch"):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
        )
    assert mutations == ["ENABLE", "DISPATCHES", "DISABLE"]
    assert json.loads(receipt_path.read_bytes())["verdict"] == "FAIL_AND_STOP"
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=lambda: pytest.fail("second hold reached"),
            mutator=lambda **_kwargs: pytest.fail("second mutation reached"),
        )


def test_controller_failure_after_known_dispatch_persists_workflow_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )

    def mutate(**kwargs: object) -> dict[str, object] | None:
        operation = str(kwargs["path"]).rsplit("/", 1)[-1].upper()
        if operation == "DISPATCHES":
            return {"workflow_run_id": 101}
        if operation == "DISABLE":
            raise controller.RecoveryV2ControllerError("ambiguous disable")
        return None

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(controller.RecoveryV2ControllerError, match="ambiguous disable"):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
        )
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["workflow_run_id"] == 101
    assert failure["mutations_confirmed"] == ["ENABLE", "DISPATCH"]


def test_controller_receipt_failure_after_known_dispatch_keeps_workflow_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    real_write = controller._write_receipt
    failed_once = False

    def fail_first_known_run_write(
        path: Path,
        document: Mapping[str, object],
        *,
        exclusive: bool = False,
    ) -> None:
        nonlocal failed_once
        if document.get("workflow_run_id") == 101 and not failed_once:
            failed_once = True
            raise controller.RecoveryV2ControllerError("synthetic receipt failure")
        real_write(path, document, exclusive=exclusive)

    monkeypatch.setattr(controller, "_write_receipt", fail_first_known_run_write)

    def mutate(**kwargs: object) -> dict[str, object] | None:
        if str(kwargs["path"]).endswith("/dispatches"):
            return {"workflow_run_id": 101}
        return None

    receipt_path = _controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2")
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="synthetic receipt failure",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=receipt_path,
            hold_validator=_controller_hold,
            mutator=mutate,
        )
    assert failed_once is True
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["workflow_run_id"] == 101


@pytest.mark.parametrize(
    "mutator",
    [
        lambda hold: hold["recovery_v2_scope_guard"].__setitem__("job_id", 101),
        lambda hold: hold["post_merge_ci"].__setitem__("run_id", 101),
        lambda hold: hold["recovery_v2_production_workflow_quarantine"][0].__setitem__(
            "workflow_id", 901
        ),
        lambda hold: hold.__setitem__("active_after", 1),
    ],
)
def test_controller_requires_two_identical_full_holds_before_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator: object,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    first = _controller_hold()
    second = deepcopy(first)
    assert callable(mutator)
    mutator(second)
    holds = iter((first, second))
    mutations: list[str] = []
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_HOLD_INVALID",
    ):
        controller.run_cycle(
            stage="RECOVERY_IDENTITY_V2",
            main_sha="a" * 40,
            inputs={"expected_main_sha": "a" * 40},
            receipt_path=_controller_receipt(tmp_path, "RECOVERY_IDENTITY_V2"),
            hold_validator=lambda: next(holds),
            mutator=lambda **kwargs: mutations.append(str(kwargs["path"])),
        )
    assert mutations == []


def test_postmerge_quarantine_disables_only_initially_active_workflows_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    pre_hold = _controller_hold()
    initial = pre_hold["recovery_v2_production_workflow_quarantine"]
    assert isinstance(initial, list)
    active_paths = sorted(controller._QUARANTINE_WORKFLOWS)[::2]
    for entry in initial:
        assert isinstance(entry, dict)
        if entry["workflow_path"] in active_paths:
            entry["state"] = "active"
    mutations: list[str] = []

    def mutate(**kwargs: object) -> None:
        mutations.append(str(kwargs["path"]))

    receipt_path = _quarantine_receipt(tmp_path)
    receipt = controller.run_postmerge_quarantine(
        main_sha="a" * 40,
        receipt_path=receipt_path,
        pre_hold_validator=lambda: pre_hold,
        post_hold_validator=_controller_hold,
        mutator=mutate,
    )
    assert receipt["verdict"] == "POSTMERGE_QUARANTINE_CONFIRMED"
    assert receipt["disable_attempted_paths"] == active_paths
    assert receipt["disable_confirmed_paths"] == active_paths
    assert receipt["disable_outcomes"] == [
        {"workflow_path": path, "outcome": "CONFIRMED"} for path in active_paths
    ]
    assert receipt["unconfirmed_paths"] == []
    assert mutations == [
        f"/repos/dddur75/robin-stades-ng/actions/workflows/{path.rsplit('/', 1)[-1]}/disable"
        for path in active_paths
    ]
    assert receipt["already_disabled_paths"] == sorted(
        set(controller._QUARANTINE_WORKFLOWS) - set(active_paths)
    )
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: pytest.fail("second GET reached"),
            post_hold_validator=lambda: pytest.fail("second GET reached"),
            mutator=lambda **_kwargs: pytest.fail("second mutation reached"),
        )


def test_postmerge_quarantine_uses_one_exact_300_second_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    monkeypatch.setattr(controller.time, "time", lambda: 1_000.0)
    pre_hold = _controller_hold()
    inventory = pre_hold["recovery_v2_production_workflow_quarantine"]
    assert isinstance(inventory, list)
    first_new_path = controller._QUARANTINE_WORKFLOWS[0]
    next(
        cast(dict[str, object], item)
        for item in inventory
        if cast(dict[str, object], item)["workflow_path"] == first_new_path
    )["state"] = "active"
    holds = iter((pre_hold, _controller_hold()))
    deadlines: list[float] = []

    def verify(**kwargs: object) -> Mapping[str, object]:
        deadlines.append(float(kwargs["effect_deadline_epoch"]))
        return next(holds)

    def github_get(*_args: object, **kwargs: object) -> dict[str, object]:
        deadlines.append(float(kwargs["effect_deadline_epoch"]))
        return {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": "a" * 40},
        }

    def mutate(**kwargs: object) -> None:
        deadlines.append(float(kwargs["effect_deadline_epoch"]))

    monkeypatch.setattr(controller, "verify_hold", verify)
    monkeypatch.setattr(controller, "_github_get", github_get)
    controller.run_postmerge_quarantine(
        main_sha="a" * 40,
        receipt_path=_quarantine_receipt(tmp_path),
        mutator=mutate,
    )
    assert deadlines == [1_300.0, 1_300.0, 1_300.0, 1_300.0]


def test_postmerge_quarantine_requires_council_release_before_receipt_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_council_release",
        lambda **_kwargs: (_ for _ in ()).throw(ChronosProductionError("missing release")),
    )
    external_calls: list[str] = []
    receipt_path = _quarantine_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_QUARANTINE_AUTHORITY_INVALID",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: external_calls.append("HOLD") or {},
            post_hold_validator=lambda: external_calls.append("HOLD") or {},
            mutator=lambda **_kwargs: external_calls.append("MUTATION"),
        )
    assert not receipt_path.exists()
    assert external_calls == []


def test_postmerge_quarantine_requires_token_before_one_shot_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    receipt_path = _quarantine_receipt(tmp_path)
    external_calls: list[str] = []
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_QUARANTINE_TOKEN_MISSING",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: external_calls.append("HOLD") or {},
            post_hold_validator=lambda: external_calls.append("HOLD") or {},
            mutator=lambda **_kwargs: external_calls.append("MUTATION"),
        )
    assert external_calls == []
    assert not receipt_path.exists()


def test_postmerge_quarantine_ambiguous_disable_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    pre_hold = _controller_hold()
    inventory = pre_hold["recovery_v2_production_workflow_quarantine"]
    assert isinstance(inventory, list)
    active = list(controller._QUARANTINE_WORKFLOWS[:3])
    for entry in inventory:
        assert isinstance(entry, dict)
        if entry["workflow_path"] in active:
            entry["state"] = "active"
    mutations: list[str] = []

    def ambiguous(**kwargs: object) -> None:
        mutations.append(str(kwargs["path"]))
        raise OSError("untrusted transport detail")

    receipt_path = _quarantine_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: pre_hold,
            post_hold_validator=_controller_hold,
            mutator=ambiguous,
        )
    assert len(mutations) == len(active)
    assert len(mutations) == len(set(mutations))
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["disable_attempted_paths"] == active
    assert failure["disable_confirmed_paths"] == []
    assert failure["disable_outcomes"] == [
        {"workflow_path": path, "outcome": "AMBIGUOUS"} for path in active
    ]
    assert failure["unconfirmed_paths"] == active
    assert "untrusted" not in receipt_path.read_text(encoding="utf-8")
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_CONTROLLER_INVOCATION_ALREADY_CONSUMED",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: pytest.fail("second hold reached"),
            post_hold_validator=lambda: pytest.fail("second hold reached"),
            mutator=lambda **_kwargs: pytest.fail("second mutation reached"),
        )


def test_postmerge_quarantine_refuses_mutation_if_pre_effect_progress_is_not_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    pre_hold = _controller_hold()
    inventory = pre_hold["recovery_v2_production_workflow_quarantine"]
    assert isinstance(inventory, list)
    first = controller._QUARANTINE_WORKFLOWS[0]
    for entry in inventory:
        assert isinstance(entry, dict)
        if entry["workflow_path"] == first:
            entry["state"] = "active"
    original_write = controller._write_receipt
    write_count = 0

    def fail_first_progress(
        path: Path,
        document: Mapping[str, object],
        *,
        exclusive: bool = False,
    ) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 3:
            raise controller.RecoveryV2ControllerError("RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS")
        original_write(path, document, exclusive=exclusive)

    monkeypatch.setattr(controller, "_write_receipt", fail_first_progress)
    mutations: list[str] = []
    receipt_path = _quarantine_receipt(tmp_path)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_QUARANTINE_MUTATION_AMBIGUOUS",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=receipt_path,
            pre_hold_validator=lambda: pre_hold,
            post_hold_validator=_controller_hold,
            mutator=lambda **kwargs: mutations.append(str(kwargs["path"])),
        )
    assert mutations == []
    failure = json.loads(receipt_path.read_bytes())
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["disable_attempted_paths"] == [first]
    assert failure["disable_confirmed_paths"] == []
    assert failure["disable_outcomes"] == []
    assert failure["unconfirmed_paths"] == [first]


def test_postmerge_quarantine_rejects_malformed_hold_before_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        _test_authority_expiry,
    )
    malformed = _controller_hold()
    malformed["queued_after"] = 1
    mutations: list[str] = []
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="RECOVERY_V2_QUARANTINE_PRECONDITION_INVALID",
    ):
        controller.run_postmerge_quarantine(
            main_sha="a" * 40,
            receipt_path=_quarantine_receipt(tmp_path),
            pre_hold_validator=lambda: malformed,
            post_hold_validator=_controller_hold,
            mutator=lambda **kwargs: mutations.append(str(kwargs["path"])),
        )
    assert mutations == []


def test_cleanup_child_cannot_be_blocked_by_lock_or_authority_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        controller,
        "assert_production_safety_locks",
        lambda _environment: (_ for _ in ()).throw(ChronosProductionError("lock closed")),
    )
    monkeypatch.setattr(
        controller,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: (_ for _ in ()).throw(ChronosProductionError("window closed")),
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        controller,
        "_mutation_direct",
        lambda **kwargs: calls.append((str(kwargs["method"]), str(kwargs["path"]))) or None,
    )

    class Connection:
        messages: list[tuple[str, object]] = []

        def send(self, value: tuple[str, object]) -> None:
            self.messages.append(value)

        def close(self) -> None:
            return None

    connection = Connection()
    stage = "RECOVERY_IDENTITY_V2"
    path = (
        "/repos/dddur75/robin-stades-ng/actions/workflows/"
        "chronos-neon-branch-identity-v2.yml/disable"
    )
    controller._mutation_worker(
        connection,
        token="synthetic-token",
        method="PUT",
        path=path,
        payload=None,
        stage=stage,
        main_sha="a" * 40,
        inputs_sha256="b" * 64,
        pre_effect_proof_sha256="c" * 64,
        receipt_path=_controller_receipt(tmp_path, stage),
        effect_deadline_epoch=float(_TEST_EFFECT_DEADLINE_EPOCH),
    )
    assert calls == [("PUT", path)]
    assert connection.messages == [("CONFIRMED", None)]
    assert controller._MUTATION_TOTAL_TIMEOUT_SECONDS == 15.0
    assert (
        controller._MUTATION_WORK_TIMEOUT_SECONDS + controller._MUTATION_TERMINATE_TIMEOUT_SECONDS
        < controller._MUTATION_TOTAL_TIMEOUT_SECONDS
    )


def test_shared_private_mutation_child_returns_one_exact_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {"processes": 0, "joins": 0, "closed": 0}

    class Connection:
        def close(self) -> None:
            observed["closed"] += 1

    class Receiver(Connection):
        def poll(self) -> bool:
            return True

        def recv(self) -> tuple[str, dict[str, int]]:
            return "CONFIRMED", {"workflow_run_id": 101}

    class Process:
        exitcode = 0

        def start(self) -> None:
            return None

        def join(self, _timeout: float) -> None:
            observed["joins"] += 1

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            observed["closed"] += 1

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Receiver, Connection]:
            assert duplex is False
            return Receiver(), Connection()

        def Process(self, **_kwargs: object) -> Process:
            observed["processes"] += 1
            return Process()

    monkeypatch.setattr(controller.multiprocessing, "get_context", lambda mode: Context())
    assert controller._run_private_mutation_child(
        target=lambda **_kwargs: None,
        kwargs={},
        error_code="SYNTHETIC_AMBIGUOUS",
    ) == {"workflow_run_id": 101}
    assert observed["processes"] == 1
    assert observed["joins"] == 1


def test_shared_private_mutation_child_timeout_terminates_then_kills_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {
        "processes": 0,
        "joins": [],
        "terminate": 0,
        "kill": 0,
    }

    class Connection:
        def poll(self) -> bool:
            return False

        def close(self) -> None:
            return None

    class Process:
        exitcode: int | None = None
        alive = True

        def start(self) -> None:
            return None

        def join(self, timeout: float) -> None:
            joins = observed["joins"]
            assert isinstance(joins, list)
            joins.append(timeout)

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            observed["terminate"] = int(observed["terminate"]) + 1

        def kill(self) -> None:
            observed["kill"] = int(observed["kill"]) + 1
            self.alive = False
            self.exitcode = -9

        def close(self) -> None:
            return None

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **_kwargs: object) -> Process:
            observed["processes"] = int(observed["processes"]) + 1
            return process

    monkeypatch.setattr(controller.multiprocessing, "get_context", lambda mode: Context())
    with pytest.raises(controller.RecoveryV2ControllerError, match="SYNTHETIC_AMBIGUOUS"):
        controller._run_private_mutation_child(
            target=lambda **_kwargs: None,
            kwargs={},
            error_code="SYNTHETIC_AMBIGUOUS",
        )
    joins = observed["joins"]
    assert isinstance(joins, list) and len(joins) == 3
    assert 0 < joins[0] <= controller._MUTATION_WORK_TIMEOUT_SECONDS
    assert 0 < joins[1] <= controller._MUTATION_TERMINATE_TIMEOUT_SECONDS
    assert 0 <= joins[2] <= controller._MUTATION_TOTAL_TIMEOUT_SECONDS
    assert observed["processes"] == 1
    assert observed["terminate"] == 1
    assert observed["kill"] == 1


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _scope_repository(tmp_path: Path) -> tuple[str, str]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Recovery Test")
    _git(tmp_path, "config", "user.email", "recovery@example.invalid")
    matrix = tmp_path / "configs" / "agents" / "mission-activation-matrix-v3.json"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        json.dumps(
            {
                "missions": {
                    "DATA_TORRENT_RECOVERY_V2": {
                        "writer": "C0",
                        "scale_ceiling": "E4",
                        "allowed_paths": [
                            "allowed.txt",
                            "configs/agents/mission-activation-matrix-v3.json",
                        ],
                    }
                }
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(tmp_path, "add", "--", "configs/agents/mission-activation-matrix-v3.json")
    _git(tmp_path, "commit", "-q", "-m", "base")
    start = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "allowed.txt").write_text("allowed\n", encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "--", "allowed.txt")
    _git(tmp_path, "commit", "-q", "-m", "allowed")
    return start, _git(tmp_path, "rev-parse", "HEAD")


def _scope_merge_repository(tmp_path: Path) -> tuple[str, str]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Recovery Test")
    _git(tmp_path, "config", "user.email", "recovery@example.invalid")
    matrix = tmp_path / "configs" / "agents" / "mission-activation-matrix-v3.json"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        json.dumps(
            {
                "missions": {
                    "DATA_TORRENT_RECOVERY_V2": {
                        "writer": "C0",
                        "scale_ceiling": "E4",
                        "allowed_paths": [
                            "allowed.txt",
                            "configs/agents/mission-activation-matrix-v3.json",
                        ],
                    }
                }
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(tmp_path, "add", "--", "configs/agents/mission-activation-matrix-v3.json")
    _git(tmp_path, "commit", "-q", "-m", "base")
    start = _git(tmp_path, "rev-parse", "HEAD")
    base_branch = _git(tmp_path, "branch", "--show-current")
    _git(tmp_path, "switch", "-q", "-c", "recovery-candidate")
    (tmp_path / "allowed.txt").write_text("allowed\n", encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "--", "allowed.txt")
    _git(tmp_path, "commit", "-q", "-m", "candidate")
    _git(tmp_path, "switch", "-q", base_branch)
    _git(
        tmp_path,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "[DATA_TORRENT_RECOVERY_V2] PR-A",
        "recovery-candidate",
    )
    return start, _git(tmp_path, "rev-parse", "HEAD")


def _patch_minimal_scope_guard(
    monkeypatch: pytest.MonkeyPatch,
    *,
    start: str,
) -> None:
    paths = ["allowed.txt", "configs/agents/mission-activation-matrix-v3.json"]
    monkeypatch.setattr(scope_guard, "START_SHA", start)
    monkeypatch.setattr(
        scope_guard,
        "EXPECTED_ALLOWED_PATHS_SHA256",
        scope_guard._paths_sha256(paths),
    )
    monkeypatch.setattr(
        scope_guard,
        "_phase_allowed_paths",
        lambda allowed, *, phase: sorted(allowed),
    )


def test_scope_guard_accepts_only_exact_start_to_head_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, head = _scope_repository(tmp_path)
    _patch_minimal_scope_guard(monkeypatch, start=start)
    output = tmp_path / ".ci" / "scope.json"
    receipt = scope_guard.verify_scope(
        repository_root=tmp_path,
        expected_head=head,
        expected_base=start,
        phase="PR_A",
        event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
        output=output,
    )
    assert receipt["verdict"] == "SCOPE_GUARD_PASS"
    assert receipt["outside_paths"] == []
    assert receipt["changed_path_count"] == 1
    assert b"\r" not in output.read_bytes()
    with pytest.raises(scope_guard.ScopeGuardError, match="HEAD_MISMATCH"):
        scope_guard.verify_scope(
            repository_root=tmp_path,
            expected_head="f" * 40,
            expected_base=start,
            phase="PR_A",
            event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
            output=output,
        )


def test_scope_guard_rejects_one_outside_path_without_merge_base_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, _head = _scope_repository(tmp_path)
    _patch_minimal_scope_guard(monkeypatch, start=start)
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "--", "outside.txt")
    _git(tmp_path, "commit", "-q", "-m", "outside")
    with pytest.raises(scope_guard.ScopeGuardError, match="OUTSIDE_ALLOWLIST"):
        scope_guard.verify_scope(
            repository_root=tmp_path,
            expected_head=_git(tmp_path, "rev-parse", "HEAD"),
            expected_base=start,
            phase="PR_A",
            event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
            output=tmp_path / ".ci" / "scope.json",
        )


def test_scope_guard_rejects_self_modified_allowlist_even_when_outside_path_is_added(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, _head = _scope_repository(tmp_path)
    _patch_minimal_scope_guard(monkeypatch, start=start)
    matrix_path = tmp_path / "configs" / "agents" / "mission-activation-matrix-v3.json"
    matrix = json.loads(matrix_path.read_bytes())
    matrix["missions"]["DATA_TORRENT_RECOVERY_V2"]["allowed_paths"].append("outside.txt")
    matrix["missions"]["DATA_TORRENT_RECOVERY_V2"]["allowed_paths"].sort()
    matrix_path.write_text(
        json.dumps(matrix, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8", newline="\n")
    _git(tmp_path, "add", "--", "configs/agents/mission-activation-matrix-v3.json", "outside.txt")
    _git(tmp_path, "commit", "-q", "-m", "self-modifying scope")
    with pytest.raises(scope_guard.ScopeGuardError, match="SCOPE_MATRIX_INVALID"):
        scope_guard.verify_scope(
            repository_root=tmp_path,
            expected_head=_git(tmp_path, "rev-parse", "HEAD"),
            expected_base=start,
            phase="PR_A",
            event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
            output=tmp_path / ".ci" / "scope.json",
        )


def test_scope_guard_postmerge_requires_exact_two_parent_normal_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, head = _scope_merge_repository(tmp_path)
    _patch_minimal_scope_guard(monkeypatch, start=start)
    receipt = scope_guard.verify_scope(
        repository_root=tmp_path,
        expected_head=head,
        expected_base=start,
        phase="PR_A",
        event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
        expected_first_parent=start,
        output=tmp_path / ".ci" / "scope.json",
    )
    assert receipt["merge_first_parent"] == start
    assert receipt["merge_parent_count"] == 2
    with pytest.raises(scope_guard.ScopeGuardError, match="MERGE_PARENT_INVALID"):
        scope_guard.verify_scope(
            repository_root=tmp_path,
            expected_head=head,
            expected_base=start,
            phase="PR_A",
            event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
            expected_first_parent="f" * 40,
            output=tmp_path / ".ci" / "scope.json",
        )


def test_scope_guard_postmerge_rejects_single_parent_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, head = _scope_repository(tmp_path)
    _patch_minimal_scope_guard(monkeypatch, start=start)
    with pytest.raises(scope_guard.ScopeGuardError, match="MERGE_PARENT_INVALID"):
        scope_guard.verify_scope(
            repository_root=tmp_path,
            expected_head=head,
            expected_base=start,
            phase="PR_A",
            event_label="[DATA_TORRENT_RECOVERY_V2] PR-A",
            expected_first_parent=start,
            output=tmp_path / ".ci" / "scope.json",
        )


def test_safe_v2_binds_scope_job_to_recovery_pr_and_postmerge_run() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci-safe-v2.yml"
    source = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)
    tests_job = workflow["jobs"]["tests"]
    scope_job = workflow["jobs"]["data-torrent-recovery-v2-scope-guard"]
    witness_job = workflow["jobs"]["data-torrent-recovery-v2-final-gate-witness"]
    assert "data-torrent-recovery-v2-scope-guard:" in source
    assert tests_job["if"] == "${{ !cancelled() }}"
    assert "data-torrent-recovery-v2-scope-guard" in tests_job["needs"]
    assert "fetch-depth: 0" in source
    recovery_step = next(
        step
        for step in tests_job["steps"]
        if step.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
    )
    assert " ".join(scope_job["if"].split()) == " ".join(recovery_step["if"].split())
    assert source.count("github.head_ref == 'codex/data-torrent-recovery-v2'") == 2
    subjects = [
        "[DATA_TORRENT_RECOVERY_V2] PR-A",
        "[DATA_TORRENT_RECOVERY_V2] PR-B",
        "[DATA_TORRENT_RECOVERY_V2] PR-C",
    ]
    assert source.count(f"github.event.head_commit.message == '{subjects[0]}'") == 2
    assert source.count(f"github.event.head_commit.message == '{subjects[1]}'") == 2
    assert source.count(f"github.event.head_commit.message == '{subjects[2]}'") == 3
    assert "startsWith(github.event.head_commit.message" not in source
    assert '--expected-first-parent "$EXPECTED_FIRST_PARENT"' in source
    assert "scripts/check_data_torrent_recovery_v2_scope.py" in source
    assert "DATA_TORRENT_RECOVERY_V2_SCOPE_RESULT" in source
    assert 'test "$DATA_TORRENT_RECOVERY_V2_TERMINAL_CANDIDATE_COMPLETE" = "true"' in source
    assert set(witness_job["needs"]) == set(workflow["jobs"]) - {
        "data-torrent-recovery-v2-final-gate-witness"
    }
    depended_on = {
        dependency
        for job in workflow["jobs"].values()
        for dependency in (
            [job.get("needs")] if isinstance(job.get("needs"), str) else job.get("needs", [])
        )
    }
    assert set(workflow["jobs"]) - depended_on == {
        "data-torrent-recovery-v2-final-gate-witness"
    }
    assert "always()" in witness_job["if"]
    assert "github.event.head_commit.message == '[DATA_TORRENT_RECOVERY_V2] PR-C'" in witness_job[
        "if"
    ]
    assert "terminal_candidate_complete" in scope_job["outputs"]
    assert "terminal_ready" not in source
    assert '"current_run_completion_claimed": False' in source
    assert '"global_quiescence_claimed": False' in source
    assert '"data_torrent_ready_claimed": False' in source
    assert '"terminal_candidate_complete": "true"' in source

    def is_recovery_run(
        *, event: str, ref: str = "", head_ref: str = "", message: str = ""
    ) -> bool:
        return (event == "pull_request" and head_ref == "codex/data-torrent-recovery-v2") or (
            event == "push" and ref == "refs/heads/main" and message in subjects
        )

    assert is_recovery_run(event="pull_request", head_ref="codex/data-torrent-recovery-v2")
    assert not is_recovery_run(event="pull_request", head_ref="codex/another-branch")
    for subject in subjects:
        assert is_recovery_run(event="push", ref="refs/heads/main", message=subject)
    for invalid in (
        "Merge pull request #123 from dddur75/codex/data-torrent-recovery-v2",
        "[DATA_TORRENT_RECOVERY_V2] ",
        "[DATA_TORRENT_RECOVERY_V2] PR-D",
        "[DATA_TORRENT_RECOVERY_V2] PR-A\nbody",
        "[DATA_TORRENT_RECOVERY_V2] PR-A suffix",
    ):
        assert not is_recovery_run(event="push", ref="refs/heads/main", message=invalid)
    assert not is_recovery_run(event="push", ref="refs/heads/not-main", message=subjects[0])
    assert not is_recovery_run(
        event="workflow_dispatch", ref="refs/heads/main", message=subjects[0]
    )
    contract = json.loads(EFFECT_CONTRACT.read_bytes())
    assert contract["postmerge_scope_trigger"]["merge_commit_subjects"] == subjects
    runbook = (ROOT / "docs" / "operations" / "DATA-TORRENT-RECOVERY-V2.md").read_text(
        encoding="utf-8"
    )
    for slot, subject in zip(("A", "B", "C"), subjects, strict=True):
        assert (
            f'gh pr merge "$PR_{slot}_NUMBER" --repo dddur75/robin-stades-ng '
            f'--merge --match-head-commit "$PR_{slot}_HEAD" '
            f'--subject "{subject}" --body ""'
        ) in runbook
    assert "gh pr view --json headRefName,headRefOid,baseRefName,mergeable,state" in runbook

    def prerequisites_accept(
        *,
        recovery: bool,
        scope: str,
        remaining: tuple[str, ...],
    ) -> bool:
        first_step = all(result == "success" for result in remaining) and scope in {
            "success",
            "skipped",
        }
        recovery_step = not recovery or scope == "success"
        return first_step and recovery_step

    assert prerequisites_accept(
        recovery=False,
        scope="skipped",
        remaining=("success",) * 8,
    )
    assert not prerequisites_accept(
        recovery=False,
        scope="skipped",
        remaining=("success",) * 7 + ("failure",),
    )
    assert not prerequisites_accept(
        recovery=True,
        scope="skipped",
        remaining=("success",) * 8,
    )


def test_recovery_v2_runbook_orders_every_effectful_entrypoint_and_cas_gate() -> None:
    source = (ROOT / "docs" / "operations" / "DATA-TORRENT-RECOVERY-V2.md").read_text(
        encoding="utf-8"
    )
    runbook = source[source.index("## Séquence opérateur exécutable") :]
    ordered = (
        'git push --porcelain origin "${PR_A_HEAD}:refs/heads/$Branch"',
        "gh pr create --repo $Repo --base main --head $Branch",
        "gh pr view $PR_A_NUMBER --repo $Repo --json headRefName,headRefOid,baseRefName,mergeable,state",
        "gh pr merge $PR_A_NUMBER --repo $Repo --merge --match-head-commit $PR_A_HEAD",
        "--neutralize-provider-branch",
        "--postmerge-quarantine",
        "--stage RECOVERY_IDENTITY_V2",
        "--stage DURABLE_IDENTITY_SEAL_V2",
        "--stage PRODUCTION_PREFLIGHT_V2",
        "scripts/install_chronos_runtime_bindings_v2.py",
        "--stage MIGRATE_0015",
        "--stage VERIFY_0015",
        "--stage LIVE_ONCE",
        "--reserve-only",
        "--observe-phase C1",
        "--observe-phase C2",
        "gh pr merge $PR_C_NUMBER --repo $Repo --merge --match-head-commit $PR_C_HEAD",
        "--observe-phase POSTMERGE",
        "scripts/verify_data_torrent_recovery_v2_postmerge_gate.py",
    )
    cursor = -1
    for marker in ordered:
        cursor = runbook.index(marker, cursor + 1)
    assert "un nouveau commit après SAFE V2" in source
    assert "hard stop avant l’écriture de\nmerge" in source
    assert "gh run rerun" in runbook
    assert "ne jamais\nutiliser `gh run rerun`" in runbook


def _postmerge_gate_fixture(
    *,
    witness_overrides: Mapping[str, object] | None = None,
) -> tuple[
    dict[str, object],
    Callable[[str, str], dict[str, object]],
    Callable[..., bytes | dict[str, object]],
    Callable[..., dict[str, object]],
]:
    runtime_sha = "b" * 40
    phase_one_sha = "c" * 40
    candidate_sha = "d" * 40
    candidate_tree_sha = "e" * 40
    merge_sha = "f" * 40
    pr_number = 81
    phase_one_run_id = 301
    candidate_run_id = 302
    postmerge_run_id = 303
    candidate_report: dict[str, object] = {
        "schema_version": "data-torrent-recovery-v2-terminal-report-v1",
        "report_role": "CANDIDATE_NOT_TERMINAL",
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
        "duration_seconds": 40_000,
        "mission_complete": False,
        "data_torrent_ready": False,
        "final_verdict": "PASS_AND_HOLD",
        "completion_states": {
            "engineering_complete": True,
            "runtime_ready": True,
            "data_torrent_ready": False,
        },
        "delivery": {
            "pr_c": pr_number,
            "final_main_sha": None,
            "final_main_sha_definition": "PENDING_PR_C_MERGE_AND_POSTMERGE_SAFE",
        },
        "postmerge_final_gate": {
            "state": "PENDING_EXTERNAL_POSTMERGE_ATTESTATION",
            "committed_in_pr_c": False,
            "conditional_contract_sha256": "4" * 64,
            "entrypoint": {
                "path": "scripts/verify_data_torrent_recovery_v2_postmerge_gate.py",
                "raw_sha256": "5" * 64,
                "witness_schema": "data-torrent-recovery-v2-final-gate-witness-v1",
                "result_schema": "data-torrent-recovery-v2-terminal-report-v2",
            },
        },
        "global_quiescence": False,
        "worktree_status": "PENDING_C2_COMMIT_AND_EPHEMERAL_CLEANUP",
        "all_run_ids": [91, 92],
        "all_artifact_ids": [201],
        "all_payload_sha256": ["6" * 64],
        "all_archive_sha256": ["7" * 64],
        "data_metrics": {"leagues_enabled": 5},
        "effect_counters": {"automatic_retries": 0},
    }
    local: dict[str, object] = {
        "terminal_record_hash": "1" * 64,
        "terminal_report_sha256": "2" * 64,
        "delivery_receipt_sha256": "3" * 64,
        "runtime_main_sha": runtime_sha,
        "phase_one_sha": phase_one_sha,
        "candidate_sha": candidate_sha,
        "candidate_tree_sha": candidate_tree_sha,
        "pr_number": pr_number,
        "c1_observer_result_raw_sha256": hashlib.sha256(b"c1-observer-result\n").hexdigest(),
        "c1_observer_run_id": phase_one_run_id,
        "runtime_close_observed_at": "2026-08-31T00:00:00Z",
        "delivery_observed_at": "2026-08-31T00:04:00Z",
        "candidate_report_generated_at": "2026-08-31T00:05:00Z",
        "candidate_topology": [{"sha": "a" * 40}, {"sha": phase_one_sha}, {"sha": candidate_sha}],
        "candidate_report": candidate_report,
    }
    repository = {"full_name": "dddur75/robin-stades-ng"}
    pull_request = {
        "number": pr_number,
        "title": "[DATA_TORRENT_RECOVERY_V2] PR-C",
        "state": "closed",
        "merged": True,
        "draft": False,
        "created_at": "2026-08-31T00:01:00Z",
        "merged_at": "2026-08-31T00:08:00Z",
        "merge_commit_sha": merge_sha,
        "head": {"ref": "codex/data-torrent-recovery-v2", "sha": candidate_sha, "repo": repository},
        "base": {"ref": "main", "repo": repository},
    }
    main_commit = {
        "sha": merge_sha,
        "commit": {
            "message": "[DATA_TORRENT_RECOVERY_V2] PR-C",
            "tree": {"sha": candidate_tree_sha},
        },
        "parents": [{"sha": runtime_sha}, {"sha": candidate_sha}],
    }

    def run(
        *,
        run_id: int,
        head_sha: str,
        conclusion: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, object]:
        return {
            "id": run_id,
            "run_attempt": 1,
            "event": "pull_request",
            "head_branch": "codex/data-torrent-recovery-v2",
            "head_sha": head_sha,
            "path": ".github/workflows/ci-safe-v2.yml",
            "status": "completed",
            "conclusion": conclusion,
            "created_at": created_at,
            "updated_at": updated_at,
            "pull_requests": [{"number": pr_number}],
        }

    phase_one_run = run(
        run_id=phase_one_run_id,
        head_sha=phase_one_sha,
        conclusion="failure",
        created_at="2026-08-31T00:02:00Z",
        updated_at="2026-08-31T00:03:00Z",
    )
    candidate_run = run(
        run_id=candidate_run_id,
        head_sha=candidate_sha,
        conclusion="success",
        created_at="2026-08-31T00:06:00Z",
        updated_at="2026-08-31T00:07:00Z",
    )
    runs = {"total_count": 2, "workflow_runs": [phase_one_run, candidate_run]}

    def jobs(run_id: int, head_sha: str, tests_conclusion: str) -> dict[str, object]:
        values = [
            {
                "id": run_id * 10 + 1,
                "name": "Recovery V2 — scope guard exact",
                "run_id": run_id,
                "run_attempt": 1,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": run_id * 10 + 2,
                "name": "tests",
                "run_id": run_id,
                "run_attempt": 1,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": tests_conclusion,
                "steps": [
                    {
                        "name": "Exiger le scope guard sur chaque run Recovery V2",
                        "status": "completed",
                        "conclusion": tests_conclusion,
                    }
                ],
            },
        ]
        return {"total_count": len(values), "jobs": values}

    api_documents = {
        f"/repos/dddur75/robin-stades-ng/pulls/{pr_number}": pull_request,
        "/repos/dddur75/robin-stades-ng/commits/main": main_commit,
        (
            "/repos/dddur75/robin-stades-ng/actions/workflows/ci-safe-v2.yml/runs"
            "?event=pull_request&branch=codex/data-torrent-recovery-v2&per_page=100"
        ): runs,
        f"/repos/dddur75/robin-stades-ng/actions/runs/{phase_one_run_id}/jobs?per_page=100": jobs(
            phase_one_run_id, phase_one_sha, "failure"
        ),
        f"/repos/dddur75/robin-stades-ng/actions/runs/{candidate_run_id}/jobs?per_page=100": jobs(
            candidate_run_id, candidate_sha, "success"
        ),
    }

    def api_loader(path: str, token: str) -> dict[str, object]:
        assert token == "test-token"
        return deepcopy(api_documents[path])

    prerequisite_results = {name: "success" for name in sorted(final_gate._PREREQUISITE_JOBS)}
    witness: dict[str, object] = {
        "artifact_uploads_planned": 1,
        "current_run_completion_claimed": False,
        "data_torrent_ready_claimed": False,
        "event": "push",
        "github_api_gets": 0,
        "global_quiescence_claimed": False,
        "head_branch": "main",
        "head_sha": merge_sha,
        "merge_subject": "[DATA_TORRENT_RECOVERY_V2] PR-C",
        "phase": "PR_C",
        "prerequisite_results": prerequisite_results,
        "ref": "refs/heads/main",
        "repository": "dddur75/robin-stades-ng",
        "run_attempt": 1,
        "run_id": postmerge_run_id,
        "schema_version": "data-torrent-recovery-v2-final-gate-witness-v1",
        "scope_guard_outputs": {"phase": "PR_C", "terminal_candidate_complete": "true"},
        "verdict": "PR_C_POSTMERGE_PREREQUISITES_COMPLETE",
        "workflow_path": ".github/workflows/ci-safe-v2.yml",
    }
    if witness_overrides:
        witness.update(witness_overrides)
    witness_payload = _canonical(witness) + b"\n"
    archive_stream = io.BytesIO()
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr("data-torrent-recovery-v2-final-gate-witness-v1.json", witness_payload)
    archive = archive_stream.getvalue()
    artifact_id = 401
    listing: dict[str, object] = {
        "total_count": 2,
        "artifacts": [
            {
                "id": 400,
                "name": f"recovery-v2-scope-{postmerge_run_id}-1",
            },
            {
                "id": artifact_id,
                "name": f"data-torrent-recovery-v2-final-gate-{postmerge_run_id}-1",
                "expired": False,
                "size_in_bytes": len(archive),
                "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
                "workflow_run": {"id": postmerge_run_id, "head_sha": merge_sha},
            }
        ],
    }

    def artifact_loader(path: str, *, binary: bool = False) -> bytes | dict[str, object]:
        if binary:
            assert path == f"repos/dddur75/robin-stades-ng/actions/artifacts/{artifact_id}/zip"
            return archive
        assert path == (
            f"repos/dddur75/robin-stades-ng/actions/runs/{postmerge_run_id}/artifacts?per_page=100"
        )
        return deepcopy(listing)

    production_workflows = [
        {"workflow_id": index, "workflow_path": path, "state": "disabled_manually"}
        for index, path in enumerate(sorted(RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS), 1)
    ]
    hold: dict[str, object] = {
        "post_merge_ci": {
            "workflow_path": ".github/workflows/ci-safe-v2.yml",
            "run_id": postmerge_run_id,
            "run_attempt": 1,
            "head_sha": merge_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-31T00:09:00Z",
            "updated_at": "2026-08-31T00:11:00Z",
        },
        "recovery_v2_scope_guard": {
            "job_id": 501,
            "status": "completed",
            "conclusion": "success",
        },
        "recovery_v2_final_witness": {
            "job_id": 502,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-08-31T00:10:00Z",
        },
        "current_run_excluded": 0,
        "legacy_secret_branch_sha": runtime_sha,
        "nonterminal_run_counts": {
            "requested": 0,
            "waiting": 0,
            "pending": 0,
            "queued": 0,
            "in_progress": 0,
        },
        "recovery_v2_production_workflow_quarantine": production_workflows,
    }

    def hold_loader(**kwargs: object) -> dict[str, object]:
        assert kwargs["expected_successful_ci_run_id"] == postmerge_run_id
        assert kwargs["expected_legacy_branch_sha"] == runtime_sha
        assert kwargs["require_recovery_v2_final_witness"] is True
        return deepcopy(hold)

    return local, api_loader, artifact_loader, hold_loader


def _install_postmerge_observer_fixture(
    monkeypatch: pytest.MonkeyPatch,
    local: Mapping[str, object],
) -> None:
    c1_payload = b"c1-observer-result\n"
    c2_payload = b"c2-observer-result\n"
    postmerge_payload = b"postmerge-observer-result\n"
    c1_hash = hashlib.sha256(c1_payload).hexdigest()
    c2_hash = hashlib.sha256(c2_payload).hexdigest()
    c1 = {
        "runtime_main_sha": local["runtime_main_sha"],
        "phase_one_sha": local["phase_one_sha"],
        "head_sha": local["phase_one_sha"],
        "observed_at": "2026-08-31T00:03:30Z",
        "predecessor_results": {},
        "run": {
            "run_id": 301,
            "run_attempt": 1,
            "head_sha": local["phase_one_sha"],
            "conclusion": "failure",
            "scope_guard_job_id": 3011,
            "tests_job_id": 3012,
            "scope_guard_conclusion": "success",
            "tests_conclusion": "failure",
            "gate_step_conclusion": "failure",
        },
    }
    c2 = {
        "runtime_main_sha": local["runtime_main_sha"],
        "phase_one_sha": local["phase_one_sha"],
        "candidate_sha": local["candidate_sha"],
        "head_sha": local["candidate_sha"],
        "observed_at": "2026-08-31T00:07:30Z",
        "predecessor_results": {"C1": c1_hash},
        "run": {
            "run_id": 302,
            "run_attempt": 1,
            "head_sha": local["candidate_sha"],
            "conclusion": "success",
            "scope_guard_job_id": 3021,
            "tests_job_id": 3022,
            "scope_guard_conclusion": "success",
            "tests_conclusion": "success",
            "gate_step_conclusion": "success",
        },
    }
    postmerge = {
        "runtime_main_sha": local["runtime_main_sha"],
        "phase_one_sha": local["phase_one_sha"],
        "candidate_sha": local["candidate_sha"],
        "head_sha": local["candidate_sha"],
        "merge_sha": "f" * 40,
        "pr_number": 81,
        "observed_at": "2026-08-31T00:11:30Z",
        "predecessor_results": {"C1": c1_hash, "C2": c2_hash},
        "run": {"run_id": 303, "run_attempt": 1},
    }
    values = {
        "C1": (c1_payload, c1),
        "C2": (c2_payload, c2),
        "POSTMERGE": (postmerge_payload, postmerge),
    }

    def load_observer_result(**kwargs: object) -> tuple[bytes, dict[str, object]]:
        not_after = kwargs.get("not_after")
        assert isinstance(not_after, datetime)
        payload, document = values[cast(str, kwargs["phase"])]
        return payload, deepcopy(document)

    monkeypatch.setattr(delivery_evidence, "_load_observer_result", load_observer_result)


def test_postmerge_gate_is_the_only_external_ready_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, api_loader, artifact_loader, hold_loader = _postmerge_gate_fixture()
    _install_postmerge_observer_fixture(monkeypatch, local)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(final_gate, "_local_candidate", lambda _root, *, observed_now: local)
    monkeypatch.setattr(
        final_gate,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC),
    )
    monkeypatch.setattr(
        final_gate,
        "_host_identity_sha256",
        lambda: chronos_production.DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    )
    state_base = tmp_path.parent / f"{tmp_path.name}-state"
    state_base.mkdir()
    monkeypatch.setattr(final_gate, "_state_base", lambda: state_base)
    result = final_gate.verify_postmerge_gate(
        repository_root=tmp_path,
        pr_number=81,
        postmerge_run_id=303,
        now=datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
        api_loader=api_loader,
        artifact_loader=artifact_loader,
        hold_loader=hold_loader,
        clock=lambda: datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
    )
    assert result["semantic_verdict"] == "DATA_TORRENT_READY"
    assert result["mission_complete"] is result["data_torrent_ready"] is True
    assert result["global_quiescence"] is True
    assert result["schema_version"] == "data-torrent-recovery-v2-terminal-report-v2"
    assert result["report_role"] == "FINAL_EXTERNAL_COMPOSITE_NON_DURABLE"
    gate = result["postmerge_final_gate"]
    assert gate["state"] == "SATISFIED"
    assert gate["effect_counters"] == {
        "github_api_gets_exact": 34,
        "artifact_downloads_exact": 1,
        "validated_artifact_redirects_exact": 1,
        "physical_https_gets_exact": 35,
        "automatic_retries": 0,
    }
    assert {301, 302, 303} <= set(result["all_run_ids"])
    assert 401 in result["all_artifact_ids"]


def test_postmerge_gate_rejects_a_circular_witness_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, api_loader, artifact_loader, hold_loader = _postmerge_gate_fixture(
        witness_overrides={"current_run_completion_claimed": True}
    )
    _install_postmerge_observer_fixture(monkeypatch, local)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(final_gate, "_local_candidate", lambda _root, *, observed_now: local)
    monkeypatch.setattr(
        final_gate,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC),
    )
    monkeypatch.setattr(
        final_gate,
        "_host_identity_sha256",
        lambda: chronos_production.DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    )
    state_base = tmp_path.parent / f"{tmp_path.name}-state"
    state_base.mkdir()
    monkeypatch.setattr(final_gate, "_state_base", lambda: state_base)
    with pytest.raises(final_gate.RecoveryV2PostmergeGateError, match="WITNESS_INVALID"):
        final_gate.verify_postmerge_gate(
            repository_root=tmp_path,
            pr_number=81,
            postmerge_run_id=303,
            now=datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
            api_loader=api_loader,
            artifact_loader=artifact_loader,
            hold_loader=hold_loader,
            clock=lambda: datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
        )


def test_postmerge_gate_rejects_expired_mission_budget_before_local_or_external_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_start = datetime(2026, 8, 30, 12, 46, 58, tzinfo=UTC)
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        final_gate,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC),
    )
    monkeypatch.setattr(
        final_gate,
        "_local_candidate",
        lambda *_args, **_kwargs: pytest.fail("local candidate reached after time budget"),
    )

    with pytest.raises(final_gate.RecoveryV2PostmergeGateError, match="TIME_BUDGET_EXCEEDED"):
        final_gate.verify_postmerge_gate(
            repository_root=tmp_path,
            pr_number=81,
            postmerge_run_id=303,
            now=mission_start
            + timedelta(seconds=chronos_production.DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS + 1),
            api_loader=lambda *_args: pytest.fail("GitHub read reached"),
            artifact_loader=lambda *_args, **_kwargs: pytest.fail("artifact read reached"),
            hold_loader=lambda **_kwargs: pytest.fail("hold reached"),
            clock=lambda: mission_start
            + timedelta(seconds=chronos_production.DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS + 1),
        )


def test_postmerge_gate_rejects_wrong_host_before_reservation_or_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, _api_loader, _artifact_loader, _hold_loader = _postmerge_gate_fixture()
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(final_gate, "_local_candidate", lambda _root, *, observed_now: local)
    monkeypatch.setattr(
        final_gate,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC),
    )
    monkeypatch.setattr(final_gate, "_host_identity_sha256", lambda: "0" * 64)
    monkeypatch.setattr(final_gate, "_state_base", lambda: pytest.fail("reservation reached"))

    with pytest.raises(final_gate.RecoveryV2PostmergeGateError, match="HOST_IDENTITY_MISMATCH"):
        final_gate.verify_postmerge_gate(
            repository_root=tmp_path,
            pr_number=81,
            postmerge_run_id=303,
            now=datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
            api_loader=lambda *_args: pytest.fail("GitHub read reached"),
            artifact_loader=lambda *_args, **_kwargs: pytest.fail("artifact read reached"),
            hold_loader=lambda **_kwargs: pytest.fail("hold reached"),
            clock=lambda: datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
        )


def test_postmerge_gate_stops_before_the_next_get_when_deadline_margin_is_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, api_loader, artifact_loader, hold_loader = _postmerge_gate_fixture()
    _install_postmerge_observer_fixture(monkeypatch, local)
    observed = datetime(2026, 8, 31, 0, 12, tzinfo=UTC)
    current = [observed]
    api_calls: list[str] = []

    def advancing_loader(path: str, token: str) -> dict[str, object]:
        api_calls.append(path)
        document = api_loader(path, token)
        current[0] = observed + timedelta(seconds=1_194)
        return document

    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(final_gate, "_local_candidate", lambda _root, *, observed_now: local)
    monkeypatch.setattr(
        final_gate,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC),
    )
    monkeypatch.setattr(
        final_gate,
        "_host_identity_sha256",
        lambda: chronos_production.DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256,
    )
    state_base = tmp_path.parent / f"{tmp_path.name}-deadline-state"
    state_base.mkdir()
    monkeypatch.setattr(final_gate, "_state_base", lambda: state_base)

    with pytest.raises(final_gate.RecoveryV2PostmergeGateError, match="EFFECT_DEADLINE_EXCEEDED"):
        final_gate.verify_postmerge_gate(
            repository_root=tmp_path,
            pr_number=81,
            postmerge_run_id=303,
            now=observed,
            clock=lambda: current[0],
            api_loader=advancing_loader,
            artifact_loader=artifact_loader,
            hold_loader=hold_loader,
        )
    assert len(api_calls) == 1


def test_postmerge_gate_reservation_is_no_replace_in_fixed_namespace(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    state_base = tmp_path / "state"
    root.mkdir()
    state_base.mkdir()
    local = {
        "candidate_sha": "d" * 40,
        "candidate_tree_sha": "e" * 40,
        "candidate_report": {
            "postmerge_final_gate": {"conditional_contract_sha256": "4" * 64}
        },
    }
    kwargs = {
        "state_base": state_base,
        "local": local,
        "pr_number": 81,
        "postmerge_run_id": 303,
        "observed_at": datetime(2026, 8, 31, 0, 12, tzinfo=UTC),
        "host_identity_sha256": (
            chronos_production.DATA_TORRENT_RECOVERY_V2_ONE_WRITER_HOST_SHA256
        ),
        "observer_chain_result_raw_sha256": "d" * 64,
    }
    final_gate._reserve_final_gate(root, **kwargs)
    with pytest.raises(final_gate.RecoveryV2PostmergeGateError, match="ALREADY_RESERVED"):
        final_gate._reserve_final_gate(root, **kwargs)


def test_postmerge_gate_state_and_host_identity_ignore_ambient_home_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_state = final_gate._state_base()
    expected_identity = final_gate._host_identity_sha256()
    for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "XDG_STATE_HOME"):
        monkeypatch.setenv(name, "C:\\untrusted" if final_gate.os.name == "nt" else "/untrusted")
    assert final_gate._state_base() == expected_state
    assert final_gate._host_identity_sha256() == expected_identity


def test_postmerge_gate_git_strips_tokens_replace_refs_and_fsmonitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_EXEC_PATH",
        "GIT_SSH_COMMAND",
    ):
        monkeypatch.setenv(name, "untrusted")
    captured: dict[str, object] = {}

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(final_gate.subprocess, "run", run)
    assert final_gate._git(tmp_path, "status", "--porcelain=v2") == b""
    environment = cast(dict[str, str], captured["kwargs"]["env"])  # type: ignore[index]
    assert not {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_EXEC_PATH",
        "GIT_SSH_COMMAND",
    } & set(environment)
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    command = cast(tuple[str, ...] | list[str], captured["args"])[0]  # type: ignore[index]
    assert "--no-replace-objects" in command
    assert "core.fsmonitor=false" in command
    assert "core.untrackedCache=false" in command


def test_scope_guard_git_strips_tokens_replace_refs_and_fsmonitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_EXEC_PATH",
        "GIT_REPLACE_REF_BASE",
    ):
        monkeypatch.setenv(name, "untrusted")
    captured: dict[str, object] = {}

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(scope_guard.subprocess, "run", run)
    assert scope_guard._git(tmp_path, "status", "--porcelain=v2") == b""
    environment = cast(dict[str, str], captured["kwargs"]["env"])  # type: ignore[index]
    assert not {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
        "GIT_EXEC_PATH",
        "GIT_REPLACE_REF_BASE",
    } & set(environment)
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    command = cast(tuple[object, ...], captured["args"])[0]
    assert isinstance(command, list)
    assert "--no-replace-objects" in command
    assert "core.fsmonitor=false" in command
    assert "core.untrackedCache=false" in command


def test_v2_production_workflows_use_only_the_bounded_exact_main_transport() -> None:
    paths = (
        ".github/workflows/chronos-neon-branch-identity-v2.yml",
        ".github/workflows/chronos-identity-seal-v2.yml",
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        ".github/workflows/data-torrent-live-v2.yml",
    )
    sources = [(ROOT / path).read_text(encoding="utf-8") for path in paths]
    assert all("gh api" not in source for source in sources)
    assert sum(source.count("--exact-main-sha") for source in sources) == 10
    assert sources[0].count("--exact-main-sha") == 2
    assert sources[1].count("--exact-main-sha") == 2
    assert sources[2].count("--exact-main-sha") == 4
    assert sources[3].count("--exact-main-sha") == 2
    validation_jobs = ("identity", "seal", "validate", "validate")
    for path, job_name in zip(paths, validation_jobs, strict=True):
        workflow = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        first_step = workflow["jobs"][job_name]["steps"][0]
        assert "GH_TOKEN" not in first_step.get("env", {})


def test_council_authorization_binds_v1_terminal_report_and_current_hashes() -> None:
    records = [
        json.loads(line)
        for line in (ROOT / "reports" / "council" / "decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    record = next(item for item in records if item["decision_id"] == "RCV3-20260830-193")
    assert record["decision_id"] == "RCV3-20260830-193"
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["previous_hash"] == (
        "d3d1fc64ff5d8cfc47f23198fa08bcb50d880bdb5a61a7821bcdc2a746e1eeb8"
    )
    assert record["context"]["manifest"]["raw_sha256"] == (DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256)
    assert record["context"]["effect_contract"]["raw_sha256"] == (
        "7043cb6e502e825e8b2344dd1f2b9981daab0abfd5190eea603681affddc60bd"
    )
    assert record["context"]["effect_contract"]["canonical_sha256"] == (
        "3145af32a9eff4b327f876e7a7e37bf0c0e26facdc295ee0d5d57f97c65ce59b"
    )
    assert record["context"]["terminal_v1_report"] == {
        "workflow_run_id": 33308432195,
        "artifact_id": 9731217979,
        "artifact_archive_sha256": (
            "82d4d9803c3f3e06451b18f98846c1182b3aff86b53f5e3a62ee493ef2873f61"
        ),
        "report_sha256": ("60070f1534fd0e0472b776213e124941df60b8a185b7a65d7cc891c4293ec589"),
        "observed_at": "2026-08-30T11:15:12Z",
        "semantic_verdict": "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED",
        "reason": "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        "failed_gate": "branch_inventory_truncated",
        "neon_gets": 9,
        "production_effects": 0,
        "rerun_forbidden": True,
    }


def _write_mutated_effect_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
) -> None:
    execution = tmp_path / "configs" / "execution"
    execution.mkdir(parents=True, exist_ok=True)
    (execution / MANIFEST.name).write_bytes(MANIFEST.read_bytes())
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (execution / EFFECT_CONTRACT.name).write_bytes(payload)
    monkeypatch.setattr(
        chronos_production,
        "DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(
        chronos_production,
        "DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256",
        hashlib.sha256(_canonical(document)).hexdigest(),
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("stage_entrypoints",), None),
        (("stage_entrypoints", "REPLAY_100", "separate_dispatches"), False),
        (("safe_v2_ci_budget", "consolidated_exact_head_cycles_per_engineering_pr_maximum"), 4),
        (("safe_v2_ci_budget", "phase_budgets_fungible"), 0),
        (("pr_budget", "one_open_at_a_time"), 1),
        (("pr_budget", "engineering_required"), True),
        (("postmerge_scope_trigger", "merge_method"), "squash"),
        (("github_release_attestation_transport", "github_run_id_decimal_digits_maximum"), 19),
        (("stage_effect_budgets", "RECOVERY_IDENTITY_V2", "neon_gets_maximum"), 26),
        (("stage_effect_budgets", "RECOVERY_IDENTITY_V2", "dispatches"), True),
        (("stage_effect_budgets", "RECOVERY_IDENTITY_V2", "extra_authority"), 0),
        (("stage_effect_budgets", "DURABLE_IDENTITY_SEAL_V2", "r2_puts"), True),
        (("stage_effect_budgets", "PRODUCTION_PREFLIGHT_V2", "sql_writes"), False),
        (("stage_effect_budgets", "FOUR_RUNTIME_BINDINGS", "secret_names_in_order"), []),
        (("stage_effect_budgets", "FOUR_RUNTIME_BINDINGS", "github_api_gets_maximum"), 49),
        (("stage_effect_budgets", "FOUR_RUNTIME_BINDINGS", "invocations"), True),
        (("stage_effect_budgets", "FOUR_RUNTIME_BINDINGS", "other_secret_writes"), False),
        (("github_read_budgets", "execution_stages", "FOUR_RUNTIME_BINDINGS"), 49),
        (
            (
                "stage_effect_budgets",
                "MIGRATE_0015",
                "postgresql_connection_attempts_additional_maximum",
            ),
            5,
        ),
        (("stage_effect_budgets", "LIVE_ONCE", "postgresql_connection_attempts_maximum"), 54),
        (("stage_effect_budgets", "LIVE_ONCE", "r2_gets"), True),
        (("stage_effect_budgets", "LIVE_ONCE", "purchases"), 1),
        (("stage_effect_budgets", "REPLAY_100", "iterations_exact"), 99),
        (("stage_effect_budgets", "REPLAY_100", "external_effects"), False),
        (("stage_effect_budgets", "MIGRATE_0015", "github_workflow_dispatches"), True),
        (("stage_effect_budgets", "VERIFY_0015", "dispatches"), True),
        (("forbidden_effects", "real_bets"), 1),
    ],
)
def test_recovery_authority_rejects_semantic_contract_drift_even_when_rehashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, ...],
    value: object,
) -> None:
    document = json.loads(EFFECT_CONTRACT.read_bytes())
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _write_mutated_effect_contract(tmp_path, monkeypatch, document)
    with pytest.raises(ChronosProductionError, match="RECOVERY_V2"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E1",
            now=datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC),
            repository_root=tmp_path,
        )


def test_recovery_authority_rejects_duplicate_effect_contract_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = tmp_path / "configs" / "execution"
    execution.mkdir(parents=True)
    (execution / MANIFEST.name).write_bytes(MANIFEST.read_bytes())
    payload = EFFECT_CONTRACT.read_bytes().replace(
        b'  "mission_id":',
        b'  "mission_id": "duplicate",\n  "mission_id":',
        1,
    )
    (execution / EFFECT_CONTRACT.name).write_bytes(payload)
    monkeypatch.setattr(
        chronos_production,
        "DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    with pytest.raises(ChronosProductionError, match="AUTHORITY_INVALID"):
        validate_data_torrent_recovery_v2_authority(
            scale_stage="E1",
            now=datetime(2026, 8, 30, 13, 0, 0, tzinfo=UTC),
            repository_root=tmp_path,
        )


def test_recovery_mission_matrix_is_sorted_unique_and_requires_four_keys() -> None:
    matrix = json.loads(MATRIX.read_bytes())
    mission = matrix["missions"]["DATA_TORRENT_RECOVERY_V2"]
    paths = mission["allowed_paths"]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert mission["writer"] == "C0"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
        "platform": ["A2"],
    }
    delivery = matrix["authorization"]["data_torrent_recovery_v2_delivery"]
    for clause in (
        "ENGINEERING_PULL_REQUESTS_MAX_2",
        "CONSOLIDATED_EXACT_HEAD_SAFE_V2_CYCLES_PER_ENGINEERING_PR_MAX_3",
        "ENGINEERING_EXACT_HEAD_SAFE_V2_CYCLES_TOTAL_MAX_6",
        "FAILED_RUN_RERUNS_0",
        "HISTORICAL_CI_RUNS_0",
        "CI_PHASE_BUDGETS_NON_FUNGIBLE",
        "REQUIRE_MERGE_COMMIT_SUBJECT_PREFIX_DATA_TORRENT_RECOVERY_V2_"
        "EXACT_FIRST_PARENT_GITHUB_EVENT_BEFORE_AND_PARENT_COUNT_2",
        "ALLOW_ONE_ORDINARY_NON_FORCE_FAST_FORWARD_OF_LEGACY_PROVIDER_BRANCH_FROM_EXACT_START_SHA_"
        "TO_EXACT_POSTMERGE_MAIN_WITHIN_ENGINEERING_REQUIRED_SLOT_AFTER_POSTMERGE_SAFE_V2_"
        "AND_BEFORE_QUARANTINE",
    ):
        assert clause in delivery
    delivery = matrix["authorization"]["data_torrent_recovery_v2_delivery"]
    assert "FOUR_INDEPENDENT_REVIEWS_DP6_C4_C2_A2" in delivery
    assert "THREE_INDEPENDENT_REVIEWS" not in delivery
    assert ".github/workflows/data-torrent-replay-v2.yml" not in paths
    assert "scripts/run_data_torrent_replay_v2.py" not in paths
    assert "scripts/run_data_torrent_v1.py" not in paths
    assert "scripts/install_chronos_runtime_bindings_v1.py" not in paths


def test_owner_authorization_and_implementation_release_are_independently_verified() -> None:
    graph = json.loads(EVIDENCE_GRAPH.read_bytes())
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    authority = claims["GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001"]
    assert authority["artifact"] == "configs/execution/data-torrent-recovery-v2.json"
    assert authority["hash"] == DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256
    assert authority["code_revision"] == chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA
    assert authority["execution_id"] == "council-record:RCV3-20260830-193"
    assert authority["status"] == "VERIFIED"
    assert authority["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]
    predecessor = claims["GOV.COUNCIL.DATA_TORRENT_READY.EVIDENCE.SUCCESSION.LEDGER.V1.009"]
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == authority["claim_id"]
    initial_release = claims["GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.001"]
    assert initial_release["status"] == "SUPERSEDED"
    assert initial_release["superseded_by"] == (
        "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002"
    )
    release = claims["GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002"]
    assert release["artifact"] == chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH
    assert release["status"] == "SUPERSEDED"
    assert release["superseded_by"] == (
        chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM
    )
    assert release["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]
    failure = claims[chronos_production._RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM]
    assert failure["status"] == "VERIFIED"
    assert failure["successor_of"] == release["claim_id"]
    local_release = claims[chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM]
    assert local_release["artifact"] == (
        chronos_production.DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH
    )
    assert local_release["status"] == "SUPERSEDED"
    assert local_release["superseded_by"] == (
        chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM
    )
    assert local_release["successor_of"] == failure["claim_id"]
    assert local_release["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]
    static_failure = claims[chronos_production._RECOVERY_V2_STATIC_QA_FAILURE_CLAIM]
    assert static_failure["status"] == "VERIFIED"
    assert static_failure["successor_of"] == local_release["claim_id"]
    static_release = claims[chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM]
    assert static_release["artifact"] == (
        chronos_production.DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH
    )
    assert static_release["status"] == "VERIFIED"
    assert static_release["successor_of"] == static_failure["claim_id"]
    assert static_release["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]
    superseded = {
        "GOV.FIRST_C0.PR69.CI.WORKTREE_SCOPE.ISOLATION.V1.005",
        "GOV.CI.DATA_TORRENT_READY.FULL_SUITE.CORRECTION.V1.001",
        "GOV.CI.DATA_TORRENT_READY.EXACT_HEAD.POSTGRESQL.CORRECTION.V1.001",
    }
    for claim_id in superseded:
        assert claims[claim_id]["status"] == "SUPERSEDED"
        assert claims[claim_id]["superseded_by"] == initial_release["claim_id"]


def test_v31_implementation_limits_remain_scoped_to_control_and_record_code() -> None:
    policy = json.loads(SCALE_POLICY.read_bytes())
    scope_review = json.loads(
        (ROOT / "reports" / "council" / "v31-scope-drift-review.json").read_bytes()
    )
    final_review = json.loads(
        (ROOT / "reports" / "council" / "governance-final-review-v3.json").read_bytes()
    )
    assert policy["policy_role"] == "CONTROL_AND_RECORD_ONLY"
    assert policy["executes_workloads"] is False
    assert final_review["reviewed_scope"] == "PHASE_A_V31_MINIMAL_POLICY_CONTROL_ONLY"
    assert final_review["implementation_limits"] == policy["implementation_limits"]
    assert scope_review["post_simplification"]["within_limits"] is True
    assert "two governance source files" in scope_review["post_simplification"]["measurement"]


def _copy_frozen_council_release(tmp_path: Path) -> Path:
    for relative in (
        *chronos_production.DATA_TORRENT_RECOVERY_V2_RELEASE_PATHS,
        "reports/council/decision-ledger.jsonl",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return tmp_path


def _rewrite_test_council_chain(
    root: Path,
    *,
    start_decision_id: str,
    mutator: Callable[[dict[str, object], list[dict[str, object]]], None],
) -> list[dict[str, object]]:
    """Rehash a synthetic suffix so a mutant reaches the intended invariant."""

    ledger_path = root / "reports/council/decision-ledger.jsonl"
    records = [
        cast(dict[str, object], json.loads(line))
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    start_index = next(
        index
        for index, record in enumerate(records)
        if record.get("decision_id") == start_decision_id
    )
    mutator(records[start_index], records)
    for index in range(start_index, len(records)):
        record = records[index]
        if index > 0:
            record["previous_hash"] = records[index - 1]["hash"]
        unsigned = {key: value for key, value in record.items() if key != "hash"}
        record["hash"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    ledger_path.write_bytes(b"\n".join(_canonical(record) for record in records) + b"\n")

    changed = {
        cast(str, record["decision_id"]): cast(str, record["hash"])
        for record in records[start_index:]
    }
    graph_path = root / "reports/evidence/evidence-graph.json"
    graph = cast(dict[str, object], json.loads(graph_path.read_bytes()))
    for node in cast(list[dict[str, object]], graph["decision_nodes"]):
        decision_id = node.get("decision_id")
        if isinstance(decision_id, str) and decision_id in changed:
            node["ledger_record_hash"] = changed[decision_id]
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return records


def test_frozen_council_release_guard_accepts_exact_current_bytes() -> None:
    records = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    expected = next(
        record["hash"] for record in records if record["decision_id"] == "RCV3-20260831-200"
    )
    assert (
        validate_data_torrent_recovery_v2_council_release(
            repository_root=ROOT,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )
        == expected
    )
    projection = data_torrent_recovery_v2_release_projection(ROOT)
    assert projection["projection_schema"] == "sha256-sorted-path-utf8-lf-sha256-v1"
    assert projection["excluded_paths"] == [
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
    ]
    assert not {
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
    } & {item["path"] for item in projection["files"]}
    assert {
        *chronos_production.DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS.values(),
        chronos_production.DATA_TORRENT_RECOVERY_V2_INITIAL_FINAL_REVIEW_PATH,
        *chronos_production.DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS.values(),
        chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_REVIEW_PATH,
        *chronos_production.DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS.values(),
        chronos_production.DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_FINAL_REVIEW_PATH,
        *chronos_production.DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS.values(),
        chronos_production.DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_FINAL_REVIEW_PATH,
    } <= {item["path"] for item in projection["files"]}
    assert all(set(item) == {"path", "lf_sha256"} for item in projection["files"])


@pytest.mark.parametrize(
    "relative",
    (
        "docs/operations/DATA-TORRENT-RECOVERY-V2.md",
        "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        "scripts/install_chronos_runtime_bindings_v2.py",
        "tests/activation/test_chronos_migrate_verify_v2.py",
        "tests/activation/test_chronos_runtime_bindings_v2.py",
    ),
)
def test_record_200_rejects_each_sensitive_correction_path_omission(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)

    def omit_path(
        record: dict[str, object],
        _records: list[dict[str, object]],
    ) -> None:
        context = cast(dict[str, object], record["context"])
        files = cast(list[str], context["files"])
        assert relative in files
        files.remove(relative)

    _rewrite_test_council_chain(
        root,
        start_decision_id="RCV3-20260831-200",
        mutator=omit_path,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


@pytest.mark.parametrize(
    ("decision_id", "mutation"),
    (
        ("RCV3-20260831-197", "extra_top_level"),
        ("RCV3-20260831-198", "extra_top_level"),
        ("RCV3-20260831-197", "fractional_timestamp"),
        ("RCV3-20260831-198", "equal_predecessor_timestamp"),
        ("RCV3-20260831-197", "boolean_zero_counter"),
        ("RCV3-20260831-198", "boolean_writer_count"),
        ("RCV3-20260831-199", "extra_top_level"),
        ("RCV3-20260831-200", "extra_top_level"),
        ("RCV3-20260831-199", "fractional_timestamp"),
        ("RCV3-20260831-200", "equal_predecessor_timestamp"),
        ("RCV3-20260831-199", "boolean_zero_counter"),
        ("RCV3-20260831-200", "boolean_writer_count"),
    ),
)
def test_local_correction_pair_rejects_fully_rehashed_shape_type_and_time_mutants(
    tmp_path: Path,
    decision_id: str,
    mutation: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)

    def mutate(
        record: dict[str, object],
        records: list[dict[str, object]],
    ) -> None:
        if mutation == "extra_top_level":
            record["forged_external_authority"] = True
        elif mutation == "fractional_timestamp":
            record["date"] = cast(str, record["date"]).replace("Z", ".000Z")
        elif mutation == "equal_predecessor_timestamp":
            index = records.index(record)
            record["date"] = records[index - 1]["date"]
        elif mutation == "boolean_zero_counter":
            context = cast(dict[str, object], record["context"])
            effects = cast(dict[str, object], context["observed_external_effects"])
            effects["git_remote_writes"] = False
        elif mutation == "boolean_writer_count":
            cast(dict[str, object], record["context"])["writer_count"] = True
        else:
            raise AssertionError(mutation)

    _rewrite_test_council_chain(
        root,
        start_decision_id=decision_id,
        mutator=mutate,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


@pytest.mark.parametrize(
    "decision_id",
    (
        "RCV3-20260831-197",
        "RCV3-20260831-198",
        "RCV3-20260831-199",
        "RCV3-20260831-200",
    ),
)
def test_local_correction_pair_rejects_noncanonical_raw_record_lines(
    tmp_path: Path,
    decision_id: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    ledger_path = root / "reports/council/decision-ledger.jsonl"
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    index = next(
        offset for offset, line in enumerate(lines) if f'"decision_id":"{decision_id}"' in line
    )
    lines[index] = json.dumps(json.loads(lines[index]), ensure_ascii=False)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


@pytest.mark.parametrize("failure_id", ("RCV3-20260831-197", "RCV3-20260831-199"))
@pytest.mark.parametrize("mutation", ("partial", "inverted", "intercalated"))
def test_local_correction_pair_is_mandatory_ordered_and_contiguous(
    tmp_path: Path,
    failure_id: str,
    mutation: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    ledger_path = root / "reports/council/decision-ledger.jsonl"
    records = [
        cast(dict[str, object], json.loads(line))
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    failure_index = next(
        index
        for index, record in enumerate(records)
        if record.get("decision_id") == failure_id
    )
    release_index = failure_index + 1
    if mutation == "partial":
        records.pop(release_index)
    elif mutation == "inverted":
        records[failure_index], records[release_index] = (
            records[release_index],
            records[failure_index],
        )
    elif mutation == "intercalated":
        failure_date = datetime.fromisoformat(
            cast(str, records[failure_index]["date"]).replace("Z", "+00:00")
        )
        foreign_unsigned: dict[str, object] = {
            "decision_id": "RCV3-20260831-999",
            "record_type": "VETO",
            "date": (failure_date + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "proposal": "A foreign Council record cannot interleave the correction pair.",
            "objections": [],
            "proof": [chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM],
            "decision": "PASS_AND_HOLD",
            "dissent": None,
            "responsible": "C0",
            "context": {"mission_id": "DATA_TORRENT_RECOVERY_V2"},
            "previous_hash": records[failure_index]["hash"],
            "hash_algorithm": "SHA-256",
        }
        records.insert(
            release_index,
            {
                **foreign_unsigned,
                "hash": hashlib.sha256(_canonical(foreign_unsigned)).hexdigest(),
            },
        )
    else:
        raise AssertionError(mutation)
    for index in range(failure_index, len(records)):
        record = records[index]
        record["previous_hash"] = records[index - 1]["hash"]
        unsigned = {key: value for key, value in record.items() if key != "hash"}
        record["hash"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    ledger_path.write_bytes(b"\n".join(_canonical(record) for record in records) + b"\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


def test_frozen_council_release_guard_rejects_candidate_byte_drift(tmp_path: Path) -> None:
    root = _copy_frozen_council_release(tmp_path)
    candidate = root / "scripts" / "run_data_torrent_v2.py"
    candidate.write_bytes(candidate.read_bytes() + b"\n# unauthorized drift\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "relative",
    (
        chronos_production.DATA_TORRENT_RECOVERY_V2_INITIAL_REVIEW_PATHS["C4"],
        chronos_production.DATA_TORRENT_RECOVERY_V2_REVIEW_PATHS["C4"],
        chronos_production.DATA_TORRENT_RECOVERY_V2_LOCAL_CORRECTION_REVIEW_PATHS["C4"],
        chronos_production.DATA_TORRENT_RECOVERY_V2_STATIC_CORRECTION_REVIEW_PATHS["C4"],
    ),
)
def test_frozen_council_release_guard_rejects_initial_or_correction_review_drift(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    review = root / relative
    review.write_bytes(review.read_bytes().replace(b'"confidence":', b'"confidence":0,"drift":'))
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize("in_context", (False, True))
def test_frozen_council_release_guard_rejects_rehashed_extra_authority_field(
    tmp_path: Path,
    in_context: bool,
) -> None:
    root = _copy_frozen_council_release(tmp_path)

    def mutate(
        release: dict[str, object],
        _records: list[dict[str, object]],
    ) -> None:
        if in_context:
            cast(dict[str, object], release["context"])["forged_external_authority"] = True
        else:
            release["forged_external_authority"] = True

    _rewrite_test_council_chain(
        root,
        start_decision_id="RCV3-20260830-196",
        mutator=mutate,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("claim_id", "field", "value"),
    (
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.001",
            "status",
            "VERIFIED",
        ),
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.001",
            "superseded_by",
            None,
        ),
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002",
            "code_revision",
            "f" * 40,
        ),
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002",
            "claim",
            "Narrative drift must fail closed.",
        ),
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002",
            "source",
            "Source drift must fail closed.",
        ),
        (
            chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM,
            "superseded_by",
            chronos_production._RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
        ),
        (
            chronos_production._RECOVERY_V2_LOCAL_QA_FAILURE_CLAIM,
            "successor_of",
            "GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
        ),
        (
            chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
            "successor_of",
            chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM,
        ),
        (
            chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
            "status",
            "VERIFIED",
        ),
        (
            chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
            "superseded_by",
            chronos_production._RECOVERY_V2_PR_B_RELEASE_CLAIM,
        ),
        (
            chronos_production._RECOVERY_V2_STATIC_QA_FAILURE_CLAIM,
            "successor_of",
            chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM,
        ),
        (
            chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
            "successor_of",
            chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        ),
        (
            chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
            "status",
            "SUPERSEDED",
        ),
    ),
)
def test_frozen_council_release_guard_rejects_release_claim_lineage_drift(
    tmp_path: Path,
    claim_id: str,
    field: str,
    value: object,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    graph_path = root / "reports" / "evidence" / "evidence-graph.json"
    graph = json.loads(graph_path.read_bytes())
    claim = next(item for item in graph["claims"] if item["claim_id"] == claim_id)
    if value is None:
        claim.pop(field, None)
    else:
        claim[field] = value
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


@pytest.mark.parametrize(
    "mutation",
    ("failure_edge_id", "failure_edge_source", "foreign_edge_before_failure"),
)
@pytest.mark.parametrize("failure_id", ("RCV3-20260831-197", "RCV3-20260831-199"))
def test_local_correction_release_graph_rejects_edge_identity_and_boundary_mutants(
    tmp_path: Path,
    failure_id: str,
    mutation: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    graph_path = root / "reports/evidence/evidence-graph.json"
    graph = json.loads(graph_path.read_bytes())
    failure_edge_index = next(
        index
        for index, edge in enumerate(graph["edges"])
        if edge.get("to_decision_id") == failure_id
    )
    failure_edge = graph["edges"][failure_edge_index]
    if mutation == "failure_edge_id":
        failure_edge["edge_id"] = "EDGE.TEST.197"
    elif mutation == "failure_edge_source":
        failure_edge["from_claim_id"] = chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM
    elif mutation == "foreign_edge_before_failure":
        graph["edges"].insert(
            failure_edge_index,
            {
                "edge_id": "EDGE.TEST.FOREIGN",
                "from_claim_id": "GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
                "to_decision_id": "RCV3-TEST-FOREIGN",
                "relation": "SUPPORTS",
                "status": "RECORDED",
            },
        )
    else:
        raise AssertionError(mutation)
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=_RECOVERY_V2_TEST_NOW,
        )


def _append_test_council_successor(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    successor_count: int = 3,
    **terminal_overrides: object,
) -> None:
    """Materialize a canonical prefix of the three-step runtime Council closure."""

    assert type(successor_count) is int and successor_count in {1, 2, 3}

    from scripts.materialize_data_torrent_recovery_v2_terminal_evidence import (
        _intent_documents,
    )

    ledger_path = root / "reports/council/decision-ledger.jsonl"
    records = [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()
    ]
    release_claims = {
        chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM,
        chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
        chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
        chronos_production._RECOVERY_V2_PR_B_RELEASE_CLAIM,
    }
    release = next(
        record
        for record in reversed(records)
        if record.get("record_type") == "DECISION"
        and isinstance(record.get("proof"), list)
        and len(record["proof"]) == 1
        and record["proof"][0] in release_claims
    )
    active_release_claim = cast(str, release["proof"][0])
    runtime_main_sha = "b" * 40
    reservation_commit_sha = "c" * 40
    pr_c_phase_one_head_sha = "d" * 40
    release_date = datetime.fromisoformat(cast(str, release["date"]).replace("Z", "+00:00"))
    reservation_date = release_date + timedelta(minutes=1)
    phase_one_date = release_date + timedelta(minutes=2, seconds=25)
    live_completed_at = release_date + timedelta(minutes=2, seconds=10)
    quiescence_observed_at = release_date + timedelta(minutes=2, seconds=20)
    delivery_observed_at = release_date + timedelta(minutes=2, seconds=30)
    generated_at = release_date + timedelta(minutes=3)
    terminal_date = release_date + timedelta(minutes=4)

    def utc_text(value: datetime) -> str:
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fixture_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def stage_effects(**values: int) -> dict[str, int]:
        effects = {
            field: 0 for field in chronos_production._RECOVERY_V2_STAGE_EFFECT_FIELDS
        }
        effects.update(values)
        return effects

    terminal_intent, delivery_intent = _intent_documents(
        main_sha=runtime_main_sha,
        live_run_id="106",
        engineering_numbers=(80,),
    )
    terminal_intent_payload = _canonical(terminal_intent) + b"\n"
    delivery_intent_payload = _canonical(delivery_intent) + b"\n"
    for relative, payload in (
        (
            chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
            terminal_intent_payload,
        ),
        (
            chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            delivery_intent_payload,
        ),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    effects_by_stage = {
        "RECOVERY_IDENTITY_V2": stage_effects(neon_gets=3),
        "DURABLE_IDENTITY_SEAL_V2": stage_effects(
            r2_puts=1,
            r2_gets=1,
            r2_objects=1,
        ),
        "PRODUCTION_PREFLIGHT_V2": stage_effects(
            neon_gets=5,
            neon_posts=1,
            postgresql_connection_attempts_upper_bound=3,
            postgresql_sql_statements_upper_bound=128,
            r2_gets=1,
        ),
        "MIGRATE_0015": stage_effects(
            neon_gets=2,
            postgresql_connection_attempts_upper_bound=10,
            postgresql_sql_statements_upper_bound=2_048,
            postgresql_sql_write_statements_upper_bound=1_024,
            postgresql_migrations=1,
        ),
        "VERIFY_0015": stage_effects(
            postgresql_connection_attempts_upper_bound=4,
            postgresql_sql_statements_upper_bound=128,
        ),
        "LIVE_ONCE": stage_effects(
            postgresql_connection_attempts_upper_bound=51,
            postgresql_read_transactions_attempted=5,
            postgresql_function_reads_attempted=5,
            postgresql_mutating_function_calls_attempted=41,
            postgresql_mutating_function_calls_completed=41,
            postgresql_possible_durable_mutations_upper_bound=41,
            r2_puts=2,
            r2_gets=1,
            r2_objects=2,
            official_reads=5,
            provider_requests=5,
            provider_credits=50,
            leagues=5,
            league_market_cells=10,
        ),
        "FOUR_RUNTIME_BINDINGS": stage_effects(secret_writes=4),
        "REPLAY_100": stage_effects(),
    }
    runtime_stages: dict[str, dict[str, object]] = {}
    for index, (stage, (workflow_path, verdict, payload_filename)) in enumerate(
        chronos_production._RECOVERY_V2_TERMINAL_WORKFLOW_STAGES.items(),
        1,
    ):
        runtime_stages[stage] = {
            "run_id": 100 + index,
            "run_attempt": 1,
            "workflow_path": workflow_path,
            "head_sha": runtime_main_sha,
            "artifact_id": 200 + index,
            "payload_filename": payload_filename,
            "payload_sha256": fixture_hash(f"payload:{stage}"),
            "archive_sha256": fixture_hash(f"archive:{stage}"),
            "semantic_verdict": verdict,
            "effect_counters": effects_by_stage[stage],
        }
    binding_receipt_sha = fixture_hash("runtime-bindings-receipt")
    replay_output_sha = fixture_hash("replay-output")
    runtime_stages["FOUR_RUNTIME_BINDINGS"] = {
        "run_id": 107,
        "run_attempt": 1,
        "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
        "head_sha": runtime_main_sha,
        "artifact_id": 207,
        "payload_filename": "chronos-runtime-bindings-v2.json",
        "payload_sha256": fixture_hash("runtime-bindings-payload"),
        "archive_sha256": fixture_hash("runtime-bindings-archive"),
        "semantic_verdict": "FOUR_RUNTIME_BINDINGS_INSTALLED_V2",
        "effect_counters": effects_by_stage["FOUR_RUNTIME_BINDINGS"],
        "artifact_relation": (
            "EXACT_RECEIPT_BOUND_BY_MIGRATE_CONTROLLER_INPUT_AND_SIGNED_OBJECT"
        ),
        "carrier_payload_sha256": runtime_stages["MIGRATE_0015"]["payload_sha256"],
        "runtime_bindings_receipt_path": (
            chronos_production.DATA_TORRENT_RECOVERY_V2_BINDINGS_EVIDENCE_PATH
        ),
        "runtime_bindings_receipt_sha256": binding_receipt_sha,
        "secret_writes": 4,
    }
    runtime_stages["REPLAY_100"] = {
        "run_id": 108,
        "run_attempt": 1,
        "workflow_path": ".github/workflows/data-torrent-live-v2.yml",
        "head_sha": runtime_main_sha,
        "artifact_id": 208,
        "payload_filename": "torrent-load-replay-report-v1.json",
        "payload_sha256": fixture_hash("replay-payload"),
        "archive_sha256": fixture_hash("replay-archive"),
        "semantic_verdict": "REPLAY_100_COMPLETE",
        "effect_counters": effects_by_stage["REPLAY_100"],
        "parent_stage": "LIVE_ONCE",
        "iterations_exact": 100,
        "equivalent_records": 1_000,
        "external_effects": 0,
        "output_sha256": replay_output_sha,
        "records_per_second": 250.0,
        "p95_latency_ms": 4.5,
        "peak_memory_bytes": 1_048_576,
        "idempotent": True,
    }

    live_artifact_payloads = {
        name: f"terminal-artifact:{name}".encode("utf-8")
        for name in chronos_production._RECOVERY_V2_TERMINAL_ARTIFACT_NAMES
    }
    live_archive_sha = cast(str, runtime_stages["LIVE_ONCE"]["archive_sha256"])
    terminal_artifacts = [
        {
            "name": name,
            "artifact_id": 206,
            "payload_sha256": hashlib.sha256(live_artifact_payloads[name]).hexdigest(),
            "archive_sha256": live_archive_sha,
        }
        for name in chronos_production._RECOVERY_V2_TERMINAL_ARTIFACT_NAMES
    ]
    runtime_stages["LIVE_ONCE"]["payload_sha256"] = terminal_artifacts[0][
        "payload_sha256"
    ]
    live_attestation = {
        "run_id": "106",
        "workflow_path": ".github/workflows/data-torrent-live-v2.yml",
        "head_sha": runtime_main_sha,
        "artifact_id": 206,
        "archive_sha256": live_archive_sha,
        "run_completed_observed_at": utc_text(live_completed_at),
    }
    live_attestation_payload = _canonical(live_attestation) + b"\n"
    quiescence = {
        "observed_at": utc_text(quiescence_observed_at),
        "production_workflows_quiescent_at_runtime_close": True,
        "global_queue_empty_at_runtime_close": True,
        "reservation": {"reservation_commit_sha": reservation_commit_sha},
        "worktree": {
            "tracked_status": "CLEAN",
            "unexpected_nonignored_untracked_paths": [],
            "ephemeral_release_paths_exact": True,
        },
        "full_hold": {
            "post_merge_ci": {
                "workflow_path": ".github/workflows/ci-safe-v2.yml",
                "run_id": 92,
                "run_attempt": 1,
                "head_sha": runtime_main_sha,
                "conclusion": "success",
            },
            "recovery_v2_scope_guard": {"job_id": 902, "conclusion": "success"},
        },
    }
    quiescence_payload = _canonical(quiescence) + b"\n"
    provider = {
        "receipt_path": chronos_production.DATA_TORRENT_RECOVERY_V2_PROVIDER_EVIDENCE_PATH,
        "receipt_sha256": fixture_hash("provider-neutralization-receipt"),
        "verdict": "LEGACY_PROVIDER_BRANCH_NEUTRALIZED",
        "required_current_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
        "target_main_sha": runtime_main_sha,
        "push_mode": "ORDINARY_NON_FORCE_FAST_FORWARD",
        "push_attempts": 1,
        "remote_ref_observations": 2,
        "non_fast_forward_updates": 0,
        "branch_deletes": 0,
        "automatic_retries": 0,
    }
    quarantine = {
        "receipt_path": chronos_production.DATA_TORRENT_RECOVERY_V2_QUARANTINE_EVIDENCE_PATH,
        "receipt_sha256": fixture_hash("postmerge-quarantine-receipt"),
        "verdict": "POSTMERGE_QUARANTINE_CONFIRMED",
        "automatic_retries": 0,
        "workflows_dormant": True,
        "global_queue_empty": True,
    }
    production_state = {
        "production_database_revision": "0015_data_torrent_opportunity",
        "chronos_opportunity_claim_active": True,
        "runtime_bindings_present": [
            "CHRONOS_AUTHORITY_DATABASE_URL",
            "CHRONOS_RUNTIME_DATABASE_URL",
            "CHRONOS_READER_DATABASE_URL",
            "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        ],
        "binding_writes": 4,
    }
    data_metrics = {
        "leagues_enabled": 5,
        "leagues_with_real_data": 5,
        "fixtures_captured": 5,
        "markets_requested": ["h2h", "totals"],
        "markets_returned": ["h2h", "totals"],
        "league_market_cells": 10,
        "league_market_cells_non_empty": True,
        "official_physical_reads": 5,
        "odds_provider_requests": 5,
        "odds_credits_used": 50,
        "raw_responses": 10,
        "raw_bytes": 10_000,
        "normalized_records": 10,
        "rejected_records": 0,
        "rejected_records_reason_coded": True,
        "silent_drops": 0,
        "logical_duplicates": 0,
        "temporal_leakage": 0,
        "canonical_dataset_sha256": fixture_hash("canonical-dataset"),
        "raw_durable": True,
        "normalized_durable": True,
        "lineage_complete": True,
        "missed_windows": "MISSED_NOT_BACKDATED",
    }
    qa = {
        "acceptance_percent": 100,
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "open_threads": 0,
        "gates": [
            {"name": name, "status": "PASS"}
            for name in chronos_production._RECOVERY_V2_TERMINAL_QA_GATES
        ],
    }
    stage_values = tuple(effects_by_stage.values())
    effect_counters = {
        "neon_identity_gets": effects_by_stage["RECOVERY_IDENTITY_V2"]["neon_gets"],
        "neon_preflight_gets": effects_by_stage["PRODUCTION_PREFLIGHT_V2"]["neon_gets"],
        "neon_migrate_validation_gets": effects_by_stage["MIGRATE_0015"]["neon_gets"],
        **{
            field: sum(stage[field] for stage in stage_values)
            for field in chronos_production._RECOVERY_V2_STAGE_EFFECT_FIELDS
            if field != "neon_gets"
        },
    }
    delivery_reservation_payload = _canonical({"fixture": "delivery-reservation"}) + b"\n"
    delivery_evidence_payload = _canonical(
        {"observed_at": utc_text(delivery_observed_at)}
    ) + b"\n"
    delivery = {
        "pr_a": {
            "number": 80,
            "head_sha": "a" * 40,
            "merge_commit_sha": runtime_main_sha,
            "state": "MERGED",
            "merge_method": "MERGE_COMMIT",
            "base_ref": "main",
        },
        "pr_b": "NOT_OPENED",
        "pr_c": 81,
        "pr_c_phase_one_head_sha": pr_c_phase_one_head_sha,
        "pr_c_phase_one_safe_v2": {
            "workflow_path": ".github/workflows/ci-safe-v2.yml",
            "run_id": 93,
            "run_attempt": 1,
            "head_sha": pr_c_phase_one_head_sha,
            "conclusion": "success",
            "scope_guard_job_id": 903,
            "scope_guard_conclusion": "success",
        },
        "pr_c_reservation_parent_sha": reservation_commit_sha,
        "engineering_pr_merged": True,
        "exact_head_safe_v2": {
            "workflow_path": ".github/workflows/ci-safe-v2.yml",
            "run_id": 91,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "conclusion": "success",
            "scope_guard_job_id": 901,
            "scope_guard_conclusion": "success",
        },
        "final_main_sha": None,
        "final_main_sha_definition": "PENDING_PR_C_MERGE_AND_POSTMERGE_SAFE",
        "evidence": {
            "path": chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
            "raw_sha256": hashlib.sha256(delivery_evidence_payload).hexdigest(),
        },
    }
    runtime_postmerge_safe = {
        "workflow_path": ".github/workflows/ci-safe-v2.yml",
        "run_id": 92,
        "run_attempt": 1,
        "head_sha": runtime_main_sha,
        "conclusion": "success",
        "scope_guard_job_id": 902,
        "scope_guard_conclusion": "success",
    }
    postmerge_final_gate = (
        chronos_production.data_torrent_recovery_v2_postmerge_final_gate_contract(root)
    )
    replay = runtime_stages["REPLAY_100"]
    live_semantics = {
        "data_metrics": data_metrics,
        "qa": qa,
        "live_effects": effects_by_stage["LIVE_ONCE"],
        "replay_effects": effects_by_stage["REPLAY_100"],
        "replay": {
            field: replay[field]
            for field in (
                "iterations_exact",
                "equivalent_records",
                "external_effects",
                "output_sha256",
                "payload_filename",
                "payload_sha256",
                "records_per_second",
                "p95_latency_ms",
                "peak_memory_bytes",
                "idempotent",
            )
        },
    }
    stage_evidence = {
        "runtime_stages": runtime_stages,
        "provider_neutralization": provider,
        "postmerge_quarantine": quarantine,
        "production_state": production_state,
        "payload_sha256": [],
        "archive_sha256": [],
    }
    phase_paths = chronos_production._recovery_v2_phase_one_evidence_paths()
    phase_files = [
        {"path": path, "raw_sha256": fixture_hash(f"phase-one:{path}")}
        for path in phase_paths
    ]
    phase_projection = {
        "projection_schema": "sha256-sorted-path-raw-sha256-v1",
        "files": phase_files,
        "projection_sha256": hashlib.sha256(_canonical(phase_files)).hexdigest(),
    }

    def fake_projection(_root: Path, *, paths: tuple[str, ...]) -> dict[str, object]:
        assert _root == root and paths == phase_paths
        return deepcopy(phase_projection)

    def fake_runtime(*, repository_root: Path) -> dict[str, object]:
        assert repository_root == root
        return {
            "runtime_main_sha": runtime_main_sha,
            "quiescence_payload": quiescence_payload,
            "quiescence": deepcopy(quiescence),
        }

    def fake_bundle(
        _root: Path, *, runtime_main_sha: str
    ) -> tuple[bytes, dict[str, object], dict[str, bytes]]:
        assert _root == root and runtime_main_sha == "b" * 40
        return live_attestation_payload, deepcopy(live_attestation), dict(live_artifact_payloads)

    def fake_semantics(
        artifacts: Mapping[str, bytes], *, repository_root: Path
    ) -> dict[str, object]:
        assert repository_root == root and dict(artifacts) == live_artifact_payloads
        return deepcopy(live_semantics)

    def fake_stages(
        _root: Path,
        *,
        runtime_main_sha: str,
        live_attestation: Mapping[str, object],
        live_artifact_payloads: Mapping[str, bytes],
        live_semantics: Mapping[str, object],
    ) -> dict[str, object]:
        assert _root == root and runtime_main_sha == "b" * 40
        assert dict(live_attestation) == globals_live_attestation
        assert dict(live_artifact_payloads) == globals_live_artifacts
        assert dict(live_semantics) == globals_live_semantics
        return deepcopy(stage_evidence)

    globals_live_attestation = deepcopy(live_attestation)
    globals_live_artifacts = dict(live_artifact_payloads)
    globals_live_semantics = deepcopy(live_semantics)

    def fake_quiescence(
        _root: Path,
        *,
        runtime_main_sha: str,
        live_attestation_payload: bytes,
        live_attestation: Mapping[str, object],
    ) -> tuple[bytes, dict[str, object]]:
        assert _root == root and runtime_main_sha == "b" * 40
        assert live_attestation_payload == globals_live_attestation_payload
        assert dict(live_attestation) == globals_live_attestation
        return quiescence_payload, deepcopy(quiescence)

    globals_live_attestation_payload = live_attestation_payload

    def fake_delivery(
        _root: Path, *, runtime_main_sha: str
    ) -> tuple[bytes, bytes, dict[str, object]]:
        assert _root == root and runtime_main_sha == "b" * 40
        return (
            delivery_reservation_payload,
            delivery_evidence_payload,
            deepcopy(delivery),
        )

    monkeypatch.setattr(
        chronos_production, "_recovery_v2_raw_evidence_projection", fake_projection
    )
    monkeypatch.setattr(
        chronos_production,
        "validate_data_torrent_recovery_v2_terminal_runtime_evidence",
        fake_runtime,
    )
    monkeypatch.setattr(
        chronos_production, "_recovery_v2_terminal_live_bundle", fake_bundle
    )
    monkeypatch.setattr(
        chronos_production, "_recovery_v2_terminal_live_semantics", fake_semantics
    )
    monkeypatch.setattr(
        chronos_production, "_recovery_v2_terminal_stage_evidence", fake_stages
    )
    monkeypatch.setattr(
        chronos_production, "_recovery_v2_terminal_quiescence", fake_quiescence
    )
    monkeypatch.setattr(
        chronos_production, "_recovery_v2_terminal_delivery", fake_delivery
    )

    workflow_proofs = [
        runtime_stages[stage]
        for stage in chronos_production._RECOVERY_V2_TERMINAL_WORKFLOW_STAGES
    ]
    all_run_ids = sorted({91, 92, 93, *(cast(int, proof["run_id"]) for proof in workflow_proofs)})
    all_artifact_ids = sorted(
        {
            *(cast(int, proof["artifact_id"]) for proof in workflow_proofs),
            *(cast(int, item["artifact_id"]) for item in terminal_artifacts),
        }
    )
    all_payload_sha256 = sorted(
        {
            *(cast(str, proof["payload_sha256"]) for proof in workflow_proofs),
            *(cast(str, item["payload_sha256"]) for item in terminal_artifacts),
            cast(str, provider["receipt_sha256"]),
            cast(str, quarantine["receipt_sha256"]),
            binding_receipt_sha,
            cast(str, replay["payload_sha256"]),
            hashlib.sha256(live_attestation_payload).hexdigest(),
            hashlib.sha256(quiescence_payload).hexdigest(),
            hashlib.sha256(delivery_reservation_payload).hexdigest(),
            hashlib.sha256(delivery_evidence_payload).hexdigest(),
        }
    )
    all_archive_sha256 = sorted(
        {
            *(cast(str, proof["archive_sha256"]) for proof in workflow_proofs),
            *(cast(str, item["archive_sha256"]) for item in terminal_artifacts),
        }
    )
    terminal_base: dict[str, object] = {
        "schema_version": "data-torrent-recovery-v2-terminal-report-v1",
        "report_role": "CANDIDATE_NOT_TERMINAL",
        "mission_id": "DATA_TORRENT_RECOVERY_V2",
        "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
        "runtime_main_sha": runtime_main_sha,
        "generated_at": utc_text(generated_at),
        "duration_seconds": int(
            (
                generated_at
                - datetime.fromisoformat(
                    chronos_production.DATA_TORRENT_RECOVERY_V2_NOT_BEFORE.replace(
                        "Z", "+00:00"
                    )
                )
            ).total_seconds()
        ),
        "mission_complete": False,
        "data_torrent_ready": False,
        "final_verdict": "PASS_AND_HOLD",
        "completion_states": {
            field: field != "data_torrent_ready"
            for field in chronos_production._RECOVERY_V2_TERMINAL_COMPLETION_STATES
        },
        "delivery": delivery,
        "runtime_postmerge_safe_v2": runtime_postmerge_safe,
        "postmerge_final_gate": postmerge_final_gate,
        "provider_neutralization": provider,
        "postmerge_quarantine": quarantine,
        "runtime_stages": runtime_stages,
        "production_state": production_state,
        "data_metrics": data_metrics,
        "terminal_artifacts": terminal_artifacts,
        "qa": qa,
        "effect_counters": effect_counters,
        "all_run_ids": all_run_ids,
        "all_artifact_ids": all_artifact_ids,
        "all_payload_sha256": all_payload_sha256,
        "all_archive_sha256": all_archive_sha256,
        "runtime_close_quiescence": {
            "path": chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
            "raw_sha256": hashlib.sha256(quiescence_payload).hexdigest(),
        },
        "global_quiescence": False,
        "worktree_status": "PENDING_C2_COMMIT_AND_EPHEMERAL_CLEANUP",
    }
    terminal_snapshot = hashlib.sha256(_canonical(terminal_base)).hexdigest()
    review_bindings: dict[str, dict[str, str]] = {}
    for agent_id, relative in (
        chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS.items()
    ):
        review = {
            "agent_id": agent_id,
            "mission_id": "DATA_TORRENT_RECOVERY_V2",
            "facts_verified": [
                {
                    "claim": "The exact terminal runtime snapshot is a held PR-C candidate.",
                    "evidence_refs": [
                        f"TERMINAL_RUNTIME_SNAPSHOT_SHA256:{terminal_snapshot}",
                        "TEST_ONLY_CANONICAL_TERMINAL_FIXTURE",
                    ],
                    "status": "VERIFIED",
                }
            ],
            "unknowns": [],
            "assumptions": [],
            "main_objection": (
                "P0=0; P1=0; P2=0; OPEN_THREADS=0; "
                "VERDICT=PASS_AND_HOLD_CANDIDATE"
            ),
            "risks": [],
            "minimum_decisive_test": "VERIFY_EXACT_TERMINAL_CANDIDATE_AND_FINAL_GATE",
            "recommended_action": "RUN_EXTERNAL_PR_C_POSTMERGE_FINAL_GATE",
            "scale_condition": "PR_C_MERGE_AND_POSTMERGE_SAFE_REQUIRED",
            "estimated_compute": "READ_ONLY_TERMINAL_QA",
            "estimated_external_cost": "ZERO",
            "estimated_human_time": "ONE_TERMINAL_REVIEW",
            "maintenance_impact": "NONE_TERMINAL",
            "confidence": 0.99,
        }
        payload = _canonical(review) + b"\n"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        review_bindings[agent_id] = {
            "path": relative,
            "raw_sha256": hashlib.sha256(payload).hexdigest(),
        }
    terminal_report = {
        **terminal_base,
        "reviewed_runtime_snapshot_sha256": terminal_snapshot,
        "independent_reviews": review_bindings,
    }
    terminal_payload = _canonical(terminal_report) + b"\n"
    terminal_path = root / chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
    terminal_path.parent.mkdir(parents=True, exist_ok=True)
    terminal_path.write_bytes(terminal_payload)
    terminal_hash = hashlib.sha256(terminal_payload).hexdigest()

    def signed_record(unsigned: dict[str, object]) -> dict[str, object]:
        return {**unsigned, "hash": hashlib.sha256(_canonical(unsigned)).hexdigest()}

    reservation_id = chronos_production._recovery_v2_next_decision_id(
        cast(str, release["decision_id"]), reservation_date
    )
    reservation_unsigned: dict[str, object] = {
        "decision_id": reservation_id,
        "record_type": "STAGE_STARTED",
        "date": utc_text(reservation_date),
        "proposal": (
            "Reserve the exact Recovery V2 terminal and delivery intents before any "
            "external read."
        ),
        "objections": [],
        "proof": [
            active_release_claim,
            chronos_production._RECOVERY_V2_RESERVATION_CLAIM,
        ],
        "decision": "PASS_AND_HOLD",
        "dissent": None,
        "responsible": "C0",
        "context": {
            "mission_id": "DATA_TORRENT_RECOVERY_V2",
            "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
            "release_decision_id": release["decision_id"],
            "release_record_hash": release["hash"],
            "active_release_claim_id": active_release_claim,
            "manifest_hashes": {
                "raw_sha256": chronos_production.DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256,
                "canonical_sha256": (
                    chronos_production.DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256
                ),
                "source_hash": (
                    chronos_production.DATA_TORRENT_RECOVERY_V2_OWNER_DIRECTIVE_SHA256
                ),
            },
            "effect_contract_hashes": {
                "raw_sha256": (
                    chronos_production.DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256
                ),
                "canonical_sha256": (
                    chronos_production.DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256
                ),
            },
            "scale_stage": "E4",
            "phase": "TERMINAL_EVIDENCE_RESERVATION",
            "writer": "C0",
            "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
            "branch": "codex/data-torrent-recovery-v2",
            "head": runtime_main_sha,
            "runtime_main_sha": runtime_main_sha,
            "live_run_id": "106",
            "engineering_pull_request_numbers": [80],
            "pr": "PR_C_PENDING",
            "files": sorted(
                [
                    chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                    chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
                    "reports/council/decision-ledger.jsonl",
                    "reports/evidence/evidence-graph.json",
                ]
            ),
            "targeted_tests": {
                "dual_intent_bytes": "PASS",
                "reservation_crash_adoption": "PASS",
                "scope_guard_pr_c_c0": "PASS",
            },
            "proofs_reused": [
                f"active-release-claim:{active_release_claim}",
                f"manifest-raw:{chronos_production.DATA_TORRENT_RECOVERY_V2_MANIFEST_SHA256}",
                f"manifest-canonical:{chronos_production.DATA_TORRENT_RECOVERY_V2_MANIFEST_CANONICAL_SHA256}",
                f"effect-contract-raw:{chronos_production.DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_SHA256}",
                f"effect-contract-canonical:{chronos_production.DATA_TORRENT_RECOVERY_V2_EFFECT_CONTRACT_CANONICAL_SHA256}",
            ],
            "terminal_intent": {
                "path": chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                "raw_sha256": hashlib.sha256(terminal_intent_payload).hexdigest(),
            },
            "delivery_intent": {
                "path": chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
                "raw_sha256": hashlib.sha256(delivery_intent_payload).hexdigest(),
            },
            "intent_set_sha256": terminal_intent["intent_set_sha256"],
            "external_read_upper_bounds": {
                "terminal_runtime_close_github_gets": 13,
                "terminal_pr_c_c1_status_observation_gets": 30,
                "terminal_pr_c_c2_status_observation_gets": 30,
                "terminal_postmerge_run_observation_gets": 19,
                "terminal_postmerge_final_gate_gets": 34,
                "terminal_github_gets_total": 126,
                "terminal_artifact_downloads": 1,
                "terminal_git_remote_ref_observations": 1,
                "delivery_github_gets": 5,
                "delivery_artifact_downloads": 0,
                "delivery_git_remote_ref_observations": 1,
                "terminal_slot_github_gets_total": 131,
                "terminal_slot_github_gets_maximum": 136,
            },
            "shared_git_effect_upper_bound": {
                "commits": 3,
                "non_force_pushes": 3,
                "force_pushes": 0,
            },
            "automatic_retries": 0,
            "data_torrent_ready": False,
        },
        "previous_hash": release["hash"],
        "hash_algorithm": "SHA-256",
    }
    reservation_record = signed_record(reservation_unsigned)
    phase_one_id = chronos_production._recovery_v2_next_decision_id(
        reservation_id, phase_one_date
    )
    phase_one_files = [
        *(
            path
            for path in phase_paths
            if path
            not in {
                chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_PATH,
            }
        ),
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
    ]
    phase_one_unsigned: dict[str, object] = {
        "decision_id": phase_one_id,
        "record_type": "STAGE_FINISHED",
        "date": utc_text(phase_one_date),
        "proposal": (
            "Record Recovery V2 E4 runtime and phase-one evidence while readiness "
            "remains held."
        ),
        "objections": [],
        "proof": [
            active_release_claim,
            chronos_production._RECOVERY_V2_RESERVATION_CLAIM,
            chronos_production._RECOVERY_V2_PHASE_ONE_CLAIM,
        ],
        "decision": "PASS_AND_HOLD",
        "dissent": None,
        "responsible": "C0",
        "context": {
            "mission_id": "DATA_TORRENT_RECOVERY_V2",
            "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
            "release_decision_id": release["decision_id"],
            "release_record_hash": release["hash"],
            "active_release_claim_id": active_release_claim,
            "reservation_decision_id": reservation_id,
            "reservation_record_hash": reservation_record["hash"],
            "reservation_commit_sha": reservation_commit_sha,
            "scale_stage": "E4",
            "phase": "TERMINAL_EVIDENCE_PHASE_ONE",
            "writer": "C0",
            "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
            "branch": "codex/data-torrent-recovery-v2",
            "head": reservation_commit_sha,
            "runtime_main_sha": runtime_main_sha,
            "pr": "PR_C_PENDING",
            "files": phase_one_files,
            "targeted_tests": {
                "runtime_evidence_semantics": "PASS",
                "terminal_phase_one_projection": "PASS",
                "scope_guard_pr_c_c1": "PASS",
            },
            "proofs_reused": [
                f"active-release-claim:{active_release_claim}",
                f"reservation-claim:{chronos_production._RECOVERY_V2_RESERVATION_CLAIM}",
                f"reservation-commit:{reservation_commit_sha}",
                f"runtime-close-quiescence-raw:{hashlib.sha256(quiescence_payload).hexdigest()}",
            ],
            "phase_one_projection": phase_projection,
            "runtime_close_quiescence": {
                "path": chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
                "raw_sha256": hashlib.sha256(quiescence_payload).hexdigest(),
            },
            "data_torrent_ready": False,
        },
        "previous_hash": reservation_record["hash"],
        "hash_algorithm": "SHA-256",
    }
    phase_one_record = signed_record(phase_one_unsigned)
    terminal_id = chronos_production._recovery_v2_next_decision_id(
        phase_one_id, terminal_date
    )
    terminal_unsigned: dict[str, object] = {
        "decision_id": terminal_id,
        "record_type": "DECISION",
        "date": utc_text(terminal_date),
        "proposal": (
            "Record the Recovery V2 PR-C terminal candidate pending merge and "
            "postmerge SAFE V2."
        ),
        "objections": [],
        "proof": [
            active_release_claim,
            chronos_production._RECOVERY_V2_RESERVATION_CLAIM,
            chronos_production._RECOVERY_V2_PHASE_ONE_CLAIM,
            chronos_production._RECOVERY_V2_TERMINAL_CLAIM,
        ],
        "decision": "PASS_AND_HOLD",
        "dissent": None,
        "responsible": "C0",
        "context": {
            "mission_id": "DATA_TORRENT_RECOVERY_V2",
            "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
            "release_decision_id": release["decision_id"],
            "release_record_hash": release["hash"],
            "active_release_claim_id": active_release_claim,
            "reservation_decision_id": reservation_id,
            "reservation_record_hash": reservation_record["hash"],
            "phase_one_decision_id": phase_one_id,
            "phase_one_record_hash": phase_one_record["hash"],
            "phase_one_projection_sha256": phase_projection["projection_sha256"],
            "scale_stage": "E4",
            "phase": "TERMINAL_EVIDENCE_PR_C",
            "writer": "C0",
            "worktree": "ENGINEERING_WORKTREE:data-torrent-recovery-v2",
            "branch": "codex/data-torrent-recovery-v2",
            "head": pr_c_phase_one_head_sha,
            "pr": "PR_C:81",
            "files": sorted(
                {
                    chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_RESERVATION_EVIDENCE_PATH,
                    chronos_production.DATA_TORRENT_RECOVERY_V2_DELIVERY_EVIDENCE_PATH,
                    *chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS.values(),
                    chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH,
                    "reports/council/decision-ledger.jsonl",
                    "reports/evidence/evidence-graph.json",
                }
            ),
            "targeted_tests": {
                "scope_guard_pr_c_c2": "PASS",
                "terminal_independent_qa": "PASS",
                "terminal_runtime_semantics": "PASS",
            },
            "proofs_reused": [
                f"active-release-claim:{active_release_claim}",
                f"reservation-record:{reservation_record['hash']}",
                f"phase-one-record:{phase_one_record['hash']}",
                f"terminal-runtime-snapshot:{terminal_snapshot}",
            ],
            "terminal_report": {
                "path": chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH,
                "raw_sha256": terminal_hash,
            },
            "postmerge_final_gate_contract_sha256": hashlib.sha256(
                _canonical(postmerge_final_gate)
            ).hexdigest(),
            "data_torrent_ready": False,
            "runtime_main_sha": runtime_main_sha,
        },
        "previous_hash": phase_one_record["hash"],
        "hash_algorithm": "SHA-256",
    }
    terminal_unsigned.update(terminal_overrides)
    terminal_record = signed_record(terminal_unsigned)
    successor_records = (reservation_record, phase_one_record, terminal_record)[
        :successor_count
    ]
    with ledger_path.open("a", encoding="utf-8", newline="\n") as stream:
        for record in successor_records:
            stream.write(_canonical(record).decode("utf-8") + "\n")

    graph_path = root / "reports/evidence/evidence-graph.json"
    graph = json.loads(graph_path.read_bytes())
    reservation_claim = chronos_production._RECOVERY_V2_RESERVATION_CLAIM
    phase_one_claim = chronos_production._RECOVERY_V2_PHASE_ONE_CLAIM
    terminal_claim = chronos_production._RECOVERY_V2_TERMINAL_CLAIM
    successor_claims = [
            {
                "claim_id": reservation_claim,
                "claim": (
                    "Recovery V2 terminal and delivery external-read intents are durably "
                    "reserved; no read has been attempted"
                ),
                "scope": "DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION",
                "source": chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                "grain": "ONE_RUNTIME_MAIN_TO_ONE_DUAL_INTENT_RESERVATION",
                "temporal_class": "DECISION_AS_OF",
                "artifact": chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_RESERVATION_PATH,
                "hash": hashlib.sha256(terminal_intent_payload).hexdigest(),
                "code_revision": runtime_main_sha,
                "execution_id": f"council-record:{reservation_id}",
                "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
                "dataset_lineage_id": terminal_intent["intent_set_sha256"],
                "status": "VERIFIED",
                "verified_by": ["C0", "C2", "C4"],
                "successor_of": active_release_claim,
            },
            {
                "claim_id": phase_one_claim,
                "claim": (
                    "Recovery V2 runtime E4 and terminal evidence phase one are complete; "
                    "READY remains held"
                ),
                "scope": "DATA_TORRENT_RECOVERY_V2_TERMINAL_PHASE_ONE",
                "source": chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
                "grain": "ONE_RUNTIME_MAIN_TO_ONE_PHASE_ONE_STAGE_FINISHED",
                "temporal_class": "DECISION_AS_OF",
                "artifact": chronos_production.DATA_TORRENT_RECOVERY_V2_FINAL_QUIESCENCE_PATH,
                "hash": hashlib.sha256(quiescence_payload).hexdigest(),
                "code_revision": runtime_main_sha,
                "execution_id": f"council-record:{phase_one_id}",
                "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
                "dataset_lineage_id": phase_projection["projection_sha256"],
                "status": "VERIFIED",
                "verified_by": ["C0", "CI_SAFE_V2", "RUNTIME_RECEIPTS"],
                "successor_of": reservation_claim,
            },
            {
                "claim_id": terminal_claim,
                "claim": (
                    "Recovery V2 terminal runtime evidence and independent QA form a held "
                    "PR-C candidate pending merge and postmerge SAFE V2"
                ),
                "scope": "DATA_TORRENT_RECOVERY_V2_TERMINAL_CANDIDATE",
                "source": (
                    f"Terminal report SHA-256 {terminal_hash}; reviewed runtime snapshot "
                    f"SHA-256 {terminal_snapshot}"
                ),
                "grain": "ONE_TERMINAL_RUNTIME_TO_ONE_POSTMERGE_CANDIDATE",
                "temporal_class": "DECISION_AS_OF",
                "artifact": chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH,
                "hash": terminal_hash,
                "code_revision": pr_c_phase_one_head_sha,
                "execution_id": f"council-record:{terminal_id}",
                "scientific_lineage_id": "DATA_TORRENT_RECOVERY_V2",
                "dataset_lineage_id": terminal_snapshot,
                "status": "VERIFIED",
                "verified_by": ["C0", "C2", "C4", "DP6", "A2"],
                "successor_of": phase_one_claim,
            },
        ]
    graph["claims"].extend(successor_claims[:successor_count])
    for record in successor_records:
        graph["decision_nodes"].append(
            {"decision_id": record["decision_id"], "ledger_record_hash": record["hash"]}
        )
    proof_sets = (
        (reservation_record, [active_release_claim, reservation_claim]),
        (
            phase_one_record,
            [active_release_claim, reservation_claim, phase_one_claim],
        ),
        (
            terminal_record,
            [active_release_claim, reservation_claim, phase_one_claim, terminal_claim],
        ),
    )[:successor_count]
    numeric_edge_ids = [
        int(match.group(1))
        for edge in graph["edges"]
        if isinstance(edge.get("edge_id"), str)
        and (match := re.fullmatch(r"EDGE\.([1-9][0-9]*)", edge["edge_id"]))
        is not None
    ]
    next_edge_id = max(numeric_edge_ids) + 1
    for record, proofs in proof_sets:
        for claim_id in proofs:
            graph["edges"].append(
                {
                    "edge_id": f"EDGE.{next_edge_id}",
                    "from_claim_id": claim_id,
                    "to_decision_id": record["decision_id"],
                    "relation": "SUPPORTS",
                    "status": "RECORDED",
                }
            )
            next_edge_id += 1
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _rewrite_test_terminal_report(
    root: Path,
    mutator: Callable[[dict[str, object]], None],
    *,
    refresh_snapshot: bool = True,
) -> None:
    terminal_path = root / chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
    terminal_report = cast(dict[str, object], json.loads(terminal_path.read_bytes()))
    mutator(terminal_report)
    if refresh_snapshot:
        projection = {
            key: value
            for key, value in terminal_report.items()
            if key not in {"reviewed_runtime_snapshot_sha256", "independent_reviews"}
        }
        snapshot = hashlib.sha256(_canonical(projection)).hexdigest()
        terminal_report["reviewed_runtime_snapshot_sha256"] = snapshot
        review_bindings: dict[str, dict[str, str]] = {}
        for (
            agent_id,
            relative,
        ) in chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REVIEW_PATHS.items():
            review_path = root / relative
            review = cast(dict[str, object], json.loads(review_path.read_bytes()))
            for fact in cast(list[dict[str, object]], review["facts_verified"]):
                references = cast(list[str], fact["evidence_refs"])
                fact["evidence_refs"] = [
                    (
                        f"TERMINAL_RUNTIME_SNAPSHOT_SHA256:{snapshot}"
                        if reference.startswith("TERMINAL_RUNTIME_SNAPSHOT_SHA256:")
                        else reference
                    )
                    for reference in references
                ]
            review_payload = _canonical(review) + b"\n"
            review_path.write_bytes(review_payload)
            review_bindings[agent_id] = {
                "path": relative,
                "raw_sha256": hashlib.sha256(review_payload).hexdigest(),
            }
        terminal_report["independent_reviews"] = review_bindings
    terminal_payload = _canonical(terminal_report) + b"\n"
    terminal_path.write_bytes(terminal_payload)
    terminal_hash = hashlib.sha256(terminal_payload).hexdigest()

    ledger_path = root / "reports/council/decision-ledger.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    successor = cast(dict[str, object], records[-1])
    context = cast(dict[str, object], successor["context"])
    binding = cast(dict[str, object], context["terminal_report"])
    binding["raw_sha256"] = terminal_hash
    runtime_main_sha = terminal_report.get("runtime_main_sha")
    if isinstance(runtime_main_sha, str):
        context["runtime_main_sha"] = runtime_main_sha
    unsigned = {key: value for key, value in successor.items() if key != "hash"}
    successor["hash"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    ledger_path.write_bytes(b"\n".join(_canonical(record) for record in records) + b"\n")

    graph_path = root / "reports/evidence/evidence-graph.json"
    graph = cast(dict[str, object], json.loads(graph_path.read_bytes()))
    terminal_claim = next(
        claim
        for claim in cast(list[dict[str, object]], graph["claims"])
        if claim.get("claim_id") == chronos_production._RECOVERY_V2_TERMINAL_CLAIM
    )
    terminal_claim["hash"] = terminal_hash
    terminal_snapshot = terminal_report.get("reviewed_runtime_snapshot_sha256")
    if isinstance(terminal_snapshot, str):
        terminal_claim["dataset_lineage_id"] = terminal_snapshot
        terminal_claim["source"] = (
            f"Terminal report SHA-256 {terminal_hash}; reviewed runtime snapshot "
            f"SHA-256 {terminal_snapshot}"
        )
    terminal_node = next(
        node
        for node in cast(list[dict[str, object]], graph["decision_nodes"])
        if node.get("decision_id") == successor["decision_id"]
    )
    terminal_node["ledger_record_hash"] = successor["hash"]
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_frozen_council_release_guard_accepts_only_canonical_terminal_pr_c_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    _append_test_council_successor(root, monkeypatch)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )
    assert validate_data_torrent_recovery_v2_terminal_council_closure(
        repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
    )


def test_terminal_council_closure_requires_exactly_three_ordered_successors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)
    zero_root = _copy_frozen_council_release(tmp_path / "zero")
    assert validate_data_torrent_recovery_v2_council_release(
        repository_root=zero_root,
        now=now,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        chronos_production.validate_data_torrent_recovery_v2_reservation_council_closure(
            repository_root=zero_root,
            now=now,
        )

    one_root = _copy_frozen_council_release(tmp_path / "one")
    _append_test_council_successor(one_root, monkeypatch, successor_count=1)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=one_root,
            now=now,
        )
    assert chronos_production.validate_data_torrent_recovery_v2_reservation_council_closure(
        repository_root=one_root,
        now=now,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        chronos_production.validate_data_torrent_recovery_v2_phase_one_council_closure(
            repository_root=one_root,
            now=now,
        )

    two_root = _copy_frozen_council_release(tmp_path / "two")
    _append_test_council_successor(two_root, monkeypatch, successor_count=2)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        chronos_production.validate_data_torrent_recovery_v2_reservation_council_closure(
            repository_root=two_root,
            now=now,
        )
    assert chronos_production.validate_data_torrent_recovery_v2_phase_one_council_closure(
        repository_root=two_root,
        now=now,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=two_root,
            now=now,
        )

    three_root = _copy_frozen_council_release(tmp_path / "three")
    _append_test_council_successor(three_root, monkeypatch, successor_count=3)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        chronos_production.validate_data_torrent_recovery_v2_phase_one_council_closure(
            repository_root=three_root,
            now=now,
        )
    assert validate_data_torrent_recovery_v2_terminal_council_closure(
        repository_root=three_root,
        now=now,
    )

    four_root = _copy_frozen_council_release(tmp_path / "four")
    _append_test_council_successor(four_root, monkeypatch, successor_count=3)
    _append_test_council_successor(four_root, monkeypatch, successor_count=1)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=four_root,
            now=now,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "qa_gate_missing",
        "migrate_connections_9",
        "migrate_connections_11",
        "terminal_artifact_id",
        "terminal_artifact_archive",
        "live_manifest_payload",
        "binding_v1_verdict",
        "run_id_collision",
        "silent_drop",
        "completion_false",
        "duration_missing",
        "duration_over_budget",
    ),
)
def test_terminal_council_closure_rejects_rebound_semantic_mutants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    _append_test_council_successor(root, monkeypatch)

    def mutate(report: dict[str, object]) -> None:
        if mutation == "qa_gate_missing":
            cast(list[object], cast(dict[str, object], report["qa"])["gates"]).pop()
        elif mutation.startswith("migrate_connections_"):
            replacement = int(mutation.rsplit("_", 1)[1])
            stages = cast(dict[str, object], report["runtime_stages"])
            migrate = cast(dict[str, object], stages["MIGRATE_0015"])
            counters = cast(dict[str, int], migrate["effect_counters"])
            delta = replacement - counters["postgresql_connection_attempts_upper_bound"]
            counters["postgresql_connection_attempts_upper_bound"] = replacement
            global_counters = cast(dict[str, int], report["effect_counters"])
            global_counters["postgresql_connection_attempts_upper_bound"] += delta
        elif mutation == "terminal_artifact_id":
            artifacts = cast(list[dict[str, object]], report["terminal_artifacts"])
            artifacts[0]["artifact_id"] = 999
            report["all_artifact_ids"] = sorted(
                {
                    *cast(list[int], report["all_artifact_ids"]),
                    999,
                }
            )
        elif mutation == "terminal_artifact_archive":
            replacement = "f" * 64
            artifacts = cast(list[dict[str, object]], report["terminal_artifacts"])
            artifacts[0]["archive_sha256"] = replacement
            report["all_archive_sha256"] = sorted(
                {
                    *cast(list[str], report["all_archive_sha256"]),
                    replacement,
                }
            )
        elif mutation == "live_manifest_payload":
            replacement = "e" * 64
            stages = cast(dict[str, object], report["runtime_stages"])
            cast(dict[str, object], stages["LIVE_ONCE"])["payload_sha256"] = replacement
            report["all_payload_sha256"] = sorted(
                {
                    *cast(list[str], report["all_payload_sha256"]),
                    replacement,
                }
            )
        elif mutation == "binding_v1_verdict":
            stages = cast(dict[str, object], report["runtime_stages"])
            cast(dict[str, object], stages["FOUR_RUNTIME_BINDINGS"])[
                "semantic_verdict"
            ] = "FOUR_RUNTIME_BINDINGS_INSTALLED"
        elif mutation == "run_id_collision":
            delivery = cast(dict[str, object], report["delivery"])
            exact_head = cast(dict[str, object], delivery["exact_head_safe_v2"])
            postmerge = cast(dict[str, object], report["runtime_postmerge_safe_v2"])
            postmerge["run_id"] = exact_head["run_id"]
            report["all_run_ids"] = sorted(set(cast(list[int], report["all_run_ids"])) - {92})
        elif mutation == "silent_drop":
            cast(dict[str, object], report["data_metrics"])["silent_drops"] = 1
        elif mutation == "completion_false":
            cast(dict[str, object], report["completion_states"])["replay_verified"] = False
        elif mutation == "duration_missing":
            report.pop("duration_seconds")
        elif mutation == "duration_over_budget":
            report["duration_seconds"] = 604_801
        else:
            raise AssertionError(mutation)

    _rewrite_test_terminal_report(root, mutate)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


def test_terminal_council_closure_rejects_arbitrary_snapshot_after_full_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    _append_test_council_successor(root, monkeypatch)
    _rewrite_test_terminal_report(
        root,
        lambda report: report.__setitem__("reviewed_runtime_snapshot_sha256", "f" * 64),
        refresh_snapshot=False,
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "claim_hash",
        "claim_main",
        "claim_narrative",
        "claim_source",
        "node_hash",
        "missing_edge",
        "extra_edge",
        "intercalated_edge",
        "swapped_edge_sources",
    ),
)
def test_terminal_council_closure_rejects_graph_mutants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    _append_test_council_successor(root, monkeypatch)
    graph_path = root / "reports/evidence/evidence-graph.json"
    graph = json.loads(graph_path.read_bytes())
    terminal_claim = next(
        claim
        for claim in graph["claims"]
        if claim.get("claim_id") == chronos_production._RECOVERY_V2_TERMINAL_CLAIM
    )
    terminal_node = graph["decision_nodes"][-1]
    terminal_decision_id = terminal_node["decision_id"]
    if mutation == "claim_hash":
        terminal_claim["hash"] = "f" * 64
    elif mutation == "claim_main":
        terminal_claim["code_revision"] = "f" * 40
    elif mutation == "claim_narrative":
        terminal_claim["claim"] = "Narrative drift must fail closed."
    elif mutation == "claim_source":
        terminal_claim["source"] = "Source drift must fail closed."
    elif mutation == "node_hash":
        terminal_node["ledger_record_hash"] = "f" * 64
    elif mutation == "missing_edge":
        records = [
            json.loads(line)
            for line in (root / "reports/council/decision-ledger.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        active_release_claim = cast(
            dict[str, object], cast(dict[str, object], records[-1])["context"]
        )["active_release_claim_id"]
        graph["edges"] = [
            edge
            for edge in graph["edges"]
            if not (
                edge.get("to_decision_id") == terminal_decision_id
                and edge.get("from_claim_id") == active_release_claim
            )
        ]
    elif mutation == "extra_edge":
        graph["edges"].append(
            {
                "edge_id": "EDGE.TEST.TERMINAL.EXTRA",
                "from_claim_id": "GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
                "to_decision_id": terminal_decision_id,
                "relation": "SUPPORTS",
                "status": "RECORDED",
            }
        )
    elif mutation == "intercalated_edge":
        first_terminal_index = next(
            index
            for index, edge in enumerate(graph["edges"])
            if edge.get("to_decision_id") == terminal_decision_id
        )
        graph["edges"].insert(
            first_terminal_index,
            {
                "edge_id": "EDGE.TEST.TERMINAL.INTERCALATED",
                "from_claim_id": "GOV.AUTHORIZATION.DATA_TORRENT_RECOVERY.V2.MANIFEST.001",
                "to_decision_id": "RCV3-TEST-FOREIGN",
                "relation": "SUPPORTS",
                "status": "RECORDED",
            },
        )
    elif mutation == "swapped_edge_sources":
        terminal_edges = [
            edge
            for edge in graph["edges"]
            if edge.get("to_decision_id") == terminal_decision_id
        ]
        terminal_edges[0]["from_claim_id"], terminal_edges[1]["from_claim_id"] = (
            terminal_edges[1]["from_claim_id"],
            terminal_edges[0]["from_claim_id"],
        )
    graph_path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


def test_terminal_council_closure_rejects_missing_or_byte_drifted_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    _append_test_council_successor(root, monkeypatch)
    terminal_path = root / chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
    terminal_path.unlink()
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_MISSING"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )

    root = _copy_frozen_council_release(tmp_path / "drift")
    _append_test_council_successor(root, monkeypatch)
    terminal_path = root / chronos_production.DATA_TORRENT_RECOVERY_V2_TERMINAL_REPORT_PATH
    terminal_path.write_bytes(terminal_path.read_bytes() + b"\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )
    _append_test_council_successor(root, monkeypatch)
    _append_test_council_successor(root, monkeypatch)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


def test_frozen_council_release_guard_rejects_raw_prefix_reserialization(
    tmp_path: Path,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    ledger = root / "reports/council/decision-ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    line_index = next(
        index for index, line in enumerate(lines) if '"decision_id":"RCV3-20260830-195"' in line
    )
    lines[line_index] = json.dumps(json.loads(lines[line_index]), ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


def test_frozen_council_release_guard_rejects_release_line_reserialization(
    tmp_path: Path,
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    ledger = root / "reports/council/decision-ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    line_index = next(
        index for index, line in enumerate(lines) if '"decision_id":"RCV3-20260830-196"' in line
    )
    release = json.loads(lines[line_index])
    lines[line_index] = json.dumps(release, ensure_ascii=False)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_council_release(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"record_type": "FAILURE"},
        {"record_type": "VETO"},
        {"record_type": "REDESIGN"},
        {"decision": "FAIL_AND_STOP"},
        {"proof": []},
        {
            "proof": [
                "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002",
                "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION.RELEASE.002",
            ]
        },
        {"date": "2026-09-01T00:00:01Z"},
        {
            "context": {
                "mission_id": "DATA_TORRENT_RECOVERY_V2",
                "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
                "release_decision_id": "RCV3-20260830-196",
                "release_record_hash": "0" * 64,
                "scale_stage": "E2",
            }
        },
        {
            "context": {
                "mission_id": "DATA_TORRENT_RECOVERY_V2",
                "program_start_sha": chronos_production.DATA_TORRENT_RECOVERY_V2_START_SHA,
                "release_decision_id": "RCV3-20260830-196",
                "release_record_hash": "USE_CURRENT_RELEASE_HASH",
                "scale_stage": "E4",
            }
        },
    ),
)
def test_frozen_council_release_guard_rejects_invalid_append_only_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    root = _copy_frozen_council_release(tmp_path)
    if isinstance(overrides.get("context"), dict):
        context = dict(overrides["context"])
        if context.get("release_record_hash") == "USE_CURRENT_RELEASE_HASH":
            records = [
                json.loads(line)
                for line in (root / "reports/council/decision-ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            context["release_record_hash"] = next(
                record["hash"]
                for record in reversed(records)
                if record.get("record_type") == "DECISION"
                and isinstance(record.get("proof"), list)
                and len(record["proof"]) == 1
                and record["proof"][0]
                in {
                    chronos_production._RECOVERY_V2_BASE_RELEASE_CLAIM,
                    chronos_production._RECOVERY_V2_LOCAL_CORRECTION_RELEASE_CLAIM,
                    chronos_production._RECOVERY_V2_STATIC_CORRECTION_RELEASE_CLAIM,
                    chronos_production._RECOVERY_V2_PR_B_RELEASE_CLAIM,
                }
            )
        overrides = {**overrides, "context": context}
    _append_test_council_successor(root, monkeypatch, **overrides)
    with pytest.raises(ChronosProductionError, match="COUNCIL_RELEASE_INVALID"):
        validate_data_torrent_recovery_v2_terminal_council_closure(
            repository_root=root,
            now=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC),
        )
