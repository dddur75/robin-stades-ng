# Atomic and Pair Campaign V1

## Résultat exécuté

La campagne reconstruite couvre cinq ligues, la saison 2024 et 1 756 fixtures.
Elle matérialise 80 tags (`10 bases × 2 orientations × 4 fenêtres`) et exécute
160 tests atomiques sur deux cibles canoniques. Les cinq sorties
HOME/DRAW/AWAY/OVER/UNDER sont des vues descriptives, pas cinq familles de
tests indépendantes.

Le rolling-origin comprend cinq folds expanding et 1 053 observations OOF.
Chaque source appartient à un match antérieur et devient éligible seulement
six heures après son coup d’envoi. Cet embargo est conservateur mais ne prouve
pas un vrai `known_at`; le plafond de statut est donc
`SURVIVED_TEMPORAL_VALIDATION` avec
`point_in_time_source_provenance=false`.

Le sous-espace de paires est gelé avant lecture des cibles : 60 cross-side,
30 home-home et 30 away-away, avec bases distinctes, couverture initiale,
support, Jaccard et degré parent maximal de six. Les 120 paires produisent 240
tests et sont comparées au modèle simple, aux deux parents et à leur forme
additive. BH/FDR est appliqué sur les dénominateurs complets 160 et 240.

## Limites

- aucune capacité stricte n’est prouvée par les artefacts E3 ;
- TEAM_STATISTICS reste partielle et hors de cette campagne reconstruite ;
- Calendar reste bloquée par temporalité ;
- aucun prix point-in-time admissible n’existe ;
- `markets=[]`, profit, ROI, drawdown et CLV sont `null` ;
- les signaux survivants restent historiques et doivent être revus, jamais
  promus automatiquement.

Les huit contrôles négatifs couvrent labels mélangés, feature aléatoire,
feature future, prix décalé, condition impossible, règle triviale,
post-résultat et winner/loser. Les contrôles de fuite sont rejetés avant
modélisation; le contrôle prix confirme l’absence du contrat requis.

## Arrêt

La profondeur maximale exécutée est deux. La campagne de triples est compilée
mais `executed=false`; `TRIPLE_SEARCH_LOCKED=true`. Aucun triple, profondeur
4+, programmation génétique massive, stratégie de pari, pari réel ou
déploiement n’a été lancé.
