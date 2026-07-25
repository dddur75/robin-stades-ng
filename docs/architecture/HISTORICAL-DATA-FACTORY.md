# Architecture — Historical Data Factory

```text
API-Football
  → payload brut gzip immuable (SHA-256)
  → observation expurgée des secrets
  → pagination + checkpoint
  → normalisation avec UUID interne
  → Parquet partitionné
  → qualité et politique point-in-time
  → datasets versionnés
  → modèles et backtests OOS
  → snapshot Deep Data Cockpit
```

PostgreSQL conserve les identités, manifests, tâches, qualités, définitions de
features et résultats synthétiques. Parquet conserve les faits volumineux. La
branche `shadow-data` conserve le pont durable tant qu’aucun stockage objet
supplémentaire n’est autorisé. Les GitHub Artifacts ne sont qu’une reprise
courte.

Les pipelines historiques utilisent leurs propres workflows, budgets, états et
répertoires. Ils ne modifient pas les fenêtres ni le quota de The Odds API.

