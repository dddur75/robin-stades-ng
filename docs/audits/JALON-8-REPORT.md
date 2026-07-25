# Jalon 8 — rapport d’audit

## Portée

Validation externe multi-ligues, sans nouvel appel fournisseur, sans nouveau
marché et sans pari réel.

## Preuves initiales

- source durable : `historical-data@9aa54ef` ;
- stockage avant analytique : 361 005 947 octets ;
- stockage après analytique local : 364 477 070 octets ;
- seuil warning : 750 000 000 ; pause : 900 000 000 ;
- protocole gelé avant résultats ;
- 3 TEAM_GATE prêts, 2 en attente d’identités ;
- 3 datasets, 2 136 fixtures d’évaluation, 12 816 prédictions ;
- transfert, spécifique, pooled, Poisson, Dixon–Coles et LOLO exécutés ;
- 5 000 bootstraps groupés, échantillons exactement appariés ;
- 15 contrôles négatifs enregistrés ;
- 0 appel, 0 crédit, 0 candidat, 0 pari ;
- package honnête en attente des gates ;
- `PRODUCTION_LOCKED`.

## Décision

`WAITING_FOR_EXTERNAL_GATES` est un état normal tant que Serie A/UCL, joueurs,
lineups et marchés attendent leur couverture. Les workflows poursuivent
automatiquement après chaque évolution durable. Le résultat scientifique
actuel est `NO_EXTERNAL_VALIDATED_EDGE`.
