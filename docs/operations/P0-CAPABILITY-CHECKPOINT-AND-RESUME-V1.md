# P0 Capability Checkpoint and Resume V1

Ce contrat rend la future mission reprenable sans faire des artefacts GitHub
l'unique source durable. Il est testé localement sur le Golden Pack synthétique ;
aucun objet R2, aucune table Neon et aucun workload réel ne sont touchés ici.

## Checkpoint minimal

Chaque niveau et chaque shard produit un document canonique contenant :

```text
mission_id
stage
capability_scope
source_sha
dataset_hash
cursor
objects_read
bytes_read
fixtures_processed
status
next_action
```

Le document porte aussi `attempt`, `previous_checkpoint_hash`,
`gate_results_hash`, les consommations par service et son propre
`checkpoint_hash` SHA-256. Le hash est calculé sur le JSON UTF-8 canonique sans
le champ `checkpoint_hash`. La chaîne lie donc source, dataset, cursor, gates,
budgets et décision ; toute mutation rétrospective devient détectable.

Valeurs de statut admises :

```text
STARTED
CHECKPOINTED
COMPLETED
FAILED_RETRYABLE
FAILED_REDESIGN_REQUIRED
STOPPED_LOCAL_CAMPAIGN
BLOCKED_EXTERNAL_ACTION
```

Un checkpoint `COMPLETED` est la seule base d'une transition automatique. Un
checkpoint incomplet peut reprendre le même shard, jamais ouvrir l'étape
suivante.

## Identité et idempotence

Clé logique :

```text
mission_id / source_sha / stage / capability_scope / dataset_hash / shard_id
```

Une réexécution avec la même clé doit produire le même hash de sortie ou
échouer `SOURCE_HASH_MISMATCH`. Une sortie déjà complète est relue et vérifiée,
pas recalculée. Un cursor n'est valide que pour le même dataset, la même source
et le même périmètre de capacité.

## Ordre de persistance

1. Écrire localement le document compact de manière atomique.
2. Vérifier le JSON, le hash, le lien précédent et les compteurs.
3. Persister le manifeste autoritatif dans Git pour les contrats/revues, ou en
   append-only dans R2 pour les preuves/datasets réels. Les seuls writes R2
   autorisés ici sont 256 checkpoints/manifests compacts maximum sous le préfixe
   dédié ; aucun payload brut, overwrite ou delete. Ce plafond ne devient actif
   qu'après une décision C0/DP5/A2 append-only au ledger ; sinon il vaut zéro.
4. Publier seulement ensuite une copie d'observation comme artefact GitHub.
5. Journaliser le pointeur durable, le hash et la décision.

Les payloads fournisseur bruts ne vont jamais dans Git. Les artefacts GitHub
peuvent accélérer une reprise, mais leur absence ne doit pas détruire l'autorité.

## Reprise par incident

| Incident | Reprise minimale | Interdiction |
|---|---|---|
| annulation GitHub | reprendre le dernier shard `CHECKPOINTED` compatible | repartir du corpus complet |
| runner shutdown | vérifier le hash durable puis reprendre au cursor | faire confiance au workspace éphémère |
| timeout | réduire le shard, conserver le niveau | augmenter le timeout au-delà de 15 min |
| CI retardée | attendre ou poursuivre un travail indépendant | démarrer un doublon stateful |
| artifact perdu | relire le manifeste Git/R2 autoritatif | déclarer la preuve perdue sans audit |
| pending remplacé | résoudre l'intention committée avant dispatch et reprendre depuis le dernier checkpoint durable | supposer le run pending durable |
| redémarrage Codex | résoudre Git/PR/run/checkpoint exacts | reconstruire l'état de mémoire |

## Algorithme de reprise

1. Résoudre le manifeste futur par hash.
2. Résoudre la dernière chaîne de checkpoints valide.
3. Vérifier mission, source, dataset, stage, capacité et budgets cumulés.
4. Refuser tout trou ou hash de chaîne divergent.
5. Vérifier qu'aucun run stateful identique n'est actif ou pending.
6. Relire uniquement les objets explicitement autorisés.
7. Reprendre au cursor ; les objets déjà reçus sont vérifiés par hash.
8. Produire un nouveau checkpoint lié au précédent.

## Budgets et compteurs

Les compteurs sont monotones et cumulatifs : objets/bytes lus, fixtures,
GET R2, écritures R2, appels fournisseur, crédits de cotes et opérations SQL.
Le dépassement d'un seul plafond produit `BUDGET_EXCEEDED` avant l'opération
suivante. Une valeur inconnue n'est ni zéro ni autorisation implicite.

Dans ce prévol synthétique, tous les compteurs externes valent exactement zéro.
Dans la future mission, le plafond R2 lecture est 10 000 GET et le plafond
d'écriture checkpoint est 256 objets compacts append-only ; API, cotes et SQL
restent à zéro. La mission de prévol actuelle consomme zéro opération externe.

## Retry et redesign

La signature d'échec combine taxonomie, cause racine et périmètre de capacité.
Premier échec similaire : correctif minimal, même niveau. Deuxième :
`REDESIGN_REQUIRED`. Troisième tentative identique :
`FORBIDDEN_FAIL_AND_STOP`. Un redesign change explicitement la signature,
le contrat et le hash ; il ne réécrit jamais une preuve historique.

## Test mécanique couvert

Le test de prévol sérialise un checkpoint E2, le recharge depuis un fichier
temporaire, reprend E3A/E3B et exige le même hash final qu'une exécution
ininterrompue. Il rejette un checkpoint altéré et vérifie l'idempotence de deux
runs complets identiques. Ce résultat reste `MECHANICAL_PREFLIGHT_ONLY`.
