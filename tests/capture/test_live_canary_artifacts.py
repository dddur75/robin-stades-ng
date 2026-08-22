from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from robin.capture import (
    LIVE_ALLOWED_MARKET_SETS,
    LIVE_ALLOWED_SPORT_KEYS,
    ActivationEnvelopeV1,
    FixtureMapping,
    LivePlanV1,
    OwnerAuthorizationV1,
    ProviderRequestSpec,
    RequestFingerprint,
    fixture_mappings_sha256,
)

ROOT = Path(__file__).parents[2]
GOLDEN_PATH = ROOT / "tests/capture/fixtures/bounded-live-canary-v1-golden-pack.json"
REPORT_PATH = ROOT / "reports/data-sourcing/bounded-live-canary-capability-v1.json"
BUILDER_PATH = ROOT / "tools/data-sourcing/build_bounded_live_canary_artifacts.py"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_module(BUILDER_PATH, "build_bounded_live_canary_artifacts")


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_golden_pack_and_capability_report_are_reproducible() -> None:
    pack = BUILDER.build_golden_pack()
    assert _load(GOLDEN_PATH) == pack
    assert _load(REPORT_PATH) == BUILDER.build_report(pack)


def test_golden_pack_validates_the_complete_hash_dag() -> None:
    pack = _load(GOLDEN_PATH)
    authorization = OwnerAuthorizationV1.model_validate(pack["authorization"])
    activation = ActivationEnvelopeV1.model_validate(pack["activation"])
    plan = LivePlanV1.model_validate(pack["plan"])
    request = ProviderRequestSpec.model_validate(pack["request"])
    mappings = tuple(FixtureMapping.model_validate(value) for value in pack["fixture_mappings"])

    assert tuple(authorization.allowed_sport_keys) == LIVE_ALLOWED_SPORT_KEYS
    assert tuple(authorization.allowed_market_sets) == LIVE_ALLOWED_MARKET_SETS
    assert activation.authorization_hash == authorization.canonical_authorization_hash
    assert plan.activation_hash == activation.activation_scope_sha256
    assert activation.plan_sha256 == plan.canonical_plan_hash
    assert (
        plan.items[0].provider_request_fingerprint
        == RequestFingerprint.create(request).request_sha256
    )
    assert plan.items[0].fixture_mappings_sha256 == fixture_mappings_sha256(mappings)
    assert pack["expected"] == {
        "activation_scope_sha256": activation.activation_scope_sha256,
        "authorization_hash": authorization.canonical_authorization_hash,
        "item_hash": plan.items[0].canonical_item_hash,
        "plan_hash": plan.canonical_plan_hash,
        "request_fingerprint_sha256": RequestFingerprint.create(request).request_sha256,
    }


def test_committed_capability_artifacts_contain_no_real_activation_or_effect() -> None:
    pack = _load(GOLDEN_PATH)
    report = _load(REPORT_PATH)
    assert pack["provenance"] == ("ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD_NO_REAL_AUTHORITY")
    assert pack["repository_sha_is_synthetic"] is True
    assert pack["capture_root_fingerprint_is_synthetic"] is True
    assert set(pack["mission_effects"].values()) == {0}
    assert report["default_state"] == "DEFAULT_DENY"
    assert report["real_authorization_present"] is False
    assert report["real_authorization_status"] == "NOT_CREATED"
    assert report["real_activation_present"] is False
    assert report["real_activation_status"] == "NOT_CREATED"
    assert report["real_batch_status"] == "NOT_EXECUTED"
    assert report["real_capture_count"] == 0
    assert report["real_snapshot_status"] == "NOT_CREATED"
    assert report["real_snapshot_count"] == 0
    assert report["experiment_readiness_status"] == "NOT_ASSESSED_ON_REAL_DATA"
    assert report["real_executable_experiment_count"] == 0
    assert report["accumulation_candidates"] == []
    assert report["network_calls"] == 0
    assert report["network_calls_scope"] == (
        "PROVIDER_AND_PROVIDER_DNS_ONLY_AUTHORIZED_GIT_GITHUB_DELIVERY_EXCLUDED"
    )
    assert report["real_provider_calls"] == report["real_provider_dns_calls"] == 0
    assert report["real_secret_reads"] == 0
    assert report["purchases"] == report["promotions"] == report["bets"] == 0
    assert report["claim_ids"] == {
        "capability_contract": "GOV.BOUNDED_LIVE_CANARY.CAPABILITY.REPORT.V1.001",
        "non_execution_state": "SCIENCE.BOUNDED_LIVE_CANARY.NON_EXECUTION.V1.001",
        "zero_external_effects": "SECURITY.BOUNDED_LIVE_CANARY.ZERO_EFFECTS.V1.001",
    }
    assert report["automatic_activation"] is False


def test_capability_artifact_check_accepts_platform_line_endings(
    tmp_path: Path,
) -> None:
    relative = Path("synthetic-artifact.json")
    document = {"synthetic": True}
    content = BUILDER._json_text(document)
    (tmp_path / relative).write_bytes(content.replace("\n", "\r\n").encode("utf-8"))

    BUILDER.check_artifacts(tmp_path, {relative: document})
