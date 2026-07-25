# Test d’isolation live / historique

Les invariants vérifiés par simulation et par workflow sont :

- workflows historiques : groupe `historical-state`, branche
  `historical-data`, aucune annulation silencieuse ;
- workflows live : groupe `shadow-state`, branche `shadow-data` ;
- trois retries Git bornés avec rebase en cas de non-fast-forward ;
- aucun chemin de publication historique ne cible `shadow-data` ;
- aucun workflow live ne restaure `historical-data`.

La preuve d’exécution GitHub renseigne les identifiants des runs, leurs temps
de démarrage, leurs conclusions et les commits des deux registres après le
déclenchement contrôlé. Un diagnostic et une simulation de cotes live peuvent
démarrer pendant le backfill parce que les clés de concurrence diffèrent.

Statut attendu : `LIVE_HISTORICAL_ISOLATED`, retard 0, conflit 0, mélange 0.
