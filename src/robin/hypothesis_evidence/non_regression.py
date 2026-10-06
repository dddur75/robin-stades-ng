"""Bounded R3 replay for the three frozen Jalon 10 engineering witnesses."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from robin.hypothesis_evidence.contracts import (
    AUTHORITATIVE_HISTORICAL_REVISION,
    CAMPAIGN_RESULT_HASH,
    COMPACT_CAMPAIGN_SHA256,
    DATASET_HASH,
    FULL_CAMPAIGN_SHA256,
    HISTORICAL_PARQUET_TREE,
    REGISTRY_SHA256,
)
from robin.hypothesis_evidence.factory import _rule_evidence
from robin.hypothesis_evidence.source import load_frozen_historical_market
from robin.patterns.contracts import PatternCondition
from robin.patterns.engine import Rule

MISSION_ID = "ROBIN_SIMPLIFICATION_R3_JALON10_20261005"
SCIENTIFIC_VERDICT = "JALON_10_NO_ROBUST_PATTERN_FOUND"
REJECTED_STATUS = "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
PER_BET_ABS_TOLERANCE = 1e-12
AGGREGATE_UNITS_ABS_TOLERANCE = 1e-9
ROI_ABS_TOLERANCE = 1e-12

EXPECTED_WITNESS_IDS = ("J10-M001", "J10-M002", "J10-M003")
EXPECTED_RULE_HASHES = (
    "293f3a6d5e635389abc272e8b6579b5e95df58836cd2e1355737df96c52f4867",
    "a82c917853baf22ec85eea189eb2efde72022b0271e1e0eadffb2f851d0623a2",
    "561b8a16908ab9bb8cb477c77af343779d20485d959b40ea7ed2a2e60535ec20",
)
EXPECTED_BETS = (261, 363, 241)

EXPECTED_ARTIFACT_SHA256 = {
    "historical_fixture_evidence.parquet": (
        "b16150b9620bb1af4d68bfa0f9c30de2786e3107dfb4b1b1f0152bbdf44be3ce"
    ),
    "hypothesis_fixture_membership.parquet": (
        "95f5745803cd76d93bbd949debd5219723506838d15d3d8d034cb82bf710aeea"
    ),
    "hypothesis_historical_evidence_summary.parquet": (
        "ae3f4b5590c54bb036533871245258f7714d86e4e368c9b6244b524e821e0058"
    ),
}

PER_BET_FLOAT_FIELDS = {
    "observed_odds",
    "market_margin",
    "stake_units",
    "gross_return_units",
    "profit_units",
}
AGGREGATE_FLOAT_FIELDS = {"cumulative_profit_units"}


class NonRegressionMismatch(ValueError):
    """Raised when a frozen witness differs from its bounded replay."""


@dataclass(frozen=True, slots=True)
class WitnessRule:
    hypothesis_id: str
    rule: Rule
    expected_bets: int
    expected_profit_units: float
    expected_roi: float
    expected_drawdown_units: float
    expected_q_value: float
    expected_status: str
    expected_membership_set_hash: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NonRegressionMismatch(message)


def witness_rules(payload: Mapping[str, object]) -> tuple[WitnessRule, ...]:
    """Build only the three pinned rules, without regenerating the search space."""

    _require(payload.get("dataset_hash") == DATASET_HASH, "dataset_hash mismatch")
    _require(
        payload.get("source_result_hash") == CAMPAIGN_RESULT_HASH,
        "campaign result hash mismatch",
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise NonRegressionMismatch("top-three items missing")
    _require(len(items) == 3, "exactly three witnesses required")
    result: list[WitnessRule] = []
    for position, raw_value in enumerate(items):
        if not isinstance(raw_value, Mapping):
            raise NonRegressionMismatch(f"witness {position} is not an object")
        raw: Mapping[str, object] = raw_value
        conditions = raw.get("conditions")
        if not isinstance(conditions, list):
            raise NonRegressionMismatch(f"witness {position} conditions missing")
        rule = Rule(
            market=str(raw.get("market")),
            selection=str(raw.get("selection")),
            conditions=tuple(PatternCondition.model_validate(item) for item in conditions),
        )
        hypothesis_id = str(raw.get("hypothesis_id"))
        _require(
            hypothesis_id == EXPECTED_WITNESS_IDS[position],
            f"unexpected hypothesis_id at {position}",
        )
        _require(
            rule.digest == EXPECTED_RULE_HASHES[position],
            f"rule_hash mismatch for {hypothesis_id}",
        )
        _require(
            str(raw.get("rule_hash")) == rule.digest,
            f"published rule_hash mismatch for {hypothesis_id}",
        )
        expected_bets = _integer(raw.get("occurrences", -1), field="occurrences")
        _require(
            expected_bets == EXPECTED_BETS[position],
            f"published bets mismatch for {hypothesis_id}",
        )
        result.append(
            WitnessRule(
                hypothesis_id=hypothesis_id,
                rule=rule,
                expected_bets=expected_bets,
                expected_profit_units=_float(
                    raw.get("profit_units", math.nan), field="profit_units"
                ),
                expected_roi=_float(raw.get("roi", math.nan), field="roi"),
                expected_drawdown_units=_float(
                    raw.get("maximum_drawdown_units", math.nan),
                    field="maximum_drawdown_units",
                ),
                expected_q_value=_float(raw.get("q_value", math.nan), field="q_value"),
                expected_status=str(raw.get("status")),
                expected_membership_set_hash=str(raw.get("membership_set_hash")),
            )
        )
    _require(
        all(item.expected_q_value == 1.0 for item in result),
        "q_value must remain 1",
    )
    _require(
        all(item.expected_status == REJECTED_STATUS for item in result),
        "scientific status changed",
    )
    return tuple(result)


def _float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise NonRegressionMismatch(f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise NonRegressionMismatch(f"{field} must be finite")
    return converted


def _integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NonRegressionMismatch(f"{field} must be an integer")
    return value


def recalculate_metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Independently recalculate unit-stake profit, ROI and chronological drawdown."""

    profits: list[float] = []
    wins = 0
    losses = 0
    voids = 0
    bankroll = 1_000.0
    peak = bankroll
    maximum_drawdown = 0.0
    for position, row in enumerate(rows, start=1):
        stake = _float(row.get("stake_units"), field="stake_units")
        _require(
            math.isclose(stake, 1.0, rel_tol=0.0, abs_tol=PER_BET_ABS_TOLERANCE),
            f"stake_units mismatch at {position}",
        )
        won = row.get("won") is True
        lost = row.get("lost") is True
        void = row.get("void") is True
        _require(
            sum((won, lost, void)) == 1,
            f"settlement state mismatch at {position}",
        )
        odds = _float(row.get("observed_odds"), field="observed_odds")
        expected_profit = stake * (odds - 1.0) if won else (-stake if lost else 0.0)
        profit = _float(row.get("profit_units"), field="profit_units")
        _require(
            math.isclose(
                profit,
                expected_profit,
                rel_tol=0.0,
                abs_tol=PER_BET_ABS_TOLERANCE,
            ),
            f"profit_units settlement mismatch at {position}",
        )
        profits.append(profit)
        wins += int(won)
        losses += int(lost)
        voids += int(void)
        bankroll += profit
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, peak - bankroll)
    total_staked = float(len(rows))
    total_profit = math.fsum(profits)
    return {
        "bets": len(rows),
        "wins": wins,
        "losses": losses,
        "voids": voids,
        "total_staked_units": total_staked,
        "profit_units": total_profit,
        "roi": total_profit / total_staked if total_staked else None,
        "maximum_drawdown_units": maximum_drawdown,
    }


def _assert_occurrence_contract(
    rows: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> None:
    identities = [
        (str(row.get("hypothesis_id")), str(row.get("canonical_match_id"))) for row in rows
    ]
    _require(len(identities) == len(set(identities)), f"{label} duplicate identity")
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("hypothesis_id"))].append(
            _integer(row.get("occurrence_index", -1), field="occurrence_index")
        )
    for hypothesis_id, indices in grouped.items():
        _require(
            indices == list(range(1, len(indices) + 1)),
            f"{label} occurrence_index mismatch for {hypothesis_id}",
        )


def compare_detailed_rows(
    baseline: Sequence[Mapping[str, object]],
    replay: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compare frozen and replayed rows, failing on every unexplained delta."""

    _require(len(baseline) == len(replay), "row count mismatch")
    _assert_occurrence_contract(baseline, label="baseline")
    _assert_occurrence_contract(replay, label="replay")
    maxima = {field: 0.0 for field in sorted(PER_BET_FLOAT_FIELDS | AGGREGATE_FLOAT_FIELDS)}
    for position, (before, after) in enumerate(zip(baseline, replay, strict=True)):
        _require(
            set(before) == set(after),
            f"field set mismatch at row {position + 1}",
        )
        for field in sorted(before):
            left = before[field]
            right = after[field]
            if field in PER_BET_FLOAT_FIELDS:
                tolerance = PER_BET_ABS_TOLERANCE
            elif field in AGGREGATE_FLOAT_FIELDS:
                tolerance = AGGREGATE_UNITS_ABS_TOLERANCE
            else:
                _require(left == right, f"{field} mismatch at row {position + 1}")
                continue
            difference = abs(_float(left, field=field) - _float(right, field=field))
            maxima[field] = max(maxima[field], difference)
            _require(
                difference <= tolerance,
                f"{field} mismatch at row {position + 1}: {difference}",
            )
    return {
        "rows_compared": len(baseline),
        "unexplained_delta_count": 0,
        "maximum_absolute_deltas": maxima,
    }


def _verify_hash(path: Path, expected: str, *, label: str) -> str:
    _require(path.is_file(), f"{label} missing: {path}")
    observed = _sha256(path)
    _require(observed == expected, f"{label} SHA-256 mismatch: {observed}")
    return observed


def _read_parquet(
    path: Path,
    *,
    filters: list[tuple[str, str, object]] | None = None,
) -> list[dict[str, object]]:
    return [dict(row) for row in pq.read_table(path, filters=filters).to_pylist()]


def _fixture_projection(row: Mapping[str, object]) -> dict[str, object]:
    fixture_id = str(row.get("fixture_id"))
    return {
        "canonical_match_id": str(row.get("canonical_match_id") or f"api-football:{fixture_id}"),
        "fixture_id": fixture_id,
        "kickoff_at": str(row.get("kickoff_at")),
        "competition": str(row.get("competition")),
        "season": _integer(row.get("season", -1), field="season"),
        "home_team_id": str(row.get("home_team_id")),
        "away_team_id": str(row.get("away_team_id")),
        "home_team_name": str(row.get("home_team_name") or row.get("home_source_name")),
        "away_team_name": str(row.get("away_team_name") or row.get("away_source_name")),
        "home_goals": _integer(row.get("home_goals", -1), field="home_goals"),
        "away_goals": _integer(row.get("away_goals", -1), field="away_goals"),
        "source_row_hash": str(row.get("record_hash") or row.get("_record_hash")),
    }


def _enrich_memberships(
    rows: Sequence[Mapping[str, object]],
    fixtures: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for membership in rows:
        match_id = str(membership.get("canonical_match_id"))
        fixture = fixtures.get(match_id)
        if fixture is None:
            raise NonRegressionMismatch(f"fixture identity missing for {match_id}")
        projection = _fixture_projection(fixture)
        _require(
            projection["canonical_match_id"] == match_id,
            f"canonical_match_id mismatch for {match_id}",
        )
        result.append({**dict(membership), **projection})
    return result


def _ordered_witness_rows(
    rows: Sequence[Mapping[str, object]],
    witnesses: Sequence[WitnessRule],
) -> list[dict[str, object]]:
    order = {item.hypothesis_id: position for position, item in enumerate(witnesses)}
    _require(
        {str(row.get("hypothesis_id")) for row in rows} == set(order),
        "membership hypothesis set mismatch",
    )
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            order[str(row["hypothesis_id"])],
            _integer(row["occurrence_index"], field="occurrence_index"),
        ),
    )


def _campaign_hypotheses(
    path: Path,
    witnesses: Sequence[WitnessRule],
) -> dict[str, Mapping[str, Any]]:
    _verify_hash(path, FULL_CAMPAIGN_SHA256, label="full campaign")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(
        payload.get("result_hash") == CAMPAIGN_RESULT_HASH,
        "full campaign result hash mismatch",
    )
    hypotheses = payload.get("hypotheses")
    _require(isinstance(hypotheses, list), "full campaign hypotheses missing")
    wanted = {item.rule.digest for item in witnesses}
    selected = {
        str(item.get("rule_hash")): item
        for item in hypotheses
        if isinstance(item, Mapping) and str(item.get("rule_hash")) in wanted
    }
    _require(set(selected) == wanted, "three campaign hypotheses not found")
    return selected


def _summary_comparison(
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, float]:
    float_tolerances = {
        "profit_units": AGGREGATE_UNITS_ABS_TOLERANCE,
        "roi": ROI_ABS_TOLERANCE,
        "maximum_drawdown_units": AGGREGATE_UNITS_ABS_TOLERANCE,
        "max_drawdown_units": AGGREGATE_UNITS_ABS_TOLERANCE,
        "average_odds": ROI_ABS_TOLERANCE,
        "hit_rate": ROI_ABS_TOLERANCE,
    }
    exact_fields = {
        "hypothesis_id",
        "rule_hash",
        "membership_set_hash",
        "market",
        "selection",
        "occurrences",
        "settled_bets",
        "wins",
        "losses",
        "voids",
        "hypothesis_status",
    }
    for field in exact_fields:
        _require(before.get(field) == after.get(field), f"summary {field} mismatch")
    deltas: dict[str, float] = {}
    for field, tolerance in float_tolerances.items():
        difference = abs(
            _float(before.get(field), field=field) - _float(after.get(field), field=field)
        )
        deltas[field] = difference
        _require(difference <= tolerance, f"summary {field} mismatch: {difference}")
    return deltas


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> str:
    payload = b"".join(_canonical_bytes(dict(row)) + b"\n" for row in rows)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def run_non_regression(
    *,
    repo_root: Path,
    evidence_root: Path,
    campaign_root: Path,
    output_root: Path,
    report_path: Path,
) -> dict[str, object]:
    """Replay three rules from pinned Git blobs and compare every detailed result."""

    top_three_path = repo_root / "reports/hypothesis-evidence/top-3.json"
    compact_campaign_path = repo_root / "reports/pattern-research/campaign-summary.json"
    registry_path = campaign_root / "hypothesis-registry.jsonl"
    full_campaign_path = campaign_root / "campaign-summary.json"
    _verify_hash(compact_campaign_path, COMPACT_CAMPAIGN_SHA256, label="compact campaign")
    _verify_hash(registry_path, REGISTRY_SHA256, label="hypothesis registry")
    top_three = json.loads(top_three_path.read_text(encoding="utf-8"))
    witnesses = witness_rules(top_three)

    observed_artifact_hashes = {
        name: _verify_hash(evidence_root / name, expected, label=name)
        for name, expected in EXPECTED_ARTIFACT_SHA256.items()
    }
    rule_hashes = [item.rule.digest for item in witnesses]
    hypothesis_ids = [item.hypothesis_id for item in witnesses]
    membership_rows = _read_parquet(
        evidence_root / "hypothesis_fixture_membership.parquet",
        filters=[("rule_hash", "in", rule_hashes)],
    )
    summary_rows = _read_parquet(
        evidence_root / "hypothesis_historical_evidence_summary.parquet",
        filters=[("rule_hash", "in", rule_hashes)],
    )
    _require(len(membership_rows) == sum(EXPECTED_BETS), "oracle row count mismatch")
    _require(len(summary_rows) == 3, "oracle summary count mismatch")
    match_ids = sorted({str(row["canonical_match_id"]) for row in membership_rows})
    fixture_rows = _read_parquet(
        evidence_root / "historical_fixture_evidence.parquet",
        filters=[("canonical_match_id", "in", match_ids)],
    )
    _require(len(fixture_rows) == len(match_ids), "oracle fixture identity mismatch")
    oracle_fixtures = {str(row["canonical_match_id"]): row for row in fixture_rows}

    historical = load_frozen_historical_market(
        repo_root,
        historical_root=None,
        revision=AUTHORITATIVE_HISTORICAL_REVISION,
    )
    _require(historical.dataset_hash == DATASET_HASH, "historical dataset mismatch")
    _require(
        historical.parquet_tree == HISTORICAL_PARQUET_TREE,
        "historical parquet tree mismatch",
    )
    source_fixtures = {f"api-football:{row['fixture_id']}": row for row in historical.rows}
    hypotheses = _campaign_hypotheses(full_campaign_path, witnesses)

    replay_memberships: list[dict[str, object]] = []
    replay_summaries: dict[str, dict[str, object]] = {}
    for witness in witnesses:
        memberships, summary, _ = _rule_evidence(
            historical.rows,
            witness.rule,
            hypotheses[witness.rule.digest],
        )
        _require(
            len(memberships) == witness.expected_bets,
            f"replay bets mismatch for {witness.hypothesis_id}",
        )
        replay_memberships.extend(memberships)
        replay_summaries[witness.rule.digest] = summary

    baseline = _ordered_witness_rows(
        _enrich_memberships(membership_rows, oracle_fixtures),
        witnesses,
    )
    replay = _ordered_witness_rows(
        _enrich_memberships(replay_memberships, source_fixtures),
        witnesses,
    )
    detail_comparison = compare_detailed_rows(baseline, replay)

    oracle_summaries = {str(row["rule_hash"]): row for row in summary_rows}
    witness_reports: list[dict[str, object]] = []
    for witness in witnesses:
        rule_hash = witness.rule.digest
        before_summary = oracle_summaries[rule_hash]
        after_summary = replay_summaries[rule_hash]
        summary_deltas = _summary_comparison(before_summary, after_summary)
        rule_rows = [row for row in replay if row["rule_hash"] == rule_hash]
        metrics = recalculate_metrics(rule_rows)
        _require(metrics["bets"] == witness.expected_bets, "metrics bets mismatch")
        _require(
            abs(
                _float(metrics["profit_units"], field="profit_units")
                - witness.expected_profit_units
            )
            <= AGGREGATE_UNITS_ABS_TOLERANCE,
            f"profit_units mismatch for {witness.hypothesis_id}",
        )
        _require(
            abs(_float(metrics["roi"], field="roi") - witness.expected_roi) <= ROI_ABS_TOLERANCE,
            f"roi mismatch for {witness.hypothesis_id}",
        )
        _require(
            abs(
                _float(
                    metrics["maximum_drawdown_units"],
                    field="maximum_drawdown_units",
                )
                - witness.expected_drawdown_units
            )
            <= AGGREGATE_UNITS_ABS_TOLERANCE,
            f"maximum_drawdown_units mismatch for {witness.hypothesis_id}",
        )
        _require(
            str(after_summary["membership_set_hash"]) == witness.expected_membership_set_hash,
            f"membership_set_hash mismatch for {witness.hypothesis_id}",
        )
        witness_reports.append(
            {
                "hypothesis_id": witness.hypothesis_id,
                "rule_hash": rule_hash,
                "bets": witness.expected_bets,
                "metrics": metrics,
                "summary_maximum_absolute_deltas": summary_deltas,
                "membership_set_hash": witness.expected_membership_set_hash,
                "q_value": witness.expected_q_value,
                "status": witness.expected_status,
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    baseline_path = output_root / "baseline-before-simplification.jsonl"
    replay_path = output_root / "replay-after-simplification.jsonl"
    baseline_sha256 = _write_jsonl(baseline_path, baseline)
    replay_sha256 = _write_jsonl(replay_path, replay)
    _require(
        baseline_sha256 == replay_sha256,
        "detailed canonical output hash mismatch",
    )
    detailed_manifest = {
        "schema_version": "r3-jalon10-detailed-manifest-v1",
        "outside_git": True,
        "rows": len(baseline),
        "baseline": {
            "name": baseline_path.name,
            "sha256": baseline_sha256,
        },
        "replay": {"name": replay_path.name, "sha256": replay_sha256},
    }
    manifest_path = output_root / "detailed-manifest.json"
    manifest_path.write_bytes(_canonical_bytes(detailed_manifest) + b"\n")

    report: dict[str, object] = {
        "schema_version": "r3-jalon10-non-regression-v1",
        "mission_id": MISSION_ID,
        "equivalence_status": "PASS",
        "scientific_verdict": SCIENTIFIC_VERDICT,
        "scientific_verdict_changed": False,
        "search_reopened": False,
        "rules_replayed": hypothesis_ids,
        "rule_count": len(witnesses),
        "rows_compared": len(baseline),
        "unique_fixtures_compared": len(match_ids),
        "source": {
            "mode": historical.source_mode,
            "historical_revision": historical.authoritative_revision,
            "historical_parquet_tree": historical.parquet_tree,
            "dataset_hash": historical.dataset_hash,
            "partition_count": len(historical.partitions),
        },
        "oracle": {
            "artifact_sha256": observed_artifact_hashes,
            "campaign_result_hash": CAMPAIGN_RESULT_HASH,
            "registry_sha256": REGISTRY_SHA256,
        },
        "tolerances": {
            "relative": 0.0,
            "per_bet_absolute": PER_BET_ABS_TOLERANCE,
            "aggregate_units_absolute": AGGREGATE_UNITS_ABS_TOLERANCE,
            "roi_absolute": ROI_ABS_TOLERANCE,
            "justification": (
                "Bounds cover binary64 addition noise over at most 363 bets and "
                "remain far below the report precision of 0.01 unit."
            ),
        },
        "detailed_artifacts": detailed_manifest,
        "detailed_manifest_sha256": _sha256(manifest_path),
        "comparison": detail_comparison,
        "witnesses": witness_reports,
        "explained_legacy_bug_corrections": [],
        "unexplained_deltas": [],
        "external_effects": {
            "provider_http_requests_new": 0,
            "provider_credits_new": 0,
            "r2_reads_new": 0,
            "r2_writes_new": 0,
            "bets": 0,
            "promotions": 0,
        },
        "warning": (
            "Historical exposed engineering witnesses only; not evidence of a "
            "predictive edge or future performance."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(json.dumps(report, ensure_ascii=False, indent=2).encode() + b"\n")
    return report
