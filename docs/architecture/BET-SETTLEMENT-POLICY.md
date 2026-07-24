# Politique de cotes et règlement

Statut : `VERIFIED` pour les marchés initiaux en simulation
Paris réels : `PRODUCTION_LOCKED`

## Quatre grains distincts

1. `market_opportunity` : opportunité bookmaker-agnostique, unique par fixture,
   marché, sélection, ligne, période, règle et stratégie ;
2. `bookmaker_quote` : prix observé chez un bookmaker à un instant précis ;
3. `selected_bet` : choix d'une cotation pour une opportunité, au maximum un ;
4. `settled_bet` : résultat versionné du pari sélectionné.

Deux bookmakers proposant la même sélection ne créent donc pas deux opportunités.
Ils créent deux cotations comparables.

## Contrat canonique

```text
market_type
market_scope
selection
line_value
period
settlement_rule_version
bookmaker
odds_format
observed_at
```

La cote prise et la cote de clôture sont deux cotations différentes. Une clôture
inconnue reste manquante.

## Marchés initiaux

- 1X2 : domicile, nul, extérieur ;
- double chance : 1X, 12, X2 ;
- total buts : over/under avec ligne explicite, dont 2,5 ;
- les deux équipes marquent : oui/non.

Une ligne entière peut produire `PUSH`. Une ligne 2,5 ne peut pas. Un match reporté
ou annulé est `VOID` dans la règle canonique. Un match non terminé reste
`UNSETTLED`.

## Différences bookmaker

Chaque cotation conserve `bookmaker_rule_version`. Une règle spécifique non
modélisée interdit le règlement automatique de ce bookmaker. Une ligne 4,5 ne peut
jamais régler une cotation 5,5.

Le moteur legacy de confrontation reste `PARTIAL` tant qu'il n'est pas migré vers
ces tables. Ses anciens ROI multi-bookmaker demeurent `UNVERIFIED`.

## Corrections

Une correction de résultat crée un nouveau `settled_bet` avec
`result_version + 1` et `supersedes_settlement_id`. L'ancien règlement reste
consultable.
