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

Le pilote et son replay, le benchmark 250, la migration complète segmentée,
l'audit intégral sans écriture, la restauration et la réplication continue sont
vérifiés. Le miroir R2 est `SYNCED` avec lag nul; Neon et les workflows 14, 21
et 22 sont verts sur la branche.

Action unique :

**Valider puis fusionner la PR #12.**

Les secrets nécessaires uniquement aux runs réels sont `R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` et `R2_BUCKET_NAME`. Leur valeur ne
doit jamais être publiée. La production reste `PRODUCTION_LOCKED`,
`REAL_BETS=false` et `NO_BET_DEFAULT=true`.

## Jalon 10

La campagne réelle cache-only et son replay sont terminés : 700 hypothèses
exécutées, zéro survivante FDR, zéro candidat shadow, 7/7 contrôles négatifs,
zéro doublon et zéro coût fournisseur. Verdict :
`JALON_10_NO_ROBUST_PATTERN_FOUND`.

La campagne ne demande aucune action utilisateur. Tant que la PR brouillon
n’est pas déclarée verte et prête :

`AUCUNE ACTION UTILISATEUR REQUISE`

Une fois la PR brouillon complète, verte et déclarée prête, l’unique action
pourra devenir : `Valider puis fusionner la PR du Jalon 10.`

Aucun secret, crédit fournisseur, connexion sociale, permission de pari ou
reprise P3/P4 n’est demandé. La production reste `PRODUCTION_LOCKED`.
