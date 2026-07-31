# Historical Deep Data Harvest V1

## But

Cette lane récupère et rejoue les données historiques profondes d’API-Football
pour la Ligue 1, la Premier League, la Liga, la Bundesliga et la Serie A. Elle
traite d’abord 2020–2025, puis 2018–2019 et enfin les saisons antérieures dont
la couverture est réellement vérifiée.

La lane est indépendante du pipeline historique legacy. R2 est la source
primaire des payloads et des reçus ; Git ne reçoit que le code, les contrats et
des rapports compacts sanitisés.

## Invariants de sécurité

- `STORAGE_PAUSED=true`
- `P3_P4_PAUSED=true`
- `PRODUCTION_LOCKED=true`
- `REAL_BETS=false`
- `NO_BET_DEFAULT=true`
- `PROMOTION_LOCKED=true`
- `SOCIAL_PUBLISHING_ENABLED=false`
- `DEMO_MODE_ENABLED=false`
- aucune suppression R2 ;
- aucune écriture destructive PostgreSQL ;
- aucun payload brut dans Git ou dans un artefact Actions ;
- aucun crédit historique The Odds API.

Le collecteur refuse l’exécution lorsque ces verrous ne sont pas présents avec
leur valeur exacte.

## Quota

Le workflow 70 appelle `/status`, exige un plan `Mega` actif et conserve
uniquement les champs sanitisés du contrat. Le budget de mission est recalculé
depuis le statut et les headers :

```text
mandatory_reserve = max(20 000, 20 % de daily_limit)
mission_available = daily_remaining - mandatory_reserve
continuation_available = min(daily_remaining - mandatory_reserve, 90 000)
```

La cadence initiale ne dépasse pas 8 requêtes par seconde ou 480 par minute.
Chaque réponse peut la réduire. Un HTTP 429 entraîne un backoff exponentiel
avec jitter, trois reprises au maximum, puis l’ouverture du circuit.

## Persistance

Chaque appel fournisseur réussi passe d’abord par une intention durable, puis
par un payload gzip canonique et un reçu immuable :

```text
historical-deep-data/schema-v1/
  competition=<canonical-key>/
  season=<season>/
  family=<family>/
  endpoint=<endpoint>/
  task=<task-id>/
  payload-<sha256>.json.gz
  receipt.json
```

Une tâche `COMPLETE` ou `EMPTY_VALID` ne peut pas rappeler le fournisseur. Les
réservations de continuation sont bornées à 250 appels et les checkpoints de
collecte sont écrits au plus tard toutes les 250 requêtes ou cinq minutes.
Les versions d’un checkpoint sont append-only ; un pointeur mutable n’est pas
une autorité.

## Chaîne de workflows

| Numéro | Rôle | Fournisseur |
|---|---|---|
| 70 | statut Mega et census annoncé/vérifié | oui |
| 71 | fixtures, bundles et fallbacks ciblés | oui |
| 72 | pages joueurs paginées | oui |
| 73 | blessures puis sidelined borné | oui |
| 74A | audit de continuation et inventaire R2 immuable | non |
| 74B | replay segmenté, quatre lecteurs R2 maximum | non |
| 74C | reducer séquentiel et staging isolé | non |
| 74D | second replay complet et preuve d’idempotence | non |
| 75 | qualité, couverture V2 et gates | non |
| 76 | six datasets temporels séparés | non |
| 77 | pilote cache-only sans promotion | non |
| 78 | rapport de campagne sanitisé | non |

Le workflow 74 orchestre 74A–74D. Tous utilisent `historical-deep-r2-state` avec
`cancel-in-progress: false`. Le contrôleur 79 les enchaîne dans l’ordre. Les
jobs fournisseur s’arrêtent avant 110 minutes et partagent une limite de
mission de douze heures ; une phase terminée tôt permet de passer
immédiatement à la suivante.

Avant tout nouvel appel fournisseur, le contrôleur exige les trois preuves
`CURRENT_R2_REPLAY_VERIFIED`, `CURRENT_PROJECTION_RECONSTRUCTED` et
`CURRENT_SECOND_PASS_IDEMPOTENT`. Il exécute ensuite un replay et un contrôle qualité après P0, puis après
P1, avant d’autoriser la priorité suivante. Un replay en échec ou une qualité
autre que `COMPLETE` ferme la suite des appels fournisseur ; un dernier
replay/contrôle qualité précède les features et le backtest.

Tant que les nouveaux workflows ne sont pas présents sur la branche par
défaut, le workflow 21 sert uniquement de bootstrap à la branche de PR. Une
exécution manuelle avec `priority=HISTORICAL_DEEP_V1` sélectionne le contrôleur
79 et désactive complètement le pipeline legacy Git-first.

## Temporalité

Les features strictes n’acceptent que les faits dont le match source commence
strictement avant le match cible. Les lineups du match cible restent
`POST_LINEUP_RECONSTRUCTED`, ses statistiques restent `POST_MATCH_ONLY`, et une
blessure sans heure d’annonce prouvée reste
`ANNOUNCEMENT_TIME_UNKNOWN`. Les agrégats finaux d’une saison ne sont jamais
des features pré-match de cette même saison.

Les six datasets sont publiés séparément :

1. `TEAM_PREMATCH_STRICT`
2. `PLAYER_PREMATCH_STRICT`
3. `LINEUP_HISTORY_PREMATCH_STRICT`
4. `TARGET_POST_LINEUP_RECONSTRUCTED`
5. `INJURY_INTERVAL_RECONSTRUCTED`
6. `POST_MATCH_DESCRIPTIVE`

Chaque manifest déclare le cutoff, les usages autorisés, la provenance, les
nulls et le hash du contenu.

## Arrêt propre

Le collecteur rend un checkpoint et un rapport avant de s’arrêter pour quota,
limite de temps, taux d’erreur supérieur à 1 %, 429 répétés, circuit ouvert,
R2 indisponible, hash incohérent ou fournisseur bloqué. L’indisponibilité d’un
staging PostgreSQL ne peut jamais autoriser une écriture sur la production :
R2 reste le ledger durable jusqu’à la revue de la PR.

## Continuation de la PR 26

La fermeture P0 utilise une nouvelle lignée append-only :

```text
continuation_of = 30622258001:1
run_purpose = P0_CLOSURE_AND_SHARDED_REPLAY
continuation_id = p0-closure-30622258001-1
```

L’horloge et le verdict du run parent ne sont jamais modifiés. L’inventaire
partitionne déterministement par compétition, saison, famille et segment. Un
segment est fermé à 250 objets, 75 Mio logiques ou dix minutes estimées. Il
écrit des chunks indépendants et un checkpoint R2 toutes les 50 pièces ou cinq
minutes ; le reducer seul écrit dans le staging isolé. Le passage 2 relit R2
avec des checkpoints distincts et doit prouver zéro nouvel insert.
