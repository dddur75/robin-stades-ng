# ROBIN Point-in-Time Lineage V1

## Résumé technique — réponses immédiates

Verdict global : `ROBIN_POINT_IN_TIME_LINEAGE_V1_PARTIAL`.

LOOP 55 fixe et documente le dénominateur temporel E2013, introduit un contrat
prospectif fail-closed vérifiable sur un périmètre borné et refuse de requalifier
l’historique. Il ne prouve pas le chemin décisionnel de production de bout en bout.
Le verrou de production, l’absence de promotion et le défaut d’autorisation de pari
restent explicites.

| Question | Réponse | Portée de la preuve |
| --- | ---: | --- |
| Combien de surfaces temporelles existent réellement ? | **72** | Dénominateur exact de la sélection E2013 : 35 surfaces fichier et 37 surfaces PostgreSQL. Ce nombre n’est pas présenté comme un inventaire exhaustif de tout stockage actuel. |
| Combien sont prouvées historiquement ? | **0/72** | Aucun reçu d’observation immuable ne borne l’ensemble des entrées avant le cutoff. |
| Combien sont seulement receipt-bounded ? | **0/72** | E2013 ne fournit aucun objet-reçu historique permettant cette qualification. |
| Combien sont non prouvables rétroactivement ? | **72/72** | 19 `RECONSTRUCTED_NOT_PROVEN` et 53 `UNKNOWN`; aucune date métier, mtime, date Git ou position dans un fichier n’est convertie en reçu. |
| Combien sont prospectivement fail-closed ? | **7 symboles bornés; 0 chemin actif de production prouvé de bout en bout** | Les preuves bornées couvrent sept symboles. Les champs JSON, R2 et JSONL existants suffisent aux chemins couverts, mais le runtime complet n’est pas prouvé. |
| Quels feature builders résistent aux mutations du futur ? | **`freeze_feature_snapshot` et `build_team_feature_rows`, sur fixtures bornées** | Le snapshot reste immuable; les ajouts, suppressions, réordonnancements et modifications futures ne changent pas les features passées couvertes. `_latest_fixtures`, `asof_select` et `decide_shadow_bet` ferment aussi la sélection et le hash décisionnel couverts. |
| Quels chemins actifs restent non couverts ? | **10 symboles, 1 103 LOC bornées** | Builders historiques, backtest V3, collecte/settlement shadow et commandes historiques détaillés ci-dessous. |
| Combien de décisions historiques sont rejouables ? | **0/15 résultats logiques** | Soit 0/45 occurrences physiques publiées par LOOP 54. |
| Combien restent invalides ou non rejouables ? | **15/15 résultats logiques** | Les 45 occurrences sont `TEMPORAL_VALIDITY_NOT_PROVEN` / `POINT_IN_TIME_UNREPLAYABLE`; ce statut n’affirme pas que le calcul mathématique est faux. |
| Le chemin décisionnel est-il désormais prouvé point-in-time ? | **NON** | `PRODUCTION_DECISION_PATH_POINT_IN_TIME_STILL_NOT_PROVEN`. |

Statut de stockage : `NO_NEW_MIGRATION_REQUIRED_FOR_COVERED_PATHS`. Les chemins
couverts utilisent la provenance JSON et le manifest R2 content-addressed des features,
la chaîne snapshot odds–reçu–payload R2, le registre de modèle existant et le JSONL
append-only shadow. Les surfaces legacy ou non observées restent
`UNKNOWN_NOT_REVALIDATED`; cette capacité de stockage bornée ne prouve pas le runtime
complet et ne justifie aucune migration ou publication métier dans LOOP 55.

## Conclusions étayées

### Dénominateur et classification historique

La source normative est `AUDIT:E2013`, épinglée par les identifiants suivants :

- manifest SHA-256 : `38559704269d4e31b9406fc3ca90a8d8ba3fa4c16b0e8e8a89eaeaeaef6e5476`;
- révision auditée : `1ffeec1cd89e83deda008da39bb22540a70db896`;
- arbre Git : `d751c18ea6233ab59ffeb07c3a38453212a9dd87`;
- base immuable de revue LOOP 55 : `71833964e5d7ba7f5882bfff49b39d567fd5473b`.

Le pack LOOP55 final est scellé par le manifest
`07e3e8eeb62329bf0b79b1e0b5026a79f20c55e1aa122c4edb4b073999a8fd22`.
Son autorité source est
`ad864e0fb8345cc5864b79dc2671758e2dab1b2ec23b44a92b7267ac16656454`;
son manifest candidat lie 65 chemins inclus par l’agrégat
`dc75c24432852fa80cc41b89fba545f9b61b4905f7c9cddb9c823d911a88b05f`,
avec 15 sorties détachées sur 80 chemins modifiés et 0 chemin hors des 98 autorisés.

L’inventaire conserve les 72 lignes de `dataset-lineage.csv` et les 720 lignes de
`time-fields.csv`, soit exactement dix mappings temporels par surface. Les états de
matérialisation sont 27 `PRESENT`, 8 `ABSENT` et 37 `EXTERNAL_UNOBSERVED`. Les 37
surfaces PostgreSQL ont été inspectées au niveau du schéma par E2013; aucune ligne de
production n’a été lue pour LOOP 55.

Les classes historiques sont exclusives :

| Classe | Surfaces | Signification |
| --- | ---: | --- |
| `POINT_IN_TIME_PROVEN` | 0 | Reçus et disponibilité suffisants pour une preuve stricte. |
| `RECEIPT_BOUNDED` | 0 | Reçu historique bornant la disponibilité, sans preuve stricte complète. |
| `RECONSTRUCTED_NOT_PROVEN` | 19 | Reconstruction utile, explicitement non assimilée à un reçu. |
| `UNKNOWN` | 53 | Disponibilité historique inconnue. |
| `INVALID_AFTER_CUTOFF` | 0 | Aucune entrée n’a pu être classée ainsi avec la preuve observée. |

Le dénominateur au grain observation est séparé du dénominateur de surfaces. Les 27
surfaces E2013 matérialisées totalisent **104 254 observations** : 11 401
`RECONSTRUCTED_NOT_PROVEN` et 92 853 `UNKNOWN`, avec 0 observation
`POINT_IN_TIME_PROVEN`, `RECEIPT_BOUNDED` ou `INVALID_AFTER_CUTOFF`. Ce total n’est
pas global : les 8 surfaces absentes et les 37 surfaces PostgreSQL
`EXTERNAL_UNOBSERVED` ont un nombre d’observations `UNKNOWN_NOT_ENUMERABLE`.

### Contrat temporel prospectif

Le contrat distingue systématiquement :

- `event_at`, temps du fait métier;
- `source_published_at`, temps déclaré par la source, fiable seulement si sa
  sémantique et ses octets sont retenus dans un reçu;
- `robin_first_observed_at`, première observation attestée par Robin;
- `robin_ingested_at`, persistance chez Robin;
- `available_at`, maximum conservateur des temps de publication fiable et de première
  observation attestée;
- `computed_at`, temps du calcul, qui ne prouve jamais la disponibilité de la source;
- `cutoff_at`, frontière de décision ou de feature.

Une entrée est admissible seulement si son reçu est valide et si
`available_at <= cutoff_at`. Une égalité à la frontière est admissible. Une collision
au dernier `available_at` avec des payloads différents échoue avec
`ASOF_JOIN_AMBIGUOUS`. Une disponibilité absente ou auto-déclarée sans reçu échoue
avec `POINT_IN_TIME_INPUT_NOT_PROVEN`.

Les métriques préquentielles sont liées dans le rapport à
`PREQUENTIAL_METRIC_DEFINITION_V1_REPORT_BOUND` : log-loss naturel sur la
probabilité de l’issue, Brier normalisé par le nombre de sélections, ECE à dix bins
sur les paires one-vs-rest aplaties, coverage sur les heads scorés distincts,
missingness sur les flags fournis et delta de log-loss seulement lorsque l’arête
référence exacte existe. Les lignes métriques durables ne portent pas encore cette
version; toute agrégation entre révisions reste donc interdite et classée P2.

Les sept symboles couverts par les preuves bornées sont :

1. `asof_select` pour la sélection receipt-backed;
2. `freeze_feature_snapshot` pour la provenance et l’invariance du hash de feature;
3. `_latest_fixtures` pour l’exclusion d’une version enregistrée après le cutoff;
4. `PrequentialLearningFactory.forecast` pour la disponibilité du modèle;
5. `decide_shadow_bet` pour la lignée complète en mémoire et l’invariance du hash
   décisionnel;
6. `build_team_feature_rows` pour l’invariance des features historiques avant cutoff;
7. `_rolling_goal_rates` pour l’isolation des lots partageant le même kickoff.

La fermeture receipt-backed est désormais testée contre les octets persistés : un
`SourceReceipt` content-addressed est reconstruit depuis la provenance, son objet
repository ou R2 est relu avant forecast, un mapping seulement vraisemblable ou un
`receipt_id` auto-déclaré est rejeté et une ingestion postérieure au cutoff échoue
fermée. Cette preuve reste bornée au repository de test; elle ne prouve pas la capture
effective d’un runtime de production.

Cette couverture est une preuve locale déterministe. `_latest_fixtures` repose encore
sur `registered_at`; le chemin couvert lie par ailleurs features, odds et modèles aux
artefacts existants, et `ShadowDecision` sérialise sa lignée dans le JSONL append-only.
L’orchestration active complète n’est cependant pas couverte de bout en bout. Le statut prospectif est donc
`ROBIN_PROSPECTIVE_POINT_IN_TIME_FAIL_CLOSED_PARTIAL`, pas
`ROBIN_PROSPECTIVE_POINT_IN_TIME_FAIL_CLOSED`.

### Chemins actifs non couverts

La mesure AST bornée identifie 1 103 LOC non couvertes dans 10 symboles décisionnels :

- `src/robin/historical/dataset_factory.py::build_api_team_pre_match`;
- `src/robin/historical/dataset_factory.py::build_player_feature_datasets`;
- `src/robin/backtesting/v3.py::run_backtest`;
- `scripts/run_shadow_pipeline.py::collect_odds`;
- `scripts/run_shadow_pipeline.py::pre_match_shadow`;
- `scripts/run_shadow_pipeline.py::post_match_settlement`;
- `scripts/run_historical_pipeline.py::build_observed_forecast`;
- `scripts/run_historical_pipeline.py::command_features`;
- `scripts/run_historical_pipeline.py::command_train`;
- `scripts/run_historical_pipeline.py::command_backtest`.

Cette mesure décrit les spans de symboles audités; elle n’est ni une couverture de
lignes pytest globale, ni la preuve que chaque ligne influence une décision.

### Matrice de mutation et replay historique

La matrice normative exécute ses 25 classes adversariales : 25 `PASS`, 0 `PARTIAL`
et 0 `NOT_COVERED`. Son état d’exécution est `PASS`; son verdict scientifique reste
`ADVERSARIAL_FUTURE_MUTATION_INVARIANCE_PARTIAL`, car chaque succès est borné au
composant et à la fixture nommés. Les tests couvrent notamment append/change/delete,
retard et correction tardive, ingestion hors ordre, doublons et ambiguïtés,
fuseaux/DST/date seule, rolling
windows, résultat/lineup/odds post-cutoff et disponibilité modèle/calibration. Ils ne
permettent pas de généraliser au chemin actif complet.

Le replay historique réutilise les 15 résultats logiques de LOOP 54, représentant 45
occurrences physiques. Aucun n’expose simultanément les entrées observationnelles,
leurs reçus, le cutoff et les identités de modèle/calibration/odds nécessaires. Le
replay est donc 0 complet, 0 partiel et 15 non rejouables. Le ledger append-only ajoute
une relation `TEMPORAL_VALIDITY_NOT_PROVEN` hash-chaînée par résultat logique; il ne
réécrit ni ne supprime le résultat source.
Chaque résultat conserve aussi le label d’identité scientifique
`LEGACY_UNVERSIONED_NOT_CANONICAL`, distinct du statut temporel
`POINT_IN_TIME_UNREPLAYABLE`.

Le conflit `DEVIG_PROTOCOL_CONFLICT` reste explicite. Aucune méthode de de-vig n’est
choisie par performance et aucun résultat de protocoles incompatibles n’est agrégé.

## Réponses de revue indépendantes

Dans leur portée couverte, les dix réponses normatives sont `NO` :

| ID | Question | Réponse |
| --- | --- | --- |
| Q1 | Can a late-arriving pre-cutoff event influence an earlier decision? | NO |
| Q2 | Can a future value mutation change a past feature hash? | NO |
| Q3 | Can a future value mutation change a past decision hash? | NO |
| Q4 | Can event_at substitute for available_at? | NO |
| Q5 | Can a self-declared observed_at pass without a receipt? | NO |
| Q6 | Can an unknown availability input be used with only a warning? | NO |
| Q7 | Can a model created after cutoff be used? | NO |
| Q8 | Can an odds snapshot observed after cutoff be selected? | NO |
| Q9 | Can a historical reconstructed timestamp be labelled proven? | NO |
| Q10 | Can a prospective valid contract falsely revalidate all history? | NO |

Les réponses Q1–Q3, Q5, Q7 et Q8 sont bornées aux chemins couverts; Q5 s’appuie
explicitement sur le rejet repository-backed d’un reçu auto-déclaré. Elles ne
transforment pas le chemin de production non couvert en preuve globale.

## Méthode et reproductibilité

Le générateur `scripts/build_temporal_lineage_reports_v1.py` exige explicitement
`--audit-root` et `--loop55-root`. Il échoue si le manifest, la révision, l’arbre ou
les fichiers E2013 ne correspondent pas aux hashes épinglés, mais aussi si le pack
LOOP55 scellé, ses six commandes, l’une de ses 23 empreintes ou l’un des 65 fichiers
candidats inclus dérive. Les
preuves sont séparées : `AUDIT:E2013` décrit l’inventaire historique immuable,
`LOOP55:E0001` conserve les cinq tests rouges pré-correctif, `LOOP55:E0002` porte
les 579 régressions bornées historiques et `LOOP55:E0003` leur validation statique,
toutes deux remplacées comme preuve active. `LOOP55:E0004` porte les 730 régressions
finales et `LOOP55:E0006` la validation statique finale. `LOOP55:E0005` est conservé
immuablement comme `INVALID_HARNESS_COMMAND_RETAINED_NOT_PROOF`; il ne contribue à
aucun verdict positif. Le
générateur n’infère jamais un reçu depuis un mtime, un commit, un temps d’événement
ou l’ordre des lignes.

Chaque rapport déclare sans cycle le futur reçu détaché
`LOOP55_REPORTS:E0003`, sous
`audit-evidence/ROBIN-POINT-IN-TIME-LINEAGE-V1-REPORTS-RECEIPT-V2`. Aucun hash du
manifest détaché n’est embarqué dans les rapports; le claim correspondant du graphe
de preuve lie ce manifest après génération. Ce reçu détaché lie le builder, ce
document, les dix JSON et leur test de validation report-only.

Chaque rapport utilise du JSON canonique trié, UTF-8 et sans NaN. Son champ
`content_sha256` est le SHA-256 du document canonique après retrait du seul champ
`content_sha256`, selon
`SHA256_CANONICAL_JSON_EXCLUDING_CONTENT_SHA256`. Aucun `generated_at` dynamique
n’est émis. Le mode `--check` échoue sur toute dérive d’octets ou tout rapport JSON
non déclaré.

## Limites et robustesse

- E2013 est une sélection auditée fixe; les 72 surfaces ne prétendent pas décrire tout
  stockage ajouté après la révision auditée.
- Les 37 surfaces PostgreSQL restent `EXTERNAL_UNOBSERVED`; aucune donnée Neon ou
  production n’a été consultée.
- Une reconstruction peut aider l’analyse, mais reste
  `RECONSTRUCTED_NOT_PROVEN` et ne devient jamais `RECEIPT_ATTESTED`.
- Les tests synthétiques content-addressed démontrent des propriétés de code, pas la
  rétention effective des reçus en production.
- Les scalaires temporels auto-déclarés du shadow ne peuvent pas autoriser une mise :
  le statut reste `POINT_IN_TIME_NOT_PROVEN`, la décision est rejetée et la mise reste
  nulle. C’est une fermeture fail-closed, pas une preuve PIT positive.
- Les lignes historiques sans reçu, les closing odds et les disponibilités endpoint
  restent `TEMPORAL_VALIDITY_NOT_PROVEN`; une bonne qualité apparente ne contourne pas
  les gates de temporalité.
- Les packages de validation externe restent research-only/`WAITING` sans preuve
  repository-backed, et les familles Effectifs/Joueurs du cockpit restent
  `BLOCKED_BY_TEMPORALITY` même avec deux saisons de couverture.
- Les chemins couverts n’exigent pas de nouvelles colonnes : le shadow utilise son
  JSONL append-only et le prequential résout `odds_snapshot_id` contre les snapshots
  liés à `capture_receipts`, vérifie l’index payload et relit les octets R2. Les anciennes
  lignes SQL et les surfaces non observées ne sont toutefois pas rétroactivement validées.
- Les P0 et P1 ouverts sont à zéro dans le laboratoire borné; sept P1 sont fermés
  par des tests fail-closed explicitement bornés, sans être requalifiés en preuve PIT
  positive. Huit P2 de preuve runtime, couverture, version de formule, batch à kickoff
  égal, liaison de pointer ou histoire irréversible restent ouverts. Aucun de ces P2
  n’impose une nouvelle migration pour les chemins couverts.
- `PRODUCTION_LOCKED`, `NO_PROMOTION` et `NO_BET_DEFAULT` sont conservés. Aucun appel
  provider, aucune migration, aucun workflow live et aucun pari n’ont été effectués.

## Artefacts déterministes

Les dix livrables machine sont :

1. `reports/temporal-lineage/temporal-surface-inventory-v1.json`;
2. `reports/temporal-lineage/temporal-contract-v1.json`;
3. `reports/temporal-lineage/source-receipt-inventory-v1.json`;
4. `reports/temporal-lineage/asof-join-audit-v1.json`;
5. `reports/temporal-lineage/temporal-test-coverage-v1.json`;
6. `reports/temporal-lineage/future-mutation-matrix-v1.json`;
7. `reports/temporal-lineage/decision-lineage-trace-v1.json`;
8. `reports/temporal-lineage/historical-point-in-time-replay-v1.json`;
9. `reports/temporal-lineage/temporal-invalidation-ledger-v1.json`;
10. `reports/temporal-lineage/temporal-defect-inventory-v1.json`.

## Étapes suivantes bornées

1. Étendre la même matrice adversariale aux 10 symboles actifs encore non couverts;
   les 25 classes sont vertes sur le périmètre borné, pas sur chaque symbole du dépôt.
2. Capturer prospectivement les reçus de source, modèle, calibration et odds, puis
   démontrer la persistance et le replay d’une décision complète hors production.
3. Lancer ensuite le re-audit indépendant `ROBIN SCIENTIFIC RECEIPT AUDIT V2`, limité
   au noyau mathématique, à la lignée de de-vig, à la disponibilité point-in-time, aux
   mutations du futur, aux frontières de replay et aux verrous de promotion.

## Questions restant à trancher

- Quel test de replay de bout en bout doit attester la chaîne existante
  JSON/JSONL–snapshot–reçu–R2 sans la confondre avec une preuve de production ?
- Quel mécanisme atteste le premier instant d’observation Robin lorsque la source ne
  publie pas un temps sémantiquement fiable ?
- Comment versionner le modèle et la calibration pour garantir leur disponibilité
  avant `predicted_at`, puis la décision avant `cutoff_at` ?
- Quels chemins parmi les 10 symboles non couverts sont réellement promotables et
  doivent donc être fermés en priorité ?
- Quel jeu prospectif minimal permet un replay complet indépendant avant tout nouvel
  examen de promotion ?
