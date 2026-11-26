"""Private unqualified profile observations; no fixture or prematch inference."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

MAX_RECORDS = 20
MAX_BYTES = 131072


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def mapping(value: Any, reason: str) -> dict[str, Any]:
    require(type(value) is dict, reason)
    return cast(dict[str, Any], value)


def integer(value: Any) -> bool:
    return type(value) is int and 0 < value <= 2**53 - 1


def text(value: Any, maximum: int, *, empty: bool = False) -> bool:
    if type(value) is not str or not (0 if empty else 1) <= len(value) <= maximum:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value)


def hash_value(value: Any) -> bool:
    return type(value) is str and re.fullmatch("[a-f0-9]{64}", value) is not None


def project_pending_observations(source: dict[str, Any], *, parser_sha: str) -> dict[str, Any]:
    """Project bounded native strings, never admit or interpret a prediction.

    The caller must independently authenticate source authority and provenance.
    This pure function neither writes a pending file nor grants permission to do so.
    """
    profiles = source.get("profiles")
    require(type(profiles) is list and len(profiles) == 1, "PENDING_PROFILE_REFUSED")
    profile = mapping(cast(list[Any], profiles)[0], "PENDING_PROFILE_REFUSED")
    facts = mapping(profile.get("facts"), "PENDING_PROFILE_REFUSED")
    request = mapping(profile.get("request"), "PENDING_PROFILE_REFUSED")
    author = facts.get("authorId")
    label = facts.get("authorLabel")
    require(integer(author) and text(label, 80) and facts.get("mode") == "current", "PENDING_PROFILE_REFUSED")
    url = f"https://www.olbg.com/tipsters/tips/{author}"
    require(request.get("url") == url, "PENDING_PROFILE_REFUSED")
    stamp = request.get("observedAt")
    require(text(stamp, 40) and hash_value(request.get("responseSha256")) and hash_value(parser_sha), "PENDING_PROVENANCE_REFUSED")
    try:
        observed = datetime.fromisoformat(cast(str, stamp).replace("Z", "+00:00"))
        require(observed.utcoffset() == timedelta(0), "PENDING_PROVENANCE_REFUSED")
    except (ValueError, TypeError):
        raise ValueError("PENDING_PROVENANCE_REFUSED") from None
    records = facts.get("records")
    require(type(records) is list and len(records) <= 100, "PENDING_RECORD_LIMIT")
    records = cast(list[Any], records)
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    omitted = dict(nonFootballOpen=0, invalidNativeFields=0)
    for value in records:
        row = mapping(value, "PENDING_NATIVE_ID_REFUSED")
        tip = row.get("tipid")
        require(integer(tip) and tip not in seen, "PENDING_NATIVE_ID_REFUSED")
        tip = cast(int, tip)
        seen.add(tip)
        if type(row.get("vc_sport_id")) is not int or row["vc_sport_id"] != 1 or row.get("result") != "Open":
            omitted["nonFootballOpen"] += 1
            continue
        valid = integer(row.get("eventid")) and all((
            text(row.get("eventname"), 240), text(row.get("selection"), 120),
            text(row.get("market"), 120, empty=True), text(row.get("winew"), 80, empty=True),
            text(row.get("event_datetime"), 40),
        ))
        if not valid:
            omitted["invalidNativeFields"] += 1
            continue
        rows.append(dict(sourceTipId=tip, sourceEventId=row["eventid"], eventText=row["eventname"], selectionText=row["selection"], marketText=row["market"], betTypeText=row["winew"], nativeDateText=row["event_datetime"]))
        require(len(rows) <= MAX_RECORDS, "PENDING_RECORD_LIMIT")
    require(bool(rows), "NO_VALID_PENDING_RECORDS")
    result: dict[str, Any] = dict(
        schemaVersion="olbg-private-pending-profile-observations-v1",
        status="UNQUALIFIED_INDIVIDUAL_PROFILE_OBSERVATIONS", sourceId="SRC_014",
        observedAtUTC=observed.astimezone(UTC).isoformat(), responseSHA256=request["responseSha256"], parserSHA256=parser_sha,
        attribution=dict(kind="SOURCE_PROFILE_ACCOUNT", nativeId=author, label=label, sourceUrl=url, personIdentityVerified=False),
        sourceRecordCount=len(records), records=rows, omitted=omitted,
        competition=None, canonicalFixture=None, kickoffUTC=None, sourceEventTimezone=None,
        publishedAt=None, preMatchProven=False, sourceReady=False, admissions=0,
        eligibleForApplication=False, interpretationAllowed=False, performanceEvaluationAllowed=False,
        settlementAllowed=False, globalCoverage="UNKNOWN",
    )
    require(len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()) <= MAX_BYTES, "PENDING_BYTES_LIMIT")
    return result
