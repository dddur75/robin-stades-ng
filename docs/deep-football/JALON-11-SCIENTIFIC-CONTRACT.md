# Jalon 11 — contrat scientifique

Version gelée : `deep-football-scientific-contract-v1`
Verdict autorisé au vu des preuves : `JALON_11_BLOCKED_BY_DATA_GATES`

## Question

Le Jalon 11 cherche une information footballistique incrémentale par rapport à
la probabilité de marché dé-viguée. Il ne cherche pas à fabriquer une stratégie
rentable. Un résultat historique n'est jamais qualifié de causal ni de validé
prospectivement.

## Périmètre gelé

- cinq ligues : Ligue 1, Premier League, La Liga, Bundesliga et Serie A ;
- saisons disponibles 2020 à 2025, sans supposer leur complétude ;
- baseline principale `B0_MARKET` ;
- modèles d'équipe `B1_REGULARIZED_MULTINOMIAL` et
  `B1_BOUNDED_GRADIENT_BOOSTING` ;
- campagnes préenregistrées 11A à 11G ;
- hypothèses du propriétaire H11-001 à H11-008 ;
- calcul cache-only, avec `API_FOOTBALL_CALLS_ALLOWED=0` et
  `ODDS_API_CREDITS_ALLOWED=0`.

## Hiérarchie des preuves

1. donnée observée avec provenance, fixture et cutoff ;
2. dataset versionné, hashé et exactement apparié ;
3. walk-forward chronologique ;
4. comparaison au marché sur les mêmes fixtures ;
5. tests robustes, correction BH par famille puis globale ;
6. contrôles négatifs et red-team ;
7. replay déterministe ;
8. observation prospective future.

L'historique courant est un corpus exposé. Il n'est pas présenté comme un
holdout vierge.

## Contrat temporel

- toute entrée d'une feature doit vérifier `observed_at < target_kickoff` ;
- une rolling window exclut toujours le match cible ;
- `PRE_LINEUP` et `POST_LINEUP` sont des populations séparées ;
- une composition reçue après kickoff est rejetée ;
- une absence non datée ou reconstruite depuis le onze final est rejetée ;
- une cote d'un autre fixture ou une cote future est rejetée ;
- une valeur manquante reste manquante, jamais zéro par défaut.

Les lineups et statistiques joueurs historiques présentes en cache sont
`POST_MATCH_ONLY`. Les blessures sont
`HISTORICAL_NON_POINT_IN_TIME`. Leur contenu peut être audité, mais ne peut pas
alimenter une preuve pré-match.

## Appariement

L'échantillon de comparaison doit avoir :

- une clé fixture unique de chaque côté ;
- aucune intersection silencieuse ;
- la même liste de fixtures pour tous les modèles comparés ;
- un rapport explicite de toute attrition.

Le dataset `TEAM_PREMATCH` contient 10 732 fixtures exactement appariées au
marché, sans doublon ni attrition du périmètre marché. L'évaluation
chronologique 2022–2025 porte sur 7 081 fixtures ; les saisons 2020–2021 servent
au premier entraînement.

## Décision statistique

Une amélioration correspond à un delta de Log Loss ou de Brier négatif par
rapport à B0. Les p-values utilisent un contrôle adapté à la dépendance, avec
au minimum 30 clusters. Les tests incluent 999 permutations de signe. Les
q-values sont calculées par famille puis globalement.

Les résultats actuels sont défavorables :

| Modèle | N évaluation | Log Loss | Brier | Δ Log Loss vs B0 | Δ Brier vs B0 |
|---|---:|---:|---:|---:|---:|
| B0 marché | 7 081 | 0,966773 | 0,191619 | — | — |
| B1 multinomiale régularisée | 7 081 | 0,988918 | 0,196458 | +0,022145 | +0,004839 |
| B1 gradient boosting borné | 7 081 | 0,998024 | 0,198176 | +0,031251 | +0,006557 |

Les p-values et q-values principales valent 1. Aucun incrément au-delà du
marché n'est démontré.

## Promotion fail-closed

Les 17 gates de promotion sont une conjonction. Un seul échec interdit
`LIVE_SHADOW_CANDIDATE`. L'absence d'un prix live avec `observed_at` exact
interdit toute décision, même si un effet historique paraissait intéressant.

État courant :

- watchlist : 0 ;
- candidats shadow : 0 ;
- décisions : 0 ;
- mises : 0 unité ;
- bankroll shadow : 1 000 unités, inchangée ;
- paris réels : interdits.

## Invariants

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Les données lourdes restent hors Git. Aucun résultat de ce jalon n'autorise une
collecte fournisseur, une publication sociale automatique ou une fusion
automatique.
