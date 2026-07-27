# Spécification des exports sociaux

Version : `social-export-v1`
Publication : `SOCIAL_PUBLISHING_ENABLED=false`

## Sorties normalisées

```text
social_exports/
├── daily_picks.json
├── daily_results.json
├── weekly_bankroll.json
├── experiment_update.json
└── rejected_pattern.json
```

Chaque document contient version de schéma, instant UTC, statut shadow,
message factuel, lien vers le ledger, inclusion des résultats négatifs et
`publishing_enabled=false`.

## Templates

Les cinq familles couvrent :

- test shadow ou `NO BET` du jour ;
- bilan quotidien complet ;
- bankroll hebdomadaire ;
- nouvelle hypothèse ;
- pattern rejeté et raison.

Chaque texte mentionne le caractère shadow ou l’absence de garantie. Il renvoie
vers le registre public et publie aussi pertes, void et rejets.

## Vocabulaire

Termes autorisés : hypothèse, pattern historique, test shadow, candidat,
rejeté, drawdown, aucune garantie et `NO BET`.

Sont interdits : « pari sûr », « gain garanti », « stratégie infaillible »,
« quasi-certitude », « argent facile » et « 100 % gagnant ».

## Sécurité

Aucun adaptateur Facebook, Discord, Telegram ou autre réseau n’est actif au
Jalon 10. Les exports ne contiennent ni secret, ni URL PostgreSQL/R2, ni donnée
personnelle, ni ordre de pari. Leur génération n’autorise jamais leur
publication.
