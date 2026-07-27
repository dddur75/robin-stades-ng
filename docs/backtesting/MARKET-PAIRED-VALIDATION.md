# Validation appariée au marché

Les modèles Jalon 8 restent gelés. Chaque comparaison utilise les mêmes fixtures
pour le modèle et le marché, sans retuning : transfert Ligue 1, spécifique,
pooled, Poisson et Dixon-Coles.

Les sorties prévues sont Log Loss, Brier, ECE, pente/intercept de calibration,
delta apparié, IC 90/95 % et probabilité de supériorité. Sans MARKET_GATE READY,
le statut reste `NO_EXTERNAL_VALIDATED_EDGE`.

La première exécution réelle apparie 12 786 prédictions. Dans chaque comparaison
Premier League, La Liga et Bundesliga, le delta Log Loss modèle moins marché est
positif et son IC 95 % reste positif. Aucun modèle ne bat le marché :
`NO_EXTERNAL_VALIDATED_EDGE`.
