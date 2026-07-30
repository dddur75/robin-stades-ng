"""Deterministic sparse evidence factory for every frozen Jalon 10 rule."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from robin.hypothesis_evidence.contracts import (
    AUTHORITATIVE_HISTORICAL_REVISION,
    CAMPAIGN_CODE_REVISION,
    CAMPAIGN_EXECUTED_AT,
    CAMPAIGN_ID,
    CAMPAIGN_RESULT_HASH,
    COMPACT_CAMPAIGN_SHA256,
    DATASET_HASH,
    EXPECTED_FIXTURES,
    EXPECTED_RAW_MEMBERSHIPS,
    EXPECTED_RAW_STRICT_DELTA,
    EXPECTED_RULES,
    EXPECTED_STRICT_MEMBERSHIPS,
    FULL_CAMPAIGN_SHA256,
    HISTORICAL_FIXTURE_EVIDENCE_SCHEMA,
    HISTORICAL_FIXTURE_SCHEMA_VERSION,
    HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA,
    HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA,
    MEMBERSHIP_SCHEMA_VERSION,
    REGISTRY_SHA256,
    SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
    TOP_RULE_IDS,
    EvidenceBuildConfig,
    EvidenceBuildResult,
    EvidenceFactoryError,
    canonical_json,
    canonical_sha256,
    hypothesis_id,
    schema_contract,
    sha256_file,
)
from robin.hypothesis_evidence.source import (
    LoadedHistoricalMarket,
    load_frozen_historical_market,
)
from robin.hypothesis_intelligence.competition_identity import resolve_competition
from robin.patterns.campaign import _walk_forward_evidence
from robin.patterns.engine import (
    Rule,
    apply_rule,
    fixed_stake_metrics,
    market_won,
    observed_odds,
)
from robin.patterns.persistence import _validate_result_hash
from robin.patterns.search_space import generate_rules
from robin.patterns.statistics import (
    benjamini_hochberg,
    clustered_positive_mean_p_value,
    flat_stake_metrics,
    grouped_bootstrap_mean,
)

PARQUET_OPTIONS: dict[str, object] = {
    "compression": "zstd",
    "compression_level": 3,
    "data_page_version": "2.0",
    "use_dictionary": True,
    "write_statistics": True,
}
FLOAT_ABS_TOLERANCE = 1e-9
FLOAT_REL_TOLERANCE = 1e-12


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceFactoryError(f"JSON_INPUT_INVALID:{path.name}") from exc
    if not isinstance(payload, dict):
        raise EvidenceFactoryError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    try:
        lines = path.read_text("utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("record")
            output.append(item)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceFactoryError("J10_REGISTRY_JSONL_INVALID") from exc
    return output


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_parquet(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    schema: pa.Schema,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    table = pa.Table.from_pylist(list(rows), schema=schema)
    pq.write_table(
        table,
        temporary,
        row_group_size=32_768,
        **PARQUET_OPTIONS,
    )
    os.replace(temporary, path)


def _merge_parquet(
    sources: Sequence[Path],
    destination: Path,
    schema: pa.Schema,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    writer = pq.ParquetWriter(temporary, schema, **PARQUET_OPTIONS)
    try:
        for source in sources:
            table = pq.read_table(source, schema=schema)
            writer.write_table(table, row_group_size=32_768)
    finally:
        writer.close()
    os.replace(temporary, destination)


def _parquet_rows(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def _assert_float(label: str, actual: object, expected: object) -> None:
    if actual is None or expected is None:
        if actual is expected:
            return
        raise EvidenceFactoryError(
            f"RECONCILIATION_NULL_MISMATCH:{label}:{actual}:{expected}"
        )
    if not math.isclose(
        _safe_float(actual, label=f"{label}.actual"),
        _safe_float(expected, label=f"{label}.expected"),
        rel_tol=FLOAT_REL_TOLERANCE,
        abs_tol=FLOAT_ABS_TOLERANCE,
    ):
        raise EvidenceFactoryError(
            f"RECONCILIATION_FLOAT_MISMATCH:{label}:{actual}:{expected}"
        )


def _assert_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise EvidenceFactoryError(
            f"RECONCILIATION_VALUE_MISMATCH:{label}:{actual}:{expected}"
        )


def _campaign_inputs(
    config: EvidenceBuildConfig,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    if sha256_file(config.registry_path) != REGISTRY_SHA256:
        raise EvidenceFactoryError("J10_REGISTRY_HASH_MISMATCH")
    if sha256_file(config.full_campaign_path) != FULL_CAMPAIGN_SHA256:
        raise EvidenceFactoryError("J10_FULL_CAMPAIGN_HASH_MISMATCH")
    if sha256_file(config.compact_campaign_path) != COMPACT_CAMPAIGN_SHA256:
        raise EvidenceFactoryError("J10_COMPACT_CAMPAIGN_HASH_MISMATCH")
    full = _load_json(config.full_campaign_path)
    compact = _load_json(config.compact_campaign_path)
    registry = _load_jsonl(config.registry_path)
    if len(registry) != EXPECTED_RULES:
        raise EvidenceFactoryError(
            f"J10_RULE_COUNT_MISMATCH:{len(registry)}"
        )
    if full.get("hypotheses") != registry:
        raise EvidenceFactoryError("J10_REGISTRY_CAMPAIGN_CONTENT_MISMATCH")
    if _validate_result_hash(full) != CAMPAIGN_RESULT_HASH:
        raise EvidenceFactoryError("J10_RESULT_HASH_MISMATCH")
    expected_compact = {
        "campaign_id": CAMPAIGN_ID,
        "executed_at": CAMPAIGN_EXECUTED_AT,
        "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
        "code_revision": CAMPAIGN_CODE_REVISION,
        "result_hash": CAMPAIGN_RESULT_HASH,
    }
    for name, expected in expected_compact.items():
        _assert_equal(f"compact.{name}", compact.get(name), expected)
    _assert_equal("full.code_revision", full.get("code_revision"), CAMPAIGN_CODE_REVISION)
    _assert_equal("full.dataset_hashes", full.get("dataset_hashes"), [DATASET_HASH])
    _assert_equal("compact.dataset_hashes", compact.get("dataset_hashes"), [DATASET_HASH])
    _assert_equal("compact.mode", compact.get("mode"), "CACHE_ONLY")
    _assert_equal("compact.provider_calls", compact.get("costs", {}).get("provider_calls"), 0)
    _assert_equal("full.provider_calls", full.get("provider_calls"), 0)
    return full, compact, registry


def _rule_catalog(
    rows: Sequence[Mapping[str, object]],
    registry: Sequence[Mapping[str, object]],
) -> list[Rule]:
    rules = generate_rules(rows)
    if len(rules) != EXPECTED_RULES:
        raise EvidenceFactoryError(f"GENERATED_RULE_COUNT_MISMATCH:{len(rules)}")
    generated_hashes = [rule.digest for rule in rules]
    registry_hashes = [str(item.get("rule_hash")) for item in registry]
    if generated_hashes != registry_hashes:
        raise EvidenceFactoryError("GENERATED_RULE_ORDER_OR_HASH_MISMATCH")
    if len(set(generated_hashes)) != EXPECTED_RULES:
        raise EvidenceFactoryError("GENERATED_RULE_HASH_DUPLICATE")
    identifiers = [hypothesis_id(digest) for digest in generated_hashes]
    if len(set(identifiers)) != EXPECTED_RULES:
        raise EvidenceFactoryError("J10_HYPOTHESIS_ID_COLLISION")
    return rules


def _condition_competition(
    hypothesis: Mapping[str, object],
) -> str:
    conditions = hypothesis.get("conditions")
    if not isinstance(conditions, list):
        raise EvidenceFactoryError("RULE_CONDITIONS_INVALID")
    for condition in conditions:
        if (
            isinstance(condition, Mapping)
            and condition.get("feature") == "competition"
        ):
            return str(condition.get("value"))
    return "ALL_AVAILABLE"


def _safe_int(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise EvidenceFactoryError(f"INTEGER_REQUIRED:{label}")
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise EvidenceFactoryError(f"INTEGER_REQUIRED:{label}") from exc


def _safe_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise EvidenceFactoryError(f"FLOAT_REQUIRED:{label}")
    try:
        converted = float(value)
    except ValueError as exc:
        raise EvidenceFactoryError(f"FLOAT_REQUIRED:{label}") from exc
    if not math.isfinite(converted):
        raise EvidenceFactoryError(f"FINITE_FLOAT_REQUIRED:{label}")
    return converted


def _rule_evidence(
    rows: Sequence[Mapping[str, object]],
    rule: Rule,
    hypothesis: Mapping[str, Any],
) -> tuple[list[dict[str, object]], dict[str, object], int]:
    raw_matches = apply_rule(rows, rule)
    selected: list[
        tuple[Mapping[str, object], float, bool, int, str, float]
    ] = []
    price_field = "totals_price_type" if rule.market.startswith("TOTAL_") else "price_type"
    margin_field = (
        "market_margin_totals"
        if rule.market.startswith("TOTAL_")
        else "market_margin_1x2"
    )
    for row in raw_matches:
        odds = observed_odds(row, rule.market)
        won = market_won(row, rule.market)
        if odds is None or won is None:
            continue
        season = _safe_int(row.get("season"), label="season")
        price_class = str(row.get(price_field) or "")
        margin_value = row.get(margin_field)
        if not price_class or not isinstance(margin_value, int | float):
            raise EvidenceFactoryError(
                f"STRICT_MEMBERSHIP_PRICE_CONTRACT_INVALID:{rule.digest}"
            )
        selected.append(
            (
                row,
                float(odds),
                bool(won),
                season,
                price_class,
                float(margin_value),
            )
        )

    fixture_ids = [str(item[0].get("fixture_id")) for item in selected]
    if len(set(fixture_ids)) != len(fixture_ids):
        raise EvidenceFactoryError(
            f"RULE_FIXTURE_MEMBERSHIP_DUPLICATE:{rule.digest}"
        )
    canonical_ids = [f"api-football:{fixture_id}" for fixture_id in fixture_ids]
    membership_set_hash = canonical_sha256(
        {
            "dataset_hash": DATASET_HASH,
            "canonical_match_ids": sorted(canonical_ids),
        }
    )
    profits = [
        odds - 1.0 if won else -1.0
        for _, odds, won, _, _, _ in selected
    ]
    odds_values = [odds for _, odds, _, _, _, _ in selected]
    outcomes = [won for _, _, won, _, _, _ in selected]
    seasons = [season for _, _, _, season, _, _ in selected]
    groups = [
        str(row.get("match_date") or row.get("fixture_id"))
        for row, _, _, _, _, _ in selected
    ]

    fixed = fixed_stake_metrics(profits, odds_values)
    flat = (
        flat_stake_metrics(odds_values, outcomes)
        if odds_values
        else None
    )
    if flat is None:
        financial: dict[str, object] = {
            "bets": 0,
            "settled_bets": 0,
            "wins": 0,
            "losses": 0,
            "voids": 0,
            "stake_per_bet": 1.0,
            "total_staked_units": 0.0,
            "turnover_units": 0.0,
            "profit_units": 0.0,
            "roi": None,
            "hit_rate": None,
            "average_odds": None,
            "median_odds": None,
            "max_drawdown_units": 0.0,
            "max_losing_streak": 0,
            "gross_profit_units": 0.0,
            "gross_loss_units": 0.0,
            "profit_factor": None,
            "starting_bankroll_units": 1000.0,
            "ending_bankroll_units": 1000.0,
        }
    else:
        financial = asdict(flat)
        for name in (
            "bets",
            "wins",
            "losses",
            "max_losing_streak",
        ):
            _assert_equal(
                f"{rule.digest}.engine.{name}",
                getattr(fixed, name),
                financial[name],
            )
        for name, fixed_name in (
            ("profit_units", "profit_units"),
            ("roi", "roi"),
            ("hit_rate", "hit_rate"),
            ("average_odds", "average_odds"),
            ("median_odds", "median_odds"),
            ("max_drawdown_units", "max_drawdown_units"),
        ):
            _assert_float(
                f"{rule.digest}.engine.{name}",
                getattr(fixed, fixed_name),
                financial[name],
            )

    support = hypothesis.get("support")
    if not isinstance(support, Mapping):
        raise EvidenceFactoryError(f"RULE_SUPPORT_MISSING:{rule.digest}")
    _assert_equal(
        f"{rule.digest}.support.observations",
        len(selected),
        int(support.get("observations", -1)),
    )
    _assert_equal(
        f"{rule.digest}.support.distinct_groups",
        len(set(seasons)),
        int(support.get("distinct_groups", -1)),
    )

    authoritative_metrics = hypothesis.get("metrics")
    if authoritative_metrics is None:
        if selected:
            raise EvidenceFactoryError(
                f"RULE_AUTHORITATIVE_METRICS_MISSING:{rule.digest}"
            )
    elif not isinstance(authoritative_metrics, Mapping):
        raise EvidenceFactoryError(
            f"RULE_AUTHORITATIVE_METRICS_INVALID:{rule.digest}"
        )
    else:
        for name in (
            "bets",
            "settled_bets",
            "wins",
            "losses",
            "voids",
            "max_losing_streak",
        ):
            _assert_equal(
                f"{rule.digest}.metrics.{name}",
                financial[name],
                authoritative_metrics.get(name),
            )
        for name in (
            "stake_per_bet",
            "total_staked_units",
            "turnover_units",
            "profit_units",
            "roi",
            "hit_rate",
            "average_odds",
            "median_odds",
            "max_drawdown_units",
            "gross_profit_units",
            "gross_loss_units",
            "profit_factor",
            "starting_bankroll_units",
            "ending_bankroll_units",
        ):
            _assert_float(
                f"{rule.digest}.metrics.{name}",
                financial[name],
                authoritative_metrics.get(name),
            )

    support_sufficient = bool(support.get("sufficient"))
    recomputed_p = (
        clustered_positive_mean_p_value(profits, groups)
        if support_sufficient and profits
        else 1.0
    )
    _assert_float(
        f"{rule.digest}.p_value",
        recomputed_p,
        hypothesis.get("p_value"),
    )

    bootstrap = hypothesis.get("bootstrap")
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    confidence_level: float | None = None
    bootstrap_groups = 0
    if bootstrap is not None:
        if not isinstance(bootstrap, Mapping):
            raise EvidenceFactoryError(f"RULE_BOOTSTRAP_INVALID:{rule.digest}")
        recomputed_bootstrap = asdict(
            grouped_bootstrap_mean(
                profits,
                groups,
                iterations=int(bootstrap["iterations"]),
                seed=int(bootstrap["seed"]),
                confidence=float(bootstrap["confidence"]),
            )
        )
        for name in ("iterations", "seed", "groups"):
            _assert_equal(
                f"{rule.digest}.bootstrap.{name}",
                recomputed_bootstrap[name],
                bootstrap.get(name),
            )
        for name in ("estimate", "lower", "upper", "confidence"):
            _assert_float(
                f"{rule.digest}.bootstrap.{name}",
                recomputed_bootstrap[name],
                bootstrap.get(name),
            )
        confidence_lower = float(bootstrap["lower"])
        confidence_upper = float(bootstrap["upper"])
        confidence_level = float(bootstrap["confidence"])
        bootstrap_groups = int(bootstrap["groups"])

    walk_forward = hypothesis.get("walk_forward")
    eligible_folds = 0
    positive_folds = 0
    walk_forward_survived = False
    if walk_forward is not None:
        if not isinstance(walk_forward, Mapping):
            raise EvidenceFactoryError(
                f"RULE_WALK_FORWARD_INVALID:{rule.digest}"
            )
        recomputed_walk = _walk_forward_evidence(
            profits=profits,
            seasons=seasons,
            minimum_fold_bets=15,
            minimum_positive_fold_ratio=0.67,
        )
        if canonical_json(recomputed_walk) != canonical_json(dict(walk_forward)):
            raise EvidenceFactoryError(
                f"RULE_WALK_FORWARD_MISMATCH:{rule.digest}"
            )
        eligible_folds = int(walk_forward["eligible_folds"])
        positive_folds = int(walk_forward["positive_folds"])
        walk_forward_survived = bool(walk_forward["survived"])

    hypothesis_identifier = hypothesis_id(rule.digest)
    campaign_status = str(hypothesis.get("status"))
    hypothesis_status = (
        "DATA_GATE_BLOCKED"
        if campaign_status == "INSUFFICIENT_SUPPORT"
        else "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
    )
    evidence_scope = str(hypothesis.get("evidence_scope"))
    membership_rows: list[dict[str, object]] = []
    cumulative_profit = 0.0
    for index, (
        row,
        odds,
        won,
        season,
        price_class,
        margin,
    ) in enumerate(selected, start=1):
        fixture_id = str(row["fixture_id"])
        canonical_match_id = f"api-football:{fixture_id}"
        profit = odds - 1.0 if won else -1.0
        cumulative_profit += profit
        group_key = str(row.get("match_date") or fixture_id)
        fold_key = f"SEASON:{season}"
        membership: dict[str, object] = {
            "schema_version": MEMBERSHIP_SCHEMA_VERSION,
            "dataset_hash": DATASET_HASH,
            "campaign_result_hash": CAMPAIGN_RESULT_HASH,
            "registry_sha256": REGISTRY_SHA256,
            "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
            "hypothesis_id": hypothesis_identifier,
            "hypothesis_version": "1.0.0",
            "rule_hash": rule.digest,
            "canonical_match_id": canonical_match_id,
            "market": rule.market,
            "selection": rule.selection,
            "price_class": price_class,
            "observed_time_status": str(row["observed_time_status"]),
            "observed_odds": odds,
            "market_margin": margin,
            "stake_units": 1.0,
            "won": won,
            "lost": not won,
            "void": False,
            "gross_return_units": odds if won else 0.0,
            "profit_units": profit,
            "cumulative_profit_units": cumulative_profit,
            "occurrence_index": index,
            "chronological_fold": fold_key,
            "statistical_group": group_key,
            "eligibility_status": "ELIGIBLE_SETTLED",
            "eligibility_reason": (
                "ALL_CONDITIONS_MATCH;OBSERVED_ODDS_ELIGIBLE;"
                "OUTCOME_SETTLED"
            ),
        }
        membership_hash = canonical_sha256(
            {
                **membership,
                "source_row_hash": str(row["_record_hash"]),
                "membership_set_hash": membership_set_hash,
            }
        )
        membership_rows.append(
            {
                **membership,
                "membership_hash": membership_hash,
            }
        )

    teams = {
        str(team)
        for row, _, _, _, _, _ in selected
        for team in (row.get("home_team_id"), row.get("away_team_id"))
        if team not in (None, "")
    }
    competition_scope = _condition_competition(hypothesis)
    confidence_interval = (
        canonical_json([confidence_lower, confidence_upper])
        if confidence_lower is not None and confidence_upper is not None
        else None
    )
    total_return_units = _safe_float(
        financial["total_staked_units"],
        label=f"{rule.digest}.total_staked_units",
    ) + _safe_float(
        financial["profit_units"],
        label=f"{rule.digest}.profit_units",
    )
    summary_core: dict[str, object] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "dataset_hash": DATASET_HASH,
        "campaign_result_hash": CAMPAIGN_RESULT_HASH,
        "registry_sha256": REGISTRY_SHA256,
        "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
        "hypothesis_id": hypothesis_identifier,
        "rule_hash": rule.digest,
        "membership_set_hash": membership_set_hash,
        "market": rule.market,
        "selection": rule.selection,
        "family": "MARKET",
        "competition_scope": competition_scope,
        "condition_count": len(rule.conditions),
        "conditions_json": canonical_json(hypothesis.get("conditions", [])),
        "raw_occurrences": len(raw_matches),
        "occurrences": len(selected),
        "settled_occurrences": _safe_int(
            financial["settled_bets"], label="settled_bets"
        ),
        "settled_bets": _safe_int(
            financial["settled_bets"], label="settled_bets"
        ),
        "wins": _safe_int(financial["wins"], label="wins"),
        "losses": _safe_int(financial["losses"], label="losses"),
        "voids": _safe_int(financial["voids"], label="voids"),
        "hit_rate": financial["hit_rate"],
        "average_odds": financial["average_odds"],
        "median_odds": financial["median_odds"],
        "stake_per_bet": _safe_float(
            financial["stake_per_bet"], label="stake_per_bet"
        ),
        "total_staked_units": _safe_float(
            financial["total_staked_units"], label="total_staked_units"
        ),
        "gross_returns_units": total_return_units,
        "total_return_units": total_return_units,
        "profit_units": _safe_float(
            financial["profit_units"], label="profit_units"
        ),
        "roi": financial["roi"],
        "maximum_drawdown_units": _safe_float(
            financial["max_drawdown_units"], label="max_drawdown_units"
        ),
        "max_drawdown_units": _safe_float(
            financial["max_drawdown_units"], label="max_drawdown_units"
        ),
        "longest_losing_streak": _safe_int(
            financial["max_losing_streak"], label="max_losing_streak"
        ),
        "max_losing_streak": _safe_int(
            financial["max_losing_streak"], label="max_losing_streak"
        ),
        "gross_profit_units": _safe_float(
            financial["gross_profit_units"], label="gross_profit_units"
        ),
        "gross_loss_units": _safe_float(
            financial["gross_loss_units"], label="gross_loss_units"
        ),
        "profit_factor": financial["profit_factor"],
        "confidence_interval": confidence_interval,
        "confidence_lower": confidence_lower,
        "confidence_upper": confidence_upper,
        "confidence_level": confidence_level,
        "bootstrap_groups": bootstrap_groups,
        "eligible_folds": eligible_folds,
        "positive_folds": positive_folds,
        "walk_forward_survived": walk_forward_survived,
        "distinct_seasons": len(set(seasons)),
        "distinct_teams": len(teams),
        "statistical_groups": len(set(groups)),
        "distinct_groups": len(set(groups)),
        "p_value": _safe_float(
            hypothesis.get("p_value", 1.0), label="p_value"
        ),
        "q_value": _safe_float(
            hypothesis.get("q_value", 1.0), label="q_value"
        ),
        "support_sufficient": support_sufficient,
        "hypothesis_status": hypothesis_status,
        "evidence_scope": evidence_scope,
        "reconciled": True,
    }
    summary = {
        **summary_core,
        "summary_hash": canonical_sha256(summary_core),
    }
    return membership_rows, summary, len(raw_matches)


def _fixture_rows(
    historical: LoadedHistoricalMarket,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in historical.rows:
        competition_name = str(row["competition"])
        competition = resolve_competition(competition_name)
        fixture_id = str(row["fixture_id"])
        output.append(
            {
                "schema_version": HISTORICAL_FIXTURE_SCHEMA_VERSION,
                "dataset_hash": DATASET_HASH,
                "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
                "historical_parquet_tree": historical.parquet_tree,
                "source_partition": str(row["__source_partition"]),
                "source_partition_sha256": str(
                    row["__source_partition_sha256"]
                ),
                "record_hash": str(row["_record_hash"]),
                "source_dataset_hash": DATASET_HASH,
                "source_row_hash": str(row["_record_hash"]),
                "canonical_match_id": f"api-football:{fixture_id}",
                "provider_fixture_id": fixture_id,
                "fixture_id": fixture_id,
                "competition_key": competition.canonical_competition_key,
                "competition_name": competition_name,
                "competition": competition_name,
                "season": _safe_int(row["season"], label="fixture.season"),
                "round": None,
                "final_status": "RESULT_RECORDED",
                "match_date": str(row["match_date"]),
                "kickoff_at": str(row["kickoff_at"]),
                "home_team_id": str(row["home_team_id"]),
                "away_team_id": str(row["away_team_id"]),
                "home_team_name": str(row["home_source_name"]),
                "away_team_name": str(row["away_source_name"]),
                "home_source_name": str(row["home_source_name"]),
                "away_source_name": str(row["away_source_name"]),
                "home_goals": _safe_int(
                    row["home_goals"], label="fixture.home_goals"
                ),
                "away_goals": _safe_int(
                    row["away_goals"], label="fixture.away_goals"
                ),
                "odds_home": row.get("odds_home"),
                "odds_draw": row.get("odds_draw"),
                "odds_away": row.get("odds_away"),
                "odds_over_25": row.get("odds_over_25"),
                "odds_under_25": row.get("odds_under_25"),
                "bookmaker_1x2": row.get("bookmaker_1x2"),
                "bookmaker_totals": row.get("bookmaker_totals"),
                "price_type": row.get("price_type"),
                "totals_price_type": row.get("totals_price_type"),
                "observed_time_status": str(row["observed_time_status"]),
                "quality_status": row.get("quality_status"),
                "source": str(row["source"]),
                "raw_payload_hash": row.get("raw_payload_hash"),
                "mapping_status": row.get("mapping_status"),
                "market_margin_1x2": row.get("market_margin_1x2"),
                "market_margin_totals": row.get("market_margin_totals"),
                "de_vig_home": row.get("de_vig_home"),
                "de_vig_draw": row.get("de_vig_draw"),
                "de_vig_away": row.get("de_vig_away"),
                "de_vig_over_25": row.get("de_vig_over_25"),
                "de_vig_under_25": row.get("de_vig_under_25"),
                "quality": row.get("quality"),
            }
        )
    if len({row["canonical_match_id"] for row in output}) != EXPECTED_FIXTURES:
        raise EvidenceFactoryError("CANONICAL_MATCH_ID_NOT_UNIQUE")
    return output


def _batch_checkpoint_entry(
    *,
    batch_index: int,
    rule_hashes: Sequence[str],
    membership_path: Path,
    summary_path: Path,
    raw_memberships: int,
) -> dict[str, object]:
    return {
        "batch_index": batch_index,
        "first_rule_hash": rule_hashes[0],
        "last_rule_hash": rule_hashes[-1],
        "rules": len(rule_hashes),
        "raw_memberships": raw_memberships,
        "strict_memberships": _parquet_rows(membership_path),
        "membership_artifact": membership_path.name,
        "membership_sha256": sha256_file(membership_path),
        "summary_artifact": summary_path.name,
        "summary_sha256": sha256_file(summary_path),
    }


def _validate_completed_batch(
    batch_root: Path,
    entry: Mapping[str, object],
    *,
    expected_index: int,
    expected_rule_hashes: Sequence[str],
) -> None:
    _assert_equal(
        "checkpoint.batch_index",
        _safe_int(entry["batch_index"], label="batch_index"),
        expected_index,
    )
    _assert_equal(
        "checkpoint.rules",
        _safe_int(entry["rules"], label="rules"),
        len(expected_rule_hashes),
    )
    _assert_equal(
        "checkpoint.first_rule_hash",
        entry.get("first_rule_hash"),
        expected_rule_hashes[0],
    )
    _assert_equal(
        "checkpoint.last_rule_hash",
        entry.get("last_rule_hash"),
        expected_rule_hashes[-1],
    )
    membership = batch_root / str(entry["membership_artifact"])
    summary = batch_root / str(entry["summary_artifact"])
    if not membership.is_file() or not summary.is_file():
        raise EvidenceFactoryError("CHECKPOINT_BATCH_ARTIFACT_MISSING")
    if sha256_file(membership) != entry.get("membership_sha256"):
        raise EvidenceFactoryError("CHECKPOINT_MEMBERSHIP_HASH_MISMATCH")
    if sha256_file(summary) != entry.get("summary_sha256"):
        raise EvidenceFactoryError("CHECKPOINT_SUMMARY_HASH_MISMATCH")
    if (
        pq.ParquetFile(membership).schema_arrow
        != HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA
    ):
        raise EvidenceFactoryError("CHECKPOINT_MEMBERSHIP_SCHEMA_MISMATCH")
    if (
        pq.ParquetFile(summary).schema_arrow
        != HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA
    ):
        raise EvidenceFactoryError("CHECKPOINT_SUMMARY_SCHEMA_MISMATCH")
    _assert_equal(
        "checkpoint.membership_rows",
        _parquet_rows(membership),
        _safe_int(entry["strict_memberships"], label="strict_memberships"),
    )
    _assert_equal(
        "checkpoint.summary_rows",
        _parquet_rows(summary),
        _safe_int(entry["rules"], label="rules"),
    )


def _top_row(summary: Mapping[str, object]) -> dict[str, object]:
    return {
        "hypothesis_id": summary["hypothesis_id"],
        "rule_hash": summary["rule_hash"],
        "membership_set_hash": summary["membership_set_hash"],
        "competition": summary["competition_scope"],
        "family": summary["family"],
        "market": summary["market"],
        "selection": summary["selection"],
        "conditions": json.loads(str(summary["conditions_json"])),
        "occurrences": summary["occurrences"],
        "settled_occurrences": summary["settled_occurrences"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "voids": summary["voids"],
        "hit_rate": summary["hit_rate"],
        "average_odds": summary["average_odds"],
        "median_odds": summary["median_odds"],
        "total_staked_units": summary["total_staked_units"],
        "gross_returns_units": summary["gross_returns_units"],
        "profit_units": summary["profit_units"],
        "roi": summary["roi"],
        "maximum_drawdown_units": summary["maximum_drawdown_units"],
        "longest_losing_streak": summary["longest_losing_streak"],
        "eligible_folds": summary["eligible_folds"],
        "positive_folds": summary["positive_folds"],
        "distinct_seasons": summary["distinct_seasons"],
        "distinct_teams": summary["distinct_teams"],
        "statistical_groups": summary["statistical_groups"],
        "confidence_interval": (
            json.loads(str(summary["confidence_interval"]))
            if summary.get("confidence_interval")
            else None
        ),
        "p_value": summary["p_value"],
        "q_value": summary["q_value"],
        "status": summary["hypothesis_status"],
        "evidence_scope": summary["evidence_scope"],
    }


RANKING_CONTRACTS: dict[str, tuple[str, bool]] = {
    "by_roi": ("roi", True),
    "by_profit": ("profit_units", True),
    "by_support": ("occurrences", True),
    "by_hit_rate": ("hit_rate", True),
    "by_lowest_drawdown": ("maximum_drawdown_units", False),
}


def _rank_unique(
    summaries: Sequence[Mapping[str, object]],
    *,
    metric: str,
    descending: bool,
    limit: int = 10,
) -> tuple[list[dict[str, object]], int, int]:
    eligible = [
        item
        for item in summaries
        if item.get("support_sufficient") is True
        and item.get("hypothesis_status")
        == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
        and item.get("walk_forward_survived") is True
        and item.get(metric) is not None
    ]
    eligible.sort(
        key=lambda item: (
            (
                -_safe_float(item[metric], label=metric)
                if descending
                else _safe_float(item[metric], label=metric)
            ),
            str(item["rule_hash"]),
        )
    )
    unique: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for item in eligible:
        key = str(item["membership_set_hash"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return (
        [_top_row(item) for item in unique[:limit]],
        len(unique),
        len(eligible) - len(unique),
    )


def _ranking_scope(
    summaries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for ranking, (metric, descending) in RANKING_CONTRACTS.items():
        rows, available_count, removed = _rank_unique(
            summaries,
            metric=metric,
            descending=descending,
        )
        output[ranking] = {
            "requested_limit": 10,
            "available_count": available_count,
            "complete": available_count >= 10,
            "ordering": [
                f"{metric.upper()}_{'DESC' if descending else 'ASC'}",
                "RULE_HASH_ASC",
            ],
            "duplicate_membership_sets_removed": removed,
            "items": rows,
        }
    return output


def _top_ten_report(
    summaries: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    competitions = sorted(
        {str(item["competition_scope"]) for item in summaries}
    )
    families = sorted({str(item["family"]) for item in summaries})
    by_competition = {
        key: _ranking_scope(
            [
                item
                for item in summaries
                if str(item["competition_scope"]) == key
            ]
        )
        for key in competitions
    }
    by_family = {
        key: _ranking_scope(
            [item for item in summaries if str(item["family"]) == key]
        )
        for key in families
    }
    return {
        "schema_version": "j10-historical-evidence-top-10-v1",
        "source_result_hash": CAMPAIGN_RESULT_HASH,
        "dataset_hash": DATASET_HASH,
        "selection_contract": {
            "support_sufficient": True,
            "campaign_status": "DISCOVERED",
            "walk_forward_survived": True,
            "deduplication": "UNIQUE_MEMBERSHIP_SET_HASH",
            "public_status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
            "rankings": {
                name: {
                    "metric": metric,
                    "direction": "DESC" if descending else "ASC",
                    "tie_break": "RULE_HASH_ASC",
                }
                for name, (metric, descending) in RANKING_CONTRACTS.items()
            },
            "validated_label_forbidden": True,
        },
        "global": _ranking_scope(summaries),
        "by_competition": by_competition,
        "by_family": by_family,
    }


def _top_three_report(
    summaries: Sequence[Mapping[str, object]],
    compact_campaign: Mapping[str, object],
) -> dict[str, object]:
    by_hash = {str(item["rule_hash"]): item for item in summaries}
    compact_top = compact_campaign.get("top_exploratory_walk_forward_results")
    if not isinstance(compact_top, list) or len(compact_top) != 3:
        raise EvidenceFactoryError("COMPACT_TOP_THREE_INVALID")
    output: list[dict[str, object]] = []
    for expected in compact_top:
        if not isinstance(expected, Mapping):
            raise EvidenceFactoryError("COMPACT_TOP_THREE_RECORD_INVALID")
        digest = str(expected["rule_hash"])
        summary = by_hash.get(digest)
        if summary is None or digest not in TOP_RULE_IDS:
            raise EvidenceFactoryError(f"TOP_THREE_RULE_MISSING:{digest}")
        comparisons = {
            "occurrences": "bets",
            "profit_units": "profit_units",
            "roi": "roi",
            "average_odds": "average_odds",
            "hit_rate": "hit_rate",
            "maximum_drawdown_units": "max_drawdown_units",
            "eligible_folds": "walk_forward_eligible_folds",
            "positive_folds": "walk_forward_positive_folds",
            "statistical_groups": "distinct_bootstrap_groups",
            "q_value": "q_value",
        }
        for actual_name, expected_name in comparisons.items():
            actual_value = summary[actual_name]
            expected_value = expected[expected_name]
            if isinstance(expected_value, float):
                _assert_float(
                    f"top3.{digest}.{actual_name}",
                    actual_value,
                    expected_value,
                )
            else:
                _assert_equal(
                    f"top3.{digest}.{actual_name}",
                    actual_value,
                    expected_value,
                )
        interval = json.loads(str(summary["confidence_interval"]))
        expected_interval = expected["bootstrap_roi_95"]
        _assert_float(f"top3.{digest}.ci.lower", interval[0], expected_interval[0])
        _assert_float(f"top3.{digest}.ci.upper", interval[1], expected_interval[1])
        output.append(_top_row(summary))
    _assert_equal(
        "top3.ids",
        [item["hypothesis_id"] for item in output],
        ["J10-M001", "J10-M002", "J10-M003"],
    )
    return {
        "schema_version": "j10-historical-evidence-top-3-v1",
        "source_result_hash": CAMPAIGN_RESULT_HASH,
        "dataset_hash": DATASET_HASH,
        "warning": (
            "Historical exploratory evidence; rejected after multiple testing; "
            "not a prediction of future performance."
        ),
        "items": output,
    }


def _validate_q_values(
    summaries: Sequence[Mapping[str, object]],
    hypotheses: Sequence[Mapping[str, object]],
) -> None:
    p_values = [
        _safe_float(item["p_value"], label="p_value")
        for item in summaries
    ]
    q_values = benjamini_hochberg(p_values, alpha=0.05).q_values
    for summary, hypothesis, q_value in zip(
        summaries,
        hypotheses,
        q_values,
        strict=True,
    ):
        _assert_equal("q.rule_order", summary["rule_hash"], hypothesis["rule_hash"])
        _assert_float(
            f"{summary['rule_hash']}.q_value",
            q_value,
            hypothesis["q_value"],
        )


def _build_fingerprint(
    config: EvidenceBuildConfig,
    historical: LoadedHistoricalMarket,
) -> str:
    return canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "schema_contract_sha256": canonical_sha256(schema_contract()),
            "historical_revision": config.historical_revision,
            "historical_tree": historical.parquet_tree,
            "dataset_hash": historical.dataset_hash,
            "registry_sha256": REGISTRY_SHA256,
            "full_campaign_sha256": FULL_CAMPAIGN_SHA256,
            "compact_campaign_sha256": COMPACT_CAMPAIGN_SHA256,
            "campaign_result_hash": CAMPAIGN_RESULT_HASH,
            "rules": EXPECTED_RULES,
            "batch_size": config.batch_size,
        }
    )


def _artifact_entry(path: Path, *, rows: int) -> dict[str, object]:
    return {
        "name": path.name,
        "rows": rows,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "storage": "ARTIFACT_ONLY_NOT_GIT",
    }


def _validate_membership_uniqueness_streaming(
    paths: Sequence[Path],
) -> int:
    """Prove global uniqueness with memory bounded by one rule membership set."""

    completed_rules: set[str] = set()
    current_rule: str | None = None
    current_matches: set[str] = set()
    total = 0
    for path in paths:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(
            batch_size=32_768,
            columns=["rule_hash", "canonical_match_id"],
        ):
            rule_hashes = batch.column(0).to_pylist()
            match_ids = batch.column(1).to_pylist()
            for raw_rule_hash, raw_match_id in zip(
                rule_hashes,
                match_ids,
                strict=True,
            ):
                rule_hash = str(raw_rule_hash)
                match_id = str(raw_match_id)
                if rule_hash != current_rule:
                    if current_rule is not None:
                        completed_rules.add(current_rule)
                    if rule_hash in completed_rules:
                        raise EvidenceFactoryError(
                            "FINAL_MEMBERSHIP_RULE_NOT_CONTIGUOUS"
                        )
                    current_rule = rule_hash
                    current_matches.clear()
                if match_id in current_matches:
                    raise EvidenceFactoryError("FINAL_MEMBERSHIP_DUPLICATE")
                current_matches.add(match_id)
                total += 1
    return total


def build_hypothesis_evidence(
    config: EvidenceBuildConfig,
) -> EvidenceBuildResult:
    """Build or resume all three normalized Parquet evidence tables."""

    if config.historical_revision != AUTHORITATIVE_HISTORICAL_REVISION:
        raise EvidenceFactoryError("HISTORICAL_REVISION_NOT_AUTHORIZED")
    if config.batch_size < 1 or config.batch_size > 100:
        raise EvidenceFactoryError("EVIDENCE_BATCH_SIZE_OUT_OF_RANGE")
    full_campaign, compact_campaign, registry = _campaign_inputs(config)
    historical = load_frozen_historical_market(
        config.repo_root,
        historical_root=config.historical_root,
        revision=config.historical_revision,
    )
    rules = _rule_catalog(historical.rows, registry)
    fingerprint = _build_fingerprint(config, historical)
    schema_contract_sha256 = canonical_sha256(schema_contract())

    output = config.output_root
    batch_root = output / "_batches"
    checkpoint_path = output / "checkpoint-manifest.json"
    batch_root.mkdir(parents=True, exist_ok=True)
    total_batches = math.ceil(len(rules) / config.batch_size)
    checkpoint: dict[str, Any]
    if checkpoint_path.is_file():
        if not config.resume:
            raise EvidenceFactoryError("CHECKPOINT_EXISTS_RESUME_DISABLED")
        checkpoint = _load_json(checkpoint_path)
        if checkpoint.get("build_fingerprint") != fingerprint:
            raise EvidenceFactoryError("CHECKPOINT_BUILD_FINGERPRINT_MISMATCH")
        if checkpoint.get("schema_contract_sha256") != schema_contract_sha256:
            raise EvidenceFactoryError("CHECKPOINT_SCHEMA_CONTRACT_MISMATCH")
        if int(checkpoint.get("total_batches", -1)) != total_batches:
            raise EvidenceFactoryError("CHECKPOINT_BATCH_COUNT_MISMATCH")
    else:
        checkpoint = {
            "schema_version": "j10-hypothesis-evidence-checkpoint-v1",
            "build_fingerprint": fingerprint,
            "schema_contract_sha256": schema_contract_sha256,
            "status": "IN_PROGRESS",
            "batch_size": config.batch_size,
            "total_batches": total_batches,
            "completed": [],
            "provider_calls": 0,
            "database_writes": 0,
            "r2_operations": 0,
        }
        _write_json(checkpoint_path, checkpoint)

    completed = checkpoint.get("completed")
    if not isinstance(completed, list):
        raise EvidenceFactoryError("CHECKPOINT_COMPLETED_INVALID")
    if len(completed) > total_batches:
        raise EvidenceFactoryError("CHECKPOINT_COMPLETED_EXCEEDS_BATCH_COUNT")
    for expected_index, entry in enumerate(completed):
        if not isinstance(entry, Mapping):
            raise EvidenceFactoryError("CHECKPOINT_ENTRY_INVALID")
        start = expected_index * config.batch_size
        stop = min(start + config.batch_size, len(rules))
        _validate_completed_batch(
            batch_root,
            entry,
            expected_index=expected_index,
            expected_rule_hashes=[
                rule.digest for rule in rules[start:stop]
            ],
        )

    batches_built_this_run = 0
    for batch_index in range(len(completed), total_batches):
        start = batch_index * config.batch_size
        stop = min(start + config.batch_size, len(rules))
        batch_rules = rules[start:stop]
        batch_hypotheses = registry[start:stop]
        membership_rows: list[dict[str, object]] = []
        summary_rows: list[dict[str, object]] = []
        raw_memberships = 0
        for rule, hypothesis in zip(
            batch_rules,
            batch_hypotheses,
            strict=True,
        ):
            memberships, summary, raw_count = _rule_evidence(
                historical.rows,
                rule,
                hypothesis,
            )
            membership_rows.extend(memberships)
            summary_rows.append(summary)
            raw_memberships += raw_count
        membership_path = (
            batch_root / f"membership-batch-{batch_index:05d}.parquet"
        )
        summary_path = batch_root / f"summary-batch-{batch_index:05d}.parquet"
        _write_parquet(
            membership_path,
            membership_rows,
            HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA,
        )
        _write_parquet(
            summary_path,
            summary_rows,
            HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA,
        )
        entry = _batch_checkpoint_entry(
            batch_index=batch_index,
            rule_hashes=[rule.digest for rule in batch_rules],
            membership_path=membership_path,
            summary_path=summary_path,
            raw_memberships=raw_memberships,
        )
        completed.append(entry)
        checkpoint["completed"] = completed
        checkpoint["completed_batches"] = len(completed)
        checkpoint["strict_memberships_completed"] = sum(
            int(item["strict_memberships"]) for item in completed
        )
        checkpoint["raw_memberships_completed"] = sum(
            int(item["raw_memberships"]) for item in completed
        )
        _write_json(checkpoint_path, checkpoint)
        batches_built_this_run += 1
        if (
            config.stop_after_batches is not None
            and batches_built_this_run >= config.stop_after_batches
            and len(completed) < total_batches
        ):
            return EvidenceBuildResult(
                status="INTERRUPTED_RESUMABLE",
                replay_hash=None,
                fixture_rows=0,
                membership_rows=int(
                    checkpoint["strict_memberships_completed"]
                ),
                summary_rows=sum(int(item["rules"]) for item in completed),
                completed_batches=len(completed),
                output_root=output,
            )

    membership_batch_paths = [
        batch_root / str(entry["membership_artifact"])
        for entry in completed
    ]
    summary_batch_paths = [
        batch_root / str(entry["summary_artifact"])
        for entry in completed
    ]
    strict_total = sum(int(entry["strict_memberships"]) for entry in completed)
    raw_total = sum(int(entry["raw_memberships"]) for entry in completed)
    if strict_total != EXPECTED_STRICT_MEMBERSHIPS:
        raise EvidenceFactoryError(
            f"STRICT_MEMBERSHIP_COUNT_MISMATCH:{strict_total}"
        )
    if raw_total != EXPECTED_RAW_MEMBERSHIPS:
        raise EvidenceFactoryError(f"RAW_MEMBERSHIP_COUNT_MISMATCH:{raw_total}")
    if raw_total - strict_total != EXPECTED_RAW_STRICT_DELTA:
        raise EvidenceFactoryError(
            f"RAW_STRICT_DELTA_MISMATCH:{raw_total - strict_total}"
        )

    summary_rows = []
    for path in summary_batch_paths:
        summary_rows.extend(pq.read_table(path).to_pylist())
    if len(summary_rows) != EXPECTED_RULES:
        raise EvidenceFactoryError(
            f"SUMMARY_RULE_COUNT_MISMATCH:{len(summary_rows)}"
        )
    if [str(item["rule_hash"]) for item in summary_rows] != [
        str(item["rule_hash"]) for item in registry
    ]:
        raise EvidenceFactoryError("SUMMARY_RULE_ORDER_MISMATCH")
    _validate_q_values(summary_rows, registry)
    top_three = _top_three_report(summary_rows, compact_campaign)
    top_ten = _top_ten_report(summary_rows)

    fixture_path = output / "historical_fixture_evidence.parquet"
    membership_path = output / "hypothesis_fixture_membership.parquet"
    summary_path = output / "hypothesis_historical_evidence_summary.parquet"
    _write_parquet(
        fixture_path,
        _fixture_rows(historical),
        HISTORICAL_FIXTURE_EVIDENCE_SCHEMA,
    )
    _merge_parquet(
        membership_batch_paths,
        membership_path,
        HYPOTHESIS_FIXTURE_MEMBERSHIP_SCHEMA,
    )
    _merge_parquet(
        summary_batch_paths,
        summary_path,
        HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY_SCHEMA,
    )
    artifact_entries = [
        _artifact_entry(fixture_path, rows=EXPECTED_FIXTURES),
        _artifact_entry(
            membership_path,
            rows=EXPECTED_STRICT_MEMBERSHIPS,
        ),
        _artifact_entry(summary_path, rows=EXPECTED_RULES),
    ]
    unique_memberships = _validate_membership_uniqueness_streaming(
        membership_batch_paths
    )
    if unique_memberships != EXPECTED_STRICT_MEMBERSHIPS:
        raise EvidenceFactoryError(
            f"FINAL_MEMBERSHIP_COUNT_MISMATCH:{unique_memberships}"
        )

    replay_hash = canonical_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "build_fingerprint": fingerprint,
            "artifacts": artifact_entries,
            "batch_hashes": [
                {
                    "membership_sha256": entry["membership_sha256"],
                    "summary_sha256": entry["summary_sha256"],
                }
                for entry in completed
            ],
            "reconciliation": {
                "fixtures": EXPECTED_FIXTURES,
                "rules": EXPECTED_RULES,
                "raw_memberships": raw_total,
                "strict_memberships": strict_total,
                "raw_strict_delta": raw_total - strict_total,
            },
        }
    )
    artifact_manifest = {
        "schema_version": "j10-hypothesis-evidence-artifact-manifest-v1",
        "generated_at": CAMPAIGN_EXECUTED_AT,
        "build_fingerprint": fingerprint,
        "replay_hash": replay_hash,
        "source": {
            "mode": historical.source_mode,
            "authoritative_revision": historical.authoritative_revision,
            "historical_parquet_tree": historical.parquet_tree,
            "byte_identical_replicas": historical.replica_trees,
            "dataset_hash": historical.dataset_hash,
            "registry_sha256": REGISTRY_SHA256,
            "full_campaign_sha256": FULL_CAMPAIGN_SHA256,
            "compact_campaign_sha256": COMPACT_CAMPAIGN_SHA256,
            "campaign_result_hash": CAMPAIGN_RESULT_HASH,
        },
        "artifacts": artifact_entries,
        "checkpoint": {
            "batch_size": config.batch_size,
            "completed_batches": len(completed),
            "total_batches": total_batches,
        },
        "controls": {
            "provider_calls": 0,
            "database_writes": 0,
            "temporary_database_rows": 0,
            "postgresql_rows": 0,
            "r2_operations": 0,
            "network_calls": 0,
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
        },
    }
    _write_json(output / "artifact-manifest.json", artifact_manifest)

    reconciliation = {
        "schema_version": "j10-hypothesis-evidence-reconciliation-v1",
        "generated_at": CAMPAIGN_EXECUTED_AT,
        "status": "RECONCILED",
        "source_result_hash": CAMPAIGN_RESULT_HASH,
        "dataset_hash": DATASET_HASH,
        "checks": {
            "partitions": len(historical.partitions),
            "fixtures": EXPECTED_FIXTURES,
            "unique_fixtures": EXPECTED_FIXTURES,
            "rules": EXPECTED_RULES,
            "summaries_reconciled": EXPECTED_RULES,
            "raw_memberships": raw_total,
            "strict_memberships": strict_total,
            "raw_strict_delta": raw_total - strict_total,
            "duplicate_rule_canonical_match": 0,
            "top_three_exact": True,
            "q_values_recomputed": True,
            "provider_calls": 0,
            "database_writes": 0,
            "temporary_database_rows": 0,
            "postgresql_rows": 0,
            "r2_operations": 0,
        },
        "summary_hashes_sha256": canonical_sha256(
            [item["summary_hash"] for item in summary_rows]
        ),
        "replay_hash": replay_hash,
    }
    source_provenance = {
        "schema_version": "j10-hypothesis-evidence-source-v1",
        "logical_campaign_source": {
            "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
            "historical_parquet_tree": historical.parquet_tree,
            "dataset_hash": DATASET_HASH,
        },
        "byte_identical_replicas_not_logical_sources": historical.replica_trees,
        "partitions": [asdict(item) for item in historical.partitions],
        "price_time_contract": {
            "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
            "exact_intraday_timestamp": False,
            "point_in_time_claim": False,
        },
    }
    artifact_hash_report = {
        "schema_version": "j10-hypothesis-evidence-artifact-hashes-v1",
        "replay_hash": replay_hash,
        "artifacts": artifact_entries,
        "git_policy": "COMPACT_REPORTS_SCHEMAS_HASHES_TOPS_ONLY",
        "detailed_storage": "ARTIFACT_ONLY;R2_INDEXABLE;NOT_POSTGRES_PAYLOAD",
    }
    report_root = config.report_root
    if report_root is not None:
        _write_json(report_root / "schema-contract.json", schema_contract())
        _write_json(report_root / "source-provenance.json", source_provenance)
        _write_json(report_root / "artifact-hashes.json", artifact_hash_report)
        _write_json(report_root / "reconciliation.json", reconciliation)
        _write_json(report_root / "top-10.json", top_ten)
        _write_json(report_root / "top-3.json", top_three)

    checkpoint["status"] = "COMPLETE"
    checkpoint["replay_hash"] = replay_hash
    checkpoint["artifacts"] = artifact_entries
    _write_json(checkpoint_path, checkpoint)
    return EvidenceBuildResult(
        status="COMPLETE",
        replay_hash=replay_hash,
        fixture_rows=EXPECTED_FIXTURES,
        membership_rows=EXPECTED_STRICT_MEMBERSHIPS,
        summary_rows=EXPECTED_RULES,
        completed_batches=len(completed),
        output_root=output,
    )
