# Sources de données

## API-Football v3 — Jalon 5

Statut : `ADAPTER_ONLY` avant exécution live de la branche.

L’API officielle `https://v3.football.api-sports.io` est appelée avec
`x-apisports-key`. Les endpoints intégrés incluent leagues, teams, players,
squads, fixtures, events, statistics, lineups, standings, injuries, coaches et
transfers. La pagination utilise `paging.current`, `paging.total` et `page`.

Les identifiants des six compétitions sont validés par réponse `/leagues`; ils
ne sont pas supposés dans la matrice. Voir
`docs/data-sources/API-FOOTBALL-COVERAGE-MATRIX.md`.

Dernière revue : 2026-07-24.

## Situation Jalon 4

| Source | Statut réel | Usage |
|---|---|---|
| The Odds API | `LIVE_PIPELINE_VERIFIED` | fixtures et cotes 1X2/totaux |
| API-Football | `ADAPTER_ONLY` | enrichissement futur, secret absent |
| Football-Data.co.uk | `LEGACY_SOURCE` | contrôle historique séparé |

The Odds API a produit 9 fixtures et 2 snapshots réels. API-Football n’a produit
aucune donnée live et n’est jamais présenté autrement. Les payloads live sont
adressés par SHA-256 et conservés dans `shadow-data`, puis PostgreSQL dès que le
secret `DATABASE_URL` est disponible.

Décision détaillée : `docs/data-sources/JALON-2-SOURCE-DECISION.md`.

## Décision Jalon 2

| Besoin | Source retenue | État |
|---|---|---|
| données sportives profondes | API-Football | adaptateur prêt, clé optionnelle absente |
| cotes prospectives et fixtures courtes | The Odds API | secret GitHub existant |
| contrôle historique | Football-Data.co.uk | actif, origine legacy |

La collecte initiale est limitée à la Ligue 1. Aucun abonnement n'a été souscrit.
Le budget The Odds API est borné à 450 crédits par mois avec arrêt préventif
sous 25 crédits. Les marchés demandés sont `h2h` et `totals`; les marchés non
couverts ne sont pas synthétisés.

## Football-Data.co.uk

Statut : `PARTIAL` — source historique principale.

- couverture locale : 36 423 matchs, 9 ligues, 11 saisons, du 2015-07-31 au
  2026-05-24 ;
- usage : résultats, statistiques de match et cotes historiques ;
- limite : le dataset legacy ne conserve ni réponse brute, ni heure précise
  d'observation des cotes, ni provenance par ligne ;
- risque : 24 segments et 7 936 valeurs sont classés `SUSPECT_ZERO` ;
- décision : conserver pour audit et baselines, exclure les valeurs suspectes des
  modèles concernés, puis recollecter via le stockage brut append-only ;
- vigilance : les cotes Pinnacle sont signalées obsolètes par la source depuis le
  2025-07-23.

Référence : https://www.football-data.co.uk/data.php

## Understat

Statut : `UNVERIFIED` — enrichissement xG best effort.

- extraction HTML non officielle dans `agents/agent_understat.py` ;
- schéma et disponibilité sans contrat ni SLA ;
- aucune dépendance bloquante ne doit reposer sur cette source ;
- toute future observation devra respecter le contrat brut immuable.

## The Odds API

Statut : `PARTIAL` — source prospective configurée ; preuve réelle à confirmer.

- le secret `ODDS_API_KEY` existe déjà dans GitHub Actions ;
- 86 événements figurent dans le ledger historique, mais aucun
  `odds_*.parquet` réel n'est archivé au 2026-07-24 ;
- plafond Jalon 2 : 450 crédits par mois, arrêt sous 25 crédits ;
- le Jalon 1 fournit le schéma de snapshot, l'interface fournisseur, les règles
  d'idempotence et un mock complet ; aucune nouvelle clé ou souscription requise ;
- une clé active débloquera les observations réelles, pas la mise automatique ni
  la validation d'une stratégie.

Références : https://the-odds-api.com/ et
https://the-odds-api.com/liveapi/guides/v4/

## Contrat commun d'intégration

Toute nouvelle source doit fournir :

- identifiants fournisseur stables et correspondances vers UUID internes ;
- `requested_at`, `received_at`, `observed_at`, version de schéma et run ;
- payload brut immuable, hashé et rejouable ;
- paramètres expurgés de tout secret ;
- conditions d'utilisation, limites et coût documentés ;
- contrôles de volume, fraîcheur, cohérence, conflits et identités non résolues.
