"""Independent reconciliation of the delivered Parquet and coverage claims."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from robin.prematch.criteria import METRICS

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports/prematch/mission036"


def test_delivered_report_identifies_the_current_calculator():
    code = ROOT / "src/robin/prematch"
    digest = hashlib.sha256(b"".join((code / name).read_bytes()
        for name in ("criteria.py", "sources.py", "export.py"))).hexdigest()
    report = json.loads((OUTPUT / "REPORT.json").read_text())
    assert report["calculator_sha256"] == digest


def test_delivered_parquets_reconcile_with_coverage_and_population():
    report = json.loads((OUTPUT / "REPORT.json").read_text())
    seen = set()
    counts = Counter()
    covered = Counter()
    reasons = Counter()
    for artifact in report["outputs"]:
        path = OUTPUT / artifact["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
        rows = pq.ParquetFile(path).read().to_pylist()
        assert len(rows) == artifact["rows"]
        for row in rows:
            assert row["season"] != 2025
            assert all(row[k] is not None and row[k] != "" for k in
                       ("fixture_id", "date", "equipe_domicile", "equipe_exterieur"))
            assert row["fixture_id"] not in seen
            seen.add(row["fixture_id"])
            for side in ("home", "away"):
                for metric in METRICS:
                    key = row["competition"], str(row["season"]), metric
                    counts[key] += 1
                    value = row[f"{metric}_{side}"]
                    reason = row[f"reason_{metric}_{side}"]
                    if value is None:
                        assert isinstance(reason, str) and reason
                        reasons[*key, reason] += 1
                    else:
                        assert reason is None
                        covered[key] += 1
                        if metric == "etat_score_buts10":
                            assert 0 <= value["minutes"] <= 900
                            assert value["buts_pour"] >= 0 and value["buts_contre"] >= 0
                        elif metric == "points_tardifs5":
                            assert -15 <= value <= 15
                        elif metric == "absents_cles":
                            assert 0 <= value <= 1
    assert len(seen) == report["target_fixtures"] == 70084
    digest = hashlib.sha256("".join(f"{i}\n" for i in sorted(seen)).encode()).hexdigest()
    assert digest == report["target_fixture_ids_sha256"]
    with (OUTPUT / "coverage.csv").open() as stream:
        coverage = list(csv.DictReader(stream))
    assert len(coverage) == len(counts)
    for row in coverage:
        key = row["competition"], row["season"], row["criterion"]
        assert int(row["total_team_rows"]) == counts[key]
        assert int(row["non_null"]) == covered[key]
        assert float(row["rate"]) == covered[key] / counts[key]
        expected = {k[-1]: n for k, n in reasons.items() if k[:3] == key}
        assert json.loads(row["null_reasons"]) == expected


def test_shifted_audit_is_non_vacuous_and_sources_exclude_holdout():
    audit = json.loads((OUTPUT / "TEMPORAL-AUDIT.json").read_text())
    assert audit["passed"] is True
    assert len(audit["comparisons"]) == audit["sampled_team_rows"] >= 100
    assert any("etat_score_buts10" in row["non_null"] for row in audit["comparisons"])
    assert any("points_tardifs5" in row["non_null"] for row in audit["comparisons"])
    assert any("cadre_suspendu" in row["non_null"] for row in audit["comparisons"])
    sources = json.loads((OUTPUT / "SOURCES.json").read_text())
    inventory = OUTPUT / sources["inventory_file"]
    assert hashlib.sha256(inventory.read_bytes()).hexdigest() == sources["inventory_sha256"]
    with inventory.open() as stream:
        records = list(csv.DictReader(stream))
    assert len(records) == sources["inventory_entries"]
    assert all(row["season"] != "2025" for row in records)
    assert all("season=2025/" not in row["path"] for row in records)
    assert all(int(row["linked_rows"]) <= int(row["rows"]) for row in records)
