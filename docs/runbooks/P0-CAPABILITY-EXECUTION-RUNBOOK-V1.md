# P0 Capability Execution Runbook V1

Ce runbook prépare la prochaine mission longue. Il n'autorise aucune exécution
dans la PR de prévol et ne transforme pas le dry-run synthétique en preuve
scientifique.

## Autorité gelée

- source : `main@4d12da146602585a9df58b9db725a1c483d230d0` ;
- contrat : `configs/data/capability-scoped-evidence-ladder-v2.json` ;
- manifeste futur : `configs/execution/p0-capability-execution-manifest-v1.json` ;
- enveloppe Council exacte :
  `configs/execution/p0-capability-council-activation-v1.json` ;
- campagne locale stoppée : `E1A_ABSENCE_CAUSE_CLASSIFICATION` ;
- invariant E1A : `3036 = 2681 + 206 + 149` ;
- `ABSENCE_CAUSE_UNKNOWN` reste une valeur de première classe ;
- les 14 capacités non évaluées restent `NOT_EVALUATED` ;
- aucun statut scientifique n'est modifié par ce prévol.

Avant tout futur workload, vérifier les trois hashes du manifeste sur les octets
exacts des fichiers. Un écart arrête la mission. La branche visible
`codex/hypothesis-universe-experience-v1` reste une porte d'entrée protégée ; le
travail s'effectue dans un worktree dédié à la branche réelle de mission.

## Préflight d'activation future

1. Résoudre le head distant exact, l'état des PR et les runs GitHub concurrents.
2. Vérifier le manifeste, son plafond, ses budgets et les verrous de sécurité.
3. Vérifier au runtime, sans afficher les secrets, la présence des accès requis.
4. Vérifier le manifeste R2 gelé par GET exact ; aucun LIST de préfixe brut.
5. Refuser tout receipt, payload, hash, grain ou identité manquant ou divergent.
6. Démarrer au dernier checkpoint durable compatible, sinon à `E1B`.
7. Journaliser la décision avant chaque changement de niveau.

Les faits de compte, quota, connectivité, pooler, taille réelle et disponibilité
non observables depuis Git restent `UNKNOWN_TO_BE_VERIFIED_AT_RUNTIME`.

## Progression par capacité

Pour chaque étape et chaque capacité, produire :

```text
capability_id, tested_scope, grain, expected, received, unknown, invalid,
coverage, temporal_class, status_before, status_after, scale_decision,
block_reason
```

Séquence automatique autorisée :

```text
E1B PASS_AND_SCALE -> E2
E2  PASS_AND_SCALE -> E3A
E3A PASS_AND_SCALE -> E3B
```

Une transition exige une preuve qualifiée pour au moins un sous-espace utile,
les dépendances satisfaites, l'absence de veto critique, le respect des budgets
et un checkpoint durable. Un échec bloque uniquement la capacité, ses enfants
déclarés et les croisements qui en dépendent. `ABSENCE_CAUSE_EXACT` ne bloque
jamais automatiquement `TEAM`, `LINEUP`, `FORMATION`, `CALENDAR` ou `FATIGUE`.

Après `E3B` :

- si un sous-espace fiable existe, passer au contrat `MASK_BENCHMARK` ;
- sinon, conclure `P0_CAPABILITY_PARTIAL` ;
- ne pas rendre E4 obligatoire ;
- proposer E4 dans un nouveau manifeste uniquement si une capacité utile reste
  indécidable et si sa fermeture P0 apporte une information nécessaire.

## Politique UNKNOWN

Chaque campagne choisit explicitement une politique parmi :

```text
CONFIRMED_ONLY
GENERIC_UNAVAILABILITY
EXCLUDE_UNKNOWN
INCLUDE_UNKNOWN_AS_UNKNOWN
SENSITIVITY_ANALYSIS
```

`UNKNOWN` ne devient jamais implicitement `false`, `0`, `injury` ou
`suspension`. Une réponse vide valide reste distincte d'une source absente et
d'un zéro observé.

## GitHub Actions future

Les contrats logiques attendus sont distincts ; aucun workflow lourd n'est créé
dans ce prévol.

| Contrat | Déclenchement | Groupe | Sortie durable |
|---|---|---|---|
| E1B | manuel | `p0-capability-manual` | checkpoint + gates E1B |
| E2 | manuel après E1B | `p0-capability-manual` | checkpoint + gates E2 |
| E3A/E3B | manuel après gate | `p0-capability-manual` | checkpoints par shard |
| masques | manuel | `hypothesis-mask-build` | contrat/benchmark puis masques |
| propriétés | manuel | `hypothesis-mask-build` | propriétés atomiques filtrées |
| paires | manuel | `hypothesis-pair-search` | paires compatibles auditées |

La mission manuelle ne partage aucun groupe avec cron, cockpit, backfill
historique général ou déploiement. Cible : 10 minutes par job ; maximum :
15 minutes ; checkpoint : 5 minutes. Tous les jobs writers utilisent le groupe
partagé `p0-capability-stateful-writer`. Les jobs de lecture peuvent être shardés
jusqu'au plafond du manifeste. GitHub peut remplacer un run encore pending :
l'intention, la source, le shard et le dernier checkpoint doivent donc être
committés avant le dispatch, puis résolus à nouveau au démarrage du runner.

Après un premier échec similaire : correctif minimal et maintien du niveau.
Après le deuxième : `REDESIGN_REQUIRED`. Une troisième tentative inchangée est
interdite. `GITHUB_RUN_ATTEMPT` ne constitue pas à lui seul l'identité métier ;
l'idempotency key inclut mission, stage, capacité, source et shard.

## R2 et Neon

R2 reste append-only et cache-first sous
`historical-deep-data/schema-v1/`. Le bootstrap futur lit uniquement la clé de
manifeste gelée, puis les receipts et payloads explicitement listés par ce
manifeste. Budgets : 10 000 GET maximum, 0 LIST global et 0 HEAD. Un plafond de
256 écritures est réservé exclusivement aux checkpoints/manifests JSON compacts
append-only sous `_derived/capability-execution/checkpoints/`. Les payloads bruts,
overwrites, copies et suppressions restent interdits. Avant le premier write,
une décision append-only C0/DP5/A2 doit être inscrite au ledger conformément à
la matrice d'activation ; sans cette décision, le budget effectif reste zéro.

Neon n'est pas requis pour E1B-E3B dans ce manifeste : budgets SQL lecture et
écriture à zéro. Si une mission ultérieure l'autorise, le mode attendu est
read-only via pooler pour les workers courts ; connexion directe uniquement pour
une migration explicitement autorisée. `statement_timeout`, `lock_timeout`,
taille de batch et plan d'exécution doivent être gelés avant la première requête.

## Masques, propriétés et paires

Le benchmark futur compare NumPy boolean arrays, Polars, DuckDB, PyArrow, Python
bitsets et RoaringBitmap sur temps de construction, intersection, union,
mémoire, taille sérialisée, rechargement, déterminisme et support d'UNKNOWN.
L'absence d'une bibliothèque installée est un résultat de compatibilité, pas une
autorisation d'ajouter une dépendance sans revue.

Le maximum théorique est de 486 propriétés et 117 855 paires avant filtres.
Éliminer avant calcul : contradiction logique, mauvaise entité, mauvaise
orientation, temporalité invalide, source ou marché absent, prix absent, support
nul, doublon canonique et dépendance bloquée.

`TRIPLE_SEARCH` reste verrouillé tant que les huit conditions du manifeste ne
sont pas toutes prouvées. Aucun triple, profondeur 4+, modèle, promotion, pari
ou publication ne fait partie de la prochaine mission.

## Validation et arrêt

À chaque niveau : tests ciblés, contrôle UTF-8/JSON, invariants de grain et
d'identité, audit temporel, checkpoint, revue indépendante, puis décision.
Arrêter sur hash divergent, preuve source manquante, fuite temporelle,
coercition d'UNKNOWN, identité dupliquée/ambiguë, budget dépassé, timeout,
veto critique, effet externe interdit ou troisième tentative inchangée.

Le dry-run local de cette PR est exclusivement
`MECHANICAL_PREFLIGHT_ONLY` : cinq ligues synthétiques, 10 fixtures E1B,
100 fixtures E2, une mini-saison E3A et une mini-saison multi-ligues E3B.
