"""Source-literal choices observed before match, without interpreting their market."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .connectors import canonical
from .olbg import _team
from .recurring import instant


def build_opaque_choices(
    source: dict[str, Any], accepted_tip_ids: list[int], *, parser_sha: str
) -> list[dict[str, Any]]:
    if (
        len(accepted_tip_ids) != len(set(accepted_tip_ids))
        or len(accepted_tip_ids) > 100
        or any(type(i) is not int or i <= 0 for i in accepted_tip_ids)
        or re.fullmatch("[a-f0-9]{64}", parser_sha) is None
    ):
        raise ValueError("opaque identity/parser")
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for profile in source["profiles"]:
        facts, request = profile["facts"], profile["request"]
        for native in facts["records"]:
            tid = native.get("tipid")
            if tid not in accepted_tip_ids:
                continue
            author = facts["authorId"]
            if (
                type(tid) is not int
                or tid in seen
                or type(author) is not int
                or author <= 0
                or facts["mode"] != "current"
                or request["url"] != f"https://www.olbg.com/tipsters/tips/{author}"
                or native.get("vc_sport_id") != 1
                or native.get("result") != "Open"
                or type(native.get("eventid")) is not int
                or native["eventid"] <= 0
            ):
                raise ValueError("opaque personal attribution")
            seen.add(tid)
            names = re.split(r"\s+v(?:s\.?)?\s+", native.get("eventname", ""), flags=re.I)
            matches = [
                f
                for f in source["fixtures"]
                if len(names) == 2
                and _team(names[0]) in {_team(a) for a in f["homeAliases"]}
                and _team(names[1]) in {_team(a) for a in f["awayAliases"]}
            ]
            if len(matches) != 1:
                raise ValueError("opaque canonical fixture absent/ambiguous")
            fixture = matches[0]
            if (
                instant(request["observedAt"]) >= instant(fixture["kickoff"])
                or datetime.strptime(native["event_datetime"], "%Y-%m-%d %H:%M:%S").date()
                != instant(fixture["kickoff"]).date()
            ):
                raise ValueError("opaque pre-match timing")
            if (
                not isinstance(native.get("selection"), str)
                or not 0 < len(native["selection"]) <= 120
                or not isinstance(native.get("market"), str)
                or len(native["market"]) > 120
                or not isinstance(native.get("winew"), str)
                or any(isinstance(v, (dict, list)) for v in native.values())
                or any(
                    re.fullmatch("[a-f0-9]{64}", h) is None
                    for h in (request["responseSha256"], source["calendarSha256"])
                )
            ):
                raise ValueError("opaque native fields/provenance")
            rows.append(
                dict(
                    id=f"olbg-tip:{tid}",
                    sourceId="SRC_014",
                    authorId=f"olbg:{author}",
                    authorLabel=facts["authorLabel"],
                    authorUrl=request["url"],
                    sourceUrl=request["url"],
                    sourceTipId=tid,
                    sourceEventId=native["eventid"],
                    fixtureId=fixture["id"],
                    fixtureLabel=fixture["label"],
                    kickoff=fixture["kickoff"],
                    selection=native["selection"],
                    market="source_native_opaque",
                    marketLabel="Choix publié (marché source non interprété)",
                    sourceMarketLabel=native["market"],
                    sourceBetType=native["winew"],
                    sourceFields=deepcopy(native),
                    sourceEventLocalText=native["event_datetime"],
                    sourceEventTimezone=None,
                    publishedAt=None,
                    publishedCivilDate=None,
                    observedAt=request["observedAt"],
                    firstSeenAt=request["observedAt"],
                    responseSha256=request["responseSha256"],
                    parserSha256=parser_sha,
                    calendarSha256=source["calendarSha256"],
                    performanceEvaluationAllowed=False,
                    settlementAllowed=False,
                    marketInterpretationAllowed=False,
                    versions=[
                        dict(selection=native["selection"], observedAt=request["observedAt"])
                    ],
                    versionCount=1,
                )
            )
    if seen != set(accepted_tip_ids):
        raise ValueError("accepted opaque fact absent")
    return rows


def read_opaque_bundle(
    path: Path, expected_sha: str, source_path: Path, expected_source_sha: str
) -> dict[str, Any]:
    if path.stat().st_size > 2_000_000 or source_path.stat().st_size > 2_000_000:
        raise ValueError("opaque bundle size")
    raw, source_raw = path.read_bytes(), source_path.read_bytes()
    if (
        sha256(raw).hexdigest() != expected_sha
        or sha256(source_raw).hexdigest() != expected_source_sha
    ):
        raise ValueError("opaque source/bundle hash")
    value: dict[str, Any] = json.loads(raw)
    source = json.loads(source_raw)
    if (
        value.get("schemaVersion") != "robin-opaque-tipster-facts-v1"
        or value.get("sourceResultSha256") != expected_source_sha
        or canonical(value.get("fixtures")) != canonical(source["fixtures"])
    ):
        raise ValueError("opaque bundle lineage")
    expected = build_opaque_choices(
        source, value["acceptedSourceTipIds"], parser_sha=value["lexicalParserSha256"]
    )
    picks = value.get("picks")
    if (
        not isinstance(picks, list)
        or any(
            not isinstance(row, dict)
            or any(
                row.get(flag) is not False
                for flag in (
                    "performanceEvaluationAllowed",
                    "settlementAllowed",
                    "marketInterpretationAllowed",
                )
            )
            for row in picks
        )
        or canonical(picks) != canonical(expected)
    ):
        raise ValueError("opaque literal data or interpretation changed")
    value["distinctPicks"] = len(expected)
    value["authorCount"] = len({r["authorId"] for r in expected})
    return value


def merge_distinct_choices(
    previous: list[dict[str, Any]], additional: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One source prediction counts once across its literal/normalized views."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in [*previous, *additional]:
        key = (
            (row.get("sourceId"), row.get("authorId"), row["sourceTipId"])
            if row.get("sourceTipId") is not None
            else (row.get("sourceId"), row["id"])
        )
        if key not in seen:
            result.append(deepcopy(row))
            seen.add(key)
    return result
