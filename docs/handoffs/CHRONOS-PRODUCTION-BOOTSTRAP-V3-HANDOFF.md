# Robin Chronos Production Bootstrap V3 — handoff

Autorité courante: cette mission et le runbook
`docs/operations/CHRONOS-PRODUCTION-BOOTSTRAP-V3.md`.

Le handoff PR41 antérieur est classé
`SUPERSEDED_BY_CHRONOS_PRODUCTION_BOOTSTRAP_V3`. Il reste une preuve historique
et ne doit plus autoriser une migration ou une réactivation de workflow.

État d’entrée vérifié:

- `main`: `8591024b1ef96d766ab0e1090c45d15e3a25d429`;
- PR39 fermée non fusionnée; PR40, PR41 et PR42 fusionnées;
- Environment présent et deux secrets bootstrap présents par nom;
- hold: 14 actifs, 61 désactivés, aucune queue ni exécution;
- legacy `DATABASE_URL`: `LEGACY_DATABASE_URL_QUARANTINED`;
- fournisseur, odds, R2 et PostgreSQL distant utilisés par la préparation: zéro.

Ordre immuable: PR + CI, merge, PREFLIGHT, contrôle artifact, MIGRATE unique,
installation scoped, VERIFY, canari provider-free, replay sans réseau, cleanup.

Le prochain handoff fournisseur ne devient autoritaire qu’après la preuve du
canari provider-free et doit nommer une fixture et un cutoff réellement dus.
