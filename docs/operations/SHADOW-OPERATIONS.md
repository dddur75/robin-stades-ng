# Opérations shadow

Statut : `SHADOW_COLLECTION_ACTIVE`
Paris réels : `PRODUCTION_LOCKED`

## Chaîne autonome

1. `collect-fixtures.yml` récupère événements, horaires et résultats courts ;
2. `collect-odds.yml` applique les fenêtres et le budget de crédits ;
3. `pre-match-shadow.yml` vérifie fraîcheur, calcule Elo/Poisson/consensus et
   journalise candidats comme rejets ;
4. `post-match-settlement.yml` récupère les scores et règle uniquement le shadow ;
5. `daily-health.yml` agrège couverture, fraîcheur, erreurs et motifs de rejet.

Chaque workflow est exécutable manuellement, sérialisé par la concurrence
globale `shadow-state`, idempotent et publie son état même en cas d’échec.
Le dernier artifact `shadow-state-<run_id>` est restauré explicitement avant
l’exécution suivante ; les payloads restent append-only et adressés par hash.

## Quotas

- plafond logiciel : 1 000 crédits/mois ;
- arrêt préventif avant la réserve de 4 000 crédits ;
- un snapshot groupé Ligue 1, région EU, `h2h+totals` coûte au plus 2 crédits ;
- les endpoints événements sans cote sont privilégiés pour éviter les appels
  inutiles ;
- un diagnostic hors fenêtre est limité à une fixture.

## États dégradés

| Situation | Comportement |
|---|---|
| clé absente | `READY_NO_KEY`, aucun appel, workflow non trompeur |
| quota 429 | reprises bornées, puis erreur explicite |
| serveur 5xx | reprises exponentielles bornées |
| réponse vide | `ABSENT`, pas `ERROR` |
| donnée périmée | décision `STALE_DATA` |
| identité incertaine | décision `QUALITY_BLOCKED` |
| cotes absentes | décision `MISSING_ODDS` |
| mode mock | badge `DEMO DATA`, aucune cote réelle simulée |

## Alertes

- `INFO` : fenêtre sans match ou réponse vide normale ;
- `WARNING` : fraîcheur insuffisante, couverture partielle, identité probable ;
- `CRITICAL` : quota épuisé, corruption de hash, fuite temporelle, secret exposé
  ou écriture non idempotente.

Une alerte critique doit bloquer la prédiction ou le règlement concerné.
