"""Derived availability projection for the frozen 486-property Genome."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Final

from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.ontology import (
    PROPERTY_UNIVERSE,
    property_universe_hash,
)

FAMILY_GATE_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {
    "MATCH_COMPETITION": ("TEAM",),
    "STADIUM_PITCH": ("TEAM", "WEATHER"),
    "WEATHER": ("WEATHER",),
    "TRAVEL_LOGISTICS": ("TEAM",),
    "CALENDAR_FATIGUE": ("TEAM",),
    "STRENGTH_FORM": ("TEAM",),
    "ATTACK": ("TEAM",),
    "DEFENCE": ("TEAM",),
    "POSSESSION_PRESSING": ("TEAM",),
    "SET_PIECES": ("TEAM",),
    "PLAYER": ("PLAYER", "PLAYER_FORM"),
    "FOOTEDNESS_LATERALITY": ("FOOTEDNESS",),
    "LINEUP_CONTINUITY": ("LINEUP", "STARTER_BASELINE"),
    "ABSENCE_RETURN": ("ABSENCE",),
    "DISCIPLINE_REFEREE": ("DISCIPLINE",),
    "FORMATION_STRUCTURE": ("FORMATION",),
    "ROLE_TACTICS": ("PLAYER", "FORMATION"),
    "COACH": ("TEAM",),
    "GOALKEEPER": ("PLAYER", "STARTER_BASELINE"),
    "BENCH_SUBSTITUTIONS": ("PLAYER", "LINEUP"),
    "CHEMISTRY_NETWORKS": ("PLAYER", "LINEUP"),
    "INFORMATION_NEWS": ("ABSENCE",),
    "TRAINING_LOAD": ("PLAYER_FORM",),
    "MEDICAL": ("ABSENCE",),
    "EVENT_GAME_STATE": ("TEAM",),
    "ORGANISATION_SQUAD": ("PLAYER",),
}

READY_STATUSES: Final = {"READY_STRICT", "READY_RECONSTRUCTED"}
BLOCKED_STATUSES: Final = {
    "BLOCKED_BY_COVERAGE",
    "BLOCKED_BY_TEMPORALITY",
    "BLOCKED_BY_SOURCE",
}


def _plain(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        converted = asdict(value)
        if isinstance(converted, Mapping):
            return converted
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        converted = as_dict()
        if isinstance(converted, Mapping):
            return converted
    return {}


def _project_status(
    requirements: Sequence[str],
    gates: Mapping[str, object],
) -> tuple[str, tuple[str, ...]]:
    statuses = tuple(
        str(_plain(gates.get(gate)).get("status", "BLOCKED_BY_SOURCE"))
        for gate in requirements
    )
    if any(status in BLOCKED_STATUSES for status in statuses):
        return "DATA_GATE_BLOCKED", statuses
    if any(status == "PARTIAL" for status in statuses):
        return "PARTIAL", statuses
    if statuses and all(status in READY_STATUSES for status in statuses):
        return (
            "READY_RECONSTRUCTED"
            if "READY_RECONSTRUCTED" in statuses
            else "READY_STRICT",
            statuses,
        )
    return "DATA_GATE_BLOCKED", statuses


def build_genome_availability_projection(
    gates: Mapping[str, object],
) -> dict[str, object]:
    """Recompute availability without mutating any scientific definition."""

    items: list[dict[str, object]] = []
    family_statuses: dict[str, list[str]] = {}
    for definition in PROPERTY_UNIVERSE:
        requirements = FAMILY_GATE_REQUIREMENTS.get(definition.family, ())
        if requirements:
            status, evidence = _project_status(requirements, gates)
            reason = (
                "HISTORICAL_DEEP_GATES:"
                + ",".join(
                    f"{gate}={gate_status}"
                    for gate, gate_status in zip(requirements, evidence, strict=True)
                )
            )
        else:
            status = definition.availability_status.value
            evidence = ()
            reason = "NO_HISTORICAL_DEEP_GATE_MAPPING;FROZEN_STATUS_PRESERVED"
        family_statuses.setdefault(definition.family, []).append(status)
        items.append(
            {
                "property_id": definition.property_id,
                "family": definition.family,
                "scientific_definition_hash": definition.property_hash,
                "frozen_availability_status": definition.availability_status.value,
                "historical_deep_required_gates": list(requirements),
                "historical_deep_gate_statuses": list(evidence),
                "derived_availability_status": status,
                "reason": reason,
            }
        )

    families: dict[str, dict[str, object]] = {}
    for family, statuses in sorted(family_statuses.items()):
        counts = Counter(statuses)
        if all(status in READY_STATUSES for status in statuses):
            status = (
                "READY_RECONSTRUCTED"
                if "READY_RECONSTRUCTED" in counts
                else "READY_STRICT"
            )
        elif counts["DATA_GATE_BLOCKED"] == len(statuses):
            status = "BLOCKED_BY_COVERAGE"
        else:
            status = "PARTIAL"
        families[family] = {
            "status": status,
            "properties": len(statuses),
            "property_status_counts": dict(sorted(counts.items())),
        }

    property_counts = Counter(
        str(item["derived_availability_status"]) for item in items
    )
    family_counts = Counter(str(value["status"]) for value in families.values())
    projection: dict[str, object] = {
        "schema_version": "historical-deep-genome-availability-v1",
        "scientific_definitions_modified": False,
        "frozen_property_universe_hash": property_universe_hash(),
        "properties": len(items),
        "property_status_counts": dict(sorted(property_counts.items())),
        "families": families,
        "family_status_counts": dict(sorted(family_counts.items())),
        "materializable_properties": sum(
            status in READY_STATUSES
            for status in (
                str(item["derived_availability_status"]) for item in items
            )
        ),
        "blocked_properties": property_counts["DATA_GATE_BLOCKED"],
        "items": items,
    }
    projection["projection_hash"] = canonical_sha256(projection)
    return projection


__all__ = [
    "FAMILY_GATE_REQUIREMENTS",
    "build_genome_availability_projection",
]
