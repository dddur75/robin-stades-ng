# Première campagne de recherche

Statut : `JALON_10_NO_ROBUST_PATTERN_FOUND`
Protocole : `pattern-scientific-contract-v1`

La première campagne réelle cache-only et son replay sont terminés. Les
résultats ci-dessous proviennent de la sortie déterministe ; aucun résultat
simulé ou supposé n’est ajouté.

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

## Résultats de l’artefact signé

| Mesure | Valeur |
|---|---|
| Statut du run | `CACHE_ONLY_COMPLETED` |
| Révision du code | `5c5b1a0344346b812a71962e7d0abadc3ba19266` |
| Hash du dataset | `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` |
| Hash du résultat | `e7dbd83ce41a96bcf58cbedba5102d499d2fa9a8f9b6ab2aaf22169abce1d0db` |
| Hypothèses générées | 700 |
| Hypothèses exécutées | 700 |
| Rejets pour support | 167 |
| Positives brutes | 118 |
| Survivantes FDR | 0 |
| Survivantes walk-forward brutes | 24 |
| Survivantes ligues externes | 0 |
| Candidates shadow | 0 |
| Contrôles négatifs | 7/7 réussis |
| Replay / hash identique | oui |
| Appels fournisseur | 0 |
| Crédits The Odds API | 0 |
| Doublons au replay | 0 |

Les 24 survivantes walk-forward sont un résultat brut avant le gate FDR. Avec
zéro survivante FDR, aucune ne peut progresser vers une validation externe ou
le shadow. Le replay reproduit le même hash de résultat sans fournisseur.

## Règles de publication

Le rapport final montre toutes les hypothèses et tous les rejets, pas seulement
le meilleur ROI. Pour chaque meilleur résultat, il publie support, intervalle,
q-value, folds, drawdown, concentration, limites et comparaison au marché.

Le verdict est `JALON_10_NO_ROBUST_PATTERN_FOUND`. Aucun seuil n’est modifié
après lecture des résultats.
