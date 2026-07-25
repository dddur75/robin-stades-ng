# Preseason Shadow Package V1

Statut : `PRESEASON_PACKAGE_WAITING_FOR_EXTERNAL_GATES`.

Le package versionné référence le protocole gelé et les datasets :

- `pl_team_pre_match_v1` ;
- `laliga_team_pre_match_v1` ;
- `bundesliga_team_pre_match_v1`.

Il ne contient aucun modèle ni stratégie promu. Ses règles sont :

```text
MARKET_BASELINE_MONITORING
NO_EXTERNAL_VALIDATED_EDGE
NO_BET_DEFAULT = true
REAL_BETS = false
PRODUCTION_LOCKED = true
```

Il ne deviendra `PRESEASON_SHADOW_PACKAGE_V1_FROZEN` qu’après franchissement
des gates externes et validation complète. Toute version gelée est immuable ;
une modification crée une nouvelle version.
