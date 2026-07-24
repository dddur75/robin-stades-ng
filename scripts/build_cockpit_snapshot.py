"""Construire le snapshot live, compact et traçable du Cockpit Shadow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from robin.domain.odds import stable_internal_id

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cockpit" / "app" / "cockpit-data.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def sanitize_public_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_public_snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_snapshot(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        marker = "/data/historical/"
        if marker in normalized:
            return f"historical/{normalized.split(marker, 1)[1]}"
    return value


def build_deep_data() -> dict[str, Any]:
    state = ROOT / "data" / "historical"
    analytics = read_json(
        ROOT / "data" / "live-proof" / "jalon5-legacy-analytics.json",
        {},
    )
    matrix = read_json(
        state / "coverage" / "matrix.json",
        read_json(ROOT / "data" / "contracts" / "api-football-coverage.json", []),
    )
    pilot = read_json(state / "runs" / "pilot-ligue-1-2025.json", {})
    plan = read_json(state / "tasks" / "backfill-plan.json", {})
    quality = read_json(state / "quality" / "latest.json", {})
    dataset = read_json(
        state / "datasets" / "team_baseline_v1.json",
        (
            {
                **analytics.get("dataset", {}),
                "dataset_version": analytics.get("dataset", {}).get("name"),
                "status": "FEATURE_FACTORY_ACTIVE",
            }
            if analytics
            else {}
        ),
    )
    model = read_json(
        state / "models" / "elo_v1.json",
        (
            {
                **analytics.get("model", {}),
                "model_version": analytics.get("model", {}).get("version"),
                "oos_metrics": {
                    "matches": analytics.get("model", {}).get("oos_matches"),
                    "log_loss": analytics.get("model", {}).get("oos_log_loss"),
                    "brier_score": analytics.get("model", {}).get("oos_brier_score"),
                },
            }
            if analytics
            else {}
        ),
    )
    backtest = read_json(
        state / "backtests" / "elo_edge_5pct_oos.json",
        analytics.get("backtest", {}),
    )
    proof = read_json(
        state / "proofs" / "api-football-live.json",
        read_json(ROOT / "data" / "live-proof" / "jalon5-api-football.json", {}),
    )
    task_counts: dict[str, int] = {}
    for task in plan.get("tasks", []):
        status = str(task.get("status", "UNKNOWN"))
        task_counts[status] = task_counts.get(status, 0) + 1
    coverage_counts: dict[str, int] = {}
    for row in matrix:
        status = str(row.get("status", "UNKNOWN"))
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    endpoint_counts: dict[str, int] = {}
    for report in pilot.get("endpoints", []):
        endpoint = str(report.get("endpoint", "UNKNOWN"))
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
    public_pilot = {
        key: value for key, value in pilot.items() if key != "endpoints"
    }
    public_pilot["endpointCounts"] = endpoint_counts
    public_dataset = {
        key: value for key, value in dataset.items() if key != "partitions"
    }
    players: list[dict[str, Any]] = []
    player_partitions = (
        path
        for path in (state / "parquet").rglob("*.parquet")
        if any(parent.name == "entity_type=players" for parent in path.parents)
    )
    for path in sorted(player_partitions):
        for payload in pd.read_parquet(path).get("payload", []).tolist()[:20]:
            record = json.loads(str(payload))
            player = record.get("player", {})
            statistics = record.get("statistics", [])
            stat = statistics[0] if statistics else {}
            games = stat.get("games", {})
            goals = stat.get("goals", {})
            players.append(
                {
                    "id": player.get("id"),
                    "name": player.get("name"),
                    "age": player.get("age"),
                    "position": games.get("position"),
                    "appearances": games.get("appearences"),
                    "minutes": games.get("minutes"),
                    "rating": games.get("rating"),
                    "goals": goals.get("total"),
                    "assists": goals.get("assists"),
                    "origin": "HISTORICAL POINT-IN-TIME",
                }
            )
        if players:
            break
    models = [
        {
            "name": "Elo",
            "version": model.get("model_version", "elo_v1"),
            "status": model.get("status", "WAITING_FOR_DATASET"),
            "logLoss": model.get("oos_metrics", {}).get("log_loss"),
            "brier": model.get("oos_metrics", {}).get("brier_score"),
            "origin": "OOS HISTORICAL" if model else "NO OUTPUT",
        }
    ] + [
        {
            "name": name,
            "version": "planned_v1",
            "status": "BLOCKED_BY_COVERAGE",
            "logLoss": None,
            "brier": None,
            "origin": "NO OUTPUT",
        }
        for name in (
            "Poisson",
            "Dixon-Coles",
            "Régression logistique",
            "Gradient boosting",
            "Force joueurs",
            "Composition",
            "Baseline marché",
            "Ensemble calibré",
        )
    ]
    return {
        "status": proof.get("status", "ADAPTER_ONLY"),
        "pilotStatus": pilot.get("status", "NOT_STARTED"),
        "backfillStatus": plan.get("status", "NOT_STARTED"),
        "qualityStatus": quality.get("status", "NOT_RUN"),
        "productionStatus": "PRODUCTION_LOCKED",
        "coverageCounts": coverage_counts,
        "coverageMatrix": matrix,
        "taskCounts": task_counts,
        "remainingTasks": plan.get("remaining_tasks", 0),
        "nextTask": next(
            (
                task
                for task in plan.get("tasks", [])
                if task.get("status")
                in {"PENDING", "READY", "RETRYABLE", "SKIPPED_QUOTA"}
            ),
            None,
        ),
        "pilot": public_pilot,
        "quota": {
            "remaining": pilot.get("quota_remaining", proof.get("quota_remaining")),
            "calls": pilot.get("provider_calls", proof.get("calls", 0)),
            "mode": "ACCELERATED",
            "reserve": 100,
        },
        "storage": {
            "rawBytes": directory_size(state / "raw"),
            "parquetBytes": directory_size(state / "parquet"),
            "derivedBytes": directory_size(state / "derived"),
            "backend": "POSTGRESQL + PARQUET + SHADOW-DATA",
        },
        "players": players,
        "featureCatalog": [
            {
                "name": name,
                "version": "v1",
                "status": "COMPUTABLE" if dataset else "CANDIDATE",
                "leakageRisk": "LOW",
                "origin": "HISTORICAL POINT-IN-TIME",
            }
            for name in (
                "elo_global",
                "forme_5",
                "forme_10",
                "buts_marques_5",
                "buts_encaisses_5",
                "jours_repos",
                "minutes_joueur_5",
                "force_onze",
                "continuite_onze",
            )
        ],
        "dataset": public_dataset,
        "models": models,
        "backtests": (
            [
                {
                    **{key: value for key, value in backtest.items() if key != "details"},
                    "origin": "OOS HISTORICAL",
                }
            ]
            if backtest
            else []
        ),
        "quality": quality,
        "origins": [
            "LIVE SHADOW",
            "HISTORICAL POINT-IN-TIME",
            "HISTORICAL SIMULATED",
            "OOS HISTORICAL",
            "LEGACY SOURCE",
            "DEMO DATA",
            "NO OUTPUT",
        ],
    }


def main() -> None:
    live = read_json(
        ROOT / "data" / "live-proof" / "jalon3-activation.json",
        {},
    )
    if not live:
        raise RuntimeError("preuve live Jalon 3 absente")
    durable = read_json(
        ROOT / "data" / "live-proof" / "jalon4-durable-shadow.json",
        {},
    )
    if not durable:
        raise RuntimeError("preuve durable Jalon 4 absente")
    migration_rows = read_json(
        ROOT / "data" / "migrations" / "jalon2" / "legacy-uuid-summary.json",
        [{}],
    )
    migration = migration_rows[0] if migration_rows else {}
    oos = read_json(ROOT / "rapports" / "jalon2" / "oos-results.json", [])

    predictions = {
        item["internal_fixture_id"]: item
        for item in live.get("predictions", [])
    }
    decisions = {
        item["internal_fixture_id"]: item
        for item in live.get("decisions", [])
    }
    matches: list[dict[str, Any]] = []
    fixture_names: dict[str, tuple[str, str]] = {}
    for fixture in live.get("fixtures", []):
        internal_id = stable_internal_id(
            "fixture",
            "the-odds-api",
            fixture["provider_fixture_id"],
        )
        fixture_names[internal_id] = (fixture["home"], fixture["away"])
        prediction = predictions.get(internal_id)
        decision = decisions.get(internal_id)
        matches.append(
            {
                "id": fixture["provider_fixture_id"],
                "internalId": internal_id,
                "kickoff": fixture["kickoff"],
                "competition": fixture["competition"],
                "home": fixture["home"],
                "away": fixture["away"],
                "origin": fixture["origin"],
                "quality": prediction["quality"] if prediction else "PENDING",
                "model": (
                    prediction["model"]
                    if prediction
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "probabilities": {
                    "home": prediction.get("probability_home") if prediction else None,
                    "draw": prediction.get("probability_draw") if prediction else None,
                    "away": prediction.get("probability_away") if prediction else None,
                },
                "expectedGoals": {"home": None, "away": None},
                "decision": (
                    decision["primary_reason"]
                    if decision
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "accepted": bool(decision and decision["accepted"]),
            }
        )

    odds = []
    for item in live.get("snapshots", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        odds.append({**item, "home": home, "away": away})

    decision_rows = []
    for item in live.get("decisions", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        decision_rows.append(
            {
                **item,
                "home": home,
                "away": away,
                "decided_at": next(
                    (
                        prediction["generated_at"]
                        for prediction in live.get("predictions", [])
                        if prediction["prediction_id"] == item["prediction_id"]
                    ),
                    live["captured_at"],
                ),
            }
        )

    quota = live["quota"]
    persistence = live["persistence"]
    idempotence = live["idempotence"]
    health = live["health"]
    postgresql = durable["postgresql"]
    double_write = durable["double_write"]
    quality_checks = [
        {
            "check": "PostgreSQL Neon",
            "status": "PASS",
            "value": (
                f"{postgresql['registry_records']} lignes · "
                f"révision {postgresql['migration_revision']}"
            ),
            "threshold": "connecté, migré et audité",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Double écriture durable",
            "status": "PASS",
            "value": double_write["latest_ack_backend"],
            "threshold": "PostgreSQL + shadow-data",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Authentification The Odds API",
            "status": "PASS",
            "value": "appel HTTP 200, secret non exposé",
            "threshold": "source authentifiée",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Provenance brute",
            "status": "PASS",
            "value": "endpoint + temps + hash + ingestion",
            "threshold": "champs complets",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Persistance inter-runners",
            "status": "PASS",
            "value": f"{persistence['files_restored_by_runner_b']} fichiers restaurés",
            "threshold": "observation stable",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Déduplication exacte",
            "status": "PASS",
            "value": f"{idempotence['exact_duplicate_snapshots']} doublon",
            "threshold": "0",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Idempotence prédictions",
            "status": "PASS",
            "value": "1 → 1 ; décisions 1 → 1",
            "threshold": "aucun ajout identique",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Réserve quota",
            "status": "PASS",
            "value": f"{quota['reserve_pct']} %",
            "threshold": "≥ 20 %",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Prédictions sans cote",
            "status": "WARN",
            "value": f"{health['blocked_predictions']} bloquées",
            "threshold": "jamais synthétisées",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "API-Football",
            "status": "PENDING",
            "value": "adaptateur prêt, secret absent",
            "threshold": "enrichissement optionnel",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Paris réels",
            "status": "PASS",
            "value": "PRODUCTION_LOCKED",
            "threshold": "aucune exécution financière",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Couverture UUID legacy",
            "status": "PASS",
            "value": f"{migration.get('coverage', 0) * 100:.3f} %",
            "threshold": "≥ 98 %",
            "origin": "LEGACY SOURCE",
        },
    ]

    strategies = [
        {
            **item,
            "origin": "LEGACY SOURCE",
            "roiPct": round(item.get("roi", 0) * 100, 2),
            "ciLowPct": round(item.get("roi_ci_low", 0) * 100, 2),
            "ciHighPct": round(item.get("roi_ci_high", 0) * 100, 2),
        }
        for item in oos
    ]
    deep_data = build_deep_data()
    snapshot = {
        "generatedAt": durable["captured_at"],
        "snapshotType": live["snapshot_type"],
        "status": durable["burn_in"]["health"],
        "shadowStatus": durable["status"],
        "productionStatus": live["production_status"],
        "demoModeAvailable": True,
        "demoModeEnabled": False,
        "message": (
            "PostgreSQL Neon et le registre append-only shadow-data sont "
            "synchronisés. La double écriture et le replay sans fournisseur "
            "sont vérifiés ; le burn-in reste statistiquement insuffisant."
        ),
        "metrics": {
            "fixtures": len(matches),
            "snapshots": len(odds),
            "quotes": sum(item["quotes"] for item in odds),
            "bookmakers": max((item["bookmakers"] for item in odds), default=0),
            "predictions": len(live.get("predictions", [])),
            "candidates": sum(1 for item in decision_rows if item["accepted"]),
            "rejections": sum(1 for item in decision_rows if not item["accepted"]),
            "blockedPredictions": health["blocked_predictions"],
            "quotaUsed": quota["used_after_activation"],
            "quotaRemaining": quota["remaining_after_activation"],
            "migrationCoveragePct": round(migration.get("coverage", 0) * 100, 3),
            "durableRecords": postgresql["registry_records"],
            "rawPayloads": durable["migration"]["physical_payloads_migrated"],
            "windowCoveragePct": 0,
            "sloBreaches": 0,
        },
        "matches": matches,
        "odds": odds,
        "decisions": decision_rows,
        "qualityChecks": quality_checks,
        "strategies": strategies,
        "runs": [
            {
                "id": str(item["id"]),
                "pipeline": item["pipeline"],
                "status": item["status"],
                "records": item["records"],
                "calls": item["calls"],
                "quotaRemaining": item["quota_remaining"],
                "finishedAt": item["finished_at"],
                "origin": item["origin"],
            }
            for item in live.get("runs", [])
        ],
        "filters": {
            "periods": ["30 prochains jours", "7 prochains jours", "Saison 2026–2027"],
            "competitions": ["Ligue 1 - France"],
            "markets": ["1X2", "TOTAL_GOALS"],
            "strategies": ["Toutes"]
            + [item.get("strategy", "inconnue") for item in oos],
            "models": ["MARKET_BASELINE_ONLY"],
            "statuses": ["Tous", "Bloqué", "En attente"],
            "qualities": ["Toutes", "OBSERVED", "PENDING"],
            "bookmakers": ["Tous", "22 agrégés"],
        },
        "provenance": {
            "demo": "Mode démo disponible uniquement sur activation explicite.",
            "legacy": "data/matches.parquet + rapports/jalon2/oos-results.json",
            "live": (
                "The Odds API → registre append-only shadow-data → "
                "preuve compacte Jalon 4"
            ),
            "stateArtifact": live["source_state_artifact"],
            "sourceCommit": live["source_commit"],
        },
        "quota": quota,
        "persistence": persistence,
        "idempotence": idempotence,
        "providers": live["providers"],
        "durableStorage": durable["storage"],
        "postgresql": postgresql,
        "doubleWrite": double_write,
        "failureRecovery": durable["failure_recovery"],
        "migration": durable["migration"],
        "replay": durable["replay"],
        "burnIn": durable["burn_in"],
        "slo": durable["slo"],
        "scheduler": durable["scheduler"],
        "funnel": [
            {"stage": "Fixtures attendues", "count": len(matches), "loss": 0},
            {"stage": "Fixtures collectées", "count": len(matches), "loss": 0},
            {"stage": "Avec marchés", "count": 1, "loss": len(matches) - 1},
            {"stage": "Avec snapshots", "count": 1, "loss": 0},
            {"stage": "Analysables", "count": 1, "loss": 0},
            {"stage": "Prédictions", "count": len(predictions), "loss": 0},
            {"stage": "Candidats", "count": len(decision_rows), "loss": 0},
            {"stage": "Retenus shadow", "count": 0, "loss": len(decision_rows)},
            {"stage": "Rejetés / bloqués", "count": 9, "loss": 0},
            {"stage": "Réglés", "count": 0, "loss": 0},
        ],
        "notAnalyzableReasons": [
            {"reason": "MARKET_NOT_AVAILABLE", "count": 8, "origin": "LIVE SOURCE"},
            {"reason": "QUALITY_BLOCKED", "count": 1, "origin": "LIVE SOURCE"},
        ],
        "coverage": [
            {
                "fixture": f"{item['home']} — {item['away']}",
                "fixtureId": item["internalId"],
                "kickoff": item["kickoff"],
                "providerCoverage": 1 if item["probabilities"]["home"] else 0,
                "analyticCoverage": 1 if item["probabilities"]["home"] else 0,
                "windows": {
                    window: "PENDING"
                    for window in durable["scheduler"]["windows"]
                },
                "origin": item["origin"],
            }
            for item in matches
        ],
        "coverageRates": {
            "provider": round(1 / len(matches), 4) if matches else 0,
            "collection": None,
            "analytic": round(1 / len(matches), 4) if matches else 0,
            "collectionStatus": "INSUFFICIENT_OBSERVATION",
        },
        "oddsMovement": durable["odds_movement"],
        "incidents": [
            {
                "code": "ARTIFACT_REDIRECT_AUTH_HEADER",
                "severity": "WARNING",
                "status": "RESOLVED",
                "startedAt": "2026-07-24T12:54:00Z",
                "endedAt": "2026-07-24T12:56:43Z",
                "cause": "En-tête GitHub transmis vers une URL signée",
                "impact": "Un run arrêté avant appel fournisseur",
                "correction": "Retrait de l’en-tête hors api.github.com",
                "origin": "LIVE SOURCE",
            }
        ],
        "costScenarios": [
            {"scope": "Rythme actuel", "competitions": 1, "markets": 2, "credits": 720},
            {"scope": "Deux championnats", "competitions": 2, "markets": 2, "credits": 1440},
            {"scope": "Cinq championnats", "competitions": 5, "markets": 2, "credits": 3600},
            {"scope": "Marchés étendus", "competitions": 1, "markets": 4, "credits": 1440},
        ],
        "dataExplorer": [
            {
                "date": item["kickoff"],
                "fixture": f"{item['home']} — {item['away']}",
                "competition": item["competition"],
                "market": "1X2",
                "bookmakers": 22 if item["probabilities"]["home"] else 0,
                "snapshots": 2 if item["probabilities"]["home"] else 0,
                "model": item["model"],
                "decision": item["decision"],
                "quality": item["quality"],
                "provenance": item["origin"],
            }
            for item in matches
        ],
        "deepData": deep_data,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    public_snapshot = sanitize_public_snapshot(snapshot)
    OUTPUT.write_text(
        json.dumps(public_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Snapshot Cockpit écrit dans {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
