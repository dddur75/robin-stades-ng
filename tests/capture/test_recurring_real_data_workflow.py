from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/92-robin-autonomous-lab.yml"


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_workflow_is_schedule_only_on_main_and_serialized_globally() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert trigger == {"schedule": [{"cron": "37 * * * *"}]}
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "robin-autonomous-lab-20261004-global",
        "cancel-in-progress": False,
    }
    job = workflow["jobs"]["capture"]
    assert job["timeout-minutes"] == 30
    assert "github.event_name == 'schedule'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert "github.run_attempt == 1" in job["if"]
    assert "workflow_dispatch" not in WORKFLOW.read_text(encoding="utf-8")


def test_workflow_gates_exact_main_authority_and_retired_provider_routes() -> None:
    workflow = _workflow()
    gate = next(step for step in workflow["jobs"]["capture"]["steps"] if step.get("id") == "gate")
    command = gate["run"]
    assert "current_main_sha" in command
    assert '[[ "$GITHUB_SHA" == "$current_main_sha" ]]' in command
    for workflow_id, path in {
        308531686: "03_archive.yml",
        319598077: "collect-fixtures.yml",
        319598078: "collect-odds.yml",
        319598079: "daily-health.yml",
        319598080: "post-match-settlement.yml",
        319598083: "pre-match-shadow.yml",
        319799017: "shadow-diagnostics.yml",
        321915844: "prospective-odds-capture.yml",
        345580923: "data-torrent-live-v1.yml",
        373855898: "90-reprise-collecte-pilot.yml",
        374107131: "91-robin-real-data-result.yml",
    }.items():
        assert str(workflow_id) in command
        assert path in command
    assert "disabled_manually" in command
    assert "datetime.timedelta(hours=3) <= expires" in command
    manifest = ROOT / "configs/execution/robin-autonomous-lab-20261004.json"
    source = ROOT / "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md"
    schedule_manifest = (
        ROOT / "configs/execution/robin-autonomous-lab-schedule-reliability-20261004.json"
    )
    schedule_source = (
        ROOT / "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-SCHEDULE-RELIABILITY-2026-10-04.md"
    )
    assert gate["env"]["EXPECTED_MANIFEST_SHA256"] == _lf_sha256(manifest)
    assert gate["env"]["EXPECTED_SOURCE_SHA256"] == _lf_sha256(source)
    assert gate["env"]["EXPECTED_SCHEDULE_MANIFEST_SHA256"] == _lf_sha256(schedule_manifest)
    assert gate["env"]["EXPECTED_SCHEDULE_SOURCE_SHA256"] == _lf_sha256(schedule_source)
    assert "set(schedule_manifest) == set(manifest)" in command
    assert "EXPECTED_SCHEDULE_MANIFEST_SHA256" in command
    assert "EXPECTED_SCHEDULE_SOURCE_SHA256" in command


def test_gate_inventories_every_existing_provider_secret_route() -> None:
    expected = {
        "03_archive.yml",
        "collect-fixtures.yml",
        "collect-odds.yml",
        "daily-health.yml",
        "post-match-settlement.yml",
        "pre-match-shadow.yml",
        "shadow-diagnostics.yml",
        "prospective-odds-capture.yml",
        "data-torrent-live-v1.yml",
        "90-reprise-collecte-pilot.yml",
        "91-robin-real-data-result.yml",
        "92-robin-autonomous-lab.yml",
    }
    observed = {
        path.name
        for path in (ROOT / ".github/workflows").glob("*.yml")
        if "secrets.ODDS_API_KEY" in path.read_text(encoding="utf-8")
    }
    assert observed == expected


def test_workflow_scopes_secrets_and_uploads_only_normalized_delivery() -> None:
    workflow = _workflow()
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
    steps = workflow["jobs"]["capture"]["steps"]
    capture = next(step for step in steps if step.get("id") == "capture")
    assert capture["env"] == {
        "THE_ODDS_API_KEY": "${{ secrets.ODDS_API_KEY }}",
        "R2_ACCOUNT_ID": "${{ secrets.R2_ACCOUNT_ID }}",
        "R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}",
        "R2_SECRET_ACCESS_KEY": "${{ secrets.R2_SECRET_ACCESS_KEY }}",
        "R2_BUCKET_NAME": "${{ secrets.R2_BUCKET_NAME }}",
    }
    assert "scripts/run_recurring_real_data.py" in capture["run"]
    assert "--execute ROBIN_AUTONOMOUS_LAB_20261004" in capture["run"]
    for step in steps:
        if step is capture:
            continue
        serialized = yaml.safe_dump(step)
        assert "secrets.ODDS_API_KEY" not in serialized
        assert "secrets.R2_" not in serialized
    validate = next(step for step in steps if step.get("id") == "validate")
    assert validate["if"] == "${{ always() && !cancelled() }}"
    assert "RECURRING_NORMALIZED_FILE_SET_INVALID" in validate["run"]
    assert 'root.rglob("*")' in validate["run"]
    assert "path.is_symlink() or not path.is_file()" in validate["run"]
    assert "RECURRING_NORMALIZED_TREE_INVALID" in validate["run"]
    assert "raw_payload_base64" in validate["run"]
    assert "private_report_r2_status" in validate["run"]
    assert 'receipt["display_row_count"]' in validate["run"]
    assert 'snapshot["data_role"] == "CARRY_FORWARD_STALE"' in validate["run"]
    assert 'receipt["claim_ids"] == snapshot["claim_ids"]' in validate["run"]
    assert "RECURRING_CLAIM_IDS" in validate["run"]
    assert "SEED_CLAIM_IDS" in validate["run"]
    assert "RECURRING_CLAIM_IDS + SEED_CLAIM_IDS" in validate["run"]
    assert "Claim IDs" in validate["run"]
    upload = next(step for step in steps if step.get("id") == "upload")
    assert upload["with"]["path"] == "${{ runner.temp }}/robin-autonomous-lab"
    assert upload["with"]["retention-days"] == 30


def test_workflow_pins_actions_dependencies_and_preserves_terminal_outcome() -> None:
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
    terminal = next(step for step in steps if step.get("id") == "terminal")
    assert terminal["if"] == "${{ always() }}"
    assert "RECURRING_DELIVERY_INCOMPLETE" in terminal["run"]
    assert "GITHUB_SERVER_URL" in workflow["jobs"]["capture"]["steps"][-3]["run"]
