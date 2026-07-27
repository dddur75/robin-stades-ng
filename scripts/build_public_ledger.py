"""Auditer la chaîne append-only avant toute construction Robin Live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.patterns.ledger import EvidenceLedger


def build_public_summary(ledger: EvidenceLedger) -> dict[str, object]:
    """Construire le résumé public complet après audit de la chaîne."""

    audit = ledger.audit()
    if audit.get("production_status") != "PRODUCTION_LOCKED":
        raise RuntimeError("PUBLIC_LEDGER_PRODUCTION_LOCK_REQUIRED")
    if audit.get("real_bets") is not False:
        raise RuntimeError("PUBLIC_LEDGER_REAL_BETS_FORBIDDEN")
    if audit.get("social_publishing_enabled") is not False:
        raise RuntimeError("PUBLIC_LEDGER_SOCIAL_PUBLISHING_FORBIDDEN")
    if audit.get("no_bet_default") is not True:
        raise RuntimeError("PUBLIC_LEDGER_NO_BET_DEFAULT_REQUIRED")

    settled_stake_units = float(str(audit["settled_stake_units"]))
    return {
        "status": str(audit["status"]),
        "published_at": audit["published_at"],
        "records": int(str(audit["records"])),
        "decisions": int(str(audit["decisions"])),
        "shadow_bets": int(str(audit["shadow_bets"])),
        "no_bets": int(str(audit["no_bets"])),
        "settlements": int(str(audit["settlements"])),
        "won": int(str(audit["won"])),
        "lost": int(str(audit["lost"])),
        "void": int(str(audit["void"])),
        "matches_analyzed": int(str(audit["matches_analyzed"])),
        "shadow_bankroll": float(str(audit["shadow_bankroll"])),
        "bankroll_curve": audit["bankroll_curve"],
        "profit_units": float(str(audit["profit_units"])),
        "settled_stake_units": settled_stake_units,
        "roi": (
            float(str(audit["roi"]))
            if settled_stake_units > 0
            else None
        ),
        "max_drawdown_units": float(str(audit["max_drawdown_units"])),
        "last_record_hash": str(audit["last_record_hash"]),
        "production_status": str(audit["production_status"]),
        "real_bets": bool(audit["real_bets"]),
        "no_bet_default": bool(audit["no_bet_default"]),
        "social_publishing_enabled": bool(
            audit["social_publishing_enabled"]
        ),
        "demo_mode_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = build_public_summary(EvidenceLedger(args.ledger))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
