from __future__ import annotations

import json

from scripts.check_no_tracked_absolute_paths import find_forbidden_absolute_paths


def managed_worktree(
    *, drive: str = "C:", task: str = "task", repository: str = "repository"
) -> str:
    return drive + "/" + "Users/alice/" + "." + "codex/worktrees/" + task + "/" + repository


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


def test_append_only_ledger_worktree_field_is_accepted() -> None:
    worktree = managed_worktree()
    line = f'{{"context":{{"worktree":"{worktree}","artifact":"reports/evidence/proof.json"}}}}'

    assert (
        find_forbidden_absolute_paths(
            line,
            path="reports/council/decision-ledger.jsonl",
        )
        == []
    )


def test_append_only_ledger_sorted_record_accepts_spaced_repository() -> None:
    worktree = managed_worktree(repository="Robin des stades V2")
    line = json.dumps(
        {
            "context": {
                "observed_external_effects": {"provider_http_requests_new": 0},
                "worktree": worktree,
            },
            "decision_id": "RCV3-TEST",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert (
        find_forbidden_absolute_paths(
            line,
            path="reports/council/decision-ledger.jsonl",
        )
        == []
    )


def test_append_only_ledger_other_field_remains_rejected() -> None:
    worktree = managed_worktree()
    artifact = "C:" + "/" + "Users/alice/Downloads/proof.json"
    line = f'{{"context":{{"worktree":"{worktree}","artifact":"{artifact}"}}}}'

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/decision-ledger.jsonl",
    )

    assert {finding.category for finding in findings} >= {
        "WINDOWS_ABSOLUTE_PATH",
        "UNIX_LOCAL_ABSOLUTE_PATH",
    }


def test_append_only_ledger_top_level_worktree_remains_rejected() -> None:
    worktree = managed_worktree()
    line = f'{{"worktree":"{worktree}","context":{{"writer":"C0"}}}}'

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/decision-ledger.jsonl",
    )

    assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings)


def test_append_only_ledger_unmanaged_context_worktree_remains_rejected() -> None:
    worktree = "C:" + "/" + "Users/alice/Downloads/repository"
    line = f'{{"context":{{"worktree":"{worktree}"}}}}'

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/decision-ledger.jsonl",
    )

    assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings)


def test_append_only_ledger_duplicate_nested_context_worktree_fails_closed() -> None:
    worktree = managed_worktree()
    line = (
        f'{{"context":{{"worktree":"{worktree}"}},'
        f'"other":{{"context":{{"worktree":"{worktree}"}}}}}}'
    )

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/decision-ledger.jsonl",
    )

    assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings)


def test_append_only_ledger_rejects_unmanaged_worktree_shapes() -> None:
    forbidden = (
        managed_worktree(drive="D:"),
        managed_worktree(repository="..") + "/Downloads/secret",
        managed_worktree(task=".."),
        managed_worktree() + "/nested",
        managed_worktree(repository="repository:C:Downloads"),
    )

    for worktree in forbidden:
        line = f'{{"context":{{"worktree":"{worktree}"}}}}'
        findings = find_forbidden_absolute_paths(
            line,
            path="reports/council/decision-ledger.jsonl",
        )
        assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings), worktree


def test_append_only_ledger_noncanonical_json_fails_closed() -> None:
    worktree = managed_worktree()
    encoded = "".join(f"\\u{ord(character):04x}" for character in worktree)
    line = (
        '{"context":{"meta":{},"worktree":"'
        + encoded
        + '"},"other":{"context":{"worktree":"'
        + worktree
        + '"}}}'
    )

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/decision-ledger.jsonl",
    )

    assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings)


def test_worktree_field_outside_append_only_ledger_remains_rejected() -> None:
    worktree = managed_worktree()
    line = f'{{"worktree":"{worktree}"}}'

    findings = find_forbidden_absolute_paths(
        line,
        path="reports/council/review.json",
    )

    assert any(finding.category == "WINDOWS_ABSOLUTE_PATH" for finding in findings)
