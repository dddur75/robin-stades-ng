# Rapport Jalon 4 — Durabilité et burn-in prospectif

Date : 2026-07-24.
Statut : `VERIFIED`.
État opérationnel : `SHADOW_BURN_IN_ACTIVE`.
Production : `PRODUCTION_LOCKED`.

## Résultat

Le stockage n’est plus dépendant exclusivement des GitHub Artifacts. Le registre
append-only `shadow-data` est actif et vérifié ; PostgreSQL est prêt mais attend
`DATABASE_URL`. Les données live Jalon 3 ont été migrées à 100 % et sont
rejouables hors ligne. Le scheduler gère neuf fenêtres, une marge de reprise et
un budget adaptatif. Le burn-in et ses rapports sont actifs. Cockpit Live V2
expose couverture, mouvements, SLO, incidents, coûts et données filtrables.

## Preuves

- PR #3 fusionnée, CI verte ;
- CI Jalon 4 verte sur la branche ;
- workflow réel fixtures `30101116019` réussi avec écriture durable ;
- santé quotidienne `30102875755` réussie et rapport de burn-in produit ;
- registre distant revérifié : 3 bundles, 17 références d’objets, 0 erreur ;
- 393 enregistrements migrés, 5 observations, 3 objets physiques ;
- 5/5 hashes valides, 2 doublons évités, 0 erreur ;
- replay identique, 0 appel et 0 quota ;
- tests adversariaux, lint, typage strict, migrations et build Cockpit ;
- aucune exposition de secret et aucun pari réel.

## Limites honnêtes

- aucun secret `DATABASE_URL` : Neon n’est pas encore la source primaire ;
- API-Football reste `ADAPTER_ONLY` ;
- les snapshots diagnostics ne comptent pas dans la couverture ;
- un seul jour calendaire est observé ;
- zéro pari shadow accepté ou réglé.

ÉCHANTILLON INSUFFISANT — AUCUNE CONCLUSION STATISTIQUE.

## Prochaine transition

Après ajout de `DATABASE_URL`, la double écriture s’activera automatiquement.
Le prochain jalon reste interdit avant au moins 30 jours de burn-in et des
volumes réellement réglés suffisants. Aucun statut de validation live n’est
revendiqué.
