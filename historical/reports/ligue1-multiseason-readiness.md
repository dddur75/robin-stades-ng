# Ligue 1 — readiness multi-saison

Généré : `2026-08-09T04:14:46.220915+00:00`.

Les couvertures sont calculées depuis les Parquet et observations du registre durable. Une absence reste une absence ; elle n'est jamais remplacée par zéro.

## Gates

| Gate | Statut | Saisons éligibles |
|---|---|---|
| A | BLOCKED_BY_COVERAGE | 2018, 2020, 2021, 2022, 2023, 2024, 2025 |
| B | API_PLAYER_DATASET_READY | 2020, 2021, 2022, 2023, 2024, 2025 |
| C | POST_LINEUP_SIMULATED_READY | 2020, 2021, 2022, 2023, 2024, 2025 |
| D | BLOCKED_BY_TEMPORALITY | — |

## Couverture

| Saison | Fixtures | Résultats | Stats joueurs | Compositions | Statut |
|---:|---:|---:|---:|---:|---|
| 2018 | 380/380 | 380/380 | 0.0% | 0.0% | REGULAR_SEASON_CANONICAL |
| 2019 | 279/380 | 279/380 | 73.4% | 73.4% | PARTIAL |
| 2020 | 380/380 | 380/380 | 100.0% | 100.0% | REGULAR_SEASON_CANONICAL |
| 2021 | 380/380 | 380/380 | 100.0% | 100.0% | REGULAR_SEASON_CANONICAL |
| 2022 | 380/380 | 380/380 | 100.0% | 100.0% | REGULAR_SEASON_CANONICAL |
| 2023 | 306/306 | 306/306 | 100.0% | 100.0% | REGULAR_SEASON_CANONICAL |
| 2024 | 306/306 | 306/306 | 100.0% | 100.0% | REGULAR_SEASON_CANONICAL |
| 2025 | 306/306 | 306/306 | 99.0% | 99.7% | REGULAR_SEASON_CANONICAL |

## Temporalité

Les statistiques de la fixture cible restent `POST_MATCH_ONLY`. Les compositions cibles ne sont autorisées que dans `POST_LINEUP_SIMULATED`. Les blessures restent `HISTORICAL_NON_POINT_IN_TIME` et sont exclues des modèles causaux.

Production : `PRODUCTION_LOCKED`.
