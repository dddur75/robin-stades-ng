from __future__ import annotations

from pathlib import Path

import pytest

import scripts.run_reprise_collecte as cli


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
        "ROBIN_REPRISE_COLLECTE_20261002",
        "--manifest",
        str(tmp_path / "manifest.json"),
        "--output-directory",
        str(tmp_path),
    ]


def test_cli_returns_dedicated_nonzero_code_after_partial_delivery(
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
        cli, "run_reprise_collecte", lambda *_args, **_kwargs: {"status": "PARTIEL"}
    )

    assert cli.main(_arguments(tmp_path)) == 4
    assert '"status":"PARTIEL"' in capsys.readouterr().out


def test_cli_maps_missing_r2_configuration_to_one_sanitized_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _github_environment(monkeypatch)
    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    assert cli.main(_arguments(tmp_path)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "REPRISE_R2_CONFIGURATION_INVALID"
