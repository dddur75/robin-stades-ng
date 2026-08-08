# Phase C Execution Contract V1

## État actuel

Les workflows 86–89 sont `workflow_dispatch` uniquement, read-only et
`cancel-in-progress=false`. Ils sont volontairement dormants :
`phase-c-execution-activation-v1.json` vaut
`HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH`, `allowed_execution_sha=null`, et le verrou
d’artefacts Phase C est vide. Aucun workflow Phase C n’a été déclenché dans
cette PR draft.

Une activation future doit être committée et revue sur la branche par défaut.
Le preflight partagé `validate_phase_c_workflow_contract.py` est lu depuis un
checkout `main` séparé, puis exige la triple égalité : SHA de l’input, head
distant de la branche et `allowed_execution_sha`. Il recalcule le hash canonique
de l’activation et du verrou d’artefacts, ainsi que les hashes du preflight, du
générateur, des quatre workflows et du verrou source. Le candidat ne peut
jamais s’auto-autoriser.

Les runs source, les stages amont et les reprises sont relus par l’endpoint
GitHub exact `runs/{run_id}/attempts/{attempt}`. Un rerun ultérieur ne peut donc
ni invalider un verrou d’attempt antérieur ni substituer silencieusement le
dernier attempt.

## Chaîne d’artefacts

1. Raw census lit les cinq artefacts E3 immuables, après validation exacte de
   run, attempt, head, ID, nom, taille, digest, expiration et budget.
2. Tag/mask lit ces cinq mêmes sources et publie census, registre, 80 masques
   binaires et `analysis-core-v1.json.gz` compact.
3. Atomic consomme uniquement l’artefact tag/mask verrouillé ; il ne
   retélécharge pas les 95 006 161 octets bruts.
4. Pair consomme les artefacts tag/mask et atomic verrouillés, répartit les
   120 paires par hash sur huit shards, puis réduit exactement huit sorties.

Chaque stage dérivé doit être inscrit sur `main` dans
`phase-c-artifact-lock-v1.json` avec workflow, run, attempt, head, artifact ID,
nom, taille, digest et hash de `stage-manifest-v1.json`. Un ID fourni par un
utilisateur n’est jamais une autorité suffisante.

Le manifeste d’un stage inventorie exactement les fichiers téléversés. La
vérification refuse tout fichier manquant, supplémentaire ou altéré, ainsi
qu’une dérive de stage, SHA, shard, checkpoint ou hash. Les plafonds durs sont
120 MB pour les sources, 5 MB pour census, tag/mask et atomic, 2 MB par shard
de paires, 16 MB pour les huit shards et 25 MB pour la réduction finale ; le
budget cumulé des téléchargements dérivés est 120 MB.

## Replay, reprise et sécurité

Chaque calcul est exécuté dans une namespace réseau `unshare --net`; si elle
n’est pas disponible, le workflow s’arrête. Les scripts ne reçoivent aucun
token et les compteurs provider, R2, SQL et Odds restent à zéro. Les actions
checkout/setup/download/upload sont épinglées par SHA.

Chaque stage est construit deux fois dans des répertoires frais et comparé par
hash avant upload. Une deadline logicielle de 240 secondes précède le timeout
dur de 270 secondes. Atomic et pair écrivent après chaque tag ou paire un
snapshot canonique gzip, alterné sur deux slots, puis publient atomiquement le
checkpoint qui référence exactement son hash et son curseur. Une reprise
refuse toute dérive de SHA, source, générateur, shard, checkpoint ou snapshot,
et reprend après le dernier bloc durable ; un shard complet n’est jamais
recalculé. Les paires exigent huit shards uniques et deux réductions fraîches
byte-identiques ; manque, duplication ou dérive du rapport global échoue
fail-closed.

La preuve locale sanitised `checkpoint-resume-proof-v1.json` lie une
interruption forcée après 17 paires au hash du checkpoint et du snapshot, puis
montre que la reprise ne recalcule aucun des 17 blocs déjà durables et produit
les mêmes hashes compact et gzip qu’un run propre. Le reducer possède sa
deadline coopérative propre, reconstruit le gzip détaillé exact à partir des
huit shards, vérifie son hash contre leur source commune et publie ensemble la
synthèse compacte et le full artifact.

Les triples, tout write distant, tout déploiement, toute publication et tout
pari réel restent hors contrat.
