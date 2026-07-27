# Résultats des campagnes Jalon 11

## Synthèse

| Campagne | Périmètre | Statut | Appels / crédits |
|---|---|---|---:|
| 11A | équipe et calendrier | `COMPLETED_CACHE_ONLY` | 0 / 0 |
| 11B | disponibilité joueurs | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11C | continuité lineup | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11D | matchups formation | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11E | H11-001 à H11-008 | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11F | transfert inter-ligues profond | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11G | arène intégrée | `DATA_GATE_BLOCKED` | 0 / 0 |

## Campagne 11A

Le dataset construit contient 10 732 fixtures. L'échantillon d'évaluation
exactement apparié contient 7 081 fixtures sur quatre folds chronologiques.

| Modèle | Log Loss | Brier | Δ LL vs marché | Δ Brier vs marché |
|---|---:|---:|---:|---:|
| `B0_MARKET` | 0,966773 | 0,191619 | — | — |
| `B1_REGULARIZED_MULTINOMIAL` | 0,988918 | 0,196458 | +0,022145 | +0,004839 |
| `B1_BOUNDED_GRADIENT_BOOSTING` | 0,998024 | 0,198176 | +0,031251 | +0,006557 |

Un delta positif signifie une dégradation. La multinomiale est moins mauvaise
que le gradient boosting mais reste inférieure au marché dans chaque fold.

| Saison test | N | Δ LL multinomiale | Δ LL boosting |
|---|---:|---:|---:|
| 2022 | 1 826 | +0,015248 | +0,032097 |
| 2023 | 1 752 | +0,028365 | +0,032001 |
| 2024 | 1 751 | +0,025426 | +0,035621 |
| 2025 | 1 752 | +0,019833 | +0,025250 |

Tests :

- CR1 unilatéral : p = 1 ;
- permutation de signe : p = 1, 999 permutations ;
- BH famille : q = 1 ;
- BH global : q = 1 ;
- ROI : non calculé, aucune règle de mise préenregistrée ;
- concentration : non applicable, aucune stratégie promue.

## Appariement et replay

- paires marché/équipe : 10 732 / 10 732 ;
- doublons de clé : 0 ;
- attrition marché : 0 ;
- hash de campagne :
  `2c131727c4a1af593443c3fe54f16ef5d4ed530bc010e361f349e68fe4930260` ;
- replay identique : oui ;
- doublons métier : 0 ;
- perte : 0 ;
- mismatch de hash : 0 ;
- appels fournisseur et crédits au replay : 0.

## Verdict

`JALON_11_BLOCKED_BY_DATA_GATES`.

La campagne éligible n'ajoute aucune information au marché ; les campagnes
profondes restantes ne sont pas évaluables avec une temporalité honnête.
Watchlist, candidats et décisions restent à zéro.
