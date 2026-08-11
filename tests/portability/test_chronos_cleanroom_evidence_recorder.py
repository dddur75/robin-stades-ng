from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.record_chronos_cleanroom_evidence import (
    CI1_CORRECTION_GENERATED_AT,
    CORRECTION_GENERATED_AT,
    PORTABILITY_CORRECTION_GENERATED_AT,
    TEMPORAL_CORRECTION_GENERATED_AT,
    canonical_hash,
    verify_ci1_correction_final,
    verify_correction_final,
    verify_portability_correction_final,
    verify_temporal_correction_final,
)

ROOT = Path(__file__).resolve().parents[2]


def _evidence() -> tuple[list[dict[str, object]], dict[str, object]]:
    records = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    graph = json.loads(
        (ROOT / "reports/evidence/evidence-graph.json").read_text(encoding="utf-8")
    )
    return records, graph


def _prefix(
    records: list[dict[str, object]],
    graph: dict[str, object],
    *,
    record_count: int,
    claim_count: int,
    edge_count: int,
    generated_at: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    prefix_records = copy.deepcopy(records[:record_count])
    prefix_graph = copy.deepcopy(graph)
    prefix_graph["claims"] = prefix_graph["claims"][:claim_count]  # type: ignore[index]
    prefix_graph["decision_nodes"] = prefix_graph["decision_nodes"][  # type: ignore[index]
        :record_count
    ]
    prefix_graph["edges"] = prefix_graph["edges"][:edge_count]  # type: ignore[index]
    prefix_graph["generated_at"] = generated_at
    return prefix_records, prefix_graph


def _correction_prefix(
    records: list[dict[str, object]], graph: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    return _prefix(
        records,
        graph,
        record_count=109,
        claim_count=125,
        edge_count=296,
        generated_at=CORRECTION_GENERATED_AT,
    )


def _ci1_prefix(
    records: list[dict[str, object]], graph: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    return _prefix(
        records,
        graph,
        record_count=110,
        claim_count=126,
        edge_count=297,
        generated_at=CI1_CORRECTION_GENERATED_AT,
    )


def _portability_prefix(
    records: list[dict[str, object]], graph: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    return _prefix(
        records,
        graph,
        record_count=111,
        claim_count=127,
        edge_count=298,
        generated_at=PORTABILITY_CORRECTION_GENERATED_AT,
    )


def _temporal_prefix(
    records: list[dict[str, object]], graph: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    return _prefix(
        records,
        graph,
        record_count=112,
        claim_count=128,
        edge_count=299,
        generated_at=TEMPORAL_CORRECTION_GENERATED_AT,
    )


def test_correction_final_state_is_exact_and_read_only() -> None:
    records, graph = _evidence()
    records, graph = _correction_prefix(records, graph)
    before_records = copy.deepcopy(records)
    before_graph = copy.deepcopy(graph)
    verify_correction_final(records, graph)
    assert records == before_records
    assert graph == before_graph


def test_correction_final_state_rejects_missing_final_edge() -> None:
    records, graph = _evidence()
    records, graph = _correction_prefix(records, graph)
    graph["edges"].pop()  # type: ignore[union-attr]
    with pytest.raises(SystemExit, match="CORRECTION_FINAL_STATE_INVALID"):
        verify_correction_final(records, graph)


def test_correction_final_state_rejects_rehashed_authority_escalation() -> None:
    records, graph = _evidence()
    records, graph = _correction_prefix(records, graph)
    final = records[-1]
    final["decision"] = "READY_AND_MERGE_AUTHORIZED"
    final["hash"] = canonical_hash(
        {key: value for key, value in final.items() if key != "hash"}
    )
    graph["decision_nodes"][-1]["ledger_record_hash"] = final["hash"]  # type: ignore[index]
    with pytest.raises(SystemExit, match="CORRECTION_FINAL_STATE_INVALID"):
        verify_correction_final(records, graph)


def test_ci1_correction_final_state_is_exact_and_read_only() -> None:
    records, graph = _evidence()
    records, graph = _ci1_prefix(records, graph)
    before_records = copy.deepcopy(records)
    before_graph = copy.deepcopy(graph)
    verify_ci1_correction_final(records, graph)
    assert records == before_records
    assert graph == before_graph


def test_ci1_correction_final_state_rejects_missing_final_edge() -> None:
    records, graph = _evidence()
    records, graph = _ci1_prefix(records, graph)
    graph["edges"].pop()  # type: ignore[union-attr]
    with pytest.raises(SystemExit, match="CI1_CORRECTION_FINAL_STATE_INVALID"):
        verify_ci1_correction_final(records, graph)


def test_ci1_correction_final_state_rejects_rehashed_authority_escalation() -> None:
    records, graph = _evidence()
    records, graph = _ci1_prefix(records, graph)
    final = records[-1]
    final["decision"] = "READY_AND_MERGE_AUTHORIZED"
    final["hash"] = canonical_hash(
        {key: value for key, value in final.items() if key != "hash"}
    )
    graph["decision_nodes"][-1]["ledger_record_hash"] = final["hash"]  # type: ignore[index]
    with pytest.raises(SystemExit, match="CI1_CORRECTION_FINAL_STATE_INVALID"):
        verify_ci1_correction_final(records, graph)


def test_portability_correction_final_state_is_exact_and_read_only() -> None:
    records, graph = _evidence()
    records, graph = _portability_prefix(records, graph)
    before_records = copy.deepcopy(records)
    before_graph = copy.deepcopy(graph)
    verify_portability_correction_final(records, graph)
    assert records == before_records
    assert graph == before_graph
    assert graph["generated_at"] == PORTABILITY_CORRECTION_GENERATED_AT


def test_portability_correction_final_state_rejects_missing_final_edge() -> None:
    records, graph = _evidence()
    records, graph = _portability_prefix(records, graph)
    graph["edges"].pop()  # type: ignore[union-attr]
    with pytest.raises(SystemExit, match="PORTABILITY_CORRECTION_FINAL_STATE_INVALID"):
        verify_portability_correction_final(records, graph)


def test_portability_correction_rejects_rehashed_authority_escalation() -> None:
    records, graph = _evidence()
    records, graph = _portability_prefix(records, graph)
    final = records[-1]
    final["decision"] = "READY_AND_MERGE_AUTHORIZED"
    final["hash"] = canonical_hash(
        {key: value for key, value in final.items() if key != "hash"}
    )
    graph["decision_nodes"][-1]["ledger_record_hash"] = final["hash"]  # type: ignore[index]
    with pytest.raises(SystemExit, match="PORTABILITY_CORRECTION_FINAL_STATE_INVALID"):
        verify_portability_correction_final(records, graph)


def test_temporal_correction_final_state_is_exact_and_read_only() -> None:
    records, graph = _evidence()
    records, graph = _temporal_prefix(records, graph)
    before_records = copy.deepcopy(records)
    before_graph = copy.deepcopy(graph)
    verify_temporal_correction_final(records, graph)
    assert records == before_records
    assert graph == before_graph
    assert graph["generated_at"] == TEMPORAL_CORRECTION_GENERATED_AT


def test_temporal_correction_final_state_rejects_missing_final_edge() -> None:
    records, graph = _evidence()
    records, graph = _temporal_prefix(records, graph)
    graph["edges"].pop()  # type: ignore[union-attr]
    with pytest.raises(SystemExit, match="TEMPORAL_CORRECTION_FINAL_STATE_INVALID"):
        verify_temporal_correction_final(records, graph)


def test_temporal_correction_rejects_rehashed_authority_escalation() -> None:
    records, graph = _evidence()
    records, graph = _temporal_prefix(records, graph)
    final = records[-1]
    final["decision"] = "READY_AND_MERGE_AUTHORIZED"
    final["hash"] = canonical_hash(
        {key: value for key, value in final.items() if key != "hash"}
    )
    graph["decision_nodes"][-1]["ledger_record_hash"] = final["hash"]  # type: ignore[index]
    with pytest.raises(SystemExit, match="TEMPORAL_CORRECTION_FINAL_STATE_INVALID"):
        verify_temporal_correction_final(records, graph)
