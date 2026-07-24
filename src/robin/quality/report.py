"""Rapports Markdown et HTML de santé des données."""

from __future__ import annotations

import argparse
import html
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from robin.quality.checks import QualityCheckResult, run_match_checks
from robin.quality.zero_audit import ZeroAuditRow, audit_suspect_zeros


def zero_audit_frame(rows: list[ZeroAuditRow]) -> pd.DataFrame:
    return pd.DataFrame([row.model_dump(mode="json") for row in rows])


def write_zero_report(rows: list[ZeroAuditRow], path: Path) -> None:
    suspect = [row for row in rows if row.quality_status.value == "SUSPECT_ZERO"]
    lines = [
        "# Audit des zéros suspects",
        "",
        f"Généré le {datetime.now(UTC).isoformat()}",
        "",
        f"- Segments audités : {len(rows)}",
        f"- Segments `SUSPECT_ZERO` : {len(suspect)}",
        f"- Valeurs suspectes conservées : {sum(row.zeros for row in suspect)}",
        "",
        "| Compétition | Saison | Colonne | Lignes | Zéros | Manquants | Probabilité | Statut |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.competition} | {row.season} | {row.column} | {row.rows} "
            f"| {row.zeros} | {row.missing} | {row.artificial_probability:.0%} "
            f"| {row.quality_status.value} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_health_dashboard(
    checks: list[QualityCheckResult],
    audit: list[ZeroAuditRow],
    path: Path,
) -> None:
    failures = sum(check.status.value == "FAILED" for check in checks)
    warnings = sum(check.status.value == "WARNING" for check in checks)
    rows = []
    for check in checks:
        rows.append(
            "<tr>"
            f"<td>{html.escape(check.check_name)}</td>"
            f"<td><span class='{check.status.value.lower()}'>{check.status.value}</span></td>"
            f"<td>{check.severity.value}</td>"
            f"<td>{html.escape(check.observed_value)}</td>"
            f"<td>{check.affected_rows:,}</td>"
            "</tr>"
        )
    suspect = [row for row in audit if row.quality_status.value == "SUSPECT_ZERO"]
    suspect_rows = []
    for row in suspect:
        suspect_rows.append(
            "<tr>"
            f"<td>{html.escape(row.competition)}</td><td>{html.escape(row.season)}</td>"
            f"<td>{html.escape(row.column)}</td><td>{row.zeros:,}</td>"
            f"<td>{row.artificial_probability:.0%}</td></tr>"
        )
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Robin des Stades · Santé Data</title>
<style>
:root{{--bg:#08111f;--panel:#111d2e;--line:#24344b;--text:#e8eef7;--muted:#91a3bb;
--ok:#3ddc97;--warn:#ffca57;--bad:#ff6b6b}}*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,system-ui,sans-serif}}
main{{max-width:1280px;margin:auto;padding:32px}}h1{{font-size:28px;margin:0 0 4px}}
.sub{{color:var(--muted);margin-bottom:24px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px}}
.metric{{font-size:30px;font-weight:750}}table{{width:100%;border-collapse:collapse;margin-top:12px}}
th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{color:var(--muted)}}
.passed{{color:var(--ok)}}.warning{{color:var(--warn)}}.failed{{color:var(--bad)}}
section{{margin-top:24px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}main{{padding:18px}}}}
</style></head><body><main><h1>Robin des Stades · Santé Data</h1>
<div class="sub">Jalon 1 · généré le {datetime.now(UTC).isoformat()} · PRODUCTION_LOCKED</div>
<div class="grid"><div class="card"><div class="sub">Contrôles</div><div class="metric">{len(checks)}</div></div>
<div class="card"><div class="sub">Échecs critiques</div><div class="metric failed">{failures}</div></div>
<div class="card"><div class="sub">Alertes</div><div class="metric warning">{warnings}</div></div></div>
<section class="card"><h2>Contrôles</h2><table><thead><tr><th>Contrôle</th><th>Statut</th>
<th>Sévérité</th><th>Observation</th><th>Lignes</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section class="card"><h2>Zéros suspects</h2><table><thead><tr><th>Compétition</th><th>Saison</th>
<th>Colonne</th><th>Valeurs</th><th>Probabilité</th></tr></thead>
<tbody>{''.join(suspect_rows)}</tbody></table></section></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def generate(input_path: Path, output_dir: Path) -> tuple[list[ZeroAuditRow], list[QualityCheckResult]]:
    frame = pd.read_parquet(input_path)
    audit = audit_suspect_zeros(frame, provider="football-data.co.uk")
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_csv = output_dir / "suspect-zero-audit.csv"
    zero_audit_frame(audit).to_csv(audit_csv, index=False)
    write_zero_report(audit, output_dir / "SUSPECT-ZERO-AUDIT.md")
    checks = run_match_checks(
        frame,
        audit,
        evidence_location=audit_csv,
    )
    pd.DataFrame([check.model_dump(mode="json") for check in checks]).to_json(
        output_dir / "quality-checks.json",
        orient="records",
        indent=2,
        force_ascii=False,
    )
    write_health_dashboard(checks, audit, output_dir / "health.html")
    return audit, checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/matches.parquet"))
    parser.add_argument("--output", type=Path, default=Path("rapports/quality"))
    args = parser.parse_args()
    generate(args.input, args.output)


if __name__ == "__main__":
    main()

