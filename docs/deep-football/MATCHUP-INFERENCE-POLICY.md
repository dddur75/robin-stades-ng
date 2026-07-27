# Politique d'inférence des matchups

## Estimand principal

La question est : une feature profonde explique-t-elle le résidu entre le
résultat et la probabilité 1X2 de-viguée du marché ? Le terme autorisé est
`ADJUSTED_ASSOCIATION`, jamais causalité sans protocole causal dédié.

## Comparaison

Tous les modèles d'une comparaison utilisent exactement les mêmes fixtures.
Les clés dupliquées, une intersection silencieuse et une cote appartenant à un
autre fixture font échouer le calcul.

Les covariables minimales sont :

- probabilité de marché ;
- domicile ;
- ligue et saison ;
- force antérieure ;
- repos et calendrier ;
- continuité si son gate est prêt ;
- changement d'entraîneur si daté ;
- clustering par équipe ou journée.

## Walk-forward

Le protocole est expanding et chronologique :

| Fold | Train | Test | N test |
|---|---|---|---:|
| 1 | 2020–2021 | 2022 | 1 826 |
| 2 | 2020–2022 | 2023 | 1 752 |
| 3 | 2020–2023 | 2024 | 1 751 |
| 4 | 2020–2024 | 2025 | 1 752 |

Les imputations, pondérations et calibrations sont ajustées uniquement sur le
train. La seed de campagne est 11011.

## Tests

- Log Loss et Brier appariés ;
- CR1 avec au moins 30 clusters ;
- permutation par signes, 999 répétitions ;
- BH par famille puis globale ;
- leave-one-team/season/league-out lorsque le signal est éligible ;
- concentration et bootstrap avant toute promotion.

## Résultat 11A

Le marché domine les deux modèles d'équipe. Le delta Log Loss est positif dans
les quatre folds pour la multinomiale : +0,015248, +0,028365, +0,025426 et
+0,019833. Les tests CR1, permutation, BH famille et BH global donnent 1.

Ce résultat n'autorise ni ROI, ni stratégie, ni watchlist. Les campagnes de
matchups joueurs/lineups/formations sont bloquées par leurs gates et ne sont pas
remplacées par des analyses rétrospectives trompeuses.
