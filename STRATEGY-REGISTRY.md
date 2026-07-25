# Registre des stratégies

## Strategy Factory Jalon 5

| Stratégie | Modèle | Période | N | ROI | Statut |
|---|---|---|---:|---:|---|
| Edge 5 %, mise fixe | Elo V1 | OOS 2024–2025 | 4 139 | -8,55 % | `REJECTED` |

Le résultat est négatif et ne déclenche aucune promotion. La stratégie reste
historique et simulée ; `PRODUCTION_LOCKED` est obligatoire.

| Famille | Version | Usage | Statut |
|---|---:|---|---|
| Vague 1 | 1.0 | 66 hypothèses pré-enregistrées | `PARTIAL` |
| Vague 1B | 1.0 | famille annexe séparée | `PARTIAL` |
| Vague 2 | 1.0 | exploration combinatoire brute | `UNVERIFIED` |
| Vague 2B | 1.0 | référence ajustée par cellules de marché | `PARTIAL` |
| Confrontation CP-01 à CP-10 | 1.0 | suivi prospectif | `IN_PROGRESS` |
| Favori marché | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Favori domicile | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Seuil probabilité 55 % | J2-OOS | consensus Elo–Poisson | `REJECTED_OOS` |
| Value simple edge 4 % | J2-OOS | prix dé-viggé | `REJECTED_OOS` |
| Over 2,5 value | J2-OOS | Poisson vs marché | `INCONCLUSIVE_OOS` |
| BTTS | J2-OOS | odds legacy absentes | `INSUFFICIENT_SAMPLE` |

Règles globales :

- mise réelle interdite ;
- holdout 2025-26 scellé tant qu'une décision formelle ne l'ouvre pas ;
- une stratégie rentable en exploration reste `UNVERIFIED` ;
- le passage à `PRODUCTION_READY` exige hors échantillon, robustesse, coûts,
  concentration des gains, drawdown et shadow test.

## Burn-in Jalon 4

Zéro stratégie est promue. Une décision live a été rejetée et aucun pari shadow
n’est accepté ou réglé. Le legacy, l’OOS historique et le prospectif live restent
trois populations séparées.

## Strategy Lab V1

Les seuils d'edge 1X2 2 %, 4 % et 6 % sont testés par modèle avec intervalle
bootstrap et correction Bonferroni. Les résultats ne peuvent être que
`INCONCLUSIVE` ou `REJECTED` dans ce cycle. Aucun combiné et aucune stratégie
réelle ne sont ouverts.

## Strategy Lab V2

Le protocole borné couvre 1X2, Over/Under 2,5 et BTTS, edges 3/5/7 %, mises
plates ou Kelly 0,10 plafonné à 1 unité et risque quotidien 3 unités. Les
paramètres sont arrêtés avant lecture des périodes exposées. Aucun prix BTTS
historique exploitable n'est artificiellement créé et aucune stratégie n'est
promue.
## Strategy Lab V3 externe

13 hypothèses sont préenregistrées. Le `MARKET_GATE` est indisponible :
0 backtest économique, 0 candidat live, 0 candidat modèle et
`NO_EXTERNAL_VALIDATED_EDGE`. Aucun test BTTS n’est exécuté sans prix fiable.

## Strategy Lab V4

Hypothèses bornées : 1X2 edges 2/3/5 %, probabilités 55/65 %, accord de modèles;
totals edges 3/5 % et accord Poisson/Dixon-Coles. Aucun combiné. Les filtres
joueur exigent PLAYER_GATE READY. `NO_BET_DEFAULT = true`.
