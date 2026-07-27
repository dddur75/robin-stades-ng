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

Le test principal compare
`B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` à
`B0_MARKET_RECALIBRATED_TRAIN_ONLY`. Le delta Log Loss agrégé est
`+0,001702211` et le delta Brier `+0,000340731`. L'IC bootstrap 95 %
`[-0,000242884 ; +0,003901782]` traverse zéro ; p CR1 vaut `0,9638269` et
q globale `1,0`.

Ce résultat n'autorise ni ROI, ni stratégie, ni watchlist. Les campagnes de
matchups joueurs/lineups/formations sont bloquées par leurs gates et ne sont pas
remplacées par des analyses rétrospectives trompeuses.

`TEAM_GATE=PARTIAL` : le target est exclu par ordre algorithmique, mais le
`source_observed_at` ligne par ligne n'est pas établi. Quatre modèles team-only
et un gradient boosting incrémental sont donc documentés seulement comme
diagnostics post-contrat non promouvables.

## Diagnostic 11F

Les cinq rotations inter-ligues sont descriptives, rétrospectives et
chevauchantes. Elles produisent zéro direction positive et zéro survivante.
Le déplacement temporel et le déplacement de ligue restent confondus ; aucune
rotation n'est éligible à une promotion.
