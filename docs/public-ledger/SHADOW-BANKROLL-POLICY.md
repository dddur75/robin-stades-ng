# Politique de bankroll shadow

Version : `shadow-bankroll-v1`

## Paramètres

- bankroll initiale : 1 000 unités fictives ;
- mise scientifique : 1 unité fixe par décision `BET` ;
- `NO_BET` : 0 unité ;
- `VOID` : profit 0 ;
- aucune devise réelle nécessaire à l’affichage public.

La bankroll est une simulation comptable. Elle ne représente ni un compte
bookmaker, ni de l’argent détenu, ni une recommandation de mise.

## Calcul

Pour une cote décimale observée :

- gain : `cote - 1` unité ;
- perte : `-1` unité ;
- void : `0` unité.

La bankroll change uniquement lors d’un événement de règlement append-only.
Décisions non réglées et `NO BET` ne modifient pas le solde.

Les rapports publient turnover, profit, ROI, hit rate, drawdown maximal et
séries de pertes. Les pertes ne sont jamais masquées.

## Interdictions

- martingale ou rattrapage d’une perte ;
- optimisation de mise pendant la découverte ;
- transaction réelle ;
- connexion bookmaker ;
- retrait, dépôt ou ordre automatique ;
- confusion entre bankroll shadow et promesse de gain.

Une simulation Kelly éventuelle doit rester séparée de la preuve à mise fixe et
ne peut déclencher aucune action.

## Invariants

```text
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
```
