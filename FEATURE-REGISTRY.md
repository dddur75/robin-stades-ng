# Registre des features

## Jalon 5 — Feature Factory V1

| Feature | Version | Disponibilité | Statut | Risque de fuite |
|---|---:|---|---|---|
| Elo global / domicile / extérieur | v1 | avant match | `COMPUTABLE` | faible |
| Forme 5 / 10 / 20 | v1 | matchs antérieurs | `COMPUTABLE` | faible |
| Buts marqués / encaissés glissants | v1 | matchs antérieurs | `COMPUTABLE` | faible |
| Jours de repos / congestion | v1 | calendrier antérieur | `COMPUTABLE` | faible |
| Minutes joueurs 5 / 10 / 30 jours | v1 | statistiques antérieures | `BLOCKED_BY_COVERAGE` | moyen |
| Disponibilité / retour de blessure | v1 | source datée fiable | `BLOCKED_BY_COVERAGE` | élevé |
| Continuité et force du onze | v1 | mode `PRE_LINEUP` | `BLOCKED_BY_COVERAGE` | élevé |
| Composition officielle historique | v1 | `POST_LINEUP_SIMULATED` | `TESTING` | critique |

Les features d’équipe de `team_baseline_v1` sont calculées avant la mise à jour
du match cible. Une valeur absente reste `null`. Les blessures non point-in-time
et la composition officielle du match cible sont exclues du mode `PRE_LINEUP`.

