# Ligue 1 — readiness multi-saison

La version exacte est recalculée dans
`historical/readiness/ligue1-multiseason-v1.json`. Le dernier audit local du
registre durable donne :

| Saison | Fixtures canoniques | Résultats | Stats joueurs | Lineups |
|---:|---:|---:|---:|---:|
| 2018 | indisponible | — | — | — |
| 2019 | indisponible | — | — | — |
| 2020 | 380/380 | 380/380 | indisponible | indisponible |
| 2021 | 380/380 | 380/380 | 312/380 | 380/380 |
| 2022 | 380/380 | 380/380 | 380/380 | 380/380 |
| 2023 | 306/306 | 306/306 | 306/306 | 306/306 |
| 2024 | 306/306 | 306/306 | 306/306 | 306/306 |
| 2025 | 306/306 | 306/306 | 303/306 | 305/306 |

Les barrages sont `PLAYOFF_EXCLUDED`; les annulations, abandons et doublons
ont leurs propres classifications. Les valeurs nulles sont mesurées dans les
payloads, jamais remplacées par zéro.

| Gate | Statut | Motif |
|---|---|---|
| A | `API_TEAM_DATASET_READY` | 6 saisons, provenance et temporalité vertes |
| B | `API_PLAYER_DATASET_READY` | 4 saisons ≥ 90 %, identités et minutes cohérentes |
| C | `POST_LINEUP_SIMULATED_READY` | 5 saisons ≥ 90 %, onze résolus |
| D | `BLOCKED_BY_TEMPORALITY` | blessures rétrospectives non datées |

