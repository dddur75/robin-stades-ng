# Rapport d’audit — Jalon 3 · Activation live shadow

Date : 2026-07-24
Branche : `codex/jalon-3-live-shadow-activation`
Statut shadow : `SHADOW_COLLECTION_ACTIVE`
Paris réels : `PRODUCTION_LOCKED`

## Résultat

La PR #2 a été relue, commentée, rendue prête puis fusionnée par squash dans
`main` au commit `f3dc90fe33d6a7ea7d4392a61d39c07fa173fceb`. Les workflows ont ensuite
été déclenchés manuellement sur `main`, puis sur la branche Jalon 3 après
durcissement de la persistance.

The Odds API a répondu avec des données Ligue 1 réelles et authentifiées :

- 9 fixtures de la première journée 2026–2027 ;
- 2 snapshots de cotes réellement distincts ;
- 90 quotes et 22 bookmakers par snapshot, marchés `1X2` et `TOTAL_GOALS` ;
- 1 prédiction `MARKET_BASELINE_ONLY`, fondée uniquement sur le snapshot live ;
- 1 décision shadow rejetée, mise fictive nulle ;
- 8 fixtures sans cote bloquées, sans prédiction sportive synthétique.

La collecte est active et le stockage est démontré entre deux runners
éphémères. Aucune période prospective suffisante n’existe encore pour conclure
à une performance ou utiliser `LIVE_SHADOW_VALIDATED`.

## Exécutions probantes

| Pipeline | Run | Résultat | Preuve |
|---|---:|---|---|
| fixtures | [30094740235](https://github.com/dddur75/robin-stades-ng/actions/runs/30094740235) | `WORKFLOW_SUCCESS_LIVE_DATA` | 9 fixtures, hash brut stable |
| odds A | [30094948631](https://github.com/dddur75/robin-stades-ng/actions/runs/30094948631) | `WORKFLOW_SUCCESS_LIVE_DATA` | état runner A restauré, 1 snapshot |
| odds B | [30095046115](https://github.com/dddur75/robin-stades-ng/actions/runs/30095046115) | `WORKFLOW_SUCCESS_LIVE_DATA` | second payload distinct, 2 snapshots |
| pré-match A | [30095111573](https://github.com/dddur75/robin-stades-ng/actions/runs/30095111573) | `WORKFLOW_SUCCESS_LIVE_DATA` | 1 baseline, 8 blocages, 1 décision |
| pré-match B | [30095193298](https://github.com/dddur75/robin-stades-ng/actions/runs/30095193298) | `WORKFLOW_SUCCESS_LIVE_DATA` | 0 ajout, idempotence confirmée |
| santé | [30095263615](https://github.com/dddur75/robin-stades-ng/actions/runs/30095263615) | `PASSED` | 0 alerte critique |

Un run odds, [30094795509](https://github.com/dddur75/robin-stades-ng/actions/runs/30094795509),
a échoué avant tout appel fournisseur : l’en-tête GitHub était transmis vers
l’URL de stockage signée. Le téléchargement suit désormais les redirections en
retirant cet en-tête hors de `api.github.com`. Les six runs ci-dessus prouvent
la correction ; cet incident n’a consommé aucun crédit fournisseur.

## Idempotence et vérité temporelle

- même payload fixtures : une seule copie binaire, trois observations
  append-only ;
- deux appels odds : deux hashes différents, donc deux snapshots légitimes ;
- doublons exacts de snapshot : 0 ;
- second pré-match : prédictions `1 → 1`, décisions `1 → 1` ;
- chaque observation conserve fournisseur, endpoint, instant UTC, hash brut,
  run d’ingestion et origine ;
- aucune donnée legacy n’alimente la baseline live ;
- aucun règlement post-match n’a été forcé : aucune décision éligible n’existe.

## Verrous

`real_bets_enabled` reste à `false`. Il n’existe ni connexion bookmaker, ni
ordre financier, ni promotion automatique de stratégie. Le Jalon 3 active
l’observation prospective, pas la production de paris.
