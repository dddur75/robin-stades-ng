"""Construire et exécuter le notebook de preuve qualité du jalon 1."""

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient


def build() -> Path:
    root = Path(__file__).resolve().parents[1]
    target = root / "notebooks" / "jalon1_data_quality.ipynb"
    notebook = nbf.v4.new_notebook(
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        }
    )
    notebook.cells = [
        nbf.v4.new_markdown_cell(
            """# Audit qualité du jalon 1

## tl;dr

Le dataset versionné contient **36 423 matchs**. L'audit reproductible identifie
**24 segments** `SUSPECT_ZERO`, soit **7 936 valeurs** conservées mais exclues par
défaut des modèles concernés. Elles se concentrent sur F2, N1 et P1 en 2015-16 et
2016-17. Aucun doublon `match_id`, score final manquant ou match futur n'est détecté."""
        ),
        nbf.v4.new_markdown_cell(
            """## Context & Methods

Objectif : vérifier le grain match, l'unicité, la complétude temporelle et les
zéros historiquement imputés. Le fichier source est `data/matches.parquet`.

### Key Assumptions

- grain attendu : un match terminé par ligne ;
- `match_id` est la clé legacy à auditer, pas la future identité interne ;
- un couple de statistiques intégralement nul sur une ligue-saison est suspect,
  jamais corrigé automatiquement."""
        ),
        nbf.v4.new_markdown_cell("## Data\n\n### 1. Charger et profiler"),
        nbf.v4.new_code_cell(
            """from datetime import UTC, datetime
from pathlib import Path
import pandas as pd
from robin.quality.checks import run_match_checks
from robin.quality.zero_audit import audit_suspect_zeros

root = Path.cwd()
matches = pd.read_parquet(root / "data" / "matches.parquet")
profile = {
    "rows": len(matches),
    "columns": len(matches.columns),
    "date_min": str(matches["date"].min()),
    "date_max": str(matches["date"].max()),
    "leagues": matches["league"].nunique(),
    "seasons": matches["season"].nunique(),
    "duplicate_match_id": int(matches["match_id"].duplicated().sum()),
}
pd.Series(profile, name="value")"""
        ),
        nbf.v4.new_markdown_cell("## Results\n\n### 2. Détecter les zéros suspects"),
        nbf.v4.new_code_cell(
            """audit = audit_suspect_zeros(matches, provider="football-data.co.uk")
audit_frame = pd.DataFrame([row.model_dump(mode="json") for row in audit])
suspect = audit_frame[audit_frame["quality_status"] == "SUSPECT_ZERO"]
summary = {
    "segments_audited": len(audit_frame),
    "suspect_segments": len(suspect),
    "suspect_values": int(suspect["zeros"].sum()),
}
pd.Series(summary, name="value")"""
        ),
        nbf.v4.new_code_cell(
            """suspect.groupby(
    ["competition", "season"], as_index=False
).agg(columns=("column", "count"), suspect_values=("zeros", "sum"))"""
        ),
        nbf.v4.new_markdown_cell("### 3. Exécuter les contrôles de confiance"),
        nbf.v4.new_code_cell(
            """checks = run_match_checks(
    matches,
    audit,
    as_of_time=datetime(2026, 7, 24, 23, 59, tzinfo=UTC),
)
pd.DataFrame([check.model_dump(mode="json") for check in checks])[
    ["check_name", "status", "severity", "observed_value", "affected_rows"]
]"""
        ),
        nbf.v4.new_markdown_cell(
            """## Takeaways

- Le grain historique est unique sur `match_id`, mais cette clé reste à remplacer
  par l'identité interne stable du jalon 1.
- Les 7 936 zéros suspects ne sont ni supprimés ni remplacés : leur statut qualité
  les exclut des features concernées.
- Les rapports Vague 2/Vague 2B antérieurs utilisant ces segments restent
  `UNVERIFIED`.
- La preuve détaillée est exportée dans `docs/data-quality/`."""
        ),
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    client = NotebookClient(notebook, timeout=120, kernel_name="python3")
    executed = client.execute(cwd=str(root))
    nbf.write(executed, target)
    return target


if __name__ == "__main__":
    print(build())
