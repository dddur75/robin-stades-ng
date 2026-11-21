"""Pure lexical projection, never eval/JavaScript; records remain unadmitted."""

import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from .forum_tipsters import _walk
from .public_formats import _Tree
from .recurring import instant

_TOKEN = re.compile(
    r'"(?:[^"\\]|\\.)*"|\x27(?:[^\x27\\]|\\.)*\x27|/\*[\s\S]*?\*/|//[^\r\n]*|`(?:[^`\\]|\\.)*`|[A-Za-z_$][\w$]*|-?\d+(?:\.\d+)?|[^\s]'
)
_FIELDS = {
    "tipid",
    "selection",
    "eventname",
    "market",
    "winew",
    "odds",
    "result",
    "eventid",
    "event_datetime",
    "vc_sport_id",
    "hcap",
    "hcap_market",
}


def _scalar(v: str) -> Any:
    if v.startswith('"'):
        return json.loads(v)
    if v in ["true", "false", "null"]:
        return json.loads(v)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", v):
        return json.loads(v)
    raise ValueError("not a data scalar")


def _end_literal(tokens: list[str], start: int) -> int:
    pairs = {"{": "}", "[": "]"}
    stack = []
    for i in range(start, len(tokens)):
        t = tokens[i]
        if t in pairs:
            stack.append(pairs[t])
        elif t in ["}", "]"]:
            if not stack or stack.pop() != t:
                raise ValueError("unbalanced data")
            if not stack:
                return i
    raise ValueError("truncated data")


def _elements(tokens: list[str], start: int) -> list[int]:
    """Only immediate object elements; nested recommendations never become tips."""
    end = _end_literal(tokens, start)
    out = []
    i = start + 1
    while i < end:
        if tokens[i] != "{":
            raise ValueError("object array required")
        out.append(i)
        i = _end_literal(tokens, i) + 1
        if i < end:
            if tokens[i] != ",":
                raise ValueError("array expression")
            i += 1
    return out


def _properties(tokens: list[str], start: int) -> dict[str, int]:
    end = _end_literal(tokens, start)
    fields = {}
    i = start + 1
    while i < end:
        key = tokens[i]
        if key.startswith('"'):
            key = _scalar(key)
        if key in fields or tokens[i + 1] != ":":
            raise ValueError("ambiguous object field")
        fields[key] = i + 2
        value = i + 2
        i = _end_literal(tokens, value) + 1 if tokens[value] in ["{", "["] else value + 1
        if i < end:
            if tokens[i] != ",":
                raise ValueError("object scalar expression")
            i += 1
    return fields


def extract_profile(body: bytes, expected_author_id: int | None = None) -> dict[str, Any]:
    tree = _Tree()
    tree.feed(body.decode("utf-8"))
    scripts = [
        "".join(c for c in n.children if isinstance(c, str))
        for n in _walk(tree.root)
        if n.tag == "script" and not n.attrs.get("src")
    ]
    scripts = [s for s in scripts if "effectiveTipsterId:" in s and "tipsByDate:" in s]
    if len(scripts) != 1:
        raise ValueError("unique profile hydration absent")
    s = scripts[0]
    tokens = [t for t in _TOKEN.findall(s) if not t.startswith(("/*", "//"))]
    out: list[dict[str, Any]] = []
    stack = []
    arrays = []
    for i, t in enumerate(tokens):
        if t == "{":
            stack.append(i)
        elif t == "}":
            if stack:
                stack.pop()
        elif t == "tipsByDate" and tokens[i + 1 : i + 3] == [":", "["] and stack:
            arrays.append((stack[-1], i + 2))
    if len(arrays) != 1:
        raise ValueError("unique personal array absent")
    parent, start = arrays[0]
    owner: dict[str, Any] = {}
    depth = 0
    for i in range(parent, _end_literal(tokens, parent) + 1):
        t = tokens[i]
        if t in ["{", "["]:
            depth += 1
        elif t in ["}", "]"]:
            depth -= 1
        elif (
            depth == 1
            and t in ["effectiveTipsterId", "tipsterUsername", "mode"]
            and tokens[i + 1] == ":"
        ):
            if t in owner:
                raise ValueError("ambiguous profile")
            if tokens[i + 3] not in [",", "}"]:
                raise ValueError("profile scalar expression")
            owner[t] = _scalar(tokens[i + 2])
    if (
        owner.get("mode") != "current"
        or not isinstance(owner.get("effectiveTipsterId"), int)
        or not owner.get("tipsterUsername")
        or (expected_author_id is not None and owner["effectiveTipsterId"] != expected_author_id)
    ):
        raise ValueError("current author not established")
    for day in _elements(tokens, start):
        day_fields = _properties(tokens, day)
        events = day_fields.get("events")
        if events is None or tokens[events] != "[":
            raise ValueError("personal events array absent")
        for event in _elements(tokens, events):
            tips = _properties(tokens, event).get("tips")
            if tips is None or tokens[tips] != "[":
                raise ValueError("personal tips array absent")
            for tip in _elements(tokens, tips):
                fields = _properties(tokens, tip)
                row = {
                    key: _scalar(tokens[index]) for key, index in fields.items() if key in _FIELDS
                }
                if "tipid" not in row:
                    raise ValueError("personal tip identifier absent")
                out.append(row)
    return dict(
        authorId=owner["effectiveTipsterId"],
        authorLabel=owner["tipsterUsername"],
        mode="current",
        records=out,
        scope="unadmitted source facts only; no analysis, tracking, session or affiliate fields",
    )


def _team(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum())


def admit_facts(
    facts: dict[str, Any],
    profile_url: str,
    observed: datetime,
    fixtures: list[dict[str, Any]],
    *,
    response_sha: str,
    parser_sha: str,
    calendar_sha: str,
) -> list[dict[str, Any]]:
    """Admit source-native selections without inventing a betting contract or timezone."""
    match = re.fullmatch(r"https://www\.olbg\.com/tipsters/tips/([0-9]+)", profile_url)
    if (
        not match
        or type(facts.get("authorId")) is not int
        or int(match[1]) != facts["authorId"]
        or facts.get("mode") != "current"
        or observed.utcoffset() is None
    ):
        raise ValueError("profile attribution absent")
    if not isinstance(facts.get("authorLabel"), str) or not 0 < len(facts["authorLabel"]) <= 80:
        raise ValueError("author label absent")
    if any(
        re.fullmatch(r"[a-f0-9]{64}", s) is None for s in [response_sha, parser_sha, calendar_sha]
    ):
        raise ValueError("invalid evidence SHA-256")
    observed = observed.astimezone(UTC)
    out = []
    seen = set()
    for row in facts["records"]:
        tid = row.get("tipid")
        if type(tid) is not int or tid <= 0 or tid in seen:
            raise ValueError("duplicate or invalid source tip")
        seen.add(tid)
        if (
            type(row.get("eventid")) is not int
            or row["eventid"] <= 0
            or row.get("vc_sport_id") != 1
            or row.get("result") != "Open"
            or row.get("winew") != "Win"
            or row.get("market") != ""
            or row.get("hcap_market") is not False
        ):
            continue
        names = re.split(r"\s+v(?:s\.?)?\s+", row.get("eventname", ""), flags=re.I)
        if len(names) != 2:
            continue
        matches = [
            f
            for f in fixtures
            if _team(names[0]) in {_team(a) for a in f["homeAliases"]}
            and _team(names[1]) in {_team(a) for a in f["awayAliases"]}
        ]
        if len(matches) != 1:
            continue
        fixture = matches[0]
        kickoff = instant(fixture["kickoff"])
        try:
            source_date = datetime.strptime(row["event_datetime"], "%Y-%m-%d %H:%M:%S").date()
        except (ValueError, TypeError, KeyError):
            continue
        if observed >= kickoff or source_date != kickoff.date():
            continue
        selection = row.get("selection")
        aliases = fixture["homeAliases"] + fixture["awayAliases"] + ["Draw"]
        if not isinstance(selection, str) or _team(selection) not in {_team(a) for a in aliases}:
            continue
        out.append(
            dict(
                id=f"olbg-tip:{tid}",
                sourceId="SRC_014",
                authorId=f"olbg:{facts['authorId']}",
                authorLabel=facts["authorLabel"],
                authorUrl=profile_url,
                sourceUrl=profile_url,
                sourceTipId=tid,
                sourceEventId=row.get("eventid"),
                fixtureId=fixture["id"],
                fixtureLabel=fixture["label"],
                kickoff=fixture["kickoff"],
                selection=selection,
                market="source_native",
                marketLabel="Choix publié (Win)",
                sourceMarketLabel="",
                sourceBetType="Win",
                sourceEventLocalText=row["event_datetime"],
                sourceEventTimezone=None,
                publishedAt=None,
                publishedCivilDate=None,
                observedAt=observed.isoformat(),
                firstSeenAt=observed.isoformat(),
                odds=row.get("odds"),
                performanceEvaluationAllowed=False,
                responseSha256=response_sha,
                parserSha256=parser_sha,
                calendarSha256=calendar_sha,
                versions=[dict(selection=selection, observedAt=observed.isoformat())],
                versionCount=1,
            )
        )
    return out
