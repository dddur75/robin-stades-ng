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

## Preuve GitHub du 25 juillet 2026

| Run | Job | Début UTC | Fin UTC | Conclusion |
|---:|---|---|---|---|
| 30145120932 | Backfill historique | 05:04:47 | 05:05:51 | succès |
| 30145126424 | Diagnostic shadow | 05:04:46 | 05:05:35 | succès |
| 30145127029 | Collecte cotes `mock=true` | 05:04:48 | 05:06:07 | succès |

Les trois jobs se chevauchent dès leur démarrage. Le backfill publie
`historical-data`; la collecte simulée publie uniquement les deux fichiers
prospectifs attendus dans `shadow-data`. Le diagnostic est en lecture seule.
Les trois conclusions sont `success`, aucun appel de cotes et aucun crédit
The Odds API n’ont été consommés par la simulation.
