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

État avant campagne : `PENDING_REAL_CACHE_ONLY_RUN`. Aucun modèle n’est
réentraîné, retuné, promu ou déclaré `MODEL_VALIDATED`. Le marché déviggué reste
la baseline économique ; un pattern doit au minimum lui survivre avec prix
observés, FDR, walk-forward et contrôles négatifs.
