# Jalon 11 — matrice de couverture

Snapshot cache-only du 27 juillet 2026. Les colonnes `Player` et `Lineup`
indiquent une couverture de contenu estimée en fixtures, pas une disponibilité
pré-match. En Ligue 1, ces observations sont `POST_MATCH_ONLY`.

## Couverture par ligue et saison

| Ligue | Saison | Marché | Équipe | Player | Lineup | XI exacts (équipes) | Formations (équipes) | Blessures | Pied sourcé |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ligue 1 | 2020 | 380 | 380 | 380 | 380 | 764 | 764 | 0 | 0 |
| Ligue 1 | 2021 | 380 | 380 | 380 | 380 | 764 | 764 | 2 681 | 0 |
| Ligue 1 | 2022 | 380 | 380 | 380 | 380 | 760 | 750 | 2 717 | 0 |
| Ligue 1 | 2023 | 306 | 306 | 306 | 306 | 616 | 615 | 2 078 | 0 |
| Ligue 1 | 2024 | 306 | 306 | 306 | 306 | 616 | 616 | 2 460 | 0 |
| Ligue 1 | 2025 | 306 | 306 | 306 | 306 | 618 | 618 | 2 865 | 0 |
| Premier League | 2020 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2021 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2022 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2023 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2024 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2025 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2020 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2021 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2022 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2023 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2024 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2025 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2020 | 306 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2021 | 306 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2022 | 306 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2023 | 306 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2024 | 305 | 305 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2025 | 306 | 306 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2020 | 379 | 379 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2021 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2022 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2023 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2024 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2025 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 |

## Totaux observés

- marché 1X2 et O/U 2,5 : 10 732 fixtures ;
- appariement équipe/calendrier : 10 732 / 10 732, sans doublon ;
- lignes équipes-joueurs : 4 134 ;
- lignes équipes-lineups : 4 138 ;
- XI exacts : 4 138 ;
- formations présentes et grilles complètes : 4 127 ;
- blessures : 12 801 lignes, toutes non point-in-time ;
- pied fort observé et sourcé : 0.

## Gates

| Gate | Statut | Preuve ou blocage |
|---|---|---|
| `TEAM_GATE` | `PARTIAL` | 10 732 / 10 732 appariées, cible exclue par ordre algorithmique, `observed_at` source non prouvé |
| `MARKET_GATE` | `READY` historique seulement | prix 1X2/O-U présents ; `observed_at` exact absent |
| `PLAYER_GATE` | `BLOCKED_BY_TEMPORALITY` | profondeur Ligue 1 seulement, observations post-match |
| `PLAYER_FORM_GATE` | `BLOCKED_BY_TEMPORALITY` | fenêtres V1 mêlent remplaçants non utilisés ; null/zero buts ambigu |
| `STARTER_BASELINE_GATE` | `BLOCKED_BY_TEMPORALITY` | baseline V1 et lignée as-of insuffisamment prouvées |
| `LINEUP_GATE` | `BLOCKED_BY_TEMPORALITY` | lineups proches de la complétude mais post-match |
| `FORMATION_GATE` | `BLOCKED_BY_TEMPORALITY` | contenu presque complet en L1, cutoff pré-kickoff absent |
| `ABSENCE_GATE` | `BLOCKED_BY_TEMPORALITY` | blessures historiques sans date d'annonce exploitable |
| `FOOTEDNESS_GATE` | `BLOCKED_BY_COVERAGE` | aucun champ de pied sourcé en cache |

## Lecture correcte

Une couverture de contenu élevée ne ferme pas un gate temporel. Les 4 138 XI
exacts et les 12 801 blessures ne peuvent pas être requalifiés en information
connue avant match. Les ligues hors Ligue 1 sont disponibles uniquement pour
les diagnostics descriptifs équipe/calendrier et le benchmark marché
historique.

Verdict de couverture : `TEAM_FEATURES_PARTIAL_DESCRIPTIVE_ONLY`,
`PLAYER_FEATURES_BLOCKED`, `ABSENCE_FEATURES_BLOCKED`,
`LINEUP_FEATURES_BLOCKED`, `FORMATION_MATCHUPS_BLOCKED` et
`FOOTEDNESS_MATCHUPS_BLOCKED`.
