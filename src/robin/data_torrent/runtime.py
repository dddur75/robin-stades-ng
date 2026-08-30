"""One-shot Ubuntu data-torrent orchestration from claim to terminal receipt."""

from __future__ import annotations

import hashlib
import importlib
import io
import math
import os
import statistics
import sys
import tarfile
import time
import tracemalloc
from collections import Counter
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, unquote, urlsplit

import sqlalchemy as sa

from robin.capture.official_schedule_sources import (
    OfficialFetchReceipt,
    OfficialFetchResult,
    OfficialScheduleEvidence,
    RedirectHop,
    SupportingOfficialRead,
    build_official_schedule_evidence,
    reconcile_official_schedule_evidence,
)
from robin.chronos_production import (
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    PRODUCTION_SAFETY_LOCKS,
    SCOPED_LOGINS,
    ChronosProductionError,
    DirectPostgresTarget,
    assert_production_safety_locks,
    generation_hash,
    require_generation_bound_password,
    require_hash,
    require_sha,
    validate_controlled_go_binding,
    validate_data_torrent_authority,
    validate_direct_postgres_url,
    verify_signed_document,
)
from robin.chronos_role_lifecycle import (
    CHRONOS_FUNCTION_SIGNATURES,
    CHRONOS_RELATIONS,
    GROUP_ROLES,
    ROLE_MARKER,
)
from robin.data_torrent.archive import (
    artifact_index,
    coverage_csv,
    deterministic_tar_gz,
    json_artifact,
    write_artifacts,
)
from robin.data_torrent.claims import (
    DataTorrentOpportunity,
    OpportunityClaimReceipt,
    PostgresExternalEffectLedger,
    PostgresOpportunityClaimer,
    PostgresTorrentBatchRecorder,
)
from robin.data_torrent.contracts import (
    RawResponseEnvelope,
    TorrentConfig,
    canonical_json_bytes,
    load_torrent_config,
    strict_json_loads,
    utc_text,
)
from robin.data_torrent.durability import (
    CountingR2Store,
    DurableObjectReceipt,
    DurableObjectUploadError,
    upload_immutable_object,
)
from robin.data_torrent.normalization import (
    NormalizedBatch,
    load_team_aliases,
    normalize_batch,
    team_alias_registry_document,
    validate_official_team_aliases,
)
from robin.data_torrent.reporting import (
    field_dictionary,
    hypothesis_backlog,
    load_replay_markdown,
    operations_pack,
    qa_matrix,
    recovery_pack,
    verify_qa_matrix,
)
from robin.data_torrent.sources import (
    ExternalEffectTrace,
    ObservedSourceResponse,
    OddsCapture,
    OfficialCapture,
    SourceCaptureProgress,
    SourceEffectCounters,
    capture_odds_sources,
    capture_official_sources,
)
from robin.prospective_observatory.chronos_control_plane import (
    GitHubRunIdentity,
    PostgresAuthorityIssuer,
    PostgresEffectLedger,
)
from robin.prospective_observatory.chronos_postgres import (
    SQLAlchemyPostgresFunctionClient,
)
from robin.prospective_observatory.chronos_r2 import ChronosR2ConditionalStore
from robin.storage.database import build_engine

MISSION_ID = "data-torrent-ready-v1"
MISSION_MANIFEST_PATH = "configs/execution/data-torrent-ready-v1.json"
MISSION_MANIFEST_SHA256 = "22e64bb33bd54aeeb528a416c7f6d0ca1c0719a27677302b8065249923ca96e7"
MISSION_SOURCE_SHA256 = "c03e218ca8f69d30f3fe998f7534d3edb11e2ba71bdd3ca022ada7ee08a2295d"
MISSION_AUTHORIZED_STAGES = ("E1", "E2", "E3A", "E3B", "E4")
MISSION_EXTERNAL_EFFECTS = (
    "git_remote_write_non_force",
    "github_pull_request_write_up_to_4",
    "github_merge_commit",
    "github_actions_exact_head_observe_and_dispatch",
    "github_environment_exact_required_secret_update",
    "neon_control_plane_read_and_scoped_credential_rotation",
    "postgresql_additive_production_migration_up_to_3",
    "official_schedule_public_reads_up_to_50",
    "odds_provider_requests_up_to_5_and_credits_up_to_1000",
    "r2_immutable_put_up_to_20_get_up_to_20_list_up_to_2_delete_0",
)
EXPECTED_REVISION = "0015_data_torrent_opportunity"
WORKFLOW_PATH = ".github/workflows/data-torrent-live-v1.yml"
HOLD_REPORT_PATH = ".torrent/hold/chronos-production-workflow-hold-live-v3.json"
VERIFY_ARTIFACT_PATH = ".torrent/release/chronos-production-verify-v3.json"
CI_WORKFLOW_PATH = ".github/workflows/ci-safe-v2.yml"
LEGACY_CI_WORKFLOW_ID = 319500816
TEAM_ALIASES_PATH = "config/alias_equipes.yaml"
MINIMUM_FIXTURE_COVERAGE_PERCENTAGE = 100.0
CROSS_RUN_CONTRACT = (
    "tests/data_torrent/test_postgresql_v1.py::"
    "test_cross_run_claim_has_one_winner_and_loser_has_zero_permits"
)
FINAL_ARTIFACT_NAMES = frozenset(
    {
        "torrent-real-batch-manifest-v1.json",
        "torrent-real-batch-raw-index-v1.json",
        "torrent-real-batch-normalized-index-v1.json",
        "torrent-real-batch-quality-report-v1.json",
        "torrent-real-batch-coverage-matrix-v1.csv",
        "torrent-load-replay-report-v1.json",
        "torrent-load-replay-report-v1.md",
        "torrent-opportunity-claim-receipt-v1.json",
        "torrent-control-plane-event-chain-v1.json",
        "torrent-official-read-receipts-v1.json",
        "torrent-provider-credit-receipt-v1.json",
        "torrent-r2-inventory-v1.json",
        "torrent-raw-to-normalized-lineage-v1.json",
        "torrent-canonical-dataset-hash-v1.json",
        "torrent-qa-acceptance-matrix-v1.json",
        "robin-data-torrent-operations-pack-v1.md",
        "robin-data-torrent-recovery-pack-v1.md",
        "hypothesis-ready-field-dictionary-v1.json",
        "hypothesis-backlog-from-real-data-v1.md",
    }
)
NORMALIZED_CORE_MEMBER_NAMES = frozenset(
    {
        "config/team-alias-registry-v1.json",
        "data/normalized-records.jsonl",
        "data/rejected-records.jsonl",
        "lineage/raw-to-normalized-v1.json",
        "reports/coverage-v1.csv",
        "reports/load-replay-v1.json",
        "science/field-dictionary-v1.json",
        "science/hypothesis-backlog-v1.md",
        "operations/operations-pack-v1.md",
        "operations/recovery-pack-v1.md",
    }
)
_CHRONOS_VIEW_RELATIONS = frozenset(
    {
        "chronos_effect_accounting",
        "chronos_opportunity_claim_audit",
        "chronos_torrent_batch_audit",
        "chronos_torrent_external_effect_audit",
    }
)
_EXPECTED_CHRONOS_RELATION_INVENTORY = frozenset(
    (name, "v" if name in _CHRONOS_VIEW_RELATIONS else "r") for name in CHRONOS_RELATIONS
)
_EXPECTED_CHRONOS_OBJECT_ACL = frozenset(
    {
        (
            "function",
            "public.chronos_issue_effect_authority("
            + CHRONOS_FUNCTION_SIGNATURES["chronos_issue_effect_authority"]
            + ")",
            "chronos_authority_executor",
            "EXECUTE",
            False,
        ),
        *{
            (
                "function",
                f"public.{name}({CHRONOS_FUNCTION_SIGNATURES[name]})",
                "chronos_runtime_writer",
                "EXECUTE",
                False,
            )
            for name in (
                "chronos_claim_effect_authority",
                "chronos_append_effect_event",
                "chronos_get_effect_state",
                "chronos_claim_opportunity",
                "chronos_reserve_torrent_external_effect",
                "chronos_append_torrent_external_effect",
                "chronos_record_torrent_batch",
            )
        },
        (
            "function",
            "public.chronos_get_effect_state("
            + CHRONOS_FUNCTION_SIGNATURES["chronos_get_effect_state"]
            + ")",
            "chronos_reader",
            "EXECUTE",
            False,
        ),
        *{
            (
                "relation",
                f"public.{name}",
                "chronos_reader",
                "SELECT",
                False,
            )
            for name in _CHRONOS_VIEW_RELATIONS
        },
    }
)


class DataTorrentRuntimeError(RuntimeError):
    """Sanitized fail-closed runtime error."""

    effect_receipt: dict[str, Any]


@dataclass(slots=True)
class LiveRuntimeEffects:
    """Conservative process-local accounting for every live runtime boundary."""

    postgresql_read_transactions_attempted: int = 0
    postgresql_function_reads_attempted: int = 0
    postgresql_mutating_function_calls_attempted: int = 0
    postgresql_mutating_function_calls_completed: int = 0
    postgresql_mutating_function_outcomes_ambiguous: int = 0
    source_counters: SourceEffectCounters | None = None
    r2_store: CountingR2Store | None = None

    def begin_read_transaction(self) -> None:
        self.postgresql_read_transactions_attempted += 1

    def begin_function_call(self, *, mutating: bool) -> None:
        if mutating:
            self.postgresql_mutating_function_calls_attempted += 1
        else:
            self.postgresql_function_reads_attempted += 1

    def complete_function_call(self, *, mutating: bool) -> None:
        if mutating:
            self.postgresql_mutating_function_calls_completed += 1

    def fail_function_call(self, *, mutating: bool) -> None:
        if mutating:
            # A disconnect can happen after the server commit but before the result
            # reaches the runner. Treat every failed mutating call as ambiguous.
            self.postgresql_mutating_function_outcomes_ambiguous += 1

    def snapshot(self) -> dict[str, Any]:
        sources = (
            self.source_counters.snapshot()
            if self.source_counters is not None
            else {
                "official_reads": 0,
                "odds_dns_resolutions": 0,
                "odds_provider_dispatches": 0,
                "odds_credits": 0,
            }
        )
        r2 = (
            self.r2_store.counters()
            if self.r2_store is not None
            else {
                "puts": 0,
                "gets": 0,
                "lists": 0,
                "deletes": 0,
            }
        )
        return {
            "schema_version": "robin-data-torrent-live-runtime-effects-v1",
            "accounting_status": "COMPLETE_CONSERVATIVE",
            "postgresql": {
                "read_transactions_attempted": self.postgresql_read_transactions_attempted,
                "function_reads_attempted": self.postgresql_function_reads_attempted,
                "mutating_function_calls_attempted": (
                    self.postgresql_mutating_function_calls_attempted
                ),
                "mutating_function_calls_completed": (
                    self.postgresql_mutating_function_calls_completed
                ),
                "mutating_function_outcomes_ambiguous": (
                    self.postgresql_mutating_function_outcomes_ambiguous
                ),
                "possible_durable_mutations_upper_bound": (
                    self.postgresql_mutating_function_calls_attempted
                ),
                "connection_attempts_upper_bound": (
                    self.postgresql_read_transactions_attempted
                    + self.postgresql_function_reads_attempted
                    + self.postgresql_mutating_function_calls_attempted
                ),
                "automatic_retries": 0,
            },
            "official": {
                "physical_reads_attempted": sources["official_reads"],
                "automatic_retries": 0,
            },
            "odds": {
                "dns_resolutions_attempted": sources["odds_dns_resolutions"],
                "provider_requests_attempted": sources["odds_provider_dispatches"],
                "credits_used_upper_bound": sources["odds_credits"],
                "automatic_retries": 0,
            },
            "r2": {
                "puts_attempted": r2["puts"],
                "gets_attempted": r2["gets"],
                "lists_attempted": r2["lists"],
                "deletes_attempted": r2["deletes"],
                "put_outcomes_ambiguous_upper_bound": max(
                    0,
                    r2["puts"] - len(self.r2_store.results),
                )
                if self.r2_store is not None
                else 0,
                "automatic_retries": 0,
            },
        }


_LIVE_RUNTIME_EFFECTS: ContextVar[LiveRuntimeEffects | None] = ContextVar(
    "data_torrent_live_runtime_effects",
    default=None,
)


def _current_live_runtime_effects() -> LiveRuntimeEffects:
    effects = _LIVE_RUNTIME_EFFECTS.get()
    if effects is None:
        raise DataTorrentRuntimeError("DATA_TORRENT_EFFECT_ACCOUNTING_NOT_ACTIVE")
    return effects


class _AccountingPostgresFunctionClient(SQLAlchemyPostgresFunctionClient):
    """Classify PostgreSQL function calls before their first network boundary."""

    def __init__(self, engine: Any, *, effects: LiveRuntimeEffects) -> None:
        super().__init__(engine)
        self._runtime_effects = effects

    def fetch_one(
        self,
        statement: str,
        parameters: Any,
    ) -> Mapping[str, object]:
        mutating = "chronos_get_effect_state" not in statement
        try:
            validate_data_torrent_authority()
        except ChronosProductionError as error:
            raise DataTorrentRuntimeError(str(error)) from None
        self._runtime_effects.begin_function_call(mutating=mutating)
        try:
            result = super().fetch_one(statement, parameters)
        except Exception:
            self._runtime_effects.fail_function_call(mutating=mutating)
            raise
        self._runtime_effects.complete_function_call(mutating=mutating)
        return result


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise DataTorrentRuntimeError(f"DATA_TORRENT_MISSING_SECRET:{name}")
    return value


def _context(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise DataTorrentRuntimeError(f"DATA_TORRENT_MISSING_CONTEXT:{name}")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    github: GitHubRunIdentity
    workflow_path: str
    workflow_file_sha256: str
    runner_os: str
    runner_arch: str
    post_merge_ci_sha: str

    def to_json(self) -> dict[str, Any]:
        return {
            "github_repository": self.github.github_repository,
            "github_run_id": self.github.github_run_id,
            "github_run_attempt": self.github.github_run_attempt,
            "github_sha": self.github.github_sha,
            "github_ref": self.github.github_ref,
            "github_workflow_ref": self.github.github_workflow_ref,
            "github_workflow_sha": self.github.github_workflow_sha,
            "workflow_path": self.workflow_path,
            "workflow_file_sha256": self.workflow_file_sha256,
            "code_revision": self.github.github_sha,
            "runner_os": self.runner_os,
            "runner_arch": self.runner_arch,
            "post_merge_ci_sha": self.post_merge_ci_sha,
        }


@dataclass(frozen=True, slots=True)
class ReplayMeasurement:
    report: dict[str, Any]
    final_batch: NormalizedBatch


def _validated_mission_manifest(
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    observed_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Validate the immutable user authorization before constructing any live client."""

    if _context(environment, "DATA_TORRENT_MISSION_MANIFEST") != MISSION_MANIFEST_PATH:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_PATH_MISMATCH")
    expected_hash = require_hash(
        _context(environment, "DATA_TORRENT_EXPECTED_MISSION_MANIFEST_SHA256"),
        field="expected_mission_manifest_sha256",
    )
    if expected_hash != MISSION_MANIFEST_SHA256:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_HASH_MISMATCH")
    path = repository_root / MISSION_MANIFEST_PATH
    try:
        if path.is_symlink():
            raise OSError
        payload = path.read_bytes()
    except OSError:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_MISSING") from None
    if not payload or len(payload) > 65_536:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_INVALID")
    payload_hash = hashlib.sha256(payload).hexdigest()
    if payload_hash != expected_hash:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_HASH_MISMATCH")
    try:
        document = strict_json_loads(
            payload,
            duplicate_code="DATA_TORRENT_MISSION_MANIFEST_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_MISSION_MANIFEST_NON_FINITE",
        )
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_INVALID") from None
    exact_fields = {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    if not isinstance(document, dict) or set(document) != exact_fields:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_SCHEMA_MISMATCH")
    manifest = cast(dict[str, Any], document)
    if (
        manifest.get("mission_id") != MISSION_ID
        or manifest.get("authorized_stages") != list(MISSION_AUTHORIZED_STAGES)
        or manifest.get("maximum_stage") != "E4"
        or manifest.get("external_effects") != list(MISSION_EXTERNAL_EFFECTS)
        or type(manifest.get("compute_budget")) is not int
        or manifest.get("compute_budget") != 1_000_000
        or type(manifest.get("time_budget")) is not int
        or manifest.get("time_budget") != 86_400
        or manifest.get("source_hash") != MISSION_SOURCE_SHA256
        or not isinstance(manifest.get("expires_at"), str)
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_MISMATCH")
    try:
        expiry = datetime.fromisoformat(cast(str, manifest["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_EXPIRY_INVALID") from None
    now = datetime.now(UTC) if observed_at_utc is None else observed_at_utc
    if (
        expiry.tzinfo is None
        or cast(str, manifest["expires_at"]) != "2026-09-01T23:59:59Z"
        or now.astimezone(UTC) >= expiry.astimezone(UTC)
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_MISSION_MANIFEST_EXPIRED")
    return {
        **manifest,
        "manifest_path": MISSION_MANIFEST_PATH,
        "manifest_sha256": payload_hash,
    }


def _assert_config_within_mission_authority(config: TorrentConfig) -> None:
    if (
        config.budgets.official_physical_reads_max > 50
        or config.budgets.odds_provider_requests_max > 5
        or config.budgets.odds_credits_max > 1_000
        or config.budgets.r2_puts_max > 20
        or config.budgets.r2_gets_max > 20
        or config.budgets.r2_lists_max > 2
        or config.budgets.r2_deletes_max != 0
        or config.budgets.automatic_retries != 0
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_CONFIG_EXCEEDS_MISSION_AUTHORITY")


def _runtime_identity(
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    system_platform: str,
) -> RuntimeIdentity:
    if system_platform != "linux" or _context(environment, "RUNNER_OS") != "Linux":
        raise DataTorrentRuntimeError("DATA_TORRENT_UBUNTU_REQUIRED")
    if _context(environment, "RUNNER_ARCH") != "X64":
        raise DataTorrentRuntimeError("DATA_TORRENT_X64_REQUIRED")
    if _context(environment, "GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPOSITORY_MISMATCH")
    if _context(environment, "GITHUB_REF") != EXPECTED_REF:
        raise DataTorrentRuntimeError("DATA_TORRENT_REF_MISMATCH")
    run_attempt = int(_context(environment, "GITHUB_RUN_ATTEMPT"))
    if run_attempt != 1:
        raise DataTorrentRuntimeError("DATA_TORRENT_RERUN_FORBIDDEN")
    github_sha = require_sha(_context(environment, "GITHUB_SHA"), field="github_sha")
    expected_main = require_sha(
        _context(environment, "DATA_TORRENT_EXPECTED_MAIN_SHA"),
        field="expected_main_sha",
    )
    workflow_sha = require_sha(
        _context(environment, "GITHUB_WORKFLOW_SHA"),
        field="github_workflow_sha",
    )
    if github_sha != expected_main or workflow_sha != expected_main:
        raise DataTorrentRuntimeError("DATA_TORRENT_EXACT_MAIN_MISMATCH")
    post_merge_ci_sha = require_sha(
        _context(environment, "DATA_TORRENT_POST_MERGE_CI_SHA"),
        field="post_merge_ci_sha",
    )
    if post_merge_ci_sha != github_sha:
        raise DataTorrentRuntimeError("DATA_TORRENT_POST_MERGE_CI_MISMATCH")
    workflow_ref = _context(environment, "GITHUB_WORKFLOW_REF")
    expected_workflow_ref = f"{EXPECTED_REPOSITORY}/{WORKFLOW_PATH}@{EXPECTED_REF}"
    if workflow_ref != expected_workflow_ref:
        raise DataTorrentRuntimeError("DATA_TORRENT_WORKFLOW_REF_MISMATCH")
    workflow_file = repository_root / WORKFLOW_PATH
    workflow_hash = hashlib.sha256(workflow_file.read_bytes()).hexdigest()
    expected_workflow_hash = require_hash(
        _context(environment, "DATA_TORRENT_EXPECTED_WORKFLOW_SHA256"),
        field="expected_workflow_sha256",
    )
    if workflow_hash != expected_workflow_hash:
        raise DataTorrentRuntimeError("DATA_TORRENT_WORKFLOW_FILE_MISMATCH")
    return RuntimeIdentity(
        github=GitHubRunIdentity(
            github_run_id=int(_context(environment, "GITHUB_RUN_ID")),
            github_run_attempt=run_attempt,
            github_sha=github_sha,
            github_workflow_ref=workflow_ref,
            github_workflow_sha=workflow_sha,
            github_repository=EXPECTED_REPOSITORY,
            github_ref=EXPECTED_REF,
        ),
        workflow_path=WORKFLOW_PATH,
        workflow_file_sha256=workflow_hash,
        runner_os="Linux",
        runner_arch=_context(environment, "RUNNER_ARCH"),
        post_merge_ci_sha=post_merge_ci_sha,
    )


def _validated_hold_report(
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    identity: RuntimeIdentity,
) -> dict[str, Any]:
    if _context(environment, "DATA_TORRENT_HOLD_REPORT") != HOLD_REPORT_PATH:
        raise DataTorrentRuntimeError("DATA_TORRENT_HOLD_REPORT_PATH_MISMATCH")
    report_path = repository_root / HOLD_REPORT_PATH
    try:
        report_bytes = report_path.read_bytes()
        document = strict_json_loads(
            report_bytes,
            duplicate_code="DATA_TORRENT_HOLD_REPORT_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_HOLD_REPORT_NON_FINITE",
        )
    except OSError:
        raise DataTorrentRuntimeError("DATA_TORRENT_HOLD_REPORT_MISSING") from None
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_HOLD_REPORT_INVALID") from None
    if not isinstance(document, dict):
        raise DataTorrentRuntimeError("DATA_TORRENT_HOLD_REPORT_INVALID")
    hold = cast(dict[str, Any], document)
    ci = hold.get("post_merge_ci")
    if not isinstance(ci, dict):
        raise DataTorrentRuntimeError("DATA_TORRENT_POST_MERGE_CI_PROOF_MISSING")
    proof = cast(dict[str, Any], ci)
    legacy_ci = hold.get("legacy_ci_workflow_quarantine")
    environment_policy = hold.get("production_environment_policy")
    if (
        hold.get("schema_version") != "chronos-production-workflow-hold-live-v3"
        or hold.get("verdict") != "WORKFLOW_HOLD_ESTABLISHED"
        or hold.get("current_run_excluded") != identity.github.github_run_id
        or hold.get("queued_after") != 0
        or hold.get("in_progress_after") != 0
        or hold.get("unauthorized_active_workflows") != []
        or hold.get("provider_calls") != 0
        or hold.get("r2_operations") != 0
        or hold.get("legacy_secret_branch_sha") != identity.github.github_sha
        or not isinstance(legacy_ci, dict)
        or legacy_ci.get("workflow_id") != LEGACY_CI_WORKFLOW_ID
        or legacy_ci.get("workflow_path") != ".github/workflows/ci.yml"
        or legacy_ci.get("state") != "disabled_manually"
        or environment_policy
        != {
            "environment": "chronos-control-plane-production",
            "can_admins_bypass": False,
            "protected_branches": False,
            "custom_branch_policies": True,
            "allowed_branches": ["main"],
        }
        or proof.get("workflow_path") != CI_WORKFLOW_PATH
        or type(proof.get("run_id")) is not int
        or int(proof["run_id"]) <= 0
        or type(proof.get("run_attempt")) is not int
        or proof.get("run_attempt") != 1
        or proof.get("head_sha") != identity.github.github_sha
        or proof.get("head_branch") != "main"
        or proof.get("event") != "push"
        or proof.get("status") != "completed"
        or proof.get("conclusion") != "success"
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_POST_MERGE_CI_PROOF_INVALID")
    try:
        ci_workflow = (repository_root / CI_WORKFLOW_PATH).read_bytes()
    except OSError:
        raise DataTorrentRuntimeError("DATA_TORRENT_CROSS_RUN_CI_CONTRACT_MISSING") from None
    if b"tests/data_torrent/test_postgresql_v1.py" not in ci_workflow:
        raise DataTorrentRuntimeError("DATA_TORRENT_CROSS_RUN_CI_CONTRACT_MISSING")
    return {
        "receipt_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "workflow_path": CI_WORKFLOW_PATH,
        "workflow_file_sha256": hashlib.sha256(ci_workflow).hexdigest(),
        "run_id": int(proof["run_id"]),
        "run_attempt": int(proof["run_attempt"]),
        "head_sha": str(proof["head_sha"]),
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "cross_run_test_contract": CROSS_RUN_CONTRACT,
    }


def _validated_chronos_verify_artifact(
    *,
    repository_root: Path,
    environment: Mapping[str, str],
    identity: RuntimeIdentity,
    generation_token: str,
    expected_generation_hash: str,
) -> dict[str, Any]:
    if _context(environment, "DATA_TORRENT_VERIFY_ARTIFACT") != VERIFY_ARTIFACT_PATH:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_PATH_MISMATCH")
    expected_run_id = _context(environment, "DATA_TORRENT_EXPECTED_VERIFY_RUN_ID")
    if (
        not expected_run_id.isascii()
        or not expected_run_id.isdigit()
        or expected_run_id == "0"
        or str(int(expected_run_id)) != expected_run_id
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_RUN_ID_INVALID")
    path = repository_root / VERIFY_ARTIFACT_PATH
    try:
        artifact_bytes = path.read_bytes()
        raw = strict_json_loads(
            artifact_bytes,
            duplicate_code="DATA_TORRENT_VERIFY_ARTIFACT_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_VERIFY_ARTIFACT_NON_FINITE",
        )
    except OSError:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_MISSING") from None
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_INVALID") from None
    if not isinstance(raw, dict):
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_INVALID")
    signed = cast(dict[str, Any], raw)
    signature = signed.get("signature")
    try:
        artifact = verify_signed_document(signed, generation_token)
    except ChronosProductionError:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_SIGNATURE_INVALID") from None
    migration_run_id = artifact.get("migration_run_id")
    preflight_run_id = artifact.get("preflight_run_id")
    try:
        preflight_artifact_hash = require_hash(
            str(artifact.get("preflight_hash", "")),
            field="preflight_hash",
        )
    except ChronosProductionError:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_PREFLIGHT_HASH_INVALID") from None
    identities = artifact.get("identities")
    if (
        artifact.get("schema_version") != "chronos-production-verify-v3"
        or artifact.get("verdict") != "CHRONOS_SCOPED_IDENTITIES_READY"
        or artifact.get("revision") != EXPECTED_REVISION
        or artifact.get("main_sha") != identity.github.github_sha
        or artifact.get("workflow_sha") != identity.github.github_sha
        or artifact.get("post_merge_ci_sha") != identity.post_merge_ci_sha
        or artifact.get("generation_hash") != expected_generation_hash
        or artifact.get("verify_run_id") != expected_run_id
        or artifact.get("verify_run_attempt") != "1"
        or artifact.get("migration_run_attempt") != "1"
        or not isinstance(migration_run_id, str)
        or not migration_run_id.isascii()
        or not migration_run_id.isdigit()
        or migration_run_id == "0"
        or not isinstance(preflight_run_id, str)
        or not preflight_run_id.isascii()
        or not preflight_run_id.isdigit()
        or preflight_run_id == "0"
        or artifact.get("business_data_modified") is not False
        or artifact.get("forbidden_membership") != 0
        or artifact.get("migrator_runtime_membership") != 0
        or artifact.get("runtime_effective_bootstrap_edge") != 0
        or artifact.get("provider_calls") != 0
        or artifact.get("r2_operations") != 0
        or not isinstance(identities, dict)
        or set(identities) != {"authority", "runtime", "reader"}
        or not isinstance(signature, dict)
        or signature.get("algorithm") != "HMAC-SHA256"
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_ARTIFACT_MISMATCH")
    try:
        controlled_go = validate_controlled_go_binding(
            artifact.get("controlled_go"),
            main_sha=identity.github.github_sha,
        )
    except ChronosProductionError:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_CONTROLLED_GO_INVALID") from None
    expected_accounts = {
        role: (login, group)
        for role, (login, group, _secret_name) in zip(
            ("authority", "runtime", "reader"), SCOPED_LOGINS, strict=True
        )
    }
    target_values: set[tuple[str, int, str, str, str]] = set()
    server_epochs: set[str] = set()
    for role, (login, group) in expected_accounts.items():
        entry = cast(dict[str, Any], identities[role])
        if (
            not isinstance(entry, dict)
            or set(entry)
            != {
                "database_host",
                "database_port",
                "database_name",
                "sslmode",
                "channel_binding",
                "current_user",
                "revision",
                "server_epoch",
                "memberships",
            }
            or not isinstance(entry.get("database_host"), str)
            or type(entry.get("database_port")) is not int
            or not isinstance(entry.get("database_name"), str)
            or entry.get("sslmode") not in {"require", "verify-ca", "verify-full"}
            or entry.get("channel_binding") != "require"
            or entry.get("current_user") != login
            or entry.get("revision") != EXPECTED_REVISION
            or entry.get("memberships") != [{"granted_role": group}]
            or not isinstance(entry.get("server_epoch"), str)
            or not entry["server_epoch"]
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_IDENTITIES_MISMATCH")
        target_values.add(
            (
                str(entry["database_host"]),
                int(entry["database_port"]),
                str(entry["database_name"]),
                str(entry["sslmode"]),
                str(entry["channel_binding"]),
            )
        )
        server_epochs.add(str(entry["server_epoch"]))
    if len(target_values) != 1 or len(server_epochs) != 1:
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_IDENTITIES_MISMATCH")
    database_target = next(iter(target_values))
    return {
        "receipt_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "schema_version": str(artifact["schema_version"]),
        "verdict": str(artifact["verdict"]),
        "revision": str(artifact["revision"]),
        "main_sha": str(artifact["main_sha"]),
        "post_merge_ci_sha": str(artifact["post_merge_ci_sha"]),
        "generation_hash": str(artifact["generation_hash"]),
        "preflight_run_id": preflight_run_id,
        "preflight_hash": preflight_artifact_hash,
        "migration_run_id": migration_run_id,
        "verify_run_id": expected_run_id,
        "verify_run_attempt": 1,
        "signature_algorithm": "HMAC-SHA256",
        "controlled_go": controlled_go,
        "database_target": {
            "host": database_target[0],
            "port": database_target[1],
            "database": database_target[2],
            "sslmode": database_target[3],
            "channel_binding": database_target[4],
            "server_epoch": next(iter(server_epochs)),
        },
    }


def _mission_r2_counters(
    *,
    proof: Mapping[str, Any],
    live_counters: Mapping[str, int],
    live_objects: int,
) -> dict[str, int]:
    binding = cast(dict[str, Any], proof["controlled_go"])
    return {
        "puts": int(binding["seal_r2_puts"]) + int(live_counters["puts"]),
        "gets": (
            int(binding["seal_r2_gets"])
            + int(binding["preflight_r2_gets"])
            + int(live_counters["gets"])
        ),
        "lists": int(live_counters["lists"]),
        "deletes": int(live_counters["deletes"]),
        "objects": int(binding["seal_r2_objects_created"]) + live_objects,
        "overwrites": 0,
    }


def _assert_chronos_verify_database_targets(
    *,
    proof: Mapping[str, Any],
    targets: list[DirectPostgresTarget],
) -> None:
    signed_target = proof.get("database_target")
    if not isinstance(signed_target, dict):
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_DATABASE_TARGET_MISSING")
    expected = (
        signed_target.get("host"),
        signed_target.get("port"),
        signed_target.get("database"),
        signed_target.get("sslmode"),
        signed_target.get("channel_binding"),
    )
    if any(
        (
            target.host,
            target.port,
            target.database,
            target.sslmode,
            target.channel_binding,
        )
        != expected
        for target in targets
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_VERIFY_DATABASE_TARGET_MISMATCH")


def _assert_chronos_object_acl(connection: Any) -> None:
    relation_rows = connection.execute(
        sa.text(
            "SELECT c.relname,c.relkind FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND left(c.relname,8)='chronos_' "
            "AND c.relkind IN ('r','p','v','m','f','S') ORDER BY 1,2"
        )
    ).all()
    function_rows = connection.execute(
        sa.text(
            "SELECT p.proname,pg_catalog.oidvectortypes(p.proargtypes) "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
            "ON n.oid=p.pronamespace WHERE n.nspname='public' "
            "AND left(p.proname,8)='chronos_' ORDER BY 1,2"
        )
    ).all()
    acl_statement = sa.text(
        "SELECT object_kind,object_name,grantee,privilege_type,is_grantable FROM ("
        "SELECT 'relation' AS object_kind,'public.'||c.relname AS object_name,"
        "coalesce(r.rolname,'PUBLIC') AS grantee,a.privilege_type,a.is_grantable "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
        "ON n.oid=c.relnamespace CROSS JOIN LATERAL pg_catalog.aclexplode("
        "coalesce(c.relacl,CASE WHEN c.relkind='S' "
        "THEN pg_catalog.acldefault('S',c.relowner) "
        "ELSE pg_catalog.acldefault('r',c.relowner) END)) a "
        "LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
        "WHERE n.nspname='public' AND left(c.relname,8)='chronos_' "
        "AND c.relkind IN ('r','p','v','m','f','S') "
        "AND (a.grantee=0 OR r.rolname IN :group_roles) "
        "UNION ALL SELECT 'function','public.'||p.proname||'('||"
        "pg_catalog.oidvectortypes(p.proargtypes)||')',"
        "coalesce(r.rolname,'PUBLIC'),a.privilege_type,a.is_grantable "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
        "ON n.oid=p.pronamespace CROSS JOIN LATERAL pg_catalog.aclexplode("
        "coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a "
        "LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
        "WHERE n.nspname='public' AND left(p.proname,8)='chronos_' "
        "AND (a.grantee=0 OR r.rolname IN :group_roles) "
        "UNION ALL SELECT 'column','public.'||c.relname||'.'||att.attname,"
        "coalesce(r.rolname,'PUBLIC'),a.privilege_type,a.is_grantable "
        "FROM pg_catalog.pg_attribute att JOIN pg_catalog.pg_class c "
        "ON c.oid=att.attrelid JOIN pg_catalog.pg_namespace n "
        "ON n.oid=c.relnamespace CROSS JOIN LATERAL "
        "pg_catalog.aclexplode(att.attacl) a LEFT JOIN pg_catalog.pg_roles r "
        "ON r.oid=a.grantee WHERE n.nspname='public' "
        "AND left(c.relname,8)='chronos_' "
        "AND (a.grantee=0 OR r.rolname IN :group_roles)) observed "
        "ORDER BY 1,2,3,4,5"
    ).bindparams(sa.bindparam("group_roles", expanding=True))
    acl_rows = connection.execute(
        acl_statement,
        {"group_roles": GROUP_ROLES},
    ).all()
    observed_acl = {
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            bool(row[4]),
        )
        for row in acl_rows
    }
    if (
        {(str(row[0]), str(row[1])) for row in relation_rows}
        != _EXPECTED_CHRONOS_RELATION_INVENTORY
        or len(relation_rows) != len(_EXPECTED_CHRONOS_RELATION_INVENTORY)
        or {(str(row[0]), str(row[1])) for row in function_rows}
        != set(CHRONOS_FUNCTION_SIGNATURES.items())
        or len(function_rows) != len(CHRONOS_FUNCTION_SIGNATURES)
        or observed_acl != _EXPECTED_CHRONOS_OBJECT_ACL
        or len(acl_rows) != len(_EXPECTED_CHRONOS_OBJECT_ACL)
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_SCOPED_DATABASE_ACL_INVALID")


def _assert_scoped_database_identities(
    *,
    targets: list[Any],
    engines: list[Any],
    effects: LiveRuntimeEffects | None = None,
) -> None:
    for target, engine, (expected_login, expected_group, _secret_name) in zip(
        targets,
        engines,
        SCOPED_LOGINS,
        strict=True,
    ):
        if target.username != expected_login:
            raise DataTorrentRuntimeError("DATA_TORRENT_SCOPED_DATABASE_USER_MISMATCH")
        if effects is not None:
            effects.begin_read_transaction()
        with engine.connect() as connection:
            _assert_chronos_object_acl(connection)
            identity_row = connection.execute(
                sa.text(
                    "SELECT session_user,current_user,rolcanlogin,rolinherit,"
                    "rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
                    "rolbypassrls,rolconnlimit,rolconfig,rolvaliduntil IS NULL,"
                    "pg_catalog.shobj_description(oid,'pg_authid') "
                    "FROM pg_catalog.pg_roles WHERE rolname=current_user"
                )
            ).one_or_none()
            memberships = {
                (
                    str(row[0]),
                    str(row[1]),
                    bool(row[2]),
                    bool(row[3]),
                    bool(row[4]),
                    bool(row[5]),
                )
                for row in connection.execute(
                    sa.text(
                        "SELECT granted.rolname,grantor.rolname,grantor.rolsuper,"
                        "member_edge.admin_option,member_edge.inherit_option,"
                        "member_edge.set_option "
                        "FROM pg_catalog.pg_auth_members member_edge "
                        "JOIN pg_catalog.pg_roles granted ON granted.oid=member_edge.roleid "
                        "JOIN pg_catalog.pg_roles member ON member.oid=member_edge.member "
                        "JOIN pg_catalog.pg_roles grantor ON grantor.oid=member_edge.grantor "
                        "WHERE member.rolname=session_user"
                    )
                )
            }
            elevated = bool(
                connection.scalar(
                    sa.text(
                        "SELECT pg_catalog.pg_has_role(session_user,"
                        "'chronos_bootstrap_authority','USAGE') OR "
                        "pg_catalog.pg_has_role(session_user,"
                        "'chronos_bootstrap_authority','SET')"
                    )
                )
            )
            direct_acl_count = int(
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM ("
                        "SELECT 1 FROM pg_catalog.pg_class c CROSS JOIN LATERAL "
                        "pg_catalog.aclexplode(c.relacl) a JOIN pg_catalog.pg_roles r "
                        "ON r.oid=a.grantee WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
                        "pg_catalog.aclexplode(p.proacl) a JOIN pg_catalog.pg_roles r "
                        "ON r.oid=a.grantee WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n "
                        "CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) a "
                        "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
                        "WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_database d "
                        "CROSS JOIN LATERAL pg_catalog.aclexplode(d.datacl) a "
                        "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
                        "WHERE r.rolname=session_user) direct_acl"
                    )
                )
                or 0
            )
            smuggled_state = bool(
                connection.scalar(
                    sa.text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_catalog.pg_db_role_setting s "
                        "JOIN pg_catalog.pg_roles r ON r.oid=s.setrole "
                        "WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_database d "
                        "JOIN pg_catalog.pg_roles r ON r.oid=d.datdba "
                        "WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n "
                        "JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner "
                        "WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_roles r ON r.oid=c.relowner "
                        "WHERE r.rolname=session_user "
                        "UNION ALL SELECT 1 FROM pg_catalog.pg_proc p "
                        "JOIN pg_catalog.pg_roles r ON r.oid=p.proowner "
                        "WHERE r.rolname=session_user)"
                    )
                )
            )
        if (
            identity_row is None
            or str(identity_row[0]) != expected_login
            or str(identity_row[1]) != expected_login
            or not bool(identity_row[2])
            or bool(identity_row[3])
            or bool(identity_row[4])
            or bool(identity_row[5])
            or bool(identity_row[6])
            or bool(identity_row[7])
            or bool(identity_row[8])
            or int(identity_row[9]) != -1
            or identity_row[10] is not None
            or not bool(identity_row[11])
            or str(identity_row[12]) != ROLE_MARKER
            or memberships
            != {
                (
                    expected_group,
                    "chronos_bootstrap_authority",
                    False,
                    False,
                    True,
                    False,
                )
            }
            or elevated
            or direct_acl_count != 0
            or smuggled_state
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_SCOPED_DATABASE_IDENTITY_INVALID")


def _opportunity(mission_manifest: Mapping[str, Any]) -> DataTorrentOpportunity:
    canonical_key = canonical_json_bytes(
        {
            "mission_id": mission_manifest["mission_id"],
            "authorization_source_sha256": mission_manifest["source_hash"],
        }
    ).decode("utf-8")
    return DataTorrentOpportunity(
        opportunity_kind="DATA_TORRENT_MISSION_AUTHORIZATION",
        canonical_key=canonical_key,
    )


def _claim_json(
    *,
    opportunity: DataTorrentOpportunity,
    receipt: OpportunityClaimReceipt,
    identity: RuntimeIdentity,
    mission_manifest: Mapping[str, Any],
    config_sha256: str,
    first_external_permit_at: datetime | None,
) -> dict[str, Any]:
    return {
        "schema_version": "robin-data-torrent-opportunity-claim-receipt-v1",
        "run_identity": identity.to_json(),
        "opportunity_id": receipt.opportunity_id,
        "opportunity_kind": opportunity.opportunity_kind,
        "canonical_key": opportunity.canonical_key,
        "mission_manifest_sha256": mission_manifest["manifest_sha256"],
        "mission_source_sha256": mission_manifest["source_hash"],
        "torrent_config_sha256": config_sha256,
        "acquired_now": receipt.acquired_now,
        "winner_authority_id": receipt.winner_authority_id,
        "winner_github_run_id": receipt.winner_github_run_id,
        "winner_github_run_attempt": receipt.winner_github_run_attempt,
        "db_claimed_at_utc": utc_text(receipt.db_claimed_at),
        "postgres_server_epoch_utc": utc_text(receipt.postgres_server_epoch),
        "claim_receipt_hash": receipt.claim_receipt_hash,
        "first_external_permit_at_utc": (
            utc_text(first_external_permit_at) if first_external_permit_at is not None else None
        ),
        "claim_before_first_external_effect": (
            first_external_permit_at is None or receipt.db_claimed_at <= first_external_permit_at
        ),
    }


def _select_evidence(
    *,
    config: TorrentConfig,
    official: OfficialCapture,
    anchor: datetime,
    observed_at_utc: datetime | None = None,
) -> tuple[tuple[OfficialScheduleEvidence, ...], dict[str, Any]]:
    maximum_expires = anchor + timedelta(days=config.fallback_horizon_days)
    maximum = tuple(
        build_official_schedule_evidence(
            league.official_source,
            official.results[league.sport_key],
            horizon_not_before_utc=anchor,
            horizon_expires_at_utc=maximum_expires,
        )
        for league in config.leagues
    )
    primary_expires = anchor + timedelta(days=config.primary_horizon_days)
    primary_count = sum(
        1
        for evidence in maximum
        for fixture in evidence.fixtures
        if fixture.kickoff_utc < primary_expires
    )
    fallback = primary_count < config.fallback_if_fixtures_below
    selected_expires = maximum_expires if fallback else primary_expires
    selected = tuple(
        replace(
            evidence,
            horizon_expires_at_utc=selected_expires,
            fixtures=tuple(
                item for item in evidence.fixtures if anchor <= item.kickoff_utc < selected_expires
            ),
        )
        for evidence in maximum
    )
    reconciliation = reconcile_official_schedule_evidence(
        selected,
        observed_at_utc=(datetime.now(UTC) if observed_at_utc is None else observed_at_utc),
    )
    return selected, {
        "anchor_utc": utc_text(anchor),
        "not_before_utc": utc_text(anchor),
        "expires_at_utc": utc_text(selected_expires),
        "primary_days": config.primary_horizon_days,
        "fallback_days": config.fallback_horizon_days,
        "fallback_threshold": config.fallback_if_fixtures_below,
        "primary_fixture_count": primary_count,
        "selected_days": (
            config.fallback_horizon_days if fallback else config.primary_horizon_days
        ),
        "fallback_triggered": fallback,
        "selected_fixture_count": sum(len(item.fixtures) for item in selected),
        "no_backfill": True,
        "reconciliation": reconciliation,
    }


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _assert_meaningful_breadth(
    *,
    config: TorrentConfig,
    evidences: tuple[OfficialScheduleEvidence, ...],
    batch: NormalizedBatch,
) -> None:
    expected_cells = tuple(
        (league.sport_key, market) for league in config.leagues for market in config.markets
    )
    observed_cells = tuple((str(item["sport_key"]), str(item["market"])) for item in batch.coverage)
    odds_records = tuple(item for item in batch.records if item["record_type"] == "ODDS_OUTCOME")
    if (
        observed_cells != expected_cells
        or any(not evidence.fixtures for evidence in evidences)
        or any(int(item["fixtures_available"]) <= 0 for item in batch.coverage)
        or any(int(item["fixtures_captured"]) <= 0 for item in batch.coverage)
        or any(
            int(item["fixtures_captured"]) != int(item["fixtures_available"])
            for item in batch.coverage
        )
        or any(
            float(item["coverage_percentage"]) < MINIMUM_FIXTURE_COVERAGE_PERCENTAGE
            for item in batch.coverage
        )
        or any(int(item["markets_requested"]) != 1 for item in batch.coverage)
        or any(int(item["markets_returned"]) != 1 for item in batch.coverage)
        or any(int(item["records_normalized"]) <= 0 for item in batch.coverage)
        or any(str(item["absence_reason"]) != "NONE" for item in batch.coverage)
        or any(
            not any(item["sport_key"] == league.sport_key for item in odds_records)
            for league in config.leagues
        )
        or any(
            not any(item["market_key"] == market for item in odds_records)
            for market in config.markets
        )
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_MEANINGFUL_BREADTH_FAILED")


def _effect_counter_snapshot(
    *,
    sources: SourceEffectCounters,
    r2_store: CountingR2Store,
) -> dict[str, int]:
    return {
        **sources.snapshot(),
        "r2_puts": r2_store.puts,
        "r2_gets": r2_store.gets,
        "r2_lists": r2_store.lists,
        "r2_deletes": r2_store.deletes,
    }


def _replay_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_TIME_INVALID") from None
    if parsed.tzinfo is None or utc_text(parsed) != value:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_TIME_INVALID")
    return parsed.astimezone(UTC)


def _replay_redirects(value: object) -> tuple[RedirectHop, ...]:
    if not isinstance(value, list):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
    redirects: list[RedirectHop] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "requested_url",
            "status_code",
            "location",
        }:
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
        if (
            type(raw["requested_url"]) is not str
            or type(raw["status_code"]) is not int
            or type(raw["location"]) is not str
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
        try:
            redirects.append(
                RedirectHop(
                    requested_url=raw["requested_url"],
                    status_code=raw["status_code"],
                    location=raw["location"],
                )
            )
        except (KeyError, TypeError, ValueError):
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID") from None
    return tuple(redirects)


def _read_replay_archive(raw_archive: bytes) -> dict[str, bytes]:
    if not raw_archive or len(raw_archive) > 1_073_741_824:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
    members: dict[str, bytes] = {}
    total_uncompressed = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_archive), mode="r:gz") as archive:
            entries = archive.getmembers()
            if not entries or len(entries) > 256:
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
            for entry in entries:
                if (
                    not entry.isfile()
                    or entry.name in members
                    or entry.mtime != 0
                    or entry.mode != 0o444
                    or entry.uid != 0
                    or entry.gid != 0
                    or entry.uname != ""
                    or entry.gname != ""
                    or entry.size < 0
                ):
                    raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
                total_uncompressed += entry.size
                if total_uncompressed > 1_073_741_824:
                    raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
                handle = archive.extractfile(entry)
                if handle is None:
                    raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
                payload = handle.read(entry.size + 1)
                if len(payload) != entry.size:
                    raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID")
                members[entry.name] = payload
    except (OSError, EOFError, tarfile.TarError):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID") from None
    try:
        if deterministic_tar_gz(members) != raw_archive:
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_NONCANONICAL")
    except (TypeError, ValueError):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_INVALID") from None
    return members


def _decode_replay_archive(
    *,
    config: TorrentConfig,
    raw_archive: bytes,
    expected_archive_sha256: str,
    expected_run_identity: str,
    expected_claim_identity: str,
) -> tuple[OfficialCapture, tuple[RawResponseEnvelope, ...], int]:
    """Reconstruct replay inputs exclusively from the confirmed raw archive bytes."""

    expected_sha = require_hash(expected_archive_sha256, field="raw_archive_sha256")
    if hashlib.sha256(raw_archive).hexdigest() != expected_sha:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_HASH_MISMATCH")
    members = _read_replay_archive(raw_archive)
    required_metadata = {
        "indexes/raw-index-core-v1.json",
        "receipts/official-v1.json",
        "receipts/provider-credit-v1.json",
    }
    if not required_metadata <= set(members):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_MEMBER_MISSING")
    try:
        raw_index_value = strict_json_loads(
            members["indexes/raw-index-core-v1.json"],
            duplicate_code="DATA_TORRENT_REPLAY_INDEX_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_REPLAY_INDEX_NON_FINITE",
        )
        official_value = strict_json_loads(
            members["receipts/official-v1.json"],
            duplicate_code="DATA_TORRENT_REPLAY_RECEIPT_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_REPLAY_RECEIPT_NON_FINITE",
        )
        strict_json_loads(
            members["receipts/provider-credit-v1.json"],
            duplicate_code="DATA_TORRENT_REPLAY_PROVIDER_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_REPLAY_PROVIDER_NON_FINITE",
        )
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_ARCHIVE_JSON_INVALID") from None
    index_fields = {
        "schema_version",
        "mission_id",
        "generated_at_utc",
        "run_identity",
        "claim_identity",
        "responses",
        "totals",
    }
    if (
        not isinstance(raw_index_value, dict)
        or set(raw_index_value) != index_fields
        or raw_index_value.get("schema_version") != "robin-data-torrent-real-batch-raw-index-v1"
        or raw_index_value.get("mission_id") != MISSION_ID
        or raw_index_value.get("claim_identity") != expected_claim_identity
        or type(raw_index_value.get("generated_at_utc")) is not str
        or type(raw_index_value.get("run_identity")) is not dict
        or not isinstance(raw_index_value.get("responses"), list)
        or not isinstance(raw_index_value.get("totals"), dict)
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_INVALID")
    _replay_timestamp(raw_index_value["generated_at_utc"])
    raw_entries = cast(list[Any], raw_index_value["responses"])
    entry_fields = {
        "response_id",
        "family",
        "sport_key",
        "source",
        "request_contract",
        "retrieved_at_utc",
        "http_status",
        "content_type",
        "response_headers",
        "raw_bytes",
        "raw_sha256",
        "response_sequence",
        "run_identity",
        "claim_identity",
        "effect_accounting",
        "archive_path",
        "disposition",
        "rejection_reason",
    }
    accounting_fields = {
        "effect_id",
        "permit_hash",
        "dispatch_event_hash",
        "confirmation_event_hash",
        "sequence",
        "attempt",
        "physical_reads",
        "provider_requests",
        "provider_credits",
        "automatic_retries",
    }
    envelopes: list[RawResponseEnvelope] = []
    archive_paths: set[str] = set()
    try:
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict) or set(raw_entry) != entry_fields:
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_INVALID")
            entry = cast(dict[str, Any], raw_entry)
            accounting = entry["effect_accounting"]
            archive_path = entry["archive_path"]
            string_fields = {
                "response_id",
                "family",
                "sport_key",
                "source",
                "retrieved_at_utc",
                "content_type",
                "raw_sha256",
                "run_identity",
                "claim_identity",
                "archive_path",
                "disposition",
            }
            accounting_string_fields = {
                "effect_id",
                "permit_hash",
                "dispatch_event_hash",
                "confirmation_event_hash",
            }
            accounting_int_fields = {
                "sequence",
                "attempt",
                "physical_reads",
                "provider_requests",
                "provider_credits",
                "automatic_retries",
            }
            if (
                not isinstance(accounting, dict)
                or set(accounting) != accounting_fields
                or any(type(entry.get(name)) is not str for name in string_fields)
                or type(entry.get("http_status")) is not int
                or type(entry.get("raw_bytes")) is not int
                or type(entry.get("response_sequence")) is not int
                or type(entry.get("request_contract")) is not dict
                or type(entry.get("response_headers")) is not dict
                or any(
                    type(name) is not str or type(value) is not str
                    for name, value in cast(dict[Any, Any], entry["response_headers"]).items()
                )
                or (
                    entry.get("rejection_reason") is not None
                    and type(entry.get("rejection_reason")) is not str
                )
                or any(type(accounting.get(name)) is not str for name in accounting_string_fields)
                or any(type(accounting.get(name)) is not int for name in accounting_int_fields)
                or accounting.get("attempt") != 1
                or accounting.get("automatic_retries") != 0
                or archive_path in archive_paths
                or archive_path not in members
                or not archive_path.startswith("responses/")
            ):
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_INVALID")
            archive_paths.add(archive_path)
            body = members[archive_path]
            envelope = RawResponseEnvelope(
                response_id=entry["response_id"],
                family=cast(Any, entry["family"]),
                sport_key=entry["sport_key"],
                source=entry["source"],
                request_contract=cast(dict[str, Any], entry["request_contract"]),
                retrieved_at_utc=_replay_timestamp(entry["retrieved_at_utc"]),
                http_status=entry["http_status"],
                content_type=entry["content_type"],
                response_headers=cast(dict[str, str], entry["response_headers"]),
                body=body,
                run_identity=entry["run_identity"],
                claim_identity=entry["claim_identity"],
                response_sequence=entry["response_sequence"],
                external_effect_sequence=accounting["sequence"],
                external_operation_id=accounting["effect_id"],
                permit_hash=accounting["permit_hash"],
                dispatch_event_hash=accounting["dispatch_event_hash"],
                confirmation_event_hash=accounting["confirmation_event_hash"],
                physical_reads=accounting["physical_reads"],
                provider_requests=accounting["provider_requests"],
                provider_credits=accounting["provider_credits"],
                disposition=entry["disposition"],
                rejection_reason=cast(str | None, entry["rejection_reason"]),
            )
            if (
                entry["raw_bytes"] != len(body)
                or entry["raw_sha256"] != envelope.sha256
                or envelope.response_id
                != hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "family": envelope.family,
                            "sport_key": envelope.sport_key,
                            "sequence": envelope.response_sequence,
                            "raw_sha256": envelope.sha256,
                        }
                    )
                ).hexdigest()
                or archive_path
                != (f"responses/{envelope.response_sequence:03d}-{envelope.response_id}.bin")
                or envelope.run_identity != expected_run_identity
                or envelope.claim_identity != expected_claim_identity
            ):
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_BINDING_INVALID")
            envelopes.append(envelope)
    except (KeyError, TypeError, ValueError):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_INVALID") from None
    envelopes.sort(key=lambda item: item.response_sequence)
    if (
        not envelopes
        or [item.response_sequence for item in envelopes] != list(range(1, len(envelopes) + 1))
        or len({item.response_id for item in envelopes}) != len(envelopes)
        or set(members) != required_metadata | archive_paths
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_INDEX_INVALID")
    totals = cast(dict[str, Any], raw_index_value["totals"])
    raw_payload_bytes = sum(len(item.body) for item in envelopes)
    expected_totals = {
        "raw_responses": len(envelopes),
        "raw_bytes": raw_payload_bytes,
        "official_physical_reads": sum(
            item.physical_reads for item in envelopes if item.family != "ODDS"
        ),
        "odds_provider_requests": sum(item.provider_requests for item in envelopes),
        "odds_credits_used": sum(item.provider_credits for item in envelopes),
        "odds_dns_resolutions": len(config.leagues),
        "accounting_status": "PENDING_NORMALIZATION",
    }
    if canonical_json_bytes(totals) != canonical_json_bytes(expected_totals):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_TOTALS_INVALID")

    if (
        not isinstance(official_value, dict)
        or set(official_value) != {"reads"}
        or not isinstance(official_value.get("reads"), list)
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
    receipt_fields = {
        "schema_version",
        "sport_key",
        "adapter_revision",
        "requested_url",
        "final_url",
        "official_domain",
        "observed_at_utc",
        "http_status",
        "content_type",
        "byte_count",
        "raw_sha256",
        "redirect_chain",
        "accepted",
        "rejection_code",
        "supporting_official_reads",
    }
    supporting_fields = {
        "requested_url",
        "final_url",
        "official_domain",
        "status_code",
        "content_type",
        "byte_count",
        "raw_sha256",
        "redirect_chain",
    }
    results: dict[str, OfficialFetchResult] = {}
    receipt_documents: list[dict[str, Any]] = []
    expected_sport_order = [item.sport_key for item in config.leagues]
    for receipt_index, raw_receipt in enumerate(cast(list[Any], official_value["reads"])):
        if not isinstance(raw_receipt, dict) or set(raw_receipt) != receipt_fields:
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
        receipt_document = cast(dict[str, Any], raw_receipt)
        sport_key = receipt_document.get("sport_key")
        supporting_value = receipt_document.get("supporting_official_reads")
        receipt_string_fields = {
            "schema_version",
            "sport_key",
            "adapter_revision",
            "requested_url",
            "final_url",
            "official_domain",
            "observed_at_utc",
            "content_type",
            "raw_sha256",
        }
        if (
            receipt_document.get("schema_version") != "robin-official-schedule-fetch-receipt-v1"
            or receipt_index >= len(expected_sport_order)
            or sport_key != expected_sport_order[receipt_index]
            or sport_key in results
            or not isinstance(sport_key, str)
            or not isinstance(supporting_value, list)
            or any(type(receipt_document.get(name)) is not str for name in receipt_string_fields)
            or type(receipt_document.get("http_status")) is not int
            or type(receipt_document.get("byte_count")) is not int
            or type(receipt_document.get("accepted")) is not bool
            or receipt_document.get("rejection_code") is not None
            or type(receipt_document.get("redirect_chain")) is not list
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
        main_matches = [
            item
            for item in envelopes
            if item.family == "OFFICIAL"
            and item.sport_key == sport_key
            and item.sha256 == receipt_document.get("raw_sha256")
            and item.http_status == receipt_document.get("http_status")
            and item.content_type == receipt_document.get("content_type")
            and len(item.body) == receipt_document.get("byte_count")
            and item.source == receipt_document.get("final_url")
        ]
        if len(main_matches) != 1:
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_BODY_MISMATCH")
        supporting_receipts: list[SupportingOfficialRead] = []
        supporting_bodies: list[bytes] = []
        used_supporting: set[str] = set()
        for raw_supporting in supporting_value:
            if not isinstance(raw_supporting, dict) or set(raw_supporting) != supporting_fields:
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
            supporting = cast(dict[str, Any], raw_supporting)
            if (
                any(
                    type(supporting.get(name)) is not str
                    for name in {
                        "requested_url",
                        "final_url",
                        "official_domain",
                        "content_type",
                        "raw_sha256",
                    }
                )
                or type(supporting.get("status_code")) is not int
                or type(supporting.get("byte_count")) is not int
                or type(supporting.get("redirect_chain")) is not list
            ):
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
            matches = [
                item
                for item in envelopes
                if item.response_id not in used_supporting
                and item.family == "OFFICIAL_SUPPORTING"
                and item.sport_key == sport_key
                and item.sha256 == supporting.get("raw_sha256")
                and item.http_status == supporting.get("status_code")
                and item.content_type == supporting.get("content_type")
                and len(item.body) == supporting.get("byte_count")
                and item.source == supporting.get("final_url")
            ]
            if len(matches) != 1:
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_BODY_MISMATCH")
            matched = matches[0]
            used_supporting.add(matched.response_id)
            try:
                supporting_receipts.append(
                    SupportingOfficialRead(
                        requested_url=supporting["requested_url"],
                        final_url=supporting["final_url"],
                        official_domain=supporting["official_domain"],
                        status_code=supporting["status_code"],
                        content_type=supporting["content_type"],
                        byte_count=supporting["byte_count"],
                        raw_sha256=supporting["raw_sha256"],
                        redirect_chain=_replay_redirects(supporting["redirect_chain"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                raise DataTorrentRuntimeError(
                    "DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID"
                ) from None
            supporting_bodies.append(matched.body)
        try:
            if (
                receipt_document["accepted"] is not True
                or receipt_document["rejection_code"] is not None
                or type(receipt_document["http_status"]) is not int
                or type(receipt_document["byte_count"]) is not int
            ):
                raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
            receipt = OfficialFetchReceipt(
                sport_key=sport_key,
                adapter_revision=receipt_document["adapter_revision"],
                requested_url=receipt_document["requested_url"],
                final_url=receipt_document["final_url"],
                official_domain=receipt_document["official_domain"],
                observed_at_utc=_replay_timestamp(receipt_document["observed_at_utc"]),
                http_status=receipt_document["http_status"],
                content_type=receipt_document["content_type"],
                byte_count=receipt_document["byte_count"],
                raw_sha256=receipt_document["raw_sha256"],
                redirect_chain=_replay_redirects(receipt_document["redirect_chain"]),
                accepted=receipt_document["accepted"],
                rejection_code=cast(str | None, receipt_document["rejection_code"]),
                supporting_official_reads=tuple(supporting_receipts),
            )
        except (KeyError, TypeError, ValueError):
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID") from None
        main = main_matches[0]
        if (
            receipt.accepted is not True
            or receipt.rejection_code is not None
            or receipt.byte_count != len(main.body)
            or any(
                item.byte_count != len(body)
                for item, body in zip(
                    receipt.supporting_official_reads,
                    supporting_bodies,
                    strict=True,
                )
            )
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_RECEIPT_INVALID")
        results[sport_key] = OfficialFetchResult(
            raw_bytes=main.body,
            receipt=receipt,
            supporting_official_raw_bytes=tuple(supporting_bodies),
        )
        receipt_documents.append(receipt_document)
    expected_sports = {item.sport_key for item in config.leagues}
    if set(results) != expected_sports:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_OFFICIAL_COVERAGE_INVALID")
    return (
        OfficialCapture(
            results=results,
            raw_responses=tuple(envelopes),
            receipts=tuple(receipt_documents),
            effects=(),
            physical_reads=sum(item.physical_reads for item in envelopes if item.family != "ODDS"),
            errors=(),
        ),
        tuple(envelopes),
        raw_payload_bytes,
    )


def _replay_archive_once(
    *,
    config: TorrentConfig,
    raw_archive: bytes,
    raw_archive_sha256: str,
    league_names: dict[str, str],
    team_aliases: Mapping[str, str],
    run_identity: str,
    claim_identity: str,
    anchor: datetime,
    reconciliation_observed_at: datetime,
) -> tuple[NormalizedBatch, int]:
    official, raw_responses, raw_bytes = _decode_replay_archive(
        config=config,
        raw_archive=raw_archive,
        expected_archive_sha256=raw_archive_sha256,
        expected_run_identity=run_identity,
        expected_claim_identity=claim_identity,
    )
    evidences, _horizon = _select_evidence(
        config=config,
        official=official,
        anchor=anchor,
        observed_at_utc=reconciliation_observed_at,
    )
    return (
        normalize_batch(
            evidences=evidences,
            raw_responses=raw_responses,
            league_names=league_names,
            requested_markets=config.markets,
            run_identity=run_identity,
            claim_identity=claim_identity,
            team_aliases=team_aliases,
        ),
        raw_bytes,
    )


def _measure_replay(
    *,
    config: TorrentConfig,
    raw_archive: bytes,
    raw_archive_sha256: str,
    league_names: dict[str, str],
    team_aliases: Mapping[str, str],
    run_identity: str,
    claim_identity: str,
    anchor: datetime,
    reconciliation_observed_at: datetime,
    original: NormalizedBatch,
    capture_started: datetime,
    capture_ended: datetime,
    counter_snapshot: Callable[[], dict[str, int]],
) -> ReplayMeasurement:
    if (
        capture_started.tzinfo is None
        or capture_started.utcoffset() is None
        or capture_ended.tzinfo is None
        or capture_ended.utcoffset() is None
        or capture_ended <= capture_started
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_CAPTURE_WINDOW_INVALID")
    latencies: list[float] = []
    hashes: set[str] = set()
    final_batch = original
    external_before = counter_snapshot()
    raw_bytes_per_iteration: int | None = None
    total_bytes = 0
    tracemalloc.start()
    baseline_memory, _ = tracemalloc.get_traced_memory()
    started = time.perf_counter()
    for _iteration in range(config.replay_multiplier):
        iteration_started = time.perf_counter()
        final_batch, iteration_raw_bytes = _replay_archive_once(
            config=config,
            raw_archive=raw_archive,
            raw_archive_sha256=raw_archive_sha256,
            league_names=league_names,
            team_aliases=team_aliases,
            run_identity=run_identity,
            claim_identity=claim_identity,
            anchor=anchor,
            reconciliation_observed_at=reconciliation_observed_at,
        )
        if raw_bytes_per_iteration is None:
            raw_bytes_per_iteration = iteration_raw_bytes
        elif raw_bytes_per_iteration != iteration_raw_bytes:
            raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_RAW_BYTES_UNSTABLE")
        total_bytes += iteration_raw_bytes
        hashes.add(final_batch.canonical_dataset_sha256)
        latencies.append((time.perf_counter() - iteration_started) * 1000.0)
    elapsed = time.perf_counter() - started
    _current_memory, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    try:
        resource_module: Any = importlib.import_module("resource")
        baseline_rss = int(resource_module.getrusage(resource_module.RUSAGE_SELF).ru_maxrss) * 1024
    except ImportError:  # pragma: no cover - Ubuntu is enforced in production.
        baseline_rss = 0
    peak_memory = max(baseline_rss, traced_peak)
    records_per_iteration = len(original.records)
    equivalent_records = records_per_iteration * config.replay_multiplier
    total_records = equivalent_records
    if raw_bytes_per_iteration is None or raw_bytes_per_iteration <= 0:
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_RAW_BYTES_INVALID")
    replay_rps = total_records / elapsed
    replay_bps = total_bytes / elapsed
    capture_seconds = (capture_ended - capture_started).total_seconds()
    required_rps = records_per_iteration / capture_seconds
    required_bps = raw_bytes_per_iteration / capture_seconds
    records_ratio = replay_rps / required_rps
    bytes_ratio = replay_bps / required_bps
    minimum_ratio = min(records_ratio, bytes_ratio)
    equality = hashes == {original.canonical_dataset_sha256}
    external_after = counter_snapshot()
    if set(external_before) != set(external_after):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_COUNTER_SHAPE_INVALID")
    external_delta = {
        name: external_after[name] - external_before[name] for name in sorted(external_before)
    }
    if any(value < 0 for value in external_delta.values()):
        raise DataTorrentRuntimeError("DATA_TORRENT_REPLAY_COUNTER_REGRESSION")
    acceptance = {
        "raw_archive_binding_pass": True,  # nosec B105 - acceptance boolean.
        "volume_pass": (config.replay_multiplier >= 100 or equivalent_records >= 100_000),
        "throughput_pass": minimum_ratio >= config.minimum_throughput_ratio,
        "canonical_equality_pass": equality,
        "idempotence_pass": equality,
        "no_external_effect_pass": all(value == 0 for value in external_delta.values()),
    }
    report = {
        "schema_version": "robin-data-torrent-load-replay-report-v1",
        "mission_id": MISSION_ID,
        "generated_at_utc": utc_text(datetime.now(UTC)),
        "input": {
            "raw_archive_sha256": raw_archive_sha256,
            "replay_source": "CONFIRMED_IMMUTABLE_RAW_ARCHIVE_BYTES",
            "raw_archive_decode_count": config.replay_multiplier,
            "raw_payload_parse_iterations": config.replay_multiplier,
            "raw_bytes_per_iteration": raw_bytes_per_iteration,
            "canonical_dataset_sha256": original.canonical_dataset_sha256,
            "normalized_records_per_iteration": records_per_iteration,
            "rejected_records_per_iteration": len(original.rejects),
        },
        "normal_required_throughput": {
            "basis": "REAL_BATCH_CAPTURE_WINDOW",
            "window_started_at_utc": utc_text(capture_started),
            "window_ended_at_utc": utc_text(capture_ended),
            "elapsed_seconds": capture_seconds,
            "records_per_second": required_rps,
            "bytes_per_second": required_bps,
        },
        "replay": {
            "multiplier": config.replay_multiplier,
            "equivalent_normalized_records": equivalent_records,
            "iterations_completed": config.replay_multiplier,
            "total_records_processed": total_records,
            "total_bytes_processed": total_bytes,
        },
        "measurement": {
            "wall_clock_seconds": elapsed,
            "records_per_second": replay_rps,
            "bytes_per_second": replay_bps,
            "latency_sample_unit": "BATCH_REPLAY_ITERATION",
            "latency_sample_count": len(latencies),
            "p50_latency_ms": statistics.median(latencies),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "baseline_rss_bytes": baseline_rss,
            "peak_memory_bytes": peak_memory,
            "incremental_peak_memory_bytes": max(0, traced_peak - baseline_memory),
            "rejects": len(original.rejects) * config.replay_multiplier,
            "duplicates": final_batch.logical_duplicates,
            "silent_losses": final_batch.silent_drops,
            "unique_canonical_hashes": sorted(hashes),
        },
        "throughput": {
            "records_ratio": records_ratio,
            "bytes_ratio": bytes_ratio,
            "minimum_ratio": minimum_ratio,
            "required_minimum_ratio": config.minimum_throughput_ratio,
        },
        "external_effects_delta": external_delta,
        "acceptance": acceptance,
        "status": "PASS" if all(acceptance.values()) else "FAIL",
    }
    return ReplayMeasurement(report=report, final_batch=final_batch)


def _lineage(
    *,
    raw_responses: tuple[RawResponseEnvelope, ...],
    batch: NormalizedBatch,
) -> dict[str, Any]:
    record_counts = Counter(str(item["source_response_id"]) for item in batch.records)
    reject_counts = Counter(str(item["response_id"]) for item in batch.rejects)
    primary_by_operation = {
        item.external_operation_id: item.response_id
        for item in raw_responses
        if item.family == "OFFICIAL"
    }
    raw_rows: list[dict[str, Any]] = []
    accounted_responses = 0
    for response in sorted(raw_responses, key=lambda item: item.response_sequence):
        normalized_records = record_counts[response.response_id]
        rejected_units = reject_counts[response.response_id]
        supporting_primary = (
            primary_by_operation.get(response.external_operation_id)
            if response.family == "OFFICIAL_SUPPORTING"
            else None
        )
        if normalized_records and rejected_units:
            accounting_role = "NORMALIZED_WITH_EXPLICIT_REJECTS"
        elif normalized_records:
            accounting_role = "NORMALIZED_SOURCE"
        elif rejected_units:
            accounting_role = "EXPLICIT_REJECT_SOURCE"
        elif supporting_primary is not None:
            accounting_role = "SUPPORTING_PHYSICAL_EVIDENCE"
        elif response.family == "OFFICIAL":
            accounting_role = "PRIMARY_OFFICIAL_SELECTION_EVIDENCE"
        else:
            accounting_role = "UNACCOUNTED"
        accounted = accounting_role != "UNACCOUNTED"
        accounted_responses += int(accounted)
        raw_rows.append(
            {
                "response_id": response.response_id,
                "response_sequence": response.response_sequence,
                "family": response.family,
                "raw_sha256": response.sha256,
                "disposition": response.disposition,
                "rejection_reason": response.rejection_reason,
                "external_operation_id": response.external_operation_id,
                "external_effect_sequence": response.external_effect_sequence,
                "accounting_role": accounting_role,
                "normalized_records": normalized_records,
                "rejected_units": rejected_units,
                "linked_primary_response_id": supporting_primary,
                "accounted": accounted,
            }
        )
    return {
        "schema_version": "robin-data-torrent-raw-to-normalized-lineage-v1",
        "raw_responses": raw_rows,
        "records": [
            {
                "record_id": item["record_id"],
                "source_response_id": item["source_response_id"],
                "source_raw_sha256": item["source_raw_sha256"],
                "source_pointer": item["source_pointer"],
                "source_pointer_domain": item.get("source_pointer_domain"),
                "source_adapter_revision": item.get("source_adapter_revision"),
            }
            for item in batch.records
        ],
        "rejects": [
            {
                "reject_id": item["reject_id"],
                "source_response_id": item["response_id"],
                "source_raw_sha256": item["source_raw_sha256"],
                "source_pointer": item["source_pointer"],
                "reason": item["reason"],
            }
            for item in batch.rejects
        ],
        "summary": {
            "raw_responses_observed": len(raw_responses),
            "raw_responses_accounted": accounted_responses,
            "normalized_records": len(batch.records),
            "rejected_units": len(batch.rejects),
            "silent_responses": len(raw_responses) - accounted_responses,
        },
    }


def _safe_events(
    official: OfficialCapture,
    odds: OddsCapture,
    objects: tuple[DurableObjectReceipt, ...],
    *,
    normalized_evidence_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_effects = [item.to_json() for item in (*official.effects, *odds.effects)]
    return {
        "schema_version": "robin-data-torrent-control-plane-event-chain-v1",
        "events": {
            "external_sources": source_effects,
            "r2": [event for item in objects for event in item.events],
            "normalized_evidence_terminal_resolver": normalized_evidence_binding,
        },
        "summary": {
            "official_effects": len(official.effects),
            "odds_effects": len(odds.effects),
            "r2_operations": len(objects) + int(normalized_evidence_binding is not None),
            "all_external_sources_confirmed": all(
                item.terminal.event_type == "CONFIRMED"
                for item in (*official.effects, *odds.effects)
            ),
            "all_embedded_r2_terminal": all(
                item.terminal_event in {"CREATED_CONFIRMED", "PREEXISTING_CONFIRMED"}
                for item in objects
            ),
            "final_r2_terminal_requires_append_only_resolution": (
                normalized_evidence_binding is not None
            ),
        },
    }


def _assert_source_effect_lineage(
    *,
    raw_responses: tuple[RawResponseEnvelope, ...],
    effects: tuple[ExternalEffectTrace, ...],
) -> None:
    responses_by_operation: dict[str, list[RawResponseEnvelope]] = {}
    for response in raw_responses:
        responses_by_operation.setdefault(response.external_operation_id, []).append(response)
    if len(effects) != 10 or len({item.permit.operation_id for item in effects}) != 10:
        raise DataTorrentRuntimeError("DATA_TORRENT_EXTERNAL_EFFECT_LINEAGE_INVALID")
    for trace in effects:
        permit = trace.permit
        responses = sorted(
            responses_by_operation.get(permit.operation_id, []),
            key=lambda item: item.response_sequence,
        )
        request_hash = hashlib.sha256(canonical_json_bytes(trace.request_contract)).hexdigest()
        expected_families = (
            {"OFFICIAL", "OFFICIAL_SUPPORTING"} if trace.family == "OFFICIAL" else {"ODDS"}
        )
        contracts_match = all(
            canonical_json_bytes(response.request_contract)
            == canonical_json_bytes(
                trace.request_contract
                if trace.family == "ODDS"
                else {
                    **trace.request_contract,
                    "sanitized_endpoint": response.source,
                    "physical_response_index": physical_index,
                    "logical_request_endpoint": trace.request_contract["sanitized_endpoint"],
                }
            )
            for physical_index, response in enumerate(responses)
        )
        if (
            not responses
            or permit.effect_family != trace.family
            or permit.request_hash != request_hash
            or not contracts_match
            or trace.dispatched.event_type != "DISPATCHED"
            or trace.terminal.event_type != "CONFIRMED"
            or trace.dispatched.event_seq != 1
            or trace.terminal.event_seq != 2
            or trace.terminal.previous_event_hash != trace.dispatched.event_hash
            or any(
                response.family not in expected_families
                or response.sport_key != trace.sport_key
                or response.external_effect_sequence != permit.effect_sequence
                or response.permit_hash != permit.permit_hash
                or response.dispatch_event_hash != trace.dispatched.event_hash
                or response.confirmation_event_hash != trace.terminal.event_hash
                for response in responses
            )
            or sum(item.physical_reads for item in responses)
            != trace.terminal.actual_official_reads + trace.terminal.actual_odds_requests
            or sum(item.provider_requests for item in responses)
            != trace.terminal.actual_odds_requests
            or sum(item.provider_credits for item in responses)
            != trace.terminal.actual_odds_credits
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_EXTERNAL_EFFECT_LINEAGE_INVALID")


def _durabilize_partial_capture(
    *,
    raw_responses: tuple[RawResponseEnvelope, ...],
    errors: tuple[dict[str, str], ...],
    effects: tuple[Any, ...],
    opportunity_id: str,
    identity: RuntimeIdentity,
    generation_token: str,
    issuer: PostgresAuthorityIssuer,
    effect_ledger: PostgresEffectLedger,
    r2_store: CountingR2Store,
    output_dir: Path,
    environment: Mapping[str, str],
    source_effect_counters: Mapping[str, int],
    provider_receipt: Mapping[str, Any] | None,
    observed_responses: tuple[ObservedSourceResponse, ...] = (),
    active_effects: tuple[Mapping[str, Any], ...] = (),
    allow_r2_upload: bool = True,
    recovery_status: str = "R2_UPLOAD_PENDING_NO_RETRY_AUTHORIZED",
) -> DurableObjectReceipt | None:
    members = {
        f"responses/{item.response_sequence:03d}-{item.response_id}.bin": item.body
        for item in raw_responses
    }
    bound_observations = [False] * len(observed_responses)
    for response in raw_responses:
        for index, observed in enumerate(observed_responses):
            if (
                not bound_observations[index]
                and observed.sport_key == response.sport_key
                and observed.source == response.source
                and observed.http_status == response.http_status
                and observed.sha256 == response.sha256
            ):
                bound_observations[index] = True
                break
    unbound_observed = tuple(
        item for index, item in enumerate(observed_responses) if not bound_observations[index]
    )
    for item in unbound_observed:
        members[f"unbound/{item.observation_sequence:03d}-{item.observation_id}.bin"] = item.body
    failure = {
        "schema_version": "robin-data-torrent-partial-capture-v1",
        "status": "CONSUMED_ONE_SHOT_HARD_STOP",
        "run_identity": identity.to_json(),
        "claim_identity": opportunity_id,
        "errors": list(errors),
        "responses": [
            item.index_entry(
                archive_path=f"responses/{item.response_sequence:03d}-{item.response_id}.bin"
            )
            for item in raw_responses
        ],
        "unbound_observed_responses": [
            item.index_entry(
                archive_path=(f"unbound/{item.observation_sequence:03d}-{item.observation_id}.bin")
            )
            for item in unbound_observed
        ],
        "external_effects": [item.to_json() for item in effects],
        "active_external_effects": [dict(item) for item in active_effects],
        "source_effect_counters": dict(source_effect_counters),
        "r2_counters": r2_store.counters(),
        "provider_receipt": dict(provider_receipt) if provider_receipt is not None else None,
    }
    members["failure/partial-capture-v1.json"] = json_artifact(failure)
    attempt_evidence = {
        **failure,
        "recovery_status": recovery_status,
        "raw_payload_inventory": [
            {
                "response_id": item.response_id,
                "raw_bytes": len(item.body),
                "raw_sha256": item.sha256,
            }
            for item in raw_responses
        ]
        + [
            {
                "observation_id": item.observation_id,
                "raw_bytes": len(item.body),
                "raw_sha256": item.sha256,
                "terminal_binding": "UNAVAILABLE_AT_RESPONSE_BOUNDARY",
                "spool_name": item.spool_name,
            }
            for item in unbound_observed
        ],
    }
    attempt_artifacts = {
        "torrent-partial-capture-attempt-v1.json": json_artifact(attempt_evidence),
    }
    _secret_scan(artifacts=attempt_artifacts, environment=environment)
    # Persist a sanitized, upload-independent receipt before archive construction
    # or the R2 boundary can fail. Exact raw bytes remain only in the restricted
    # process/recovery path and are never published as a GitHub artifact.
    local_attempt_write_failed = False
    try:
        write_artifacts(output_dir, attempt_artifacts)
    except Exception:
        local_attempt_write_failed = True
        failure["local_attempt_artifact_status"] = "FAILED_BEFORE_REMOTE_DURABILITY"
        members["failure/partial-capture-v1.json"] = json_artifact(failure)
    if not allow_r2_upload:
        return None
    archive = deterministic_tar_gz(members)
    receipt = upload_immutable_object(
        role="PARTIAL_RAW",
        object_key=f"data-torrent/v1/{opportunity_id}/partial-raw.tar.gz",
        payload=archive,
        mission_id=f"{MISSION_ID}-partial-raw-r2",
        identity=identity.github,
        generation_token=generation_token,
        issuer=issuer,
        base_ledger=effect_ledger,
        store=r2_store,
    )
    evidence = {
        **failure,
        "partial_raw_object": receipt.to_json(),
        "r2_counters": r2_store.counters(),
    }
    partial_artifacts = {
        "torrent-partial-capture-receipt-v1.json": json_artifact(evidence),
    }
    _secret_scan(artifacts=partial_artifacts, environment=environment)
    try:
        write_artifacts(output_dir, partial_artifacts)
    except Exception:
        if not local_attempt_write_failed:
            failure["local_terminal_artifact_status"] = "FAILED_AFTER_REMOTE_DURABILITY"
    return receipt


def _partial_raw_put_authorized(*, error: Exception, r2_puts: int) -> bool:
    """Authorize a distinct recovery PUT only when no physical PUT was consumed."""

    if isinstance(error, DurableObjectUploadError):
        return not error.put_permit_consumed
    return r2_puts == 0


def _secret_scan(
    *,
    artifacts: Mapping[str, bytes],
    environment: Mapping[str, str],
) -> bool:
    sensitive_names = (
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        "THE_ODDS_API_KEY",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    )
    sensitive_values: set[bytes] = set()
    for name in sensitive_names:
        value = environment.get(name, "")
        if not value:
            continue
        variants = {value, unquote(value), quote(value, safe="")}
        if name.endswith("_DATABASE_URL"):
            try:
                parsed = urlsplit(value)
            except ValueError:
                parsed = None
            if parsed is not None and parsed.password:
                password = parsed.password
                decoded_password = unquote(password)
                variants.update(
                    {
                        password,
                        decoded_password,
                        quote(password, safe=""),
                        quote(decoded_password, safe=""),
                    }
                )
        sensitive_values.update(item.encode("utf-8") for item in variants if item)
    for payload in artifacts.values():
        if any(value in payload for value in sensitive_values):
            raise DataTorrentRuntimeError("DATA_TORRENT_SECRET_IN_ARTIFACT")
        lowered = payload.lower()
        if b"apikey=" in lowered or b"authorization:" in lowered:
            raise DataTorrentRuntimeError("DATA_TORRENT_SECRET_SHAPE_IN_ARTIFACT")
    return True


def _normalized_evidence_binding(
    *,
    opportunity_id: str,
    object_key: str,
) -> dict[str, Any]:
    """Describe the external terminal binding for a self-containing R2 bundle."""

    return {
        "schema_version": "robin-data-torrent-normalized-evidence-binding-v1",
        "role": "NORMALIZED_EVIDENCE",
        "object_key": object_key,
        "archive_format": "DETERMINISTIC_USTAR_GZIP_V1",
        "evidence_member_prefix": "evidence/",
        "normalized_core_members": sorted(NORMALIZED_CORE_MEMBER_NAMES),
        "evidence_members": sorted(FINAL_ARTIFACT_NAMES),
        "manifest_self_witness": {
            "member": "evidence/torrent-real-batch-manifest-v1.json",
            "rule": "PRESENT_WITHOUT_SELF_HASH",
        },
        "resolver": {
            "relation": "public.chronos_torrent_batch_audit",
            "lookup": {"opportunity_id": opportunity_id},
            "required_columns": {
                "object_key": "normalized_object_key",
                "object_sha256": "normalized_object_sha256",
                "operation_id": "normalized_operation_id",
                "terminal_event": "normalized_terminal_event_type",
                "terminal_event_hash": "normalized_terminal_event_hash",
            },
            "required_terminal_events": [
                "CREATED_CONFIRMED",
                "PREEXISTING_CONFIRMED",
            ],
            "unbound_bundle_validity": "INVALID",
        },
    }


def _json_artifact_document(payload: bytes) -> dict[str, Any]:
    try:
        document = strict_json_loads(
            payload,
            duplicate_code="DATA_TORRENT_FINAL_ARTIFACT_DUPLICATE_KEY",
            non_finite_code="DATA_TORRENT_FINAL_ARTIFACT_NON_FINITE",
        )
    except (TypeError, ValueError):
        raise DataTorrentRuntimeError("DATA_TORRENT_FINAL_ARTIFACT_JSON_INVALID") from None
    if not isinstance(document, dict):
        raise DataTorrentRuntimeError("DATA_TORRENT_FINAL_ARTIFACT_JSON_INVALID")
    return cast(dict[str, Any], document)


def _resolve_json_pointer(document: object, pointer: str) -> object:
    current = document
    if not pointer:
        return current
    if not pointer.startswith("/"):
        raise DataTorrentRuntimeError("DATA_TORRENT_QA_EVIDENCE_POINTER_INVALID")
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isascii() and token.isdigit():
            index = int(token)
            if index >= len(current):
                raise DataTorrentRuntimeError("DATA_TORRENT_QA_EVIDENCE_POINTER_INVALID")
            current = current[index]
        else:
            raise DataTorrentRuntimeError("DATA_TORRENT_QA_EVIDENCE_POINTER_INVALID")
    return current


def _assert_final_artifact_closure(
    *,
    artifacts: Mapping[str, bytes],
    normalized_binding: Mapping[str, Any],
) -> None:
    if set(artifacts) != FINAL_ARTIFACT_NAMES:
        raise DataTorrentRuntimeError("DATA_TORRENT_FINAL_ARTIFACT_SET_INVALID")
    manifest_name = "torrent-real-batch-manifest-v1.json"
    manifest = _json_artifact_document(artifacts[manifest_name])
    non_manifest = {name: payload for name, payload in artifacts.items() if name != manifest_name}
    if manifest.get("artifacts") != artifact_index(non_manifest):
        raise DataTorrentRuntimeError("DATA_TORRENT_FINAL_ARTIFACT_INDEX_INVALID")
    qa = _json_artifact_document(artifacts["torrent-qa-acceptance-matrix-v1.json"])
    try:
        verify_qa_matrix(qa)
    except ValueError:
        raise DataTorrentRuntimeError("DATA_TORRENT_QA_PROOF_INVALID") from None
    for gate in cast(list[dict[str, Any]], qa["gates"]):
        for evidence in cast(list[dict[str, Any]], gate["evidence"]):
            name = str(evidence["evidence_file"])
            pointer = str(evidence["evidence_pointer"])
            if name not in artifacts:
                raise DataTorrentRuntimeError("DATA_TORRENT_QA_EVIDENCE_FILE_INVALID")
            if pointer:
                _resolve_json_pointer(_json_artifact_document(artifacts[name]), pointer)
    binding_locations = (
        cast(dict[str, Any], manifest["evidence_validity"])["binding"],
        _json_artifact_document(artifacts["torrent-real-batch-normalized-index-v1.json"])[
            "archive_object"
        ],
        cast(
            dict[str, Any],
            _json_artifact_document(artifacts["torrent-real-batch-quality-report-v1.json"])[
                "durability"
            ],
        )["normalized_evidence_binding"],
        cast(
            list[Any],
            _json_artifact_document(artifacts["torrent-r2-inventory-v1.json"])["objects"],
        )[1],
        cast(
            dict[str, Any],
            _json_artifact_document(artifacts["torrent-control-plane-event-chain-v1.json"])[
                "events"
            ],
        )["normalized_evidence_terminal_resolver"],
    )
    expected = canonical_json_bytes(normalized_binding)
    if any(canonical_json_bytes(item) != expected for item in binding_locations):
        raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_EVIDENCE_BINDING_INVALID")


def _normalized_evidence_archive(
    *,
    normalized_members: Mapping[str, bytes],
    artifacts: Mapping[str, bytes],
    normalized_binding: Mapping[str, Any],
) -> bytes:
    _assert_final_artifact_closure(
        artifacts=artifacts,
        normalized_binding=normalized_binding,
    )
    if set(normalized_members) != NORMALIZED_CORE_MEMBER_NAMES:
        raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_MEMBER_SET_INVALID")
    evidence_members = {f"evidence/{name}": payload for name, payload in artifacts.items()}
    combined: dict[str, bytes] = dict(normalized_members)
    combined.update(evidence_members)
    if len(combined) != len(NORMALIZED_CORE_MEMBER_NAMES) + len(FINAL_ARTIFACT_NAMES):
        raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_EVIDENCE_SET_INVALID")
    return deterministic_tar_gz(combined)


def _verify_terminal_artifact_semantics(
    *,
    config: TorrentConfig,
    raw_archive: bytes,
    raw_object: DurableObjectReceipt,
    normalized_archive: bytes,
    normalized_object: DurableObjectReceipt,
    normalized_members: Mapping[str, bytes],
    artifacts: Mapping[str, bytes],
    normalized_binding: Mapping[str, Any],
    measured_replay_report_bytes: bytes,
    league_names: dict[str, str],
    team_aliases: Mapping[str, str],
    identity: RuntimeIdentity,
    expected_post_merge_ci_proof: Mapping[str, Any],
    expected_chronos_verify_proof: Mapping[str, Any],
    expected_revision: str,
    reader_engine: Any,
    runtime_effects: LiveRuntimeEffects | None = None,
    run_identity: str,
    claim_identity: str,
    anchor: datetime,
    reconciliation_observed_at: datetime,
    capture_started: datetime,
    capture_ended: datetime,
    r2_counters: Mapping[str, int],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Independently derive every terminal QA predicate from immutable bytes."""

    error_code = "DATA_TORRENT_TERMINAL_SEMANTIC_QA_FAILED"
    try:
        expected_source_run_identity = (
            f"github:{identity.github.github_repository}:"
            f"{identity.github.github_run_id}:{identity.github.github_run_attempt}:"
            f"{identity.github.github_sha}"
        )
        if run_identity != expected_source_run_identity:
            raise DataTorrentRuntimeError(error_code)
        _assert_final_artifact_closure(
            artifacts=artifacts,
            normalized_binding=normalized_binding,
        )
        if (
            raw_object.object_sha256 != hashlib.sha256(raw_archive).hexdigest()
            or raw_object.object_bytes != len(raw_archive)
            or raw_object.terminal_event not in {"CREATED_CONFIRMED", "PREEXISTING_CONFIRMED"}
            or normalized_object.object_sha256 != hashlib.sha256(normalized_archive).hexdigest()
            or normalized_object.object_bytes != len(normalized_archive)
            or normalized_object.object_key != normalized_binding.get("object_key")
            or normalized_object.terminal_event
            not in {"CREATED_CONFIRMED", "PREEXISTING_CONFIRMED"}
        ):
            raise DataTorrentRuntimeError(error_code)
        archive_members = _read_replay_archive(normalized_archive)
        expected_archive_members = set(normalized_members) | {
            f"evidence/{name}" for name in artifacts
        }
        if set(archive_members) != expected_archive_members:
            raise DataTorrentRuntimeError(error_code)
        if any(archive_members[name] != payload for name, payload in normalized_members.items()):
            raise DataTorrentRuntimeError(error_code)
        if any(
            archive_members[f"evidence/{name}"] != payload for name, payload in artifacts.items()
        ):
            raise DataTorrentRuntimeError(error_code)

        archived_official, archived_responses, _raw_bytes = _decode_replay_archive(
            config=config,
            raw_archive=raw_archive,
            expected_archive_sha256=raw_object.object_sha256,
            expected_run_identity=run_identity,
            expected_claim_identity=claim_identity,
        )
        replay_evidences, replay_horizon = _select_evidence(
            config=config,
            official=archived_official,
            anchor=anchor,
            observed_at_utc=reconciliation_observed_at,
        )
        validate_official_team_aliases(replay_evidences, team_aliases=team_aliases)
        rebuilt = normalize_batch(
            evidences=replay_evidences,
            raw_responses=archived_responses,
            league_names=league_names,
            requested_markets=config.markets,
            run_identity=run_identity,
            claim_identity=claim_identity,
            team_aliases=team_aliases,
        )
        _assert_meaningful_breadth(
            config=config,
            evidences=replay_evidences,
            batch=rebuilt,
        )
        rebuilt_lineage = _lineage(raw_responses=archived_responses, batch=rebuilt)
        if (
            archive_members["data/normalized-records.jsonl"] != rebuilt.canonical_dataset_bytes
            or archive_members["data/rejected-records.jsonl"] != rebuilt.rejects_bytes
            or archive_members["lineage/raw-to-normalized-v1.json"]
            != json_artifact(rebuilt_lineage)
            or archive_members["reports/coverage-v1.csv"] != coverage_csv(rebuilt.coverage)
        ):
            raise DataTorrentRuntimeError(error_code)

        manifest = _json_artifact_document(artifacts["torrent-real-batch-manifest-v1.json"])
        claim = _json_artifact_document(artifacts["torrent-opportunity-claim-receipt-v1.json"])
        chain = _json_artifact_document(artifacts["torrent-control-plane-event-chain-v1.json"])
        replay = _json_artifact_document(artifacts["torrent-load-replay-report-v1.json"])
        if (
            artifacts["torrent-load-replay-report-v1.json"] != measured_replay_report_bytes
            or normalized_members["reports/load-replay-v1.json"] != measured_replay_report_bytes
            or artifacts["torrent-load-replay-report-v1.md"]
            != load_replay_markdown(replay).encode("utf-8")
        ):
            raise DataTorrentRuntimeError(error_code)
        raw_index = _json_artifact_document(artifacts["torrent-real-batch-raw-index-v1.json"])
        normalized_index = _json_artifact_document(
            artifacts["torrent-real-batch-normalized-index-v1.json"]
        )
        quality = _json_artifact_document(artifacts["torrent-real-batch-quality-report-v1.json"])
        provider = _json_artifact_document(artifacts["torrent-provider-credit-receipt-v1.json"])
        transitions = provider.get("credit_transitions")
        official = _json_artifact_document(artifacts["torrent-official-read-receipts-v1.json"])
        inventory = _json_artifact_document(artifacts["torrent-r2-inventory-v1.json"])
        lineage = _json_artifact_document(artifacts["torrent-raw-to-normalized-lineage-v1.json"])
        canonical = _json_artifact_document(artifacts["torrent-canonical-dataset-hash-v1.json"])
        field_document = _json_artifact_document(
            artifacts["hypothesis-ready-field-dictionary-v1.json"]
        )
        qa = _json_artifact_document(artifacts["torrent-qa-acceptance-matrix-v1.json"])
        raw_members = _read_replay_archive(raw_archive)
        raw_core = cast(
            dict[str, Any],
            strict_json_loads(
                raw_members["indexes/raw-index-core-v1.json"],
                duplicate_code="DATA_TORRENT_TERMINAL_RAW_INDEX_DUPLICATE_KEY",
                non_finite_code="DATA_TORRENT_TERMINAL_RAW_INDEX_NON_FINITE",
            ),
        )
        raw_core_without_totals = {key: value for key, value in raw_core.items() if key != "totals"}
        final_without_extension = {
            key: value
            for key, value in raw_index.items()
            if key not in {"totals", "archive_object"}
        }
        core_totals = cast(dict[str, Any], raw_core.get("totals"))
        final_totals = cast(dict[str, Any], raw_index.get("totals"))
        expected_core_totals = {
            **{
                key: value
                for key, value in final_totals.items()
                if key not in {"accounted_responses", "silent_responses"}
            },
            "accounting_status": "PENDING_NORMALIZATION",
        }
        if (
            canonical_json_bytes(raw_core_without_totals)
            != canonical_json_bytes(final_without_extension)
            or canonical_json_bytes(core_totals) != canonical_json_bytes(expected_core_totals)
            or final_totals.get("accounting_status") != "COMPLETE"
            or set(final_totals) != set(core_totals) | {"accounted_responses", "silent_responses"}
            or final_totals.get("accounted_responses") != len(archived_responses)
            or final_totals.get("silent_responses") != 0
            or raw_index.get("archive_object")
            != {
                "object_key": raw_object.object_key,
                "bytes": raw_object.object_bytes,
                "sha256": raw_object.object_sha256,
                "media_type": "application/gzip",
                "format": "DETERMINISTIC_USTAR_GZIP_V1",
            }
        ):
            raise DataTorrentRuntimeError(error_code)
        if (
            normalized_index.get("members") != artifact_index(normalized_members)
            or normalized_index.get("canonical_dataset_sha256") != rebuilt.canonical_dataset_sha256
            or normalized_index.get("archive_object") != normalized_binding
            or lineage != rebuilt_lineage
            or artifacts["torrent-real-batch-coverage-matrix-v1.csv"]
            != coverage_csv(rebuilt.coverage)
            or field_document.get("canonical_dataset_sha256") != rebuilt.canonical_dataset_sha256
            or normalized_members["config/team-alias-registry-v1.json"]
            != json_artifact(team_alias_registry_document(team_aliases))
            or normalized_members["reports/load-replay-v1.json"]
            != artifacts["torrent-load-replay-report-v1.json"]
            or normalized_members["science/field-dictionary-v1.json"]
            != artifacts["hypothesis-ready-field-dictionary-v1.json"]
            or normalized_members["science/hypothesis-backlog-v1.md"]
            != artifacts["hypothesis-backlog-from-real-data-v1.md"]
            or normalized_members["operations/operations-pack-v1.md"]
            != artifacts["robin-data-torrent-operations-pack-v1.md"]
            or normalized_members["operations/recovery-pack-v1.md"]
            != artifacts["robin-data-torrent-recovery-pack-v1.md"]
        ):
            raise DataTorrentRuntimeError(error_code)

        source_events = cast(dict[str, Any], chain.get("events", {})).get("external_sources")
        if not isinstance(source_events, list) or len(source_events) != 10:
            raise DataTorrentRuntimeError(error_code)
        source_documents = [
            cast(dict[str, Any], item) for item in source_events if isinstance(item, dict)
        ]
        if len(source_documents) != len(source_events):
            raise DataTorrentRuntimeError(error_code)
        official_effects = [item for item in source_documents if item.get("family") == "OFFICIAL"]
        odds_effects = [item for item in source_documents if item.get("family") == "ODDS"]
        if runtime_effects is not None:
            runtime_effects.begin_read_transaction()
        with reader_engine.connect() as connection:
            database_claim_row = (
                connection.execute(
                    sa.text(
                        "SELECT * FROM public.chronos_opportunity_claim_audit "
                        "WHERE opportunity_id=:opportunity_id"
                    ),
                    {"opportunity_id": claim_identity},
                )
                .mappings()
                .one_or_none()
            )
            database_effect_rows = (
                connection.execute(
                    sa.text(
                        "SELECT * FROM public.chronos_torrent_external_effect_audit "
                        "WHERE opportunity_id=:opportunity_id "
                        "ORDER BY effect_family,effect_sequence,event_seq"
                    ),
                    {"opportunity_id": claim_identity},
                )
                .mappings()
                .all()
            )
        rows_by_operation: dict[str, list[Mapping[str, Any]]] = {}
        for row in database_effect_rows:
            rows_by_operation.setdefault(str(row["operation_id"]), []).append(row)
        if (
            database_claim_row is None
            or len(database_effect_rows) != 20
            or len(rows_by_operation) != 10
        ):
            raise DataTorrentRuntimeError(error_code)
        database_first_permit_at = min(
            cast(datetime, row["db_permitted_at"]) for row in database_effect_rows
        )
        expected_claim_database = {
            "opportunity_id": claim_identity,
            "opportunity_kind": claim.get("opportunity_kind"),
            "canonical_key": claim.get("canonical_key"),
            "mission_id": MISSION_ID,
            "authority_id": claim.get("winner_authority_id"),
            "github_run_id": identity.github.github_run_id,
            "github_run_attempt": identity.github.github_run_attempt,
            "github_sha": identity.github.github_sha,
            "github_workflow_ref": identity.github.github_workflow_ref,
            "github_workflow_sha": identity.github.github_workflow_sha,
            "github_repository": identity.github.github_repository,
            "github_ref": identity.github.github_ref,
            "code_revision": identity.github.github_sha,
            "db_claimed_at": _replay_timestamp(claim.get("db_claimed_at_utc")),
            "postgres_server_epoch": _replay_timestamp(claim.get("postgres_server_epoch_utc")),
            "claim_hash": claim.get("claim_receipt_hash"),
        }
        if (
            any(
                (
                    database_claim_row.get(name) != value
                    if isinstance(value, datetime)
                    else canonical_json_bytes(database_claim_row.get(name))
                    != canonical_json_bytes(value)
                )
                for name, value in expected_claim_database.items()
            )
            or claim.get("acquired_now") is not True
            or canonical_json_bytes(claim.get("winner_github_run_id"))
            != canonical_json_bytes(identity.github.github_run_id)
            or canonical_json_bytes(claim.get("winner_github_run_attempt"))
            != canonical_json_bytes(identity.github.github_run_attempt)
            or _replay_timestamp(claim.get("first_external_permit_at_utc"))
            != database_first_permit_at
            or claim.get("claim_before_first_external_effect") is not True
        ):
            raise DataTorrentRuntimeError(error_code)
        expected_source_sequences = list(range(1, len(config.leagues) + 1))
        if (
            any(
                type(cast(dict[str, Any], item["permit"]).get("effect_sequence")) is not int
                for item in source_documents
            )
            or sorted(
                cast(dict[str, Any], item["permit"])["effect_sequence"] for item in official_effects
            )
            != expected_source_sequences
            or sorted(
                cast(dict[str, Any], item["permit"])["effect_sequence"] for item in odds_effects
            )
            != expected_source_sequences
        ):
            raise DataTorrentRuntimeError(error_code)
        response_operations = {item.external_operation_id for item in archived_responses}
        trace_operations: set[str] = set()
        for source_document in source_documents:
            try:
                if set(source_document) != {
                    "family",
                    "sport_key",
                    "request_contract",
                    "permit",
                    "dispatched",
                    "terminal",
                }:
                    raise DataTorrentRuntimeError(error_code)
                family = source_document["family"]
                sport_key = source_document["sport_key"]
                request_contract = cast(dict[str, Any], source_document["request_contract"])
                permit = cast(dict[str, Any], source_document["permit"])
                dispatched_document = cast(dict[str, Any], source_document["dispatched"])
                terminal_document = cast(dict[str, Any], source_document["terminal"])
                operation_id = permit["operation_id"]
                if (
                    type(family) is not str
                    or type(sport_key) is not str
                    or type(operation_id) is not str
                    or not isinstance(request_contract, dict)
                    or not isinstance(permit, dict)
                    or not isinstance(dispatched_document, dict)
                    or not isinstance(terminal_document, dict)
                ):
                    raise DataTorrentRuntimeError(error_code)
                effect_sequence = permit["effect_sequence"]
                if (
                    type(effect_sequence) is not int
                    or not 1 <= effect_sequence <= len(config.leagues)
                    or sport_key != config.leagues[effect_sequence - 1].sport_key
                    or request_contract.get("sport_key") != sport_key
                ):
                    raise DataTorrentRuntimeError(error_code)
                operation_responses = sorted(
                    (
                        item
                        for item in archived_responses
                        if item.external_operation_id == operation_id
                    ),
                    key=lambda item: item.response_sequence,
                )
                database_rows = rows_by_operation[operation_id]
                if (
                    operation_id in trace_operations
                    or len(database_rows) != 2
                    or not operation_responses
                    or family not in {"OFFICIAL", "ODDS"}
                    or permit["effect_family"] != family
                    or permit["request_hash"]
                    != hashlib.sha256(canonical_json_bytes(request_contract)).hexdigest()
                    or permit["created_now"] is not True
                    or any(row["opportunity_id"] != claim_identity for row in database_rows)
                ):
                    raise DataTorrentRuntimeError(error_code)
                trace_operations.add(operation_id)
                database_permit = database_rows[0]
                expected_permit_document = {
                    "operation_id": database_permit["operation_id"],
                    "effect_family": database_permit["effect_family"],
                    "effect_sequence": database_permit["effect_sequence"],
                    "request_hash": database_permit["request_hash"],
                    "max_official_reads": database_permit["max_official_reads"],
                    "max_odds_requests": database_permit["max_odds_requests"],
                    "max_odds_credits": database_permit["max_odds_credits"],
                    "created_now": True,
                    "db_permitted_at": utc_text(cast(datetime, database_permit["db_permitted_at"])),
                    "postgres_server_epoch": utc_text(
                        cast(datetime, database_permit["postgres_server_epoch"])
                    ),
                    "permit_hash": database_permit["permit_hash"],
                }
                if (
                    canonical_json_bytes(permit) != canonical_json_bytes(expected_permit_document)
                    or database_permit["github_run_id"] != identity.github.github_run_id
                    or database_permit["github_run_attempt"] != identity.github.github_run_attempt
                    or database_permit["code_revision"] != identity.github.github_sha
                ):
                    raise DataTorrentRuntimeError(error_code)
                for event_document, database_row in zip(
                    (dispatched_document, terminal_document),
                    database_rows,
                    strict=True,
                ):
                    expected_event_document = {
                        "operation_id": database_row["operation_id"],
                        "event_seq": database_row["event_seq"],
                        "event_type": database_row["event_type"],
                        "actual_official_reads": database_row["actual_official_reads"],
                        "actual_odds_requests": database_row["actual_odds_requests"],
                        "actual_odds_credits": database_row["actual_odds_credits"],
                        "db_recorded_at": utc_text(cast(datetime, database_row["db_recorded_at"])),
                        "postgres_server_epoch": utc_text(
                            cast(
                                datetime,
                                database_row["event_postgres_server_epoch"],
                            )
                        ),
                        "previous_event_hash": database_row["previous_event_hash"],
                        "event_hash": database_row["event_hash"],
                    }
                    if canonical_json_bytes(event_document) != canonical_json_bytes(
                        expected_event_document
                    ):
                        raise DataTorrentRuntimeError(error_code)
                expected_families = (
                    {"OFFICIAL", "OFFICIAL_SUPPORTING"} if family == "OFFICIAL" else {"ODDS"}
                )
                contracts_match = all(
                    canonical_json_bytes(response.request_contract)
                    == canonical_json_bytes(
                        request_contract
                        if family == "ODDS"
                        else {
                            **request_contract,
                            "sanitized_endpoint": response.source,
                            "physical_response_index": physical_index,
                            "logical_request_endpoint": request_contract["sanitized_endpoint"],
                        }
                    )
                    for physical_index, response in enumerate(operation_responses)
                )
                if (
                    not contracts_match
                    or any(
                        response.family not in expected_families
                        or response.sport_key != sport_key
                        or response.external_effect_sequence != permit["effect_sequence"]
                        or response.permit_hash != permit["permit_hash"]
                        or response.dispatch_event_hash != dispatched_document["event_hash"]
                        or response.confirmation_event_hash != terminal_document["event_hash"]
                        for response in operation_responses
                    )
                    or sum(item.physical_reads for item in operation_responses)
                    != terminal_document["actual_official_reads"]
                    + terminal_document["actual_odds_requests"]
                    or sum(item.provider_requests for item in operation_responses)
                    != terminal_document["actual_odds_requests"]
                    or sum(item.provider_credits for item in operation_responses)
                    != terminal_document["actual_odds_credits"]
                ):
                    raise DataTorrentRuntimeError(error_code)
            except (KeyError, TypeError, ValueError):
                raise DataTorrentRuntimeError(error_code) from None
        if trace_operations != response_operations:
            raise DataTorrentRuntimeError(error_code)
        all_source_confirmed = len(official_effects) == len(odds_effects) == 5 and all(
            cast(dict[str, Any], item.get("dispatched", {})).get("event_type") == "DISPATCHED"
            and cast(dict[str, Any], item.get("terminal", {})).get("event_type") == "CONFIRMED"
            and cast(dict[str, Any], item.get("terminal", {})).get("previous_event_hash")
            == cast(dict[str, Any], item.get("dispatched", {})).get("event_hash")
            for item in source_events
        )
        chain_events = cast(dict[str, Any], chain.get("events", {}))
        expected_chain_summary = {
            "official_effects": len(config.leagues),
            "odds_effects": len(config.leagues),
            "r2_operations": 2,
            "all_external_sources_confirmed": True,
            "all_embedded_r2_terminal": True,
            "final_r2_terminal_requires_append_only_resolution": True,
        }
        expected_r2 = {"puts": 2, "gets": 0, "lists": 0, "deletes": 0}
        expected_mission_r2 = _mission_r2_counters(
            proof=expected_chronos_verify_proof,
            live_counters=expected_r2,
            live_objects=2,
        )
        expected_inventory = {
            "schema_version": "robin-data-torrent-r2-inventory-v1",
            "objects": [
                {**raw_object.to_json(), "events": list(raw_object.events)},
                normalized_binding,
            ],
            "counters": {
                "puts": 2,
                "gets": 0,
                "lists": 0,
                "deletes": 0,
                "objects": 2,
                "overwrites": 0,
                "validity": "CONDITIONAL_APPEND_ONLY_BINDING",
            },
            "control_plane_release": expected_chronos_verify_proof["controlled_go"],
            "mission_counters": expected_mission_r2,
            "limits": {
                "puts": config.budgets.r2_puts_max,
                "gets": config.budgets.r2_gets_max,
                "lists": config.budgets.r2_lists_max,
                "deletes": config.budgets.r2_deletes_max,
            },
        }
        if (
            set(chain) != {"schema_version", "events", "summary"}
            or set(chain_events)
            != {
                "external_sources",
                "r2",
                "normalized_evidence_terminal_resolver",
            }
            or chain.get("schema_version") != "robin-data-torrent-control-plane-event-chain-v1"
            or canonical_json_bytes(chain_events.get("r2"))
            != canonical_json_bytes(list(raw_object.events))
            or canonical_json_bytes(chain_events.get("normalized_evidence_terminal_resolver"))
            != canonical_json_bytes(normalized_binding)
            or canonical_json_bytes(chain.get("summary"))
            != canonical_json_bytes(expected_chain_summary)
            or canonical_json_bytes(inventory) != canonical_json_bytes(expected_inventory)
        ):
            raise DataTorrentRuntimeError(error_code)
        official_reads = sum(
            int(cast(dict[str, Any], item["terminal"])["actual_official_reads"])
            for item in official_effects
        )
        odds_requests = sum(
            int(cast(dict[str, Any], item["terminal"])["actual_odds_requests"])
            for item in odds_effects
        )
        odds_credits = sum(
            int(cast(dict[str, Any], item["terminal"])["actual_odds_credits"])
            for item in odds_effects
        )
        expected_raw_totals = {
            "raw_responses": len(archived_responses),
            "raw_bytes": _raw_bytes,
            "official_physical_reads": official_reads,
            "odds_provider_requests": odds_requests,
            "odds_credits_used": odds_credits,
            "odds_dns_resolutions": len(config.leagues),
            "accounting_status": "COMPLETE",
            "accounted_responses": len(archived_responses),
            "silent_responses": 0,
        }
        expected_record_type_counts = [
            {"record_type": name, "records": count}
            for name, count in sorted(
                Counter(str(item["record_type"]) for item in rebuilt.records).items()
            )
        ]
        alias_document = team_alias_registry_document(team_aliases)
        alias_bytes = json_artifact(alias_document)
        expected_team_aliases = {
            "artifact": TEAM_ALIASES_PATH,
            "archive_member": "config/team-alias-registry-v1.json",
            "entries": len(team_aliases),
            "mapping_sha256": alias_document["mapping_sha256"],
            "registry_artifact_sha256": hashlib.sha256(alias_bytes).hexdigest(),
            "matching_mode": "ONE_HOP_EXACT_ONLY",
        }
        expected_normalized_totals = {
            "normalized_records": len(rebuilt.records),
            "rejected_records": len(rebuilt.rejects),
            "logical_duplicates": rebuilt.logical_duplicates,
            "canonical_bytes": len(rebuilt.canonical_dataset_bytes),
        }
        expected_canonical = {
            "schema_version": "robin-data-torrent-canonical-dataset-hash-v1",
            "algorithm": "SHA-256",
            "canonicalization": "ROBIN_CANONICAL_JSON_LINES_V1",
            "record_count": len(rebuilt.records),
            "canonical_bytes": len(rebuilt.canonical_dataset_bytes),
            "original_sha256": rebuilt.canonical_dataset_sha256,
            "replay_sha256": rebuilt.canonical_dataset_sha256,
            "equality": True,
        }
        expected_official_artifact = {
            "schema_version": "robin-data-torrent-official-read-receipts-v1",
            "reads": [
                item
                for item in cast(list[dict[str, Any]], raw_index["responses"])
                if item["family"] != "ODDS"
            ],
            "total_physical_reads": official_reads,
            "maximum_physical_reads": config.budgets.official_physical_reads_max,
            "automatic_retries": 0,
        }
        expected_provider_contracts = [item.sport_key for item in config.leagues]
        expected_raw_official_receipts = json_artifact(
            {
                "reads": [
                    archived_official.results[item.sport_key].receipt.to_json()
                    for item in config.leagues
                ]
            }
        )
        expected_credit_transitions: list[dict[str, int | str]] = []
        expected_credits_total = 0
        for league in config.leagues:
            league_odds_responses = [
                item
                for item in archived_responses
                if item.family == "ODDS" and item.sport_key == league.sport_key
            ]
            if len(league_odds_responses) != 1:
                raise DataTorrentRuntimeError(error_code)
            headers = league_odds_responses[0].response_headers

            def exact_credit_header(name: str, *, maximum: int) -> int:
                value = headers.get(name)
                if type(value) is not str or not value.isascii() or not value.isdigit():
                    raise DataTorrentRuntimeError(error_code)
                parsed = int(value)
                if not 0 <= parsed <= maximum:
                    raise DataTorrentRuntimeError(error_code)
                return parsed

            credits_used = exact_credit_header("x-requests-last", maximum=200)
            used_after = exact_credit_header("x-requests-used", maximum=2**63 - 1)
            remaining_after = exact_credit_header("x-requests-remaining", maximum=2**63 - 1)
            if (
                used_after < credits_used
                or league_odds_responses[0].provider_credits != credits_used
            ):
                raise DataTorrentRuntimeError(error_code)
            expected_credit_transitions.append(
                {
                    "sport_key": league.sport_key,
                    "used_before": used_after - credits_used,
                    "used_after": used_after,
                    "remaining_after": remaining_after,
                    "credits_used": credits_used,
                }
            )
            expected_credits_total += credits_used
        provider_transitions_valid = (
            isinstance(transitions, list)
            and canonical_json_bytes(transitions)
            == canonical_json_bytes(expected_credit_transitions)
            and expected_credits_total == odds_credits
        )
        expected_provider_artifact = {
            "schema_version": "robin-data-torrent-provider-credit-receipt-v1",
            "selection_mode": "FULL",
            "contracts_requested": expected_provider_contracts,
            "markets": list(config.markets),
            "credit_transitions": expected_credit_transitions,
            "credit_accounting": "EXACT",
            "credit_anomalies": [],
            "automatic_retries": 0,
            "identical_snapshot_attempts": 1,
            "provider_requests": odds_requests,
            "credits_used": odds_credits,
            "dns_resolutions": len(config.leagues),
            "maximum_dns_resolutions": len(config.leagues),
            "maximum_credits": config.budgets.odds_credits_max,
            "errors": [],
        }
        if (
            canonical_json_bytes(final_totals) != canonical_json_bytes(expected_raw_totals)
            or raw_members["receipts/official-v1.json"] != expected_raw_official_receipts
            or raw_members["receipts/provider-credit-v1.json"]
            != artifacts["torrent-provider-credit-receipt-v1.json"]
            or canonical_json_bytes(official) != canonical_json_bytes(expected_official_artifact)
            or canonical_json_bytes(provider) != canonical_json_bytes(expected_provider_artifact)
            or not provider_transitions_valid
            or normalized_index.get("canonicalization")
            != {
                "version": "ROBIN_CANONICAL_JSON_LINES_V1",
                "sort_key": "record_id",
                "encoding": "UTF-8",
                "line_ending": "LF",
            }
            or canonical_json_bytes(normalized_index.get("team_aliases"))
            != canonical_json_bytes(expected_team_aliases)
            or canonical_json_bytes(normalized_index.get("record_type_counts"))
            != canonical_json_bytes(expected_record_type_counts)
            or canonical_json_bytes(normalized_index.get("league_market_counts"))
            != canonical_json_bytes(list(rebuilt.coverage))
            or canonical_json_bytes(normalized_index.get("totals"))
            != canonical_json_bytes(expected_normalized_totals)
            or canonical_json_bytes(canonical) != canonical_json_bytes(expected_canonical)
        ):
            raise DataTorrentRuntimeError(error_code)
        claim_time = _replay_timestamp(claim.get("db_claimed_at_utc"))
        first_permit_after_claim = all(
            _replay_timestamp(cast(dict[str, Any], item["permit"])["db_permitted_at"]) >= claim_time
            and cast(dict[str, Any], item["permit"])["created_now"] is True
            for item in source_events
        )
        actual_r2 = dict(r2_counters)
        inventory_counters = cast(dict[str, Any], inventory.get("counters", {}))
        inventory_mission_counters = cast(dict[str, Any], inventory.get("mission_counters", {}))
        manifest_actual = cast(
            dict[str, Any], cast(dict[str, Any], manifest.get("effect_summary", {})).get("actual")
        )
        expected_actual = {
            "official_physical_reads": official_reads,
            "odds_dns_resolutions": len(config.leagues),
            "odds_provider_requests": odds_requests,
            "odds_credits_used": odds_credits,
            **expected_mission_r2,
        }
        source_limits = cast(
            dict[str, Any], cast(dict[str, Any], manifest.get("effect_summary", {})).get("limits")
        )
        expected_limits = {
            **asdict(config.budgets),
            "odds_dns_resolutions_max": len(config.leagues),
        }
        hypothesis_text = artifacts["hypothesis-backlog-from-real-data-v1.md"].decode("utf-8")
        hypothesis_headers = [
            line for line in hypothesis_text.splitlines() if line.startswith("## HYP-")
        ]
        replay_acceptance = cast(dict[str, Any], replay.get("acceptance", {}))
        replay_throughput = cast(dict[str, Any], replay.get("throughput", {}))
        replay_measurement = cast(dict[str, Any], replay.get("measurement", {}))
        production = cast(dict[str, Any], manifest.get("production", {}))
        manifest_identity = cast(dict[str, Any], manifest.get("run_identity", {}))
        post_merge = cast(dict[str, Any], manifest.get("post_merge_ci_proof", {}))
        chronos = cast(dict[str, Any], manifest.get("chronos_release_chain_proof", {}))
        execution = cast(dict[str, Any], manifest.get("execution", {}))
        horizon = cast(dict[str, Any], manifest.get("horizon", {}))
        temporal = cast(dict[str, Any], quality.get("temporal", {}))
        lineage_summary = cast(dict[str, Any], lineage.get("summary", {}))
        source_units = cast(dict[str, Any], quality.get("source_unit_accounting", {}))
        official_reads_rows = official.get("reads")
        target = chronos.get("database_target")
        expected_identity = identity.to_json()
        expected_post_merge = dict(expected_post_merge_ci_proof)
        expected_chronos = dict(expected_chronos_verify_proof)
        target_valid = (
            isinstance(target, dict)
            and canonical_json_bytes(target)
            == canonical_json_bytes(expected_chronos.get("database_target"))
            and set(target)
            == {
                "host",
                "port",
                "database",
                "sslmode",
                "channel_binding",
                "server_epoch",
            }
            and target.get("channel_binding") == "require"
        )
        if (
            manifest.get("schema_version") != "robin-data-torrent-real-batch-manifest-v1"
            or manifest.get("mission_id") != MISSION_ID
            or manifest.get("config_sha256") != config.canonical_sha256
            or canonical_json_bytes(manifest_identity) != canonical_json_bytes(expected_identity)
            or canonical_json_bytes(post_merge) != canonical_json_bytes(expected_post_merge)
            or canonical_json_bytes(chronos) != canonical_json_bytes(expected_chronos)
            or production.get("database_revision") != expected_revision
            or canonical_json_bytes(claim.get("run_identity"))
            != canonical_json_bytes(expected_identity)
            or canonical_json_bytes(claim.get("cross_run_contract_proof"))
            != canonical_json_bytes(expected_post_merge)
            or canonical_json_bytes(claim.get("chronos_release_chain_proof"))
            != canonical_json_bytes(expected_chronos)
            or canonical_json_bytes(manifest.get("claim_identity")) != canonical_json_bytes(claim)
            or canonical_json_bytes(raw_core.get("run_identity"))
            != canonical_json_bytes(expected_identity)
            or canonical_json_bytes(normalized_index.get("run_identity"))
            != canonical_json_bytes(expected_identity)
            or canonical_json_bytes(quality.get("run_identity"))
            != canonical_json_bytes(expected_identity)
            or normalized_index.get("schema_version") != "robin-data-torrent-normalized-index-v1"
            or normalized_index.get("mission_id") != MISSION_ID
            or normalized_index.get("claim_identity") != claim_identity
            or replay.get("schema_version") != "robin-data-torrent-load-replay-report-v1"
            or replay.get("mission_id") != MISSION_ID
            or claim.get("schema_version") != "robin-data-torrent-opportunity-claim-receipt-v1"
            or claim.get("torrent_config_sha256") != config.canonical_sha256
            or claim.get("mission_manifest_sha256") != MISSION_MANIFEST_SHA256
            or claim.get("mission_source_sha256") != MISSION_SOURCE_SHA256
            or canonical_json_bytes(replay.get("cross_run_loser_contract_proof"))
            != canonical_json_bytes(expected_post_merge)
            or canonical_json_bytes(replay.get("chronos_release_chain_proof"))
            != canonical_json_bytes(expected_chronos)
        ):
            raise DataTorrentRuntimeError(error_code)
        coverage_complete = (
            len(rebuilt.coverage) == len(config.leagues) * len(config.markets)
            and all(item["absence_reason"] == "NONE" for item in rebuilt.coverage)
            and all(int(item["records_normalized"]) > 0 for item in rebuilt.coverage)
            and all(
                int(item["fixtures_captured"]) == int(item["fixtures_available"])
                for item in rebuilt.coverage
            )
            and all(
                float(item["coverage_percentage"]) >= MINIMUM_FIXTURE_COVERAGE_PERCENTAGE
                for item in rebuilt.coverage
            )
        )
        replay_input = cast(dict[str, Any], replay.get("input", {}))
        replay_run = cast(dict[str, Any], replay.get("replay", {}))
        replay_required = cast(dict[str, Any], replay.get("normal_required_throughput", {}))
        replay_external_delta = cast(dict[str, Any], replay.get("external_effects_delta", {}))

        def finite_number(value: object) -> bool:
            return type(value) in {int, float} and math.isfinite(float(cast(int | float, value)))

        def exact_float(actual: object, expected: float) -> bool:
            return finite_number(actual) and math.isclose(
                float(cast(int | float, actual)),
                expected,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )

        expected_external_delta_keys = {
            "official_reads",
            "odds_dns_resolutions",
            "odds_provider_dispatches",
            "odds_credits",
            "r2_puts",
            "r2_gets",
            "r2_lists",
            "r2_deletes",
        }
        expected_acceptance_keys = {
            "raw_archive_binding_pass",
            "volume_pass",
            "throughput_pass",
            "canonical_equality_pass",
            "idempotence_pass",
            "no_external_effect_pass",
        }
        expected_input = {
            "raw_archive_sha256": raw_object.object_sha256,
            "replay_source": "CONFIRMED_IMMUTABLE_RAW_ARCHIVE_BYTES",
            "raw_archive_decode_count": config.replay_multiplier,
            "raw_payload_parse_iterations": config.replay_multiplier,
            "raw_bytes_per_iteration": _raw_bytes,
            "canonical_dataset_sha256": rebuilt.canonical_dataset_sha256,
            "normalized_records_per_iteration": len(rebuilt.records),
            "rejected_records_per_iteration": len(rebuilt.rejects),
        }
        equivalent_records = len(rebuilt.records) * config.replay_multiplier
        total_replay_bytes = _raw_bytes * config.replay_multiplier
        replay_wall = replay_measurement.get("wall_clock_seconds")
        replay_wall_number = (
            float(cast(int | float, replay_wall)) if finite_number(replay_wall) else -1.0
        )
        replay_wall_valid = replay_wall_number > 0
        measured_rps = equivalent_records / replay_wall_number if replay_wall_valid else -1.0
        measured_bps = total_replay_bytes / replay_wall_number if replay_wall_valid else -1.0
        if (
            capture_started.tzinfo is None
            or capture_started.utcoffset() is None
            or capture_ended.tzinfo is None
            or capture_ended.utcoffset() is None
            or capture_ended <= capture_started
        ):
            raise DataTorrentRuntimeError(error_code)
        trusted_capture_seconds = (capture_ended - capture_started).total_seconds()
        try:
            capture_started_at = _replay_timestamp(replay_required.get("window_started_at_utc"))
            capture_ended_at = _replay_timestamp(replay_required.get("window_ended_at_utc"))
        except DataTorrentRuntimeError:
            capture_started_at = datetime.min.replace(tzinfo=UTC)
            capture_ended_at = datetime.min.replace(tzinfo=UTC)
        required_rps = len(rebuilt.records) / trusted_capture_seconds
        required_bps = _raw_bytes / trusted_capture_seconds
        records_ratio = measured_rps / required_rps if required_rps > 0 else -1.0
        bytes_ratio = measured_bps / required_bps if required_bps > 0 else -1.0
        minimum_ratio = min(records_ratio, bytes_ratio)
        independent_hashes: set[str] = set()
        independent_total_bytes = 0
        independent_started = time.perf_counter()
        for _verification_iteration in range(config.replay_multiplier):
            independent_batch, independent_iteration_bytes = _replay_archive_once(
                config=config,
                raw_archive=raw_archive,
                raw_archive_sha256=raw_object.object_sha256,
                league_names=league_names,
                team_aliases=team_aliases,
                run_identity=run_identity,
                claim_identity=claim_identity,
                anchor=anchor,
                reconciliation_observed_at=reconciliation_observed_at,
            )
            independent_total_bytes += independent_iteration_bytes
            independent_hashes.add(independent_batch.canonical_dataset_sha256)
        independent_seconds = time.perf_counter() - independent_started
        independent_rps = equivalent_records / independent_seconds
        independent_bps = independent_total_bytes / independent_seconds
        independent_minimum_ratio = min(
            independent_rps / required_rps if required_rps > 0 else -1.0,
            independent_bps / required_bps if required_bps > 0 else -1.0,
        )
        independent_load_pass = (
            independent_hashes == {rebuilt.canonical_dataset_sha256}
            and independent_total_bytes == total_replay_bytes
            and independent_minimum_ratio >= config.minimum_throughput_ratio
        )
        p50_latency = replay_measurement.get("p50_latency_ms")
        p95_latency = replay_measurement.get("p95_latency_ms")
        p50_number = float(cast(int | float, p50_latency)) if finite_number(p50_latency) else -1.0
        p95_number = float(cast(int | float, p95_latency)) if finite_number(p95_latency) else -1.0
        replay_arithmetic = (
            canonical_json_bytes(replay_input) == canonical_json_bytes(expected_input)
            and canonical_json_bytes(replay_run)
            == canonical_json_bytes(
                {
                    "multiplier": config.replay_multiplier,
                    "equivalent_normalized_records": equivalent_records,
                    "iterations_completed": config.replay_multiplier,
                    "total_records_processed": equivalent_records,
                    "total_bytes_processed": total_replay_bytes,
                }
            )
            and replay_required.get("basis") == "REAL_BATCH_CAPTURE_WINDOW"
            and capture_started_at == capture_started.astimezone(UTC)
            and capture_ended_at == capture_ended.astimezone(UTC)
            and exact_float(replay_required.get("elapsed_seconds"), trusted_capture_seconds)
            and exact_float(replay_required.get("records_per_second"), required_rps)
            and exact_float(replay_required.get("bytes_per_second"), required_bps)
            and replay_wall_valid
            and exact_float(replay_measurement.get("records_per_second"), measured_rps)
            and exact_float(replay_measurement.get("bytes_per_second"), measured_bps)
            and replay_measurement.get("latency_sample_unit") == "BATCH_REPLAY_ITERATION"
            and replay_measurement.get("latency_sample_count") == config.replay_multiplier
            and finite_number(p50_latency)
            and finite_number(p95_latency)
            and 0 <= p50_number <= p95_number
            and p95_number <= replay_wall_number * 1000.0
            and type(replay_measurement.get("baseline_rss_bytes")) is int
            and type(replay_measurement.get("peak_memory_bytes")) is int
            and type(replay_measurement.get("incremental_peak_memory_bytes")) is int
            and int(replay_measurement["peak_memory_bytes"])
            >= int(replay_measurement["baseline_rss_bytes"])
            and int(replay_measurement["incremental_peak_memory_bytes"]) >= 0
            and replay_measurement.get("rejects") == len(rebuilt.rejects) * config.replay_multiplier
            and replay_measurement.get("duplicates") == rebuilt.logical_duplicates
            and replay_measurement.get("silent_losses") == rebuilt.silent_drops
            and replay_measurement.get("unique_canonical_hashes")
            == [rebuilt.canonical_dataset_sha256]
            and exact_float(replay_throughput.get("records_ratio"), records_ratio)
            and exact_float(replay_throughput.get("bytes_ratio"), bytes_ratio)
            and exact_float(replay_throughput.get("minimum_ratio"), minimum_ratio)
            and replay_throughput.get("required_minimum_ratio") == config.minimum_throughput_ratio
            and set(replay_external_delta) == expected_external_delta_keys
            and all(type(value) is int and value == 0 for value in replay_external_delta.values())
            and set(replay_acceptance) == expected_acceptance_keys
            and all(type(value) is bool for value in replay_acceptance.values())
            and canonical_json_bytes(replay_acceptance)
            == canonical_json_bytes(
                {
                    "raw_archive_binding_pass": True,  # nosec B105 - acceptance boolean.
                    "volume_pass": (
                        config.replay_multiplier >= 100 or equivalent_records >= 100_000
                    ),
                    "throughput_pass": (minimum_ratio >= config.minimum_throughput_ratio),
                    "canonical_equality_pass": True,  # nosec B105 - acceptance boolean.
                    "idempotence_pass": True,  # nosec B105 - acceptance boolean.
                    "no_external_effect_pass": True,  # nosec B105 - acceptance boolean.
                }
            )
            and replay.get("status") == "PASS"
        )
        numeric_load = (
            replay_arithmetic
            and minimum_ratio >= config.minimum_throughput_ratio
            and independent_load_pass
        )
        expected_reject_counts = [
            {"reason_code": name, "count": count}
            for name, count in sorted(
                Counter(str(item["reason"]) for item in rebuilt.rejects).items()
            )
        ]
        expected_quality_gates = [
            {"gate_id": name, "status": "PASS", "observed": observed, "required": required}
            for name, observed, required in (
                ("silent_drops", rebuilt.silent_drops, 0),
                ("logical_duplicates", rebuilt.logical_duplicates, 0),
                ("temporal_leakage", rebuilt.temporal_leakage, 0),
                ("replay_multiplier", config.replay_multiplier, 100),
                (
                    "throughput_ratio",
                    replay_throughput["minimum_ratio"],
                    config.minimum_throughput_ratio,
                ),
                ("unaccounted_external_effects", 0, 0),
            )
        ]
        expected_quality_projection = {
            "schema_version": "robin-data-torrent-quality-report-v1",
            "mission_id": MISSION_ID,
            "run_identity": expected_identity,
            "claim_identity": claim_identity,
            "response_accounting": {
                "observed": len(archived_responses),
                "accounted": len(archived_responses),
                "silent": 0,
            },
            "source_unit_accounting": {
                "observed": rebuilt.raw_events_observed,
                "accounted": rebuilt.raw_events_accounted,
                "silent": rebuilt.silent_drops,
            },
            "rejects_by_reason": expected_reject_counts,
            "logical_duplicates": rebuilt.logical_duplicates,
            "temporal": {
                "timezone_missing": 0,
                "backfill": 0,
                "future_information": 0,
                "post_event_as_pre_event": 0,
                "leakage_total": rebuilt.temporal_leakage,
            },
            "coverage": {
                "expected_cells": len(config.leagues) * len(config.markets),
                "emitted_cells": len(rebuilt.coverage),
                "minimum_fixture_coverage_percentage": (MINIMUM_FIXTURE_COVERAGE_PERCENTAGE),
                "minimum_observed_fixture_coverage_percentage": min(
                    float(item["coverage_percentage"]) for item in rebuilt.coverage
                ),
                "incomplete_cells": sum(
                    int(item["absence_reason"] != "NONE") for item in rebuilt.coverage
                ),
            },
            "durability": {
                "raw_verified": True,
                "normalized_verified": "CONDITIONAL_APPEND_ONLY_BINDING",
                "normalized_evidence_binding": normalized_binding,
            },
            "lineage": {
                "raw_responses_covered": len(archived_responses),
                "normalized_records_covered": len(rebuilt.records),
                "rejected_units_covered": len(rebuilt.rejects),
            },
            "replay": {
                "canonical_equality": True,
                "external_reads": 0,
                "report": replay,
            },
            "external_effects": {
                "official_source_operations": len(config.leagues),
                "official_physical_reads": official_reads,
                "odds_provider_operations": len(config.leagues),
                "odds_dns_resolutions": len(config.leagues),
                "odds_provider_requests": odds_requests,
                "r2_live_operations": sum(expected_r2.values()),
                "r2_control_plane_operations": 3,
                "r2_mission_operations": (
                    expected_mission_r2["puts"] + expected_mission_r2["gets"]
                ),
                "r2_objects": expected_mission_r2["objects"],
                "accounted": (
                    official_reads
                    + len(config.leagues)
                    + odds_requests
                    + expected_mission_r2["puts"]
                    + expected_mission_r2["gets"]
                ),
                "unaccounted": 0,
            },
            "gates": expected_quality_gates,
            "quality_status": "PASS",
        }
        quality_without_generated_at = {
            name: value for name, value in quality.items() if name != "generated_at_utc"
        }
        if set(quality) != set(expected_quality_projection) | {
            "generated_at_utc"
        } or canonical_json_bytes(quality_without_generated_at) != canonical_json_bytes(
            expected_quality_projection
        ):
            raise DataTorrentRuntimeError(error_code)
        _replay_timestamp(quality.get("generated_at_utc"))

        fixtures_available = sum(len(item.fixtures) for item in replay_evidences)
        captured_fixture_ids = {
            str(item["canonical_fixture_id"])
            for item in rebuilt.records
            if item["record_type"] == "ODDS_OUTCOME"
        }
        expected_manifest_counts = {
            "leagues_enabled": len(config.leagues),
            "leagues_with_real_data": len(
                {item.sport_key for item in replay_evidences if item.fixtures}
            ),
            "fixtures_available": fixtures_available,
            "fixtures_captured": len(captured_fixture_ids),
            "markets_requested": len(config.markets),
            "markets_returned": len(
                {
                    item["market_key"]
                    for item in rebuilt.records
                    if item["record_type"] == "ODDS_OUTCOME"
                }
            ),
            **expected_raw_totals,
            "normalized_records": len(rebuilt.records),
            "rejected_records": len(rebuilt.rejects),
            "silent_drops": rebuilt.silent_drops,
            "logical_duplicates": rebuilt.logical_duplicates,
            "temporal_leakage": rebuilt.temporal_leakage,
        }
        expected_manifest_scope = {
            "season": config.season,
            "region": config.region,
            "leagues_enabled": [
                {"sport_key": item.sport_key, "name": item.name} for item in config.leagues
            ],
            "markets_enabled": list(config.markets),
            "minimum_fixture_coverage_percentage": (MINIMUM_FIXTURE_COVERAGE_PERCENTAGE),
            "team_aliases": {
                "artifact": TEAM_ALIASES_PATH,
                "entries": len(team_aliases),
                "mapping_sha256": alias_document["mapping_sha256"],
                "registry_artifact_sha256": hashlib.sha256(alias_bytes).hexdigest(),
                "matching_mode": "ONE_HOP_EXACT_ONLY",
            },
        }
        expected_raw_object_document = {
            **raw_object.to_json(),
            "events": list(raw_object.events),
        }
        expected_manifest_projection = {
            "schema_version": "robin-data-torrent-real-batch-manifest-v1",
            "mission_id": MISSION_ID,
            "status": "SUCCESS",
            "evidence_validity": {
                "mode": "CONDITIONAL_APPEND_ONLY_EXTERNAL_BINDING_V1",
                "binding": normalized_binding,
                "unbound_status": "INVALID",
            },
            "config_sha256": config.canonical_sha256,
            "run_identity": expected_identity,
            "post_merge_ci_proof": expected_post_merge,
            "chronos_release_chain_proof": expected_chronos,
            "claim_identity": claim,
            "production": {
                "database_revision": expected_revision,
                "runtime_bindings_present": [
                    "CHRONOS_AUTHORITY_DATABASE_URL",
                    "CHRONOS_RUNTIME_DATABASE_URL",
                    "CHRONOS_READER_DATABASE_URL",
                    "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
                ],
                "cloud_runtime": "ubuntu-latest",
            },
            "scope": expected_manifest_scope,
            "horizon": replay_horizon,
            "execution": {
                "official_batch_status": "SUCCESS",
                "odds_snapshot_status": "SUCCESS",
                "odds_selection_mode": "FULL",
                "automatic_retries": 0,
                "identical_snapshot_attempts": 1,
                "safety_locks": dict(PRODUCTION_SAFETY_LOCKS),
            },
            "counts": expected_manifest_counts,
            "effect_summary": {
                "limits": expected_limits,
                "actual": expected_actual,
                "unaccounted_external_effects": 0,
            },
            "durability": {
                "raw_object": expected_raw_object_document,
                "normalized_evidence_binding": normalized_binding,
                "verification_status": "VALID_ONLY_WITH_APPEND_ONLY_BINDING",
            },
            "integrity": {
                "raw_response_accounting": "COMPLETE",
                "raw_to_normalized_lineage": "COMPLETE",
                "canonical_replay_equality": True,
                "idempotent_replay": True,
                "temporal_validity": "PASS",
            },
            "canonical_dataset_sha256": rebuilt.canonical_dataset_sha256,
            "data_torrent_ready": True,
            "edge_promotions": 0,
            "bet_calls": 0,
        }
        manifest_projection = {
            name: value
            for name, value in manifest.items()
            if name not in {"generated_at_utc", "artifacts"}
        }
        if set(manifest) != set(expected_manifest_projection) | {
            "generated_at_utc",
            "artifacts",
        } or canonical_json_bytes(manifest_projection) != canonical_json_bytes(
            expected_manifest_projection
        ):
            raise DataTorrentRuntimeError(error_code)
        _replay_timestamp(manifest.get("generated_at_utc"))
        secret_safety = _secret_scan(artifacts=artifacts, environment=environment) and _secret_scan(
            artifacts=normalized_members,
            environment=environment,
        )
        derived = {
            "baseline_identity": (
                manifest_identity.get("github_sha")
                == manifest_identity.get("github_workflow_sha")
                == manifest_identity.get("post_merge_ci_sha")
                == post_merge.get("head_sha")
                and post_merge.get("conclusion") == "success"
            ),
            "cross_run_claim": (
                claim.get("acquired_now") is True
                and claim.get("claim_identity", claim.get("opportunity_id")) == claim_identity
                and claim.get("opportunity_id") == claim_identity
                and claim.get("claim_before_first_external_effect") is True
                and first_permit_after_claim
                and cast(dict[str, Any], claim.get("cross_run_contract_proof", {})).get(
                    "conclusion"
                )
                == "success"
            ),
            "loser_replay_no_reads": (
                replay_arithmetic
                and all(value == 0 for value in replay_external_delta.values())
                and cast(dict[str, Any], replay.get("cross_run_loser_contract_proof", {})).get(
                    "cross_run_test_contract"
                )
                == CROSS_RUN_CONTRACT
            ),
            "migration_rbac": (
                production.get("database_revision") == EXPECTED_REVISION
                and chronos.get("revision") == EXPECTED_REVISION
                and chronos.get("verdict") == "CHRONOS_SCOPED_IDENTITIES_READY"
                and target_valid
            ),
            "production_bindings": (
                production.get("runtime_bindings_present")
                == [
                    "CHRONOS_AUTHORITY_DATABASE_URL",
                    "CHRONOS_RUNTIME_DATABASE_URL",
                    "CHRONOS_READER_DATABASE_URL",
                    "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
                ]
                and target_valid
            ),
            "ordering_one_shot": (
                claim.get("claim_before_first_external_effect") is True
                and manifest_identity.get("github_run_attempt") == 1
                and all_source_confirmed
            ),
            "ledger_caps": (
                all_source_confirmed
                and manifest_actual == expected_actual
                and source_limits == expected_limits
                and actual_r2 == expected_r2
                and inventory_counters
                == {
                    **expected_r2,
                    "objects": 2,
                    "overwrites": 0,
                    "validity": "CONDITIONAL_APPEND_ONLY_BINDING",
                }
                and inventory_mission_counters == expected_mission_r2
                and inventory.get("control_plane_release") == expected_chronos["controlled_go"]
                and expected_mission_r2["puts"] <= config.budgets.r2_puts_max
                and expected_mission_r2["gets"] <= config.budgets.r2_gets_max
                and expected_mission_r2["lists"] <= config.budgets.r2_lists_max
                and expected_mission_r2["deletes"] <= config.budgets.r2_deletes_max
                and official_reads <= config.budgets.official_physical_reads_max
                and odds_requests == len(config.leagues)
                and 0 < odds_credits <= config.budgets.odds_credits_max
            ),
            "forbidden_effects": (
                execution.get("automatic_retries") == 0
                and cast(dict[str, Any], manifest.get("effect_summary", {})).get(
                    "unaccounted_external_effects"
                )
                == 0
                and inventory_counters.get("deletes") == 0
                and inventory_counters.get("overwrites") == 0
                and execution.get("safety_locks") == dict(PRODUCTION_SAFETY_LOCKS)
            ),
            "secret_safety": secret_safety,
            "temporal_safety": (
                rebuilt.temporal_leakage == 0
                and temporal.get("leakage_total") == 0
                and horizon.get("no_backfill") is True
            ),
            "scope_horizon": (
                horizon == replay_horizon
                and horizon.get("selected_days")
                in {config.primary_horizon_days, config.fallback_horizon_days}
                and int(horizon.get("selected_fixture_count", 0)) > 0
            ),
            "official_breadth": (
                isinstance(official_reads_rows, list)
                and official.get("total_physical_reads") == official_reads
                and official.get("maximum_physical_reads")
                == config.budgets.official_physical_reads_max
                and {
                    item.get("sport_key")
                    for item in official_reads_rows
                    if isinstance(item, dict) and item.get("family") == "OFFICIAL"
                }
                == {item.sport_key for item in config.leagues}
            ),
            "odds_breadth": (
                isinstance(transitions, list)
                and len(transitions) == len(config.leagues)
                and provider.get("provider_requests") == odds_requests == len(config.leagues)
                and provider.get("dns_resolutions") == len(config.leagues)
                and provider.get("credits_used") == odds_credits
                and provider.get("maximum_credits") == config.budgets.odds_credits_max
                and provider.get("errors") == []
            ),
            "raw_durability": (
                raw_object.object_bytes > 0
                and final_totals.get("raw_responses") == len(archived_responses)
                and final_totals.get("accounted_responses") == len(archived_responses)
                and final_totals.get("silent_responses") == 0
            ),
            "normalization_lineage": (
                rebuilt.silent_drops == 0
                and lineage_summary.get("raw_responses_observed") == len(archived_responses)
                and lineage_summary.get("raw_responses_accounted") == len(archived_responses)
                and lineage_summary.get("silent_responses") == 0
                and source_units.get("observed") == source_units.get("accounted")
                and source_units.get("silent") == 0
            ),
            "fixture_mapping_coverage": coverage_complete,
            "replay": (
                replay_arithmetic
                and replay.get("status") == "PASS"
                and replay.get("input", {}).get("raw_archive_sha256") == raw_object.object_sha256
                and replay.get("input", {}).get("replay_source")
                == "CONFIRMED_IMMUTABLE_RAW_ARCHIVE_BYTES"
                and replay_acceptance
                and all(value is True for value in replay_acceptance.values())
                and canonical.get("equality") is True
                and canonical.get("original_sha256")
                == canonical.get("replay_sha256")
                == rebuilt.canonical_dataset_sha256
            ),
            "load": numeric_load,
            "artifact_closure": canonical_json_bytes(manifest.get("artifacts"))
            == canonical_json_bytes(
                artifact_index(
                    {
                        name: payload
                        for name, payload in artifacts.items()
                        if name != "torrent-real-batch-manifest-v1.json"
                    }
                )
            ),
            "ops_recovery_science": (
                10 <= len(hypothesis_headers) <= 20
                and len(hypothesis_headers) == len(set(hypothesis_headers))
                and hypothesis_text.count("Status: NOT_TESTED") == len(hypothesis_headers)
                and hypothesis_text.count("Observation:") == len(hypothesis_headers)
                and hypothesis_text.count("Hypothesis:") == len(hypothesis_headers)
                and hypothesis_text.count("Edge promotion: NO") == len(hypothesis_headers)
                and bool(field_document.get("fields"))
                and artifacts["robin-data-torrent-operations-pack-v1.md"].startswith(
                    b"# Robin data torrent operations pack V1"
                )
                and artifacts["robin-data-torrent-recovery-pack-v1.md"].startswith(
                    b"# Robin data torrent recovery pack V1"
                )
            ),
            "ci_merge_postmerge": (
                post_merge.get("head_sha") == manifest_identity.get("github_sha")
                and post_merge.get("conclusion") == "success"
                and chronos.get("main_sha") == manifest_identity.get("github_sha")
                and chronos.get("post_merge_ci_sha") == post_merge.get("head_sha")
                and chronos.get("verify_run_attempt") == 1
            ),
        }
        qa_rows = qa.get("gates")
        if not isinstance(qa_rows, list) or len(qa_rows) != len(derived) + 1:
            raise DataTorrentRuntimeError(error_code)
        observed = {
            item.get("gate_id"): item.get("observed")
            for item in qa_rows[:-1]
            if isinstance(item, dict)
        }
        terminal = qa_rows[-1]
        if (
            canonical_json_bytes(observed) != canonical_json_bytes(derived)
            or not all(derived.values())
            or not isinstance(terminal, dict)
            or terminal.get("gate_id") != "qa_terminal"
            or terminal.get("observed") is not True
            or canonical_json_bytes(qa.get("summary"))
            != canonical_json_bytes(
                {
                    "passed": len(qa_rows),
                    "total": len(qa_rows),
                    "qa_acceptance_percent": 100,
                    "p0": 0,
                    "p1": 0,
                    "p2": 0,
                    "open_threads": 0,
                }
            )
        ):
            raise DataTorrentRuntimeError(error_code)
    except DataTorrentRuntimeError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise DataTorrentRuntimeError(error_code) from None
    return {
        "schema_version": "robin-data-torrent-terminal-semantic-qa-v1",
        "status": "PASS",
        "raw_archive_sha256": raw_object.object_sha256,
        "normalized_archive_sha256": normalized_object.object_sha256,
        "canonical_dataset_sha256": rebuilt.canonical_dataset_sha256,
        "qa_acceptance_percent": 100,
        "gates_verified": len(derived) + 1,
        "external_effects": expected_mission_r2,
        "live_r2_effects": dict(r2_counters),
        "independent_replay": {
            "multiplier": config.replay_multiplier,
            "canonical_equality": independent_hashes == {rebuilt.canonical_dataset_sha256},
            "records_per_second": independent_rps,
            "bytes_per_second": independent_bps,
            "minimum_ratio": independent_minimum_ratio,
            "required_minimum_ratio": config.minimum_throughput_ratio,
            "status": "PASS" if independent_load_pass else "FAIL",
        },
    }


def _assert_recorded_batch_binding(
    *,
    reader_engine: Any,
    runtime_effects: LiveRuntimeEffects | None = None,
    opportunity_id: str,
    raw_object: DurableObjectReceipt,
    normalized_object: DurableObjectReceipt,
    canonical_dataset_sha256: str,
    record_hash: str,
    identity: RuntimeIdentity,
    expected_counts: Mapping[str, int],
) -> None:
    if runtime_effects is not None:
        runtime_effects.begin_read_transaction()
    with reader_engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    "SELECT * FROM public.chronos_torrent_batch_audit "
                    "WHERE opportunity_id=:opportunity_id"
                ),
                {"opportunity_id": opportunity_id},
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise DataTorrentRuntimeError("DATA_TORRENT_BATCH_READBACK_MISSING")
    expected = {
        "opportunity_id": opportunity_id,
        "raw_operation_id": raw_object.operation_id,
        "raw_object_key": raw_object.object_key,
        "raw_object_sha256": raw_object.object_sha256,
        "raw_terminal_event_type": raw_object.terminal_event,
        "raw_terminal_event_hash": raw_object.terminal_event_hash,
        "normalized_operation_id": normalized_object.operation_id,
        "normalized_object_key": normalized_object.object_key,
        "normalized_object_sha256": normalized_object.object_sha256,
        "canonical_dataset_sha256": canonical_dataset_sha256,
        "normalized_terminal_event_type": normalized_object.terminal_event,
        "normalized_terminal_event_hash": normalized_object.terminal_event_hash,
        "github_run_id": identity.github.github_run_id,
        "github_run_attempt": identity.github.github_run_attempt,
        "code_revision": identity.github.github_sha,
        "record_hash": record_hash,
        "qa_acceptance_percent": 100,
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "open_threads": 0,
        "edge_promotions": 0,
        "bet_calls": 0,
        "data_torrent_ready": True,
        **dict(expected_counts),
    }
    if any(
        canonical_json_bytes(row.get(name)) != canonical_json_bytes(value)
        for name, value in expected.items()
    ):
        raise DataTorrentRuntimeError("DATA_TORRENT_BATCH_READBACK_MISMATCH")


def _execute_data_torrent(
    *,
    repository_root: Path,
    config_path: Path,
    output_dir: Path,
    environment: Mapping[str, str] | None = None,
    system_platform: str = sys.platform,
) -> dict[str, Any]:
    runtime_effects = _current_live_runtime_effects()
    env = os.environ if environment is None else environment
    try:
        assert_production_safety_locks(env)
    except ChronosProductionError as error:
        raise DataTorrentRuntimeError(str(error)) from None
    try:
        validate_data_torrent_authority(repository_root=repository_root)
    except ChronosProductionError as error:
        raise DataTorrentRuntimeError(str(error)) from None
    mission_manifest = _validated_mission_manifest(
        repository_root=repository_root,
        environment=env,
    )
    identity = _runtime_identity(
        repository_root=repository_root,
        environment=env,
        system_platform=system_platform,
    )
    post_merge_ci_proof = _validated_hold_report(
        repository_root=repository_root,
        environment=env,
        identity=identity,
    )
    generation_token = require_hash(
        _required(env, "CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
        field="generation_nonce",
    )
    expected_generation_hash = require_hash(
        _context(env, "DATA_TORRENT_EXPECTED_GENERATION_HASH"),
        field="expected_generation_hash",
    )
    if generation_hash(generation_token) != expected_generation_hash:
        raise DataTorrentRuntimeError("DATA_TORRENT_GENERATION_MISMATCH")
    chronos_verify_proof = _validated_chronos_verify_artifact(
        repository_root=repository_root,
        environment=env,
        identity=identity,
        generation_token=generation_token,
        expected_generation_hash=expected_generation_hash,
    )
    config = load_torrent_config(config_path)
    _assert_config_within_mission_authority(config)
    team_aliases = load_team_aliases(repository_root / TEAM_ALIASES_PATH)
    team_alias_registry = team_alias_registry_document(team_aliases)
    team_alias_registry_bytes = json_artifact(team_alias_registry)
    team_aliases_sha256 = str(team_alias_registry["mapping_sha256"])
    team_alias_registry_sha256 = hashlib.sha256(team_alias_registry_bytes).hexdigest()
    if output_dir.exists():
        raise DataTorrentRuntimeError("DATA_TORRENT_OUTPUT_ALREADY_EXISTS")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    authority_url = _required(env, "CHRONOS_AUTHORITY_DATABASE_URL")
    runtime_url = _required(env, "CHRONOS_RUNTIME_DATABASE_URL")
    reader_url = _required(env, "CHRONOS_READER_DATABASE_URL")
    targets = [
        validate_direct_postgres_url(value) for value in (authority_url, runtime_url, reader_url)
    ]
    for value in (authority_url, runtime_url, reader_url):
        require_generation_bound_password(
            password=unquote(urlsplit(value).password or ""),
            nonce_hex=generation_token,
        )
    if len({(item.host, item.port, item.database) for item in targets}) != 1:
        raise DataTorrentRuntimeError("DATA_TORRENT_SCOPED_DATABASE_MISMATCH")
    _assert_chronos_verify_database_targets(
        proof=chronos_verify_proof,
        targets=targets,
    )
    try:
        validate_data_torrent_authority(repository_root=repository_root)
    except ChronosProductionError as error:
        raise DataTorrentRuntimeError(str(error)) from None
    authority_engine = build_engine(authority_url)
    runtime_engine = build_engine(runtime_url)
    reader_engine = build_engine(reader_url)
    try:
        _assert_scoped_database_identities(
            targets=targets,
            engines=[authority_engine, runtime_engine, reader_engine],
            effects=runtime_effects,
        )
        try:
            validate_data_torrent_authority(repository_root=repository_root)
        except ChronosProductionError as error:
            raise DataTorrentRuntimeError(str(error)) from None
        runtime_effects.begin_read_transaction()
        with reader_engine.connect() as connection:
            revision = str(
                connection.scalar(sa.text("SELECT version_num FROM public.alembic_version"))
            )
        if revision != EXPECTED_REVISION:
            raise DataTorrentRuntimeError("DATA_TORRENT_DATABASE_REVISION_MISMATCH")
        authority_client = _AccountingPostgresFunctionClient(
            authority_engine,
            effects=runtime_effects,
        )
        runtime_client = _AccountingPostgresFunctionClient(
            runtime_engine,
            effects=runtime_effects,
        )
        issuer = PostgresAuthorityIssuer(authority_client)
        effect_ledger = PostgresEffectLedger(runtime_client)
        external_ledger = PostgresExternalEffectLedger(runtime_client)
        opportunity = _opportunity(mission_manifest)
        claim_authority_id = issuer.issue_authority(
            mission_id=MISSION_ID,
            identity=identity.github,
            generation_token=generation_token,
            ttl_seconds=1200,
            code_revision=identity.github.github_sha,
        )
        claim = PostgresOpportunityClaimer(runtime_client).claim(
            authority_id=claim_authority_id,
            mission_id=MISSION_ID,
            identity=identity.github,
            generation_token=generation_token,
            opportunity=opportunity,
            code_revision=identity.github.github_sha,
        )
        if not claim.acquired_now:
            loser = _claim_json(
                opportunity=opportunity,
                receipt=claim,
                identity=identity,
                mission_manifest=mission_manifest,
                config_sha256=config.canonical_sha256,
                first_external_permit_at=None,
            )
            loser["loser_effect_counters"] = {
                "official_physical_reads": 0,
                "odds_provider_requests": 0,
                "odds_credits_used": 0,
                "r2_puts": 0,
                "r2_gets": 0,
                "r2_lists": 0,
                "r2_deletes": 0,
            }
            loser["post_merge_ci_proof"] = post_merge_ci_proof
            loser["chronos_verify_proof"] = chronos_verify_proof
            write_artifacts(
                output_dir,
                {"torrent-opportunity-claim-receipt-v1.json": json_artifact(loser)},
            )
            return {
                "status": "LOSER_ZERO_EFFECTS",
                **loser["loser_effect_counters"],
                "runtime_effects": runtime_effects.snapshot(),
            }

        base_r2_store = ChronosR2ConditionalStore.from_environment(env)
        r2_store = CountingR2Store(base_r2_store, config.budgets)
        source_effect_counters = SourceEffectCounters()
        runtime_effects.r2_store = r2_store
        runtime_effects.source_counters = source_effect_counters
        source_progress = SourceCaptureProgress(
            spool_directory=(output_dir.parent / f".raw-spool-{claim.opportunity_id}")
        )
        capture_started = datetime.now(UTC)
        anchor = capture_started
        try:
            official = capture_official_sources(
                config=config,
                ledger=external_ledger,
                opportunity_id=claim.opportunity_id,
                identity=identity.github,
                generation_token=generation_token,
                counters=source_effect_counters,
                anchor=anchor,
                progress=source_progress,
            )
        except Exception as error:
            _durabilize_partial_capture(
                raw_responses=tuple(source_progress.raw_responses),
                observed_responses=tuple(source_progress.observed_responses),
                errors=(
                    {
                        "sport_key": "ALL",
                        "code": "DATA_TORRENT_OFFICIAL_CAPTURE_INTERRUPTED",
                    },
                ),
                effects=tuple(source_progress.effects),
                active_effects=tuple(source_progress.active_effects.values()),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=None,
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_OFFICIAL_CAPTURE_INTERRUPTED") from error
        if official.errors or len(official.results) != len(config.leagues):
            _durabilize_partial_capture(
                raw_responses=official.raw_responses,
                errors=official.errors,
                effects=official.effects,
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=None,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_OFFICIAL_BATCH_FAILED")
        reconciliation_observed_at = datetime.now(UTC)
        try:
            evidences, horizon = _select_evidence(
                config=config,
                official=official,
                anchor=anchor,
                observed_at_utc=reconciliation_observed_at,
            )
            validate_official_team_aliases(evidences, team_aliases=team_aliases)
        except Exception as error:
            error_code = (
                str(error)
                if isinstance(error, ValueError | RuntimeError)
                and str(error).startswith(
                    (
                        "DATA_TORRENT_",
                        "OFFICIAL_",
                        "LALIGA_",
                        "LIGUE1_",
                        "PREMIER_",
                        "SERIE_",
                        "BUNDESLIGA_",
                    )
                )
                else "DATA_TORRENT_OFFICIAL_EVIDENCE_INVALID"
            )
            _durabilize_partial_capture(
                raw_responses=official.raw_responses,
                errors=({"sport_key": "ALL", "code": error_code},),
                effects=official.effects,
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=None,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_OFFICIAL_EVIDENCE_FAILED") from error
        try:
            odds = capture_odds_sources(
                config=config,
                ledger=external_ledger,
                opportunity_id=claim.opportunity_id,
                identity=identity.github,
                generation_token=generation_token,
                environment=env,
                response_sequence_start=len(official.raw_responses),
                counters=source_effect_counters,
                progress=source_progress,
            )
        except Exception as error:
            _durabilize_partial_capture(
                raw_responses=tuple(source_progress.raw_responses),
                observed_responses=tuple(source_progress.observed_responses),
                errors=(
                    {
                        "sport_key": "ALL",
                        "code": "DATA_TORRENT_ODDS_CAPTURE_INTERRUPTED",
                    },
                ),
                effects=tuple(source_progress.effects),
                active_effects=tuple(source_progress.active_effects.values()),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=None,
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_ODDS_CAPTURE_INTERRUPTED") from error
        if odds.errors or len(odds.raw_responses) != len(config.leagues):
            _durabilize_partial_capture(
                raw_responses=(*official.raw_responses, *odds.raw_responses),
                errors=odds.errors,
                effects=(*official.effects, *odds.effects),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=odds.provider_receipt,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_ODDS_BATCH_FAILED")
        raw_responses = (*official.raw_responses, *odds.raw_responses)
        try:
            _assert_source_effect_lineage(
                raw_responses=raw_responses,
                effects=(*official.effects, *odds.effects),
            )
        except DataTorrentRuntimeError as error:
            _durabilize_partial_capture(
                raw_responses=raw_responses,
                errors=({"sport_key": "ALL", "code": str(error)},),
                effects=(*official.effects, *odds.effects),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=odds.provider_receipt,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise
        source_counter_mismatches = sum(
            (
                source_effect_counters.official_physical_reads != official.physical_reads,
                source_effect_counters.odds_dns_resolutions != odds.dns_resolutions,
                source_effect_counters.odds_provider_dispatches != odds.provider_requests,
                source_effect_counters.odds_credits != odds.credits_used,
            )
        )
        if source_counter_mismatches:
            _durabilize_partial_capture(
                raw_responses=raw_responses,
                errors=(
                    {
                        "sport_key": "ALL",
                        "code": "DATA_TORRENT_SOURCE_EFFECT_ACCOUNTING_INVALID",
                    },
                ),
                effects=(*official.effects, *odds.effects),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=odds.provider_receipt,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_SOURCE_EFFECT_ACCOUNTING_INVALID")
        try:
            raw_members = {
                f"responses/{item.response_sequence:03d}-{item.response_id}.bin": item.body
                for item in raw_responses
            }
            raw_entries = [
                item.index_entry(
                    archive_path=(f"responses/{item.response_sequence:03d}-{item.response_id}.bin")
                )
                for item in raw_responses
            ]
            raw_totals: dict[str, Any] = {
                "raw_responses": len(raw_responses),
                "raw_bytes": sum(len(item.body) for item in raw_responses),
                "official_physical_reads": official.physical_reads,
                "odds_provider_requests": odds.provider_requests,
                "odds_credits_used": odds.credits_used,
                "odds_dns_resolutions": odds.dns_resolutions,
                "accounting_status": "PENDING_NORMALIZATION",
            }
            raw_index_core = {
                "schema_version": "robin-data-torrent-real-batch-raw-index-v1",
                "mission_id": MISSION_ID,
                "generated_at_utc": utc_text(datetime.now(UTC)),
                "run_identity": identity.to_json(),
                "claim_identity": claim.opportunity_id,
                "responses": raw_entries,
                "totals": raw_totals,
            }
            raw_members["indexes/raw-index-core-v1.json"] = json_artifact(raw_index_core)
            raw_members["receipts/official-v1.json"] = json_artifact({"reads": official.receipts})
            raw_members["receipts/provider-credit-v1.json"] = json_artifact(odds.provider_receipt)
            raw_archive = deterministic_tar_gz(raw_members)
        except Exception as error:
            _durabilize_partial_capture(
                raw_responses=raw_responses,
                errors=(
                    {
                        "sport_key": "ALL",
                        "code": "DATA_TORRENT_RAW_ARCHIVE_CONSTRUCTION_FAILED",
                    },
                ),
                effects=(*official.effects, *odds.effects),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=odds.provider_receipt,
                observed_responses=tuple(source_progress.observed_responses),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_RAW_ARCHIVE_CONSTRUCTION_FAILED") from error
        try:
            raw_object = upload_immutable_object(
                role="RAW",
                object_key=f"data-torrent/v1/{claim.opportunity_id}/raw.tar.gz",
                payload=raw_archive,
                mission_id=f"{MISSION_ID}-raw-r2",
                identity=identity.github,
                generation_token=generation_token,
                issuer=issuer,
                base_ledger=effect_ledger,
                store=r2_store,
            )
        except Exception as error:
            safe_partial_put = _partial_raw_put_authorized(
                error=error,
                r2_puts=r2_store.puts,
            )
            _durabilize_partial_capture(
                raw_responses=raw_responses,
                errors=(
                    {
                        "sport_key": "ALL",
                        "code": "DATA_TORRENT_RAW_R2_OUTCOME_UNCONFIRMED",
                    },
                ),
                effects=(*official.effects, *odds.effects),
                opportunity_id=claim.opportunity_id,
                identity=identity,
                generation_token=generation_token,
                issuer=issuer,
                effect_ledger=effect_ledger,
                r2_store=r2_store,
                output_dir=output_dir,
                environment=env,
                source_effect_counters=source_effect_counters.snapshot(),
                provider_receipt=odds.provider_receipt,
                observed_responses=tuple(source_progress.observed_responses),
                allow_r2_upload=safe_partial_put,
                recovery_status=(
                    "RAW_R2_FAILED_BEFORE_DISPATCH_PARTIAL_PUT_AUTHORIZED"
                    if safe_partial_put
                    else "RAW_R2_OUTCOME_UNCONFIRMED_NO_RETRY_AUTHORIZED"
                ),
            )
            raise DataTorrentRuntimeError("DATA_TORRENT_RAW_R2_OUTCOME_UNCONFIRMED") from error
        raw_index = {
            **raw_index_core,
            "archive_object": {
                "object_key": raw_object.object_key,
                "bytes": raw_object.object_bytes,
                "sha256": raw_object.object_sha256,
                "media_type": "application/gzip",
                "format": "DETERMINISTIC_USTAR_GZIP_V1",
            },
        }
        run_text = official.raw_responses[0].run_identity
        league_names = {item.sport_key: item.name for item in config.leagues}
        normalized = normalize_batch(
            evidences=evidences,
            raw_responses=raw_responses,
            league_names=league_names,
            requested_markets=config.markets,
            run_identity=run_text,
            claim_identity=claim.opportunity_id,
            team_aliases=team_aliases,
        )
        _assert_meaningful_breadth(
            config=config,
            evidences=evidences,
            batch=normalized,
        )
        capture_ended = datetime.now(UTC)
        replay = _measure_replay(
            config=config,
            raw_archive=raw_archive,
            raw_archive_sha256=raw_object.object_sha256,
            league_names=league_names,
            team_aliases=team_aliases,
            run_identity=run_text,
            claim_identity=claim.opportunity_id,
            anchor=anchor,
            reconciliation_observed_at=reconciliation_observed_at,
            original=normalized,
            capture_started=capture_started,
            capture_ended=capture_ended,
            counter_snapshot=lambda: _effect_counter_snapshot(
                sources=source_effect_counters,
                r2_store=r2_store,
            ),
        )
        if replay.report["status"] != "PASS":
            raise DataTorrentRuntimeError("DATA_TORRENT_LOAD_REPLAY_FAILED")
        normalized = replay.final_batch
        if (
            normalized.silent_drops != 0
            or normalized.logical_duplicates != 0
            or normalized.temporal_leakage != 0
            or replay.report["throughput"]["minimum_ratio"] < config.minimum_throughput_ratio
            or any(replay.report["external_effects_delta"].values())
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_QUALITY_GATES_FAILED")
        lineage = _lineage(raw_responses=raw_responses, batch=normalized)
        lineage_summary = cast(dict[str, Any], lineage["summary"])
        if int(lineage_summary["silent_responses"]) != 0:
            raise DataTorrentRuntimeError("DATA_TORRENT_RAW_LINEAGE_INCOMPLETE")
        raw_totals.update(
            {
                "accounting_status": "COMPLETE",
                "accounted_responses": int(lineage_summary["raw_responses_accounted"]),
                "silent_responses": int(lineage_summary["silent_responses"]),
            }
        )
        coverage_bytes = coverage_csv(normalized.coverage)
        field_dict = field_dictionary(
            mission_id=MISSION_ID,
            generated_at=datetime.now(UTC),
            canonical_dataset_sha256=normalized.canonical_dataset_sha256,
            records=normalized.records,
        )
        hypotheses = hypothesis_backlog(
            canonical_dataset_sha256=normalized.canonical_dataset_sha256,
            coverage=normalized.coverage,
            records=normalized.records,
            rejects=normalized.rejects,
        )
        reject_counts = Counter(str(item["reason"]) for item in normalized.rejects)
        normalized_object_key = f"data-torrent/v1/{claim.opportunity_id}/normalized-evidence.tar.gz"
        normalized_binding = _normalized_evidence_binding(
            opportunity_id=claim.opportunity_id,
            object_key=normalized_object_key,
        )
        expected_live_r2_counters = {
            "puts": 2,
            "gets": 0,
            "lists": 0,
            "deletes": 0,
        }
        mission_r2_counters = _mission_r2_counters(
            proof=chronos_verify_proof,
            live_counters=expected_live_r2_counters,
            live_objects=2,
        )
        quality_core = {
            "schema_version": "robin-data-torrent-quality-report-v1",
            "mission_id": MISSION_ID,
            "generated_at_utc": utc_text(datetime.now(UTC)),
            "run_identity": identity.to_json(),
            "claim_identity": claim.opportunity_id,
            "response_accounting": {
                "observed": int(lineage_summary["raw_responses_observed"]),
                "accounted": int(lineage_summary["raw_responses_accounted"]),
                "silent": int(lineage_summary["silent_responses"]),
            },
            "source_unit_accounting": {
                "observed": normalized.raw_events_observed,
                "accounted": normalized.raw_events_accounted,
                "silent": normalized.silent_drops,
            },
            "rejects_by_reason": [
                {"reason_code": name, "count": count}
                for name, count in sorted(reject_counts.items())
            ],
            "logical_duplicates": normalized.logical_duplicates,
            "temporal": {
                "timezone_missing": 0,
                "backfill": 0,
                "future_information": 0,
                "post_event_as_pre_event": 0,
                "leakage_total": normalized.temporal_leakage,
            },
            "coverage": {
                "expected_cells": 10,
                "emitted_cells": len(normalized.coverage),
                "minimum_fixture_coverage_percentage": (MINIMUM_FIXTURE_COVERAGE_PERCENTAGE),
                "minimum_observed_fixture_coverage_percentage": min(
                    float(item["coverage_percentage"]) for item in normalized.coverage
                ),
                "incomplete_cells": sum(
                    int(item["absence_reason"] != "NONE") for item in normalized.coverage
                ),
            },
            "durability": {"raw_verified": True, "normalized_verified": False},
            "lineage": {
                "raw_responses_covered": int(lineage_summary["raw_responses_accounted"]),
                "normalized_records_covered": len(normalized.records),
                "rejected_units_covered": len(normalized.rejects),
            },
            "replay": {
                "canonical_equality": True,
                "external_reads": 0,
                "report": replay.report,
            },
            "external_effects": {
                "official_source_operations": len(official.effects),
                "official_physical_reads": official.physical_reads,
                "odds_provider_operations": len(odds.effects),
                "odds_dns_resolutions": odds.dns_resolutions,
                "odds_provider_requests": odds.provider_requests,
                "r2_live_operations": sum(expected_live_r2_counters.values()),
                "r2_control_plane_operations": 3,
                "r2_mission_operations": (
                    mission_r2_counters["puts"] + mission_r2_counters["gets"]
                ),
                "r2_objects": mission_r2_counters["objects"],
                "accounted": (
                    official.physical_reads
                    + odds.dns_resolutions
                    + odds.provider_requests
                    + mission_r2_counters["puts"]
                    + mission_r2_counters["gets"]
                ),
                "unaccounted": source_counter_mismatches,
            },
            "gates": [],
            "quality_status": "PASS",
        }
        first_permit_at = min(
            item.permit.db_permitted_at for item in (*official.effects, *odds.effects)
        )
        claim_document = _claim_json(
            opportunity=opportunity,
            receipt=claim,
            identity=identity,
            mission_manifest=mission_manifest,
            config_sha256=config.canonical_sha256,
            first_external_permit_at=first_permit_at,
        )
        claim_document["cross_run_contract_proof"] = post_merge_ci_proof
        claim_document["chronos_release_chain_proof"] = chronos_verify_proof
        replay.report["cross_run_loser_contract_proof"] = post_merge_ci_proof
        replay.report["chronos_release_chain_proof"] = chronos_verify_proof
        measured_replay_report_bytes = json_artifact(replay.report)
        quality = {
            **quality_core,
            "durability": {
                "raw_verified": True,
                "normalized_verified": "CONDITIONAL_APPEND_ONLY_BINDING",
                "normalized_evidence_binding": normalized_binding,
            },
            "gates": [
                {
                    "gate_id": name,
                    "status": "PASS" if passed else "FAIL",
                    "observed": observed,
                    "required": required,
                }
                for name, observed, required, passed in (
                    ("silent_drops", normalized.silent_drops, 0, normalized.silent_drops == 0),
                    (
                        "logical_duplicates",
                        normalized.logical_duplicates,
                        0,
                        normalized.logical_duplicates == 0,
                    ),
                    (
                        "temporal_leakage",
                        normalized.temporal_leakage,
                        0,
                        normalized.temporal_leakage == 0,
                    ),
                    (
                        "replay_multiplier",
                        config.replay_multiplier,
                        100,
                        config.replay_multiplier >= 100,
                    ),
                    (
                        "throughput_ratio",
                        replay.report["throughput"]["minimum_ratio"],
                        config.minimum_throughput_ratio,
                        replay.report["throughput"]["minimum_ratio"]
                        >= config.minimum_throughput_ratio,
                    ),
                    ("unaccounted_external_effects", 0, 0, True),
                )
            ],
        }
        normalized_members = {
            "config/team-alias-registry-v1.json": team_alias_registry_bytes,
            "data/normalized-records.jsonl": normalized.canonical_dataset_bytes,
            "data/rejected-records.jsonl": normalized.rejects_bytes,
            "lineage/raw-to-normalized-v1.json": json_artifact(lineage),
            "reports/coverage-v1.csv": coverage_bytes,
            "reports/load-replay-v1.json": measured_replay_report_bytes,
            "science/field-dictionary-v1.json": json_artifact(field_dict),
            "science/hypothesis-backlog-v1.md": hypotheses.encode("utf-8"),
            "operations/operations-pack-v1.md": operations_pack().encode("utf-8"),
            "operations/recovery-pack-v1.md": recovery_pack().encode("utf-8"),
        }
        if set(normalized_members) != NORMALIZED_CORE_MEMBER_NAMES:
            raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_MEMBER_SET_INVALID")
        normalized_index = {
            "schema_version": "robin-data-torrent-normalized-index-v1",
            "mission_id": MISSION_ID,
            "generated_at_utc": utc_text(datetime.now(UTC)),
            "run_identity": identity.to_json(),
            "claim_identity": claim.opportunity_id,
            "archive_object": normalized_binding,
            "members": artifact_index(normalized_members),
            "canonicalization": {
                "version": "ROBIN_CANONICAL_JSON_LINES_V1",
                "sort_key": "record_id",
                "encoding": "UTF-8",
                "line_ending": "LF",
            },
            "team_aliases": {
                "artifact": TEAM_ALIASES_PATH,
                "archive_member": "config/team-alias-registry-v1.json",
                "entries": len(team_aliases),
                "mapping_sha256": team_aliases_sha256,
                "registry_artifact_sha256": team_alias_registry_sha256,
                "matching_mode": "ONE_HOP_EXACT_ONLY",
            },
            "record_type_counts": [
                {"record_type": name, "records": count}
                for name, count in sorted(
                    Counter(str(item["record_type"]) for item in normalized.records).items()
                )
            ],
            "league_market_counts": list(normalized.coverage),
            "totals": {
                "normalized_records": len(normalized.records),
                "rejected_records": len(normalized.rejects),
                "logical_duplicates": normalized.logical_duplicates,
                "canonical_bytes": len(normalized.canonical_dataset_bytes),
            },
            "canonical_dataset_sha256": normalized.canonical_dataset_sha256,
        }
        r2_inventory = {
            "schema_version": "robin-data-torrent-r2-inventory-v1",
            "objects": [raw_object.to_json(), normalized_binding],
            "counters": {
                "puts": 2,
                "gets": 0,
                "lists": 0,
                "deletes": 0,
                "objects": 2,
                "overwrites": 0,
                "validity": "CONDITIONAL_APPEND_ONLY_BINDING",
            },
            "control_plane_release": chronos_verify_proof["controlled_go"],
            "mission_counters": mission_r2_counters,
            "limits": {
                "puts": config.budgets.r2_puts_max,
                "gets": config.budgets.r2_gets_max,
                "lists": config.budgets.r2_lists_max,
                "deletes": config.budgets.r2_deletes_max,
            },
        }
        control_chain = _safe_events(
            official,
            odds,
            (raw_object,),
            normalized_evidence_binding=normalized_binding,
        )
        canonical_hash = {
            "schema_version": "robin-data-torrent-canonical-dataset-hash-v1",
            "algorithm": "SHA-256",
            "canonicalization": "ROBIN_CANONICAL_JSON_LINES_V1",
            "record_count": len(normalized.records),
            "canonical_bytes": len(normalized.canonical_dataset_bytes),
            "original_sha256": normalized.canonical_dataset_sha256,
            "replay_sha256": replay.final_batch.canonical_dataset_sha256,
            "equality": True,
        }
        artifacts: dict[str, bytes] = {
            "torrent-real-batch-raw-index-v1.json": json_artifact(raw_index),
            "torrent-real-batch-normalized-index-v1.json": json_artifact(normalized_index),
            "torrent-real-batch-quality-report-v1.json": json_artifact(quality),
            "torrent-real-batch-coverage-matrix-v1.csv": coverage_bytes,
            "torrent-load-replay-report-v1.json": measured_replay_report_bytes,
            "torrent-load-replay-report-v1.md": load_replay_markdown(replay.report).encode("utf-8"),
            "torrent-opportunity-claim-receipt-v1.json": json_artifact(claim_document),
            "torrent-control-plane-event-chain-v1.json": json_artifact(control_chain),
            "torrent-official-read-receipts-v1.json": json_artifact(
                {
                    "schema_version": "robin-data-torrent-official-read-receipts-v1",
                    "reads": [item for item in raw_entries if item["family"] != "ODDS"],
                    "total_physical_reads": official.physical_reads,
                    "maximum_physical_reads": config.budgets.official_physical_reads_max,
                    "automatic_retries": 0,
                }
            ),
            "torrent-provider-credit-receipt-v1.json": json_artifact(odds.provider_receipt),
            "torrent-r2-inventory-v1.json": json_artifact(r2_inventory),
            "torrent-raw-to-normalized-lineage-v1.json": json_artifact(lineage),
            "torrent-canonical-dataset-hash-v1.json": json_artifact(canonical_hash),
            "robin-data-torrent-operations-pack-v1.md": operations_pack().encode("utf-8"),
            "robin-data-torrent-recovery-pack-v1.md": recovery_pack().encode("utf-8"),
            "hypothesis-ready-field-dictionary-v1.json": json_artifact(field_dict),
            "hypothesis-backlog-from-real-data-v1.md": hypotheses.encode("utf-8"),
        }
        secret_safety_observed = _secret_scan(artifacts=artifacts, environment=env)
        source_effects = (*official.effects, *odds.effects)
        all_source_effects_confirmed = all(
            item.terminal.event_type == "CONFIRMED" for item in source_effects
        )
        raw_r2_terminal = raw_object.terminal_event in {
            "CREATED_CONFIRMED",
            "PREEXISTING_CONFIRMED",
        }
        first_permit_after_claim = all(
            item.permit.db_permitted_at >= claim.db_claimed_at for item in source_effects
        )
        qa_statuses = {
            "baseline_identity": (
                identity.github.github_sha
                == identity.github.github_workflow_sha
                == identity.post_merge_ci_sha
            ),
            "cross_run_claim": (
                claim.acquired_now
                and claim.opportunity_id == opportunity.opportunity_id
                and claim.winner_github_run_id == identity.github.github_run_id
                and claim.winner_github_run_attempt == identity.github.github_run_attempt
                and first_permit_after_claim
                and all(item.permit.created_now for item in source_effects)
                and post_merge_ci_proof["conclusion"] == "success"
            ),
            "loser_replay_no_reads": (
                all(value == 0 for value in replay.report["external_effects_delta"].values())
                and identity.post_merge_ci_sha == identity.github.github_sha
                and post_merge_ci_proof["cross_run_test_contract"] == CROSS_RUN_CONTRACT
            ),
            "migration_rbac": (
                revision == EXPECTED_REVISION
                and chronos_verify_proof["revision"] == EXPECTED_REVISION
                and chronos_verify_proof["generation_hash"] == expected_generation_hash
            ),
            "production_bindings": [item.username for item in targets]
            == [login for login, _group, _secret_name in SCOPED_LOGINS],
            "ordering_one_shot": (
                first_permit_after_claim
                and identity.github.github_run_attempt == 1
                and all_source_effects_confirmed
            ),
            "ledger_caps": (
                official.physical_reads <= config.budgets.official_physical_reads_max
                and odds.provider_requests <= config.budgets.odds_provider_requests_max
                and odds.credits_used <= config.budgets.odds_credits_max
                and odds.dns_resolutions == len(config.leagues)
                and source_counter_mismatches == 0
                and r2_store.puts == 1
                and config.budgets.r2_puts_max >= 2
                and r2_store.gets == 0
                and r2_store.lists == 0
                and r2_store.deletes == 0
            ),
            "forbidden_effects": (
                config.budgets.automatic_retries == 0
                and config.budgets.r2_deletes_max == 0
                and r2_store.deletes == 0
                and all(
                    env.get(name, "").strip().lower() == expected
                    for name, expected in PRODUCTION_SAFETY_LOCKS.items()
                )
            ),
            "secret_safety": secret_safety_observed,
            "temporal_safety": (normalized.temporal_leakage == 0 and bool(horizon["no_backfill"])),
            "scope_horizon": (
                horizon["selected_days"]
                in {config.primary_horizon_days, config.fallback_horizon_days}
                and int(horizon["selected_fixture_count"]) > 0
            ),
            "official_breadth": (
                len(official.results) == len(config.leagues)
                and not official.errors
                and official.physical_reads > 0
            ),
            "odds_breadth": (
                not odds.errors
                and odds.provider_requests == len(config.leagues)
                and odds.dns_resolutions == len(config.leagues)
                and len(odds.provider_receipt["credit_transitions"]) == len(config.leagues)
                and 0 < odds.credits_used <= config.budgets.odds_credits_max
            ),
            "raw_durability": (
                raw_object.object_bytes > 0
                and raw_r2_terminal
                and cast(dict[str, Any], raw_index["totals"])["raw_responses"] == len(raw_responses)
            ),
            "normalization_lineage": (
                normalized.silent_drops == 0
                and len(normalized.records) > 0
                and int(lineage_summary["silent_responses"]) == 0
                and len(raw_responses) == int(raw_totals["accounted_responses"])
            ),
            "fixture_mapping_coverage": (
                len(normalized.coverage) == len(config.leagues) * len(config.markets)
                and all(item["absence_reason"] == "NONE" for item in normalized.coverage)
                and all(int(item["records_normalized"]) > 0 for item in normalized.coverage)
                and all(
                    int(item["fixtures_captured"]) == int(item["fixtures_available"])
                    for item in normalized.coverage
                )
                and all(
                    float(item["coverage_percentage"]) >= MINIMUM_FIXTURE_COVERAGE_PERCENTAGE
                    for item in normalized.coverage
                )
            ),
            "replay": (
                replay.report["status"] == "PASS"
                and replay.report["acceptance"]["canonical_equality_pass"] is True
            ),
            "load": (
                replay.report["throughput"]["minimum_ratio"] >= config.minimum_throughput_ratio
            ),
            "artifact_closure": (
                set(artifacts)
                | {
                    "torrent-qa-acceptance-matrix-v1.json",
                    "torrent-real-batch-manifest-v1.json",
                }
                == FINAL_ARTIFACT_NAMES
            ),
            "ops_recovery_science": (
                "## HYP-010" in hypotheses
                and "Edge promotion: NO" in hypotheses
                and bool(field_dict["fields"])
            ),
            "ci_merge_postmerge": (
                identity.post_merge_ci_sha == identity.github.github_sha
                and post_merge_ci_proof["head_sha"] == identity.github.github_sha
                and post_merge_ci_proof["conclusion"] == "success"
                and chronos_verify_proof["main_sha"] == identity.github.github_sha
                and chronos_verify_proof["post_merge_ci_sha"] == identity.post_merge_ci_sha
            ),
        }
        qa = qa_matrix(generated_at=datetime.now(UTC), statuses=qa_statuses)
        qa_summary = qa["summary"]
        if qa_summary != {
            "passed": len(qa["gates"]),
            "total": len(qa["gates"]),
            "qa_acceptance_percent": 100,
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }:
            raise DataTorrentRuntimeError("DATA_TORRENT_QA_ACCEPTANCE_FAILED")
        artifacts["torrent-qa-acceptance-matrix-v1.json"] = json_artifact(qa)
        fixtures_available = sum(len(item.fixtures) for item in evidences)
        captured_fixture_ids = {
            str(item["canonical_fixture_id"])
            for item in normalized.records
            if item["record_type"] == "ODDS_OUTCOME"
        }
        manifest = {
            "schema_version": "robin-data-torrent-real-batch-manifest-v1",
            "mission_id": MISSION_ID,
            "generated_at_utc": utc_text(datetime.now(UTC)),
            "status": "SUCCESS",
            "evidence_validity": {
                "mode": "CONDITIONAL_APPEND_ONLY_EXTERNAL_BINDING_V1",
                "binding": normalized_binding,
                "unbound_status": "INVALID",
            },
            "config_sha256": config.canonical_sha256,
            "run_identity": identity.to_json(),
            "post_merge_ci_proof": post_merge_ci_proof,
            "chronos_release_chain_proof": chronos_verify_proof,
            "claim_identity": claim_document,
            "production": {
                "database_revision": revision,
                "runtime_bindings_present": [
                    "CHRONOS_AUTHORITY_DATABASE_URL",
                    "CHRONOS_RUNTIME_DATABASE_URL",
                    "CHRONOS_READER_DATABASE_URL",
                    "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
                ],
                "cloud_runtime": "ubuntu-latest",
            },
            "scope": {
                "season": config.season,
                "region": config.region,
                "leagues_enabled": [
                    {"sport_key": item.sport_key, "name": item.name} for item in config.leagues
                ],
                "markets_enabled": list(config.markets),
                "minimum_fixture_coverage_percentage": (MINIMUM_FIXTURE_COVERAGE_PERCENTAGE),
                "team_aliases": {
                    "artifact": TEAM_ALIASES_PATH,
                    "entries": len(team_aliases),
                    "mapping_sha256": team_aliases_sha256,
                    "registry_artifact_sha256": team_alias_registry_sha256,
                    "matching_mode": "ONE_HOP_EXACT_ONLY",
                },
            },
            "horizon": horizon,
            "execution": {
                "official_batch_status": "SUCCESS",
                "odds_snapshot_status": "SUCCESS",
                "odds_selection_mode": "FULL",
                "automatic_retries": 0,
                "identical_snapshot_attempts": 1,
                "safety_locks": dict(PRODUCTION_SAFETY_LOCKS),
            },
            "counts": {
                "leagues_enabled": len(config.leagues),
                "leagues_with_real_data": len(
                    {item.sport_key for item in evidences if item.fixtures}
                ),
                "fixtures_available": fixtures_available,
                "fixtures_captured": len(captured_fixture_ids),
                "markets_requested": len(config.markets),
                "markets_returned": len(
                    {
                        item["market_key"]
                        for item in normalized.records
                        if item["record_type"] == "ODDS_OUTCOME"
                    }
                ),
                **raw_totals,
                "normalized_records": len(normalized.records),
                "rejected_records": len(normalized.rejects),
                "silent_drops": normalized.silent_drops,
                "logical_duplicates": normalized.logical_duplicates,
                "temporal_leakage": normalized.temporal_leakage,
            },
            "effect_summary": {
                "limits": {
                    **asdict(config.budgets),
                    "odds_dns_resolutions_max": len(config.leagues),
                },
                "actual": {
                    "official_physical_reads": official.physical_reads,
                    "odds_dns_resolutions": odds.dns_resolutions,
                    "odds_provider_requests": odds.provider_requests,
                    "odds_credits_used": odds.credits_used,
                    **mission_r2_counters,
                },
                "unaccounted_external_effects": 0,
            },
            "durability": {
                "raw_object": raw_object.to_json(),
                "normalized_evidence_binding": normalized_binding,
                "verification_status": "VALID_ONLY_WITH_APPEND_ONLY_BINDING",
            },
            "integrity": {
                "raw_response_accounting": "COMPLETE",
                "raw_to_normalized_lineage": "COMPLETE",
                "canonical_replay_equality": True,
                "idempotent_replay": True,
                "temporal_validity": "PASS",
            },
            "artifacts": artifact_index(artifacts),
            "canonical_dataset_sha256": normalized.canonical_dataset_sha256,
            "data_torrent_ready": True,
            "edge_promotions": 0,
            "bet_calls": 0,
        }
        artifacts["torrent-real-batch-manifest-v1.json"] = json_artifact(manifest)
        _secret_scan(artifacts=artifacts, environment=env)
        _secret_scan(artifacts=normalized_members, environment=env)
        normalized_archive = _normalized_evidence_archive(
            normalized_members=normalized_members,
            artifacts=artifacts,
            normalized_binding=normalized_binding,
        )
        normalized_object = upload_immutable_object(
            role="NORMALIZED_EVIDENCE",
            object_key=normalized_object_key,
            payload=normalized_archive,
            mission_id=f"{MISSION_ID}-normalized-evidence-r2",
            identity=identity.github,
            generation_token=generation_token,
            issuer=issuer,
            base_ledger=effect_ledger,
            store=r2_store,
        )
        if (
            normalized_object.role != "NORMALIZED_EVIDENCE"
            or normalized_object.object_key != normalized_object_key
            or normalized_object.object_sha256 != hashlib.sha256(normalized_archive).hexdigest()
            or normalized_object.terminal_event
            not in {"CREATED_CONFIRMED", "PREEXISTING_CONFIRMED"}
            or raw_object.object_key == normalized_object.object_key
            or r2_store.counters() != {"puts": 2, "gets": 0, "lists": 0, "deletes": 0}
        ):
            raise DataTorrentRuntimeError("DATA_TORRENT_NORMALIZED_EVIDENCE_BINDING_FAILED")
        terminal_qa = _verify_terminal_artifact_semantics(
            config=config,
            raw_archive=raw_archive,
            raw_object=raw_object,
            normalized_archive=normalized_archive,
            normalized_object=normalized_object,
            normalized_members=normalized_members,
            artifacts=artifacts,
            normalized_binding=normalized_binding,
            measured_replay_report_bytes=measured_replay_report_bytes,
            league_names=league_names,
            team_aliases=team_aliases,
            identity=identity,
            expected_post_merge_ci_proof=post_merge_ci_proof,
            expected_chronos_verify_proof=chronos_verify_proof,
            expected_revision=revision,
            reader_engine=reader_engine,
            runtime_effects=runtime_effects,
            run_identity=run_text,
            claim_identity=claim.opportunity_id,
            anchor=anchor,
            reconciliation_observed_at=reconciliation_observed_at,
            capture_started=capture_started,
            capture_ended=capture_ended,
            r2_counters=r2_store.counters(),
            environment=env,
        )
        replay_metrics = replay.report["measurement"]
        required_metrics = replay.report["normal_required_throughput"]
        throughput = replay.report["throughput"]
        batch_receipt = PostgresTorrentBatchRecorder(runtime_client).record(
            opportunity_id=claim.opportunity_id,
            raw_operation_id=raw_object.operation_id,
            raw_object_key=raw_object.object_key,
            raw_object_sha256=raw_object.object_sha256,
            normalized_operation_id=normalized_object.operation_id,
            normalized_object_key=normalized_object.object_key,
            normalized_object_sha256=normalized_object.object_sha256,
            canonical_dataset_sha256=normalized.canonical_dataset_sha256,
            manifest=manifest,
            raw_index=raw_index,
            normalized_index=normalized_index,
            quality_report=quality,
            coverage_matrix=list(normalized.coverage),
            official_physical_reads=official.physical_reads,
            odds_provider_requests=odds.provider_requests,
            odds_credits_used=odds.credits_used,
            raw_responses=len(raw_responses),
            raw_bytes=raw_totals["raw_bytes"],
            normalized_records=len(normalized.records),
            rejected_records=len(normalized.rejects),
            silent_drops=normalized.silent_drops,
            logical_duplicates=normalized.logical_duplicates,
            temporal_leakage=normalized.temporal_leakage,
            replay_multiplier=config.replay_multiplier,
            replay_equivalent_records=replay.report["replay"]["equivalent_normalized_records"],
            replay_records_per_second=replay_metrics["records_per_second"],
            replay_bytes_per_second=replay_metrics["bytes_per_second"],
            replay_p50_latency_ms=replay_metrics["p50_latency_ms"],
            replay_p95_latency_ms=replay_metrics["p95_latency_ms"],
            replay_peak_memory_bytes=replay_metrics["peak_memory_bytes"],
            normal_required_records_per_second=required_metrics["records_per_second"],
            normal_required_bytes_per_second=required_metrics["bytes_per_second"],
            throughput_ratio=throughput["minimum_ratio"],
            idempotent_replay=True,
            r2_puts=r2_store.puts,
            r2_gets=r2_store.gets,
            r2_lists=r2_store.lists,
            r2_deletes=r2_store.deletes,
            r2_objects=2,
            automatic_retries=0,
            unaccounted_external_effects=0,
            qa_acceptance_percent=int(qa_summary["qa_acceptance_percent"]),
            p0=int(qa_summary["p0"]),
            p1=int(qa_summary["p1"]),
            p2=int(qa_summary["p2"]),
            open_threads=int(qa_summary["open_threads"]),
            edge_promotions=0,
            bet_calls=0,
            data_torrent_ready=True,
            identity=identity.github,
            generation_token=generation_token,
        )
        if not batch_receipt.created_now:
            raise DataTorrentRuntimeError("DATA_TORRENT_BATCH_REPLAY_FORBIDDEN")
        _assert_recorded_batch_binding(
            reader_engine=reader_engine,
            runtime_effects=runtime_effects,
            opportunity_id=claim.opportunity_id,
            raw_object=raw_object,
            normalized_object=normalized_object,
            canonical_dataset_sha256=normalized.canonical_dataset_sha256,
            record_hash=batch_receipt.record_hash,
            identity=identity,
            expected_counts={
                "official_physical_reads": official.physical_reads,
                "odds_provider_requests": odds.provider_requests,
                "odds_credits_used": odds.credits_used,
                "raw_responses": len(raw_responses),
                "raw_bytes": int(raw_totals["raw_bytes"]),
                "normalized_records": len(normalized.records),
                "rejected_records": len(normalized.rejects),
                "silent_drops": normalized.silent_drops,
                "logical_duplicates": normalized.logical_duplicates,
                "temporal_leakage": normalized.temporal_leakage,
                "replay_multiplier": config.replay_multiplier,
                "replay_equivalent_records": int(
                    replay.report["replay"]["equivalent_normalized_records"]
                ),
                "r2_puts": r2_store.puts,
                "r2_gets": r2_store.gets,
                "r2_lists": r2_store.lists,
                "r2_deletes": r2_store.deletes,
                "r2_objects": 2,
                "automatic_retries": 0,
                "unaccounted_external_effects": 0,
            },
        )
        write_artifacts(output_dir, artifacts)
        return {
            "status": "DATA_TORRENT_READY",
            "data_torrent_ready": True,
            "opportunity_id": claim.opportunity_id,
            "record_hash": batch_receipt.record_hash,
            "canonical_dataset_sha256": normalized.canonical_dataset_sha256,
            "official_physical_reads": official.physical_reads,
            "odds_provider_requests": odds.provider_requests,
            "odds_credits_used": odds.credits_used,
            "raw_responses": len(raw_responses),
            "raw_bytes": raw_totals["raw_bytes"],
            "normalized_records": len(normalized.records),
            "rejected_records": len(normalized.rejects),
            "replay_multiplier": config.replay_multiplier,
            "replay_records_per_second": replay_metrics["records_per_second"],
            "replay_p95_latency_ms": replay_metrics["p95_latency_ms"],
            "replay_peak_memory_bytes": replay_metrics["peak_memory_bytes"],
            "r2": mission_r2_counters,
            "live_r2": r2_store.counters(),
            "terminal_semantic_qa": terminal_qa,
            "runtime_effects": runtime_effects.snapshot(),
            "artifacts": sorted(artifacts),
        }
    finally:
        authority_engine.dispose()
        runtime_engine.dispose()
        reader_engine.dispose()


def execute_data_torrent(
    *,
    repository_root: Path,
    config_path: Path,
    output_dir: Path,
    environment: Mapping[str, str] | None = None,
    system_platform: str = sys.platform,
) -> dict[str, Any]:
    """Attach a complete conservative effect receipt to every terminal failure."""

    runtime_effects = LiveRuntimeEffects()
    token = _LIVE_RUNTIME_EFFECTS.set(runtime_effects)
    try:
        return _execute_data_torrent(
            repository_root=repository_root,
            config_path=config_path,
            output_dir=output_dir,
            environment=environment,
            system_platform=system_platform,
        )
    except Exception as error:
        error.effect_receipt = runtime_effects.snapshot()  # type: ignore[attr-defined]
        raise
    finally:
        _LIVE_RUNTIME_EFFECTS.reset(token)


__all__ = [
    "DataTorrentRuntimeError",
    "EXPECTED_REVISION",
    "LiveRuntimeEffects",
    "MISSION_ID",
    "RuntimeIdentity",
    "execute_data_torrent",
]
