from __future__ import annotations

from jsonschema import Draft202012Validator

from tests.coverage.build_denominator_artifacts import build_artifacts
from tests.coverage.denominator_oracle import (
    ROOT,
    artifact_proof_hash,
    load_json,
)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for child in value.values()
            for key in _all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_golden_pack_is_bounded_and_all_expected_results_are_reproduced() -> None:
    artifacts = build_artifacts()
    e0 = next(item for path, item in artifacts.items() if path.name.startswith("e0-"))
    assert e0["source_record_count"] <= 100
    assert e0["expanded_candidate_count"] <= 100
    assert e0["all_expected_results_reproduced"] is True
    assert e0["real_cells_closed"] == 0
    assert e0["authorizes_scale"] is False


def test_generated_artifacts_match_tracked_files_and_hashes() -> None:
    for path, expected in build_artifacts().items():
        actual = load_json(path)
        assert actual == expected
        assert artifact_proof_hash(actual) == actual["proof_hash"]
        assert actual["provider_calls"] == 0
        assert actual["r2_writes"] == 0
        assert actual["purchases"] == 0
        assert actual["odds_credits"] == 0


def test_private_projection_is_sanitized_and_complete() -> None:
    projection = load_json(
        ROOT / "cockpit/private-coverage/p0-denominator-status-v1.json"
    )
    assert projection["privacy"] == {
        "classification": "PRIVATE_SANITIZED_PROJECTION",
        "raw_payloads": False,
        "provider_endpoints": False,
        "r2_keys": False,
        "secrets": False,
    }
    assert len(projection["cells"]) == 480
    assert {
        cell["source_endpoint"] for cell in projection["cells"]
    } == {"SANITIZED_IN_PRIVATE_PROJECTION"}
    assert all(cell["payload_hash"] is None for cell in projection["cells"])
    assert all(cell["receipt_hash"] is None for cell in projection["cells"])
    forbidden = {"payload", "endpoint", "r2_key", "secret", "api_key"}
    assert not forbidden & _all_keys(projection)


def test_no_fake_level_proof_files_exist() -> None:
    reports = ROOT / "reports/coverage"
    forbidden = [
        "e1-denominator-proof-v1.json",
        "e2-denominator-proof-v1.json",
        "e3-denominator-proof-v1.json",
        "e4-p0-closure-proof-v1.json",
    ]
    assert all(not (reports / name).exists() for name in forbidden)


def test_artifact_schema_has_all_seven_contracts() -> None:
    schema = load_json(
        ROOT / "configs/data/historical-coverage-artifact-schema-v1.json"
    )
    assert set(schema["$defs"]) == {
        "nullable_count",
        "nullable_rate_value",
        "rate",
        "rates",
        "cell",
        "private_cell",
        "p0_grid",
        "level_proof",
        "census_manifest",
        "gate_report",
        "property_readiness",
        "closure_summary",
        "private_projection",
    }
    assert schema["$schema"].endswith("draft/2020-12/schema")
    assert schema["$defs"]["p0_grid"]["properties"]["cells"]["items"] == {
        "$ref": "#/$defs/cell"
    }


def test_all_generated_artifacts_validate_against_json_schema() -> None:
    schema = load_json(
        ROOT / "configs/data/historical-coverage-artifact-schema-v1.json"
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for artifact in build_artifacts().values():
        validator.validate(artifact)
