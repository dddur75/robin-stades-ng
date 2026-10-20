import csv
import json
from dataclasses import replace

import pyarrow.parquet as pq

from robin.prematch.export import export_snapshot
from robin.prematch.sources import Snapshot, Target
from tests.prematch.test_criteria import pack


def test_export_preserves_denominators_null_reasons_and_parquet_schema(tmp_path):
    fixtures, players, lineups, events = pack()
    snapshot = Snapshot("a" * 40, fixtures, players, lineups, events)
    targets = [Target(f.fixture_id, f.competition, f.season) for f in fixtures]
    targets.append(Target(999, "MISSING", 2020, "2020-12-01", "Home", "Away"))
    report = export_snapshot(snapshot, targets, tmp_path)
    table = pq.ParquetFile(tmp_path / "season=2020.parquet").read()
    rows = table.to_pylist()
    assert len(rows) == len(targets) == 13
    assert len({r["fixture_id"] for r in rows}) == len(rows)
    missing = next(r for r in rows if r["fixture_id"] == 999)
    assert missing["equipe_domicile"] == "Home"
    assert missing["points_tardifs5_home"] is None
    assert missing["reason_points_tardifs5_home"] == "fixture_context_missing"
    covered = next(r for r in rows if r["fixture_id"] == 10)
    assert covered["etat_score_buts10_home"]["minutes"] == 900
    assert covered["points_tardifs5_home"] == 0
    assert covered["source_compo_home"] == "feuille_officielle"
    coverage = list(csv.DictReader((tmp_path / "coverage.csv").open()))
    cell = next(r for r in coverage if r["competition"] == "TEST" and r["criterion"] == "points_tardifs5")
    assert int(cell["total_team_rows"]) == 24
    assert int(cell["non_null"]) == 14
    assert float(cell["rate"]) == 14 / 24
    assert report["temporal_audit"]["passed"] is True
    assert report["temporal_audit"]["sampled_team_rows"] > 0
    assert report["outputs"][0]["rows"] == 13
    assert "MISSING | 2020" in (tmp_path / "COVERAGE.md").read_text()


def test_incomplete_fixture_calendar_prevents_skipping_missing_target(tmp_path):
    fixtures, players, lineups, events = pack()
    targets = [Target(f.fixture_id, f.competition, f.season) for f in fixtures]
    targets.append(Target(999, "TEST", 2020))
    snapshot = Snapshot("a" * 40, fixtures, players, lineups, events)
    export_snapshot(snapshot, targets, tmp_path)
    rows = pq.ParquetFile(tmp_path / "season=2020.parquet").read().to_pylist()
    assert all(r["points_tardifs5_home"] is None for r in rows)
    assert rows[10]["reason_points_tardifs5_home"] == "fixture_calendar_incomplete"


def test_deterministic_exports_and_lagged_real_sample(tmp_path):
    fixtures, players, lineups, events = pack()
    fixtures[-1] = replace(fixtures[-1], season=2021)
    snapshot = Snapshot("a" * 40, fixtures, players, lineups, events)
    targets = [Target(f.fixture_id, f.competition, f.season) for f in fixtures]
    a = export_snapshot(snapshot, targets, tmp_path / "a")
    b = export_snapshot(snapshot, targets, tmp_path / "b")
    assert a == b
    assert (tmp_path / "a/season=2020.parquet").read_bytes() == (tmp_path / "b/season=2020.parquet").read_bytes()
    assert json.loads((tmp_path / "a/REPORT.json").read_text())["temporal_audit"]["passed"]
