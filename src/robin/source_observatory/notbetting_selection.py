"""Bounded RAM-only selection, before independent owner/fixture/time qualification.

The caller must bind the exact native competition and supply a shared work budget.
Records retain their input identity for downstream reference checks; never log or
persist them. Only diagnostics are suitable for a closed metadata receipt.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict, cast

MAX_VISITS = 150000
MAX_DEPTH = 32
MAX_RECORDS = 4
_SKIP = re.compile(
    "stats|statistics|recommend|suggest|reco|analysis|description|biography|contact", re.I
)
_GATES = (
    "isReco",
    "isPaid",
    "isPremium",
    "requiresAuth",
    "authenticatedOnly",
    "isLocked",
    "requiresSubscription",
)
_SENSITIVE = ("auth", "token", "cookie", "password", "secret", "session")
_FIELDS = ("competition", "createdAt", "event", "id", "kind", "pick", "status")


class SelectionResult(TypedDict):
    records: list[dict[str, Any]]
    diagnostics: dict[str, int | bool | str]


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("SELECTION_CONTRACT")


def _gated(node: dict[str, Any]) -> bool:
    if any(key in node and (type(node[key]) is not bool or node[key]) for key in _GATES):
        return True
    if "access" in node:
        return True
    return any(
        type(node.get(key)) is str and (len(node[key]) > 512 or _SKIP.search(node[key]))
        for key in ("type", "kind", "__typename")
    )


def _candidate(node: dict[str, Any]) -> bool:
    return (
        all(type(node.get(key)) is str and 0 < len(node[key]) <= 512 for key in _FIELDS)
        and type(node.get("isReco")) is bool
        and type(node.get("tipster")) is dict
    )


def select_records(
    documents: dict[str, Any], *, competition: str, shared_budget: dict[str, int]
) -> SelectionResult:
    """Select at most four supported static matches; never establish source admissibility."""
    _require(type(documents) is dict)
    _require(
        type(competition) is str
        and 0 < len(competition) <= 200
        and competition == competition.strip()
        and re.search(r"[\x00-\x1f\x7f]", competition) is None
    )
    _require(
        type(shared_budget) is dict
        and set(shared_budget) == {"remaining"}
        and type(shared_budget["remaining"]) is int
        and 0 <= shared_budget["remaining"] <= MAX_VISITS
    )
    initial = shared_budget["remaining"]
    reference_work = 0
    records: list[dict[str, Any]] = []
    stack: list[tuple[object, int]] = [(documents, 0)]
    omitted = sensitive = filtered = 0
    at_limit = False

    def resolve_competition(value: object) -> str:
        nonlocal reference_work
        active: tuple[tuple[str, tuple[str, ...]], ...] = ()
        depth = 0

        def touch(value: object) -> None:
            nonlocal reference_work
            _require(shared_budget["remaining"] > len(stack))
            shared_budget["remaining"] -= 1
            reference_work += 1
            _require(depth <= MAX_DEPTH)
            if type(value) is dict:
                _require(not _gated(cast(dict[str, Any], value)))

        def plain(
            reference: str, chain: tuple[tuple[str, tuple[str, ...]], ...], level: int
        ) -> tuple[object, tuple[tuple[str, tuple[str, ...]], ...], int]:
            nonlocal depth
            _require(0 < len(reference) <= 512)
            matched = re.fullmatch(r"\$([a-f0-9]+)((?::[^:\x00-\x1f]+)*)", reference)
            _require(matched is not None)
            assert matched is not None
            key = matched[1]
            path = tuple(matched[2][1:].split(":")) if matched[2] else ()
            _require(
                key == format(int(key, 16), "x") and (key, path) not in chain and len(chain) < 12
            )
            imports: object = documents.get("__flight_import_ids", [])
            _require(type(imports) is list)
            entries = cast(list[object], imports)
            _require(len(entries) <= MAX_VISITS)
            seen: set[str] = set()
            for entry in entries:
                touch(None)
                _require(type(entry) is str and 0 < len(entry) <= 512)
                assert isinstance(entry, str)
                _require(
                    re.fullmatch("[a-f0-9]+", entry) is not None
                    and entry == format(int(entry, 16), "x")
                    and entry not in seen
                )
                seen.add(entry)
            _require(key not in seen and key in documents)
            chain = (*chain, (key, path))
            current: object = documents[key]
            depth = level + 1
            touch(current)
            for segment in path:
                _require(0 < len(segment) <= 512)
                if type(current) is str and current.startswith("$"):
                    current, chain, depth = plain(current, chain, depth)
                _require(
                    not _SKIP.search(segment)
                    and not any(part in segment.casefold() for part in _SENSITIVE)
                )
                if type(current) is dict:
                    mapping = cast(dict[str, object], current)
                    _require(segment in mapping)
                    current = mapping[segment]
                elif type(current) is list:
                    values = cast(list[object], current)
                    _require(
                        len(segment) <= 7
                        and re.fullmatch("0|[1-9][0-9]*", segment) is not None
                        and int(segment) < len(values)
                    )
                    current = values[int(segment)]
                else:
                    raise ValueError("SELECTION_CONTRACT")
                depth += 1
                touch(current)
            if type(current) is str and current.startswith("$"):
                return plain(current, chain, depth)
            return current, chain, depth

        if type(value) is str and value.startswith("$"):
            value, active, depth = plain(value, active, 0)
        _require(type(value) is str and 0 < len(value) <= 512)
        assert isinstance(value, str)
        return value

    while stack:
        if shared_budget["remaining"] < len(stack):
            omitted += 1
            break
        node, depth = stack.pop()
        shared_budget["remaining"] -= 1
        if depth > MAX_DEPTH:
            omitted += 1
            continue
        if type(node) is dict:
            item = cast(dict[str, Any], node)
            if _gated(item):
                filtered += 1
                continue
            if _candidate(item):
                try:
                    resolved_competition = resolve_competition(item["competition"])
                except ValueError:
                    omitted += 1
                else:
                    if resolved_competition == competition:
                        records.append(item)
                        if len(records) == MAX_RECORDS:
                            at_limit = True
                            break
            room = shared_budget["remaining"] - len(stack)
            if 2 * len(item) > room:
                omitted += 1
                continue
            children: list[tuple[object, int]] = []
            for key, child in item.items():
                shared_budget["remaining"] -= 1
                _require(type(key) is str and len(key) <= 512)
                if any(part in key.casefold() for part in _SENSITIVE):
                    sensitive += 1
                elif _SKIP.search(key):
                    filtered += 1
                else:
                    children.append((child, depth + 1))
            stack.extend(reversed(children))
        elif type(node) is list:
            values = cast(list[object], node)
            if len(values) > shared_budget["remaining"] - len(stack):
                omitted += 1
                continue
            stack.extend((child, depth + 1) for child in reversed(values))
        elif type(node) not in (str, int, float, bool, type(None)):
            raise ValueError("SELECTION_CONTRACT")
    stack.clear()
    return {
        "records": records,
        "diagnostics": {
            "schemaVersion": "notbetting-competition-selection-v2",
            "physicalVisitedNodes": initial - shared_budget["remaining"] - reference_work,
            "referenceVisitedNodes": reference_work,
            "selectionVisitedNodes": initial - shared_budget["remaining"],
            "omittedBranches": omitted,
            "prunedSensitiveSubtrees": sensitive,
            "prunedFilteredSubtrees": filtered,
            "selectionLimitReached": at_limit,
            "selectionComplete": not omitted and not at_limit,
            "globalCoverage": "UNKNOWN",
            "sourceReady": False,
            "admissions": 0,
        },
    }
