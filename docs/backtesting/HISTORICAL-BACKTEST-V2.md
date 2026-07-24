# Historical Backtest V2

Découpage initial :

- discovery : 2018–2022 ;
- validation : 2023 ;
- blind OOS : 2024–2025.

Le moteur V1 implémente une baseline Elo interprétable et une simulation à mise
fixe. Sur les données legacy, l’Elo obtient Log Loss 1,0075 et Brier 0,2010 sur
6 443 matchs OOS. La stratégie edge 5 % perd 353,87 unités sur 4 139 paris
simulés ; elle est `REJECTED` et n’est pas promue.

Les modèles Poisson, Dixon-Coles, joueurs, compositions, marché et ensemble
restent `BLOCKED_BY_COVERAGE` dans le Jalon 5 tant que les datasets API-Football
requis ne sont pas vérifiés.
