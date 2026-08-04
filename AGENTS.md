# Robin Council OS V3

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
- Toute métrique présentée comme réelle doit référencer un `claim_id` de
  `reports/evidence/evidence-graph.json`.

Avant chaque commit, ajouter au ledger : worktree, branche, HEAD, PR, rédacteur,
fichiers, tests ciblés et preuves réutilisées.

## Boucle obligatoire

Suivre dans l'ordre : observer, formaliser, construire le plus petit test,
mesurer, contredire, corriger, autoriser ou refuser la montée en charge, réaliser,
recetter, livrer.

Utiliser l'échelle et les délais de `configs/experiments/scale-policy-v3.json`.
Un correctif local commence à E0, puis au Canary Real Pack seulement si nécessaire.
Après deux échecs similaires : arrêter, analyser la cause, changer d'architecture
et revenir à E0 ou E1. Une troisième tentative identique est interdite.

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

## GitHub Actions et plateforme

- Séparer les groupes `historical-deep-manual`, `historical-deep-scheduled`,
  `prospective-live`, `cockpit-refresh`, `research-campaign` et `deployment`.
- Calculer les batches avant la matrice. Un job cible 15 minutes et ne dépasse
  jamais 20 minutes pour une nouvelle orchestration de cette mission.
- Deux tentatives automatiques au plus; rapport `always()` court; chaque
  annulation durable est journalisée.
- Toute limite non lue ou non mesurée vaut `UNKNOWN`.

## Tests proportionnés

- Micro-correctif : test ciblé, Golden Synthetic Pack, puis canari si nécessaire.
- Lot fonctionnel : suite du domaine.
- Commit important : tests du domaine, lint, typage et sécurité pertinents.
- PR prête ou fusion : suite complète, CI, red-team et recette.
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

Interdictions : achat, suppression R2, écriture destructive, payload fournisseur
brut dans Git, pari réel, promotion automatique, publication sociale, correction
rétroactive d'un résultat ou source non auditée.

## Arrêt fail-closed

Rendre `PARTIAL` si une preuve source est réellement absente, si un achat est
requis, si une limite de plateforme bloque, si deux architectures ont échoué, si
le budget est atteint ou si un risque scientifique majeur reste ouvert. Ne jamais
masquer un blocage par une simulation ou une affirmation non sourcée.
