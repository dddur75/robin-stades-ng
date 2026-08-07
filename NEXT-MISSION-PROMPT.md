# ROBIN DES STADES 2.0
# P0 CAPABILITY EXECUTION — VERY HIGH MISSION V1
# E1B → E2 → E3A → E3B
# MASQUES, PROPRIÉTÉS ET PAIRES SOUS GATES
# TRIPLES VERROUILLÉS

---

# 0. CONFIGURATION

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
BRANCHE RÉELLE DE PRÉVOL = codex/p0-capability-execution-launch-readiness-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Résoudre au démarrage l'état GitHub réel, le head exact de la PR de prévol et
son worktree. Ne jamais supposer que le head local est le head distant.

---

# 1. OBJECTIF UNIQUE

1. revoir et fusionner la PR `P0 Capability Execution Launch Readiness V1` ;
2. vérifier la CI du merge commit sur `main` ;
3. créer une branche d'exécution depuis le nouveau `origin/main` ;
4. exécuter E1B, E2, E3A et E3B par capacité, avec auto-progression bornée ;
5. recalculer les gates locales sans blocage global implicite ;
6. si un sous-espace fiable existe, benchmarker les masques ;
7. construire et tester les propriétés atomiques admissibles ;
8. tester les paires compatibles ;
9. conserver les triples verrouillés et produire un rapport final complet.

---

# 2. CHECKOUT PROTÉGÉ

Le checkout visible `codex/hypothesis-universe-experience-v1` est uniquement une
porte d'entrée. Ne jamais y modifier, indexer, committer, pousser, fusionner,
rebaser, nettoyer, ni utiliser `git switch` ou `git checkout`.

Commencer par :

```text
git worktree list --porcelain
git branch -vv
git status --short --branch
git rev-parse HEAD
git remote -v
```

Résoudre la PR de prévol depuis GitHub. La fusion doit utiliser un merge commit
et conserver la branche distante. Le travail d'exécution utilise un worktree
séparé depuis le nouveau `origin/main`.

---

# 3. HASHES ET ÉTAT SCIENTIFIQUE

Vérifier avant tout workload :

```text
source_main_sha = 4d12da146602585a9df58b9db725a1c483d230d0
capability_contract_hash = aa6f60694b7bfe1684c6fcf0faf1bbbc6fa1bb9f1001f06fee999451d1d011e8
grain_catalog_hash = 5b2581e7d3a4630fd9d84be6ca954dc63cae83a602fce91d68c4847c5498cd71
provider_inventory_hash = f0b0f36d68c24692964868de3618c5a5c42b47d839f36bd6cb22a7c2ef65f18b
```

Le `source_main_sha` est l'ancêtre scientifique gelé ; la PR de prévol ajoute
uniquement des contrats et tests. Tout hash de contrat différent arrête la
mission avant accès distant. Le contrat de capacités autoritatif est
`configs/data/capability-scoped-evidence-ladder-v2.json`.

Préserver strictement :

```text
E1A = Serie A 2024, 10 fixtures, 16 familles
3036 = 2681 blessures confirmées + 206 suspensions confirmées + 149 UNKNOWN
16/16 cellules techniques
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
14 capacités = NOT_EVALUATED
3 capacités = MEASURED_PARTIAL
0 capacité READY ou scale-authorized
```

Ne lancer ni E1A, ni troisième architecture. Ne pas reclasser les 149 cas. Le
stop reste local à la cause exacte.

---

# 4. MANIFESTE ET BUDGETS

Charger et valider :

```text
configs/execution/p0-capability-execution-manifest-v1.json
configs/execution/p0-capability-council-activation-v1.json
```

L'enveloppe Council contient exactement les huit champs V3.1, autorise
`E1/E2/E3A/E3B`, mappe E1B sur le niveau E1 et plafonne `maximum_stage=E3B`.
Vérifier son `source_hash` contre le manifeste détaillé et son expiration avant
tout workload. `MASK_BENCHMARK`, `ATOMIC_PROPERTIES` et `PAIR_SEARCH` sont des
phases détaillées post-E3B, pas des valeurs `EvidenceStage` du Council.

Plafonds :

```text
time_budget_hours = 50
target_minutes_per_job = 10
maximum_minutes_per_job = 15
checkpoint_interval <= 5 minutes
maximum_parallel_read_only_jobs = 5
maximum_stateful_writers = 1
r2_read_budget = 10000 GET
r2_write_budget = 256 compact checkpoints/manifests append-only
api_football_budget = 0
odds_credit_budget = 0
sql_read_budget = 0
sql_write_budget = 0
```

Les faits runtime de compte, secrets, quotas, objets et connectivité restent
`UNKNOWN_TO_BE_VERIFIED_AT_RUNTIME` jusqu'à un contrôle autorisé. Ne jamais
afficher une valeur de secret.

---

# 5. ÉTAPES ET AUTO-PROGRESSION

```text
E1B PASS_AND_SCALE -> E2
E2  PASS_AND_SCALE -> E3A
E3A PASS_AND_SCALE -> E3B
```

Chaque transition exige : preuve du niveau courant, dépendances satisfaites,
grain et temporalité valides, aucun veto critique, budgets respectés, source
hashée, et checkpoint durable. Après E3B :

```text
si sous-espace fiable -> MASK_BENCHMARK
sinon -> P0_CAPABILITY_PARTIAL
```

E4 n'est pas automatique. Il exige un nouveau manifeste si une capacité utile
reste indécidable et si sa fermeture P0 est nécessaire.

---

# 6. GATES PAR CAPACITÉ

Pour chaque étape et chaque capacité, produire :

```text
capability_id
tested_scope
grain
expected
received
unknown
invalid
coverage
temporal_class
status_before
status_after
scale_decision
block_reason
```

Valeurs de statut exclusivement :

```text
NOT_EVALUATED
MEASURED_PARTIAL
READY_STRICT
READY_RECONSTRUCTED
BLOCKED_BY_COVERAGE
BLOCKED_BY_TEMPORALITY
BLOCKED_BY_SOURCE
BLOCKED_BY_DEPENDENCY
STOPPED_LOCAL_CAMPAIGN
```

Un échec bloque seulement la capacité, ses enfants et ses croisements dépendants.
Une capacité indépendante continue. Une capacité non testée reste
`NOT_EVALUATED`.

---

# 7. UNKNOWN

Choisir explicitement pour chaque campagne :

```text
CONFIRMED_ONLY
GENERIC_UNAVAILABILITY
EXCLUDE_UNKNOWN
INCLUDE_UNKNOWN_AS_UNKNOWN
SENSITIVITY_ANALYSIS
```

Interdire toute coercition implicite de `UNKNOWN` vers false, zéro, blessure ou
suspension. Distinguer réponse vide valide, source absente et zéro observé.

---

# 8. GITHUB ACTIONS

Créer uniquement les petits workflows nécessaires, après revue de leurs
contrats. Groupes distincts :

```text
p0-capability-manual
p0-capability-scheduled
hypothesis-mask-build
hypothesis-pair-search
cockpit-refresh
deployment
```

La mission manuelle ne partage aucun groupe avec cron, cockpit, backfill général
ou déploiement. Tous les writers utilisent `p0-capability-stateful-writer`.
Comme GitHub peut remplacer un pending, committer l'intention et le dernier
checkpoint avant dispatch. `GITHUB_RUN_ATTEMPT` est journalisé. Premier échec similaire :
correctif minimal ; deuxième : `REDESIGN_REQUIRED` ; troisième inchangée :
interdite.

Contrôler les CI toutes les 10 à 15 minutes, pas chaque minute. Pendant une CI,
avancer sur un livrable indépendant ; ne pas modifier le code sans échec concret.

---

# 9. R2

Accès uniquement à partir du manifeste gelé : bootstrap par GET exact, puis
receipts et payloads explicitement listés. Interdire LIST brut/dérivé, HEAD,
COPY, multipart et suppression. Limites : 200 GET/job, 10 000 GET mission,
10 MiB stockés/job et 80 MiB logiques/job selon le contrat source. Seules 256
écritures de checkpoints/manifests JSON compacts append-only sont autorisées
sous `_derived/capability-execution/checkpoints/` ; aucun payload brut ni overwrite.
Avant le premier write, inscrire une décision append-only C0/DP5/A2 au ledger
selon la matrice d'activation. Sans cette décision, le budget effectif vaut zéro.

Tout receipt ou hash manquant échoue de manière fermée. R2 conserve la preuve
append-only et les checkpoints réels ; Git ne reçoit aucun payload brut.

---

# 10. NEON

Le manifeste courant autorise zéro SQL. Auditer le besoin avant toute évolution.
Si une requête devient indispensable, arrêter et produire un nouveau manifeste
avec tables, rôle read-only, pooler/direct, `statement_timeout`, `lock_timeout`,
batch et plan d'exécution gelés. Aucune migration ni écriture ne peut être
déduite de l'accès complet.

Tables candidates documentées, non autorisées par défaut :

```text
hypothesis_historical_evidence_summaries
hypothesis_evidence_artifact_indexes
historical_fixture_evidence_indexes
hypothesis_fixture_membership_indexes
coverage_gates
evidence_ledger
```

---

# 11. CHECKPOINTS ET REPRISE

Appliquer `docs/operations/P0-CAPABILITY-CHECKPOINT-AND-RESUME-V1.md`.
Chaque checkpoint contient au minimum :

```text
mission_id, stage, capability_scope, source_sha, dataset_hash, cursor,
objects_read, bytes_read, fixtures_processed, status, next_action
```

Il porte son hash et le hash précédent. Reprise obligatoire après annulation,
runner shutdown, timeout, CI retardée, artifact perdu, pending remplacé ou
redémarrage Codex. Les artefacts GitHub ne sont jamais la seule source durable.

---

# 12. MASQUES

Après E3B seulement, comparer sur E2 réel puis E3A réel :

```text
NumPy boolean arrays
Polars
DuckDB
PyArrow
Python bitsets
RoaringBitmap
```

Mesurer construction, intersection, union, mémoire, taille sérialisée,
rechargement, déterminisme et support d'UNKNOWN. Choisir sur preuves, sans ajouter
une dépendance ou augmenter le budget sans revue.

---

# 13. PROPRIÉTÉS ET PAIRES

Maximum théorique avant filtres : 486 propriétés et 117 855 paires. Éliminer
avant calcul : contradiction logique, mauvaise entité/orientation, temporalité
invalide, source/marché/prix absent, support nul, doublon canonique et dépendance
bloquée. Tester toutes les propriétés admissibles, puis les paires compatibles.

Checkpoint par shard, support et folds temporels obligatoires. Ne jamais lancer
de triple dans cette mission.

---

# 14. VERROU DES TRIPLES

`TRIPLE_SEARCH_LOCKED` jusqu'à preuve cumulative :

1. masques atomiques validés ;
2. prix historiques admissibles ;
3. support minimal gelé ;
4. folds temporels possibles ;
5. contrat statistique gelé ;
6. paires exécutées et auditées ;
7. budget de calcul approuvé ;
8. checkpointing prouvé.

Profondeur 4+, promotion, paris réels et publication sociale restent interdits.

---

# 15. TESTS ET REVUES

Pour chaque livrable : construction, tests ciblés, revue scientifique, revue
Git/CI, correction locale, revue finale. Maximum deux cycles de correction par
phase. Une seule suite complète avant fusion. Vérifier Ruff, mypy strict,
JSON/YAML, UTF-8/mojibake, secrets, hashes, grains, temporalité, identités,
UNKNOWN, idempotence, reprise et `git diff --check`.

Un seul rédacteur modifie un worktree. Les reviewers restent en lecture seule.
Ne créer aucun nouveau Council, orchestrateur ou moteur transactionnel.

---

# 16. SÉCURITÉ

Maintenir :

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

Interdire achat, secret exposé, suppression R2, écriture destructive, force-push,
pari, promotion, publication, déploiement et réécriture rétroactive d'une preuve.

---

# 17. DÉFINITION DE TERMINÉ

- PR de prévol revue, tests/CI verts, fusionnée et `main` vérifié ;
- E1B/E2/E3A/E3B exécutés seulement dans les budgets et par capacités ;
- dénominateurs, UNKNOWN, grains, temporalité, receipts et coûts traçables ;
- checkpoints et reprise prouvés ;
- E4 soit justifié par nouveau manifeste, soit non exécuté ;
- masques benchmarkés seulement après E3B fiable ;
- propriétés et paires filtrées, exécutées et auditées si leurs gates passent ;
- triples toujours verrouillés ;
- aucune action interdite ;
- branche poussée sans force, PR propre et rapport final livré.

---

# 18. RAPPORT FINAL

Rapporter Git/worktrees/PR/heads/CI, capacités et transitions par étape,
couvertures et UNKNOWN, checkpoints/reprises/idempotence, GitHub/R2/Neon et
inconnues runtime, benchmark des masques, propriétés/paires filtrées, état des
huit gates de triples, temps/mémoire/coûts/appels/lectures/écritures, sécurité et
une cause unique si blocage.

Ne demander aucune validation intermédiaire. Ne revenir vers David qu'avec le
rapport final ou un blocage externe réellement irréversible.
