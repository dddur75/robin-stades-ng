# Jalon 2 — Réévaluation hors échantillon

Date : 2026-07-24  
Holdout : saison `2025-26`  
Méthode : walk-forward par date, mises unitaires, mises à jour après le lot de
matchs simultanés, cotes legacy de clôture lorsqu'elles existent.

## Conclusion

Aucune stratégie n'est validée pour la production. Toutes les baselines 1X2 sont
négatives. Over 2,5 affiche +2,83 % sur 396 paris, mais son intervalle 95 %
[-8,00 % ; +13,66 %] recouvre largement zéro : résultat `INCONCLUSIVE_OOS`,
seulement admissible à l'observation shadow.

## Résultats

| Stratégie | Paris | ROI | IC 95 % | Drawdown | Statut |
|---|---:|---:|---:|---:|---|
| aucun pari | 0 | 0,00 % | — | 0,00 | `INSUFFICIENT_SAMPLE` |
| favori marché | 1 563 | -2,13 % | [-7,08 % ; +2,82 %] | 60,25 | `REJECTED_OOS` |
| favori domicile | 1 031 | -0,61 % | [-6,59 % ; +5,36 %] | 46,18 | `REJECTED_OOS` |
| aléatoire contrôlée | 1 563 | -0,88 % | [-8,45 % ; +6,68 %] | 77,51 | `REJECTED_OOS` |
| seuil probabilité 55 % | 418 | -0,58 % | [-7,50 % ; +6,35 %] | 13,20 | `REJECTED_OOS` |
| value edge 2 % | 1 519 | -13,34 % | [-21,73 % ; -4,96 %] | 203,51 | `REJECTED_OOS` |
| value edge 4 % | 1 250 | -14,14 % | [-23,36 % ; -4,92 %] | 179,55 | `REJECTED_OOS` |
| value edge 6 % | 939 | -14,96 % | [-25,45 % ; -4,46 %] | 142,10 | `REJECTED_OOS` |
| domicile cote 1,80–2,20 | 315 | -3,38 % | [-14,49 % ; +7,72 %] | 32,25 | `REJECTED_OOS` |
| Over 2,5 value | 396 | +2,83 % | [-8,00 % ; +13,66 %] | 15,03 | `INCONCLUSIVE_OOS` |
| BTTS value | 0 | — | — | 0,00 | `INSUFFICIENT_SAMPLE` |

BTTS est bloqué car le dataset legacy ne contient pas de cote BTTS fiable. Cette
absence n'est pas remplacée par une cote synthétique.

## Garde-fous

- séparation temporelle stricte ;
- matchs simultanés mis à jour en batch ;
- marge 1X2 retirée avant calcul d'edge ;
- sensibilité 2/4/6 % ;
- nombre de paris, intervalle et drawdown visibles ;
- aucune performance historique mélangée aux futures performances shadow ;
- aucun statut supérieur à `OUT_OF_SAMPLE_VALIDATED`, et aucun résultat n'atteint
  ce statut dans ce run.

Résultats machine : `rapports/jalon2/oos-results.json`.
