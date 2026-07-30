"""Frozen contracts for the cache-only Jalon 10 match evidence factory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow as pa  # type: ignore[import-untyped]

SCHEMA_VERSION: Final = "j10-hypothesis-evidence-v1"
HISTORICAL_FIXTURE_SCHEMA_VERSION: Final = "historical-fixture-evidence-v1"
MEMBERSHIP_SCHEMA_VERSION: Final = "hypothesis-fixture-membership-v1"
SUMMARY_SCHEMA_VERSION: Final = "hypothesis-historical-evidence-summary-v1"

AUTHORITATIVE_HISTORICAL_REVISION: Final = (
    "5c85cf20b932df44dca8665de00e52e3f1e02236"
)
BYTE_IDENTICAL_REPLICA_REVISIONS: Final = (
    "518cb4b708b214f550e38c519d1226a0d34f1e38",
    "4678a30a72bc1cbe138508c4f5881275d97e9b47",
)
HISTORICAL_PARQUET_TREE: Final = "986010a776cb7c0f4948098660febea9577f159e"
DATASET_HASH: Final = (
    "3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495"
)
REGISTRY_SHA256: Final = (
    "cb928f00340f64893e90cc40aaed9bd4ba22e4ef39d59e5f66994dd79331d731"
)
FULL_CAMPAIGN_SHA256: Final = (
    "3fe485238073e739cf423b1686ed9115f9b1a5a3db5cbd4e152c4dadde02c00c"
)
COMPACT_CAMPAIGN_SHA256: Final = (
    "f92df657bbe5bacefeb445841836f563d86b63500246f78e63643aeab52df0c7"
)
CAMPAIGN_RESULT_HASH: Final = (
    "edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b"
)
CAMPAIGN_CODE_REVISION: Final = "423fb7e77ba52286b660956161f02f8a2c1be7f8"
CAMPAIGN_ID: Final = "jalon10-cache-only-20260727"
CAMPAIGN_EXECUTED_AT: Final = "2026-07-27T11:00:02Z"

EXPECTED_PARTITIONS: Final = 30
EXPECTED_FIXTURES: Final = 10_732
EXPECTED_RULES: Final = 700
EXPECTED_RAW_MEMBERSHIPS: Final = 681_490
EXPECTED_STRICT_MEMBERSHIPS: Final = 681_466
EXPECTED_RAW_STRICT_DELTA: Final = 24

TOP_RULE_IDS: Final = {
    "293f3a6d5e635389abc272e8b6579b5e95df58836cd2e1355737df96c52f4867": (
        "J10-M001"
    ),
    "a82c917853baf22ec85eea189eb2efde72022b0271e1e0eadffb2f851d0623a2": (
        "J10-M002"
    ),
    "561b8a16908ab9bb8cb477c77af343779d20485d959b40ea7ed2a2e60535ec20": (
        "J10-M003"
    ),
}

EXPECTED_MARKET_COLUMNS: Final = (
    "competition",
    "season",
    "match_date",
    "home_source_name",
    "away_source_name",
    "home_goals",
    "away_goals",
    "odds_home",
    "odds_draw",
    "odds_away",
    "odds_over_25",
    "odds_under_25",
    "bookmaker_1x2",
    "bookmaker_totals",
    "price_type",
    "totals_price_type",
    "observed_time_status",
    "quality_status",
    "source",
    "raw_payload_hash",
    "mapping_status",
    "fixture_id",
    "kickoff_at",
    "home_team_id",
    "away_team_id",
    "market_margin_1x2",
    "market_margin_totals",
    "de_vig_home",
    "de_vig_draw",
    "de_vig_away",
    "de_vig_over_25",
    "de_vig_under_25",
    "quality",
    "_record_hash",
)

HISTORICAL_FIXTURE_EVIDENCE_SCHEMA: Final = pa.schema(
    [
        ("schema_version", pa.string(), False),
        ("dataset_hash", pa.string(), False),
        ("historical_data_revision", pa.string(), False),
        ("historical_parquet_tree", pa.string(), False),
        ("source_partition", pa.string(), False),
        ("source_partition_sha256", pa.string(), False),
        ("record_hash", pa.string(), False),
        ("source_dataset_hash", pa.string(), False),
        ("source_row_hash", pa.string(), False),
        ("canonical_match_id", pa.string(), False),
        ("provider_fixture_id", pa.string(), False),
        ("fixture_id", pa.string(), False),
        ("competition_key", pa.string(), False),
        ("competition_name", pa.string(), False),
        ("competition", pa.string(), False),
        ("season", pa.int16(), False),
        ("round", pa.string()),
        ("final_status", pa.string(), False),
        ("match_date", pa.string(), False),
        ("kickoff_at", pa.string(), False),
        ("home_team_id", pa.string(), False),
        ("away_team_id", pa.string(), False),
        ("home_team_name", pa.string(), False),
        ("away_team_name", pa.string(), False),
        ("home_source_name", pa.string(), False),
        ("away_source_name", pa.string(), False),
        ("home_goals", pa.int16(), False),
        ("away_goals", pa.int16(), False),
        ("odds_home", pa.float64()),
        ("odds_draw", pa.float64()),
        ("odds_away", pa.float64()),
        ("odds_over_25", pa.float64()),
        ("odds_under_25", pa.float64()),
        ("bookmaker_1x2", pa.string()),
        ("bookmaker_totals", pa.string()),
        ("price_type", pa.string()),
        ("totals_price_type", pa.string()),
        ("observed_time_status", pa.string(), False),
        ("quality_status", pa.string()),
        ("source", pa.string(), False),
        ("raw_payload_hash", pa.string()),
        ("mapping_status", pa.string()),
        ("market_margin_1x2", pa.float64()),
        ("market_margin_totals", pa.float64()),
        ("de_vig_home", pa.float64()),
        ("de_vig_draw", pa.float64()),
        ("de_vig_away", pa.float64()),
        ("de_vig_over_25", pa.float64()),
        ("de_vig_under_25", pa.float64()),
        ("quality", pa.string()),
    ]
)

HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA: Final = pa.schema(
    [
        ("schema_version", pa.string(), False),
        ("dataset_hash", pa.string(), False),
        ("campaign_result_hash", pa.string(), False),
        ("registry_sha256", pa.string(), False),
        ("historical_data_revision", pa.string(), False),
        ("hypothesis_id", pa.string(), False),
        ("hypothesis_version", pa.string(), False),
        ("rule_hash", pa.string(), False),
        ("membership_hash", pa.string(), False),
        ("canonical_match_id", pa.string(), False),
        ("market", pa.string(), False),
        ("selection", pa.string(), False),
        ("price_class", pa.string(), False),
        ("observed_time_status", pa.string(), False),
        ("observed_odds", pa.float64(), False),
        ("market_margin", pa.float64(), False),
        ("stake_units", pa.float64(), False),
        ("won", pa.bool_(), False),
        ("lost", pa.bool_(), False),
        ("void", pa.bool_(), False),
        ("gross_return_units", pa.float64(), False),
        ("profit_units", pa.float64(), False),
        ("cumulative_profit_units", pa.float64(), False),
        ("occurrence_index", pa.int32(), False),
        ("chronological_fold", pa.string(), False),
        ("statistical_group", pa.string(), False),
        ("eligibility_status", pa.string(), False),
        ("eligibility_reason", pa.string(), False),
    ]
)

HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA: Final = pa.schema(
    [
        ("schema_version", pa.string(), False),
        ("dataset_hash", pa.string(), False),
        ("campaign_result_hash", pa.string(), False),
        ("registry_sha256", pa.string(), False),
        ("historical_data_revision", pa.string(), False),
        ("hypothesis_id", pa.string(), False),
        ("rule_hash", pa.string(), False),
        ("summary_hash", pa.string(), False),
        ("membership_set_hash", pa.string(), False),
        ("market", pa.string(), False),
        ("selection", pa.string(), False),
        ("family", pa.string(), False),
        ("competition_scope", pa.string(), False),
        ("condition_count", pa.int8(), False),
        ("conditions_json", pa.string(), False),
        ("raw_occurrences", pa.int32(), False),
        ("occurrences", pa.int32(), False),
        ("settled_occurrences", pa.int32(), False),
        ("settled_bets", pa.int32(), False),
        ("wins", pa.int32(), False),
        ("losses", pa.int32(), False),
        ("voids", pa.int32(), False),
        ("hit_rate", pa.float64()),
        ("average_odds", pa.float64()),
        ("median_odds", pa.float64()),
        ("stake_per_bet", pa.float64(), False),
        ("total_staked_units", pa.float64(), False),
        ("gross_returns_units", pa.float64(), False),
        ("total_return_units", pa.float64(), False),
        ("profit_units", pa.float64(), False),
        ("roi", pa.float64()),
        ("maximum_drawdown_units", pa.float64(), False),
        ("max_drawdown_units", pa.float64(), False),
        ("longest_losing_streak", pa.int32(), False),
        ("max_losing_streak", pa.int32(), False),
        ("gross_profit_units", pa.float64(), False),
        ("gross_loss_units", pa.float64(), False),
        ("profit_factor", pa.float64()),
        ("confidence_interval", pa.string()),
        ("confidence_lower", pa.float64()),
        ("confidence_upper", pa.float64()),
        ("confidence_level", pa.float64()),
        ("bootstrap_groups", pa.int32(), False),
        ("eligible_folds", pa.int16(), False),
        ("positive_folds", pa.int16(), False),
        ("walk_forward_survived", pa.bool_(), False),
        ("distinct_seasons", pa.int16(), False),
        ("distinct_teams", pa.int32(), False),
        ("statistical_groups", pa.int32(), False),
        ("distinct_groups", pa.int32(), False),
        ("p_value", pa.float64(), False),
        ("q_value", pa.float64(), False),
        ("support_sufficient", pa.bool_(), False),
        ("hypothesis_status", pa.string(), False),
        ("evidence_scope", pa.string(), False),
        ("reconciled", pa.bool_(), False),
    ]
)


class EvidenceFactoryError(RuntimeError):
    """Fail-closed error raised before detailed evidence can be published."""


@dataclass(frozen=True, slots=True)
class EvidenceBuildConfig:
    repo_root: Path
    output_root: Path
    registry_path: Path
    full_campaign_path: Path
    compact_campaign_path: Path
    historical_root: Path | None = None
    report_root: Path | None = None
    historical_revision: str = AUTHORITATIVE_HISTORICAL_REVISION
    batch_size: int = 25
    resume: bool = True
    stop_after_batches: int | None = None


@dataclass(frozen=True, slots=True)
class EvidenceBuildResult:
    status: str
    replay_hash: str | None
    fixture_rows: int
    membership_rows: int
    summary_rows: int
    completed_batches: int
    output_root: Path


def hypothesis_id(rule_hash: str) -> str:
    """Return the stable J10 public identifier used by Hypothesis Intelligence."""

    return TOP_RULE_IDS.get(rule_hash, f"J10-{rule_hash[:16].upper()}")


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_contract() -> dict[str, object]:
    def fields(schema: pa.Schema) -> list[dict[str, object]]:
        return [
            {
                "name": field.name,
                "nullable": field.nullable,
                "type": str(field.type),
            }
            for field in schema
        ]

    return {
        "schema_version": SCHEMA_VERSION,
        "tables": {
            "historical_fixture_evidence": {
                "grain": "one frozen historical market source record per fixture",
                "primary_key": ["source_dataset_hash", "canonical_match_id"],
                "fields": fields(HISTORICAL_FIXTURE_EVIDENCE_SCHEMA),
            },
            "hypothesis_fixture_membership": {
                "grain": "one strict eligible settled fixture per J10 rule",
                "primary_key": [
                    "dataset_hash",
                    "rule_hash",
                    "canonical_match_id",
                ],
                "foreign_key": {
                    "canonical_match_id": (
                        "historical_fixture_evidence.canonical_match_id"
                    )
                },
                "membership_hash_contract": (
                    "SHA256_CANONICAL_JSON_OF_STORED_FIELDS_PLUS_"
                    "SOURCE_ROW_HASH_AND_MEMBERSHIP_SET_HASH"
                ),
                "fields": fields(HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA),
            },
            "hypothesis_historical_evidence_summary": {
                "grain": "one aggregate historical evidence record per J10 rule",
                "primary_key": ["dataset_hash", "rule_hash"],
                "fields": fields(
                    HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA
                ),
            },
        },
    }
