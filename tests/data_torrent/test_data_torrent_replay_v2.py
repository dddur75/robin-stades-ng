from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

import scripts.run_data_torrent_v2 as live_runner
from robin.chronos_production import ChronosProductionError
from robin.data_torrent import reporting, runtime
from robin.data_torrent.live_call_graph import (
    LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2,
    LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2,
    validate_live_postgresql_call_graph_v2,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
EFFECT_CONTRACT = ROOT / "configs" / "execution" / "data-torrent-recovery-v2-effect-contract.json"
SCALE_POLICY = ROOT / "configs" / "experiments" / "scale-policy-v3.json"
V2_WORKFLOWS = {
    "identity": WORKFLOWS / "chronos-neon-branch-identity-v2.yml",
    "seal": WORKFLOWS / "chronos-identity-seal-v2.yml",
    "bootstrap": WORKFLOWS / "chronos-production-bootstrap-v4.yml",
    "live": WORKFLOWS / "data-torrent-live-v2.yml",
}
FULL_ACTION_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
SECRET_REFERENCE = re.compile(r"secrets\.([A-Z][A-Z0-9_]*)")


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _trigger(document: dict[str, Any]) -> dict[str, Any]:
    trigger = document.get("on", document.get(True))
    assert isinstance(trigger, dict)
    return trigger


def _walk(value: object) -> list[object]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_walk(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk(item))
    return values


def _step_names(document: dict[str, Any], job: str) -> list[str]:
    return [str(step.get("name", step.get("uses", ""))) for step in document["jobs"][job]["steps"]]


def test_v2_workflows_are_manual_bounded_and_sha_pinned() -> None:
    for document in map(_load_yaml, V2_WORKFLOWS.values()):
        assert set(_trigger(document)) == {"workflow_dispatch"}
        assert document["permissions"] == {"actions": "read", "contents": "read"}
        assert document["concurrency"] == {
            "group": "chronos-data-torrent-production-global-v1",
            "cancel-in-progress": False,
        }
        uses = [
            value["uses"]
            for value in _walk(document)
            if isinstance(value, dict) and isinstance(value.get("uses"), str)
        ]
        assert uses
        assert all(FULL_ACTION_PIN.fullmatch(item) for item in uses)
        for value in _walk(document):
            if not isinstance(value, dict) or not str(value.get("uses", "")).startswith(
                "actions/checkout@"
            ):
                continue
            assert value["with"]["persist-credentials"] is False
            assert value["with"]["ref"] == "${{ inputs.expected_main_sha }}"

    identity = _load_yaml(V2_WORKFLOWS["identity"])["jobs"]["identity"]
    seal = _load_yaml(V2_WORKFLOWS["seal"])["jobs"]["seal"]
    bootstrap = _load_yaml(V2_WORKFLOWS["bootstrap"])["jobs"]
    live = _load_yaml(V2_WORKFLOWS["live"])["jobs"]
    assert "if" not in identity
    assert "if" not in seal
    assert identity["environment"] == seal["environment"] == "chronos-control-plane-production"
    for name, mode in (("preflight", "PREFLIGHT"), ("migrate", "MIGRATE"), ("verify", "VERIFY")):
        assert bootstrap[name]["needs"] == "validate"
        assert bootstrap[name]["if"] == f"${{{{ always() && inputs.mode == '{mode}' }}}}"
        assert bootstrap[name]["environment"] == "chronos-control-plane-production"
    assert live["torrent"]["needs"] == "validate"
    assert live["torrent"]["if"] == "${{ always() }}"
    assert live["torrent"]["environment"] == "chronos-control-plane-production"


def test_workflow_timeouts_match_scale_policy_and_effect_contract() -> None:
    identity = _load_yaml(V2_WORKFLOWS["identity"])
    seal = _load_yaml(V2_WORKFLOWS["seal"])
    bootstrap = _load_yaml(V2_WORKFLOWS["bootstrap"])
    live = _load_yaml(V2_WORKFLOWS["live"])
    policy = json.loads(SCALE_POLICY.read_bytes())
    levels = {item["id"]: item for item in policy["levels"]}
    contract = json.loads(EFFECT_CONTRACT.read_bytes())

    assert identity["jobs"]["identity"]["timeout-minutes"] == levels["E2"]["max_minutes"] == 10
    assert seal["jobs"]["seal"]["timeout-minutes"] == levels["E2"]["max_minutes"] == 10
    assert bootstrap["jobs"]["validate"]["timeout-minutes"] == 10
    assert bootstrap["jobs"]["preflight"]["timeout-minutes"] == levels["E3A"]["max_minutes_per_job"]
    assert bootstrap["jobs"]["migrate"]["timeout-minutes"] == levels["E3B"]["max_minutes_per_job"]
    assert bootstrap["jobs"]["verify"]["timeout-minutes"] == levels["E3B"]["max_minutes_per_job"]
    assert live["jobs"]["validate"]["timeout-minutes"] == 10
    assert (
        live["jobs"]["torrent"]["timeout-minutes"] == levels["E4"]["absolute_max_minutes_per_job"]
    )
    assert contract["maximum_effect_runtime_seconds"] == 20 * 60
    assert contract["stage_timeout_minutes"] == {
        "POSTMERGE_QUARANTINE": 5,
        "LEGACY_PROVIDER_BRANCH_NEUTRALIZATION": 5,
        "RECOVERY_IDENTITY_V2": 10,
        "DURABLE_IDENTITY_SEAL_V2": 10,
        "PRODUCTION_PREFLIGHT_V2": 15,
        "FOUR_RUNTIME_BINDINGS": 10,
        "MIGRATE_0015": 15,
        "VERIFY_0015": 15,
        "LIVE_ONCE": 20,
        "REPLAY_100": 20,
    }


def test_no_authoritative_github_context_is_synthesized_in_env() -> None:
    for document in map(_load_yaml, V2_WORKFLOWS.values()):
        for value in _walk(document):
            if not isinstance(value, dict) or not isinstance(value.get("env"), dict):
                continue
            forbidden = {
                key for key in value["env"] if key.startswith("GITHUB_") and key != "GITHUB_TOKEN"
            }
            assert forbidden == set()
            if "GITHUB_TOKEN" in value["env"]:
                assert value["env"]["GITHUB_TOKEN"] == "${{ github.token }}"


def test_live_workflow_has_exact_inputs_secrets_and_pre_effect_order() -> None:
    document = _load_yaml(V2_WORKFLOWS["live"])
    inputs = _trigger(document)["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "expected_main_sha",
        "expected_workflow_sha256",
        "expected_mission_manifest_sha256",
        "expected_generation_hash",
        "post_merge_ci_sha",
        "identity_run_id",
        "verify_run_id",
        "recovery_v2_effect_deadline_epoch",
        "recovery_v2_dispatch_nonce",
    }
    assert all(item["required"] is True for item in inputs.values())
    source = V2_WORKFLOWS["live"].read_text(encoding="utf-8")
    assert set(SECRET_REFERENCE.findall(source)) == {
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        "ODDS_API_KEY",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }
    assert "NEON_API_KEY" not in source
    assert "API_FOOTBALL" not in " ".join(SECRET_REFERENCE.findall(source))
    assert '[[ "$EXPECTED_GENERATION_HASH" =~ ^[0-9a-f]{64}$ ]]' in source

    names = _step_names(document, "torrent")
    identity = names.index("Attest download and guard exact R1 identity")
    verify = names.index("Attest and download exact R6 VERIFY")
    hold = names.index("Revalidate protected hold after workflow was disabled")
    main = names.index("Revalidate current main immediately before effects")
    execute = names.index("Execute one LIVE and its in-process replay")
    assert identity < verify < hold < main < execute
    steps = document["jobs"]["torrent"]["steps"]
    identity_step = next(step for step in steps if step.get("name") == names[identity])
    verify_step = next(step for step in steps if step.get("name") == names[verify])
    assert "github_release_attestation_v2.py" in identity_step["run"]
    assert "chronos_live_path_artifact_guard_v2" in identity_step["run"]
    assert "--require-go" in identity_step["run"]
    assert "github_release_attestation_v2.py" in verify_step["run"]
    assert "chronos-production-verify-v2.json" in verify_step["run"]
    for step in steps:
        referenced = set(SECRET_REFERENCE.findall(json.dumps(step)))
        if step.get("name") == names[execute]:
            assert referenced == set(SECRET_REFERENCE.findall(source))
        else:
            assert referenced == set()


def test_identity_has_only_neon_identity_secrets_and_no_business_effects() -> None:
    source = V2_WORKFLOWS["identity"].read_text(encoding="utf-8")
    assert set(SECRET_REFERENCE.findall(source)) == {
        "NEON_API_KEY",
        "NEON_BOOTSTRAP_DATABASE_URL",
    }
    for forbidden in (
        "ODDS_API_KEY",
        "R2_ACCESS_KEY_ID",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "secrets.API_FOOTBALL_KEY",
        'API_FOOTBALL_CALLS_ALLOWED: "1"',
    ):
        assert forbidden not in source


def test_seal_has_only_the_four_r2_secrets() -> None:
    source = V2_WORKFLOWS["seal"].read_text(encoding="utf-8")
    assert set(SECRET_REFERENCE.findall(source)) == {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }


def test_replay_is_in_process_only_and_runner_is_v2_exclusive() -> None:
    assert not (WORKFLOWS / "data-torrent-replay-v2.yml").exists()
    assert not (ROOT / "scripts" / "run_data_torrent_replay_v2.py").exists()
    runner = (ROOT / "scripts" / "run_data_torrent_v2.py").read_text(encoding="utf-8")
    assert "execute_data_torrent_v2(" in runner
    assert "execute_data_torrent(" not in runner
    assert 'configs" / "data" / "torrent-live-v2.json' in runner
    assert "DATA_TORRENT_LOSER_ZERO_POST_CLAIM_EFFECTS" in runner
    assert '"DATA_TORRENT_LOSER_ZERO_EFFECTS"' not in runner


def test_live_runner_never_serializes_untrusted_value_error_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "postgresql://admin:plain-secret@forbidden.example/db"
    monkeypatch.setattr(
        live_runner,
        "execute_data_torrent_v2",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError(secret)),
    )
    monkeypatch.setattr(
        live_runner,
        "_validated_supervised_child_output",
        lambda output_dir, **_kwargs: output_dir,
    )
    monkeypatch.setattr(
        live_runner.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type(
            "Args",
            (),
            {
                "config": tmp_path / "config.json",
                "output_dir": tmp_path,
                "supervised_child": True,
            },
        )(),
    )
    with pytest.raises(SystemExit):
        live_runner.main()
    receipt = (tmp_path / "torrent-run-failure-v2.json").read_text(encoding="utf-8")
    output = capsys.readouterr().out
    assert secret not in receipt
    assert secret not in output
    assert json.loads(receipt)["error_code"] == "DATA_TORRENT_UNCLASSIFIED_FAILURE"


def test_live_runner_preserves_valid_nonzero_effects_from_any_counted_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = live_runner._zero_effects()
    effects["postgresql"]["mutating_function_calls_attempted"] = 2
    effects["postgresql"]["possible_durable_mutations_upper_bound"] = 2
    effects["postgresql"]["connection_attempts_upper_bound"] = 2
    effects["r2"]["puts_attempted"] = 1
    error = ChronosProductionError("DATA_TORRENT_SAFE_FAILURE")
    error.effect_receipt = effects  # type: ignore[attr-defined]
    monkeypatch.setattr(
        live_runner,
        "execute_data_torrent_v2",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        live_runner,
        "_validated_supervised_child_output",
        lambda output_dir, **_kwargs: output_dir,
    )
    monkeypatch.setattr(
        live_runner.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type(
            "Args",
            (),
            {
                "config": tmp_path / "config.json",
                "output_dir": tmp_path,
                "supervised_child": True,
            },
        )(),
    )
    with pytest.raises(SystemExit):
        live_runner.main()
    receipt = json.loads((tmp_path / "torrent-run-failure-v2.json").read_bytes())
    assert receipt["effects"] == effects


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(secret_sentinel="postgresql://secret"),
        lambda value: value["r2"].update(puts_attempted="1"),
        lambda value: value["r2"].update(puts_attempted=-1),
        lambda value: value["r2"].update(automatic_retries=1),
    ],
)
def test_live_runner_rejects_malformed_exception_effect_receipt_without_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    effects = live_runner._zero_effects()
    mutate(effects)
    error = ValueError("DATA_TORRENT_SAFE_FAILURE")
    error.effect_receipt = effects  # type: ignore[attr-defined]
    monkeypatch.setattr(
        live_runner,
        "execute_data_torrent_v2",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        live_runner,
        "_validated_supervised_child_output",
        lambda output_dir, **_kwargs: output_dir,
    )
    monkeypatch.setattr(
        live_runner.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type(
            "Args",
            (),
            {
                "config": tmp_path / "config.json",
                "output_dir": tmp_path,
                "supervised_child": True,
            },
        )(),
    )
    with pytest.raises(SystemExit):
        live_runner.main()
    raw = (tmp_path / "torrent-run-failure-v2.json").read_text(encoding="utf-8")
    assert "postgresql://secret" not in raw
    assert json.loads(raw)["effects"] == live_runner._zero_effects()


def test_live_runner_rejects_malformed_loser_effect_receipt_without_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        live_runner,
        "execute_data_torrent_v2",
        lambda **_kwargs: {
            "data_torrent_ready": False,
            "runtime_effects": {"secret_sentinel": "postgresql://secret"},
        },
    )
    monkeypatch.setattr(
        live_runner,
        "_validated_supervised_child_output",
        lambda output_dir, **_kwargs: output_dir,
    )
    monkeypatch.setattr(
        live_runner.argparse.ArgumentParser,
        "parse_args",
        lambda _self: type(
            "Args",
            (),
            {
                "config": tmp_path / "config.json",
                "output_dir": tmp_path,
                "supervised_child": True,
            },
        )(),
    )
    with pytest.raises(SystemExit):
        live_runner.main()
    raw = (tmp_path / "torrent-run-failure-v2.json").read_text(encoding="utf-8")
    assert "postgresql://secret" not in raw
    assert json.loads(raw)["effects"] == live_runner._zero_effects()


def test_live_supervisor_timeout_leaves_one_valid_maximum_failure_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        live_runner,
        "run_child_once",
        lambda *_args, **_kwargs: live_runner.SUPERVISOR_TIMEOUT_EXIT,
    )
    output_dir = tmp_path / "artifacts"
    failure = tmp_path / "reports" / "torrent-run-failure-v2.json"
    failure.parent.mkdir()
    assert (
        live_runner._supervise(
            config=tmp_path / "config.json",
            output_dir=output_dir,
            failure_report=failure,
        )
        == live_runner.SUPERVISOR_TIMEOUT_EXIT
    )
    document = live_runner._load_guarded_failure(failure)
    assert document["effects"] == live_runner._supervisor_effects()
    assert document["effect_counter_certainty"] == "UNKNOWN_OR_UPPER_BOUND"
    assert not output_dir.exists()


def test_live_supervisor_uses_absent_candidate_leaf_and_rejects_trivial_nineteen_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_runner, "ROOT", tmp_path)

    def child(command: tuple[str, ...], **_kwargs: object) -> int:
        candidate = Path(command[command.index("--output-dir") + 1])
        assert not candidate.exists()
        candidate.mkdir()
        for name in runtime.FINAL_ARTIFACT_NAMES:
            candidate.joinpath(name).write_bytes(
                b"{}\n" if name.endswith(".json") else b"synthetic\n"
            )
        return 0

    monkeypatch.setattr(live_runner, "run_child_once", child)
    output_dir = tmp_path / "artifacts"
    failure = tmp_path / "reports" / "torrent-run-failure-v2.json"
    failure.parent.mkdir()
    assert live_runner._supervise(
        config=tmp_path / "config.json",
        output_dir=output_dir,
        failure_report=failure,
    ) == live_runner.SUPERVISOR_EXPORT_EXIT
    assert not output_dir.exists()
    assert live_runner._load_guarded_failure(failure)["status"] == "FAILED"


def test_live_export_key_guard_allows_only_exact_safe_structural_markers() -> None:
    assert not live_runner._contains_forbidden_export_key(
        {
            "secret_values_observed": False,
            "secret_value_readbacks": 0,
            "password_null": True,
        }
    )
    for mutant in (
        {"secret_values_observed": True},
        {"secret_value_readbacks": 1},
        {"password_null": "true"},
        {"database_url": "postgresql://secret"},
        {"api_key": "secret"},
    ):
        assert live_runner._contains_forbidden_export_key(mutant)


def test_effect_contract_freezes_r4_r5_live_and_replay_boundaries() -> None:
    contract = json.loads(EFFECT_CONTRACT.read_bytes())
    budgets = contract["stage_effect_budgets"]
    assert contract["github_workflow_enable_dispatch_disable_cycles_maximum"] == 6
    assert contract["stage_entrypoints"]["REPLAY_100"] == {
        "kind": "IN_PROCESS_LOCAL_ONLY",
        "path": "src/robin/data_torrent/runtime.py",
        "mode": "REPLAY",
        "parent_stage": "LIVE_ONCE",
        "separate_dispatches": 0,
    }
    assert budgets["FOUR_RUNTIME_BINDINGS"]["invocations"] == 1
    assert budgets["FOUR_RUNTIME_BINDINGS"]["successful_secret_writes"] == 4
    assert budgets["FOUR_RUNTIME_BINDINGS"]["other_secret_writes"] == 0
    assert budgets["FOUR_RUNTIME_BINDINGS"]["secret_value_readbacks"] == 0
    assert budgets["FOUR_RUNTIME_BINDINGS"]["secret_value_logging"] == 0
    assert budgets["FOUR_RUNTIME_BINDINGS"]["global_hold_full_validations"] == 2
    assert budgets["FOUR_RUNTIME_BINDINGS"]["concurrent_run_inventory_validations"] == 4
    assert budgets["FOUR_RUNTIME_BINDINGS"]["github_api_gets_maximum"] == 55
    assert budgets["FOUR_RUNTIME_BINDINGS"]["effect_admission_deadline_seconds"] == 480
    assert budgets["FOUR_RUNTIME_BINDINGS"]["stage_outer_timeout_seconds"] == 600
    assert "dispatches" not in budgets["FOUR_RUNTIME_BINDINGS"]
    assert "run_attempt" not in budgets["FOUR_RUNTIME_BINDINGS"]
    assert budgets["MIGRATE_0015"]["github_workflow_dispatches"] == 1
    assert budgets["MIGRATE_0015"]["migration_execution_dispatches_if_absent"] == 1
    assert budgets["MIGRATE_0015"]["migration_execution_dispatches_if_present"] == 0
    assert budgets["MIGRATE_0015"]["postgresql_connection_attempts_additional_maximum"] == 4
    assert budgets["MIGRATE_0015"]["postgresql_connection_attempts_total_maximum"] == 10
    assert budgets["MIGRATE_0015"]["neon_authority_validation_gets_maximum"] == 26
    assert budgets["MIGRATE_0015"]["neon_mutations"] == 0
    assert budgets["MIGRATE_0015"]["authorized_revision"] == "0015_data_torrent_opportunity"
    assert budgets["MIGRATE_0015"]["sql_statements_maximum"] == 2_048
    assert budgets["MIGRATE_0015"]["sql_writes_maximum"] == 1_024
    assert budgets["VERIFY_0015"]["automatic_retries"] == 0

    live = budgets["LIVE_ONCE"]
    assert live["postgresql_connection_attempts_nominal"] == 51
    assert live["postgresql_connection_attempts_maximum"] == 53
    assert live["postgresql_first_refused_attempt"] == 54
    assert live["postgresql_connection_retries"] == 0
    assert live["leagues"] == 5
    assert live["markets"] == ["h2h", "totals"]
    assert live["official_physical_reads_maximum"] == 50
    assert live["odds_provider_requests_on_success"] == 5
    assert live["odds_credits_maximum"] == 1_000
    assert live["official_retries"] == live["provider_retries"] == live["r2_retries"] == 0
    assert live["r2_gets"] == 1 and live["r2_puts"] == live["r2_objects"] == 2

    replay = budgets["REPLAY_100"]
    assert replay["iterations_exact"] == 100
    assert replay["raw_durable_terminal_event"] == "CREATED_CONFIRMED"
    assert replay["normalized_durable_terminal_event"] == "CREATED_CONFIRMED"
    zero_boundaries = {
        "postgresql_connections",
        "sql_statements",
        "neon_operations",
        "r2_operations",
        "official_reads",
        "provider_requests",
        "secret_writes",
        "purchases",
        "bet_calls",
        "automatic_retries",
        "external_effects",
    }
    assert all(replay[name] == 0 for name in zero_boundaries)
    assert set(contract["terminal_artifacts"]) == set(runtime.FINAL_ARTIFACT_NAMES)


def test_live_postgresql_call_graph_is_generated_and_hash_bound() -> None:
    document = validate_live_postgresql_call_graph_v2(ROOT)
    contract = json.loads(EFFECT_CONTRACT.read_bytes())
    live = contract["stage_effect_budgets"]["LIVE_ONCE"]
    path = ROOT / live["postgresql_call_graph_path"]
    payload = path.read_bytes()
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == live["postgresql_call_graph_raw_sha256"]
    assert hashlib.sha256(canonical).hexdigest() == live["postgresql_call_graph_canonical_sha256"]
    assert LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2 == 51
    assert LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2 == 53
    assert document["derived"]["first_refused_attempt"] == 54


def test_v2_database_engine_uses_null_pool_without_hidden_pre_ping(monkeypatch: Any) -> None:
    observed: dict[str, Any] = {}

    def fake_create_engine(url: object, **kwargs: Any) -> object:
        observed.update({"url": url, **kwargs})
        return object()

    monkeypatch.setattr(runtime, "database_url_object", lambda _value: "validated-url")
    monkeypatch.setattr(runtime.sa, "create_engine", fake_create_engine)
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        runtime._build_live_database_engine("not-observed")
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)

    assert observed == {
        "url": "validated-url",
        "future": True,
        "hide_parameters": True,
        "connect_args": {"connect_timeout": 10},
        "poolclass": runtime.NullPool,
    }


def test_v2_inventory_closes_every_qa_evidence_pointer() -> None:
    config = runtime.load_torrent_config(ROOT / "configs" / "data" / "torrent-live-v2.json")
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        inventory_limits = runtime._r2_inventory_limits(config)
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)

    expected_live_limits = {"puts": 2, "gets": 1, "lists": 0, "deletes": 0}
    assert inventory_limits["limits"] == expected_live_limits
    assert inventory_limits["live_limits"] == expected_live_limits
    assert inventory_limits["mission_limits"] == {
        "puts": 3,
        "gets": 3,
        "objects": 3,
        "lists": 0,
        "deletes": 0,
    }

    qa = reporting.qa_matrix(
        generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        statuses={gate_id: True for gate_id, _priority, _evidence in reporting._QA_GATE_SPECS},
    )
    documents: dict[str, dict[str, Any]] = {
        name: {} for name in runtime.FINAL_ARTIFACT_NAMES if name.endswith(".json")
    }

    def set_pointer(document: dict[str, Any], pointer: str) -> None:
        current: Any = document
        tokens = pointer.removeprefix("/").split("/")
        for index, raw_token in enumerate(tokens):
            token_value = raw_token.replace("~1", "/").replace("~0", "~")
            last = index == len(tokens) - 1
            next_is_index = not last and tokens[index + 1].isdigit()
            if isinstance(current, dict):
                if last:
                    current.setdefault(token_value, True)
                    return
                if token_value not in current or not isinstance(current[token_value], (dict, list)):
                    current[token_value] = [] if next_is_index else {}
                current = current[token_value]
                continue
            position = int(token_value)
            while len(current) <= position:
                current.append({})
            if last:
                current[position] = True
                return
            current = current[position]

    for gate in qa["gates"]:
        for evidence in gate["evidence"]:
            name = evidence["evidence_file"]
            pointer = evidence["evidence_pointer"]
            if pointer and name != "torrent-qa-acceptance-matrix-v1.json":
                set_pointer(documents[name], pointer)

    binding = {"role": "NORMALIZED_EVIDENCE", "terminal_event": "CREATED_CONFIRMED"}
    documents["torrent-r2-inventory-v1.json"].update(inventory_limits)
    documents["torrent-r2-inventory-v1.json"]["objects"] = [{"role": "RAW"}, binding]
    documents["torrent-real-batch-normalized-index-v1.json"]["archive_object"] = binding
    documents["torrent-real-batch-quality-report-v1.json"].setdefault("durability", {})[
        "normalized_evidence_binding"
    ] = binding
    documents["torrent-control-plane-event-chain-v1.json"]["events"] = {
        "external_sources": True,
        "normalized_evidence_terminal_resolver": binding,
    }
    manifest = documents["torrent-real-batch-manifest-v1.json"]
    manifest["evidence_validity"] = {"binding": binding}
    artifacts = {
        name: (
            runtime.json_artifact(qa)
            if name == "torrent-qa-acceptance-matrix-v1.json"
            else runtime.json_artifact(documents[name])
            if name.endswith(".json") and name != "torrent-real-batch-manifest-v1.json"
            else b"synthetic-evidence\n"
        )
        for name in runtime.FINAL_ARTIFACT_NAMES
        if name != "torrent-real-batch-manifest-v1.json"
    }
    manifest["artifacts"] = runtime.artifact_index(artifacts)
    artifacts["torrent-real-batch-manifest-v1.json"] = runtime.json_artifact(manifest)

    runtime._assert_final_artifact_closure(artifacts=artifacts, normalized_binding=binding)
