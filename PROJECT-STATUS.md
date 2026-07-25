# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-25
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-5-deep-data-factory`
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
| 5 à 9 | `NOT_STARTED` | hors périmètre |

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

Valider puis fusionner la PR #4.

## Jalon 5 — Deep Data Factory

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
