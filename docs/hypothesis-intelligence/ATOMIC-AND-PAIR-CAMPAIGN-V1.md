# Atomic and Pair Campaign V1

## Périmètre exécuté

La campagne couvre cinq ligues, la saison 2024 et 1 756 fixtures. La
réconciliation distingue bien 486 propriétés et 28 familles : 46 READY,
46 PARTIAL, 344 BLOCKED et 50 UNKNOWN explicites. Chaque propriété revue
READY/PARTIAL possède désormais une table blanche exacte de chemins d’entité,
capacités et rôle temporel ; aucun UNKNOWN n’est attribué par ordre lexical.

La piste prédictive matérialise 80 tags issus de sept `property_id` réellement
adaptés aux variables historiques laggées (`10 bases × 2 orientations ×
4 fenêtres`). Les 39 autres propriétés READY sont des cibles, identités ou
descriptifs et ne sont pas faussement comptées comme tests atomiques. Les
80 tags produisent 160 tests sur deux cibles canoniques ; les vues
HOME/DRAW/AWAY/OVER/UNDER restent descriptives.

Le rolling-origin contient cinq folds expanding et 1 053 observations OOF.
Seuils Q67, probabilités et transformations sont appris sur le train. Chaque
source appartient à un match antérieur et reçoit un embargo conservateur de
six heures. Comme aucun vrai `known_at` point-in-time n’est disponible,
`point_in_time_source_provenance=false` et aucun résultat ne peut dépasser la
validation temporelle historique.

## Résultats atomiques

BH/FDR est appliqué globalement (160 tests) et par famille ; un test bloqué
reçoit p=1, et toute survie exige support total, support dans chaque fold,
couverture, au moins trois ligues, concentration ≤ 0,5 et gains log-loss et
Brier strictement positifs.

- 78 tags restent `RAW_HISTORICAL_SIGNAL` ;
- `TEAM_AWAY…WIN_RATE.SEASON_TO_DATE` survit la multiplicité sur TOTAL 2.5
  (`Δlog-loss=0,00036960`, `ΔBrier=0,00020128`, q global 0,007672096) ;
- `TEAM_HOME…FAILED_TO_SCORE_RATE.SEASON_TO_DATE` survit la validation
  temporelle sur MATCH_RESULT (`Δlog-loss=0,01877118`,
  `ΔBrier=0,00450980`, q global 0,018238712).

Ces deux résultats restent sous `SUSPICIOUS_EDGE_REVIEW` et ne sont ni
VALIDATED, ni PRODUCTION_READY, ni promus.

## Paires et grains

Les comptes ne mélangent plus propriétés et tags : 117 855 couples de
`property_id` dans le Genome, 21 couples dans le sous-espace de sept
propriétés, et 3 160 couples de tags. Après contradictions, support,
couverture et pruning, 1 398 couples de tags sont éligibles ; 120 sont gelés
par quotas (60 cross-side, 30 home-home, 30 away-away) et degré parent ≤6.
Les parents d’une paire ont toujours deux `property_id` distincts.

Les 120 paires produisent 240 tests : 45 `RAW_HISTORICAL_SIGNAL`, 51
`REJECTED`, 24 `LONG_TAIL_DEFERRED`, zéro survivante. Le comparateur n’est
plus choisi après observation du label : trois tests appariés séparés sont
calculés contre parent A, parent B et additif, puis
`p_intersection_union=max(p_A,p_B,p_additif)`. BH/FDR global et familial,
support enfant/parent et stabilité sont appliqués avant tout statut.

La partition de workflow est `first64(sha256(pair_id)) mod 8`; les huit shards
se réduisent à exactement 120 identifiants uniques et refusent manque,
duplication ou dérive du hash global.

## Contrôles et arrêt

Les huit contrôles négatifs sont réellement exécutés. Quatre passent les cinq
folds et la multiplicité (labels mélangés, aléatoire, impossible, trivial) ;
quatre exécutent les détecteurs d’admissibilité (future, prix décalé,
post-résultat, winner/loser). Aucun n’est promu et les rapports atomique/pair
sont distincts.

Aucun prix point-in-time admissible n’existe : `markets=[]`, profit, ROI,
drawdown et CLV sont absents. La profondeur maximale exécutée est deux ; la
campagne de triples est compilée mais `executed=false` et
`TRIPLE_SEARCH_LOCKED=true`.
