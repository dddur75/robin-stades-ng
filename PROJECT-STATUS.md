# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/jalon-3-live-shadow-activation`
Mode : `SHADOW`
Paris réels : `PRODUCTION_LOCKED`

## État global

`PARTIAL` — la collecte prospective authentifiée est active et persistante.
Cette capacité ne constitue ni une validation de rentabilité, ni une autorisation
de pari réel. La PR Jalon 3 reste à fusionner dans `main`.

Statut shadow : `SHADOW_COLLECTION_ACTIVE`.

## Jalons

| Jalon | Statut | Preuve principale |
|---|---|---|
| 0 — audit initial | `VERIFIED` | `docs/audits/JALON-0-AUDIT.md` |
| 1 — fondation data temporelle | `VERIFIED` | PR #1 fusionnée par squash |
| 2 — collecte, migration et shadow | `VERIFIED` | PR #2 fusionnée par squash |
| 3 — activation live et accumulation | `ACTIVE` | `docs/audits/JALON-3-LIVE-ACTIVATION.md` |
| 4 à 9 | `NOT_STARTED` | hors périmètre |

## Capacités Jalon 3

- appel authentifié The Odds API et données Ligue 1 2026–2027 réelles ;
- collecte Ligue 1 selon neuf fenêtres de J-7 à M-10, budget et déduplication ;
- stockage brut et snapshots append-only, secrets expurgés, hashes de payload ;
- persistance explicite par GitHub Artifact entre runners éphémères ;
- cinq workflows GitHub Actions planifiés, manuels et non concurrents ;
- 37 024 correspondances UUID legacy sans collision ni fichier source réécrit ;
- prédictions live limitées à `MARKET_BASELINE_ONLY` si une cote existe ;
- prédictions et décisions immuables et idempotentes ;
- Cockpit V1 live par défaut avec séparation stricte des origines.

## Résultats mesurés

- 9 fixtures Ligue 1 réelles ;
- 2 snapshots de cotes distincts, 180 quotes, 22 bookmakers ;
- 1 baseline marché, 1 décision rejetée, 8 sorties bloquées ;
- 0 doublon exact, second pré-match sans nouvel enregistrement ;
- quota : 8 consommés, 19 992 restants, prévision 720 crédits/mois ;
- artifact canonique : `shadow-state-30095263615`.

## Verrous maintenus

- `real_bets_enabled: false` ;
- aucune connexion bookmaker ni mise financière ;
- identités `PROBABLE` exclues des modèles exigeant une certitude ;
- `LIVE_SHADOW_VALIDATED` interdit sans période prospective suffisante.

## Action utilisateur

Valider et fusionner la PR brouillon Jalon 3 après revue. Voir
`USER-ACTION.md`.
