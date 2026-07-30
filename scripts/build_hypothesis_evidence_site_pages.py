"""Build bounded, static historical-evidence pages from normalized Parquet.

This adapter deliberately does not reconstruct evidence and does not contact a
provider, object storage, or a database.  It validates the three normalized
J10 evidence tables, selects the bounded union of hypotheses exposed by every
top-10 ranking scope, and publishes a temporary preview directory atomically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from robin.historical.storage import canonical_record_hash
from robin.hypothesis_evidence.contracts import EXPECTED_MARKET_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "hypothesis-evidence"
DEFAULT_TOP_TEN_REPORT = ROOT / "reports" / "hypothesis-evidence" / "top-10.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "hypothesis-evidence-site-pages"

PAGE_SIZES: Final = (25, 50)
ANALYSIS_MAX_BYTES: Final = 768 * 1024
MATCH_DETAIL_MAX_BYTES: Final = 64 * 1024
MEMBERSHIP_PAGE_MAX_BYTES: Final = 160 * 1024
QUERY_INDEX_MAX_BYTES: Final = 2 * 1024 * 1024
QUERY_INDEX_MAX_ITEMS: Final = 2_000
SUMMARY_MAX_BYTES: Final = 32 * 1024
MAX_PUBLISHED_HYPOTHESES: Final = 32
MAX_CONDITIONS: Final = 16
MAX_CONDITION_BYTES: Final = 16 * 1024
MAX_CONDITION_TEXT: Final = 256
ELIGIBILITY_REASONS: Final = {
    "ALL_CONDITIONS_MATCH;OBSERVED_ODDS_ELIGIBLE;OUTCOME_SETTLED",
}
CONDITION_KEYS: Final = {
    "available_at",
    "feature",
    "operator",
    "source",
    "value",
}
CONDITION_OPERATORS: Final = {"BETWEEN", "EQ", "LE"}
CONDITION_AVAILABILITY: Final = {
    "FIXTURE_PUBLICATION",
    "HISTORICAL_PRICE_CATEGORY",
}
CONDITION_SOURCES: Final = {"API_FOOTBALL_FIXTURE", "FOOTBALL_DATA"}
SOURCE_INTEGER_FIELDS: Final = {
    "away_team_id",
    "fixture_id",
    "home_team_id",
}
RANKING_BUCKETS: Final = (
    "by_roi",
    "by_profit",
    "by_support",
    "by_hit_rate",
    "by_lowest_drawdown",
)
RANKING_CONTRACTS: Final = {
    "by_roi": ("roi", True),
    "by_profit": ("profit_units", True),
    "by_support": ("occurrences", True),
    "by_hit_rate": ("hit_rate", True),
    "by_lowest_drawdown": ("maximum_drawdown_units", False),
}
PARQUET_NAMES: Final = (
    "historical_fixture_evidence.parquet",
    "hypothesis_fixture_membership.parquet",
    "hypothesis_historical_evidence_summary.parquet",
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_HYPOTHESIS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_CONDITION_FEATURE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")

FIXTURE_FIELDS: Final = {
    "dataset_hash",
    "source_dataset_hash",
    "record_hash",
    "source_row_hash",
    "canonical_match_id",
    "fixture_id",
    "competition_key",
    "competition_name",
    "competition",
    "season",
    "round",
    "final_status",
    "match_date",
    "kickoff_at",
    "home_team_id",
    "away_team_id",
    "home_team_name",
    "away_team_name",
    "home_goals",
    "away_goals",
    "observed_time_status",
    "source",
} | (set(EXPECTED_MARKET_COLUMNS) - {"_record_hash"})
MEMBERSHIP_FIELDS: Final = {
    "schema_version",
    "dataset_hash",
    "campaign_result_hash",
    "registry_sha256",
    "historical_data_revision",
    "hypothesis_id",
    "hypothesis_version",
    "rule_hash",
    "membership_hash",
    "canonical_match_id",
    "market",
    "selection",
    "price_class",
    "observed_time_status",
    "observed_odds",
    "market_margin",
    "stake_units",
    "won",
    "lost",
    "void",
    "gross_return_units",
    "profit_units",
    "cumulative_profit_units",
    "occurrence_index",
    "chronological_fold",
    "statistical_group",
    "eligibility_status",
    "eligibility_reason",
}
SUMMARY_FIELDS: Final = {
    "dataset_hash",
    "campaign_result_hash",
    "registry_sha256",
    "historical_data_revision",
    "hypothesis_id",
    "rule_hash",
    "summary_hash",
    "membership_set_hash",
    "market",
    "selection",
    "family",
    "competition_scope",
    "conditions_json",
    "occurrences",
    "settled_occurrences",
    "wins",
    "losses",
    "voids",
    "hit_rate",
    "average_odds",
    "median_odds",
    "total_staked_units",
    "gross_returns_units",
    "profit_units",
    "roi",
    "maximum_drawdown_units",
    "longest_losing_streak",
    "eligible_folds",
    "positive_folds",
    "walk_forward_survived",
    "p_value",
    "q_value",
    "support_sufficient",
    "hypothesis_status",
    "evidence_scope",
    "reconciled",
}
SUMMARY_PUBLIC_FIELDS: Final = (
    "family",
    "competition_scope",
    "market",
    "selection",
    "occurrences",
    "settled_occurrences",
    "wins",
    "losses",
    "voids",
    "hit_rate",
    "average_odds",
    "median_odds",
    "total_staked_units",
    "gross_returns_units",
    "profit_units",
    "roi",
    "maximum_drawdown_units",
    "longest_losing_streak",
    "eligible_folds",
    "positive_folds",
    "walk_forward_survived",
    "p_value",
    "q_value",
    "support_sufficient",
    "hypothesis_status",
    "evidence_scope",
)


class SitePageBuildError(RuntimeError):
    """Raised before a partial or inconsistent preview can be published."""


@dataclass(frozen=True, slots=True)
class SitePageBuildResult:
    output_root: Path
    hypothesis_count: int
    unique_match_count: int
    selected_membership_count: int
    content_tree_sha256: str


@dataclass(slots=True)
class _RuleAccumulator:
    canonical_match_ids: set[str]
    wins: int = 0
    losses: int = 0
    voids: int = 0
    stake_units: float = 0.0
    gross_return_units: float = 0.0
    profit_units: float = 0.0


@dataclass(slots=True)
class _AnalysisAggregate:
    reference: Mapping[str, object] | None = None
    losses: int = 0
    occurrences: int = 0
    profit_units: float = 0.0
    stake_units: float = 0.0
    voids: int = 0
    wins: int = 0

    def add(self, membership: Mapping[str, object]) -> None:
        if self.reference is None:
            self.reference = membership
        self.occurrences += 1
        self.wins += int(membership["won"] is True)
        self.losses += int(membership["lost"] is True)
        self.voids += int(membership["void"] is True)
        self.stake_units += _require_float(
            membership["stake_units"],
            "analysis.stake_units",
        )
        self.profit_units += _require_float(
            membership["profit_units"],
            "analysis.profit_units",
        )


@dataclass(slots=True)
class _TeamAggregate:
    reference: Mapping[str, object]
    team_id: str
    team_name: str
    away_occurrences: int = 0
    home_occurrences: int = 0
    losses: int = 0
    profit_units: float = 0.0
    voids: int = 0
    wins: int = 0

    @property
    def occurrences(self) -> int:
        return self.home_occurrences + self.away_occurrences

    def add_result(self, membership: Mapping[str, object]) -> None:
        self.wins += int(membership["won"] is True)
        self.losses += int(membership["lost"] is True)
        self.voids += int(membership["void"] is True)
        self.profit_units += _require_float(
            membership["profit_units"],
            "analysis.team.profit_units",
        )


def _canonical_json(value: object, *, pretty: bool = False) -> str:
    try:
        if pretty:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
                indent=2,
            )
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise SitePageBuildError("NON_CANONICAL_JSON_VALUE") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SitePageBuildError(f"INPUT_UNREADABLE:{path.name}") from exc
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SitePageBuildError(f"JSON_INPUT_INVALID:{path.name}") from exc
    if not isinstance(value, dict):
        raise SitePageBuildError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SitePageBuildError(f"STRING_REQUIRED:{label}")
    return value


def _require_hash(value: object, label: str) -> str:
    text = _require_string(value, label)
    if HEX_64.fullmatch(text) is None:
        raise SitePageBuildError(f"SHA256_INVALID:{label}")
    return text


def _require_revision(value: object, label: str) -> str:
    text = _require_string(value, label)
    if HEX_40.fullmatch(text) is None:
        raise SitePageBuildError(f"REVISION_INVALID:{label}")
    return text


def _require_hypothesis_id(value: object, label: str) -> str:
    text = _require_string(value, label)
    if SAFE_HYPOTHESIS_ID.fullmatch(text) is None:
        raise SitePageBuildError(f"HYPOTHESIS_ID_UNSAFE:{label}")
    return text


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SitePageBuildError(f"INTEGER_INVALID:{label}")
    return value


def _require_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SitePageBuildError(f"NUMBER_INVALID:{label}")
    output = float(value)
    if not math.isfinite(output):
        raise SitePageBuildError(f"NUMBER_NON_FINITE:{label}")
    return output


def _require_bounded_float(
    value: object,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    output = _require_float(value, label)
    if minimum is not None and output < minimum:
        raise SitePageBuildError(f"NUMBER_BELOW_MINIMUM:{label}")
    if maximum is not None and output > maximum:
        raise SitePageBuildError(f"NUMBER_ABOVE_MAXIMUM:{label}")
    return output


def _require_iso_date(value: object, label: str) -> str:
    text = _require_string(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise SitePageBuildError(f"DATE_INVALID:{label}") from exc
    if parsed.isoformat() != text:
        raise SitePageBuildError(f"DATE_NON_CANONICAL:{label}")
    return text


def _require_iso_datetime(value: object, label: str) -> str:
    text = _require_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SitePageBuildError(f"DATETIME_INVALID:{label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SitePageBuildError(f"DATETIME_TIMEZONE_REQUIRED:{label}")
    return text


def _source_record_from_fixture(
    row: Mapping[str, object],
    label: str,
) -> dict[str, object]:
    source: dict[str, object] = {}
    for field in EXPECTED_MARKET_COLUMNS:
        if field == "_record_hash":
            continue
        value = row.get(field)
        if field in SOURCE_INTEGER_FIELDS:
            text = _require_string(value, f"{label}.{field}")
            if not text.isascii() or not text.isdecimal():
                raise SitePageBuildError(
                    f"FIXTURE_SOURCE_INTEGER_INVALID:{label}.{field}"
                )
            value = int(text)
        source[field] = value
    return source


def _assert_close(actual: float, expected: object, label: str) -> None:
    expected_number = _require_float(expected, label)
    if not math.isclose(
        actual,
        expected_number,
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise SitePageBuildError(
            f"AGGREGATE_MISMATCH:{label}:{actual}:{expected_number}"
        )


def _require_columns(path: Path, required: set[str]) -> pq.ParquetFile:
    if not path.is_file():
        raise SitePageBuildError(f"PARQUET_INPUT_MISSING:{path.name}")
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, ValueError) as exc:
        raise SitePageBuildError(f"PARQUET_INPUT_INVALID:{path.name}") from exc
    missing = sorted(required - set(parquet.schema_arrow.names))
    if missing:
        raise SitePageBuildError(
            f"PARQUET_COLUMNS_MISSING:{path.name}:{','.join(missing)}"
        )
    return parquet


def _validate_optional_artifact_manifest(
    artifact_root: Path,
    inputs: Mapping[str, tuple[Path, int, str]],
) -> None:
    path = artifact_root / "artifact-manifest.json"
    if not path.exists():
        return
    manifest = _load_json_object(path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise SitePageBuildError("ARTIFACT_MANIFEST_ARTIFACTS_INVALID")
    by_name: dict[str, Mapping[str, object]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise SitePageBuildError("ARTIFACT_MANIFEST_ENTRY_INVALID")
        name = _require_string(item.get("name"), "artifact_manifest.name")
        if name in by_name:
            raise SitePageBuildError("ARTIFACT_MANIFEST_NAME_DUPLICATE")
        by_name[name] = item
    for name, (_, rows, digest) in inputs.items():
        entry = by_name.get(name)
        if entry is None:
            raise SitePageBuildError(f"ARTIFACT_MANIFEST_ENTRY_MISSING:{name}")
        if entry.get("rows") != rows:
            raise SitePageBuildError(f"ARTIFACT_MANIFEST_ROWS_MISMATCH:{name}")
        if entry.get("sha256") != digest:
            raise SitePageBuildError(f"ARTIFACT_MANIFEST_HASH_MISMATCH:{name}")


def _load_fixtures(
    parquet: pq.ParquetFile,
) -> tuple[dict[str, dict[str, object]], str]:
    rows = parquet.read().to_pylist()
    fixtures: dict[str, dict[str, object]] = {}
    primary_keys: set[tuple[str, str]] = set()
    dataset_hash: str | None = None
    for index, raw in enumerate(rows):
        row = dict(raw)
        label = f"fixture[{index}]"
        current_dataset = _require_hash(row.get("dataset_hash"), f"{label}.dataset_hash")
        source_dataset = _require_hash(
            row.get("source_dataset_hash"),
            f"{label}.source_dataset_hash",
        )
        if current_dataset != source_dataset:
            raise SitePageBuildError(f"FIXTURE_DATASET_HASH_MISMATCH:{index}")
        if dataset_hash is None:
            dataset_hash = current_dataset
        elif current_dataset != dataset_hash:
            raise SitePageBuildError("FIXTURE_MULTIPLE_DATASETS")
        record_hash = _require_hash(row.get("record_hash"), f"{label}.record_hash")
        source_row_hash = _require_hash(
            row.get("source_row_hash"),
            f"{label}.source_row_hash",
        )
        if record_hash != source_row_hash:
            raise SitePageBuildError(f"FIXTURE_ROW_HASH_MISMATCH:{index}")
        if canonical_record_hash(
            _source_record_from_fixture(row, label)
        ) != source_row_hash:
            raise SitePageBuildError(
                f"FIXTURE_SOURCE_ROW_HASH_MISMATCH:{index}"
            )
        canonical_match_id = _require_string(
            row.get("canonical_match_id"),
            f"{label}.canonical_match_id",
        )
        fixture_id = _require_string(
            row.get("fixture_id"),
            f"{label}.fixture_id",
        )
        if canonical_match_id != f"api-football:{fixture_id}":
            raise SitePageBuildError(
                f"FIXTURE_CANONICAL_ID_INVALID:{index}"
            )
        key = (source_dataset, canonical_match_id)
        if key in primary_keys:
            raise SitePageBuildError("FIXTURE_PRIMARY_KEY_DUPLICATE")
        primary_keys.add(key)
        if canonical_match_id in fixtures:
            raise SitePageBuildError("FIXTURE_CANONICAL_ID_AMBIGUOUS")
        for name in (
            "competition_key",
            "competition_name",
            "competition",
            "final_status",
            "home_team_id",
            "away_team_id",
            "home_team_name",
            "away_team_name",
            "observed_time_status",
            "source",
        ):
            _require_string(row.get(name), f"{label}.{name}")
        _require_iso_date(row.get("match_date"), f"{label}.match_date")
        _require_iso_datetime(row.get("kickoff_at"), f"{label}.kickoff_at")
        _require_int(row.get("season"), f"{label}.season", minimum=1900)
        _require_int(row.get("home_goals"), f"{label}.home_goals")
        _require_int(row.get("away_goals"), f"{label}.away_goals")
        if row.get("competition") != row.get("competition_name"):
            raise SitePageBuildError(
                f"FIXTURE_COMPETITION_NAME_MISMATCH:{index}"
            )
        if row.get("home_source_name") != row.get("home_team_name"):
            raise SitePageBuildError(f"FIXTURE_HOME_NAME_MISMATCH:{index}")
        if row.get("away_source_name") != row.get("away_team_name"):
            raise SitePageBuildError(f"FIXTURE_AWAY_NAME_MISMATCH:{index}")
        fixtures[canonical_match_id] = row
    if dataset_hash is None:
        raise SitePageBuildError("FIXTURE_TABLE_EMPTY")
    return fixtures, dataset_hash


def _summary_core(row: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key != "summary_hash"}


def _parse_conditions(row: Mapping[str, object], label: str) -> list[object]:
    conditions_json = _require_string(row.get("conditions_json"), label)
    if len(conditions_json.encode("utf-8")) > MAX_CONDITION_BYTES:
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_TOO_LARGE:{label}")
    try:
        conditions = json.loads(conditions_json)
    except json.JSONDecodeError as exc:
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_INVALID:{label}") from exc
    if not isinstance(conditions, list):
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_NOT_LIST:{label}")
    if not conditions or len(conditions) > MAX_CONDITIONS:
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_COUNT_INVALID:{label}")
    for index, condition in enumerate(conditions):
        item_label = f"{label}[{index}]"
        if (
            not isinstance(condition, dict)
            or set(condition) != CONDITION_KEYS
        ):
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_SHAPE_INVALID:{item_label}"
            )
        feature = _require_string(
            condition.get("feature"),
            f"{item_label}.feature",
        )
        if SAFE_CONDITION_FEATURE.fullmatch(feature) is None:
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_FEATURE_INVALID:{item_label}"
            )
        operator = _require_string(
            condition.get("operator"),
            f"{item_label}.operator",
        )
        if operator not in CONDITION_OPERATORS:
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_OPERATOR_INVALID:{item_label}"
            )
        for key, allowed in (
            ("available_at", CONDITION_AVAILABILITY),
            ("source", CONDITION_SOURCES),
        ):
            text = _require_string(
                condition.get(key),
                f"{item_label}.{key}",
            )
            if len(text) > MAX_CONDITION_TEXT or text not in allowed:
                raise SitePageBuildError(
                    f"SUMMARY_CONDITION_TEXT_INVALID:{item_label}.{key}"
                )
        value = condition.get("value")
        values = value if isinstance(value, list) else [value]
        if not values or len(values) > 8:
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_VALUE_INVALID:{item_label}"
            )
        for scalar in values:
            if isinstance(scalar, str):
                if not scalar or len(scalar) > MAX_CONDITION_TEXT:
                    raise SitePageBuildError(
                        f"SUMMARY_CONDITION_VALUE_INVALID:{item_label}"
                    )
            elif isinstance(scalar, bool) or scalar is None:
                continue
            elif isinstance(scalar, int | float):
                _require_float(
                    scalar,
                    f"{item_label}.value",
                )
            else:
                raise SitePageBuildError(
                    f"SUMMARY_CONDITION_VALUE_INVALID:{item_label}"
                )
        if operator == "BETWEEN" and (
            not isinstance(value, list) or len(value) != 2
        ):
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_BETWEEN_INVALID:{item_label}"
            )
        if operator == "LE" and (
            isinstance(value, bool) or not isinstance(value, int | float)
        ):
            raise SitePageBuildError(
                f"SUMMARY_CONDITION_LE_INVALID:{item_label}"
            )
    _canonical_json(conditions)
    return conditions


def _load_summaries(
    parquet: pq.ParquetFile,
    fixture_dataset_hash: str,
) -> tuple[dict[str, dict[str, object]], dict[str, list[object]]]:
    rows = parquet.read().to_pylist()
    summaries: dict[str, dict[str, object]] = {}
    conditions: dict[str, list[object]] = {}
    primary_keys: set[tuple[str, str]] = set()
    hypothesis_ids: set[str] = set()
    for index, raw in enumerate(rows):
        row = dict(raw)
        label = f"summary[{index}]"
        dataset_hash = _require_hash(row.get("dataset_hash"), f"{label}.dataset_hash")
        if dataset_hash != fixture_dataset_hash:
            raise SitePageBuildError(f"SUMMARY_DATASET_HASH_MISMATCH:{index}")
        _require_hash(
            row.get("campaign_result_hash"),
            f"{label}.campaign_result_hash",
        )
        _require_hash(row.get("registry_sha256"), f"{label}.registry_sha256")
        _require_revision(
            row.get("historical_data_revision"),
            f"{label}.historical_data_revision",
        )
        rule_hash = _require_hash(row.get("rule_hash"), f"{label}.rule_hash")
        hypothesis_id = _require_hypothesis_id(
            row.get("hypothesis_id"),
            f"{label}.hypothesis_id",
        )
        summary_hash = _require_hash(row.get("summary_hash"), f"{label}.summary_hash")
        _require_hash(
            row.get("membership_set_hash"),
            f"{label}.membership_set_hash",
        )
        if summary_hash != _canonical_sha256(_summary_core(row)):
            raise SitePageBuildError(f"SUMMARY_HASH_MISMATCH:{rule_hash}")
        key = (dataset_hash, rule_hash)
        if key in primary_keys:
            raise SitePageBuildError("SUMMARY_PRIMARY_KEY_DUPLICATE")
        primary_keys.add(key)
        if hypothesis_id in hypothesis_ids:
            raise SitePageBuildError("SUMMARY_HYPOTHESIS_ID_DUPLICATE")
        hypothesis_ids.add(hypothesis_id)
        if row.get("reconciled") is not True:
            raise SitePageBuildError(f"SUMMARY_NOT_RECONCILED:{rule_hash}")
        for name in (
            "market",
            "selection",
            "family",
            "competition_scope",
            "hypothesis_status",
            "evidence_scope",
        ):
            _require_string(row.get(name), f"{label}.{name}")
        for name in (
            "occurrences",
            "settled_occurrences",
            "wins",
            "losses",
            "voids",
            "eligible_folds",
            "positive_folds",
            "longest_losing_streak",
        ):
            _require_int(row.get(name), f"{label}.{name}")
        for name in ("total_staked_units", "gross_returns_units"):
            _require_bounded_float(
                row.get(name),
                f"{label}.{name}",
                minimum=0,
            )
        _require_float(row.get("profit_units"), f"{label}.profit_units")
        _require_bounded_float(
            row.get("maximum_drawdown_units"),
            f"{label}.maximum_drawdown_units",
            minimum=0,
        )
        for name in ("p_value", "q_value"):
            _require_bounded_float(
                row.get(name),
                f"{label}.{name}",
                minimum=0,
                maximum=1,
            )
        if row.get("hit_rate") is not None:
            _require_bounded_float(
                row.get("hit_rate"),
                f"{label}.hit_rate",
                minimum=0,
                maximum=1,
            )
        for name in ("average_odds", "median_odds"):
            if row.get(name) is not None:
                _require_bounded_float(
                    row.get(name),
                    f"{label}.{name}",
                    minimum=1.000000000001,
                )
        if row.get("roi") is not None:
            _require_float(row.get("roi"), f"{label}.roi")
        conditions[rule_hash] = _parse_conditions(row, f"{label}.conditions_json")
        summaries[rule_hash] = row
    if not summaries:
        raise SitePageBuildError("SUMMARY_TABLE_EMPTY")
    return summaries, conditions


def _top_ten_items(
    report: Mapping[str, object],
    summaries: Mapping[str, Mapping[str, object]],
    dataset_hash: str,
) -> tuple[list[dict[str, object]], str]:
    if report.get("schema_version") != "j10-historical-evidence-top-10-v1":
        raise SitePageBuildError("TOP_TEN_SCHEMA_INVALID")
    if report.get("dataset_hash") != dataset_hash:
        raise SitePageBuildError("TOP_TEN_DATASET_HASH_MISMATCH")
    selection_contract = report.get("selection_contract")
    if not isinstance(selection_contract, Mapping):
        raise SitePageBuildError("TOP_TEN_SELECTION_CONTRACT_INVALID")
    if (
        selection_contract.get("support_sufficient") is not True
        or selection_contract.get("campaign_status") != "DISCOVERED"
        or selection_contract.get("walk_forward_survived") is not True
        or selection_contract.get("deduplication")
        != "UNIQUE_MEMBERSHIP_SET_HASH"
        or selection_contract.get("public_status")
        != "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
        or selection_contract.get("validated_label_forbidden") is not True
    ):
        raise SitePageBuildError("TOP_TEN_SELECTION_CONTRACT_INVALID")
    ranking_contracts = selection_contract.get("rankings")
    if (
        not isinstance(ranking_contracts, Mapping)
        or set(ranking_contracts) != set(RANKING_CONTRACTS)
    ):
        raise SitePageBuildError("TOP_TEN_RANKING_CONTRACTS_INVALID")
    for name, (metric, descending) in RANKING_CONTRACTS.items():
        contract = ranking_contracts.get(name)
        if not isinstance(contract, Mapping) or dict(contract) != {
            "metric": metric,
            "direction": "DESC" if descending else "ASC",
            "tie_break": "RULE_HASH_ASC",
        }:
            raise SitePageBuildError(
                f"TOP_TEN_RANKING_CONTRACT_INVALID:{name}"
            )
    source_result_hash = _require_hash(
        report.get("source_result_hash"),
        "top_ten.source_result_hash",
    )
    global_scope = report.get("global")
    if not isinstance(global_scope, Mapping):
        raise SitePageBuildError("TOP_TEN_GLOBAL_INVALID")

    ranking_scopes: list[tuple[str, Mapping[str, object]]] = [
        ("global", global_scope)
    ]
    for scope_name in ("by_competition", "by_family"):
        scope_value = report.get(scope_name)
        if scope_value is None:
            continue
        if not isinstance(scope_value, Mapping):
            raise SitePageBuildError(f"TOP_TEN_{scope_name.upper()}_INVALID")
        for key in sorted(scope_value, key=str):
            nested_scope = scope_value[key]
            if not isinstance(nested_scope, Mapping):
                raise SitePageBuildError(
                    f"TOP_TEN_{scope_name.upper()}_SCOPE_INVALID:{key}"
                )
            ranking_scopes.append((f"{scope_name}.{key}", nested_scope))

    collected: list[tuple[str, int, Mapping[str, object]]] = []
    ranking_paths: list[str] = []
    global_roi_rank_by_rule: dict[str, int] = {}
    for scope_path, scope in ranking_scopes:
        is_legacy_global = scope_path == "global" and "items" in scope
        missing_buckets = set(RANKING_BUCKETS) - set(scope)
        if missing_buckets and not is_legacy_global:
            raise SitePageBuildError(
                f"TOP_TEN_RANKING_BUCKETS_MISSING:{scope_path}:"
                + ",".join(sorted(missing_buckets))
            )
        for bucket_name in RANKING_BUCKETS:
            bucket = scope.get(bucket_name)
            if bucket is None:
                continue
            if not isinstance(bucket, Mapping):
                raise SitePageBuildError(
                    f"TOP_TEN_RANKING_BUCKET_INVALID:{scope_path}.{bucket_name}"
                )
            items = bucket.get("items")
            if not isinstance(items, list):
                raise SitePageBuildError(
                    f"TOP_TEN_ITEMS_INVALID:{scope_path}.{bucket_name}"
                )
            metric, descending = RANKING_CONTRACTS[bucket_name]
            expected_ordering = [
                f"{metric.upper()}_{'DESC' if descending else 'ASC'}",
                "RULE_HASH_ASC",
            ]
            available_count = _require_int(
                bucket.get("available_count"),
                f"{scope_path}.{bucket_name}.available_count",
            )
            if (
                bucket.get("requested_limit") != 10
                or bucket.get("ordering") != expected_ordering
                or bucket.get("complete") is not (available_count >= 10)
            ):
                raise SitePageBuildError(
                    f"TOP_TEN_RANKING_CONTRACT_INVALID:"
                    f"{scope_path}.{bucket_name}"
                )
            _require_int(
                bucket.get("duplicate_membership_sets_removed"),
                f"{scope_path}.{bucket_name}."
                "duplicate_membership_sets_removed",
            )
            if len(items) > 10:
                raise SitePageBuildError(
                    f"TOP_TEN_ITEMS_OVER_LIMIT:{scope_path}.{bucket_name}"
                )
            if len(items) > available_count:
                raise SitePageBuildError(
                    f"TOP_TEN_AVAILABLE_COUNT_INVALID:"
                    f"{scope_path}.{bucket_name}"
                )
            ranking_path = f"{scope_path}.{bucket_name}.items"
            ranking_paths.append(ranking_path)
            seen_bucket_hypotheses: set[str] = set()
            seen_bucket_rules: set[str] = set()
            seen_bucket_memberships: set[str] = set()
            previous_order: tuple[float, str] | None = None
            for item_rank, value in enumerate(items, start=1):
                if not isinstance(value, Mapping):
                    raise SitePageBuildError(
                        f"TOP_TEN_ITEM_INVALID:{ranking_path}:{item_rank}"
                    )
                hypothesis_value = _require_hypothesis_id(
                    value.get("hypothesis_id"),
                    f"{ranking_path}[{item_rank}].hypothesis_id",
                )
                rule_value = _require_hash(
                    value.get("rule_hash"),
                    f"{ranking_path}[{item_rank}].rule_hash",
                )
                membership_value = _require_hash(
                    value.get("membership_set_hash"),
                    f"{ranking_path}[{item_rank}].membership_set_hash",
                )
                metric_value = _require_float(
                    value.get(metric),
                    f"{ranking_path}[{item_rank}].{metric}",
                )
                order_key = (
                    -metric_value if descending else metric_value,
                    rule_value,
                )
                if previous_order is not None and order_key < previous_order:
                    raise SitePageBuildError(
                        f"TOP_TEN_ORDER_INVALID:{ranking_path}"
                    )
                previous_order = order_key
                if (
                    hypothesis_value in seen_bucket_hypotheses
                    or rule_value in seen_bucket_rules
                    or membership_value in seen_bucket_memberships
                ):
                    raise SitePageBuildError(
                        f"TOP_TEN_ITEM_DUPLICATE:{ranking_path}"
                    )
                seen_bucket_hypotheses.add(hypothesis_value)
                seen_bucket_rules.add(rule_value)
                seen_bucket_memberships.add(membership_value)
                if scope_path.startswith("by_competition.") and value.get(
                    "competition"
                ) != scope_path.removeprefix("by_competition."):
                    raise SitePageBuildError(
                        f"TOP_TEN_COMPETITION_SCOPE_INVALID:{ranking_path}"
                    )
                if scope_path.startswith("by_family.") and value.get(
                    "family"
                ) != scope_path.removeprefix("by_family."):
                    raise SitePageBuildError(
                        f"TOP_TEN_FAMILY_SCOPE_INVALID:{ranking_path}"
                    )
                if ranking_path == "global.by_roi.items":
                    global_roi_rank_by_rule[rule_value] = item_rank
                collected.append((ranking_path, item_rank, value))

    if not ranking_paths:
        legacy_items = global_scope.get("items")
        if not isinstance(legacy_items, list):
            raise SitePageBuildError("TOP_TEN_ITEMS_INVALID")
        if len(legacy_items) > 10:
            raise SitePageBuildError("TOP_TEN_ITEMS_OVER_LIMIT")
        ranking_paths.append("global.items")
        seen_legacy_hypotheses: set[str] = set()
        seen_legacy_rules: set[str] = set()
        for item_rank, value in enumerate(legacy_items, start=1):
            if not isinstance(value, Mapping):
                raise SitePageBuildError(f"TOP_TEN_ITEM_INVALID:{item_rank}")
            hypothesis_value = _require_hypothesis_id(
                value.get("hypothesis_id"),
                f"global.items[{item_rank}].hypothesis_id",
            )
            rule_value = _require_hash(
                value.get("rule_hash"),
                f"global.items[{item_rank}].rule_hash",
            )
            if (
                hypothesis_value in seen_legacy_hypotheses
                or rule_value in seen_legacy_rules
            ):
                raise SitePageBuildError("TOP_TEN_ITEM_DUPLICATE:global.items")
            seen_legacy_hypotheses.add(hypothesis_value)
            seen_legacy_rules.add(rule_value)
            global_roi_rank_by_rule[rule_value] = item_rank
            collected.append(("global.items", item_rank, value))

    selected_by_hypothesis: dict[str, dict[str, object]] = {}
    selected_by_rule: dict[str, dict[str, object]] = {}
    for ranking_path, item_rank, value in collected:
        hypothesis_id = _require_hypothesis_id(
            value.get("hypothesis_id"),
            f"{ranking_path}[{item_rank}].hypothesis_id",
        )
        rule_hash = _require_hash(
            value.get("rule_hash"),
            f"{ranking_path}[{item_rank}].rule_hash",
        )
        membership_set_hash = _require_hash(
            value.get("membership_set_hash"),
            f"{ranking_path}[{item_rank}].membership_set_hash",
        )
        summary = summaries.get(rule_hash)
        if summary is None:
            raise SitePageBuildError(f"TOP_TEN_SUMMARY_MISSING:{rule_hash}")
        if summary.get("hypothesis_id") != hypothesis_id:
            raise SitePageBuildError(f"TOP_TEN_HYPOTHESIS_RELATION_INVALID:{rule_hash}")
        if summary.get("membership_set_hash") != membership_set_hash:
            raise SitePageBuildError(f"TOP_TEN_MEMBERSHIP_SET_INVALID:{rule_hash}")
        if summary.get("campaign_result_hash") != source_result_hash:
            raise SitePageBuildError(f"TOP_TEN_CAMPAIGN_HASH_INVALID:{rule_hash}")
        bucket_name = ranking_path.rsplit(".", maxsplit=2)[-2]
        if bucket_name in RANKING_CONTRACTS:
            metric = RANKING_CONTRACTS[bucket_name][0]
            _assert_close(
                _require_float(
                    value.get(metric),
                    f"{ranking_path}[{item_rank}].{metric}",
                ),
                summary.get(metric),
                f"{ranking_path}[{item_rank}].{metric}",
            )
        selected_item: dict[str, object] = {
            "hypothesis_id": hypothesis_id,
            "rule_hash": rule_hash,
            "membership_set_hash": membership_set_hash,
        }
        existing_hypothesis = selected_by_hypothesis.get(hypothesis_id)
        existing_rule = selected_by_rule.get(rule_hash)
        if (
            existing_hypothesis is not None
            and existing_hypothesis != selected_item
        ) or (existing_rule is not None and existing_rule != selected_item):
            raise SitePageBuildError("TOP_TEN_ITEM_AMBIGUOUS")
        selected_by_hypothesis[hypothesis_id] = selected_item
        selected_by_rule[rule_hash] = selected_item

    if len(selected_by_rule) > MAX_PUBLISHED_HYPOTHESES:
        raise SitePageBuildError("TOP_TEN_ITEMS_UNION_OVER_LIMIT")

    output: list[dict[str, object]] = []
    for rule_hash in sorted(
        selected_by_rule,
        key=lambda value: (
            global_roi_rank_by_rule.get(value) is None,
            global_roi_rank_by_rule.get(value, 0),
            value,
        ),
    ):
        output.append(
            {
                "rank": global_roi_rank_by_rule.get(rule_hash),
                **selected_by_rule[rule_hash],
            }
        )
    ranking_path = (
        ranking_paths[0]
        if len(ranking_paths) == 1
        else "top-10.all-ranking-scopes.items-union"
    )
    return output, ranking_path


def _membership_hash(
    row: Mapping[str, object],
    fixture: Mapping[str, object],
    summary: Mapping[str, object],
) -> str:
    membership_public = {
        key: value
        for key, value in row.items()
        if key != "membership_hash"
    }
    return _canonical_sha256(
        {
            **membership_public,
            "source_row_hash": fixture["source_row_hash"],
            "membership_set_hash": summary["membership_set_hash"],
        }
    )


def _validate_membership_relation(
    row: Mapping[str, object],
    summary: Mapping[str, object],
    fixture: Mapping[str, object],
    row_index: int,
) -> None:
    label = f"membership[{row_index}]"
    equality_relations = {
        "dataset_hash": summary["dataset_hash"],
        "campaign_result_hash": summary["campaign_result_hash"],
        "registry_sha256": summary["registry_sha256"],
        "historical_data_revision": summary["historical_data_revision"],
        "hypothesis_id": summary["hypothesis_id"],
        "market": summary["market"],
        "selection": summary["selection"],
        "observed_time_status": fixture["observed_time_status"],
    }
    for name, expected in equality_relations.items():
        if row.get(name) != expected:
            raise SitePageBuildError(f"MEMBERSHIP_RELATION_INVALID:{label}.{name}")


def _stream_memberships(
    parquet: pq.ParquetFile,
    fixtures: Mapping[str, Mapping[str, object]],
    summaries: Mapping[str, Mapping[str, object]],
    selected_rules: set[str],
) -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, _RuleAccumulator],
    dict[str, int],
]:
    selected: dict[str, list[dict[str, object]]] = {
        rule_hash: [] for rule_hash in selected_rules
    }
    accumulators: dict[str, _RuleAccumulator] = {
        rule_hash: _RuleAccumulator(set()) for rule_hash in summaries
    }
    primary_keys: set[tuple[str, str, str]] = set()
    historical_rule_counts_by_match: dict[str, int] = defaultdict(int)
    row_index = 0
    for batch in parquet.iter_batches(batch_size=65_536):
        for raw in batch.to_pylist():
            row_index += 1
            row = dict(raw)
            label = f"membership[{row_index}]"
            dataset_hash = _require_hash(
                row.get("dataset_hash"),
                f"{label}.dataset_hash",
            )
            _require_hash(
                row.get("campaign_result_hash"),
                f"{label}.campaign_result_hash",
            )
            _require_hash(
                row.get("registry_sha256"),
                f"{label}.registry_sha256",
            )
            _require_revision(
                row.get("historical_data_revision"),
                f"{label}.historical_data_revision",
            )
            rule_hash = _require_hash(row.get("rule_hash"), f"{label}.rule_hash")
            membership_hash = _require_hash(
                row.get("membership_hash"),
                f"{label}.membership_hash",
            )
            canonical_match_id = _require_string(
                row.get("canonical_match_id"),
                f"{label}.canonical_match_id",
            )
            _require_hypothesis_id(
                row.get("hypothesis_id"),
                f"{label}.hypothesis_id",
            )
            summary = summaries.get(rule_hash)
            if summary is None:
                raise SitePageBuildError(f"MEMBERSHIP_SUMMARY_ORPHAN:{rule_hash}")
            fixture = fixtures.get(canonical_match_id)
            if fixture is None:
                raise SitePageBuildError(
                    f"MEMBERSHIP_FIXTURE_ORPHAN:{canonical_match_id}"
                )
            key = (dataset_hash, rule_hash, canonical_match_id)
            if key in primary_keys:
                raise SitePageBuildError("MEMBERSHIP_PRIMARY_KEY_DUPLICATE")
            primary_keys.add(key)
            historical_rule_counts_by_match[canonical_match_id] += 1
            if membership_hash != _membership_hash(row, fixture, summary):
                raise SitePageBuildError(
                    f"MEMBERSHIP_HASH_MISMATCH:{rule_hash}:{canonical_match_id}"
                )
            _validate_membership_relation(row, summary, fixture, row_index)
            if row.get("eligibility_status") != "ELIGIBLE_SETTLED":
                raise SitePageBuildError(f"MEMBERSHIP_NOT_ELIGIBLE_SETTLED:{row_index}")
            eligibility_reason = _require_string(
                row.get("eligibility_reason"),
                f"{label}.eligibility_reason",
            )
            if eligibility_reason not in ELIGIBILITY_REASONS:
                raise SitePageBuildError(
                    f"MEMBERSHIP_ELIGIBILITY_REASON_INVALID:{row_index}"
                )
            for name in (
                "hypothesis_version",
                "price_class",
                "chronological_fold",
                "statistical_group",
            ):
                _require_string(row.get(name), f"{label}.{name}")
            _require_int(row.get("occurrence_index"), f"{label}.occurrence_index", minimum=1)
            observed_odds = _require_float(
                row.get("observed_odds"),
                f"{label}.observed_odds",
            )
            if observed_odds <= 1:
                raise SitePageBuildError(
                    f"MEMBERSHIP_ODDS_INVALID:{row_index}"
                )
            _require_bounded_float(
                row.get("market_margin"),
                f"{label}.market_margin",
                minimum=0,
                maximum=1,
            )
            for name in ("stake_units", "gross_return_units"):
                _require_bounded_float(
                    row.get(name),
                    f"{label}.{name}",
                    minimum=0,
                )
            for name in ("profit_units", "cumulative_profit_units"):
                _require_float(row.get(name), f"{label}.{name}")
            outcomes = [row.get("won"), row.get("lost"), row.get("void")]
            if any(not isinstance(value, bool) for value in outcomes):
                raise SitePageBuildError(f"MEMBERSHIP_OUTCOME_NOT_BOOLEAN:{row_index}")
            if sum(bool(value) for value in outcomes) != 1:
                raise SitePageBuildError(f"MEMBERSHIP_OUTCOME_NOT_EXCLUSIVE:{row_index}")

            accumulator = accumulators[rule_hash]
            if canonical_match_id in accumulator.canonical_match_ids:
                raise SitePageBuildError("MEMBERSHIP_PRIMARY_KEY_DUPLICATE")
            accumulator.canonical_match_ids.add(canonical_match_id)
            accumulator.wins += int(row["won"] is True)
            accumulator.losses += int(row["lost"] is True)
            accumulator.voids += int(row["void"] is True)
            accumulator.stake_units += float(row["stake_units"])
            accumulator.gross_return_units += float(row["gross_return_units"])
            accumulator.profit_units += float(row["profit_units"])
            if rule_hash in selected:
                selected[rule_hash].append(row)
    return selected, accumulators, dict(historical_rule_counts_by_match)


def _validate_summary_aggregates(
    summaries: Mapping[str, Mapping[str, object]],
    accumulators: Mapping[str, _RuleAccumulator],
) -> None:
    for rule_hash, summary in summaries.items():
        accumulator = accumulators[rule_hash]
        canonical_match_ids = sorted(accumulator.canonical_match_ids)
        expected_set_hash = _canonical_sha256(
            {
                "dataset_hash": summary["dataset_hash"],
                "canonical_match_ids": canonical_match_ids,
            }
        )
        if summary.get("membership_set_hash") != expected_set_hash:
            raise SitePageBuildError(f"MEMBERSHIP_SET_HASH_MISMATCH:{rule_hash}")
        count = len(canonical_match_ids)
        integer_aggregates = {
            "occurrences": count,
            "settled_occurrences": count,
            "wins": accumulator.wins,
            "losses": accumulator.losses,
            "voids": accumulator.voids,
        }
        for name, expected in integer_aggregates.items():
            if summary.get(name) != expected:
                raise SitePageBuildError(
                    f"SUMMARY_AGGREGATE_MISMATCH:{rule_hash}:{name}"
                )
        _assert_close(
            accumulator.stake_units,
            summary.get("total_staked_units"),
            f"{rule_hash}.total_staked_units",
        )
        _assert_close(
            accumulator.gross_return_units,
            summary.get("gross_returns_units"),
            f"{rule_hash}.gross_returns_units",
        )
        _assert_close(
            accumulator.profit_units,
            summary.get("profit_units"),
            f"{rule_hash}.profit_units",
        )


def _validate_selected_order(
    selected: Mapping[str, list[dict[str, object]]],
    fixtures: Mapping[str, Mapping[str, object]],
) -> None:
    for rule_hash, rows in selected.items():
        ordered = sorted(
            rows,
            key=lambda row: (
                _require_int(
                    row["occurrence_index"],
                    "selected.occurrence_index",
                    minimum=1,
                ),
                str(row["canonical_match_id"]),
            ),
        )
        indices = [
            _require_int(
                row["occurrence_index"],
                "selected.occurrence_index",
                minimum=1,
            )
            for row in ordered
        ]
        if indices != list(range(1, len(rows) + 1)):
            raise SitePageBuildError(f"OCCURRENCE_INDEX_INVALID:{rule_hash}")
        chronology = [
            (
                str(fixtures[str(row["canonical_match_id"])]["kickoff_at"]),
                str(row["canonical_match_id"]),
            )
            for row in ordered
        ]
        if chronology != sorted(chronology):
            raise SitePageBuildError(f"OCCURRENCE_CHRONOLOGY_INVALID:{rule_hash}")
        cumulative = 0.0
        for row in ordered:
            cumulative += _require_float(
                row["profit_units"],
                "selected.profit_units",
            )
            if not math.isclose(
                cumulative,
                _require_float(
                    row["cumulative_profit_units"],
                    "selected.cumulative_profit_units",
                ),
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                raise SitePageBuildError(
                    f"CUMULATIVE_PROFIT_INVALID:{rule_hash}:"
                    f"{row['occurrence_index']}"
                )
        rows[:] = ordered


def _safe_match_path(canonical_match_id: str) -> str:
    digest = hashlib.sha256(canonical_match_id.encode("utf-8")).hexdigest()
    return f"matches/{digest}.json"


def _summary_path(hypothesis_id: str) -> str:
    return f"hypotheses/{hypothesis_id}/summary.json"


def _analysis_path(hypothesis_id: str) -> str:
    return f"hypotheses/{hypothesis_id}/analysis.json"


def _query_index_path(hypothesis_id: str) -> str:
    return f"hypotheses/{hypothesis_id}/query-index.json"


def _page_path(hypothesis_id: str, page_size: int, page: int) -> str:
    return (
        f"hypotheses/{hypothesis_id}/memberships/"
        f"{page_size}/page-{page:04d}.json"
    )


def _reason_payload(
    membership: Mapping[str, object],
    summary_path: str,
) -> dict[str, object]:
    reason = str(membership["eligibility_reason"])
    codes = [item.strip() for item in reason.split(";") if item.strip()]
    if not codes:
        raise SitePageBuildError("MEMBERSHIP_REASON_CODES_EMPTY")
    return {
        "eligibility_reason": reason,
        "eligibility_codes": codes,
        "condition_definitions_ref": summary_path,
        "source_columns": [
            "hypothesis_fixture_membership.eligibility_reason",
            "hypothesis_historical_evidence_summary.conditions_json",
        ],
        "per_condition_evaluation_in_source": False,
    }


def _membership_item(
    membership: Mapping[str, object],
    fixture: Mapping[str, object],
    summary_path: str,
) -> dict[str, object]:
    canonical_match_id = str(membership["canonical_match_id"])
    return {
        "evidence_kind": "HISTORICAL",
        "canonical_match_id": canonical_match_id,
        "match_detail_ref": _safe_match_path(canonical_match_id),
        "fixture": {
            "kickoff_at": fixture["kickoff_at"],
            "competition": fixture["competition_name"],
            "competition_key": fixture["competition_key"],
            "season": fixture["season"],
            "round": fixture["round"],
            "home_team": {
                "id": fixture["home_team_id"],
                "name": fixture["home_team_name"],
            },
            "away_team": {
                "id": fixture["away_team_id"],
                "name": fixture["away_team_name"],
            },
            "final_score": {
                "home": fixture["home_goals"],
                "away": fixture["away_goals"],
            },
            "final_status": fixture["final_status"],
        },
        "membership": {
            "membership_hash": membership["membership_hash"],
            "occurrence_index": membership["occurrence_index"],
            "market": membership["market"],
            "selection": membership["selection"],
            "price_class": membership["price_class"],
            "observed_time_status": fixture["observed_time_status"],
            "observed_odds": membership["observed_odds"],
            "market_margin": membership["market_margin"],
            "stake_units": membership["stake_units"],
            "won": membership["won"],
            "lost": membership["lost"],
            "void": membership["void"],
            "gross_return_units": membership["gross_return_units"],
            "profit_units": membership["profit_units"],
            "cumulative_profit_units": membership["cumulative_profit_units"],
            "chronological_fold": membership["chronological_fold"],
            "statistical_group": membership["statistical_group"],
        },
        "reason": _reason_payload(membership, summary_path),
    }


def _membership_outcome(membership: Mapping[str, object]) -> str:
    outcomes = [
        name
        for name, flag in (
            ("won", membership["won"]),
            ("lost", membership["lost"]),
            ("void", membership["void"]),
        )
        if flag is True
    ]
    if len(outcomes) != 1:
        raise SitePageBuildError("MEMBERSHIP_OUTCOME_INVALID")
    return outcomes[0]


def _query_index_item(
    membership: Mapping[str, object],
    fixture: Mapping[str, object],
) -> dict[str, object]:
    canonical_match_id = str(membership["canonical_match_id"])
    return {
        "canonical_match_id": canonical_match_id,
        "match_detail_ref": _safe_match_path(canonical_match_id),
        "occurrence_index": membership["occurrence_index"],
        "kickoff_at": fixture["kickoff_at"],
        "match_date": fixture["match_date"],
        "competition": fixture["competition_name"],
        "competition_key": fixture["competition_key"],
        "season": fixture["season"],
        "round": fixture["round"],
        "home_team": {
            "id": fixture["home_team_id"],
            "name": fixture["home_team_name"],
        },
        "away_team": {
            "id": fixture["away_team_id"],
            "name": fixture["away_team_name"],
        },
        "final_score": {
            "home": fixture["home_goals"],
            "away": fixture["away_goals"],
        },
        "final_status": fixture["final_status"],
        "chronological_fold": membership["chronological_fold"],
        "market": membership["market"],
        "market_margin": membership["market_margin"],
        "selection": membership["selection"],
        "observed_odds": membership["observed_odds"],
        "outcome": _membership_outcome(membership),
        "profit_units": membership["profit_units"],
        "cumulative_profit_units": membership["cumulative_profit_units"],
    }


def _query_index_payload(
    *,
    hypothesis_id: str,
    rule_hash: str,
    summary_ref: str,
    rows: Sequence[Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
    summary: Mapping[str, object],
) -> dict[str, object]:
    if len(rows) > QUERY_INDEX_MAX_ITEMS:
        raise SitePageBuildError(
            f"QUERY_INDEX_ITEM_LIMIT_EXCEEDED:{rule_hash}:"
            f"{len(rows)}:{QUERY_INDEX_MAX_ITEMS}"
        )
    items = [
        _query_index_item(
            row,
            fixtures[str(row["canonical_match_id"])],
        )
        for row in rows
    ]
    match_ids = [str(item["canonical_match_id"]) for item in items]
    if len(set(match_ids)) != len(match_ids):
        raise SitePageBuildError(f"QUERY_INDEX_DUPLICATE_MATCH:{rule_hash}")
    occurrence_indices = [
        _require_int(
            item["occurrence_index"],
            "query_index.occurrence_index",
            minimum=1,
        )
        for item in items
    ]
    if occurrence_indices != list(range(1, len(items) + 1)):
        raise SitePageBuildError(f"QUERY_INDEX_ORDER_INVALID:{rule_hash}")
    return {
        "schema_version": "hypothesis-evidence-query-index-v1",
        "evidence_kind": "HISTORICAL",
        "prospective_evidence_included": False,
        "intended_consumer": "SERVER_RENDERED_MATCH_LIST",
        "transport": "PUBLIC_SAME_ORIGIN_STATIC_ASSET",
        "hypothesis_id": hypothesis_id,
        "rule_hash": rule_hash,
        "summary_ref": summary_ref,
        "ordering": [
            "OCCURRENCE_INDEX_ASC",
            "CANONICAL_MATCH_ID_ASC",
        ],
        "supported_page_sizes": list(PAGE_SIZES),
        "supported_filters": [
            "chronological_fold",
            "observed_odds",
            "outcome",
            "season",
            "selection",
            "team",
        ],
        "supported_sorts": [
            "kickoff_at",
            "observed_odds",
            "outcome",
            "profit_units",
        ],
        "maximum_items": QUERY_INDEX_MAX_ITEMS,
        "total_items": len(items),
        "items": items,
        "provenance": {
            "dataset_hash": summary["dataset_hash"],
            "summary_hash": summary["summary_hash"],
            "membership_set_hash": summary["membership_set_hash"],
            "derived_from": [
                "historical_fixture_evidence",
                "hypothesis_fixture_membership",
            ],
            "provider_payloads_copied": False,
        },
    }


def _analysis_number(value: float) -> float:
    rounded = round(value, 12)
    return 0.0 if rounded == 0 else rounded


def _analysis_match_label(fixture: Mapping[str, object]) -> str:
    home_team = _require_string(
        fixture.get("home_team_name"),
        "analysis.fixture.home_team_name",
    )
    away_team = _require_string(
        fixture.get("away_team_name"),
        "analysis.fixture.away_team_name",
    )
    return f"{home_team} – {away_team}"


def _analysis_reference(
    membership: Mapping[str, object],
    fixtures: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    canonical_match_id = str(membership["canonical_match_id"])
    fixture = fixtures[canonical_match_id]
    return {
        "canonical_match_id": canonical_match_id,
        "match_date": fixture["match_date"],
        "match_detail_ref": _safe_match_path(canonical_match_id),
        "match_label": _analysis_match_label(fixture),
    }


def _aggregate_payload(
    aggregate: _AnalysisAggregate,
    fixtures: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    return {
        "occurrences": aggregate.occurrences,
        "wins": aggregate.wins,
        "losses": aggregate.losses,
        "voids": aggregate.voids,
        "total_staked_units": _analysis_number(aggregate.stake_units),
        "profit_units": _analysis_number(aggregate.profit_units),
        "roi": (
            _analysis_number(
                aggregate.profit_units / aggregate.stake_units
            )
            if aggregate.stake_units > 0
            else None
        ),
        "reference_match": (
            _analysis_reference(aggregate.reference, fixtures)
            if aggregate.reference is not None
            else None
        ),
    }


ODDS_BANDS: Final = (
    ("LT_1_50", "Moins de 1,50", 0.0, 1.5),
    ("FROM_1_50_TO_1_99", "1,50–1,99", 1.5, 2.0),
    ("FROM_2_00_TO_2_99", "2,00–2,99", 2.0, 3.0),
    ("FROM_3_00_TO_4_99", "3,00–4,99", 3.0, 5.0),
    ("GE_5_00", "5,00 ou plus", 5.0, None),
)


def _odds_band_index(odds: float) -> int:
    for index, (_, _, minimum, maximum) in enumerate(ODDS_BANDS):
        if odds >= minimum and (maximum is None or odds < maximum):
            return index
    raise SitePageBuildError(f"ANALYSIS_ODDS_OUT_OF_BANDS:{odds}")


def _streak_payload(
    rows: Sequence[Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    runs: list[dict[str, object]] = []
    current_outcome: str | None = None
    current_rows: list[Mapping[str, object]] = []

    def flush() -> None:
        nonlocal current_outcome, current_rows
        if current_outcome is None or not current_rows:
            current_outcome = None
            current_rows = []
            return
        start = current_rows[0]
        end = current_rows[-1]
        runs.append(
            {
                "outcome": current_outcome,
                "length": len(current_rows),
                "start_occurrence_index": start["occurrence_index"],
                "end_occurrence_index": end["occurrence_index"],
                "start_match": _analysis_reference(start, fixtures),
                "end_match": _analysis_reference(end, fixtures),
            }
        )
        current_outcome = None
        current_rows = []

    for row in rows:
        outcome = (
            "WIN"
            if row["won"] is True
            else "LOSS"
            if row["lost"] is True
            else None
        )
        if outcome is None:
            flush()
            continue
        if outcome != current_outcome:
            flush()
            current_outcome = outcome
        current_rows.append(row)
    flush()

    def run_reference(
        run: Mapping[str, object] | None,
    ) -> dict[str, object] | None:
        if run is None:
            return None
        start_match = run["start_match"]
        end_match = run["end_match"]
        if not isinstance(start_match, Mapping) or not isinstance(
            end_match,
            Mapping,
        ):
            raise SitePageBuildError("ANALYSIS_STREAK_REFERENCE_INVALID")
        return {
            "length": run["length"],
            "start_occurrence_index": run["start_occurrence_index"],
            "end_occurrence_index": run["end_occurrence_index"],
            "start_match": dict(start_match),
            "end_match": dict(end_match),
        }

    def summary(outcome: str) -> dict[str, object]:
        matching = [run for run in runs if run["outcome"] == outcome]
        terminal = runs[-1] if runs and runs[-1]["outcome"] == outcome else None
        longest = (
            min(
                matching,
                key=lambda run: (
                    -_require_int(
                        run["length"],
                        "analysis.streak.length",
                        minimum=1,
                    ),
                    _require_int(
                        run["start_occurrence_index"],
                        "analysis.streak.start_occurrence_index",
                        minimum=1,
                    ),
                ),
            )
            if matching
            else None
        )
        return {
            "run_count": len(matching),
            "longest_length": max(
                (
                    _require_int(
                        run["length"],
                        "analysis.streak.length",
                        minimum=1,
                    )
                    for run in matching
                ),
                default=0,
            ),
            "current_length": (
                _require_int(
                    terminal["length"],
                    "analysis.streak.length",
                    minimum=1,
                )
                if terminal
                else 0
            ),
            "longest_run": run_reference(longest),
            "current_run": run_reference(terminal),
        }

    return {
        "winning": summary("WIN"),
        "losing": summary("LOSS"),
        "runs": [
            {
                "outcome": run["outcome"],
                "length": run["length"],
                "start_occurrence_index": run["start_occurrence_index"],
                "end_occurrence_index": run["end_occurrence_index"],
            }
            for run in runs
        ],
    }


def _analysis_payload(
    *,
    hypothesis_id: str,
    rule_hash: str,
    rows: Sequence[Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
    summary: Mapping[str, object],
) -> dict[str, object]:
    if not rows:
        raise SitePageBuildError(f"ANALYSIS_EVIDENCE_EMPTY:{rule_hash}")
    bankroll_points: list[dict[str, object]] = []
    seasons: dict[int, _AnalysisAggregate] = {}
    folds: dict[str, _AnalysisAggregate] = {}
    band_aggregates = [_AnalysisAggregate() for _ in ODDS_BANDS]
    teams: dict[str, _TeamAggregate] = {}

    for row in rows:
        canonical_match_id = str(row["canonical_match_id"])
        fixture = fixtures[canonical_match_id]
        bankroll_points.append(
            {
                "canonical_match_id": canonical_match_id,
                "match_date": fixture["match_date"],
                "match_detail_ref": _safe_match_path(canonical_match_id),
                "match_label": _analysis_match_label(fixture),
                "occurrence_index": row["occurrence_index"],
                "cumulative_profit_units": _analysis_number(
                    _require_float(
                        row["cumulative_profit_units"],
                        "analysis.cumulative_profit_units",
                    )
                ),
            }
        )

        season = _require_int(
            fixture["season"],
            "analysis.season",
            minimum=1,
        )
        season_aggregate = seasons.setdefault(
            season,
            _AnalysisAggregate(reference=row),
        )
        season_aggregate.add(row)

        fold = str(row["chronological_fold"])
        fold_aggregate = folds.setdefault(
            fold,
            _AnalysisAggregate(reference=row),
        )
        fold_aggregate.add(row)

        observed_odds = _require_float(
            row["observed_odds"],
            "analysis.observed_odds",
        )
        band_aggregates[_odds_band_index(observed_odds)].add(row)

        for side in ("home", "away"):
            team_id = str(fixture[f"{side}_team_id"])
            team = teams.setdefault(
                team_id,
                _TeamAggregate(
                    reference=row,
                    team_id=team_id,
                    team_name=str(fixture[f"{side}_team_name"]),
                ),
            )
            if team.team_name != str(fixture[f"{side}_team_name"]):
                raise SitePageBuildError(
                    f"ANALYSIS_TEAM_NAME_CONFLICT:{team_id}"
                )
            if side == "home":
                team.home_occurrences += 1
            else:
                team.away_occurrences += 1
            team.add_result(row)

    if len({point["canonical_match_id"] for point in bankroll_points}) != len(
        bankroll_points
    ):
        raise SitePageBuildError(f"ANALYSIS_BANKROLL_DUPLICATE:{rule_hash}")
    if not math.isclose(
        _require_float(
            rows[-1]["cumulative_profit_units"],
            "analysis.final_cumulative_profit_units",
        ),
        _require_float(
            summary["profit_units"],
            "analysis.summary_profit_units",
        ),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise SitePageBuildError(f"ANALYSIS_BANKROLL_SUMMARY_MISMATCH:{rule_hash}")

    season_rows: list[dict[str, object]] = []
    for season, season_value in sorted(seasons.items()):
        season_rows.append(
            {
                "season": season,
                **_aggregate_payload(season_value, fixtures),
            }
        )
    ordered_folds = sorted(
        folds.items(),
        key=lambda item: (
            _require_int(
                item[1].reference["occurrence_index"],
                "analysis.fold.occurrence_index",
                minimum=1,
            )
            if item[1].reference is not None
            else 0
        ),
    )
    fold_rows: list[dict[str, object]] = []
    for index, (fold, fold_value) in enumerate(ordered_folds, start=1):
        fold_rows.append(
            {
                "fold_index": index,
                "fold": fold,
                "positive": fold_value.profit_units > 0,
                **_aggregate_payload(fold_value, fixtures),
            }
        )
    odds_rows = []
    for (band_id, label, minimum, maximum), band_value in zip(
        ODDS_BANDS,
        band_aggregates,
        strict=True,
    ):
        odds_rows.append(
            {
                "band_id": band_id,
                "label": label,
                "minimum_odds": minimum,
                "maximum_odds_exclusive": maximum,
                **_aggregate_payload(band_value, fixtures),
            }
        )

    team_appearances = len(rows) * 2
    team_rows = []
    for rank, team_value in enumerate(
        sorted(
            teams.values(),
            key=lambda item: (
                -item.occurrences,
                item.team_name.casefold(),
                item.team_id,
            ),
        )[:10],
        start=1,
    ):
        team_rows.append(
            {
                "rank": rank,
                "team_id": team_value.team_id,
                "team_name": team_value.team_name,
                "occurrences": team_value.occurrences,
                "home_occurrences": team_value.home_occurrences,
                "away_occurrences": team_value.away_occurrences,
                "wins": team_value.wins,
                "losses": team_value.losses,
                "voids": team_value.voids,
                "profit_units": _analysis_number(team_value.profit_units),
                "share_of_team_appearances": _analysis_number(
                    team_value.occurrences / team_appearances
                ),
                "reference_match": _analysis_reference(
                    team_value.reference,
                    fixtures,
                ),
            }
        )

    return {
        "schema_version": "hypothesis-evidence-analysis-v1",
        "evidence_kind": "HISTORICAL",
        "prospective_evidence_included": False,
        "hypothesis_id": hypothesis_id,
        "rule_hash": rule_hash,
        "bankroll_points": bankroll_points,
        "seasons": season_rows,
        "odds_bands": odds_rows,
        "folds": fold_rows,
        "team_concentration": {
            "maximum_items": 10,
            "denominator_team_appearances": team_appearances,
            "items": team_rows,
        },
        "streaks": _streak_payload(rows, fixtures),
        "provenance": {
            "dataset_hash": summary["dataset_hash"],
            "summary_hash": summary["summary_hash"],
            "membership_set_hash": summary["membership_set_hash"],
            "derived_from": [
                "historical_fixture_evidence",
                "hypothesis_fixture_membership",
                "hypothesis_historical_evidence_summary",
            ],
            "provider_payloads_copied": False,
        },
    }


class _OutputWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: list[dict[str, object]] = []

    def write(
        self,
        relative_path: str,
        payload: object,
        *,
        maximum_bytes: int | None = None,
        row_count: int,
        record_kind: str,
    ) -> None:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise SitePageBuildError("OUTPUT_RELATIVE_PATH_INVALID")
        encoded = (_canonical_json(payload, pretty=True) + "\n").encode("utf-8")
        if maximum_bytes is not None and len(encoded) > maximum_bytes:
            raise SitePageBuildError(
                f"OUTPUT_SIZE_LIMIT_EXCEEDED:{relative_path}:"
                f"{len(encoded)}:{maximum_bytes}"
            )
        path = self.root.joinpath(*pure.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_bytes(encoded)
            os.replace(temporary, path)
        except OSError as exc:
            raise SitePageBuildError(f"OUTPUT_WRITE_FAILED:{relative_path}") from exc
        self.entries.append(
            {
                "path": relative_path,
                "record_kind": record_kind,
                "row_count": row_count,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )


def _assert_output_safe(
    output_root: Path,
    artifact_root: Path,
    top_ten_report: Path,
) -> None:
    ignored_artifact_root = (ROOT / "artifacts").resolve()
    if output_root.is_relative_to(ROOT) and not output_root.is_relative_to(
        ignored_artifact_root
    ):
        raise SitePageBuildError("OUTPUT_INSIDE_TRACKED_REPOSITORY_AREA")
    if output_root == artifact_root or output_root in artifact_root.parents:
        raise SitePageBuildError("OUTPUT_WOULD_REPLACE_INPUT_ARTIFACTS")
    if artifact_root in output_root.parents:
        raise SitePageBuildError("OUTPUT_INSIDE_INPUT_ARTIFACTS")
    if output_root == top_ten_report or output_root in top_ten_report.parents:
        raise SitePageBuildError("OUTPUT_WOULD_REPLACE_TOP_TEN_REPORT")
    if ".git" in output_root.parts:
        raise SitePageBuildError("OUTPUT_INSIDE_GIT_METADATA")
    if output_root.is_symlink():
        raise SitePageBuildError("OUTPUT_SYMLINK_FORBIDDEN")
    if output_root.exists() and not output_root.is_dir():
        raise SitePageBuildError("OUTPUT_NOT_DIRECTORY")


def _publish_staging(staging: Path, output_root: Path) -> None:
    backup: Path | None = None
    try:
        if output_root.exists():
            backup = output_root.with_name(
                f".{output_root.name}.backup-{uuid.uuid4().hex}"
            )
            os.replace(output_root, backup)
        os.replace(staging, output_root)
    except OSError as exc:
        if backup is not None and backup.exists() and not output_root.exists():
            os.replace(backup, output_root)
        raise SitePageBuildError("OUTPUT_ATOMIC_PUBLISH_FAILED") from exc
    if backup is not None:
        shutil.rmtree(backup)


def _build_output(
    staging: Path,
    *,
    top_items: Sequence[Mapping[str, object]],
    ranking_path: str,
    selected: Mapping[str, list[dict[str, object]]],
    historical_rule_counts_by_match: Mapping[str, int],
    fixtures: Mapping[str, Mapping[str, object]],
    summaries: Mapping[str, Mapping[str, object]],
    conditions: Mapping[str, list[object]],
    inputs: Sequence[Mapping[str, object]],
    top_report_entry: Mapping[str, object],
) -> tuple[int, int, str]:
    writer = _OutputWriter(staging)
    selected_match_ids: set[str] = set()
    hypothesis_index: list[dict[str, object]] = []
    match_links: dict[str, list[dict[str, object]]] = defaultdict(list)
    selected_memberships = 0

    for top_item in top_items:
        rank_value = top_item["rank"]
        rank = (
            None
            if rank_value is None
            else _require_int(rank_value, "top_item.rank", minimum=1)
        )
        hypothesis_id = str(top_item["hypothesis_id"])
        rule_hash = str(top_item["rule_hash"])
        summary = summaries[rule_hash]
        rows = selected[rule_hash]
        if not rows:
            raise SitePageBuildError(f"TOP_TEN_HYPOTHESIS_HAS_NO_EVIDENCE:{rule_hash}")
        summary_ref = _summary_path(hypothesis_id)
        pages_by_size: dict[str, dict[str, object]] = {}
        for page_size in PAGE_SIZES:
            total_pages = math.ceil(len(rows) / page_size)
            page_refs: list[str] = []
            for page_number in range(1, total_pages + 1):
                start = (page_number - 1) * page_size
                page_rows = rows[start : start + page_size]
                page_ref = _page_path(hypothesis_id, page_size, page_number)
                page_refs.append(page_ref)
                items = [
                    _membership_item(row, fixtures[str(row["canonical_match_id"])], summary_ref)
                    for row in page_rows
                ]
                writer.write(
                    page_ref,
                    {
                        "schema_version": "hypothesis-evidence-membership-page-v1",
                        "evidence_kind": "HISTORICAL",
                        "prospective_evidence_included": False,
                        "hypothesis_id": hypothesis_id,
                        "rule_hash": rule_hash,
                        "summary_ref": summary_ref,
                        "condition_definitions": conditions[rule_hash],
                        "ordering": ["OCCURRENCE_INDEX_ASC", "CANONICAL_MATCH_ID_ASC"],
                        "page_size": page_size,
                        "page": page_number,
                        "total_pages": total_pages,
                        "total_items": len(rows),
                        "items": items,
                    },
                    maximum_bytes=MEMBERSHIP_PAGE_MAX_BYTES,
                    row_count=len(items),
                    record_kind="HISTORICAL_MEMBERSHIP_PAGE",
                )
                for offset, row in enumerate(page_rows):
                    canonical_match_id = str(row["canonical_match_id"])
                    selected_match_ids.add(canonical_match_id)
                    match_links[canonical_match_id].append(
                        {
                            "hypothesis_id": hypothesis_id,
                            "rule_hash": rule_hash,
                            "summary_ref": summary_ref,
                            "page_size": page_size,
                            "page": page_number,
                            "item_index": offset,
                        }
                    )
            pages_by_size[str(page_size)] = {
                "page_size": page_size,
                "total_pages": total_pages,
                "page_refs": page_refs,
            }
        selected_memberships += len(rows)
        analysis_ref = _analysis_path(hypothesis_id)
        writer.write(
            analysis_ref,
            _analysis_payload(
                hypothesis_id=hypothesis_id,
                rule_hash=rule_hash,
                rows=rows,
                fixtures=fixtures,
                summary=summary,
            ),
            maximum_bytes=ANALYSIS_MAX_BYTES,
            row_count=len(rows),
            record_kind="HYPOTHESIS_HISTORICAL_ANALYSIS",
        )
        query_index_ref = _query_index_path(hypothesis_id)
        writer.write(
            query_index_ref,
            _query_index_payload(
                hypothesis_id=hypothesis_id,
                rule_hash=rule_hash,
                summary_ref=summary_ref,
                rows=rows,
                fixtures=fixtures,
                summary=summary,
            ),
            maximum_bytes=QUERY_INDEX_MAX_BYTES,
            row_count=len(rows),
            record_kind="HYPOTHESIS_MEMBERSHIP_QUERY_INDEX",
        )
        historical_summary = {
            name: summary[name] for name in SUMMARY_PUBLIC_FIELDS
        }
        writer.write(
            summary_ref,
            {
                "schema_version": "hypothesis-evidence-site-summary-v1",
                "rank": rank,
                "hypothesis_id": hypothesis_id,
                "rule_hash": rule_hash,
                "analysis_ref": analysis_ref,
                "query_index_ref": query_index_ref,
                "evidence_availability": {
                    "historical": {
                        "available": True,
                        "source": "NORMALIZED_FROZEN_PARQUET",
                    },
                    "prospective": {
                        "available": False,
                        "reason_code": "NOT_PRESENT_IN_HISTORICAL_ARTIFACTS",
                    },
                },
                "conditions": conditions[rule_hash],
                "historical_summary": historical_summary,
                "membership_pages": pages_by_size,
                "provenance": {
                    "dataset_hash": summary["dataset_hash"],
                    "campaign_result_hash": summary["campaign_result_hash"],
                    "registry_sha256": summary["registry_sha256"],
                    "historical_data_revision": summary["historical_data_revision"],
                    "summary_hash": summary["summary_hash"],
                    "membership_set_hash": summary["membership_set_hash"],
                },
            },
            maximum_bytes=SUMMARY_MAX_BYTES,
            row_count=1,
            record_kind="HYPOTHESIS_HISTORICAL_SUMMARY",
        )
        hypothesis_index.append(
            {
                "rank": rank,
                "hypothesis_id": hypothesis_id,
                "rule_hash": rule_hash,
                "summary_ref": summary_ref,
                "historical_occurrences": len(rows),
                "prospective_evidence_included": False,
            }
        )

    match_index: list[dict[str, object]] = []
    for canonical_match_id in sorted(
        selected_match_ids,
        key=lambda match_id: (
            str(fixtures[match_id]["kickoff_at"]),
            match_id,
        ),
    ):
        fixture = fixtures[canonical_match_id]
        detail_ref = _safe_match_path(canonical_match_id)
        raw_links = match_links[canonical_match_id]
        grouped_links: dict[str, dict[str, object]] = {}
        for link in raw_links:
            hypothesis_id = str(link["hypothesis_id"])
            association = grouped_links.setdefault(
                hypothesis_id,
                {
                    "hypothesis_id": hypothesis_id,
                    "rule_hash": link["rule_hash"],
                    "summary_ref": link["summary_ref"],
                    "membership_page_refs": [],
                },
            )
            association_page_refs = association["membership_page_refs"]
            if not isinstance(association_page_refs, list):
                raise SitePageBuildError("MATCH_LINK_PAGE_REFS_INVALID")
            association_page_refs.append(
                {
                    "page_size": link["page_size"],
                    "page": link["page"],
                    "path": _page_path(
                        hypothesis_id,
                        _require_int(
                            link["page_size"],
                            "match_link.page_size",
                            minimum=1,
                        ),
                        _require_int(
                            link["page"],
                            "match_link.page",
                            minimum=1,
                        ),
                    ),
                    "item_index": link["item_index"],
                }
            )
        associations: list[dict[str, object]] = []
        for hypothesis_id in sorted(grouped_links):
            association = grouped_links[hypothesis_id]
            rule_hash = str(association["rule_hash"])
            membership = next(
                row
                for row in selected[rule_hash]
                if row["canonical_match_id"] == canonical_match_id
            )
            association["membership"] = {
                "membership_hash": membership["membership_hash"],
                "market": membership["market"],
                "selection": membership["selection"],
                "observed_odds": membership["observed_odds"],
                "market_margin": membership["market_margin"],
                "won": membership["won"],
                "lost": membership["lost"],
                "void": membership["void"],
                "profit_units": membership["profit_units"],
            }
            association["reason"] = _reason_payload(
                membership,
                str(association["summary_ref"]),
            )
            associations.append(association)
        if len(associations) > len(top_items):
            raise SitePageBuildError("MATCH_HYPOTHESIS_LINKS_OVER_BOUND")
        total_historical_rules = historical_rule_counts_by_match.get(
            canonical_match_id
        )
        if (
            total_historical_rules is None
            or total_historical_rules < len(associations)
        ):
            raise SitePageBuildError("MATCH_HISTORICAL_RULE_COUNT_INVALID")
        writer.write(
            detail_ref,
            {
                "schema_version": "hypothesis-evidence-historical-match-v1",
                "evidence_kind": "HISTORICAL",
                "prospective_evidence_included": False,
                "canonical_match_id": canonical_match_id,
                "fixture": {
                    "kickoff_at": fixture["kickoff_at"],
                    "match_date": fixture["match_date"],
                    "competition": fixture["competition_name"],
                    "competition_key": fixture["competition_key"],
                    "season": fixture["season"],
                    "round": fixture["round"],
                    "home_team": {
                        "id": fixture["home_team_id"],
                        "name": fixture["home_team_name"],
                    },
                    "away_team": {
                        "id": fixture["away_team_id"],
                        "name": fixture["away_team_name"],
                    },
                    "final_score": {
                        "home": fixture["home_goals"],
                        "away": fixture["away_goals"],
                    },
                    "final_status": fixture["final_status"],
                },
                "source_reference": {
                    "dataset_hash": fixture["dataset_hash"],
                    "source_row_hash": fixture["source_row_hash"],
                    "source": fixture["source"],
                    "observed_time_status": fixture["observed_time_status"],
                },
                "total_historical_rules": total_historical_rules,
                "top_ten_hypotheses": associations,
            },
            maximum_bytes=MATCH_DETAIL_MAX_BYTES,
            row_count=1,
            record_kind="UNIQUE_HISTORICAL_MATCH_DETAIL",
        )
        match_index.append(
            {
                "canonical_match_id": canonical_match_id,
                "detail_ref": detail_ref,
                "hypothesis_count": total_historical_rules,
                "published_hypothesis_count": len(associations),
            }
        )

    writer.write(
        "matches/index.json",
        {
            "schema_version": "hypothesis-evidence-match-index-v1",
            "evidence_kind": "HISTORICAL",
            "prospective_evidence_included": False,
            "ordering": ["KICKOFF_AT_ASC", "CANONICAL_MATCH_ID_ASC"],
            "items": match_index,
        },
        row_count=len(match_index),
        record_kind="HISTORICAL_MATCH_INDEX",
    )
    writer.write(
        "index.json",
        {
            "schema_version": "hypothesis-evidence-site-index-v1",
            "preview_scope": "RANKING_TOP_TEN_UNION",
            "ranking_source": ranking_path,
            "maximum_hypotheses": len(top_items),
            "evidence_availability": {
                "historical": True,
                "prospective": False,
            },
            "hypotheses": hypothesis_index,
            "match_index_ref": "matches/index.json",
        },
        row_count=len(hypothesis_index),
        record_kind="HYPOTHESIS_INDEX",
    )

    writer.entries.sort(key=lambda item: str(item["path"]))
    content_tree_sha256 = _canonical_sha256(writer.entries)
    manifest = {
        "schema_version": "hypothesis-evidence-site-manifest-v1",
        "publication_scope": "TEMPORARY_PREVIEW_NOT_FOR_GIT",
        "selection": {
            "ranking_source": ranking_path,
            "maximum_hypotheses": len(top_items),
            "hypothesis_count": len(top_items),
            "hypothesis_ids": [item["hypothesis_id"] for item in top_items],
        },
        "evidence": {
            "historical_included": True,
            "prospective_included": False,
            "provider_payloads_copied": False,
            "analysis_max_bytes": ANALYSIS_MAX_BYTES,
            "match_detail_max_bytes": MATCH_DETAIL_MAX_BYTES,
            "membership_page_max_bytes": MEMBERSHIP_PAGE_MAX_BYTES,
            "query_index_max_bytes": QUERY_INDEX_MAX_BYTES,
            "query_index_max_items": QUERY_INDEX_MAX_ITEMS,
            "query_index_intended_consumer": "SERVER_RENDERED_MATCH_LIST",
            "query_index_transport": "PUBLIC_SAME_ORIGIN_STATIC_ASSET",
            "summary_max_bytes": SUMMARY_MAX_BYTES,
            "selected_membership_rows": selected_memberships,
            "unique_match_rows": len(match_index),
            "maximum_hypothesis_links_per_match": len(top_items),
            "maximum_historical_rule_count_for_published_matches": max(
                (
                    historical_rule_counts_by_match[match_id]
                    for match_id in selected_match_ids
                ),
                default=0,
            ),
        },
        "inputs": {
            "parquet": list(inputs),
            "top_ten_report": dict(top_report_entry),
        },
        "outputs": writer.entries,
        "content_tree_sha256": content_tree_sha256,
    }
    writer.write(
        "manifest.json",
        manifest,
        row_count=len(writer.entries),
        record_kind="OUTPUT_MANIFEST",
    )
    return selected_memberships, len(match_index), content_tree_sha256


def build_hypothesis_evidence_site_pages(
    artifact_root: Path,
    top_ten_report: Path,
    output_root: Path,
) -> SitePageBuildResult:
    """Validate normalized evidence and atomically publish bounded JSON pages."""

    artifact_root = artifact_root.resolve()
    top_ten_report = top_ten_report.resolve()
    output_root = output_root.resolve()
    _assert_output_safe(output_root, artifact_root, top_ten_report)

    fixture_path = artifact_root / PARQUET_NAMES[0]
    membership_path = artifact_root / PARQUET_NAMES[1]
    summary_path = artifact_root / PARQUET_NAMES[2]
    fixture_parquet = _require_columns(fixture_path, FIXTURE_FIELDS)
    membership_parquet = _require_columns(membership_path, MEMBERSHIP_FIELDS)
    summary_parquet = _require_columns(summary_path, SUMMARY_FIELDS)
    parquet_files = {
        fixture_path.name: fixture_parquet,
        membership_path.name: membership_parquet,
        summary_path.name: summary_parquet,
    }
    input_metadata: dict[str, tuple[Path, int, str]] = {}
    input_entries: list[dict[str, object]] = []
    for name in PARQUET_NAMES:
        path = artifact_root / name
        parquet = parquet_files[name]
        rows = int(parquet.metadata.num_rows)
        digest = _sha256_file(path)
        input_metadata[name] = (path, rows, digest)
        input_entries.append(
            {
                "name": name,
                "rows": rows,
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        )
    _validate_optional_artifact_manifest(artifact_root, input_metadata)

    fixtures, dataset_hash = _load_fixtures(fixture_parquet)
    summaries, conditions = _load_summaries(summary_parquet, dataset_hash)
    report = _load_json_object(top_ten_report)
    top_items, ranking_path = _top_ten_items(report, summaries, dataset_hash)
    selected_rules = {str(item["rule_hash"]) for item in top_items}
    (
        selected,
        accumulators,
        historical_rule_counts_by_match,
    ) = _stream_memberships(
        membership_parquet,
        fixtures,
        summaries,
        selected_rules,
    )
    _validate_summary_aggregates(summaries, accumulators)
    _validate_selected_order(selected, fixtures)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.staging-",
            dir=output_root.parent,
        )
    )
    try:
        selected_memberships, unique_matches, tree_hash = _build_output(
            staging,
            top_items=top_items,
            ranking_path=ranking_path,
            selected=selected,
            historical_rule_counts_by_match=historical_rule_counts_by_match,
            fixtures=fixtures,
            summaries=summaries,
            conditions=conditions,
            inputs=input_entries,
            top_report_entry={
                "name": top_ten_report.name,
                "bytes": top_ten_report.stat().st_size,
                "sha256": _sha256_file(top_ten_report),
            },
        )
        _publish_staging(staging, output_root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return SitePageBuildResult(
        output_root=output_root,
        hypothesis_count=len(top_items),
        unique_match_count=unique_matches,
        selected_membership_count=selected_memberships,
        content_tree_sha256=tree_hash,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a bounded temporary site-page projection from the three "
            "normalized historical-evidence Parquet artifacts."
        )
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
    )
    parser.add_argument(
        "--top-ten-report",
        type=Path,
        default=DEFAULT_TOP_TEN_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_hypothesis_evidence_site_pages(
        args.artifact_root,
        args.top_ten_report,
        args.output,
    )
    print(
        _canonical_json(
            {
                "status": "BUILT",
                "output_root": str(result.output_root),
                "hypothesis_count": result.hypothesis_count,
                "unique_match_count": result.unique_match_count,
                "selected_membership_count": result.selected_membership_count,
                "content_tree_sha256": result.content_tree_sha256,
                "provider_calls": 0,
                "network_calls": 0,
                "database_writes": 0,
                "r2_operations": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
