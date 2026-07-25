# Qualité des données historiques

Contrôles bloquants :

- hash brut et Parquet ;
- pages manquantes, dupliquées ou incohérentes ;
- doublons métier ;
- identités absentes ou homonymes non résolus ;
- scores, minutes, événements et compositions incohérents ;
- absence transformée en zéro ;
- donnée future ou cible utilisée comme feature ;
- blessure non point-in-time dans un dataset causal ;
- saison OOS utilisée pour régler un paramètre.

Statuts : `PASSED`, `WARNING`, `FAILED`, `QUARANTINED`, `UNAVAILABLE`.

Une erreur temporelle arrête la Feature Factory et exclut la donnée des modèles.

