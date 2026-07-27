# Politique point-in-time des patterns

Version : `pattern-point-in-time-v1`
Principe : toute information doit être disponible strictement avant le cutoff
de la décision.

## Classes de preuve

| Classe | Usage |
|---|---|
| `DISCOVERY_EXPOSED` | génération d’hypothèses sur historique déjà examiné |
| `EXPOSED_HISTORICAL_OOS` | fold temporel exposé, jamais qualifié de vierge |
| `EXTERNAL_LEAGUE_VALIDATION` | nom technique ; scientifiquement, stabilité inter-ligues exposée sans holdout indépendant |
| `LIVE_PROSPECTIVE` | seule classe pouvant contribuer à `VALIDATED` |

## Disponibilité des marchés

| Marché | Résultats | Cotes observées | Point-in-time | Taille stricte | Statut |
|---|---:|---:|---|---:|---|
| 1X2 | oui | oui | `SOURCE_PRICE_CLASS_ONLY` | 10 731 | `HISTORICAL_EVALUABLE_EXPOSED` |
| Over/Under 2,5 | oui | oui | `SOURCE_PRICE_CLASS_ONLY` | 10 732 | `HISTORICAL_EVALUABLE_EXPOSED` |
| BTTS | dérivable | non | absent | 0 | `MARKET_UNAVAILABLE` |
| Score exact | oui | non | absent | 0 | `MARKET_UNAVAILABLE` |
| Cartons/corners | partiel | non | absent | 0 | `MARKET_UNAVAILABLE` |
| Handicaps | résultat dérivable | non | absent | 0 | `MARKET_UNAVAILABLE` |
| Buteurs/props joueurs | partiel | non | absent | 0 | `MARKET_UNAVAILABLE` |

Les 10 732 matchs appariés couvrent Ligue 1, Premier League, La Liga,
Bundesliga et Serie A sur les saisons Football-Data 2020–2025. La ligne 1X2 à
marge négative est conservée pour audit mais exclue du corpus strict.

`SOURCE_PRICE_CLASS_ONLY` signifie que la source documente une classe de prix
closing ou pre-closing, sans `observed_at` intrajournalier fiable. Cette donnée
permet une recherche historique correctement étiquetée, mais ne prouve pas que
le même prix aurait été disponible à un cutoff live donné. Le gate
`live_market_point_in_time` reste fermé.

## Contrat d’une feature

Chaque feature déclare :

- source et version ;
- `observed_at` ou classe de disponibilité ;
- fenêtre de calcul ;
- délai de publication éventuel ;
- cutoff et modes de décision autorisés ;
- qualité, nullabilité et provenance.

Une valeur manquante reste `null`. Elle n’est jamais remplacée par zéro.

## Informations interdites

Une décision pré-match ne peut utiliser le score final, le vainqueur, des
statistiques du match cible, une cote future, un classement recalculé avec le
match cible, une moyenne glissante incluant le match cible, une composition ou
une blessure connue après le cutoff, ni un dérivé de ces informations.

Les colonnes orientées `winner_*`/`loser_*` sont interdites : leur orientation
dépend du résultat futur.

## Tests adversariaux

Le gate échoue fermé pour :

1. target leakage ;
2. future leakage ;
3. rolling incluant le match cible ;
4. jointure sur le mauvais fixture ;
5. orientation winner/loser ;
6. duplication domicile/extérieur ;
7. cote postérieure au cutoff ;
8. lineup post-cutoff en mode pré-lineup ;
9. signal persistant après mélange des labels ;
10. performance anormalement parfaite.

Toute règle concernée devient `LEAKAGE_REJECTED`; elle reste enregistrée dans
le registre des hypothèses et ne peut pas être promue.

## Décision live

Tant qu’un prix possède seulement `SOURCE_PRICE_CLASS_ONLY`, un pattern
historique peut au plus atteindre le statut technique
`EXTERNAL_LEAGUE_SURVIVOR`, qui ne prouve qu’une stabilité inter-ligues exposée.
Il ne devient pas `LIVE_SHADOW_CANDIDATE`. En exploitation, l’absence d’une
feature ou d’une cote point-in-time produit `NO_BET_DATA_UNAVAILABLE`.
