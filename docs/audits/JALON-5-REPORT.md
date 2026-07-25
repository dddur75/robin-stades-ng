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

## Activation post-fusion

- PR #6 fusionnée et fermée ; `main` au commit `9726ea9` ;
- backfill `30150002144` : 99 appels, 99 tâches, 1 597 lignes, 0 erreur,
  0 HTTP 429, quota restant 149 895 ;
- progression : 54 → 153 tâches terminées, 6 130 → 6 031 restantes ;
- nouvelle partition `fixture_events` Ligue 1 2024 ;
- branche `historical-data` : 65 → 69 fichiers physiques et
  23 152 551 → 27 127 859 octets après le lot ;
- archive du lot : 3 334 objets, SHA-256 vérifié ;
- Neon : SSL, révision `0004`, 6 713 upserts, 0 insert dupliqué ;
- replay : 0 appel, 0 crédit, 0 doublon, 40 fichiers Parquet stables ;
- diagnostic live concurrent `30150014764` : `PASSED`, `windows_due=0`,
  `PRODUCTION_LOCKED` ;
- qualité initiale `30150214587` verte mais trop étroite ; la correction dédiée
  ajoute provenance, pages, identités, nulls, données futures, cardinalité et
  blocages temporels ;
- Cockpit `30150283344` : build et artefact réussis ; la version privée
  antérieure au lot a été identifiée comme non redéployée automatiquement.

La correction est vérifiée par le run `30151227188` : 27 600/27 600 lignes
reliées à un payload brut, 0 appel, 0 crédit, qualité `PASSED`, révision Neon
`0004`, un run d'ingestion ajouté puis protégé par une clé idempotente. Le
Cockpit `30151317894` publie l'artefact `8617713588` et la version privée Sites
8 a été déployée avec le snapshot du 25 juillet 2026 à 08:34 UTC.

## Contrôle Jalon 5.2

- PR #7 fusionnée et fermée ; `main` au commit
  `0b72fcb6db4af304edad95d76a26db217eb84568` ; CI `30153554924` verte ;
- backfill planifié réutilisé, sans doublon de run : `30154099512`, 2 500
  appels, 2 500 tâches terminées, 38 enfants matérialisés, 14 072 lignes,
  quota restant 147 395, 0 erreur et 0 HTTP 429 ;
- progression : 6 184 → 6 222 tâches, 153 → 2 655 terminées,
  6 031 → 3 567 restantes, 1 649 → 4 149 payloads,
  27 600 → 41 672 lignes et 40 → 48 partitions Parquet ;
- `historical-data` : registre de 90 objets vérifié, 57 258 793 octets
  physiques après qualité, bundles et hashes valides ;
- Neon : SSL, Alembic `0004_jalon5_deep_data_factory`, 6 222 tâches,
  3 runs historiques ; lot initial 39 insertions/6 713 mises à jour, puis
  replay qualité 0 insertion/6 752 mises à jour ;
- qualité `30155383297` : 41 672/41 672 provenances, hashes et identités,
  0 ligne non résolue, 0 donnée future, 0 zéro synthétique ;
- replay depuis le cache : 0 appel fournisseur, 0 crédit, 0 perte ;
- diagnostic live concurrent `30155237678` : `PASSED`, 69 tables Neon,
  26 bundles shadow, 0 retard, `windows_due=0`, `PRODUCTION_LOCKED` ;
- Cockpit `main` après qualité : run `30155451951`, build vert et artefact
  `8618862988` ; la version privée 8 est inchangée et donc en retard.

Le forecast corrigé distingue 3 256 appels matérialisés de 60 057 appels
latents centraux. Les scénarios bas/central/haut sont 47 417 / 63 313 /
69 977 appels, avec ETA globale 1,58 / 2,11 / 2,33 jours et stockage restauré
projeté 227,9 / 427,2 / 665,3 MB. La cadence reste 30 000 appels/jour.

Statuts maintenus : `API_FOOTBALL_LIVE_PIPELINE_VERIFIED`,
`HISTORICAL_BACKFILL_ACTIVE`, `SHADOW_COLLECTION_HARDENED` et
`PRODUCTION_LOCKED`. Aucun modèle joueur, marché, stratégie ou pari réel n’est
promu.
