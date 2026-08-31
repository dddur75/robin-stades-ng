from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.chronos_neon_pure_readonly_preflight_v4 as readonly
import scripts.chronos_production_bootstrap_v3 as bootstrap
import scripts.seal_chronos_controlled_go_v1 as seal
from robin.chronos_production import ChronosProductionError
from robin.prospective_observatory.chronos_control_plane import (
    ConditionalPutOutcome,
    ConditionalPutResult,
    ObservedObject,
)
from tests.activation.test_chronos_neon_controlled_idle_wake_readonly_v1 import (
    _run_synthetic,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "chronos-controlled-go-durable-seal-v1.yml"
EFFECT_CONTRACT = (
    ROOT / "configs" / "execution" / "data-torrent-ready-v1-controlled-go-effect-contract.json"
)
MAIN_SHA = "a" * 40
CONTROLLED_RUN_ID = "1234"
SEAL_RUN_ID = "5678"


class _Store:
    def __init__(self) -> None:
        self.data: bytes | None = None
        self.key = ""
        self.metadata: dict[str, str] = {}
        self.puts = 0
        self.gets = 0

    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: dict[str, str],
        on_dispatch: Any,
    ) -> ConditionalPutResult:
        on_dispatch()
        self.puts += 1
        self.key = key
        self.data = data
        self.metadata = dict(metadata)
        return ConditionalPutResult(
            outcome=ConditionalPutOutcome.CREATED,
            transport_attempts=1,
            automatic_retry_possible=False,
        )

    def get_object(self, key: str) -> ObservedObject | None:
        self.gets += 1
        assert key == self.key
        if self.data is None:
            return None
        return ObservedObject(data=self.data, metadata=self.metadata)


class _RejectedPutStore(_Store):
    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: dict[str, str],
        on_dispatch: Any,
    ) -> ConditionalPutResult:
        del key, data, metadata
        on_dispatch()
        self.puts += 1
        return ConditionalPutResult(
            outcome=ConditionalPutOutcome.PRECONDITION_FAILED,
            transport_attempts=1,
            automatic_retry_possible=False,
        )


class _AmbiguousPutStore(_Store):
    def put_if_absent(
        self,
        key: str,
        data: bytes,
        *,
        metadata: dict[str, str],
        on_dispatch: Any,
    ) -> ConditionalPutResult:
        del key, data, metadata
        on_dispatch()
        self.puts += 1
        return ConditionalPutResult(
            outcome=ConditionalPutOutcome.AMBIGUOUS,
            transport_attempts=1,
            automatic_retry_possible=False,
        )


class _WrongReadbackStore(_Store):
    def get_object(self, key: str) -> ObservedObject | None:
        observed = super().get_object(key)
        if observed is None:
            return None
        return ObservedObject(data=b"wrong-bytes", metadata=observed.metadata)


def _controlled_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, Any]]:
    report = _run_synthetic(monkeypatch)
    path = tmp_path / "controlled.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path, report


def _seal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "GITHUB_REPOSITORY": readonly.EXPECTED_REPOSITORY,
        "GITHUB_REF": readonly.EXPECTED_REF,
        "GITHUB_SHA": MAIN_SHA,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": SEAL_RUN_ID,
        "GITHUB_TOKEN": "synthetic-github-token",
        "R2_ACCOUNT_ID": "synthetic-account",
        "R2_ACCESS_KEY_ID": "synthetic-access",
        "R2_SECRET_ACCESS_KEY": "synthetic-secret",
        "R2_BUCKET_NAME": "synthetic-bucket",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        readonly,
        "_github_actions_state",
        lambda *_args, **_kwargs: (0, 0, 1),
    )
    monkeypatch.setattr(
        readonly,
        "_github_authority_window_dispatch_count",
        lambda *_args, **_kwargs: 1,
    )


def test_seal_is_one_conditional_put_and_one_exact_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _Store()

    receipt = seal.seal_controlled_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        controlled_run_id=CONTROLLED_RUN_ID,
        store=store,  # type: ignore[arg-type]
    )

    digest = hashlib.sha256(controlled_path.read_bytes()).hexdigest()
    assert receipt["verdict"] == "CHRONOS_CONTROLLED_GO_DURABLY_SEALED"
    assert receipt["controlled_go"]["report_sha256"] == digest
    assert receipt["controlled_go"]["durable_readback_sha256"] == digest
    assert receipt["controlled_go"]["conditional_put_outcome"] == "CREATED"
    assert store.puts == 1
    assert store.gets == 1
    assert store.key.endswith(f"report-{digest}.json")
    assert receipt["effects"] == {
        "r2_puts": 1,
        "r2_gets": 1,
        "r2_objects_created": 1,
        "r2_lists": 0,
        "r2_deletes": 0,
        "r2_overwrites": 0,
        "automatic_retries": 0,
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_connections": 0,
        "sql_statements": 0,
        "provider_calls": 0,
        "purchases": 0,
        "sensitive_values_exposed": 0,
    }


def test_non_go_is_rejected_before_any_r2_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, report = _controlled_file(tmp_path, monkeypatch)
    report["verdict"] = readonly.NO_GO_VERDICT
    controlled_path.write_text(json.dumps(report), encoding="utf-8")
    _seal_environment(monkeypatch)
    store = _Store()

    with pytest.raises(ChronosProductionError, match="GO_NOT_PROVEN"):
        seal.seal_controlled_go(
            controlled_path,
            expected_main_sha=MAIN_SHA,
            controlled_run_id=CONTROLLED_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )

    assert store.puts == 0
    assert store.gets == 0


def test_failed_seal_receipt_conservatively_counts_dispatched_r2_put(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _RejectedPutStore()
    effects = seal.SealEffects()

    with pytest.raises(seal.ControlledGoSealError) as caught:
        seal.seal_controlled_go(
            controlled_path,
            expected_main_sha=MAIN_SHA,
            controlled_run_id=CONTROLLED_RUN_ID,
            store=store,  # type: ignore[arg-type]
            effects=effects,
        )

    failure = seal._failure(caught.value, effects)
    assert failure["effects"]["r2_puts"] == 1
    assert failure["effects"]["r2_gets"] == 0
    assert failure["effects"]["r2_objects_created"] == 0
    assert failure["effects"]["r2_objects_created_exact"] is True
    assert failure["effect_counter_certainty"] == ("CONSERVATIVE_DISPATCH_ACCOUNTING")


def test_ambiguous_seal_put_never_reports_zero_created_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _AmbiguousPutStore()
    effects = seal.SealEffects()

    with pytest.raises(
        seal.ControlledGoSealError,
        match="CONTROLLED_GO_SEAL_PUT_NOT_CREATED",
    ) as caught:
        seal.seal_controlled_go(
            controlled_path,
            expected_main_sha=MAIN_SHA,
            controlled_run_id=CONTROLLED_RUN_ID,
            store=store,  # type: ignore[arg-type]
            effects=effects,
        )

    failure = seal._failure(caught.value, effects)
    assert failure["effects"]["r2_puts"] == 1
    assert failure["effects"]["r2_gets"] == 0
    assert failure["effects"]["r2_objects_created"] == 1
    assert failure["effects"]["r2_objects_created_exact"] is False
    assert failure["effect_counter_certainty"] == ("CONSERVATIVE_DISPATCH_ACCOUNTING")


def test_failed_seal_readback_counts_created_object_and_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _WrongReadbackStore()
    effects = seal.SealEffects()

    with pytest.raises(
        seal.ControlledGoSealError,
        match="CONTROLLED_GO_SEAL_READBACK_MISMATCH",
    ) as caught:
        seal.seal_controlled_go(
            controlled_path,
            expected_main_sha=MAIN_SHA,
            controlled_run_id=CONTROLLED_RUN_ID,
            store=store,  # type: ignore[arg-type]
            effects=effects,
        )

    failure = seal._failure(caught.value, effects)
    assert failure["effects"]["r2_puts"] == 1
    assert failure["effects"]["r2_gets"] == 1
    assert failure["effects"]["r2_objects_created"] == 1
    assert failure["effects"]["r2_objects_created_exact"] is True


def test_seal_rechecks_authority_before_readback_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _Store()
    validations = 0

    def expire_before_get() -> None:
        nonlocal validations
        validations += 1
        if validations == 3:
            raise ChronosProductionError("CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED")

    monkeypatch.setattr(seal, "validate_data_torrent_authority", expire_before_get)
    with pytest.raises(
        seal.ControlledGoSealError,
        match="CONTROLLED_GO_SEAL_AUTHORITY_INACTIVE",
    ):
        seal.seal_controlled_go(
            controlled_path,
            expected_main_sha=MAIN_SHA,
            controlled_run_id=CONTROLLED_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )

    assert validations == 3
    assert store.puts == 1
    assert store.gets == 0


def test_bootstrap_revalidates_exact_seal_and_r2_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    store = _Store()
    seal_receipt = seal.seal_controlled_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        controlled_run_id=CONTROLLED_RUN_ID,
        store=store,  # type: ignore[arg-type]
    )
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal_receipt), encoding="utf-8")
    controlled = bootstrap._controlled_readonly_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        expected_run_id=CONTROLLED_RUN_ID,
    )

    binding = bootstrap._controlled_go_durable_binding(
        seal_path,
        controlled_path,
        controlled,
        expected_main_sha=MAIN_SHA,
        expected_controlled_run_id=CONTROLLED_RUN_ID,
        expected_seal_run_id=SEAL_RUN_ID,
        store=store,  # type: ignore[arg-type]
    )

    assert binding["seal_run_id"] == SEAL_RUN_ID
    assert binding["seal_r2_puts"] == 1
    assert binding["seal_r2_gets"] == 1
    assert binding["seal_r2_objects_created"] == 1
    assert binding["preflight_r2_gets"] == 1
    assert binding["compute_wake_events"] == 1
    assert binding["report_sha256"] == binding["preflight_readback_sha256"]
    assert store.gets == 2


def test_bootstrap_rejects_tampered_seal_before_r2_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    seal_store = _Store()
    seal_receipt = seal.seal_controlled_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        controlled_run_id=CONTROLLED_RUN_ID,
        store=seal_store,  # type: ignore[arg-type]
    )
    seal_receipt["effects"]["r2_puts"] = 2
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal_receipt), encoding="utf-8")
    controlled = bootstrap._controlled_readonly_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        expected_run_id=CONTROLLED_RUN_ID,
    )
    readback = _Store()

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_CONTROLLED_GO_DURABILITY_NOT_PROVEN",
    ):
        bootstrap._controlled_go_durable_binding(
            seal_path,
            controlled_path,
            controlled,
            expected_main_sha=MAIN_SHA,
            expected_controlled_run_id=CONTROLLED_RUN_ID,
            expected_seal_run_id=SEAL_RUN_ID,
            store=readback,  # type: ignore[arg-type]
        )

    assert readback.gets == 0


def test_bootstrap_wrong_r2_readback_is_counted_in_failure_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controlled_path, _report = _controlled_file(tmp_path, monkeypatch)
    _seal_environment(monkeypatch)
    seal_store = _Store()
    seal_receipt = seal.seal_controlled_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        controlled_run_id=CONTROLLED_RUN_ID,
        store=seal_store,  # type: ignore[arg-type]
    )
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal_receipt), encoding="utf-8")
    controlled = bootstrap._controlled_readonly_go(
        controlled_path,
        expected_main_sha=MAIN_SHA,
        expected_run_id=CONTROLLED_RUN_ID,
    )
    readback = _Store()
    readback.key = seal_store.key
    readback.data = b"wrong-bytes"
    readback.metadata = dict(seal_store.metadata)
    effects = bootstrap.BootstrapEffects()

    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_CONTROLLED_GO_R2_READBACK_MISMATCH",
    ) as caught:
        bootstrap._controlled_go_durable_binding(
            seal_path,
            controlled_path,
            controlled,
            expected_main_sha=MAIN_SHA,
            expected_controlled_run_id=CONTROLLED_RUN_ID,
            expected_seal_run_id=SEAL_RUN_ID,
            store=readback,  # type: ignore[arg-type]
            effects=effects,
        )

    failure = bootstrap._safe_failure("PREFLIGHT", caught.value, effects)
    assert readback.gets == 1
    assert failure["r2_operations"] == 1


def test_seal_workflow_is_manual_exact_protected_and_bounded() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = document.get("on", document.get(True))
    assert set(on) == {"workflow_dispatch"}
    assert set(on["workflow_dispatch"]["inputs"]) == {
        "expected_main_sha",
        "controlled_run_id",
    }
    assert document["permissions"] == {"actions": "read", "contents": "read"}
    assert document["concurrency"] == {
        "group": "chronos-data-torrent-production-global-v1",
        "cancel-in-progress": False,
    }
    job = document["jobs"]["seal"]
    assert job["environment"] == "chronos-control-plane-production"
    source = WORKFLOW.read_text(encoding="utf-8")
    assert source.count("scripts.github_release_attestation_v1") == 0
    assert source.count("github_release_attestation_v1.py") == 1
    assert source.count("scripts.seal_chronos_controlled_go_v1") == 1
    assert source.count("scripts/check_chronos_github_hold_v3.py") == 1
    assert '--required-successful-ci-sha "$EXPECTED_MAIN_SHA"' in source
    assert source.rindex("git/ref/heads/main") < source.index(
        "python -m scripts.seal_chronos_controlled_go_v1"
    )
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in source
    assert "R2_BUCKET_NAME: ${{ secrets.R2_BUCKET_NAME }}" in source
    assert "list_objects" not in source
    assert "delete_object" not in source
    assert "cache: pip" not in source


def test_owner_bound_effect_contract_names_only_the_exact_new_effects() -> None:
    document = json.loads(EFFECT_CONTRACT.read_text(encoding="utf-8"))
    assert document["parent_manifest_sha256"] == (
        "22e64bb33bd54aeeb528a416c7f6d0ca1c0719a27677302b8065249923ca96e7"
    )
    assert document["owner_directive_source_sha256"] == (
        "c03e218ca8f69d30f3fe998f7534d3edb11e2ba71bdd3ca022ada7ee08a2295d"
    )
    assert document["expands_parent_authority"] is False
    assert document["activation_requirement"] == (
        "APPEND_ONLY_COUNCIL_RELEASE_AND_EXACT_GREEN_FINAL_SHA"
    )
    effects = document["maximum_effect_allocation"]
    assert effects["controlled_workflow_dispatches"] == 1
    assert effects["neon_compute_wake_events"] == 1
    assert effects["postgresql_read_only_connection_attempts"] == 1
    assert effects["controlled_go_r2_immutable_puts"] == 1
    assert effects["controlled_go_r2_readback_gets"] == 2
    assert effects["controlled_go_r2_deletes"] == 0


def test_council_release_is_explicitly_superseding_and_dormant() -> None:
    ledger_path = ROOT / "reports" / "council" / "decision-ledger.jsonl"
    records = [
        json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line
    ]
    records_by_id = {record["decision_id"]: record for record in records}
    failure = records_by_id["RCV3-20260830-190"]
    release = records_by_id["RCV3-20260830-191"]
    correction = records_by_id["RCV3-20260830-192"]
    assert failure["decision_id"] == "RCV3-20260830-190"
    assert failure["decision"] == "BLOCKED_EXTERNAL_ACTION"
    assert failure["context"]["v4_observation"]["idle_proved"] is False
    assert failure["context"]["retry_policy"]["v4_rerun"] == "FORBIDDEN"

    assert release["decision_id"] == "RCV3-20260830-191"
    assert release["decision"] == "PASS_AND_HOLD"
    supersession = release["context"]["temporal_supersession"]
    assert supersession == {
        "superseded_record": "RCV3-20260830-189",
        "superseded_clause": (
            "DISTINCT_APPEND_ONLY_C0_DECISION_CHRONOLOGICALLY_AFTER_DURABLE_READONLY_GO"
        ),
        "replacement": (
            "DISTINCT_PRECOMMITTED_DORMANT_CONDITIONAL_AUTHORITY_"
            "ACTIVATED_ONLY_AFTER_EXACT_DURABLE_EVIDENCE"
        ),
        "rewrites_history": False,
        "expands_parent_owner_authority": False,
    }
    conditional = release["context"]["conditional_release"]
    assert conditional["state_at_record_time"] == "ALL_EXTERNAL_STAGES_DORMANT"
    assert conditional["activation_order"] == [
        "LEGACY_CI_REMAINS_DISABLED",
        "FINAL_PR_EXACT_HEAD_SAFE_CI_GREEN",
        "FINAL_PR_NORMAL_MERGE",
        "FINAL_MAIN_POST_MERGE_SAFE_CI_GREEN",
        "LEGACY_PROVIDER_BRANCH_EQUALS_FINAL_MAIN",
        "GLOBAL_QUIESCENCE",
        "CONTROLLED_READONLY_GO_ONCE",
        "DURABLE_R2_SEAL_ONCE",
        "PREFLIGHT_EXACT_R2_REREAD",
        "INSTALL_FOUR_RUNTIME_BINDINGS",
        "MIGRATE_ADDITIVE_0015",
        "VERIFY",
        "LIVE_DATA_TORRENT_ONCE",
        "INDEPENDENT_TERMINAL_AUDIT",
    ]
    limits = release["context"]["maximum_effect_allocation"]
    assert (limits["mission_r2_puts"], limits["mission_r2_gets"]) == (3, 2)
    assert limits["mission_r2_objects"] == 3
    assert limits["official_physical_reads"] == 50
    assert limits["odds_provider_requests"] == 5
    assert limits["odds_credits"] == 1000
    assert limits["automatic_retries"] == 0
    assert correction["decision"] == "PASS_AND_HOLD"
    failed_ci = correction["context"]["failed_exact_head_ci"]
    assert failed_ci["run_id"] == 33301054721
    assert failed_ci["head_sha"] == "ba0a237bb6fe0c92c929204a5acfa7f2e1b74438"
    assert failed_ci["run_attempt"] == 1
    assert failed_ci["rerun_in_place"] is False
    assert failed_ci["external_production_effects"] == 0

    graph = json.loads(
        (ROOT / "reports" / "evidence" / "evidence-graph.json").read_text(encoding="utf-8")
    )
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    observation_id = (
        "GOV.PRODUCTION.DATA_TORRENT_READY.PREFLIGHT.NEON.V4.ENDPOINT_STATE.NON_ACTIVE.NO_GO.V1.001"
    )
    initial_release_id = (
        "GOV.PRODUCTION.DATA_TORRENT_READY.CONTROLLED_GO.DURABLE_SEAL.CONDITIONAL.RELEASE.V1.001"
    )
    corrected_release_id = (
        "GOV.PRODUCTION.DATA_TORRENT_READY.CONTROLLED_GO.DURABLE_SEAL.CONDITIONAL.RELEASE.V1.002"
    )
    assert claims[observation_id]["status"] == "SUPERSEDED"
    assert claims[observation_id]["superseded_by"] == initial_release_id
    assert claims[initial_release_id]["status"] == "SUPERSEDED"
    assert claims[initial_release_id]["successor_of"] == observation_id
    assert claims[initial_release_id]["superseded_by"] == corrected_release_id
    assert claims[corrected_release_id]["status"] == "VERIFIED"
    assert claims[corrected_release_id]["successor_of"] == initial_release_id
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    for edge_id in (
        "EDGE.806",
        "EDGE.807",
        "EDGE.808",
        "EDGE.809",
        "EDGE.810",
        "EDGE.811",
    ):
        assert edge_id in edges

    previous_hash = records_by_id["RCV3-20260830-189"]["hash"]
    for record in (failure, release, correction):
        assert record["previous_hash"] == previous_hash
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]
        previous_hash = record["hash"]
