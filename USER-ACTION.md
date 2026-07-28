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

Sous-verdict :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`. La
conclusion porte sur 700 règles préenregistrées de tranches de marché, pas sur
tous les patterns football ni sur les familles non testées.

La campagne ne demande aucune action utilisateur. Tant que la PR brouillon
n’est pas déclarée verte et prête :

`AUCUNE ACTION UTILISATEUR REQUISE`

Une fois la PR brouillon complète, verte et déclarée prête, l’unique action
pourra devenir : `Valider puis fusionner la PR du Jalon 10.`

Aucun secret, crédit fournisseur, connexion sociale, permission de pari ou
reprise P3/P4 n’est demandé. La production reste `PRODUCTION_LOCKED`.

## Jalon 11

Le calcul cache-only et son replay démontrent 10 732 fixtures équipe/marché,
7 081 évaluations chronologiques, aucun gain primaire, zéro watchlist,
zéro candidat, zéro décision et zéro coût fournisseur. `TEAM_GATE=PARTIAL`
limite 11A et 11F aux diagnostics descriptifs ; 11E termine l'évaluation de
gates avec huit hypothèses bloquées. Les familles profondes restent honnêtement
bloquées.

Le replay vérifie les quatre hashes campagne, dataset, Parquet et ledger sans
écart. Le preflight à 0007 reste conservé comme photographie historique. Le run
vert `30282406035` vérifie désormais Neon à
`0008_jalon11_deep_football`, deux passages idempotents de 304 preuves
compactes et R2 à 25 453 / 25 453 objets avec lag nul.

Le test principal est un amendement correctif non promouvable, enregistré après
les diagnostics team-only et avant ce run autoritatif ; il n'est pas présenté
comme préenregistré. Le verdict reste `JALON_11_BLOCKED_BY_DATA_GATES`.

Tant que la PR brouillon n'est pas complète et verte :

`AUCUNE ACTION UTILISATEUR REQUISE`

Après validation finale de la CI et passage explicite de la PR à l'état prêt,
l'unique action pourra être :

`Valider puis fusionner la PR du Jalon 11.`

Aucun crédit fournisseur, reprise P3/P4, secret, connexion sociale, permission
de pari ou déverrouillage de production n'est demandé.

### Revue finale Jalon 11

La revue adversariale et le run cache-only `30290942945` sont verts sur le
correctif `31ec416`. Le replay, Neon `0008`, R2, le ledger à 27 événements et
Robin Live sont vérifiés. La PR doit être fusionnée par l'automatisation de
clôture uniquement après son passage en Ready et le dernier contrôle GitHub.

`AUCUNE ACTION UTILISATEUR REQUISE`

## Jalon 12

La branche et la PR brouillon Jalon 12 doivent rester non fusionnées pendant la
construction et le pilote. Le système utilise les secrets existants sans jamais
les afficher. Aucun achat, nouvel abonnement, réseau social, pari réel ou
reprise P3/P4 n’est demandé.

Tant que le pilote réel, le replay R2, PostgreSQL et la CI ne sont pas tous
verts :

`AUCUNE ACTION UTILISATEUR REQUISE`

Une demande de fusion éventuelle appartiendra à une mission distincte après
revue des preuves.

Le pilote borné et le replay-only final sont désormais vérifiés par le run
`30314975830`, avec CI PR `30314978406` verte. Le verdict reste
`JALON_12_PARTIAL_CAPTURE_READY` parce qu’aucune fenêtre critique joueur,
blessure, lineup, formation ou cote n’était due. Cette couverture partielle
est attendue et ne justifie ni appel forcé ni fusion automatique.

`AUCUNE ACTION UTILISATEUR REQUISE`

Ne pas fusionner la PR #17 dans cette mission.

## Robin Experience V1

La refonte est livrée dans une PR brouillon distincte. Aucune autorisation de
fournisseur, aucun secret, aucune dépense, aucune connexion sociale et aucun
pari ne sont demandés.

Avant la fin de la CI :

`AUCUNE ACTION UTILISATEUR REQUISE`

Après publication des preuves, l’action recommandée est uniquement de consulter
le [site privé](https://robin-stades-shadow-cockpit.dddur.chatgpt.site), les
captures `robin-experience-visual-*` et la
[PR brouillon #19](https://github.com/dddur75/robin-stades-ng/pull/19).
Ne pas fusionner automatiquement. Toute fusion doit être une décision explicite
après revue de l’UX, de l’accessibilité et de la séparation scientifique.

## Robin Experience V1.1

`AUCUNE ACTION UTILISATEUR REQUISE`

La mise à jour reste sur la PR brouillon #19, ouverte et non fusionnée. Elle ne
demande aucun secret, appel fournisseur, crédit, écriture distante, connexion
sociale, décision ou pari.

La CI et le redéploiement privé Sites 15 sont terminés avec succès. L’action
recommandée reste uniquement de consulter le
[site privé](https://robin-stades-shadow-cockpit.dddur.chatgpt.site), les
18 captures des artefacts `robin-experience-visual-30352906004` /
`robin-experience-visual-30352908592` et la PR #19. Toute fusion appartient à
une décision ultérieure explicite.

## Robin Experience V1.2 — clôturée

`AUCUNE ACTION UTILISATEUR REQUISE`

La PR #19 a été passée en Ready, fusionnée par merge commit et validée sur
`main`. La version privée Sites 18 a été reconstruite et déployée depuis le
sous-arbre exact du commit de fusion. Elle reste accessible au seul
propriétaire :

https://robin-stades-shadow-cockpit.dddur.chatgpt.site

La CI post-fusion, les 18 captures, les routes privées, le mobile, la Vue
expert, le glossaire et l’absence d’erreur console ont été vérifiés. Aucun
appel fournisseur forcé, crédit Odds, pari réel, publication sociale, secret
supplémentaire ou déverrouillage de production n’est demandé.

```text
ROBIN EXPERIENCE V1.2
MERGED
POST_MERGE_VERIFIED
PRIVATE_DEPLOYED_FROM_MAIN
```

## Expansion prospective cinq ligues

`AUCUNE ACTION AUTOMATIQUE REQUISE`

Le pilote réel est terminé et la PR brouillon #20 reste volontairement non
fusionnée. Trois ligues sur cinq sont actives ; Liga et Bundesliga restent
`BLOCKED_PROVIDER` faute de fixture admissible dans l’audit borné. La CI, le
replay, R2, PostgreSQL, les identités et Robin Experience sont verts.

Action recommandée : examiner la
[PR brouillon #20](https://github.com/dddur75/robin-stades-ng/pull/20) et le
verdict `FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL`. Ne fusionner que par
décision explicite après acceptation de ce périmètre partiel ou après un futur
audit fournisseur autorisé. Aucun pari réel, secret supplémentaire, achat,
publication sociale ou reprise P3/P4 n’est demandé.
