# Modèle de force joueurs

Le score est interprétable et combine forme récente, minutes, contributions
offensive et défensive, rôle et régularisation par le support. L'incertitude
est `1 - minutes/(minutes+900)`.

Les comparaisons obligatoires sont :

1. équipe seule ;
2. équipe + onze attendu ;
3. équipe + onze confirmé simulé.

Un gain n'est retenu que s'il améliore au moins Log Loss et Brier sans
instabilité temporelle. Sinon la décision reste `INCONCLUSIVE` ou `REJECTED`.
Le modèle n'utilise aucune blessure tant que le Gate D est bloqué.

