# Rapport Jalon 9

Le Jalon 9 introduit une planification orientée gates sans supprimer de tâche,
conserve le contexte fixture dans les nouvelles lignes, audite Serie A/UCL,
ingère les archives Football-Data, produit les datasets marché, mesure les gates
joueurs/lineups/marché et prépare R2.

La preuve opérationnelle est écrite dans
`historical/market/runs/jalon9-latest.json`. Les valeurs finales de fichiers,
lignes, matching et stockage viennent exclusivement de ce rapport durable.

The Odds API historique reste en dry-run à zéro crédit. La production reste
`PRODUCTION_LOCKED` et `REAL_BETS = false`.

## Preuve réelle sur historical-data@1f3b606

- 30 CSV archivés, 10 734 matchs source et 10 732 appariés;
- mapping global 99,981 %, zéro ambiguïté, zéro non-résolu, deux conflits de
  score explicitement exclus;
- 10 732 lignes `historical_market_v1`, cinq MARKET_GATE domestiques READY;
- 12 786 prédictions appariées aux prix sur 18 couples ligue/modèle;
- le marché présente un Log Loss inférieur dans les 18 comparaisons;
- zéro candidat shadow, `NO_EXTERNAL_VALIDATED_EDGE`;
- zéro appel API-Football et zéro crédit The Odds API;
- stockage mesuré 421,2 MB, projection centrale 841,2 MB, projection haute
  886,2 MB : `OBJECT_STORAGE_RECOMMENDED`.

Cette preuve locale détachée ne concurrence pas le backfill actif. Sa
persistance sur `historical-data` est effectuée par le workflow pré-fusion dès
que le verrou `historical-state` est libre.
