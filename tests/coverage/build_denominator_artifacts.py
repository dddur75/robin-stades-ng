from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.coverage.denominator_oracle import (
    CALENDAR_PATH,
    CONTRACT_PATH,
    GATES_PATH,
    GRAIN_CATALOG_PATH,
    PACKS_PATH,
    PR26_REVIEW_PATH,
    ROOT,
    aggregate_weighted_rate,
    artifact_proof_hash,
    build_p0_cells,
    calendar_family_status,
    calendar_ready_properties,
    canonical_file_hash,
    canonical_hash,
    closure_counts,
    grid_invariants,
    initial_level_states,
    load_contract,
    load_grain_catalog,
    load_json,
    run_golden_pack,
    seal_artifact,
    verify_pr26_census_source,
)

CAPTURED_AT = "2026-08-04T16:18:00Z"
GRID_PATH = ROOT / "reports/coverage/p0-denominator-grid-v1.json"
E0_PATH = ROOT / "reports/coverage/e0-denominator-proof-v1.json"
SUMMARY_PATH = ROOT / "reports/coverage/denominator-closure-summary-v1.json"
PRIVATE_PATH = ROOT / "cockpit/private-coverage/p0-denominator-status-v1.json"
CENSUS_PATH = ROOT / "reports/coverage/coverage-census-manifest-v1.json"
GATES_REPORT_PATH = ROOT / "reports/coverage/p0-readiness-gates-v1.json"
PROPERTIES_PATH = ROOT / "reports/coverage/p0-property-readiness-v1.json"
GOLDEN_PATH = ROOT / "tests/coverage/fixtures/golden-denominator-pack-v1.json"


def _artifact_base(schema_version: str) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "captured_at": CAPTURED_AT,
        "source_revision": "2a59a20a786a13be1eb4a110c11bb585f35565cb",
        "contract_path": str(CONTRACT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "provider_calls": 0,
        "r2_writes": 0,
        "purchases": 0,
        "odds_credits": 0,
    }


def build_artifacts() -> dict[Path, dict[str, Any]]:
    contract = load_contract()
    catalog = load_grain_catalog()
    pr26_review = verify_pr26_census_source(contract)
    gates_contract = load_json(GATES_PATH)
    calendar_contract = load_json(CALENDAR_PATH)
    packs_contract = load_json(PACKS_PATH)
    ready_calendar_properties = calendar_ready_properties()
    cells = build_p0_cells(contract)
    counts = closure_counts(cells)
    invariants = grid_invariants(cells)
    grid_hash = canonical_hash([cell["definition_hash"] for cell in cells])
    evidence_set_hash = canonical_hash([cell["cell_hash"] for cell in cells])
    weighted_aggregates = {
        name: aggregate_weighted_rate([cell["rates"][name] for cell in cells])
        for name in ("scope_completion", "normalization_integrity", "content_presence")
    }

    grid = seal_artifact(
        {
            **_artifact_base("p0-denominator-grid-v1"),
            "definition_state": "DEFINITION_CLOSED",
            "empirical_state": "OPEN",
            "grid_hash": grid_hash,
            "evidence_set_hash": evidence_set_hash,
            "grain_catalog_path": str(GRAIN_CATALOG_PATH.relative_to(ROOT)).replace(
                "\\", "/"
            ),
            "grain_catalog_hash": canonical_hash(catalog),
            "cell_count": len(cells),
            "invariants": invariants,
            "weighted_aggregates": weighted_aggregates,
            "cells": cells,
        }
    )

    golden = load_json(GOLDEN_PATH)
    golden_results = run_golden_pack(golden)
    e0 = seal_artifact(
        {
            **_artifact_base("e0-denominator-proof-v1"),
            "evaluation_level": "E0",
            "population_kind": "SYNTHETIC",
            "status": "PASS_DEFINITION_ONLY",
            "golden_pack_hash": canonical_hash(golden),
            "source_record_count": golden["source_record_count"],
            "expanded_candidate_count": golden["expanded_candidate_count"],
            "scenario_count": len(golden_results),
            "scenario_results": golden_results,
            "all_expected_results_reproduced": all(
                item["status"] == "PASS" for item in golden_results
            ),
            "real_cells_closed": 0,
            "authorizes_scale": False,
        }
    )

    coverage = pr26_review["coverage"]
    replay = pr26_review["replay"]
    census = seal_artifact(
        {
            **_artifact_base("coverage-census-manifest-v1"),
            "manifest_id": canonical_hash(
                {
                    "scope": "P0_2020_2025",
                    "grid_hash": grid_hash,
                    "contract": contract["contract_id"],
                }
            ),
            "run_independent_identity": True,
            "scope": "P0_2020_2025",
            "status": "AUTHORITATIVE_P0_CENSUS_MISSING",
            "source_search_order": [
                "R2 league payloads",
                "R2 fixture payloads",
                "census manifests",
                "receipts",
                "intentions",
                "coverage flags",
                "inventories",
            ],
            "reused_evidence": {
                "review_path": str(PR26_REVIEW_PATH.relative_to(ROOT)).replace("\\", "/"),
                "review_proof_hash": pr26_review["proof_hash"],
                "source_run": "github-run:30896340821",
                "coverage_proof_hash": pr26_review["artifacts"]["coverage_proof"][
                    "proof_sha256"
                ],
                "payloads_replayed": replay["payloads_replayed"],
                "receipts_verified": replay["receipts_verified"],
                "normalized_rows": replay["normalized_rows"],
                "hash_mismatches": replay["hash_mismatches"],
            },
            "observed_union": {
                "cells": coverage["coverage_count"],
                "census_evidence_cells": coverage["census_evidence_cells"],
                "without_census_evidence": coverage["no_census_evidence_cells"],
                "projectable_to_authoritative_p0_grid": False,
                "gate_status_counts": coverage["gate_status_counts"],
            },
            "authoritative_p0": {
                "expected_cells": len(cells),
                "empirically_closed_cells": counts["closed"],
                "open_cells": counts["open"],
            },
            "api_football_calls_allowed": 0,
            "conditional_census_call_cap": 100,
            "conditional_census_calls_authorized": False,
            "r2_reads_during_phase": 0,
            "new_replay": False,
            "scale_authorized": False,
        }
    )

    functional_gates = [item for item in gates_contract["gates"] if item["families"]]
    source_gates = [item for item in gates_contract["gates"] if not item["families"]]
    gate_report = seal_artifact(
        {
            **_artifact_base("p0-readiness-gates-report-v1"),
            "scope": gates_contract["scope"],
            "coverage_gate": gates_contract["coverage_gate"],
            "gates": gates_contract["gates"],
            "counts": {
                "functional_total": len(functional_gates),
                "functional_ready": sum(
                    item["status"] == "READY" for item in functional_gates
                ),
                "blocked_by_coverage": sum(
                    item["status"] == "BLOCKED_BY_COVERAGE"
                    for item in functional_gates
                ),
                "blocked_by_source": sum(
                    item["status"] == "BLOCKED_BY_SOURCE" for item in source_gates
                ),
            },
            "readiness_verdicts": gates_contract["readiness_verdicts"],
            "properties_unlocked": [],
            "weather_and_footedness_block_p0_api_coverage": False,
            "scale_authorized": False,
            "promotion": False,
        }
    )

    property_report = seal_artifact(
        {
            **_artifact_base("p0-property-readiness-v1"),
            "scope": "P0_2020_2025",
            "canonical_property_source": {
                "path": "reports/hypothesis-genome/property-semantic-roles.json",
                "file_sha256_lf": canonical_file_hash(
                    ROOT / "reports/hypothesis-genome/property-semantic-roles.json"
                ),
            },
            "family_readiness": [
                {
                    "family": family,
                    "status": "BLOCKED_BY_P0_DENOMINATORS",
                    "properties_unlocked": [],
                }
                for family in contract["grid"]["families"]
            ],
            "calendar_fatigue": {
                "status": calendar_family_status(len(ready_calendar_properties)),
                "ready_properties": len(ready_calendar_properties),
                "total_properties": len(calendar_contract["properties"]),
                "properties": calendar_contract["properties"],
            },
            "families_exploitable": [],
            "properties_unlocked": [],
            "opens_hypergraph": False,
            "hypergraph_verdict": "NOT_OPENED_DATA_GATES_INSUFFICIENT",
        }
    )

    summary = seal_artifact(
        {
            **_artifact_base("denominator-closure-summary-v1"),
            "verdict": "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL",
            "scopes": {
                "gating": "P0_2020_2025",
                "non_gating": "EXTENDED_ALL_AVAILABLE",
            },
            "definition_state": "DEFINITION_CLOSED",
            "empirical_state": "OPEN",
            "grid_hash": grid_hash,
            "total_cells": len(cells),
            "closed_cells": counts["closed"],
            "open_cells": counts["open"],
            "closure_rate": counts["closed"] / len(cells),
            "weighted_aggregates": weighted_aggregates,
            "level_states": initial_level_states(),
            "level_controls": packs_contract["levels"],
            "reused_coverage_reality": {
                "observed_union_cells": coverage["coverage_count"],
                "census_evidence_cells": coverage["census_evidence_cells"],
                "observed_union_projected_into_p0": False,
                "blocked_by_coverage": coverage["gate_status_counts"][
                    "BLOCKED_BY_COVERAGE"
                ],
                "not_assessed": coverage["gate_status_counts"]["NOT_ASSESSED"],
            },
            "gate_counts": gate_report["counts"],
            "readiness_verdicts": gates_contract["readiness_verdicts"],
            "properties_unlocked": [],
            "families_exploitable": [],
            "calendar_fatigue": {
                "ready_properties": len(ready_calendar_properties),
                "total_properties": len(calendar_contract["properties"]),
                "status": calendar_family_status(len(ready_calendar_properties)),
                "opens_hypergraph": False,
            },
            "hypergraph_verdict": "NOT_OPENED_DATA_GATES_INSUFFICIENT",
            "scale_authorized": False,
            "promotion": False,
        }
    )

    private_cells = [
        {
            "cell_id": cell["cell_id"],
            "scope": cell["scope"],
            "competition": cell["competition"],
            "season": cell["season"],
            "family": cell["family"],
            "grain": cell["grain"],
            "distinct_key": cell["distinct_key"],
            "advertised_coverage": cell["advertised_coverage"],
            "expected_count": cell["expected_count"],
            "received_count": cell["received_count"],
            "empty_valid_count": cell["empty_valid_count"],
            "invalid_count": cell["invalid_count"],
            "coverage_percent": cell["coverage_percent"],
            "null_rate": cell["null_rate"],
            "source_endpoint": "SANITIZED_IN_PRIVATE_PROJECTION",
            "payload_hash": cell["payload_hash"],
            "receipt_hash": cell["receipt_hash"],
            "temporal_class": cell["temporal_class"],
            "gate": cell["gate"],
            "gate_reason": cell["gate_reason"],
            "closure_state": cell["closure_state"],
            "reason_codes": cell["reason_codes"],
            "rates": cell["rates"],
            "cell_hash": cell["cell_hash"],
        }
        for cell in cells
    ]
    private = seal_artifact(
        {
            **_artifact_base("p0-denominator-private-projection-v1"),
            "privacy": {
                "classification": "PRIVATE_SANITIZED_PROJECTION",
                "raw_payloads": False,
                "provider_endpoints": False,
                "r2_keys": False,
                "secrets": False,
            },
            "verdict": "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL",
            "summary": {
                "dimensions": "5 competitions × 6 seasons × 16 families",
                "gating_scope": "P0_2020_2025",
                "non_gating_scope": "EXTENDED_ALL_AVAILABLE",
                "total_cells": len(cells),
                "closed_cells": counts["closed"],
                "open_cells": counts["open"],
                "definition_state": "DEFINITION_CLOSED",
                "empirical_state": "OPEN",
            },
            "rate_labels": {
                "scope_completion": "Complétion du périmètre",
                "normalization_integrity": "Intégrité de normalisation",
                "content_presence": "Présence de contenu",
            },
            "weighted_aggregates": weighted_aggregates,
            "level_states": initial_level_states(),
            "level_controls": packs_contract["levels"],
            "calendar_fatigue": {
                "ready_properties": len(ready_calendar_properties),
                "total_properties": len(calendar_contract["properties"]),
                "status": calendar_family_status(len(ready_calendar_properties)),
                "properties": calendar_contract["properties"],
            },
            "gate_counts": gate_report["counts"],
            "gates": [
                {
                    "id": item["id"],
                    "status": item["status"],
                    "reason": item["reason"],
                }
                for item in gates_contract["gates"]
            ],
            "readiness_verdicts": gates_contract["readiness_verdicts"],
            "properties_unlocked": [],
            "families_exploitable": [],
            "navigation_gates": {
                "data": "AVAILABLE",
                "hypothesis": "BLOCKED_BY_DATA",
                "strategy": "BLOCKED_BY_SCIENCE",
                "matches": "BLOCKED_BY_MEMBERSHIP_SET",
            },
            "trust_questions": [
                "Pourquoi est-il affiché ?",
                "Sur quelles données repose-t-il ?",
                "Qu’est-ce qui pourrait l’invalider ?",
                "Est-il historique, reconstruit ou prospectif ?",
                "A-t-il survécu aux corrections statistiques ?",
            ],
            "cells": private_cells,
        }
    )
    return {
        GRID_PATH: grid,
        E0_PATH: e0,
        CENSUS_PATH: census,
        GATES_REPORT_PATH: gate_report,
        PROPERTIES_PATH: property_report,
        SUMMARY_PATH: summary,
        PRIVATE_PATH: private,
    }


def write_artifacts() -> None:
    for path, artifact in build_artifacts().items():
        if artifact_proof_hash(artifact) != artifact["proof_hash"]:
            raise RuntimeError(f"PROOF_HASH_INVALID:{path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    write_artifacts()
