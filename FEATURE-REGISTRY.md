# Registre des features

## Jalon 5.1 — verrou joueurs

Toutes les features joueurs restent `BLOCKED_BY_COVERAGE`. Une saison pilote
ne satisfait pas les seuils multi-saisons, identité, cardinalité et
point-in-time. Aucun modèle joueur n’est entraîné. `team_baseline_v1` demeure
`LEGACY SOURCE`, et Elo V1 demeure `LEGACY/OOS HISTORICAL`.

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

## Jalon 5.2 — métriques de readiness

Chaque famille joueurs publie désormais séparément :

- compétitions, saisons, équipes, fixtures et joueurs couverts ;
- taux de null ;
- identités ;
- qualité ;
- temporalité ;
- statut et raison du blocage.

`Joueurs` peut être `COMPUTABLE` comme dimension sans rendre un modèle joueurs
prêt. Minutes, statistiques par match, compositions, formations, continuité,
forces du onze et du banc, fatigue, blessures, disponibilité et retour de
blessure conservent leurs propres verrous. Aucun zéro n’est substitué à une
valeur manquante.

### Mesure après le lot `30154099512`

- `Joueurs` : 5 saisons, 32 équipes, 2 039 joueurs, 4 132 lignes, null 0 %,
  `COMPUTABLE` comme dimension uniquement ;
- `Minutes` et `Statistiques joueurs par match` : 3 saisons, 1 285 joueurs,
  1 846 lignes, `TESTING` avec contrôle as-of encore requis ;
- `Compositions`, `Formations` et `Continuité du onze` : 3 saisons,
  1 286 joueurs, 1 850 lignes, `TESTING` ;
- `Blessures` : 5 saisons, 1 638 fixtures, 1 210 joueurs, mais
  `BLOCKED_BY_TEMPORALITY` ;
- `Disponibilité` et `Retour de blessure` :
  `BLOCKED_BY_TEMPORALITY` ;
- `Effectifs` et `Force du banc` : une seule saison commune,
  `BLOCKED_BY_COVERAGE` ;
- `Force du onze` et `Fatigue` : `TESTING`, jamais promues en modèle.

Le statut global reste `BLOCKED_BY_COVERAGE`. Aucun modèle joueurs n’est
entraîné ni présenté comme prêt.

## Jalon 6

- `api_team_pre_match_v1` : `API_TEAM_DATASET_READY`.
- charge, forme, contributions et rôle joueurs :
  `PLAYER_FEATURE_FACTORY_ACTIVE`.
- onze attendu : `API_PLAYER_DATASET_READY`.
- onze confirmé historique : `POST_LINEUP_SIMULATED_READY`.
- blessures, disponibilité et retour de blessure :
  `BLOCKED_BY_TEMPORALITY`.

Les features du match cible sont interdites. Les nulls restent nulls et chaque
score joueur expose son support en minutes et son incertitude.

## Jalon 7 — ablations

Les groupes `TEAM_FORM`, `PLAYER_PRE_LINEUP`, `CONFIRMED_LINEUP` et `MARKET`
sont préenregistrés pour retrait unitaire. Chaque ablation garde exactement les
mêmes fixtures et cutoffs. Une importance instable entre saisons ou ligues est
marquée `INCONCLUSIVE`; elle ne débloque pas de feature.
## Jalon 8 — généralisation

| Bloc | Portée externe | Statut |
|---|---|---|
| Team pré-match V1 | PL, Liga, Bundesliga | `EXTERNAL_DATASET_READY` |
| Team pré-match V1 | Serie A, UCL | `BLOCKED_BY_COVERAGE` |
| Player pré-lineup | cinq ligues | `PLAYER_GENERALIZATION_INCONCLUSIVE` |
| Post-lineup simulé | cinq ligues | `BLOCKED_BY_COVERAGE` |
| Blessures | cinq ligues | `BLOCKED_BY_TEMPORALITY` |

Aucune cible, donnée future ou valeur manquante convertie en zéro n’est
autorisée.

## Gates externes Jalon 9

Les features joueur ne sont calculables qu’après PLAYER_GATE par ligue; les
features composition conservent `PRE_LINEUP` et `POST_LINEUP_SIMULATED`
séparés. Les blessures restent `BLOCKED_BY_TEMPORALITY`.
