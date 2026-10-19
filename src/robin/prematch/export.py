"""Season exports, full-denominator coverage and shifted-cutoff verification."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from robin.prematch.criteria import METRICS, Fixture, PrematchEngine, goal_state
from robin.prematch.sources import POPULATION_SHA256, Snapshot, Target


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _schema() -> Any:
    fields = [pa.field("fixture_id", pa.int64()), pa.field("date", pa.string()),
              pa.field("date_precision", pa.string()), pa.field("competition", pa.string()),
              pa.field("season", pa.int32()), pa.field("equipe_domicile", pa.string()),
              pa.field("equipe_exterieur", pa.string()), pa.field("home_team_id", pa.int64()),
              pa.field("away_team_id", pa.int64())]
    state = pa.struct([("minutes", pa.float64()), ("buts_pour", pa.int64()), ("buts_contre", pa.int64())])
    for side in ("home", "away"):
        fields.extend([pa.field(f"source_compo_{side}", pa.string()),
                       pa.field(f"history_count_{side}", pa.int64()),
                       pa.field(f"cong21_observe_{side}", pa.int64()),
                       pa.field(f"repos_jours_observe_{side}", pa.float64())])
        for metric in METRICS:
            typ = (state if metric == "etat_score_buts10" else pa.bool_()
                   if metric.startswith("cadre_suspendu") else pa.int64()
                   if metric in {"points_tardifs5", "cong21"} else pa.float64())
            fields.extend([pa.field(f"{metric}_{side}", typ),
                           pa.field(f"reason_{metric}_{side}", pa.string())])
    return pa.schema(fields, metadata={b"contract": b"mission036-prematch-v1",
                                      b"history_cutoff": b"kickoff_exclusive_minus_3h"})


def _temporal_audit(
    snapshot: Snapshot, engine: PrematchEngine,
    candidates: dict[tuple[str, int], list[tuple[Fixture, int, dict[str, Any]]]],
) -> dict[str, Any]:
    evidence = []
    for _cell, entries in sorted(candidates.items()):
        # Earliest plus the most usable row: test both null and calculable histories.
        selected = {entries[0][0].fixture_id: entries[0]}
        for metric in METRICS:
            found = next((e for e in reversed(entries) if e[2][metric] is not None), None)
            if found:
                selected[found[0].fixture_id] = found
        for target, _team, _values in selected.values():
            cutoff = target.kickoff - timedelta(hours=3)
            prior = [f for f in snapshot.fixtures if f.kickoff < cutoff]
            ids = {f.fixture_id for f in prior}
            reduced = PrematchEngine(
                prior, {k: v for k, v in snapshot.players.items() if k[0] in ids},
                {k: v for k, v in snapshot.lineups.items() if k[0] == target.fixture_id},
                {k: v for k, v in snapshot.events.items() if k in ids}, engine.calendar_complete)
            # Strip even the target result/status: only fixture context and XI remain.
            stripped = replace(target, home_goals=None, away_goals=None, status="NS")
            for team in (target.home, target.away):
                expected = engine.team(target, team)
                actual = reduced.team(stripped, team)
                if actual != expected:
                    raise AssertionError(f"temporal leakage: fixture {target.fixture_id}, team {team}")
                evidence.append(dict(fixture_id=target.fixture_id, team_id=team,
                                     competition=target.competition, season=target.season,
                                     cutoff=cutoff.isoformat(), result_sha256=_hash(actual),
                                     non_null=[m for m in METRICS if actual[m] is not None]))
    return {"passed": True, "sampled_team_rows": len(evidence), "comparisons": evidence,
            "method": "rebuild_without_target_or_future_postmatch_data; target_official_XI_only"}


def export_snapshot(snapshot: Snapshot, targets: list[Target], output: Path) -> dict[str, Any]:
    if any(t.season == 2025 for t in targets):
        raise ValueError("holdout output forbidden")
    if len({t.fixture_id for t in targets}) != len(targets):
        raise ValueError("duplicate output fixture")
    output.mkdir(parents=True, exist_ok=True)
    fixtures = {f.fixture_id: f for f in snapshot.fixtures}
    required: dict[tuple[str, int], set[int]] = defaultdict(set)
    for target in targets:
        required[target.competition, target.season].add(target.fixture_id)
    complete = {k: ids <= fixtures.keys() for k, ids in required.items()}
    # Additional prior seasons are usable only with a published fixture calendar.
    for source_fixture in snapshot.fixtures:
        complete.setdefault((source_fixture.competition, source_fixture.season), True)
    engine = PrematchEngine(snapshot.fixtures, snapshot.players, snapshot.lineups, snapshot.events, complete)
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    counts: dict[tuple[str, int, str], Counter[str]] = defaultdict(Counter)
    candidates: dict[tuple[str, int], list[tuple[Fixture, int, dict[str, Any]]]] = defaultdict(list)
    contexts: Counter[str] = Counter()
    for target in sorted(targets, key=lambda t: (t.season, t.competition, t.fixture_id)):
        f = fixtures.get(target.fixture_id)
        if f is not None and (f.competition, f.season) != (target.competition, target.season):
            raise ValueError("target/source fixture binding mismatch")
        row: dict[str, Any] = dict(fixture_id=target.fixture_id, season=target.season,
                                   competition=target.competition,
                                   date=f.kickoff.isoformat() if f else target.date,
                                   date_precision="kickoff" if f else "day" if target.date else "missing",
                                   equipe_domicile=f.home_name if f else target.home_name,
                                   equipe_exterieur=f.away_name if f else target.away_name,
                                   home_team_id=f.home if f else None, away_team_id=f.away if f else None)
        contexts["fixture_context_present" if f else "fixture_context_missing"] += 1
        for side in ("home", "away"):
            if f:
                team = f.home if side == "home" else f.away
                values = engine.team(f, team)
                if side == "home":
                    candidates[target.competition, target.season].append((f, team, values))
            else:
                values = dict.fromkeys(METRICS)
                values["reasons"] = dict.fromkeys(METRICS, "fixture_context_missing")
                values["reasons"].update(tc_neutre10="timestamped_shots_unavailable",
                                         cong21="all_competitions_calendar_unproven",
                                         repos_jours="all_competitions_calendar_unproven",
                                         cadre_suspendu_cumul="league_season_yellow_rule_undocumented")
            for extra in ("source_compo", "history_count", "cong21_observe", "repos_jours_observe"):
                row[f"{extra}_{side}"] = values.get(extra)
            for metric in METRICS:
                value = values[metric]
                reason = values["reasons"].get(metric) if value is None else None
                if value is None and not reason:
                    raise AssertionError("null without reason")
                row[f"{metric}_{side}"] = value
                row[f"reason_{metric}_{side}"] = reason
                counts[target.competition, target.season, metric][reason or "NON_NULL"] += 1
        by_season[target.season].append(row)

    outputs = []
    for season, rows in sorted(by_season.items()):
        path = output / f"season={season}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=_schema()), path, compression="zstd")
        outputs.append(dict(path=path.name, rows=len(rows), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    coverage = []
    for (league, season, metric), counter in sorted(counts.items()):
        total, non_null = sum(counter.values()), counter["NON_NULL"]
        reasons = dict(sorted((k, v) for k, v in counter.items() if k != "NON_NULL"))
        coverage.append(dict(competition=league, season=season, criterion=metric, total_team_rows=total,
                             non_null=non_null, rate=non_null / total, null_reasons=json.dumps(reasons, sort_keys=True)))
    with (output / "coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)
    inventory_path = output / "source-inventory.csv"
    if snapshot.inventory:
        with inventory_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(snapshot.inventory[0]))
            writer.writeheader()
            writer.writerows(snapshot.inventory)
    else:
        inventory_path.write_text("", encoding="utf-8")
    (output / "SOURCES.json").write_text(_json(dict(revision=snapshot.revision,
        inventory_file=inventory_path.name, inventory_entries=len(snapshot.inventory),
        inventory_sha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        audit=snapshot.audit)), encoding="utf-8")
    _source_coverage(snapshot, targets, output)
    audit = _temporal_audit(snapshot, engine, candidates)
    (output / "TEMPORAL-AUDIT.json").write_text(_json(audit), encoding="utf-8")
    target_hash = hashlib.sha256("".join(f"{i}\n" for i in sorted(t.fixture_id for t in targets)).encode()).hexdigest()
    calculator_hash = hashlib.sha256(b"".join((Path(__file__).parent / name).read_bytes()
        for name in ("criteria.py", "sources.py", "export.py"))).hexdigest()
    report = dict(schema_version="mission036-prematch-v1", status="PARTIAL",
                  claim_id="DATA.MISSION036.PREMATCH.V1", calculator_sha256=calculator_hash,
                  source_revision=snapshot.revision, target_fixture_ids_sha256=target_hash,
                  frozen_mission_fixture_ids_sha256=POPULATION_SHA256,
                  target_fixtures=len(targets), source_audit=snapshot.audit,
                  contexts=dict(contexts), outputs=outputs,
                  temporal_audit={k: v for k, v in audit.items() if k != "comparisons"},
                  coverage_unit="team-fixture; non-null includes 0 and false",
                  provider_calls=0, neon_writes=0, r2_accesses=0,
                  source_inventory_sha256=_hash(snapshot.inventory))
    (output / "REPORT.json").write_text(_json(report), encoding="utf-8")
    _coverage_markdown(output, coverage, report)
    return report


def _coverage_markdown(output: Path, coverage: list[dict[str, Any]], report: dict[str, Any]) -> None:
    lines = ["# Couverture réelle — critères avant-match 036", "",
             "Claim : `DATA.MISSION036.PREMATCH.V1` (revue indépendante en attente).", "",
             f"Source figée : `{report['source_revision']}`. Population : {report['target_fixtures']} matchs.",
             "Unité : équipe-match (2 lignes par match). Taux = valeurs non nulles / population cible.",
             "Zéro et faux sont comptés comme couverts. Les matchs sans source restent au dénominateur.",
             "Statut PARTIAL : publication et familles incomplètes ; aucun proxy des données manquantes.", "",
             "Les compositions officielles sont admissibles conformément à l'instruction utilisateur.",
             "Abs/XI restent à 0 % faute de recouvrement suffisant avec les statistiques par match.",
             "Les fiches joueurs agrégées sur toute la saison ne sont pas utilisées.",
             "Le calendrier toutes compétitions et les règles de cumul de jaunes ne sont pas prouvés.",
             "Une suspension rouge prouvée produit vrai ; sinon la suspension globale reste inconnue.", "",
             "Détail des motifs : `coverage.csv`. Inventaire : `SOURCES.json`.",
             "Couverture des familles rattachables : `source-coverage.csv` ; blobs : `source-inventory.csv`.",
             "Recalcul décalé, résultat cible et futur retirés : `TEMPORAL-AUDIT.json`.", "",
             "TC = tc_neutre10 ; État = etat_score_buts10 ; Abs = absents_cles ; XI = force_xi ;",
             "Cong = cong21 ; Rep = repos_jours ; Susp = cadre_suspendu ; R = partie rouge ;",
             "J = partie cumul de jaunes ; Tard = points_tardifs5.", "",
             "| Ligue | Saison | Équipe-matchs | TC | État | Abs | XI | Cong | Rep | Susp | R | J | Tard |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    cells: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for c in coverage:
        cells[c["competition"], c["season"]][c["criterion"]] = c
    for (league, season), metrics in sorted(cells.items()):
        n = metrics["tc_neutre10"]["total_team_rows"]
        rates = " | ".join(f"{100 * metrics[m]['rate']:.2f}%" for m in METRICS)
        lines.append(f"| {league} | {season} | {n} | {rates} |")
    (output / "COVERAGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _source_coverage(snapshot: Snapshot, targets: list[Target], output: Path) -> None:
    fixtures = {f.fixture_id: f for f in snapshot.fixtures}
    counts: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for t in targets:
        cell = counts[t.competition, t.season]
        cell["target_fixtures"] += 1
        cell["target_team_rows"] += 2
        f = fixtures.get(t.fixture_id)
        if f:
            cell["fixture_context"] += 1
            cell["events_file_present"] += f.fixture_id in snapshot.events
            cell["goal_trajectory_valid"] += goal_state(f, snapshot.events.get(f.fixture_id), f.home) is not None
            for team in (f.home, f.away):
                key = f.fixture_id, team
                block = snapshot.players.get(key)
                cell["official_xi"] += key in snapshot.lineups
                cell["player_block"] += key in snapshot.players
                cell["player_minutes_complete"] += PrematchEngine._minutes_valid(block)
                cell["xi_and_player_block"] += key in snapshot.lineups and key in snapshot.players
    fields = ["competition", "season", "target_fixtures", "target_team_rows", "fixture_context",
              "events_file_present", "goal_trajectory_valid", "official_xi", "player_block",
              "player_minutes_complete", "xi_and_player_block"]
    with (output / "source-coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for (league, season), c in sorted(counts.items()):
            writer.writerow(dict(competition=league, season=season, **{k: c[k] for k in fields[2:]}))
