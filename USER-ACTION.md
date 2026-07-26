# Action utilisateur

Action après validation verte de la PR #6 :

Le Jalon 6 ne demande aucune manipulation pendant la construction et la CI.
Une fois la PR brouillon déclarée prête et verte, l'unique action sera :

`Valider puis fusionner la PR du Jalon 6.`

Aucune dépense, permission de pari réel ou migration de stockage n'est demandée.

## Jalon 7

Après CI verte : `Valider puis fusionner la PR du Jalon 7.`

Aucun crédit fournisseur, déverrouillage de production ou abonnement de
stockage n'est requis.

## Jalon 8

Après CI verte de la PR brouillon :

`Valider puis fusionner la PR du Jalon 8.`

Aucun crédit fournisseur, achat de stockage ou déverrouillage de pari réel
n’est demandé. Les gates encore en attente progresseront avec le backfill.

## Jalon 9

Le rapport durable conclut `OBJECT_STORAGE_REQUIRED`. Avant toute fusion de la
PR #12 :

1. Dans GitHub Actions, lancer `22 - Qualité historique`.
2. Sélectionner la branche `codex/jalon-9-market-player-storage`.
3. Faire un dry-run avec
   `run_object_storage_migration=true`,
   `execute_object_storage_migration=false`,
   `object_storage_max_files=25`, et les deux autres modes spéciaux à `false`.
4. Exécuter un premier lot réel de 25 avec
   `execute_object_storage_migration=true`.
5. Rejouer le lot de 25 et obtenir 25 `replayed`, 0 `uploaded` et
   25 `remote_verified`.
6. Passer à `object_storage_max_files=250`.
7. Utiliser ensuite une valeur supérieure au total, par exemple `1000000`,
   pour migrer tout le périmètre.
8. Rejouer tout le périmètre et obtenir `complete=true` avec
   `status=COMPLETE_VERIFIED`.
9. Ne jamais supprimer `historical-data`.
10. Ne fusionner la PR #12 qu'après cette preuve complète.

Les secrets nécessaires uniquement aux runs réels sont `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` et `R2_BUCKET_NAME`. Leur valeur ne
doit jamais être publiée. La production reste `PRODUCTION_LOCKED`,
`REAL_BETS=false` et `NO_BET_DEFAULT=true`.
