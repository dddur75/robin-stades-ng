# Dictionnaire de données

Statut : `VERIFIED` pour le schéma Jalon 1 ; `PARTIAL` pour la migration du
dataset historique.

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
- UUID internes et provenance brute absents : migration encore nécessaire.

Une donnée absente n'est jamais convertie en zéro. Les zéros suspects restent
visibles et sont masqués par défaut pour les modèles concernés.
