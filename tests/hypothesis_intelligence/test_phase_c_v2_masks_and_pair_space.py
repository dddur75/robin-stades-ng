from __future__ import annotations

import base64
import gzip
import json
import shutil
import struct
from pathlib import Path

import pytest

from robin.hypothesis_intelligence import phase_c_v2 as v2
from scripts import run_phase_c_v2_campaign as campaign

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "reports/closure/phase-c-v2-source-evidence"


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def freeze_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copied = tmp_path / "repo"
    directories = (
        "configs/hypothesis-tags",
        "configs/hypothesis-campaigns",
        "reports/closure/phase-c-v2-source-evidence",
        "reports/hypothesis-genome",
        "reports/hypothesis-masks",
        "reports/hypothesis-research/v2/full",
    )
    for relative in directories:
        shutil.copytree(ROOT / relative, copied / relative)
    summary = "reports/hypothesis-research/v2/pair-census-summary-v2.json"
    (copied / summary).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / summary, copied / summary)
    monkeypatch.setattr(campaign, "ROOT", copied)
    monkeypatch.setattr(
        campaign,
        "REGISTRY",
        copied / "configs/hypothesis-tags/canonical-tag-registry-v2.json",
    )
    monkeypatch.setattr(
        campaign,
        "PROPERTY_CONTRACT",
        copied / "configs/hypothesis-tags/predictor-property-contract-v2.json",
    )
    monkeypatch.setattr(
        campaign,
        "PROPERTY_SET",
        copied / "reports/hypothesis-genome/predictor-eligible-property-set-v2.json",
    )
    monkeypatch.setattr(
        campaign,
        "SOURCE_BUNDLE",
        copied / "reports/closure/phase-c-v2-source-evidence",
    )
    monkeypatch.setattr(
        campaign,
        "MASK_MANIFEST",
        copied / "reports/hypothesis-masks/atomic-mask-manifest-v2.json",
    )
    monkeypatch.setattr(
        campaign,
        "MASK_PAYLOAD",
        copied / "reports/hypothesis-masks/mask-payload-bundle-v2.json.gz",
    )
    monkeypatch.setattr(
        campaign,
        "PAIR_SUMMARY",
        copied / "reports/hypothesis-research/v2/pair-census-summary-v2.json",
    )
    monkeypatch.setattr(
        campaign,
        "FULL_ROOT",
        copied / "reports/hypothesis-research/v2/full",
    )
    monkeypatch.setattr(
        campaign,
        "CAMPAIGN",
        copied / "configs/hypothesis-campaigns/exhaustive-property-campaign-v2.json",
    )
    return copied


@pytest.fixture(scope="module")
def frozen() -> tuple[
    dict[str, object],
    v2.FeatureInputs,
    dict[str, tuple[v2.Observation, ...]],
    dict[str, tuple[int, int]],
    dict[str, dict[str, float]],
]:
    registry = load(ROOT / "configs/hypothesis-tags/canonical-tag-registry-v2.json")
    inputs = v2.load_feature_inputs(BUNDLE)
    observations = v2.build_observations(registry, inputs)
    masks, thresholds = v2.build_structural_masks(registry, inputs, observations)
    return registry, inputs, observations, masks, thresholds


def decode_v1_masks() -> dict[str, tuple[int, int]]:
    with gzip.open(
        ROOT
        / "reports/closure/phase-c-v1-durable-evidence/mask-payload-bundle-v1.json.gz",
        "rt",
        encoding="utf-8",
    ) as stream:
        payload = json.load(stream)
    result: dict[str, tuple[int, int]] = {}
    for row in payload["records"]:
        envelope = base64.b64decode(row["payload_base64"])
        raw = envelope[:-32]
        count, identity_length = struct.unpack("<QH", raw[8:18])
        assert count == 1_756
        offset = 18 + 32 + identity_length
        known = int.from_bytes(raw[offset : offset + 220], "little")
        true = int.from_bytes(raw[offset + 220 : offset + 440], "little")
        result[str(row["tag_id"])] = (known, true)
    return result


def test_v2_feature_inputs_are_sorted_aware_and_target_exclusive(
    frozen: tuple[object, v2.FeatureInputs, object, object, object],
) -> None:
    inputs = frozen[1]
    assert len(inputs.fixtures) == 1_756
    assert len(inputs.facts) == 3_512
    assert all(fixture.kickoff.tzinfo is not None for fixture in inputs.fixtures)
    for fixture in inputs.fixtures:
        for side in ("HOME", "AWAY"):
            target_fact = inputs.facts_by_fixture[fixture.fixture_key][side]
            history = v2.eligible_history(inputs.history_by_team[target_fact.team_key], fixture)
            assert all(row.fixture_key != fixture.fixture_key for row in history)
            assert all(row.available_at < fixture.kickoff for row in history)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="PHASE_C_V2_NAIVE_DATETIME_REJECTED"):
        v2.parse_utc("2024-01-01T12:00:00")


def test_v2_builds_exact_150_masks_and_preserves_unknown(
    frozen: tuple[
        dict[str, object],
        v2.FeatureInputs,
        dict[str, tuple[v2.Observation, ...]],
        dict[str, tuple[int, int]],
        object,
    ],
) -> None:
    registry, inputs, observations, masks, _ = frozen
    assert len(observations) == len(masks) == registry["tag_count"] == 150
    universe = (1 << len(inputs.fixtures)) - 1
    assert all(true & ~known == 0 for known, true in masks.values())
    assert all((known | (universe ^ known)) == universe for known, _ in masks.values())
    assert any(known != universe for known, _ in masks.values())


def test_all_80_v1_structural_masks_are_bit_exact(
    frozen: tuple[object, object, object, dict[str, tuple[int, int]], object],
) -> None:
    masks = frozen[3]
    legacy = decode_v1_masks()
    assert len(legacy) == 80
    assert {tag_id: masks[tag_id] for tag_id in legacy} == legacy


def test_target_label_mutation_cannot_change_registry_masks_or_pair_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = freeze_copy(tmp_path, monkeypatch)
    before_mask = load(campaign.MASK_MANIFEST)
    before = {
        "registry_hash": load(campaign.REGISTRY)["registry_hash"],
        "mask_records_hash": v2.object_hash(before_mask["records"]),
        "mask_payload_content_sha256": before_mask["payload"][  # type: ignore[index]
            "content_sha256"
        ],
        "pair_space_hash": load(campaign.PAIR_SUMMARY)["pair_space_hash"],
    }
    labels = list(v2.load_target_labels(BUNDLE))
    labels.reverse()
    labels = [dict(row, match_result_90m="MUTATED") for row in labels]
    assert labels

    def reject_target_label_load(_: Path) -> tuple[dict[str, str], ...]:
        raise AssertionError("target labels entered target-blind freeze")

    monkeypatch.setattr(v2, "load_target_labels", reject_target_label_load)
    campaign.build_freeze()
    after_mask = load(campaign.MASK_MANIFEST)
    after = {
        "registry_hash": load(campaign.REGISTRY)["registry_hash"],
        "mask_records_hash": v2.object_hash(after_mask["records"]),
        "mask_payload_content_sha256": after_mask["payload"][  # type: ignore[index]
            "content_sha256"
        ],
        "pair_space_hash": load(campaign.PAIR_SUMMARY)["pair_space_hash"],
    }
    assert copied == campaign.ROOT
    assert before == after


def test_formation_known_other_is_false_not_unknown(
    frozen: tuple[
        dict[str, object],
        v2.FeatureInputs,
        dict[str, tuple[v2.Observation, ...]],
        object,
        object,
    ],
) -> None:
    registry, inputs, observations, _, _ = frozen
    tag = next(
        row
        for row in registry["tags"]  # type: ignore[index]
        if row["tag_id"]
        == "TEAM_HOME.FORMATION_STRUCTURE.LAST_PRIOR_FORMATION.LAST1.EQ_F_4_3_3.V2"
    )
    states, _ = v2.tag_states(
        tag,
        observations[str(tag["tag_id"])],
        inputs.fixtures,
        tuple(range(703)),
        len(inputs.fixtures),
    )
    known_other_indices = [
        index
        for index, observation in enumerate(observations[str(tag["tag_id"])])
        if observation.known
        and isinstance(observation.value, str)
        and observation.value
        not in {"3-4-3", "3-5-2", "4-1-4-1", "4-2-3-1", "4-3-3", "4-4-2", "5-3-2", "5-4-1"}
    ]
    assert known_other_indices
    assert all(states[index] is False for index in known_other_indices)


def test_pair_census_is_exhaustive_target_blind_and_pre_sharded(
    frozen: tuple[dict[str, object], object, object, dict[str, tuple[int, int]], object],
) -> None:
    registry, _, _, masks, _ = frozen
    census, eligible = v2.enumerate_pair_census(registry, masks)
    assert len(census) == 11_175
    assert sum(row["reason"] == "SAME_PROPERTY_REDUNDANCY" for row in census) == 763
    assert sum(row["disposition"] == "PRUNED" for row in census) + len(eligible) == 11_175
    assert len({row["pair_id"] for row in census}) == 11_175
    assert all(0 <= int(row["shard_id"]) < 64 for row in census)
    assert all("selection_hash" not in row and "seed" not in row for row in census)


def test_freeze_campaign_self_hash_and_source_lineage_tamper_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = freeze_copy(tmp_path, monkeypatch)
    path = copied / "configs/hypothesis-campaigns/exhaustive-property-campaign-v2.json"
    value = load(path)
    value["source_manifest_hash"] = "1" * 64
    value["campaign_hash"] = v2.object_hash(
        {key: item for key, item in value.items() if key != "campaign_hash"}
    )
    path.write_bytes(v2.canonical_bytes(value) + b"\n")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_CAMPAIGN_LINEAGE_MISMATCH"):
        campaign.verify_freeze()


def test_freeze_rehashed_prospective_and_external_effect_tamper_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = freeze_copy(tmp_path, monkeypatch)
    path = copied / "configs/hypothesis-campaigns/exhaustive-property-campaign-v2.json"
    value = load(path)
    value["point_in_time_source_provenance"] = True
    value["proof_ceiling"] = "PROSPECTIVE"
    value["external_effects"]["provider_calls"] = 9  # type: ignore[index]
    value["campaign_hash"] = v2.object_hash(
        {key: item for key, item in value.items() if key != "campaign_hash"}
    )
    path.write_bytes(v2.canonical_bytes(value) + b"\n")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_CAMPAIGN_SAFETY_CONTRACT_MISMATCH"):
        campaign.verify_freeze()


def test_freeze_mask_registry_lineage_tamper_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = freeze_copy(tmp_path, monkeypatch)
    path = copied / "reports/hypothesis-masks/atomic-mask-manifest-v2.json"
    value = load(path)
    value["registry_hash"] = "2" * 64
    value["manifest_hash"] = v2.object_hash(
        {key: item for key, item in value.items() if key != "manifest_hash"}
    )
    path.write_bytes(v2.canonical_bytes(value) + b"\n")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_MASK_LINEAGE_MISMATCH"):
        campaign.verify_freeze()


def test_freeze_pair_eligible_union_tamper_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = freeze_copy(tmp_path, monkeypatch)
    path = copied / "reports/hypothesis-research/v2/pair-census-summary-v2.json"
    value = load(path)
    value["eligible_pair_ids_hash"] = "3" * 64
    value["summary_hash"] = v2.object_hash(
        {key: item for key, item in value.items() if key != "summary_hash"}
    )
    path.write_bytes(v2.canonical_bytes(value) + b"\n")
    with pytest.raises(RuntimeError, match="PHASE_C_V2_ELIGIBLE_PAIR_IDS_HASH_MISMATCH"):
        campaign.verify_freeze()


def test_fixed_thresholds_and_after_result_forced_false_are_distinct_from_unknown(
    frozen: tuple[
        dict[str, object],
        object,
        dict[str, tuple[v2.Observation, ...]],
        object,
        object,
    ],
) -> None:
    registry, _, observations, _, _ = frozen
    after_tag = next(
        row
        for row in registry["tags"]  # type: ignore[index]
        if row["tag_id"]
        == "TEAM_HOME.STRENGTH_FORM.AFTER_WIN_POINTS_PER_MATCH.STD_MIN3_TRANSITIONS.HIGH_Q67.V2"
    )
    rows = observations[str(after_tag["tag_id"])]
    assert any(row.forced_false and row.known for row in rows)
    assert any(not row.known for row in rows)
