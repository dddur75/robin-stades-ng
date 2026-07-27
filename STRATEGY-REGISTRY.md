# Registre des stratégies

## Strategy Factory Jalon 5

| Stratégie | Modèle | Période | N | ROI | Statut |
|---|---|---|---:|---:|---|
| Edge 5 %, mise fixe | Elo V1 | OOS 2024–2025 | 4 139 | -8,55 % | `REJECTED` |

Le résultat est négatif et ne déclenche aucune promotion. La stratégie reste
historique et simulée ; `PRODUCTION_LOCKED` est obligatoire.

| Famille | Version | Usage | Statut |
|---|---:|---|---|
| Vague 1 | 1.0 | 66 hypothèses pré-enregistrées | `PARTIAL` |
| Vague 1B | 1.0 | famille annexe séparée | `PARTIAL` |
| Vague 2 | 1.0 | exploration combinatoire brute | `UNVERIFIED` |
| Vague 2B | 1.0 | référence ajustée par cellules de marché | `PARTIAL` |
| Confrontation CP-01 à CP-10 | 1.0 | suivi prospectif | `IN_PROGRESS` |
| Favori marché | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Favori domicile | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Seuil probabilité 55 % | J2-OOS | consensus Elo–Poisson | `REJECTED_OOS` |
| Value simple edge 4 % | J2-OOS | prix dé-viggé | `REJECTED_OOS` |
| Over 2,5 value | J2-OOS | Poisson vs marché | `INCONCLUSIVE_OOS` |
| BTTS | J2-OOS | odds legacy absentes | `INSUFFICIENT_SAMPLE` |

Règles globales :

- mise réelle interdite ;
- holdout 2025-26 scellé tant qu'une décision formelle ne l'ouvre pas ;
- une stratégie rentable en exploration reste `UNVERIFIED` ;
- le passage à `PRODUCTION_READY` exige hors échantillon, robustesse, coûts,
  concentration des gains, drawdown et shadow test.

## Burn-in Jalon 4

Zéro stratégie est promue. Une décision live a été rejetée et aucun pari shadow
n’est accepté ou réglé. Le legacy, l’OOS historique et le prospectif live restent
trois populations séparées.

## Strategy Lab V1

Les seuils d'edge 1X2 2 %, 4 % et 6 % sont testés par modèle avec intervalle
bootstrap et correction Bonferroni. Les résultats ne peuvent être que
`INCONCLUSIVE` ou `REJECTED` dans ce cycle. Aucun combiné et aucune stratégie
réelle ne sont ouverts.

## Strategy Lab V2

Le protocole borné couvre 1X2, Over/Under 2,5 et BTTS, edges 3/5/7 %, mises
plates ou Kelly 0,10 plafonné à 1 unité et risque quotidien 3 unités. Les
paramètres sont arrêtés avant lecture des périodes exposées. Aucun prix BTTS
historique exploitable n'est artificiellement créé et aucune stratégie n'est
promue.
## Strategy Lab V3 externe

13 hypothèses sont préenregistrées. Le `MARKET_GATE` est indisponible :
0 backtest économique, 0 candidat live, 0 candidat modèle et
`NO_EXTERNAL_VALIDATED_EDGE`. Aucun test BTTS n’est exécuté sans prix fiable.

## Strategy Lab V4

Hypothèses bornées : 1X2 edges 2/3/5 %, probabilités 55/65 %, accord de modèles;
totals edges 3/5 % et accord Poisson/Dixon-Coles. Aucun combiné. Les filtres
joueur exigent PLAYER_GATE READY. `NO_BET_DEFAULT = true`.

## Pattern Research V1

| Famille | Marché | Evidence scope | Statut |
|---|---|---|---|
| Tranches de marché | 1X2 domicile/nul/extérieur, O/U 2,5 | `DISCOVERY_EXPOSED` | `NO_FDR_SURVIVOR` |
| Conditions testées | cote, marge, catégorie de prix, compétition | `DISCOVERY_EXPOSED` | `EXECUTED_700` |
| Équipe/forme/Elo | non testé dans V1 | aucun | `NOT_TESTED_IN_V1` |
| Calendrier/repos | non testé dans V1 | aucun | `NOT_TESTED_IN_V1` |
| Joueurs/tactique | non testé dans V1 | aucun | `NOT_TESTED_IN_V1` |
| Latéralité | non testé dans V1 | aucun | `FOOTEDNESS_DATA_GATE` |

La campagne V1 a exécuté 700 règles : 118 sont positives brutes et 24 survivent
au walk-forward brut, mais aucune ne survit à la FDR. Il reste donc zéro pattern
`LIVE_SHADOW_CANDIDATE`, `LIVE_SHADOW` ou `VALIDATED`. Le verdict est
`JALON_10_NO_ROBUST_PATTERN_FOUND`.

Sous-verdict :
`NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE`. Il
n’exclut pas un signal dans les familles équipe, calendrier, joueurs, tactique,
autres marchés ou futures données prospectives, qui n’ont pas été testées.

Le contrôle Bundesliga/Serie A est une stabilité inter-ligues exposée, pas un
holdout externe indépendant. Indépendamment du résultat, la classe
`SOURCE_PRICE_CLASS_ONLY` maintient le gate live fermé sans prix exact
observable.

Mise scientifique : 1 unité fixe. Bankroll : 1 000 unités fictives. Martingale,
pari réel et publication sociale sont interdits.

## Deep Matchup Research V1

| Famille | Statut | Motif |
|---|---|---|
| équipe/calendrier 11A | `DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC` | primaire sans gain, `TEAM_GATE=PARTIAL` |
| disponibilité joueurs 11B | `DATA_GATE_BLOCKED` | temporalité joueurs/absences |
| continuité lineup 11C | `DATA_GATE_BLOCKED` | lineups post-match |
| formations 11D | `DATA_GATE_BLOCKED` | cutoff pré-kickoff absent |
| hypothèses propriétaire 11E | `COMPLETED_AS_GATE_EVALUATION` | H11-001 à H11-008 bloquées individuellement |
| transfert équipe 11F | `DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC` | 5 rotations, 0 positive, 0 survivante |
| arène intégrée 11G | `DATA_GATE_BLOCKED` | B2–B4 indisponibles |

Le test principal 11A compare le marché + équipe multinomial au marché
recalibré train-only : Δ Log Loss `+0,001702211`, IC 95 %
`[-0,000242884 ; +0,003901782]`, q globale `1,0`. Les quatre challengers
team-only et le gradient boosting incrémental sont des diagnostics post-contrat
non promouvables.

Aucune règle de mise n'a été préenregistrée ; le ROI n'est donc pas calculé.
Zéro pattern rejoint `PROSPECTIVE_WATCHLIST` ou
`LIVE_SHADOW_CANDIDATE`. Zéro décision et zéro unité sont émises, la bankroll
shadow reste 1 000.

`PRODUCTION_LOCKED`, `REAL_BETS=false` et `NO_BET_DEFAULT=true` sont
obligatoires.
