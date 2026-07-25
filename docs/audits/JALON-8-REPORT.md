# Jalon 8 — rapport d’audit

## Portée

Validation externe multi-ligues, sans nouvel appel fournisseur, sans nouveau
marché et sans pari réel.

## Preuves opérationnelles

- run GitHub : `30167355305`, succès en 8 min 33 s ;
- code source : `959245089d13935e9a6d80b5614f50b98933e8bc` ;
- source durable publiée : `historical-data@15de864` ;
- stockage mesuré avant analytique : 379 897 417 octets ;
- stockage mesuré après analytique : 383 367 123 octets ;
- seuil warning : 750 000 000 ; pause : 900 000 000 ;
- protocole gelé avant résultats :
  `53932dff3a30038668230b493746d3d7e7f45cbd4c9f967191e934da853645d2` ;
- 3 TEAM_GATE prêts, 2 en attente d’identités ;
- 3 datasets, 2 136 fixtures d’évaluation, 12 816 prédictions ;
- transfert, spécifique, pooled, Poisson, Dixon–Coles et LOLO exécutés ;
- 5 000 bootstraps groupés, échantillons exactement appariés ;
- 15 contrôles négatifs enregistrés ;
- 0 appel, 0 crédit, 0 candidat, 0 pari ;
- PostgreSQL connecté en SSL, révision `0004_jalon5_deep_data_factory`,
  58 330 lignes synchronisées, 7 tables vérifiées et aucune fuite de secret ;
- package honnête en attente des gates ;
- `PRODUCTION_LOCKED`.

## Décision

`WAITING_FOR_EXTERNAL_GATES` est un état normal tant que Serie A/UCL, joueurs,
lineups et marchés attendent leur couverture. Les workflows poursuivent
automatiquement après chaque évolution durable. Le résultat scientifique
actuel est `NO_EXTERNAL_VALIDATED_EDGE`.
