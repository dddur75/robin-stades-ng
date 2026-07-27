# Première campagne de recherche

Statut : `PENDING_REAL_CACHE_ONLY_RUN`
Protocole : `pattern-scientific-contract-v1`

Ce document est le réceptacle compact de la première exécution réelle. Il ne
contient volontairement aucun résultat simulé ou supposé.

## Entrées vérifiées avant exécution

| Élément | Valeur |
|---|---|
| Compétitions | Ligue 1, Premier League, La Liga, Bundesliga, Serie A |
| Saisons | 2020–2025 |
| Matchs appariés | 10 732 |
| 1X2 strict | 10 731 |
| Over/Under 2,5 | 10 732 |
| Provenance | Football-Data archivé et hashé |
| Prix | `SOURCE_PRICE_CLASS_ONLY` |
| Evidence scope | `DISCOVERY_EXPOSED` |
| Appels autorisés | 0 API-Football, 0 crédit The Odds API |
| Production | `PRODUCTION_LOCKED` |

Le corpus n’est pas un holdout vierge. L’absence d’horodatage exact du prix
ferme le gate live point-in-time.

## Configuration gelée

- seed : `10010` ;
- support minimal : 80 paris et 3 saisons ;
- support minimal par fold : 15 ;
- au moins 2 folds admissibles et dernier fold positif ;
- ratio de folds positifs : 0,67 ;
- FDR Benjamini–Hochberg : 0,05 ;
- bootstrap groupé : 1 000 réplications ;
- external : Bundesliga et Serie A, chacune ≥ 40 paris et ROI > 0 ;
- domination : Jaccard ≥ 0,90 et amélioration ROI < 1 point ;
- calcul borné : 40 bootstraps, 5 permutations × 100 ;
- mise : 1 unité fixe ;
- conditions : une à trois ;
- exécution : cache-only, déterministe et checkpointée.

## Résultats à remplacer depuis l’artefact signé

| Mesure | Valeur |
|---|---|
| Run / révision | `PENDING_REAL_CACHE_ONLY_RUN` |
| Hash du dataset | `PENDING_REAL_CACHE_ONLY_RUN` |
| Hypothèses générées | `PENDING_REAL_CACHE_ONLY_RUN` |
| Hypothèses exécutées | `PENDING_REAL_CACHE_ONLY_RUN` |
| Rejets pour fuite | `PENDING_REAL_CACHE_ONLY_RUN` |
| Rejets pour support | `PENDING_REAL_CACHE_ONLY_RUN` |
| Positives brutes | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes FDR | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes walk-forward | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes ligues externes | `PENDING_REAL_CACHE_ONLY_RUN` |
| Candidates shadow | `PENDING_REAL_CACHE_ONLY_RUN` |
| Contrôles négatifs | `PENDING_REAL_CACHE_ONLY_RUN` |
| Replay / hash identique | `PENDING_REAL_CACHE_ONLY_RUN` |
| Coût fournisseur | `PENDING_REAL_CACHE_ONLY_RUN` |

Ces cellules ne sont remplacées qu’après une exécution réelle ayant restauré
les données historiques durables. Un succès de workflow sans règles exécutées
ne suffit pas.

## Règles de publication

Le rapport final montre toutes les hypothèses et tous les rejets, pas seulement
le meilleur ROI. Pour chaque meilleur résultat, il publie support, intervalle,
q-value, folds, drawdown, concentration, limites et comparaison au marché.

Si aucun candidat ne franchit les gates, le résultat attendu est
`NO_ROBUST_PATTERN_FOUND`. Aucun seuil ne sera modifié après lecture des
résultats.
