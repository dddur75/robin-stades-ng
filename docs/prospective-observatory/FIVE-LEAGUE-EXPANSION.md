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

## Pilotes réels bornés du 28 juillet 2026

Le pilote initial `30371041646` avait activé Ligue 1, Premier League et
Serie A. La Liga avait échoué sur une fixture antérieure à l’horizon et la
Bundesliga avait répondu normalement sans fixture dans l’ancien horizon de
30 jours. Aucun de ces deux cas ne constitue désormais une erreur fournisseur.

Après correction du filtrage et passage de l’horizon de découverte à 45 jours,
deux probes ciblés ont fermé les gates :

| Ligue | Run | Appels | Fixtures reçues/admissibles | Équipes | Identités | Kickoffs | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Liga | `30387868451` | 3 | 40/30 | 20 | 60/60 | 30/30 | `ACTIVE_ODDS_REDUCED` |
| Bundesliga | `30390501082` | 3 | 19/19 | 18 | 38/38 | 19/19 | `ACTIVE_ODDS_REDUCED` |

Les deux réponses fournisseur sont valides, sans erreur de schéma et sans
payload vide. Elles ajoutent respectivement 60 objets R2 / 67 959 octets et
38 objets / 33 595 octets, puis 30 et 19 index PostgreSQL. Les deux tentatives
Bundesliga précédentes (`30388379467` et `30389253163`) ont échoué avant le
premier transport fournisseur : elles ont consommé 0 appel et 0 crédit.

Le budget total de cette mission est donc exactement :

```text
API_FOOTBALL_CALLS_TOTAL=6
ODDS_API_CREDITS_TOTAL=0
```

Aucun appel n’a été répété pour Ligue 1, Premier League ou Serie A. Aucune
fenêtre profonde future n’a été forcée.

## Activation automatique

Le workflow quotidien conserve `competition=ALL`. Les tests construisent
d’abord une compétition en `WAITING_FOR_FIXTURES`, puis lui présentent un
calendrier valide. Sans mutation de code ou de configuration, le workflow :

1. découvre les fixtures ;
2. résout les identités ;
3. crée les fenêtres idempotentes ;
4. passe la compétition en `ACTIVE_ODDS_REDUCED` ;
5. met à jour le modèle de présentation Robin Experience ;
6. évite toute duplication au passage suivant.

Le planificateur fournisseur-free `30393664912` confirme 78 fixtures suivies,
3 615 fenêtres canoniques, 0 fenêtre due et 0 appel. Les 18 échéances déjà
passées sont marquées comme manquées ; elles ne sont jamais forcées après
leur cutoff.

## Mutualisation du quota

Le coût théorique reste de trois transports par ligue : `/status`, résolution
de saison et fixtures. Un cycle complet représente donc 15 appels maximum ;
les deux probes séparés en représentent 6. La revue n’a pas mutualisé
`/status` entre des runs indépendants et n’a pas réutilisé une saison sans
reçu de fraîcheur : 15 estimés / 15 physiques pour un cycle complet, soit
0 économie artificielle. La provenance a priorité sur une optimisation
facultative.

## Replay et preuves finales

Le replay autonome `30396732141` puis le rapport composite `30403466803` sont
verts et sans fournisseur. Le dernier état vérifie :

- 78 fixtures reconstruites sur 78 et 156 slots d’identité résolus sur 156 ;
- 96 payloads et 96 reçus live, 279 objets physiques uniques et 652 026
  octets ;
- 87 objets de récupération / 347 848 octets, avec namespace vérifié ;
- zéro hash divergent, perte, suppression ou lag ;
- 3 615 fenêtres canoniques ; aucune fenêtre n’était due lors du passage
  fournisseur-free ;
- 12 tables PostgreSQL, zéro payload brut en base et reconstruction complète ;
- seconde passe avec 0 insert et 96 doublons évités ;
- 0 appel fournisseur et 0 crédit Odds pendant replay, gates, audit des
  identités et reconstruction de Robin Experience ;
- 0 candidat, 0 décision, 0 mise et aucune promotion de modèle.

Le rapport de gates évalue 390 combinaisons fixture/gate. Les gates profondes
restent honnêtement `BLOCKED_BY_COVERAGE` tant que leurs fenêtres ne sont pas
échues ; ce statut scientifique ne remet pas en cause l’activation du registre
des cinq compétitions.

Les preuves compactes suivies sont :

- `reports/prospective-observatory/five-league-expansion-summary.json` ;
- `reports/prospective-observatory/five-league-r2-replay-audit.json` ;
- `reports/prospective-observatory/five-league-cost-projection.json` ;
- `reports/ux/team-identity-provenance.json` ;
- `reports/jalon12/next-due-windows.json`.

## Résultat par ligue

| Ligue | Fixtures | Profil | Gate | Raison |
|---|---:|---|---|---|
| Ligue 1 | 9 | `FULL` | `ACTIVE_FULL` | Fixtures, identités, stockage et replay vérifiés |
| Premier League | 10 | `DEEP_FULL_ODDS_REDUCED` | `ACTIVE_ODDS_REDUCED` | Fixtures et identités vérifiées, cotes sous budget réduit |
| Liga | 30 | `DEEP_FULL_ODDS_REDUCED` | `ACTIVE_ODDS_REDUCED` | Probe ciblé valide sur l’horizon de 45 jours |
| Bundesliga | 19 | `DEEP_FULL_ODDS_REDUCED` | `ACTIVE_ODDS_REDUCED` | Calendrier trouvé dans l’horizon de 45 jours |
| Serie A | 10 | `DEEP_FULL_ODDS_REDUCED` | `ACTIVE_ODDS_REDUCED` | Fixtures et identités vérifiées, cotes sous budget réduit |

Verdict réel :

```text
FIVE_LEAGUE_PROSPECTIVE_EXPANSION_READY
```

La PR #20 peut quitter le brouillon puis être fusionnée par merge commit après
confirmation de la CI et de l’absence d’objection majeure.
