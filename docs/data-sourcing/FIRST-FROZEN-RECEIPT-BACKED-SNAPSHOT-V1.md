# Frozen Receipt-Backed Snapshot Tooling V1

## Décision de livraison

Cette mission livre uniquement l'outillage offline, ses fixtures synthétiques, le classifier fail-closed et les gardes d'intégrité et de confidentialité. Le batch réel `FIVE_CANARY_RECEIPT_BATCH_V1` n'a pas été exécuté : le gate `REPOSITORY_LIVE_ACTIVATION_REQUIRED` a produit `BATCH_REQUIRES_REPOSITORY_ACTIVATION` avant toute lecture de secret, résolution DNS ou requête fournisseur.

Les statuts de livraison sont donc :

```text
tooling_status = OFFLINE_DRAFT_READY
synthetic_validation_status = PASS
real_data_status = NOT_AVAILABLE
real_batch_status = NOT_EXECUTED
real_capture_count = 0
real_snapshot_status = NOT_CREATED
real_snapshot_count = 0
experiment_readiness_status = NOT_ASSESSED_ON_REAL_DATA
real_executable_experiment_count = 0
accumulation_candidates = []
```

Aucun `FINALIZED.json` n'est attendu ou sondé par cette mission. Aucun snapshot réel, profil qualité réel, readiness réelle ou candidat d'accumulation réel n'est revendiqué.

## Témoin de non-exécution

Deux preuves externes seulement ont été lues en lecture seule. Le rapport Git sanitisé `five-canary-batch-non-execution-witness-v1.json` conserve leurs références logiques et leurs SHA-256 :

```text
P0_NON_EXECUTION_REPORT = 055ac930a71baf99307b54713da861316808fbef6bc23c60c93042d69ec6667c
PREFLIGHT_EVIDENCE = 2d26a1b72a503972b81ecc537c34c8733094629635731d88fbf637e92c90f88a
```

Il ne sérialise aucun chemin Windows, secret, payload, cote, événement fournisseur ou URL authentifiée. Les compteurs attestés sont : appels fournisseur 0, lectures de secret 0, résolutions DNS 0, crédits 0, retries 0, paris 0, écritures Git du batch 0 et exposition de secret 0.

## Outillage préservé

Le builder réel reste volontairement fail-closed pour une mission future autorisée. Il :

- lit le raw et vérifie son SHA-256 avant parsing ;
- lie reçu final, reçu intake, raw, manifeste technique, normalisé et schéma PR59 ;
- re-normalise le raw et exige les octets JSONL exacts ;
- rejette les racines qui se chevauchent, UNC, lecteurs distants, reparse points, junctions, symlinks et hardlinks ;
- arme une sentinelle continue avant la première lecture et exige au moins cinq minutes de stabilité ;
- bloque socket, DNS, HTTP et urllib pendant la validation ;
- rejette secrets, credentials, URL signées, chemins absolus et données de marché détaillées ;
- calcule chaque dénominateur à son grain explicite ;
- ne promeut un mapping que depuis les preuves canoniques complètes ;
- lie strictement les rôles temporels, cutoffs, timestamps et reçus ;
- valide le manifeste et les sept rapports contre les schémas runtime avant toute écriture ;
- s'arrête avant matérialisation dès que le gate scientifique est fermé.

## Contrat synthétique

Le dialecte synthétique utilise les modèles PR59 publics et une identité distincte. Il ne peut pas être routé vers la voie réelle : le flag CLI `--synthetic-contract` fixe l'identité synthétique et le bypass de durée reste interdit à tout autre batch.

Un snapshot synthétique peut être matérialisé temporairement pour prouver la canonicalisation, l'immuabilité, la reproductibilité et les sept rapports. Son manifeste et son marqueur portent `snapshot_scope=SYNTHETIC_CONTRACT_ONLY` et `real_snapshot_status=NOT_CREATED`. Ses rapports portent toujours :

```text
tooling_status = OFFLINE_DRAFT_READY
synthetic_validation_status = PASS
real_data_status = NOT_AVAILABLE
```

Ils ne qualifient jamais les données ou expériences synthétiques comme réelles, production-ready, exécutables ou démarrées. La readiness publiée garde les 25 contrats PR57 une fois chacun, ne conserve que les statuts fermés `DATA_GATE_BLOCKED` ou `PROTOCOL_SUCCESSOR_REQUIRED`, fixe `real_readiness_claimed=false` et publie zéro candidat.

## Gate scientifique

La logique de test vérifie séparément qu'un gate substantiel ne pourrait s'ouvrir qu'avec :

- au moins un mapping canonique prouvé ;
- absence de drift incompatible ;
- un token h2h commun avec exactement domicile, nul et extérieur ;
- au moins cinq bookmakers complets distincts par fixture et capture ;
- tous les timestamps source et bookmaker requis présents et UTC-valides ;
- une fenêtre commune `PREDICTOR:H2` valide et liée à son reçu.

Toute absence ferme le gate. Gate fermé implique `accumulation_candidates=[]`, aucune affirmation de capacité et arrêt avant écriture dans la voie réelle. Les fixtures synthétiques testent ce comportement sans constituer une preuve de disponibilité réelle.

## Exécution synthétique

Génération de la fixture :

```powershell
py -3.12 tools/data-sourcing/generate_synthetic_frozen_batch_v1.py `
  --output <synthetic-source>
```

Construction contractuelle temporaire :

```powershell
py -3.12 tools/data-sourcing/build_frozen_snapshot_v1.py `
  --synthetic-contract `
  --source <synthetic-source> `
  --output-root <synthetic-output> `
  --reports-output <synthetic-reports> `
  --observation-seconds 0
```

Deux racines temporaires distinctes doivent produire le même identifiant, les mêmes listes de fichiers et les mêmes octets. Le troisième appel ajoute `--check` sur l'une des sorties et ne doit écrire aucun octet. Les dossiers temporaires sont supprimés après vérification.

## Frontières Git et réseau

Git reçoit uniquement du code, des tests, des schémas, des fixtures entièrement synthétiques, des hashes, comptages, statuts et le témoin sanitisé. Les payloads réels, cotes, équipes associées aux cotes, listes bookmaker-prix, identifiants d'événements, clés, query strings, URL authentifiées et chemins locaux sont interdits.

La mission n'exécute aucun backtest, calcul d'edge, sélection par performance, achat, promotion ou pari. Elle ouvre uniquement une Draft PR ; elle ne passe pas Ready et ne fusionne pas.

## Mission suivante

La prochaine autorité distincte devra être :

```text
BOUNDED LIVE CANARY ACTIVATION
AND PROVIDER TRANSPORT V1
```

Elle devra ajouter et tester explicitement l'activation locale du canari et le transport fournisseur borné avant qu'un nouveau batch réel puisse être lancé.
