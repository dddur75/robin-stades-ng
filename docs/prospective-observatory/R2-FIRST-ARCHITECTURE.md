# Architecture R2-first

## Décision

R2 devient la source primaire des nouveaux payloads prospectifs bruts. Cette
décision ne change pas rétroactivement le rôle de `historical-data`.
Le namespace et les limites de stockage proviennent de
`configs/prospective_observatory_v1.json`.

```text
provider
  → payload JSON reçu
  → SHA-256 sur les octets canoniques
  → compression gzip déterministe
  → intention de reprise immuable
  → payload R2 conditionnel
  → receipt compact conditionnel
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
```

Le payload brut est dédupliqué par son hash. Chaque fenêtre conserve toutefois
un reçu distinct grâce au hash de portée `window_id + window_label`, y compris
si deux fenêtres partagent exactement le même payload et le même `observed_at`.

Avant le payload, une intention de reprise canonique et append-only conserve le
payload gzip exact et son reçu complet. Un arrêt après cette intention ou après
le payload est ainsi réparé sans rappeler le fournisseur. Une capture legacy
complète, payload et reçu cohérents mais sans intention, reste valide.

La capacité publiée compte les objets physiques uniques et leurs octets réels :
payloads, reçus JSON et intentions de reprise. Les compteurs
`physical_recovery_objects` et `physical_recovery_bytes` rendent explicite le
surcoût de durabilité. Les métriques de replay publient séparément les
références logiques et les octets relus ; elles ne supposent jamais
`objets = 2 × reçus`, car plusieurs reçus peuvent référencer le même payload
physique dédupliqué.
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
| PostgreSQL | index, relations, tentatives, reçus, projections, gates | corps JSON volumineux |
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

## Mesures d’exploitation

Le rapport quotidien expose objets ajoutés, octets, objets vérifiés, lag R2,
lag PostgreSQL, suppressions, mismatches et statut de replay. `lag=0` est
nécessaire mais ne suffit pas : les hashes et tailles doivent aussi concorder.
