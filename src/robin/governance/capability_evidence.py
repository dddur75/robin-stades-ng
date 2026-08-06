from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = frozenset(
    {
        "NOT_EVALUATED",
        "MEASURED_PARTIAL",
        "READY_STRICT",
        "READY_RECONSTRUCTED",
        "BLOCKED_BY_COVERAGE",
        "BLOCKED_BY_TEMPORALITY",
        "BLOCKED_BY_SOURCE",
        "BLOCKED_BY_DEPENDENCY",
        "STOPPED_LOCAL_CAMPAIGN",
    }
)
ALLOWED_UNKNOWN_POLICIES = frozenset(
    {
        "CONFIRMED_ONLY",
        "GENERIC_UNAVAILABILITY",
        "EXCLUDE_UNKNOWN",
        "INCLUDE_UNKNOWN_AS_UNKNOWN",
        "SENSITIVITY_ANALYSIS",
    }
)
BLOCKING_STATUSES = frozenset(
    {
        "BLOCKED_BY_COVERAGE",
        "BLOCKED_BY_TEMPORALITY",
        "BLOCKED_BY_SOURCE",
        "BLOCKED_BY_DEPENDENCY",
        "STOPPED_LOCAL_CAMPAIGN",
    }
)
READY_STATUSES = frozenset({"READY_STRICT", "READY_RECONSTRUCTED"})
ABSENCE_CAUSES = frozenset(
    {"INJURY_CONFIRMED", "SUSPENSION_CONFIRMED", "ABSENCE_CAUSE_UNKNOWN"}
)
CAPABILITY_FIELDS = frozenset(
    {
        "capability_id",
        "family",
        "source_family",
        "grain",
        "temporal_class",
        "tested_scope",
        "status",
        "depends_on",
        "requires_exact_absence_cause",
        "allows_unknown",
        "unknown_policy",
        "scale_authorized",
        "block_reason",
        "evidence_claims",
    }
)
EXACT_CAUSE_CAPABILITY = "ABSENCE_CAUSE_EXACT"
REQUIRED_EXTERNAL_EFFECTS = {
    "api_football_calls": 0,
    "r2_reads": 0,
    "r2_writes": 0,
    "remote_sql": 0,
    "deployments": 0,
    "publication": False,
    "real_bets": False,
    "promotion": False,
}


class CapabilityContractError(ValueError):
    """Raised when a capability evidence contract is ambiguous or unsafe."""


def load_capability_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapabilityContractError("capability contract must be a JSON object")
    return value


def _require_non_empty_string(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise CapabilityContractError(f"{field} must be a non-empty string")


def _validate_external_effects(document: Mapping[str, Any]) -> None:
    effects = document.get("external_effects")
    if not isinstance(effects, dict) or set(effects) != set(REQUIRED_EXTERNAL_EFFECTS):
        raise CapabilityContractError("external_effects must use the closed required schema")
    for field, expected in REQUIRED_EXTERNAL_EFFECTS.items():
        value = effects[field]
        if type(value) is not type(expected) or value != expected:
            raise CapabilityContractError("all external effects must remain disabled")


def _validate_capability(capability: Mapping[str, Any]) -> None:
    missing = CAPABILITY_FIELDS - capability.keys()
    extra = capability.keys() - CAPABILITY_FIELDS
    if missing or extra:
        raise CapabilityContractError(
            f"invalid capability fields: missing={sorted(missing)}, extra={sorted(extra)}"
        )

    capability_id = capability["capability_id"]
    _require_non_empty_string(capability_id, field="capability_id")
    for field in (
        "family",
        "source_family",
        "grain",
        "temporal_class",
        "tested_scope",
        "block_reason",
    ):
        _require_non_empty_string(capability[field], field=f"{capability_id}.{field}")

    status = capability["status"]
    if status == "READY" or status not in ALLOWED_STATUSES:
        raise CapabilityContractError(f"{capability_id} has forbidden status {status!r}")
    if capability["unknown_policy"] not in ALLOWED_UNKNOWN_POLICIES:
        raise CapabilityContractError(f"{capability_id} has an invalid unknown policy")
    if not isinstance(capability["depends_on"], list) or not all(
        isinstance(value, str) and value for value in capability["depends_on"]
    ):
        raise CapabilityContractError(f"{capability_id}.depends_on must contain IDs")
    if not isinstance(capability["evidence_claims"], list) or not all(
        isinstance(value, str) and value for value in capability["evidence_claims"]
    ):
        raise CapabilityContractError(f"{capability_id}.evidence_claims must contain IDs")
    for field in ("requires_exact_absence_cause", "allows_unknown", "scale_authorized"):
        if not isinstance(capability[field], bool):
            raise CapabilityContractError(f"{capability_id}.{field} must be boolean")
    if capability["scale_authorized"] and status not in READY_STATUSES:
        raise CapabilityContractError(f"{capability_id} cannot scale from status {status}")
    if status in READY_STATUSES and (
        capability["tested_scope"] == "NONE" or not capability["evidence_claims"]
    ):
        raise CapabilityContractError(
            f"{capability_id} cannot be ready without tested scope and evidence"
        )
    if status == "NOT_EVALUATED" and capability["evidence_claims"]:
        raise CapabilityContractError(
            f"{capability_id} is not evaluated and cannot assert evidence claims"
        )
    if (
        capability["requires_exact_absence_cause"]
        and capability_id != EXACT_CAUSE_CAPABILITY
        and EXACT_CAUSE_CAPABILITY not in capability["depends_on"]
    ):
        raise CapabilityContractError(
            f"{capability_id} requires exact absence cause without declaring the dependency"
        )


def _validate_dependency_graph(capabilities: Mapping[str, Mapping[str, Any]]) -> None:
    for capability_id, capability in capabilities.items():
        for dependency in capability["depends_on"]:
            if dependency not in capabilities:
                raise CapabilityContractError(
                    f"{capability_id} depends on unknown capability {dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(capability_id: str) -> None:
        if capability_id in visiting:
            raise CapabilityContractError("capability dependency graph contains a cycle")
        if capability_id in visited:
            return
        visiting.add(capability_id)
        for dependency in capabilities[capability_id]["depends_on"]:
            visit(dependency)
        visiting.remove(capability_id)
        visited.add(capability_id)

    for capability_id in capabilities:
        visit(capability_id)


def _resolve_effective_statuses(
    capabilities: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    resolved: dict[str, str] = {}

    def resolve(capability_id: str) -> str:
        if capability_id in resolved:
            return resolved[capability_id]
        capability = capabilities[capability_id]
        dependency_statuses = [resolve(value) for value in capability["depends_on"]]
        declared_status = str(capability["status"])
        if declared_status in BLOCKING_STATUSES:
            effective_status = declared_status
        elif any(value in BLOCKING_STATUSES for value in dependency_statuses):
            effective_status = "BLOCKED_BY_DEPENDENCY"
        else:
            effective_status = declared_status
        resolved[capability_id] = effective_status
        return effective_status

    for capability_id in capabilities:
        resolve(capability_id)
    return resolved


def validate_capability_contract(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != "capability-scoped-evidence-ladder-v2":
        raise CapabilityContractError("unexpected schema_version")
    if set(document.get("allowed_statuses", [])) != ALLOWED_STATUSES:
        raise CapabilityContractError("allowed_statuses must match the closed V2 vocabulary")
    if set(document.get("allowed_unknown_policies", [])) != ALLOWED_UNKNOWN_POLICIES:
        raise CapabilityContractError("unknown policy vocabulary is incomplete")
    if document.get("global_readiness") != "NOT_DETERMINED_BY_E1A":
        raise CapabilityContractError("E1A cannot determine global P0 readiness")
    if document.get("e1a_campaign_status") != "STOPPED_LOCAL_CAMPAIGN":
        raise CapabilityContractError("the E1A exact-cause campaign must remain locally stopped")
    _validate_external_effects(document)

    raw_capabilities = document.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise CapabilityContractError("capabilities must be a non-empty list")
    capabilities: dict[str, Mapping[str, Any]] = {}
    for raw_capability in raw_capabilities:
        if not isinstance(raw_capability, dict):
            raise CapabilityContractError("each capability must be an object")
        _validate_capability(raw_capability)
        capability_id = raw_capability["capability_id"]
        if capability_id in capabilities:
            raise CapabilityContractError(f"duplicate capability {capability_id}")
        capabilities[capability_id] = raw_capability

    exact_cause = capabilities.get(EXACT_CAUSE_CAPABILITY)
    if exact_cause is None or exact_cause["status"] != "STOPPED_LOCAL_CAMPAIGN":
        raise CapabilityContractError("ABSENCE_CAUSE_EXACT must be locally stopped")
    _validate_dependency_graph(capabilities)
    effective_statuses = _resolve_effective_statuses(capabilities)
    for capability_id, capability in capabilities.items():
        if capability["status"] not in READY_STATUSES:
            continue
        dependencies = capability["depends_on"]
        if any(effective_statuses[value] not in READY_STATUSES for value in dependencies):
            raise CapabilityContractError(
                f"{capability_id} cannot be ready before all dependencies are ready"
            )
        if effective_statuses[capability_id] not in READY_STATUSES:
            raise CapabilityContractError(
                f"{capability_id} cannot be ready while effectively blocked"
            )


def resolve_effective_statuses(document: Mapping[str, Any]) -> dict[str, str]:
    validate_capability_contract(document)
    capabilities = {
        capability["capability_id"]: capability for capability in document["capabilities"]
    }
    return _resolve_effective_statuses(capabilities)


def preserve_absence_cause(value: str) -> str:
    if value not in ABSENCE_CAUSES:
        raise CapabilityContractError(f"unsupported absence cause {value!r}")
    return value


__all__ = [
    "ALLOWED_STATUSES",
    "ALLOWED_UNKNOWN_POLICIES",
    "CapabilityContractError",
    "load_capability_contract",
    "preserve_absence_cause",
    "resolve_effective_statuses",
    "validate_capability_contract",
]
