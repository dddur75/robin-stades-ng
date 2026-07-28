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
3. fixtures des quarante-cinq prochains jours.

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

Les statuts distinguent désormais explicitement :

- `ACTIVE_FULL` et `ACTIVE_ODDS_REDUCED` pour une cadence active ;
- `WAITING_FOR_FIXTURES` pour une réponse valide sans calendrier admissible ;
- `NO_FIXTURES_IN_CURRENT_HORIZON` lorsque les réponses observées restent hors
  des quarante-cinq jours de découverte ;
- `BLOCKED_PROVIDER_ERROR` uniquement pour une erreur HTTP,
  d’authentification, de timeout ou de schéma ;
- `BLOCKED_IDENTITY`, `BLOCKED_BUDGET` et `DISABLED` pour les autres verrous.

Le libellé historique `BLOCKED_PROVIDER` n’est plus produit.

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

## Pilote réel borné du 28 juillet 2026

Le registre réel est le run GitHub Actions `30371041646`. Son estimation
signée autorisait 15 appels API-Football au maximum, soit exactement trois par
ligue, et zéro crédit Odds. Le ledger durable confirme 15 appels physiques :
le compteur de 12 du premier rapport compact sous-comptait les trois appels
consommés avant l’exception Liga ; ce défaut de comptage a été corrigé sans
relancer le registre.

| Ligue | Fixtures | Équipes | Saison | Dates des fixtures | Identités | Kickoffs | Gate | Profil |
|---|---:|---:|---:|---|---:|---:|---|---|
| Ligue 1 | 9 | 18 | 2026 | 21–23 août 2026 | 18/18 | 9/9 | `ACTIVE_FULL` | `FULL` |
| Premier League | 10 | 20 | 2026 | 21–24 août 2026 | 20/20 | 10/10 | `ACTIVE_ODDS_REDUCED` | `DEEP_FULL_ODDS_REDUCED` |
| Liga | 0 | 0 | — | — | 0/0 | 0/0 | `BLOCKED_PROVIDER` | `DEEP_FULL_ODDS_REDUCED` |
| Bundesliga | 0 | 0 | 2026 | aucune fixture publiée dans l’horizon | 0/0 | 0/0 | `BLOCKED_PROVIDER` | `DEEP_FULL_ODDS_REDUCED` |
| Serie A | 10 | 20 | 2026 | 22–24 août 2026 | 20/20 | 10/10 | `ACTIVE_ODDS_REDUCED` | `DEEP_FULL_ODDS_REDUCED` |

La Liga a rencontré une validation sur une fixture antérieure à l’horizon.
Le filtrage précède désormais la construction du contrat, mais le pilote
initial n’a pas été relancé afin de ne jamais dépasser trois appels par ligue.
La Bundesliga a répondu sans fixture sur les trente jours demandés. Ces deux
blocages n’ont pas empêché l’activation des trois autres compétitions.

Le planificateur `30373123502` a créé 1 361 fenêtres actives et constaté
zéro fenêtre due et zéro fenêtre manquée. Les collecteurs joueurs/blessures
`30373961624`, lineups/formations `30374838033` et Odds `30375023103` ont tous
retourné `NO_DUE_WINDOW_SUCCESS` : zéro appel supplémentaire, zéro crédit
Odds, zéro tentative et zéro écriture de capture. Aucune fenêtre future n’a été
forcée.

## Preuves finales

Le replay autonome `30375179062` puis le rapport final `30383448949` sont
verts et sans fournisseur. Le dernier état vérifie :

- 29 fixtures reconstruites sur 29 et 58 slots d’identité résolus sur 58 ;
- 47 payloads/reçus live, 132 objets physiques uniques et 264 184 octets ;
- zéro hash divergent, perte, suppression ou lag ;
- 1 361 fenêtres actives, 531 fenêtres héritées inactives et 47 observations
  temporellement admissibles ;
- 12 tables PostgreSQL, zéro payload brut en base, replay de second passage
  avec 0 insert et 47 doublons évités ;
- 0 appel fournisseur et 0 crédit Odds pour le replay, les gates, les
  identités et la reconstruction Robin Experience ;
- 0 candidat, 0 décision, 0 mise et aucune promotion de modèle.

Les preuves compactes suivies sont :

- `reports/prospective-observatory/five-league-expansion-summary.json` ;
- `reports/prospective-observatory/five-league-r2-replay-audit.json` ;
- `reports/prospective-observatory/five-league-cost-projection.json` ;
- `reports/ux/team-identity-provenance.json` ;
- `reports/jalon12/next-due-windows.json`.

Verdict réel :

```text
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_PARTIAL
```

La PR #20 reste en brouillon et non fusionnée. Le verdict est partiel parce
que la Liga et la Bundesliga n’ont aucune fixture active issue de cet audit,
pas à cause d’un défaut R2, PostgreSQL, replay, identité, budget ou dashboard.
