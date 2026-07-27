# Runbook de migration R2

## Invariants

- branche : `codex/jalon-9-market-player-storage` ;
- PR #12 maintenue en brouillon jusqu'à fermeture de tous les gates ;
- `historical-data` reste la source principale ;
- R2 est un miroir privé, sans méthode de suppression ;
- `PRODUCTION_LOCKED`, `REAL_BETS=false`, `NO_BET_DEFAULT=true` ;
- aucun appel API-Football ni The Odds API pendant une migration ou restauration.

## Workflows

- `22 - Qualité historique` : benchmark cumulatif 25 puis 250 ;
- `30 - Migration object storage` : lots segmentés avec checkpoint ;
- `31 - Test restauration R2` : restauration représentative isolée.

Tous utilisent `historical-state`, `cancel-in-progress: false` et une
persistance légère des seuls contrôles R2.

## Benchmark 250

1. Attendre que `historical-state` soit libre.
2. Lancer le workflow 22 avec :
   - `run_external_validation=false`
   - `run_critical_closure=false`
   - `run_object_storage_migration=true`
   - `execute_object_storage_migration=true`
   - `object_storage_max_files=250`
3. Exiger `remote_verified=250`, zéro mismatch, zéro mutation et zéro
   suppression.
4. Rejouer exactement les mêmes paramètres.
5. Exiger `uploaded=0`, `replayed=250`, `remote_verified=250`.
6. Calculer l'ETA centrale et haute avant toute migration complète.

## Migration segmentée

Avant fusion, utiliser le workflow 22 sur la branche de la PR avec :

- `run_object_storage_migration=true`
- `execute_object_storage_migration=true`
- `object_storage_max_files=5000` pour la migration ;
- les deux autres modes spéciaux à `false`.

Une valeur supérieure à 250 active la reprise et découpe la borne en sous-lots
de 1 000 sous le même verrou. Répéter le run jusqu'à
`COMPLETE_VERIFIED`. Une valeur négative active l'audit sans écriture; utiliser
`-5000` jusqu'à `AUDIT_COMPLETE_VERIFIED`.

Après fusion, le workflow 30 expose directement :

- `execute=true`
- `max_files=<taille du lot validée>`
- `resume=true`
- `max_batches_per_run=<nombre borné par l'ETA mesurée>`
- `start_after=""`, sauf reprise opérateur explicite.

Le scope est figé dans `r2-migration-scope.json`. Le checkpoint contient
`next_index`, `last_key`, `uploaded`, `replayed`, `verified`, `failed` et le
statut. Ne jamais supprimer ou éditer manuellement ces fichiers.

Après un échec, relancer le même workflow avec `resume=true`. Le curseur reprend
au premier objet non acquitté. Ne pas utiliser un run monolithique si l'ETA
centrale dépasse 90 minutes ou si l'ETA haute dépasse 110 minutes.

Après la migration complète, relancer le workflow 30 avec les mêmes paramètres,
`resume=true` et `audit=true`. L'audit dispose de son propre checkpoint et
relit le scope complet sans aucun `PutObject`. Exiger
`AUDIT_COMPLETE_VERIFIED`, zéro upload, zéro mismatch et zéro objet manquant.

### Dimensionnement mesuré

- périmètre : 25 422 fichiers, 710 072 047 octets ;
- benchmark upload/replay : 250 fichiers en 246,660 s ;
- replay pur : 250 fichiers en 172,533 s ;
- projection monolithique restante : 400,6 minutes, donc interdite ;
- plan : six runs de 5 000 objets au plus, sous-lots de 1 000 ;
- durée centrale projetée par run plein : 82,7 minutes ;
- durée haute projetée par run plein : 102,6 minutes ;
- audit : six runs de 5 000 objets au plus.

Le volume et les opérations projetés restent sous les quotas gratuits mensuels
R2 publiés (10 Go-mois, 1 million de classe A, 10 millions de classe B). Ne
souscrire aucun service ni augmenter la taille des runs pour consommer un quota
disponible.

### Exécution réelle du périmètre figé

Les six runs de migration sont `30204764498`, `30209017214`,
`30212660451`, `30218134027`, `30220648824` et `30225027066`.
Le checkpoint final contient `next_index=25422`, `verified=25422`,
`uploaded=24627`, `replayed=471`, `bootstrapped_from_index=324` et
`status=COMPLETE`.

L'audit complet s'effectue avec la borne `-5000`. Il est strictement en lecture
seule : chaque segment doit conserver `uploaded=0` et `put_operations=0`.
Si un fichier source mutable a changé depuis la migration, ne pas contourner
le mismatch et ne pas réinitialiser le checkpoint. Exécuter d'abord un passage
normal de réplication continue sans fournisseur, puis reprendre l'audit au même
curseur jusqu'à `AUDIT_COMPLETE_VERIFIED`.

Preuves réelles de l'audit :

- segments 1 à 5 : `30225577323`, `30228448367`, `30230060695`,
  `30232044231`, `30233935541` ;
- incident bloquant sans écriture : `30236737672` ;
- réplication du delta et lag nul : `30238268175` ;
- reprise du segment 6 : `30239697041`.

Le checkpoint final contient `next_index=25422`, `verified=25422`,
`replayed=25422`, `uploaded=0`, `failed=0` et `status=COMPLETE`.

## Réplication continue

Les workflows historiques normaux passent les secrets R2 à l'action de
persistance. La réplication est limitée à 500 objets par run, avec deux retries
et circuit breaker après trois échecs consécutifs.

Contrôler `storage/r2-replication-latest.json` :

- `SYNCED` et `lag_objects=0` : miroir à jour ;
- `LAGGING` : relancer un workflow historique ou un replay de delta ;
- `CIRCUIT_OPEN` : conserver Git/Neon, corriger l'incident R2, puis rejouer.

Une panne R2 ne justifie jamais une suppression Git.

## Restauration

Lancer le workflow 31 seulement après un lot migré vert. Le dossier de
restauration est créé par `mktemp -d` et doit être vide. Le gate exige :

- JSON, Parquet, CSV, manifeste et checkpoint ;
- hash et taille identiques ;
- registre vérifié ;
- Parquet lisible ;
- replay bundle sans fournisseur ;
- zéro perte et zéro doublon métier ;
- `status=RESTORE_VERIFIED`.

Le test n'écrit jamais dans l'état historique réel.

## Gate avant fusion

La PR #12 ne devient prête que lorsque :

- benchmark et replay 250 verts ;
- migration segmentée complète et replay/audit intégral verts ;
- restauration R2 verte ;
- réplication continue verte et lag nul ;
- CI complète verte ;
- workflows 14, 21 et 22 verts ;
- aucun mode maintenance laissé actif ;
- production toujours verrouillée.

Ne pas fusionner automatiquement la PR.
