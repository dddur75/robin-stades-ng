from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from robin.historical.readiness import build_multiseason_readiness


def _write_partition(
    state: Path,
    season: int,
    entity: str,
    records: list[dict[str, object]],
) -> None:
    path = (
        state
        / "parquet"
        / "competition=Ligue-1"
        / f"season={season}"
        / f"entity_type={entity}"
        / "dataset_version=api-football-v3"
        / "part-00000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(path, index=False)


def _observation(
    state: Path,
    *,
    payload_hash: str,
    fixture_id: int,
    season: int,
    endpoint: str,
) -> None:
    path = state / "raw" / "observations" / f"{payload_hash}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "payload_hash": payload_hash,
                "endpoint": endpoint,
                "request_parameters": {
                    "fixture": fixture_id,
                    "season": season,
                },
                "received_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _state(tmp_path: Path) -> Path:
    state = tmp_path / "historical"
    total_rows = 0
    for season in range(2020, 2025):
        fixture_records: list[dict[str, object]] = []
        player_records: list[dict[str, object]] = []
        lineup_records: list[dict[str, object]] = []
        for index, (home, away) in enumerate(((1, 2), (2, 1)), start=1):
            fixture_id = season * 10 + index
            fixture_records.append(
                {
                    "payload": json.dumps(
                        {
                            "fixture": {
                                "id": fixture_id,
                                "date": f"{season}-08-0{index}T18:00:00Z",
                                "status": {"short": "FT"},
                            },
                            "league": {"round": f"Regular Season - {index}"},
                            "teams": {
                                "home": {"id": home, "name": f"Team {home}"},
                                "away": {"id": away, "name": f"Team {away}"},
                            },
                            "goals": {"home": index, "away": 0},
                        }
                    ),
                    "raw_payload_hash": f"fixture-{fixture_id}",
                }
            )
            player_hash = hashlib.sha256(f"players-{fixture_id}".encode()).hexdigest()
            lineup_hash = hashlib.sha256(f"lineups-{fixture_id}".encode()).hexdigest()
            _observation(
                state,
                payload_hash=player_hash,
                fixture_id=fixture_id,
                season=season,
                endpoint="fixtures/players",
            )
            _observation(
                state,
                payload_hash=lineup_hash,
                fixture_id=fixture_id,
                season=season,
                endpoint="fixtures/lineups",
            )
            player_records.append(
                {
                    "payload": json.dumps(
                        {
                            "team": {"id": home},
                            "players": [
                                {
                                    "player": {"id": fixture_id},
                                    "statistics": [
                                        {"games": {"minutes": 90, "substitute": False}}
                                    ],
                                }
                            ],
                        }
                    ),
                    "raw_payload_hash": player_hash,
                }
            )
            lineup_records.append(
                {
                    "payload": json.dumps(
                        {
                            "team": {"id": home},
                            "formation": "4-3-3",
                            "startXI": [
                                {"player": {"id": fixture_id * 100 + player}}
                                for player in range(11)
                            ],
                            "substitutes": [],
                        }
                    ),
                    "raw_payload_hash": lineup_hash,
                }
            )
        _write_partition(state, season, "fixtures", fixture_records)
        _write_partition(
            state,
            season,
            "fixture_player_statistics",
            player_records,
        )
        _write_partition(state, season, "lineups", lineup_records)
        total_rows += len(fixture_records) + len(player_records) + len(lineup_records)
    quality = state / "quality" / "latest.json"
    quality.parent.mkdir(parents=True, exist_ok=True)
    quality.write_text(
        json.dumps(
            {
                "status": "PASSED",
                "normalized_rows": total_rows,
                "provenance_rows": total_rows,
                "checks": [{"check": "NO_FUTURE_DATA", "value": 0}],
            }
        ),
        encoding="utf-8",
    )
    return state


def test_all_non_injury_gates_pass_on_eligible_data(tmp_path: Path) -> None:
    report = build_multiseason_readiness(
        _state(tmp_path),
        seasons=tuple(range(2020, 2025)),
    )
    gates = report["gates"]
    assert gates["A"]["passed"] is True
    assert gates["B"]["passed"] is True
    assert gates["C"]["passed"] is True
    assert gates["D"]["status"] == "BLOCKED_BY_TEMPORALITY"
    assert report["status"] == "DATA_FACTORY_READY"


def test_stale_quality_proof_blocks_gate_a(tmp_path: Path) -> None:
    state = _state(tmp_path)
    quality = state / "quality" / "latest.json"
    payload = json.loads(quality.read_text("utf-8"))
    payload["normalized_rows"] -= 1
    payload["provenance_rows"] -= 1
    quality.write_text(json.dumps(payload), encoding="utf-8")
    report = build_multiseason_readiness(
        state,
        seasons=tuple(range(2020, 2025)),
    )
    assert report["gates"]["A"]["passed"] is False
    assert report["gates"]["A"]["provenance_complete"] is False


def test_playoff_is_excluded_from_canonical_scope(tmp_path: Path) -> None:
    state = _state(tmp_path)
    path = next(
        (
            state
            / "parquet"
            / "competition=Ligue-1"
            / "season=2020"
            / "entity_type=fixtures"
        ).rglob("*.parquet")
    )
    frame = pd.read_parquet(path)
    payload = json.loads(frame.loc[0, "payload"])
    payload["league"]["round"] = "Relegation Playoffs - Final"
    frame.loc[0, "payload"] = json.dumps(payload)
    frame.to_parquet(path, index=False)
    report = build_multiseason_readiness(
        state,
        seasons=tuple(range(2020, 2025)),
    )
    first = report["seasons"][0]
    assert first["classifications"]["PLAYOFF_EXCLUDED"] == 1
    assert report["gates"]["A"]["passed"] is False
