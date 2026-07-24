"""Diagnostic read-only du stockage, des secrets, quotas et fenêtres dues."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text

from robin.storage.database import (
    DatabaseConfigurationError,
    build_engine,
    normalize_database_url,
)

if __package__:
    from scripts.manage_durable_registry import read_json, verify_registry
else:
    from manage_durable_registry import read_json, verify_registry


def diagnose(state: Path, registry: Path) -> dict[str, object]:
    runs = [
        read_json(path, {})
        for path in sorted((state / "runs").glob("*.json"))
    ]
    latest_run = runs[-1] if runs else {}
    scheduler = read_json(state / "scheduler" / "latest.json", [])
    due = [
        item
        for item in scheduler if isinstance(item, dict)
        and item.get("status") in {"DUE", "MISSED_RECOVERABLE"}
    ] if isinstance(scheduler, list) else []
    database_url = os.getenv("ROBIN_DATABASE_URL")
    database: dict[str, object] = {
        "configured": bool(database_url),
        "connected": False,
        "tables": 0,
        "write_test": "NOT_RUN_READ_ONLY",
    }
    if database_url:
        try:
            normalized_url = normalize_database_url(database_url)
            engine = build_engine(normalized_url)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database.update(
                connected=True,
                tables=len(inspect(engine).get_table_names()),
                driver="postgresql+psycopg",
                error_code=None,
            )
        except DatabaseConfigurationError:
            database.update(error_code="INVALID_DATABASE_CONFIGURATION")
        except Exception:  # diagnostic borné : ne jamais sérialiser l'exception
            database.update(error_code="DATABASE_UNAVAILABLE")
    registry_result = verify_registry(registry)
    status = (
        "PASSED"
        if registry_result["status"] == "PASSED"
        and (database["connected"] or registry_result["bundles"])
        else "PARTIAL"
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "mode": "READ_ONLY",
        "secrets": {
            "ODDS_API_KEY": "AVAILABLE" if os.getenv("ODDS_API_KEY") else "ABSENT",
            "API_FOOTBALL_KEY": (
                "AVAILABLE" if os.getenv("API_FOOTBALL_KEY") else "ABSENT"
            ),
            "DATABASE_URL": "AVAILABLE" if database_url else "ABSENT",
        },
        "providers": {
            "the_odds_api": (
                "SECRET_AVAILABLE" if os.getenv("ODDS_API_KEY") else "ADAPTER_ONLY"
            ),
            "api_football": (
                "SECRET_AVAILABLE"
                if os.getenv("API_FOOTBALL_KEY")
                else "ADAPTER_ONLY"
            ),
        },
        "database": database,
        "durable_registry": registry_result,
        "latest_observation": latest_run.get("finished_at"),
        "quota_used": latest_run.get("quota_used"),
        "quota_remaining": latest_run.get("quota_remaining"),
        "windows_due": len(due),
        "production_status": "PRODUCTION_LOCKED",
    }


def markdown(report: dict[str, object]) -> str:
    secrets = report["secrets"]
    database = report["database"]
    registry = report["durable_registry"]
    assert isinstance(secrets, dict)
    assert isinstance(database, dict)
    assert isinstance(registry, dict)
    return "\n".join(
        [
            "# Diagnostic shadow",
            "",
            f"Statut : `{report['status']}`",
            "Mode : lecture seule",
            "Production : `PRODUCTION_LOCKED`",
            "",
            f"- registre durable : {registry['status']} ;",
            f"- bundles : {registry['bundles']} ;",
            f"- PostgreSQL configuré : {database['configured']} ;",
            f"- The Odds API : {secrets['ODDS_API_KEY']} ;",
            f"- API-Football : {secrets['API_FOOTBALL_KEY']} ;",
            f"- fenêtres dues : {report['windows_due']} ;",
            f"- quota restant : {report['quota_remaining']} ;",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(args.state, args.registry)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "diagnostic.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    (args.output / "diagnostic.md").write_text(markdown(result), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
