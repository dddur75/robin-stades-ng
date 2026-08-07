# ROBIN DES STADES 2.0
# P0 E2 HUNDRED-FIXTURE CAPABILITY EVIDENCE V1
# REVUE ET FUSION E1B
# PROGRESSION LOCALE UNIQUEMENT
# ARRÊT AVANT E3A

---

# 0. CONFIGURATION

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
BRANCHE E1B À REVOIR = codex/p0-e1b-five-league-capability-canary-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Cette mission commence à E2. Ne pas réexécuter E1B si ses preuves, hashes et CI
sont encore valides.

---

# 1. OBJECTIF UNIQUE

1. revoir et fusionner la PR brouillon `P0 E1B Five-League Capability Canary V1` ;
2. vérifier le merge commit et la CI de `main` ;
3. créer une branche E2 depuis le nouveau `origin/main` ;
4. geler exactement 100 fixtures réelles par clés et hashes connus ;
5. mesurer uniquement les neuf capacités candidates E2 ;
6. recalculer les gates locales sans promotion globale ;
7. produire replay, coûts, contrats dashboard et handoff ;
8. s’arrêter avant E3A.

---

# 2. PREUVE D’ENTRÉE

Vérifier depuis GitHub et Git, sans supposer le head :

```text
E1B selection hash = 8e3ef9e5e44ef26ef4fd37d884b3290504f2b167b1fceeec669e0ed8684deb22
E1B successful run = 31177349967
E1B successful logical GETs = 21
E1B successful bytes = 1107479
E1B replay = BYTE_IDENTICAL
E1B decision = PASS_AND_HOLD
E2 executed = false
capability contract = configs/data/capability-scoped-evidence-ladder-v2.json
```

Préserver strictement :

```text
3036 = 2681 + 206 + 149
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
UNKNOWN reste UNKNOWN
0 READY_STRICT hérité
0 READY_RECONSTRUCTED hérité
```

Ne lancer ni E1A ni une troisième architecture. Ne pas rouvrir E1A ou
reclasser les 149 inconnues.

---

# 3. CHECKOUT PROTÉGÉ

Le checkout visible est une porte d’entrée uniquement. Ne jamais y modifier,
indexer, committer, pousser, fusionner, rebaser, nettoyer ou changer de branche.
Utiliser un worktree séparé pour la PR E1B puis pour E2.

Commencer par l’inventaire Git/worktrees et résoudre l’état réel de la PR sur
GitHub. Fusionner E1B uniquement si le head exact, la CI, les hashes, les coûts,
la portée scientifique et le diff restent sains. Conserver la branche distante.

---

# 4. CAPACITÉS E2 AUTORISÉES

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
PLAYER_STATISTICS
DISCIPLINE_GENERIC
CALENDAR
```

Ne pas faire progresser automatiquement :

```text
TEAM_FORM
PLAYER_FORM
STARTER_BASELINE
FATIGUE
STANDINGS
INJURY_CONFIRMED
SUSPENSION_CONFIRMED
ABSENCE_GENERIC
ABSENCE_CAUSE_EXACT
```

Une capacité bloquée n’arrête que ses dépendants déclarés. Une capacité non
testée reste `NOT_EVALUATED`. E2 ne peut pas transformer une mesure bornée en
readiness scientifique sans contrat explicite et preuve suffisante.

---

# 5. SÉLECTION DE 100 FIXTURES

Créer et committer avant toute lecture distante un manifeste déterministe avec :

```text
fixture_id
competition
season
kickoff_utc
home_team_id
away_team_id
allowed_r2_keys
payload_sha256
stored_sha256
receipt_hash
grain expectations
selection_reason
```

La sélection doit être équilibrée, temporellement défendable et entièrement
réconciliée avec l’inventaire. Comparer tous les champs contractuels, pas
seulement l’object_id. Faire relire le manifeste par DP6, C2 et DP5 avant GET.

---

# 6. ACCÈS ET SÉCURITÉ

```text
API_FOOTBALL_CALLS_ALLOWED = 0
ODDS_CREDITS_ALLOWED = 0
REMOTE_SQL_ALLOWED = 0
R2_LIST_ALLOWED = 0
R2_HEAD_ALLOWED = 0
R2_WRITES_ALLOWED = 0
R2_DELETES_ALLOWED = 0
DEPLOYMENT_ALLOWED = 0
PUBLICATION_ALLOWED = 0
REAL_BETS = false
PROMOTION_LOCKED = true
```

R2 est limité aux GET exacts du manifeste gelé. Aucun scan, fallback, payload
brut committé ou clé dynamique. Les coûts de chaque tentative sont conservés
séparément et cumulés dans le rapport de mission.

Plafonds de la mission longue :

```text
r2_read_budget = 10000 GET
r2_write_budget = 0
api_football_budget = 0
sql_read_budget = 0
sql_write_budget = 0
TRIPLE_SEARCH_LOCKED = true
```

Le budget d’écriture R2 reste zéro pendant toute cette mission. Ne jamais lancer
de triple.

---

# 7. MESURES ET UNKNOWN

Pour chaque capacité et partition, produire au minimum :

```text
grain
expected
received
empty_valid
unknown
invalid
unclassifiable
exact_duplicates
contradictory_duplicates
coverage_rate
content_presence_rate
normalization_integrity_rate
temporal_class
status_before
e2_measurement_status
block_reason
```

Les identités sont uniques à leur grain. Les taux globaux sont pondérés par les
dénominateurs, jamais moyennés simplement entre ligues. Un conteneur absent ne
devient ni liste vide valide, ni zéro. Les 149 inconnues E1A ne sont jamais
projetées dans les partitions E2.

---

# 8. REPLAY ET VALIDATION

Après les GET autorisés, conserver les objets uniquement en mémoire dans le job,
rejouer deux fois sans nouveau GET et exiger des rapports byte-identiques.

Ordre de validation : tests sélection/allow-list/budgets, Ruff, mypy strict,
JSON/YAML, secrets, `git diff --check`, mesure, agrégation pondérée, UNKNOWN,
dépendances, replay, contrat dashboard, suite de domaine, CI finale unique.

Maximum deux tentatives techniques. Après le second échec similaire :
`E2_TECHNICAL_PARTIAL` et arrêt.

---

# 9. ARRÊT OBLIGATOIRE

Ne pas exécuter E3A, E3B, E4, masques, propriétés, paires, triples, hypergraphe,
backtest, entraînement, déploiement ou publication.

Verdict final :

```text
PASS_AND_HOLD
```

ou :

```text
PARTIAL_AND_HOLD
```

La mission doit rendre une PR brouillon E2, non fusionnée, un worktree propre,
les preuves et coûts complets, puis préparer seulement la mission E3A suivante.
