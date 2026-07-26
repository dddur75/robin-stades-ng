# Runbook de migration R2

## Invariants

- workflow pré-fusion : `22 - Qualité historique` ;
- branche : `codex/jalon-9-market-player-storage` ;
- `PRODUCTION_LOCKED`, `REAL_BETS=false`, `NO_BET_DEFAULT=true` ;
- bucket R2 privé, endpoint global
  `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`, région `auto` ;
- aucune suppression et conservation intégrale de `historical-data` ;
- aucun appel API-Football ni consommation The Odds API.

Le dry-run ne lit aucun secret R2 et n'instancie aucun client distant. Les
quatre secrets `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY` et `R2_BUCKET_NAME` ne sont transmis au script que
comme variables d'environnement lors d'une exécution réelle.

## Procédure pré-fusion exacte

Dans GitHub Actions, choisir `22 - Qualité historique`, puis sélectionner la
branche `codex/jalon-9-market-player-storage`.

1. Dry-run :
   - `run_external_validation=false`
   - `run_critical_closure=false`
   - `run_object_storage_migration=true`
   - `execute_object_storage_migration=false`
   - `object_storage_max_files=25`
2. Premier lot réel de 25 :
   - mêmes valeurs, sauf `execute_object_storage_migration=true`
3. Rejouer exactement le lot de 25 avec les mêmes valeurs.
4. Passer à `object_storage_max_files=250`.
5. Utiliser une valeur très supérieure au périmètre, par exemple
   `object_storage_max_files=1000000`, pour vérifier tout le périmètre.
6. Rejouer la valeur complète pour prouver l'idempotence globale.
7. Contrôler le rapport durable
   `storage/r2-migration-latest.json` après chaque exécution.
8. Ne jamais supprimer la branche `historical-data` ni ses fichiers.
9. Ne fusionner la PR #12 qu'après un replay complet vert.

Un seul des trois modes spéciaux `run_external_validation`,
`run_critical_closure` et `run_object_storage_migration` peut être actif.

## Résultats attendus

Dry-run :

- `mode=DRY_RUN`, `status=DRY_RUN_READY`, `complete=false` ;
- `uploaded=0`, `replayed=0`, `remote_verified=0` ;
- `deletions=0`, `source_mutations=0`, `double_write=true` ;
- `bucket_hash=null` et aucun secret requis.

Premier lot de 25, si le périmètre compte au moins 25 fichiers :

- `selected_files=25`, `uploaded=25`, `replayed=0` ;
- `remote_verified=25`, zéro mismatch et zéro objet distant manquant ;
- `status=PARTIAL_VERIFIED`, sauf si le périmètre total ne dépasse pas 25.

Replay du lot de 25 :

- `selected_files=25`, `uploaded=0`, `replayed=25` ;
- les 25 objets sont relus et `remote_verified=25`.

Exécution complète :

- `selected_files=source_files` ;
- `remote_verified=source_files` ;
- `status=COMPLETE_VERIFIED` et `complete=true` uniquement avec zéro
  mismatch, zéro objet manquant, zéro mutation source et `double_write=true`.

Toute erreur d'authentification, d'autorisation, de réseau, de hash ou de
taille est bloquante. Un `401` ou `403` n'est jamais assimilé à un objet
absent.

## Risques résiduels

- coût et durée de lecture/écriture du périmètre complet d'environ 500 MB ;
- indisponibilité temporaire de GitHub Actions, R2 ou du pont
  `historical-data` ;
- erreur de configuration du bucket privé ou de ses credentials ;
- mutation concurrente du périmètre source, qui fait échouer la preuve.

Le workflow est limité à 120 minutes et le groupe de concurrence
`historical-state` sérialise les écritures durables.
