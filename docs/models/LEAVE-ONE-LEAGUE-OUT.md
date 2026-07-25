# Leave-One-League-Out

| Ligue tenue à l’écart | Fixtures | Log Loss | Brier | ECE |
|---|---:|---:|---:|---:|
| Premier League | 760 | 1,0105 | 0,2021 | 0,0316 |
| La Liga | 760 | 0,9913 | 0,1962 | 0,0205 |
| Bundesliga | 616 | 0,9947 | 0,1977 | 0,0420 |

Chaque modèle est entraîné sur les deux autres ligues prêtes, sans label de la
ligue tenue à l’écart. La standardisation utilise uniquement les distributions
de features pré-test. Le marché externe reste indisponible ; ces mesures
démontrent la capacité technique de transfert, pas un edge économique.

Statut : `LEAVE_ONE_LEAGUE_OUT_READY` pour trois ligues ; Serie A et UCL
attendent TEAM_GATE.
