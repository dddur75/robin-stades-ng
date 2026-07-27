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
| Poisson | marché déviggué | fixture exacte | à compléter si prix valides |
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
| External league transfer | La règle reste-t-elle positive séparément en Bundesliga et Serie A ? | `NO_EXTERNAL_SURVIVOR` |
| Negative controls V1 | Labels mélangés, fuite, règle triviale et règles impossibles sont-ils rejetés ? | `VERIFIED_7_OF_7` |
| Deterministic replay | Configuration, règles, métriques et hashes sont-ils identiques ? | `VERIFIED_IDENTICAL` |
| Public Ledger V1 | Décisions et règlements forment-ils une chaîne append-only valide ? | `VERIFIED_EMPTY_LEDGER_AND_TESTS` |
| Shadow Bankroll V1 | La comptabilité fixe de 1 unité est-elle rejouable ? | `VERIFIED_EMPTY_LEDGER_AND_TESTS` |

Paramètres gelés : support 80 paris / 3 saisons, q ≤ 0,05, bootstrap groupé
1 000, au moins 2 folds admissibles, 15 paris par fold, ratio positif ≥ 0,67 et
dernier fold positif. Bundesliga et Serie A exigent chacune 40 paris et un ROI
positif. Les données restent exposées et ne peuvent produire `VALIDATED`.

Résultat V1 : 700/700 hypothèses exécutées, 167 rejets support, 118 positives
brutes, 24 survivantes walk-forward brutes, 0 survivante FDR, 0 externe et
0 candidat shadow. Verdict : `JALON_10_NO_ROBUST_PATTERN_FOUND`.
