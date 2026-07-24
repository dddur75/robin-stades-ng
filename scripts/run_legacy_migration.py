"""Générer les artefacts mesurés de migration legacy vers UUID."""

from pathlib import Path

import pandas as pd

from robin.migration.legacy import migrate_legacy_frame, write_migration_artifacts


def main() -> None:
    frame = pd.read_parquet("data/matches.parquet")
    mappings, summary = migrate_legacy_frame(frame)
    output = Path("data/migrations/jalon2")
    write_migration_artifacts(mappings, summary, output)
    print(
        f"{summary.rows_examined} lignes, {summary.mappings_total} mappings, "
        f"couverture certaine {summary.certain_coverage:.2%}, "
        f"{summary.collisions} collision"
    )


if __name__ == "__main__":
    main()
