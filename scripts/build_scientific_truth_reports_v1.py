"""Build the bounded, offline Scientific Truth Kernel V1 reports.

The builder is intentionally deterministic.  It reads only tracked repository
artifacts, optionally verifies the independent audit pack, and never connects
to a provider, database, object store, or workflow API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from robin.market_math import (
    DECISION_THRESHOLD_VERSION,
    PROFIT_PER_BET_DEFINITION_VERSION,
    ROI_DEFINITION_VERSION,
    SCIENTIFIC_KERNEL_VERSION,
    SETTLEMENT_VERSION,
    STAKING_VERSION,
    TURNOVER_DEFINITION_VERSION,
    YIELD_DEFINITION_VERSION,
    decide_market,
    devig_execution_metadata,
    kernel_versions,
    performance_summary,
    settle_profit,
    stake_units,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "scientific-truth"
DOC_PATH = ROOT / "docs" / "scientific" / "ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1.md"

AUDITED_REVISION = "1ffeec1cd89e83deda008da39bb22540a70db896"
AUDITED_TREE = "d751c18ea6233ab59ffeb07c3a38453212a9dd87"
REPAIR_REVISION = "c2bb1769a611728a44c19477932d37e6ab11e5a7"
GENERATED_AT = "2026-08-13T15:38:28Z"
AUDIT_MANIFEST_SHA256 = "38559704269d4e31b9406fc3ca90a8d8ba3fa4c16b0e8e8a89eaeaeaef6e5476"
LOOP54_MANIFEST_SHA256 = "f3907663f43fcd72078b6e36e0f40b276478e11e28c72fbfaed9e32af65c34df"
LOOP54_FINGERPRINT_COUNT = 89

AUDIT_FILES = {
    "manifest.json": AUDIT_MANIFEST_SHA256,
    "findings.json": "7ec533b93c5db97b96c68c9cf99dc42f80206699bd383dff505eceed6b164581",
    "AUDIT-REPORT.md": "9af65e802c9fc6a253e6f00c10dc4b11d60c4796eece01aca07878c757b0a6d0",
    "tables/backtest-v3-historical-roi-replay.csv": "4d5af21bd19e1f5850bf4fa043b22abe5899e97ea0101b52e1c73d6c695c942c",
    "tables/devig-implementations.csv": "8a50263f82413775aeb823df0530ad749b2c6b15edd87fe0dbe0fd8614cae1ab",
    "tables/devig-documentation-vs-execution.csv": "3543c3fc6f27de15b72e6dfa6ffe4e83d4f3156cd690e2fbee8d0d22764ed345",
    "tables/devig-historical-summary.csv": "fe6b0398d24fe569019cfc2b07453814bbd9feb96d9b744f3f441cbe4b660437",
    "tables/devig-decision-divergence.csv": "41ba3733f6075cfa5600dabf83d95f24688d1c0e6d6c49d3d4db2239ed95b749",
    "tables/hypothesis-search-space.csv": "882021641f80359d732533419567b1da4dc9cd722dc491097bdb9eac673dfb63",
    "tables/hypothesis-selection-history.csv": "9433cad0313c298b5b987fcaa4396ad38e13b881839c078139c47c3b26628f9a",
    "tables/historical-survivor-replay.csv": "a6aa6b29c95eaa8b3dfd62326b3e754d5a222a4e3162e8550cf83f79d1aca920",
    "tables/dataset-lineage.csv": "a7497c74dd2c32ffa91997cf8dcfb882b2e64d046e5c0375246dd866122c985b",
    "tables/time-fields.csv": "8c09e249b937ae62ea374be87bcb0ece9c2d8f41ae0d22077c35be9e5b14e3a8",
    "tables/report-metric-propagation.csv": "0007df39df35c26c163420ed2afe2a61b58e6d024335101b1284c98d48d5eb97",
}

REPOSITORY_INPUTS = {
    "cockpit/app/cockpit-data.json": "269dc665549f2ed69b87d71a7be732e327d1e0275b3e8cffbf6d6736b850db36",
    "cockpit/app/cockpit-expert-data.json": "1600eadca2ffb91df829b4f0faab2d13b628f0914a2dc5a3c416227a59220e57",
}
AUDITED_CHECKOUT_INPUTS = {
    "cockpit/app/cockpit-data.json": "5abeed0bc029e80f24a39aa4de0ac6da67e44c61c1389b7e7b1353a4354f3c20",
    "cockpit/app/cockpit-expert-data.json": "3b5651f7718daa5019b56523e5669da31b9f4a40a2528645bc0ebb0628b3af1e",
}

AUDIT_LOGICAL_PATH = "audit-evidence/ROBIN-SCIENTIFIC-AUDIT-V1"
LOOP54_LOGICAL_PATH = "audit-evidence/ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1"
LOOP54_REPORTS_LOGICAL_PATH = (
    "audit-evidence/ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1-REPORTS-RECEIPT-V3"
)
LOOP54_REPORTS_EVIDENCE_ID = "LOOP54_REPORTS:E0003"
GENERATOR_PATH = "scripts/build_scientific_truth_reports_v1.py"
REPLAY_PATH = "reports/scientific-truth/historical-truth-replay-v1.json"

SOURCE_PROJECTION_KEYS = (
    "backtest_version",
    "strategy",
    "market",
    "segment",
    "staking",
    "bets",
    "profit_units",
    "stored_roi",
    "stored_yield",
    "production_status",
    "promotion",
    "status",
)

REPORT_SPECS = {
    "scientific-truth-defect-inventory-v1.json": (
        "scientific-truth-defect-inventory-v1",
        "GOV.SCIENTIFIC.TRUTH.DEFECT.INVENTORY.V1.001",
    ),
    "roi-turnover-repair-v1.json": (
        "roi-turnover-repair-v1",
        "EVAL.SCIENTIFIC.ROI.TURNOVER.REPAIR.V1.001",
    ),
    "yield-consumer-inventory-v1.json": (
        "yield-consumer-inventory-v1",
        "GOV.SCIENTIFIC.YIELD.CONSUMER.INVENTORY.V1.001",
    ),
    "devig-implementation-inventory-v1.json": (
        "devig-implementation-inventory-v1",
        "GOV.SCIENTIFIC.DEVIG.IMPLEMENTATION.INVENTORY.V1.001",
    ),
    "devig-canonicalization-v1.json": (
        "devig-canonicalization-v1",
        "EVAL.SCIENTIFIC.DEVIG.CANONICALIZATION.V1.001",
    ),
    "decision-path-trace-v1.json": (
        "decision-path-trace-v1",
        "GOV.SCIENTIFIC.DECISION.PATH.TRACE.V1.001",
    ),
    "historical-truth-replay-v1.json": (
        "historical-truth-replay-v1",
        "REPLAY.SCIENTIFIC.HISTORICAL.TRUTH.V1.001",
    ),
    "historical-invalidation-ledger-v1.json": (
        "historical-invalidation-ledger-v1",
        "GOV.SCIENTIFIC.HISTORICAL.INVALIDATION.LEDGER.V1.001",
    ),
}

EXTERNAL_EFFECTS_ZERO = {
    "network_calls": 0,
    "neon_api_calls": 0,
    "provider_calls": 0,
    "api_football_calls": 0,
    "odds_provider_calls": 0,
    "production_connections": 0,
    "production_postgresql_connections": 0,
    "sql_reads": 0,
    "sql_writes": 0,
    "r2_operations": 0,
    "live_workflow_dispatches": 0,
    "migration_0014": 0,
    "recovery_branch_creations": 0,
    "role_creations": 0,
    "purchases": 0,
    "real_bets": 0,
    "promotions": 0,
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_repository_file(path: Path) -> str:
    """Hash tracked text as the canonical LF Git representation."""
    return _sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


LOOP54_EVIDENCE_IDS = frozenset({"E0016", "E0017", "E0026"})
LOOP54_RESOLUTION_CLAIM_ID = "SCIENCE.TRUTH_KERNEL.REGRESSION.V1.001"


def _qualify_evidence_id(evidence_id: str) -> str:
    if ":" in evidence_id:
        return evidence_id
    namespace = "LOOP54" if evidence_id in LOOP54_EVIDENCE_IDS else "AUDIT"
    return f"{namespace}:{evidence_id}"


def _evidence_ref(evidence_id: str) -> str:
    return _qualify_evidence_id(evidence_id)


def _namespace_evidence_ids(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _namespace_evidence_ids(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        if key is not None and key.endswith("evidence_ids"):
            return [_evidence_ref(str(item)) for item in value]
        return [_namespace_evidence_ids(item) for item in value]
    return value


def _bind_resolution_claims(value: Any) -> Any:
    if isinstance(value, dict):
        result = {item_key: _bind_resolution_claims(item_value) for item_key, item_value in value.items()}
        if result.get("status") == "RESOLVED_IN_CODE":
            result["resolution_claim_ids"] = [LOOP54_RESOLUTION_CLAIM_ID]
        return result
    if isinstance(value, list):
        return [_bind_resolution_claims(item) for item in value]
    return value


def _with_content_hash(document: dict[str, Any]) -> dict[str, Any]:
    result = _bind_resolution_claims(_namespace_evidence_ids(dict(document)))
    result["content_hash_algorithm"] = "SHA256_CANONICAL_JSON_EXCLUDING_CONTENT_SHA256"
    result["content_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def _verify_content_hash(document: dict[str, Any]) -> None:
    stored = document["content_sha256"]
    candidate = {key: value for key, value in document.items() if key != "content_sha256"}
    actual = _sha256_bytes(_canonical_bytes(candidate))
    if stored != actual:
        raise ValueError(f"REPORT_CONTENT_HASH_MISMATCH:{document.get('report_id')}")


def _verify_audit_root(audit_root: Path) -> None:
    root = audit_root.resolve(strict=True)
    for relative, expected in AUDIT_FILES.items():
        path = root / relative
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(f"AUDIT_INPUT_HASH_MISMATCH:{relative}")


def _verify_loop54_root(loop54_root: Path) -> None:
    root = loop54_root.resolve(strict=True)
    manifest_path = root / "manifest.json"
    sums_path = root / "sha256sums.txt"
    commands_path = root / "commands.jsonl"
    if not manifest_path.is_file() or _sha256_file(manifest_path) != LOOP54_MANIFEST_SHA256:
        raise ValueError("LOOP54_MANIFEST_HASH_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("evidence_pack_id") != "ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1"
        or manifest.get("namespace") != "LOOP54"
        or manifest.get("repair_revision") != REPAIR_REVISION
        or manifest.get("command_count") != 29
        or manifest.get("fingerprint_count") != LOOP54_FINGERPRINT_COUNT
    ):
        raise ValueError("LOOP54_MANIFEST_CONTRACT_MISMATCH")
    if not sums_path.is_file() or _sha256_file(sums_path) != manifest.get("sha256sums_sha256"):
        raise ValueError("LOOP54_SHA256SUMS_HASH_MISMATCH")
    if not commands_path.is_file() or _sha256_file(commands_path) != manifest.get(
        "commands_jsonl_sha256"
    ):
        raise ValueError("LOOP54_COMMANDS_JSONL_HASH_MISMATCH")

    listed_paths: set[str] = set()
    lines = sums_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != LOOP54_FINGERPRINT_COUNT:
        raise ValueError("LOOP54_FINGERPRINT_COUNT_MISMATCH")
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise ValueError("LOOP54_FINGERPRINT_FORMAT_INVALID")
        expected, relative = line[:64], line[66:]
        if (
            len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or relative in listed_paths
        ):
            raise ValueError("LOOP54_FINGERPRINT_ENTRY_INVALID")
        listed_paths.add(relative)
        path = root.joinpath(*relative.split("/"))
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(f"LOOP54_FINGERPRINT_MISMATCH:{relative}")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "sha256sums.txt"}
    }
    if actual_paths != listed_paths:
        raise ValueError("LOOP54_FINGERPRINT_FILE_SET_MISMATCH")


def _load_repository_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for relative, expected in REPOSITORY_INPUTS.items():
        path = ROOT / relative
        if _sha256_repository_file(path) != expected:
            raise ValueError(f"REPOSITORY_INPUT_HASH_MISMATCH:{relative}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"REPOSITORY_INPUT_NOT_OBJECT:{relative}")
        documents.append(value)
    return documents[0], documents[1]


def _source_projection(item: dict[str, Any]) -> dict[str, Any]:
    parameters = item.get("parameters")
    if not isinstance(parameters, dict):
        raise TypeError("HISTORICAL_PARAMETERS_NOT_OBJECT")
    projection = {
        "backtest_version": item.get("backtest_version"),
        "strategy": item.get("strategy"),
        "market": item.get("market"),
        "segment": item.get("segment"),
        "staking": parameters.get("staking"),
        "bets": item.get("bets"),
        "profit_units": item.get("profit_units"),
        "stored_roi": item.get("roi"),
        "stored_yield": item.get("yield"),
        "production_status": item.get("production_status"),
        "promotion": item.get("promotion"),
        "status": item.get("status"),
    }
    if tuple(projection) != SOURCE_PROJECTION_KEYS:
        raise AssertionError("HISTORICAL_SOURCE_PROJECTION_KEYS_DRIFT")
    return projection


def _assert_finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label}_NOT_NUMBER")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label}_NOT_FINITE")
    return result


def _extract_historical_results(
    cockpit: dict[str, Any], expert: dict[str, Any]
) -> list[dict[str, Any]]:
    deep = cockpit.get("deepData")
    if not isinstance(deep, dict):
        raise TypeError("COCKPIT_DEEP_DATA_NOT_OBJECT")
    backtests = deep.get("backtests")
    strategies = deep.get("strategies")
    expert_backtests = expert.get("backtests")
    if not all(isinstance(items, list) for items in (backtests, strategies, expert_backtests)):
        raise TypeError("HISTORICAL_SURFACE_NOT_ARRAY")
    if len(backtests) != 15 or len(expert_backtests) != 15:
        raise ValueError("HISTORICAL_RESULT_COUNT_DRIFT")
    strategy_indexes = {
        item.get("strategy"): index
        for index, item in enumerate(strategies)
        if isinstance(item, dict) and item.get("backtest_version") == "api_football_backtest_v3"
    }
    if len(strategy_indexes) != 15:
        raise ValueError("HISTORICAL_STRATEGY_SURFACE_COUNT_DRIFT")

    artifact_hashes = REPOSITORY_INPUTS
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(backtests):
        if not isinstance(raw, dict):
            raise TypeError("HISTORICAL_BACKTEST_NOT_OBJECT")
        strategy = raw.get("strategy")
        if not isinstance(strategy, str) or strategy not in strategy_indexes:
            raise ValueError("HISTORICAL_STRATEGY_IDENTITY_DRIFT")
        strategy_index = strategy_indexes[strategy]
        strategy_item = strategies[strategy_index]
        expert_item = expert_backtests[index]
        if not isinstance(strategy_item, dict) or not isinstance(expert_item, dict):
            raise TypeError("HISTORICAL_OCCURRENCE_NOT_OBJECT")

        projection = _source_projection(raw)
        projection_hash = _sha256_bytes(_canonical_bytes(projection))
        if _source_projection(strategy_item) != projection:
            raise ValueError("HISTORICAL_STRATEGY_PROJECTION_DRIFT")
        if _source_projection(expert_item) != projection:
            raise ValueError("HISTORICAL_EXPERT_PROJECTION_DRIFT")
        if set(strategy_item) ^ set(raw) != {"origin", "strategy_version"}:
            raise ValueError("HISTORICAL_STRATEGY_OBJECT_SHAPE_DRIFT")
        if raw != expert_item:
            raise ValueError("HISTORICAL_BACKTEST_EXPERT_OBJECT_DRIFT")

        bets = projection["bets"]
        if isinstance(bets, bool) or not isinstance(bets, int) or bets <= 0:
            raise ValueError("HISTORICAL_BETS_INVALID")
        profit = _assert_finite_number(projection["profit_units"], "HISTORICAL_PROFIT")
        stored_roi = _assert_finite_number(projection["stored_roi"], "HISTORICAL_ROI")
        stored_yield = _assert_finite_number(projection["stored_yield"], "HISTORICAL_YIELD")
        if projection["staking"] != "FIXED":
            raise ValueError("HISTORICAL_STAKING_NOT_FIXED")
        corrected_roi = profit / bets
        if math.isclose(stored_roi, corrected_roi, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("HISTORICAL_ROI_EXPECTED_MISMATCH_ABSENT")
        if not math.isclose(stored_yield, corrected_roi, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("HISTORICAL_YIELD_FIXED_ROI_MISMATCH")
        if projection["status"] != "INCONCLUSIVE":
            raise ValueError("HISTORICAL_STATUS_DRIFT")
        if projection["promotion"] != "NO_PROMOTION":
            raise ValueError("HISTORICAL_PROMOTION_DRIFT")
        if projection["production_status"] != "PRODUCTION_LOCKED":
            raise ValueError("HISTORICAL_PRODUCTION_LOCK_DRIFT")

        repair_projection = {
            **projection,
            "turnover_units": float(bets),
            "corrected_roi": corrected_roi,
            "corrected_yield": corrected_roi,
            "scientific_kernel_version": SCIENTIFIC_KERNEL_VERSION,
            "roi_definition_version": ROI_DEFINITION_VERSION,
            "turnover_definition_version": TURNOVER_DEFINITION_VERSION,
            "yield_definition_version": YIELD_DEFINITION_VERSION,
            "repair_status": ("INVALIDATE_STORED_ROI_PRESERVE_PROFIT_VOLUME_SIGN_AND_LOCK"),
        }
        result_id = f"V3-FIXED-{index + 1:03d}-{projection_hash[:12]}"
        occurrences = [
            {
                "occurrence_id": f"{result_id}-O1",
                "repo_path": "cockpit/app/cockpit-data.json",
                "json_pointer": f"/deepData/backtests/{index}",
                "source_artifact_sha256": artifact_hashes["cockpit/app/cockpit-data.json"],
                "source_artifact_hash_representation": "GIT_CANONICAL_LF",
                "audited_checkout_artifact_sha256": AUDITED_CHECKOUT_INPUTS[
                    "cockpit/app/cockpit-data.json"
                ],
                "source_object_sha256": _sha256_bytes(_canonical_bytes(raw)),
                "relation": "PRIMARY_SOURCE_OCCURRENCE",
            },
            {
                "occurrence_id": f"{result_id}-O2",
                "repo_path": "cockpit/app/cockpit-data.json",
                "json_pointer": f"/deepData/strategies/{strategy_index}",
                "source_artifact_sha256": artifact_hashes["cockpit/app/cockpit-data.json"],
                "source_artifact_hash_representation": "GIT_CANONICAL_LF",
                "audited_checkout_artifact_sha256": AUDITED_CHECKOUT_INPUTS[
                    "cockpit/app/cockpit-data.json"
                ],
                "source_object_sha256": _sha256_bytes(_canonical_bytes(strategy_item)),
                "relation": "COPY_OF",
                "copy_of": f"{result_id}-O1",
            },
            {
                "occurrence_id": f"{result_id}-O3",
                "repo_path": "cockpit/app/cockpit-expert-data.json",
                "json_pointer": f"/backtests/{index}",
                "source_artifact_sha256": artifact_hashes["cockpit/app/cockpit-expert-data.json"],
                "source_artifact_hash_representation": "GIT_CANONICAL_LF",
                "audited_checkout_artifact_sha256": AUDITED_CHECKOUT_INPUTS[
                    "cockpit/app/cockpit-expert-data.json"
                ],
                "source_object_sha256": _sha256_bytes(_canonical_bytes(expert_item)),
                "relation": "COPY_OF",
                "copy_of": f"{result_id}-O1",
            },
        ]
        results.append(
            {
                "logical_result_id": result_id,
                "strategy": strategy,
                "source_projection": projection,
                "source_projection_sha256": projection_hash,
                "repair_projection": repair_projection,
                "repair_projection_sha256": _sha256_bytes(_canonical_bytes(repair_projection)),
                "source_occurrences": occurrences,
                "original": {
                    "scientific_kernel_version": None,
                    "scientific_identity_status": "LEGACY_UNVERSIONED_NOT_CANONICAL",
                    "devig_method": "UNKNOWN",
                    "devig_version": "UNKNOWN",
                    "turnover_units": None,
                    "bets": bets,
                    "profit_units": profit,
                    "roi": stored_roi,
                    "yield": stored_yield,
                    "status": projection["status"],
                    "promotion": projection["promotion"],
                    "production_status": projection["production_status"],
                },
                "branches": {
                    "A": {
                        "label": "STORED_ARTIFACT_REPRODUCTION_ONLY",
                        "method": "UNKNOWN",
                        "turnover_units": None,
                        "profit_units": profit,
                        "roi": stored_roi,
                        "yield": stored_yield,
                        "bet_ids_hash": None,
                        "selection_ids_hash": None,
                        "evidence_status": "PROUVÉ",
                        "evidence_ids": ["E0025"],
                    },
                    "B": {
                        "label": ("FORMULA_REPLAY_FROM_STORED_PROFIT_AND_FIXED_STAKE_BET_COUNT"),
                        "method": "UNKNOWN",
                        "turnover_units": float(bets),
                        "profit_units": profit,
                        "roi": corrected_roi,
                        "yield": corrected_roi,
                        "bet_ids_hash": None,
                        "selection_ids_hash": None,
                        "evidence_status": "PROBABLE",
                        "evidence_ids": ["E0025", "E2008"],
                    },
                    "C": {
                        "label": "ALTERNATE_DEVIG_OLD_ROI",
                        "method": "ALTERNATE_EXPLICIT_METHOD",
                        "metrics": None,
                        "bet_ids_hash": None,
                        "selection_ids_hash": None,
                        "evidence_status": "NON VÉRIFIÉ",
                        "evidence_ids": ["E1040"],
                        "reason": "PER_BET_ODDS_AND_DECISIONS_NOT_PUBLISHED",
                    },
                    "D1": {
                        "label": "CORRECT_ROI_PLUS_PROPORTIONAL",
                        "method": "PROPORTIONAL",
                        "metrics": None,
                        "bet_ids_hash": None,
                        "selection_ids_hash": None,
                        "evidence_status": "NON VÉRIFIÉ",
                        "evidence_ids": ["E1040"],
                        "reason": "PER_BET_ODDS_AND_DECISIONS_NOT_PUBLISHED",
                    },
                    "D2": {
                        "label": "CORRECT_ROI_PLUS_SHIN",
                        "method": "SHIN",
                        "metrics": None,
                        "bet_ids_hash": None,
                        "selection_ids_hash": None,
                        "evidence_status": "NON VÉRIFIÉ",
                        "evidence_ids": ["E1040"],
                        "reason": "PER_BET_ODDS_AND_DECISIONS_NOT_PUBLISHED",
                    },
                },
                "attribution": {
                    "old_bets": bets,
                    "new_bets": bets,
                    "old_selections": "NOT_PUBLISHED",
                    "new_selections": "NOT_REPLAYED",
                    "old_turnover_units": None,
                    "new_turnover_units": float(bets),
                    "old_profit_units": profit,
                    "new_profit_units": profit,
                    "old_roi": stored_roi,
                    "new_roi": corrected_roi,
                    "old_yield": stored_yield,
                    "new_yield": corrected_roi,
                    "decision_changes": "NON VÉRIFIÉ",
                    "classification": "METRIC_ONLY_CHANGE_FOR_SUMMARY_ONLY",
                },
                "calculation_basis": "SUMMARY_FIXED_1U_INFERENCE",
                "evidence_status": "PROBABLE",
                "evidence_ids": ["E0025", "E2008"],
                "temporal_validity": "TEMPORAL_VALIDITY_NOT_PROVEN",
            }
        )

    if len(results) != 15:
        raise AssertionError("HISTORICAL_LOGICAL_RESULT_COUNT_DRIFT")
    if sum(len(item["source_occurrences"]) for item in results) != 45:
        raise AssertionError("HISTORICAL_PHYSICAL_OCCURRENCE_COUNT_DRIFT")
    if len({item["source_projection_sha256"] for item in results}) != 15:
        raise AssertionError("HISTORICAL_LOGICAL_PROJECTION_UNIQUENESS_DRIFT")
    return results


DEVIG_IMPLEMENTATIONS = [
    {
        "implementation_id": "legacy_shin_default",
        "audit_repo_path": "moteur/devig.py",
        "audit_function": "probas_justes -> devig_shin",
        "audit_line_range": "11-40",
        "audit_method": "SHIN",
        "audit_dynamic_path": "legacy Vague1 historical backtest",
        "audit_invalid_input_policy": "dispatcher returned None for nonfinite or odds<=1",
        "audit_output_contract": "normalized float ndarray or None",
        "audit_call_sites": [
            "moteur/marches.py",
            "agents/agent_backtest.py",
            "agents/agent_confrontation.py",
        ],
        "audit_tests": ["tests/test_moteur.py"],
        "current_anchor": "moteur/devig.py:19,31",
        "current_disposition": "EXPLICIT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "legacy_proportional",
        "audit_repo_path": "moteur/devig.py",
        "audit_function": "devig_proportionnel",
        "audit_line_range": "6-8",
        "audit_method": "PROPORTIONAL",
        "audit_dynamic_path": "counterfactual and legacy Shin fallback",
        "audit_invalid_input_policy": "no direct validation",
        "audit_output_contract": "float ndarray",
        "audit_call_sites": ["moteur/devig.py"],
        "audit_tests": [],
        "current_anchor": "moteur/devig.py:12",
        "current_disposition": "EXPLICIT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "operations_activation",
        "audit_repo_path": "src/robin/operations/activation.py",
        "audit_function": "normalized_market_probabilities",
        "audit_line_range": "42-66",
        "audit_method": "AVERAGE_ODDS_THEN_PROPORTIONAL",
        "audit_dynamic_path": "scheduled pre-match shadow prediction",
        "audit_invalid_input_policy": "None for missing lists or arithmetic mean <=1",
        "audit_output_contract": "three-float tuple or None",
        "audit_call_sites": ["scripts/run_shadow_pipeline.py"],
        "audit_tests": ["tests/jalon3/test_live_activation.py"],
        "current_anchor": "src/robin/operations/activation.py:44",
        "current_disposition": "EXPLICIT_CENTRAL_PROTOCOL",
    },
    {
        "implementation_id": "deep_football",
        "audit_repo_path": "src/robin/deep_football/models.py",
        "audit_function": "devig_1x2",
        "audit_line_range": "23-37",
        "audit_method": "PROPORTIONAL",
        "audit_dynamic_path": "test-only; no non-test caller found",
        "audit_invalid_input_policy": "raise for nonfinite or odds<=1",
        "audit_output_contract": "MatchProbabilities",
        "audit_call_sites": [],
        "audit_tests": ["tests/jalon11/test_models_statistics.py"],
        "current_anchor": "src/robin/deep_football/models.py:24",
        "current_disposition": "EXPLICIT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "backtesting_v3",
        "audit_repo_path": "src/robin/backtesting/v3.py",
        "audit_function": "devig_probabilities",
        "audit_line_range": "32-42",
        "audit_method": "PARTIAL_MARKET_PROPORTIONAL",
        "audit_dynamic_path": "run_backtest",
        "audit_invalid_input_policy": "missing or odds<=1 became None and remaining outcomes were renormalized",
        "audit_output_contract": "list with available subset summing to one",
        "audit_call_sites": ["src/robin/backtesting/v3.py:run_backtest"],
        "audit_tests": ["tests/jalon6/test_model_calibration_backtest.py"],
        "current_anchor": "src/robin/backtesting/v3.py:76,132",
        "current_disposition": "LOCAL_FORMULA_REMOVED_CENTRAL_DECISION",
    },
    {
        "implementation_id": "historical_dataset_factory",
        "audit_repo_path": "src/robin/historical/dataset_factory.py",
        "audit_function": "_devig",
        "audit_line_range": "204-208",
        "audit_method": "PARTIAL_MARKET_PROPORTIONAL",
        "audit_dynamic_path": "historical API-team dataset builder",
        "audit_invalid_input_policy": "missing or odds<=1 became None and available outcomes were renormalized",
        "audit_output_contract": "tuple with optional outcomes",
        "audit_call_sites": ["src/robin/historical/dataset_factory.py"],
        "audit_tests": ["tests/jalon6/test_dataset_and_player_features.py"],
        "current_anchor": "src/robin/historical/dataset_factory.py:210,290",
        "current_disposition": "LOCAL_FORMULA_REMOVED_CENTRAL_PROTOCOL",
    },
    {
        "implementation_id": "historical_external_validation",
        "audit_repo_path": "src/robin/historical/external_validation.py",
        "audit_function": "devig_market_odds",
        "audit_line_range": "868-875",
        "audit_method": "PROPORTIONAL_COMPLETE_MARKET",
        "audit_dynamic_path": "test-only static caller found",
        "audit_invalid_input_policy": "all None for missing or odds<=1",
        "audit_output_contract": "list or all None",
        "audit_call_sites": [],
        "audit_tests": ["tests/jalon8/test_external_validation.py"],
        "current_anchor": "src/robin/historical/external_validation.py:869",
        "current_disposition": "EXPLICIT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "historical_critical_closure",
        "audit_repo_path": "src/robin/historical/critical_closure.py",
        "audit_function": "proportional_devig",
        "audit_line_range": "485-494",
        "audit_method": "PROPORTIONAL_COMPLETE_MARKET",
        "audit_dynamic_path": "historical market dataset builder",
        "audit_invalid_input_policy": "rejected missing or odds<=0 but admitted 0<odds<=1",
        "audit_output_contract": "margin plus optional probabilities",
        "audit_call_sites": ["src/robin/historical/critical_closure.py"],
        "audit_tests": ["tests/jalon9/test_critical_closure.py"],
        "current_anchor": "src/robin/historical/critical_closure.py:491",
        "current_disposition": "EXPLICIT_STRICT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "historical_model_lab",
        "audit_repo_path": "src/robin/historical/model_lab.py",
        "audit_function": "_market_probabilities",
        "audit_line_range": "603-615",
        "audit_method": "PROPORTIONAL_COMPLETE_1X2",
        "audit_dynamic_path": "market-devigged baseline model",
        "audit_invalid_input_policy": "None for missing or odds<=1",
        "audit_output_contract": "three-float ndarray or None",
        "audit_call_sites": ["src/robin/historical/model_lab.py"],
        "audit_tests": ["tests/jalon6/test_model_calibration_backtest.py"],
        "current_anchor": "src/robin/historical/model_lab.py:610",
        "current_disposition": "EXPLICIT_CENTRAL_PROTOCOL",
    },
    {
        "implementation_id": "modeling_reference",
        "audit_repo_path": "src/robin/modeling/reference.py",
        "audit_function": "market_probabilities",
        "audit_line_range": "169-178",
        "audit_method": "PROPORTIONAL_1X2",
        "audit_dynamic_path": "test-only static caller found",
        "audit_invalid_input_policy": "no local validation",
        "audit_output_contract": "MatchProbabilities or validation exception",
        "audit_call_sites": [],
        "audit_tests": ["tests/jalon2/test_migration_models.py"],
        "current_anchor": "src/robin/modeling/reference.py:170",
        "current_disposition": "EXPLICIT_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "prequential_factory",
        "audit_repo_path": "src/robin/prospective_observatory/prequential_factory.py",
        "audit_function": "devig_probabilities",
        "audit_line_range": "37-57",
        "audit_method": "PROPORTIONAL_EXACT_SELECTION_SET",
        "audit_dynamic_path": "prequential reference forecast",
        "audit_invalid_input_policy": "raise for wrong selection set or odds<=1",
        "audit_output_contract": "probability mapping plus overround",
        "audit_call_sites": ["src/robin/prospective_observatory/prequential_factory.py"],
        "audit_tests": ["tests/jalon14/test_prequential_factory.py"],
        "current_anchor": "src/robin/prospective_observatory/prequential_factory.py:45",
        "current_disposition": "EXPLICIT_PROPORTIONAL_ONLY_CENTRAL_ADAPTER",
    },
    {
        "implementation_id": "chronos_complete_market",
        "audit_repo_path": "src/robin/prospective_observatory/chronos.py",
        "audit_function": "derive_complete_book_markets",
        "audit_line_range": "556-630",
        "audit_method": "PROPORTIONAL_COMPLETE_SAME_RECEIPT",
        "audit_dynamic_path": "Chronos CANARY point-in-time price derivation",
        "audit_invalid_input_policy": "drop incomplete, invalid, underround or overround>6% markets",
        "audit_output_contract": "derived price rows or empty tuple",
        "audit_call_sites": ["Chronos materialization contract"],
        "audit_tests": ["tests/chronos/test_chronos_contracts_v1.py"],
        "current_anchor": "src/robin/prospective_observatory/chronos.py:556-630",
        "current_disposition": "FROZEN_SCOPED_DECIMAL_AUTHORITY_UNCHANGED",
    },
    {
        "implementation_id": "historical_pipeline_inline",
        "audit_repo_path": "scripts/run_historical_pipeline.py",
        "audit_function": "_market_prediction_rows",
        "audit_line_range": "1460-1503",
        "audit_method": "PROPORTIONAL_COMPLETE_1X2_INLINE",
        "audit_dynamic_path": "historical scientific arena baseline",
        "audit_invalid_input_policy": "skipped conversion/nonfinite but admitted some odds<=1",
        "audit_output_contract": "prediction rows or skipped market",
        "audit_call_sites": ["scripts/run_historical_pipeline.py"],
        "audit_tests": ["tests/jalon6/test_scientific_truth_kernel_v1.py"],
        "current_anchor": "scripts/run_historical_pipeline.py:1471,1488",
        "current_disposition": "INLINE_FORMULA_REMOVED_CENTRAL_PROTOCOL",
    },
    {
        "implementation_id": "backtesting_oos_inline",
        "audit_repo_path": "src/robin/backtesting/oos.py",
        "audit_function": "evaluate_walk_forward inline normalization",
        "audit_line_range": "185-198",
        "audit_method": "PROPORTIONAL_COMPLETE_1X2_INLINE",
        "audit_dynamic_path": "OOS value strategies",
        "audit_invalid_input_policy": "skip unless all three odds were present and >1",
        "audit_output_contract": "local fair-probability list",
        "audit_call_sites": ["src/robin/backtesting/oos.py"],
        "audit_tests": ["tests/jalon6/test_scientific_truth_kernel_v1.py"],
        "current_anchor": "src/robin/backtesting/oos.py:174,250,297",
        "current_disposition": "INLINE_FORMULA_REMOVED_CENTRAL_PROTOCOL",
    },
    {
        "implementation_id": "shadow_raw_implied_not_devig",
        "audit_repo_path": "src/robin/shadow/decision.py",
        "audit_function": "decide_shadow_bet",
        "audit_line_range": "54-118",
        "audit_method": "RAW_IMPLIED_NOT_DEVIG",
        "audit_dynamic_path": "scheduled pre-match shadow decision",
        "audit_invalid_input_policy": "truthiness only; negative admitted",
        "audit_output_contract": "single raw implied probability",
        "audit_call_sites": ["scripts/run_shadow_pipeline.py"],
        "audit_tests": ["tests/jalon2/test_decisions_pipeline_workflows.py"],
        "current_anchor": "src/robin/shadow/decision.py:80,130",
        "current_disposition": "COMPLETE_MARKET_CENTRAL_DECISION_WITH_EXECUTION_LINEAGE",
    },
]


def _audit_source(evidence_ids: list[str]) -> dict[str, Any]:
    qualified = [_qualify_evidence_id(item) for item in evidence_ids]
    return {
        "target_sha": AUDITED_REVISION,
        "target_tree": AUDITED_TREE,
        "manifest_sha256": AUDIT_MANIFEST_SHA256,
        "evidence_ids": [item for item in qualified if item.startswith("AUDIT:")],
        "logical_root": AUDIT_LOGICAL_PATH,
    }


def _loop54_source(evidence_ids: list[str]) -> dict[str, Any]:
    qualified = [_qualify_evidence_id(item) for item in evidence_ids]
    return {
        "repair_sha": REPAIR_REVISION,
        "manifest_sha256": LOOP54_MANIFEST_SHA256,
        "evidence_ids": [item for item in qualified if item.startswith("LOOP54:")],
        "logical_root": LOOP54_LOGICAL_PATH,
        "status": "SEALED_EXTERNAL_EVIDENCE_PACK",
    }


def _source(relative: str, sha256: str, evidence_ids: list[str]) -> dict[str, Any]:
    return {
        "repo_or_evidence_path": relative,
        "sha256": sha256,
        "evidence_ids": [_evidence_ref(item) for item in evidence_ids],
    }


def _base_report(
    filename: str,
    *,
    scope: str,
    grain: str,
    temporal_class: str,
    evidence_status: str,
    evidence_ids: list[str],
    sources: list[dict[str, Any]],
    limitations: list[str],
    non_claims: list[str],
    verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    report_id, claim_id = REPORT_SPECS[filename]
    generator_sha = _sha256_repository_file(ROOT / GENERATOR_PATH)
    return {
        "schema_version": "robin-scientific-truth-report-v1",
        "report_id": report_id,
        "mission_id": "SCIENTIFIC_TRUTH_KERNEL",
        "scientific_kernel_version": SCIENTIFIC_KERNEL_VERSION,
        "claim_id": claim_id,
        "generated_at": GENERATED_AT,
        "source_code_revision": REPAIR_REVISION,
        "commit1_revision": REPAIR_REVISION,
        "immutable_audit_base_revision": AUDITED_REVISION,
        "scope": scope,
        "grain": grain,
        "temporal_class": temporal_class,
        "as_of": GENERATED_AT,
        "evidence_status": evidence_status,
        "authority": {
            "global_devig_authority": "CONFLICTING",
            "basis": "PROTOCOL_SCOPE_NOT_HISTORICAL_PERFORMANCE",
            "roi_used_for_authority": False,
            "global_selected_method": None,
            "chronos_scoped_authority": {
                "status": "UNIQUE",
                "scope": "CANARY_POINT_IN_TIME_COMPLETE_SAME_RECEIPT_ONLY",
                "method": "PROPORTIONAL_COMPLETE_MARKET_V1",
                "global_authority": False,
            },
        },
        "generator": {
            "repo_path": GENERATOR_PATH,
            "sha256": generator_sha,
            "hash_representation": "GIT_CANONICAL_LF",
            "deterministic_timestamp_source": "COMMIT1_COMMIT_TIME_UTC",
        },
        "hash_policy": {
            "tracked_repository_text": "SHA256_GIT_CANONICAL_LF_BYTES",
            "external_evidence_pack_files": "SHA256_RAW_BYTES",
            "audited_windows_checkout_hashes_preserved_separately": True,
        },
        "audit_source": _audit_source(evidence_ids),
        "loop54_source": _loop54_source(evidence_ids),
        "report_generation_receipt": {
            "namespace": "LOOP54_REPORTS",
            "evidence_id": LOOP54_REPORTS_EVIDENCE_ID,
            "logical_root": LOOP54_REPORTS_LOGICAL_PATH,
            "binding": "DETACHED_MANIFEST_CLAIM_IN_EVIDENCE_GRAPH",
        },
        "sources": sources,
        "reproducibility": {
            "input_hashes": [
                {"path": item["repo_or_evidence_path"], "sha256": item["sha256"]}
                for item in sources
            ],
            "seed": None,
            "command_evidence_ids": [LOOP54_REPORTS_EVIDENCE_ID],
            "generation_command": (
                "python -m scripts.build_scientific_truth_reports_v1 "
                "--audit-root <verified-audit-pack-root> "
                "--loop54-root <verified-loop54-pack-root> --check"
            ),
        },
        "reviews": {
            "scientific_statistical": "PENDING_INDEPENDENT_FINAL_REVIEW",
            "data_temporal": "PENDING_INDEPENDENT_FINAL_REVIEW",
            "security_red_team": "PENDING_INDEPENDENT_FINAL_REVIEW",
        },
        "review_status": "PENDING_INDEPENDENT_REVIEW",
        "verified_by": [],
        "external_effects": dict(EXTERNAL_EFFECTS_ZERO),
        "limitations": limitations,
        "non_claims": non_claims,
        "verdicts": verdicts,
    }


def _build_defect_inventory() -> dict[str, Any]:
    filename = "scientific-truth-defect-inventory-v1.json"
    defects = [
        {
            "defect_id": "SCI54-ROI-001",
            "severity": "P1",
            "component": "backtesting-v3",
            "repo_path": "src/robin/backtesting/v3.py",
            "line_anchor": "run_backtest performance summary",
            "finding_id": "SCI-002",
            "original_behavior": "roi=profit/sum(abs(realized_profit))",
            "required_behavior": "roi=profit_units/actual_turnover_units",
            "consequence": "45 stored FIXED ROI fields differ from turnover ROI",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0016", "E0023", "E0025", "E2008"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-YIELD-002",
            "severity": "P1",
            "component": "performance-metadata",
            "repo_path": "src/robin/market_math/truth.py",
            "line_anchor": "performance_summary",
            "finding_id": "SCI-002",
            "original_behavior": "yield named profit/bet count and diverged under non-unit stakes",
            "required_behavior": "yield=roi=profit/turnover; profit_per_bet separate",
            "consequence": "metric name could conceal a denominator change",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0023", "E0027", "E3068"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-DEVIG-003",
            "severity": "P1",
            "component": "de-vig-active-paths",
            "repo_path": "src/robin/market_math/devig.py",
            "line_anchor": "devig_probabilities",
            "finding_id": "SCI-003",
            "original_behavior": "15 mechanisms had divergent method and invalid-market semantics",
            "required_behavior": "explicit method, version, complete-market contract and deterministic errors",
            "consequence": "same market could yield different decisions across active paths",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0017", "E1012", "E1016", "E1040", "E1044"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-STAKING-004",
            "severity": "P1",
            "component": "staking-bankroll",
            "repo_path": "src/robin/market_math/truth.py",
            "line_anchor": "stake_units",
            "finding_id": "LOOP54-RED-STAKING",
            "original_behavior": "fixed stake could exceed remaining bankroll and crash the next bet",
            "required_behavior": "every stake is bounded by stake cap and current bankroll",
            "consequence": "ruin sequences could create negative bankroll or abort a batch",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0026"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-SETTLEMENT-005",
            "severity": "P1",
            "component": "backtest-settlement",
            "repo_path": "src/robin/backtesting/v3.py",
            "line_anchor": "target validation and settlement",
            "finding_id": "LOOP54-RED-TARGET",
            "original_behavior": "out-of-domain targets were silently settled as losses",
            "required_behavior": "target must belong to the selected market domain",
            "consequence": "corrupt outcomes could change profit and ROI",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0026"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-SHADOW-006",
            "severity": "P1",
            "component": "shadow-decision-identity",
            "repo_path": "src/robin/shadow/decision.py",
            "line_anchor": "decision identity and journal append",
            "finding_id": "LOOP54-RED-SHADOW",
            "original_behavior": "different complete markets could collide and be silently deduplicated",
            "required_behavior": "full decision input identity plus append conflict/supersession semantics",
            "consequence": "accepted and rejected decisions could share one identity",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0026", "E1042"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-PREQUENT-007",
            "severity": "P1",
            "component": "prequential-persistence",
            "repo_path": "src/robin/prospective_observatory/prequential_persistence.py",
            "line_anchor": "load_predictions",
            "finding_id": "LOOP54-DATA-PREQUENTIAL",
            "original_behavior": "reload could publish a reconstructed current hash as persisted identity",
            "required_behavior": "preserve stored identity and mark legacy scientific lineage not persisted",
            "consequence": "historical scientific identity could be reinterpreted after a version change",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0026"],
            "status": "RESOLVED_IN_CODE",
            "resolved": True,
            "resolution_evidence_ids": ["E0026"],
        },
        {
            "defect_id": "SCI54-TEMPORAL-008",
            "severity": "P2",
            "component": "point-in-time-lineage",
            "repo_path": "reports/scientific-truth/historical-truth-replay-v1.json",
            "line_anchor": "temporal",
            "finding_id": "TEMPORAL-LINEAGE-OPEN",
            "original_behavior": "72 audited surfaces lack complete point-in-time proof",
            "required_behavior": "availability and as-of lineage must be proven in LOOP55",
            "consequence": "mathematical repair cannot establish causal or point-in-time validity",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E2013"],
            "status": "NOT_IN_SCOPE",
            "resolved": False,
            "resolution_evidence_ids": [],
        },
        {
            "defect_id": "SCI54-HISTORICAL-009",
            "severity": "P2",
            "component": "historical-decision-replay",
            "repo_path": "reports/scientific-truth/historical-truth-replay-v1.json",
            "line_anchor": "branches C D1 D2",
            "finding_id": "HISTORICAL-DEVIG-REPLAY-OPEN",
            "original_behavior": "published aggregates contain no per-bet odds, selections or de-vig identity",
            "required_behavior": "replay from observation-level frozen inputs under each explicit method",
            "consequence": "only formula repair, not portfolio replay, is supportable",
            "evidence_status": "PROUVÉ",
            "evidence_ids": ["E0025", "E1040"],
            "status": "REPLAY_REQUIRED",
            "resolved": False,
            "resolution_evidence_ids": [],
        },
        {
            "defect_id": "SCI54-PROJECTION-010",
            "severity": "P2",
            "component": "legacy-prospective-projection",
            "repo_path": "scripts/run_prospective_observatory.py",
            "line_anchor": "strict complete positive-overround projection",
            "finding_id": "LEGACY-PROJECTION-REBUILD-OPEN",
            "original_behavior": "old SQL projections may include clamped underround or incomplete markets",
            "required_behavior": "separately authorized rebuild or migration with parity evidence",
            "consequence": "strict replay can fail closed against legacy PostgreSQL state",
            "evidence_status": "PROBABLE",
            "evidence_ids": ["E0026"],
            "status": "NOT_IN_SCOPE",
            "resolved": False,
            "resolution_evidence_ids": [],
        },
    ]
    severity = Counter(item["severity"] for item in defects)
    report = _base_report(
        filename,
        scope="BOUNDED_SCIENTIFIC_TRUTH_KERNEL_DEFECTS",
        grain="ONE_RECORD_PER_REPRODUCED_DEFECT_OR_RESIDUAL_LIMITATION",
        temporal_class="MIXED_STATIC_AND_BOUNDED_OFFLINE_EXECUTION",
        evidence_status="PROUVÉ",
        evidence_ids=["E0016", "E0017", "E0023", "E0025", "E0026", "E1012", "E2013"],
        sources=[
            _source(
                "src/robin/market_math/truth.py",
                _sha256_repository_file(ROOT / "src/robin/market_math/truth.py"),
                ["E0026"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/findings.json",
                AUDIT_FILES["findings.json"],
                ["E0023", "E1012", "E2013"],
            ),
        ],
        limitations=[
            "Historical aggregate repair is not an observation-level decision replay.",
            "Point-in-time validity remains outside LOOP54 and not proven.",
        ],
        non_claims=[
            "No global de-vig method was selected.",
            "No historical result is promoted or declared scientifically validated.",
        ],
        verdicts=[
            {
                "verdict": "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL",
                "evidence_ids": ["E0026", "E2013"],
            },
            {"verdict": "PASS_AND_HOLD", "evidence_ids": ["E0026"]},
        ],
    )
    report.update(
        {
            "severity_definition": {
                "P0": "temporal leakage proven, false promotable result, or unauthorized write/bet",
                "P1": "wrong scientific calculation, path inconsistency, or unsupported valid history",
                "P2": "missing lineage, incomplete diagnostic, or ambiguity needed for replay",
                "P3": "readability or nonessential cleanup",
            },
            "defects": defects,
            "counts": {
                "total": len(defects),
                "p0": severity["P0"],
                "p1": severity["P1"],
                "p2": severity["P2"],
                "p3": severity["P3"],
                "open_p0": sum(
                    item["severity"] == "P0" and not item["resolved"] for item in defects
                ),
                "open_p1": sum(
                    item["severity"] == "P1" and not item["resolved"] for item in defects
                ),
                "essential_p2_open": sum(
                    item["severity"] == "P2" and not item["resolved"] for item in defects
                ),
            },
        }
    )
    return _with_content_hash(report)


def _build_roi_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    filename = "roi-turnover-repair-v1.json"
    errors = [abs(item["original"]["roi"] - item["branches"]["B"]["roi"]) for item in results]
    report = _base_report(
        filename,
        scope="ROI_TURNOVER_YIELD_AND_PROFIT_PER_BET",
        grain="DEFINITION_PLUS_15_LOGICAL_AND_45_PHYSICAL_HISTORICAL_SUMMARIES",
        temporal_class="TIME_INVARIANT_ARITHMETIC_WITH_HISTORICAL_AGGREGATES",
        evidence_status="PROUVÉ",
        evidence_ids=["E0016", "E0023", "E0025", "E0027", "E2001", "E2008", "E3068"],
        sources=[
            _source(
                "src/robin/market_math/truth.py",
                _sha256_repository_file(ROOT / "src/robin/market_math/truth.py"),
                ["E0026"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/backtest-v3-historical-roi-replay.csv",
                AUDIT_FILES["tables/backtest-v3-historical-roi-replay.csv"],
                ["E0025"],
            ),
            *[_source(path, sha, ["E0025"]) for path, sha in REPOSITORY_INPUTS.items()],
        ],
        limitations=[
            "The 15 historical corrections use declared FIXED staking and aggregate bet count; per-bet stakes were not published.",
            "No de-vig or portfolio replay is inferred from the aggregate objects.",
        ],
        non_claims=[
            "Corrected ROI does not validate data lineage, model quality, or profitability.",
            "Stored historical JSON is preserved and not rewritten.",
        ],
        verdicts=[
            {
                "verdict": "ROBIN_ROI_TURNOVER_DEFINITION_CORRECTED",
                "evidence_ids": ["E0016", "E0026"],
            },
            {"verdict": "ROBIN_YIELD_SEMANTICS_UNAMBIGUOUS", "evidence_ids": ["E0026", "E3068"]},
        ],
    )
    report.update(
        {
            "definitions": {
                "profit_units": "sum(detail.profit)",
                "turnover_units": "sum(detail.stake)",
                "roi": "profit_units / turnover_units if turnover_units > 0 else null",
                "yield": "roi",
                "profit_per_bet": "profit_units / bets if bets > 0 else null",
                "ending_bankroll_units": "starting_bankroll_units + profit_units",
            },
            "definition_versions": {
                "roi": ROI_DEFINITION_VERSION,
                "turnover": TURNOVER_DEFINITION_VERSION,
                "yield": YIELD_DEFINITION_VERSION,
                "profit_per_bet": PROFIT_PER_BET_DEFINITION_VERSION,
            },
            "synthetic_red_proof": {
                "stakes": [1.0, 1.0],
                "profits": [2.0, -1.0],
                "expected_turnover_units": 2.0,
                "expected_profit_units": 1.0,
                "old_roi": 1.0 / 3.0,
                "expected_roi": 0.5,
                "evidence_ids": ["E0016", "E3068"],
            },
            "code_paths": [
                {
                    "repo_path": "src/robin/market_math/truth.py",
                    "function": "performance_summary",
                    "status": "CANONICAL",
                },
                {
                    "repo_path": "src/robin/backtesting/v3.py",
                    "function": "run_backtest",
                    "status": "CANONICAL_DELEGATE",
                },
                {
                    "repo_path": "src/robin/backtesting/oos.py",
                    "function": "evaluate_walk_forward",
                    "status": "CANONICAL_DELEGATE",
                },
                {
                    "repo_path": "src/robin/historical_deep/backtest.py",
                    "function": "fold summaries",
                    "status": "CANONICAL_DELEGATE",
                },
            ],
            "output_metadata_versions": {
                "scientific_kernel_version": SCIENTIFIC_KERNEL_VERSION,
                "roi_definition_version": ROI_DEFINITION_VERSION,
                "turnover_definition_version": TURNOVER_DEFINITION_VERSION,
                "yield_definition_version": YIELD_DEFINITION_VERSION,
                "profit_per_bet_definition_version": PROFIT_PER_BET_DEFINITION_VERSION,
                "decision_threshold_version": DECISION_THRESHOLD_VERSION,
                "staking_version": STAKING_VERSION,
                "settlement_version": SETTLEMENT_VERSION,
            },
            "historical_scope": {
                "logical_results": 15,
                "physical_occurrences": 45,
                "stored_roi_mismatches": 45,
                "stored_yield_matches_fixed_1u_turnover_roi": 45,
                "minimum_absolute_roi_error": min(errors),
                "maximum_absolute_roi_error": max(errors),
                "profit_sign_changes": 0,
                "status_changes": 0,
                "promotion_changes": 0,
                "production_lock_changes": 0,
            },
        }
    )
    return _with_content_hash(report)


def _build_yield_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    filename = "yield-consumer-inventory-v1.json"
    occurrences = [
        {
            "logical_result_id": result["logical_result_id"],
            "occurrence_id": occurrence["occurrence_id"],
            "repo_path": occurrence["repo_path"],
            "json_pointer": occurrence["json_pointer"],
            "stored_yield": result["original"]["yield"],
            "corrected_fixed_1u_roi": result["branches"]["B"]["roi"],
            "relation": occurrence["relation"],
        }
        for result in results
        for occurrence in result["source_occurrences"]
    ]
    report = _base_report(
        filename,
        scope="YIELD_FIELD_SEMANTICS_AND_CONSUMERS",
        grain="ONE_CONSUMER_OR_ONE_HISTORICAL_FIELD_OCCURRENCE",
        temporal_class="STATIC_SOURCE_AND_TRACKED_HISTORICAL_SNAPSHOT",
        evidence_status="PROUVÉ",
        evidence_ids=["E0025", "E0027", "E2002", "E2003", "E3068"],
        sources=[
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/report-metric-propagation.csv",
                AUDIT_FILES["tables/report-metric-propagation.csv"],
                ["E2002"],
            ),
            *[_source(path, sha, ["E0025"]) for path, sha in REPOSITORY_INPUTS.items()],
        ],
        limitations=[
            "Text matches of Python generator keyword yield are excluded from metric consumers.",
            "Historical FIXED objects do not establish variable-stake behavior.",
        ],
        non_claims=[
            "The 45 stored yield fields are not invalidated; under FIXED 1u they already equal profit/turnover.",
        ],
        verdicts=[
            {"verdict": "ROBIN_YIELD_SEMANTICS_UNAMBIGUOUS", "evidence_ids": ["E0026", "E3068"]}
        ],
    )
    report.update(
        {
            "definition": {
                "yield": "profit_units / turnover_units",
                "yield_definition_version": YIELD_DEFINITION_VERSION,
                "profit_per_bet": "profit_units / bets",
                "profit_per_bet_definition_version": PROFIT_PER_BET_DEFINITION_VERSION,
                "zero_turnover": None,
            },
            "consumers": [
                {
                    "repo_path": "src/robin/backtesting/v3.py",
                    "role": "producer",
                    "status": "CANONICAL",
                },
                {
                    "repo_path": "src/robin/backtesting/oos.py",
                    "role": "producer/serializer",
                    "status": "CANONICAL_NULLABLE",
                },
                {
                    "repo_path": "src/robin/market_math/truth.py",
                    "role": "definition authority",
                    "status": "CANONICAL",
                },
                {
                    "repo_path": "scripts/build_cockpit_snapshot.py",
                    "role": "presentation consumer",
                    "status": "NULL_SAFE_PRESENTATION",
                },
                {
                    "repo_path": "scripts/run_oos_backtest.py",
                    "role": "report serializer",
                    "status": "CANONICAL_METADATA",
                },
                {
                    "repo_path": "scripts/run_historical_pipeline.py",
                    "role": "historical result consumer",
                    "status": "CANONICAL_METADATA",
                },
                {
                    "repo_path": "src/robin/prospective_observatory/prequential_contracts.py",
                    "role": "lineage carrier",
                    "status": "VERSION_METADATA_ONLY",
                },
                {
                    "repo_path": "src/robin/shadow/decision.py",
                    "role": "lineage carrier",
                    "status": "VERSION_METADATA_ONLY",
                },
                {
                    "repo_path": "cockpit/app/cockpit-data.json",
                    "role": "historical rendered artifact",
                    "status": "PRESERVED_LEGACY_FIXED_1U",
                },
                {
                    "repo_path": "cockpit/app/cockpit-expert-data.json",
                    "role": "historical rendered artifact",
                    "status": "PRESERVED_LEGACY_FIXED_1U",
                },
            ],
            "historical_occurrences": occurrences,
            "counts": {
                "logical_results": 15,
                "physical_occurrences": 45,
                "cockpit_data_backtests": 15,
                "cockpit_data_strategies": 15,
                "cockpit_expert_backtests": 15,
                "fixed_staking": 45,
                "stored_yield_matches_repaired_fixed_1u_roi": 45,
                "stored_yield_invalidated": 0,
            },
        }
    )
    return _with_content_hash(report)


def _build_devig_inventory() -> dict[str, Any]:
    filename = "devig-implementation-inventory-v1.json"
    if (
        len(DEVIG_IMPLEMENTATIONS) != 15
        or len({item["implementation_id"] for item in DEVIG_IMPLEMENTATIONS}) != 15
    ):
        raise AssertionError("DEVIG_IMPLEMENTATION_INVENTORY_COUNT_DRIFT")
    report = _base_report(
        filename,
        scope="AUDITED_15_DEVIG_AND_RAW_IMPLIED_MECHANISMS",
        grain="ONE_AUDITED_IMPLEMENTATION_OR_DECISION_PROBABILITY_MECHANISM",
        temporal_class="STATIC_SOURCE_AT_AUDITED_AND_REPAIR_REVISIONS",
        evidence_status="PROUVÉ",
        evidence_ids=["E1012", "E1016", "E1027", "E1030", "E1035", "E1040", "E1044"],
        sources=[
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/devig-implementations.csv",
                AUDIT_FILES["tables/devig-implementations.csv"],
                ["E1012", "E1016"],
            ),
            _source(
                "src/robin/market_math/devig.py",
                _sha256_repository_file(ROOT / "src/robin/market_math/devig.py"),
                ["E0026"],
            ),
        ],
        limitations=[
            "The inventory preserves the 15 audited mechanisms; the new central kernel is a repair authority, not a sixteenth historical mechanism.",
            "Chronos remains a separate Decimal implementation frozen to its exact CANARY scope.",
        ],
        non_claims=[
            "Inventory membership does not confer global authority.",
            "The raw implied shadow mechanism was not de-vig and is retained to expose the historical decision basis.",
        ],
        verdicts=[
            {
                "verdict": "DEVIG_IMPLEMENTATION_INVENTORY_15_PROVEN",
                "evidence_ids": ["E1012", "E1016"],
            },
            {"verdict": "DEVIG_PROTOCOL_CONFLICT", "evidence_ids": ["E1035", "E1040"]},
        ],
    )
    report.update(
        {
            "implementation_count": 15,
            "implementations": DEVIG_IMPLEMENTATIONS,
            "historical_method_counts": {
                "SHIN_DECLARED_DEFAULT": 1,
                "PROPORTIONAL_OR_PROPORTIONAL_VARIANT": 13,
                "RAW_IMPLIED_NOT_DEVIG": 1,
            },
            "post_audit_kernel": {
                "repo_path": "src/robin/market_math/devig.py",
                "role": "EXPLICIT_VERSIONED_EXECUTION_AUTHORITY",
                "historical_implementation_count_increment": 0,
                "supported_methods": ["PROPORTIONAL", "SHIN"],
            },
            "conflict": {
                "shin_and_proportional_coexist": True,
                "decision_changes_proven": True,
                "global_authority": "CONFLICTING",
                "evidence_ids": ["E1040", "E1044"],
            },
        }
    )
    return _with_content_hash(report)


def _build_devig_canonicalization() -> dict[str, Any]:
    filename = "devig-canonicalization-v1.json"
    proportional = kernel_versions("PROPORTIONAL")
    shin = kernel_versions("SHIN")
    report = _base_report(
        filename,
        scope="DEVIG_PROTOCOL_REGISTRY_AUTHORITY_AND_SCOPED_RESOLUTION",
        grain="ONE_METHOD_SPEC_OR_AUTHORITY_SCOPE",
        temporal_class="VERSIONED_PROTOCOL_DECISION",
        evidence_status="PROUVÉ",
        evidence_ids=["E1012", "E1016", "E1027", "E1030", "E1035", "E1040", "E1044"],
        sources=[
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/devig-documentation-vs-execution.csv",
                AUDIT_FILES["tables/devig-documentation-vs-execution.csv"],
                ["E1012", "E1035"],
            ),
            _source(
                "src/robin/market_math/devig.py",
                _sha256_repository_file(ROOT / "src/robin/market_math/devig.py"),
                ["E0026"],
            ),
            _source(
                "configs/prices/point-in-time-price-contract-v1.json",
                _sha256_repository_file(
                    ROOT / "configs/prices/point-in-time-price-contract-v1.json"
                ),
                ["E1012"],
            ),
        ],
        limitations=[
            "No repository-global ex-ante protocol resolves legacy Shin and modern proportional authorities.",
            "The OOS and synthetic divergence evidence measures sensitivity and cannot select a winner.",
        ],
        non_claims=[
            "The explicit API is not a declaration that proportional is globally canonical.",
            "Chronos scoped authority is not generalized beyond complete same-receipt CANARY markets.",
        ],
        verdicts=[
            {"verdict": "DEVIG_PROTOCOL_CONFLICT", "evidence_ids": ["E1035", "E1040", "E1044"]},
            {
                "verdict": "DEVIG_DECISION_PATH_PARITY_PROVEN_BOUNDED_FIXTURES",
                "evidence_ids": ["E0017", "E0026"],
            },
        ],
    )
    report.update(
        {
            "protocol_resolution": {
                "verdict": "DEVIG_PROTOCOL_CONFLICT",
                "canonical_method": None,
                "canonical_version": None,
                "authority_reviewers": ["DP5", "DP6", "C4"],
                "rationale": "legacy Shin and proportional authorities overlap without one global ex-ante scope decision; ROI is prohibited as tie-breaker",
                "roi_used_for_authority": False,
                "evidence_ids": ["E1012", "E1016", "E1035", "E1040", "E1044"],
            },
            "supported_methods": [
                {
                    "method_id": proportional["devig_method"],
                    "version": proportional["devig_version"],
                    "definition_hash": proportional["devig_definition_hash"],
                    "formula": "q_i=1/odds_i; p_i=q_i/sum(q)",
                    "completeness": "COMPLETE_LABELLED_MARKET_REQUIRED",
                    "invalid_policy": "RAISE_DEVIG_INPUT_ERROR",
                },
                {
                    "method_id": shin["devig_method"],
                    "version": shin["devig_version"],
                    "definition_hash": shin["devig_definition_hash"],
                    "formula": "LEGACY_SHIN_FIXED_POINT_Z_WITH_FROZEN_BOUNDS",
                    "completeness": "COMPLETE_LABELLED_MARKET_REQUIRED",
                    "invalid_policy": "RAISE_DEVIG_INPUT_ERROR",
                    "effective_method_policy": "TWO_OUTCOME_OR_UNDERROUND_PROPORTIONAL_WITH_EXPLICIT_REASON",
                },
            ],
            "shared_contract": {
                "complete_market": True,
                "odds_gt_1": True,
                "label_uniqueness": True,
                "normalization_tolerance": 1e-12,
                "invalid_policy": "DETERMINISTIC_FAIL_CLOSED",
                "no_silent_fallback": True,
                "unknown_method": "ERROR",
                "missing_method": "ERROR",
            },
            "scope_resolution": [
                {"scope": "REPOSITORY_GLOBAL", "status": "CONFLICTING", "method": None},
                {
                    "scope": "CHRONOS_CANARY_POINT_IN_TIME_COMPLETE_SAME_RECEIPT",
                    "status": "UNIQUE",
                    "method": "PROPORTIONAL_COMPLETE_MARKET_V1",
                },
                {
                    "scope": "LEGACY_VAGUE1_REPLAY_3WAY",
                    "status": "UNIQUE_OBSERVED_LEGACY",
                    "method": "LEGACY_SHIN_VAGUE1_V1",
                },
                {"scope": "UNDER_SPECIFIED_HISTORICAL_ARTIFACTS", "status": "NONE", "method": None},
            ],
            "caller_bindings": [
                {
                    "caller": item["current_anchor"],
                    "declared_method": "EXPLICIT_OR_SCOPED",
                    "reason": item["current_disposition"],
                    "evidence_ids": ["E0026"],
                }
                for item in DEVIG_IMPLEMENTATIONS
                if item["implementation_id"] != "chronos_complete_market"
            ],
            "parity_cases": [
                {
                    "fixture": "balanced_1x2_proportional",
                    "result": "PASS",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0017", "E0026"],
                },
                {
                    "fixture": "complete_shadow_market_identity",
                    "result": "PASS",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
                {
                    "fixture": "invalid_missing_duplicate_nonfinite_odds",
                    "result": "PASS_FAIL_CLOSED",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
            ],
            "historical_replay_requirement": {
                "status": "REPLAY_REQUIRED",
                "reason": "published 15-result aggregates omit method identity and per-bet inputs",
                "methods": ["PROPORTIONAL", "SHIN"],
                "no_winner_designation": True,
                "evidence_ids": ["E0025", "E1040"],
            },
            "sensitivity_evidence": {
                "oos_complete_markets": 1563,
                "oos_bet_no_bet_divergences": 51,
                "synthetic_markets": 20000,
                "synthetic_bet_no_bet_divergence_rate": 0.1011,
                "selection_use": "SENSITIVITY_ONLY_NOT_AUTHORITY",
                "evidence_ids": ["E1040", "E1044"],
            },
        }
    )
    return _with_content_hash(report)


def _build_decision_trace() -> dict[str, Any]:
    filename = "decision-path-trace-v1.json"
    odds = (2.0, 3.2, 4.0)
    model_probabilities = (0.60, 0.25, 0.15)
    decision = decide_market(
        odds,
        model_probabilities,
        method="PROPORTIONAL",
        threshold=0.04,
        outcome_labels=("HOME", "DRAW", "AWAY"),
    )
    stake = stake_units(
        probability=model_probabilities[decision.selected_index],
        odds=odds[decision.selected_index],
        bankroll_units=100.0,
        staking="FIXED",
        kelly_fraction=0.25,
        stake_cap_units=2.0,
    )
    profit = settle_profit(stake_units=stake, odds=odds[0], won=True)
    performance = performance_summary(
        starting_bankroll_units=100.0,
        stakes=[stake],
        profits=[profit],
    )
    report = _base_report(
        filename,
        scope="STATIC_ACTIVE_PATH_LINKS_AND_ONE_DETERMINISTIC_OFFLINE_KERNEL_TRACE",
        grain="ONE_STATIC_LINK_OR_ONE_FIXTURE_EXECUTION",
        temporal_class="OFFLINE_FIXTURE_TEMPORAL_VALIDITY_NOT_PROVEN",
        evidence_status="PROBABLE",
        evidence_ids=["E1006", "E1036", "E1042", "E0017", "E0026"],
        sources=[
            _source(
                "src/robin/market_math/truth.py",
                _sha256_repository_file(ROOT / "src/robin/market_math/truth.py"),
                ["E0026"],
            ),
            _source(
                "src/robin/backtesting/v3.py",
                _sha256_repository_file(ROOT / "src/robin/backtesting/v3.py"),
                ["E0017", "E0026"],
            ),
            _source(
                "src/robin/shadow/decision.py",
                _sha256_repository_file(ROOT / "src/robin/shadow/decision.py"),
                ["E1042", "E0026"],
            ),
        ],
        limitations=[
            "The dynamic trace exercises the shared kernel without any provider or production service.",
            "Feature availability, provider publication times, as-of joins and all live lineage are not proven.",
            "Chronos has no active non-test consumer proven in the audited snapshot.",
        ],
        non_claims=[
            "The fixture is not evidence that production data is point-in-time valid.",
            "The fixture does not certify the scheduled shadow workflow because its quality gate remains closed.",
        ],
        verdicts=[
            {
                "verdict": "DEVIG_DECISION_PATH_PARITY_PROVEN_BOUNDED_FIXTURES",
                "evidence_ids": ["E0017", "E0026"],
            },
            {
                "verdict": "PRODUCTION_DECISION_PATH_STILL_NOT_PROVEN",
                "evidence_ids": ["E1006", "E1036", "E1042", "E2013"],
            },
            {"verdict": "TEMPORAL_VALIDITY_NOT_PROVEN", "evidence_ids": ["E2013"]},
        ],
    )
    report.update(
        {
            "static_links": [
                {
                    "link_id": "TRACE-V3-ENTRY",
                    "repo_path": "src/robin/backtesting/v3.py",
                    "line_anchor": "run_backtest",
                    "caller": "scripts/run_historical_pipeline.py",
                    "callee": "robin.market_math.decide_market",
                    "input_schema": "complete odds + normalized model probabilities + explicit method",
                    "output_schema": "MarketDecision",
                    "version": SCIENTIFIC_KERNEL_VERSION,
                    "test": "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0017", "E0026"],
                },
                {
                    "link_id": "TRACE-DEVIG",
                    "repo_path": "src/robin/market_math/devig.py",
                    "line_anchor": "devig_probabilities",
                    "caller": "decide_market and explicit adapters",
                    "callee": "named proportional or Shin implementation",
                    "input_schema": "complete uniquely labelled decimal odds >1",
                    "output_schema": "DevigResult requested/effective/version/hash",
                    "version": "PROPORTIONAL_COMPLETE_MARKET_V1 or LEGACY_SHIN_VAGUE1_V1",
                    "test": "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
                {
                    "link_id": "TRACE-DECISION",
                    "repo_path": "src/robin/market_math/truth.py",
                    "line_anchor": "decide_market",
                    "caller": "active migrated decision paths",
                    "callee": "maximum edge with explicit threshold",
                    "input_schema": "DevigResult + model probabilities + threshold",
                    "output_schema": "MarketDecision selected outcome and accepted flag",
                    "version": DECISION_THRESHOLD_VERSION,
                    "test": "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
                {
                    "link_id": "TRACE-STAKING",
                    "repo_path": "src/robin/market_math/truth.py",
                    "line_anchor": "stake_units",
                    "caller": "backtesting V3 and decision adapters",
                    "callee": "fixed/proportional/fractional-Kelly stake",
                    "input_schema": "probability odds bankroll method fraction cap",
                    "output_schema": "nonnegative stake bounded by bankroll and cap",
                    "version": STAKING_VERSION,
                    "test": "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
                {
                    "link_id": "TRACE-SETTLEMENT",
                    "repo_path": "src/robin/market_math/truth.py",
                    "line_anchor": "settle_profit and performance_summary",
                    "caller": "backtesting and settlement paths",
                    "callee": "profit turnover ROI yield summary",
                    "input_schema": "accepted stake odds boolean outcome",
                    "output_schema": "profit turnover roi yield profit_per_bet bankroll",
                    "version": SETTLEMENT_VERSION,
                    "test": "tests/jalon6/test_scientific_truth_kernel_v1.py",
                    "evidence_status": "PROUVÉ",
                    "evidence_ids": ["E0026"],
                },
                {
                    "link_id": "TRACE-SHADOW",
                    "repo_path": "scripts/run_shadow_pipeline.py",
                    "line_anchor": "pre-match shadow decision",
                    "caller": "scheduled workflow",
                    "callee": "src/robin/shadow/decision.py",
                    "input_schema": "durable fixture prediction and complete market snapshots",
                    "output_schema": "append-only shadow decision",
                    "version": SCIENTIFIC_KERNEL_VERSION,
                    "test": "tests/jalon2/test_decisions_pipeline_workflows.py",
                    "evidence_status": "PROBABLE",
                    "evidence_ids": ["E1006", "E1042", "E0026"],
                    "limitation": "quality_ok is fail-closed and live lineage is not inspected",
                },
                {
                    "link_id": "TRACE-PREQUENTIAL",
                    "repo_path": "src/robin/prospective_observatory/prequential_factory.py",
                    "line_anchor": "forecast",
                    "caller": "scripts/run_prequential_learning_factory.py",
                    "callee": "explicit proportional central adapter",
                    "input_schema": "frozen prediction evidence and complete market",
                    "output_schema": "FrozenPredictionRecord with persistent identity status",
                    "version": SCIENTIFIC_KERNEL_VERSION,
                    "test": "tests/jalon14/test_prequential_persistence.py",
                    "evidence_status": "PROBABLE",
                    "evidence_ids": ["E0026"],
                    "limitation": "legacy rows expose SCIENTIFIC_LINEAGE_NOT_PERSISTED",
                },
                {
                    "link_id": "TRACE-CHRONOS",
                    "repo_path": "src/robin/prospective_observatory/chronos.py",
                    "line_anchor": "derive_complete_book_markets",
                    "caller": "no active non-test consumer proven",
                    "callee": "scoped Decimal point-in-time price contract",
                    "input_schema": "complete same-receipt CANARY market",
                    "output_schema": "derived book price rows",
                    "version": "PROPORTIONAL_COMPLETE_MARKET_V1",
                    "test": "tests/chronos/test_chronos_contracts_v1.py",
                    "evidence_status": "NON VÉRIFIÉ",
                    "evidence_ids": ["E1012"],
                },
            ],
            "dynamic_trace": {
                "fixture_id": "SCIENTIFIC_TRUTH_KERNEL_BALANCED_1X2_WIN_V1",
                "input_lineage": "LOCAL_DETERMINISTIC_FIXTURE_ONLY",
                "cutoff": "2025-02-01T17:00:00Z",
                "features": {"source": "fixture", "point_in_time_validity": "NOT_PROVEN"},
                "model_probability": list(model_probabilities),
                "calibration": "IDENTITY_FIXTURE_V1",
                "odds": list(odds),
                "devig": {
                    **decision.devig.as_dict(),
                    **devig_execution_metadata(decision.devig),
                },
                "fair_probability": list(decision.devig.fair_probabilities),
                "edge": list(decision.edges),
                "threshold": decision.threshold,
                "decision": {
                    "accepted": decision.accepted,
                    "selected_index": decision.selected_index,
                    "selected_outcome": decision.selected_outcome,
                },
                "stake": stake,
                "settlement": {"won": True, "odds": odds[0]},
                "profit": profit,
                "turnover": performance["turnover_units"],
                "roi": performance["roi"],
                "yield": performance["yield"],
                "temporal_status": "TEMPORAL_VALIDITY_NOT_PROVEN",
                "evidence_ids": ["E0026", "E2013"],
            },
            "missing_links": [
                "provider publication timestamp",
                "data_available_at for every source",
                "feature as-of join proof",
                "live durable state identity",
                "production connection and runtime trace",
                "all 72 temporal surfaces",
            ],
            "path_verdict": "PRODUCTION_DECISION_PATH_STILL_NOT_PROVEN",
        }
    )
    return _with_content_hash(report)


def _rank_map(results: list[dict[str, Any]], field_path: tuple[str, ...]) -> dict[str, int]:
    def value(item: dict[str, Any]) -> float:
        current: Any = item
        for key in field_path:
            current = current[key]
        return float(current)

    ordered = sorted(results, key=lambda item: (-value(item), item["logical_result_id"]))
    return {item["logical_result_id"]: rank for rank, item in enumerate(ordered, 1)}


def _build_historical_replay(results: list[dict[str, Any]]) -> dict[str, Any]:
    filename = "historical-truth-replay-v1.json"
    old_ranks = _rank_map(results, ("original", "roi"))
    new_ranks = _rank_map(results, ("branches", "B", "roi"))
    rank_changes = []
    errors = []
    for item in results:
        logical_id = item["logical_result_id"]
        item["ranking"] = {
            "stored_roi_rank": old_ranks[logical_id],
            "repaired_roi_rank": new_ranks[logical_id],
            "changed": old_ranks[logical_id] != new_ranks[logical_id],
        }
        if item["ranking"]["changed"]:
            rank_changes.append(
                {
                    "logical_result_id": logical_id,
                    "strategy": item["strategy"],
                    **item["ranking"],
                }
            )
        errors.append(abs(item["original"]["roi"] - item["branches"]["B"]["roi"]))
    report = _base_report(
        filename,
        scope="15_LOGICAL_V3_FIXED_SUMMARIES_AND_45_TRACKED_OCCURRENCES",
        grain="ONE_LOGICAL_RESULT_WITH_THREE_PHYSICAL_OCCURRENCES",
        temporal_class="HISTORICAL_AGGREGATE_TEMPORAL_VALIDITY_NOT_PROVEN",
        evidence_status="PROBABLE",
        evidence_ids=["E0025", "E1040", "E1044", "E2013", "E3046"],
        sources=[
            *[_source(path, sha, ["E0025"]) for path, sha in REPOSITORY_INPUTS.items()],
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/backtest-v3-historical-roi-replay.csv",
                AUDIT_FILES["tables/backtest-v3-historical-roi-replay.csv"],
                ["E0025"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/hypothesis-search-space.csv",
                AUDIT_FILES["tables/hypothesis-search-space.csv"],
                ["E3046"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/hypothesis-selection-history.csv",
                AUDIT_FILES["tables/hypothesis-selection-history.csv"],
                ["E3046"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/historical-survivor-replay.csv",
                AUDIT_FILES["tables/historical-survivor-replay.csv"],
                ["E3046"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/dataset-lineage.csv",
                AUDIT_FILES["tables/dataset-lineage.csv"],
                ["E2013"],
            ),
            _source(
                f"{AUDIT_LOGICAL_PATH}/tables/time-fields.csv",
                AUDIT_FILES["tables/time-fields.csv"],
                ["E2013"],
            ),
        ],
        limitations=[
            "Branches C, D1 and D2 cannot be reconstructed because the 15 published summaries omit per-bet odds, selections and method identity.",
            "Branch B is a formula replay from stored profit and declared FIXED 1u bet count, not a decision replay.",
            "The temporal census is reused from the immutable audited revision and is not a new certification of the repair revision.",
        ],
        non_claims=[
            "No repaired result is scientifically validated, profitable, promotable or point-in-time valid.",
            "Physical copies are not counted as independent experiments.",
            "No new hypothesis or survivor was generated.",
        ],
        verdicts=[
            {
                "verdict": "ROBIN_HISTORICAL_FORMULA_REPAIR_VERSIONED_PARTIAL",
                "evidence_ids": ["E0025"],
            },
            {
                "verdict": "HISTORICAL_DECISION_AND_DEVIG_REPLAY_STILL_REQUIRED",
                "evidence_ids": ["E1040"],
            },
            {"verdict": "TEMPORAL_VALIDITY_NOT_PROVEN", "evidence_ids": ["E2013"]},
            {"verdict": "MULTIPLE_TESTING_REMAINS_FAIL_CLOSED", "evidence_ids": ["E3046"]},
        ],
    )
    report.update(
        {
            "replay_type": "FORMULA_REPLAY_FROM_STORED_PROFIT_AND_FIXED_STAKE_BET_COUNT",
            "source_inventory": {
                "logical_results": 15,
                "physical_occurrences": 45,
                "primary_source_occurrences": 15,
                "copies": 30,
                "stored_roi_mismatches": 45,
                "stored_yield_matches_repaired_fixed_1u_roi": 45,
            },
            "results": results,
            "summary": {
                "formula_replayed_logical_results": 15,
                "formula_replayed_physical_occurrences": 45,
                "decision_replayed_logical_results": 0,
                "devig_replayed_logical_results": 0,
                "metric_only_summary_changes": 15,
                "portfolio_changes_proven": 0,
                "maximum_absolute_roi_change": max(errors),
                "median_absolute_roi_change": sorted(errors)[len(errors) // 2],
                "profit_sign_changes": 0,
                "historical_status_changes": 0,
                "promotion_changes": 0,
                "rank_changes": rank_changes,
            },
            "oos_devig_sensitivity": {
                "eligible_complete_markets": 1563,
                "bet_no_bet_divergent_markets": 51,
                "full_decision_divergent_markets": 75,
                "status": "REUSED_AUDIT_REPLAY_NOT_METHOD_AUTHORITY",
                "evidence_ids": ["E1040"],
            },
            "synthetic_devig_sensitivity": {
                "markets": 20000,
                "seed": 20260813,
                "bet_no_bet_divergence_rate": 0.1011,
                "full_decision_divergence_rate": 0.2146,
                "status": "SENSITIVITY_ONLY_NOT_METHOD_AUTHORITY",
                "evidence_ids": ["E1044"],
            },
            "multiplicity": {
                "atomic_tests": 300,
                "pair_tests": 7180,
                "tests": 7480,
                "eligible_pairs": 3590,
                "survivors": 0,
                "triple_search_locked": True,
                "machine_discoveries": 3,
                "machine_q_values": [1.0, 1.0, 1.0],
                "historical_status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
                "prospective_status": "PROSPECTIVE_FROZEN",
                "live_observations": 0,
                "promotion": False,
                "clean_independent_holdout": "NON VÉRIFIÉ",
                "evidence_ids": ["E3046"],
            },
            "temporal": {
                "surfaces": 72,
                "file_materialized": 27,
                "absent": 8,
                "external_unobserved": 37,
                "canonical_timestamp_fields": 720,
                "proven_surfaces": 0,
                "verdict": "TEMPORAL_VALIDITY_NOT_PROVEN",
                "evidence_ids": ["E2013"],
            },
            "historical_verdict": "HISTORICAL_DECISION_AND_DEVIG_REPLAY_STILL_REQUIRED",
        }
    )
    return _with_content_hash(report)


def _invalidation_record(
    *,
    sequence: int,
    previous_hash: str,
    relation: str,
    result: dict[str, Any],
    occurrence: dict[str, Any],
    original: Any,
    corrected: Any,
    reason: str,
    replay_sha256: str,
    evidence_status: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    record = {
        "sequence": sequence,
        "record_id": f"STK-INVALIDATION-{sequence:04d}",
        "previous_record_hash": previous_hash,
        "recorded_at": GENERATED_AT,
        "relation": relation,
        "logical_result_id": result["logical_result_id"],
        "occurrence_id": occurrence["occurrence_id"],
        "source": {
            "repo_path": occurrence["repo_path"],
            "json_pointer": occurrence["json_pointer"],
            "artifact_sha256": occurrence["source_artifact_sha256"],
            "artifact_hash_representation": occurrence[
                "source_artifact_hash_representation"
            ],
            "audited_checkout_artifact_sha256": occurrence[
                "audited_checkout_artifact_sha256"
            ],
            "object_sha256": occurrence["source_object_sha256"],
        },
        "original": original,
        "corrected": corrected,
        "reason": reason,
        "replacement": {
            "repo_path": REPLAY_PATH,
            "artifact_sha256": replay_sha256,
            "logical_result_id": result["logical_result_id"],
        },
        "scientific_kernel_version": SCIENTIFIC_KERNEL_VERSION,
        "evidence_status": evidence_status,
        "evidence_ids": [_evidence_ref(item) for item in evidence_ids],
    }
    record["record_hash"] = _sha256_bytes(_canonical_bytes(record))
    return record


def _build_invalidation_ledger(
    results: list[dict[str, Any]], replay_bytes: bytes
) -> dict[str, Any]:
    filename = "historical-invalidation-ledger-v1.json"
    replay_sha = _sha256_bytes(replay_bytes)
    records: list[dict[str, Any]] = []
    previous = "0" * 64

    def append(
        *,
        relation: str,
        result: dict[str, Any],
        occurrence: dict[str, Any],
        original: Any,
        corrected: Any,
        reason: str,
        evidence_status: str,
        evidence_ids: list[str],
    ) -> None:
        nonlocal previous
        record = _invalidation_record(
            sequence=len(records) + 1,
            previous_hash=previous,
            relation=relation,
            result=result,
            occurrence=occurrence,
            original=original,
            corrected=corrected,
            reason=reason,
            replay_sha256=replay_sha,
            evidence_status=evidence_status,
            evidence_ids=evidence_ids,
        )
        records.append(record)
        previous = record["record_hash"]

    for result in results:
        primary = result["source_occurrences"][0]
        for occurrence in result["source_occurrences"][1:]:
            append(
                relation="COPY_OF",
                result=result,
                occurrence=occurrence,
                original={"occurrence_id": occurrence["occurrence_id"]},
                corrected={"primary_occurrence_id": primary["occurrence_id"]},
                reason="PHYSICAL_RENDERING_OF_ONE_LOGICAL_SCIENTIFIC_RESULT",
                evidence_status="PROUVÉ",
                evidence_ids=["E0025"],
            )
        for occurrence in result["source_occurrences"]:
            append(
                relation="INVALIDATED_BY_ROI_DEFINITION",
                result=result,
                occurrence=occurrence,
                original={
                    "roi": result["original"]["roi"],
                    "roi_definition": "profit_over_sum_absolute_realized_profit",
                },
                corrected={
                    "roi": result["branches"]["B"]["roi"],
                    "roi_definition": ROI_DEFINITION_VERSION,
                    "turnover_units": result["branches"]["B"]["turnover_units"],
                    "yield": result["branches"]["B"]["yield"],
                    "yield_disposition": "PRESERVED_NUMERICALLY_FOR_FIXED_1U",
                },
                reason="STORED_ROI_DENOMINATOR_IS_NOT_ACTUAL_TURNOVER",
                evidence_status="PROBABLE",
                evidence_ids=["E0025", "E2008"],
            )
            append(
                relation="SUPERSEDED_BY",
                result=result,
                occurrence=occurrence,
                original={
                    "source_projection_sha256": result["source_projection_sha256"],
                    "scientific_kernel_version": None,
                },
                corrected={
                    "repair_projection_sha256": result["repair_projection_sha256"],
                    "scientific_kernel_version": SCIENTIFIC_KERNEL_VERSION,
                    "repair_scope": "FORMULA_REPAIR_ONLY",
                },
                reason="VERSIONED_FORMULA_REPAIR_WITHOUT_SOURCE_ARTIFACT_REWRITE",
                evidence_status="PROBABLE",
                evidence_ids=["E0025", "E0026"],
            )
            append(
                relation="TEMPORAL_VALIDITY_NOT_PROVEN",
                result=result,
                occurrence=occurrence,
                original={"temporal_validity": "UNKNOWN_OR_UNSERIALIZED"},
                corrected={
                    "temporal_validity": "TEMPORAL_VALIDITY_NOT_PROVEN",
                    "next_mission": "LOOP55_POINT_IN_TIME_LINEAGE_CLOSURE_V1",
                },
                reason="AGGREGATE_RESULT_HAS_NO_COMPLETE_POINT_IN_TIME_LINEAGE",
                evidence_status="PROUVÉ",
                evidence_ids=["E2013"],
            )

    counts = Counter(record["relation"] for record in records)
    expected = {
        "COPY_OF": 30,
        "INVALIDATED_BY_ROI_DEFINITION": 45,
        "SUPERSEDED_BY": 45,
        "TEMPORAL_VALIDITY_NOT_PROVEN": 45,
    }
    if dict(counts) != expected:
        raise AssertionError(f"INVALIDATION_RELATION_COUNT_DRIFT:{dict(counts)}")

    report = _base_report(
        filename,
        scope="APPEND_ONLY_DISPOSITION_OF_45_HISTORICAL_OCCURRENCES",
        grain="ONE_RELATION_RECORD_PER_OCCURRENCE_AND_REASON",
        temporal_class="APPEND_ONLY_HISTORICAL_DISPOSITION",
        evidence_status="PROBABLE",
        evidence_ids=["E0025", "E1040", "E2013", "E3046"],
        sources=[
            *[_source(path, sha, ["E0025"]) for path, sha in REPOSITORY_INPUTS.items()],
            _source(REPLAY_PATH, replay_sha, ["E0025", "E2013", "E3046"]),
        ],
        limitations=[
            "ROI invalidation is mathematically supported from FIXED aggregate summaries but is not a bet-level replay.",
            "DEVIG invalidation is not asserted per result because the original method was not serialized.",
        ],
        non_claims=[
            "The ledger does not delete or rewrite either cockpit source artifact.",
            "SUPERSEDED_BY means versioned formula replacement, not scientific validation.",
        ],
        verdicts=[
            {"verdict": "HISTORICAL_ROI_FIELDS_APPEND_ONLY_INVALIDATED", "evidence_ids": ["E0025"]},
            {"verdict": "HISTORICAL_DEVIG_REPLAY_STILL_REQUIRED", "evidence_ids": ["E1040"]},
            {"verdict": "TEMPORAL_VALIDITY_NOT_PROVEN", "evidence_ids": ["E2013"]},
        ],
    )
    report.update(
        {
            "append_only": True,
            "hash_algorithm": "SHA-256",
            "record_hash_contract": "SHA256_CANONICAL_JSON_EXCLUDING_RECORD_HASH",
            "allowed_relations": [
                "SUPERSEDED_BY",
                "COPY_OF",
                "INVALIDATED_BY_ROI_DEFINITION",
                "INVALIDATED_BY_DEVIG_METHOD",
                "TEMPORAL_VALIDITY_NOT_PROVEN",
            ],
            "records": records,
            "counts": {
                "records": len(records),
                **{key.lower(): value for key, value in expected.items()},
                "logical_results": 15,
                "physical_occurrences": 45,
                "source_artifacts_rewritten": 0,
                "stored_yield_fields_invalidated": 0,
                "promotions": 0,
            },
            "chain_tip": previous,
        }
    )
    return _with_content_hash(report)


def _validate_reports(reports: dict[str, dict[str, Any]]) -> None:
    if set(reports) != set(REPORT_SPECS):
        raise AssertionError("REPORT_FILE_SET_DRIFT")
    allowed_statuses = {"PROUVÉ", "PROBABLE", "HYPOTHÈSE", "NON VÉRIFIÉ"}
    for filename, document in reports.items():
        if document["evidence_status"] not in allowed_statuses:
            raise ValueError(f"REPORT_EVIDENCE_STATUS_INVALID:{filename}")
        if document["scientific_kernel_version"] != SCIENTIFIC_KERNEL_VERSION:
            raise ValueError(f"REPORT_KERNEL_VERSION_DRIFT:{filename}")
        if document["authority"]["global_devig_authority"] != "CONFLICTING":
            raise ValueError(f"REPORT_FALSE_GLOBAL_DEVIG_AUTHORITY:{filename}")
        if document["authority"]["roi_used_for_authority"] is not False:
            raise ValueError(f"REPORT_ROI_METHOD_SELECTION:{filename}")
        if any(value != 0 for value in document["external_effects"].values()):
            raise ValueError(f"REPORT_EXTERNAL_EFFECT_NONZERO:{filename}")
        _verify_content_hash(document)

    replay = reports["historical-truth-replay-v1.json"]
    if len(replay["results"]) != 15:
        raise AssertionError("REPLAY_LOGICAL_COUNT_DRIFT")
    occurrences = [
        occurrence for result in replay["results"] for occurrence in result["source_occurrences"]
    ]
    if (
        len(occurrences) != 45
        or len({occurrence["occurrence_id"] for occurrence in occurrences}) != 45
    ):
        raise AssertionError("REPLAY_OCCURRENCE_COUNT_DRIFT")
    if sum(occurrence["relation"] == "COPY_OF" for occurrence in occurrences) != 30:
        raise AssertionError("REPLAY_COPY_COUNT_DRIFT")
    for result in replay["results"]:
        if result["original"]["devig_method"] != "UNKNOWN":
            raise AssertionError("REPLAY_INFERRED_HISTORICAL_DEVIG")
        if result["branches"]["C"]["evidence_status"] != "NON VÉRIFIÉ":
            raise AssertionError("REPLAY_FALSE_BRANCH_C_PROOF")
        if result["branches"]["D1"]["evidence_status"] != "NON VÉRIFIÉ":
            raise AssertionError("REPLAY_FALSE_BRANCH_D1_PROOF")
        if result["branches"]["D2"]["evidence_status"] != "NON VÉRIFIÉ":
            raise AssertionError("REPLAY_FALSE_BRANCH_D2_PROOF")

    ledger = reports["historical-invalidation-ledger-v1.json"]
    previous = "0" * 64
    for sequence, record in enumerate(ledger["records"], 1):
        if record["sequence"] != sequence or record["previous_record_hash"] != previous:
            raise AssertionError("INVALIDATION_CHAIN_ORDER_DRIFT")
        candidate = {key: value for key, value in record.items() if key != "record_hash"}
        actual = _sha256_bytes(_canonical_bytes(candidate))
        if actual != record["record_hash"]:
            raise AssertionError("INVALIDATION_RECORD_HASH_DRIFT")
        previous = actual
    if previous != ledger["chain_tip"] or len(ledger["records"]) != 165:
        raise AssertionError("INVALIDATION_CHAIN_TIP_OR_COUNT_DRIFT")


def _build_doc(reports: dict[str, dict[str, Any]]) -> str:
    replay = reports["historical-truth-replay-v1.json"]
    table_rows = []
    for item in replay["results"]:
        table_rows.append(
            "| {strategy} | {bets} | {profit:.12g} | {old:.12g} | {new:.12g} | {delta:.12g} |".format(
                strategy=item["strategy"],
                bets=item["original"]["bets"],
                profit=item["original"]["profit_units"],
                old=item["original"]["roi"],
                new=item["branches"]["B"]["roi"],
                delta=abs(item["original"]["roi"] - item["branches"]["B"]["roi"]),
            )
        )
    report_links = "\n".join(
        f"- [{filename}](../../reports/scientific-truth/{filename})" for filename in REPORT_SPECS
    )
    return f"""# Robin Scientific Truth Kernel V1

## Résultat technique

Le noyau mathématique est réparé et versionné au commit `{REPAIR_REVISION}` : le ROI et le yield utilisent le turnover réellement misé, `profit_per_bet` porte désormais sa propre définition, les méthodes de-vig sont explicites, et les chemins actifs migrés échouent fermés sur un marché invalide ou une méthode absente.

Le verdict global reste **`ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL` / `PASS_AND_HOLD`**. L'autorité de-vig globale est **`CONFLICTING`** ; aucune méthode n'a été choisie sur la base du ROI. Chronos conserve une autorité `UNIQUE` uniquement dans son scope CANARY point-in-time, marché complet et same-receipt. Les 72 surfaces temporelles restent `TEMPORAL_VALIDITY_NOT_PROVEN`.

## Les corrections ferment le calcul, pas la validité historique complète

- `profit_units = sum(detail.profit)`
- `turnover_units = sum(detail.stake)`
- `roi = profit_units / turnover_units` si le turnover est positif, sinon `null`
- `yield = roi`, version `{YIELD_DEFINITION_VERSION}`
- `profit_per_bet = profit_units / bets` si des paris existent, sinon `null`

Le test rouge obligatoire a reproduit `1 / (|2| + |-1|) = 1/3` à la place du ROI attendu `1 / (1 + 1) = 1/2`. Les tests corrigés couvrent FIXED, proportionnel, Kelly fractionné, mise variable, cap, ruine, zéro pari et frontières de settlement.

## Les 15 résultats représentent 45 rendus, pas 45 expériences

Les deux JSON cockpit audités contiennent 15 résultats logiques, chacun rendu sur trois surfaces : `deepData.backtests`, `deepData.strategies` et `cockpit-expert-data.backtests`. Le replay LOOP54 relie 30 copies par `COPY_OF`; il ne les recompte jamais comme expériences indépendantes.

La correction ci-dessous est un **`FORMULA_REPLAY_FROM_STORED_PROFIT_AND_FIXED_STAKE_BET_COUNT`**. Les objets déclarent FIXED et publient bets/profit, ce qui permet de recalculer `profit/bets`. Ils ne publient ni les paris unitaires, ni les cotes, ni les sélections, ni la méthode de-vig : les branches de portfolio PROPORTIONAL/SHIN restent `NON VÉRIFIÉ`.

| Stratégie | Bets | Profit (u) | ROI stocké | ROI réparé | Écart absolu |
|---|---:|---:|---:|---:|---:|
{chr(10).join(table_rows)}

Les 45 champs ROI sont invalidés append-only ; les 45 yields ne le sont pas, car ils égalaient déjà `profit/bets` sous FIXED 1u. Aucun JSON cockpit historique n'est réécrit. Le plus grand écart absolu est `0.04577382258550142`; aucun signe de profit, statut `INCONCLUSIVE`, verrou `PRODUCTION_LOCKED` ou `NO_PROMOTION` ne change.

## L'autorité de-vig reste conflictuelle

L'audit a recensé exactement 15 mécanismes historiques, dont un défaut Shin legacy, plusieurs variantes proportionnelles aux politiques d'entrées divergentes, le contrat Chronos borné, et un chemin shadow historiquement fondé sur la probabilité implicite brute. LOOP54 fournit une interface centrale stricte pour `PROPORTIONAL` et `SHIN`, avec méthode demandée/effective, version et hash de définition. Cela rend l'exécution rejouable ; cela ne crée pas une autorité globale.

Les preuves de sensibilité sont conservées sans arbitrage : 1 563 marchés OOS complets, 51 divergences bet/no-bet et 75 décisions complètes ; 20 000 marchés synthétiques (seed 20260813), 10,11 % de divergences bet/no-bet et 21,46 % de décisions complètes. Ces chiffres décrivent la sensibilité au protocole, jamais une sélection par performance.

## Le chemin décisionnel reste partiellement prouvé

La fixture offline trace odds complètes → de-vig explicite → probabilités justes → modèle → edge → seuil → décision → mise → settlement → profit → turnover → ROI/yield. La parité est prouvée pour les fixtures et chemins migrés couverts par tests.

Le verdict production reste `PRODUCTION_DECISION_PATH_STILL_NOT_PROVEN` : les timestamps de publication fournisseur, `data_available_at`, as-of joins, lineage des features, état durable live et toutes les 72 surfaces temporelles ne sont pas fermés. Les anciennes lignes SQL préquentielles conservent leur hash persistant avec `SCIENTIFIC_LINEAGE_NOT_PERSISTED`; d'anciennes projections prospectives incomplètes/underround peuvent exiger un rebuild séparément autorisé.

## La multiplicité reste fermée

Les artefacts gelés réutilisés prouvent 300 tests atomiques + 7 180 tests de paires = 7 480, zéro paire survivante et recherche triple verrouillée. Les trois cartes « découverte machine » ont `q=1`, restent `EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING`, `PROSPECTIVE_FROZEN`, avec zéro observation live. LOOP54 ne génère aucune hypothèse ni promotion.

## Sources et rapports versionnés

Base auditée : `{AUDITED_REVISION}`. Manifeste audit : `{AUDIT_MANIFEST_SHA256}`. Réparation code : `{REPAIR_REVISION}`.

{report_links}

Chaque rapport JSON porte son claim ID, ses Evidence IDs, les hashes d'entrée, un content hash canonique, ses limites et des compteurs d'effets externes tous égaux à zéro.

## Limites et prochaine étape

Ce travail ne prouve ni rentabilité, ni causalité, ni absence de fuite, ni préparation production. Aucun accès Neon/PostgreSQL production/R2/provider, aucune migration, aucun workflow live, aucun pari et aucune promotion n'ont été exécutés.

La prochaine mission est **LOOP55 — Robin Point-in-Time Lineage Closure V1** : timestamps de disponibilité et fournisseur, ingestion, as-of joins, cutoff des features, mutations futures adversariales et fermeture des 72 surfaces temporelles.
"""


def _materialize(reports: dict[str, dict[str, Any]], doc: str, *, check: bool) -> None:
    targets = {
        REPORT_DIR / filename: _json_bytes(document) for filename, document in reports.items()
    }
    targets[DOC_PATH] = doc.replace("\r\n", "\n").encode("utf-8")
    if check:
        drift = [
            path.relative_to(ROOT).as_posix()
            for path, expected in targets.items()
            if not path.is_file() or path.read_bytes() != expected
        ]
        if drift:
            raise SystemExit("SCIENTIFIC_TRUTH_REPORT_DRIFT:" + ",".join(drift))
        return

    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    try:
        for path, payload in targets.items():
            temp = path.with_name(path.name + ".tmp")
            temp.write_bytes(payload)
            temporary.append((temp, path))
        for temp, path in temporary:
            temp.replace(path)
    finally:
        for temp, _ in temporary:
            if temp.exists():
                temp.unlink()


def _build_all() -> dict[str, dict[str, Any]]:
    cockpit, expert = _load_repository_inputs()
    results = _extract_historical_results(cockpit, expert)
    reports: dict[str, dict[str, Any]] = {
        "scientific-truth-defect-inventory-v1.json": _build_defect_inventory(),
        "roi-turnover-repair-v1.json": _build_roi_report(results),
        "yield-consumer-inventory-v1.json": _build_yield_report(results),
        "devig-implementation-inventory-v1.json": _build_devig_inventory(),
        "devig-canonicalization-v1.json": _build_devig_canonicalization(),
        "decision-path-trace-v1.json": _build_decision_trace(),
    }
    replay = _build_historical_replay(results)
    reports["historical-truth-replay-v1.json"] = replay
    reports["historical-invalidation-ledger-v1.json"] = _build_invalidation_ledger(
        results, _json_bytes(replay)
    )
    _validate_reports(reports)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-root",
        type=Path,
        required=True,
        help="Local independent audit-pack root; its path is never serialized.",
    )
    parser.add_argument(
        "--loop54-root",
        type=Path,
        required=True,
        help="Local LOOP54 evidence-pack root; its path is never serialized.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if tracked reports differ from deterministic regeneration.",
    )
    args = parser.parse_args()
    _verify_audit_root(args.audit_root)
    _verify_loop54_root(args.loop54_root)
    reports = _build_all()
    _materialize(reports, _build_doc(reports), check=args.check)
    print(
        json.dumps(
            {
                "status": "SCIENTIFIC_TRUTH_REPORTS_MATCH"
                if args.check
                else "SCIENTIFIC_TRUTH_REPORTS_WRITTEN",
                "reports": len(reports),
                "logical_results": 15,
                "physical_occurrences": 45,
                "invalidation_records": 165,
                "global_verdict": "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL",
                "external_effects": EXTERNAL_EFFECTS_ZERO,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
