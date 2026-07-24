# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-4-durable-shadow`
Mode : `SHADOW`
Paris réels : `PRODUCTION_LOCKED`

## État global

`SHADOW_BURN_IN_ACTIVE` — la collecte prospective écrit désormais dans un
registre durable append-only, indépendant de la rétention des GitHub Artifacts.
Le burn-in technique et de couverture est démarré. Sa composante statistique
reste strictement descriptive :
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

- branche de données orpheline `shadow-data`, append-only et vérifiée ;
- migration de 393 enregistrements, 5 observations, 3 objets physiques ;
- couverture de migration 100 %, 2 doublons physiques évités, 0 erreur ;
- replay à octets identiques, sans appel fournisseur ni crédit consommé ;
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

La cible permanente recommandée est PostgreSQL managé chez Neon. En attendant
`DATABASE_URL`, le pont `shadow-data` satisfait la durabilité minimale et les
Artifacts ne servent plus que de journal court et de reprise rapide. Voir
`docs/architecture/DURABLE-SHADOW-STORAGE.md`.

## Action utilisateur

Créer le projet PostgreSQL Neon et enregistrer sa chaîne de connexion dans le
secret GitHub `DATABASE_URL`. Voir `USER-ACTION.md`.
