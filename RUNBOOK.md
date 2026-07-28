# Runbook

## Jalon 5.1

Les restaurations historiques lisent `historical-data`; les publications
utilisent trois essais fetch/rebase/push. Ne jamais rediriger ces actions vers
`shadow-data`. En cas de quota, 429, erreurs > 5 %, temporalité critique ou
stockage ≥ 900 MB, conserver le checkpoint et arrêter proprement. Les quatre
fixtures de barrage L1 2025 restent auditables mais sont exclues de
`ligue1_2025_regular_season`.

## Deep Data Factory

Les opérations historiques sont décrites dans
`docs/operations/API-FOOTBALL-BACKFILL-RUNBOOK.md`. Les workflows 20 à 26
valident la couverture, reprennent le backfill, contrôlent la qualité,
recalculent features/modèles/backtests et reconstruisent le cockpit.

En replay, un checkpoint `COMPLETED` interdit tout nouvel appel fournisseur. Si
Neon échoue, `shadow-data` reste la source de reprise et la synchronisation
PostgreSQL est retentée sans perdre les payloads.

## Installation locale

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Référence CI : Python 3.12. Le mode doit rester `simulation` et
`real_bets_enabled: false` dans `config/runtime.yaml`.

## Validation complète

```powershell
.\.venv\Scripts\python.exe -m ruff check src/robin tests/jalon1 tests/jalon2 tests/jalon3 scripts migrations
.\.venv\Scripts\python.exe -m mypy src/robin
.\.venv\Scripts\python.exe -m bandit -q -r src/robin
.\.venv\Scripts\python.exe -m compileall -q agents moteur src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/check_no_secrets.py
```

## Base de données

PostgreSQL local, si Docker est disponible :

```powershell
docker compose up -d postgres
$env:ROBIN_DATABASE_URL = "postgresql+psycopg://robin:robin_local@localhost:5432/robin"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Une URL Neon native `postgresql://...` est acceptée directement et normalisée
centralement en `postgresql+psycopg://...`. Ne pas décoder ni reconstruire le mot
de passe ; les caractères spéciaux doivent rester encodés dans l’URL. Les
paramètres, notamment `sslmode=require`, sont conservés.

Les tests utilisent SQLite sans service payant. La CI démarre PostgreSQL 16 et
exécute `upgrade head`, puis `downgrade base`.

## Rapport qualité

```powershell
.\.venv\Scripts\python.exe -m robin.quality.report `
  --input data/matches.parquet `
  --output docs/data-quality
.\.venv\Scripts\python.exe scripts/build_jalon1_notebook.py
```

Artefacts attendus :

- `docs/data-quality/health.html` ;
- `docs/data-quality/quality-checks.json` ;
- `docs/data-quality/suspect-zero-audit.csv` ;
- `docs/data-quality/SUSPECT-ZERO-AUDIT.md` ;
- `notebooks/jalon1_data_quality.ipynb`.

Un statut `WARNING` garde la preuve visible ; un `FAILED` critique bloque le
jalon ou le pipeline.

## Ingestion brute

Chaque réponse est d'abord écrite via le stockage append-only, puis référencée par
une observation et un run idempotent. Ne jamais éditer un payload existant. Un
hash différent crée un nouvel objet ; un hash identique crée seulement une
nouvelle observation.

Les paramètres sont expurgés avant persistance. Ne jamais enregistrer ou afficher
une clé API dans les logs.

## Collecte prospective live

Commandes locales sans clé :

```powershell
.\.venv\Scripts\python.exe scripts/run_shadow_pipeline.py collect-fixtures --mock --output data/shadow-demo
.\.venv\Scripts\python.exe scripts/run_shadow_pipeline.py collect-odds --mock --output data/shadow-demo
.\.venv\Scripts\python.exe scripts/run_shadow_pipeline.py pre-match-shadow --mock --output data/shadow-demo
.\.venv\Scripts\python.exe scripts/run_shadow_pipeline.py post-match-settlement --mock --output data/shadow-demo
.\.venv\Scripts\python.exe scripts/run_shadow_pipeline.py daily-health --output data/shadow-demo
```

Les workflows canoniques sont `collect-fixtures.yml`, `collect-odds.yml`,
`pre-match-shadow.yml`, `post-match-settlement.yml` et `daily-health.yml`.
Le workflow `03_archive.yml` est désormais un diagnostic legacy manuel et
n'écrit plus dans Git. Un statut `WORKFLOW_SUCCESS_LIVE_DATA` exige au moins une
donnée réelle ; `WORKFLOW_SUCCESS_NO_DATA` reste une exécution saine sans sortie.

Chaque workflow restaure le dernier artifact `shadow-state-<run_id>`, exécute
son étape, puis publie un nouvel état. La concurrence globale `shadow-state`
sérialise les écritures. Deux copies sont conservées pendant 30 jours. Le cache
GitHub Actions n’est pas la persistance canonique.

## Diagnostic et reprise

1. télécharger l'artifact `shadow-state-<run_id>` et lire `runs/*.json` ;
2. distinguer `READY_NO_KEY`, `ABSENT` et une erreur réseau ;
3. conserver payloads bruts, ledger et identifiant de run ;
4. relancer manuellement le workflow avec les mêmes entrées ;
5. laisser l'idempotence empêcher les doublons ;
6. ne jamais réécrire snapshot, prédiction ou décision.

En cas de quota dépassé, arrêter les appels, conserver l'état du ledger et
attendre le renouvellement. Ne pas augmenter le plan sans décision documentée.

Pour une rotation de clé, remplacer uniquement le secret GitHub
`ODDS_API_KEY`, puis exécuter `collect-odds.yml` manuellement en mode diagnostic.
Ne jamais écrire la clé dans un fichier ou un log.

Pour désactiver un fournisseur, retirer ses marchés de `configs/shadow_v1.yaml`
ou désactiver le workflow concerné ; conserver ses payloads et mappings.

## Restauration et rollback

- restaurer la base via Alembic vers la révision précédente ;
- restaurer fichiers analytiques et ledgers depuis un artefact GitHub ;
- ne pas supprimer les payloads bruts ;
- si une normalisation est erronée, produire une nouvelle version et rejouer ;
- le rollback ne déverrouille jamais les paris réels.

## Cockpit V1

```powershell
.\.venv\Scripts\python.exe scripts/build_cockpit_snapshot.py
cd cockpit
pnpm install --frozen-lockfile
pnpm test
pnpm dev
```

Ouvrir `http://localhost:3000`. Le cockpit charge la preuve live compacte par
défaut. Les badges `LIVE SOURCE`, `LEGACY SOURCE`, `DEMO DATA` et `NO OUTPUT`
sont contractuels. La démo reste opt-in et ne doit jamais remplacer une absence
de donnée prospective.

## Incident et reprise

1. conserver payloads, manifestes, logs et identifiant du run ;
2. ne pas masquer l'erreur ;
3. reprendre depuis la dernière étape transactionnelle réussie ;
4. rejouer avec la même clé d'idempotence ;
5. versionner toute correction tardive ;
6. ne jamais réécrire une cote, une prédiction ou un résultat historique.

## Jalon 4 — registre durable et burn-in

Vérifier la branche de données :

```powershell
python scripts/manage_durable_registry.py verify --registry <checkout-shadow-data>
python scripts/manage_durable_registry.py replay --registry <checkout-shadow-data> --destination <replay>
```

Le replay n’appelle aucun fournisseur. Avec `DATABASE_URL`, les workflows
publient d’abord le bundle dans `shadow-data`, appliquent Alembic, synchronisent
l’intégralité du registre vers PostgreSQL, auditent les deux copies, puis
émettent l’acquittement `POSTGRESQL_AND_GIT_DATA_BRIDGE`.

Bootstrap ou rattrapage contrôlé :

```powershell
.\.venv\Scripts\python.exe scripts/neon_bootstrap.py `
  --registry <checkout-shadow-data> `
  --report <rapport-json> `
  --controlled-rollback
```

Le rollback contrôlé ne s’exécute que si toutes les tables applicatives sont
vides. Dès qu’une donnée est présente, aucun downgrade destructif ne doit être
tenté. En cas d’indisponibilité PostgreSQL, le bundle déjà poussé reste durable,
un incident `POSTGRESQL_WRITE_FAILED` est ouvert une seule fois et le prochain
workflow rejoue automatiquement tout le registre sans rappel fournisseur.

Pour une fenêtre manquée, ne relancer que `MISSED_RECOVERABLE` pendant la marge
de 120 minutes. Un diagnostic hors fenêtre ne doit pas modifier la couverture.
Voir `docs/operations/MISSED-WINDOW-RECOVERY.md`.

Les rapports automatiques sont `reports/daily.md`, `reports/weekly.md` et
`reports/matchday.md`. Un incident critique persistant peut produire une seule
issue GitHub ; une absence de marché normale ne doit jamais en produire.

## Cockpit Live V2

```powershell
python scripts/build_cockpit_snapshot.py
pnpm --dir cockpit test
```

Le mode démo est désactivé par défaut. Toujours conserver
`PRODUCTION_LOCKED` et le message d’échantillon insuffisant.

### Activation post-fusion Jalon 5

Avant un lot, vérifier quota, réserve de 5 000 appels, stockage inférieur à
900 MB, migration `0004`, qualité temporelle et accessibilité de
`historical-data`. Laisser `max_calls=0` et `max_tasks=0` pour que le
planificateur adapte le lot.

Après un lot :

```powershell
python scripts/run_historical_pipeline.py repair-provenance
python scripts/run_historical_pipeline.py quality
python scripts/run_historical_pipeline.py forecast
```

Ces commandes n'appellent pas le fournisseur. La réparation rattache les lignes
Parquet aux payloads bruts immuables, puis la qualité bloque les features
concernées en cas de hash, pagination, identité, temporalité ou cardinalité
incohérente.

Le workflow Cockpit doit distinguer :

- `COCKPIT_BUILD_SUCCESS` ;
- `COCKPIT_ARTIFACT_PUBLISHED` ;
- `COCKPIT_PRIVATE_DEPLOYED`.

Un artefact GitHub n'est jamais présenté comme un déploiement privé. Le snapshot
frontend reste statique et nettoyé ; Neon et les secrets ne sont jamais
accessibles au navigateur.

### Forecast complet et tâches latentes

Après chaque lot :

```powershell
python scripts/run_historical_pipeline.py forecast
```

Vérifier séparément :

- `materialized_tasks_remaining` et `materialized_calls_remaining` ;
- `latent_fixture_tasks` ;
- `latent_team_tasks` ;
- `latent_player_pages` ;
- `calls_remaining_low/base/high` ;
- `storage_projected_low/base/high`.

Une ETA `MATERIALIZED_TASKS_ONLY` n’est jamais utilisée comme ETA complète.
Les scénarios doivent converger lors de l’expansion d’un parent sans tomber
artificiellement à zéro.

Ne pas augmenter la cadence si le scénario haut approche 750 MB, si une erreur
temporelle apparaît, si le taux d’erreur atteint 1 %, si un HTTP 429 survient
ou si le live attend `historical-state`.

### Fraîcheur du Cockpit privé

Comparer `currentBackfillRunId` à `deployedBackfillRunId` et
`currentDataHash` au hash de données déployé. Un écart de run ou de hash impose
`COCKPIT_PRIVATE_STALE`. GitHub Actions continue à publier l’artefact ; il ne
prétend pas déployer Sites. La version privée existante et son accès
propriétaire sont conservés.

Le run de référence Jalon 5.2 est `30154099512`. Après restauration et avant
publication, exécuter `repair-provenance`, `quality`, `forecast`, puis le build
du Cockpit. Les valeurs attendues à cette preuve sont 41 672 lignes de
provenance, 0 ligne non résolue et la révision Neon `0004`.

## Chaîne Jalon 6 sans fournisseur

Après restauration de `historical-data` :

1. `repair-provenance`, `quality`, puis `readiness` ;
2. `datasets` si les gates l'autorisent ;
3. `model-lab` si `api_team_pre_match_v1` existe ;
4. `strategy-lab` si des prédictions OOS existent ;
5. `persist`, compactage, append durable et Cockpit.

Ces commandes ont `provider_calls=0`. Un gate bloqué produit un statut explicite
et ne doit jamais être contourné. La cadence backfill reste inchangée et le
verrou `historical-state` empêche deux runs simultanés.

## Jalon 7

Après restauration de `historical-data` :

```bash
python scripts/run_historical_pipeline.py --max-calls 0 scientific-arena
python scripts/run_historical_pipeline.py --max-calls 0 strategy-lab-v2
python scripts/build_cockpit_snapshot.py
```

Le second passage de `scientific-arena` doit retourner `execution_status=CACHED`.
Ne jamais contourner `storage.status=PAUSED`, modifier le gel Jalon 6 ou
relancer un fournisseur pour cette chaîne. Les workflows 24 et 25 partagent
`historical-state`; le live reste sur `shadow-state`.
## Validation externe multi-ligues

Le workflow `27 - Validation externe multi-ligues` restaure `historical-data`,
verrouille ou vérifie le protocole V1, recalcule les gates, construit seulement
les datasets autorisés puis exécute les évaluations sans fournisseur :

```bash
python scripts/run_external_validation.py \
  --state data/historical \
  --run-id "$GITHUB_RUN_ID" \
  --source-commit "$GITHUB_SHA"
```

Ne jamais supprimer le protocole verrouillé pour changer des paramètres. Une
définition différente doit devenir une version exploratoire distincte. À
750 MB, arrêter les artefacts secondaires et compacter. À 900 MB, le workflow
doit rester en pause. Les statuts `WAITING_FOR_EXTERNAL_GATES` et
`NO_EXTERNAL_VALIDATED_EDGE` sont normaux.

## Jalon 9

Ne jamais lancer un second backfill si `historical-state` est actif. Pour la
fermeture critique, utiliser `27 - Backfill des gates critiques`; l’ordonnanceur
reste responsable du budget et de la réserve. L’ingestion marché utilise
`28 - Ingestion marchés historiques`; le replay qualité utilise les archives et
zéro fournisseur.

À `OBJECT_STORAGE_REQUIRED`, suspendre P3/P4 et exécuter d’abord le workflow R2
en dry-run. Suivre `docs/operations/R2-MIGRATION-RUNBOOK.md`.

Le Jalon 9.1 distingue conservation des sources, réplication continue et
restauration. `double_write=true` dans un ancien rapport ne prouve que
l'absence de mutation pendant le lot. Les migrations longues utilisent le
workflow 30 avec scope, curseur et checkpoint; le workflow 31 restaure un
échantillon multi-format dans un dossier temporaire. Les workflows historiques
normaux répliquent uniquement leur delta et laissent Git/Neon disponibles si
R2 est momentanément indisponible.

Avant fusion de la PR #12, utiliser sur la branche de la PR le workflow 22
comme façade compatible avec la branche par défaut : une borne strictement
supérieure à 250 lance la migration reprenable par sous-lots de 1 000; une
borne négative lance l'audit sans écriture. Réserver le workflow 30 natif aux
exécutions post-fusion, lorsqu'il sera présent sur la branche par défaut. Ne
jamais lancer deux modes spéciaux simultanément.

Si `repair-provenance` retourne
`HISTORICAL_PROVENANCE_REPAIR_INCOMPLETE`, ne pas ignorer l'incident et ne pas
relancer le fournisseur. La persistance doit s'exécuter avec `always()` avant
le verdict terminal afin de conserver le lot dans Git/Neon et le pont R2. Le
workflow publie ensuite l'échec de provenance. Cette séquence est obligatoire
avant fusion de la PR #12.

Pour fermer le gate live sans appel fournisseur, lancer `14 - Sante quotidienne
shadow` sur la branche de la PR. Exiger `POSTGRESQL_HEALTHY`, la révision
Alembic attendue, `bridge_lag_records=0`, `provider_calls=0`,
`quota_consumed=0` et `PRODUCTION_LOCKED`.

Preuve Jalon 9.1 : migration complète en six runs, audit
`AUDIT_COMPLETE_VERIFIED` dans `30239697041`, restauration
`RESTORE_VERIFIED` dans `30203249310`, réplication `SYNCED` et lag nul dans
`30238268175`. L'audit a repris après un delta de readiness sans réinitialiser
son curseur et n'a exécuté aucun `PutObject`.

## Politique de stockage post-fusion

À partir de 900 MB, maintenir `STORAGE_PAUSED` même si le miroir R2 est
`SYNCED`. Autoriser uniquement l'historique critique nécessaire aux gates.
Différer P3/P4, les tâches secondaires et toute collecte massive. R2 reste un
miroir vérifié; `historical-data` demeure la source principale.

Ne reprendre les tâches secondaires qu'après une décision d'architecture
séparée réduisant réellement la dépendance au stockage Git. Cette évolution
doit appartenir à un jalon ultérieur distinct et ne fait pas partie de la
validation post-fusion du Jalon 9.

## Jalon 10 — recherche cache-only et ledger

Prérequis : restaurer l’historique durable sans l’écrire dans Git, vérifier
`STORAGE_PAUSED`, conserver P3/P4 suspendus et ne fournir aucune variable de
secret fournisseur au job de recherche.

Exécution locale bornée :

```powershell
.\.venv\Scripts\python.exe scripts/run_pattern_campaign.py `
  --state data/historical `
  --output data/pattern-research/run.json `
  --code-revision (git rev-parse HEAD)

.\.venv\Scripts\python.exe scripts/run_pattern_campaign.py `
  --state data/historical `
  --output data/pattern-research/replay.json `
  --code-revision (git rev-parse HEAD) `
  --replay
```

Comparer configuration, hash du dataset, règles, sélections, métriques et hash
stable. Le replay doit consommer zéro appel et zéro crédit. Un run GitHub vert
sans hypothèse exécutée n’est pas une preuve.

Avant toute promotion, exiger le contrat
`docs/pattern-research/SCIENTIFIC-CONTRACT.md`, la politique temporelle, FDR,
bootstrap, walk-forward, contrôles négatifs et rapport de concentration. Les
prix `SOURCE_PRICE_CLASS_ONLY` ferment le gate live ; ne pas le contourner.

Les workflows séparés sont `pattern-discovery.yml`,
`pattern-validation.yml`, `shadow-pattern-decisions.yml`,
`pattern-settlement.yml` et `public-ledger-build.yml`. Ils ne doivent pas
prendre le verrou `historical-state`, écrire dans `historical-data`, lancer un
fournisseur ou réactiver P3/P4.

Pour le ledger :

1. vérifier la chaîne avant toute génération publique ;
2. figer la décision avant kickoff ;
3. ajouter le règlement sans modifier la décision ;
4. refuser un identifiant rejoué avec un contenu différent ;
5. afficher `NO_BET_DATA_UNAVAILABLE` si le point-in-time manque ;
6. conserver `simulation=true`, `REAL_BETS=false` et la bankroll fictive.

Une incohérence de hash bloque Robin Live. Un artifact construit n’est pas
qualifié de déploiement privé. Les exports sociaux peuvent être construits,
mais `SOCIAL_PUBLISHING_ENABLED=false` interdit tout envoi externe.

## Jalon 11 — Deep Football

Le moteur démarre toujours en cache-only :

```powershell
$out = Join-Path $env:TEMP "robin-jalon11"
.\.venv\Scripts\python.exe scripts\run_deep_football.py all `
  --state data\historical `
  --output $out `
  --source-commit (git rev-parse historical-data) `
  --main-commit (git rev-parse HEAD) `
  --main-ci-run-id <RUN_ID>
```

Le replay utilise exactement le même répertoire et doit reproduire le hash :

```powershell
.\.venv\Scripts\python.exe scripts\run_deep_football.py all `
  --state data\historical `
  --output $out `
  --source-commit (git rev-parse historical-data) `
  --main-commit (git rev-parse HEAD) `
  --main-ci-run-id <RUN_ID> `
  --replay
```

Avant exécution, confirmer :

```text
API_FOOTBALL_CALLS_ALLOWED=0
ODDS_API_CREDITS_ALLOWED=0
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Dans les rapports JSON, le verrou `P3/P4_PAUSED` est sérialisé sous
`P3_P4_PAUSED=true`.

Vérifier ensuite `dataset-manifest.json`, `campaign-11a-summary.json`,
`red-team-report.json`, `replay.json`, `prospective-watchlist.json`,
`shadow-candidate-decision.json` et `ledger-audit.json`. Un replay valide exige
le même hash, zéro doublon, zéro perte, zéro mismatch, zéro appel et zéro
crédit.

Ne jamais exécuter une campagne joueurs, absence, lineup, formation ou pied
fort si son gate n'est pas `READY`. Une couverture de contenu post-match ne
ferme pas un gate pré-match. Les sorties lourdes vont vers R2/PostgreSQL ; Git
ne conserve que contrats, rapports compacts, hashes et checkpoints.

`TEAM_GATE=PARTIAL` autorise uniquement `DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC`.
Le test principal est la multinomiale marché + équipe contre le marché
recalibré train-only. Il relève de l'amendement correctif
`1.0.0-amendment-1`, enregistré après les diagnostics team-only et avant le run
autoritatif ; ne jamais le qualifier de préenregistré ni de promouvable. Son
hash est
`37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa`.
Les quatre challengers team-only, le gradient boosting incrémental et les cinq
rotations 11F restent descriptifs et non promouvables. 11E peut terminer comme
évaluation de gates même lorsque ses huit hypothèses sont bloquées.

Le snapshot preflight conserve historiquement la révision `0007`. Le run
opérationnel `30282406035` a ensuite vérifié l'upgrade Neon live vers
`0008_jalon11_deep_football` : 304 preuves examinées deux fois, 0 insertion et
304 doublons évités à chaque passage, avec six équivalences numériques legacy.
Le même run a vérifié 25 453 objets R2, un upload du Parquet de 2 000 155
octets, lag 0, aucune suppression et aucune mutation. La source est
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`.

Pour auditer ce run, exiger le hash campagne
`437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355`,
la tête ledger
`90bd34d99a689553246ce3b57ea344d751fb1f948cdc048661d6c2e0b22b92a8`
et `REPLAY_FULL_HASH_VERIFIED`.

Lorsque seuls les rapports Jalon 11 sont disponibles, rafraîchir uniquement le
volet Matchup du Cockpit afin de préserver les autres preuves :

```powershell
$env:COCKPIT_MATCHUP_ONLY = "1"
python scripts/build_cockpit_snapshot.py
```

Sous un shell POSIX, l'équivalent est :

```bash
COCKPIT_MATCHUP_ONLY=1 python scripts/build_cockpit_snapshot.py
```

Le gate de décision shadow exige un candidat et un prix live avec
`observed_at` exact. À défaut, le résultat normal est
`NO_DECISION_NO_CANDIDATE`, avec 0 unité mise et une bankroll inchangée.

### Audit de revue finale Jalon 11

Conserver `30282406035` comme preuve initiale. Pour la revue finale, exiger :

- run `30290942945`, commit
  `31ec41632b72cd93676f5b1d8592e1bba429e937`, six jobs verts ;
- CI push `30290942423` et CI PR `30290944657` vertes ;
- ledger `HASH_CHAIN_VERIFIED`, 27 événements, tête
  `7f52801f6a4fee8786df0fd71c1f5af3d26dbed31168ebe1e422ba387ccd3ddf` ;
- replay `REPLAY_FULL_HASH_VERIFIED`, quatre comparaisons vraies et tous les
  compteurs fournisseur, doublon, perte et mismatch à zéro ;
- PostgreSQL `0008`, deux passages de 304 preuves et 304 doublons évités ;
- R2 25 453 / 25 453, lag 0, aucune suppression ni mutation.

Pour rafraîchir Robin Live depuis un artefact de validation, définir en plus
`JALON11_REPORT_ROOT` vers sa racine. Toujours conserver
`COCKPIT_MATCHUP_ONLY=1` afin de ne modifier que `generatedAt` et `matchupLab`.

## Jalon 12 — Observatoire prospectif

Politique : `configs/prospective_observatory_v1.json`. Migration :
`0009_jalon12_observatory`. Verrou :
`prospective-deep-state`.

Politique temporelle active : `prospective-capture-window-v2`, Option B.
`H-2` couvre `[H-3,H-1)` et `NEAR_KICKOFF` couvre `[H-1,kickoff)`. Pour neuf
fixtures, 441 fenêtres v2 sont actives ; les 531 fenêtres v1 du pilote restent
append-only mais inactives.

Ordre d’exploitation :

1. `prospective-fixture-registry.yml` enregistre les fixtures officielles ;
2. `prospective-deep-scheduler.yml` publie les fenêtres dues et le budget ;
3. les workflows player, lineup et odds capturent uniquement les fenêtres dues ;
4. player et lineup vérifient une fois le kickoff et `status.short=NS` de
   chaque fixture due ;
5. le budget maximal est journalisé append-only dans R2 avant transport ;
6. R2 reçoit le payload brut append-only et son reçu hashé ;
7. PostgreSQL indexe et projette sans corps de payload ;
8. la parité bidirectionnelle reçus/index/budgets est vérifiée ;
9. `prospective-r2-replay-audit.yml` rejoue sans fournisseur ;
10. `prospective-gate-report.yml` produit le rapport compact et Robin Live.

CLI canonique :

```powershell
python scripts/run_prospective_observatory.py fixture-registry --help
python scripts/run_prospective_observatory.py scheduler --help
python scripts/run_prospective_observatory.py capture-player --help
python scripts/run_prospective_observatory.py capture-lineup --help
python scripts/run_prospective_observatory.py capture-odds --help
python scripts/run_prospective_observatory.py replay-audit --help
python scripts/run_prospective_observatory.py gate-report --help
python scripts/run_prospective_observatory.py next-due-report --help
```

`windows_due=0` doit terminer avec `NO_DUE_WINDOW_SUCCESS`,
`provider_calls=0`, `odds_api_credits=0`, `r2_puts=0` et
`capture_attempts=0`. Le preflight kickoff est alors interdit. Une fenêtre
dépassée devient `MISSED_WINDOW`; un retry tardif reste `LATE_RETRY` et ne
ferme pas le cutoff.

`r2_puts` mesure seulement la capture courante. Si une intention antérieure
répare un payload ou reçu manquant, publier ces écritures dans
`recovery_r2_puts` sans changer `provider_calls=0`.

Relire l’horloge avant le preflight, avant chaque transport et à réception.
Avant transport, un cutoff franchi produit
`WINDOW_CUTOFF_PASSED_BEFORE_PROVIDER_CALL` sans coût. À réception, il produit
`TEMPORALITY_FAILED`. Le replay exige aussi
`opens_at <= response_received_at < cutoff_at < kickoff_at`.

`CAPTURED_EMPTY` sur `INJURY` peut faire passer le gate avec
`NO_INJURY_REPORTED_AT_CAPTURE`; cette preuve signifie seulement « rien de
rapporté par le fournisseur à cet instant », jamais zéro ni absence certaine.

`next-due-report` est une estimation provider-free. Sa sortie canonique est
`reports/jalon12/next-due-windows.json` ; elle liste pour chaque fixture et
famille la prochaine fenêtre UTC, le workflow, le coût maximal et l’état
attendu.

Rafraîchissement cockpit borné :

```powershell
$env:COCKPIT_PROSPECTIVE_ONLY = "1"
$env:PROSPECTIVE_REPORT_ROOT = "<répertoire de rapports compacts>"
python scripts/build_cockpit_snapshot.py
pnpm --dir cockpit test
```

Le builder refuse toute source sans `PRODUCTION_LOCKED`, avec pari réel,
publication sociale, démo active ou décision non nulle. Voir
`docs/prospective-observatory/OBSERVATORY-OPERATIONS.md`.

### Validation pré-fusion sans fournisseur

Le pont CI de la branche Jalon 12 accepte deux modes mutuellement exclusifs :

- `[run-j12-pilot]` autorise le pilote borné après la CI ;
- `[run-j12-replay-only]` migre Neon, rejoue tout R2, recalcule les gates et
  teste Robin Live, avec les credentials fournisseur vidés et les plafonds
  d’appel à zéro.

Un commit contenant les deux marqueurs échoue avant toute étape réseau. En
mode replay-only, vérifier dans le run GitHub que les étapes registre,
scheduler et captures sont toutes `skipped`. Ne jamais utiliser le replay-only
pour simuler une capture : il ne fait que reconstruire l’état déjà durable.

Avant toute sélection due, le replay réconcilie R2 vers PostgreSQL. Les reçus,
index payloads et clés du journal budget doivent être identiques des deux
côtés ; une ligne orpheline produit `R2_POSTGRESQL_*_PARITY_FAILED`.
Comparer également l’ensemble exact des lignes de
`prospective_player_status`, `prospective_injuries`, `prospective_lineups`,
`prospective_formations` et `prospective_odds_snapshots`. Une ligne
supplémentaire, absente ou mutée produit
`R2_POSTGRESQL_PROJECTION_PARITY_FAILED:<table>`.

Le seeding budget legacy est ligne-par-ligne et idempotent : compléter les clés
SQL absentes de R2 même si le namespace est partiellement rempli, reprojeter
R2 vers SQL, puis comparer toutes les valeurs.
Le statut complet exact est :

```text
R2_REPLAY_VERIFIED
CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2
```

Une fixture non reconstruite donne
`R2_REPLAY_PARTIAL_FIXTURE_INDEX` / `RECONSTRUCTION_INCOMPLETE`.
Tester les reprises après intention seule, payload sans reçu, reçu sans
PostgreSQL, projection partielle et timeout après index, puis un replay complet
et un replay répété. Aucun de ces chemins ne rappelle un fournisseur.

Dans le ledger, `physical_capture_id` inclut la fixture pour API-Football mais
la neutralise pour la réponse Odds globale. Contrôler séparément
`physical_capture_events`, `physical_http_calls`, reçus et preuves temporelles
par fixture.

Preuve de référence finale : run `30314975830`, commit `2469e57`, 18 objets R2
examinés pour 24 714 octets physiques, 9 payloads rejoués, 0 appel fournisseur,
0 crédit, 0 mismatch, 0 perte et 0 suppression. L’artefact Cockpit doit
afficher PostgreSQL `0009`, 12 tables, 54 écritures compactes, 9 doublons
évités, lag 0 et zéro corps de payload. Son SHA-256 attendu est
`f0ff76b0c476ef259eb73143f969a75f3c6904786e1d073ce9874c1cbd776f53`.

Cette preuve appartient au pilote v1. La PR #17 reste non fusionnée tant que
la revue 12.1 n’a pas sa propre suite verte ; les cron de branche ne prouvent
pas une activation sur `main`. P0 reste Ligue 1, P1 reste `P1_OFF`, et
`PRODUCTION_LOCKED`, `REAL_BETS=false`, `NO_BET_DEFAULT=true` restent
obligatoires.

## Robin Experience V1 — validation sans fournisseur

Tous les contrôles suivants sont locaux et ne doivent recevoir aucun secret
fournisseur :

```powershell
cd cockpit
pnpm install --frozen-lockfile
pnpm run lint
pnpm test
pnpm run test:visual
```

`pnpm test` compile le build de production puis exécute les tests SSR et i18n.
`pnpm run test:visual` démarre un serveur local sur `127.0.0.1:4173`, utilise
Chromium avec mouvements réduits et écrit les captures dans
`cockpit/.ci/visual-regression`. Ce dossier est ignoré par Git.

Pour une vérification manuelle :

```powershell
cd cockpit
pnpm run dev
```

Contrôler `/robin-live`, les filtres de `/matchs`, les neuf onglets d’une fiche,
la matrice mobile de `/observatoire`, les huit hypothèses de `/laboratoire`,
l’état vide de `/resultats`, le glossaire et la Vue expert.

Résolutions obligatoires :

```text
360 × 800
390 × 844
430 × 932
768 × 1024
1440 × 900
1920 × 1080
```

Le test visuel doit échouer en cas de débordement horizontal, de route sans
titre français, de Vue expert inactive, de glossaire inaccessible ou de focus
d’évitement absent.

Ne jamais utiliser cette validation pour déclencher :

- API-Football ou The Odds API ;
- une capture ou un workflow prospectif ;
- une écriture R2 ou PostgreSQL distante ;
- une décision, une mise ou une publication sociale.

Les preuves scientifiques demeurent dans `cockpit/app/cockpit-data.json` et son
empreinte. Les ajustements UX appartiennent aux catalogues, au modèle de
présentation et aux composants.

## Robin Experience V1.1 — reconstruction provider-free

Pour reconstruire le cockpit depuis un snapshot vérifié déjà téléchargé :

```powershell
$env:COCKPIT_VERIFIED_SNAPSHOT_INPUT = "<chemin vers cockpit-data.json>"
$env:COCKPIT_VERIFIED_SNAPSHOT_SHA256 = "<sha256 attendu>"
$env:COCKPIT_SOURCE_RUN = "<run GitHub>"
$env:COCKPIT_SOURCE_REVISION = "<commit source>"
$env:COCKPIT_SOURCE_WORKFLOW = "<workflow source>"
python scripts/build_cockpit_snapshot.py
cd cockpit
pnpm run build:data
pnpm test
pnpm run test:visual
```

Le builder refuse une empreinte différente, une production déverrouillée, un
pari réel, une publication sociale ou une décision non nulle non autorisée.
Cette commande ne doit jamais recevoir de credential fournisseur ou de
stockage distant.

Contrôles de livraison V1.1 :

```powershell
python -m pytest -q
python -m ruff check src/robin tests scripts migrations
python -m mypy src/robin scripts/run_prospective_observatory.py
python -m mypy --strict scripts/build_cockpit_snapshot.py
python -m bandit -q -r src/robin
python scripts/check_no_secrets.py
python -m pip check
cd cockpit
pnpm run typecheck
pnpm run lint
pnpm test
pnpm run test:visual
```

Le build génère `cockpit-presentation.json` et
`cockpit-expert-data.json`. Ils doivent être régénérés et commités avec le
snapshot. Toute modification de `cockpit-data.json` doit également mettre à
jour `cockpit-data.sha256`.

Référence de livraison V1.1 :

```text
commit fonctionnel = 51a91f29397854d21861cee71ece37ee72f6e015
CI push = 30352906004
CI PR = 30352908592
sous-arbre Sites = 7e879a70df712b10b749a6b38f4cf6f44b8e11b4
version privée Sites = 15
```

Les deux CI sont vertes. Le site est en accès `custom`, avec le propriétaire
comme seul utilisateur autorisé et aucun groupe autorisé.

## Robin Experience V1.2 — validation depuis main

Référence post-fusion :

```text
head pré-fusion = 77f3ea358b4a4b71014ed32c96ebca9f0dca15af
merge commit = 937481e914ddbac56432a85bef8466a30c43e1d0
CI main = 30359456373
Pages = 30359455364
sous-arbre cockpit = fb07ed35c23c7b7b0a7d0fce30b37031141bf9c6
arbre cockpit = 4e6adb2bd418ef8a75ba05494b1af2ca4fce7f41
source Sites = d0a78b3fb710b949e7ac7b99907ef20002c017d8
version privée Sites = 18
```

Contrôler après chaque déploiement privé depuis `main` :

```text
/
/robin-live
/matchs
/matchs/<fixture canonique>
/observatoire
/laboratoire
/resultats
/methode
/expert
```

Vérifier sur desktop et 390 px : langue `fr-FR`, dates Europe/Paris, compte à
rebours, 9 fixtures, 18 identités, aucun `Équipe <id>` en Vue essentielle,
Vue expert, glossaire, navigation, absence de débordement et absence d’erreur
console. Le déploiement doit conserver l’accès `custom` au seul propriétaire.

Les workflows 60 à 66 doivent rester `active`, conserver leurs crons, le
groupe `prospective-deep-state` et `cancel-in-progress=false`. Leur inspection
est en lecture seule : ne jamais forcer un dispatch fournisseur pour valider
Robin Experience.

## Registre cinq ligues — calendrier et probes ciblés

Le workflow 60 découvre les fixtures sur 45 jours, tout en conservant trois
journées maximum par compétition. Cette portée ne change aucune fenêtre de
capture : J-21 reste la première échéance et aucun collecteur profond ou Odds
n’est déclenché par la découverte.

Le cycle planifié utilise toujours `competition=ALL`. Un probe manuel peut
cibler exactement une compétition configurée, après estimation signée :

```powershell
gh workflow run prospective-fixture-registry.yml `
  --ref <branche-ou-main> `
  -f execute=true `
  -f competition="Liga"
```

Le script valide le nom contre la politique centrale ; le workflow ne contient
aucune liste de ligues codée en dur. Le budget maximal est alors de 3 appels
API-Football et 0 crédit Odds. Répéter séparément pour `Bundesliga` uniquement
si la mission l’autorise.

Interprétation obligatoire :

- `WAITING_FOR_FIXTURES` ou `NO_FIXTURES_IN_CURRENT_HORIZON` : réponse
  fournisseur valide, sans incident ;
- `BLOCKED_PROVIDER_ERROR` : erreur HTTP, authentification, timeout ou schéma ;
- `BLOCKED_BUDGET` : plafond ou réserve protégée ;
- `ACTIVE_FULL` ou `ACTIVE_ODDS_REDUCED` : fixtures et identités admissibles.

Une compétition en attente est réévaluée chaque jour par le même workflow.
L’arrivée d’un calendrier planifie automatiquement les fenêtres idempotentes et
met à jour Robin Experience sans changement de code.

État attendu :

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```
