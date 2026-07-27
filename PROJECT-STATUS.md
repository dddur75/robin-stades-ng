# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-26
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-9-market-player-storage`
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
| 9 | `PRE_MERGE_R2_VALIDATION` | PR #12 |

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
