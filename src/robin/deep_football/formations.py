"""Conservative formation normalization and tactical families."""

from __future__ import annotations

import re
from dataclasses import dataclass

CANONICAL_FORMATIONS = {
    "4-3-3",
    "4-2-3-1",
    "4-4-2",
    "4-1-4-1",
    "3-4-3",
    "3-5-2",
    "5-3-2",
    "5-4-1",
}


@dataclass(frozen=True, slots=True)
class NormalizedFormation:
    raw: str
    normalized: str | None
    confidence: float
    ambiguous: bool
    families: tuple[str, ...]


def _families(formation: str) -> tuple[str, ...]:
    lines = tuple(int(value) for value in formation.split("-"))
    output: list[str] = []
    if lines[0] == 4:
        output.append("BACK_FOUR")
    elif lines[0] == 3:
        output.append("BACK_THREE")
    elif lines[0] == 5:
        output.append("BACK_FIVE")
    midfield = sum(lines[1:-1])
    if midfield == 3:
        output.append("MIDFIELD_THREE")
    if midfield == 4:
        output.append("MIDFIELD_FOUR")
    if lines[-1] == 3:
        output.append("FRONT_THREE")
    elif lines[-1] == 2:
        output.append("FRONT_TWO")
    elif lines[-1] == 1:
        output.append("SINGLE_STRIKER")
    return tuple(output)


def normalize_formation(raw: str | None) -> NormalizedFormation:
    if raw is None or not raw.strip():
        return NormalizedFormation(raw or "", None, 0.0, True, ())
    compact = re.sub(r"\s+", "", raw).replace("–", "-").replace("—", "-")
    compact = compact.replace("/", "-")
    if compact in CANONICAL_FORMATIONS:
        return NormalizedFormation(
            raw,
            compact,
            1.0,
            False,
            _families(compact),
        )
    digits = re.findall(r"\d+", compact)
    if len(digits) >= 3 and sum(int(value) for value in digits) == 10:
        candidate = "-".join(digits)
        if candidate in CANONICAL_FORMATIONS:
            return NormalizedFormation(
                raw,
                candidate,
                0.9,
                False,
                _families(candidate),
            )
    return NormalizedFormation(raw, None, 0.0, True, ())
