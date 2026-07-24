"""Construction reproductible des correspondances UUID sans altérer le legacy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid5

import pandas as pd

LEGACY_NAMESPACE = UUID("68fa9bb2-b818-4fc0-b17a-211cb11cbd4b")


class LegacyMappingStatus(StrEnum):
    EXACT = "EXACT"
    PROVIDER_CONFIRMED = "PROVIDER_CONFIRMED"
    RULE_MATCHED = "RULE_MATCHED"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class LegacyMigrationSummary:
    rows_examined: int
    mappings_total: int
    exact: int
    provider_confirmed: int
    rule_matched: int
    probable: int
    ambiguous: int
    unresolved: int
    rejected: int
    collisions: int

    @property
    def certain_coverage(self) -> float:
        certain = self.exact + self.provider_confirmed + self.rule_matched
        return certain / self.mappings_total if self.mappings_total else 0.0


def _internal_id(entity_type: str, canonical_key: str) -> str:
    return str(uuid5(LEGACY_NAMESPACE, f"{entity_type}:{canonical_key}"))


def _record(
    entity_type: str,
    provider_entity_id: str,
    canonical_key: str,
    observed_name: str,
    status: LegacyMappingStatus,
) -> dict[str, object]:
    return {
        "internal_entity_id": _internal_id(entity_type, canonical_key),
        "entity_type": entity_type,
        "provider_name": "football-data.co.uk-legacy",
        "provider_entity_id": provider_entity_id,
        "canonical_key": canonical_key,
        "observed_name": observed_name,
        "mapping_status": status.value,
        "mapping_confidence": {
            LegacyMappingStatus.EXACT: 1.0,
            LegacyMappingStatus.PROVIDER_CONFIRMED: 1.0,
            LegacyMappingStatus.RULE_MATCHED: 0.95,
            LegacyMappingStatus.PROBABLE: 0.65,
            LegacyMappingStatus.AMBIGUOUS: 0.25,
            LegacyMappingStatus.UNRESOLVED: 0.0,
            LegacyMappingStatus.REJECTED: 0.0,
        }[status],
        "model_eligible_identity": status
        in {
            LegacyMappingStatus.EXACT,
            LegacyMappingStatus.PROVIDER_CONFIRMED,
            LegacyMappingStatus.RULE_MATCHED,
        },
    }


def migrate_legacy_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, LegacyMigrationSummary]:
    records: list[dict[str, object]] = []
    for league in sorted(frame["league"].dropna().astype(str).unique()):
        records.append(
            _record("competition", league, league, league, LegacyMappingStatus.EXACT)
        )
    for league, season in sorted(
        frame[["league", "season"]].drop_duplicates().itertuples(index=False, name=None)
    ):
        key = f"{league}:{season}"
        records.append(
            _record("season", key, key, str(season), LegacyMappingStatus.RULE_MATCHED)
        )
    team_pairs = pd.concat(
        [
            frame[["league", "home"]].rename(columns={"home": "team"}),
            frame[["league", "away"]].rename(columns={"away": "team"}),
        ],
        ignore_index=True,
    ).drop_duplicates()
    for league, team in sorted(team_pairs.itertuples(index=False, name=None)):
        key = f"{league}:{team}"
        records.append(
            _record("team", key, key, str(team), LegacyMappingStatus.PROBABLE)
        )
    for row in frame[
        ["match_id", "league", "season", "date", "home", "away"]
    ].itertuples(index=False):
        canonical = (
            f"{row.league}:{row.season}:{pd.Timestamp(str(row.date)).isoformat()}:"
            f"{row.home}:{row.away}"
        )
        records.append(
            _record(
                "fixture",
                str(row.match_id),
                canonical,
                f"{row.home} – {row.away}",
                LegacyMappingStatus.RULE_MATCHED,
            )
        )
    if "referee" in frame:
        for league, referee in sorted(
            frame[["league", "referee"]]
            .dropna()
            .drop_duplicates()
            .itertuples(index=False, name=None)
        ):
            key = f"{league}:{referee}"
            records.append(
                _record(
                    "referee",
                    key,
                    key,
                    str(referee),
                    LegacyMappingStatus.PROBABLE,
                )
            )
    mappings = pd.DataFrame(records)
    duplicate_provider = mappings.duplicated(
        ["provider_name", "entity_type", "provider_entity_id"], keep=False
    )
    collisions = int(duplicate_provider.sum())
    counts = mappings["mapping_status"].value_counts()
    summary = LegacyMigrationSummary(
        rows_examined=len(frame),
        mappings_total=len(mappings),
        exact=int(counts.get(LegacyMappingStatus.EXACT.value, 0)),
        provider_confirmed=int(
            counts.get(LegacyMappingStatus.PROVIDER_CONFIRMED.value, 0)
        ),
        rule_matched=int(counts.get(LegacyMappingStatus.RULE_MATCHED.value, 0)),
        probable=int(counts.get(LegacyMappingStatus.PROBABLE.value, 0)),
        ambiguous=int(counts.get(LegacyMappingStatus.AMBIGUOUS.value, 0)),
        unresolved=int(counts.get(LegacyMappingStatus.UNRESOLVED.value, 0)),
        rejected=int(counts.get(LegacyMappingStatus.REJECTED.value, 0)),
        collisions=collisions,
    )
    return mappings, summary


def write_migration_artifacts(
    mappings: pd.DataFrame,
    summary: LegacyMigrationSummary,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    mappings.to_parquet(output_dir / "legacy-uuid-mappings.parquet", index=False)
    ambiguities = mappings[
        mappings["mapping_status"].isin(
            [
                LegacyMappingStatus.PROBABLE.value,
                LegacyMappingStatus.AMBIGUOUS.value,
                LegacyMappingStatus.UNRESOLVED.value,
            ]
        )
    ]
    ambiguities.to_csv(output_dir / "legacy-uuid-ambiguities.csv", index=False)
    summary_frame = pd.DataFrame([summary.__dict__ | {"coverage": summary.certain_coverage}])
    summary_frame.to_json(
        output_dir / "legacy-uuid-summary.json",
        orient="records",
        indent=2,
    )
