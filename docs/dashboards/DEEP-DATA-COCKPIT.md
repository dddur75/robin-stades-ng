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
- `COCKPIT_PRIVATE_DEPLOYED` lorsque le run historique correspond à la version
  privée ;
- `COCKPIT_PRIVATE_STALE` lorsque l’artefact est plus récent.

Le quota, les appels, les lignes et l'horodatage viennent désormais du dernier
lot historique, pas du pilote. Les ETA bas/central/haut incluent les tâches
matérialisées, les enfants fixture/équipe et les pages futures. L’ancienne ETA
matérialisée reste visible sous `MATERIALIZED_TASKS_ONLY`. La readiness publie,
par famille, compétitions, saisons, équipes, fixtures, joueurs, taux de null,
identités, qualité et temporalité.

Preuve d'activation : le workflow `30151317894` a produit l'artefact
`8617713588`, puis le snapshot a été déployé sur le Cockpit privé Sites en
version 8. L'accès reste limité au propriétaire.

Le déploiement Sites privé est officiellement disponible depuis le connecteur
Codex, mais pas depuis GitHub Actions dans la configuration actuelle. Le
workflow ne simule donc aucun déploiement et conserve l’artefact automatique.
Voir `docs/operations/COCKPIT-PRIVATE-DEPLOYMENT.md`.

## Snapshot Jalon 5.2

Le snapshot corrigé après le lot `30154099512` et la qualité
`30155383297` expose :

- 6 222 tâches, 2 655 terminées, 3 567 restantes ;
- 47 417 / 63 313 / 69 977 appels restants ;
- ETA globale 1,58 / 2,11 / 2,33 jours ;
- 55 344 tâches fixture, 3 036 tâches équipe et 1 677 pages latentes ;
- 41 672 lignes de provenance contrôlées ;
- 4 149 payloads, 48 partitions Parquet et 8 bundles dans l’état restauré ;
- stockage restauré 65,2 MB et projection haute 665,3 MB ;
- readiness globale `BLOCKED_BY_COVERAGE` ;
- version privée 8, accès `OWNER_ONLY`, statut
  `COCKPIT_PRIVATE_STALE`.

Le workflow `30155451951` a construit le frontend et publié l’artefact
`8618862988` depuis `main`. Il s’agit d’une preuve de build/artefact, pas d’un
redéploiement privé.
