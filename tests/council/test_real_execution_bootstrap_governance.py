from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PureWindowsPath

import pytest
from jsonschema import Draft202012Validator

from robin.capture import RealExecutionMissionManifestV1
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1"
START_MAIN = "0591f01c580eb853890e9c1c304a78c21ba9de63"
SOURCE_HASH = "204e4323d0b99fdfa8c655cdc3a08a8d2b3c82ac0a784f9a97982c90ab3a7312"
OLD_SOURCE_HASH = "3d3b43f68c0d339448e52de7ec66cce068646a4a006e267dfe063bffe2767f5e"
OLDER_SOURCE_HASH = "0270bdd51d8d50b7d3c9f608e4f429b46b94b789d92d4b13055b81c9b72e6291"
EXPECTED_CANONICAL_MANIFEST_SHA256 = (
    "d3d570be434b61c0875212061d92419d074b0d8357ba60e55c9f10cd79458e14"
)


def load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_mission_manifest_matches_the_exact_external_effect_boundary() -> None:
    manifest = load("configs/execution/real-execution-bootstrap-closure-v1.json")
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
    effects = manifest["external_effects"]
    assert isinstance(effects, list)
    assert "provider_public_dns_resolution_exactly_once_after_merge" in effects
    assert all("provider_http" not in effect for effect in effects)
    validated = RealExecutionMissionManifestV1.issue(**manifest)
    assert validated.canonical_manifest_sha256() == EXPECTED_CANONICAL_MANIFEST_SHA256
    assert validated.expires_at.isoformat().replace("+00:00", "Z") == ("2026-09-01T20:00:00Z")
    assert validated.external_effects == tuple(effects)

    for historical_source_hash in (OLD_SOURCE_HASH, OLDER_SOURCE_HASH):
        historical = dict(manifest)
        historical["source_hash"] = historical_source_hash
        with pytest.raises(ValueError):
            RealExecutionMissionManifestV1.issue(**historical)

    serialized_effects = json.dumps(effects).casefold()
    assert "provider_http" not in serialized_effects
    assert "provider_tcp" not in serialized_effects
    assert "secret" not in serialized_effects


def test_production_bootstrap_clis_do_not_accept_backdated_timestamps_or_self_pins() -> None:
    forbidden = {
        "tools/data-sourcing/prepare_real_capture_workspace_v1.py": "--prepared-at-utc",
        "tools/data-sourcing/freeze_official_fixture_target_set_v1.py": "--created-at-utc",
        "tools/data-sourcing/select_campaign_window_v1.py": "--selected-at-utc",
        "tools/data-sourcing/build_owner_review_pack_v1.py": "--generated-at-utc",
        "tools/data-sourcing/run_bounded_live_canary_v2.py": "--owner-authorization-sha256",
    }
    for path, argument in forbidden.items():
        assert argument not in (ROOT / path).read_text(encoding="utf-8")
    owner_pack_cli = (ROOT / "tools/data-sourcing/build_owner_review_pack_v1.py").read_text(
        encoding="utf-8"
    )
    dns_cli = (ROOT / "tools/data-sourcing/prepare_provider_network_binding_v1.py").read_text(
        encoding="utf-8"
    )
    assert "--fixture-target-set" not in owner_pack_cli
    assert "--request" not in owner_pack_cli
    assert "--campaign-selection" in owner_pack_cli
    assert "--campaign-selection" in dns_cli
    assert owner_pack_cli.index("paths = write_owner_review_pack_v1") < owner_pack_cli.index(
        "assert_owner_review_pack_completion_current_v1(pack"
    )
    assert "--official-source-content" in (
        ROOT / "tools/data-sourcing/freeze_official_fixture_target_set_v1.py"
    ).read_text(encoding="utf-8")
    for path in (
        "tools/data-sourcing/freeze_official_fixture_target_set_v1.py",
        "tools/data-sourcing/select_campaign_window_v1.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
        "tools/data-sourcing/build_owner_review_pack_v1.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "assert_real_capture_workspace_receipt_current_v1" in source
        assert "assert_workspace_control_artifact_destination_v1" in source
    for path in (
        "tools/data-sourcing/select_campaign_window_v1.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
        "tools/data-sourcing/build_owner_review_pack_v1.py",
        "tools/data-sourcing/run_bounded_live_canary_v2.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        manifest_load = source.index("manifest = load_tracked_real_execution_mission_manifest_v1(")
        effect_boundary = source.index(
            {
                "tools/data-sourcing/select_campaign_window_v1.py": (
                    "selection = CampaignWindowSelectionV1.issue("
                ),
                "tools/data-sourcing/prepare_provider_network_binding_v1.py": (
                    "binding = prepare_provider_network_binding_once_v1("
                ),
                "tools/data-sourcing/build_owner_review_pack_v1.py": (
                    "pack = build_owner_review_pack_v1("
                ),
                "tools/data-sourcing/run_bounded_live_canary_v2.py": (
                    "secret_reader=EnvironmentSecretReader(),"
                ),
            }[path]
        )
        assert manifest_load < effect_boundary


def test_matrix_authorizes_only_ordered_bootstrap_and_owner_candidates() -> None:
    matrix = load("configs/agents/mission-activation-matrix-v3.json")
    authorization = matrix["authorization"]
    assert isinstance(authorization, dict)
    delivery = authorization["real_execution_bootstrap_closure_v1_delivery"]
    effects = authorization["real_execution_bootstrap_closure_v1_effect_budget"]
    ordering = authorization["real_execution_bootstrap_closure_v1_ordering"]
    live = authorization["real_execution_bootstrap_closure_v1_live_boundary"]
    assert f"REQUIRE_EXACT_BASE_{START_MAIN.upper()}" in delivery
    assert "MERGE_COMMIT_ONLY" in delivery
    assert "POST_MERGE_PROVIDER_DNS_RESOLUTION_EXACTLY_1" in effects
    assert "PROVIDER_HTTP_CALLS_0" in effects
    assert "REAL_PROVIDER_SECRET_READS_0" in effects
    assert "ENGINEERING_AND_EXACT_HEAD_CI_AND_THREE_REVIEWS_AND_MERGE_FIRST" in ordering
    assert "STOP_BEFORE_ENVIRONMENT_SECRET_READER_OR_PROVIDER_TRANSPORT" in ordering
    assert "NO_REAL_LIVE_CAPTURE_AUTHORIZED" in live
    mission = matrix["missions"][MISSION_ID]
    assert mission["agents"] == ["C0", "C2", "C4", "DP6"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E1"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
    }
    paths = mission["allowed_paths"]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))


def test_agent_schema_and_three_independent_final_reviews_accept() -> None:
    schema = load("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
    validator = Draft202012Validator(schema)
    paths = (
        "reports/council/real-execution-bootstrap-dp6-review-v3.json",
        "reports/council/real-execution-bootstrap-c4-review-v3.json",
        "reports/council/real-execution-bootstrap-c2-review-v3.json",
    )
    agents: list[str] = []
    for path in paths:
        report = load(path)
        validator.validate(report)
        assert report["mission_id"] == MISSION_ID
        agents.append(str(report["agent_id"]))
    assert agents == ["DP6", "C4", "C2"]
    aggregate = load("reports/council/real-execution-bootstrap-final-review-v3.json")
    assert aggregate["mission_id"] == MISSION_ID
    assert [review["agent_id"] for review in aggregate["reviewers"]] == agents
    assert all(review["verdict"] == "ACCEPT" for review in aggregate["reviewers"])
    assert aggregate["aggregate_gate"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
        "independent_review_count": 3,
        "required_axes_covered": True,
    }
    assert aggregate["verdict"] == "ACCEPT_ENGINEERING_FOR_DRAFT_DELIVERY"
    assert aggregate["real_effects"] == {
        "engineering_provider_dns_resolutions": 0,
        "provider_tcp_connections": 0,
        "provider_http_calls": 0,
        "real_secret_reads": 0,
        "real_capture_calls": 0,
        "real_batch": "NOT_EXECUTED",
        "real_snapshot": "NOT_CREATED",
    }


def test_committed_report_has_zero_real_effects_and_no_local_runtime_paths() -> None:
    report = load("reports/data-sourcing/real-execution-bootstrap-closure-v1.json")
    assert report["starting_main_sha"] == START_MAIN
    for field in (
        "engineering_provider_dns_resolutions",
        "provider_tcp_connections",
        "provider_http_calls",
        "real_secret_reads",
        "real_market_capture_calls",
        "purchases",
        "promotions",
        "bets",
    ):
        assert report[field] == 0
    assert report["real_batch_status"] == "NOT_EXECUTED"
    assert report["real_snapshot_status"] == "NOT_CREATED"
    serialized = json.dumps(report, sort_keys=True)
    assert "C:\\Users\\" not in serialized
    assert "/home/" not in serialized


def test_dns_preparation_tool_has_no_secret_or_transport_capability() -> None:
    paths = (
        "src/robin/capture/provider_network.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
    )
    source = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)
    assert "EnvironmentSecretReader" not in source
    assert "THE_ODDS_API_KEY" not in source
    assert "socket.connect" not in source
    assert "HTTPSConnection" not in source
    assert "requests." not in source


def test_first_c0_single_league_canary_authority_is_additive_and_fail_closed() -> None:
    bootstrap = (ROOT / "src/robin/capture/bootstrap_contracts.py").read_text(encoding="utf-8")
    global_claims = (ROOT / "src/robin/capture/global_claim_boundary.py").read_text(
        encoding="utf-8"
    )
    provider = (ROOT / "src/robin/capture/provider_network.py").read_text(encoding="utf-8")
    predns = (ROOT / "src/robin/capture/predns_orchestration.py").read_text(encoding="utf-8")
    owner_pack = (ROOT / "src/robin/capture/owner_review_pack.py").read_text(encoding="utf-8")
    canary_cli = (ROOT / "tools/data-sourcing/prepare_first_c0_canary_selection_v1.py").read_text(
        encoding="utf-8"
    )
    dns_cli = (ROOT / "tools/data-sourcing/prepare_provider_network_binding_v1.py").read_text(
        encoding="utf-8"
    )
    pack_cli = (ROOT / "tools/data-sourcing/build_owner_review_pack_v1.py").read_text(
        encoding="utf-8"
    )

    assert "class FirstC0CanarySelectionV1(FrozenContract):" in bootstrap
    assert '"robin-first-c0-canary-selection-v1"' in bootstrap
    assert '"single-league-first-real-c0-canary-v1"' in bootstrap
    assert 'Literal["FIRST_REAL_CAPTURE_CANARY_ONLY"]' in bootstrap
    assert (
        "CampaignSelectionAuthorityV1: TypeAlias = "
        "CampaignWindowSelectionV1 | FirstC0CanarySelectionV1"
    ) in bootstrap
    assert "def load_campaign_selection_authority_v1(payload: object)" in bootstrap
    assert 'Field(discriminator="schema_version")' in bootstrap
    assert "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED" in bootstrap
    assert "CAMPAIGN_SELECTION_AUTHORITY_PAYLOAD_INVALID" in bootstrap
    assert "CAMPAIGN_SELECTION_REVISION: Final[" in bootstrap
    assert '"complete-five-league-interval-clique-ranking-v2"' in bootstrap
    assert (
        "CAMPAIGN_RANKING_POLICY: Final[" in bootstrap
        and "cross-league-desc;earliest-readiness-asc;stable-group-hash-asc" in bootstrap
    )
    assert LIVE_ALLOWED_SPORT_KEYS == (
        "soccer_spain_la_liga",
        "soccer_france_ligue_one",
        "soccer_epl",
        "soccer_italy_serie_a",
        "soccer_germany_bundesliga",
    )

    assert canary_cli.count("parser.add_argument(") == 4
    for argument in (
        "--workspace-receipt",
        "--mission-manifest",
        "--source-plan",
        "--output-directory",
    ):
        assert f'parser.add_argument("{argument}"' in canary_cli
    for forbidden_argument in (
        "--skip-five-league",
        "--unsafe-canary",
        "--force",
        "--test-mode",
    ):
        assert forbidden_argument not in canary_cli
        assert forbidden_argument not in dns_cli
        assert forbidden_argument not in pack_cli

    assert 'host != "apim.laliga.com"' in canary_cli
    assert 'parsed.path != "/public-service/api/v1/matches"' in canary_cli
    assert 'query.get("competition") != ["primera-division"]' in canary_cli
    assert 'query.get("limit") != ["100"]' in canary_cli
    assert 'query.get("offset") != ["300"]' in canary_cli
    assert 'host != "datencenter.dfb.de"' in canary_cli
    assert 'parsed.path != "/competitions/12/seasons/current"' in canary_cli
    initial_marker_inspection = canary_cli.index(
        "marker_inspection = inspect_markers_absent_current()"
    )
    first_composite_barrier = canary_cli.index(
        "marker_inspection = inspect_current_pre_dns_authority(output_directory)"
    )
    final_composite_barrier = canary_cli.rindex(
        "marker_inspection = inspect_current_pre_dns_authority(output_directory)"
    )
    final_clock_sample = canary_cli.index("before_fetch_at = _utc(clock()")
    official_fetch = canary_cli.index("fetch_result = fetch_official_schedule_source(")
    assert (
        canary_cli.index("workspace_validator(workspace_receipt)")
        < initial_marker_inspection
        < first_composite_barrier
        < final_clock_sample
        < final_composite_barrier
        < official_fetch
    )
    assert canary_cli.count("_assert_cycle_history_current(") == 3
    assert canary_cli.index(
        "mission_manifest = load_tracked_real_execution_mission_manifest_v1("
    ) < canary_cli.index("result = prepare_first_c0_canary_selection_v1(")
    assert '_PRIMARY_SPORT_KEY = "soccer_spain_la_liga"' in canary_cli
    assert '_FALLBACK_SPORT_KEY = "soccer_germany_bundesliga"' in canary_cli
    assert (
        '_CYCLE_RESERVATION_NAME = "first-c0-canary-cycle-{cycle:02d}-read-reservation-v1.json"'
        in canary_cli
    )
    assert (
        '_CYCLE_RECEIPT_NAME = "first-c0-canary-cycle-{cycle:02d}-attempt-receipt-v1.json"'
        in canary_cli
    )
    assert "_MAXIMUM_PREPARATION_CYCLES = 3" in canary_cli
    assert "_MAXIMUM_OFFICIAL_PHYSICAL_READS = 12" in canary_cli
    assert (
        'receipt.get("status") not in {"SUCCEEDED", "FAILED_BEFORE_DNS", "FAILED_NO_FALLBACK"}'
        in (canary_cli)
    )
    assert 'previous.get("status") == "SUCCEEDED"' in canary_cli
    assert "plan.source.sport_key != _FALLBACK_SPORT_KEY" in canary_cli
    assert "cumulative_official_reads > _MAXIMUM_OFFICIAL_PHYSICAL_READS" in canary_cli
    assert "anticipated_reads > 2" in canary_cli
    assert "EnvironmentSecretReader" not in canary_cli
    assert "THE_ODDS_API_KEY" not in canary_cli
    assert "socket.connect" not in canary_cli
    assert "api.the-odds-api.com" not in canary_cli

    for source in (dns_cli, pack_cli):
        assert "load_campaign_selection_authority_v1" in source
        assert "CampaignWindowSelectionV1.model_validate" not in source
    assert '_RESOLUTION_CLAIM_NAME = "provider-network-resolution-one-shot-v1.json"' in (provider)
    assert 'GLOBAL_CLAIM_ROOT_V2_NAME: Final = "RobinGlobalClaimsV2"' in global_claims
    assert (
        'LEGACY_GLOBAL_CLAIM_ROOT_V1_NAME: Final = "RobinRealExecutionMissionClaimsV1"'
        in global_claims
    )
    for operation in (
        "resolve_owner_execution_boundary_v2",
        "resolve_global_claim_root_candidate_v2",
        "ensure_global_claim_root_v2",
    ):
        assert f"def {operation}(" in global_claims
    for failure_code in (
        "GLOBAL_CLAIM_OWNER_BOUNDARY_UNAVAILABLE",
        "GLOBAL_CLAIM_OWNER_BOUNDARY_MISMATCH",
        "GLOBAL_CLAIM_OWNER_BOUNDARY_UNSAFE",
        "GLOBAL_CLAIM_ROOT_COLLISION",
        "GLOBAL_CLAIM_ROOT_REPARSE_FORBIDDEN",
        "GLOBAL_CLAIM_ROOT_ACL_REQUIRED",
        "GLOBAL_CLAIM_ROOT_IDENTITY_CHANGED",
        "GLOBAL_CLAIM_LEGACY_CONFLICT",
        "GLOBAL_CLAIM_ALREADY_CONSUMED",
    ):
        assert failure_code in global_claims
    for current_consumer in (provider, predns, canary_cli):
        assert (
            "from robin.capture import global_claim_boundary as global_claims" in current_consumer
        )
        assert "LOCALAPPDATA" not in current_consumer
        assert "CSIDL_LOCAL_APPDATA" not in current_consumer
        assert "_MISSION_GLOBAL_CLAIM_ROOT_NAME" not in current_consumer
    assert "reserve_global_claim_marker_v2(" in provider
    assert "reserve_global_claim_marker_v2(" in canary_cli
    assert "assert_global_claim_marker_current_v2(" in provider
    assert "assert_global_claim_marker_current_v2(" in canary_cli
    assert "read_global_claim_marker_pair_v2(" in predns
    assert "_FIRST_C0_CANARY_MINIMUM_PRE_DNS_MARGIN = timedelta(seconds=840)" in provider
    assert "write_owner_review_pack_v1(arguments.output_directory, pack)" in pack_cli
    assert "assert_owner_review_pack_completion_current_v1(pack" in pack_cli
    assert "SELECTION_SCHEMA={selection.schema_version}" in owner_pack
    assert "SELECTION_PURPOSE={selection.purpose}" in owner_pack
    assert "SOURCE_TARGET_SET_COUNT={selection.source_target_set_count}" in owner_pack
    assert "SCIENTIFIC_EDGE_CLAIM={str(selection.scientific_edge_claim).lower()}" in owner_pack

    matrix_payload = (
        (ROOT / "configs/agents/mission-activation-matrix-v3.json")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    assert hashlib.sha256(matrix_payload).hexdigest() == (
        "6777e609247356a9e93fb089a928d25f28c5ba7f9d3fb39a199130d6e866f5ef"
    )


def test_global_claim_boundary_v2_evidence_is_exact_append_only_and_effect_free() -> None:
    base_revision = "2e62496e5efffb564bc8ef8b4ae26e3a76675e44"
    record_token = '"decision_id":"RCV3-20260828-183"'
    expected_files = [
        "docs/data-sourcing/REAL-EXECUTION-BOOTSTRAP-CLOSURE-V1.md",
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "src/robin/capture/global_claim_boundary.py",
        "src/robin/capture/predns_orchestration.py",
        "src/robin/capture/provider_network.py",
        "tests/capture/test_first_c0_canary_selection_v1.py",
        "tests/capture/test_global_claim_boundary_v2.py",
        "tests/capture/test_predns_orchestration_v1.py",
        "tests/capture/test_provider_network_binding.py",
        "tests/council/test_real_execution_bootstrap_governance.py",
        "tools/data-sourcing/prepare_first_c0_canary_selection_v1.py",
    ]
    head_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    base_revision_probe = subprocess.run(
        ["git", "cat-file", "-e", f"{base_revision}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if base_revision_probe.returncode != 0:
        shallow_repository = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert shallow_repository == "true"
        subprocess.run(
            [
                "git",
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                "--unshallow",
                "origin",
                head_revision,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    subprocess.run(
        ["git", "cat-file", "-e", f"{base_revision}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_revision, head_revision],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    introducing_revisions = (
        subprocess.run(
            [
                "git",
                "log",
                "--no-merges",
                "HEAD",
                "--format=%H",
                f"-S{record_token}",
                "--",
                "reports/council/decision-ledger.jsonl",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .splitlines()
    )
    assert len(introducing_revisions) <= 1
    dirty_paths = set(
        subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    dirty_paths.update(
        subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    closure_revision: str | None = None
    # Ambient CI artifacts outside the governed 12-file scope must not replace
    # the immutable base-tree-to-closure-tree proof. In-scope edits still use
    # the precommit worktree path so pending governance changes are fail-closed.
    current_ledger = (ROOT / "reports/council/decision-ledger.jsonl").read_bytes()
    successor_record_token = b'"decision_id":"RCV3-20260829-184"'
    if introducing_revisions and (
        dirty_paths.isdisjoint(expected_files) or successor_record_token in current_ledger
    ):
        first_parent_merges = subprocess.run(
            [
                "git",
                "rev-list",
                "--first-parent",
                "--reverse",
                "--merges",
                f"{base_revision}..{head_revision}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        introducing_merges: list[tuple[str, str, str]] = []
        for merge_revision in first_parent_merges:
            parent_fields = (
                subprocess.run(
                    ["git", "rev-list", "--parents", "-n", "1", merge_revision],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .split()
            )
            if len(parent_fields) != 3:
                continue
            _, first_parent, second_parent = parent_fields
            merge_ledger = subprocess.run(
                ["git", "show", f"{merge_revision}:reports/council/decision-ledger.jsonl"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
            first_parent_ledger = subprocess.run(
                ["git", "show", f"{first_parent}:reports/council/decision-ledger.jsonl"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
            if (
                record_token.encode() in merge_ledger
                and record_token.encode() not in first_parent_ledger
            ):
                introducing_merges.append((merge_revision, first_parent, second_parent))
        closure_search_head = head_revision
        if introducing_merges:
            assert len(introducing_merges) == 1
            merge_revision, first_parent, closure_search_head = introducing_merges[0]
            assert first_parent == base_revision
            merge_tree = subprocess.run(
                ["git", "rev-parse", f"{merge_revision}^{{tree}}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            closure_tree = subprocess.run(
                ["git", "rev-parse", f"{closure_search_head}^{{tree}}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert merge_tree == closure_tree
        candidate_revisions = subprocess.run(
            [
                "git",
                "rev-list",
                "--reverse",
                "--no-merges",
                f"{base_revision}..{closure_search_head}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        assert 1 <= len(candidate_revisions) <= 3
        eligible_closure_revisions: list[str] = []
        for revision in candidate_revisions:
            candidate_ledger = subprocess.run(
                ["git", "show", f"{revision}:reports/council/decision-ledger.jsonl"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
            if record_token.encode() not in candidate_ledger:
                continue
            if len(candidate_ledger.splitlines()) != 176:
                continue
            candidate_paths = subprocess.run(
                ["git", "diff", "--name-only", base_revision, revision],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            if candidate_paths != expected_files:
                continue
            eligible_closure_revisions.append(revision)
        assert eligible_closure_revisions
        closure_revision = eligible_closure_revisions[-1]
        assert closure_revision == closure_search_head
        assert len(introducing_revisions) == 1

    def snapshot_bytes(relative: str) -> bytes:
        if closure_revision is None:
            return (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        payload = subprocess.run(
            ["git", "show", f"{closure_revision}:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        return payload.replace(b"\r\n", b"\n")

    ledger_bytes = snapshot_bytes("reports/council/decision-ledger.jsonl")
    ledger_lines = ledger_bytes.splitlines()
    records = [json.loads(line) for line in ledger_lines]
    assert len(records) == 176
    assert hashlib.sha256(b"\n".join(ledger_lines[:175]) + b"\n").hexdigest() == (
        "6142e12482b97568d0765c491a8e1b7887720e48d36b43b7e54fa3019c7c53b0"
    )
    assert ledger_bytes == b"\n".join(ledger_lines) + b"\n"

    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.033",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.042",
        "GOV.AUTHORIZATION.REAL_EXECUTION_BOOTSTRAP.CLOSURE.MANIFEST.V1.005",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.OWNER_BOUNDARY.V2.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.NETWORK.WINDOWS_API_TYPING.V1.004",
        "GOV.FIRST_C0.PRE_DNS.ORCHESTRATION.V1.004",
        "SECURITY.OWNER_REVIEW_PACK.DATETIME_FIX.ZERO_EFFECTS.V1.008",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.DUAL_ROOT.ZERO_EFFECTS.V2.001",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.013",
    ]
    previous_record = records[-2]
    record = records[-1]
    assert previous_record["decision_id"] == "RCV3-20260827-182"
    assert previous_record["hash"] == (
        "9f75f23b27396584b67cf34b65e5225b885f829e2ba21ef70914f584e26702de"
    )
    assert record["decision_id"] == "RCV3-20260828-183"
    assert record["record_type"] == "DECISION"
    assert record["date"] == "2026-08-28T20:23:05Z"
    assert "RobinGlobalClaimsV2" in record["proposal"]
    assert "one fresh S2/W2 runtime" in record["proposal"]
    assert len(record["objections"]) == 7
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["dissent"] is None
    assert record["responsible"] == "C0"
    assert record["previous_hash"] == previous_record["hash"]
    assert record["proof"] == expected_proof
    canonical_record = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert record["hash_algorithm"] == "SHA-256"
    assert hashlib.sha256(canonical_record).hexdigest() == record["hash"]

    context = record["context"]
    assert context["candidate_context"] is True
    assert context["commit_context"] is False
    assert context["mission_id"] == MISSION_ID
    assert context["phase"] == "GLOBAL_CLAIM_BOUNDARY_V2_PRECOMMIT"
    assert context["base_revision"] == "2e62496e5efffb564bc8ef8b4ae26e3a76675e44"
    assert context["branch"] == "codex/global-claim-boundary-v2"
    assert context["writer_count"] == 1
    assert context["scope"] == {
        "tracked_file_count": 12,
        "tracked_files_maximum": 12,
        "product_or_scientific_change": False,
        "outside_closure": [],
    }
    assert context["files"] == expected_files
    if closure_revision is None:
        tracked_paths = (
            subprocess.run(
                ["git", "diff", "--name-only", context["base_revision"]],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .splitlines()
        )
        untracked_paths = (
            subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .splitlines()
        )
        changed_paths = sorted(set(tracked_paths + untracked_paths))
    else:
        changed_paths = (
            subprocess.run(
                [
                    "git",
                    "diff",
                    "--name-only",
                    context["base_revision"],
                    closure_revision,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .splitlines()
        )
    assert changed_paths == expected_files
    assert context["owner_directive"] == {
        "utf8_bytes": 23127,
        "sha256": "2d30511e1ae2ab9e49ba97fcd0e57d48a93212c96ab5f75b2cf3b8386c09e368",
        "line_endings": "UTF8_LF_NO_BOM",
    }
    assert context["mission_manifest"] == {
        "source_hash": SOURCE_HASH,
        "canonical_sha256": EXPECTED_CANONICAL_MANIFEST_SHA256,
        "artifact_sha256": "05f37235a41331376854e301932d1aac2ddf4486911d0447e1ef5558db4653a4",
        "expires_at_utc": "2026-09-01T20:00:00Z",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
    }
    manifest_payload = snapshot_bytes("configs/execution/real-execution-bootstrap-closure-v1.json")
    assert (
        hashlib.sha256(manifest_payload).hexdigest()
        == context["mission_manifest"]["artifact_sha256"]
    )
    manifest = json.loads(manifest_payload)
    assert manifest["source_hash"] == context["mission_manifest"]["source_hash"]
    assert manifest["expires_at"] == context["mission_manifest"]["expires_at_utc"]
    canonical_manifest = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert (
        hashlib.sha256(canonical_manifest).hexdigest()
        == context["mission_manifest"]["canonical_sha256"]
    )
    assert context["global_claim_boundary_v2"] == {
        "owner_boundary": "<Windows Profile>\\RDS",
        "registry_child": "RobinGlobalClaimsV2",
        "legacy_root": "%LOCALAPPDATA%\\RobinRealExecutionMissionClaimsV1",
        "legacy_write_policy": "FORBIDDEN",
        "legacy_read_compatibility": True,
        "workspace_bound_to_one_physical_registry": True,
        "exclusive_acl_required": True,
        "reparse_forbidden": True,
        "sync_root_forbidden": True,
    }
    assert context["authority_relation"] == {
        "owner_delivery_directive_supersedes_older_matrix_allowlist_for_exact_scope": True,
        "exact_scope_path_count": 12,
        "runtime_manifest_v5_unchanged": True,
        "runtime_authority_expanded": False,
        "provider_dns_authorized_by_this_decision": False,
    }
    assert context["postmerge_runtime_boundary"]["source_stage_preferred"] == (
        "<Windows Profile>\\RDS\\S2"
    )
    assert context["postmerge_runtime_boundary"]["new_runtime_root_preferred"] == (
        "<Windows Profile>\\RDS\\W2"
    )
    effects = context["external_effects"]
    assert effects == {
        "official_schedule_reads": 0,
        "real_preparation_cycles": 0,
        "global_v2_reservation_writes": 0,
        "legacy_reservation_writes": 0,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "real_secret_reads": 0,
        "owner_review_pack_builds": 0,
        "owner_authorizations": 0,
        "c0_calls": 0,
        "captures": 0,
        "promotions": 0,
        "bets": 0,
    }

    graph = json.loads(snapshot_bytes("reports/evidence/evidence-graph.json"))
    assert (
        len(graph["claims"]),
        len(graph["decision_nodes"]),
        len(graph["edges"]),
    ) == (491, 176, 790)
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    base_graph = json.loads(
        subprocess.run(
            [
                "git",
                "show",
                f"{context['base_revision']}:reports/evidence/evidence-graph.json",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    )
    assert (
        len(base_graph["claims"]),
        len(base_graph["decision_nodes"]),
        len(base_graph["edges"]),
    ) == (483, 175, 781)
    assert [claim["claim_id"] for claim in graph["claims"][-8:]] == [
        claim_id for claim_id in expected_proof if claim_id != expected_proof[2]
    ]
    successions = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.032": expected_proof[0],
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.041": expected_proof[1],
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.NETWORK.WINDOWS_API_TYPING.V1.003": (
            expected_proof[4]
        ),
        "GOV.FIRST_C0.PRE_DNS.ORCHESTRATION.V1.003": expected_proof[5],
        "SECURITY.OWNER_REVIEW_PACK.DATETIME_FIX.ZERO_EFFECTS.V1.007": (expected_proof[6]),
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.012": (
            expected_proof[8]
        ),
    }
    for predecessor, successor in successions.items():
        assert claims[predecessor]["status"] == "SUPERSEDED"
        assert claims[predecessor]["superseded_by"] == successor
        assert claims[successor]["successor_of"] == predecessor
    expected_historical_claims = json.loads(json.dumps(base_graph["claims"]))
    expected_historical_by_id = {claim["claim_id"]: claim for claim in expected_historical_claims}
    for predecessor, successor in successions.items():
        expected_historical_by_id[predecessor]["status"] = "SUPERSEDED"
        expected_historical_by_id[predecessor]["superseded_by"] = successor
    assert graph["claims"][:483] == expected_historical_claims
    assert graph["decision_nodes"][:175] == base_graph["decision_nodes"]
    assert graph["edges"][:781] == base_graph["edges"]
    assert claims[expected_proof[2]]["status"] == "VERIFIED"
    new_claim_ids = [claim_id for claim_id in expected_proof if claim_id != expected_proof[2]]
    assert {claim_id: claims[claim_id]["status"] for claim_id in new_claim_ids} == {
        expected_proof[0]: "PARTIAL",
        expected_proof[1]: "PARTIAL",
        expected_proof[3]: "VERIFIED",
        expected_proof[4]: "VERIFIED",
        expected_proof[5]: "VERIFIED",
        expected_proof[6]: "VERIFIED",
        expected_proof[7]: "VERIFIED",
        expected_proof[8]: "VERIFIED",
    }
    for claim_id in new_claim_ids:
        assert claims[claim_id]["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]

    claim_artifacts = {
        expected_proof[0]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[1]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[3]: "src/robin/capture/global_claim_boundary.py",
        expected_proof[4]: "src/robin/capture/provider_network.py",
        expected_proof[5]: "src/robin/capture/predns_orchestration.py",
        expected_proof[6]: "tests/capture/test_first_c0_canary_selection_v1.py",
        expected_proof[7]: "tests/capture/test_global_claim_boundary_v2.py",
        expected_proof[8]: "reports/council/decision-ledger.jsonl",
    }
    for claim_id, relative in claim_artifacts.items():
        payload = snapshot_bytes(relative)
        assert claims[claim_id]["artifact"] == relative
        assert claims[claim_id]["hash"] == hashlib.sha256(payload).hexdigest()
        assert claims[claim_id]["code_revision"] == context["base_revision"]

    assert graph["decision_nodes"][-1] == {
        "decision_id": record["decision_id"],
        "ledger_record_hash": record["hash"],
    }
    expected_edges = [
        {
            "edge_id": f"EDGE.{number}",
            "from_claim_id": claim_id,
            "to_decision_id": record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for number, claim_id in zip(range(782, 791), expected_proof, strict=True)
    ]
    assert graph["edges"][-9:] == expected_edges
    assert [edge["edge_id"] for edge in graph["edges"]] == [
        f"EDGE.{number:03d}" for number in range(1, 791)
    ]
    assert context["reviews_observed"] == {
        "qa_director": "ACCEPT",
        "architecture": "ACCEPT",
        "c4": "ACCEPT",
        "a2": "ACCEPT",
        "red_team": "ACCEPT",
        "dp6_final": "PENDING_AFTER_STATIC",
        "c2_final": "PENDING_AFTER_STATIC",
    }
    assert set(context["defects"].values()) == {0}


def test_owner_rights_acl_compatibility_evidence_is_append_only_and_effect_free() -> None:
    base_revision = "c40f3809d76f7acab54295cf45b685dc8c4190ac"
    start_revision = "5100d6352a10b84b0e4c136d85d17efe03d64dd9"

    def start_bytes(relative: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{start_revision}:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout

    expected_files = [
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "src/robin/capture/workspace_bootstrap.py",
        "tests/capture/test_global_claim_boundary_v2.py",
        "tests/capture/test_real_capture_workspace_bootstrap.py",
        "tests/council/test_real_execution_bootstrap_governance.py",
    ]
    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.034",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.043",
        "GOV.AUTHORIZATION.REAL_EXECUTION_BOOTSTRAP.CLOSURE.MANIFEST.V1.005",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.OWNER_BOUNDARY.V2.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.SETTLEMENT.V1.002",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.REGRESSION.V1.006",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.DUAL_ROOT.ZERO_EFFECTS.V2.002",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.014",
    ]
    supersessions = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.033": expected_proof[0],
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.042": expected_proof[1],
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.SETTLEMENT.V1.001": expected_proof[4],
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.REGRESSION.V1.005": expected_proof[5],
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.DUAL_ROOT.ZERO_EFFECTS.V2.001": (
            expected_proof[6]
        ),
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION."
        "LEDGER.V1.013": expected_proof[7],
    }

    ledger_bytes = start_bytes("reports/council/decision-ledger.jsonl").replace(b"\r\n", b"\n")
    ledger_lines = ledger_bytes.splitlines()
    records = [json.loads(line) for line in ledger_lines]
    assert len(records) == 177
    assert hashlib.sha256(b"\n".join(ledger_lines[:176]) + b"\n").hexdigest() == (
        "c4c78869daa61e953c1566a0c35fb600e5321bb3a99fe2dbbdf6840f17667441"
    )
    assert ledger_bytes == b"\n".join(ledger_lines) + b"\n"
    previous_record, record = records[-2:]
    assert previous_record["decision_id"] == "RCV3-20260828-183"
    assert previous_record["hash"] == (
        "5bf35074a887329257ce5a9d16d7a74e4f1135638a3f6801251d981695b4ae5a"
    )
    assert record["decision_id"] == "RCV3-20260829-184"
    assert record["previous_hash"] == previous_record["hash"]
    assert record["proof"] == expected_proof
    canonical_record = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(canonical_record).hexdigest() == record["hash"]

    context = record["context"]
    assert context["mission_id"] == MISSION_ID
    assert context["phase"] == "OWNER_RIGHTS_ACL_COMPATIBILITY_V1_PRECOMMIT"
    assert context["base_revision"] == base_revision
    assert context["branch"] == "codex/owner-rights-acl-compatibility-v1"
    assert context["writer"] == "C0"
    assert context["writer_count"] == 1
    assert context["files"] == expected_files
    assert context["scope"] == {
        "tracked_file_count": 6,
        "tracked_files_maximum": 6,
        "product_or_scientific_change": False,
        "outside_closure": [],
    }
    assert context["engineering_validation"] == {
        "acl_bit_matrix": {"passed": 33, "status": "PASS"},
        "capture_domain": {"passed": 730, "skipped": 4, "status": "PASS"},
        "capture_domain_last_observed": {"passed": 730, "skipped": 4},
        "council_governance": {"passed": 52, "status": "PASS"},
        "full_repository_suite": {
            "attempts": 2,
            "diagnostic_replay": {"passed": 26, "status": "PASS"},
            "duration_seconds": 1262.93,
            "first_attempt": {
                "failed": 26,
                "passed": 3320,
                "skipped": 29,
                "status": "CHECKOUT_CRLF_ENVIRONMENTAL_FAILURE",
            },
            "passed": 3346,
            "resolution": "LF_CANONICAL_WORKTREE_BYTES_WITH_NO_GOVERNED_SCOPE_EXPANSION",
            "skipped": 29,
            "status": "PASS",
        },
        "principal_files": {"passed": 121, "skipped": 3, "status": "PASS"},
        "static_checks": "PASS",
        "unapproved_network_attempts": 0,
    }
    assert context["owner_directive"] == {
        "raw_bytes": 24899,
        "raw_sha256": ("962a587df46f690577a72179790cd80e04a193f38716d3b5a9061d5634304774"),
        "normalized_utf8_lf_bytes": 23397,
        "normalized_utf8_lf_sha256": (
            "ca8ce9912edc9ed09307c849e8bee8d589914b79cf585ec13bfb934ef67c5590"
        ),
    }
    assert context["mission_manifest"] == {
        "source_hash": ("204e4323d0b99fdfa8c655cdc3a08a8d2b3c82ac0a784f9a97982c90ab3a7312"),
        "canonical_sha256": ("d3d570be434b61c0875212061d92419d074b0d8357ba60e55c9f10cd79458e14"),
        "artifact_sha256": ("05f37235a41331376854e301932d1aac2ddf4486911d0447e1ef5558db4653a4"),
        "expires_at_utc": "2026-09-01T20:00:00Z",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
    }
    assert context["root_cause"] == "CREATOR_VALIDATOR_ACL_SEMANTIC_MISMATCH"
    assert context["secondary_defect"] == {
        "defect": "GENERIC_RIGHTS_STRINGIFICATION_BYPASS",
        "disposition": "CLOSED_BY_EXPLICIT_BITMASK",
        "write_mask_hex": "0x500D0156",
    }
    assert context["acl_policy"] == {
        "owner_check_preserved": True,
        "owner_rights_sid": "S-1-3-4",
        "allowed_write_trustees": [
            "CONCRETE_CURRENT_OWNER_SID",
            "S-1-3-4",
            "S-1-5-18",
            "S-1-5-32-544",
        ],
        "newly_allowed_non_owner_principals": 0,
        "acl_writes": 0,
        "acl_normalization": False,
        "path_special_case": False,
    }
    observed_rds_root = PureWindowsPath("C:/", "Users", "ddura", "RDS")
    assert context["observed_v2_baseline"] == {
        "path": str(observed_rds_root / "RobinGlobalClaimsV2"),
        "owner_sid": "S-1-5-21-247581674-517489618-2716653085-1001",
        "raw_sddl_sha256": ("b60c34520c2307630e80071587188617004f245013cbfb0ffb75100157edeebd"),
        "file_id_decimal": "19984723346564237",
        "entry_count": 0,
        "unchanged": True,
    }
    assert context["external_effects"] == {
        "official_schedule_reads": 0,
        "real_preparation_cycles": 0,
        "global_v2_reservation_writes": 0,
        "legacy_reservation_writes": 0,
        "local_reservation_writes": 0,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "real_secret_reads": 0,
        "owner_review_pack_builds": 0,
        "owner_authorizations": 0,
        "c0_calls": 0,
        "captures": 0,
        "promotions": 0,
        "bets": 0,
    }
    assert context["runtime_preservation"] == {
        "old_runtimes_untouched": True,
        "v2_acl_changed": False,
        "rds_acl_changed": False,
        "localappdata_acl_changed": False,
        "legacy_root_written": False,
        "post_fix_runtime_pending_postmerge": True,
        "stop_before_provider_dns": True,
    }
    assert context["delivery_authority"] == {
        "pull_requests": 1,
        "engineering_commits_maximum": 3,
        "consolidated_ci_cycles_maximum": 3,
        "normal_merge_commit_required": True,
        "exact_head_ci_required": True,
        "postmerge_ci_required": True,
        "force_push_authorized": False,
        "rebase_authorized": False,
        "squash_merge_authorized": False,
    }
    assert context["postmerge_runtime_boundary"] == {
        "new_source_stage": str(observed_rds_root / "S3"),
        "new_runtime_root": str(observed_rds_root / "W3"),
        "create_invocations_maximum": 1,
        "verify_invocations_maximum": 1,
        "preparation_cycles_maximum": 3,
        "official_physical_reads_maximum": 12,
        "identical_retry_forbidden": True,
        "stop_before_provider_dns": True,
    }
    assert context["reviews_observed"] == {
        "qa_director": "ACCEPT",
        "architecture_a2": "ACCEPT",
        "c4": "ACCEPT",
        "red_team": "ACCEPT",
        "c2_final": "ACCEPT",
        "dp6_final": "ACCEPT",
    }
    assert context["outcome_boundary"] == {
        "engineering_candidate_ready": True,
        "pull_request_pending": True,
        "fresh_runtime_pending_postmerge": True,
        "boundary_receipt_pending_postmerge": True,
        "pre_dns_bundle_pending_postmerge": True,
        "owner_launch_kit_pending_postmerge": True,
        "owner_pack_created": False,
        "owner_authorized": False,
        "c0_executed": False,
    }
    assert context["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
        "active_claim_hash_mismatches": 0,
        "broken_successions": 0,
        "broken_ledger_links": 0,
        "duplicate_ids": 0,
        "edge_gaps": 0,
    }

    changed_paths = (
        subprocess.run(
            ["git", "diff", "--name-only", base_revision, start_revision, "--"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert changed_paths == expected_files

    base_graph = json.loads(
        subprocess.run(
            ["git", "show", f"{base_revision}:reports/evidence/evidence-graph.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    )
    graph = json.loads(start_bytes("reports/evidence/evidence-graph.json"))
    assert len(base_graph["claims"]) == 491
    assert len(base_graph["decision_nodes"]) == 176
    assert len(base_graph["edges"]) == 790
    assert len(graph["claims"]) == 497
    assert len(graph["decision_nodes"]) == 177
    assert len(graph["edges"]) == 798
    for before, after in zip(base_graph["claims"], graph["claims"][:491], strict=True):
        if before["claim_id"] not in supersessions:
            assert after == before
            continue
        expected_successor = supersessions[before["claim_id"]]
        assert after == {
            **before,
            "status": "SUPERSEDED",
            "superseded_by": expected_successor,
        }
    assert graph["decision_nodes"][:176] == base_graph["decision_nodes"]
    assert graph["edges"][:790] == base_graph["edges"]

    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    assert [claim["claim_id"] for claim in graph["claims"][-6:]] == [
        expected_proof[index] for index in (0, 1, 4, 5, 6, 7)
    ]
    claim_artifacts = {
        expected_proof[0]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[1]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[4]: "src/robin/capture/workspace_bootstrap.py",
        expected_proof[5]: "tests/capture/test_real_capture_workspace_bootstrap.py",
        expected_proof[6]: "tests/capture/test_global_claim_boundary_v2.py",
        expected_proof[7]: "reports/council/decision-ledger.jsonl",
    }
    for claim_id, relative in claim_artifacts.items():
        payload = start_bytes(relative).replace(b"\r\n", b"\n")
        assert claims[claim_id]["artifact"] == relative
        assert claims[claim_id]["hash"] == hashlib.sha256(payload).hexdigest()
        assert claims[claim_id]["code_revision"] == base_revision
        assert claims[claim_id]["status"] == (
            "PARTIAL" if claim_id in expected_proof[:2] else "VERIFIED"
        )
        assert claims[claim_id]["successor_of"] == next(
            predecessor for predecessor, successor in supersessions.items() if successor == claim_id
        )
        assert claims[claim_id]["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]

    assert graph["decision_nodes"][-1] == {
        "decision_id": record["decision_id"],
        "ledger_record_hash": record["hash"],
    }
    expected_edges = [
        {
            "edge_id": f"EDGE.{number}",
            "from_claim_id": claim_id,
            "to_decision_id": record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for number, claim_id in zip(range(791, 799), expected_proof, strict=True)
    ]
    assert graph["edges"][-8:] == expected_edges
    assert [edge["edge_id"] for edge in graph["edges"]] == [
        f"EDGE.{number:03d}" for number in range(1, 799)
    ]


def test_pr75_final_windows_fixture_closure_evidence_is_append_only_and_effect_free() -> None:
    base_revision = "c40f3809d76f7acab54295cf45b685dc8c4190ac"
    start_revision = "5100d6352a10b84b0e4c136d85d17efe03d64dd9"
    incremental_files = [
        ".github/workflows/ci.yml",
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "tests/capture/test_real_capture_workspace_bootstrap.py",
        "tests/council/test_real_execution_bootstrap_governance.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
    ]
    pull_request_files = [
        ".github/workflows/ci.yml",
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "src/robin/capture/workspace_bootstrap.py",
        "tests/capture/test_global_claim_boundary_v2.py",
        "tests/capture/test_real_capture_workspace_bootstrap.py",
        "tests/council/test_real_execution_bootstrap_governance.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
    ]
    frozen_existing_paths = [
        "src/robin/capture/workspace_bootstrap.py",
        "tests/capture/test_global_claim_boundary_v2.py",
    ]
    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.035",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.044",
        "GOV.AUTHORIZATION.REAL_EXECUTION_BOOTSTRAP.CLOSURE.MANIFEST.V1.005",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.OWNER_BOUNDARY.V2.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.SETTLEMENT.V1.002",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.REGRESSION.V1.007",
        "GOV.CI.REAL_EXECUTION_BOOTSTRAP.CLOSURE.WORKFLOW.V1.003",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.CI.WINDOWS.OWNER_RIGHTS.CONTRACT.V1.001",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.GLOBAL_CLAIM.DUAL_ROOT.ZERO_EFFECTS.V2.002",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.015",
    ]
    supersessions = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.034": expected_proof[0],
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.043": expected_proof[1],
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE."
        "JOB_ACCOUNTING.REGRESSION.V1.006": expected_proof[5],
        "GOV.CI.REAL_EXECUTION_BOOTSTRAP.CLOSURE.WORKFLOW.V1.002": expected_proof[6],
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION."
        "LEDGER.V1.014": expected_proof[9],
    }

    def revision_bytes(revision: str, relative: str) -> bytes:
        return subprocess.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout

    def artifact_sha256(relative: str) -> str:
        payload = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        return hashlib.sha256(payload).hexdigest()

    start_ledger = revision_bytes(start_revision, "reports/council/decision-ledger.jsonl").replace(
        b"\r\n", b"\n"
    )
    ledger_bytes = (
        (ROOT / "reports/council/decision-ledger.jsonl").read_bytes().replace(b"\r\n", b"\n")
    )
    ledger_lines = ledger_bytes.splitlines()
    records = [json.loads(line) for line in ledger_lines]
    assert len(records) == 178
    assert b"\n".join(ledger_lines[:177]) + b"\n" == start_ledger
    assert hashlib.sha256(start_ledger).hexdigest() == (
        "fa9f5dcdd435df1528ad3a8ea7e06bc5dcff723465c7a541677f7a12700c5735"
    )
    assert ledger_bytes == b"\n".join(ledger_lines) + b"\n"
    previous_record, record = records[-2:]
    assert previous_record["decision_id"] == "RCV3-20260829-184"
    assert previous_record["hash"] == (
        "4ac091a327b731d6c5182227e82fe2e30e785298326a121397c81a82327a9f0d"
    )
    assert record["decision_id"] == "RCV3-20260829-185"
    assert record["previous_hash"] == previous_record["hash"]
    assert record["proof"] == expected_proof
    canonical_record = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(canonical_record).hexdigest() == record["hash"]

    context = record["context"]
    assert context["mission_id"] == "PR75_WINDOWS_FIXTURE_CLOSURE_V2"
    assert context["phase"] == "PR75_WINDOWS_FIXTURE_CLOSURE_V2_PRECOMMIT"
    assert context["base_revision"] == base_revision
    assert context["start_pr_head_sha"] == start_revision
    assert context["candidate_parent_sha"] == start_revision
    assert context["branch"] == "codex/owner-rights-acl-compatibility-v1"
    assert context["pr"] == 75
    assert context["writer"] == "ONE_CODEX_DELIVERY_AGENT"
    assert context["writer_count"] == 1
    assert context["files"] == incremental_files
    assert context["pull_request_files"] == pull_request_files
    assert context["scope"] == {
        "closure_changed_paths": 6,
        "frozen_existing_paths": 2,
        "pull_request_changed_paths": 8,
        "tracked_paths_maximum": 8,
        "outside_allowlist": [],
        "product_or_scientific_change": False,
    }
    assert context["owner_directive"] == {
        "raw_bytes": 21813,
        "raw_sha256": "071e9ba887c1ac00d695804124d549345f3257330327a8786c4dfa6d8cbc9679",
        "normalized_utf8_lf_bytes": 21813,
        "normalized_utf8_lf_sha256": (
            "071e9ba887c1ac00d695804124d549345f3257330327a8786c4dfa6d8cbc9679"
        ),
    }
    assert context["causal_evidence"] == {
        "decision": "ACCEPTED_AS_SUFFICIENT_FOR_FIXTURE_ONLY_PATCH",
        "root_cause": "TEST_FIXTURE_CURRENT_OWNER_ACCOUNT_REPRESENTATION_DEFECT",
        "confidence": "HIGH",
        "exact_github_child_return_code": "UNKNOWN_NOT_CLAIMED",
        "production_code_defect_indicated": False,
    }
    assert context["fixture_contract"] == {
        "current_identity": "CHILD_WINDOWS_TOKEN_SID_TO_NTACCOUNT",
        "mismatch_identity": "CHILD_SUPPLIED_SID_TO_NTACCOUNT",
        "positive_round_trip": "TOKEN_SID_TO_NTACCOUNT_TO_PRODUCTION_SID",
        "positive_sanity_diagnostic": "ACL_FIXTURE_INFRASTRUCTURE_FAILED",
        "positive_sanity_precedes_negative_conclusions": True,
        "in_memory": True,
        "subprocess_command_runner_contained": True,
        "acl_writes": 0,
        "provider_access": 0,
    }
    assert context["ci_contract"] == {
        "job": "bounded-live-canary-windows",
        "timeout_minutes": 25,
        "targeted_step": "Vérifier le chemin positif OWNER RIGHTS sous Windows",
        "targeted_shell": "pwsh",
        "targeted_collected_cases": 8,
        "targeted_precedes_full_capture": True,
        "targeted_continue_on_error": False,
        "full_capture_command": "python -m pytest -q tests/capture",
        "full_capture_invocations": 1,
        "permissions": {"contents": "read"},
        "require_windows_storage_links": "1",
        "github_secret_expressions": 0,
    }
    assert context["frozen_paths"] == {
        "src/robin/capture/workspace_bootstrap.py": {
            "start_blob": "451e0701e01375df2661f095e3944278f82cbef6",
            "delta_bytes": 0,
        },
        "tests/capture/test_global_claim_boundary_v2.py": {
            "start_blob": "0e896aa68ab1ae3c2e02c8ae5163feb13a38307f",
            "delta_bytes": 0,
        },
    }
    artifact_paths = (
        ".github/workflows/ci.yml",
        "tests/capture/test_real_capture_workspace_bootstrap.py",
        "tests/council/test_real_execution_bootstrap_governance.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
    )
    assert context["candidate_artifact_hashes"] == {
        relative: artifact_sha256(relative) for relative in artifact_paths
    }
    assert context["delivery_authority"] == {
        "additional_engineering_commits_maximum": 1,
        "total_pr75_engineering_commits_maximum": 4,
        "additional_non_force_pushes_maximum": 1,
        "additional_exact_head_ci_cycles_maximum": 1,
        "automatic_rerun_authorized": False,
        "force_push_authorized": False,
        "new_pull_request_authorized": False,
        "normal_merge_commit_required": True,
        "merge_with_red_ci_authorized": False,
    }
    assert context["validation_contract"] == {
        "ordered_local_gates": [
            "POSITIVE_FIXTURE_SANITY",
            "EXACT_SEVEN",
            "ACL_MATRIX",
            "WINDOWS_MKDIR_0700",
            "PRINCIPAL_FIXTURE_FILE",
            "GLOBAL_CLAIM_BOUNDARY_V2",
            "PORTABILITY_CONTRACT",
            "CAPTURE_DOMAIN",
            "COUNCIL",
            "FULL_REPOSITORY_ONCE",
            "STATIC_SECURITY_MATRIX",
        ],
        "full_repository_suite_invocations_maximum": 1,
        "precommit_status": "ALL_GATES_REQUIRED",
    }
    assert context["external_effects"] == {
        "preparation_cli_invocations": 0,
        "preparation_cycles": 0,
        "official_physical_reads": 0,
        "global_v2_reservation_writes": 0,
        "legacy_reservation_writes": 0,
        "local_reservation_writes": 0,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,
        "owner_pack_builds": 0,
        "owner_authorizations": 0,
        "c0_calls": 0,
        "acl_writes": 0,
    }
    assert context["runtime_preservation"] == {
        "rds_untouched": True,
        "w_untouched": True,
        "w2_untouched": True,
        "v2_root_untouched": True,
        "legacy_root_untouched": True,
        "s3_w3_pending_postmerge_green_ci": True,
        "stop_before_provider_dns": True,
    }
    assert context["reviews_observed"] == {
        "c4": "ACCEPT",
        "architecture_a2": "ACCEPT",
        "red_team": "ACCEPT",
        "ci_portability": "ACCEPT",
        "c2_final": "PENDING_AFTER_LOCAL_GATES",
        "dp6_final": "PENDING_AFTER_LOCAL_GATES",
        "qa_director": "PENDING_AFTER_LOCAL_GATES",
    }
    assert set(context["defects"].values()) == {0}

    incremental_changed_paths = (
        subprocess.run(
            ["git", "diff", "--name-only", start_revision, "--"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert incremental_changed_paths == incremental_files
    pull_request_changed_paths = (
        subprocess.run(
            ["git", "diff", "--name-only", base_revision, "--"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    assert pull_request_changed_paths == pull_request_files
    for relative in frozen_existing_paths:
        assert (ROOT / relative).read_bytes().replace(b"\r\n", b"\n") == revision_bytes(
            start_revision, relative
        ).replace(b"\r\n", b"\n")

    start_graph = json.loads(revision_bytes(start_revision, "reports/evidence/evidence-graph.json"))
    graph = load("reports/evidence/evidence-graph.json")
    assert len(start_graph["claims"]) == 497
    assert len(start_graph["decision_nodes"]) == 177
    assert len(start_graph["edges"]) == 798
    assert len(graph["claims"]) == 503
    assert len(graph["decision_nodes"]) == 178
    assert len(graph["edges"]) == 808
    for before, after in zip(start_graph["claims"], graph["claims"][:497], strict=True):
        if before["claim_id"] not in supersessions:
            assert after == before
            continue
        expected_successor = supersessions[before["claim_id"]]
        assert after == {
            **before,
            "status": "SUPERSEDED",
            "superseded_by": expected_successor,
        }
    assert graph["decision_nodes"][:177] == start_graph["decision_nodes"]
    assert graph["edges"][:798] == start_graph["edges"]

    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    appended_claim_ids = [expected_proof[index] for index in (0, 1, 5, 6, 7, 9)]
    assert [claim["claim_id"] for claim in graph["claims"][-6:]] == appended_claim_ids
    claim_artifacts = {
        expected_proof[0]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[1]: "tests/council/test_real_execution_bootstrap_governance.py",
        expected_proof[5]: "tests/capture/test_real_capture_workspace_bootstrap.py",
        expected_proof[6]: ".github/workflows/ci.yml",
        expected_proof[7]: "tests/portability/test_chronos_portable_ci_contract.py",
        expected_proof[9]: "reports/council/decision-ledger.jsonl",
    }
    for claim_id, relative in claim_artifacts.items():
        assert claims[claim_id]["artifact"] == relative
        assert claims[claim_id]["hash"] == artifact_sha256(relative)
        assert claims[claim_id]["code_revision"] == start_revision
        assert claims[claim_id]["status"] == (
            "PARTIAL" if claim_id in expected_proof[:2] else "VERIFIED"
        )
        if claim_id in supersessions.values():
            assert claims[claim_id]["successor_of"] == next(
                predecessor
                for predecessor, successor in supersessions.items()
                if successor == claim_id
            )
        else:
            assert "successor_of" not in claims[claim_id]
        assert claims[claim_id]["verified_by"] == ["C0", "C2", "C4", "DP6", "A2"]

    assert graph["decision_nodes"][-1] == {
        "decision_id": record["decision_id"],
        "ledger_record_hash": record["hash"],
    }
    expected_edges = [
        {
            "edge_id": f"EDGE.{number}",
            "from_claim_id": claim_id,
            "to_decision_id": record["decision_id"],
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for number, claim_id in zip(range(799, 809), expected_proof, strict=True)
    ]
    assert graph["edges"][-10:] == expected_edges
    assert [edge["edge_id"] for edge in graph["edges"]] == [
        f"EDGE.{number:03d}" for number in range(1, 809)
    ]
