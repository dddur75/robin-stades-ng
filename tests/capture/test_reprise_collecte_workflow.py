from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/90-reprise-collecte-pilot.yml"
ATTESTATION = ROOT / "configs/execution/reprise-collecte-code-attestation.json"
SIGNATURE = ROOT / "configs/execution/reprise-collecte-code-attestation.sig"


def _load_workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_workflow_is_one_manual_main_bound_run_with_no_retry_surface() -> None:
    workflow = _load_workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    assert set(trigger) == {"workflow_dispatch"}
    dispatch = trigger["workflow_dispatch"]
    assert set(dispatch["inputs"]) == {"execute", "expected_main_sha"}
    assert all(spec["required"] is True for spec in dispatch["inputs"].values())

    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "robin-reprise-collecte-20261002-global",
        "cancel-in-progress": False,
    }
    jobs = workflow["jobs"]
    assert set(jobs) == {"capture"}
    job = jobs["capture"]
    condition = job["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.run_attempt == 1" in condition
    assert "github.actor == 'dddur75'" in condition
    assert "github.triggering_actor == 'dddur75'" in condition
    assert "inputs.execute == 'ROBIN_REPRISE_COLLECTE_20261002'" in condition
    assert job["timeout-minutes"] == 20
    assert "strategy" not in job
    assert "continue-on-error" not in job

    steps = job["steps"]
    capture = next(step for step in steps if step.get("id") == "capture")
    encrypt = next(step for step in steps if step.get("id") == "encrypt")
    upload = next(step for step in steps if step.get("id") == "upload")
    terminal = next(step for step in steps if step.get("id") == "terminal")
    assert capture["continue-on-error"] is True
    assert "always()" in encrypt["if"] and "!cancelled()" in encrypt["if"]
    assert "steps.encrypt.outcome == 'success'" in upload["if"]
    assert terminal["env"]["CAPTURE_OUTCOME"] == "${{ steps.capture.outcome }}"


def test_workflow_scopes_secrets_to_the_effect_step_and_preserves_safety_locks() -> None:
    workflow = _load_workflow()
    locks = workflow["env"]
    assert locks == {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    job = workflow["jobs"]["capture"]
    assert "env" not in job
    steps = job["steps"]
    effect = next(step for step in steps if step.get("id") == "capture")
    assert effect["env"] == {
        "THE_ODDS_API_KEY": "${{ secrets.ODDS_API_KEY }}",
        "R2_ACCOUNT_ID": "${{ secrets.R2_ACCOUNT_ID }}",
        "R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}",
        "R2_SECRET_ACCESS_KEY": "${{ secrets.R2_SECRET_ACCESS_KEY }}",
        "R2_BUCKET_NAME": "${{ secrets.R2_BUCKET_NAME }}",
    }
    for step in steps:
        if step is effect:
            continue
        serialized = yaml.safe_dump(step)
        assert "secrets.ODDS_API_KEY" not in serialized
        assert "secrets.R2_" not in serialized
    assert "--interval-seconds 120" in effect["run"]
    assert "--execute ROBIN_REPRISE_COLLECTE_20261002" in effect["run"]

    gate = next(step for step in steps if step.get("id") == "gate")
    gate_command = gate["run"]
    assert "--paginate" in gate_command
    assert "head_sha" not in gate_command
    assert '[[ "$dispatch_count" == "1" ]]' in gate_command
    assert '.actor.login == "dddur75"' in gate_command
    assert '.triggering_actor.login == "dddur75"' in gate_command
    assert "reprise-collecte-code-attestation.json" in gate_command
    assert "reprise-collecte-code-attestation.sig" in gate_command
    assert "openssl dgst -sha256 -verify" in gate_command
    assert "97259bc1513f8bfaebaa08cf2d5ecfbc86c9de8471b9e33dd5891349e9900943" in gate_command
    assert steps.index(gate) < steps.index(effect)
    assert 'runtime_dir = Path(os.environ["RUNNER_TEMP"]) / "reprise-runtime"' in gate_command
    assert "runtime_relative_paths" in gate_command
    assert 'cd "$RUNNER_TEMP/reprise-runtime"' in effect["run"]
    assert "python -I scripts/run_reprise_collecte.py" in effect["run"]
    assert "python - <<" not in gate_command
    assert "python -I - <<'PY'" in gate_command


def test_workflow_uploads_only_public_receipt_and_encrypted_private_bundle() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["capture"]["steps"]
    encryption = next(step for step in steps if step.get("id") == "encrypt")
    command = encryption["run"]
    assert "openssl cms -encrypt" in command
    assert "-aes-256-cbc" in command
    assert "reprise-collecte-private.json" in command
    assert "reprise-collecte.csv" in command
    assert "reprise-collecte.html" in command
    assert "public-receipt.json" in command
    assert "reprise-collecte-private.p7m" in command
    assert "umask 077" in command
    assert "rm -f" in command
    assert "trap 'rm -f -- \"$plaintext_archive\"' EXIT" in command

    validation = next(step for step in steps if step.get("id") == "gate")
    assert "cms-preflight" in validation["run"]
    assert steps.index(validation) < steps.index(
        next(step for step in steps if step.get("id") == "capture")
    )

    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["id"] == "upload"
    assert upload["uses"] == ("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02")
    assert upload["with"] == {
        "name": "robin-reprise-collecte-${{ github.run_id }}",
        "path": "${{ runner.temp }}/reprise-upload",
        "if-no-files-found": "error",
        "include-hidden-files": False,
        "retention-days": 7,
    }
    assert "reprise-private" not in upload["with"]["path"]

    assert "private_report_r2_key" not in command


def test_workflow_uses_exact_dependency_and_action_revisions() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["capture"]["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert uses == [
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {
        "fetch-depth": 1,
        "persist-credentials": False,
        "ref": "${{ inputs.expected_main_sha }}",
    }
    install = next(step for step in steps if step.get("id") == "install")
    assert install["run"] == (
        "python -I -m pip install --only-binary=:all: --require-hashes "
        "-r requirements-data-torrent.lock"
    )


def test_retired_signed_attestation_fails_closed_after_successor_transport_fix() -> None:
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    assert set(attestation) == {
        "schema_version",
        "mission_id",
        "certificate_der_sha256",
        "hash_algorithm",
        "normalization",
        "artifact_hashes",
    }
    assert attestation["mission_id"] == "ROBIN_REPRISE_COLLECTE_20261002"
    assert attestation["hash_algorithm"] == "SHA-256"
    assert attestation["normalization"] == "LF_NORMALIZED_TEXT_BYTES"
    hashes = attestation["artifact_hashes"]
    required = {
        ".github/workflows/90-reprise-collecte-pilot.yml",
        "configs/execution/reprise-collecte-20261002.json",
        "configs/execution/reprise-collecte-recipient-cert.pem",
        "requirements-data-torrent.lock",
        "scripts/run_reprise_collecte.py",
        "src/robin/prospective_observatory/chronos_control_plane.py",
        "src/robin/prospective_observatory/chronos_r2.py",
    }
    probe = """
import pathlib
import runpy
import sys

root = pathlib.Path.cwd().resolve()
runpy.run_path("scripts/run_reprise_collecte.py", run_name="attestation_probe")
paths = []
for module in sys.modules.values():
    raw = getattr(module, "__file__", None)
    if not raw:
        continue
    path = pathlib.Path(raw).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        continue
    if relative.suffix == ".py":
        paths.append(relative.as_posix())
print("\\n".join(sorted(set(paths))))
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    imported = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    required.update(imported.stdout.splitlines())
    assert required <= set(hashes)
    mismatches: list[str] = []
    for filename, expected in hashes.items():
        normalized = (ROOT / filename).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(normalized).hexdigest()
        if actual != expected:
            mismatches.append(filename)
        else:
            assert actual == expected
    assert mismatches == ["src/robin/capture/live_transport.py"]
    signature = SIGNATURE.read_text(encoding="ascii").strip()
    assert len(base64.b64decode(signature, validate=True)) == 512


def test_isolated_runtime_does_not_execute_an_unattested_sitecustomize(
    tmp_path: Path,
) -> None:
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    runtime = tmp_path / "runtime"
    for filename in attestation["artifact_hashes"]:
        if filename == "scripts/run_reprise_collecte.py" or filename.startswith("src/"):
            destination = runtime / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / filename, destination)
    marker = tmp_path / "sitecustomize-executed"
    injected = runtime / "src/sitecustomize.py"
    injected.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-I", "scripts/run_reprise_collecte.py", "--help"],
        cwd=runtime,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
