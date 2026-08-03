"""Quality V2, temporal classification, and separated dataset manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final

from robin.historical_deep.replay import canonical_sha256

TEAM_PREMATCH_STRICT: Final = "TEAM_PREMATCH_STRICT"
PLAYER_PREMATCH_STRICT: Final = "PLAYER_PREMATCH_STRICT"
LINEUP_HISTORY_PREMATCH_STRICT: Final = "LINEUP_HISTORY_PREMATCH_STRICT"
TARGET_POST_LINEUP_RECONSTRUCTED: Final = "TARGET_POST_LINEUP_RECONSTRUCTED"
INJURY_INTERVAL_RECONSTRUCTED: Final = "INJURY_INTERVAL_RECONSTRUCTED"
POST_MATCH_DESCRIPTIVE: Final = "POST_MATCH_DESCRIPTIVE"

DATASET_NAMES: Final = (
    TEAM_PREMATCH_STRICT,
    PLAYER_PREMATCH_STRICT,
    LINEUP_HISTORY_PREMATCH_STRICT,
    TARGET_POST_LINEUP_RECONSTRUCTED,
    INJURY_INTERVAL_RECONSTRUCTED,
    POST_MATCH_DESCRIPTIVE,
)

_LINEUP_FAMILIES = {
    "lineup",
    "lineups",
    "lineup_players",
    "formations",
    "formation",
}
_INJURY_FAMILIES = {
    "injury",
    "injuries",
    "suspension",
    "suspensions",
    "sidelined",
    "sidelined_periods",
}
_PLAYER_FAMILIES = {
    "player",
    "players",
    "player_match_statistics",
    "player_statistics",
    "player_season_statistics",
    "lineup_player_statistics",
}
_POST_MATCH_FAMILIES = {
    "events",
    "fixture_events",
    "team_match_statistics",
    "match_statistics",
    "player_match_statistics",
    "player_statistics",
    "scores",
    "result",
    "results",
}

_DEFAULT_USAGES: Final[dict[str, tuple[str, ...]]] = {
    TEAM_PREMATCH_STRICT: (
        "STRICT_PREMATCH",
        "WALK_FORWARD_TRAIN",
        "WALK_FORWARD_TEST",
    ),
    PLAYER_PREMATCH_STRICT: (
        "STRICT_PREMATCH",
        "WALK_FORWARD_TRAIN",
        "WALK_FORWARD_TEST",
    ),
    LINEUP_HISTORY_PREMATCH_STRICT: (
        "STRICT_PREMATCH",
        "WALK_FORWARD_TRAIN",
        "WALK_FORWARD_TEST",
    ),
    TARGET_POST_LINEUP_RECONSTRUCTED: ("RECONSTRUCTED_POST_LINEUP",),
    INJURY_INTERVAL_RECONSTRUCTED: (
        "RECONSTRUCTED_POST_LINEUP",
        "HISTORICAL_RECONSTRUCTION",
    ),
    POST_MATCH_DESCRIPTIVE: (
        "DESCRIPTIVE_POST_MATCH",
        "TARGET_LABEL",
    ),
}

_DEFAULT_FORBIDDEN_USAGES: Final[dict[str, tuple[str, ...]]] = {
    TEAM_PREMATCH_STRICT: ("TARGET_POST_MATCH_FEATURE",),
    PLAYER_PREMATCH_STRICT: ("TARGET_POST_MATCH_FEATURE",),
    LINEUP_HISTORY_PREMATCH_STRICT: ("TARGET_LINEUP", "TARGET_POST_MATCH_FEATURE"),
    TARGET_POST_LINEUP_RECONSTRUCTED: ("STRICT_PREMATCH", "PROSPECTIVE_CLAIM"),
    INJURY_INTERVAL_RECONSTRUCTED: ("STRICT_PREMATCH", "PROSPECTIVE_CLAIM"),
    POST_MATCH_DESCRIPTIVE: (
        "STRICT_PREMATCH",
        "RECONSTRUCTED_POST_LINEUP",
        "PREDICTIVE_FEATURE",
    ),
}

_DEFAULT_CUTOFF_POLICY: Final = {
    TEAM_PREMATCH_STRICT: "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
    PLAYER_PREMATCH_STRICT: "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
    LINEUP_HISTORY_PREMATCH_STRICT: (
        "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF"
    ),
    TARGET_POST_LINEUP_RECONSTRUCTED: "TARGET_LINEUP_POST_RELEASE",
    INJURY_INTERVAL_RECONSTRUCTED: "HISTORICAL_INTERVAL_RECONSTRUCTED",
    POST_MATCH_DESCRIPTIVE: "DESCRIPTIVE_ONLY_NOT_PREDICTIVE",
}


def _datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field.upper()}_INVALID") from exc
    else:
        raise ValueError(f"{field.upper()}_REQUIRED")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field.upper()}_UTC_REQUIRED")
    return result.astimezone(UTC)


def _optional_datetime(value: object, *, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    return _datetime(value, field=field)


def _first(record: Mapping[str, object], fields: Sequence[str]) -> object | None:
    direct = next(
        (
            record[field]
            for field in fields
            if field in record and record[field] not in (None, "")
        ),
        None,
    )
    if direct is not None:
        return direct
    nested = record.get("data")
    if isinstance(nested, Mapping):
        return next(
            (
                nested[field]
                for field in fields
                if field in nested and nested[field] not in (None, "")
            ),
            None,
        )
    return None


def _family(record: Mapping[str, object]) -> str:
    value = _first(record, ("family", "data_family", "endpoint_family", "kind"))
    return str(value or "").strip().casefold()


@dataclass(frozen=True, slots=True)
class TemporalClassification:
    dataset: str
    temporal_class: str
    strict_prematch_usable: bool
    reconstructed: bool
    reason: str
    source_fixture_kickoff: str | None
    target_fixture_kickoff: str
    cutoff_policy: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_temporal_record(
    record: Mapping[str, object],
    *,
    target_fixture_id: str,
    target_fixture_kickoff: datetime | str,
) -> TemporalClassification:
    """Classify one record without ever treating the target as prior history."""

    target_kickoff = _datetime(
        target_fixture_kickoff,
        field="target_fixture_kickoff",
    )
    source_fixture_id = str(
        _first(
            record,
            (
                "source_fixture_id",
                "fixture_id",
                "match_id",
                "provider_fixture_id",
                "canonical_fixture_id",
            ),
        )
        or ""
    )
    source_kickoff_value = _first(
        record,
        (
            "source_fixture_kickoff",
            "fixture_kickoff",
            "kickoff_at",
            "source_kickoff_at",
            "target_kickoff_at",
        ),
    )
    source_kickoff = _optional_datetime(
        source_kickoff_value,
        field="source_fixture_kickoff",
    )
    family = _family(record)
    target_record = source_fixture_id == str(target_fixture_id)
    if (
        not source_fixture_id
        and source_kickoff is not None
        and source_kickoff == target_kickoff
    ):
        target_record = True

    def result(
        dataset: str,
        temporal_class: str,
        strict: bool,
        reconstructed: bool,
        reason: str,
        cutoff_policy: str,
    ) -> TemporalClassification:
        return TemporalClassification(
            dataset=dataset,
            temporal_class=temporal_class,
            strict_prematch_usable=strict,
            reconstructed=reconstructed,
            reason=reason,
            source_fixture_kickoff=(
                source_kickoff.isoformat() if source_kickoff is not None else None
            ),
            target_fixture_kickoff=target_kickoff.isoformat(),
            cutoff_policy=cutoff_policy,
        )

    if family in _INJURY_FAMILIES:
        announced_at = _optional_datetime(
            _first(
                record,
                (
                    "announced_at",
                    "announcement_at",
                    "published_at",
                    "source_published_at",
                ),
            ),
            field="injury_announcement_at",
        )
        if announced_at is None:
            return result(
                INJURY_INTERVAL_RECONSTRUCTED,
                "ANNOUNCEMENT_TIME_UNKNOWN",
                False,
                True,
                "INJURY_ANNOUNCEMENT_NOT_PROVEN_BEFORE_TARGET",
                "HISTORICAL_INTERVAL_RECONSTRUCTED",
            )
        if announced_at >= target_kickoff:
            return result(
                INJURY_INTERVAL_RECONSTRUCTED,
                "FIXTURE_SPECIFIC_POST_HOC",
                False,
                True,
                "INJURY_ANNOUNCEMENT_NOT_STRICTLY_BEFORE_TARGET",
                "HISTORICAL_INTERVAL_RECONSTRUCTED",
            )
        return result(
            INJURY_INTERVAL_RECONSTRUCTED,
            "EVENT_TIME_USABLE",
            False,
            True,
            "INJURY_ANNOUNCEMENT_PROVEN_BEFORE_TARGET_BUT_INTERVAL_RECONSTRUCTED",
            "HISTORICAL_INTERVAL_RECONSTRUCTED",
        )

    if target_record and family in _LINEUP_FAMILIES:
        return result(
            TARGET_POST_LINEUP_RECONSTRUCTED,
            "POST_LINEUP_RECONSTRUCTED",
            False,
            True,
            "TARGET_LINEUP_IS_NEVER_STRICT_PREMATCH",
            "TARGET_LINEUP_POST_RELEASE",
        )

    if target_record and (
        family in _POST_MATCH_FAMILIES or family not in _LINEUP_FAMILIES
    ):
        return result(
            POST_MATCH_DESCRIPTIVE,
            "POST_MATCH_ONLY",
            False,
            False,
            "TARGET_FIXTURE_STATISTICS_ARE_POST_MATCH_ONLY",
            "DESCRIPTIVE_ONLY_NOT_PREDICTIVE",
        )

    if source_kickoff is None:
        return result(
            POST_MATCH_DESCRIPTIVE,
            "ANNOUNCEMENT_TIME_UNKNOWN",
            False,
            False,
            "SOURCE_FIXTURE_KICKOFF_UNPROVEN",
            "DESCRIPTIVE_ONLY_NOT_PREDICTIVE",
        )
    if source_kickoff >= target_kickoff:
        return result(
            POST_MATCH_DESCRIPTIVE,
            "FIXTURE_SPECIFIC_POST_HOC",
            False,
            False,
            "SOURCE_FIXTURE_NOT_STRICTLY_BEFORE_TARGET",
            "DESCRIPTIVE_ONLY_NOT_PREDICTIVE",
        )
    if family in _LINEUP_FAMILIES:
        return result(
            LINEUP_HISTORY_PREMATCH_STRICT,
            "PRIOR_MATCH_USABLE",
            True,
            False,
            "SOURCE_FIXTURE_STRICTLY_BEFORE_TARGET",
            "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        )
    if family in _PLAYER_FAMILIES:
        return result(
            PLAYER_PREMATCH_STRICT,
            "PRIOR_MATCH_USABLE",
            True,
            False,
            "SOURCE_FIXTURE_STRICTLY_BEFORE_TARGET",
            "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
        )
    return result(
        TEAM_PREMATCH_STRICT,
        "PRIOR_MATCH_USABLE",
        True,
        False,
        "SOURCE_FIXTURE_STRICTLY_BEFORE_TARGET",
        "SOURCE_FIXTURE_KICKOFF_LT_TARGET_FIXTURE_KICKOFF",
    )


def separate_temporal_datasets(
    records: Sequence[Mapping[str, object]],
    *,
    target_fixtures: Mapping[str, datetime | str] | None = None,
    target_fixture_id: str | None = None,
    target_fixture_kickoff: datetime | str | None = None,
    copy_records: bool = True,
) -> dict[str, list[dict[str, object]]]:
    """Return six physically separate logical datasets with explicit lineage.

    Large replay projections can contain millions of rows.  Reducer-owned rows
    are already private mutable dictionaries, so callers may opt into in-place
    classification to avoid retaining a second full copy of the projection.
    The default remains copy-on-write for the public API and small callers.
    """

    if (target_fixture_id is None) != (target_fixture_kickoff is None):
        raise ValueError("SINGLE_TARGET_ID_AND_KICKOFF_REQUIRED_TOGETHER")
    datasets: dict[str, list[dict[str, object]]] = {
        name: [] for name in DATASET_NAMES
    }
    targets = target_fixtures or {}
    for record in records:
        row_target_fixture_id = str(
            _first(
                record,
                (
                    "target_fixture_id",
                    "prediction_fixture_id",
                    "target_canonical_fixture_id",
                ),
            )
            or target_fixture_id
            or ""
        )
        if not row_target_fixture_id:
            raise ValueError("TARGET_FIXTURE_ID_REQUIRED")
        target_kickoff: object = _first(
            record,
            ("target_fixture_kickoff", "prediction_fixture_kickoff", "cutoff_at"),
        )
        if target_kickoff is None:
            target_kickoff = targets.get(
                row_target_fixture_id,
                target_fixture_kickoff,
            )
        if target_kickoff is None:
            raise ValueError(
                f"TARGET_FIXTURE_KICKOFF_REQUIRED:{row_target_fixture_id}"
            )
        if not isinstance(target_kickoff, (datetime, str)):
            raise ValueError(
                f"TARGET_FIXTURE_KICKOFF_INVALID:{row_target_fixture_id}"
            )
        classification = classify_temporal_record(
            record,
            target_fixture_id=row_target_fixture_id,
            target_fixture_kickoff=target_kickoff,
        )
        if copy_records:
            classified = dict(record)
        elif isinstance(record, dict):
            classified = record
        else:
            raise TypeError("QUALITY_IN_PLACE_RECORD_MUST_BE_MUTABLE")
        classified.update(
            {
                "target_fixture_id": row_target_fixture_id,
                "temporal_class": classification.temporal_class,
                "strict_prematch_usable": classification.strict_prematch_usable,
                "reconstructed": classification.reconstructed,
                "temporal_reason": classification.reason,
                "cutoff_policy": classification.cutoff_policy,
                "dataset_name": classification.dataset,
            }
        )
        datasets[classification.dataset].append(classified)
    return datasets


@dataclass(frozen=True, slots=True)
class CoverageSnapshotV2:
    rows: int
    expected_rows: int
    covered_rows: int
    coverage_rate: float | None
    null_rate: dict[str, float | None]
    identity_rate: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QualityMismatch:
    key: tuple[str, ...]
    field: str
    before: object
    after: object
    kind: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QualityComparisonV2:
    schema_version: str
    before: CoverageSnapshotV2
    after: CoverageSnapshotV2
    mismatches: tuple[QualityMismatch, ...]
    null_to_zero_conversions: int
    before_hash: str
    after_hash: str
    exact_replay: bool

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "mismatches": [mismatch.as_dict() for mismatch in self.mismatches],
        }


def null_rates(
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str] | None = None,
) -> dict[str, float | None]:
    selected = tuple(
        fields
        or sorted({str(field) for row in rows for field in row})
    )
    if not rows:
        return {field: None for field in selected}
    return {
        field: sum(row.get(field) is None for row in rows) / len(rows)
        for field in selected
    }


def identity_rate(
    rows: Sequence[Mapping[str, object]],
    *,
    identity_fields: Sequence[str] = ("fixture_id",),
) -> float | None:
    if not rows:
        return None
    valid = 0
    for row in rows:
        explicit = row.get("identity_ok")
        if explicit is False:
            continue
        identity_status = str(row.get("identity_status", "")).upper()
        if identity_status in {
            "PROVIDER_ID_VERIFIED",
            "CANONICAL",
            "VERIFIED",
            "MATCHED",
        }:
            valid += 1
            continue
        if explicit is True or all(
            (
                row.get(field) is not None
                and str(row.get(field)).strip()
            )
            or (
                field == "fixture_id"
                and row.get("canonical_fixture_id") is not None
                and str(row.get("canonical_fixture_id")).strip()
            )
            for field in identity_fields
        ):
            valid += 1
    return valid / len(rows)


def coverage_snapshot_v2(
    rows: Sequence[Mapping[str, object]],
    *,
    required_fields: Sequence[str],
    identity_fields: Sequence[str] = ("fixture_id",),
    expected_rows: int | None = None,
) -> CoverageSnapshotV2:
    expected = len(rows) if expected_rows is None else expected_rows
    if expected < 0:
        raise ValueError("QUALITY_EXPECTED_ROWS_MUST_BE_NON_NEGATIVE")
    covered = sum(
        all(field in row and row.get(field) is not None for field in required_fields)
        for row in rows
    )
    return CoverageSnapshotV2(
        rows=len(rows),
        expected_rows=expected,
        covered_rows=covered,
        coverage_rate=(min(covered / expected, 1.0) if expected else None),
        null_rate=null_rates(rows, required_fields),
        identity_rate=identity_rate(rows, identity_fields=identity_fields),
    )


def _row_index(
    rows: Sequence[Mapping[str, object]],
    *,
    key_fields: Sequence[str],
    label: str,
) -> dict[tuple[str, ...], Mapping[str, object]]:
    output: dict[tuple[str, ...], Mapping[str, object]] = {}
    for row in rows:
        key = tuple(
            "" if row.get(field) is None else str(row.get(field))
            for field in key_fields
        )
        if any(not value for value in key):
            raise ValueError(f"QUALITY_{label}_KEY_MISSING:{'|'.join(key_fields)}")
        if key in output:
            raise ValueError(f"QUALITY_{label}_DUPLICATE_KEY:{'|'.join(key)}")
        output[key] = row
    return output


def compare_quality_v2(
    before_rows: Sequence[Mapping[str, object]],
    after_rows: Sequence[Mapping[str, object]],
    *,
    key_fields: Sequence[str],
    required_fields: Sequence[str],
    identity_fields: Sequence[str] = ("fixture_id",),
    expected_rows: int | None = None,
    fail_on_null_to_zero: bool = True,
) -> QualityComparisonV2:
    """Compare source and replay rows, preserving missingness as evidence."""

    before = _row_index(before_rows, key_fields=key_fields, label="BEFORE")
    after = _row_index(after_rows, key_fields=key_fields, label="AFTER")
    mismatches: list[QualityMismatch] = []
    all_fields = tuple(
        sorted(
            set(required_fields)
            | {str(field) for row in before_rows for field in row}
            | {str(field) for row in after_rows for field in row}
        )
    )
    for key in sorted(set(before) | set(after)):
        left = before.get(key)
        right = after.get(key)
        if left is None:
            mismatches.append(QualityMismatch(key, "*", None, right, "ROW_ADDED"))
            continue
        if right is None:
            mismatches.append(QualityMismatch(key, "*", left, None, "ROW_MISSING"))
            continue
        for field in all_fields:
            left_value = left.get(field)
            right_value = right.get(field)
            if left_value == right_value:
                continue
            kind = (
                "NULL_TO_ZERO"
                if left_value is None
                and isinstance(right_value, (int, float))
                and not isinstance(right_value, bool)
                and right_value == 0
                else "VALUE_MISMATCH"
            )
            mismatches.append(
                QualityMismatch(key, field, left_value, right_value, kind)
            )
    null_to_zero = sum(item.kind == "NULL_TO_ZERO" for item in mismatches)
    if fail_on_null_to_zero and null_to_zero:
        raise ValueError(f"QUALITY_NULL_TO_ZERO_FORBIDDEN:{null_to_zero}")
    expected = expected_rows if expected_rows is not None else len(before_rows)
    return QualityComparisonV2(
        schema_version="historical-deep-quality-v2",
        before=coverage_snapshot_v2(
            before_rows,
            required_fields=required_fields,
            identity_fields=identity_fields,
            expected_rows=expected,
        ),
        after=coverage_snapshot_v2(
            after_rows,
            required_fields=required_fields,
            identity_fields=identity_fields,
            expected_rows=expected,
        ),
        mismatches=tuple(mismatches),
        null_to_zero_conversions=null_to_zero,
        before_hash=canonical_sha256([dict(before[key]) for key in sorted(before)]),
        after_hash=canonical_sha256([dict(after[key]) for key in sorted(after)]),
        exact_replay=not mismatches,
    )


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    schema_version: str
    dataset_name: str
    row_count: int
    fixture_count: int
    dataset_hash: str
    provenance: dict[str, object]
    provenance_hash: str
    cutoff_policy: str
    allowed_usages: tuple[str, ...]
    forbidden_usages: tuple[str, ...]
    features: tuple[str, ...]
    null_counts: dict[str, int]
    null_count: int
    null_rate: float | None
    temporal_classes: tuple[str, ...]
    temporal_class_counts: dict[str, int]
    normalized_family_counts: dict[str, int]
    manifest_hash: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_dataset_manifests(
    datasets: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    provenance: Mapping[str, object],
) -> dict[str, DatasetManifest]:
    if not provenance:
        raise ValueError("DATASET_PROVENANCE_REQUIRED")
    unknown = set(datasets) - set(DATASET_NAMES)
    if unknown:
        raise ValueError(f"DATASET_NAME_UNKNOWN:{','.join(sorted(unknown))}")
    output: dict[str, DatasetManifest] = {}
    provenance_value = dict(provenance)
    provenance_hash = canonical_sha256(provenance_value)
    for name in DATASET_NAMES:
        # Sorting a list of references is sufficient: manifest construction is
        # read-only and must not duplicate every dictionary in a large corpus.
        rows = sorted(datasets.get(name, ()), key=canonical_sha256)
        dataset_hash = canonical_sha256(rows)
        fixture_count = len(
            {
                str(
                    _first(
                        row,
                        (
                            "target_fixture_id",
                            "fixture_id",
                            "source_fixture_id",
                            "canonical_fixture_id",
                        ),
                    )
                )
                for row in rows
                if _first(
                    row,
                    (
                        "target_fixture_id",
                        "fixture_id",
                        "source_fixture_id",
                        "canonical_fixture_id",
                    ),
                )
                is not None
            }
        )
        observed_cutoffs = {
            str(row["cutoff_policy"])
            for row in rows
            if row.get("cutoff_policy")
        }
        if len(observed_cutoffs) > 1:
            raise ValueError(f"DATASET_CUTOFF_POLICY_MIXED:{name}")
        cutoff_policy = next(
            iter(observed_cutoffs),
            _DEFAULT_CUTOFF_POLICY[name],
        )
        if cutoff_policy != _DEFAULT_CUTOFF_POLICY[name]:
            raise ValueError(f"DATASET_CUTOFF_POLICY_INVALID:{name}")
        temporal_classes = tuple(
            sorted(
                {
                    str(row["temporal_class"])
                    for row in rows
                    if row.get("temporal_class")
                }
            )
        )
        features = tuple(
            sorted({str(field) for row in rows for field in row})
        )
        null_counts = {
            field: sum(row.get(field) is None for row in rows)
            for field in features
        }
        null_count = sum(null_counts.values())
        observed_cells = len(rows) * len(features)
        null_rate = (
            null_count / observed_cells if observed_cells > 0 else None
        )
        temporal_class_counts: dict[str, int] = {}
        normalized_family_counts: dict[str, int] = {}
        for row in rows:
            temporal_class = str(row.get("temporal_class", "UNKNOWN"))
            temporal_class_counts[temporal_class] = (
                temporal_class_counts.get(temporal_class, 0) + 1
            )
            normalized_family = str(
                row.get("normalized_family", row.get("family", "UNKNOWN"))
            )
            normalized_family_counts[normalized_family] = (
                normalized_family_counts.get(normalized_family, 0) + 1
            )
        body = {
            "schema_version": "historical-deep-dataset-manifest-v1",
            "dataset_name": name,
            "row_count": len(rows),
            "fixture_count": fixture_count,
            "dataset_hash": dataset_hash,
            "provenance": provenance_value,
            "provenance_hash": provenance_hash,
            "cutoff_policy": cutoff_policy,
            "allowed_usages": list(_DEFAULT_USAGES[name]),
            "forbidden_usages": list(_DEFAULT_FORBIDDEN_USAGES[name]),
            "features": list(features),
            "null_counts": null_counts,
            "null_count": null_count,
            "null_rate": null_rate,
            "temporal_classes": list(temporal_classes),
            "temporal_class_counts": dict(sorted(temporal_class_counts.items())),
            "normalized_family_counts": dict(
                sorted(normalized_family_counts.items())
            ),
        }
        output[name] = DatasetManifest(
            schema_version=str(body["schema_version"]),
            dataset_name=name,
            row_count=len(rows),
            fixture_count=fixture_count,
            dataset_hash=dataset_hash,
            provenance=provenance_value,
            provenance_hash=provenance_hash,
            cutoff_policy=cutoff_policy,
            allowed_usages=_DEFAULT_USAGES[name],
            forbidden_usages=_DEFAULT_FORBIDDEN_USAGES[name],
            features=features,
            null_counts=null_counts,
            null_count=null_count,
            null_rate=null_rate,
            temporal_classes=temporal_classes,
            temporal_class_counts=dict(sorted(temporal_class_counts.items())),
            normalized_family_counts=dict(
                sorted(normalized_family_counts.items())
            ),
            manifest_hash=canonical_sha256(body),
        )
    return output
