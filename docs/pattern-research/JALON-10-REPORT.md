# Rapport Jalon 10

Statut documentaire : `JALON_10_NO_ROBUST_PATTERN_FOUND`
Sous-verdict scientifique :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`
Date : 2026-07-27

## Résumé actuel

L’espace de recherche et les seuils ont été gelés avant la campagne initiale.
La revue pré-fusion V1.1 a ensuite remplacé la p-value naïve par une p-value
CR1 groupée par date, raccordé les contrôles négatifs au verdict et fermé les
gates permutation/concentration, sans retuner une règle ni un seuil. La
campagne cache-only complète et son replay ont été relancés avec ces
corrections. Malgré 118 ROI positifs bruts et 24 stabilités walk-forward
brutes, aucune hypothèse ne survit à la correction FDR. Aucune des 700 règles
de ce search space n’est promue, shadow ou validée ; cette conclusion ne porte
pas sur les patterns football non testés.

## Audit tennis

L’archive a servi uniquement d’antériorité fonctionnelle et méthodologique.
Signal de sécurité : `LEGACY_HARDCODED_SECRET_DETECTED`. Aucun fichier ATP,
aucun ROI tennis et aucun secret n’est importé dans Robin. Le football conserve
son moteur, son vocabulaire et ses preuves propres.

## Données et marchés

- 10 732 matchs appariés sur cinq ligues, saisons 2020–2025 ;
- 10 731 lignes 1X2 strictes après exclusion d’une marge négative ;
- 10 732 lignes Over/Under 2,5 ;
- prix closing/pre-closing observés mais seulement
  `SOURCE_PRICE_CLASS_ONLY` ;
- données déjà exposées, donc aucune validation prospective ;
- autres marchés sans prix historique : `MARKET_UNAVAILABLE`.

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
groupé, des p-values CR1 groupées par date, le walk-forward exposé et sept
contrôles négatifs exécutés.

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

## Recherche

| Mesure | Résultat |
|---|---|
| Run réel | `CACHE_ONLY_COMPLETED` |
| Révision du code | `423fb7e77ba52286b660956161f02f8a2c1be7f8` |
| Hash dataset | `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` |
| Hash résultat | `edd5f84a84ebbe63fdfeaea0451478fc3baf3387265a9831b620fd6ef0f8194b` |
| Hypothèses générées | 700 |
| Hypothèses exécutées | 700 |
| Rejets pour fuite dans l’univers admissible | 0 |
| Rejets pour support | 167 |
| Positives brutes | 118 |
| Plus petite p-value CR1 | 0,0074788920 |
| Plus petite q-value | 1,00 |
| Survivantes FDR | 0 |
| Survivantes walk-forward brutes | 24 |
| Survivantes stabilité inter-ligues exposée | 0 |
| Candidates shadow | 0 |
| Contrôles négatifs | 7/7 réussis |
| Replay | hash identique, 0 doublon |

Le walk-forward brut n’outrepasse pas la correction des tests multiples. Zéro
survivante FDR implique zéro promotion, même si 24 règles ont des folds bruts
positifs.

## Meilleurs résultats exploratoires

Ces trois règles sont les meilleurs ROI parmi les règles à support suffisant
ayant survécu au walk-forward brut. Leur statut public est
`EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING` : elles restent `DISCOVERED`
dans le registre brut, avec `q = 1`, ne survivent pas au contrôle de stabilité
inter-ligues exposé et ne sont ni shadow, ni `VALIDATED`.

| Règle | Support | ROI / profit | IC bootstrap 95 % | q | Folds | Drawdown | Limite |
|---|---:|---:|---:|---:|---:|---:|---|
| La Liga, extérieur, cote 2,00–2,50, marge ≤ 6 % | 261 paris / 225 groupes | 16,64 % / 43,43 u | [3,36 % ; 30,77 %] | 1,00 | 4/4 | 9,27 u | spécifique à une ligue, sans holdout indépendant ni prix live exact |
| Serie A, nul, cote 2,50–3,25, marge ≤ 6 % | 363 paris / 282 groupes | 15,94 % / 57,88 u | [0,43 % ; 31,39 %] | 1,00 | 4/4 | 19,52 u | spécifique à une ligue, sans holdout indépendant ni prix live exact |
| Serie A, extérieur, cote 1,60–2,00, marge ≤ 6 % | 241 paris / 207 groupes | 13,87 % / 33,42 u | [2,49 % ; 24,27 %] | 1,00 | 3/3 | 7,22 u | spécifique à une ligue, sans holdout indépendant ni prix live exact |

La comparaison pertinente reste le marché observé : aucune de ces règles ne
survit à la correction des 700 hypothèses, et l’absence d’horodatage exact
interdit toute mesure CLV ou affirmation de supériorité reproductible en live.

## Contrôles négatifs

Les sept contrôles sont non promouvables et réussissent : labels mélangés
stratifiés, feature aléatoire inconnue, cotes décalées, condition impossible,
règle triviale « domicile partout », pattern post-résultat et orientation
winner/loser. Le contrôle mélangé produit un ROI de −8,02 % sur 10 731 paris ;
la règle triviale produit −8,12 %. Aucun faux edge n’est promu.

## Public Evidence Ledger

Le contrat est append-only : décision immuable avant match, règlement séparé,
chaîne SHA-256, replay, bankroll shadow initiale de 1 000 unités et transparence
des pertes/`NO BET`. Tant qu’aucun candidat live n’existe, Robin Live doit
afficher zéro pari réel et zéro pari shadow, sans données de démonstration
présentées comme réelles.

## Coûts et stockage

Le run et son replay ont consommé zéro appel fournisseur et zéro crédit The
Odds API. Aucun nouveau fournisseur n’a été utilisé et seules des sorties
compactes sont conservées.

`STORAGE_PAUSED` reste actif ; P3/P4 sont différés. Aucune suppression
`historical-data` ou R2 n’est autorisée.

## Sécurité

```text
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Aucun pari réel, aucune publication sociale automatique et aucune fusion ne
sont autorisés par ce rapport.

## Verdict

`JALON_10_NO_ROBUST_PATTERN_FOUND`

Sous-verdict scientifique :

`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`

Cela signifie qu’aucune des 700 règles préenregistrées de tranches de marché
n’a survécu à la FDR sur ce corpus historique exposé. Cela ne signifie pas
qu’aucun pattern robuste n’existe dans le football, dans les familles de
features non testées, sur d’autres marchés ou dans de futures données
prospectives.

Ce verdict est scientifique, non opérationnel : il n’autorise ni changement de
seuil, ni nouvelle source, ni pari réel.
