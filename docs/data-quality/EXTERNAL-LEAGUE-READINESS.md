# Readiness externe multi-ligues

Mesure initiale : `historical-data@9aa54ef`, cache uniquement, 0 appel et
0 crédit fournisseur.

| Compétition | Saisons | Fixtures | Équipes observées | Joueurs roster | TEAM | PLAYER | LINEUP | MARKET |
|---|---:|---:|---:|---:|---|---|---|---|
| Premier League | 7 | 2 660 | 28 | 5 216 | `READY` | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `UNAVAILABLE` |
| La Liga | 7 | 2 660 | 28 | 5 042 | `READY` | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `UNAVAILABLE` |
| Bundesliga | 7 | 2 156 | 28 | 4 178 | `READY` | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `UNAVAILABLE` |
| Serie A | 7 | 2 661 | 31 | 5 530 | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `UNAVAILABLE` |
| Ligue des champions | 7 | 1 594 | 209 | 14 392 | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `BLOCKED_BY_COVERAGE` | `UNAVAILABLE` |

Les 11 731 fixtures ont cible, provenance et temporalité valides. Les taux
d’identité équipe sont 100 % pour PL/Liga/Bundesliga, 93,55 % pour Serie A et
95,22 % pour UCL. Ces deux dernières ligues attendent donc le backfill des
identités. Les statistiques joueurs par match et compositions externes ne sont
pas encore persistées. Les effectifs reçus ne sont jamais assimilés à des
statistiques par match.

Le manifeste machine versionné est
`historical/external/readiness/external-league-readiness-v1.json`.
