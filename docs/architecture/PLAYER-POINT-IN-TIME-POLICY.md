# Politique point-in-time joueurs

Pour une fixture cible `T`, seules les observations de fixtures terminées avec
un coup d'envoi strictement antérieur à `T` peuvent alimenter les features.

- Score, événements, statistiques équipes et joueurs de `T` :
  `POST_MATCH_ONLY`.
- Composition officielle de `T` : uniquement
  `POST_LINEUP_SIMULATED`.
- Blessure sans observation datée avant `T` :
  `HISTORICAL_NON_POINT_IN_TIME`.
- Absence de valeur : `null`, jamais zéro implicite.

Le split principal est temporel : Discovery 2020–2022, Validation 2023 et
Blind OOS 2024–2025. L'adaptation par rapport à 2018–2025 est imposée par la
couverture réelle. L'OOS ne sélectionne ni feature, ni calibration, ni seuil.

