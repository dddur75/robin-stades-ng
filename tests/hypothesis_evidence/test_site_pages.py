from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.build_hypothesis_evidence_site_pages import (
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


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(index: int) -> dict[str, object]:
    fixture_id = str(10_000 + index)
    record_hash = _sha(f"fixture-record:{fixture_id}")
    match_date = f"2024-01-{index + 1:02d}"
    kickoff_at = f"{match_date}T15:00:00+00:00"
    return {
        "dataset_hash": DATASET_HASH,
        "source_dataset_hash": DATASET_HASH,
        "record_hash": record_hash,
        "source_row_hash": record_hash,
        "canonical_match_id": f"api-football:{fixture_id}",
        "fixture_id": fixture_id,
        "competition_key": "TEST_LEAGUE",
        "competition_name": "Test League",
        "competition": "Test League",
        "season": 2024,
        "round": f"Round {index + 1}",
        "final_status": "FT",
        "match_date": match_date,
        "kickoff_at": kickoff_at,
        "home_team_id": f"H{index}",
        "away_team_id": f"A{index}",
        "home_team_name": f"Home {index}",
        "away_team_name": f"Away {index}",
        "home_goals": 2 if index % 2 == 0 else 0,
        "away_goals": 1,
        "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
        "source": "SYNTHETIC_NORMALIZED_FIXTURE",
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
            "property": "competition",
            "operator": "EQ",
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


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _write_synthetic_inputs(
    root: Path,
    *,
    fixture_count: int = 3,
    include_second_rule: bool = True,
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
    top_items: list[dict[str, object]] = [
        {
            "hypothesis_id": "J10-TEST-001",
            "rule_hash": RULE_ONE,
            "membership_set_hash": summary_one["membership_set_hash"],
        }
    ]
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
        top_items.append(
            {
                "hypothesis_id": "J10-TEST-002",
                "rule_hash": RULE_TWO,
                "membership_set_hash": summary_two["membership_set_hash"],
            }
        )

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
        global_payload = {"by_roi": {"items": top_items}}
    report = {
        "schema_version": "j10-historical-evidence-top-10-v1",
        "source_result_hash": CAMPAIGN_HASH,
        "dataset_hash": DATASET_HASH,
        "global": global_payload,
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
    assert index["ranking_source"] == "global.by_roi.items"
    assert index["evidence_availability"] == {
        "historical": True,
        "prospective": False,
    }
    summary = _read_json(
        first_output / "hypotheses" / "J10-TEST-001" / "summary.json"
    )
    assert summary["evidence_availability"]["historical"]["available"] is True
    assert summary["evidence_availability"]["prospective"]["available"] is False
    assert summary["conditions"][0]["property"] == "competition"

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

    shared_match_id = "api-football:10001"
    detail = _read_json(
        first_output.joinpath(*Path(_safe_match_path(shared_match_id)).parts)
    )
    assert detail["canonical_match_id"] == shared_match_id
    assert detail["prospective_evidence_included"] is False
    assert [item["hypothesis_id"] for item in detail["top_ten_hypotheses"]] == [
        "J10-TEST-001",
        "J10-TEST-002",
    ]
    assert all(
        len(item["membership_page_refs"]) == 2
        for item in detail["top_ten_hypotheses"]
    )

    manifest = _read_json(first_output / "manifest.json")
    assert manifest["publication_scope"] == "TEMPORARY_PREVIEW_NOT_FOR_GIT"
    assert manifest["evidence"]["provider_payloads_copied"] is False
    assert manifest["evidence"]["selected_membership_rows"] == 5
    assert manifest["evidence"]["unique_match_rows"] == 3
    assert all(
        len(item["sha256"]) == 64 and item["row_count"] >= 0
        for item in manifest["outputs"]
    )
    serialized = "\n".join(
        path.read_text("utf-8") for path in first_output.rglob("*.json")
    )
    assert "raw_payload" not in serialized


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
    if corruption == "membership_hash":
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
