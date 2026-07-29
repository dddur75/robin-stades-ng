"""Import, canonical grouping and transparent ranking for Jalon 10."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from robin.deep_football.matchups import owner_hypotheses
from robin.hypothesis_intelligence.contracts import (
    HypothesisOrigin,
    HypothesisRecord,
    HypothesisStatus,
    canonical_sha256,
)

J10_EXPECTED_RULES = 700
J10_REGISTRY_SHA256 = "cb928f00340f64893e90cc40aaed9bd4ba22e4ef39d59e5f66994dd79331d731"
J10_RESULT_HASH = "edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b"
J10_TOP_IDS = {
    "293f3a6d5e635389abc272e8b6579b5e95df58836cd2e1355737df96c52f4867": "J10-M001",
    "a82c917853baf22ec85eea189eb2efde72022b0271e1e0eadffb2f851d0623a2": "J10-M002",
    "561b8a16908ab9bb8cb477c77af343779d20485d959b40ea7ed2a2e60535ec20": "J10-M003",
}
RANKING_VERSION = "hypothesis-exploratory-priority-v1"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _condition_value(
    conditions: Iterable[dict[str, object]],
    feature: str,
) -> object | None:
    return next(
        (item.get("value") for item in conditions if item.get("feature") == feature),
        None,
    )


def canonical_rule_fingerprint(
    *,
    market: str,
    selection: str,
    competition: str,
    conditions: Iterable[dict[str, object]],
    cutoff: str,
) -> str:
    conditions_list = list(conditions)
    odds_band = next(
        (
            item.get("value")
            for item in conditions_list
            if str(item.get("feature", "")).startswith("odds_")
        ),
        None,
    )
    margin = next(
        (item.get("value") for item in conditions_list if "margin" in str(item.get("feature", ""))),
        None,
    )
    return canonical_sha256(
        {
            "market": market,
            "selection": selection,
            "competition": competition,
            "odds_band": odds_band,
            "margin": margin,
            "conditions": sorted(
                conditions_list,
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
            "cutoff": cutoff,
        }
    )


def _title(market: str, selection: str, competition: str) -> str:
    labels = {
        "HOME": "victoire à domicile",
        "DRAW": "match nul",
        "AWAY": "victoire à l’extérieur",
        "OVER": "plus de 2,5 buts",
        "UNDER": "moins de 2,5 buts",
    }
    return f"{labels.get(selection, selection)} · {competition or 'toutes ligues'}"


def import_j10_registry(
    raw_rules: Iterable[dict[str, Any]],
    campaign: dict[str, Any],
) -> tuple[HypothesisRecord, ...]:
    rules = list(raw_rules)
    if len(rules) != J10_EXPECTED_RULES:
        raise ValueError(f"J10_RULE_COUNT_MISMATCH:{len(rules)}")
    if campaign.get("result_hash") != J10_RESULT_HASH:
        raise ValueError("J10_RESULT_HASH_MISMATCH")
    created_at = datetime.fromisoformat(
        str(campaign["executed_at"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    dataset_hashes = campaign.get("dataset_hashes", [])
    discovery_dataset = str(dataset_hashes[0]) if dataset_hashes else ""
    negative_controls = tuple(sorted(str(key) for key in campaign.get("negative_controls", {})))
    output: list[HypothesisRecord] = []
    for raw in rules:
        rule_hash = str(raw["rule_hash"])
        conditions = tuple(dict(item) for item in raw.get("conditions", []))
        competition = str(_condition_value(conditions, "competition") or "ALL_AVAILABLE")
        market = str(raw["market"])
        selection = str(raw["selection"])
        support = dict(raw.get("support") or {})
        metrics = dict(raw.get("metrics") or {})
        bootstrap = dict(raw.get("bootstrap") or {})
        walk_forward = dict(raw.get("walk_forward") or {})
        stability = dict(raw.get("exposed_league_stability") or {})
        concentration = dict(raw.get("concentration") or {})
        cutoff = str(
            campaign.get("configuration", {}).get(
                "feature_cutoff",
                "HISTORICAL_PRICE_CATEGORY_NO_EXACT_CUTOFF",
            )
        )
        fingerprint = canonical_rule_fingerprint(
            market=market,
            selection=selection,
            competition=competition,
            conditions=conditions,
            cutoff=cutoff,
        )
        top_id = J10_TOP_IDS.get(rule_hash)
        status = (
            HypothesisStatus.DATA_GATE_BLOCKED
            if raw.get("status") == "INSUFFICIENT_SUPPORT"
            else HypothesisStatus.EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING
        )
        status_reason = (
            "INSUFFICIENT_HISTORICAL_SUPPORT"
            if status is HypothesisStatus.DATA_GATE_BLOCKED
            else "Q_VALUE_ABOVE_FROZEN_FDR_ALPHA;NO_LIVE_POINT_IN_TIME_VALIDATION"
        )
        odds_condition = next(
            (item for item in conditions if str(item.get("feature", "")).startswith("odds_")),
            {},
        )
        margin_condition = next(
            (item for item in conditions if "margin" in str(item.get("feature", ""))),
            {},
        )
        output.append(
            HypothesisRecord(
                hypothesis_id=top_id or f"J10-{rule_hash[:16].upper()}",
                hypothesis_version="1.0.0",
                origin=HypothesisOrigin.MACHINE_DISCOVERED,
                title=_title(market, selection, competition),
                description=(
                    "Signal extrait automatiquement de la campagne Jalon 10. "
                    "Le résultat historique ne prédit aucune performance future."
                ),
                mechanism="Règle de marché exploratoire; mécanisme causal non établi.",
                family=f"{market}:{selection}",
                competition_scope=(competition,),
                market=market,
                selection=selection,
                conditions=conditions,
                price_contract={
                    "historical_source": "FOOTBALL_DATA",
                    "historical_price_class": "CLOSING_OR_PRE_CLOSING",
                    "exact_observed_at": False,
                    "odds_band": odds_condition.get("value"),
                    "maximum_margin": margin_condition.get("value"),
                    "cutoff": cutoff,
                },
                discovery_dataset=discovery_dataset,
                discovery_run_id=str(campaign["campaign_id"]),
                discovery_code_revision=str(campaign["code_revision"]),
                discovery_timestamp=created_at,
                historical_support=int(support.get("observations", 0)),
                historical_profit=(float(metrics["profit_units"]) if metrics else None),
                historical_roi=float(metrics["roi"]) if metrics else None,
                historical_confidence_interval=(
                    (float(bootstrap["lower"]), float(bootstrap["upper"])) if bootstrap else None
                ),
                historical_p_value=float(raw.get("p_value", 1.0)),
                historical_q_value=float(raw.get("q_value", 1.0)),
                historical_walk_forward=walk_forward,
                historical_drawdown=(float(metrics["max_drawdown_units"]) if metrics else None),
                historical_cross_league_stability=stability,
                team_concentration=concentration,
                time_concentration={
                    "distinct_seasons": concentration.get("distinct_seasons"),
                    "measured": bool(concentration),
                },
                negative_controls=negative_controls,
                required_data_gates=("PROSPECTIVE_MARKET_GATE",),
                current_data_gates={"PROSPECTIVE_MARKET_GATE": "WAITING_FOR_DUE_CUTOFF"},
                status=status,
                status_reason=status_reason,
                preregistered_at=None,
                preregistration_hash=None,
                prospective_start_at=None,
                minimum_prospective_support=80 if top_id else 0,
                promotion_locked=True,
                created_at=created_at,
                supersedes=None,
                rule_hash=rule_hash,
                canonical_fingerprint=fingerprint,
            )
        )
    if len({item.rule_hash for item in output}) != J10_EXPECTED_RULES:
        raise ValueError("J10_DUPLICATE_RULE_HASH")
    if len({item.canonical_fingerprint for item in output}) != J10_EXPECTED_RULES:
        raise ValueError("J10_DUPLICATE_CANONICAL_RULE")
    return tuple(output)


def owner_registry() -> tuple[HypothesisRecord, ...]:
    created_at = datetime(2026, 7, 27, tzinfo=UTC)
    records: list[HypothesisRecord] = []
    for contract in owner_hypotheses():
        conditions: tuple[dict[str, object], ...] = (
            {
                "feature": "required_gates",
                "operator": "ALL_READY",
                "value": list(contract.required_gates),
                "available_at": contract.cutoff,
                "source": "H11_OWNER_PROTOCOL",
            },
        )
        rule_hash = contract.preregistration_hash
        records.append(
            HypothesisRecord(
                hypothesis_id=contract.hypothesis_id,
                hypothesis_version="1.0.0",
                origin=HypothesisOrigin.OWNER_PROPOSED,
                title=contract.title,
                description="Hypothèse humaine préenregistrée proposée par David.",
                mechanism=contract.mechanism,
                family=contract.statistical_family,
                competition_scope=("FIVE_LEAGUES",),
                market="MULTI_MARKET",
                selection="PREREGISTERED_DIRECTION",
                conditions=conditions,
                price_contract={"cutoff": contract.cutoff},
                discovery_dataset="OWNER_PROTOCOL_NO_MACHINE_DISCOVERY",
                discovery_run_id="JALON_11_OWNER_HYPOTHESES",
                discovery_code_revision="JALON_11",
                discovery_timestamp=created_at,
                historical_support=0,
                historical_profit=None,
                historical_roi=None,
                historical_confidence_interval=None,
                historical_p_value=None,
                historical_q_value=None,
                historical_walk_forward={},
                historical_drawdown=None,
                historical_cross_league_stability={},
                team_concentration={},
                time_concentration={},
                negative_controls=(contract.negative_control,),
                required_data_gates=tuple(contract.required_gates),
                current_data_gates={gate: "DATA_GATE_BLOCKED" for gate in contract.required_gates},
                status=HypothesisStatus.DATA_GATE_BLOCKED,
                status_reason="REQUIRED_PROSPECTIVE_DATA_GATES_NOT_READY",
                preregistered_at=created_at,
                preregistration_hash=contract.preregistration_hash,
                prospective_start_at=None,
                minimum_prospective_support=contract.minimum_support,
                promotion_locked=True,
                created_at=created_at,
                supersedes=None,
                rule_hash=rule_hash,
                canonical_fingerprint=canonical_rule_fingerprint(
                    market="MULTI_MARKET",
                    selection="PREREGISTERED_DIRECTION",
                    competition="FIVE_LEAGUES",
                    conditions=conditions,
                    cutoff=contract.cutoff,
                ),
            )
        )
    return tuple(records)


@dataclass(frozen=True, slots=True)
class Ranking:
    hypothesis_id: str
    raw_roi_rank: int
    support_rank: int
    uncertainty_rank: int
    walk_forward_rank: int
    drawdown_rank: int
    stability_rank: int
    concentration_risk: float
    replicability_rank: int
    live_observability_rank: int
    overall_exploratory_priority: float
    ranking_version: str = RANKING_VERSION


def _rank(
    records: tuple[HypothesisRecord, ...],
    value: Any,
    *,
    reverse: bool,
) -> dict[str, int]:
    ordered = sorted(
        records,
        key=lambda item: (value(item), item.hypothesis_id),
        reverse=reverse,
    )
    return {item.hypothesis_id: index + 1 for index, item in enumerate(ordered)}


def rank_hypotheses(
    records: tuple[HypothesisRecord, ...],
) -> tuple[Ranking, ...]:
    eligible = tuple(item for item in records if item.historical_roi is not None)
    roi = _rank(eligible, lambda item: item.historical_roi or -1e9, reverse=True)
    support = _rank(eligible, lambda item: item.historical_support, reverse=True)
    uncertainty = _rank(
        eligible,
        lambda item: (
            (item.historical_confidence_interval[1] - item.historical_confidence_interval[0])
            if item.historical_confidence_interval
            else 1e9
        ),
        reverse=False,
    )
    walk = _rank(
        eligible,
        lambda item: float(item.historical_walk_forward.get("positive_ratio", 0)),
        reverse=True,
    )
    drawdown = _rank(
        eligible,
        lambda item: item.historical_drawdown or 1e9,
        reverse=False,
    )
    stability = _rank(
        eligible,
        lambda item: int(item.historical_cross_league_stability.get("survived") is True),
        reverse=True,
    )
    live = _rank(
        eligible,
        lambda item: int(item.price_contract.get("exact_observed_at") is True),
        reverse=True,
    )
    count = max(1, len(eligible))
    output: list[Ranking] = []
    for item in eligible:
        concentration_risk = (
            1.0
            if item.team_concentration and item.team_concentration.get("passed") is not True
            else 0.0
        )
        q_penalty = 1.0 if (item.historical_q_value or 1.0) > 0.05 else 0.0
        complexity_penalty = min(len(item.conditions) / 4, 1.0)

        def normalized(rank: int) -> float:
            return 1 - ((rank - 1) / count)

        priority = 100 * (
            0.16 * normalized(roi[item.hypothesis_id])
            + 0.16 * normalized(support[item.hypothesis_id])
            + 0.13 * normalized(uncertainty[item.hypothesis_id])
            + 0.13 * normalized(walk[item.hypothesis_id])
            + 0.10 * normalized(drawdown[item.hypothesis_id])
            + 0.10 * normalized(stability[item.hypothesis_id])
            + 0.10 * normalized(live[item.hypothesis_id])
            + 0.06 * (1 - concentration_risk)
            + 0.03 * (1 - q_penalty)
            + 0.03 * (1 - complexity_penalty)
        )
        output.append(
            Ranking(
                hypothesis_id=item.hypothesis_id,
                raw_roi_rank=roi[item.hypothesis_id],
                support_rank=support[item.hypothesis_id],
                uncertainty_rank=uncertainty[item.hypothesis_id],
                walk_forward_rank=walk[item.hypothesis_id],
                drawdown_rank=drawdown[item.hypothesis_id],
                stability_rank=stability[item.hypothesis_id],
                concentration_risk=concentration_risk,
                replicability_rank=live[item.hypothesis_id],
                live_observability_rank=live[item.hypothesis_id],
                overall_exploratory_priority=round(priority, 6),
            )
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                -item.overall_exploratory_priority,
                item.hypothesis_id,
            ),
        )
    )


def registry_counts(records: Iterable[HypothesisRecord]) -> dict[str, object]:
    items = tuple(records)
    return {
        "total": len(items),
        "origins": dict(Counter(item.origin.value for item in items)),
        "statuses": dict(Counter(item.status.value for item in items)),
        "families": len({item.family for item in items}),
        "canonical_rules": len({item.canonical_fingerprint for item in items}),
        "duplicates": len(items) - len({item.rule_hash for item in items}),
    }


__all__ = [
    "J10_EXPECTED_RULES",
    "J10_REGISTRY_SHA256",
    "J10_RESULT_HASH",
    "J10_TOP_IDS",
    "RANKING_VERSION",
    "Ranking",
    "canonical_rule_fingerprint",
    "import_j10_registry",
    "load_jsonl",
    "owner_registry",
    "rank_hypotheses",
    "registry_counts",
]
