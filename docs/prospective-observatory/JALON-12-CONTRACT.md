# Jalon 12 — contrat de l’Observatoire prospectif

Statut du contrat : `FROZEN_BEFORE_PROSPECTIVE_RESULTS`.

Politique machine canonique :
`configs/prospective_observatory_v1.json`. Elle porte ligues, horizons,
fenêtres, tolérance, budgets, réserves, stockage et invariants.

## Finalité

Le Jalon 12 construit la mémoire vérifiable de ce qui était réellement connu
avant chaque match. Il ne cherche ni une stratégie rentable, ni une sélection
de pari, ni une preuve rétrospective requalifiée en preuve live.

La chaîne autorisée est :

```text
fixture officielle
→ fenêtre préenregistrée
→ appel borné
→ payload brut R2 append-only
→ reçu compact
→ projection PostgreSQL
→ gate temporel
→ rapport compact
→ Robin Live
```

Le pilote est `P0 = Ligue 1`. Premier League, La Liga, Bundesliga et Serie A
restent `P1` jusqu’à ce que le pilote P0 soit vert.

## Invariants non négociables

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

- Git raw payload growth : `0`.
- Corps de payload dans PostgreSQL : `0`.
- Suppression R2 par un workflow normal : `0`.
- Décision de pari dans le Public Evidence Ledger V3 : `0`.
- Réseau social connecté : `0`.

## Périmètre de données

Les neuf familles sont `FIXTURE`, `TEAM`, `SQUAD`, `PLAYER_STATUS`, `INJURY`,
`LINEUP`, `FORMATION`, `ODDS` et `EVENT_STATUS`.

Chaque observation possède des temps distincts : `event_time`,
`provider_updated_at`, `requested_at`, `response_received_at`, `observed_at`,
`kickoff_at` et `materialized_at`. La preuve d’admissibilité est :

```text
opens_at <= response_received_at < cutoff_at < kickoff_at
```

Les reçus `REGISTRY` sans fenêtre n’ont pas d’ouverture et conservent
`response_received_at < cutoff_at < kickoff_at`. Une règle plus stricte peut
être gelée avant la capture. Elle ne peut pas être assouplie après observation.

## États autorisés

Une fixture × famille × fenêtre prend exactement l’un des états :

```text
NOT_DUE
DUE
CAPTURED
CAPTURED_EMPTY
PROVIDER_UNAVAILABLE
MISSED_WINDOW
INVALID_PAYLOAD
TEMPORALITY_FAILED
IDENTITY_FAILED
RETRY_PENDING
COMPLETE
```

`CAPTURED_EMPTY` prouve une réponse vide observée. Cet état n’est admissible
que pour `PLAYER_STATUS`, `INJURY`, `LINEUP` et `FORMATION` ; un `SQUAD` vide
reste invalide. Il n’est ni remplacé par zéro, ni confondu avec un appel
absent. `MISSED_WINDOW` est définitif pour le cutoff concerné.

Pour `INJURY`, un vide admissible peut satisfaire le gate avec
`NO_INJURY_REPORTED_AT_CAPTURE`, soit aucune blessure publiée par ce fournisseur
à cet instant. Il ne prouve pas l’absence médicale. Pour les captures
API-Football prospectives, seul le statut fixture exact `NS` est admissible ;
tout autre statut est `REGISTRY_STALE`.

## Échantillons préenregistrés

| Usage | Minimum |
|---|---:|
| Audit technique | 1 fixture complète |
| Validation pipeline | 5 fixtures, 2 journées, 2 fenêtres par famille critique |
| Première analyse descriptive | 30 occurrences pertinentes |
| Recherche exploratoire | 80 occurrences, plusieurs équipes et journées |
| Promotion shadow | gates Jalon 11 + période prospective suffisante |

Les protocoles H11-001 à H11-008 sont gelés. Avant leur minimum, leur statut
reste `WAITING_FOR_OBSERVATIONS`, `DATA_CAPTURE_ACTIVE` ou
`MINIMUM_SAMPLE_NOT_REACHED`. `ELIGIBLE_FOR_EXPLORATORY_ANALYSIS` n’est ni un
signal, ni une validation, ni une promotion.

## Budget initial

```text
MAX_API_FOOTBALL_CALLS_TOTAL=5000
MAX_ODDS_API_CREDITS_TOTAL=250
ODDS_API_INTERNAL_SAFETY_RESERVE=2
API_FOOTBALL_PROVIDER_RESERVE=5000
ODDS_API_PROVIDER_RESERVE=4000
ODDS_NEAR_KICKOFF_RESERVE=80
```

Les deux premiers plafonds bornent tout le pilote Jalon 12. Les trois réserves
protègent les opérations déjà existantes et les fenêtres critiques. Un budget
insuffisant réduit le périmètre à la Ligue 1 ; il n’autorise aucun dépassement.

## Sources de vérité

1. R2 conserve le payload brut immuable et son reçu.
2. PostgreSQL indexe les fixtures, fenêtres, tentatives, reçus et projections.
3. Les rapports compacts résument des objets vérifiés.
4. Robin Live affiche ces rapports sans accéder à R2 ou Neon depuis le
   navigateur.
5. Git conserve code, migrations, contrats, hashes, tests et rapports compacts.

Un statut GitHub `SUCCESS` sans progression ni preuve de fenêtre n’est pas une
capture réussie.

## Non-objectifs

- aucun nouveau marché joueur ;
- aucun nouveau modèle ;
- aucune décision ou mise, même fictive, issue du Jalon 12 ;
- aucun backfill historique avec les budgets prospectifs ;
- aucune reconstruction post-kickoff d’une fenêtre manquée ;
- aucune donnée historique post-match présentée comme point-in-time.

## Critère de sortie

L’implémentation est déclarable prête uniquement après tests, migration,
capture réelle de fenêtres effectivement dues, projection, replay R2 sans
fournisseur, gates, rapports compacts et CI verte. L’absence de lineup,
blessure ou cote quand sa fenêtre n’est pas due est un résultat correct.
