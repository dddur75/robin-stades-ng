# Runbook — Backfill API-Football

## Cadence Jalon 5.1

Le cron s’exécute à `37 */2 * * *`. Laisser `max_calls=0` et `max_tasks=0`
active le calcul `ACCELERATED_SAFE`. Les limites explicites de dispatch restent
des plafonds opérateur. Un seul run historique est actif. Le live utilise une
autre clé de concurrence et ne doit jamais attendre ce run.

Raisons d’arrêt enregistrées : `QUOTA_PROTECTED`, `MAX_DURATION_REACHED`,
`HTTP_429_CIRCUIT_OPEN`, `ERROR_RATE_ABOVE_5_PERCENT`,
`TEMPORAL_QUALITY_CRITICAL`, `STORAGE_PAUSE_THRESHOLD` ou absence de tâche.

## Ordre autonome

1. `20 - Couverture API-Football` valide l’authentification et les identifiants.
2. `21 - Backfill historique` exécute le pilote Ligue 1 2025.
3. Le même workflow crée puis reprend le plan A → B → C.
4. `22 - Qualité historique` bloque toute partition critique.
5. Features, modèles, backtests et cockpit s’enchaînent ensuite.

Chaque lot est borné par appels, tâches, durée GitHub Actions et réserve quota.
Un checkpoint `COMPLETED` provoque un replay à zéro appel. Une indisponibilité
Neon laisse les données dans `shadow-data`; le prochain lot rejoue les
métadonnées sans rappeler le fournisseur.

Commande locale de test, sans secret :

```powershell
python scripts/run_historical_pipeline.py contract
python scripts/run_historical_pipeline.py features
python scripts/run_historical_pipeline.py train
python scripts/run_historical_pipeline.py backtest
```
