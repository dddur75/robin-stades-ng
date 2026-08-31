from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import scripts.check_chronos_github_hold_v3 as hold_module
import scripts.install_chronos_runtime_bindings_v1 as installer
from robin.chronos_production import (
    ChronosProductionError,
    generation_hash,
    preflight_hash,
    require_generation_bound_password,
)

ROOT = Path(__file__).resolve().parents[2]
MAIN_SHA = "1" * 40
PREFLIGHT_RUN_ID = "123456789"
PROJECT_ID = "project-robin"
PRODUCTION_BRANCH_ID = "branch-production"
RECOVERY_BRANCH_ID = "branch-recovery"
RECOVERY_BRANCH_NAME = "chronos-pre-0015-recovery-20260830T000000Z"
SIGNATURE_VALUE = "f" * 64
REAL_ATTEST_PREFLIGHT = installer._attest_preflight_artifact


def _controlled_go() -> dict[str, object]:
    report_sha = "b" * 64
    return {
        "schema_version": "chronos-controlled-go-binding-v1",
        "workflow_path": (".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml"),
        "run_id": "111",
        "run_attempt": "1",
        "main_sha": MAIN_SHA,
        "report_schema": "chronos-neon-controlled-idle-wake-readonly-v1",
        "report_sha256": report_sha,
        "endpoint_pre_wake_state": "idle",
        "compute_wake_events": 1,
        "postgresql_connection_attempts": 1,
        "production_sql_writes": 0,
        "neon_mutations": 0,
        "durable_store": "R2_IMMUTABLE",
        "conditional_put_outcome": "CREATED",
        "durable_object_key": (
            "data-torrent-ready-v1/control-plane/controlled-go/"
            f"main_sha={MAIN_SHA}/run_id=111/report-{report_sha}.json"
        ),
        "durable_readback_sha256": report_sha,
        "seal_workflow_path": (".github/workflows/chronos-controlled-go-durable-seal-v1.yml"),
        "seal_run_id": "222",
        "seal_run_attempt": "1",
        "seal_receipt_sha256": "c" * 64,
        "seal_r2_puts": 1,
        "seal_r2_gets": 1,
        "seal_r2_objects_created": 1,
        "preflight_readback_sha256": report_sha,
        "preflight_r2_gets": 1,
    }


@pytest.fixture(autouse=True)
def _attest_exact_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    def attested(path: Path, **_values: object) -> tuple[dict[str, object], bytes]:
        return (
            {
                "schema_version": "github-release-artifact-attestation-v1",
                "repository": "dddur75/robin-stades-ng",
                "workflow_path": ".github/workflows/chronos-production-bootstrap-v3.yml",
                "run_id": int(PREFLIGHT_RUN_ID),
                "run_attempt": 1,
                "head_sha": MAIN_SHA,
                "conclusion": "success",
                "artifact_name": f"chronos-preflight-v3-{PREFLIGHT_RUN_ID}",
                "artifact_filename": "chronos-preflight-artifact-v3.json",
            },
            path.read_bytes(),
        )

    monkeypatch.setattr(
        installer,
        "_attest_preflight_artifact",
        attested,
    )
    monkeypatch.setattr(installer, "assert_current_main", lambda **_values: MAIN_SHA)


def _write_preflight(
    path: Path,
    *,
    expires_at: datetime,
    overrides: dict[str, object] | None = None,
    remove: str | None = None,
) -> dict[str, object]:
    artifact: dict[str, object] = {
        "schema_version": "chronos-preflight-artifact-v3",
        "main_sha": MAIN_SHA,
        "workflow_sha": MAIN_SHA,
        "project_id": PROJECT_ID,
        "production_branch_id": PRODUCTION_BRANCH_ID,
        "current_revision": "0014_chronos_control_plane_v2",
        "role_inventory_hash": "a" * 64,
        "role_inventory": {"chronos_reader_login": [False, True]},
        "recovery_branch_id": RECOVERY_BRANCH_ID,
        "recovery_branch_name": RECOVERY_BRANCH_NAME,
        "golden_gate": "CHRONOS_MIGRATION_READY",
        "database_host": "ep-test.eu-central-1.aws.neon.tech",
        "database_port": 5432,
        "database_name": "neondb",
        "sslmode": "require",
        "channel_binding": "require",
        "created_at": (expires_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "preflight_run_attempt": "1",
        "post_merge_ci_sha": MAIN_SHA,
        "controlled_go": _controlled_go(),
        "signature": {
            "algorithm": "HMAC-SHA256",
            "value": SIGNATURE_VALUE,
        },
    }
    artifact.update(overrides or {})
    if remove is not None:
        artifact.pop(remove)
    artifact["preflight_hash"] = preflight_hash(artifact)
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return artifact


def test_installer_sets_only_four_exact_bindings_and_emits_sanitized_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    report_path = tmp_path / "report.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    installed: list[tuple[str, str, str, str]] = []
    generated_passwords = iter(("p" * 64, "q" * 64, "r" * 64))
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_urlsafe",
        lambda _size: next(generated_passwords),
    )
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_hex",
        lambda _size: "ab" * 32,
    )

    def capture_secret(*, name: str, value: str, repository: str, environment: str) -> None:
        installed.append((name, value, repository, environment))

    monkeypatch.setattr(installer, "_set_secret", capture_secret)
    report = installer.install(
        preflight_artifact=preflight,
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id=PREFLIGHT_RUN_ID,
        report_path=report_path,
    )
    assert [name for name, _value, _repository, _environment in installed] == [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    for (_name, value, repository, environment), expected_login in zip(
        installed[:3],
        (
            "chronos_authority_runtime_login",
            "chronos_effect_runtime_login",
            "chronos_reader_login",
        ),
        strict=True,
    ):
        parsed = urlparse(value)
        assert unquote(parsed.username or "") == expected_login
        require_generation_bound_password(
            password=unquote(parsed.password or ""),
            nonce_hex="ab" * 32,
        )
        assert parsed.hostname == "ep-test.eu-central-1.aws.neon.tech"
        assert repository == "dddur75/robin-stades-ng"
        assert environment == "chronos-control-plane-production"
    assert installed[3][1] == "ab" * 32
    assert report["generation_hash"] == generation_hash("ab" * 32)
    assert report["preflight_hash"] == preflight_hash(json.loads(preflight.read_bytes()))
    assert report["preflight_run_id"] == PREFLIGHT_RUN_ID
    assert report["preflight_run_attempt"] == 1
    assert report["current_main_sha_observed"] == MAIN_SHA
    assert report["project_id"] == PROJECT_ID
    assert report["production_branch_id"] == PRODUCTION_BRANCH_ID
    assert report["recovery_branch_id"] == RECOVERY_BRANCH_ID
    assert report["recovery_branch_name"] == RECOVERY_BRANCH_NAME
    assert report["preflight_signature_algorithm"] == "HMAC-SHA256"
    assert report["preflight_artifact_attestation"]["run_id"] == int(PREFLIGHT_RUN_ID)
    assert report["controlled_go"] == _controlled_go()
    persisted = json.loads(report_path.read_bytes())
    serialized = report_path.read_text(encoding="utf-8")
    assert persisted["secret_values_observed"] is False
    assert persisted["secrets_updated"] == [item[0] for item in installed]
    assert all(value not in serialized for _name, value, _repository, _environment in installed)
    assert SIGNATURE_VALUE not in serialized


def test_secret_effect_is_blocked_when_authority_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess_calls = 0

    def closed() -> None:
        raise ChronosProductionError("CHRONOS_MISSION_EFFECT_ADMISSION_CLOSED")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal subprocess_calls
        subprocess_calls += 1

    monkeypatch.setattr(installer, "validate_data_torrent_authority", closed)
    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(
        installer.BindingInstallerError,
        match="CHRONOS_BINDING_MISSION_AUTHORITY_INACTIVE",
    ):
        installer._set_secret(
            name="CHRONOS_RUNTIME_DATABASE_URL",
            value="synthetic",
            repository="dddur75/robin-stades-ng",
            environment="chronos-control-plane-production",
        )
    assert subprocess_calls == 0


def test_installer_partial_write_is_fail_closed_and_emits_recovery_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    report_path = tmp_path / "report.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    generated_passwords = iter(("p" * 64, "q" * 64, "r" * 64))
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_urlsafe",
        lambda _size: next(generated_passwords),
    )
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_hex",
        lambda _size: "cd" * 32,
    )
    attempted: list[tuple[str, str]] = []

    def fail_second(*, name: str, value: str, **_kwargs: str) -> None:
        attempted.append((name, value))
        if len(attempted) == 2:
            raise installer.BindingInstallerError(f"CHRONOS_BINDING_INSTALL_FAILED:{name}")

    monkeypatch.setattr(installer, "_set_secret", fail_second)
    with pytest.raises(installer.BindingInstallerError, match="CHRONOS_BINDING_INSTALL_FAILED"):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
            report_path=report_path,
        )

    receipt = json.loads(report_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED"
    assert receipt["secret_updates_attempted"] == [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
    ]
    assert receipt["secrets_updated_confirmed"] == ["CHRONOS_AUTHORITY_DATABASE_URL"]
    assert receipt["secret_updates_possible"] == ["CHRONOS_RUNTIME_DATABASE_URL"]
    assert receipt["activation_secret_update_confirmed"] is False
    assert receipt["activation_secret_update_possible"] is False
    assert receipt["partial_generation_can_be_active"] is False
    assert receipt["activation_state_certainty"] == ("NEW_GENERATION_NOT_ACTIVATED_BY_THIS_ATTEMPT")
    assert receipt["generation_hash"] == generation_hash("cd" * 32)
    serialized = report_path.read_text(encoding="utf-8")
    assert "cd" * 32 not in serialized
    assert all(value not in serialized for _name, value in attempted)


def test_installer_ambiguous_commit_marker_reports_possible_complete_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    report_path = tmp_path / "report.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_urlsafe",
        lambda _size: "s" * 64,
    )
    monkeypatch.setattr(
        "scripts.install_chronos_runtime_bindings_v1.secrets.token_hex",
        lambda _size: "ef" * 32,
    )
    attempted_values: list[str] = []

    def ambiguous_marker(*, name: str, value: str, **_kwargs: str) -> None:
        attempted_values.append(value)
        if name == "CHRONOS_CONTROL_PLANE_GENERATION_NONCE":
            raise installer.BindingInstallerError(f"CHRONOS_BINDING_INSTALL_FAILED:{name}")

    monkeypatch.setattr(installer, "_set_secret", ambiguous_marker)
    with pytest.raises(installer.BindingInstallerError, match="CHRONOS_BINDING_INSTALL_FAILED"):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
            report_path=report_path,
        )

    receipt = json.loads(report_path.read_text(encoding="utf-8"))
    assert receipt["secret_updates_attempted"] == [
        "CHRONOS_AUTHORITY_DATABASE_URL",
        "CHRONOS_RUNTIME_DATABASE_URL",
        "CHRONOS_READER_DATABASE_URL",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
    ]
    assert receipt["secrets_updated_confirmed"] == receipt["secret_updates_attempted"][:3]
    assert receipt["secret_updates_possible"] == ["CHRONOS_CONTROL_PLANE_GENERATION_NONCE"]
    assert receipt["activation_secret_update_possible"] is True
    assert receipt["partial_generation_can_be_active"] is False
    assert receipt["activation_state_certainty"] == ("UNKNOWN_PREVIOUS_OR_COMPLETE_NEW_GENERATION")
    serialized = report_path.read_text(encoding="utf-8")
    assert all(value not in serialized for value in attempted_values)


def test_installer_refuses_expired_preflight_before_any_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "expired.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    calls = 0

    def capture_secret(*, name: str, value: str, repository: str, environment: str) -> None:
        del name, value, repository, environment
        nonlocal calls
        calls += 1

    monkeypatch.setattr(installer, "_set_secret", capture_secret)
    with pytest.raises(installer.BindingInstallerError, match="CHRONOS_BINDING_PREFLIGHT_EXPIRED"):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
            report_path=tmp_path / "report.json",
        )
    assert calls == 0


@pytest.mark.parametrize(
    ("overrides", "expected_run_id", "error"),
    (
        ({"preflight_run_id": "987654321"}, PREFLIGHT_RUN_ID, "RUN_MISMATCH"),
        ({"preflight_run_attempt": "2"}, PREFLIGHT_RUN_ID, "RUN_MISMATCH"),
        ({"project_id": ""}, PREFLIGHT_RUN_ID, "IDENTITY_INVALID"),
        (
            {"recovery_branch_id": PRODUCTION_BRANCH_ID},
            PREFLIGHT_RUN_ID,
            "IDENTITY_INVALID",
        ),
        (
            {"recovery_branch_name": "recovery-branch-unbound"},
            PREFLIGHT_RUN_ID,
            "IDENTITY_INVALID",
        ),
        (
            {"signature": {"algorithm": "HMAC-SHA256", "value": "F" * 64}},
            PREFLIGHT_RUN_ID,
            "SIGNATURE_INVALID",
        ),
        (
            {
                "signature": {
                    "algorithm": "HMAC-SHA256",
                    "value": SIGNATURE_VALUE,
                    "key_id": "forbidden",
                }
            },
            PREFLIGHT_RUN_ID,
            "SIGNATURE_INVALID",
        ),
        ({"unexpected_field": "forbidden"}, PREFLIGHT_RUN_ID, "SCHEMA_MISMATCH"),
    ),
)
def test_installer_rejects_untrusted_provenance_before_any_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    expected_run_id: str,
    error: str,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(
        preflight,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        overrides=overrides,
    )
    calls = 0

    def capture_secret(*, name: str, value: str, repository: str, environment: str) -> None:
        del name, value, repository, environment
        nonlocal calls
        calls += 1

    monkeypatch.setattr(installer, "_set_secret", capture_secret)
    with pytest.raises(installer.BindingInstallerError, match=f"CHRONOS_BINDING_PREFLIGHT_{error}"):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=expected_run_id,
            report_path=tmp_path / "report.json",
        )
    assert calls == 0


@pytest.mark.parametrize(
    "remove",
    ("project_id", "recovery_branch_name", "signature"),
)
def test_installer_requires_the_exact_preflight_schema(
    tmp_path: Path,
    remove: str,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(
        preflight,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        remove=remove,
    )
    with pytest.raises(
        installer.BindingInstallerError,
        match="CHRONOS_BINDING_PREFLIGHT_SCHEMA_MISMATCH",
    ):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
            report_path=tmp_path / "report.json",
        )


def test_installer_rejects_tampered_controlled_go_before_any_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    controlled = _controlled_go()
    controlled["seal_r2_puts"] = 2
    _write_preflight(
        preflight,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        overrides={"controlled_go": controlled},
    )
    calls = 0

    def capture_secret(**_values: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(installer, "_set_secret", capture_secret)
    with pytest.raises(
        installer.BindingInstallerError,
        match="CHRONOS_BINDING_CONTROLLED_GO_INVALID",
    ):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
            report_path=tmp_path / "report.json",
        )
    assert calls == 0


def test_installer_rejects_noncanonical_expected_run_id(
    tmp_path: Path,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    with pytest.raises(
        installer.BindingInstallerError,
        match="CHRONOS_BINDING_PREFLIGHT_RUN_INVALID",
    ):
        installer.install(
            preflight_artifact=preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="0123456789",
            report_path=tmp_path / "report.json",
        )


def test_installer_attests_exact_successful_github_artifact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))

    def download(**values: object) -> dict[str, object]:
        output_path = Path(str(values["output_path"]))
        output_path.write_bytes(preflight.read_bytes())
        return {
            "schema_version": "github-release-artifact-attestation-v1",
            "run_id": int(PREFLIGHT_RUN_ID),
            "head_sha": MAIN_SHA,
            "conclusion": "success",
        }

    monkeypatch.setattr(installer, "attest_and_download", download)
    receipt, attested_bytes = REAL_ATTEST_PREFLIGHT(
        preflight,
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id=PREFLIGHT_RUN_ID,
    )
    assert receipt["run_id"] == int(PREFLIGHT_RUN_ID)
    assert attested_bytes == preflight.read_bytes()


def test_installer_rejects_any_local_artifact_byte_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))

    def download(**values: object) -> dict[str, object]:
        Path(str(values["output_path"])).write_bytes(b'{"different":true}\n')
        return {"run_id": int(PREFLIGHT_RUN_ID)}

    monkeypatch.setattr(installer, "attest_and_download", download)
    with pytest.raises(
        installer.BindingInstallerError,
        match="CHRONOS_BINDING_PREFLIGHT_BYTES_MISMATCH",
    ):
        REAL_ATTEST_PREFLIGHT(
            preflight,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=PREFLIGHT_RUN_ID,
        )


def test_installer_parses_only_attested_bytes_without_path_toctou(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = tmp_path / "preflight.json"
    _write_preflight(preflight, expires_at=datetime.now(UTC) + timedelta(minutes=15))
    attested_bytes = preflight.read_bytes()
    _write_preflight(
        preflight,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        overrides={"database_host": "ep-forged.eu-central-1.aws.neon.tech"},
    )

    monkeypatch.setattr(
        installer,
        "_attest_preflight_artifact",
        lambda _path, **_values: ({"run_id": int(PREFLIGHT_RUN_ID)}, attested_bytes),
    )
    monkeypatch.setattr(
        installer.secrets,
        "token_urlsafe",
        lambda _size: "p" * 64,
    )
    monkeypatch.setattr(installer.secrets, "token_hex", lambda _size: "ab" * 32)
    installed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **values: installed.append((str(values["name"]), str(values["value"]))),
    )
    installer.install(
        preflight_artifact=preflight,
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id=PREFLIGHT_RUN_ID,
        report_path=tmp_path / "report.json",
    )
    assert urlparse(installed[0][1]).hostname == "ep-test.eu-central-1.aws.neon.tech"
    assert "ep-forged" in preflight.read_text(encoding="utf-8")


def test_installer_direct_cli_entrypoint_is_self_contained() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_chronos_runtime_bindings_v1.py"),
            "--help",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert b"--preflight-artifact" in completed.stdout


def test_hold_requires_real_successful_main_push_ci_at_exact_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    conclusion = "success"
    legacy_ci_state = "disabled_manually"
    active_workflows = [
        {
            "path": ".github/workflows/ci-safe-v2.yml",
            "state": "active",
        },
        {
            "path": ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml",
            "state": "active",
        },
        {
            "path": ".github/workflows/chronos-controlled-go-durable-seal-v1.yml",
            "state": "active",
        },
    ]

    def github_get(path: str, _token: str, **_kwargs: object) -> dict[str, object]:
        if path.endswith("/actions/workflows?per_page=100"):
            return {"workflows": active_workflows}
        if path.endswith("/actions/workflows/ci.yml"):
            return {
                "id": 319500816,
                "path": ".github/workflows/ci.yml",
                "state": legacy_ci_state,
            }
        if path.endswith("/environments/chronos-control-plane-production"):
            return {
                "name": "chronos-control-plane-production",
                "can_admins_bypass": False,
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }
        if path.endswith(
            "/environments/chronos-control-plane-production/deployment-branch-policies"
        ):
            return {
                "total_count": 1,
                "branch_policies": [{"name": "main", "type": "branch"}],
            }
        if "actions/runs?status=" in path:
            return {"total_count": 0, "workflow_runs": []}
        if "actions/workflows/ci-safe-v2.yml/runs" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 456,
                        "run_attempt": 1,
                        "head_sha": MAIN_SHA,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": conclusion,
                    }
                ]
            }
        if "/git/ref/heads/codex/jalon-12-prospective-deep-data-observatory" in path:
            return {
                "ref": "refs/heads/codex/jalon-12-prospective-deep-data-observatory",
                "object": {"type": "commit", "sha": MAIN_SHA},
            }
        raise AssertionError(path)

    monkeypatch.setattr(hold_module, "_github_get", github_get)
    report = hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)
    assert report["post_merge_ci"] == {
        "workflow_path": ".github/workflows/ci-safe-v2.yml",
        "run_id": 456,
        "run_attempt": 1,
        "head_sha": MAIN_SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
    }
    assert report["unauthorized_active_workflows"] == []
    assert report["legacy_secret_branch_sha"] == MAIN_SHA
    assert report["legacy_ci_workflow_quarantine"] == {
        "workflow_id": 319500816,
        "workflow_path": ".github/workflows/ci.yml",
        "state": "disabled_manually",
    }
    assert report["production_environment_policy"] == {
        "environment": "chronos-control-plane-production",
        "can_admins_bypass": False,
        "protected_branches": False,
        "custom_branch_policies": True,
        "allowed_branches": ["main"],
    }
    legacy_ci_state = "active"
    with pytest.raises(ChronosProductionError, match="CHRONOS_LEGACY_CI_NOT_QUARANTINED"):
        hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)
    legacy_ci_state = "disabled_manually"
    active_run = 2
    original_get = hold_module._github_get

    def rerun_github_get(
        path: str, token: str, **kwargs: object
    ) -> dict[str, object]:
        document = original_get(path, token, **kwargs)
        if "actions/workflows/ci-safe-v2.yml/runs" in path:
            runs = document["workflow_runs"]
            assert isinstance(runs, list)
            runs[0]["run_attempt"] = active_run
        return document

    monkeypatch.setattr(hold_module, "_github_get", rerun_github_get)
    with pytest.raises(ChronosProductionError, match="CHRONOS_POST_MERGE_CI_NOT_PROVEN"):
        hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)
    active_run = 1
    conclusion = "failure"
    with pytest.raises(ChronosProductionError, match="CHRONOS_POST_MERGE_CI_NOT_PROVEN"):
        hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)

    conclusion = "success"
    active_workflows.append(
        {
            "path": ".github/workflows/chronos-neon-pure-readonly-preflight-v4.yml",
            "state": "active",
        }
    )
    with pytest.raises(ChronosProductionError, match="CHRONOS_UNAUTHORIZED_ACTIVE_WORKFLOW"):
        hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)
    active_workflows[-1]["path"] = ".github/workflows/chronos-provider-free-canary-v3.yml"
    with pytest.raises(ChronosProductionError, match="CHRONOS_UNAUTHORIZED_ACTIVE_WORKFLOW"):
        hold_module.verify_hold(required_successful_ci_sha=MAIN_SHA)
