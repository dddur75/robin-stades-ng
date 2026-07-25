# Backtest OOS API-Football

Le moteur V3 accepte 1X2 et Over/Under 2,5, probabilités déviguées, mise fixe,
proportionnelle ou Kelly fractionné, plafond, bankroll fictive, drawdown et
séries de pertes.

Les segments `HISTORICAL_DISCOVERY`, `HISTORICAL_VALIDATION`, `BLIND_OOS` et
`LIVE_SHADOW` ne peuvent pas être mélangés. Le premier cycle utilise
2024–2025 en `BLIND_OOS`.

Une absence de prix ou de probabilité produit aucune décision, pas une valeur
de remplacement. La CLV reste nulle/absente si son horodatage n'est pas
disponible.

