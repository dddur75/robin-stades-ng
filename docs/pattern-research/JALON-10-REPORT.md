# Rapport Jalon 10

Statut documentaire : `JALON_10_NO_ROBUST_PATTERN_FOUND`
Date : 2026-07-27

## Résumé actuel

Le contrat scientifique, la politique point-in-time, les tests multiples et
les gates de promotion ont été gelés avant lecture. La campagne réelle
cache-only a exécuté les 700 hypothèses générées. Malgré 118 ROI positifs bruts
et 24 survivantes walk-forward brutes, aucune hypothèse ne survit à la
correction FDR. Aucun pattern n’est robuste, shadow ou validé.

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

## Recherche

| Mesure | Résultat |
|---|---|
| Run réel | `CACHE_ONLY_COMPLETED` |
| Révision du code | `5c5b1a0344346b812a71962e7d0abadc3ba19266` |
| Hash dataset | `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` |
| Hash résultat | `e7dbd83ce41a96bcf58cbedba5102d499d2fa9a8f9b6ab2aaf22169abce1d0db` |
| Hypothèses générées | 700 |
| Hypothèses exécutées | 700 |
| Rejets pour fuite dans l’univers admissible | 0 |
| Rejets pour support | 167 |
| Positives brutes | 118 |
| Survivantes FDR | 0 |
| Survivantes walk-forward brutes | 24 |
| Survivantes validation externe | 0 |
| Candidates shadow | 0 |
| Contrôles négatifs | 7/7 réussis |
| Replay | hash identique, 0 doublon |

Le walk-forward brut n’outrepasse pas la correction des tests multiples. Zéro
survivante FDR implique zéro promotion, même si 24 règles ont des folds bruts
positifs.

## Meilleurs résultats exploratoires

Ces trois règles sont les meilleurs ROI parmi les règles à support suffisant
ayant survécu au walk-forward brut. Elles restent `DISCOVERED`, avec `q = 1`,
et ne sont ni externes, ni shadow, ni `VALIDATED`.

| Règle | Support | ROI / profit | IC bootstrap 95 % | q | Folds | Drawdown | Limite |
|---|---:|---:|---:|---:|---:|---:|---|
| La Liga, extérieur, cote 2,00–2,50, marge ≤ 6 % | 261 paris / 225 groupes | 16,64 % / 43,43 u | [3,36 % ; 30,77 %] | 1,00 | 4/4 | 9,27 u | spécifique à une ligue, sans validation externe ni prix live exact |
| Serie A, nul, cote 2,50–3,25, marge ≤ 6 % | 363 paris / 282 groupes | 15,94 % / 57,88 u | [0,43 % ; 31,39 %] | 1,00 | 4/4 | 19,52 u | spécifique à une ligue, sans validation externe ni prix live exact |
| Serie A, extérieur, cote 1,60–2,00, marge ≤ 6 % | 241 paris / 204 groupes | 13,87 % / 33,42 u | [2,49 % ; 24,27 %] | 1,00 | 3/3 | 7,22 u | spécifique à une ligue, sans validation externe ni prix live exact |

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
```

Aucun pari réel, aucune publication sociale automatique et aucune fusion ne
sont autorisés par ce rapport.

## Verdict

`JALON_10_NO_ROBUST_PATTERN_FOUND`

Ce verdict est scientifique, non opérationnel : il n’autorise ni changement de
seuil, ni nouvelle source, ni pari réel.
