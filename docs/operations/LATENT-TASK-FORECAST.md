# Forecast des tâches latentes

## Pourquoi l’ancien chiffre était incomplet

Le forecast antérieur additionnait seulement `estimated_calls` sur les tâches
déjà présentes dans `backfill-plan.json`. Il comptait donc un parent
`fixtures/events`, `fixtures/statistics`, `fixtures/players` ou
`fixtures/lineups` comme un appel, alors que ce parent matérialise ensuite une
tâche par fixture canonique. Le même problème existait pour les dépendances par
équipe et les pages joueurs.

L’ETA historique est désormais séparée en deux périmètres :

- `MATERIALIZED_TASKS_ONLY` : travail déjà présent dans le plan ;
- `MATERIALIZED_PLUS_LATENT` : travail matérialisé et enfants futurs estimés.

Seul le second constitue le forecast complet.

## Registre versionné

`configs/historical_dependency_registry_v1.json` définit chaque endpoint :

- `FIXTURE_DEPENDENT` pour événements, statistiques, joueurs et compositions ;
- `TEAM_DEPENDENT` pour effectifs, statistiques équipe et entraîneurs ;
- `PAGINATED` pour joueurs et blessures ;
- `DIRECT` pour les endpoints qui ne développent pas d’enfants ;
- `UNAVAILABLE` uniquement après preuve d’indisponibilité.

Les cardinalités domestiques utilisent le format réel de la compétition :
306 fixtures pour 18 équipes, 380 pour 20 équipes. Les barrages Ligue 1 sont
exclus. La Ligue des champions utilise un profil multi-phase séparé.

## Scénarios

| Scénario | Cache | Cardinalité | Reprises | Finalité |
|---|---:|---|---:|---|
| bas | efficace | minimale vérifiée | aucune | plancher prudent |
| central | observé | format réel | normale | pilotage |
| haut | nul | couverture maximale | marge 10 % | capacité et pause |

La pagination joueurs repose d’abord sur les checkpoints observés : 39 à
46 pages, médiane 40. Le forecast converge lorsque les parents deviennent des
enfants : les appels passent du compartiment latent au compartiment
matérialisé, sans chute artificielle à zéro.

La projection de capacité utilise également la croissance physique observée
sur le lot `30154099512` : 14 292 000 octets pour 2 500 appels, soit
5 716,8 octets par appel. Cette observation sert de plancher afin que la
suppression des sources après compactage ne sous-estime pas le stockage futur.

## Garde-fous

- cible inchangée : 30 000 appels/jour ;
- réserve : 5 000 appels ;
- exécution toutes les deux heures ;
- alerte stockage : 750 MB ;
- pause stockage : 900 MB ;
- aucune hausse de cadence sans forecast complet, zéro HTTP 429, moins de 1 %
  d’erreurs, qualité temporelle verte et absence d’impact live.
