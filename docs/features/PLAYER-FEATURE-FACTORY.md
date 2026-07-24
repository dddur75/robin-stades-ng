# Player Feature Factory

La V1 prépare minutes pondérées, titularisations, contributions offensives et
défensives, disponibilité, fatigue, importance dans l’effectif et valeur de
remplacement. Chaque valeur porte `as_of_time`, source, version, qualité et
classe de disponibilité.

Les features joueurs restent `BLOCKED_BY_COVERAGE` tant que le pilote live n’a
pas démontré une couverture suffisante. Aucune valeur manquante n’est remplacée
par zéro. L’apport joueur sera comparé à la baseline équipe uniquement sur
validation et OOS.

