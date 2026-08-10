from __future__ import annotations

from scripts.check_no_tracked_absolute_paths import find_forbidden_absolute_paths


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
