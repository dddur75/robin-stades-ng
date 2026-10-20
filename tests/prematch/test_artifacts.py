"""Independent reconciliation of the delivered Parquet and coverage claims."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import pytest

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
    audit = json.loads((OUTPUT / "TEMPORAL-AUDIT.json").read_text())
    audited = {(row["fixture_id"], row["team_id"]): row for row in audit["comparisons"]}
    matched_audits = set()
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
                        if metric in {"absents_cles", "force_xi"}:
                            assert row[f"source_compo_{side}"] == "feuille_officielle"
                        if metric == "etat_score_buts10":
                            assert 0 <= value["minutes"] <= 900
                            assert value["buts_pour"] >= 0 and value["buts_contre"] >= 0
                        elif metric == "points_tardifs5":
                            assert -15 <= value <= 15
                        elif metric == "absents_cles":
                            assert 0 <= value <= 1
                audit_key = row["fixture_id"], row[f"{side}_team_id"]
                if audit_key in audited:
                    values = {m: row[f"{m}_{side}"] for m in METRICS}
                    assert set(audited[audit_key]["non_null"]) == {
                        m for m in METRICS if values[m] is not None}
                    values["reasons"] = {m: row[f"reason_{m}_{side}"] for m in METRICS
                                         if values[m] is None}
                    for extra in ("source_compo", "history_count", "cong21_observe", "repos_jours_observe"):
                        values[extra] = row[f"{extra}_{side}"]
                    encoded = json.dumps(values, sort_keys=True, ensure_ascii=False,
                                         indent=2, allow_nan=False) + "\n"
                    assert hashlib.sha256(encoded.encode()).hexdigest() == audited[audit_key]["result_sha256"]
                    matched_audits.add(audit_key)
    assert len(seen) == report["target_fixtures"] == 70084
    assert len(matched_audits) == len(audited) == audit["sampled_team_rows"]
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


def test_catchup_delivers_attachment_and_non_vacuous_xi():
    report = json.loads((OUTPUT / "REPORT.json").read_text())
    assert report["contexts"].get("fixture_context_present", 0) / report["target_fixtures"] >= 0.9
    with (OUTPUT / "coverage.csv").open() as stream:
        coverage = list(csv.DictReader(stream))
    audit = json.loads((OUTPUT / "TEMPORAL-AUDIT.json").read_text())
    audited = {metric for row in audit["comparisons"] for metric in row["non_null"]}
    assert sum(int(row["non_null"]) for row in coverage if row["criterion"] == "force_xi") > 0
    assert "force_xi" in audited


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Abs non-null goal unmet: historical minutes incomplete; ABSENCE-SOURCE-GAP.json")
def test_real_archive_absence_non_null_goal():
    with (OUTPUT / "coverage.csv").open() as stream:
        coverage = list(csv.DictReader(stream))
    audit = json.loads((OUTPUT / "TEMPORAL-AUDIT.json").read_text())
    assert sum(int(row["non_null"]) for row in coverage if row["criterion"] == "absents_cles") > 0
    assert any("absents_cles" in row["non_null"] for row in audit["comparisons"])


def test_absence_source_gap_matches_delivered_values_and_explicit_partial_status():
    gap = json.loads((OUTPUT / "ABSENCE-SOURCE-GAP.json").read_text())
    report = json.loads((OUTPUT / "REPORT.json").read_text())
    reasons, official = Counter(), Counter()
    non_null = 0
    for artifact in report["outputs"]:
        columns = [f"{prefix}_{side}" for side in ("home", "away")
                   for prefix in ("absents_cles", "reason_absents_cles", "source_compo")]
        for row in pq.ParquetFile(OUTPUT / artifact["path"]).read(columns=columns).to_pylist():
            for side in ("home", "away"):
                value, reason = row[f"absents_cles_{side}"], row[f"reason_absents_cles_{side}"]
                if value is None:
                    reasons[reason] += 1
                    if row[f"source_compo_{side}"] == "feuille_officielle":
                        official[reason] += 1
                else:
                    non_null += 1
    assert gap["source_revision"] == report["source_revision"]
    assert gap["absents_cles_non_null"] == non_null
    assert gap["null_reasons_all_team_rows"] == dict(reasons)
    assert gap["null_reasons_official_xi_team_rows"] == dict(official)
    if non_null == 0:
        assert report["status"] == "PARTIAL"
        assert gap["status"] == "PARTIAL_SOURCE_GAP_ABSENCE_NON_NULL_GOAL_NOT_MET"
        assert set(official) <= {"season_player_minutes_incomplete", "season_player_statistics_incomplete"}
        assert sum(official.values()) == gap["official_xi_team_rows"] > 0
