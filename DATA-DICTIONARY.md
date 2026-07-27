# Dictionnaire de données

## Schéma Jalon 5

La révision `0004_jalon5_deep_data_factory` ajoute 31 tables de contrôle :
couverture, runs, tâches, référentiels, saisons équipes/joueurs, événements,
statistiques, compositions, blessures, transferts, feature store, datasets,
entraînements, modèles, backtests et stratégies. Les faits volumineux restent
en Parquet ; PostgreSQL conserve leurs manifests, hashes et statuts.

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
# Extensions durables Jalon 4

Le schéma Alembic `0003_jalon4_durable_shadow` ajoute les entités suivantes :

| Entité | Grain | Clé d’idempotence principale |
|---|---|---|
| `ingestion_runs` | une exécution de pipeline | `run_id` |
| `raw_payloads` | un contenu brut unique | `payload_hash` |
| `provider_requests` | une requête fournisseur | fournisseur + endpoint + temps |
| `durable_fixtures` | une version de fixture | fixture interne + version |
| `provider_entity_mappings` | un mapping valide dans le temps | fournisseur + type + id |
| `odds_snapshots` | une observation de marché | fixture + marché + bookmaker + temps |
| `prediction_runs` | une exécution de modèle | run + modèle + version |
| `predictions` | une prédiction immuable | fixture + as-of + modèle |
| `candidate_bets` | une opportunité évaluée | prédiction + sélection + stratégie |
| `rejected_bets` | un rejet motivé | candidat + code |
| `shadow_bets` | un pari simulé accepté | candidat |
| `settlements` | une version de règlement | pari + version |
| `quality_runs/results` | un contrôle et ses résultats | run + contrôle |
| `pipeline_incidents` | une version d’incident | code + instant |
| `quota_usage` | un relevé fournisseur | fournisseur + période + instant |
| `scheduler_windows` | une fenêtre par fixture | fixture + code fenêtre |
| `burn_in_daily_metrics` | un relevé quotidien | date |

Les tables append-only portent `created_at`, les références de run et les
versions nécessaires. Les payloads bruts sont référencés par SHA-256 ; ils ne
sont jamais écrasés.

## Datasets Jalon 6

| Objet | Grain | Temporalité |
|---|---|---|
| `api_team_pre_match_v1` | une fixture | point-in-time avant kickoff |
| `api_player_match_facts_v1` | joueur × fixture | `POST_MATCH_ONLY` |
| `player_feature_store_v1` | feature × joueur × fixture | `PRE_LINEUP` |
| `api_player_pre_lineup_v1` | une fixture | `PRE_LINEUP` |
| `api_post_lineup_simulated_v1` | une fixture | `POST_LINEUP_SIMULATED` |
| `api_market_baseline_v1` | fixture × marché | `HISTORICAL_CLOSING_MARKET` |

Chaque manifest porte `dataset_version`, saisons, lignes, fixtures, features,
cibles, couverture, qualité, politique temporelle, révision et SHA-256.

## Datasets Jalon 9

| Dataset | Grain | Temporalité |
|---|---|---|
| `historical_market_v1` | fixture × source | prix source documenté |
| `historical_market_1x2_v1` | fixture × 1X2 | closing sinon pre-closing |
| `historical_market_totals_v1` | fixture × ligne 2,5 | closing sinon pre-closing |
| `ucl_main_competition_v1` | fixture UCL principale | post-match |
| `ucl_qualifying_v1` | fixture UCL qualifications | post-match |

`business_value_priority` est distinct de `priority`. `provider_fixture_id`
conserve le contexte de requête pour les statistiques joueurs et lineups.

## Entités Jalon 10

La révision Alembic `0006_jalon10_pattern_ledger` ajoute :

| Entité | Grain | Clé d’idempotence |
|---|---|---|
| `pattern_definitions` | une version immuable de règle | pattern + version ; hash + version |
| `pattern_runs` | une campagne ou un replay | `idempotency_key` |
| `pattern_evaluations` | règle × fold/périmètre | run + règle + fold |
| `pattern_decisions` | décision pré-match gelée | `decision_id` |
| `pattern_settlements` | règlement séparé | `settlement_id` |
| `bankroll_events` | variation shadow | événement / règlement |
| `evidence_ledger` | record de chaîne append-only | hash du record |
| `experiment_registry` | version d’expérience | identifiant + version |

Une définition porte conditions canoniques, source, cutoff, evidence scope,
statut, révision et hashes. Une évaluation porte support, métriques à mise fixe,
intervalle, q-value, stabilité et motifs de rejet.

Une décision contient `published_at < kickoff_at`, la cote réellement observée
ou `null`, le motif `BET`/`NO_BET`, la bankroll avant, `simulation=true`, le
hash précédent et le hash courant. Le règlement est un nouvel événement ; il
ne modifie jamais la décision.

## Corpus marché du Pattern Research Engine

| Dataset logique | Lignes strictes | Temporalité |
|---|---:|---|
| `historical_market_v1` apparié | 10 732 | `DISCOVERY_EXPOSED` |
| 1X2 strict courant | 10 732 | `SOURCE_PRICE_CLASS_ONLY` |
| Over/Under 2,5 | 10 732 | `SOURCE_PRICE_CLASS_ONLY` |

Le snapshot de cache courant contient 10 732 lignes 1X2 strictes. Il n’existe
pas de timestamp intrajournalier fiable pour ces prix. Aucun BTTS, handicap,
corner, carton, buteur ou prop joueur n’est créé sans cote historique observée.

## Entités Jalon 11

La révision Alembic `0008_jalon11_deep_football` définit :

Il s'agit de la révision cible présente dans le code. La dernière preuve Neon
préflight reste `0007_jalon10_immutable_evidence`; cette section ne revendique
pas l'application live de 0008.

| Entité | Grain | Rôle |
|---|---|---|
| `deep_feature_definitions` | contrat de feature versionné | schéma, cutoff, gate et hash |
| `deep_feature_observations` | valeur feature × entité × fixture | observation point-in-time |
| `coverage_gates` | gate × périmètre × dataset | preuve de disponibilité |
| `matchup_hypotheses` | hypothèse préenregistrée | mécanisme, marchés, support, hash |
| `matchup_evaluations` | hypothèse × campagne/fold | métriques et décision scientifique |
| `prospective_watchlist` | version de règle surveillée | suivi sans pari ni mise |
| `shadow_candidate_versions` | package candidat immuable | décision fail-closed |

Tous les objets portent version de dataset, révision de code, timestamps UTC et
hashes. Les preuves sont append-only et idempotentes.

## Dataset `TEAM_PREMATCH`

Grain : une fixture avec état domicile/extérieur émis avant la mise à jour par
le résultat du match cible. La frontière de matérialisation est égale au
kickoff ; le `source_observed_at` ligne par ligne n'est pas prouvé. Champs
principaux : identifiants ligue/saison/fixture, kickoff, labels de résultat
séparés, probabilités de marché, différence Elo, formes 5/10, buts pour/contre
5, repos et indicateurs de missingness.

Le dataset courant contient 10 732 lignes ; son hash est
`2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6`.
Son SHA-256 Parquet est
`d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673`.
`TEAM_GATE=PARTIAL` limite ce dataset aux diagnostics rétrospectifs.
Les datasets joueurs, lineup, formation et pied fort restent bloqués et
n'existent pas sous une forme artificiellement complétée.
