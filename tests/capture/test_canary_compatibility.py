from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from robin.capture import (
    CaptureBudget,
    CaptureHarness,
    CaptureManifest,
    CaptureStore,
    FixtureMapping,
    InternalRetentionPolicy,
    ProviderRequestSpec,
)
from robin.capture.contracts import MappingStatus, canonical_sha256

ROOT = Path(__file__).parents[2]
FIXTURE_PATH = (
    ROOT / "tests" / "capture" / "fixtures" / "synthetic-canary-structural-equivalent-v1.json"
)
GENERATOR_PATH = ROOT / "tools" / "data-sourcing" / "generate_synthetic_canary_fixture.py"
WITNESS_TOOL_PATH = ROOT / "tools" / "data-sourcing" / "build_canary_compatibility_witness.py"
REPORT_ROOT = ROOT / "reports" / "data-sourcing"
EXPECTED_ANSWERS = {
    "new_provider_call": "NO",
    "provider_key_read": "NO",
    "real_bytes_verified_before_parsing": "YES",
    "harness_reproduces_supported_real_observations_offline": "YES",
    "raw_payload_entered_git": "NO",
    "detailed_real_odds_entered_git": "NO",
    "c1_backdated_or_replaced": "NO",
    "c2_relaunched": "NO",
    "totals_coverage_presented_as_guaranteed": "NO",
    "live_canary_authorized_after_delivery": "NO",
    "experiment_may_be_launched": "NO",
    "promotion_or_bet_may_be_launched": "NO",
}


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WITNESS_TOOL = _load_module(WITNESS_TOOL_PATH, "build_canary_compatibility_witness")


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))


def _mappings(events: list[dict[str, Any]]) -> tuple[FixtureMapping, ...]:
    return tuple(
        FixtureMapping(
            provider_event_id=str(event["id"]),
            fixture_id=f"fixture-synthetic-{index + 1:03d}",
            status=MappingStatus.MAPPED,
            candidate_fixture_ids=(f"fixture-synthetic-{index + 1:03d}",),
            mapping_revision="synthetic-canary-compatibility-v1",
        )
        for index, event in enumerate(events)
    )


def _capture(
    tmp_path: Path, events: list[dict[str, Any]], *, name: str
) -> tuple[CaptureManifest, CaptureStore]:
    payload = json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    capture_root = tmp_path / name
    store = CaptureStore(
        capture_root,
        InternalRetentionPolicy(),
        approved_local_root=capture_root,
    )
    harness = CaptureHarness(
        store,
        CaptureBudget(maximum_requests=1, maximum_credits=2),
    )
    manifest = harness.record_offline_response(
        ProviderRequestSpec(
            endpoint="/v4/sports/soccer_synthetic_alpha/odds",
            sport_key="soccer_synthetic_alpha",
            markets=("h2h", "totals"),
        ),
        payload=payload,
        http_status=200,
        response_headers={
            "x-requests-last": "2",
            "x-requests-used": "2",
            "x-requests-remaining": "998",
        },
        mappings=_mappings(events),
        first_observed_at=datetime(2030, 2, 5, 12, 0, tzinfo=UTC),
        ingested_at=datetime(2030, 2, 5, 12, 0, 1, tzinfo=UTC),
    )
    return manifest, store


def test_synthetic_canary_fixture_is_reproducible_and_provider_free() -> None:
    generator = _load_module(GENERATOR_PATH, "generate_synthetic_canary_fixture")
    assert FIXTURE_PATH.read_text(encoding="utf-8") == generator.render_fixture()
    fixture = _fixture()
    assert fixture["provenance"] == "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD"
    rendered = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "event-synthetic-001" in rendered
    assert "Home Alpha" in rendered
    assert "Away Beta" in rendered
    assert "bookmaker_alpha" in rendered
    assert "bookmaker_beta" in rendered


def test_cardinality_fixture_matches_the_sanitized_c0_denominator() -> None:
    fixture = _fixture()
    events = cast(list[dict[str, Any]], fixture["responses"]["c0_cardinality_equivalent"])
    market_objects: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    bookmaker_keys: set[str] = set()
    bookmaker_occurrences = 0
    totals_by_event: list[int] = []
    for event in events:
        event_totals = 0
        for bookmaker in cast(list[dict[str, Any]], event["bookmakers"]):
            bookmaker_occurrences += 1
            bookmaker_keys.add(str(bookmaker["key"]))
            for market in cast(list[dict[str, Any]], bookmaker["markets"]):
                key = str(market["key"])
                market_objects[key] += 1
                outcomes[key] += len(cast(list[object], market["outcomes"]))
                event_totals += int(key == "totals")
                for outcome in cast(list[dict[str, object]], market["outcomes"]):
                    assert float(cast(float, outcome["price"])) > 100
        totals_by_event.append(event_totals)
    expected = cast(dict[str, Any], fixture["expected_cardinality"])
    assert len(events) == expected["event_count"] == 4
    assert len(bookmaker_keys) == expected["unique_bookmaker_count"] == 19
    assert bookmaker_occurrences == expected["event_bookmaker_occurrence_count"] == 76
    assert market_objects == Counter({"h2h": 76, "totals": 51, "h2h_lay": 8})
    assert outcomes == Counter({"h2h": 228, "totals": 102, "h2h_lay": 24})
    assert totals_by_event == expected["totals_by_event"] == [13, 13, 13, 12]


def test_pr59_replays_the_cardinality_fixture_and_ignores_unsupported_market(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    events = cast(list[dict[str, Any]], fixture["responses"]["c0_cardinality_equivalent"])
    manifest, store = _capture(tmp_path, events, name="cardinality")
    assert manifest.observation_count == 330
    first = store.replay(manifest.snapshot_id)
    second = store.replay(manifest.snapshot_id)
    assert first == second
    assert first.observation_count == 330
    assert first.network_calls == first.provider_calls == 0

    canary_paths = sorted(WITNESS_TOOL._schema_paths(events))
    harness_paths = sorted(
        WITNESS_TOOL._neutralize_harness_path(item)
        for item in manifest.schema_fingerprint.paths_and_types
    )
    assert harness_paths == canary_paths
    assert canonical_sha256(canary_paths) == fixture["expected_neutral_path_type_signature_sha256"]


def test_structural_fixture_covers_optional_market_timestamp_paths(tmp_path: Path) -> None:
    fixture = _fixture()
    events = cast(
        list[dict[str, Any]],
        fixture["responses"]["structural_optional_timestamp_paths"],
    )
    manifest, store = _capture(tmp_path, events, name="optional-timestamps")
    assert manifest.observation_count == 20
    rows = [
        cast(dict[str, Any], json.loads(line))
        for line in (store.root / manifest.normalized_storage_key).read_bytes().splitlines()
    ]
    assert sum(row["market_last_update"] is None for row in rows) == 3


def test_neutral_signature_detects_optional_presence_mutation() -> None:
    fixture = _fixture()
    original = cast(
        list[dict[str, Any]],
        fixture["responses"]["structural_optional_timestamp_paths"],
    )
    mutated = copy.deepcopy(original)
    cast(list[dict[str, Any]], mutated[1]["bookmakers"])[0].pop("last_update")
    original_paths = sorted(WITNESS_TOOL._schema_paths(original))
    mutated_paths = sorted(WITNESS_TOOL._schema_paths(mutated))
    assert original_paths == mutated_paths
    assert canonical_sha256(
        WITNESS_TOOL._neutral_schema_material(original, original_paths)
    ) != canonical_sha256(WITNESS_TOOL._neutral_schema_material(mutated, mutated_paths))


def test_semantic_projection_verifies_before_after_and_absent_market_timestamps(
    tmp_path: Path,
) -> None:
    fixture = _fixture()
    source = cast(
        list[dict[str, Any]],
        fixture["responses"]["structural_optional_timestamp_paths"],
    )
    event = copy.deepcopy(source[0])
    base_bookmaker = cast(list[dict[str, Any]], event["bookmakers"])[0]
    bookmakers = [copy.deepcopy(base_bookmaker) for _ in range(3)]
    for index, bookmaker in enumerate(bookmakers):
        bookmaker["key"] = f"bookmaker_temporal_{index + 1}"
        bookmaker["title"] = f"Synthetic Temporal {index + 1}"
        market = cast(list[dict[str, Any]], bookmaker["markets"])[0]
        market["last_update"] = (
            "2030-02-05T11:59:00Z" if index == 0 else "2030-02-05T12:01:00Z" if index == 1 else None
        )
        if market["last_update"] is None:
            market.pop("last_update")
        bookmaker["markets"] = [market]
    event["bookmakers"] = bookmakers
    events = [event]
    manifest, store = _capture(tmp_path, events, name="temporal-semantics")
    rows = [
        cast(dict[str, Any], json.loads(line))
        for line in (store.root / manifest.normalized_storage_key).read_bytes().splitlines()
    ]
    expected = WITNESS_TOOL._expected_supported_semantic_projection(
        events,
        _mappings(events),
        datetime(2030, 2, 5, 12, 0, tzinfo=UTC),
    )
    actual = WITNESS_TOOL._harness_semantic_projection(rows)
    assert actual == expected
    summary = WITNESS_TOOL._temporal_projection_summary(
        actual, datetime(2030, 2, 5, 12, 0, tzinfo=UTC)
    )
    assert summary == {
        "available_at_rule_verified": 9,
        "market_last_update_absent": 3,
        "market_last_update_after_first_observed": 3,
        "market_last_update_before_first_observed": 3,
    }


def test_leak_scan_is_fail_closed_for_every_forbidden_category() -> None:
    tokens = {"provider_event_ids": {b"real-event-token"}}
    separator = chr(92)
    forbidden_path = "C:" + separator + "private" + separator + "canary"
    clean = WITNESS_TOOL._scan_candidate_material(
        b"synthetic-only",
        tokens,
        sentinel=b"synthetic-secret-control",
        forbidden_paths=(forbidden_path,),
    )
    assert clean["verdict"] == "PASS"
    assert clean["total_failure_count"] == 0
    assert clean["absolute_canary_path_occurrences"] == 0

    query_url = b"https://" + b"provider.invalid/odds" + b"?" + b"token" + b"=" + b"forbidden"
    userinfo_url = b"https://" + b"user" + b":" + b"password@provider.invalid/odds"
    isolated_query_fragment = b"api" + b"Key" + b"=" + b"forbidden"
    alternate_windows_path = (
        "D:" + separator + "Users" + separator + "someone" + separator + "evidence.json"
    ).encode()
    unc_path = (
        separator * 2 + "server" + separator + "share" + separator + "evidence.json"
    ).encode()
    posix_user_path = ("/" + "home/someone/evidence.json").encode()
    contaminated = WITNESS_TOOL._scan_candidate_material(
        b" ".join(
            (
                b"real-event-token",
                b"synthetic-secret-control",
                query_url,
                userinfo_url,
                isolated_query_fragment,
                forbidden_path.encode(),
                alternate_windows_path,
                unc_path,
                posix_user_path,
            )
        ),
        tokens,
        sentinel=b"synthetic-secret-control",
        forbidden_paths=(forbidden_path,),
    )
    assert contaminated["verdict"] == "FAIL"
    assert contaminated["real_canary_data_leak_count"] == 1
    assert contaminated["synthetic_secret_sentinel_occurrences_in_compatibility_candidate"] == 1
    assert contaminated["authenticated_url_occurrences"] == 2
    assert contaminated["sensitive_query_fragment_occurrences"] >= 2
    assert contaminated["generic_absolute_path_occurrences"] >= 4
    assert contaminated["exact_forbidden_path_occurrences"] >= 1
    assert contaminated["absolute_canary_path_occurrences"] >= 5
    assert contaminated["total_failure_count"] >= 10


def test_external_evidence_root_binds_leak_scan_guards_and_commands(tmp_path: Path) -> None:
    (tmp_path / "canary-leak-scan-v1.json").write_text("{}\n", encoding="utf-8")
    guards = tmp_path / "derived" / "environment-and-network-guards.json"
    guards.parent.mkdir()
    guards.write_text("{}\n", encoding="utf-8")
    (tmp_path / "commands.jsonl").write_text("{}\n", encoding="utf-8")
    initial = WITNESS_TOOL._anchored_evidence_pack_sha256(tmp_path)
    (tmp_path / "canary-leak-scan-v1.json").write_text('{"verdict":"FAIL"}\n', encoding="utf-8")
    after_leak_change = WITNESS_TOOL._anchored_evidence_pack_sha256(tmp_path)
    assert after_leak_change != initial
    guards.write_text('{"network_attempts":1}\n', encoding="utf-8")
    assert WITNESS_TOOL._anchored_evidence_pack_sha256(tmp_path) != after_leak_change


def test_quota_transition_is_bound_to_absolute_receipt_and_global_values() -> None:
    captures: dict[str, dict[str, object]] = {
        "C0": {
            "quota": {
                "requests_last": 2,
                "requests_used": 2,
                "requests_remaining": 19998,
                "interpretation": "COHERENT_WITH_ONE_REQUEST_AND_TWO_CREDITS",
            }
        },
        "C2": {
            "quota": {
                "requests_last": 2,
                "requests_used": 4,
                "requests_remaining": 19996,
                "interpretation": "COHERENT_WITH_ONE_REQUEST_AND_TWO_CREDITS",
            }
        },
    }
    global_quota = {
        "credits_used_this_run_from_x_requests_last": 4,
        "provider_account_credits_used": 4,
        "provider_account_credits_remaining": 19996,
    }
    WITNESS_TOOL._verify_quota_transitions(captures, global_quota)

    shifted = copy.deepcopy(captures)
    cast(dict[str, object], shifted["C0"]["quota"])["requests_used"] = 100
    cast(dict[str, object], shifted["C0"]["quota"])["requests_remaining"] = 19900
    cast(dict[str, object], shifted["C2"]["quota"])["requests_used"] = 102
    cast(dict[str, object], shifted["C2"]["quota"])["requests_remaining"] = 19898
    with pytest.raises(RuntimeError, match="CANARY_PER_RECEIPT_QUOTA_TRANSITION_INCOHERENT"):
        WITNESS_TOOL._verify_quota_transitions(shifted, global_quota)


def test_committed_witness_is_aggregate_only_and_keeps_all_locks() -> None:
    witness = cast(
        dict[str, Any],
        json.loads(
            (REPORT_ROOT / "canary-harness-compatibility-witness-v1.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    assert witness["mandatory_answers"] == EXPECTED_ANSWERS
    assert witness["captures_discovered"] == witness["captures_admitted"] == 2
    assert witness["captures_excluded"] == 0
    assert witness["network_call_count"] == witness["provider_call_count"] == 0
    assert witness["provider_secret_read_count"] == witness["real_data_leak_count"] == 0
    assert witness["live_canary_authorized"] is False
    assert witness["compatibility_verdict"] == ("ROBIN_CANARY_TO_HARNESS_COMPATIBILITY_PROVEN")
    assert witness["comparison_scope"]["admitted_market_keys"] == ["h2h", "totals"]
    assert witness["comparison_scope"]["unsupported_observed_market_keys"] == ["h2h_lay"]

    committed = b"".join(
        (REPORT_ROOT / name).read_bytes()
        for name in (
            "canary-harness-compatibility-witness-v1.json",
            "real-schema-coverage-summary-v1.json",
            "canary-external-evidence-reference-v1.json",
            "canary-final-disposition-v1.json",
        )
    )
    windows_user_prefix = b"C:" + bytes((92,)) + b"Users" + bytes((92,))
    unix_user_prefix = b"/" + b"Users" + b"/"
    assert windows_user_prefix not in committed
    assert unix_user_prefix not in committed
    assert b"Home Alpha" not in committed
    assert b"Away Beta" not in committed
    assert b"bookmaker_alpha" not in committed
    assert b"event-synthetic-" not in committed


def test_witness_tool_blocks_network_and_never_reads_the_provider_secret() -> None:
    source = WITNESS_TOOL_PATH.read_text(encoding="utf-8")
    assert "class NetworkBlockade" in source
    assert 'os.environ.get("THE_ODDS_API_KEY")' not in source
    assert 'socket.socket, "connect"' in source
    assert '"getaddrinfo"' in source
    assert "http.client.HTTPSConnection" in source
    assert "urllib.request" in source
