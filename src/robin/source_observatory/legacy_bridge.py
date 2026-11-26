"""Read two pinned legacy snapshots without sharing their control directories."""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

APPROVED_LEGACY_READERS = {
    "read-public-tipsters.py": "634accac4455375b166c667ed8dbf8d91445ce75c17ff424896eddca4990db5a",
    "read-tipster-candidates.py": "d7bf22ab291f345d801e34638284052db956ee901340a0c19f398c34aebd5da0",
}


def read_legacy_snapshot(script_name: str, arguments: list[str]) -> dict[str, Any] | None:
    if script_name not in APPROVED_LEGACY_READERS:
        raise ValueError("legacy read-only script required")
    configured = os.environ.get("ROBIN_LEGACY_READ_ROOT")
    if not configured:
        return None
    root = Path(configured).resolve(strict=True)
    if root == Path(__file__).resolve().parents[3]:
        raise ValueError("legacy bridge recursion")
    if (
        len(arguments) > 4
        or len(arguments) % 2
        or any(
            arguments[i] not in ("--directory", "--campaign-directory")
            for i in range(0, len(arguments), 2)
        )
    ):
        raise ValueError("legacy read arguments")
    script = root / "cockpit/scripts" / script_name
    raw = script.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw).hexdigest() != APPROVED_LEGACY_READERS[script_name]:
        raise ValueError("legacy read-only script hash")
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    env.pop("ROBIN_LEGACY_READ_ROOT", None)
    # Fixed interpreter and pinned consultation-only CLI; the whitelist above
    # rejects every run/init/update flag, including on the historic mixed CLI.
    try:
        result = subprocess.run(  # nosec B603
            [sys.executable, "-X", "utf8", "-B", str(script), *arguments],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=6,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.SubprocessError:
        raise ValueError("legacy read-only snapshot failed") from None
    if len(result.stdout) > 12_000_000:
        raise ValueError("legacy snapshot size")
    value: dict[str, Any] = json.loads(result.stdout)
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise ValueError("legacy snapshot unavailable")
    return value
