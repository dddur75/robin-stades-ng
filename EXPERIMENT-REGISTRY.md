# Registre des expériences

## Jalon 5

| Expérience | Question | État |
|---|---|---|
| J5 Dataset Factory V1 | Les features d’équipe sont-elles reproductibles sans fuite ? | `VERIFIED_LEGACY` |
| J5 Elo OOS | La baseline reste-t-elle calibrée sur 2024–2025 ? | `OOS_BACKTEST_V1_READY` |
| J5 API-Football pilote | La Ligue 1 2025 est-elle profondément couverte ? | `HISTORICAL_PILOT_ACTIVE` |
| J5 Player lift | Les variables joueurs améliorent-elles l’OOS ? | `BLOCKED_BY_COVERAGE` |

## Expériences antérieures

| Expérience | Question | État |
|---|---|---|
| Vague 1 | Les hypothèses pré-enregistrées battent-elles le prix ? | `PARTIAL` |
| Vague 1B | Les hypothèses complémentaires résistent-elles séparément ? | `PARTIAL` |
| Vague 2 | Des combinaisons d'atomes produisent-elles un lift ? | `UNVERIFIED` |
| Vague 2B | Le lift survit-il à une référence ajustée au marché ? | `PARTIAL` |
| Confrontation | Les candidats conservent-ils un edge prospectif ? | `IN_PROGRESS` |
| J2 OOS 2025–2026 | Les stratégies simples résistent-elles en walk-forward ? | `VERIFIED_NO_PROMOTION` |
| Shadow V1 Ligue 1 | Les décisions restent-elles reproductibles prospectivement ? | `INFRASTRUCTURE_READY` |
| Burn-in Jalon 4 | La chaîne reste-t-elle durable, complète et récupérable ? | `ACTIVE_DESCRIPTIVE_ONLY` |

La distinction obligatoire est :

`BACKTEST EXPLORATOIRE` → `HORS ÉCHANTILLON` → `SHADOW TEST` → `PRODUCTION`.

Le dépôt ne fournit encore aucun résultat au stade `PRODUCTION`. Le résultat
Over 2,5 observé en OOS reste inconclusif et n'est pas mélangé aux futures
performances shadow.

## Expériences Jalon 6

| Expérience | Comparaison | Décision possible |
|---|---|---|
| A | legacy/team baseline vs API équipe | retained/inconclusive/rejected |
| B | API équipe vs joueur pré-lineup | incrémental uniquement |
| C | pré-lineup vs composition simulée | historique simulé |
| D | statistique vs marché dévigué | OOS uniquement |
| E | individuel vs ensemble | différé jusqu'aux modèles validés |

Le choix des features, calibrations et seuils s'arrête avant l'ouverture de
2024–2025.

## Jalon 7 — registre préenregistré

| Expérience | Comparateur | Unité | Décision actuelle |
|---|---|---|---|
| HGB équipe | multinomiale équipe | fixture exacte | `INCONCLUSIVE` |
| Poisson | marché déviggué | fixture exacte | non complété dans le Jalon 7 |
| Dixon–Coles | Poisson | fixture exacte | `INCONCLUSIVE` |
| joueurs pré-lineup | équipe | fixture exacte | `INCONCLUSIVE` |
| post-lineup | joueurs pré-lineup | fixture exacte | inférieur, non promu |

Les contrôles cibles permutées et lineups aléatoires sont obligatoires.
## Jalon 8

| Expérience | Échantillon | Résultat |
|---|---:|---|
| Transfert vs league-specific | 2 136 | inconclusif, CI 95 % traverse zéro |
| League-specific vs pooled | 2 136 | inconclusif, CI 95 % traverse zéro |
| Dixon–Coles vs Poisson | 2 136 | inconclusif |
| Poisson vs discriminatif | 2 136 | Poisson inférieur, CI 95 % positive |
| Leave-one-league-out | 760/760/616 | prêt PL/Liga/Bundesliga |
| Contrôles négatifs | 15 | aucun signal anormal |

## Expériences Jalon 9

| Expérience | Statut initial |
|---|---|
| Football-Data 2020–2025 | pipeline prêt, preuve durable à mesurer |
| Matching fixture/marché | seuil 98 %, ambiguïtés utilisées = 0 |
| The Odds API historique | dry-run, 0 crédit |
| Market paired validation | conditionnée par MARKET_GATE |
| Strategy Lab V4 | conditionné par MARKET_GATE |
| Migration R2 | dry-run, suppression interdite |

## Expériences Jalon 10

| Expérience | Question | État |
|---|---|---|
| Pattern Campaign V1 | Une règle simple survit-elle à FDR, bootstrap et walk-forward ? | `NO_FDR_SURVIVOR` |
| Exposed cross-league stability | La règle reste-t-elle positive séparément dans les sous-groupes exposés Bundesliga et Serie A ? | `NO_EXPOSED_CROSS_LEAGUE_SURVIVOR` |
| Negative controls V1 | Labels mélangés, fuite, règle triviale et règles impossibles sont-ils rejetés ? | `VERIFIED_7_OF_7` |
| Deterministic replay | Configuration, règles, métriques et hashes sont-ils identiques ? | `VERIFIED_IDENTICAL` |
| Public Ledger V1 | Décisions et règlements forment-ils une chaîne append-only valide ? | `VERIFIED_EMPTY_LEDGER_AND_TESTS` |
| Shadow Bankroll V1 | La comptabilité fixe de 1 unité est-elle rejouable ? | `VERIFIED_EMPTY_LEDGER_AND_TESTS` |

Paramètres gelés : support 80 paris / 3 saisons, q ≤ 0,05, bootstrap groupé
1 000, au moins 2 folds admissibles, 15 paris par fold, ratio positif ≥ 0,67 et
dernier fold positif. Bundesliga et Serie A exigent chacune 40 paris et un ROI
positif. Les données restent exposées et ne peuvent produire `VALIDATED`.

Résultat V1 : 700/700 hypothèses exécutées, 167 rejets support, 118 positives
brutes, 24 survivantes walk-forward brutes, 0 survivante FDR, 0 survivante du
contrôle inter-ligues exposé et 0 candidat shadow. Verdict :
`JALON_10_NO_ROBUST_PATTERN_FOUND`.

Sous-verdict :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`. Les
familles équipe, calendrier/repos, joueurs, tactique et autres marchés ne font
pas partie des 700 règles. Le contrôle Bundesliga/Serie A réutilise le corpus
exposé et ne constitue pas un holdout externe indépendant.

## Expériences Jalon 11

| Expérience | Question | Échantillon | Résultat |
|---|---|---:|---|
| 11A primaire | marché + équipe améliore-t-il le marché recalibré train-only ? | 7 081 | Δ LL +0,001702 ; IC traverse zéro |
| 11A diagnostics post-contrat | les challengers team-only ou GBT incrémental falsifient-ils le résultat ? | 7 081 | 5 diagnostics, tous non promouvables |
| 11B disponibilité | les absences apportent-elles un résidu ? | 0 | `DATA_GATE_BLOCKED` |
| 11C lineup | la continuité apporte-t-elle un résidu ? | 0 | `DATA_GATE_BLOCKED` |
| 11D formations | les interactions tactiques sont-elles stables ? | 0 | `DATA_GATE_BLOCKED` |
| 11E H11-001…008 | les intuitions propriétaire sont-elles éligibles ? | 0 | gate evaluation terminée, huit bloquées |
| 11F transfert équipe | l'effet équipe se transfère-t-il entre ligues ? | 5 rotations, N 2 743–3 040 | descriptif, 0 positive, 0 survivante |
| 11G intégrée | B2–B4 améliorent-ils B0/B1 ? | 0 | `DATA_GATE_BLOCKED` |
| contrôles négatifs | un faux edge peut-il être promu ? | 12 contrôles | aucun faux edge promu |
| replay | les résultats sont-ils déterministes ? | 1 replay | hash identique |

Paramètres : seed 11011, expanding walk-forward, 999 permutations, 729 dates
clusterisées, BH par famille et globale. Le primaire donne p CR1 `0,9638269`,
q famille `0,9638269` et q globale `1,0`. Huit hypothèses bloquées sont incluses
dans la multiplicité.

Le contrôle `impossible_condition` est réellement calculé sur 7 081 lignes :
le prédicat `OUTCOME_IS_HOME_AND_AWAY` a un support nul et le statut
`EXECUTED_ZERO_SUPPORT_NO_PROMOTION`.

Le replay complet conserve le hash
`ff37983cc85ad77716ce1b96e3499da1e29908c133c6b085e86fdfd9667a1cfe`
et vérifie les quatre hashes campagne, dataset, Parquet et ledger avec zéro
doublon, perte, mismatch, appel et crédit.

Verdict : `JALON_11_BLOCKED_BY_DATA_GATES`. Aucun résultat historique n'est
qualifié de `VALIDATED`.
