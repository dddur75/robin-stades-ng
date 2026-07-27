# Jalon 11 — rapport red-team

## Conclusion indépendante

Aucun candidat ne doit être conservé. La baseline équipe est dominée par le
marché et les familles joueurs, absences, lineups, formations et pied fort sont
bloquées avant estimation. Il n'existe donc pas d'objection majeure non résolue
sur un candidat : il n'y a aucun candidat.

## Objections examinées

| Objection | Test | Conclusion |
|---|---|---|
| hasard | CR1, 999 permutations, BH famille/globale | p = q = 1, aucun signal |
| fuite | allowlist de features, rolling strict | aucune cible dans les features 11A |
| concentration | exigée avant promotion | non applicable, aucune stratégie |
| dépendance | clusters minimum 30 | contrôle requis et appliqué au résultat 11A |
| mauvaise cote | appariement exact par fixture | 10 732 paires, 0 doublon |
| mauvais cutoff marché | classe de prix sans instant exact | historique seulement, live bloqué |
| seuil choisi après résultat | paramètres gelés | aucune règle ROI sélectionnée |
| échantillon incomplet | égalité des clés exigée | 0 attrition du périmètre marché |
| confusion | baseline marché + facteurs antérieurs | aucune affirmation causale |
| join erroné | jointure bijective | garde activée |
| formation mal normalisée | campagne formation bloquée | aucun effet estimé |
| absence mal classée | campagne absence bloquée | aucune absence reconstruite |

## Contrôles négatifs

| Contrôle | Résultat |
|---|---|
| labels mélangés stratifiés | `PASSED_NO_PROMOTION` |
| formation décalée | `DATA_GATE_BLOCKED` |
| absence décalée | `DATA_GATE_BLOCKED` |
| joueur aléatoire | `DATA_GATE_BLOCKED` |
| faux pied fort | `DATA_GATE_BLOCKED` |
| lineup post-kickoff | `REJECTED_BY_TEMPORAL_GUARD` |
| cote d'un autre fixture | `REJECTED_BY_PAIRING_GUARD` |
| condition impossible | `PASSED_NO_OCCURRENCES` |
| équipe domicile systématique | `PASSED_NO_PROMOTION` |
| règle post-résultat | `REJECTED_BY_FEATURE_ALLOWLIST` |
| faux duo central | `DATA_GATE_BLOCKED` |
| interaction tactique aléatoire | `DATA_GATE_BLOCKED` |

Les contrôles bloqués ne sont pas qualifiés de « passés » : leur gate empêche
simplement une exécution scientifiquement recevable.

## Replay

Le replay cache-only reproduit le hash de campagne
`2c131727c4a1af593443c3fe54f16ef5d4ed530bc010e361f349e68fe4930260`
avec zéro doublon, perte, mismatch, appel fournisseur et crédit.

## Décision

`promotion_allowed=false`. Aucun ROI n'est calculé. Aucun pattern ne rejoint la
watchlist, aucun candidat shadow n'est créé, et aucune mise n'est produite.
