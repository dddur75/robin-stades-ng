# External Validation Protocol V1

Statut : `EXTERNAL_VALIDATION_PROTOCOL_V1_LOCKED`.

Le protocole machine est écrit avant toute lecture de résultat externe dans
`historical/external/protocol/external-validation-protocol-v1-locked.json`.
Son hash inclut la définition, le commit source et l’heure de gel. Une
définition différente après gel provoque un échec bloquant.

## Données et périodes

- compétitions : Premier League, La Liga, Bundesliga, Serie A, UEFA Champions League ;
- discovery : 2019–2022 ;
- validation : 2023 ;
- external test : 2024–2025 ;
- datasets : `*_team_pre_match_v1`, puis joueurs et post-lineup uniquement si
  leurs gates respectifs passent ;
- prix : seulement des cotes historiques observées et jointes par identité de
  fixture ; aucune cote n’est imputée ou inventée.

## Features, modèles et paramètres

Les features équipe du Jalon 6 sont les seules autorisées tant que les gates
joueurs et compositions sont bloqués. Les cibles, informations futures et
blessures rétrospectives sont interdites.

Familles préenregistrées :

- transfert du multinomial Ligue 1 gelé ;
- multinomial régularisé spécifique à chaque ligue ;
- multinomial pooled avec standardisation par ligue ;
- Poisson et Dixon–Coles ;
- leave-one-league-out.

Paramètres gelés : seed 1707, 300 itérations, learning rate 0,08,
régularisation 0,01 et rho Dixon–Coles -0,08. Aucun label externe ne sélectionne
un paramètre ou calibrateur. Toute adaptation ultérieure est
`POST_EXTERNAL_EXPLORATORY`.

## Mesure et décision

Les comparaisons emploient exactement les mêmes compétition, fixture, saison,
cible, snapshot marché et politique temporelle. Les métriques sont Log Loss,
Brier, ECE, accuracy, sharpness, pente et intercept de calibration.

Le bootstrap déterministe utilise 5 000 réplications groupées par compétition,
saison et semaine. Une supériorité exige un CI 95 % favorable et
P(supériorité) ≥ 0,95 ; la validation externe globale exige au moins trois
compétitions. Le manque de couverture conduit à `WAITING_FOR_EXTERNAL_GATES`,
jamais à une promotion.

`PRODUCTION_LOCKED`, `REAL_BETS=false` et `NO_BET_DEFAULT=true` restent
invariants.
