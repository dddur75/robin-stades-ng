# Contrat d'exploitation GitHub Actions

## Groupes de concurrence

Les nouvelles orchestrations utilisent des groupes distincts :

```text
historical-deep-manual
historical-deep-scheduled
prospective-live
cockpit-refresh
research-campaign
deployment
```

Une collecte manuelle critique ne partage jamais son groupe avec un cron, un
refresh cockpit, un rapport ou une validation secondaire. Avant d'annuler un run
fournisseur, prouver qu'il n'écrit plus d'état durable et journaliser l'annulation.

## Batching et durée

Le nombre de batches est calculé avant création de la matrice. Pour toute nouvelle
orchestration de cette mission, un job cible 15 minutes, s'arrête à 20 minutes et
checkpoint au plus toutes les cinq minutes. Les limites générales GitHub ne sont
pas des objectifs de durée.

Deux tentatives automatiques au plus. `GITHUB_RUN_ATTEMPT` appartient à la lignée
d'exécution, jamais à la lignée scientifique. Un échec répété change
l'architecture ou revient à E0/E1.

Tout nouveau workflow part de `permissions: {contents: read}`. Une élévation est
job-scoped, justifiée et minimale. Les secrets ne sont injectés que dans le job
fournisseur qui les consomme. Les actions tierces sont épinglées à un SHA immuable,
pas à un seul tag majeur. `cancel-in-progress` est toujours explicite. Les marqueurs
réservés `[run-j12-pilot]` et `[run-j12-replay-only]` ne sont jamais réutilisés par
une nouvelle mission. La PR Robin Council n'ajoute aucun workflow, secret ou droit.

## Artefacts et reprise

Un artefact GitHub accélère le passage entre jobs mais n'est pas l'unique preuve.
Manifests, receipts et checkpoints content-addressed sont durables dans R2.
Les noms d'artefacts incluent `run_id`, `run_attempt`, shard et lignée pour éviter les
collisions.

Les rapports `always()` sont courts, ne scannent pas le corpus et ne maintiennent
pas un verrou critique. Ils publient état, compteurs, prochaine clé de reprise et
raisons fail-closed, sans convertir une étape sautée en succès.
