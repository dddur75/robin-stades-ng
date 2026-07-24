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
.\.venv\Scripts\python.exe -m ruff check src/robin tests/jalon1 scripts/build_jalon1_notebook.py migrations
.\.venv\Scripts\python.exe -m mypy src/robin
.\.venv\Scripts\python.exe -m bandit -q -r src/robin
.\.venv\Scripts\python.exe -m compileall -q agents moteur src tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
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

## Collecte prospective

Le fournisseur mock valide le contrat sans clé. Une future collecte réelle doit :

1. créer le run idempotent ;
2. archiver la réponse brute ;
3. résoudre les identités ;
4. écrire les snapshots immuables en UTC ;
5. lancer les contrôles qualité ;
6. publier volumes, fraîcheur et artefacts.

Un workflow vert sans snapshot réel n'est pas une preuve de collecte.

## Incident et reprise

1. conserver payloads, manifestes, logs et identifiant du run ;
2. ne pas masquer l'erreur ;
3. reprendre depuis la dernière étape transactionnelle réussie ;
4. rejouer avec la même clé d'idempotence ;
5. versionner toute correction tardive ;
6. ne jamais réécrire une cote, une prédiction ou un résultat historique.
