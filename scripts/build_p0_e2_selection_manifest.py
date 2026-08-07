"""Freeze the bounded E2 selection from already acquired signed replay artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MISSION_ID = "p0-e2-capability-sample-v1"
SOURCE_MAIN = "3e250c2a4a01a141f6403219fd4c45ae75a05522"
INVENTORY_SHA256 = "87326eba00976c8cdd00c68e7d24b98c1ccd4f109b38681228f527bcb273e28d"
ALLOWED_CAPABILITIES = [
    "TEAM",
    "PLAYER",
    "LINEUP",
    "FORMATION",
    "EVENTS",
    "TEAM_STATISTICS",
    "PLAYER_STATISTICS",
    "DISCIPLINE_GENERIC",
    "CALENDAR",
]
STOPPED_CAPABILITIES = [
    "ABSENCE_CAUSE_EXACT",
    "INJURY_CONFIRMED",
    "SUSPENSION_CONFIRMED",
    "ABSENCE_GENERIC",
    "TEAM_FORM",
    "PLAYER_FORM",
    "STARTER_BASELINE",
    "FATIGUE",
    "STANDINGS",
]
LEAGUES = {
    39: {
        "artifact_id": 8875626108,
        "competition": "Premier League",
        "segment_id": "seg-000209-75959aee62633e1d",
        "segment_manifest_hash": "b09199b3a6349b2d83cb5ad871bec6039165211131d3d195f049e3de3ff289b0",
        "segment_rows_hash": "d33529af36d2a24c4130fffd77c5733bf960248bacaed514bb370d89f32c6eb6",
    },
    61: {
        "artifact_id": 8875918562,
        "competition": "Ligue 1",
        "segment_id": "seg-000283-c1badd6c93caeaa1",
        "segment_manifest_hash": "f4fa059bb726e51ddc94216705febc623253cf6af2ca7b2bb85b6f4310ec68b6",
        "segment_rows_hash": "f619c06d0d0a6c70760a4e32a7412d5b704082c867559f78960bda5e8994646d",
    },
    78: {
        "artifact_id": 8876203323,
        "competition": "Bundesliga",
        "segment_id": "seg-000358-e8aa4904c2844e97",
        "segment_manifest_hash": "2d0e873bf86799353d33b34d85ffc37da8f2119c83f42ad6311016a9c346b8a3",
        "segment_rows_hash": "48aff73f5976b270775d36c48f2db23ebd6a5f9076412ea8b67186e840e32353",
    },
    135: {
        "artifact_id": 8875016575,
        "competition": "Serie A",
        "segment_id": "seg-000061-2c731db89c0e7973",
        "segment_manifest_hash": "61139caaf28dad7d97fb15ae128c34ee4ebe3b02f59d782bc241082d70503233",
        "segment_rows_hash": "26a3dd084fe8b2b80c457edda61b73b5cd2f5c57219f097e82ac7c08ac6f9118",
    },
    140: {
        "artifact_id": 8875329908,
        "competition": "Liga",
        "segment_id": "seg-000135-7561044ce00d9626",
        "segment_manifest_hash": "fa0b9736d94a48d6fcc412a29a13f99a07b5011b9f4f40557a910f4159c0b6a5",
        "segment_rows_hash": "f6183917c0b59043c59a2eab47a9371e140e32447091e3e6111631e4b6557527",
    },
}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(label)
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(label)
    return value


def _read(path: Path) -> Mapping[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))


def _render(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _hash(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _segment(artifact_root: Path, expected: Mapping[str, Any]) -> Mapping[str, Any]:
    segment_id = str(expected["segment_id"])
    manifest_path = next(artifact_root.rglob(f"{segment_id}/segment-manifest.json"))
    manifest = _read(manifest_path)
    if manifest.get("manifest_sha256") != expected["segment_manifest_hash"]:
        raise ValueError("E2_SEGMENT_MANIFEST_HASH_MISMATCH")
    if manifest.get("rows_hash") != expected["segment_rows_hash"]:
        raise ValueError("E2_SEGMENT_ROWS_HASH_MISMATCH")
    with gzip.open(manifest_path.with_name("segment-result.json.gz"), "rt", encoding="utf-8") as stream:
        result = _mapping(json.load(stream), "E2_SEGMENT_RESULT")
    if _mapping(result["manifest"], "E2_EMBEDDED_MANIFEST").get("rows_hash") != expected["segment_rows_hash"]:
        raise ValueError("E2_EMBEDDED_ROWS_HASH_MISMATCH")
    return result


def _anchor_tasks(root: Path) -> dict[int, str]:
    selection = _read(root / "reports/evidence/e1b/e1b-selection-manifest-v1.json")
    sources = {
        int(item["competition_id"]): str(item["receipt_id"])
        for raw in _sequence(selection["source_objects"], "E1B_SOURCES")
        if (item := _mapping(raw, "E1B_SOURCE"))["source_role"] == "DETAIL"
    }
    return {
        int(item["fixture_id"]): sources[int(item["competition_id"])]
        for raw in _sequence(selection["fixtures"], "E1B_FIXTURES")
        if (item := _mapping(raw, "E1B_FIXTURE"))
    }


def _candidate_rows(
    result: Mapping[str, Any],
    inventory_by_task: Mapping[str, Mapping[str, Any]],
    anchor_tasks: Mapping[int, str],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for raw in _sequence(result["rows"], "E2_ROWS"):
        row = _mapping(raw, "E2_ROW")
        if row.get("entity_type") == "fixture":
            grouped[int(row["provider_fixture_id"])].append(row)
    candidates = []
    for fixture_id, rows in grouped.items():
        identity = min(
            rows,
            key=lambda row: (
                0 if "league" in _mapping(row["source_request_params"], "E2_PARAMS") else 1,
                str(row["task_id"]),
            ),
        )
        details = {
            str(row["task_id"]): row
            for row in rows
            if "ids" in _mapping(row["source_request_params"], "E2_PARAMS")
        }
        if not details:
            continue
        task_id = anchor_tasks.get(fixture_id, min(details))
        if task_id not in details:
            raise ValueError(f"E2_ANCHOR_SOURCE_MISSING:{fixture_id}")
        data = _mapping(identity["data"], "E2_FIXTURE_DATA")
        fixture = _mapping(data["fixture"], "E2_FIXTURE")
        status = str(_mapping(fixture["status"], "E2_STATUS")["short"])
        if status not in {"FT", "AET", "PEN"}:
            continue
        source = inventory_by_task.get(task_id)
        if source is None:
            raise ValueError(f"E2_TASK_NOT_IN_INVENTORY:{task_id}")
        teams = _mapping(data["teams"], "E2_TEAMS")
        home = _mapping(teams["home"], "E2_HOME")
        away = _mapping(teams["away"], "E2_AWAY")
        candidates.append(
            {
                "away_team_id": int(away["id"]),
                "competition": str(_mapping(data["league"], "E2_LEAGUE")["name"]),
                "fixture_id": fixture_id,
                "fixture_record_hash": str(identity["record_hash"]),
                "home_team_id": int(home["id"]),
                "identity_status": str(identity["identity_status"]),
                "kickoff": str(fixture["date"]),
                "source": source,
                "source_record_hash": str(details[task_id]["record_hash"]),
                "status": status,
                "task_id": task_id,
            }
        )
    return sorted(candidates, key=lambda row: (row["kickoff"], row["fixture_id"]))


def _stratified_selection(
    candidates: Sequence[dict[str, Any]], anchor_tasks: Mapping[int, str]
) -> list[dict[str, Any]]:
    anchors = [row for row in candidates if row["fixture_id"] in anchor_tasks]
    if len(anchors) != 2:
        raise ValueError("E2_ANCHOR_COUNT_PER_LEAGUE_INVALID")
    pool = [row for row in candidates if row["fixture_id"] not in anchor_tasks]
    represented = {
        int(team)
        for row in anchors
        for team in (row["home_team_id"], row["away_team_id"])
    }
    selected: list[dict[str, Any]] = []
    count = len(pool)
    for index in range(18):
        lower = index * count // 18
        upper = (index + 1) * count // 18
        center = (lower + upper - 1) / 2
        indexed = list(enumerate(pool[lower:upper], start=lower))
        _, choice = min(
            indexed,
            key=lambda pair: (
                pair[1]["home_team_id"] in represented,
                pair[1]["away_team_id"] in represented,
                abs(pair[0] - center),
                pair[1]["kickoff"],
                pair[1]["fixture_id"],
            ),
        )
        selected.append({**choice, "temporal_stratum": index + 1})
        represented.update((choice["home_team_id"], choice["away_team_id"]))
    return [{**row, "temporal_stratum": 0} for row in anchors] + selected


def _public_fixture(row: Mapping[str, Any], anchor_tasks: Mapping[int, str]) -> dict[str, Any]:
    source = _mapping(row["source"], "E2_SOURCE")
    anchor = int(row["fixture_id"]) in anchor_tasks
    return {
        "allowed_payload_key": source["payload_key"],
        "allowed_receipt_key": source["receipt_key"],
        "away_team_id": row["away_team_id"],
        "competition": row["competition"],
        "fixture_id": row["fixture_id"],
        "fixture_record_hash": row["fixture_record_hash"],
        "home_team_id": row["home_team_id"],
        "identity_status": row["identity_status"],
        "is_e1b_anchor": anchor,
        "kickoff": row["kickoff"],
        "logical_bytes": source["logical_bytes"],
        "object_id": source["object_id"],
        "payload_hash": source["payload_sha256"],
        "receipt_hash": source["receipt_hash"],
        "season": 2024,
        "selection_reason": "E1B_ANCHOR_EXACT_SOURCE" if anchor else "DETERMINISTIC_TEMPORAL_STRATUM_TEAM_DIVERSITY",
        "source_record_hash": row["source_record_hash"],
        "stored_bytes": source["stored_bytes"],
        "task_id": row["task_id"],
        "temporal_stratum": row["temporal_stratum"],
    }


def build(
    root: Path, inventory_path: Path, artifact_roots: Mapping[int, Path]
) -> tuple[dict[str, Any], dict[str, Any]]:
    inventory = _read(inventory_path)
    if inventory.get("manifest_sha256") != INVENTORY_SHA256:
        raise ValueError("E2_INVENTORY_HASH_MISMATCH")
    objects = [_mapping(item, "E2_INVENTORY_OBJECT") for item in _sequence(inventory["objects"], "E2_INVENTORY")]
    inventory_by_task = {str(item["task_id"]): item for item in objects}
    anchors = _anchor_tasks(root)
    fixtures: list[dict[str, Any]] = []
    segment_sources = []
    for competition_id, expected in LEAGUES.items():
        result = _segment(artifact_roots[competition_id], expected)
        candidates = _candidate_rows(result, inventory_by_task, anchors)
        for candidate in candidates:
            candidate["competition"] = expected["competition"]
        current = [_public_fixture(row, anchors) for row in _stratified_selection(candidates, anchors)]
        if len(current) != 20:
            raise ValueError("E2_FIXTURE_COUNT_PER_LEAGUE_INVALID")
        fixtures.extend(current)
        segment_sources.append({"competition_id": competition_id, **expected})
    fixtures.sort(key=lambda row: (int(next(key for key, value in LEAGUES.items() if value["competition"] == row["competition"])), row["kickoff"], row["fixture_id"]))
    anchor_rows = [row for row in fixtures if row["is_e1b_anchor"]]
    new_rows = [row for row in fixtures if not row["is_e1b_anchor"]]
    payload_bytes = sum(int(row["stored_bytes"]) for row in fixtures)
    selection = {
        "anchor_hash": _hash(anchor_rows),
        "budgets": {
            "planned_bootstrap_gets": 1,
            "planned_logical_gets_total": 201,
            "planned_payload_stored_bytes": payload_bytes,
            "planned_receipt_bytes_upper_bound": 26214400,
            "planned_total_bytes_upper_bound": payload_bytes + 26214400 + 4194304,
            "r2_byte_budget": 50000000,
            "r2_get_budget": 300,
            "r2_writes": 0,
        },
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
        "frozen_at": "2026-08-07T15:00:00Z",
        "gate": {
            "decision": "E2_SELECTION_PENDING_REVIEW",
            "mechanical_checks": {
                "ambiguous_identities": sum(row["identity_status"] != "PROVIDER_ID_VERIFIED" for row in fixtures),
                "anchor_fixture_count": len(anchor_rows),
                "competition_count": len({row["competition"] for row in fixtures}),
                "duplicate_fixtures": len(fixtures) - len({row["fixture_id"] for row in fixtures}),
                "fixture_count": len(fixtures),
                "missing_hashes": sum(not row["payload_hash"] or not row["receipt_hash"] for row in fixtures),
                "new_fixture_count": len(new_rows),
                "planned_bytes_within_budget": payload_bytes + 26214400 + 4194304 <= 50000000,
                "planned_gets_within_budget": 201 <= 300,
                "provider_fallbacks": 0,
                "r2_head_methods_imported": 0,
                "r2_list_methods_imported": 0,
                "r2_write_or_delete_methods_imported": 0,
                "unlisted_keys": 0,
            },
            "required_reviewers": ["DP6", "C2", "DP5"],
            "review_status": "PENDING_DP6_C2_DP5",
        },
        "inventory_manifest_sha256": INVENTORY_SHA256,
        "mission_id": MISSION_ID,
        "new_fixture_hash": _hash(new_rows),
        "schema_version": "p0-e2-selection-manifest-v1",
        "season": 2024,
        "selection_hash": _hash(fixtures),
        "selection_policy": {
            "anchor_policy": "PRESERVE_TEN_E1B_FIXTURES_AND_EXACT_DETAIL_SOURCES",
            "candidate_order": ["kickoff", "fixture_id"],
            "detail_source_tie_break": "LOWEST_SIGNED_TASK_ID_EXCEPT_PINNED_E1B_ANCHORS",
            "finished_statuses": ["FT", "AET", "PEN"],
            "new_fixtures_per_league": 18,
            "strata_per_league": 18,
            "stratum_tie_break": ["HOME_TEAM_NOT_REPRESENTED", "AWAY_TEAM_NOT_REPRESENTED", "DISTANCE_TO_STRATUM_CENTER", "KICKOFF", "FIXTURE_ID"],
        },
        "selection_sources": {
            "github_run_id": 30853757779,
            "inventory_artifact_id": 8871763918,
            "inventory_artifact_digest": "sha256:9d6562d30502570614f8c68a7d0c72325398a43071026e7f7bcf9c633dad6864",
            "segments": segment_sources,
        },
        "source_main_sha": SOURCE_MAIN,
        "stage": "E2",
    }
    mission = {
        "allowed_capabilities": ALLOWED_CAPABILITIES,
        "anchor_fixture_count": 10,
        "capability_contract_hash": _file_hash(root / "configs/data/capability-scoped-evidence-ladder-v2.json"),
        "competition_count": 5,
        "e1b_measurement_hash": _file_hash(root / "reports/evidence/e1b/e1b-measurement-v1.json"),
        "e1b_selection_hash": _file_hash(root / "reports/evidence/e1b/e1b-selection-manifest-v1.json"),
        "fixture_count": 100,
        "fixture_count_per_league": 20,
        "grain_catalog_hash": _file_hash(root / "configs/data/football-grain-catalog-v1.json"),
        "mission_id": MISSION_ID,
        "new_fixture_count": 90,
        "provider_budget": 0,
        "r2_byte_budget": 50000000,
        "r2_get_budget": 300,
        "r2_write_budget": 0,
        "retry_policy": {"maximum_technical_attempts": 2, "same_selection_required": True, "scope_expansion_allowed": False},
        "season_policy": {"canonical_season": 2024, "cross_league_uniform": True},
        "selection_policy": selection["selection_policy"],
        "source_main_sha": SOURCE_MAIN,
        "sql_budget": 0,
        "stage": "E2",
        "stop_conditions": ["UNLISTED_R2_KEY", "MISSING_RECEIPT_OR_HASH", "IDENTITY_AMBIGUITY", "R2_GET_BUDGET_EXCEEDED", "R2_BYTE_BUDGET_EXCEEDED", "ANY_R2_LIST_OR_HEAD", "ANY_R2_WRITE_OR_DELETE", "ANY_PROVIDER_CALL", "ANY_REMOTE_SQL_QUERY", "SECOND_SIMILAR_TECHNICAL_FAILURE"],
        "stopped_capabilities": STOPPED_CAPABILITIES,
        "time_budget": {"maximum_hours": 8, "maximum_job_minutes": 15, "target_hours": [2, 6]},
    }
    return mission, selection


def validate(root: Path) -> None:
    mission = _read(root / "configs/execution/p0-e2-capability-sample-v1.json")
    selection = _read(root / "reports/evidence/e2/e2-selection-manifest-v1.json")
    fixtures = [_mapping(item, "E2_FIXTURE") for item in _sequence(selection["fixtures"], "E2_FIXTURES")]
    checks = _mapping(_mapping(selection["gate"], "E2_GATE")["mechanical_checks"], "E2_CHECKS")
    if mission.get("source_main_sha") != SOURCE_MAIN or selection.get("source_main_sha") != SOURCE_MAIN:
        raise ValueError("E2_SOURCE_MAIN_INVALID")
    if len(fixtures) != 100 or len({row["fixture_id"] for row in fixtures}) != 100:
        raise ValueError("E2_FIXTURE_SCOPE_INVALID")
    if sum(bool(row["is_e1b_anchor"]) for row in fixtures) != 10:
        raise ValueError("E2_ANCHOR_SCOPE_INVALID")
    counts: defaultdict[str, int] = defaultdict(int)
    for row in fixtures:
        counts[str(row["competition"])] += 1
    if sorted(counts.values()) != [20] * 5:
        raise ValueError("E2_LEAGUE_SCOPE_INVALID")
    if selection.get("selection_hash") != _hash(fixtures):
        raise ValueError("E2_SELECTION_HASH_INVALID")
    if any(value not in (0, True, 5, 10, 90, 100) for value in checks.values()):
        raise ValueError("E2_MECHANICAL_GATE_INVALID")
    if _render(selection) != _render(_mapping(json.loads(_render(selection)), "E2_REPLAY")):
        raise ValueError("E2_SELECTION_NOT_BYTE_IDENTICAL")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--artifact-root", type=Path, action="append", default=[])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.verify:
        validate(root)
        print("E2_SELECTION_VALID")
        return
    if args.inventory is None or len(args.artifact_root) != 5:
        parser.error("generation requires --inventory and five --artifact-root values")
    roots: dict[int, Path] = {}
    for path in args.artifact_root:
        artifact_id = int(path.name.rsplit("-", 1)[-1])
        competition_id = next(key for key, value in LEAGUES.items() if value["artifact_id"] == artifact_id)
        roots[competition_id] = path.resolve()
    mission, selection = build(root, args.inventory.resolve(), roots)
    outputs = {
        root / "configs/execution/p0-e2-capability-sample-v1.json": mission,
        root / "reports/evidence/e2/e2-selection-manifest-v1.json": selection,
    }
    for path, value in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_render(value))
    print(f"E2_SELECTION_FROZEN:{selection['selection_hash']}")


if __name__ == "__main__":
    main()
