"""Latest bounded-source findings; documentary qualification never grants collection."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .personal_access import apply_personal_access

APPROVED_COMPATIBLE_ACCESS_SHA256 = (
    "d9aaa27d738b6614c581e17eeda12fc32a21716d9e4e17da323f54b264b1e389"
)


def read_compatible_access(base: dict[str, Any], path: Path, expected_sha: str) -> dict[str, Any]:
    try:
        data = apply_personal_access(base, path, expected_sha)
        qualification = data.setdefault("qualification", {})
        if qualification.get("status") != "ok":
            raise ValueError("previous source qualification unavailable")
        qualification["compatibleAccessState"] = "ok"
        qualification["compatibleClaimId"] = qualification["personalClaimId"]
        previous_claim = base.get("qualification", {}).get("personalClaimId")
        if previous_claim:
            qualification["personalClaimId"] = previous_claim
        return data
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["compatibleAccessState"] = "unavailable"
        return data


def add_compatible_access(base: dict[str, Any], root: Path) -> dict[str, Any]:
    return read_compatible_access(
        base,
        root / "reports/source_observatory/TIPSTERS-COMPATIBLE-ACCESS-FOLLOWUP-20261120.json",
        APPROVED_COMPATIBLE_ACCESS_SHA256,
    )
