# Phase C Execution Contract V1

## État actuel

Les workflows 86–89 sont `workflow_dispatch` uniquement, read-only et
`cancel-in-progress=false`. Ils sont volontairement dormants :
`phase-c-execution-activation-v1.json` vaut
`HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH`, `allowed_execution_sha=null`, et le verrou
d’artefacts Phase C est vide. Aucun workflow Phase C n’a été déclenché dans
cette PR draft.

Une activation future doit être committée et revue sur la branche par défaut.
Le preflight lit l’autorité depuis un checkout `main` séparé, puis exige la
triple égalité : SHA de l’input, head distant de la branche et
`allowed_execution_sha`. Il valide ensuite les hashes du générateur, des
workflows et du verrou source. Le candidat ne peut jamais s’auto-autoriser.

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

## Replay, reprise et sécurité

Chaque calcul est exécuté dans une namespace réseau `unshare --net`; si elle
n’est pas disponible, le workflow s’arrête. Les scripts ne reçoivent aucun
token et les compteurs provider, R2, SQL et Odds restent à zéro. Les actions
checkout/setup/download/upload sont épinglées par SHA.

Chaque stage est construit deux fois dans des répertoires frais et comparé par
hash avant upload. Un checkpoint initial incomplet existe avant le calcul et
un checkpoint final référence le manifeste de stage. Une reprise refuse toute
dérive de SHA, source, générateur ou shard ; un shard marqué complet n’est pas
recalculé si son manifeste exact est présent. Les paires exigent huit shards
uniques ; manque, duplication ou dérive du rapport global échoue fail-closed.

Les triples, tout write distant, tout déploiement, toute publication et tout
pari réel restent hors contrat.
