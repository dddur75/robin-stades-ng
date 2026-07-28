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

## Jalon 10 — disponibilité pour les patterns

| Famille | Usage recherche | Gate |
|---|---|---|
| Résultat du match cible | interdit | `POST_MATCH_ONLY` |
| Forme/ratings roulants antérieurs | admissible si fenêtre exclut la cible | `POINT_IN_TIME_TEST_REQUIRED` |
| Repos/calendrier antérieur | admissible | `POINT_IN_TIME_TEST_REQUIRED` |
| Cotes 1X2 / O-U 2,5 | historique exposé uniquement | `SOURCE_PRICE_CLASS_ONLY` |
| Mouvement de cote | non calculable sans snapshots multiples datés | `MARKET_UNAVAILABLE` |
| Joueurs pré-lineup | non forcé dans V1 | gates Jalon 9 conservés |
| Composition confirmée | simulation historique seulement | `POST_LINEUP_SIMULATED` |
| Blessures/disponibilité | exclu | `BLOCKED_BY_TEMPORALITY` |
| Formations | exclu sans preuve de disponibilité | `POINT_IN_TIME_GATE` |
| Latéralité/pied fort | exclu | `FOOTEDNESS_DATA_GATE` |

Les noms `winner_*`/`loser_*`, scores, statistiques du match cible et cotes
futures produisent `LEAKAGE_REJECTED`. Une valeur manquante reste `null`.

Les concentrations équipe et bookmaker doivent être rapportées avant toute
promotion. La sensibilité bookmaker n’est pas démontrable à partir du seul prix
moyen actuel et échoue fermée.

## Jalon 11 — Feature Contract V2

| Famille | Dataset | Cutoff | Statut |
|---|---|---|---|
| Elo, forme 5/10, buts 5, repos | `TEAM_PREMATCH` v2 | target exclu avant update, frontière = kickoff | `TEAM_FEATURES_PARTIAL_DESCRIPTIVE_ONLY` |
| forme joueur par apparitions | `PLAYER_PRELINEUP` | pré-lineup | `PLAYER_FEATURES_BLOCKED` |
| titulaire/central/gardien habituel | joueur/lineup | antérieur au match cible | `BLOCKED_BY_TEMPORALITY` |
| absences et spine disruption | joueur/équipe | annonce pré-match | `ABSENCE_FEATURES_BLOCKED` |
| continuité et duo central | `POST_LINEUP` | annonce officielle avant kickoff | `LINEUP_FEATURES_BLOCKED` |
| formation et interactions | `FORMATION_MATCHUP` | post-lineup avant kickoff | `FORMATION_MATCHUPS_BLOCKED` |
| pied fort | `FOOTEDNESS_MATCHUP` | valeur sourcée | `FOOTEDNESS_MATCHUPS_BLOCKED` |

`TEAM_PREMATCH` compte 10 732 lignes et porte le hash
`2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6`.
Les features manquantes restent nulles ; les indicateurs de missingness sont
séparés et les imputations sont apprises sur chaque train.

Le target est exclu de ses propres agrégats, mais la temporalité
`source_observed_at` n'est pas prouvée ligne par ligne. Le dataset n'est ni
promotion-ready ni live-ready.

Les seuils joueurs sont gelés : 2 buts/3 apparitions, 3 buts/5 apparitions,
4 implications/5 apparitions et 180 minutes/3 apparitions. Ils ne sont pas
exécutés tant que `PLAYER_FORM_GATE` n'est pas prêt.

Preuve opérationnelle : le run `30282406035`, source
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`, a persisté sous
Alembic `0008_jalon11_deep_football` le contrat compact de 11 définitions et
270 gates. Les deux passages ont inséré 0 objet et évité les mêmes doublons ;
le Parquet hashé est vérifié dans R2 avec lag nul. Aucun gate profond n'a été
ouvert par cette validation d'infrastructure.

## Jalon 12 — features prospectives

| Famille | Données requises | Gate | Statut initial |
|---|---|---|---|
| forme joueur, minutes 3/5 | PLAYER_STATUS antérieur | `PROSPECTIVE_PLAYER_GATE` | `WAITING_FOR_OBSERVATIONS` |
| titulaire/gardien/centraux habituels | PLAYER_STATUS + LINEUP | player + lineup | `WAITING_FOR_OBSERVATIONS` |
| absences et deux centraux absents | INJURY + identités | `PROSPECTIVE_INJURY_GATE` | `WAITING_FOR_OBSERVATIONS` |
| continuité et nouveau duo central | LINEUP | `PROSPECTIVE_LINEUP_GATE` | `WAITING_FOR_OBSERVATIONS` |
| formation et changement | LINEUP + FORMATION | `PROSPECTIVE_FORMATION_GATE` | `WAITING_FOR_OBSERVATIONS` |
| repos et congestion | fixtures antérieures | gate temporel | `WAITING_FOR_OBSERVATIONS` |
| prix à chaque fenêtre | ODDS, bookmaker, marge, observed_at | `PROSPECTIVE_MARKET_GATE` | `WAITING_FOR_OBSERVATIONS` |
| pied fort | source observée dédiée | non disponible | `BLOCKED_BY_TEMPORALITY` |

Les nulls restent nulls. `CAPTURED_EMPTY` ne devient pas zéro. Aucune feature
ne produit une décision dans le Jalon 12.
