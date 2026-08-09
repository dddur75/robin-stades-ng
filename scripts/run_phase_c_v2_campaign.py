"""Run the bounded, Git-durable Phase C V2 campaign without network access."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import platform
import sys
import tempfile
import time
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from robin.hypothesis_intelligence import phase_c_v2 as v2  # noqa: E402
from scripts import export_phase_c_v2_source_bundle as source  # noqa: E402

REGISTRY = ROOT / "configs/hypothesis-tags/canonical-tag-registry-v2.json"
PROPERTY_CONTRACT = ROOT / "configs/hypothesis-tags/predictor-property-contract-v2.json"
PROPERTY_SET = ROOT / "reports/hypothesis-genome/predictor-eligible-property-set-v2.json"
SOURCE_BUNDLE = ROOT / "reports/closure/phase-c-v2-source-evidence"
MASK_MANIFEST = ROOT / "reports/hypothesis-masks/atomic-mask-manifest-v2.json"
MASK_PAYLOAD = ROOT / "reports/hypothesis-masks/mask-payload-bundle-v2.json.gz"
PAIR_SUMMARY = ROOT / "reports/hypothesis-research/v2/pair-census-summary-v2.json"
FULL_ROOT = ROOT / "reports/hypothesis-research/v2/full"
CAMPAIGN = ROOT / "configs/hypothesis-campaigns/exhaustive-property-campaign-v2.json"
ATOMIC_SUMMARY = ROOT / "reports/hypothesis-research/v2/atomic-results-summary-v2.json"
PAIR_RESULTS_SUMMARY = ROOT / "reports/hypothesis-research/v2/pair-results-summary-v2.json"
MULTIPLICITY_SUMMARY = ROOT / "reports/hypothesis-research/v2/campaign-multiplicity-v2.json"
NEGATIVE_CONTROLS = ROOT / "reports/hypothesis-research/v2/negative-controls-v2.json"
NEGATIVE_GUARD_PROOF = (
    ROOT / "reports/hypothesis-research/v2/negative-control-guard-execution-v2.json"
)
RESULT_MANIFEST = ROOT / "reports/hypothesis-research/v2/full-results-manifest-v2.json"
CHECKPOINT_RECEIPT = ROOT / "reports/hypothesis-research/v2/checkpoint-resume-receipt-v2.json"
CAMPAIGN_REPLAY = ROOT / "reports/hypothesis-research/v2/campaign-replay-v2.json"
CLOSURE_REPORT = ROOT / "reports/closure/phase-c-v2-full-bounded-expansion-closure-v1.json"
GENERATED_AT = "2026-08-08T23:30:00Z"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"PHASE_C_V2_JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: object, *, compact: bool = False) -> dict[str, Any]:
    payload = (
        v2.canonical_bytes(value)
        if compact
        else json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    ) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "content_sha256": v2.object_hash(value), "compression": "NONE"}


def write_gzip(path: Path, value: object) -> dict[str, Any]:
    content = v2.canonical_bytes(value)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(content)
    payload = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "compression": "GZIP_MTIME_0",
        "transport_identity": "RUNTIME_BOUND",
        "reconstruction_identity": "CANONICAL_DECOMPRESSED_CONTENT_SHA256",
        "python": platform.python_version(),
        "zlib_build": zlib.ZLIB_VERSION,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    }


def canonical_gzip_bytes(value: object) -> bytes:
    content = v2.canonical_bytes(value)
    buffer = io.BytesIO()
    with gzip.GzipFile(
        fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9
    ) as stream:
        stream.write(content)
    return buffer.getvalue()


def write_work_gzip(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_gzip_bytes(value))


def write_json_under(
    base: Path, relative_path: str, value: object, *, compact: bool = False
) -> dict[str, Any]:
    path = base / relative_path
    payload = (
        v2.canonical_bytes(value)
        if compact
        else json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    ) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_sha256": v2.object_hash(value),
        "compression": "NONE",
    }


def write_gzip_under(base: Path, relative_path: str, value: object) -> dict[str, Any]:
    path = base / relative_path
    content = v2.canonical_bytes(value)
    payload = canonical_gzip_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "compression": "GZIP_MTIME_0",
        "transport_identity": "RUNTIME_BOUND",
        "reconstruction_identity": "CANONICAL_DECOMPRESSED_CONTENT_SHA256",
        "python": platform.python_version(),
        "zlib_build": zlib.ZLIB_VERSION,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    }


def read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"PHASE_C_V2_GZIP_OBJECT_REQUIRED:{path}")
    return value


def verify_self_hash(
    value: Mapping[str, Any], hash_field: str, error: str
) -> str:
    stored = str(value.get(hash_field))
    computed = v2.object_hash(
        {key: item for key, item in value.items() if key != hash_field}
    )
    if stored != computed:
        raise RuntimeError(error)
    return stored


def require_sha256(value: object, error: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RuntimeError(error)
    return text


def descriptor_path(base: Path, descriptor: Mapping[str, Any]) -> Path:
    relative = Path(str(descriptor["path"]))
    if relative.is_absolute():
        raise RuntimeError("PHASE_C_V2_ABSOLUTE_DESCRIPTOR_PATH")
    resolved_base = base.resolve()
    resolved = (resolved_base / relative).resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError as error:
        raise RuntimeError("PHASE_C_V2_DESCRIPTOR_PATH_ESCAPE") from error
    return resolved


def verify_descriptor_json(
    base: Path, descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    path = descriptor_path(base, descriptor)
    payload = path.read_bytes()
    if (
        len(payload) != int(descriptor["bytes"])
        or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]
    ):
        raise RuntimeError(f"PHASE_C_V2_TRANSPORT_HASH_MISMATCH:{path}")
    if path.suffix != ".gz":
        raise RuntimeError(f"PHASE_C_V2_GZIP_DESCRIPTOR_REQUIRED:{path}")
    with gzip.open(path, "rb") as stream:
        content = stream.read()
    if hashlib.sha256(content).hexdigest() != descriptor["content_sha256"]:
        raise RuntimeError(f"PHASE_C_V2_CONTENT_HASH_MISMATCH:{path}")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise TypeError(f"PHASE_C_V2_GZIP_OBJECT_REQUIRED:{path}")
    return value


def campaign_work_root(override: Path | None = None) -> Path:
    campaign = read_json(CAMPAIGN)
    campaign_hash = str(campaign["campaign_hash"])
    root = override or (
        Path(tempfile.gettempdir()) / "robin-phase-c-v2" / campaign_hash
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_context() -> tuple[
    dict[str, Any],
    v2.FeatureInputs,
    dict[str, tuple[v2.Observation, ...]],
    tuple[dict[str, str], ...],
    dict[str, tuple[v2.FoldTagState, ...]],
    dict[str, tuple[dict[str, Any], ...]],
]:
    verify_freeze()
    registry = read_json(REGISTRY)
    inputs = v2.load_feature_inputs(SOURCE_BUNDLE)
    observations = v2.build_observations(registry, inputs)
    # The target loader is intentionally called only after the registry, masks,
    # pair census and campaign hashes have passed verify_freeze().
    labels = v2.load_target_labels(SOURCE_BUNDLE)
    fold_states = v2.build_fold_states(registry, inputs, observations)
    baselines = v2.build_baselines(registry, inputs, observations, labels)
    return registry, inputs, observations, labels, fold_states, baselines


def eligible_pairs_for_shard(shard_id: int) -> list[dict[str, Any]]:
    if shard_id < 0 or shard_id >= v2.PAIR_SHARD_COUNT:
        raise ValueError(f"PHASE_C_V2_SHARD_ID_OUT_OF_RANGE:{shard_id}")
    payload = read_gzip_json(
        FULL_ROOT / f"pair-census-shard-{shard_id:02d}-v2.json.gz"
    )
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise TypeError("PHASE_C_V2_PAIR_CENSUS_ROWS_REQUIRED")
    eligible = [dict(row) for row in rows if row.get("disposition") == "ELIGIBLE"]
    eligible.sort(key=lambda row: str(row["pair_id"]))
    if any(int(row["shard_id"]) != shard_id for row in eligible):
        raise RuntimeError("PHASE_C_V2_PAIR_SHARD_ASSIGNMENT_MISMATCH")
    return eligible


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"PHASE_C_V2_PROGRESS_ROW_REQUIRED:{path}")
        rows.append(value)
    return rows


def append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(v2.canonical_bytes(value) + b"\n")


def write_checkpoint(
    path: Path,
    *,
    shard_id: int,
    pair_ids: Sequence[str],
    completed_rows: Sequence[Mapping[str, Any]],
    previous_checkpoint_hash: str | None,
    complete: bool,
) -> dict[str, Any]:
    campaign = read_json(CAMPAIGN)
    pair_summary = read_json(PAIR_SUMMARY)
    completed_ids = [str(row["pair_id"]) for row in completed_rows]
    if completed_ids != list(pair_ids[: len(completed_ids)]):
        raise RuntimeError("PHASE_C_V2_CHECKPOINT_PREFIX_MISMATCH")
    checkpoint: dict[str, Any] = {
        "schema_version": "phase-c-v2-pair-checkpoint",
        "mission_id": "PHASE-C-FULL-BOUNDED-EXPANSION-V2",
        "stage": "COMPATIBLE_PAIR_SEARCH",
        "campaign_hash": campaign["campaign_hash"],
        "pair_space_hash": pair_summary["pair_space_hash"],
        "eligible_pair_ids_hash": pair_summary["eligible_pair_ids_hash"],
        "shard_id": shard_id,
        "shard_count": v2.PAIR_SHARD_COUNT,
        "shard_pair_ids_hash": v2.object_hash(list(pair_ids)),
        "cursor": len(completed_ids),
        "completed_pair_ids_hash": v2.object_hash(completed_ids),
        "completed_rows_hash": v2.object_hash(list(completed_rows)),
        "previous_checkpoint_hash": previous_checkpoint_hash,
        "recomputed_prefix_count": 0,
        "complete": complete,
        "external_effects": {
            "provider_calls": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "triples": 0,
        },
    }
    checkpoint["checkpoint_hash"] = v2.object_hash(checkpoint)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(v2.canonical_bytes(checkpoint) + b"\n")
    temporary.replace(path)
    return checkpoint


def mask_payload(known: int, true: int) -> tuple[str, str]:
    if true & ~known:
        raise RuntimeError("PHASE_C_V2_MASK_TRUE_NOT_SUBSET_KNOWN")
    return (
        base64.b64encode(known.to_bytes(220, "little")).decode("ascii"),
        base64.b64encode(true.to_bytes(220, "little")).decode("ascii"),
    )


def build_freeze() -> dict[str, Any]:
    source_manifest = source.verify(SOURCE_BUNDLE)
    registry = read_json(REGISTRY)
    property_contract = read_json(PROPERTY_CONTRACT)
    inputs = v2.load_feature_inputs(SOURCE_BUNDLE)
    observations = v2.build_observations(registry, inputs)
    masks, thresholds = v2.build_structural_masks(registry, inputs, observations)
    universe_hash = v2.object_hash([row.fixture_key for row in inputs.fixtures])
    tags_by_id = {str(row["tag_id"]): row for row in registry["tags"]}
    mask_records: list[dict[str, Any]] = []
    payload_records: list[dict[str, Any]] = []
    for tag_id in sorted(masks):
        known, true = masks[tag_id]
        tag = tags_by_id[tag_id]
        threshold_snapshot = dict(sorted(thresholds[tag_id].items()))
        tag_snapshot_hash = v2.object_hash(
            {
                "definition_hash": tag["definition_hash"],
                "threshold_origin": tag["threshold_origin"],
                "thresholds_by_competition": threshold_snapshot,
                "training_end_ordinal_exclusive": v2.TARGET_BLIND_TRAIN_END,
            }
        )
        mask_id = "mask:" + hashlib.sha256(
            (
                universe_hash
                + "\0"
                + tag_id
                + "\0"
                + str(tag["definition_hash"])
                + "\0"
                + tag_snapshot_hash
            ).encode("utf-8")
        ).hexdigest()
        known_base64, true_base64 = mask_payload(known, true)
        payload_records.append(
            {
                "tag_id": tag_id,
                "mask_id": mask_id,
                "known_base64_little_endian": known_base64,
                "true_base64_little_endian": true_base64,
            }
        )
        mask_records.append(
            {
                "tag_id": tag_id,
                "property_id": tag["property_id"],
                "definition_hash": tag["definition_hash"],
                "tag_snapshot_hash": tag_snapshot_hash,
                "mask_id": mask_id,
                "known_count": known.bit_count(),
                "true_count": true.bit_count(),
                "false_count": (known & ~true).bit_count(),
                "unknown_count": len(inputs.fixtures) - known.bit_count(),
                "thresholds_by_competition": threshold_snapshot,
            }
        )
    payload_descriptor = write_gzip(
        MASK_PAYLOAD,
        {
            "schema_version": "phase-c-v2-mask-payload-bundle",
            "universe_count": len(inputs.fixtures),
            "universe_hash": universe_hash,
            "bitorder": "little",
            "endianness": "little",
            "records": payload_records,
        },
    )
    manifest = {
        "schema_version": "phase-c-v2-mask-manifest",
        "generated_at": GENERATED_AT,
        "registry_hash": registry["registry_hash"],
        "property_contract_hash": property_contract["contract_hash"],
        "source_manifest_hash": source_manifest["manifest_hash"],
        "universe_count": len(inputs.fixtures),
        "universe_hash": universe_hash,
        "mask_count": len(mask_records),
        "known_true_bytes_per_mask": 440,
        "target_labels_loaded": False,
        "point_in_time_source_provenance": False,
        "payload": payload_descriptor,
        "records": mask_records,
    }
    manifest["manifest_hash"] = v2.object_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    write_json(MASK_MANIFEST, manifest, compact=True)

    census, eligible = v2.enumerate_pair_census(registry, masks)
    shard_descriptors: list[dict[str, Any]] = []
    for shard_id in range(v2.PAIR_SHARD_COUNT):
        rows = [row for row in census if row["shard_id"] == shard_id]
        shard_descriptors.append(
            write_gzip(
                FULL_ROOT / f"pair-census-shard-{shard_id:02d}-v2.json.gz",
                {
                    "schema_version": "phase-c-v2-pair-census-shard",
                    "shard_id": shard_id,
                    "shard_count": v2.PAIR_SHARD_COUNT,
                    "pair_count": len(rows),
                    "pair_ids_hash": v2.object_hash([row["pair_id"] for row in rows]),
                    "records": rows,
                },
            )
        )
    reason_counts = Counter(str(row["reason"]) for row in census)
    pair_space_hash = v2.object_hash(census)
    eligible_pair_ids_hash = v2.object_hash([row["pair_id"] for row in eligible])
    summary = {
        "schema_version": "phase-c-v2-pair-census-summary",
        "generated_at": GENERATED_AT,
        "tag_count": 150,
        "theoretical_pair_count": 11_175,
        "same_property_pair_count": 763,
        "distinct_property_pair_count": 10_412,
        "eligible_pair_count": len(eligible),
        "pruned_pair_count": 11_175 - len(eligible),
        "atomic_test_count": 300,
        "pair_test_count": 2 * len(eligible),
        "target_blind_support_slice": [303, 703],
        "target_labels_loaded": False,
        "quotas": None,
        "degree_cap": None,
        "selection_seed": None,
        "near_duplicate_policy": "JACCARD_GTE_0_98_EXPLICIT_PRUNE",
        "reason_counts": dict(sorted(reason_counts.items())),
        "pair_space_hash": pair_space_hash,
        "eligible_pair_ids_hash": eligible_pair_ids_hash,
        "shard_count": v2.PAIR_SHARD_COUNT,
        "shards": shard_descriptors,
    }
    summary["summary_hash"] = v2.object_hash(
        {key: value for key, value in summary.items() if key != "summary_hash"}
    )
    write_json(PAIR_SUMMARY, summary)
    campaign = {
        "schema_version": "phase-c-v2-exhaustive-property-campaign",
        "generated_at": GENERATED_AT,
        "property_count": 16,
        "tag_count": 150,
        "atomic_test_count": 300,
        "theoretical_pair_count": 11_175,
        "eligible_pair_count": len(eligible),
        "pair_test_count": 2 * len(eligible),
        "registry_hash": registry["registry_hash"],
        "property_contract_hash": property_contract["contract_hash"],
        "source_manifest_hash": source_manifest["manifest_hash"],
        "mask_manifest_hash": manifest["manifest_hash"],
        "pair_space_hash": pair_space_hash,
        "eligible_pair_ids_hash": eligible_pair_ids_hash,
        "folds": [
            {
                "fold_id": fold_id,
                "train_end": train_end,
                "validation_end": validation_end,
                "validation_start": validation_start,
            }
            for fold_id, train_end, validation_end, validation_start in v2.FOLDS
        ],
        "multiple_testing": {
            "atomic": "BH_GLOBAL_300_AND_PROPERTY_FAMILY_TARGET",
            "pair": f"BH_GLOBAL_{2 * len(eligible)}_AND_PROPERTY_PAIR_FAMILY_TARGET",
            "campaign": f"BH_GLOBAL_{2 * (150 + len(eligible))}",
            "blocked_tests_p_value": 1.0,
        },
        "pair_shard_count": v2.PAIR_SHARD_COUNT,
        "triple_search_locked": True,
        "max_depth": 2,
        "point_in_time_source_provenance": False,
        "proof_ceiling": "HISTORICAL_RECONSTRUCTED_ONLY",
        "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
        "roi": None,
        "profit": None,
        "clv": None,
        "drawdown": None,
        "external_effects": {
            "provider_calls": 0,
            "r2_gets": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "real_bets": 0,
            "triples": 0,
        },
    }
    campaign["campaign_hash"] = v2.object_hash(
        {key: value for key, value in campaign.items() if key != "campaign_hash"}
    )
    write_json(CAMPAIGN, campaign)
    return campaign


def verify_freeze() -> dict[str, Any]:
    source_manifest = source.verify(SOURCE_BUNDLE)
    property_contract = read_json(PROPERTY_CONTRACT)
    registry = read_json(REGISTRY)
    property_set = read_json(PROPERTY_SET)
    campaign = read_json(CAMPAIGN)
    mask_manifest = read_json(MASK_MANIFEST)
    pair_summary = read_json(PAIR_SUMMARY)

    contract_hash = verify_self_hash(
        property_contract,
        "contract_hash",
        "PHASE_C_V2_PROPERTY_CONTRACT_HASH_MISMATCH",
    )
    if property_contract.get("transform_registry_hash") != v2.object_hash(
        property_contract.get("transform_registry")
    ):
        raise RuntimeError("PHASE_C_V2_TRANSFORM_REGISTRY_HASH_MISMATCH")
    tags = registry.get("tags")
    if not isinstance(tags, list) or len(tags) != 150:
        raise RuntimeError("PHASE_C_V2_REGISTRY_TAG_COUNT_MISMATCH")
    tag_ids = [str(row["tag_id"]) for row in tags]
    if tag_ids != sorted(tag_ids) or len(set(tag_ids)) != 150:
        raise RuntimeError("PHASE_C_V2_REGISTRY_TAG_ID_MISMATCH")
    if registry.get("registry_hash") != v2.object_hash(tags):
        raise RuntimeError("PHASE_C_V2_REGISTRY_HASH_MISMATCH")
    if registry.get("source_field_registry_hash") != v2.object_hash(
        registry.get("source_field_registry")
    ):
        raise RuntimeError("PHASE_C_V2_SOURCE_FIELD_REGISTRY_HASH_MISMATCH")
    if (
        registry.get("property_contract_hash") != contract_hash
        or registry.get("transform_registry_hash")
        != property_contract.get("transform_registry_hash")
    ):
        raise RuntimeError("PHASE_C_V2_REGISTRY_CONTRACT_LINEAGE_MISMATCH")
    source_fields = registry.get("source_field_registry")
    if not isinstance(source_fields, Mapping):
        raise TypeError("PHASE_C_V2_SOURCE_FIELD_REGISTRY_REQUIRED")
    properties_by_id = {
        str(row["property_id"]): row for row in property_contract["properties"]
    }
    for tag in tags:
        if str(tag["property_id"]) not in properties_by_id:
            raise RuntimeError("PHASE_C_V2_TAG_PROPERTY_FOREIGN_KEY_MISMATCH")
        if any(str(field_id) not in source_fields for field_id in tag["source_fields"]):
            raise RuntimeError("PHASE_C_V2_TAG_SOURCE_FIELD_FOREIGN_KEY_MISMATCH")
        if int(tag.get("tag_version", 0)) == 2:
            definition = {
                key: item
                for key, item in tag.items()
                if key not in {"definition_hash", "feature_id"}
            }
            if tag.get("definition_hash") != v2.object_hash(definition):
                raise RuntimeError("PHASE_C_V2_TAG_DEFINITION_HASH_MISMATCH")
            expected_feature = "feature:" + v2.object_hash(
                {"definition_hash": tag["definition_hash"]}
            )
            if tag.get("feature_id") != expected_feature:
                raise RuntimeError("PHASE_C_V2_TAG_FEATURE_ID_MISMATCH")

    records = property_set.get("records")
    if not isinstance(records, list) or records != property_contract.get("properties"):
        raise RuntimeError("PHASE_C_V2_PROPERTY_SET_CONTRACT_MISMATCH")
    if property_set.get("property_set_hash") != v2.object_hash(records):
        raise RuntimeError("PHASE_C_V2_PROPERTY_SET_HASH_MISMATCH")
    if property_set.get("property_contract_hash") != contract_hash:
        raise RuntimeError("PHASE_C_V2_PROPERTY_SET_LINEAGE_MISMATCH")

    mask_hash = verify_self_hash(
        mask_manifest,
        "manifest_hash",
        "PHASE_C_V2_MASK_MANIFEST_HASH_MISMATCH",
    )
    pair_summary_hash = verify_self_hash(
        pair_summary,
        "summary_hash",
        "PHASE_C_V2_PAIR_SUMMARY_HASH_MISMATCH",
    )
    del pair_summary_hash
    campaign_hash = verify_self_hash(
        campaign,
        "campaign_hash",
        "PHASE_C_V2_CAMPAIGN_HASH_MISMATCH",
    )
    del campaign_hash
    expected_mask_lineage = {
        "registry_hash": registry["registry_hash"],
        "property_contract_hash": contract_hash,
        "source_manifest_hash": source_manifest["manifest_hash"],
    }
    for field, expected in expected_mask_lineage.items():
        if mask_manifest.get(field) != expected:
            raise RuntimeError(f"PHASE_C_V2_MASK_LINEAGE_MISMATCH:{field}")

    mask_records = mask_manifest.get("records")
    if not isinstance(mask_records, list) or len(mask_records) != 150:
        raise RuntimeError("PHASE_C_V2_MASK_RECORD_COUNT_MISMATCH")
    mask_ids = [str(row["tag_id"]) for row in mask_records]
    if mask_ids != tag_ids or len(set(mask_ids)) != 150:
        raise RuntimeError("PHASE_C_V2_MASK_TAG_UNION_MISMATCH")
    payload_descriptor = mask_manifest.get("payload")
    if not isinstance(payload_descriptor, Mapping):
        raise TypeError("PHASE_C_V2_MASK_PAYLOAD_DESCRIPTOR_REQUIRED")
    payload = verify_descriptor_json(ROOT, payload_descriptor)
    payload_records = payload.get("records")
    if (
        payload.get("universe_count") != mask_manifest.get("universe_count")
        or payload.get("universe_hash") != mask_manifest.get("universe_hash")
        or not isinstance(payload_records, list)
        or [str(row["tag_id"]) for row in payload_records] != tag_ids
    ):
        raise RuntimeError("PHASE_C_V2_MASK_PAYLOAD_LINEAGE_MISMATCH")
    manifest_by_tag = {str(row["tag_id"]): row for row in mask_records}
    universe_count = int(mask_manifest["universe_count"])
    universe_mask = (1 << universe_count) - 1
    for row in payload_records:
        tag_id = str(row["tag_id"])
        manifest_row = manifest_by_tag[tag_id]
        known_bytes = base64.b64decode(str(row["known_base64_little_endian"]), validate=True)
        true_bytes = base64.b64decode(str(row["true_base64_little_endian"]), validate=True)
        if len(known_bytes) != 220 or len(true_bytes) != 220:
            raise RuntimeError("PHASE_C_V2_MASK_PAYLOAD_SIZE_MISMATCH")
        known = int.from_bytes(known_bytes, "little")
        true = int.from_bytes(true_bytes, "little")
        if known & ~universe_mask or true & ~known:
            raise RuntimeError("PHASE_C_V2_MASK_PAYLOAD_INVARIANT_MISMATCH")
        expected_counts = {
            "known_count": known.bit_count(),
            "true_count": true.bit_count(),
            "false_count": (known & ~true).bit_count(),
            "unknown_count": universe_count - known.bit_count(),
            "mask_id": row["mask_id"],
        }
        if any(manifest_row.get(key) != value for key, value in expected_counts.items()):
            raise RuntimeError("PHASE_C_V2_MASK_PAYLOAD_COUNT_MISMATCH")

    shard_descriptors = pair_summary.get("shards")
    if not isinstance(shard_descriptors, list) or len(shard_descriptors) != v2.PAIR_SHARD_COUNT:
        raise RuntimeError("PHASE_C_V2_PAIR_CENSUS_SHARD_COUNT_MISMATCH")
    census: list[dict[str, Any]] = []
    seen_shards: set[int] = set()
    for descriptor in shard_descriptors:
        if not isinstance(descriptor, Mapping):
            raise TypeError("PHASE_C_V2_DURABLE_DESCRIPTOR_REQUIRED")
        shard = verify_descriptor_json(ROOT, descriptor)
        shard_id = int(shard.get("shard_id", -1))
        shard_rows = shard.get("records")
        if (
            shard_id in seen_shards
            or shard_id not in range(v2.PAIR_SHARD_COUNT)
            or shard.get("shard_count") != v2.PAIR_SHARD_COUNT
            or not isinstance(shard_rows, list)
            or shard.get("pair_count") != len(shard_rows)
            or shard.get("pair_ids_hash")
            != v2.object_hash([str(row["pair_id"]) for row in shard_rows])
            or any(int(row["shard_id"]) != shard_id for row in shard_rows)
        ):
            raise RuntimeError("PHASE_C_V2_PAIR_CENSUS_SHARD_MISMATCH")
        seen_shards.add(shard_id)
        census.extend(shard_rows)
    census.sort(key=lambda row: (str(row["parent_a"]), str(row["parent_b"])))
    pair_ids = [str(row["pair_id"]) for row in census]
    eligible_ids = [
        str(row["pair_id"]) for row in census if row["disposition"] == "ELIGIBLE"
    ]
    if len(census) != 11_175 or len(set(pair_ids)) != 11_175:
        raise RuntimeError("PHASE_C_V2_PAIR_CENSUS_UNION_MISMATCH")
    if pair_summary.get("pair_space_hash") != v2.object_hash(census):
        raise RuntimeError("PHASE_C_V2_PAIR_SPACE_HASH_MISMATCH")
    if pair_summary.get("eligible_pair_ids_hash") != v2.object_hash(eligible_ids):
        raise RuntimeError("PHASE_C_V2_ELIGIBLE_PAIR_IDS_HASH_MISMATCH")
    if pair_summary.get("eligible_pair_count") != len(eligible_ids):
        raise RuntimeError("PHASE_C_V2_ELIGIBLE_PAIR_COUNT_MISMATCH")

    expected_campaign_lineage = {
        "registry_hash": registry["registry_hash"],
        "property_contract_hash": contract_hash,
        "source_manifest_hash": source_manifest["manifest_hash"],
        "mask_manifest_hash": mask_hash,
        "pair_space_hash": pair_summary["pair_space_hash"],
        "eligible_pair_ids_hash": pair_summary["eligible_pair_ids_hash"],
        "eligible_pair_count": len(eligible_ids),
        "pair_test_count": 2 * len(eligible_ids),
    }
    for field, expected in expected_campaign_lineage.items():
        if campaign.get(field) != expected:
            raise RuntimeError(f"PHASE_C_V2_CAMPAIGN_LINEAGE_MISMATCH:{field}")
    if campaign["mask_manifest_hash"] != mask_manifest["manifest_hash"]:
        raise RuntimeError("PHASE_C_V2_MASK_MANIFEST_LINEAGE_MISMATCH")
    if campaign["pair_space_hash"] != pair_summary["pair_space_hash"]:
        raise RuntimeError("PHASE_C_V2_PAIR_SPACE_LINEAGE_MISMATCH")
    if campaign["triple_search_locked"] is not True or campaign["max_depth"] != 2:
        raise RuntimeError("PHASE_C_V2_TRIPLE_LOCK_MISMATCH")
    if (
        campaign.get("point_in_time_source_provenance") is not False
        or campaign.get("proof_ceiling") != "HISTORICAL_RECONSTRUCTED_ONLY"
        or campaign.get("price_track") != "BLOCKED_NO_POINT_IN_TIME_PRICES"
        or any(campaign.get(field) is not None for field in ("roi", "profit", "clv", "drawdown"))
        or campaign.get("external_effects")
        != {
            "provider_calls": 0,
            "r2_gets": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "real_bets": 0,
            "triples": 0,
        }
    ):
        raise RuntimeError("PHASE_C_V2_CAMPAIGN_SAFETY_CONTRACT_MISMATCH")
    return campaign


def run_atomic(work_root: Path) -> dict[str, Any]:
    registry, inputs, observations, labels, fold_states, baselines = load_context()
    for tag in registry["tags"]:
        validate_candidate_admission(admission_candidate_from_tag(tag, track="ATOMIC"))
    report = v2.evaluate_atomic(
        registry, inputs, observations, labels, fold_states, baselines
    )
    report["generated_at"] = GENERATED_AT
    report["registry_hash"] = registry["registry_hash"]
    report["campaign_hash"] = read_json(CAMPAIGN)["campaign_hash"]
    write_work_gzip(work_root / "atomic-results-raw-v2.json.gz", report)
    return report


def validate_resume_checkpoint(
    checkpoint_path: Path,
    progress_path: Path,
    shard_id: int,
    pair_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], str | None]:
    rows = jsonl_rows(progress_path)
    if not checkpoint_path.exists():
        if rows:
            raise RuntimeError("PHASE_C_V2_PROGRESS_WITHOUT_CHECKPOINT")
        return [], None
    checkpoint = read_json(checkpoint_path)
    stored_hash = str(checkpoint.get("checkpoint_hash"))
    computed_hash = v2.object_hash(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_hash"}
    )
    if stored_hash != computed_hash:
        raise RuntimeError("PHASE_C_V2_CHECKPOINT_HASH_MISMATCH")
    campaign = read_json(CAMPAIGN)
    pair_summary = read_json(PAIR_SUMMARY)
    checkpoint_cursor = int(checkpoint.get("cursor", -1))
    if len(rows) < checkpoint_cursor:
        raise RuntimeError("PHASE_C_V2_PROGRESS_SHORTER_THAN_COMMITTED_CHECKPOINT")
    if len(rows) > checkpoint_cursor:
        # A hard process kill can occur after the append-only progress write but
        # before the atomic checkpoint replace.  That tail was never committed;
        # discard it and resume from the last hash-bound checkpoint.  No
        # completed prefix row is recalculated.
        rows = rows[:checkpoint_cursor]
        progress_path.write_bytes(
            b"".join(v2.canonical_bytes(row) + b"\n" for row in rows)
        )
    required = {
        "campaign_hash": campaign["campaign_hash"],
        "pair_space_hash": pair_summary["pair_space_hash"],
        "eligible_pair_ids_hash": pair_summary["eligible_pair_ids_hash"],
        "shard_id": shard_id,
        "shard_count": v2.PAIR_SHARD_COUNT,
        "shard_pair_ids_hash": v2.object_hash(list(pair_ids)),
        "cursor": checkpoint_cursor,
        "completed_pair_ids_hash": v2.object_hash(
            [str(row["pair_id"]) for row in rows]
        ),
        "completed_rows_hash": v2.object_hash(rows),
        "recomputed_prefix_count": 0,
    }
    for key, expected in required.items():
        if checkpoint.get(key) != expected:
            raise RuntimeError(f"PHASE_C_V2_RESUME_LINEAGE_MISMATCH:{key}")
    if [str(row["pair_id"]) for row in rows] != list(pair_ids[: len(rows)]):
        raise RuntimeError("PHASE_C_V2_RESUME_CURSOR_OR_ORDER_MISMATCH")
    return rows, stored_hash


def run_pair_shard(
    work_root: Path,
    shard_id: int,
    *,
    stop_after: int | None = None,
    soft_deadline_seconds: int | None = None,
    context: tuple[
        dict[str, Any],
        v2.FeatureInputs,
        dict[str, tuple[v2.Observation, ...]],
        tuple[dict[str, str], ...],
        dict[str, tuple[v2.FoldTagState, ...]],
        dict[str, tuple[dict[str, Any], ...]],
    ]
    | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    pairs = eligible_pairs_for_shard(shard_id)
    pair_ids = [str(row["pair_id"]) for row in pairs]
    shard_root = work_root / f"pair-shard-{shard_id:02d}"
    progress_path = shard_root / "progress-v2.jsonl"
    checkpoint_path = shard_root / "checkpoint-v2.json"
    completed, previous_checkpoint_hash = validate_resume_checkpoint(
        checkpoint_path, progress_path, shard_id, pair_ids
    )
    if completed and len(completed) == len(pairs):
        return {
            "shard_id": shard_id,
            "pair_count": len(completed),
            "complete": True,
            "resumed_from": len(completed),
            "recomputed_prefix_count": 0,
            "results_hash": v2.object_hash(completed),
        }
    resumed_from = len(completed)
    if context is None:
        context = load_context()
    registry, inputs, _observations, labels, fold_states, baselines = context
    registry_by_id = {str(row["tag_id"]): row for row in registry["tags"]}
    mask_manifest = read_json(MASK_MANIFEST)
    mask_records = {
        str(row["tag_id"]): row for row in mask_manifest["records"]
    }
    for pair in pairs[len(completed) :]:
        if soft_deadline_seconds is not None and (
            time.monotonic() - started >= soft_deadline_seconds
        ):
            write_checkpoint(
                checkpoint_path,
                shard_id=shard_id,
                pair_ids=pair_ids,
                completed_rows=completed,
                previous_checkpoint_hash=previous_checkpoint_hash,
                complete=False,
            )
            break
        for parent_key in ("parent_a", "parent_b"):
            validate_candidate_admission(
                admission_candidate_from_tag(
                    registry_by_id[str(pair[parent_key])], track="PAIR"
                )
            )
        row = v2.evaluate_pair_raw(
            pair,
            registry_by_id,
            inputs,
            labels,
            fold_states,
            baselines,
            mask_records,
        )
        completed.append(row)
        append_jsonl(progress_path, row)
        checkpoint = write_checkpoint(
            checkpoint_path,
            shard_id=shard_id,
            pair_ids=pair_ids,
            completed_rows=completed,
            previous_checkpoint_hash=previous_checkpoint_hash,
            complete=len(completed) == len(pairs),
        )
        previous_checkpoint_hash = str(checkpoint["checkpoint_hash"])
        if stop_after is not None and len(completed) >= stop_after:
            break
    complete = len(completed) == len(pairs)
    return {
        "shard_id": shard_id,
        "pair_count": len(completed),
        "expected_pair_count": len(pairs),
        "complete": complete,
        "resumed_from": resumed_from,
        "recomputed_prefix_count": 0,
        "results_hash": v2.object_hash(completed),
    }


def run_all_pair_shards(
    work_root: Path, *, soft_deadline_seconds: int | None = None
) -> list[dict[str, Any]]:
    context = load_context()
    receipts: list[dict[str, Any]] = []
    for shard_id in range(v2.PAIR_SHARD_COUNT):
        receipt = run_pair_shard(
            work_root,
            shard_id,
            soft_deadline_seconds=soft_deadline_seconds,
            context=context,
        )
        receipts.append(receipt)
        if receipt["complete"] is not True:
            break
    return receipts


def load_complete_pair_rows(work_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for shard_id in range(v2.PAIR_SHARD_COUNT):
        pairs = eligible_pairs_for_shard(shard_id)
        pair_ids = [str(row["pair_id"]) for row in pairs]
        shard_root = work_root / f"pair-shard-{shard_id:02d}"
        progress_path = shard_root / "progress-v2.jsonl"
        checkpoint_path = shard_root / "checkpoint-v2.json"
        shard_rows, _ = validate_resume_checkpoint(
            checkpoint_path, progress_path, shard_id, pair_ids
        )
        if len(shard_rows) != len(pair_ids):
            raise RuntimeError(f"PHASE_C_V2_INCOMPLETE_SHARD:{shard_id}")
        for row in shard_rows:
            pair_id = str(row["pair_id"])
            if pair_id in seen:
                raise RuntimeError(f"PHASE_C_V2_DUPLICATE_PAIR_RESULT:{pair_id}")
            seen.add(pair_id)
            rows.append(row)
    summary = read_json(PAIR_SUMMARY)
    expected = int(summary["eligible_pair_count"])
    if len(rows) != expected:
        raise RuntimeError(
            f"PHASE_C_V2_PAIR_RESULT_CARDINALITY_MISMATCH:{len(rows)}:{expected}"
        )
    expected_ids = sorted(
        str(row["pair_id"])
        for shard_id in range(v2.PAIR_SHARD_COUNT)
        for row in eligible_pairs_for_shard(shard_id)
    )
    if sorted(seen) != expected_ids:
        raise RuntimeError("PHASE_C_V2_PAIR_RESULT_UNION_MISMATCH")
    return rows


def deterministic_control_states(
    inputs: v2.FeatureInputs, control_id: str, salt: str
) -> tuple[bool | None, ...]:
    states: list[bool | None] = []
    for fixture in inputs.fixtures:
        token = hashlib.sha256(
            (control_id + "\0" + salt + "\0" + fixture.fixture_key).encode("utf-8")
        ).digest()
        if control_id == "ALWAYS_TRUE":
            states.append(True)
        elif control_id == "IMPOSSIBLE_FALSE":
            states.append(False)
        elif control_id == "RANDOM_PREVALENCE_UNKNOWN":
            states.append(None if token[0] % 5 == 0 else token[1] % 3 == 0)
        elif control_id == "SHUFFLED_LEAGUE_MONTH":
            month_key = fixture.kickoff.strftime("%Y-%m")
            group_token = hashlib.sha256(
                (
                    control_id
                    + "\0"
                    + salt
                    + "\0"
                    + fixture.competition_key
                    + "\0"
                    + month_key
                    + "\0"
                    + fixture.fixture_key
                ).encode("utf-8")
            ).digest()
            states.append(group_token[0] % 3 == 0)
        else:
            raise KeyError(control_id)
    return tuple(states)


def evaluate_modeled_control(
    control_id: str,
    track: str,
    inputs: v2.FeatureInputs,
    labels: Sequence[Mapping[str, str]],
    baselines: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    states_a = deterministic_control_states(inputs, control_id, "A")
    states_b = deterministic_control_states(inputs, control_id, "B")
    rows: list[dict[str, Any]] = []
    for target in v2.TARGET_SPECS:
        target_labels = [row[target.label_key] for row in labels]
        differences: dict[str, list[float]] = {
            name: []
            for name in (
                ("BASE",) if track == "ATOMIC" else v2.PAIR_COMPARATORS
            )
        }
        brier_differences: dict[str, list[float]] = {
            name: [] for name in differences
        }
        dates: list[str] = []
        true_count = 0
        known_count = 0
        fold_true_counts: list[int] = []
        for fold_index, (_fold_id, train_end, validation_end, _) in enumerate(v2.FOLDS):
            baseline = baselines[target.target_id][fold_index]
            train_indices = tuple(range(train_end))
            validation_indices = tuple(range(train_end, validation_end))
            global_probs = baseline["global_probs"]
            if track == "ATOMIC":
                conditional = v2.conditional_probs(
                    train_indices,
                    target_labels,
                    states_a,
                    target.categories,
                    global_probs,
                )
            else:
                pair_states = tuple(
                    None if left is None or right is None else left and right
                    for left, right in zip(states_a, states_b, strict=True)
                )
                conditional_pair = v2.conditional_probs(
                    train_indices,
                    target_labels,
                    pair_states,
                    target.categories,
                    global_probs,
                )
                conditional_a = v2.conditional_probs(
                    train_indices,
                    target_labels,
                    states_a,
                    target.categories,
                    global_probs,
                )
                conditional_b = v2.conditional_probs(
                    train_indices,
                    target_labels,
                    states_b,
                    target.categories,
                    global_probs,
                )
            fold_true = 0
            for index in validation_indices:
                base = baseline["simple"][index]
                label = target_labels[index]
                if track == "ATOMIC":
                    state = states_a[index]
                    if state is None:
                        continue
                    model = v2.adjusted_probs(
                        base, conditional[state], global_probs, target.categories
                    )
                    differences["BASE"].append(
                        v2.log_loss(base, label) - v2.log_loss(model, label)
                    )
                    brier_differences["BASE"].append(
                        v2.brier_loss(base, label, target.categories)
                        - v2.brier_loss(model, label, target.categories)
                    )
                else:
                    state_a, state_b = states_a[index], states_b[index]
                    state_pair = pair_states[index]
                    if state_a is None or state_b is None or state_pair is None:
                        continue
                    model = v2.adjusted_probs(
                        base,
                        conditional_pair[state_pair],
                        global_probs,
                        target.categories,
                    )
                    comparator_predictions = {
                        "PARENT_A": v2.adjusted_probs(
                            base,
                            conditional_a[state_a],
                            global_probs,
                            target.categories,
                        ),
                        "PARENT_B": v2.adjusted_probs(
                            base,
                            conditional_b[state_b],
                            global_probs,
                            target.categories,
                        ),
                        "ADDITIVE": v2.combine_adjustments(
                            base,
                            conditional_a[state_a],
                            conditional_b[state_b],
                            global_probs,
                            target.categories,
                        ),
                    }
                    for name, prediction in comparator_predictions.items():
                        differences[name].append(
                            v2.log_loss(prediction, label) - v2.log_loss(model, label)
                        )
                        brier_differences[name].append(
                            v2.brier_loss(prediction, label, target.categories)
                            - v2.brier_loss(model, label, target.categories)
                        )
                    state = state_pair
                dates.append(inputs.fixtures[index].kickoff.date().isoformat())
                known_count += 1
                if state:
                    true_count += 1
                    fold_true += 1
            fold_true_counts.append(fold_true)
        p_values = {
            name: v2.one_sided_cluster_p(values, dates)[0]
            for name, values in differences.items()
        }
        p_value_raw = max(p_values.values())
        support_gate = (
            true_count >= 80
            and known_count / v2.OOF_COUNT >= 0.8
            and all(value >= 15 for value in fold_true_counts)
        )
        rows.append(
            {
                "control_id": control_id,
                "track": track,
                "target_id": target.target_id,
                "execution": "MODELED_FIVE_FOLD_OOF",
                "known_oof": known_count,
                "true_oof": true_count,
                "fold_true_counts": fold_true_counts,
                "p_values_raw": p_values,
                "p_value_raw": p_value_raw,
                "p_value": p_value_raw if support_gate else 1.0,
                "delta_log_loss": {
                    name: round(v2.arithmetic_mean(values) or 0, 8)
                    for name, values in differences.items()
                },
                "delta_brier": {
                    name: round(v2.arithmetic_mean(values) or 0, 8)
                    for name, values in brier_differences.items()
                },
                "support_gate": support_gate,
            }
        )
    return rows


def build_negative_controls(
    inputs: v2.FeatureInputs,
    labels: Sequence[Mapping[str, str]],
    baselines: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    guards = (
        ("FUTURE_FEATURE", "REJECTED_FUTURE_OR_EQUAL_CUTOFF"),
        ("SHIFTED_PRICE", "REJECTED_NO_POINT_IN_TIME_PRICES"),
        ("POST_RESULT_FIELD", "REJECTED_TARGET_FIXTURE_POST_RESULT"),
        ("WINNER_LOSER_IDENTITY", "REJECTED_TARGET_DERIVED_IDENTITY"),
    )
    modeled_ids = (
        "SHUFFLED_LEAGUE_MONTH",
        "RANDOM_PREVALENCE_UNKNOWN",
        "IMPOSSIBLE_FALSE",
        "ALWAYS_TRUE",
    )
    modeled_rows = [
        row
        for control_id in modeled_ids
        for track in ("ATOMIC", "PAIR")
        for row in evaluate_modeled_control(
            control_id, track, inputs, labels, baselines
        )
    ]
    q_values = v2.bh_adjust(
        [
            (
                f"{row['control_id']}|{row['track']}|{row['target_id']}",
                float(row["p_value"]),
            )
            for row in modeled_rows
        ]
    )
    surviving = 0
    for row in modeled_rows:
        key = f"{row['control_id']}|{row['track']}|{row['target_id']}"
        row["q_value"] = q_values[key]
        minimum_log_loss = min(float(value) for value in row["delta_log_loss"].values())
        minimum_brier = min(float(value) for value in row["delta_brier"].values())
        survived = (
            float(row["q_value"]) <= 0.05
            and bool(row["support_gate"])
            and minimum_log_loss >= 0.005
            and minimum_brier >= 0.002
        )
        row["status"] = (
            "NEGATIVE_CONTROL_SURVIVED_UNEXPECTEDLY" if survived else "REJECTED"
        )
        surviving += int(survived)
    if surviving:
        raise RuntimeError(f"PHASE_C_V2_NEGATIVE_CONTROL_SURVIVED:{surviving}")
    return {
        "schema_version": "phase-c-v2-negative-controls",
        "control_count": 8,
        "guard_control_count": 4,
        "modeled_control_count": 4,
        "modeled_track_target_test_count": len(modeled_rows),
        "guard_records": [
            {
                "control_id": control_id,
                "atomic_status": status,
                "pair_status": status,
                "modeled": False,
            }
            for control_id, status in guards
        ],
        "modeled_records": modeled_rows,
        "surviving_control_count": 0,
        "negative_control_gate": "PASS",
    }


GUARD_REJECTION_REASONS = {
    "FUTURE_FEATURE": "REJECTED_FUTURE_OR_EQUAL_CUTOFF",
    "SHIFTED_PRICE": "REJECTED_NO_POINT_IN_TIME_PRICES",
    "POST_RESULT_FIELD": "REJECTED_TARGET_FIXTURE_POST_RESULT",
    "WINNER_LOSER_IDENTITY": "REJECTED_TARGET_DERIVED_IDENTITY",
}


def admission_candidate_from_tag(
    tag: Mapping[str, Any], *, track: str
) -> dict[str, Any]:
    """Build the common admission envelope used before atomic and pair evaluation."""
    availability_relation = "UNVERIFIED_TEMPORAL_CONTRACT"
    if (
        tag.get("cutoff") == "TARGET_KICKOFF_EXCLUSIVE_WITH_PT6H_SOURCE_EMBARGO"
        and tag.get("temporal_class") == "LAGGED_RECONSTRUCTED_ONLY"
    ):
        availability_relation = "STRICTLY_BEFORE_TARGET_KICKOFF"
    return {
        "candidate_id": str(tag["tag_id"]),
        "track": track,
        "availability_relation": availability_relation,
        "scientific_role": str(tag["scientific_role"]),
        "requires_point_in_time_price": False,
        "point_in_time_price_provenance": False,
    }


def validate_candidate_admission(candidate: Mapping[str, Any]) -> None:
    """Reject leakage and unavailable-price candidates at the shared entry gate."""
    if candidate.get("track") not in {"ATOMIC", "PAIR"}:
        raise RuntimeError("PHASE_C_V2_CANDIDATE_TRACK_INVALID")
    if candidate.get("availability_relation") != "STRICTLY_BEFORE_TARGET_KICKOFF":
        raise RuntimeError("REJECTED_FUTURE_OR_EQUAL_CUTOFF")
    if candidate.get("requires_point_in_time_price") is True and candidate.get(
        "point_in_time_price_provenance"
    ) is not True:
        raise RuntimeError("REJECTED_NO_POINT_IN_TIME_PRICES")
    if candidate.get("scientific_role") == "TARGET_ONLY_POST_RESULT":
        raise RuntimeError("REJECTED_TARGET_FIXTURE_POST_RESULT")
    if candidate.get("scientific_role") == "TARGET_DERIVED_IDENTITY":
        raise RuntimeError("REJECTED_TARGET_DERIVED_IDENTITY")
    if candidate.get("scientific_role") != "FOOTBALL_PREDICTOR":
        raise RuntimeError("PHASE_C_V2_CANDIDATE_SCIENTIFIC_ROLE_INVALID")


def injected_guard_candidate(control_id: str, track: str) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "candidate_id": f"NEGATIVE_CONTROL:{control_id}:{track}",
        "track": track,
        "availability_relation": "STRICTLY_BEFORE_TARGET_KICKOFF",
        "scientific_role": "FOOTBALL_PREDICTOR",
        "requires_point_in_time_price": False,
        "point_in_time_price_provenance": False,
    }
    if control_id == "FUTURE_FEATURE":
        candidate["availability_relation"] = "AT_OR_AFTER_TARGET_KICKOFF"
    elif control_id == "SHIFTED_PRICE":
        candidate["requires_point_in_time_price"] = True
    elif control_id == "POST_RESULT_FIELD":
        candidate["scientific_role"] = "TARGET_ONLY_POST_RESULT"
    elif control_id == "WINNER_LOSER_IDENTITY":
        candidate["scientific_role"] = "TARGET_DERIVED_IDENTITY"
    else:
        raise ValueError(f"PHASE_C_V2_GUARD_CONTROL_UNKNOWN:{control_id}")
    return candidate


def build_negative_guard_execution_proof() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for control_id, expected_reason in GUARD_REJECTION_REASONS.items():
        for track in ("ATOMIC", "PAIR"):
            candidate = injected_guard_candidate(control_id, track)
            rejected = False
            rejection_reason: str | None = None
            try:
                validate_candidate_admission(candidate)
            except RuntimeError as error:
                rejected = True
                rejection_reason = str(error)
            if not rejected or rejection_reason != expected_reason:
                raise RuntimeError(
                    f"PHASE_C_V2_GUARD_CONTROL_NOT_REJECTED:{control_id}:{track}"
                )
            records.append(
                {
                    "control_id": control_id,
                    "track": track,
                    "input_hash": v2.object_hash(candidate),
                    "execution": "INJECTED_SHARED_CANDIDATE_ADMISSION_GATE",
                    "rejection_stage": "CANDIDATE_ADMISSION",
                    "rejection_reason": rejection_reason,
                    "status": "REJECTED",
                }
            )
    proof: dict[str, Any] = {
        "schema_version": "phase-c-v2-negative-control-guard-execution",
        "generated_at": GENERATED_AT,
        "guard_control_count": len(GUARD_REJECTION_REASONS),
        "executed_guard_control_count": len(
            {str(row["control_id"]) for row in records}
        ),
        "executed_guard_track_count": len(records),
        "records": records,
        "negative_control_guard_gate": "PASS",
        "external_effects": {
            "provider_calls": 0,
            "odds_credits": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "triples": 0,
        },
    }
    proof["proof_hash"] = v2.object_hash(proof)
    return proof


def verify_negative_guard_execution_proof() -> dict[str, Any]:
    proof = read_json(NEGATIVE_GUARD_PROOF)
    verify_self_hash(
        proof,
        "proof_hash",
        "PHASE_C_V2_NEGATIVE_GUARD_PROOF_HASH_MISMATCH",
    )
    expected = build_negative_guard_execution_proof()
    if proof != expected:
        raise RuntimeError("PHASE_C_V2_NEGATIVE_GUARD_EXECUTION_MISMATCH")
    return proof


def _atomic_compact(report: Mapping[str, Any], descriptors: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for row in report["results"]:
        metrics = {
            target_id: {
                key: metric[key]
                for key in (
                    "known_oof",
                    "true_oof",
                    "false_oof",
                    "unknown_oof",
                    "coverage_oof",
                    "delta_log_loss",
                    "delta_brier",
                    "p_value",
                    "q_value_atomic_global",
                    "q_value_family",
                    "q_value_campaign_global",
                    "q_value",
                    "status",
                    "review_gate",
                    "hypothesis_id",
                )
            }
            for target_id, metric in row["target_metrics"].items()
        }
        records.append(
            {
                "property_id": row["property_id"],
                "tag_id": row["tag_id"],
                "status": row["status"],
                "target_metrics": metrics,
            }
        )
    return {
        "schema_version": "phase-c-v2-atomic-results-summary",
        "generated_at": GENERATED_AT,
        "track": report["track"],
        "point_in_time_source_provenance": False,
        "tag_count": report["tag_count"],
        "property_count": report["property_count"],
        "canonical_test_count": report["canonical_test_count"],
        "status_counts": report["status_counts"],
        "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
        "roi": None,
        "profit": None,
        "clv": None,
        "drawdown": None,
        "full_result_shards": list(descriptors),
        "records": records,
    }


def _pair_compact(report: Mapping[str, Any], descriptors: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(report["results"])
    surviving = [row for row in rows if str(row["status"]).startswith("SURVIVED_")]
    ranked = sorted(
        rows,
        key=lambda row: (
            min(float(metric["q_value"]) for metric in row["target_metrics"].values()),
            str(row["pair_id"]),
        ),
    )[:50]
    review_ids = {str(row["pair_id"]) for row in (*surviving, *ranked)}
    compact_rows = [
        {
            "pair_id": row["pair_id"],
            "parent_a": row["parent_a"],
            "parent_b": row["parent_b"],
            "status": row["status"],
            "target_metrics": {
                target_id: {
                    key: metric[key]
                    for key in (
                        "known_oof",
                        "true_oof",
                        "unknown_oof",
                        "coverage_oof",
                        "delta_log_loss_by_comparator",
                        "delta_brier_by_comparator",
                        "p_value_raw_intersection_union",
                        "p_value",
                        "q_value_pair_global",
                        "q_value_family",
                        "q_value_campaign_global",
                        "q_value",
                        "status",
                        "review_gate",
                        "pair_snapshot_hash",
                        "hypothesis_id",
                    )
                }
                for target_id, metric in row["target_metrics"].items()
            },
        }
        for row in rows
        if str(row["pair_id"]) in review_ids
    ]
    return {
        "schema_version": "phase-c-v2-pair-results-summary",
        "generated_at": GENERATED_AT,
        "verdict": report["verdict"],
        "pair_count": report["pair_count"],
        "canonical_test_count": report["canonical_test_count"],
        "campaign_test_count": report["campaign_test_count"],
        "status_counts": report["status_counts"],
        "surviving_test_count": report["surviving_test_count"],
        "review_queue_pair_count": len(compact_rows),
        "triple_search_locked": True,
        "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
        "roi": None,
        "profit": None,
        "clv": None,
        "drawdown": None,
        "full_result_shards": list(descriptors),
        "review_queue": compact_rows,
    }


def reduce_campaign(work_root: Path, output_base: Path = ROOT) -> dict[str, Any]:
    atomic_path = work_root / "atomic-results-raw-v2.json.gz"
    if not atomic_path.exists():
        raise RuntimeError("PHASE_C_V2_ATOMIC_RAW_RESULTS_MISSING")
    atomic_report = read_gzip_json(atomic_path)
    pair_rows = load_complete_pair_rows(work_root)
    pair_report, multiplicity = v2.finalize_pair_results(pair_rows, atomic_report)
    registry, inputs, observations, labels, fold_states, baselines = load_context()
    del registry, observations, fold_states
    controls = build_negative_controls(inputs, labels, baselines)
    descriptors: list[dict[str, Any]] = []
    atomic_descriptors: list[dict[str, Any]] = []
    atomic_rows = list(atomic_report["results"])
    for shard_id in range(16):
        shard_rows = [
            row for index, row in enumerate(atomic_rows) if index % 16 == shard_id
        ]
        descriptor = write_gzip_under(
            output_base,
            f"reports/hypothesis-research/v2/full/atomic-results-shard-{shard_id:02d}-v2.json.gz",
            {
                "schema_version": "phase-c-v2-atomic-result-shard",
                "shard_id": shard_id,
                "shard_count": 16,
                "record_count": len(shard_rows),
                "record_ids_hash": v2.object_hash(
                    [str(row["tag_id"]) for row in shard_rows]
                ),
                "records": shard_rows,
            },
        )
        atomic_descriptors.append(descriptor)
        descriptors.append(descriptor)
    pair_descriptors: list[dict[str, Any]] = []
    for shard_id in range(v2.PAIR_SHARD_COUNT):
        shard_rows = [
            row for row in pair_report["results"] if int(row["shard_id"]) == shard_id
        ]
        descriptor = write_gzip_under(
            output_base,
            f"reports/hypothesis-research/v2/full/pair-results-shard-{shard_id:02d}-v2.json.gz",
            {
                "schema_version": "phase-c-v2-pair-result-shard",
                "shard_id": shard_id,
                "shard_count": v2.PAIR_SHARD_COUNT,
                "record_count": len(shard_rows),
                "record_ids_hash": v2.object_hash(
                    [str(row["pair_id"]) for row in shard_rows]
                ),
                "records": shard_rows,
            },
        )
        pair_descriptors.append(descriptor)
        descriptors.append(descriptor)
    oversized = [
        (descriptor["path"], descriptor["bytes"])
        for descriptor in descriptors
        if int(descriptor["bytes"]) > 300_000
    ]
    if oversized:
        raise RuntimeError(f"PHASE_C_V2_DURABLE_BLOB_TOO_LARGE:{oversized}")
    atomic_compact = _atomic_compact(atomic_report, atomic_descriptors)
    pair_compact = _pair_compact(pair_report, pair_descriptors)
    compact_descriptors = [
        write_json_under(
            output_base,
            "reports/hypothesis-research/v2/atomic-results-summary-v2.json",
            atomic_compact,
        ),
        write_json_under(
            output_base,
            "reports/hypothesis-research/v2/pair-results-summary-v2.json",
            pair_compact,
        ),
        write_json_under(
            output_base,
            "reports/hypothesis-research/v2/campaign-multiplicity-v2.json",
            multiplicity,
        ),
        write_json_under(
            output_base,
            "reports/hypothesis-research/v2/negative-controls-v2.json",
            controls,
        ),
    ]
    for descriptor in compact_descriptors:
        if int(descriptor["bytes"]) > 300_000:
            raise RuntimeError(
                f"PHASE_C_V2_COMPACT_REPORT_TOO_LARGE:{descriptor['path']}:{descriptor['bytes']}"
            )
    dashboard = {
        "schema_version": "phase-c-v2-dashboard-data-contract",
        "generated_at": GENERATED_AT,
        "data_only": True,
        "source_reports": [
            descriptor["path"] for descriptor in compact_descriptors
        ],
        "allowed_fields": [
            "counts",
            "coverage",
            "status",
            "q_value",
            "historical_delta_log_loss",
            "historical_delta_brier",
            "replay",
            "checkpoint",
        ],
        "forbidden_fields": [
            "stake",
            "bet",
            "odds",
            "roi",
            "profit",
            "clv",
            "drawdown",
            "promotion",
        ],
        "point_in_time_price_provenance": False,
        "triple_search_locked": True,
    }
    dashboard_descriptor = write_json_under(
        output_base,
        "reports/hypothesis-research/v2/dashboard-data-contract-v2.json",
        dashboard,
    )
    result_manifest: dict[str, Any] = {
        "schema_version": "phase-c-v2-full-results-manifest",
        "generated_at": GENERATED_AT,
        "campaign_hash": read_json(CAMPAIGN)["campaign_hash"],
        "eligible_pair_count": len(pair_rows),
        "atomic_test_count": 300,
        "pair_test_count": 2 * len(pair_rows),
        "campaign_test_count": 300 + 2 * len(pair_rows),
        "atomic_shard_count": 16,
        "pair_shard_count": v2.PAIR_SHARD_COUNT,
        "durability": "GIT_FULL_SANITIZED_EVIDENCE",
        "canonical_identity": "DECOMPRESSED_CONTENT_SHA256",
        "transport_identity": "RUNTIME_BOUND_GZIP_SHA256",
        "files": [*descriptors, *compact_descriptors, dashboard_descriptor],
    }
    result_manifest["manifest_hash"] = v2.object_hash(result_manifest)
    manifest_descriptor = write_json_under(
        output_base,
        "reports/hypothesis-research/v2/full-results-manifest-v2.json",
        result_manifest,
        compact=True,
    )
    return {
        "atomic_report": atomic_report,
        "pair_report": pair_report,
        "multiplicity": multiplicity,
        "controls": controls,
        "manifest": result_manifest,
        "manifest_descriptor": manifest_descriptor,
    }


def verify_results(output_base: Path = ROOT) -> dict[str, Any]:
    campaign = verify_freeze()
    registry = read_json(REGISTRY)
    manifest = read_json(
        output_base / "reports/hypothesis-research/v2/full-results-manifest-v2.json"
    )
    stored_manifest_hash = str(manifest.get("manifest_hash"))
    computed_manifest_hash = v2.object_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    if stored_manifest_hash != computed_manifest_hash:
        raise RuntimeError("PHASE_C_V2_RESULT_MANIFEST_HASH_MISMATCH")
    if manifest.get("campaign_hash") != campaign["campaign_hash"]:
        raise RuntimeError("PHASE_C_V2_RESULT_CAMPAIGN_LINEAGE_MISMATCH")
    expected_paths = {
        *{
            f"reports/hypothesis-research/v2/full/atomic-results-shard-{shard_id:02d}-v2.json.gz"
            for shard_id in range(16)
        },
        *{
            f"reports/hypothesis-research/v2/full/pair-results-shard-{shard_id:02d}-v2.json.gz"
            for shard_id in range(v2.PAIR_SHARD_COUNT)
        },
        "reports/hypothesis-research/v2/atomic-results-summary-v2.json",
        "reports/hypothesis-research/v2/pair-results-summary-v2.json",
        "reports/hypothesis-research/v2/campaign-multiplicity-v2.json",
        "reports/hypothesis-research/v2/negative-controls-v2.json",
        "reports/hypothesis-research/v2/dashboard-data-contract-v2.json",
    }
    descriptors = manifest.get("files")
    if not isinstance(descriptors, list):
        raise TypeError("PHASE_C_V2_RESULT_DESCRIPTORS_REQUIRED")
    descriptor_paths = [str(row["path"]) for row in descriptors]
    if len(descriptor_paths) != len(set(descriptor_paths)) or set(descriptor_paths) != expected_paths:
        raise RuntimeError("PHASE_C_V2_RESULT_FILE_SET_MISMATCH")
    if (
        manifest.get("atomic_shard_count") != 16
        or manifest.get("pair_shard_count") != v2.PAIR_SHARD_COUNT
        or manifest.get("eligible_pair_count") != campaign["eligible_pair_count"]
        or manifest.get("atomic_test_count") != 300
        or manifest.get("pair_test_count") != campaign["pair_test_count"]
    ):
        raise RuntimeError("PHASE_C_V2_RESULT_DENOMINATOR_LINEAGE_MISMATCH")

    expected_atomic_ids_by_shard = {
        shard_id: [
            str(row["tag_id"])
            for index, row in enumerate(registry["tags"])
            if index % 16 == shard_id
        ]
        for shard_id in range(16)
    }
    expected_pair_ids_by_shard = {
        shard_id: [
            str(row["pair_id"]) for row in eligible_pairs_for_shard(shard_id)
        ]
        for shard_id in range(v2.PAIR_SHARD_COUNT)
    }
    atomic_count = 0
    pair_count = 0
    atomic_ids: set[str] = set()
    pair_ids: set[str] = set()
    seen_atomic_shards: set[int] = set()
    seen_pair_shards: set[int] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            raise TypeError("PHASE_C_V2_RESULT_DESCRIPTOR_REQUIRED")
        path = descriptor_path(output_base, descriptor)
        payload = path.read_bytes()
        if (
            len(payload) != int(descriptor["bytes"])
            or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]
        ):
            raise RuntimeError(f"PHASE_C_V2_RESULT_TRANSPORT_MISMATCH:{path}")
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as stream:
                content = stream.read()
            if hashlib.sha256(content).hexdigest() != descriptor["content_sha256"]:
                raise RuntimeError(f"PHASE_C_V2_RESULT_CONTENT_MISMATCH:{path}")
            value = json.loads(content)
            if not isinstance(value, dict):
                raise TypeError("PHASE_C_V2_RESULT_SHARD_OBJECT_REQUIRED")
            records = value.get("records", [])
            if "atomic-results-shard" in path.name:
                shard_id = int(value.get("shard_id", -1))
                row_ids = [str(row["tag_id"]) for row in records]
                if (
                    shard_id in seen_atomic_shards
                    or shard_id not in range(16)
                    or value.get("shard_count") != 16
                    or value.get("record_count") != len(records)
                    or value.get("record_ids_hash") != v2.object_hash(row_ids)
                    or row_ids != expected_atomic_ids_by_shard[shard_id]
                ):
                    raise RuntimeError("PHASE_C_V2_ATOMIC_RESULT_SHARD_MISMATCH")
                seen_atomic_shards.add(shard_id)
                atomic_count += len(records)
                for row in records:
                    tag_id = str(row["tag_id"])
                    if tag_id in atomic_ids:
                        raise RuntimeError(f"PHASE_C_V2_DUPLICATE_ATOMIC_RESULT:{tag_id}")
                    atomic_ids.add(tag_id)
            elif "pair-results-shard" in path.name:
                shard_id = int(value.get("shard_id", -1))
                row_ids = [str(row["pair_id"]) for row in records]
                if (
                    shard_id in seen_pair_shards
                    or shard_id not in range(v2.PAIR_SHARD_COUNT)
                    or value.get("shard_count") != v2.PAIR_SHARD_COUNT
                    or value.get("record_count") != len(records)
                    or value.get("record_ids_hash") != v2.object_hash(row_ids)
                    or row_ids != expected_pair_ids_by_shard[shard_id]
                    or any(int(row["shard_id"]) != shard_id for row in records)
                ):
                    raise RuntimeError("PHASE_C_V2_PAIR_RESULT_SHARD_MISMATCH")
                seen_pair_shards.add(shard_id)
                pair_count += len(records)
                for row in records:
                    pair_id = str(row["pair_id"])
                    if pair_id in pair_ids:
                        raise RuntimeError(f"PHASE_C_V2_DUPLICATE_PAIR_RESULT:{pair_id}")
                    pair_ids.add(pair_id)
        else:
            value = json.loads(payload)
            if descriptor.get("content_sha256") != v2.object_hash(value):
                raise RuntimeError(f"PHASE_C_V2_RESULT_CONTENT_MISMATCH:{path}")
    if atomic_count != 150 or len(atomic_ids) != 150:
        raise RuntimeError("PHASE_C_V2_ATOMIC_RESULT_UNION_MISMATCH")
    if pair_count != int(manifest["eligible_pair_count"]) or len(pair_ids) != pair_count:
        raise RuntimeError("PHASE_C_V2_PAIR_RESULT_UNION_MISMATCH")
    if seen_atomic_shards != set(range(16)) or seen_pair_shards != set(
        range(v2.PAIR_SHARD_COUNT)
    ):
        raise RuntimeError("PHASE_C_V2_RESULT_SHARD_UNION_MISMATCH")
    if manifest["campaign_test_count"] != 300 + 2 * pair_count:
        raise RuntimeError("PHASE_C_V2_RESULT_TEST_DENOMINATOR_MISMATCH")
    return manifest


def prove_checkpoint_resume(clean_work_root: Path, proof_root: Path) -> dict[str, Any]:
    if proof_root.exists() and any(proof_root.iterdir()):
        raise RuntimeError("PHASE_C_V2_RESUME_PROOF_ROOT_NOT_FRESH")
    proof_root.mkdir(parents=True, exist_ok=True)
    context = load_context()
    interrupted = run_pair_shard(
        proof_root, 0, stop_after=17, context=context
    )
    if interrupted["pair_count"] != 17 or interrupted["complete"] is not False:
        raise RuntimeError("PHASE_C_V2_FORCED_INTERRUPT_CURSOR_MISMATCH")
    shard_root = proof_root / "pair-shard-00"
    interrupted_checkpoint = read_json(shard_root / "checkpoint-v2.json")
    interrupted_rows = jsonl_rows(shard_root / "progress-v2.jsonl")
    interrupted_prefix_hash = v2.object_hash(interrupted_rows)
    resumed = run_pair_shard(proof_root, 0, context=context)
    if resumed["complete"] is not True or resumed["resumed_from"] != 17:
        raise RuntimeError("PHASE_C_V2_RESUME_DID_NOT_USE_CURSOR_17")
    resumed_rows = jsonl_rows(shard_root / "progress-v2.jsonl")
    clean_rows = jsonl_rows(
        clean_work_root / "pair-shard-00" / "progress-v2.jsonl"
    )
    if v2.canonical_bytes(resumed_rows) != v2.canonical_bytes(clean_rows):
        raise RuntimeError("PHASE_C_V2_RESUME_NOT_EQUAL_CLEAN")
    if resumed_rows[:17] != interrupted_rows:
        raise RuntimeError("PHASE_C_V2_RESUME_PREFIX_CHANGED")
    completed_skip = run_pair_shard(proof_root, 0)
    if (
        completed_skip["resumed_from"] != len(resumed_rows)
        or completed_skip["recomputed_prefix_count"] != 0
        or completed_skip["results_hash"] != resumed["results_hash"]
    ):
        raise RuntimeError("PHASE_C_V2_COMPLETED_SHARD_SKIP_MISMATCH")
    final_checkpoint = read_json(shard_root / "checkpoint-v2.json")
    receipt: dict[str, Any] = {
        "schema_version": "phase-c-v2-checkpoint-resume-receipt",
        "generated_at": GENERATED_AT,
        "campaign_hash": read_json(CAMPAIGN)["campaign_hash"],
        "pair_space_hash": read_json(PAIR_SUMMARY)["pair_space_hash"],
        "shard_id": 0,
        "shard_pair_count": len(resumed_rows),
        "forced_interrupt_cursor": 17,
        "interrupted_checkpoint_hash": interrupted_checkpoint["checkpoint_hash"],
        "interrupted_prefix_hash": interrupted_prefix_hash,
        "resumed_checkpoint_hash": final_checkpoint["checkpoint_hash"],
        "resumed_from": resumed["resumed_from"],
        "recomputed_prefix_count": 0,
        "prefix_17_preserved": True,
        "resume_equals_clean": True,
        "clean_results_hash": v2.object_hash(clean_rows),
        "resumed_results_hash": v2.object_hash(resumed_rows),
        "completed_shard_skip_verified": True,
        "external_effects": {
            "provider_calls": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "triples": 0,
        },
    }
    receipt["receipt_hash"] = v2.object_hash(receipt)
    write_json(CHECKPOINT_RECEIPT, receipt)
    return receipt


def result_file_hashes(output_base: Path) -> dict[str, dict[str, Any]]:
    manifest = verify_results(output_base)
    paths = [str(row["path"]) for row in manifest["files"]]
    paths.append("reports/hypothesis-research/v2/full-results-manifest-v2.json")
    result: dict[str, dict[str, Any]] = {}
    for relative_path in sorted(paths):
        path = output_base / relative_path
        payload = path.read_bytes()
        row: dict[str, Any] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if relative_path.endswith(".gz"):
            with gzip.open(path, "rb") as stream:
                content = stream.read()
            row["content_sha256"] = hashlib.sha256(content).hexdigest()
        result[relative_path] = row
    return result


def fresh_run_receipt(
    run_label: str, work_root: Path, shard_receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if len(shard_receipts) != v2.PAIR_SHARD_COUNT:
        raise RuntimeError("PHASE_C_V2_FRESH_RUN_SHARD_COUNT_MISMATCH")
    ordered = sorted(shard_receipts, key=lambda row: int(row["shard_id"]))
    if [int(row["shard_id"]) for row in ordered] != list(range(v2.PAIR_SHARD_COUNT)):
        raise RuntimeError("PHASE_C_V2_FRESH_RUN_SHARD_ID_MISMATCH")
    if any(
        row.get("complete") is not True
        or int(row.get("resumed_from", -1)) != 0
        or int(row.get("recomputed_prefix_count", -1)) != 0
        for row in ordered
    ):
        raise RuntimeError("PHASE_C_V2_FRESH_RUN_REUSED_CHECKPOINT")
    atomic_path = work_root / "atomic-results-raw-v2.json.gz"
    atomic_payload = atomic_path.read_bytes()
    receipt: dict[str, Any] = {
        "schema_version": "phase-c-v2-fresh-campaign-run-receipt",
        "run_label": run_label,
        "campaign_hash": read_json(CAMPAIGN)["campaign_hash"],
        "work_root_empty_before_run": True,
        "atomic_executed_in_run": True,
        "atomic_transport_sha256": hashlib.sha256(atomic_payload).hexdigest(),
        "pair_shard_count": v2.PAIR_SHARD_COUNT,
        "all_pair_shards_started_from_zero": True,
        "all_pair_shards_complete": True,
        "shards": [
            {
                "shard_id": int(row["shard_id"]),
                "pair_count": int(row["pair_count"]),
                "results_hash": row["results_hash"],
                "resumed_from": int(row["resumed_from"]),
                "recomputed_prefix_count": int(row["recomputed_prefix_count"]),
            }
            for row in ordered
        ],
    }
    receipt["receipt_hash"] = v2.object_hash(receipt)
    return receipt


def build_replay_manifest(
    output_a: Path,
    output_b: Path,
    run_receipts: Sequence[Mapping[str, Any]],
    git_output: Path = ROOT,
) -> dict[str, Any]:
    hashes_a = result_file_hashes(output_a)
    hashes_b = result_file_hashes(output_b)
    hashes_git = result_file_hashes(git_output)
    if hashes_a != hashes_b or hashes_a != hashes_git:
        differing = sorted(
            set(hashes_a) | set(hashes_b) | set(hashes_git),
            key=str,
        )
        differing = [
            path
            for path in differing
            if hashes_a.get(path) != hashes_b.get(path)
            or hashes_a.get(path) != hashes_git.get(path)
        ]
        raise RuntimeError(f"PHASE_C_V2_REPLAY_MISMATCH:{differing[:10]}")
    source_replay = read_json(SOURCE_BUNDLE / "source-export-replay-v2.json")
    if source_replay.get("replay_identical") is not True:
        raise RuntimeError("PHASE_C_V2_SOURCE_REPLAY_NOT_IDENTICAL")
    replay: dict[str, Any] = {
        "schema_version": "phase-c-v2-campaign-replay",
        "generated_at": GENERATED_AT,
        "fresh_campaign_runs": 2,
        "fresh_reducers": 2,
        "fresh_directory_contract": {
            "work_root_count": 2,
            "output_root_count": 2,
            "all_four_roots_resolved_disjoint": True,
            "all_four_roots_empty_before_run": True,
        },
        "fresh_run_receipts": [dict(row) for row in run_receipts],
        "result_file_count": len(hashes_a),
        "result_files": [
            {"path": path, **hashes_a[path]} for path in sorted(hashes_a)
        ],
        "byte_identical_a_b_git": True,
        "source_bundle_replay_runs": source_replay.get("replay_runs"),
        "source_bundle_replay_identical": True,
        "additional_network_reads": 0,
        "external_effects": {
            "provider_calls": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "triples": 0,
        },
    }
    replay["replay_hash"] = v2.object_hash(replay)
    write_json(CAMPAIGN_REPLAY, replay)
    return replay


def verify_replay_manifest() -> dict[str, Any]:
    replay = read_json(CAMPAIGN_REPLAY)
    verify_self_hash(
        replay, "replay_hash", "PHASE_C_V2_REPLAY_HASH_MISMATCH"
    )
    expected_hashes = result_file_hashes(ROOT)
    result_files = replay.get("result_files")
    if not isinstance(result_files, list):
        raise TypeError("PHASE_C_V2_REPLAY_RESULT_FILES_REQUIRED")
    declared_hashes = {
        str(row["path"]): {key: item for key, item in row.items() if key != "path"}
        for row in result_files
    }
    if (
        len(declared_hashes) != len(result_files)
        or declared_hashes != expected_hashes
        or replay.get("result_file_count") != len(expected_hashes)
        or replay.get("byte_identical_a_b_git") is not True
        or replay.get("fresh_campaign_runs") != 2
        or replay.get("fresh_reducers") != 2
    ):
        raise RuntimeError("PHASE_C_V2_REPLAY_RESULT_LINEAGE_MISMATCH")
    directory_contract = replay.get("fresh_directory_contract")
    if directory_contract != {
        "work_root_count": 2,
        "output_root_count": 2,
        "all_four_roots_resolved_disjoint": True,
        "all_four_roots_empty_before_run": True,
    }:
        raise RuntimeError("PHASE_C_V2_REPLAY_FRESH_DIRECTORY_CONTRACT_MISMATCH")
    run_receipts = replay.get("fresh_run_receipts")
    if not isinstance(run_receipts, list) or len(run_receipts) != 2:
        raise RuntimeError("PHASE_C_V2_REPLAY_FRESH_RUN_RECEIPT_COUNT_MISMATCH")
    campaign_hash = read_json(CAMPAIGN)["campaign_hash"]
    labels: set[str] = set()
    receipts_by_label: dict[str, Mapping[str, Any]] = {}
    expected_pair_counts = {
        shard_id: len(eligible_pairs_for_shard(shard_id))
        for shard_id in range(v2.PAIR_SHARD_COUNT)
    }
    for receipt in run_receipts:
        if not isinstance(receipt, Mapping):
            raise TypeError("PHASE_C_V2_REPLAY_FRESH_RUN_RECEIPT_REQUIRED")
        verify_self_hash(
            receipt,
            "receipt_hash",
            "PHASE_C_V2_FRESH_RUN_RECEIPT_HASH_MISMATCH",
        )
        label = str(receipt.get("run_label"))
        shards = receipt.get("shards")
        if (
            label in labels
            or label not in {"A", "B"}
            or receipt.get("campaign_hash") != campaign_hash
            or receipt.get("work_root_empty_before_run") is not True
            or receipt.get("atomic_executed_in_run") is not True
            or receipt.get("pair_shard_count") != v2.PAIR_SHARD_COUNT
            or receipt.get("all_pair_shards_started_from_zero") is not True
            or receipt.get("all_pair_shards_complete") is not True
            or not isinstance(shards, list)
            or [int(row["shard_id"]) for row in shards]
            != list(range(v2.PAIR_SHARD_COUNT))
            or any(
                int(row["resumed_from"]) != 0
                or int(row["recomputed_prefix_count"]) != 0
                or int(row["pair_count"])
                != expected_pair_counts[int(row["shard_id"])]
                for row in shards
            )
        ):
            raise RuntimeError("PHASE_C_V2_FRESH_RUN_RECEIPT_LINEAGE_MISMATCH")
        require_sha256(
            receipt.get("atomic_transport_sha256"),
            "PHASE_C_V2_FRESH_RUN_ATOMIC_HASH_MISMATCH",
        )
        for shard in shards:
            require_sha256(
                shard.get("results_hash"),
                "PHASE_C_V2_FRESH_RUN_SHARD_HASH_MISMATCH",
            )
        labels.add(label)
        receipts_by_label[label] = receipt
    receipt_a = receipts_by_label["A"]
    receipt_b = receipts_by_label["B"]
    if (
        receipt_a["atomic_transport_sha256"]
        != receipt_b["atomic_transport_sha256"]
        or receipt_a["shards"] != receipt_b["shards"]
    ):
        raise RuntimeError("PHASE_C_V2_FRESH_RUN_A_B_MISMATCH")
    source_manifest = source.verify(SOURCE_BUNDLE)
    source_replay = read_json(SOURCE_BUNDLE / "source-export-replay-v2.json")
    source_files = sorted(
        path.name
        for path in SOURCE_BUNDLE.iterdir()
        if path.is_file() and path.name != "source-export-replay-v2.json"
    )
    declared_source_files = source_replay.get("files")
    if not isinstance(declared_source_files, list):
        raise TypeError("PHASE_C_V2_SOURCE_REPLAY_FILES_REQUIRED")
    actual_source_files = [
        {
            "path": name,
            "bytes": (SOURCE_BUNDLE / name).stat().st_size,
            "sha256": hashlib.sha256((SOURCE_BUNDLE / name).read_bytes()).hexdigest(),
        }
        for name in source_files
    ]
    if (
        source_replay.get("manifest_hash") != source_manifest["manifest_hash"]
        or source_replay.get("replay_runs") != 2
        or source_replay.get("replay_identical") is not True
        or source_replay.get("compared_file_count") != len(actual_source_files)
        or declared_source_files != actual_source_files
        or replay.get("source_bundle_replay_runs") != 2
        or replay.get("source_bundle_replay_identical") is not True
        or replay.get("additional_network_reads") != 0
        or replay.get("external_effects")
        != {
            "provider_calls": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "triples": 0,
        }
        or any(
            source_replay.get(field) != 0
            for field in (
                "additional_network_reads",
                "provider_calls",
                "r2_gets",
                "remote_sql",
                "odds_credits",
                "manual_deployments",
                "triples",
            )
        )
    ):
        raise RuntimeError("PHASE_C_V2_SOURCE_REPLAY_LINEAGE_MISMATCH")
    return replay


def verify_checkpoint_receipt() -> dict[str, Any]:
    receipt = read_json(CHECKPOINT_RECEIPT)
    verify_self_hash(
        receipt, "receipt_hash", "PHASE_C_V2_RESUME_RECEIPT_HASH_MISMATCH"
    )
    campaign = verify_freeze()
    pair_summary = read_json(PAIR_SUMMARY)
    replay = verify_replay_manifest()
    replay_shard_zero_hashes = {
        str(run["shards"][0]["results_hash"])
        for run in replay["fresh_run_receipts"]
    }
    expected_shard_pair_count = len(eligible_pairs_for_shard(0))
    for field in (
        "interrupted_checkpoint_hash",
        "interrupted_prefix_hash",
        "resumed_checkpoint_hash",
        "clean_results_hash",
        "resumed_results_hash",
    ):
        require_sha256(
            receipt.get(field), f"PHASE_C_V2_RESUME_RECEIPT_INVALID_HASH:{field}"
        )
    if (
        receipt.get("campaign_hash") != campaign["campaign_hash"]
        or receipt.get("pair_space_hash") != pair_summary["pair_space_hash"]
        or receipt.get("shard_id") != 0
        or receipt.get("shard_pair_count") != expected_shard_pair_count
        or receipt.get("forced_interrupt_cursor") != 17
        or receipt.get("resumed_from") != 17
        or receipt.get("recomputed_prefix_count") != 0
        or receipt.get("prefix_17_preserved") is not True
        or receipt.get("resume_equals_clean") is not True
        or receipt.get("clean_results_hash") != receipt.get("resumed_results_hash")
        or replay_shard_zero_hashes != {str(receipt.get("clean_results_hash"))}
        or receipt.get("completed_shard_skip_verified") is not True
        or receipt.get("interrupted_checkpoint_hash")
        == receipt.get("resumed_checkpoint_hash")
        or receipt.get("external_effects")
        != {
            "provider_calls": 0,
            "r2_reads": 0,
            "r2_writes": 0,
            "remote_sql": 0,
            "odds_credits": 0,
            "deployments": 0,
            "triples": 0,
        }
    ):
        raise RuntimeError("PHASE_C_V2_RESUME_RECEIPT_LINEAGE_MISMATCH")
    return receipt


def require_fresh_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise RuntimeError(f"PHASE_C_V2_REPLAY_ROOT_NOT_FRESH:{label}")
    else:
        resolved.mkdir(parents=True)
    return resolved


def require_disjoint_replay_roots(paths: Sequence[Path]) -> None:
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise RuntimeError("PHASE_C_V2_REPLAY_ROOTS_NOT_DISTINCT")
    root = ROOT.resolve()
    for path in resolved:
        if path == root or root in path.parents:
            raise RuntimeError("PHASE_C_V2_REPLAY_ROOT_INSIDE_REPOSITORY")
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise RuntimeError("PHASE_C_V2_REPLAY_ROOTS_NOT_DISJOINT")


def build_closure_report(*, write: bool = True) -> dict[str, Any]:
    source_manifest = source.verify(SOURCE_BUNDLE)
    verify_freeze()
    result_manifest = verify_results(ROOT)
    property_set = read_json(
        ROOT / "reports/hypothesis-genome/predictor-eligible-property-set-v2.json"
    )
    registry = read_json(REGISTRY)
    mask_manifest = read_json(MASK_MANIFEST)
    pair_census = read_json(PAIR_SUMMARY)
    atomic = read_json(ATOMIC_SUMMARY)
    pairs = read_json(PAIR_RESULTS_SUMMARY)
    multiplicity = read_json(MULTIPLICITY_SUMMARY)
    controls = read_json(NEGATIVE_CONTROLS)
    guard_proof = verify_negative_guard_execution_proof()
    replay = verify_replay_manifest()
    resume = verify_checkpoint_receipt()
    pages = read_json(
        ROOT / "reports/closure/automatic-pages-side-effect-reclassification-v1.json"
    )
    atomic_test_statuses: Counter[str] = Counter()
    pair_test_statuses: Counter[str] = Counter()
    atomic_stability_all = 0
    pair_stability_all = 0
    for descriptor in result_manifest["files"]:
        path = str(descriptor["path"])
        if not path.endswith(".gz"):
            continue
        payload = read_gzip_json(ROOT / path)
        if "atomic-results-shard" in path:
            for row in payload["records"]:
                for metric in row["target_metrics"].values():
                    atomic_test_statuses[str(metric["status"])] += 1
                    stability = metric["stability"]
                    if all(
                        int(stability[key]["positive_count"])
                        == int(stability[key]["group_count"])
                        for key in (
                            "leave_one_league_out",
                            "leave_one_team_out",
                            "leave_one_period_out",
                        )
                    ):
                        atomic_stability_all += 1
        elif "pair-results-shard" in path:
            for row in payload["records"]:
                for metric in row["target_metrics"].values():
                    pair_test_statuses[str(metric["status"])] += 1
                    stability = metric["stability_by_comparator"]
                    if all(
                        int(stability[comparator][key]["positive_count"])
                        == int(stability[comparator][key]["group_count"])
                        for comparator in v2.PAIR_COMPARATORS
                        for key in (
                            "leave_one_league_out",
                            "leave_one_team_out",
                            "leave_one_period_out",
                        )
                    ):
                        pair_stability_all += 1
    selected = [
        row
        for row in property_set["records"]
        if str(row["disposition"]).startswith("SELECTED_")
    ]
    blocked = [
        row
        for row in property_set["records"]
        if row["disposition"] == "BLOCKED_V2"
    ]
    report: dict[str, Any] = {
        "schema_version": "phase-c-v2-full-bounded-expansion-closure-v1",
        "generated_at": GENERATED_AT,
        "mission": "PHASE C FOUNDATION CLOSURE AND FULL BOUNDED EXPANSION V2",
        "git": {
            "repository": "dddur75/robin-stades-ng",
            "base_main_sha": "d4ce1836ef8f42f37e284126a7190ebf051f6dbf",
            "implementation_parent_sha": "10ea1d7fd34333daea10f7cbc7f42d6f2acb6bf2",
            "branch": "codex/phase-c-full-bounded-expansion-v2",
            "pull_request": 38,
            "required_delivery_state": "OPEN_DRAFT_NOT_MERGED",
            "delivery_head_sha": None,
            "workflow_dispatches": 0,
            "activation_state": "HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH",
        },
        "deployments_and_publications": pages["effect_accounting"],
        "pages_reclassification": {
            "automatic_side_effect": True,
            "phase_c_execution_violation": False,
            "exposure_audit": pages["publication_exposure_audit"],
            "bounded_v1_summary_publication_observed": True,
            "new_v2_results_publications": 0,
        },
        "properties": {
            "genome_property_count": property_set["genome_property_count"],
            "candidate_property_count": property_set["candidate_property_count"],
            "selected_property_count": property_set["selected_property_count"],
            "selected_v1_property_count": property_set["selected_v1_property_count"],
            "selected_v2_property_count": property_set["selected_v2_property_count"],
            "blocked_candidate_count": property_set["blocked_candidate_count"],
            "selected_property_ids": [row["property_id"] for row in selected],
            "blocked_candidates": [
                {
                    "property_id": row["property_id"],
                    "block_reason": row["block_reason"],
                }
                for row in blocked
            ],
            "difference_from_up_to_25_explained": (
                "Nine of the 25 public candidates remain fail-closed: four calendar fields "
                "lack revision-known_at provenance, season is a constant context, venue_role "
                "duplicates orientation, and three player fields lack a cutoff-observed player population."
            ),
            "proof_ceiling": "HISTORICAL_RECONSTRUCTED_ONLY",
            "point_in_time_source_provenance": False,
        },
        "source": {
            "manifest_hash": source_manifest["manifest_hash"],
            "source_row_count": source_manifest["counts"]["normalized_row_count"],
            "fixture_count": source_manifest["counts"]["scientific_fixture_count"],
            "team_match_fact_count": source_manifest["counts"]["team_fixture_count"],
            "event_fact_count": source_manifest["counts"]["scientific_event_fact_count"],
            "substitution_fact_count": source_manifest["counts"]["substitution_fact_count"],
            "generic_card_fact_count": source_manifest["counts"]["generic_card_fact_count"],
            "legacy_generic_card_fact_count": source_manifest["counts"]["legacy_generic_card_fact_count"],
            "yellow_card_fact_count": source_manifest["counts"]["yellow_card_fact_count"],
            "dismissal_fact_count": source_manifest["counts"]["dismissal_fact_count"],
            "formation_fact_count": source_manifest["counts"]["formation_fact_count"],
            "provider_ids_in_bundle": 0,
            "target_labels_separate": True,
        },
        "tags": {
            "tag_count": registry["tag_count"],
            "legacy_tag_count": registry["legacy_tag_count"],
            "new_tag_count": registry["new_tag_count"],
            "registry_hash": registry["registry_hash"],
            "legacy_objects_unchanged": True,
        },
        "masks": {
            "mask_count": mask_manifest["mask_count"],
            "known_true_bytes_per_mask": mask_manifest["known_true_bytes_per_mask"],
            "manifest_hash": mask_manifest["manifest_hash"],
            "true_subset_known": True,
            "unknown_preserved": True,
            "target_labels_loaded_during_freeze": False,
        },
        "atomic": {
            "tag_count": atomic["tag_count"],
            "canonical_test_count": atomic["canonical_test_count"],
            "row_status_counts": atomic["status_counts"],
            "test_status_counts": dict(sorted(atomic_test_statuses.items())),
            "fully_positive_leave_one_league_team_period_test_count": atomic_stability_all,
            "surviving_test_count_after_campaign_bh": 0,
        },
        "pairs": {
            "theoretical_pair_count": pair_census["theoretical_pair_count"],
            "same_property_pair_count": pair_census["same_property_pair_count"],
            "distinct_property_pair_count": pair_census["distinct_property_pair_count"],
            "eligible_pair_count": pair_census["eligible_pair_count"],
            "pruned_pair_count": pair_census["pruned_pair_count"],
            "pruning_reasons": pair_census["reason_counts"],
            "evaluated_pair_count": pairs["pair_count"],
            "canonical_test_count": pairs["canonical_test_count"],
            "row_status_counts": pairs["status_counts"],
            "test_status_counts": dict(sorted(pair_test_statuses.items())),
            "fully_positive_all_comparators_leave_one_league_team_period_test_count": pair_stability_all,
            "surviving_test_count": pairs["surviving_test_count"],
            "comparators": list(v2.PAIR_COMPARATORS),
            "label_oracle": False,
        },
        "shards": {
            "pair_census_shards": pair_census["shard_count"],
            "atomic_result_shards": result_manifest["atomic_shard_count"],
            "pair_result_shards": result_manifest["pair_shard_count"],
            "eligible_union_exact": True,
            "duplicate_result_count": 0,
            "missing_result_count": 0,
            "maximum_git_blob_bytes": max(
                int(row["bytes"])
                for row in result_manifest["files"]
                if str(row["path"]).endswith(".gz")
            ),
        },
        "multiplicity": multiplicity,
        "stability": {
            "dimensions": [
                "LEAVE_ONE_LEAGUE_OUT",
                "LEAVE_ONE_TEAM_OUT",
                "LEAVE_ONE_PERIOD_OUT",
            ],
            "stored_per_test": True,
            "pair_survivors_requiring_ultra_review": 0,
        },
        "negative_controls": {
            "control_count": controls["control_count"],
            "modeled_control_count": controls["modeled_control_count"],
            "guard_control_count": controls["guard_control_count"],
            "executed_guard_control_count": guard_proof[
                "executed_guard_control_count"
            ],
            "executed_guard_track_count": guard_proof[
                "executed_guard_track_count"
            ],
            "guard_execution_proof": (
                "reports/hypothesis-research/v2/"
                "negative-control-guard-execution-v2.json"
            ),
            "guard_execution_proof_hash": guard_proof["proof_hash"],
            "modeled_track_target_test_count": controls["modeled_track_target_test_count"],
            "surviving_control_count": controls["surviving_control_count"],
            "gate": controls["negative_control_gate"],
        },
        "prices_and_bets": {
            "point_in_time_price_provenance": False,
            "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
            "roi": None,
            "profit": None,
            "clv": None,
            "drawdown": None,
            "real_bets": 0,
            "promotions": 0,
        },
        "costs": {
            "provider_calls": 0,
            "odds_credits": 0,
            "remote_sql": 0,
            "r2_list": 0,
            "r2_head": 0,
            "r2_get": 0,
            "r2_write": 0,
            "r2_delete": 0,
            "phase_c_workflow_deployments": 0,
            "manual_pages_dispatches": 0,
            "external_financial_cost_eur": 0,
            "git_result_evidence_bytes": sum(
                int(row["bytes"]) for row in result_manifest["files"]
            ),
        },
        "replay": {
            "fresh_campaign_runs": replay["fresh_campaign_runs"],
            "fresh_reducers": replay["fresh_reducers"],
            "result_file_count": replay["result_file_count"],
            "byte_identical_a_b_git": replay["byte_identical_a_b_git"],
            "source_bundle_replay_runs": replay["source_bundle_replay_runs"],
            "replay_hash": replay["replay_hash"],
        },
        "checkpoint_resume": resume,
        "dashboard": {
            "contract": "reports/hypothesis-research/v2/dashboard-data-contract-v2.json",
            "data_only": True,
            "betting_outputs_forbidden": True,
        },
        "security": {
            "forbidden_data_publications": 0,
            "heavy_phase_c_evidence_publications": 0,
            "provider_payload_publications": 0,
            "secret_publications": 0,
            "manual_deployments": 0,
            "manual_publications": 0,
            "triple_search_executed": False,
            "max_depth": 2,
        },
        "next_mission": {
            "verdict": "NO_TRIPLE_EXECUTION_AUTHORIZED",
            "recommended": (
                "Acquire real revision-known_at and point-in-time source provenance before "
                "any prospective or betting interpretation; keep the current V2 evidence immutable."
            ),
        },
        "verdicts": [
            "AUTOMATIC_GITHUB_PAGES_SIDE_EFFECT_RECLASSIFIED",
            "PUBLICATION_EXPOSURE_AUDIT_PASSED",
            "PHASE_C_V2_RESUMED_AFTER_NON_BLOCKING_SIDE_EFFECT",
            "PHASE_C_FULL_BOUNDED_EXPANSION_READY",
            "TRIPLE_SEARCH_REMAINS_LOCKED_NO_PAIR_SURVIVOR",
        ],
    }
    report["report_hash"] = v2.object_hash(report)
    if write:
        write_json(CLOSURE_REPORT, report)
    return report


def verify_closure_report() -> dict[str, Any]:
    report = read_json(CLOSURE_REPORT)
    verify_self_hash(
        report, "report_hash", "PHASE_C_V2_CLOSURE_REPORT_HASH_MISMATCH"
    )
    source_manifest = source.verify(SOURCE_BUNDLE)
    campaign = verify_freeze()
    result_manifest = verify_results(ROOT)
    replay = verify_replay_manifest()
    receipt = verify_checkpoint_receipt()
    guard_proof = verify_negative_guard_execution_proof()
    registry = read_json(REGISTRY)
    mask_manifest = read_json(MASK_MANIFEST)
    pair_summary = read_json(PAIR_SUMMARY)
    expected_links = {
        "source": report["source"]["manifest_hash"]
        == source_manifest["manifest_hash"],
        "registry": report["tags"]["registry_hash"] == registry["registry_hash"],
        "mask": report["masks"]["manifest_hash"] == mask_manifest["manifest_hash"],
        "campaign": report["checkpoint_resume"]["campaign_hash"]
        == campaign["campaign_hash"],
        "pair_space": report["checkpoint_resume"]["pair_space_hash"]
        == pair_summary["pair_space_hash"],
        "results": report["pairs"]["evaluated_pair_count"]
        == result_manifest["eligible_pair_count"],
        "replay": report["replay"]["replay_hash"] == replay["replay_hash"],
        "receipt": report["checkpoint_resume"]["receipt_hash"]
        == receipt["receipt_hash"],
        "negative_guard": report["negative_controls"][
            "guard_execution_proof_hash"
        ]
        == guard_proof["proof_hash"],
    }
    if not all(expected_links.values()):
        failed = sorted(key for key, passed in expected_links.items() if not passed)
        raise RuntimeError(f"PHASE_C_V2_CLOSURE_LINEAGE_MISMATCH:{failed}")
    effects = report["deployments_and_publications"]
    if effects != {
        "automatic_repository_pages_deployments_observed": 1,
        "documentation_site_publication_observed": True,
        "bounded_v1_scientific_summary_publication_observed": True,
        "mission_initiated_scientific_publications": 0,
        "new_v2_results_publications": 0,
        "forbidden_heavy_scientific_evidence_publications": 0,
        "mission_initiated_deployments": 0,
        "phase_c_workflow_deployments": 0,
        "manual_pages_dispatches": 0,
        "pages_configuration_changes": 0,
        "forbidden_data_publications": 0,
        "heavy_phase_c_evidence_publications": 0,
        "provider_payload_publications": 0,
        "secret_publications": 0,
        "provider_calls": 0,
        "odds_credits": 0,
        "remote_sql": 0,
        "r2_list": 0,
        "r2_head": 0,
        "r2_get": 0,
        "r2_write": 0,
        "r2_delete": 0,
        "real_bets": 0,
        "promotions": 0,
        "triples": 0,
    }:
        raise RuntimeError("PHASE_C_V2_CLOSURE_EFFECT_ACCOUNTING_MISMATCH")
    if (
        report["properties"]["proof_ceiling"]
        != "HISTORICAL_RECONSTRUCTED_ONLY"
        or report["properties"]["point_in_time_source_provenance"] is not False
        or report["pairs"]["surviving_test_count"] != 0
        or report["pairs"]["label_oracle"] is not False
        or report["multiplicity"]["triple_search_locked"] is not True
        or report["multiplicity"]["surviving_pair_test_count"] != 0
        or report["negative_controls"]["executed_guard_control_count"] != 4
        or report["negative_controls"]["executed_guard_track_count"] != 8
        or report["negative_controls"]["surviving_control_count"] != 0
        or report["negative_controls"]["gate"] != "PASS"
        or report["security"]
        != {
            "forbidden_data_publications": 0,
            "heavy_phase_c_evidence_publications": 0,
            "provider_payload_publications": 0,
            "secret_publications": 0,
            "manual_deployments": 0,
            "manual_publications": 0,
            "triple_search_executed": False,
            "max_depth": 2,
        }
        or report["prices_and_bets"]
        != {
            "point_in_time_price_provenance": False,
            "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
            "roi": None,
            "profit": None,
            "clv": None,
            "drawdown": None,
            "real_bets": 0,
            "promotions": 0,
        }
        or any(
            report["costs"].get(field) != 0
            for field in (
                "provider_calls",
                "odds_credits",
                "remote_sql",
                "r2_list",
                "r2_head",
                "r2_get",
                "r2_write",
                "r2_delete",
                "phase_c_workflow_deployments",
                "manual_pages_dispatches",
                "external_financial_cost_eur",
            )
        )
    ):
        raise RuntimeError("PHASE_C_V2_CLOSURE_SAFETY_CONTRACT_MISMATCH")
    if report["verdicts"] != [
        "AUTOMATIC_GITHUB_PAGES_SIDE_EFFECT_RECLASSIFIED",
        "PUBLICATION_EXPOSURE_AUDIT_PASSED",
        "PHASE_C_V2_RESUMED_AFTER_NON_BLOCKING_SIDE_EFFECT",
        "PHASE_C_FULL_BOUNDED_EXPANSION_READY",
        "TRIPLE_SEARCH_REMAINS_LOCKED_NO_PAIR_SURVIVOR",
    ]:
        raise RuntimeError("PHASE_C_V2_CLOSURE_VERDICT_MISMATCH")
    expected_report = build_closure_report(write=False)
    if report != expected_report:
        raise RuntimeError("PHASE_C_V2_CLOSURE_REBUILD_MISMATCH")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "freeze",
            "verify-freeze",
            "atomic",
            "pair-shard",
            "pairs",
            "reduce",
            "verify-results",
            "guard-proof",
            "verify-guard-proof",
            "prove-resume",
            "replay",
            "closure",
        ),
    )
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--proof-root", type=Path)
    parser.add_argument("--second-work-root", type=Path)
    parser.add_argument("--replay-output-a", type=Path)
    parser.add_argument("--replay-output-b", type=Path)
    parser.add_argument("--shard-id", type=int)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--soft-deadline-seconds", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "freeze":
        build_freeze()
    elif args.command == "verify-freeze":
        verify_freeze()
    elif args.command == "verify-results":
        verify_results(args.output_root)
    elif args.command == "guard-proof":
        write_json(NEGATIVE_GUARD_PROOF, build_negative_guard_execution_proof())
        verify_negative_guard_execution_proof()
    elif args.command == "verify-guard-proof":
        verify_negative_guard_execution_proof()
    elif args.command == "closure":
        build_closure_report()
        verify_closure_report()
    else:
        work_root = campaign_work_root(args.work_root)
        if args.command == "atomic":
            run_atomic(work_root)
        elif args.command == "pair-shard":
            if args.shard_id is None:
                raise SystemExit("--shard-id is required for pair-shard")
            receipt = run_pair_shard(
                work_root,
                args.shard_id,
                stop_after=args.stop_after,
                soft_deadline_seconds=args.soft_deadline_seconds,
            )
            print(json.dumps(receipt, sort_keys=True))
        elif args.command == "pairs":
            receipts = run_all_pair_shards(
                work_root, soft_deadline_seconds=args.soft_deadline_seconds
            )
            print(json.dumps(receipts, sort_keys=True))
        elif args.command == "reduce":
            reduce_campaign(work_root, args.output_root)
        elif args.command == "prove-resume":
            if args.proof_root is None:
                raise SystemExit("--proof-root is required for prove-resume")
            prove_checkpoint_resume(work_root, args.proof_root)
        elif args.command == "replay":
            if (
                args.work_root is None
                or args.second_work_root is None
                or args.replay_output_a is None
                or args.replay_output_b is None
            ):
                raise SystemExit(
                    "--work-root, --second-work-root, --replay-output-a and --replay-output-b are required"
                )
            replay_roots = [
                work_root,
                args.second_work_root,
                args.replay_output_a,
                args.replay_output_b,
            ]
            require_disjoint_replay_roots(replay_roots)
            work_root = require_fresh_directory(work_root, "WORK_A")
            second = require_fresh_directory(args.second_work_root, "WORK_B")
            output_a = require_fresh_directory(args.replay_output_a, "OUTPUT_A")
            output_b = require_fresh_directory(args.replay_output_b, "OUTPUT_B")
            run_atomic(work_root)
            receipts_a = run_all_pair_shards(work_root)
            run_atomic(second)
            receipts_b = run_all_pair_shards(second)
            run_receipts = [
                fresh_run_receipt("A", work_root, receipts_a),
                fresh_run_receipt("B", second, receipts_b),
            ]
            reduce_campaign(work_root, output_a)
            reduce_campaign(second, output_b)
            build_replay_manifest(
                output_a, output_b, run_receipts, ROOT
            )
        else:
            raise AssertionError(args.command)


if __name__ == "__main__":
    main()
