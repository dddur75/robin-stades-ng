# Expansion prospective aux cinq grands championnats

## Périmètre

La source machine est `configs/prospective_observatory_v1.json`. Elle active :

| Compétition | ID API-Football | Profil |
|---|---:|---|
| Ligue 1 | 61 | `FULL` |
| Premier League | 39 | `DEEP_FULL_ODDS_REDUCED` |
| Liga | 140 | `DEEP_FULL_ODDS_REDUCED` |
| Bundesliga | 78 | `DEEP_FULL_ODDS_REDUCED` |
| Serie A | 135 | `DEEP_FULL_ODDS_REDUCED` |

Le workflow 60 ne contient plus de compétition codée en dur. Il produit une
estimation signée de 15 appels maximum, puis traite les cinq entrées dans le
même état durable. Une erreur est isolée dans la ligne de la ligue concernée.

## Audit initial

Chaque ligue dispose de trois transports API-Football au maximum :

1. quota `/status` ;
2. saison/compétition ;
3. fixtures des trente prochains jours.

L’audit initial consomme exactement zéro crédit The Odds API. Il publie saison,
horizon, fixtures reçues/admissibles, équipes, identités, kickoffs, quota,
objets/octets R2, inserts/doublons PostgreSQL et gate préliminaire.

## Stockage et replay

Les payloads restent append-only sous :

```text
prospective-deep-data/schema-v1/
  competition=<competition>/
  season=<season>/
  fixture=<fixture>/
```

PostgreSQL ne stocke que les index, relations, tentatives, budgets et
projections. Le workflow 65 rejoue R2 sans fournisseur. Le workflow 66 exige
la parité reçus/index/budgets/projections, audite les identités depuis R2 et
PostgreSQL, puis reconstruit Robin Experience.

## Gates

Une compétition ne devient active que si :

- au moins une fixture est admissible ;
- les deux identités de chaque fixture sont vérifiées ;
- les kickoffs UTC sont fiables ;
- R2 et PostgreSQL sont cohérents ;
- le replay est vert ;
- tous les caps et réserves sont respectés.

Les seuls statuts sont `ACTIVE_FULL`, `ACTIVE_ODDS_REDUCED`,
`BLOCKED_PROVIDER`, `BLOCKED_IDENTITY`, `BLOCKED_BUDGET` et `DISABLED`.

## Projection centrale

Le rapport compact
`reports/prospective-observatory/five-league-cost-projection.json` retient
1 752 fixtures par saison, 63 859 appels API-Football dans le scénario central
sans retry et 1 296 crédits Odds. Les moyennes centrales sont 174,96 appels
API-Football par jour et 24,92 crédits Odds par semaine. Les octets et le coût
de stockage restent `null` avant mesure réelle ; aucune précision artificielle
n’est inventée.

## Interdictions

- aucun backfill historique ;
- aucune recherche de pattern ;
- aucune promotion de modèle ;
- aucune fenêtre future forcée ;
- aucun payload brut dans Git ;
- aucune suppression R2 ;
- aucun pari réel, bookmaker ou publication sociale.
