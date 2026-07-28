# Politique de retry et de fenêtre manquée

## Objectif

Récupérer d’une panne technique sans fabriquer après coup une disponibilité
pré-match qui n’a jamais existé.

## Catégories

| Cas | État | Retry |
|---|---|---|
| timeout ou 5xx dans la fenêtre | `RETRY_PENDING` | borné avec backoff |
| HTTP 429 | `PROVIDER_UNAVAILABLE` | circuit breaker, pas de boucle |
| réponse 2xx vide admissible pour player-status/injury/lineup/formation | `CAPTURED_EMPTY` | non |
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
`cancel-in-progress=false` conserve le run actif.

## Limites temporelles

Une tentative ne démarre pas après le cutoff si son objet est de fermer la
fenêtre initiale. Après kickoff :

- aucun appel ne peut convertir `MISSED_WINDOW` en `CAPTURED` ;
- une donnée diagnostique reste `LATE_RETRY` ;
- la projection conserve le temps réel de réception ;
- le gate initial reste fermé.

Les bornes canoniques Option B sont `H-2=[H-3,H-1)` et
`NEAR_KICKOFF=[H-1,kickoff)`. Un retry commencé après H-1 ne peut donc pas
acquitter `H-2`, même si `NEAR_KICKOFF` est encore ouverte. Une capture
post-kickoff reste inadmissible dans tous les cas.

Le choix `DUE` n’est pas une autorisation durable : l’horloge est relue avant
le preflight de fraîcheur, avant chaque appel profond et à la réception. Si le
lot franchit le cutoff avant le transport, il enregistre
`WINDOW_CUTOFF_PASSED_BEFORE_PROVIDER_CALL` sans unité fournisseur. Si la
réponse franchit le cutoff, elle est conservée pour audit avec
`TEMPORALITY_FAILED` et ne ferme pas le gate.

## Preuve d’absence

Une réponse vide reçue et hashée est une observation. Une panne, une requête
non exécutée et une fenêtre non due sont trois états différents. Aucun de ces
cas ne devient un zéro de feature.

## Reprise

La reprise part des objets immuables R2 et réconcilie ensuite PostgreSQL. Elle
n’appelle un fournisseur que si la fenêtre est encore ouverte, le budget vert
et le circuit fermé. Sinon elle publie l’état final sans perte silencieuse.

Avant toute sélection de fenêtre due, l’état R2 est réconcilié vers
PostgreSQL : reçus, index, projections, tentatives compactes et journal de
budget. La parité est ensuite vérifiée dans les deux sens : aucun reçu ou index
PostgreSQL sans objet R2 correspondant, et aucun reçu R2 absent de PostgreSQL.
Une divergence ferme l’exécution avec un code
`R2_POSTGRESQL_*_PARITY_FAILED`; elle ne déclenche pas un appel fournisseur.

La parité de projection compare l’ensemble exact des lignes, y compris les
lignes supplémentaires, manquantes ou mutées, dans :

```text
prospective_player_status
prospective_injuries
prospective_lineups
prospective_formations
prospective_odds_snapshots
```

Le journal budget legacy est amorcé de façon idempotente ligne par ligne.
Même si R2 contient déjà une partie du journal, les clés SQL manquantes sont
complétées dans R2 ; les enregistrements R2 sont ensuite reprojetés en SQL et
tous les champs doivent être identiques. Un conflit append-only ou une parité
partielle bloque le run.

## Interruption et reprise sans fournisseur

Le write-ahead append-only couvre les sept points d’arrêt suivants :

1. intention écrite, payload final absent : le payload et le reçu exacts sont
   rematérialisés depuis l’intention ;
2. payload final écrit, reçu absent : le reçu canonique est rematérialisé ;
3. payload et reçu écrits, PostgreSQL absent : la base est reconstruite depuis
   R2 ;
4. PostgreSQL partiellement projeté : les upserts idempotents complètent les
   lignes manquantes ;
5. timeout après index : la parité R2/PostgreSQL classe les écritures déjà
   acquises et rejoue seulement le delta ;
6. replay complet : `R2_REPLAY_VERIFIED` si toutes les fixtures attendues sont
   reconstruites ;
7. replay répété : zéro nouvel appel, zéro nouvelle ligne métier et doublons
   évités explicitement comptés.

Le statut PostgreSQL exact d’un replay complet est
`CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2`. Si les index de
fixtures attendus ne sont pas complets, les statuts sont
`RECONSTRUCTION_INCOMPLETE` et `R2_REPLAY_PARTIAL_FIXTURE_INDEX` : aucun succès
partiel n’est présenté comme une reconstruction complète.
