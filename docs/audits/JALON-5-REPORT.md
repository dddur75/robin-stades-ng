# Audit Jalon 5 — Deep Data Factory

Statut courant : `HISTORICAL_PILOT_ACTIVE`.

## Preuves acquises

- PR #4 et #5 fusionnées ; départ depuis `main` au commit `1ee274e`.
- secrets `DATABASE_URL`, `ODDS_API_KEY`, `API_FOOTBALL_KEY` présents, valeurs
  jamais lues ni journalisées ;
- adaptateur API-Football paramétrable et pagination complète/reprenable ;
- stockage brut gzip immuable, Parquet partitionné et métadonnées PostgreSQL ;
- migration `0004_jalon5_deep_data_factory` appliquée en test ;
- dataset legacy point-in-time `team_baseline_v1` : 36 423 lignes ;
- Elo V1 : 6 443 matchs OOS, Log Loss 1,0075, Brier 0,2010 ;
- backtest OOS : 4 139 paris simulés, ROI -8,55 %, statut `REJECTED` ;
- sept workflows historiques et Deep Data Cockpit construits ;
- `PRODUCTION_LOCKED` maintenu.

## Preuves live à compléter automatiquement

La branche doit encore exécuter l’appel authentifié, le pilote Ligue 1 2025,
persister ses payloads dans `shadow-data` et Neon, puis démarrer les lots de
priorité A. Aucun résultat local ou legacy n’est présenté comme live.
