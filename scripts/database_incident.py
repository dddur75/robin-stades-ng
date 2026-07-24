"""Journaliser sans secret la disponibilité du stockage PostgreSQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.operations.burn_in import AlertSeverity, IncidentJournal


def update_incident(state: Path, *, status: str, source_run_id: str) -> dict[str, object]:
    journal = IncidentJournal(state / "incidents" / "history.jsonl")
    if status == "FAILED":
        changed = journal.open(
            code="POSTGRESQL_WRITE_FAILED",
            severity=AlertSeverity.CRITICAL,
            cause="PostgreSQL indisponible ou écriture refusée",
            impact=(
                "données conservées dans shadow-data ; synchronisation SQL en attente"
            ),
            source_run_id=source_run_id,
        )
        return {
            "status": "INCIDENT_OPEN",
            "changed": changed,
            "recovery": "REPLAY_REGISTRY_ON_NEXT_RUN",
        }
    changed = journal.resolve(
        code="POSTGRESQL_WRITE_FAILED",
        correction="registre shadow-data rejoué vers PostgreSQL",
    )
    return {
        "status": "POSTGRESQL_HEALTHY",
        "changed": changed,
        "recovery": "UP_TO_DATE",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--status", choices=("SUCCESS", "FAILED"), required=True)
    parser.add_argument("--source-run-id", required=True)
    args = parser.parse_args()
    result = update_incident(
        args.state,
        status=args.status,
        source_run_id=args.source_run_id,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
