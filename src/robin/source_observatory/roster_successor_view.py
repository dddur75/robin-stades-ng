"""Read a separately authorized successor without changing the completed campaign."""

import json
import re
import subprocess  # nosec B404
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any

from .roster_recurring_view import _check, merge_group_candidates, merge_group_public

CAMPAIGN_ID = "ROBIN-OLBG-ROSTER42-NEXT3-20261121"
PACKET = Path(
    "C:/Users/ddura/.codex/worktrees/robin-roster-successor-e1/Robin V3/cockpit/.ci/roster42-next3-e1-20261121"
)
PYTHON = Path(
    "C:/Users/ddura/.codex/worktrees/robin-dossier-fidele/Robin V3/.venv/Scripts/python.exe"
)
CONFIG = "cockpit/.ci/roster-next-bridge-20261121/config.json"


def _read(root: Path, deadline: float | None = None) -> tuple[dict[str, Any], bool] | None:
    path = root / CONFIG
    if not path.exists():
        return None
    if path.stat().st_size > 8_192:
        raise ValueError("successor bridge bound")
    config = json.loads(path.read_bytes())
    if set(config) != {
        "directory",
        "readerSha256",
        "sourceDecisionSha256",
        "taskDecisionSha256",
        "nativeXmlSha256",
    }:
        raise ValueError("successor bridge contract")
    if Path(config["directory"]).resolve() != (PACKET / "runtime").resolve():
        raise ValueError("successor directory")
    for key in ("readerSha256", "sourceDecisionSha256", "taskDecisionSha256", "nativeXmlSha256"):
        if not isinstance(config[key], str) or not re.fullmatch(r"[0-9a-f]{64}", config[key]):
            raise ValueError("successor pin")
    reader = PACKET / "read.py"
    if (
        reader.stat().st_size > 100_000
        or sha256(reader.read_bytes()).hexdigest() != config["readerSha256"]
    ):
        raise ValueError("successor reader pin")
    remaining = min(5.0, deadline - monotonic() - 0.3) if deadline is not None else 5.0
    if remaining <= 0:
        raise TimeoutError("parent reader budget exhausted")
    result = subprocess.run(  # nosec B603
        [
            str(PYTHON),
            "-X",
            "utf8",
            "-B",
            str(reader),
            "--directory",
            config["directory"],
            "--source-decision-sha256",
            config["sourceDecisionSha256"],
            "--task-decision-sha256",
            config["taskDecisionSha256"],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=remaining,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if len(result.stdout) > 4_000_000:
        raise ValueError("successor projection bound")
    value = json.loads(result.stdout)
    observed = value["observed"]
    if (
        observed["rosterCampaign"]["campaignId"] != CAMPAIGN_ID
        or type(value["operational"]) is not bool
    ):
        raise ValueError("successor projection identity")
    return observed, value["operational"]


ERRORS = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def add_next_public(
    base: dict[str, Any], root: Path, *, deadline: float | None = None
) -> dict[str, Any]:
    try:
        result = _read(root) if deadline is None else _read(root, deadline)
        if result is None:
            return deepcopy(base)
        observed, _ = result
        data = merge_group_public(base, observed)
        data["rosterNextCampaign"] = data.pop("rosterCampaign")
        if "rosterCampaign" in base:
            data["rosterCampaign"] = deepcopy(base["rosterCampaign"])
        return data
    except ERRORS:
        data = deepcopy(base)
        data["rosterNextCampaign"] = dict(state="unavailable")
        return data


def add_next_candidates(
    base: dict[str, Any], root: Path, *, deadline: float | None = None
) -> dict[str, Any]:
    try:
        result = _read(root) if deadline is None else _read(root, deadline)
        if result is None:
            return deepcopy(base)
        if base.get("qualification", {}).get("status") != "ok":
            raise ValueError("base qualification unavailable")
        observed, operational = result
        historical = [
            pick
            for row in [*base.get("candidates", []), *base.get("rosterAssessments", [])]
            for qualification in [row.get("qualification")]
            if isinstance(qualification, dict)
            for pick in qualification.get("picks", [])
        ]
        _check(historical, observed["picks"])
        data = merge_group_candidates(base, observed, operational)
        for key in ("rosterRecurringState", "rosterCampaignId"):
            if key in base["qualification"]:
                data["qualification"][key] = deepcopy(base["qualification"][key])
            else:
                data["qualification"].pop(key, None)
        data["qualification"].update(rosterNextState="ok", rosterNextCampaignId=CAMPAIGN_ID)
        return data
    except ERRORS:
        data = deepcopy(base)
        for row in [*data.get("candidates", []), *data.get("rosterAssessments", [])]:
            if row.get("qualification", {}).get("rosterCampaignId") == CAMPAIGN_ID:
                row["collectionEnabled"] = False
        data["enabledCount"] = sum(
            bool(r.get("collectionEnabled")) for r in data.get("candidates", [])
        )
        data.setdefault("qualification", {})["rosterNextState"] = "unavailable"
        return data
