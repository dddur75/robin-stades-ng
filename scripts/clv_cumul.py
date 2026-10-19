"""Rebuild paper CLV daily exports and cumulative tables from existing local stock.

No remote access. Directories discover only odds-snapshots.jsonl and
robin-real-data.json; explicit paths also accept other JSON/JSONL filenames.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from robin import clv
from robin.domain.odds import OddsSnapshot

BANDS = ("<30%", "30-45%", "45-60%", ">=60%", "INCONNUE")


def load_source(path: Path) -> list[OddsSnapshot]:
    """Adapt public dashboard projections; keep the pinned engine unchanged."""
    if path.suffix == ".jsonl":
        return clv.load([path])
    rows = json.loads(path.read_text("utf-8"))["rows"]
    relevant = []
    for row in rows:
        if row["market_key"] != "h2h" or row.get("point") is not None:
            continue
        if "home_team" not in row or "away_team" not in row:
            teams = row.get("match", "").split(" — ")
            if len(teams) != 2 or not all(teams):
                raise ValueError("ambiguous or missing team names")
            row = {**row, "home_team": teams[0], "away_team": teams[1]}
        relevant.append(row)
    with tempfile.TemporaryDirectory(prefix="clv-cumul-") as temporary:
        adapted = Path(temporary) / "normalized.json"
        adapted.write_text(json.dumps({"rows": relevant}), encoding="utf-8")
        return clv.load([adapted])


def cumulative(rows: list[clv.Row]) -> list[clv.Row]:
    groups: dict[tuple[str, str, int], list[clv.Row]] = defaultdict(list)
    stats = {(r["book"], r["band"], r["horizon"]): r for r in clv.summarize(rows)}
    for row in rows:
        band = clv.probability_band(row["p_fair_close"]) if row["p_fair_close"] else "INCONNUE"
        groups[row["book"], band, row["horizon"]].append(row)
    result = []
    for book in clv.FR_BOOKS:
        for band in BANDS:
            for horizon in (48, 24, 2):
                key = (book, band, horizon)
                values = groups[key]
                late = [r["clv"] for r in values if r["late"] is True and r["clv"] is not None]
                missing = sum(r["status"] == "MISSING_HORIZON" for r in values)
                result.append({"book": book, "band": band, "horizon": horizon,
                    "n": 0, "mean_clv": None, "ci95_low": None, "ci95_high": None,
                    **stats.get(key, {}), "total": len(values), "late_n": len(late),
                    "late_mean_clv": mean(late) if late else None,
                    "missing_horizon_n": missing,
                    "missing_horizon_share": missing / len(values) if values else None})
    return result


def table(rows: list[clv.Row]) -> str:
    def percent(value: float | None) -> str:
        return "—" if value is None else f"{value * 100:.3f}%"
    lines = ["| Book FR | Bande | Horizon | n | CLV moyen | IC95 | late n | late CLV moyen | MISSING_HORIZON / total | Part |",
             "|---|---|---|---:|---:|---|---:|---:|---:|---:|"]
    for r in rows:
        interval = f"[{percent(r['ci95_low'])} ; {percent(r['ci95_high'])}]"
        lines.append(f"| {r['book']} | {r['band']} | T−{r['horizon']} h | {r['n']} | "
                     f"{percent(r['mean_clv'])} | {interval} | {r['late_n']} | "
                     f"{percent(r['late_mean_clv'])} | {r['missing_horizon_n']} / {r['total']} | "
                     f"{percent(r['missing_horizon_share'])} |")
    return "\n".join(lines)


def write_csv(path: Path, fields: tuple[str, ...], rows: list[clv.Row]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: "'" + v if isinstance(v, str)
                          and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                          for k, v in row.items()} for row in rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--through", type=date.fromisoformat,
                        default=datetime.now(ZoneInfo("Europe/Paris")).date() - timedelta(days=1))
    parser.add_argument("--output", type=Path, default=Path("reports/clv/2026-27"))
    args = parser.parse_args(argv)
    if args.start > args.through:
        parser.error("start must precede through")
    paths = set()
    for source in args.sources:
        if source.is_dir():
            paths.update(source.rglob("odds-snapshots.jsonl"))
            paths.update(source.rglob("robin-real-data.json"))
        elif source.is_file() and source.suffix in (".json", ".jsonl"):
            paths.add(source)
        else:
            parser.error(f"missing or unsupported source: {source}")
    if not paths:
        parser.error("no snapshot or normalized report found")
    by_fixture = defaultdict(list)
    days = set()
    sources = []
    observed: list[datetime] = []
    cutoff = datetime.combine(args.through + timedelta(days=1), time(), UTC)
    for path in sorted(paths):
        snapshots = load_source(path)
        observed.extend(s.observed_at for s in snapshots if s.observed_at < cutoff)
        for s in snapshots:
            if (args.start <= s.fixture_kickoff_at.date() <= args.through
                    and s.observed_at < cutoff and s.ingested_at < cutoff):
                by_fixture[s.fixture_id].append(s)
                days.add(s.fixture_kickoff_at.date())
        sources.append({"path": str(path.relative_to(path.parent.parent)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "snapshots": len(snapshots)})
    # Quarantine contradictory fixtures, never select a convenient source/version.
    # Calculate everything before writing; invalid input files still fail closed.
    daily: dict[date, list[clv.Row]] = {day: [] for day in sorted(days)}
    exclusions = []
    for fixture, values in sorted(by_fixture.items()):
        kickoffs = sorted({s.fixture_kickoff_at for s in values})
        try:
            if len(kickoffs) != 1:
                raise ValueError("conflicting fixture kickoff")
            daily[kickoffs[0].date()].extend(clv.calculate(values, kickoffs[0].date(), as_of=cutoff))
        except ValueError as exc:
            exclusions.append({"match": fixture, "reason": str(exc),
                               "kickoffs": ";".join(k.isoformat() for k in kickoffs),
                               "snapshot_count": len(values)})
    rows = [r for values in daily.values() for r in values]
    stats = cumulative(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "EXCLUSIONS.csv",
              ("match", "reason", "kickoffs", "snapshot_count"), exclusions)
    for day, day_rows in daily.items():
        write_csv(args.output / f"{day}-clv.csv", clv.DETAIL_FIELDS, day_rows)
        write_csv(args.output / f"{day}-summary.csv", clv.SUMMARY_FIELDS, clv.summarize(day_rows))
    manifest = {"start": str(args.start), "through": str(args.through), "sources": sources}
    (args.output / "SOURCES.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    top = sorted((r for r in stats if r["n"] >= 30), key=lambda r: -r["mean_clv"])[:10]
    coverage = f"{min(observed).isoformat()} → {max(observed).isoformat()}" if observed else "vide"
    missing = sum(r["status"] == "MISSING_HORIZON" for r in rows)
    report = f"""# CLV papier 2026-27 — cumul

Statut : PARTIAL — stock local traité ; exhaustivité du stock durable non établie.
Claim : `DATA.CLV202627.CUMUL.V1`. Voir `COVERAGE.md` pour l'inventaire de livraison.

Période des coups d'envoi UTC : {args.start} → {args.through} inclus.
Observations disponibles avant la borne : {coverage}.
Sources locales : {len(paths)} fichiers ; {len(daily)} journées avec matchs ;
{len(rows)} lignes book × issue × horizon ; {sum(r['clv'] is not None for r in rows)} CLV calculables.
Matchs exclus pour preuve contradictoire : {len(exclusions)} (`EXCLUSIONS.csv`).
MISSING_HORIZON : {missing} / {len(rows)} lignes.
Traçabilité : `SOURCES.json` (SHA-256 de chaque entrée). Aucune collecte nouvelle.

## Méthode et limites

Le moteur `robin.clv.load/calculate/summarize` est réutilisé sans modifier les fenêtres,
le fair de clôture ni la définition de late. Une observation répétée ne multiplie pas
les lignes ; toute contradiction de prix ou de coup d'envoi exclut le match entier,
avec motif et horaires dans `EXCLUSIONS.csv`, sans choisir une version des faits.
Les journées sont celles des matchs, pas celles des captures. Les données hors
saison/borne sont exclues ; une journée avec seulement Pinnacle a des CSV à en-tête.
`n` compte les CLV calculables ; IC95 Student, vide pour n < 2. CLV et IC affichés
ici en pourcentage, CSV en ratios. `late n` compte uniquement late=True avec CLV
calculable. Part MISSING_HORIZON = nombre de ces statuts / toutes les lignes du
groupe (y compris les autres statuts manquants). INCONNUE = fair de clôture absent.
Un book absent d'un match ne produit aucune ligne : le dénominateur n'est pas
une mesure de couverture de tous les books sur tous les matchs.
Les IC sont descriptifs : dépendances entre issues, books et horizons non corrigées.
La clôture est la dernière observation Pinnacle complète disponible, parfois éloignée
du coup d'envoi. Ces chiffres ne prouvent aucun edge ni rendement réalisable.

## 10 plus forts CLV moyens, n ≥ 30

{table(top) if top else 'Aucun groupe avec n ≥ 30.'}

## Cumul complet

{table(stats)}
"""
    (args.output / "CUMUL.md").write_text(report, encoding="utf-8")
    print(f"{len(paths)} sources, {len(daily)} days, {len(rows)} rows → {args.output}")


if __name__ == "__main__":
    main()
