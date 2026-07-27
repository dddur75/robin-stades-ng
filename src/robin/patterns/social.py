"""Exports sociaux normalisés; aucun adaptateur réseau n'est activé."""

from __future__ import annotations

import json
from pathlib import Path

from robin.patterns.ledger import SOCIAL_PUBLISHING_ENABLED

FORBIDDEN_PUBLIC_CLAIMS = (
    "pari sûr",
    "gain garanti",
    "stratégie infaillible",
    "quasi-certitude",
    "argent facile",
    "100 % gagnant",
)

EXPORT_FILES = (
    "daily_picks.json",
    "daily_results.json",
    "weekly_bankroll.json",
    "experiment_update.json",
    "rejected_pattern.json",
)


def validate_public_text(text: str) -> None:
    folded = text.casefold()
    for forbidden in FORBIDDEN_PUBLIC_CLAIMS:
        if forbidden.casefold() in folded:
            raise ValueError(f"FORBIDDEN_PUBLIC_CLAIM:{forbidden}")
    if "shadow" not in folded and "aucune garantie" not in folded:
        raise ValueError("PUBLIC_TEXT_MUST_STATE_SHADOW_OR_NO_GUARANTEE")


def build_disabled_exports(
    destination: Path,
    *,
    ledger_url: str,
) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    templates = {
        "daily_picks.json": "Test shadow du jour — aucune garantie.",
        "daily_results.json": "Bilan shadow complet, pertes incluses — aucune garantie.",
        "weekly_bankroll.json": "Bankroll shadow fictive — aucune garantie.",
        "experiment_update.json": "Hypothèse en recherche shadow — aucune garantie.",
        "rejected_pattern.json": "Pattern historique rejeté — aucune garantie.",
    }
    created: list[Path] = []
    for filename in EXPORT_FILES:
        message = templates[filename]
        validate_public_text(message)
        payload = {
            "schema_version": "social-export-v1",
            "publishing_enabled": SOCIAL_PUBLISHING_ENABLED,
            "status": "SHADOW_ONLY",
            "message_template": message,
            "public_ledger": ledger_url,
            "negative_results_included": True,
        }
        path = destination / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        created.append(path)
    return created
