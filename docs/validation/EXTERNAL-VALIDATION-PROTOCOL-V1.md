# External Validation Protocol V1

Protocole enregistré avant résultats : Premier League, La Liga, Bundesliga,
Serie A et UEFA Champions League, au moins trois saisons par compétition.

Métrique primaire : delta apparié de Log Loss. Secondaires : Brier, ECE et
accuracy. Unité bootstrap : saison-semaine, 5 000 réplications. Succès :
CI 95 % favorable et P ≥ 0,95 sur au moins trois compétitions. Tout échec ou
manque de couverture conserve le résultat en recherche.

Le hash du protocole est produit par l’arène et fait partie de la clé de cache.
Il ne peut être réécrit après observation des résultats externes.
