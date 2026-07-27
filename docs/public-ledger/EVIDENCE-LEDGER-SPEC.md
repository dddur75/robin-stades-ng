# Spécification du Public Evidence Ledger

Version : `public-evidence-ledger-v1`

## But

Le ledger est la source append-only de Robin Live. Il expose décisions shadow,
`NO BET`, règlements et évolution de bankroll sans rendre accessibles
PostgreSQL, R2, des secrets ou des données privées.

## Décision

Une décision contient au minimum :

- `decision_id`, `published_at`, `cutoff_at` ;
- fixture, compétition, kickoff, marché et sélection ;
- cote observée, source et statut temporel ;
- pattern et version ;
- `BET` ou `NO_BET`, motif et mise ;
- bankroll shadow avant décision ;
- révision, hash du dataset, hash précédent et hash du record ;
- `simulation=true`.

Elle est publiée avant kickoff et ne peut plus être modifiée. Une donnée
point-in-time absente produit `NO_BET_DATA_UNAVAILABLE`.

## Règlement

Le règlement est un nouvel événement qui référence la décision. Il contient
résultat `WIN`, `LOSS` ou `VOID`, profit, bankroll après règlement, instant UTC
et chaîne de hashes. Il ne remplace jamais la décision.

## Hash et idempotence

Le premier record référence un hash genesis de 64 zéros. Chaque record suivant
référence le SHA-256 du précédent et possède son SHA-256 canonique. L’audit
recalcule la chaîne complète.

Un replay du même identifiant et du même contenu est sans effet. Le même
identifiant avec un contenu différent est un conflit immuable. Suppression,
édition en place et réordonnancement sont interdits.

## Source de vérité

PostgreSQL conserve les entités structurées et R2 les preuves durables lourdes.
Git ne reçoit que le registre compact, ses résumés et hashes. Une divergence
bloque le build public ; elle n’est pas corrigée silencieusement.

## Sécurité

Le ledger ne contient ni clé, ni URL secrète, ni jeton, ni pari réel. Les
invariants sont `PRODUCTION_LOCKED`, `REAL_BETS=false` et
`NO_BET_DEFAULT=true`.
