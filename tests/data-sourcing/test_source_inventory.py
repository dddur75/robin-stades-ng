from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

MODULE_PATH = Path(__file__).parents[2] / "tools" / "data-sourcing" / "source_inventory.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("source_inventory", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_inventory = _load_module()


def _source(source_id: str, source_class: str = "C") -> dict[str, Any]:
    return {
        "source_id": source_id,
        "name": source_id,
        "publisher": "publisher",
        "official_url": "https://example.test",
        "access_type": "public",
        "licence_terms": {"status": "OPEN", "summary": "documented"},
        "commercial_use": "reviewed",
        "history_available": "yes",
        "league_coverage": ["league"],
        "season_coverage": "current",
        "frequency": "daily",
        "latency": "unknown",
        "timestamps_provided": ["updated_at"],
        "raw_payload_retention": "allowed",
        "stable_identifiers": "yes",
        "quality": "reviewed",
        "schema_change_risk": "medium",
        "initial_cost": {"amount": 0, "currency": "EUR", "as_of": "2026-08-14"},
        "monthly_cost": {"amount": 0, "currency": "EUR", "as_of": "2026-08-14"},
        "api_limits": "none",
        "human_maintenance": "low",
        "scientific_value": "useful",
        "source_class": source_class,
        "family_coverage": ["fixtures_results"],
        "scores": dict(source_inventory.WEIGHTS),
        "score_rationales": {key: "traceable rationale" for key in source_inventory.WEIGHTS},
    }


def test_build_scorecard_ranks_and_filters_classes() -> None:
    high = _source("high", "C")
    history = _source("history", "A")
    excluded = _source("excluded", "D")
    excluded["scores"] = {key: 0 for key in source_inventory.WEIGHTS}
    inventory = {"inventory_id": "test", "sources": [excluded, history, high]}

    result = source_inventory.build_scorecard(inventory)

    assert result["top_5_global"][0]["source_id"] == "high"
    assert result["top_3_historical"][0]["source_id"] == "history"
    assert result["top_3_prospective"][0]["source_id"] == "high"
    assert result["excluded_sources"][0]["source_id"] == "excluded"


def test_class_d_is_never_in_global_top_five() -> None:
    excluded = _source("excluded", "D")
    admissible = _source("admissible", "C")
    admissible["scores"]["temporal_proof"] = 19

    result = source_inventory.build_scorecard(
        {"inventory_id": "test", "sources": [excluded, admissible]}
    )

    assert [row["source_id"] for row in result["top_5_global"]] == ["admissible"]


def test_legal_uncertainty_requires_class_d() -> None:
    candidate = _source("unclear", "C")
    candidate["licence_terms"] = {"status": "UNCLEAR", "summary": "not proven"}

    with pytest.raises(source_inventory.InventoryError, match="requires class D"):
        source_inventory.score_source(candidate)


def test_rejects_score_above_weight() -> None:
    candidate = _source("invalid")
    scores = dict(candidate["scores"])
    scores["cost"] = 6
    candidate["scores"] = scores

    with pytest.raises(source_inventory.InventoryError, match="outside 0..5"):
        source_inventory.score_source(candidate)


def test_profile_csv_is_deterministic(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    sample.write_text("Date,Home,Away\n2026-08-02,A,B\n2026-08-01,C,D\n", encoding="utf-8")

    receipt = source_inventory.profile_sample(
        sample,
        source_id="public-sample",
        request_url="https://example.test/sample.csv",
        downloaded_at="2026-08-14T12:00:00Z",
        status_http=200,
        licence_note="CC0",
    )

    assert receipt["row_count"] == 2
    assert receipt["first_event"] == "2026-08-01"
    assert receipt["last_event"] == "2026-08-02"
    assert receipt["payload_sha256"]
    assert receipt["schema_fingerprint"]


def test_profile_csv_orders_day_first_dates_chronologically(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    sample.write_text("Date,Home\n31/08/2025,A\n01/02/2026,B\n", encoding="utf-8")

    receipt = source_inventory.profile_sample(
        sample,
        source_id="public-sample",
        request_url="https://example.test/sample.csv",
        downloaded_at="2026-08-14T12:00:00Z",
        status_http=200,
        licence_note="CC0",
    )

    assert receipt["first_event"] == "2025-08-31"
    assert receipt["last_event"] == "2026-02-01"


def test_cli_writes_scorecard(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    output_path = tmp_path / "scorecard.json"
    inventory_path.write_text(
        json.dumps({"inventory_id": "test", "sources": [_source("candidate")]}),
        encoding="utf-8",
    )

    status = source_inventory.main(
        [
            "score",
            "--inventory",
            str(inventory_path),
            "--output",
            str(output_path),
        ]
    )

    assert status == 0
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["top_5_global"][0]["source_id"] == "candidate"
    assert len(result["source_inventory_fingerprint"]) == 64
