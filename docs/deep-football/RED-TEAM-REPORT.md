# Jalon 11 — rapport red-team

## Conclusion indépendante

Aucun candidat ne doit être conservé. Le test principal
`B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` n'améliore pas le marché
recalibré train-only. `TEAM_GATE` reste `PARTIAL`; joueurs, absences, lineups,
formations et pied fort sont bloqués avant estimation. La revue indépendante
est `REVISED_AND_FAIL_CLOSED`.

## Objections examinées

| Objection | Test | Conclusion |
|---|---|---|
| hasard | CR1, 999 permutations, BH famille/globale | p CR1 0,9638269 ; q globale 1 |
| fuite | allowlist et ordre de mise à jour | cible exclue, mais `observed_at` source non prouvé : gate partiel |
| concentration | exigée avant promotion | non applicable, aucune stratégie |
| dépendance | 729 dates de match clusterisées | dépendance sérielle équipe non multiway restante |
| mauvaise cote | appariement exact par fixture | 10 732 paires, 0 doublon |
| mauvais cutoff marché | classe de prix sans instant exact | historique seulement, live bloqué |
| seuil/modèle choisi après résultat | primaire fixé | aucune sélection sur le test |
| échantillon incomplet | égalité des clés exigée | 0 attrition du périmètre marché |
| confusion | baseline marché + facteurs antérieurs | aucune affirmation causale |
| join erroné | jointure bijective | garde activée |
| multiplicité | un test + huit hypothèses bloquées | neuf hypothèses dans la famille, q globale 1 |
| calibration | recalibration marché train-only | ECE descriptif, aucune sélection sur labels OOS |
| formation mal normalisée | campagne formation bloquée | aucun effet estimé |
| absence mal classée | campagne absence bloquée | aucune absence reconstruite |

## Contrôles négatifs

| Contrôle | Résultat |
|---|---|
| labels mélangés stratifiés | `EXECUTED_NO_PROMOTION`, N = 7 081 |
| formation décalée | `DATA_GATE_BLOCKED` |
| absence décalée | `DATA_GATE_BLOCKED` |
| joueur aléatoire | `DATA_GATE_BLOCKED` |
| faux pied fort | `DATA_GATE_BLOCKED` |
| lineup post-kickoff | `REJECTED_BY_TEMPORAL_GUARD`, N = 1 |
| cote d'un autre fixture | `REJECTED_BY_PAIRING_GUARD`, N = 1 |
| condition impossible | `OUTCOME_IS_HOME_AND_AWAY`, 7 081 lignes examinées, support 0, `EXECUTED_ZERO_SUPPORT_NO_PROMOTION` |
| équipe domicile systématique | `EXECUTED_NO_PROMOTION`, N = 7 081 |
| règle post-résultat | `REJECTED_BY_FEATURE_ALLOWLIST`, N = 1 |
| faux duo central | `DATA_GATE_BLOCKED` |
| interaction tactique aléatoire | `DATA_GATE_BLOCKED` |

Les contrôles bloqués ne sont pas qualifiés de « passés » : leur gate empêche
simplement une exécution scientifiquement recevable.

Six contrôles sont exécutés ou rejetés par un garde et six restent data-gated.
Les diagnostics post-contrat — quatre challengers team-only, un gradient
boosting incrémental et les cinq rotations 11F — sont tous explicitement
non promouvables.

## Replay

Le replay cache-only reproduit le hash de campagne
`ff37983cc85ad77716ce1b96e3499da1e29908c133c6b085e86fdfd9667a1cfe`.
Les hashes campagne, dataset, Parquet et chaîne ledger sont identiques, avec
zéro doublon, perte, mismatch, appel fournisseur et crédit. La tête ledger est
`8e6d3f0bef494288dca5de747a66b199598c4bdb362024db16d6f8b76aadf5a8`.

## Décision

`promotion_allowed=false`. Les limites bloquantes sont `TEAM_GATE_PARTIAL`,
les gates football profond, l'absence d'`observed_at` exact du marché live et
la sensibilité sérielle non multiway. Aucun ROI n'est calculé. Aucun pattern ne
rejoint la watchlist, aucun candidat shadow n'est créé, et aucune mise n'est
produite.
