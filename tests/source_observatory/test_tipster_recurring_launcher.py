"""Exercise the real launcher's date/mode preparation without invoking Python or HTTP."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("culture", ["fr-FR", "en-US"])
@pytest.mark.parametrize(
    ("expiry", "expected"),
    [("2099-11-26T07:00:00+00:00", "--run"), ("2000-11-26T07:00:00+00:00", "--close")],
)
def test_launcher_selects_mode_independently_of_windows_culture(
    tmp_path, culture, expiry, expected
):
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not installed")
    root = Path(__file__).resolve().parents[2]
    launcher = (root / "cockpit/scripts/tipsters-recurring-tick.ps1").read_text(encoding="utf-8")
    lines = [line for line in launcher.splitlines() if line.startswith(("$manifest =", "$mode ="))]
    assert len(lines) == 2
    (tmp_path / "manifest.json").write_text(json.dumps({"expires_at": expiry}), encoding="utf-8")
    environment = dict(os.environ, ROBIN_TEST_DIRECTORY=str(tmp_path), ROBIN_TEST_CULTURE=culture)
    # Only the actual manifest/mode expressions are executed. The invocation
    # of the collector is deliberately outside this probe.
    code = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "[cultureinfo]::CurrentCulture = [cultureinfo]::GetCultureInfo($env:ROBIN_TEST_CULTURE)",
            "$Directory = $env:ROBIN_TEST_DIRECTORY",
            *lines,
            "$mode",
        ]
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", code],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
