# Next Mission Brief — P0 Capability Execution

## Configuration

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE VISIBLE = codex/hypothesis-universe-experience-v1
BRANCHE RÉELLE = codex/p0-capability-execution-launch-readiness-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

La mission commencera par revoir et fusionner la PR brouillon de prévol, puis
créera un worktree d'exécution depuis le nouveau `origin/main`. Le head de PR
doit être résolu sur GitHub au démarrage ; ne jamais le supposer depuis ce brief.

## Autorité

- source scientifique : `main@4d12da146602585a9df58b9db725a1c483d230d0` ;
- contrat Capability V2 :
  `aa6f60694b7bfe1684c6fcf0faf1bbbc6fa1bb9f1001f06fee999451d1d011e8` ;
- catalogue des grains :
  `5b2581e7d3a4630fd9d84be6ca954dc63cae83a602fce91d68c4847c5498cd71` ;
- inventaire fournisseurs :
  `f0b0f36d68c24692964868de3618c5a5c42b47d839f36bd6cb22a7c2ef65f18b` ;
- manifeste : `configs/execution/p0-capability-execution-manifest-v1.json` ;
- enveloppe Council à huit champs :
  `configs/execution/p0-capability-council-activation-v1.json` ;
- contrat de capacités :
  `configs/data/capability-scoped-evidence-ladder-v2.json`.

État immuable : `3036 = 2681 + 206 + 149`, cause exacte localement stoppée,
14 capacités non évaluées, aucune troisième architecture, aucun statut READY
implicite.

## Objectif

Exécuter progressivement E1B, E2, E3A et E3B sur les capacités admissibles,
recalculer les gates locales, puis, uniquement si un sous-espace fiable existe,
benchmarker les représentations de masques, construire les propriétés atomiques
et tester les paires compatibles.

L'enveloppe Council borne l'échelle de preuve à E3B (`E1B` est la campagne
capability-scoped du niveau Council `E1`). Les masques, propriétés et paires
restent contrôlés par le contrat détaillé et ne sont pas des `EvidenceStage`.

## Plafonds

- 50 heures ; jobs cible 10 min, maximum 15 min, checkpoint 5 min ;
- 10 000 GET R2 maximum et, après décision C0/DP5/A2 au ledger seulement,
  256 checkpoints/manifests compacts append-only ;
- 0 appel API-Football, 0 crédit de cotes ;
- 0 lecture/écriture SQL dans le manifeste courant ;
- un seul writer stateful, cinq lecteurs parallèles maximum ;
- deuxième échec similaire : redesign ; troisième tentative identique interdite.

E4 est conditionnel, jamais automatique. Triples, profondeur 4+, promotion,
pari réel, publication sociale et déploiement restent interdits.

## Terminé

Chaque niveau possède preuves, dénominateurs, UNKNOWN, grains, audit temporel,
checkpoint durable, reprise vérifiée, coût et décision par capacité. Les masques
et paires ne démarrent qu'après leurs gates. La recherche de triples reste
`TRIPLE_SEARCH_LOCKED` tant que les huit conditions gelées ne sont pas toutes
prouvées.

Le prompt complet directement copiable est `NEXT-MISSION-PROMPT.md`. Il est
préparé mais n'a pas été exécuté dans la mission de prévol.
