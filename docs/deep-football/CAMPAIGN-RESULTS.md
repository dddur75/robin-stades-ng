# Résultats des campagnes Jalon 11

## Synthèse

| Campagne | Périmètre | Statut | Appels / crédits |
|---|---|---|---:|
| 11A | équipe et calendrier | `DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC`, non promouvable | 0 / 0 |
| 11B | disponibilité joueurs | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11C | continuité lineup | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11D | matchups formation | `DATA_GATE_BLOCKED` | 0 / 0 |
| 11E | H11-001 à H11-008 | `COMPLETED_AS_GATE_EVALUATION`, 8/8 bloquées | 0 / 0 |
| 11F | transfert inter-ligues équipe | diagnostic rétrospectif, 0/5 positive et 0 survivante | 0 / 0 |
| 11G | arène intégrée | `DATA_GATE_BLOCKED` | 0 / 0 |

## Campagne 11A

Le dataset construit contient 10 732 fixtures. L'échantillon d'évaluation
exactement apparié contient 7 081 fixtures sur quatre folds chronologiques.

`TEAM_GATE=PARTIAL` : le match cible est exclu de ses propres agrégats, mais
les 10 732 frontières de matérialisation sont égales au kickoff et le
`observed_at` ligne par ligne des sources n'est pas prouvé. Ces résultats sont
donc descriptifs et non promouvables.

### Test principal correctif

Ce test n'est pas préenregistré. L'amendement `1.0.0-amendment-1` a été
enregistré après l'examen des diagnostics team-only et avant le run
autoritatif `30282406035`. Son hash est
`37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa`.
Il reste descriptif et non promouvable.

| Modèle | Log Loss | Brier | ECE | Référence |
|---|---:|---:|---:|---|
| `B0_MARKET_RECALIBRATED_TRAIN_ONLY` | 0,968936 | 0,192127 | 0,012386 | référence train-only |
| `B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` | 0,970638 | 0,192468 | 0,009652 | primaire |

Delta primaire B1 − B0 recalibré :

- Log Loss : `+0,001702211` ;
- Brier : `+0,000340731` ;
- IC bootstrap 95 % du delta Log Loss :
  `[-0,000242884 ; +0,003901782]` ;
- p CR1 unilatérale : `0,9638269` ;
- p permutation de signe : `0,961` sur 999 permutations ;
- q famille : `0,9638269` ;
- q globale : `1,0`.

Le delta positif est défavorable et l'intervalle traverse zéro. Aucun incrément
au-delà du marché recalibré n'est démontré.

### Diagnostics post-contrat initial, antérieurs à l'amendement

Ces résultats complètent le diagnostic ; ils ne sont pas des tests principaux
et ne peuvent pas produire un candidat. Ils ont précédé l'enregistrement de
l'amendement correctif :

| Modèle | Log Loss | Brier | Δ Log Loss | Δ Brier |
|---|---:|---:|---:|---:|
| `B0_MARKET` brut | 0,966773 | 0,191619 | — | — |
| team-only multinomiale | 0,988918 | 0,196458 | +0,022145 | +0,004839 |
| team-only gradient boosting | 0,998024 | 0,198176 | +0,031251 | +0,006557 |
| team-only Poisson | 1,046019 | 0,209819 | +0,079246 | +0,018200 |
| team-only Dixon–Coles | 1,046626 | 0,209863 | +0,079853 | +0,018244 |
| marché + équipe, gradient boosting | 0,978452 | 0,193938 | +0,009516 | +0,001811 |

Les quatre challengers team-only sont comparés au marché brut. Le diagnostic
incrémental gradient boosting est comparé au marché recalibré train-only.

## Campagne 11F

11F est exécutée uniquement comme diagnostic rétrospectif descriptif. Cinq
rotations gelées entraînent sur trois ligues et décrivent deux ligues de
validation. Les supports vont de 2 743 à 3 040 ; les cinq deltas Log Loss sont
défavorables (`+0,003395` à `+0,008942`), avec :

```text
descriptive_positive_rotations=0
cross_league_survivors=0
promotion_eligible=false
```

Les rotations se chevauchent, le déplacement ligue/temps est confondu et
aucune inférence de multiplicité au niveau rotation n'est revendiquée.

### Folds team-only post-contrat

Ces deltas sont conservés comme diagnostic secondaire non promouvable :

| Saison test | N | Δ LL multinomiale | Δ LL boosting |
|---|---:|---:|---:|
| 2022 | 1 826 | +0,015248 | +0,032097 |
| 2023 | 1 752 | +0,028365 | +0,032001 |
| 2024 | 1 751 | +0,025426 | +0,035621 |
| 2025 | 1 752 | +0,019833 | +0,025250 |

### Inférence du test principal

Tests applicables au primaire marché + équipe :

- CR1 unilatéral : p = 0,9638269 ;
- permutation de signe : p = 0,961, 999 permutations ;
- BH famille : q = 0,9638269 ;
- BH global : q = 1 ;
- ROI : non calculé, aucune règle de mise préenregistrée ;
- concentration : non applicable, aucune stratégie promue.

## Appariement et replay

- paires marché/équipe : 10 732 / 10 732 ;
- doublons de clé : 0 ;
- attrition marché : 0 ;
- contrôle `impossible_condition` : prédicat
  `OUTCOME_IS_HOME_AND_AWAY` réellement calculé sur 7 081 lignes, support 0,
  `EXECUTED_ZERO_SUPPORT_NO_PROMOTION` ;
- hash de campagne :
  `437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355` ;
- hash dataset :
  `2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6` ;
- SHA-256 Parquet :
  `d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673` ;
- tête ledger :
  `90bd34d99a689553246ce3b57ea344d751fb1f948cdc048661d6c2e0b22b92a8` ;
- replay complet : quatre hashes identiques ;
- doublons métier : 0 ;
- perte : 0 ;
- mismatch de hash : 0 ;
- appels fournisseur et crédits au replay : 0.

Le run autoritatif utilise
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`. Il vérifie
PostgreSQL `0008` avec 304 preuves examinées et 304 doublons évités sur chacun
des deux passages, ainsi que R2 à 25 453 / 25 453 objets, lag 0.

## Verdict

`JALON_11_BLOCKED_BY_DATA_GATES`.

Le test principal n'ajoute aucune information au marché recalibré. 11A et 11F
restent des diagnostics descriptifs non promouvables, 11E termine l'évaluation
de gates avec huit hypothèses bloquées, et 11B/11C/11D/11G restent data-gated.
Watchlist, candidats, décisions et mises restent à zéro.
