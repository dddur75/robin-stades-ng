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

R2 n’est demandé que si le rapport durable conclut
`OBJECT_STORAGE_REQUIRED`. L’adaptateur, le dry-run et le workflow sont prêts.
Les secrets à ajouter dans ce seul cas sont `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` et `R2_BUCKET_NAME`. Leur valeur ne
doit jamais être publiée.
