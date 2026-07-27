# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-27
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-11-deep-football-matchups`
Mode : `SHADOW`
Paris réels : `PRODUCTION_LOCKED`

## Jalon 5.1 — revue pré-fusion

`historical-data` est séparée de `shadow-data` avec 3 180 fichiers et
16 184 894 octets migrés à hash identique. Les sept workflows historiques
utilisent `historical-state`; le live conserve `shadow-state`.

Le pilote Ligue 1 2025 est canonicalisé : 306 fixtures et 18 clubs entrent dans
`ligue1_2025_regular_season`; quatre fixtures de barrage et Red Star, Rodez,
Saint-Étienne sont conservés mais exclus. Le backfill reste
`HISTORICAL_BACKFILL_ACTIVE` en mode `ACCELERATED_SAFE`.

## État global

`SHADOW_COLLECTION_HARDENED` — Neon PostgreSQL est connecté, migré à la révision
`0003_jalon4_durable_shadow`, synchronisé avec le registre append-only
`shadow-data` et audité sans écart. La double écriture et le replay idempotent
sans fournisseur sont démontrés. Le burn-in technique et de couverture continue ;
sa composante statistique reste strictement descriptive :
`ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE`.

Ce statut n’est ni `LIVE_SHADOW_VALIDATED`, ni `PRODUCTION_READY`.

## Jalons

| Jalon | Statut | Preuve principale |
|---|---|---|
| 0 — audit initial | `VERIFIED` | `docs/audits/JALON-0-AUDIT.md` |
| 1 — fondation data temporelle | `VERIFIED` | PR #1 |
| 2 — collecte, migration et shadow | `VERIFIED` | PR #2 |
| 3 — activation live et accumulation | `VERIFIED` | PR #3 fusionnée |
| 4 — durabilité et burn-in | `VERIFIED` | `docs/audits/JALON-4-REPORT.md` |
| 5 — Deep Data Factory | `HISTORICAL_BACKFILL_ACTIVE` | PR #6 fusionnée |
| 6 — dataset et Player Feature Factory | `VERIFIED` | PR #9 fusionnée |
| 7 — Scientific Model Arena | `VERIFIED` | PR #10 fusionnée |
| 8 — validation externe | `WAITING_FOR_EXTERNAL_GATES` | `docs/audits/JALON-8-REPORT.md` |
| 9 | `MERGED_AND_POST_MERGE_VERIFIED` | PR #12 |
| 10 — Pattern Research / Public Ledger | `JALON_10_NO_ROBUST_PATTERN_FOUND` | `docs/pattern-research/JALON-10-REPORT.md` |
| 11 — Deep Football / Matchup Arena | `JALON_11_BLOCKED_BY_DATA_GATES` | `docs/deep-football/JALON-11-REPORT.md` |

## Preuves Jalon 4

- Neon PostgreSQL réel connecté en SSL avec Psycopg 3 ;
- cycle contrôlé upgrade/downgrade/upgrade exécuté avant les écritures live ;
- branche de données orpheline `shadow-data`, append-only et vérifiée ;
- migration de 393 enregistrements, 5 observations, 3 objets physiques ;
- couverture de migration 100 %, 2 doublons physiques évités, 0 erreur ;
- 6 bundles, 2 401 lignes cumulées examinées et 101 lignes métier uniques en base ;
- 40 hashes validés, 0 ligne manquante, 0 écart de provenance, 0 démo comme live ;
- replay de 1 997 lignes : 0 insertion, 0 appel fournisseur, 0 crédit consommé ;
- collecte contrôlée `30114121615` acquittée sur PostgreSQL et `shadow-data` ;
- 20 tables durables nouvelles, contraintes métier, index et migrations Alembic ;
- fenêtres J-7 à H-0:10, reprise tardive de 120 minutes et budget adaptatif ;
- rapports quotidien, hebdomadaire et journée de match ;
- Cockpit Live V2 avec couverture, cotes, performance séparée, SLO et coûts ;
- CI de branche et collecte fixtures réelle réussies.

## Données live observées

- 9 fixtures Ligue 1 ;
- 2 snapshots distincts, 180 cotes, 22 bookmakers ;
- prix agrégés identiques entre les deux snapshots : mouvement observé nul ;
- 1 baseline marché, 1 décision rejetée, 0 pari shadow accepté ou réglé ;
- quota : 8 crédits consommés, 19 992 restants.

## Stockage

La cible permanente est Neon PostgreSQL et le pont durable est `shadow-data`.
Les deux sont synchronisés avec un retard nul. La base occupe 11 943 936 octets
(2,39 % de la capacité Free de 0,5 GB). Les Artifacts ne servent que de journal
court et de reprise rapide. Voir
`docs/architecture/DURABLE-SHADOW-STORAGE.md`.

## Action utilisateur

PR #4 déjà fusionnée ; cette mention est conservée comme historique du Jalon 4.

## Jalon 5 — Deep Data Factory

## Jalon 8 — validation externe

Le protocole V1 est gelé. Premier League, La Liga et Bundesliga franchissent
TEAM_GATE et produisent 3 datasets canoniques, 2 136 fixtures d’évaluation et
12 816 prédictions sans fournisseur. Serie A et UCL attendent la complétion des
identités équipe ; joueurs, lineups et marchés attendent le backfill.

Transfert Ligue 1, modèles spécifiques, pooled, score models et
leave-one-league-out sont évalués sans retuning. Aucun edge externe n’est
validé, aucun candidat n’est promu et le package reste
`PRESEASON_PACKAGE_WAITING_FOR_EXTERNAL_GATES`. `PRODUCTION_LOCKED`.

Statut courant : `HISTORICAL_PILOT_VERIFIED` et
`HISTORICAL_BACKFILL_ACTIVE`.

La branche `codex/jalon-5-deep-data-factory` ajoute la migration 0004, le
pipeline API-Football, la pagination reprenable, le stockage historique à trois
niveaux, sept workflows, la Feature Factory V1, une baseline Elo OOS et le Deep
Data Cockpit. Le dataset legacy point-in-time compte 36 423 matchs ; les
résultats sont étiquetés `LEGACY SOURCE`/`OOS HISTORICAL`, jamais live.

Le pilote API-Football Ligue 1 2025 a été exécuté sur GitHub Actions : 1 354
appels, 1 347 pages, 10 868 lignes normalisées, 310 fixtures, 21 équipes,
1 545 payloads gzip et 38 partitions Parquet. Les six identifiants de
compétition sont validés par réponse live. Le plan priorisé contient 6 184
tâches, dont 54 terminées ; les lots suivants restent autonomes.

Le replay du pilote retourne zéro appel fournisseur. Le registre durable
contient plus de 3 100 fichiers avec hashes vérifiés. La migration Neon
`0004_jalon5_deep_data_factory` est appliquée et les métadonnées historiques
sont synchronisées par lots bornés. Le burn-in prospectif continue et
`PRODUCTION_LOCKED` reste invariant.

## Activation post-fusion du Jalon 5

La PR #6 est fusionnée sur `main` au commit
`9726ea9ded1b8a96b5ac6f280a22c24af563241a`.

Le premier lot accéléré exécuté depuis `main` est le run `30150002144` :
99 appels, 99 tâches terminées, 1 597 lignes normalisées, 0 erreur, 0 HTTP 429
et quota restant 149 895. Le plan passe de 54/6 184 à 153/6 184 tâches
terminées. `historical-data` conserve le bundle vérifié et Neon reste à la
révision `0004_jalon5_deep_data_factory`.

Le diagnostic live `30150014764` a démarré pendant le backfill et a réussi avec
`windows_due=0`, démontrant l'indépendance de `shadow-state` et
`historical-state`. Le replay local a consommé 0 appel et 0 crédit.

Une correction post-fusion est isolée dans une PR dédiée : provenance Parquet
réparée depuis les payloads durables sans fournisseur, contrôles qualité
explicites, historique du lot dans PostgreSQL, cadence recalculée après
expansion des tâches, readiness joueurs par famille et séparation explicite
entre build, artefact et déploiement privé du Cockpit. La production reste
`PRODUCTION_LOCKED`.

Le run qualité correctif `30151227188` valide 27 600/27 600 lignes de
provenance, avec 0 appel fournisseur et 0 ligne non résolue. Neon contient
désormais deux runs d'ingestion, dont le lot courant, sans nouvel enregistrement
métier dupliqué. Le Cockpit corrigé est construit par `30151317894`, publié
comme artefact `8617713588` et réellement déployé en version privée 8.

## Jalon 5.2 — forecast complet

L’ancienne ETA inférieure à une journée est reclassée
`MATERIALIZED_TASKS_ONLY`. Le forecast complet inclut désormais les enfants
futurs par fixture, les enfants par équipe et les pages joueurs. Il publie des
scénarios bas, central et haut, avec ETA A/B/globale et stockage projeté.

Le registre versionné `historical-dependency-registry-v1` conserve les
cardinalités 18/20 équipes, le format multi-phase de la Ligue des champions et
l’exclusion des barrages Ligue 1. La cadence reste 30 000 appels/jour, la
réserve 5 000 et la production `PRODUCTION_LOCKED`.

Le Cockpit privé reste en version 8. Le workflow 26 publie automatiquement le
build et l’artefact, puis indique `COCKPIT_PRIVATE_STALE` lorsque le dernier
backfill est plus récent que la version privée réellement déployée.

### Contrôle opérationnel du 25 juillet 2026

Le run planifié `30154099512`, déjà actif au début du contrôle, a été utilisé
sans lancer de second backfill. Il a consommé 2 500 appels, terminé 2 500 tâches,
matérialisé 38 enfants, ajouté 14 072 lignes et laissé 147 395 appels de quota.
Le plan passe de 6 184 à 6 222 tâches, de 153 à 2 655 terminées et de 6 031 à
3 567 restantes. Il n’a produit ni erreur ni HTTP 429.

Le contrôle qualité `30155383297` valide 41 672/41 672 lignes et leurs
provenances, avec 0 hash incohérent, 0 ligne non résolue, 0 donnée future et
0 zéro synthétique. Neon est connecté en SSL à la révision
`0004_jalon5_deep_data_factory`, avec 6 222 tâches et 3 runs historiques.

Le forecast complet mesure 3 256 appels déjà matérialisés et estime encore
55 344 enfants fixture, 3 036 enfants équipe et 1 677 pages joueurs. Les
scénarios bas/central/haut valent 47 417 / 63 313 / 69 977 appels, soit
1,58 / 2,11 / 2,33 jours à 30 000 appels/jour. Le stockage projeté est
227,9 / 427,2 / 665,3 MB dans le snapshot restauré, sous le warning de 750 MB.

Le diagnostic live `30155237678` a démarré pendant le verrou historique et a
réussi : PostgreSQL connecté, 69 tables, registre `shadow-data` vérifié,
`windows_due=0`, aucun appel The Odds API forcé et `PRODUCTION_LOCKED`.
Le Cockpit est construit et publié comme artefact ; la version privée Sites 8,
restée au run `30150002144`, est correctement signalée
`COCKPIT_PRIVATE_STALE`.

## Jalon 6 — Data Factory analytique

La PR #8 est fusionnée sur `main`. Le Jalon 6 travaille sur
`codex/jalon-6-player-model-lab` et maintient `PRODUCTION_LOCKED`.

L'audit durable compte 6 242 tâches, 5 156 terminées et 1 086 restantes.
Les 55 079 lignes restaurées ont une provenance valide. Les Gates A, B et C
sont ouverts ; le Gate D reste `BLOCKED_BY_TEMPORALITY`. Les datasets équipes,
joueurs et compositions simulées sont générés sans appel fournisseur. Les
modèles et stratégies restent `PLAYER_MODEL_TESTING`/`INCONCLUSIVE`.

Premier OOS 2024–2025 : équipe multinomiale Log Loss 1,0518 / Brier 0,2012 ;
pré-lineup 1,0267 / 0,2043 (`INCONCLUSIVE`) ; composition confirmée simulée
1,6920 / 0,2108 (`REJECTED` face à l'équipe seule). Aucune stratégie n'est
promue.

## Jalon 7 — Scientific Model Arena

Statut : `MODEL_ARENA_ACTIVE`. La baseline Jalon 6 est gelée sous
`JALON6_BASELINE_FROZEN`; 2024–2025 reste `EXPOSED_HISTORICAL_OOS` et ne sert
plus à sélectionner un paramètre. La preuve sur `historical-data@d25865e`
produit 4 691 prédictions sur 8 familles, avec comparaisons appariées et 5 000 bootstraps
groupés. Aucun modèle ni stratégie n'est promu; `PRODUCTION_LOCKED` reste actif.

## Jalon 9 — Critical Data Closure

La branche Jalon 9 ajoute la priorité `business_value_priority`, la Historical
Market Factory Football-Data, les gates TEAM/PLAYER/LINEUP/MARKET, le forecast
object storage et l’adaptateur R2. Le backfill conserve 30 000 appels/jour, une
réserve de 5 000 et un passage toutes les deux heures. `REAL_BETS = false`.

La preuve durable `historical-data@518cb4b` mesure 474,1 MB, 894,1 MB de
projection centrale et 939,1 MB de projection haute :
`OBJECT_STORAGE_REQUIRED`. P3/P4 sont suspendus; les gates critiques restent
autorisés.

### Correctif pré-migration R2

Le workflow existant `22 - Qualité historique` expose désormais un mode
pré-fusion exclusif pour la migration R2 sur la branche de la PR #12. Il
restaure et persiste `historical-state`, accepte un dry-run sans secret, puis
des lots cumulatifs de 25, 250 et du périmètre complet.

La preuve exige une lecture distante après chaque upload et chaque replay,
vérifie SHA-256 et taille, exclut ses propres rapports, conserve toutes les
sources et ne fournit aucune suppression. Le client utilise la région `auto`
et l'endpoint Cloudflare R2 global. Le pilote réel, son replay et les gates de
montée en charge sont verts sur la branche avant fusion.
`PRODUCTION_LOCKED`, `REAL_BETS = false` et `NO_BET_DEFAULT = true`.

### Jalon 9.1 — Réplication et restauration R2

Le pilote réel de 25 fichiers est vert en upload puis replay. Il ne constitue
pas une migration complète. L'audit confirme que l'ancien
`double_write=true` prouvait seulement la conservation des sources pendant le
lot.

La branche PR #12 contient désormais un scope stable, un index par objet, un
checkpoint et un curseur reprenable. La persistance historique normale
réplique seulement son delta vers R2 avec retry borné, circuit breaker, lag et
accusé durable. R2 reste un miroir; `historical-data` demeure la source
principale. Une action légère publie les contrôles R2 sans recompacter toutes
les sources à chaque lot.

Le workflow 31 restaure un échantillon JSON/Parquet/CSV/manifeste/checkpoint
dans un dossier temporaire, vérifie les hashes et tailles, lit Parquet et rejoue
un bundle sans fournisseur.

Le benchmark réel 250 est vert : 225 uploads, 25 replays et 250 lectures
distantes en 246,660 s, puis un replay de contrôle avec 0 upload, 250 replays
et 250 lectures distantes en 172,533 s. Le périmètre stable compte 25 422
fichiers pour 710 072 047 octets. La projection monolithique dépasse largement
les 120 minutes; la migration est donc découpée en segments de 5 000 objets,
eux-mêmes checkpointés tous les 1 000 objets.

La restauration réelle est `RESTORE_VERIFIED` sur sept fichiers représentatifs,
avec 3 128 fichiers de bundle rejoués, zéro appel fournisseur, zéro perte,
zéro doublon et zéro mismatch. La réplication continue a rattrapé un lag réel
de 50 objets jusqu'à `SYNCED`, 804 objets vérifiés et lag nul.

La migration complète a ensuite traité les 25 422 fichiers en six runs bornés :
`30204764498`, `30209017214`, `30212660451`, `30218134027`,
`30220648824` et `30225027066`. Le rapport final est `COMPLETE_VERIFIED` et
le checkpoint `COMPLETE` : 24 627 uploads, 471 replays et 324 objets déjà
acquittés par l'index, soit 25 422 objets vérifiés; zéro mismatch, objet
manquant, mutation, suppression ou retry.

L'audit intégral en lecture seule a vérifié ses cinq premiers segments de
5 000 objets sans aucun `PutObject`. Son dernier segment a correctement bloqué
sur une readiness régénérée après sa migration : taille inchangée mais hash
source plus récent que la métadonnée R2. La réplication continue
`30238268175` a alors envoyé et relu les 23 deltas courants, avec 816 objets
attendus et vérifiés, lag nul, zéro erreur, retry, mutation ou suppression.
PostgreSQL a été synchronisé à la révision `0005_jalon9_critical_closure`.

L'audit a repris exactement au curseur 25 399. Le run `30239697041` est
`AUDIT_COMPLETE_VERIFIED` : 25 422/25 422 objets, 710 072 047 octets,
`uploaded=0`, `put_operations=0`, zéro mismatch de hash ou taille, objet
manquant, mutation ou suppression. Le checkpoint d'audit est `COMPLETE`.
Les 21 clés créées après le gel du scope sont volontairement hors de ce
dénominateur; elles sont couvertes par le contrôle courant 816/816 de la
réplication, dont le lag effectif est nul.

Le contrôle shadow `30238014683` exécuté sur la branche de la PR est vert.
Neon est `POSTGRESQL_HEALTHY` à la révision
`0005_jalon9_critical_closure`, le pont durable n'a aucun retard, le replay a
consommé zéro appel et zéro quota, et la production reste
`PRODUCTION_LOCKED`.

Les workflows de gate 14, 21 et 22 sont verts sur la branche avec les runs
`30238014683`, `30238268175` et `30239697041`. Les arrêts
`HISTORICAL_PROVENANCE_REPAIR_INCOMPLETE` et `STORAGE_PAUSED` observés sur
`main` restent explicites : le premier est corrigé dans la PR avant toute
nouvelle perte silencieuse; le second maintient volontairement les priorités
P3/P4 suspendues tant que Git reste la source principale proche de son seuil.
La PR #12 a été fusionnée par merge commit dans `main`.

Le run planifié `30205590638` de `main` a confirmé l'incident de provenance
pré-fusion : le lot fournisseur a réussi, puis
`HISTORICAL_PROVENANCE_REPAIR_INCOMPLETE` a empêché la persistance. Le correctif
présent dans la PR #12 exécute désormais la réparation en mode contrôlé,
persiste Git/Neon et le delta R2 dans tous les cas, puis échoue explicitement
si la provenance reste incomplète. Il empêche une nouvelle perte silencieuse
sans masquer l'incident.

### Validation post-fusion du Jalon 9

Le merge commit `77baf8bedffc0cd76a9b2a44bd7dd1de31d22bac` est validé par
la CI `30246853477`. Les contrôles réels sur `main` sont verts :

- santé shadow `30247017756`, Neon `POSTGRESQL_HEALTHY`, Alembic `0005`,
  replay fournisseur et quota à zéro ;
- backfill dry-run `30247200571`, provenance réparée, PostgreSQL connecté,
  cinq deltas R2 vérifiés et lag nul ;
- audit R2 borné `30248653612`, scope 25 422 toujours
  `AUDIT_COMPLETE_VERIFIED`, zéro upload et zéro suppression.

Le stockage historique courant dépasse le seuil de pause de 900 MB.
`STORAGE_PAUSED` reste donc obligatoire : seuls les traitements historiques
critiques sont autorisés, P3/P4 et les tâches secondaires restent différés.
R2 demeure un miroir et ne justifie aucune croissance libre de Git. La
réduction de la dépendance à Git et un éventuel basculement de source principale
seront traités dans un jalon ultérieur distinct, non ouvert par cette mission.
La production reste `PRODUCTION_LOCKED`.

## Jalon 10 — Pattern Research Engine et Public Evidence Ledger

L’espace et les seuils V1 sont gelés avant lecture des résultats. La revue
pré-fusion V1.1 durcit les p-values CR1 groupées, les contrôles exécutés et les
gates fail-closed sans retuning. Le corpus disponible
comprend 10 732 matchs appariés sur Ligue 1, Premier League, La Liga,
Bundesliga et Serie A en 2020–2025. Le marché 1X2 strict conserve 10 731 lignes
après exclusion d’une marge négative ; Over/Under 2,5 conserve 10 732 lignes.

Ces données sont `DISCOVERY_EXPOSED`. Les prix portent
`SOURCE_PRICE_CLASS_ONLY` et ne disposent pas d’un `observed_at` exact : ils
autorisent la recherche historique, mais ferment le gate live point-in-time.
La première campagne cache-only a généré et exécuté 700 hypothèses : 167 sont
rejetées pour support, 118 ont un ROI brut positif, 24 survivent au
walk-forward brut, mais zéro survit à la FDR, zéro au contrôle de stabilité
inter-ligues exposé et zéro ne devient candidat shadow. Les 7 contrôles
négatifs sur 7 réussissent. Bundesliga et Serie A appartiennent déjà au corpus :
ce contrôle n’est pas un holdout externe indépendant.
Le replay est identique, avec zéro appel fournisseur, zéro crédit et zéro
doublon. Révision exécutée :
`423fb7e77ba52286b660956161f02f8a2c1be7f8`.

Hashes de preuve :

- dataset :
  `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` ;
- résultat :
  `edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b`.

Verdict : `JALON_10_NO_ROBUST_PATTERN_FOUND`. Aucun seuil n’est assoupli et
aucun pattern n’est promu.

Sous-verdict scientifique :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`. Il porte
uniquement sur les 700 règles de cote, marge, catégorie de prix et compétition
préenregistrées ; il ne conclut pas à l’absence de pattern robuste dans le
football ou dans les familles de features non testées.

Le Public Evidence Ledger est défini comme append-only, chaîné par SHA-256 et
shadow-only, avec une bankroll initiale fictive de 1 000 unités. Robin Live V1
doit afficher zéro pari honnête tant qu’aucun candidat n’existe. Les exports
sociaux restent générables mais désactivés.

L’audit borné de l’antériorité tennis a produit uniquement le signal
`LEGACY_HARDCODED_SECRET_DETECTED`; aucune valeur, archive, règle ou performance
tennis n’entre dans Robin.

Invariants :

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

## Jalon 11 — Deep Football et Matchup Arena

La fabrique `TEAM_PREMATCH` matérialise 10 732 fixtures exactement appariées au
marché dans cinq ligues, saisons 2020–2025. L'évaluation walk-forward
2022–2025 porte sur 7 081 fixtures. `TEAM_GATE=PARTIAL` : le target est exclu
par ordre algorithmique, mais la temporalité source ligne par ligne n'est pas
prouvée. L'usage reste descriptif et non promouvable.

Le test principal compare le marché recalibré train-only au modèle incrémental :

| Modèle | Log Loss | Brier |
|---|---:|---:|
| B0 marché recalibré train-only | 0,968936 | 0,192127 |
| B1 marché + équipe multinomiale | 0,970638 | 0,192468 |

Le delta Log Loss est `+0,001702211`, le delta Brier `+0,000340731`, l'IC 95 %
`[-0,000242884 ; +0,003901782]`, p CR1 `0,9638269` et q globale `1,0`.
Aucun gain n'est établi. Quatre challengers team-only et un gradient boosting
incrémental sont des diagnostics post-contrat initial, antérieurs à
l'amendement et non promouvables.

Ce test principal n'est pas qualifié de préenregistré. Il appartient à
`1.0.0-amendment-1`, amendement correctif enregistré après les diagnostics
team-only et avant le run autoritatif, sous le hash
`37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa`.
Il reste descriptif et non promouvable.

11E est terminée comme évaluation de gates : H11-001 à H11-008 restent toutes
bloquées. 11F exécute cinq rotations descriptives rétrospectives, avec zéro
direction positive et zéro survivante. 11B, 11C, 11D et 11G restent
`DATA_GATE_BLOCKED`.

Les données joueurs/lineups profondes sont limitées à la Ligue 1 et marquées
`POST_MATCH_ONLY`; les 12 801 blessures ne sont pas point-in-time et aucun pied
fort sourcé n'est disponible.

Le run opérationnel autoritatif `30282406035` est vert sur le commit
`1b74e94d38038b566e14f21ff2c852230cf046fa`, avec la source
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`. Le snapshot
preflight reste une preuve historique de l'état antérieur à 0008.

Neon est désormais vérifié à `0008_jalon11_deep_football`. Chacun des deux
passages PostgreSQL a examiné 304 preuves compactes, inséré 0 ligne et évité
304 doublons ; six évaluations legacy ont été reconnues comme équivalentes
numériquement par le contrat strict
(`legacy_numeric_equivalent_evaluations=6`). R2 a vérifié 25 453 / 25 453
objets, téléversé le seul Parquet Jalon 11 de 2 000 155 octets, avec lag 0,
aucune suppression et aucune mutation source.

Le replay complet vérifie à l'identique les hashes campagne, dataset, Parquet et
ledger, sans doublon, perte, mismatch, appel fournisseur ni crédit. Watchlist,
candidat, décision et mise restent à zéro ; la bankroll shadow reste à
1 000 unités. Hash campagne :
`437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355`.
Tête ledger :
`90bd34d99a689553246ce3b57ea344d751fb1f948cdc048661d6c2e0b22b92a8`.
Le contrôle `impossible_condition` a réellement examiné 7 081 lignes avec le
prédicat `OUTCOME_IS_HOME_AND_AWAY` : support 0,
`EXECUTED_ZERO_SUPPORT_NO_PROMOTION`.
Voir
`docs/deep-football/JALON-11-SCIENTIFIC-CONTRACT.md`.

### Revue finale PR #14

Le run `30290942945` et les CI push/PR du commit
`31ec41632b72cd93676f5b1d8592e1bba429e937` sont verts. Le replay est
`REPLAY_FULL_HASH_VERIFIED` sur campagne, dataset, Parquet et ledger. Le ledger
compte 27 événements, dont le triplet H11-A, avec la tête
`7f52801f6a4fee8786df0fd71c1f5af3d26dbed31168ebe1e422ba387ccd3ddf`.

PostgreSQL est à `0008_jalon11_deep_football`, avec deux passages de 304 preuves,
0 insertion et 304 doublons évités. R2 est synchronisé à 25 453 objets, lag 0,
0 nouvel objet, 0 suppression et 0 mutation. Le verdict scientifique reste
`JALON_11_BLOCKED_BY_DATA_GATES`; aucun candidat, aucune décision et aucune mise
n'ont été créés.
