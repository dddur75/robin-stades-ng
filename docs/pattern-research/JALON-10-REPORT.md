# Rapport Jalon 10

Statut documentaire : `PENDING_REAL_CACHE_ONLY_RUN`
Date : 2026-07-27

## Résumé actuel

Le contrat scientifique, la politique point-in-time, les tests multiples, les
gates de promotion et le registre public sont spécifiés avant lecture des
résultats. La campagne réelle cache-only n’est pas encore consignée dans ce
rapport ; aucun pattern n’est donc annoncé robuste, shadow ou validé.

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
| Run réel | `PENDING_REAL_CACHE_ONLY_RUN` |
| Hypothèses générées | `PENDING_REAL_CACHE_ONLY_RUN` |
| Hypothèses exécutées | `PENDING_REAL_CACHE_ONLY_RUN` |
| Rejets fuite/support | `PENDING_REAL_CACHE_ONLY_RUN` |
| Positives brutes | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes FDR | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes walk-forward | `PENDING_REAL_CACHE_ONLY_RUN` |
| Survivantes validation externe | `PENDING_REAL_CACHE_ONLY_RUN` |
| Candidates shadow | `PENDING_REAL_CACHE_ONLY_RUN` |
| Contrôles négatifs | `PENDING_REAL_CACHE_ONLY_RUN` |

La section sera remplacée uniquement depuis le rapport stable et son hash.

## Public Evidence Ledger

Le contrat est append-only : décision immuable avant match, règlement séparé,
chaîne SHA-256, replay, bankroll shadow initiale de 1 000 unités et transparence
des pertes/`NO BET`. Tant qu’aucun candidat live n’existe, Robin Live doit
afficher zéro pari réel et zéro pari shadow, sans données de démonstration
présentées comme réelles.

## Coûts et stockage

L’objectif du run est zéro appel API-Football, zéro crédit The Odds API, aucun
nouveau fournisseur et seulement des sorties compactes. Les mesures réelles de
temps Actions, stockage et opérations R2 restent
`PENDING_REAL_CACHE_ONLY_RUN`.

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

`PENDING_REAL_CACHE_ONLY_RUN`

Un des verdicts officiels du Jalon 10 ne sera inscrit qu’après exécution,
replay, red team et CI :

- `JALON_10_PATTERN_ENGINE_READY`
- `JALON_10_NO_ROBUST_PATTERN_FOUND`
- `JALON_10_BLOCKED_BY_DATA_GATES`
- `JALON_10_SCIENTIFIC_VALIDATION_FAILED`
