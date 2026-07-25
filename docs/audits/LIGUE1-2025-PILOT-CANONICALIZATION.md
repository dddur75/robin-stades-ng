# Canonicalisation du pilote Ligue 1 2025

Statut : `PASSED`.

L’API-Football retourne 310 fixtures parce que son périmètre `league=61,
season=2025` agrège la phase régulière et le barrage de relégation. Les 306
fixtures `Regular Season - 1` à `Regular Season - 34` forment le dataset
canonique `ligue1_2025_regular_season` : 34 journées, neuf matchs par journée
et 18 clubs.

Les quatre lignes conservées mais exclues sont :

| Fixture | Date UTC | Affiche | Tour fournisseur | Classe |
|---:|---|---|---|---|
| 1544684 | 2026-05-12 18:30 | Red Star — Rodez | Relegation round - Quarter-finals | `RELEGATION_PLAYOFF` |
| 1544972 | 2026-05-15 18:30 | Saint-Étienne — Rodez | Semi-finals | `RELEGATION_PLAYOFF` |
| 1545408 | 2026-05-26 18:45 | Saint-Étienne — Nice | Final | `RELEGATION_PLAYOFF` |
| 1545409 | 2026-05-29 18:45 | Nice — Saint-Étienne | Final | `RELEGATION_PLAYOFF` |

Les 21 équipes reçues sont les 18 clubs de phase régulière plus Red Star
(104), Rodez (1301) et Saint-Étienne (1063), présents uniquement dans le
barrage. Nice appartient à la phase régulière et au barrage. Il ne s’agit ni
de doublons ni de reports : les quatre fixtures sont légitimes, hors périmètre
du modèle de saison régulière.

Chaque observation conserve l’identifiant fournisseur et interne, les équipes,
le tour, la phase, le statut, le coup d’envoi, la dernière observation, la
compétition, la saison, la classe et la raison d’exclusion. Le hash du dataset
canonique audité est
`e876d705d4272163a6499464f3ea220853654e3a3714de28d8c2da7617a633c0`.

Le contrôle est générique : `n × (n - 1) × legs / 2`, paramétré par saison et
phase dans `config/competition-formats.json`. Les tests couvrent notamment les
formats à 18 et 20 clubs, reports, annulations, doublons, changements
d’identifiant, playoffs et équipes hors phase. La Feature Factory s’arrête si
la cardinalité déclarée n’est pas satisfaite.
