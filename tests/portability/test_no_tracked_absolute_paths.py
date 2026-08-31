from __future__ import annotations

from pathlib import Path

from scripts.check_no_tracked_absolute_paths import find_forbidden_absolute_paths

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "reports" / "council" / "decision-ledger.jsonl"


def violations(value: str) -> list[str]:
    return [
        finding.category
        for finding in find_forbidden_absolute_paths(
            value,
            path="tests/portability/fixture.txt",
        )
    ]


def test_windows_absolute_path_is_rejected() -> None:
    value = "C:" + "/Users/alice/project/report.json"  # PORTABILITY_TEST_FIXTURE
    assert "WINDOWS_ABSOLUTE_PATH" in violations(value)


def test_unix_home_path_is_rejected() -> None:
    value = "/" + "home/alice/project/report.json"  # PORTABILITY_TEST_FIXTURE
    assert "UNIX_LOCAL_ABSOLUTE_PATH" in violations(value)


def test_onedrive_path_is_rejected() -> None:
    value = "One" + "Drive/Documents/report.json"  # PORTABILITY_TEST_FIXTURE
    assert "LOCAL_MACHINE_SEGMENT" in violations(value)


def test_codex_temp_path_is_rejected() -> None:
    value = "." + "codex/attachments/report.json"  # PORTABILITY_TEST_FIXTURE
    assert "LOCAL_MACHINE_SEGMENT" in violations(value)


def test_repo_relative_path_is_accepted() -> None:
    assert violations("reports/closure/audit.json") == []


def test_url_is_accepted() -> None:
    assert violations("https://example.com/Users/alice/report.json") == []


def test_placeholder_is_accepted() -> None:
    assert violations("<repo_root>/reports/closure/audit.json") == []


def test_only_the_exact_hash_bound_append_only_worktree_is_accepted() -> None:
    record = next(
        line
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if '"decision_id":"RCV3-20260830-194"' in line
    )
    ledger_path = "reports/council/decision-ledger.jsonl"
    assert find_forbidden_absolute_paths(record, path=ledger_path) == []

    mutated = record.replace('"worktree":"C:', '"worktree":"D:', 1)
    assert find_forbidden_absolute_paths(mutated, path=ledger_path)

    signed_field_mutation = record.replace('"writer":"C0"', '"writer":"C1"', 1)
    assert find_forbidden_absolute_paths(signed_field_mutation, path=ledger_path)

    appended = record + " " + ("C:" + "/Users/other/repository")  # PORTABILITY_TEST_FIXTURE
    assert find_forbidden_absolute_paths(appended, path=ledger_path)
