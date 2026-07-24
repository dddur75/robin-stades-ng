# Rapport Jalon 4 — Durabilité et burn-in prospectif

Date : 2026-07-24.
Statut : `VERIFIED`.
État opérationnel : `SHADOW_COLLECTION_HARDENED`.
Production : `PRODUCTION_LOCKED`.

## Résultat

Neon PostgreSQL est réellement connecté en SSL, migré et synchronisé avec le
registre append-only `shadow-data`. Le secret GitHub est présent et n’a jamais
été affiché. Les URL Neon `postgresql://` sont normalisées centralement vers le
pilote Psycopg 3. Les données live Jalon 3 et les bundles Jalon 4 ont été
persistés, audités et rejoués sans fournisseur. Le scheduler, le burn-in et ses
rapports restent actifs. Cockpit Live V2 expose désormais l’état PostgreSQL, la
dernière écriture, la volumétrie, le retard du pont et la double écriture.

## Preuves

- PR #3 fusionnée, CI verte ;
- secret `DATABASE_URL` détecté dans GitHub sans lecture de sa valeur ;
- bootstrap Neon `30113926625` réussi ;
- upgrade initial, downgrade contrôlé sur base vide et nouvel upgrade observés
  dans les logs avant les écritures live ;
- révision Alembic `0003_jalon4_durable_shadow` ;
- collecte contrôlée live `30114121615` réussie et acquittée par
  `POSTGRESQL_AND_GIT_DATA_BRIDGE` ;
- replay post-collecte `30114240081` réussi sans appel fournisseur ;
- registre distant : 6 bundles, 2 401 lignes cumulées, 40 hashes validés ;
- PostgreSQL : 101 lignes métier uniques, 6 runs, 3 payloads bruts ;
- 0 ligne manquante, 0 écart de provenance, 0 démo présentée comme live ;
- retard entre PostgreSQL et `shadow-data` : 0 ligne ;
- 393 enregistrements migrés, 5 observations, 3 objets physiques ;
- 5/5 hashes valides, 2 doublons évités, 0 erreur ;
- replay de 1 997 lignes exécuté deux fois : 0 insertion, 0 appel et 0 quota ;
- panne PostgreSQL simulée : pont conservé, incident explicite et dédupliqué,
  replay contrôlé sans perte silencieuse ;
- base : 11 943 936 octets, soit 2,39 % de 0,5 GB ;
- tests adversariaux, lint, typage strict, migrations et build Cockpit ;
- aucune exposition de secret et aucun pari réel.

## Limites honnêtes

- API-Football reste `ADAPTER_ONLY` ;
- les snapshots diagnostics ne comptent pas dans la couverture ;
- un seul jour calendaire est observé ;
- zéro pari shadow accepté ou réglé.

ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE.

## Prochaine transition

Après fusion, les workflows poursuivront automatiquement le burn-in, la double
écriture, les audits de retard et les reprises de fenêtres. Le prochain jalon
reste interdit avant au moins 30 jours de burn-in et des volumes réellement
réglés suffisants. Aucun statut de validation stratégique n’est revendiqué et
les paris réels restent `PRODUCTION_LOCKED`.
