from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]


def test_linux_ci_proves_the_exact_runtime_lock_before_the_full_suite() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["tests"]["steps"]
    lock_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Valider le lock data torrent Linux avant tout effet reel"
    )
    install_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Installer les dependances"
    )
    assert lock_index < install_index
    command = " ".join(steps[lock_index]["run"].split())
    assert "--dry-run" not in command
    assert "--ignore-installed" not in command
    assert command.startswith("python -m pip install --only-binary=:all: --require-hashes")
    assert "-r requirements-data-torrent.lock" in command
    assert (
        "import boto3, psycopg, pypdf, requests, robin.data_torrent.runtime, sqlalchemy" in command
    )
