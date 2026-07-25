# Audit Jalon 5 — Deep Data Factory

## Addendum Jalon 5.1

- registre historique isolé : 3 180/3 180 fichiers, 16 184 894 octets,
  0 hash modifié, 0 appel fournisseur ;
- pilote canonicalisé : 310 reçues, 306 régulières, 4 barrages ;
- équipes : 21 reçues, 18 régulières, Red Star/Rodez/Saint-Étienne hors phase ;
- débit observé : 0,146 s/appel, 8,027 lignes/appel, 1 857 octets/appel ;
- cadence : `ACCELERATED_SAFE`, 30 000 appels/jour, réserve 5 000 ;
- stockage projeté : 139 827 339 octets, alerte 750 MB, pause 900 MB ;
- production : `PRODUCTION_LOCKED`.

Statut courant : `VERIFIED` — backfill `HISTORICAL_BACKFILL_ACTIVE`.

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

## Preuves live

- authentification API-Football HTTP 200, quota quotidien observé : 150 000 ;
- six compétitions validées par réponse fournisseur : Ligue 1 `61`, Premier
  League `39`, La Liga `140`, Bundesliga `78`, Serie A `135`, UEFA Champions
  League `2` ;
- pilote Ligue 1 2025 `HISTORICAL_PILOT_VERIFIED` : 1 354 appels, 1 347 pages,
  10 868 lignes, 310 fixtures, 21 équipes et 0 échec qualité ;
- 1 545 payloads bruts gzip, 2 514 328 octets compressés ;
- 38 partitions Parquet, 3 789 988 octets ;
- 1 309 rapports d’endpoint terminés, 10 868 insertions et 0 doublon au premier
  passage ;
- registre `shadow-data` vérifié avec plus de 3 100 fichiers et hashes valides ;
- replay du pilote : `provider_calls=0`, aucune réécriture métier ;
- plan priorisé : 6 184 tâches, 54 terminées, 6 130 restantes ;
- migration Neon `0004_jalon5_deep_data_factory` appliquée ; upserts du plan
  segmentés sous la limite Psycopg et preuve PostgreSQL durable ;
- aucune clé dans les logs, payloads, manifests, frontend ou rapports.

## Analytique et décision

Le dataset et le premier modèle reposent sur la source legacy point-in-time,
explicitement séparée des données live API-Football. L’Elo V1 obtient une Log
Loss OOS de 1,0075 et un Brier de 0,2010. Le backtest à mise fixe perd 353,87
unités sur 4 139 paris (ROI -8,55 %, drawdown maximal 414,76 unités) : la
stratégie est `REJECTED`, sans promotion.

Le backfill massif continue par lots bornés ; il n’est pas un blocage de sortie
du Jalon 5. Aucun résultat local ou legacy n’est présenté comme live.
