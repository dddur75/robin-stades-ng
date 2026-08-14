from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPO_ROOT / "tools" / "hypothesis-lab" / "build_catalogue.py"


@pytest.fixture(scope="session")
def builder() -> dict[str, Any]:
    return runpy.run_path(str(BUILDER_PATH), run_name="hypothesis_lab_builder")


@pytest.fixture(scope="session")
def artifacts(builder: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = builder["build_artifacts"]()
    assert isinstance(value, dict)
    return value
