# Robin Council OS V3.1 minimal

Ces instructions s'appliquent à tout le dépôt.

## Démarrage sûr

Avant toute mutation, exécuter et conserver la sortie de :

```text
git worktree list --porcelain
git branch -vv
git status --short --branch
git rev-parse HEAD
git remote -v
```

Le checkout `codex/hypothesis-universe-experience-v1` est une porte d'entrée
protégée. Depuis ce checkout, ne jamais modifier ou indexer un fichier, committer,
pousser, fusionner, rebaser, ni réaffecter le checkout avec `git switch` ou
`git checkout`. Préserver tout travail local. Créer un worktree séparé depuis la
ref distante exacte de la branche de base.

## Conseil et rédacteur unique

- C0 nomme exactement un rédacteur pour un worktree et une phase.
- Les autres agents restent en lecture seule et rendent le rapport défini par
  `configs/agents/agent-report-schema-v3.json`.
- L'auteur ne valide jamais seul son travail. Appliquer les doubles ou triples
  clés définies par `configs/agents/mission-activation-matrix-v3.json`.
- Les faits se tranchent par preuve, pas par vote. Les décisions importantes sont
  ajoutées à `reports/council/decision-ledger.jsonl`; ne jamais réécrire une ligne
  historique.
- Toute métrique présentée comme réelle référence un `claim_id` de
  `reports/evidence/evidence-graph.json`.

Avant chaque commit, ajouter au ledger : worktree, branche, HEAD, PR, rédacteur,
fichiers, tests ciblés et preuves réutilisées.

## Contrat minimal V3.1

Le Council est une politique de contrôle. Il valide et journalise une décision;
il ne planifie ni n'exécute le workload.

Une mission est définie par un manifeste immuable qui contient exactement :
`mission_id`, `authorized_stages`, `maximum_stage`, `external_effects`,
`compute_budget`, `time_budget`, `source_hash` et `expires_at`.

Les seuls états de décision sont :

```text
PASS_AND_SCALE
PASS_AND_HOLD
FAIL_AND_REDESIGN
FAIL_AND_STOP
BLOCKED_EXTERNAL_ACTION
```

La chaîne autorisée est `E1 → E2 → E3A → E3B → E4`. Une transition n'ouvre que
l'étape immédiatement suivante et uniquement si l'étape courante est prouvée,
les critères courants sont satisfaits, le plafond et le budget de mission sont
respectés, aucun veto critique n'est ouvert et aucun effet externe interdit
n'est demandé. Une source obligatoire absente produit `FAIL_AND_STOP`.

Après un premier échec similaire, appliquer le plus petit correctif et conserver
le niveau. Le deuxième impose `FAIL_AND_REDESIGN` et un retour à E1. La
troisième tentative identique est interdite et produit `FAIL_AND_STOP`.

Le journal append-only accepte seulement : `MISSION_AUTHORIZED`, `STAGE_STARTED`,
`STAGE_FINISHED`, `DECISION`, `FAILURE`, `VETO` et `REDESIGN`. Chaque record est
canonique, déterministe et lié au hash du record précédent. Il ne constitue ni
un ordonnanceur, ni un système de transaction distribuée.

Les capacités suivantes sont `FUTURE_DESIGN_NOT_IMPLEMENTED` : planification ou
exécution des workloads, transactions distribuées, rotation d'autorité complexe,
contrôleurs concurrents, réparation d'authority race, quarantaine post-commit,
reconstruction complexe des grants et remplacement de GitHub Actions, R2, Git ou
de l'orchestrateur Codex.

## Boucle obligatoire

Suivre dans l'ordre : observer, formaliser, construire le plus petit test,
mesurer, contredire, corriger, autoriser ou refuser la montée en charge, réaliser,
recetter, livrer.

Utiliser l'échelle et les délais de `configs/experiments/scale-policy-v3.json`.
La progression peut être automatique à l'intérieur du manifeste autorisé, mais
elle ne crée aucune autorité, n'élève jamais le plafond et ne déclenche aucun
effet externe.

## Calcul et données

- Réutiliser les manifests, receipts, hashes, datasets temporels et bundles
  compatibles avant tout calcul.
- Interdiction de rejouer intégralement un corpus pour tester un parser, une clé,
  une formule, un filtre, un graphique, un état vide, un timeout ou un workflow.
- Aucun nouveau replay `186 + 186`, census intégral, harvest Mega général, ni
  reconstruction des `2 023 144` lignes sans décision `SCALE_APPROVED` tracée.
- Par défaut `API_FOOTBALL_CALLS_ALLOWED=0`. Un appel de recensement éventuel
  exige une preuve source réellement absente, une décision C0/C1/C4, un plafond
  explicite et un receipt append-only.
- R2 conserve les payloads bruts immuables; PostgreSQL ne reçoit que des données
  structurées, index et agrégats. GitHub orchestre mais n'est jamais l'unique
  source durable d'une preuve.

## Tests proportionnés

- Simplification V3.1 : tests ciblés uniquement; une seule suite complète avant
  fusion.
- Micro-correctif : test ciblé, Golden Synthetic Pack, puis canari si nécessaire.
- Lot fonctionnel : suite du domaine.
- Commit important : tests du domaine, lint, typage et sécurité pertinents.
- Ne pas relancer la suite complète après chaque changement mineur.

## Sécurité immuable

Conserver :

```text
STORAGE_PAUSED=true
P3_P4_PAUSED=true
PRODUCTION_LOCKED=true
REAL_BETS=false
NO_BET_DEFAULT=true
PROMOTION_LOCKED=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Tout effet externe ou irréversible est `DEFAULT_DENY`. Sont interdits : achat,
secret exposé, suppression R2, écriture destructive, payload fournisseur brut
dans Git, pari réel, promotion, publication sociale et correction rétroactive
d'un résultat ou d'une source non auditée.

## Arrêt fail-closed

Rendre `PARTIAL` si une preuve source est réellement absente, si un achat est
requis, si une limite de plateforme bloque, si deux architectures ont échoué, si
le budget est atteint ou si un risque scientifique majeur reste ouvert. Ne jamais
masquer un blocage par une simulation ou une affirmation non sourcée.
