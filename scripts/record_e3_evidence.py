"""Append the reviewed E3 evidence nodes without rewriting historical claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "reports/evidence/evidence-graph.json"
LEDGER = ROOT / "reports/council/decision-ledger.jsonl"
REVISION = "b7c20ed1da599109da9a94619fe95b9c5b2d2324"


def _file_hash(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _compact_json(value: object, level: int = 0) -> str:
    if isinstance(value, dict):
        rows = [
            " " * (level + 2)
            + json.dumps(str(key), ensure_ascii=False)
            + ":"
            + _compact_json(item, level + 2)
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(rows) + "\n" + " " * level + "}"
    if isinstance(value, list):
        if not value or all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ",".join(_compact_json(item, level) for item in value) + "]"
        if all(
            isinstance(item, dict)
            and all(not isinstance(child, (dict, list)) for child in item.values())
            for item in value
        ):
            rows = [
                " " * (level + 2)
                + json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in value
            ]
            return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
        rows = [" " * (level + 2) + _compact_json(item, level + 2) for item in value]
        return "[\n" + ",\n".join(rows) + "\n" + " " * level + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise TypeError("EVIDENCE_GRAPH_OBJECT_REQUIRED")
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line]
    ledger_hashes = {record["decision_id"]: record["hash"] for record in records}
    claims: list[dict[str, Any]] = [
        {
            "claim_id": "COVERAGE.E3A.SELECTION.V1.001",
            "claim": "The deterministic ordinal policy selects Ligue 1 2024 with 308 terminal fixtures and nineteen inventory-bound payload/receipt pairs from immutable GitHub artifacts.",
            "scope": "E3A_LIGUE1_2024_FROZEN_SELECTION",
            "source": "verified replay inventory plus exact segment and artifact locks",
            "grain": "one_frozen_competition_season_selection",
            "temporal_class": "CODE_AS_OF",
            "artifact": "reports/evidence/e3a/e3a-selection-manifest-v1.json",
            "hash": _file_hash("reports/evidence/e3a/e3a-selection-manifest-v1.json"),
            "code_revision": REVISION,
            "execution_id": "local-e3-selection-freeze-20260808",
            "scientific_lineage_id": "p0-e3-capability-scale-v1",
            "dataset_lineage_id": "E3_SOURCE_RUN_30853757779_INVENTORY_87326EBA",
            "status": "VERIFIED",
            "verified_by": ["DP6", "DP5"],
        },
        {
            "claim_id": "COVERAGE.E3A.CAPABILITY_SCALE.V1.001",
            "claim": "E3A measures 308 Ligue 1 fixtures: seven identity or reconstructed capabilities pass while strict Calendar remains blocked; all source and report replay hashes are byte-identical.",
            "scope": "E3A_LIGUE1_2024_EIGHT_AUTHORIZED_CAPABILITIES",
            "source": "immutable verified fixture replay segment",
            "grain": "one_capability_over_one_complete_competition_season",
            "temporal_class": "MIXED_ROLE_CLASSIFIED",
            "artifact": "reports/evidence/e3a/e3a-measurement-v1.json",
            "hash": _file_hash("reports/evidence/e3a/e3a-measurement-v1.json"),
            "code_revision": REVISION,
            "execution_id": "local-e3a-byte-identical-20260808",
            "scientific_lineage_id": "p0-e3-capability-scale-v1",
            "dataset_lineage_id": "E3A_LIGUE1_2024_SEG_000283",
            "status": "INVALIDATED",
            "verified_by": ["DP6", "C2"],
            "invalidation_reason": (
                "Independent DQ review found understated UNKNOWN statistics, incomplete "
                "denominators and non-scientific event identity in revision b7c20ed1."
            ),
        },
        {
            "claim_id": "FEATURE.CALENDAR.REAL_ASOF.E3A.V1.001",
            "claim": "The real E3A rows expose neither known_at nor a revision catalog; all 5,236 Calendar feature evaluations remain UNKNOWN and READY_STRICT promotion is denied.",
            "scope": "CALENDAR_REAL_E3A_LIGUE1_2024",
            "source": "real E3A temporal fields plus the verified synthetic Golden Pack",
            "grain": "one_calendar_feature_per_fixture_cutoff",
            "temporal_class": "STRICT_AS_OF_BLOCKED_BY_SOURCE",
            "artifact": "reports/evidence/e3a/e3a-calendar-asof-v1.json",
            "hash": _file_hash("reports/evidence/e3a/e3a-calendar-asof-v1.json"),
            "code_revision": REVISION,
            "execution_id": "local-e3a-calendar-real-20260808",
            "scientific_lineage_id": "p0-e3-capability-scale-v1",
            "dataset_lineage_id": "E3A_LIGUE1_2024_TEMPORAL_EVIDENCE",
            "status": "INVALIDATED",
            "verified_by": ["DP6", "C2"],
            "invalidation_reason": (
                "Calendar was source-blocked instead of the more precise temporality block "
                "in revision b7c20ed1."
            ),
        },
        {
            "claim_id": "COVERAGE.E3B.CAPABILITY_SCALE.V1.001",
            "claim": "Conditional E3B covers 1,756 fixtures across five leagues: five capabilities are reconstructed-ready while Lineup and Team Statistics remain partial only on localized Serie A evidence.",
            "scope": "E3B_FIVE_LEAGUES_2024_E3A_PASSED_CAPABILITIES",
            "source": "five immutable verified fixture replay segments",
            "grain": "one_capability_per_league_season_then_weighted_global_aggregate",
            "temporal_class": "POST_MATCH_RECONSTRUCTED_OR_LAGGABLE",
            "artifact": "reports/evidence/e3b/e3b-measurement-v1.json",
            "hash": _file_hash("reports/evidence/e3b/e3b-measurement-v1.json"),
            "code_revision": REVISION,
            "execution_id": "local-e3b-byte-identical-20260808",
            "scientific_lineage_id": "p0-e3-capability-scale-v1",
            "dataset_lineage_id": "E3B_FIVE_LEAGUES_2024_1756_FIXTURES",
            "status": "INVALIDATED",
            "verified_by": ["DP6", "C2"],
            "invalidation_reason": (
                "The E3B gate and aggregate inherited the invalid E3A statistical and grain "
                "classifications from revision b7c20ed1."
            ),
        },
        {
            "claim_id": "SECURITY.E3.EXTERNAL_EFFECTS.ZERO.V1.001",
            "claim": "The E3 execution uses exact GitHub artifacts and records zero provider, R2, SQL and Odds consumption, with no deployment, publication, bet, promotion or triple execution.",
            "scope": "P0_E3_CAPABILITY_SCALE_EXTERNAL_EFFECTS",
            "source": "manual workflow contract, runtime safety gate and deterministic cost reports",
            "grain": "one_bounded_e3_mission",
            "temporal_class": "CODE_AND_EXECUTION_AS_OF",
            "artifact": "reports/evidence/e3b/e3b-costs-v1.json",
            "hash": _file_hash("reports/evidence/e3b/e3b-costs-v1.json"),
            "code_revision": REVISION,
            "execution_id": "local-e3-security-review-20260808",
            "scientific_lineage_id": "p0-e3-capability-scale-v1",
            "dataset_lineage_id": "NO_EXTERNAL_DATA_CLIENT",
            "status": "VERIFIED",
            "verified_by": ["DP5", "C2"],
        },
    ]
    claim_ids = {claim["claim_id"] for claim in claims}
    decision_ids = {
        "RCV3-20260808-064",
        "RCV3-20260808-065",
        "RCV3-20260808-066",
        "RCV3-20260808-067",
    }
    graph["claims"] = [claim for claim in graph["claims"] if claim["claim_id"] not in claim_ids]
    graph["decision_nodes"] = [
        node for node in graph["decision_nodes"] if node["decision_id"] not in decision_ids
    ]
    graph["edges"] = [edge for edge in graph["edges"] if edge["from_claim_id"] not in claim_ids]
    graph["claims"].extend(claims)
    for decision_id in (
        "RCV3-20260808-064",
        "RCV3-20260808-065",
        "RCV3-20260808-066",
        "RCV3-20260808-067",
    ):
        graph["decision_nodes"].append(
            {"decision_id": decision_id, "ledger_record_hash": ledger_hashes[decision_id]}
        )
    relationships = (
        ("COVERAGE.E3A.SELECTION.V1.001", "RCV3-20260808-064"),
        ("COVERAGE.E3A.SELECTION.V1.001", "RCV3-20260808-065"),
        ("COVERAGE.E3A.CAPABILITY_SCALE.V1.001", "RCV3-20260808-065"),
        ("FEATURE.CALENDAR.REAL_ASOF.E3A.V1.001", "RCV3-20260808-065"),
        ("COVERAGE.E3B.CAPABILITY_SCALE.V1.001", "RCV3-20260808-065"),
        ("SECURITY.E3.EXTERNAL_EFFECTS.ZERO.V1.001", "RCV3-20260808-065"),
        ("COVERAGE.E3A.CAPABILITY_SCALE.V1.001", "RCV3-20260808-066"),
        ("FEATURE.CALENDAR.REAL_ASOF.E3A.V1.001", "RCV3-20260808-066"),
        ("COVERAGE.E3B.CAPABILITY_SCALE.V1.001", "RCV3-20260808-066"),
        ("SECURITY.E3.EXTERNAL_EFFECTS.ZERO.V1.001", "RCV3-20260808-066"),
        ("COVERAGE.E3A.CAPABILITY_SCALE.V1.001", "RCV3-20260808-067"),
        ("FEATURE.CALENDAR.REAL_ASOF.E3A.V1.001", "RCV3-20260808-067"),
        ("COVERAGE.E3B.CAPABILITY_SCALE.V1.001", "RCV3-20260808-067"),
    )
    first_edge = len(graph["edges"]) + 1
    graph["edges"].extend(
        {
            "edge_id": f"EDGE.{first_edge + offset}",
            "from_claim_id": claim_id,
            "to_decision_id": decision_id,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        }
        for offset, (claim_id, decision_id) in enumerate(relationships)
    )
    graph["generated_at"] = "2026-08-08T07:47:00Z"
    GRAPH.write_text(
        _compact_json(graph) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
