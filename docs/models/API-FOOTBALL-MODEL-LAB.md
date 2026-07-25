# API-Football Model Lab

Le premier cycle compare Elo API, régression multinomiale équipe, variante
pré-lineup, variante composition simulée et baseline marché déviguée. Les
modèles sont déterministes, régularisés et calibrés sur 2023 seulement.

Trois calibrations sont comparées : aucune, sigmoid et isotonic. Le choix se
fait par Log Loss de validation ; 2024–2025 reste aveugle jusqu'à l'évaluation
finale. Les sorties enregistrent Log Loss, Brier, ECE, résultats par saison,
artefact et hash.

Poisson, Dixon-Coles, gradient boosting et ensemble restent des étapes
progressives. Ils ne sont pas exécutés tant que leur hypothèse et leur
comparateur ne sont pas enregistrés.

