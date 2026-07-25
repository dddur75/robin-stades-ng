# Deep Data Cockpit

## Extension Jalon 5.1

Le snapshot expose tâches totales/terminées/restantes, appels observés et
estimés, débit, ETA A/B/globale, fichiers/bundles/payloads/Parquet, volume
actuel et projeté, capacité, canonicalité 310/306 et 21/18, branches et groupes
de concurrence, conflit/retard ainsi que la readiness joueurs
`BLOCKED_BY_COVERAGE`. Les anomalies restent visibles comme compteurs séparés.

Le Cockpit Live V2 comprend désormais :

- Deep Data Command Center ;
- Backfill Monitor ;
- Player Explorer ;
- Feature Lab ;
- Model Lab ;
- Backtest Explorer ;
- Historical Data Quality.

Le snapshot est généré côté workflow. Aucun secret Neon ou fournisseur n’entre
dans le bundle frontend. Les origines `LIVE SHADOW`, `HISTORICAL POINT-IN-TIME`,
`HISTORICAL SIMULATED`, `OOS HISTORICAL`, `LEGACY SOURCE`, `DEMO DATA` et
`NO OUTPUT` restent contractuellement distinctes.
