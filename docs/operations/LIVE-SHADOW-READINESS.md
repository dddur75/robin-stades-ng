# Readiness opérationnelle — Live Shadow

Date : 2026-07-24
Décision : `SHADOW_COLLECTION_ACTIVE`
Production : `PRODUCTION_LOCKED`

| Contrôle | État | Preuve / limite |
|---|---|---|
| PR Jalon 2 fusionnée | `PASS` | PR #2 squashée dans `main` |
| Workflows planifiés actifs | `PASS` | cinq workflows présents sur `main`, exécutions manuelles réelles réussies |
| Authentification fournisseur | `PASS` | `ODDS_API_KEY` présente, appel HTTP 200, secret absent des logs |
| Fixtures réelles | `PASS` | 9 rencontres Ligue 1 2026–2027 |
| Cotes réelles | `PASS` | 2 snapshots, 180 quotes, 22 bookmakers |
| Persistance inter-runners | `PASS` | artifact `shadow-state-30094740235` restauré par le runner odds |
| Rétention bornée | `PASS` | 2 copies, 30 jours, 29 939 octets |
| Idempotence snapshot | `PASS` | 0 doublon exact ; 2 payloads réellement différents |
| Idempotence pré-match | `PASS` | second run : 0 prédiction et 0 décision ajoutées |
| Provenance complète | `PASS` | source, endpoint, UTC, hash, run, origine |
| Cockpit live par défaut | `PASS` | données live affichées, legacy explicitement étiqueté, démo opt-in |
| Fraîcheur | `PASS` | observations datées du 24 juillet 2026, première journée du 21 au 23 août |
| Cohérence calendrier | `PASS` | affiches et horaires concordent avec la programmation officielle LFP |
| Couverture sportive | `PARTIAL` | cotes disponibles pour 1 fixture sur 9 au moment des appels |
| Baseline autorisée | `PARTIAL` | 1 `MARKET_BASELINE_ONLY`, 8 sorties bloquées |
| Règlement post-match | `NO OUTPUT` | aucune décision éligible ; appel fournisseur volontairement évité |
| Validation statistique prospective | `PENDING` | accumulation calendaire nécessaire |
| Paris réels | `LOCKED` | `PRODUCTION_LOCKED`, aucune exécution financière |

## Fournisseurs

| Fournisseur | Adaptateur | Secret | Appel authentifié | Données live | Persistance | État |
|---|---|---|---|---|---|---|
| The Odds API | prêt | présent | oui | oui | oui | `LIVE_PIPELINE_VERIFIED` |
| API-Football | prêt | absent | non | non | non | `ADAPTER_ONLY` |
| Football-Data.co.uk | prêt | non requis | non exécuté au Jalon 3 | non | non | `ADAPTER_ONLY` |

L’absence d’`API_FOOTBALL_KEY` n’est pas bloquante : The Odds API couvre la
collecte minimale réelle. Le second fournisseur reste un enrichissement
optionnel, sans achat automatique.

## Exploitation et reprise

L’état canonique voyage dans un artifact `shadow-state-<run_id>`. Chaque
workflow restaure le dernier artifact disponible, exécute son étape, puis publie
un nouvel état. La concurrence globale `shadow-state` empêche deux écritures
simultanées. Les deux artifacts les plus récents sont conservés 30 jours.

En cas d’échec, conserver l’artifact et le run, corriger la cause, puis relancer
avec la même clé d’idempotence. Ne jamais modifier un payload ou un snapshot
existant.
