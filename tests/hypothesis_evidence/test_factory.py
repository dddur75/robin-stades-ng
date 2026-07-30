from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from robin.hypothesis_evidence.contracts import (
    CAMPAIGN_RESULT_HASH,
    DATASET_HASH,
    EXPECTED_FIXTURES,
    EXPECTED_RAW_MEMBERSHIPS,
    EXPECTED_RAW_STRICT_DELTA,
    EXPECTED_RULES,
    EXPECTED_STRICT_MEMBERSHIPS,
    REGISTRY_SHA256,
    EvidenceBuildConfig,
    EvidenceFactoryError,
    sha256_file,
)
from robin.hypothesis_evidence.factory import build_hypothesis_evidence
from robin.hypothesis_evidence.source import load_frozen_historical_market

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / ".ci" / "hypothesis-j10" / "hypothesis-registry.jsonl"
FULL_CAMPAIGN = ROOT / ".ci" / "hypothesis-j10" / "campaign-summary.json"
COMPACT_CAMPAIGN = ROOT / "reports" / "pattern-research" / "campaign-summary.json"
EXTRACTED = ROOT / "artifacts" / "j10-frozen-reference" / "historical"
RUNTIME_INPUTS = REGISTRY.is_file() and FULL_CAMPAIGN.is_file()

pytestmark = pytest.mark.skipif(
    not RUNTIME_INPUTS,
    reason="frozen runtime-only J10 registry/campaign cache unavailable",
)


def config(
    *,
    output: Path,
    reports: Path,
    historical_root: Path | None = EXTRACTED if EXTRACTED.is_dir() else None,
    registry: Path = REGISTRY,
    stop_after_batches: int | None = None,
) -> EvidenceBuildConfig:
    return EvidenceBuildConfig(
        repo_root=ROOT,
        historical_root=historical_root,
        output_root=output,
        report_root=reports,
        registry_path=registry,
        full_campaign_path=FULL_CAMPAIGN,
        compact_campaign_path=COMPACT_CAMPAIGN,
        batch_size=50,
        stop_after_batches=stop_after_batches,
    )


@dataclass(frozen=True)
class BuiltEvidence:
    output: Path
    reports: Path
    replay_hash: str
    artifact_hashes: dict[str, str]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> BuiltEvidence:
    root = tmp_path_factory.mktemp("j10-evidence")
    output = root / "artifacts"
    reports = root / "reports"
    interrupted = build_hypothesis_evidence(
        config(
            output=output,
            reports=reports,
            stop_after_batches=2,
        )
    )
    assert interrupted.status == "INTERRUPTED_RESUMABLE"
    assert interrupted.completed_batches == 2
    assert not (output / "hypothesis_fixture_membership.parquet").exists()

    completed = build_hypothesis_evidence(
        config(output=output, reports=reports)
    )
    assert completed.status == "COMPLETE"
    assert completed.replay_hash is not None
    paths = sorted(output.glob("*.parquet"))
    hashes = {path.name: sha256_file(path) for path in paths}

    replayed = build_hypothesis_evidence(
        config(output=output, reports=reports)
    )
    assert replayed.status == "COMPLETE"
    assert replayed.replay_hash == completed.replay_hash
    assert {path.name: sha256_file(path) for path in paths} == hashes
    return BuiltEvidence(
        output=output,
        reports=reports,
        replay_hash=completed.replay_hash,
        artifact_hashes=hashes,
    )


def test_source_golden_and_logical_pin() -> None:
    historical = load_frozen_historical_market(
        ROOT,
        historical_root=EXTRACTED if EXTRACTED.is_dir() else None,
    )
    assert historical.dataset_hash == DATASET_HASH
    assert len(historical.partitions) == 30
    assert len(historical.rows) == EXPECTED_FIXTURES
    assert len({str(row["fixture_id"]) for row in historical.rows}) == EXPECTED_FIXTURES
    assert all(row["source"] == "FOOTBALL_DATA" for row in historical.rows)
    assert all(
        row["observed_time_status"] == "SOURCE_PRICE_CLASS_ONLY"
        for row in historical.rows
    )


def test_extracted_cache_and_pinned_git_blobs_are_identical() -> None:
    if not EXTRACTED.is_dir():
        pytest.skip("extracted frozen cache unavailable")
    extracted = load_frozen_historical_market(
        ROOT,
        historical_root=EXTRACTED,
    )
    blobs = load_frozen_historical_market(ROOT, historical_root=None)
    assert extracted.dataset_hash == blobs.dataset_hash == DATASET_HASH
    assert extracted.partitions == blobs.partitions
    assert extracted.rows == blobs.rows


def test_all_three_normalized_tables_and_memberships(
    built: BuiltEvidence,
) -> None:
    fixtures = pq.read_table(
        built.output / "historical_fixture_evidence.parquet"
    ).to_pandas()
    memberships = pq.read_table(
        built.output / "hypothesis_fixture_membership.parquet"
    ).to_pandas()
    summaries = pq.read_table(
        built.output / "hypothesis_historical_evidence_summary.parquet"
    ).to_pandas()

    assert len(fixtures) == EXPECTED_FIXTURES
    assert fixtures["canonical_match_id"].nunique() == EXPECTED_FIXTURES
    assert fixtures["source_dataset_hash"].eq(DATASET_HASH).all()
    assert fixtures["final_status"].eq("RESULT_RECORDED").all()
    assert fixtures["home_team_name"].notna().all()
    assert fixtures["away_team_name"].notna().all()

    assert len(memberships) == EXPECTED_STRICT_MEMBERSHIPS
    assert not memberships.duplicated(
        ["rule_hash", "canonical_match_id"]
    ).any()
    assert memberships["membership_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert memberships["eligibility_status"].eq("ELIGIBLE_SETTLED").all()
    assert memberships["void"].eq(False).all()  # noqa: E712
    assert memberships["won"].ne(memberships["lost"]).all()

    assert len(summaries) == EXPECTED_RULES
    assert summaries["rule_hash"].nunique() == EXPECTED_RULES
    assert summaries["reconciled"].all()
    assert summaries["family"].eq("MARKET").all()
    assert summaries["hypothesis_status"].isin(
        {
            "DATA_GATE_BLOCKED",
            "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
        }
    ).all()
    assert int(summaries["raw_occurrences"].sum()) == EXPECTED_RAW_MEMBERSHIPS
    assert int(summaries["occurrences"].sum()) == EXPECTED_STRICT_MEMBERSHIPS
    assert (
        int(
            (
                summaries["raw_occurrences"] - summaries["occurrences"]
            ).sum()
        )
        == EXPECTED_RAW_STRICT_DELTA
    )


@pytest.mark.parametrize(
    (
        "hypothesis_id",
        "occurrences",
        "wins",
        "losses",
        "profit",
        "roi",
        "median_odds",
        "losing_streak",
        "groups",
        "folds",
    ),
    [
        (
            "J10-M001",
            261,
            135,
            126,
            43.43,
            0.1663984674329502,
            2.23,
            6,
            225,
            4,
        ),
        (
            "J10-M002",
            363,
            136,
            227,
            57.88,
            0.1594490358126722,
            3.11,
            15,
            282,
            4,
        ),
        (
            "J10-M003",
            241,
            154,
            87,
            33.42,
            0.1386721991701245,
            1.77,
            4,
            207,
            3,
        ),
    ],
)
def test_top_three_exact_reconciliation(
    built: BuiltEvidence,
    hypothesis_id: str,
    occurrences: int,
    wins: int,
    losses: int,
    profit: float,
    roi: float,
    median_odds: float,
    losing_streak: int,
    groups: int,
    folds: int,
) -> None:
    top = json.loads((built.reports / "top-3.json").read_text("utf-8"))
    item = next(
        row for row in top["items"] if row["hypothesis_id"] == hypothesis_id
    )
    assert item["occurrences"] == occurrences
    assert item["wins"] == wins
    assert item["losses"] == losses
    assert item["profit_units"] == pytest.approx(profit)
    assert item["roi"] == pytest.approx(roi)
    assert item["median_odds"] == pytest.approx(median_odds)
    assert item["longest_losing_streak"] == losing_streak
    assert item["eligible_folds"] == folds
    assert item["q_value"] == 1.0
    assert item["status"] == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
    summary = pq.read_table(
        built.output / "hypothesis_historical_evidence_summary.parquet"
    ).to_pandas()
    row = summary.loc[summary["hypothesis_id"] == hypothesis_id].iloc[0]
    assert row["statistical_groups"] == groups


def test_top_ten_is_precomputed_for_five_metrics_and_scopes(
    built: BuiltEvidence,
) -> None:
    payload = json.loads((built.reports / "top-10.json").read_text("utf-8"))
    rankings = {
        "by_roi",
        "by_profit",
        "by_support",
        "by_hit_rate",
        "by_lowest_drawdown",
    }
    assert set(payload["global"]) == rankings
    assert set(payload["by_family"]) == {"MARKET"}
    assert set(payload["by_competition"]) == {
        "ALL_AVAILABLE",
        "Bundesliga",
        "La Liga",
        "Ligue 1",
        "Premier League",
        "Serie A",
    }
    for scope in [
        payload["global"],
        *payload["by_competition"].values(),
        *payload["by_family"].values(),
    ]:
        assert set(scope) == rankings
        for ranking in scope.values():
            assert ranking["available_count"] >= len(ranking["items"])
            assert ranking["complete"] is (
                ranking["available_count"] >= ranking["requested_limit"]
            )
            hashes = [
                item["membership_set_hash"] for item in ranking["items"]
            ]
            assert len(hashes) == len(set(hashes))
            assert all(
                item["status"]
                == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
                for item in ranking["items"]
            )


def test_replay_manifest_proves_zero_live_writes(
    built: BuiltEvidence,
) -> None:
    manifest = json.loads(
        (built.output / "artifact-manifest.json").read_text("utf-8")
    )
    assert manifest["replay_hash"] == built.replay_hash
    assert manifest["source"]["dataset_hash"] == DATASET_HASH
    assert manifest["source"]["registry_sha256"] == REGISTRY_SHA256
    assert manifest["source"]["campaign_result_hash"] == CAMPAIGN_RESULT_HASH
    assert manifest["controls"] == {
        "provider_calls": 0,
        "database_writes": 0,
        "temporary_database_rows": 0,
        "postgresql_rows": 0,
        "r2_operations": 0,
        "network_calls": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
    assert set(built.artifact_hashes) == {
        "historical_fixture_evidence.parquet",
        "hypothesis_fixture_membership.parquet",
        "hypothesis_historical_evidence_summary.parquet",
    }


def test_corrupted_registry_fails_before_publication(tmp_path: Path) -> None:
    corrupted = tmp_path / "registry.jsonl"
    payload = REGISTRY.read_text("utf-8")
    corrupted.write_text(payload.replace('"rule_hash": "', '"rule_hash": "f', 1), "utf-8")
    output = tmp_path / "output"
    with pytest.raises(
        EvidenceFactoryError,
        match="J10_REGISTRY_HASH_MISMATCH",
    ):
        build_hypothesis_evidence(
            config(
                output=output,
                reports=tmp_path / "reports",
                registry=corrupted,
            )
        )
    assert not output.exists()


def test_corrupted_historical_row_fails_dataset_hash(tmp_path: Path) -> None:
    if not EXTRACTED.is_dir():
        pytest.skip("extracted frozen cache unavailable")
    copied = tmp_path / "historical"
    shutil.copytree(EXTRACTED, copied)
    partition = sorted(copied.rglob("*.parquet"))[0]
    frame = pd.read_parquet(partition)
    frame["odds_home"] = frame["odds_home"].astype("float64") + 0.01
    frame.to_parquet(partition, index=False)
    with pytest.raises(
        EvidenceFactoryError,
        match="HISTORICAL_DATASET_HASH_MISMATCH",
    ):
        build_hypothesis_evidence(
            config(
                output=tmp_path / "output-corrupt",
                reports=tmp_path / "reports-corrupt",
                historical_root=copied,
            )
        )


def test_checkpoint_rejects_a_different_rule_segment(tmp_path: Path) -> None:
    output = tmp_path / "checkpoint-output"
    reports = tmp_path / "checkpoint-reports"
    interrupted = build_hypothesis_evidence(
        config(
            output=output,
            reports=reports,
            stop_after_batches=1,
        )
    )
    assert interrupted.status == "INTERRUPTED_RESUMABLE"
    checkpoint_path = output / "checkpoint-manifest.json"
    checkpoint = json.loads(checkpoint_path.read_text("utf-8"))
    checkpoint["completed"][0]["first_rule_hash"] = "f" * 64
    checkpoint_path.write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        EvidenceFactoryError,
        match="checkpoint.first_rule_hash",
    ):
        build_hypothesis_evidence(config(output=output, reports=reports))
