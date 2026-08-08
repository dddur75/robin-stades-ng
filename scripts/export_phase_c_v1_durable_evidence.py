"""Export and verify the sanitized durable evidence needed to close Phase C V1."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import platform
import struct
import zlib
from collections.abc import Mapping, Sequence
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_ROOT = ROOT / "reports/closure/phase-c-v1-durable-evidence"
MASK_MANIFEST_PATH = ROOT / "reports/hypothesis-masks/atomic-mask-manifest-v1.json"
TAG_REGISTRY_PATH = ROOT / "configs/hypothesis-tags/canonical-tag-registry-v1.json"
ATOMIC_COMPACT_PATH = ROOT / "reports/hypothesis-research/atomic-results-v1.json"
PAIR_COMPACT_PATH = ROOT / "reports/hypothesis-research/pair-results-v1.json"
PAIR_SPACE_PATH = ROOT / "reports/hypothesis-research/pair-search-space-v1.json"
GENERATED_AT = "2026-08-08T17:20:00Z"
FIXTURE_COUNT = 1_756
MASK_NBYTES = (FIXTURE_COUNT + 7) // 8
FOLD0_TRAIN_END = 703
OOF_START = 303
SEED = 11_011


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def object_hash(value: object) -> str:
    return sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def load_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"GZIP_JSON_OBJECT_REQUIRED:{path.name}")
    return value


def write_gzip_json(path: Path, value: object) -> dict[str, Any]:
    payload = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(payload)
    compressed = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(compressed),
        "sha256": sha256_bytes(compressed),
        "content_sha256": sha256_bytes(payload),
        "reconstruction_identity": "content_sha256",
        "transport_sha256_runtime_bound": True,
    }


def parse_mask(payload: bytes, expected_mask_id: str) -> tuple[int, int]:
    if len(payload) < 18 + 32 + 2 * MASK_NBYTES + 32:
        raise RuntimeError("MASK_PAYLOAD_TOO_SHORT")
    body, checksum = payload[:-32], payload[-32:]
    if hashlib.sha256(body).digest() != checksum or not body.startswith(b"RMASKV1\0"):
        raise RuntimeError("MASK_ENVELOPE_INVALID")
    count, identity_length = struct.unpack("<QH", body[8:18])
    if count != FIXTURE_COUNT:
        raise RuntimeError("MASK_FIXTURE_COUNT_MISMATCH")
    identity_start = 50
    identity_end = identity_start + identity_length
    identity = body[identity_start:identity_end].decode("utf-8")
    if identity != expected_mask_id:
        raise RuntimeError("MASK_IDENTITY_MISMATCH")
    masks = body[identity_end:]
    if len(masks) != 2 * MASK_NBYTES:
        raise RuntimeError("MASK_LENGTH_MISMATCH")
    known = int.from_bytes(masks[:MASK_NBYTES], "little")
    true = int.from_bytes(masks[MASK_NBYTES:], "little")
    if true & ~known:
        raise RuntimeError("MASK_TRUE_NOT_SUBSET_KNOWN")
    return known, true


def sanitize_analysis_core(source: Mapping[str, Any]) -> dict[str, Any]:
    fixtures = source.get("fixtures")
    features = source.get("features")
    targets = source.get("targets")
    if not isinstance(fixtures, list) or len(fixtures) != FIXTURE_COUNT:
        raise RuntimeError("ANALYSIS_CORE_FIXTURE_COUNT_MISMATCH")
    if not isinstance(features, list) or len(features) != FIXTURE_COUNT:
        raise RuntimeError("ANALYSIS_CORE_FEATURE_COUNT_MISMATCH")
    if not isinstance(targets, list) or len(targets) != FIXTURE_COUNT:
        raise RuntimeError("ANALYSIS_CORE_TARGET_COUNT_MISMATCH")
    team_ordinals: dict[object, str] = {}
    competition_ordinals: dict[object, str] = {}
    sanitized_fixtures: list[dict[str, Any]] = []
    for ordinal, fixture in enumerate(fixtures, start=1):
        if not isinstance(fixture, Mapping):
            raise TypeError("ANALYSIS_CORE_FIXTURE_OBJECT_REQUIRED")
        row = dict(fixture)
        for key in ("home_id", "away_id"):
            source_team_id = row[key]
            if source_team_id not in team_ordinals:
                team_ordinals[source_team_id] = f"team:{len(team_ordinals) + 1:03d}"
            row[key] = team_ordinals[source_team_id]
        source_competition_id = row["competition_id"]
        if source_competition_id not in competition_ordinals:
            competition_ordinals[source_competition_id] = (
                f"competition:{len(competition_ordinals) + 1:02d}"
            )
        row["competition_id"] = competition_ordinals[source_competition_id]
        row["fixture_id"] = f"fixture:{ordinal:04d}"
        sanitized_fixtures.append(row)
    return {
        "schema_version": "phase-c-analysis-core-sanitized-v1",
        "generated_at": GENERATED_AT,
        "fixture_count": FIXTURE_COUNT,
        "identifier_policy": "INTERNAL_FIRST_APPEARANCE_ORDINALS_NO_LITERAL_PROVIDER_IDS",
        "ordinal_contract": "row i preserves the exact frozen V1 universe ordinal",
        "source_schema_version": source.get("schema_version"),
        "fixtures": sanitized_fixtures,
        "features": features,
        "targets": targets,
    }


def load_mask_bundle_from_source(
    mask_source_root: Path, manifest: Mapping[str, Any]
) -> tuple[dict[str, tuple[int, int]], dict[str, Any]]:
    masks: dict[str, tuple[int, int]] = {}
    bundle_rows: list[dict[str, Any]] = []
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 80:
        raise RuntimeError("MASK_MANIFEST_COUNT_MISMATCH")
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("MASK_MANIFEST_RECORD_REQUIRED")
        relative = str(record["artifact_relative_path"])
        payload = (mask_source_root / relative).read_bytes()
        if len(payload) != int(record["serialized_bytes"]):
            raise RuntimeError("MASK_SERIALIZED_BYTES_MISMATCH")
        if sha256_bytes(payload) != record["payload_sha256"]:
            raise RuntimeError("MASK_PAYLOAD_HASH_MISMATCH")
        known, true = parse_mask(payload, str(record["mask_id"]))
        tag_id = str(record["tag_id"])
        if known.bit_count() != int(record["known_count"]):
            raise RuntimeError("MASK_KNOWN_COUNT_MISMATCH")
        if true.bit_count() != int(record["true_count"]):
            raise RuntimeError("MASK_TRUE_COUNT_MISMATCH")
        masks[tag_id] = (known, true)
        bundle_rows.append(
            {
                "tag_id": tag_id,
                "mask_id": record["mask_id"],
                "artifact_relative_path": relative,
                "serialized_bytes": len(payload),
                "payload_sha256": sha256_bytes(payload),
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
    return masks, {
        "schema_version": "phase-c-mask-payload-bundle-v1",
        "generated_at": GENERATED_AT,
        "encoding": "base64 of exact mask-v1 envelope bytes",
        "mask_count": len(bundle_rows),
        "records": sorted(bundle_rows, key=lambda row: row["tag_id"]),
    }


def pair_id(tag_a: str, tag_b: str) -> str:
    left, right = sorted((tag_a, tag_b))
    return "pair:" + sha256_bytes((left + "\0" + right).encode("utf-8"))


def build_eligible_pairs(
    masks: Mapping[str, tuple[int, int]], registry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    property_by_tag = {
        str(row["tag_id"]): str(row["property_id"])
        for row in registry["tags"]
    }
    eligible_mask = ((1 << FOLD0_TRAIN_END) - 1) ^ ((1 << OOF_START) - 1)
    rows: list[dict[str, Any]] = []
    for tag_a, tag_b in combinations(sorted(masks), 2):
        property_a = property_by_tag[tag_a]
        property_b = property_by_tag[tag_b]
        if property_a == property_b:
            continue
        known = masks[tag_a][0] & masks[tag_b][0] & eligible_mask
        true = masks[tag_a][1] & masks[tag_b][1] & eligible_mask
        known_count = known.bit_count()
        true_count = true.bit_count()
        union = (masks[tag_a][1] | masks[tag_b][1]) & eligible_mask
        jaccard = true_count / union.bit_count() if union else 1.0
        if known_count < int(eligible_mask.bit_count() * 0.8):
            continue
        if true_count < 40 or jaccard >= 0.98:
            continue
        side_a = tag_a.split(".", 1)[0].removeprefix("TEAM_")
        side_b = tag_b.split(".", 1)[0].removeprefix("TEAM_")
        pid = pair_id(tag_a, tag_b)
        rows.append(
            {
                "pair_id": pid,
                "parent_a": tag_a,
                "parent_b": tag_b,
                "parent_property_a": property_a,
                "parent_property_b": property_b,
                "category": "CROSS_SIDE" if side_a != side_b else f"{side_a}_{side_a}",
                "initial_known_count": known_count,
                "initial_true_count": true_count,
                "initial_jaccard": round(jaccard, 8),
                "selection_hash": sha256_bytes(
                    (str(SEED) + "\0" + pid).encode("utf-8")
                ),
                "shard_id": int(sha256_bytes(pid.encode("utf-8"))[:16], 16) % 8,
            }
        )
    return sorted(rows, key=lambda row: row["pair_id"])


def verify_full_artifact(source: Path, compact: Mapping[str, Any]) -> bytes:
    descriptor = compact["full_results_artifact"]
    payload = source.read_bytes()
    if len(payload) != int(descriptor["compressed_bytes"]):
        raise RuntimeError("FULL_ARTIFACT_SIZE_MISMATCH")
    if sha256_bytes(payload) != descriptor["sha256"]:
        raise RuntimeError("FULL_ARTIFACT_HASH_MISMATCH")
    with gzip.open(source, "rb") as handle:
        content = handle.read()
    if sha256_bytes(content) != descriptor["content_sha256"]:
        raise RuntimeError("FULL_ARTIFACT_CONTENT_HASH_MISMATCH")
    return payload


def export(args: argparse.Namespace) -> None:
    evidence_root = args.evidence_root.resolve()
    evidence_root.mkdir(parents=True, exist_ok=True)
    mask_manifest = load_json(MASK_MANIFEST_PATH)
    registry = load_json(TAG_REGISTRY_PATH)
    atomic_compact = load_json(ATOMIC_COMPACT_PATH)
    pair_compact = load_json(PAIR_COMPACT_PATH)
    pair_space = load_json(PAIR_SPACE_PATH)

    source_core_bytes = args.analysis_core.read_bytes()
    source_core_descriptor = mask_manifest["analysis_core"]
    if len(source_core_bytes) != int(source_core_descriptor["compressed_bytes"]):
        raise RuntimeError("ANALYSIS_CORE_SIZE_MISMATCH")
    if sha256_bytes(source_core_bytes) != source_core_descriptor["sha256"]:
        raise RuntimeError("ANALYSIS_CORE_HASH_MISMATCH")
    with gzip.open(args.analysis_core, "rb") as handle:
        source_core_content = handle.read()
    if sha256_bytes(source_core_content) != source_core_descriptor["content_sha256"]:
        raise RuntimeError("ANALYSIS_CORE_CONTENT_HASH_MISMATCH")

    sanitized_core = sanitize_analysis_core(json.loads(source_core_content))
    core_record = write_gzip_json(
        evidence_root / "analysis-core-sanitized-v1.json.gz", sanitized_core
    )
    masks, bundle = load_mask_bundle_from_source(args.mask_source_root, mask_manifest)
    mask_record = write_gzip_json(
        evidence_root / "mask-payload-bundle-v1.json.gz", bundle
    )

    eligible_pairs = build_eligible_pairs(masks, registry)
    if len(eligible_pairs) != int(pair_space["structurally_eligible_tag_pairs"]):
        raise RuntimeError("ELIGIBLE_PAIR_COUNT_MISMATCH")
    selected_ids = {str(row["pair_id"]) for row in pair_space["pairs"]}
    eligible_ids = {str(row["pair_id"]) for row in eligible_pairs}
    if not selected_ids <= eligible_ids or len(selected_ids) != 120:
        raise RuntimeError("SELECTED_PAIR_SUBSET_MISMATCH")
    pair_census = {
        "schema_version": "phase-c-eligible-tag-pair-census-v1",
        "generated_at": GENERATED_AT,
        "selection_is_target_blind": True,
        "structurally_eligible_tag_pairs": len(eligible_pairs),
        "selected_tag_pairs": len(selected_ids),
        "eligible_not_selected_tag_pairs": len(eligible_ids - selected_ids),
        "eligible_pair_ids_sha256": object_hash(sorted(eligible_ids)),
        "pairs": [
            row | {"v1_disposition": "SELECTED" if row["pair_id"] in selected_ids else "ELIGIBLE_NOT_SELECTED"}
            for row in eligible_pairs
        ],
    }
    eligible_record = write_gzip_json(
        evidence_root / "eligible-tag-pair-census-v1.json.gz", pair_census
    )

    atomic_payload = verify_full_artifact(args.atomic_full, atomic_compact)
    pair_payload = verify_full_artifact(args.pair_full, pair_compact)
    (evidence_root / "atomic-results-full-v1.json.gz").write_bytes(atomic_payload)
    (evidence_root / "pair-results-full-v1.json.gz").write_bytes(pair_payload)
    atomic_record = {
        "path": "atomic-results-full-v1.json.gz",
        "bytes": len(atomic_payload),
        "sha256": sha256_bytes(atomic_payload),
        "content_sha256": atomic_compact["full_results_artifact"]["content_sha256"],
        "reconstruction_identity": "exact_source_gzip_sha256",
        "transport_sha256_runtime_bound": False,
    }
    pair_record = {
        "path": "pair-results-full-v1.json.gz",
        "bytes": len(pair_payload),
        "sha256": sha256_bytes(pair_payload),
        "content_sha256": pair_compact["full_results_artifact"]["content_sha256"],
        "reconstruction_identity": "exact_source_gzip_sha256",
        "transport_sha256_runtime_bound": False,
    }
    manifest = {
        "schema_version": "phase-c-v1-durable-evidence-manifest-v1",
        "generated_at": GENERATED_AT,
        "source_revision": "008396bad19885386bd7d17ab07c75ee79bb0a9e",
        "purpose": "sanitized durable reconstruction and audit evidence for bounded Phase C V1",
        "raw_provider_rows_included": False,
        "raw_fixture_ids_included": False,
        "raw_provider_identifiers_included": False,
        "absolute_paths_included": False,
        "regenerated_gzip_python_runtime": platform.python_version(),
        "regenerated_gzip_zlib_compile_version": zlib.ZLIB_VERSION,
        "regenerated_gzip_zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "regenerated_gzip_identity": "canonical_uncompressed_content_sha256",
        "fixture_count": FIXTURE_COUNT,
        "mask_count": 80,
        "structurally_eligible_tag_pairs": 1_398,
        "selected_tag_pairs": 120,
        "eligible_not_selected_tag_pairs": 1_278,
        "files": [core_record, mask_record, eligible_record, atomic_record, pair_record],
        "reconstruction_contract": {
            "analysis_core": "sanitized values and internal first-appearance ordinals in exact V1 universe order",
            "mask_payloads": "exact mask-v1 envelope bytes recoverable from base64",
            "atomic_full": "exact V1 full gzip bytes",
            "pair_full": "exact V1 full gzip bytes",
            "eligible_pairs": "all 1,398 target-blind structurally eligible V1 tag pairs",
        },
        "provider_calls": 0,
        "r2_operations": 0,
        "remote_sql_queries": 0,
        "odds_credits": 0,
        "triples_executed": 0,
    }
    (evidence_root / "durable-evidence-manifest-v1.json").write_bytes(
        canonical_bytes(manifest)
    )
    verify(evidence_root)


def verify(evidence_root: Path) -> None:
    manifest = load_json(evidence_root / "durable-evidence-manifest-v1.json")
    file_records = {str(row["path"]): row for row in manifest["files"]}
    if set(file_records) != {
        "analysis-core-sanitized-v1.json.gz",
        "mask-payload-bundle-v1.json.gz",
        "eligible-tag-pair-census-v1.json.gz",
        "atomic-results-full-v1.json.gz",
        "pair-results-full-v1.json.gz",
    }:
        raise RuntimeError("DURABLE_EVIDENCE_FILE_SET_MISMATCH")
    for relative, record in file_records.items():
        payload = (evidence_root / relative).read_bytes()
        if len(payload) != int(record["bytes"]) or sha256_bytes(payload) != record["sha256"]:
            raise RuntimeError(f"DURABLE_EVIDENCE_FILE_MISMATCH:{relative}")
        if relative.endswith(".json.gz"):
            content = gzip.decompress(payload)
            if sha256_bytes(content) != record["content_sha256"]:
                raise RuntimeError(
                    f"DURABLE_EVIDENCE_CONTENT_HASH_MISMATCH:{relative}"
                )

    core = load_gzip_json(evidence_root / "analysis-core-sanitized-v1.json.gz")
    if len(core["fixtures"]) != FIXTURE_COUNT:
        raise RuntimeError("DURABLE_CORE_FIXTURE_COUNT_MISMATCH")
    if any(
        not str(row["fixture_id"]).startswith("fixture:")
        or not str(row["home_id"]).startswith("team:")
        or not str(row["away_id"]).startswith("team:")
        or not str(row["competition_id"]).startswith("competition:")
        for row in core["fixtures"]
    ):
        raise RuntimeError("DURABLE_CORE_RAW_IDENTIFIER_DETECTED")

    mask_manifest = load_json(MASK_MANIFEST_PATH)
    bundle = load_gzip_json(evidence_root / "mask-payload-bundle-v1.json.gz")
    manifest_by_tag = {str(row["tag_id"]): row for row in mask_manifest["records"]}
    reconstructed_masks: dict[str, tuple[int, int]] = {}
    for row in bundle["records"]:
        payload = base64.b64decode(row["payload_base64"], validate=True)
        if sha256_bytes(payload) != row["payload_sha256"]:
            raise RuntimeError("DURABLE_MASK_PAYLOAD_HASH_MISMATCH")
        source = manifest_by_tag[str(row["tag_id"])]
        if row["payload_sha256"] != source["payload_sha256"]:
            raise RuntimeError("DURABLE_MASK_MANIFEST_HASH_MISMATCH")
        reconstructed_masks[str(row["tag_id"])] = parse_mask(
            payload, str(source["mask_id"])
        )
    if len(reconstructed_masks) != 80:
        raise RuntimeError("DURABLE_MASK_COUNT_MISMATCH")

    registry = load_json(TAG_REGISTRY_PATH)
    recomputed_pairs = build_eligible_pairs(reconstructed_masks, registry)
    pair_census = load_gzip_json(evidence_root / "eligible-tag-pair-census-v1.json.gz")
    if [row["pair_id"] for row in recomputed_pairs] != [
        row["pair_id"] for row in pair_census["pairs"]
    ]:
        raise RuntimeError("DURABLE_ELIGIBLE_PAIR_RECONSTRUCTION_MISMATCH")
    if len(recomputed_pairs) != 1_398:
        raise RuntimeError("DURABLE_ELIGIBLE_PAIR_COUNT_MISMATCH")

    for compact_path, full_name in (
        (ATOMIC_COMPACT_PATH, "atomic-results-full-v1.json.gz"),
        (PAIR_COMPACT_PATH, "pair-results-full-v1.json.gz"),
    ):
        compact = load_json(compact_path)
        verify_full_artifact(evidence_root / full_name, compact)
    if any(
        manifest[key] != 0
        for key in (
            "provider_calls",
            "r2_operations",
            "remote_sql_queries",
            "odds_credits",
            "triples_executed",
        )
    ):
        raise RuntimeError("DURABLE_EVIDENCE_EXTERNAL_EFFECT_MISMATCH")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--analysis-core", type=Path, required=True)
    export_parser.add_argument("--mask-source-root", type=Path, required=True)
    export_parser.add_argument("--atomic-full", type=Path, required=True)
    export_parser.add_argument("--pair-full", type=Path, required=True)
    export_parser.add_argument(
        "--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT
    )
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument(
        "--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "export":
        export(args)
    else:
        verify(args.evidence_root.resolve())


if __name__ == "__main__":
    main()
