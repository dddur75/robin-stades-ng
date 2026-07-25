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
