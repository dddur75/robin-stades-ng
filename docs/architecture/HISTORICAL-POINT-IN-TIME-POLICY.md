# Politique historique point-in-time

Classes obligatoires :

- `POINT_IN_TIME_SAFE` : connu avant le match cible ;
- `POST_MATCH_ONLY` : résultat, événement ou statistique du match cible ;
- `HISTORICAL_NON_POINT_IN_TIME` : récupéré aujourd’hui sans preuve de date ;
- `SIMULATED_AVAILABILITY` : disponibilité reconstruite et explicitement simulée ;
- `UNKNOWN_AVAILABILITY` : exclu par défaut.

Le mode `PRE_LINEUP` interdit la composition officielle du match cible. Le mode
`POST_LINEUP_SIMULATED` l’autorise uniquement sous étiquette historique simulée.
Les blessures sans temporalité fiable sont exclues. Les saisons 2024 et 2025
OOS ne règlent ni features, ni seuils, ni paramètres.

Les tests adversariaux modifient le résultat du match cible et vérifient que ses
features pré-match restent identiques.

