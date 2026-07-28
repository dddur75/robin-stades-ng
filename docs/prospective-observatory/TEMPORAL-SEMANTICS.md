# Sémantique temporelle prospective

## Principe

La disponibilité d’une donnée est prouvée par sa réception, pas par la date
qu’elle décrit ni par la date de matérialisation.

```text
opens_at <= response_received_at < cutoff_at < kickoff_at
```

`observed_at` est le temps d’observation retenu par le contrat. Il ne remplace
jamais `response_received_at`.

Les reçus `REGISTRY`, qui ne représentent pas une fenêtre planifiée, n’ont pas
de `opens_at` et conservent la règle
`response_received_at < cutoff_at < kickoff_at`.

La politique de fenêtre canonique est versionnée dans
`configs/prospective_observatory_v1.json`.

La version active est `prospective-capture-window-v2`. Elle applique l’Option B
aux observations proches du kickoff :

```text
H-2          = [H-3, H-1)
NEAR_KICKOFF = [H-1, kickoff)
```

Ces intervalles sont adjacents et non chevauchants. Les libellés v1 H-1,
H-0:45, H-0:30 et H-0:15 restent dans l’historique append-only, mais ne sont
pas des fenêtres actives v2.

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
| `physical_capture_id` | SHA-256 de la réponse : fixture-scoped pour API-Football, global pour `/sports/.../odds` |

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
- une réponse mutualisée peut produire plusieurs reçus sémantiques. Le ledger
  la compte une fois physiquement, puis au plus une preuve temporelle par
  `physical_capture_id × fixture`; les familles restent des alias techniques.
- API-Football inclut la fixture dans l’identité physique. La réponse Odds
  globale la neutralise, de sorte qu’un transport couvrant plusieurs fixtures
  conserve un seul `physical_capture_id`.

## Fenêtre manquée et retry tardif

Après `cutoff_at`, une absence de capture devient `MISSED_WINDOW`. Aucun appel
post-kickoff ne peut la convertir en capture admissible. Un retry technique
hors fenêtre porte `LATE_RETRY` et reste exclu du cutoff initial.

`CAPTURED_EMPTY` signifie que le fournisseur a répondu sans donnée dans la
fenêtre. Il conserve son reçu et ne devient jamais un zéro analytique.

Pour `INJURY`, un vide admissible avant cutoff est une preuve négative bornée :
`NO_INJURY_REPORTED_AT_CAPTURE` /
`NO_PROVIDER_REPORTED_INJURY_AT_CAPTURE_TIME`. Il peut faire passer le gate
blessure, mais signifie seulement qu’aucune blessure n’était publiée par ce
fournisseur à cet instant. Il ne prouve ni l’absence médicale réelle, ni une
valeur analytique égale à zéro. Pour lineup/formation, un vide reste une preuve
de réponse avant publication et ne satisfait pas la couverture attendue.

Quand une fenêtre player ou lineup est réellement due, un preflight borné
relit la fixture officielle avant la capture. Le kickoff, l’identité et le
statut doivent encore correspondre à la version de registre. Ce preflight
n’existe pas en l’absence de fenêtre due. Une correction de kickoff produit
une nouvelle version de registre et de nouvelles fenêtres ; elle ne réhabilite
jamais les anciennes.

API-Football n’admet que le statut exact `NS` pour une capture prospective.
Tout autre statut devient `REGISTRY_STALE`. Après la sélection due, l’horloge
est relue avant le preflight, avant chaque transport profond et après la
réponse. Le replay recalcule aussi `opens_at` depuis la politique versionnée :
une réponse avant ouverture n’est pas admissible ; une réponse reçue au cutoff
ou après celui-ci porte `TEMPORALITY_FAILED`.

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

Chaque gate conserve fixture, famille, fenêtre, ouverture, cutoff, temps de réponse,
résultat, raisons, `physical_capture_id`, hash du reçu et révision de code.
Sa couverture est calculée avec les identités physiques distinctes dans le
périmètre du gate, pas sur le nombre de reçus techniques. Les agrégats du
cockpit ne remplacent jamais l’audit au grain fixture.

Un passage sans fenêtre due est un état temporel positif et explicite :
`NO_DUE_WINDOW_SUCCESS`. Il implique zéro appel fournisseur, zéro crédit Odds,
zéro `r2_puts` de capture et zéro tentative ; migration, estimation, rapport et
réparation provider-free d’une intention antérieure peuvent néanmoins
s’exécuter. Ces dernières écritures sont isolées dans `recovery_r2_puts`.
