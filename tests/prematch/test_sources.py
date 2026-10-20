import json
import subprocess
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from robin.prematch.sources import load_snapshot, load_targets


def repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.org"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    return tmp_path


def write(repo, entity, rows, season=2020, name="part-00000.parquet"):
    p = repo / (f"historical/parquet/competition=TEST/season={season}/"
                f"entity_type={entity}/dataset_version=api-football-v3/{name}")
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), p)


def commit(repo):
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)


def record(payload, fixture_id=None, entity="lineups"):
    return {"payload": json.dumps(payload), "provider_fixture_id": fixture_id,
            "season": 2020, "entity_type": entity}


def fixture_payload():
    return {"fixture": {"id": 1, "date": "2020-01-01T12:00:00+00:00",
                        "status": {"short": "FT"}},
            "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}},
            "score": {"fulltime": {"home": 0, "away": 0}},
            "league": {"season": 2020}}


def test_loader_joins_explicit_fixture_identity_but_not_old_unlinked_blocks(tmp_path):
    repo = repository(tmp_path)
    write(repo, "fixtures", [record(fixture_payload(), entity="fixtures")])
    xi = {"team": {"id": 1}, "startXI": [{"player": {"id": p}} for p in range(1, 12)]}
    write(repo, "lineups", [record(xi, 1), record(xi)])
    write(repo, "fixture_events", [record({"type": "Goal"}, entity="fixture_events")])
    # The holdout blob deliberately cannot be decoded as a Parquet.
    p = repo / "historical/parquet/competition=TEST/season=2025/entity_type=lineups/broken.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"MUST NEVER READ HOLDOUT")
    commit(repo)
    snapshot = load_snapshot(repo, "HEAD")
    assert snapshot.lineups[(1, 1)] == tuple(range(1, 12))
    assert snapshot.events == {}
    assert snapshot.audit["unlinked_rows"] == 2
    assert all("season=2025" not in f["path"] for f in snapshot.inventory)
    assert len(snapshot.fixtures) == 1


def test_conflicting_fixture_sources_are_quarantined(tmp_path):
    repo = repository(tmp_path)
    first = fixture_payload()
    second = fixture_payload()
    second["score"]["fulltime"]["home"] = 1
    write(repo, "fixtures", [record(first, entity="fixtures"), record(second, entity="fixtures")])
    commit(repo)
    snapshot = load_snapshot(repo, "HEAD")
    assert snapshot.fixtures == []
    assert snapshot.audit["conflicting_fixtures"] == [1]


def test_empty_per_fixture_events_are_distinct_from_missing_file(tmp_path):
    repo = repository(tmp_path)
    write(repo, "events", [], name="fixture-123.parquet")
    commit(repo)
    snapshot = load_snapshot(repo, "HEAD")
    assert snapshot.events == {123: []}
    assert snapshot.inventory[0]["rows"] == 0


def test_population_is_exact_frozen_036_and_has_no_holdout():
    root = Path(__file__).resolve().parents[2]
    targets = load_targets(root)
    assert len(targets) == len({t.fixture_id for t in targets}) == 70084
    assert all(t.season != 2025 for t in targets)
    assert len({t.competition for t in targets}) == 38


def test_invalid_source_ref_is_rejected_without_remote_access(tmp_path):
    repo = repository(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        load_snapshot(repo, "missing-ref")
