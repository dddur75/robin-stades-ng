# Première campagne de recherche

Statut : `JALON_10_NO_ROBUST_PATTERN_FOUND`
Sous-verdict scientifique :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`
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

## WHAT_WAS_TESTED

La conclusion porte exclusivement sur 700 règles historiques préenregistrées
de tranches de marché, et non sur tous les patterns possibles dans le football.

Ont été testés :

- cinq sélections : domicile, nul et extérieur en 1X2, Over 2,5 et Under 2,5 ;
- cinq bandes de cote : 1,20–1,60, 1,60–2,00, 2,00–2,50, 2,50–3,25 et
  3,25–5,00 ;
- trois plafonds de marge : 6 %, 8 % et 10 % ;
- deux catégories de prix source : closing et pre-closing ;
- cinq filtres de compétition : Ligue 1, Premier League, La Liga, Bundesliga et
  Serie A ;
- des règles simples, des paires limitées à cote + un filtre et des triplets
  limités à cote + marge + compétition.

Le dénominateur est 15 règles simples, 50 paires et 75 triplets par marché,
soit 140 règles par marché et 700 règles au total. L’évaluation utilise
l’historique exposé 2020–2025, une mise fixe d’une unité, la FDR, le bootstrap
groupé, le walk-forward exposé et sept contrôles négatifs.

## WHAT_WAS_NOT_TESTED

Cette campagne n’a pas testé :

- l’ensemble des patterns possibles dans le football ;
- la forme, l’Elo, les buts ou xG historiques, la force d’équipe ou les
  confrontations directes ;
- le repos, la congestion, le déplacement ou le calendrier ;
- les joueurs, absences, blessures, compositions, formations, tactiques,
  entraîneurs ou la latéralité ;
- le mouvement de cote, la CLV, des snapshots intrajournaliers ou les prix de
  bookmakers individuels ;
- BTTS, handicaps, scores exacts, corners, cartons, buteurs ou props joueurs ;
- d’autres ligues, saisons, seuils, règles à quatre conditions ou modèles
  non linéaires ;
- une validation prospective live, un prix réellement observé à T−60 ou un
  closing exact : seules les catégories source closing/pre-closing existent ;
- un holdout externe indépendant : Bundesliga et Serie A appartiennent déjà au
  corpus historique exposé ;
- une permutation candidate stratifiée par compétition, saison et bande de
  cote ; la permutation V1 reste globale et le gate concentration ferme toute
  promotion ;
- une gestion de mise autre que la mise fixe d’une unité.

Aucune conclusion ne peut être extrapolée à ces familles non testées.

## Configuration gelée

- seed : `10010` ;
- support minimal : 80 paris et 3 saisons ;
- support minimal par fold : 15 ;
- au moins 2 folds admissibles et dernier fold positif ;
- ratio de folds positifs : 0,67 ;
- FDR Benjamini–Hochberg : 0,05 ;
- bootstrap groupé : 1 000 réplications ;
- stabilité inter-ligues exposée : Bundesliga et Serie A, chacune ≥ 40 paris
  et ROI > 0 ; ce contrôle n’est pas un holdout externe ;
- domination : Jaccard ≥ 0,90 et amélioration ROI < 1 point ;
- calcul borné : 40 bootstraps, 5 permutations × 100 ;
- mise : 1 unité fixe ;
- conditions : une à trois ;
- exécution : cache-only, déterministe et checkpointée.

## Résultats de l’artefact hashé

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
| Survivantes stabilité inter-ligues exposée | 0 |
| Candidates shadow | 0 |
| Contrôles négatifs | 7/7 réussis |
| Replay / hash identique | oui |
| Appels fournisseur | 0 |
| Crédits The Odds API | 0 |
| Doublons au replay | 0 |

Les 24 survivantes walk-forward sont un résultat brut avant le gate FDR. Avec
zéro survivante FDR, aucune ne peut progresser vers le contrôle de stabilité
inter-ligues exposé ou le shadow. Le replay reproduit le même hash de résultat
sans fournisseur.

## Règles de publication

Le rapport final montre toutes les hypothèses et tous les rejets, pas seulement
le meilleur ROI. Pour chaque meilleur résultat, il publie support, intervalle,
q-value, folds, drawdown, concentration, limites et comparaison au marché.

Le verdict est `JALON_10_NO_ROBUST_PATTERN_FOUND`. Aucun seuil n’est modifié
après lecture des résultats.

Sous-verdict scientifique :

`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`

Cela signifie qu’aucune des 700 règles préenregistrées de tranches de marché
n’a survécu à la FDR sur ce corpus historique exposé. Cela ne signifie pas
qu’aucun pattern robuste n’existe dans le football, dans les familles de
features non testées, sur d’autres marchés ou dans de futures données
prospectives.
