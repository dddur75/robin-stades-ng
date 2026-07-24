# Runbook

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
