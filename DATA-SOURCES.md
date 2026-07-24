# Sources de données

Dernière revue : 2026-07-24.

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

Statut : `PARTIAL` — source prospective configurée, sans archive réelle.

- le secret `ODDS_API_KEY` existe déjà dans GitHub Actions ;
- 86 événements figurent dans le ledger historique, mais aucun
  `odds_*.parquet` réel n'est archivé au 2026-07-24 ;
- plafond local : 15 000 crédits par mois, arrêt sous 500 crédits ;
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
