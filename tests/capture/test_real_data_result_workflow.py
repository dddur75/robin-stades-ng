from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/91-robin-real-data-result.yml"


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_successor_workflow_is_exact_main_bounded_and_has_no_recurring_trigger() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"execute", "expected_main_sha"}
    assert all(spec["required"] is True for spec in inputs.values())
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "robin-real-data-result-20261003-global",
        "cancel-in-progress": False,
    }
    job = workflow["jobs"]["capture"]
    assert job["timeout-minutes"] == 30
    assert "github.run_attempt == 1" in job["if"]
    assert "inputs.execute == 'ROBIN_REAL_DATA_RESULT_20261003'" in job["if"]
    gate = next(step for step in job["steps"] if step.get("id") == "gate")
    command = gate["run"]
    assert '"$dispatch_count" -ge 1 && "$dispatch_count" -le 3' in command
    assert "37118924677" in command
    assert "datetime.timedelta(minutes=30) <= expires" in command
    assert "reprise-collecte-code-attestation" not in command
    assert "openssl" not in command
    assert "current_main_sha" in command


def test_successor_workflow_scopes_secrets_and_uploads_only_normalized_delivery() -> None:
    workflow = _workflow()
    locks = workflow["env"]
    assert locks["API_FOOTBALL_CALLS_ALLOWED"] == "0"
    assert locks["REAL_BETS"] == "false"
    assert locks["PRODUCTION_LOCKED"] == "true"
    steps = workflow["jobs"]["capture"]["steps"]
    capture = next(step for step in steps if step.get("id") == "capture")
    assert capture["env"] == {
        "THE_ODDS_API_KEY": "${{ secrets.ODDS_API_KEY }}",
        "R2_ACCOUNT_ID": "${{ secrets.R2_ACCOUNT_ID }}",
        "R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}",
        "R2_SECRET_ACCESS_KEY": "${{ secrets.R2_SECRET_ACCESS_KEY }}",
        "R2_BUCKET_NAME": "${{ secrets.R2_BUCKET_NAME }}",
    }
    assert "--interval-seconds 120" in capture["run"]
    assert "scripts/run_real_data_result.py" in capture["run"]
    for step in steps:
        if step is capture:
            continue
        serialized = yaml.safe_dump(step)
        assert "secrets.ODDS_API_KEY" not in serialized
        assert "secrets.R2_" not in serialized
    upload = next(step for step in steps if step.get("id") == "upload")
    assert upload["uses"] == "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
    assert upload["with"]["path"] == "${{ runner.temp }}/real-data-result"
    validate = next(step for step in steps if step.get("id") == "validate")
    assert "robin-real-data.html" in validate["run"]
    assert "robin-real-data.csv" in validate["run"]
    assert "raw_payload_base64" in validate["run"]
    assert "credits_upper is None" in validate["run"]
    assert "UNBOUNDED_COST_HEADER_MISSING_STOPPED_WITH_PRIOR_RESERVE" in validate["run"]
    assert 'receipt["terminal_safety_status"] in {"PASS", "FAIL_CLOSED"}' in validate["run"]
    assert 'receipt["status"] == "REAL_DATA_COMPLETE"' in validate["run"]
    assert 'receipt["effect_accounting"]["r2_put_requests"] <= 34' in validate["run"]
    assert 'receipt["effect_accounting"]["r2_get_requests"] <= 34' in validate["run"]
    assert "openssl cms" not in WORKFLOW.read_text(encoding="utf-8")


def test_successor_workflow_pins_actions_dependencies_manifest_and_source() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["capture"]["steps"]
    assert [step["uses"] for step in steps if "uses" in step] == [
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ]
    install = next(step for step in steps if step.get("id") == "install")
    assert install["run"] == (
        "python -I -m pip install --only-binary=:all: --require-hashes "
        "-r requirements-data-torrent.lock"
    )
    gate = next(step for step in steps if step.get("id") == "gate")
    manifest = ROOT / "configs/execution/robin-real-data-result-20261003.json"
    source = ROOT / "docs/data-sourcing/ROBIN-REAL-DATA-RESULT-2026-10-03.md"
    assert gate["env"]["EXPECTED_MANIFEST_SHA256"] == _lf_sha256(manifest)
    assert gate["env"]["EXPECTED_SOURCE_SHA256"] == _lf_sha256(source)
