"""Point-in-time feature snapshots with explicit missingness and provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FeatureSnapshot,
    PredictionMarket,
)
from robin.prospective_observatory.prequential_storage import (
    PrequentialArtifactRepository,
)

FEATURE_FAMILIES = (
    "market",
    "team",
    "rest",
    "form",
    "players",
    "injuries",
    "lineup",
    "formation",
    "tactical_matchup",
)


class FeatureSnapshotRegistry:
    """Append-only in-process registry used by the factory and deterministic replay."""

    def __init__(self) -> None:
        self._by_id: dict[str, FeatureSnapshot] = {}
        self._by_business_key: dict[
            tuple[str, CutoffName, PredictionMarket, str], list[FeatureSnapshot]
        ] = {}

    @property
    def snapshots(self) -> tuple[FeatureSnapshot, ...]:
        return tuple(self._by_id.values())

    def get(self, snapshot_id: str) -> FeatureSnapshot | None:
        return self._by_id.get(snapshot_id)

    def append(self, snapshot: FeatureSnapshot) -> bool:
        existing = self._by_id.get(snapshot.snapshot_id)
        if existing is not None:
            if existing != snapshot:
                raise ValueError("FEATURE_SNAPSHOT_IDEMPOTENCY_CONFLICT")
            return False
        key = (
            snapshot.fixture_record_id,
            snapshot.cutoff_name,
            snapshot.market,
            snapshot.feature_contract_version,
        )
        versions = self._by_business_key.setdefault(key, [])
        if versions:
            previous = versions[-1]
            if snapshot.supersedes_id != previous.snapshot_id:
                raise ValueError("FEATURE_SNAPSHOT_CORRECTION_LINK_REQUIRED")
            if snapshot.created_at < previous.created_at:
                raise ValueError("FEATURE_SNAPSHOT_CORRECTION_TIME_INVALID")
        elif snapshot.supersedes_id is not None:
            raise ValueError("FEATURE_SNAPSHOT_SUPERSEDES_UNKNOWN")
        self._by_id[snapshot.snapshot_id] = snapshot
        versions.append(snapshot)
        return True


def _normalise_missingness(
    values: Mapping[str, object],
    availability: Mapping[str, bool],
) -> tuple[dict[str, object], dict[str, bool]]:
    unknown = set(values) - set(FEATURE_FAMILIES)
    if unknown:
        raise ValueError(
            f"UNKNOWN_PREQUENTIAL_FEATURE_FAMILY:{','.join(sorted(unknown))}"
        )
    unknown_availability = set(availability) - set(FEATURE_FAMILIES)
    if unknown_availability:
        raise ValueError(
            "UNKNOWN_PREQUENTIAL_AVAILABILITY_FAMILY:"
            + ",".join(sorted(unknown_availability))
        )
    normalised: dict[str, object] = {}
    missingness: dict[str, bool] = {}
    for family in FEATURE_FAMILIES:
        available = bool(availability.get(family, False))
        value = values.get(family)
        if not available:
            if value not in (None, {}, [], ()):
                raise ValueError("BLOCKED_FEATURE_MUST_BE_EXPLICITLY_MISSING")
            normalised[family] = None
            missingness[family] = True
        else:
            if value is None:
                raise ValueError("AVAILABLE_FEATURE_VALUE_REQUIRED")
            normalised[family] = value
            missingness[family] = False
    return normalised, missingness


def freeze_feature_snapshot(
    *,
    repository: PrequentialArtifactRepository,
    registry: FeatureSnapshotRegistry,
    fixture_record_id: str,
    fixture_id: str,
    competition: str,
    market: PredictionMarket,
    cutoff_name: CutoffName,
    cutoff_at: datetime,
    created_at: datetime,
    feature_contract_version: str,
    feature_contract: Mapping[str, object],
    values: Mapping[str, object],
    availability: Mapping[str, bool],
    provenance: Mapping[str, Mapping[str, object]],
    quality: Mapping[str, object],
    code_revision: str,
    supersedes_id: str | None = None,
) -> FeatureSnapshot:
    normalised_values, missingness = _normalise_missingness(values, availability)
    provenance_dict = {
        family: dict(evidence)
        for family, evidence in sorted(provenance.items())
    }
    for family, is_missing in missingness.items():
        if is_missing:
            continue
        if family not in provenance_dict:
            raise ValueError(f"FEATURE_PROVENANCE_REQUIRED:{family}")
    contract_hash = canonical_sha256(dict(feature_contract))
    identity = canonical_sha256(
        {
            "fixture_record_id": fixture_record_id,
            "fixture_id": fixture_id,
            "market": market.value,
            "cutoff_name": cutoff_name.value,
            "cutoff_at": cutoff_at.isoformat(),
            "feature_contract_version": feature_contract_version,
            "contract_hash": contract_hash,
            "values": normalised_values,
            "missingness": missingness,
            "provenance": provenance_dict,
            "quality": dict(quality),
            "supersedes_id": supersedes_id,
        }
    )
    snapshot_id = f"feature-{identity}"
    existing = registry.get(snapshot_id)
    if existing is not None:
        return existing
    provisional_manifest: dict[str, object] = {
        "schema_version": "prequential-feature-snapshot-v1",
        "snapshot_id": snapshot_id,
        "fixture_record_id": fixture_record_id,
        "fixture_id": fixture_id,
        "competition": competition,
        "market": market.value,
        "cutoff_name": cutoff_name.value,
        "cutoff_at": cutoff_at.isoformat(),
        "created_at": created_at.isoformat(),
        "feature_contract_version": feature_contract_version,
        "feature_contract_hash": contract_hash,
        "values": normalised_values,
        "missingness": missingness,
        "provenance": provenance_dict,
        "quality": dict(quality),
        "code_revision": code_revision,
        "supersedes_id": supersedes_id,
        "status": "FROZEN",
    }
    stored = repository.put_manifest("feature-snapshots", provisional_manifest)
    snapshot = FeatureSnapshot(
        snapshot_id=snapshot_id,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        created_at=created_at,
        feature_contract_version=feature_contract_version,
        feature_contract_hash=contract_hash,
        values=normalised_values,
        missingness=missingness,
        provenance=provenance_dict,
        quality=dict(quality),
        code_revision=code_revision,
        r2_manifest_key=stored.key,
        supersedes_id=supersedes_id,
    )
    registry.append(snapshot)
    return snapshot


__all__ = [
    "FEATURE_FAMILIES",
    "FeatureSnapshotRegistry",
    "freeze_feature_snapshot",
]
