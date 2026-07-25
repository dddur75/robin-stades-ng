# Strategy Lab V1

Le premier laboratoire teste des seuils d'edge 1X2 voisins (2 %, 4 %, 6 %)
pour chaque modèle. Il publie volume, profit, ROI, yield, drawdown, série de
pertes, intervalle bootstrap et p-value corrigée Bonferroni.

Une stratégie négative avec intervalle entièrement sous zéro est `REJECTED`.
Les autres restent `INCONCLUSIVE` dans ce jalon. Même une validation OOS
crédible devrait encore devenir `LIVE_SHADOW_CANDIDATE` et traverser le
shadow prospectif 2026–2027 ; elle ne peut jamais devenir
`PRODUCTION_READY`.

