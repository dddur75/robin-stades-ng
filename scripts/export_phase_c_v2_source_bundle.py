"""Export a durable, sanitized Phase C V2 source bundle from locked E3 segments."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import platform
import sys
import zlib
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_hypothesis_tag_mask_pair_factory as v1  # noqa: E402
from scripts import run_p0_e3_capability_scale as e3  # noqa: E402

ROOT = REPO_ROOT
LOCK = ROOT / "configs/execution/phase-c-v2-source-lock.json"
DEFAULT_OUTPUT = ROOT / "reports/closure/phase-c-v2-source-evidence"
SUPPORTED_FORMATIONS = {"3-4-3", "3-5-2", "4-1-4-1", "4-2-3-1", "4-3-3", "4-4-2", "5-3-2", "5-4-1"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def validate_source_authority(v2_lock_path: Path = LOCK) -> dict[str, Any]:
    lock = read_json(v2_lock_path)
    p0_path = ROOT / str(lock["source_lock_path"])
    p0_payload = p0_path.read_bytes().replace(b"\r\n", b"\n")
    if sha256(p0_payload) != lock["source_lock_sha256_lf"]:
        raise RuntimeError("V2_P0_SOURCE_LOCK_HASH_MISMATCH")
    p0 = read_json(p0_path)
    for field in ("source_run_id", "source_run_attempt", "source_head_sha"):
        if p0[field] != lock[field]:
            raise RuntimeError(f"V2_P0_SOURCE_AUTHORITY_MISMATCH:{field}")
    if p0["inventory_manifest_sha256"] != lock["inventory_manifest_sha256"]:
        raise RuntimeError("V2_P0_INVENTORY_HASH_MISMATCH")
    if (
        p0["mission_source_bytes"] != lock["source_bytes"]
        or p0["mission_source_byte_limit"] != lock["source_byte_limit"]
    ):
        raise RuntimeError("V2_P0_SOURCE_BUDGET_MISMATCH")
    p0_artifacts = {str(row["competition"]): row for row in p0["artifacts"]}
    p0_segments = p0["segments"]
    if len(p0_artifacts) != 5 or len(p0_segments) != 5 or len(lock["segments"]) != 5:
        raise RuntimeError("V2_P0_SOURCE_CARDINALITY_MISMATCH")
    for row in lock["segments"]:
        competition = str(row["competition"])
        artifact = p0_artifacts.get(competition)
        segment = p0_segments.get(competition)
        if not isinstance(artifact, Mapping) or not isinstance(segment, Mapping):
            raise RuntimeError(f"V2_P0_SOURCE_COMPETITION_MISSING:{competition}")
        expected_artifact = (
            row["artifact_id"],
            row["artifact_size_bytes"],
            row["artifact_digest"],
        )
        actual_artifact = (
            artifact["artifact_id"],
            artifact["size_in_bytes"],
            artifact["artifact_digest"],
        )
        expected_segment = (row["segment_id"], row["row_count"], row["rows_sha256"])
        actual_segment = (
            segment["segment_id"],
            segment["row_count"],
            segment["rows_sha256"],
        )
        if expected_artifact != actual_artifact or expected_segment != actual_segment:
            raise RuntimeError(f"V2_P0_SOURCE_PROJECTION_MISMATCH:{competition}")
    return lock


def write_json(path: Path, value: object) -> dict[str, Any]:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"path": path.name, "bytes": len(payload), "sha256": sha256(payload), "content_sha256": sha256(canonical_bytes(value)), "compression": "NONE"}


def write_gzip(path: Path, value: object) -> dict[str, Any]:
    content = canonical_bytes(value)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(content)
    payload = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": path.name,
        "bytes": len(payload),
        "sha256": sha256(payload),
        "content_sha256": sha256(content),
        "compression": "GZIP_MTIME_0",
        "transport_identity": "RUNTIME_BOUND",
        "reconstruction_identity": "CANONICAL_DECOMPRESSED_CONTENT_SHA256",
        "python": platform.python_version(),
        "zlib_build": zlib.ZLIB_VERSION,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    }


def event_facts(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, int], dict[str, int | str]],
    dict[str, int],
    set[str],
    dict[str, set[int]],
]:
    grouped: dict[tuple[object, ...], set[bytes]] = defaultdict(set)
    original_counts: Counter[tuple[object, ...]] = Counter()
    canonical_rows: dict[bytes, dict[str, Any]] = {}
    for row in rows:
        if row.get("entity_type") != "fixture_event":
            continue
        event = e3._normalized_event(row)
        fixture_key = row.get("canonical_fixture_id")
        base: tuple[object, ...] = (fixture_key, event.get("team_id"), str(event.get("type") or "").casefold(), event.get("elapsed"), event.get("extra"), event.get("player_id"), event.get("assist_id"))
        payload = canonical_bytes(event)
        original_counts[base] += 1
        grouped[base].add(payload)
        canonical_rows[payload] = event
    facts: dict[tuple[str, int], dict[str, int | str]] = defaultdict(
        lambda: {
            "substitutions": 0,
            "generic_cards": 0,
            "yellow_cards": 0,
            "dismissals": 0,
            "substitutions_status": "KNOWN",
            "generic_cards_status": "KNOWN",
            "cards_status": "KNOWN",
        }
    )
    unique = 0
    substitutions = 0
    generic_cards = 0
    yellow = 0
    dismissals = 0
    invalid_fixtures: set[str] = set()
    observed_teams: dict[str, set[int]] = defaultdict(set)
    for base, values in grouped.items():
        fixture_key = base[0]
        for payload in sorted(values):
            unique += 1
            event = canonical_rows[payload]
            team = event.get("team_id")
            event_type = event.get("type")
            if not isinstance(fixture_key, str):
                raise RuntimeError("EVENT_FIXTURE_KEY_REQUIRED")
            if not isinstance(team, int):
                invalid_fixtures.add(fixture_key)
                continue
            observed_teams[fixture_key].add(team)
            row = facts[(fixture_key, team)]
            if not isinstance(event_type, str) or not event_type.strip():
                row["substitutions_status"] = "UNKNOWN_UNCLASSIFIABLE_TYPE"
                row["generic_cards_status"] = "UNKNOWN_UNCLASSIFIABLE_TYPE"
                row["cards_status"] = "UNKNOWN_UNCLASSIFIABLE_TYPE"
                continue
            kind = event_type.strip().casefold()
            if kind in {"subst", "substitution"}:
                row["substitutions"] = int(row["substitutions"]) + 1
                substitutions += 1
            if kind == "card":
                row["generic_cards"] = int(row["generic_cards"]) + 1
                generic_cards += 1
                detail = event.get("detail")
                if not isinstance(detail, str):
                    row["cards_status"] = "UNKNOWN_UNCLASSIFIABLE_DETAIL"
                    continue
                card = detail.strip().casefold()
                if card in {"yellow card", "second yellow card"}:
                    row["yellow_cards"] = int(row["yellow_cards"]) + 1
                    yellow += 1
                if card in {"red card", "second yellow card"}:
                    row["dismissals"] = int(row["dismissals"]) + 1
                    dismissals += 1
                if card not in {"yellow card", "red card", "second yellow card"}:
                    row["cards_status"] = "UNKNOWN_UNCLASSIFIABLE_DETAIL"
    return (
        dict(facts),
        {
            "scientific_event_fact_count": unique,
            "substitution_fact_count": substitutions,
            "generic_card_fact_count": generic_cards,
            "yellow_card_fact_count": yellow,
            "dismissal_fact_count": dismissals,
            "event_exact_repetitions": sum(
                original_counts[base] - len(values) for base, values in grouped.items()
            ),
        },
        invalid_fixtures,
        dict(observed_teams),
    )


def build_bundle(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    fixtures, formations, legacy_cards = v1.build_fixture_data(rows)
    events, event_counts, invalid_event_fixtures, observed_event_teams = event_facts(rows)
    event_collections: set[str] = set()
    invalid_event_collections: set[str] = set()
    for source_row in rows:
        if source_row.get("entity_type") != "fixture":
            continue
        source_fixture_key = source_row.get("canonical_fixture_id")
        data = source_row.get("data")
        if not isinstance(source_fixture_key, str) or not isinstance(data, Mapping):
            continue
        if "events" not in data:
            continue
        if isinstance(data["events"], list):
            event_collections.add(source_fixture_key)
        else:
            invalid_event_collections.add(source_fixture_key)
    fixture_ids = {fixture.fixture_id for fixture in fixtures}
    missing_event_collections = fixture_ids - event_collections
    if missing_event_collections or invalid_event_collections:
        raise RuntimeError(
            "V2_EVENT_COLLECTION_COVERAGE_MISMATCH:"
            f"{len(missing_event_collections)}:{len(invalid_event_collections)}"
        )
    formation_fact_count = sum(value is not None for value in formations.values())
    fixture_ord = {fixture.fixture_id: f"fixture:{index:04d}" for index, fixture in enumerate(fixtures, 1)}
    team_order: dict[int, str] = {}
    competition_order: dict[int, str] = {}
    for fixture in fixtures:
        if fixture.competition_id not in competition_order:
            competition_order[fixture.competition_id] = f"competition:{len(competition_order) + 1:02d}"
        for team in (fixture.home_id, fixture.away_id):
            if team not in team_order:
                team_order[team] = f"team:{len(team_order) + 1:03d}"
    universe: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    source_hashes: set[str] = set()
    for fixture in fixtures:
        source_hashes.update(fixture.source_hashes)
        fkey = fixture_ord[fixture.fixture_id]
        competition = competition_order[fixture.competition_id]
        kickoff = fixture.kickoff.isoformat()
        universe.append({"fixture_key": fkey, "competition_key": competition, "kickoff_utc": kickoff, "status": fixture.status})
        result = "HOME_WIN" if fixture.home_goals > fixture.away_goals else ("AWAY_WIN" if fixture.away_goals > fixture.home_goals else "DRAW")
        labels.append({"fixture_key": fkey, "match_result_90m": result, "total_goals_2_5_90m": "OVER" if fixture.home_goals + fixture.away_goals > 2 else "UNDER"})
        expected_event_teams = {fixture.home_id, fixture.away_id}
        event_collection_invalid = (
            fixture.fixture_id in invalid_event_fixtures
            or not observed_event_teams.get(fixture.fixture_id, set()).issubset(
                expected_event_teams
            )
        )
        for side, team, opponent, goals_for, goals_against in (("HOME", fixture.home_id, fixture.away_id, fixture.home_goals, fixture.away_goals), ("AWAY", fixture.away_id, fixture.home_id, fixture.away_goals, fixture.home_goals)):
            e = events.get(
                (fixture.fixture_id, team),
                {
                    "substitutions": 0,
                    "generic_cards": 0,
                    "yellow_cards": 0,
                    "dismissals": 0,
                    "substitutions_status": "KNOWN_EMPTY_OR_CLASSIFIED",
                    "generic_cards_status": "KNOWN_EMPTY_OR_CLASSIFIED",
                    "cards_status": "KNOWN_EMPTY_OR_CLASSIFIED",
                },
            )
            if event_collection_invalid:
                e = {
                    "substitutions": 0,
                    "generic_cards": 0,
                    "yellow_cards": 0,
                    "dismissals": 0,
                    "substitutions_status": "UNKNOWN_CONTRADICTORY_TEAM",
                    "generic_cards_status": "UNKNOWN_CONTRADICTORY_TEAM",
                    "cards_status": "UNKNOWN_CONTRADICTORY_TEAM",
                }
            raw_formation = formations.get((fixture.fixture_id, team))
            normalized = raw_formation.strip() if isinstance(raw_formation, str) else None
            formation_status = (
                "UNKNOWN_MISSING_OR_AMBIGUOUS"
                if normalized is None
                else (
                    "KNOWN_SELECTED_CATEGORY"
                    if normalized in SUPPORTED_FORMATIONS
                    else "KNOWN_OTHER_CATEGORY"
                )
            )
            facts.append({
                "fixture_key": fkey, "competition_key": competition,
                "team_key": team_order[team], "opponent_key": team_order[opponent],
                "side": side, "kickoff_utc": kickoff,
                "availability_proxy_at": (fixture.kickoff + timedelta(hours=6)).isoformat(),
                "settlement_status": fixture.status,
                "result": "WIN" if goals_for > goals_against else ("LOSS" if goals_for < goals_against else "DRAW"),
                "points": 3 if goals_for > goals_against else (1 if goals_for == goals_against else 0),
                "goals_for": goals_for, "goals_against": goals_against,
                "substitutions": int(e["substitutions"]) if str(e["substitutions_status"]).startswith("KNOWN") else None,
                "substitutions_status": str(e["substitutions_status"]),
                "legacy_generic_cards": legacy_cards.get((fixture.fixture_id, team), 0),
                "legacy_generic_cards_status": "KNOWN_V1_CANONICAL_EVENT_IDENTITY",
                "generic_cards": int(e["generic_cards"]) if str(e["generic_cards_status"]).startswith("KNOWN") else None,
                "generic_cards_status": str(e["generic_cards_status"]),
                "yellow_cards": int(e["yellow_cards"]) if str(e["cards_status"]).startswith("KNOWN") else None,
                "dismissals": int(e["dismissals"]) if str(e["cards_status"]).startswith("KNOWN") else None,
                "cards_status": str(e["cards_status"]),
                "formation": normalized if formation_status.startswith("KNOWN") else None,
                "formation_status": formation_status,
            })
    facts.sort(key=lambda row: (str(row["kickoff_utc"]), str(row["fixture_key"]), str(row["side"])))
    labels.sort(key=lambda row: str(row["fixture_key"]))
    universe.sort(key=lambda row: str(row["fixture_key"]))
    counts = dict(event_counts)
    counts.update(
        {
            "normalized_row_count": len(rows),
            "scientific_fixture_count": len(fixtures),
            "team_fixture_count": len(facts),
            "event_collection_count": len(event_collections),
            "formation_fact_count": formation_fact_count,
            "legacy_generic_card_fact_count": sum(legacy_cards.values()),
            "target_label_count": len(labels),
            "team_ordinal_count": len(team_order),
            "competition_ordinal_count": len(competition_order),
            "source_content_hash_count": len(source_hashes),
        }
    )
    return universe, facts, labels, counts


def export(source_root: Path, output_root: Path) -> dict[str, Any]:
    lock = validate_source_authority()
    rows = v1.load_rows(source_root)
    universe, facts, labels, counts = build_bundle(rows)
    expected = {
        key: lock[key]
        for key in (
            "normalized_row_count",
            "scientific_fixture_count",
            "team_fixture_count",
            "event_collection_count",
            "formation_fact_count",
            "scientific_event_fact_count",
            "substitution_fact_count",
            "yellow_card_fact_count",
            "dismissal_fact_count",
        )
    }
    expected["generic_card_fact_count"] = lock["generic_card_fact_count"]
    expected["legacy_generic_card_fact_count"] = lock["legacy_generic_card_fact_count"]
    for key, value in expected.items():
        if counts.get(key) != value:
            raise RuntimeError(f"V2_SOURCE_COUNT_MISMATCH:{key}:{counts.get(key)}:{value}")
    records = [
        write_gzip(output_root / "fixture-universe-v2.json.gz", {"schema_version": "phase-c-v2-fixture-universe", "records": universe}),
        write_gzip(output_root / "target-labels-v2.json.gz", {"schema_version": "phase-c-v2-target-labels", "records": labels}),
    ]
    competition_keys = sorted({str(row["competition_key"]) for row in facts})
    for competition_key in competition_keys:
        suffix = competition_key.split(":", 1)[1]
        shard = [row for row in facts if row["competition_key"] == competition_key]
        records.append(
            write_gzip(
                output_root / f"team-match-facts-competition-{suffix}-v2.json.gz",
                {
                    "schema_version": "phase-c-v2-team-match-facts",
                    "competition_key": competition_key,
                    "records": shard,
                },
            )
        )
    manifest = {
        "schema_version": "phase-c-v2-source-evidence-manifest", "source_lock_sha256": sha256(LOCK.read_bytes()),
        "source_run_id": lock["source_run_id"], "source_run_attempt": lock["source_run_attempt"],
        "source_head_sha": lock["source_head_sha"], "point_in_time_source_provenance": False,
        "availability_proxy": "PRIOR_FIXTURE_KICKOFF_PLUS_PT6H", "targets_physically_separate": True,
        "raw_provider_ids_committed": False, "reverse_ordinal_map_committed": False,
        "counts": counts, "team_match_shard_count": len(competition_keys),
        "files": sorted(records, key=lambda row: str(row["path"])),
    }
    manifest["manifest_hash"] = v1.object_hash(manifest)
    write_json(output_root / "source-evidence-manifest-v2.json", manifest)
    receipt = {"schema_version": "phase-c-v2-source-export-receipt", "manifest_hash": manifest["manifest_hash"], "double_export_required": True, "provider_calls": 0, "r2_gets": 0, "remote_sql": 0, "odds_credits": 0, "manual_deployments": 0, "triples": 0}
    write_json(output_root / "source-export-receipt-v2.json", receipt)
    return manifest


def replay(first_root: Path, second_root: Path, output_root: Path) -> dict[str, Any]:
    first_manifest = verify(first_root)
    second_manifest = verify(second_root)
    if canonical_bytes(first_manifest) != canonical_bytes(second_manifest):
        raise RuntimeError("V2_SOURCE_REPLAY_MANIFEST_MISMATCH")
    excluded = {"source-export-replay-v2.json"}
    first_files = sorted(
        path.name for path in first_root.iterdir() if path.is_file() and path.name not in excluded
    )
    second_files = sorted(
        path.name for path in second_root.iterdir() if path.is_file() and path.name not in excluded
    )
    if first_files != second_files:
        raise RuntimeError("V2_SOURCE_REPLAY_FILE_SET_MISMATCH")
    compared: list[dict[str, object]] = []
    for name in first_files:
        first_payload = (first_root / name).read_bytes()
        second_payload = (second_root / name).read_bytes()
        if first_payload != second_payload:
            raise RuntimeError(f"V2_SOURCE_REPLAY_BYTES_MISMATCH:{name}")
        compared.append({"path": name, "bytes": len(first_payload), "sha256": sha256(first_payload)})
    record = {
        "schema_version": "phase-c-v2-source-export-replay",
        "manifest_hash": first_manifest["manifest_hash"],
        "replay_runs": 2,
        "replay_identical": True,
        "compared_file_count": len(compared),
        "files": compared,
        "additional_network_reads": 0,
        "provider_calls": 0,
        "r2_gets": 0,
        "remote_sql": 0,
        "odds_credits": 0,
        "manual_deployments": 0,
        "triples": 0,
    }
    write_json(output_root / "source-export-replay-v2.json", record)
    return record


def verify(output_root: Path) -> dict[str, Any]:
    lock = validate_source_authority()
    manifest = read_json(output_root / "source-evidence-manifest-v2.json")
    declared_manifest_hash = manifest.get("manifest_hash")
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("manifest_hash", None)
    if declared_manifest_hash != v1.object_hash(manifest_without_hash):
        raise RuntimeError("V2_SOURCE_MANIFEST_HASH_MISMATCH")
    if manifest.get("source_lock_sha256") != sha256(LOCK.read_bytes()):
        raise RuntimeError("V2_SOURCE_LOCK_HASH_MISMATCH")
    if any(
        manifest.get(field) != lock[field]
        for field in ("source_run_id", "source_run_attempt", "source_head_sha")
    ):
        raise RuntimeError("V2_SOURCE_AUTHORITY_MISMATCH")
    for raw in manifest.get("files", []):
        if not isinstance(raw, Mapping):
            raise TypeError("V2_SOURCE_FILE_RECORD_REQUIRED")
        path = output_root / str(raw["path"])
        payload = path.read_bytes()
        if len(payload) != raw["bytes"] or sha256(payload) != raw["sha256"]:
            raise RuntimeError(f"V2_SOURCE_TRANSPORT_HASH_MISMATCH:{path.name}")
        with gzip.open(path, "rb") as stream:
            content = stream.read()
        if sha256(content) != raw["content_sha256"]:
            raise RuntimeError(f"V2_SOURCE_CONTENT_HASH_MISMATCH:{path.name}")
        decoded = json.loads(content)
        text = json.dumps(decoded, ensure_ascii=False)
        for forbidden in ("provider_fixture_id", "provider_team_id", "canonical_fixture_id", "canonical_team_id", "source_payload_hash", "C:\\\\", "/tmp/"):
            if forbidden in text:
                raise RuntimeError(f"V2_SOURCE_SANITIZATION_MISMATCH:{path.name}:{forbidden}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "verify", "replay"))
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--first-root", type=Path)
    parser.add_argument("--second-root", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "export":
        if args.source_root is None:
            raise RuntimeError("V2_SOURCE_ROOT_REQUIRED")
        export(args.source_root.resolve(), args.output_root.resolve())
    elif args.command == "verify":
        verify(args.output_root.resolve())
    else:
        if args.first_root is None or args.second_root is None:
            raise RuntimeError("V2_SOURCE_REPLAY_ROOTS_REQUIRED")
        replay(
            args.first_root.resolve(),
            args.second_root.resolve(),
            args.output_root.resolve(),
        )


if __name__ == "__main__":
    main()
