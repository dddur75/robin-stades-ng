# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-2-shadow-data`
Mode : `SHADOW`
Paris réels : `PRODUCTION_LOCKED`

## État global

`PARTIAL` — le Jalon 2 livre une infrastructure prospective autonome, une
migration legacy mesurée, des modèles interprétables et le Cockpit Shadow V1.
Cette capacité ne constitue ni une validation de rentabilité, ni une autorisation
de pari réel.

Statut shadow : `SHADOW_INFRASTRUCTURE_READY`.

## Jalons

| Jalon | Statut | Preuve principale |
|---|---|---|
| 0 — audit initial | `VERIFIED` | `docs/audits/JALON-0-AUDIT.md` |
| 1 — fondation data temporelle | `VERIFIED` | PR #1 fusionnée par squash |
| 2 — collecte, migration et shadow | `VERIFIED` | `docs/audits/JALON-2-REPORT.md` |
| 3 — accumulation prospective | `NOT_STARTED` | exige du temps calendaire |
| 4 à 9 | `NOT_STARTED` | hors périmètre |

## Capacités Jalon 2

- fournisseurs interchangeables typés : The Odds API, API-Football et mock ;
- collecte Ligue 1 selon neuf fenêtres de J-7 à M-10, budget et déduplication ;
- stockage brut et snapshots append-only, secrets expurgés ;
- cinq workflows GitHub Actions planifiés, manuels et non concurrents ;
- 37 024 correspondances UUID legacy sans collision ni fichier source réécrit ;
- Elo, Poisson, Dixon-Coles, consensus et baseline de marché en shadow-only ;
- prédictions et décisions immuables, candidats comme rejets journalisés ;
- validation walk-forward OOS avec marge, bankroll, drawdown et IC 95 % ;
- Cockpit V1 à six vues avec séparation stricte des origines.

## Résultats mesurés

- 36 423 lignes legacy examinées ;
- couverture certaine UUID : 98,668 % ;
- collisions, ambiguïtés et non-résolus : 0 ;
- meilleure observation OOS : Over 2,5, ROI +2,83 %, IC 95 %
  `[-8,00 % ; +13,66 %]`, donc `INCONCLUSIVE_OOS` ;
- aucune stratégie promue ;
- collecte réelle non encore prouvée dans l'artefact Cockpit : les démonstrations
  restent étiquetées et l'état demeure `SHADOW_INFRASTRUCTURE_READY`.

## Verrous maintenus

- `real_bets_enabled: false` ;
- aucune connexion bookmaker ni mise financière ;
- identités `PROBABLE` exclues des modèles exigeant une certitude ;
- `SHADOW_COLLECTION_ACTIVE` réservé à une preuve de snapshots réels ;
- `LIVE_SHADOW_VALIDATED` interdit sans période prospective suffisante.

## Action utilisateur

Aucune. Voir `USER-ACTION.md`.
