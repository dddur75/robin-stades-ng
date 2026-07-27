"""Exécuter le Jalon 9 sans appel API-Football ni crédit The Odds API."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from robin.historical.critical_closure import (
    build_historical_market_dataset,
    classify_ucl_phase,
    download_football_data,
    historical_fixture_facts,
    market_gates,
    market_paired_validation,
    match_market_fixtures,
    odds_api_historical_dry_run,
    parse_archived_market_files,
    player_and_lineup_gates,
    preseason_package_v2,
    storage_readiness,
    strategy_lab_v4,
    team_identity_audit,
    write_market_datasets,
)
from robin.historical.storage import write_json_atomic


def execute(
    state: Path,
    *,
    run_id: str,
    source_commit: str,
    download: bool,
) -> dict[str, object]:
    started_at = datetime.now(UTC).isoformat()
    manifests = download_football_data(state) if download else []
    fixtures = historical_fixture_facts(state)
    raw_market = parse_archived_market_files(state)
    matched, matching = match_market_fixtures(raw_market, fixtures)
    dataset = build_historical_market_dataset(matched)
    writes = write_market_datasets(state, dataset)
    gates = market_gates(dataset, fixtures)
    team_audits = {
        competition: team_identity_audit(fixtures, competition=competition)
        for competition in ("Serie A", "UEFA Champions League")
    }
    ucl = [
        {**fixture, "canonical_phase": classify_ucl_phase(fixture.get("round"))}
        for fixture in fixtures
        if fixture["competition"] == "UEFA Champions League"
    ]
    ucl_main = [
        row
        for row in ucl
        if row["canonical_phase"]
        in {"GROUP_STAGE", "LEAGUE_PHASE", "KNOCKOUT", "FINAL"}
    ]
    ucl_qualifying = [
        row
        for row in ucl
        if row["canonical_phase"] in {"QUALIFYING", "PLAYOFF"}
    ]
    team_audits["UEFA Champions League"] = team_identity_audit(
        ucl_main,
        competition="UEFA Champions League",
    )
    write_json_atomic(
        state / "identity" / "team-alias-registry-v1.json",
        {
            "schema": "team-alias-registry-v1",
            "entries": [
                alias
                for audit in team_audits.values()
                for alias in cast(list[dict[str, object]], audit["aliases"])
            ],
        },
    )
    write_json_atomic(
        state / "datasets" / "ucl-main-competition-v1.json",
        {"dataset": "ucl_main_competition_v1", "rows": ucl_main},
    )
    write_json_atomic(
        state / "datasets" / "ucl-qualifying-v1.json",
        {"dataset": "ucl_qualifying_v1", "rows": ucl_qualifying},
    )
    readiness = player_and_lineup_gates(state, fixtures)
    storage = storage_readiness(state)
    odds_dry_run = odds_api_historical_dry_run(snapshots=0)
    strategy = strategy_lab_v4(gates)
    market_validation = market_paired_validation(state)
    hashes = [str(report["sha256"]) for report in writes]
    package = preseason_package_v2(
        code_revision=source_commit,
        market_gates_report=gates,
        dataset_hashes=hashes,
    )
    write_json_atomic(
        state / "packages" / "preseason-shadow-package-v2.json",
        package,
    )
    result: dict[str, object] = {
        "milestone": "JALON_9",
        "run_id": run_id,
        "source_commit": source_commit,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "football_data_files_downloaded": len(manifests),
        "football_data_files_available": len(
            list((state / "market" / "raw").rglob("*.metadata.json"))
        ),
        "raw_market_rows": len(raw_market),
        "market_dataset_rows": len(dataset),
        "market_dataset_writes": writes,
        "matching": matching,
        "market_gates": gates,
        "team_gates": team_audits,
        "ucl_phases": {
            "main": len(ucl_main),
            "qualifying": len(ucl_qualifying),
            "unknown": sum(row["canonical_phase"] == "UNKNOWN" for row in ucl),
        },
        **readiness,
        "odds_api_historical_pilot": odds_dry_run,
        "storage": storage,
        "strategy_lab_v4": strategy,
        "market_paired_validation": market_validation,
        "preseason_package": package,
        "provider_calls": 0,
        "odds_api_credits_consumed": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
    write_json_atomic(state / "market" / "runs" / "jalon9-latest.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", default="LOCAL")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Rejouer uniquement les archives déjà conservées.",
    )
    args = parser.parse_args()
    result = execute(
        args.state,
        run_id=str(args.run_id),
        source_commit=str(args.source_commit),
        download=not bool(args.no_download),
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "market_dataset_rows": result["market_dataset_rows"],
                "matching": result["matching"],
                "storage": result["storage"],
                "provider_calls": result["provider_calls"],
                "odds_api_credits_consumed": result[
                    "odds_api_credits_consumed"
                ],
                "production_status": result["production_status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
