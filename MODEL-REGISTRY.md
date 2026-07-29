# Registre des modèles

## Model Lab Jalon 5

| Modèle | Version | Dataset | OOS | Statut |
|---|---:|---|---|---|
| Elo interprétable | `elo_v1` | `team_baseline_v1` | Log Loss 1,0075 ; Brier 0,2010 ; N=6 443 | `OOS_BACKTEST_V1_READY` |
| Poisson / Dixon-Coles | v1 planifié | API-Football | — | `BLOCKED_BY_COVERAGE` |
| Force joueurs / composition | v1 planifié | `team_player_v1` | — | `BLOCKED_BY_COVERAGE` |
| Logistique / gradient boosting | v1 planifié | datasets versionnés | — | `BLOCKED_BY_COVERAGE` |
| Marché / ensemble calibré | v1 planifié | odds réconciliées | — | `BLOCKED_BY_COVERAGE` |

L’Elo est une preuve historique legacy, pas une preuve prospective live.

## Baselines existantes

| Modèle | Version | Statut | Preuve |
|---|---:|---|---|
| Marché dé-viggé proportionnel | 0.1 | `VERIFIED` | test de somme à 1 |
| Marché dé-viggé Shin | 0.1 | `VERIFIED` | utilisé par `probas_justes` |
| Taux de base segmenté | 0.1 | `PARTIAL` | rapports Vague 1/2 |

## Modèles probabilistes Jalon 2

| Modèle | Version | Statut | Usage |
|---|---:|---|---|
| Elo | 1.0 | `SHADOW_READY` | probabilités 1N2 interprétables |
| Poisson | 1.0 | `SHADOW_READY` | buts attendus et 1N2 |
| Dixon-Coles | 1.0 | `SHADOW_READY` | correction faibles scores |
| Consensus Elo–Poisson | 1.0 | `SHADOW_READY` | référence initiale |
| Marché dé-viggé | 1.0 | `SHADOW_READY` | baseline si snapshot disponible |
| Régression logistique | — | `NOT_STARTED` | hors périmètre |
| Gradient boosting | — | `NOT_STARTED` | hors périmètre |
| Ensemble calibré | — | `NOT_STARTED` | hors périmètre |

Tous appliquent un cutoff temporel strict et enregistrent `as_of_time`.
`SHADOW_READY` n'implique pas de validation prospective. Aucun modèle n'est
`PRODUCTION_READY`.

## État prospectif Jalon 4

Seul `MARKET_BASELINE_ONLY` a produit une prédiction live, faute de données
sportives profondes API-Football. Elle reste `SHADOW_ONLY`, versionnée et
rejouable. Aucun modèle n’est promu pendant le burn-in.

## Model Lab API-Football

| Modèle | Dataset | Statut |
|---|---|---|
| `api_elo_v1` | équipe | `API_OOS_BACKTEST_READY` |
| `api_team_multinomial_v1` | équipe | `API_OOS_BACKTEST_READY` |
| `api_player_pre_lineup_multinomial_v1` | équipe + attendu | `PLAYER_MODEL_TESTING` |
| `api_post_lineup_simulated_multinomial_v1` | équipe + confirmé simulé | `PLAYER_MODEL_TESTING` |
| `market_devigged_baseline_v1` | marché | `API_OOS_BACKTEST_READY` |

Poisson, Dixon-Coles, gradient boosting et ensemble restent planifiés. Aucun
modèle n'est `PRODUCTION_READY`.

Mesures initiales OOS : `api_elo_v1` 1,1642 / 0,1986,
`api_team_multinomial_v1` 1,0518 / 0,2012,
`api_player_pre_lineup_multinomial_v1` 1,0267 / 0,2043 et
`api_post_lineup_simulated_multinomial_v1` 1,6920 / 0,2108
(Log Loss / Brier). Le gain joueur est inconclusif car les deux métriques ne
s'améliorent pas ensemble ; la variante lineup simulée est rejetée.

## Jalon 7

Familles admises dans l'arène : multinomiale, gradient boosting histogramme,
Poisson, Dixon–Coles, marché déviggué, pré-lineup joueurs et audit post-lineup.
La preuve appariée confirme le modèle joueurs `INCONCLUSIVE` (Δ Log Loss
+0,00056; CI 95 % croise zéro) et le post-lineup inférieur au pré-lineup
(Δ +0,03178). Aucun statut `MODEL_VALIDATED` ou `LIVE_SHADOW_CANDIDATE` n'est
accordé.
## Jalon 8 — arène externe

| Famille | Fixtures appariées | Log Loss | Statut |
|---|---:|---:|---|
| Ligue 1 frozen transfer | 2 136 | 0,9945 | `FROZEN_TRANSFER_EVALUATED` |
| League-specific | 2 136 | 0,9983 | `LEAGUE_SPECIFIC_EVALUATED` |
| Pooled | 2 136 | 0,9958 | `POOLED_MODEL_EVALUATED` |
| Poisson | 2 136 | 1,0317 | `EXTERNAL_VALIDATION_FAILED` face au discriminatif |
| Dixon–Coles | 2 136 | 1,0312 | `INCONCLUSIVE` face à Poisson |

Aucun modèle n’est `PRODUCTION_READY`; aucun candidat shadow n’est promu.

## Validation marché Jalon 9

Les modèles Jalon 8 restent gelés. Ils ne sont comparés au marché que pour une
ligue dont MARKET_GATE est READY, sur échantillon apparié. Sans amélioration
robuste : `NO_EXTERNAL_VALIDATED_EDGE`, zéro promotion.

## Jalon 10

Le Pattern Research Engine est un moteur de règles et d’évaluation, pas un
nouveau modèle probabiliste. Les modèles Jalons 7–9 restent gelés et leurs
résultats historiques restent exposés.

État après campagne : `JALON_10_NO_ROBUST_PATTERN_FOUND`. Les 700 règles ont
été exécutées, mais aucune ne survit à la FDR et aucun candidat shadow n’est
créé. Aucun modèle n’est réentraîné, retuné, promu ou déclaré
`MODEL_VALIDATED`. Le marché déviggué reste la baseline économique.

Sous-verdict :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`. Les
700 règles portent uniquement sur des tranches de cote, marge, catégorie de
prix et compétition. Les modèles et features d’équipe, calendrier, joueurs et
tactiques n’ont pas été testés par cette campagne.

## Jalon 11 — Deep Football Arena

Échantillon strictement apparié : 7 081 fixtures, folds 2022–2025.
`TEAM_GATE=PARTIAL`; toutes les métriques restent historiques descriptives.

### Test principal correctif

Ce comparateur principal n'est pas préenregistré. La version
`1.0.0-amendment-1` a été enregistrée après l'exécution des diagnostics
team-only, mais avant le run autoritatif `30282406035`. L'amendement est
traçable par le hash
`37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa`
et reste explicitement non promouvable.

| Modèle | Features | Log Loss | Brier | Δ LL | Statut |
|---|---|---:|---:|---:|---|
| `B0_MARKET_RECALIBRATED_TRAIN_ONLY` | marché recalibré sur train | 0,968936 | 0,192127 | — | `REFERENCE` |
| `B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` | marché + équipe/calendrier | 0,970638 | 0,192468 | +0,001702 | `PRIMARY_CORRECTIVE_NON_PROMOTABLE_TEAM_GATE_PARTIAL` |

IC 95 % du delta Log Loss :
`[-0,000242884 ; +0,003901782]`; p CR1 `0,9638269`; q globale `1,0`.

### Diagnostics post-contrat initial, antérieurs à l'amendement

| Modèle | Log Loss | Brier | Δ LL | Statut |
|---|---:|---:|---:|---|
| `B0_MARKET` brut | 0,966773 | 0,191619 | — | diagnostic |
| `B1_TEAM_ONLY_REGULARIZED_MULTINOMIAL` | 0,988918 | 0,196458 | +0,022145 | non promouvable |
| `B1_TEAM_ONLY_BOUNDED_GRADIENT_BOOSTING` | 0,998024 | 0,198176 | +0,031251 | non promouvable |
| `B1_TEAM_ONLY_POISSON` | 1,046019 | 0,209819 | +0,079246 | non promouvable |
| `B1_TEAM_ONLY_DIXON_COLES` | 1,046626 | 0,209863 | +0,079853 | non promouvable |
| `B1_MARKET_PLUS_TEAM_BOUNDED_GRADIENT_BOOSTING` | 0,978452 | 0,193938 | +0,009516 | non promouvable |

Les quatre modèles team-only sont comparés au marché brut ; le gradient
boosting incrémental est comparé au marché recalibré. Aucune sélection n'utilise
les labels du test.

| Famille profonde | Statut |
|---|---|
| B2 joueurs pré-lineup | `DATA_GATE_BLOCKED` |
| B3 lineup confirmée | `DATA_GATE_BLOCKED` |
| B4 matchups | `DATA_GATE_BLOCKED` |

Aucun modèle n'est promu, calibré pour une décision live ou déclaré
`MODEL_VALIDATED`.

La preuve autoritative porte le hash campagne
`437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355`
et la source
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`.

## Prequential Learning Factory V1

La factory prépare six scopes :

| Scope | Référence initiale | Challenger initial |
|---|---|---|
| `GLOBAL_FIVE_LEAGUES` | marché dé-vigué, version gelée | admissible lorsque le support temporel est suffisant |
| `LIGUE_1` | marché dé-vigué, version gelée | `INSUFFICIENT_TRAINING_SUPPORT` autorisé |
| `PREMIER_LEAGUE` | marché dé-vigué, version gelée | `INSUFFICIENT_TRAINING_SUPPORT` autorisé |
| `LIGA` | marché dé-vigué, version gelée | `INSUFFICIENT_TRAINING_SUPPORT` autorisé |
| `BUNDESLIGA` | marché dé-vigué, version gelée | `INSUFFICIENT_TRAINING_SUPPORT` autorisé |
| `SERIE_A` | marché dé-vigué, version gelée | `INSUFFICIENT_TRAINING_SUPPORT` autorisé |

Une version conserve `model_id`, `model_version`, `created_at`,
`training_cutoff`, `feature_contract_hash`, `code_revision`, son artifact et
son statut. Une référence active n’est jamais mise à jour en place. Le
challenger exige au moins 30 nouvelles fixtures réglées et éligibles dans deux
ligues ; sinon l’entraînement est différé.

Le gate de promotion reste `PROMOTION_LOCKED`. La comparaison
référence/challenger est une évaluation descriptive : elle ne crée ni pari
réel, ni candidat automatiquement promu, ni déclaration de rentabilité.
