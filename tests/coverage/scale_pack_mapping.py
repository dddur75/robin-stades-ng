"""Pure fail-closed resolver for the domain-to-Council evidence ladder."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal, cast

LEGACY_SCHEMA = "coverage-scale-pack-manifests-v1"
V2_SCHEMA = "coverage-scale-pack-manifests-v2"


class ScalePackMappingError(ValueError):
    """A stable fail-closed mapping error."""


@dataclass(frozen=True, slots=True)
class StageResolution:
    source_schema_version: str
    requested_stage: str
    canonical_stage: str
    council_stage: str | None
    required_domain_stages: tuple[str, ...]
    legacy_read_only: bool
    can_close_real_cell: bool
    maximum_scope_cells: int
    grants_execution_authority: bool


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScalePackMappingError(code)
    return cast(Mapping[str, object], value)


def _strings(value: object, code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ScalePackMappingError(code)
    return tuple(cast(list[str], value))


def _level_resolution(
    manifest: Mapping[str, object],
    *,
    source_schema_version: str,
    requested_stage: str,
    canonical_stage: str,
    legacy_read_only: bool,
) -> StageResolution:
    levels = _mapping(manifest.get("levels"), "LEVELS_INVALID")
    if canonical_stage not in levels:
        raise ScalePackMappingError("UNKNOWN_STAGE")
    level = _mapping(levels[canonical_stage], "LEVEL_INVALID")
    council = level.get("council_stage")
    if council is not None and not isinstance(council, str):
        raise ScalePackMappingError("COUNCIL_STAGE_INVALID")
    can_close = level.get("can_close_real_cell")
    maximum = level.get("maximum_scope_cells")
    if type(can_close) is not bool or type(maximum) is not int or maximum < 0:
        raise ScalePackMappingError("LEVEL_CLOSURE_POLICY_INVALID")
    requirements = _mapping(
        manifest.get("council_evidence_requirements"),
        "COUNCIL_REQUIREMENTS_INVALID",
    )
    required = () if council is None else _strings(
        requirements.get(council),
        "COUNCIL_REQUIREMENTS_INVALID",
    )
    return StageResolution(
        source_schema_version=source_schema_version,
        requested_stage=requested_stage,
        canonical_stage=canonical_stage,
        council_stage=council,
        required_domain_stages=required,
        legacy_read_only=legacy_read_only,
        can_close_real_cell=can_close,
        maximum_scope_cells=maximum,
        grants_execution_authority=False,
    )


def resolve_stage(
    manifest: Mapping[str, object],
    *,
    source_schema_version: str,
    requested_stage: str,
    operation: Literal["READ", "WRITE"],
) -> StageResolution:
    """Resolve one label without performing filesystem, Council or workload actions."""

    if operation not in {"READ", "WRITE"}:
        raise ScalePackMappingError("UNKNOWN_OPERATION")
    if source_schema_version == LEGACY_SCHEMA:
        if operation == "WRITE":
            raise ScalePackMappingError("LEGACY_SCHEMA_WRITE_FORBIDDEN")
        legacy = _mapping(manifest.get("legacy_read_mapping"), "LEGACY_MAPPING_INVALID")
        if requested_stage not in legacy:
            raise ScalePackMappingError("UNKNOWN_STAGE")
        rule = _mapping(legacy[requested_stage], "LEGACY_MAPPING_INVALID")
        if rule.get("status") == "INCOMPATIBLE":
            raise ScalePackMappingError("LEGACY_E2_50_NOT_V2_E2_100")
        canonical = rule.get("domain_stage")
        if not isinstance(canonical, str):
            raise ScalePackMappingError("LEGACY_MAPPING_INVALID")
        return _level_resolution(
            manifest,
            source_schema_version=source_schema_version,
            requested_stage=requested_stage,
            canonical_stage=canonical,
            legacy_read_only=True,
        )
    if source_schema_version != V2_SCHEMA:
        raise ScalePackMappingError("UNKNOWN_SCALE_PACK_SCHEMA")
    write_policy = _mapping(manifest.get("write_policy"), "WRITE_POLICY_INVALID")
    ambiguous = _strings(
        write_policy.get("ambiguous_domain_labels_forbidden"),
        "WRITE_POLICY_INVALID",
    )
    if operation == "WRITE" and requested_stage in ambiguous:
        raise ScalePackMappingError("AMBIGUOUS_STAGE_WRITE_FORBIDDEN")
    return _level_resolution(
        manifest,
        source_schema_version=source_schema_version,
        requested_stage=requested_stage,
        canonical_stage=requested_stage,
        legacy_read_only=False,
    )


def council_stage_proven(
    manifest: Mapping[str, object],
    *,
    council_stage: str,
    proven_domain_stages: Collection[str],
) -> bool:
    """Return whether the exact domain evidence set proves a Council stage."""

    requirements = _mapping(
        manifest.get("council_evidence_requirements"),
        "COUNCIL_REQUIREMENTS_INVALID",
    )
    if council_stage not in requirements:
        raise ScalePackMappingError("UNKNOWN_COUNCIL_STAGE")
    required = _strings(requirements[council_stage], "COUNCIL_REQUIREMENTS_INVALID")
    return set(required) <= set(proven_domain_stages)


def validate_source_bindings(
    manifest: Mapping[str, object],
    *,
    observed_hashes: Mapping[str, str],
) -> None:
    """Validate already-observed LF hashes without reading the filesystem."""

    bindings = _mapping(manifest.get("source_bindings"), "SOURCE_BINDINGS_INVALID")
    for value in bindings.values():
        binding = _mapping(value, "SOURCE_BINDING_INVALID")
        path = binding.get("path")
        expected = binding.get("file_sha256_lf")
        if not isinstance(path, str) or not isinstance(expected, str):
            raise ScalePackMappingError("SOURCE_BINDING_INVALID")
        if observed_hashes.get(path) != expected:
            raise ScalePackMappingError("SOURCE_HASH_MISMATCH")
