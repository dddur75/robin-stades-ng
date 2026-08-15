# First Receipt-Backed Capture Harness V1

## Décision

Le moteur durable de capture est construit et prouvé hors réseau. Il ne contient aucun transport HTTP : `VALIDATE_OFFLINE` est le mode par défaut, `DRY_RUN` calcule seulement le fingerprint et la réservation budgétaire, et `LIVE_CANARY` échoue immédiatement avec `ROBIN_LIVE_CANARY_DISABLED_NOT_AUTHORIZED`.

Cette mission a effectué zéro appel à un endpoint fournisseur, lu zéro clé réelle, consommé zéro crédit, lancé zéro expérience, calculé zéro pari et effectué zéro promotion.

## Architecture

Le package `robin.capture` contient quatre surfaces :

- `contracts.py` définit les onze contrats immuables : `ProviderRequestSpec`, `RequestFingerprint`, `CaptureBudget`, `QuotaObservation`, `RawPayloadReceipt`, `NormalizedMarketObservation`, `SchemaFingerprint`, `FixtureMapping`, `CaptureManifest`, `InternalRetentionPolicy` et `OfflineReplayResult` ;
- `harness.py` applique les gardes, calcule le SHA-256 brut avant tout parsing, met en quarantaine les réponses rejetées et matérialise reçus, observations et manifests ;
- `normalization.py` parse le JSON sans clés dupliquées, impose un mapping fixture bijectif et exhaustif, lie l'ensemble canonique des mappings et leurs révisions au snapshot, exige des bookmakers uniques par événement, puis produit un JSONL canonique ;
- `storage.py` fournit le stockage content-addressed, atomique create-if-absent, idempotent et collision fail-closed, ainsi que le replay offline et la suppression TTL.

Le générateur `tools/data-sourcing/build_capture_harness_artifacts.py` reconstruit les cinq rapports V1 depuis une fixture entièrement synthétique. Son mode `--check` compare les octets calculés aux rapports suivis.

## Modes et absence de réseau

| Mode | Effet | Réseau | Secret |
|---|---|---:|---:|
| `VALIDATE_OFFLINE` | Valide, enregistre des octets fournis localement et rejoue | 0 | 0 lecture réelle |
| `DRY_RUN` | Valide la requête, le fingerprint et le budget, sans payload | 0 | 0 |
| `LIVE_CANARY` | Refus immédiat | 0 | aucune lecture avant refus |

Les tests `capture` remplacent `socket.socket`, `socket.create_connection` et `socket.getaddrinfo` par des fonctions qui échouent. Le passage de la suite prouve donc l'absence d'usage socket et DNS sur toutes les voies testées.

## Préflight fail-closed

Avant toute future frontière réseau, le contrat impose :

- schéma `https` et host exact `api.the-odds-api.com` ;
- aucun redirect et `retries = 0` ;
- région `eu` et marchés limités à `h2h` et `totals` ;
- budget explicite et cumulatif dans un ledger local hash-chaîné, fsync et verrouillé entre processus, dont chaque transition prouve les deltas et compteurs antérieurs, avec réservation refusée avant dépassement des appels ou crédits, y compris après recréation du harness ;
- endpoint relatif sans query, token, clé ou paramètre sensible ;
- politique `INTERNAL_MARKET_DATA_RETENTION_POLICY_V1` présente ;
- racine de capture locale explicitement approuvée, hors de tout ancêtre Git et hors dossier synchronisé ; une vérification OS-backed des racines Cloud Files, lecteurs réseau et clients de synchronisation reste obligatoire avant le live ;
- pour une future voie live séparément autorisée, secret présent uniquement dans `THE_ODDS_API_KEY` et absent de tout matériel public.

La classe `SecretCapability` ne conserve jamais la valeur du secret et exige un matériau public non vide à contrôler. La sentinelle synthétique est injectée via un mapping d'environnement de test, puis tous les fichiers du store sont balayés : occurrence observée dans les outputs = 0. Les frontières de validation publiques transforment les erreurs Pydantic en codes stables sans entrée rejetée, y compris pour un contrat composite. Aucun fingerprint, reçu, manifest, chemin ou exception ne reçoit cette valeur.

## Ordre de capture et intégrité

Pour une réponse fournie hors réseau, l'ordre est immuable :

1. valider requête, mode, politique et budget ;
2. fixer `robin_first_observed_at` et `robin_ingested_at` en UTC ;
3. valider la plage du statut HTTP, calculer le SHA-256 et refuser sans conservation brute tout payload dépassant la borne ;
4. écrire un reçu d'intake `INTAKE_PENDING` avec TTL avant les octets et conserver son identifiant dans tout reçu final associé ;
5. écrire les octets dans le store content-addressed ;
6. valider redirect et quota, puis parser le JSON et calculer le fingerprint de schéma ;
7. valider mapping bijectif, bookmakers, timestamps et complétude des marchés ;
8. écrire reçu final, JSONL normalisé et manifest immuables et auto-vérifiables.

Ainsi, même un crash immédiatement après l'écriture brute laisse un reçu d'intake gouverné par la TTL, et un JSON invalide possède son SHA-256 et son reçu final de quarantaine. Un payload trop grand conserve son hash et son reçu, jamais ses octets. Une collision entre une identité et des octets différents arrête le traitement.

`available_at` n'est jamais antérieur à `robin_first_observed_at`. Pour une observation de marché, il vaut le maximum entre la première observation Robin et `market.last_update` lorsqu'il est présent. L'absence de `market.last_update` reste explicite (`null`) et ne provoque aucun antidatage.

## Stockage durable

```text
raw/sha256/<prefix>/<sha>.bin
receipts/<receipt_id>.json
normalized/<snapshot_id>.jsonl
manifests/<snapshot_id>.json
quarantine/
deletion-ledger.jsonl
budget-ledger.jsonl
```

Les payloads bruts expirent exactement 30 jours après `robin_first_observed_at`. Capture et sweep partagent un verrou fichier inter-processus sur le store : aucun nouveau reçu du même hash ne peut être finalisé au milieu d'un snapshot TTL. La suppression écrit et fsync d'abord une intention dans un ledger hash-chaîné, supprime ensuite les octets, puis écrit le commit. Une panne de journal avant l'intention laisse donc le brut intact ; une panne après suppression laisse au moins l'intention durable. Les reçus, le SHA-256 brut, les observations normalisées et les données dérivées restent conservés. Un même payload référencé par un reçu encore actif n'est pas supprimé prématurément.

Le replay revérifie les identités du reçu et du manifest, l'existence et les champs communs du reçu d'intake, l'égalité entre `captured_at` et l'ingestion du reçu, l'ensemble exact des mappings et leurs révisions, tous les liens vers le brut et le JSONL, puis le SHA-256 brut avant parsing. Il renormalise sans réseau et refuse de produire le verdict `PROVEN` si l'identité du snapshot, les octets JSONL, le hash normalisé, le fingerprint de schéma ou le nombre d'observations divergent. La preuve synthétique est enregistrée dans `reports/data-sourcing/offline-replay-proof-v1.json`.

## Fixtures synthétiques

Le pack `tests/capture/fixtures/synthetic-odds-responses-v1.json` ne contient aucune donnée fournisseur. Il couvre h2h complet, h2h+totals, totals absent, `market.last_update` présent et absent, bookmaker incomplet, événement dupliqué, mapping ambigu, timestamp invalide, JSON invalide, HTTP non-200, payload trop grand, quota invalide, redirect et secret sentinelle.

Les équipes, bookmakers, identifiants et prix sont fictifs. Aucun payload réel, nom de bookmaker associé à un prix réel, URL authentifiée ou clé n'est admis dans Git.

## Limites et arrêt

La présence locale du workspace canari a été constatée, mais aucun des quatre fichiers de métadonnées autorisés n'y était présent. Aucune métadonnée canari n'a donc été intégrée et aucune exploration plus large du répertoire n'a été effectuée.

Le harness n'autorise pas le live. Une mission séparée devra fournir une autorisation propriétaire, initialiser et éprouver le budget persistant sous concurrence réelle, fournir un workspace local non synchronisé vérifié par l'OS, une politique active et orchestrée, une clé d'environnement, puis exiger replay et secret scan. Aucun de ces prérequis n'autorise une archive brute permanente, une saison complète, une expérience, une promotion ou un pari.

## Sources publiques examinées

La revue du 15 août 2026 s'appuie sur les [conditions officielles](https://the-odds-api.com/terms-and-conditions.html), qui admettent les outils analytiques mais interdisent la redistribution brute autonome, sur la [documentation V4](https://the-odds-api.com/liveapi/guides/v4/) pour le host et les headers de quota, et sur l'[avertissement de domaine officiel](https://the-odds-api.com/impersonation-warning.html). Elle ne constitue pas un avis juridique ni une autorisation contractuelle explicite de rétention.

## Verdicts

```text
ROBIN_RECEIPT_CAPTURE_HARNESS_V1_DRAFT_READY
ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN
INTERNAL_MARKET_DATA_RETENTION_POLICY_V1_RECORDED
ROBIN_LIVE_CANARY_DISABLED
NO_PROVIDER_CALL
NO_PROMOTION
NO_BET
```
