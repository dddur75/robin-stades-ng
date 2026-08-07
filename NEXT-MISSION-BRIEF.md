# Next Mission Brief — E3A puis préparation E3B

## Configuration

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
PR À REVOIR = E2 Targeted Fixes and E3A Launch V1
BRANCHE À REVOIR = codex/e2-targeted-fixes-e3a-launch-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

La mission est compilée mais n'a pas été exécutée.

## Entrée autoritative

- PR #34 fusionnée au merge commit `ba928d096e12dbffaea96bbd67770a313257433a` ;
- E2 : 100 fixtures, 161 GET, 6 434 224 octets, replay byte-identique ;
- fixture `1208603` : `PROVIDER_INCONSISTENCY`, 40/40 identités de part et
  d'autre mais intersection 39, `missing_player_stat_row = UNKNOWN` ;
- Calendar : `CALENDAR_STRICT_ASOF_MECHANICALLY_VALIDATED`, preuve synthétique
  seulement ;
- huit candidates E3A, `PLAYER_STATISTICS` encore bloquée ;
- E3A, E3B et masques non exécutés.

Le contrat par capacité reste
`configs/data/capability-scoped-evidence-ladder-v2.json`. Ne lancer ni E1A ni
une troisième architecture et ne jamais reclasser les 149
`ABSENCE_CAUSE_UNKNOWN`.

## Mission suivante

1. revoir et fusionner la PR de correctifs ;
2. exécuter E3A sur une compétition-saison gelée pour les seules candidates ;
3. exécuter E3B sur cinq ligues seulement si chaque gate E3A requis passe ;
4. lancer ensuite le recensement général des champs non mappés ;
5. construire le registre canonique des tags ;
6. benchmarker puis construire les masques atomiques ;
7. tester les propriétés seules puis les paires compatibles ;
8. s'arrêter avant les millions de triples.

Ne jamais lancer de triple avant des masques validés, des prix historiques
admissibles, un support minimal défini, des folds temporels disponibles et un
contrat statistique gelé.
