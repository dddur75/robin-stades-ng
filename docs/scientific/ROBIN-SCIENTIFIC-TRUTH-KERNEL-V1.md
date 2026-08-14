# Robin Scientific Truth Kernel V1

## Résultat technique

Le noyau mathématique est réparé et versionné au commit `c2bb1769a611728a44c19477932d37e6ab11e5a7` : le ROI et le yield utilisent le turnover réellement misé, `profit_per_bet` porte désormais sa propre définition, les méthodes de-vig sont explicites, et les chemins actifs migrés échouent fermés sur un marché invalide ou une méthode absente.

Le verdict global reste **`ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL` / `PASS_AND_HOLD`**. L'autorité de-vig globale est **`CONFLICTING`** ; aucune méthode n'a été choisie sur la base du ROI. Chronos conserve une autorité `UNIQUE` uniquement dans son scope CANARY point-in-time, marché complet et same-receipt. Les 72 surfaces temporelles restent `TEMPORAL_VALIDITY_NOT_PROVEN`.

## Les corrections ferment le calcul, pas la validité historique complète

- `profit_units = sum(detail.profit)`
- `turnover_units = sum(detail.stake)`
- `roi = profit_units / turnover_units` si le turnover est positif, sinon `null`
- `yield = roi`, version `profit_over_turnover_v1`
- `profit_per_bet = profit_units / bets` si des paris existent, sinon `null`

Le test rouge obligatoire a reproduit `1 / (|2| + |-1|) = 1/3` à la place du ROI attendu `1 / (1 + 1) = 1/2`. Les tests corrigés couvrent FIXED, proportionnel, Kelly fractionné, mise variable, cap, ruine, zéro pari et frontières de settlement.

## Les 15 résultats représentent 45 rendus, pas 45 expériences

Les deux JSON cockpit audités contiennent 15 résultats logiques, chacun rendu sur trois surfaces : `deepData.backtests`, `deepData.strategies` et `cockpit-expert-data.backtests`. Le replay LOOP54 relie 30 copies par `COPY_OF`; il ne les recompte jamais comme expériences indépendantes.

La correction ci-dessous est un **`FORMULA_REPLAY_FROM_STORED_PROFIT_AND_FIXED_STAKE_BET_COUNT`**. Les objets déclarent FIXED et publient bets/profit, ce qui permet de recalculer `profit/bets`. Ils ne publient ni les paris unitaires, ni les cotes, ni les sélections, ni la méthode de-vig : les branches de portfolio PROPORTIONAL/SHIN restent `NON VÉRIFIÉ`.

| Stratégie | Bets | Profit (u) | ROI stocké | ROI réparé | Écart absolu |
|---|---:|---:|---:|---:|---:|
| api_elo_v1_1x2_edge_0.02 | 382 | 0.07 | 0.000139422789651 | 0.000183246073298 | 4.38232836476e-05 |
| api_elo_v1_1x2_edge_0.04 | 342 | -9.39 | -0.0209313211921 | -0.0274561403509 | 0.00652481915875 |
| api_elo_v1_1x2_edge_0.06 | 260 | -5.25 | -0.0150537634409 | -0.0201923076923 | 0.00513854425145 |
| api_player_pre_lineup_multinomial_v1_1x2_edge_0.02 | 396 | -36.33 | -0.065146054118 | -0.0917424242424 | 0.0265963701244 |
| api_player_pre_lineup_multinomial_v1_1x2_edge_0.04 | 361 | -46.77 | -0.0918445496141 | -0.129556786704 | 0.0377122370895 |
| api_player_pre_lineup_multinomial_v1_1x2_edge_0.06 | 307 | -29.95 | -0.0677525166836 | -0.0975570032573 | 0.0298044865737 |
| api_post_lineup_simulated_multinomial_v1_1x2_edge_0.02 | 388 | -54.33 | -0.102962078572 | -0.140025773196 | 0.037063694624 |
| api_post_lineup_simulated_multinomial_v1_1x2_edge_0.04 | 353 | -64.15 | -0.13595422274 | -0.181728045326 | 0.0457738225855 |
| api_post_lineup_simulated_multinomial_v1_1x2_edge_0.06 | 304 | -48.38 | -0.117535591079 | -0.159144736842 | 0.041609145763 |
| api_team_multinomial_v1_1x2_edge_0.02 | 393 | -17.92 | -0.0349945321044 | -0.0455979643766 | 0.0106034322722 |
| api_team_multinomial_v1_1x2_edge_0.04 | 338 | -6.02 | -0.0133783723721 | -0.0178106508876 | 0.00443227851547 |
| api_team_multinomial_v1_1x2_edge_0.06 | 271 | -10.49 | -0.0290171779481 | -0.0387084870849 | 0.00969130913682 |
| market_devigged_baseline_v1_1x2_edge_0.02 | 339 | -31.66 | -0.0794798413416 | -0.0933923303835 | 0.0139124890419 |
| market_devigged_baseline_v1_1x2_edge_0.04 | 261 | -12.43 | -0.0412176277481 | -0.0476245210728 | 0.00640689332468 |
| market_devigged_baseline_v1_1x2_edge_0.06 | 200 | -11.57 | -0.0534583930139 | -0.05785 | 0.00439160698609 |

Les 45 champs ROI sont invalidés append-only ; les 45 yields ne le sont pas, car ils égalaient déjà `profit/bets` sous FIXED 1u. Le ledger d'invalidation ne réécrit pas les résultats cockpit. LOOP55 corrige séparément leurs labels de temporalité dans les artefacts courants, sans changer les résultats de formule stockés. Le plus grand écart absolu est `0.04577382258550142`; aucun signe de profit, statut `INCONCLUSIVE`, verrou `PRODUCTION_LOCKED` ou `NO_PROMOTION` ne change.

## L'autorité de-vig reste conflictuelle

L'audit a recensé exactement 15 mécanismes historiques, dont un défaut Shin legacy, plusieurs variantes proportionnelles aux politiques d'entrées divergentes, le contrat Chronos borné, et un chemin shadow historiquement fondé sur la probabilité implicite brute. LOOP54 fournit une interface centrale stricte pour `PROPORTIONAL` et `SHIN`, avec méthode demandée/effective, version et hash de définition. Cela rend l'exécution rejouable ; cela ne crée pas une autorité globale.

Les preuves de sensibilité sont conservées sans arbitrage : 1 563 marchés OOS complets, 51 divergences bet/no-bet et 75 décisions complètes ; 20 000 marchés synthétiques (seed 20260813), 10,11 % de divergences bet/no-bet et 21,46 % de décisions complètes. Ces chiffres décrivent la sensibilité au protocole, jamais une sélection par performance.

## Le chemin décisionnel reste partiellement prouvé

La fixture offline trace odds complètes → de-vig explicite → probabilités justes → modèle → edge → seuil → décision → mise → settlement → profit → turnover → ROI/yield. La parité est prouvée pour les fixtures et chemins migrés couverts par tests.

Le verdict production reste `PRODUCTION_DECISION_PATH_STILL_NOT_PROVEN` : les timestamps de publication fournisseur, `data_available_at`, as-of joins, lineage des features, état durable live et toutes les 72 surfaces temporelles ne sont pas fermés. Les anciennes lignes SQL préquentielles conservent leur hash persistant avec `SCIENTIFIC_LINEAGE_NOT_PERSISTED`; d'anciennes projections prospectives incomplètes/underround peuvent exiger un rebuild séparément autorisé.

## La multiplicité reste fermée

Les artefacts gelés réutilisés prouvent 300 tests atomiques + 7 180 tests de paires = 7 480, zéro paire survivante et recherche triple verrouillée. Les trois cartes « découverte machine » ont `q=1`, restent `EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING`, `PROSPECTIVE_FROZEN`, avec zéro observation live. LOOP54 ne génère aucune hypothèse ni promotion.

## Sources et rapports versionnés

Base auditée : `1ffeec1cd89e83deda008da39bb22540a70db896`. Manifeste audit : `38559704269d4e31b9406fc3ca90a8d8ba3fa4c16b0e8e8a89eaeaeaef6e5476`. Réparation code : `c2bb1769a611728a44c19477932d37e6ab11e5a7`.

- [scientific-truth-defect-inventory-v1.json](../../reports/scientific-truth/scientific-truth-defect-inventory-v1.json)
- [roi-turnover-repair-v1.json](../../reports/scientific-truth/roi-turnover-repair-v1.json)
- [yield-consumer-inventory-v1.json](../../reports/scientific-truth/yield-consumer-inventory-v1.json)
- [devig-implementation-inventory-v1.json](../../reports/scientific-truth/devig-implementation-inventory-v1.json)
- [devig-canonicalization-v1.json](../../reports/scientific-truth/devig-canonicalization-v1.json)
- [decision-path-trace-v1.json](../../reports/scientific-truth/decision-path-trace-v1.json)
- [historical-truth-replay-v1.json](../../reports/scientific-truth/historical-truth-replay-v1.json)
- [historical-invalidation-ledger-v1.json](../../reports/scientific-truth/historical-invalidation-ledger-v1.json)

Chaque rapport JSON porte son claim ID, ses Evidence IDs, les hashes d'entrée, un content hash canonique, ses limites et des compteurs d'effets externes tous égaux à zéro.

## Limites et prochaine étape

Ce travail ne prouve ni rentabilité, ni causalité, ni absence de fuite, ni préparation production. Aucun accès Neon/PostgreSQL production/R2/provider, aucune migration, aucun workflow live, aucun pari et aucune promotion n'ont été exécutés.

La prochaine mission est **LOOP55 — Robin Point-in-Time Lineage Closure V1** : timestamps de disponibilité et fournisseur, ingestion, as-of joins, cutoff des features, mutations futures adversariales et fermeture des 72 surfaces temporelles.
