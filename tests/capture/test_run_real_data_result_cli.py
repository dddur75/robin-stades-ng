from __future__ import annotations

from pathlib import Path

import pytest

import scripts.run_real_data_result as cli


def _github_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "dddur75/robin-stades-ng")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "424242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--execute",
        "ROBIN_REAL_DATA_RESULT_20261003",
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--output-directory",
        str(tmp_path),
    ]


@pytest.mark.parametrize("status", ["REAL_DATA_COMPLETE", "REAL_DATA_PARTIAL"])
def test_cli_delivers_complete_or_explicitly_partial_result_as_success(
    status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _github_environment(monkeypatch)
    monkeypatch.setattr(
        cli.ChronosR2ConditionalStore,
        "from_environment",
        lambda _environment: object(),
    )
    monkeypatch.setattr(
        cli,
        "run_real_data_result",
        lambda *_args, **_kwargs: {"status": status, "terminal_safety_status": "PASS"},
    )

    assert cli.main(_arguments(tmp_path)) == 0
    assert f'"status":"{status}"' in capsys.readouterr().out


def test_cli_refuses_no_real_capture_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _github_environment(monkeypatch)
    monkeypatch.setattr(
        cli.ChronosR2ConditionalStore,
        "from_environment",
        lambda _environment: object(),
    )
    monkeypatch.setattr(
        cli,
        "run_real_data_result",
        lambda *_args, **_kwargs: {"status": "NO_REAL_CAPTURE"},
    )
    assert cli.main(_arguments(tmp_path)) == 4


def test_cli_fails_closed_for_partial_data_with_a_terminal_safety_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _github_environment(monkeypatch)
    monkeypatch.setattr(
        cli.ChronosR2ConditionalStore,
        "from_environment",
        lambda _environment: object(),
    )
    monkeypatch.setattr(
        cli,
        "run_real_data_result",
        lambda *_args, **_kwargs: {
            "status": "REAL_DATA_PARTIAL",
            "terminal_safety_status": "FAIL_CLOSED",
            "global_stop_code": "RESULT_PROVIDER_QUOTA_UNVERIFIED",
        },
    )

    assert cli.main(_arguments(tmp_path)) == 4
