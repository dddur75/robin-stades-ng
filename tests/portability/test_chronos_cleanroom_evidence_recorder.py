from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.record_chronos_cleanroom_evidence import (
    CORRECTION_GENERATED_AT,
    canonical_hash,
    verify_ci1_correction_final,
    verify_correction_final,
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


def _correction_prefix(
    records: list[dict[str, object]], graph: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object]]:
    prefix_records = copy.deepcopy(records[:-1])
    prefix_graph = copy.deepcopy(graph)
    prefix_graph["claims"] = prefix_graph["claims"][:-1]  # type: ignore[index]
    prefix_graph["decision_nodes"] = prefix_graph["decision_nodes"][:-1]  # type: ignore[index]
    prefix_graph["edges"] = prefix_graph["edges"][:-1]  # type: ignore[index]
    prefix_graph["generated_at"] = CORRECTION_GENERATED_AT
    return prefix_records, prefix_graph


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
    before_records = copy.deepcopy(records)
    before_graph = copy.deepcopy(graph)
    verify_ci1_correction_final(records, graph)
    assert records == before_records
    assert graph == before_graph


def test_ci1_correction_final_state_rejects_missing_final_edge() -> None:
    records, graph = _evidence()
    graph["edges"].pop()  # type: ignore[union-attr]
    with pytest.raises(SystemExit, match="CI1_CORRECTION_FINAL_STATE_INVALID"):
        verify_ci1_correction_final(records, graph)


def test_ci1_correction_final_state_rejects_rehashed_authority_escalation() -> None:
    records, graph = _evidence()
    final = records[-1]
    final["decision"] = "READY_AND_MERGE_AUTHORIZED"
    final["hash"] = canonical_hash(
        {key: value for key, value in final.items() if key != "hash"}
    )
    graph["decision_nodes"][-1]["ledger_record_hash"] = final["hash"]  # type: ignore[index]
    with pytest.raises(SystemExit, match="CI1_CORRECTION_FINAL_STATE_INVALID"):
        verify_ci1_correction_final(records, graph)
