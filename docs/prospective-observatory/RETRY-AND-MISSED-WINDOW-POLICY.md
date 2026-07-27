# Politique de retry et de fenêtre manquée

## Objectif

Récupérer d’une panne technique sans fabriquer après coup une disponibilité
pré-match qui n’a jamais existé.

## Catégories

| Cas | État | Retry |
|---|---|---|
| timeout ou 5xx dans la fenêtre | `RETRY_PENDING` | borné avec backoff |
| HTTP 429 | `PROVIDER_UNAVAILABLE` | circuit breaker, pas de boucle |
| réponse 2xx vide valide | `CAPTURED_EMPTY` | non |
| JSON invalide | `INVALID_PAYLOAD` | borné si fenêtre ouverte |
| identité ambiguë | `IDENTITY_FAILED` | après correction de registre, dans la fenêtre |
| cutoff dépassé | `MISSED_WINDOW` | jamais pour simuler la fenêtre |
| retry technique tardif autorisé pour diagnostic | `LATE_RETRY` | exclu du gate initial |

## Backoff

Le nombre de tentatives est borné et persistant. Le délai croît entre les
tentatives et tient compte de `Retry-After` sans exposer les headers. Un
circuit breaker fournisseur bloque les nouvelles tentatives après un seuil
d’erreurs ou HTTP 429.

Une exécution GitHub plus récente ne doit pas annuler une capture active sans
politique explicite. Le groupe `prospective-deep-state` sérialise les écritures.

## Limites temporelles

Une tentative ne démarre pas après le cutoff si son objet est de fermer la
fenêtre initiale. Après kickoff :

- aucun appel ne peut convertir `MISSED_WINDOW` en `CAPTURED` ;
- une donnée diagnostique reste `LATE_RETRY` ;
- la projection conserve le temps réel de réception ;
- le gate initial reste fermé.

## Preuve d’absence

Une réponse vide reçue et hashée est une observation. Une panne, une requête
non exécutée et une fenêtre non due sont trois états différents. Aucun de ces
cas ne devient un zéro de feature.

## Reprise

La reprise part des tentatives et reçus PostgreSQL, puis vérifie R2. Elle
n’appelle un fournisseur que si la fenêtre est encore ouverte, le budget vert
et le circuit fermé. Sinon elle publie l’état final sans perte silencieuse.
