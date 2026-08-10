from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_no_secrets import find_secret_literals


@pytest.mark.parametrize(
    ("name", "content", "label"),
    [
        (
            "workflow.log",
            "masked? " + "napi_" + "abcdefghijklmnopqrstuvwxyz012345",
            "Neon API key",
        ),
        (
            "artifact.json",
            '"dsn":"postgresql://owner:not-a-real-password@'
            'ep-example.eu.aws.neon.tech/robin?sslmode=require"',
            "Neon production DSN",
        ),
        (
            "temporary.txt",
            "CHRONOS_CONTROL_PLANE_GENERATION_NONCE=" + "ab" * 32,
            "Chronos generation nonce literal",
        ),
    ],
)
def test_log_artifact_and_temporary_sentinels_are_detected(
    tmp_path: Path,
    name: str,
    content: str,
    label: str,
) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    assert find_secret_literals([path]) == [f"{path}: {label}"]


def test_secret_placeholders_do_not_trigger(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text(
        "CHRONOS_BOOTSTRAP_READER_PASSWORD=${{ secrets.VALUE }}\n",
        encoding="utf-8",
    )
    assert find_secret_literals([path]) == []
