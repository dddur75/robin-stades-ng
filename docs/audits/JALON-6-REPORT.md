# Jalon 6 — rapport d'audit

## Décision

Le Jalon 6 livre une Data Factory analytique gouvernée par quatre gates. Les
Gates A, B et C sont atteints sur l'état durable audité ; le Gate D reste
`BLOCKED_BY_TEMPORALITY`. Aucun résultat historique n'autorise un pari réel :
`PRODUCTION_LOCKED`.

## Preuves observées

- PR #8 fusionnée au commit `e41de53f4bb79c63a9a3200b8cf5c3ce2e9bf8eb`.
- Backfill laissé à sa cadence de 30 000 appels/jour, sans lot concurrent.
- État relu : 6 242 tâches, 5 156 terminées, 1 086 restantes.
- Qualité : 55 079/55 079 lignes avec provenance et hashes valides.
- Gate A : six saisons canoniques 2020–2025, identités équipes 100 %.
- Gate B : quatre saisons joueurs exploitables 2022–2025, identités 100 %.
- Gate C : cinq saisons de lineups exploitables, 11 titulaires 100 % des
  réponses complètes.
- Gate D : blessures historiques exclues faute de preuve point-in-time.

## Premier cycle analytique

Le cycle est exécuté depuis les payloads restaurés, avec
`provider_calls=0` et `quota_consumed=0`. Il génère les manifests de datasets,
les prédictions OOS, les calibrations et les backtests V3. Les résultats
détaillés sont persistés dans `historical-data` par les workflows, puis leurs
synthèses dans PostgreSQL.

Les modèles joueurs et compositions restent des expériences historiques. Une
amélioration de Log Loss isolée ne suffit pas si le Brier, la stabilité ou le
volume ne confirment pas le gain.

## Gouvernance

Les workflows sont chaînés par succès : qualité → readiness → datasets →
modèles → strategy lab → cockpit. Chaque commande quitte proprement avec un
manifest bloqué si son gate n'est pas atteint. Les branches et verrous restent
séparés : `historical-data`/`historical-state` et
`shadow-data`/`shadow-state`.

