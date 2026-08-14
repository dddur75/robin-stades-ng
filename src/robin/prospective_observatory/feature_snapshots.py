"""Point-in-time feature snapshots with explicit missingness and provenance."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Mapping

from robin.prospective_observatory.contracts import (
    CaptureFamily,
    canonical_sha256,
    ensure_utc,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FeatureSnapshot,
    PredictionMarket,
    source_receipt_from_provenance,
)
from robin.prospective_observatory.prequential_storage import (
    PrequentialArtifactRepository,
)
from robin.prospective_observatory.r2 import (
    R2_NAMESPACE,
    ProspectiveR2Repository,
    operational_odds_replay_projection,
    project_odds_rows,
)
from robin.temporal.lineage import (
    SourceReceipt,
    TemporalProofLevel,
    freeze_json,
    parse_utc,
    thaw_json,
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

SOURCE_OBSERVATION_SCHEMA_VERSION = "prequential-source-observation-v1"
_UNBOUND_SOURCE_VALUE = object()
_UNBOUND_SOURCE_PAYLOAD = object()


def _float_matches(value: object, expected: float, *, abs_tol: float) -> bool:
    return isinstance(value, (int, float)) and math.isclose(
        float(value),
        expected,
        rel_tol=0.0,
        abs_tol=abs_tol,
    )


def _source_observation_manifest(
    receipt: SourceReceipt,
    *,
    payload: object,
) -> dict[str, object]:
    return {
        "schema_version": SOURCE_OBSERVATION_SCHEMA_VERSION,
        "source_name": receipt.source_name,
        "request_identity": receipt.request_identity,
        "source_published_at": (
            receipt.source_published_at.isoformat()
            if receipt.source_published_at is not None
            else None
        ),
        "robin_first_observed_at": receipt.robin_first_observed_at.isoformat(),
        "robin_ingested_at": receipt.robin_ingested_at.isoformat(),
        "capture_code_revision": receipt.capture_code_revision,
        "availability_status": receipt.availability_status.value,
        "supersedes_receipt_id": receipt.supersedes_receipt_id,
        "event_at": receipt.event_at.isoformat() if receipt.event_at else None,
        "payload": payload,
    }


def persist_source_receipt(
    repository: PrequentialArtifactRepository,
    *,
    source_name: str,
    request_identity: str,
    payload: object,
    observed_at: datetime,
    ingested_at: datetime,
    code_revision: str,
    source_published_at: datetime | None = None,
    event_at: datetime | None = None,
    supersedes_receipt_id: str | None = None,
    availability_status: TemporalProofLevel | None = None,
) -> SourceReceipt:
    """Persist one synthetic/local observation before exposing its receipt."""

    observed = parse_utc(observed_at, field="robin_first_observed_at")
    ingested = parse_utc(ingested_at, field="robin_ingested_at")
    published = (
        parse_utc(source_published_at, field="source_published_at")
        if source_published_at is not None
        else None
    )
    event = parse_utc(event_at, field="event_at") if event_at is not None else None
    frozen_payload = thaw_json(freeze_json(payload))
    proof_level = availability_status or (
        TemporalProofLevel.SOURCE_AND_RECEIPT_ATTESTED
        if published is not None
        else TemporalProofLevel.RECEIPT_ATTESTED
    )
    provisional_receipt = SourceReceipt.create(
        source_name=source_name,
        request_identity=request_identity,
        payload_sha256="0" * 64,
        source_published_at=published,
        robin_first_observed_at=observed,
        robin_ingested_at=ingested,
        capture_code_revision=code_revision,
        storage_identity="pending://content-addressed-source-observation",
        availability_status=proof_level,
        supersedes_receipt_id=supersedes_receipt_id,
        event_at=event,
    )
    stored = repository.put_manifest(
        "source-observations",
        _source_observation_manifest(
            provisional_receipt,
            payload=frozen_payload,
        ),
    )
    receipt = SourceReceipt.create(
        source_name=source_name,
        request_identity=request_identity,
        payload_sha256=stored.sha256,
        source_published_at=published,
        robin_first_observed_at=observed,
        robin_ingested_at=ingested,
        capture_code_revision=code_revision,
        storage_identity=stored.key,
        availability_status=provisional_receipt.availability_status,
        supersedes_receipt_id=supersedes_receipt_id,
        event_at=event,
    )
    payload_fixture_id = (
        str(frozen_payload.get("fixture_id"))
        if isinstance(frozen_payload, Mapping)
        and frozen_payload.get("fixture_id") is not None
        else None
    )
    payload_fixture_record_id = (
        str(frozen_payload.get("fixture_record_id"))
        if isinstance(frozen_payload, Mapping)
        and frozen_payload.get("fixture_record_id") is not None
        else None
    )
    verify_source_receipt_artifact(
        repository,
        receipt,
        expected_fixture_id=payload_fixture_id,
        expected_fixture_record_id=payload_fixture_record_id,
    )
    return receipt


def verify_source_receipt_artifact(
    repository: PrequentialArtifactRepository,
    receipt: SourceReceipt,
    *,
    expected_family: str | None = None,
    expected_value: object = _UNBOUND_SOURCE_VALUE,
    expected_payload: object = _UNBOUND_SOURCE_PAYLOAD,
    expected_fixture_id: str | None = None,
    expected_fixture_record_id: str | None = None,
) -> None:
    """Verify the immutable bytes that attest a source receipt."""

    if receipt.storage_identity.startswith(f"{repository.namespace}/"):
        raw = repository.read_verified(
            receipt.storage_identity,
            receipt.payload_sha256,
        )
        try:
            manifest = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_JSON_INVALID") from error
        if not isinstance(manifest, dict) or "payload" not in manifest:
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_MANIFEST_INVALID")
        if manifest != _source_observation_manifest(
            receipt,
            payload=manifest["payload"],
        ):
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_MANIFEST_MISMATCH")
        payload = manifest["payload"]
        if (
            expected_fixture_id is not None
            or expected_fixture_record_id is not None
        ) and (
            not isinstance(payload, Mapping)
            or payload.get("fixture_id") != expected_fixture_id
            or payload.get("fixture_record_id")
            != expected_fixture_record_id
        ):
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_FIXTURE_MISMATCH")
        if expected_payload is not _UNBOUND_SOURCE_PAYLOAD and thaw_json(
            freeze_json(payload)
        ) != thaw_json(freeze_json(expected_payload)):
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_PROJECTION_MISMATCH")
        if expected_value is not _UNBOUND_SOURCE_VALUE:
            if (
                not isinstance(payload, Mapping)
                or payload.get("family") != expected_family
                or "value" not in payload
                or thaw_json(freeze_json(payload["value"]))
                != thaw_json(freeze_json(expected_value))
            ):
                raise ValueError("FEATURE_SOURCE_RECEIPT_VALUE_MISMATCH")
        if (
            isinstance(payload, Mapping)
            and payload.get("schema_version")
            == "prequential-prospective-source-closure-v1"
        ):
            # This closure schema implements one raw projection only: an odds
            # capture becomes the market feature below.  Content addressing
            # cannot authorize relabeling those same bytes as team, lineup,
            # injuries, or another feature family.
            if payload.get("family") != "market":
                raise ValueError(
                    "PREQUENTIAL_SOURCE_RECEIPT_RAW_FAMILY_MISMATCH"
                )
            raw_receipt_key = str(payload.get("raw_receipt_r2_key", ""))
            raw_capture = ProspectiveR2Repository(repository.store).read_capture(
                raw_receipt_key
            )
            raw_receipt = raw_capture.receipt
            index_evidence = payload.get("payload_index")
            if not isinstance(index_evidence, Mapping):
                raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_R2_MISMATCH")
            try:
                indexed_at = parse_utc(
                    str(index_evidence.get("indexed_at")),
                    field="payload_index_indexed_at",
                )
                consumable_at = parse_utc(
                    str(index_evidence.get("consumable_at")),
                    field="payload_index_consumable_at",
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError(
                    "PREQUENTIAL_SOURCE_RECEIPT_R2_MISMATCH"
                ) from error
            expected_consumable_at = max(
                raw_receipt.materialized_at,
                indexed_at,
            )
            if (
                receipt.availability_status
                is not TemporalProofLevel.PROSPECTIVE_CAPTURED
                or raw_receipt.family is not CaptureFamily.ODDS
                or not raw_receipt.temporally_admissible
                or receipt.request_identity != raw_receipt.receipt_hash
                or receipt.source_name != raw_receipt.provider
                or payload.get("raw_receipt_hash") != raw_receipt.receipt_hash
                or payload.get("raw_payload_sha256")
                != raw_receipt.payload_sha256
                or payload.get("raw_payload_r2_key") != raw_receipt.r2_key
                or (
                    expected_fixture_id is not None
                    and raw_receipt.fixture_id != expected_fixture_id
                )
                or receipt.source_published_at
                != raw_receipt.provider_updated_at
                or receipt.robin_first_observed_at
                != raw_receipt.response_received_at
                or receipt.robin_ingested_at
                != consumable_at
                or consumable_at != expected_consumable_at
                or receipt.capture_code_revision != raw_receipt.code_revision
                or receipt.event_at != raw_receipt.event_time
            ):
                raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_R2_MISMATCH")
            if payload.get("family") == "market":
                value = payload.get("value")
                if not isinstance(value, Mapping):
                    raise ValueError(
                        "PREQUENTIAL_SOURCE_RECEIPT_RAW_PROJECTION_MISMATCH"
                    )
                decimal_odds = value.get("decimal_odds")
                bookmaker = value.get("bookmaker")
                margin = value.get("margin")
                coverage = value.get("coverage")
                if (
                    not isinstance(decimal_odds, Mapping)
                    or not isinstance(bookmaker, str)
                    or not isinstance(margin, (int, float))
                    or coverage != 1.0
                ):
                    raise ValueError(
                        "PREQUENTIAL_SOURCE_RECEIPT_RAW_PROJECTION_MISMATCH"
                    )
                selections = set(decimal_odds)
                market = (
                    "1X2"
                    if selections == {"HOME", "DRAW", "AWAY"}
                    else "OVER_UNDER_2_5"
                    if selections == {"OVER", "UNDER"}
                    else None
                )
                try:
                    projection = operational_odds_replay_projection(
                        raw_receipt,
                        raw_capture.payload,
                    )
                    rows = tuple(
                        row
                        for row in project_odds_rows(raw_receipt, projection)
                        if row.get("bookmaker") == bookmaker
                        and row.get("market") == market
                    )
                except (RuntimeError, TypeError, ValueError) as error:
                    raise ValueError(
                        "PREQUENTIAL_SOURCE_RECEIPT_RAW_PROJECTION_MISMATCH"
                    ) from error
                rows_by_selection = {
                    str(row.get("selection")): row for row in rows
                }
                if (
                    market is None
                    or len(rows_by_selection) != len(rows)
                    or set(rows_by_selection) != selections
                    or any(
                        not isinstance(decimal_odds.get(selection), (int, float))
                        or not _float_matches(
                            rows_by_selection[selection].get("odds"),
                            float(decimal_odds[selection]),
                            abs_tol=1e-15,
                        )
                        for selection in selections
                    )
                    or any(
                        not _float_matches(
                            row.get("margin"),
                            float(margin),
                            abs_tol=1e-12,
                        )
                        for row in rows
                    )
                ):
                    raise ValueError(
                        "PREQUENTIAL_SOURCE_RECEIPT_RAW_PROJECTION_MISMATCH"
                    )
        return
    if receipt.storage_identity.startswith(f"{R2_NAMESPACE}/"):
        if (
            expected_value is not _UNBOUND_SOURCE_VALUE
            or expected_payload is not _UNBOUND_SOURCE_PAYLOAD
        ):
            raise ValueError("FEATURE_SOURCE_RECEIPT_VALUE_BINDING_MISSING")
        capture = ProspectiveR2Repository(repository.store).read_capture(
            receipt.storage_identity
        ).receipt
        if (
            receipt.availability_status is not TemporalProofLevel.PROSPECTIVE_CAPTURED
            or receipt.request_identity != capture.receipt_hash
            or receipt.source_name != capture.provider
            or receipt.payload_sha256 != capture.payload_sha256
            or receipt.source_published_at != capture.provider_updated_at
            or receipt.robin_first_observed_at != capture.response_received_at
            or receipt.robin_ingested_at != capture.materialized_at
            or receipt.capture_code_revision != capture.code_revision
            or receipt.storage_identity != capture.receipt_r2_key
            or receipt.event_at != capture.event_time
        ):
            raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_R2_MISMATCH")
        return
    raise ValueError("PREQUENTIAL_SOURCE_RECEIPT_STORAGE_UNVERIFIABLE")


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


def feature_snapshot_record_id(
    *,
    fixture_record_id: str,
    fixture_id: str,
    market: PredictionMarket,
    cutoff_name: CutoffName,
    cutoff_at: datetime,
    feature_contract_version: str,
    feature_contract_hash: str,
    values: Mapping[str, object],
    missingness: Mapping[str, bool],
    provenance: Mapping[str, object],
    quality: Mapping[str, object],
    supersedes_id: str | None,
) -> str:
    cutoff = ensure_utc(cutoff_at, field="cutoff_at")
    return "feature-" + canonical_sha256(
        {
            "fixture_record_id": fixture_record_id,
            "fixture_id": fixture_id,
            "market": market.value,
            "cutoff_name": cutoff_name.value,
            "cutoff_at": cutoff.isoformat(),
            "feature_contract_version": feature_contract_version,
            "contract_hash": feature_contract_hash,
            "values": thaw_json(freeze_json(values)),
            "missingness": thaw_json(freeze_json(missingness)),
            "provenance": thaw_json(freeze_json(provenance)),
            "quality": thaw_json(freeze_json(quality)),
            "supersedes_id": supersedes_id,
        }
    )


def verify_feature_snapshot_artifact(
    repository: PrequentialArtifactRepository,
    snapshot: FeatureSnapshot,
) -> None:
    """Verify the R2 bytes and their exact SQL-projected snapshot contract."""

    if (
        set(snapshot.values) != set(FEATURE_FAMILIES)
        or set(snapshot.missingness) != set(FEATURE_FAMILIES)
        or any(
            not isinstance(snapshot.missingness[family], bool)
            for family in FEATURE_FAMILIES
        )
    ):
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_SHAPE_INVALID")
    if snapshot.snapshot_id != feature_snapshot_record_id(
        fixture_record_id=snapshot.fixture_record_id,
        fixture_id=snapshot.fixture_id,
        market=snapshot.market,
        cutoff_name=snapshot.cutoff_name,
        cutoff_at=snapshot.cutoff_at,
        feature_contract_version=snapshot.feature_contract_version,
        feature_contract_hash=snapshot.feature_contract_hash,
        values=snapshot.values,
        missingness=snapshot.missingness,
        provenance=snapshot.provenance,
        quality=snapshot.quality,
        supersedes_id=snapshot.supersedes_id,
    ):
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_ID_INVALID")

    filename = snapshot.r2_manifest_key.rsplit("/", 1)[-1]
    if not filename.endswith(".json"):
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_R2_KEY_INVALID")
    digest = filename.removesuffix(".json")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_R2_KEY_INVALID")
    raw = repository.read_verified(snapshot.r2_manifest_key, digest)
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_R2_JSON_INVALID") from error
    if manifest != snapshot.storage_manifest():
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_R2_MANIFEST_MISMATCH")
    for family, missing in snapshot.missingness.items():
        if missing:
            continue
        evidence = snapshot.provenance.get(family)
        if not isinstance(evidence, Mapping):
            raise ValueError(f"FEATURE_PROVENANCE_REQUIRED:{family}")
        verify_source_receipt_artifact(
            repository,
            source_receipt_from_provenance(evidence),
            expected_family=family,
            expected_value=snapshot.values[family],
            expected_fixture_id=snapshot.fixture_id,
            expected_fixture_record_id=snapshot.fixture_record_id,
        )


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
    cutoff = ensure_utc(cutoff_at, field="cutoff_at")
    created = ensure_utc(created_at, field="created_at")
    normalised_input, missingness = _normalise_missingness(values, availability)
    frozen_values = freeze_json(normalised_input)
    frozen_provenance = freeze_json(
        {
            family: dict(evidence)
            for family, evidence in sorted(provenance.items())
        }
    )
    frozen_quality = freeze_json(dict(quality))
    thawed_values = thaw_json(frozen_values)
    provenance_value = thaw_json(frozen_provenance)
    quality_value = thaw_json(frozen_quality)
    if not isinstance(thawed_values, dict):
        raise ValueError("FEATURE_VALUES_JSON_INVALID")
    if not isinstance(provenance_value, dict):
        raise ValueError("FEATURE_PROVENANCE_JSON_INVALID")
    if not isinstance(quality_value, dict):
        raise ValueError("FEATURE_QUALITY_JSON_INVALID")
    normalised_values: dict[str, object] = {
        str(key): value for key, value in thawed_values.items()
    }
    provenance_dict = {
        str(family): dict(evidence)
        for family, evidence in provenance_value.items()
        if isinstance(evidence, Mapping)
    }
    expected_provenance = {
        family
        for family, is_missing in missingness.items()
        if not is_missing
    }
    if set(provenance_dict) != expected_provenance:
        raise ValueError("FEATURE_PROVENANCE_FAMILY_SET_INVALID")
    for family, is_missing in missingness.items():
        if is_missing:
            continue
        if family not in provenance_dict:
            raise ValueError(f"FEATURE_PROVENANCE_REQUIRED:{family}")
    contract_hash = canonical_sha256(dict(feature_contract))
    snapshot_id = feature_snapshot_record_id(
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff,
        feature_contract_version=feature_contract_version,
        feature_contract_hash=contract_hash,
        values=normalised_values,
        missingness=missingness,
        provenance=provenance_dict,
        quality=quality_value,
        supersedes_id=supersedes_id,
    )
    existing = registry.get(snapshot_id)
    if existing is not None:
        verify_feature_snapshot_artifact(repository, existing)
        return existing
    provisional_manifest: dict[str, object] = {
        "schema_version": "prequential-feature-snapshot-v1",
        "snapshot_id": snapshot_id,
        "fixture_record_id": fixture_record_id,
        "fixture_id": fixture_id,
        "competition": competition,
        "market": market.value,
        "cutoff_name": cutoff_name.value,
        "cutoff_at": cutoff.isoformat(),
        "created_at": created.isoformat(),
        "feature_contract_version": feature_contract_version,
        "feature_contract_hash": contract_hash,
        "values": normalised_values,
        "missingness": missingness,
        "provenance": provenance_dict,
        "quality": quality_value,
        "code_revision": code_revision,
        "supersedes_id": supersedes_id,
        "status": "FROZEN",
    }
    expected_manifest_sha256 = canonical_sha256(provisional_manifest)
    expected_manifest_key = (
        f"{repository.namespace}/feature-snapshots/"
        f"{expected_manifest_sha256}.json"
    )
    snapshot = FeatureSnapshot(
        snapshot_id=snapshot_id,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff,
        created_at=created,
        feature_contract_version=feature_contract_version,
        feature_contract_hash=contract_hash,
        values=normalised_values,
        missingness=missingness,
        provenance=provenance_dict,
        quality=quality_value,
        code_revision=code_revision,
        r2_manifest_key=expected_manifest_key,
        supersedes_id=supersedes_id,
    )
    for family, is_missing in snapshot.missingness.items():
        if is_missing:
            continue
        evidence = snapshot.provenance.get(family)
        if not isinstance(evidence, Mapping):
            raise ValueError(f"FEATURE_PROVENANCE_REQUIRED:{family}")
        verify_source_receipt_artifact(
            repository,
            source_receipt_from_provenance(evidence),
            expected_family=family,
            expected_value=snapshot.values[family],
            expected_fixture_id=snapshot.fixture_id,
            expected_fixture_record_id=snapshot.fixture_record_id,
        )
    stored = repository.put_manifest("feature-snapshots", provisional_manifest)
    if stored.key != expected_manifest_key or stored.sha256 != expected_manifest_sha256:
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_R2_KEY_MISMATCH")
    if snapshot.storage_manifest() != provisional_manifest:
        raise ValueError("PREQUENTIAL_FEATURE_SNAPSHOT_MANIFEST_MISMATCH")
    verify_feature_snapshot_artifact(repository, snapshot)
    registry.append(snapshot)
    return snapshot


__all__ = [
    "FEATURE_FAMILIES",
    "feature_snapshot_record_id",
    "FeatureSnapshotRegistry",
    "freeze_feature_snapshot",
    "persist_source_receipt",
    "verify_feature_snapshot_artifact",
    "verify_source_receipt_artifact",
]
