# P0 E3B Capability Scale V1

E3B étend uniquement les capacités ayant passé E3A aux cinq ligues de la saison
2024. La contribution Ligue 1 est réutilisée sans nouveau téléchargement dans le
job E3A ; les quatre autres ligues sont mesurées séparément puis agrégées par
sommes des numérateurs et dénominateurs.

Le gate transmet six capacités. TEAM, PLAYER, FORMATION, EVENTS et
DISCIPLINE_GENERIC sont `E3B_READY_RECONSTRUCTED` sur les 1 756 fixtures.
LINEUP reste `E3B_MEASURED_PARTIAL` : 3 510 lineups sur 3 512 sont valides et
deux lineups Serie A sont affectées par quatre conflits de rôle joueur, sans
double comptage comme identités PLAYER ni comme contradictions. TEAM_STATISTICS reste fermée par le gate
E3A, et Calendar reste bloquée par temporalité.

Un défaut local ne contamine pas une capacité indépendante. Les statuts globaux
sont calculés après conservation du statut par ligue. Ils décrivent la couverture
de données et la temporalité, pas une stratégie de pari.

La preuve demeure prédictive et descriptive, sans prix point-in-time. Aucun ROI,
pari réel, déploiement, publication, promotion ou recherche de triples n'est
autorisé par E3B.
