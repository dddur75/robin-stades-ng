# Market Residual Campaign V3 — draft

La campagne reste `NOT_OPENED_INSUFFICIENT_POINT_IN_TIME_SUPPORT`. Elle n'est
pas exécutée par Robin Chronos V1.

La question confirmatoire est l'amélioration d'une probabilité de résultat par
rapport au consensus de marché déviggué, au cutoff unique `NEAR_KICKOFF`.
H24, H6 et H2 sont descriptifs. Si les quatre cutoffs devenaient
confirmatoires, le dénominateur serait pré-enregistré à 29 920 tests.

L'univers primaire conserve les 150 atomiques et 3 590 paires admissibles de
Phase C V2, pour 7 480 tests globaux. Les entrées indisponibles restent dans le
dénominateur avec `p=1`. Le seuil de 30 matchs n'est pas une analyse de
puissance.

Avec Bonferroni `alpha=0,05/7 480`, les minima effectifs à 80 % sont 675, 1 200
et 2 699 pour des effets standardisés 0,20, 0,15 et 0,10. À 90 %, ils sont 794,
1 412 et 3 176. Le besoin calendaire est
`ceil(n_eff * design_effect / (prevalence * admissible_price_coverage))`.

Le futur confirmatoire mesure le delta de log-loss contre le marché déviggué,
le delta Brier, la calibration résiduelle, la couverture, la fraîcheur, la
marge et la stabilité temporelle. ROI et CLV restent interdits sans prix,
cutoff, bookmaker et règlement exacts.
