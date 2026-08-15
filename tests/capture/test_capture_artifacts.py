from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from robin.capture import InternalRetentionPolicy

ROOT = Path(__file__).parents[2]
REPORTS = ROOT / "reports" / "data-sourcing"
MODULE_PATH = ROOT / "tools" / "data-sourcing" / "build_capture_harness_artifacts.py"
REQUIRED_REPORTS = {
    "capture-harness-contract-v1.json",
    "internal-retention-policy-v1.json",
    "capture-threat-model-v1.json",
    "offline-replay-proof-v1.json",
    "live-canary-plan-v1.json",
}


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_capture_harness_artifacts", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((REPORTS / name).read_text(encoding="utf-8")))


def test_capture_reports_are_reproducible() -> None:
    module = _load_module()
    generated = cast(dict[str, str], module.build_reports(ROOT))
    assert set(generated) == REQUIRED_REPORTS
    for name, content in generated.items():
        assert (REPORTS / name).read_bytes() == content.encode("utf-8")


def test_all_eleven_contracts_are_inventory_bound() -> None:
    report = _json("capture-harness-contract-v1.json")
    names = [item["name"] for item in report["contracts"]]
    assert names == [
        "ProviderRequestSpec",
        "RequestFingerprint",
        "CaptureBudget",
        "QuotaObservation",
        "RawPayloadReceipt",
        "NormalizedMarketObservation",
        "SchemaFingerprint",
        "FixtureMapping",
        "CaptureManifest",
        "InternalRetentionPolicy",
        "OfflineReplayResult",
    ]
    assert report["default_mode"] == "VALIDATE_OFFLINE"
    assert report["modes"]["LIVE_CANARY"] == {
        "authorized": False,
        "status": "DISABLED_NOT_AUTHORIZED",
    }


def test_retention_report_matches_executable_contract() -> None:
    report = _json("internal-retention-policy-v1.json")
    assert report["policy"] == InternalRetentionPolicy().model_dump(mode="json")
    assert report["public_terms_review"]["public_raw_retention_duration"] == "NOT_STATED"
    assert report["public_terms_review"]["interpretation"] == (
        "INTERNAL_RISK_DECISION_NOT_EXPLICIT_PROVIDER_AUTHORIZATION"
    )
    assert report["verdict"] == "INTERNAL_MARKET_DATA_RETENTION_POLICY_V1_RECORDED"


def test_offline_proof_and_live_lock_are_explicit() -> None:
    proof = _json("offline-replay-proof-v1.json")
    live = _json("live-canary-plan-v1.json")
    assert proof["fixture_provenance"] == "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD"
    assert proof["replay"]["byte_identical"] is True
    assert proof["replay"]["deterministic"] is True
    assert proof["secret_sentinel_occurrences_in_outputs"] == 0
    assert proof["network_calls"] == proof["provider_calls"] == 0
    assert live["authorization"] is False
    assert live["mission_effects"] == {
        "network_calls": 0,
        "provider_calls": 0,
        "secret_reads": 0,
        "credits_consumed": 0,
        "purchases": 0,
        "promotions": 0,
        "bets": 0,
    }
    assert live["canary_metadata_integration"]["status"] == (
        "ABSENT_ALLOWED_METADATA_NOT_FOUND"
    )


def test_threat_model_has_no_open_p0_or_p1() -> None:
    threat = _json("capture-threat-model-v1.json")
    assert threat["open_p0"] == threat["open_p1"] == 0
    assert len(threat["threats"]) == 11
