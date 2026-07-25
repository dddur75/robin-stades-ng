# Readiness des features joueurs

Statut global : `BLOCKED_BY_COVERAGE`.

| Feature | Couverture | Qualité | Temporalité | Statut |
|---|---:|---:|---:|---|
| Minutes joueurs | une saison pilote | partielle | multi-saisons absentes | `BLOCKED_BY_COVERAGE` |
| Forme joueurs | une saison pilote | partielle | fenêtres à valider | `BLOCKED_BY_COVERAGE` |
| Force du onze | une saison pilote | partielle | compositions pré-match incomplètes | `BLOCKED_BY_COVERAGE` |
| Disponibilité | une saison pilote | partielle | snapshots historiques à confirmer | `BLOCKED_BY_COVERAGE` |
| Blessures | une saison pilote | hétérogène | point-in-time à étendre | `BLOCKED_BY_COVERAGE` |
| Continuité | une saison pilote | partielle | plusieurs saisons requises | `BLOCKED_BY_COVERAGE` |

Les identités, cardinalités, temporalités et plusieurs saisons exploitables
doivent toutes passer avant un entraînement joueur. `team_baseline_v1` reste
`LEGACY SOURCE`; Elo V1 reste `LEGACY/OOS HISTORICAL`; le ROI de -8,55 % reste
`REJECTED`.

## Mesure post-fusion

- dimension joueurs : 5 saisons et 4 132 lignes, `COMPUTABLE` comme dimension
  seulement ;
- statistiques joueurs par match et minutes : une saison, donc
  `BLOCKED_BY_COVERAGE` ;
- compositions, continuité, formations, force du banc et force du onze : une
  saison commune, donc `BLOCKED_BY_COVERAGE` ;
- blessures : 5 saisons mais source historique non point-in-time, donc
  `BLOCKED_BY_TEMPORALITY` ;
- disponibilité et retour de blessure : `BLOCKED_BY_TEMPORALITY` ;
- fatigue : `BLOCKED_BY_COVERAGE`.

Ces statuts ne débloquent aucun modèle joueurs. Les valeurs manquantes restent
nulles et ne sont jamais converties en zéro.

## Mesure Jalon 5.2 après qualité

| Famille | Comp. | Saisons | Équipes | Fixtures | Joueurs | Lignes | Null | Temporalité | Statut |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Effectifs | 1 | 1 | 21 | 0 | 0 | 21 | 7,14 % | point-in-time | `BLOCKED_BY_COVERAGE` |
| Joueurs | 1 | 5 | 32 | 0 | 2 039 | 4 132 | 0 % | point-in-time | `COMPUTABLE` |
| Minutes | 1 | 3 | 24 | 923 | 1 285 | 1 846 | 7,14 % | lag post-match requis | `TESTING` |
| Statistiques joueurs/match | 1 | 3 | 24 | 923 | 1 285 | 1 846 | 7,14 % | lag post-match requis | `TESTING` |
| Compositions | 1 | 3 | 24 | 925 | 1 286 | 1 850 | 7,14 % | lag post-match requis | `TESTING` |
| Formations | 1 | 3 | 24 | 925 | 1 286 | 1 850 | 7,14 % | lag post-match requis | `TESTING` |
| Continuité du onze | 1 | 3 | 24 | 925 | 1 286 | 1 850 | 7,14 % | lag post-match requis | `TESTING` |
| Force du onze | 1 | 3 | 24 | 922 | 1 280 | 1 846 | 7,14 % | lag post-match requis | `TESTING` |
| Force du banc | 1 | 1 | 21 | 925 | 1 286 | 21 | 7,14 % | lag post-match requis | `BLOCKED_BY_COVERAGE` |
| Blessures | 1 | 5 | 27 | 1 638 | 1 210 | 12 801 | 7,14 % | non point-in-time | `BLOCKED_BY_TEMPORALITY` |
| Disponibilité | 1 | 3 | 24 | 915 | 858 | 1 850 | 7,14 % | non point-in-time | `BLOCKED_BY_TEMPORALITY` |
| Fatigue | 1 | 3 | 24 | 922 | 1 280 | 1 846 | 7,14 % | lag post-match requis | `TESTING` |
| Retour de blessure | 1 | 3 | 24 | 913 | 859 | 1 846 | 7,14 % | non point-in-time | `BLOCKED_BY_TEMPORALITY` |

La qualité et les identités sont `PASSED`/`VERIFIED` pour les treize familles.
`COMPUTABLE` pour la dimension joueurs ne signifie pas `PLAYER_MODEL_READY`.
Les features `TESTING` exigent encore une validation as-of par match ; les
blessures historiques ne peuvent pas devenir point-in-time par imputation.
