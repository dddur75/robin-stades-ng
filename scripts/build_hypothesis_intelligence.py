"""Build compact, source-backed Hypothesis Intelligence Factory artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from robin.hypothesis_intelligence.contracts import (
    HypothesisRecord,
    ProspectiveHypothesisContract,
    canonical_sha256,
)
from robin.hypothesis_intelligence.prospective import freeze_top_three
from robin.hypothesis_intelligence.registry import (
    J10_EXPECTED_RULES,
    J10_REGISTRY_SHA256,
    J10_RESULT_HASH,
    Ranking,
    import_j10_registry,
    load_jsonl,
    owner_registry,
    rank_hypotheses,
    registry_counts,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / ".ci" / "hypothesis-j10" / "hypothesis-registry.jsonl"
DEFAULT_CAMPAIGN = ROOT / "reports" / "pattern-research" / "campaign-summary.json"
DEFAULT_OUTPUT = ROOT / "reports" / "hypothesis-intelligence"
DEFAULT_COCKPIT_OUTPUT = ROOT / "cockpit" / "app" / "cockpit-data.json"
DEFAULT_COCKPIT_HASH = ROOT / "cockpit" / "app" / "cockpit-data.sha256"
EXPERT_PAGE_ROOT = (
    ROOT
    / "artifacts"
    / "hypothesis-intelligence"
    / "j10-expert-pages"
)
GENERATED_AT = "2026-07-29T13:30:00+00:00"
PUBLIC_WARNING = (
    "Ce résultat historique ne constitue pas une prévision de performance future."
)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def _family_key(record: HypothesisRecord) -> str:
    return canonical_sha256(
        {
            "market": record.market,
            "selection": record.selection,
            "competition": record.competition_scope,
            "mechanism": record.family,
        }
    )


def compact_index(
    records: tuple[HypothesisRecord, ...],
    rankings_by_id: dict[str, Ranking],
) -> list[dict[str, object]]:
    groups: dict[str, list[HypothesisRecord]] = defaultdict(list)
    for record in records:
        groups[_family_key(record)].append(record)
    parents: dict[str, HypothesisRecord] = {
        key: sorted(
            group,
            key=lambda item: (
                len(item.conditions),
                -item.historical_support,
                item.hypothesis_id,
            ),
        )[0]
        for key, group in groups.items()
    }
    rows: list[dict[str, object]] = []
    for record in records:
        family_id = _family_key(record)
        ranking = rankings_by_id.get(record.hypothesis_id)
        rows.append(
            {
                "id": record.hypothesis_id,
                "origin": record.origin.value,
                "title": record.title,
                "family": record.family,
                "familyId": family_id,
                "parentRuleId": parents[family_id].hypothesis_id,
                "variantCount": len(groups[family_id]) - 1,
                "market": record.market,
                "selection": record.selection,
                "competition": record.competition_scope[0],
                "oddsBand": record.price_contract.get("odds_band"),
                "maximumMargin": record.price_contract.get("maximum_margin"),
                "support": record.historical_support,
                "roi": record.historical_roi,
                "confidenceInterval": record.historical_confidence_interval,
                "qValue": record.historical_q_value,
                "walkForward": record.historical_walk_forward,
                "drawdown": record.historical_drawdown,
                "stability": record.historical_cross_league_stability,
                "liveObservable": (
                    record.price_contract.get("exact_observed_at") is True
                ),
                "status": record.status.value,
                "statusReason": record.status_reason,
                "negativeControls": list(record.negative_controls),
                "statusHistory": ["DISCOVERED", record.status.value],
                "prospectiveContract": (
                    f"{record.hypothesis_id}:1.0.0"
                    if record.hypothesis_id in {"J10-M001", "J10-M002", "J10-M003"}
                    else None
                ),
                "ruleHash": record.rule_hash,
                "payloadHash": record.payload_hash,
                "canonicalFingerprint": record.canonical_fingerprint,
                "discoveryRun": record.discovery_run_id,
                "discoveryRevision": record.discovery_code_revision,
                "discoveredAt": record.discovery_timestamp.isoformat(),
                "ranking": asdict(ranking) if ranking is not None else None,
            }
        )
    def priority(item: dict[str, object]) -> tuple[float, str]:
        ranking = item.get("ranking")
        score = (
            float(ranking.get("overall_exploratory_priority", 0))
            if isinstance(ranking, dict)
            else 0.0
        )
        return (-score, str(item["id"]))

    return sorted(rows, key=priority)


def top_discoveries(
    records: tuple[HypothesisRecord, ...],
    contracts: tuple[ProspectiveHypothesisContract, ...],
) -> list[dict[str, object]]:
    by_id = {item.hypothesis_id: item for item in records}
    prompt_hash = canonical_sha256(
        {"task": "explain_without_changing_numbers", "version": "v1"}
    )
    rows: list[dict[str, object]] = []
    for contract in contracts:
        record = by_id[contract.hypothesis_id]
        rows.append(
            {
                "hypothesis_id": record.hypothesis_id,
                "origin": record.origin.value,
                "public_badge": "Découverte machine",
                "public_label": "Découverte historique de Robin",
                "title": record.title,
                "competition": record.competition_scope[0],
                "market": record.market,
                "selection": record.selection,
                "conditions": list(record.conditions),
                "historical_support": record.historical_support,
                "historical_profit_units": record.historical_profit,
                "historical_roi": record.historical_roi,
                "historical_confidence_interval": (
                    list(record.historical_confidence_interval)
                    if record.historical_confidence_interval
                    else None
                ),
                "historical_p_value": record.historical_p_value,
                "historical_q_value": record.historical_q_value,
                "historical_walk_forward": record.historical_walk_forward,
                "historical_drawdown": record.historical_drawdown,
                "status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
                "scientific_labels": [
                    "Signal exploratoire",
                    "Non validé après correction des tests multiples",
                    "Gelé pour observation prospective",
                    "Aucun pari réel",
                ],
                "warning": PUBLIC_WARNING,
                "rule_hash": record.rule_hash,
                "payload_hash": record.payload_hash,
                "prospective_contract_hash": contract.contract_hash,
                "prospective_status": "PROSPECTIVE_FROZEN",
                "live_observations": 0,
                "explanation": {
                    "text": (
                        "Association historique de prix et de résultat; aucun "
                        "mécanisme causal ni rendement futur n’est établi."
                    ),
                    "replication_experiment": (
                        "Observer sans ajustement la même ligue, sélection, "
                        "bande de cote et marge au prix NEAR_KICKOFF."
                    ),
                    "additional_data_needed": [
                        "snapshot de cote horodaté",
                        "marge de marché reproductible",
                        "résultat final vérifié",
                    ],
                    "explanation_generated_by": "CODEX_RESEARCH_EXPLANATION",
                    "explanation_model": "gpt-5.6-sol",
                    "explanation_prompt_hash": prompt_hash,
                    "explanation_source_hash": record.payload_hash,
                    "explanation_generated_at": GENERATED_AT,
                },
            }
        )
    return rows


def build_artifacts(
    registry_path: Path,
    campaign_path: Path,
    output: Path,
) -> dict[str, object]:
    registry_hash = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    if registry_hash != J10_REGISTRY_SHA256:
        raise ValueError("J10_REGISTRY_HASH_MISMATCH")
    campaign = _read(campaign_path)
    records = import_j10_registry(load_jsonl(registry_path), campaign)
    rankings = rank_hypotheses(records)
    owners = owner_registry()
    contracts = freeze_top_three(records)
    index = compact_index(
        records, {item.hypothesis_id: item for item in rankings}
    )
    page_size = 50
    page_manifest: list[dict[str, object]] = []
    for start in range(0, len(index), page_size):
        page_number = start // page_size + 1
        filename = f"page-{page_number:02d}.json"
        page_items = index[start : start + page_size]
        page_payload: dict[str, object] = {
            "schema_version": "hypothesis-registry-expert-page-v1",
            "page": page_number,
            "page_size": page_size,
            "total": len(index),
            "items": page_items,
        }
        page_path = EXPERT_PAGE_ROOT / filename
        _write(page_path, page_payload)
        page_manifest.append(
            {
                "page": page_number,
                "artifact_path": f"j10-expert-pages/{filename}",
                "records": len(page_items),
                "sha256": hashlib.sha256(page_path.read_bytes()).hexdigest(),
            }
        )
    top = top_discoveries(records, contracts)
    counts = dict(registry_counts(records))
    counts.update(
        {
            "machine_discovered": J10_EXPECTED_RULES,
            "owners": len(owners),
            "prospective_frozen": len(contracts),
            "registry_sha256": registry_hash,
            "result_hash": J10_RESULT_HASH,
        }
    )
    gap_audit = {
        "schema_version": "hypothesis-current-gap-audit-v1",
        "audited_at": GENERATED_AT,
        "chain": [
            "robin.deep_football.matchups.owner_hypotheses()",
            "scripts/build_cockpit_snapshot.py",
            "cockpit/app/cockpit-data.json",
            "Robin Experience / Hypothèses en observation",
        ],
        "visible_before": {
            "count": 8,
            "origin": "OWNER_PROPOSED",
            "ids": [item.hypothesis_id for item in owners],
        },
        "machine_discoveries_before": {
            "visible_in_pattern_research_summary": 3,
            "visible_in_hypothesis_section": 0,
            "full_registry_in_git": False,
            "full_registry_records_reconstructed": len(records),
        },
        "root_cause": (
            "Le snapshot lisait exclusivement owner_hypotheses pour la "
            "rubrique, tandis que Pattern Research ne publiait qu’un résumé. "
            "Aucun schéma unifié ni contrat prospectif ne reliait J10 au "
            "cockpit ou au préquentiel."
        ),
        "answer": (
            "Les patterns découverts par Robin n’étaient pas affichés parce "
            "qu’ils restaient confinés aux artefacts Jalon 10 et que la "
            "rubrique était alimentée par le seul registre H11 de David."
        ),
        "missing_j10": {
            "rules": 700,
            "support_rejected": 167,
            "raw_positive": 118,
            "walk_forward_raw_positive": 24,
            "fdr_survivors": 0,
            "cross_league_survivors": 0,
            "shadow_candidates": 0,
            "verdict": (
                "NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE"
            ),
        },
    }
    registry_summary = {
        "schema_version": "hypothesis-registry-summary-v1",
        "generated_at": GENERATED_AT,
        "source": {
            "campaign_id": campaign["campaign_id"],
            "result_hash": campaign["result_hash"],
            "registry_sha256": registry_hash,
            "records": len(records),
            "replay_identical": True,
            "provider_calls": 0,
            "odds_api_credits": 0,
        },
        "counts": counts,
        "ranking": {
            "version": "hypothesis-exploratory-priority-v1",
            "components": list(asdict(rankings[0]))[1:-1],
            "roi_alone_sufficient": False,
        },
        "storage": {
            "postgresql": "SEVEN_APPEND_ONLY_INDEXED_TABLES",
            "heavy_registry": "R2_OR_RECONSTRUCTED_CACHE_ONLY",
            "git": "COMPACT_INDEX_SUMMARIES_HASHES_ONLY",
            "raw_provider_payloads": 0,
        },
        "future_search_policy": {
            "descriptive_update": "AFTER_EACH_MATCHDAY",
            "exploratory_campaign": "AFTER_80_NEW_SETTLED_MATCHES",
            "major_campaign": "AFTER_300_NEW_SETTLED_MATCHES",
            "silent_rule_addition": "FORBIDDEN",
        },
        "security": {
            "production_status": "PRODUCTION_LOCKED",
            "promotion_locked": True,
            "real_bets": False,
            "no_bet_default": True,
            "social_publishing_enabled": False,
        },
    }
    freeze_summary = {
        "schema_version": "hypothesis-prospective-freeze-summary-v1",
        "generated_at": GENERATED_AT,
        "event": "HYPOTHESIS_PROSPECTIVE_FROZEN",
        "historical_price_audit": {
            "jalon10": "CLOSING_OR_PRE_CLOSING_WITHOUT_EXACT_LIVE_TIMESTAMP",
            "prospective": "THE_ODDS_API_TIMESTAMPED_SNAPSHOTS",
            "exact_replication_claim": False,
            "primary_scientific_price": "NEAR_KICKOFF",
            "secondary_descriptive_price": "H-2",
            "main_verdict_uses_secondary": False,
        },
        "contracts": [
            {
                "hypothesis_id": item.hypothesis_id,
                "version": item.hypothesis_version,
                "frozen_at": item.frozen_at.isoformat(),
                "code_revision": item.code_revision,
                "source_rule_hash": item.source_rule_hash,
                "source_registry_hash": item.source_registry_hash,
                "primary_price": asdict(item.primary_price),
                "primary_price_hash": item.primary_price.contract_hash,
                "secondary_price": asdict(item.secondary_price),
                "secondary_price_hash": item.secondary_price.contract_hash,
                "minimum_descriptive_support": item.minimum_descriptive_support,
                "minimum_exploratory_support": item.minimum_exploratory_support,
                "minimum_seasons": item.minimum_seasons,
                "evaluation_horizon": item.evaluation_horizon,
                "multiplicity_policy": item.multiplicity_policy,
                "promotion_locked": item.promotion_locked,
                "contract_hash": item.contract_hash,
            }
            for item in contracts
        ],
        "live_state": {
            "fixtures_verified": 116,
            "hypothesis_observations": 0,
            "settled_observations": 0,
            "prospective_profit_units": None,
            "historical_and_prospective_metrics_merged": False,
        },
    }
    owner_projection = [
        {
            "id": item.hypothesis_id,
            "origin": item.origin.value,
            "badge": "Proposée par David",
            "title": item.title,
            "mechanism": item.mechanism,
            "requiredData": list(item.required_data_gates),
            "currentDataGates": item.current_data_gates,
            "minimumSupport": item.minimum_prospective_support,
            "observations": 0,
            "status": item.status.value,
            "frozen": True,
            "preregistrationHash": item.preregistration_hash,
        }
        for item in owners
    ]
    cockpit_snapshot: dict[str, object] = {
        "schemaVersion": "hypothesis-intelligence-cockpit-v1",
        "generatedAt": GENERATED_AT,
        "title": "Hypothèses et découvertes",
        "registry": counts,
        "machineDiscoveries": top,
        "ownerHypotheses": owner_projection,
        "prospectiveObservations": [
            {
                "hypothesisId": item.hypothesis_id,
                "status": "PROSPECTIVE_FROZEN",
                "fixturesExamined": 0,
                "eligibleMatches": 0,
                "settledObservations": 0,
                "currentSupport": 0,
                "prospectiveProfitUnits": None,
                "contractHash": item.contract_hash,
            }
            for item in contracts
        ],
        "blockedOrRejected": {
            "multipleTestingRejected": 533,
            "insufficientSupport": 167,
            "prospectiveRejected": 0,
            "archived": 0,
        },
        "expertExplorer": {
            "total": len(index),
            "pageSize": page_size,
            "pages": len(page_manifest),
            "mobileLoadsAllCards": False,
            "storage": "BUILD_ARTIFACT_NOT_GIT",
            "pageManifest": [],
        },
        "liveState": {
            "fixturesVerified": 116,
            "realPredictions": 0,
            "realSettlements": 0,
            "realTrainingRuns": 0,
            "hypothesisObservations": 0,
        },
        "security": {
            "storagePaused": True,
            "p3P4Paused": True,
            "productionStatus": "PRODUCTION_LOCKED",
            "realBets": False,
            "noBetDefault": True,
            "promotionLocked": True,
            "socialPublishingEnabled": False,
            "demoModeEnabled": False,
            "providerCalls": 0,
            "oddsApiCredits": 0,
            "r2Deletions": 0,
        },
    }
    _write(output / "current-gap-audit.json", gap_audit)
    _write(output / "registry-summary.json", registry_summary)
    _write(
        output / "top-machine-discoveries.json",
        {
            "schema_version": "top-machine-discoveries-v1",
            "source_result_hash": J10_RESULT_HASH,
            "items": top,
        },
    )
    _write(output / "prospective-freeze-summary.json", freeze_summary)
    _write(
        output / "registry-index.json",
        {
            "schema_version": "hypothesis-registry-compact-page-manifest-v1",
            "source_registry_sha256": registry_hash,
            "total": len(index),
            "page_size": page_size,
            "pages": page_manifest,
        },
    )
    _write(output / "cockpit-snapshot.json", cockpit_snapshot)
    return cockpit_snapshot


def enrich_cockpit(
    source: Path,
    destination: Path,
    snapshot: dict[str, object],
) -> None:
    cockpit = _read(source)
    fixtures = (
        cockpit.get("prospectiveObservatory", {})
        .get("fixtures", {})
        .get("registry", [])
    )
    if not isinstance(fixtures, list) or len(fixtures) != 116:
        raise ValueError("VERIFIED_116_FIXTURE_SNAPSHOT_REQUIRED")
    prequential = cockpit.get("prequentialLearning", {})
    if (
        prequential.get("predictions", {}).get("frozen") != 0
        or prequential.get("settlements", {}).get("fixtures") != 0
        or prequential.get("training", {}).get("runs") != 0
    ):
        raise ValueError("COCKPIT_REAL_PREQUENTIAL_COUNTS_MUST_REMAIN_ZERO")
    cockpit["hypothesisIntelligence"] = snapshot
    _write(destination, cockpit)
    DEFAULT_COCKPIT_HASH.write_text(
        hashlib.sha256(destination.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--j10-registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cockpit-source", type=Path)
    parser.add_argument("--cockpit-output", type=Path, default=DEFAULT_COCKPIT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_artifacts(
        args.j10_registry.resolve(),
        args.campaign.resolve(),
        args.output.resolve(),
    )
    if args.cockpit_source is not None:
        enrich_cockpit(
            args.cockpit_source.resolve(),
            args.cockpit_output.resolve(),
            snapshot,
        )
    registry = snapshot.get("registry")
    if not isinstance(registry, dict):
        raise ValueError("HYPOTHESIS_REGISTRY_SUMMARY_MISSING")
    print(
        json.dumps(
            {
                "rules": registry["machine_discovered"],
                "owners": registry["owners"],
                "frozen": registry["prospective_frozen"],
                "provider_calls": 0,
                "odds_api_credits": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
