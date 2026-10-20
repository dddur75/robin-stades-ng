"""Radar papier local : exports CLV existants ou stock normalisé, aucun accès réseau."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from robin import clv

THRESHOLDS = (0, 0.02, 0.05)
START = date(2026, 10, 3)
END = date(2026, 11, 16)  # décision le 17/11, dernière journée complète
Row = dict


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("timestamp must include UTC offset")
    return result


def finite(value: str | float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite number")
    return result


def kickoff(row: Row) -> datetime:
    return instant(row["close_at"]) + timedelta(minutes=finite(row["close_gap_minutes"]))


def load_details(directory: Path, through: date) -> tuple[list[Row], list[Row]]:
    rows, sources, seen = [], [], {}
    for path in sorted(directory.glob("????-??-??-clv.csv")):
        day = date.fromisoformat(path.name[:10])
        if not START <= day <= through:
            continue
        sources.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        with path.open(encoding="utf-8", newline="") as stream:
            for raw in csv.DictReader(stream):
                r = {**raw, "day": str(day), "kind": "standard", "horizon": int(raw["horizon"])}
                if r["book"] not in clv.FR_BOOKS or r["issue"] not in ("1", "N", "2"):
                    raise ValueError("unsupported book or issue")
                if r["horizon"] not in (48, 24, 2):
                    raise ValueError("unsupported horizon")
                r["clv"] = None
                for field in ("gap_minutes", "close_gap_minutes"):
                    r[field] = finite(raw[field]) if raw[field] else None
                if raw["clv"]:
                    p, price = finite(raw["p_fair_close"]), finite(raw["price"])
                    if not 0 < p < 1 or price <= 1:
                        raise ValueError("invalid probability or price")
                    r.update(p_fair_close=p, price=price, clv=price * p - 1)
                    if not math.isclose(r["clv"], finite(raw["clv"]), abs_tol=1e-12):
                        raise ValueError("CLV formula mismatch")
                    ko = kickoff(r)
                    if (
                        instant(r["observed_at"]) >= ko
                        or instant(r["close_at"]) >= ko
                        or ko.date() != day
                    ):
                        raise ValueError("price at/after kickoff or wrong day")
                key = (r["match"], r["issue"], r["book"], r["horizon"])
                if key in seen and seen[key] != r:
                    raise ValueError("conflicting duplicate CLV row")
                if key not in seen:
                    seen[key] = r
                    rows.append(r)
    if not sources:
        raise ValueError("no CLV exports in requested period")
    return rows, sources


def load_boosts(path: Path, details: list[Row]) -> list[Row]:
    """Manual single-match full-time 1N2 only. Match is the canonical CLV ID."""
    references = {}
    for r in details:
        if r["clv"] is None:
            continue
        key = (r["match"], r["issue"])
        reference = (finite(r["p_fair_close"]), kickoff(r), r["close_at"], r["close_gap_minutes"])
        if key in references and references[key] != reference:
            raise ValueError("conflicting Pinnacle reference")
        references[key] = reference
    result, seen = [], {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["date", "book", "match", "issue", "cote_boostee", "mise_max"]:
            raise ValueError("invalid manual CSV header")
        for r in reader:
            if r["book"] not in clv.FR_BOOKS:
                raise ValueError("unsupported French book")
            key = (r["match"], r["issue"])
            if key not in references:
                raise ValueError("boost without usable Pinnacle reference")
            p, ko, close, gap = references[key]
            observed = instant(r["date"])
            if observed >= ko:
                raise ValueError("boost at/after kickoff")
            price, cap = finite(r["cote_boostee"]), finite(r["mise_max"])
            if price <= 1 or cap <= 0:
                raise ValueError("invalid boost price or maximum stake")
            item = dict(
                match=key[0],
                issue=key[1],
                book=r["book"],
                day=str(ko.date()),
                observed_at=observed.isoformat(),
                horizon="MANUEL",
                price=price,
                p_fair_close=p,
                clv=price * p - 1,
                kind="boost",
                status="OK",
                close_at=close,
                close_gap_minutes=gap,
                mise_max=cap,
                gain_10_eligible=cap >= 10,
                gain_capped=min(10, cap) * (price * p - 1),
            )
            identity = (key, r["book"], observed)
            if identity in seen and seen[identity] != item:
                raise ValueError("conflicting manual boost")
            if identity not in seen:
                seen[identity] = item
                result.append(item)
    return result


def first_crossings(rows: list[Row]) -> list[Row]:
    """One match/issue/book per threshold, irrespective of horizon and kind."""
    chosen = {}
    for threshold in THRESHOLDS:
        for r in sorted(
            rows,
            key=lambda r: (
                instant(r["observed_at"])
                if r.get("observed_at")
                else datetime.min.replace(tzinfo=ZoneInfo("UTC")),
                str(r["horizon"]),
                r["kind"],
            ),
        ):
            ev = r["clv"]
            if ev is None or (ev <= 0 if threshold == 0 else ev < threshold - 1e-12):
                continue
            key = (r["match"], r["issue"], r["book"], threshold)
            chosen.setdefault(key, {**r, "threshold": threshold})
    return list(chosen.values())


def statistics(crossings: list[Row]) -> list[Row]:
    result = []
    for threshold in THRESHOLDS:
        values = [r["clv"] for r in crossings if r["threshold"] == threshold]
        result.append(
            dict(
                threshold=threshold,
                n=len(values),
                mean_ev=mean(values) if values else None,
                gain_10=10 * sum(values),
            )
        )
    return result


def book_table(crossings: list[Row]) -> str:
    lines = [
        "| Book | EV+ n | ≥2% n | ≥5% n | EV moy. EV+ | Gain 10€ EV+ | EV moy. ≥2% | Gain ≥2% | EV moy. ≥5% | Gain ≥5% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for book in clv.FR_BOOKS:
        stats = statistics([r for r in crossings if r["book"] == book])
        means = ["—" if s["mean_ev"] is None else f"{100 * s['mean_ev']:.3f}%" for s in stats]
        lines.append(
            f"| {book} | "
            + " | ".join(str(s["n"]) for s in stats)
            + " | "
            + " | ".join(f"{m} | {s['gain_10']:.2f} €" for s, m in zip(stats, means))
            + " |"
        )
    return "\n".join(lines)


def cuts(crossings: list[Row]) -> str:
    groups = defaultdict(list)
    for r in crossings:
        groups[r["book"], clv.probability_band(float(r["p_fair_close"])), str(r["horizon"])].append(
            r
        )
    lines = [
        "| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |",
        "|---|---|---|---:|---:|---:|",
    ]
    for (book, band, horizon), values in sorted(groups.items()):
        lines.append(
            f"| {book} | {band} | {horizon} | "
            + " | ".join(str(s["n"]) for s in statistics(values))
            + " |"
        )
    return "\n".join(lines)


def write_csv(path: Path, rows: list[Row]) -> None:
    fields = sorted({k for r in rows for k in r}) or ["match", "issue", "book", "threshold"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {
                k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                for k, v in r.items()
            }
            for r in rows
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clv-dir", type=Path, default=Path("reports/clv/2026-27"))
    parser.add_argument("--stock", type=Path, help="recalculer via clv_cumul sur ce stock local")
    parser.add_argument(
        "--baseline", type=Path, help="socle CLV figé, nouvelles journées après sa borne"
    )
    parser.add_argument("--boosts", type=Path, default=Path("data/radar/boosts.csv"))
    parser.add_argument(
        "--through",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("Europe/Paris")).date() - timedelta(days=1),
    )
    parser.add_argument("--output", type=Path, default=Path("reports/radar/2026-27"))
    args = parser.parse_args(argv)
    through = min(args.through, END)
    if args.baseline and not args.stock:
        parser.error("--baseline requires --stock")
    with tempfile.TemporaryDirectory(prefix="radar-") as temporary:
        directory = args.clv_dir
        if args.stock:
            # Same loader, duplicate quarantine, temporal windows and fair as CLV.
            import runpy

            directory = Path(temporary)
            start = START
            baseline_files = []
            if args.baseline:
                baseline_files = sorted(args.baseline.glob("????-??-??-clv.csv"))
                if not baseline_files:
                    raise ValueError("empty frozen baseline")
                start = max(date.fromisoformat(p.name[:10]) for p in baseline_files) + timedelta(
                    days=1
                )
            if start <= through:
                runpy.run_path(str(Path(__file__).with_name("clv_cumul.py")))["main"](
                    [
                        "--start",
                        str(start),
                        "--through",
                        str(through),
                        "--output",
                        str(directory),
                        str(args.stock),
                    ]
                )
            for path in baseline_files:
                if START <= date.fromisoformat(path.name[:10]) <= through:
                    (directory / path.name).write_bytes(path.read_bytes())
        rows, sources = load_details(directory, through)
        if args.baseline:
            old_ids = {r["match"] for r in rows if date.fromisoformat(r["day"]) < start}
            new_ids = {r["match"] for r in rows if date.fromisoformat(r["day"]) >= start}
            if old_ids & new_ids:
                raise ValueError("fixture crosses frozen baseline boundary")
        provenance = {}
        for name in ("SOURCES.json", "ARTIFACTS.json", "EXCLUSIONS.csv", "COVERAGE.md"):
            path = directory / name
            if path.exists():
                provenance[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                if args.stock:
                    args.output.mkdir(parents=True, exist_ok=True)
                    (args.output / ("CLV-" + name)).write_bytes(path.read_bytes())
        if args.baseline:
            for path in sorted(args.baseline.glob("*.json")):
                provenance["BASELINE-" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        boosts = load_boosts(args.boosts, rows) if args.boosts.exists() else []
        audit = {
            "normalized_files_inspected": 0,
            "normalized_rows_inspected": 0,
            "market_keys": {},
            "boost_label_rows": 0,
            "status": "UNKNOWN: CLV exports do not preserve promotion labels",
        }
        if args.stock:
            markets = defaultdict(int)
            for path in sorted(args.stock.rglob("robin-real-data.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                audit["normalized_files_inspected"] += 1
                for r in payload["rows"]:
                    audit["normalized_rows_inspected"] += 1
                    markets[r["market_key"]] += 1
                    labels = " ".join(
                        str(r.get(k, "")) for k in ("market_key", "market_name", "market_label")
                    )
                    audit["boost_label_rows"] += bool(re.search("boost|super.?cote", labels, re.I))
            audit.update(
                market_keys=dict(markets), status="LABEL_AUDIT_ONLY: unlabeled promotions unknown"
            )
    selected = first_crossings(rows + boosts)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "DETAIL-HORIZONS.csv", rows)
    write_csv(out / "PREMIERS-FRANCHISSEMENTS.csv", selected)
    write_csv(out / "BOOSTS.csv", boosts)
    boost_hash = (
        hashlib.sha256(args.boosts.read_bytes()).hexdigest() if args.boosts.exists() else None
    )
    (out / "SOURCES.json").write_text(
        json.dumps(
            dict(
                start=str(START),
                through=str(through),
                latest_kickoff_day=max(r["day"] for r in rows),
                clv_exports=sources,
                clv_provenance_sha256=provenance,
                boost_csv_sha256=boost_hash,
                boost_audit=audit,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    note = f"""Statut **PARTIAL** — papier uniquement ; décision le 17/11/2026.
Claim source : `DATA.CLV202627.CUMUL.V1` ; dérivation : `DATA.RADAR202627.PAPER.V1`.
Borne demandée : {through} ; dernière journée de matchs disponible : {max(r["day"] for r in rows)}.
Période depuis le 03/10 ; semaines ISO des coups d'envoi UTC. Couverture R2 non établie.
Stock global : {len(rows)} lignes horizon, {sum(r["clv"] is not None for r in rows)} EV calculables,
{sum(r["clv"] is None for r in rows)} lignes non calculables ; {len(boosts)} boosts manuels.

EV = prix FR × p juste Pinnacle clôture − 1 ; p juste = (1/cote) / somme(1/cote) sur 1,N,2.
La clôture est la dernière observation complète disponible avant le match, parfois distante.
EV+ signifie strictement >0 (zéro exclu) ; ≥2% et ≥5% inclusifs à 1e−12 près.
Pour chaque seuil : une seule opportunité par match/issue/book, au premier franchissement.
Les seuils se recouvrent : ne pas additionner leurs comptes ni leurs gains.
EV moyenne et gain sont ceux des prix au premier franchissement du seuil concerné.
Gain = somme(10 € × EV), hypothétique brut ; aucun pari ni résultat réalisé.
Pour un boost limité à <10 €, le gain fixe reste théorique et non éligible :
`BOOSTS.csv` expose `gain_10_eligible` et `gain_capped` à min(10 €, mise max).
Les détails par horizon ne constituent pas des opportunités supplémentaires.
Les boosts et prix standards sont dédupliqués ensemble dans le total ; leur détail reste séparé.
Fenêtres du moteur CLV : ±6h à T−48/T−24, ±90min à T−2, toujours avant coup d'envoi.
Une cote positive contre la clôture future est un constat rétrospectif, pas un signal disponible en direct.
Traçabilité : `SOURCES.json`, CSV détaillés et [couverture CLV](../../clv/2026-27/COVERAGE.md).
Boosts : aucun label observable dans les exports CLV ; absence dans les flux non démontrée.
Voir [audit et sources](../../../docs/RADAR-2026-27.md).
Aucun chiffre sur une semaine sans données ne prouve une absence de prix EV+.
"""
    weeks = defaultdict(list)
    for r in rows + boosts:
        year, week, _ = date.fromisoformat(r["day"]).isocalendar()
        weeks[f"{year}-{week:02}"].append(r)
    day = START
    while day <= through:
        year, week, _ = day.isocalendar()
        weeks.setdefault(f"{year}-{week:02}", [])
        day += timedelta(days=1)
    links = []
    for week, values in sorted(weeks.items()):
        chosen = first_crossings(values)
        filename = f"SEMAINE-{week}.md"
        links.append(f"- [{week}]({filename})")
        horizon_rows = [
            {**r, "threshold": t}
            for r in values
            for t in THRESHOLDS
            if r["clv"] is not None and (r["clv"] > 0 if t == 0 else r["clv"] >= t - 1e-12)
        ]
        text = f"# Radar {week}\n\n{note}\n## Opportunités uniques par book\n\n{book_table(chosen)}\n\n"
        text += f"## Première apparition par bande et horizon\n\n{cuts(chosen)}\n\n"
        text += f"## Détail par horizon (répétitions possibles)\n\n{cuts(horizon_rows)}\n"
        (out / filename).write_text(text, encoding="utf-8")
    text = f"# Radar de prix 2026-27 — cumul\n\n{note}\n## Opportunités uniques par book\n\n{book_table(selected)}\n\n"
    text += (
        f"## Première apparition par bande et horizon\n\n{cuts(selected)}\n\n## Boosts seuls\n\n"
    )
    text += book_table(first_crossings(boosts)) + "\n\n## Semaines\n\n" + "\n".join(links) + "\n"
    (out / "RADAR.md").write_text(text, encoding="utf-8")
    print(f"{len(rows)} lignes, {len(boosts)} boosts, {len(selected)} franchissements → {out}")


if __name__ == "__main__":
    main()
