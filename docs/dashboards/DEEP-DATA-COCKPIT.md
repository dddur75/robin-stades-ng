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

## Frontière de publication post-fusion

Le workflow 26 construit et teste le Cockpit, publie l'artefact et inclut le
snapshot JSON nettoyé. Il publie trois états distincts :

- `COCKPIT_BUILD_SUCCESS` ;
- `COCKPIT_ARTIFACT_PUBLISHED` ;
- `COCKPIT_PRIVATE_DEPLOYMENT_REQUIRED` tant que la version Sites privée n'a
  pas été déployée.

Le quota, les appels, les lignes et l'horodatage viennent désormais du dernier
lot historique, pas du pilote. Les ETA sont recalculées depuis les tâches et
appels réellement restants. La readiness est publiée séparément pour chaque
famille de données joueurs.

Preuve d'activation : le workflow `30151317894` a produit l'artefact
`8617713588`, puis le snapshot a été déployé sur le Cockpit privé Sites en
version 8. L'accès reste limité au propriétaire.
