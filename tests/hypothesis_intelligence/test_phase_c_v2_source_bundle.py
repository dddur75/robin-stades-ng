from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts import export_phase_c_v2_source_bundle as source

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "reports/closure/phase-c-v2-source-evidence"


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def load_gzip(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    assert isinstance(value, dict)
    return value


def event_row(
    *,
    event_type: object = "Card",
    detail: object = "Yellow Card",
    team_id: object = 10,
) -> dict[str, object]:
    return {
        "entity_type": "fixture_event",
        "canonical_fixture_id": "fixture-source-key",
        "provider_fixture_id": 1,
        "provider_team_id": team_id,
        "data": {
            "type": event_type,
            "detail": detail,
            "time": {"elapsed": 12, "extra": None},
            "team": {"id": team_id},
            "player": {"id": 100},
            "assist": {"id": None},
            "comments": None,
        },
    }


def test_v2_source_manifest_counts_and_five_shards() -> None:
    manifest = source.verify(BUNDLE)
    counts = manifest["counts"]
    assert isinstance(counts, dict)
    assert counts["normalized_row_count"] == 286_075
    assert counts["scientific_fixture_count"] == 1_756
    assert counts["team_fixture_count"] == 3_512
    assert counts["event_collection_count"] == 1_756
    assert counts["formation_fact_count"] == 3_512
    assert counts["scientific_event_fact_count"] == 29_033
    assert counts["substitution_fact_count"] == 15_793
    assert counts["generic_card_fact_count"] == 7_479
    assert counts["legacy_generic_card_fact_count"] == 7_487
    assert counts["yellow_card_fact_count"] == 7_150
    assert counts["dismissal_fact_count"] == 329
    assert counts["event_exact_repetitions"] == 1_897
    assert counts["target_label_count"] == 1_756
    assert manifest["team_match_shard_count"] == 5
    files = manifest["files"]
    assert isinstance(files, list)
    assert sum(str(row["path"]).startswith("team-match-facts-") for row in files) == 5


def test_v2_source_ordinals_and_targets_are_physically_separate() -> None:
    universe = load_gzip(BUNDLE / "fixture-universe-v2.json.gz")["records"]
    labels = load_gzip(BUNDLE / "target-labels-v2.json.gz")["records"]
    assert isinstance(universe, list) and isinstance(labels, list)
    assert len(universe) == len(labels) == 1_756
    assert all(re.fullmatch(r"fixture:\d{4}", str(row["fixture_key"])) for row in universe)
    all_facts: list[dict[str, object]] = []
    for path in sorted(BUNDLE.glob("team-match-facts-competition-*-v2.json.gz")):
        records = load_gzip(path)["records"]
        assert isinstance(records, list)
        all_facts.extend(records)
    assert len(all_facts) == 3_512
    assert all(re.fullmatch(r"team:\d{3}", str(row["team_key"])) for row in all_facts)
    assert all(re.fullmatch(r"competition:\d{2}", str(row["competition_key"])) for row in all_facts)
    forbidden_targets = {"match_result_90m", "total_goals_2_5_90m"}
    assert all(forbidden_targets.isdisjoint(row) for row in all_facts)
    assert all(set(row) == {"fixture_key", *forbidden_targets} for row in labels)
    formation_statuses = [str(row["formation_status"]) for row in all_facts]
    assert formation_statuses.count("KNOWN_SELECTED_CATEGORY") == 2_646
    assert formation_statuses.count("KNOWN_OTHER_CATEGORY") == 866
    assert not any(status.startswith("UNKNOWN") for status in formation_statuses)


def test_v2_source_transport_and_content_hashes_are_enforced(tmp_path: Path) -> None:
    manifest = load_json(BUNDLE / "source-evidence-manifest-v2.json")
    records = manifest["files"]
    assert isinstance(records, list)
    for row in records:
        path = BUNDLE / str(row["path"])
        payload = path.read_bytes()
        assert len(payload) == row["bytes"]
        assert hashlib.sha256(payload).hexdigest() == row["sha256"]
        with gzip.open(path, "rb") as stream:
            content = stream.read()
        assert hashlib.sha256(content).hexdigest() == row["content_sha256"]

    copied = tmp_path / "bundle"
    copied.mkdir()
    for path in BUNDLE.iterdir():
        if path.is_file():
            (copied / path.name).write_bytes(path.read_bytes())
    mutated = load_json(copied / "source-evidence-manifest-v2.json")
    mutated_files = mutated["files"]
    assert isinstance(mutated_files, list)
    mutated_files[0]["content_sha256"] = "0" * 64
    mutated_without_hash = dict(mutated)
    mutated_without_hash.pop("manifest_hash", None)
    mutated["manifest_hash"] = hashlib.sha256(
        json.dumps(
            mutated_without_hash,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    (copied / "source-evidence-manifest-v2.json").write_text(
        json.dumps(mutated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="V2_SOURCE_CONTENT_HASH_MISMATCH"):
        source.verify(copied)


def test_v2_source_manifest_and_authority_are_fail_closed(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    copied.mkdir()
    for path in BUNDLE.iterdir():
        if path.is_file():
            (copied / path.name).write_bytes(path.read_bytes())
    manifest_path = copied / "source-evidence-manifest-v2.json"
    manifest = load_json(manifest_path)
    manifest["manifest_hash"] = "0" * 64
    manifest["source_lock_sha256"] = "1" * 64
    manifest["source_run_id"] = 0
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="V2_SOURCE_MANIFEST_HASH_MISMATCH"):
        source.verify(copied)


def test_v2_source_replay_is_two_fresh_byte_identical_exports() -> None:
    replay = load_json(BUNDLE / "source-export-replay-v2.json")
    manifest = load_json(BUNDLE / "source-evidence-manifest-v2.json")
    assert replay["manifest_hash"] == manifest["manifest_hash"]
    assert replay["replay_runs"] == 2
    assert replay["replay_identical"] is True
    assert replay["compared_file_count"] == 9
    assert replay["additional_network_reads"] == 0
    assert replay["provider_calls"] == replay["r2_gets"] == 0
    assert replay["remote_sql"] == replay["odds_credits"] == 0
    assert replay["manual_deployments"] == replay["triples"] == 0


def test_event_semantics_deduplicate_and_second_yellow_is_dual_counted() -> None:
    row = event_row(detail="Second Yellow Card")
    facts, counts, invalid, observed = source.event_facts([row, row])
    fact = facts[("fixture-source-key", 10)]
    assert fact["yellow_cards"] == 1
    assert fact["dismissals"] == 1
    assert fact["generic_cards"] == 1
    assert counts["scientific_event_fact_count"] == 1
    assert counts["event_exact_repetitions"] == 1
    assert invalid == set()
    assert observed == {"fixture-source-key": {10}}


def test_null_event_type_team_and_card_detail_fail_closed() -> None:
    facts, _, invalid, _ = source.event_facts([event_row(event_type=None)])
    fact = facts[("fixture-source-key", 10)]
    assert fact["substitutions_status"] == "UNKNOWN_UNCLASSIFIABLE_TYPE"
    assert fact["generic_cards_status"] == "UNKNOWN_UNCLASSIFIABLE_TYPE"
    assert fact["cards_status"] == "UNKNOWN_UNCLASSIFIABLE_TYPE"

    facts, _, invalid, _ = source.event_facts([event_row(detail=None)])
    assert invalid == set()
    assert facts[("fixture-source-key", 10)]["cards_status"] == (
        "UNKNOWN_UNCLASSIFIABLE_DETAIL"
    )

    _, _, invalid, _ = source.event_facts([event_row(team_id=None)])
    assert invalid == {"fixture-source-key"}

    facts, _, _, _ = source.event_facts([event_row(detail="Blue Card")])
    assert facts[("fixture-source-key", 10)]["cards_status"] == (
        "UNKNOWN_UNCLASSIFIABLE_DETAIL"
    )


def test_v2_p0_source_lock_projection_is_fail_closed(tmp_path: Path) -> None:
    copied = tmp_path / "phase-c-v2-source-lock.json"
    lock = load_json(ROOT / "configs/execution/phase-c-v2-source-lock.json")
    lock["source_lock_sha256_lf"] = "0" * 64
    copied.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="V2_P0_SOURCE_LOCK_HASH_MISMATCH"):
        source.validate_source_authority(copied)


def test_committed_bundle_contains_no_literal_provider_identifiers_or_paths() -> None:
    forbidden = (
        "provider_fixture_id",
        "provider_team_id",
        "canonical_fixture_id",
        "canonical_team_id",
        "source_payload_hash",
        "C:\\\\",
        "/tmp/",
    )
    for path in BUNDLE.iterdir():
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                text = stream.read()
        else:
            text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden)
