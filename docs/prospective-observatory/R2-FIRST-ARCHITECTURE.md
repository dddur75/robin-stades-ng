# Architecture R2-first

## Décision

R2 devient la source primaire des nouveaux payloads prospectifs bruts. Cette
décision ne change pas rétroactivement le rôle de `historical-data`.
Le namespace et les limites de stockage proviennent de
`configs/prospective_observatory_v1.json`.

```text
fixture × fenêtre × tentative
  → guard R2 zéro unité immuable
  → transport fournisseur de données
  → payload JSON reçu
  → SHA-256 sur les octets canoniques
  → compression gzip déterministe
  → intention de reprise immuable
  → payload R2 conditionnel
  → receipt compact conditionnel
  → complétion append-only guard → hash du reçu
  → index PostgreSQL
  → projections et gates
```

## Namespace versionné

```text
prospective-deep-data/
  schema-v1/
    competition=<competition>/
      season=<season>/
        fixture=<fixture_id>/
          source=<provider>/
            family=<family>/
              observed_at=<utc_timestamp>/
                payload-<sha256>.json.gz
                receipt-<window-scope-sha256>-<payload-sha256>.json

prospective-deep-data-recovery/
  schema-v1/
    intent-<receipt-sha256>.json

prospective-deep-budget/
  prospective-provider-budget-v1/
    entry-<idempotency-sha256>.json
```

Le payload brut est dédupliqué par son hash. Chaque fenêtre conserve toutefois
un reçu distinct grâce au hash de portée `window_id + window_label`.
`physical_capture_id` est dérivé à la lecture par SHA-256 du fournisseur, de
l’endpoint, des temps de requête/réponse et du statut HTTP. API-Football ajoute
la fixture à cette identité, car ses réponses admises sont fixture-scoped.
The Odds API neutralise la fixture pour la réponse globale
`/sports/.../odds` : un même transport couvrant plusieurs matchs reste une
seule capture physique. Les reçus par fixture et famille demeurent des
observations sémantiques auditables, pas des transports supplémentaires.

Avant le payload, une intention de reprise canonique et append-only conserve le
payload gzip exact et son reçu complet. Un arrêt après cette intention ou après
le payload est ainsi réparé sans rappeler le fournisseur. Une capture legacy
complète, payload et reçu cohérents mais sans intention, reste valide.

Avant chaque transport fournisseur, l’unité maximale facturable est aussi
écrite dans le journal append-only R2
`prospective-deep-budget/prospective-provider-budget-v1`. PostgreSQL en conserve
la projection compacte. Le journal empêche qu’un crash entre le transport et
la base rende la consommation invisible.

Chaque transport de données possède en plus, avant le passage de la frontière
réseau, un guard R2 immuable de zéro unité, au grain fournisseur × commande ×
portée de requête × étape × fenêtre × numéro de tentative. Il ne représente
pas une consommation : il rend durable le fait que l’issue de cette tentative
peut devenir indémontrable. La reprise contrôle ce guard avant tout preflight.
Si le processus s’est arrêté après la réponse fournisseur mais avant la
première intention de capture R2, aucun reçu ne prouve l’issue : elle échoue
avec `PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED` sans second appel ni crédit.
Si le reçu R2 avait déjà été rendu durable mais que la complétion manquait, la
reprise réconcilie au contraire le lien append-only
`pcc1:<guard_sha256>:<receipt_hash>` sans fournisseur. Une preuve
de fraîcheur `/fixtures` ainsi complétée est réutilisée avant d’autoriser le
transport profond. Le fail-closed ne vise donc que le guard réellement non
résolu.

Le guard utilise la clé compacte
`pcg1:<provider>:<command>:<f|d>:<scope_sha256>:<step_sha256>:<window_sha256>:aN`.
Sa longueur maximale mesurée reste inférieure à 250 caractères ; la complétion
`pcc1` en compte 134. Les deux sont donc compatibles avec
`provider_budget_ledger.idempotency_key VARCHAR(250)` dans PostgreSQL.

Cette traçabilité ajoute une entrée R2 et une lignée SQL de complétion par
guard. Sans retry, la projection de capacité compte 71 guards et 71 complétions
par fixture ; ces enregistrements portent zéro unité fournisseur.

La capacité publiée compte les objets physiques uniques et leurs octets réels :
payloads, reçus JSON et intentions de reprise. Les compteurs
`physical_recovery_objects` et `physical_recovery_bytes` rendent explicite le
surcoût de durabilité. Les métriques de replay publient séparément les
références logiques et les octets relus ; elles ne supposent jamais
`objets = 2 × reçus`, car plusieurs reçus peuvent référencer le même payload
physique dédupliqué.
Le journal budget possède son propre inventaire et n’est pas inclus dans les
compteurs du namespace raw `prospective-deep-data`.
Tous les segments sont normalisés et validés. Une clé ne contient ni secret,
ni header, ni URL signée, ni paramètre de clé API.

## Contrat d’immutabilité

- `PutObject` utilise une création conditionnelle.
- Une clé existante avec le même hash est un replay idempotent.
- Une clé existante avec un autre contenu est
  `IMMUTABILITY_CONFLICT` et bloque la projection.
- Aucun workflow courant ne possède d’opération de suppression.
- Une correction produit un nouvel objet, un nouveau reçu et une nouvelle
  version ; elle ne remplace pas l’objet antérieur.

Le reçu contient au minimum :

```json
{
  "schema_version": "prospective-capture-receipt-v1",
  "fixture_id": "...",
  "provider": "...",
  "family": "LINEUP",
  "requested_at": "...",
  "response_received_at": "...",
  "observed_at": "...",
  "kickoff_at": "...",
  "payload_sha256": "...",
  "payload_bytes": 0,
  "r2_key": "...",
  "complete": true,
  "quality_status": "...",
  "provider_calls": 1,
  "code_revision": "..."
}
```

Les secrets et headers sensibles sont interdits.

## Rôle des stockages

| Stockage | Contenu | Interdit |
|---|---|---|
| R2 | intentions de reprise, payloads gzip, reçus unitaires, versions | suppression et écrasement |
| R2 budget | réservations fournisseur append-only, idempotentes | écriture négative ou réinitialisation |
| PostgreSQL | index, relations, tentatives, reçus, budgets, projections, gates | corps JSON volumineux |
| Git | code, migrations, contrats, rapports compacts, hashes | payload brut |
| Artifacts GitHub | rapports bornés et preuves de run | source primaire durable |

Le navigateur Robin Live ne reçoit qu’un snapshot compact nettoyé.

## Double écriture contrôlée

L’écriture n’est déclarée complète que si :

1. le payload est vérifiable dans R2 ;
2. le reçu référence sa clé et son SHA-256 ;
3. PostgreSQL indexe ce reçu avec la même identité métier ;
4. le rapport compact réconcilie R2 et PostgreSQL.

Une panne PostgreSQL après R2 produit un incident explicite et un lag. Le replay
reprojette depuis R2 sans rappel fournisseur. Une panne R2 empêche de présenter
la capture comme durable.

La réconciliation est stricte et bidirectionnelle :

- chaque reçu R2 doit exister à l’identique dans PostgreSQL ;
- aucun reçu PostgreSQL supplémentaire n’est accepté ;
- chaque reçu doit avoir exactement un index payload lié, avec mêmes fixture,
  famille, temps, hashes, tailles, clés R2 et provenance ;
- le jeu des clés de budget R2 et PostgreSQL doit être identique ;
- les ensembles complets de lignes doivent être identiques dans
  `prospective_player_status`, `prospective_injuries`,
  `prospective_lineups`, `prospective_formations` et
  `prospective_odds_snapshots` ;
- une base vide ou partielle est complétée depuis R2 avant le calcul des
  fenêtres dues ;
- une ligne PostgreSQL orpheline ferme le run, elle n’est pas copiée
  silencieusement vers R2.

La seule compatibilité transitoire est l’amorçage idempotent d’un ancien
journal budget PostgreSQL. Chaque ligne SQL est écrite conditionnellement dans
R2, même si le namespace R2 est déjà partiellement rempli. Puis R2 est
reprojeté en SQL et clés, fournisseur, unités, soldes, réserves, timestamp,
raison et révision doivent être strictement identiques. Un conflit
append-only bloque la réconciliation.

Les reçus `CAPTURED_EMPTY` restent une preuve R2/SQL, mais ne fabriquent aucune
ligne de projection analytique. Pour `INJURY`, le gate peut interpréter ce vide
comme « aucune blessure rapportée à cet instant », jamais comme un zéro ni
comme une absence médicale certaine.

## Idempotence

L’identité d’une capture associe fixture, fournisseur, famille, fenêtre,
`observed_at` et hash du payload. Rejouer le même objet donne :

```text
provider_calls=0
provider_credits=0
business_duplicates=0
hash_mismatches=0
data_loss=0
```

Les upserts de projection ne rendent jamais mutables les tentatives ni les
reçus.

Un replay complet publie exactement :

```text
status=R2_REPLAY_VERIFIED
postgresql.reconstruction_status=
  CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2
```

Une fixture attendue non reconstruite donne
`R2_REPLAY_PARTIAL_FIXTURE_INDEX` et `RECONSTRUCTION_INCOMPLETE`.

## Mesures d’exploitation

Le rapport quotidien expose objets ajoutés, octets, objets vérifiés, lag R2,
lag PostgreSQL, suppressions, mismatches et statut de replay. `lag=0` est
nécessaire mais ne suffit pas : les hashes et tailles doivent aussi concorder.

Les métriques séparent trois cardinalités :

- `physical_http_calls` : somme des appels HTTP attribués aux reçus de captures
  physiques ; les appels de contrôle sans reçu restent dans le rapport de run
  et le journal budget, qui demeure l’autorité de consommation ;
- `r2_puts` : objets créés par la capture courante ;
- `recovery_r2_puts` : payloads ou reçus rematérialisés depuis une intention
  antérieure, sans fournisseur.

Ainsi, `windows_due=0` exige `provider_calls=0` et `r2_puts=0` pour le run.
Le `physical_http_calls` cumulatif du ledger reste inchangé, tandis qu’un
`recovery_r2_puts` non nul demeure autorisé et explicitement séparé.
