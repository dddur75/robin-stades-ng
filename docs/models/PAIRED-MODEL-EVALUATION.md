# Évaluation appariée des modèles

Deux sorties ne sont comparables que sur l’intersection exacte de :

1. fixture ;
2. saison et cible ;
3. snapshot de marché ;
4. cutoff et politique temporelle.

Un mismatch bloque l’expérience. Le delta primaire est la Log Loss
challenger-référence (négatif = meilleur). Brier, ECE et accuracy restent
secondaires. L’incertitude resample les groupes saison + semaine ISO, avec
5 000 réplications, CI 90/95 % et probabilité de supériorité.

La supériorité exige une CI 95 % entièrement favorable et P ≥ 0,95. Une moyenne
seule ne suffit jamais.
