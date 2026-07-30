from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from robin.historical.storage import canonical_record_hash
from scripts.build_hypothesis_evidence_site_pages import (
    ANALYSIS_MAX_BYTES,
    MATCH_DETAIL_MAX_BYTES,
    MEMBERSHIP_PAGE_MAX_BYTES,
    QUERY_INDEX_MAX_BYTES,
    QUERY_INDEX_MAX_ITEMS,
    SUMMARY_MAX_BYTES,
    SitePageBuildError,
    _canonical_sha256,
    _safe_match_path,
    build_hypothesis_evidence_site_pages,
)

DATASET_HASH = "a" * 64
CAMPAIGN_HASH = "b" * 64
REGISTRY_HASH = "c" * 64
HISTORICAL_REVISION = "d" * 40
RULE_ONE = "1" * 64
RULE_TWO = "2" * 64
RULE_THREE = "3" * 64
RULE_HIDDEN = "4" * 64


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(index: int) -> dict[str, object]:
    raw_fixture_id = 10_000 + index
    raw_home_team_id = 20_000 + index * 2
    raw_away_team_id = raw_home_team_id + 1
    fixture_id = str(raw_fixture_id)
    match_date = (date(2024, 1, 1) + timedelta(days=index)).isoformat()
    kickoff_at = f"{match_date}T15:00:00+00:00"
    source_record: dict[str, object] = {
        "competition": "Test League",
        "season": 2024,
        "match_date": match_date,
        "home_source_name": f"Home {index}",
        "away_source_name": f"Away {index}",
        "home_goals": 2 if index % 2 == 0 else 0,
        "away_goals": 1,
        "odds_home": 2.0,
        "odds_draw": 3.0,
        "odds_away": 4.0,
        "odds_over_25": 2.1,
        "odds_under_25": 1.8,
        "bookmaker_1x2": "Synthetic Book",
        "bookmaker_totals": "Synthetic Book",
        "price_type": "HISTORICAL_PRE_CLOSING_MARKET",
        "totals_price_type": "HISTORICAL_PRE_CLOSING_MARKET",
        "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
        "quality_status": "ACCEPTED",
        "source": "SYNTHETIC_NORMALIZED_FIXTURE",
        "raw_payload_hash": _sha(f"raw:{fixture_id}"),
        "mapping_status": "MAPPED",
        "fixture_id": raw_fixture_id,
        "kickoff_at": kickoff_at,
        "home_team_id": raw_home_team_id,
        "away_team_id": raw_away_team_id,
        "market_margin_1x2": 0.05,
        "market_margin_totals": 0.04,
        "de_vig_home": 0.45,
        "de_vig_draw": 0.30,
        "de_vig_away": 0.25,
        "de_vig_over_25": 0.48,
        "de_vig_under_25": 0.52,
        "quality": "ACCEPTED",
    }
    record_hash = canonical_record_hash(source_record)
    return {
        **source_record,
        "dataset_hash": DATASET_HASH,
        "source_dataset_hash": DATASET_HASH,
        "record_hash": record_hash,
        "source_row_hash": record_hash,
        "canonical_match_id": f"api-football:{fixture_id}",
        "fixture_id": fixture_id,
        "competition_key": "TEST_LEAGUE",
        "competition_name": "Test League",
        "round": f"Round {index + 1}",
        "final_status": "FT",
        "home_team_id": str(raw_home_team_id),
        "away_team_id": str(raw_away_team_id),
        "home_team_name": f"Home {index}",
        "away_team_name": f"Away {index}",
    }


def _membership_set_hash(fixture_rows: list[dict[str, object]]) -> str:
    return _canonical_sha256(
        {
            "dataset_hash": DATASET_HASH,
            "canonical_match_ids": sorted(
                str(row["canonical_match_id"]) for row in fixture_rows
            ),
        }
    )


def _membership(
    *,
    fixture: dict[str, object],
    rule_hash: str,
    hypothesis_id: str,
    membership_set_hash: str,
    occurrence_index: int,
    cumulative_profit: float,
) -> dict[str, object]:
    won = int(str(fixture["fixture_id"])) % 2 == 0
    odds = 2.0
    profit = 1.0 if won else -1.0
    membership: dict[str, object] = {
        "schema_version": "hypothesis-fixture-membership-v1",
        "dataset_hash": DATASET_HASH,
        "campaign_result_hash": CAMPAIGN_HASH,
        "registry_sha256": REGISTRY_HASH,
        "historical_data_revision": HISTORICAL_REVISION,
        "hypothesis_id": hypothesis_id,
        "hypothesis_version": "1.0.0",
        "rule_hash": rule_hash,
        "canonical_match_id": fixture["canonical_match_id"],
        "market": "MATCH_RESULT",
        "selection": "HOME",
        "price_class": "CLOSING",
        "observed_time_status": fixture["observed_time_status"],
        "observed_odds": odds,
        "market_margin": 0.05,
        "stake_units": 1.0,
        "won": won,
        "lost": not won,
        "void": False,
        "gross_return_units": odds if won else 0.0,
        "profit_units": profit,
        "cumulative_profit_units": cumulative_profit,
        "occurrence_index": occurrence_index,
        "chronological_fold": "SEASON:2024",
        "statistical_group": fixture["match_date"],
        "eligibility_status": "ELIGIBLE_SETTLED",
        "eligibility_reason": (
            "ALL_CONDITIONS_MATCH;OBSERVED_ODDS_ELIGIBLE;OUTCOME_SETTLED"
        ),
    }
    return {
        **membership,
        "membership_hash": _canonical_sha256(
            {
                **membership,
                "source_row_hash": fixture["source_row_hash"],
                "membership_set_hash": membership_set_hash,
            }
        ),
    }


def _summary(
    *,
    fixture_rows: list[dict[str, object]],
    membership_rows: list[dict[str, object]],
    rule_hash: str,
    hypothesis_id: str,
) -> dict[str, object]:
    wins = sum(row["won"] is True for row in membership_rows)
    losses = sum(row["lost"] is True for row in membership_rows)
    voids = sum(row["void"] is True for row in membership_rows)
    odds = [float(row["observed_odds"]) for row in membership_rows]
    profit = sum(float(row["profit_units"]) for row in membership_rows)
    conditions = [
        {
            "available_at": "FIXTURE_PUBLICATION",
            "feature": "competition",
            "operator": "EQ",
            "source": "API_FOOTBALL_FIXTURE",
            "value": "Test League",
        }
    ]
    row: dict[str, object] = {
        "dataset_hash": DATASET_HASH,
        "campaign_result_hash": CAMPAIGN_HASH,
        "registry_sha256": REGISTRY_HASH,
        "historical_data_revision": HISTORICAL_REVISION,
        "hypothesis_id": hypothesis_id,
        "rule_hash": rule_hash,
        "membership_set_hash": _membership_set_hash(fixture_rows),
        "market": "MATCH_RESULT",
        "selection": "HOME",
        "family": "MARKET",
        "competition_scope": "Test League",
        "conditions_json": json.dumps(
            conditions,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "occurrences": len(membership_rows),
        "settled_occurrences": len(membership_rows),
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "hit_rate": wins / len(membership_rows),
        "average_odds": sum(odds) / len(odds),
        "median_odds": 2.0,
        "total_staked_units": float(len(membership_rows)),
        "gross_returns_units": sum(
            float(row["gross_return_units"]) for row in membership_rows
        ),
        "profit_units": profit,
        "roi": profit / len(membership_rows),
        "maximum_drawdown_units": 1.0,
        "longest_losing_streak": 1,
        "eligible_folds": 1,
        "positive_folds": 1,
        "walk_forward_survived": True,
        "p_value": 0.1,
        "q_value": 0.2,
        "support_sufficient": True,
        "hypothesis_status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
        "evidence_scope": "FROZEN_HISTORICAL_EXPLORATION",
        "reconciled": True,
    }
    row["summary_hash"] = _canonical_sha256(row)
    return row


def _rule_rows(
    fixture_rows: list[dict[str, object]],
    *,
    rule_hash: str,
    hypothesis_id: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    membership_set_hash = _membership_set_hash(fixture_rows)
    memberships: list[dict[str, object]] = []
    cumulative = 0.0
    for index, fixture in enumerate(fixture_rows, start=1):
        won = int(str(fixture["fixture_id"])) % 2 == 0
        cumulative += 1.0 if won else -1.0
        memberships.append(
            _membership(
                fixture=fixture,
                rule_hash=rule_hash,
                hypothesis_id=hypothesis_id,
                membership_set_hash=membership_set_hash,
                occurrence_index=index,
                cumulative_profit=cumulative,
            )
        )
    return memberships, _summary(
        fixture_rows=fixture_rows,
        membership_rows=memberships,
        rule_hash=rule_hash,
        hypothesis_id=hypothesis_id,
    )


RANKING_METRICS = {
    "by_roi": ("roi", True),
    "by_profit": ("profit_units", True),
    "by_support": ("occurrences", True),
    "by_hit_rate": ("hit_rate", True),
    "by_lowest_drawdown": ("maximum_drawdown_units", False),
}


def _top_item(summary: dict[str, object]) -> dict[str, object]:
    return {
        "hypothesis_id": summary["hypothesis_id"],
        "rule_hash": summary["rule_hash"],
        "membership_set_hash": summary["membership_set_hash"],
        "competition": summary["competition_scope"],
        "family": summary["family"],
        **{
            metric: summary[metric]
            for metric, _ in RANKING_METRICS.values()
        },
    }


def _ranking_bucket(
    items: list[dict[str, object]],
    metric: str,
    descending: bool,
) -> dict[str, object]:
    ranked = sorted(
        items,
        key=lambda item: (
            -float(item[metric])
            if descending
            else float(item[metric]),
            str(item["rule_hash"]),
        ),
    )
    return {
        "requested_limit": 10,
        "available_count": len(ranked),
        "complete": len(ranked) >= 10,
        "ordering": [
            f"{metric.upper()}_{'DESC' if descending else 'ASC'}",
            "RULE_HASH_ASC",
        ],
        "duplicate_membership_sets_removed": 0,
        "items": ranked,
    }


def _ranking_scope(
    items: list[dict[str, object]],
) -> dict[str, object]:
    return {
        name: _ranking_bucket(items, metric, descending)
        for name, (metric, descending) in RANKING_METRICS.items()
    }


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _write_synthetic_inputs(
    root: Path,
    *,
    fixture_count: int = 3,
    include_second_rule: bool = True,
    include_cross_scope_rule: bool = False,
    include_unpublished_rule: bool = False,
    legacy_top_shape: bool = False,
) -> tuple[Path, Path, dict[str, list[dict[str, object]]]]:
    artifact_root = root / "evidence"
    fixture_rows = [_fixture(index) for index in range(fixture_count)]
    membership_one, summary_one = _rule_rows(
        fixture_rows,
        rule_hash=RULE_ONE,
        hypothesis_id="J10-TEST-001",
    )
    memberships = list(membership_one)
    summaries = [summary_one]
    top_items: list[dict[str, object]] = [_top_item(summary_one)]
    rows_by_rule = {RULE_ONE: membership_one}
    if include_second_rule:
        second_fixtures = fixture_rows[1:]
        membership_two, summary_two = _rule_rows(
            second_fixtures,
            rule_hash=RULE_TWO,
            hypothesis_id="J10-TEST-002",
        )
        memberships.extend(membership_two)
        summaries.append(summary_two)
        rows_by_rule[RULE_TWO] = membership_two
        top_items.append(_top_item(summary_two))
    cross_scope_item: dict[str, object] | None = None
    if include_cross_scope_rule:
        membership_three, summary_three = _rule_rows(
            fixture_rows[:1],
            rule_hash=RULE_THREE,
            hypothesis_id="J10-TEST-003",
        )
        memberships.extend(membership_three)
        summaries.append(summary_three)
        rows_by_rule[RULE_THREE] = membership_three
        cross_scope_item = _top_item(summary_three)
    if include_unpublished_rule:
        membership_hidden, summary_hidden = _rule_rows(
            fixture_rows[1:2],
            rule_hash=RULE_HIDDEN,
            hypothesis_id="J10-TEST-HIDDEN",
        )
        memberships.extend(membership_hidden)
        summaries.append(summary_hidden)
        rows_by_rule[RULE_HIDDEN] = membership_hidden

    _write_parquet(
        artifact_root / "historical_fixture_evidence.parquet",
        fixture_rows,
    )
    _write_parquet(
        artifact_root / "hypothesis_fixture_membership.parquet",
        memberships,
    )
    _write_parquet(
        artifact_root / "hypothesis_historical_evidence_summary.parquet",
        summaries,
    )
    global_payload: dict[str, object]
    if legacy_top_shape:
        global_payload = {"items": top_items}
    else:
        global_payload = _ranking_scope(top_items)
        if cross_scope_item is not None:
            metric, descending = RANKING_METRICS["by_profit"]
            global_payload["by_profit"] = _ranking_bucket(
                [*top_items, cross_scope_item],
                metric,
                descending,
            )
    report = {
        "schema_version": "j10-historical-evidence-top-10-v1",
        "source_result_hash": CAMPAIGN_HASH,
        "dataset_hash": DATASET_HASH,
        "selection_contract": {
            "support_sufficient": True,
            "campaign_status": "DISCOVERED",
            "walk_forward_survived": True,
            "deduplication": "UNIQUE_MEMBERSHIP_SET_HASH",
            "public_status": (
                "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
            ),
            "rankings": {
                name: {
                    "metric": metric,
                    "direction": "DESC" if descending else "ASC",
                    "tie_break": "RULE_HASH_ASC",
                }
                for name, (metric, descending) in RANKING_METRICS.items()
            },
            "validated_label_forbidden": True,
        },
        "global": global_payload,
    }
    if cross_scope_item is not None:
        report["by_competition"] = {
            "Test League": _ranking_scope([cross_scope_item])
        }
    report_path = root / "top-10.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_root, report_path, rows_by_rule


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_builds_deterministic_bounded_pages_and_bidirectional_match_links(
    tmp_path: Path,
) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(tmp_path)
    membership_columns = set(
        pq.ParquetFile(
            artifact_root / "hypothesis_fixture_membership.parquet"
        ).schema_arrow.names
    )
    assert {
        "fixture_id",
        "fixture_record_hash",
        "competition",
        "season",
        "match_date",
        "kickoff_at",
        "home_team_id",
        "away_team_id",
        "membership_set_hash",
        "fold_key",
        "group_key",
        "evidence_scope",
        "hypothesis_status",
        "source",
    }.isdisjoint(membership_columns)
    first_output = tmp_path / "site-a"
    second_output = tmp_path / "site-b"

    first = build_hypothesis_evidence_site_pages(
        artifact_root,
        report_path,
        first_output,
    )
    second = build_hypothesis_evidence_site_pages(
        artifact_root,
        report_path,
        second_output,
    )

    assert first.hypothesis_count == 2
    assert first.selected_membership_count == 5
    assert first.unique_match_count == 3
    assert first.content_tree_sha256 == second.content_tree_sha256
    assert {
        path.relative_to(first_output).as_posix()
        for path in first_output.rglob("*.json")
    } == {
        path.relative_to(second_output).as_posix()
        for path in second_output.rglob("*.json")
    }

    index = _read_json(first_output / "index.json")
    assert index["ranking_source"] == (
        "top-10.all-ranking-scopes.items-union"
    )
    assert index["preview_scope"] == "RANKING_TOP_TEN_UNION"
    assert index["maximum_hypotheses"] == 2
    assert [item["rank"] for item in index["hypotheses"]] == [1, 2]
    assert index["evidence_availability"] == {
        "historical": True,
        "prospective": False,
    }
    summary = _read_json(
        first_output / "hypotheses" / "J10-TEST-001" / "summary.json"
    )
    assert summary["evidence_availability"]["historical"]["available"] is True
    assert summary["evidence_availability"]["prospective"]["available"] is False
    assert summary["conditions"][0]["feature"] == "competition"
    assert summary["analysis_ref"] == (
        "hypotheses/J10-TEST-001/analysis.json"
    )
    assert summary["query_index_ref"] == (
        "hypotheses/J10-TEST-001/query-index.json"
    )
    analysis_path = (
        first_output / "hypotheses" / "J10-TEST-001" / "analysis.json"
    )
    analysis = _read_json(analysis_path)
    assert analysis["schema_version"] == "hypothesis-evidence-analysis-v1"
    assert analysis["prospective_evidence_included"] is False
    assert [
        point["cumulative_profit_units"]
        for point in analysis["bankroll_points"]
    ] == [1.0, 0.0, 1.0]
    assert len(
        {
            point["canonical_match_id"]
            for point in analysis["bankroll_points"]
        }
    ) == 3
    assert [
        point["match_label"] for point in analysis["bankroll_points"]
    ] == [
        "Home 0 – Away 0",
        "Home 1 – Away 1",
        "Home 2 – Away 2",
    ]
    assert all(
        "api-football:" not in str(point["match_label"])
        for point in analysis["bankroll_points"]
    )
    assert analysis["seasons"] == [
        {
            "losses": 1,
            "occurrences": 3,
            "profit_units": 1.0,
            "reference_match": {
                "canonical_match_id": "api-football:10000",
                "match_date": "2024-01-01",
                "match_detail_ref": _safe_match_path(
                    "api-football:10000"
                ),
                "match_label": "Home 0 – Away 0",
            },
            "roi": 0.333333333333,
            "season": 2024,
            "total_staked_units": 3.0,
            "voids": 0,
            "wins": 2,
        }
    ]
    populated_band = next(
        band
        for band in analysis["odds_bands"]
        if band["band_id"] == "FROM_2_00_TO_2_99"
    )
    assert populated_band["occurrences"] == 3
    assert populated_band["wins"] == 2
    assert populated_band["profit_units"] == 1.0
    assert analysis["folds"][0]["fold"] == "SEASON:2024"
    assert analysis["folds"][0]["roi"] == 0.333333333333
    assert (
        analysis["team_concentration"][
            "denominator_team_appearances"
        ]
        == 6
    )
    assert len(analysis["team_concentration"]["items"]) == 6
    assert analysis["team_concentration"]["items"][0] == {
        "away_occurrences": 1,
        "home_occurrences": 0,
        "losses": 0,
        "occurrences": 1,
        "profit_units": 1.0,
        "rank": 1,
        "reference_match": {
            "canonical_match_id": "api-football:10000",
            "match_date": "2024-01-01",
                "match_detail_ref": _safe_match_path(
                    "api-football:10000"
                ),
                "match_label": "Home 0 – Away 0",
            },
        "share_of_team_appearances": 0.166666666667,
        "team_id": "20001",
        "team_name": "Away 0",
        "voids": 0,
        "wins": 1,
    }
    assert analysis["streaks"]["winning"]["current_length"] == 1
    assert analysis["streaks"]["winning"]["longest_length"] == 1
    assert analysis["streaks"]["winning"]["run_count"] == 2
    assert analysis["streaks"]["winning"]["current_run"][
        "end_match"
    ]["canonical_match_id"] == "api-football:10002"
    assert analysis["streaks"]["winning"]["current_run"][
        "end_match"
    ]["match_label"] == "Home 2 – Away 2"
    assert analysis["streaks"]["losing"]["current_length"] == 0
    assert analysis["streaks"]["losing"]["longest_length"] == 1
    assert analysis["streaks"]["losing"]["run_count"] == 1
    assert analysis["streaks"]["losing"]["current_run"] is None
    assert analysis_path.stat().st_size <= ANALYSIS_MAX_BYTES

    query_index_path = (
        first_output
        / "hypotheses"
        / "J10-TEST-001"
        / "query-index.json"
    )
    query_index = _read_json(query_index_path)
    assert query_index["schema_version"] == (
        "hypothesis-evidence-query-index-v1"
    )
    assert query_index["intended_consumer"] == "SERVER_RENDERED_MATCH_LIST"
    assert query_index["transport"] == "PUBLIC_SAME_ORIGIN_STATIC_ASSET"
    assert query_index["maximum_items"] == QUERY_INDEX_MAX_ITEMS
    assert query_index["total_items"] == 3
    assert query_index["supported_page_sizes"] == [25, 50]
    assert query_index["supported_filters"] == [
        "chronological_fold",
        "observed_odds",
        "outcome",
        "season",
        "selection",
        "team",
    ]
    assert query_index["supported_sorts"] == [
        "kickoff_at",
        "observed_odds",
        "outcome",
        "profit_units",
    ]
    assert [
        item["occurrence_index"] for item in query_index["items"]
    ] == [1, 2, 3]
    assert len(
        {
            item["canonical_match_id"]
            for item in query_index["items"]
        }
    ) == 3
    assert query_index["items"][0] == {
        "away_team": {"id": "20001", "name": "Away 0"},
        "canonical_match_id": "api-football:10000",
        "chronological_fold": "SEASON:2024",
        "competition": "Test League",
        "competition_key": "TEST_LEAGUE",
        "cumulative_profit_units": 1.0,
        "final_score": {"away": 1, "home": 2},
        "final_status": "FT",
        "home_team": {"id": "20000", "name": "Home 0"},
        "kickoff_at": "2024-01-01T15:00:00+00:00",
        "match_date": "2024-01-01",
        "match_detail_ref": _safe_match_path("api-football:10000"),
        "market": "MATCH_RESULT",
        "market_margin": 0.05,
        "observed_odds": 2.0,
        "occurrence_index": 1,
        "outcome": "won",
        "profit_units": 1.0,
        "round": "Round 1",
        "season": 2024,
        "selection": "HOME",
    }
    assert query_index["provenance"]["provider_payloads_copied"] is False
    assert query_index_path.stat().st_size <= QUERY_INDEX_MAX_BYTES

    page_25 = _read_json(
        first_output
        / "hypotheses"
        / "J10-TEST-001"
        / "memberships"
        / "25"
        / "page-0001.json"
    )
    page_50 = _read_json(
        first_output
        / "hypotheses"
        / "J10-TEST-001"
        / "memberships"
        / "50"
        / "page-0001.json"
    )
    assert page_25["total_items"] == page_50["total_items"] == 3
    assert page_25["items"][0]["evidence_kind"] == "HISTORICAL"
    assert (
        page_25["items"][0]["reason"]["per_condition_evaluation_in_source"]
        is False
    )
    assert page_25["items"][0]["reason"]["eligibility_codes"] == [
        "ALL_CONDITIONS_MATCH",
        "OBSERVED_ODDS_ELIGIBLE",
        "OUTCOME_SETTLED",
    ]
    assert (
        first_output
        / "hypotheses"
        / "J10-TEST-001"
        / "memberships"
        / "25"
        / "page-0001.json"
    ).stat().st_size <= MEMBERSHIP_PAGE_MAX_BYTES
    assert (
        first_output / "hypotheses" / "J10-TEST-001" / "summary.json"
    ).stat().st_size <= SUMMARY_MAX_BYTES

    shared_match_id = "api-football:10001"
    detail = _read_json(
        first_output.joinpath(*Path(_safe_match_path(shared_match_id)).parts)
    )
    assert detail["canonical_match_id"] == shared_match_id
    assert detail["prospective_evidence_included"] is False
    assert detail["total_historical_rules"] == 2
    assert [item["hypothesis_id"] for item in detail["top_ten_hypotheses"]] == [
        "J10-TEST-001",
        "J10-TEST-002",
    ]
    assert all(
        len(item["membership_page_refs"]) == 2
        for item in detail["top_ten_hypotheses"]
    )
    assert (
        first_output.joinpath(*Path(_safe_match_path(shared_match_id)).parts)
        .stat()
        .st_size
        <= MATCH_DETAIL_MAX_BYTES
    )

    manifest = _read_json(first_output / "manifest.json")
    assert manifest["publication_scope"] == "TEMPORARY_PREVIEW_NOT_FOR_GIT"
    assert manifest["evidence"]["provider_payloads_copied"] is False
    assert manifest["evidence"]["analysis_max_bytes"] == ANALYSIS_MAX_BYTES
    assert (
        manifest["evidence"]["match_detail_max_bytes"]
        == MATCH_DETAIL_MAX_BYTES
    )
    assert manifest["evidence"]["membership_page_max_bytes"] == (
        MEMBERSHIP_PAGE_MAX_BYTES
    )
    assert manifest["evidence"]["query_index_max_bytes"] == (
        QUERY_INDEX_MAX_BYTES
    )
    assert manifest["evidence"]["query_index_intended_consumer"] == (
        "SERVER_RENDERED_MATCH_LIST"
    )
    assert manifest["evidence"]["query_index_transport"] == (
        "PUBLIC_SAME_ORIGIN_STATIC_ASSET"
    )
    assert manifest["evidence"]["summary_max_bytes"] == SUMMARY_MAX_BYTES
    assert manifest["evidence"]["selected_membership_rows"] == 5
    assert manifest["evidence"]["unique_match_rows"] == 3
    assert all(
        len(item["sha256"]) == 64 and item["row_count"] >= 0
        for item in manifest["outputs"]
    )
    query_entry = next(
        item
        for item in manifest["outputs"]
        if item["path"] == "hypotheses/J10-TEST-001/query-index.json"
    )
    assert query_entry["record_kind"] == (
        "HYPOTHESIS_MEMBERSHIP_QUERY_INDEX"
    )
    assert query_entry["row_count"] == 3
    assert query_entry["sha256"] == hashlib.sha256(
        query_index_path.read_bytes()
    ).hexdigest()
    serialized = "\n".join(
        path.read_text("utf-8") for path in first_output.rglob("*.json")
    )
    assert "raw_payload" not in serialized


def test_publishes_the_deduplicated_union_of_every_ranking_scope(
    tmp_path: Path,
) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(
        tmp_path,
        include_cross_scope_rule=True,
    )
    output = tmp_path / "site"

    result = build_hypothesis_evidence_site_pages(
        artifact_root,
        report_path,
        output,
    )

    assert result.hypothesis_count == 3
    index = _read_json(output / "index.json")
    assert index["ranking_source"] == (
        "top-10.all-ranking-scopes.items-union"
    )
    assert index["maximum_hypotheses"] == 3
    assert {
        item["hypothesis_id"] for item in index["hypotheses"]
    } == {
        "J10-TEST-001",
        "J10-TEST-002",
        "J10-TEST-003",
    }
    assert len(index["hypotheses"]) == len(
        {item["rule_hash"] for item in index["hypotheses"]}
    )
    assert (
        output / "hypotheses" / "J10-TEST-003" / "summary.json"
    ).is_file()
    ranks = {
        item["hypothesis_id"]: item["rank"]
        for item in index["hypotheses"]
    }
    assert ranks == {
        "J10-TEST-001": 1,
        "J10-TEST-002": 2,
        "J10-TEST-003": None,
    }


def test_match_detail_reports_all_historical_rules_but_bounds_relations(
    tmp_path: Path,
) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(
        tmp_path,
        include_unpublished_rule=True,
    )
    output = tmp_path / "site"

    build_hypothesis_evidence_site_pages(
        artifact_root,
        report_path,
        output,
    )

    shared_match_id = "api-football:10001"
    detail = _read_json(
        output.joinpath(*Path(_safe_match_path(shared_match_id)).parts)
    )
    assert detail["total_historical_rules"] == 3
    assert len(detail["top_ten_hypotheses"]) == 2
    assert {
        item["hypothesis_id"] for item in detail["top_ten_hypotheses"]
    } == {"J10-TEST-001", "J10-TEST-002"}
    match_index = _read_json(output / "matches" / "index.json")
    match_item = next(
        item
        for item in match_index["items"]
        if item["canonical_match_id"] == shared_match_id
    )
    assert match_item["hypothesis_count"] == 3
    assert match_item["published_hypothesis_count"] == 2


def test_paginates_25_and_50_without_changing_source_order(tmp_path: Path) -> None:
    artifact_root, report_path, rows_by_rule = _write_synthetic_inputs(
        tmp_path,
        fixture_count=51,
        include_second_rule=False,
    )
    output = tmp_path / "site"

    result = build_hypothesis_evidence_site_pages(
        artifact_root,
        report_path,
        output,
    )

    assert result.selected_membership_count == 51
    summary = _read_json(
        output / "hypotheses" / "J10-TEST-001" / "summary.json"
    )
    assert summary["membership_pages"]["25"]["total_pages"] == 3
    assert summary["membership_pages"]["50"]["total_pages"] == 2
    analysis_path = (
        output / "hypotheses" / "J10-TEST-001" / "analysis.json"
    )
    analysis = _read_json(analysis_path)
    assert len(analysis["bankroll_points"]) == 51
    assert analysis_path.stat().st_size <= ANALYSIS_MAX_BYTES
    query_index_path = (
        output / "hypotheses" / "J10-TEST-001" / "query-index.json"
    )
    query_index = _read_json(query_index_path)
    assert query_index["total_items"] == 51
    assert query_index["items"][-1]["occurrence_index"] == 51
    assert query_index_path.stat().st_size <= QUERY_INDEX_MAX_BYTES
    page_25_3 = _read_json(
        output
        / "hypotheses"
        / "J10-TEST-001"
        / "memberships"
        / "25"
        / "page-0003.json"
    )
    page_50_2 = _read_json(
        output
        / "hypotheses"
        / "J10-TEST-001"
        / "memberships"
        / "50"
        / "page-0002.json"
    )
    expected_last = rows_by_rule[RULE_ONE][-1]["canonical_match_id"]
    assert page_25_3["items"][0]["canonical_match_id"] == expected_last
    assert page_50_2["items"][0]["canonical_match_id"] == expected_last


def test_accepts_only_the_fail_closed_legacy_global_items_fallback(
    tmp_path: Path,
) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(
        tmp_path,
        legacy_top_shape=True,
    )
    output = tmp_path / "site"

    build_hypothesis_evidence_site_pages(artifact_root, report_path, output)

    index = _read_json(output / "index.json")
    assert index["ranking_source"] == "global.items"
    assert len(index["hypotheses"]) == 2


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("membership_hash", "MEMBERSHIP_HASH_MISMATCH"),
        ("membership_primary_key", "MEMBERSHIP_PRIMARY_KEY_DUPLICATE"),
        ("fixture_relation", "MEMBERSHIP_FIXTURE_ORPHAN"),
        ("fixture_source_hash", "FIXTURE_SOURCE_ROW_HASH_MISMATCH"),
        ("top_relation", "TOP_TEN_MEMBERSHIP_SET_INVALID"),
    ],
)
def test_rejects_invalid_hashes_primary_keys_and_relations_without_partial_publish(
    tmp_path: Path,
    corruption: str,
    expected_error: str,
) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(tmp_path)
    membership_path = artifact_root / "hypothesis_fixture_membership.parquet"
    rows = pq.read_table(membership_path).to_pylist()
    if corruption == "fixture_source_hash":
        fixture_path = (
            artifact_root / "historical_fixture_evidence.parquet"
        )
        fixture_rows = pq.read_table(fixture_path).to_pylist()
        fixture_rows[0]["home_team_name"] = "Tampered team"
        fixture_rows[0]["home_source_name"] = "Tampered team"
        _write_parquet(fixture_path, fixture_rows)
    elif corruption == "membership_hash":
        rows[0]["membership_hash"] = "e" * 64
        _write_parquet(membership_path, rows)
    elif corruption == "membership_primary_key":
        rows.append(dict(rows[0]))
        _write_parquet(membership_path, rows)
    elif corruption == "fixture_relation":
        rows[0]["canonical_match_id"] = "api-football:missing"
        _write_parquet(membership_path, rows)
    else:
        report = _read_json(report_path)
        report["global"]["by_roi"]["items"][0]["membership_set_hash"] = "f" * 64
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "preexisting.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(SitePageBuildError, match=expected_error):
        build_hypothesis_evidence_site_pages(
            artifact_root,
            report_path,
            output,
        )

    assert sentinel.read_text("utf-8") == "keep"
    assert not (output / "manifest.json").exists()


def test_validates_optional_input_artifact_manifest_hashes(tmp_path: Path) -> None:
    artifact_root, report_path, _ = _write_synthetic_inputs(tmp_path)
    entries = []
    for path in sorted(artifact_root.glob("*.parquet")):
        entries.append(
            {
                "name": path.name,
                "rows": pq.ParquetFile(path).metadata.num_rows,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    entries[0]["sha256"] = "0" * 64
    (artifact_root / "artifact-manifest.json").write_text(
        json.dumps({"artifacts": entries}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SitePageBuildError,
        match="ARTIFACT_MANIFEST_HASH_MISMATCH",
    ):
        build_hypothesis_evidence_site_pages(
            artifact_root,
            report_path,
            tmp_path / "site",
        )
