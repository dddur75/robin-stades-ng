# Dictionnaire de données

Statut : `VERIFIED` pour les schémas Jalons 1 et 2 ; la provenance historique
reste `LEGACY SOURCE`.

## Snapshot de cote Jalon 2

Grain : une observation immuable de plusieurs cotations d'un même événement.

Champs minimaux : `snapshot_id`, `fixture_id`, `provider`, `bookmaker_id`,
`market_type`, `market_scope`, `selection`, `line_value`, `odds_decimal`,
`observed_at_utc`, `fixture_kickoff_at_utc`, `time_to_kickoff_seconds`,
`is_live`, `raw_payload_id`, `quality_status` et `ingestion_run_id`.

Une ouverture est la première observation disponible, pas une affirmation sur
l'ouverture commerciale du bookmaker. Une clôture approchée est la dernière
observation pré-match disponible dans les fenêtres configurées.

## Prédiction, décision et migration

Une prédiction est immuable et porte `prediction_id`, `fixture_id`,
`generated_at`, `as_of_time`, versions, probabilités 1N2, buts attendus,
qualité, incertitude et éventuel `market_snapshot_id`. Une décision ajoute
sélection, cote, probabilité implicite, edge, stratégie, mise fictive et motifs
normalisés. `simulation` vaut toujours `true`.

Les statuts de migration sont `EXACT`, `PROVIDER_CONFIRMED`, `RULE_MATCHED`,
`PROBABLE`, `AMBIGUOUS`, `UNRESOLVED` et `REJECTED`. `PROBABLE` est conservé
mais exclu par défaut des modèles exigeant une identité certaine.

## Instants temporels

Tous les instants normalisés sont UTC.

| Champ | Définition |
|---|---|
| `fixture_created_at` | première connaissance interne du match |
| `fixture_kickoff_at` | coup d'envoi prévu pour la version du fixture |
| `data_observed_at` | instant où l'information est vraie/observable à la source |
| `data_ingested_at` | instant de réception dans le système |
| `prediction_generated_at` | instant immuable de création de la prédiction |
| `odds_observed_at` | instant de lecture de la cote |
| `lineup_confirmed_at` | instant de confirmation de composition |
| `result_confirmed_at` | instant de confirmation du résultat |

Une feature exige `data_observed_at < as_of_time`.

## Entités et identités

Entités internes : compétition, saison, équipe, joueur, arbitre, fixture,
bookmaker, marché, sélection, snapshot de cote, prédiction, stratégie et version
de modèle.

Les correspondances fournisseur portent :
`internal_entity_id`, `provider_name`, `provider_entity_id`, `valid_from`,
`valid_to`, `mapping_status`, `mapping_confidence`, `mapping_method` et
`review_status`.

## Observation brute

Grain : une réponse fournisseur reçue.

Champs contractuels : `provider`, `endpoint`, `request_parameters`,
`requested_at`, `received_at`, `http_status`, `payload_hash`, `schema_version`,
`ingestion_run_id` et `raw_payload_location`.

## Feature

Grain : une valeur versionnée pour une entité et un fixture.

Champs contractuels : `feature_name`, `entity_id`, `fixture_id`, `value`,
`as_of_time`, `calculated_at`, `source_version`, `feature_version` et
`quality_status`.

## Marchés et paris

Une clé de marché contient `market_type`, `market_scope`, `selection`,
`line_value`, `period` et `settlement_rule_version`. Une cote ajoute bookmaker,
format, instant d'observation et phase ouverture/intermédiaire/clôture.

Le cycle métier sépare opportunité, cotation bookmaker, pari sélectionné et pari
réglé. Les résultats possibles incluent gain, perte, remboursement, annulation et
non réglé.

## Qualité

Statuts de valeur : `OBSERVED`, `DERIVED`, `MISSING`, `NOT_APPLICABLE`,
`SUSPECT_ZERO`, `CORRECTED`, `CONFLICTING`.

Un contrôle porte `check_name`, `run_id`, `status`, `severity`, `scope`,
`observed_value`, `expected_rule`, `affected_rows`, `started_at`, `finished_at`
et `evidence_location`.

## Dataset historique — `data/matches.parquet`

Grain : un match terminé. Clé legacy : `match_id`.

- 36 423 lignes, 27 colonnes, 9 ligues, 11 saisons ;
- résultats finaux complets et identifiants uniques ;
- champs mi-temps, cartons et corners après match : `hthg`, `htag`, `hy`, `ay`,
  `hr`, `ar`, `hc`, `ac` ;
- cotes historiques sans horodatage suffisamment précis ;
- correspondances UUID produites dans
  `data/migrations/jalon2/legacy-uuid-mappings.parquet`, sans réécriture du
  Parquet source ;
- provenance brute historique toujours absente : origine `LEGACY SOURCE`.

Une donnée absente n'est jamais convertie en zéro. Les zéros suspects restent
visibles et sont masqués par défaut pour les modèles concernés.
