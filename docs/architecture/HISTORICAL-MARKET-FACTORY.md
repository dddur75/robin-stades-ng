# Historical Market Factory

Football-Data est la source massive domestique pour Ligue 1, Premier League, La
Liga, Bundesliga et Serie A, saisons 2020 à 2025. Chaque CSV est archivé avant
normalisation avec son hash SHA-256, le hash de l’URL, la date de téléchargement,
la compétition, la saison et une version de schéma dérivée des colonnes.

La chaîne est `CSV brut → mapping versionné → registre d’alias → matching
canonique → historical_market_v1 → vues 1X2/totals → MARKET_GATE`. Un CSV
distant n’est jamais relu pendant un backtest. Les lignes ambiguës ou en conflit
sont exclues. Le dévig principal est une normalisation proportionnelle.

Les cotes de clôture sont préférées, puis les pré-clôture. Une absence reste
nulle. Aucun horaire d’observation n’est fabriqué.
