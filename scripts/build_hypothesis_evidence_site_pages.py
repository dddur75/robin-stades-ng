"""Build bounded, static historical-evidence pages from normalized Parquet.

This adapter deliberately does not reconstruct evidence and does not contact a
provider, object storage, or a database.  It validates the three normalized
J10 evidence tables, selects at most the ten hypotheses named by the compact
top-10 report, and publishes a temporary preview directory atomically.
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
from pathlib import Path, PurePosixPath
from typing import Any, Final

import pyarrow.parquet as pq  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "hypothesis-evidence"
DEFAULT_TOP_TEN_REPORT = ROOT / "reports" / "hypothesis-evidence" / "top-10.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "hypothesis-evidence-site-pages"

PAGE_SIZES: Final = (25, 50)
PARQUET_NAMES: Final = (
    "historical_fixture_evidence.parquet",
    "hypothesis_fixture_membership.parquet",
    "hypothesis_historical_evidence_summary.parquet",
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_HYPOTHESIS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

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
}
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
        canonical_match_id = _require_string(
            row.get("canonical_match_id"),
            f"{label}.canonical_match_id",
        )
        key = (source_dataset, canonical_match_id)
        if key in primary_keys:
            raise SitePageBuildError("FIXTURE_PRIMARY_KEY_DUPLICATE")
        primary_keys.add(key)
        if canonical_match_id in fixtures:
            raise SitePageBuildError("FIXTURE_CANONICAL_ID_AMBIGUOUS")
        for name in (
            "fixture_id",
            "competition_key",
            "competition_name",
            "competition",
            "final_status",
            "match_date",
            "kickoff_at",
            "home_team_id",
            "away_team_id",
            "home_team_name",
            "away_team_name",
            "observed_time_status",
            "source",
        ):
            _require_string(row.get(name), f"{label}.{name}")
        _require_int(row.get("season"), f"{label}.season")
        _require_int(row.get("home_goals"), f"{label}.home_goals")
        _require_int(row.get("away_goals"), f"{label}.away_goals")
        fixtures[canonical_match_id] = row
    if dataset_hash is None:
        raise SitePageBuildError("FIXTURE_TABLE_EMPTY")
    return fixtures, dataset_hash


def _summary_core(row: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key != "summary_hash"}


def _parse_conditions(row: Mapping[str, object], label: str) -> list[object]:
    conditions_json = _require_string(row.get("conditions_json"), label)
    try:
        conditions = json.loads(conditions_json)
    except json.JSONDecodeError as exc:
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_INVALID:{label}") from exc
    if not isinstance(conditions, list):
        raise SitePageBuildError(f"SUMMARY_CONDITIONS_NOT_LIST:{label}")
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
        for name in (
            "total_staked_units",
            "gross_returns_units",
            "profit_units",
            "maximum_drawdown_units",
            "p_value",
            "q_value",
        ):
            _require_float(row.get(name), f"{label}.{name}")
        for name in ("hit_rate", "average_odds", "median_odds", "roi"):
            if row.get(name) is not None:
                _require_float(row.get(name), f"{label}.{name}")
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
    if report.get("dataset_hash") != dataset_hash:
        raise SitePageBuildError("TOP_TEN_DATASET_HASH_MISMATCH")
    source_result_hash = _require_hash(
        report.get("source_result_hash"),
        "top_ten.source_result_hash",
    )
    global_scope = report.get("global")
    if not isinstance(global_scope, Mapping):
        raise SitePageBuildError("TOP_TEN_GLOBAL_INVALID")
    by_roi = global_scope.get("by_roi")
    ranking_path: str
    items_value: object
    if by_roi is not None:
        if not isinstance(by_roi, Mapping):
            raise SitePageBuildError("TOP_TEN_BY_ROI_INVALID")
        items_value = by_roi.get("items")
        ranking_path = "global.by_roi.items"
    else:
        items_value = global_scope.get("items")
        ranking_path = "global.items"
    if not isinstance(items_value, list):
        raise SitePageBuildError("TOP_TEN_ITEMS_INVALID")
    if len(items_value) > 10:
        raise SitePageBuildError("TOP_TEN_ITEMS_OVER_LIMIT")

    output: list[dict[str, object]] = []
    seen_hypotheses: set[str] = set()
    seen_rules: set[str] = set()
    for rank, value in enumerate(items_value, start=1):
        if not isinstance(value, Mapping):
            raise SitePageBuildError(f"TOP_TEN_ITEM_INVALID:{rank}")
        hypothesis_id = _require_hypothesis_id(
            value.get("hypothesis_id"),
            f"top_ten[{rank}].hypothesis_id",
        )
        rule_hash = _require_hash(
            value.get("rule_hash"),
            f"top_ten[{rank}].rule_hash",
        )
        membership_set_hash = _require_hash(
            value.get("membership_set_hash"),
            f"top_ten[{rank}].membership_set_hash",
        )
        if hypothesis_id in seen_hypotheses or rule_hash in seen_rules:
            raise SitePageBuildError("TOP_TEN_ITEM_DUPLICATE")
        seen_hypotheses.add(hypothesis_id)
        seen_rules.add(rule_hash)
        summary = summaries.get(rule_hash)
        if summary is None:
            raise SitePageBuildError(f"TOP_TEN_SUMMARY_MISSING:{rule_hash}")
        if summary.get("hypothesis_id") != hypothesis_id:
            raise SitePageBuildError(f"TOP_TEN_HYPOTHESIS_RELATION_INVALID:{rule_hash}")
        if summary.get("membership_set_hash") != membership_set_hash:
            raise SitePageBuildError(f"TOP_TEN_MEMBERSHIP_SET_INVALID:{rule_hash}")
        if summary.get("campaign_result_hash") != source_result_hash:
            raise SitePageBuildError(f"TOP_TEN_CAMPAIGN_HASH_INVALID:{rule_hash}")
        output.append(
            {
                "rank": rank,
                "hypothesis_id": hypothesis_id,
                "rule_hash": rule_hash,
                "membership_set_hash": membership_set_hash,
            }
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
]:
    selected: dict[str, list[dict[str, object]]] = {
        rule_hash: [] for rule_hash in selected_rules
    }
    accumulators: dict[str, _RuleAccumulator] = {
        rule_hash: _RuleAccumulator(set()) for rule_hash in summaries
    }
    primary_keys: set[tuple[str, str, str]] = set()
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
            if membership_hash != _membership_hash(row, fixture, summary):
                raise SitePageBuildError(
                    f"MEMBERSHIP_HASH_MISMATCH:{rule_hash}:{canonical_match_id}"
                )
            _validate_membership_relation(row, summary, fixture, row_index)
            if row.get("eligibility_status") != "ELIGIBLE_SETTLED":
                raise SitePageBuildError(f"MEMBERSHIP_NOT_ELIGIBLE_SETTLED:{row_index}")
            _require_string(
                row.get("eligibility_reason"),
                f"{label}.eligibility_reason",
            )
            for name in (
                "hypothesis_version",
                "price_class",
                "chronological_fold",
                "statistical_group",
            ):
                _require_string(row.get(name), f"{label}.{name}")
            _require_int(row.get("occurrence_index"), f"{label}.occurrence_index", minimum=1)
            for name in (
                "observed_odds",
                "market_margin",
                "stake_units",
                "gross_return_units",
                "profit_units",
                "cumulative_profit_units",
            ):
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
    return selected, accumulators


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


class _OutputWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: list[dict[str, object]] = []

    def write(
        self,
        relative_path: str,
        payload: object,
        *,
        row_count: int,
        record_kind: str,
    ) -> None:
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise SitePageBuildError("OUTPUT_RELATIVE_PATH_INVALID")
        encoded = (_canonical_json(payload, pretty=True) + "\n").encode("utf-8")
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
        rank = _require_int(top_item["rank"], "top_item.rank", minimum=1)
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
                "top_ten_hypotheses": associations,
            },
            row_count=1,
            record_kind="UNIQUE_HISTORICAL_MATCH_DETAIL",
        )
        match_index.append(
            {
                "canonical_match_id": canonical_match_id,
                "detail_ref": detail_ref,
                "hypothesis_count": len(associations),
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
            "preview_scope": "GLOBAL_TOP_ROI_ONLY",
            "ranking_source": ranking_path,
            "maximum_hypotheses": 10,
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
            "maximum_hypotheses": 10,
            "hypothesis_count": len(top_items),
            "hypothesis_ids": [item["hypothesis_id"] for item in top_items],
        },
        "evidence": {
            "historical_included": True,
            "prospective_included": False,
            "provider_payloads_copied": False,
            "selected_membership_rows": selected_memberships,
            "unique_match_rows": len(match_index),
            "maximum_hypothesis_links_per_match": len(top_items),
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
    selected, accumulators = _stream_memberships(
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
