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
