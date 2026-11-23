from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.check_no_tracked_absolute_paths as candidate_checker
from scripts.check_no_tracked_absolute_paths import find_forbidden_absolute_paths


def sealed_authorization_line() -> str:
    path = Path(__file__).resolve().parents[2] / "reports/council/decision-ledger.jsonl"
    line = path.read_text(encoding="utf-8").splitlines()[460]
    assert json.loads(line)["decision_id"] == "RCV3-20261120-NT-E1-LEGAL-AUTHORIZED"
    return line


def scan_sealed(line: str, path: str = "reports/council/decision-ledger.jsonl"):
    return find_forbidden_absolute_paths("\n" * 460 + line, path=path)


def canonical_record(record: dict) -> str:
    record["hash"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in record.items() if k != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_exact_immutable_authorization_file_locators_have_one_narrow_exception() -> None:
    assert scan_sealed(sealed_authorization_line()) == []


def test_copy_of_the_immutable_record_at_another_line_or_file_is_rejected() -> None:
    line = sealed_authorization_line()
    findings = scan_sealed(line + "\n" + line)
    assert findings and all(f.line == 462 for f in findings)
    assert scan_sealed(line, path="reports/other.jsonl")


def test_immutable_exception_rejects_modified_or_rehashed_values() -> None:
    line = sealed_authorization_line()
    for recompute in [False, True]:
        record = json.loads(line)
        record["context"]["files"][1] += ".changed"
        changed = (
            canonical_record(record) if recompute else json.dumps(record, separators=(",", ":"))
        )
        assert scan_sealed(changed)


def test_immutable_exception_never_allows_third_path_other_field_or_other_decision() -> None:
    line = sealed_authorization_line()
    for kind in ["third", "other_field", "decision", "moved"]:
        record = json.loads(line)
        if kind == "third":
            record["context"]["files"].append(record["context"]["files"][1] + ".new")
        elif kind == "other_field":
            record["proposal"] = record["context"]["files"][1]
        elif kind == "decision":
            record["decision_id"] = "RCV3-UNREVIEWED"
        else:
            record["context"]["files"][1:3] = list(reversed(record["context"]["files"][1:3]))
        assert scan_sealed(canonical_record(record))


def test_semantically_identical_but_noncanonical_or_moved_line_is_rejected() -> None:
    line = sealed_authorization_line()
    assert scan_sealed(line.replace(":", ": ", 1))
    assert find_forbidden_absolute_paths(line, path="reports/council/decision-ledger.jsonl")


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


# New immutable-publication receipt regression; no provider corpus is loaded.


def publication_line() -> str:
    root = Path(__file__).resolve().parents[2]
    assert (
        Path(candidate_checker.__file__).resolve()
        == root / "scripts/check_no_tracked_absolute_paths.py"
    )
    return (
        (root / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[1992]
    )


def scan_publication(
    line: str, *, number: int = 1993, path: str = "reports/council/decision-ledger.jsonl"
):
    return find_forbidden_absolute_paths("\n" * (number - 1) + line, path=path)


def test_exact_publication_test_receipt_values_are_sealed() -> None:
    passed = not scan_publication(publication_line())
    assert passed, "EXACT_PUBLICATION_RECEIPTS_NOT_MASKED"


def test_publication_copy_wrong_line_and_file_are_rejected() -> None:
    line = publication_line()
    assert scan_publication(line, number=1994)
    assert scan_publication(line, path="reports/other.jsonl")


def test_publication_mutations_remain_rejected() -> None:
    for mutation in ("id", "hash", "value", "order", "sixth", "other", "newrecord"):
        record = json.loads(publication_line())
        values = record["context"]["targeted_tests"]
        if mutation == "id":
            record["decision_id"] = "UNREVIEWED"
        elif mutation == "hash":
            record["hash"] = "0" * 64
        elif mutation == "value":
            values[0] += ".changed"
        elif mutation == "order":
            values.reverse()
        elif mutation == "sixth":
            values.append(values[0] + ".sixth")
        elif mutation == "other":
            record["proposal"] = values[0]
        else:
            record = {"decision_id": "NEW", "context": {"targeted_tests": values}}
        changed = (
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if mutation == "hash"
            else canonical_record(record)
        )
        assert scan_publication(changed)
    record = json.loads(publication_line())
    record["context"]["targeted_tests"][0] += ".changed"
    assert scan_publication(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    assert scan_publication(publication_line().replace(":", ": ", 1))


def test_publication_masks_only_five_string_interiors() -> None:
    line = publication_line()
    masked = candidate_checker._mask_sealed_publication_test_values(line, 1993)
    expected = line
    values = json.loads(line)["context"]["targeted_tests"]
    for value in values:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        assert expected.count(encoded) == 1
        expected = expected.replace(encoded, '"' + " " * (len(encoded) - 2) + '"', 1)
    assert masked == expected
    assert len(masked) == len(line)
