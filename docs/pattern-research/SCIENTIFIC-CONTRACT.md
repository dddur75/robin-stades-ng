# Contrat scientifique du Pattern Research Engine

Version : `pattern-scientific-contract-v1`
État : `FROZEN_BEFORE_RESULTS`
Date de gel : 2026-07-27

## Objet

Le moteur recherche des hypothèses football reproductibles sans transformer une
corrélation historique en promesse de gain. Une absence de pattern robuste est
un résultat recevable. Une preuve uniquement historique ne peut jamais produire
le statut `VALIDATED`.

Les données 2020–2025 ont déjà été examinées par les Jalons 7 à 9. Elles sont
donc classées `DISCOVERY_EXPOSED` ou `EXPOSED_HISTORICAL_OOS`, jamais holdout
vierge ni preuve prospective.

## Périmètre initial gelé

| Élément | Contrat |
|---|---|
| Sport | football |
| Compétitions | Ligue 1, Premier League, La Liga, Bundesliga, Serie A |
| Saisons | 2020–2025 disponibles dans l’archive Football-Data |
| Matchs appariés | 10 732 |
| 1X2 strict | 10 731 lignes après exclusion d’une marge négative |
| Over/Under 2,5 | 10 732 lignes |
| Prix | historiques observés, classe closing/pre-closing documentée |
| Horodatage de prix | `SOURCE_PRICE_CLASS_ONLY`, pas d’instant intrajournalier exact |
| Mise de preuve | 1 unité fixe |
| Fournisseurs | cache-only, zéro appel et zéro crédit attendus |

Les marchés sans cote historique observée ne sont pas reconstruits. BTTS,
handicaps, corners, cartons, buteurs et props joueurs restent
`MARKET_UNAVAILABLE` pour une mesure de ROI.

## Contrat d’un pattern

Une définition est immuable et porte au minimum :

- identifiant et version ;
- sport, compétitions, marché et sélection ;
- une à trois conditions canoniques ; une quatrième exige un
  préenregistrement explicite ;
- source et disponibilité temporelle de chaque condition ;
- cutoff de décision et classe du prix ;
- périmètres de découverte et de validation ;
- support, métriques financières, incertitude, q-value et stabilité ;
- révision du code et hashes des datasets ;
- statut, date de création et éventuel prédécesseur ;
- hash canonique de la règle.

Deux ordres différents des mêmes conditions produisent le même hash. Une règle
plus complexe sans amélioration démontrée est `DUPLICATE` ou `DOMINATED`.

## Statuts autorisés

```text
DISCOVERED
LEAKAGE_REJECTED
INSUFFICIENT_SUPPORT
DUPLICATE
DOMINATED
UNSTABLE
MARKET_UNAVAILABLE
HISTORICAL_CANDIDATE
EXPOSED_OOS_SURVIVOR
EXTERNAL_LEAGUE_SURVIVOR
LIVE_SHADOW_CANDIDATE
LIVE_SHADOW
PUBLIC_TEST
VALIDATED
REJECTED
```

Le chemin est monotone : un statut élevé ne masque jamais les rejets
précédents. `VALIDATED` exige une preuve `LIVE_PROSPECTIVE` indépendante.

## Métriques financières

Chaque règle exécutée, y compris négative, conserve :

- nombre d’occurrences et de paris ;
- cote moyenne et médiane ;
- profit brut, turnover et ROI à mise fixe ;
- hit rate, maximum drawdown et série maximale de pertes ;
- profit factor et bankroll théorique ;
- intervalle bootstrap groupé ;
- q-value et résultats par fold, saison, compétition et bande de cote.

Le Kelly, la martingale et toute optimisation de mise sont hors de la preuve
principale. Une cote modèle ou reconstituée ne remplace jamais une cote
historique observée.

## Reproductibilité

Un run conserve seed, configuration, révision, hashes, environnement, début,
fin, checkpoint, règles générées/exécutées/rejetées et coûts. Un replay
identique doit produire les mêmes règles, sélections, métriques et hashes, sans
appel fournisseur.

## Verrous permanents

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
```

Le moteur n’exécute aucune transaction, ne se connecte à aucun bookmaker et ne
publie sur aucun réseau social.
