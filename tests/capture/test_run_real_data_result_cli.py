from __future__ import annotations

import json
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


def test_cli_emits_only_a_structured_sanitized_dns_failure(
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

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise cli.ResultError("RESULT_DNS_RESOLUTION_EXPIRED")

    monkeypatch.setattr(cli, "run_real_data_result", fail)

    assert cli.main(_arguments(tmp_path)) == 2
    stderr_lines = capsys.readouterr().err.splitlines()
    assert stderr_lines[0] == "RESULT_DNS_RESOLUTION_EXPIRED"
    assert json.loads(stderr_lines[1]) == {
        "stage": "DNS_RESOLUTION",
        "code": "RESULT_DNS_RESOLUTION_EXPIRED",
        "exception_class": "ResultError",
        "errno": None,
        "http_status": None,
    }


def test_cli_preserves_safe_errno_without_exception_message(
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

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise OSError(9, "forbidden https://provider.invalid/?apiKey=secret-value")

    monkeypatch.setattr(cli, "run_real_data_result", fail)

    assert cli.main(_arguments(tmp_path)) == 3
    stderr = capsys.readouterr().err
    assert "secret-value" not in stderr
    assert "apiKey" not in stderr
    stderr_lines = stderr.splitlines()
    assert stderr_lines[0] == "RESULT_UNEXPECTED_FAILURE"
    assert json.loads(stderr_lines[1]) == {
        "stage": "RESULT_RUNTIME",
        "code": "RESULT_UNEXPECTED_FAILURE",
        "exception_class": "OSError",
        "errno": 9,
        "http_status": None,
    }


def test_cli_emits_typed_r2_result_diagnostic_without_detail(
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

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise cli.ResultError(
            "RESULT_R2_READBACK_FAILED",
            diagnostic={
                "stage": "R2_READBACK",
                "code": "RESULT_R2_READBACK_FAILED",
                "exception_class": "ClientError",
                "errno": None,
                "http_status": 403,
            },
        )

    monkeypatch.setattr(cli, "run_real_data_result", fail)

    assert cli.main(_arguments(tmp_path)) == 2
    stderr_lines = capsys.readouterr().err.splitlines()
    assert stderr_lines[0] == "RESULT_R2_READBACK_FAILED"
    assert json.loads(stderr_lines[1]) == {
        "stage": "R2_READBACK",
        "code": "RESULT_R2_READBACK_FAILED",
        "exception_class": "ClientError",
        "errno": None,
        "http_status": 403,
    }
