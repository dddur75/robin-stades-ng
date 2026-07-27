# Sémantique temporelle prospective

## Principe

La disponibilité d’une donnée est prouvée par sa réception, pas par la date
qu’elle décrit ni par la date de matérialisation.

```text
response_received_at < cutoff_at < kickoff_at
```

`observed_at` est le temps d’observation retenu par le contrat. Il ne remplace
jamais `response_received_at`.

La politique de fenêtre canonique est versionnée dans
`configs/prospective_observatory_v1.json`.

## Définitions

| Champ | Définition |
|---|---|
| `event_time` | temps de l’événement football décrit |
| `provider_updated_at` | temps annoncé par le fournisseur, si disponible |
| `requested_at` | départ de la requête |
| `response_received_at` | réception complète de la réponse |
| `observed_at` | instant contractuel de l’observation stockée |
| `cutoff_at` | borne d’admissibilité gelée pour la fenêtre |
| `kickoff_at` | kickoff officiel UTC vérifié |
| `materialized_at` | création d’une projection ou feature |

Tous les champs sont UTC et timezone-aware. Un timestamp naïf ou incohérent
produit `TEMPORALITY_FAILED`.

## Règles d’ordre

- `requested_at <= response_received_at`.
- `response_received_at <= observed_at` si `observed_at` représente la fin de
  capture ; toute autre convention doit être explicite.
- `cutoff_at < kickoff_at`.
- la matérialisation peut être postérieure au kickoff sans rendre la donnée
  admissible ; seule la réception avant cutoff le permet.
- un temps fournisseur futur ou contradictoire est conservé pour audit mais
  bloque le gate concerné.

## Fenêtre manquée et retry tardif

Après `cutoff_at`, une absence de capture devient `MISSED_WINDOW`. Aucun appel
post-kickoff ne peut la convertir en capture admissible. Un retry technique
hors fenêtre porte `LATE_RETRY` et reste exclu du cutoff initial.

`CAPTURED_EMPTY` signifie que le fournisseur a répondu sans donnée dans la
fenêtre. Il conserve son reçu et ne devient jamais un zéro analytique.

## Historique sémantique

| Catégorie | Statut |
|---|---|
| Fait d’un match source antérieur avec délai de sécurité | `HISTORICAL_EVENT_TIME_USABLE` |
| Lineup du match cible récupéré après coup | `HISTORICAL_SEMANTIC_POST_LINEUP_EXPOSED` |
| Blessure du match cible récupérée après coup | `BLOCKED_BY_TEMPORALITY` |
| Pied fort sans source observée | `BLOCKED_BY_TEMPORALITY` |

Le match cible est toujours exclu des agrégats qui prétendent décrire l’état
pré-match.

## Cutoffs par usage

- les features pré-lineup utilisent uniquement les captures reçues avant leur
  cutoff préenregistré ;
- les features post-lineup nécessitent une lineup officielle reçue avant
  kickoff ;
- une cote est liée à son `observed_at` exact, son bookmaker et sa fenêtre ;
- un changement de formation n’est calculé que si les deux formations ont une
  provenance admissible ;
- les nulls restent nulls.

## Audit

Chaque gate conserve fixture, famille, fenêtre, cutoff, temps de réponse,
résultat, raisons, hash du reçu et révision de code. Les agrégats du cockpit ne
remplacent jamais l’audit au grain fixture.
